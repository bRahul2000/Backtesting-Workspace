"""TradingView Mode: the React + Lightweight Charts terminal.

This terminal is the only TradingView Mode interface. The earlier Streamlit/
Plotly workspace (chart.py, workspace.py toolbar/panels) is no longer reachable
from here; if the terminal cannot load, the page says so instead of switching
to another renderer.
"""
import streamlit as st

# Desktop trading terminal: the workspace fills the browser viewport (this page only). Hooks are Streamlit's stable
# data-testid attributes; tests/tradingview_mode/browser/viewport_layout.mjs measures the result at several sizes.
#  - no max-width, 6 px around the terminal (EDGE; the terminal leaves the same gap at the bottom)
#  - the header takes no height: Deploy (a Streamlit Cloud action) is hidden, the main menu floats bottom-left
#  - sidebar: 240 px with compact padding; collapsed it is a 52 px rail holding Streamlit's expand button
#  - the CSS carrier element takes no space
_TERMINAL_CSS = """<style>
:root { --tv-edge: 6px; --tv-rail: 52px; }
[data-testid="stHeader"] { height: 0; min-height: 0; background: transparent; overflow: visible; z-index: 1000050; }
[data-testid="stHeader"] [data-testid="stToolbar"] { height: 0; min-height: 0; }
[data-testid="stAppDeployButton"] { display: none; }
[data-testid="stMainMenu"] { position: fixed; left: 8px; bottom: 8px; z-index: 1000100; }
[data-testid="stMain"] { padding: 0; }
[data-testid="stMainBlockContainer"] { max-width: none; width: 100%;
  padding: var(--tv-edge) var(--tv-edge) 0 var(--tv-edge); }
[data-testid="stMainBlockContainer"] [data-testid="stVerticalBlock"] { gap: 0; }
[data-testid="stElementContainer"]:has(style) { display: none; }
/* an inline iframe adds a baseline gap under it (page overflow -> a scrollbar eating the right edge) */
iframe[title*="tradingview_terminal"] { display: block; }
[data-testid="stSidebar"][aria-expanded="true"] { width: 240px; min-width: 240px; max-width: 240px; }
[data-testid="stSidebarContent"] { padding: 0 6px; }
[data-testid="stSidebarHeader"] { margin-bottom: 4px; height: 40px; padding: 0 2px; }
[data-testid="stSidebarUserContent"] { padding: 8px 0 48px; }
/* collapsed sidebar: a narrow rail with Streamlit's expand button (inside the zero-height header) */
body:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stMain"] { padding-left: var(--tv-rail); }
body:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stAppViewContainer"]::before {
  content: ""; position: fixed; left: 0; top: 0; bottom: 0; width: var(--tv-rail); z-index: 0;
  background: var(--secondary-background-color, #262730); border-right: 1px solid rgba(128, 128, 128, 0.2); }
[data-testid="stExpandSidebarButton"] { position: fixed; left: 12px; top: 8px; z-index: 1000100; }
body:has([data-testid="stSidebar"][aria-expanded="false"]) [data-testid="stMainMenu"] { left: 12px; }
/* chart only (the terminal marks its iframe): no rail, no menu, the chart takes the whole viewport */
body:has(iframe[data-tv-layout="chart"]) [data-testid="stMain"] { padding-left: 0 !important; }
body:has(iframe[data-tv-layout="chart"]) [data-testid="stAppViewContainer"]::before,
body:has(iframe[data-tv-layout="chart"]) [data-testid="stExpandSidebarButton"],
body:has(iframe[data-tv-layout="chart"]) [data-testid="stMainMenu"] { display: none !important; }
</style>"""


def render_tradingview_mode():
    from .component.terminal import render_custom_terminal

    st.markdown(_TERMINAL_CSS, unsafe_allow_html=True)
    try:
        render_custom_terminal()
    except Exception as exc:  # Streamlit's rerun/stop signals are BaseException and pass through
        st.error(f"TradingView Mode failed to load: {type(exc).__name__}: {exc}")
