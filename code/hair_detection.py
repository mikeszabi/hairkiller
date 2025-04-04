import sys
import torch
from ultralytics import YOLO
import cv2
import numpy as np
import tempfile
from detection_utils import remove_overlapping_boxes, calculate_box_center, get_box_centers, draw_boxes, split_image, merge_predictions

class ObjectDetector:
        def __init__(self, model_path, device="cpu"):
            self.model_path=model_path
            self.model = YOLO(self.model_path)
            if device == "cuda" and torch.cuda.is_available():
                self.model.to(device)
            self.device = device

        def simple_inference(self, image, conf=0.05):
            results = self.model(image, conf=conf)
            results_cpu = results[0].cpu()
            boxe_with_scores = results_cpu.boxes
            return boxe_with_scores.data.numpy()
        
        def split_inference(self, image, conf=0.05):
            # large images are split into smaller (640x604) tiles
             # Split image into grid
            tiles, original_shape, grid_size = split_image(image)
            
            # Run inference on all tiles
            results = []
            with torch.no_grad():
                for tile in tiles:
                    # with tempfile.NamedTemporaryFile(suffix=".jpg") as temp_file:
                    #     temp_path = temp_file.name
                    #     cv2.imwrite(temp_path, tile)
                    #     result = self.model(temp_path, conf=0.2)[0]
                    #     results.append(result)
                    # cv2.imwrite(temp_path, tile)
                    result = self.model(tile, conf=conf)[0]
                    results.append(result)
            
            # Merge predictions
            boxes, scores, classes = merge_predictions(results, original_shape, grid_size)
            if len(boxes) == 0:
                return []
            boxes_with_scores = np.concatenate((boxes, scores[:, None], classes[:,None]), axis=1)
            return boxes_with_scores
                

        