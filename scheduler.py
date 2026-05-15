"""
자동 알람 스케줄러
매일 장 마감 후 (15:40 KST) 자동으로 신호 체크 후 이메일 발송
"""

import yfinance as yf
import pandas as pd
import numpy as np
import smtplib, json, os, time, schedule
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import warnings
warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))

MARKETS = {
    "코스닥":  {"signal": "229200.KS", "trade": "233740.KS", "name_signal": "KODEX 코스닥150",   "name_trade": "KODEX 코스닥150레버리지", "code_signal":"229200","code_trade":"233740"},
    "코스피":  {"signal": "069500.KS", "trade": "122630.KS", "name_signal": "KODEX 200",         "name_trade": "KODEX 레버리지",          "code_signal":"069500","code_trade":"122630"},
    "2차전지": {"signal": "305720.KS", "trade": "462330.KS", "name_signal": "KODEX 2차전지산업", "name_trade": "KODEX 2차전지레버리지",   "code_signal":"305720","code_trade":"462330"},
    "반도체":  {"signal": "091160.KS", "trade": "494310.KS", "name_signal": "KODEX 반도체",      "name_trade": "KODEX 반도체레버리지",    "code_signal":"091160","code_trade":"494310"},
}

def load_settings():
    if os.path.exists("settings.json"):
        with open("settings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def load_data(ticker):
    try:
        df = yf.download(ticker, start="2018-01-01", auto_adjust=True, progress=False)
        if df.empty:
            return None
        close = df["Close"].squeeze()
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()
        r = pd.DataFrame({"price": close, "high": high, "low": low})
        r["SMA120"] = r["price"].rolling(120).mean()
        r["SMA20"]  = r["price"].rolling(20).mean()
        prev = r["price"].shift(1)
        tr = pd.concat([
            r["high"] - r["low"],
            (r["high"] - prev).abs(),
            (r["low"]  - prev).abs()
        ], axis=1).max(axis=1)
        r["ATR20"] = tr.rolling(20).mean()
        r["gap"]   = (r["price"] - r["SMA120"]) / r["SMA120"] * 100
        return r.dropna()
    except:
        return None

def calc_signal(df):
    if df is None or len(df) < 5:
        return None
    price  = float(df["price"].iloc[-1])
    sma120 = float(df["SMA120"].iloc[-1])
    sma20  = float(df["SMA20"].iloc[-1])
    gap    = float(df["gap"].iloc[-1])
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
    return {
        "price": price, "sma120": sma120, "sma20": sma20, "gap": gap,
        "trail_stop": trail_stop, "stop_dist": stop_dist,
        "buy_signal": buy_signal, "atr_sell": atr_sell,
        "sma_sell": sma_sell, "reentry": reentry,
        "above_sma120": above_sma120,
    }

def get_pre_alerts(sig):
    alerts = []
    if not sig:
        return alerts
    gap = sig["gap"]
    stop_dist = sig["stop_dist"]
    if   15 < gap <= 18: alerts.append({"level":"D-1","msg":"매수 임박! gap " + str(round(gap,1)) + "%"})
    elif 18 < gap <= 22: alerts.append({"level":"D-2","msg":"매수 접근 gap " + str(round(gap,1)) + "%"})
    elif 22 < gap <= 26: alerts.append({"level":"D-3","msg":"매수 모니터링 gap " + str(round(gap,1)) + "%"})
    if stop_dist is not None:
        if   0  < stop_dist <= 2:  alerts.append({"level":"D-1","msg":"ATR스탑 거의 도달! " + str(round(stop_dist,1)) + "% 남음"})
        elif 2  < stop_dist <= 5:  alerts.append({"level":"D-2","msg":"ATR스탑 " + str(round(stop_dist,1)) + "% 남음"})
        elif 5  < stop_dist <= 10: alerts.append({"level":"D-3","msg":"ATR스탑 " + str(round(stop_dist,1)) + "% 남음"})
    return alerts

def send_email(settings, subject, body):
    try:
        smtp_email = settings.get("smtp_email","")
        smtp_pass  = settings.get("smtp_pass","")
        to_email   = settings.get("email","")
        if not all([smtp_email, smtp_pass, to_email]):
            return False
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"]    = smtp_email
        msg["To"]      = to_email
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(smtp_email, smtp_pass)
            s.send_message(msg)
        return True
    except:
        return False

def check_and_alert():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    print("[" + now + "] 신호 체크 시작...")

    settings = load_settings()
    lines = ["[ETF 알람] 일일 신호 요약", "시각: " + now, ""]

    any_signal = False

    for mkt, info in MARKETS.items():
        df  = load_data(info["signal"])
        sig = calc_signal(df)
        pre = get_pre_alerts(sig) if sig else []

        if sig is None:
            continue

        signal_type = None
        if sig["buy_signal"]:   signal_type = "🔴 매수 신호"
        elif sig["reentry"]:    signal_type = "🔴 재진입 신호"
        elif sig["atr_sell"]:   signal_type = "🔵 ATR 매도 신호"
        elif sig["sma_sell"]:   signal_type = "🔵 SMA120 매도 신호"

        lines.append("■ " + mkt + " (" + info["name_signal"] + ")")
        lines.append("  현재가: ₩{:,.0f} | SMA120: ₩{:,.0f} | gap: {:+.1f}%".format(
            sig["price"], sig["sma120"], sig["gap"]))

        if signal_type:
            lines.append("  👉 " + signal_type)
            lines.append("  매매 ETF: " + info["name_trade"] + " (" + info["code_trade"] + ")")
            any_signal = True

        if sig["trail_stop"] and sig["stop_dist"]:
            lines.append("  ATR스탑: ₩{:,.0f} ({:.1f}%남음)".format(
                sig["trail_stop"], sig["stop_dist"]))

        for a in pre:
            lines.append("  [" + a["level"] + "] " + a["msg"])
            any_signal = True

        lines.append("")

    lines += ["─"*40, "본 알람은 참고용입니다. 투자 판단은 본인이 하세요."]
    body = "\n".join(lines)

    if any_signal:
        subject = "[ETF알람] 🚨 신호 발생! " + now
    else:
        subject = "[ETF알람] ✅ 이상 없음 " + now

    ok = send_email(settings, subject, body)
    print("이메일 발송: " + ("성공" if ok else "실패 (설정 확인 필요)"))

# 스케줄 설정 (KST 15:40 = UTC 06:40)
schedule.every().day.at("06:40").do(check_and_alert)  # 장 마감 후
schedule.every().day.at("08:50").do(check_and_alert)  # 오전 장 시작 전 (9시 전)

print("✅ 자동 알람 스케줄러 시작!")
print("   매일 09:00 KST (장 시작 전) 체크")
print("   매일 15:40 KST (장 마감 후) 체크")

# 시작하자마자 한번 실행
check_and_alert()

while True:
    schedule.run_pending()
    time.sleep(60)
