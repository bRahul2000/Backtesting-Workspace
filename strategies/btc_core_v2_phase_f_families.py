"""Research-only Phase F candidate families, operating inside H1 TRANSITION.

Phases A-C closed parameter work on A4 and T3. Phase D and E closed the mirror
and range families. Phase F looks at the one large pool the frozen Core has no
gate for: the TRANSITION bucket, 28,879 development bars, 50.31% of the split,
7.66% of it inside a Core position, and — measured, not assumed — **zero** A4 or
T3 setups on any of those bars.

``research/core_v2_phase_f_map.py`` splits that pool into the four disjoint ways
a bar can fail both frozen trend branches. Two of them are genuinely "not yet a
trend": ``EMERGING_SEPARATION`` (3,072 bars, H1 EMAs closer than 1.00 ATR) and
``WIDE_BUT_WEAK_ADX`` (11,689 bars, trend geometry present, momentum not). The
other two are misalignment, not emergence. The families below are built for the
first two.

* **F1, Emerging-Trend Breakout.** The frozen T3 trend engine with its regime
  gate moved, and nothing else. No new decision logic: same structure break,
  body, range, RSI, extension, buffers, stop lookback and 3R. It fires only on
  bars the frozen bucket calls TRANSITION, so it cannot overlap T3 by
  construction — it acts *before* the regime is a trend, which is exactly what
  the brief asked for.
* **F2, Transition EMA Trend-Initiation.** The M15 EMA20/EMA50 cross itself as
  the trigger, H1 lean agreeing. The prior-research audit found no family in the
  repository that triggers on an EMA cross: PB1 is a measured impulse, PB2/PB3
  are break-retest-reclaim, A4/D2 are pullbacks *within* an established stack,
  T3/D1 are structure breakouts, R2/D3 are range sweeps, M1 is compression to
  expansion. This replaces the briefed F2 (breakout -> retest -> continuation),
  which the audit showed is PB2/PB3's mechanism and was already run on these
  bars: 20 of PB3's 50 development trades and 3 of PB2 SHORT's 8 landed on
  TRANSITION bars. Rebuilding it would re-run a rejected architecture.
* **F3, Transition Failed-Break Reversal.** A break of local structure that does
  not hold and closes back through the level. The audit cleared this one: V3-R2
  is the repository's sweep-reversal family and it entered on **0** TRANSITION
  bars — its own source disables itself outside a <= 0.80-separation range — and
  PB3 reclaims in the *break* direction, which is the opposite trade.

Every numeric constant is taken from ``V3T3FrozenParameters``: continuation
families use T3's trend band (body 0.70, range 0.60-2.00 ATR, RSI 50-76 / 24-50,
extension 2.50 ATR), the reversal family uses T3's own reversal band (body 0.35,
RSI <= 46 long / >= 54 short). Nothing here was chosen by search, and 3R is
unchanged. Each family emits a distinct setup id because the Core routes
pending-order ownership by setup id.
"""
from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass

import pandas as pd

import strategies.btc_v3_t3_breakout_short as _t3
from engine.models import (CancelPendingOrder, Candle, Direction, ExecutionState,
                           PendingOrder, Signal)
from research.core_v2_opportunity_map import MIN_ADX, RANGE_SEPARATION, TREND_SEPARATION
from strategies.base import Strategy
from strategies.base_strategy import (
    ParameterType, StrategyDescriptor, StrategyMetadata, StrategyParameter, StrategyStatus,
)
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.btc_v3_t3_breakout_short import (
    BtcV3T3BreakoutShortFrozen, V3T3FrozenParameters,
)
from strategies.confirmed_h1_regime import ConfirmedH1Regime, H1RegimeValue
from strategies.pine_indicators import ATR, DMI, EMA, RSI
from strategies.registry import StrategyRegistry, discover_builtin_strategies
from strategies.universal_catalog import _core_warmup, _source_hash, _t3_warmup

VARIANT_FILE = "btc_core_v2_phase_f_families.py"

F1_SETUP_ID = "RESEARCH_F1_EMERGING_BREAKOUT"
F2_SETUP_ID = "RESEARCH_F2_EMA_INITIATION"
F3_SETUP_ID = "RESEARCH_F3_FAILED_BREAK_REVERSAL"


