import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "code"))

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import time
import cv2
import logging
import json
from turbojpeg import TurboJPEG
from pydantic import BaseModel

from camera_handler import UVCInterface
from detection_handler import ObjectDetector
from detection_utils import remove_overlapping_boxes, get_box_centers, detect_red_dot
from galvo_handler import GalvoInterface
from laser_handler import LaserInterface
from target_handler import TargetInterface
from calibration_utils import (
    read_transformation_from_file,
    transform_to_mover_coordinates,
    calculate_homography,
    save_transformation_to_file,
)
import threading
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==================== FastAPI App ====================
_galvo = GalvoInterface(debug=False)
_laser = None  # initialized on startup
_target = None  # initialized once laser is available

app = FastAPI(title="hk_full_app")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
_uvc = UVCInterface()
_hair_detection_enabled = False
_detected_points = []
_homography = None
_walking = False
_detection_conf = 0.1
_current_target_image_pt = None
_last_detection_count = 0
_cam_frame_window = 0.25 # sec
_stream_w, _stream_h = 960, 960  # stream output resolution (native is 1920x1920)
_turbo = TurboJPEG()

# Calibration state
_calibration_points = []  # list of (image_pt, mover_pt) pairs
_red_dot_detection_enabled = False  # toggle for red dot overlay
_red_dot_enabled = False  # hardware red dot state
_app_error_events = deque(maxlen=25)
_app_error_lock = threading.Lock()
_sequence_events = deque(maxlen=25)
_sequence_lock = threading.Lock()
_test_events = deque(maxlen=25)
_test_lock = threading.Lock()

# Background inference optimization
_inference_cache = None
_inference_lock = threading.Lock()
_inference_thread = None

_detector = None
try:
    _detector = ObjectDetector("./model/follicle_exit_v11i_yolov8n_20250513.pt", device="cuda")
    print("[DETECTOR] Initialized", flush=True)
except Exception as e:
    print(f"[DETECTOR] Failed: {e}", flush=True)

try:
    _homography = read_transformation_from_file()
    print("[HOMOGRAPHY] Loaded", flush=True)
except Exception as e:
    print(f"[HOMOGRAPHY] Failed: {e}", flush=True)

# Initialize laser interface
try:
    _laser = LaserInterface()
    _target = TargetInterface(dev=_laser.dev, channel_provider=_laser.get_channel_power_triplet)
    print("[LASER] Interface initialized", flush=True)
except Exception as e:
    print(f"[LASER] Failed to initialize: {e}", flush=True)
    _laser = None
    _target = None


def _background_inference_worker():
    """Background thread that continuously runs YOLO inference and updates cache."""
    global _inference_cache
    print("[INFERENCE THREAD] Started", flush=True)
    
    while True:
        if not _hair_detection_enabled or _detector is None:
            time.sleep(0.1)
            continue
        
        frame, _ = _uvc.read()
        if frame is None:
            time.sleep(0.01)
            continue
        
        try:
            boxes_with_scores = _detector.split_inference(frame, conf=_detection_conf)
            if len(boxes_with_scores) > 0:
                boxes_distinct = remove_overlapping_boxes(boxes_with_scores)
                centers = get_box_centers(boxes_distinct)
                
                with _inference_lock:
                    _inference_cache = {
                        'boxes': boxes_distinct,
                        'centers': centers,
                        'count': len(centers)
                    }
            else:
                with _inference_lock:
                    _inference_cache = {'boxes': [], 'centers': [], 'count': 0}
        except Exception as e:
            print(f"[INFERENCE THREAD] Error: {e}", flush=True)
            time.sleep(0.1)


# Start background inference thread
_inference_thread = threading.Thread(target=_background_inference_worker, daemon=True)
_inference_thread.start()
print("[INFERENCE THREAD] Background worker started", flush=True)


class RawCommandRequest(BaseModel):
    command: str


def _record_app_error_event(raw_message: str) -> None:
    message = str(raw_message).strip()
    if not message:
        return

    if "APP_HARD_FAULT_HAPPENED" in message:
        level = "hard_fault"
    elif "APP_ERROR_HAPPENED" in message:
        level = "error"
    else:
        return

    event = {
        "level": level,
        "message": message,
        "timestamp": int(time.time() * 1000),
    }
    with _app_error_lock:
        _app_error_events.appendleft(event)


