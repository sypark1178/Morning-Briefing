#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌅 아침 브리핑 v24 — 6개국 5대 경제신문 + 전문가 분석
GitHub Actions + Make Webhook 자동 발송
v24  |  2026-03  |  KST 06:00 매일 실행

변경 사항 (v23 → v24):
- 뉴스 수집국 확대: 4개국 → 6개국 (중국·독일 추가)
- 중국 5대 경제신문 추가 (人民日報·新华社·南方都市报·财新·第一财经)
- 독일 5대 경제신문 추가 (Handelsblatt·FAZ·Süddeutsche·Reuters DE·Spiegel Wirtschaft)
- 분야별 뉴스 10개 → 14개 (중국 2 + 독일 2 추가)
- 국가별 배분: 한국 4 + 미국 2 + 영국 2 + 일본 2 + 중국 2 + 독일 2
- 번역 범위 확대: 영어·일본어·중국어·독일어 → 한국어
- 거시지표 추가: DAX 지수, 원/위안 환율, 유로화 환율
- GPT 분석: 6개국 글로벌 관점 반영
"""

# ═══════════════════════════════════════════════════════════════
# 0. 환경 설정
# ═══════════════════════════════════════════════════════════════
import os, re, sys, json, time, logging, requests, feedparser
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from bs4 import BeautifulSoup
import yfinance as yf
import openai

# ── .env 파일 자동 로드 (로컬 실행 시) ──────────────────────
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=True)
        print(f"[dotenv] .env 로드 완료: {_env_path}")
    else:
        print(f"[dotenv] .env 파일 없음 (GitHub Actions Secrets 모드): {_env_path}")
except ImportError:
    print("[dotenv] python-dotenv 미설치 → pip install python-dotenv")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("briefing_log.txt", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))


# ═══════════════════════════════════════════════════════════════
# 1. 환경변수 / 설정값
# ═══════════════════════════════════════════════════════════════
def _env(key: str, required=True) -> str:
    v = os.environ.get(key, "").strip()
    if required and not v:
        log.error(f"❌ 환경변수 누락: {key}  →  .env 파일 또는 GitHub Secrets 확인 필요")
        sys.exit(1)
    return v


OPENAI_API_KEY   = _env("OPENAI_API_KEY")
KIS_APP_KEY      = _env("KIS_APP_KEY")
KIS_APP_SECRET   = _env("KIS_APP_SECRET")
MAKE_WEBHOOK_URL = _env("MAKE_WEBHOOK_URL")

client = openai.OpenAI(api_key=OPENAI_API_KEY)

# ── 디폴트 설정 ──────────────────────────────────────────────
CITY = "서울"
CITIES = {
    "서울": {"lat": 37.5665, "lon": 126.9780},
    "부산": {"lat": 35.1796, "lon": 129.0756},
    "인천": {"lat": 37.4563, "lon": 126.7052},
    "대전": {"lat": 36.3504, "lon": 127.3845},
    "대구": {"lat": 35.8714, "lon": 128.6014},
}

# 관심 종목
DEFAULT_TICKERS: dict[str, str] = {
    "삼성전자":           "005930.KS",
    "SK하이닉스":         "000660.KS",
    "LG에너지솔루션":     "373220.KS",
    "삼성SDI":            "006400.KS",
    "에코프로비엠":       "247540.KS",
    "한화에어로스페이스": "012450.KS",
    "두산에너빌리티":     "034020.KS",
    "한국항공우주":       "047810.KS",
    "현대로템":           "064350.KS",
    "LIG넥스원":          "079550.KS",
}

# 관심 분야
TOPICS = ["📈 주식", "💰 경제", "🏦 금융", "🛡️ 방산"]

TOPIC_KEYWORDS = {
    "📈 주식":  "반도체 이차전지 주식 코스피 증시",
    "💰 경제":  "경제 트럼프관세 환율 금리 부동산정책 GDP",
    "🏦 금융":  "금융 은행 증권 SMR 에너지 중앙은행",
    "🛡️ 방산":  "방산 방위산업 무기수출 한화 현대로템 LIG넥스원 천궁",
}

TOPIC_KEYWORDS_EN = {
    "📈 주식":  "stock market semiconductor battery equity",
    "💰 경제":  "economy tariff exchange rate interest rate GDP inflation",
    "🏦 금융":  "finance banking securities central bank Fed monetary",
    "🛡️ 방산":  "defense aerospace weapons military exports arms",
}

TOPIC_KEYWORDS_JA = {
    "📈 주식":  "株式 半導体 証券 株価 日経",
    "💰 경제":  "経済 関税 為替 金利 GDP インフレ",
    "🏦 금융":  "金融 銀行 証券 日銀 金融政策",
    "🛡️ 방산":  "防衛 防衛産業 兵器 安全保障",
}

TOPIC_KEYWORDS_ZH = {
    "📈 주식":  "股市 半导体 证券 股价 A股",
    "💰 경제":  "经济 关税 汇率 利率 GDP 通胀",
    "🏦 금융":  "金融 银行 证券 央行 货币政策",
    "🛡️ 방산":  "国防 军工 武器出口 军事 安全",
}

TOPIC_KEYWORDS_DE = {
    "📈 주식":  "Aktien DAX Halbleiter Börse Technologie",
    "💰 경제":  "Wirtschaft Zölle Wechselkurs Zinsen BIP Inflation",
    "🏦 금융":  "Finanzen Banken EZB Geldpolitik Wertpapiere",
    "🛡️ 방산":  "Verteidigung Rüstung Waffenexporte Bundeswehr",
}

EXTRA_KEYWORDS = [
    "관세","천궁","K9전차","홍해","코스피200","코스닥","반도체","금리",
    "보유세","부동산정책","유가","양도소득세","환율","방산","AI","로봇",
    "전기차","우주항공","원전","SMR","해외증시","닛케이","엔화",
    "위안화","DAX","ECB","중국경기","독일경기",
]

# ── 뉴스 수집 설정 ──────────────────────────────────────────
NEWS_CUTOFF_DAYS = 1
N_ARTICLES_PER_COUNTRY = {
    "한국": 4,
    "미국": 2,
    "영국": 2,
    "일본": 2,
    "중국": 2,
    "독일": 2,
}
N_ARTICLES = sum(N_ARTICLES_PER_COUNTRY.values())  # 총 14개

# 중복 우선순위: 경제 > 금융 > 주식 > 방산
DEDUP_PRIORITY = ["💰 경제", "🏦 금융", "📈 주식", "🛡️ 방산"]

# ══════════════════════════════════════════════════════════════
# 📰 뉴스 소스 — 6개국 5대 경제신문사
# ══════════════════════════════════════════════════════════════
#
# 🇰🇷 한국 5대 경제신문
#   1. 한국경제신문  — 국내 최대 경제지, 한경닷컴
#   2. 매일경제신문  — 매경닷컴, MBN 계열
#   3. 머니투데이    — 온라인 중심, 실시간 속보 강점
#   4. 이데일리      — 증권·금융 특화
#   5. 파이낸셜뉴스  — 금융·증권 중심
#
# 🇺🇸 미국 5대 경제신문
#   1. Wall Street Journal (WSJ)  — 글로벌 금융 최고 권위지
#   2. Bloomberg                  — 금융정보·데이터 특화
#   3. Reuters                    — 글로벌 실시간 경제뉴스
#   4. CNBC                       — 시장·투자 뉴스
#   5. Financial Times (US)       — 글로벌 비즈니스 분석
#
# 🇬🇧 영국 5대 경제신문
#   1. Financial Times (UK)       — 세계 최고 경제지 중 하나
#   2. The Economist              — 글로벌 경제·정치 분석
#   3. Reuters UK                 — 영국발 경제 실시간 뉴스
#   4. The Guardian Business      — 영국 비즈니스·경제 심층
#   5. BBC Business               — 영국 공영 경제 뉴스
#
# 🇯🇵 일본 5대 경제신문
#   1. 닛케이 (日本経済新聞)       — 세계 최대 경제지(구독자 300만), 닛케이225 발표
#   2. Nikkei Asia                — 닛케이 영문판, 아시아 경제
#   3. 산케이비즈 (産経ビズ)       — 산케이그룹 경제전문
#   4. Japan Times Business       — 영문 일본 경제
#   5. NHK Business               — 일본 공영 경제 뉴스
#
# 🇨🇳 중국 5대 경제신문 (v24 신규)
#   1. 人民日報 (인민일보)         — 중국 최대 관영 신문, 정책 방향 선행 지표
#   2. 新华社 (신화통신)           — 국영 통신사, 대외 공식 발표 채널
#   3. 南方都市报 (남방도시보)      — 시장경제 시각의 독립적 경제 보도
#   4. 财新传媒 (차이신)           — 중국판 블룸버그, 금융·기업 심층 분석
#   5. 第一财经 (제1재경)          — 상하이 기반 경제 전문 방송·신문
#
# 🇩🇪 독일 5대 경제신문 (v24 신규)
#   1. Handelsblatt               — 독일 최대 경제지, 유럽판 WSJ
#   2. Frankfurter Allgemeine (FAZ) — 독일 3대 일간지, 경제 심층 분석
#   3. Süddeutsche Zeitung        — 독일 최대 발행부수 일간지
#   4. Reuters Deutschland        — 독일발 실시간 경제뉴스
#   5. Spiegel Wirtschaft         — 독일 최대 시사주간지 경제섹션
#
# ※ 직접 RSS 구독 장벽(유료 멤버십) 우회: Google News 검색 RSS 활용
# ══════════════════════════════════════════════════════════════
NEWS_FEEDS = {
    "한국": [
        "https://news.google.com/rss/search?q=한국경제신문&hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/search?q=매일경제&hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/search?q=머니투데이&hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/search?q=이데일리&hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/search?q=파이낸셜뉴스&hl=ko&gl=KR&ceid=KR:ko",
    ],
    "미국": [
        "https://news.google.com/rss/search?q=Wall+Street+Journal+economy&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Bloomberg+markets+economy&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Reuters+economy+finance&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=CNBC+markets+stocks&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=Financial+Times+economy&hl=en&gl=US&ceid=US:en",
    ],
    "영국": [
        "https://news.google.com/rss/search?q=Financial+Times+UK+economy&hl=en&gl=GB&ceid=GB:en",
        "https://news.google.com/rss/search?q=The+Economist+economy&hl=en&gl=GB&ceid=GB:en",
        "https://news.google.com/rss/search?q=Reuters+UK+economy&hl=en&gl=GB&ceid=GB:en",
        "https://news.google.com/rss/search?q=Guardian+business+economy&hl=en&gl=GB&ceid=GB:en",
        "https://news.google.com/rss/search?q=BBC+business+economy&hl=en&gl=GB&ceid=GB:en",
    ],
    "일본": [
        "https://news.google.com/rss/search?q=日本経済新聞+経済&hl=ja&gl=JP&ceid=JP:ja",
        "https://news.google.com/rss/search?q=Nikkei+Asia+economy&hl=en&gl=JP&ceid=JP:en",
        "https://news.google.com/rss/search?q=産経ビズ+経済&hl=ja&gl=JP&ceid=JP:ja",
        "https://news.google.com/rss/search?q=Japan+Times+business+economy&hl=en&gl=JP&ceid=JP:en",
        "https://news.google.com/rss/search?q=NHK+Japan+economy+business&hl=en&gl=JP&ceid=JP:en",
    ],
    "중국": [
        "https://news.google.com/rss/search?q=人民日报+经济&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=新华社+经济+金融&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=财新+经济+金融&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=第一财经+经济&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
        "https://news.google.com/rss/search?q=China+economy+finance&hl=en&gl=CN&ceid=CN:en",
    ],
    "독일": [
        "https://news.google.com/rss/search?q=Handelsblatt+Wirtschaft&hl=de&gl=DE&ceid=DE:de",
        "https://news.google.com/rss/search?q=FAZ+Wirtschaft+Finanzen&hl=de&gl=DE&ceid=DE:de",
        "https://news.google.com/rss/search?q=Süddeutsche+Zeitung+Wirtschaft&hl=de&gl=DE&ceid=DE:de",
        "https://news.google.com/rss/search?q=Reuters+Deutschland+Wirtschaft&hl=de&gl=DE&ceid=DE:de",
        "https://news.google.com/rss/search?q=Spiegel+Wirtschaft+Deutschland&hl=de&gl=DE&ceid=DE:de",
    ],
}

# ── 거시경제지표 (yfinance) ──────────────────────────────────
MACRO_INDICATORS = [
    ("코스피",            "^KS11",   "pt",    2),
    ("코스닥",            "^KQ11",   "pt",    2),
    ("나스닥",            "^IXIC",   "pt",    2),
    ("S&P 500",          "^GSPC",   "pt",    2),
    ("다우존스",          "^DJI",    "pt",    2),
    ("닛케이 225",        "^N225",   "pt",    2),
    ("DAX (독일)",        "^GDAXI",  "pt",    2),
    ("상하이종합 (중국)", "000001.SS","pt",   2),
    ("원/달러 환율",      "KRW=X",   "원",    1),
    ("원/엔 환율(100엔)", "KRWJPY=X","원",    2),
    ("원/위안 환율",      "KRWCNY=X","원",    2),
    ("원/유로 환율",      "KRWEUR=X","원",    1),
    ("WTI 원유(26-04)",   "CL=F",    "$/bbl", 2),
    ("금 선물(26-04)",    "GC=F",    "$/oz",  2),
]

MAIL_SUBJECT = "🌅 오늘의 아침 브리핑"


# ═══════════════════════════════════════════════════════════════
# 2. 유틸리티
# ═══════════════════════════════════════════════════════════════
def now_kst() -> datetime:
    return datetime.now(KST)


def date_str_kst() -> str:
    n = now_kst()
    wd = ["월", "화", "수", "목", "금", "토", "일"][n.weekday()]
    return n.strftime(f"%Y년 %m월 %d일 ({wd}) %H:%M")


def parse_dt(s: str) -> datetime:
    for fmt in ["%a, %d %b %Y %H:%M:%S %z",
                "%a, %d %b %Y %H:%M:%S GMT",
                "%Y-%m-%dT%H:%M:%S%z"]:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def time_ago(s: str) -> str:
    try:
        dt = parse_dt(s)
        if not dt.tzinfo:
            dt = dt.replace(tzinfo=timezone.utc)
        d = int((datetime.now(timezone.utc) - dt).total_seconds())
        if d < 60:    return f"{d}초 전"
        if d < 3600:  return f"{d // 60}분 전"
        if d < 86400: return f"{d // 3600}시간 전"
        return f"{d // 86400}일 전"
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════
# 2-B. 번역 함수 (영어·일본어 → 한국어)
# ═══════════════════════════════════════════════════════════════
_translation_cache: dict[str, str] = {}


def translate_to_korean(text: str) -> str:
    """
    영어·일본어·중국어·독일어 텍스트를 한국어로 번역 (캐싱 포함).
    한글이 이미 포함된 텍스트는 스킵.
    실패 시 원문 반환.
    """
    if not text or len(text) < 5:
        return text
    # 이미 한글 포함 → 스킵
    if any(0xAC00 <= ord(c) <= 0xD7A3 for c in text):
        return text
    cache_key = text[:120]
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=300,
            messages=[
                {"role": "system",
                 "content": (
                     "You are a professional translator specializing in economics and finance. "
                     "Translate the given text (English, Japanese, Chinese, or German) into natural Korean. "
                     "Preserve proper nouns, company names, and financial terms accurately. "
                     "Return only the translated text without any explanation."
                 )},
                {"role": "user", "content": text[:500]},
            ],
        )
        translated = r.choices[0].message.content.strip()
        _translation_cache[cache_key] = translated
        return translated
    except Exception as e:
        log.warning(f"⚠️ 번역 실패: {e}")
        return text


# ═══════════════════════════════════════════════════════════════
# 3. 날씨 (Open-Meteo, 무료)
# ═══════════════════════════════════════════════════════════════
WEATHER_SLOTS = [
    ("🌄 아침", 7), ("🌞 오전", 10), ("🌇 오후", 14),
    ("🌆 저녁", 17), ("🌙 밤", 21),
]

WCODE_MAP = {
    0:  "☀️ 맑음",       1:  "🌤️ 대체로맑음", 2:  "⛅ 구름조금",   3:  "☁️ 흐림",
    45: "🌫️ 안개",       48: "🌫️ 짙은안개",
    51: "🌦️ 이슬비",     53: "🌦️ 이슬비",     55: "🌧️ 이슬비강",
    61: "🌧️ 비약",       63: "🌧️ 비",          65: "🌧️ 비강",
    71: "🌨️ 눈약",       73: "❄️ 눈",           75: "❄️ 눈강",
    80: "🌦️ 소나기",     81: "🌧️ 소나기",      82: "⛈️ 소나기강",
    95: "⛈️ 뇌우",       99: "⛈️ 강한뇌우",
}


def fetch_weather(city: str) -> dict:
    c = CITIES.get(city, CITIES["서울"])
    params = {
        "latitude": c["lat"], "longitude": c["lon"],
        "hourly": "temperature_2m,apparent_temperature,weathercode,"
                  "precipitation_probability,relativehumidity_2m,windspeed_10m",
        "current": "temperature_2m,apparent_temperature,weathercode,"
                   "precipitation_probability,relativehumidity_2m,windspeed_10m",
        "timezone": "Asia/Seoul", "forecast_days": 1,
    }
    try:
        r = requests.get("https://api.open-meteo.com/v1/forecast",
                         params=params, timeout=10)
        r.raise_for_status()
        data   = r.json()
        hourly = data.get("hourly", {})
        times  = hourly.get("time", [])
        today  = now_kst().strftime("%Y-%m-%d")
        slots  = {}
        for label, hour in WEATHER_SLOTS:
            target = f"{today}T{hour:02d}:00"
            if target in times:
                idx = times.index(target)
                slots[label] = {
                    "temp":  hourly["temperature_2m"][idx],
                    "feels": hourly["apparent_temperature"][idx],
                    "cond":  WCODE_MAP.get(hourly["weathercode"][idx], "🌡️"),
                    "rain":  hourly["precipitation_probability"][idx],
                    "hum":   hourly["relativehumidity_2m"][idx],
                    "wind":  hourly["windspeed_10m"][idx],
                }
        cur = data.get("current", {})
        slots["_cur"] = {
            "temp":  cur.get("temperature_2m", "-"),
            "feels": cur.get("apparent_temperature", "-"),
            "cond":  WCODE_MAP.get(cur.get("weathercode", 0), "🌡️"),
            "rain":  cur.get("precipitation_probability", "-"),
            "hum":   cur.get("relativehumidity_2m", "-"),
            "wind":  cur.get("windspeed_10m", "-"),
        }
        log.info(f"✅ 날씨 조회 완료: {city}")
        return {"slots": slots, "error": None}
    except Exception as e:
        log.warning(f"⚠️ 날씨 조회 실패: {e}")
        return {"slots": {}, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# 4. 한국투자증권 KIS API (국내주식 현재가)
# ═══════════════════════════════════════════════════════════════
_kis_token: dict = {"access_token": "", "expire": 0}
KIS_BASE_URL  = "https://openapivts.koreainvestment.com:29443"  # 모의투자
KIS_AVAILABLE = None


def _kis_get_token() -> bool:
    global KIS_AVAILABLE
    if KIS_AVAILABLE is False:
        return False
    if _kis_token["access_token"] and time.time() < _kis_token["expire"]:
        return True
    if not KIS_APP_KEY or not KIS_APP_SECRET:
        KIS_AVAILABLE = False
        return False
    try:
        res = requests.post(
            f"{KIS_BASE_URL}/oauth2/tokenP",
            headers={"content-type": "application/json"},
            data=json.dumps({
                "grant_type": "client_credentials",
                "appkey":     KIS_APP_KEY,
                "appsecret":  KIS_APP_SECRET,
            }),
            timeout=5,
        )
        if res.status_code == 200:
            d = res.json()
            _kis_token["access_token"] = d["access_token"]
            _kis_token["expire"]       = time.time() + 86400 - 300
            KIS_AVAILABLE = True
            log.info("✅ KIS 토큰 발급 성공")
            return True
        log.warning(f"⚠️ KIS 토큰 발급 실패: {res.status_code} {res.text[:100]}")
        KIS_AVAILABLE = False
    except Exception as e:
        log.warning(f"⚠️ KIS 접속 불가 (yfinance로 전환): {e}")
        KIS_AVAILABLE = False
    return False


def _kis_fetch_price(code6: str) -> dict | None:
    if not _kis_get_token():
        return None
    headers = {
        "Content-Type":  "application/json",
        "authorization": f"Bearer {_kis_token['access_token']}",
        "appkey":        KIS_APP_KEY,
        "appsecret":     KIS_APP_SECRET,
        "tr_id":         "FHKST01010100",
    }
    try:
        res = requests.get(
            f"{KIS_BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-price",
            headers=headers,
            params={"fid_cond_mrkt_div_code": "J", "fid_input_iscd": code6},
            timeout=10,
        )
        if res.status_code == 200:
            out        = res.json().get("output", {})
            curr_price = float(out.get("stck_prpr", 0) or 0)
            prev_close = float(out.get("stck_sdpr", 0) or 0)
            change     = float(out.get("prdy_vrss", 0) or 0)
            pct        = float(out.get("prdy_ctrt", 0) or 0)
            name = next(
                (k for k, v in DEFAULT_TICKERS.items() if v.startswith(code6)),
                code6,
            )
            return {
                "ticker": code6 + ".KS", "name": name,
                "price": curr_price, "curr": curr_price,
                "prev": prev_close if prev_close else curr_price - change,
                "change": change, "pct": pct, "currency": "KRW",
            }
    except Exception as e:
        log.warning(f"⚠️ KIS 조회 예외 ({code6}): {e}")
    return None


def fetch_stock_prices(tickers: dict[str, str]) -> list[dict]:
    results = []
    for name, raw in tickers.items():
        raw  = raw.strip()
        is_krx = (raw.isdigit() and len(raw) == 6) or \
                  raw.upper().endswith(".KS") or raw.upper().endswith(".KQ")
        if is_krx:
            code = raw.split(".")[0].zfill(6)
            data = _kis_fetch_price(code)
            if data:
                data["name"] = name
                results.append(data)
                time.sleep(0.2)
                continue
            ticker_str = code + ".KS"
        else:
            ticker_str = raw
        try:
            tk   = yf.Ticker(ticker_str)
            info = tk.info
            prev = float(info.get("previousClose") or
                         info.get("regularMarketPreviousClose") or 0)
            curr = float(info.get("currentPrice") or
                         info.get("regularMarketPrice") or prev)
            chg  = curr - prev
            pct  = chg / prev * 100 if prev else 0
            results.append({
                "ticker": ticker_str, "name": name,
                "price": curr, "curr": curr, "prev": prev,
                "change": chg, "pct": pct,
                "currency": info.get("currency", "KRW"),
            })
        except Exception as e:
            log.warning(f"⚠️ yfinance 실패 ({ticker_str}): {e}")
            results.append({
                "ticker": ticker_str, "name": name,
                "price": 0, "curr": 0, "prev": 0,
                "change": 0, "pct": 0, "currency": "", "error": str(e),
            })
        time.sleep(0.1)
    log.info(f"✅ 주식 조회 완료: {len(results)}종목")
    return results


# ═══════════════════════════════════════════════════════════════
# 4-B. 거시경제지표 (yfinance)
# ═══════════════════════════════════════════════════════════════
def fetch_macro_indicators() -> list[dict]:
    results = []
    for name, ticker, unit, decimals in MACRO_INDICATORS:
        try:
            tk   = yf.Ticker(ticker)
            info = tk.info
            curr = float(
                info.get("regularMarketPrice") or
                info.get("currentPrice") or 0
            )
            prev = float(
                info.get("previousClose") or
                info.get("regularMarketPreviousClose") or 0
            )
            change = curr - prev
            pct    = change / prev * 100 if prev else 0
            fmt    = f",.{decimals}f"
            results.append({
                "name":     name,    "ticker":   ticker,
                "unit":     unit,    "curr":     curr,
                "prev":     prev,    "change":   change,
                "pct":      pct,
                "curr_s":   f"{curr:{fmt}}",
                "prev_s":   f"{prev:{fmt}}",
                "change_s": f"{abs(change):{fmt}}",
                "pct_s":    f"{abs(pct):.2f}",
            })
            log.info(f"  ✓ [{name}]: {curr:{fmt}} {unit} "
                     f"({'+' if change >= 0 else '-'}{abs(pct):.2f}%)")
        except Exception as e:
            log.warning(f"⚠️ 거시지표 실패 [{name}/{ticker}]: {e}")
            results.append({
                "name": name, "ticker": ticker, "unit": unit,
                "curr": 0, "prev": 0, "change": 0, "pct": 0,
                "curr_s": "-", "prev_s": "-",
                "change_s": "-", "pct_s": "-", "error": str(e),
            })
        time.sleep(0.1)
    log.info(f"✅ 거시경제지표 완료: {len(results)}건")
    return results


# ═══════════════════════════════════════════════════════════════
# 5. 뉴스 수집 (4개국 5대 경제신문사 RSS)
# ═══════════════════════════════════════════════════════════════
def _build_feed_url(country: str, keyword: str) -> list[str]:
    """
    국가+키워드 조합으로 Google News RSS URL 목록 생성.
    각 신문사 피드 URL에 키워드를 결합.
    """
    kw_map = {
        "한국": keyword,
        "미국": TOPIC_KEYWORDS_EN.get(keyword, keyword),
        "영국": TOPIC_KEYWORDS_EN.get(keyword, keyword),
        "일본": TOPIC_KEYWORDS_JA.get(keyword, keyword),
        "중국": TOPIC_KEYWORDS_ZH.get(keyword, keyword),
        "독일": TOPIC_KEYWORDS_DE.get(keyword, keyword),
    }
    locale_map = {
        "한국": ("ko",    "KR", "ko"),
        "미국": ("en",    "US", "en"),
        "영국": ("en",    "GB", "en"),
        "일본": ("ja",    "JP", "ja"),
        "중국": ("zh-CN", "CN", "zh-Hans"),
        "독일": ("de",    "DE", "de"),
    }
    kw   = kw_map.get(country, keyword)
    hl, gl, ceid_lang = locale_map.get(country, ("en", "US", "en"))
    urls = []
    for base_url in NEWS_FEEDS.get(country, []):
        # 신문사명을 유지하면서 키워드 추가
        domain = base_url.split("q=")[1].split("&")[0] if "q=" in base_url else ""
        combined = f"{domain} {kw}".strip() if domain else kw
        new_url = (
            f"https://news.google.com/rss/search?"
            f"q={quote(combined)}&hl={hl}&gl={gl}&ceid={gl}:{ceid_lang}"
        )
        urls.append(new_url)
    return urls


def fetch_news_by_country(
    country: str,
    topic: str = "",
    keyword: str = "",
    n: int = 5,
    pool: int = 0
) -> list[dict]:
    """
    국가별 RSS 피드에서 뉴스 수집.
    keyword가 있으면 URL에 결합, 없으면 기본 피드 사용.
    영어·일본어 기사는 자동 한국어 번역.
    """
    fetch_size = pool if pool > n else n * 3
    cutoff     = datetime.now(timezone.utc) - timedelta(days=NEWS_CUTOFF_DAYS)
    all_arts   = []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }

    # 키워드가 있으면 키워드 결합 URL 사용, 없으면 기본 피드
    if keyword:
        feed_urls = _build_feed_url(country, topic if topic else keyword)
    else:
        feed_urls = NEWS_FEEDS.get(country, [])

    for feed_url in feed_urls:
        try:
            response = requests.get(feed_url, headers=headers, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)

            if not feed.entries:
                log.debug(f"⚠️ 빈 피드 [{country}]: {feed_url[:60]}")
                continue

            for e in feed.entries[:fetch_size * 3]:
                pub = e.get("published", e.get("updated", ""))
                dt  = parse_dt(pub)
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue

                title = e.get("title", "(제목없음)")
                sr    = e.get("summary", e.get("description", ""))
                txt   = BeautifulSoup(sr, "lxml").get_text(strip=True)[:300] if sr else ""

                # 비한국어 → 한국어 번역
                if country != "한국":
                    title = translate_to_korean(title)
                    if txt:
                        txt = translate_to_korean(txt)

                art = {
                    "title":   title,
                    "link":    e.get("link", ""),
                    "summary": txt,
                    "pub":     pub,
                    "ago":     time_ago(pub),
                    "_dt":     dt,
                    "country": country,
                    "source":  (
                        e.get("source", {}).get("title", "")
                        if isinstance(e.get("source"), dict)
                        else ""
                    ),
                }

                # 키워드 필터 (한국어 키워드 기준)
                if keyword:
                    kws = keyword.lower().split()
                    body = (title + txt).lower()
                    if not any(kw in body for kw in kws):
                        continue

                all_arts.append(art)

            time.sleep(0.3)

        except requests.exceptions.RequestException as e:
            log.warning(f"⚠️ 네트워크 오류 [{country}]: {type(e).__name__} — {feed_url[:60]}")
        except Exception as e:
            log.warning(f"⚠️ RSS 오류 [{country}]: {e}")

    all_arts.sort(key=lambda x: x["_dt"], reverse=True)
    # 제목 기준 중복 제거
    seen_titles: set[str] = set()
    deduped = []
    for a in all_arts:
        t = a["title"][:30]
        if t not in seen_titles:
            seen_titles.add(t)
            deduped.append(a)

    log.info(f"  ✓ 뉴스 수집 [{country}]: {len(deduped[:fetch_size])}건")
    return deduped[:fetch_size]


def fetch_news_smart(topic: str, keywords_ko: str) -> list[dict]:
    """
    4개국 5대 경제신문 기반 스마트 뉴스 수집.
    1단계: 키워드 검색 → 2단계: 부족하면 AI 주제 분류로 보완.
    """
    results = []

    for country in ["한국", "미국", "영국", "일본", "중국", "독일"]:
        needed = N_ARTICLES_PER_COUNTRY[country]
        kw     = keywords_ko  # _build_feed_url 내부에서 국가별 키워드로 변환

        # 1단계: 키워드 검색
        arts = fetch_news_by_country(
            country, topic=topic, keyword=kw, n=needed, pool=needed * 3
        )

        # 2단계: 부족하면 키워드 없이 넓게 수집 후 AI 분류
        if len(arts) < needed:
            arts_all = fetch_news_by_country(
                country, keyword="", n=needed * 3, pool=needed * 5
            )
            if arts_all:
                extra = needed - len(arts)
                ctx   = "\n".join(
                    f"[{i+1}] {a['title']}"
                    for i, a in enumerate(arts_all[:15])
                )
                idxs = _gpt_select_by_topic(topic, ctx, extra)
                for idx in idxs:
                    if 0 <= idx < len(arts_all) and arts_all[idx] not in arts:
                        arts.append(arts_all[idx])
                        if len(arts) >= needed:
                            break

        results.extend(arts[:needed])

    return results


def _gpt_select_by_topic(topic: str, ctx: str, count: int) -> list[int]:
    """AI가 주제와 관련된 기사 인덱스 선택 (0-based)."""
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=60,
            messages=[
                {"role": "system",
                 "content": "You are a news classifier. Return ONLY a JSON array of 0-based indices."},
                {"role": "user",
                 "content": (
                     f"Select top {count} articles most relevant to [{topic}].\n"
                     f"{ctx}\nReturn format: [0,2,4]"
                 )},
            ],
        )
        raw = r.choices[0].message.content.strip()
        return json.loads(raw)
    except Exception as e:
        log.warning(f"⚠️ GPT 분류 실패: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# 6. GPT 분석/요약 — 객관적 사실 기반 최고 전문가 수준
# ═══════════════════════════════════════════════════════════════
_EXPERT_SYSTEM = (
    "당신은 CFA·FRM 자격증을 보유한 20년 경력의 글로벌 거시경제·투자 전문가입니다. "
    "블룸버그·WSJ·닛케이·FT·Handelsblatt에 기고 이력이 있으며 현재 국내 대형 자산운용사 수석 이코노미스트입니다.\n"
    "분석 원칙:\n"
    "① 제공된 뉴스 기사의 객관적 사실만을 근거로 분석합니다.\n"
    "② 수치·지표·정책명 등 사실관계를 정확히 인용하고, 근거가 없는 추측은 '~가능성' 또는 '~우려'로 표현합니다.\n"
    "③ 단편적 사건이 아닌 글로벌 거시 흐름과의 연결고리를 제시합니다.\n"
    "④ 투자 판단은 참고용임을 명시하고, 균형 있는 리스크/기회 시각을 유지합니다.\n"
    "⑤ 한국·미국·영국·일본·중국·독일 6개국 관점을 통합하여 입체적 분석을 제공합니다."
)


def _gpt(system: str, user: str, temperature=0.3, max_tokens=1000) -> str:
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        return r.choices[0].message.content.strip()
    except openai.RateLimitError as e:
        if "insufficient_quota" in str(e):
            log.warning("⚠️ OpenAI 크레딧 소진")
            return "⚠️ [OpenAI 크레딧 소진] platform.openai.com/billing 에서 충전 후 재실행하세요."
        log.warning(f"⚠️ GPT 요청 한도 초과: {e}")
        return "⚠️ [GPT 요청 한도 초과] 잠시 후 다시 실행해 주세요."
    except Exception as e:
        log.warning(f"⚠️ GPT 호출 실패: {e}")
        return f"⚠️ [GPT 오류] {e}"


def gpt_summarize(topic: str, arts: list) -> str:
    """분야별 뉴스 요약 — 4개국 시각 통합, 사실 기반 전문가 브리핑."""
    if not arts:
        return "해당 분야 관련 기사를 찾을 수 없습니다."
    ctx = "\n".join(
        f"[{i+1}][{a.get('country','?')}] {a['title']} ({a['ago']})\n"
        f"  → {a['summary'][:200]}"
        for i, a in enumerate(arts[:10])
    )
    return _gpt(
        _EXPERT_SYSTEM,
        (
            f"■ 분야: {topic}\n"
            f"■ 수집 기사 (한국·미국·영국·일본·중국·독일):\n{ctx}\n\n"
            "위 기사들을 바탕으로 다음 형식으로 전문가 브리핑을 작성하세요:\n"
            "1. 📌 핵심 동향 (2문장, 수치·정책명 포함)\n"
            "2. 🌐 글로벌 시각 (한·미·영·일·중·독 공통점 또는 차이점 1문장)\n"
            "3. ⚡ 주목 포인트 (투자자·실무자가 반드시 알아야 할 1가지)\n"
            "각 항목은 기사 번호 [n]을 근거로 인용하세요."
        ),
        max_tokens=600,
    )


def gpt_top3(all_arts: list) -> str:
    """오늘의 주요뉴스 TOP3 — 글로벌 영향력 기준 선정."""
    if not all_arts:
        return ""
    ctx = "\n".join(
        f"[{i+1}][{a.get('topic','?')}][{a.get('country','?')}] "
        f"{a['title']} ({a['ago']})"
        for i, a in enumerate(all_arts[:30])
    )
    return _gpt(
        _EXPERT_SYSTEM,
        (
            f"■ 전체 기사:\n{ctx}\n\n"
            "오늘 가장 중요한 TOP 3 뉴스를 선정하세요.\n"
            "선정 기준: 글로벌 경제·시장에 미치는 영향력, 정책 변화 가능성, 투자자 주목도.\n"
            "형식:\n"
            "① [번호] 제목 | [국가] | [분야]\n"
            "   → 왜 중요한가: (사실 근거 1~2문장)\n"
            "   → 파급 효과: (투자·경제적 함의 1문장)\n"
        ),
        max_tokens=700,
    )


def gpt_market_analysis(all_arts: list) -> str:
    """AI 시장 분석 — 4개국 뉴스 통합 거시경제 브리핑."""
    ctx = "\n".join(
        f"[{i+1}][{a.get('country','?')}] {a['title']} ({a['ago']})"
        for i, a in enumerate(all_arts[:25])
    )
    now_str = now_kst().strftime("%Y년 %m월 %d일 %H:%M KST")
    return _gpt(
        _EXPERT_SYSTEM,
        (
            f"■ 분석 기준시: {now_str}\n"
            f"■ 한·미·영·일·중·독 주요 기사:\n{ctx}\n\n"
            "다음 형식으로 전문가 시장 분석 브리핑을 작성하세요:\n"
            "1. 📊 오늘의 시장 핵심 (3문장 이내, 수치 포함)\n"
            "2. 🌏 글로벌 매크로 흐름 (미국·영국·일본·중국·독일 동향과 한국 시장 연결, 2~3줄)\n"
            "3. 📈 주목 섹터/종목 시그널 (구체적 근거 포함, 2~3가지)\n"
            "4. ⚠️ 핵심 리스크 요인 (실현 가능성과 근거 포함, 1~2가지)\n"
            "5. 💡 오늘의 투자 인사이트 (객관적 근거 기반, 참고용 1문장)\n"
            "모든 분석은 제공된 기사의 사실에 근거하며, 추측은 명시적으로 표시합니다."
        ),
        max_tokens=900,
    )


def gpt_comment(wd: dict, city: str, sums: dict) -> str:
    """오늘의 한 마디 — 전문가 위트와 통찰의 조화."""
    cur   = wd.get("slots", {}).get("_cur", {})
    w_str = (
        f"{city} {cur.get('cond', '?')} "
        f"{cur.get('temp', '?')}°C 강수확률 {cur.get('rain', '?')}%"
    )
    ns = "\n".join(f"- {t}: {s[:120]}" for t, s in sums.items())
    return _gpt(
        (
            "당신은 경제 전문가이면서 따뜻한 유머 감각을 가진 아침 브리핑 앵커입니다. "
            "복잡한 경제 현실을 날씨와 버무려 청중이 '아, 맞아!'와 동시에 '재밌다'고 느낄 수 있는 "
            "촌철살인의 한 마디를 2~3문장으로 전합니다. 제공된 정보만 근거로 합니다."
        ),
        f"날씨: {w_str}\n주요 분야별 동향:\n{ns}\n\n오늘의 아침 한 마디를 작성해 주세요.",
        temperature=0.8,
        max_tokens=200,
    )


# ═══════════════════════════════════════════════════════════════
# 7. HTML 이메일 렌더러
# ═══════════════════════════════════════════════════════════════
COUNTRY_EMOJI = {
    "한국": "🇰🇷",
    "미국": "🇺🇸",
    "영국": "🇬🇧",
    "일본": "🇯🇵",
    "중국": "🇨🇳",
    "독일": "🇩🇪",
}


def _build_weather_html(wd: dict, city: str) -> str:
    slots = wd.get("slots", {})
    cur   = slots.get("_cur", {})
    if wd.get("error") or not cur:
        return "<p style='color:#e74c3c;'>⚠️ 날씨 조회 실패</p>"

    icon  = cur.get("cond", "🌡️").split()[0]
    cond  = " ".join(cur.get("cond", "").split()[1:])
    now_s = now_kst().strftime("%m/%d %H:%M 기준")

    slot_cells = ""
    for label, _ in WEATHER_SLOTS:
        s = slots.get(label)
        if s:
            rain_col = "#c0392b" if s["rain"] >= 70 else \
                       "#e67e22" if s["rain"] >= 40 else "#27ae60"
            slot_cells += f"""
