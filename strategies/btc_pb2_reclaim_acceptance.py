"""PB2 — BTC Reclaim & Acceptance Continuation (Phase A research core).

Hypothesis: a continuation entry should require price to *prove* it can hold a
level it has broken, not merely to retrace by a percentage. The sequence is

    H1 trend context
    -> structural displacement through a prior M15 structure level
    -> retest of that broken level
    -> reclaim of the level
    -> one further bar of acceptance beyond it
    -> stop-entry above/below the acceptance bar

This module holds the direction-parameterised core shared by the two research
components (strategies/btc_pb2_reclaim_long.py and
strategies/btc_pb2_reclaim_short.py). Each component instantiates its own
object, so LONG and SHORT keep entirely independent state, structures, pending
orders and diagnostics; nothing is shared at runtime.

Deliberately unrelated to PB1 (BTC_PB1_SHALLOW_PULLBACK_V1, REJECTED): there is
no measured multi-candle impulse, no percentage retracement of a leg, and no
single confirmation candle that both confirms and triggers. PB2 keys every
decision off a *price level* and demands a separate acceptance bar. No PB1
module is imported and no PB1 parameter, candidate or filter is reused.

Only setup detection lives here. Fills, stops, targets, gaps and Bid/Ask
semantics stay in the audited engine; the 3R target is applied by the audited
engine's BacktestSettings.risk_reward_ratio, so PB2 never sets take_profit.
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


#: Architecture modes for the acceptance gate. STRICT is the Phase A baseline and
#: the default, so default behaviour is unchanged; the other two exist only so a
#: predeclared ablation can measure what the gate is actually doing. The mode is
#: part of PB2Parameters, so it participates in the effective-parameter
#: fingerprint and a variant run can never be mistaken for the baseline.
ACCEPTANCE_STRICT = "STRICT"
ACCEPTANCE_LEVEL_HOLD = "LEVEL_HOLD"
ACCEPTANCE_RECLAIM_ONLY = "RECLAIM_ONLY"
ACCEPTANCE_MODES = (ACCEPTANCE_STRICT, ACCEPTANCE_LEVEL_HOLD, ACCEPTANCE_RECLAIM_ONLY)


@dataclass(frozen=True)
class PB2Parameters:
    """Typed Phase A baseline. ``tunable`` marks plausible future search space;
    Phase A runs zero optimization and every value below stays at its default."""

    # H1 context (section 4)
    h1_fast_ema: int = 50
    h1_slow_ema: int = 200
    h1_atr_length: int = 14
    h1_slope_lookback: int = 4

    # M15 indicators
    m15_atr_length: int = 14
    m15_ema20_length: int = 20
    m15_ema50_length: int = 50

    # Prior structure (section 5)
    structure_lookback: int = 12

    # Displacement candle (section 6)
    displacement_minimum_range_atr: float = 1.30
    displacement_minimum_body_percent: float = 0.70
    displacement_close_location_percent: float = 0.20

    # Retest window (section 7)
    retest_tolerance_atr: float = 0.10
    retest_maximum_bars: int = 5

    # Reclaim candle (section 9)
    reclaim_minimum_body_percent: float = 0.50
    reclaim_close_location_percent: float = 0.35
    reclaim_maximum_range_atr: float = 2.00

    # Entry (section 11)
    entry_buffer_atr: float = 0.05
    pending_expiry_bars: int = 2

    # Stop (section 12)
    stop_buffer_atr: float = 0.20
    minimum_stop_atr: float = 0.50
    maximum_stop_atr: float = 2.50

    # Target (section 13) — informational; the audited engine applies the fixed
    # R multiple via BacktestSettings.risk_reward_ratio. PB2 never sets a target.
    reward_multiple: float = 3.0

    # Acceptance architecture. STRICT reproduces the Phase A baseline exactly.
    acceptance_mode: str = ACCEPTANCE_STRICT

    def __post_init__(self) -> None:
        lengths = (self.h1_fast_ema, self.h1_slow_ema, self.h1_atr_length, self.h1_slope_lookback,
                   self.m15_atr_length, self.m15_ema20_length, self.m15_ema50_length,
                   self.structure_lookback, self.retest_maximum_bars, self.pending_expiry_bars)
        if min(lengths) < 1:
            raise ValueError("All lengths, lookbacks and windows must be positive integers.")
        if self.h1_fast_ema >= self.h1_slow_ema:
            raise ValueError("h1_fast_ema must be faster (smaller) than h1_slow_ema.")
        if self.m15_ema20_length >= self.m15_ema50_length:
            raise ValueError("m15_ema20_length must be faster (smaller) than m15_ema50_length.")
        if self.displacement_minimum_range_atr <= 0:
            raise ValueError("displacement_minimum_range_atr must be positive.")
        if not (0 < self.displacement_minimum_body_percent <= 1):
            raise ValueError("displacement_minimum_body_percent must be within (0, 1].")
        if not (0 < self.displacement_close_location_percent < 0.5):
            raise ValueError("displacement_close_location_percent must be within (0, 0.5).")
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
        if self.acceptance_mode not in ACCEPTANCE_MODES:
            raise ValueError(f"acceptance_mode must be one of {ACCEPTANCE_MODES}.")


#: Parameters a later phase could plausibly search. Declared here so the typed
#: schema records the intent while Phase A still runs zero optimization.
TUNABLE_PARAMETERS: tuple[str, ...] = (
    "structure_lookback", "displacement_minimum_range_atr", "displacement_minimum_body_percent",
    "displacement_close_location_percent", "retest_tolerance_atr", "retest_maximum_bars",
    "reclaim_minimum_body_percent", "reclaim_close_location_percent", "reclaim_maximum_range_atr",
    "entry_buffer_atr", "stop_buffer_atr", "minimum_stop_atr", "maximum_stop_atr",
)


class PB2State(str, Enum):
    SEARCHING_DISPLACEMENT = "SEARCHING_DISPLACEMENT"
    WAITING_RETEST = "WAITING_RETEST"
    WAITING_RECLAIM = "WAITING_RECLAIM"
    WAITING_ACCEPTANCE = "WAITING_ACCEPTANCE"
    PENDING_ENTRY = "PENDING_ENTRY"
    IN_TRADE = "IN_TRADE"


@dataclass
class _Structure:
    """One displacement and everything the sequence has proven about it so far."""
    direction: Direction
    structure_level: float
    structure_start: pd.Timestamp
    structure_end: pd.Timestamp
    displacement_time: pd.Timestamp
    displacement_high: float
    displacement_low: float
    displacement_range_atr: float
    displacement_body_percent: float
    displacement_close_location: float
    breakout_distance_atr: float
    bars_since_displacement: int = 0
    retested: bool = False
    bars_to_retest: int | None = None
    retest_extreme: float | None = None
    retest_overshoot_atr: float | None = None
    maximum_adverse_excursion: float | None = None
    same_bar_retest_reclaim: bool = False
    reclaim_time: pd.Timestamp | None = None
    reclaim_close: float | None = None
    reclaim_body_percent: float | None = None
    reclaim_close_location: float | None = None
    reclaim_range_atr: float | None = None
    # Running extreme across the retest/reclaim/acceptance bars: the structural
    # stop anchor (lowest low for LONG, highest high for SHORT).
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


class PB2ReclaimAcceptance(Strategy):
    """Direction-parameterised reclaim/acceptance engine.

    Subclasses set ``direction``, ``strategy_id`` and ``setup_id``. Every
    comparison below is written once and mirrored by direction, so the LONG and
    SHORT components share one implementation and one set of indicator
    calculations without sharing any runtime state.
    """

    direction: Direction
    strategy_id: str
    setup_id: str

    def __init__(self, params: PB2Parameters | None = None) -> None:
        self.params = params or PB2Parameters()
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
        self.history: deque[Candle] = deque(maxlen=p.structure_lookback)
        self.state = PB2State.SEARCHING_DISPLACEMENT
        self.structure: _Structure | None = None
        self.execution_state: ExecutionState | None = None
        self._h1_fast_history: deque[float] = deque(maxlen=p.h1_slope_lookback + 1)
        self._h1_last_hour: pd.Timestamp | None = None
        self._tracked_pending_setup: str | None = None
        self._trade_start: pd.Timestamp | None = getattr(self, "_trade_start", None)
        self.diagnostic_events = []
        self.xray_evaluations = []

    def on_data_gap(self) -> None:
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
        # them and break the entries/closed-trades reconciliation, so PB2 only
        # tracks the resulting state transitions.
        self.execution_state = state
        if state.opened_position is not None:
            self.state = PB2State.IN_TRADE
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
            self.state = PB2State.PENDING_ENTRY

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
        self.state = PB2State.SEARCHING_DISPLACEMENT
        self.structure = None

    # ------------------------------------------------------------------
    # direction mirroring
    # ------------------------------------------------------------------

    @property
    def _long(self) -> bool:
        return self.direction is Direction.LONG

    def _beyond(self, price: float, level: float) -> bool:
        """Is ``price`` on the continuation side of ``level``?"""
        return price > level if self._long else price < level

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

        if atr is None or atr <= 0:
            self.history.append(candle)
            return None

        if self._has_open_exposure():
            self.history.append(candle)
            return None

        signal: Signal | None = None
        if self.state is PB2State.SEARCHING_DISPLACEMENT:
            self._search_displacement(candle, regime, atr, ema20, ema50)
        elif self.state in (PB2State.WAITING_RETEST, PB2State.WAITING_RECLAIM):
            # Under RECLAIM_ONLY the reclaim bar itself produces the entry, so
            # this branch can return a signal.
            signal = self._advance_retest_and_reclaim(candle, atr, ema20, ema50)
        elif self.state is PB2State.WAITING_ACCEPTANCE:
            signal = self._evaluate_acceptance(candle, atr)

        self.history.append(candle)
        return signal

    def _has_open_exposure(self) -> bool:
        state = self.execution_state
        return bool(state and (state.pending_order is not None or state.position is not None))

    # ------------------------------------------------------------------
    # section 4: H1 context
    # ------------------------------------------------------------------

    def _h1_fast_slope(self) -> float | None:
        if len(self._h1_fast_history) < self._h1_fast_history.maxlen:
            return None
        return self._h1_fast_history[-1] - self._h1_fast_history[0]

    def _evaluate_context(self, candle: Candle, regime) -> dict[str, Any] | None:
        """Baseline context is the EMA50/EMA200 ordering only.

        Separation and both slopes are measured and recorded, but Phase A
        deliberately applies no threshold to them.
        """
        if regime.fast_ema is None or regime.slow_ema is None or regime.atr is None:
            self._log("context_rejected", False, "H1 regime not yet warmed up", candle.timestamp)
            return None
        aligned = regime.fast_ema > regime.slow_ema if self._long else regime.fast_ema < regime.slow_ema
        fast_slope = self._h1_fast_slope()
        context = {
            "direction": self.direction.value,
            "separation_atr": regime.separation_atr,
            "fast_slope_atr": (fast_slope / regime.atr) if fast_slope is not None and regime.atr else None,
            "slow_slope_atr": (regime.slope / regime.atr) if regime.slope is not None and regime.atr else None,
            "h1_atr": regime.atr,
        }
        if not aligned:
            self._log("context_rejected", False, "H1 EMA50/EMA200 not aligned with this component",
                      candle.timestamp, context)
            return None
        self._log("context_evaluated", True, None, candle.timestamp, context)
        return context

    # ------------------------------------------------------------------
    # sections 5-6: prior structure and the displacement candle
    # ------------------------------------------------------------------

    def _search_displacement(self, candle: Candle, regime, atr: float,
                             ema20: float, ema50: float) -> None:
        p = self.params
        context = self._evaluate_context(candle, regime)
        if context is None:
            return
        if len(self.history) < p.structure_lookback:
            self._log("displacement_rejected", False, "insufficient structure history", candle.timestamp)
            return

        # The lookback is the bars *preceding* the displacement candle; the
        # candle under evaluation has not been appended to history yet.
        window = list(self.history)
        level = max(bar.high for bar in window) if self._long else min(bar.low for bar in window)

        directional = candle.close > candle.open if self._long else candle.close < candle.open
        broke_structure = self._beyond(candle.close, level)
        self._log("displacement_evaluated", True, None, candle.timestamp,
                  {"structure_level": level, "directional": directional,
                   "broke_structure": broke_structure})

        if not directional:
            self._log("displacement_rejected", False, "candle not directional", candle.timestamp,
                      {"structure_level": level})
            return
        if not broke_structure:
            self._log("displacement_rejected", False, "close did not break the structure level",
                      candle.timestamp, {"structure_level": level, "close": candle.close})
            return

        body = body_percent(candle)
        location = close_location_percent(candle)
        if body is None or location is None:
            self._log("displacement_rejected", False, "zero-range candle", candle.timestamp)
            return

        range_atr = (candle.high - candle.low) / atr
        breakout_distance_atr = abs(candle.close - level) / atr
        directional_location = location if self._long else 1.0 - location

        range_ok = range_atr >= p.displacement_minimum_range_atr
        body_ok = body >= p.displacement_minimum_body_percent
        location_ok = directional_location >= 1.0 - p.displacement_close_location_percent

        self._xray(candle.timestamp, "displacement_range_atr", range_atr,
                   p.displacement_minimum_range_atr, range_ok, "Displacement candle range in ATR")
        self._xray(candle.timestamp, "displacement_body_percent", body,
                   p.displacement_minimum_body_percent, body_ok,
                   "Displacement body as a share of its range")
        self._xray(candle.timestamp, "displacement_close_location", directional_location,
                   1.0 - p.displacement_close_location_percent, location_ok,
                   "Displacement close location within its range, oriented to the trade direction")
        self._xray(candle.timestamp, "breakout_distance_atr", breakout_distance_atr, None, True,
                   "Displacement close beyond the prior structure level, in ATR")

        if not (range_ok and body_ok and location_ok):
            reason = ("insufficient range" if not range_ok
                      else "insufficient body" if not body_ok else "close not at the extreme")
            self._log("displacement_rejected", False, reason, candle.timestamp,
                      {"range_atr": range_atr, "body_percent": body,
                       "close_location": directional_location})
            return

        self._xray(candle.timestamp, "h1_direction", self.direction.value, None, True,
                   "H1 EMA50 vs EMA200 ordering required by this component")
        self._xray(candle.timestamp, "h1_separation_atr", context["separation_atr"], None, True,
                   "abs(H1 EMA50 - H1 EMA200) / H1 ATR (diagnostic only in Phase A)")
        self._xray(candle.timestamp, "h1_fast_slope_atr", context["fast_slope_atr"], None, True,
                   "H1 EMA50 slope over the slope lookback / H1 ATR (diagnostic only)")
        self._xray(candle.timestamp, "h1_slow_slope_atr", context["slow_slope_atr"], None, True,
                   "H1 EMA200 slope over the slope lookback / H1 ATR (diagnostic only)")
        self._xray(candle.timestamp, "structure_level", level, None, True,
                   "Prior structure extreme over the lookback preceding the displacement")

        self.structure = _Structure(
            direction=self.direction, structure_level=level,
            structure_start=window[0].timestamp, structure_end=window[-1].timestamp,
            displacement_time=candle.timestamp, displacement_high=candle.high,
            displacement_low=candle.low, displacement_range_atr=range_atr,
            displacement_body_percent=body, displacement_close_location=directional_location,
            breakout_distance_atr=breakout_distance_atr,
        )
        self.state = PB2State.WAITING_RETEST
        self._log("structure_level_created", True, None, candle.timestamp,
                  {"structure_level": level, "structure_start": str(window[0].timestamp),
                   "structure_end": str(window[-1].timestamp),
                   "distance_to_ema20": candle.close - ema20,
                   "distance_to_ema50": candle.close - ema50})
        self._log("displacement_detected", True, None, candle.timestamp, {
            "structure_level": level, "range_atr": range_atr, "body_percent": body,
            "close_location": directional_location, "breakout_distance_atr": breakout_distance_atr,
            "displacement_high": candle.high, "displacement_low": candle.low,
        })
        self._log("waiting_retest", True, None, candle.timestamp,
                  {"maximum_bars": p.retest_maximum_bars})

    # ------------------------------------------------------------------
    # sections 7-9: retest, invalidation and reclaim
    # ------------------------------------------------------------------

    def _advance_retest_and_reclaim(self, candle: Candle, atr: float,
                                    ema20: float, ema50: float) -> Signal | None:
        p = self.params
        structure = self.structure
        assert structure is not None
        structure.bars_since_displacement += 1

        # Section 8: a completed close back through the displacement candle
        # destroys the premise before anything else is considered.
        destroyed = (candle.close < structure.displacement_low if self._long
                     else candle.close > structure.displacement_high)
        if destroyed:
            self._log("structure_invalidated", False, "close beyond the displacement candle extreme",
                      candle.timestamp, {"close": candle.close,
                                         "displacement_low": structure.displacement_low,
                                         "displacement_high": structure.displacement_high,
                                         "displacement_time": str(structure.displacement_time),
                                         "bars_since_displacement": structure.bars_since_displacement})
            self._reset_structure()
            return None

        adverse = (structure.displacement_low - candle.low if self._long
                   else candle.high - structure.displacement_high)
        structure.maximum_adverse_excursion = max(structure.maximum_adverse_excursion or 0.0, adverse)

        if not structure.retested:
            tolerance = p.retest_tolerance_atr * atr
            touched = (candle.low <= structure.structure_level + tolerance if self._long
                       else candle.high >= structure.structure_level - tolerance)
            if touched:
                extreme = candle.low if self._long else candle.high
                overshoot = ((structure.structure_level - extreme) if self._long
                             else (extreme - structure.structure_level))
                structure.retested = True
                structure.bars_to_retest = structure.bars_since_displacement
                structure.retest_extreme = extreme
                structure.retest_overshoot_atr = overshoot / atr
                structure.stop_anchor = extreme
                structure.anchor_bars = 1
                self.state = PB2State.WAITING_RECLAIM
                self._xray(candle.timestamp, "bars_to_retest", structure.bars_to_retest,
                           p.retest_maximum_bars, True, "Completed bars from displacement to retest")
                self._xray(candle.timestamp, "retest_overshoot_atr", structure.retest_overshoot_atr,
                           p.retest_tolerance_atr, True,
                           "Retest extreme beyond the structure level, in ATR (negative = never reached it)")
                self._log("retest_detected", True, None, candle.timestamp, {
                    "bars_to_retest": structure.bars_to_retest, "retest_extreme": extreme,
                    "retest_overshoot_atr": structure.retest_overshoot_atr,
                    "maximum_adverse_excursion": structure.maximum_adverse_excursion,
                    "distance_to_ema20": candle.close - ema20,
                    "distance_to_ema50": candle.close - ema50,
                })

        if structure.retested:
            # A bar that both retests and reclaims is allowed: the close is by
            # construction the last price of the bar, so a low/high inside the
            # retest tolerance necessarily precedes the reclaiming close. No
            # intrabar ordering has to be assumed. Acceptance still requires the
            # following bar, so the sequence never collapses into one candle.
            same_bar = structure.bars_to_retest == structure.bars_since_displacement
            if self._evaluate_reclaim(candle, structure, atr):
                structure.same_bar_retest_reclaim = same_bar
                if p.acceptance_mode == ACCEPTANCE_RECLAIM_ONLY:
                    # Architecture ablation: no separate acceptance bar, so the
                    # reclaim candle is the entry reference.
                    return self._construct_entry(candle, structure, atr)
                return None

        if structure.bars_since_displacement >= p.retest_maximum_bars:
            self._log("retest_expired", False,
                      "no reclaim within the retest window" if structure.retested
                      else "structure level never retested",
                      candle.timestamp, {"bars_since_displacement": structure.bars_since_displacement,
                                         "displacement_time": str(structure.displacement_time),
                                         "retested": structure.retested})
            self._reset_structure()
        return None

    def _evaluate_reclaim(self, candle: Candle, structure: _Structure, atr: float) -> bool:
        p = self.params
        body = body_percent(candle)
        location = close_location_percent(candle)
        if body is None or location is None:
            self._log("reclaim_rejected", False, "zero-range candle", candle.timestamp)
            return False

        range_atr = (candle.high - candle.low) / atr
        directional_location = location if self._long else 1.0 - location
        directional = candle.close > candle.open if self._long else candle.close < candle.open
        beyond_level = self._beyond(candle.close, structure.structure_level)
        body_ok = body >= p.reclaim_minimum_body_percent
        location_ok = directional_location >= 1.0 - p.reclaim_close_location_percent
        range_ok = range_atr <= p.reclaim_maximum_range_atr

        self._log("reclaim_evaluated", True, None, candle.timestamp,
                  {"body_percent": body, "close_location": directional_location,
                   "range_atr": range_atr, "beyond_level": beyond_level})
        self._xray(candle.timestamp, "reclaim_body_percent", body, p.reclaim_minimum_body_percent,
                   body_ok, "Reclaim candle body as a share of its range")
        self._xray(candle.timestamp, "reclaim_close_location", directional_location,
                   1.0 - p.reclaim_close_location_percent, location_ok,
                   "Reclaim close location within its range, oriented to the trade direction")
        self._xray(candle.timestamp, "reclaim_range_atr", range_atr, p.reclaim_maximum_range_atr,
                   range_ok, "Reclaim candle range in ATR")

        passed = directional and beyond_level and body_ok and location_ok and range_ok
        if not passed:
            reason = ("candle not directional" if not directional
                      else "close did not reclaim the structure level" if not beyond_level
                      else "insufficient body" if not body_ok
                      else "close not at the extreme" if not location_ok
                      else "range too wide")
            self._log("reclaim_rejected", False, reason, candle.timestamp,
                      {"body_percent": body, "close_location": directional_location,
                       "range_atr": range_atr})
            return False

        structure.reclaim_time = candle.timestamp
        structure.reclaim_close = candle.close
        structure.reclaim_body_percent = body
        structure.reclaim_close_location = directional_location
        structure.reclaim_range_atr = range_atr
        self._extend_anchor(candle, structure)
        if p.acceptance_mode != ACCEPTANCE_RECLAIM_ONLY:
            self.state = PB2State.WAITING_ACCEPTANCE
        self._log("reclaim_confirmed", True, None, candle.timestamp, {
            "body_percent": body, "close_location": directional_location, "range_atr": range_atr,
            "reclaim_close": candle.close, "structure_level": structure.structure_level,
            "displacement_time": str(structure.displacement_time),
        })
        return True

    def _extend_anchor(self, candle: Candle, structure: _Structure) -> None:
        """Track the structural stop anchor across retest/reclaim/acceptance bars."""
        extreme = candle.low if self._long else candle.high
        if structure.stop_anchor is None:
            structure.stop_anchor = extreme
        else:
            structure.stop_anchor = (min(structure.stop_anchor, extreme) if self._long
                                     else max(structure.stop_anchor, extreme))
        structure.anchor_bars += 1

    # ------------------------------------------------------------------
    # sections 10-12: acceptance, risk and the pending entry
    # ------------------------------------------------------------------

    def _evaluate_acceptance(self, candle: Candle, atr: float) -> Signal | None:
        p = self.params
        structure = self.structure
        assert structure is not None and structure.reclaim_close is not None

        beyond_level = self._beyond(candle.close, structure.structure_level)
        held_reclaim = (candle.close >= structure.reclaim_close if self._long
                        else candle.close <= structure.reclaim_close)
        # STRICT additionally demands the acceptance bar extend beyond the
        # reclaim close; LEVEL_HOLD only asks that the reclaimed level holds.
        requires_expansion = p.acceptance_mode == ACCEPTANCE_STRICT
        distance_atr = abs(candle.close - structure.structure_level) / atr
        range_atr = (candle.high - candle.low) / atr
        change = candle.close - structure.reclaim_close

        self._log("acceptance_evaluated", True, None, candle.timestamp, {
            "beyond_level": beyond_level, "held_reclaim": held_reclaim,
            "acceptance_mode": p.acceptance_mode, "requires_expansion": requires_expansion,
            "acceptance_distance_atr": distance_atr, "acceptance_range_atr": range_atr,
            "reclaim_to_acceptance_change": change,
            "displacement_time": str(structure.displacement_time),
        })
        self._xray(candle.timestamp, "acceptance_distance_atr", distance_atr, 0.0, beyond_level,
                   "Acceptance close beyond the structure level, in ATR")
        self._xray(candle.timestamp, "acceptance_range_atr", range_atr, None, True,
                   "Acceptance candle range in ATR (unfiltered in Phase A)")

        if not (beyond_level and (held_reclaim or not requires_expansion)):
            self._log("acceptance_failed", False,
                      "close fell back through the structure level" if not beyond_level
                      else "close did not hold the reclaim close",
                      candle.timestamp, {"acceptance_close": candle.close,
                                         "structure_level": structure.structure_level,
                                         "reclaim_close": structure.reclaim_close,
                                         "acceptance_mode": p.acceptance_mode,
                                         "beyond_level": beyond_level,
                                         "held_reclaim": held_reclaim,
                                         "displacement_time": str(structure.displacement_time)})
            self._reset_structure()
            return None

        self._extend_anchor(candle, structure)
        self._log("acceptance_confirmed", True, None, candle.timestamp, {
            "acceptance_distance_atr": distance_atr, "acceptance_range_atr": range_atr,
            "reclaim_to_acceptance_change": change, "acceptance_close": candle.close,
            "acceptance_mode": p.acceptance_mode, "held_reclaim": held_reclaim,
            "displacement_time": str(structure.displacement_time),
        })
        return self._construct_entry(candle, structure, atr)

    def _construct_entry(self, candle: Candle, structure: _Structure, atr: float) -> Signal | None:
        p = self.params
        assert structure.stop_anchor is not None
        if self._long:
            trigger = candle.high + p.entry_buffer_atr * atr
            stop = structure.stop_anchor - p.stop_buffer_atr * atr
            stop_distance = trigger - stop
        else:
            trigger = candle.low - p.entry_buffer_atr * atr
            stop = structure.stop_anchor + p.stop_buffer_atr * atr
            stop_distance = stop - trigger

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
            direction=self.direction, pending_entry_price=trigger, pending_stop_price=stop,
            pending_expiry_bars=p.pending_expiry_bars, setup_id=self.setup_id,
        )
        self._log("pending_created", True, None, candle.timestamp, {
            "trigger": trigger, "stop": stop, "stop_atr": stop_atr,
            "expiry_bars": p.pending_expiry_bars,
            "structure_level": structure.structure_level,
            "bars_to_retest": structure.bars_to_retest,
            "retest_overshoot_atr": structure.retest_overshoot_atr,
            "breakout_distance_atr": structure.breakout_distance_atr,
            "reclaim_body_percent": structure.reclaim_body_percent,
            "acceptance_distance_atr": abs(candle.close - structure.structure_level) / atr,
            "same_bar_retest_reclaim": structure.same_bar_retest_reclaim,
            "acceptance_mode": p.acceptance_mode,
            "displacement_time": str(structure.displacement_time),
            "reclaim_time": str(structure.reclaim_time),
            "before_trade_start": bool(self._trade_start is not None
                                       and candle.timestamp < self._trade_start),
        })
        # The structure is consumed: one displacement can produce at most one
        # pending order, so a fresh displacement is required for the next entry.
        self.structure = None
        self.state = PB2State.PENDING_ENTRY
        return signal
