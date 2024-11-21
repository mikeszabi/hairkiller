import sys
sys.path.append(r'./code')

import cv2
from hair_detection import ObjectDetector

model_path = r"./model/follicle_v9.pt"
# Create an object detector
detector = ObjectDetector(model_path)

# Load an image
image_path = r"./images/hair_test.png"
image = cv2.imread(image_path)

# Run inference
boxes = detector.inference(image)
boxes = detector.remove_overlapping_boxes(boxes)
# Draw bounding boxes on the image
image_with_boxes = detector.draw_boxes(image.copy(), boxes)



# Display the image with bounding boxes
cv2.imshow('Object Detection', image_with_boxes)
cv2.waitKey(0)
cv2.destroyAllWindows()

