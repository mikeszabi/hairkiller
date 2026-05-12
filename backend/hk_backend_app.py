import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "code"))

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
import time
import cv2
import logging
import json
import numpy as np
import re
import os
from pydantic import BaseModel

try:
    from turbojpeg import TurboJPEG
except ModuleNotFoundError:
    TurboJPEG = None

from camera_handler import UVCInterface
from detection_handler import ObjectDetector
from detection_utils import detect_red_dot, remove_overlapping_boxes, get_box_centers
from galvo_handler import GalvoInterface
from laser_handler import LaserInterface
from vacuum_handler import VacuumInterface
from serial_commands import COMMANDS
from target_handler import TargetInterface
from api_prefix import install_api_prefix
from calibration_utils import (
    read_transformation_from_file,
    transform_to_mover_coordinates,
    calculate_homography,
    save_transformation_to_file,
)
import threading
from collections import deque

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"

# ==================== FastAPI App ====================
_galvo = None
_galvo_error = None
try:
    _galvo = GalvoInterface(debug=False)
    print("[GALVO] Interface initialized", flush=True)
except Exception as e:
    _galvo_error = str(e)
    print(f"[GALVO] Failed to initialize: {e}", flush=True)

_laser = None  # initialized on startup
_target = None  # initialized once laser is available
_vacuum = None  # initialized once laser serial device is available

