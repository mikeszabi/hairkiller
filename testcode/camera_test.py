# v4l2-ctl --list-devices
# v4l2-ctl --list-formats-ext
# v4l2-ctl --all -d /dev/video0


import cv2

def find_cameras(max_index=2):
    found = []
    for i in range(max_index):
        cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
        if cap.isOpened():
            found.append(i)
            cap.release()
    return found

camera_indexes = find_cameras(2)
print("Found camera indexes:", camera_indexes)

if not camera_indexes:
    raise SystemExit("No cameras detected.")

idx = camera_indexes[0]  # pick the first one (or choose manually)
cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)

# Request MJPG (important for high resolutions on many UVC cams)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))

# Request a mode (start lower if needed, then increase)
# change values according to camera capabilities
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 2692)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1944)
cap.set(cv2.CAP_PROP_FPS, 10)

if not cap.isOpened():
    raise SystemExit("Error: Could not open camera.")

# Read a few frames to let it settle
for _ in range(5):
    cap.read()

w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
fps = cap.get(cv2.CAP_PROP_FPS)
print(f"Opened: {w}x{h} @ {fps} fps")

# create a resizable window and set desired display size
cv2.namedWindow("UVC Camera Stream", cv2.WINDOW_NORMAL)
cv2.resizeWindow("UVC Camera Stream", 1280, 720)  # adjust as needed

last_frame = None
while True:
    ret, frame = cap.read()
    print(f"Read frame: {ret}, shape: {frame.shape if frame is not None else 'None'}")
    if not ret or frame is None:
        print("Error: Could not read frame.")
        break

    # last_frame = frame
    # draw a hard-coded bounding box (modify coords as needed)
    tl = (336, 12)  # top-left corner (x, y)
    br = (2256, 1932)  # bottom-right corner (x, y)
    color = (0, 255, 0)  # green
    thickness = 2
    # cv2.rectangle(frame, tl, br, color, thickness)

    # crop using numpy slicing: frame[y1:y2, x1:x2]
    x1, y1 = tl
    x2, y2 = br
    cropped = frame[y1:y2, x1:x2]
    print(f"Cropped frame size: {cropped.shape[1]}x{cropped.shape[0]}")
    last_frame = cropped
    cv2.imshow("UVC Camera Stream", cropped)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()

if last_frame is not None:
    cv2.imwrite("test.jpg", last_frame)
    print("Saved test.jpg")