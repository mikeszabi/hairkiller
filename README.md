On Jetson Nano Orin

## Install camera utils if not installed
sudo apt install v4l-utils

# v4l2-ctl --list-devices
# v4l2-ctl --list-formats-ext
# v4l2-ctl --all -d /dev/video0

## test camera
gst-launch-1.0 v4l2src device=/dev/video0 io-mode=2 ! \
image/jpeg, width=1920, height=1080, framerate=30/1 ! \
nvv4l2decoder mjpeg=1 ! \
nvvidconv ! nveglglessink

## hairkiller git project
# Generate public key
ssh-keygen
cat /home/digdeep/.ssh/id_rsa.pub

## Setting up python environment
apt install python3.10-venv
python3 -m venv yolo_env
source yolo_env/bin/activate

# from https://pypi.jetson-ai-lab.dev/jp6/cu126

pip install torch-2.7.0-cp310-cp310-linux_aarch64.whl -y
pip install torchvision-0.22.0-cp310-cp310-linux_aarch64.whl
pip install --upgrade numpy==1.26.4
pip install ultralytics

ln -s /usr/lib/python3.10/dist-packages/tensorrt ~/Projects/hairkiller/yolo_env/lib/python3.10/site-packages/tensorrt
