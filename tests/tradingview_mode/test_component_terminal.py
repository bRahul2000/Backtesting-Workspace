import copy
from datetime import date
import json

import numpy as np
import pandas as pd
import pytest

from services.market_datasets import dataset
from ui.tradingview_mode.component import build_problems
from ui.tradingview_mode.component.protocol import PayloadValidationError, validate_payload
from ui.tradingview_mode.component.state import IndicatorInstance, LogEntry, TerminalState
from ui.tradingview_mode.component.terminal import (
    build_terminal_payload,
    consume_event,
    context_for,
    effective_range,
    filter_range,
)
from ui.tradingview_mode.timeframes import resolve_timeframe


def frame(periods=60, freq="4h"):
    times = pd.date_range("2026-01-01", periods=periods, freq=freq, tz="UTC")
    close = 100.0 + np.arange(periods, dtype=float)
    return pd.DataFrame({"timestamp": times, "open": close - 0.5, "high": close + 1.0,
                         "low": close - 1.0, "close": close, "volume": np.full(periods, 10.0)})


def payload_for(key="EXNESS_BTCUSDM_M15", timeframe="4h", data=None, indicators=()):
    selected = dataset(key)
    resolution = resolve_timeframe(selected, timeframe)
    data = frame() if data is None else data
    state = TerminalState(dataset_key=key, timeframe=timeframe, indicators=tuple(indicators))
    bounds = (data["timestamp"].iloc[0].date(), data["timestamp"].iloc[-1].date())
    return build_terminal_payload(state=state, selected=selected, resolution=resolution, frame=data,
                                  bounds=bounds, shown=bounds, logs=[LogEntry("info", "x")], notices=[],
                                  watchlist=[], ack="abc-3")


# ---- payload identity ----------------------------------------------------------

def test_payload_preserves_provider_symbol_and_timeframe_identity():
    payload = payload_for()
    ds = dataset("EXNESS_BTCUSDM_M15")
    assert (payload["provider"], payload["symbol"], payload["dataset_key"]) == (ds.broker, ds.symbol, ds.key)
    assert payload["timeframe"] == "4h"
    assert payload["source"]["provider"] == ds.broker  # derived data never crosses providers
    assert payload["source"]["native"] is False
    assert payload["source"]["description"].startswith("Derived from")
    assert payload["ack"] == "abc-3"
    assert payload["mode"] == "historical"


def test_native_timeframe_payload_reports_native_source():
    payload = payload_for(timeframe="1h", data=frame(freq="1h"))
    assert payload["source"] == {**payload["source"], "native": True, "description": "Native",
                                 "dataset_key": "EXNESS_BTCUSDM_H1", "timeframe": "1h"}


def test_payload_is_strict_json_and_uses_epoch_seconds():
    payload = payload_for()
    text = json.dumps(payload, allow_nan=False)
    assert json.loads(text)["bars"][0]["time"] == int(pd.Timestamp("2026-01-01", tz="UTC").timestamp())


def test_indicators_are_calculated_in_python_and_routed_to_panes():
    indicators = (
        IndicatorInstance("ema-1", "ema", {"length": 5}, True, "#f5a623"),
        IndicatorInstance("rsi-2", "rsi", {"length": 14}, True, "#4aa3ff"),
        IndicatorInstance("macd-3", "macd", {"fast": 12, "slow": 26, "signal": 9}, False, "#c678dd"),
    )
    payload = payload_for(indicators=indicators)
    assert [o["id"] for o in payload["overlays"]] == ["ema-1"]
    assert [p["id"] for p in payload["panes"]] == ["rsi-2"]  # disabled MACD is not drawn
    assert payload["panes"][0]["levels"] == [70.0, 50.0, 30.0]
    assert [i["id"] for i in payload["indicators"]] == ["ema-1", "rsi-2", "macd-3"]
    ema = payload["overlays"][0]["series"][0]["data"]
    assert len(ema) == 60 - 4  # warm-up bars omitted, not zero-filled
    assert "volume" not in {item["key"] for item in payload["indicator_catalog"]}


def test_payload_building_does_not_mutate_source_frame():
    data = frame()
    before = data.copy(deep=True)
    payload_for(data=data, indicators=(IndicatorInstance("bb-1", "bb", {"length": 20, "stddev": 2.0}, True, "#fff"),))
    pd.testing.assert_frame_equal(data, before)


