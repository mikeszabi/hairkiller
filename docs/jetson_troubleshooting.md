# Jetson Troubleshooting Runbook

Quick command checklist for the Hairkiller Jetson when something does not start,
the USB SSH link is down, the camera is missing, the microcontroller does not
respond, or a service looks unhealthy.

## 0. Basic System State

```bash
hostname
date
uptime
whoami
pwd
uname -a
cat /etc/nv_tegra_release
df -h
free -h
top
```

Jetson-specific monitor:

```bash
tegrastats
```

Recent CPU/GPU/USB/kernel warnings:

```bash
dmesg -T | tail -100
journalctl -p warning..alert -n 100
```

## 1. USB SSH Connection

For Jetson USB device mode, the common address from the host machine is:

```bash
ssh jetson@192.168.55.1
```

If that does not work, run on the host machine:

```bash
ping 192.168.55.1
ip addr
ip route
nmcli device status
lsusb
dmesg -T | tail -80
```

On the Jetson, if you have another way in:

```bash
ip addr
ip route
nmcli connection show
systemctl status ssh
sudo systemctl restart ssh
ss -ltnp | grep ':22'
```

SSH key and permission checks:

```bash
ls -la ~/.ssh
cat ~/.ssh/authorized_keys
ssh -v jetson@192.168.55.1
```

USB gadget / RNDIS related checks on the Jetson:

```bash
dmesg -T | grep -iE 'usb|gadget|rndis|cdc|ether'
ls /sys/class/net
```

## 2. Network And Backend Access

IP addresses:

```bash
hostname -I
ip addr
```

Listening ports:

```bash
ss -ltnp
ss -ltnp | grep -E ':22|:8000|:8080'
```

Local backend checks:

```bash
curl -v http://127.0.0.1:8000/api/diagnostics/full_app_check
curl -v http://127.0.0.1:8000/
```

Local nginx frontend check:

```bash
curl -v http://127.0.0.1:8080/
```

From another machine, replace `JETSON_IP` with the Jetson address:

```bash
curl -v http://JETSON_IP:8080/
curl -v http://JETSON_IP:8000/api/diagnostics/full_app_check
```

## 3. Service Status

Hairkiller backend:

```bash
systemctl status hairkiller-backend
journalctl -u hairkiller-backend -n 200 --no-pager
journalctl -u hairkiller-backend -f
sudo systemctl restart hairkiller-backend
sudo systemctl stop hairkiller-backend
sudo systemctl start hairkiller-backend
```

Nginx frontend:

```bash
systemctl status nginx
sudo nginx -t
journalctl -u nginx -n 100 --no-pager
sudo systemctl reload nginx
sudo systemctl restart nginx
```

Installed service files and symlinks:

```bash
ls -la /etc/systemd/system/hairkiller-backend.service
ls -la /etc/nginx/sites-available/test-frontend
ls -la /etc/nginx/sites-enabled/test-frontend
ls -la /var/www/test-frontend
```

After editing a systemd service file:

```bash
sudo systemctl daemon-reload
sudo systemctl enable hairkiller-backend
sudo systemctl restart hairkiller-backend
```

## 4. Camera Checks

List video devices:

```bash
v4l2-ctl --list-devices
ls -la /dev/video*
dmesg -T | grep -iE 'video|camera|uvc|v4l2|csi'
```

Camera capabilities:

```bash
v4l2-ctl --all -d /dev/video0
v4l2-ctl --list-formats-ext -d /dev/video0
```

GStreamer test for a USB MJPEG camera:

```bash
gst-launch-1.0 v4l2src device=/dev/video0 io-mode=2 ! \
image/jpeg,width=2592,height=1944,framerate=10/1 ! \
nvv4l2decoder mjpeg=1 ! nvvidconv ! nveglglessink
```

If the output says `Device '/dev/video0' is busy`, another process already has
the camera open. The later `not-negotiated` error is usually only a consequence
of that first failure.

```bash
sudo lsof /dev/video0
sudo fuser -v /dev/video0
systemctl status hairkiller-backend
sudo systemctl stop hairkiller-backend
sudo lsof /dev/video0
```

After the process releases the camera, retry the GStreamer command. If the
backend was stopped only for the camera test, start it again afterwards:

```bash
sudo systemctl start hairkiller-backend
```

If no process is shown but the camera still looks busy, unplug/replug the USB
camera, then check the kernel log:

```bash
dmesg -T | tail -100
v4l2-ctl --list-devices
```

