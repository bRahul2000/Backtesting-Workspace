"""Small, deterministic checks for frozen MT5 export comparison."""
from __future__ import annotations

import pandas as pd
import pytest

from tools.compare_mt5_setup_a import (compare_exports, frozen_config,
                                       parse_mt5_export)


T = pd.Timestamp("2026-01-05 10:15:00", tz="UTC")


def signals(direction="LONG"):
    return pd.DataFrame([{"signal_time": T, "direction": direction,
                          "trigger": 50000., "structural_stop": 49900.,
                          "planned_target_distance": 300.}])


def trades(direction="LONG", pnl=300.):
    return pd.DataFrame([{"signal_time": T, "direction": direction,
                          "entry_time": T + pd.Timedelta(minutes=15),
                          "entry_price": 50000.,
                          "exit_time": T + pd.Timedelta(hours=1),
                          "exit_price": 50300. if pnl > 0 else 49900.,
                          "gross_pnl": pnl,
                          "exit_reason": "TAKE_PROFIT" if pnl > 0 else "STOP_LOSS"}])


def events(direction="LONG", trigger=50000.):
    base = {"signal_time": T, "direction": direction, "qualified": "true",
            "trigger": trigger, "stop": 49900., "target": 50300.,
            "fill_time": pd.NaT, "fill_price": 0., "exit_time": pd.NaT,
            "exit_price": 0., "pnl": 0.}
    signal = {**base, "event": "SIGNAL_EVALUATED"}
    fill = {**base, "event": "ORDER_FILLED",
            "fill_time": T + pd.Timedelta(minutes=15), "fill_price": 50000.}
    exit_row = {**base, "event": "TAKE_PROFIT",
                "exit_time": T + pd.Timedelta(hours=1),
                "exit_price": 50300., "pnl": 300.}
    return pd.DataFrame([signal, fill, exit_row])


def test_loader_keeps_existing_freeze_verified():
    frozen = frozen_config()
    assert frozen["setup_a_enabled"] is True
    assert frozen["setup_b_enabled"] is False
    assert frozen["freeze_hash_sha256"] == "b9c1f07ed3ec4b068f65d0ede59e6a94dc6985c4ad8824ae606c168c7f33b649"


def test_parity_export_parsing_utc_and_numeric(tmp_path):
    path = tmp_path / "mt5.csv"
    events().assign(signal_time="2026-01-05 10:15:00",
                    fill_time=["", "2026-01-05 10:30:00", ""],
                    exit_time=["", "", "2026-01-05 11:15:00"]).to_csv(path, index=False)
    parsed = parse_mt5_export(path)
    assert parsed.signal_time.iloc[0] == T
    assert parsed.fill_time.iloc[1] == T + pd.Timedelta(minutes=15)
    assert parsed.trigger.dtype.kind == "f"


def test_parser_rejects_missing_fields(tmp_path):
    path = tmp_path / "broken.csv"
    path.write_text("event,signal_time\nSIGNAL_EVALUATED,2026-01-05 10:15:00\n")
    with pytest.raises(ValueError, match="lacks columns"):
        parse_mt5_export(path)


def test_exact_signal_and_trade_match():
    result = compare_exports(signals(), trades(), events())
    assert result["exact_signal_matches"] == 1
    assert result["issues"] == []


def test_missing_and_extra_signal_classification():
    empty = events().iloc[0:0]
    missing = compare_exports(signals(), trades(), empty)
    assert missing["issue_counts"]["missing_mt5_signal"] == 1
    extra = compare_exports(signals().iloc[0:0], trades().iloc[0:0], events())
    assert extra["issue_counts"]["extra_mt5_signal"] == 1


def test_direction_mismatch_is_distinct_from_extra_signal():
    result = compare_exports(signals(), trades(), events(direction="SHORT"))
    assert result["issue_counts"]["direction_mismatch"] == 1
    assert "extra_mt5_signal" not in result["issue_counts"]


def test_price_tolerance_one_point_maximum():
    assert not compare_exports(signals(), trades(), events(trigger=50000.005))["issues"]
    result = compare_exports(signals(), trades(), events(trigger=50000.02))
    assert result["issue_counts"]["trigger_difference"] == 1
    with pytest.raises(ValueError, match="one BTCUSDm point"):
        compare_exports(signals(), trades(), events(), .02)


def test_missing_and_extra_fill_classification():
    no_fill = events().loc[lambda x: x.event.ne("ORDER_FILLED")]
    assert compare_exports(signals(), trades(), no_fill)["issue_counts"]["missing_mt5_fill"] == 1
    assert compare_exports(signals(), trades().iloc[0:0], events())["issue_counts"]["extra_mt5_fill"] == 1


def test_outcome_mismatch_classification():
    mt = events()
    mt.loc[mt.event.eq("TAKE_PROFIT"), "event"] = "STOP_LOSS"
    mt.loc[mt.event.eq("STOP_LOSS"), "pnl"] = -100.
    assert compare_exports(signals(), trades(), mt)["issue_counts"]["outcome_mismatch"] == 1


def test_specific_exit_event_takes_precedence_over_lifecycle_duplicate():
    mt = events()
    lifecycle = mt.iloc[-1].copy()
    lifecycle["event"] = "POSITION_CLOSED"
    mt = pd.concat([mt, pd.DataFrame([lifecycle])], ignore_index=True)
    assert compare_exports(signals(), trades(), mt)["issues"] == []


def test_duplicate_mt5_signals_and_fills_are_visible():
    mt = events()
    mt = pd.concat([mt, mt.iloc[:2]], ignore_index=True)
    counts = compare_exports(signals(), trades(), mt)["issue_counts"]
    assert counts["duplicate_mt5_signal"] == 1
    assert counts["duplicate_mt5_fill"] == 1
