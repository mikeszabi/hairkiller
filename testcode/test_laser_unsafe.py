#!/usr/bin/env python3
import time

from serial_device import SerialDevice, list_serial_ports, parse_args_base

# !!! SAFETY GATE !!!
I_UNDERSTAND = True  # <-- set True only if you really want to run this on real hardware


def main():
    if not I_UNDERSTAND:
        print("Refusing to run: set I_UNDERSTAND=True in the script to enable UNSAFE laser tests.")
        return 3

    ap = parse_args_base("UNSAFE laser tests")
    ap.add_argument("--laser", type=int, choices=[0, 1, 2, 3, 4], default=4, help="0:660 1:808 2:980 3:1064 4:ALL")
    ap.add_argument("--pwr", type=int, default=10, help="1-100")
    ap.add_argument("--enable-dcdc", action="store_true", help="SET_LASER_DCDC 1")
    ap.add_argument("--disable-dcdc", action="store_true", help="SET_LASER_DCDC 0")
    ap.add_argument("--enable-reg", action="store_true", help="SET_LASER_STATE <laser>,1")
    ap.add_argument("--disable-reg", action="store_true", help="SET_LASER_STATE <laser>,0")
    ap.add_argument("--shunt-off", action="store_true", help="SET_SHUNT_STATE 0 (remove short) DANGEROUS")
    ap.add_argument("--shunt-on", action="store_true", help="SET_SHUNT_STATE 1 (apply short)")
    ap.add_argument("--arm", action="store_true", help="ARM_LASER")
    ap.add_argument("--disarm", action="store_true", help="DISARM_LASER (recommended)")
    ap.add_argument("--ack", action="store_true", help="ACK_ERRORS")
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

        # Always start by checking status
        dev.query("STATUS", expect_prefix="STATUS:")

        if args.ack:
            dev.query("ACK_ERRORS", expect_prefix="ACK_ERRORS:")

        # Power setpoint
        dev.query(f"SET_LASER_PWR {args.laser},{args.pwr}", expect_prefix="SET_LASER_PWR:")

        # DCDC
        if args.enable_dcdc and args.disable_dcdc:
            print("Choose only one: --enable-dcdc or --disable-dcdc")
            return 2
        if args.enable_dcdc:
            dev.query("SET_LASER_DCDC 1", expect_prefix="SET_LASER_DCDC:")
        if args.disable_dcdc:
            dev.query("SET_LASER_DCDC 0", expect_prefix="SET_LASER_DCDC:")

        # Regulator enable/disable
        if args.enable_reg and args.disable_reg:
            print("Choose only one: --enable-reg or --disable-reg")
            return 2
        if args.enable_reg:
            dev.query(f"SET_LASER_STATE {args.laser},1", expect_prefix="SET_LASER_STATE:")
        if args.disable_reg:
            dev.query(f"SET_LASER_STATE {args.laser},0", expect_prefix="SET_LASER_STATE:")

        # Shunt (last safety mechanism)
        if args.shunt_off and args.shunt_on:
            print("Choose only one: --shunt-off or --shunt-on")
            return 2
        if args.shunt_on:
            dev.query("SET_SHUNT_STATE 1", expect_prefix="SET_SHUNT_STATE:")
        if args.shunt_off:
            dev.query("SET_SHUNT_STATE 0", expect_prefix="SET_SHUNT_STATE:")

        # Arm/Disarm
        if args.arm:
            dev.query("ARM_LASER", expect_prefix="ARM_LASER:")
        if args.disarm:
            dev.query("DISARM_LASER", expect_prefix="DISARM_LASER:")

        # Final status
        dev.query("STATUS", expect_prefix="STATUS:")

        return 0
    finally:
        dev.close()


if __name__ == "__main__":
    raise SystemExit(main())


# python test_laser_unsafe.py --port /dev/ttyACM0 --ack --arm
# python test_laser_unsafe.py --port /dev/ttyACM0 --laser 1 --pwr 10 --enable-dcdc --enable-reg --shunt-on
# python test_laser_unsafe.py --port /dev/ttyACM0 --disarm