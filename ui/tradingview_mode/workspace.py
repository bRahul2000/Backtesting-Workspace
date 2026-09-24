"""Small, testable layout helpers for the TradingView workspace."""
from __future__ import annotations

import streamlit as st

from services.market_datasets import MarketDataset, all_datasets, dataset
from utils.data_validation import load_ohlcv_csv
from .timeframes import available_timeframes


def quick_timeframe_labels(timeframes: tuple[str, ...]) -> tuple[str, ...]:
    """Return compact button labels while preserving the registered values."""
    return tuple("D" if value == "1d" else "W" if value == "1w" else value for value in timeframes)


def timeframe_value(label: str) -> str:
    return "1d" if label == "D" else "1w" if label == "W" else label


def registered_watchlist() -> tuple[MarketDataset, ...]:
    """The watchlist is sourced only from the local market dataset registry."""
    return all_datasets()


def watchlist_groups() -> tuple[tuple[MarketDataset, ...], ...]:
    """Group native timeframes by provider and instrument for compact display."""
    groups: dict[tuple[str, str, str], list[MarketDataset]] = {}
    for entry in registered_watchlist():
        groups.setdefault((entry.instrument, entry.broker, entry.symbol), []).append(entry)
    return tuple(tuple(entries) for entries in groups.values())


def render_top_toolbar():
    """Render the live workspace toolbar and return its current selections."""
    datasets = all_datasets()
    options = {entry.label: entry.key for entry in datasets}
    selected_key = st.session_state.get("tv_dataset_selection", datasets[0].key)
    if selected_key not in options.values():
        selected_key = datasets[0].key
    toolbar = st.container()
    with toolbar:
        symbol_col, tf_col, indicator_col, tools_col, settings_col = st.columns([1.6, 7.0, 1.1, 1.1, 1.1])
        with symbol_col:
            keys = list(options.values())
            st.caption("Symbol")
            selected_key = st.selectbox("Symbol", keys, index=keys.index(selected_key), format_func=lambda key: dataset(key).symbol, label_visibility="collapsed", key="tv_dataset_selector")
            st.session_state["tv_dataset_selection"] = selected_key
            st.caption(dataset(selected_key).broker.split()[0])
        selected_dataset = dataset(selected_key)
        with tf_col:
            timeframe_options = available_timeframes(selected_dataset)
            current_tf = st.session_state.get("tv_tf_selection", selected_dataset.timeframe)
            if current_tf not in timeframe_options:
                current_tf = selected_dataset.timeframe
            st.caption("Timeframe")
            button_cols = st.columns(len(timeframe_options))
            for button_col, label in zip(button_cols, quick_timeframe_labels(timeframe_options)):
                if button_col.button(label, key=f"tv_tf_{timeframe_value(label)}", type="primary" if timeframe_value(label) == current_tf else "secondary"):
                    st.session_state["tv_tf_selection"] = timeframe_value(label)
                    st.rerun()
        indicator_popover = indicator_col.popover("Indicators", use_container_width=True)
        tools_popover = tools_col.popover("Tools", use_container_width=True)
        settings_popover = settings_col.popover("Settings", use_container_width=True)
    return selected_dataset, st.session_state.get("tv_tf_selection", selected_dataset.timeframe), indicator_popover, tools_popover, settings_popover


def render_workspace_panels(data, chart_renderer, *, show_volume, indicators):
    """Render the left tools, dominant chart, watchlist, and bottom dock."""
    left_col, center_col, right_col = st.columns([0.32, 5.08, 1.45], gap="small")
    with left_col:
        st.caption("Tools")
        tools = (("⌖", "Cursor / crosshair"), ("╱", "Trend line"), ("—", "Horizontal line"), ("│", "Vertical line"), ("□", "Rectangle"), ("T", "Text"), ("↕", "Measure"), ("⌫", "Delete drawings"))
        for icon, help_text in tools:
            if st.button(icon, key=f"tv_left_tool_{help_text.lower().replace(' ', '_').replace('/', '')}", help=help_text, use_container_width=True):
                st.info("Drawing tool coming in Phase 3B")
    with center_col:
        chart_renderer(data, show_volume=show_volume, indicators=indicators)
    with right_col:
        st.markdown("#### Watchlist")
        st.caption("Registered markets")
        with st.container(height=270, border=True):
            for group in watchlist_groups():
                available = [entry for entry in group if entry.exists]
                if not available:
                    continue
                primary = available[0]
                watch_data = load_ohlcv_csv(primary.path)
                last_close = float(watch_data["close"].iloc[-1]) if not watch_data.empty else None
                close_text = f"{last_close:.2f}" if last_close is not None else "—"
                native = ", ".join(entry.timeframe for entry in available)
                st.markdown(f"**{primary.symbol}**  \\n+{primary.broker.split()[0]} · {close_text}  \\n+<small>Native: {native}</small>", unsafe_allow_html=True)
                if st.button("Open", key=f"tv_watch_{primary.key}", help=primary.label, use_container_width=True):
                    st.session_state["tv_dataset_selection"] = primary.key
                    st.session_state["tv_tf_selection"] = primary.timeframe
                    st.rerun()
                st.divider()
    # Keep the dock visible in Phase 3A; it can be collapsed by the user.
    with st.expander("Bottom panel", expanded=True):
        tabs = st.tabs(["Indicators", "Strategy Tester", "Trades", "Logs"])
        with tabs[0]:
            st.caption("Active indicators render on the chart and lower panes.")
        with tabs[1]:
            st.info("Strategy Tester coming in next phase.")
        with tabs[2]:
            st.info("Trades panel coming in next phase.")
        with tabs[3]:
            st.info("Logs panel coming in next phase.")