# --- the shared TRANSITION gate -------------------------------------------------


def frozen_bucket(h1: H1RegimeValue, ema20: float, ema50: float,
                  adx: float | None, atr: float | None) -> str:
    """The Phase D / Phase F census bucket for one bar.

    Restated here rather than imported from the census so a strategy never
    depends on a reporting module, but it is the same expression and a test
    asserts the two agree bar for bar on the development split.
    """
    separation, slope = h1.separation_atr, h1.slope
    if separation is None or slope is None or adx is None or atr is None:
        return "WARMUP"
    if (separation >= TREND_SEPARATION and adx >= MIN_ADX
            and h1.fast_ema > h1.slow_ema and slope > 0 and ema20 > ema50):
        return "BULLISH_TREND"
    if (separation >= TREND_SEPARATION and adx >= MIN_ADX
            and h1.fast_ema < h1.slow_ema and slope < 0 and ema20 < ema50):
        return "BEARISH_TREND"
    if separation <= RANGE_SEPARATION:
        return "NEUTRAL_RANGE"
    return "TRANSITION"


class TransitionGate:
    """A shadow indicator set that answers "is this bar TRANSITION, and widening?"

    It runs its own ``ConfirmedH1Regime``, EMAs, ATR and DMI rather than reading
    a strategy's, so it can be updated on *every* candle. A strategy's own
    indicators are only consulted on bars that survive its session, cap and
    position checks, and a separation history with holes in it would silently
    compare the wrong two hours.
    """

    def __init__(self, params: V3T3FrozenParameters) -> None:
        self.params = params
        self.reset()

    def reset(self) -> None:
        p = self.params
        self.h1 = ConfirmedH1Regime(p.h1_fast_ema, p.h1_slow_ema, p.h1_atr_length,
                                    p.h1_slope_lookback)
        self.fast, self.slow = EMA(p.ema_fast), EMA(p.ema_slow)
        self.atr, self.dmi = ATR(p.atr_length), DMI(p.di_length, p.adx_smoothing)
        self.hour: pd.Timestamp | None = None
        self.separation: float | None = None
        self.previous_separation: float | None = None
        self.bucket = "WARMUP"
        self.lean = "NONE"

    def update(self, candle: Candle) -> None:
        value = self.h1.update(candle)
        ema20 = self.fast.update(candle.close)
        ema50 = self.slow.update(candle.close)
        atr = self.atr.update(candle)
        adx = self.dmi.update(candle).adx
        if value.hour is not None and value.hour != self.hour:
            self.previous_separation = self.separation
            self.separation, self.hour = value.separation_atr, value.hour
        self.bucket = frozen_bucket(value, ema20, ema50, adx, atr)
        if value.fast_ema is not None and value.slow_ema is not None:
            self.lean = ("BULLISH_LEAN" if value.fast_ema > value.slow_ema
                         else "BEARISH_LEAN" if value.fast_ema < value.slow_ema else "FLAT")

    @property
    def in_transition(self) -> bool:
        return self.bucket == "TRANSITION"

    @property
    def expanding(self) -> bool:
        return (self.previous_separation is not None and self.separation is not None
                and self.separation > self.previous_separation)


# --- F1: the frozen T3 trend engine, moved to the pre-trend bucket ----------------


def f1_parameters() -> V3T3FrozenParameters:
    """T3's trend engine with its regime gate opened and both sides enabled.

    The thresholds are set to zero rather than to some other number because the
    real gate is the explicit TRANSITION check in ``F1EmergingBreakout``. Leaving
    a second numeric threshold here would make the family look like a tuned
    relaxation of T3 when it is a regime substitution.
    """
    params = V3T3FrozenParameters()
    object.__setattr__(params, "longs_enabled", True)
    object.__setattr__(params, "shorts_enabled", True)
    object.__setattr__(params, "trend_min_h1_separation_atr", 0.0)
    object.__setattr__(params, "trend_min_adx", 0.0)
    V3T3FrozenParameters.__post_init__(params)
    return params


@contextmanager
def _setup_id(setup_id: str):
    """Stamp this family's own id on the signal ``evaluate_v3`` builds."""
    original = _t3.TREND_SETUP_ID
    _t3.TREND_SETUP_ID = setup_id
    try:
        yield
    finally:
        _t3.TREND_SETUP_ID = original