<td style='padding:10px 8px;text-align:center;background:#fff;
           border-right:1px solid #e0ede0;vertical-align:top;'>
  <div style='font-size:11px;font-weight:800;color:#2d6a4f;'>{label}</div>
  <div style='font-size:20px;margin:4px 0;'>{s['cond'].split()[0]}</div>
  <div style='font-size:15px;font-weight:900;color:#1a3a5c;'>{s['temp']}°C</div>
  <div style='font-size:11px;color:#7a9ab5;'>체감 {s['feels']}°C</div>
  <div style='font-size:11px;font-weight:700;color:{rain_col};margin-top:4px;'>
    ☔{s['rain']}%</div>
</td>"""

    return f"""
<table style='width:100%;border-collapse:collapse;background:#e8f4fd;
              border-radius:12px;overflow:hidden;border:1px solid #b8d9f0;'>
  <tr>
    <td style='padding:16px 20px;background:linear-gradient(135deg,#e3f2fd,#d4e8f7);'>
      <div style='display:flex;align-items:center;gap:12px;'>
        <span style='font-size:40px;'>{icon}</span>
        <div>
          <div style='font-size:28px;font-weight:900;color:#1a3a5c;'>{cur['temp']}°C</div>
          <div style='font-size:13px;color:#2c5f8a;font-weight:700;'>
            {city} · 체감 {cur['feels']}°C · {cond}
          </div>
          <div style='font-size:12px;color:#5b8aaa;margin-top:4px;'>
            ☔{cur['rain']}% &nbsp; 💧{cur['hum']}% &nbsp; 💨{cur['wind']}km/h
          </div>
        </div>
        <div style='margin-left:auto;font-size:11px;color:#6b9ec4;'>{now_s}</div>
      </div>
    </td>
  </tr>
  <tr>
    <td style='padding:0;'>
      <table style='width:100%;border-collapse:collapse;'>
        <tr>{slot_cells}</tr>
      </table>
    </td>
  </tr>
