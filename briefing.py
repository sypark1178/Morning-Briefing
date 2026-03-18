#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌅 아침 브리핑 v22 — 국제 신문사 RSS + 자동 번역
GitHub Actions + Make Webhook 자동 발송
v22  |  2026-03  |  KST 06:00 매일 실행

변경 사항:
- 국제 신문사 RSS 추가 (미국 3대 + 영국 3대)
- 영어 기사 자동 번역 (OpenAI)
- 검색 기간: 15일 → 어제까지 (매일 새로운 기사)
- 분야별 국가 구성: 한국 3개, 미국 1개, 영국 1개
- 스마트 키워드 매칭 (키워드 우선 → AI 분류)
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

# 관심 종목 (디폴트)
DEFAULT_TICKERS: dict[str, str] = {
    "삼성전자":       "005930.KS",
    "SK하이닉스":     "000660.KS",
    "LG에너지솔루션": "373220.KS",
    "삼성SDI":        "006400.KS",
    "에코프로비엠":   "247540.KS",
    "한화에어로스페이스": "012450.KS",
    "두산에너빌리티": "034020.KS",
    "한국항공우주":   "047810.KS",
    "현대로템":       "064350.KS",
    "LIG넥스원":      "079550.KS",
}

# 관심 분야
TOPICS = ["📈 주식", "💰 경제", "🏦 금융", "🛡️ 방산"]
TOPIC_KEYWORDS = {
    "📈 주식":  "반도체 이차전지 주식 코스피",
    "💰 경제":  "경제 트럼프관세 환율 금리 부동산정책",
    "🏦 금융":  "금융 은행 증권 SMR 에너지",
    "🛡️ 방산":  "방산 방위산업 무기수출 한화 현대로템 LIG넥스원",
}

# 추가 키워드 (분야 공통 보조)
EXTRA_KEYWORDS = ["관세","천궁","K9전차","홍해","코스피200","코스닥","반도체","금리","보유세","부동산정책","유가", "양도소득세", "환율", "방산", "부동산정책", "AI", "로봇", "전기차", "우주항공", "원전", "SMR", "해외증시"]

# ── 뉴스 검색 설정 ──────────────────────────────────────────
NEWS_CUTOFF_DAYS = 1    # 어제부터 오늘까지 (매일 새로운 기사만)
N_ARTICLES_PER_COUNTRY = {
    "한국": 3,
    "미국": 1,
    "영국": 1,
}
N_ARTICLES = sum(N_ARTICLES_PER_COUNTRY.values())  # 총 5개

# 뉴스 중복 제거 우선순위
DEDUP_PRIORITY = ["💰 경제", "🏦 금융", "📈 주식", "🛡️ 방산"]

# ── RSS 피드 소스 ──────────────────────────────────────────────
# 주요 신문사 RSS들이 구독 장벽이 있어 Google News 기반으로 변경
# 각 국가/키워드별로 Google News 검색 RSS 사용 (안정성 ↑)
NEWS_FEEDS = {
    "한국": [
        "https://news.google.com/rss/search?q=한국경제&hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/search?q=연합뉴스&hl=ko&gl=KR&ceid=KR:ko",
        "https://news.google.com/rss/search?q=중앙일보&hl=ko&gl=KR&ceid=KR:ko",
    ],
    "미국": [
        # Google News (영어) - 미국 뉴스
        "https://news.google.com/rss/search?q=USA+economy&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=US+stock+market&hl=en&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=US+federal+reserve&hl=en&gl=US&ceid=US:en",
    ],
    "영국": [
        # Google News (영어) - 영국 뉴스
        "https://news.google.com/rss/search?q=UK+economy&hl=en&gl=GB&ceid=GB:en",
        "https://news.google.com/rss/search?q=UK+stock+market&hl=en&gl=GB&ceid=GB:en",
        "https://news.google.com/rss/search?q=UK+business&hl=en&gl=GB&ceid=GB:en",
    ],
}

