"""Streamlit parameter controls for BTC V3.0 — Regime Adaptive."""
from __future__ import annotations

from datetime import time

import streamlit as st

from strategies.btc_v3_regime_adaptive import V3Parameters


def render_v3_controls() -> V3Parameters:
    flags = st.columns(4)
    trend_enabled = flags[0].checkbox("Trend Engine", value=True, key="v3_trend_on")
    range_enabled = flags[1].checkbox("Range Engine", value=True, key="v3_range_on")
    longs_enabled = flags[2].checkbox("Enable Longs", value=True, key="v3_long_on")
    shorts_enabled = flags[3].checkbox("Enable Shorts", value=True, key="v3_short_on")

    with st.expander("H1 REGIME", expanded=True):
        a, b, c, d = st.columns(4)
        h1_fast = a.number_input("H1 Fast EMA", min_value=1, value=50, step=1, key="v3_h1_fast")
        h1_slow = b.number_input("H1 Slow EMA", min_value=2, value=200, step=1, key="v3_h1_slow")
        h1_atr = c.number_input("H1 ATR Length", min_value=2, value=14, step=1, key="v3_h1_atr")
        h1_slope = d.number_input("H1 EMA200 Slope Lookback", min_value=1, value=4, step=1, key="v3_h1_slope")
        e, f = st.columns(2)
        trend_sep = e.number_input("Trend Min EMA Separation (H1 ATR)", min_value=0.0,
                                   value=0.65, key="v3_trend_sep")
        range_sep = f.number_input("Range Max EMA Separation (H1 ATR)", min_value=0.0,
                                   value=0.80, key="v3_range_sep")

    with st.expander("M15 INDICATORS", expanded=True):
        a, b, c, d = st.columns(4)
        ema_fast = a.number_input("M15 EMA Fast", min_value=1, value=20, step=1, key="v3_m15_fast")
        ema_slow = b.number_input("M15 EMA Slow", min_value=2, value=50, step=1, key="v3_m15_slow")
        atr_length = c.number_input("ATR Length", min_value=2, value=14, step=1, key="v3_atr")
        rsi_length = d.number_input("RSI Length", min_value=2, value=14, step=1, key="v3_rsi")
        e, f, g, h = st.columns(4)
        di_length = e.number_input("DI Length", min_value=2, value=14, step=1, key="v3_di")
        adx_smoothing = f.number_input("ADX Smoothing", min_value=2, value=14, step=1, key="v3_adx_smoothing")
        trend_adx = g.number_input("Trend Min ADX", min_value=0.0, value=18.0, key="v3_trend_adx")
        range_adx = h.number_input("Range Max ADX", min_value=0.0, value=24.0, key="v3_range_adx")

    with st.expander("TREND ENTRY", expanded=False):
        a, b, c, d = st.columns(4)
        trend_lookback = a.number_input("Trend Break Lookback", min_value=1, value=5, step=1, key="v3_trend_lookback")
        trend_body = b.number_input("Trend Minimum Body %", min_value=1.0, max_value=100.0, value=50.0, key="v3_trend_body")
        trend_range_min = c.number_input("Trend Min Candle Range ATR", min_value=0.01, value=0.60, key="v3_trend_range_min")
        trend_range_max = d.number_input("Trend Max Candle Range ATR", min_value=0.01, value=2.75, key="v3_trend_range_max")
        e, f, g, h = st.columns(4)
        trend_long_min = e.number_input("Trend Long RSI Min", min_value=0.0, max_value=100.0, value=50.0, key="v3_trend_long_min")
        trend_long_max = f.number_input("Trend Long RSI Max", min_value=0.0, max_value=100.0, value=76.0, key="v3_trend_long_max")
        trend_short_min = g.number_input("Trend Short RSI Min", min_value=0.0, max_value=100.0, value=24.0, key="v3_trend_short_min")
        trend_short_max = h.number_input("Trend Short RSI Max", min_value=0.0, max_value=100.0, value=50.0, key="v3_trend_short_max")
        i, j = st.columns(2)
        trend_extension = i.number_input("Trend Max EMA20 Extension ATR", min_value=0.0, value=2.50, key="v3_trend_ext")
        trend_stop_lookback = j.number_input("Trend Stop Lookback", min_value=1, value=2, step=1, key="v3_trend_stop_lb")

    with st.expander("RANGE ENTRY", expanded=False):
        a, b, c, d = st.columns(4)
        sweep_lookback = a.number_input("Sweep Lookback", min_value=1, value=8, step=1, key="v3_sweep_lb")
        sweep_min = b.number_input("Minimum Sweep Depth ATR", min_value=0.0, value=0.05, key="v3_sweep_min")
        sweep_max = c.number_input("Maximum Sweep Depth ATR", min_value=0.0, value=0.80, key="v3_sweep_max")
        range_body = d.number_input("Range Minimum Body %", min_value=1.0, max_value=100.0, value=35.0, key="v3_range_body")
        e, f = st.columns(2)
        range_long_rsi = e.number_input("Range Long RSI Max", min_value=0.0, max_value=100.0, value=46.0, key="v3_range_long_rsi")
        range_short_rsi = f.number_input("Range Short RSI Min", min_value=0.0, max_value=100.0, value=54.0, key="v3_range_short_rsi")

    with st.expander("ENTRY / STOP / PENDING", expanded=False):
        a, b, c, d = st.columns(4)
        entry_buffer = a.number_input("Entry Buffer ATR", min_value=0.0, value=0.05, key="v3_entry_buffer")
        stop_buffer = b.number_input("Stop Buffer ATR", min_value=0.0, value=0.20, key="v3_stop_buffer")
        pending = c.number_input("Pending Bars", min_value=1, value=2, step=1, key="v3_pending")
        min_stop = d.number_input("Minimum Stop ATR", min_value=0.01, value=0.50, key="v3_min_stop")
        e, f = st.columns(2)
        max_stop = e.number_input("Maximum Stop ATR", min_value=0.01, value=3.00, key="v3_max_stop")
        max_trades = f.number_input("Max Filled Trades / UTC Day", min_value=1, value=3, step=1, key="v3_max_trades")

    with st.expander("SESSION", expanded=False):
        a, b = st.columns(2)
        session_start = a.time_input("Session Start UTC", value=time(0, 0), step=900, key="v3_session_start")
        session_end = b.time_input("Session End UTC", value=time(22, 0), step=900, key="v3_session_end")
        st.caption("All seven UTC weekdays are enabled, including Saturday and Sunday.")

    return V3Parameters(
        trend_enabled=bool(trend_enabled), range_enabled=bool(range_enabled),
        longs_enabled=bool(longs_enabled), shorts_enabled=bool(shorts_enabled),
        h1_fast_ema=int(h1_fast), h1_slow_ema=int(h1_slow),
        h1_atr_length=int(h1_atr), h1_slope_lookback=int(h1_slope),
        trend_min_h1_separation_atr=float(trend_sep),
        range_max_h1_separation_atr=float(range_sep),
        ema_fast=int(ema_fast), ema_slow=int(ema_slow), atr_length=int(atr_length),
        rsi_length=int(rsi_length), di_length=int(di_length),
        adx_smoothing=int(adx_smoothing), trend_min_adx=float(trend_adx),
        range_max_adx=float(range_adx), trend_structure_lookback=int(trend_lookback),
        trend_minimum_body_percent=float(trend_body) / 100,
        trend_minimum_range_atr=float(trend_range_min),
        trend_maximum_range_atr=float(trend_range_max),
        trend_long_rsi_min=float(trend_long_min), trend_long_rsi_max=float(trend_long_max),
        trend_short_rsi_min=float(trend_short_min), trend_short_rsi_max=float(trend_short_max),
        trend_maximum_extension_atr=float(trend_extension),
        trend_stop_lookback=int(trend_stop_lookback), range_sweep_lookback=int(sweep_lookback),
        range_minimum_sweep_atr=float(sweep_min), range_maximum_sweep_atr=float(sweep_max),
        range_minimum_body_percent=float(range_body) / 100,
        range_long_rsi_max=float(range_long_rsi), range_short_rsi_min=float(range_short_rsi),
        entry_buffer_atr=float(entry_buffer), stop_buffer_atr=float(stop_buffer),
        minimum_stop_atr=float(min_stop), maximum_stop_atr=float(max_stop),
        pending_bars=int(pending), max_trades_per_day=int(max_trades),
        session_start=session_start, session_end=session_end,
    )
