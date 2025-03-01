import os

from ultralytics import YOLO
import torch
print("CUDA available:", torch.cuda.is_available())
print("CUDA device count:", torch.cuda.device_count())

model = YOLO('yolo11s.pt')

train_data_dir=r'/home/mike/data/hair_follicle_train'
os.chdir(train_data_dir)

model.train(data=os.path.join(train_data_dir,'data.yaml'), epochs=60, imgsz=640, batch=20, device=0, save=True)