app = FastAPI(title="hk_backend_app")
install_api_prefix(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
_uvc = None
_camera_error = None
try:
    _uvc = UVCInterface()
    print("[CAMERA] Interface initialized", flush=True)
except Exception as e:
    _camera_error = str(e)
    print(f"[CAMERA] Failed to initialize: {e}", flush=True)
_hair_detection_enabled = False
_detected_points = []
_homography = None
_walking = False
_detection_conf = 0.1
_current_target_image_pt = None
_show_target_points_overlay = False
_last_detection_count = 0
_cam_frame_window = 0.0 # sec; frame rate is primarily controlled by _frame_stride
_frame_stride = max(1, int(os.getenv("HK_FRAME_STRIDE", "2")))
_stream_w, _stream_h = 960, 960  # stream output resolution (native is 1920x1920)
_turbo = TurboJPEG() if TurboJPEG is not None else None
_max_sequence_targets = 50

# App state
_red_dot_enabled = False  # hardware red dot state
_calibration_detection_enabled = False
_mask_overlay_enabled = False
_calibration_points = []
_hsv_lower1 = [0, 50, 250]
_hsv_upper1 = [20, 240, 255]
_hsv_lower2 = [160, 50, 250]
_hsv_upper2 = [180, 240, 255]
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
_stream_stats = {
    "streamed_frames": 0,
    "encode_ms_min": None,
    "encode_ms_avg": None,
    "encode_ms_max": None,
    "last_encode_ms": None,
    "last_stream_frame_index": None,
    "last_frame_age_at_encode_ms": None,
}


def _sequence_target_image_points():
    """Return loaded sequence targets projected back into native image coordinates."""
    if _target is None or _homography is None or not _target.targets:
        return []

    try:
        inverse_homography = np.linalg.inv(_homography)
        galvo_points = np.array(
            [[[float(x), float(y)]] for _, (x, y) in sorted(_target.targets.items())],
            dtype=np.float32,
        )
        image_points = cv2.perspectiveTransform(galvo_points, inverse_homography)
    except Exception as exc:
        logging.warning("Failed to project sequence targets to image coordinates: %s", exc)
        return []

    return [
        (int(round(point[0][0])), int(round(point[0][1])))
        for point in image_points
    ]


def _encode_jpeg(frame, quality: int = 70) -> bytes:
    if _turbo is not None:
        return _turbo.encode(frame, quality=quality)

    ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return jpeg.tobytes()


def _camera_ready() -> bool:
    return _uvc is not None


def _camera_unavailable_response():
    return JSONResponse(
        status_code=503,
        content={"ok": False, "camera_ready": False, "error": _camera_error or "Camera unavailable"},
    )


def _frame_stride_value() -> int:
    return max(1, int(_frame_stride))


def _is_stride_frame(frame_idx) -> bool:
    if frame_idx is None:
        return False
    return int(frame_idx) % _frame_stride_value() == 0


def _read_strided_frame(timeout_s: float = 1.0):
    """Return the latest frame whose camera index matches the configured stride."""
    if _uvc is None:
        return None, None

    deadline = time.perf_counter() + timeout_s
    while time.perf_counter() < deadline:
        frame, idx = _uvc.read()
        if frame is None:
            time.sleep(0.005)
            continue
        if _is_stride_frame(idx):
            return frame, idx
        time.sleep(0.001)

    return None, None


def _clamp_hsv_value(value: int, channel: str) -> int:
    upper = 180 if channel == "h" else 255
    return max(0, min(upper, int(value)))


def _current_hsv_bounds():
    return tuple(_hsv_lower1), tuple(_hsv_upper1), tuple(_hsv_lower2), tuple(_hsv_upper2)


def _detect_red_dot_with_current_hsv(frame):
    lower1, upper1, lower2, upper2 = _current_hsv_bounds()
    return detect_red_dot(
        frame,
        hsv_lower1=lower1,
        hsv_upper1=upper1,
        hsv_lower2=lower2,
        hsv_upper2=upper2,
    )


def _update_stream_stats(frame_idx, encode_ms, captured_ts):
    streamed_frames = _stream_stats["streamed_frames"] + 1
    prev_avg = _stream_stats["encode_ms_avg"]
    new_avg = encode_ms if prev_avg is None else ((prev_avg * (streamed_frames - 1)) + encode_ms) / streamed_frames

    _stream_stats["streamed_frames"] = streamed_frames
    _stream_stats["last_stream_frame_index"] = frame_idx
    _stream_stats["last_encode_ms"] = encode_ms
    _stream_stats["encode_ms_avg"] = new_avg
    _stream_stats["encode_ms_min"] = encode_ms if _stream_stats["encode_ms_min"] is None else min(_stream_stats["encode_ms_min"], encode_ms)
    _stream_stats["encode_ms_max"] = encode_ms if _stream_stats["encode_ms_max"] is None else max(_stream_stats["encode_ms_max"], encode_ms)
    _stream_stats["last_frame_age_at_encode_ms"] = None if captured_ts is None else (time.perf_counter() - captured_ts) * 1000.0


def _benchmark_latency(samples: int) -> dict:
    read_wait_ms = []
    frame_age_ms = []
    encode_ms = []
    total_ms = []
    last_idx = None

    if _uvc is None:
        return {"ok": False, "error": _camera_error or "Camera unavailable"}

    while len(total_ms) < samples:
        start = time.perf_counter()
        frame, idx, captured_ts = _uvc.read_with_meta()
        if frame is None or last_idx == idx:
            time.sleep(0.001)
            continue

        after_read = time.perf_counter()
        t0 = time.perf_counter()
        _ = _encode_jpeg(frame, quality=75)
        after_encode = time.perf_counter()

        read_wait_ms.append((after_read - start) * 1000.0)
        encode_ms.append((after_encode - t0) * 1000.0)
        total_ms.append((after_encode - start) * 1000.0)
        frame_age_ms.append(None if captured_ts is None else (after_read - captured_ts) * 1000.0)
        last_idx = idx

    def summarize(values):
        vals = [value for value in values if value is not None]
        if not vals:
            return {"min": None, "avg": None, "max": None}
        return {"min": min(vals), "avg": sum(vals) / len(vals), "max": max(vals)}

    return {
        "ok": True,
        "samples": samples,
        "read_wait_ms": summarize(read_wait_ms),
        "frame_age_ms": summarize(frame_age_ms),
        "encode_ms": summarize(encode_ms),
        "total_pipeline_ms": summarize(total_ms),
        "camera_stats": _uvc.get_stats(),
        "settings": _uvc.get_settings(),
    }

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
    _vacuum = VacuumInterface(dev=_laser.dev)
    print("[LASER] Interface initialized", flush=True)
except Exception as e:
    print(f"[LASER] Failed to initialize: {e}", flush=True)
    _laser = None
    _target = None
    _vacuum = None


def _background_inference_worker():
    """Background thread that continuously runs YOLO inference and updates cache."""
    global _inference_cache
    last_processed_idx = -1
    print("[INFERENCE THREAD] Started", flush=True)
    
    while True:
        if not _hair_detection_enabled or _detector is None:
            time.sleep(0.1)
            continue
        if _uvc is None:
            time.sleep(0.25)
            continue
        
        frame, idx = _uvc.read()
        if frame is None or idx == last_processed_idx or not _is_stride_frame(idx):
            time.sleep(0.01)
            continue
        last_processed_idx = idx
        
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


class LaserSettingsRequest(BaseModel):
    armed: bool
    p808: int
    p980: int
    p1064: int
    pulse_ms: int
    reload_targets: bool = True


def _parse_channel_power_response(lines):
    if not isinstance(lines, list):
        return None

    for line in lines:
        text = str(line).strip()
        if "->" not in text:
            continue
        payload = text.split("->", 1)[1].strip().strip("[]")
        parts = [part.strip() for part in payload.split(",")]
        if len(parts) < 3:
            continue
        try:
            p808 = int(float(parts[0]))
            p980 = int(float(parts[1]))
            p1064 = int(float(parts[2]))
            return {"p808": p808, "p980": p980, "p1064": p1064}
        except ValueError:
            continue

    return None


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


def _extract_single_value_response(lines) -> str | None:
    if not isinstance(lines, list):
        return None

    for line in lines:
        text = str(line).strip()
        match = re.search(r"->\[(.*?)\]", text)
        if match:
            return match.group(1).strip()
    return None


def _is_enabled_response(lines) -> bool:
    return _extract_single_value_response(lines) == "1"


def _prepare_peltier_for_arming():
    if _laser is None:
        return None

    status_resp = _laser.get_peltier_cooling_enabled()
    if _is_enabled_response(status_resp):
        return {
            "status": status_resp,
            "enable": None,
            "enabled": True,
        }

    enable_resp = _laser.set_peltier_cooling_enabled(True)
    return {
        "status": status_resp,
        "enable": enable_resp,
        "enabled": _is_enabled_response(_laser.get_peltier_cooling_enabled()),
    }


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
    """Stream frames with treatment, calibration, and target overlays."""
    global _last_detection_count
    last_sent_idx = -1
    
    while True:
        if _uvc is None:
            time.sleep(0.25)
            continue
        frame, idx = _uvc.read()
        if frame is None or idx == last_sent_idx or not _is_stride_frame(idx):
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
        
        # Update detection count
        if current_count != _last_detection_count:
            _last_detection_count = current_count

        # Calibration red-dot overlay shares the same stream so every frontend
        # can continue to use `/frame/current`.
        if _calibration_detection_enabled:
            mask, center = _detect_red_dot_with_current_hsv(frame)
            if _mask_overlay_enabled:
                overlay = frame.copy()
                overlay[mask > 0] = (0, 255, 255)
                cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)
            if center is not None:
                x, y = center
                cv2.circle(frame, (x, y), 25, (255, 0, 255), 3)
                cv2.line(frame, (x - 30, y), (x + 30, y), (0, 255, 255), 2)
                cv2.line(frame, (x, y - 30), (x, y + 30), (0, 255, 255), 2)
                cv2.putText(frame, f"({x}, {y})", (x + 35, y - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # Sequence target overlay. Targets are stored in galvo coordinates, so
        # project them back through the inverse homography before drawing.
        if _show_target_points_overlay:
            target_points = _sequence_target_image_points()
            if target_points:
                overlay = frame.copy()
                height, width = frame.shape[:2]
                for tx, ty in target_points:
                    if 0 <= tx < width and 0 <= ty < height:
                        cv2.circle(overlay, (tx, ty), 18, (0, 255, 255), -1)
                cv2.addWeighted(overlay, 0.5, frame, 0.5, 0, frame)
        
        # Target crosshair
        if _current_target_image_pt is not None:
            tx, ty = int(_current_target_image_pt[0]), int(_current_target_image_pt[1])
            cv2.line(frame, (tx - 40, ty), (tx + 40, ty), (0, 0, 255), 2)
            cv2.line(frame, (tx, ty - 40), (tx, ty + 40), (0, 0, 255), 2)
            cv2.circle(frame, (tx, ty), 8, (0, 0, 255), 2)
            cv2.putText(frame, "TARGET", (tx + 15, ty - 15),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
        
        small = cv2.resize(frame, (_stream_w, _stream_h))
        encode_start = time.perf_counter()
        buf = _encode_jpeg(small, quality=70)
        _update_stream_stats(last_sent_idx, (time.perf_counter() - encode_start) * 1000.0, None)
        yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf + b'\r\n'
        time.sleep(_cam_frame_window)


@app.get("/")
def root():
    return FileResponse(APP_DIR / "hk_full_app.html")


# ==================== Diagnostics ====================
@app.get("/health")
def health():
    frame, idx, captured_ts = (None, None, None)
    if _uvc is not None:
        frame, idx, captured_ts = _uvc.read_with_meta()
    ok = frame is not None
    return {
        "ok": ok and _galvo is not None,
        "camera_ready": ok,
        "camera_error": _camera_error,
        "laser_ready": _laser is not None,
        "target_ready": _target is not None,
        "galvo_ready": _galvo is not None,
        "galvo_error": _galvo_error,
        "detector_ready": _detector is not None,
        "homography_loaded": _homography is not None,
        "last_frame_index": idx,
        "frame_age_ms": None if captured_ts is None else (time.perf_counter() - captured_ts) * 1000.0,
    }


@app.get("/frame/meta")
def frame_meta():
    if _uvc is None:
        return _camera_unavailable_response()
    frame, idx, captured_ts = _uvc.read_with_meta()
    if frame is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "No frame available"})

    height, width = frame.shape[:2]
    return {
        "ok": True,
        "frame_index": idx,
        "width": width,
        "height": height,
        "stream_width": _stream_w,
        "stream_height": _stream_h,
        "frame_age_ms": None if captured_ts is None else (time.perf_counter() - captured_ts) * 1000.0,
    }


@app.get("/stats")
def stats():
    camera_stats = {} if _uvc is None else _uvc.get_stats()
    camera_settings = {} if _uvc is None else _uvc.get_settings()
    return {
        "ok": _uvc is not None,
        "camera": camera_stats,
        "settings": camera_settings,
        "stream": {
            "width": _stream_w,
            "height": _stream_h,
            "window_s": _cam_frame_window,
            "frame_stride": _frame_stride_value(),
            **_stream_stats,
        },
        "detection_enabled": _hair_detection_enabled,
        "detection_count": _last_detection_count,
        "calibration_detection_enabled": _calibration_detection_enabled,
        "mask_overlay_enabled": _mask_overlay_enabled,
        "red_dot_enabled": _red_dot_enabled,
        "homography_loaded": _homography is not None,
        "detected_points": len(_detected_points),
        "calibration_points": len(_calibration_points),
        "walking": _walking,
    }


# ==================== Video Stream ====================
@app.get("/frame/current")
def stream_video():
    if _uvc is None:
        return _camera_unavailable_response()
    return StreamingResponse(_generate_camera(),
                             media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/frame/snapshot")
def frame_snapshot():
    if _uvc is None:
        return _camera_unavailable_response()
    frame, _, _ = _uvc.read_with_meta()
    if frame is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "No frame available"})
    buf = _encode_jpeg(frame, quality=90)
    return StreamingResponse(iter([buf]), media_type="image/jpeg")


