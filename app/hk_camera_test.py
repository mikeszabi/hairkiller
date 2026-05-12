import sys
import time
from pathlib import Path

import cv2
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "code"))

from camera_handler import UVCInterface
from api_prefix import install_api_prefix


app = FastAPI(title="hk_camera_test_backend")
install_api_prefix(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_uvc = None
_camera_error = None
_stream_stats = {
    "streamed_frames": 0,
    "encode_ms_min": None,
    "encode_ms_avg": None,
    "encode_ms_max": None,
    "last_encode_ms": None,
    "last_stream_frame_index": None,
}

try:
    _uvc = UVCInterface()
except Exception as exc:
    _camera_error = str(exc)


def _generate_camera():
    last_idx = -1

    while True:
        if _uvc is None:
            time.sleep(0.25)
            continue

        frame, idx, captured_ts = _uvc.read_with_meta()
        if frame is None or idx == last_idx:
            time.sleep(0.01)
            continue

        last_idx = idx
        t0 = time.perf_counter()
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        encode_ms = (time.perf_counter() - t0) * 1000.0
        if not ok:
            time.sleep(0.01)
            continue
        _update_stream_stats(idx, encode_ms, captured_ts)

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n"
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


def _camera_ready():
    return _uvc is not None


def _camera_error_response():
    return JSONResponse(
        status_code=503,
        content={"ok": False, "error": _camera_error},
    )


def _benchmark_latency(samples: int) -> dict:
    read_wait_ms = []
    frame_age_ms = []
    encode_ms = []
    total_ms = []
    frame_intervals_ms = []

    last_idx = None
    while len(total_ms) < samples:
        start = time.perf_counter()
        frame, idx, captured_ts = _uvc.read_with_meta()
        if frame is None:
            time.sleep(0.01)
            continue
        if last_idx == idx:
            time.sleep(0.001)
            continue

        after_read = time.perf_counter()
        ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
        after_encode = time.perf_counter()
        if not ok:
            continue

        read_wait_ms.append((after_read - start) * 1000.0)
        encode_ms.append((after_encode - after_read) * 1000.0)
        total_ms.append((after_encode - start) * 1000.0)
        frame_age_ms.append(None if captured_ts is None else (after_read - captured_ts) * 1000.0)

        if last_idx is not None:
            frame_intervals_ms.append(max(0, idx - last_idx))
        last_idx = idx
        _ = jpeg

    def summarize(values):
        vals = [v for v in values if v is not None]
        if not vals:
            return {"min": None, "avg": None, "max": None}
        return {
            "min": min(vals),
            "avg": sum(vals) / len(vals),
            "max": max(vals),
        }

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


@app.get("/")
def root():
    return {
        "app": "hk_camera_test_backend",
        "status": "ok" if _uvc is not None else "camera_unavailable",
        "stream_url": "/frame/current",
        "meta_url": "/frame/meta",
        "health_url": "/health",
        "controls_url": "/camera/settings",
        "stats_url": "/stats",
        "latency_url": "/latency/benchmark",
        "camera_error": _camera_error,
    }


@app.get("/health")
def health():
    if not _camera_ready():
        return JSONResponse(
            status_code=503,
            content={"ok": False, "camera_ready": False, "error": _camera_error},
        )

    frame, idx = _uvc.read()
    return {
        "ok": frame is not None,
        "camera_ready": frame is not None,
        "last_frame_index": idx,
        "error": None if frame is not None else "No frame available",
    }


@app.get("/frame/meta")
def frame_meta():
    if not _camera_ready():
        return _camera_error_response()

    frame, idx, captured_ts = _uvc.read_with_meta()
    if frame is None:
        return JSONResponse(
            status_code=503,
            content={"ok": False, "error": "No frame available"},
        )

    height, width = frame.shape[:2]
    return {
        "ok": True,
        "frame_index": idx,
        "width": width,
        "height": height,
        "frame_age_ms": None if captured_ts is None else (time.perf_counter() - captured_ts) * 1000.0,
    }


@app.get("/frame/snapshot")
def frame_snapshot():
    if not _camera_ready():
        return _camera_error_response()

    frame, _, _ = _uvc.read_with_meta()
    if frame is None:
        return JSONResponse(status_code=503, content={"ok": False, "error": "No frame available"})

    ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return JSONResponse(status_code=500, content={"ok": False, "error": "JPEG encoding failed"})

    return StreamingResponse(iter([jpeg.tobytes()]), media_type="image/jpeg")


@app.get("/camera/settings")
def get_camera_settings():
    if not _camera_ready():
        return _camera_error_response()
    return {"ok": True, "settings": _uvc.get_settings()}


@app.post("/camera/settings")
def set_camera_settings(
    auto_exposure: bool | None = Query(default=None),
    auto_wb: bool | None = Query(default=None),
    exposure: int | None = Query(default=None, ge=1, le=10000),
    white_balance: int | None = Query(default=None, ge=2000, le=10000),
    fps: float | None = Query(default=None, ge=1, le=120),
):
    if not _camera_ready():
        return _camera_error_response()
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


@app.get("/stats")
def stats():
    if not _camera_ready():
        return _camera_error_response()
    return {
        "ok": True,
        "camera": _uvc.get_stats(),
        "stream": _stream_stats,
        "settings": _uvc.get_settings(),
    }


@app.post("/latency/benchmark")
def latency_benchmark(samples: int = Query(default=20, ge=5, le=200)):
    if not _camera_ready():
        return _camera_error_response()
    return _benchmark_latency(samples)


@app.get("/frame/current")
def stream_video():
    if not _camera_ready():
        return _camera_error_response()

    return StreamingResponse(
        _generate_camera(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
