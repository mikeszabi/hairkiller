import sys
from pathlib import Path

# allow imports from top-level project folders like hk_app does
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "code"))

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import time
import cv2
import json

# hardware interfaces
from camera_handler import UVCInterface
from detection_utils import detect_red_dot
from galvo_handler import GalvoInterface
from laser_handler import LaserInterface
from calibration_utils import (
    calculate_homography,
    save_transformation_to_file,
    read_transformation_from_file,
    transform_to_mover_coordinates,
)

# create interfaces on startup (galvo initializes to 3000,3000)
_galvo = GalvoInterface(debug=False)
try:
    _laser = LaserInterface()
    print("[LASER] Interface initialized", flush=True)
except Exception as e:
    print("[LASER] Failed to initialize:", e, flush=True)
    _laser = None

app = FastAPI(title="hk_calibration_app")

# allow CORS from anywhere for ease of local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# global objects
_uvc = UVCInterface()
# we already created `_galvo` above using the SerialDevice wrapper
_calibration_points = []  # list of (image_pt, mover_pt) pairs
_detection_enabled = False  # toggle for automatic red dot detection on frames
_red_dot_enabled = False
_homography = None

# attempt to load the homography at startup
try:
    _homography = read_transformation_from_file()
    print("[HOMOGRAPHY] Loaded transformation matrix", flush=True)
except Exception as e:
    print("[HOMOGRAPHY] Could not load transformation matrix:", e, flush=True)
    _homography = None


def _response_has_enabled(lines) -> bool | None:
    """Best-effort boolean parser for ``...->1`` / ``...->0`` style replies."""
    if not isinstance(lines, list):
        return None
    for line in lines:
        text = str(line).strip()
        if text.endswith("->1") or text.endswith("[1]") or text.endswith(" 1"):
            return True
        if text.endswith("->0") or text.endswith("[0]") or text.endswith(" 0"):
            return False
    return None


def _generate_camera():
    """Stream frames from the camera as multipart JPEG.
    
    If detection is enabled, draw the detected red dot center on the frame.
    """
    last_idx = -1
    while True:
        frame, idx = _uvc.read()
        if frame is None:
            time.sleep(0.01)
            continue
        last_idx = idx

        # optionally perform detection and draw on frame
        if _detection_enabled:
            mask, center = detect_red_dot(frame)
            print(f"[DETECTION] Frame {idx}: Detected center at {center}", flush=True)
            if center is not None:
                x, y = center
                # draw large magenta circle
                cv2.circle(frame, (x, y), 25, (255, 0, 255), 3)
                # draw crosshairs in yellow
                cv2.line(frame, (x - 30, y), (x + 30, y), (0, 255, 255), 2)
                cv2.line(frame, (x, y - 30), (x, y + 30), (0, 255, 255), 2)
                # draw white text label
                cv2.putText(frame, f"({x}, {y})", (x + 35, y - 10),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        # small delay to avoid hogging CPU
        #time.sleep(0.03)


@app.get("/")
def root():
    return FileResponse(Path(__file__).with_name("hk_calibration_app.html"))


@app.post("/homography/reload")
def reload_homography():
    """Reload the homography matrix from the transformation file."""
    global _homography
    try:
        _homography = read_transformation_from_file()
        return {"status": "reloaded"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/health")
def health():
    frame, idx, captured_ts = _uvc.read_with_meta()
    ok = frame is not None
    return {
        "ok": ok,
        "camera_ready": ok,
        "laser_ready": _laser is not None,
        "galvo_ready": _galvo is not None,
        "homography_loaded": _homography is not None,
        "last_frame_index": idx,
        "frame_age_ms": None if captured_ts is None else (time.perf_counter() - captured_ts) * 1000.0,
    }


@app.get("/frame/meta")
def frame_meta():
    frame, idx, captured_ts = _uvc.read_with_meta()
    if frame is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "No frame available"})

    height, width = frame.shape[:2]
    return {
        "ok": True,
        "frame_index": idx,
        "width": width,
        "height": height,
        "frame_age_ms": None if captured_ts is None else (time.perf_counter() - captured_ts) * 1000.0,
    }


@app.get("/stats")
def stats():
    return {
        "ok": True,
        "camera": _uvc.get_stats(),
        "settings": _uvc.get_settings(),
        "detection_enabled": _detection_enabled,
        "red_dot_enabled": _red_dot_enabled,
        "homography_loaded": _homography is not None,
        "calibration_points": len(_calibration_points),
    }


