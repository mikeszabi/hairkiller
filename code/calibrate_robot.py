import sys
sys.path.append(r'./code')
import cv2
import numpy as np
import tkinter as tk
import math
import keyboard

from robot_handler import RobotHandler
from cam_interface import UVCInterface

from sklearn.linear_model import LinearRegression
import matplotlib.pyplot as plt

def detect_laser_dot(image):
    """Detect the red laser dot in the image and return its coordinates."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    lower_red = np.array([0, 100, 100])
    upper_red = np.array([10, 255, 255])
    mask = cv2.inRange(hsv, lower_red, upper_red)
    
    # Find contours of the laser dot
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        # Get the largest contour (assuming it's the laser dot)
        largest_contour = max(contours, key=cv2.contourArea)
        M = cv2.moments(largest_contour)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            return (cx, cy)
    return None

# def collect_calibration_data(robot, camera, num_points=10):
#     """Collect calibration data by moving the robot to known positions and capturing image points."""
#     image_points = []
#     robot_points = []
    
#     # Set up the plot
#     plt.ion()
#     fig, ax = plt.subplots(1, 2, figsize=(12, 6))
#     ax[0].set_title('Image Points')
#     ax[1].set_title('Robot Points')
#     img_plot = ax[0].imshow(np.zeros((480, 640, 3), dtype=np.uint8))  # Assuming a 640x480 image size
#     robot_plot, = ax[1].plot([], [], 'ro')
    
#     for _ in range(num_points):
#         # Get current robot position
#         !!!! robot_position = robot.get_cartesian_position()
#         x, y = robot_position[0], robot_position[1]
        
#         # Capture image and detect laser dot
#         ret, frame = camera.read()
#         if not ret:
#             print("Failed to capture image")
#             continue
        
#         laser_point = detect_laser_dot(frame)
#         if laser_point is not None:
#             image_points.append(laser_point)
#             robot_points.append((x, y))
            
#             # Update the image plot
#             img_plot.set_data(frame)
#             ax[0].scatter(*laser_point, color='red')
            
#             # Update the robot points plot
#             robot_plot.set_data(*zip(*robot_points))
#             ax[1].relim()
#             ax[1].autoscale_view()
            
#             plt.draw()
#             plt.pause(0.1)
            
#         print(f"Captured point: {laser_point} -> Robot: {x}, {y}")
    
#     plt.ioff()
#     plt.show()
    
#     return np.array(image_points), np.array(robot_points)

def collect_calibration_data(robot, uvc_interface):
    """Collect data by moving the robot with tkinter buttons and capturing image points."""
    image_points = []
    robot_points = []
    
    def save_coordinates():
        if laser_point is not None:
            image_points.append(laser_point)
            robot_points.append(robot_position)
            print(f"Saved coordinates: Image {laser_point}, Robot {robot_position}")

    def move_robot_left():
        nonlocal robot_position
        robot.move_rel(-10, 0, 0, 0, 0, 0)
        robot_position = robot.get_position()
        print(f"Robot position: {robot_position}")

    def move_robot_right():
        nonlocal robot_position
        robot.move_rel(10, 0, 0, 0, 0, 0)
        robot_position = robot.get_position()
        print(f"Robot position: {robot_position}")

    def move_robot_up():
        nonlocal robot_position
        robot.move_rel(0, -10, 0, 0, 0, 0)
        robot_position = robot.get_position()
        print(f"Robot position: {robot_position}")

    def move_robot_down():
        nonlocal robot_position
        robot.move_rel(0, 10, 0, 0, 0, 0)
        robot_position = robot.get_position()
        print(f"Robot position: {robot_position}")

    # Set up the tkinter window
    root = tk.Tk()
    root.title("Data Collection")

    save_button = tk.Button(root, text="Save Coordinates", command=save_coordinates)
    save_button.pack()

    move_left_button = tk.Button(root, text="Move Left", command=move_robot_left)
    move_left_button.pack(side=tk.LEFT, padx=10, pady=10)

    move_right_button = tk.Button(root, text="Move Right", command=move_robot_right)
    move_right_button.pack(side=tk.LEFT, padx=10, pady=10)

    move_up_button = tk.Button(root, text="Move Up", command=move_robot_up)
    move_up_button.pack(side=tk.LEFT, padx=10, pady=10)

    move_down_button = tk.Button(root, text="Move Down", command=move_robot_down)
    move_down_button.pack(side=tk.LEFT, padx=10, pady=10)

    # Set up the plot
    plt.ion()
    fig, ax = plt.subplots(1, 2, figsize=(12, 6))
    ax[0].set_title('Image Points')
    ax[1].set_title('Robot Points')
    img_plot = ax[0].imshow(np.zeros((480, 640, 3), dtype=np.uint8))  # Assuming a 640x480 image size
    robot_plot, = ax[1].plot([], [], 'ro')

    robot_position = robot.get_position()
    laser_point = None

    stop = False

    def stop_collection():
        nonlocal stop
        stop = True

    stop_button = tk.Button(root, text="STOP", command=stop_collection)
    stop_button.pack()

    while not stop:
        # Capture image and detect laser dot
        frame = uvc_interface.read_frame()

        laser_point = detect_laser_dot(frame)
        if laser_point is not None:
            # Update the image plot
            img_plot.set_data(frame)
            ax[0].scatter(*laser_point, color='red')

            # Update the robot points plot
            if robot_points:
                robot_plot.set_data(*zip(*robot_points))
                ax[1].relim()
                ax[1].autoscale_view()

            plt.draw()
            plt.pause(0.1)

        print(f"Laser point: {laser_point}")

        # Update the tkinter window
        root.update_idletasks()
        root.update()

    plt.ioff()
    plt.show()

    return np.array(image_points), np.array(robot_points)


def compute_transformation(image_points, robot_points):
    """Compute a transformation matrix between image and robot coordinates."""
    A = []
    B = []
    
    for (u, v), (x, y) in zip(image_points, robot_points):
        A.append([u, v, 1, 0, 0, 0])
        A.append([0, 0, 0, u, v, 1])
        B.append(x)
        B.append(y)
    
    A = np.array(A)
    B = np.array(B)
    
    # Solve for transformation matrix
    T = np.linalg.lstsq(A, B, rcond=None)[0]
    # Save the transformation matrix to a file
    np.savetxt('transformation_matrix.txt', T)
    return T.reshape(2, 3)

def apply_transformation(T, image_point):
    """Apply the transformation matrix to convert image coordinates to robot coordinates."""
    u, v = image_point
    x = T[0, 0] * u + T[0, 1] * v + T[0, 2]
    y = T[1, 0] * u + T[1, 1] * v + T[1, 2]
    return x, y

def read_transformation_from_file(filename='transformation_matrix.txt'):
    """Read the transformation matrix from a file."""
    T = np.loadtxt(filename)
    return T.reshape(2, 3)

# def move_robot_to_click(event, x, y, flags, params):
#     """Mouse click callback function to move the robot to the clicked position."""
#     if event == cv2.EVENT_LBUTTONDOWN:
#         T, robot = params
#         robot_coords = apply_transformation(T, (x, y))
#         print(f"Moving robot to coordinates: {robot_coords}")
#         !!!! robot.move_linear(robot_coords[0], robot_coords[1], 0)  # Assuming z = 0


def main():
    robot = RobotHandler()

    print(robot.is_allowed_to_move())
    robot.handle_errors(None)

    print(robot.is_allowed_to_move())

    uvc_interface = UVCInterface()
        
    # Collect calibration data
    image_points, robot_points = collect_calibration_data(robot, uvc_interface)
    T = compute_transformation(image_points, robot_points)
    print("Transformation matrix:", T)
    
    # Set up the OpenCV window with mouse callback
    # cv2.namedWindow("Camera Feed")
    # cv2.setMouseCallback("Camera Feed", move_robot_to_click, (T, robot))
    
    # while True:
    #     im_frame = uvc_interface.read_frame()
    #     if not ret:
    #         break
        
    #     # Detect laser dot for visual feedback
    #     laser_point = detect_laser_dot(im_frame)
    #     if laser_point:
    #         cv2.circle(im_frame, laser_point, 5, (0, 255, 0), -1)
        
    #     cv2.imshow("Camera Feed", im_frame)
        
    #     # Press 'q' to exit the loop
    #     if cv2.waitKey(1) & 0xFF == ord('q'):
    #         break

    #cv2.destroyAllWindows()


    uvc_interface.release()
    robot.deactivate()
    robot.disconnet()

if __name__ == "__main__":
    main()
