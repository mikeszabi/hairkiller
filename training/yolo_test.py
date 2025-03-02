import torch
from ultralytics import YOLO 
import cv2

# Check device
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print(f"Using device: {device}")

# Load the model and set device to CPU

device="cude" # "cude"
model_path = r"./model/follicle_v9.pt"
model_path = r"./model/follicle_exit_v11s_20250301.pt"

model = YOLO(model_path)
model.to(device)

image_path = r"./images/hair_test.png"
image_path = r"./images/hair_test_live.jpg"

im = cv2.imread(image_path)
im = cv2.cvtColor(im, cv2.COLOR_BGR2RGB)

results = model(im, device=device, conf=0.05)  # Inference using GPU


# Display results or process further as needed
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from PIL import Image
# Load the original image
image = Image.open(image_path)
image_np = np.array(image)


# Access the bounding boxes from results
results_cpu = results[0].cpu()  # Move to CPU if necessary
boxes = results_cpu.boxes  # Get the bounding boxes

# Plot the image and bounding boxes
plt.imshow(image_np)
ax = plt.gca()  # Get the current axes

# Iterate through the bounding boxes and plot them
for box in boxes:
    xyxy = box.xyxy[0].numpy()  # Get box coordinates in xyxy format
    # Create a Rectangle patch
    rect = patches.Rectangle(
        (xyxy[0], xyxy[1]),
        xyxy[2] - xyxy[0],
        xyxy[3] - xyxy[1],
        linewidth=2,
        edgecolor='r',
        facecolor='none'
    )
    ax.add_patch(rect)  # Add the patch to the axes

plt.show()