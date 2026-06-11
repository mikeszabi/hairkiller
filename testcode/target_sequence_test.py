#!/usr/bin/env python3
"""Interactive USB CDC targeting/fire test tool for LaserDriver firmware."""

from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import Iterable

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Missing dependency: pyserial")
    print(f"This script is running with: {sys.executable}")
    print(f"Install it for this interpreter with: \"{sys.executable}\" -m pip install pyserial")
    print("Or run this script explicitly with the Python where pyserial is installed:")
    print("  python targeting_console_test.py")
    raise SystemExit(2)


DEFAULT_BAUD = 115200
READ_TIMEOUT_S = 0.1
RESPONSE_TIMEOUT_S = 5.0
FINISH_TIMEOUT_S = 30.0


def elapsed_ms(start_s: float) -> float:
    return (time.perf_counter() - start_s) * 1000.0


@dataclass(frozen=True)
class TargetPoint:
    x: int
    y: int


class DeviceConsole:
    def __init__(self, port: str, baud: int) -> None:
        self.ser = serial.Serial(port=port, baudrate=baud, timeout=READ_TIMEOUT_S)
        self.lines: queue.Queue[str] = queue.Queue()
        self.stop_event = threading.Event()
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def close(self) -> None:
        self.stop_event.set()
        self.reader.join(timeout=1.0)
        self.ser.close()

    def _read_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                raw = self.ser.readline()
            except serial.SerialException as exc:
                print(f"\n[SERIAL ERROR] {exc}")
                self.stop_event.set()
                return

            if not raw:
                continue

            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue

            print(f"< {text}", flush=True)
            self.lines.put(text)

    def send(self, command: str) -> None:
        payload = (command.rstrip() + "\r\n").encode("ascii")
        print(f"> {command}", flush=True)
        self.ser.write(payload)
        self.ser.flush()

    def command_prefix(self, command: str) -> str:
        return command.split(maxsplit=1)[0].upper()

    def wait_for_command_result(self, command: str, timeout_s: float = RESPONSE_TIMEOUT_S) -> str:
        prefix = self.command_prefix(command)
        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=0.1)
            except queue.Empty:
                continue

            if not line.startswith(f"[{prefix}]"):
                continue

            if "->[OK]" in line:
                return line
            if "->[NOK]" in line:
                raise RuntimeError(f"{prefix} failed: {line}")

            # Query commands often return data rather than OK/NOK.
            if "->[UNKNOWN]" not in line:
                return line

        raise TimeoutError(f"Timed out waiting for response to {prefix}")

    def run_command(self, command: str, timeout_s: float = RESPONSE_TIMEOUT_S) -> str:
        start_s = time.perf_counter()
        self.send(command)
        result = self.wait_for_command_result(command, timeout_s)
        print(f"# {self.command_prefix(command)} acknowledged in {elapsed_ms(start_s):.1f} ms")
        return result

    def wait_for_line_containing(self, needle: str, timeout_s: float) -> str:
        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            try:
                line = self.lines.get(timeout=0.1)
            except queue.Empty:
                continue

            if needle in line:
                return line

        raise TimeoutError(f"Timed out waiting for line containing {needle!r}")


def list_serial_ports() -> None:
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return

    print("Available serial ports:")
    for item in ports:
        print(f"  {item.device}: {item.description}")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        answer = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not answer:
            return default
        if answer in {"y", "yes"}:
            return True
        if answer in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def ask_int(prompt: str, default: int, minimum: int, maximum: int) -> int:
    while True:
        answer = input(f"{prompt} [{default}]: ").strip()
        if not answer:
            return default
        try:
            value = int(answer, 0)
        except ValueError:
            print("Please enter an integer.")
            continue
        if minimum <= value <= maximum:
            return value
        print(f"Value must be in range {minimum}-{maximum}.")


def wait_for_enter(prompt: str) -> None:
    input(f"{prompt} Press Enter to continue.")


def generate_grid_points(count: int, min_xy: int, max_xy: int) -> list[TargetPoint]:
    cols = 10
    rows = (count + cols - 1) // cols
    points: list[TargetPoint] = []

    for row in range(rows):
        y = min_xy if rows == 1 else min_xy + round((max_xy - min_xy) * row / (rows - 1))
        x_indices: Iterable[int] = range(cols)
        if row % 2:
            x_indices = reversed(range(cols))

        for col in x_indices:
            if len(points) >= count:
                break
            x = min_xy if cols == 1 else min_xy + round((max_xy - min_xy) * col / (cols - 1))
            points.append(TargetPoint(x=x, y=y))

    return points


