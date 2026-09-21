"""Research-only Phase D candidate setup families.

Phase A, B and C closed parameter-level work on A4 and T3. Phase D looks for an
*additive* source of trades instead. The opportunity map says where to look: the
frozen Core occupies 10.0% of development bars, A4 enters almost only in bullish
H1 trend (86 of 93) and T3 almost only in bearish (83 of 84), and the
NEUTRAL_RANGE bucket — 20.0% of all bars — has **zero** Core coverage.

Three families, all built from validated structure rather than new invention:

* **D1, T3 LONG mirror.** The frozen T3 source already contains a complete long
  trend-breakout branch behind ``longs_enabled``. Enabling it runs the validated
  structure in the bullish direction with no new decision logic at all, so a
  result is a fact about the market rather than about fresh code.
* **D2, A4 SHORT mirror.** No short pullback-continuation exists. PB2 SHORT is a
  different idea (reclaim/acceptance) and was closed on 14 trades. This is the
  one family that needs a real implementation, mirrored line by line from
  ``btc_v3_l2_trend_pullback_long`` with the A4 overlays applied.
* **D3, T3 RANGE sweep.** Also already in the frozen T3 source, behind
  ``range_enabled``, and gated on ``separation_atr <= 0.80`` — which is exactly
  the NEUTRAL_RANGE bucket the Core never touches. This replaces the briefed
  compression→expansion family because that idea is already implemented as
  ``BTC_V3_M1_MOMENTUM_EXPANSION`` and was REJECTED, while this pool is both
  larger and entirely uncontested.

Every family emits a distinct setup id, because the Core routes pending-order
ownership by setup id and two children sharing one id would break cancellation.
"""
from __future__ import annotations

from collections import Counter, deque
from contextlib import contextmanager
from dataclasses import dataclass, replace

import pandas as pd

import strategies.btc_v3_t3_breakout_short as _t3
from engine.models import (CancelPendingOrder, Candle, Direction, ExecutionState,
                           PendingOrder, Signal)
from strategies.base import Strategy
from strategies.base_strategy import (
    ParameterType, StrategyDescriptor, StrategyMetadata, StrategyParameter, StrategyStatus,
)
from strategies.btc_v3_a4_pullback_long import (
    CONFIRMATION_MAX_BODY_PERCENT, MINIMUM_NORMALIZED_H1_SLOPE, V3A4FrozenParameters,
    frozen_parameters,
)
import strategies.btc_v3_l2_trend_pullback_long as _l2
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.btc_v3_t3_breakout_short import BtcV3T3BreakoutShortFrozen, V3T3FrozenParameters
from strategies.confirmed_h1_regime import ConfirmedH1Regime, H1RegimeValue
from strategies.pine_indicators import ATR, DMI, EMA, RSI
from strategies.registry import StrategyRegistry, discover_builtin_strategies
from strategies.universal_catalog import _a4_warmup, _core_warmup, _source_hash, _t3_warmup

VARIANT_FILE = "btc_core_v2_phase_d_families.py"

D1_SETUP_ID = "RESEARCH_D1_T3_LONG_MIRROR"
D2_SETUP_ID = "RESEARCH_D2_A4_SHORT_MIRROR"
D3_SETUP_ID = "BTC_V3_RANGE"  # the frozen source's own range id


# --- D1: the frozen T3 structure, long side -------------------------------------


def t3_long_parameters() -> V3T3FrozenParameters:
    params = V3T3FrozenParameters()
    object.__setattr__(params, "longs_enabled", True)
    object.__setattr__(params, "shorts_enabled", False)
    V3T3FrozenParameters.__post_init__(params)
    return params


def t3_range_parameters(longs: bool = True, shorts: bool = True) -> V3T3FrozenParameters:
    params = V3T3FrozenParameters()
    object.__setattr__(params, "trend_enabled", False)
    object.__setattr__(params, "range_enabled", True)
    object.__setattr__(params, "longs_enabled", longs)
    object.__setattr__(params, "shorts_enabled", shorts)
    V3T3FrozenParameters.__post_init__(params)
    return params


@contextmanager
def _trend_setup_id(setup_id: str):
    """Give this family its own setup id for one call.

    ``evaluate_v3`` stamps the frozen module global onto the signal, and the Core
    routes pending-order ownership by setup id, so two children sharing T3's id
    would let either cancel the other's order.
    """
    original = _t3.TREND_SETUP_ID
    _t3.TREND_SETUP_ID = setup_id
    try:
        yield
    finally:
        _t3.TREND_SETUP_ID = original


