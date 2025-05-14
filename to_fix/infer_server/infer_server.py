from flask import Flask, request, jsonify
from flask_cors import CORS
from ultralytics import YOLO
import uuid
import os

app = Flask(__name__)
CORS(app)

# Load TensorRT-exported YOLOv8n model
MODEL_PATH = "yolov8n.engine"
model = YOLO(MODEL_PATH)

@app.route('/infer', methods=['POST'])
def infer():
    if 'image' not in request.files:
        return jsonify({'error': 'No image file provided'}), 400
    
    image_file = request.files['image']
    image_id = str(uuid.uuid4())
    filename = f"/tmp/{image_id}.jpg"
    image_file.save(filename)

    results = model(filename)
    result = results[0]

    detections = []
    for box in result.boxes:
        detections.append({
            "class": int(box.cls[0]),
            "conf": float(box.conf[0]),
            "bbox": [float(coord) for coord in box.xyxy[0]]
        })

    os.remove(filename)

    return jsonify({
        "detections": detections,
        "count": len(detections)
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

#curl -X POST http://localhost:5000/infer -F image=@bus.jpg
