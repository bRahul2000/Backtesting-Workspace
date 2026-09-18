"""BTC V3-M1 — Momentum Expansion Continuation.

Standalone M15 momentum component:
compression -> volatility expansion -> directional follow-through -> stop entry.

The component intentionally does not depend on H1 regime logic and does not
modify any frozen V3 Core, A4, T3, or R2 implementation.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
from datetime import time
from math import isfinite

import pandas as pd

from engine.models import CancelPendingOrder, Candle, Direction, ExecutionState, PendingOrder, Signal
from strategies.base import Strategy
from strategies.pine_indicators import ATR, EMA, RSI

STRATEGY_ID = "BTC_V3_M1_MOMENTUM_EXPANSION_CONTINUATION"
SETUP_ID = "BTC_V3_M1_MOMENTUM_EXPANSION"


@dataclass(frozen=True)
class V3M1Parameters:
    ema_fast: int = 20
    ema_slow: int = 50
    atr_length: int = 14
    rsi_length: int = 14

    compression_lookback: int = 12
    compression_max_width_atr: float = 3.00
    prior_tr_lookback: int = 5
    prior_tr_average_max_atr: float = 0.90

    expansion_min_body_percent: float = 0.65
    expansion_min_range_atr: float = 1.20
    expansion_max_range_atr: float = 2.75
    long_min_close_location: float = 0.75
    short_max_close_location: float = 0.25
    long_rsi_min: float = 52.0
    long_rsi_max: float = 76.0
    short_rsi_min: float = 24.0
    short_rsi_max: float = 48.0

    follow_through_bars: int = 2
    entry_buffer_atr: float = 0.05
    stop_buffer_atr: float = 0.20
    minimum_stop_atr: float = 0.60
    maximum_stop_atr: float = 3.00
    pending_bars: int = 2
    reward_multiple: float = 3.00

    session_start: time = time(0, 0)
    session_end: time = time(22, 0)
    max_trades_per_day: int = 3

    def __post_init__(self) -> None:
        integer_fields = (
            self.ema_fast, self.ema_slow, self.atr_length, self.rsi_length,
            self.compression_lookback, self.prior_tr_lookback,
            self.follow_through_bars, self.pending_bars, self.max_trades_per_day,
        )
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in integer_fields):
            raise ValueError("V3-M1 lengths/counts must be positive integers.")
        if self.ema_fast >= self.ema_slow:
            raise ValueError("V3-M1 fast EMA must be below slow EMA.")
        numeric = (
            self.compression_max_width_atr, self.prior_tr_average_max_atr,
            self.expansion_min_body_percent, self.expansion_min_range_atr,
            self.expansion_max_range_atr, self.long_min_close_location,
            self.short_max_close_location, self.long_rsi_min, self.long_rsi_max,
            self.short_rsi_min, self.short_rsi_max, self.entry_buffer_atr,
            self.stop_buffer_atr, self.minimum_stop_atr, self.maximum_stop_atr,
            self.reward_multiple,
        )
        if not all(isfinite(v) for v in numeric):
            raise ValueError("V3-M1 numeric parameters must be finite.")
        if self.compression_max_width_atr <= 0 or self.prior_tr_average_max_atr <= 0:
            raise ValueError("Compression thresholds must be positive.")
        if not 0 < self.expansion_min_body_percent <= 1:
            raise ValueError("Expansion body percent must be in (0,1].")
        if not 0 < self.expansion_min_range_atr <= self.expansion_max_range_atr:
            raise ValueError("Expansion ATR range bounds are invalid.")
        if not 0 <= self.short_max_close_location < self.long_min_close_location <= 1:
            raise ValueError("Close-location thresholds are invalid.")
        if not 0 <= self.long_rsi_min <= self.long_rsi_max <= 100:
            raise ValueError("Long RSI bounds are invalid.")
        if not 0 <= self.short_rsi_min <= self.short_rsi_max <= 100:
            raise ValueError("Short RSI bounds are invalid.")
        if min(self.entry_buffer_atr, self.stop_buffer_atr) < 0:
            raise ValueError("Entry/stop buffers must be nonnegative.")
        if not 0 < self.minimum_stop_atr <= self.maximum_stop_atr:
            raise ValueError("Stop-distance bounds are invalid.")
        if self.reward_multiple <= 0:
            raise ValueError("Reward multiple must be positive.")
        if self.session_start >= self.session_end:
            raise ValueError("UTC session start must precede session end.")


def body_percent(candle: Candle) -> float:
    width = candle.high - candle.low
    return abs(candle.close - candle.open) / width if width > 0 else 0.0


def close_location(candle: Candle) -> float:
    """Return close location from candle low (0) to candle high (1)."""
    width = candle.high - candle.low
    return (candle.close - candle.low) / width if width > 0 else 0.5


def true_range(candle: Candle, previous_close: float | None) -> float:
    if previous_close is None:
        return candle.high - candle.low
    return max(candle.high - candle.low,
               abs(candle.high - previous_close),
               abs(candle.low - previous_close))


@dataclass
class ExpansionState:
    direction: Direction
    expansion_time: pd.Timestamp
    range_high: float
    range_low: float
    midpoint: float
    structure_low: float
    structure_high: float
    bars_elapsed: int
    diagnostics: dict


class BtcV3M1MomentumExpansionContinuation(Strategy):
    """Stateful compression/expansion/follow-through component."""

    def __init__(self, params: V3M1Parameters | None = None) -> None:
        self.params = params or V3M1Parameters()
        self.reset()

    def reset(self) -> None:
        p = self.params
        self.fast = EMA(p.ema_fast)
        self.slow = EMA(p.ema_slow)
        self.atr = ATR(p.atr_length)
        self.rsi = RSI(p.rsi_length)
        self.previous: deque[Candle] = deque(maxlen=p.compression_lookback)
        self.true_ranges: deque[float] = deque(maxlen=p.prior_tr_lookback)
        self.last_atr: float | None = None
        self.expansion: ExpansionState | None = None
        self.pending_context: dict | None = None
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
        if state.opened_position is not None:
            self.pending_context = None
            self.expansion = None
        elif state.pending_order is None and state.position is None and self.pending_context is not None:
            # The audited runner may have expired or cancelled the prior pending
            # order before this strategy callback.
            self.pending_context = None

    def on_backtest_end(self, pending_order: PendingOrder) -> CancelPendingOrder | None:
        return CancelPendingOrder("Backtest range ended.", pending_order.setup_id)

    def _back_inside(self, candle: Candle, direction: Direction,
                     range_high: float, range_low: float) -> bool:
        # Directional interpretation is intentionally conservative: after an
        # upside expansion, any close at/below the old ceiling invalidates it;
        # after a downside expansion, any close at/above the old floor does.
        return (candle.close <= range_high if direction is Direction.LONG
                else candle.close >= range_low)

    def _follow_through_valid(self, candle: Candle, previous: Candle | None,
                              state: ExpansionState) -> bool:
        if previous is None:
            return False
        if state.direction is Direction.LONG:
            return (
                candle.close > state.range_high
                and candle.close > state.midpoint
                and (candle.close > candle.open or candle.close > previous.high)
            )
        return (
            candle.close < state.range_low
            and candle.close < state.midpoint
            and (candle.close < candle.open or candle.close < previous.low)
        )

    def _detect_expansion(self, candle: Candle, ema20: float, ema50: float,
                          rsi: float | None, prior_atr: float | None,
                          prior_candles: list[Candle], prior_true_ranges: list[float]) -> ExpansionState | None:
        p = self.params
        if (prior_atr is None or prior_atr <= 0 or rsi is None
                or len(prior_candles) < p.compression_lookback
                or len(prior_true_ranges) < p.prior_tr_lookback):
            return None

        range_high = max(x.high for x in prior_candles[-p.compression_lookback:])
        range_low = min(x.low for x in prior_candles[-p.compression_lookback:])
        compression_width_atr = (range_high - range_low) / prior_atr
        prior_5_average_tr_over_atr = (
            sum(prior_true_ranges[-p.prior_tr_lookback:]) / p.prior_tr_lookback / prior_atr
        )
        if (compression_width_atr > p.compression_max_width_atr
                or prior_5_average_tr_over_atr > p.prior_tr_average_max_atr):
            return None

        candle_range = candle.high - candle.low
        if candle_range <= 0:
            return None
        expansion_range_atr = candle_range / prior_atr
        expansion_body = body_percent(candle)
        location = close_location(candle)
        ema_distance_atr = abs(ema20 - ema50) / prior_atr
        common = (
            expansion_body >= p.expansion_min_body_percent
            and p.expansion_min_range_atr <= expansion_range_atr <= p.expansion_max_range_atr
        )
        if not common:
            return None

        direction: Direction | None = None
        if (
            ema20 > ema50
            and candle.close > range_high
            and candle.close > candle.open
            and location >= p.long_min_close_location
            and p.long_rsi_min <= rsi <= p.long_rsi_max
        ):
            direction = Direction.LONG
        elif (
            ema20 < ema50
            and candle.close < range_low
            and candle.close < candle.open
            and location <= p.short_max_close_location
            and p.short_rsi_min <= rsi <= p.short_rsi_max
        ):
            direction = Direction.SHORT
        if direction is None:
            return None

        self.diagnostics[f"{direction.value} expansions"] += 1
        return ExpansionState(
            direction=direction,
            expansion_time=candle.timestamp,
            range_high=range_high,
            range_low=range_low,
            midpoint=(candle.high + candle.low) / 2.0,
            structure_low=candle.low,
            structure_high=candle.high,
            bars_elapsed=0,
            diagnostics={
                "compression_width_atr": compression_width_atr,
                "prior_5_average_tr_over_atr": prior_5_average_tr_over_atr,
                "expansion_range_atr": expansion_range_atr,
                "expansion_body_percent": expansion_body,
                "expansion_close_location_percent": location * 100.0,
                "rsi": rsi,
                "ema20_ema50_distance_atr": ema_distance_atr,
                "expansion_atr_reference": prior_atr,
                "compression_range_high": range_high,
                "compression_range_low": range_low,
            },
        )

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        p = self.params

        prior_candles = list(self.previous)
        previous_candle = prior_candles[-1] if prior_candles else None
        prior_true_ranges = list(self.true_ranges)
        prior_atr = self.last_atr

        ema20 = self.fast.update(candle.close)
        ema50 = self.slow.update(candle.close)
        current_atr = self.atr.update(candle)
        rsi = self.rsi.update(candle.close)

        current_tr = true_range(candle, previous_candle.close if previous_candle else None)
        self.previous.append(candle)
        self.true_ranges.append(current_tr)
        self.last_atr = current_atr

        if ((self.window_start is not None and candle.timestamp < self.window_start)
                or (self.window_end is not None and candle.timestamp > self.window_end)):
            return None
        state = self.execution_state
        if state is None:
            raise RuntimeError("BTC V3-M1 needs execution state from the backtester.")

        day = (candle.timestamp.year, candle.timestamp.month, candle.timestamp.day)
        if day != self.day_key:
            self.day_key = day
            self.trades_today = 0
        if state.opened_position is not None:
            self.trades_today += 1

        in_session = p.session_start <= candle.timestamp.time() < p.session_end
        if not in_session:
            self.expansion = None
            if state.pending_order is not None:
                self.pending_context = None
                return CancelPendingOrder("UTC trading session ended.", state.pending_order.setup_id)
            return None
        if self.trades_today >= p.max_trades_per_day:
            self.expansion = None
            if state.pending_order is not None:
                self.pending_context = None
                return CancelPendingOrder("Maximum filled trades per UTC day reached.", state.pending_order.setup_id)
            return None

        if state.pending_order is not None:
            context = self.pending_context
            if context is not None and self._back_inside(
                    candle, context["direction"], context["range_high"], context["range_low"]):
                self.pending_context = None
                return CancelPendingOrder(
                    "Price closed back inside the prior compression range before entry.",
                    state.pending_order.setup_id,
                )
            return None
        if state.position is not None:
            self.expansion = None
            return None

        # Follow-through is evaluated only on bars after the expansion candle.
        if self.expansion is not None:
            exp = self.expansion
            exp.bars_elapsed += 1
            exp.structure_low = min(exp.structure_low, candle.low)
            exp.structure_high = max(exp.structure_high, candle.high)

            if self._back_inside(candle, exp.direction, exp.range_high, exp.range_low):
                self.diagnostics["Expansion cancellations: close back inside"] += 1
                self.expansion = None
            else:
                valid = self._follow_through_valid(candle, previous_candle, exp)
                if valid and current_atr is not None and current_atr > 0:
                    ft_body = body_percent(candle)
                    if exp.direction is Direction.LONG:
                        trigger = candle.high + p.entry_buffer_atr * current_atr
                        stop = exp.structure_low - p.stop_buffer_atr * current_atr
                        stop_distance_atr = (trigger - stop) / current_atr
                    else:
                        trigger = candle.low - p.entry_buffer_atr * current_atr
                        stop = exp.structure_high + p.stop_buffer_atr * current_atr
                        stop_distance_atr = (stop - trigger) / current_atr
                    if p.minimum_stop_atr <= stop_distance_atr <= p.maximum_stop_atr:
                        signal_time = candle.timestamp + pd.Timedelta(minutes=15)
                        self.signal_diagnostics[signal_time] = {
                            "expansion_time": exp.expansion_time,
                            "follow_through_time": candle.timestamp,
                            "side": exp.direction.value,
                            **exp.diagnostics,
                            "follow_through_delay_bars": exp.bars_elapsed,
                            "follow_through_body_percent": ft_body,
                            "stop_distance_atr": stop_distance_atr,
                            "entry_trigger": trigger,
                            "structural_stop": stop,
                        }
                        self.pending_context = {
                            "direction": exp.direction,
                            "range_high": exp.range_high,
                            "range_low": exp.range_low,
                        }
                        self.expansion = None
                        self.diagnostics[f"{exp.direction.value} signals"] += 1
                        return Signal.pending_stop(exp.direction, trigger, stop,
                                                   p.pending_bars, SETUP_ID)
                    self.diagnostics["Follow-through rejected: stop distance"] += 1
                if self.expansion is not None and exp.bars_elapsed >= p.follow_through_bars:
                    self.diagnostics["Expansion cancellations: no follow-through"] += 1
                    self.expansion = None

        # If an older expansion ended on this close, the same completed candle
        # may independently qualify as a fresh expansion from its own prior-12
        # compression window. The current candle is never part of that window.
        if self.expansion is None:
            candidate = self._detect_expansion(
                candle, ema20, ema50, rsi, prior_atr, prior_candles, prior_true_ranges)
            if candidate is not None:
                self.expansion = candidate
        return None
