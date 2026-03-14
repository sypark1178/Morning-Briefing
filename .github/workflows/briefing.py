#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
🌅 아침 브리핑 — GitHub Actions + Make Webhook 자동 발송
v18  |  2026-03  |  KST 06:00 매일 실행
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
    # briefing.py 와 같은 폴더의 .env 를 명시적으로 지정
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

# 보유 종목 (디폴트)
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
EXTRA_KEYWORDS = ["트럼프 관세", "반도체", "환율", "방산", "부동산정책"]

NEWS_CUTOFF_DAYS = 30   # 30일 이내
N_ARTICLES       = 10   # 분야별 최대 10건

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
KIS_BASE_URL = "https://openapi.koreainvestment.com:22443"   # 실전투자
KIS_AVAILABLE = None   # None=미확인, True=사용가능, False=사용불가


def _kis_get_token() -> bool:
    global KIS_AVAILABLE
    # 이미 사용불가로 확인된 경우 즉시 False 반환 (반복 타임아웃 방지)
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
            timeout=5,   # 5초로 단축 (기존 15초 → 타임아웃 150초 낭비 방지)
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
        KIS_AVAILABLE = False   # 1회 실패 시 이후 모든 종목은 yfinance 사용
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
                data["name"] = name   # 한글명 우선
                results.append(data)
                time.sleep(0.2)
                continue
            # KIS 실패 → yfinance 폴백
            ticker_str = code + ".KS"
        else:
            ticker_str = raw

        # ── yfinance 폴백 (해외 or KIS 실패) ──
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
# 5. Google News RSS 수집
# ═══════════════════════════════════════════════════════════════
def fetch_news(keyword: str, n: int = N_ARTICLES) -> list[dict]:
    url = (f"https://news.google.com/rss/search"
           f"?q={quote(keyword)}&hl=ko&gl=KR&ceid=KR:ko")
    cutoff = datetime.now(timezone.utc) - timedelta(days=NEWS_CUTOFF_DAYS)
    try:
        feed = feedparser.parse(url)
        arts = []
        for e in feed.entries[:n * 5]:
            pub = e.get("published", e.get("updated", ""))
            dt  = parse_dt(pub)
            if not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt < cutoff:
                continue
            sr  = e.get("summary", e.get("description", ""))
            txt = BeautifulSoup(sr, "lxml").get_text(strip=True)[:300] if sr else ""
            arts.append({
                "title":   e.get("title", "(제목없음)"),
                "link":    e.get("link", ""),
                "summary": txt,
                "pub":     pub,
                "ago":     time_ago(pub),
                "_dt":     dt,
            })
        arts.sort(key=lambda x: x["_dt"], reverse=True)
        log.info(f"✅ 뉴스 수집 [{keyword}]: {len(arts[:n])}건")
        return arts[:n]
    except Exception as e:
        log.warning(f"⚠️ 뉴스 수집 실패 [{keyword}]: {e}")
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
            log.warning("⚠️ OpenAI 크레딧 소진 — platform.openai.com/billing 에서 충전 필요")
            return "⚠️ [OpenAI 크레딧 소진] platform.openai.com/billing 에서 충전 후 재실행하세요."
        log.warning(f"⚠️ GPT 요청 한도 초과 (잠시 후 재시도): {e}")
        return "⚠️ [GPT 요청 한도 초과] 잠시 후 다시 실행해 주세요."
    except Exception as e:
        log.warning(f"⚠️ GPT 호출 실패: {e}")
        return f"⚠️ [GPT 오류] {e}"


def gpt_summarize(topic: str, arts: list) -> str:
    if not arts:
        return "관련 기사를 찾을 수 없습니다."
    ctx = "\n".join(
        f"[{i+1}] {a['title']} ({a['ago']})\n{a['summary'][:150]}"
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
        f"[{i+1}][{a.get('topic','?')}] {a['title']} ({a['ago']})"
        for i, a in enumerate(all_arts[:25])
    )
    return _gpt(
        "뉴스 편집장. 제공된 기사에서만 선택. 간결하고 명확하게.",
        f"오늘 가장 중요한 TOP 3 선정 — 각각 번호·제목·한줄이유:\n\n{ctx}",
    )


