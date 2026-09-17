"""Deterministic tests for the isolated frozen-entry exit research."""
from types import SimpleNamespace

import pandas as pd
import pytest

from research.setup_b_exit_research import (
    _event, cost_reprice, development_robust_models, metrics, possible_mfe_reach,
    research_set, simulate_model,
)


BASE = pd.Timestamp("2024-06-01 00:00", tz="UTC")


def row(direction="LONG", **changes):
    values = dict(segment_id="S01", trade_id=7, direction=direction,
                  signal_time=BASE, signal_candle_time=BASE - pd.Timedelta(minutes=15),
                  pending_trigger_price=101 if direction == "LONG" else 99,
                  entry_time=BASE, actual_fill_price=100.,
                  structural_stop=90. if direction == "LONG" else 110.,
                  quantity_recovered=1., planned_risk_dollars=10.,
                  gap_through_trigger=False)
    values.update(changes)
    return SimpleNamespace(**values)


def candles(*bars):
    index = pd.date_range(BASE, periods=len(bars), freq="15min", tz="UTC", name="timestamp")
    return pd.DataFrame(bars, columns=["open", "high", "low", "close"], index=index)


def test_fixed_targets_long_and_short():
    long_bars = candles((99, 116, 99, 114), (114, 121, 111, 120))
    short_bars = candles((101, 101, 84, 86), (86, 89, 79, 80))
    for direction, bars, expected in (("LONG", long_bars, 120.),
                                      ("SHORT", short_bars, 80.)):
        e1 = _event(row(direction), bars, "E1")
        e2 = _event(row(direction), bars, "E2")
        assert e1["exit_price"] == expected
        assert e2["exit_price"] == (115. if direction == "LONG" else 85.)


@pytest.mark.parametrize("direction,activation", [("LONG", 110.), ("SHORT", 90.)])
def test_be_at_one_r(direction, activation):
    bars = (candles((99, activation, 99, 109), (109, 109, 100, 101))
            if direction == "LONG" else
            candles((101, 101, activation, 91), (91, 100, 91, 99)))
    event = _event(row(direction), bars, "E3")
    assert event["exit_price"] == 100.
    assert event["breakeven_exit"]
    assert event["net_pnl"] < 0  # price BE still pays both commissions


def test_be_at_one_point_five_r():
    assert _event(row(), candles((99, 115, 99, 114), (114, 114, 100, 101)), "E4")["breakeven_exit"]


def test_partial_commission_and_partial_be():
    bars = candles((99, 111, 99, 110), (110, 130, 109, 129))
    e5 = _event(row(), bars, "E5")
    assert e5["partial"] and e5["exit_price"] == 130
    assert e5["gross_pnl"] == 20.  # half at 1R, half at 3R
    assert e5["costs"] == pytest.approx((100 + 0.5 * 110 + 0.5 * 130) * .0005)
    e6 = _event(row(), candles((99, 111, 99, 110), (110, 111, 100, 101)), "E6")
    assert e6["partial"] and e6["breakeven_exit"]
    assert e6["gross_pnl"] == 5.


def test_two_r_plus_be():
    event = _event(row(), candles((99, 109, 99, 108), (111, 121, 111, 120)), "E7")
    assert event["exit_price"] == 120.


def test_stop_first_on_activation_ambiguity():
    event = _event(row(), candles((99, 111, 89, 100)), "E3")
    assert event["exit_price"] == 90.
    assert event["full_stop"]
    assert not event["breakeven_exit"]


def test_new_be_stop_wins_over_same_bar_target():
    event = _event(row(), candles((99, 131, 99, 130)), "E3")
    assert event["exit_price"] == 100.
    assert event["breakeven_exit"]


def test_opening_gap_and_segment_end():
    gap = _event(row(), candles((99, 105, 99, 104), (85, 90, 80, 88)), "E0")
    assert gap["exit_price"] == 85.
    assert _event(row(), candles((99, 105, 99, 104)), "E0") is None


def test_cost_reprice_gross_to_net():
    frame = pd.DataFrame([dict(entry_price=100., quantity=2., exit_notional=240.,
                               gross_pnl=40., planned_risk=20.)])
    priced = cost_reprice(frame, .05).iloc[0]
    assert priced.costs == pytest.approx(.22)
    assert priced.net_pnl == pytest.approx(39.78)
    assert priced.realized_r == pytest.approx(1.989)
    assert cost_reprice(frame, 0).iloc[0].net_pnl == 40.


def test_development_validation_boundary():
    assert research_set(pd.Timestamp("2024-12-31 23:45", tz="UTC")) == "development"
    assert research_set(pd.Timestamp("2025-01-01 00:00", tz="UTC")) == "forward-validation"
    with pytest.raises(ValueError):
        research_set(pd.Timestamp("2024-12-31"))


def test_frozen_entry_identity_across_models():
    source = pd.DataFrame([vars(row())])
    bars = {"S01": candles((99, 115, 99, 110), (110, 131, 100, 130))}
    for model in ("E0", "E1", "E2", "E3", "E4", "E5", "E6", "E7"):
        frame, open_end = simulate_model(source, bars, model)
        assert not open_end
        event = frame.iloc[0]
        assert (event.signal_time, event.pending_trigger, event.entry_price,
                event.initial_stop, event.direction) == (BASE, 101, 100, 90, "LONG")


def test_metrics_profit_factor_and_expectancy():
    frame = pd.DataFrame([dict(segment_id="S01", exit_time=BASE, net_pnl=20.,
                               gross_pnl=21., costs=1., realized_r=2., bars_held=2,
                               full_stop=False, breakeven_exit=False, partial=False),
                          dict(segment_id="S01", exit_time=BASE + pd.Timedelta(minutes=15),
                               net_pnl=-10., gross_pnl=-9., costs=1., realized_r=-1.,
                               bars_held=1, full_stop=True, breakeven_exit=False,
                               partial=False)])
    stats = metrics(frame)
    assert stats["profit_factor"] == 2.
    assert stats["average_r"] == stats["expectancy_r"] == .5
    assert stats["max_dd_percent"] > 0


def test_possible_mfe_upper_bound_includes_ambiguous_exit_bar():
    source = pd.DataFrame([vars(row(exit_time=BASE, actual_risk_distance=10.))])
    bars = {"S01": candles((99, 131, 90, 90))}
    upper = possible_mfe_reach(source, bars)
    assert upper["3R"] == 100.


def test_robust_screen_uses_only_development_rows():
    dev = pd.DataFrame([dict(model="E0", trades=150, average_r=-.1,
                             profit_factor=.9, max_dd_percent=5),
                        dict(model="E1", trades=150, average_r=.2,
                             profit_factor=1.2, max_dd_percent=5)])
    years = pd.DataFrame([dict(model="E1", year=2021, net_pnl=100),
                          dict(model="E1", year=2022, net_pnl=100),
                          dict(model="E1", year=2023, net_pnl=-20),
                          dict(model="E1", year=2024, net_pnl=-20)])
    assert development_robust_models(dev, years) == ["E1"]
