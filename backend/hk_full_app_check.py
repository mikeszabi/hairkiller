#!/usr/bin/env python3
"""Command-line preflight checklist for the consolidated backend app.

This script checks the main runtime dependencies used by backend/hk_backend_app.py:
- Python package imports as one grouped check
- Required local files as one grouped check
- CUDA/model readiness for YOLO inference
- Microcontroller device-node/backend liveness without opening a new serial connection
- Camera device-node/backend liveness without opening a new camera connection

Exit code:
- 0: all required checks passed
- 1: one or more required checks failed
"""

from __future__ import annotations

import argparse, importlib, json, sys, time, urllib.error, urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parent.parent
CODE_DIR = ROOT / "code"

if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))
if str(CODE_DIR) not in sys.path:
    sys.path.append(str(CODE_DIR))


@dataclass
class CheckResult:
    name: str
    ok: bool
    message: str
    required: bool = True


class Checklist:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def add(self, name: str, ok: bool, message: str, required: bool = True) -> None:
        self.results.append(CheckResult(name=name, ok=ok, message=message, required=required))

    def run(self, name: str, fn: Callable[[], tuple[bool, str]], required: bool = True) -> None:
        try:
            ok, message = fn()
        except Exception as exc:
            ok, message = False, f"{type(exc).__name__}: {exc}"
        self.add(name, ok, message, required=required)

    def print_report(self) -> None:
        print("hk_full_app preflight checklist")
        print("=" * 32)
        for result in self.results:
            status = "OK" if result.ok else ("WARN" if not result.required else "FAIL")
            detail = result.message if result.message else ""
            if result.ok and status == "OK" and detail:
                detail = f": {detail}"
            elif not result.ok:
                detail = f": {detail or 'no failure cause reported'}"
            else:
                detail = ""
            print(f"[{status:<4}] {result.name}{detail}")

        required_failures = [r for r in self.results if r.required and not r.ok]
        optional_failures = [r for r in self.results if (not r.required) and (not r.ok)]

        print("-" * 32)
        print(
            f"Summary: {len(self.results) - len(required_failures) - len(optional_failures)} passed, "
            f"{len(required_failures)} required failed, {len(optional_failures)} optional warnings"
        )

    def exit_code(self) -> int:
        return 1 if any((not r.ok) and r.required for r in self.results) else 0


def check_import(module_name: str) -> tuple[bool, str]:
    module = importlib.import_module(module_name)
    version = getattr(module, "__version__", None)
    if version:
        return True, f"imported ({version})"
    return True, "imported"


def check_python_imports(module_names: tuple[str, ...]) -> tuple[bool, str]:
    failures: list[str] = []

    for module_name in module_names:
        try:
            check_import(module_name)
        except Exception as exc:
            failures.append(f"{module_name}: {type(exc).__name__}: {exc}")

    if failures:
        return False, "; ".join(failures)
    return True, f"all required imports available ({', '.join(module_names)})"


