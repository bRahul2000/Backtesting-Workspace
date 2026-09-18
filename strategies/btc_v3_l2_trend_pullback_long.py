"""BTC V3-L2 Trend Pullback Long.

Research component independent from V2.2 and V3/T3. It uses completed M15 Bid
candles and only the previous fully confirmed H1 candle. The strategy is long
only: in a confirmed bullish H1/M15 trend it waits for a controlled pullback to
EMA20, EMA50, or the most recently broken local 5-bar structure high, then
requires a separate bullish reclaim/continuation candle before placing a two-bar
buy-stop order.
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


STRATEGY_ID = "BTC_V3_L2_TREND_PULLBACK_LONG"
SETUP_ID = "BTC_V3_L2_TREND_PULLBACK_LONG"
# The prompt says to reject a close "materially" below EMA50 but does not assign
# a number. For this first frozen baseline only, "materially" is operationalized
# as 0.20 ATR below EMA50, matching the existing V3 structural buffer. It is not
# optimized or varied anywhere in the baseline.
MATERIAL_EMA50_CLOSE_ATR = 0.20


@dataclass(frozen=True)
class V3L2Parameters:
    h1_fast_ema: int = 50
    h1_slow_ema: int = 200
    h1_atr_length: int = 14
    h1_slope_lookback: int = 4
    h1_min_separation_atr: float = 1.00

    ema_fast: int = 20
    ema_slow: int = 50
    atr_length: int = 14
    rsi_length: int = 14
    di_length: int = 14
    adx_smoothing: int = 14
    min_adx: float = 18.0

    local_structure_lookback: int = 5
    max_pullback_depth_below_ema20_atr: float = 1.00
    confirmation_min_body_percent: float = 0.60
    confirmation_rsi_min: float = 48.0
    confirmation_rsi_max: float = 70.0

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
        ints = (
            self.h1_fast_ema, self.h1_slow_ema, self.h1_atr_length,
            self.h1_slope_lookback, self.ema_fast, self.ema_slow,
            self.atr_length, self.rsi_length, self.di_length,
            self.adx_smoothing, self.local_structure_lookback,
            self.pending_bars, self.max_trades_per_day,
        )
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in ints):
            raise ValueError("V3-L2 lengths/counts must be positive integers.")
        if self.h1_fast_ema >= self.h1_slow_ema or self.ema_fast >= self.ema_slow:
            raise ValueError("Fast EMA lengths must be below slow EMA lengths.")
        nums = (
            self.h1_min_separation_atr, self.min_adx,
            self.max_pullback_depth_below_ema20_atr,
            self.confirmation_min_body_percent, self.confirmation_rsi_min,
            self.confirmation_rsi_max, self.entry_buffer_atr,
            self.stop_buffer_atr, self.minimum_stop_atr,
            self.maximum_stop_atr, self.reward_multiple,
        )
        if not all(isfinite(v) for v in nums):
            raise ValueError("V3-L2 numeric parameters must be finite.")
        if self.h1_min_separation_atr < 0 or self.min_adx < 0:
            raise ValueError("V3-L2 regime thresholds must be nonnegative.")
        if self.max_pullback_depth_below_ema20_atr < 0:
            raise ValueError("Pullback depth must be nonnegative.")
        if not 0 < self.confirmation_min_body_percent <= 1:
            raise ValueError("Confirmation body percent must be in (0, 1].")
        if not 0 <= self.confirmation_rsi_min <= self.confirmation_rsi_max <= 100:
            raise ValueError("Confirmation RSI bounds are invalid.")
        if min(self.entry_buffer_atr, self.stop_buffer_atr) < 0:
            raise ValueError("Entry/stop buffers must be nonnegative.")
        if not 0 < self.minimum_stop_atr <= self.maximum_stop_atr:
            raise ValueError("Stop-distance bounds are invalid.")
        if self.reward_multiple <= 0:
            raise ValueError("Reward multiple must be positive.")
        if self.session_start >= self.session_end:
            raise ValueError("UTC session start must be before session end.")


def h1_bullish(h1: H1RegimeValue, params: V3L2Parameters) -> bool:
    """Bullish regime using only the already-confirmed H1 value."""
    return (
        h1.close is not None
        and h1.fast_ema is not None
        and h1.slow_ema is not None
        and h1.slope is not None
        and h1.separation_atr is not None
        and h1.fast_ema > h1.slow_ema
        and h1.close > h1.slow_ema
        and h1.slope > 0
        and h1.separation_atr >= params.h1_min_separation_atr
    )


def body_percent(candle: Candle) -> float:
    width = candle.high - candle.low
    return abs(candle.close - candle.open) / width if width > 0 else 0.0


def confirmation_passes(
    candle: Candle,
    previous_candle: Candle | None,
    ema20: float,
    rsi: float | None,
    params: V3L2Parameters,
) -> bool:
    if previous_candle is None or rsi is None:
        return False
    return (
        candle.close > candle.open
        and body_percent(candle) >= params.confirmation_min_body_percent
        and candle.close > ema20
        and candle.close > previous_candle.high
        and params.confirmation_rsi_min <= rsi <= params.confirmation_rsi_max
    )


class BtcV3L2TrendPullbackLong(Strategy):
    """Stateful long-only pullback/reclaim component."""

    def __init__(self, params: V3L2Parameters | None = None) -> None:
        self.params = params or V3L2Parameters()
        self.reset()

    def reset(self) -> None:
        self.diagnostics: Counter = Counter()
        self.signal_diagnostics: dict[pd.Timestamp, dict] = {}
        self.execution_state: ExecutionState | None = None
        self.window_start = self.window_end = None
        self.day_key: tuple[int, int, int] | None = None
        self.trades_today = 0
        self._reset_indicators()
        self._reset_pullback_state(clear_structure=True)

    def _reset_indicators(self) -> None:
        p = self.params
        self.h1 = ConfirmedH1Regime(
            p.h1_fast_ema, p.h1_slow_ema, p.h1_atr_length, p.h1_slope_lookback)
        self.fast = EMA(p.ema_fast)
        self.slow = EMA(p.ema_slow)
        self.atr = ATR(p.atr_length)
        self.rsi = RSI(p.rsi_length)
        self.dmi = DMI(p.di_length, p.adx_smoothing)
        self.previous: deque[Candle] = deque(maxlen=max(p.local_structure_lookback, 2))

    def _reset_pullback_state(self, *, clear_structure: bool = False) -> None:
        self.pullback_active = False
        self.pullback_start_time: pd.Timestamp | None = None
        self.pullback_low: float | None = None
        self.pullback_max_depth_atr = 0.0
        self.pullback_bars = 0
        self.pullback_touch = ""
        if clear_structure:
            self.last_broken_structure_level: float | None = None
            self.last_structure_break_time: pd.Timestamp | None = None

    def on_data_gap(self) -> None:
        self._reset_indicators()
        self._reset_pullback_state(clear_structure=True)

    def on_backtest_window(self, start, end) -> None:
        self.window_start, self.window_end = start, end

    def on_execution_state(self, state: ExecutionState) -> None:
        self.execution_state = state
        if state.opened_position is not None:
            self._reset_pullback_state(clear_structure=False)

    def on_backtest_end(self, pending_order: PendingOrder) -> CancelPendingOrder | None:
        return CancelPendingOrder("Backtest range ended.", pending_order.setup_id)

    def _context_valid(self, h1: H1RegimeValue, ema20: float, ema50: float,
                       adx: float | None) -> bool:
        return h1_bullish(h1, self.params) and ema20 > ema50 and adx is not None and adx >= self.params.min_adx

    def _materially_below_ema50(self, candle: Candle, ema50: float, atr: float | None) -> bool:
        return atr is not None and atr > 0 and candle.close < ema50 - MATERIAL_EMA50_CLOSE_ATR * atr

    def _record_structure_break(self, candle: Candle, prior_high: float | None,
                                context_valid: bool) -> bool:
        if context_valid and prior_high is not None and candle.close > prior_high:
            self.last_broken_structure_level = prior_high
            self.last_structure_break_time = candle.timestamp
            self.diagnostics["Local structure breaks"] += 1
            return True
        return False

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        p = self.params
        h1 = self.h1.update(candle)
        ema20 = self.fast.update(candle.close)
        ema50 = self.slow.update(candle.close)
        atr = self.atr.update(candle)
        rsi = self.rsi.update(candle.close)
        dmi = self.dmi.update(candle)

        prior = list(self.previous)
        previous_candle = prior[-1] if prior else None
        prior_high = (max(x.high for x in prior[-p.local_structure_lookback:])
                      if len(prior) >= p.local_structure_lookback else None)
        self.previous.append(candle)

        if ((self.window_start is not None and candle.timestamp < self.window_start)
                or (self.window_end is not None and candle.timestamp > self.window_end)):
            return None
        state = self.execution_state
        if state is None:
            raise RuntimeError("BTC V3-L2 needs execution state from the backtester.")

        day = (candle.timestamp.year, candle.timestamp.month, candle.timestamp.day)
        if day != self.day_key:
            self.day_key = day
            self.trades_today = 0
        if state.opened_position is not None:
            self.trades_today += 1

        in_session = p.session_start <= candle.timestamp.time() < p.session_end
        context_valid = self._context_valid(h1, ema20, ema50, dmi.adx)
        material_below = self._materially_below_ema50(candle, ema50, atr)

        if state.pending_order is not None:
            if not in_session:
                return CancelPendingOrder("UTC trading session ended.", state.pending_order.setup_id)
            if self.trades_today >= p.max_trades_per_day:
                return CancelPendingOrder("Maximum filled trades per UTC day reached.", state.pending_order.setup_id)
            if not context_valid or material_below:
                return CancelPendingOrder("V3-L2 bullish trend context invalidated.", state.pending_order.setup_id)
            return None
        if state.position is not None:
            return None
        if not in_session or self.trades_today >= p.max_trades_per_day:
            self._reset_pullback_state(clear_structure=False)
            return None
        if atr is None or atr <= 0 or rsi is None or dmi.adx is None:
            return None

        if not context_valid or material_below:
            if self.pullback_active:
                self.diagnostics["Pullbacks invalidated by trend/EMA50"] += 1
            self._reset_pullback_state(clear_structure=not h1_bullish(h1, p))
            return None

        depth = max(0.0, (ema20 - candle.low) / atr)
        if self.pullback_active and depth > p.max_pullback_depth_below_ema20_atr:
            self.diagnostics["Pullbacks too deep"] += 1
            self._reset_pullback_state(clear_structure=False)
            # A bar that invalidates a pullback is not allowed to start another one.
            self._record_structure_break(candle, prior_high, context_valid)
            return None

        # Once a pullback exists, confirmation has priority over recording a new
        # breakout level so a reclaim candle is not accidentally reset.
        if self.pullback_active:
            self.pullback_low = min(self.pullback_low, candle.low) if self.pullback_low is not None else candle.low
            self.pullback_max_depth_atr = max(self.pullback_max_depth_atr, depth)
            self.pullback_bars += 1
            if (self.pullback_start_time is not None and candle.timestamp > self.pullback_start_time
                    and confirmation_passes(candle, previous_candle, ema20, rsi, p)):
                trigger = candle.high + p.entry_buffer_atr * atr
                stop = self.pullback_low - p.stop_buffer_atr * atr
                risk_atr = (trigger - stop) / atr
                if p.minimum_stop_atr <= risk_atr <= p.maximum_stop_atr:
                    signal = Signal.pending_stop(Direction.LONG, trigger, stop, p.pending_bars, SETUP_ID)
                    signal_time = candle.timestamp + pd.Timedelta(minutes=15)
                    self.signal_diagnostics[signal_time] = {
                        "setup_id": SETUP_ID,
                        "signal_candle_time": candle.timestamp,
                        "pullback_start_time": self.pullback_start_time,
                        "pullback_bars": self.pullback_bars,
                        "pullback_touch": self.pullback_touch,
                        "pullback_depth_atr": self.pullback_max_depth_atr,
                        "distance_to_ema20_atr": (candle.close - ema20) / atr,
                        "distance_to_ema50_atr": (candle.close - ema50) / atr,
                        "adx": dmi.adx,
                        "rsi": rsi,
                        "body_percent": body_percent(candle),
                        "h1_separation_atr": h1.separation_atr,
                        "h1_ema200_slope": h1.slope,
                        "h1_ema200_slope_atr": (h1.slope / h1.atr if h1.slope is not None and h1.atr else None),
                        "structure_level": self.last_broken_structure_level,
                        "entry_trigger": trigger,
                        "structural_stop": stop,
                        "stop_distance_atr": risk_atr,
                    }
                    self.diagnostics["Confirmation signals"] += 1
                    self._reset_pullback_state(clear_structure=False)
                    return signal
                self.diagnostics["Confirmation stop distance rejected"] += 1

        fresh_break = self._record_structure_break(candle, prior_high, context_valid)
        if fresh_break:
            # A structure-break candle is an impulse, not the pullback itself.
            return None

        if not self.pullback_active:
            touches: list[str] = []
            if candle.low <= ema20:
                touches.append("EMA20")
            if candle.low <= ema50:
                touches.append("EMA50")
            if self.last_broken_structure_level is not None and candle.low <= self.last_broken_structure_level:
                touches.append("STRUCTURE")
            if touches and depth <= p.max_pullback_depth_below_ema20_atr:
                self.pullback_active = True
                self.pullback_start_time = candle.timestamp
                self.pullback_low = candle.low
                self.pullback_max_depth_atr = depth
                self.pullback_bars = 1
                self.pullback_touch = "+".join(touches)
                self.diagnostics["Pullbacks started"] += 1
        return None