class D1T3LongMirror(BtcV3T3BreakoutShortFrozen):
    """The frozen T3 trend breakout, long side. No new decision logic."""

    def __init__(self) -> None:
        super().__init__(t3_long_parameters())

    def on_candle(self, candle: Candle):
        with _trend_setup_id(D1_SETUP_ID):
            return super().on_candle(candle)

    def on_backtest_end(self, pending_order: PendingOrder):
        return CancelPendingOrder("Backtest range ended.", pending_order.setup_id)


class D3T3RangeSweep(BtcV3T3BreakoutShortFrozen):
    """The frozen T3 range sweep engine, both directions, trend engine off."""

    def __init__(self, longs: bool = True, shorts: bool = True) -> None:
        super().__init__(t3_range_parameters(longs, shorts))


# --- D2: A4's pullback-continuation concept, mirrored short ----------------------


def h1_bearish(h1: H1RegimeValue, params) -> bool:
    """Mirror of ``btc_v3_l2_trend_pullback_long.h1_bullish``."""
    return (
        h1.close is not None
        and h1.fast_ema is not None
        and h1.slow_ema is not None
        and h1.slope is not None
        and h1.separation_atr is not None
        and h1.fast_ema < h1.slow_ema
        and h1.close < h1.slow_ema
        and h1.slope < 0
        and h1.separation_atr >= params.h1_min_separation_atr
    )


def short_confirmation_passes(candle: Candle, previous_candle: Candle | None,
                              ema20: float, rsi: float | None, params) -> bool:
    """Mirror of the A4 confirmation overlay.

    The RSI band is reflected about 50: A4 requires 48 <= rsi <= 70 on a bullish
    reclaim, so the bearish mirror requires 30 <= rsi <= 52. It is a reflection,
    not a tuned band, and no value here was chosen by search.
    """
    if previous_candle is None or rsi is None:
        return False
    body = _l2.body_percent(candle)
    return (
        candle.close < candle.open
        and body >= params.confirmation_min_body_percent
        and body <= CONFIRMATION_MAX_BODY_PERCENT
        and candle.close < ema20
        and candle.close < previous_candle.low
        and (100 - params.confirmation_rsi_max) <= rsi <= (100 - params.confirmation_rsi_min)
    )


