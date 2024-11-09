import sys
sys.path.append(r'./code')
import cv2
import numpy as np
import tkinter as tk
import logging
from PIL import Image, ImageTk
from robot_handler import RobotHandler
from cam_interface import UVCInterface

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

class CalibrateRobotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Calibrate Robot App")

        self.robot = RobotHandler()
        self.uvc_interface = UVCInterface()

        self.image_points = []
        self.robot_points = []

        self.canvas = tk.Canvas(root, width=1024, height=768)
        self.scroll_x = tk.Scrollbar(root, orient="horizontal", command=self.canvas.xview)
        self.scroll_y = tk.Scrollbar(root, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=self.scroll_x.set, yscrollcommand=self.scroll_y.set)

        self.scroll_x.pack(side="bottom", fill="x")
        self.scroll_y.pack(side="right", fill="y")
        self.canvas.pack(side="left", expand=True, fill="both")

        self.frame = tk.Frame(self.canvas)
        self.canvas.create_window((0, 0), window=self.frame, anchor="nw")

        self.display = tk.Label(self.frame)
        self.display.pack()

        self.save_button = tk.Button(root, text="Save Coordinates", command=self.save_coordinates)
        self.save_button.pack()

        self.move_left_button = tk.Button(root, text="Move Left", command=self.move_robot_left)
        self.move_left_button.pack(side=tk.LEFT, padx=10, pady=10)

        self.move_right_button = tk.Button(root, text="Move Right", command=self.move_robot_right)
        self.move_right_button.pack(side=tk.LEFT, padx=10, pady=10)

        self.move_up_button = tk.Button(root, text="Move Up", command=self.move_robot_up)
        self.move_up_button.pack(side=tk.LEFT, padx=10, pady=10)

        self.move_down_button = tk.Button(root, text="Move Down", command=self.move_robot_down)
        self.move_down_button.pack(side=tk.LEFT, padx=10, pady=10)

        self.update_frame()

    def update_frame(self):
        frame = self.uvc_interface.read_frame()
        laser_point = detect_laser_dot(frame)
        if laser_point is not None:
            self.image_points.append(laser_point)
            robot_position = self.robot.get_position()
            self.robot_points.append(robot_position)

            # Convert the frame to an image for tkinter
            cv2image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(cv2image)
            imgtk = ImageTk.PhotoImage(image=img)

            # Update the canvas image
            self.display.imgtk = imgtk
            self.display.config(image=imgtk)

            logging.info(f"Laser point: {laser_point}, Robot position: {robot_position}")

        self.root.after(10, self.update_frame)

    def save_coordinates(self):
        if self.image_points and self.robot_points:
            logging.info(f"Saved coordinates: Image {self.image_points[-1]}, Robot {self.robot_points[-1]}")

    def move_robot_left(self):
        self.robot.move_rel(-10, 0, 0, 0, 0, 0)
        logging.info("Moved robot left")

    def move_robot_right(self):
        self.robot.move_rel(10, 0, 0, 0, 0, 0)
        logging.info("Moved robot right")

    def move_robot_up(self):
        self.robot.move_rel(0, -10, 0, 0, 0, 0)
        logging.info("Moved robot up")

    def move_robot_down(self):
        self.robot.move_rel(0, 10, 0, 0, 0, 0)
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