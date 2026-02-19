#!/usr/bin/env python3
from serial_device import SerialDevice, list_serial_ports, parse_args_base

def main():
    ap = parse_args_base("Interactive serial REPL (type commands, Ctrl+C to exit)")
    args = ap.parse_args()

    if args.list_ports:
        ports = list_serial_ports()
        print("\n".join(ports) if ports else "No serial ports found.")
        return 0

    if not args.port:
        print("Please provide --port. Available ports:", list_serial_ports())
        return 2

    dev = SerialDevice(
        port=args.port,
        baud=args.baud,
        timeout_s=args.timeout,
        eol=args.eol.encode("utf-8").decode("unicode_escape"),
        debug=False,
    )
    dev.open()
    print("Connected. Type commands like: STATUS / PING / GET_GALVO_POS_XY")
    try:
        while True:
            cmd = input("cmd> ").strip()
            if not cmd:
                continue
            lines = dev.query(cmd, expect_prefix=None, extra_read_window_s=0.5)
            if not lines:
                print("(no response)")
    except KeyboardInterrupt:
        print("\nBye.")
    finally:
        dev.close()

if __name__ == "__main__":
    raise SystemExit(main())

# python serial_repl.py --port /dev/ttyACM0