"""Standalone, frozen Pine V2.2.0 Setup A pullback/rejection strategy.

The current M15 candle is never counted as its own prior EMA touch. Entries
use the same pending-stop execution and shared Pine permissions as Setup B.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import time
from math import isfinite

from engine.models import CancelPendingOrder, Candle, Direction, ExecutionState, PendingOrder, Signal
from strategies.base import Strategy
from strategies.btc_v2_setup_b import SetupBRiskState
from strategies.confirmed_h1 import ConfirmedH1Trend, H1TrendValue
from strategies.pine_indicators import ATR, DMI, EMA, RSI


SETUP_ID = "BTC_V2_SETUP_A"
STAGES = (
    "Eligible candles", "H1 long trend", "H1 short trend",
    "M15 long alignment", "M15 short alignment", "ADX pass",
    "Long RSI pass", "Short RSI pass", "Recent prior EMA touch",
    "Bullish rejection", "Bearish rejection", "Rejection range pass",
    "Long stop-distance pass", "Short stop-distance pass",
    "Final Long Signals", "Final Short Signals",
)


@dataclass(frozen=True)
class SetupAParameters:
    h1_fast_ema: int = 50
    h1_slow_ema: int = 200
    h1_slope_lookback: int = 5
    ema_fast: int = 20
    ema_slow: int = 50
    rsi_length: int = 14
    di_length: int = 14
    adx_smoothing: int = 14
    minimum_adx: float = 18.0
    atr_length: int = 14
    touch_lookback: int = 5
    long_rsi_min: float = 54.0
    long_rsi_max: float = 68.0
    short_rsi_min: float = 32.0
    short_rsi_max: float = 46.0
    long_close_location: float = .60
    short_close_location: float = .40
    ema50_tolerance_atr: float = .50
    use_large_candle_filter: bool = True
    maximum_range_atr: float = 2.50
    entry_buffer_atr: float = .20
    stop_buffer_atr: float = .30
    pending_bars: int = 2
    minimum_stop_atr: float = .60
    maximum_stop_atr: float = 3.00
    reward_multiple: float = 3.0
    session_start: time = time(7)
    session_end: time = time(20)
    allowed_days: frozenset[int] = field(default_factory=lambda: frozenset(range(7)))
    longs_enabled: bool = True
    shorts_enabled: bool = True
    max_trades_per_day: int = 3
    maximum_daily_drawdown_percent: float = 1.0
    maximum_daily_losing_streak: int = 3
    maximum_monthly_drawdown_percent: float = 6.0
    all_time_protection: bool = False
    maximum_all_time_drawdown_percent: float = 10.0

    def __post_init__(self) -> None:
        lengths = (self.h1_fast_ema, self.h1_slow_ema, self.h1_slope_lookback,
                   self.ema_fast, self.ema_slow, self.rsi_length, self.di_length,
                   self.adx_smoothing, self.atr_length, self.touch_lookback,
                   self.pending_bars, self.max_trades_per_day,
                   self.maximum_daily_losing_streak)
        if any(type(x) is not int or x < 1 for x in lengths):
            raise ValueError("Setup A lengths and count limits must be positive integers.")
        values = (self.minimum_adx, self.long_rsi_min, self.long_rsi_max,
                  self.short_rsi_min, self.short_rsi_max, self.long_close_location,
                  self.short_close_location, self.ema50_tolerance_atr,
                  self.maximum_range_atr, self.entry_buffer_atr,
                  self.stop_buffer_atr, self.minimum_stop_atr,
                  self.maximum_stop_atr, self.reward_multiple,
                  self.maximum_daily_drawdown_percent,
                  self.maximum_monthly_drawdown_percent,
                  self.maximum_all_time_drawdown_percent)
        if not all(isfinite(x) for x in values):
            raise ValueError("Setup A numeric parameters must be finite.")
        if (self.h1_fast_ema >= self.h1_slow_ema or self.ema_fast >= self.ema_slow or
            not 1 <= self.touch_lookback <= 20 or not 1 <= self.pending_bars <= 10 or
            not 1 <= self.h1_slope_lookback <= 50 or
            min(self.rsi_length, self.di_length, self.adx_smoothing, self.atr_length) < 2 or
            not 0 <= self.long_rsi_min <= self.long_rsi_max <= 100 or
            not 0 <= self.short_rsi_min <= self.short_rsi_max <= 100 or
            not .5 <= self.long_close_location <= 1 or
            not 0 <= self.short_close_location <= .5 or
            min(self.minimum_adx, self.ema50_tolerance_atr, self.entry_buffer_atr,
                self.stop_buffer_atr) < 0 or self.maximum_range_atr < .5 or
            not 0 < self.minimum_stop_atr <= self.maximum_stop_atr or
            self.reward_multiple <= 0 or
            min(self.maximum_daily_drawdown_percent, self.maximum_monthly_drawdown_percent,
                self.maximum_all_time_drawdown_percent) <= 0 or
            self.session_start >= self.session_end or
            any(day not in range(7) for day in self.allowed_days)):
            raise ValueError("Setup A parameters violate Pine input bounds.")


@dataclass(frozen=True)
class SetupAObservation:
    candle: Candle
    h1: H1TrendValue
    ema_fast: float
    ema_slow: float
    adx: float | None
    rsi: float | None
    atr: float | None
    bars_since_prior_touch: int | None


def evaluate_setup_a(obs: SetupAObservation, params: SetupAParameters,
                     counters: Counter | None = None) -> Signal | None:
    """Apply the Pine 32/33 conjunctions in A-long, then A-short priority."""
    c = obs.candle
    candle_range = c.high - c.low
    valid_range = candle_range > 0
    location = (c.close - c.low) / candle_range if valid_range else None
    atr = obs.atr
    recent_touch = (obs.bars_since_prior_touch is not None and
                    obs.bars_since_prior_touch < params.touch_lookback)
    range_allowed = (not params.use_large_candle_filter or
                     (atr is not None and candle_range <= params.maximum_range_atr * atr))
    for direction in (Direction.LONG, Direction.SHORT):
        if direction is Direction.LONG:
            checks = (("H1 long trend", params.longs_enabled and obs.h1.long),
                      ("M15 long alignment", obs.ema_fast > obs.ema_slow),
                      ("ADX pass", obs.adx is not None and obs.adx >= params.minimum_adx),
                      ("Long RSI pass", obs.rsi is not None and
                       params.long_rsi_min <= obs.rsi <= params.long_rsi_max),
                      ("Recent prior EMA touch", recent_touch),
                      ("Bullish rejection", valid_range and c.close > c.open and
                       location >= params.long_close_location and atr is not None and
                       c.low >= obs.ema_slow - params.ema50_tolerance_atr * atr),
                      ("Rejection range pass", range_allowed))
            stage = "Long stop-distance pass"
        else:
            checks = (("H1 short trend", params.shorts_enabled and obs.h1.short),
                      ("M15 short alignment", obs.ema_fast < obs.ema_slow),
                      ("ADX pass", obs.adx is not None and obs.adx >= params.minimum_adx),
                      ("Short RSI pass", obs.rsi is not None and
                       params.short_rsi_min <= obs.rsi <= params.short_rsi_max),
                      ("Recent prior EMA touch", recent_touch),
                      ("Bearish rejection", valid_range and c.close < c.open and
                       location <= params.short_close_location and atr is not None and
                       c.high <= obs.ema_slow + params.ema50_tolerance_atr * atr),
                      ("Rejection range pass", range_allowed))
            stage = "Short stop-distance pass"
        passed = True
        for name, condition in checks:
            if not condition:
                passed = False
                if counters is not None:
                    counters[f"Failed: {name}"] += 1
                break
            if counters is not None:
                counters[name] += 1
        if not passed or atr is None or atr <= 0:
            continue
        if direction is Direction.LONG:
            trigger = c.high + params.entry_buffer_atr * atr
            stop = c.low - params.stop_buffer_atr * atr
            distance = trigger - stop
        else:
            trigger = c.low - params.entry_buffer_atr * atr
            stop = c.high + params.stop_buffer_atr * atr
            distance = stop - trigger
        if trigger <= 0 or stop <= 0 or distance <= 0:
            if counters is not None:
                counters[f"Failed: {stage} (invalid price)"] += 1
            continue
        if not params.minimum_stop_atr <= distance / atr <= params.maximum_stop_atr:
            if counters is not None:
                counters[f"Failed: {stage}"] += 1
            continue
        if counters is not None:
            counters[stage] += 1
            counters["Final Long Signals" if direction is Direction.LONG else
                     "Final Short Signals"] += 1
        return Signal.pending_stop(direction, trigger, stop, params.pending_bars, SETUP_ID)
    return None


class BtcV2SetupA(Strategy):
    def __init__(self, params: SetupAParameters | None = None) -> None:
        self.params = params or SetupAParameters()
        self.reset()

    def reset(self) -> None:
        self.risk = SetupBRiskState(self.params)
        self.diagnostics: Counter = Counter()
        self.window_start = self.window_end = None
        self.execution_state: ExecutionState | None = None
        self._reset_indicators()

    def _reset_indicators(self) -> None:
        p = self.params
        self.h1 = ConfirmedH1Trend(p.h1_fast_ema, p.h1_slow_ema, p.h1_slope_lookback)
        self.fast = EMA(p.ema_fast)
        self.slow = EMA(p.ema_slow)
        self.atr = ATR(p.atr_length)
        self.rsi = RSI(p.rsi_length)
        self.dmi = DMI(p.di_length, p.adx_smoothing)
        self._bar_index = 0
        self._last_touch_index: int | None = None

    def on_data_gap(self) -> None:
        self._reset_indicators()

    def on_backtest_window(self, start, end) -> None:
        self.window_start = start
        self.window_end = end

    def on_execution_state(self, state: ExecutionState) -> None:
        self.execution_state = state

    def on_backtest_end(self, pending_order: PendingOrder) -> CancelPendingOrder | None:
        return CancelPendingOrder("Backtest range ended.", SETUP_ID)

    def _marked_equity(self, candle: Candle) -> float:
        state = self.execution_state
        equity = state.balance
        if state.position is not None:
            position = state.position
            sign = 1 if position.direction is Direction.LONG else -1
            equity += sign * (candle.close - position.entry_price) * position.quantity
            equity -= position.entry_commission
        return equity

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        p = self.params
        self._bar_index += 1
        h1 = self.h1.update(candle)
        fast = self.fast.update(candle.close)
        slow = self.slow.update(candle.close)
        atr = self.atr.update(candle)
        rsi = self.rsi.update(candle.close)
        adx = self.dmi.update(candle).adx
        # Pine ta.barssince(touchesEither)[1]: inspect the preceding bar's
        # counter before recording whether the current bar touches an EMA.
        prior_touch = (None if self._last_touch_index is None else
                       self._bar_index - 1 - self._last_touch_index)
        if (candle.high >= fast >= candle.low or
            candle.high >= slow >= candle.low):
            self._last_touch_index = self._bar_index
        if (self.window_start is not None and candle.timestamp < self.window_start or
            self.window_end is not None and candle.timestamp > self.window_end):
            return None
        state = self.execution_state
        if state is None:
            raise RuntimeError("Setup A needs execution state from the backtester.")
        self.risk.advance(candle, self._marked_equity(candle), state)
        if candle.timestamp.weekday() not in p.allowed_days:
            self.diagnostics["Blocked: UTC weekday"] += 1
            if state.pending_order is not None:
                return CancelPendingOrder("UTC trading day is disabled.", SETUP_ID)
            return None
        if not p.session_start <= candle.timestamp.time() < p.session_end:
            self.diagnostics["Blocked: UTC session"] += 1
            if state.pending_order is not None:
                return CancelPendingOrder("UTC trading session ended.", SETUP_ID)
            return None
        if self.risk.lock_reason is not None:
            self.diagnostics[f"Blocked: {self.risk.lock_reason}"] += 1
            if state.pending_order is not None:
                return CancelPendingOrder(self.risk.lock_reason, SETUP_ID)
            return None
        if state.position is not None or state.pending_order is not None:
            self.diagnostics["Blocked: active position or pending order"] += 1
            return None
        self.diagnostics["Eligible candles"] += 1
        return evaluate_setup_a(
            SetupAObservation(candle, h1, fast, slow, adx, rsi, atr, prior_touch),
            p, self.diagnostics,
        )
