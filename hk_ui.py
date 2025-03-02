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
from hair_detection import ObjectDetector, remove_overlapping_boxes, draw_boxes
from laser_interface import LaserInterface
from galvo_interface import GalvoInterface
from calibrate_mover import save_transformation_to_file, read_transformation_from_file,calculate_homography, transform_to_mover_coordinates



# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

saved_coordinates=[]


def np_2_imageTK(im_np):
    img = Image.fromarray(im_np)
    imgtk = ImageTk.PhotoImage(image=img)
    return imgtk


def detect_laser_dot(image,drawing=True):
    """Detect the red laser dot in the image and return its coordinates."""
    # Define the range for the red color in BGR
    # lower_red = np.array([0, 10, 150])
    # upper_red = np.array([20, 100, 255])
    lower_red = np.array([0, 0, 200])
    upper_red = np.array([255, 10, 255])
    
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
        self.mover_points = []
        self.laser_point = None
        self.im_frame = None
        self.H = None
        self.calibrate_on=False
        self.store_on=False
        self.move_random=False
        self.saved_coordinates=[]
        self.calib_position = None

        self.random_mover_radius = 200  # Define the radius for random coordinates
        self.mover_min=10
        self.mover_max=250
        self.mover_step=10

        self.laser_min=0
        self.laser_max=250
        self.laser_step=25

        self.detection_tsh_min=0
        self.detection_tsh_max=0.5
        self.detection_tsh_step=0.05

        self.root.title("Interactive Camera App with Buttons and Coordinates")

        self.uvc_interface = UVCInterface()

        model_path = r"./model/follicle_exit_v11s_20250301.pt"
        self.detector = ObjectDetector(model_path)

        self.load_transformation()

        self.laser = LaserInterface()

        self.mover = GalvoInterface()

        ######## UI Elements ########
        self.clicked_x, self.clicked_y = None, None
        self.isDetectionOn=tk.IntVar()
        self.isLaserPointer=tk.IntVar()

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


        ### Calibration Panel
        self.calibration_panel = tk.LabelFrame(self.root, text="Calibration Panel", padx=10, pady=10)
        self.calibration_panel.pack(side=tk.TOP, fill="x", padx=10, pady=10)


        self.calib_button = tk.Checkbutton(self.calibration_panel, text="Calibrate", command=self.calibrate_mover)
        self.calib_button.pack(anchor="w", pady=5)

        self.rmove_button = tk.Button(self.calibration_panel, text="Random move", command=self.random_move)
        self.rmove_button.pack(anchor="w", pady=5)

        self.store_button = tk.Button(self.calibration_panel, text="Store coordinates", command=self.store_coordinates)
        self.store_button.pack(anchor="w", pady=5)

        self.save_button = tk.Button(self.calibration_panel, text="Save And Calc", command=self.save_coordinates)
        self.save_button.pack(anchor="w", pady=5)

        self.coordinates_label = tk.Label(self.calibration_panel, text=f"Stored Coordinates: {len(self.saved_coordinates)}")
        self.coordinates_label.pack(anchor="w", pady=5)

        ### Detection Panel
        self.detection_panel = tk.LabelFrame(self.root, text="Detection Settings", padx=10, pady=10)
        self.detection_panel.pack(side=tk.TOP, fill="x", padx=10, pady=10)

        self.btn_1 = tk.Checkbutton(self.detection_panel, text="Enable Detection", variable=self.isDetectionOn, onvalue=1, offvalue=0)
        self.btn_1.pack(anchor="w", pady=5)

        self.threshold_slider = tk.Scale(self.detection_panel, from_=self.detection_tsh_min, to=self.detection_tsh_max, resolution=self.detection_tsh_step, orient=tk.HORIZONTAL, label="Detection Threshold")
        self.threshold_slider.set(self.detection_tsh_max/2)  # Default value
        self.threshold_slider.pack(fill="x", pady=5)

        ### mover Panel

        self.mover_panel = tk.LabelFrame(self.root, text="Mover Panel", padx=10, pady=10)
        self.mover_panel.pack(side=tk.TOP, fill="x", padx=10, pady=10)

        self.move_up_button = tk.Button(self.mover_panel, text="Move Up", command=self.move_mover_up)
        self.move_up_button.grid(row=0, column=1, padx=5, pady=5)

        self.move_left_button = tk.Button(self.mover_panel, text="Move Left", command=self.move_mover_left)
        self.move_left_button.grid(row=1, column=0, padx=5, pady=5)

        self.move_right_button = tk.Button(self.mover_panel, text="Move Right", command=self.move_mover_right)
        self.move_right_button.grid(row=1, column=2, padx=5, pady=5)
        
        self.move_down_button = tk.Button(self.mover_panel, text="Move Down", command=self.move_mover_down)
        self.move_down_button.grid(row=2, column=1, padx=5, pady=5)

        self.move_step = tk.DoubleVar()
        self.move_step.set(self.mover_max/2)
        self.step_slider = tk.Scale(self.mover_panel, from_= self.mover_min, to=self.mover_max, resolution=self.mover_step, orient=tk.HORIZONTAL, label="Move Step", variable=self.move_step)
        self.step_slider.grid(row=3, column=1, padx=10, pady=10)
        
        self.btn_5 = tk.Button(self.mover_panel, text="MOVE 2 CLICK", command=self.move_2_last_click)
        self.btn_5.grid(row=5, column=0, padx=10, pady=10)

        self.btn_7 = tk.Button(self.mover_panel, text="VISIT ALL", command=self.visit_all)
        self.btn_7.grid(row=5, column=2, padx=10, pady=10)

        self.btn_8 = tk.Button(self.mover_panel, text="VISIT ALL AND SHOOT", command=self.visit_all_and_shoot, bg="red")
        self.btn_8.grid(row=6, column=1, padx=10, pady=10)

        ### Laser Panel
        self.laser_panel = tk.LabelFrame(self.root, text="Laser Settings", padx=10, pady=10)
        self.laser_panel.pack(side=tk.TOP, fill="x", padx=10, pady=10)

        self.isLaserPointer.set(1)  # Set default value to on
        self.btn_2 = tk.Checkbutton(self.laser_panel, text="Enable Laser Pointer", variable=self.isLaserPointer, onvalue=1, offvalue=0, command=self.switch_plaser)
        self.btn_2.pack(anchor="w", pady=5)

        self.laser_slider = tk.Scale(self.laser_panel, from_=self.laser_min, to=self.laser_max, orient=tk.HORIZONTAL, label="Laser Intensity")
        self.laser_slider.bind("<ButtonRelease-1>", self.on_laser_update)
        self.laser_slider.pack(fill="x", pady=5)

        self.btn_3 = tk.Button(self.laser_panel, text="Shoot Laser", command=self.on_shoot)
        self.btn_3.pack(anchor="w", pady=5)

        ###

        self.release_button = tk.Button(self.root, text="Release", command=self.on_closing)
        self.release_button.pack(side=tk.BOTTOM, padx=10, pady=10)

        self.update_frame()

    def update_frame(self):
        self.im_frame, frame_index = self.uvc_interface.read_frame()

        if self.im_frame is not None:

            #logging.info("Frame %s read successfully", frame_index)

            if self.calibrate_on:
                self.laser_point = detect_laser_dot(self.im_frame)
                if self.move_random:
                    x, y = self.calib_position
                    random_coords = generate_random_coordinates(self.calib_position, self.random_mover_radius, 1)
                    next_coord = random_coords[0]
                    x,y = self.mover.get_position()
                    logging.info("Current position: (X: %s, Y: %s)", x, y)
                    self.move_mover(int(next_coord[0]), int(next_coord[1]))
                    self.move_random=False
                if self.store_on:
                    if self.laser_point is not None:
                        x, y= self.mover.get_position()
                        self.saved_coordinates.append((self.laser_point, (x,y)))
                        self.update_coordinates_label()
                        logging.info(f"Laser point: {self.laser_point}, mover position: {(x,y)}")
                    self.store_on=False

            if self.clicked_x is not None and self.clicked_y is not None:
                cv2.circle(self.im_frame, (self.clicked_x, self.clicked_y), 5, (0, 255, 0), -1)
                cv2.putText(self.im_frame, f"({self.clicked_x}, {self.clicked_y})", 
                            (self.clicked_x + 10, self.clicked_y - 10), 
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
                
            if self.isDetectionOn.get() == 1:
                self.detection_boxes  = self.detector.split_inference(self.im_frame, self.threshold_slider.get())
                #self.detection_boxes  = remove_overlapping_boxes(self.detection_boxes )
                self.im_frame = draw_boxes(self.im_frame, self.detection_boxes)

                self_detection_centers = self.detector.get_box_centers(self.detection_boxes)
            
            imgtk = np_2_imageTK(self.im_frame)
            
            self.display.imgtk = imgtk
            self.display.config(image=imgtk)
            
            self.canvas.config(scrollregion=self.canvas.bbox("all"))
            self.root.update_idletasks()
            self.root.update()
        
        if self.update_frame_running:
            self.root.after(10, self.update_frame)

    def calibrate_mover(self):

        if not self.calibrate_on:
            self.saved_coordinates=[]
            self.calib_position = self.mover.get_position() # Get current (x, y) position of the mover
            self.calibrate_on = True
        else:
            self.calibrate_on = False

    def store_coordinates(self):
        self.store_on=True

    def random_move(self):
        self.move_random=True

    def save_coordinates(self):
        if len(self.saved_coordinates) > 5:
            self.H  = calculate_homography([d[0] for d in self.saved_coordinates], [d[1][0:2] for d in self.saved_coordinates])
            save_transformation_to_file(self.H)
            logging.info("Transformation matrix saved to transformation_matrix.txt")
            with open("saved_coordinates.json", "w") as f:
                json.dump(self.saved_coordinates, f)
            logging.info("Coordinates saved to saved_coordinates.json")
        self.saved_coordinates=[]
        self.update_coordinates_label()

    def load_transformation(self):
        self.H = read_transformation_from_file(filename='transformation_matrix.txt')
        logging.info("Transformation matrix loaded from transformation_matrix.txt")
    
    def update_coordinates_label(self):
        self.coordinates_label.config(text=f"Stored Coordinates: {len(self.saved_coordinates)}")


    def click_event(self, event):
        self.clicked_x, self.clicked_y = event.x, event.y
        logging.info("Clicked at (X: %s, Y: %s)", self.clicked_x, self.clicked_y)

    def move_2_last_click(self):
        if self.clicked_x is not None and self.clicked_y is not None:
            if self.H is None:
                logging.warning("No transformation matrix found. Please calibrate the mover.")
            else:
                image_coords = (self.clicked_x, self.clicked_y)
                mover_coords = transform_to_mover_coordinates(image_coords,self.H)
                x,y = self.mover.get_position()
                logging.info("Current position: (X: %s, Y: %s)", x, y)
                self.move_mover(int(mover_coords[0]), int(mover_coords[1]))
        else:
            logging.warning("No click event recorded")


    def visit_all(self):
        if self.detection_boxes is not None:
            for box in self.detection_boxes:
                center = self.detector.get_box_centers([box])[0]
                mover_coords = transform_to_mover_coordinates(center,self.H)
                
                self.move_mover(int(mover_coords[0]), int(mover_coords[1]))
                time.sleep(1)

                self.im_frame, frame_index = self.uvc_interface.read_frame()

                if self.im_frame is not None:
                    #logging.info("Frame %s read successfully", frame_index)
                    self.im_frame = self.detector.draw_boxes(self.im_frame, self.detection_boxes)

                    imgtk = np_2_imageTK(self.im_frame)
                    self.display.imgtk = imgtk
                    self.display.config(image=imgtk)
                    self.canvas.config(scrollregion=self.canvas.bbox("all"))
                    self.root.update_idletasks()
                    self.root.update()
        else:
            logging.warning("No detections found")

    def visit_all_and_shoot(self):
        if self.detection_boxes is not None:
            for box in self.detection_boxes:
                center = self.detector.get_box_centers([box])[0]
                mover_coords = transform_to_mover_coordinates(center,self.H)
                
                self.move_mover(int(mover_coords[0]), int(mover_coords[1]))
                time.sleep(1)
                self.laser.shoot()

                self.im_frame, frame_index = self.uvc_interface.read_frame()

                if self.im_frame is not None:
                    #logging.info("Frame %s read successfully", frame_index)
                    self.im_frame = self.detector.draw_boxes(self.im_frame, self.detection_boxes)

                    imgtk = np_2_imageTK(self.im_frame)
                    self.display.imgtk = imgtk
                    self.display.config(image=imgtk)
                    self.canvas.config(scrollregion=self.canvas.bbox("all"))
                    self.root.update_idletasks()
                    self.root.update()
        else:
            logging.warning("No detections found")

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
        logging.info("Laser intensity set to: %s", laser_dim)


        self.laser.setImpulse(value=laser_dim)

    def move_mover(self,x,y):
        new_pos = self.mover.move_2_pos(x, y)
        if new_pos is None:
            logging.warning("The position is out of range")
        else:
            logging.info("New position: (X: %s, Y: %s)", new_pos[0], new_pos[1])

    def move_mover_up(self):
        x,y = self.mover.get_position()
        logging.info("Current position: (X: %s, Y: %s)", x, y)
        y=y+int(self.move_step.get())
        self.move_mover(x,y)

    def move_mover_down(self):
        x,y = self.mover.get_position()
        logging.info("Current position: (X: %s, Y: %s)", x, y)
        y=y-int(self.move_step.get())
        self.move_mover(x,y)

    def move_mover_left(self):
        x,y = self.mover.get_position()
        logging.info("Current position: (X: %s, Y: %s)", x, y)
        x=x+int(self.move_step.get())
        self.move_mover(x,y)


    def move_mover_right(self):
        x,y = self.mover.get_position()
        logging.info("Current position: (X: %s, Y: %s)", x, y)
        x=x-int(self.move_step.get())
        self.move_mover(x,y)


    def release(self):
        self.uvc_interface.release()
        self.mover.stop()
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