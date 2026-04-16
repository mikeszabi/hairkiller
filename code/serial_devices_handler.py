#!/usr/bin/env python3
import argparse
import sys
import time
from dataclasses import dataclass
from typing import List, Optional

import serial
from serial.tools import list_ports
from serial_commands import is_async_message

DEFAULT_PORT = '/dev/ttyACM0'
DEFAULT_BAUD = 115200
DEFAULT_TIMEOUT_S = 0.4
DEFAULT_EOL = "\n"  # change to "\r\n" if the device requires CRLF


def list_serial_ports() -> List[str]:
    return [p.device for p in list_ports.comports()]


@dataclass
class SerialDevice:
    port: str = DEFAULT_PORT
    baud: int = DEFAULT_BAUD
    timeout_s: float = DEFAULT_TIMEOUT_S
    eol: str = DEFAULT_EOL
    debug: bool = True

    def __post_init__(self) -> None:
        self._async_messages: List[str] = []

    def open(self) -> None:
        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.timeout_s,
            write_timeout=1.0,
        )
        # Some USB-serial chips reset on open; short settle helps.
        time.sleep(0.2)
        self.flush()

    def close(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass

    def flush(self) -> None:
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()

    def _read_available_lines(self, max_lines: int = 50) -> List[str]:
        lines = []
        for _ in range(max_lines):
            raw = self.ser.readline()
            if not raw:
                break
            try:
                s = raw.decode("utf-8", errors="replace").strip()
            except Exception:
                s = str(raw)
            if s:
                if is_async_message(s):
                    self._async_messages.append(s)
                lines.append(s)
        return lines

    def pop_async_messages(self) -> List[str]:
        messages = list(self._async_messages)
        self._async_messages.clear()
        return messages

    def query(
        self,
        cmd: str,
        expect_prefix: Optional[str] = None,
        wait_s: float = 0.05,
        retries: int = 0,
        extra_read_window_s: float = 0.2,
    ) -> List[str]:
        """
        Send a command, then collect lines that arrive shortly after.
        Returns all non-empty response lines.
        """
        payload = (cmd.strip() + self.eol).encode("utf-8")

        for attempt in range(retries + 1):
            if self.debug:
                print(f">>> {cmd}")
            self.ser.write(payload)
            self.ser.flush()
            time.sleep(wait_s)

            # Read a first batch
            lines = self._read_available_lines()

            # Some commands (sequence) may produce delayed INFO lines:
            t_end = time.time() + extra_read_window_s
            while time.time() < t_end:
                more = self._read_available_lines()
                if more:
                    lines.extend(more)
                    # extend window a bit if we keep receiving data
                    t_end = time.time() + extra_read_window_s
                else:
                    time.sleep(0.02)

            if self.debug:
                for ln in lines:
                    print(f"<<< {ln}")

            if expect_prefix is None:
                return lines

            if any(ln.startswith(expect_prefix) for ln in lines):
                return lines

            if attempt < retries:
                time.sleep(0.1)

        return lines


def parse_args_base(description: str):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--port", help="Serial port (e.g. /dev/ttyUSB0 or COM5)", default=DEFAULT_PORT)
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--eol", default=DEFAULT_EOL, help=r"Line ending: '\n' or '\r\n'")
    ap.add_argument("--quiet", action="store_true", help="Less console output")
    ap.add_argument("--list-ports", action="store_true", help="List available serial ports and exit")
    return ap
