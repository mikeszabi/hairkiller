import cv2

def list_camera_details(max_index=10):
    cameras = []
    for index in range(max_index):
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            # Get some properties (e.g., frame width, height) for identification
            width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            fps = cap.get(cv2.CAP_PROP_FPS)
            cameras.append((index, width, height, fps))
            cap.release()
    return cameras

# List available cameras with details
camera_details = list_camera_details()
if camera_details:
    for cam in camera_details:
        print(f"Camera Index: {cam[0]}, Resolution: {cam[1]}x{cam[2]}, FPS: {cam[3]}")
else:
    print("No cameras detected.")