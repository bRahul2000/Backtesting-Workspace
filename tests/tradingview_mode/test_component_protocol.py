import json

import numpy as np
import pandas as pd
import pytest

from ui.tradingview_mode.component.protocol import (
    EVENT_SCHEMAS,
    EventValidationError,
    bars_from_frame,
    epoch_seconds,
    parse_event,
    price_precision,
    series_points,
)


def bars(periods=3):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=periods, freq="15min", tz="UTC"),
        "open": [10.0, 11.0, 12.0][:periods], "high": [12.0, 13.0, 14.0][:periods],
        "low": [9.0, 10.0, 11.0][:periods], "close": [11.0, 12.0, 13.0][:periods],
        "volume": [100, 110, 120][:periods],
    })


# ---- UTC conversion ------------------------------------------------------------

def test_epoch_seconds_are_utc_integers():
    times = epoch_seconds(bars()["timestamp"])
    assert times.dtype == np.int64
    assert times.tolist() == [1767225600, 1767226500, 1767227400]


def test_naive_and_non_utc_timestamps_are_rejected_not_reinterpreted():
    naive = bars()["timestamp"].dt.tz_localize(None)
    with pytest.raises(ValueError, match="UTC"):
        epoch_seconds(naive)
    london = bars()["timestamp"].dt.tz_convert("Europe/London")
    with pytest.raises(ValueError, match="UTC"):
        epoch_seconds(london)


# ---- bars ----------------------------------------------------------------------

def test_bars_serialize_exact_values_as_json_floats():
    records = bars_from_frame(bars())
    assert records[0] == {"time": 1767225600, "open": 10.0, "high": 12.0, "low": 9.0, "close": 11.0, "volume": 100.0}
    assert all(type(record["time"]) is int for record in records)
    assert all(type(record["volume"]) is float for record in records)
    json.dumps(records, allow_nan=False)


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.assign(open=[10.0, float("nan"), 12.0]), "finite"),
    (lambda d: d.assign(high=[12.0, float("inf"), 14.0]), "finite"),
    (lambda d: d.iloc[[0, 0, 1]], "duplicates"),
    (lambda d: d.iloc[[1, 0, 2]], "chronological"),
    (lambda d: d.drop(columns=["volume"]), "Missing"),
])
def test_bars_reject_invalid_frames(mutate, message):
    with pytest.raises(ValueError, match=message):
        bars_from_frame(mutate(bars()))


def test_bars_do_not_mutate_source():
    data = bars()
    before = data.copy(deep=True)
    bars_from_frame(data)
    pd.testing.assert_frame_equal(data, before)


def test_series_points_drop_warmup_and_reject_infinite():
    times = [1, 2, 3]
    assert series_points(times, pd.Series([np.nan, 1.5, 2.5])) == [{"time": 2, "value": 1.5}, {"time": 3, "value": 2.5}]
    with pytest.raises(ValueError, match="finite"):
        series_points(times, pd.Series([1.0, np.inf, 2.0]))
    with pytest.raises(ValueError, match="length"):
        series_points(times, pd.Series([1.0]))


def test_price_precision_is_display_only_and_bounded():
    assert price_precision([76540.72, 76558.01]) == 2
    assert price_precision([4380.893, 4380.1]) == 3
    assert price_precision([100.0, 101.0]) == 2


# ---- events --------------------------------------------------------------------

VALID_EVENTS = {
    "chart_ready": {},
    "frontend_error": {"message": "boom"},
    "select_dataset": {"dataset_key": "EXNESS_BTCUSDM_M15"},
    "select_watchlist_item": {"dataset_key": "EXNESS_XAUUSDM_M15"},
    "select_timeframe": {"timeframe": "4h"},
    "set_date_range": {"start": "2026-01-01", "end": "2026-01-31"},
    "add_indicator": {"key": "ema", "params": {"length": 21}},
    "update_indicator": {"id": "ema-1", "params": {"length": 30}},
    "toggle_indicator": {"id": "ema-1", "enabled": False},
    "remove_indicator": {"id": "ema-1"},
    "set_bottom_panel": {"panel": "logs", "open": True},
    "set_chart_setting": {"show_volume": False},
    "run_backtest": {"strategy_id": "BTC_V3_CORE_V1_FROZEN", "dataset_key": "EXNESS_BTCUSDM_M15",
                     "broker_profile": "EXNESS_STANDARD", "dataset_role": "DEVELOPMENT",
                     "start": "2026-06-01", "end": "2026-06-30", "ledger_mode": "scratch",
                     "parameters": {"reward_multiple": 3.0},
                     "settings": {"risk_mode": "PERCENT_EQUITY", "risk_per_trade_percent": 0.5}},
    "clear_backtest": {},
    "restore_run": {"history_id": 1},
    "enter_replay": {"start": "2026-06-10T14:30"},
    "set_replay_start": {"start": "2026-06-10T14:30Z"},
    "jump_replay": {"to": "2026-07-01T09:00"},
    "step_forward": {}, "step_backward": {}, "play_replay": {}, "pause_replay": {},
    "set_replay_speed": {"speed": 5}, "exit_replay": {}, "go_to_replay_latest": {},
    "enter_live": {}, "go_live": {"market": "BTC", "source": "binance", "timeframe": "15m"}, "exit_live": {}, "live_poll": {}, "load_live_history": {},
    "export_run": {"history_id": 1, "kind": "trades_csv"},
}


def test_every_event_type_has_a_valid_example():
    assert set(VALID_EVENTS) == set(EVENT_SCHEMAS)


@pytest.mark.parametrize("event_type", sorted(VALID_EVENTS))
def test_valid_events_parse(event_type):
    event = parse_event({"id": "abc-1", "type": event_type, "data": VALID_EVENTS[event_type]})
    assert event.type == event_type
    assert event.id == "abc-1"


@pytest.mark.parametrize("raw, message", [
    ("select_timeframe", "object"),
    ({"type": "chart_ready", "data": {}}, "id"),
    ({"id": "x", "type": "place_order", "data": {}}, "Unknown event"),
    ({"id": "x", "type": "chart_ready", "data": {}, "extra": 1}, "Unexpected event field"),
    ({"id": "x", "type": "select_timeframe", "data": {}}, "missing field"),
    ({"id": "x", "type": "select_timeframe", "data": {"timeframe": 15}}, "invalid timeframe"),
    ({"id": "x", "type": "select_timeframe", "data": {"timeframe": "1h", "fallback": "15m"}}, "unexpected field"),
    ({"id": "x", "type": "set_date_range", "data": {"start": "2026/01/01", "end": "2026-01-02"}}, "invalid start"),
    ({"id": "x", "type": "add_indicator", "data": {"key": "ema", "params": {"length": True}}}, "invalid params"),
    ({"id": "x", "type": "set_bottom_panel", "data": {"panel": "orders"}}, "invalid panel"),
    ({"id": "x", "type": "toggle_indicator", "data": {"id": "ema-1", "enabled": "yes"}}, "invalid enabled"),
    ({"id": "x", "type": "export_run", "data": {"history_id": 1, "kind": "trades_xlsx"}}, "invalid kind"),
    ({"id": "x", "type": "restore_run", "data": {"history_id": "1"}}, "invalid history_id"),
])
def test_invalid_events_are_rejected(raw, message):
    with pytest.raises(EventValidationError, match=message):
        parse_event(raw)
