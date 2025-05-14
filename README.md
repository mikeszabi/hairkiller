# hairkiller

#ON JETSON NANO
python3 -m venv yolo_env
source yolo_env/bin/activate

# from https://pypi.jetson-ai-lab.dev/jp6/cu126

pip install torch-2.7.0-cp310-cp310-linux_aarch64.whl -y
pip install torchvision-0.22.0-cp310-cp310-linux_aarch64.whl
pip install --upgrade numpy==1.26.4
pip install ultralytics

ln -s /usr/lib/python3.10/dist-packages/tensorrt ~/Projects/hairkiller/yolo_env/lib/python3.10/site-packages/tensorrt
