"""Galvo controller wrapper using serial_commands and SerialDevice."""

from __future__ import annotations

from typing import Tuple, Optional
import sys

from serial_devices_handler import SerialDevice, DEFAULT_PORT, DEFAULT_BAUD
from serial_commands import build_command


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, val))


class GalvoInterface:
    """Minimal galvo control surface used by the apps."""

    def __init__(self, port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD,
                 timeout_s: Optional[float] = None, debug: bool = False,
                 dev: Optional[SerialDevice] = None):
        self.dev = dev
        self._owns_dev = dev is None
        if self.dev is None:
            kwargs = {}
            if timeout_s is not None:
                kwargs["timeout_s"] = timeout_s
            self.dev = SerialDevice(port=port, baud=baud, debug=debug, **kwargs)
            self.dev.open()
        self._position_x = 3000
        self._position_y = 3000
        self._move_internal(self._position_x, self._position_y)

    def _send(self, cmd_name: str, *params) -> None:
        payload = build_command(cmd_name, *params)
        self.dev.query(payload, expect_prefix=None, extra_read_window_s=0.2)

    def _move_internal(self, x: int, y: int) -> None:
        x = _clamp(x, 0, 4095)
        y = _clamp(y, 0, 4095)
        self._send("TARGET_SET_POS", x, y)
        self._position_x, self._position_y = x, y

    def close(self):
        if self._owns_dev:
            self.dev.close()

    def get_position(self) -> Tuple[int, int]:
        return self._position_x, self._position_y

    def move_2_pos(self, x: int, y: int) -> Tuple[int, int]:
        self._move_internal(x, y)
        return self.get_position()

    def move_direction(self, direction: str, step: int = 25) -> Tuple[int, int]:
        x, y = self.get_position()
        if direction == "up":
            y -= step
        elif direction == "down":
            y += step
        elif direction == "left":
            x -= step
        elif direction == "right":
            x += step
        return self.move_2_pos(x, y)

    def stop(self) -> None:
        self.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test galvo interface via serial")
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--list-ports", action="store_true")
    args = parser.parse_args()

    if args.list_ports:
        from serial_devices_handler import list_serial_ports
        print("\n".join(list_serial_ports()))
        sys.exit(0)

    gi = GalvoInterface(port=args.port, baud=args.baud, debug=True)
    print("current", gi.get_position())
    gi.move_2_pos(2000, 2000)
    print("after move", gi.get_position())
    gi.stop()
