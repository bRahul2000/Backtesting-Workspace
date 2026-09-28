"""TradingView Mode: the React + Lightweight Charts terminal.

This terminal is the only TradingView Mode interface. The earlier Streamlit/
Plotly workspace (chart.py, workspace.py toolbar/panels) is no longer reachable
from here; if the terminal cannot load, the page says so instead of switching
to another renderer.
"""
import streamlit as st

_TERMINAL_CSS = """<style>
[data-testid="stMainBlockContainer"] { padding-top: 3.4rem; padding-bottom: 0; padding-left: 1rem; padding-right: 1rem; max-width: 100%; }
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0.25rem; }
</style>"""


def render_tradingview_mode():
    from .component.terminal import render_custom_terminal

    st.markdown(_TERMINAL_CSS, unsafe_allow_html=True)
    try:
        render_custom_terminal()
    except Exception as exc:  # Streamlit's rerun/stop signals are BaseException and pass through
        st.error(f"TradingView Mode failed to load: {type(exc).__name__}: {exc}")
