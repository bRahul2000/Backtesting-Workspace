"""TradingView Mode renders exactly one workspace: React terminal or legacy Plotly."""
import pytest
from streamlit.testing.v1 import AppTest

import ui.tradingview_mode.page as page

FLAG = page.CUSTOM_FRONTEND_FLAG
CALLS: list[str] = []


def _script():
    from ui.tradingview_mode.page import render_tradingview_mode

    render_tradingview_mode()


@pytest.fixture
def recorded(monkeypatch):
    """Replace both workspace bodies with recorders (restored after the test)."""
    import streamlit as st

    CALLS.clear()

    def custom():
        CALLS.append("custom")
        st.caption("custom terminal")

    def legacy():
        CALLS.append("legacy")
        st.caption("legacy workspace")

    monkeypatch.setattr(page, "render_custom_workspace", custom)
    monkeypatch.setattr(page, "render_legacy_workspace", legacy)
    return CALLS


def run(enabled: bool) -> AppTest:
    app = AppTest.from_function(_script, default_timeout=60)
    app.session_state[FLAG] = enabled
    app.run()
    assert not app.exception
    return app


def test_custom_on_never_executes_the_legacy_workspace(recorded):
    app = run(True)
    assert recorded == ["custom"]
    assert [c.value for c in app.caption] == ["custom terminal"]


def test_custom_off_renders_only_the_legacy_workspace(recorded):
    app = run(False)
    assert recorded == ["legacy"]
    assert [c.value for c in app.caption] == ["legacy workspace"]


@pytest.mark.parametrize("enabled", [True, False])
def test_inactive_workspace_slot_is_emptied_at_run_start(recorded, enabled):
    # Toggle, custom slot, legacy slot. The inactive slot is an empty element,
    # which is what removes the other mode's previous elements immediately
    # instead of at the end of the run.
    app = run(enabled)
    toggle, custom_slot, legacy_slot = (app.main.children[i] for i in range(3))
    assert len(app.main.children) == 3 and toggle.type == "toggle"
    active, inactive = (custom_slot, legacy_slot) if enabled else (legacy_slot, custom_slot)
    assert inactive.type == "empty"
    assert active.type != "empty" and len(active.children) == 1


def test_custom_failure_shows_error_and_does_not_fall_back(monkeypatch):
    import ui.tradingview_mode.component.terminal as terminal

    def broken():
        raise RuntimeError("component exploded")

    legacy_calls = []
    monkeypatch.setattr(terminal, "render_custom_terminal", broken)
    monkeypatch.setattr(page, "render_legacy_workspace", lambda: legacy_calls.append(1))
    app = run(True)
    assert any("component exploded" in error.value for error in app.error)
    assert not legacy_calls
    assert not app.get("plotly_chart")


def test_real_custom_mode_renders_no_legacy_controls():
    app = run(True)
    assert not app.get("plotly_chart")
    assert not app.get("popover") and not app.get("expander") and not app.get("date_input")
    assert not [m for m in app.markdown if "### TradingView Mode" in m.value]
