"""Deterministic quote-side and order-reconciliation audit fixtures."""
from __future__ import annotations

import pandas as pd
import pytest

from engine.backtester import run_backtest
from engine.execution import (close_position, create_pending_order, exit_decision,
                              fill_pending_order)
from engine.models import Candle, Direction, SameBarResolution, Signal
from research.exness_cost_calibrated import (SETTINGS, entry_candle, exit_candle,
                                             run_synthetic_segment)
from research.exness_synthetic_audit import (LABEL, _trade_row, classify_order,
                                             explain_exclusive, same_bar_row)


T0 = pd.Timestamp("2024-05-06 12:00", tz="UTC")


def bar(n, open_, high, low, close):
    return Candle(T0 + pd.Timedelta(minutes=15 * n), open_, high, low, close, 1.)


class SinglePending:
    def __init__(self, direction):
        self.direction = direction

    def reset(self):
        self.seen = 0

    def on_backtest_window(self, start, end):
        pass

    def on_execution_state(self, state):
        pass

    def on_candle(self, candle):
        self.seen += 1
        if self.seen != 1:
            return None
        return (Signal.pending_stop(Direction.LONG, 105, 95, 1, "TEST")
                if self.direction is Direction.LONG else
                Signal.pending_stop(Direction.SHORT, 95, 105, 1, "TEST"))

    def on_backtest_end(self, order):
        return None


def frame(*bars):
    return pd.DataFrame([{"timestamp": c.timestamp, "open": c.open, "high": c.high,
                          "low": c.low, "close": c.close, "volume": c.volume}
                         for c in bars])


def test_long_ask_trigger_creates_synthetic_only_fill():
    data = frame(bar(0, 100, 101, 99, 100), bar(1, 100, 104, 98, 103))
    old = run_backtest(data, SinglePending(Direction.LONG), SETTINGS, trade_start=T0)
    new = run_synthetic_segment(data, SinglePending(Direction.LONG), 10, T0)
    assert old.order_events[0].status == "expired"
    assert new.order_events[0].status == "triggered"
    assert new.order_events[0].fill_price == 110  # Ask opened through the stop.
    category = classify_order({"status": "expired"}, {"status": "triggered"})
    assert category == "SYNTHETIC_ONLY_FILL"
    reason, explanation = explain_exclusive(
        {"direction": "LONG", "trigger_price": 105,
         "original_status": "expired", "synthetic_status": "triggered"},
        pd.Series({"open": 100, "high": 104, "low": 98, "close": 103}), 10,
        synthetic_only=True)
    assert reason == "LONG_ASK_TRIGGER" and "Bid high 104.00 did not" in explanation


def test_short_sell_stop_uses_bid_and_same_fill_bar():
    data = frame(bar(0, 100, 101, 99, 100), bar(1, 100, 104, 94, 96))
    old = run_backtest(data, SinglePending(Direction.SHORT), SETTINGS, trade_start=T0)
    new = run_synthetic_segment(data, SinglePending(Direction.SHORT), 10, T0)
    assert old.order_events[0].status == new.order_events[0].status == "triggered"
    assert old.order_events[0].fill_price == new.order_events[0].fill_price == 95
    assert classify_order({"status": "triggered", "fill_time": T0, "fill_price": 95},
                          {"status": "triggered", "fill_time": T0, "fill_price": 95}) == "SAME_FILL"
    reason, explanation = explain_exclusive(
        {"direction": "SHORT", "trigger_price": 95,
         "original_status": "triggered", "synthetic_status": "absent"},
        pd.Series({"open": 100, "high": 104, "low": 94, "close": 96}), 10,
        synthetic_only=False)
    assert reason == "SHORT_BID_TRIGGER" and "Bid-triggered in both" in explanation


def test_reconciliation_priority_is_disjoint():
    filled = {"status": "triggered", "fill_time": T0, "fill_price": 105.}
    later = {"status": "triggered", "fill_time": T0 + pd.Timedelta(minutes=15),
             "fill_price": 105.}
    different = {"status": "triggered", "fill_time": T0, "fill_price": 115.}
    assert classify_order(None, filled) == "SYNTHETIC_ONLY_FILL"
    assert classify_order(filled, None) == "ORIGINAL_ONLY_FILL"
    assert classify_order(filled, later) == "TIMING_CHANGED_FILL"
    assert classify_order(filled, different) == "PRICE_CHANGED_FILL"
    assert classify_order(filled, filled) == "SAME_FILL"
    assert classify_order({"status": "expired"}, {"status": "expired"}) == "EXPIRED_BOTH"
    assert classify_order({"status": "cancelled"}, {"status": "cancelled"}) == "CANCELED_BOTH"
    assert classify_order({"status": "expired"}, {"status": "cancelled"}) == "OTHER_ORDER_STATE"


