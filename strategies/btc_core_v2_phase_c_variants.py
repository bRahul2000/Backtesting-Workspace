"""Research-only Phase C variants: T3 break-definition sensitivity at a fixed lookback.

Phase C exists to decide whether the Phase B lookback-4 lead is structural or
noise. This module supplies the one new kind of arm it needs: the same frozen T3
with the same lookback, but with the level its close must break shifted by an
amount small enough to be conceptually irrelevant.

Why the level and not the comparison. The frozen break is
``close < obs.trend_previous_low`` inside ``evaluate_v3``. Rewriting that
comparison would mean reimplementing the function, which is exactly what this
research must not do. Shifting ``trend_previous_low`` on the observation instead
leaves the frozen comparison, the frozen stop (taken from ``trend_stop_high``,
not from this level) and every other rule untouched, and expresses "break by at
least X" exactly. A negative shift expresses the looser direction.

One definition from the brief does not map cleanly. ``close <= prior low``
cannot be written as a level shift, because no finite shift turns a strict ``<``
into ``<=``. A one-tick loosening (shift of -1 tick) is the narrowest equivalent
the frozen architecture supports, and it admits the ``close == prior low`` case
that ``<=`` was meant to probe, so that is what is tested.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, replace

import strategies.btc_v3_t3_breakout_short as _t3
from instruments.btcusd import BTCUSD
from strategies.base_strategy import (
    ParameterType, StrategyDescriptor, StrategyMetadata, StrategyParameter, StrategyStatus,
)
from strategies.btc_core_v2_phase_b_variants import T3StructureLookbackVariant
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.registry import StrategyRegistry, discover_builtin_strategies
from strategies.universal_catalog import _core_warmup, _source_hash, _t3_warmup

VARIANT_FILE = "btc_core_v2_phase_c_variants.py"

#--- BTCUSD quotes to two decimals; one tick is the smallest price move that
#--- can exist, so a one-tick shift is the smallest possible change of meaning.
TICK_SIZE = BTCUSD.tick_size

LOOKBACKS_UNDER_TEST: tuple[int, ...] = (5, 4)


@dataclass(frozen=True)
class BreakDefinition:
    """How far below the prior low the close must settle."""
    key: str
    label: str
    ticks: float = 0.0
    atr: float = 0.0

    @property
    def is_frozen_semantics(self) -> bool:
        return self.ticks == 0.0 and self.atr == 0.0


#--- Ordered loosest to strictest. FROZEN is the unmodified comparison.
BREAK_DEFINITIONS: tuple[BreakDefinition, ...] = (
    BreakDefinition("LOOSER_1_TICK", "close below prior low, one tick of tolerance", ticks=-1.0),
    BreakDefinition("FROZEN", "close strictly below prior low (frozen)"),
    BreakDefinition("STRICT_1_TICK", "close below prior low by at least one tick", ticks=1.0),
    BreakDefinition("STRICT_0P01_ATR", "close below prior low by at least 0.01 ATR", atr=0.01),
    BreakDefinition("STRICT_0P02_ATR", "close below prior low by at least 0.02 ATR", atr=0.02),
    BreakDefinition("STRICT_0P05_ATR", "close below prior low by at least 0.05 ATR", atr=0.05),
)
BREAK_BY_KEY = {item.key: item for item in BREAK_DEFINITIONS}


@contextmanager
def _break_level_shifted(definition: BreakDefinition):
    """Shift the level the frozen break test compares against, for one call.

    ``on_candle`` resolves ``evaluate_v3`` as a module global at call time, so
    rebinding it here is what the frozen strategy will actually run — the same
    mechanism the frozen A4 wrapper uses to install its own overlay.
    """
    if definition.is_frozen_semantics:
        yield
        return
    original = _t3.evaluate_v3

    def shifted(obs, params, counters=None):
        low = obs.trend_previous_low
        if low is not None:
            buffer = definition.ticks * TICK_SIZE + definition.atr * (obs.atr or 0.0)
            obs = replace(obs, trend_previous_low=low - buffer)
        return original(obs, params, counters)

    _t3.evaluate_v3 = shifted
    try:
        yield
    finally:
        _t3.evaluate_v3 = original


class T3BreakDefinitionVariant(T3StructureLookbackVariant):
    """Frozen T3 at a fixed lookback, with the break level shifted."""

    def __init__(self, structure_lookback: int = 4, definition: str = "FROZEN") -> None:
        super().__init__(structure_lookback)
        if definition not in BREAK_BY_KEY:
            raise ValueError(f"Unknown break definition: {definition!r}")
        self.break_definition = BREAK_BY_KEY[definition]

    def on_candle(self, candle):
        with _break_level_shifted(self.break_definition):
            return super().on_candle(candle)


class CoreV2PhaseCVariant(BtcV3CoreV1Frozen):
    """Frozen Core with T3 replaced; A4 stays exactly frozen."""

    def __init__(self, structure_lookback: int = 4, definition: str = "FROZEN") -> None:
        super().__init__()
        self.t3 = T3BreakDefinitionVariant(structure_lookback, definition)
        self.params = _CoreComposition(int(structure_lookback), definition)
        self.reset()


@dataclass(frozen=True)
class _CoreComposition:
    t3_trend_structure_lookback: int
    t3_break_definition: str


# --- Registration ---------------------------------------------------------------

BREAK_IDS = {(lookback, item.key): f"RESEARCH_T3_L{lookback}_BREAK_{item.key}"
             for lookback in LOOKBACKS_UNDER_TEST for item in BREAK_DEFINITIONS}
CORE_BREAK_IDS = {(lookback, item.key): f"RESEARCH_CORE_T3_L{lookback}_BREAK_{item.key}"
                  for lookback in LOOKBACKS_UNDER_TEST for item in BREAK_DEFINITIONS}


def _metadata(strategy_id: str, name: str, description: str) -> StrategyMetadata:
    return StrategyMetadata(
        strategy_id=strategy_id, name=name, version="phase-c",
        status=StrategyStatus.RESEARCH, category="ablation",
        supported_instruments=("BTCUSD",), supported_timeframes=("15m",),
        description=description, created_date="2026-09-21",
        strategy_fingerprint=_source_hash(VARIANT_FILE),
    )


def _descriptors() -> tuple[StrategyDescriptor, ...]:
    output: list[StrategyDescriptor] = []
    for lookback in LOOKBACKS_UNDER_TEST:
        for item in BREAK_DEFINITIONS:
            output.append(StrategyDescriptor(
                metadata=_metadata(
                    BREAK_IDS[(lookback, item.key)],
                    f"Research · T3 lookback {lookback}, break {item.key}",
                    f"Frozen T3, lookback {lookback}; {item.label}."),
                factory=(lambda lookback=lookback, key=item.key:
                         T3BreakDefinitionVariant(lookback, key)),
                parameters=(StrategyParameter(
                    "break_definition", ParameterType.STRING, f"L{lookback}:{item.key}",
                    description="Phase C sensitivity arm; fixed for the run.",
                    optimization_allowed=False, frozen=True),),
                required_timeframes=("15m", "1h"), warmup_resolver=_t3_warmup,
                execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
            output.append(StrategyDescriptor(
                metadata=_metadata(
                    CORE_BREAK_IDS[(lookback, item.key)],
                    f"Research · Core, T3 lookback {lookback}, break {item.key}",
                    f"Frozen Core; A4 frozen; T3 lookback {lookback}; {item.label}."),
                factory=(lambda lookback=lookback, key=item.key:
                         CoreV2PhaseCVariant(lookback, key)),
                parameters=(StrategyParameter(
                    "break_definition", ParameterType.STRING, f"CORE:L{lookback}:{item.key}",
                    description="Phase C sensitivity arm; fixed for the run.",
                    optimization_allowed=False, frozen=True),),
                required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
                execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
    return tuple(output)


def phase_c_registry() -> StrategyRegistry:
    """An isolated registry; never the global one the workspace lists."""
    registry = StrategyRegistry()
    for descriptor in discover_builtin_strategies().all():
        registry.register(descriptor)
    for descriptor in _descriptors():
        registry.register(descriptor)
    return registry


PHASE_C_STRATEGY_IDS = tuple(d.metadata.strategy_id for d in _descriptors())
