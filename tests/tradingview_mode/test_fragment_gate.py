"""PB-001/PB-003: the terminal reruns alone (st.fragment) and still re-checks the login on every run."""
from pathlib import Path
import re

import pytest

from services.auth import gate
from services.auth.gate import Decision

ROOT = Path(__file__).resolve().parents[2]


def test_terminal_is_rendered_inside_a_fragment_that_rechecks_the_session():
    source = (ROOT / "ui" / "tradingview_mode" / "page.py").read_text()
    body = source[source.index("@st.fragment"):]
    assert re.search(r"@st\.fragment\s+def _terminal_fragment\(\):", body)
    assert body.index("recheck_session()") < body.index("render_custom_terminal()")
    # no timer-driven rerun of the whole app anywhere in TradingView Mode
    for path in (ROOT / "ui" / "tradingview_mode").rglob("*.py"):
        text = path.read_text()
        assert "run_every" not in text and "st_autorefresh" not in text, path
    # the page CSS never lets Streamlit dim the terminal or show its Running/Stop status over it
    assert '[data-stale="true"] {{ opacity: 1 !important' in source
    assert '[data-testid="stStatusWidget"] {{ visibility: hidden' in source


def test_a_revoked_session_reruns_the_whole_app(monkeypatch):
    calls = []

    class FakeRerun(Exception):
        pass

    import streamlit as st

    def fake_rerun(*, scope="app"):
        calls.append(scope)
        raise FakeRerun

    monkeypatch.setattr(st, "rerun", fake_rerun)
    monkeypatch.setattr(gate, "decide", lambda headers, cookies: Decision(False, None, "no valid session"))
    with pytest.raises(FakeRerun):
        gate.recheck_session()
    assert calls == ["app"]                        # the app-level gate then shows the sign-in notice
    calls.clear()
    monkeypatch.setattr(gate, "decide", lambda headers, cookies: Decision(True, "rahul", "session"))
    gate.recheck_session()
    assert calls == []


def test_live_polling_is_the_only_timer_and_is_serialised():
    app = (ROOT / "ui" / "tradingview_mode" / "component" / "frontend" / "src" / "App.jsx").read_text()
    live = (ROOT / "ui" / "tradingview_mode" / "component" / "frontend" / "src" / "liveControls.js").read_text()
    assert 'sendEvent("live_poll")' in app and "isIdle()" in app
    assert "return idle ? \"poll\" : \"wait\";" in live        # never piles up behind a slow run
    events = (ROOT / "ui" / "tradingview_mode" / "component" / "frontend" / "src" / "events.js").read_text()
    assert "!hydrating" in events                               # nothing is sent while data files load
