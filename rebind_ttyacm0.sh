#!/usr/bin/env bash
set -euo pipefail

PORT="/dev/ttyACM0"
USB_ID=""

if [ -e "$PORT" ]; then
  echo "$PORT exists."
  exit 0
fi

echo "$PORT not found. Searching USB ACM devices..."

for dev in /sys/bus/usb/devices/*; do
  [ -e "$dev/idVendor" ] || continue
  [ -e "$dev/idProduct" ] || continue

  if find "$dev" -name "ttyACM*" | grep -q .; then
    USB_ID="$(basename "$dev")"
    break
  fi
done

if [ -z "$USB_ID" ]; then
  echo "No USB ACM device found in sysfs."
  echo "Try: dmesg -w"
  exit 1
fi

echo "Rebinding USB device: $USB_ID"

echo "$USB_ID" | sudo tee /sys/bus/usb/drivers/usb/unbind >/dev/null
sleep 2
echo "$USB_ID" | sudo tee /sys/bus/usb/drivers/usb/bind >/dev/null

sleep 2

if [ -e "$PORT" ]; then
  echo "Success: $PORT is back."
else
  echo "Rebind done, but $PORT still not found."
  echo "Check: dmesg | tail -50"
  exit 1
fi