@pytest.mark.parametrize("direction,signal,fill_bar,exit_bid", [
    (Direction.LONG, (105, 95), (100, 106, 98, 104), (100, 106, 94, 100)),
    (Direction.SHORT, (95, 105), (100, 104, 94, 96), (90, 96, 88, 92)),
])
def test_synthetic_entry_target_exit_and_no_double_cost(direction, signal, fill_bar, exit_bid):
    source = bar(0, 100, 101, 99, 100)
    pending = create_pending_order(Signal.pending_stop(direction, *signal, 2, "TEST"),
                                   source, 0, 10_000, SETTINGS)
    entry_bid = bar(1, *fill_bar)
    fill = fill_pending_order(pending, entry_candle(entry_bid, 10, direction),
                              1, 1, SETTINGS)
    assert fill is not None
    assert fill.entry_price == (110 if direction is Direction.LONG else 95)
    expected_target = fill.entry_price + (1 if direction is Direction.LONG else -1) * 3 * abs(
        fill.entry_price - fill.stop_loss)
    assert fill.take_profit == pytest.approx(expected_target)
    assert fill.entry_commission == 0
    closing_bid = bar(2, *exit_bid)
    closing_side = exit_candle(closing_bid, 10, direction)
    decision = exit_decision(fill, closing_side, SETTINGS.same_bar_resolution)
    assert decision is not None
    trade = close_position(fill, closing_side, 2, decision[0], decision[1], SETTINGS)
    audited = _trade_row("S01", trade)
    assert audited["entry_commission"] == audited["exit_commission"] == 0
    sign = 1 if direction is Direction.LONG else -1
    assert trade.pnl == pytest.approx(sign * (trade.exit_price - trade.entry_price) * trade.quantity)
    assert LABEL == "EXNESS STANDARD COST-CALIBRATED APPROXIMATION"


@pytest.mark.parametrize("direction,near_bid,hit_bid", [
    (Direction.LONG, (100, 154, 98, 110), (110, 156, 98, 120)),
    (Direction.SHORT, (90, 94, 60, 80), (80, 94, 54, 70)),
])
def test_target_is_evaluated_on_correct_exit_quote_side(direction, near_bid, hit_bid):
    source = bar(0, 100, 101, 99, 100)
    trigger, stop = (105, 95) if direction is Direction.LONG else (95, 105)
    pending = create_pending_order(Signal.pending_stop(direction, trigger, stop, 2),
                                   source, 0, 10_000, SETTINGS)
    fill_bid = (bar(1, 100, 106, 98, 104) if direction is Direction.LONG else
                bar(1, 100, 104, 94, 96))
    position = fill_pending_order(pending, entry_candle(fill_bid, 10, direction),
                                  1, 1, SETTINGS)
    assert position is not None
    assert exit_decision(position, exit_candle(bar(2, *near_bid), 10, direction),
                         SETTINGS.same_bar_resolution) is None
    decision = exit_decision(position, exit_candle(bar(3, *hit_bid), 10, direction),
                             SETTINGS.same_bar_resolution)
    assert decision is not None and decision[0] == position.take_profit


@pytest.mark.parametrize("direction", [Direction.LONG, Direction.SHORT])
def test_same_bar_ambiguous_stop_and_target_use_conservative_sl(direction):
    source = bar(0, 100, 101, 99, 100)
    trigger, stop = (105, 95) if direction is Direction.LONG else (95, 105)
    pending = create_pending_order(Signal.pending_stop(direction, trigger, stop, 2),
                                   source, 0, 10_000, SETTINGS)
    entry_bid = (bar(1, 100, 170, 80, 100) if direction is Direction.LONG else
                 bar(1, 100, 120, 40, 90))
    position = fill_pending_order(pending, entry_candle(entry_bid, 10, direction),
                                  1, 1, SETTINGS)
    side = exit_candle(entry_bid, 10, direction)
    decision = exit_decision(position, side, SameBarResolution.SL_FIRST,
                             entered_intrabar=True)
    assert decision is not None
    assert decision[0] == position.stop_loss
    assert "ambiguous bar, SL First" in decision[1]
    trade = close_position(position, side, 1, decision[0], decision[1], SETTINGS)
    row = same_bar_row("S01", trade, frame(entry_bid).set_index("timestamp"), 10)
    assert row["stop_touched"] and row["target_touched"] and row["both_touched"]
