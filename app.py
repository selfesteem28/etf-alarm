"""
국내 레버리지 ETF 알람 시스템 v2.1
수정사항:
  - sendPopupAlert JS 함수 최상단 정의 (알람 먹통 버그 수정)
  - trail_stop 계산 로직 수정 (peak 기반 단순 계산)
  - localStorage 저장/로드 안정화 (껐다 켜도 유지)
  - 설정값 Tab2 자동 계산 연동
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
        r = pd.DataFrame({"price": close, "high": high, "low": low})
        r["SMA120"] = r["price"].rolling(120).mean()
        r["SMA20"]  = r["price"].rolling(20).mean()
        prev = r["price"].shift(1)
        tr = pd.concat([r["high"]-r["low"],(r["high"]-prev).abs(),(r["low"]-prev).abs()], axis=1).max(axis=1)
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

    # ── trail_stop 수정: 최근 120일 고점 기준 단순 계산 ──
    recent_high = float(df["price"].tail(120).max())
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

# ── CSS ──
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

# ── 버그수정1: JS 공통 함수 최상단 정의 ──
# sendPopupAlert를 Tab3가 아닌 앱 시작 시 전역으로 정의
st.markdown("""
<script>
// ── 전역 공통 JS (앱 시작 시 즉시 정의) ──
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

# 자동 새로고침 1분
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
        "SMA120 + ATR(20)x2.0 + SMA20 재진입 (약 1분 지연) | "
        "<span style='color:#e2e8f0;font-weight:700;'>" + now_str + " KST</span></div>",
        unsafe_allow_html=True
    )

    signals = []
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

