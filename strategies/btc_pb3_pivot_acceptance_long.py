"""PB3 — BTC Confirmed Pivot Reclaim & Acceptance, LONG only (Phase A research).

Hypothesis. PB1 (REJECTED) produced plenty of trades but weak continuation
quality across regimes; PB2 (REJECTED) produced a strict acceptance gate that
demonstrably rejected losing setups on the long side, but its opportunity
generator — a 1.30-ATR displacement through a rolling 12-bar extreme — yielded
only 29 LONG trades in three years. PB3 keeps the proof-of-acceptance idea and
replaces the opportunity generator:

    H1 bullish context
    -> break of a *confirmed* M15 swing/pivot high
    -> retest of that actual pivot level
    -> strict reclaim
    -> strict next-bar acceptance
    -> stop entry above the acceptance bar

The research question is whether structural opportunities can be materially
increased without weakening the acceptance gate.

Independence. PB3 imports no PB1 or PB2 module, reuses none of their parameter
candidates or optimizer results, and leaves their sources untouched. It reuses
only generic platform infrastructure: the streaming Pine indicators, the
confirmed-H1 context helper, the diagnostics dataclasses and the audited
execution engine. The strict acceptance rule is re-expressed here as part of
PB3's own architecture rather than imported.

No-lookahead. A pivot does not exist for this strategy until both right-side
confirmation bars have completed, and pivot registration happens *after* the
current bar's decisions, so at any bar PB3 can only see pivots whose
confirmation timestamp is already in the past. See ``_observe_pivot``.

Only setup detection lives here. Fills, stops, targets, gaps and Bid/Ask
semantics stay in the audited engine; the fixed 3R target is applied by
BacktestSettings.risk_reward_ratio, so PB3 never sets take_profit.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pandas as pd

from engine.diagnostics import DiagnosticEvent, XRayEvaluation
from engine.models import CancelPendingOrder, Candle, Direction, ExecutionState, Signal
from strategies.base import Strategy
from strategies.confirmed_h1_regime import ConfirmedH1Regime
from strategies.pine_indicators import ATR, EMA

STRATEGY_ID = "BTC_PB3_PIVOT_ACCEPTANCE_LONG_V1"
SETUP_ID = "PB3_PIVOT_ACCEPTANCE_LONG"


@dataclass(frozen=True)
class PB3Parameters:
    """Typed Phase A baseline. Every value below stays at its default: Phase A
    runs exactly one backtest and zero optimization."""

    # H1 context (section 4)
    h1_fast_ema: int = 50
    h1_slow_ema: int = 200
    h1_atr_length: int = 14
    h1_slope_lookback: int = 4

    # M15 indicators
    m15_atr_length: int = 14
    m15_ema20_length: int = 20
    m15_ema50_length: int = 50

    # Confirmed pivot (section 5)
    pivot_left_bars: int = 2
    pivot_right_bars: int = 2
    maximum_pivot_age_bars: int = 24

    # Breakout candle (section 6)
    breakout_minimum_range_atr: float = 1.00
    breakout_minimum_body_percent: float = 0.60
    breakout_close_location_percent: float = 0.30

    # Retest (section 8)
    retest_tolerance_atr: float = 0.15
    retest_maximum_bars: int = 6

    # Reclaim (section 10)
    reclaim_minimum_body_percent: float = 0.50
    reclaim_close_location_percent: float = 0.35
    reclaim_maximum_range_atr: float = 2.00

    # Entry (section 12)
    entry_buffer_atr: float = 0.05
    pending_expiry_bars: int = 2

    # Stop (section 13)
    stop_buffer_atr: float = 0.20
    minimum_stop_atr: float = 0.50
    maximum_stop_atr: float = 2.50

    # Target (section 14) — informational. The audited engine applies the fixed
    # R multiple via BacktestSettings.risk_reward_ratio; PB3 never sets a target.
    reward_multiple: float = 3.0

    def __post_init__(self) -> None:
        lengths = (self.h1_fast_ema, self.h1_slow_ema, self.h1_atr_length, self.h1_slope_lookback,
                   self.m15_atr_length, self.m15_ema20_length, self.m15_ema50_length,
                   self.pivot_left_bars, self.pivot_right_bars, self.maximum_pivot_age_bars,
                   self.retest_maximum_bars, self.pending_expiry_bars)
        if min(lengths) < 1:
            raise ValueError("All lengths, lookbacks and windows must be positive integers.")
        if self.h1_fast_ema >= self.h1_slow_ema:
            raise ValueError("h1_fast_ema must be faster (smaller) than h1_slow_ema.")
        if self.m15_ema20_length >= self.m15_ema50_length:
            raise ValueError("m15_ema20_length must be faster (smaller) than m15_ema50_length.")
        # A pivot is usable no earlier than pivot_right_bars + 1 bars after it
        # formed, so an age cap below that could never admit any pivot.
        if self.maximum_pivot_age_bars <= self.pivot_right_bars:
            raise ValueError("maximum_pivot_age_bars must exceed pivot_right_bars.")
        if self.breakout_minimum_range_atr <= 0:
            raise ValueError("breakout_minimum_range_atr must be positive.")
        if not (0 < self.breakout_minimum_body_percent <= 1):
            raise ValueError("breakout_minimum_body_percent must be within (0, 1].")
        if not (0 < self.breakout_close_location_percent < 0.5):
            raise ValueError("breakout_close_location_percent must be within (0, 0.5).")
        if self.retest_tolerance_atr < 0:
            raise ValueError("retest_tolerance_atr must be non-negative.")
        if not (0 < self.reclaim_minimum_body_percent <= 1):
            raise ValueError("reclaim_minimum_body_percent must be within (0, 1].")
        if not (0 < self.reclaim_close_location_percent < 0.5):
            raise ValueError("reclaim_close_location_percent must be within (0, 0.5).")
        if self.reclaim_maximum_range_atr <= 0:
            raise ValueError("reclaim_maximum_range_atr must be positive.")
        if self.entry_buffer_atr < 0 or self.stop_buffer_atr < 0:
            raise ValueError("ATR buffers must be non-negative.")
        if not (0 < self.minimum_stop_atr < self.maximum_stop_atr):
            raise ValueError("Stop ATR bounds must satisfy 0 < minimum < maximum.")
        if self.reward_multiple <= 0:
            raise ValueError("reward_multiple must be positive.")


#: Parameters a later phase could plausibly search. Declared so the typed schema
#: records the intent; Phase A runs zero optimization and the research policy in
#: reports/pb3/PHASE_A_BASELINE.md governs whether a search is ever permitted.
TUNABLE_PARAMETERS: tuple[str, ...] = (
    "pivot_left_bars", "pivot_right_bars", "maximum_pivot_age_bars",
    "breakout_minimum_range_atr", "breakout_minimum_body_percent",
    "breakout_close_location_percent", "retest_tolerance_atr", "retest_maximum_bars",
    "reclaim_minimum_body_percent", "reclaim_close_location_percent",
    "reclaim_maximum_range_atr", "entry_buffer_atr", "stop_buffer_atr",
    "minimum_stop_atr", "maximum_stop_atr",
)


class PB3State(str, Enum):
    SEARCHING_PIVOT_BREAKOUT = "SEARCHING_PIVOT_BREAKOUT"
    WAITING_RETEST = "WAITING_RETEST"
    WAITING_RECLAIM = "WAITING_RECLAIM"
    WAITING_ACCEPTANCE = "WAITING_ACCEPTANCE"
    PENDING_ENTRY = "PENDING_ENTRY"
    IN_TRADE = "IN_TRADE"


@dataclass
class _Pivot:
    """A swing high that has completed both right-side confirmation bars."""
    price: float
    timestamp: pd.Timestamp
    confirmation_timestamp: pd.Timestamp
    bar_index: int


@dataclass
class _Structure:
    """One breakout of one confirmed pivot, and what the sequence has proven."""
    pivot_price: float
    pivot_timestamp: pd.Timestamp
    pivot_confirmation_timestamp: pd.Timestamp
    pivot_age_bars: int
    pivot_distance_atr: float
    breakout_time: pd.Timestamp
    breakout_high: float
    breakout_low: float
    breakout_range_atr: float
    breakout_body_percent: float
    breakout_close_location: float
    breakout_distance_atr: float
    bars_since_breakout: int = 0
    retested: bool = False
    bars_to_retest: int | None = None
    retest_low: float | None = None
    retest_overshoot_atr: float | None = None
    maximum_retracement_atr: float | None = None
    same_bar_retest_reclaim: bool = False
    reclaim_time: pd.Timestamp | None = None
    reclaim_close: float | None = None
    reclaim_body_percent: float | None = None
    reclaim_close_location: float | None = None
    reclaim_range_atr: float | None = None
    reclaim_distance_atr: float | None = None
    # Lowest completed low across the retest, reclaim and acceptance bars —
    # the structural stop anchor of section 13.
    stop_anchor: float | None = None
    anchor_bars: int = 0


def body_percent(candle: Candle) -> float | None:
    """Body as a share of range; ``None`` for a zero-range candle."""
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return None
    return abs(candle.close - candle.open) / candle_range


def close_location_percent(candle: Candle) -> float | None:
    """0.0 = closed at the low, 1.0 = closed at the high; ``None`` if zero range."""
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return None
    return (candle.close - candle.low) / candle_range


class BtcPB3PivotAcceptanceLong(Strategy):
    """LONG-only confirmed-pivot reclaim/acceptance continuation."""

    direction = Direction.LONG
    strategy_id = STRATEGY_ID
    setup_id = SETUP_ID

    def __init__(self, params: PB3Parameters | None = None) -> None:
        self.params = params or PB3Parameters()
        self.diagnostic_events: list[DiagnosticEvent] = []
        self.xray_evaluations: list[XRayEvaluation] = []
        self.reset()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        p = self.params
        self.h1 = ConfirmedH1Regime(p.h1_fast_ema, p.h1_slow_ema, p.h1_atr_length, p.h1_slope_lookback)
        self.ema20 = EMA(p.m15_ema20_length)
        self.ema50 = EMA(p.m15_ema50_length)
        self.atr = ATR(p.m15_atr_length)
        self.state = PB3State.SEARCHING_PIVOT_BREAKOUT
        self.structure: _Structure | None = None
        self.active_pivot: _Pivot | None = None
        self.execution_state: ExecutionState | None = None
        self._bar_index = 0
        self._pivot_window: deque[tuple[int, Candle]] = deque(
            maxlen=p.pivot_left_bars + p.pivot_right_bars + 1)
        self._h1_fast_history: deque[float] = deque(maxlen=p.h1_slope_lookback + 1)
        self._h1_last_hour: pd.Timestamp | None = None
        self._tracked_pending_setup: str | None = None
        self._trade_start: pd.Timestamp | None = getattr(self, "_trade_start", None)
        self.diagnostic_events = []
        self.xray_evaluations = []

    def on_data_gap(self) -> None:
        # A gap breaks bar adjacency, so every pivot candidate straddling it
        # would be meaningless. Indicators, pivots and structure all restart.
        self.reset()

    def on_backtest_window(self, start: pd.Timestamp | None, end: pd.Timestamp | None) -> None:
        # The engine discards any signal emitted before the warmup boundary, so
        # recording it lets the funnel separate rule decisions that could
        # actually become orders from those the engine was always going to drop.
        self._trade_start = start

    def on_execution_state(self, state: ExecutionState) -> None:
        # DiagnosticStrategyObserver already emits the generic "trade_entered"
        # and "trade_exited" stages for every strategy, and the audited engine
        # counts entries from them. Re-emitting either here would double-count
        # them and break the entries/closed-trades reconciliation (a bug found
        # during PB2), so PB3 only tracks the resulting state transitions.
        self.execution_state = state
        if state.opened_position is not None:
            self.state = PB3State.IN_TRADE
            # The tracked pending became a position; leaving it set would make
            # every later bar of the open trade look like an expiry.
            self._tracked_pending_setup = None
        if state.closed_trade is not None:
            self._reset_structure()
        if (self._tracked_pending_setup is not None and state.pending_order is None
                and state.position is None and state.opened_position is None
                and state.closed_trade is None):
            self._log("pending_expired", False, "expiry reached without a trigger", None, None)
            self._tracked_pending_setup = None
            self._reset_structure()
        if state.pending_order is not None:
            self._tracked_pending_setup = state.pending_order.setup_id
            self.state = PB3State.PENDING_ENTRY

    # ------------------------------------------------------------------
    # diagnostics (records what the rules decided; never decides anything)
    # ------------------------------------------------------------------

    def _log(self, stage: str, passed: bool | None, reason: str | None,
             timestamp: pd.Timestamp | None, metadata: dict[str, Any] | None = None) -> None:
        self.diagnostic_events.append(
            DiagnosticEvent(stage, passed, reason, timestamp, self.setup_id, metadata))

    def _xray(self, timestamp: pd.Timestamp, rule: str, observed: Any, threshold: Any,
              passed: bool, description: str) -> None:
        self.xray_evaluations.append(XRayEvaluation(
            timestamp=timestamp, strategy_id=self.strategy_id, component=self.setup_id, rule=rule,
            observed_value=observed, threshold=threshold, result="PASS" if passed else "FAIL",
            reason_code=rule.upper(), description=description,
        ))

    def _reset_structure(self) -> None:
        self.state = PB3State.SEARCHING_PIVOT_BREAKOUT
        self.structure = None

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------

    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        regime = self.h1.update(candle)
        if regime.hour is not None and regime.hour != self._h1_last_hour:
            self._h1_last_hour = regime.hour
            self._h1_fast_history.append(regime.fast_ema)
        ema20 = self.ema20.update(candle.close)
        ema50 = self.ema50.update(candle.close)
        atr = self.atr.update(candle)

        self._bar_index += 1
        signal = self._evaluate(candle, regime, atr, ema20, ema50)
        # Pivot registration happens last, so a pivot confirmed by *this* bar is
        # not visible to this bar's own decision. That is the no-lookahead
        # guarantee of section 17: at any bar, only pivots whose confirmation
        # timestamp is strictly in the past can be used.
        self._observe_pivot(candle)
        return signal

    def _evaluate(self, candle: Candle, regime, atr: float | None,
                  ema20: float | None, ema50: float | None) -> Signal | None:
        if atr is None or atr <= 0:
            return None
        if self._has_open_exposure():
            return None
        if self.state is PB3State.SEARCHING_PIVOT_BREAKOUT:
            self._search_breakout(candle, regime, atr, ema20, ema50)
            return None
        if self.state in (PB3State.WAITING_RETEST, PB3State.WAITING_RECLAIM):
            self._advance_retest_and_reclaim(candle, atr, ema20, ema50)
            return None
        if self.state is PB3State.WAITING_ACCEPTANCE:
            return self._evaluate_acceptance(candle, atr)
        return None

    def _has_open_exposure(self) -> bool:
        state = self.execution_state
        return bool(state and (state.pending_order is not None or state.position is not None))

    # ------------------------------------------------------------------
    # section 5: confirmed M15 pivot highs
    # ------------------------------------------------------------------

    def _observe_pivot(self, candle: Candle) -> None:
        """Append the completed bar and register a pivot if one just confirmed.

        The candidate sits ``pivot_right_bars`` back from the newest bar, so it
        is evaluated only once both of its right-side bars exist. Ties are
        resolved deterministically: strictly greater than both left bars, and
        greater-or-equal to both right bars. On a flat triple high only the
        leftmost bar qualifies (the next bar fails its own strict left test), so
        one plateau can never register two pivots.
        """
        p = self.params
        self._pivot_window.append((self._bar_index, candle))
        if len(self._pivot_window) < self._pivot_window.maxlen:
            return
        window = list(self._pivot_window)
        candidate_index, candidate = window[p.pivot_left_bars]
        left = window[:p.pivot_left_bars]
        right = window[p.pivot_left_bars + 1:]
        if not all(candidate.high > bar.high for _, bar in left):
            return
        if not all(candidate.high >= bar.high for _, bar in right):
            return
        self.active_pivot = _Pivot(
            price=candidate.high, timestamp=candidate.timestamp,
            confirmation_timestamp=candle.timestamp, bar_index=candidate_index,
        )
        self._log("pivot_confirmed", True, None, candle.timestamp, {
            "pivot_price": candidate.high,
            "pivot_timestamp": str(candidate.timestamp),
            "pivot_confirmation_timestamp": str(candle.timestamp),
            "left_bars": p.pivot_left_bars, "right_bars": p.pivot_right_bars,
        })

    def _usable_pivot(self, candle: Candle) -> _Pivot | None:
        """The latest confirmed pivot, if it is still within the age cap."""
        p = self.params
        pivot = self.active_pivot
        if pivot is None:
            return None
        age = self._bar_index - pivot.bar_index
        if age > p.maximum_pivot_age_bars:
            self._log("pivot_expired", False, "pivot older than the maximum age",
                      candle.timestamp, {"pivot_price": pivot.price,
                                         "pivot_timestamp": str(pivot.timestamp),
                                         "pivot_age_bars": age,
                                         "maximum_pivot_age_bars": p.maximum_pivot_age_bars})
            self.active_pivot = None
            return None
        return pivot

    # ------------------------------------------------------------------
    # section 4: H1 context
    # ------------------------------------------------------------------

    def _h1_fast_slope(self) -> float | None:
        if len(self._h1_fast_history) < self._h1_fast_history.maxlen:
            return None
        return self._h1_fast_history[-1] - self._h1_fast_history[0]

    def _evaluate_context(self, candle: Candle, regime) -> dict[str, Any] | None:
        """Baseline context is the H1 EMA50 > EMA200 ordering only.

        Separation and both slopes are measured and recorded, but Phase A
        deliberately applies no threshold to them.
        """
        if regime.fast_ema is None or regime.slow_ema is None or regime.atr is None:
            self._log("context_rejected", False, "H1 regime not yet warmed up", candle.timestamp)
            return None
        fast_slope = self._h1_fast_slope()
        context = {
            "separation_atr": regime.separation_atr,
            "fast_slope_atr": (fast_slope / regime.atr) if fast_slope is not None and regime.atr else None,
            "slow_slope_atr": (regime.slope / regime.atr) if regime.slope is not None and regime.atr else None,
            "h1_atr": regime.atr,
        }
        if not regime.fast_ema > regime.slow_ema:
            self._log("context_rejected", False, "H1 EMA50 not above EMA200",
                      candle.timestamp, context)
            return None
        self._log("context_evaluated", True, None, candle.timestamp, context)
        return context

    # ------------------------------------------------------------------
    # sections 6-7: breakout of the confirmed pivot
    # ------------------------------------------------------------------

    def _search_breakout(self, candle: Candle, regime, atr: float,
                         ema20: float | None, ema50: float | None) -> None:
        p = self.params
        context = self._evaluate_context(candle, regime)
        if context is None:
            return
        pivot = self._usable_pivot(candle)
        if pivot is None:
            return

        age = self._bar_index - pivot.bar_index
        pivot_distance_atr = (candle.close - pivot.price) / atr
        bullish = candle.close > candle.open
        broke_pivot = candle.close > pivot.price
        self._log("breakout_evaluated", True, None, candle.timestamp, {
            "pivot_price": pivot.price, "pivot_age_bars": age,
            "pivot_timestamp": str(pivot.timestamp),
            # Recorded on every evaluation, not just confirmations, so the
            # no-lookahead invariant (confirmation strictly before the decision
            # bar) is checkable over an entire run, not only over entries.
            "pivot_confirmation_timestamp": str(pivot.confirmation_timestamp),
            "pivot_distance_atr": pivot_distance_atr,
            "bullish": bullish, "broke_pivot": broke_pivot,
        })

        if not bullish:
            self._log("breakout_rejected", False, "candle not bullish", candle.timestamp,
                      {"pivot_price": pivot.price})
            return
        if not broke_pivot:
            self._log("breakout_rejected", False, "close did not break the pivot high",
                      candle.timestamp, {"pivot_price": pivot.price, "close": candle.close})
            return

        body = body_percent(candle)
        location = close_location_percent(candle)
        if body is None or location is None:
            self._log("breakout_rejected", False, "zero-range candle", candle.timestamp)
            return

        range_atr = (candle.high - candle.low) / atr
        breakout_distance_atr = (candle.close - pivot.price) / atr

        range_ok = range_atr >= p.breakout_minimum_range_atr
        body_ok = body >= p.breakout_minimum_body_percent
        location_ok = location >= 1.0 - p.breakout_close_location_percent

        self._xray(candle.timestamp, "breakout_range_atr", range_atr,
                   p.breakout_minimum_range_atr, range_ok, "Breakout candle range in ATR")
        self._xray(candle.timestamp, "breakout_body_percent", body,
                   p.breakout_minimum_body_percent, body_ok,
                   "Breakout body as a share of its range")
        self._xray(candle.timestamp, "breakout_close_location", location,
                   1.0 - p.breakout_close_location_percent, location_ok,
                   "Breakout close location within its range (1.0 = at the high)")
        self._xray(candle.timestamp, "breakout_distance_atr", breakout_distance_atr, None, True,
                   "Breakout close beyond the confirmed pivot high, in ATR")

        if not (range_ok and body_ok and location_ok):
            reason = ("insufficient range" if not range_ok
                      else "insufficient body" if not body_ok else "close not in the upper range")
            self._log("breakout_rejected", False, reason, candle.timestamp,
                      {"range_atr": range_atr, "body_percent": body, "close_location": location,
                       "pivot_price": pivot.price})
            return

        self._xray(candle.timestamp, "h1_context_long", True, None, True,
                   "H1 EMA50 above EMA200 required by this component")
        self._xray(candle.timestamp, "h1_separation_atr", context["separation_atr"], None, True,
                   "abs(H1 EMA50 - H1 EMA200) / H1 ATR (diagnostic only in Phase A)")
        self._xray(candle.timestamp, "h1_fast_slope_atr", context["fast_slope_atr"], None, True,
                   "H1 EMA50 slope over the slope lookback / H1 ATR (diagnostic only)")
        self._xray(candle.timestamp, "h1_slow_slope_atr", context["slow_slope_atr"], None, True,
                   "H1 EMA200 slope over the slope lookback / H1 ATR (diagnostic only)")
        self._xray(candle.timestamp, "pivot_price", pivot.price, None, True,
                   "Confirmed M15 swing high the breakout traded through")
        self._xray(candle.timestamp, "pivot_age_bars", age, p.maximum_pivot_age_bars, True,
                   "Completed M15 bars from the pivot bar to the breakout")
        self._xray(candle.timestamp, "pivot_distance_atr", pivot_distance_atr, None, True,
                   "Distance from the breakout close to the pivot level, in ATR")

        self.structure = _Structure(
            pivot_price=pivot.price, pivot_timestamp=pivot.timestamp,
            pivot_confirmation_timestamp=pivot.confirmation_timestamp,
            pivot_age_bars=age, pivot_distance_atr=pivot_distance_atr,
            breakout_time=candle.timestamp, breakout_high=candle.high, breakout_low=candle.low,
            breakout_range_atr=range_atr, breakout_body_percent=body,
            breakout_close_location=location, breakout_distance_atr=breakout_distance_atr,
        )
        # Section 7: one confirmed pivot may produce at most one PB3 structure
        # attempt. Dropping it here means only a newly confirmed pivot can start
        # the next structure, whatever happens to this one.
        self.active_pivot = None
        self.state = PB3State.WAITING_RETEST
        self._log("breakout_confirmed", True, None, candle.timestamp, {
            "pivot_price": pivot.price, "pivot_timestamp": str(pivot.timestamp),
            "pivot_confirmation_timestamp": str(pivot.confirmation_timestamp),
            "pivot_age_bars": age, "range_atr": range_atr, "body_percent": body,
            "close_location": location, "breakout_distance_atr": breakout_distance_atr,
            "breakout_high": candle.high, "breakout_low": candle.low,
            "distance_to_ema20": (candle.close - ema20) if ema20 is not None else None,
            "distance_to_ema50": (candle.close - ema50) if ema50 is not None else None,
        })
        self._log("waiting_retest", True, None, candle.timestamp,
                  {"maximum_bars": p.retest_maximum_bars, "pivot_price": pivot.price})

    # ------------------------------------------------------------------
    # sections 8-10: retest, invalidation and reclaim
    # ------------------------------------------------------------------

    def _advance_retest_and_reclaim(self, candle: Candle, atr: float,
                                    ema20: float | None, ema50: float | None) -> None:
        p = self.params
        structure = self.structure
        assert structure is not None
        structure.bars_since_breakout += 1

        # Section 9: a completed close back below the breakout candle low
        # destroys the premise before anything else is considered.
        if candle.close < structure.breakout_low:
            self._log("structure_invalidated", False, "close below the breakout candle low",
                      candle.timestamp, {"close": candle.close,
                                         "breakout_low": structure.breakout_low,
                                         "breakout_time": str(structure.breakout_time),
                                         "bars_since_breakout": structure.bars_since_breakout})
            self._reset_structure()
            return

        retracement = (structure.breakout_high - candle.low) / atr
        structure.maximum_retracement_atr = max(structure.maximum_retracement_atr or 0.0,
                                                retracement)

        if not structure.retested:
            tolerance = p.retest_tolerance_atr * atr
            if candle.low <= structure.pivot_price + tolerance:
                overshoot = (structure.pivot_price - candle.low) / atr
                structure.retested = True
                structure.bars_to_retest = structure.bars_since_breakout
                structure.retest_low = candle.low
                structure.retest_overshoot_atr = overshoot
                structure.stop_anchor = candle.low
                structure.anchor_bars = 1
                self.state = PB3State.WAITING_RECLAIM
                self._xray(candle.timestamp, "bars_to_retest", structure.bars_to_retest,
                           p.retest_maximum_bars, True, "Completed bars from breakout to retest")
                self._xray(candle.timestamp, "retest_overshoot_atr", overshoot,
                           p.retest_tolerance_atr, True,
                           "Retest low beyond the pivot level, in ATR (negative = never reached it)")
                self._log("retest_detected", True, None, candle.timestamp, {
                    "bars_to_retest": structure.bars_to_retest, "retest_low": candle.low,
                    "retest_overshoot_atr": overshoot,
                    "maximum_retracement_atr": structure.maximum_retracement_atr,
                    "pivot_price": structure.pivot_price,
                    "distance_to_ema20": (candle.close - ema20) if ema20 is not None else None,
                    "distance_to_ema50": (candle.close - ema50) if ema50 is not None else None,
                })

        if structure.retested:
            # A bar that both retests and reclaims is allowed: the close is by
            # construction the last price of the bar, so a low inside the retest
            # tolerance necessarily precedes a reclaiming close. No intrabar path
            # has to be invented. Acceptance still requires the *following* bar,
            # so the sequence can never collapse into a single candle.
            same_bar = structure.bars_to_retest == structure.bars_since_breakout
            if self._evaluate_reclaim(candle, structure, atr):
                structure.same_bar_retest_reclaim = same_bar
                return

        if structure.bars_since_breakout >= p.retest_maximum_bars:
            self._log("retest_expired", False,
                      "no reclaim within the retest window" if structure.retested
                      else "pivot level never retested",
                      candle.timestamp, {"bars_since_breakout": structure.bars_since_breakout,
                                         "breakout_time": str(structure.breakout_time),
                                         "retested": structure.retested})
            self._reset_structure()

    def _evaluate_reclaim(self, candle: Candle, structure: _Structure, atr: float) -> bool:
        p = self.params
        body = body_percent(candle)
        location = close_location_percent(candle)
        if body is None or location is None:
            self._log("reclaim_rejected", False, "zero-range candle", candle.timestamp)
            return False

        range_atr = (candle.high - candle.low) / atr
        bullish = candle.close > candle.open
        beyond_level = candle.close > structure.pivot_price
        body_ok = body >= p.reclaim_minimum_body_percent
        location_ok = location >= 1.0 - p.reclaim_close_location_percent
        range_ok = range_atr <= p.reclaim_maximum_range_atr

        self._log("reclaim_evaluated", True, None, candle.timestamp,
                  {"body_percent": body, "close_location": location,
                   "range_atr": range_atr, "beyond_level": beyond_level})
        self._xray(candle.timestamp, "reclaim_body_percent", body, p.reclaim_minimum_body_percent,
                   body_ok, "Reclaim candle body as a share of its range")
        self._xray(candle.timestamp, "reclaim_close_location", location,
                   1.0 - p.reclaim_close_location_percent, location_ok,
                   "Reclaim close location within its range (1.0 = at the high)")
        self._xray(candle.timestamp, "reclaim_range_atr", range_atr, p.reclaim_maximum_range_atr,
                   range_ok, "Reclaim candle range in ATR")

        if not (bullish and beyond_level and body_ok and location_ok and range_ok):
            reason = ("candle not bullish" if not bullish
                      else "close did not reclaim the pivot level" if not beyond_level
                      else "insufficient body" if not body_ok
                      else "close not in the upper range" if not location_ok
                      else "range too wide")
            self._log("reclaim_rejected", False, reason, candle.timestamp,
                      {"body_percent": body, "close_location": location, "range_atr": range_atr})
            return False

        distance_atr = (candle.close - structure.pivot_price) / atr
        structure.reclaim_time = candle.timestamp
        structure.reclaim_close = candle.close
        structure.reclaim_body_percent = body
        structure.reclaim_close_location = location
        structure.reclaim_range_atr = range_atr
        structure.reclaim_distance_atr = distance_atr
        self._extend_anchor(candle, structure)
        self.state = PB3State.WAITING_ACCEPTANCE
        self._xray(candle.timestamp, "reclaim_distance_atr", distance_atr, 0.0, True,
                   "Reclaim close beyond the pivot level, in ATR")
        self._log("reclaim_confirmed", True, None, candle.timestamp, {
            "body_percent": body, "close_location": location, "range_atr": range_atr,
            "reclaim_close": candle.close, "reclaim_distance_atr": distance_atr,
            "pivot_price": structure.pivot_price,
            "breakout_time": str(structure.breakout_time),
        })
        return True

    def _extend_anchor(self, candle: Candle, structure: _Structure) -> None:
        """Track the structural stop anchor across retest/reclaim/acceptance bars."""
        if structure.stop_anchor is None:
            structure.stop_anchor = candle.low
        else:
            structure.stop_anchor = min(structure.stop_anchor, candle.low)
        structure.anchor_bars += 1

    # ------------------------------------------------------------------
    # sections 11-13: acceptance, risk and the pending entry
    # ------------------------------------------------------------------

    def _evaluate_acceptance(self, candle: Candle, atr: float) -> Signal | None:
        structure = self.structure
        assert structure is not None and structure.reclaim_close is not None

        # Section 9 invalidation runs until entry, so it also guards the
        # acceptance bar. It is not redundant with the acceptance test: when the
        # breakout candle's low sits above the reclaim close, a bar can satisfy
        # acceptance and still have closed back through the breakout candle.
        if candle.close < structure.breakout_low:
            self._log("structure_invalidated", False, "close below the breakout candle low",
                      candle.timestamp, {"close": candle.close,
                                         "breakout_low": structure.breakout_low,
                                         "breakout_time": str(structure.breakout_time),
                                         "bars_since_breakout": structure.bars_since_breakout + 1})
            self._reset_structure()
            return None

        beyond_level = candle.close > structure.pivot_price
        held_reclaim = candle.close >= structure.reclaim_close
        distance_atr = (candle.close - structure.pivot_price) / atr
        range_atr = (candle.high - candle.low) / atr
        change_atr = (candle.close - structure.reclaim_close) / atr

        self._log("acceptance_evaluated", True, None, candle.timestamp, {
            "beyond_level": beyond_level, "held_reclaim": held_reclaim,
            "acceptance_distance_atr": distance_atr, "acceptance_range_atr": range_atr,
            "reclaim_to_acceptance_atr": change_atr,
            "breakout_time": str(structure.breakout_time),
        })
        self._xray(candle.timestamp, "acceptance_distance_atr", distance_atr, 0.0, beyond_level,
                   "Acceptance close beyond the pivot level, in ATR")
        self._xray(candle.timestamp, "acceptance_range_atr", range_atr, None, True,
                   "Acceptance candle range in ATR (unfiltered in Phase A)")
        self._xray(candle.timestamp, "reclaim_to_acceptance_atr", change_atr, 0.0, held_reclaim,
                   "Acceptance close minus reclaim close, in ATR")

        # Section 11: exactly the next completed bar decides. There is no second
        # chance and no multi-bar acceptance window.
        if not (beyond_level and held_reclaim):
            self._log("acceptance_failed", False,
                      "close fell back through the pivot level" if not beyond_level
                      else "close did not hold the reclaim close",
                      candle.timestamp, {"acceptance_close": candle.close,
                                         "pivot_price": structure.pivot_price,
                                         "reclaim_close": structure.reclaim_close,
                                         "beyond_level": beyond_level,
                                         "held_reclaim": held_reclaim,
                                         "breakout_time": str(structure.breakout_time)})
            self._reset_structure()
            return None

        self._extend_anchor(candle, structure)
        self._log("acceptance_confirmed", True, None, candle.timestamp, {
            "acceptance_distance_atr": distance_atr, "acceptance_range_atr": range_atr,
            "reclaim_to_acceptance_atr": change_atr, "acceptance_close": candle.close,
            "breakout_time": str(structure.breakout_time),
        })
        return self._construct_entry(candle, structure, atr)

    def _construct_entry(self, candle: Candle, structure: _Structure, atr: float) -> Signal | None:
        p = self.params
        assert structure.stop_anchor is not None
        trigger = candle.high + p.entry_buffer_atr * atr
        stop = structure.stop_anchor - p.stop_buffer_atr * atr
        stop_distance = trigger - stop
        stop_atr = stop_distance / atr
        stop_ok = p.minimum_stop_atr <= stop_atr <= p.maximum_stop_atr

        self._log("risk_evaluated", True, None, candle.timestamp,
                  {"stop_atr": stop_atr, "stop_distance": stop_distance, "stop_price": stop,
                   "stop_anchor": structure.stop_anchor, "anchor_bars": structure.anchor_bars})
        self._xray(candle.timestamp, "stop_atr", stop_atr,
                   (p.minimum_stop_atr, p.maximum_stop_atr), stop_ok,
                   "Structural stop distance in ATR")

        if not stop_ok:
            self._log("risk_rejected", False, "stop distance outside the safety range",
                      candle.timestamp, {"stop_atr": stop_atr, "stop_distance": stop_distance})
            self._reset_structure()
            return None

        signal = Signal.pending_stop(
            direction=Direction.LONG, pending_entry_price=trigger, pending_stop_price=stop,
            pending_expiry_bars=p.pending_expiry_bars, setup_id=self.setup_id,
        )
        self._log("pending_created", True, None, candle.timestamp, {
            "trigger": trigger, "stop": stop, "stop_atr": stop_atr,
            "expiry_bars": p.pending_expiry_bars,
            "pivot_price": structure.pivot_price,
            "pivot_timestamp": str(structure.pivot_timestamp),
            "pivot_confirmation_timestamp": str(structure.pivot_confirmation_timestamp),
            "pivot_age_bars": structure.pivot_age_bars,
            "breakout_range_atr": structure.breakout_range_atr,
            "breakout_body_percent": structure.breakout_body_percent,
            "breakout_close_location": structure.breakout_close_location,
            "breakout_distance_atr": structure.breakout_distance_atr,
            "bars_to_retest": structure.bars_to_retest,
            "retest_overshoot_atr": structure.retest_overshoot_atr,
            "maximum_retracement_atr": structure.maximum_retracement_atr,
            "reclaim_body_percent": structure.reclaim_body_percent,
            "reclaim_close_location": structure.reclaim_close_location,
            "reclaim_range_atr": structure.reclaim_range_atr,
            "acceptance_distance_atr": (candle.close - structure.pivot_price) / atr,
            "acceptance_range_atr": (candle.high - candle.low) / atr,
            "same_bar_retest_reclaim": structure.same_bar_retest_reclaim,
            "breakout_time": str(structure.breakout_time),
            "reclaim_time": str(structure.reclaim_time),
            "before_trade_start": bool(self._trade_start is not None
                                       and candle.timestamp < self._trade_start),
        })
        # The structure is consumed: one breakout produces at most one pending
        # order, and the pivot behind it was already retired at breakout time.
        self.structure = None
        self.state = PB3State.PENDING_ENTRY
        return signal


__all__ = [
    "BtcPB3PivotAcceptanceLong", "PB3Parameters", "PB3State",
    "TUNABLE_PARAMETERS", "STRATEGY_ID", "SETUP_ID",
    "body_percent", "close_location_percent",
]
