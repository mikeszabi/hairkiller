import sys
from pathlib import Path
# Add parent directory to path to import from utils
sys.path.append(str(Path(__file__).parent.parent))
import numpy as np
import cv2
from sklearn.linear_model import LinearRegression
import json
import matplotlib.pyplot as plt


import numpy as np
import cv2

def calculate_homography(image_points, mover_points):
    """
    Calculate the homography matrix to map image points to mover coordinates.
    
    Parameters:
    image_points (np.ndarray): Nx2 array of points in the image coordinate system.
    mover_points (np.ndarray): Nx2 array of corresponding points in the mover coordinate system.
    
    Returns:
    np.ndarray: 3x3 homography matrix.
    """
    image_points = np.array(image_points, dtype=np.float32)
    mover_points = np.array(mover_points, dtype=np.float32)
    
    # Calculate the homography matrix using the DLT algorithm with RANSAC
    H, status = cv2.findHomography(image_points, mover_points, method=cv2.RANSAC)
    return H

def transform_to_mover_coordinates(image_point, homography_matrix):
    """
    Transform a single image point to mover coordinates using the homography matrix.
    
    Parameters:
    image_point (tuple): (x, y) coordinates in the image.
    homography_matrix (np.ndarray): 3x3 homography matrix.
    
    Returns:
    tuple: Transformed (x, y) coordinates in the mover coordinate system.
    """
    point_homogeneous = np.array([image_point[0], image_point[1], 1.0])
    mover_point_homogeneous = homography_matrix @ point_homogeneous
    # Convert from homogeneous to Cartesian coordinates
    mover_point = mover_point_homogeneous[:2] / mover_point_homogeneous[2]
    return tuple(mover_point)


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
    mover_points = []
    with open(filename, 'r') as f:
        data = json.load(f)
        image_points = [d[0] for d in data]
        mover_points = [d[1][0:2] for d in data]
    return image_points, mover_points

def main():

    # Collect calibration data
    image_points, mover_points = read_corresponding_points(filename='saved_coordinates.json')

    # Plot image points and corresponding mover points
    image_points = np.array(image_points)
    mover_points = np.array(mover_points)

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
    plt.scatter(mover_points[:, 0], mover_points[:, 1], color='red', label='mover Points')
    for i, (x, y) in enumerate(mover_points):
        plt.text(x, y, str(i), fontsize=9, ha='right')
    plt.xlabel('X')
    plt.ylabel('Y')
    plt.title('mover Points')
    plt.legend()

    plt.show()

    H = calculate_homography(image_points, mover_points)

    # Test the homography matrix

    transformed_mover_points = [transform_to_mover_coordinates(pt, H) for pt in image_points]

    original_mover_points = np.array(mover_points)
    transformed_mover_points = np.array(transformed_mover_points)

    plt.scatter(original_mover_points[:, 0], original_mover_points[:, 1], color='blue', label='Original mover Points')
    plt.scatter(transformed_mover_points[:, 0], transformed_mover_points[:, 1], color='red', label='Transformed mover Points')
    plt.legend()
    plt.xlabel('X')
    plt.ylabel('Y')
    plt.title('Original vs Transformed mover Points')
    # Connect corresponding points with lines
    for (orig_pt, trans_pt) in zip(original_mover_points, transformed_mover_points):
        plt.plot([orig_pt[0], trans_pt[0]], [orig_pt[1], trans_pt[1]], 'k--')
    plt.show()

if __name__ == "__main__":
    main()