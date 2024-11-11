import sys
import numpy as np

from sklearn.linear_model import LinearRegression
import json
import matplotlib.pyplot as plt


def compute_transformation(image_points, robot_points):
    """Compute a transformation matrix between image and robot coordinates."""
    A = []
    B = []
    
    for (u, v), (x, y) in zip(image_points, robot_points):
        A.append([u, v, 1, 0, 0, 0])
        A.append([0, 0, 0, u, v, 1])
        B.append(x)
        B.append(y)
    
    A = np.array(A)
    B = np.array(B)
    
    # Solve for transformation matrix
    T = np.linalg.lstsq(A, B, rcond=None)[0]
    # Save the transformation matrix to a file
    np.savetxt('transformation_matrix.txt', T)
    return T.reshape(2, 3)

def apply_transformation(T, image_point):
    """Apply the transformation matrix to convert image coordinates to robot coordinates."""
    u, v = image_point
    x = T[0, 0] * u + T[0, 1] * v + T[0, 2]
    y = T[1, 0] * u + T[1, 1] * v + T[1, 2]
    return x, y

def read_transformation_from_file(filename='transformation_matrix.txt'):
    """Read the transformation matrix from a file."""
    T = np.loadtxt(filename)
    return T.reshape(2, 3)

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

    T = compute_transformation(image_points, robot_points)

    T = read_transformation_from_file(filename='transformation_matrix.txt')

    test_robot_points = apply_transformation(T, image_points[0])


    print("Transformation matrix:", T)
    

if __name__ == "__main__":
    main()