def _record_sequence_event(raw_message: str) -> None:
    message = str(raw_message).strip()
    if not message or "TARGET_SEQ_FINISHED" not in message:
        return

    status = "unknown"
    if "->" in message:
        payload = message.split("->", 1)[1].strip().strip("[]")
        if payload:
            status = payload.split(",", 1)[0].strip() or "unknown"

    event = {
        "status": status,
        "message": message,
        "timestamp": int(time.time() * 1000),
    }
    with _sequence_lock:
        _sequence_events.appendleft(event)


def _record_test_event(raw_message: str) -> None:
    message = str(raw_message).strip()
    if not message:
        return

    if "APP_WATCHDOG_TRIGGERED" in message:
        kind = "watchdog"
        status = "triggered"
    elif "APP_LASER_PWR_TEST_FINISHED" in message:
        kind = "laser_power_test"
        status = "unknown"
        if "->" in message:
            payload = message.split("->", 1)[1].strip().strip("[]")
            if payload:
                status = payload.split(",", 1)[0].strip() or "unknown"
    else:
        return

    event = {
        "kind": kind,
        "status": status,
        "message": message,
        "timestamp": int(time.time() * 1000),
    }
    with _test_lock:
        _test_events.appendleft(event)


def _drain_async_messages() -> None:
    if _laser is None:
        return
    for raw_message in _laser.pop_async_messages():
        if "APP_ERROR_HAPPENED" in raw_message or "APP_HARD_FAULT_HAPPENED" in raw_message:
            _record_app_error_event(raw_message)
        if "TARGET_SEQ_FINISHED" in raw_message:
            _record_sequence_event(raw_message)
        if "APP_WATCHDOG_TRIGGERED" in raw_message or "APP_LASER_PWR_TEST_FINISHED" in raw_message:
            _record_test_event(raw_message)


def _generate_camera():
    """Stream frames with detection overlay and target crosshair."""
    global _last_detection_count
    last_sent_idx = -1
    
    while True:
        frame, idx = _uvc.read()
        if frame is None or idx == last_sent_idx:
            time.sleep(0.01)
            continue
        last_sent_idx = idx
        
        # Hair detection overlay (from cached results)
        current_count = 0
        if _hair_detection_enabled:
            with _inference_lock:
                cache = _inference_cache
            
            if cache is not None:
                current_count = cache['count']
                for box in cache['boxes']:
                    x1, y1, x2, y2 = [int(v) for v in box[:4]]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                
                for cx, cy in cache['centers']:
                    cv2.circle(frame, (int(cx), int(cy)), 5, (0, 255, 255), -1)
                    cv2.putText(frame, f"({int(cx)},{int(cy)})", (int(cx)+10, int(cy)-10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
        
        # Red dot detection overlay (for calibration)
        if _red_dot_detection_enabled:
            try:
                _, center = detect_red_dot(frame)
                if center is not None:
                    x, y = center
                    cv2.circle(frame, (x, y), 25, (255, 0, 255), 3)
                    cv2.line(frame, (x - 30, y), (x + 30, y), (0, 255, 255), 2)
                    cv2.line(frame, (x, y - 30), (x, y + 30), (0, 255, 255), 2)
                    cv2.putText(frame, f"({x}, {y})", (x + 35, y - 10),
                               cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            except Exception as e:
                print(f"[RED DOT] Error: {e}", flush=True)
        
        # Update detection count
        if current_count != _last_detection_count:
            _last_detection_count = current_count
        
        # Target crosshair
        if _current_target_image_pt is not None:
            tx, ty = int(_current_target_image_pt[0]), int(_current_target_image_pt[1])
            cv2.line(frame, (tx - 40, ty), (tx + 40, ty), (0, 0, 255), 2)
            cv2.line(frame, (tx, ty - 40), (tx, ty + 40), (0, 0, 255), 2)
            cv2.circle(frame, (tx, ty), 8, (0, 0, 255), 2)
            cv2.putText(frame, "TARGET", (tx + 15, ty - 15),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        
        small = cv2.resize(frame, (_stream_w, _stream_h))
        buf = _turbo.encode(small, quality=70)
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf + b'\r\n'
        time.sleep(_cam_frame_window)


# ==================== Video Stream ====================
@app.get("/frame/current")
def stream_video():
    return StreamingResponse(_generate_camera(),
                             media_type="multipart/x-mixed-replace; boundary=frame")


# ==================== SSE for Detection Count ====================
@app.get("/sse/detection")
def sse_detection():
    """Server-Sent Events endpoint for real-time detection count updates."""
    def event_stream():
        last_sent_count = -1
        while True:
            current_count = _last_detection_count
            if current_count != last_sent_count:
                last_sent_count = current_count
                data = json.dumps({"type": "detection_count", "count": current_count})
                yield f"data: {data}\n\n"
            time.sleep(0.1)  # Check every 100ms
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/app/errors")
def get_app_errors():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})

    _drain_async_messages()

    app_state = _laser.get_app_state()
    app_last_error = _laser.get_app_last_error()

    with _app_error_lock:
        events = list(_app_error_events)

    return {
        "state": app_state,
        "last_error": app_last_error,
        "events": events,
    }


@app.get("/app/errors/events")
def get_app_error_events():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})

    _drain_async_messages()

    with _app_error_lock:
        events = list(_app_error_events)

    return {"events": events}


