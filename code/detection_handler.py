import sys
from pathlib import Path
import torch
from ultralytics import YOLO
import cv2
import numpy as np
import tempfile
import logging
from detection_utils import remove_overlapping_boxes, calculate_box_center, get_box_centers, draw_boxes, split_image, merge_predictions

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def preprocess_tiles(tiles, device="cuda"):
    """Resize and convert tiles to torch tensors (BGR->RGB)."""
    tensor_tiles = []
    for tile in tiles:
        #tile_resized = cv2.resize(tile, (640, 640))
        tile = cv2.cvtColor(tile, cv2.COLOR_BGR2RGB)
        tile_tensor = torch.from_numpy(tile).permute(2, 0, 1).float() / 255.0
        tensor_tiles.append(tile_tensor)
    batch_tensor = torch.stack(tensor_tiles).to(device)
    return batch_tensor

class ObjectDetector:
        def __init__(self, model_path, device="cuda"):
            self.model_path=model_path
            if device == "cuda" and not torch.cuda.is_available():
                raise RuntimeError("CUDA requested for YOLO detector, but torch.cuda.is_available() is false")
            self.model = YOLO(self.model_path)
            self.device = device
            self.model.to(self.device)

        def simple_inference(self, image, conf=0.05):
            # Run inference on a single image, resolution is 640x640
            with torch.no_grad():
                results = self.model(image, conf=conf, verbose=False)
            results_cpu = results[0].cpu()
            boxes_with_scores = results_cpu.boxes
            return boxes_with_scores.data.numpy()
        
        def split_inference(self, image, conf=0.1):
            # large images are split into smaller (640x604) tiles, then batch processed
             # Split image into grid
            tiles, original_shape, grid_size = split_image(image)
            #logging.info(f"Split into {len(tiles)} tiles.")

            # --- Preprocess tiles into batch tensor ---
            tile_batch = preprocess_tiles(tiles, device=self.device)

            # --- Inference in batch ---
            with torch.no_grad():
                results = self.model(tile_batch, conf=conf, verbose=False)

            # # Run inference on all tiles
            # results = []
            # with torch.no_grad():
            #     for tile in tiles:
            #         result = self.model(tile, conf=conf)[0]
            #         results.append(result)

            # --- Merge tile predictions back to original image ---
            boxes, scores, classes = merge_predictions(results, image.shape, grid_size)  

            if len(boxes) == 0:
                return []
            boxes_with_scores = np.concatenate((boxes, scores[:, None], classes[:,None]), axis=1)
            return boxes_with_scores

                
def main():
    # --- Load TensorRT YOLO model ---

    model_path = Path(__file__).resolve().parent.parent / "model" / "follicle_exit_v11i_yolov8n_20250513.pt"

    detector = ObjectDetector(str(model_path))

    # --- Load and split full image ---
    image_path = "./images/hair_test_live_2.jpg"
    im_frame = cv2.imread(image_path)
    if im_frame is None:
        print(f"Error: Could not load image at {image_path}")
        return

    boxes_with_scores=detector.split_inference(im_frame, conf=0.1)
    if len(boxes_with_scores) == 0:
        print("No objects detected.")
        return

    logging.info(f"Detected {len(boxes_with_scores)} objects.")
    # --- Remove overlapping boxes ---
    boxes_distinct = remove_overlapping_boxes(boxes_with_scores)
    logging.info(f"After removing overlaps, {len(boxes_distinct)} objects remain.")
    # --- Calculate box centers ---
    centers = get_box_centers(boxes_distinct)
    logging.info(f"Calculated {len(centers)} box centers.")
    # --- Draw boxes on image ---
    im_with_boxes = draw_boxes(im_frame.copy(), boxes_distinct)
    cv2.imwrite("output_boxes.jpg", im_with_boxes)
    print("Boxes drawn on image saved as output_boxes.jpg")
    # --- Save box centers ---
    centers_path = "box_centers.txt"
    np.savetxt(centers_path, centers, fmt='%.2f', header='x,y', comments='')
    print(f"Box centers saved to {centers_path}")
    logging.info(f"Box centers saved to {centers_path}")
    # --- Save boxes with scores ---
    boxes_scores_path = "boxes_with_scores.txt"
    np.savetxt(boxes_scores_path, boxes_with_scores, fmt='%.2f', header='x1,y1,x2,y2,score,class', comments='')
    print(f"Boxes with scores saved to {boxes_scores_path}")
    logging.info(f"Boxes with scores saved to {boxes_scores_path}")
    # --- Save original image with boxes ---
    cv2.imwrite("output_full.jpg", im_with_boxes)
    print("Detection completed. Output saved as 'output_full.jpg'")
    logging.info("Detection completed. Output saved as 'output_full.jpg'")


if __name__ == "__main__":
    main()
