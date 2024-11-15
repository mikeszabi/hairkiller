#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Mon Mar  6 22:06:30 2023

@author: itqs
"""

# imports
import cv2
import numpy as np
from matplotlib import pyplot as plt

# Read image
img = cv2.imread(r'../results_output/2023-03-06_22-05-38_left.jpg', cv2.IMREAD_GRAYSCALE)

params = cv2.SimpleBlobDetector_Params()

# Change thresholds
# params.minThreshold = 50;
# params.maxThreshold = 256;

blur = cv2.GaussianBlur(img,(21,21),0)
retval, threshold = cv2.threshold(blur, 100, 255, cv2.THRESH_BINARY_INV)

# params.filterByCircularity = False
# params.minCircularity = 0.2

# params.filterByArea = False;
# params.minArea = 100;

ver = (cv2.__version__).split('.')
if int(ver[0]) < 3 :
    detector = cv2.SimpleBlobDetector(params)
else :
    detector = cv2.SimpleBlobDetector_create(params)


# Detect blobs.
keypoints = detector.detect(threshold)

# Draw detected blobs as red circles.
# cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS ensures the size of the circle corresponds to the size of blob
im_with_keypoints = cv2.drawKeypoints(img, keypoints, np.array([]), (0,0,255), cv2.DRAW_MATCHES_FLAGS_DRAW_RICH_KEYPOINTS)

# Show keypoints
# cv2.imshow("Keypoints", im_with_keypoints)
# cv2.waitKey(0)


kp=keypoints[0].pt

def draw_cross(img,center, color, d):
    cv2.line(img,
             (int(center[0] - d), int(center[1] - d)), (int(center[0] + d), int(center[1] + d)),
             color, 1, cv2.LINE_AA, 0)
    cv2.line(img,
             (int(center[0] + d), int(center[1] - d)), (int(center[0] - d), int(center[1] + d)),
             color, 1, cv2.LINE_AA, 0) 

draw_cross(im_with_keypoints,kp,1,10)

plt.imshow(im_with_keypoints)
