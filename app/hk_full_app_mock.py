import base64
import json
import math
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = ROOT / "code"
if str(CODE_DIR) not in sys.path:
    sys.path.append(str(CODE_DIR))

try:
    from serial_commands import COMMANDS, SENSOR_FIELDS
except Exception:  # pragma: no cover - mock should still boot without code path
    COMMANDS = {}
    SENSOR_FIELDS = []


class RawCommandRequest(BaseModel):
    command: str


class LaserSettingsRequest(BaseModel):
    armed: bool
    p808: int
    p980: int
    p1064: int
    pulse_ms: int
    reload_targets: bool = True


app = FastAPI(title="hk_full_app_mock")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STREAM_W = 960
STREAM_H = 960
NATIVE_W = 1920
NATIVE_H = 1920
MAX_SEQUENCE_TARGETS = 50

_started_at = time.time()
_frame_index = 0
_detection_enabled = False
_detection_conf = 0.1
_last_detection_count = 0
_detected_points: list[list[int]] = []
_walking = False
_mover_pos = [3000, 3000]
_red_dot_enabled = False
_armed = False
_laser_active = False
_channel_power = {"p808": 20, "p980": 25, "p1064": 50}
_active_channels = {"p808": True, "p980": True, "p1064": True}
_pulse_ms = 50
_pending_sync = False
_sequence_mode = "MANUAL"
_sequence_state = "IDLE"
_show_target_points_overlay = False
_targets: dict[int, list[int]] = {}
_app_error_events: deque[dict[str, Any]] = deque(maxlen=25)
_sequence_events: deque[dict[str, Any]] = deque(maxlen=25)
_test_events: deque[dict[str, Any]] = deque(maxlen=25)

_mock_image_candidates = [
    ROOT / "images" / "hair_test_live.jpg",
    ROOT / "images" / "hair_test.jpg",
    ROOT / "test.jpg",
]
_fallback_jpeg = base64.b64decode(
    b"/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    b"2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQ"
    b"AAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAH/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAEFAqf/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/ASP/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/ASP/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAY/Aqf/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/ISf/2gAMAwEAAgADAAAAEP/EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQMBAT8QH//EABQRAQAAAAAAAAAAAAAAAAAAABD/2gAIAQIBAT8QH//EABQQAQAAAAAAAAAAAAAAAAAAABD/2gAIAQEAAT8QH//Z"
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _uptime_ms() -> int:
    return int((time.time() - _started_at) * 1000)


def _ok(command: str, payload: str = "OK") -> list[str]:
    return [f"[{command}]->[{payload}][{_uptime_ms()}]"]


def _ok_arg(command: str, arg: str, payload: str = "OK") -> list[str]:
    return [f"[{command}][{arg}]->[{payload}][{_uptime_ms()}]"]


def _bool_str(value: bool) -> str:
    return "1" if value else "0"


def _clamp_int(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(value)))


def _native_to_galvo(ix: int, iy: int) -> list[int]:
    x = round(_clamp_int(ix, 0, NATIVE_W) * 4095 / NATIVE_W)
    y = round(_clamp_int(iy, 0, NATIVE_H) * 4095 / NATIVE_H)
    return [_clamp_int(x, 0, 4095), _clamp_int(y, 0, 4095)]


def _galvo_to_native(x: int, y: int) -> list[int]:
    ix = round(_clamp_int(x, 0, 4095) * NATIVE_W / 4095)
    iy = round(_clamp_int(y, 0, 4095) * NATIVE_H / 4095)
    return [ix, iy]


def _mock_points() -> list[list[int]]:
    phase = int(time.time() * 10) % 20
    return [
        [420 + phase, 510],
        [760, 620 + phase],
        [1040 - phase, 840],
        [1280, 1010 - phase],
        [610, 1220],
    ]