def run_startup_queries(dev: DeviceConsole) -> None:
    commands = [
        "APP_PING",
        "LASER_GET_STATE",
        "PELTIER_GET_STATE",
        "TARGET_GET_STATE",
        "APP_GET_STATE",
        "SENSORS_GET_VALUES",
        "TARGET_GET_MODE",
        "APP_GET_GENERAL_PARAMS",
        "APP_GET_PELTIER_PARAMS",
        "APP_GET_LASER_PARAMS",
        "APP_GET_CALIB_PARAMS",
    ]

    for command in commands:
        try:
            dev.run_command(command)
        except Exception as exc:
            print(f"! {command}: {exc}")


def upload_targets(
    dev: DeviceConsole,
    points: list[TargetPoint],
    power_808: int,
    power_980: int,
    power_1064: int,
    pulse_ms: int,
) -> None:
    upload_start_s = time.perf_counter()
    dev.run_command("TARGET_CLEAR_TARGETS")

    total = len(points)
    for idx, point in enumerate(points, start=1):
        target_start_s = time.perf_counter()
        command = (
            f"TARGET_SET_NEW_TARGET "
            f"{point.x},{point.y},{point.x},{point.y},"
            f"{power_808},{power_980},{power_1064},{pulse_ms}"
        )
        dev.run_command(command)
        print(f"Uploaded target {idx}/{total}: ({point.x},{point.y}) in {elapsed_ms(target_start_s):.1f} ms")

    total_ms = elapsed_ms(upload_start_s)
    per_target_ms = total_ms / total if total else 0.0
    print(f"Upload complete in {total_ms:.1f} ms ({per_target_ms:.1f} ms/target including clear)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive LaserDriver targeting/fire test.")
    parser.add_argument("port", nargs="?", help="Serial port, for example COM7 or /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD, help="CDC line coding baud value")
    parser.add_argument("--count", type=int, default=50, help="Number of target points")
    parser.add_argument("--min-xy", type=int, default=1000, help="Grid minimum X/Y")
    parser.add_argument("--max-xy", type=int, default=3000, help="Grid maximum X/Y")
    parser.add_argument("--finish-timeout", type=float, default=FINISH_TIMEOUT_S)
    args = parser.parse_args()

    if args.count <= 0:
        print("--count must be positive")
        return 2
    if not (0 <= args.min_xy <= args.max_xy <= 4095):
        print("--min-xy/--max-xy must satisfy 0 <= min <= max <= 4095")
        return 2

    if not args.port:
        list_serial_ports()
        args.port = input("Serial port: ").strip()
        if not args.port:
            return 2

    print(f"Connecting to {args.port} at CDC line coding {args.baud}...")
    dev = DeviceConsole(args.port, args.baud)

    try:
        time.sleep(0.5)
        print("Running startup queries...")
        run_startup_queries(dev)

        print("Setting target mode to AUTO...")
        dev.run_command("TARGET_SET_MODE 1")

        pulse_ms = ask_int("Pulse length ms", default=10, minimum=10, maximum=1000)
        power_808 = ask_int("808 nm power percent", default=0, minimum=0, maximum=100)
        power_980 = ask_int("980 nm power percent", default=0, minimum=0, maximum=100)
        power_1064 = ask_int("1064 nm power percent", default=0, minimum=0, maximum=100)

        if power_808 == 0 and power_980 == 0 and power_1064 == 0:
            print("All laser powers are 0%; refusing to continue.")
            return 2

        wait_for_enter("Allow laser arming now.")
        dev.run_command("LASER_SET_ARM_EN 1")

        points = generate_grid_points(args.count, args.min_xy, args.max_xy)
        print(f"Prepared {len(points)} grid points from {args.min_xy} to {args.max_xy}.")

        while True:
            if not ask_yes_no("Can I upload targets and fire the sequence now?", default=False):
                if ask_yes_no("Exit?", default=True):
                    break
                continue

            upload_targets(dev, points, power_808, power_980, power_1064, pulse_ms)
            print("All targets acknowledged. Starting target sequence immediately.")
            sequence_start_s = time.perf_counter()
            dev.run_command("TARGET_START")
            fire_start_ms = elapsed_ms(sequence_start_s)

            finished = dev.wait_for_line_containing(
                "[APP_TARGET_SEQ_FINISHED]->[OK]",
                timeout_s=args.finish_timeout,
            )
            sequence_ms = elapsed_ms(sequence_start_s)
            print(f"Sequence finished: {finished}")
            print(f"TARGET_START acknowledged in {fire_start_ms:.1f} ms; sequence finished in {sequence_ms:.1f} ms")

            if not ask_yes_no(f"Run the same {len(points)}-point sequence again?", default=True):
                break

        return 0
    except KeyboardInterrupt:
        print("\nInterrupted.")
        return 130
    except Exception as exc:
        print(f"\nERROR: {exc}")
        return 1
    finally:
        dev.close()


if __name__ == "__main__":
    raise SystemExit(main())