@app.post("/app/errors/clear")
def clear_app_errors():
    global _red_dot_enabled
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})

    resp = _laser.clear_app_error()
    _red_dot_enabled = False
    _drain_async_messages()

    with _app_error_lock:
        _app_error_events.clear()

    return {"response": resp}


@app.get("/app/test/status")
def get_app_test_status():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})

    _drain_async_messages()

    with _test_lock:
        events = list(_test_events)

    return {
        "state": _laser.get_app_state(),
        "last_error": _laser.get_app_last_error(),
        "laser_test_result": _laser.get_laser_test_result(),
        "fw_version": _laser.get_fw_version(),
        "hw_version": _laser.get_hw_version(),
        "proc_time": _laser.get_app_proc_time(),
        "events": events,
    }


@app.get("/app/test/events")
def get_app_test_events():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})

    _drain_async_messages()

    with _test_lock:
        events = list(_test_events)

    return {"events": events}


@app.post("/app/ping")
def app_ping():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.app_ping()}


@app.get("/app/commands")
def get_app_commands():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.get_app_commands()}


@app.get("/app/limits")
def get_app_limits():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.get_app_limits()}


@app.post("/app/reset")
def app_reset():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.app_reset()}


@app.get("/app/proc_time")
def get_app_proc_time():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.get_app_proc_time()}


@app.post("/app/laser_test/start")
def start_app_laser_power_test():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.do_laser_power_test()}


@app.get("/app/laser_test/result")
def get_app_laser_test_result():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.get_laser_test_result()}


@app.get("/app/laser_test/data")
def get_app_laser_test_data():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.get_laser_test_data()}


@app.get("/app/fw_version")
def get_app_fw_version():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.get_fw_version()}


@app.get("/app/hw_version")
def get_app_hw_version():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.get_hw_version()}


@app.get("/app/state")
def get_app_state():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.get_app_state()}


@app.get("/app/last_error")
def get_app_last_error():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    return {"response": _laser.get_app_last_error()}


@app.post("/app/clear_error")
def clear_app_last_error():
    global _red_dot_enabled
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.clear_app_error()
    _red_dot_enabled = False
    return {"response": resp}


@app.post("/app/raw_command")
def app_raw_command(payload: RawCommandRequest):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})

    command = str(payload.command).strip()
    if not command:
        return JSONResponse(status_code=400, content={"error": "Command is empty"})

    response = _laser.send_raw_command(command)
    _drain_async_messages()
    return {"command": command, "response": response}


@app.get("/seq/status")
def get_sequence_status():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})

    _drain_async_messages()
    state = _target.get_state()
    last_error = _target.get_last_error()

    with _sequence_lock:
        events = list(_sequence_events)

    return {
        "state": state,
        "last_error": last_error,
        "events": events,
    }


@app.get("/seq/events")
def get_sequence_events():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})

    _drain_async_messages()

    with _sequence_lock:
        events = list(_sequence_events)

    return {"events": events}