# ══════════════════════════════════════════
# TAB 2: 투자현황
# ══════════════════════════════════════════
with tab2:
    st.markdown(
        "<div style='color:#e2e8f0;font-size:17px;font-weight:600;margin-bottom:2px;'>💰 투자현황</div>"
        "<div style='font-size:10px;color:#9a9ab8;margin-bottom:12px;'>"
        "실시간 수익률 | <span style='color:#e2e8f0;font-weight:700;'>" + now_str + " KST</span></div>",
        unsafe_allow_html=True
    )

    prices_dict = {}
    for mkt, data in all_data.items():
        sig = data["sig"]
        prices_dict[MARKETS[mkt]["ls_key"]] = sig["price"] if sig else 0

    prices_js  = str(prices_dict).replace("'", '"')
    markets_js = str([
        {"key": info["ls_key"], "name": info["emoji"]+" "+mkt,
         "bg": info["card_bg"], "bd": info["card_bd"]}
        for mkt, info in MARKETS.items()
    ]).replace("'", '"')

    st.markdown("""
<div id="invest-wrap">
  <div style="color:#6b7280;font-size:12px;text-align:center;padding:20px;">데이터 로딩 중...</div>
</div>
<script>
(function(){
    var prices  = """ + prices_js + """;
    var markets = """ + markets_js + """;

    function fNum(n){ return Math.round(n).toLocaleString('ko-KR'); }

    function renderInvest(){
        var totalInvest=0, totalCurrent=0, html='';
        markets.forEach(function(m){
            var amt   = parseFloat(localStorage.getItem(m.key+'_amount')   || '0');
            var bp    = parseFloat(localStorage.getItem(m.key+'_buy_price')|| '0');
            var price = prices[m.key] || 0;
            if(amt>0 && bp>0 && price>0){
                var shares  = Math.floor(amt/bp);
                var invest  = shares*bp;
                var current = shares*price;
                var profit  = current-invest;
                var pct     = ((price-bp)/bp*100).toFixed(1);
                totalInvest+=invest; totalCurrent+=current;
                var pc=profit>=0?'#4ade80':'#f87171', sg=profit>=0?'+':'';
                html+='<div style="background:'+m.bg+';border:1px solid '+m.bd+';border-radius:10px;padding:10px 12px;margin-bottom:7px;">'
                    +'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">'
                    +'<span style="color:#e2e8f0;font-size:13px;font-weight:600;">'+m.name+'</span>'
                    +'<span style="color:'+pc+';font-size:13px;font-weight:600;">'+sg+pct+'%</span></div>'
                    +'<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:5px;">'
                    +'<div style="background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;"><div style="font-size:9px;color:#6b7280;margin-bottom:2px;">투자금</div><div style="font-size:10px;font-weight:600;color:#e2e8f0;">₩'+fNum(invest)+'</div></div>'
                    +'<div style="background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;"><div style="font-size:9px;color:#6b7280;margin-bottom:2px;">평균매수가</div><div style="font-size:10px;font-weight:600;color:#e2e8f0;">₩'+fNum(bp)+'</div></div>'
                    +'<div style="background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;"><div style="font-size:9px;color:#6b7280;margin-bottom:2px;">보유수량</div><div style="font-size:10px;font-weight:600;color:#e2e8f0;">'+shares+'주</div></div>'
                    +'<div style="background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;"><div style="font-size:9px;color:#6b7280;margin-bottom:2px;">현재가</div><div style="font-size:10px;font-weight:600;color:#e2e8f0;">₩'+fNum(price)+'</div></div>'
                    +'<div style="background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;"><div style="font-size:9px;color:#6b7280;margin-bottom:2px;">평가금액</div><div style="font-size:10px;font-weight:600;color:'+pc+';">₩'+fNum(current)+'</div></div>'
                    +'<div style="background:#0a0a1a;border-radius:6px;padding:6px 4px;text-align:center;"><div style="font-size:9px;color:#6b7280;margin-bottom:2px;">수익금</div><div style="font-size:10px;font-weight:600;color:'+pc+';">'+sg+'₩'+fNum(profit)+'</div></div>'
                    +'</div></div>';
            } else {
                html+='<div style="background:'+m.bg+';border:1px solid '+m.bd+';border-radius:10px;padding:10px 12px;margin-bottom:7px;">'
                    +'<div style="color:#e2e8f0;font-size:13px;font-weight:600;margin-bottom:4px;">'+m.name+'</div>'
                    +'<div style="color:#6b7280;font-size:11px;">⚙️ 설정 탭에서 투자금액·매수가를 입력하세요</div></div>';
            }
        });

        var tp=totalCurrent-totalInvest;
        var tpct=totalInvest>0?((tp/totalInvest)*100).toFixed(1):0;
        var tc=tp>=0?'#4ade80':'#f87171', tsg=tp>=0?'+':'';
        var summary = totalInvest>0
            ? '<div style="background:#111120;border:1px solid #1e2040;border-radius:10px;padding:12px 14px;margin-bottom:12px;">'
              +'<div style="font-size:10px;color:#6b7280;margin-bottom:8px;">전체 요약</div>'
              +'<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">'
              +'<div style="background:#0a0a1a;border-radius:8px;padding:8px;text-align:center;"><div style="font-size:9px;color:#6b7280;margin-bottom:3px;">총 투자금</div><div style="font-size:13px;font-weight:600;color:#e2e8f0;">₩'+fNum(totalInvest)+'</div></div>'
              +'<div style="background:#0a0a1a;border-radius:8px;padding:8px;text-align:center;"><div style="font-size:9px;color:#6b7280;margin-bottom:3px;">현재 평가금</div><div style="font-size:13px;font-weight:600;color:'+tc+';">₩'+fNum(totalCurrent)+'</div></div>'
              +'<div style="background:#0a0a1a;border-radius:8px;padding:8px;text-align:center;"><div style="font-size:9px;color:#6b7280;margin-bottom:3px;">총 수익금</div><div style="font-size:13px;font-weight:600;color:'+tc+';">'+tsg+'₩'+fNum(tp)+'</div></div>'
              +'<div style="background:#0a0a1a;border-radius:8px;padding:8px;text-align:center;"><div style="font-size:9px;color:#6b7280;margin-bottom:3px;">총 수익률</div><div style="font-size:13px;font-weight:600;color:'+tc+';">'+tsg+tpct+'%</div></div>'
              +'</div></div>'
            : '';
        document.getElementById('invest-wrap').innerHTML = summary + html;
    }

    // 탭 전환·새로고침 후에도 안정적으로 로드
    if(document.readyState === 'loading'){
        document.addEventListener('DOMContentLoaded', function(){ setTimeout(renderInvest,300); });
    } else {
        setTimeout(renderInvest, 300);
    }
})();
</script>
    """, unsafe_allow_html=True)