def _nearest_neighbor(points: list[list[int]]) -> list[list[int]]:
    if len(points) < 2:
        return points[:]
    remaining = points[:]
    result = [remaining.pop(0)]
    while remaining:
        x, y = result[-1]
        idx = min(
            range(len(remaining)),
            key=lambda i: (remaining[i][0] - x) ** 2 + (remaining[i][1] - y) ** 2,
        )
        result.append(remaining.pop(idx))
    return result


def _load_targets_from_points(points: list[list[int]]) -> list[str]:
    global _targets
    _targets = {idx: _native_to_galvo(x, y) for idx, (x, y) in enumerate(points)}
    return [f"SEQ_LEN={len(_targets)}"] + [
        f"TARGET[{idx}]={xy[0]},{xy[1]}" for idx, xy in sorted(_targets.items())
    ] + [f"TARGET_COUNT={len(_targets)}"]


def _target_count() -> int:
    return len(_targets)


def _append_sequence_event(status: str = "OK") -> None:
    _sequence_events.appendleft(
        {
            "status": status,
            "message": f"[TARGET_SEQ_FINISHED]->[{status}][{_uptime_ms()}]",
            "timestamp": _now_ms(),
        }
    )


def _append_test_event(kind: str, status: str) -> None:
    if kind == "watchdog":
        message = f"[APP_WATCHDOG_TRIGGERED]->[{status}][{_uptime_ms()}]"
    else:
        message = f"[APP_LASER_PWR_TEST_FINISHED]->[{status}][{_uptime_ms()}]"
    _test_events.appendleft(
        {"kind": kind, "status": status, "message": message, "timestamp": _now_ms()}
    )


def _sensor_values() -> dict[str, float]:
    values = {
        "inputCurrent_mA": 680.0,
        "laser660Curr_mA": 0.0 if not _red_dot_enabled else 18.0,
        "laser808Curr_mA": float(_channel_power["p808"] * 10 if _armed else 0),
        "laser980Curr_mA": float(_channel_power["p980"] * 10 if _armed else 0),
        "laser1064Curr_mA": float(_channel_power["p1064"] * 10 if _armed else 0),
        "laserPower_mV": float(sum(_channel_power.values()) * 12),
        "laserTemp_C": 31.5 + math.sin(time.time() / 5) * 1.2,
        "peltierVoltage_mV": 11800.0,
        "heatsinkTemp_C": 29.1,
        "mosfetTemp_C": 30.4,
        "target1Temp_C": 28.7,
        "target2Temp_C": 28.8,
        "galvoPosX_raw": float(_mover_pos[0]),
        "galvoPosY_raw": float(_mover_pos[1]),
        "updateTimestamp_ms": float(_uptime_ms()),
    }
    for field in SENSOR_FIELDS:
        values.setdefault(field, 0.0)
    return values


def _raw_sensor_line(values: dict[str, float]) -> list[str]:
    ordered = [values.get(field, 0.0) for field in SENSOR_FIELDS] if SENSOR_FIELDS else list(values.values())
    payload = ",".join(f"{value:.2f}" for value in ordered)
    return [f"[SENSORS_GET_VALUES]->[{payload}][{_uptime_ms()}]"]


def _jpeg_bytes() -> bytes:
    for path in _mock_image_candidates:
        if path.exists() and path.is_file():
            return path.read_bytes()
    return _fallback_jpeg


def _generate_camera():
    global _frame_index, _last_detection_count
    jpeg = _jpeg_bytes()
    while True:
        _frame_index += 1
        _last_detection_count = len(_mock_points()) if _detection_enabled else len(_detected_points)
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        time.sleep(0.25)


@app.get("/")
def root():
    return FileResponse(Path(__file__).with_name("hk_full_app.html"))


@app.get("/health")
def health():
    return {
        "ok": True,
        "camera_ready": True,
        "laser_ready": True,
        "target_ready": True,
        "galvo_ready": True,
        "detector_ready": True,
        "homography_loaded": True,
        "last_frame_index": _frame_index,
        "frame_age_ms": 12.0,
        "mock": True,
    }


