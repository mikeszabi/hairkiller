#!/usr/bin/env python3
"""Tkinter GUI for exercising the LaserDriver USB CDC command interface."""

from __future__ import annotations

import queue
import base64
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, scrolledtext, ttk
from typing import Callable, Iterable

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    print("Missing dependency: pyserial")
    print(f"This script is running with: {sys.executable}")
    print(f"Install it with: \"{sys.executable}\" -m pip install -r requirements.txt")
    raise SystemExit(2)

try:
    import cv2
except ImportError:
    cv2 = None


DEFAULT_BAUD = 115200
READ_TIMEOUT_S = 0.1
COMMAND_TIMEOUT_S = 5.0
CAMERA_DISPLAY_MAX_W = 960
CAMERA_DISPLAY_MAX_H = 540


@dataclass(frozen=True)
class TargetPoint:
    x: int
    y: int


class DeviceClient:
    def __init__(self, port: str, baud: int, on_line: Callable[[str, str], None]) -> None:
        self.serial = serial.Serial(port=port, baudrate=baud, timeout=READ_TIMEOUT_S)
        self.on_line = on_line
        self.stop_event = threading.Event()
        self.response_lines: queue.Queue[str] = queue.Queue()
        self.reader = threading.Thread(target=self._read_loop, daemon=True)
        self.reader.start()

    def close(self) -> None:
        self.stop_event.set()
        self.reader.join(timeout=1.0)
        if self.serial.is_open:
            self.serial.close()

    def _read_loop(self) -> None:
        while not self.stop_event.is_set():
            try:
                raw = self.serial.readline()
            except serial.SerialException as exc:
                self.on_line("error", f"[SERIAL ERROR] {exc}")
                self.stop_event.set()
                return

            if not raw:
                continue

            text = raw.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            self.response_lines.put(text)
            self.on_line("rx", text)

    @staticmethod
    def command_prefix(command: str) -> str:
        return command.split(maxsplit=1)[0].strip().upper()

    def send(self, command: str) -> None:
        payload = (command.rstrip() + "\r\n").encode("ascii")
        self.on_line("tx", command.rstrip())
        self.serial.write(payload)
        self.serial.flush()

    def request(self, command: str, timeout_s: float = COMMAND_TIMEOUT_S) -> list[str]:
        prefix = self.command_prefix(command)
        lines: list[str] = []
        deadline = time.monotonic() + timeout_s

        self.send(command)

        while time.monotonic() < deadline:
            try:
                line = self.response_lines.get(timeout=0.1)
            except queue.Empty:
                continue

            if not line.startswith(f"[{prefix}]"):
                continue

            lines.append(line)
            if "->[NOK]" in line:
                raise RuntimeError(line)
            if "->[END]" in line:
                return lines
            if "->[OK]" in line and "Count," not in line:
                return lines

        raise TimeoutError(f"Timed out waiting for {prefix}")


def generate_grid_points(count: int, min_xy: int, max_xy: int) -> list[TargetPoint]:
    cols = min(10, max(1, count))
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


class LaserDriverGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("LaserDriver Tester")
        self.minsize(1120, 760)

        self.client: DeviceClient | None = None
        self.ui_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.auto_refresh = tk.BooleanVar(value=False)
        self.raw_command = tk.StringVar()
        self.port_var = tk.StringVar()
        self.baud_var = tk.StringVar(value=str(DEFAULT_BAUD))
        self.connection_var = tk.StringVar(value="Disconnected")
        self.status_vars: dict[str, tk.StringVar] = {}
        self.camera = None
        self.camera_photo: tk.PhotoImage | None = None
        self.camera_running = False
        self.camera_index_var = tk.StringVar(value="0")
        self.camera_status_var = tk.StringVar(value="Camera stopped")

        self._build_ui()
        self.refresh_ports()
        self.after(50, self._drain_ui_queue)
        self.after(1000, self._auto_refresh_tick)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        top = ttk.Frame(self, padding=(8, 8, 8, 4))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="Port").grid(row=0, column=0, padx=(0, 4))
        self.port_combo = ttk.Combobox(top, textvariable=self.port_var, width=28)
        self.port_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        ttk.Button(top, text="Refresh", command=self.refresh_ports).grid(row=0, column=2, padx=(0, 8))

        ttk.Label(top, text="Baud").grid(row=0, column=3, padx=(0, 4))
        ttk.Entry(top, textvariable=self.baud_var, width=10).grid(row=0, column=4, padx=(0, 8))
        self.connect_button = ttk.Button(top, text="Connect", command=self.toggle_connection)
        self.connect_button.grid(row=0, column=5, padx=(0, 8))
        ttk.Label(top, textvariable=self.connection_var).grid(row=0, column=6, sticky="w")

        paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        paned.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))

        self.tabs = ttk.Notebook(paned)
        paned.add(self.tabs, weight=4)

        self.log_text = scrolledtext.ScrolledText(paned, height=12, wrap=tk.WORD, state="disabled")
        self.log_text.tag_configure("tx", foreground="#0b5cad")
        self.log_text.tag_configure("rx", foreground="#167a3a")
        self.log_text.tag_configure("error", foreground="#b00020")
        self.log_text.tag_configure("info", foreground="#444444")
        paned.add(self.log_text, weight=2)

        self._build_status_tab()
        self._build_laser_tab()
        self._build_peltier_tab()
        self._build_target_tab()
        self._build_camera_tab()
        self._build_params_tab()
        self._build_raw_tab()

    def _build_status_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Status")
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)

        summary = ttk.LabelFrame(tab, text="Quick Status", padding=8)
        summary.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        summary.columnconfigure(1, weight=1)

        for row, key in enumerate([
            "APP_GET_STATE",
            "LASER_GET_STATE",
            "PELTIER_GET_STATE",
            "TARGET_GET_STATE",
            "SENSORS_GET_STATE",
            "APP_GET_FW_VERSION",
            "APP_GET_HW_VERSION",
        ]):
            ttk.Label(summary, text=key).grid(row=row, column=0, sticky="w", pady=2)
            var = tk.StringVar(value="-")
            self.status_vars[key] = var
            ttk.Label(summary, textvariable=var).grid(row=row, column=1, sticky="ew", pady=2)

        actions = ttk.LabelFrame(tab, text="Actions", padding=8)
        actions.grid(row=0, column=1, sticky="nsew")
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        ttk.Button(actions, text="Ping", command=lambda: self.send_simple("APP_PING")).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(actions, text="Refresh Status", command=self.refresh_status).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        ttk.Checkbutton(actions, text="Auto refresh", variable=self.auto_refresh).grid(row=1, column=0, sticky="w", padx=3, pady=3)
        ttk.Button(actions, text="Get Limits", command=lambda: self.send_simple("APP_GET_LIMITS")).grid(row=1, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(actions, text="Get Sensors", command=lambda: self.send_simple("SENSORS_GET_VALUES")).grid(row=2, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(actions, text="Clear App Error", command=lambda: self.send_simple("APP_CLEAR_ERROR")).grid(row=2, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(actions, text="Reset App", command=lambda: self.confirm_and_send("APP_RESET", "Reset the application state?")).grid(row=3, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(actions, text="Bootloader", command=self.bootloader_confirm).grid(row=3, column=1, sticky="ew", padx=3, pady=3)

    def _build_laser_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Laser")
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)

        control = ttk.LabelFrame(tab, text="Control", padding=8)
        control.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        for col in range(3):
            control.columnconfigure(col, weight=1)

        ttk.Button(control, text="Arm", command=lambda: self.confirm_and_send("LASER_SET_ARM_EN 1", "Arm the laser?")).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(control, text="Disarm", command=lambda: self.send_simple("LASER_SET_ARM_EN 0")).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(control, text="Get Arm", command=lambda: self.send_simple("LASER_GET_ARM_EN")).grid(row=0, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(control, text="Red Dot On", command=lambda: self.send_simple("LASER_SET_RED_DOT_EN 1")).grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(control, text="Red Dot Off", command=lambda: self.send_simple("LASER_SET_RED_DOT_EN 0")).grid(row=1, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(control, text="Get Red Dot", command=lambda: self.send_simple("LASER_GET_RED_DOT_EN")).grid(row=1, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(control, text="Stop Laser", command=lambda: self.send_simple("LASER_STOP")).grid(row=2, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(control, text="State", command=lambda: self.send_simple("LASER_GET_STATE")).grid(row=2, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(control, text="Clear Error", command=lambda: self.send_simple("LASER_CLEAR_ERROR")).grid(row=2, column=2, sticky="ew", padx=3, pady=3)

        fire = ttk.LabelFrame(tab, text="Power And Fire", padding=8)
        fire.grid(row=0, column=1, sticky="nsew")
        for col in range(4):
            fire.columnconfigure(col, weight=1)

        self.p808 = self._spin(fire, "808 %", 0, 0, 100, row=0, col=0)
        self.p980 = self._spin(fire, "980 %", 0, 0, 100, row=0, col=1)
        self.p1064 = self._spin(fire, "1064 %", 0, 0, 100, row=0, col=2)
        ttk.Button(fire, text="Set Power", command=self.set_laser_power).grid(row=2, column=0, sticky="ew", padx=3, pady=5)
        ttk.Button(fire, text="Get Power", command=lambda: self.send_simple("LASER_GET_CHANNEL_PWR")).grid(row=2, column=1, sticky="ew", padx=3, pady=5)

        self.fire_ms = self._spin(fire, "Fire ms", 10, 1, 1000, row=3, col=0)
        ttk.Button(fire, text="Fire", command=self.fire_laser_confirm).grid(row=5, column=0, sticky="ew", padx=3, pady=5)
        ttk.Button(fire, text="Power Test", command=lambda: self.confirm_and_send("APP_DO_LASER_PWR_TEST", "Start the laser power test?")).grid(row=5, column=1, sticky="ew", padx=3, pady=5)
        ttk.Button(fire, text="Test Result", command=lambda: self.send_simple("APP_GET_LASER_TEST_RESULT")).grid(row=5, column=2, sticky="ew", padx=3, pady=5)
        ttk.Button(fire, text="Test Data", command=lambda: self.send_simple("APP_GET_LASER_TEST_DATA")).grid(row=5, column=3, sticky="ew", padx=3, pady=5)

    def _build_peltier_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Peltier")
        tab.columnconfigure(0, weight=1)

        frame = ttk.LabelFrame(tab, text="Cooling", padding=8)
        frame.grid(row=0, column=0, sticky="ew")
        for col in range(4):
            frame.columnconfigure(col, weight=1)

        ttk.Button(frame, text="Cooling On", command=lambda: self.send_simple("PELTIER_SET_COOLING_EN 1")).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(frame, text="Cooling Off", command=lambda: self.confirm_and_send("PELTIER_SET_COOLING_EN 0", "Disable Peltier cooling?")).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(frame, text="Get Enabled", command=lambda: self.send_simple("PELTIER_GET_COOLING_EN")).grid(row=0, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(frame, text="State", command=lambda: self.send_simple("PELTIER_GET_STATE")).grid(row=0, column=3, sticky="ew", padx=3, pady=3)
        ttk.Button(frame, text="Last Error", command=lambda: self.send_simple("PELTIER_GET_LAST_ERROR")).grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(frame, text="Clear Error", command=lambda: self.send_simple("PELTIER_CLEAR_ERROR")).grid(row=1, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(frame, text="Default On", command=lambda: self.send_simple("APP_SET_PELTIER_DEFAULT_EN 1")).grid(row=1, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(frame, text="Default Off", command=lambda: self.send_simple("APP_SET_PELTIER_DEFAULT_EN 0")).grid(row=1, column=3, sticky="ew", padx=3, pady=3)

    def _build_target_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Target")
        tab.columnconfigure(0, weight=1)
        tab.columnconfigure(1, weight=1)

        pos = ttk.LabelFrame(tab, text="Position", padding=8)
        pos.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 8))
        for col in range(4):
            pos.columnconfigure(col, weight=1)
        self.target_x = self._spin(pos, "X", 2000, 0, 4095, row=0, col=0)
        self.target_y = self._spin(pos, "Y", 2000, 0, 4095, row=0, col=1)
        ttk.Button(pos, text="Set Pos", command=self.set_target_pos).grid(row=2, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(pos, text="Get Pos", command=lambda: self.send_simple("TARGET_GET_POS")).grid(row=2, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(pos, text="Get Feedback", command=lambda: self.send_simple("TARGET_GET_FB_POS")).grid(row=2, column=2, sticky="ew", padx=3, pady=3)

        seq = ttk.LabelFrame(tab, text="Sequence", padding=8)
        seq.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        for col in range(4):
            seq.columnconfigure(col, weight=1)
        ttk.Button(seq, text="Mode Single", command=lambda: self.send_simple("TARGET_SET_MODE 0")).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(seq, text="Mode Auto", command=lambda: self.send_simple("TARGET_SET_MODE 1")).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(seq, text="Get Mode", command=lambda: self.send_simple("TARGET_GET_MODE")).grid(row=0, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(seq, text="Clear Targets", command=lambda: self.send_simple("TARGET_CLEAR_TARGETS")).grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(seq, text="Get All", command=lambda: self.send_simple("TARGET_GET_ALL_TARGETS")).grid(row=1, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(seq, text="Start", command=lambda: self.confirm_and_send("TARGET_START", "Start target sequence?")).grid(row=1, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(seq, text="Halt", command=lambda: self.send_simple("TARGET_HALT")).grid(row=2, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(seq, text="Continue", command=lambda: self.send_simple("TARGET_CONTINUE")).grid(row=2, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(seq, text="Stop", command=lambda: self.send_simple("TARGET_STOP")).grid(row=2, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(seq, text="State", command=lambda: self.send_simple("TARGET_GET_STATE")).grid(row=2, column=3, sticky="ew", padx=3, pady=3)

        line = ttk.LabelFrame(tab, text="Add Target Line", padding=8)
        line.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        for col in range(8):
            line.columnconfigure(col, weight=1)
        self.line_x0 = self._spin(line, "X0", 1000, 0, 4095, row=0, col=0)
        self.line_y0 = self._spin(line, "Y0", 1000, 0, 4095, row=0, col=1)
        self.line_x1 = self._spin(line, "X1", 3000, 0, 4095, row=0, col=2)
        self.line_y1 = self._spin(line, "Y1", 3000, 0, 4095, row=0, col=3)
        self.line_p808 = self._spin(line, "808 %", 0, 0, 100, row=0, col=4)
        self.line_p980 = self._spin(line, "980 %", 0, 0, 100, row=0, col=5)
        self.line_p1064 = self._spin(line, "1064 %", 0, 0, 100, row=0, col=6)
        self.line_pulse = self._spin(line, "Pulse ms", 10, 1, 1000, row=0, col=7)
        ttk.Button(line, text="Add Target", command=self.add_target_line).grid(row=2, column=0, sticky="ew", padx=3, pady=5)

        grid = ttk.LabelFrame(tab, text="Grid Upload", padding=8)
        grid.grid(row=2, column=0, columnspan=2, sticky="ew")
        for col in range(8):
            grid.columnconfigure(col, weight=1)
        self.grid_count = self._spin(grid, "Count", 50, 1, 512, row=0, col=0)
        self.grid_min = self._spin(grid, "Min XY", 1000, 0, 4095, row=0, col=1)
        self.grid_max = self._spin(grid, "Max XY", 3000, 0, 4095, row=0, col=2)
        self.grid_p808 = self._spin(grid, "808 %", 0, 0, 100, row=0, col=3)
        self.grid_p980 = self._spin(grid, "980 %", 0, 0, 100, row=0, col=4)
        self.grid_p1064 = self._spin(grid, "1064 %", 0, 0, 100, row=0, col=5)
        self.grid_pulse = self._spin(grid, "Pulse ms", 10, 1, 1000, row=0, col=6)
        ttk.Button(grid, text="Upload Grid", command=lambda: self.start_grid_worker(False)).grid(row=2, column=0, sticky="ew", padx=3, pady=5)
        ttk.Button(grid, text="Upload And Start", command=lambda: self.start_grid_worker(True)).grid(row=2, column=1, sticky="ew", padx=3, pady=5)

    def _build_camera_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Camera")
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(1, weight=1)

        controls = ttk.LabelFrame(tab, text="Camera And Galvo", padding=8)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for col in range(8):
            controls.columnconfigure(col, weight=1)

        ttk.Label(controls, text="Camera index").grid(row=0, column=0, sticky="w", padx=3)
        self.camera_combo = ttk.Combobox(controls, textvariable=self.camera_index_var, values=["0", "1", "2", "3", "4"], width=10)
        self.camera_combo.grid(row=1, column=0, sticky="ew", padx=3)
        ttk.Button(controls, text="Probe", command=self.probe_cameras).grid(row=1, column=1, sticky="ew", padx=3)
        ttk.Button(controls, text="Start Camera", command=self.start_camera).grid(row=1, column=2, sticky="ew", padx=3)
        ttk.Button(controls, text="Stop Camera", command=self.stop_camera).grid(row=1, column=3, sticky="ew", padx=3)

        self.camera_x = self._spin(controls, "Target X", 2000, 0, 4095, row=0, col=4)
        self.camera_y = self._spin(controls, "Target Y", 2000, 0, 4095, row=0, col=5)
        ttk.Button(controls, text="Set Pos", command=self.set_camera_target_pos).grid(row=2, column=4, sticky="ew", padx=3, pady=(6, 0))
        ttk.Button(controls, text="Get Pos", command=lambda: self.send_simple("TARGET_GET_POS")).grid(row=2, column=5, sticky="ew", padx=3, pady=(6, 0))
        ttk.Button(controls, text="Get Feedback", command=lambda: self.send_simple("TARGET_GET_FB_POS")).grid(row=2, column=6, sticky="ew", padx=3, pady=(6, 0))

        ttk.Label(controls, textvariable=self.camera_status_var).grid(row=2, column=0, columnspan=4, sticky="w", padx=3, pady=(6, 0))

        preview = ttk.LabelFrame(tab, text="Preview", padding=8)
        preview.grid(row=1, column=0, sticky="nsew")
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        self.camera_label = ttk.Label(preview, text="Camera preview stopped", anchor="center")
        self.camera_label.grid(row=0, column=0, sticky="nsew")

    def _build_params_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Params/Sensors")
        tab.columnconfigure(0, weight=1)

        frame = ttk.LabelFrame(tab, text="Queries", padding=8)
        frame.grid(row=0, column=0, sticky="ew")
        for col in range(4):
            frame.columnconfigure(col, weight=1)

        commands = [
            "APP_GET_GENERAL_PARAMS",
            "APP_GET_PELTIER_PARAMS",
            "APP_GET_LASER_PARAMS",
            "APP_GET_CALIB_PARAMS",
            "SENSORS_GET_VALUES",
            "SENSORS_GET_LAST_ERROR",
            "APP_GET_LAST_ERROR",
            "APP_GET_PROC_TIME",
            "APP_GET_CHECK_VACUUM",
            "APP_GET_VACUUM_EN",
            "APP_GET_PERIODIC_REPORT_EN",
            "APP_GET_PELTIER_DEFAULT_EN",
        ]
        for idx, command in enumerate(commands):
            ttk.Button(frame, text=command, command=lambda c=command: self.send_simple(c)).grid(
                row=idx // 4, column=idx % 4, sticky="ew", padx=3, pady=3
            )

        set_frame = ttk.LabelFrame(tab, text="Simple Settings", padding=8)
        set_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for col in range(4):
            set_frame.columnconfigure(col, weight=1)
        ttk.Button(set_frame, text="Periodic On", command=lambda: self.send_simple("APP_SET_PERIODIC_REPORT_EN 1")).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(set_frame, text="Periodic Off", command=lambda: self.send_simple("APP_SET_PERIODIC_REPORT_EN 0")).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(set_frame, text="Check Vacuum On", command=lambda: self.send_simple("APP_SET_CHECK_VACUUM 1")).grid(row=0, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(set_frame, text="Check Vacuum Off", command=lambda: self.send_simple("APP_SET_CHECK_VACUUM 0")).grid(row=0, column=3, sticky="ew", padx=3, pady=3)
        ttk.Button(set_frame, text="Vacuum On", command=lambda: self.send_simple("APP_SET_VACUUM_EN 1")).grid(row=1, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(set_frame, text="Vacuum Off", command=lambda: self.send_simple("APP_SET_VACUUM_EN 0")).grid(row=1, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(set_frame, text="Store Params", command=lambda: self.confirm_and_send("APP_STORE_PARAMS_TO_NVM", "Store current parameters to NVM?")).grid(row=1, column=2, sticky="ew", padx=3, pady=3)
        ttk.Button(set_frame, text="Defaults", command=lambda: self.confirm_and_send("APP_RESET_TO_DEFAULTS", "Reset parameters to defaults?")).grid(row=1, column=3, sticky="ew", padx=3, pady=3)

    def _build_raw_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Raw")
        tab.columnconfigure(0, weight=1)

        raw = ttk.LabelFrame(tab, text="Raw Command", padding=8)
        raw.grid(row=0, column=0, sticky="ew")
        raw.columnconfigure(0, weight=1)
        entry = ttk.Entry(raw, textvariable=self.raw_command)
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        entry.bind("<Return>", lambda _event: self.send_raw())
        ttk.Button(raw, text="Send", command=self.send_raw).grid(row=0, column=1)

        common = ttk.LabelFrame(tab, text="Command Discovery", padding=8)
        common.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        for col in range(3):
            common.columnconfigure(col, weight=1)
        ttk.Button(common, text="APP_GET_COMMANDS", command=lambda: self.send_simple("APP_GET_COMMANDS")).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        ttk.Button(common, text="APP_GET_LIMITS", command=lambda: self.send_simple("APP_GET_LIMITS")).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        ttk.Button(common, text="Clear Log", command=self.clear_log).grid(row=0, column=2, sticky="ew", padx=3, pady=3)

    def _spin(self, parent: ttk.Frame, label: str, default: int, minimum: int, maximum: int, row: int, col: int) -> tk.Spinbox:
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=3)
        spin = tk.Spinbox(parent, from_=minimum, to=maximum, width=8)
        spin.delete(0, tk.END)
        spin.insert(0, str(default))
        spin.grid(row=row + 1, column=col, sticky="ew", padx=3)
        return spin

    def refresh_ports(self) -> None:
        ports = list(list_ports.comports())
        values = [f"{item.device} - {item.description}" for item in ports]
        self.port_combo["values"] = values
        if values and not self.port_var.get():
            self.port_var.set(values[0])

    def selected_port(self) -> str:
        value = self.port_var.get().strip()
        return value.split(" - ", 1)[0].strip()

    def toggle_connection(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None
            self.connection_var.set("Disconnected")
            self.connect_button.configure(text="Connect")
            return

        port = self.selected_port()
        if not port:
            messagebox.showerror("No port", "Select a serial port first.")
            return

        try:
            baud = int(self.baud_var.get(), 0)
            self.client = DeviceClient(port, baud, self._queue_line)
        except Exception as exc:
            self.client = None
            messagebox.showerror("Connection failed", str(exc))
            return

        self.connection_var.set(f"Connected to {port}")
        self.connect_button.configure(text="Disconnect")
        self.log("info", f"Connected to {port} at CDC line coding {baud}")

    def _queue_line(self, kind: str, text: str) -> None:
        self.ui_queue.put((kind, text))

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                kind, text = self.ui_queue.get_nowait()
            except queue.Empty:
                break
            self.log(kind, text)
            self._update_status_from_line(text)
        self.after(50, self._drain_ui_queue)

    def log(self, kind: str, text: str) -> None:
        prefixes = {"tx": "> ", "rx": "< ", "error": "! ", "info": "# "}
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, prefixes.get(kind, "") + text + "\n", kind)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def _update_status_from_line(self, line: str) -> None:
        for command, var in self.status_vars.items():
            if line.startswith(f"[{command}]"):
                var.set(line)

    def send_simple(self, command: str) -> None:
        if self.client is None:
            messagebox.showerror("Not connected", "Connect to a device first.")
            return
        try:
            self.client.send(command)
        except Exception as exc:
            messagebox.showerror("Send failed", str(exc))

    def send_raw(self) -> None:
        command = self.raw_command.get().strip()
        if command:
            self.send_simple(command)
            self.raw_command.set("")

    def confirm_and_send(self, command: str, prompt: str) -> None:
        if messagebox.askyesno("Confirm", prompt):
            self.send_simple(command)

    def refresh_status(self) -> None:
        for command in self.status_vars:
            self.send_simple(command)

    def _auto_refresh_tick(self) -> None:
        if self.auto_refresh.get() and self.client is not None:
            self.refresh_status()
        self.after(2000, self._auto_refresh_tick)

    @staticmethod
    def _int_from_spin(spin: tk.Spinbox) -> int:
        return int(spin.get(), 0)

    def set_laser_power(self) -> None:
        self.send_simple(
            f"LASER_SET_CHANNEL_PWR {self._int_from_spin(self.p808)},"
            f"{self._int_from_spin(self.p980)},"
            f"{self._int_from_spin(self.p1064)}"
        )

    def fire_laser_confirm(self) -> None:
        duration = self._int_from_spin(self.fire_ms)
        self.confirm_and_send(f"LASER_FIRE {duration}", f"Fire laser for {duration} ms?")

    def set_target_pos(self) -> None:
        self.send_simple(f"TARGET_SET_POS {self._int_from_spin(self.target_x)},{self._int_from_spin(self.target_y)}")

    def set_camera_target_pos(self) -> None:
        command = f"TARGET_SET_POS {self._int_from_spin(self.camera_x)},{self._int_from_spin(self.camera_y)}"
        self.send_simple(command)

    def add_target_line(self) -> None:
        values = [
            self._int_from_spin(self.line_x0),
            self._int_from_spin(self.line_y0),
            self._int_from_spin(self.line_x1),
            self._int_from_spin(self.line_y1),
            self._int_from_spin(self.line_p808),
            self._int_from_spin(self.line_p980),
            self._int_from_spin(self.line_p1064),
            self._int_from_spin(self.line_pulse),
        ]
        self.send_simple("TARGET_SET_NEW_TARGET " + ",".join(str(v) for v in values))

    def start_grid_worker(self, start_after_upload: bool) -> None:
        if self.client is None:
            messagebox.showerror("Not connected", "Connect to a device first.")
            return

        count = self._int_from_spin(self.grid_count)
        min_xy = self._int_from_spin(self.grid_min)
        max_xy = self._int_from_spin(self.grid_max)
        powers = (
            self._int_from_spin(self.grid_p808),
            self._int_from_spin(self.grid_p980),
            self._int_from_spin(self.grid_p1064),
        )
        pulse = self._int_from_spin(self.grid_pulse)

        if min_xy > max_xy:
            messagebox.showerror("Invalid grid", "Min XY must be <= Max XY.")
            return
        if start_after_upload and not messagebox.askyesno("Confirm", f"Upload {count} targets and start the target sequence?"):
            return
        if all(power == 0 for power in powers) and not messagebox.askyesno("All powers zero", "All laser powers are 0%. Upload anyway?"):
            return

        thread = threading.Thread(
            target=self._grid_worker,
            args=(count, min_xy, max_xy, powers, pulse, start_after_upload),
            daemon=True,
        )
        thread.start()

    def _grid_worker(
        self,
        count: int,
        min_xy: int,
        max_xy: int,
        powers: tuple[int, int, int],
        pulse: int,
        start_after_upload: bool,
    ) -> None:
        assert self.client is not None
        try:
            points = generate_grid_points(count, min_xy, max_xy)
            self._queue_line("info", f"Uploading {len(points)} grid targets")
            self.client.request("TARGET_CLEAR_TARGETS")
            self.client.request("TARGET_SET_MODE 1")

            for idx, point in enumerate(points, start=1):
                command = (
                    f"TARGET_SET_NEW_TARGET {point.x},{point.y},{point.x},{point.y},"
                    f"{powers[0]},{powers[1]},{powers[2]},{pulse}"
                )
                self.client.request(command)
                if idx == 1 or idx == len(points) or (idx % 10) == 0:
                    self._queue_line("info", f"Uploaded {idx}/{len(points)}")

            if start_after_upload:
                self.client.request("TARGET_START")
            self._queue_line("info", "Grid operation complete")
        except Exception as exc:
            self._queue_line("error", f"Grid operation failed: {exc}")

    def bootloader_confirm(self) -> None:
        if not messagebox.askyesno(
            "Enter bootloader",
            "This will erase the firmware vector pages and jump to the STM32 ROM bootloader. Continue?",
        ):
            return
        if not messagebox.askyesno("Final confirmation", "Send APP_BOOT ERASE now?"):
            return
        self.send_simple("APP_BOOT ERASE")

    def probe_cameras(self) -> None:
        if cv2 is None:
            messagebox.showerror("OpenCV missing", "Install camera support with: python -m pip install opencv-python")
            return

        found: list[str] = []
        backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        self.camera_status_var.set("Probing camera indexes...")
        self.update_idletasks()

        for index in range(8):
            cap = cv2.VideoCapture(index, backend)
            if cap is not None and cap.isOpened():
                ok, _frame = cap.read()
                if ok:
                    found.append(str(index))
            if cap is not None:
                cap.release()

        if found:
            self.camera_combo["values"] = found
            self.camera_index_var.set(found[0])
            self.camera_status_var.set("Found camera index(es): " + ", ".join(found))
        else:
            self.camera_status_var.set("No camera indexes responded")

    def start_camera(self) -> None:
        if cv2 is None:
            messagebox.showerror("OpenCV missing", "Install camera support with: python -m pip install opencv-python")
            return

        self.stop_camera()

        try:
            index = int(self.camera_index_var.get(), 0)
        except ValueError:
            messagebox.showerror("Invalid camera", "Camera index must be an integer.")
            return

        backend = cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY
        cap = cv2.VideoCapture(index, backend)
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            messagebox.showerror("Camera failed", f"Could not open camera index {index}.")
            return

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.camera = cap
        self.camera_running = True
        self.camera_status_var.set(f"Camera {index} running")
        self._camera_tick()

    def stop_camera(self) -> None:
        self.camera_running = False
        if self.camera is not None:
            self.camera.release()
            self.camera = None
        self.camera_photo = None
        if hasattr(self, "camera_label"):
            self.camera_label.configure(image="", text="Camera preview stopped")
        self.camera_status_var.set("Camera stopped")

    def _camera_tick(self) -> None:
        if not self.camera_running or self.camera is None:
            return

        ok, frame = self.camera.read()
        if not ok or frame is None:
            self.camera_status_var.set("Camera frame read failed")
            self.after(100, self._camera_tick)
            return

        frame_h, frame_w = frame.shape[:2]
        scale = min(CAMERA_DISPLAY_MAX_W / frame_w, CAMERA_DISPLAY_MAX_H / frame_h, 1.0)
        if scale < 1.0:
            frame = cv2.resize(frame, (int(frame_w * scale), int(frame_h * scale)), interpolation=cv2.INTER_AREA)

        ok, encoded = cv2.imencode(".png", frame)
        if ok:
            data = base64.b64encode(encoded.tobytes()).decode("ascii")
            self.camera_photo = tk.PhotoImage(data=data)
            self.camera_label.configure(image=self.camera_photo, text="")

        self.after(33, self._camera_tick)

    def _on_close(self) -> None:
        self.stop_camera()
        if self.client is not None:
            self.client.close()
        self.destroy()


def main() -> int:
    app = LaserDriverGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
