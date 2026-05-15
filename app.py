"""
국내 레버리지 ETF 알람 시스템 v1.0
대상: 코스닥 / 코스피 / 2차전지 / 반도체
전략: SMA120 + ATR(20)×2.0 트레일링스탑 + SMA20 재진입
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import json, os, smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
import warnings
warnings.filterwarnings("ignore")

# 한국 시간
KST = timezone(timedelta(hours=9))

SETTINGS_FILE = "settings.json"

MARKETS = {
    "코스닥": {
        "signal": "229200.KS", "trade": "233740.KS",
        "name_signal": "KODEX 코스닥150", "name_trade": "KODEX 코스닥150레버리지",
        "code_signal": "229200", "code_trade": "233740", "emoji": "📈",
        "card_bg":"#0a120a","card_bd":"#1a3020","box_bg":"#060f06","box_bd":"#1a2a1a","gap_bg":"#0a1a0a","gap_bd":"#1a4a1a","sub_col":"#7a9a7a",
    },
    "코스피": {
        "signal": "069500.KS", "trade": "122630.KS",
        "name_signal": "KODEX 200", "name_trade": "KODEX 레버리지",
        "code_signal": "069500", "code_trade": "122630", "emoji": "📊",
        "card_bg":"#111120","card_bd":"#1e2040","box_bg":"#0a0a1a","box_bd":"#1e2040","gap_bg":"#1a1500","gap_bd":"#3a3000","sub_col":"#7a7a9a",
    },
    "2차전지": {
        "signal": "305720.KS", "trade": "462330.KS",
        "name_signal": "KODEX 2차전지산업", "name_trade": "KODEX 2차전지레버리지",
        "code_signal": "305720", "code_trade": "462330", "emoji": "🔋",
        "card_bg":"#140a0a","card_bd":"#2e1010","box_bg":"#0f0606","box_bd":"#2e1010","gap_bg":"#1a1200","gap_bd":"#3a2800","sub_col":"#8a7070",
    },
    "반도체": {
        "signal": "091160.KS", "trade": "494310.KS",
        "name_signal": "KODEX 반도체", "name_trade": "KODEX 반도체레버리지",
        "code_signal": "091160", "code_trade": "494310", "emoji": "💾",
        "card_bg":"#111120","card_bd":"#1e2040","box_bg":"#0a0a1a","box_bd":"#1e2040","gap_bg":"#1a1500","gap_bd":"#3a3000","sub_col":"#7a7a9a",
    },
}

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    # Streamlit Cloud secrets 사용
    try:
        return dict(st.secrets)
    except:
        return {}

def save_settings(data):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

@st.cache_data(ttl=1800)
def load_market_data(ticker):
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
    atr20  = float(df["ATR20"].iloc[-1])
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
    sma120_dist  = (price - sma120) / price * 100
    return {
        "price": price, "sma120": sma120, "sma20": sma20,
        "atr20": atr20, "gap": gap,
        "trail_stop": trail_stop, "stop_dist": stop_dist,
        "sma120_dist": sma120_dist,
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
    sma_dist  = sig["sma120_dist"]
    if   15 < gap <= 18: alerts.append({"level":"D-1","msg":"매수 임박! gap " + str(round(gap,1)) + "%","kind":"buy"})
    elif 18 < gap <= 22: alerts.append({"level":"D-2","msg":"매수 접근 gap " + str(round(gap,1)) + "%","kind":"buy"})
    elif 22 < gap <= 26: alerts.append({"level":"D-3","msg":"매수 모니터링 gap " + str(round(gap,1)) + "%","kind":"buy"})
    if stop_dist is not None:
        if   0  < stop_dist <= 2:  alerts.append({"level":"D-1","msg":"ATR스탑 거의 도달! " + str(round(stop_dist,1)) + "% 남음","kind":"sell"})
        elif 2  < stop_dist <= 5:  alerts.append({"level":"D-2","msg":"ATR스탑 " + str(round(stop_dist,1)) + "% 남음","kind":"sell"})
        elif 5  < stop_dist <= 10: alerts.append({"level":"D-3","msg":"ATR스탑 " + str(round(stop_dist,1)) + "% 남음","kind":"sell"})
    if sig["above_sma120"]:
        if   0  < sma_dist <= 2:  alerts.append({"level":"D-1","msg":"SMA120 이탈 직전! " + str(round(sma_dist,1)) + "% 남음","kind":"sell"})
        elif 2  < sma_dist <= 5:  alerts.append({"level":"D-2","msg":"SMA120까지 " + str(round(sma_dist,1)) + "%","kind":"sell"})
    return alerts

def calc_profit(price, buy_price, amount):
    if buy_price and buy_price > 0 and amount and amount > 0:
        shares   = int(amount / buy_price)
        invested = shares * buy_price
        current  = shares * price
        profit   = current - invested
        pct      = (price - buy_price) / buy_price * 100
        return {"shares": shares, "invested": invested,
                "current": current, "profit": profit, "pct": pct}
    return None

def send_email(settings, subject, body):
    try:
        smtp_email = settings.get("smtp_email", "")
        smtp_pass  = settings.get("smtp_pass", "")
        to_email   = settings.get("email", "")
        if not all([smtp_email, smtp_pass, to_email]):
            return False, "이메일 설정 미완료"
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"]    = smtp_email
        msg["To"]      = to_email
        msg.attach(MIMEText(body, "plain", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(smtp_email, smtp_pass)
            s.send_message(msg)
        return True, "발송 성공"
    except Exception as e:
        return False, str(e)

# ── CSS ──
st.set_page_config(page_title="국내 ETF 알람", page_icon="📈", layout="wide")
st.markdown(
    "<style>"
    "body,.main,.block-container{background:#0d0d14!important;}"
    ".block-container{padding:1rem!important;}"
    "*{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}"
    ".stTabs [data-baseweb=tab]{font-size:15px;font-weight:600;color:#94a3b8;padding:8px 20px;}"
    ".stTabs [aria-selected=true]{color:#e2e8f0!important;}"
    "div[data-testid=metric-container]{background:#111120;border-radius:8px;padding:8px;border:1px solid #1e2040;}"
    "#MainMenu{visibility:hidden;}"
    "header{visibility:hidden;}"
    "footer{visibility:hidden;}"
    "</style>",
    unsafe_allow_html=True
)

settings = load_settings()
now_str  = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

@st.cache_data(ttl=1800)
def load_all_data():
    result = {}
    for name, info in MARKETS.items():
        df  = load_market_data(info["signal"])
        sig = calc_signal(df)
        result[name] = {"df": df, "sig": sig}
    return result

with st.spinner("📡 데이터 로딩 중..."):
    all_data = load_all_data()

tab1, tab2 = st.tabs(["📱 대시보드", "⚙️ 설정"])

# ══════════════════════════════════════════
# TAB 1: 대시보드
# ══════════════════════════════════════════
with tab1:
    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;'>"
        "<span style='color:#e2e8f0;font-size:17px;font-weight:600;'>🇰🇷 국내 레버리지 ETF 알람</span>"
        "<span style='display:flex;align-items:center;gap:4px;'>"
        "<span style='width:6px;height:6px;border-radius:50%;background:#4ade80;display:inline-block;'></span>"
        "<span style='color:#4ade80;font-size:11px;'>Live</span></span></div>"
        "<div style='font-size:10px;margin-bottom:10px;color:#9a9ab8;'>"
        "SMA120 + ATR(20)×2.0 + SMA20 재진입 (KST) | "
        "<span style='color:#e2e8f0;font-weight:700;'>" + now_str + "</span></div>",
        unsafe_allow_html=True
    )

    signals = []
    for mkt, data in all_data.items():
        sig = data["sig"]
        if sig:
            if sig["buy_signal"]: signals.append("<span style='color:#4ade80;font-size:11px;font-weight:600;'>🔴 " + mkt + " 매수</span>")
            if sig["reentry"]:    signals.append("<span style='color:#4ade80;font-size:11px;font-weight:600;'>🔴 " + mkt + " 재진입</span>")
            if sig["atr_sell"]:   signals.append("<span style='color:#f87171;font-size:11px;font-weight:600;'>🔵 " + mkt + " ATR매도</span>")
            if sig["sma_sell"]:   signals.append("<span style='color:#f87171;font-size:11px;font-weight:600;'>🔵 " + mkt + " SMA매도</span>")

    sep = "<span style='color:#2a3a2a;margin:0 4px;'>|</span>"
    if signals:
        st.markdown(
            "<div style='background:#0a1a0a;border:1px solid #1a3020;border-radius:8px;"
            "padding:7px 12px;margin-bottom:8px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;'>"
            "<span style='font-size:14px;'>🚨</span>" + sep.join(signals) + "</div>",
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            "<div style='background:#0a1a0a;border:1px solid #1a3020;border-radius:8px;"
            "padding:7px 12px;margin-bottom:8px;'>"
            "<span style='color:#4ade80;font-size:11px;'>✅ 현재 특이 신호 없음</span></div>",
            unsafe_allow_html=True
        )

    for mkt, data in all_data.items():
        sig  = data["sig"]
        info = MARKETS[mkt]
        buy_price   = float(settings.get(mkt + "_buy_price", 0) or 0)
        amount      = float(settings.get(mkt + "_amount", 0) or 0)
        profit_info = calc_profit(sig["price"], buy_price, amount) if sig else None
        pre_alerts  = get_pre_alerts(sig) if sig else []

        if sig is None:
            sig_txt, sig_col = "⬜ 데이터없음", "#6b7280"
            card_bg, card_bd = "#111120", "#1e2040"
        elif sig["buy_signal"]:
            sig_txt, sig_col = "🔴 매수 신호", "#4ade80"
            card_bg, card_bd = info["card_bg"], info["card_bd"]
        elif sig["reentry"]:
            sig_txt, sig_col = "🔴 재진입 신호", "#4ade80"
            card_bg, card_bd = info["card_bg"], info["card_bd"]
        elif sig["atr_sell"] or sig["sma_sell"]:
            sig_txt, sig_col = "🔵 매도 신호", "#f87171"
            card_bg, card_bd = "#140a0a", "#2e1010"
        elif sig["above_sma120"]:
            sig_txt, sig_col = "🟢 보유중", "#94a3b8"
            card_bg, card_bd = info["card_bg"], info["card_bd"]
        else:
            sig_txt, sig_col = "⚪ 대기중", "#6b7280"
            card_bg, card_bd = "#111120", "#1e2040"

        html = (
            "<div style='background:" + card_bg + ";border:1px solid " + card_bd + ";"
            "border-radius:10px;padding:9px 11px;margin-bottom:7px;'>"
            "<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:3px;'>"
            "<span style='color:#e2e8f0;font-size:14px;font-weight:600;'>" + info["emoji"] + " " + mkt + "</span>"
            "<span style='color:" + sig_col + ";font-size:13px;font-weight:600;'>" + sig_txt + "</span></div>"
            "<div style='font-size:10px;color:" + info["sub_col"] + ";margin-bottom:6px;'>"
            "신호: " + info["name_signal"] + " (" + info["code_signal"] + ") | "
            "매매: " + info["name_trade"] + " (" + info["code_trade"] + ")</div>"
        )

        if sig:
            price_s  = "{:,.0f}".format(sig["price"])
            sma120_s = "{:,.0f}".format(sig["sma120"])
            sma20_s  = "{:,.0f}".format(sig["sma20"])
            gap_s    = "{:+.1f}%".format(sig["gap"])
            gap_val  = sig["gap"]

            if sig["buy_signal"]:
                gap_col = "#4ade80"
                gap_sub = "<div style='font-size:7px;color:#2a5a2a;margin-top:1px;'>✅매수</div>"
            elif gap_val > 20:
                gap_col = "#fbbf24"
                gap_sub = "<div style='font-size:7px;color:#5a4a00;margin-top:1px;'>⚠️과열</div>"
            else:
                gap_col = "#94a3b8"
                gap_sub = ""

            if sig["trail_stop"] and sig["stop_dist"] is not None:
                sd = sig["stop_dist"]
                stop_col = "#f87171" if sd <= 3 else "#fbbf24"
                stop_dist_s = "🔴터치!" if sd <= 0 else "{:.1f}%남음".format(sd)
                stop_html = (
                    "<div style='font-size:9px;font-weight:600;color:" + stop_col + ";'>" +
                    "{:,.0f}".format(sig["trail_stop"]) + "</div>"
                    "<div style='font-size:7px;color:" + stop_col + ";margin-top:1px;'>" + stop_dist_s + "</div>"
                )
            else:
                stop_html = "<div style='font-size:12px;font-weight:600;color:#6b7280;'>—</div>"

            html += (
                "<div style='display:grid;grid-template-columns:repeat(5,1fr);gap:3px;'>"
                "<div style='background:" + info["box_bg"] + ";border:1px solid " + info["box_bd"] + ";border-radius:5px;padding:5px 2px;text-align:center;'>"
                "<div style='font-size:8px;color:#8a9aaa;margin-bottom:2px;'>현재가</div>"
                "<div style='font-size:11px;font-weight:600;color:#e2e8f0;'>₩" + price_s + "</div></div>"
                "<div style='background:" + info["box_bg"] + ";border:1px solid " + info["box_bd"] + ";border-radius:5px;padding:5px 2px;text-align:center;'>"
                "<div style='font-size:8px;color:#8a9aaa;margin-bottom:2px;'>SMA120</div>"
                "<div style='font-size:11px;font-weight:600;color:#e2e8f0;'>₩" + sma120_s + "</div></div>"
                "<div style='background:" + info["gap_bg"] + ";border:1px solid " + info["gap_bd"] + ";border-radius:5px;padding:5px 2px;text-align:center;'>"
                "<div style='font-size:8px;color:#8a9aaa;margin-bottom:2px;'>gap%</div>"
                "<div style='font-size:11px;font-weight:600;color:" + gap_col + ";'>" + gap_s + "</div>" + gap_sub + "</div>"
                "<div style='background:" + info["box_bg"] + ";border:1px solid " + info["box_bd"] + ";border-radius:5px;padding:5px 2px;text-align:center;'>"
                "<div style='font-size:8px;color:#8a9aaa;margin-bottom:2px;'>SMA20</div>"
                "<div style='font-size:11px;font-weight:600;color:#e2e8f0;'>₩" + sma20_s + "</div></div>"
                "<div style='background:" + info["gap_bg"] + ";border:1px solid " + info["gap_bd"] + ";border-radius:5px;padding:5px 2px;text-align:center;'>"
                "<div style='font-size:8px;color:#8a9aaa;margin-bottom:2px;'>ATR스탑</div>" +
                stop_html + "</div>"
                "</div>"
            )

            if profit_info:
                pc = "#4ade80" if profit_info["profit"] >= 0 else "#f87171"
                sg = "+" if profit_info["profit"] >= 0 else ""
                html += (
                    "<div style='background:" + info["box_bg"] + ";border:1px solid " + info["box_bd"] + ";"
                    "border-radius:6px;padding:5px 9px;margin-top:5px;font-size:10px;'>"
                    "💰 <span style='color:#94a3b8;'>" + str(profit_info["shares"]) + "주</span>"
                    " | 투자 ₩" + "{:,.0f}".format(profit_info["invested"]) +
                    " | 현재 ₩" + "{:,.0f}".format(profit_info["current"]) +
                    " | <span style='color:" + pc + ";font-weight:600;'>" +
                    sg + "₩" + "{:,.0f}".format(profit_info["profit"]) +
                    " (" + sg + "{:.1f}%)</span></div>".format(profit_info["pct"])
                )

        for a in pre_alerts:
            if a["level"] == "D-1":
                icon, ab, abd, ac = "🚨", "#1f0808", "#4a1010", "#f87171"
            elif a["level"] == "D-2":
                icon, ab, abd, ac = "⚠️", "#1a1200", "#3a2800", "#fbbf24"
            else:
                icon, ab, abd, ac = "📌", "#1a1200", "#2a2000", "#a3a380"
            html += (
                "<div style='background:" + ab + ";border:1px solid " + abd + ";"
                "border-radius:6px;padding:5px 9px;margin-top:5px;"
                "display:flex;align-items:center;gap:5px;font-size:10px;'>"
                "<span>" + icon + "</span>"
                "<span style='color:" + ac + ";'>[" + a["level"] + "] " + a["msg"] + "</span></div>"
            )

        html += "</div>"
        st.markdown(html, unsafe_allow_html=True)

    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        if st.button("📧 이메일 테스트", use_container_width=True):
            ok, msg = send_email(settings, "[ETF알람] 테스트", "정상 작동 중\n" + now_str)
            st.success("✅ 발송 성공!") if ok else st.error("❌ " + msg)
    with c2:
        if st.button("🔄 새로고침", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

# ══════════════════════════════════════════
# TAB 2: 설정
# ══════════════════════════════════════════
with tab2:
    st.markdown("<span style='color:#e2e8f0;font-size:16px;font-weight:600;'>⚙️ 설정</span>", unsafe_allow_html=True)
    st.caption("설정은 이 서버에 저장됩니다.")

    with st.form("settings_form"):
        st.markdown("**👤 사용자 정보**")
        c1, c2 = st.columns(2)
        name  = c1.text_input("이름",        value=settings.get("name",""))
        email = c2.text_input("수신 이메일", value=settings.get("email",""))

        st.markdown("**📧 Gmail 발신 설정**")
        st.caption("Gmail → 보안 → 2단계인증 → 앱 비밀번호 (16자리) 생성")
        c1, c2 = st.columns(2)
        smtp_email = c1.text_input("발신 Gmail",  value=settings.get("smtp_email",""))
        smtp_pass  = c2.text_input("앱 비밀번호", value=settings.get("smtp_pass",""), type="password")

        st.divider()
        st.markdown("**💰 시장별 투자 설정**")
        st.caption("투자금액·매수가 입력시 실시간 수익률 표시. 비워두면 모니터링만.")
        mkt_vals = {}
        for mkt, info in MARKETS.items():
            st.markdown(info["emoji"] + " **" + mkt + "** — " + info["name_trade"] + " (" + info["code_trade"] + ")")
            c1, c2, c3 = st.columns(3)
            amt = c1.number_input("투자금액(원)", min_value=0,
                value=int(settings.get(mkt + "_amount", 0) or 0),
                step=100000, key="amt_" + mkt, format="%d")
            bp  = c2.number_input("평균매수가(원)", min_value=0.0,
                value=float(settings.get(mkt + "_buy_price", 0) or 0),
                step=10.0, key="bp_" + mkt, format="%.0f")
            if amt > 0 and bp > 0:
                c3.metric("예상수량", str(int(amt/bp)) + "주")
            mkt_vals[mkt] = {"amount": amt, "buy_price": bp}

        st.divider()
        st.markdown("**🔔 알람 설정**")
        c1, c2 = st.columns(2)
        a_buy      = c1.checkbox("매수 신호",             value=settings.get("alarm_buy", True))
        a_sell     = c2.checkbox("매도 신호",             value=settings.get("alarm_sell", True))
        a_reentry  = c1.checkbox("재진입 신호",           value=settings.get("alarm_reentry", True))
        a_pre_buy  = c2.checkbox("매수 사전경보 D-3/2/1", value=settings.get("alarm_pre_buy", True))
        a_pre_sell = c1.checkbox("매도 사전경보 D-3/2/1", value=settings.get("alarm_pre_sell", True))
        a_email    = c2.checkbox("이메일 알람",            value=settings.get("alarm_email", True))

        st.divider()
        st.markdown("**🤖 키움증권 API (추후 자동매매)**")
        st.caption("지금은 저장만 됩니다.")
        c1, c2 = st.columns(2)
        kiwoom_id  = c1.text_input("키움 HTS ID", value=settings.get("kiwoom_id",""))
        kiwoom_key = c2.text_input("API Key",      value=settings.get("kiwoom_key",""), type="password")

        st.divider()
        submitted = st.form_submit_button("💾 설정 저장", use_container_width=True, type="primary")
        if submitted:
            new = {
                "name":name, "email":email,
                "smtp_email":smtp_email, "smtp_pass":smtp_pass,
                "alarm_buy":a_buy, "alarm_sell":a_sell,
                "alarm_reentry":a_reentry,
                "alarm_pre_buy":a_pre_buy, "alarm_pre_sell":a_pre_sell,
                "alarm_email":a_email,
                "kiwoom_id":kiwoom_id, "kiwoom_key":kiwoom_key,
            }
            for mkt, v in mkt_vals.items():
                new[mkt + "_amount"]    = v["amount"]
                new[mkt + "_buy_price"] = v["buy_price"]
            save_settings(new)
            st.success("✅ 설정 저장 완료!")