@app.get("/frame/meta")
def frame_meta():
    return {
        "ok": True,
        "frame_index": _frame_index,
        "width": NATIVE_W,
        "height": NATIVE_H,
        "stream_width": STREAM_W,
        "stream_height": STREAM_H,
        "frame_age_ms": 12.0,
    }


@app.get("/stats")
def stats():
    return {
        "ok": True,
        "camera": {
            "frame_index": _frame_index,
            "read_fail_count": 0,
            "frame_age_ms": 12.0,
            "interval_min_ms": 240.0,
            "interval_avg_ms": 250.0,
            "interval_max_ms": 260.0,
            "measured_fps": 4.0,
        },
        "settings": {
            "width": 2592,
            "height": 1944,
            "fps": 5.0,
            "fourcc": "MJPG",
            "auto_exposure": 3,
            "exposure": 1000,
            "buffer_size": 2,
            "auto_wb": 1,
        },
        "stream": {"width": STREAM_W, "height": STREAM_H, "window_s": 0.25},
        "detection_enabled": _detection_enabled,
        "detection_count": _last_detection_count,
        "red_dot_enabled": _red_dot_enabled,
        "homography_loaded": True,
        "detected_points": len(_detected_points),
        "walking": _walking,
        "mock": True,
    }


@app.get("/frame/current")
def stream_video():
    return StreamingResponse(_generate_camera(), media_type="multipart/x-mixed-replace; boundary=frame")


@app.get("/sse/detection")
def sse_detection():
    def event_stream():
        last_count = -1
        while True:
            count = len(_mock_points()) if _detection_enabled else len(_detected_points)
            if count != last_count:
                last_count = count
                yield f"data: {json.dumps({'type': 'detection_count', 'count': count})}\n\n"
            time.sleep(0.1)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/sse/galvo_pos")
def sse_galvo_pos():
    def event_stream():
        last = None
        while True:
            current = tuple(_mover_pos)
            if current != last:
                last = current
                yield f"data: {json.dumps({'x': _mover_pos[0], 'y': _mover_pos[1]})}\n\n"
            time.sleep(0.2)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/app/errors")
def get_app_errors():
    return {
        "state": _ok("APP_GET_STATE", "RUNNING"),
        "last_error": _ok("APP_GET_LAST_ERROR", "No error,APP_ERROR_NONE"),
        "events": list(_app_error_events),
    }


@app.get("/app/errors/events")
def get_app_error_events():
    return {"events": list(_app_error_events)}


@app.post("/app/errors/clear")
def clear_app_errors():
    global _red_dot_enabled
    _red_dot_enabled = False
    _app_error_events.clear()
    return {"response": _ok("APP_CLEAR_ERROR")}


@app.get("/app/test/status")
def get_app_test_status():
    return {
        "state": _ok("APP_GET_STATE", "RUNNING"),
        "last_error": _ok("APP_GET_LAST_ERROR", "No error,APP_ERROR_NONE"),
        "laser_test_result": _ok("APP_GET_LASER_TEST_RESULT", "OK"),
        "fw_version": _ok("APP_GET_FW_VERSION", "MOCK_FW_1.0.0"),
        "hw_version": _ok("APP_GET_HW_VERSION", "MOCK_HW_1.0"),
        "proc_time": _ok("APP_GET_PROC_TIME", str(_uptime_ms())),
        "events": list(_test_events),
    }


@app.get("/app/test/events")
def get_app_test_events():
    return {"events": list(_test_events)}


@app.post("/app/ping")
def app_ping():
    return {"response": _ok("APP_PING", "PONG")}


@app.get("/app/commands")
def get_app_commands():
    commands = ",".join(sorted(COMMANDS)) if COMMANDS else "APP_PING,LASER_FIRE,TARGET_START"
    return {"response": _ok("APP_GET_COMMANDS", commands)}


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
        return JSONResponse(status_code=404, content={"error": f"Unknown command: {normalized}", "command": normalized})
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
    return {"response": _ok("APP_GET_LIMITS", "maxFireDuration=1000,maxTargets=256")}


