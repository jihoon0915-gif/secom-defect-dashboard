"""SECOM 불량 예측 결과를 Slack Incoming Webhook으로 전송하는 모듈."""
import os
import sys

import requests
from dotenv import load_dotenv

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

load_dotenv()

WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")


def send_defect_alert(record: dict, suppressed_count: int = 0) -> bool:
    """불량(fail) 예측 1건에 대한 Slack 알림을 전송한다.

    webhook이 설정되지 않은 경우 콘솔에만 출력하고 False를 반환한다(파이프라인은 계속 진행).
    """
    proba_pct = round(record["pred_proba"] * 100, 1)
    lines = [
        f":rotating_light: *SECOM 불량 예측 감지*",
        f"> 시간: `{record['time']}`",
        f"> 예측 확률: *{proba_pct}%*",
        f"> 실제 라벨: {'FAIL' if record['true_label'] else 'PASS'}",
    ]
    if suppressed_count > 0:
        lines.append(f"> _쿨다운 동안 억제된 추가 불량 예측: {suppressed_count}건_")
    text = "\n".join(lines)

    if not WEBHOOK_URL:
        print("[notify_slack] SLACK_WEBHOOK_URL 미설정 — 콘솔에만 출력합니다.")
        print(text)
        return False

    resp = requests.post(WEBHOOK_URL, json={"text": text}, timeout=5)
    resp.raise_for_status()
    return True
