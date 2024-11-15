import sys
sys.path.append(r'./code')
import cv2
import tkinter as tk
from PIL import Image, ImageTk
import logging
import random
import time
import math
import json
import numpy as np
import matplotlib.pyplot as plt


from cam_interface import UVCInterface
from hair_detection import ObjectDetector
from laser_interface import LaserInterface
from robot_handler import RobotHandler
from calibrate_robot import save_transformation_to_file, calculate_homography, transform_to_robot_coordinates



# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

saved_coordinates=[]


def np_2_imageTK(im_np):
    img = Image.fromarray(im_np)
    imgtk = ImageTk.PhotoImage(image=img)
    return imgtk

# def move_robot(robot, x, y):
#     robot.move(x, y)
#     logging.info("Robot moved to (X: %s, Y: %s)", x, y)

# READ transformation matrix - global variable?
# ADD RobotHandler

def detect_laser_dot(image,drawing=True):
    """Detect the red laser dot in the image and return its coordinates."""
    # Define the range for the red color in BGR
    lower_red = np.array([0, 10, 150])
    upper_red = np.array([20, 100, 255])
    
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
            cv2.drawContours(image, [largest_contour], -1, (255, 0, 0), 5)
            # Draw the center of the laser dot
            cv2.circle(image, (cx, cy), 5, (255, 0, 0), -1)
            
            return (cx, cy)
    return None

def generate_random_coordinates(center, radius, n):
        coordinates = []
        for _ in range(n):
            angle = random.uniform(0, 2 * math.pi)
            r = radius * math.sqrt(random.uniform(0, 1))
            x = center[0] + r * math.cos(angle)
            y = center[1] + r * math.sin(angle)
            coordinates.append((x, y))
        return coordinates

