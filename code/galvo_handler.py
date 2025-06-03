#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Dec 14 16:24:15 2020

@author: itqs
"""


import time
import serial
import os

# Constants
STX = 2
ETX = 3

class GalvoInterface:

    def __init__(self):
        #self.port='/dev/ttyUSB0'
        self.x_pos_range = (0,5000)
        self.y_pos_range = (0,5800)
        self.command=5
        self.serial_connect()
        self.current_position = (1500,1800)
        self.move_2_pos(self.current_position[0],self.current_position[1])

    def serial_connect(self):
        self.ser = serial.Serial('/dev/serial/by-id/usb-FTDI_USB__-__Serial-if00-port0', baudrate=115200, timeout=1)
        if self.ser.isOpen():
            self.ser.close()
        self.ser.open()
        print(self.ser.isOpen())

    def serial_close(self):
        self.ser.close()

    def get_position(self):
        return self.current_position
    
    def move_2_pos(self, x, y):
        if (x<self.x_pos_range[0] or x>self.x_pos_range[1] or y<self.y_pos_range[0] or y>self.y_pos_range[1]):
            raise ValueError('The position is out of range')
            return None
        try:
            self._move(x,y)
        except Exception as e:
            print(e)
            return None
        self.current_position = (x,y)
        return self.current_position

    def _sendcmd(self,command, data):
        """
        Send a command to the serial port.
        :param command: The command to send.
        :param data: The data array (6 elements long).
        """
        packet = bytearray(10)  # 8-byte buffer
        chksum = command

        packet[0] = STX
        packet[1] = command

        # Add data and calculate checksum
        for k in range(6):
            packet[k + 2] = data[k]
            chksum += data[k]

        packet[8] = ETX
        #buf.append(chksum & 0xFF)  # Ensure checksum is within byte range
        packet[9] = chksum & 0xFF

        # Send to serial port
        self.ser.write(packet)

        
    def _move(self,Galvo1,Galvo2):
        
        # Example data initialization
        #Galvo1 = 1750  # Example value, set as needed
        #Galvo2 = 1700  # Example value, set as needed

        data = [
            Galvo1 & 0xff,  # Lower 8 bits
            Galvo1 >> 8,    # Upper 8 bits
            Galvo2 & 0xff,  # Lower 8 bits
            Galvo2 >> 8,    # Upper 8 bits
            0,              # Empty byte
            0               # Empty byte
        ]

        self._sendcmd(self.command, data)
        
    def stop(self):
        self.serial_close()
        
        
def main():

    # port = '/dev/ttyUSB0'  # For Linux
    galvo = GalvoInterface()

    print(galvo.get_position())
    
    galvo.move_2_pos(2000,1800)

    print(galvo.get_position())

    galvo.stop()

if __name__ == "__main__":
    main()