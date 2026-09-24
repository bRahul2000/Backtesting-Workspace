from datetime import date

import pytest

from ui.tradingview_mode.component.protocol import parse_event
from ui.tradingview_mode.component.state import (
    MAX_BARS,
    TerminalContext,
    TerminalState,
    apply_event,
    default_range_days,
    validate_indicator_params,
)

NATIVE = {"EXNESS_BTCUSDM_M15": "15m", "EXNESS_XAUUSDM_M15": "15m", "EXNESS_BTCUSDM_H1": "1h"}
SECONDS = {"15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}


def ctx(bounds=(date(2024, 1, 1), date(2026, 9, 20))):
    return TerminalContext(
        dataset_exists=lambda key: key in NATIVE,
        native_timeframe=lambda key: NATIVE[key],
        available_timeframes=lambda key: ("15m", "30m", "1h", "4h", "1d") if "BTC" in key else ("15m", "1h"),
        timeframe_seconds=lambda tf: SECONDS[tf],
        data_bounds=bounds,
    )


def state(**overrides):
    return TerminalState(**{"dataset_key": "EXNESS_BTCUSDM_M15", "timeframe": "15m", **overrides})


def apply(current, event_type, **data):
    return apply_event(current, parse_event({"id": "t-1", "type": event_type, "data": data}), ctx())


# ---- timeframe / dataset identity ----------------------------------------------

def test_select_timeframe_accepts_only_python_resolved_timeframes():
    new, log = apply(state(), "select_timeframe", timeframe="4h")
    assert new.timeframe == "4h" and log.level == "info"


def test_unavailable_timeframe_is_rejected_without_substitution():
    gold = state(dataset_key="EXNESS_XAUUSDM_M15")
    new, log = apply(gold, "select_timeframe", timeframe="4h")
    assert new == gold
    assert log.level == "error" and "not available" in log.message


def test_select_dataset_selects_its_native_timeframe_and_resets_range():
    current = state(timeframe="4h", date_range=(date(2025, 1, 1), date(2025, 2, 1)))
    new, log = apply(current, "select_dataset", dataset_key="EXNESS_BTCUSDM_H1")
    assert (new.dataset_key, new.timeframe, new.date_range) == ("EXNESS_BTCUSDM_H1", "1h", None)
    assert "native 1h" in log.message


@pytest.mark.parametrize("event_type", ["select_dataset", "select_watchlist_item"])
def test_unknown_dataset_is_rejected(event_type):
    current = state()
    new, log = apply(current, event_type, dataset_key="BINANCE_BTCUSDT")
    assert new == current and log.level == "error"


# ---- date range ----------------------------------------------------------------

def test_date_range_validation():
    current = state()
    assert apply(current, "set_date_range", start="2026-01-01", end="2026-01-31")[0].date_range == (date(2026, 1, 1), date(2026, 1, 31))
    assert apply(current, "set_date_range", start="2026-02-01", end="2026-01-01")[0] == current
    assert apply(current, "set_date_range", start="2020-01-01", end="2020-02-01")[0] == current
    assert apply(current, "set_date_range", start="2026-01-01", end=None)[0] == current
    reset, _ = apply(state(date_range=(date(2026, 1, 1), date(2026, 1, 2))), "set_date_range", start=None, end=None)
    assert reset.date_range is None


def test_date_range_rejects_more_than_max_bars():
    new, log = apply(state(), "set_date_range", start="2024-01-01", end="2026-09-20")
    assert new.date_range is None and log.level == "error" and f"{MAX_BARS:,}" in log.message
    wide_ok, _ = apply(state(timeframe="1d"), "set_date_range", start="2024-01-01", end="2026-09-20")
    assert wide_ok.date_range is not None


def test_default_range_scales_with_timeframe():
    assert default_range_days(900) == 30
    assert default_range_days(14400) == 334
    assert default_range_days(86400) == 2000


# ---- indicators ----------------------------------------------------------------

def test_add_update_toggle_remove_indicator_lifecycle():
    current, _ = apply(state(), "add_indicator", key="ema")
    current, _ = apply(current, "add_indicator", key="ema", params={"length": 50})
    assert [(i.id, i.params) for i in current.indicators] == [("ema-1", {"length": 20}), ("ema-2", {"length": 50})]
    assert current.indicators[0].color != current.indicators[1].color
    current, _ = apply(current, "update_indicator", id="ema-1", params={"length": 9})
    assert current.indicators[0].params == {"length": 9}
    current, _ = apply(current, "toggle_indicator", id="ema-2", enabled=False)
    assert current.indicators[1].enabled is False
    current, _ = apply(current, "remove_indicator", id="ema-1")
    assert [i.id for i in current.indicators] == ["ema-2"]
    current, _ = apply(current, "add_indicator", key="rsi")
    assert current.indicators[-1].id == "rsi-3"  # ids are never reused


@pytest.mark.parametrize("key, params, message", [
    ("volume", None, "unknown indicator"),
    ("pine", None, "unknown indicator"),
    ("ema", {"length": 0}, "between"),
    ("ema", {"length": 14.5}, "whole number"),
    ("ema", {"period": 14}, "unknown parameter"),
    ("macd", {"fast": 30, "slow": 26}, "fast length"),
    ("bb", {"stddev": 50.0}, "between"),
])
def test_invalid_indicator_requests_are_rejected(key, params, message):
    data = {"key": key} if params is None else {"key": key, "params": params}
    current = state()
    new, log = apply(current, "add_indicator", **data)
    assert new == current
    assert log.level == "error" and message in log.message


@pytest.mark.parametrize("event_type, data", [
    ("update_indicator", {"id": "ema-9", "params": {"length": 3}}),
    ("toggle_indicator", {"id": "ema-9", "enabled": True}),
    ("remove_indicator", {"id": "ema-9"}),
])
def test_indicator_events_for_unknown_ids_are_rejected(event_type, data):
    current = state()
    new, log = apply(current, event_type, **data)
    assert new == current and log.level == "error"


def test_invalid_update_keeps_previous_params():
    current, _ = apply(state(), "add_indicator", key="bb")
    new, log = apply(current, "update_indicator", id="bb-1", params={"length": -1})
    assert new == current and log.level == "error"


def test_param_validation_fills_defaults_and_types():
    assert validate_indicator_params("bb", {"length": 30.0}) == {"length": 30, "stddev": 2.0}
    assert isinstance(validate_indicator_params("bb", {"stddev": 3})["stddev"], float)


# ---- ui ------------------------------------------------------------------------

def test_bottom_panel_and_volume_settings():
    new, log = apply(state(), "set_bottom_panel", panel="trades", open=False)
    assert (new.bottom_panel, new.bottom_open, log.level) == ("trades", False, "debug")
    assert apply(state(), "set_chart_setting", show_volume=False)[0].show_volume is False


def test_frontend_error_is_logged_as_error():
    current = state()
    new, log = apply(current, "frontend_error", message="TypeError: x is undefined")
    assert new == current and log.level == "error" and "TypeError" in log.message
