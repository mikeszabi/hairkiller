import cv2
import numpy as np

"""Simple utility to inspect HSV values of pixels in an image.

Run the script and click on the image window; the HSV value at the clicked
location will be printed to the console and drawn on the image.  This can
help you choose thresholds or debug colour problems.

Usage:
    python code/hsv_inspector.py [--image=path]

Default image is ``images/calibration_test.jpg``.
"""

import argparse

current_hsv = None


def on_mouse(event, x, y, flags, param):
    global current_hsv
    img_bgr, img_hsv = param
    if event == cv2.EVENT_LBUTTONDOWN:
        current_hsv = img_hsv[y, x]
        print(f"Clicked at ({x},{y}) -> HSV {current_hsv}")


def main():
    parser = argparse.ArgumentParser(description="HSV value inspector")
    parser.add_argument("--image", default="images/calibration_test.jpg",
                        help="path to image file")
    args = parser.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        raise FileNotFoundError(f"could not load {args.image}")
    img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    window = "image"
    cv2.namedWindow(window,cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 1280, 720)
    cv2.setMouseCallback(window, on_mouse, (img, img_hsv))

    print("Click on the image to see HSV values. Press 'q' to quit.")
    while True:
        display = img.copy()
        if current_hsv is not None:
            text = f"HSV: {tuple(int(v) for v in current_hsv)}"
            cv2.putText(display, text, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                        0.8, (0,255,0), 2)
        cv2.imshow(window, display)
        if cv2.waitKey(50) & 0xFF == ord('q'):
            break

    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
