"""Vacuum controller wrapper using serial_commands and SerialDevice."""

from __future__ import annotations

import argparse
import re
import sys
from typing import Optional

from serial_devices_handler import SerialDevice, DEFAULT_PORT, DEFAULT_BAUD
from serial_commands import build_command


def _extract_bool_response(lines: list[str]) -> Optional[bool]:
    """Extract a firmware boolean response formatted like [CMD]->[1][TS]."""
    if not isinstance(lines, list):
        return None

    for line in lines:
        text = str(line).strip()
        match = re.search(r"->\[(.*?)\]", text)
        if not match:
            continue

        value = match.group(1).strip()
        if value == "1":
            return True
        if value == "0":
            return False

    return None


class VacuumInterface:
    """High-level vacuum output and vacuum-check control API."""

    parse_bool_response = staticmethod(_extract_bool_response)

    def __init__(
        self,
        dev: Optional[SerialDevice] = None,
        port: str = DEFAULT_PORT,
        baud: int = DEFAULT_BAUD,
        timeout_s: Optional[float] = None,
        debug: bool = False,
    ):
        self.dev = dev
        self._owns_dev = dev is None

        if self.dev is None:
            kwargs = {}
            if timeout_s is not None:
                kwargs["timeout_s"] = timeout_s
            self.dev = SerialDevice(port=port, baud=baud, debug=debug, **kwargs)
            self.dev.open()

    # ---------- helpers ----------
    def _send(self, cmd_name: str, *params, wait_s: float = 0.05, extra_read_window_s: float = 0.2):
        payload = build_command(cmd_name, *params)
        try:
            return self.dev.query(
                payload,
                expect_prefix=None,
                wait_s=wait_s,
                extra_read_window_s=extra_read_window_s,
            )
        except Exception as exc:  # pragma: no cover - runtime safety
            return [f"ERROR: {exc}"]

    # ---------- vacuum output ----------
    def set_vacuum_on(self, on: bool):
        """Turn the vacuum output on or off."""
        return self._send("APP_SET_VACUUM_EN", 1 if on else 0)

    def get_vacuum_on(self):
        """Read whether the vacuum output is on."""
        return self._send("APP_GET_VACUUM_EN")

    def is_vacuum_on(self) -> Optional[bool]:
        """Return parsed vacuum output state, or None if the response was not parseable."""
        return _extract_bool_response(self.get_vacuum_on())

    def vacuum_on(self):
        """Turn the vacuum output on."""
        return self.set_vacuum_on(True)

    def vacuum_off(self):
        """Turn the vacuum output off."""
        return self.set_vacuum_on(False)

    # ---------- vacuum safety check ----------
    def set_check_vacuum(self, enabled: bool):
        """Enable or disable the firmware vacuum safety check."""
        return self._send("APP_SET_CHECK_VACUUM", 1 if enabled else 0)

    def get_check_vacuum(self):
        """Read whether the firmware vacuum safety check is enabled."""
        return self._send("APP_GET_CHECK_VACUUM")

    def is_check_vacuum_enabled(self) -> Optional[bool]:
        """Return parsed vacuum-check state, or None if the response was not parseable."""
        return _extract_bool_response(self.get_check_vacuum())

    def enable_vacuum_check(self):
        """Enable the firmware vacuum safety check."""
        return self.set_check_vacuum(True)

    def disable_vacuum_check(self):
        """Disable the firmware vacuum safety check."""
        return self.set_check_vacuum(False)

    def get_status(self) -> dict[str, object]:
        """Return raw and parsed vacuum state in one call for API/UI use."""
        vacuum_resp = self.get_vacuum_on()
        check_resp = self.get_check_vacuum()
        return {
            "vacuum_on": _extract_bool_response(vacuum_resp),
            "check_vacuum_enabled": _extract_bool_response(check_resp),
            "raw": {
                "vacuum_on": vacuum_resp,
                "check_vacuum_enabled": check_resp,
            },
        }

    def close(self):
        if not self._owns_dev:
            return
        try:
            self.dev.close()
        except Exception:
            pass


# compatibility alias if older code expects this name
VacuumControlInterface = VacuumInterface


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test vacuum interface via serial")
    parser.add_argument("--port", default=DEFAULT_PORT)
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "action",
        choices=["on", "off", "status", "check-on", "check-off"],
        nargs="?",
        default="status",
    )
    args = parser.parse_args()

    vi = VacuumInterface(
        port=args.port,
        baud=args.baud,
        timeout_s=args.timeout,
        debug=args.debug,
    )
    try:
        if args.action == "on":
            print(vi.vacuum_on())
        elif args.action == "off":
            print(vi.vacuum_off())
        elif args.action == "check-on":
            print(vi.enable_vacuum_check())
        elif args.action == "check-off":
            print(vi.disable_vacuum_check())
        else:
            print(vi.get_status())
    finally:
        vi.close()
        sys.exit(0)
