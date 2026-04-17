#!/bin/bash

# Change ownership of the laser device to the current user
sudo chown $USER /dev/serial/by-id/usb-STMicroelectronics_STM32_Virtual_ComPort_024731423034-if00

echo "Ownership of serial devices changed to $USER"

#!/bin/bash

# Get the group of /dev/ttyUSB0
GROUP=$(stat -c "%G" /dev/ttyACM0)

# Add the current user to the group
sudo usermod -a -G "$GROUP" $USER

# Change the permissions of /dev/ttyUSB0 to allow read and write access for the group
sudo dmesg | grep ttyACM0
sudo chmod 660 /dev/ttyACM0

# Notify the user to log out and log back in
echo "User $USER has been added to the group $GROUP and permissions for /dev/ttyUSB0 have been updated. Please log out and log back in for the changes to take effect."
