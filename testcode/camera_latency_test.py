#!/usr/bin/env python3
"""
Camera latency diagnostic script.
Covers every stage of the pipeline:
  1. V4L2 controls audit     — detect auto-exposure, exposure time, gain
  2. USB bandwidth estimate  — compare expected vs measured throughput
  3. Buffer depth probe      — frames queued in V4L2 kernel buffer
  4. grab() vs retrieve()    — USB transfer vs MJPEG decode timing
  5. Auto-exposure impact    — compare grab timing with AE on vs off
  6. Crop + JPEG encode      — streaming endpoint simulation
  7. Streaming pipeline sim  — total end-to-end budget per frame
  8. Visual latency test     — interactive, point camera at a clock

Usage:
  python code/camera_latency_test.py            # tests 1-7
  python code/camera_latency_test.py --visual   # adds interactive test 8
  python code/camera_latency_test.py --ae-test  # auto-exposure on/off comparison
"""

import subprocess
import time
import cv2
import sys
import numpy as np

DEV = "/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._Arducam_16MP_SN0001-video-index0"
CROP_X, CROP_Y, CROP_W, CROP_H = 336, 12, 1920, 1920
W, H, FPS = 2592, 1944, 5
FOURCC = "MJPG"
JPEG_QUALITY = 70


def open_camera(auto_exposure=True, exposure_time=None):
    cap = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
    if not cap.isOpened():
        print("ERROR: Cannot open camera")
        sys.exit(1)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*FOURCC))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    cap.set(cv2.CAP_PROP_FPS, FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    if not auto_exposure:
        # UVC: 1 = Manual, 3 = Aperture Priority (auto). OpenCV maps 0.25 = manual.
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)   # manual mode
        if exposure_time is not None:
            cap.set(cv2.CAP_PROP_EXPOSURE, exposure_time)

    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = cap.get(cv2.CAP_PROP_FPS)
    bufsz = cap.get(cv2.CAP_PROP_BUFFERSIZE)
    ae = cap.get(cv2.CAP_PROP_AUTO_EXPOSURE)
    exp = cap.get(cv2.CAP_PROP_EXPOSURE)
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    f = "".join([chr((fourcc >> 8 * i) & 0xFF) for i in range(4)])
    print(f"  Opened: {w:.0f}x{h:.0f} @ {fps:.0f} FPS, fourcc={f}, bufsize={bufsz}")
    print(f"  auto_exposure={ae}, exposure={exp}")
    # warm up
    for _ in range(5):
        cap.read()
    return cap


def drain(cap, n=10):
    for _ in range(n):
        cap.grab()


# ── TEST 1 ──────────────────────────────────────────────────────────────────

def test_v4l2_controls():
    """Dump all V4L2 camera controls, highlight auto-exposure and exposure time."""
    print("\n=== TEST 1: V4L2 Controls Audit ===")
    try:
        out = subprocess.check_output(
            ["v4l2-ctl", f"--device={DEV}", "--list-ctrls"],
            stderr=subprocess.DEVNULL, text=True
        )
        for line in out.splitlines():
            lo = line.lower()
            if any(k in lo for k in ("exposure", "gain", "white", "backlight", "fps", "bright")):
                flag = "  <-- *** KEY ***" if "exposure" in lo else ""
                print(f"  {line.strip()}{flag}")
    except FileNotFoundError:
        print("  v4l2-ctl not found — install v4l-utils for full control inspection")
    except subprocess.CalledProcessError as e:
        print(f"  v4l2-ctl failed: {e}")


# ── TEST 2 ──────────────────────────────────────────────────────────────────