@app.get("/sse/galvo_pos")
def sse_galvo_pos():
    """Server-Sent Events endpoint for real-time galvo position updates."""
    def event_stream():
        last_x, last_y = None, None
        while True:
            if _galvo is not None:
                x, y = _galvo.get_position()
                if x != last_x or y != last_y:
                    last_x, last_y = x, y
                    data = json.dumps({"x": x, "y": y})
                    yield f"data: {data}\n\n"
            time.sleep(0.2)  # Check every 200ms
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/sse/dot")
def sse_dot():
    """Server-Sent Events endpoint for real-time red dot position updates."""
    def event_stream():
        last_x, last_y = None, None
        while True:
            frame, _ = _uvc.read()
            if frame is not None:
                _, center = detect_red_dot(frame)
                if center is not None:
                    x, y = int(center[0]), int(center[1])
                    if x != last_x or y != last_y:
                        last_x, last_y = x, y
                        data = json.dumps({"x": x, "y": y})
                        yield f"data: {data}\n\n"
                else:
                    if last_x is not None or last_y is not None:
                        last_x, last_y = None, None
                        data = json.dumps({"x": None, "y": None})
                        yield f"data: {data}\n\n"
            time.sleep(0.5)  # Check every 500ms
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ==================== Galvo Control ====================
@app.get("/mover/pos")
def get_mover_pos():
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo unavailable"})
    x, y = _galvo.get_position()
    return {"x": x, "y": y}


@app.post("/mover/move")
def move_to(x: int = Query(...), y: int = Query(...)):
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo unavailable"})
    newpos = _galvo.move_2_pos(x, y)
    return {"new_position": newpos}


@app.post("/mover/direction")
def move_direction(direction: str = Query(...), step: int = Query(25)):
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo unavailable"})
    x, y = _galvo.get_position()
    if direction == "up":
        y -= step
    elif direction == "down":
        y += step
    elif direction == "left":
        x -= step
    elif direction == "right":
        x += step
    newpos = _galvo.move_2_pos(x, y)
    return {"new_position": newpos}


@app.post("/mover/move_image")
def move_to_image(x: int = Query(...), y: int = Query(...)):
    """Transform the supplied image coordinates using the loaded homography
    and move the galvo to the resulting location."""
    global _homography
    if _homography is None:
        return JSONResponse(status_code=500, content={"error": "Homography not available"})
    # Scale stream coords back to native resolution (stream is _stream_w x _stream_h, native is 1920x1920)
    native_x = int(round(x * 1920 / _stream_w))
    native_y = int(round(y * 1920 / _stream_h))
    mover_coord = transform_to_mover_coordinates((native_x, native_y), _homography)
    tx, ty = int(round(mover_coord[0])), int(round(mover_coord[1]))
    newpos = _galvo.move_2_pos(tx, ty)
    return {"image": [x, y], "native_image": [native_x, native_y], "target": [tx, ty], "new_position": newpos}


# ==================== Detection ====================
@app.post("/detection/toggle")
def toggle_detection(enabled: bool = Query(...)):
    global _hair_detection_enabled
    _hair_detection_enabled = enabled
    return {"detection_enabled": _hair_detection_enabled, "conf": _detection_conf}


@app.get("/detection/status")
def get_detection_status():
    return {"detection_enabled": _hair_detection_enabled, "conf": _detection_conf, "red_dot": _red_dot_enabled}


@app.post("/detection/conf")
def set_detection_conf(conf: float = Query(...)):
    global _detection_conf
    try:
        conf_val = float(conf)
        conf_val = max(0.01, min(1.0, conf_val))
        _detection_conf = conf_val
        return {"conf": _detection_conf}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.post("/detection/capture")
def capture_detections():
    global _detected_points
    if _detector is None:
        return JSONResponse(status_code=500, content={"error": "Detector unavailable"})
    
    frame, _ = _uvc.read()
    if frame is None:
        return JSONResponse(status_code=500, content={"error": "Could not read frame"})
    
    try:
        boxes_with_scores = _detector.split_inference(frame, conf=_detection_conf)
        if len(boxes_with_scores) == 0:
            return {"captured": 0, "points": []}
        
        boxes_distinct = remove_overlapping_boxes(boxes_with_scores)
        centers = get_box_centers(boxes_distinct)
        _detected_points = [(int(cx), int(cy)) for cx, cy in centers]
        #print(f"[CAPTURE] Detected points: {_detected_points}", flush=True)
        
        return {"captured": len(_detected_points), "points": _detected_points}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/points/list")
