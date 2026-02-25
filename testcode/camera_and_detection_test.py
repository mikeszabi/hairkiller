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

# create a resizable window and set desired display size
cv2.namedWindow("UVC Camera Stream with Detection", cv2.WINDOW_NORMAL)
cv2.resizeWindow("UVC Camera Stream with Detection", 640, 640)  # adjust as needed

def main():
    model_path = "./model/follicle_exit_v11i_yolov8n_20250513.pt"
    # Create an object detector
    detector = ObjectDetector(model_path)

    # Testing with camera interface
    uvc = UVCInterface()
    while True:
        im_frame, frame_index = uvc.read()
        if im_frame is None:
            print("Failed to capture frame")
            continue

        # Process the frame (e.g., display it)
        boxes_with_scores=detector.split_inference(im_frame, conf=0.01)
        image_with_boxes = draw_boxes(im_frame.copy(), boxes_with_scores)
        cv2.putText(image_with_boxes, f"Frame index: {frame_index}", (30, 30), cv2.FONT_HERSHEY_SIMPLEX, 5, (255, 255, 255), 10)

        cv2.imshow("UVC Camera Stream with Detection", image_with_boxes)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    uvc.release()

if __name__ == "__main__":
    main()