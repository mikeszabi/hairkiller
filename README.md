On Jetson Nano Orin

## Install camera utils if not installed
sudo apt install v4l-utils

# v4l2-ctl --list-devices
# v4l2-ctl --list-formats-ext
# v4l2-ctl --all -d /dev/video0

## test camera
gst-launch-1.0 v4l2src device=/dev/video0 io-mode=2 ! \
image/jpeg, width=2592, height=1944, framerate=10/1 ! \
nvv4l2decoder mjpeg=1 ! \
nvvidconv ! nveglglessink

## hairkiller git project
# Generate public key
ssh-keygen
cat /home/digdeep/.ssh/id_rsa.pub

## Setting up python environment
apt install python3.10-venv
python3 -m venv --system-site-packages yolo_venv
source yolo_venv/bin/activate

#python -c "import cv2; print(cv2.__version__)"

# from https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform/index.html

sudo apt-get -y update; 
sudo apt-get install -y  python3-pip libopenblas-dev

cd /tmp
CUSP_VER="0.7.1.0"
CUSP_NAME="libcusparse_lt-linux-aarch64-${CUSP_VER}-archive"

wget -O "${CUSP_NAME}.tar.xz" \
  "https://developer.download.nvidia.com/compute/cusparselt/redist/libcusparse_lt/linux-aarch64/${CUSP_NAME}.tar.xz"

tar -xf "${CUSP_NAME}.tar.xz"

# NVIDIA recommends numpy pin in their install flow
pip install -U pip
pip install "numpy==1.26.1"

# install CUDA-enabled torch wheel (cp310 / aarch64)
pip install --no-cache-dir \
  https://developer.download.nvidia.com/compute/redist/jp/v61/pytorch/torch-2.5.0a0+872d972e41.nv24.08.17622132-cp310-cp310-linux_aarch64.whl

Check:
python - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda available:", torch.cuda.is_available())
print("torch cuda:", torch.version.cuda)
if torch.cuda.is_available():
    print("gpu:", torch.cuda.get_device_name(0))
PY

pip install ultralytics

# Serial port
pip install pyserial

