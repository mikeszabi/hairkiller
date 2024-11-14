import sys
from ultralytics import YOLO
import cv2
import numpy as np


class ObjectDetector:
        def __init__(self, model_path, device="cpu"):
            self.model_path=model_path
            self.model = YOLO(self.model_path)
            self.model.to(device)
            self.device = device

        def inference(self, image_path, conf=0.05):
            results = self.model(image_path, conf=conf)
            results_cpu = results[0].cpu()
            boxes = results_cpu.boxes
            return boxes.data.numpy()
        
        def remove_overlapping_boxes(self, boxes, intersection_threshold=0.01):
            # Implement non-maximum suppression here
            if len(boxes) == 0:
                return []

            # Extract coordinates and scores
            x1 = boxes[:, 0]
            y1 = boxes[:, 1]
            x2 = boxes[:, 2]
            y2 = boxes[:, 3]
            scores = boxes[:, 4]

            # Compute the area of the bounding boxes and sort by score
            areas = (x2 - x1 + 1) * (y2 - y1 + 1)
            order = scores.argsort()[::-1]

            keep = []
            while order.size > 0:
                i = order[0]
                keep.append(i)

                xx1 = np.maximum(x1[i], x1[order[1:]])
                yy1 = np.maximum(y1[i], y1[order[1:]])
                xx2 = np.minimum(x2[i], x2[order[1:]])
                yy2 = np.minimum(y2[i], y2[order[1:]])

                w = np.maximum(0, xx2 - xx1 + 1)
                h = np.maximum(0, yy2 - yy1 + 1)
                inter = w * h

                ovr = inter / (areas[i] + areas[order[1:]] - inter)

                inds = np.where(ovr <= intersection_threshold)[0]
                order = order[inds + 1]

            return boxes[keep]
        
        def calculate_box_center(self, box):
            x1, y1, x2, y2, _, _ = box
            center = (x1 + x2) / 2, (y1 + y2) / 2
            return center
        
        def get_box_centers(self, boxes):
            centers = []
            for box in boxes:
                center = self.calculate_box_center(box)
                centers.append(center)
            return centers
 
            
        def draw_boxes(self, image, boxes):

            for box in boxes:
                center = self.calculate_box_center(box)
                x1, y1, x2, y2, _, _ = box
                xyxy = box[:4]
                start_point = (int(x1), int(y1))
                end_point = (int(x2), int(y2))
                color = (0, 0, 255)  # Red color in BGR
                thickness = 2
                image = cv2.rectangle(image, start_point, end_point, color, thickness)
                image = cv2.circle(image, (int(center[0]), int(center[1])), 5, (0, 0, 255), -1)

            return image
        