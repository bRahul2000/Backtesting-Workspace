"""Research-only ablation variants of the frozen BTC V3 A4 / T3 / Core.

Phase A of BTC Core V2 research asks one narrow question per experiment: what
does the *candle body* quality gate cost in opportunity, and is the opportunity
it excludes worth having? Nothing here edits a frozen file. Each variant
subclasses the frozen strategy and overrides exactly one parameter, so every
other rule — H1 regime, ADX, structure, pullback state machine, RSI, extension,
stop band, 3R target, session, daily cap — is inherited unchanged.

A variant at the frozen default must behave identically to the frozen strategy.
tests/test_core_v2_phase_a.py asserts that on real data for all three wrappers;
if it ever fails, the wrapper is doing something other than moving one number.

These descriptors are never registered globally. The global registry is what
the Universal Workspace lists, so registering ablation arms there would put all
sixteen of them in the user's strategy dropdown the moment anything imported
this module. ``phase_a_registry()`` returns an isolated registry instead, which
run_universal_backtest accepts directly.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from strategies.base_strategy import (
    ParameterType, StrategyDescriptor, StrategyMetadata, StrategyParameter, StrategyStatus,
)
from strategies.btc_v3_a4_pullback_long import (
    BtcV3A4PullbackLongFrozen, CONFIRMATION_MAX_BODY_PERCENT, V3A4FrozenParameters,
)
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.btc_v3_t3_breakout_short import (
    BtcV3T3BreakoutShortFrozen, V3T3FrozenParameters,
)
from strategies.registry import StrategyRegistry, discover_builtin_strategies
from strategies.universal_catalog import _a4_warmup, _core_warmup, _source_hash, _t3_warmup

#--- The ablation grid. 0.70 is the frozen default and is the control arm.
BODY_THRESHOLDS: tuple[float, ...] = (0.70, 0.60, 0.50, 0.40)
BASELINE_THRESHOLD = 0.70

VARIANT_FILE = "btc_core_v2_variants.py"


def _tag(value: float) -> str:
    return f"{int(round(value * 100)):03d}"


# --- A4: confirmation candle minimum body ------------------------------------


class A4ConfirmationBodyVariant(BtcV3A4PullbackLongFrozen):
    """Frozen A4 with only ``confirmation_min_body_percent`` moved.

    The bullish-candle requirement, the 0.90 upper body cap, the RSI band, the
    previous-high break and the EMA20 close are all inherited untouched.
    """

    def __init__(self, minimum_body_percent: float = BASELINE_THRESHOLD) -> None:
        super().__init__()
        #--- replace() re-runs V3L2Parameters.__post_init__, so an out-of-range
        #--- threshold is rejected by the frozen validator, not by this module.
        self.params = replace(self.params,
                              confirmation_min_body_percent=float(minimum_body_percent))
        self.reset()


# --- T3: breakout candle minimum body ----------------------------------------


def t3_parameters(minimum_body_percent: float) -> V3T3FrozenParameters:
    """Frozen T3 parameters with only ``trend_minimum_body_percent`` moved.

    V3T3FrozenParameters is declared ``init=False`` precisely so the frozen
    strategy cannot be retuned through its constructor, which also means
    dataclasses.replace cannot build one. The override is written directly and
    then handed to the frozen validator.
    """
    params = V3T3FrozenParameters()
    object.__setattr__(params, "trend_minimum_body_percent", float(minimum_body_percent))
    V3T3FrozenParameters.__post_init__(params)
    return params


class T3BreakoutBodyVariant(BtcV3T3BreakoutShortFrozen):
    """Frozen T3 with only the trend breakout body minimum moved."""

    def __init__(self, minimum_body_percent: float = BASELINE_THRESHOLD) -> None:
        super().__init__(t3_parameters(minimum_body_percent))


# --- Core: one child swapped, the other frozen -------------------------------


@dataclass(frozen=True)
class CoreV2Composition:
    """What this Core is composed of, so runs fingerprint distinctly."""
    a4_confirmation_min_body_percent: float = BASELINE_THRESHOLD
    t3_trend_minimum_body_percent: float = BASELINE_THRESHOLD


class CoreV2BodyVariant(BtcV3CoreV1Frozen):
    """The frozen Core composition with one child replaced by a variant.

    The Core's own logic — both children see every candle, only the owning child
    may cancel its pending order, one global position — is inherited unchanged,
    so single-position contention is measured, not modelled.
    """

    def __init__(self, a4_body: float = BASELINE_THRESHOLD,
                 t3_body: float = BASELINE_THRESHOLD) -> None:
        super().__init__()
        self.a4 = A4ConfirmationBodyVariant(a4_body)
        self.t3 = T3BreakoutBodyVariant(t3_body)
        self.params = CoreV2Composition(float(a4_body), float(t3_body))
        self.reset()


# --- Registration ------------------------------------------------------------

A4_VARIANT_IDS = {value: f"RESEARCH_A4_BODY_{_tag(value)}" for value in BODY_THRESHOLDS}
T3_VARIANT_IDS = {value: f"RESEARCH_T3_BODY_{_tag(value)}" for value in BODY_THRESHOLDS}
CORE_A4_VARIANT_IDS = {value: f"RESEARCH_CORE_A4_BODY_{_tag(value)}" for value in BODY_THRESHOLDS}
CORE_T3_VARIANT_IDS = {value: f"RESEARCH_CORE_T3_BODY_{_tag(value)}" for value in BODY_THRESHOLDS}


def _metadata(strategy_id: str, name: str, description: str) -> StrategyMetadata:
    return StrategyMetadata(
        strategy_id=strategy_id, name=name, version="phase-a",
        status=StrategyStatus.RESEARCH, category="ablation",
        supported_instruments=("BTCUSD",), supported_timeframes=("15m",),
        description=description, created_date="2026-09-21",
        strategy_fingerprint=_source_hash(VARIANT_FILE),
    )


def _body_parameter(name: str, value: float) -> StrategyParameter:
    return StrategyParameter(
        name, ParameterType.PERCENTAGE, value,
        description="Phase A ablation arm; fixed for the run.",
        optimization_allowed=False, frozen=True)


def _descriptors() -> tuple[StrategyDescriptor, ...]:
    output: list[StrategyDescriptor] = []
    for value in BODY_THRESHOLDS:
        label = f"{value:.2f}"
        output.append(StrategyDescriptor(
            metadata=_metadata(
                A4_VARIANT_IDS[value], f"Research · A4 confirmation body {label}",
                f"Frozen A4 with confirmation_min_body_percent = {label}."),
            factory=lambda value=value: A4ConfirmationBodyVariant(value),
            parameters=(_body_parameter("confirmation_min_body_percent", value),),
            required_timeframes=("15m", "1h"), warmup_resolver=_a4_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
        output.append(StrategyDescriptor(
            metadata=_metadata(
                T3_VARIANT_IDS[value], f"Research · T3 breakout body {label}",
                f"Frozen T3 with trend_minimum_body_percent = {label}."),
            factory=lambda value=value: T3BreakoutBodyVariant(value),
            parameters=(_body_parameter("trend_minimum_body_percent", value),),
            required_timeframes=("15m", "1h"), warmup_resolver=_t3_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
        output.append(StrategyDescriptor(
            metadata=_metadata(
                CORE_A4_VARIANT_IDS[value], f"Research · Core, A4 body {label}, T3 frozen",
                f"Frozen Core with A4 confirmation_min_body_percent = {label}; T3 unchanged."),
            factory=lambda value=value: CoreV2BodyVariant(a4_body=value),
            parameters=(_body_parameter("a4_confirmation_min_body_percent", value),),
            required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
        output.append(StrategyDescriptor(
            metadata=_metadata(
                CORE_T3_VARIANT_IDS[value], f"Research · Core, T3 body {label}, A4 frozen",
                f"Frozen Core with T3 trend_minimum_body_percent = {label}; A4 unchanged."),
            factory=lambda value=value: CoreV2BodyVariant(t3_body=value),
            parameters=(_body_parameter("t3_trend_minimum_body_percent", value),),
            required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
    return tuple(output)


def phase_a_registry() -> StrategyRegistry:
    """A private registry: every builtin strategy plus the ablation arms.

    The builtins are included so a research run can compare an arm against its
    frozen counterpart through one registry, without mutating the global one.
    """
    registry = StrategyRegistry()
    for descriptor in discover_builtin_strategies().all():
        registry.register(descriptor)
    for descriptor in _descriptors():
        registry.register(descriptor)
    return registry


PHASE_A_STRATEGY_IDS = tuple(d.metadata.strategy_id for d in _descriptors())

#--- The A4 upper body cap is not part of this ablation; re-exported so a test
#--- can assert it never moved.
UPPER_BODY_CAP = CONFIRMATION_MAX_BODY_PERCENT