@app.post("/app/reset")
def app_reset():
    global _armed, _laser_active, _red_dot_enabled, _sequence_state
    _armed = False
    _laser_active = False
    _red_dot_enabled = False
    _sequence_state = "IDLE"
    return {"response": _ok("APP_RESET")}


@app.get("/app/proc_time")
def get_app_proc_time():
    return {"response": _ok("APP_GET_PROC_TIME", str(_uptime_ms()))}


@app.post("/app/laser_test/start")
def start_app_laser_power_test():
    _append_test_event("laser_power_test", "OK")
    return {"response": _ok("APP_DO_LASER_PWR_TEST")}


@app.get("/app/laser_test/result")
def get_app_laser_test_result():
    return {"response": _ok("APP_GET_LASER_TEST_RESULT", "OK")}


@app.get("/app/laser_test/data")
def get_app_laser_test_data():
    return {"response": _ok("APP_GET_LASER_TEST_DATA", "808=20,980=25,1064=50")}


@app.get("/app/fw_version")
def get_app_fw_version():
    return {"response": _ok("APP_GET_FW_VERSION", "MOCK_FW_1.0.0")}


@app.get("/app/hw_version")
def get_app_hw_version():
    return {"response": _ok("APP_GET_HW_VERSION", "MOCK_HW_1.0")}


@app.get("/app/state")
def get_app_state():
    return {"response": _ok("APP_GET_STATE", "RUNNING")}


@app.get("/app/last_error")
def get_app_last_error():
    return {"response": _ok("APP_GET_LAST_ERROR", "No error,APP_ERROR_NONE")}


@app.post("/app/clear_error")
def clear_app_last_error():
    global _red_dot_enabled
    _red_dot_enabled = False
    _app_error_events.clear()
    return {"response": _ok("APP_CLEAR_ERROR")}


@app.post("/app/raw_command")
def app_raw_command(payload: RawCommandRequest):
    command = str(payload.command).strip()
    if not command:
        return JSONResponse(status_code=400, content={"error": "Command is empty"})
    name = command.split()[0]
    if name == "SENSORS_GET_VALUES":
        response = _raw_sensor_line(_sensor_values())
    elif name.endswith("GET_STATE"):
        response = _ok(name, "RUNNING" if name.startswith("APP") else "MOCK_STATE_IDLE")
    elif name.endswith("GET_LAST_ERROR"):
        response = _ok(name, "No error,MOCK_ERROR_NONE")
    else:
        response = _ok_arg(name, command[len(name):].strip() or "~")
    return {"command": command, "response": response}


@app.get("/seq/status")
def get_sequence_status():
    return {
        "state": _ok("TARGET_GET_STATE", _sequence_state),
        "mode": _ok("TARGET_GET_MODE", f"TARGET_MODE_{_sequence_mode}"),
        "last_error": _ok("TARGET_GET_LAST_ERROR", "No error,TARGET_ERROR_NONE"),
        "target_count": _target_count(),
        "show_target_points_overlay": _show_target_points_overlay,
        "events": list(_sequence_events),
    }


@app.get("/seq/events")
def get_sequence_events():
    return {"events": list(_sequence_events)}


@app.get("/mover/pos")
def get_mover_pos():
    return {"x": _mover_pos[0], "y": _mover_pos[1]}


@app.post("/mover/move")
def move_to(x: int = Query(...), y: int = Query(...)):
    _mover_pos[:] = [_clamp_int(x, 0, 4095), _clamp_int(y, 0, 4095)]
    return {"new_position": _mover_pos[:]}


@app.post("/mover/direction")
def move_direction(direction: str = Query(...), step: int = Query(25)):
    x, y = _mover_pos
    if direction == "up":
        y -= step
    elif direction == "down":
        y += step
    elif direction == "left":
        x -= step
    elif direction == "right":
        x += step
    _mover_pos[:] = [_clamp_int(x, 0, 4095), _clamp_int(y, 0, 4095)]
    return {"new_position": _mover_pos[:]}