If the output says `Failed to allocate required memory` or `Buffer pool
activation failed`, test the camera in smaller pieces. First verify that V4L2 can
read frames without opening a preview window:

```bash
gst-launch-1.0 -v v4l2src device=/dev/video0 num-buffers=60 ! \
image/jpeg,width=2592,height=1944,framerate=10/1 ! fakesink
```

If this `fakesink` command also fails, the failure is already at the
camera/V4L2 buffer level. Try lower bandwidth modes:

```bash
gst-launch-1.0 -v v4l2src device=/dev/video0 num-buffers=60 ! \
image/jpeg,width=1280,height=720,framerate=30/1 ! fakesink

gst-launch-1.0 -v v4l2src device=/dev/video0 num-buffers=60 ! \
image/jpeg,width=640,height=480,framerate=30/1 ! fakesink
```

Then test with `v4l2-ctl`, bypassing GStreamer:

```bash
v4l2-ctl -d /dev/video0 --set-fmt-video=width=2592,height=1944,pixelformat=MJPG --stream-mmap --stream-count=60 --stream-to=/tmp/camera.mjpg
v4l2-ctl -d /dev/video0 --set-fmt-video=width=1280,height=720,pixelformat=MJPG --stream-mmap --stream-count=60 --stream-to=/tmp/camera_720p.mjpg
ls -lh /tmp/camera*.mjpg
```

Also try the GStreamer read/write I/O path instead of mmap:

```bash
gst-launch-1.0 -v v4l2src device=/dev/video0 io-mode=1 num-buffers=60 ! \
image/jpeg,width=1280,height=720,framerate=30/1 ! fakesink
```

If only high-resolution modes fail, suspect USB bandwidth, cable, hub, or camera
power. Plug the camera directly into the Jetson, avoid passive hubs, and check:

```bash
lsusb -t
dmesg -T | tail -150
```

If raw `fakesink` capture works at a lower resolution, try preview again at that
lower resolution. This separates camera/USB problems from decoder/display
problems:

```bash
gst-launch-1.0 -v v4l2src device=/dev/video0 ! \
image/jpeg,width=1280,height=720,framerate=30/1 ! \
nvv4l2decoder mjpeg=1 ! nvvidconv ! nveglglessink
```

If the NVIDIA decoder path fails but raw capture works, try the software JPEG
decoder:

```bash
gst-launch-1.0 -v v4l2src device=/dev/video0 ! \
image/jpeg,width=1280,height=720,framerate=30/1 ! \
jpegdec ! videoconvert ! autovideosink
```

If running over SSH or without a local desktop session, avoid the EGL preview
sink and test with `fakesink` first. The `libEGL warning: DRI...` lines are often
display/authentication warnings, not the root camera failure.

If there is no display or you are testing over SSH, save a frame:

```bash
v4l2-ctl -d /dev/video0 --stream-mmap --stream-count=1 --stream-to=/tmp/camera.raw
ls -lh /tmp/camera.raw
```

OpenCV/Python import and camera-open test:

```bash
source yolo_venv/bin/activate
python - <<'PY'
import cv2
print('opencv', cv2.__version__)
cap = cv2.VideoCapture(0)
print('opened', cap.isOpened())
ok, frame = cap.read()
print('frame', ok, None if frame is None else frame.shape)
cap.release()
PY
```

Hairkiller camera tests:

```bash
source yolo_venv/bin/activate
python testcode/camera_test.py
python testcode/camera_and_detection_test.py
python backend/hk_full_app_check.py
python backend/hk_full_app_check.py --allow-hardware-open
```

## 5. Microcontroller / Serial Checks

USB and serial devices:

```bash
lsusb
ls -la /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
ls -la /dev/serial/by-id/ 2>/dev/null
dmesg -T | grep -iE 'ttyACM|ttyUSB|cdc_acm|stm|serial|usb'
```

Expected STM32 by-id path used by this project:

```bash
ls -la /dev/serial/by-id/usb-STMicroelectronics_STM32_Virtual_ComPort_024731423034-if00
```

Permissions:

```bash
stat -c '%A %U %G %n' /dev/ttyACM0
groups
sudo usermod -a -G dialout "$USER"
sudo chmod 660 /dev/ttyACM0
```

Note: after adding a user to a group, log out and back in, or start a new login shell.

If `/dev/ttyACM0` disappears, rebind the USB device:

```bash
bash setup_scripts/rebind_ttyacm0.sh
```

