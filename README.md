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

** source yolo_venv/bin/activate **

# Fix common broken environment issues
pip uninstall -y opencv-python
pip install --no-cache-dir numpy==1.26.4
python -c "import numpy as np; print(np.__version__)"

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
pip uninstall -y opencv-python
pip install --no-cache-dir numpy==1.26.4

Verify:

python -c "import numpy; print(numpy.__version__)"

# Confirm the full stack has compatible packages
python - <<'PY'
import numpy as np
import scipy
import sklearn
print('numpy', np.__version__)
print('scipy', scipy.__version__)
print('sklearn', sklearn.__version__)
PY

🧠 Install Torch + Torchvision (Matching Pair)

From Ultralytics Jetson guide:
https://docs.ultralytics.com/guides/nvidia-jetson/

pip install \
https://github.com/ultralytics/assets/releases/download/v0.0.0/torch-2.5.0a0+872d972e41.nv24.08-cp310-cp310-linux_aarch64.whl

pip install \
https://github.com/ultralytics/assets/releases/download/v0.0.0/torchvision-0.20.0a0+afc54f7-cp310-cp310-linux_aarch64.whl

If CUDA later reports a driver mismatch such as `found version 12060` with
`torch 2.12.0+cu130`, pip has replaced the Jetson wheel with a generic PyTorch
wheel. Repair it with:

pip install --no-cache-dir --force-reinstall --no-deps \
https://github.com/ultralytics/assets/releases/download/v0.0.0/torch-2.5.0a0+872d972e41.nv24.08-cp310-cp310-linux_aarch64.whl \
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

pip install -r requirements.txt
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

---
### system check
source yolo_venv/bin/activate
python backend/hk_full_app_check.py

### 🔥 Full Hair Removal Control App (`hk_full_app`)

Complete hair removal system with laser firing, detection, and automated galvo sequencing:

**Start the server:**
```bash
source yolo_venv/bin/activate
uvicorn backend.hk_backend_app:app --reload
```

**Open in browser:** `http://localhost:8000`

**API base for external frontends:** `http://localhost:8000/api`

**Serve standalone HTML frontends:**
```bash
bash setup_scripts/start_frontends.sh
```

**Features:**

**Detection & Galvo:**
- Live detection overlay with configurable confidence slider
- Capture follicles from current frame into a point list
- Auto-walk: move galvo through detected points in optimized order (nearest-neighbor TSP)
- Visual crosshair on target position during walking

**Laser Safety & Control:**
- ARM/DISARM laser with hardware checks
- Acknowledge errors
- Select active wavelengths (1064, 980, 808, 660 nm)
- Set laser current (power %, 1-100)
- Set pulse duration (1-1000 ms)

**Sequence & Firing:**
- Configure sequence length (1-256 points)
- Set target coordinates per point
- START_SEQ (live firing with hardware checks)
- START_SEQ_TEST (test mode, no safety checks)
- HALT, RESUME, STOP sequence controls

**🔥 Fire Hair Removal Workflow:**
1. Set all laser parameters (active lasers, current, pulse)
2. Capture detection points from video
3. Click **Fire TEST** to dry-run the sequence
4. Click **Fire LIVE** (with confirmation) to actually fire at all detected points:
   - Auto-transforms image coords to galvo coords via homography
   - Auto-sets target points in firmware sequence
   - Auto-configures sequence length
   - Fires the sequence

**Serial Protocol:** Communicates with hardware via `/dev/ttyACM0` at 115200 baud using commands from `README_serial.md`.

Requires: `transformation_matrix.txt` from prior calibration.

---

🔌 Serial Port Support
pip install pyserial

ls -l /dev/ttyUSB* /dev/ttyACM* /dev/ttyTHS* 2>/dev/null || true

🧠 Summary of Critical Jetson Rules

Use NVIDIA torch wheels only

Torch and torchvision must match

NumPy must be 1.26.x (not 2.x)

Use apt OpenCV

Avoid ultralytics[export] unless necessary

## RUN backend as a service

## Backend (Hairkiller)

The backend is a FastAPI/uvicorn service managed by systemd. The service file is at `deploy/hairkiller-backend.service`.

```bash
# Install (first time)
sudo cp deploy/hairkiller-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable hairkiller-backend

# Start / Stop / Restart
sudo systemctl start hairkiller-backend
sudo systemctl stop hairkiller-backend
sudo systemctl restart hairkiller-backend

# Status & logs
sudo systemctl status hairkiller-backend
sudo journalctl -u hairkiller-backend -f
```

### Serial Port Setup

To access the laser device on `/dev/ttyACM0`, run the setup script from the hairkiller project:

```bash
cd /home/jetson/Projects/hairkiller/setup_scripts
./setup_serial.sh
```

This script:
- Changes ownership of the STM32 Virtual ComPort device to the current user
- Adds the user to the `dialout` group for serial port access
- Sets proper permissions (660) on `/dev/ttyACM0`

**Note:** You may need to log out and log back in for group changes to take effect.

## Mock Services

All backend interactions are mocked:
- **Authentication**: Simulated Supabase auth
- **Hardware Control**: Simulated Python backend communication
- **Settings Persistence**: Local state only
- **Connection Monitoring**: Simulated heartbeat/ping
