🚀 Hairkiller – Jetson Orin Nano Setup Guide

Tested on:

Jetson Orin Nano

JetPack 6.x

Python 3.10

CUDA 12.6

torch 2.5.0a0+nv24.08

📷 Camera Setup
Install camera utils
sudo apt update
sudo apt install -y v4l-utils
List devices
v4l2-ctl --list-devices
v4l2-ctl --list-formats-ext
v4l2-ctl --all -d /dev/video0
Test camera (GStreamer HW accelerated)
gst-launch-1.0 v4l2src device=/dev/video0 io-mode=2 ! \
image/jpeg, width=2592, height=1944, framerate=10/1 ! \
nvv4l2decoder mjpeg=1 ! \
nvvidconv ! nveglglessink
🔐 hairkiller Git Project
Generate SSH key
ssh-keygen
cat ~/.ssh/id_rsa.pub

Add the public key to GitHub.

🐍 Python Environment Setup
Install venv support
sudo apt install -y python3.10-venv python3-opencv

⚠ IMPORTANT: We use apt OpenCV, NOT pip opencv-python on Jetson.

Create virtual environment (keep system packages!)
python3 -m venv --system-site-packages yolo_venv
source yolo_venv/bin/activate
Test OpenCV
python -c "import cv2; print(cv2.__version__)"
🔥 Install NVIDIA PyTorch (JetPack 6.x)

From:
https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform/index.html

System dependencies
sudo apt-get update
sudo apt-get install -y python3-pip libopenblas-dev
Install cuSPARSELt (required for torch 2.5)
cd /tmp
CUSP_VER="0.7.1.0"
CUSP_NAME="libcusparse_lt-linux-aarch64-${CUSP_VER}-archive"

wget -O "${CUSP_NAME}.tar.xz" \
"https://developer.download.nvidia.com/compute/cusparselt/redist/libcusparse_lt/linux-aarch64/${CUSP_NAME}.tar.xz"

tar -xf "${CUSP_NAME}.tar.xz"
cd ${CUSP_NAME}
sudo cp -a include/* /usr/local/cuda/include/
sudo cp -a lib/* /usr/local/cuda/lib64/
📌 CRITICAL: NumPy Version Pin

⚠ Jetson PyTorch wheels are compiled against NumPy 1.x ABI.

DO NOT USE NumPy 2.x.

pip install --upgrade pip
pip install --no-cache-dir numpy==1.26.4

Verify:

python -c "import numpy; print(numpy.__version__)"
🧠 Install Torch + Torchvision (Matching Pair)

From Ultralytics Jetson guide:
https://docs.ultralytics.com/guides/nvidia-jetson/

pip install \
https://github.com/ultralytics/assets/releases/download/v0.0.0/torch-2.5.0a0+872d972e41.nv24.08-cp310-cp310-linux_aarch64.whl

pip install \
https://github.com/ultralytics/assets/releases/download/v0.0.0/torchvision-0.20.0a0+afc54f7-cp310-cp310-linux_aarch64.whl
Verify CUDA + Torch
python - <<'PY'
import torch
print("torch:", torch.__version__)
print("cuda available:", torch.cuda.is_available())
print("torch cuda:", torch.version.cuda)
if torch.cuda.is_available():
    print("gpu:", torch.cuda.get_device_name(0))
PY
🤖 Install Ultralytics (Lightweight Mode)

⚠ DO NOT use [export] on Jetson unless required.

pip install ultralytics
pip install psutil polars ultralytics-thop
❌ DO NOT INSTALL

Do NOT run:

pip install ultralytics[export]
pip install opencv-python
pip install numpy>=2

These break Jetson compatibility.

✅ Verify Full Stack
python - <<'PY'
import numpy as np
import torch
from ultralytics import YOLO

print("numpy:", np.__version__)
print("torch:", torch.__version__)
print("cuda:", torch.cuda.is_available())

x = np.zeros((2,2), dtype=np.float32)
t = torch.from_numpy(x)
print("torch.from_numpy OK:", t.shape)

print("Ultralytics import OK")
PY

If this works → environment is correct.

🎥 Run Hairkiller Test
python ./testcode/yolo_test.py

Expected:

Using device: cuda

No NumPy warnings.
No torchvision::nms error.
No "Numpy is not available" error.

🔌 Serial Port Support
pip install pyserial
🧠 Summary of Critical Jetson Rules

Use NVIDIA torch wheels only

Torch and torchvision must match

NumPy must be 1.26.x (not 2.x)

Use apt OpenCV

Avoid ultralytics[export] unless necessary