from pathlib import Path
import json
import subprocess
import sys
import tempfile
import threading
import time
import os

import cv2
import imageio_ffmpeg
import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
from flask import Flask, jsonify, request
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from forgesafe.workflow import ForgeSafeWorkflow

workflow = ForgeSafeWorkflow(PROJECT_ROOT)
model = YOLO(str(ROOT / "models" / "best.pt"))
MACHINE_ROOT = ROOT.parent / "machine-health"
MACHINE_MODELS = {
    "CNC_Lathe": "cnc_lathe",
    "CNC_Mill": "cnc_mill",
    "Hydraulic_Press": "hydraulic_press",
    "Injection_Molder": "injection_molder",
    "Industrial_Chiller": "industrial_chiller",
    "Furnace": "furnace",
}
machine_models = {}
for machine_type, model_name in MACHINE_MODELS.items():
    machine_model = CatBoostClassifier()
    machine_model.load_model(str(MACHINE_ROOT / "models" / f"{model_name}_failure_model.cbm"))
    with (MACHINE_ROOT / "models" / f"{model_name}_metadata.json").open() as metadata_file:
        metadata = json.load(metadata_file)
    machine_models[machine_type] = {"model": machine_model, "features": metadata["features"]}
machine_feed_paths = {
    "normal": MACHINE_ROOT / "models" / "industrial_continuous_live_feed.csv",
    "faulty": MACHINE_ROOT / "models" / "industrial_gradual_fault_live_feed.csv",
}
machine_feeds = {"normal": pd.read_csv(machine_feed_paths["normal"])}
machine_groups = {
    "normal": [group.reset_index(drop=True) for _, group in machine_feeds["normal"].groupby("Machine_Type", sort=False)]
}
machine_stream_started = {"normal": None}
machine_lock = threading.Lock()


def load_machine_feed(feed_name):
    if feed_name not in machine_feeds:
        feed = pd.read_csv(machine_feed_paths[feed_name])
        machine_feeds[feed_name] = feed
        machine_groups[feed_name] = [
            group.reset_index(drop=True)
            for _, group in feed.groupby("Machine_Type", sort=False)
        ]
        machine_stream_started[feed_name] = None
    return machine_feeds[feed_name], machine_groups[feed_name]


sensor_priorities = {
    "CNC_Lathe": ["Vibration_mms", "Sound_dB", "Temperature_C", "Power_Consumption_kW"],
    "CNC_Mill": ["Vibration_mms", "Sound_dB", "Temperature_C", "Power_Consumption_kW"],
    "Hydraulic_Press": ["Hydraulic_Pressure_bar", "Vibration_mms", "Temperature_C", "Power_Consumption_kW"],
    "Injection_Molder": ["Temperature_C", "Power_Consumption_kW", "Oil_Level_pct", "Coolant_Level_pct"],
    "Industrial_Chiller": ["Temperature_C", "Coolant_Level_pct", "Power_Consumption_kW", "Sound_dB"],
    "Furnace": ["Temperature_C", "Heat_Index", "Sound_dB", "Power_Consumption_kW"],
}
sensor_labels = {
    "Vibration_mms": ("Vibration", "mm/s", 1),
    "Sound_dB": ("Sound", "dB", 1),
    "Temperature_C": ("Temperature", "°C", 1),
    "Power_Consumption_kW": ("Power", "kW", 1),
    "Hydraulic_Pressure_bar": ("Hydraulic pressure", "bar", 1),
    "Oil_Level_pct": ("Oil level", "%", 1),
    "Coolant_Level_pct": ("Coolant level", "%", 1),
    "Heat_Index": ("Heat index", "", 2),
}
app = Flask(__name__)


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS, PUT, DELETE"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With"
    response.headers["Access-Control-Expose-Headers"] = "X-Result-Type, X-Detections"
    return response


def detect_image(image):
    result = model.predict(image, verbose=False)[0]
    detections = []
    for box in result.boxes:
        coordinates = box.xyxy[0].tolist()
        detections.append({
            "class": result.names[int(box.cls[0])],
            "confidence": round(float(box.conf[0]), 3),
            "box": [round(value, 1) for value in coordinates],
        })
    annotated = result.plot()
    success, encoded = cv2.imencode(".jpg", annotated)
    if not success:
        raise RuntimeError("Could not encode annotated image")

    # Pass detections through the Safety Agent -> Supervisor Agent -> RAG pipeline
    if any(d["class"].startswith("NO-") for d in detections):
        workflow.process_cctv(detections)

    return detections, encoded.tobytes()


