"""
국내 레버리지 ETF 알람 시스템 v3.0
- Tab1: 대시보드 (실시간 신호)
- Tab2: 투자현황 (거래시작일~오늘 시뮬, 다음날 시가 기준)
- Tab3: 설정 (팝업알람 + 시장별 투자금/거래시작일)
"""


import streamlit as st
import yfinance as yf
import requests
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import warnings
warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))

MARKETS = {
    "코스닥": {
        "signal_code": "229200", "trade_code": "233740",
        "name_signal": "KODEX 코스닥150", "name_trade": "KODEX 코스닥150레버리지",
        "emoji": "📈", "ls_key": "kosdaq",
        "card_bg":"#0a120a","card_bd":"#1a3020","box_bg":"#060f06","box_bd":"#1a2a1a","gap_bg":"#0a1a0a","gap_bd":"#1a4a1a","sub_col":"#7a9a7a",
    },
    "코스피": {
        "signal_code": "069500", "trade_code": "122630",
        "name_signal": "KODEX 200", "name_trade": "KODEX 레버리지",
        "emoji": "📊", "ls_key": "kospi",
        "card_bg":"#111120","card_bd":"#1e2040","box_bg":"#0a0a1a","box_bd":"#1e2040","gap_bg":"#1a1500","gap_bd":"#3a3000","sub_col":"#7a7a9a",
    },
    "2차전지": {
        "signal_code": "305720", "trade_code": "462330",
        "name_signal": "KODEX 2차전지산업", "name_trade": "KODEX 2차전지레버리지",
        "emoji": "🔋", "ls_key": "battery",
        "card_bg":"#140a0a","card_bd":"#2e1010","box_bg":"#0f0606","box_bd":"#2e1010","gap_bg":"#1a1200","gap_bd":"#3a2800","sub_col":"#8a7070",
    },
    "반도체": {
        "signal_code": "091160", "trade_code": "494310",
        "name_signal": "KODEX 반도체", "name_trade": "KODEX 반도체레버리지",
        "emoji": "💾", "ls_key": "semi",
        "card_bg":"#111120","card_bd":"#1e2040","box_bg":"#0a0a1a","box_bd":"#1e2040","gap_bg":"#1a1500","gap_bd":"#3a3000","sub_col":"#7a7a9a",
    },
}

COMMISSION = 0.0005  # 편도 0.05%

# ══════════════════════════════════════════════════════════
# 공통 함수
# ══════════════════════════════════════════════════════════

def get_naver_price(code):
    try:
        url = "https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:" + code
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            item = res.json()["result"]["areas"][0]["datas"][0]
            return float(item["nv"])
    except:
        pass
    return None

@st.cache_data(ttl=3600)
def load_history(code):
    try:
        df = yf.download(code + ".KS", start="2018-01-01", auto_adjust=True, progress=False)
        if df.empty:
            return None
        close = df["Close"].squeeze()
        high  = df["High"].squeeze()
        low   = df["Low"].squeeze()
        open_ = df["Open"].squeeze()
        r = pd.DataFrame({"price": close, "high": high, "low": low, "open": open_})
        r["SMA120"] = r["price"].rolling(120).mean()
        r["SMA20"]  = r["price"].rolling(20).mean()
        prev = r["price"].shift(1)
        tr = pd.concat([r["high"]-r["low"], (r["high"]-prev).abs(), (r["low"]-prev).abs()], axis=1).max(axis=1)
        r["ATR20"] = tr.rolling(20).mean()
        return r.dropna()
    except:
        return None

def calc_signal(df, rt_price=None):
    if df is None or len(df) < 5:
        return None
    price  = rt_price if rt_price else float(df["price"].iloc[-1])
    sma120 = float(df["SMA120"].iloc[-1])
    sma20  = float(df["SMA20"].iloc[-1])
    atr20  = float(df["ATR20"].iloc[-1])
    gap    = (price - sma120) / sma120 * 100

    recent_high = float(df["high"].tail(120).max())
    trail_stop  = recent_high - atr20 * 2.0 if gap > 20 else None
    stop_dist   = (price - trail_stop) / price * 100 if trail_stop else None

    above_sma120 = price > sma120
    buy_signal   = above_sma120 and (0 < gap <= 15)
    atr_sell     = bool(trail_stop and gap > 20 and price < trail_stop)
    sma_sell     = not above_sma120
    prev_price   = float(df["price"].iloc[-2])
    prev_sma20   = float(df["SMA20"].iloc[-2])
    reentry      = (price > sma20) and (prev_price <= prev_sma20) and above_sma120
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

