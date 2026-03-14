# 🌅 아침 브리핑 자동 발송 시스템

매일 KST 06:00 날씨·주식·뉴스 브리핑을 자동 생성하여 이메일로 발송합니다.

---

## 🏗️ 아키텍처

```
GitHub Actions (KST 06:00)
        │
        ▼
  briefing.py 실행
  ├── Open-Meteo API  → 날씨
  ├── KIS API         → 국내 주식 현재가
  ├── yfinance        → 해외 주식 (KIS 폴백)
  ├── Google News RSS → 분야별 뉴스 (30일 이내, 10건)
  └── GPT-4o-mini     → 요약 / TOP3 / 시장분석 / 한마디
        │
        ▼  HTML 이메일 생성
        │
        ▼  Make Webhook POST
        │
  Make 시나리오
  ├── Gmail → sypark1178@naver.com
  ├── Gmail → pjh200106@sogang.ac.kr
  └── Gmail → mihwa.lee@myangel.co.kr
```

---

## ⚙️ 설정 방법

### 1. GitHub Secrets 등록

GitHub 레포지토리 → Settings → Secrets and variables → Actions → **New repository secret**

| Secret 이름       | 값                          |
|-------------------|-----------------------------|
| `OPENAI_API_KEY`  | OpenAI API 키 (`sk-...`)    |
| `KIS_APP_KEY`     | 한국투자증권 App Key         |
| `KIS_APP_SECRET`  | 한국투자증권 App Secret      |
| `MAKE_WEBHOOK_URL`| `https://hook.us2.make.com/...` |

### 2. Make 시나리오 설정

1. Make.com 접속 → **Scenarios** → **Create a new scenario**
2. 우측 하단 `...` → **Import Blueprint** 클릭
3. `make_scenario_blueprint.json` 파일 업로드
4. **Webhook 모듈**: 기존 웹훅 URL 확인 (`Custom Webhook` 탭)
5. **Gmail 모듈** 3개 각각: Gmail 계정 연결 (`sypark1178@gmail.com`)
6. 시나리오 **저장 → 활성화(ON)**

> **Gmail 연결 주의**: Make에서 Gmail OAuth 연결 시  
> `sypark1178@gmail.com` 계정으로 인증해야 발신자가 올바르게 설정됩니다.

### 3. GitHub Actions 활성화

`.github/workflows/morning_briefing.yml` 파일이 레포에 포함되어 있으면  
자동으로 매일 UTC 21:00 (= KST 06:00)에 실행됩니다.

수동 테스트: **Actions 탭** → `🌅 아침 브리핑 자동 발송` → **Run workflow**

---

## 📁 파일 구조

```
morning-briefing/
├── .github/
│   └── workflows/
│       └── morning_briefing.yml   # GitHub Actions 스케줄
├── src/
│   └── briefing.py                # 메인 브리핑 스크립트
├── make_scenario_blueprint.json   # Make 시나리오 임포트 파일
├── requirements.txt
└── README.md
```

---

## 📌 디폴트 설정

| 항목       | 값                                                      |
|------------|--------------------------------------------------------|
| 지역       | 서울                                                    |
| 관심분야   | 주식, 경제, 금융, 방산                                  |
| 뉴스기간   | 조회일 기준 **30일 이내**                                |
| 뉴스건수   | 분야별 **최대 10건**                                    |
| 주식종목   | 삼성전자, SK하이닉스, LG에너지솔루션, 삼성SDI, 에코프로비엠, 한화에어로스페이스, 두산에너빌리티, 한국항공우주, 현대로템, LIG넥스원 |
| 발송시각   | 매일 **KST 06:00**                                      |

---

## ❗ 주의사항

- **KIS API 실전투자 계정** 사용 — 모의투자 URL과 다릅니다.
- KIS API는 장 개장(09:00) 전 조회 시 **전일 종가** 기준으로 반환됩니다.
- OpenAI API 크레딧이 소진되면 GPT 항목이 오류 메시지로 표시됩니다.
- GitHub Actions 무료 플랜은 월 2,000분 제한 (본 워크플로우는 회당 약 5~10분 소요).
