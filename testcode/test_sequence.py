#!/usr/bin/env python3
import time

from serial_device import SerialDevice, list_serial_ports, parse_args_base


def main():
    ap = parse_args_base("Sequence test: SET_* + START_SEQ_TEST (no safety checks)")
    ap.add_argument("--pulse-ms", type=int, default=1000)
    ap.add_argument("--curr", type=int, default=50)
    ap.add_argument("--length", type=int, default=5)
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

    # Example 5 points along y=2900
    points = [
        (0, 2000, 2900),
        (1, 2400, 2900),
        (2, 2800, 2900),
        (3, 3200, 2900),
        (4, 3600, 2900),
    ]

    try:
        dev.open()

        # Configure sequence
        dev.query("SET_ACTIVE_LASERS 1,1,1,0", expect_prefix="SET_ACTIVE_LASERS:")
        dev.query(f"SET_LAS_CURR {args.curr}", expect_prefix="SET_LAS_CURR:")
        dev.query(f"SET_LAS_PULSE {args.pulse_ms}", expect_prefix="SET_LAS_PULSE:")
        dev.query(f"SET_SEQ_LENGTH {args.length}", expect_prefix="SET_SEQ_LENGTH:")

        for idx, x, y in points[: args.length]:
            dev.query(f"SET_TARGET_POINT {idx},{x},{y}", expect_prefix="SET_TARGET_POINT:")

        # Start test sequence
        # give bigger window because "INFO: Sequence finished" is delayed
        dev.query("START_SEQ_TEST", expect_prefix="START_SEQ_TEST:", extra_read_window_s=2.0)

        # Keep reading for completion info (if device sends it later)
        t_end = time.time() + (args.length * (args.pulse_ms / 1000.0) + 5.0)
        finished = False
        while time.time() < t_end and not finished:
            lines = dev.query("", expect_prefix=None, wait_s=0.0, extra_read_window_s=0.5)  # just read window
            finished = any("INFO: Sequence finished" in ln for ln in lines)
            time.sleep(0.1)

        if not finished:
            print("WARNING: Did not see 'INFO: Sequence finished' within expected time window.")

        return 0
    finally:
        dev.close()


if __name__ == "__main__":
    raise SystemExit(main())


#python test_sequence.py --port /dev/ttyACM0