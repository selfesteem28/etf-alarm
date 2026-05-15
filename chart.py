"""
국내 ETF 전략 차트
코스닥 / 코스피 / 2차전지 / 반도체
SMA120 + ATR(20)×2.0 트레일링스탑 + SMA20 재진입
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from datetime import datetime, timezone, timedelta
import warnings
warnings.filterwarnings("ignore")

KST = timezone(timedelta(hours=9))

plt.rcParams["font.family"]       = "DejaVu Sans"
plt.rcParams["figure.facecolor"]  = "#0e1117"
plt.rcParams["axes.facecolor"]    = "#1e2130"
plt.rcParams["axes.labelcolor"]   = "#cccccc"
plt.rcParams["xtick.color"]       = "#cccccc"
plt.rcParams["ytick.color"]       = "#cccccc"
plt.rcParams["text.color"]        = "#ffffff"
plt.rcParams["grid.color"]        = "#2a2a3a"
plt.rcParams["grid.alpha"]        = 0.5

MARKETS = {
    "코스닥":  {"ticker": "229200.KS", "name": "KODEX 코스닥150",    "color": "#FF4B4B"},
    "코스피":  {"ticker": "069500.KS", "name": "KODEX 200",          "color": "#FF8C00"},
    "2차전지": {"ticker": "305720.KS", "name": "KODEX 2차전지산업",  "color": "#00C49F"},
    "반도체":  {"ticker": "091160.KS", "name": "KODEX 반도체",       "color": "#818CF8"},
}

st.set_page_config(page_title="ETF 전략 차트", page_icon="📊", layout="wide")
st.markdown(
    "<style>"
    "body,.main,.block-container{background:#0e1117!important;}"
    ".block-container{padding:1rem!important;}"
    "#MainMenu{visibility:hidden;}header{visibility:hidden;}footer{visibility:hidden;}"
    "</style>",
    unsafe_allow_html=True
)

@st.cache_data(ttl=3600)
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
        r["ret"]   = r["price"].pct_change()
        return r.dropna()
    except:
        return None

def backtest(df):
    cash = 10000
    position = 0
    peak, trail_stop = None, None
    atr_sold = False
    equity = []
    buy_dates, sell_dates = [], []

    for i in range(1, len(df)):
        row      = df.iloc[i]
        prev_row = df.iloc[i-1]
        price    = float(row["price"])
        sma120   = float(row["SMA120"])
        sma20    = float(row["SMA20"])
        atr20    = float(row["ATR20"])
        gap      = float(row["gap"])
        date     = df.index[i]

        if position == 1:
            cash *= (1 + float(row["ret"]))
            if peak is None or price > peak:
                peak = price
            if gap > 20:
                ts = peak - atr20 * 2.0
                trail_stop = ts if trail_stop is None else max(trail_stop, ts)
            if trail_stop and price < trail_stop and gap > 20:
                position = 0; peak = None; trail_stop = None; atr_sold = True
                sell_dates.append(date)
            elif price < sma120:
                position = 0; peak = None; trail_stop = None; atr_sold = False
                sell_dates.append(date)
        else:
            buy_ok = (price > sma120) and (0 < gap <= 15) and not atr_sold
            sma20_cross = (price > sma20) and (float(prev_row["price"]) <= float(prev_row["SMA20"]))
            reentry = atr_sold and sma20_cross and (price > sma120)
            if buy_ok or reentry:
                position = 1; peak = price; trail_stop = None; atr_sold = False
                buy_dates.append(date)

        equity.append(cash)

    return pd.Series(equity, index=df.index[1:]), buy_dates, sell_dates

now_str = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

st.markdown(
    "<div style='color:#e2e8f0;font-size:18px;font-weight:600;margin-bottom:4px;'>📊 국내 ETF 전략 차트</div>"
    "<div style='color:#6b7280;font-size:11px;margin-bottom:16px;'>SMA120 + ATR(20)×2.0 + SMA20 재진입 | " + now_str + "</div>",
    unsafe_allow_html=True
)

mkt_sel = st.selectbox("시장 선택", list(MARKETS.keys()), index=0)
info    = MARKETS[mkt_sel]
period  = st.slider("기간 (거래일)", 120, 1500, 500, 50)

with st.spinner("데이터 로딩 중..."):
    df = load_data(info["ticker"])

if df is None:
    st.error("데이터를 불러올 수 없습니다.")
    st.stop()

df_chart = df.tail(period).copy()
equity, buy_dates, sell_dates = backtest(df)
equity_chart = equity.reindex(df_chart.index)
color = info["color"]

fig, axes = plt.subplots(4, 1, figsize=(12, 14),
                          gridspec_kw={"height_ratios": [3, 1.2, 1.2, 1.5]})
fig.suptitle(mkt_sel + " — " + info["name"], fontsize=13, y=0.98, color="#e2e8f0")

# ── 차트 1: 가격 + SMA ──
ax1 = axes[0]
ax1.plot(df_chart.index, df_chart["price"],  color="#ffffff", lw=1.0, label="현재가")
ax1.plot(df_chart.index, df_chart["SMA120"], color="#FFD700", lw=1.5, linestyle="--", label="SMA120")
ax1.plot(df_chart.index, df_chart["SMA20"],  color="#87CEEB", lw=1.0, linestyle=":",  label="SMA20")

for d in buy_dates:
    if d in df_chart.index:
        ax1.scatter(d, float(df_chart.loc[d, "price"]), color="#FF4B4B", marker="^", s=60, zorder=5)
for d in sell_dates:
    if d in df_chart.index:
        ax1.scatter(d, float(df_chart.loc[d, "price"]), color="#4B9EFF", marker="v", s=60, zorder=5)

ax1.set_title("가격 + SMA120 + SMA20  (▲매수 ▼매도)", fontsize=10, color="#cccccc")
ax1.legend(fontsize=8, loc="upper left")
ax1.grid(True); ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x,_: f"{x:,.0f}"))

# ── 차트 2: gap % ──
ax2 = axes[1]
ax2.plot(df_chart.index, df_chart["gap"], color=color, lw=1.2, label="gap%")
ax2.axhline(15,  color="#FF4B4B", lw=1.0, linestyle="--", label="매수상한 15%")
ax2.axhline(0,   color="#ffffff", lw=0.8)
ax2.axhline(20,  color="#F59E0B", lw=1.0, linestyle=":", label="ATR작동 20%")
ax2.fill_between(df_chart.index, 0, 15,
    where=(df_chart["gap"]>=0)&(df_chart["gap"]<=15),
    color="#FF4B4B", alpha=0.12, label="매수구간")
ax2.set_title("gap % (SMA120 대비)", fontsize=10, color="#cccccc")
ax2.legend(fontsize=8, loc="upper left"); ax2.grid(True)

# ── 차트 3: ATR 트레일링스탑 ──
ax3 = axes[2]
ax3.plot(df_chart.index, df_chart["price"],  color="#ffffff", lw=1.0, label="현재가", alpha=0.6)
ax3.plot(df_chart.index, df_chart["ATR20"]*2, color="#F59E0B", lw=1.2, linestyle="--", label="ATR×2.0")
ax3.set_title("ATR(20)×2.0 트레일링스탑 기준", fontsize=10, color="#cccccc")
ax3.legend(fontsize=8, loc="upper left"); ax3.grid(True)
ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x,_: f"{x:,.0f}"))

# ── 차트 4: 누적 수익 ──
ax4 = axes[3]
if equity_chart.notna().any():
    ax4.plot(equity_chart.index, equity_chart/10000, color=color, lw=2.0, label="전략")
bh = (1 + df_chart["ret"].fillna(0)).cumprod()
ax4.plot(df_chart.index, bh, color="#6B7280", lw=1.5, linestyle="--", label="단순보유")
ax4.axhline(1.0, color="#ffffff", lw=0.8, linestyle=":")
ax4.set_title("누적 수익 (배수)", fontsize=10, color="#cccccc")
ax4.legend(fontsize=8, loc="upper left"); ax4.grid(True)

final_eq = equity_chart.dropna().iloc[-1] / 10000 if equity_chart.notna().any() else 1.0
ax4.text(0.02, 0.92, "전략: {:.2f}배".format(final_eq),
         transform=ax4.transAxes, fontsize=10,
         bbox=dict(boxstyle="round", facecolor="#252840", alpha=0.8))

plt.tight_layout()
st.pyplot(fig)

# 현재 지표
if not df_chart.empty:
    sig_row = df_chart.iloc[-1]
    gap_val = float(sig_row["gap"])
    c1,c2,c3,c4 = st.columns(4)
    c1.metric("현재가",  "₩{:,.0f}".format(float(sig_row["price"])))
    c2.metric("SMA120", "₩{:,.0f}".format(float(sig_row["SMA120"])))
    c3.metric("gap",    "{:+.1f}%".format(gap_val),
              delta="매수구간" if 0 < gap_val <= 15 else ("과열" if gap_val > 20 else ""))
    c4.metric("ATR20",  "₩{:,.0f}".format(float(sig_row["ATR20"])))