@app.post("/mover/move_image")
def move_to_image(x: int = Query(...), y: int = Query(...)):
    native_x = round(x * NATIVE_W / STREAM_W)
    native_y = round(y * NATIVE_H / STREAM_H)
    target = _native_to_galvo(native_x, native_y)
    _mover_pos[:] = target
    return {"image": [x, y], "native_image": [native_x, native_y], "target": target, "new_position": _mover_pos[:]}


@app.post("/detection/toggle")
def toggle_detection(enabled: bool = Query(...)):
    global _detection_enabled, _last_detection_count
    _detection_enabled = enabled
    _last_detection_count = len(_mock_points()) if enabled else len(_detected_points)
    return {"detection_enabled": _detection_enabled, "conf": _detection_conf}


@app.get("/detection/status")
def get_detection_status():
    return {"detection_enabled": _detection_enabled, "conf": _detection_conf, "red_dot": _red_dot_enabled}


@app.post("/detection/conf")
def set_detection_conf(conf: float = Query(...)):
    global _detection_conf
    _detection_conf = max(0.01, min(1.0, float(conf)))
    return {"conf": _detection_conf}


@app.post("/detection/capture")
def capture_detections():
    global _detected_points, _last_detection_count
    _detected_points = _mock_points()
    _last_detection_count = len(_detected_points)
    return {"captured": len(_detected_points), "points": _detected_points}


@app.get("/points/list")
def get_detected_points():
    return {"points": _detected_points, "count": len(_detected_points)}


@app.post("/points/clear")
def clear_detected_points():
    global _detected_points, _last_detection_count
    _detected_points = []
    _last_detection_count = 0
    return {"status": "cleared"}


@app.post("/homography/reload")
def reload_homography():
    return {"status": "reloaded"}


@app.post("/walk/start")
def start_walking():
    global _walking
    if not _detected_points:
        return JSONResponse(status_code=400, content={"error": "No points"})
    _walking = True
    visited = []
    for img_pt in _nearest_neighbor(_detected_points):
        if not _walking:
            break
        target = _native_to_galvo(img_pt[0], img_pt[1])
        _mover_pos[:] = target
        visited.append({"target": target, "actual": _mover_pos[:]})
        time.sleep(0.02)
    _walking = False
    return {"status": "completed", "visited": visited}


@app.post("/walk/stop")
def stop_walking():
    global _walking
    _walking = False
    return {"status": "stopped"}


@app.post("/laser/arm_en")
def set_laser_arm_enabled(enabled: bool = Query(...)):
    global _armed
    _armed = enabled
    peltier = {"status": _ok("PELTIER_GET_COOLING_EN", "1"), "enable": None, "enabled": True} if enabled else None
    return {"response": _ok_arg("LASER_SET_ARM_EN", _bool_str(enabled)), "enabled": enabled, "peltier": peltier}


@app.get("/laser/arm_en")
def get_laser_arm_enabled():
    return {"response": _ok("LASER_GET_ARM_EN", _bool_str(_armed))}


@app.post("/laser/arm")
def arm_laser():
    global _armed
    _armed = True
    return {
        "response": _ok_arg("LASER_SET_ARM_EN", "1"),
        "peltier": {"status": _ok("PELTIER_GET_COOLING_EN", "1"), "enable": None, "enabled": True},
    }


@app.post("/laser/disarm")
def disarm_laser():
    global _armed, _laser_active
    _armed = False
    _laser_active = False
    return {"response": _ok_arg("LASER_SET_ARM_EN", "0")}


@app.post("/laser/ack")
def ack_errors():
    return {"response": _ok("LASER_CLEAR_ERROR")}


@app.post("/laser/clear_error")
def clear_laser_error():
    global _red_dot_enabled
    _red_dot_enabled = False
    return {"response": _ok("LASER_CLEAR_ERROR")}


@app.get("/laser/last_error")
def get_laser_last_error():
    return {"response": _ok("LASER_GET_LAST_ERROR", "No error,LASER_ERROR_NONE")}