</table>"""


def _build_stock_html(stocks: list) -> str:
    if not stocks:
        return "<p style='color:#aaa;'>종목 데이터 없음</p>"
    rows = ""
    for i, s in enumerate(stocks):
        up    = s["change"] >= 0
        icon  = "📈" if up else "📉"
        color = "#27ae60" if up else "#e74c3c"
        sign  = "+" if up else "-"
        rows += f"""
<tr style='border-bottom:1px solid #e8edf5;{"background:#f8fbff;" if i%2==0 else ""}'>
  <td style='padding:9px 10px;font-size:12px;font-weight:600;color:#1a3a5c;'>{s['name']}</td>
  <td style='padding:9px 10px;text-align:right;font-size:12px;font-weight:800;color:#333;'>
    {s['price']:,.0f}</td>
  <td style='padding:9px 10px;text-align:right;font-size:11px;color:{color};font-weight:700;'>
    {icon} {sign}{abs(s['pct']):.2f}%</td>
  <td style='padding:9px 10px;text-align:right;font-size:10px;color:#999;'>{s['currency']}</td>
</tr>"""
    return f"""
<table style='width:100%;border-collapse:collapse;font-size:12px;'>
  <thead>
    <tr style='background:#f0f4f8;border-bottom:2px solid #d4dce6;'>
      <td style='padding:8px 10px;color:#666;font-weight:600;text-align:left;'>종목</td>
      <td style='padding:8px 10px;color:#666;font-weight:600;text-align:right;'>현재가</td>
      <td style='padding:8px 10px;color:#666;font-weight:600;text-align:right;'>등락률</td>
      <td style='padding:8px 10px;color:#666;font-weight:600;text-align:right;'>통화</td>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""


