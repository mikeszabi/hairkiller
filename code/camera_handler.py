# -*- coding: utf-8 -*-
"""
Provides a small wrapper for UVC cameras using OpenCV.
"""

import os
import logging
import threading
import time
import cv2

# configure logging and silence OpenCV noise
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
os.environ["OPENCV_LOG_LEVEL"] = "SILENT"

DEV = "/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._Arducam_16MP_SN0001-video-index0"

W, H, FPS = 2592, 1944, 5
FOURCC = "MJPG"

# Exposure time in 100µs units (V4L2 exposure_time_absolute).
# 100 = 10ms (bright light)  |  333 = 33ms (1/30s, normal indoor)
# 500 = 50ms (dim indoor)    |  1000 = 100ms (max at 10 FPS)
# Increase if the image is too dark, decrease if too bright.
EXPOSURE = 100
WHITE_BALANCE = 3000

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

def open_cam(
    dev: str = DEV,
    width: int = W,
    height: int = H,
    fps: int = FPS,
    fourcc: str = FOURCC,
    auto_exposure: bool = False,
    exposure: int | None = EXPOSURE,
    auto_wb: bool = False,
    white_balance: int | None = WHITE_BALANCE,
):
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)

    # gyakran segít, hogy ne álljon bent sok régi frame:
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
    cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3 if auto_exposure else 1)
    if exposure is not None:
        cap.set(cv2.CAP_PROP_EXPOSURE, exposure)

    if hasattr(cv2, "CAP_PROP_AUTO_WB"):
        cap.set(cv2.CAP_PROP_AUTO_WB, 1 if auto_wb else 0)
    if white_balance is not None and hasattr(cv2, "CAP_PROP_WB_TEMPERATURE"):
        cap.set(cv2.CAP_PROP_WB_TEMPERATURE, white_balance)

    # Disable auto-exposure so the camera cannot pick exposure times > 1/FPS.
    # With auto on, the driver silently stops streaming in dim light because
    # the sensor integration time exceeds the requested frame interval.
    #cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)   # 1 = manual (UVC standard)
    #cap.set(cv2.CAP_PROP_EXPOSURE, EXPOSURE) # tune via EXPOSURE constant above

    for _ in range(WARMUP):
        cap.read()

    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = cap.get(cv2.CAP_PROP_FPS)
    ae  = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
    exp = cap.get(cv2.CAP_PROP_EXPOSURE)
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    f = "".join([chr((fourcc >> 8*i) & 0xFF) for i in range(4)])
    auto_wb_now = cap.get(cv2.CAP_PROP_AUTO_WB) if hasattr(cv2, "CAP_PROP_AUTO_WB") else None
    wb_now = cap.get(cv2.CAP_PROP_WB_TEMPERATURE) if hasattr(cv2, "CAP_PROP_WB_TEMPERATURE") else None
    print(
        "Opened negotiated: "
        f"{w}x{h}@{fps} fourcc={f} auto_exposure={ae} exposure={exp} "
        f"auto_wb={auto_wb_now} white_balance={wb_now}",
        flush=True,
    )
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
        width: int = W,
        height: int = H,
        fps: int = FPS,
        fourcc: str = FOURCC,
        auto_exposure: bool = False,
        exposure: int | None = EXPOSURE,
        auto_wb: bool = False,
        white_balance: int | None = WHITE_BALANCE,
    ) -> None:
        # store user-provided/default parameters

        self.crop_x = crop_x
        self.crop_y = crop_y
        self.crop_w = crop_w
        self.crop_h = crop_h
        self.width = width
        self.height = height
        self.fps = fps
        self.fourcc = fourcc
        self.auto_exposure = auto_exposure
        self.exposure = exposure
        self.auto_wb = auto_wb
        self.white_balance = white_balance

        self.cap = None
        self.frame_index = 0
        self._raw_frame = None    # full decoded frame, no crop yet
        self._lock = threading.Lock()
        self._cap_lock = threading.Lock()
        self._running = True
        self._last_frame_ts = None
        self._frame_intervals_ms = []
        self._read_fail_count = 0
        self._open_camera_or_raise()
        self._thread = threading.Thread(target=self._grab_loop, daemon=True)
        self._thread.start()

    def _open_camera_or_raise(self) -> None:
        cap = open_cam(
            dev=DEV,
            width=self.width,
            height=self.height,
            fps=self.fps,
            fourcc=self.fourcc,
            auto_exposure=self.auto_exposure,
            exposure=self.exposure,
            auto_wb=self.auto_wb,
            white_balance=self.white_balance,
        )
        if cap is None:
            raise ValueError(f"Could not open camera {DEV}")
        self.cap = cap

    def _grab_loop(self) -> None:
        """Background thread: grab + decode as fast as possible, store raw frame.

        Cropping is NOT done here so this thread restarts the next grab()
        immediately after retrieve(), minimising the gap between frames.
        """
        while self._running:
            with self._cap_lock:
                cap = self.cap
                ret, frame = cap.read() if cap is not None else (False, None)
            if not ret:
                self._read_fail_count += 1
                continue
            now = time.perf_counter()
            with self._lock:
                self.frame_index += 1
                if self._last_frame_ts is not None:
                    interval_ms = (now - self._last_frame_ts) * 1000.0
                    self._frame_intervals_ms.append(interval_ms)
                    if len(self._frame_intervals_ms) > 120:
                        self._frame_intervals_ms.pop(0)
                self._last_frame_ts = now
                self._raw_frame = (frame, self.frame_index, now)

    def read(self) -> tuple:
        """Return the latest frame, cropped on demand.  Returns (frame, index) or (None, None)."""
        with self._lock:
            if self._raw_frame is None:
                return None, None
            frame, idx, _ = self._raw_frame
        cropped = self.crop_frame(frame, self.crop_x, self.crop_y, self.crop_w, self.crop_h)
        return cropped, idx

    def read_with_meta(self):
        with self._lock:
            if self._raw_frame is None:
                return None, None, None
            frame, idx, ts = self._raw_frame
        cropped = self.crop_frame(frame, self.crop_x, self.crop_y, self.crop_w, self.crop_h)
        return cropped, idx, ts

    def crop_frame(self, frame, x, y, w, h):
        """Crop a frame to the specified rectangle."""
        return frame[y : y + h, x : x + w]

    def get_settings(self) -> dict:
        with self._cap_lock:
            if self.cap is None:
                return {}
            cap = self.cap
            fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
            fourcc_str = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])
            settings = {
                "width": int(round(cap.get(cv2.CAP_PROP_FRAME_WIDTH))),
                "height": int(round(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))),
                "fps": cap.get(cv2.CAP_PROP_FPS),
                "fourcc": fourcc_str,
                "auto_exposure": cap.get(cv2.CAP_PROP_AUTO_EXPOSURE),
                "exposure": cap.get(cv2.CAP_PROP_EXPOSURE),
                "buffer_size": cap.get(cv2.CAP_PROP_BUFFERSIZE),
            }
            if hasattr(cv2, "CAP_PROP_AUTO_WB"):
                settings["auto_wb"] = cap.get(cv2.CAP_PROP_AUTO_WB)
            if hasattr(cv2, "CAP_PROP_WB_TEMPERATURE"):
                settings["white_balance"] = cap.get(cv2.CAP_PROP_WB_TEMPERATURE)
            return settings

    def get_stats(self) -> dict:
        with self._lock:
            intervals = list(self._frame_intervals_ms)
            frame_index = self.frame_index
            last_frame_ts = self._last_frame_ts
        now = time.perf_counter()
        frame_age_ms = None if last_frame_ts is None else (now - last_frame_ts) * 1000.0
        avg_interval = sum(intervals) / len(intervals) if intervals else None
        return {
            "frame_index": frame_index,
            "read_fail_count": self._read_fail_count,
            "frame_age_ms": frame_age_ms,
            "interval_min_ms": min(intervals) if intervals else None,
            "interval_avg_ms": avg_interval,
            "interval_max_ms": max(intervals) if intervals else None,
            "measured_fps": (1000.0 / avg_interval) if avg_interval and avg_interval > 0 else None,
        }

    def apply_settings(
        self,
        *,
        auto_exposure: bool | None = None,
        exposure: int | None = None,
        auto_wb: bool | None = None,
        white_balance: int | None = None,
        fps: float | None = None,
    ) -> dict:
        reopen_required = False

        if auto_exposure is not None:
            self.auto_exposure = bool(auto_exposure)
        if exposure is not None:
            self.exposure = int(exposure)
        if auto_wb is not None:
            self.auto_wb = bool(auto_wb)
        if white_balance is not None:
            self.white_balance = int(white_balance)
        if fps is not None:
            new_fps = int(round(fps))
            if new_fps != self.fps:
                self.fps = new_fps
                reopen_required = True

        with self._cap_lock:
            if self.cap is None:
                raise ValueError("Camera is not open")

            if reopen_required:
                old_cap = self.cap
                old_cap.release()
                self.cap = None
                time.sleep(0.2)
                new_cap = open_cam(
                    dev=DEV,
                    width=self.width,
                    height=self.height,
                    fps=self.fps,
                    fourcc=self.fourcc,
                    auto_exposure=self.auto_exposure,
                    exposure=self.exposure,
                    auto_wb=self.auto_wb,
                    white_balance=self.white_balance,
                )
                if new_cap is None:
                    self.cap = old_cap
                    raise ValueError(f"Could not reopen camera {DEV} with fps={self.fps}")
                self.cap = new_cap
                with self._lock:
                    self._raw_frame = None
                    self._last_frame_ts = None
                    self._frame_intervals_ms.clear()
                    self._read_fail_count = 0
            else:
                self.cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 3 if self.auto_exposure else 1)
                if self.exposure is not None:
                    self.cap.set(cv2.CAP_PROP_EXPOSURE, self.exposure)
                if hasattr(cv2, "CAP_PROP_AUTO_WB"):
                    self.cap.set(cv2.CAP_PROP_AUTO_WB, 1 if self.auto_wb else 0)
                if self.white_balance is not None and hasattr(cv2, "CAP_PROP_WB_TEMPERATURE"):
                    self.cap.set(cv2.CAP_PROP_WB_TEMPERATURE, self.white_balance)

        return self.get_settings()

    def release(self) -> None:
        """Stop the grabber thread and release the underlying VideoCapture."""
        self._running = False
        self._thread.join(timeout=2)
        with self._cap_lock:
            if self.cap is not None:
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