@contextmanager
def _withdrawn(inactive: bool):
    """Suppress the signal without disturbing a single indicator update.

    The parent's ``on_candle`` has to run in full — it advances the H1 bucket,
    the EMAs, the ATR, the RSI, the DMI and the structure deque — so the gate
    cannot be an early return. Rebinding the evaluator for one call is the same
    mechanism the frozen A4 wrapper uses on ``confirmation_passes``.
    """
    if not inactive:
        yield
        return
    original = _t3.evaluate_v3
    _t3.evaluate_v3 = lambda obs, params, counters=None: None
    try:
        yield
    finally:
        _t3.evaluate_v3 = original


class F1EmergingBreakout(BtcV3T3BreakoutShortFrozen):
    """T3's structure breakout, fired only before the regime becomes a trend."""

    def __init__(self, structure_lookback: int = 5, require_expansion: bool = True) -> None:
        params = f1_parameters()
        if structure_lookback != params.trend_structure_lookback:
            object.__setattr__(params, "trend_structure_lookback", structure_lookback)
            V3T3FrozenParameters.__post_init__(params)
        super().__init__(params)
        self.require_expansion = require_expansion
        self.gate = TransitionGate(params)

    def reset(self) -> None:
        super().reset()
        gate = getattr(self, "gate", None)
        if gate is not None:
            gate.reset()

    def on_data_gap(self) -> None:
        super().on_data_gap()
        self.gate.reset()

    def _blocked(self) -> bool:
        return not self.gate.in_transition or (self.require_expansion and not self.gate.expanding)

    def on_candle(self, candle: Candle):
        self.gate.update(candle)
        with _setup_id(F1_SETUP_ID), _withdrawn(self._blocked()):
            return super().on_candle(candle)

    def on_backtest_end(self, pending_order: PendingOrder):
        return CancelPendingOrder("Backtest range ended.", pending_order.setup_id)


# --- F2 and F3: a shared control flow, mirrored from the frozen T3 ----------------


@dataclass(frozen=True)
class TransitionObservation:
    candle: Candle
    previous: tuple[Candle, ...]
    ema20: float
    ema50: float
    atr: float
    rsi: float
    adx: float
    bucket: str
    lean: str
    expanding: bool
    crossed_up: bool
    crossed_down: bool
    stop_low: float
    stop_high: float
    structure_high: float | None
    structure_low: float | None