def check_required_file(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing: {path}"
    if not path.is_file():
        return False, f"not a file: {path}"
    return True, str(path)


def check_required_files(paths: tuple[Path, ...]) -> tuple[bool, str]:
    failures: list[str] = []

    for path in paths:
        ok, message = check_required_file(path)
        if not ok:
            failures.append(message)

    if failures:
        return False, "; ".join(failures)
    return True, "all required files present"


def check_torch_cuda() -> tuple[bool, str]:
    import torch

    if not torch.cuda.is_available():
        return False, "torch.cuda.is_available() is False"

    try:
        gpu_name = torch.cuda.get_device_name(0)
    except Exception:
        gpu_name = "CUDA device available"
    return True, gpu_name


def check_yolo_model_load(model_path: Path) -> tuple[bool, str]:
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    model_name = getattr(model, "ckpt_path", None) or model_path.name
    return True, f"loaded {model_name}"


def check_serial_port_presence(port: str) -> tuple[bool, str]:
    from serial_devices_handler import list_serial_ports

    ports = list_serial_ports()
    if port in ports:
        return True, f"found in available ports: {', '.join(ports)}"
    if Path(port).exists():
        return True, f"device node exists but was not listed by pyserial: {port}"
    if ports:
        return False, f"{port} not found; available: {', '.join(ports)}"
    return False, f"{port} not found; no serial ports detected"


def list_found_serial_ports() -> tuple[bool, str]:
    ports: list[str] = []

    try:
        from serial_devices_handler import list_serial_ports

        ports.extend(list_serial_ports())
    except Exception:
        pass

    for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*", "/dev/ttyTHS*"):
        for path in sorted(Path("/dev").glob(pattern.replace("/dev/", ""))):
            ports.append(str(path))

    unique_ports = sorted(dict.fromkeys(ports))
    if unique_ports:
        return True, ", ".join(unique_ports)
    return False, "none found"


def check_serial_handshake(port: str, baud: int, timeout_s: float) -> tuple[bool, str]:
    from serial_devices_handler import SerialDevice

    dev = SerialDevice(port=port, baud=baud, timeout_s=timeout_s, debug=False)
    try:
        dev.open()

        ping = dev.query("APP_PING", expect_prefix="APP_PING", extra_read_window_s=0.3)
        if not any("APP_PING" in line for line in ping):
            return False, f"APP_PING did not return expected reply: {ping}"

        fw = dev.query("APP_GET_FW_VERSION", expect_prefix="APP_GET_FW_VERSION", extra_read_window_s=0.3)
        app_state = dev.query("APP_GET_STATE", expect_prefix="APP_GET_STATE", extra_read_window_s=0.3)
        sensors = dev.query("SENSORS_GET_VALUES", expect_prefix="SENSORS_GET_VALUES", extra_read_window_s=0.4)

        details = []
        if fw:
            details.append(f"fw={fw[0]}")
        if app_state:
            details.append(f"state={app_state[0]}")
        if sensors:
            details.append("sensors=OK")
        else:
            details.append("sensors=no response")

        return True, ", ".join(details)
    finally:
        dev.close()


def _read_json_url(url: str, timeout_s: float) -> dict:
    with urllib.request.urlopen(url, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def _post_json_url(url: str, payload: dict | None, timeout_s: float) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


def check_backend_microcontroller(api_base: str, timeout_s: float = 6.0) -> tuple[bool, str]:
    base = api_base.rstrip("/")
    ping_url = f"{base}/app/ping?t={int(time.time() * 1000)}"

    try:
        payload = _post_json_url(ping_url, None, timeout_s)
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return False, f"backend app ping failed at {ping_url}: HTTP {exc.code}: {detail}"
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return False, f"backend app ping failed at {ping_url}: {type(exc).__name__}: {exc}"

    response = payload.get("response")
    lines = response if isinstance(response, list) else [response]
    if any("[APP_PING]" in str(line) and "[OK]" in str(line) for line in lines):
        return True, f"backend APP_PING OK: {lines[0]}"
    if any("OK" in str(line).upper() for line in lines):
        return True, f"backend app ping returned OK: {response}"
    return False, f"backend APP_PING did not return OK: {response}"


def check_microcontroller(
    port: str,
    baud: int,
    timeout_s: float,
    backend_api_base: str | None = None,
    allow_hardware_open: bool = False,
) -> tuple[bool, str]:
    try:
        port_ok, port_message = check_serial_port_presence(port)
        if not port_ok:
            return False, port_message

        if backend_api_base:
            backend_ok, backend_message = check_backend_microcontroller(backend_api_base)
            return backend_ok, f"{port_message}; {backend_message}"

        if not allow_hardware_open:
            return True, f"{port_message}; serial handshake skipped to avoid opening a second connection"

        return check_serial_handshake(port, baud, timeout_s)
    except Exception as exc:
        _, found_ports = list_found_serial_ports()
        return False, f"{port} serial check failed: {type(exc).__name__}: {exc}; available ports: {found_ports}"


def check_camera_device_path() -> tuple[bool, str]:
    from camera_handler import DEV

    if Path(DEV).exists():
        return True, DEV
    return False, f"missing camera device path: {DEV}"


def list_found_camera_devices() -> tuple[bool, str]:
    devices: list[str] = []

    for path in sorted(Path("/dev").glob("video*")):
        devices.append(str(path))

    by_id_dir = Path("/dev/v4l/by-id")
    if by_id_dir.exists():
        for path in sorted(by_id_dir.iterdir()):
            devices.append(str(path))

    unique_devices = sorted(dict.fromkeys(devices))
    if unique_devices:
        return True, ", ".join(unique_devices)
    return False, "none found"


def check_camera_stream() -> tuple[bool, str]:
    import cv2
    from camera_handler import DEV, H, FOURCC, FPS, W, open_cam

    cap = open_cam(dev=DEV, width=W, height=H, fps=FPS, fourcc=FOURCC)
    if cap is None:
        return False, f"OpenCV could not open {DEV}"

    try:
        ok, frame = cap.read()
        if not ok or frame is None:
            return False, "camera opened but no frame was captured"

        height, width = frame.shape[:2]
        negotiated_fps = cap.get(cv2.CAP_PROP_FPS)
        return True, f"frame={width}x{height}, fps={negotiated_fps}"
    finally:
        cap.release()


def check_backend_camera_status(api_base: str, timeout_s: float = 6.0) -> tuple[bool, str]:
    base = api_base.rstrip("/")
    health_url = f"{base}/health?t={int(time.time() * 1000)}"

    try:
        health = _read_json_url(health_url, timeout_s)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return False, f"backend health check failed at {health_url}: {type(exc).__name__}: {exc}"

    if not health.get("camera_ready"):
        return False, f"backend reports camera not ready: {health.get('camera_error') or health}"

    frame = health.get("last_frame_index")
    age = health.get("frame_age_ms")
    return True, f"backend camera ready via {health_url}, frame={frame}, age_ms={age}"


def check_camera(
    backend_api_base: str | None = None,
    allow_hardware_open: bool = False,
) -> tuple[bool, str]:
    if backend_api_base:
        return check_backend_camera_status(backend_api_base)

    device_ok, device_message = check_camera_device_path()
    if not device_ok:
        _, found_devices = list_found_camera_devices()
        return False, f"{device_message}; available camera devices: {found_devices}"

    if not allow_hardware_open:
        return True, f"{device_message}; camera stream check skipped to avoid opening a second connection"

    try:
        return check_camera_stream()
    except Exception as exc:
        _, found_devices = list_found_camera_devices()
        return False, (
            f"camera stream failed: {type(exc).__name__}: {exc}; "
            f"configured device: {device_message}; available camera devices: {found_devices}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight checklist for backend/hk_backend_app.py")
    parser.add_argument("--port", default="/dev/ttyACM0", help="Serial controller port")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--timeout", type=float, default=0.4, help="Serial read timeout in seconds")
    parser.add_argument(
        "--skip-model-load",
        action="store_true",
        help="Skip loading the YOLO model file and only check that it exists",
    )
    parser.add_argument(
        "--backend-api-base",
        default="",
        help="Check already-running backend endpoints instead of opening hardware devices directly",
    )
    parser.add_argument(
        "--allow-hardware-open",
        action="store_true",
        help="Allow this script to open serial/camera devices directly. Use only when the backend service is stopped.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    model_path = ROOT / "model" / "follicle_exit_v11i_yolov8n_20250513.pt"
    transform_path = ROOT / "transformation_matrix.txt"
    checklist = Checklist()

    required_modules = (
        "fastapi",
        "uvicorn",
        "cv2",
        "serial",
        "numpy",
        "pydantic",
        "torch",
        "ultralytics",
        "sklearn",
    )

    checklist.run("Python imports", lambda: check_python_imports(required_modules))
    checklist.run("Required files", lambda: check_required_files((model_path, transform_path)))

    checklist.run("CUDA available", check_torch_cuda)
    if args.skip_model_load:
        checklist.add("YOLO model load", True, "skipped by --skip-model-load")
    else:
        checklist.run("YOLO model load", lambda: check_yolo_model_load(model_path))

    checklist.run(
        f"Microcontroller {args.port}",
        lambda: check_microcontroller(
            args.port,
            args.baud,
            args.timeout,
            backend_api_base=args.backend_api_base or None,
            allow_hardware_open=args.allow_hardware_open,
        ),
    )

    checklist.run(
        "Camera",
        lambda: check_camera(
            args.backend_api_base or None,
            allow_hardware_open=args.allow_hardware_open,
        ),
    )

    checklist.print_report()

    if checklist.exit_code() == 0:
        print("Ready to start: uvicorn backend.hk_backend_app:app --reload --timeout-graceful-shutdown 1")
    else:
        print("Not ready: fix the FAIL items before starting hk_backend_app.")

    return checklist.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
