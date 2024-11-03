from ultralytics import YOLO 

# Load the model and set device to CPU
model = YOLO("best.pt")  # Replace with the path to your YOLOv8 model
model.to("cpu")  # Ensure the model is running on CPU

# Run inference on an image
results = model("hair_test.png",conf=0.05)  # Replace with the path to your image

# Display results or process further as needed
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
from PIL import Image
# Load the original image
image_path = "hair_test.png"
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