@app.get("/camera/settings")
def get_camera_settings():
    if _uvc is None:
        return _camera_unavailable_response()
    return {"ok": True, "settings": _uvc.get_settings()}


@app.post("/camera/settings")
def set_camera_settings(
    auto_exposure: bool | None = Query(default=None),
    auto_wb: bool | None = Query(default=None),
    exposure: int | None = Query(default=None, ge=1, le=10000),
    white_balance: int | None = Query(default=None, ge=2000, le=10000),
    fps: float | None = Query(default=None, ge=1, le=120),
):
    if _uvc is None:
        return _camera_unavailable_response()
    try:
        settings = _uvc.apply_settings(
            auto_exposure=auto_exposure,
            exposure=exposure,
            auto_wb=auto_wb,
            white_balance=white_balance,
            fps=fps,
        )
    except Exception as exc:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(exc)})
    return {"ok": True, "settings": settings}


@app.post("/latency/benchmark")
def latency_benchmark(samples: int = Query(default=20, ge=5, le=200)):
    if _uvc is None:
        return _camera_unavailable_response()
    return _benchmark_latency(samples)


@app.get("/camera/frame_stride")
def get_camera_frame_stride():
    return {"frame_stride": _frame_stride_value()}


@app.post("/camera/frame_stride")
def set_camera_frame_stride(value: int = Query(..., ge=1, le=60)):
    global _frame_stride
    _frame_stride = int(value)
    return {"frame_stride": _frame_stride_value()}


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


