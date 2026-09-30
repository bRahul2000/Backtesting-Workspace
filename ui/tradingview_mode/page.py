"""TradingView Mode: the React + Lightweight Charts terminal.

This terminal is the only TradingView Mode interface. The earlier Streamlit/
Plotly workspace (chart.py, workspace.py toolbar/panels) is no longer reachable
from here; if the terminal cannot load, the page says so instead of switching
to another renderer.
"""
import streamlit as st

# Desktop trading terminal: the workspace fills the browser viewport (this page only). Streamlit renames its
# data-testid hooks between releases, so every rule names the selector of each supported release (verified by
# tests/tradingview_mode/test_browser_viewport_layout.py against each installed Streamlit, e.g. 1.37.1 and 1.64):
#   main section    1.64 [stMain]                 1.37 section.main
#   block container 1.64 [stMainBlockContainer]   1.37 [stAppViewBlockContainer] (.block-container, max-width 1280px)
#   element wrapper 1.64 [stElementContainer]     1.37 [element-container]
#   Deploy          1.64 [stAppDeployButton]      1.37 [stDeployButton]
#   expand sidebar  1.64 [stExpandSidebarButton]  1.37 [collapsedControl]
# Result: no max-width, 6 px around the terminal (the terminal leaves the same gap at the bottom); the header takes no
# height, Deploy and the top decoration are hidden and the main menu floats bottom-left; a 240 px sidebar with compact
# padding, a 52 px rail when collapsed; the CSS carrier element takes no space.
_MAIN = '[data-testid="stMain"], section.main'
_BLOCK = '[data-testid="stMainBlockContainer"], [data-testid="stAppViewBlockContainer"]'
_EXPAND = '[data-testid="stExpandSidebarButton"], [data-testid="collapsedControl"]'
_COLLAPSED = 'body:has([data-testid="stSidebar"][aria-expanded="false"])'
_CHART_ONLY = 'body:has(iframe[data-tv-layout="chart"])'


def _each(prefix: str, selectors: str) -> str:
    return ", ".join(f"{prefix} {s.strip()}" for s in selectors.split(","))


_TERMINAL_CSS = f"""<style>
:root {{ --tv-edge: 6px; --tv-rail: 52px; }}
[data-testid="stHeader"] {{ height: 0; min-height: 0; background: transparent; overflow: visible; z-index: 1000050; }}
[data-testid="stHeader"] [data-testid="stToolbar"] {{ height: 0; min-height: 0; }}
[data-testid="stAppDeployButton"], [data-testid="stDeployButton"], [data-testid="stDecoration"] {{ display: none !important; }}
[data-testid="stMainMenu"] {{ position: fixed; left: 8px; bottom: 8px; z-index: 1000100; }}
{_MAIN} {{ padding: 0; }}
{_BLOCK} {{ max-width: none !important; width: 100%; padding: var(--tv-edge) var(--tv-edge) 0 var(--tv-edge) !important; }}
{_each('[data-testid="stAppViewBlockContainer"]', '[data-testid="stVerticalBlock"]')},
{_each('[data-testid="stMainBlockContainer"]', '[data-testid="stVerticalBlock"]')} {{ gap: 0; }}
[data-testid="stElementContainer"]:has(style):not(:has(.zf-account)),
[data-testid="element-container"]:has(style):not(:has(.zf-account)) {{ display: none; }}
[data-testid="stElementContainer"]:has(.zf-account), [data-testid="element-container"]:has(.zf-account) {{ height: 0; margin: 0; }}
/* The terminal reruns alone (an st.fragment) and is never dimmed or faded while it runs; Streamlit's own
   "Running... / Stop" status never overlays the terminal (terminal activity shows in its own status bar). */
[data-stale="true"] {{ opacity: 1 !important; transition: none !important; }}
[data-testid="stStatusWidget"] {{ visibility: hidden !important; }}
/* an inline iframe adds a baseline gap under it (page overflow -> a scrollbar eating the right edge) */
iframe[title*="tradingview_terminal"] {{ display: block !important; vertical-align: top; }}
[data-testid="stElementContainer"]:has(> iframe), [data-testid="element-container"]:has(> iframe) {{ line-height: 0; }}
[data-testid="stSidebar"][aria-expanded="true"] {{ width: 240px; min-width: 240px; max-width: 240px; }}
[data-testid="stSidebarContent"] {{ padding: 0 6px; }}
[data-testid="stSidebarHeader"] {{ margin-bottom: 4px; height: 40px; padding: 0 2px; }}
[data-testid="stSidebarUserContent"] {{ padding: 8px 0 48px; }}
/* collapsed sidebar: a narrow rail holding Streamlit's expand button */
{_each(_COLLAPSED, _MAIN)} {{ padding-left: var(--tv-rail); }}
{_COLLAPSED} [data-testid="stAppViewContainer"]::before {{
  content: ""; position: fixed; left: 0; top: 0; bottom: 0; width: var(--tv-rail); z-index: 0;
  background: var(--secondary-background-color, #262730); border-right: 1px solid rgba(128, 128, 128, 0.2); }}
{_EXPAND} {{ position: fixed !important; left: 8px !important; top: 8px !important; z-index: 1000100; }}
{_COLLAPSED} [data-testid="stMainMenu"] {{ left: 10px; }}
/* chart only (the terminal marks its iframe): no rail, no menu, the chart takes the whole viewport */
{_each(_CHART_ONLY, _MAIN)} {{ padding-left: 0 !important; }}
{_CHART_ONLY} [data-testid="stAppViewContainer"]::before, {_each(_CHART_ONLY, _EXPAND)},
{_CHART_ONLY} [data-testid="stMainMenu"] {{ display: none !important; }}
</style>"""


def render_tradingview_mode():
    st.markdown(_TERMINAL_CSS, unsafe_allow_html=True)
    _terminal_fragment()


# The terminal reruns on its own: every terminal event (a click, a live poll, a tab) reruns only this fragment, never
# the whole app - so the sidebar, the account control and this page's CSS are built once and stay put.
@st.fragment
def _terminal_fragment():
    from services.auth.gate import recheck_session
    from .component.terminal import render_custom_terminal

    recheck_session()                 # the app-level login gate does not run for a fragment-only rerun
    try:
        render_custom_terminal()
    except Exception as exc:  # Streamlit's rerun/stop signals are BaseException and pass through
        from services.auth.logs import setup as _logs
        _logs("app").exception("TradingView Mode failed to load")
        st.error(f"TradingView Mode failed to load: {type(exc).__name__}: {exc}")
