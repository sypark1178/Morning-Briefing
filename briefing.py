#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌅 아침 브리핑 v26 — 6개국 뉴스 + 싱크탱크 + 정부정책 + 3대 펀드매니저 + 세계정치 분석
GitHub Actions + Make Webhook 자동 발송
v26  |  2026-04  |  KST 05:27 매일 실행

변경 사항 (v25 → v26):
- 📈주식 분야 뉴스 → 🌏 세계정치 분야 뉴스로 대체
  뉴스 출처: Politico (politico.com) + Reuters (reuters.com) RSS 피드
  분석 인사이트: 다론 아세모글루 · 조셉 나이 · 프란시스 후쿠야마 정치석학 시각 적용
    - 포용적 제도 vs 착취적 제도 (Acemoglu)
    - 소프트 파워 / 스마트 파워 (Joseph Nye)
    - 역사의 종언 / 정체성 정치 / 사회적 자본 (Fukuyama)
  진보·보수 균형 시각, 최대 5건 수집 (중요도 순)
- 거시경제지표 색상: 상승 → 붉은색(#e63946), 하락 → 파란색(#1d6fa5)
- 관심종목 색상: 상승 → 붉은색(#e63946), 하락 → 파란색(#1d6fa5)
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

# ── 도시 설정 ────────────────────────────────────────────────
CITY = "서울"
CITIES = {
    "서울": {"lat": 37.5665, "lon": 126.9780},
    "부산": {"lat": 35.1796, "lon": 129.0756},
    "인천": {"lat": 37.4563, "lon": 126.7052},
    "대전": {"lat": 36.3504, "lon": 127.3845},
    "대구": {"lat": 35.8714, "lon": 128.6014},
}

# ── 관심 종목 ────────────────────────────────────────────────
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

# ── v26: 뉴스 분야 3개 (📈주식 → 🌏세계정치 대체) ──────────────
TOPICS = ["🌏 세계정치", "💰 경제", "🏦 금융"]
DEDUP_PRIORITY = ["💰 경제", "🏦 금융", "🌏 세계정치"]

TOPIC_KEYWORDS = {
    "🌏 세계정치": "정치 외교 선거 국제관계 지정학 민주주의 권위주의",
    "💰 경제":     "경제 트럼프관세 환율 금리 부동산정책 GDP",
    "🏦 금융":     "금융 은행 증권 SMR 에너지 중앙은행",
}

TOPIC_KEYWORDS_EN = {
    "🌏 세계정치": "politics election democracy geopolitics international relations foreign policy",
    "💰 경제":     "economy tariff exchange rate interest rate GDP inflation",
    "🏦 금융":     "finance banking securities central bank Fed monetary",
}

TOPIC_KEYWORDS_JA = {
    "🌏 세계정치": "政治 外交 選挙 国際関係 地政学 民主主義",
    "💰 경제":     "経済 関税 為替 金利 GDP インフレ",
    "🏦 금융":     "金融 銀行 証券 日銀 金融政策",
}

TOPIC_KEYWORDS_ZH = {
    "🌏 세계정치": "政治 外交 选举 国际关系 地缘政治 民主",
    "💰 경제":     "经济 关税 汇率 利率 GDP 通胀",
    "🏦 금융":     "金融 银行 证券 央行 货币政策",
}

TOPIC_KEYWORDS_DE = {
    "🌏 세계정치": "Politik Wahl Demokratie Geopolitik internationale Beziehungen Diplomatie",
    "💰 경제":     "Wirtschaft Zölle Wechselkurs Zinsen BIP Inflation",
    "🏦 금융":     "Finanzen Banken EZB Geldpolitik Wertpapiere",
}

# ── 수집 설정 ────────────────────────────────────────────────
NEWS_CUTOFF_DAYS = 1
N_ARTICLES_PER_COUNTRY = {
    "한국": 4, "미국": 2, "영국": 2,
    "일본": 2, "중국": 2, "독일": 2,
}
N_ARTICLES = sum(N_ARTICLES_PER_COUNTRY.values())  # 총 14개

# v25 신규 수집 건수
N_THINKTANK  = 3   # 싱크탱크 최대 3건
N_GOVPOLICY  = 7   # 정부정책 최대 7건

# ── v26 신규: 세계정치 뉴스 피드 (Politico + Reuters) ────────────
N_POLITICS = 5   # 각 소스별 최대 5건 (중요도 순)

POLITICS_FEEDS = [
    # Politico RSS (글로벌/EU/미국 정치)
    "https://rss.politico.com/politics-news.xml",
    "https://rss.politico.com/congress.xml",
    "https://rss.politico.com/whitehouse.xml",
    "https://www.politico.eu/feed/",
    # Reuters RSS (세계 정치·외교·지정학)
    "https://feeds.reuters.com/reuters/politicsNews",
    "https://feeds.reuters.com/Reuters/worldNews",
    "https://feeds.reuters.com/reuters/topNews",
]

# ── 뉴스 피드: 6개국 5대 경제신문사 ──────────────────────────
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

# ── v25 신규: 한국 6대 싱크탱크 RSS 피드 ──────────────────────
# 1. 현대경제연구원 (hyundai-rei.com)
# 2. 삼성경제연구소 (SERI, samsung.com/seri)
# 3. LG경제연구원 (lgeri.com)
# 4. 한국경제연구원 (keri.org)
# 5. 한국금융연구원 (kif.re.kr)
# 6. 미래에셋증권 리서치센터
THINK_TANK_FEEDS = [
    "https://news.google.com/rss/search?q=현대경제연구원+보고서&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=삼성경제연구소+SERI+경제&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=LG경제연구원+전망&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=한국경제연구원+keri+경제&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=한국금융연구원+금융&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=미래에셋증권+리서치+주식&hl=ko&gl=KR&ceid=KR:ko",
]

THINK_TANK_NAMES = [
    "현대경제연구원", "삼성경제연구소(SERI)",
    "LG경제연구원", "한국경제연구원",
    "한국금융연구원", "미래에셋증권 리서치",
]

# ── v25 신규: 한국 정부 경제·금융·부동산 정책 RSS 피드 ───────
GOV_POLICY_FEEDS = [
    "https://news.google.com/rss/search?q=기획재정부+경제정책+발표&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=금융위원회+정책+발표+규제&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=국토교통부+부동산+정책+발표&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=한국은행+금리+통화정책+결정&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=금융감독원+정책+규제+발표&hl=ko&gl=KR&ceid=KR:ko",
    "https://news.google.com/rss/search?q=정부+경제정책+주식+부동산+발표&hl=ko&gl=KR&ceid=KR:ko",
]

# ── 거시경제지표 (yfinance, 14개) ─────────────────────────────
MACRO_INDICATORS = [
    ("코스피",            "^KS11",    "pt",    2),
    ("코스닥",            "^KQ11",    "pt",    2),
    ("나스닥",            "^IXIC",    "pt",    2),
    ("S&P 500",          "^GSPC",    "pt",    2),
    ("다우존스",          "^DJI",     "pt",    2),
    ("닛케이 225",        "^N225",    "pt",    2),
    ("DAX (독일)",        "^GDAXI",   "pt",    2),
    ("상하이종합 (중국)", "000001.SS","pt",    2),
    ("원/달러 환율",      "KRW=X",    "원",    1),
    ("원/엔 환율",        "JPYKRW=X", "원",    2),
    ("원/위안 환율",      "CNYKRW=X", "원",    2),
    ("원/유로 환율",      "EURKRW=X", "원",    1),
    ("WTI 원유",          "CL=F",     "$/bbl", 2),
    ("금 선물",           "GC=F",     "$/oz",  2),
]

MAIL_SUBJECT = "🌅 오늘의 아침 브리핑"


# ═══════════════════════════════════════════════════════════════
# 2. 유틸리티
# ═══════════════════════════════════════════════════════════════
def now_kst() -> datetime:
    return datetime.now(KST)


def date_str_kst() -> str:
    n  = now_kst()
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
# 2-B. 번역 함수 (영어·일본어·중국어·독일어 → 한국어)
# ═══════════════════════════════════════════════════════════════
_translation_cache: dict[str, str] = {}


def translate_to_korean(text: str) -> str:
    if not text or len(text) < 5:
        return text
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
KIS_BASE_URL  = "https://openapivts.koreainvestment.com:29443"
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
        raw   = raw.strip()
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
# 5. 뉴스 수집 (6개국 5대 경제신문사 RSS)
# ═══════════════════════════════════════════════════════════════
def _build_feed_url(country: str, keyword: str) -> list[str]:
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
        domain = base_url.split("q=")[1].split("&")[0] if "q=" in base_url else ""
        combined = f"{domain} {kw}".strip() if domain else kw
        new_url = (
            f"https://news.google.com/rss/search?"
            f"q={quote(combined)}&hl={hl}&gl={gl}&ceid={gl}:{ceid_lang}"
        )
        urls.append(new_url)
    return urls


def _fetch_rss_articles(
    feed_urls: list[str],
    country: str,
    cutoff: datetime,
    keyword_filter: str = "",
    fetch_size: int = 10,
    translate: bool = True,
) -> list[dict]:
    """
    공통 RSS 수집 함수.
    여러 피드 URL에서 기사를 수집하고, 번역 옵션을 적용.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    }
    all_arts = []
    for feed_url in feed_urls:
        try:
            response = requests.get(feed_url, headers=headers, timeout=10)
            response.raise_for_status()
            feed = feedparser.parse(response.content)
            if not feed.entries:
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
                if translate and country != "한국":
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
                        if isinstance(e.get("source"), dict) else ""
                    ),
                }
                if keyword_filter:
                    kws  = keyword_filter.lower().split()
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
    seen: set[str] = set()
    deduped = []
    for a in all_arts:
        t = a["title"][:30]
        if t not in seen:
            seen.add(t)
            deduped.append(a)
    return deduped


def fetch_news_by_country(
    country: str, topic: str = "", keyword: str = "",
    n: int = 5, pool: int = 0
) -> list[dict]:
    fetch_size = pool if pool > n else n * 3
    cutoff     = datetime.now(timezone.utc) - timedelta(days=NEWS_CUTOFF_DAYS)
    if keyword:
        feed_urls = _build_feed_url(country, topic if topic else keyword)
    else:
        feed_urls = NEWS_FEEDS.get(country, [])
    arts = _fetch_rss_articles(
        feed_urls, country, cutoff,
        keyword_filter=keyword,
        fetch_size=fetch_size,
        translate=(country != "한국"),
    )
    log.info(f"  ✓ 뉴스 수집 [{country}]: {len(arts[:fetch_size])}건")
    return arts[:fetch_size]


def _gpt_select_by_topic(topic: str, ctx: str, count: int) -> list[int]:
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


def fetch_news_smart(topic: str, keywords_ko: str) -> list[dict]:
    results = []
    for country in ["한국", "미국", "영국", "일본", "중국", "독일"]:
        needed = N_ARTICLES_PER_COUNTRY[country]
        arts   = fetch_news_by_country(
            country, topic=topic, keyword=keywords_ko, n=needed, pool=needed * 3
        )
        if len(arts) < needed:
            arts_all = fetch_news_by_country(country, keyword="", n=needed * 3, pool=needed * 5)
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


# ═══════════════════════════════════════════════════════════════
# 5-B. 싱크탱크 수집 (v25 신규)
# ═══════════════════════════════════════════════════════════════
def fetch_thinktank_news() -> list[dict]:
    """
    한국 6대 싱크탱크 보고서·분석자료 수집.
    각 기관당 최신 기사를 수집하여 상위 N_THINKTANK건 반환.
    """
    cutoff    = datetime.now(timezone.utc) - timedelta(days=3)  # 3일 이내
    all_arts  = []
    for feed_url, tank_name in zip(THINK_TANK_FEEDS, THINK_TANK_NAMES):
        arts = _fetch_rss_articles(
            [feed_url], "한국", cutoff,
            fetch_size=3, translate=False
        )
        for a in arts[:1]:  # 기관당 최대 1건
            a["thinktank"] = tank_name
            all_arts.append(a)

    all_arts.sort(key=lambda x: x["_dt"], reverse=True)
    selected = all_arts[:N_THINKTANK]
    log.info(f"✅ 싱크탱크 수집: {len(selected)}건 / 목표 {N_THINKTANK}건")
    return selected


# ═══════════════════════════════════════════════════════════════
# 5-C. 정부 경제정책 수집 (v25 신규)
# ═══════════════════════════════════════════════════════════════
def fetch_govpolicy_news() -> list[dict]:
    """
    한국 정부의 경제·금융·주식·부동산 정책 발표 수집.
    기획재정부·금융위원회·국토교통부·한국은행·금융감독원 등.
    """
    cutoff   = datetime.now(timezone.utc) - timedelta(days=NEWS_CUTOFF_DAYS)
    all_arts = _fetch_rss_articles(
        GOV_POLICY_FEEDS, "한국", cutoff,
        fetch_size=N_GOVPOLICY * 2,
        translate=False,
    )
    selected = all_arts[:N_GOVPOLICY]
    log.info(f"✅ 정부정책 수집: {len(selected)}건 / 목표 {N_GOVPOLICY}건")
    return selected


# ═══════════════════════════════════════════════════════════════
# 5-D. 세계정치 뉴스 수집 (v26 신규 — Politico + Reuters)
# ═══════════════════════════════════════════════════════════════
def fetch_politics_news() -> list[dict]:
    """
    Politico + Reuters 에서 세계 정치 뉴스를 수집.
    정치석학(아세모글루·나이·후쿠야마) 시각으로 중요도 기준 최대 N_POLITICS건 반환.
    """
    cutoff   = datetime.now(timezone.utc) - timedelta(days=NEWS_CUTOFF_DAYS)
    all_arts = _fetch_rss_articles(
        POLITICS_FEEDS,
        "미국",          # 영어 피드이므로 번역 적용
        cutoff,
        keyword_filter="",
        fetch_size=N_POLITICS * 4,
        translate=True,
    )
    # 정치 관련성 필터링 (느슨한 키워드 — 거의 모든 정치 뉴스 포함)
    POLITICS_KW = [
        "politic", "election", "government", "democracy", "diplomacy",
        "president", "congress", "senate", "parliament", "minister",
        "geopolit", "sanction", "treaty", "nato", "united nations",
        "정치", "선거", "외교", "민주", "대통령", "의회", "지정학",
    ]
    filtered = []
    for a in all_arts:
        body = (a["title"] + " " + a.get("summary", "")).lower()
        if any(kw in body for kw in POLITICS_KW):
            filtered.append(a)

    # GPT 로 중요도 순 상위 N_POLITICS개 선별
    if len(filtered) > N_POLITICS:
        ctx = "\n".join(
            f"[{i+1}] {a['title']}"
            for i, a in enumerate(filtered[:20])
        )
        try:
            r = client.chat.completions.create(
                model="gpt-4o-mini",
                temperature=0.1,
                max_tokens=80,
                messages=[
                    {"role": "system",
                     "content": (
                         "You are a political science expert. "
                         "Select the most globally significant political news articles. "
                         "Return ONLY a JSON array of 0-based indices, e.g. [0,2,4,1,3]"
                     )},
                    {"role": "user",
                     "content": (
                         f"Select top {N_POLITICS} most important political news "
                         f"(balance progressive/conservative perspectives, "
                         f"prioritize geopolitics, democracy, institutions, power dynamics):\n{ctx}"
                     )},
                ],
            )
            raw  = r.choices[0].message.content.strip()
            idxs = json.loads(raw)
            filtered = [filtered[i] for i in idxs if 0 <= i < len(filtered)]
        except Exception as e:
            log.warning(f"⚠️ 정치뉴스 GPT 선별 실패: {e}")
            filtered = filtered[:N_POLITICS]
    else:
        filtered = filtered[:N_POLITICS]

    for a in filtered:
        a["source_type"] = "politics"
    log.info(f"✅ 세계정치 뉴스 수집: {len(filtered)}건 / 목표 {N_POLITICS}건")
    return filtered


# ═══════════════════════════════════════════════════════════════
# 6. GPT 분석/요약 — v25 강화
# ═══════════════════════════════════════════════════════════════

# ── 전문가 시스템 (경제·시장 기사 요약용) ────────────────────
_EXPERT_SYSTEM = (
    "당신은 CFA·FRM 자격증을 보유한 20년 경력의 글로벌 거시경제·투자 전문가입니다. "
    "블룸버그·WSJ·닛케이·FT·Handelsblatt에 기고 이력이 있으며 "
    "현재 국내 대형 자산운용사 수석 이코노미스트입니다.\n"
    "분석 원칙:\n"
    "① 제공된 뉴스 기사의 객관적 사실만을 근거로 분석합니다.\n"
    "② 수치·지표·정책명 등 사실관계를 정확히 인용하고, 근거가 없는 추측은 '~가능성' 또는 '~우려'로 표현합니다.\n"
    "③ 단편적 사건이 아닌 글로벌 거시 흐름과의 연결고리를 제시합니다.\n"
    "④ 투자 판단은 참고용임을 명시하고, 균형 있는 리스크/기회 시각을 유지합니다.\n"
    "⑤ 한국·미국·영국·일본·중국·독일 6개국 관점을 통합하여 입체적 분석을 제공합니다."
)

# ── v25 신규: 3대 펀드매니저 통합 시스템 ─────────────────────
_FUND_MANAGER_SYSTEM = (
    "당신은 워렌 버핏(Warren Buffett), 피터 린치(Peter Lynch), 조지 소로스(George Soros)의 "
    "투자 철학을 통합적으로 체화한 세계 최고 수준의 펀드매니저입니다.\n\n"
    "■ 주식 가격 3대 결정 요소 (분석 프레임워크):\n"
    "  1. 기업 실적(Earnings): EPS 성장세가 주가의 핵심 동력 (Bankrate, 2026)\n"
    "  2. 거시 경제(Macro): 금리·인플레이션·환율이 주식 상대 매력도를 결정 (OECD, 2023)\n"
    "  3. 투자 심리(Sentiment): 공포·탐욕 지수가 단기 주가를 펀더멘털 대비 과열·급락시킴 (Zacks, 2026)\n\n"
    "■ 3대 거장의 핵심 철학:\n"
    "  🏦 버핏(Buffett): 경제적 해자·내재가치·ROE·현금창출력·경영진 도덕성 — 초장기 보유\n"
    "  📈 린치(Lynch): PEG 배수·이익 성장 스토리·GARP — '아는 것에 투자', 중장기\n"
    "  🌊 소로스(Soros): 재귀성·시장 왜곡·거품 형성/붕괴 — 시장의 오류 포착, 단중기\n\n"
    "모든 분석은 제공된 정보의 객관적 사실에만 근거하며, 추측은 '~가능성', '~우려'로 명시합니다. "
    "투자 판단은 참고용이며 최종 결정은 투자자 본인의 판단에 따릅니다."
)

# ── v26 신규: 3대 정치석학 통합 시스템 ───────────────────────────
_POLITICAL_SCHOLAR_SYSTEM = (
    "당신은 다론 아세모글루(Daron Acemoglu), 조셉 나이(Joseph Nye), 프란시스 후쿠야마(Francis Fukuyama)의 "
    "정치·국제관계 이론을 통합적으로 체화한 세계 최고 수준의 정치 분석가입니다.\n\n"
    "■ 3대 석학의 핵심 분석 프레임:\n"
    "  🏛️ 아세모글루(Acemoglu): 포용적 제도(Inclusive Institutions) vs 착취적 제도(Extractive Institutions) — "
    "국가 번영과 쇠퇴의 근원은 제도적 구조에 있으며, 포용적 정치·경제 제도가 지속 성장을 낳고 "
    "착취적 제도는 엘리트 이익을 위해 다수를 배제해 장기 침체를 초래함\n"
    "  🌐 조셉 나이(Joseph Nye): 소프트 파워(Soft Power) / 스마트 파워(Smart Power) — "
    "군사·경제적 하드 파워와 문화·가치·외교의 소프트 파워를 결합한 스마트 파워가 "
    "21세기 국제 영향력의 핵심; 매력과 설득을 통한 원하는 결과 달성\n"
    "  📜 후쿠야마(Fukuyama): 역사의 종언(End of History) · 정체성 정치(Identity Politics) · "
    "사회적 자본(Trust/Social Capital) — 자유민주주의의 보편적 확산 가능성, 집단 정체성이 "
    "현대 정치를 재편하는 방식, 사회 신뢰 자본이 민주주의와 경제 발전의 토대임\n\n"
    "■ 분석 원칙:\n"
    "① 진보와 보수의 균형 잡힌 시각으로 사실에 근거한 분석을 제공합니다.\n"
    "② 단편적 사건이 아닌 역사적·구조적 맥락과의 연결고리를 제시합니다.\n"
    "③ 세 석학의 이론 중 해당 사건에 가장 관련성 높은 프레임을 적용합니다.\n"
    "④ 지정학적 리스크와 민주주의·권위주의 동학을 균형있게 평가합니다.\n"
    "⑤ 분석은 제공된 뉴스 사실에만 근거하며, 추측은 '~가능성', '~우려'로 명시합니다."
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
    """분야별 뉴스 요약 — 6개국 시각 통합, 사실 기반 전문가 브리핑."""
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


def gpt_summarize_thinktank(arts: list) -> str:
    """싱크탱크 보고서 요약 — 핵심 경제·투자 시사점 추출."""
    if not arts:
        return "싱크탱크 관련 자료를 찾을 수 없습니다."
    ctx = "\n".join(
        f"[{i+1}][{a.get('thinktank', '?')}] {a['title']} ({a['ago']})\n"
        f"  → {a['summary'][:250]}"
        for i, a in enumerate(arts)
    )
    return _gpt(
        _EXPERT_SYSTEM,
        (
            f"■ 한국 싱크탱크 최신 보고서·분석자료:\n{ctx}\n\n"
            "각 기관의 보고서를 다음 형식으로 요약하세요 (기관별로 구분):\n"
            "【기관명】\n"
            "• 핵심 메시지: (1~2문장, 주요 수치·전망 포함)\n"
            "• 투자 시사점: (1문장, 실무적 함의)\n\n"
            "제공된 사실에만 근거하고, 추측은 '~가능성', '~우려'로 표현하세요."
        ),
        max_tokens=500,
    )


def gpt_summarize_govpolicy(arts: list) -> str:
    """정부 경제정책 발표 요약 — 경제·금융·주식·부동산 분야별 정리."""
    if not arts:
        return "정부 정책 관련 기사를 찾을 수 없습니다."
    ctx = "\n".join(
        f"[{i+1}] {a['title']} ({a['ago']})\n"
        f"  → {a['summary'][:200]}"
        for i, a in enumerate(arts)
    )
    return _gpt(
        _EXPERT_SYSTEM,
        (
            f"■ 한국 정부 경제·금융·주식·부동산 정책 발표:\n{ctx}\n\n"
            "아래 형식으로 분야별로 분류하여 정리하세요:\n"
            "📊 경제 정책: (해당 기사가 있을 경우)\n"
            "🏦 금융 정책: (해당 기사가 있을 경우)\n"
            "📈 주식·자본시장 정책: (해당 기사가 있을 경우)\n"
            "🏠 부동산 정책: (해당 기사가 있을 경우)\n"
            "각 항목은 '정책명/내용 → 시장 영향' 형식으로 1~2문장 작성.\n"
            "해당 분야 발표가 없으면 해당 항목을 생략하세요.\n"
            "수치와 정책명을 정확히 인용하세요."
        ),
        max_tokens=600,
    )


def gpt_summarize_politics(arts: list) -> str:
    """
    v26 신규: 세계정치 뉴스 분석
    — 아세모글루·나이·후쿠야마 3대 정치석학 프레임 적용
    — 진보·보수 균형 시각
    """
    if not arts:
        return "세계정치 관련 기사를 찾을 수 없습니다."
    ctx = "\n".join(
        f"[{i+1}] {a['title']} ({a['ago']})\n"
        f"  → {a.get('summary', '')[:250]}"
        for i, a in enumerate(arts)
    )
    return _gpt(
        _POLITICAL_SCHOLAR_SYSTEM,
        (
            f"■ 오늘의 세계정치 주요 뉴스 (Politico · Reuters):\n{ctx}\n\n"
            "위 기사들을 3대 정치석학의 프레임으로 분석하여 아래 형식으로 전문가 정치 브리핑을 작성하세요:\n\n"
            "📌 오늘의 핵심 정치 동향 (2~3문장, 주요 사건·인물·수치 포함)\n\n"
            "🏛️ 아세모글루 시각 — 포용적 vs 착취적 제도 관점:\n"
            "  오늘 뉴스에서 나타나는 제도적 포용성·착취성의 징후와 함의 (1~2문장)\n\n"
            "🌐 조셉 나이 시각 — 소프트/스마트 파워 관점:\n"
            "  관련 국가들의 소프트 파워·하드 파워 동학 분석 (1~2문장)\n\n"
            "📜 후쿠야마 시각 — 정체성 정치·사회적 자본·민주주의 관점:\n"
            "  민주주의 후퇴·강화, 정체성 정치, 사회 신뢰와의 연관성 (1~2문장)\n\n"
            "⚖️ 진보·보수 균형 평가:\n"
            "  진보적 관점에서의 해석 / 보수적 관점에서의 해석 (각 1문장)\n\n"
            "⚡ 투자자·정책입안자 주목 포인트 (지정학적 리스크 또는 기회, 1가지)\n\n"
            "각 항목은 기사 번호 [n]을 근거로 인용하세요. "
            "진보와 보수 어느 쪽으로도 치우치지 않은 균형 잡힌 시각을 유지하세요."
        ),
        max_tokens=900,
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


def gpt_market_analysis(
    all_arts: list,
    thinktank_sum: str,
    govpolicy_sum: str,
    macros: list,
) -> str:
    """
    v25 강화: AI 시장 분석 브리핑
    - 주식 3대 요소(기업실적·거시경제·투자심리) 프레임 적용
    - 3대 펀드매니저(버핏·린치·소로스) 통합 시각
    - 싱크탱크·정부정책까지 종합 반영
    """
    ctx_news = "\n".join(
        f"[{i+1}][{a.get('country','?')}] {a['title']} ({a['ago']})"
        for i, a in enumerate(all_arts[:25])
    )
    # 거시지표 요약
    macro_ctx = "\n".join(
        f"{m['name']}: {m['curr_s']} {m['unit']} "
        f"({'▲' if m['change'] >= 0 else '▼'}{m['pct_s']}%)"
        for m in macros if m.get('curr', 0) != 0
    )
    now_str = now_kst().strftime("%Y년 %m월 %d일 %H:%M KST")
    return _gpt(
        _FUND_MANAGER_SYSTEM,
        (
            f"■ 분석 기준시: {now_str}\n\n"
            f"■ 거시경제지표 (현재):\n{macro_ctx}\n\n"
            f"■ 한·미·영·일·중·독 주요 기사:\n{ctx_news}\n\n"
            f"■ 싱크탱크 분석 요약:\n{thinktank_sum[:400]}\n\n"
            f"■ 정부 정책 발표 요약:\n{govpolicy_sum[:400]}\n\n"
            "위 모든 정보를 종합하여, 3대 요소(기업실적·거시경제·투자심리) 프레임과 "
            "3대 펀드매니저 시각을 적용해 다음 형식으로 시장 분석 브리핑을 작성하세요:\n\n"
            "📊 오늘의 시장 핵심 (3대 요소 관점, 3문장 이내·수치 포함)\n"
            "  ▸ 기업실적(Earnings): 실적·EPS 관련 동향\n"
            "  ▸ 거시경제(Macro): 금리·환율·인플레이션 동향\n"
            "  ▸ 투자심리(Sentiment): 시장 공포/탐욕 및 심리 지표\n\n"
            "🌏 글로벌 매크로 흐름 (미·영·일·중·독 동향과 한국 시장 연결, 2~3줄)\n\n"
            "📈 주목 섹터/종목 시그널 (구체적 근거 포함, 2~3가지)\n\n"
            "⚠️ 핵심 리스크 요인 (실현 가능성과 근거 포함, 1~2가지)\n\n"
            "🎯 3대 거장의 오늘 시각\n"
            "  🏦 버핏 관점: (해자·내재가치 기준, 1문장)\n"
            "  📈 린치 관점: (성장스토리·PEG 기준, 1문장)\n"
            "  🌊 소로스 관점: (재귀성·시장왜곡 기준, 1문장)\n\n"
            "모든 분석은 제공된 정보의 사실에 근거하며, 추측은 반드시 명시합니다."
        ),
        max_tokens=1200,
    )


def gpt_investment_insight(
    all_arts: list,
    thinktank_sum: str,
    govpolicy_sum: str,
    market_analysis: str,
    stocks: list,
    macros: list,
) -> str:
    """
    v25 신규: 투자 인사이트 + 관심종목 3대 펀드매니저 피드백
    - 전문가 투자 인사이트 (2~3문장)
    - 관심종목별 버핏·린치·소로스 관점 피드백
    - 주의 종목 경고
    """
    # 관심종목 현황 컨텍스트
    stock_ctx = "\n".join(
        f"  {s['name']} ({s['ticker']}): {s['price']:,.0f}원 "
        f"{'▲' if s['change'] >= 0 else '▼'}{abs(s['pct']):.2f}% | {s.get('currency','KRW')}"
        for s in stocks
        if s.get("price", 0) > 0
    )
    macro_ctx = "\n".join(
        f"  {m['name']}: {m['curr_s']} {m['unit']} ({'▲' if m['change'] >= 0 else '▼'}{m['pct_s']}%)"
        for m in macros[:8] if m.get("curr", 0) != 0
    )
    news_ctx = "\n".join(
        f"[{i+1}][{a.get('country','?')}] {a['title']}"
        for i, a in enumerate(all_arts[:20])
    )
    return _gpt(
        _FUND_MANAGER_SYSTEM,
        (
            f"■ 오늘의 시장 분석 요약:\n{market_analysis[:600]}\n\n"
            f"■ 거시지표:\n{macro_ctx}\n\n"
            f"■ 싱크탱크 시사점:\n{thinktank_sum[:300]}\n\n"
            f"■ 정부 정책:\n{govpolicy_sum[:300]}\n\n"
            f"■ 주요 뉴스:\n{news_ctx}\n\n"
            f"■ 관심종목 현황:\n{stock_ctx}\n\n"
            "위 정보를 종합하여 아래 두 파트로 작성하세요:\n\n"
            "【파트 1. 💡 오늘의 투자 인사이트】\n"
            "3대 요소(기업실적·거시경제·투자심리)와 오늘의 시장 환경을 고려한 "
            "전문가 수준의 투자 인사이트를 2~3문장으로 작성하세요. "
            "막연한 조언이 아닌, 오늘의 구체적 데이터에 근거한 통찰을 제시하세요.\n\n"
            "【파트 2. 📌 관심종목 3대 거장 피드백】\n"
            "각 관심종목에 대해 오늘의 시장 분석과 연관지어 아래 형식으로 작성하세요:\n"
            "종목명 (티커) | 현재가 | 등락률\n"
            "  🏦 버핏 시각: (경제적 해자·내재가치·현금창출 관점, 1문장)\n"
            "  📈 린치 시각: (성장스토리·PEG·사업이해 관점, 1문장)\n"
            "  🌊 소로스 시각: (시장심리·재귀성·추세 관점, 1문장)\n"
            "  ⚡ 종합 판단: [주목 / 관망 / 주의 / 경고] — 이유 1문장\n\n"
            "특히 오늘 시장 상황에서 주의가 필요한 종목은 명확히 경고 표시하세요. "
            "모든 분석은 오늘의 실제 데이터와 뉴스에 근거해야 하며, "
            "투자 판단은 참고용임을 명시하세요."
        ),
        max_tokens=1500,
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
    "한국": "🇰🇷", "미국": "🇺🇸", "영국": "🇬🇧",
    "일본": "🇯🇵", "중국": "🇨🇳", "독일": "🇩🇪",
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
        # v26: 상승 → 붉은색, 하락 → 파란색 (한국 증권 관례)
        color = "#e63946" if up else "#1d6fa5"
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
        # v26: 상승 → 붉은색, 하락 → 파란색 (한국 증권 관례)
        color = "#e63946" if up else "#1d6fa5"
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


def _build_thinktank_html(arts: list, summary: str) -> str:
    """싱크탱크 섹션 HTML."""
    if not arts and not summary:
        return "<p style='color:#aaa;font-size:11px;'>싱크탱크 자료 없음</p>"
    items = ""
    for i, a in enumerate(arts, 1):
        tank = a.get("thinktank", "")
        link = a.get("link", "#")
        items += f"""
<div style='margin-bottom:12px;padding:10px 12px;background:#fff;
            border-radius:8px;border-left:3px solid #7c3aed;'>
  <div style='font-size:10px;color:#7c3aed;font-weight:800;margin-bottom:3px;'>
    🏛️ {tank} · {a['ago']}
  </div>
  <div style='font-size:12px;font-weight:700;margin-bottom:4px;'>
    <a href="{link}" target="_blank"
       style='color:#1a3a5c;text-decoration:none;border-bottom:1px solid #c8b8f0;'>
      {a['title']}
    </a>
  </div>
  <div style='font-size:11px;color:#666;line-height:1.5;'>{a['summary'][:200]}</div>
</div>"""
    summary_html = f"""
<div style='font-size:12px;line-height:1.75;color:#333;background:#f5f0ff;
            border-radius:6px;padding:10px 12px;margin-bottom:12px;
            border-left:3px solid #7c3aed;'>
  {summary.replace(chr(10), '<br>')}
</div>"""
    return summary_html + f"<div style='margin-top:10px;'>{items}</div>"


def _build_govpolicy_html(arts: list, summary: str) -> str:
    """정부정책 섹션 HTML."""
    if not arts and not summary:
        return "<p style='color:#aaa;font-size:11px;'>정부 정책 발표 자료 없음</p>"
    items = ""
    for i, a in enumerate(arts, 1):
        link = a.get("link", "#")
        items += f"""
<div style='margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid #eef2f7;'>
  <div style='font-size:10px;color:#0369a1;margin-bottom:3px;'>
    [{i}] 🏛️ 정부발표 · {a['ago']}
  </div>
  <div style='font-size:12px;font-weight:700;margin-bottom:4px;'>
    <a href="{link}" target="_blank"
       style='color:#1a3a5c;text-decoration:none;border-bottom:1px solid #bae6fd;'>
      {a['title']}
    </a>
  </div>
  <div style='font-size:11px;color:#555;'>{a['summary'][:150]}</div>
</div>"""
    summary_html = f"""
<div style='font-size:12px;line-height:1.75;color:#333;background:#f0f9ff;
            border-radius:6px;padding:10px 12px;margin-bottom:12px;
            border-left:3px solid #0369a1;'>
  {summary.replace(chr(10), '<br>')}
</div>"""
    return summary_html + f"<div style='margin-top:10px;'>{items}</div>"


def _build_politics_html(arts: list, summary: str) -> str:
    """v26 신규: 세계정치 뉴스 섹션 HTML."""
    if not arts and not summary:
        return "<p style='color:#aaa;font-size:11px;'>세계정치 뉴스 없음</p>"

    SOURCE_BADGE = {
        "politico": ("#c0392b", "POLITICO"),
        "reuters":  ("#1a6496", "REUTERS"),
    }

    def _source_badge(link: str) -> str:
        if "politico" in link.lower():
            bg, label = SOURCE_BADGE["politico"]
        elif "reuters" in link.lower():
            bg, label = SOURCE_BADGE["reuters"]
        else:
            bg, label = ("#555", "NEWS")
        return (
            f"<span style='background:{bg};color:#fff;font-size:9px;"
            f"font-weight:800;padding:1px 6px;border-radius:3px;"
            f"margin-right:5px;'>{label}</span>"
        )

    items = ""
    for i, a in enumerate(arts, 1):
        link  = a.get("link", "#")
        badge = _source_badge(link)
        items += f"""
<div style='margin-bottom:14px;padding:10px 12px;background:#fff;
            border-radius:8px;border-left:3px solid #8b1a1a;
            box-shadow:0 1px 3px rgba(0,0,0,.06);'>
  <div style='font-size:10px;color:#666;margin-bottom:4px;display:flex;align-items:center;'>
    {badge}
    <span>[{i}] 🌏 · {a.get('ago','')}</span>
  </div>
  <div style='font-size:12px;font-weight:700;margin-bottom:5px;line-height:1.45;'>
    <a href="{link}" target="_blank"
       style='color:#1a3a5c;text-decoration:none;border-bottom:1px solid #c8b0b0;'>
      {a['title']}
    </a>
  </div>
  <div style='font-size:11px;color:#555;line-height:1.55;'>{a.get('summary','')[:200]}</div>
</div>"""

    summary_html = f"""
<div style='font-size:12px;line-height:1.8;color:#333;background:#fff8f8;
            border-radius:6px;padding:12px 14px;margin-bottom:14px;
            border-left:4px solid #8b1a1a;'>
  {summary.replace(chr(10), '<br>')}
</div>"""
    return summary_html + f"<div style='margin-top:10px;'>{items}</div>"


def _build_news_section_html(topic: str, arts: list) -> str:
    """분야별 뉴스 기사 목록 HTML (6개국 이모지 포함)."""
    if not arts:
        return "<p style='color:#aaa;font-size:11px;'>해당 분야 기사 없음</p>"
    items = ""
    for i, a in enumerate(arts, 1):
        flag  = COUNTRY_EMOJI.get(a.get("country", ""), "🌐")
        link  = a.get("link", "#")
        src   = f" · {a['source']}" if a.get("source") else ""
        items += f"""
<div style='margin-bottom:14px;padding-bottom:14px;border-bottom:1px solid #eef2f7;'>
  <div style='font-size:10px;color:#999;margin-bottom:3px;'>
    [{i}] {flag} {a.get('country','?')}{src} · {a.get('ago','')}
  </div>
  <div style='font-size:12px;font-weight:700;margin-bottom:5px;line-height:1.45;'>
    <a href="{link}" target="_blank"
       style='color:#1a3a5c;text-decoration:none;border-bottom:1px solid #c8d8ee;'>
      {a['title']}
    </a>
  </div>
  <div style='font-size:11px;color:#666;line-height:1.55;'>{a.get('summary','')[:180]}</div>
</div>"""
    return f"<div style='margin:12px 0;'>{items}</div>"


def build_email_html(
    city: str,
    wd: dict,
    stocks: list,
    macros: list,
    topic_arts: dict,
    topic_sums: dict,
    thinktank_arts: list,
    thinktank_sum: str,
    govpolicy_arts: list,
    govpolicy_sum: str,
    politics_arts: list,
    politics_sum: str,
    top3: str,
    market: str,
    investment_insight: str,
    comment: str,
) -> str:
    date_s          = date_str_kst()
    weather_html    = _build_weather_html(wd, city)
    stock_html      = _build_stock_html(stocks)
    macro_html      = _build_macro_html(macros)
    thinktank_html  = _build_thinktank_html(thinktank_arts, thinktank_sum)
    govpolicy_html  = _build_govpolicy_html(govpolicy_arts, govpolicy_sum)
    politics_html   = _build_politics_html(politics_arts, politics_sum)

    top3_html    = f"<div style='font-size:12px;line-height:1.75;color:#333;'>{top3.replace(chr(10), '<br>')}</div>"
    market_html  = f"<div style='font-size:12px;line-height:1.8;color:#333;'>{market.replace(chr(10), '<br>')}</div>"
    insight_html = f"<div style='font-size:12px;line-height:1.8;color:#333;'>{investment_insight.replace(chr(10), '<br>')}</div>"
    comment_html = f"""<div style='font-size:13px;line-height:1.6;color:#2c5f8a;
                           font-weight:500;font-style:italic;
                           border-left:3px solid #40916c;padding-left:12px;'>
      "{comment}"
    </div>"""

    news_sections = ""
    for topic in TOPICS:
        arts     = topic_arts.get(topic, [])
        sum_text = topic_sums.get(topic, "")
        cnt = {c: sum(1 for a in arts if a.get("country") == c)
               for c in ["한국", "미국", "영국", "일본", "중국", "독일"]}
        cnt_str = " · ".join(
            f"{COUNTRY_EMOJI[c]} {v}건" for c, v in cnt.items() if v > 0
        )
        news_sections += f"""
<div style='margin:16px 0;border-top:1px solid #d8ead8;padding-top:14px;'>
  <div style='display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;'>
    <h3 style='font-size:13px;color:#1b4332;font-weight:800;margin:0;'>{topic}</h3>
    <span style='font-size:10px;color:#888;'>{cnt_str}</span>
  </div>
  <div style='font-size:11px;line-height:1.65;color:#444;background:#f7faf7;
              border-radius:6px;padding:10px 12px;margin-bottom:10px;
              border-left:3px solid #40916c;'>
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
      .page-break {{ page-break-before: always; }}
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
             "Helvetica Neue",Arial,sans-serif;margin:0;padding:0;color:#333;'>

<div style='max-width:660px;margin:0 auto;background:white;
            box-shadow:0 2px 12px rgba(0,0,0,.08);'>

  <!-- 헤더 -->
  <div style="background:linear-gradient(135deg,#1a472a,#2d6a4f,#40916c);
              padding:20px 22px 16px;">
    <h1 style="color:#fff;font-size:18px;margin:0 0 4px;font-weight:800;
               letter-spacing:-0.3px;">
      🌅 아침 브리핑 v26
    </h1>
    <p style="color:rgba(255,255,255,.88);font-size:11px;margin:0;">
      {date_s} &nbsp;|&nbsp; GPT-4o-mini · KIS API · 6개국 경제신문 · 싱크탱크 · 정부정책 · 세계정치
    </p>
    <div style="display:inline-block;background:rgba(255,255,255,.18);
                color:#fff;font-size:10px;font-weight:600;border-radius:14px;
                padding:3px 10px;margin-top:7px;border:1px solid rgba(255,255,255,.28);">
      📍 {city} &nbsp;|&nbsp; 🇰🇷 🇺🇸 🇬🇧 🇯🇵 🇨🇳 🇩🇪 6개국 · 🏛️ 싱크탱크 · 🏦 정책분석 · 🌏 세계정치
    </div>
  </div>

  <div style="padding:20px 22px 28px;">

    <!-- 수집 대상 안내 -->
    <div style="background:#f0f7f0;border:1px solid #c8e6c9;border-radius:8px;
                padding:10px 14px;margin-bottom:16px;font-size:10px;color:#555;line-height:1.7;">
      <strong style="color:#1b4332;">📰 경제·금융 뉴스 소스</strong><br>
      🇰🇷 한경·매경·머니투데이·이데일리·파이낸셜뉴스 &nbsp;|&nbsp;
      🇺🇸 WSJ·Bloomberg·Reuters·CNBC·FT &nbsp;|&nbsp;
      🇬🇧 FT·Economist·Reuters·Guardian·BBC &nbsp;|&nbsp;
      🇯🇵 닛케이·Nikkei Asia·産経ビズ·Japan Times·NHK &nbsp;|&nbsp;
      🇨🇳 人民日報·新华社·财新·第一财经·南方都市报 &nbsp;|&nbsp;
      🇩🇪 Handelsblatt·FAZ·Süddeutsche·Reuters DE·Spiegel<br>
      <strong style="color:#1b4332;">🌏 세계정치 뉴스 소스</strong>
      Politico (politico.com · politico.eu) · Reuters World/Politics &nbsp;|&nbsp;
      분석 프레임: 아세모글루·조셉 나이·후쿠야마 · 진보·보수 균형 시각<br>
      <strong style="color:#1b4332;">🏛️ 싱크탱크</strong>
      현대경제연구원·삼성경제연구소·LG경제연구원·한국경제연구원·한국금융연구원·미래에셋증권 리서치
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
        🌐 거시경제지표 (14개)
        <span style="font-size:9px;color:#888;font-weight:400;">
          코스피·나스닥·S&amp;P·닛케이·DAX·상하이·환율·WTI·금
        </span>
      </h2>
      <div style="border:1px solid #1a2a4a;border-radius:8px;overflow:hidden;">
        {macro_html}
      </div>
    </div>

    <!-- 관심종목 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        📈 관심종목 시세
        <span style="font-size:9px;color:#888;font-weight:400;">KIS API (국내) · yfinance (해외)</span>
      </h2>
      <div style="border:1px solid #e8edf5;border-radius:8px;overflow:hidden;">
        {stock_html}
        <div style="background:#f8fafc;padding:4px 10px;text-align:right;
                    font-size:9px;color:#cbd5e1;border-top:1px solid #e8edf5;">
          전일종가 기준
        </div>
      </div>
    </div>

    <!-- TOP3 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        🔥 오늘의 주요뉴스 TOP 3
      </h2>
      {top3_html}
    </div>

    <!-- AI 시장 분석 (v25 강화: 3대요소 + 3대 펀드매니저) -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        📊 AI 시장 분석 브리핑
        <span style="font-size:9px;color:#888;font-weight:400;">
          3대 요소(실적·거시·심리) · 버핏·린치·소로스 통합 시각
        </span>
      </h2>
      <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;
                  padding:8px 12px;margin-bottom:10px;font-size:10px;color:#92400e;">
        ⚡ 분석 프레임: 기업실적(Earnings) · 거시경제(Macro) · 투자심리(Sentiment)
        &nbsp;|&nbsp; 버핏의 해자론 · 린치의 PEG · 소로스의 재귀성 통합 적용
      </div>
      {market_html}
    </div>

    <!-- 투자 인사이트 + 관심종목 피드백 (v25 신규) -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        💡 투자 인사이트 &amp; 관심종목 피드백
        <span style="font-size:9px;color:#888;font-weight:400;">
          3대 펀드매니저(버핏·린치·소로스) 시각
        </span>
      </h2>
      <div style="background:#fef3f2;border:1px solid #fecaca;border-radius:8px;
                  padding:6px 10px;margin-bottom:10px;font-size:10px;color:#7f1d1d;">
        ⚠️ 투자 판단은 참고용이며 최종 결정은 본인 책임입니다.
      </div>
      {insight_html}
    </div>

    <!-- 오늘의 한 마디 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        💬 오늘의 한 마디
      </h2>
      {comment_html}
    </div>

    <!-- 싱크탱크 분석 (v25 신규: 방산 대체) -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        🌏 세계정치 분석
        <span style="font-size:9px;color:#888;font-weight:400;">
          Politico · Reuters · 최대 {N_POLITICS}건 · 아세모글루·나이·후쿠야마 시각
        </span>
      </h2>
      <div style="background:#fff3f3;border:1px solid #f5c6c6;border-radius:8px;
                  padding:6px 10px;margin-bottom:10px;font-size:10px;color:#7b1c1c;">
        🏛️ 분석 프레임: 포용적 제도(Acemoglu) · 소프트/스마트 파워(Nye) · 정체성 정치·사회적 자본(Fukuyama)
        &nbsp;|&nbsp; 진보·보수 균형 시각
      </div>
      {politics_html}
    </div>

    <!-- 싱크탱크 분석 (v25: 방산 대체) -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        🏛️ 싱크탱크 분석 리포트
        <span style="font-size:9px;color:#888;font-weight:400;">
          최대 {N_THINKTANK}건 · 현대경제연구원·삼성경제연구소·LG·한국경제연구원·한국금융연구원·미래에셋
        </span>
      </h2>
      {thinktank_html}
    </div>

    <!-- 정부 경제정책 발표 (v25 신규) -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        📋 정부 경제·금융·주식·부동산 정책 발표
        <span style="font-size:9px;color:#888;font-weight:400;">
          기획재정부·금융위·국토부·한국은행·금감원
        </span>
      </h2>
      {govpolicy_html}
    </div>

    <!-- 분야별 뉴스 (3개 분야: 세계정치·경제·금융) -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:5px;margin:18px 0 10px;font-weight:800;">
        📰 분야별 뉴스
        <span style="font-size:9px;color:#888;font-weight:400;">
          최근 {NEWS_CUTOFF_DAYS}일 · 분야당 최대 14건
          (🇰🇷 4 + 🇺🇸 2 + 🇬🇧 2 + 🇯🇵 2 + 🇨🇳 2 + 🇩🇪 2) · 🌏세계정치·💰경제·🏦금융
        </span>
      </h2>
      {news_sections}
    </div>

  </div>

  <!-- 푸터 -->
  <div style="background:#f0f7f0;padding:12px 22px;text-align:center;
              border-top:1px solid #d8ead8;margin-top:12px;">
    <p style="font-size:9px;color:#999;margin:0;line-height:1.6;">
      ⚡ 아침 브리핑 v26 — 6개국 5대 경제신문 · 한국 6대 싱크탱크 · 정부정책 · 세계정치 통합 분석<br>
      🌏 정치 분석: 아세모글루(포용적 제도) · 조셉 나이(소프트/스마트 파워) · 후쿠야마(정체성 정치·사회적 자본) · 진보·보수 균형<br>
      📊 투자 프레임: 기업실적(Earnings) · 거시경제(Macro) · 투자심리(Sentiment)<br>
      🏦 버핏(해자·내재가치) · 📈 린치(PEG·성장스토리) · 🌊 소로스(재귀성·시장왜곡) 통합 시각<br>
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
    payload = {"html_body": html_body, "subject": subject, "sent_at": sent_at}
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
# 8. 발송 엔진 (SMTP 직접 발송 - Manual 용도)
# ═══════════════════════════════════════════════════════════════
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def send_via_smtp(html_body: str, subject: str) -> bool:
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    # .env 파일에 반드시 SMTP_USER (본인 이메일) 및 SMTP_APP_PW (앱 비밀번호) 추가 필요
    smtp_user = _env("SMTP_USER")      
    smtp_pw = _env("SMTP_APP_PW")      
    target_email = "sypark1178@gmail.com" # 테스트 발송 타겟

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = target_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pw)
        server.sendmail(smtp_user, target_email, msg.as_string())
        server.quit()
        log.info(f"✅ sypark1178@gmail.com 으로 이메일 수동 발송 성공!")
        return True
    except Exception as e:
        log.error(f"❌ SMTP 발송 실패: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# 8. Make Webhook 발송
# ═══════════════════════════════════════════════════════════════
def send_to_make(html_body: str, subject: str) -> bool:
    sent_at = now_kst().strftime("%Y-%m-%d %H:%M KST")
    payload = {"html_body": html_body, "subject": subject, "sent_at": sent_at}
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
# 9. 메인 실행 (v25 최적화 흐름)
# ═══════════════════════════════════════════════════════════════
def main():
    log.info("=" * 65)
    log.info(f"🌅 아침 브리핑 v26 생성 시작 — {date_str_kst()}")
    log.info("뉴스 소스: 6개국(🇰🇷🇺🇸🇬🇧🇯🇵🇨🇳🇩🇪) 각 5대 경제신문사")
    log.info("세계정치: Politico · Reuters — 아세모글루·나이·후쿠야마 시각 · 진보·보수 균형")
    log.info("싱크탱크: 현대경제연구원·삼성경제연구소·LG경제연구원·한국경제연구원·한국금융연구원·미래에셋")
    log.info("정책분석: 기획재정부·금융위원회·국토교통부·한국은행·금융감독원")
    log.info(f"분야별 최대: 🇰🇷 4건 + 🇺🇸 2건 + 🇬🇧 2건 + 🇯🇵 2건 + 🇨🇳 2건 + 🇩🇪 2건 = 총 14건")
    log.info(f"분석 프레임: 3대요소(실적·거시·심리) + 버핏·린치·소로스 통합 시각")
    log.info("색상: 상승=붉은색(#e63946) / 하락=파란색(#1d6fa5)")
    log.info("=" * 65)

    # ── [1/10] 날씨 ──────────────────────────────────────────────
    log.info("🌤️ [1/10] 날씨 조회...")
    wd = fetch_weather(CITY)

    # ── [2/10] 관심종목 주가 ─────────────────────────────────────
    log.info("📈 [2/10] 관심종목 주가 조회...")
    stocks = fetch_stock_prices(DEFAULT_TICKERS)

    # ── [3/10] 거시경제지표 ──────────────────────────────────────
    log.info("🌐 [3/10] 거시경제지표 조회 (14개)...")
    macros = fetch_macro_indicators()

    # ── [4/10] 6개국 분야별 뉴스 수집 ───────────────────────────
    log.info("📰 [4/10] 6개국 5대 경제신문 뉴스 수집 (3개 분야: 세계정치·경제·금융)...")
    raw_pools: dict[str, list] = {}
    for topic in DEDUP_PRIORITY:
        kw   = TOPIC_KEYWORDS.get(topic, topic)
        pool = fetch_news_smart(topic, kw)
        raw_pools[topic] = pool
        log.info(f"  ✓ {topic}: {len(pool)}건 수집")

    # 중복 URL 제거 후 분야별 기사 확정
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
        log.info(f"  ✓ {topic}: 후보 {len(candidates)}건 → 중복제거 후 {len(selected)}건 확정")

    # ── [5/10] 세계정치 뉴스 수집 (Politico + Reuters) ──────────
    log.info("🌏 [5/10] 세계정치 뉴스 수집 (Politico · Reuters)...")
    politics_arts = fetch_politics_news()

    # ── [6/10] 싱크탱크 수집 ─────────────────────────────────────
    log.info("🏛️ [6/10] 한국 6대 싱크탱크 자료 수집...")
    thinktank_arts = fetch_thinktank_news()

    # ── [7/10] 정부 경제정책 수집 ────────────────────────────────
    log.info("📋 [7/10] 한국 정부 경제정책 발표 수집...")
    govpolicy_arts = fetch_govpolicy_news()

    # ── [8/10] GPT 분석 ──────────────────────────────────────────
    log.info("🤖 [8/10] GPT 전문가 분석 시작...")

    # 8-1. 분야별 뉴스 요약 (세계정치 포함)
    topic_sums: dict[str, str] = {}
    all_arts: list[dict]       = []
    for topic in TOPICS:
        arts = topic_arts.get(topic, [])
        for a in arts:
            a["topic"] = topic
        all_arts.extend(arts)
        topic_sums[topic] = gpt_summarize(topic, arts)
        log.info(f"  ✓ {topic}: 요약 완료")

    # 8-2. 세계정치 뉴스 GPT 분석 (정치석학 프레임)
    log.info("  ✓ 세계정치 GPT 분석 (아세모글루·나이·후쿠야마)...")
    politics_sum = gpt_summarize_politics(politics_arts)

    # 8-3. 싱크탱크 요약
    log.info("  ✓ 싱크탱크 GPT 요약...")
    thinktank_sum = gpt_summarize_thinktank(thinktank_arts)

    # 8-4. 정부정책 요약
    log.info("  ✓ 정부정책 GPT 요약...")
    govpolicy_sum = gpt_summarize_govpolicy(govpolicy_arts)

    # 8-5. TOP3 선정
    log.info("  ✓ TOP3 선정...")
    top3 = gpt_top3(all_arts)

    # 8-6. AI 시장 분석 (3대요소 + 3대 펀드매니저)
    log.info("  ✓ AI 시장 분석 브리핑 (3대요소 + 버핏·린치·소로스)...")
    market = gpt_market_analysis(all_arts, thinktank_sum, govpolicy_sum, macros)

    # 8-7. 투자 인사이트 + 관심종목 피드백
    log.info("  ✓ 투자 인사이트 + 관심종목 3대 거장 피드백...")
    investment_insight = gpt_investment_insight(
        all_arts, thinktank_sum, govpolicy_sum, market, stocks, macros
    )

    # 8-8. 오늘의 한 마디
    log.info("  ✓ 오늘의 한 마디...")
    comment = gpt_comment(wd, CITY, topic_sums)

    # ── [9/10] HTML 이메일 빌드 ──────────────────────────────────
    log.info("🖥️  [9/10] HTML 이메일 빌드...")
    html_body = build_email_html(
        city=CITY,
        wd=wd,
        stocks=stocks,
        macros=macros,
        topic_arts=topic_arts,
        topic_sums=topic_sums,
        thinktank_arts=thinktank_arts,
        thinktank_sum=thinktank_sum,
        govpolicy_arts=govpolicy_arts,
        govpolicy_sum=govpolicy_sum,
        politics_arts=politics_arts,
        politics_sum=politics_sum,
        top3=top3,
        market=market,
        investment_insight=investment_insight,
        comment=comment,
    )

    with open("briefing_output.html", "w", encoding="utf-8") as f:
        f.write(html_body)
    log.info("💾 briefing_output.html 저장 완료")

    

#    #  ── [9/9]  Make Webhook 대신 SMTP 함수 호출  ─────────────────────────────────
#    if send_via_smtp(html_body, f"{MAIL_SUBJECT} - 수동 테스트 ({now_kst().strftime('%Y/%m/%d')})"):
#        log.info("✅ V2.0 수동 발송 테스트 완료!")
#
    # ── [9/9] Make Webhook 발송 ─────────────────────────────────
    log.info("📨 [9/9] Make Webhook 발송...")
    subject = f"{MAIL_SUBJECT} — {now_kst().strftime('%Y/%m/%d')} (v26)"
    ok = send_to_make(html_body, subject)

    if ok:
        log.info("✅ 브리핑 V2.0 발송 완료!")
    else:
        log.error("❌ 브리핑 V2.0 발송 실패!")
        sys.exit(1)


if __name__ == "__main__":
    main()