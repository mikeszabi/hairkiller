#!/usr/bin/env python3
import time

from serial_device import SerialDevice, list_serial_ports, parse_args_base

GALVO_POINTS = {
    "CENTER": (2900, 2900),
    "TOP":    (2900, 1200),
    "LEFT":   (1250, 2900),
    "RIGHT":  (4095, 2900),
    "BOTTOM": (2900, 2900),
}

def main():
    ap = parse_args_base("Galvo test: SET_GALVO_POS_XY + GET_GALVO_POS_XY")
    ap.add_argument("--point", choices=list(GALVO_POINTS.keys()) + ["ALL"], default="ALL")
    ap.add_argument("--dwell-ms", type=int, default=250, help="Wait after move (ms)")
    args = ap.parse_args()

    if args.list_ports:
        ports = list_serial_ports()
        print("\n".join(ports) if ports else "No serial ports found.")
        return 0

    if not args.port:
        ports = list_serial_ports()
        print("Please provide --port. Available ports:", ports)
        return 2

    dev = SerialDevice(
        port=args.port,
        baud=args.baud,
        timeout_s=args.timeout,
        eol=args.eol.encode("utf-8").decode("unicode_escape"),
        debug=not args.quiet,
    )

    try:
        dev.open()

        names = list(GALVO_POINTS.keys()) if args.point == "ALL" else [args.point]
        for name in names:
            x, y = GALVO_POINTS[name]
            dev.query(f"SET_GALVO_POS_XY {x},{y}", expect_prefix="SET_GALVO_POS_XY:")
            time.sleep(args.dwell_ms / 1000.0)
            dev.query("GET_GALVO_POS_XY", expect_prefix="GET_GALVO_POS_XY:")

        # Return to center at the end if we did multiple moves
        if args.point == "ALL":
            x, y = GALVO_POINTS["CENTER"]
            dev.query(f"SET_GALVO_POS_XY {x},{y}", expect_prefix="SET_GALVO_POS_XY:")

        return 0
    finally:
        dev.close()

if __name__ == "__main__":
    raise SystemExit(main())

# python test_galvo.py --port /dev/ttyACM0 --point ALL
# python test_galvo.py --port /dev/ttyACM0 --point LEFT