# ── 거시경제지표 (yfinance ticker 기준) ─────────────────────
MACRO_INDICATORS = [
    ("코스피",          "^KS11",          "pt",    2),
    ("코스닥",          "^KQ11",          "pt",    2),
    ("나스닥",          "^IXIC",          "pt",    2),
    ("S&P 500",        "^GSPC",          "pt",    2),
    ("다우존스",        "^DJI",           "pt",    2),
    ("원/달러 환율",    "KRW=X",          "원",    1),
    ("WTI 원유(26-04)", "CL=F",           "$/bbl", 2),
    ("금 선물(26-04)",  "GC=F",           "$/oz",  2),
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
        if d < 60:   return f"{d}초 전"
        if d < 3600: return f"{d // 60}분 전"
        if d < 86400: return f"{d // 3600}시간 전"
        return f"{d // 86400}일 전"
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════
# 2-B. 번역 함수 (영어 → 한글)
# ═══════════════════════════════════════════════════════════════
_translation_cache: dict[str, str] = {}

def translate_to_korean(text: str, max_retries=2) -> str:
    """
    영어 텍스트를 한글로 번역 (캐싱 포함).
    실패 시 원문 반환.
    """
    if not text or len(text) < 5:
        return text
    
    # 이미 한글로 보이면 번역 스킵 (간단한 휴리스틱)
    if any(ord(c) >= 0xAC00 for c in text):
        return text
    
    # 캐시 확인
    cache_key = text[:100]
    if cache_key in _translation_cache:
        return _translation_cache[cache_key]
    
    try:
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=300,
            messages=[
                {"role": "system", "content": "You are a translator. Translate the given English text to Korean concisely. Return only the translated text."},
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
WEATHER_SLOTS = [("🌄 아침", 7), ("🌞 오전", 10), ("🌇 오후", 14),
                 ("🌆 저녁", 17), ("🌙 밤", 21)]

WCODE_MAP = {
    0: "☀️ 맑음", 1: "🌤️ 대체로맑음", 2: "⛅ 구름조금", 3: "☁️ 흐림",
    45: "🌫️ 안개", 48: "🌫️ 짙은안개",
    51: "🌦️ 이슬비", 53: "🌦️ 이슬비", 55: "🌧️ 이슬비강",
    61: "🌧️ 비약", 63: "🌧️ 비", 65: "🌧️ 비강",
    71: "🌨️ 눈약", 73: "❄️ 눈", 75: "❄️ 눈강",
    80: "🌦️ 소나기", 81: "🌧️ 소나기", 82: "⛈️ 소나기강",
    95: "⛈️ 뇌우", 99: "⛈️ 강한뇌우",
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
        data = r.json()
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
KIS_BASE_URL = "https://openapivts.koreainvestment.com:29443"   # 모의투자
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
                "appkey": KIS_APP_KEY,
                "appsecret": KIS_APP_SECRET,
            }),
            timeout=5,
        )
        if res.status_code == 200:
            d = res.json()
            _kis_token["access_token"] = d["access_token"]
            _kis_token["expire"] = time.time() + 86400 - 300
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
        raw = raw.strip()
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

        # ── yfinance 폴백 ──
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
# 4-B. 거시경제지표 조회 (yfinance)
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
            change  = curr - prev
            pct     = change / prev * 100 if prev else 0

            fmt = f",.{decimals}f"
            results.append({
                "name":     name,
                "ticker":   ticker,
                "unit":     unit,
                "curr":     curr,
                "prev":     prev,
                "change":   change,
                "pct":      pct,
                "curr_s":   f"{curr:{fmt}}",
                "prev_s":   f"{prev:{fmt}}",
                "change_s": f"{abs(change):{fmt}}",
                "pct_s":    f"{abs(pct):.2f}",
            })
            log.info(f"  ✓ 거시지표 [{name}]: {curr:{fmt}} {unit} ({'+' if change>=0 else '-'}{abs(pct):.2f}%)")
        except Exception as e:
            log.warning(f"⚠️ 거시지표 조회 실패 [{name}/{ticker}]: {e}")
            results.append({
                "name": name, "ticker": ticker, "unit": unit,
                "curr": 0, "prev": 0, "change": 0, "pct": 0,
                "curr_s": "-", "prev_s": "-", "change_s": "-", "pct_s": "-",
                "error": str(e),
            })
        time.sleep(0.1)

    log.info(f"✅ 거시경제지표 조회 완료: {len(results)}건")
    return results


