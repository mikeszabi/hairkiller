import sys
sys.path.append(r'./code')
import cv2
import numpy as np
import tkinter as tk
import logging
from PIL import Image, ImageTk
from robot_handler import RobotHandler
from cam_interface import UVCInterface
import json

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

saved_coordinates=[]

def detect_laser_dot(image,drawing=True):
    """Detect the red laser dot in the image and return its coordinates."""
    # Define the range for the red color in BGR
    lower_red = np.array([0, 25, 100])
    upper_red = np.array([10, 100, 255])
    
    # Convert image to HSV color space
    hsv_image = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    
    # Create a mask for the red color
    mask = cv2.inRange(hsv_image, lower_red, upper_red)
    # Find contours of the laser dot
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(image, contours, -1, (0, 100, 0), 1)
    if contours:
        # Get the largest contour (assuming it's the laser dot)
        largest_contour = max(contours, key=cv2.contourArea)
        M = cv2.moments(largest_contour)
        if M["m00"] > 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            
            # Draw the largest contour
            cv2.drawContours(image, [largest_contour], -1, (0, 255, 0), 5)
            # Draw the center of the laser dot
            cv2.circle(image, (cx, cy), 5, (255, 0, 0), -1)
            
            return (cx, cy)
    return None

class CalibrateRobotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Calibrate Robot App")

        self.robot = RobotHandler()
        self.uvc_interface = UVCInterface()

        self.image_points = []
        self.robot_points = []

        self.canvas = tk.Canvas(self.root, width=1024, height=768)
        self.scroll_x = tk.Scrollbar(self.root, orient="horizontal", command=self.canvas.xview)
        self.scroll_y = tk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.scroll_x.set, yscrollcommand=self.scroll_y.set)

        self.scroll_x.pack(side="bottom", fill="x")
        self.scroll_y.pack(side="right", fill="y")
        self.canvas.pack(side="left", expand=True, fill="both")

        self.frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.frame, anchor="nw")

        self.display = tk.Label(self.frame)
        self.display.pack()

        self.store_button = tk.Button(self.root, text="Store Coordinates", command=self.store_coordinates)
        self.store_button.pack()

        self.save_button = tk.Button(self.root, text="Save Coordinates", command=self.save_coordinates)
        self.save_button.pack()

        self.release_button = tk.Button(self.root, text="Release", command=self.on_closing)
        self.release_button.pack(side=tk.BOTTOM, padx=10, pady=10)

        self.control_frame = tk.Frame(self.root)
        self.control_frame.pack(side=tk.RIGHT, padx=10, pady=10)

        self.move_up_button = tk.Button(self.control_frame, text="Move Up", command=self.move_robot_up)
        self.move_up_button.grid(row=0, column=1, padx=5, pady=5)

        self.move_left_button = tk.Button(self.control_frame, text="Move Left", command=self.move_robot_left)
        self.move_left_button.grid(row=1, column=0, padx=5, pady=5)

        self.move_right_button = tk.Button(self.control_frame, text="Move Right", command=self.move_robot_right)
        self.move_right_button.grid(row=1, column=2, padx=5, pady=5)
        
        self.move_down_button = tk.Button(self.control_frame, text="Move Down", command=self.move_robot_down)
        self.move_down_button.grid(row=2, column=1, padx=5, pady=5)

        self.move_step = tk.DoubleVar()
        self.move_step.set(1.0)
        self.step_slider = tk.Scale(self.control_frame, from_=0, to=10, resolution=0.2, orient=tk.HORIZONTAL, label="Move Step", variable=self.move_step)
        self.step_slider.grid(row=3, column=1, padx=10, pady=10)

        # Labels to display coordinates
        self.coord_frame = tk.Frame(self.root)
        self.coord_frame.pack(side=tk.TOP, padx=10, pady=10)

        self.laser_coords_label = tk.Label(self.coord_frame, text="Laser Coordinates: N/A")
        self.laser_coords_label.grid(row=4, column=0, columnspan=3, padx=5, pady=5)

        self.robot_coords_label = tk.Label(self.coord_frame, text="Robot Coordinates: N/A")
        self.robot_coords_label.grid(row=5, column=0, columnspan=3, padx=5, pady=5)

        self.update_frame()

    def update_frame(self):
        frame = self.uvc_interface.read_frame()
        laser_point = detect_laser_dot(frame)
        if laser_point is not None:
            self.image_points.append(laser_point)
            robot_position = self.robot.get_position()
            self.robot_points.append(robot_position)

            # Convert the frame to an image for tkinter
            img = Image.fromarray(frame.copy())
            imgtk = ImageTk.PhotoImage(image=img)

            # Update the canvas image
            self.display.imgtk = imgtk
            self.display.config(image=imgtk)

            logging.info(f"Laser point: {laser_point}, Robot position: {robot_position}")

            # Display the laser point and robot position on the UI
            # Update the labels with the coordinates
            self.laser_coords_label.config(text=f"Laser Coordinates: {laser_point}")
            self.robot_coords_label.config(text=f"Robot Coordinates: {robot_position[0:2]}")        
        self.root.after(10, self.update_frame)

    def store_coordinates(self):
        if self.image_points and self.robot_points:
            global saved_coordinates
            saved_coordinates.append((self.image_points[-1], self.robot_points[-1]))
            logging.info(f"Saved coordinates: Image {self.image_points[-1]}, Robot {self.robot_points[-1]}")

    def save_coordinates(self):
        if saved_coordinates:
            with open("saved_coordinates.json", "w") as f:
                json.dump(saved_coordinates, f)
            logging.info("Coordinates saved to saved_coordinates.json")

    def move_robot_left(self):
        self.robot.handle_errors(None)
        self.robot.move_rel(0, -self.move_step.get(), 0, 0, 0, 0)
        logging.info("Moved robot left")

    def move_robot_right(self):
        self.robot.handle_errors(None)
        self.robot.move_rel(0, self.move_step.get(), 0, 0, 0, 0)
        logging.info("Moved robot right")

    def move_robot_up(self):
        self.robot.handle_errors(None)
        self.robot.move_rel(-self.move_step.get(), 0, 0, 0, 0, 0)
        logging.info("Moved robot up")

    def move_robot_down(self):
        self.robot.handle_errors(None)
        self.robot.move_rel(self.move_step.get(), 0, 0, 0, 0, 0)
        logging.info("Moved robot down")

    def release(self):
        self.uvc_interface.release()
        self.robot.deactivate()
        self.robot.disconnect()
        logging.info("Released resources")

    def on_closing(self):
        logging.info("Application is closing")
        self.release()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = CalibrateRobotApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()