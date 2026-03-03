import cv2
import numpy as np

"""Simple OpenCV utility to find the centre of a red dot in an image.
Place this file in the workspace and run with the working directory set to the
project root (where images/ lives).

Usage:
    python code/red_dot_detector.py

The script loads `images/calibration_test.jpg`, thresholds for red in HSV,
finds the largest red contour and reports its centre coordinates.
"""

# load image
img = cv2.imread("images/calibration_test.jpg")
if img is None:
    raise FileNotFoundError("could not load images/calibration_test.jpg")

# convert to HSV so we can threshold on hue
hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
# build mask that keeps only the central 30% of the frame
h, w = img.shape[:2]
cw = int(w * 0.3)
ch = int(h * 0.3)
cx, cy = w // 2, h // 2
region_mask = np.zeros((h, w), dtype=np.uint8)
region_mask[cy - ch//2:cy + ch//2, cx - cw//2:cx + cw//2] = 255
# two ranges to cover red wrap-around at 180
lower_red1 = np.array([45, 10, 180])
upper_red1 = np.array([70, 30, 255])

# lower_red2 = np.array([160, 100, 100])
# upper_red2 = np.array([180, 255, 255])

mask = cv2.inRange(hsv, lower_red1, upper_red1)
#mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
#mask = cv2.bitwise_or(mask1, mask2)
# restrict to central region
mask = cv2.bitwise_and(mask, region_mask)
# optional cleanup
mask = cv2.medianBlur(mask, 5)

contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

if len(contours) == 0:
    print("No red blob detected")
    center = None
else:
    # pick the largest contour, assuming it's the dot
    c = max(contours, key=cv2.contourArea)
    (x, y), radius = cv2.minEnclosingCircle(c)
    center = (int(x), int(y))
    print(f"Detected red dot centre: {center}, radius {radius:.1f}")

    # draw for visual confirmation
    cv2.circle(img, center, int(radius), (0, 255, 0), 2)
    cv2.circle(img, center, 2, (255, 0, 0), -1)

    cv2.imshow("mask", mask)
    cv2.imshow("result", img)
    cv2.waitKey(0)
    cv2.destroyAllWindows()