# ═══════════════════════════════════════════════════════════════
# 5. 뉴스 수집 (국가별 RSS 소스)
# ═══════════════════════════════════════════════════════════════
def fetch_news_by_country(country: str, keyword: str = "", n: int = 5, pool: int = 0) -> list[dict]:
    """
    국가별 RSS 피드에서 뉴스를 수집.
    keyword가 있으면 필터링, 없으면 전체 반환.
    
    ✅ FIXED: feedparser.parse()는 timeout을 지원하지 않음
              → requests.get()으로 먼저 받은 후 feedparser.parse()에 전달
    """
    fetch_size = pool if pool > n else n * 3
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_CUTOFF_DAYS)
    
    feeds = NEWS_FEEDS.get(country, [])
    all_arts = []
    
    # User-Agent 설정 (일부 서버는 이것이 없으면 차단)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    for feed_url in feeds:
        try:
            # Google News RSS인 경우 keyword 추가 + 국가별 locale 설정
            if "news.google.com" in feed_url and keyword:
                if country == "한국":
                    feed_url = f"https://news.google.com/rss/search?q={quote(keyword)}&hl=ko&gl=KR&ceid=KR:ko"
                elif country == "미국":
                    feed_url = f"https://news.google.com/rss/search?q={quote(keyword)}&hl=en&gl=US&ceid=US:en"
                elif country == "영국":
                    feed_url = f"https://news.google.com/rss/search?q={quote(keyword)}&hl=en&gl=GB&ceid=GB:en"
            
            # ✅ FIXED: requests.get()으로 먼저 HTTP 요청 (timeout 적용)
            response = requests.get(feed_url, headers=headers, timeout=10)
            response.raise_for_status()
            
            # feedparser.parse()는 텍스트/바이너리를 받음 (timeout 파라미터 없음)
            feed = feedparser.parse(response.content)
            
            if not feed.entries:
                log.debug(f"⚠️ RSS 피드가 비어있음 [{country}]: {feed_url[:50]}")
                continue
            
            for e in feed.entries[:fetch_size * 3]:
                pub = e.get("published", e.get("updated", ""))
                dt  = parse_dt(pub)
                if not dt.tzinfo:
                    dt = dt.replace(tzinfo=timezone.utc)
                if dt < cutoff:
                    continue
                
                title = e.get("title", "(제목없음)")
                sr = e.get("summary", e.get("description", ""))
                txt = BeautifulSoup(sr, "lxml").get_text(strip=True)[:300] if sr else ""
                
                # 영어 기사 번역
                if country != "한국":
                    title = translate_to_korean(title)
                    txt = translate_to_korean(txt) if txt else txt
                
                art = {
                    "title":   title,
                    "link":    e.get("link", ""),
                    "summary": txt,
                    "pub":     pub,
                    "ago":     time_ago(pub),
                    "_dt":     dt,
                    "country": country,
                    "source":  e.get("source", {}).get("title", feed_url.split("/")[2]) if isinstance(e.get("source"), dict) else "",
                }
                
                # 키워드 필터링 (있는 경우)
                if keyword:
                    keywords_lower = keyword.lower().split()
                    if not any(kw in (title + txt).lower() for kw in keywords_lower):
                        continue
                
                all_arts.append(art)
            
            time.sleep(0.3)  # RSS 피드 서버 부하 방지
        except requests.exceptions.RequestException as e:
            log.warning(f"⚠️ 네트워크 오류 [{country}]: {type(e).__name__} - {feed_url[:50]}")
        except Exception as e:
            log.warning(f"⚠️ RSS 피드 조회 실패 [{country}]: {e}")
    
    all_arts.sort(key=lambda x: x["_dt"], reverse=True)
    log.info(f"✅ 뉴스 수집 [{country}]: {len(all_arts[:fetch_size])}건 (후보풀)")
    return all_arts[:fetch_size]


