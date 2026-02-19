import sys
import time

from serial_device import SerialDevice, list_serial_ports, parse_args_base


def main():
    ap = parse_args_base("Basic comms test: PING / STATUS / unknown / RESET")
    ap.add_argument("--do-reset", action="store_true", help="Also send RESET (reboots device)")
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

        # PING
        dev.query("PING", expect_prefix="PING:")

        # STATUS
        dev.query("STATUS", expect_prefix="STATUS:")

        # Unknown command test
        dev.query("THIS_IS_NOT_A_CMD", expect_prefix="ERR:")

        # Optional RESET
        if args.do_reset:
            dev.query("RESET", expect_prefix="RESET:")
            # Give it time to reboot and re-enumerate if needed
            time.sleep(1.0)

        return 0
    finally:
        dev.close()


if __name__ == "__main__":
    raise SystemExit(main())

# python test_basic.py --list-ports
# python test_basic.py --port /dev/ttyACM0
# python test_basic.py --port /dev/ttyACM0 --do-reset