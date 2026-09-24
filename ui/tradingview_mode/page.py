import os

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from services.market_datasets import dataset
from utils.data_validation import load_ohlcv_csv
from .chart import render_tradingview_chart
from .timeframes import (
    UnsupportedTimeframeError,
    available_timeframes,
    load_resolution_data,
    resolve_timeframe,
)
from .indicators import INDICATORS, calculate_indicator
from .workspace import render_top_toolbar, render_workspace_panels

CUSTOM_FRONTEND_FLAG = "tv_custom_chart_prototype_enabled"
_TERMINAL_CSS = """<style>
[data-testid="stMainBlockContainer"] { padding-top: 3.4rem; padding-bottom: 0; padding-left: 1rem; padding-right: 1rem; max-width: 100%; }
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0.25rem; }
</style>"""


def _custom_frontend_default() -> bool:
    return os.environ.get("TV_CUSTOM_FRONTEND", "").strip().lower() in {"1", "true", "on", "yes"}


def render_tradingview_mode():
    # Development renderer flag. ON renders only the React terminal (never Plotly);
    # OFF keeps the proven Streamlit + Plotly workspace as the fallback.
    custom = st.toggle("Custom Chart Prototype", value=_custom_frontend_default(), key=CUSTOM_FRONTEND_FLAG,
                       help="Render TradingView Mode with the React + Lightweight Charts terminal. "
                            "Default can be set with TV_CUSTOM_FRONTEND=1.")
    if custom:
        from .component.terminal import render_custom_terminal
        st.markdown(_TERMINAL_CSS, unsafe_allow_html=True)
        render_custom_terminal()
        return

    st.markdown("### TradingView Mode")
    st.caption("Mode: Historical")
    ds, selected_tf_label, indicator_popover, tools_popover, settings_popover = render_top_toolbar()
    timeframe_options = available_timeframes(ds)
    if selected_tf_label not in timeframe_options:
        selected_tf_label = ds.timeframe
        st.session_state["tv_tf_selection"] = selected_tf_label
    try:
        resolution = resolve_timeframe(ds, selected_tf_label)
    except UnsupportedTimeframeError as exc:
        st.error(str(exc))
        return

    with tools_popover:
        st.caption("Drawing tools")
        for tool in ("Cursor / Crosshair", "Trend line", "Horizontal line", "Vertical line", "Rectangle", "Text", "Measure", "Delete drawings"):
            if st.button(tool, key=f"tv_tool_{tool.lower().replace(' ', '_').replace('/', '')}", use_container_width=True):
                st.info("Drawing tool coming in Phase 3B")
    with settings_popover:
        st.caption(f"Source: {resolution.source_label}")
        st.caption(f"Exact timeframe: {selected_tf_label}")

    # Resolve the exact selected chart data before rendering controls that depend on it.
    try:
        df_full = load_resolution_data(resolution, load_ohlcv_csv)
        min_date = df_full['timestamp'].min().date()
        max_date = df_full['timestamp'].max().date()
    except Exception:
        min_date = datetime.now().date() - timedelta(days=365)
        max_date = datetime.now().date()

    with settings_popover:
        start_date = st.date_input("Start Date", value=max_date - timedelta(days=30), min_value=min_date, max_value=max_date, key="tv_chart_start")
        end_date = st.date_input("End Date", value=max_date, min_value=min_date, max_value=max_date, key="tv_chart_end")
        show_volume = st.checkbox("Show Volume", value=True, key="tv_show_volume")

    # Indicator controls remain keyed and isolated, but live in a compact toolbar popover.
    with indicator_popover:
        st.caption("Overlay and lower-panel indicators")
    indicator_keys = [key for key in INDICATORS if key != "volume"]
    selected_indicator = indicator_popover.selectbox(
        "Add indicator", options=indicator_keys,
        format_func=lambda key: INDICATORS[key].display_name,
        key="tv_ind_type",
    )
    if indicator_popover.button("Add indicator", key="tv_ind_add"):
        st.session_state.setdefault("tv_indicators", {})[selected_indicator] = True
    active_indicators = st.session_state.setdefault("tv_indicators", {})
    indicator_configs = []
    for key in list(active_indicators):
        definition = INDICATORS[key]
        with indicator_popover.expander(definition.display_name, expanded=True):
            enabled = st.checkbox("Enabled", value=True, key=f"tv_ind_{key}_enabled")
            params = {}
            for name, default in definition.defaults.items():
                if isinstance(default, float):
                    params[name] = st.number_input(name.title(), min_value=0.1, value=float(default), step=0.1, key=f"tv_ind_{key}_{name}")
                else:
                    params[name] = st.number_input(name.title(), min_value=1, value=int(default), step=1, key=f"tv_ind_{key}_{name}")
            if st.button(f"Remove {definition.display_name}", key=f"tv_ind_{key}_remove"):
                del active_indicators[key]
                st.rerun()
            if enabled:
                indicator_configs.append((key, definition, params))

    # --- Data Loading & Processing ---
    try:
        # Load data
        df = load_resolution_data(resolution, load_ohlcv_csv)
        
        # Filter by date range
        mask = (df['timestamp'].dt.date >= start_date) & (df['timestamp'].dt.date <= end_date)
        df_filtered = df.loc[mask].copy()
        
        # Preserve UTC timestamps
        df_filtered['timestamp'] = pd.to_datetime(df_filtered['timestamp'], utc=True)

        indicator_values = {"overlay": [], "lower": []}
        for key, definition, params in indicator_configs:
            try:
                values = calculate_indicator(df_filtered, key, params)
                indicator_values[definition.pane].append({"key": key, "name": definition.display_name, "values": values})
            except ValueError as exc:
                st.error(str(exc))

        render_workspace_panels(df_filtered, render_tradingview_chart, show_volume=show_volume, indicators=indicator_values)

    except Exception as e:
        st.error(f"Error loading market data: {e}")
