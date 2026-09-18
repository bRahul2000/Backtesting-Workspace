"""BTC V3-R2 — Range Liquidity Sweep Reversal.

Standalone range/reversal component. It uses only completed M15 Bid candles and
previously confirmed H1 state. It is intentionally independent from frozen A4,
T3, and V3 Core v1 components.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import time
from math import isfinite

import pandas as pd

from engine.models import CancelPendingOrder, Candle, Direction, ExecutionState, PendingOrder, Signal
from strategies.base import Strategy
from strategies.confirmed_h1_regime import ConfirmedH1Regime, H1RegimeValue
from strategies.pine_indicators import ATR, DMI, EMA, RSI

STRATEGY_ID = "BTC_V3_R2_RANGE_LIQUIDITY_SWEEP_REVERSAL"
SETUP_ID = "BTC_V3_R2_RANGE_SWEEP"


@dataclass(frozen=True)
class V3R2Parameters:
    h1_fast_ema: int = 50
    h1_slow_ema: int = 200
    h1_atr_length: int = 14
    h1_slope_lookback: int = 4

    ema_fast: int = 20
    ema_slow: int = 50
    atr_length: int = 14
    rsi_length: int = 14
    di_length: int = 14
    adx_smoothing: int = 14

    range_max_h1_separation_atr: float = 0.80
    range_max_adx: float = 24.0
    range_max_m15_ema_separation_atr: float = 0.75

    # Explicit strong-trend exclusion uses the frozen V3/T3 trend boundary.
    strong_trend_min_h1_separation_atr: float = 1.00
    strong_trend_min_adx: float = 18.0

    structure_lookback: int = 12
    minimum_range_width_atr: float = 1.50
    maximum_range_width_atr: float = 5.00
    minimum_sweep_depth_atr: float = 0.05
    maximum_sweep_depth_atr: float = 0.75
    minimum_body_percent: float = 0.50
    close_location_fraction: float = 0.40
    long_rsi_max: float = 45.0
    short_rsi_min: float = 55.0
    maximum_boundary_distance_atr: float = 1.25

    entry_buffer_atr: float = 0.05
    stop_buffer_atr: float = 0.20
    minimum_stop_atr: float = 0.50
    maximum_stop_atr: float = 2.50
    pending_bars: int = 2
    reward_multiple: float = 2.50

    session_start: time = time(0, 0)
    session_end: time = time(22, 0)
    max_trades_per_day: int = 3

    def __post_init__(self) -> None:
        lengths = (
            self.h1_fast_ema, self.h1_slow_ema, self.h1_atr_length,
            self.h1_slope_lookback, self.ema_fast, self.ema_slow,
            self.atr_length, self.rsi_length, self.di_length,
            self.adx_smoothing, self.structure_lookback,
            self.pending_bars, self.max_trades_per_day,
        )
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in lengths):
            raise ValueError("V3-R2 lengths/counts must be positive integers.")
        if self.h1_fast_ema >= self.h1_slow_ema or self.ema_fast >= self.ema_slow:
            raise ValueError("V3-R2 fast EMA lengths must be below slow EMA lengths.")
        numeric = (
            self.range_max_h1_separation_atr, self.range_max_adx,
            self.range_max_m15_ema_separation_atr,
            self.strong_trend_min_h1_separation_atr, self.strong_trend_min_adx,
            self.minimum_range_width_atr, self.maximum_range_width_atr,
            self.minimum_sweep_depth_atr, self.maximum_sweep_depth_atr,
            self.minimum_body_percent, self.close_location_fraction,
            self.long_rsi_max, self.short_rsi_min, self.maximum_boundary_distance_atr,
            self.entry_buffer_atr, self.stop_buffer_atr,
            self.minimum_stop_atr, self.maximum_stop_atr, self.reward_multiple,
        )
        if not all(isfinite(v) for v in numeric):
            raise ValueError("V3-R2 numeric parameters must be finite.")
        if not 0 <= self.range_max_h1_separation_atr:
            raise ValueError("Range H1 separation must be nonnegative.")
        if min(self.range_max_adx, self.strong_trend_min_adx) < 0:
            raise ValueError("ADX thresholds must be nonnegative.")
        if not 0 <= self.range_max_m15_ema_separation_atr:
            raise ValueError("M15 EMA separation must be nonnegative.")
        if not 0 < self.minimum_range_width_atr <= self.maximum_range_width_atr:
            raise ValueError("Range-width ATR bounds are invalid.")
        if not 0 <= self.minimum_sweep_depth_atr <= self.maximum_sweep_depth_atr:
            raise ValueError("Sweep-depth ATR bounds are invalid.")
        if not 0 < self.minimum_body_percent <= 1:
            raise ValueError("Body percent must be in (0,1].")
        if not 0 < self.close_location_fraction < 0.5:
            raise ValueError("Close-location fraction must be in (0,0.5).")
        if not 0 <= self.long_rsi_max <= 100 or not 0 <= self.short_rsi_min <= 100:
            raise ValueError("RSI bounds must be in [0,100].")
        if min(self.maximum_boundary_distance_atr, self.entry_buffer_atr,
               self.stop_buffer_atr) < 0:
            raise ValueError("Distance/buffer parameters must be nonnegative.")
        if not 0 < self.minimum_stop_atr <= self.maximum_stop_atr:
            raise ValueError("Stop-distance ATR bounds are invalid.")
        if self.reward_multiple <= 0:
            raise ValueError("Reward multiple must be positive.")
        if self.session_start >= self.session_end:
            raise ValueError("UTC session start must precede session end.")


def body_percent(candle: Candle) -> float:
    width = candle.high - candle.low
    return abs(candle.close - candle.open) / width if width > 0 else 0.0


def close_location(candle: Candle) -> float:
    """0 = candle low, 1 = candle high."""
    width = candle.high - candle.low
    return (candle.close - candle.low) / width if width > 0 else 0.5


def strong_trend_active(h1: H1RegimeValue, ema20: float, ema50: float,
                        adx: float | None, params: V3R2Parameters) -> bool:
    if (h1.close is None or h1.fast_ema is None or h1.slow_ema is None
            or h1.slope is None or h1.separation_atr is None or adx is None):
        return False
    if h1.separation_atr < params.strong_trend_min_h1_separation_atr or adx < params.strong_trend_min_adx:
        return False
    bullish = (h1.fast_ema > h1.slow_ema and h1.close > h1.slow_ema
               and h1.slope > 0 and ema20 > ema50)
    bearish = (h1.fast_ema < h1.slow_ema and h1.close < h1.slow_ema
               and h1.slope < 0 and ema20 < ema50)
    return bullish or bearish


def range_regime(h1: H1RegimeValue, ema20: float, ema50: float,
                 atr: float | None, adx: float | None,
                 params: V3R2Parameters) -> bool:
    if (atr is None or atr <= 0 or adx is None or h1.separation_atr is None):
        return False
    if strong_trend_active(h1, ema20, ema50, adx, params):
        return False
    m15_sep = abs(ema20 - ema50) / atr
    return (h1.separation_atr <= params.range_max_h1_separation_atr
            and adx <= params.range_max_adx
            and m15_sep <= params.range_max_m15_ema_separation_atr)


@dataclass(frozen=True)
class SweepEvaluation:
    signal: Signal | None
    diagnostics: dict | None


def evaluate_sweep(candle: Candle, h1: H1RegimeValue, ema20: float, ema50: float,
                   atr: float | None, adx: float | None, rsi: float | None,
                   range_high: float | None, range_low: float | None,
                   params: V3R2Parameters) -> SweepEvaluation:
    if (atr is None or atr <= 0 or adx is None or rsi is None
            or range_high is None or range_low is None):
        return SweepEvaluation(None, None)
    if not range_regime(h1, ema20, ema50, atr, adx, params):
        return SweepEvaluation(None, None)

    range_width_atr = (range_high - range_low) / atr
    if not params.minimum_range_width_atr <= range_width_atr <= params.maximum_range_width_atr:
        return SweepEvaluation(None, None)

    width = candle.high - candle.low
    if width <= 0:
        return SweepEvaluation(None, None)
    body = body_percent(candle)
    location = close_location(candle)
    ema_sep_atr = abs(ema20 - ema50) / atr

    # Long sweep: current low breaches the prior completed-bar range low and
    # the same candle reclaims/closes above it with bullish rejection quality.
    long_depth = (range_low - candle.low) / atr
    long_boundary_distance = (candle.close - range_low) / atr
    long_ok = (
        candle.low < range_low
        and candle.close > range_low
        and params.minimum_sweep_depth_atr <= long_depth <= params.maximum_sweep_depth_atr
        and candle.close > candle.open
        and body >= params.minimum_body_percent
        and location >= 1.0 - params.close_location_fraction
        and rsi <= params.long_rsi_max
        and 0.0 <= long_boundary_distance <= params.maximum_boundary_distance_atr
    )
    if long_ok:
        trigger = candle.high + params.entry_buffer_atr * atr
        stop = candle.low - params.stop_buffer_atr * atr
        stop_atr = (trigger - stop) / atr
        if params.minimum_stop_atr <= stop_atr <= params.maximum_stop_atr:
            return SweepEvaluation(
                Signal.pending_stop(Direction.LONG, trigger, stop, params.pending_bars, SETUP_ID),
                {
                    "side": Direction.LONG.value,
                    "range_high": range_high,
                    "range_low": range_low,
                    "sweep_depth_atr": long_depth,
                    "range_width_atr": range_width_atr,
                    "body_percent": body,
                    "close_location_percent": location * 100.0,
                    "rsi": rsi,
                    "adx": adx,
                    "ema20_ema50_separation_atr": ema_sep_atr,
                    "boundary_distance_atr": long_boundary_distance,
                    "stop_distance_atr": stop_atr,
                    "h1_separation_atr": h1.separation_atr,
                    "h1_ema200_slope": h1.slope,
                    "entry_trigger": trigger,
                    "structural_stop": stop,
                },
            )

    short_depth = (candle.high - range_high) / atr
    short_boundary_distance = (range_high - candle.close) / atr
    short_ok = (
        candle.high > range_high
        and candle.close < range_high
        and params.minimum_sweep_depth_atr <= short_depth <= params.maximum_sweep_depth_atr
        and candle.close < candle.open
        and body >= params.minimum_body_percent
        and location <= params.close_location_fraction
        and rsi >= params.short_rsi_min
        and 0.0 <= short_boundary_distance <= params.maximum_boundary_distance_atr
    )
    if short_ok:
        trigger = candle.low - params.entry_buffer_atr * atr
        stop = candle.high + params.stop_buffer_atr * atr
        stop_atr = (stop - trigger) / atr
        if params.minimum_stop_atr <= stop_atr <= params.maximum_stop_atr:
            return SweepEvaluation(
                Signal.pending_stop(Direction.SHORT, trigger, stop, params.pending_bars, SETUP_ID),
                {
                    "side": Direction.SHORT.value,
                    "range_high": range_high,
                    "range_low": range_low,
                    "sweep_depth_atr": short_depth,
                    "range_width_atr": range_width_atr,
                    "body_percent": body,
                    "close_location_percent": location * 100.0,
                    "rsi": rsi,
                    "adx": adx,
                    "ema20_ema50_separation_atr": ema_sep_atr,
                    "boundary_distance_atr": short_boundary_distance,
                    "stop_distance_atr": stop_atr,
                    "h1_separation_atr": h1.separation_atr,
                    "h1_ema200_slope": h1.slope,
                    "entry_trigger": trigger,
                    "structural_stop": stop,
                },
            )

    return SweepEvaluation(None, None)


class BtcV3R2RangeLiquiditySweepReversal(Strategy):
    def __init__(self, params: V3R2Parameters | None = None) -> None:
        self.params = params or V3R2Parameters()
        self.reset()

    def reset(self) -> None:
        p = self.params
        self.h1 = ConfirmedH1Regime(p.h1_fast_ema, p.h1_slow_ema,
                                    p.h1_atr_length, p.h1_slope_lookback)
        self.fast = EMA(p.ema_fast)
        self.slow = EMA(p.ema_slow)
        self.atr = ATR(p.atr_length)
        self.rsi = RSI(p.rsi_length)
        self.dmi = DMI(p.di_length, p.adx_smoothing)
        self.previous: deque[Candle] = deque(maxlen=p.structure_lookback)
        self.execution_state: ExecutionState | None = None
        self.window_start = self.window_end = None
        self.day_key: tuple[int, int, int] | None = None
        self.trades_today = 0
        self.signal_diagnostics: dict[pd.Timestamp, dict] = {}
        self.diagnostics: Counter = Counter()

    def on_data_gap(self) -> None:
        self.reset()

    def on_backtest_window(self, start, end) -> None:
        self.window_start, self.window_end = start, end

    def on_execution_state(self, state: ExecutionState) -> None:
        self.execution_state = state

    def on_backtest_end(self, pending_order: PendingOrder) -> CancelPendingOrder | None:
        return CancelPendingOrder("Backtest range ended.", pending_order.setup_id)

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        p = self.params
        h1 = self.h1.update(candle)
        ema20 = self.fast.update(candle.close)
        ema50 = self.slow.update(candle.close)
        atr = self.atr.update(candle)
        rsi = self.rsi.update(candle.close)
        dmi = self.dmi.update(candle)

        prior = list(self.previous)
        range_high = max(x.high for x in prior) if len(prior) >= p.structure_lookback else None
        range_low = min(x.low for x in prior) if len(prior) >= p.structure_lookback else None
        self.previous.append(candle)

        if ((self.window_start is not None and candle.timestamp < self.window_start)
                or (self.window_end is not None and candle.timestamp > self.window_end)):
            return None
        state = self.execution_state
        if state is None:
            raise RuntimeError("BTC V3-R2 needs execution state from the backtester.")

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
                return CancelPendingOrder("Maximum filled trades per UTC day reached.", state.pending_order.setup_id)
            return None
        if state.position is not None or state.pending_order is not None:
            return None

        self.diagnostics["Eligible candles"] += 1
        if range_regime(h1, ema20, ema50, atr, dmi.adx, p):
            self.diagnostics["Range-regime candles"] += 1

        evaluation = evaluate_sweep(candle, h1, ema20, ema50, atr, dmi.adx, rsi,
                                    range_high, range_low, p)
        if evaluation.signal is None:
            return None
        signal_time = candle.timestamp + pd.Timedelta(minutes=15)
        self.signal_diagnostics[signal_time] = {
            "signal_candle_time": candle.timestamp,
            **(evaluation.diagnostics or {}),
        }
        self.diagnostics[f"{evaluation.signal.direction.value} signals"] += 1
        return evaluation.signal