def test_usb_bandwidth():
    """Estimate USB bandwidth and compare against MJPEG frame size."""
    print("\n=== TEST 2: USB Bandwidth Estimate ===")
    try:
        tree = subprocess.check_output(["lsusb", "-t"], stderr=subprocess.DEVNULL, text=True)
        for line in tree.splitlines():
            if "arducam" in line.lower() or "class=Video" in line:
                print(f"  {line.strip()}")
        # also look for the device in lsusb -v output (speed field)
        ids = subprocess.check_output(["lsusb"], stderr=subprocess.DEVNULL, text=True)
        for line in ids.splitlines():
            if "arducam" in line.lower():
                print(f"  {line.strip()}")
    except Exception:
        pass

    # estimate MJPEG frame size from a real grab
    cap = open_camera()
    drain(cap, 5)
    sizes = []
    for _ in range(5):
        ok = cap.grab()
        if ok:
            ret, frame = cap.retrieve()
            if ret:
                _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                sizes.append(len(jpeg))
    cap.release()

    if sizes:
        avg_kb = sum(sizes) / len(sizes) / 1024
        print(f"\n  Avg MJPEG frame size at Q95: {avg_kb:.0f} KB")
        print(f"  At {FPS} FPS that's ~{avg_kb * FPS / 1024:.1f} MB/s needed")
        print(f"  USB 2.0 limit: ~60 MB/s  |  USB 3.0 limit: ~400 MB/s")
        print(f"  {'OK for USB 2.0' if avg_kb * FPS / 1024 < 40 else 'MAY be tight on USB 2.0 — check cable/port'}")


# ── TEST 3 ──────────────────────────────────────────────────────────────────

def test_buffer_depth(cap):
    """How many frames are queued in the V4L2 kernel buffer."""
    print("\n=== TEST 3: Buffer Depth Probe ===")
    for _ in range(5):
        cap.read()
    time.sleep(0.5)

    times = []
    for i in range(20):
        t0 = time.perf_counter()
        ok = cap.grab()
        dt = (time.perf_counter() - t0) * 1000
        times.append(dt)
        if not ok:
            print(f"  grab #{i}: FAILED")
            break
        label = "<-- BUFFERED" if dt < 10 else "<-- REAL-TIME"
        print(f"  grab #{i:2d}: {dt:7.2f} ms  {label}")

    fast = sum(1 for t in times if t < 10)
    print(f"\n  {fast} frames pre-buffered → ~{fast/FPS*1000:.0f} ms kernel latency")


# ── TEST 4 ──────────────────────────────────────────────────────────────────

def test_grab_vs_retrieve(cap):
    """grab() = USB transfer; retrieve() = MJPEG CPU decode."""
    print("\n=== TEST 4: grab() vs retrieve() Timing ===")
    drain(cap)

    grab_times, retrieve_times = [], []
    for i in range(10):
        t0 = time.perf_counter()
        ok = cap.grab()
        t1 = time.perf_counter()
        if not ok:
            continue
        ret, frame = cap.retrieve()
        t2 = time.perf_counter()
        g, r = (t1 - t0) * 1000, (t2 - t1) * 1000
        grab_times.append(g)
        retrieve_times.append(r)
        print(f"  [{i:2d}] grab={g:7.2f} ms  decode={r:7.2f} ms  total={g+r:7.2f} ms")

    if grab_times:
        print(f"\n  Avg grab (USB wait):   {sum(grab_times)/len(grab_times):7.2f} ms")
        print(f"  Avg retrieve (decode): {sum(retrieve_times)/len(retrieve_times):7.2f} ms")
        total_avg = (sum(grab_times) + sum(retrieve_times)) / len(grab_times)
        print(f"  Avg total:             {total_avg:7.2f} ms  ({1000/total_avg:.1f} FPS throughput)")
        # detect auto-exposure pattern: look for bimodal grab times
        if grab_times:
            mn, mx = min(grab_times), max(grab_times)
            if mx > mn * 1.5:
                print(f"\n  WARNING: grab times vary {mn:.0f}-{mx:.0f} ms (ratio {mx/mn:.1f}x)")
                print("  This bimodal pattern strongly suggests AUTO-EXPOSURE is active.")
                print("  The camera doubles its exposure time under certain lighting → half the FPS.")


# ── TEST 5 ──────────────────────────────────────────────────────────────────

