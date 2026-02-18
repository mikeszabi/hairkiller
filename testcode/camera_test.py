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
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 2592)
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

last_frame = None
while True:
    ret, frame = cap.read()
    if not ret or frame is None:
        print("Error: Could not read frame.")
        break

    last_frame = frame
    cv2.imshow("UVC Camera Stream", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()

if last_frame is not None:
    cv2.imwrite("test.jpg", last_frame)
    print("Saved test.jpg")