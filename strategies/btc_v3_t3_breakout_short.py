"""BTC V3 T3 Breakout Short — Frozen.

Permanent frozen short-only T3 component recovered from validated research. It consumes completed M15 Bid
candles, uses only the previous fully confirmed H1 context, and emits pending
stop entries for either a trend-breakout engine or a range-sweep engine.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import time
from enum import Enum
from math import isfinite

from engine.models import (CancelPendingOrder, Candle, Direction, ExecutionState,
                           PendingOrder, Signal)
from strategies.base import Strategy
from strategies.confirmed_h1_regime import ConfirmedH1Regime, H1RegimeValue
from strategies.pine_indicators import ATR, DMI, EMA, RSI


STRATEGY_ID = "BTC_V3_T3_BREAKOUT_SHORT_FROZEN"
TREND_SETUP_ID = "BTC_V3_T3_BREAKOUT_SHORT_FROZEN"
RANGE_SETUP_ID = "BTC_V3_RANGE"


class MarketRegime(str, Enum):
    TREND = "TREND"
    RANGE = "RANGE"
    CHOP = "CHOP"


@dataclass(frozen=True)
class RegimeDecision:
    state: MarketRegime
    direction: Direction | None = None
    h1_separation_atr: float | None = None


@dataclass(frozen=True, init=False)
class V3T3FrozenParameters:
    trend_enabled: bool = True
    range_enabled: bool = False
    longs_enabled: bool = False
    shorts_enabled: bool = True

    h1_fast_ema: int = 50
    h1_slow_ema: int = 200
    h1_atr_length: int = 14
    h1_slope_lookback: int = 4
    trend_min_h1_separation_atr: float = 1.00
    range_max_h1_separation_atr: float = 0.80

    ema_fast: int = 20
    ema_slow: int = 50
    atr_length: int = 14
    rsi_length: int = 14
    di_length: int = 14
    adx_smoothing: int = 14
    trend_min_adx: float = 18.0
    range_max_adx: float = 24.0

    trend_structure_lookback: int = 5
    trend_minimum_body_percent: float = 0.70
    trend_minimum_range_atr: float = 0.60
    trend_maximum_range_atr: float = 2.00
    trend_long_rsi_min: float = 50.0
    trend_long_rsi_max: float = 76.0
    trend_short_rsi_min: float = 24.0
    trend_short_rsi_max: float = 50.0
    trend_maximum_extension_atr: float = 2.50
    trend_stop_lookback: int = 2

    range_sweep_lookback: int = 8
    range_minimum_sweep_atr: float = 0.05
    range_maximum_sweep_atr: float = 0.80
    range_minimum_body_percent: float = 0.35
    range_long_rsi_max: float = 46.0
    range_short_rsi_min: float = 54.0

    entry_buffer_atr: float = 0.05
    stop_buffer_atr: float = 0.20
    minimum_stop_atr: float = 0.50
    maximum_stop_atr: float = 3.00
    pending_bars: int = 2
    reward_multiple: float = 3.0

    session_start: time = time(0, 0)
    session_end: time = time(22, 0)
    max_trades_per_day: int = 3

    def __post_init__(self) -> None:
        lengths = (
            self.h1_fast_ema, self.h1_slow_ema, self.h1_atr_length,
            self.h1_slope_lookback, self.ema_fast, self.ema_slow,
            self.atr_length, self.rsi_length, self.di_length,
            self.adx_smoothing, self.trend_structure_lookback,
            self.trend_stop_lookback, self.range_sweep_lookback,
            self.pending_bars, self.max_trades_per_day,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
               for value in lengths):
            raise ValueError("V3 lengths, bars, and count limits must be positive integers.")
        if self.h1_fast_ema >= self.h1_slow_ema or self.ema_fast >= self.ema_slow:
            raise ValueError("V3 fast EMA lengths must be below slow EMA lengths.")
        if min(self.h1_atr_length, self.atr_length, self.rsi_length,
               self.di_length, self.adx_smoothing) < 2:
            raise ValueError("V3 ATR/RSI/DI/ADX lengths must be at least 2.")
        numeric = (
            self.trend_min_h1_separation_atr, self.range_max_h1_separation_atr,
            self.trend_min_adx, self.range_max_adx,
            self.trend_minimum_body_percent, self.trend_minimum_range_atr,
            self.trend_maximum_range_atr, self.trend_long_rsi_min,
            self.trend_long_rsi_max, self.trend_short_rsi_min,
            self.trend_short_rsi_max, self.trend_maximum_extension_atr,
            self.range_minimum_sweep_atr, self.range_maximum_sweep_atr,
            self.range_minimum_body_percent, self.range_long_rsi_max,
            self.range_short_rsi_min, self.entry_buffer_atr,
            self.stop_buffer_atr, self.minimum_stop_atr,
            self.maximum_stop_atr, self.reward_multiple,
        )
        if not all(isfinite(value) for value in numeric):
            raise ValueError("V3 numeric parameters must be finite.")
        if not 0 <= self.trend_min_h1_separation_atr:
            raise ValueError("Trend H1 separation must be nonnegative.")
        if not 0 <= self.range_max_h1_separation_atr:
            raise ValueError("Range H1 separation must be nonnegative.")
        if min(self.trend_min_adx, self.range_max_adx) < 0:
            raise ValueError("ADX thresholds must be nonnegative.")
        if not 0 < self.trend_minimum_body_percent <= 1:
            raise ValueError("Trend body percent must be in (0, 1].")
        if not 0 < self.range_minimum_body_percent <= 1:
            raise ValueError("Range body percent must be in (0, 1].")
        if not 0 < self.trend_minimum_range_atr <= self.trend_maximum_range_atr:
            raise ValueError("Trend candle ATR range is invalid.")
        if not 0 <= self.trend_long_rsi_min <= self.trend_long_rsi_max <= 100:
            raise ValueError("Trend long RSI bounds are invalid.")
        if not 0 <= self.trend_short_rsi_min <= self.trend_short_rsi_max <= 100:
            raise ValueError("Trend short RSI bounds are invalid.")
        if not 0 <= self.range_long_rsi_max <= 100 or not 0 <= self.range_short_rsi_min <= 100:
            raise ValueError("Range RSI bounds are invalid.")
        if not 0 <= self.range_minimum_sweep_atr <= self.range_maximum_sweep_atr:
            raise ValueError("Range sweep ATR bounds are invalid.")
        if self.trend_maximum_extension_atr < 0 or self.entry_buffer_atr < 0 or self.stop_buffer_atr < 0:
            raise ValueError("V3 distance/buffer parameters must be nonnegative.")
        if not 0 < self.minimum_stop_atr <= self.maximum_stop_atr:
            raise ValueError("V3 stop-distance bounds are invalid.")
        if self.reward_multiple <= 0:
            raise ValueError("V3 reward multiple must be positive.")
        if self.session_start >= self.session_end:
            raise ValueError("V3 UTC session must begin before it ends.")


@dataclass(frozen=True)
class V3Observation:
    candle: Candle
    h1: H1RegimeValue
    ema_fast: float
    ema_slow: float
    adx: float | None
    rsi: float | None
    atr: float | None
    trend_previous_high: float | None
    trend_previous_low: float | None
    range_previous_high: float | None
    range_previous_low: float | None
    trend_stop_low: float
    trend_stop_high: float


def classify_regime(obs: V3Observation, params: V3T3FrozenParameters) -> RegimeDecision:
    """Classify from signal-time information only; TREND has priority on overlap."""
    h1 = obs.h1
    sep = h1.separation_atr
    slope = h1.slope
    if sep is None or slope is None or obs.adx is None:
        return RegimeDecision(MarketRegime.CHOP, h1_separation_atr=sep)

    bullish = (h1.fast_ema > h1.slow_ema and slope > 0 and
               obs.ema_fast > obs.ema_slow)
    bearish = (h1.fast_ema < h1.slow_ema and slope < 0 and
               obs.ema_fast < obs.ema_slow)
    if (params.trend_enabled and sep >= params.trend_min_h1_separation_atr
            and obs.adx >= params.trend_min_adx):
        if bullish:
            return RegimeDecision(MarketRegime.TREND, Direction.LONG, sep)
        if bearish:
            return RegimeDecision(MarketRegime.TREND, Direction.SHORT, sep)
    if (params.range_enabled and sep <= params.range_max_h1_separation_atr
            and obs.adx <= params.range_max_adx):
        return RegimeDecision(MarketRegime.RANGE, None, sep)
    return RegimeDecision(MarketRegime.CHOP, None, sep)


def _body_percent(candle: Candle) -> float:
    width = candle.high - candle.low
    return abs(candle.close - candle.open) / width if width > 0 else 0.0


def _pending(direction: Direction, trigger: float, stop: float,
             atr: float, params: V3T3FrozenParameters, setup_id: str) -> Signal | None:
    if not (trigger > 0 and stop > 0 and atr > 0):
        return None
    risk_atr = ((trigger - stop) / atr if direction is Direction.LONG
                else (stop - trigger) / atr)
    if not params.minimum_stop_atr <= risk_atr <= params.maximum_stop_atr:
        return None
    return Signal.pending_stop(direction, trigger, stop, params.pending_bars, setup_id)


def evaluate_v3(obs: V3Observation, params: V3T3FrozenParameters,
                counters: Counter | None = None) -> Signal | None:
    c, atr = obs.candle, obs.atr
    regime = classify_regime(obs, params)
    if counters is not None:
        counters[f"Regime {regime.state.value}"] += 1
    if atr is None or atr <= 0 or obs.rsi is None:
        return None
    body = _body_percent(c)

    if regime.state is MarketRegime.TREND:
        direction = regime.direction
        if direction is Direction.LONG:
            if not params.longs_enabled:
                return None
            range_atr = (c.high - c.low) / atr
            extension = abs(c.close - obs.ema_fast) / atr
            passed = (
                obs.trend_previous_high is not None and c.close > obs.trend_previous_high
                and c.close > c.open
                and body >= params.trend_minimum_body_percent
                and params.trend_minimum_range_atr <= range_atr <= params.trend_maximum_range_atr
                and params.trend_long_rsi_min <= obs.rsi <= params.trend_long_rsi_max
                and extension <= params.trend_maximum_extension_atr
            )
            if not passed:
                return None
            trigger = c.high + params.entry_buffer_atr * atr
            stop = obs.trend_stop_low - params.stop_buffer_atr * atr
        elif direction is Direction.SHORT:
            if not params.shorts_enabled:
                return None
            range_atr = (c.high - c.low) / atr
            extension = abs(c.close - obs.ema_fast) / atr
            passed = (
                obs.trend_previous_low is not None and c.close < obs.trend_previous_low
                and c.close < c.open
                and body >= params.trend_minimum_body_percent
                and params.trend_minimum_range_atr <= range_atr <= params.trend_maximum_range_atr
                and params.trend_short_rsi_min <= obs.rsi <= params.trend_short_rsi_max
                and extension <= params.trend_maximum_extension_atr
            )
            if not passed:
                return None
            trigger = c.low - params.entry_buffer_atr * atr
            stop = obs.trend_stop_high + params.stop_buffer_atr * atr
        else:
            return None
        signal = _pending(direction, trigger, stop, atr, params, TREND_SETUP_ID)
        if signal is not None and counters is not None:
            counters[f"Trend {direction.value} Signals"] += 1
        return signal

    if regime.state is MarketRegime.RANGE:
        long_depth = ((obs.range_previous_low - c.low) / atr
                      if obs.range_previous_low is not None else None)
        short_depth = ((c.high - obs.range_previous_high) / atr
                       if obs.range_previous_high is not None else None)
        if (params.longs_enabled and long_depth is not None
                and params.range_minimum_sweep_atr <= long_depth <= params.range_maximum_sweep_atr
                and c.low < obs.range_previous_low and c.close > obs.range_previous_low
                and c.close > c.open and body >= params.range_minimum_body_percent
                and obs.rsi <= params.range_long_rsi_max):
            signal = _pending(
                Direction.LONG,
                c.high + params.entry_buffer_atr * atr,
                c.low - params.stop_buffer_atr * atr,
                atr, params, RANGE_SETUP_ID,
            )
            if signal is not None and counters is not None:
                counters["Range LONG Signals"] += 1
            return signal
        if (params.shorts_enabled and short_depth is not None
                and params.range_minimum_sweep_atr <= short_depth <= params.range_maximum_sweep_atr
                and c.high > obs.range_previous_high and c.close < obs.range_previous_high
                and c.close < c.open and body >= params.range_minimum_body_percent
                and obs.rsi >= params.range_short_rsi_min):
            signal = _pending(
                Direction.SHORT,
                c.low - params.entry_buffer_atr * atr,
                c.high + params.stop_buffer_atr * atr,
                atr, params, RANGE_SETUP_ID,
            )
            if signal is not None and counters is not None:
                counters["Range SHORT Signals"] += 1
            return signal
    return None


class BtcV3T3BreakoutShortFrozen(Strategy):
    def __init__(self, params: V3T3FrozenParameters | None = None) -> None:
        self.params = params or V3T3FrozenParameters()
        self.reset()

    def reset(self) -> None:
        self.diagnostics: Counter = Counter()
        self.execution_state: ExecutionState | None = None
        self.window_start = self.window_end = None
        self.day_key: tuple[int, int, int] | None = None
        self.trades_today = 0
        self._reset_indicators()

    def _reset_indicators(self) -> None:
        p = self.params
        self.h1 = ConfirmedH1Regime(
            p.h1_fast_ema, p.h1_slow_ema, p.h1_atr_length, p.h1_slope_lookback)
        self.fast = EMA(p.ema_fast)
        self.slow = EMA(p.ema_slow)
        self.atr = ATR(p.atr_length)
        self.rsi = RSI(p.rsi_length)
        self.dmi = DMI(p.di_length, p.adx_smoothing)
        self.previous: deque[Candle] = deque(maxlen=max(
            p.trend_structure_lookback, p.range_sweep_lookback,
            p.trend_stop_lookback - 1,
        ))

    def on_data_gap(self) -> None:
        self._reset_indicators()

    def on_backtest_window(self, start, end) -> None:
        self.window_start, self.window_end = start, end

    def on_execution_state(self, state: ExecutionState) -> None:
        self.execution_state = state

    def on_backtest_end(self, pending_order: PendingOrder) -> CancelPendingOrder | None:
        return CancelPendingOrder("Backtest range ended.", pending_order.setup_id)

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        p = self.params
        h1 = self.h1.update(candle)
        fast = self.fast.update(candle.close)
        slow = self.slow.update(candle.close)
        atr = self.atr.update(candle)
        rsi = self.rsi.update(candle.close)
        dmi = self.dmi.update(candle)

        prior = list(self.previous)
        trend_high = (max(x.high for x in prior[-p.trend_structure_lookback:])
                      if len(prior) >= p.trend_structure_lookback else None)
        trend_low = (min(x.low for x in prior[-p.trend_structure_lookback:])
                     if len(prior) >= p.trend_structure_lookback else None)
        range_high = (max(x.high for x in prior[-p.range_sweep_lookback:])
                      if len(prior) >= p.range_sweep_lookback else None)
        range_low = (min(x.low for x in prior[-p.range_sweep_lookback:])
                     if len(prior) >= p.range_sweep_lookback else None)
        stop_bars = prior[-(p.trend_stop_lookback - 1):] if p.trend_stop_lookback > 1 else []
        stop_low = min(x.low for x in (*stop_bars, candle))
        stop_high = max(x.high for x in (*stop_bars, candle))
        self.previous.append(candle)

        if ((self.window_start is not None and candle.timestamp < self.window_start)
                or (self.window_end is not None and candle.timestamp > self.window_end)):
            return None
        state = self.execution_state
        if state is None:
            raise RuntimeError("BTC V3 T3 Frozen needs execution state from the backtester.")

        day = (candle.timestamp.year, candle.timestamp.month, candle.timestamp.day)
        if day != self.day_key:
            self.day_key = day
            self.trades_today = 0
        if state.opened_position is not None:
            self.trades_today += 1

        if not p.session_start <= candle.timestamp.time() < p.session_end:
            if state.pending_order is not None:
                return CancelPendingOrder("UTC trading session ended.", state.pending_order.setup_id)
            return None
        if self.trades_today >= p.max_trades_per_day:
            if state.pending_order is not None:
                return CancelPendingOrder("Maximum filled trades per UTC day reached.",
                                          state.pending_order.setup_id)
            return None
        if state.position is not None or state.pending_order is not None:
            return None

        self.diagnostics["Eligible candles"] += 1
        observation = V3Observation(
            candle=candle, h1=h1, ema_fast=fast, ema_slow=slow,
            adx=dmi.adx, rsi=rsi, atr=atr,
            trend_previous_high=trend_high, trend_previous_low=trend_low,
            range_previous_high=range_high, range_previous_low=range_low,
            trend_stop_low=stop_low, trend_stop_high=stop_high,
        )
        return evaluate_v3(observation, p, self.diagnostics)
