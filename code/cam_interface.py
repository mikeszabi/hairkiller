# -*- coding: utf-8 -*-
"""
Created on Sat Dec 12 21:47:11 2020

@author: szabo
"""
import sys
import cv2
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# from PIL import Image, ImageTk
# from hair_detection import ObjectDetector

#LattePandas camera_resolution=2592×1944

# def draw_cross(img,center, color, d):
#     cv2.line(img,
#(center[0] - d), (center[1] + d)),
#              (int(center[0] - d), int(center[1] - d)), (int(center[0] + d), int(center[1] + d)),
#              color, 1, cv2.LINE_AA, 0)
#     cv2.line(img,
#              (int(center[0] + d), int(center[1] - d)), (int(center[0] - d), int(center[1] + d)),
#              color, 1, cv2.LINE_AA, 0) 

# def procImage(im):
#     edge=cv2.Canny(im.copy(),50,200)
#     return edge

def list_ports():
    """
    Test the ports and returns a tuple with the available ports and the ones that are working.
    """
    non_working_ports = []
    dev_port = 0
    working_ports = []
    available_ports = []
    while len(non_working_ports) < 6: # if there are more than 5 non working ports stop the testing. 
        camera = cv2.VideoCapture(dev_port) #,cv2.CAP_DSHOW)
        if not camera.isOpened():
            non_working_ports.append(dev_port)
            logging.warning("Port %s is not working.", dev_port)
        else:
            # camera.set(cv2.CAP_PROP_FRAME_WIDTH, 2592)
            # camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1944)
            is_reading, img = camera.read()
            w = camera.get(3)
            h = camera.get(4)
            if is_reading:
                logging.info("Port %s is working and reads images (%s x %s)", dev_port, h, w)
                working_ports.append(dev_port)
            else:
                logging.info("Port %s for camera (%s x %s) is present but does not read.", dev_port, h, w)
                available_ports.append(dev_port)
            camera.release()
        dev_port +=1
    return available_ports,working_ports,non_working_ports


class UVCInterface:
    def __init__(self, camera_index=0):

        _,working_ports,_ = list_ports()
        if len(working_ports)<2:
            logging.error("No working camera ports found.")
            raise ValueError("No working camera ports found.")
        self.camera_index = working_ports[1] # assuming the first working port is the built-in camera
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            logging.error("Failed to open camera at index %s", self.camera_index)
            raise ValueError(f"Failed to open camera at index {self.camera_index}")
        logging.info("Camera at index %s opened successfully", self.camera_index)

    def set_resolution(self, width, height):
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        logging.info("Resolution set to %sx%s", width, height)

    def read_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            logging.error("Failed to read frame from camera at index %s", self.camera_index)
            return None
        logging.info("Frame read successfully from camera at index %s", self.camera_index)
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) # Convert to RGB
        return frame

    def release(self):
        self.cap.release()
        logging.info("Camera at index %s released", self.camera_index)

# Example usage
if __name__ == "__main__":
    try:
        uvc = UVCInterface(camera_index=0)
        uvc.set_resolution(640, 480)
        frame = uvc.read_frame()
        if frame is not None:
            cv2.imshow("Frame", frame)
            cv2.waitKey(0)
        uvc.release()
    except ValueError as e:
        logging.error("An error occurred: %s", e)