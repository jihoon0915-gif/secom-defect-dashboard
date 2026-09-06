"""포트폴리오 시연 영상을 Playwright로 자동 녹화한다.

브라우저 조작(스크롤, 클릭)을 스크립트로 고정해 마우스 흔들림 없이
일정한 데모 영상을 재생성할 수 있게 하고, Playwright의 record_video 기능으로
OBS 같은 별도 화면 녹화 프로그램 없이 바로 .webm 파일을 얻는다.

실행:
    py scripts/record_demo.py
    -> demo_videos/static_dashboard_tour.webm
       demo_videos/live_monitoring_demo.webm
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

STATIC_URL = "https://jihoon0915-gif.github.io/secom-defect-dashboard/dashboard/secom_defect_dashboard.html"
LIVE_URL = "https://jihoon0915-gif.github.io/secom-defect-dashboard/dashboard/secom_live_monitoring.html"

OUT_DIR = Path(__file__).resolve().parent.parent / "demo_videos"
VIEWPORT = {"width": 1280, "height": 800}


def record(playwright, url, actions, out_name, wait_after_load_ms=1500):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context(
        viewport=VIEWPORT,
        record_video_dir=str(OUT_DIR),
        record_video_size=VIEWPORT,
    )
    page = context.new_page()
    print(f"[{out_name}] 접속: {url}")
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(wait_after_load_ms)

    actions(page)

    video_path = page.video.path()
    context.close()
    browser.close()

    final_path = OUT_DIR / f"{out_name}.webm"
    Path(video_path).replace(final_path)
    print(f"[{out_name}] 저장 완료 -> {final_path}")


def tour_static_dashboard(page):
    """섹션 헤더(01~05)를 순서대로 스무스 스크롤하며 각 구간에 머무른다."""
    sections = page.locator(".section-head")
    count = sections.count()
    print(f"섹션 {count}개 순회 시작")
    for i in range(count):
        sections.nth(i).scroll_into_view_if_needed()
        page.wait_for_timeout(2500)

    # 결과 요약 마지막 섹션(실시간 판별 시뮬레이션 표)까지 스크롤
    page.locator("#demo-body").scroll_into_view_if_needed()
    page.wait_for_timeout(2500)


def play_live_monitoring(page, play_seconds=22):
    """재생 버튼을 눌러 스트리밍 시뮬레이션을 일정 시간 재생한다.

    stream_queue 상 첫 불량 예측이 두 번째 레코드(idx=1)에서 바로 나오므로,
    기본 재생 속도(800ms/건)로도 몇 초 안에 alert-banner가 뜨는 장면을 담을 수 있다.
    """
    page.click("#btnStart")
    print(f"재생 시작, {play_seconds}초 녹화")
    page.wait_for_timeout(play_seconds * 1000)
    page.click("#btnPause")
    page.wait_for_timeout(1000)


def main():
    OUT_DIR.mkdir(exist_ok=True)
    with sync_playwright() as p:
        record(p, STATIC_URL, tour_static_dashboard, "static_dashboard_tour")
        record(p, LIVE_URL, play_live_monitoring, "live_monitoring_demo")


if __name__ == "__main__":
    main()
