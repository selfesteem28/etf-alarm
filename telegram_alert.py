"""
텔레그램 ETF 알람 봇 v2
GitHub Actions에서 1분마다 실행
같은 신호는 최대 3번만 발송
신호 바뀌면 다시 카운트 시작
"""

import os
import json
import requests
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import warnings
warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))

TELEGRAM_TOKEN   = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
STATE_FILE = "signal_state.json"
MAX_COUNT  = 3  # 같은 신호 최대 발송 횟수

MARKETS = {
    "코스닥":  {"signal_code": "229200", "trade_code": "233740", "name_signal": "KODEX 코스닥150",   "name_trade": "KODEX 코스닥150레버리지"},
    "코스피":  {"signal_code": "069500", "trade_code": "122630", "name_signal": "KODEX 200",         "name_trade": "KODEX 레버리지"},
    "2차전지": {"signal_code": "305720", "trade_code": "462330", "name_signal": "KODEX 2차전지산업", "name_trade": "KODEX 2차전지레버리지"},
    "반도체":  {"signal_code": "091160", "trade_code": "494310", "name_signal": "KODEX 반도체",      "name_trade": "KODEX 반도체레버리지"},
}

# ── 신호 상태 저장/불러오기 ──
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def should_send(state, mkt, signal_type):
    """같은 신호 3번까지만 발송. 신호 바뀌면 카운트 리셋"""
    prev_signal = state.get(mkt + "_signal", "")
    count       = state.get(mkt + "_count", 0)

    if prev_signal != signal_type:
        # 신호 바뀜 → 리셋 후 발송
        state[mkt + "_signal"] = signal_type
        state[mkt + "_count"]  = 1
        return True
    elif count < MAX_COUNT:
        # 같은 신호, 3번 미만 → 발송
        state[mkt + "_count"] = count + 1
        return True
    else:
        # 같은 신호, 3번 초과 → 스킵
        return False

# ── 텔레그램 발송 ──
def send_telegram(msg):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("텔레그램 설정 없음")
        return False
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        res = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"텔레그램 발송 오류: {e}")
        return False

# ── 네이버 실시간 현재가 ──
def get_naver_price(code):
    try:
        url = f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            item = res.json()["result"]["areas"][0]["datas"][0]
            return float(item["nv"])
    except:
        pass
    return None

# ── yfinance 역사 데이터 ──
def load_history(code):
    try:
        df = yf.download(code + ".KS", start="2018-01-01", auto_adjust=True, progress=False)
        if df.empty:
            return None
        close = df["Close"].squeeze()
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()
        r = pd.DataFrame({"price": close, "high": high, "low": low})
        r["SMA120"] = r["price"].rolling(120).mean()
        r["SMA20"]  = r["price"].rolling(20).mean()
        prev = r["price"].shift(1)
        tr = pd.concat([r["high"]-r["low"],(r["high"]-prev).abs(),(r["low"]-prev).abs()], axis=1).max(axis=1)
        r["ATR20"] = tr.rolling(20).mean()
        return r.dropna()
    except:
        return None

# ── 신호 계산 ──
def calc_signal(df, rt_price=None):
    if df is None or len(df) < 5:
        return None
    price  = rt_price if rt_price else float(df["price"].iloc[-1])
    sma120 = float(df["SMA120"].iloc[-1])
    sma20  = float(df["SMA20"].iloc[-1])
    atr20  = float(df["ATR20"].iloc[-1])
    gap    = (price - sma120) / sma120 * 100
    recent = df.tail(120).copy()
    peak, trail_stop = None, None
    for _, row in recent.iterrows():
        p = float(row["price"])
        if peak is None or p > peak:
            peak = p
        if gap > 20:
            ts = peak - float(row["ATR20"]) * 2.0
            trail_stop = ts if trail_stop is None else max(trail_stop, ts)
    above_sma120 = price > sma120
    buy_signal   = above_sma120 and (0 < gap <= 15)
    atr_sell     = bool(trail_stop and gap > 20 and price < trail_stop)
    sma_sell     = not above_sma120
    prev_price   = float(df["price"].iloc[-2])
    prev_sma20   = float(df["SMA20"].iloc[-2])
    reentry      = (price > sma20) and (prev_price <= prev_sma20) and above_sma120
    stop_dist    = (price - trail_stop) / price * 100 if trail_stop else None
    sma120_dist  = (price - sma120) / price * 100
    return {
        "price": price, "sma120": sma120, "sma20": sma20, "atr20": atr20, "gap": gap,
        "trail_stop": trail_stop, "stop_dist": stop_dist, "sma120_dist": sma120_dist,
        "buy_signal": buy_signal, "atr_sell": atr_sell,
        "sma_sell": sma_sell, "reentry": reentry, "above_sma120": above_sma120,
    }

