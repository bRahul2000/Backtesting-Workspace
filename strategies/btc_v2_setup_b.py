"""BTC Pullback + Trend Breakout V2.2.0: Setup B signal rules only.

The strategy consumes completed M15 candles and submits pending stop entries.
Its H1 filter always uses the preceding, fully completed UTC hour.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import time
from math import isfinite

from engine.models import CancelPendingOrder, Candle, Direction, ExecutionState, PendingOrder, Signal
from strategies.base import Strategy
from strategies.confirmed_h1 import ConfirmedH1Trend, H1TrendValue
from strategies.pine_indicators import ATR, DMI, EMA, RSI


SETUP_ID = "BTC_V2_SETUP_B"
STAGES = (
    "Eligible candles", "H1 long trend", "H1 short trend",
    "M15 long alignment", "M15 short alignment", "ADX pass",
    "Long RSI pass", "Short RSI pass", "Strong bullish candle",
    "Strong bearish candle", "Range ATR pass",
    "Long structure breakout", "Short structure breakout", "Anti-chase pass",
    "Long stop-distance pass", "Short stop-distance pass",
    "Final Long Signals", "Final Short Signals",
)


@dataclass(frozen=True)
class SetupBParameters:
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
    structure_lookback: int = 5
    minimum_body_percent: float = 0.50
    minimum_range_atr: float = 0.60
    maximum_range_atr: float = 2.75
    long_rsi_min: float = 50.0
    long_rsi_max: float = 75.0
    short_rsi_min: float = 25.0
    short_rsi_max: float = 50.0
    maximum_extension_atr: float = 2.50
    entry_buffer_atr: float = 0.05
    structure_stop_lookback: int = 2
    stop_buffer_atr: float = 0.20
    pending_bars: int = 2
    minimum_stop_atr: float = 0.60
    maximum_stop_atr: float = 3.00
    reward_multiple: float = 3.0
    session_start: time = time(7, 0)
    session_end: time = time(20, 0)
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
                   self.adx_smoothing, self.atr_length, self.structure_lookback,
                   self.structure_stop_lookback, self.pending_bars,
                   self.max_trades_per_day, self.maximum_daily_losing_streak)
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in lengths):
            raise ValueError("Setup B lengths, bars, and count limits must be positive integers.")
        if min(self.rsi_length, self.di_length, self.adx_smoothing, self.atr_length) < 2:
            raise ValueError("Pine RSI, DI, ADX smoothing, and ATR lengths require at least 2.")
        if not 3 <= self.structure_lookback <= 12 or not 1 <= self.structure_stop_lookback <= 10:
            raise ValueError("Pine structure lookbacks are outside their allowed ranges.")
        if not 1 <= self.pending_bars <= 5 or not 1 <= self.h1_slope_lookback <= 50:
            raise ValueError("Pine pending bars or H1 slope lookback is outside its allowed range.")
        if self.h1_fast_ema >= self.h1_slow_ema or self.ema_fast >= self.ema_slow:
            raise ValueError("Fast EMA lengths must be below slow EMA lengths.")
        numeric = (self.minimum_adx, self.minimum_body_percent,
                   self.minimum_range_atr, self.maximum_range_atr,
                   self.long_rsi_min, self.long_rsi_max,
                   self.short_rsi_min, self.short_rsi_max,
                   self.maximum_extension_atr, self.entry_buffer_atr,
                   self.stop_buffer_atr, self.minimum_stop_atr,
                   self.maximum_stop_atr, self.reward_multiple,
                   self.maximum_daily_drawdown_percent,
                   self.maximum_monthly_drawdown_percent,
                   self.maximum_all_time_drawdown_percent)
        if not all(isfinite(value) for value in numeric):
            raise ValueError("Setup B numeric parameters must be finite.")
        if (not 0.30 <= self.minimum_body_percent <= 1 or
            not 0.10 <= self.minimum_range_atr <= self.maximum_range_atr <= 10 or
            not 0 <= self.long_rsi_min <= self.long_rsi_max <= 100 or
            not 0 <= self.short_rsi_min <= self.short_rsi_max <= 100 or
            self.maximum_extension_atr < 0 or self.entry_buffer_atr < 0 or
            self.stop_buffer_atr < 0 or
            not 0 < self.minimum_stop_atr <= self.maximum_stop_atr or
            self.reward_multiple <= 0 or self.minimum_adx < 0 or
            min(self.maximum_daily_drawdown_percent,
                self.maximum_monthly_drawdown_percent,
                self.maximum_all_time_drawdown_percent) <= 0):
            raise ValueError("Setup B filter and risk thresholds are invalid.")
        if self.session_start >= self.session_end:
            raise ValueError("Setup B session must begin before it ends in UTC.")
        if any(day not in range(7) for day in self.allowed_days):
            raise ValueError("Allowed UTC weekdays must be 0 (Monday) through 6 (Sunday).")


@dataclass(frozen=True)
class SetupBObservation:
    candle: Candle
    h1: H1TrendValue
    ema_fast: float
    ema_slow: float
    adx: float | None
    rsi: float | None
    atr: float | None
    previous_high: float | None
    previous_low: float | None
    stop_low: float | None
    stop_high: float | None


@dataclass
class SetupBRiskState:
    """Pine V2.2 day/month opening equity and sticky permission locks."""
    params: SetupBParameters
    day_key: tuple[int, int, int] | None = None
    month_key: tuple[int, int] | None = None
    day_start_equity: float | None = None
    month_start_equity: float | None = None
    all_time_peak_equity: float | None = None
    trades_today: int = 0
    consecutive_losses_today: int = 0
    daily_equity_locked: bool = False
    daily_streak_locked: bool = False
    monthly_locked: bool = False
    all_time_locked: bool = False

    def advance(self, candle: Candle, equity: float,
                state: ExecutionState) -> None:
        day = (candle.timestamp.year, candle.timestamp.month, candle.timestamp.day)
        month = day[:2]
        if day != self.day_key:
            self.day_key = day
            self.day_start_equity = equity
            self.trades_today = 0
            self.consecutive_losses_today = 0
            self.daily_equity_locked = False
            self.daily_streak_locked = False
        if month != self.month_key:
            self.month_key = month
            self.month_start_equity = equity
            self.monthly_locked = False
        previous_peak = equity if self.all_time_peak_equity is None else self.all_time_peak_equity
        self.all_time_peak_equity = max(previous_peak, equity)
        if state.opened_position is not None:
            self.trades_today += 1
        closed = state.closed_trade
        if closed is not None:
            if closed.pnl < 0:
                self.consecutive_losses_today += 1
            elif closed.pnl > 0:
                self.consecutive_losses_today = 0
            # Pine leaves a breakeven streak unchanged.
            if self.consecutive_losses_today >= self.params.maximum_daily_losing_streak:
                self.daily_streak_locked = True
        if (self.day_start_equity > 0 and
            (self.day_start_equity - equity) / self.day_start_equity * 100 >=
                self.params.maximum_daily_drawdown_percent):
            self.daily_equity_locked = True
        if (self.month_start_equity > 0 and
            (self.month_start_equity - equity) / self.month_start_equity * 100 >=
                self.params.maximum_monthly_drawdown_percent):
            self.monthly_locked = True
        if (self.params.all_time_protection and self.all_time_peak_equity > 0 and
            (self.all_time_peak_equity - equity) / self.all_time_peak_equity * 100 >=
                self.params.maximum_all_time_drawdown_percent):
            self.all_time_locked = True

    @property
    def lock_reason(self) -> str | None:
        if self.trades_today >= self.params.max_trades_per_day:
            return "Maximum trades per UTC day reached."
        if self.daily_equity_locked:
            return "Daily equity drawdown limit reached."
        if self.daily_streak_locked:
            return "Daily consecutive closed-loss limit reached."
        if self.monthly_locked:
            return "Monthly equity drawdown limit reached."
        if self.all_time_locked:
            return "All-time equity drawdown limit reached."
        return None


def evaluate_setup_b(obs: SetupBObservation, params: SetupBParameters,
                     counters: Counter | None = None) -> Signal | None:
    """Apply directional, cumulative Pine Setup B gates without future data."""
    c = obs.candle
    atr = obs.atr
    body_pct = abs(c.close - c.open) / (c.high - c.low) if c.high > c.low else 0.0
    range_atr = (c.high - c.low) / atr if atr is not None and atr > 0 else None
    extension = abs(c.close - obs.ema_fast) / atr if atr is not None and atr > 0 else None
    for direction in (Direction.LONG, Direction.SHORT):
        if direction is Direction.LONG:
            checks = (
                ("H1 long trend", params.longs_enabled and obs.h1.long),
                ("M15 long alignment", obs.ema_fast > obs.ema_slow),
                ("ADX pass", obs.adx is not None and obs.adx >= params.minimum_adx),
                ("Long RSI pass", obs.rsi is not None and params.long_rsi_min <= obs.rsi <= params.long_rsi_max),
                ("Strong bullish candle", c.close > c.open and body_pct >= params.minimum_body_percent),
                ("Range ATR pass", range_atr is not None and params.minimum_range_atr <= range_atr <= params.maximum_range_atr),
                ("Long structure breakout", obs.previous_high is not None and c.close > obs.previous_high),
                ("Anti-chase pass", extension is not None and extension <= params.maximum_extension_atr),
            )
            stop_low = obs.stop_low
            stop_stage = "Long stop-distance pass"
        else:
            checks = (
                ("H1 short trend", params.shorts_enabled and obs.h1.short),
                ("M15 short alignment", obs.ema_fast < obs.ema_slow),
                ("ADX pass", obs.adx is not None and obs.adx >= params.minimum_adx),
                ("Short RSI pass", obs.rsi is not None and params.short_rsi_min <= obs.rsi <= params.short_rsi_max),
                ("Strong bearish candle", c.close < c.open and body_pct >= params.minimum_body_percent),
                ("Range ATR pass", range_atr is not None and params.minimum_range_atr <= range_atr <= params.maximum_range_atr),
                ("Short structure breakout", obs.previous_low is not None and c.close < obs.previous_low),
                ("Anti-chase pass", extension is not None and extension <= params.maximum_extension_atr),
            )
            stop_high = obs.stop_high
            stop_stage = "Short stop-distance pass"
        passed = True
        for name, condition in checks:
            if not condition:
                passed = False
                break
            if counters is not None:
                counters[name] += 1
        if not passed or atr is None or atr <= 0:
            continue
        if direction is Direction.LONG:
            if stop_low is None:
                continue
            trigger = c.high + params.entry_buffer_atr * atr
            stop = stop_low - params.stop_buffer_atr * atr
            risk_atr = (trigger - stop) / atr
        else:
            if stop_high is None:
                continue
            trigger = c.low - params.entry_buffer_atr * atr
            stop = stop_high + params.stop_buffer_atr * atr
            risk_atr = (stop - trigger) / atr
        if not (trigger > 0 and stop > 0):
            continue
        if not params.minimum_stop_atr <= risk_atr <= params.maximum_stop_atr:
            continue
        if counters is not None:
            counters[stop_stage] += 1
            counters["Final Long Signals" if direction is Direction.LONG else "Final Short Signals"] += 1
        return Signal.pending_stop(direction, trigger, stop, params.pending_bars, SETUP_ID)
    return None


class BtcV2SetupB(Strategy):
    def __init__(self, params: SetupBParameters | None = None) -> None:
        self.params = params or SetupBParameters()
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
        self.previous: deque[Candle] = deque(maxlen=max(p.structure_lookback,
                                                       p.structure_stop_lookback - 1))

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
        position = state.position
        if position is not None:
            sign = 1 if position.direction is Direction.LONG else -1
            equity += sign * (candle.close - position.entry_price) * position.quantity
            equity -= position.entry_commission
        return equity

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        p = self.params
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
        if (self.window_start is not None and candle.timestamp < self.window_start or
            self.window_end is not None and candle.timestamp > self.window_end):
            return None
        state = self.execution_state
        if state is None:
            raise RuntimeError("Setup B needs execution state from the backtester.")
        self.risk.advance(candle, self._marked_equity(candle), state)
        opening = candle.timestamp.time()
        if candle.timestamp.weekday() not in p.allowed_days:
            if state.pending_order is not None:
                return CancelPendingOrder("UTC trading day is disabled.", SETUP_ID)
            return None
        if not p.session_start <= opening < p.session_end:
            if state.pending_order is not None:
                return CancelPendingOrder("UTC trading session ended.", SETUP_ID)
            return None
        if self.risk.lock_reason is not None:
            if state.pending_order is not None:
                return CancelPendingOrder(self.risk.lock_reason, SETUP_ID)
            return None
        if state.position is not None or state.pending_order is not None:
            return None
        self.diagnostics["Eligible candles"] += 1
        return evaluate_setup_b(
            SetupBObservation(candle, h1, fast, slow, adx, rsi, atr,
                              previous_high, previous_low, stop_low, stop_high),
            p, self.diagnostics,
        )