@app.get("/app/command_catalog")
def get_app_command_catalog():
    catalog = []
    for name, meta in COMMANDS.items():
        catalog.append(
            {
                "name": name,
                "section": meta.get("section", ""),
                "parameters": meta.get("parameters", ""),
                "description": meta.get("description", ""),
                "returns": meta.get("returns", ""),
                "returns_nok": meta.get("returns_nok", ""),
                "example": meta.get("example", ""),
                "notes": meta.get("notes", ""),
            }
        )
    catalog.sort(key=lambda item: (item["section"], item["name"]))
    return {"commands": catalog}


@app.get("/app/command_info")
def get_app_command_info(command: str = Query(...)):
    normalized = str(command).strip().split()[0] if str(command).strip() else ""
    if not normalized:
        return JSONResponse(status_code=400, content={"error": "Command is empty"})

    meta = COMMANDS.get(normalized)
    if meta is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": f"Unknown command: {normalized}",
                "command": normalized,
            },
        )

    return {
        "command": normalized,
        "meta": {
            "name": meta.get("name", normalized),
            "section": meta.get("section", ""),
            "parameters": meta.get("parameters", ""),
            "description": meta.get("description", ""),
            "returns": meta.get("returns", ""),
            "returns_nok": meta.get("returns_nok", ""),
            "example": meta.get("example", ""),
            "notes": meta.get("notes", ""),
        },
    }


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