def _build_macro_html(macros: list) -> str:
    if not macros:
        return "<p style='color:#aaa;'>지표 데이터 없음</p>"
    rows = ""
    for m in macros:
        up    = m["change"] >= 0
        icon  = "📈" if up else "📉"
        color = "#27ae60" if up else "#e74c3c"
        sign  = "+" if up else "-"
        rows += f"""
<tr style='border-bottom:1px solid #e0e5eb;'>
  <td style='padding:8px 10px;font-size:11px;font-weight:600;color:#333;'>{m['name']}</td>
  <td style='padding:8px 10px;text-align:right;font-size:11px;font-weight:800;color:#1a3a5c;'>
    {m['curr_s']} {m['unit']}</td>
  <td style='padding:8px 10px;text-align:right;font-size:10px;color:{color};font-weight:700;'>
    {icon} {sign}{m['pct_s']}%</td>
</tr>"""
    return f"""
<table style='width:100%;border-collapse:collapse;font-size:11px;'>
  <thead>
    <tr style='background:#f5f8fb;border-bottom:1px solid #d4dce6;'>
      <td style='padding:7px 10px;color:#666;font-weight:600;text-align:left;'>지표</td>
      <td style='padding:7px 10px;color:#666;font-weight:600;text-align:right;'>현재</td>
      <td style='padding:7px 10px;color:#666;font-weight:600;text-align:right;'>변화</td>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""


def _build_news_section_html(topic: str, arts: list) -> str:
    if not arts:
        return "<p style='color:#aaa;font-size:11px;'>해당 분야 기사 없음</p>"

    items = ""
    for i, a in enumerate(arts, 1):
        flag  = COUNTRY_EMOJI.get(a.get("country", ""), "🌐")
        link  = a.get("link", "#")
        src   = f" · {a['source']}" if a.get("source") else ""
        items += f"""
