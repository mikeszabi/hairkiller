import cv2

def list_camera_details(max_index=10):
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
        except Exception as e:
            print(f"Error: Could not open camera index {index}.")
    return cameras

# List available cameras with details
camera_details = list_camera_details()
if camera_details:
    for cam in camera_details:
        print(f"Camera Index: {cam[0]}, Resolution: {cam[1]}x{cam[2]}, FPS: {cam[3]}")
else:
    print("No cameras detected.")


# Open a connection to the UVC camera (usually camera index 0 for the first USB camera)

selected_camera_index = None
for cam in camera_details:
    if cam[1] == 1280:
        selected_camera_index = cam[0]
        break

if selected_camera_index is None:
    print("No camera with the specified width found.")
    exit()

cap = cv2.VideoCapture(selected_camera_index)

#cap = cv2.VideoCapture(2)  # Change the index if you have multiple cameras

# Check if the camera opened successfully
if not cap.isOpened():
    print("Error: Could not open camera.")
    exit()

# # Set resolution (optional)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 2560)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1920)

# Display the camera feed
while True:
    # Capture frame-by-frame
    ret, frame = cap.read()
    print(frame.shape)
    
    # If frame is read correctly, ret is True
    if not ret:
        print("Error: Could not read frame.")
        break
    
    # Display the resulting frame
    cv2.imshow('UVC Camera Stream', frame)
    
    # Press 'q' to exit the loop
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# Release the capture and close the window
cap.release()
cv2.destroyAllWindows()

cv2.imwrite('test.jpg', frame)