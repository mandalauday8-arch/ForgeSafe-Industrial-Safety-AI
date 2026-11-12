# ForgeSafe — Agentic AI Framework for Industrial Safety Monitoring

ForgeSafe is a demonstration framework combining PPE detection, machine-health prediction, a multi-agent incident workflow, and retrieval-augmented safety-procedure lookup.

## Project modules

- `dashboard/` — browser-based monitoring dashboard
- `Construction-Site-Safety-PPE-Detection-main/` — YOLOv8 PPE inference API and model weights
- `machine-health/` — six CatBoost machine-failure models, metadata, and sample telemetry feeds
- `forgesafe/` — multi-agent workflow, incident schemas, and RAG knowledge retrieval
- `knowledge/` — seven industrial safety SOP documents
- `tests/` — workflow tests

## Local setup

Use Python 3.11. From this directory run:

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
```

Start the inference API:

```bash
cd Construction-Site-Safety-PPE-Detection-main
python inference_api.py
```

In a second terminal, from the project root, serve the dashboard:

```bash
python -m http.server 8000 --directory dashboard
```

Open `http://127.0.0.1:8000`. The dashboard uses `dashboard/config.js` to locate the API. For a hosted dashboard, replace the value of `window.FORGESAFE_API_URL` with the deployed API base URL.

## Backend deployment

The included `render.yaml` and `Procfile` provide a starting configuration for a Python web service. The API loads YOLOv8 and CatBoost model files at startup, so select a host instance with sufficient memory and verify model initialization and inference after deployment.

## Important demo limitation

The emergency controls in this project are simulated software actions. They do not operate or shut down physical industrial equipment. Predictions and detections are demonstration outputs and must not be used as the sole basis for real-world safety decisions.