def get_pre_alerts(sig):
    alerts = []
    if not sig:
        return alerts
    gap = sig["gap"]
    stop_dist = sig["stop_dist"]
    sma_dist  = sig["sma120_dist"]
    if   15 < gap <= 18: alerts.append({"level":"D-1","kind":"buy","msg":f"매수 임박! gap {gap:.1f}%"})
    elif 18 < gap <= 22: alerts.append({"level":"D-2","kind":"buy","msg":f"매수 접근 gap {gap:.1f}%"})
    elif 22 < gap <= 26: alerts.append({"level":"D-3","kind":"buy","msg":f"매수 모니터링 gap {gap:.1f}%"})
    if stop_dist is not None:
        if   0  < stop_dist <= 2:  alerts.append({"level":"D-1","kind":"sell","msg":f"ATR스탑 거의 도달! {stop_dist:.1f}% 남음"})
        elif 2  < stop_dist <= 5:  alerts.append({"level":"D-2","kind":"sell","msg":f"ATR스탑 {stop_dist:.1f}% 남음"})
        elif 5  < stop_dist <= 10: alerts.append({"level":"D-3","kind":"sell","msg":f"ATR스탑 {stop_dist:.1f}% 남음"})
    if sig["above_sma120"]:
        if   0  < sma_dist <= 2:  alerts.append({"level":"D-1","kind":"sell","msg":f"SMA120 이탈 직전! {sma_dist:.1f}% 남음"})
        elif 2  < sma_dist <= 5:  alerts.append({"level":"D-2","kind":"sell","msg":f"SMA120까지 {sma_dist:.1f}%"})
    return alerts

# ── 장중 여부 확인 ──
def is_market_open():
    now = datetime.now(KST)
    if now.weekday() >= 5:
        return False
    market_open  = now.replace(hour=9,  minute=0,  second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close

# ── 메인 실행 ──
def main():
    now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    print(f"실행 시각: {now_str}")

    if not is_market_open():
        print("장외 시간 - 알람 없음")
        return

    state = load_state()
    messages = []

    for mkt, info in MARKETS.items():
        code = info["signal_code"]
        df   = load_history(code)
        rt   = get_naver_price(code)
        sig  = calc_signal(df, rt)

        if not sig:
            continue

        pre_alerts = get_pre_alerts(sig)

        # 주요 신호 판단
        if sig["buy_signal"]:
            signal_type = "매수"
            if should_send(state, mkt, signal_type):
                messages.append(
                    f"🔴 <b>{mkt} 매수 신호!</b>\n"
                    f"현재가: ₩{sig['price']:,.0f}\n"
                    f"SMA120: ₩{sig['sma120']:,.0f}\n"
                    f"gap: {sig['gap']:+.1f}%\n"
                    f"매매ETF: {info['name_trade']} ({info['trade_code']})"
                )
        elif sig["reentry"]:
            signal_type = "재진입"
            if should_send(state, mkt, signal_type):
                messages.append(
                    f"🔴 <b>{mkt} 재진입 신호!</b>\n"
                    f"현재가: ₩{sig['price']:,.0f}\n"
                    f"gap: {sig['gap']:+.1f}%\n"
                    f"매매ETF: {info['name_trade']} ({info['trade_code']})"
                )
        elif sig["atr_sell"]:
            signal_type = "ATR매도"
            if should_send(state, mkt, signal_type):
                messages.append(
                    f"🔵 <b>{mkt} ATR 매도 신호!</b>\n"
                    f"현재가: ₩{sig['price']:,.0f}\n"
                    f"ATR스탑: ₩{sig['trail_stop']:,.0f}\n"
                    f"gap: {sig['gap']:+.1f}%\n"
                    f"매매ETF: {info['name_trade']} ({info['trade_code']})"
                )
        elif sig["sma_sell"]:
            signal_type = "SMA매도"
            if should_send(state, mkt, signal_type):
                messages.append(
                    f"🔵 <b>{mkt} SMA120 매도 신호!</b>\n"
                    f"현재가: ₩{sig['price']:,.0f}\n"
                    f"SMA120: ₩{sig['sma120']:,.0f}\n"
                    f"gap: {sig['gap']:+.1f}%"
                )
        else:
            signal_type = "대기"
            state[mkt + "_signal"] = signal_type
            state[mkt + "_count"]  = 0

        # 사전 경보
        for a in pre_alerts:
            alert_type = a["level"] + "_" + a["kind"]
            if should_send(state, mkt, alert_type):
                icon = "🚨" if a["level"] == "D-1" else ("⚠️" if a["level"] == "D-2" else "📌")
                messages.append(
                    f"{icon} <b>{mkt} [{a['level']}] 경보</b>\n"
                    f"{a['msg']}\n"
                    f"현재가: ₩{sig['price']:,.0f} | gap: {sig['gap']:+.1f}%"
                )

    save_state(state)

    if messages:
        header = f"📊 <b>ETF 알람</b> | {now_str}\n{'─'*30}\n\n"
        full_msg = header + "\n\n".join(messages)
        ok = send_telegram(full_msg)
        print(f"텔레그램 발송: {'성공' if ok else '실패'}")
        print(f"발송 메시지 수: {len(messages)}")
    else:
        print("신호 없음 또는 이미 3번 발송 - 스킵")

if __name__ == "__main__":
    main()