@app.post("/vacuum/on")
def vacuum_on():
    if _vacuum is None:
        return JSONResponse(status_code=500, content={"error": "Vacuum controller unavailable"})
    return {"response": _vacuum.vacuum_on()}


@app.post("/vacuum/off")
def vacuum_off():
    if _vacuum is None:
        return JSONResponse(status_code=500, content={"error": "Vacuum controller unavailable"})
    return {"response": _vacuum.vacuum_off()}


@app.post("/vacuum/check")
def set_vacuum_check_enabled(enabled: bool = Query(...)):
    if _vacuum is None:
        return JSONResponse(status_code=500, content={"error": "Vacuum controller unavailable"})
    return {"response": _vacuum.set_check_vacuum(enabled)}


@app.get("/vacuum/check")
def get_vacuum_check_enabled():
    if _vacuum is None:
        return JSONResponse(status_code=500, content={"error": "Vacuum controller unavailable"})
    resp = _vacuum.get_check_vacuum()
    return {"response": resp, "enabled": _vacuum.parse_bool_response(resp)}


@app.get("/vacuum/status")
def get_vacuum_status():
    if _vacuum is None:
        return JSONResponse(status_code=500, content={"error": "Vacuum controller unavailable"})
    return _vacuum.get_status()


@app.get("/seq/status")
def get_sequence_status():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})

    _drain_async_messages()
    state = _target.get_state()
    mode = _target.get_mode()
    last_error = _target.get_last_error()

    with _sequence_lock:
        events = list(_sequence_events)

    return {
        "state": state,
        "mode": mode,
        "last_error": last_error,
        "target_count": _target.get_target_count(),
        "show_target_points_overlay": _show_target_points_overlay,
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
    return {
        "detection_enabled": _hair_detection_enabled or _calibration_detection_enabled,
        "hair_detection_enabled": _hair_detection_enabled,
        "conf": _detection_conf,
        "red_dot": _red_dot_enabled,
        "mask_overlay_enabled": _mask_overlay_enabled,
        "hsv_lower1": _hsv_lower1,
        "hsv_upper1": _hsv_upper1,
        "hsv_lower2": _hsv_lower2,
        "hsv_upper2": _hsv_upper2,
    }


@app.post("/calibration/detection/toggle")
def toggle_calibration_detection(enabled: bool = Query(...)):
    global _calibration_detection_enabled, _red_dot_enabled
    _calibration_detection_enabled = enabled
    if _laser is not None:
        try:
            _laser.set_red_dot(enabled)
            _red_dot_enabled = enabled
        except Exception as exc:
            logging.warning("Calibration red-dot toggle failed: %s", exc)
    return {"detection_enabled": _calibration_detection_enabled, "red_dot": _red_dot_enabled}


@app.post("/detection/mask_overlay")
def set_mask_overlay(enabled: bool = Query(...)):
    global _mask_overlay_enabled
    _mask_overlay_enabled = enabled
    return {"mask_overlay_enabled": _mask_overlay_enabled}


@app.get("/detection/hsv")
def get_detection_hsv():
    return {
        "hsv_lower1": _hsv_lower1,
        "hsv_upper1": _hsv_upper1,
        "hsv_lower2": _hsv_lower2,
        "hsv_upper2": _hsv_upper2,
    }


@app.post("/detection/hsv")
def set_detection_hsv(
    lower1_h: int = Query(...),
    lower1_s: int = Query(...),
    lower1_v: int = Query(...),
    upper1_h: int = Query(...),
    upper1_s: int = Query(...),
    upper1_v: int = Query(...),
    lower2_h: int = Query(...),
    lower2_s: int = Query(...),
    lower2_v: int = Query(...),
    upper2_h: int = Query(...),
    upper2_s: int = Query(...),
    upper2_v: int = Query(...),
):
    global _hsv_lower1, _hsv_upper1, _hsv_lower2, _hsv_upper2
    _hsv_lower1 = [_clamp_hsv_value(lower1_h, "h"), _clamp_hsv_value(lower1_s, "s"), _clamp_hsv_value(lower1_v, "v")]
    _hsv_upper1 = [_clamp_hsv_value(upper1_h, "h"), _clamp_hsv_value(upper1_s, "s"), _clamp_hsv_value(upper1_v, "v")]
    _hsv_lower2 = [_clamp_hsv_value(lower2_h, "h"), _clamp_hsv_value(lower2_s, "s"), _clamp_hsv_value(lower2_v, "v")]
    _hsv_upper2 = [_clamp_hsv_value(upper2_h, "h"), _clamp_hsv_value(upper2_s, "s"), _clamp_hsv_value(upper2_v, "v")]
    return get_detection_hsv()


@app.get("/dot")
def read_dot():
    if _uvc is None:
        return {"x": None, "y": None, "error": _camera_error or "Camera unavailable"}
    frame, idx = _read_strided_frame()
    if frame is None:
        return {"x": None, "y": None}
    _, center = _detect_red_dot_with_current_hsv(frame)
    if center is None:
        return {"x": None, "y": None, "frame_index": idx}
    return {"x": int(center[0]), "y": int(center[1]), "frame_index": idx}


@app.get("/frame/hsv")
def read_frame_hsv(x: int = Query(...), y: int = Query(...)):
    if _uvc is None:
        return _camera_unavailable_response()
    frame, _ = _uvc.read()
    if frame is None:
        return JSONResponse(status_code=503, content={"error": "No frame available"})

    height, width = frame.shape[:2]
    native_x = int(round(x * width / _stream_w))
    native_y = int(round(y * height / _stream_h))
    if native_x < 0 or native_y < 0 or native_x >= width or native_y >= height:
        return JSONResponse(status_code=400, content={"error": "Point outside frame", "width": _stream_w, "height": _stream_h})

    hsv_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    b, g, r = [int(value) for value in frame[native_y, native_x]]
    h, s, v = [int(value) for value in hsv_frame[native_y, native_x]]
    return {"x": x, "y": y, "native_x": native_x, "native_y": native_y, "hsv": [h, s, v], "bgr": [b, g, r], "rgb": [r, g, b]}


@app.get("/sse/dot")
def sse_dot():
    def event_stream():
        last_x, last_y = None, None
        while True:
            if _uvc is None:
                time.sleep(0.5)
                continue
            frame, idx = _read_strided_frame()
            if frame is not None:
                _, center = _detect_red_dot_with_current_hsv(frame)
                if center is not None:
                    x, y = int(center[0]), int(center[1])
                    if x != last_x or y != last_y:
                        last_x, last_y = x, y
                        yield f"data: {json.dumps({'x': x, 'y': y, 'frame_index': idx})}\n\n"
                elif last_x is not None or last_y is not None:
                    last_x, last_y = None, None
                    yield f"data: {json.dumps({'x': None, 'y': None, 'frame_index': idx})}\n\n"
            time.sleep(0.5)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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
    if _uvc is None:
        return _camera_unavailable_response()
    
    frame, idx = _read_strided_frame()
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
        
        return {"captured": len(_detected_points), "points": _detected_points, "frame_index": idx}
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


def _build_target_points_from_image_points(image_points):
    if _target is None:
        return None, JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    if not image_points:
        return None, JSONResponse(status_code=400, content={"error": "No points"})
    if _homography is None:
        return None, JSONResponse(status_code=400, content={"error": "Homography unavailable"})

    targets = []
    for image_point in image_points:
        try:
            galvo_coord = transform_to_mover_coordinates(image_point, _homography)
            tx, ty = int(round(galvo_coord[0])), int(round(galvo_coord[1]))
            targets.append((tx, ty))
        except Exception as exc:
            return None, JSONResponse(
                status_code=500,
                content={"error": f"Failed to transform point {image_point}: {exc}"},
            )

    return targets, None


def _build_target_points_from_detected():
    limited_points = _detected_points[:_max_sequence_targets]
    return _build_target_points_from_image_points(limited_points)


def _load_targets_into_controller(targets):
    resp = _target.set_seq_length(len(targets))
    for idx, (tx, ty) in enumerate(targets):
        resp.extend(_target.set_target_point(idx, tx, ty))
    resp.extend(_target.load_targets())
    return resp


def _reload_loaded_targets_into_controller():
    if _target is None:
        return ["ERROR: target controller unavailable"]
    if not _target.targets:
        return ["TARGET_COUNT=0"]
    return _target.load_targets()


@app.post("/homography/reload")
def reload_homography():
    """Reload the homography matrix from the transformation file."""
    global _homography
    try:
        _homography = read_transformation_from_file()
        return {"status": "reloaded"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/calibration/start")
def start_calibration():
    _calibration_points.clear()
    return {"status": "started"}


@app.post("/calibration/store")
def store_calibration_point():
    if _uvc is None:
        return {"stored": len(_calibration_points), "error": _camera_error or "Camera unavailable"}
    frame, idx = _read_strided_frame()
    position = _galvo.get_position() if _galvo is not None else (None, None)
    center = None
    if frame is not None:
        _, center = _detect_red_dot_with_current_hsv(frame)
    if center is not None and position is not None:
        _calibration_points.append(((int(center[0]), int(center[1])), (position[0], position[1])))
    return {"stored": len(_calibration_points), "frame_index": idx}


@app.get("/calibration/points")
def get_calibration_points():
    return {"points": _calibration_points}


@app.post("/calibration/save")
def save_calibration():
    global _homography
    if len(_calibration_points) < 4:
        return {"status": "need_more_points", "count": len(_calibration_points)}

    image_pts = [point[0] for point in _calibration_points]
    mover_pts = [point[1] for point in _calibration_points]
    _homography = calculate_homography(image_pts, mover_pts)
    save_transformation_to_file(_homography)
    with open(ROOT / "saved_coordinates.json", "w", encoding="utf-8") as handle:
        json.dump(_calibration_points, handle)
    return {"status": "saved", "count": len(_calibration_points)}


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

    peltier = None
    if enabled:
        peltier = _prepare_peltier_for_arming()

    resp = _laser.set_arm_enabled(enabled)
    return {"response": resp, "enabled": enabled, "peltier": peltier}


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
    peltier = _prepare_peltier_for_arming()
    resp = _laser.arm_laser()
    return {"response": resp, "peltier": peltier}


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
    return {
        "response": resp,
        "power": {
            "p808": int(_laser.channel_power[0]),
            "p980": int(_laser.channel_power[1]),
            "p1064": int(_laser.channel_power[2]),
        },
        "pending_sync": _laser.has_pending_channel_power(),
        "active": {
            "p808": bool(_laser.active[0]),
            "p980": bool(_laser.active[1]),
            "p1064": bool(_laser.active[2]),
        },
    }


@app.get("/laser/channel_pwr")
def get_laser_channel_power():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.get_channel_power()
    logical_power = {
        "p808": int(_laser.channel_power[0]),
        "p980": int(_laser.channel_power[1]),
        "p1064": int(_laser.channel_power[2]),
    }
    raw_power = _parse_channel_power_response(resp)
    return {
        "response": resp,
        "power": logical_power,
        "raw_power": raw_power,
        "pending_sync": _laser.has_pending_channel_power(),
        "active": {
            "p808": bool(_laser.active[0]),
            "p980": bool(_laser.active[1]),
            "p1064": bool(_laser.active[2]),
        },
    }


@app.post("/laser/active")
def set_active_lasers(
    l1064: int = Query(1),
    l980: int = Query(1),
    l808: int = Query(1),
    l660: int | None = Query(None),
):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    resp = _laser.set_active_lasers(l1064, l980, l808, 0 if l660 is None else l660)
    if l660 is not None:
        global _red_dot_enabled
        _red_dot_enabled = bool(l660)
    return {
        "response": resp,
        "active": [bool(l1064), bool(l980), bool(l808)],
        "red_dot": _red_dot_enabled,
    }


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


@app.get("/laser/settings")
def get_laser_settings():
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})

    arm_resp = _laser.get_arm_enabled()
    arm_text = " ".join(str(line) for line in arm_resp)
    armed = "1" in arm_text
    power_resp = _laser.get_channel_power()

    return {
        "response": {
            "arm": arm_resp,
            "power": power_resp,
        },
        "armed": armed,
        "power": {
            "p808": int(_laser.channel_power[0]),
            "p980": int(_laser.channel_power[1]),
            "p1064": int(_laser.channel_power[2]),
        },
        "pulse_ms": int(_target.pulse_ms),
        "pending_sync": _laser.has_pending_channel_power(),
        "targets_count": _target.get_target_count(),
    }