# ══════════════════════════════════════════════════════════
# Tab2 시뮬레이션 (다음날 시가 기준)
# ══════════════════════════════════════════════════════════

@st.cache_data(ttl=3600)
def run_simulation(signal_code, trade_code, start_date_str, initial_amount):
    # SMA120 워밍업을 위해 시작일 200일 전부터 로드
    start_dt   = datetime.strptime(start_date_str, "%Y-%m-%d")
    data_start = (start_dt - timedelta(days=200)).strftime("%Y-%m-%d")

    try:
        sig_raw   = yf.download(signal_code + ".KS", start=data_start, auto_adjust=True, progress=False)
        trade_raw = yf.download(trade_code  + ".KS", start=data_start, auto_adjust=True, progress=False)
    except:
        return [], None

    if sig_raw.empty or trade_raw.empty:
        return [], None

    def flatten(df):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        return df

    sig_raw   = flatten(sig_raw)
    trade_raw = flatten(trade_raw)

    common   = sig_raw.index.intersection(trade_raw.index)
    sig_df   = sig_raw.loc[common]
    trade_df = trade_raw.loc[common]

    c      = sig_df["Close"]
    h      = sig_df["High"]
    l      = sig_df["Low"]
    sma120 = c.rolling(120).mean()
    sma20  = c.rolling(20).mean()
    prev_c = c.shift(1)
    tr     = pd.concat([h-l, (h-prev_c).abs(), (l-prev_c).abs()], axis=1).max(axis=1)
    atr20  = tr.rolling(20).mean()
    peak120 = h.rolling(120).max()
    trail_s = peak120 - atr20 * 2.0

    start_idx = sig_df.index.searchsorted(pd.Timestamp(start_date_str))
    start_idx = max(start_idx, 121)

    trades     = []
    cash       = initial_amount
    shares     = 0.0
    avg_price  = 0.0
    in_market  = False
    hold_trail = 0.0

    dates = sig_df.index

    for i in range(start_idx, len(dates) - 1):
        price_now = float(c.iloc[i])
        sl        = float(sma120.iloc[i])
        ss        = float(sma20.iloc[i])
        atr_v     = float(atr20.iloc[i])
        trail_v   = float(trail_s.iloc[i])

        if np.isnan(sl) or np.isnan(atr_v):
            continue

        gap          = (price_now - sl) / sl * 100
        above_sma120 = price_now > sl

        buy_signal = above_sma120 and (0 < gap <= 15) and not in_market
        sma_sell   = (not above_sma120) and in_market
        atr_sell   = in_market and (gap > 20) and (price_now < hold_trail)
        prev_p     = float(c.iloc[i-1])
        prev_ss    = float(sma20.iloc[i-1])
        reentry    = (not in_market) and above_sma120 and (price_now > ss) and (prev_p <= prev_ss)

        exec_price = float(trade_df["Open"].iloc[i + 1])
        exec_date  = dates[i + 1].strftime("%Y-%m-%d")

        if buy_signal or reentry:
            cost      = exec_price * (1 + COMMISSION)
            shares    = cash / cost
            avg_price = exec_price
            cash      = 0.0
            in_market = True
            hold_trail = trail_v
            reason = "매수" if buy_signal else "재진입"
            trades.append({
                "날짜":      exec_date,
                "구분":      "🔴 " + reason,
                "SMA120":   round(sl, 0),
                "GAP%":     round(gap, 1),
                "체결가":    round(exec_price, 0),
                "주수":      round(shares, 2),
                "평균단가":  round(avg_price, 0),
                "잔고(원)":  round(shares * exec_price, 0),
                "매매수익률": "-",
            })

        elif sma_sell or atr_sell:
            proceeds = shares * exec_price * (1 - COMMISSION)
            pnl_pct  = (exec_price - avg_price) / avg_price * 100
            reason   = "SMA매도" if sma_sell else "ATR매도"
            trades.append({
                "날짜":      exec_date,
                "구분":      "🔵 " + reason,
                "SMA120":   round(sl, 0),
                "GAP%":     round(gap, 1),
                "체결가":    round(exec_price, 0),
                "주수":      round(shares, 2),
                "평균단가":  round(avg_price, 0),
                "잔고(원)":  round(proceeds, 0),
                "매매수익률": f"{pnl_pct:+.2f}%",
            })
            cash      = proceeds
            shares    = 0.0
            avg_price = 0.0
            in_market = False
            hold_trail = 0.0

        if in_market:
            hold_trail = max(hold_trail, trail_v)

    last_price = float(trade_df["Close"].iloc[-1]) if not trade_df.empty else 0
    if in_market and avg_price > 0:
        current_value = shares * last_price
        pnl_pct = (last_price - avg_price) / avg_price * 100
        position = {
            "상태":     "보유중",
            "보유주수": round(shares, 2),
            "평균단가": round(avg_price, 0),
            "현재가":   round(last_price, 0),
            "평가금액": round(current_value, 0),
            "수익률":   round(pnl_pct, 2),
            "ATR스탑":  round(hold_trail, 0),
        }
    else:
        pnl_total = (cash - initial_amount) / initial_amount * 100
        position = {
            "상태":   "현금대기",
            "현금":   round(cash, 0),
            "수익률": round(pnl_total, 2),
        }

    return trades, position