class TransitionFamily(Strategy):
    """T3's candle handling, statement for statement, with a new evaluator.

    The ordering is T3's and not A4's: session, then daily cap, then position,
    then pending. That matters — the two orders cancel pending orders under
    different conditions, and copying the wrong one would make a family's
    execution incomparable with the frozen children it is measured against.
    """

    setup_id = "RESEARCH_TRANSITION"

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
        self.gate = TransitionGate(p)
        self.fast, self.slow = EMA(p.ema_fast), EMA(p.ema_slow)
        self.atr, self.rsi = ATR(p.atr_length), RSI(p.rsi_length)
        self.dmi = DMI(p.di_length, p.adx_smoothing)
        self.previous: deque[Candle] = deque(
            maxlen=max(p.trend_structure_lookback, p.range_sweep_lookback, 2))
        self.stack: int | None = None
        self._reset_family_state()

    def _reset_family_state(self) -> None:
        """Per-family setup memory; cleared with the indicators on a data gap."""

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
        self.gate.update(candle)
        ema20 = self.fast.update(candle.close)
        ema50 = self.slow.update(candle.close)
        atr = self.atr.update(candle)
        rsi = self.rsi.update(candle.close)
        adx = self.dmi.update(candle).adx

        prior = list(self.previous)
        structure_high = (max(x.high for x in prior[-p.trend_structure_lookback:])
                          if len(prior) >= p.trend_structure_lookback else None)
        structure_low = (min(x.low for x in prior[-p.trend_structure_lookback:])
                         if len(prior) >= p.trend_structure_lookback else None)
        stop_bars = prior[-(p.trend_stop_lookback - 1):] if p.trend_stop_lookback > 1 else []
        stop_low = min(x.low for x in (*stop_bars, candle))
        stop_high = max(x.high for x in (*stop_bars, candle))
        self.previous.append(candle)

        stack = 1 if ema20 > ema50 else (-1 if ema20 < ema50 else 0)
        crossed_up = self.stack is not None and self.stack <= 0 and stack > 0
        crossed_down = self.stack is not None and self.stack >= 0 and stack < 0
        self.stack = stack

        if ((self.window_start is not None and candle.timestamp < self.window_start)
                or (self.window_end is not None and candle.timestamp > self.window_end)):
            return None
        state = self.execution_state
        if state is None:
            raise RuntimeError(f"{type(self).__name__} needs execution state from the backtester.")

        day = (candle.timestamp.year, candle.timestamp.month, candle.timestamp.day)
        if day != self.day_key:
            self.day_key = day
            self.trades_today = 0
        if state.opened_position is not None:
            self.trades_today += 1

        if not p.session_start <= candle.timestamp.time() < p.session_end:
            if state.pending_order is not None:
                return CancelPendingOrder("UTC trading session ended.",
                                          state.pending_order.setup_id)
            return None
        if self.trades_today >= p.max_trades_per_day:
            if state.pending_order is not None:
                return CancelPendingOrder("Maximum filled trades per UTC day reached.",
                                          state.pending_order.setup_id)
            return None
        if state.position is not None or state.pending_order is not None:
            return None
        if atr is None or atr <= 0 or rsi is None or adx is None:
            return None

        self.diagnostics["Eligible candles"] += 1
        observation = TransitionObservation(
            candle=candle, previous=tuple(prior), ema20=ema20, ema50=ema50, atr=atr,
            rsi=rsi, adx=adx, bucket=self.gate.bucket, lean=self.gate.lean,
            expanding=self.gate.expanding, crossed_up=crossed_up, crossed_down=crossed_down,
            stop_low=stop_low, stop_high=stop_high,
            structure_high=structure_high, structure_low=structure_low)
        if observation.bucket != "TRANSITION":
            return None
        return self.evaluate(observation)

    def evaluate(self, obs: TransitionObservation) -> Signal | None:
        raise NotImplementedError

    def _signal(self, direction: Direction, trigger: float, stop: float,
                atr: float) -> Signal | None:
        """T3's own stop-distance validation and pending construction."""
        p = self.params
        if not (trigger > 0 and stop > 0 and atr > 0):
            return None
        risk_atr = ((trigger - stop) / atr if direction is Direction.LONG
                    else (stop - trigger) / atr)
        if not p.minimum_stop_atr <= risk_atr <= p.maximum_stop_atr:
            self.diagnostics["Stop distance rejected"] += 1
            return None
        self.diagnostics[f"{direction.value} signals"] += 1
        return Signal.pending_stop(direction, trigger, stop, p.pending_bars, self.setup_id)


def body_percent(candle: Candle) -> float:
    width = candle.high - candle.low
    return abs(candle.close - candle.open) / width if width > 0 else 0.0


# --- F2: the EMA cross as the trigger --------------------------------------------


