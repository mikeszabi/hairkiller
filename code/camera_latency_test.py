#!/usr/bin/env python3
"""
Camera latency diagnostic script.
Measures where delay comes from: V4L2 kernel buffer, MJPEG decode, or camera hardware.

Usage:
  python code/camera_latency_test.py

Tests performed:
  1. Raw grab() speed — how fast can we pull frames without decoding?
  2. Full read() speed — grab + decode timing
  3. Buffer depth probe — how many frames are queued in the kernel buffer?
  4. Visual latency test — shows a live counter on screen; point camera at a clock/phone timer
"""

import time
import cv2
import sys

DEV = "/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._Arducam_16MP_SN0001-video-index0"
W, H, FPS = 2592, 1944, 10
FOURCC = "MJPG"


def open_camera():
    cap = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("ERROR: Cannot open camera")
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*FOURCC))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = cap.get(cv2.CAP_PROP_FPS)
    bufsz = cap.get(cv2.CAP_PROP_BUFFERSIZE)
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    f = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])
    print(f"Camera opened: {w:.0f}x{h:.0f} @ {fps:.0f} FPS, fourcc={f}, buffersize={bufsz}")
    return cap


def test_buffer_depth(cap):
    """Probe how many frames are sitting in the V4L2 kernel buffer.
    We call grab() in a tight loop and measure how many return instantly (<5ms).
    Those are pre-buffered frames; the first slow one is real-time."""
    print("\n=== TEST 1: Buffer Depth Probe ===")
    # warm up
    for _ in range(5):
        cap.read()
    time.sleep(0.5)  # let frames accumulate

    times = []
    for i in range(20):
        t0 = time.perf_counter()
        ok = cap.grab()
        dt = (time.perf_counter() - t0) * 1000
        times.append(dt)
        if not ok:
            print(f"  grab #{i}: FAILED")
            break
        print(f"  grab #{i:2d}: {dt:7.2f} ms {'<-- BUFFERED' if dt < 10 else '<-- REAL-TIME (blocked)'}")

    fast = sum(1 for t in times if t < 10)
    print(f"\nResult: {fast} frames were pre-buffered in V4L2 kernel queue")
    print(f"  At {FPS} FPS, that's ~{fast/FPS*1000:.0f} ms of latency from kernel buffering alone")
    return fast


def test_grab_vs_retrieve(cap):
    """Measure grab() time (kernel transfer) vs retrieve() time (MJPEG decode) separately."""
    print("\n=== TEST 2: grab() vs retrieve() Timing ===")
    # drain first
    for _ in range(10):
        cap.grab()

    grab_times = []
    retrieve_times = []
    for i in range(10):
        t0 = time.perf_counter()
        ok = cap.grab()
        t1 = time.perf_counter()
        if not ok:
            continue
        ret, frame = cap.retrieve()
        t2 = time.perf_counter()

        g = (t1 - t0) * 1000
        r = (t2 - t1) * 1000
        grab_times.append(g)
        retrieve_times.append(r)
        print(f"  Frame {i:2d}: grab={g:7.2f} ms, retrieve(decode)={r:7.2f} ms, total={g+r:7.2f} ms")

    if grab_times:
        print(f"\n  Avg grab:     {sum(grab_times)/len(grab_times):7.2f} ms")
        print(f"  Avg retrieve: {sum(retrieve_times)/len(retrieve_times):7.2f} ms")
        print(f"  Avg total:    {(sum(grab_times)+sum(retrieve_times))/len(grab_times):7.2f} ms")


def test_full_read_fps(cap):
    """Measure sustained cap.read() throughput."""
    print("\n=== TEST 3: Sustained read() FPS ===")
    # drain
    for _ in range(10):
        cap.grab()

    N = 30
    t0 = time.perf_counter()
    for _ in range(N):
        ret, frame = cap.read()
    elapsed = time.perf_counter() - t0
    print(f"  {N} frames in {elapsed:.2f}s = {N/elapsed:.1f} FPS")
    print(f"  Per frame: {elapsed/N*1000:.1f} ms")


def test_visual_latency(cap):
    """Display live feed with a millisecond counter overlay.
    Point the camera at this screen to visually measure end-to-end latency."""
    print("\n=== TEST 4: Visual Latency (interactive) ===")
    print("  A window will open showing the camera feed with a timestamp overlay.")
    print("  Point the camera at a clock or phone timer to see the delay.")
    print("  Press 'q' to quit.\n")

    cv2.namedWindow("Latency Test", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Latency Test", 960, 720)

    # drain buffer
    for _ in range(10):
        cap.grab()

    while True:
        # grab+retrieve pattern — only decode latest
        t_before = time.perf_counter()
        ret, frame = cap.read()
        t_after = time.perf_counter()
        if not ret:
            continue

        read_ms = (t_after - t_before) * 1000
        now_ms = int(time.time() * 1000)

        # overlay current system time in large text
        text = f"SYS: {time.strftime('%H:%M:%S')}.{now_ms % 1000:03d}"
        cv2.putText(frame, text, (50, 120), cv2.FONT_HERSHEY_SIMPLEX, 3.0, (0, 255, 0), 6)
        cv2.putText(frame, f"read(): {read_ms:.0f}ms", (50, 220), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 255, 255), 4)

        cv2.imshow("Latency Test", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    cap = open_camera()

    test_buffer_depth(cap)
    test_grab_vs_retrieve(cap)
    test_full_read_fps(cap)

    if "--visual" in sys.argv:
        test_visual_latency(cap)
    else:
        print("\nTip: Run with --visual to do an interactive visual latency test")

    cap.release()
    print("\nDone.")