@app.post("/laser/settings")
def update_laser_settings(settings: LaserSettingsRequest):
    if _laser is None:
        return JSONResponse(status_code=500, content={"error": "Laser unavailable"})
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})

    responses = {}

    # If the operator requested a disarmed state, do it before changing anything
    # else. If they requested armed, arm only after settings are applied.
    if not settings.armed:
        responses["arm"] = _laser.disarm_laser()

    responses["power"] = _laser.set_channel_power(
        settings.p808,
        settings.p980,
        settings.p1064,
    )
    responses["pulse"] = _target.set_las_pulse(settings.pulse_ms)

    targets_reloaded = False
    if settings.reload_targets and _target.targets:
        responses["targets"] = _reload_loaded_targets_into_controller()
        targets_reloaded = True

    if settings.armed:
        responses["peltier"] = _prepare_peltier_for_arming()
        responses["arm"] = _laser.arm_laser()

    return {
        "response": responses,
        "armed": bool(settings.armed),
        "power": {
            "p808": int(_laser.channel_power[0]),
            "p980": int(_laser.channel_power[1]),
            "p1064": int(_laser.channel_power[2]),
        },
        "pulse_ms": int(_target.pulse_ms),
        "pending_sync": _laser.has_pending_channel_power(),
        "targets_reloaded": targets_reloaded,
        "targets_count": _target.get_target_count(),
    }


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


