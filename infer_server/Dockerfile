#t=ultralytics/ultralytics:latest-jetson-jetpack4
#sudo docker pull $t && sudo docker run -it --ipc=host --runtime=nvidia $t

FROM ultralytics/ultralytics:latest-jetson-jetpack4

RUN pip install flask flask-cors
WORKDIR /app
COPY . /app
CMD ["python3", "infer_server.py"]

# sudo docker run -it --ipc=host --runtime=nvidia -p 5000:5000 -v $(pwd):/app ultralytics/ultralytics:latest-jetson-jetpack4 python3 /app/server.py
