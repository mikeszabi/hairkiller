import sys
from pathlib import Path

# allow imports from top-level project folders
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "code"))

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import time
import cv2
import json
import logging

# hardware interfaces
from camera_handler import UVCInterface
from detection_handler import ObjectDetector
from detection_utils import remove_overlapping_boxes, get_box_centers
from galvo_handler import GalvoInterface
from calibration_utils import (
    read_transformation_from_file,
    transform_to_mover_coordinates,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# create galvo interface on startup (initializes to 3000,3000)
_galvo = GalvoInterface(debug=False)

app = FastAPI(title="hk_hair_walk_app")

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
_hair_detection_enabled = False
_detected_points = []  # list of (image_x, image_y) tuples
_homography = None
_walking = False
_detection_conf = 0.1  # default confidence for split_inference
_current_target_image_pt = None  # current target in image coords (for crosshair)

# initialize detector
try:
    _detector = ObjectDetector("./model/follicle_exit_v11i_yolov8n_20250513.pt", device="cuda")
    print("[DETECTOR] Initialized ObjectDetector", flush=True)
except Exception as e:
    print(f"[DETECTOR] Failed to initialize: {e}", flush=True)
    _detector = None

# attempt to load the homography at startup
try:
    _homography = read_transformation_from_file()
    print("[HOMOGRAPHY] Loaded transformation matrix", flush=True)
except Exception as e:
    print("[HOMOGRAPHY] Could not load transformation matrix:", e, flush=True)
    _homography = None


def _generate_camera():
    """Stream frames from the camera as multipart JPEG.
    
    If detection is enabled, draw detected follicles on the frame.
    """
    while True:
        frame, idx = _uvc.read()
        if frame is None:
            time.sleep(0.01)
            continue
        
        # optionally perform detection and draw on frame
        if _hair_detection_enabled and _detector is not None:
            try:
                boxes_with_scores = _detector.split_inference(frame, conf=_detection_conf)
                if len(boxes_with_scores) > 0:
                    boxes_distinct = remove_overlapping_boxes(boxes_with_scores)
                    centers = get_box_centers(boxes_distinct)

                    # draw boxes and centers
                    for box in boxes_distinct:
                        x1, y1, x2, y2 = [int(v) for v in box[:4]]
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                    for cx, cy in centers:
                        cv2.circle(frame, (int(cx), int(cy)), 5, (0, 255, 255), -1)
                        cv2.putText(frame, f"({int(cx)},{int(cy)})", (int(cx)+10, int(cy)-10),
                                   cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)

                    print(f"[DETECTION] Frame {idx}: {len(centers)} follicles detected", flush=True)
            except Exception as e:
                print(f"[DETECTION] Error: {e}", flush=True)
        
        # draw crosshair at current target position during walk
        if _current_target_image_pt is not None:
            tx, ty = int(_current_target_image_pt[0]), int(_current_target_image_pt[1])
            # draw large red crosshair
            cv2.line(frame, (tx - 40, ty), (tx + 40, ty), (0, 0, 255), 2)
            cv2.line(frame, (tx, ty - 40), (tx, ty + 40), (0, 0, 255), 2)
            cv2.circle(frame, (tx, ty), 8, (0, 0, 255), 2)
            cv2.putText(frame, "TARGET", (tx + 15, ty - 15),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        
        _, jpeg = cv2.imencode('.jpg', frame)
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + jpeg.tobytes() + b'\r\n')
        time.sleep(0.03)


@app.get("/frame/current")
def stream_video():
    return StreamingResponse(_generate_camera(),
                             media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/mover/pos")
def get_mover_pos():
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo interface unavailable"})
    x, y = _galvo.get_position()
    print(f"[GALVO POS] X={x}, Y={y}", flush=True)
    return {"x": x, "y": y}


@app.post("/mover/move")
def move_to(x: int = Query(...), y: int = Query(...)):
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo interface unavailable"})
    print(f"[GALVO MOVE] Target: X={x}, Y={y}", flush=True)
    newpos = _galvo.move_2_pos(x, y)
    print(f"[GALVO MOVE] Actual: X={newpos[0]}, Y={newpos[1]}", flush=True)
    return {"new_position": newpos}


@app.post("/detection/capture")
def capture_detections():
    """Capture one frame and detect all follicles, store in the points list."""
    global _detected_points
    if _detector is None:
        return JSONResponse(status_code=500, content={"error": "Detector not initialized"})
    
    frame, _ = _uvc.read()
    if frame is None:
        return JSONResponse(status_code=500, content={"error": "Could not read frame"})
    
    try:
        boxes_with_scores = _detector.split_inference(frame, conf=_detection_conf)
        if len(boxes_with_scores) == 0:
            return {"captured": 0, "points": []}
        
        boxes_distinct = remove_overlapping_boxes(boxes_with_scores)
        centers = get_box_centers(boxes_distinct)
        
        # store as (x, y) tuples
        _detected_points = [(int(cx), int(cy)) for cx, cy in centers]
        print(f"[CAPTURE] Captured {len(_detected_points)} follicles", flush=True)
        return {"captured": len(_detected_points), "points": _detected_points}
    except Exception as e:
        print(f"[CAPTURE] Error: {e}", flush=True)
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/detection/toggle")
def toggle_detection(enabled: bool = Query(...)):
    global _hair_detection_enabled
    _hair_detection_enabled = enabled
    print(f"[DETECTION] Toggled to: {_hair_detection_enabled}", flush=True)
    return {"detection_enabled": _hair_detection_enabled, "conf": _detection_conf}


@app.get("/detection/status")
def get_detection_status():
    return {"detection_enabled": _hair_detection_enabled, "conf": _detection_conf}


@app.post("/detection/conf")
def set_detection_conf(conf: float = Query(...)):
    """Set detection confidence used by split_inference (clamped).

    Expects a float between 0.01 and 1.0 (we'll clamp).
    """
    global _detection_conf
    try:
        # Clamp to sensible range
        conf_val = float(conf)
        if conf_val < 0.01:
            conf_val = 0.01
        if conf_val > 1.0:
            conf_val = 1.0
        _detection_conf = conf_val
        print(f"[DETECTION] Confidence set to {_detection_conf}", flush=True)
        return {"conf": _detection_conf}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/points/list")
def get_detected_points():
    """Return the current list of detected points."""
    return {"points": _detected_points, "count": len(_detected_points)}


@app.post("/points/clear")
def clear_detected_points():
    """Clear the detected points list."""
    global _detected_points
    _detected_points = []
    print("[POINTS] Cleared", flush=True)
    return {"status": "cleared", "count": 0}


def _nearest_neighbor_tsp(points):
    """Simple nearest-neighbor TSP approximation.
    
    Parameters:
    points : list of (x, y) tuples
    
    Returns:
    list of (x, y) tuples in optimized order
    """
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
    """Transform detected image points to galvo coordinates and visit them in optimized order."""
    global _walking, _current_target_image_pt
    
    if not _detected_points:
        return JSONResponse(status_code=400, content={"error": "No detected points"})
    
    if _homography is None:
        return JSONResponse(status_code=400, content={"error": "Homography not loaded"})
    
    if _galvo is None:
        return JSONResponse(status_code=500, content={"error": "Galvo interface unavailable"})
    
    _walking = True
    print(f"[WALK] Starting with {len(_detected_points)} points", flush=True)
    
    # Optimize the path using nearest-neighbor TSP
    optimized_image_points = _nearest_neighbor_tsp(_detected_points)
    
    # Transform to galvo coordinates
    galvo_points = []
    for img_pt in optimized_image_points:
        try:
            galvo_coord = transform_to_mover_coordinates(img_pt, _homography)
            tx, ty = int(round(galvo_coord[0])), int(round(galvo_coord[1]))
            galvo_points.append((tx, ty))
        except Exception as e:
            print(f"[WALK] Transform error for {img_pt}: {e}", flush=True)
    
    print(f"[WALK] Visiting {len(galvo_points)} galvo points", flush=True)
    visited = []
    
    # Visit each point
    for i, (tx, ty) in enumerate(galvo_points):
        if not _walking:
            print("[WALK] Stopped by user", flush=True)
            break
        
        # Set the target image point for crosshair drawing
        _current_target_image_pt = optimized_image_points[i]
        
        print(f"[WALK] Point {i+1}/{len(galvo_points)}: ({tx}, {ty})", flush=True)
        newpos = _galvo.move_2_pos(tx, ty)
        visited.append({"target": [tx, ty], "actual": newpos})
        time.sleep(0.1)  # small delay between moves
    
    _walking = False
    _current_target_image_pt = None  # clear the target when walk finishes
    print(f"[WALK] Finished", flush=True)
    return {"status": "completed", "visited": visited}


@app.post("/walk/stop")
def stop_walking():
    """Stop the walking sequence."""
    global _walking
    _walking = False
    print("[WALK] Stop requested", flush=True)
    return {"status": "stopped"}
