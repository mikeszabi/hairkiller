#!/usr/bin/env python3
import argparse
import queue
import sys
import threading
import time
from dataclasses import dataclass
from typing import List, Optional

import serial
from serial.tools import list_ports
from serial_commands import is_async_message, response_payload_tokens, response_status

DEFAULT_PORT = '/dev/ttyACM0'
DEFAULT_BAUD = 115200
DEFAULT_TIMEOUT_S = 0.1
DEFAULT_COMMAND_TIMEOUT_S = 1.0
DEFAULT_EOL = "\r\n"


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
        self._response_lines: "queue.Queue[str]" = queue.Queue()
        self._query_lock = threading.Lock()
        self._async_lock = threading.Lock()
        self._reader_stop = threading.Event()
        self._reader: Optional[threading.Thread] = None
        self.ser = None

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
        self._reader_stop.clear()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def close(self) -> None:
        self._reader_stop.set()
        if self._reader is not None:
            self._reader.join(timeout=1.0)
        try:
            self.ser.close()
        except Exception:
            pass

    def flush(self) -> None:
        self.ser.reset_input_buffer()
        self.ser.reset_output_buffer()
        self._drain_response_queue()

    @staticmethod
    def command_prefix(cmd: str) -> str:
        return str(cmd).strip().split(maxsplit=1)[0].strip().upper()

    @staticmethod
    def _prefix_token(prefix: str) -> str:
        prefix = str(prefix).strip()
        if prefix.startswith("["):
            return prefix
        return f"[{prefix}]"

    @staticmethod
    def _line_matches_prefix(line: str, prefix: str) -> bool:
        return str(line).strip().upper().startswith(str(prefix).strip().upper())

    def _read_loop(self) -> None:
        while not self._reader_stop.is_set():
            try:
                raw = self.ser.readline()
            except Exception as exc:
                with self._async_lock:
                    self._async_messages.append(f"[SERIAL_ERROR]->[{exc}]")
                self._reader_stop.set()
                return

            if not raw:
                continue
            try:
                line = raw.decode("utf-8", errors="replace").strip()
            except Exception:
                line = str(raw).strip()
            if not line:
                continue
            if is_async_message(line):
                with self._async_lock:
                    self._async_messages.append(line)
            self._response_lines.put(line)

    def _drain_response_queue(self, max_lines: int = 200) -> List[str]:
        lines: List[str] = []
        for _ in range(max_lines):
            try:
                line = self._response_lines.get_nowait()
            except queue.Empty:
                break
            lines.append(line)
        return lines

    def _read_available_lines(self, max_lines: int = 50) -> List[str]:
        lines = []
        for _ in range(max_lines):
            try:
                if getattr(self.ser, "in_waiting", 0) <= 0:
                    break
            except Exception:
                pass
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
        with self._async_lock:
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
        Send a command and return the matching response lines.

        This mirrors the fast tester: a background reader owns readline(), while
        each query waits only until the controller emits OK/NOK/END for the
        command prefix. The wait_s and extra_read_window_s arguments are kept
        for compatibility with older callers; extra_read_window_s now acts as a
        minimum command timeout instead of an unconditional post-write sleep.
        """
        payload = (cmd.strip() + self.eol).encode("utf-8")
        prefix = self._prefix_token(expect_prefix or self.command_prefix(cmd))
        timeout_s = max(DEFAULT_COMMAND_TIMEOUT_S, float(extra_read_window_s or 0.0))

        with self._query_lock:
            last_lines: List[str] = []
            for attempt in range(retries + 1):
                self._drain_response_queue()
                if self.debug:
                    print(f">>> {cmd}")
                self.ser.write(payload)
                self.ser.flush()

                matched: List[str] = []
                unmatched: List[str] = []
                awaiting_end = False
                deadline = time.monotonic() + timeout_s
                while time.monotonic() < deadline:
                    try:
                        line = self._response_lines.get(timeout=0.02)
                    except queue.Empty:
                        continue

                    if self.debug:
                        print(f"<<< {line}")

                    if not self._line_matches_prefix(line, prefix):
                        unmatched.append(line)
                        continue

                    matched.append(line)
                    status = response_status(line)
                    payload_tokens = response_payload_tokens(line)
                    first_payload = payload_tokens[0].strip() if payload_tokens else ""
                    is_count_header = first_payload.upper().startswith("COUNT,")
                    if is_count_header:
                        awaiting_end = True

                    if status == "NOK":
                        return matched
                    if status == "END":
                        return matched
                    if status == "OK" and not is_count_header:
                        return matched
                    if status is None and not is_count_header and not awaiting_end:
                        return matched

                last_lines = matched or unmatched
                if matched:
                    return matched
                if attempt < retries:
                    time.sleep(0.05)

            return last_lines


def parse_args_base(description: str):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--port", help="Serial port (e.g. /dev/ttyUSB0 or COM5)", default=DEFAULT_PORT)
    ap.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    ap.add_argument("--eol", default=DEFAULT_EOL, help=r"Line ending: '\n' or '\r\n'")
    ap.add_argument("--quiet", action="store_true", help="Less console output")
    ap.add_argument("--list-ports", action="store_true", help="List available serial ports and exit")
    return ap
