"""dashboard_data.json의 stream_queue를 순차 재생하며, 불량 예측 발생 시
쿨다운을 적용해 Slack으로 알림을 보내는 실시간 모니터링 시뮬레이터.

실행:
    py scripts/simulate_stream.py
    py scripts/simulate_stream.py --interval 0.05 --cooldown 30
"""
import argparse
import json
import sys
import time
from pathlib import Path

from notify_slack import send_defect_alert

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def run(interval: float, cooldown: float, limit: int | None, data_file: Path) -> None:
    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)

    queue = data["stream_queue"]
    if limit:
        queue = queue[:limit]

    last_alert_at: float | None = None
    suppressed = 0
    alerts_sent = 0
    fails_seen = 0

    for i, record in enumerate(queue):
        time.sleep(interval)
        tag = "FAIL" if record["true_label"] else "pass"
        print(f"[{i+1}/{len(queue)}] {record['time']} true={tag} "
              f"pred={'FAIL' if record['pred_label'] else 'pass'} "
              f"proba={record['pred_proba']:.3f}")

        if not record["pred_label"]:
            continue

        fails_seen += 1
        now = time.monotonic()
        if last_alert_at is None or (now - last_alert_at) >= cooldown:
            send_defect_alert(record, suppressed_count=suppressed)
            last_alert_at = now
            suppressed = 0
            alerts_sent += 1
        else:
            suppressed += 1

    print(f"\n완료: 총 {len(queue)}건 재생 / 불량 예측 {fails_seen}건 / "
          f"Slack 알림 {alerts_sent}건 전송 / 쿨다운으로 억제 {suppressed}건(마지막 알림 이후)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SECOM 실시간 모니터링 시뮬레이터")
    parser.add_argument("--interval", type=float, default=0.3,
                         help="레코드 간 재생 간격(초). 기본 0.3")
    parser.add_argument("--cooldown", type=float, default=60.0,
                         help="Slack 알림 쿨다운(초). 기본 60")
    parser.add_argument("--limit", type=int, default=None,
                         help="테스트용으로 재생할 레코드 수 제한")
    parser.add_argument("--file", type=str, default=str(DATA_DIR / "dashboard_data.json"),
                         help="재생할 JSON 파일 경로. 기본 data/dashboard_data.json "
                              "(테스트 시 data/sample_dashboard_data.json 사용 가능)")
    args = parser.parse_args()
    run(args.interval, args.cooldown, args.limit, Path(args.file))
