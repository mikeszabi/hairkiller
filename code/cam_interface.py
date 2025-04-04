# -*- coding: utf-8 -*-
"""
Created on Sat Dec 12 21:47:11 2020

@author: szabo
"""
import sys
import time
import cv2
import logging
#import threading

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# # GStreamer pipeline USB kamerához
# def gstreamer_pipeline_usb_cam(
#     device="/dev/video0",
#     width=640,
#     height=480,
#     framerate=25
# ):
#     return (
#         f"v4l2src device={device} ! "
#         f"video/x-raw, width={width}, height={height}, framerate={framerate}/1 ! "
#         "videoconvert ! "
#         "video/x-raw, format=(string)BGR ! appsink"
#     )

# def test_gstreamer():
#     # Initializing camera with gstreamer pipeline
#     cap = cv2.VideoCapture(gstreamer_pipeline_usb_cam(), cv2.CAP_GSTREAMER)

#     if not cap.isOpened():
#         print("Could not open camera!")
#     else:
#         ret, frame = cap.read()
#         cv2.imwrite("test.jpg", frame)  # Ellenőrzés: mentés képként
#         cap.release()

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
                logging.info("Camera index %s: Resolution: %sx%s, FPS: %s", index, width, height, fps)
        except Exception as e:
            #logging.error("Error: Could not open camera index %s.", index)
            continue
    return cameras

class UVCInterface:
    def __init__(self, camera_index=1):

        # List available cameras with details
        camera_details = list_camera_details()
        if camera_details:
            for cam in camera_details:
                logging.info("Camera Index: %s, Resolution: %sx%s, FPS: %s", cam[0], cam[1], cam[2], cam[3])
        else:
            logging.error("No cameras detected.")

        # Open a connection to the UVC camera (usually camera index 0 for the first USB camera)

        selected_camera_index = None
        for cam in camera_details:
            if cam[1] == 640: # Assuming 1280x720 resolution
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

    def set_fps(self, fps):
        self.cap.set(cv2.CAP_PROP_FPS, fps)

    def set_resolution(self, width, height):
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        logging.info("Resolution set to %sx%s", width, height)

    def read_frame(self):
        ret, frame = self.cap.read()
        if ret:
            self.frame_index+=1
            #frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) # Convert to RGB
            return frame, self.frame_index
        else:
            logging.error("Failed to read frame from camera at index %s", self.camera_index)
            return None, None

    def release(self):
        self.cap.release()
        logging.info("Camera at index %s released", self.camera_index)


# class UVCInterface_multithread:
#     def __init__(self, camera_index=1):

#         # List available cameras with details
#         camera_details = list_camera_details()
#         if camera_details:
#             for cam in camera_details:
#                 logging.info("Camera Index: %s, Resolution: %sx%s, FPS: %s", cam[0], cam[1], cam[2], cam[3])
#         else:
#             logging.error("No cameras detected.")

#         # Open a connection to the UVC camera (usually camera index 0 for the first USB camera)

#         selected_camera_index = None
#         for cam in camera_details:
#             if cam[1] == 1280: # Assuming 1280x720 resolution
#                 selected_camera_index = cam[0]
#                 logging.info("Camera with resolution 1280x720 found at index %s", selected_camera_index)
#                 break

#         if selected_camera_index is None:
#             logging.error("No working camera ports found.")
#             raise ValueError("No working camera ports found.")
#         self.camera_index = selected_camera_index # assuming the first working port is the built-in camera
#         self.cap = cv2.VideoCapture(self.camera_index)
#         if not self.cap.isOpened():
#             logging.error("Failed to open camera at index %s", self.camera_index)
#             raise ValueError(f"Failed to open camera at index {self.camera_index}")
#         logging.info("Camera at index %s opened successfully", self.camera_index)

#         self.ret = False
#         self.frame = None
#         self.frame_index=0
#         self.stopped = False
#         self.lock = threading.Lock()

#         # Start the frame capture thread
#         self.thread = threading.Thread(target=self.update, args=())
#         self.thread.daemon = True
#         self.thread.start()

#     def update(self):
#         while True:
#             if self.stopped:
#                 return

#             ret, frame = self.cap.read()
#             if ret:
#                 self.frame_index+=1
#                 with self.lock:
#                     self.ret = ret
#                     self.frame = frame

#             time.sleep(0.01)

#     def set_resolution(self, width, height):
#         self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
#         self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
#         logging.info("Resolution set to %sx%s", width, height)

#     def read_frame(self):
#         with self.lock:
#             frame = self.frame.copy() if self.frame is not None else None
#             if frame is None:
#                 logging.error("Failed to read frame from camera at index %s", self.camera_index)
#                 return None, None
#             else:
#                 #logging.info("Frame read successfully from camera at index %s", self.camera_index)
#                 frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) # Convert to RGB
#                 return frame, self.frame_index

#     def release(self):
#         self.stopped = True
#         self.thread.join()
#         self.cap.release()
#         logging.info("Camera at index %s released", self.camera_index)

# Example usage
if __name__ == "__main__":
    list_camera_details()
    #test_gstreamer()
    uvc = UVCInterface()
    #uvc.set_resolution(2560, 1920)
    uvc.set_resolution(1920, 1080)
    uvc.set_fps(10)
    while True:
        frame, frame_index = uvc.read_frame()
        if frame is None:
            print("Failed to capture frame")
            break

        # Process the frame (e.g., display it)
        cv2.imshow("Frame", frame)
        cv2.putText(frame, f"Frame index: {frame_index}", (30, 30), cv2.FONT_HERSHEY_SIMPLEX, 5, (255, 255, 255), 10)
        logging.info("Frame index: %s - Resolution: %sx%s - fps: %s" , frame_index,uvc.cap.get(cv2.CAP_PROP_FRAME_WIDTH), uvc.cap.get(cv2.CAP_PROP_FRAME_HEIGHT), uvc.cap.get(cv2.CAP_PROP_FPS))
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    uvc.release()


# v4l2-ctl --list-devices
# v4l2-ctl --list-formats-ext
# v4l2-ctl --all -d /dev/video0