"""PB1 — BTC Shallow Trend Pullback Continuation (Phase A research baseline).

Concept: strong trend impulse -> shallow controlled retracement -> continuation
trigger. Genuinely different from A4 (EMA/structure-touch pullback engine) and
T3 (breakout engine): PB1's setup is defined entirely by a *measured* impulse
range and a *bounded* retracement percentage of that specific impulse, not by
touching a moving average or breaking a prior swing level.

This module only detects setups and returns Signal/CancelPendingOrder objects.
No fill, gap, stop/target, or Bid/Ask logic is reimplemented here — that stays
in the audited engine (engine/execution.py, engine/backtester.py). Target is a
fixed 3R applied by the audited engine's BacktestSettings.risk_reward_ratio,
matching every other strategy in this catalog; PB1 never sets take_profit.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd

from engine.diagnostics import DiagnosticEvent, XRayEvaluation
from engine.models import CancelPendingOrder, Candle, Direction, ExecutionState, Signal
from strategies.base import Strategy
from strategies.confirmed_h1_regime import ConfirmedH1Regime
from strategies.pine_indicators import ATR, EMA

STRATEGY_ID = "BTC_PB1_SHALLOW_PULLBACK_V1"
SETUP_ID = "PB1_SHALLOW_PULLBACK"


@dataclass(frozen=True)
class PB1Parameters:
    # H1 context (section 2)
    h1_fast_ema: int = 50
    h1_slow_ema: int = 200
    h1_atr_length: int = 14
    h1_slope_lookback: int = 4

    # M15 indicators
    m15_ema_fast: int = 20
    m15_ema_slow: int = 50
    m15_atr_length: int = 14

    # Impulse leg (section 3)
    impulse_window_bars: int = 3
    impulse_minimum_range_atr: float = 1.5

    # Shallow pullback (section 4)
    pullback_maximum_bars: int = 3
    pullback_minimum_retracement_percent: float = 0.20
    pullback_maximum_retracement_percent: float = 0.45

    # Continuation confirmation (section 5)
    confirmation_close_location_percent: float = 0.35
    confirmation_minimum_body_percent: float = 0.50
    confirmation_maximum_range_atr: float = 2.0

    # Entry (section 6)
    entry_buffer_atr: float = 0.10
    pending_expiry_bars: int = 2

    # Stop (section 7)
    stop_buffer_atr: float = 0.20
    minimum_stop_atr: float = 0.50
    maximum_stop_atr: float = 2.50

    # Target (section 8) — informational only; the audited engine applies this
    # via BacktestSettings.risk_reward_ratio, PB1 never sets take_profit itself.
    reward_multiple: float = 3.0

    def __post_init__(self) -> None:
        if min(self.h1_fast_ema, self.h1_slow_ema, self.h1_atr_length, self.h1_slope_lookback,
               self.m15_ema_fast, self.m15_ema_slow, self.m15_atr_length,
               self.impulse_window_bars, self.pullback_maximum_bars,
               self.pending_expiry_bars) < 1:
            raise ValueError("All lengths/windows must be positive integers.")
        if self.h1_fast_ema >= self.h1_slow_ema:
            raise ValueError("h1_fast_ema must be faster (smaller) than h1_slow_ema.")
        if self.m15_ema_fast >= self.m15_ema_slow:
            raise ValueError("m15_ema_fast must be faster (smaller) than m15_ema_slow.")
        if self.impulse_minimum_range_atr <= 0:
            raise ValueError("impulse_minimum_range_atr must be positive.")
        if not (0 < self.pullback_minimum_retracement_percent < self.pullback_maximum_retracement_percent < 1):
            raise ValueError("Pullback retracement bounds must satisfy 0 < min < max < 1.")
        if not (0 < self.confirmation_close_location_percent < 0.5):
            raise ValueError("confirmation_close_location_percent must be within (0, 0.5).")
        if not (0 < self.confirmation_minimum_body_percent <= 1):
            raise ValueError("confirmation_minimum_body_percent must be within (0, 1].")
        if self.confirmation_maximum_range_atr <= 0:
            raise ValueError("confirmation_maximum_range_atr must be positive.")
        if self.entry_buffer_atr < 0 or self.stop_buffer_atr < 0:
            raise ValueError("ATR buffers must be non-negative.")
        if not (0 < self.minimum_stop_atr < self.maximum_stop_atr):
            raise ValueError("Stop ATR bounds must satisfy 0 < minimum < maximum.")
        if self.reward_multiple <= 0:
            raise ValueError("reward_multiple must be positive.")


class _State(str, Enum):
    IDLE = "IDLE"
    PULLBACK = "PULLBACK"


@dataclass
class _Structure:
    direction: Direction
    impulse_high: float
    impulse_low: float
    impulse_size: float
    impulse_size_atr: float
    impulse_start: pd.Timestamp
    impulse_end: pd.Timestamp
    pullback_bars: int = 0
    deepest_price: float = 0.0


def _body_percent(candle: Candle) -> float | None:
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return None
    return abs(candle.close - candle.open) / candle_range


def _close_location_percent(candle: Candle) -> float | None:
    """0.0 = closed at the low, 1.0 = closed at the high."""
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return None
    return (candle.close - candle.low) / candle_range


class BtcPB1ShallowPullback(Strategy):
    """RESEARCH-status BTC continuation engine: impulse -> shallow pullback -> confirmation."""

    def __init__(self, params: PB1Parameters | None = None) -> None:
        self.params = params or PB1Parameters()
        self.diagnostic_events: list[DiagnosticEvent] = []
        self.xray_evaluations: list[XRayEvaluation] = []
        self.reset()

    def reset(self) -> None:
        p = self.params
        self.h1 = ConfirmedH1Regime(p.h1_fast_ema, p.h1_slow_ema, p.h1_atr_length, p.h1_slope_lookback)
        self.ema_fast = EMA(p.m15_ema_fast)
        self.ema_slow = EMA(p.m15_ema_slow)
        self.atr = ATR(p.m15_atr_length)
        self.impulse_window: deque[Candle] = deque(maxlen=p.impulse_window_bars)
        self.state = _State.IDLE
        self.structure: _Structure | None = None
        self.execution_state: ExecutionState | None = None
        self._tracked_pending_setup: str | None = None
        self.diagnostic_events = []
        self.xray_evaluations = []

    def on_data_gap(self) -> None:
        self.reset()

    def on_execution_state(self, state: ExecutionState) -> None:
        self.execution_state = state
        if state.opened_position is not None:
            self._log(DiagnosticEvent("entry", True, None, state.opened_position.entry_time,
                                      SETUP_ID, {"direction": state.opened_position.direction.value,
                                                 "entry_price": state.opened_position.entry_price}))
        if state.closed_trade is not None:
            trade = state.closed_trade
            self._log(DiagnosticEvent("exit", True, trade.exit_reason, trade.exit_time, SETUP_ID,
                                      {"r_multiple": trade.r_multiple, "pnl": trade.pnl}))
        if (self._tracked_pending_setup is not None and state.pending_order is None
                and state.opened_position is None and state.closed_trade is None):
            self._log(DiagnosticEvent("pending_order_expired", False, "expiry reached without fill",
                                      None, self._tracked_pending_setup))
            self._tracked_pending_setup = None
        if state.pending_order is not None:
            self._tracked_pending_setup = state.pending_order.setup_id

    # ------------------------------------------------------------------
    # diagnostics helpers
    # ------------------------------------------------------------------

    def _log(self, event: DiagnosticEvent) -> None:
        self.diagnostic_events.append(event)

    def _xray(self, timestamp: pd.Timestamp, rule: str, observed: Any, threshold: Any,
             passed: bool, description: str) -> None:
        self.xray_evaluations.append(XRayEvaluation(
            timestamp=timestamp, strategy_id=STRATEGY_ID, component=SETUP_ID, rule=rule,
            observed_value=observed, threshold=threshold,
            result="PASS" if passed else "FAIL",
            reason_code=rule.upper(), description=description,
        ))

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        p = self.params
        h1_regime = self.h1.update(candle)
        ema_fast = self.ema_fast.update(candle.close)
        ema_slow = self.ema_slow.update(candle.close)
        atr = self.atr.update(candle)

        cancel = self._maybe_cancel_pending(candle, h1_regime)
        if cancel is not None:
            self.state = _State.IDLE
            self.structure = None
            return cancel

        if atr is None or atr <= 0:
            self.impulse_window.append(candle)
            return None

        context = self._evaluate_h1_context(candle, h1_regime)

        if self._has_open_exposure():
            self.impulse_window.append(candle)
            return None

        signal: Signal | None = None
        if self.state is _State.IDLE:
            self._try_detect_impulse(candle, context, ema_fast, atr)
        elif self.state is _State.PULLBACK:
            signal = self._advance_pullback(candle, ema_fast, ema_slow, atr)

        self.impulse_window.append(candle)
        return signal

    def _has_open_exposure(self) -> bool:
        state = self.execution_state
        return bool(state and (state.pending_order is not None or state.position is not None))

    def _maybe_cancel_pending(self, candle: Candle, h1_regime) -> CancelPendingOrder | None:
        state = self.execution_state
        if state is None or state.pending_order is None:
            return None
        direction = state.pending_order.direction
        still_valid = (h1_regime.fast_ema is not None and h1_regime.slow_ema is not None and (
            h1_regime.fast_ema > h1_regime.slow_ema if direction is Direction.LONG
            else h1_regime.fast_ema < h1_regime.slow_ema
        ))
        if not still_valid:
            self._log(DiagnosticEvent("pending_order_cancelled", False, "H1 context invalidated",
                                      candle.timestamp, state.pending_order.setup_id))
            return CancelPendingOrder("H1 context invalidated", setup_id=state.pending_order.setup_id)
        return None

    # ------------------------------------------------------------------
    # section 2: H1 context
    # ------------------------------------------------------------------

    def _evaluate_h1_context(self, candle: Candle, h1_regime) -> Direction | None:
        if h1_regime.fast_ema is None or h1_regime.slow_ema is None or h1_regime.atr is None:
            self._log(DiagnosticEvent("h1_context_rejected", False, "H1 regime not yet warmed up",
                                      candle.timestamp, SETUP_ID))
            return None
        separation = h1_regime.fast_ema - h1_regime.slow_ema
        direction = Direction.LONG if separation > 0 else (Direction.SHORT if separation < 0 else None)
        self._xray(candle.timestamp, "trend_direction", direction.value if direction else "FLAT", None,
                  direction is not None, "H1 EMA50 vs EMA200 directional context")
        self._xray(candle.timestamp, "ema_separation_atr", h1_regime.separation_atr, 0.0, direction is not None,
                  "abs(EMA50-EMA200)/H1 ATR")
        if direction is None:
            self._log(DiagnosticEvent("h1_context_rejected", False, "EMA50/EMA200 separation is zero",
                                      candle.timestamp, SETUP_ID, {"slope": h1_regime.slope, "atr": h1_regime.atr}))
            return None
        self._log(DiagnosticEvent("h1_context_evaluated", True, None, candle.timestamp, SETUP_ID, {
            "direction": direction.value, "separation_atr": h1_regime.separation_atr,
            "slope": h1_regime.slope, "h1_atr": h1_regime.atr,
        }))
        return direction

    # ------------------------------------------------------------------
    # section 3: impulse leg
    # ------------------------------------------------------------------

    def _try_detect_impulse(self, candle: Candle, context: Direction | None, ema_fast: float, atr: float) -> None:
        p = self.params
        window = list(self.impulse_window) + [candle]
        if context is None or len(window) < p.impulse_window_bars:
            return
        window = window[-p.impulse_window_bars:]
        net_movement = window[-1].close - window[0].open
        impulse_high = max(item.high for item in window)
        impulse_low = min(item.low for item in window)
        impulse_size = impulse_high - impulse_low
        impulse_size_atr = impulse_size / atr

        if context is Direction.LONG:
            directional = net_movement > 0 and window[-1].close > ema_fast
        else:
            directional = net_movement < 0 and window[-1].close < ema_fast

        range_ok = impulse_size_atr >= p.impulse_minimum_range_atr
        self._xray(candle.timestamp, "impulse_atr", impulse_size_atr, p.impulse_minimum_range_atr,
                  range_ok, "Impulse range (last 3 M15 candles) in ATR")

        if not (directional and range_ok):
            self._log(DiagnosticEvent("impulse_rejected", False,
                                      "insufficient range" if not range_ok else "wrong net direction",
                                      candle.timestamp, SETUP_ID, {
                                          "net_movement": net_movement, "impulse_size_atr": impulse_size_atr,
                                          "context": context.value,
                                      }))
            return

        self.structure = _Structure(
            direction=context, impulse_high=impulse_high, impulse_low=impulse_low,
            impulse_size=impulse_size, impulse_size_atr=impulse_size_atr,
            impulse_start=window[0].timestamp, impulse_end=window[-1].timestamp,
            deepest_price=impulse_high if context is Direction.LONG else impulse_low,
        )
        self.state = _State.PULLBACK
        self._log(DiagnosticEvent("impulse_detected", True, None, candle.timestamp, SETUP_ID, {
            "direction": context.value, "impulse_high": impulse_high, "impulse_low": impulse_low,
            "impulse_size": impulse_size, "impulse_size_atr": impulse_size_atr,
            "impulse_start": str(window[0].timestamp), "impulse_end": str(window[-1].timestamp),
        }))

    # ------------------------------------------------------------------
    # sections 4-7: pullback tracking, confirmation, entry/stop construction
    # ------------------------------------------------------------------

    def _advance_pullback(self, candle: Candle, ema_fast: float, ema_slow: float, atr: float) -> Signal | None:
        p = self.params
        structure = self.structure
        assert structure is not None
        long = structure.direction is Direction.LONG

        structure.pullback_bars += 1
        if long:
            structure.deepest_price = min(structure.deepest_price, candle.low)
        else:
            structure.deepest_price = max(structure.deepest_price, candle.high)

        retracement_pct = (
            (structure.impulse_high - structure.deepest_price) / structure.impulse_size if long
            else (structure.deepest_price - structure.impulse_low) / structure.impulse_size
        )
        retracement_atr = abs(structure.impulse_high - structure.deepest_price) / atr if long else \
            abs(structure.deepest_price - structure.impulse_low) / atr

        # Invalidation: pullback fully erased the impulse, or H1 context flipped.
        invalidated_reason = None
        if retracement_pct > p.pullback_maximum_retracement_percent:
            invalidated_reason = "retracement exceeded maximum"
        elif retracement_pct >= 1.0:
            invalidated_reason = "pullback fully erased the impulse"

        if invalidated_reason is not None:
            self._log(DiagnosticEvent("pullback_rejected", False, invalidated_reason, candle.timestamp, SETUP_ID, {
                "retracement_percent": retracement_pct, "retracement_atr": retracement_atr,
                "pullback_bars": structure.pullback_bars,
            }))
            self.state = _State.IDLE
            self.structure = None
            return None

        depth_valid = p.pullback_minimum_retracement_percent <= retracement_pct <= p.pullback_maximum_retracement_percent
        self._xray(candle.timestamp, "retracement_percent", retracement_pct,
                  (p.pullback_minimum_retracement_percent, p.pullback_maximum_retracement_percent),
                  depth_valid, "Pullback depth as a percent of the measured impulse range")

        if structure.pullback_bars == 1:
            self._log(DiagnosticEvent("pullback_started", True, None, candle.timestamp, SETUP_ID, {
                "direction": structure.direction.value, "impulse_size": structure.impulse_size,
            }))

        distance_to_ema20 = candle.close - ema_fast
        distance_to_ema50 = candle.close - ema_slow

        if depth_valid:
            self._log(DiagnosticEvent("pullback_depth_valid", True, None, candle.timestamp, SETUP_ID, {
                "retracement_percent": retracement_pct, "retracement_atr": retracement_atr,
                "pullback_duration": structure.pullback_bars, "deepest_price": structure.deepest_price,
                "distance_to_ema20": distance_to_ema20, "distance_to_ema50": distance_to_ema50,
            }))
            signal = self._evaluate_confirmation(candle, structure, atr)
            if signal is not None:
                self.state = _State.IDLE
                self.structure = None
                return signal

        if structure.pullback_bars >= p.pullback_maximum_bars:
            self._log(DiagnosticEvent("pullback_rejected", False, "no confirmation within pullback window",
                                      candle.timestamp, SETUP_ID, {"pullback_bars": structure.pullback_bars,
                                                                    "retracement_percent": retracement_pct}))
            self.state = _State.IDLE
            self.structure = None
        return None

    def _evaluate_confirmation(self, candle: Candle, structure: _Structure, atr: float) -> Signal | None:
        p = self.params
        long = structure.direction is Direction.LONG

        body_pct = _body_percent(candle)
        close_location = _close_location_percent(candle)
        candle_range_atr = (candle.high - candle.low) / atr

        if body_pct is None or close_location is None:
            self._log(DiagnosticEvent("confirmation_rejected", False, "zero-range candle", candle.timestamp, SETUP_ID))
            return None

        directional_close = candle.close > candle.open if long else candle.close < candle.open
        location_ok = (close_location >= 1 - p.confirmation_close_location_percent if long
                       else close_location <= p.confirmation_close_location_percent)
        body_ok = body_pct >= p.confirmation_minimum_body_percent
        range_ok = candle_range_atr <= p.confirmation_maximum_range_atr

        self._xray(candle.timestamp, "confirmation_body_percent", body_pct, p.confirmation_minimum_body_percent,
                  body_ok, "Confirmation candle body as a percent of its range")
        self._xray(candle.timestamp, "confirmation_close_location", close_location,
                  p.confirmation_close_location_percent, location_ok, "Confirmation candle close location in its range")
        self._xray(candle.timestamp, "confirmation_range_atr", candle_range_atr, p.confirmation_maximum_range_atr,
                  range_ok, "Confirmation candle range in ATR")

        passed = directional_close and location_ok and body_ok and range_ok
        self._log(DiagnosticEvent(
            "confirmation_evaluated" if passed else "confirmation_rejected", passed,
            None if passed else "confirmation criteria not met", candle.timestamp, SETUP_ID, {
                "body_percent": body_pct, "close_location": close_location, "range_atr": candle_range_atr,
            },
        ))
        if not passed:
            return None

        return self._construct_entry(candle, structure, atr)

    def _construct_entry(self, candle: Candle, structure: _Structure, atr: float) -> Signal | None:
        p = self.params
        long = structure.direction is Direction.LONG

        if long:
            trigger = candle.high + p.entry_buffer_atr * atr
            stop = structure.deepest_price - p.stop_buffer_atr * atr
            stop_distance = trigger - stop
        else:
            trigger = candle.low - p.entry_buffer_atr * atr
            stop = structure.deepest_price + p.stop_buffer_atr * atr
            stop_distance = stop - trigger

        stop_atr = stop_distance / atr
        stop_ok = p.minimum_stop_atr <= stop_atr <= p.maximum_stop_atr
        self._xray(candle.timestamp, "stop_atr", stop_atr, (p.minimum_stop_atr, p.maximum_stop_atr),
                  stop_ok, "Structural stop distance in ATR")

        if not stop_ok:
            self._log(DiagnosticEvent("risk_stop_rejected", False, "stop distance outside safety range",
                                      candle.timestamp, SETUP_ID, {"stop_atr": stop_atr, "stop_distance": stop_distance}))
            return None

        self._log(DiagnosticEvent("risk_stop_valid", True, None, candle.timestamp, SETUP_ID, {
            "stop_atr": stop_atr, "stop_distance": stop_distance,
        }))

        signal = Signal.pending_stop(
            direction=structure.direction, pending_entry_price=trigger, pending_stop_price=stop,
            pending_expiry_bars=p.pending_expiry_bars, setup_id=SETUP_ID,
        )
        self._log(DiagnosticEvent("pending_order_created", True, None, candle.timestamp, SETUP_ID, {
            "trigger": trigger, "stop": stop, "expiry_bars": p.pending_expiry_bars,
        }))
        return signal
