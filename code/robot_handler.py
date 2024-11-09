import logging
import pathlib

import mecademicpy.robot as mdr
import mecademicpy.robot_initializer as initializer
import mecademicpy.tools as tools


class RobotHandler:
        def __init__(self, address='192.168.0.100'):
            self.logger = logging.getLogger(__name__)
            self.robot = initializer.RobotWithTools()
            self.address = address
            self.connect()
            self.handle_errors(None)
            self.activate_and_home()
            self.p_start = self.get_position()

        def connect(self):
            try:
                self.robot.Connect(address=self.address)
            except mdr.CommunicationError as e:
                self.logger.info(f'Robot failed to connect. Is the IP address correct? {e}')
                raise e

        def handle_errors(self, exception):
            if self.robot.GetStatusRobot().error_status:
                self.logger.info(exception)
                self.logger.info('Robot has encountered an error, attempting to clear...')
                self.robot.ResetError()
                self.robot.ResumeMotion()
            else:
                if exception is not None:
                    raise exception
                else:
                    self.logger.info('Robot has no errors...')
            
        def get_robot_info(self):
            return self.robot.GetRobotInfo().robot_model
        
        def is_allowed_to_move(self):
            return self.robot.IsAllowedToMove()
        
        def get_position(self):
            return self.robot.GetPose()
        
        def move_2_pos(self, x, y, z, rx, ry, rz):
            try:
                self.robot.MoveLin(x, y, z, rx, ry, rz)
            except Exception as e:
                self.handle_errors(e)

        def move_rel(self, x, y, z, rx, ry, rz):
            try:
                self.robot.MoveLinRelWrf(x, y, z, rx, ry, rz)
            except Exception as e:
                self.handle_errors(e)

        def activate_and_home(self):
            try:
                self.logger.info('Activating and homing robot...')
                initializer.reset_motion_queue(self.robot, activate_home=True)
                self.robot.WaitHomed()
                self.logger.info('Robot is homed and ready.')
            except Exception as e:
                self.handle_errors(e)

        def deactivate(self):
            self.robot.DeactivateRobot()
            self.logger.info('Robot is deactivated.')

        def disconnet(self):
            self.robot.Disconnect()
            self.logger.info('Robot is disconnected.')

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            self.disconnet

def main():
    logging.basicConfig(level=logging.INFO)
    robot = RobotHandler()

    print(robot.is_allowed_to_move())
    robot.handle_errors(None)
    robot.move_rel(20, 0, 0, 0, 0, 0)
    #robot.move_rel(+10, 0, 0, 0, 0, 0)
    p_actual = robot.get_position()
    x, y, z, rx, ry, rz = robot.p_start
    robot.move_2_pos(x, y, z, rx, ry, rz )
    robot.deactivate()
    robot.disconnet()

if __name__ == '__main__':
    main()