def gpt_market_analysis(all_arts: list) -> str:
    ctx = "\n".join(
        f"[{i+1}] {a['title']} ({a['ago']})"
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
         "경제 비유·격언 자연스럽게 녹이되 딱딱함 절대 금지. 제공된 정보만 근거."),
        f"날씨: {w_str}\n주요뉴스:\n{ns}\n\n위트 있는 아침 한마디 써주세요.",
        temperature=0.82,
        max_tokens=200,
    )


# ═══════════════════════════════════════════════════════════════
# 7. HTML 이메일 렌더러
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
        arrow    = "▲" if up else "▼"
        sym      = {"KRW": "₩", "USD": "$", "EUR": "€"}.get(s["currency"], "")
        price_s  = f"{sym}{s['price']:,.0f}" if s["price"] else "-"
        chg_s    = f"{arrow} {abs(s['change']):,.0f}"
        pct_s    = f"{abs(s['pct']):.2f}%"
        row_bg   = "#fff5f5" if up else "#f3f8ff"
        clr      = "#c0392b" if up else "#1a5fa8"
        pct_bg   = "#fde8e8" if up else "#ddeeff"

        rows += f"""
<tr style='background:{row_bg};border-bottom:1px solid #f0f0f0;'>
  <td style='padding:9px 8px;font-size:12px;color:#999;text-align:center;'>{i+1}</td>
  <td style='padding:9px 10px;'>
    <div style='font-size:13px;font-weight:800;color:#1a1a2e;'>{s['name']}</div>
    <div style='font-size:10px;color:#999;'>{s['ticker']}</div>
  </td>
  <td style='padding:9px 8px;text-align:right;font-size:14px;font-weight:900;
             color:{clr};font-variant-numeric:tabular-nums;white-space:nowrap;'>{price_s}</td>
  <td style='padding:9px 6px;text-align:right;font-size:12px;color:{clr};
             white-space:nowrap;'>{chg_s}</td>
  <td style='padding:9px 8px;text-align:center;'>
    <span style='background:{pct_bg};color:{clr};border-radius:10px;
                 padding:2px 8px;font-size:11px;font-weight:800;'>{arrow} {pct_s}</span>
  </td>
  <td style='padding:9px 8px;text-align:right;font-size:10px;color:#aaa;
             white-space:nowrap;'>전일 {sym}{s['prev']:,.0f}</td>
</tr>"""

    return f"""
<table style='width:100%;border-collapse:collapse;font-family:Malgun Gothic,sans-serif;'>
  <thead>
    <tr style='background:#f8fafc;border-bottom:2px solid #e2e8f0;'>
      <th style='padding:7px 6px;font-size:11px;color:#94a3b8;text-align:center;'>#</th>
      <th style='padding:7px 10px;font-size:11px;color:#94a3b8;text-align:left;'>종목명</th>
      <th style='padding:7px 8px;font-size:11px;color:#94a3b8;text-align:right;'>현재가</th>
      <th style='padding:7px 6px;font-size:11px;color:#94a3b8;text-align:right;'>등락</th>
      <th style='padding:7px 8px;font-size:11px;color:#94a3b8;text-align:center;'>등락률</th>
      <th style='padding:7px 8px;font-size:11px;color:#94a3b8;text-align:right;'>전일종가</th>
    </tr>
  </thead>
  <tbody>{rows}</tbody>
</table>"""


def _section(title: str, color: str, content: str) -> str:
    return f"""
<div style='margin-bottom:24px;'>
  <div style='background:{color};color:#fff;padding:8px 16px;
              border-radius:8px 8px 0 0;font-size:13px;font-weight:800;
              letter-spacing:0.5px;'>{title}</div>
  <div style='background:#fff;border:1px solid #e8e8e8;border-top:none;
              border-radius:0 0 8px 8px;padding:16px 18px;
              font-size:13px;line-height:1.8;color:#333;'>
    {content}
  </div>
</div>"""