def get_detected_points():
    return {"points": _detected_points, "count": len(_detected_points)}


@app.post("/points/clear")
def clear_detected_points():
    global _detected_points
    _detected_points = []
    return {"status": "cleared"}


# ==================== Calibration ====================
@app.get("/dot")
def read_dot():
    """Get red dot position from current frame."""
    frame, _ = _uvc.read()
    if frame is None:
        return {"x": None, "y": None}
    _, center = detect_red_dot(frame)
    if center is None:
        return {"x": None, "y": None}
    return {"x": int(center[0]), "y": int(center[1])}


@app.post("/calibration/detection/toggle")
def toggle_red_dot_detection(enabled: bool = Query(...)):
    """Toggle red dot detection overlay (for calibration)."""
    global _red_dot_detection_enabled
    _red_dot_detection_enabled = enabled
    return {"red_dot_detection_enabled": _red_dot_detection_enabled}


@app.get("/calibration/detection/status")
def get_red_dot_detection_status():
    return {"red_dot_detection_enabled": _red_dot_detection_enabled}


@app.post("/calibration/start")
def start_calibration():
    """Clear calibration points to start fresh."""
    _calibration_points.clear()
    return {"status": "started"}


@app.post("/calibration/store")
def store_calibration_point():
    """Store current red dot position + galvo position as calibration pair."""
    frame, _ = _uvc.read()
    pos = _galvo.get_position() if _galvo is not None else (None, None)
    center = None
    if frame is not None:
        _, center = detect_red_dot(frame)
    if center is not None and pos is not None:
        _calibration_points.append(((int(center[0]), int(center[1])), (pos[0], pos[1])))
        print(f"[CALIB STORE] Point #{len(_calibration_points)}: Image=({int(center[0])}, {int(center[1])})  Galvo=({pos[0]}, {pos[1]})", flush=True)
    else:
        print(f"[CALIB STORE] FAILED - Center={center}, Pos={pos}", flush=True)
    return {"stored": len(_calibration_points)}


@app.get("/calibration/points")
def get_calibration_points():
    """Return all stored calibration point pairs."""
    return {"points": _calibration_points}


@app.post("/calibration/save")
def save_calibration():
    """Calculate homography from stored points and save to file."""
    if len(_calibration_points) < 4:
        print(f"[CALIB SAVE] Not enough points: {len(_calibration_points)} < 4", flush=True)
        return {"status": "need_more_points", "count": len(_calibration_points)}
    print(f"[CALIB SAVE] Computing homography with {len(_calibration_points)} points", flush=True)
    image_pts = [p[0] for p in _calibration_points]
    mover_pts = [p[1] for p in _calibration_points]
    H = calculate_homography(image_pts, mover_pts)
    save_transformation_to_file(H)
    with open("saved_coordinates.json", "w") as f:
        json.dump(_calibration_points, f)
    print(f"[CALIB SAVE] Homography saved to transformation_matrix.txt", flush=True)
    return {"status": "saved", "count": len(_calibration_points)}