class F2EmaInitiation(TransitionFamily):
    """The M15 stack flipping, with the confirmed H1 lean already pointing that way.

    ``confirmation_bars`` is the one structural choice: 0 means the cross bar
    must itself be the directional candle, and a positive value allows that many
    later bars to supply it while the cross stays valid.
    """

    setup_id = F2_SETUP_ID

    def __init__(self, confirmation_bars: int = 0, require_expansion: bool = False) -> None:
        self.confirmation_bars = confirmation_bars
        self.require_expansion = require_expansion
        super().__init__()

    def _reset_family_state(self) -> None:
        self.pending_direction: Direction | None = None
        self.pending_age = 0

    def evaluate(self, obs: TransitionObservation) -> Signal | None:
        p = self.params
        if self.require_expansion and not obs.expanding:
            self.pending_direction = None
            return None

        #--- A fresh cross replaces any cross still waiting for confirmation.
        if obs.crossed_up and obs.lean == "BULLISH_LEAN":
            self.pending_direction, self.pending_age = Direction.LONG, 0
            self.diagnostics["Crosses armed"] += 1
        elif obs.crossed_down and obs.lean == "BEARISH_LEAN":
            self.pending_direction, self.pending_age = Direction.SHORT, 0
            self.diagnostics["Crosses armed"] += 1
        elif self.pending_direction is not None:
            self.pending_age += 1
            if self.pending_age > self.confirmation_bars:
                self.pending_direction = None

        direction = self.pending_direction
        if direction is None:
            return None
        candle, atr = obs.candle, obs.atr
        range_atr = (candle.high - candle.low) / atr
        extension = abs(candle.close - obs.ema20) / atr
        body = body_percent(candle)
        if not (body >= p.trend_minimum_body_percent
                and p.trend_minimum_range_atr <= range_atr <= p.trend_maximum_range_atr
                and extension <= p.trend_maximum_extension_atr):
            return None

        if direction is Direction.LONG:
            if not (candle.close > candle.open
                    and p.trend_long_rsi_min <= obs.rsi <= p.trend_long_rsi_max):
                return None
            trigger = candle.high + p.entry_buffer_atr * atr
            stop = obs.stop_low - p.stop_buffer_atr * atr
        else:
            if not (candle.close < candle.open
                    and p.trend_short_rsi_min <= obs.rsi <= p.trend_short_rsi_max):
                return None
            trigger = candle.low - p.entry_buffer_atr * atr
            stop = obs.stop_high + p.stop_buffer_atr * atr

        signal = self._signal(direction, trigger, stop, atr)
        if signal is not None:
            self.pending_direction = None
        return signal


# --- F3: a break of structure that does not hold ----------------------------------


class F3FailedBreakReversal(TransitionFamily):
    """Break local structure, fail to hold it, close back through, trade the other way.

    The stop is the extreme the failed break actually reached, which is what makes
    this a structural stop rather than a volatility stop: if price returns there
    the break was real after all and the premise is gone.
    """

    setup_id = F3_SETUP_ID

    def __init__(self, reversal_window_bars: int = 3, require_acceptance: bool = False) -> None:
        self.reversal_window_bars = reversal_window_bars
        self.require_acceptance = require_acceptance
        super().__init__()

    def _reset_family_state(self) -> None:
        self.break_direction: Direction | None = None
        self.break_level: float | None = None
        self.break_extreme: float | None = None
        self.break_age = 0
        self.reclaimed = False

    def _arm(self, direction: Direction, level: float, extreme: float) -> None:
        self.break_direction, self.break_level = direction, level
        self.break_extreme, self.break_age, self.reclaimed = extreme, 0, False
        self.diagnostics["Structure breaks armed"] += 1

    def evaluate(self, obs: TransitionObservation) -> Signal | None:
        candle = obs.candle
        signal: Signal | None = None
        resolved = False

        if self.break_direction is not None:
            self.break_age += 1
            #--- Track how far the failed break actually ran; that extreme is the stop.
            if self.break_direction is Direction.LONG:
                self.break_extreme = max(self.break_extreme, candle.high)
            else:
                self.break_extreme = min(self.break_extreme, candle.low)

            failed = (candle.close < self.break_level
                      if self.break_direction is Direction.LONG
                      else candle.close > self.break_level)
            if failed and self.require_acceptance and not self.reclaimed:
                #--- One acceptance bar beyond the reclaim before acting.
                self.reclaimed = True
            elif failed:
                signal = self._reversal(obs)
                self._reset_family_state()
                resolved = True
            if (not resolved and self.break_age > self.reversal_window_bars):
                self._reset_family_state()
                resolved = True

        #--- A new break arms last, and never on a bar that just resolved one, so
        #--- a single bar is never both the failure of one break and the start of
        #--- the next.
        if not resolved and self.break_direction is None and obs.structure_high is not None:
            if candle.close > obs.structure_high:
                self._arm(Direction.LONG, obs.structure_high, candle.high)
            elif obs.structure_low is not None and candle.close < obs.structure_low:
                self._arm(Direction.SHORT, obs.structure_low, candle.low)
        return signal

    def _reversal(self, obs: TransitionObservation) -> Signal | None:
        p = self.params
        candle, atr = obs.candle, obs.atr
        if body_percent(candle) < p.range_minimum_body_percent:
            return None
        if self.break_direction is Direction.LONG:
            #--- The upside break failed: trade short, stop above its high.
            if not (candle.close < candle.open and obs.rsi >= p.range_short_rsi_min):
                return None
            trigger = candle.low - p.entry_buffer_atr * atr
            stop = self.break_extreme + p.stop_buffer_atr * atr
            return self._signal(Direction.SHORT, trigger, stop, atr)
        if not (candle.close > candle.open and obs.rsi <= p.range_long_rsi_max):
            return None
        trigger = candle.high + p.entry_buffer_atr * atr
        stop = self.break_extreme - p.stop_buffer_atr * atr
        return self._signal(Direction.LONG, trigger, stop, atr)


