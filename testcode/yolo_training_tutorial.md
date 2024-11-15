
# Training an Object Detection Model with YOLO and GPU on Linux

This guide walks you through training an object detection model using YOLO on a GPU-enabled Linux system.

## 1. Preparing the Dataset

In YOLO format, each image has an associated `.txt` annotation file structured as follows:
- Each line represents one object.
- Each line format: `[class_id] [x_center] [y_center] [width] [height]` (values normalized between 0 and 1).

### Example:
```
0 0.5 0.5 0.2 0.3
1 0.3 0.4 0.1 0.2
```

## 2. Organizing the Dataset

A typical YOLO directory structure:
```
dataset/
├── images/
│   ├── train/
│   │   ├── img1.jpg
│   │   └── img2.jpg
│   └── val/
│       ├── img3.jpg
│       └── img4.jpg
└── labels/
    ├── train/
    │   ├── img1.txt
    │   └── img2.txt
    └── val/
        ├── img3.txt
        └── img4.txt
```

## 3. Install YOLO Environment

You can install YOLOv8 from Ultralytics with the following command:
```bash
pip install ultralytics
```

## 4. Configuring the YAML File

Create a configuration file (`.yaml`) for your dataset and class names.

Example:
```yaml
train: dataset/images/train
val: dataset/images/val
nc: 2
names: ["class_1", "class_2"]
```

## 5. Training the Model

To train with YOLOv8:
```python
from ultralytics import YOLO

# Load a YOLO model
model = YOLO('yolov8n.pt')  # Use a pre-trained model

# Train the model
model.train(data='path/to/your_config.yaml', epochs=50, imgsz=640, batch=16)
```

## 6. Enabling GPU on Linux

### Check GPU Compatibility

Check if your GPU supports CUDA:
```bash
nvidia-smi
```

### Install NVIDIA Drivers

If needed, install the NVIDIA driver:
```bash
sudo apt update
sudo apt install nvidia-driver-###  # replace ### with your driver version
```

### Install CUDA Toolkit and cuDNN

1. **CUDA Toolkit**: Download and install from [NVIDIA CUDA Toolkit](https://developer.nvidia.com/cuda-downloads).
2. **cuDNN**: Download from [NVIDIA cuDNN](https://developer.nvidia.com/cudnn) and install.

Add CUDA to environment variables in `~/.bashrc`:
```bash
export PATH=/usr/local/cuda/bin:$PATH
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
```
Then reload with `source ~/.bashrc`.

### Install PyTorch with CUDA

To install CUDA-compatible PyTorch:
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu117
```

### Training with GPU

Once set up, train with GPU (YOLO will auto-detect):
```python
model.train(data='path/to/your_config.yaml', epochs=50, imgsz=640, batch=16, device=0)
```
- `device=0` specifies the first GPU. Use `device='cuda'` to use all available GPUs.

This setup leverages the GPU, accelerating the training process.
