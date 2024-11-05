import sys
sys.path.append(r'./code')
import cv2
import tkinter as tk
from PIL import Image, ImageTk
import logging

from cam_interface import UVCInterface
from hair_detection import ObjectDetector
from laser_interface import LaserInterface


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def np_2_imageTK(im_np):
    img = Image.fromarray(im_np)
    imgtk = ImageTk.PhotoImage(image=img)
    return imgtk

class CameraApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Interactive Camera App with Buttons and Coordinates")

        self.uvc_interface = UVCInterface()

        model_path = r"./model/best.pt"
        self.detector = ObjectDetector(model_path)

        self.laser = LaserInterface()

        self.clicked_x, self.clicked_y = None, None
        self.isDetectionOn=tk.IntVar()
        self.isLaserPointer=tk.IntVar()
        self.laser_dim=1


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
        
        ###
        # self.button1 = tk.Button(root, text="Button 1", command=self.button_action_1)
        # self.button1.pack(side=tk.BOTTOM, padx=10, pady=10)

        # self.button2 = tk.Button(root, text="Button 2", command=self.button_action_2)
        # self.button2.pack(side=tk.LEFT, padx=10, pady=10)

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
                boxes = self.detector.inference(im_frame, self.threshold_slider.get())
                boxes = self.detector.remove_overlapping_boxes(boxes)
                im_frame = self.detector.draw_boxes(im_frame, boxes)
            
            imgtk = np_2_imageTK(im_frame)
            
            self.display.imgtk = imgtk
            self.display.config(image=imgtk)
            
            self.canvas.config(scrollregion=self.canvas.bbox("all"))
        
        self.root.after(10, self.update_frame)



    def click_event(self, event):
        self.clicked_x, self.clicked_y = event.x, event.y
        logging.info("Clicked at (X: %s, Y: %s)", self.clicked_x, self.clicked_y)

    def button_action_1(self):
        logging.info("Button 1 pressed!")

    def button_action_2(self):
        logging.info("Button 2 pressed!")

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
        
    def release(self):
        self.uvc_interface.release()
        cv2.destroyAllWindows()
        logging.info("Released camera and destroyed all windows")

    def on_closing(self):
        logging.info("Application is closing")
        self.release()
        self.root.destroy()

def main():
    root = tk.Tk()
    app = CameraApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()