def _news_list_html(arts: list, color: str) -> str:
    items = ""
    for a in arts:
        title_parts = a["title"].rsplit(" - ", 1)
        title_main  = title_parts[0] if len(title_parts) > 1 else a["title"]
        source      = title_parts[1] if len(title_parts) > 1 else ""
        items += f"""
<div style='border-bottom:1px solid #f5f5f5;padding:10px 0;'>
  <div style='display:flex;justify-content:space-between;align-items:flex-start;'>
    <a href='{a["link"]}' style='color:#1a1a1a;text-decoration:none;
       font-weight:600;font-size:13px;line-height:1.5;flex:1;'>
      {title_main}
    </a>
    <span style='font-size:10px;color:{color};white-space:nowrap;
                 margin-left:8px;background:#fff8ee;border-radius:8px;
                 padding:2px 6px;font-weight:700;border:1px solid #fde8c0;'>
      {a['ago']}
    </span>
  </div>
  {'<p style="font-size:12px;color:#666;margin:4px 0 0;line-height:1.6;">' + a["summary"][:160] + ("…" if len(a["summary"]) > 160 else "") + "</p>" if a.get("summary") else ""}
  {f'<span style="font-size:10px;color:#aaa;">{source}</span>' if source else ""}
</div>"""
    return items


def build_email_html(
    city: str,
    wd: dict,
    stocks: list,
    topic_arts: dict,   # {topic: [arts]}
    topic_sums: dict,   # {topic: gpt_summary}
    top3: str,
    market: str,
    comment: str,
) -> str:
    date_s = date_str_kst()
    topics_label = ", ".join(topic_arts.keys())

    # ── 날씨 ──────────────────────────────────────────────
    weather_html = _build_weather_html(wd, city)

    # ── 주식 ──────────────────────────────────────────────
    stock_html = _build_stock_html(stocks)

    # ── AI 시장 분석 ──────────────────────────────────────
    market_lines = market.replace("\n", "<br>")
    market_html  = f"""
<div style='background:linear-gradient(135deg,#e3f2fd,#e8eaf6);
            border-radius:10px;padding:16px 20px;border:1px solid #90caf9;
            font-size:13px;line-height:1.8;color:#222;'>
  {re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', market_lines)}
  <div style='margin-top:12px;font-size:11px;color:#9e9e9e;border-top:1px solid #c5cae9;
              padding-top:8px;'>
    ⚠️ AI가 뉴스 기사를 근거로 생성한 참고 정보입니다. 투자 결정은 본인 판단 하에 하세요.
  </div>
</div>"""

    # ── TOP3 ──────────────────────────────────────────────
    top3_lines = ""
    for line in top3.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        line = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', line)
        m = re.match(r'^([1-3])\.\s*(.*)', line)
        if m:
            top3_lines += f"""
<div style='display:flex;align-items:flex-start;margin-bottom:12px;'>
  <span style='display:inline-flex;align-items:center;justify-content:center;
               width:22px;height:22px;min-width:22px;background:#e67e22;color:#fff;
               border-radius:50%;font-size:11px;font-weight:900;margin-right:10px;
               margin-top:2px;'>{m.group(1)}</span>
  <span style='font-size:13px;font-weight:700;color:#3d2800;line-height:1.6;'>
    {m.group(2)}
  </span>
</div>"""
        else:
            top3_lines += f"""
<div style='font-size:12px;color:#5a4000;line-height:1.75;
            padding-left:32px;margin-bottom:6px;'>{line}</div>"""

    top3_html = f"""
<div style='background:linear-gradient(135deg,#fff8e8,#fef3d0);
            border-radius:10px;padding:16px 20px;border:1px solid #f5d98a;'>
  {top3_lines}
</div>"""

    # ── 한마디 ────────────────────────────────────────────
    comment_html = f"""
<div style='background:linear-gradient(135deg,#f0fdf4,#dcfce7);
            border-radius:10px;padding:16px 20px;border:1px solid #86efac;'>
  <p style='font-size:14px;color:#14532d;line-height:1.9;margin:0;font-style:italic;
             border-left:4px solid #4ade80;padding-left:16px;'>
    {comment}
  </p>
</div>"""

    # ── 분야별 뉴스 ───────────────────────────────────────
    TOPIC_COLORS = {
        "📈 주식": "#e74c3c", "💰 경제": "#e67e22",
        "🏦 금융": "#1565c0", "🛡️ 방산": "#2d6a4f",
    }
    news_sections = ""
    for topic in TOPICS:
        arts   = topic_arts.get(topic, [])
        gsum   = topic_sums.get(topic, "")
        color  = TOPIC_COLORS.get(topic, "#2d6a4f")
        label  = topic.split(" ", 1)[1] if " " in topic else topic

        gsum_html = f"""
<div style='background:#f8f9fa;border-left:4px solid {color};
            border-radius:0 8px 8px 0;padding:12px 14px;
            margin-bottom:12px;font-size:13px;line-height:1.8;color:#333;'>
  <span style='font-size:10px;font-weight:700;color:{color};
               text-transform:uppercase;letter-spacing:0.5px;
               display:block;margin-bottom:4px;'>💬 GPT 요약</span>
  {gsum.replace(chr(10), "<br>")}
</div>"""

        news_items = _news_list_html(arts, color)

        news_sections += f"""
<div style='margin-bottom:28px;'>
  <div style='display:flex;align-items:center;gap:8px;margin-bottom:10px;'>
    <span style='background:{color};color:#fff;border-radius:16px;padding:4px 14px;
                 font-size:12px;font-weight:700;'>{label}</span>
    <span style='font-size:11px;color:#888;'>기사 {len(arts)}건 (최근 {NEWS_CUTOFF_DAYS}일)</span>
  </div>
  {gsum_html}
  {news_items}
</div>"""

    # ── 최종 이메일 조합 ──────────────────────────────────
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>🌅 아침 브리핑</title>
</head>
<body style="margin:0;padding:0;background:#f0f4f0;
             font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;">