@app.post("/laser/pwr")
def set_laser_pwr(laser_id: int = Query(...), pwr: int = Query(...)):
    pwr = _clamp_int(pwr, 0, 100)
    if laser_id == 1:
        _channel_power["p1064"] = pwr
    elif laser_id == 2:
        _channel_power["p980"] = pwr
    elif laser_id == 3:
        _channel_power["p808"] = pwr
    elif laser_id == 4:
        _channel_power.update({"p808": pwr, "p980": pwr, "p1064": pwr})
    else:
        return {"response": [f"ERROR: invalid laser_id {laser_id}"]}
    return {"response": _ok_arg("LASER_SET_CHANNEL_PWR", f"{_channel_power['p808']},{_channel_power['p980']},{_channel_power['p1064']}")}


@app.post("/laser/channel_pwr")
def set_laser_channel_power(p808: int = Query(...), p980: int = Query(...), p1064: int = Query(...)):
    _channel_power.update(
        {
            "p808": _clamp_int(p808, 0, 100),
            "p980": _clamp_int(p980, 0, 100),
            "p1064": _clamp_int(p1064, 0, 100),
        }
    )
    for key, value in _channel_power.items():
        _active_channels[key] = value > 0
    return {
        "response": _ok_arg("LASER_SET_CHANNEL_PWR", f"{_channel_power['p808']},{_channel_power['p980']},{_channel_power['p1064']}"),
        "power": dict(_channel_power),
        "pending_sync": _pending_sync,
        "active": dict(_active_channels),
    }


@app.get("/laser/channel_pwr")
def get_laser_channel_power():
    raw = dict(_channel_power)
    return {
        "response": _ok("LASER_GET_CHANNEL_PWR", f"{raw['p808']},{raw['p980']},{raw['p1064']}"),
        "power": dict(_channel_power),
        "raw_power": raw,
        "pending_sync": _pending_sync,
        "active": dict(_active_channels),
    }


@app.post("/laser/active")
def set_active_lasers(
    l1064: int = Query(1),
    l980: int = Query(1),
    l808: int = Query(1),
    l660: int | None = Query(None),
):
    global _red_dot_enabled
    _active_channels.update({"p808": bool(l808), "p980": bool(l980), "p1064": bool(l1064)})
    if l660 is not None:
        _red_dot_enabled = bool(l660)
    return {
        "response": _ok_arg(
            "LASER_SET_CHANNEL_PWR",
            f"{_channel_power['p808'] if _active_channels['p808'] else 0},"
            f"{_channel_power['p980'] if _active_channels['p980'] else 0},"
            f"{_channel_power['p1064'] if _active_channels['p1064'] else 0}",
        ),
        "active": [bool(l1064), bool(l980), bool(l808)],
        "red_dot": _red_dot_enabled,
    }


@app.post("/laser/current")
def set_las_curr(curr: int = Query(...)):
    curr = _clamp_int(curr, 0, 100)
    for key, enabled in _active_channels.items():
        if enabled:
            _channel_power[key] = curr
    return {"response": _ok_arg("LASER_SET_CHANNEL_PWR", f"{_channel_power['p808']},{_channel_power['p980']},{_channel_power['p1064']}"), "current": curr}


@app.get("/laser/temp")
def get_laser_temp():
    return {"temp": round(_sensor_values()["laserTemp_C"], 2)}


@app.get("/sensors/values")
def get_sensor_values():
    values = _sensor_values()
    return {"values": values, "raw": _raw_sensor_line(values)}


@app.post("/laser/pulse")
def set_las_pulse(pulse_ms: int = Query(...)):
    global _pulse_ms
    _pulse_ms = _clamp_int(pulse_ms, 10, 1000)
    return {"response": [f"PULSE_MS={_pulse_ms}"], "pulse_ms": _pulse_ms}


