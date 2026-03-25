"""Galvo controller wrapper using the generic serial_devices_handler.

This replaces the old `GalvoInterface` implementation by talking directly
via a SerialDevice object and issuing the `SET_GALVO_POS_XY` and
`GET_GALVO_POS_XY` commands seen in `test_galvo.py`.

The interface tracks internal position state (what was commanded) rather than
relying on hardware feedback, which is more accurate.  The galvo starts
and initializes to position (3000, 3000).
"""

from typing import Tuple
import sys

from serial_devices_handler import SerialDevice, DEFAULT_PORT, DEFAULT_BAUD


# helper wrappers around the raw serial device so callers see familiar methods
class GalvoInterface:
    def __init__(self, port: str = DEFAULT_PORT, baud: int = DEFAULT_BAUD,
                 timeout_s: float = None, debug: bool = False):
        """Create and open the serial device to talk to the galvo.

        Parameters mirror those of SerialDevice.  `timeout_s` defaults to the
        module default if left as None.

        The class keeps an internal state of the last commanded position
        and initializes to (3000, 3000).
        """
        kwargs = {}
        if timeout_s is not None:
            kwargs["timeout_s"] = timeout_s
        self.dev = SerialDevice(port=port, baud=baud, debug=debug, **kwargs)
        self.dev.open()
        
        # internal state: track the last commanded position (don't rely on hardware query)
        # self._position_x = 3000
        # self._position_y = 3000
        
        # move to initial position on startup
        # self._move_internal(self._position_x, self._position_y)

    def _move_internal(self, x: int, y: int) -> None:
        """Send the movement command and update internal state."""
        self.dev.query(f"SET_GALVO_POS_XY {x},{y}", expect_prefix="SET_GALVO_POS_XY:")
        self._position_x = x
        self._position_y = y

    def close(self):
        self.dev.close()

    def get_position(self) -> Tuple[int, int]:
        """Return the internally tracked position (not from hardware query).

        This avoids inaccurate hardware feedback; we trust what we commanded.
        """
        return self._position_x, self._position_y

    def _set_660_laser(self, enable: bool) -> None:
        """Send the movement command and update internal state."""
        if (enable):
            self.dev.query(f"SET_LASER_STATE 0,1")
            self.dev.query(f"SET_LASER_PWR 0,28")
        else:
            self.dev.query(f"SET_LASER_STATE 0,0")
            self.dev.query(f"SET_LASER_PWR 0,0")

    def move_2_pos(self, x: int, y: int) -> Tuple[int, int]:
        """Command the galvo to move to the given coordinates.

        Returns the internally tracked position.
        """
        self._move_internal(x, y)
        return self.get_position()

    def move_direction(self, direction: str, step: int = 25) -> Tuple[int, int]:
        """Convenience helper to nudge the galvo in a cardinal direction."""
        x, y = self.get_position()
        if direction == "up":
            y += step
        elif direction == "down":
            y -= step
        elif direction == "left":
            x -= step
        elif direction == "right":
            x += step
        return self.move_2_pos(x, y)

    def stop(self) -> None:
        """Close connection (no explicit stop command exists)."""
        self.close()


# simple demonstration when invoked directly
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
    gi._set_660_laser(True)
    # print("current", gi.get_position())
    # gi.move_2_pos(2000, 2000)
    # print("after move", gi.get_position())
    # gi.stop()

