from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from engine.diagnostics import (
    BAR_BASED_APPROXIMATION, DiagnosticEvent, compare_trades,
    detect_execution_ambiguities, enrich_trade, funnel_summary,
    serialize_diagnostics,
)
from engine.models import Direction, OrderEvent, Trade
from experiments.ledger import ExperimentLedger
from ui.universal_workspace import trades_dataframe
from core.result import UniversalBacktestResult


def candles(rows):
    return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])


def trade(direction, entry=100.0, stop=95.0, target=110.0, exit_price=102.0):
    return Trade(
        trade_id=1, direction=direction,
        signal_time=pd.Timestamp("2026-01-01 00:00", tz="UTC"),
        entry_time=pd.Timestamp("2026-01-01 00:15", tz="UTC"),
        entry_price=entry, stop_loss=stop, take_profit=target,
        exit_time=pd.Timestamp("2026-01-01 00:45", tz="UTC"), exit_price=exit_price,
        exit_reason="Take profit", quantity=1.0, initial_risk=5.0,
        pnl=exit_price - entry if direction is Direction.LONG else entry - exit_price,
        pnl_percent=2.0, r_multiple=0.4, bars_held=3,
        entry_commission=0.0, exit_commission=0.0, setup_id="TEST",
    )


def test_long_mfe_mae_and_efficiency_are_hand_calculated():
    result = enrich_trade(trade(Direction.LONG), candles([
        ["2026-01-01 00:00+00:00", 100, 101, 99, 100, 1],
        ["2026-01-01 00:15+00:00", 100, 103, 98, 101, 1],
        ["2026-01-01 00:30+00:00", 101, 102, 99, 102, 1],
        ["2026-01-01 00:45+00:00", 102, 102, 100, 102, 1],
    ]))
    assert result.mfe_price == 103
    assert result.mfe_amount == 3
    assert result.mfe_r == pytest.approx(.6)
    assert result.mae_price == 98
    assert result.mae_amount == 2
    assert result.mae_r == pytest.approx(.4)
    assert result.capture_efficiency == pytest.approx(2 / 3)
    assert result.adverse_efficiency == 0
    assert result.excursion_model == BAR_BASED_APPROXIMATION
    assert result.highest_price_while_open == 103
    assert result.lowest_price_while_open == 98


def test_short_mfe_mae_uses_short_favorable_and_adverse_sides():
    original = trade(Direction.SHORT, stop=105, target=90, exit_price=98)
    result = enrich_trade(original, candles([
        ["2026-01-01 00:15+00:00", 100, 102, 96, 99, 1],
        ["2026-01-01 00:30+00:00", 99, 101, 97, 98, 1],
        ["2026-01-01 00:45+00:00", 98, 100, 98, 98, 1],
    ]))
    assert result.mfe_amount == 4
    assert result.mfe_r == pytest.approx(.8)
    assert result.mae_amount == 2
    assert result.mae_r == pytest.approx(.4)
    assert result.capture_efficiency == pytest.approx(.5)


def test_zero_risk_and_zero_mfe_are_safe():
    zero_risk = trade(Direction.LONG)
    zero_risk = zero_risk.__class__(**{**zero_risk.__dict__, "initial_risk": 0.0})
    result = enrich_trade(zero_risk, candles([
        ["2026-01-01 00:15+00:00", 100, 100, 100, 100, 1],
        ["2026-01-01 00:30+00:00", 100, 100, 100, 100, 1],
        ["2026-01-01 00:45+00:00", 100, 100, 100, 100, 1],
    ]))
    assert result.mfe_r is None
    assert result.mae_r is None
    assert result.capture_efficiency is None
    assert result.adverse_efficiency is None


def test_ambiguity_detector_records_same_bar_policy():
    frame = candles([["2026-01-01 00:45+00:00", 100, 106, 94, 100, 1]])
    ambiguous = detect_execution_ambiguities(frame, [trade(Direction.LONG, target=105)], [])
    assert len(ambiguous) == 1
    assert ambiguous[0].ambiguity_type == "SL_AND_TP_SAME_CANDLE"
    assert ambiguous[0].resolution_policy == "SL_FIRST"


def test_trade_difference_matches_by_time_direction_and_component():
    left = trade(Direction.LONG)
    right = trade(Direction.LONG, entry=101, exit_price=103)
    right = right.__class__(**{**right.__dict__, "entry_time": left.entry_time + pd.Timedelta(seconds=1)})
    rows = compare_trades([left], [right], timestamp_tolerance=timedelta(seconds=1))
    assert rows[0]["status"] == "CHANGED"
    assert "CHANGED_ENTRY" in rows[0]["changes"]
    assert compare_trades([left], [], timestamp_tolerance=timedelta(0))[0]["status"] == "ONLY_IN_A"


def test_signal_funnel_and_serialization_are_structured():
    events = [
        DiagnosticEvent("bars_evaluated", True, None, pd.Timestamp("2026-01-01", tz="UTC")),
        DiagnosticEvent("setup_detected", True, None, pd.Timestamp("2026-01-01", tz="UTC")),
        DiagnosticEvent("order_cancelled", False, "expired", pd.Timestamp("2026-01-01", tz="UTC")),
    ]
    summary = funnel_summary(events)
    assert summary[0]["stage"] == "bars_evaluated"
    assert summary[-1]["failed"] == 1
    assert serialize_diagnostics(events)[-1]["reason"] == "expired"


def test_optional_diagnostics_columns_are_exposed_in_ui_model():
    result = UniversalBacktestResult(
        run_id="BT-1", strategy_fingerprint="s", parameter_fingerprint="p",
        dataset_fingerprint="d", broker_fingerprint="b", instrument="BTCUSD",
        period={}, dataset_role="DEVELOPMENT", total_trades=1, trades_per_month=1,
        win_rate=100, profit_factor=None, average_r=.4, pnl=2, max_drawdown_percent=0,
        trade_log=[{**trade(Direction.LONG).__dict__, "mfe_amount": 3, "mae_amount": 2,
                    "mfe_r": .6, "mae_r": .4, "capture_efficiency": .67}],
    )
    table = trades_dataframe(result, "BTCUSD")
    assert {"MFE", "MAE", "R", "Duration"}.issubset(table.columns)


def test_forward_exposure_warning_after_repeat(tmp_path):
    ledger = ExperimentLedger(tmp_path / "ledger.sqlite3")
    common = dict(
        strategy_id="S1", strategy_name="Strategy", strategy_status="RESEARCH",
        strategy_fingerprint="sf", parameter_fingerprint="pf", dataset_fingerprint="df",
        broker_fingerprint="bf", instrument_fingerprint="if", broker_profile="EXNESS_STANDARD",
        instrument="BTCUSD", date_start="2026-01-01", date_end="2026-02-01",
        dataset_role="FORWARD_VALIDATION", config={"strategy_parameters": {}},
        strategy_version="1.0",
    )
    ledger.start_run(**common)
    assert ledger.exposure_warning("S1", "pf", "FORWARD_VALIDATION") is None
    ledger.start_run(**common)
    assert ledger.exposure_warning("S1", "pf", "FORWARD_VALIDATION") == "FORWARD DATA HAS BEEN EXPOSED TO THIS CONFIGURATION"
