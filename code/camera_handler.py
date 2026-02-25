# -*- coding: utf-8 -*-
"""
Provides a small wrapper for UVC cameras using OpenCV.
"""

import os
import logging
import cv2

# configure logging and silence OpenCV noise
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"


def find_cameras(max_index=2):
    """Return a list of camera device indices that can be opened."""
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
        if cap.isOpened():
            found.append(i)
            cap.release()
    return found


class UVCInterface:
    """Basic interface for a USB/UVC camera.

    The constructor will automatically search for cameras if no index
    is provided and configure the device with sensible defaults.
    """

    def __init__(
        self,
        index: int | None = None,
        max_search: int = 2,
        width: int = 2692,
        height: int = 1944,
        crop_x: int = 336,
        crop_y: int = 12,
        crop_w: int = 1920,
        crop_h: int = 1920,
        fps: int = 10,
        fourcc: str = "MJPG",
    ) -> None:
        # store user-provided/default parameters
        self.max_search = max_search
        self.width = width
        self.height = height
        self.fps = fps
        self.fourcc = fourcc

        self.crop_x = crop_x
        self.crop_y = crop_y
        self.crop_w = crop_w
        self.crop_h = crop_h

        # pick a camera index if one wasn't specified
        if index is None:
            cameras = find_cameras(self.max_search)
            logging.info("Found camera indexes: %s", cameras)
            if not cameras:
                raise ValueError("No cameras detected.")
            index = cameras[0]
            logging.info("Using camera index %s", index)

        self.camera_index = index

        self.camera_index = index
        self.cap = cv2.VideoCapture(self.camera_index, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise ValueError(f"Could not open camera {self.camera_index}")

        # apply requested settings
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)

        self.frame_index = 0

    def read(self) -> tuple | None:
        """Grab a frame from the camera.  Returns (frame, index) or (None, None)."""
        ret, frame = self.cap.read()
        if not ret:
            return None, None
        self.frame_index += 1
        cropped = self.crop_frame(frame, self.crop_x, self.crop_y, self.crop_w, self.crop_h)
        return cropped, self.frame_index

    def crop_frame(self, frame, x, y, w, h):
        """Crop a frame to the specified rectangle."""
        return frame[y : y + h, x : x + w]

    def release(self) -> None:
        """Release the underlying VideoCapture."""
        self.cap.release()

    # context manager support
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


# simple command‑line demonstration (mirrors camera_test behaviour)
if __name__ == "__main__":
    cams = find_cameras(2)
    print("Found camera indexes:", cams)
    if not cams:
        raise SystemExit("No cameras detected.")

    with UVCInterface() as uvc:
        # show a small window to verify
        cv2.namedWindow("UVC Camera Stream", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("UVC Camera Stream", 1280, 720)

        while True:
            frame, idx = uvc.read()
            if frame is None:
                print("Error reading frame")
                break
            cv2.imshow("UVC Camera Stream", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    cv2.destroyAllWindows()

