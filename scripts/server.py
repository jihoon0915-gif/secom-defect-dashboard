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

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))  # gunicorn 등 다른 cwd에서 실행돼도 notify_slack import 보장

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from notify_slack import send_defect_alert

load_dotenv()

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
COOLDOWN_SECONDS = float(os.environ.get("SLACK_ALERT_COOLDOWN_SECONDS", "60"))
# 공개 배포 시 /api/alert가 인증 없이 열려 있으므로, 쿨다운과는 별개로
# 동일 IP가 너무 자주 두드리는 것을 막는 최소한의 스팸 방지 장치.
PER_IP_MIN_INTERVAL = 2.0

app = Flask(__name__, static_folder=str(DASHBOARD_DIR), static_url_path="")
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)  # Render 등 리버스 프록시 뒤에서 실 클라이언트 IP 사용
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024  # 알림 레코드는 작은 JSON 하나뿐이라 4KB면 충분

_lock = Lock()
_last_alert_at: float | None = None
_suppressed = 0
_last_seen_by_ip: dict[str, float] = {}


@app.get("/")
def index():
    return send_from_directory(DASHBOARD_DIR, "secom_live_monitoring.html")


def _valid_record(record) -> bool:
    if not isinstance(record, dict):
        return False
    if not isinstance(record.get("time"), str):
        return False
    proba = record.get("pred_proba")
    if not isinstance(proba, (int, float)) or not (0 <= proba <= 1):
        return False
    if record.get("true_label") not in (0, 1):
        return False
    return True


@app.post("/api/alert")
def api_alert():
    global _last_alert_at, _suppressed
    record = request.get_json(silent=True)
    if not _valid_record(record):
        return jsonify({"error": "invalid record"}), 400

    ip = request.remote_addr or "unknown"

    with _lock:
        now = time.monotonic()

        last_seen = _last_seen_by_ip.get(ip)
        _last_seen_by_ip[ip] = now
        if last_seen is not None and (now - last_seen) < PER_IP_MIN_INTERVAL:
            return jsonify({"sent": False, "reason": "rate_limited"}), 429

        if _last_alert_at is None or (now - _last_alert_at) >= COOLDOWN_SECONDS:
            sent = send_defect_alert(record, suppressed_count=_suppressed)
            _last_alert_at = now
            _suppressed = 0
            return jsonify({"sent": sent, "suppressed": 0})

        _suppressed += 1
        return jsonify({"sent": False, "suppressed": _suppressed})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    print(f"Slack 알림 쿨다운: {COOLDOWN_SECONDS}초 (SLACK_ALERT_COOLDOWN_SECONDS로 조정 가능)")
    print(f"웹훅 설정 여부: {'설정됨' if os.environ.get('SLACK_WEBHOOK_URL') else '미설정 (콘솔에만 출력)'}")
    print(f"http://localhost:{port} 에서 대시보드를 여세요")
    app.run(host="0.0.0.0", port=port, debug=False)