class D2A4ShortMirror(Strategy):
    """A4's trend / pullback / confirmation structure, mirrored to the short side.

    Control flow mirrors ``BtcV3L2TrendPullbackLong.on_candle`` statement for
    statement: the same ordering of session and cap checks, the same pending
    cancellation reasons, the same "a structure-break bar is an impulse, not the
    pullback", the same "confirmation has priority over recording a new level",
    and the same single signal per pullback.
    """

    def __init__(self, params: V3A4FrozenParameters | None = None) -> None:
        self.params = params or frozen_parameters()
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
        self.h1 = ConfirmedH1Regime(p.h1_fast_ema, p.h1_slow_ema, p.h1_atr_length,
                                    p.h1_slope_lookback)
        self.fast = EMA(p.ema_fast)
        self.slow = EMA(p.ema_slow)
        self.atr = ATR(p.atr_length)
        self.rsi = RSI(p.rsi_length)
        self.dmi = DMI(p.di_length, p.adx_smoothing)
        self.previous: deque[Candle] = deque(maxlen=max(p.local_structure_lookback, 2))

    def _reset_pullback_state(self, *, clear_structure: bool = False) -> None:
        self.pullback_active = False
        self.pullback_start_time: pd.Timestamp | None = None
        self.pullback_high: float | None = None
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

    def _context_valid(self, h1, ema20: float, ema50: float, adx: float | None) -> bool:
        return (
            h1_bearish(h1, self.params)
            and ema20 < ema50
            and adx is not None and adx >= self.params.min_adx
            and h1.slope is not None and h1.atr is not None and h1.atr > 0
            #--- Mirror of the A4 overlay: the slope is negative in a downtrend,
            #--- so the normalized magnitude is what must clear the threshold.
            and (-h1.slope) / h1.atr >= MINIMUM_NORMALIZED_H1_SLOPE
        )

    def _materially_above_ema50(self, candle: Candle, ema50: float, atr: float | None) -> bool:
        return (atr is not None and atr > 0
                and candle.close > ema50 + _l2.MATERIAL_EMA50_CLOSE_ATR * atr)

    def _record_structure_break(self, candle: Candle, prior_low: float | None,
                                context_valid: bool) -> bool:
        if context_valid and prior_low is not None and candle.close < prior_low:
            self.last_broken_structure_level = prior_low
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
        prior_low = (min(x.low for x in prior[-p.local_structure_lookback:])
                     if len(prior) >= p.local_structure_lookback else None)
        self.previous.append(candle)

        if ((self.window_start is not None and candle.timestamp < self.window_start)
                or (self.window_end is not None and candle.timestamp > self.window_end)):
            return None
        state = self.execution_state
        if state is None:
            raise RuntimeError("D2 A4 short mirror needs execution state from the backtester.")

        day = (candle.timestamp.year, candle.timestamp.month, candle.timestamp.day)
        if day != self.day_key:
            self.day_key = day
            self.trades_today = 0
        if state.opened_position is not None:
            self.trades_today += 1

        in_session = p.session_start <= candle.timestamp.time() < p.session_end
        context_valid = self._context_valid(h1, ema20, ema50, dmi.adx)
        material_above = self._materially_above_ema50(candle, ema50, atr)

        if state.pending_order is not None:
            if not in_session:
                return CancelPendingOrder("UTC trading session ended.", state.pending_order.setup_id)
            if self.trades_today >= p.max_trades_per_day:
                return CancelPendingOrder("Maximum filled trades per UTC day reached.",
                                          state.pending_order.setup_id)
            if not context_valid or material_above:
                return CancelPendingOrder("D2 bearish trend context invalidated.",
                                          state.pending_order.setup_id)
            return None
        if state.position is not None:
            return None
        if not in_session or self.trades_today >= p.max_trades_per_day:
            self._reset_pullback_state(clear_structure=False)
            return None
        if atr is None or atr <= 0 or rsi is None or dmi.adx is None:
            return None

        if not context_valid or material_above:
            if self.pullback_active:
                self.diagnostics["Pullbacks invalidated by trend/EMA50"] += 1
            self._reset_pullback_state(clear_structure=not h1_bearish(h1, p))
            return None

        depth = max(0.0, (candle.high - ema20) / atr)
        if self.pullback_active and depth > p.max_pullback_depth_below_ema20_atr:
            self.diagnostics["Pullbacks too deep"] += 1
            self._reset_pullback_state(clear_structure=False)
            self._record_structure_break(candle, prior_low, context_valid)
            return None

        if self.pullback_active:
            self.pullback_high = (max(self.pullback_high, candle.high)
                                  if self.pullback_high is not None else candle.high)
            self.pullback_max_depth_atr = max(self.pullback_max_depth_atr, depth)
            self.pullback_bars += 1
            if (self.pullback_start_time is not None
                    and candle.timestamp > self.pullback_start_time
                    and short_confirmation_passes(candle, previous_candle, ema20, rsi, p)):
                trigger = candle.low - p.entry_buffer_atr * atr
                stop = self.pullback_high + p.stop_buffer_atr * atr
                risk_atr = (stop - trigger) / atr
                if p.minimum_stop_atr <= risk_atr <= p.maximum_stop_atr:
                    signal = Signal.pending_stop(Direction.SHORT, trigger, stop,
                                                 p.pending_bars, D2_SETUP_ID)
                    self.signal_diagnostics[candle.timestamp + pd.Timedelta(minutes=15)] = {
                        "setup_id": D2_SETUP_ID,
                        "signal_candle_time": candle.timestamp,
                        "pullback_start_time": self.pullback_start_time,
                        "pullback_bars": self.pullback_bars,
                        "pullback_touch": self.pullback_touch,
                        "pullback_depth_atr": self.pullback_max_depth_atr,
                        "adx": dmi.adx, "rsi": rsi,
                        "body_percent": _l2.body_percent(candle),
                        "h1_separation_atr": h1.separation_atr,
                        "h1_ema200_slope": h1.slope,
                        "entry_trigger": trigger, "structural_stop": stop,
                        "stop_distance_atr": risk_atr,
                    }
                    self.diagnostics["Confirmation signals"] += 1
                    self._reset_pullback_state(clear_structure=False)
                    return signal
                self.diagnostics["Confirmation stop distance rejected"] += 1

        if self._record_structure_break(candle, prior_low, context_valid):
            return None

        if not self.pullback_active:
            touches: list[str] = []
            if candle.high >= ema20:
                touches.append("EMA20")
            if candle.high >= ema50:
                touches.append("EMA50")
            if (self.last_broken_structure_level is not None
                    and candle.high >= self.last_broken_structure_level):
                touches.append("STRUCTURE")
            if touches and depth <= p.max_pullback_depth_below_ema20_atr:
                self.pullback_active = True
                self.pullback_start_time = candle.timestamp
                self.pullback_high = candle.high
                self.pullback_max_depth_atr = depth
                self.pullback_bars = 1
                self.pullback_touch = "+".join(touches)
                self.diagnostics["Pullbacks started"] += 1
        return None