@app.get("/frame/current")
def stream_video():
    return StreamingResponse(_generate_camera(),
                             media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/dot")
def read_dot():
    frame, _ = _uvc.read()
    if frame is None:
        return {"x": None, "y": None}
    mask, center = detect_red_dot(frame)
    if center is None:
        return {"x": None, "y": None}
    return {"x": int(center[0]), "y": int(center[1])}


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
                elif last_x is not None or last_y is not None:
                    last_x, last_y = None, None
                    data = json.dumps({"x": None, "y": None})
                    yield f"data: {data}\n\n"
            time.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/mover/pos")
def get_mover_pos():
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo interface unavailable"})
    x, y = _galvo.get_position()
    print(f"[GALVO POS] Reported: X={x}, Y={y}", flush=True)
    return {"x": x, "y": y}


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
            time.sleep(0.2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/laser/red_dot")
def set_red_dot(enabled: bool = Query(...)):
    global _red_dot_enabled
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser interface unavailable"})
    resp = _laser.set_red_dot(enabled)
    _red_dot_enabled = enabled
    return {"response": resp, "enabled": enabled}


@app.post("/laser/arm_en")
def set_laser_arm_enabled(enabled: bool = Query(...)):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser interface unavailable"})
    resp = _laser.set_arm_enabled(enabled)
    armed = _response_has_enabled(resp)
    return {"response": resp, "enabled": enabled, "armed": armed}


@app.get("/laser/arm_en")
def get_laser_arm_enabled():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser interface unavailable"})
    resp = _laser.get_arm_enabled()
    armed = _response_has_enabled(resp)
    return {"response": resp, "armed": armed}


@app.post("/laser/arm")
def arm_laser():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser interface unavailable"})
    resp = _laser.arm_laser()
    return {"response": resp}


@app.post("/laser/disarm")
def disarm_laser():
    global _red_dot_enabled
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser interface unavailable"})
    resp = _laser.disarm_laser()
    red_dot_resp = _laser.get_red_dot_enabled()
    parsed = _response_has_enabled(red_dot_resp)
    if parsed is not None:
        _red_dot_enabled = parsed
    return {"response": resp, "red_dot": _red_dot_enabled}


@app.post("/laser/red_dot_en")
def set_laser_red_dot_enabled(enabled: bool = Query(...)):
    return set_red_dot(enabled)


@app.get("/laser/red_dot_en")
def get_laser_red_dot_enabled():
    global _red_dot_enabled
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser interface unavailable"})
    resp = _laser.get_red_dot_enabled()
    parsed = _response_has_enabled(resp)
    if parsed is not None:
        _red_dot_enabled = parsed
    return {"response": resp, "enabled": _red_dot_enabled}


@app.post("/mover/move")
def move_to(x: int = Query(...), y: int = Query(...)):
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo interface unavailable"})
    print(f"[GALVO MOVE] Requested: X={x}, Y={y}", flush=True)
    newpos = _galvo.move_2_pos(x, y)
    print(f"[GALVO MOVE] Actual after move: X={newpos[0]}, Y={newpos[1]}", flush=True)
    return {"new_position": newpos}


@app.post("/mover/move_image")
def move_to_image(x: int = Query(...), y: int = Query(...)):
    """Transform the supplied image coordinates using the loaded homography
    and move the galvo to the resulting location."""
    global _homography
    if _homography is None:
        return JSONResponse(status_code=500, content={"error": "Homography not available"})
    # convert pixel coordinate -> mover coordinate
    mover_coord = transform_to_mover_coordinates((x, y), _homography)
    tx, ty = int(round(mover_coord[0])), int(round(mover_coord[1]))
    print(f"[HOMOGRAPHY MOVE] Image ({x},{y}) -> Target ({tx},{ty})", flush=True)
    newpos = _galvo.move_2_pos(tx, ty)
    print(f"[HOMOGRAPHY MOVE] Actual: {newpos}", flush=True)
    return {"image": [x, y], "target": [tx, ty], "new_position": newpos}


@app.post("/mover/direction")
def move_direction(direction: str = Query(...), step: int = Query(25)):
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo interface unavailable"})
    x, y = _galvo.get_position()
    print(f"[GALVO DIR] Current: X={x}, Y={y}, Direction={direction}, Step={step}", flush=True)
    if direction == "up":
        y += step
    elif direction == "down":
        y -= step
    elif direction == "left":
        x += step
    elif direction == "right":
        x -= step
    print(f"[GALVO DIR] Target: X={x}, Y={y}", flush=True)
    newpos = _galvo.move_2_pos(x, y)
    print(f"[GALVO DIR] Actual after move: X={newpos[0]}, Y={newpos[1]}", flush=True)
    return {"new_position": newpos}


@app.post("/detection/toggle")
def toggle_detection(enabled: bool = Query(...)):
    global _detection_enabled, _red_dot_enabled
    _detection_enabled = enabled
    # optionally turn on/off the physical red dot to aid visualization
    if _laser is not None:
        try:
            _laser.set_red_dot(enabled)
            globals()["_red_dot_enabled"] = enabled
        except Exception as e:
            print(f"[LASER] Red dot toggle failed: {e}", flush=True)
    print(f"[DETECTION] Toggled to: {_detection_enabled}", flush=True)
    return {"detection_enabled": _detection_enabled, "red_dot": _red_dot_enabled}


@app.post("/calibration/detection/toggle")
def toggle_calibration_detection(enabled: bool = Query(...)):
    """Compatibility route used by the calibration UI."""
    return toggle_detection(enabled)


@app.get("/detection/status")
def get_detection_status():
    return {"detection_enabled": _detection_enabled, "red_dot": _red_dot_enabled}


@app.post("/calibration/start")
def start_calibration():
    _calibration_points.clear()
    return {"status": "started"}


@app.post("/calibration/store")
def store_point():
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
def get_points():
    return {"points": _calibration_points}


@app.post("/calibration/save")
def save_calibration():
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
    print(f"[CALIB POINTS] Image points: {image_pts}", flush=True)
    print(f"[CALIB POINTS] Galvo points: {mover_pts}", flush=True)
    return {"status": "saved", "count": len(_calibration_points)}