def detect_video(content, suffix):
    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / f"input{suffix}"
        raw_output_path = Path(directory) / "annotated-raw.mp4"
        output_path = Path(directory) / "annotated.mp4"
        input_path.write_bytes(content)
        capture = cv2.VideoCapture(str(input_path))
        if not capture.isOpened():
            raise ValueError("The uploaded video could not be opened")

        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = capture.get(cv2.CAP_PROP_FPS)
        fps = fps if fps and fps > 0 else 24
        writer = cv2.VideoWriter(
            str(raw_output_path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        if not writer.isOpened():
            capture.release()
            raise RuntimeError("Could not create the annotated video")

        detections = []
        structured_detections = []
        while True:
            success, frame = capture.read()
            if not success:
                break
            result = model.predict(frame, verbose=False)[0]
            for box in result.boxes:
                cls_name = result.names[int(box.cls[0])]
                detections.append(cls_name)
                structured_detections.append({
                    "class": cls_name,
                    "confidence": round(float(box.conf[0]), 3),
                    "box": [round(val, 1) for val in box.xyxy[0].tolist()],
                })
            writer.write(result.plot())

        capture.release()
        writer.release()
        if not raw_output_path.exists() or raw_output_path.stat().st_size == 0:
            raise RuntimeError("The annotated video was empty")
        try:
            subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-i", str(raw_output_path),
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
                "-an",
                str(output_path),
            ], check=True, capture_output=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as error:
            raise RuntimeError("Could not encode a browser-compatible video") from error

        # Process any unsafe detections through the multi-agent system
        unsafe_items = [d for d in structured_detections if d["class"].startswith("NO-")]
        if unsafe_items:
            workflow.process_cctv(unsafe_items[:5])

        return list(dict.fromkeys(detections)), output_path.read_bytes()


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "model": "models/best.pt",
        "services": {
            "machine_health": True,
            "cctv_detection": True,
            "file_inspection": True,
            "agent_orchestrator": True,
        },
        "agents": workflow.status()["agents"],
        "knowledge_documents": len(workflow.knowledge.chunks),
        "machine_models": [
            f"models/{name}_failure_model.cbm" for name in MACHINE_MODELS.values()
        ],
    })


@app.get("/agents/status")
def agents_status():
    return jsonify(workflow.status())


@app.get("/incidents")
def get_incidents():
    limit = int(request.args.get("limit", 50))
    return jsonify({
        "incidents": workflow.get_incidents(limit=limit),
        "total": len(workflow.incidents),
    })


@app.post("/incidents/clear")
def clear_incidents():
    workflow.clear_incidents()
    return jsonify({"success": True, "total": 0})


@app.post("/system/reset")
def reset_system():
    workflow.reset_all()
    with machine_lock:
        machine_stream_started["normal"] = None
        machine_stream_started["faulty"] = None
        machine_feeds["faulty"] = pd.read_csv(machine_feed_paths["faulty"])
        machine_groups["faulty"] = [
            group.reset_index(drop=True)
            for _, group in machine_feeds["faulty"].groupby("Machine_Type", sort=False)
        ]
    return jsonify({"success": True, "incidents": 0, "simulated_overrides": 0})


@app.post("/incidents/action")
def execute_incident_action():
    payload = request.get_json(silent=True) or {}
    report_id = payload.get("report_id", "")
    action_type = payload.get("action_type", "")
    target_id = payload.get("target_id")
    operator = payload.get("operator", "Alex Rivera")

    if not action_type:
        return jsonify({"error": "action_type is required"}), 400

    result = workflow.execute_simulated_action(
        report_id=report_id,
        action_type=action_type,
        target_id=target_id,
        operator=operator,
    )
    return jsonify(result)


@app.post("/machines/reset")
def reset_machine_endpoint():
    payload = request.get_json(silent=True) or {}
    machine_id = payload.get("machine_id", "")
    if not machine_id:
        return jsonify({"error": "machine_id is required"}), 400

    result = workflow.reset_machine(machine_id)
    return jsonify(result)


@app.post("/machines/freeze")
def freeze_machine_endpoint():
    payload = request.get_json(silent=True) or {}
    machine_id = payload.get("machine_id", "")
    if not machine_id:
        return jsonify({"error": "machine_id is required"}), 400

    workflow.freeze_machine(machine_id)
    return jsonify({"success": True, "machine_id": machine_id, "frozen": True})


@app.post("/machines/unfreeze")
def unfreeze_machine_endpoint():
    payload = request.get_json(silent=True) or {}
    machine_id = payload.get("machine_id", "")
    if not machine_id:
        return jsonify({"error": "machine_id is required"}), 400

    workflow.unfreeze_machine(machine_id)
    return jsonify({"success": True, "machine_id": machine_id, "frozen": False})


@app.get("/knowledge/search")
def search_knowledge():
    query = request.args.get("q", "").strip()
    if query:
        results = workflow.knowledge.search(query, limit=10)
    else:
        results = workflow.knowledge.get_all_chunks()
    return jsonify({"results": results, "total": len(results)})


