import sys
import numpy as np
import cv2
from sklearn.linear_model import LinearRegression
import json
import matplotlib.pyplot as plt


import numpy as np
import cv2

def calculate_homography(image_points, robot_points):
    """
    Calculate the homography matrix to map image points to robot coordinates.
    
    Parameters:
    image_points (np.ndarray): Nx2 array of points in the image coordinate system.
    robot_points (np.ndarray): Nx2 array of corresponding points in the robot coordinate system.
    
    Returns:
    np.ndarray: 3x3 homography matrix.
    """
    image_points = np.array(image_points, dtype=np.float32)
    robot_points = np.array(robot_points, dtype=np.float32)
    
    # Calculate the homography matrix using the DLT algorithm with RANSAC
    H, status = cv2.findHomography(image_points, robot_points, method=cv2.RANSAC)
    return H

def transform_to_robot_coordinates(image_point, homography_matrix):
    """
    Transform a single image point to robot coordinates using the homography matrix.
    
    Parameters:
    image_point (tuple): (x, y) coordinates in the image.
    homography_matrix (np.ndarray): 3x3 homography matrix.
    
    Returns:
    tuple: Transformed (x, y) coordinates in the robot coordinate system.
    """
    point_homogeneous = np.array([image_point[0], image_point[1], 1.0])
    robot_point_homogeneous = homography_matrix @ point_homogeneous
    # Convert from homogeneous to Cartesian coordinates
    robot_point = robot_point_homogeneous[:2] / robot_point_homogeneous[2]
    return tuple(robot_point)


def read_transformation_from_file(filename='transformation_matrix.txt'):
    """Read the transformation matrix from a file."""
    H = np.loadtxt(filename)
    return H

def save_transformation_to_file(H, filename='transformation_matrix.txt'):
    """Save the transformation matrix to a file."""
    np.savetxt(filename, H)

def read_corresponding_points(filename='saved_coordinates.json'):
    """Read the corresponding points from a file."""
    image_points = []
    robot_points = []
    with open(filename, 'r') as f:
        data = json.load(f)
        image_points = [d[0] for d in data]
        robot_points = [d[1][0:2] for d in data]
    return image_points, robot_points

def main():

    # Collect calibration data
    image_points, robot_points = read_corresponding_points(filename='saved_coordinates.json')

    # Plot image points and corresponding robot points
    image_points = np.array(image_points)
    robot_points = np.array(robot_points)

    plt.figure(figsize=(12, 6))

    plt.subplot(1, 2, 1)
    plt.scatter(image_points[:, 0], image_points[:, 1], color='blue', label='Image Points')
    for i, (x, y) in enumerate(image_points):
        plt.text(x, y, str(i), fontsize=9, ha='right')
    plt.xlabel('X')
    plt.ylabel('Y')
    plt.title('Image Points')
    plt.legend()

    plt.subplot(1, 2, 2)
    plt.scatter(robot_points[:, 0], robot_points[:, 1], color='red', label='Robot Points')
    for i, (x, y) in enumerate(robot_points):
        plt.text(x, y, str(i), fontsize=9, ha='right')
    plt.xlabel('X')
    plt.ylabel('Y')
    plt.title('Robot Points')
    plt.legend()

    plt.show()

    H = calculate_homography(image_points, robot_points)

    # Test the homography matrix

    transformed_robot_points = [transform_to_robot_coordinates(pt, H) for pt in image_points]

    original_robot_points = np.array(robot_points)
    transformed_robot_points = np.array(transformed_robot_points)

    plt.scatter(original_robot_points[:, 0], original_robot_points[:, 1], color='blue', label='Original Robot Points')
    plt.scatter(transformed_robot_points[:, 0], transformed_robot_points[:, 1], color='red', label='Transformed Robot Points')
    plt.legend()
    plt.xlabel('X')
    plt.ylabel('Y')
    plt.title('Original vs Transformed Robot Points')
    # Connect corresponding points with lines
    for (orig_pt, trans_pt) in zip(original_robot_points, transformed_robot_points):
        plt.plot([orig_pt[0], trans_pt[0]], [orig_pt[1], trans_pt[1]], 'k--')
    plt.show()

if __name__ == "__main__":
    main()
