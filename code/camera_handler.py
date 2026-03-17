# -*- coding: utf-8 -*-
"""
Provides a small wrapper for UVC cameras using OpenCV.
"""

import os
import logging
import threading
import cv2

# configure logging and silence OpenCV noise
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"

DEV = "/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._Arducam_16MP_SN0001-video-index0"

W, H, FPS = 2592, 1944, 10
FOURCC = "MJPG"

# Exposure time in 100µs units (V4L2 exposure_time_absolute).
# 100 = 10ms (bright light)  |  333 = 33ms (1/30s, normal indoor)
# 500 = 50ms (dim indoor)    |  1000 = 100ms (max at 10 FPS)
# Increase if the image is too dark, decrease if too bright.
EXPOSURE = 1000

MAX_FAILS = 10          # ennyi egymás utáni read fail után restart
BACKOFF = 1.0           # restart előtt várakozás
WARMUP = 10

# def find_cameras(max_index=2):
#     """Return a list of camera device indices that can be opened."""
#     found = []
#     for i in range(max_index):
#         cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
#         if cap.isOpened():
#             found.append(i)
#             cap.release()
#     return found

def open_cam():
    cap = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*FOURCC))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    # gyakran segít, hogy ne álljon bent sok régi frame:
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    # Disable auto-exposure so the camera cannot pick exposure times > 1/FPS.
    # With auto on, the driver silently stops streaming in dim light because
    # the sensor integration time exceeds the requested frame interval.
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)   # 1 = manual (UVC standard)
    cap.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE) # tune via EXPOSURE constant above

    for _ in range(WARMUP):
        cap.read()

    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = cap.get(cv2.CAP_PROP_FPS)
    ae  = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
    exp = cap.get(cv2.CAP_PROP_EXPOSURE)
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    f = "".join([chr((fourcc >> 8*i) & 0xFF) for i in range(4)])
    print(f"Opened negotiated: {w}x{h}@{fps} fourcc={f} auto_exposure={ae} exposure={exp}", flush=True)
    return cap

class UVCInterface:
    """Basic interface for a USB/UVC camera.

    The constructor will automatically search for cameras if no index
    is provided and configure the device with sensible defaults.

    A background thread continuously grabs and decodes frames so the
    consumer always gets the most recent image without blocking on I/O.
    Cropping is deferred to read() so the grab thread restarts immediately.
    """

    def __init__(
        self,
        crop_x: int = 336,
        crop_y: int = 12,
        crop_w: int = 1920,
        crop_h: int = 1920,
    ) -> None:
        # store user-provided/default parameters

        self.crop_x = crop_x
        self.crop_y = crop_y
        self.crop_w = crop_w
        self.crop_h = crop_h

        self.cap = None
        self.cap = open_cam()
        if self.cap is None:
            raise ValueError(f"Could not open camera {DEV}")

        self.frame_index = 0
        self._raw_frame = None    # full decoded frame, no crop yet
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._grab_loop, daemon=True)
        self._thread.start()

    def _grab_loop(self) -> None:
        """Background thread: grab + decode as fast as possible, store raw frame.

        Cropping is NOT done here so this thread restarts the next grab()
        immediately after retrieve(), minimising the gap between frames.
        """
        while self._running:
            ret, frame = self.cap.read()
            if not ret:
                continue
            with self._lock:
                self.frame_index += 1
                self._raw_frame = (frame, self.frame_index)

    def read(self) -> tuple:
        """Return the latest frame, cropped on demand.  Returns (frame, index) or (None, None)."""
        with self._lock:
            if self._raw_frame is None:
                return None, None
            frame, idx = self._raw_frame
        cropped = self.crop_frame(frame, self.crop_x, self.crop_y, self.crop_w, self.crop_h)
        return cropped, idx

    def crop_frame(self, frame, x, y, w, h):
        """Crop a frame to the specified rectangle."""
        return frame[y : y + h, x : x + w]

    def release(self) -> None:
        """Stop the grabber thread and release the underlying VideoCapture."""
        self._running = False
        self._thread.join(timeout=2)
        self.cap.release()

    # context manager support
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


# simple command‑line demonstration (mirrors camera_test behaviour)
if __name__ == "__main__":

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

