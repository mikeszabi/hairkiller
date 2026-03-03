import cv2
import numpy as np

"""Interactive red-dot finder with adjustable HSV parameters.

This utility opens an image (defaulting to `images/calibration_test.jpg`) and
shows two windows:

* ``mask``: binary result of thresholding using HSV bounds
* ``result``: original image with detected dot centre drawn

Trackbars allow you to tweak the lower/upper HSV ranges; the current
parameters are printed when you exit. This is handy for choosing optional
threshold parameters.

Usage examples:

    python code/red_dot_detector_interactive.py           # use defaults
    python code/red_dot_detector_interactive.py --image=foo.jpg

Press ``q`` in any window to quit and display the final parameters.
"""

import argparse

# ---------------------------------------------------------------------------
# helpers

def nothing(x):
    pass


def create_hsv_trackbars(window):
    cv2.createTrackbar("LH", window, 0, 179, nothing)
    cv2.createTrackbar("LS", window, 0, 255, nothing)
    cv2.createTrackbar("LV", window, 0, 255, nothing)
    cv2.createTrackbar("UH", window, 179, 179, nothing)
    cv2.createTrackbar("US", window, 255, 255, nothing)
    cv2.createTrackbar("UV", window, 255, 255, nothing)


def get_hsv_bounds(window):
    lh = cv2.getTrackbarPos("LH", window)
    ls = cv2.getTrackbarPos("LS", window)
    lv = cv2.getTrackbarPos("LV", window)
    uh = cv2.getTrackbarPos("UH", window)
    us = cv2.getTrackbarPos("US", window)
    uv = cv2.getTrackbarPos("UV", window)
    return (lh, ls, lv), (uh, us, uv)

# ---------------------------------------------------------------------------
# main logic

def main():
    parser = argparse.ArgumentParser(description="Interactive red dot detector")
    parser.add_argument("--image", default="images/calibration_test.jpg",
                        help="path to image file")
    args = parser.parse_args()

    img = cv2.imread(args.image)
    if img is None:
        raise FileNotFoundError(f"could not load {args.image}")

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # create resizable windows so the user can enlarge as needed
    cv2.namedWindow("mask", cv2.WINDOW_NORMAL)
    cv2.namedWindow("result", cv2.WINDOW_NORMAL)
    # set a reasonable default size
    cv2.resizeWindow("mask", 640, 360)
    cv2.resizeWindow("result", 640, 360)

    create_hsv_trackbars("mask")

    print("Use the trackbars to adjust HSV thresholds. Press 'q' to quit.")
    final_lower = None
    final_upper = None

    while True:
        lower, upper = get_hsv_bounds("mask")
        lower_np = np.array(lower)
        upper_np = np.array(upper)
        mask = cv2.inRange(hsv, lower_np, upper_np)
        mask = cv2.medianBlur(mask, 5)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_SIMPLE)
        display = img.copy()
        if contours:
            c = max(contours, key=cv2.contourArea)
            (x, y), radius = cv2.minEnclosingCircle(c)
            center = (int(x), int(y))
            cv2.circle(display, center, int(radius), (0, 255, 0), 2)
            cv2.circle(display, center, 2, (255, 0, 0), -1)
            cv2.putText(display, f"{center}", (center[0]+5, center[1]-5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
        
        # show windows (resizable by user)
        cv2.imshow("mask", mask)
        cv2.imshow("result", display)

        key = cv2.waitKey(50) & 0xFF
        if key == ord('q'):
            final_lower = lower
            final_upper = upper
            break

    cv2.destroyAllWindows()
    print(f"Final HSV lower: {final_lower}, upper: {final_upper}")


if __name__ == "__main__":
    main()
