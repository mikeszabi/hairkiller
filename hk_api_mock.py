from fastapi import FastAPI, Query, Response
from pydantic import BaseModel
from typing import List, Optional
from fastapi.responses import StreamingResponse
import io
import time
import cv2
import numpy as np

app = FastAPI(title="Laser Control Mocked API")

# ==== MODELS ====
class Point(BaseModel):
    x: int
    y: int

class ClickEvent(BaseModel):
    x: int
    y: int

class DetectionResult(BaseModel):
    box_id: int
    x: int
    y: int
    width: int
    height: int
    score: float

# ==== GLOBAL STATE (mock) ====
detections: List[DetectionResult] = []
last_click: Optional[Point] = None
stored_coords: List[tuple] = []
laser_on: bool = True
laser_intensity: int = 128
mover_position = Point(x=100, y=100)
calibration_mode: bool = False

# ==== MOCK CAMERA STREAM ====
def generate_mock_camera():
    while True:
        # create a blank image with mock graphics
        img = np.zeros((480, 640, 3), dtype=np.uint8)
        cv2.putText(img, "Mock Frame", (200, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

        _, jpeg = cv2.imencode('.jpg', img)
        frame = jpeg.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        time.sleep(0.1)

@app.get("/frame/current")
def stream_video():
    return StreamingResponse(generate_mock_camera(), media_type="multipart/x-mixed-replace; boundary=frame")

@app.post("/frame/click")
def post_click(event: ClickEvent):
    global last_click
    last_click = Point(x=event.x, y=event.y)
    return {"status": "ok", "clicked": last_click}

@app.post("/detection/enable")
def toggle_detection(enable: bool):
    return {"detection_enabled": enable}

@app.get("/detection/boxes")
def get_detection_boxes():
    return [
        DetectionResult(box_id=i, x=100+i*20, y=100, width=50, height=50, score=0.9)
        for i in range(3)
    ]

@app.post("/detection/threshold")
def set_detection_threshold(value: float = Query(..., ge=0.0, le=1.0)):
    return {"threshold_set": value}

@app.post("/calibration/start")
def start_calibration():
    global calibration_mode, stored_coords
    calibration_mode = True
    stored_coords = []
    return {"calibration_mode": calibration_mode}

@app.post("/calibration/store")
def store_calibration_point():
    if last_click:
        stored_coords.append(((last_click.x, last_click.y), (mover_position.x, mover_position.y)))
    return {"stored_points": len(stored_coords)}

@app.post("/calibration/random")
def random_mover_position():
    return {"mover_position": {"x": 123, "y": 456}}

@app.post("/calibration/save")
def save_homography():
    return {"homography": "saved"}

@app.get("/calibration/status")
def get_calibration_status():
    return {"stored_points": len(stored_coords), "calibration_active": calibration_mode}

@app.post("/mover/move")
def move_to(x: int, y: int):
    global mover_position
    mover_position = Point(x=x, y=y)
    return {"moved_to": mover_position}

@app.post("/mover/direction")
def move_direction(direction: str, step: int = 25):
    global mover_position
    if direction == "up":
        mover_position.y += step
    elif direction == "down":
        mover_position.y -= step
    elif direction == "left":
        mover_position.x -= step
    elif direction == "right":
        mover_position.x += step
    return {"mover_position": mover_position}

@app.post("/mover/move_to_click")
def move_to_click():
    return {"moved_to": last_click or Point(x=0, y=0)}

@app.post("/mover/visit_all")
def visit_all():
    return {"visited": 3, "shoot": False}

@app.post("/mover/visit_all_and_shoot")
def visit_all_and_shoot():
    return {"visited": 3, "shoot": True}

@app.post("/laser/pointer")
def set_laser_pointer(enabled: bool):
    global laser_on
    laser_on = enabled
    return {"laser_pointer": laser_on}

@app.post("/laser/intensity")
def set_laser_intensity(intensity: int):
    global laser_intensity
    laser_intensity = intensity
    return {"laser_intensity": laser_intensity}

@app.post("/laser/shoot")
def shoot_laser():
    return {"status": "laser_fired"}

@app.post("/release")
def release():
    return {"status": "resources_released"}

@app.post("/shutdown")
def shutdown():
    return {"status": "application_shutdown"}
