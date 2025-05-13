import os
import cv2
import numpy as np
from ultralytics import YOLO
import torch

def split_image(image):
    """Split image into pieces - so each tile have a size of 640x640"""
    original_shape = image.shape

    grid_size = (max(1, original_shape[0] // 640), max(1, original_shape[1] // 640))
    h, w = image.shape[:2]
    grid_h, grid_w = grid_size
    
    # Avoid zero division errors
    if grid_h == 0:
        grid_h = 1
    if grid_w == 0:
        grid_w = 1
    
    # Calculate tile dimensions
    tile_h, tile_w = h // grid_h, w // grid_w
    
    tiles = []
    for i in range(grid_h):
        for j in range(grid_w):
            y1, y2 = i * tile_h, min((i + 1) * tile_h, h)
            x1, x2 = j * tile_w, min((j + 1) * tile_w, w)
            tile = image[y1:y2, x1:x2]
            # Resize tile to model input size
            tile = cv2.resize(tile, (640, 640))
            tiles.append(tile)
    
    return tiles, original_shape, grid_size

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

def main():
    # Load model
    #model_path = r'./model/follicle_exit_v11s_20250301.pt'
    model_path = r"./model/follicle_exit_unsure_v8n_20250404.pt"

    model = YOLO(model_path)
    
    # Load image
    image_path = r"./images/hair_test_live.jpg"

    image = cv2.imread(image_path)
    if image is None:
        print(f"Error: Could not load image at {image_path}")
        return
    
    # # Testing with original image
    # im_np=image.copy()
    # result = model(image_path, conf=0.1)[0]
    # for box in result.boxes.xyxy.cpu().numpy():
    #     x1, y1, x2, y2 = map(int, box)
    #     cv2.rectangle(im_np, (x1, y1), (x2, y2), (0, 255, 0), 2)
    # cv2.imwrite('original_large.jpg', im_np)


    # Split image into grid
    tiles, original_shape, grid_size = split_image(image)
    
    # Run inference on all tiles
    results = []
    with torch.no_grad():
        for tile in tiles:
            # temp_path = '/home/mike/data/hair_raw/temp.jpg'
            # cv2.imwrite(temp_path, tile)
            result = model(tile, conf=0.2)[0]
            results.append(result)
    
    # Merge predictions
    boxes, scores, classes = merge_predictions(results, original_shape, grid_size)
    if len(boxes) >0:
        boxes_with_scores = np.concatenate((boxes, scores[:, None], classes[:,None]), axis=1)
    # Draw predictions on original image
    for box, score, cls in zip(boxes, scores, classes):
        x1, y1, x2, y2 = map(int, box)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2)
        label = f'Class {int(cls)}: {score:.2f}'
        cv2.putText(image, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
    
    # Save result
    cv2.imwrite('output.jpg', image)
    print("Detection completed. Output saved as 'output.jpg'")

if __name__ == '__main__':
    main()