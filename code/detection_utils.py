import numpy as np
import cv2

def remove_overlapping_boxes(boxes, intersection_threshold=0.01):
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

def calculate_box_center(box):
    x1, y1, x2, y2, _, _ = box
    center = (x1 + x2) / 2, (y1 + y2) / 2
    return center

def get_box_centers(boxes):
    centers = []
    for box in boxes:
        center = calculate_box_center(box)
        centers.append(center)
    return centers

    
def draw_boxes(image, boxes):

    for box in boxes:
        center = calculate_box_center(box)
        x1, y1, x2, y2, _, _ = box
        xyxy = box[:4]
        start_point = (int(x1), int(y1))
        end_point = (int(x2), int(y2))
        color = (0, 0, 255)  # Red color in BGR
        thickness = 2
        image = cv2.rectangle(image, start_point, end_point, color, thickness)
        image = cv2.circle(image, (int(center[0]), int(center[1])), 5, (0, 0, 255), -1)

    return image

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