<div style='margin-bottom:14px;padding-bottom:14px;
            border-bottom:1px solid #eef2f7;'>
  <div style='font-size:10px;color:#999;margin-bottom:3px;'>
    [{i}] {flag} {a.get('country','?')}{src} · {a['ago']}
  </div>
  <div style='font-size:12px;font-weight:700;margin-bottom:5px;line-height:1.45;'>
    <a href="{link}" target="_blank"
       style='color:#1a3a5c;text-decoration:none;
              border-bottom:1px solid #c8d8ee;'>
      {a['title']}
    </a>
  </div>
  <div style='font-size:11px;color:#666;line-height:1.55;'>
    {a['summary'][:180]}
  </div>
</div>"""

    return f"<div style='margin:12px 0;'>{items}</div>"


def build_email_html(
    city: str, wd: dict, stocks: list, macros: list,
    topic_arts: dict, topic_sums: dict, top3: str,
    market: str, comment: str,
) -> str:
    date_s = date_str_kst()

    weather_html = _build_weather_html(wd, city)
    stock_html   = _build_stock_html(stocks)
    macro_html   = _build_macro_html(macros)

    top3_html    = f"<div style='font-size:12px;line-height:1.75;color:#333;'>{top3.replace(chr(10), '<br>')}</div>"
    market_html  = f"<div style='font-size:12px;line-height:1.75;color:#333;'>{market.replace(chr(10), '<br>')}</div>"
    comment_html = f"""<div style='font-size:13px;line-height:1.6;color:#2c5f8a;
                           font-weight:500;font-style:italic;
                           border-left:3px solid #40916c;padding-left:12px;'>
      "{comment}"
    </div>"""

    news_sections = ""
    for topic in TOPICS:
        arts     = topic_arts.get(topic, [])
        sum_text = topic_sums.get(topic, "")
        # 국가별 기사 수 카운트
        cnt = {c: sum(1 for a in arts if a.get("country") == c)
               for c in ["한국", "미국", "영국", "일본"]}
        cnt_str = " · ".join(
            f"{COUNTRY_EMOJI[c]} {v}건" for c, v in cnt.items() if v > 0
        )
        news_sections += f"""
