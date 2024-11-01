#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Dec 14 16:24:15 2020

@author: itqs
"""

# dmesg | grep tty
# sudo chmod 666 /dev/ttyUSB0 
# Laser
# sudo minicom -D /dev/ttyUSB0 -b 9600


import serial

class SerialInterface:

    def __init__(self, port='/dev/ttyUSB0'):
        self.port=port
        self.ser = serial.Serial(self.port)  # open serial port
        self.ser.baudrate='9600'
        if self.ser.isOpen():
            self.ser.close()
        self.ser.open()
        self.laser_impulse_time=20
        print(self.ser.isOpen())
        
    def shoot(self):
        
        packet = bytearray()
        packet.append(2)
        packet.append(1)
        packet.append(self.laser_impulse_time)
        packet.append(3)
        checksum = sum(packet)
        packet.append(checksum % 256)
        
        print(packet)
        
        self.ser.write(packet)
        
    def plaser_on(self):
        
        packet = bytearray()
        packet.append(2)
        packet.append(2)
        packet.append(3)
        checksum = sum(packet)
        packet.append(checksum % 256)
        
        print(packet)
        
        self.ser.write(packet)
        
    def plaser_off(self):
         
         packet = bytearray()
         packet.append(2)
         packet.append(3)
         packet.append(3)
         checksum = sum(packet)
         packet.append(checksum % 256)
         
         print(packet)
         
         self.ser.write(packet)
        
        
    def setImpulse(self,value=1):
        value=min(value,100)
        value=max(value,1)
        self.laser_impulse_time=value
        
    def stop(self):
        self.ser.close()
        
        