def test_auto_exposure_impact():
    """Compare grab timing with auto-exposure ON vs OFF."""
    print("\n=== TEST 5: Auto-Exposure Impact ===")

    def measure_fps(cap, label, n=20):
        drain(cap, 5)
        times = []
        for _ in range(n):
            t0 = time.perf_counter()
            cap.grab()
            times.append((time.perf_counter() - t0) * 1000)
        avg = sum(times) / len(times)
        mn, mx = min(times), max(times)
        print(f"  [{label}]  avg={avg:.0f} ms  min={mn:.0f} ms  max={mx:.0f} ms  → {1000/avg:.1f} FPS")
        return avg

    print("  Opening with AUTO-EXPOSURE ON ...")
    cap_ae = open_camera(auto_exposure=True)
    avg_ae = measure_fps(cap_ae, "AE=ON ")
    cap_ae.release()

    time.sleep(0.5)

    print("  Opening with AUTO-EXPOSURE OFF (manual, fixed exposure=333 ~1/30s) ...")
    cap_man = open_camera(auto_exposure=False, exposure_time=333)
    avg_man = measure_fps(cap_man, "AE=OFF")
    cap_man.release()

    if avg_man < avg_ae * 0.8:
        print(f"\n  AUTO-EXPOSURE was adding ~{avg_ae - avg_man:.0f} ms per frame!")
        print("  RECOMMENDATION: disable auto-exposure in open_cam().")
    else:
        print("\n  Auto-exposure has minimal impact on this camera.")


# ── TEST 6 ──────────────────────────────────────────────────────────────────