@app.post("/homography/reload")
def reload_homography():
    """Reload the homography matrix from the transformation file."""
    global _homography
    try:
        _homography = read_transformation_from_file()
        return {"status": "reloaded"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ==================== Walking ====================
def _nearest_neighbor_tsp(points):
    """Simple nearest-neighbor TSP approximation."""
    if not points:
        return []
    if len(points) == 1:
        return points
    
    unvisited = set(range(len(points)))
    current_idx = 0
    path = [0]
    unvisited.remove(0)
    
    while unvisited:
        current = points[current_idx]
        nearest_idx = min(unvisited, key=lambda i: (points[i][0] - current[0])**2 + (points[i][1] - current[1])**2)
        path.append(nearest_idx)
        unvisited.remove(nearest_idx)
        current_idx = nearest_idx
    
    return [points[i] for i in path]


@app.post("/walk/start")
def start_walking():
    global _walking, _current_target_image_pt
    
    if not _detected_points:
        return JSONResponse(status_code=400, content={"error": "No points"})
    
    if _homography is None:
        return JSONResponse(status_code=400, content={"error": "Homography unavailable"})
    
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo unavailable"})
    
    _walking = True
    optimized_image_points = _nearest_neighbor_tsp(_detected_points)
    
    galvo_points = []
    for img_pt in optimized_image_points:
        try:
            galvo_coord = transform_to_mover_coordinates(img_pt, _homography)
            tx, ty = int(round(galvo_coord[0])), int(round(galvo_coord[1]))
            galvo_points.append((tx, ty))
        except Exception as e:
            print(f"[WALK] Transform error: {e}", flush=True)
    
    visited = []
    for i, (tx, ty) in enumerate(galvo_points):
        if not _walking:
            break
        
        _current_target_image_pt = optimized_image_points[i]
        newpos = _galvo.move_2_pos(tx, ty)
        visited.append({"target": [tx, ty], "actual": newpos})
        time.sleep(0.1)
    
    _walking = False
    _current_target_image_pt = None
    return {"status": "completed", "visited": visited}


@app.post("/walk/stop")
def stop_walking():
    global _walking
    _walking = False
    return {"status": "stopped"}


# ==================== Laser Control ====================
@app.post("/laser/arm_en")
def set_laser_arm_enabled(enabled: bool = Query(...)):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_arm_enabled(enabled)
    return {"response": resp, "enabled": enabled}


@app.get("/laser/arm_en")
def get_laser_arm_enabled():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.get_arm_enabled()
    return {"response": resp}


@app.post("/laser/arm")
def arm_laser():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.arm_laser()
    return {"response": resp}


@app.post("/laser/disarm")
def disarm_laser():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.disarm_laser()
    return {"response": resp}


@app.post("/laser/ack")
def ack_errors():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.ack_errors()
    return {"response": resp}


@app.post("/laser/clear_error")
def clear_laser_error():
    global _red_dot_enabled
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.clear_error()
    _red_dot_enabled = False
    return {"response": resp}


@app.get("/laser/last_error")
def get_laser_last_error():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.get_last_error()
    return {"response": resp}


@app.post("/laser/pwr")
def set_laser_pwr(laser_id: int = Query(...), pwr: int = Query(...)):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_laser_pwr(laser_id, pwr)
    return {"response": resp}


@app.post("/laser/channel_pwr")
def set_laser_channel_power(
    p808: int = Query(...),
    p980: int = Query(...),
    p1064: int = Query(...),
):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_channel_power(p808, p980, p1064)
    return {"response": resp, "power": {"p808": p808, "p980": p980, "p1064": p1064}}


@app.get("/laser/channel_pwr")
def get_laser_channel_power():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.get_channel_power()
    return {"response": resp}


@app.post("/laser/active")
def set_active_lasers(l1064: int = Query(1), l980: int = Query(1), l808: int = Query(1), l660: int = Query(0)):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_active_lasers(l1064, l980, l808, l660)
    if l660 is not None:
        global _red_dot_enabled
        _red_dot_enabled = bool(l660)
    return {"response": resp, "active": [bool(l1064), bool(l980), bool(l808), bool(l660)]}


@app.post("/laser/current")
def set_las_curr(curr: int = Query(...)):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_las_curr(curr)
    return {"response": resp, "current": curr}


@app.get("/laser/temp")
def get_laser_temp():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.get_laser_temp()
    raw = resp[0] if isinstance(resp, list) and len(resp) > 0 else str(resp)
    if raw.startswith("ERR:"):
        msg = raw[4:].strip()
        return JSONResponse(status_code=500, content={"error": msg})
    return {"temp": raw}


@app.get("/sensors/values")
def get_sensor_values():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.get_sensor_values()
    values = resp.get("values")
    if values is None:
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to parse sensor values", "raw": resp.get("raw", [])},
        )
    return {"values": values, "raw": resp.get("raw", [])}


@app.post("/laser/pulse")
def set_las_pulse(pulse_ms: int = Query(...)):
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    resp = _target.set_las_pulse(pulse_ms)
    return {"response": resp, "pulse_ms": pulse_ms}


