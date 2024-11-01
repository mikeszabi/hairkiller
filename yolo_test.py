from ultralytics import YOLO 

# Load the model and set device to CPU
model = YOLO("yolov8n.pt")  # Replace with the path to your YOLOv8 model
model.to("cpu")  # Ensure the model is running on CPU

# Run inference on an image
results = model("path/to/your/image.jpg")  # Replace with the path to your image

# Display results or process further as needed
results.show()