#!/usr/bin/env python3
"""Command-line preflight checklist for hk_full_app.

This script checks the main runtime dependencies used by hk_full_app.py:
- Python package imports
- Required local files
- CUDA/model readiness for YOLO inference
- Serial controller availability and basic protocol responses
- Camera availability and frame capture

Exit code:
- 0: all required checks passed
- 1: one or more required checks failed
"""

from __future__ import annotations

import argparse
import importlib
import sys
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
            print(f"[{status:<4}] {result.name}: {result.message}")

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


def check_required_file(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing: {path}"
    if not path.is_file():
        return False, f"not a file: {path}"
    return True, str(path)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Preflight checklist for app/hk_full_app.py")
    parser.add_argument("--port", default="/dev/ttyACM0", help="Serial controller port")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate")
    parser.add_argument("--timeout", type=float, default=0.4, help="Serial read timeout in seconds")
    parser.add_argument(
        "--skip-model-load",
        action="store_true",
        help="Skip loading the YOLO model file and only check that it exists",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    model_path = ROOT / "model" / "follicle_exit_v11i_yolov8n_20250513.pt"
    transform_path = ROOT / "transformation_matrix.txt"
    html_path = ROOT / "app" / "hk_full_app.html"

    checklist = Checklist()

    for module_name in (
        "fastapi",
        "uvicorn",
        "cv2",
        "serial",
        "numpy",
        "pydantic",
        "turbojpeg",
        "torch",
        "ultralytics",
        "sklearn",
    ):
        checklist.run(f"Python import: {module_name}", lambda mn=module_name: check_import(mn))

    checklist.run("Required file: model", lambda: check_required_file(model_path))
    checklist.run("Required file: homography", lambda: check_required_file(transform_path))
    checklist.run("Required file: HTML UI", lambda: check_required_file(html_path))

    checklist.run("CUDA available", check_torch_cuda)
    if args.skip_model_load:
        checklist.add("YOLO model load", True, "skipped by --skip-model-load")
    else:
        checklist.run("YOLO model load", lambda: check_yolo_model_load(model_path))

    checklist.run("Found serial ports", list_found_serial_ports, required=False)
    checklist.run("Serial port present", lambda: check_serial_port_presence(args.port))
    checklist.run(
        "Serial controller handshake",
        lambda: check_serial_handshake(args.port, args.baud, args.timeout),
    )

    checklist.run("Found camera devices", list_found_camera_devices, required=False)
    checklist.run("Camera device path", check_camera_device_path)
    checklist.run("Camera stream", check_camera_stream)

    checklist.print_report()

    if checklist.exit_code() == 0:
        print("Ready to start: uvicorn app.hk_full_app:app --reload")
    else:
        print("Not ready: fix the FAIL items before starting hk_full_app.")

    return checklist.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