@app.get("/machine-status")
def machine_status():
    feed_name = request.args.get("feed", "normal").lower()
    if feed_name not in machine_feed_paths:
        return jsonify({"error": "feed must be normal or faulty"}), 400
    with machine_lock:
        feed, groups = load_machine_feed(feed_name)
        if request.args.get("reset") == "1" or machine_stream_started[feed_name] is None:
            machine_stream_started[feed_name] = time.monotonic()
        elapsed_seconds = int(time.monotonic() - machine_stream_started[feed_name])
        cursor = elapsed_seconds % max(len(group) for group in groups)
        rows = pd.DataFrame([group.iloc[cursor % len(group)] for group in groups])

    predictions = {}
    probabilities = {}
    for machine_type, group in rows.groupby("Machine_Type", sort=False):
        machine_config = machine_models[machine_type]
        values = group[machine_config["features"]].copy()
        predictions[machine_type] = machine_config["model"].predict(values)
        probabilities[machine_type] = machine_config["model"].predict_proba(values)[:, 1] * 100

    prediction_indices = {machine_type: 0 for machine_type in predictions}
    machines = []
    for row in rows.to_dict("records"):
        machine_type = row["Machine_Type"]
        machine_id = row["Machine_ID"]
        row_index = prediction_indices[machine_type]
        prediction = predictions[machine_type][row_index]
        probability = probabilities[machine_type][row_index]
        prediction_indices[machine_type] += 1
        probability = round(float(probability), 2)
        if probability >= 80:
            risk = "CRITICAL"
        elif probability >= 60:
            risk = "HIGH"
        elif probability >= 30:
            risk = "MEDIUM"
        else:
            risk = "LOW"
        anomaly_detected = feed_name == "faulty" and row.get("demo_status") in {"DEGRADING", "FAULT"}
        anomaly_type = row.get("fault_type") if anomaly_detected else None
        attention = risk in {"MEDIUM", "HIGH", "CRITICAL"} or anomaly_detected
        sensor_readings = []
        for feature in sensor_priorities.get(row["Machine_Type"], machine_models[machine_type]["features"]):
            if feature not in sensor_labels or pd.isna(row.get(feature)):
                continue
            label, unit, decimals = sensor_labels[feature]
            sensor_readings.append({
                "label": label,
                "value": f"{float(row[feature]):.{decimals}f}{unit}",
            })
            if len(sensor_readings) == 3:
                break

        machine_obj = {
            "name": row["Machine_Type"].replace("_", " "),
            "id": machine_id,
            "status": "Attention" if attention else "Operational",
            "statusClass": "attention" if attention else "operational",
            "health": round(max(0, 100 - probability)),
            "failureProbability": probability,
            "risk": risk,
            "failureWithin7Days": bool(prediction),
            "anomalyDetected": anomaly_detected,
            "anomalyType": anomaly_type,
            "demoStatus": row.get("demo_status"),
            "sensorReadings": sensor_readings,
            "timestamp": row["timestamp"],
        }

        # Check for simulated control overrides
        override = workflow.get_machine_override(machine_id)
        if override:
            machine_obj["simulatedOverride"] = override
            machine_obj["status"] = override["state"]
            machine_obj["statusClass"] = "shutdown" if "SHUTDOWN" in override["state"] else "locked"
            if "SHUTDOWN" in override["state"]:
                machine_obj["health"] = 0
            attention = True
        elif attention:
            # Process through Machine Agent -> Supervisor Agent -> RAG -> Action Agent
            decisions = workflow.process_machine(machine_obj)
            if decisions:
                report = decisions[0]["report"]
                dec = decisions[0]["decision"]
                machine_obj["incidentId"] = report["report_id"]
                machine_obj["recommendedAction"] = dec["action"]
                machine_obj["simulatedAction"] = dec.get("simulated_action")
                if dec.get("guidance"):
                    machine_obj["guidanceTitle"] = dec["guidance"][0]["title"]
                    machine_obj["standard"] = dec["guidance"][0].get("standard", "")
        else:
            workflow.clear_machine_incident(machine_id)

        machines.append(machine_obj)
    return jsonify({
        "machines": machines,
        "cursor": cursor,
        "totalRows": len(feed),
        "feed": feed_name,
        "simulatedOverrides": workflow.simulated_machine_states,
    })


@app.post("/predict")
def predict():
    uploaded = request.files.get("file")
    if uploaded is None:
        return jsonify({"error": "Expected a file field named 'file'"}), 400

    content = uploaded.read()
    suffix = Path(uploaded.filename or "upload").suffix.lower()
    if uploaded.mimetype.startswith("video/") or suffix in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
        try:
            detections, annotated = detect_video(content, suffix or ".mp4")
        except (RuntimeError, ValueError) as error:
            return jsonify({"error": str(error)}), 400
        response = app.response_class(annotated, mimetype="video/mp4")
        response.headers["X-Result-Type"] = "video"
        response.headers["X-Detections"] = json.dumps(detections)
        return response

    image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return jsonify({"error": "The uploaded file is not a readable image"}), 400

    detections, annotated = detect_image(image)
    response = app.response_class(annotated, mimetype="image/jpeg")
    response.headers["X-Result-Type"] = "image"
    response.headers["X-Detections"] = json.dumps(detections)
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
