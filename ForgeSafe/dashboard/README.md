# ForgeSafe Dashboard

A local-only frontend prototype for the two ML modules in the parent project:

- Machine health monitoring with six mock machines
- CCTV monitoring with four mock camera feeds

The dashboard uses the device camera locally through the browser. The `inference_api.py` bridge loads the existing `models/best.pt` for PPE predictions and the CatBoost machine-health model for the CSV stream; the dashboard sends camera frames/files and polls machine telemetry through that bridge.

## Run

Open `index.html` directly in a browser, or serve the `dashboard` folder with any static file server.

For example, from the parent project folder:

```powershell
python -m http.server 8000 --directory dashboard
```

Then open `http://localhost:8000`.

In another terminal, start the PPE inference bridge:

```powershell
cd Construction-Site-Safety-PPE-Detection-main
python inference_api.py
```

The inference environment also needs `imageio-ffmpeg`; it is used only to encode annotated videos in a browser-compatible H.264 format.

Allow camera access in the browser, then use **Start camera** or choose an image/video file. Uploaded videos are processed frame-by-frame and returned as complete annotated MP4 results that can be viewed directly in the dashboard.