@app.post("/seq/show_targets")
def set_show_target_points(enabled: bool = Query(...)):
    global _show_target_points_overlay
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    if enabled and _homography is None:
        return JSONResponse(status_code=400, content={"error": "Homography unavailable"})

    _show_target_points_overlay = bool(enabled)
    return {
        "show_target_points_overlay": _show_target_points_overlay,
        "targets_count": _target.get_target_count(),
    }


@app.post("/seq/update_targets")
def update_sequence_targets():
    original_count = len(_detected_points)
    targets, error_response = _build_target_points_from_detected()
    if error_response is not None:
        return error_response

    try:
        start_ts = time.perf_counter()
        resp = _load_targets_into_controller(targets)
        load_ms = round((time.perf_counter() - start_ts) * 1000.0, 1)
        return {
            "response": resp,
            "targets_count": len(targets),
            "detected_count": original_count,
            "max_targets": _max_sequence_targets,
            "truncated": original_count > len(targets),
            "targets": targets,
            "load_ms": load_ms,
        }
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to load targets into controller: {exc}",
                "targets_count": len(targets),
                "detected_count": original_count,
                "max_targets": _max_sequence_targets,
            },
        )


@app.post("/seq/clear_targets")
def clear_sequence_targets():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    resp = _target.clear_targets()
    return {"response": resp, "targets_count": 0}


