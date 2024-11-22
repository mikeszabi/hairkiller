# -*- coding: utf-8 -*-
"""
Created on Sat Dec 12 21:47:11 2020

@author: szabo
"""
import sys
import cv2
import logging
import threading

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# def list_ports():
#     """
#     Test the ports and returns a tuple with the available ports and the ones that are working.
#     """
#     non_working_ports = []
#     dev_port = 0
#     working_ports = []
#     available_ports = []
#     while len(non_working_ports) < 6: # if there are more than 5 non working ports stop the testing. 
#         camera = cv2.VideoCapture(dev_port) #,cv2.CAP_DSHOW)
#         if not camera.isOpened():
#             non_working_ports.append(dev_port)
#             logging.warning("Port %s is not working.", dev_port)
#         else:
#             # camera.set(cv2.CAP_PROP_FRAME_WIDTH, 2592)
#             # camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 1944)
#             is_reading, img = camera.read()
#             w = camera.get(3)
#             h = camera.get(4)
#             if is_reading:
#                 logging.info("Port %s is working and reads images (%s x %s)", dev_port, h, w)
#                 working_ports.append(dev_port)
#             else:
#                 logging.info("Port %s for camera (%s x %s) is present but does not read.", dev_port, h, w)
#                 available_ports.append(dev_port)
#             camera.release()
#         dev_port +=1
#     return available_ports,working_ports,non_working_ports

def list_camera_details(max_index=6):
    cameras = []
    for index in range(max_index):
        try:
            cap = cv2.VideoCapture(index)
            if cap.isOpened():
                # Get some properties (e.g., frame width, height) for identification
                width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                fps = cap.get(cv2.CAP_PROP_FPS)
                cameras.append((index, width, height, fps))
                cap.release()
        except Exception as e:
            print(f"Error: Could not open camera index {index}.")
    return cameras


class UVCInterface:
    def __init__(self, camera_index=1):

        # List available cameras with details
        camera_details = list_camera_details()
        if camera_details:
            for cam in camera_details:
                print(f"Camera Index: {cam[0]}, Resolution: {cam[1]}x{cam[2]}, FPS: {cam[3]}")
        else:
            print("No cameras detected.")

        # Open a connection to the UVC camera (usually camera index 0 for the first USB camera)

        selected_camera_index = None
        for cam in camera_details:
            if cam[1] == 1280:
                selected_camera_index = cam[0]
                logging.info("Camera with resolution 1280x720 found at index %s", selected_camera_index)
                break

        if selected_camera_index is None:
            logging.error("No working camera ports found.")
            raise ValueError("No working camera ports found.")
        self.camera_index = selected_camera_index # assuming the first working port is the built-in camera
        self.cap = cv2.VideoCapture(self.camera_index)
        if not self.cap.isOpened():
            logging.error("Failed to open camera at index %s", self.camera_index)
            raise ValueError(f"Failed to open camera at index {self.camera_index}")
        logging.info("Camera at index %s opened successfully", self.camera_index)

        self.ret = False
        self.frame = None
        self.frame_index=0
        self.stopped = False
        self.lock = threading.Lock()

        # Start the frame capture thread
        self.thread = threading.Thread(target=self.update, args=())
        self.thread.daemon = True
        self.thread.start()

    def update(self):
        while True:
            if self.stopped:
                return

            ret, frame = self.cap.read()
            if ret:
                self.frame_index+=1
            with self.lock:
                self.ret = ret
                self.frame = frame

    def set_resolution(self, width, height):
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        logging.info("Resolution set to %sx%s", width, height)

    def read_frame(self):
        with self.lock:
            frame = self.frame.copy() if self.frame is not None else None
            if frame is None:
                logging.error("Failed to read frame from camera at index %s", self.camera_index)
                return None, None
            else:
                logging.info("Frame read successfully from camera at index %s", self.camera_index)
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) # Convert to RGB
                return frame, self.frame_index

    def release(self):
        self.stopped = True
        self.thread.join()
        self.cap.release()
        logging.info("Camera at index %s released", self.camera_index)

# Example usage
if __name__ == "__main__":
    uvc = UVCInterface(camera_index=0)
    while True:
        frame, frame_index = uvc.read_frame()
        if frame is None:
            print("Failed to capture frame")
            continue

        # Process the frame (e.g., display it)
        cv2.imshow("Frame", frame)
        cv2.putText(frame, f"Frame index: {frame_index}", (30, 30), cv2.FONT_HERSHEY_SIMPLEX, 5, (255, 255, 255), 10)
        logging.info("Frame index: %s", frame_index)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    uvc.release()
