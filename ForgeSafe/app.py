from pathlib import Path
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser


ROOT = Path(__file__).resolve().parent
DASHBOARD_DIR = ROOT / "dashboard"
PPE_DIR = ROOT / "Construction-Site-Safety-PPE-Detection-main"
DASHBOARD_URL = "http://127.0.0.1:8000"
API_URL = "http://127.0.0.1:5000"


def get_url(url):
    try:
        with urllib.request.urlopen(url, timeout=1) as response:
            return response.status, response.read()
    except (OSError, urllib.error.URLError):
        return None, b""


def dashboard_is_ready():
    status, _ = get_url(DASHBOARD_URL)
    return status == 200


def api_is_ready():
    status, body = get_url(f"{API_URL}/health")
    if status != 200:
        return False
    try:
        health = json.loads(body)
        stream_status, _ = get_url(f"{API_URL}/machine-status")
        services = health.get("services", {})
        return (
            health.get("ok") is True
            and len(health.get("machine_models", [])) == 6
            and services.get("machine_health") is True
            and services.get("cctv_detection") is True
            and services.get("file_inspection") is True
            and stream_status == 200
        )
    except json.JSONDecodeError:
        return False


def wait_for(url, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        status, _ = get_url(url)
        if status == 200:
            return True
        time.sleep(.25)
    return False


def start_process(command, cwd):
    return subprocess.Popen(command, cwd=cwd)


def main():
    children = []
    try:
        if api_is_ready():
            print("Using existing PPE inference API on port 5000")
        else:
            print("Starting PPE inference API...")
            api_process = start_process([sys.executable, "inference_api.py"], PPE_DIR)
            children.append(api_process)
            if not wait_for(f"{API_URL}/health"):
                raise RuntimeError("The PPE inference API did not start on port 5000")

        if dashboard_is_ready():
            print("Using existing dashboard on port 8000")
        else:
            print("Starting dashboard...")
            dashboard_process = start_process(
                [sys.executable, "-m", "http.server", "8000", "--directory", str(DASHBOARD_DIR)],
                ROOT,
            )
            children.append(dashboard_process)
            if not wait_for(DASHBOARD_URL):
                raise RuntimeError("The dashboard did not start on port 8000")

        print()
        print("ForgeSafe is running")
        print(f"Dashboard: {DASHBOARD_URL}")
        print(f"Inference API: {API_URL}")
        print("Machine health: enabled (6 models)")
        print("CCTV detection: enabled")
        print("Image/video inspection: enabled")
        print("AI Agents: enabled (5 collaborating agents)")
        print("RAG Knowledge Base: enabled (7 SOPs)")
        print("Simulated Controls: enabled (E-Stop, LOTO, Work Order)")
        print("Press Ctrl+C to stop services started by this command.")
        webbrowser.open(DASHBOARD_URL)

        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping ForgeSafe...")
    finally:
        for process in reversed(children):
            if process.poll() is None:
                process.terminate()
        for process in reversed(children):
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


if __name__ == "__main__":
    main()
