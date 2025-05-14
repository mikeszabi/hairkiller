import sys
import cv2
import numpy as np
from ultralytics import YOLO
import torch

def main():
    model_path = r"./model/follicle_exit_v11i_yolov8n_20250513.pt"

    engine_path = "./model/follicle_exit_v11i_yolov8n_20250513.engine"

    model = YOLO(model_path)
    model.export(format="onnx")  # this creates .engine file

    sys.subprocess.call("/usr/src/tensorrt/bin/trtexec","--onnx=follicle_exit_v11i_yolov8n_20250513.onnx","--saveEngine=follicle_exit_v11i_yolov8n_20250513.engine","--fp16")


#/usr/src/tensorrt/bin/trtexec   --onnx=follicle_exit_v11i_yolov8n_20250513.onnx   --saveEngine=follicle.engine   --fp16   --minShapes=input:1x3x640x640   --optShapes=input:8x3x640x640   --maxShapes=input:32x3x640x640

if __name__ == '__main__':
    main()