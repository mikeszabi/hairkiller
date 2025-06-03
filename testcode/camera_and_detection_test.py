import sys
from pathlib import Path
# Add parent directory to path to import from utils
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent.parent / "code"))
import time
import cv2
from detection_utils import remove_overlapping_boxes, calculate_box_center, get_box_centers, draw_boxes, split_image, merge_predictions
from camera_handler import UVCInterface
from detection_handler import ObjectDetector

def main():
    model_path = "./model/follicle_exit_v11i_yolov8n_20250513.pt"
    # Create an object detector
    detector = ObjectDetector(model_path)

    # Testing with camera interface
    uvc = UVCInterface()
    uvc.set_resolution(2560, 1920)
    while True:
        im_frame, frame_index = uvc.read_frame()
        if im_frame is None:
            print("Failed to capture frame")
            continue

        # Process the frame (e.g., display it)
        boxes_with_scores=detector.split_inference(im_frame, conf=0.1)
        image_with_boxes = draw_boxes(im_frame.copy(), boxes_with_scores)
        image_with_boxes=cv2.resize(image_with_boxes, (1280, 1024), image_with_boxes, interpolation=cv2.INTER_LINEAR)
        cv2.putText(image_with_boxes, f"Frame index: {frame_index}", (30, 30), cv2.FONT_HERSHEY_SIMPLEX, 5, (255, 255, 255), 10)

        cv2.imshow("Frame", image_with_boxes)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    uvc.release()

if __name__ == "__main__":
    main()