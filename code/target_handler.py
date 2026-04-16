"""Target/sequence controller using serial_commands."""

from __future__ import annotations

from typing import Callable, Dict, Optional, Tuple

from serial_devices_handler import SerialDevice, DEFAULT_PORT, DEFAULT_BAUD
from serial_commands import build_command


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))


class TargetInterface:
    """Manage target list and sequence start/stop controls."""

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
    def _send(self, cmd_name: str, *params):
        payload = build_command(cmd_name, *params)
        return self.dev.query(payload, expect_prefix=None, extra_read_window_s=0.5)

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
        return self._send_targets_and_start()

    def start_seq_test(self):
        return self._send_targets_and_start()

    def stop_seq(self):
        return self._send("TARGET_STOP")

    def halt_seq(self):
        return self._send("TARGET_HALT")

    def resume_seq(self):
        return self._send("TARGET_CONTINUE")

    def get_state(self):
        return self._send("TARGET_GET_STATE")

    def get_last_error(self):
        return self._send("TARGET_GET_LAST_ERROR")

    def close(self):
        try:
            self.dev.close()
        except Exception:
            pass

    # ---------- internal ----------
    def _send_targets_and_start(self):
        if not self.targets:
            return ["ERROR: no targets set"]

        # clear and load new targets
        self._send("TARGET_CLEAR_TARGETS")

        p808, p980, p1064 = self.channel_provider()

        for idx, (x, y) in sorted(self.targets.items()):
            self._send(
                "TARGET_SET_NEW_TARGET",
                x,
                y,
                x,
                y,
                p808,
                p980,
                p1064,
                self.pulse_ms,
            )

        self._send("TARGET_SET_MODE", "AUTO")
        return self._send("TARGET_START")


# compatibility alias if needed elsewhere
TargetControlInterface = TargetInterface
