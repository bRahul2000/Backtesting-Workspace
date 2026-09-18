"""BTC V3-MR1 — Intraday Overshoot Mean Reversion.

Standalone M15 mean-reversion research component.
Fair value for the first baseline is EMA20 because the audited codebase has no
existing session-anchored VWAP implementation. No frozen V3 module is modified.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import time
from math import isfinite

import pandas as pd

from engine.models import CancelPendingOrder, Candle, Direction, ExecutionState, PendingOrder, Signal
from strategies.base import Strategy
from strategies.pine_indicators import ATR, DMI, EMA, RSI

STRATEGY_ID = "BTC_V3_MR1_INTRADAY_OVERSHOOT_MEAN_REVERSION"
SETUP_ID = "BTC_V3_MR1_OVERSHOOT_RECLAIM"
FAIR_VALUE_REFERENCE = "EMA20"


@dataclass(frozen=True)
class V3MR1Parameters:
    ema_fast: int = 20
    ema_slow: int = 50
    atr_length: int = 14
    rsi_length: int = 14
    di_length: int = 14
    adx_smoothing: int = 14

    maximum_adx: float = 28.0
    maximum_ema_separation_atr: float = 1.50
    minimum_distance_atr: float = 1.75
    maximum_distance_atr: float = 4.00
    excursion_lookback: int = 5
    long_rsi_max: float = 35.0
    short_rsi_min: float = 65.0
    minimum_body_percent: float = 0.40
    long_min_close_location: float = 0.60
    short_max_close_location: float = 0.40

    entry_buffer_atr: float = 0.05
    stop_buffer_atr: float = 0.20
    minimum_stop_atr: float = 0.50
    maximum_stop_atr: float = 2.50
    pending_bars: int = 2
    reward_multiple: float = 2.00

    session_start: time = time(0, 0)
    session_end: time = time(22, 0)
    max_trades_per_day: int = 3

    def __post_init__(self) -> None:
        ints = (
            self.ema_fast, self.ema_slow, self.atr_length, self.rsi_length,
            self.di_length, self.adx_smoothing, self.excursion_lookback,
            self.pending_bars, self.max_trades_per_day,
        )
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in ints):
            raise ValueError("V3-MR1 lengths/counts must be positive integers.")
        if self.ema_fast >= self.ema_slow:
            raise ValueError("V3-MR1 EMA20 length must be below EMA50 length.")
        numeric = (
            self.maximum_adx, self.maximum_ema_separation_atr,
            self.minimum_distance_atr, self.maximum_distance_atr,
            self.long_rsi_max, self.short_rsi_min, self.minimum_body_percent,
            self.long_min_close_location, self.short_max_close_location,
            self.entry_buffer_atr, self.stop_buffer_atr,
            self.minimum_stop_atr, self.maximum_stop_atr, self.reward_multiple,
        )
        if not all(isfinite(v) for v in numeric):
            raise ValueError("V3-MR1 numeric parameters must be finite.")
        if self.maximum_adx < 0 or self.maximum_ema_separation_atr < 0:
            raise ValueError("Regime thresholds must be nonnegative.")
        if not 0 < self.minimum_distance_atr <= self.maximum_distance_atr:
            raise ValueError("Fair-value distance bounds are invalid.")
        if not 0 <= self.long_rsi_max <= 100 or not 0 <= self.short_rsi_min <= 100:
            raise ValueError("RSI bounds are invalid.")
        if not 0 < self.minimum_body_percent <= 1:
            raise ValueError("Body threshold must be in (0,1].")
        if not 0 <= self.short_max_close_location < self.long_min_close_location <= 1:
            raise ValueError("Close-location thresholds are invalid.")
        if min(self.entry_buffer_atr, self.stop_buffer_atr) < 0:
            raise ValueError("Entry/stop buffers must be nonnegative.")
        if not 0 < self.minimum_stop_atr <= self.maximum_stop_atr:
            raise ValueError("Stop bounds are invalid.")
        if self.reward_multiple <= 0:
            raise ValueError("Reward multiple must be positive.")
        if self.session_start >= self.session_end:
            raise ValueError("UTC session start must precede session end.")


def body_percent(candle: Candle) -> float:
    width = candle.high - candle.low
    return abs(candle.close - candle.open) / width if width > 0 else 0.0


def close_location(candle: Candle) -> float:
    width = candle.high - candle.low
    return (candle.close - candle.low) / width if width > 0 else 0.5


def wick_proportions(candle: Candle) -> tuple[float, float]:
    width = candle.high - candle.low
    if width <= 0:
        return 0.0, 0.0
    upper = candle.high - max(candle.open, candle.close)
    lower = min(candle.open, candle.close) - candle.low
    return upper / width, lower / width


@dataclass(frozen=True)
class SetupEvaluation:
    signal: Signal | None
    diagnostics: dict | None


def regime_valid(ema20: float, ema50: float, atr: float | None,
                 adx: float | None, p: V3MR1Parameters) -> bool:
    if atr is None or atr <= 0 or adx is None:
        return False
    return adx <= p.maximum_adx and abs(ema20 - ema50) / atr <= p.maximum_ema_separation_atr


def evaluate_setup(candle: Candle, ema20: float, ema50: float,
                   atr: float | None, rsi: float | None, adx: float | None,
                   prior_candles: list[Candle], p: V3MR1Parameters) -> SetupEvaluation:
    if atr is None or atr <= 0 or rsi is None or adx is None:
        return SetupEvaluation(None, None)
    if len(prior_candles) < p.excursion_lookback:
        return SetupEvaluation(None, None)
    if not regime_valid(ema20, ema50, atr, adx, p):
        return SetupEvaluation(None, None)

    width = candle.high - candle.low
    if width <= 0:
        return SetupEvaluation(None, None)

    fair_value = ema20
    distance_atr = abs(candle.close - fair_value) / atr
    if not p.minimum_distance_atr <= distance_atr <= p.maximum_distance_atr:
        return SetupEvaluation(None, None)

    body = body_percent(candle)
    loc = close_location(candle)
    upper_wick, lower_wick = wick_proportions(candle)
    ema_sep = abs(ema20 - ema50) / atr
    prior = prior_candles[-p.excursion_lookback:]
    prior_low = min(x.low for x in prior)
    prior_high = max(x.high for x in prior)

    long_ok = (
        candle.close < fair_value
        and rsi <= p.long_rsi_max
        and candle.close > candle.open
        and candle.low < prior_low
        and candle.close > (candle.high + candle.low) / 2.0
        and body >= p.minimum_body_percent
        and loc >= p.long_min_close_location
    )
    if long_ok:
        trigger = candle.high + p.entry_buffer_atr * atr
        stop = candle.low - p.stop_buffer_atr * atr
        stop_atr = (trigger - stop) / atr
        if p.minimum_stop_atr <= stop_atr <= p.maximum_stop_atr:
            excursion = (prior_low - candle.low) / atr
            return SetupEvaluation(
                Signal.pending_stop(Direction.LONG, trigger, stop, p.pending_bars, SETUP_ID),
                {
                    "side": Direction.LONG.value,
                    "fair_value_reference": FAIR_VALUE_REFERENCE,
                    "fair_value": fair_value,
                    "distance_atr": distance_atr,
                    "rsi": rsi,
                    "adx": adx,
                    "ema20_ema50_separation_atr": ema_sep,
                    "confirmation_body_percent": body,
                    "confirmation_close_location_percent": loc * 100.0,
                    "upper_wick_percent": upper_wick * 100.0,
                    "lower_wick_percent": lower_wick * 100.0,
                    "five_bar_excursion_atr": excursion,
                    "stop_distance_atr": stop_atr,
                    "confirmation_low": candle.low,
                    "confirmation_high": candle.high,
                    "entry_trigger": trigger,
                    "structural_stop": stop,
                },
            )

    short_ok = (
        candle.close > fair_value
        and rsi >= p.short_rsi_min
        and candle.close < candle.open
        and candle.high > prior_high
        and candle.close < (candle.high + candle.low) / 2.0
        and body >= p.minimum_body_percent
        and loc <= p.short_max_close_location
    )
    if short_ok:
        trigger = candle.low - p.entry_buffer_atr * atr
        stop = candle.high + p.stop_buffer_atr * atr
        stop_atr = (stop - trigger) / atr
        if p.minimum_stop_atr <= stop_atr <= p.maximum_stop_atr:
            excursion = (candle.high - prior_high) / atr
            return SetupEvaluation(
                Signal.pending_stop(Direction.SHORT, trigger, stop, p.pending_bars, SETUP_ID),
                {
                    "side": Direction.SHORT.value,
                    "fair_value_reference": FAIR_VALUE_REFERENCE,
                    "fair_value": fair_value,
                    "distance_atr": distance_atr,
                    "rsi": rsi,
                    "adx": adx,
                    "ema20_ema50_separation_atr": ema_sep,
                    "confirmation_body_percent": body,
                    "confirmation_close_location_percent": loc * 100.0,
                    "upper_wick_percent": upper_wick * 100.0,
                    "lower_wick_percent": lower_wick * 100.0,
                    "five_bar_excursion_atr": excursion,
                    "stop_distance_atr": stop_atr,
                    "confirmation_low": candle.low,
                    "confirmation_high": candle.high,
                    "entry_trigger": trigger,
                    "structural_stop": stop,
                },
            )

    return SetupEvaluation(None, None)


class BtcV3MR1IntradayOvershootMeanReversion(Strategy):
    def __init__(self, params: V3MR1Parameters | None = None) -> None:
        self.params = params or V3MR1Parameters()
        self.reset()

    def reset(self) -> None:
        p = self.params
        self.fast = EMA(p.ema_fast)
        self.slow = EMA(p.ema_slow)
        self.atr = ATR(p.atr_length)
        self.rsi = RSI(p.rsi_length)
        self.dmi = DMI(p.di_length, p.adx_smoothing)
        self.previous: deque[Candle] = deque(maxlen=p.excursion_lookback)
        self.execution_state: ExecutionState | None = None
        self.pending_context: dict | None = None
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
        if state.opened_position is not None:
            self.pending_context = None
        elif state.pending_order is None and state.position is None and self.pending_context is not None:
            self.pending_context = None

    def on_backtest_end(self, pending_order: PendingOrder) -> CancelPendingOrder | None:
        return CancelPendingOrder("Backtest range ended.", pending_order.setup_id)

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        p = self.params
        ema20 = self.fast.update(candle.close)
        ema50 = self.slow.update(candle.close)
        atr = self.atr.update(candle)
        rsi = self.rsi.update(candle.close)
        dmi = self.dmi.update(candle)
        prior = list(self.previous)
        self.previous.append(candle)

        if ((self.window_start is not None and candle.timestamp < self.window_start)
                or (self.window_end is not None and candle.timestamp > self.window_end)):
            return None
        state = self.execution_state
        if state is None:
            raise RuntimeError("BTC V3-MR1 needs execution state from the backtester.")

        day = (candle.timestamp.year, candle.timestamp.month, candle.timestamp.day)
        if day != self.day_key:
            self.day_key = day
            self.trades_today = 0
        if state.opened_position is not None:
            self.trades_today += 1

        if not p.session_start <= candle.timestamp.time() < p.session_end:
            if state.pending_order is not None:
                self.pending_context = None
                return CancelPendingOrder("UTC trading session ended.", state.pending_order.setup_id)
            return None
        if self.trades_today >= p.max_trades_per_day:
            if state.pending_order is not None:
                self.pending_context = None
                return CancelPendingOrder("Maximum filled trades per UTC day reached.", state.pending_order.setup_id)
            return None
        if state.position is not None:
            return None

        # Pending MR1 setup remains valid only while the general regime remains
        # valid and price has not invalidated the confirmation extreme.
        if state.pending_order is not None:
            ctx = self.pending_context
            if ctx is None:
                return None
            if not regime_valid(ema20, ema50, atr, dmi.adx, p):
                self.pending_context = None
                return CancelPendingOrder("MR1 regime invalid before fill.", state.pending_order.setup_id)
            if ctx["side"] == Direction.LONG.value and candle.close < ctx["confirmation_low"]:
                self.pending_context = None
                return CancelPendingOrder("MR1 long confirmation low violated.", state.pending_order.setup_id)
            if ctx["side"] == Direction.SHORT.value and candle.close > ctx["confirmation_high"]:
                self.pending_context = None
                return CancelPendingOrder("MR1 short confirmation high violated.", state.pending_order.setup_id)
            return None

        self.diagnostics["Eligible candles"] += 1
        evaluation = evaluate_setup(candle, ema20, ema50, atr, rsi, dmi.adx, prior, p)
        if evaluation.signal is None:
            return None

        signal_time = candle.timestamp + pd.Timedelta(minutes=15)
        diag = {
            "signal_candle_time": candle.timestamp,
            **(evaluation.diagnostics or {}),
        }
        self.signal_diagnostics[signal_time] = diag
        self.pending_context = diag.copy()
        self.diagnostics[f"{evaluation.signal.direction.value} signals"] += 1
        return evaluation.signal
