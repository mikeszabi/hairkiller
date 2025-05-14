import cv2
import torch
import numpy as np
from ultralytics import YOLO

def split_image(image, tile_size=640):
    """Split the image into 640x640 tiles."""
    h, w = image.shape[:2]
    tiles = []
    coords = []

    for y in range(0, h, tile_size):
        for x in range(0, w, tile_size):
            tile = image[y:min(y + tile_size, h), x:min(x + tile_size, w)]
            tiles.append(tile)
            coords.append((x, y))
    return tiles, coords

def merge_predictions(predictions, original_shape, grid_size=(4, 3)):
    """Merge predictions back to original image size"""
    h, w = original_shape[:2]
    grid_h, grid_w = grid_size
    tile_h, tile_w = h / grid_h, w / grid_w  # Ensure floating point division for accuracy
    
    all_boxes, all_scores, all_classes = [], [], []
    
    for idx, pred in enumerate(predictions):
        if len(pred.boxes) == 0:
            continue
        
        # Fix row/column index computation
        grid_y, grid_x = divmod(idx, grid_w)  # This ensures correct (row, column) mapping
        offset_x = int(grid_x * tile_w)  # Convert float tile size to int for pixel coordinates
        offset_y = int(grid_y * tile_h)

        # Scale factor for mapping 640x640 detection back to tile size
        scale_x, scale_y = tile_w / 640, tile_h / 640
        
        # Convert box coordinates to the original image space
        boxes = pred.boxes.xyxy.cpu().numpy()
        boxes[:, [0, 2]] = boxes[:, [0, 2]] * scale_x + offset_x
        boxes[:, [1, 3]] = boxes[:, [1, 3]] * scale_y + offset_y
        
        all_boxes.extend(boxes)
        all_scores.extend(pred.boxes.conf.cpu().numpy())
        all_classes.extend(pred.boxes.cls.cpu().numpy())
    
    return np.array(all_boxes), np.array(all_scores), np.array(all_classes)


def preprocess_tiles(tiles):
    """Resize and convert tiles to torch tensors (BGR->RGB)."""
    tensor_tiles = []
    for tile in tiles:
        tile_resized = cv2.resize(tile, (640, 640))
        tile_rgb = cv2.cvtColor(tile_resized, cv2.COLOR_BGR2RGB)
        tile_tensor = torch.from_numpy(tile_rgb).permute(2, 0, 1).float() / 255.0
        tensor_tiles.append(tile_tensor)
    batch_tensor = torch.stack(tensor_tiles).to("cuda")
    return batch_tensor

def main():
    # --- Load TensorRT YOLO model ---

    engine_path = "./model/follicle_exit_v11i_yolov8n_20250513.engine"

    model = YOLO(engine_path)
    print("Loaded TensorRT model.")

    # --- Load and split full image ---
    image_path = "./images/hair_test_live.jpg"
    image = cv2.imread(image_path)
    if image is None:
        print(f"Error: Could not load image at {image_path}")
        return

    tiles, coords = split_image(image, tile_size=640)
    print(f"Split into {len(tiles)} tiles.")

    # --- Preprocess tiles into batch tensor ---
    tile_batch = preprocess_tiles(tiles)

    # --- Inference in batch ---
    with torch.no_grad():
        results = model(tile_batch, conf=0.2)

    # --- Merge tile predictions back to original image ---
    boxes, scores, classes = merge_predictions(results, image.shape, grid_size=(3, 4))  # vagy 4x3 ha úgy darabolsz

    # --- Draw results on original image ---
    image_annotated = image.copy()
    for box, score, cls in zip(boxes, scores, classes):
        x1, y1, x2, y2 = map(int, box)
        label = f"{int(cls)}: {score:.2f}"
        cv2.rectangle(image_annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(image_annotated, label, (x1, y1 - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    cv2.imwrite("output_full_image.jpg", image_annotated)
    print("Merged detection result saved as output_full_image.jpg")

if __name__ == "__main__":
    main()