@app.get("/laser/settings")
def get_laser_settings():
    return {
        "response": {
            "arm": _ok("LASER_GET_ARM_EN", _bool_str(_armed)),
            "power": _ok("LASER_GET_CHANNEL_PWR", f"{_channel_power['p808']},{_channel_power['p980']},{_channel_power['p1064']}"),
        },
        "armed": _armed,
        "power": dict(_channel_power),
        "pulse_ms": _pulse_ms,
        "pending_sync": _pending_sync,
        "targets_count": _target_count(),
    }


@app.post("/laser/settings")
def update_laser_settings(settings: LaserSettingsRequest):
    global _armed, _pulse_ms
    responses: dict[str, Any] = {}
    if not settings.armed:
        _armed = False
        responses["arm"] = _ok_arg("LASER_SET_ARM_EN", "0")
    _channel_power.update(
        {
            "p808": _clamp_int(settings.p808, 0, 100),
            "p980": _clamp_int(settings.p980, 0, 100),
            "p1064": _clamp_int(settings.p1064, 0, 100),
        }
    )
    _pulse_ms = _clamp_int(settings.pulse_ms, 10, 1000)
    responses["power"] = _ok_arg("LASER_SET_CHANNEL_PWR", f"{_channel_power['p808']},{_channel_power['p980']},{_channel_power['p1064']}")
    responses["pulse"] = [f"PULSE_MS={_pulse_ms}"]
    targets_reloaded = False
    if settings.reload_targets and _targets:
        responses["targets"] = [f"TARGET_COUNT={_target_count()}"]
        targets_reloaded = True
    if settings.armed:
        _armed = True
        responses["peltier"] = {"status": _ok("PELTIER_GET_COOLING_EN", "1"), "enable": None, "enabled": True}
        responses["arm"] = _ok_arg("LASER_SET_ARM_EN", "1")
    return {
        "response": responses,
        "armed": _armed,
        "power": dict(_channel_power),
        "pulse_ms": _pulse_ms,
        "pending_sync": _pending_sync,
        "targets_reloaded": targets_reloaded,
        "targets_count": _target_count(),
    }


@app.post("/laser/red_dot")
def set_red_dot(enabled: bool = Query(...)):
    global _red_dot_enabled
    _red_dot_enabled = enabled
    return {"response": _ok_arg("LASER_SET_RED_DOT_EN", _bool_str(enabled)), "enabled": enabled}


@app.post("/laser/red_dot_en")
def set_laser_red_dot_enabled(enabled: bool = Query(...)):
    return set_red_dot(enabled)


@app.get("/laser/red_dot_en")
def get_laser_red_dot_enabled():
    return {"response": _ok("LASER_GET_RED_DOT_EN", _bool_str(_red_dot_enabled))}


@app.post("/laser/fire")
def fire_laser(duration_ms: int = Query(...)):
    global _laser_active
    duration_ms = _clamp_int(duration_ms, 10, 1000)
    _laser_active = True
    return {"response": _ok_arg("LASER_FIRE", str(duration_ms)), "duration_ms": duration_ms}


@app.post("/laser/stop")
def stop_laser():
    global _laser_active
    _laser_active = False
    return {"response": _ok("LASER_STOP")}


@app.get("/laser/is_active")
def get_laser_is_active():
    return {"response": _ok("LASER_IS_ACTIVE", _bool_str(_laser_active))}


@app.get("/laser/state")
def get_laser_state():
    if _laser_active:
        state = "LASER_STATE_FIRING"
    elif _armed:
        state = "LASER_STATE_ARMED_IDLE"
    else:
        state = "LASER_STATE_DISARMED"
    return {"response": _ok("LASER_GET_STATE", state)}


@app.post("/seq/length")
def set_seq_length(length: int = Query(...)):
    length = _clamp_int(length, 0, 256)
    for idx in sorted(list(_targets)):
        if idx >= length:
            del _targets[idx]
    return {"response": [f"SEQ_LEN={length}"], "length": length}


@app.get("/coords/convert")
def convert_image_to_galvo(ix: int = Query(...), iy: int = Query(...)):
    x, y = _native_to_galvo(ix, iy)
    return {"x": x, "y": y}