def fetch_news_smart(topic: str, keywords: str) -> list[dict]:
    """
    스마트 뉴스 검색:
    1. 한국 뉴스 3개 (keyword 사용)
    2. 미국 뉴스 1개 (keyword 사용, 부족하면 주제 관련으로)
    3. 영국 뉴스 1개 (keyword 사용, 부족하면 주제 관련으로)
    """
    results = []
    total_needed = sum(N_ARTICLES_PER_COUNTRY.values())
    
    for country in ["한국", "미국", "영국"]:
        needed = N_ARTICLES_PER_COUNTRY[country]
        
        # 단계 1: 키워드로 검색
        arts = fetch_news_by_country(country, keyword=keywords, n=needed, pool=needed * 3)
        
        # 단계 2: 부족하면 AI로 주제 관련 뉴스 선택
        if len(arts) < needed:
            arts_all = fetch_news_by_country(country, keyword="", n=needed * 3, pool=needed * 5)
            
            # AI로 주제 관련도 평가
            if arts_all:
                extra_needed = needed - len(arts)
                ctx = "\n".join(f"[{i+1}] {a['title']}" for i, a in enumerate(arts_all[:15]))
                
                selected_indices = _gpt_select_by_topic(topic, ctx, extra_needed)
                for idx in selected_indices:
                    if 0 <= idx < len(arts_all) and arts_all[idx] not in arts:
                        arts.append(arts_all[idx])
                        if len(arts) >= needed:
                            break
        
        results.extend(arts[:needed])
    
    return results[:total_needed]


