"""Laser controller wrapper built on serial_devices_handler and serial_commands.

The goal is to mirror the public surface of the previous LaserControlInterface
that hk_full_app expects while speaking the *new* command set defined in
serial_commands.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from serial_devices_handler import (
    DEFAULT_BAUD,
    DEFAULT_PORT,
    SerialDevice,
)
from serial_commands import build_command, sensor_values_to_dict


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


@dataclass
class LaserInterface:
    """High-level laser power/control API."""

    port: str = DEFAULT_PORT
    baud: int = DEFAULT_BAUD
    timeout_s: Optional[float] = None
    debug: bool = False

    # Internal state for power channels
    channel_power: List[int] = field(default_factory=lambda: [0, 0, 0])  # order: 808, 980, 1064
    active: List[bool] = field(default_factory=lambda: [True, True, True])  # order: 808, 980, 1064

    def __post_init__(self) -> None:
        kwargs = {}
        if self.timeout_s is not None:
            kwargs["timeout_s"] = self.timeout_s
        self.dev = SerialDevice(
            port=self.port,
            baud=self.baud,
            debug=self.debug,
            **kwargs,
        )
        self.dev.open()

    # --------------- low-level helpers -----------------
    def _send_cmd(self, command_name: str, *params, expect_prefix: Optional[str] = None):
        payload = build_command(command_name, *params)
        try:
            return self.dev.query(payload, expect_prefix=expect_prefix, extra_read_window_s=0.5)
        except Exception as exc:  # pragma: no cover - runtime safety
            return [f"ERROR: {exc}"]

    # --------------- high-level API --------------------
    def arm_laser(self):
        """Arm laser (LASER_SET_ARM_EN 1)."""
        return self._send_cmd("LASER_SET_ARM_EN", 1)

    def disarm_laser(self):
        """Disarm laser (LASER_SET_ARM_EN 0)."""
        return self._send_cmd("LASER_SET_ARM_EN", 0)

    def ack_errors(self):
        """Clear laser errors."""
        # Prefer laser-specific clear; fall back to app-wide clear.
        resp = self._send_cmd("LASER_CLEAR_ERROR")
        if resp:
            return resp
        return self._send_cmd("APP_CLEAR_ERROR")

    def set_laser_pwr(self, laser_id: int, pwr: int):
        """Set one channel (1=1064, 2=980, 3=808, 4=all)."""
        pwr = _clamp(pwr, 0, 100)
        idx_map = {1: 2, 2: 1, 3: 0}
        if laser_id == 4:
            self.channel_power = [pwr, pwr, pwr]
        elif laser_id in idx_map:
            self.channel_power[idx_map[laser_id]] = pwr
        else:
            return [f"ERROR: invalid laser_id {laser_id}"]
        return self._apply_channel_power()

    def set_active_lasers(self, l1064: int, l980: int, l808: int, l660: int = 0):
        """Toggle active channels (booleans). 660 is mapped to red-dot enable."""
        # Active order internally: 808, 980, 1064
        self.active = [bool(l808), bool(l980), bool(l1064)]
        power_resp = self._apply_channel_power()
        red_resp = self.set_red_dot(bool(l660))
        return power_resp + red_resp
    
    def set_red_dot(self, enabled: bool):
        """Toggle red dot (mapped to 660nm channel)."""
        red_dot_resp = self._send_cmd("LASER_SET_RED_DOT_EN", 1 if enabled else 0)
        return red_dot_resp

    def set_las_curr(self, curr: int):
        """Set same current for all active channels."""
        curr = _clamp(curr, 0, 100)
        for i, enabled in enumerate(self.active):
            if enabled:
                self.channel_power[i] = curr
        return self._apply_channel_power()

    def get_laser_temp(self):
        """Return laser temperature from sensor snapshot (Celsius)."""
        resp = self._send_cmd("SENSORS_GET_VALUES")
        if not resp:
            return resp
        try:
            # Expect first line payload after arrow; split on '->'
            line = resp[0]
            payload = line.split("->", 1)[-1].strip("[]")
            values = [float(v) for v in payload.split(",") if v]
            mapping = sensor_values_to_dict(values)
            return [mapping.get("laserTemp_C", "N/A")]
        except Exception:
            return resp

    def close(self):
        self.dev.close()

    def get_channel_power_triplet(self) -> Tuple[int, int, int]:
        """Return (808, 980, 1064) powers with inactive channels zeroed."""
        return (
            self.channel_power[0] if self.active[0] else 0,
            self.channel_power[1] if self.active[1] else 0,
            self.channel_power[2] if self.active[2] else 0,
        )

    # --------------- internal helpers ------------------
    def _apply_channel_power(self):
        """Apply current channel power/state to the device."""
        vals = [
            self.channel_power[0] if self.active[0] else 0,  # 808
            self.channel_power[1] if self.active[1] else 0,  # 980
            self.channel_power[2] if self.active[2] else 0,  # 1064
        ]
        return self._send_cmd("LASER_SET_CHANNEL_PWR", *vals)

    # --------------- end class ------------------


# convenience alias to mirror previous naming
LaserControlInterface = LaserInterface