@app.post("/seq/mode")
def set_sequence_mode(mode: str = Query(...)):
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})

    normalized = str(mode).strip().lower()
    if normalized in {"manual", "single", "step"}:
        mode_value = TargetInterface.MODE_MANUAL
        mode_name = "MANUAL"
    elif normalized in {"auto", "all"}:
        mode_value = TargetInterface.MODE_AUTO
        mode_name = "AUTO"
    else:
        return JSONResponse(status_code=400, content={"error": f"Unsupported target mode: {mode}"})

    resp = _target.set_mode(mode_value)
    return {"response": resp, "mode": mode_name}


@app.get("/seq/mode")
def get_sequence_mode():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    resp = _target.get_mode()
    return {"response": resp}


@app.post("/seq/start")
def start_seq():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    try:
        resp = _target.start_seq()
        return {"response": resp, "targets_count": _target.get_target_count()}
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to start target sequence: {exc}",
                "targets_count": _target.get_target_count(),
                "state": _target.get_state(),
                "last_error": _target.get_last_error(),
            },
        )


@app.post("/seq/start_test")
def start_seq_test():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    try:
        resp = _target.start_seq_test()
        return {"response": resp, "targets_count": _target.get_target_count()}
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to start test target sequence: {exc}",
                "targets_count": _target.get_target_count(),
                "state": _target.get_state(),
                "last_error": _target.get_last_error(),
            },
        )


@app.post("/seq/stop")
def stop_seq():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    try:
        resp = _target.stop_seq()
        return {"response": resp, "targets_count": _target.get_target_count()}
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to stop target sequence: {exc}",
                "targets_count": _target.get_target_count(),
                "state": _target.get_state(),
                "last_error": _target.get_last_error(),
            },
        )


@app.post("/seq/halt")
def halt_seq():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})
    try:
        resp = _target.halt_seq()
        return {"response": resp, "targets_count": _target.get_target_count()}
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": f"Failed to halt target sequence: {exc}",
                "targets_count": _target.get_target_count(),
                "state": _target.get_state(),
                "last_error": _target.get_last_error(),
            },
        )


@app.post("/seq/step")
def step_seq():
    if _target is None:
        return JSONResponse(status_code=500, content={"error": "Target controller unavailable"})

    state = _target.get_state()
    state_text = " ".join(str(line) for line in state).upper()
    if "IDLE" in state_text:
        _target.set_mode(TargetInterface.MODE_MANUAL)
        resp = _target.start_seq_manual()
    else:
        resp = _target.resume_seq()
    return {"response": resp, "state": state, "targets_count": _target.get_target_count()}


# ==================== Fire Sequence with Detected Points ====================
@app.post("/fire/walk")
def fire_walk(test_mode: bool = Query(False)):
    """
    Convert detected image points to galvo coordinates, 
    set them as sequence targets, and fire.
    If test_mode=True, uses START_SEQ_TEST, else START_SEQ.
    """
    optimized_image_points = _nearest_neighbor_tsp(_detected_points)
    targets, error_response = _build_target_points_from_image_points(optimized_image_points)
    if error_response is not None:
        return error_response

    load_resp = _load_targets_into_controller(targets)

    # Start sequence
    if test_mode:
        start_resp = _target.start_seq_test()
    else:
        start_resp = _target.start_seq()
    
    return {
        "status": "firing",
        "test_mode": test_mode,
        "targets_count": len(targets),
        "response": {
            "load": load_resp,
            "start": start_resp,
        },
    }
