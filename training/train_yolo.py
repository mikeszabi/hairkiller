import os

from ultralytics import YOLO
import torch
print("CUDA available:", torch.cuda.is_available())
print("CUDA device count:", torch.cuda.device_count())

#model = YOLO('yolov8n.pt')

model = YOLO(f'/home/mike/data/hair/Hair.v9i.yolov8/runs/detect/train2/weights/best.pt')

train_data_dir=r'/home/mike/data/hair/Hair.v9i.yolov8'
os.chdir(train_data_dir)

model.train(data=os.path.join(train_data_dir,'data.yaml'), epochs=100, imgsz=640, batch=20, device=0, save=True)



