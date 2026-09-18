"""BTC V3 Core v1 — Frozen.

Permanent composition of two already-validated frozen components:
* V3 A4 Pullback Long — Frozen
* V3 T3 Breakout Short — Frozen

The audited backtester owns the single global pending order / position. Both child
strategies receive every completed candle and the same execution state so their
indicator and daily-count state stays synchronized. If a pending order exists,
only the child that owns that order may cancel it; actions from the other child
are ignored. No child strategy rule is duplicated or retuned here.
"""
from __future__ import annotations

from collections import Counter

from engine.models import CancelPendingOrder, Candle, ExecutionState, PendingOrder, Signal
from strategies.base import Strategy
from strategies.btc_v3_a4_pullback_long import (
    BtcV3A4PullbackLongFrozen,
    SETUP_ID as A4_SETUP_ID,
)
from strategies.btc_v3_t3_breakout_short import (
    BtcV3T3BreakoutShortFrozen,
    TREND_SETUP_ID as T3_SETUP_ID,
)

STRATEGY_ID = "BTC_V3_CORE_V1_FROZEN"


class BtcV3CoreV1Frozen(Strategy):
    """A4 long + T3 short, with one global execution state."""

    def __init__(self) -> None:
        self.a4 = BtcV3A4PullbackLongFrozen()
        self.t3 = BtcV3T3BreakoutShortFrozen()
        self.reset()

    def reset(self) -> None:
        self.a4.reset()
        self.t3.reset()
        self.execution_state: ExecutionState | None = None
        self.diagnostics: Counter = Counter()

    def on_data_gap(self) -> None:
        self.a4.on_data_gap()
        self.t3.on_data_gap()

    def on_backtest_window(self, start, end) -> None:
        self.a4.on_backtest_window(start, end)
        self.t3.on_backtest_window(start, end)

    def on_execution_state(self, state: ExecutionState) -> None:
        self.execution_state = state
        self.a4.on_execution_state(state)
        self.t3.on_execution_state(state)

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        state = self.execution_state
        if state is None:
            raise RuntimeError("BTC V3 Core v1 needs execution state from the backtester.")

        # Both children must see every completed candle. This also keeps their H1
        # confirmed-bar aggregators and M15 indicators identical to standalone runs.
        a4_action = self.a4.on_candle(candle)
        t3_action = self.t3.on_candle(candle)
        self._refresh_diagnostics()

        pending = state.pending_order
        if pending is not None:
            if pending.setup_id == A4_SETUP_ID:
                return a4_action if isinstance(a4_action, CancelPendingOrder) else None
            if pending.setup_id == T3_SETUP_ID:
                return t3_action if isinstance(t3_action, CancelPendingOrder) else None
            return None

        # While a position is open, neither frozen child can legitimately signal.
        if state.position is not None:
            return None

        # Their validated bullish/bearish opportunity sets do not overlap. Keep an
        # explicit deterministic priority only as a safeguard against future data bugs.
        if isinstance(a4_action, Signal):
            return a4_action
        if isinstance(t3_action, Signal):
            return t3_action
        return a4_action or t3_action

    def on_backtest_end(self, pending_order: PendingOrder) -> CancelPendingOrder | None:
        if pending_order.setup_id == A4_SETUP_ID:
            return self.a4.on_backtest_end(pending_order)
        if pending_order.setup_id == T3_SETUP_ID:
            return self.t3.on_backtest_end(pending_order)
        return CancelPendingOrder("Backtest range ended.", pending_order.setup_id)

    def _refresh_diagnostics(self) -> None:
        out = Counter()
        out.update({f"A4 · {k}": v for k, v in self.a4.diagnostics.items()})
        out.update({f"T3 · {k}": v for k, v in self.t3.diagnostics.items()})
        self.diagnostics = out
