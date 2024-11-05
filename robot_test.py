import time
import mecademicpy.robot as mdr

# Initialize the robot instance
robot = mdr.Robot()
robot_ip = "192.168.0.100"  # Replace with your robot's IP address


# Connect to the robot
robot.Connect()
print("Connected in control mode.")
robot.ResetError()  # Clear any errors
robot.ResumeMotion()  # Resume motion if it was halted
# Activate and home the robot
response = robot.ActivateRobot()
if not response:
    print("Failed to activate robot.")
robot.WaitHomed()


robot.GetPose()

x, y, z = 1, 1, 0
response = robot.MoveLinRelWRF
if not response:
    print(f"Failed to move to ({x}, {y}, {z})")
    # Define the height (z-axis) for the horizontal plane
z_plane = 300  # Set the height of the plane (adjust as needed)

# Example coordinates in the horizontal plane
points = [
    (200, 0, z_plane),   # Point 1
    (250, 50, z_plane),  # Point 2
    (200, 100, z_plane), # Point 3
    (150, 50, z_plane),  # Point 4
    (200, 0, z_plane)    # Back to Point 1
]

# Move the robot to each point in the plane
for (x, y, z) in points:
    robot.MoveLin(x, y, z, 0, 180, 0)  # rx, ry, rz are fixed for orientation
    robot.WaitIdle()  # Wait for each movement to complete
    time.sleep(1)     # Optional: wait between moves for visibility



# Deactivate and disconnect from the robot
robot.DeactivateRobot()
robot.Disconnect()