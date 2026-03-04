import sys
from pathlib import Path

# allow imports from top-level project folders like hk_app does
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "code"))

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import time
import cv2
import json

# hardware interfaces
from camera_handler import UVCInterface
from detection_utils import detect_red_dot
from galvo_handler import GalvoInterface
from calibration_utils import (
    calculate_homography,
    save_transformation_to_file,
    read_transformation_from_file,
    transform_to_mover_coordinates,
)

# create galvo interface on startup (initializes to 3000,3000)
_galvo = GalvoInterface(debug=False)

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
_homography = None

# attempt to load the homography at startup
try:
    _homography = read_transformation_from_file()
    print("[HOMOGRAPHY] Loaded transformation matrix", flush=True)
except Exception as e:
    print("[HOMOGRAPHY] Could not load transformation matrix:", e, flush=True)
    _homography = None


def _generate_camera():
    """Stream frames from the camera as multipart JPEG.
    
    If detection is enabled, draw the detected red dot center on the frame.
    """
    while True:
        frame, idx = _uvc.read()
        if frame is None:
            time.sleep(0.01)
            continue
        
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
        
        _, jpeg = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        # small delay to avoid hogging CPU
        time.sleep(0.03)


@app.post("/homography/reload")
def reload_homography():
    """Reload the homography matrix from the transformation file."""
    global _homography
    try:
        _homography = read_transformation_from_file()
        return {"status": "reloaded"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


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


@app.get("/mover/pos")
def get_mover_pos():
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo interface unavailable"})
    x, y = _galvo.get_position()
    print(f"[GALVO POS] Reported: X={x}, Y={y}", flush=True)
    return {"x": x, "y": y}


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
        y -= step
    elif direction == "down":
        y += step
    elif direction == "left":
        x -= step
    elif direction == "right":
        x += step
    print(f"[GALVO DIR] Target: X={x}, Y={y}", flush=True)
    newpos = _galvo.move_2_pos(x, y)
    print(f"[GALVO DIR] Actual after move: X={newpos[0]}, Y={newpos[1]}", flush=True)
    return {"new_position": newpos}


@app.post("/detection/toggle")
def toggle_detection(enabled: bool = Query(...)):
    global _detection_enabled
    _detection_enabled = enabled
    print(f"[DETECTION] Toggled to: {_detection_enabled}", flush=True)
    return {"detection_enabled": _detection_enabled}


@app.get("/detection/status")
def get_detection_status():
    return {"detection_enabled": _detection_enabled}


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