<div style='margin:16px 0;border-top:1px solid #d8ead8;padding-top:14px;'>
  <div style='display:flex;align-items:center;justify-content:space-between;
              margin-bottom:8px;'>
    <h3 style='font-size:13px;color:#1b4332;font-weight:800;margin:0;'>{topic}</h3>
    <span style='font-size:10px;color:#888;'>{cnt_str}</span>
  </div>
  <div style='font-size:11px;line-height:1.65;color:#444;
              background:#f7faf7;border-radius:6px;padding:10px 12px;
              margin-bottom:10px;border-left:3px solid #40916c;'>
    {sum_text.replace(chr(10), '<br>')}
  </div>
  {_build_news_section_html(topic, arts)}
</div>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{MAIL_SUBJECT}</title>
  <style>
    @media print {{
      body {{ margin: 0; padding: 0; }}
      .page-break {{ page-break-before: always; margin-top: 20px; }}
      h2 {{ page-break-after: avoid; }}
      .briefing-section {{ page-break-inside: avoid; }}
      a {{ color: #1a3a5c !important; text-decoration: underline !important; }}
    }}
    @media screen {{
      body {{ background: #f5f5f5; }}
    }}
  </style>
</head>
<body style='font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
             "Helvetica Neue",Arial,sans-serif;
             margin:0;padding:0;color:#333;'>

<div style='max-width:660px;margin:0 auto;background:white;
            box-shadow:0 2px 12px rgba(0,0,0,.08);'>

  <!-- 헤더 -->
  <div class="briefing-header"
       style="background:linear-gradient(135deg,#1a472a,#2d6a4f,#40916c);
              padding:20px 22px 16px;">
    <h1 style="color:#fff;font-size:18px;margin:0 0 4px;font-weight:800;
               letter-spacing:-0.3px;">
      🌅 아침 브리핑
    </h1>
    <p style="color:rgba(255,255,255,.88);font-size:11px;margin:0;">
      {date_s} &nbsp;|&nbsp; GPT-4o-mini · KIS API · 4개국 경제신문
    </p>
    <div style="display:inline-block;background:rgba(255,255,255,.18);
                color:#fff;font-size:10px;font-weight:600;border-radius:14px;
                padding:3px 10px;margin-top:7px;border:1px solid rgba(255,255,255,.28);">
      📍 {city} &nbsp;|&nbsp; 🇰🇷 🇺🇸 🇬🇧 🇯🇵 🇨🇳 🇩🇪 6개국 5대 경제신문
    </div>
  </div>

  <div style="padding:20px 22px 28px;">

    <!-- 뉴스 소스 안내 -->
    <div style="background:#f0f7f0;border:1px solid #c8e6c9;border-radius:8px;
                padding:10px 14px;margin-bottom:16px;font-size:10px;color:#555;
                line-height:1.7;">
      <strong style="color:#1b4332;">📰 수집 대상 신문사</strong><br>
      🇰🇷 한경·매경·머니투데이·이데일리·파이낸셜뉴스 &nbsp;|&nbsp;
      🇺🇸 WSJ·Bloomberg·Reuters·CNBC·FT &nbsp;|&nbsp;
      🇬🇧 FT·Economist·Reuters UK·Guardian·BBC &nbsp;|&nbsp;
      🇯🇵 닛케이·Nikkei Asia·産経ビズ·Japan Times·NHK &nbsp;|&nbsp;
      🇨🇳 人民日報·新华社·财新·第一财经·南方都市报 &nbsp;|&nbsp;
      🇩🇪 Handelsblatt·FAZ·Süddeutsche·Reuters DE·Spiegel
    </div>

    <!-- 날씨 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:0 0 10px;font-weight:800;">
        🌤️ 날씨 — {city}
      </h2>
      {weather_html}
    </div>

    <!-- 거시경제지표 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        🌐 거시경제지표
        <span style="font-size:9px;color:#888;font-weight:400;">
          (코스피·코스닥·나스닥·S&amp;P·다우·닛케이·환율·원유·금)
        </span>
      </h2>
      <div style="border:1px solid #1a2a4a;border-radius:8px;overflow:hidden;">
        {macro_html}
      </div>
    </div>

    <!-- 관심주식 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        📈 관심종목 시세
      </h2>
      <div style="border:1px solid #e8edf5;border-radius:8px;overflow:hidden;">
        {stock_html}
        <div style="background:#f8fafc;padding:4px 10px;text-align:right;
                    font-size:9px;color:#cbd5e1;border-top:1px solid #e8edf5;">
          한국투자증권 KIS API (국내) · yfinance (해외) · 전일종가 기준
        </div>
      </div>
    </div>

    <!-- AI 시장 분석 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        📊 AI 시장 분석 브리핑
        <span style="font-size:9px;color:#888;font-weight:400;">
          (4개국 뉴스 통합 · 객관적 사실 기반)
        </span>
      </h2>
      {market_html}
    </div>

    <!-- TOP3 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        🔥 오늘의 주요뉴스 TOP 3
      </h2>
      {top3_html}
    </div>

    <!-- 한마디 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        💬 오늘의 한 마디
      </h2>
      {comment_html}
    </div>

    <!-- 분야별 뉴스 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        📰 분야별 뉴스
        <span style="font-size:9px;color:#888;font-weight:400;">
          최근 {NEWS_CUTOFF_DAYS}일 · 분야당 최대 14건
          (🇰🇷 4 + 🇺🇸 2 + 🇬🇧 2 + 🇯🇵 2 + 🇨🇳 2 + 🇩🇪 2)
          · 중복우선순위: 경제&gt;금융&gt;주식&gt;방산
        </span>
      </h2>
      {news_sections}
    </div>

  </div>

  <!-- 푸터 -->
  <div style="background:#f0f7f0;padding:12px 22px;text-align:center;
              border-top:1px solid #d8ead8;margin-top:12px;">
    <p style="font-size:9px;color:#999;margin:0;line-height:1.6;">
      ⚡ 6개국 5대 경제신문사 Google News RSS 기반 자동 생성 · 최근 {NEWS_CUTOFF_DAYS}일 기사<br>
      🇰🇷 한경·매경·머니투데이·이데일리·파이낸셜뉴스 &nbsp;
      🇺🇸 WSJ·Bloomberg·Reuters·CNBC·FT &nbsp;
      🇬🇧 FT·Economist·Reuters·Guardian·BBC<br>
      🇯🇵 닛케이·Nikkei Asia·産経ビズ·Japan Times·NHK &nbsp;
      🇨🇳 人民日報·新华社·财新·第一财经·南方都市报 &nbsp;
      🇩🇪 Handelsblatt·FAZ·Süddeutsche·Reuters DE·Spiegel<br>
      GPT 분석은 제공된 기사에만 근거합니다. 투자 결정은 본인 판단 하에 하세요.
    </p>
  </div>

</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════════
# 8. Make Webhook 발송
# ═══════════════════════════════════════════════════════════════
def send_to_make(html_body: str, subject: str) -> bool:
    sent_at = now_kst().strftime("%Y-%m-%d %H:%M KST")
    payload = {
        "html_body": html_body,
        "subject":   subject,
        "sent_at":   sent_at,
    }
    try:
        res = requests.post(
            MAKE_WEBHOOK_URL,
            json=payload,
            timeout=30,
            headers={"Content-Type": "application/json"},
        )
        if res.status_code in (200, 204):
            log.info(f"✅ Make Webhook 발송 성공: {res.status_code}")
            return True
        log.error(f"❌ Make Webhook 실패: {res.status_code} / {res.text[:200]}")
        return False
    except Exception as e:
        log.error(f"❌ Make Webhook 예외: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# 9. 메인 실행
# ═══════════════════════════════════════════════════════════════
def main():
    log.info("=" * 65)
    log.info(f"🌅 아침 브리핑 v24 생성 시작 — {date_str_kst()}")
    log.info(f"뉴스 소스: 6개국(🇰🇷🇺🇸🇬🇧🇯🇵🇨🇳🇩🇪) 각 5대 경제신문사")
    log.info(f"분야별 최대: 🇰🇷 4건 + 🇺🇸 2건 + 🇬🇧 2건 + 🇯🇵 2건 + 🇨🇳 2건 + 🇩🇪 2건 = 총 14건")
    log.info(f"중복 우선순위: 경제 > 금융 > 주식 > 방산")
    log.info("=" * 65)

    # ── 날씨 ──
    log.info("🌤️ [1/7] 날씨 조회...")
    wd = fetch_weather(CITY)

    # ── 주식 ──
    log.info("📈 [2/7] 주가 조회...")
    stocks = fetch_stock_prices(DEFAULT_TICKERS)

    # ── 거시경제지표 ──
    log.info("🌐 [3/7] 거시경제지표 조회 (DAX·상하이·위안·유로 포함)...")
    macros = fetch_macro_indicators()

    # ── 뉴스 수집 ──────────────────────────────────────────────
    log.info("📰 [4/7] 6개국 5대 경제신문 뉴스 수집 시작...")

    raw_pools: dict[str, list] = {}
    for topic in DEDUP_PRIORITY:
        kw   = TOPIC_KEYWORDS.get(topic, topic)
        pool = fetch_news_smart(topic, kw)
        raw_pools[topic] = pool
        log.info(f"  ✓ {topic}: {len(pool)}건 수집")

    # 우선순위 순서로 중복 URL 제거 후 기사 배정
    used_urls: set[str] = set()
    topic_arts: dict[str, list] = {}

    for topic in DEDUP_PRIORITY:
        candidates = raw_pools.get(topic, [])
        selected   = []
        for art in candidates:
            url = art.get("link", "").strip()
            if url and url in used_urls:
                continue
            selected.append(art)
            if url:
                used_urls.add(url)
            if len(selected) >= N_ARTICLES:
                break
        topic_arts[topic] = selected
        log.info(
            f"  ✓ {topic}: 후보 {len(candidates)}건 → "
            f"중복제거 후 {len(selected)}건 확정"
        )

    # ── GPT 요약 ──
    log.info("🤖 [5/7] 분야별 전문가 GPT 요약...")
    topic_sums: dict[str, str] = {}
    all_arts:   list[dict]     = []

    for topic in TOPICS:
        arts = topic_arts.get(topic, [])
        for a in arts:
            a["topic"] = topic
        all_arts.extend(arts)

        gsum = gpt_summarize(topic, arts)
        topic_sums[topic] = gsum
        log.info(f"  ✓ {topic}: 요약 완료")

    # ── TOP3 ──
    log.info("🔥 [6/7] TOP3 선정 및 AI 시장 분석...")
    top3   = gpt_top3(all_arts)
    market = gpt_market_analysis(all_arts)
    log.info("💬    한마디 생성...")
    comment = gpt_comment(wd, CITY, topic_sums)

    # ── HTML 빌드 ──
    log.info("🖥️  [7/7] HTML 이메일 빌드...")
    html_body = build_email_html(
        city=CITY,
        wd=wd,
        stocks=stocks,
        macros=macros,
        topic_arts=topic_arts,
        topic_sums=topic_sums,
        top3=top3,
        market=market,
        comment=comment,
    )

    with open("briefing_output.html", "w", encoding="utf-8") as f:
        f.write(html_body)
    log.info("💾 briefing_output.html 저장 완료")

    # ── Make Webhook 발송 ──
    log.info("📨 Make Webhook 발송...")
    subject = f"{MAIL_SUBJECT} — {now_kst().strftime('%Y/%m/%d')}"
    ok = send_to_make(html_body, subject)

    if ok:
        log.info("✅ 브리핑 발송 완료! (v24)")
    else:
        log.error("❌ 브리핑 발송 실패!")
        sys.exit(1)


if __name__ == "__main__":
    main()