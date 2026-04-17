#!/usr/bin/env python3
"""Small galvo motion tester using the shared serial helpers.

Examples:
    python testcode/galvo_tester.py 1750 1600
    python testcode/galvo_tester.py 1750 1600 --readback
    python testcode/galvo_tester.py --list-ports
"""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.append(str(Path(__file__).resolve().parent.parent / "code"))

from serial_commands import build_command  # type: ignore  # added to path at runtime
from serial_devices_handler import (  # type: ignore  # added to path at runtime
    SerialDevice,
    list_serial_ports,
    parse_args_base,
)


GALVO_MIN = 0
GALVO_MAX = 4095


def _clamp(value: int) -> int:
    return max(GALVO_MIN, min(GALVO_MAX, value))


def main() -> int:
    ap = parse_args_base("Move galvo to a target position using shared serial helpers")
    ap.add_argument("x", type=int, nargs="?", default=1750, help="Target X position (0-4095)")
    ap.add_argument("y", type=int, nargs="?", default=1600, help="Target Y position (0-4095)")
    ap.add_argument(
        "--readback",
        action="store_true",
        help="Query TARGET_GET_POS after moving and print the reply",
    )
    ap.add_argument(
        "--feedback",
        action="store_true",
        help="Query TARGET_GET_FB_POS after moving and print the reply",
    )
    args = ap.parse_args()

    if args.list_ports:
        ports = list_serial_ports()
        print("\n".join(ports) if ports else "No serial ports found.")
        return 0

    x = _clamp(args.x)
    y = _clamp(args.y)
    if (x, y) != (args.x, args.y):
        print(f"Clamped requested position ({args.x}, {args.y}) -> ({x}, {y})")

    dev = SerialDevice(
        port=args.port,
        baud=args.baud,
        timeout_s=args.timeout,
        eol=args.eol.encode("utf-8").decode("unicode_escape"),
        debug=not args.quiet,
    )

    try:
        dev.open()

        move_cmd = build_command("TARGET_SET_POS", x, y)
        move_resp = dev.query(move_cmd, expect_prefix=None, extra_read_window_s=0.2)
        print(f"Moved galvo to ({x}, {y})")
        if move_resp:
            print("Move response:")
            for line in move_resp:
                print(f"  {line}")
        else:
            print("Move response: (no response)")

        if args.readback:
            pos_resp = dev.query(build_command("TARGET_GET_POS"), expect_prefix=None, extra_read_window_s=0.2)
            print("Reported target position:")
            if pos_resp:
                for line in pos_resp:
                    print(f"  {line}")
            else:
                print("  (no response)")

        if args.feedback:
            fb_resp = dev.query(build_command("TARGET_GET_FB_POS"), expect_prefix=None, extra_read_window_s=0.2)
            print("Galvo feedback position:")
            if fb_resp:
                for line in fb_resp:
                    print(f"  {line}")
            else:
                print("  (no response)")
    finally:
        dev.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
