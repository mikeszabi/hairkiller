import sys
import time
sys.path.append(r'./code')
import cv2
from hair_detection import ObjectDetector, remove_overlapping_boxes, draw_boxes

model_path = r"./model/follicle_exit_v11s_20250301.pt"
# Create an object detector
detector = ObjectDetector(model_path)

# Load an image
image_path = r"./images/hair_test_live.jpg"
image = cv2.imread(image_path)

# Run inference

# t0 = time.time()
# boxes = detector.simple_inference(image)
# dt = time.time() - t0
# print(f"Simple inference time: {dt:.3f} s")

t0 = time.time()
boxes = detector.split_inference(image, conf=0.25)
dt = time.time() - t0
print(f"Split inference time: {dt:.3f} s")

boxes = remove_overlapping_boxes(boxes)
# Draw bounding boxes on the image
image_with_boxes = draw_boxes(image.copy(), boxes)

# Display the image with bounding boxes
cv2.imshow('Object Detection', image_with_boxes)
cv2.waitKey(0)
cv2.destroyAllWindows()