# --- the predeclared variation grid ------------------------------------------------

#--- Three structural alternatives per family, fixed before any of them was run.
#--- None of these is a threshold: each one changes what the family *is* — how
#--- much structure it reads, whether it waits for a separate confirmation bar,
#--- whether it demands the regime be widening. No numeric gate is searched, and
#--- the reward multiple is 3R in every arm.
@dataclass(frozen=True)
class Variant:
    key: str
    family: str
    label: str
    setup_id: str
    baseline: bool

    def build(self):
        return VARIANT_FACTORIES[self.key]()


VARIANT_FACTORIES = {
    "F1a": lambda: F1EmergingBreakout(structure_lookback=5, require_expansion=True),
    "F1b": lambda: F1EmergingBreakout(structure_lookback=5, require_expansion=False),
    "F1c": lambda: F1EmergingBreakout(structure_lookback=3, require_expansion=True),
    "F2a": lambda: F2EmaInitiation(confirmation_bars=0, require_expansion=False),
    "F2b": lambda: F2EmaInitiation(confirmation_bars=3, require_expansion=False),
    "F2c": lambda: F2EmaInitiation(confirmation_bars=0, require_expansion=True),
    "F3a": lambda: F3FailedBreakReversal(reversal_window_bars=3, require_acceptance=False),
    "F3b": lambda: F3FailedBreakReversal(reversal_window_bars=5, require_acceptance=False),
    "F3c": lambda: F3FailedBreakReversal(reversal_window_bars=3, require_acceptance=True),
}

VARIANTS: tuple[Variant, ...] = (
    Variant("F1a", "F1", "5-bar structure, separation expanding", F1_SETUP_ID, True),
    Variant("F1b", "F1", "5-bar structure, expansion not required", F1_SETUP_ID, False),
    Variant("F1c", "F1", "3-bar structure, separation expanding", F1_SETUP_ID, False),
    Variant("F2a", "F2", "cross bar is the confirmation", F2_SETUP_ID, True),
    Variant("F2b", "F2", "cross plus a confirmation bar within 3", F2_SETUP_ID, False),
    Variant("F2c", "F2", "cross bar, separation expanding", F2_SETUP_ID, False),
    Variant("F3a", "F3", "3-bar reversal window", F3_SETUP_ID, True),
    Variant("F3b", "F3", "5-bar reversal window", F3_SETUP_ID, False),
    Variant("F3c", "F3", "3-bar window plus an acceptance bar", F3_SETUP_ID, False),
)

FAMILY_LABELS = {
    "F1": "Emerging-Trend Breakout",
    "F2": "Transition EMA Trend-Initiation",
    "F3": "Transition Failed-Break Reversal",
}
FAMILY_SETUP_IDS = {"F1": F1_SETUP_ID, "F2": F2_SETUP_ID, "F3": F3_SETUP_ID}
BASELINE_VARIANTS = {"F1": "F1a", "F2": "F2a", "F3": "F3a"}
VARIANTS_BY_KEY = {variant.key: variant for variant in VARIANTS}
VARIANTS_BY_FAMILY = {
    family: tuple(v for v in VARIANTS if v.family == family) for family in FAMILY_LABELS
}


# --- Core composition ---------------------------------------------------------------


