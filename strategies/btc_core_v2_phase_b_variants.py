"""Research-only Phase B variants: A4 confirmation timing, T3 structure lookback.

Phase B asks about *structural opportunity* rather than candle quality, so the
Phase A conclusion is carried in unchanged: A4 and T3 body thresholds stay at
0.70 and the reward multiple stays at 3R.

A note on the A4 arm, because the shape of the experiment is not what it looks
like. An armed A4 pullback does **not** get one bar to confirm. It stays armed
indefinitely and is cleared only by the frozen invalidation rules — trend or
EMA50 context loss, excess depth, session end, the daily cap, or a confirmation
firing. On the development split the median confirmation arrives on the *fourth*
bar of the pullback and the tail runs to twenty-one, so there is no one-bar
window to widen. A bounded window is therefore *tighter* than the frozen
behaviour, and these arms remove opportunity rather than adding it. That is
still worth measuring: it asks whether late confirmations are worth having.

The window is applied by withdrawing the confirmation *opportunity* once the
pullback is older than the window, never by touching pullback state. Pullback
low, depth, structure level and every invalidation rule keep behaving exactly as
the frozen strategy does, so the arm isolates timing and nothing else. Blocking
is done by rebinding the A4 module's ``confirmation_passes`` for the duration of
one call, which is the same mechanism the frozen A4 wrapper itself uses to
install its overlay — so the real predicate, with all its quality conditions, is
what runs whenever the window is open.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

import strategies.btc_v3_a4_pullback_long as _a4
from strategies.base_strategy import (
    ParameterType, StrategyDescriptor, StrategyMetadata, StrategyParameter, StrategyStatus,
)
from strategies.universal_catalog import _a4_warmup, _core_warmup, _source_hash, _t3_warmup
from strategies.btc_v3_a4_pullback_long import BtcV3A4PullbackLongFrozen
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.btc_v3_t3_breakout_short import BtcV3T3BreakoutShortFrozen, V3T3FrozenParameters
from strategies.registry import StrategyRegistry, discover_builtin_strategies

#--- None is the frozen behaviour: an armed pullback waits until invalidated.
UNBOUNDED = None
A4_CONFIRMATION_WINDOWS: tuple[int | None, ...] = (UNBOUNDED, 3, 2, 1)
A4_BASELINE_WINDOW = UNBOUNDED

T3_STRUCTURE_LOOKBACKS: tuple[int, ...] = (6, 5, 4, 3)
T3_BASELINE_LOOKBACK = 5

VARIANT_FILE = "btc_core_v2_phase_b_variants.py"


def window_tag(window: int | None) -> str:
    return "UNBOUNDED" if window is None else f"{window:02d}"


# --- A4 confirmation window ---------------------------------------------------


@contextmanager
def _confirmation_withdrawn(active: bool):
    """Temporarily make the A4 confirmation predicate decline, for one call.

    ``_validated_a4_call_context`` reads the A4 module global at call time and
    installs it into the L2 module, so rebinding it here is what the frozen
    strategy will actually consult. Nothing else about the bar changes.
    """
    if not active:
        yield
        return
    original = _a4.confirmation_passes
    _a4.confirmation_passes = lambda *args, **kwargs: False
    try:
        yield
    finally:
        _a4.confirmation_passes = original


class A4ConfirmationWindowVariant(BtcV3A4PullbackLongFrozen):
    """Frozen A4, with the confirmation opportunity bounded to N bars."""

    def __init__(self, window_bars: int | None = A4_BASELINE_WINDOW) -> None:
        super().__init__()
        if window_bars is not None and (not isinstance(window_bars, int)
                                        or isinstance(window_bars, bool) or window_bars < 1):
            raise ValueError("Confirmation window must be a positive integer or None.")
        self.window_bars = window_bars

    def on_candle(self, candle):
        #--- The frozen bar increments pullback_bars before testing confirmation,
        #--- so the test sees this value plus one. The pullback's start bar holds
        #--- 1 and the first testable bar sees 2, which is window 1.
        expired = (self.window_bars is not None and self.pullback_active
                   and self.pullback_bars > self.window_bars)
        with _confirmation_withdrawn(expired):
            return super().on_candle(candle)


# --- T3 structure lookback ----------------------------------------------------


def t3_parameters(structure_lookback: int) -> V3T3FrozenParameters:
    """Frozen T3 parameters with only ``trend_structure_lookback`` moved."""
    params = V3T3FrozenParameters()
    object.__setattr__(params, "trend_structure_lookback", int(structure_lookback))
    V3T3FrozenParameters.__post_init__(params)
    return params


class T3StructureLookbackVariant(BtcV3T3BreakoutShortFrozen):
    """Frozen T3 with only the prior-low structure lookback moved.

    Break semantics are untouched: the frozen source still requires
    ``close < trend_previous_low``; only how many bars that low is taken over
    changes. The candle deque is sized by the largest lookback T3 uses, which is
    the range sweep window at 8, so every arm here keeps the same history depth.
    """

    def __init__(self, structure_lookback: int = T3_BASELINE_LOOKBACK) -> None:
        super().__init__(t3_parameters(structure_lookback))


# --- Core composition ---------------------------------------------------------


@dataclass(frozen=True)
class CoreV2PhaseBComposition:
    a4_confirmation_window_bars: int | None = A4_BASELINE_WINDOW
    t3_trend_structure_lookback: int = T3_BASELINE_LOOKBACK


class CoreV2PhaseBVariant(BtcV3CoreV1Frozen):
    """The frozen Core with one child replaced; the other stays frozen."""

    def __init__(self, a4_window: int | None = A4_BASELINE_WINDOW,
                 t3_lookback: int = T3_BASELINE_LOOKBACK) -> None:
        super().__init__()
        self.a4 = A4ConfirmationWindowVariant(a4_window)
        self.t3 = T3StructureLookbackVariant(t3_lookback)
        self.params = CoreV2PhaseBComposition(a4_window, int(t3_lookback))
        self.reset()


# --- Registration -------------------------------------------------------------

A4_WINDOW_IDS = {value: f"RESEARCH_A4_WINDOW_{window_tag(value)}"
                 for value in A4_CONFIRMATION_WINDOWS}
T3_LOOKBACK_IDS = {value: f"RESEARCH_T3_LOOKBACK_{value:02d}"
                   for value in T3_STRUCTURE_LOOKBACKS}
CORE_A4_WINDOW_IDS = {value: f"RESEARCH_CORE_A4_WINDOW_{window_tag(value)}"
                      for value in A4_CONFIRMATION_WINDOWS}
CORE_T3_LOOKBACK_IDS = {value: f"RESEARCH_CORE_T3_LOOKBACK_{value:02d}"
                        for value in T3_STRUCTURE_LOOKBACKS}


def _metadata(strategy_id: str, name: str, description: str) -> StrategyMetadata:
    return StrategyMetadata(
        strategy_id=strategy_id, name=name, version="phase-b",
        status=StrategyStatus.RESEARCH, category="ablation",
        supported_instruments=("BTCUSD",), supported_timeframes=("15m",),
        description=description, created_date="2026-09-21",
        strategy_fingerprint=_source_hash(VARIANT_FILE),
    )


def _parameter(name: str, kind: ParameterType, value) -> StrategyParameter:
    return StrategyParameter(name, kind, value,
                             description="Phase B ablation arm; fixed for the run.",
                             optimization_allowed=False, frozen=True)


def _descriptors() -> tuple[StrategyDescriptor, ...]:
    output: list[StrategyDescriptor] = []
    for window in A4_CONFIRMATION_WINDOWS:
        label = "unbounded" if window is None else f"{window} bar(s)"
        output.append(StrategyDescriptor(
            metadata=_metadata(A4_WINDOW_IDS[window],
                               f"Research · A4 confirmation window {label}",
                               f"Frozen A4; confirmation opportunity bounded to {label}."),
            factory=lambda window=window: A4ConfirmationWindowVariant(window),
            parameters=(_parameter("confirmation_window_bars", ParameterType.INTEGER,
                                   -1 if window is None else window),),
            required_timeframes=("15m", "1h"), warmup_resolver=_a4_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
        output.append(StrategyDescriptor(
            metadata=_metadata(CORE_A4_WINDOW_IDS[window],
                               f"Research · Core, A4 window {label}, T3 frozen",
                               f"Frozen Core; A4 confirmation window {label}; T3 unchanged."),
            factory=lambda window=window: CoreV2PhaseBVariant(a4_window=window),
            parameters=(_parameter("a4_confirmation_window_bars", ParameterType.INTEGER,
                                   -1 if window is None else window),),
            required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
    for lookback in T3_STRUCTURE_LOOKBACKS:
        output.append(StrategyDescriptor(
            metadata=_metadata(T3_LOOKBACK_IDS[lookback],
                               f"Research · T3 structure lookback {lookback}",
                               f"Frozen T3; trend_structure_lookback = {lookback}."),
            factory=lambda lookback=lookback: T3StructureLookbackVariant(lookback),
            parameters=(_parameter("trend_structure_lookback", ParameterType.INTEGER, lookback),),
            required_timeframes=("15m", "1h"), warmup_resolver=_t3_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
        output.append(StrategyDescriptor(
            metadata=_metadata(CORE_T3_LOOKBACK_IDS[lookback],
                               f"Research · Core, T3 lookback {lookback}, A4 frozen",
                               f"Frozen Core; T3 trend_structure_lookback = {lookback}; A4 unchanged."),
            factory=lambda lookback=lookback: CoreV2PhaseBVariant(t3_lookback=lookback),
            parameters=(_parameter("t3_trend_structure_lookback", ParameterType.INTEGER, lookback),),
            required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
    return tuple(output)


def phase_b_registry() -> StrategyRegistry:
    """An isolated registry: every builtin strategy plus the Phase B arms.

    Never the global registry, which is what the Universal Workspace lists.
    """
    registry = StrategyRegistry()
    for descriptor in discover_builtin_strategies().all():
        registry.register(descriptor)
    for descriptor in _descriptors():
        registry.register(descriptor)
    return registry


PHASE_B_STRATEGY_IDS = tuple(d.metadata.strategy_id for d in _descriptors())
