#!/bin/bash

# Change ownership of the laser device to the current user
sudo chown $USER /dev/serial/by-id/usb-FTDI_Chipi-X_FT0DI7VI-if00-port0

# Change ownership of the galvo device to the current user
sudo chown $USER /dev/serial/by-id/usb-FTDI_USB__-__Serial-if00-port0

echo "Ownership of laser and galvo devices changed to $USER"