class CoreWithTransitionFamily(BtcV3CoreV1Frozen):
    """Frozen A4 + frozen T3 + one Phase F variant, one global position.

    Identical in structure to the Phase D composition so the two phases' numbers
    mean the same thing: both frozen children see every candle, only the owning
    child may cancel a pending order, a position blocks everyone, and the
    candidate only acts on a bar where the frozen pair did not.
    """

    def __init__(self, variant_key: str) -> None:
        super().__init__()
        self.variant_key = variant_key
        self.family = VARIANTS_BY_KEY[variant_key].build()
        self.family_setup_id = VARIANTS_BY_KEY[variant_key].setup_id
        self.params = _Composition(variant_key)
        self.reset()

    def reset(self) -> None:
        super().reset()
        family = getattr(self, "family", None)
        if family is not None:
            family.reset()

    def on_data_gap(self) -> None:
        super().on_data_gap()
        self.family.on_data_gap()

    def on_backtest_window(self, start, end) -> None:
        super().on_backtest_window(start, end)
        self.family.on_backtest_window(start, end)

    def on_execution_state(self, state: ExecutionState) -> None:
        super().on_execution_state(state)
        self.family.on_execution_state(state)

    def on_backtest_end(self, pending_order: PendingOrder):
        if pending_order.setup_id == self.family_setup_id:
            return self.family.on_backtest_end(pending_order)
        return super().on_backtest_end(pending_order)

    def on_candle(self, candle: Candle):
        state = self.execution_state
        core_action = super().on_candle(candle)
        family_action = self.family.on_candle(candle)

        pending = state.pending_order if state is not None else None
        if pending is not None:
            if pending.setup_id == self.family_setup_id:
                return family_action if isinstance(family_action, CancelPendingOrder) else None
            return core_action
        if state is not None and state.position is not None:
            return None
        if isinstance(core_action, Signal):
            return core_action
        if isinstance(family_action, Signal):
            return family_action
        return core_action or family_action


@dataclass(frozen=True)
class _Composition:
    candidate_variant: str


# --- Registration ---------------------------------------------------------------------

STANDALONE_IDS = {key: f"RESEARCH_{key}_STANDALONE" for key in VARIANT_FACTORIES}
CORE_IDS = {key: f"RESEARCH_CORE_PLUS_{key}" for key in VARIANT_FACTORIES}


def _metadata(strategy_id: str, name: str, description: str) -> StrategyMetadata:
    return StrategyMetadata(
        strategy_id=strategy_id, name=name, version="phase-f",
        status=StrategyStatus.RESEARCH, category="discovery",
        supported_instruments=("BTCUSD",), supported_timeframes=("15m",),
        description=description, created_date="2026-09-21",
        strategy_fingerprint=_source_hash(VARIANT_FILE),
    )


def _parameter(value: str) -> tuple[StrategyParameter, ...]:
    return (StrategyParameter("candidate_variant", ParameterType.STRING, value,
                              description="Phase F discovery arm; fixed for the run.",
                              optimization_allowed=False, frozen=True),)


def _descriptors() -> tuple[StrategyDescriptor, ...]:
    output: list[StrategyDescriptor] = []
    for variant in VARIANTS:
        family = FAMILY_LABELS[variant.family]
        output.append(StrategyDescriptor(
            metadata=_metadata(STANDALONE_IDS[variant.key],
                               f"Research · {variant.key} {family} standalone",
                               f"Phase F {variant.key}: {family} — {variant.label}, standalone."),
            factory=(lambda key=variant.key: VARIANT_FACTORIES[key]()),
            parameters=_parameter(variant.key),
            required_timeframes=("15m", "1h"), warmup_resolver=_t3_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
        output.append(StrategyDescriptor(
            metadata=_metadata(CORE_IDS[variant.key],
                               f"Research · Core + {variant.key} {family}",
                               f"Frozen A4 + frozen T3 + Phase F {variant.key}."),
            factory=(lambda key=variant.key: CoreWithTransitionFamily(key)),
            parameters=_parameter(f"CORE+{variant.key}"),
            required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
    return tuple(output)


def phase_f_registry() -> StrategyRegistry:
    """An isolated registry; never the global one the workspace lists."""
    registry = StrategyRegistry()
    for descriptor in discover_builtin_strategies().all():
        registry.register(descriptor)
    for descriptor in _descriptors():
        registry.register(descriptor)
    return registry


PHASE_F_STRATEGY_IDS = tuple(d.metadata.strategy_id for d in _descriptors())
