#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Dec 14 16:24:15 2020

@author: itqs
"""


import time
import serial
import os

def serial_access():
    # dmesg | grep tty
    os.system('sudo dmesg | grep tty')

    # sudo chmod 666 /dev/ttyUSB0 
    os.system('sudo chmod 666 /dev/ttyUSB0')
    # Laser
    # sudo minicom -D /dev/ttyUSB0 -b 9600

class LaserInterface:

    def __init__(self, port='/dev/ttyUSB0'):
        self.port=port
        self.ser = serial.Serial(self.port)  # open serial port
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
        
        
def main():

    # port = '/dev/ttyUSB0'  # For Linux
    laser = LaserInterface()
    
    try:
        print("Turning laser on...")
        laser.plaser_on()
        time.sleep(2)
        
        print("Setting impulse to 50...")
        laser.setImpulse(50)
        time.sleep(2)
        
        print("Turning laser off...")
        laser.plaser_off()
        time.sleep(2)
        
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        print("Stopping laser interface...")
        laser.stop()

if __name__ == "__main__":
    main()