# ══════════════════════════════════════════════════════════
# Streamlit 앱
# ══════════════════════════════════════════════════════════

st.set_page_config(page_title="국내 ETF 알람", page_icon="📈", layout="wide")
st.markdown(
    "<style>"
    "body,.main,.block-container{background:#0d0d14!important;}"
    ".block-container{padding:1rem!important;}"
    "*{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}"
    "#MainMenu{visibility:hidden;}header{visibility:hidden;}footer{visibility:hidden;}"
    ".stTabs [data-baseweb=tab]{font-size:15px;font-weight:600;color:#6b7280;padding:8px 20px;}"
    ".stTabs [aria-selected=true]{color:#e2e8f0!important;}"
    "</style>",
    unsafe_allow_html=True
)

st.markdown("""
<script>
window.sendPopupAlert = function(title, body) {
    var mode = localStorage.getItem('popup_mode') || 'off';
    if(mode === 'off') return;
    if('Notification' in window && Notification.permission === 'granted') {
        new Notification(title, {body: body, silent: mode === 'silent'});
    } else if(Notification.permission !== 'denied') {
        Notification.requestPermission().then(function(p) {
            if(p === 'granted') new Notification(title, {body: body, silent: mode === 'silent'});
        });
    }
};
</script>
""", unsafe_allow_html=True)

try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=60000, key="autorefresh")
except:
    pass

now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M")

@st.cache_data(ttl=60)
def load_all():
    result = {}
    for name, info in MARKETS.items():
        code = info["signal_code"]
        df   = load_history(code)
        rt   = get_naver_price(code)
        sig  = calc_signal(df, rt)
        result[name] = {"sig": sig}
    return result

with st.spinner("📡 네이버 실시간 데이터 로딩 중..."):
    all_data = load_all()

tab1, tab2, tab3 = st.tabs(["📱 대시보드", "💰 투자현황", "⚙️ 설정"])

