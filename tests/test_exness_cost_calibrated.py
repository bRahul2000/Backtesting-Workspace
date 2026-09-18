"""Deterministic checks for research-only fixed-spread mechanics."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from engine.backtester import run_backtest
from engine.execution import create_pending_order, exit_decision, fill_pending_order
from engine.models import Candle, Direction, Signal
from research.exness_cost_calibrated import (LABEL, SETTINGS, _summary, ask_from_bid,
                                             entry_candle, exit_candle,
                                             run_synthetic_segment)
from research.exness_cost_recalibration import (load_frozen_trades, reprice,
                                                spread_round_trip_cost)
from strategies.btc_v2_setup_b import SetupBParameters


T0 = pd.Timestamp("2024-01-02 12:00", tz="UTC")


def candle(offset: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(T0 + pd.Timedelta(minutes=15 * offset), open_, high, low, close, 1.)


def test_one_full_spread_per_round_trip_and_quantity_scaling():
    assert [spread_round_trip_cost(q, 10) for q in (1., .1, .01)] == pytest.approx([10., 1., .1])
    assert SETTINGS.commission_percent == 0
    assert LABEL == "EXNESS STANDARD COST-CALIBRATED APPROXIMATION"
    bid_entry = bid_exit = 100.
    ask_entry = ask_exit = bid_entry + 10.
    assert (bid_exit - ask_entry) == -10.  # Long: Ask buy, Bid close.
    assert (bid_entry - ask_exit) == -10.  # Short: Bid sell, Ask close.


def test_quote_sides_and_ask_ohlc_are_absolute_price_offsets():
    bid = candle(0, 100, 105, 95, 101)
    ask = ask_from_bid(bid, 10)
    assert (ask.open, ask.high, ask.low, ask.close) == (110, 115, 105, 111)
    assert entry_candle(bid, 10, Direction.LONG) == ask
    assert entry_candle(bid, 10, Direction.SHORT) == bid
    assert exit_candle(bid, 10, Direction.LONG) == bid
    assert exit_candle(bid, 10, Direction.SHORT) == ask
    with pytest.raises(ValueError):
        ask_from_bid(bid, -1)


def test_buy_stop_uses_ask_and_sell_stop_uses_bid():
    signal_bar = candle(0, 100, 101, 99, 100)
    later = candle(1, 100, 104, 94, 100)
    long = create_pending_order(Signal.pending_stop(Direction.LONG, 105, 95, 2),
                                signal_bar, 0, 10_000, SETTINGS)
    short = create_pending_order(Signal.pending_stop(Direction.SHORT, 95, 105, 2),
                                 signal_bar, 0, 10_000, SETTINGS)
    assert fill_pending_order(long, later, 1, 1, SETTINGS) is None
    long_fill = fill_pending_order(long, entry_candle(later, 10, Direction.LONG),
                                   1, 1, SETTINGS)
    short_fill = fill_pending_order(short, entry_candle(later, 10, Direction.SHORT),
                                    1, 1, SETTINGS)
    assert long_fill.entry_price == 110  # Ask opened through trigger.
    assert short_fill.entry_price == 95   # Bid crossed trigger intrabar.


def test_long_exit_uses_bid_and_short_exit_uses_ask():
    signal_bar = candle(0, 100, 101, 99, 100)
    long = create_pending_order(Signal.pending_stop(Direction.LONG, 105, 95, 2),
                                signal_bar, 0, 10_000, SETTINGS)
    short = create_pending_order(Signal.pending_stop(Direction.SHORT, 95, 105, 2),
                                 signal_bar, 0, 10_000, SETTINGS)
    long_fill = fill_pending_order(long, candle(1, 100, 106, 98, 104), 1, 1, SETTINGS)
    short_fill = fill_pending_order(short, candle(1, 100, 104, 94, 96), 1, 1, SETTINGS)
    bid_for_long = candle(2, 100, 104, 94, 100)
    bid_for_short = candle(2, 90, 96, 88, 92)
    assert exit_decision(long_fill, exit_candle(bid_for_long, 10, Direction.LONG),
                         SETTINGS.same_bar_resolution)[0] == 95
    assert exit_decision(short_fill, bid_for_short,
                         SETTINGS.same_bar_resolution) is None
    assert exit_decision(short_fill, exit_candle(bid_for_short, 10, Direction.SHORT),
                         SETTINGS.same_bar_resolution)[0] == 105


class OneSignal:
    def reset(self):
        self.seen = 0

    def on_backtest_window(self, start, end):
        pass

    def on_execution_state(self, state):
        pass

    def on_candle(self, bar):
        self.seen += 1
        if self.seen == 1:
            return Signal.pending_stop(Direction.LONG, 105, 95, 2)
        return None

    def on_backtest_end(self, order):
        return None


def test_zero_spread_replay_matches_audited_generic_engine():
    frame = pd.DataFrame([
        {"timestamp": T0, "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1},
        {"timestamp": T0 + pd.Timedelta(minutes=15), "open": 100, "high": 106,
         "low": 98, "close": 104, "volume": 1},
        {"timestamp": T0 + pd.Timedelta(minutes=30), "open": 104, "high": 110,
         "low": 94, "close": 95, "volume": 1},
    ])
    original = run_backtest(frame, OneSignal(), SETTINGS, trade_start=T0)
    synthetic = run_synthetic_segment(frame, OneSignal(), 0, T0)
    assert [(t.entry_price, t.exit_price, t.pnl) for t in original.trades] == [
        (t.entry_price, t.exit_price, t.pnl) for t in synthetic.trades]
    assert [e.status for e in original.order_events] == [e.status for e in synthetic.order_events]


def test_synthetic_cost_is_reported_but_never_subtracted_twice():
    frame = pd.DataFrame([{"segment_id": "S01", "trade_id": 1,
                           "signal_time": T0, "exit_time": T0,
                           "quantity": .1, "initial_risk": 10., "pnl": 5.}])
    values = _summary(frame, synthetic=True, synthetic_spread=10)
    assert values["net_pnl"] == 5.
    assert values["total_spread_cost"] == 1.
    assert values["spread_cost_r_per_trade"] == .1


def test_frozen_setup_b_defaults_are_unmodified():
    params = SetupBParameters()
    assert params.minimum_adx == 18
    assert params.maximum_extension_atr == 2.5
    assert params.minimum_body_percent == .5
    assert SETTINGS.risk_reward_ratio == 3
    assert replace(SETTINGS, commission_percent=.05).commission_percent == .05


def test_cost_sensitivity_changes_only_cost_and_preserves_old_model():
    frozen = load_frozen_trades().head(2)
    old = reprice(frozen, old_cost=True)
    zero = reprice(frozen, spread=0)
    ten = reprice(frozen, spread=10)
    fifty = reprice(frozen, spread=50)
    assert old.net_pnl_repriced.tolist() == pytest.approx(frozen.net_pnl.tolist())
    old_summary = _summary(old, synthetic=False)
    assert old_summary["total_spread_cost"] == 0
    assert old_summary["total_commission_cost"] > 0
    assert old_summary["spread_cost_r_per_trade"] == 0
    assert old_summary["cost_r_per_trade"] > 0
    for col in ("signal_time", "entry_time", "exit_time", "actual_fill_price",
                "exit_price", "structural_stop", "target"):
        assert zero[col].equals(ten[col]) and ten[col].equals(fifty[col])
    assert (zero.net_pnl_repriced - ten.net_pnl_repriced).tolist() == pytest.approx(
        (10 * frozen.quantity_recovered).tolist())
    assert (zero.net_pnl_repriced - fifty.net_pnl_repriced).tolist() == pytest.approx(
        (50 * frozen.quantity_recovered).tolist())
