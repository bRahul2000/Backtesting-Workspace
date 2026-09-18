from __future__ import annotations

import pandas as pd

from engine.models import (CancelPendingOrder, Candle, Direction, ExecutionState,
                           PendingOrder, Position, Signal)
from strategies.btc_v3_a4_pullback_long import SETUP_ID as A4_SETUP_ID
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.btc_v3_t3_breakout_short import TREND_SETUP_ID as T3_SETUP_ID

T = pd.Timestamp("2024-06-03 12:00:00", tz="UTC")
C = Candle(T, 100., 101., 99., 100.5, 1.)


def _pending(setup_id, direction):
    return PendingOrder(direction, T, T, 105. if direction is Direction.LONG else 95.,
                        100., T + pd.Timedelta(minutes=30), 0, 2, 1., 25., 25., False,
                        setup_id)


def _position(setup_id=A4_SETUP_ID):
    return Position(1, Direction.LONG, T, T, 100., 95., 115., 1., 5., 0., 0,
                    setup_id=setup_id)


def test_core_is_composed_from_dedicated_frozen_modules():
    core = BtcV3CoreV1Frozen()
    assert core.a4.__class__.__name__ == "BtcV3A4PullbackLongFrozen"
    assert core.t3.__class__.__name__ == "BtcV3T3BreakoutShortFrozen"
    assert core.a4.params.reward_multiple == core.t3.params.reward_multiple == 3.0
    assert core.a4.params.max_trades_per_day == core.t3.params.max_trades_per_day == 3


def test_core_one_global_position_blocks_both_child_actions(monkeypatch):
    core = BtcV3CoreV1Frozen()
    core.on_execution_state(ExecutionState(10_000., None, _position()))
    monkeypatch.setattr(core.a4, "on_candle", lambda candle: Signal.pending_stop(Direction.LONG, 110., 100., 2, A4_SETUP_ID))
    monkeypatch.setattr(core.t3, "on_candle", lambda candle: Signal.pending_stop(Direction.SHORT, 90., 100., 2, T3_SETUP_ID))
    assert core.on_candle(C) is None


def test_core_non_owner_cannot_cancel_other_sides_pending_order(monkeypatch):
    core = BtcV3CoreV1Frozen()
    order = _pending(T3_SETUP_ID, Direction.SHORT)
    core.on_execution_state(ExecutionState(10_000., order, None))
    monkeypatch.setattr(core.a4, "on_candle", lambda candle: CancelPendingOrder("wrong side", A4_SETUP_ID))
    monkeypatch.setattr(core.t3, "on_candle", lambda candle: None)
    assert core.on_candle(C) is None


def test_core_pending_owner_cancellation_is_honored(monkeypatch):
    core = BtcV3CoreV1Frozen()
    order = _pending(A4_SETUP_ID, Direction.LONG)
    core.on_execution_state(ExecutionState(10_000., order, None))
    expected = CancelPendingOrder("A4 invalidated", A4_SETUP_ID)
    monkeypatch.setattr(core.a4, "on_candle", lambda candle: expected)
    monkeypatch.setattr(core.t3, "on_candle", lambda candle: CancelPendingOrder("ignore", T3_SETUP_ID))
    assert core.on_candle(C) == expected


def test_core_idle_routes_a4_or_t3_without_cross_side_replacement(monkeypatch):
    core = BtcV3CoreV1Frozen()
    core.on_execution_state(ExecutionState(10_000., None, None))
    a4 = Signal.pending_stop(Direction.LONG, 110., 100., 2, A4_SETUP_ID)
    t3 = Signal.pending_stop(Direction.SHORT, 90., 100., 2, T3_SETUP_ID)
    monkeypatch.setattr(core.a4, "on_candle", lambda candle: a4)
    monkeypatch.setattr(core.t3, "on_candle", lambda candle: None)
    assert core.on_candle(C) == a4

    core.on_execution_state(ExecutionState(10_000., None, None))
    monkeypatch.setattr(core.a4, "on_candle", lambda candle: None)
    monkeypatch.setattr(core.t3, "on_candle", lambda candle: t3)
    assert core.on_candle(C) == t3