@app.post("/laser/red_dot")
def set_red_dot(enabled: bool = Query(...)):
    global _red_dot_enabled
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_red_dot(enabled)
    _red_dot_enabled = enabled
    return {"response": resp, "enabled": enabled}


@app.post("/laser/red_dot_en")
def set_laser_red_dot_enabled(enabled: bool = Query(...)):
    global _red_dot_enabled
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_red_dot(enabled)
    _red_dot_enabled = enabled
    return {"response": resp, "enabled": enabled}


@app.get("/laser/red_dot_en")
def get_laser_red_dot_enabled():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.get_red_dot_enabled()
    return {"response": resp}


@app.post("/laser/fire")
def fire_laser(duration_ms: int = Query(...)):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.fire(duration_ms)
    return {"response": resp, "duration_ms": duration_ms}


@app.post("/laser/stop")
def stop_laser():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.stop()
    return {"response": resp}


@app.get("/laser/is_active")
def get_laser_is_active():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.is_active()
    return {"response": resp}


@app.get("/laser/state")
def get_laser_state():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.get_state()
    return {"response": resp}


# ==================== Sequence Control ====================
@app.post("/seq/length")
def set_seq_length(length: int = Query(...)):
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    resp = _target.set_seq_length(length)
    return {"response": resp, "length": length}

# helper for front-end: convert image-space point to galvo coordinates
@app.get("/coords/convert")
def convert_image_to_galvo(ix: int = Query(...), iy: int = Query(...)):
    global _homography
    if _homography is None:
        return JSONResponse(status_code=400, content={"error": "Homography unavailable"})
    try:
        galvo_coord = transform_to_mover_coordinates((ix, iy), _homography)
        tx, ty = int(round(galvo_coord[0])), int(round(galvo_coord[1]))
        return {"x": tx, "y": ty}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/seq/target")
def set_target_point(idx: int = Query(...), x: int = Query(...), y: int = Query(...)):
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    resp = _target.set_target_point(idx, x, y)
    return {"response": resp, "idx": idx, "x": x, "y": y}


@app.post("/seq/start")
def start_seq():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    resp = _target.start_seq()
    return {"response": resp}


@app.post("/seq/start_test")
def start_seq_test():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    resp = _target.start_seq_test()
    return {"response": resp}


@app.post("/seq/stop")
def stop_seq():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    resp = _target.stop_seq()
    return {"response": resp}


@app.post("/seq/halt")
def halt_seq():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    resp = _target.halt_seq()
    return {"response": resp}


@app.post("/seq/resume")
def resume_seq():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    resp = _target.resume_seq()
    return {"response": resp}


# ==================== Fire Sequence with Detected Points ====================
@app.post("/fire/walk")
def fire_walk(test_mode: bool = Query(False)):
    """
    Convert detected image points to galvo coordinates, 
    set them as sequence targets, and fire.
    If test_mode=True, uses START_SEQ_TEST, else START_SEQ.
    """
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    
    if not _detected_points:
        return JSONResponse(status_code=400, content={"error": "No points"})
    
    if _homography is None:
        return JSONResponse(status_code=400, content={"error": "Homography unavailable"})
    
    # Optimize path
    optimized_image_points = _nearest_neighbor_tsp(_detected_points)
    
    # Transform to galvo and set targets
    targets = []
    for i, img_pt in enumerate(optimized_image_points):
        try:
            galvo_coord = transform_to_mover_coordinates(img_pt, _homography)
            tx, ty = int(round(galvo_coord[0])), int(round(galvo_coord[1]))
            targets.append((i, tx, ty))
        except Exception as e:
            print(f"[FIRE] Transform error: {e}", flush=True)
    
    # Set sequence length
    _target.set_seq_length(len(targets))
    
    # Set all targets
    for idx, x, y in targets:
        _target.set_target_point(idx, x, y)
    
    # Start sequence
    if test_mode:
        resp = _target.start_seq_test()
    else:
        resp = _target.start_seq()
    
    return {
        "status": "firing",
        "test_mode": test_mode,
        "targets_count": len(targets),
        "response": resp
    }