# ══════════════════════════════════════════════════════════
# TAB 1: 대시보드
# ══════════════════════════════════════════════════════════
with tab1:
    st.markdown(
        "<div style='display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;'>"
        "<span style='color:#e2e8f0;font-size:17px;font-weight:600;'>🇰🇷 국내 레버리지 ETF 알람</span>"
        "<span style='display:flex;align-items:center;gap:4px;'>"
        "<span style='width:6px;height:6px;border-radius:50%;background:#4ade80;display:inline-block;'></span>"
        "<span style='color:#4ade80;font-size:11px;'>Live</span></span></div>"
        "<div style='font-size:10px;margin-bottom:10px;color:#9a9ab8;'>"
        "SMA120 + ATR(20)x2.0 + SMA20 재진입 (약 1분 지연) | "
        "<span style='color:#e2e8f0;font-weight:700;'>" + now_str + " KST</span></div>",
        unsafe_allow_html=True
    )

    signals  = []
    alert_js = ""
    for mkt, data in all_data.items():
        sig = data["sig"]
        if sig:
            if sig["buy_signal"]:
                signals.append("<span style='color:#4ade80;font-size:11px;font-weight:600;'>🔴 " + mkt + " 매수</span>")
                alert_js += "sendPopupAlert('🚨 ETF 알람', '" + mkt + " 매수 신호! gap " + str(round(sig["gap"],1)) + "%');"
            if sig["reentry"]:
                signals.append("<span style='color:#4ade80;font-size:11px;font-weight:600;'>🔴 " + mkt + " 재진입</span>")
                alert_js += "sendPopupAlert('🚨 ETF 알람', '" + mkt + " 재진입 신호!');"
            if sig["atr_sell"]:
                signals.append("<span style='color:#f87171;font-size:11px;font-weight:600;'>🔵 " + mkt + " ATR매도</span>")
                alert_js += "sendPopupAlert('🚨 ETF 알람', '" + mkt + " ATR 매도 신호!');"
            if sig["sma_sell"]:
                signals.append("<span style='color:#f87171;font-size:11px;font-weight:600;'>🔵 " + mkt + " SMA매도</span>")
                alert_js += "sendPopupAlert('🚨 ETF 알람', '" + mkt + " SMA120 매도 신호!');"

    sep = "<span style='color:#2a3a2a;margin:0 4px;'>|</span>"
    if signals:
        st.markdown(
            "<div style='background:#0a1a0a;border:1px solid #1a3020;border-radius:8px;"
            "padding:7px 12px;margin-bottom:8px;display:flex;align-items:center;gap:6px;flex-wrap:wrap;'>"
            "<span style='font-size:14px;'>🚨</span>" + sep.join(signals) + "</div>"
            "<script>setTimeout(function(){" + alert_js + "},500);</script>",
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
        pre_alerts = get_pre_alerts(sig) if sig else []

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
            "신호: " + info["name_signal"] + " (" + info["signal_code"] + ") | "
            "매매: " + info["name_trade"] + " (" + info["trade_code"] + ")</div>"
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
                stop_html + "</div></div>"
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
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

# ══════════════════════════════════════════════════════════
# TAB 2: 투자현황 (시뮬레이션)
# ══════════════════════════════════════════════════════════
with tab2:
    st.markdown(
        "<div style='color:#e2e8f0;font-size:17px;font-weight:600;margin-bottom:2px;'>💰 투자현황</div>"
        "<div style='font-size:10px;color:#9a9ab8;margin-bottom:10px;'>"
        "전략 신호(종가) → 다음날 시가 체결 기준 | "
        "<span style='color:#e2e8f0;font-weight:700;'>" + now_str + " KST</span></div>",
        unsafe_allow_html=True
    )

    total_invest  = 0
    total_current = 0
    any_configured = False

    for mkt, info in MARKETS.items():
        k          = info["ls_key"]
        start_val  = st.session_state.get(f"cfg_{k}_start",  None)
        amount_val = st.session_state.get(f"cfg_{k}_amount", 0)
        info_bg    = info["card_bg"]
        info_bd    = info["card_bd"]

        if not start_val or not amount_val or amount_val == 0:
            st.markdown(
                f"<div style='background:{info_bg};border:1px solid {info_bd};"
                f"border-radius:10px;padding:10px 12px;margin-bottom:8px;'>"
                f"<div style='color:#e2e8f0;font-size:13px;font-weight:600;margin-bottom:4px;'>"
                f"{info['emoji']} {mkt}</div>"
                f"<div style='color:#6b7280;font-size:11px;'>⚙️ 설정 탭에서 거래시작일과 투자금을 입력하세요</div></div>",
                unsafe_allow_html=True
            )
            continue

        any_configured = True
        with st.spinner(f"{mkt} 시뮬 계산 중..."):
            trades, position = run_simulation(
                info["signal_code"], info["trade_code"],
                start_val.strftime("%Y-%m-%d"), float(amount_val)
            )

        if position is None:
            st.markdown(
                f"<div style='background:{info_bg};border:1px solid {info_bd};"
                f"border-radius:10px;padding:10px 12px;margin-bottom:8px;'>"
                f"<div style='color:#e2e8f0;font-size:13px;font-weight:600;'>{info['emoji']} {mkt}</div>"
                f"<div style='color:#f87171;font-size:11px;'>데이터 오류 — 잠시 후 다시 시도하세요</div></div>",
                unsafe_allow_html=True
            )
            continue

        pnl     = position["수익률"]
        pnl_col = "#4ade80" if pnl >= 0 else "#f87171"
        pnl_s   = f"{pnl:+.2f}%"

        if position["상태"] == "보유중":
            total_invest  += float(amount_val)
            total_current += position["평가금액"]
            status_html = (
                f"<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:5px;margin-bottom:6px;'>"
                f"<div style='background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;'>"
                f"<div style='font-size:8px;color:#6b7280;margin-bottom:2px;'>상태</div>"
                f"<div style='font-size:11px;font-weight:600;color:#4ade80;'>🔴 보유중</div></div>"
                f"<div style='background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;'>"
                f"<div style='font-size:8px;color:#6b7280;margin-bottom:2px;'>보유주수</div>"
                f"<div style='font-size:11px;font-weight:600;color:#e2e8f0;'>{position['보유주수']:,.2f}주</div></div>"
                f"<div style='background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;'>"
                f"<div style='font-size:8px;color:#6b7280;margin-bottom:2px;'>평균단가</div>"
                f"<div style='font-size:11px;font-weight:600;color:#e2e8f0;'>₩{position['평균단가']:,.0f}</div></div>"
                f"<div style='background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;'>"
                f"<div style='font-size:8px;color:#6b7280;margin-bottom:2px;'>현재가</div>"
                f"<div style='font-size:11px;font-weight:600;color:#e2e8f0;'>₩{position['현재가']:,.0f}</div></div>"
                f"<div style='background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;'>"
                f"<div style='font-size:8px;color:#6b7280;margin-bottom:2px;'>평가금액</div>"
                f"<div style='font-size:11px;font-weight:600;color:{pnl_col};'>₩{position['평가금액']:,.0f}</div></div>"
                f"<div style='background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;'>"
                f"<div style='font-size:8px;color:#6b7280;margin-bottom:2px;'>수익률</div>"
                f"<div style='font-size:14px;font-weight:700;color:{pnl_col};'>{pnl_s}</div></div></div>"
                f"<div style='font-size:9px;color:#fbbf24;padding-bottom:6px;'>ATR스탑: ₩{position['ATR스탑']:,.0f}</div>"
            )
        else:
            total_invest  += float(amount_val)
            total_current += position["현금"]
            status_html = (
                f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:6px;'>"
                f"<div style='background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;'>"
                f"<div style='font-size:8px;color:#6b7280;margin-bottom:2px;'>상태</div>"
                f"<div style='font-size:11px;font-weight:600;color:#94a3b8;'>⬜ 현금대기</div></div>"
                f"<div style='background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;'>"
                f"<div style='font-size:8px;color:#6b7280;margin-bottom:2px;'>현금</div>"
                f"<div style='font-size:11px;font-weight:600;color:#e2e8f0;'>₩{position['현금']:,.0f}</div></div>"
                f"<div style='background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;grid-column:span 2;'>"
                f"<div style='font-size:8px;color:#6b7280;margin-bottom:2px;'>누적수익률</div>"
                f"<div style='font-size:14px;font-weight:700;color:{pnl_col};'>{pnl_s}</div></div></div>"
            )

        st.markdown(
            f"<div style='background:{info_bg};border:1px solid {info_bd};"
            f"border-radius:10px;padding:10px 12px;margin-bottom:8px;'>"
            f"<div style='color:#e2e8f0;font-size:13px;font-weight:600;margin-bottom:6px;'>"
            f"{info['emoji']} {mkt}</div>"
            + status_html + "</div>",
            unsafe_allow_html=True
        )

        if trades:
            with st.expander(f"  {mkt} 거래 내역 ({len(trades)}건)", expanded=False):
                df_t = pd.DataFrame(trades)
                st.dataframe(
                    df_t,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "날짜":      st.column_config.TextColumn("날짜",     width=95),
                        "구분":      st.column_config.TextColumn("구분",     width=80),
                        "SMA120":    st.column_config.NumberColumn("SMA120", format="₩%,.0f"),
                        "GAP%":      st.column_config.NumberColumn("GAP%",   format="%.1f%%"),
                        "체결가":    st.column_config.NumberColumn("체결가",  format="₩%,.0f"),
                        "주수":      st.column_config.NumberColumn("주수",    format="%.2f"),
                        "평균단가":  st.column_config.NumberColumn("평균단가",format="₩%,.0f"),
                        "잔고(원)":  st.column_config.NumberColumn("잔고",    format="₩%,.0f"),
                        "매매수익률":st.column_config.TextColumn("수익률",   width=70),
                    }
                )

    # 전체 요약
    if total_invest > 0:
        tp   = total_current - total_invest
        tpct = tp / total_invest * 100
        tc   = "#4ade80" if tp >= 0 else "#f87171"
        tsg  = "+" if tp >= 0 else ""
        st.markdown(
            f"<div style='background:#111120;border:1px solid #1e2040;border-radius:10px;"
            f"padding:12px 14px;margin-top:4px;'>"
            f"<div style='font-size:10px;color:#6b7280;margin-bottom:8px;'>📊 전체 요약</div>"
            f"<div style='display:grid;grid-template-columns:1fr 1fr;gap:8px;'>"
            f"<div style='background:#0a0a1a;border-radius:8px;padding:8px;text-align:center;'>"
            f"<div style='font-size:9px;color:#6b7280;margin-bottom:3px;'>총 투자금</div>"
            f"<div style='font-size:13px;font-weight:600;color:#e2e8f0;'>₩{total_invest:,.0f}</div></div>"
            f"<div style='background:#0a0a1a;border-radius:8px;padding:8px;text-align:center;'>"
            f"<div style='font-size:9px;color:#6b7280;margin-bottom:3px;'>현재 평가금</div>"
            f"<div style='font-size:13px;font-weight:600;color:{tc};'>₩{total_current:,.0f}</div></div>"
            f"<div style='background:#0a0a1a;border-radius:8px;padding:8px;text-align:center;'>"
            f"<div style='font-size:9px;color:#6b7280;margin-bottom:3px;'>총 수익금</div>"
            f"<div style='font-size:13px;font-weight:600;color:{tc};'>{tsg}₩{abs(tp):,.0f}</div></div>"
            f"<div style='background:#0a0a1a;border-radius:8px;padding:8px;text-align:center;'>"
            f"<div style='font-size:9px;color:#6b7280;margin-bottom:3px;'>총 수익률</div>"
            f"<div style='font-size:15px;font-weight:700;color:{tc};'>{tsg}{tpct:.2f}%</div></div>"
            f"</div></div>",
            unsafe_allow_html=True
        )

