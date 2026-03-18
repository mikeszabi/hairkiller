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

from camera_handler import UVCInterface
from detection_handler import ObjectDetector
from detection_utils import remove_overlapping_boxes, get_box_centers, detect_red_dot
from galvo_handler import GalvoInterface
from calibration_utils import (
    read_transformation_from_file,
    transform_to_mover_coordinates,
    calculate_homography,
    save_transformation_to_file,
)
from serial_devices_handler import SerialDevice
import threading

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# ==================== Laser Handler ====================
class LaserControlInterface:
    """Wrapper for laser serial protocol commands."""
    
    def __init__(self, port='/dev/ttyACM0', baud=115200, debug=False):
        self.device = SerialDevice(port=port, baud=baud, debug=debug)
        self.device.open()
        self.last_error = None
        print("[LASER] Interface initialized", flush=True)
    
    def _send_cmd(self, cmd: str):
        """Send command and return response."""
        try:
            response = self.device.query(cmd, wait_s=0.1)
            return response
        except Exception as e:
            self.last_error = str(e)
            print(f"[LASER] Command error: {e}", flush=True)
            return [f"ERROR: {e}"]
    
    def arm_laser(self):
        """ARM_LASER"""
        return self._send_cmd("ARM_LASER")
    
    def disarm_laser(self):
        """DISARM_LASER"""
        return self._send_cmd("DISARM_LASER")
    
    def ack_errors(self):
        """ACK_ERRORS"""
        return self._send_cmd("ACK_ERRORS")
    
    def set_laser_pwr(self, laser_id: int, pwr: int):
        """SET_LASER_PWR laser_id(1-4) pwr(1-100)"""
        pwr = max(1, min(100, pwr))
        return self._send_cmd(f"SET_LASER_PWR {laser_id},{pwr}")
    
    def set_active_lasers(self, l1064: int, l980: int, l808: int, l660: int):
        """SET_ACTIVE_LASERS 1,1,1,0"""
        return self._send_cmd(f"SET_ACTIVE_LASERS {int(bool(l1064))},{int(bool(l980))},{int(bool(l808))},{int(bool(l660))}")
    
    def set_las_curr(self, curr: int):
        """SET_LAS_CURR 1-100"""
        curr = max(1, min(100, curr))
        return self._send_cmd(f"SET_LAS_CURR {curr}")
    
    def set_las_pulse(self, pulse_ms: int):
        """SET_LAS_PULSE 1-1000"""
        pulse_ms = max(1, min(1000, pulse_ms))
        return self._send_cmd(f"SET_LAS_PULSE {pulse_ms}")
    
    def set_seq_length(self, length: int):
        """SET_SEQ_LENGTH 1-256"""
        length = max(1, min(256, length))
        return self._send_cmd(f"SET_SEQ_LENGTH {length}")
    
    def set_target_point(self, idx: int, x: int, y: int):
        """SET_TARGET_POINT idx,x,y"""
        idx = max(0, min(255, idx))
        x = max(0, min(4095, x))
        y = max(0, min(4095, y))
        return self._send_cmd(f"SET_TARGET_POINT {idx},{x},{y}")
    
    def start_seq(self):
        """START_SEQ"""
        return self._send_cmd("START_SEQ")
    
    def start_seq_test(self):
        """START_SEQ_TEST"""
        return self._send_cmd("START_SEQ_TEST")
    
    def stop_seq(self):
        """STOP_SEQ"""
        return self._send_cmd("STOP_SEQ")
    
    def halt_seq(self):
        """HALT_SEQ"""
        return self._send_cmd("HALT_SEQ")
    
    def resume_seq(self):
        """RESUME_SEQ"""
        return self._send_cmd("RESUME_SEQ")

    def get_laser_temp(self):
        """GET_LASER_TEMP"""
        return self._send_cmd("GET_LASER_TEMP")

# ==================== FastAPI App ====================
_galvo = GalvoInterface(debug=False)
_laser = None  # initialized on startup

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

# Calibration state
_calibration_points = []  # list of (image_pt, mover_pt) pairs
_red_dot_detection_enabled = False  # toggle for red dot overlay

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
    _laser = LaserControlInterface()
    print("[LASER] Interface initialized", flush=True)
except Exception as e:
    print(f"[LASER] Failed to initialize: {e}", flush=True)
    _laser = None


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
        
        _, jpeg = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
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
    mover_coord = transform_to_mover_coordinates((x, y), _homography)
    tx, ty = int(round(mover_coord[0])), int(round(mover_coord[1]))
    newpos = _galvo.move_2_pos(tx, ty)
    return {"image": [x, y], "target": [tx, ty], "new_position": newpos}


# ==================== Detection ====================
@app.post("/detection/toggle")
def toggle_detection(enabled: bool = Query(...)):
    global _hair_detection_enabled
    _hair_detection_enabled = enabled
    return {"detection_enabled": _hair_detection_enabled, "conf": _detection_conf}


@app.get("/detection/status")
def get_detection_status():
    return {"detection_enabled": _hair_detection_enabled, "conf": _detection_conf}


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


@app.post("/laser/pwr")
def set_laser_pwr(laser_id: int = Query(...), pwr: int = Query(...)):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_laser_pwr(laser_id, pwr)
    return {"response": resp}


@app.post("/laser/active")
def set_active_lasers(l1064: int = Query(1), l980: int = Query(1), l808: int = Query(1), l660: int = Query(0)):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_active_lasers(l1064, l980, l808, l660)
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


@app.post("/laser/pulse")
def set_las_pulse(pulse_ms: int = Query(...)):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_las_pulse(pulse_ms)
    return {"response": resp, "pulse_ms": pulse_ms}


# ==================== Sequence Control ====================
@app.post("/seq/length")
def set_seq_length(length: int = Query(...)):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_seq_length(length)
    return {"response": resp, "length": length}

# helper for front-end: convert image-space point to galvo coordinates
@app.get("/coords/convert")
def convert_image_to_galvo(ix: int = Query(...), iy: int = Query(...)):
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
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_target_point(idx, x, y)
    return {"response": resp, "idx": idx, "x": x, "y": y}


@app.post("/seq/start")
def start_seq():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.start_seq()
    return {"response": resp}


@app.post("/seq/start_test")
def start_seq_test():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.start_seq_test()
    return {"response": resp}


@app.post("/seq/stop")
def stop_seq():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.stop_seq()
    return {"response": resp}


@app.post("/seq/halt")
def halt_seq():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.halt_seq()
    return {"response": resp}


@app.post("/seq/resume")
def resume_seq():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.resume_seq()
    return {"response": resp}


# ==================== Fire Sequence with Detected Points ====================
@app.post("/fire/walk")
def fire_walk(test_mode: bool = Query(False)):
    """
    Convert detected image points to galvo coordinates, 
    set them as sequence targets, and fire.
    If test_mode=True, uses START_SEQ_TEST, else START_SEQ.
    """
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    
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
    _laser.set_seq_length(len(targets))
    
    # Set all targets
    for idx, x, y in targets:
        _laser.set_target_point(idx, x, y)
    
    # Start sequence
    if test_mode:
        resp = _laser.start_seq_test()
    else:
        resp = _laser.start_seq()
    
    return {
        "status": "firing",
        "test_mode": test_mode,
        "targets_count": len(targets),
        "response": resp
    }