class CameraApp:
    def __init__(self, root):
        self.root = root
        self.update_frame_running = True

        self.image_points = []
        self.robot_points = []
        self.H = None


        self.root.title("Interactive Camera App with Buttons and Coordinates")

        self.uvc_interface = UVCInterface()

        model_path = r"./model/best.pt"
        self.detector = ObjectDetector(model_path)

        self.laser = LaserInterface()

        self.robot = RobotHandler()

        # self.T = read_transformation_from_file(filename='transformation_matrix.txt')

        ######## UI Elements ########
        self.clicked_x, self.clicked_y = None, None
        self.isDetectionOn=tk.IntVar()
        self.isLaserPointer=tk.IntVar()
        self.laser_dim=1

        self.detection_boxes = []
        self_detection_centers = []

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
        self.display.bind("<Button-1>", self.click_event)

        ### Detection Panel
        self.detection_panel = tk.LabelFrame(self.root, text="Detection Settings", padx=10, pady=10)
        self.detection_panel.pack(side=tk.TOP, fill="x", padx=10, pady=10)

        self.btn_1 = tk.Checkbutton(self.detection_panel, text="Enable Detection", variable=self.isDetectionOn, onvalue=1, offvalue=0)
        self.btn_1.pack(anchor="w", pady=5)

        self.threshold_slider = tk.Scale(self.detection_panel, from_=0, to=0.5, resolution=0.01, orient=tk.HORIZONTAL, label="Detection Threshold")
        self.threshold_slider.set(0.1)  # Default value
        self.threshold_slider.pack(fill="x", pady=5)

        ### Laser Panel
        self.laser_panel = tk.LabelFrame(self.root, text="Laser Settings", padx=10, pady=10)
        self.laser_panel.pack(side=tk.TOP, fill="x", padx=10, pady=10)

        self.btn_2 = tk.Checkbutton(self.laser_panel, text="Enable Laser Pointer", variable=self.isLaserPointer, onvalue=1, offvalue=0, command=self.switch_plaser)
        self.btn_2.pack(anchor="w", pady=5)

        self.laser_slider = tk.Scale(self.laser_panel, from_=1, to=100, orient=tk.HORIZONTAL, label="Laser Intensity")
        self.laser_slider.bind("<ButtonRelease-1>", self.on_laser_update)
        self.laser_slider.pack(fill="x", pady=5)

        self.btn_3 = tk.Button(self.laser_panel, text="Shoot Laser", command=self.on_shoot)
        self.btn_3.pack(anchor="w", pady=5)

        ### Calibration Panel
        self.calibration_panel = tk.LabelFrame(self.root, text="Calibration Panel", padx=10, pady=10)
        self.calibration_panel.pack(side=tk.TOP, fill="x", padx=10, pady=10)


        self.calib_button = tk.Button(self.calibration_panel, text="Auto Calibrate", command=self.calibrate_robot)
        self.calib_button.pack(anchor="w", pady=5)


        ### Robot Panel

        self.robot_panel = tk.LabelFrame(self.root, text="Robot Panel", padx=10, pady=10)
        self.robot_panel.pack(side=tk.TOP, fill="x", padx=10, pady=10)

        self.move_up_button = tk.Button(self.robot_panel, text="Move Up", command=self.move_robot_up)
        self.move_up_button.grid(row=0, column=1, padx=5, pady=5)

        self.move_left_button = tk.Button(self.robot_panel, text="Move Left", command=self.move_robot_left)
        self.move_left_button.grid(row=1, column=0, padx=5, pady=5)

        self.move_right_button = tk.Button(self.robot_panel, text="Move Right", command=self.move_robot_right)
        self.move_right_button.grid(row=1, column=2, padx=5, pady=5)
        
        self.move_down_button = tk.Button(self.robot_panel, text="Move Down", command=self.move_robot_down)
        self.move_down_button.grid(row=2, column=1, padx=5, pady=5)

        self.move_step = tk.DoubleVar()
        self.move_step.set(1.0)
        self.step_slider = tk.Scale(self.robot_panel, from_=0, to=10, resolution=0.2, orient=tk.HORIZONTAL, label="Move Step", variable=self.move_step)
        self.step_slider.grid(row=3, column=1, padx=10, pady=10)
        
        self.btn_5 = tk.Button(self.robot_panel, text="MOVE 2 CLICK", command=self.move_2_last_click)
        self.btn_5.grid(row=5, column=0, padx=10, pady=10)

        self.btn_6 = tk.Button(self.robot_panel, text="MOVE 2 CLOSEST", command=self.move_2_closest)
        self.btn_6.grid(row=5, column=2, padx=10, pady=10)

        ###

        self.release_button = tk.Button(self.root, text="Release", command=self.on_closing)
        self.release_button.pack(side=tk.BOTTOM, padx=10, pady=10)

        self.update_frame()

    def update_frame(self):
        im_frame = self.uvc_interface.read_frame()

        if im_frame is not None:

            if self.clicked_x is not None and self.clicked_y is not None:
                cv2.circle(im_frame, (self.clicked_x, self.clicked_y), 5, (0, 255, 0), -1)
                cv2.putText(im_frame, f"({self.clicked_x}, {self.clicked_y})", 
                            (self.clicked_x + 10, self.clicked_y - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
                
            if self.isDetectionOn.get() == 1:
                self.detection_boxes  = self.detector.inference(im_frame, self.threshold_slider.get())
                self.detection_boxes  = self.detector.remove_overlapping_boxes(self.detection_boxes )
                im_frame = self.detector.draw_boxes(im_frame, self.detection_boxes)

                self_detection_centers = self.detector.get_box_centers(self.detection_boxes)
            
            imgtk = np_2_imageTK(im_frame)
            
            self.display.imgtk = imgtk
            self.display.config(image=imgtk)
            
            self.canvas.config(scrollregion=self.canvas.bbox("all"))
        
        if self.update_frame_running:
            self.root.after(10, self.update_frame)

    def calibrate_robot(self):

        self.update_frame_running = False
        saved_coordinates=[]
        # Example usage
        x, y, z, rx, ry, rz = self.robot.get_position() # Get current (x, y) position of the robot
        current_position = (x,y)  # Get current (x, y) position of the robot
        radius = 10  # Define the radius
        n = 6  # Number of random coordinates to generate

        random_coords = generate_random_coordinates(current_position, radius, n)
        logging.info("Generated random coordinates: %s", random_coords)

        fig, ax = plt.subplots()
        for i, coord in enumerate(random_coords):
            ax.plot(coord[0], coord[1], 'bo')  # Blue dot for random coordinates
            ax.text(coord[0], coord[1], f"{i}", color='black', fontsize=10)
        plt.pause(0.01)

        for robot_coord in random_coords:
            self.robot.handle_errors(None)
            self.robot.move_2_pos(robot_coord[0], robot_coord[1], z, rx, ry, rz)
            logging.info("Moved Robot to (X: %s, Y: %s)", robot_coord[0], robot_coord[1])
            time.sleep(10)
            im_frame = self.uvc_interface.read_frame()
            if im_frame is not None:
                laser_point = detect_laser_dot(im_frame)
                if laser_point is not None:
                    saved_coordinates.append((laser_point, robot_coord))
                    logging.info(f"Laser point: {laser_point}, Robot position: {robot_coord}")

                    #imgtk = np_2_imageTK(im_frame.copy())
                
                    # self.display.imgtk = imgtk
                    # self.display.config(image=imgtk)
                    # self.canvas.config(scrollregion=self.canvas.bbox("all"))

                    # Plot the detections and detected coordinates
                    fig, ax = plt.subplots()
                    plt.imshow(im_frame)

                    # Plot the laser points
                    plt.plot(laser_point[0], laser_point[1], 'ro')  # Red dot for laser points
                    plt.text(laser_point[0], laser_point[1], f"({robot_coord[0]:.2f}, {robot_coord[1]:.2f})", color='white', fontsize=8)

                    plt.pause(0.001)

        if len(saved_coordinates) > 5:
            self.H  = calculate_homography([d[0] for d in saved_coordinates], [d[1][0:2] for d in saved_coordinates])
            save_transformation_to_file(self.H)
            logging.info("Transformation matrix saved to transformation_matrix.txt")
            with open("saved_coordinates.json", "w") as f:
                json.dump(saved_coordinates, f)
            logging.info("Coordinates saved to saved_coordinates.json")
        else:
            logging.error("Not enough coordinates to compute transformation matrix. Please try again.")

        self.update_frame_running = True
        self.root.after(10, self.update_frame)

    def click_event(self, event):
        self.clicked_x, self.clicked_y = event.x, event.y
        logging.info("Clicked at (X: %s, Y: %s)", self.clicked_x, self.clicked_y)

    def move_2_last_click(self):
        if self.clicked_x is not None and self.clicked_y is not None:
            if self.H is None:
                logging.warning("No transformation matrix found. Please calibrate the robot.")
            else:
                # self.robor.move_to(self.clicked_x, self.clicked_y)
                #logging.info("Moved to (X: %s, Y: %s)", self.clicked_x, self.clicked_y)
                image_coords = (self.clicked_x, self.clicked_y)
                robot_coords = transform_to_robot_coordinates(image_coords,self.H)
                x,y,z,rx,ry,rz = self.robot.get_position()
                self.robot.move_2_pos(robot_coords[0], robot_coords[1], z, rx, ry, rz)
                logging.info("Moved Robot to (X: %s, Y: %s)", robot_coords[0], robot_coords[1])
        else:
            logging.warning("No click event recorded")

    def move_2_closest(self):
        # self.robor.move_to_closest()
        if self.detection_boxes:
            closest_box = min(self.detection_boxes, key=lambda box: math.hypot(box[0] - self.clicked_x, box[1] - self.clicked_y))
            closest_center = self.detector.get_box_centers([closest_box])[0]
            if self.T is None:
                logging.warning("No transformation matrix found. Please calibrate the robot.")
            else:
                robot_coords = transform_to_robot_coordinates(closest_center,self.H)
                x, y, z, rx, ry, rz = self.robot.get_position()
                self.robot.move_2_pos(robot_coords[0], robot_coords[1], z, rx, ry, rz)
                logging.info("Moved Robot to closest detection at (X: %s, Y: %s)", robot_coords[0], robot_coords[1])
        else:
            logging.warning("No detections found")
        logging.info("Moving to closest detection")

    def on_shoot(self):
        # grab the current timestamp and use it to construct the
        # output path
        self.laser.shoot()
        
    def switch_plaser(self):
        if self.isLaserPointer.get()==1:
            self.laser.plaser_on()
        else:
            self.laser.plaser_off()

    def on_laser_update(self,event):
        # set dim
        laser_dim=self.laser_slider.get()
        print(laser_dim)
        self.laser.setImpulse(value=laser_dim)


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
        self.robot.disconnet()
        cv2.destroyAllWindows()
        self.update_frame_running = False
        logging.info("Released camera and destroyed all windows")
        logging.info("Released resources")

    def on_closing(self):
        logging.info("Application is closing")
        self.release()
        self.root.destroy()
        self.root.quit()

def main():
    root = tk.Tk()
    app = CameraApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()