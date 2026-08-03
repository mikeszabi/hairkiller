"""Laser controller wrapper built on serial_devices_handler and serial_commands.

The goal is to mirror the public surface of the previous LaserControlInterface
that hk_full_app expects while speaking the *new* command set defined in
serial_commands.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import List, Optional, Tuple

from serial_devices_handler import (
    DEFAULT_BAUD,
    DEFAULT_PORT,
    SerialDevice,
)
from serial_commands import SENSOR_FIELDS, build_command, sensor_values_to_dict


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _extract_sensor_payload(lines: list[str]) -> list[float] | None:
    """Parse the numeric payload out of a SENSORS_GET_VALUES response.

    The controller may include extra lines or wrappers, so we scan every line
    and pick the first bracketed numeric list that contains the expected number
    of sensor values.
    """
    expected_len = len(SENSOR_FIELDS)

    for line in lines:
        text = str(line).strip()
        if "SENSORS_GET_VALUES" not in text:
            continue
        if "END" in text or "Count" in text:
            continue
        if "->" not in text:
            continue

        payload = text.split("->", 1)[1].strip()
        start = payload.find("[")
        end = payload.rfind("]")
        if start != -1 and end != -1 and end > start:
            payload = payload[start + 1:end]

        try:
            values = [float(v.strip()) for v in payload.split(",") if v.strip()]
        except ValueError:
            continue

        if len(values) >= expected_len:
            return values[:expected_len]

    # Fallback: collect numeric tokens from all sensor-related lines in case the
    # firmware splits the payload across multiple lines or adds extra text.
    combined_tokens: list[float] = []
    for line in lines:
        text = str(line).strip()
        if "SENSORS_GET_VALUES" not in text:
            continue
        if "END" in text or "Count" in text:
            continue

        if "->" in text:
            text = text.split("->", 1)[1]

        for token in re.findall(r"[-+]?\d+(?:\.\d+)?", text):
            try:
                combined_tokens.append(float(token))
            except ValueError:
                continue

    if len(combined_tokens) >= expected_len:
        return combined_tokens[:expected_len]

    return None


def _extract_legacy_sensor_values(lines: list[str]) -> dict[str, float] | None:
    """Parse legacy sensor text like:

    ADC: ADCts:2849309, Iin:690mA, ... Gy:2285 I2C:Pts:2849303, ...
    """
    text = " ".join(str(line).strip() for line in lines if line).strip()
    if "ADC:" not in text:
        return None

    patterns = {
        "inputCurrent_mA": r"\bIin:(-?\d+(?:\.\d+)?)mA\b",
        "laser660Curr_mA": r"\bI660:(-?\d+(?:\.\d+)?)mA\b",
        "laser808Curr_mA": r"\bI808:(-?\d+(?:\.\d+)?)mA\b",
        "laser980Curr_mA": r"\bI980:(-?\d+(?:\.\d+)?)mA\b",
        "laser1064Curr_mA": r"\bI1064:(-?\d+(?:\.\d+)?)mA\b",
        "laserPower_mV": r"\bPwr:(-?\d+(?:\.\d+)?)mV\b",
        "laserTemp_C": r"\bTlaser:(-?\d+(?:\.\d+)?)dC\b",
        "peltierVoltage_mV": r"\bVpelt:(-?\d+(?:\.\d+)?)mV\b",
        "heatsinkTemp_C": r"\bTheat:(-?\d+(?:\.\d+)?)dC\b",
        "mosfetTemp_C": r"\bTmos:(-?\d+(?:\.\d+)?)dC\b",
        "target1Temp_C": r"\bT1:(-?\d+(?:\.\d+)?)dC\b",
        "target2Temp_C": r"\bT2:(-?\d+(?:\.\d+)?)dC\b",
        "galvoPosX_raw": r"\bGx:(-?\d+(?:\.\d+)?)\b",
        "galvoPosY_raw": r"\bGy:(-?\d+(?:\.\d+)?)\b",
        "updateTimestamp_ms": r"\bADCts:(-?\d+(?:\.\d+)?)\b",
    }

    values: dict[str, float] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if not match:
            continue
        raw_value = float(match.group(1))
        if key.endswith("_C"):
            raw_value /= 10.0
        values[key] = raw_value

    if not values:
        return None

    # The legacy format does not expose separate offset values, so mirror the
    # corresponding measured currents to keep the UI populated consistently.
    if "laser660Curr_mA" in values:
        values["laser660_offset_ma"] = values["laser660Curr_mA"]
    if "laser808Curr_mA" in values:
        values["laser808_offset_ma"] = values["laser808Curr_mA"]
    if "laser980Curr_mA" in values:
        values["laser980_offset_ma"] = values["laser980Curr_mA"]
    if "laser1064Curr_mA" in values:
        values["laser1064_offset_ma"] = values["laser1064Curr_mA"]

    return values


@dataclass
class LaserInterface:
    """High-level laser power/control API."""

    port: str = DEFAULT_PORT
    baud: int = DEFAULT_BAUD
    timeout_s: Optional[float] = None
    debug: bool = False
    dev: Optional[SerialDevice] = None

    # Internal state for power channels
    channel_power: List[int] = field(default_factory=lambda: [0, 0, 0])  # order: 808, 980, 1064
    active: List[bool] = field(default_factory=lambda: [True, True, True])  # order: 808, 980, 1064
    pending_channel_power: Optional[Tuple[int, int, int]] = None

    def __post_init__(self) -> None:
        self._owns_dev = self.dev is None
        if self.dev is None:
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

    def set_arm_enabled(self, enabled: bool):
        """Set arm state directly."""
        return self._send_cmd("LASER_SET_ARM_EN", 1 if enabled else 0)

    def get_arm_enabled(self):
        """Get arm state directly."""
        return self._send_cmd("LASER_GET_ARM_EN")

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

    def get_red_dot_enabled(self):
        """Get red dot state directly."""
        return self._send_cmd("LASER_GET_RED_DOT_EN")

    def set_peltier_cooling_enabled(self, enabled: bool):
        """Enable or disable Peltier cooling."""
        return self._send_cmd("PELTIER_SET_COOLING_EN", 1 if enabled else 0)

    def get_peltier_cooling_enabled(self):
        """Get whether Peltier cooling is enabled."""
        return self._send_cmd("PELTIER_GET_COOLING_EN")

    def get_peltier_state(self):
        """Get Peltier controller state."""
        return self._send_cmd("PELTIER_GET_STATE")

    def get_peltier_last_error(self):
        """Get the last Peltier error."""
        return self._send_cmd("PELTIER_GET_LAST_ERROR")

    def clear_peltier_error(self):
        """Clear Peltier error state."""
        return self._send_cmd("PELTIER_CLEAR_ERROR")

    def set_channel_power(self, p808: int, p980: int, p1064: int):
        """Set per-channel power from the UI.

        This sends the exact firmware command triplet as entered so the UI path
        matches a manual raw serial command as closely as possible.
        """
        requested = [
            _clamp(int(p808), 0, 100),
            _clamp(int(p980), 0, 100),
            _clamp(int(p1064), 0, 100),
        ]
        resp = self._send_cmd("LASER_SET_CHANNEL_PWR", *requested)

        if self._response_is_ok(resp):
            self.channel_power = requested
            self.active = [value > 0 for value in requested]
            self.pending_channel_power = None
            return resp

        if self._response_blocked_by_runtime_state(resp):
            # Keep the UI and queued target sequences aligned with the latest
            # operator intent, then retry the controller write later.
            self.channel_power = requested
            self.active = [value > 0 for value in requested]
            self.pending_channel_power = tuple(requested)
            return resp + [
                "INFO: channel powers staged locally and will sync when app is RUNNING and no process is active"
            ]

        return resp

    def get_channel_power(self):
        """Get raw power triplet directly."""
        self.sync_pending_channel_power()
        return self._send_cmd("LASER_GET_CHANNEL_PWR")

    def fire(self, duration_ms: int):
        """Fire the laser for a bounded duration."""
        duration_ms = _clamp(int(duration_ms), 10, 1000)
        return self._send_cmd("LASER_FIRE", duration_ms)

    def stop(self):
        """Stop laser firing immediately."""
        return self._send_cmd("LASER_STOP")

    def is_active(self):
        """Check if the laser is currently firing."""
        return self._send_cmd("LASER_IS_ACTIVE")

    def get_state(self):
        """Read the controller state."""
        return self._send_cmd("LASER_GET_STATE")

    def get_last_error(self):
        """Read the last recorded laser error."""
        return self._send_cmd("LASER_GET_LAST_ERROR")

    def clear_error(self):
        """Clear the last recorded laser error."""
        return self._send_cmd("LASER_CLEAR_ERROR")

    def get_app_state(self):
        """Read the overall application state."""
        return self._send_cmd("APP_GET_STATE")

    def get_app_last_error(self):
        """Read the last recorded application error."""
        return self._send_cmd("APP_GET_LAST_ERROR")

    def clear_app_error(self):
        """Clear the last recorded application error."""
        return self._send_cmd("APP_CLEAR_ERROR")

    def app_ping(self):
        return self._send_cmd("APP_PING")

    def get_app_commands(self):
        return self._send_cmd("APP_GET_COMMANDS")

    def get_app_limits(self):
        return self._send_cmd("APP_GET_LIMITS")

    def app_reset(self):
        return self._send_cmd("APP_RESET")

    def get_app_proc_time(self):
        return self._send_cmd("APP_GET_PROC_TIME")

    def do_laser_power_test(self):
        return self._send_cmd("APP_DO_LASER_PWR_TEST")

    def get_laser_test_result(self):
        return self._send_cmd("APP_GET_LASER_TEST_RESULT")

    def get_laser_test_data(self):
        return self._send_cmd("APP_GET_LASER_TEST_DATA")

    def get_fw_version(self):
        return self._send_cmd("APP_GET_FW_VERSION")

    def get_hw_version(self):
        return self._send_cmd("APP_GET_HW_VERSION")

    def pop_async_messages(self):
        """Return async serial messages observed since last read."""
        return self.dev.pop_async_messages()

    def send_raw_command(self, command: str):
        """Send a raw serial command line as entered by the user."""
        command = str(command).strip()
        if not command:
            return ["ERROR: empty command"]
        try:
            return self.dev.query(command, expect_prefix=None, extra_read_window_s=0.5)
        except Exception as exc:  # pragma: no cover - runtime safety
            return [f"ERROR: {exc}"]

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
            values = _extract_sensor_payload(resp)
            if values is not None:
                mapping = sensor_values_to_dict(values)
            else:
                mapping = _extract_legacy_sensor_values(resp)
            if mapping is None:
                return resp
            return [mapping.get("laserTemp_C", "N/A")]
        except Exception:
            return resp

    def get_sensor_values(self):
        """Return a parsed sensor snapshot and raw response lines."""
        resp = self._send_cmd("SENSORS_GET_VALUES")
        if not resp:
            return {"raw": resp, "values": None}
        try:
            values = _extract_sensor_payload(resp)
            if values is not None:
                return {"raw": resp, "values": sensor_values_to_dict(values)}

            legacy_values = _extract_legacy_sensor_values(resp)
            if legacy_values is not None:
                return {"raw": resp, "values": legacy_values}

            return {"raw": resp, "values": None}
        except Exception:
            return {"raw": resp, "values": None}

    def close(self):
        if self._owns_dev:
            self.dev.close()

    def get_channel_power_triplet(self) -> Tuple[int, int, int]:
        """Return (808, 980, 1064) powers with inactive channels zeroed."""
        return (
            self.channel_power[0] if self.active[0] else 0,
            self.channel_power[1] if self.active[1] else 0,
            self.channel_power[2] if self.active[2] else 0,
        )

    def has_pending_channel_power(self) -> bool:
        return self.pending_channel_power is not None

    # --------------- internal helpers ------------------
    def _apply_channel_power(self):
        """Apply current channel power/state to the device."""
        vals = [
            self.channel_power[0] if self.active[0] else 0,  # 808
            self.channel_power[1] if self.active[1] else 0,  # 980
            self.channel_power[2] if self.active[2] else 0,  # 1064
        ]
        return self._send_cmd("LASER_SET_CHANNEL_PWR", *vals)

    def sync_pending_channel_power(self):
        """Retry a deferred channel-power write once the controller is ready."""
        if self.pending_channel_power is None:
            return None

        requested = self.pending_channel_power
        resp = self._send_cmd("LASER_SET_CHANNEL_PWR", *requested)
        if self._response_is_ok(resp):
            self.pending_channel_power = None
        elif not self._response_blocked_by_runtime_state(resp):
            # Keep the staged values available for the UI, but stop retrying
            # automatically on unrelated controller errors.
            self.pending_channel_power = None
        return resp

    def _response_is_ok(self, resp) -> bool:
        joined = " ".join(str(line) for line in resp)
        return "NOK" not in joined and "OK" in joined

    def _response_blocked_by_runtime_state(self, resp) -> bool:
        joined = " ".join(str(line).lower() for line in resp)
        return (
            "process is active" in joined
            or "not in running state" in joined
            or "app is not in running state" in joined
        )

    # --------------- end class ------------------


# convenience alias to mirror previous naming
LaserControlInterface = LaserInterface
