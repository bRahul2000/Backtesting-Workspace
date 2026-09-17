"""Streamlit parameter controls for BTC V2.2.0 Setup B."""
from __future__ import annotations

from datetime import time

import streamlit as st

from strategies.btc_v2_setup_b import SetupBParameters


DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def render_setup_b_controls() -> SetupBParameters:
    a, b = st.columns(2)
    longs_enabled = a.checkbox("Enable Longs", value=True)
    shorts_enabled = b.checkbox("Enable Shorts", value=True)
    with st.expander("HIGHER TIMEFRAME", expanded=True):
        a, b, c = st.columns(3)
        h1_fast = a.number_input("H1 Fast EMA", min_value=1, value=50, step=1)
        h1_slow = b.number_input("H1 Slow EMA", min_value=2, value=200, step=1)
        h1_slope = c.number_input("H1 EMA200 Slope Lookback", min_value=1, max_value=50, value=5, step=1)

    with st.expander("M15 INDICATORS", expanded=True):
        a, b, c, d = st.columns(4)
        ema_fast = a.number_input("M15 EMA Fast", min_value=1, value=20, step=1)
        ema_slow = b.number_input("M15 EMA Slow", min_value=2, value=50, step=1)
        rsi_length = c.number_input("RSI Length", min_value=2, value=14, step=1)
        atr_length = d.number_input("ATR Length", min_value=2, value=14, step=1, key="btc_atr_length")
        e, f, g = st.columns(3)
        di_length = e.number_input("DI Length", min_value=2, value=14, step=1)
        adx_smoothing = f.number_input("ADX Smoothing", min_value=2, value=14, step=1)
        minimum_adx = g.number_input("Minimum ADX", min_value=0.0, value=18.0)

    with st.expander("BREAKOUT", expanded=False):
        a, b, c, d = st.columns(4)
        structure = a.number_input("Structure Lookback", min_value=3, max_value=12, value=5, step=1)
        body = b.number_input("Minimum Body %", min_value=30.0, max_value=100.0, value=50.0)
        range_min = c.number_input("Minimum Candle Range ATR", min_value=0.10, max_value=5.0, value=0.60)
        range_max = d.number_input("Maximum Candle Range ATR", min_value=0.50, max_value=10.0, value=2.75)

    with st.expander("RSI", expanded=False):
        a, b, c, d = st.columns(4)
        long_min = a.number_input("Long RSI Min", min_value=0.0, max_value=100.0, value=50.0)
        long_max = b.number_input("Long RSI Max", min_value=0.0, max_value=100.0, value=75.0)
        short_min = c.number_input("Short RSI Min", min_value=0.0, max_value=100.0, value=25.0)
        short_max = d.number_input("Short RSI Max", min_value=0.0, max_value=100.0, value=50.0)

    with st.expander("ANTI-CHASE", expanded=False):
        extension = st.number_input("Maximum EMA20 Extension ATR", min_value=0.0, value=2.50)

    with st.expander("ENTRY / STOP", expanded=False):
        a, b, c, d = st.columns(4)
        entry_buffer = a.number_input("Entry Buffer ATR", min_value=0.0, value=0.05)
        stop_lookback = b.number_input("Structure Stop Lookback", min_value=1, max_value=10, value=2, step=1)
        stop_buffer = c.number_input("Stop Buffer ATR", min_value=0.0, value=0.20)
        pending_bars = d.number_input("Pending Bars", min_value=1, max_value=5, value=2, step=1)
        e, f = st.columns(2)
        min_stop = e.number_input("Minimum Stop ATR", min_value=0.01, value=0.60)
        max_stop = f.number_input("Maximum Stop ATR", min_value=0.01, value=3.00)

    with st.expander("SESSION", expanded=False):
        a, b = st.columns(2)
        session_start = a.time_input("Session Start UTC", value=time(7, 0), step=900)
        session_end = b.time_input("Session End UTC", value=time(20, 0), step=900)
        days = st.columns(7)
        allowed_days = frozenset(
            index for index, name in enumerate(DAY_NAMES)
            if days[index].checkbox(name, value=True, key=f"btc_day_{index}")
        )

    with st.expander("RISK PERMISSIONS", expanded=False):
        a, b, c, d = st.columns(4)
        max_trades = a.number_input("Max Trades / UTC Day", min_value=1, max_value=20, value=3, step=1)
        daily_dd = b.number_input("Max Daily Equity DD %", min_value=0.01, value=1.0)
        loss_streak = c.number_input("Max Daily Closed Loss Streak", min_value=1, max_value=20, value=3, step=1)
        monthly_dd = d.number_input("Max Monthly Equity DD %", min_value=0.01, value=6.0)
        all_time = st.checkbox("All-Time Equity Protection", value=False)
        all_time_dd = st.number_input("Max All-Time DD %", min_value=0.01, value=10.0)

    return SetupBParameters(
        h1_fast_ema=int(h1_fast), h1_slow_ema=int(h1_slow),
        h1_slope_lookback=int(h1_slope), ema_fast=int(ema_fast), ema_slow=int(ema_slow),
        rsi_length=int(rsi_length), di_length=int(di_length),
        adx_smoothing=int(adx_smoothing), minimum_adx=float(minimum_adx),
        atr_length=int(atr_length), structure_lookback=int(structure),
        minimum_body_percent=float(body) / 100,
        minimum_range_atr=float(range_min), maximum_range_atr=float(range_max),
        long_rsi_min=float(long_min), long_rsi_max=float(long_max),
        short_rsi_min=float(short_min), short_rsi_max=float(short_max),
        maximum_extension_atr=float(extension), entry_buffer_atr=float(entry_buffer),
        structure_stop_lookback=int(stop_lookback), stop_buffer_atr=float(stop_buffer),
        pending_bars=int(pending_bars), minimum_stop_atr=float(min_stop),
        maximum_stop_atr=float(max_stop), session_start=session_start,
        session_end=session_end, allowed_days=allowed_days,
        max_trades_per_day=int(max_trades),
        maximum_daily_drawdown_percent=float(daily_dd),
        maximum_daily_losing_streak=int(loss_streak),
        maximum_monthly_drawdown_percent=float(monthly_dd),
        all_time_protection=bool(all_time),
        maximum_all_time_drawdown_percent=float(all_time_dd),
        longs_enabled=bool(longs_enabled), shorts_enabled=bool(shorts_enabled),
    )