@app.post("/seq/target")
def set_target_point(idx: int = Query(...), x: int = Query(...), y: int = Query(...)):
    idx = _clamp_int(idx, 0, 255)
    _targets[idx] = [_clamp_int(x, 0, 4095), _clamp_int(y, 0, 4095)]
    return {"response": [f"TARGET[{idx}]={_targets[idx][0]},{_targets[idx][1]}"], "idx": idx, "x": x, "y": y}


@app.post("/seq/show_targets")
def set_show_target_points(enabled: bool = Query(...)):
    global _show_target_points_overlay
    _show_target_points_overlay = enabled
    return {"show_target_points_overlay": _show_target_points_overlay, "targets_count": _target_count()}


@app.post("/seq/update_targets")
def update_sequence_targets():
    original_count = len(_detected_points)
    if not _detected_points:
        return JSONResponse(status_code=400, content={"error": "No points"})
    points = _detected_points[:MAX_SEQUENCE_TARGETS]
    start = time.perf_counter()
    resp = _load_targets_from_points(points)
    return {
        "response": resp,
        "targets_count": _target_count(),
        "detected_count": original_count,
        "max_targets": MAX_SEQUENCE_TARGETS,
        "truncated": original_count > len(points),
        "targets": [xy for _, xy in sorted(_targets.items())],
        "load_ms": round((time.perf_counter() - start) * 1000.0, 1),
    }


@app.post("/seq/clear_targets")
def clear_sequence_targets():
    _targets.clear()
    return {"response": _ok("TARGET_CLEAR_TARGETS"), "targets_count": 0}


@app.post("/seq/mode")
def set_sequence_mode(mode: str = Query(...)):
    global _sequence_mode
    normalized = str(mode).strip().lower()
    if normalized in {"manual", "single", "step"}:
        _sequence_mode = "MANUAL"
        mode_value = 0
    elif normalized in {"auto", "all"}:
        _sequence_mode = "AUTO"
        mode_value = 1
    else:
        return JSONResponse(status_code=400, content={"error": f"Unsupported target mode: {mode}"})
    return {"response": _ok_arg("TARGET_SET_MODE", str(mode_value)), "mode": _sequence_mode}


@app.get("/seq/mode")
def get_sequence_mode():
    return {"response": _ok("TARGET_GET_MODE", f"TARGET_MODE_{_sequence_mode}")}


@app.post("/seq/start")
def start_seq():
    global _sequence_state
    _sequence_state = "RUNNING"
    _append_sequence_event("OK")
    _sequence_state = "IDLE"
    return {"response": _ok("TARGET_START"), "targets_count": _target_count()}


@app.post("/seq/start_test")
def start_seq_test():
    return start_seq()


@app.post("/seq/stop")
def stop_seq():
    global _sequence_state
    _sequence_state = "STOPPED"
    return {"response": _ok("TARGET_STOP"), "targets_count": _target_count()}


@app.post("/seq/halt")
def halt_seq():
    global _sequence_state
    _sequence_state = "HALTED"
    return {"response": _ok("TARGET_HALT"), "targets_count": _target_count()}


@app.post("/seq/step")
def step_seq():
    global _sequence_mode
    state = _ok("TARGET_GET_STATE", _sequence_state)
    if _sequence_state == "IDLE":
        _sequence_mode = "MANUAL"
        resp = _ok("TARGET_START")
        _append_sequence_event("OK")
    else:
        resp = _ok("TARGET_CONTINUE")
    return {"response": resp, "state": state, "targets_count": _target_count()}


@app.post("/fire/walk")
def fire_walk(test_mode: bool = Query(False)):
    if not _detected_points:
        return JSONResponse(status_code=400, content={"error": "No points"})
    points = _nearest_neighbor(_detected_points)
    load_resp = _load_targets_from_points(points)
    _append_sequence_event("OK")
    return {
        "status": "firing",
        "test_mode": test_mode,
        "targets_count": _target_count(),
        "response": {"load": load_resp, "start": _ok("TARGET_START")},
    }
