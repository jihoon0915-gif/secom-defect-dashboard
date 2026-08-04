# SECOM 반도체 공정 불량 판별 프로젝트

반도체 웨이퍼 제조 공정에서 수집된 센서 데이터를 기반으로, 불량(fail) 웨이퍼를 사전에 판별하는 분류 모델을 구축하고, 결과를 정적/실시간 두 종류의 대시보드로 시각화하며, 실시간 불량 예측 발생 시 Slack으로 알림을 보내는 프로젝트입니다.

## 문제 정의

반도체 공정은 590개에 달하는 센서로 지속 모니터링되지만, 불량은 전체의 6.64%에 불과할 만큼 드물게 발생합니다. 이런 극심한 클래스 불균형 속에서 불량을 놓치지 않으면서도(재현율) 오탐을 최소화하는(정밀도) 모델을 만드는 것이 핵심 과제였습니다.

## 데이터

- **출처**: [UCI Machine Learning Repository — SECOM Dataset](https://archive.ics.uci.edu/ml/datasets/secom)
- **규모**: 1,567개 샘플, 590개 센서 피처
- **라벨**: Pass(정상) 1,463건 / Fail(불량) 104건 — 약 14:1 불균형
- `data/uci-secom.csv`로 저장 (git에는 커밋하지 않음, 직접 다운로드해서 배치)

## 접근 과정

1. **전처리**: 결측치 40% 초과 컬럼 제거 → 중위값 대체 → 분산 0인 컬럼 제거 (590개 → 432개)
2. **피처 선택**: Random Forest 중요도 기준 상위 40개 피처 선택
3. **모델 비교**: Logistic Regression, Random Forest, Gradient Boosting, XGBoost, SVM(RBF) 5개 모델을 `RandomizedSearchCV`(5-fold CV, ROC-AUC 기준)로 튜닝
4. **임계값 최적화**: 기본 임계값(0.5)에서는 대부분 모델의 재현율이 0에 가까웠음 → 정밀도-재현율 곡선에서 F1을 최대화하는 임계값으로 재산정
5. **시각화**: 분석 결과를 정적 대시보드로, 실제 운영 상황을 가정한 실시간 모니터링 시뮬레이션을 별도 대시보드로 구현
6. **알림**: 실시간 모니터링 중 불량이 예측되면 쿨다운을 적용해 Slack으로 알림 전송

## 핵심 인사이트

극심한 클래스 불균형 데이터에서는 정확도(accuracy)가 무의미했습니다. 기본 임계값 기준 재현율은 0%에 가까웠지만, 임계값을 최적화하자 재현율이 최대 69%까지 개선되었습니다.

## 결과 요약

| 모델 | AUC | 정밀도 | 재현율 | F1 | 최적 임계값 |
|---|---|---|---|---|---|
| Logistic Regression | 0.765 | 0.216 | 0.423 | 0.286 | 0.639 |
| **Random Forest (최종 선정)** | 0.775 | 0.282 | 0.423 | **0.338** | 0.299 |
| Gradient Boosting | 0.732 | 0.321 | 0.346 | 0.333 | 0.074 |
| XGBoost | 0.782 | 0.238 | 0.385 | 0.294 | 0.069 |
| SVM (RBF) | 0.811 | 0.217 | 0.692 | 0.330 | 0.091 |

> 최종 모델은 AUC 최댓값이 아닌 **F1 기준**으로 선정했습니다.

## 프로젝트 구조

```
secom-defect-dashboard/
├── scripts/
│   ├── train_pipeline.py    # 모델 학습 → data/dashboard_data.json 생성
│   ├── server.py            # 대시보드 서빙 + /api/alert 수신 → 쿨다운 적용 Slack 전송
│   ├── simulate_stream.py   # (CLI용) stream_queue 순차 재생 + Slack 쿨다운 알림
│   └── notify_slack.py      # Slack Incoming Webhook 전송 모듈
├── dashboard/
│   ├── secom_defect_dashboard.html   # 정적 분석 대시보드
│   └── secom_live_monitoring.html    # 실시간 모니터링 대시보드(재생 중 불량 예측 시 서버로 이벤트 전송)
├── data/                      # uci-secom.csv, dashboard_data.json (git 미포함)
├── requirements.txt
├── render.yaml                # Render 배포 설정 (Blueprint)
└── .env.example
```

## 대시보드

- 정적 분석 대시보드 (`dashboard/secom_defect_dashboard.html`) — 전처리 과정, 모델 비교, 피처 중요도, 공정 관리도
- 실시간 모니터링 대시보드 (`dashboard/secom_live_monitoring.html`) — 고정된 모델로 신규 데이터를 스코어링하며 통계를 누적 갱신. 테스트셋을 실제 유입처럼 순차 재생하고, 불량이 예측될 때마다 `/api/alert`로 이벤트를 서버에 전달합니다. **Slack 웹훅 URL은 브라우저에 절대 내려가지 않고 `scripts/server.py` 프로세스(.env)에만 존재하며**, 서버가 쿨다운을 적용해 실제 전송 여부를 결정합니다.

## Slack 알림 설정

1. https://api.slack.com/apps → **Create New App** → **From scratch**
2. 좌측 메뉴 **Incoming Webhooks** → 토글 On
3. **Add New Webhook to Workspace** → 알림 받을 채널 선택 → Authorize
4. 발급된 `https://hooks.slack.com/services/...` URL을 `.env`에 저장:
   ```
   cp .env.example .env
   # .env 파일을 열어 SLACK_WEBHOOK_URL 값을 실제 웹훅 URL로 교체
   ```
5. 웹훅을 설정하지 않으면 알림은 콘솔에만 출력되고 에러 없이 넘어갑니다.

불량 예측이 짧은 시간 안에 연속으로 발생해도 Slack이 스팸이 되지 않도록, 기본 60초 쿨다운을 적용합니다(쿨다운 중 억제된 건수는 다음 알림 메시지에 함께 표시). `.env`의 `SLACK_ALERT_COOLDOWN_SECONDS`로 조정할 수 있습니다.

## 실행 방법

### 대시보드 + Slack 알림 (권장)

```bash
uv venv .venv
.venv\Scripts\activate
uv pip install -r requirements.txt
cp .env.example .env   # SLACK_WEBHOOK_URL 값 입력

py scripts/server.py
# 브라우저에서 http://localhost:5000 접속 → "재생" 클릭
# 불량으로 예측된 웨이퍼가 나올 때마다 서버가 쿨다운을 적용해 Slack으로 전송
```

### 공개 배포 (Render) — 다른 기기/외부에서 접속

포트폴리오 링크처럼 외부에서도 접속 가능한 고정 URL이 필요할 때 사용합니다. `render.yaml`에 배포 설정이 이미 정의되어 있습니다.

1. 이 프로젝트를 GitHub에 push
2. [Render 대시보드](https://dashboard.render.com) → **New +** → **Blueprint** → 방금 push한 저장소 선택 (render.yaml을 자동 인식)
3. 환경변수 입력 화면에서 `SLACK_WEBHOOK_URL`에 실제 웹훅 URL 입력 (`sync: false`라 저장소에는 노출되지 않음)
4. 배포 완료 후 발급되는 `https://secom-defect-dashboard-xxxx.onrender.com` 형태의 URL로 접속

**주의**: `/api/alert`는 인증이 없는 공개 엔드포인트입니다. 쿨다운(기본 60초)과 IP당 2초 최소 간격 제한을 걸어뒀지만, 완전한 스팸 방지는 아닙니다. 실제 운영 채널이 아닌 데모 전용 채널의 웹훅을 쓰는 것을 권장합니다. 무료 플랜은 일정 시간 요청이 없으면 슬립 상태가 되어 첫 접속 시 로딩이 몇 초 걸릴 수 있습니다.

### CLI로만 재생 (터미널에서 로그만 확인하고 싶을 때)

```bash
py scripts/simulate_stream.py --interval 0.3 --cooldown 60
```

### 모델 재학습

```bash
py scripts/train_pipeline.py   # data/dashboard_data.json 갱신
```

`dashboard/secom_live_monitoring.html`에는 이전에 학습된 결과가 `const DATA = ...`로 이미 삽입되어 있어 바로 재생해볼 수 있습니다. 재학습 후 대시보드에 반영하려면 새로 생성된 `data/dashboard_data.json` 내용을 이 HTML의 `const DATA = ...` 부분에 다시 붙여넣어야 합니다(수동 삽입 방식은 원본 프로젝트 구조를 그대로 유지했습니다).

## 한계와 다음 단계

- 실제 설비 데이터 연동 대신 보유한 테스트셋으로 유입을 시뮬레이션했습니다. 유입부만 실시간 소스(MES/센서 스트림)로 교체하면 동일 구조를 실제 운영에 적용할 수 있습니다.
- 현재는 모델을 1회 학습 후 고정하는 구조이며, 실제 운영에서는 주기적 재학습 배치가 별도로 필요합니다.
- 590개 피처 중 상위 40개만 사용했는데, 도메인 지식이 결합되면 피처 선택 품질을 더 높일 수 있습니다.