# ══════════════════════════════════════════
# TAB 3: 설정
# ══════════════════════════════════════════
with tab3:
    st.markdown(
        "<div style='color:#e2e8f0;font-size:17px;font-weight:600;margin-bottom:2px;'>⚙️ 설정</div>"
        "<div style='font-size:10px;color:#9a9ab8;margin-bottom:12px;'>설정은 이 브라우저에 저장됩니다 (창 닫아도 유지)</div>",
        unsafe_allow_html=True
    )

    mkt_inputs = ""
    for mkt, info in MARKETS.items():
        k = info["ls_key"]
        mkt_inputs += (
            "<div style='background:#111120;border:1px solid #1e2040;border-radius:8px;padding:9px 11px;margin-bottom:7px;'>"
            "<div style='color:#e2e8f0;font-size:12px;font-weight:600;margin-bottom:7px;'>"
            + info["emoji"] + " " + mkt + " — " + info["name_trade"] + " (" + info["trade_code"] + ")</div>"
            "<div style='display:grid;grid-template-columns:1fr 1fr;gap:8px;'>"
            "<div><div style='font-size:9px;color:#9a9ab8;margin-bottom:3px;'>투자금액 (원)</div>"
            "<input id='" + k + "_amount' type='number' placeholder='예: 10000000'"
            " oninput=\"autoSave('" + k + "_amount',this.value)\""
            " style='width:100%;background:#0a0a1a;border:1px solid #1e2040;border-radius:5px;"
            "padding:6px 8px;color:#e2e8f0;font-size:11px;outline:none;box-sizing:border-box;'></div>"
            "<div><div style='font-size:9px;color:#9a9ab8;margin-bottom:3px;'>평균매수가 (원)</div>"
            "<input id='" + k + "_buy_price' type='number' placeholder='예: 19000'"
            " oninput=\"autoSave('" + k + "_buy_price',this.value)\""
            " style='width:100%;background:#0a0a1a;border:1px solid #1e2040;border-radius:5px;"
            "padding:6px 8px;color:#e2e8f0;font-size:11px;outline:none;box-sizing:border-box;'></div>"
            "</div></div>"
        )

    st.markdown("""
<div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid #1e2040;">👤 사용자 정보</div>
<div style="margin-bottom:14px;">
  <div style="font-size:10px;color:#9a9ab8;margin-bottom:4px;">이름</div>
  <input id="user_name" type="text" placeholder="이름 입력"
    oninput="autoSave('user_name',this.value)"
    style="width:100%;background:#111120;border:1px solid #1e2040;border-radius:6px;padding:8px 10px;color:#e2e8f0;font-size:12px;outline:none;box-sizing:border-box;">
</div>

<div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid #1e2040;">🔔 팝업 알람</div>
<div style="margin-bottom:6px;">
  <label style="display:flex;align-items:center;gap:8px;background:#111120;border:1px solid #1e2040;border-radius:6px;padding:8px 10px;cursor:pointer;margin-bottom:5px;">
    <input type="radio" name="popup" id="popup_off" value="off" onchange="autoSave('popup_mode','off')" style="accent-color:#4ade80;">
    <span style="color:#e2e8f0;font-size:12px;">끄기</span>
  </label>
  <label style="display:flex;align-items:center;gap:8px;background:#111120;border:1px solid #1e2040;border-radius:6px;padding:8px 10px;cursor:pointer;margin-bottom:5px;">
    <input type="radio" name="popup" id="popup_sound" value="sound" onchange="autoSave('popup_mode','sound')" style="accent-color:#4ade80;">
    <span style="color:#e2e8f0;font-size:12px;">켜기 — 소리/진동 (폰 설정 따름)</span>
  </label>
  <label style="display:flex;align-items:center;gap:8px;background:#111120;border:1px solid #1e2040;border-radius:6px;padding:8px 10px;cursor:pointer;margin-bottom:5px;">
    <input type="radio" name="popup" id="popup_silent" value="silent" onchange="autoSave('popup_mode','silent')" style="accent-color:#4ade80;">
    <span style="color:#e2e8f0;font-size:12px;">켜기 — 무음 (팝업만)</span>
  </label>
</div>
<div style="background:#1a1200;border:1px solid #3a2800;border-radius:6px;padding:8px 10px;margin-bottom:14px;">
  <div style="color:#fbbf24;font-size:9px;line-height:1.7;">
    ⚠️ 알람 허용 방법<br>
    크롬: 설정 → 개인정보 → 사이트 설정 → 알림 → 허용<br>
    삼성 브라우저: 설정 → 사이트 및 다운로드 → 알림 → 허용
  </div>
</div>

<div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid #1e2040;">💰 시장별 투자 설정</div>
<div style="font-size:10px;color:#9a9ab8;margin-bottom:10px;">입력하면 자동 저장되고 투자현황 탭에서 바로 계산됩니다.</div>
""" + mkt_inputs + """

<div style="font-size:13px;font-weight:600;color:#e2e8f0;margin-bottom:8px;padding-bottom:5px;border-bottom:1px solid #1e2040;margin-top:10px;">🤖 키움증권 API (추후 자동매매)</div>
<div style="font-size:10px;color:#9a9ab8;margin-bottom:8px;">지금은 저장만 됩니다. 추후 업데이트 예정.</div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:16px;">
  <div>
    <div style="font-size:9px;color:#9a9ab8;margin-bottom:3px;">키움 HTS ID</div>
    <input id="kiwoom_id" type="text" placeholder="미입력"
      oninput="autoSave('kiwoom_id',this.value)"
      style="width:100%;background:#0a0a1a;border:1px solid #1e2040;border-radius:5px;padding:6px 8px;color:#e2e8f0;font-size:11px;outline:none;box-sizing:border-box;">
  </div>
  <div>
    <div style="font-size:9px;color:#9a9ab8;margin-bottom:3px;">API Key</div>
    <input id="kiwoom_key" type="password" placeholder="미입력"
      oninput="autoSave('kiwoom_key',this.value)"
      style="width:100%;background:#0a0a1a;border:1px solid #1e2040;border-radius:5px;padding:6px 8px;color:#e2e8f0;font-size:11px;outline:none;box-sizing:border-box;">
  </div>
</div>

<div id="save-status" style="text-align:center;font-size:11px;color:#4ade80;min-height:20px;margin-bottom:8px;"></div>

<script>
(function(){
    // ── 버그수정3: 자동저장 + 안정적 로드 ──
    var ALL_KEYS = ['user_name',
        'kosdaq_amount','kosdaq_buy_price',
        'kospi_amount','kospi_buy_price',
        'battery_amount','battery_buy_price',
        'semi_amount','semi_buy_price',
        'kiwoom_id','kiwoom_key'];

    // 입력할 때마다 즉시 저장
    window.autoSave = function(key, value) {
        try {
            localStorage.setItem(key, value);
            var el = document.getElementById('save-status');
            if(el){ el.textContent = '✅ 자동 저장됨'; setTimeout(function(){ el.textContent=''; }, 1500); }
        } catch(e) {}
    };

    // 라디오 버튼 변경 시 즉시 저장
    window.autoSave = function(key, value) {
        try { localStorage.setItem(key, value); } catch(e) {}
        var el = document.getElementById('save-status');
        if(el){ el.textContent = '✅ 자동 저장됨'; setTimeout(function(){ el.textContent=''; }, 1500); }
    };

    function loadAll() {
        ALL_KEYS.forEach(function(k){
            var el  = document.getElementById(k);
            var val = localStorage.getItem(k);
            if(el && val !== null && val !== '') el.value = val;
        });
        var mode = localStorage.getItem('popup_mode') || 'off';
        var rb = document.getElementById('popup_' + mode);
        if(rb) rb.checked = true;
    }

    // DOM 준비 후 로드 (탭 전환 시에도 안정적)
    function tryLoad(retry){
        var el = document.getElementById('user_name');
        if(el){ loadAll(); }
        else if(retry > 0){ setTimeout(function(){ tryLoad(retry-1); }, 200); }
    }
    tryLoad(10);
})();
</script>
    """, unsafe_allow_html=True)