def _gpt_select_by_topic(topic: str, articles_ctx: str, count: int) -> list[int]:
    """AI가 주제와 관련된 기사 인덱스를 선택."""
    try:
        prompt = f"{topic} 분야와 관련된 상위 {count}개 기사 인덱스를 선택. 형식: [1,3,5]"
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=50,
            messages=[
                {"role": "system", "content": "You are a news classifier. Return ONLY a JSON list of indices."},
                {"role": "user", "content": f"{articles_ctx}\n\n{prompt}"},
            ],
        )
        try:
            return json.loads(r.choices[0].message.content.strip())
        except:
            return []
    except Exception as e:
        log.warning(f"⚠️ GPT 선택 실패: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# 6. GPT 분석/요약
# ═══════════════════════════════════════════════════════════════
def _gpt(system: str, user: str, temperature=0.35, max_tokens=900) -> str:
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
        err_body = str(e)
        if "insufficient_quota" in err_body:
            log.warning("⚠️ OpenAI 크레딧 소진")
            return "⚠️ [OpenAI 크레딧 소진] platform.openai.com/billing 에서 충전 후 재실행하세요."
        log.warning(f"⚠️ GPT 요청 한도 초과: {e}")
        return "⚠️ [GPT 요청 한도 초과] 잠시 후 다시 실행해 주세요."
    except Exception as e:
        log.warning(f"⚠️ GPT 호출 실패: {e}")
        return f"⚠️ [GPT 오류] {e}"


def gpt_summarize(topic: str, arts: list) -> str:
    if not arts:
        return "관련 기사를 찾을 수 없습니다."
    ctx = "\n".join(
        f"[{i+1}] {a['title']} ({a['ago']}) [{a.get('country', '?')}]\n{a['summary'][:150]}"
        for i, a in enumerate(arts[:10])
    )
    return _gpt(
        "뉴스 브리핑 전문가. 제공된 기사만 근거로 [번호] 인용해 핵심 3줄로 요약.",
        f"{topic} 분야 핵심 3줄 요약:\n\n{ctx}",
    )


def gpt_top3(all_arts: list) -> str:
    if not all_arts:
        return ""
    ctx = "\n".join(
        f"[{i+1}][{a.get('topic','?')}][{a.get('country', '?')}] {a['title']} ({a['ago']})"
        for i, a in enumerate(all_arts[:25])
    )
    return _gpt(
        "뉴스 편집장. 제공된 기사에서만 선택. 간결하고 명확하게.",
        f"오늘 가장 중요한 TOP 3 선정 — 각각 번호·제목·한줄이유:\n\n{ctx}",
    )


def gpt_market_analysis(all_arts: list) -> str:
    ctx = "\n".join(
        f"[{i+1}] {a['title']} ({a['ago']}) [{a.get('country', '?')}]"
        for i, a in enumerate(all_arts[:18])
    )
    now_str = now_kst().strftime("%Y년 %m월 %d일 %H:%M")
    return _gpt(
        ("CFA 자격증 보유 투자분석가·거시경제 전문가. "
         "제공된 뉴스만 근거로 분석. 추측은 '~가능성' 표현 사용. "
         "투자 조언은 참고용임을 명시."),
        (f"[분석기준: {now_str}]\n{ctx}\n\n"
         "형식:\n"
         "1. 📊 시장 핵심 요약 (2문장)\n"
         "2. 📈 주목 섹터/종목 동향 (2~3줄)\n"
         "3. ⚠️ 리스크 요인 (1~2가지)\n"
         "4. 💡 오늘의 투자 인사이트 (1문장, 참고용)"),
    )


def gpt_comment(wd: dict, city: str, sums: dict) -> str:
    cur = wd.get("slots", {}).get("_cur", {})
    w_str = (f"{city} {cur.get('cond', '?')} "
             f"{cur.get('temp', '?')}°C 강수확률 {cur.get('rain', '?')}%")
    ns = "\n".join(f"- {t}: {s[:120]}" for t, s in sums.items())
    return _gpt(
        ("경제·금융 지식이 해박하면서도 유머 감각이 넘치는 아침 브리핑 MC. "
         "워런 버핏의 지혜와 개그맨의 위트를 동시에 갖춤. "
         "날씨+뉴스 버무려 '아, 맞아!'와 '재밌다' 동시에 나오는 한마디 2~3문장. "
         "제공된 정보만 근거."),
        f"날씨: {w_str}\n주요뉴스:\n{ns}\n\n위트 있는 아침 한마디 써주세요.",
        temperature=0.82,
        max_tokens=200,
    )


# ═══════════════════════════════════════════════════════════════
# 7. HTML 이메일 렌더러 (생략 - 기존과 동일)
# ═══════════════════════════════════════════════════════════════
def _build_weather_html(wd: dict, city: str) -> str:
    slots = wd.get("slots", {})
    cur   = slots.get("_cur", {})
    if wd.get("error") or not cur:
        return f"<p style='color:#e74c3c;'>⚠️ 날씨 조회 실패</p>"

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
  <div style='font-size:11px;font-weight:700;color:{rain_col};
              margin-top:4px;'>☔{s['rain']}%</div>
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
        up       = s["change"] >= 0
        icon     = "📈" if up else "📉"
        color    = "#27ae60" if up else "#e74c3c"
        sign     = "+" if up else "-"
        rows += f"""
<tr style='border-bottom:1px solid #e8edf5;{"background:#f8fbff;" if i%2==0 else ""}'>
  <td style='padding:9px 10px;font-size:12px;font-weight:600;color:#1a3a5c;'>{s['name']}</td>
  <td style='padding:9px 10px;text-align:right;font-size:12px;font-weight:800;color:#333;'>{s['price']:,.0f}</td>
  <td style='padding:9px 10px;text-align:right;font-size:11px;color:{color};font-weight:700;'>{icon} {sign}{abs(s['pct']):.2f}%</td>
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
  <tbody>
    {rows}
  </tbody>
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
  <td style='padding:8px 10px;text-align:right;font-size:11px;font-weight:800;color:#1a3a5c;'>{m['curr_s']} {m['unit']}</td>
  <td style='padding:8px 10px;text-align:right;font-size:10px;color:{color};font-weight:700;'>{icon} {sign}{m['pct_s']}%</td>
</tr>"""

    return f"""
<table style='width:100%;border-collapse:collapse;font-size:11px;'>
  <thead>
    <tr style='background:#f5f8fb;border-bottom:1px solid #d4dce6;'>
      <td style='padding:7px 10px;color:#666;font-weight:600;text-align:left;'>지표명</td>
      <td style='padding:7px 10px;color:#666;font-weight:600;text-align:right;'>현재</td>
      <td style='padding:7px 10px;color:#666;font-weight:600;text-align:right;'>변화</td>
    </tr>
  </thead>
  <tbody>
    {rows}
  </tbody>
</table>"""


def _build_news_section_html(topic: str, arts: list) -> str:
    if not arts:
        return f"<p style='color:#aaa;'>뉴스 없음</p>"

    items = ""
    for i, a in enumerate(arts, 1):
        country_emoji = "🇰🇷" if a.get("country") == "한국" else "🇺🇸" if a.get("country") == "미국" else "🇬🇧"
        link = a.get("link", "#")  # 링크가 없으면 # 사용
        
        items += f"""
<div style='margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid #eee;'>
  <div style='font-size:11px;color:#888;margin-bottom:3px;'>
    [{i}] {country_emoji} {a.get('country', '?')} · {a['ago']}
  </div>
  <div style='font-size:12px;font-weight:600;margin-bottom:4px;line-height:1.4;'>
    <a href="{link}" target="_blank" style='color:#1a3a5c;text-decoration:none;'>
      {a['title']}
    </a>
  </div>
  <div style='font-size:11px;color:#666;line-height:1.5;'>
    {a['summary'][:150]}
  </div>
</div>"""

    return f"""
<div style='margin:12px 0;'>
  {items}
</div>"""


def build_email_html(city: str, wd: dict, stocks: list, macros: list,
                     topic_arts: dict, topic_sums: dict, top3: str,
                     market: str, comment: str) -> str:
    date_s = date_str_kst()
    topics_label = ", ".join(TOPICS)
    
    weather_html = _build_weather_html(wd, city)
    stock_html   = _build_stock_html(stocks)
    macro_html   = _build_macro_html(macros)
    
    top3_html = f"<div style='font-size:12px;line-height:1.7;color:#333;'>{top3.replace(chr(10), '<br>')}</div>"
    market_html = f"<div style='font-size:12px;line-height:1.7;color:#333;'>{market.replace(chr(10), '<br>')}</div>"
    comment_html = f"<div style='font-size:13px;line-height:1.6;color:#2c5f8a;font-weight:500;'>\"{comment}\"</div>"
    
    news_sections = ""
    for topic in TOPICS:
        arts = topic_arts.get(topic, [])
        sum_text = topic_sums.get(topic, "")
        news_sections += f"""
<div style='margin:16px 0;border-top:1px solid #d8ead8;padding-top:12px;'>
  <h3 style='font-size:12px;color:#1b4332;font-weight:800;margin:0 0 8px;'>{topic}</h3>
  <div style='font-size:11px;line-height:1.6;color:#555;margin-bottom:8px;'>{sum_text}</div>
  {_build_news_section_html(topic, arts)}
</div>"""

    return f"""
<!DOCTYPE html>
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
    }}
  </style>
</head>
<body style='font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
              margin: 0; padding: 0; background: #f5f5f5; color: #333;'>

<div style='max-width: 650px; margin: 0 auto; background: white; box-shadow: 0 2px 8px rgba(0,0,0,.05);'>

  <!-- 헤더 -->
  <div class="briefing-header" style="background:linear-gradient(135deg,#1a472a,#2d6a4f,#40916c);
              padding:18px 20px 14px;">
    <h1 style="color:#fff;font-size:17px;margin:0 0 3px;font-weight:800;">
      🌅 아침 브리핑
    </h1>
    <p style="color:rgba(255,255,255,.85);font-size:11px;margin:0;">
      {date_s} &nbsp;|&nbsp; Powered by GPT-4o-mini · KIS API · 국제 RSS
    </p>
    <div style="display:inline-block;background:rgba(255,255,255,.18);color:#fff;
                font-size:10px;font-weight:600;border-radius:14px;
                padding:2px 9px;margin-top:6px;border:1px solid rgba(255,255,255,.25);">
      📍 {city} &nbsp;|&nbsp; 🇰🇷 🇺🇸 🇬🇧 국제 뉴스
    </div>
  </div>

  <div style="padding:18px 20px 24px;">

    <!-- 날씨 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:4px;margin:0 0 10px;font-weight:800;">
        🌤️ 날씨 — {city}
      </h2>
      {weather_html}
    </div>

    <!-- 거시경제지표 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:4px;margin:16px 0 10px;font-weight:800;">
        🌐 거시경제지표
      </h2>
      <div style="border:1px solid #1a2a4a;border-radius:8px;overflow:hidden;">
        {macro_html}
      </div>
    </div>

    <!-- 관심주식 현재가 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:4px;margin:16px 0 10px;font-weight:800;">
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
                 padding-bottom:4px;margin:16px 0 10px;font-weight:800;">
        📊 AI 시장 분석 브리핑
      </h2>
      {market_html}
    </div>

    <!-- 주요뉴스 TOP3 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:4px;margin:16px 0 10px;font-weight:800;">
        🔥 오늘의 주요뉴스 TOP 3
      </h2>
      {top3_html}
    </div>

    <!-- 한마디 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:4px;margin:16px 0 10px;font-weight:800;">
        💬 오늘의 한 마디
      </h2>
      {comment_html}
    </div>

    <!-- 분야별 뉴스 -->
    <div class="briefing-section">
      <h2 style="font-size:13px;color:#1b4332;border-bottom:2px solid #40916c;
                 padding-bottom:4px;margin:16px 0 10px;font-weight:800;">
        📰 분야별 뉴스 <span style="font-size:9px;font-weight:400;color:#888;">
          (최근 {NEWS_CUTOFF_DAYS}일 · 한국 3개 + 미국 1개 + 영국 1개)
        </span>
      </h2>
      {news_sections}
    </div>

  </div>

  <!-- 푸터 -->
  <div style="background:#f0f7f0;padding:10px 20px;text-align:center;
              border-top:1px solid #d8ead8;margin-top:12px;">
    <p style="font-size:9px;color:#999;margin:0;line-height:1.4;">
      ⚡ 국제 RSS + Google News 기반 자동 생성 · 최근 {NEWS_CUTOFF_DAYS}일 기사<br>
      🌍 한국 뉴스 + 미국 뉴스(NYT/WSJ/WaPo) + 영국 뉴스(Times/Guardian/Telegraph)<br>
      GPT 답변은 제공된 기사에만 근거합니다. 투자 결정은 본인 판단 하에 하세요.
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
    log.info("=" * 60)
    log.info(f"🌅 아침 브리핑 v22 생성 시작 — {date_str_kst()}")
    log.info(f"국제 뉴스: 한국 3개 + 미국 1개 + 영국 1개")
    log.info("=" * 60)

    # ── 날씨 ──
    log.info("🌤️ [1/7] 날씨 조회...")
    wd = fetch_weather(CITY)

    # ── 주식 ──
    log.info("📈 [2/7] 주가 조회...")
    stocks = fetch_stock_prices(DEFAULT_TICKERS)

    # ── 거시경제지표 ──
    log.info("🌐 [3/7] 거시경제지표 조회...")
    macros = fetch_macro_indicators()

    # ── 뉴스 수집 + 중복 제거 + GPT 요약 ──────────────────────
    log.info("📰 [4/7] 뉴스 수집 (스마트 필터링 + 자동 번역)...")

    # Step 1: 분야별로 뉴스 수집 (국가별 분해)
    POOL_SIZE = N_ARTICLES * 3
    raw_pools: dict[str, list] = {}
    for topic in DEDUP_PRIORITY:
        kw   = TOPIC_KEYWORDS.get(topic, topic)
        pool = fetch_news_smart(topic, kw)
        raw_pools[topic] = pool

    # Step 2: 우선순위 순서로 기사 배정 — URL 중복 제거
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
        log.info(f"  ✓ {topic}: 후보 {len(candidates)}건 → 중복제거 후 {len(selected)}건 선정")

    # Step 3: TOPICS 순서로 재정렬, GPT 요약
    topic_sums: dict[str, str] = {}
    all_arts:   list[dict]     = []

    for topic in TOPICS:
        arts = topic_arts.get(topic, [])
        for a in arts:
            a["topic"] = topic
        all_arts.extend(arts)

        gsum = gpt_summarize(topic, arts)
        topic_sums[topic] = gsum
        log.info(f"  ✓ {topic}: GPT 요약 완료")

    # ── TOP3 ──
    log.info("🔥 [5/7] TOP3 선정...")
    top3 = gpt_top3(all_arts)

    # ── AI 시장 분석 ──
    log.info("📊 [6/7] AI 시장 분석...")
    market = gpt_market_analysis(all_arts)

    # ── 한마디 ──
    log.info("💬    한마디 생성...")
    comment = gpt_comment(wd, CITY, topic_sums)

    # ── HTML 이메일 빌드 ──
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

    # ── 결과 파일 저장 ──
    with open("briefing_output.html", "w", encoding="utf-8") as f:
        f.write(html_body)
    log.info("💾 briefing_output.html 저장 완료")

    # ── Make Webhook 발송 ──
    log.info("📨 Make Webhook 발송...")
    subject = f"{MAIL_SUBJECT} — {now_kst().strftime('%Y/%m/%d')}"
    ok = send_to_make(html_body, subject)

    if ok:
        log.info("✅ 브리핑 발송 완료!")
    else:
        log.error("❌ 브리핑 발송 실패!")
        sys.exit(1)


if __name__ == "__main__":
    main()