<div style="max-width:680px;margin:20px auto;background:#fff;
            border-radius:16px;overflow:hidden;
            box-shadow:0 4px 24px rgba(0,0,0,.12);">

  <!-- 헤더 -->
  <div style="background:linear-gradient(135deg,#1a472a,#2d6a4f,#40916c);
              padding:24px 28px 18px;">
    <h1 style="color:#fff;font-size:20px;margin:0 0 4px;font-weight:800;">
      🌅 아침 브리핑
    </h1>
    <p style="color:rgba(255,255,255,.8);font-size:13px;margin:0;">
      {date_s} &nbsp;|&nbsp; Powered by GPT-4o-mini · KIS API
    </p>
    <div style="display:inline-block;background:rgba(255,255,255,.18);color:#fff;
                font-size:12px;font-weight:600;border-radius:16px;
                padding:3px 12px;margin-top:8px;border:1px solid rgba(255,255,255,.25);">
      📍 {city} &nbsp;|&nbsp; {topics_label}
    </div>
  </div>

  <div style="padding:24px 28px 32px;">

    <!-- 날씨 -->
    <h2 style="font-size:15px;color:#1b4332;border-bottom:3px solid #40916c;
               padding-bottom:6px;margin:0 0 14px;font-weight:800;">
      🌤️ 날씨 — {city}
    </h2>
    {weather_html}

    <!-- 보유주식 현재가 -->
    <h2 style="font-size:15px;color:#1b4332;border-bottom:3px solid #40916c;
               padding-bottom:6px;margin:24px 0 14px;font-weight:800;">
      📈 보유종목 시세
    </h2>
    <div style="border:1px solid #e8edf5;border-radius:10px;overflow:hidden;">
      {stock_html}
      <div style="background:#f8fafc;padding:5px 12px;text-align:right;
                  font-size:10px;color:#cbd5e1;border-top:1px solid #e8edf5;">
        한국투자증권 KIS API (국내) · yfinance (해외) · 전일종가 기준
      </div>
    </div>

    <!-- AI 시장 분석 -->
    <h2 style="font-size:15px;color:#1b4332;border-bottom:3px solid #40916c;
               padding-bottom:6px;margin:24px 0 14px;font-weight:800;">
      📊 AI 시장 분석 브리핑
    </h2>
    {market_html}

    <!-- 주요뉴스 TOP3 -->
    <h2 style="font-size:15px;color:#1b4332;border-bottom:3px solid #40916c;
               padding-bottom:6px;margin:24px 0 14px;font-weight:800;">
      🔥 오늘의 주요뉴스 TOP 3
    </h2>
    {top3_html}

    <!-- 한마디 -->
    <h2 style="font-size:15px;color:#1b4332;border-bottom:3px solid #40916c;
               padding-bottom:6px;margin:24px 0 14px;font-weight:800;">
      💬 오늘의 한 마디
    </h2>
    {comment_html}

    <!-- 분야별 뉴스 -->
    <h2 style="font-size:15px;color:#1b4332;border-bottom:3px solid #40916c;
               padding-bottom:6px;margin:24px 0 14px;font-weight:800;">
      📰 분야별 뉴스 <span style="font-size:11px;font-weight:400;color:#888;">
        (최근 {NEWS_CUTOFF_DAYS}일 이내 · 분야별 최대 {N_ARTICLES}건)
      </span>
    </h2>
    {news_sections}

  </div>

  <!-- 푸터 -->
  <div style="background:#f0f7f0;padding:14px 28px;text-align:center;
              border-top:1px solid #d8ead8;">
    <p style="font-size:11px;color:#888;margin:0;">
      ⚡ Google News RSS 기반 자동 생성 · 최근 {NEWS_CUTOFF_DAYS}일 기사<br>
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
    log.info(f"🌅 아침 브리핑 생성 시작 — {date_str_kst()}")
    log.info("=" * 60)

    # ── 날씨 ──
    log.info("🌤️ [1/6] 날씨 조회...")
    wd = fetch_weather(CITY)

    # ── 주식 ──
    log.info("📈 [2/6] 주가 조회...")
    stocks = fetch_stock_prices(DEFAULT_TICKERS)

    # ── 뉴스 수집 + GPT 요약 ──
    log.info("📰 [3/6] 뉴스 수집 및 GPT 요약...")
    topic_arts: dict[str, list] = {}
    topic_sums: dict[str, str]  = {}
    all_arts: list[dict]        = []

    for topic in TOPICS:
        kw   = TOPIC_KEYWORDS.get(topic, topic)
        arts = fetch_news(kw, N_ARTICLES)
        for a in arts:
            a["topic"] = topic
        topic_arts[topic] = arts
        all_arts.extend(arts)

        gsum = gpt_summarize(topic, arts)
        topic_sums[topic] = gsum
        log.info(f"  ✓ {topic}: {len(arts)}건 수집·요약 완료")

    # ── TOP3 ──
    log.info("🔥 [4/6] TOP3 선정...")
    top3 = gpt_top3(all_arts)

    # ── AI 시장 분석 ──
    log.info("📊 [5/6] AI 시장 분석...")
    market = gpt_market_analysis(all_arts)

    # ── 한마디 ──
    log.info("💬    한마디 생성...")
    comment = gpt_comment(wd, CITY, topic_sums)

    # ── HTML 이메일 빌드 ──
    log.info("🖥️  [6/6] HTML 이메일 빌드...")
    html_body = build_email_html(
        city=CITY,
        wd=wd,
        stocks=stocks,
        topic_arts=topic_arts,
        topic_sums=topic_sums,
        top3=top3,
        market=market,
        comment=comment,
    )

    # ── 결과 파일 저장 (GitHub Actions 아티팩트용) ──
    with open("briefing_output.html", "w", encoding="utf-8") as f:
        f.write(html_body)
    log.info("💾 briefing_output.html 저장 완료")

    # ── Make Webhook으로 발송 ──
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