# --- Core compositions ------------------------------------------------------------


FAMILIES = {"D1": D1T3LongMirror, "D2": D2A4ShortMirror, "D3": D3T3RangeSweep}
FAMILY_SETUP_IDS = {"D1": D1_SETUP_ID, "D2": D2_SETUP_ID, "D3": D3_SETUP_ID}
FAMILY_LABELS = {"D1": "T3 LONG mirror", "D2": "A4 SHORT mirror", "D3": "T3 RANGE sweep"}


class CoreWithFamily(BtcV3CoreV1Frozen):
    """Frozen A4 + frozen T3 + one candidate family, one global position.

    The frozen Core's own composition rules are reused rather than restated: both
    frozen children see every candle, only the owning child may cancel a pending
    order, and a position blocks everyone. The candidate is layered on top with
    the same contract, and it can only act when the frozen pair has not.
    """

    def __init__(self, family: str) -> None:
        super().__init__()
        self.family_key = family
        self.family = FAMILIES[family]()
        self.family_setup_id = FAMILY_SETUP_IDS[family]
        self.params = _Composition(family)
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
        #--- The frozen pair keeps priority; the candidate only fills the gaps it
        #--- leaves, which is exactly what "incremental contribution" has to mean.
        if isinstance(core_action, Signal):
            return core_action
        if isinstance(family_action, Signal):
            return family_action
        return core_action or family_action


@dataclass(frozen=True)
class _Composition:
    candidate_family: str


# --- Registration ---------------------------------------------------------------------

STANDALONE_IDS = {key: f"RESEARCH_{key}_STANDALONE" for key in FAMILIES}
CORE_IDS = {key: f"RESEARCH_CORE_PLUS_{key}" for key in FAMILIES}


def _metadata(strategy_id: str, name: str, description: str) -> StrategyMetadata:
    return StrategyMetadata(
        strategy_id=strategy_id, name=name, version="phase-d",
        status=StrategyStatus.RESEARCH, category="discovery",
        supported_instruments=("BTCUSD",), supported_timeframes=("15m",),
        description=description, created_date="2026-09-21",
        strategy_fingerprint=_source_hash(VARIANT_FILE),
    )


def _parameter(value: str) -> tuple[StrategyParameter, ...]:
    return (StrategyParameter("candidate_family", ParameterType.STRING, value,
                              description="Phase D discovery arm; fixed for the run.",
                              optimization_allowed=False, frozen=True),)


def _descriptors() -> tuple[StrategyDescriptor, ...]:
    warmup = {"D1": _t3_warmup, "D2": _a4_warmup, "D3": _t3_warmup}
    output: list[StrategyDescriptor] = []
    for key, label in FAMILY_LABELS.items():
        output.append(StrategyDescriptor(
            metadata=_metadata(STANDALONE_IDS[key], f"Research · {key} {label} standalone",
                               f"Phase D candidate {key}: {label}, standalone."),
            factory=(lambda key=key: FAMILIES[key]()),
            parameters=_parameter(key),
            required_timeframes=("15m", "1h"), warmup_resolver=warmup[key],
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
        output.append(StrategyDescriptor(
            metadata=_metadata(CORE_IDS[key], f"Research · Core + {key} {label}",
                               f"Frozen A4 + frozen T3 + Phase D candidate {key}."),
            factory=(lambda key=key: CoreWithFamily(key)),
            parameters=_parameter(f"CORE+{key}"),
            required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
    return tuple(output)


def phase_d_registry() -> StrategyRegistry:
    """An isolated registry; never the global one the workspace lists."""
    registry = StrategyRegistry()
    for descriptor in discover_builtin_strategies().all():
        registry.register(descriptor)
    for descriptor in _descriptors():
        registry.register(descriptor)
    return registry


PHASE_D_STRATEGY_IDS = tuple(d.metadata.strategy_id for d in _descriptors())
