# v4l2-ctl --list-devices
# v4l2-ctl --list-formats-ext
# v4l2-ctl --all -d /dev/video0
# ls -l /dev/v4l/by-id/
# ls -l /dev/v4l/by-path/


import cv2, time

DEV = "/dev/v4l/by-id/usb-Arducam_Technology_Co.__Ltd._Arducam_16MP_SN0001-video-index0"

W, H, FPS = 2592, 1944, 5
FOURCC = "MJPG"

MAX_FAILS = 10          # ennyi egymás utáni read fail után restart
BACKOFF = 1.0           # restart előtt várakozás
WARMUP = 10

def open_cam():
    cap = cv2.VideoCapture(DEV, cv2.CAP_V4L2)
    if not cap.isOpened():
        return None

    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*FOURCC))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    # gyakran segít, hogy ne álljon bent sok régi frame:
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)

    for _ in range(WARMUP):
        cap.read()

    w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    fps = cap.get(cv2.CAP_PROP_FPS)
    fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
    f = "".join([chr((fourcc >> 8*i) & 0xFF) for i in range(4)])
    print(f"Opened negotiated: {w}x{h}@{fps} fourcc={f}", flush=True)
    return cap

def main():
    cv2.namedWindow("UVC", cv2.WINDOW_NORMAL)
    cv2.resizeWindow("UVC", 1280, 720)

    cap = None
    fails = 0

    while True:
        if cap is None:
            cap = open_cam()
            if cap is None:
                print("Open failed, retry...", flush=True)
                time.sleep(BACKOFF)
                continue
            fails = 0

        ret, frame = cap.read()

        if not ret or frame is None:
            fails += 1
            print(f"Read fail #{fails}", flush=True)
            if fails >= MAX_FAILS:
                print("Too many fails -> reopen", flush=True)
                try:
                    cap.release()
                except Exception:
                    pass
                cap = None
                time.sleep(BACKOFF)
            continue

        fails = 0

        # crop (ellenőrzéssel)
        # tl = (336, 12)
        # br = (2256, 1932)
        # x1, y1 = tl
        # x2, y2 = br
        # if frame.shape[1] >= x2 and frame.shape[0] >= y2:
        #     cropped = frame[y1:y2, x1:x2]
        # else:
        #     cropped = frame

        cv2.imshow("UVC", frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            cv2.imwrite("test.jpg", frame)
            break

    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()