def test_crop_and_encode(cap):
    """Simulate exactly what the streaming endpoint does: crop + JPEG encode."""
    print("\n=== TEST 6: Crop + JPEG Encode Timing (streaming endpoint simulation) ===")
    drain(cap, 5)

    crop_times, enc_q95_times, enc_q70_times = [], [], []
    jpeg_sizes_q95, jpeg_sizes_q70 = [], []

    for i in range(10):
        ok = cap.grab()
        if not ok:
            continue
        ret, frame = cap.retrieve()
        if not ret:
            continue

        t0 = time.perf_counter()
        cropped = frame[CROP_Y:CROP_Y + CROP_H, CROP_X:CROP_X + CROP_W]
        t1 = time.perf_counter()
        _, j95 = cv2.imencode('.jpg', cropped, [cv2.IMWRITE_JPEG_QUALITY, 95])
        t2 = time.perf_counter()
        _, j70 = cv2.imencode('.jpg', cropped, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        t3 = time.perf_counter()

        ct = (t1 - t0) * 1000
        e95 = (t2 - t1) * 1000
        e70 = (t3 - t2) * 1000
        crop_times.append(ct)
        enc_q95_times.append(e95)
        enc_q70_times.append(e70)
        jpeg_sizes_q95.append(len(j95))
        jpeg_sizes_q70.append(len(j70))

    if crop_times:
        print(f"  Crop (numpy slice):    avg {sum(crop_times)/len(crop_times):.2f} ms")
        print(f"  JPEG encode Q=95:      avg {sum(enc_q95_times)/len(enc_q95_times):.1f} ms"
              f"  size {sum(jpeg_sizes_q95)/len(jpeg_sizes_q95)/1024:.0f} KB")
        print(f"  JPEG encode Q={JPEG_QUALITY}:      avg {sum(enc_q70_times)/len(enc_q70_times):.1f} ms"
              f"  size {sum(jpeg_sizes_q70)/len(jpeg_sizes_q70)/1024:.0f} KB")
        q95_kb = sum(jpeg_sizes_q95) / len(jpeg_sizes_q95) / 1024
        q70_kb = sum(jpeg_sizes_q70) / len(jpeg_sizes_q70) / 1024
        print(f"\n  Switching Q95→Q{JPEG_QUALITY} saves {(q95_kb-q70_kb)/q95_kb*100:.0f}% bandwidth"
              f" ({q95_kb-q70_kb:.0f} KB/frame)")


# ── TEST 7 ──────────────────────────────────────────────────────────────────

def test_pipeline_budget(cap):
    """Summarize total end-to-end budget: grab + decode + crop + encode."""
    print("\n=== TEST 7: End-to-End Frame Budget Summary ===")
    drain(cap, 5)

    results = []
    for _ in range(10):
        t0 = time.perf_counter()
        ok = cap.grab()
        t1 = time.perf_counter()
        if not ok:
            continue
        ret, frame = cap.retrieve()
        t2 = time.perf_counter()
        cropped = frame[CROP_Y:CROP_Y + CROP_H, CROP_X:CROP_X + CROP_W]
        t3 = time.perf_counter()
        _, jpeg = cv2.imencode('.jpg', cropped, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
        t4 = time.perf_counter()
        results.append(((t1-t0)*1000, (t2-t1)*1000, (t3-t2)*1000, (t4-t3)*1000))

    if results:
        avgs = [sum(r[i] for r in results) / len(results) for i in range(4)]
        labels = ["grab (USB wait)", "retrieve (decode)", "crop (numpy)", f"encode Q{JPEG_QUALITY}"]
        total = sum(avgs)
        print(f"  {'Stage':<22} {'ms':>8}  {'%':>6}")
        print(f"  {'-'*40}")
        for lbl, ms in zip(labels, avgs):
            print(f"  {lbl:<22} {ms:>8.1f}  {ms/total*100:>5.1f}%")
        print(f"  {'-'*40}")
        print(f"  {'TOTAL':<22} {total:>8.1f}  → {1000/total:.1f} FPS max")
        print(f"\n  Camera target FPS: {FPS}  (interval: {1000/FPS:.0f} ms)")
        if total > 1000 / FPS:
            print(f"  Pipeline is {total - 1000/FPS:.0f} ms OVER budget → frames will be dropped")
        else:
            print(f"  Pipeline has {1000/FPS - total:.0f} ms headroom")


# ── TEST 8 ──────────────────────────────────────────────────────────────────

def test_visual_latency(cap):
    """Interactive visual latency test — point camera at a clock."""
    print("\n=== TEST 8: Visual Latency (interactive) ===")
    print("  Window opens with system timestamp overlay.")
    print("  Point the camera at a clock/phone timer to see the hardware delay.")
    print("  Press 'q' to quit.\n")

    cv2.namedWindow("Latency Test", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("Latency Test", 960, 960)
    drain(cap, 10)

    while True:
        t0 = time.perf_counter()
        ret, frame = cap.read()
        read_ms = (time.perf_counter() - t0) * 1000
        if not ret:
            continue
        cropped = frame[CROP_Y:CROP_Y + CROP_H, CROP_X:CROP_X + CROP_W]
        now_ms = int(time.time() * 1000)
        text = f"SYS: {time.strftime('%H:%M:%S')}.{now_ms % 1000:03d}"
        cv2.putText(cropped, text, (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 2.5, (0, 255, 0), 5)
        cv2.putText(cropped, f"read: {read_ms:.0f}ms", (40, 190), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 255, 255), 4)
        cv2.imshow("Latency Test", cropped)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    cv2.destroyAllWindows()


# ── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print("Camera Latency Diagnostic")
    print("=" * 60)

    if "--ae-test" in sys.argv:
        test_auto_exposure_impact()
        sys.exit(0)

    # Tests 1-2 don't need the camera open yet
    test_v4l2_controls()
    test_usb_bandwidth()

    # Tests 3-7 share one camera instance
    print("\nOpening camera for timing tests ...")
    cap = open_camera()

    test_buffer_depth(cap)
    test_grab_vs_retrieve(cap)
    test_crop_and_encode(cap)
    test_pipeline_budget(cap)

    if "--visual" in sys.argv:
        test_visual_latency(cap)
    else:
        print("\nTip: run with --visual for interactive test, --ae-test for AE comparison")

    cap.release()
    print("\nDone.")
