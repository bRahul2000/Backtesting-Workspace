"""Deterministic frozen-trade cost accounting tests, not broker observations."""
import pandas as pd
import pytest

from brokers.exness_standard_btcusdm import PROFILE
from research.exness_cost_recalibration import (
    build_reports, floor_exness_lots, load_frozen_trades, lot_rounding_analysis,
    metrics, reprice, research_set, spread_round_trip_cost,
)


def _frozen_rows():
    rows = []
    for trade_id, signal, direction, entry, exit_price, quantity in (
        (1, "2024-12-31T23:45:00Z", "LONG", 100., 120., .105),
        (2, "2025-01-01T00:00:00Z", "SHORT", 100., 110., .009),
    ):
        gross = (1 if direction == "LONG" else -1) * (exit_price - entry) * quantity
        fee = (entry + exit_price) * quantity * .0005
        rows.append({"segment_id": "S01", "trade_id": trade_id,
                     "setup_id": "BTC_V2_SETUP_B", "signal_time": signal,
                     "entry_time": signal, "exit_time": signal,
                     "direction": direction, "actual_fill_price": entry,
                     "pending_trigger_price": entry,
                     "exit_price": exit_price, "structural_stop": 90. if direction == "LONG" else 120.,
                     "target": 130. if direction == "LONG" else 70.,
                     "exit_reason": "fixture exit",
                     "quantity_recovered": quantity, "planned_risk_dollars": 2.5,
                     "gross_price_movement_pnl": gross, "commission_cost": fee,
                     "slippage_cost": 0., "net_pnl": gross - fee,
                     "realized_r": (gross - fee) / 2.5})
    return pd.DataFrame(rows)


def test_full_spread_once_for_round_trip_and_zero_commission():
    assert PROFILE.commission_per_side_usd == 0
    assert PROFILE.btc_per_lot == 1
    assert spread_round_trip_cost(1, 10) == 10
    assert spread_round_trip_cost(.10, 10) == 1
    assert spread_round_trip_cost(1, 10) != 20


def test_floor_lot_step_and_below_minimum():
    assert floor_exness_lots(.109) == .10
    assert floor_exness_lots(.019) == .01
    assert floor_exness_lots(.0099) == 0
    assert floor_exness_lots(.01) == .01


def test_risk_after_floor_and_below_minimum_mark(tmp_path):
    source = tmp_path / "frozen.csv"
    _frozen_rows().to_csv(source, index=False)
    rows = load_frozen_trades(source)
    audit = lot_rounding_analysis(rows)
    assert audit.exness_btc_qty.tolist() == [.10, 0]
    assert audit.volume_status.tolist() == ["EXECUTABLE", "BELOW_MINIMUM_VOLUME"]
    assert audit.planned_risk_after_rounding.iloc[0] == pytest.approx(2.5 * .10 / .105)
    assert audit.structural_risk_before_rounding.iloc[0] == pytest.approx(1.05)
    assert audit.structural_risk_after_rounding.iloc[0] == pytest.approx(1.0)
    assert audit.risk_reduction_percent.iloc[0] == pytest.approx((1 - .10 / .105) * 100)


def test_cost_only_preserves_trade_identity_and_uses_one_spread(tmp_path):
    source = tmp_path / "frozen.csv"
    _frozen_rows().to_csv(source, index=False)
    rows = load_frozen_trades(source)
    old = reprice(rows, old_cost=True)
    cost_only = reprice(rows, spread=10)
    executable = reprice(rows, spread=10, executable=True)
    for column in ("segment_id", "trade_id", "signal_time", "entry_time", "exit_time",
                   "direction", "pending_trigger_price", "actual_fill_price", "exit_price",
                   "structural_stop", "target", "exit_reason"):
        assert old[column].equals(cost_only[column])
        assert cost_only[column].equals(executable[column])
    assert cost_only.quantity_used.tolist() == pytest.approx([.105, .009])
    assert cost_only.spread_cost.tolist() == pytest.approx([1.05, .09])
    assert cost_only.commission_cost_used.sum() == 0
    assert cost_only.net_pnl_repriced.iloc[0] == pytest.approx(2.1 - 1.05)
    assert metrics(cost_only)["executable_trades"] == 2
    assert metrics(executable)["executable_trades"] == 1
    assert executable.spread_cost.iloc[0] == pytest.approx(1.0)


def test_development_validation_year_and_direction_aggregation(tmp_path):
    source = tmp_path / "frozen.csv"
    _frozen_rows().to_csv(source, index=False)
    rows = load_frozen_trades(source)
    assert research_set(rows.signal_time).tolist() == ["development", "forward-validation"]
    results = build_reports(source, tmp_path / "reports")
    years = results["yearly"]
    directions = results["direction"]
    long_2024 = years.loc[(years.view == "cost_only") & (years.year == 2024)].iloc[0]
    short_2025 = years.loc[(years.view == "cost_only") & (years.year == 2025)].iloc[0]
    assert long_2024.trades == 1 and long_2024.net_pnl == pytest.approx(1.05)
    assert short_2025.trades == 1 and short_2025.net_pnl == pytest.approx(-.18)
    assert directions.loc[(directions.view == "cost_only") &
                          (directions.direction == "LONG"), "trades"].iloc[0] == 1
    assert directions.loc[(directions.view == "cost_only") &
                          (directions.direction == "SHORT"), "trades"].iloc[0] == 1
