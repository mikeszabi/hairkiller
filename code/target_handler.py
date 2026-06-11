"""Target/sequence controller using serial_commands."""

from __future__ import annotations

import os
from typing import Callable, Dict, Optional, Tuple

from serial_devices_handler import SerialDevice, DEFAULT_PORT, DEFAULT_BAUD
from serial_commands import build_command


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))


class TargetInterface:
    """Manage target list and sequence start/stop controls."""

    MODE_MANUAL = 0
    MODE_AUTO = 1

    def __init__(
        self,
        dev: Optional[SerialDevice] = None,
        port: str = DEFAULT_PORT,
        baud: int = DEFAULT_BAUD,
        timeout_s: Optional[float] = None,
        debug: bool = False,
        channel_provider: Optional[Callable[[], Tuple[int, int, int]]] = None,
    ):
        self.dev = dev
        if self.dev is None:
            kwargs = {}
            if timeout_s is not None:
                kwargs["timeout_s"] = timeout_s
            self.dev = SerialDevice(port=port, baud=baud, debug=debug, **kwargs)
            self.dev.open()

        self.pulse_ms = 50
        self.targets: Dict[int, Tuple[int, int]] = {}
        self.channel_provider = channel_provider or (lambda: (0, 0, 0))

    # ---------- helpers ----------
    def _send(self, cmd_name: str, *params, wait_s: float = 0.05, extra_read_window_s: float = 0.5):
        payload = build_command(cmd_name, *params)
        return self.dev.query(
            payload,
            expect_prefix=None,
            wait_s=wait_s,
            extra_read_window_s=extra_read_window_s,
        )

    # ---------- API ----------
    def set_las_pulse(self, pulse_ms: int):
        self.pulse_ms = _clamp(pulse_ms, 10, 1000)
        return [f"PULSE_MS={self.pulse_ms}"]

    def set_seq_length(self, length: int):
        length = _clamp(length, 0, 256)
        self.targets = {k: v for k, v in list(self.targets.items())[:length]}
        return [f"SEQ_LEN={length}"]

    def set_target_point(self, idx: int, x: int, y: int):
        idx = _clamp(idx, 0, 255)
        x = _clamp(x, 0, 4095)
        y = _clamp(y, 0, 4095)
        self.targets[idx] = (x, y)
        return [f"TARGET[{idx}]={x},{y}"]

    def start_seq(self):
        return self._send("TARGET_START")

    def start_seq_test(self):
        return self._send("TARGET_START")

    def start_seq_manual(self):
        return self._send("TARGET_START")

    def stop_seq(self):
        return self._send("TARGET_STOP")

    def halt_seq(self):
        return self._send("TARGET_HALT")

    def resume_seq(self):
        return self._send("TARGET_CONTINUE")

    def set_mode(self, mode: int):
        mode = self.MODE_AUTO if int(mode) == self.MODE_AUTO else self.MODE_MANUAL
        return self._send("TARGET_SET_MODE", mode)

    def get_mode(self):
        return self._send("TARGET_GET_MODE")

    def get_state(self):
        return self._send("TARGET_GET_STATE")

    def get_last_error(self):
        return self._send("TARGET_GET_LAST_ERROR")

    def clear_error(self):
        return self._send("TARGET_CLEAR_ERROR")

    def clear_targets(self):
        self.targets = {}
        return self._send("TARGET_CLEAR_TARGETS")

    def get_target_count(self) -> int:
        return len(self.targets)

    def close(self):
        try:
            self.dev.close()
        except Exception:
            pass

    # ---------- internal ----------
    def load_targets(self, mode: Optional[int] = None):
        if not self.targets:
            return ["ERROR: no targets set"]

        # Bulk target loading sends one serial command per target. The default
        # read window is intentionally longer for interactive commands, but it
        # makes this path scale poorly with many targets.
        load_wait_s = float(os.getenv("HK_TARGET_LOAD_WAIT_S", "0.002"))
        load_read_window_s = float(os.getenv("HK_TARGET_LOAD_READ_WINDOW_S", "0.008"))

        # clear and load new targets
        clear_resp = self._send("TARGET_CLEAR_TARGETS", wait_s=load_wait_s, extra_read_window_s=load_read_window_s)
        if any("NOK" in str(line) or "ERROR:" in str(line) for line in clear_resp):
            return clear_resp + ["ERROR: failed to clear targets"]

        p808, p980, p1064 = self.channel_provider()

        for idx, (x, y) in sorted(self.targets.items()):
            resp = self._send(
                "TARGET_SET_NEW_TARGET",
                x,
                y,
                x,
                y,
                p808,
                p980,
                p1064,
                self.pulse_ms,
                wait_s=load_wait_s,
                extra_read_window_s=load_read_window_s,
            )
            if any("NOK" in str(line) or "ERROR:" in str(line) for line in resp):
                return resp + [f"ERROR: failed to load target {idx}"]

        if mode is not None:
            mode_resp = self.set_mode(mode)
            if any("NOK" in str(line) or "ERROR:" in str(line) for line in mode_resp):
                return mode_resp + ["ERROR: failed to set target mode"]

        return [f"TARGET_COUNT={len(self.targets)}"]

    def _send_targets_and_start_with_mode(self, mode: int):
        load_resp = self.load_targets(mode=mode)
        if load_resp and any("ERROR:" in str(line) for line in load_resp):
            return load_resp
        return self._send("TARGET_START")


# compatibility alias if needed elsewhere
TargetControlInterface = TargetInterface
