#!/bin/bash

# Get the group of /dev/ttyUSB0
GROUP=$(stat -c "%G" /dev/ttyUSB0)

# Add the current user to the group
sudo usermod -a -G "$GROUP" $USER

# Change the permissions of /dev/ttyUSB0 to allow read and write access for the group
sudo dmesg | grep ttyUSB0
sudo chmod 660 /dev/ttyUSB0

# Notify the user to log out and log back in
echo "User $USER has been added to the group $GROUP and permissions for /dev/ttyUSB0 have been updated. Please log out and log back in for the changes to take effect."