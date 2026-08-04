"""SECOM 대시보드를 로컬에서 서빙하고, 프론트엔드가 불량 예측을 감지해
보내는 이벤트(/api/alert)에 쿨다운을 적용해 Slack으로 전달하는 서버.

Slack 웹훅 URL은 서버 프로세스(.env)에만 두고 브라우저에는 절대 내려주지 않는다.

실행:
    py scripts/server.py
    브라우저에서 http://localhost:5000 접속 후 대시보드의 "재생" 버튼 클릭
"""
import os
import sys
import time
from pathlib import Path
from threading import Lock

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory

from notify_slack import send_defect_alert

load_dotenv()

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
COOLDOWN_SECONDS = float(os.environ.get("SLACK_ALERT_COOLDOWN_SECONDS", "60"))

app = Flask(__name__, static_folder=str(DASHBOARD_DIR), static_url_path="")

_lock = Lock()
_last_alert_at: float | None = None
_suppressed = 0


@app.get("/")
def index():
    return send_from_directory(DASHBOARD_DIR, "secom_live_monitoring.html")


@app.post("/api/alert")
def api_alert():
    global _last_alert_at, _suppressed
    record = request.get_json(force=True)

    with _lock:
        now = time.monotonic()
        if _last_alert_at is None or (now - _last_alert_at) >= COOLDOWN_SECONDS:
            sent = send_defect_alert(record, suppressed_count=_suppressed)
            _last_alert_at = now
            _suppressed = 0
            return jsonify({"sent": sent, "suppressed": 0})

        _suppressed += 1
        return jsonify({"sent": False, "suppressed": _suppressed})


if __name__ == "__main__":
    print(f"Slack 알림 쿨다운: {COOLDOWN_SECONDS}초 (SLACK_ALERT_COOLDOWN_SECONDS로 조정 가능)")
    print(f"웹훅 설정 여부: {'설정됨' if os.environ.get('SLACK_WEBHOOK_URL') else '미설정 (콘솔에만 출력)'}")
    print("http://localhost:5000 에서 대시보드를 여세요")
    app.run(port=5000, debug=False)