# ══════════════════════════════════════════════════════════
# TAB 3: 설정
# ══════════════════════════════════════════════════════════
with tab3:
    st.markdown(
        "<div style='color:#e2e8f0;font-size:17px;font-weight:600;margin-bottom:2px;'>⚙️ 설정</div>"
        "<div style='font-size:10px;color:#9a9ab8;margin-bottom:12px;'>설정은 이 브라우저에 저장됩니다</div>",
        unsafe_allow_html=True
    )

    # 팝업 알람
    st.markdown(
        "<div style='font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;"
        "padding-bottom:5px;border-bottom:1px solid #1e2040;'>🔔 팝업 알람</div>",
        unsafe_allow_html=True
    )
    st.markdown("""
<div style="margin-bottom:6px;">
  <label style="display:flex;align-items:center;gap:8px;background:#111120;border:1px solid #1e2040;border-radius:6px;padding:8px 10px;cursor:pointer;margin-bottom:5px;">
    <input type="radio" name="popup" id="popup_off" value="off" onchange="autoSave('popup_mode','off')" style="accent-color:#4ade80;">
    <span style="color:#e2e8f0;font-size:12px;">끄기</span>
  </label>
  <label style="display:flex;align-items:center;gap:8px;background:#111120;border:1px solid #1e2040;border-radius:6px;padding:8px 10px;cursor:pointer;margin-bottom:5px;">
    <input type="radio" name="popup" id="popup_sound" value="sound" onchange="autoSave('popup_mode','sound')" style="accent-color:#4ade80;">
    <span style="color:#e2e8f0;font-size:12px;">켜기 — 소리/진동</span>
  </label>
  <label style="display:flex;align-items:center;gap:8px;background:#111120;border:1px solid #1e2040;border-radius:6px;padding:8px 10px;cursor:pointer;margin-bottom:5px;">
    <input type="radio" name="popup" id="popup_silent" value="silent" onchange="autoSave('popup_mode','silent')" style="accent-color:#4ade80;">
    <span style="color:#e2e8f0;font-size:12px;">켜기 — 무음 (팝업만)</span>
  </label>
</div>
<div style="background:#1a1200;border:1px solid #3a2800;border-radius:6px;padding:8px 10px;margin-bottom:16px;">
  <div style="color:#fbbf24;font-size:9px;line-height:1.7;">
    ⚠️ 알람 허용: 크롬 → 설정 → 사이트 설정 → 알림 → 허용
  </div>
</div>
    """, unsafe_allow_html=True)

    # 시장별 투자 설정
    st.markdown(
        "<div style='font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:4px;"
        "padding-bottom:5px;border-bottom:1px solid #1e2040;'>💰 시장별 투자 설정</div>"
        "<div style='font-size:10px;color:#9a9ab8;margin-bottom:10px;'>"
        "거래 시작일 + 투자금 입력 → 저장 → 투자현황 탭에서 시뮬 결과 확인</div>",
        unsafe_allow_html=True
    )

    with st.form("settings_form"):
        cfg = {}
        for mkt, info in MARKETS.items():
            k = info["ls_key"]
            st.markdown(
                f"<div style='color:#e2e8f0;font-size:12px;font-weight:600;margin-bottom:4px;margin-top:4px;'>"
                f"{info['emoji']} {mkt}</div>",
                unsafe_allow_html=True
            )
            c1, c2 = st.columns(2)
            with c1:
                # 기존 session_state 값 있으면 기본값으로 사용
                default_start = st.session_state.get(f"cfg_{k}_start", datetime(2024, 1, 2).date())
                cfg[f"{k}_start"] = st.date_input(
                    "거래 시작일", value=default_start, key=f"fi_{k}_start"
                )
            with c2:
                default_amt = st.session_state.get(f"cfg_{k}_amount", 0)
                cfg[f"{k}_amount"] = st.number_input(
                    "투자금 (원)", min_value=0, max_value=100000000,
                    value=int(default_amt), step=1000000, key=f"fi_{k}_amount"
                )
            st.markdown("<div style='margin-bottom:4px;'></div>", unsafe_allow_html=True)

        submitted = st.form_submit_button("💾 저장 후 시뮬레이션", use_container_width=True)
        if submitted:
            for mkt, info in MARKETS.items():
                k = info["ls_key"]
                st.session_state[f"cfg_{k}_start"]  = cfg[f"{k}_start"]
                st.session_state[f"cfg_{k}_amount"] = cfg[f"{k}_amount"]
            run_simulation.clear()
            st.success("✅ 저장 완료! 투자현황 탭에서 결과를 확인하세요")

    # 팝업 로드 JS
    st.markdown("""
<script>
(function(){
    window.autoSave = function(key, value) {
        try { localStorage.setItem(key, value); } catch(e) {}
    };
    function loadPopup() {
        var mode = localStorage.getItem('popup_mode') || 'off';
        var rb = document.getElementById('popup_' + mode);
        if(rb) rb.checked = true;
    }
    function tryLoad(retry){
        var el = document.getElementById('popup_off');
        if(el){ loadPopup(); }
        else if(retry > 0){ setTimeout(function(){ tryLoad(retry-1); }, 200); }
    }
    tryLoad(10);
})();
</script>
    """, unsafe_allow_html=True)
