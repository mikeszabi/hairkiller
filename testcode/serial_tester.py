#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Feb 20 11:01:16 2023

@author: itqs
"""
# sudo dmesg | grep tty
# ls -l /dev/serial/by-id/
# board : usb-STMicroelectronics_STM32_Virtual_ComPort_0D4734413638-if00

# sudo chown $USER ttyACM0
# sudo chown $USER ttyUSB1

import serial

# Constants
STX = 2
ETX = 3

# Initialize serial port
#ser = serial.Serial('usb-STMicroelectronics_STM32_Virtual_ComPort_0D4734413638-if00', baudrate=115200, timeout=1)

ser = serial.Serial('/dev/ttyACM0', baudrate=115200, timeout=1)
ser.close()
ser.open()
print(ser.isOpen())

# def sendcmd(command, data):
#     """
#     Send a command to the serial port.
#     :param command: The command to send.
#     :param data: The data array (6 elements long).
#     """
#     packet = bytearray(10)  # 8-byte buffer
#     chksum = command

#     packet[0] = STX
#     packet[1] = command

#     # Add data and calculate checksum
#     for k in range(6):
#         packet[k + 2] = data[k]
#         chksum += data[k]

#     packet[8] = ETX
#     #buf.append(chksum & 0xFF)  # Ensure checksum is within byte range
#     packet[9] = chksum & 0xFF

#     # Send to serial port
#     ser.write(packet)

# # Example data initialization
# Galvo1 = 1750  # Example value, set as needed
# Galvo2 = 1600  # Example value, set as needed

# data = [
#     Galvo1 & 0xff,  # Lower 8 bits
#     Galvo1 >> 8,    # Upper 8 bits
#     Galvo2 & 0xff,  # Lower 8 bits
#     Galvo2 >> 8,    # Upper 8 bits
#     0,              # Empty byte
#     0               # Empty byte
# ]

# # Send command
# sendcmd(5, data)

# ser.close()