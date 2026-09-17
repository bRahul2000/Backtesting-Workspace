"""Original Pine V2.2 A-before-B order priority, using frozen standalone gates.

This research strategy shares one account, indicator stream, pending order,
position, and risk state. Neither standalone setup nor the engine is changed.
"""
from __future__ import annotations

from collections import Counter

import pandas as pd

from engine.models import CancelPendingOrder, Candle, Signal
from strategies.btc_v2_setup_a import (SETUP_ID as A_ID, SetupAObservation,
                                       SetupAParameters, evaluate_setup_a)
from strategies.btc_v2_setup_b import (BtcV2SetupB, SETUP_ID as B_ID,
                                       SetupBObservation, SetupBParameters,
                                       evaluate_setup_b)


STEP = pd.Timedelta(minutes=15)


class BtcV2Combined(BtcV2SetupB):
    """Pine section 43: valid A long, A short, B long, then B short."""

    def __init__(self, a_params: SetupAParameters | None = None,
                 b_params: SetupBParameters | None = None) -> None:
        self.a_params = a_params or SetupAParameters()
        b = b_params or SetupBParameters()
        shared = ("h1_fast_ema", "h1_slow_ema", "h1_slope_lookback", "ema_fast",
                  "ema_slow", "rsi_length", "di_length", "adx_smoothing",
                  "minimum_adx", "atr_length", "minimum_stop_atr",
                  "maximum_stop_atr", "reward_multiple", "session_start",
                  "session_end", "allowed_days", "longs_enabled", "shorts_enabled",
                  "max_trades_per_day", "maximum_daily_drawdown_percent",
                  "maximum_daily_losing_streak", "maximum_monthly_drawdown_percent",
                  "all_time_protection", "maximum_all_time_drawdown_percent")
        if any(getattr(self.a_params, key) != getattr(b, key) for key in shared):
            raise ValueError("Combined A+B requires identical shared Pine inputs and permissions.")
        super().__init__(b)

    def reset(self) -> None:
        super().reset()
        self.a_diagnostics = Counter()
        self.captured_signals: list[dict] = []
        self.priority_suppressed: list[dict] = []
        self.blocked_by_a: list[dict] = []

    def _reset_indicators(self) -> None:
        super()._reset_indicators()
        self._bar_index = 0
        self._last_touch_index: int | None = None

    def on_backtest_end(self, pending_order) -> CancelPendingOrder | None:
        return CancelPendingOrder("Backtest range ended.", pending_order.setup_id)

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        p = self.params
        self._bar_index += 1
        h1 = self.h1.update(candle)
        fast = self.fast.update(candle.close)
        slow = self.slow.update(candle.close)
        atr = self.atr.update(candle)
        rsi = self.rsi.update(candle.close)
        adx = self.dmi.update(candle).adx
        prior = list(self.previous)
        previous_high = (max(x.high for x in prior[-p.structure_lookback:])
                         if len(prior) >= p.structure_lookback else None)
        previous_low = (min(x.low for x in prior[-p.structure_lookback:])
                        if len(prior) >= p.structure_lookback else None)
        stop_bars = prior[-(p.structure_stop_lookback - 1):] if p.structure_stop_lookback > 1 else []
        stop_low = min(x.low for x in (*stop_bars, candle))
        stop_high = max(x.high for x in (*stop_bars, candle))
        self.previous.append(candle)
        prior_touch = (None if self._last_touch_index is None else
                       self._bar_index - 1 - self._last_touch_index)
        if candle.high >= fast >= candle.low or candle.high >= slow >= candle.low:
            self._last_touch_index = self._bar_index
        if (self.window_start is not None and candle.timestamp < self.window_start or
            self.window_end is not None and candle.timestamp > self.window_end):
            return None
        state = self.execution_state
        if state is None:
            raise RuntimeError("Combined Setup A+B needs execution state.")
        self.risk.advance(candle, self._marked_equity(candle), state)
        if candle.timestamp.weekday() not in p.allowed_days:
            if state.pending_order is not None:
                return CancelPendingOrder("UTC trading day is disabled.",
                                          state.pending_order.setup_id)
            return None
        if not p.session_start <= candle.timestamp.time() < p.session_end:
            if state.pending_order is not None:
                return CancelPendingOrder("UTC trading session ended.",
                                          state.pending_order.setup_id)
            return None
        if self.risk.lock_reason is not None:
            if state.pending_order is not None:
                return CancelPendingOrder(self.risk.lock_reason,
                                          state.pending_order.setup_id)
            return None
        b_obs = SetupBObservation(candle, h1, fast, slow, adx, rsi, atr,
                                  previous_high, previous_low, stop_low, stop_high)
        if state.position is not None or state.pending_order is not None:
            blocker = (state.position.setup_id if state.position is not None
                       else state.pending_order.setup_id)
            if blocker == A_ID:
                b_candidate = evaluate_setup_b(b_obs, p)
                if b_candidate is not None:
                    self.blocked_by_a.append({"signal_time": candle.timestamp + STEP, "direction": b_candidate.direction.value,
                                              "blocker": "A_POSITION" if state.position is not None else "A_PENDING"})
            return None
        self.a_diagnostics["Eligible candles"] += 1
        self.diagnostics["Eligible candles"] += 1
        a_candidate = evaluate_setup_a(
            SetupAObservation(candle, h1, fast, slow, adx, rsi, atr, prior_touch),
            self.a_params, self.a_diagnostics)
        b_candidate = evaluate_setup_b(b_obs, p, self.diagnostics)
        if a_candidate is not None and b_candidate is not None:
            self.priority_suppressed.append({"signal_time": candle.timestamp + STEP,
                                             "direction": b_candidate.direction.value,
                                             "reason": "A priority on same candle"})
        action = a_candidate or b_candidate
        if action is not None:
            self.captured_signals.append({"signal_time": candle.timestamp + STEP,
                                          "setup_id": action.setup_id,
                                          "direction": action.direction.value,
                                          "trigger": action.pending_entry_price,
                                          "stop": action.pending_stop_price})
        return action
