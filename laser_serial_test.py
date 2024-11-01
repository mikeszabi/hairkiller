#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Feb 20 11:01:16 2023

@author: itqs
"""

# sudo chown $USER ttyUSB0


import serial


def checksum_calc(data):
        checksum = 0
        for ch in data:
                checksum += ord(ch)
        return hex(checksum % 256)


port='/dev/ttyUSB0'
ser = serial.Serial(port)  # open serial port
ser.baudrate='9600'

if ser.isOpen():
    ser.close()
ser.open()
print(ser.isOpen())



# shoot
laser_impulse_time=50 #millisec

packet = bytearray()
packet.append(2)
packet.append(1)
packet.append(laser_impulse_time)
packet.append(3)
checksum = sum(packet)
packet.append(checksum % 256)

print(packet)

ser.write(packet)

#pointer laser on
packet = bytearray()
packet.append(2)
packet.append(2)
packet.append(3)
checksum = sum(packet)
packet.append(checksum % 256)

print(packet)

ser.write(packet)


#pointer laser off

packet = bytearray()
packet.append(2)
packet.append(3)
packet.append(3)
checksum = sum(packet)
packet.append(checksum % 256)

print(packet)

ser.write(packet)