Serial REPL / hardware tests:

```bash
source yolo_venv/bin/activate
python testcode/serial_repl.py
python testcode/galvo_tester.py
```

Firmware command names use underscores, for example `APP_PING`. The REPL also
accepts the space-separated form `APP PING` and converts it before sending. If a
raw serial tool returns `UNK`, retry with the exact underscore command:

```bash
APP_PING
TARGET_SET_POS 1500 2000
```

If another process is holding the serial port:

```bash
sudo lsof /dev/ttyACM0
sudo fuser -v /dev/ttyACM0
systemctl status hairkiller-backend
```

## 6. Python, CUDA, YOLO Stack

Virtualenv:

```bash
source yolo_venv/bin/activate
which python
python --version
pip list | grep -E 'numpy|torch|torchvision|ultralytics|opencv'
```

NumPy/OpenCV/Torch quick check:

```bash
python - <<'PY'
import numpy as np
import cv2
import torch
print('numpy', np.__version__)
print('opencv', cv2.__version__)
print('torch', torch.__version__)
print('torch cuda', torch.version.cuda)
print('cuda available', torch.cuda.is_available())
if torch.cuda.is_available():
    print('gpu', torch.cuda.get_device_name(0))
PY
```

YOLO import:

```bash
python - <<'PY'
from ultralytics import YOLO
print('Ultralytics import OK')
PY
```

Full project check:

```bash
python backend/hk_full_app_check.py
curl http://127.0.0.1:8000/api/diagnostics/full_app_check
```

## 7. Nginx / Frontend Deploy Checks

Copy frontend files from the project:

```bash
sudo cp -r app/* /var/www/test-frontend
sudo cp deploy/test-frontend.nginx /etc/nginx/sites-available/test-frontend
sudo ln -s /etc/nginx/sites-available/test-frontend /etc/nginx/sites-enabled/test-frontend
sudo nginx -t
sudo systemctl reload nginx
```

Files:

```bash
ls -la /var/www/test-frontend
ls -la /etc/nginx/sites-available/test-frontend
ls -la /etc/nginx/sites-enabled/test-frontend
```

Smoke test:

```bash
curl -I http://127.0.0.1:8080/
curl http://127.0.0.1:8080/
```

## 8. Common Troubleshooting Patterns

Backend does not start:

```bash
systemctl status hairkiller-backend
journalctl -u hairkiller-backend -n 200 --no-pager
source yolo_venv/bin/activate
uvicorn backend.hk_backend_app:app --host 127.0.0.1 --port 8000
```

Port already in use:

```bash
ss -ltnp | grep ':8000'
sudo lsof -i :8000
```

Camera busy or cannot open:

```bash
sudo lsof /dev/video0
v4l2-ctl --all -d /dev/video0
journalctl -u hairkiller-backend -n 100 --no-pager
```

Microcontroller does not respond:

```bash
ls -la /dev/ttyACM0 /dev/serial/by-id/ 2>/dev/null
dmesg -T | tail -100
sudo lsof /dev/ttyACM0
bash setup_scripts/rebind_ttyacm0.sh
```

No web UI:

```bash
systemctl status nginx
sudo nginx -t
ss -ltnp | grep ':8080'
curl -I http://127.0.0.1:8080/
```

No API:

```bash
systemctl status hairkiller-backend
ss -ltnp | grep ':8000'
curl -v http://127.0.0.1:8000/api/diagnostics/full_app_check
```

## 9. Useful Logs For Bug Reports

```bash
mkdir -p /tmp/hairkiller-debug
date > /tmp/hairkiller-debug/date.txt
uname -a > /tmp/hairkiller-debug/uname.txt
ip addr > /tmp/hairkiller-debug/ip_addr.txt
ss -ltnp > /tmp/hairkiller-debug/listening_ports.txt
dmesg -T | tail -300 > /tmp/hairkiller-debug/dmesg_tail.txt
journalctl -u hairkiller-backend -n 300 --no-pager > /tmp/hairkiller-debug/hairkiller-backend.log
journalctl -u nginx -n 200 --no-pager > /tmp/hairkiller-debug/nginx.log
ls -la /dev/video* /dev/ttyACM* /dev/ttyUSB* /dev/serial/by-id/ > /tmp/hairkiller-debug/devices.txt 2>&1
tar -czf /tmp/hairkiller-debug.tar.gz -C /tmp hairkiller-debug
ls -lh /tmp/hairkiller-debug.tar.gz
```