@pytest.mark.parametrize("tamper, message", [
    (lambda p: p["source"].update(provider="Bitstamp (public exchange API)"), "provider"),
    (lambda p: p.update(timeframe="3h"), "timeframe"),
    (lambda p: p["bars"][0].update(time=float(p["bars"][0]["time"])), "integer epoch"),
    (lambda p: p["bars"].reverse(), "increasing"),
    (lambda p: p["bars"][1].update(close=float("nan")), "finite"),
    (lambda p: p["overlays"].append({"id": "x", "series": [{"type": "line", "name": "v", "color": "#fff", "data": [{"time": 1, "value": 1.0}]}]}), "not a bar time"),
    (lambda p: p["ui"].update(bottom_panel="orders"), "bottom_panel"),
    (lambda p: p.update(contract=2), "contract"),
])
def test_validate_payload_rejects_contract_violations(tamper, message):
    payload = copy.deepcopy(payload_for())
    tamper(payload)
    with pytest.raises(PayloadValidationError, match=message):
        validate_payload(payload)


# ---- event handling ------------------------------------------------------------

def test_consume_event_applies_each_event_id_exactly_once():
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    raw = {"id": "n-1", "type": "add_indicator", "data": {"key": "ema"}}
    state, entry, last, _ = consume_event(state, raw, context_for(), None)
    assert len(state.indicators) == 1 and entry.level == "info" and last == "n-1"
    # Streamlit re-delivers the same component value on unrelated reruns.
    again, entry, last, _ = consume_event(state, raw, context_for(), last)
    assert again == state and entry is None and last == "n-1"


def test_consume_event_logs_malformed_events_and_acknowledges_them():
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    new, entry, last, _ = consume_event(state, {"id": "n-2", "type": "place_order", "data": {}}, context_for(), None)
    assert new == state and entry.level == "error" and last == "n-2"


def test_real_registry_timeframe_rejection_keeps_provider():
    state = TerminalState(dataset_key="EXNESS_XAUUSDM_M15", timeframe="15m")
    raw = {"id": "n-3", "type": "select_timeframe", "data": {"timeframe": "1m"}}
    new, entry, _, _ = consume_event(state, raw, context_for(), None)
    assert new == state and entry.level == "error"


# ---- ranges --------------------------------------------------------------------

def test_effective_range_default_and_clipping_are_reported():
    bounds = (date(2026, 1, 1), date(2026, 3, 31))
    state = TerminalState(dataset_key="k", timeframe="15m")
    assert effective_range(state, bounds, 900) == (date(2026, 3, 2), date(2026, 3, 31), [])
    clipped = TerminalState(dataset_key="k", timeframe="15m", date_range=(date(2025, 12, 1), date(2026, 1, 10)))
    start, end, notices = effective_range(clipped, bounds, 900)
    assert (start, end) == (date(2026, 1, 1), date(2026, 1, 10)) and "clipped" in notices[0]["message"]


def test_filter_range_is_inclusive_utc_and_non_mutating():
    data = frame(periods=24, freq="1h")
    before = data.copy(deep=True)
    result = filter_range(data, date(2026, 1, 1), date(2026, 1, 1))
    assert len(result) == 24 and str(result["timestamp"].dt.tz) == "UTC"
    pd.testing.assert_frame_equal(data, before)


# ---- build integrity -----------------------------------------------------------

def test_build_problems_detects_absolute_asset_paths(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("")
    (tmp_path / "index.html").write_text('<script type="module" src="/assets/app.js"></script>')
    assert any("absolute" in problem for problem in build_problems(tmp_path))
    (tmp_path / "index.html").write_text('<script type="module" src="./assets/app.js"></script>')
    assert build_problems(tmp_path) == []
    (tmp_path / "index.html").write_text('<script type="module" src="./assets/missing.js"></script>')
    assert any("missing" in problem for problem in build_problems(tmp_path))
    assert "missing" in build_problems(tmp_path / "nope")[0]


def test_shipped_build_is_servable():
    assert build_problems() == []


# ---- renderer flag -------------------------------------------------------------

def _page_script():
    import ui.tradingview_mode.component as component
    from ui.tradingview_mode.page import render_tradingview_mode

    component._component = None  # simulate an unbuilt / unservable frontend
    render_tradingview_mode()


def test_flag_on_with_unavailable_frontend_shows_error_not_plotly(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import ui.tradingview_mode.component as component

    monkeypatch.setattr(component, "_component", component._component)  # restored after the test
    app = AppTest.from_function(_page_script, default_timeout=60)
    app.session_state["tv_custom_chart_prototype_enabled"] = True
    app.run()
    assert not app.exception
    assert any("Custom frontend is unavailable" in error.value for error in app.error)
    assert not app.get("plotly_chart")
