"""React + Lightweight Charts terminal served as a Streamlit custom component."""
from __future__ import annotations

from pathlib import Path
import re

import streamlit as st
import streamlit.components.v1 as components


FRONTEND_DIST = Path(__file__).with_name("frontend") / "dist"
COMPONENT_NAME = "tradingview_terminal"
DEFAULT_HEIGHT = 760
_ASSET_RE = re.compile(r'(?:src|href)="([^"]+)"')


def build_problems(dist: Path = FRONTEND_DIST) -> list[str]:
    """Return reasons the built frontend cannot be served (empty when healthy).

    Streamlit serves a component under /component/<name>/, so asset URLs in
    index.html must be relative. An absolute "/assets/..." URL silently loads
    Streamlit's own HTML instead of the bundle and the iframe stays blank.
    """
    index = dist / "index.html"
    if not index.exists():
        return [f"{index} is missing. Run `npm install && npm run build` in {dist.parent}."]
    problems = []
    for reference in _ASSET_RE.findall(index.read_text()):
        if reference.startswith(("http:", "https:", "data:")):
            continue
        if reference.startswith("/"):
            problems.append(f"index.html references absolute asset path {reference!r}; set Vite `base: './'` and rebuild.")
        elif not (dist / reference).exists():
            problems.append(f"index.html references missing asset {reference!r}; rebuild the frontend.")
    return problems


_component = None
if not build_problems():
    _component = components.declare_component(COMPONENT_NAME, path=str(FRONTEND_DIST))


def component_available() -> bool:
    return _component is not None


def render_terminal_component(payload: dict, *, key: str, height: int = DEFAULT_HEIGHT):
    """Render the terminal. Never falls back to Plotly: problems are shown as errors."""
    if _component is None:
        problems = build_problems() or ["The component was not registered at import; restart Streamlit after building."]
        st.error("Custom frontend is unavailable:\n\n" + "\n".join(f"- {problem}" for problem in problems))
        return None
    return _component(payload=payload, key=key, default=None, height=height)
