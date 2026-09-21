"""Research-only Phase E wrappers around the frozen D2 A4-SHORT mirror.

D2 itself is frozen for this phase. Its implementation lives in
``btc_core_v2_phase_d_families`` and is not touched here: every sensitivity arm
subclasses it and moves exactly one threshold, and the integration policies
compose it rather than editing it. ``D2_IMPLEMENTATION_HASH`` pins the three
source objects that make up D2, so a test fails the moment the baseline drifts.

Two integration policies are compared, and only two.

*Policy 1* is the Phase D integration, reused unchanged: on a bar where the
frozen pair signals, the frozen pair wins; on a bar where it does not, D2 may
take the single global slot — and once it holds that slot it blocks whatever
the frozen pair would have done next.

*Policy 2* removes that second effect. D2 may open a position only on a bar
where the **baseline** frozen Core had neither a position nor a pending order,
so by construction it cannot take a slot the frozen pair was going to use. The
baseline timeline is measured from a frozen-Core run and injected, which makes
the policy deterministic and replayable rather than a heuristic. A D2 setup that
arrives while the baseline is busy is discarded, not queued: "may act only when"
means the opportunity is lost, and counting it as deferred would flatter it.
"""
from __future__ import annotations

from bisect import bisect_right
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import inspect
from typing import Iterable, Sequence

import pandas as pd

from engine.models import Candle, Signal
from strategies.base_strategy import (
    ParameterType, StrategyDescriptor, StrategyMetadata, StrategyParameter, StrategyStatus,
)
from strategies.btc_core_v2_phase_d_families import (
    CoreWithFamily, D2_SETUP_ID, D2A4ShortMirror, h1_bearish, short_confirmation_passes,
)
from strategies.btc_v3_a4_pullback_long import MINIMUM_NORMALIZED_H1_SLOPE
from strategies.registry import StrategyRegistry, discover_builtin_strategies
from strategies.universal_catalog import _a4_warmup, _core_warmup, _source_hash

VARIANT_FILE = "btc_core_v2_phase_e_variants.py"

#--- The frozen D2 baseline for this phase.
D2_IMPLEMENTATION_HASH = "16b07458a0049b118cbb0003b9250e4653d6706460ab1e4c601a14679cde6a6e"


def d2_implementation_hash() -> str:
    """SHA-256 over the three source objects that constitute D2."""
    payload = "".join(inspect.getsource(obj) for obj in
                      (h1_bearish, short_confirmation_passes, D2A4ShortMirror))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def assert_d2_unchanged() -> str:
    digest = d2_implementation_hash()
    if digest != D2_IMPLEMENTATION_HASH:
        raise RuntimeError(
            f"D2 baseline implementation changed: expected {D2_IMPLEMENTATION_HASH}, "
            f"got {digest}. Phase E may not modify D2.")
    return digest


# --- Sensitivity arms: one threshold each ---------------------------------------

#--- Mechanically mirrored from A4 into D2, and therefore candidates for a
#--- sensitivity check. The first three are the continuous thresholds the brief
#--- names; the rest are listed so the mirror's full surface is on the record.
MIRRORED_PARAMETERS: tuple[tuple[str, str], ...] = (
    ("confirmation_min_body_percent", "0.70 — body of the bearish reclaim candle"),
    ("mirrored_rsi_band", "30–52, reflection of A4's 48–70 about 50"),
    ("minimum_normalized_h1_slope", "0.15 — |H1 EMA200 slope| / H1 ATR"),
    ("confirmation_max_body_percent", "0.90 — A4 overlay cap, not perturbed"),
    ("max_pullback_depth_below_ema20_atr", "1.00 — rally depth above EMA20"),
    ("material_ema50_close_atr", "0.20 — close materially above EMA50 invalidates"),
    ("h1_min_separation_atr", "1.00 — confirmed H1 EMA separation"),
    ("min_adx", "18.0 — M15 ADX floor"),
    ("local_structure_lookback", "5 bars — prior low that defines a structure break"),
    ("entry_buffer_atr / stop_buffer_atr", "0.05 / 0.20"),
    ("minimum_stop_atr / maximum_stop_atr", "0.50 / 3.00"),
    ("pending_bars", "2"),
    ("reward_multiple", "3.0 — fixed, never perturbed"),
)

BODY_THRESHOLDS: tuple[float, ...] = (0.65, 0.70, 0.75)
RSI_BAND_OFFSETS: tuple[float, ...] = (-2.0, 0.0, 2.0)
SLOPE_THRESHOLDS: tuple[float, ...] = (0.10, 0.15, 0.20)
BASELINE_BODY, BASELINE_OFFSET, BASELINE_SLOPE = 0.70, 0.0, MINIMUM_NORMALIZED_H1_SLOPE


class D2BodyVariant(D2A4ShortMirror):
    """D2 with only the confirmation body minimum moved."""

    def __init__(self, minimum_body_percent: float = BASELINE_BODY) -> None:
        super().__init__()
        self.params = replace(self.params,
                              confirmation_min_body_percent=float(minimum_body_percent))
        self.reset()


class D2RsiBandVariant(D2A4ShortMirror):
    """D2 with the mirrored RSI band shifted as a whole.

    D2 derives its band as ``100 - confirmation_rsi_max`` to
    ``100 - confirmation_rsi_min``, so shifting the mirrored band up by ``offset``
    means moving both A4 bounds down by the same amount. The width never changes.
    """

    def __init__(self, offset: float = BASELINE_OFFSET) -> None:
        super().__init__()
        self.band_offset = float(offset)
        self.params = replace(
            self.params,
            confirmation_rsi_min=self.params.confirmation_rsi_min - float(offset),
            confirmation_rsi_max=self.params.confirmation_rsi_max - float(offset))
        self.reset()

    @property
    def mirrored_band(self) -> tuple[float, float]:
        return (100 - self.params.confirmation_rsi_max,
                100 - self.params.confirmation_rsi_min)


class D2SlopeVariant(D2A4ShortMirror):
    """D2 with only the normalized H1 slope magnitude moved."""

    def __init__(self, threshold: float = BASELINE_SLOPE) -> None:
        super().__init__()
        self.slope_threshold = float(threshold)

    def _context_valid(self, h1, ema20: float, ema50: float, adx: float | None) -> bool:
        return (
            h1_bearish(h1, self.params)
            and ema20 < ema50
            and adx is not None and adx >= self.params.min_adx
            and h1.slope is not None and h1.atr is not None and h1.atr > 0
            and (-h1.slope) / h1.atr >= self.slope_threshold
        )


SENSITIVITY_ARMS: dict[str, tuple[str, tuple, type]] = {
    "BODY": ("confirmation_min_body_percent", BODY_THRESHOLDS, D2BodyVariant),
    "RSI": ("mirrored_rsi_band_offset", RSI_BAND_OFFSETS, D2RsiBandVariant),
    "SLOPE": ("minimum_normalized_h1_slope", SLOPE_THRESHOLDS, D2SlopeVariant),
}
ARM_BASELINE = {"BODY": BASELINE_BODY, "RSI": BASELINE_OFFSET, "SLOPE": BASELINE_SLOPE}


def arm_tag(value: float) -> str:
    return f"{value:+.2f}".replace(".", "P").replace("+", "P").replace("-", "M")


# --- Policy 2: D2 acts only in the baseline Core's gaps ----------------------------


_BASELINE_BUSY: tuple[tuple[pd.Timestamp, pd.Timestamp], ...] = ()


@contextmanager
def baseline_timeline(intervals: Iterable[tuple[pd.Timestamp, pd.Timestamp]]):
    """Install the frozen-Core busy timeline that Policy 2 reads."""
    global _BASELINE_BUSY
    previous = _BASELINE_BUSY
    _BASELINE_BUSY = tuple(sorted((pd.Timestamp(start), pd.Timestamp(end))
                                  for start, end in intervals))
    try:
        yield
    finally:
        _BASELINE_BUSY = previous


class CoreWithD2Policy1(CoreWithFamily):
    """The Phase D integration, reused unchanged, named for the comparison."""

    def __init__(self) -> None:
        super().__init__("D2")


class CoreWithD2Policy2(CoreWithFamily):
    """Frozen-Core priority: D2 may open only where the baseline Core was idle."""

    def __init__(self) -> None:
        super().__init__("D2")
        if not _BASELINE_BUSY:
            raise RuntimeError(
                "Policy 2 needs the frozen-Core baseline timeline; wrap the run in "
                "baseline_timeline(...).")
        self._starts = [start for start, _ in _BASELINE_BUSY]
        self._ends = [end for _, end in _BASELINE_BUSY]
        self.suppressed_signals = 0

    def _baseline_busy(self, stamp: pd.Timestamp) -> bool:
        index = bisect_right(self._starts, stamp)
        #--- Intervals are short and rarely nested; checking the few that start
        #--- at or before this bar is exact and cheap.
        return any(self._ends[i] >= stamp for i in range(max(0, index - 8), index))

    def on_candle(self, candle: Candle):
        action = super().on_candle(candle)
        if (isinstance(action, Signal) and action.setup_id == self.family_setup_id
                and self._baseline_busy(candle.timestamp)):
            #--- Discarded, not queued: "may act only when" means the opportunity
            #--- is lost, and deferring it would flatter the policy.
            self.suppressed_signals += 1
            return None
        return action


def order_events(result) -> list:
    """Per-order events, which live on the segment results, not on the summary."""
    return [event for segment in result.legacy_segment_results
            for event in segment.order_events]


def busy_intervals(result) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Every bar the frozen Core held a position or a live pending order."""
    from core.trade_log import to_timestamp

    intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for row in result.trade_log:
        intervals.append((to_timestamp(row["entry_time"]), to_timestamp(row["exit_time"])))
    for event in order_events(result):
        finish = event.fill_time if event.fill_time is not None else event.expiry_time
        intervals.append((pd.Timestamp(event.created_time), pd.Timestamp(finish)))
    return sorted(intervals)


# --- Registration -------------------------------------------------------------------

D2_BASELINE_ID = "RESEARCH_D2_STANDALONE"
POLICY_IDS = {"POLICY1": "RESEARCH_CORE_D2_POLICY1", "POLICY2": "RESEARCH_CORE_D2_POLICY2"}
SENSITIVITY_IDS = {
    (arm, value): f"RESEARCH_D2_{arm}_{arm_tag(value)}"
    for arm, (_, values, _) in SENSITIVITY_ARMS.items() for value in values
}
SENSITIVITY_CORE_IDS = {
    (arm, value): f"RESEARCH_CORE_D2_{arm}_{arm_tag(value)}"
    for arm, (_, values, _) in SENSITIVITY_ARMS.items() for value in values
}


@dataclass(frozen=True)
class _Composition:
    arm: str
    value: float


class CoreWithD2Sensitivity(CoreWithFamily):
    """Frozen A4 + frozen T3 + one perturbed D2, Policy 1 integration."""

    def __init__(self, arm: str, value: float) -> None:
        super().__init__("D2")
        self.family = SENSITIVITY_ARMS[arm][2](value)
        self.params = _Composition(arm, float(value))
        self.reset()


def _metadata(strategy_id: str, name: str, description: str) -> StrategyMetadata:
    return StrategyMetadata(
        strategy_id=strategy_id, name=name, version="phase-e",
        status=StrategyStatus.RESEARCH, category="stability",
        supported_instruments=("BTCUSD",), supported_timeframes=("15m",),
        description=description, created_date="2026-09-21",
        strategy_fingerprint=_source_hash(VARIANT_FILE),
    )


def _parameter(value: str) -> tuple[StrategyParameter, ...]:
    return (StrategyParameter("phase_e_arm", ParameterType.STRING, value,
                              description="Phase E arm; fixed for the run.",
                              optimization_allowed=False, frozen=True),)


def _descriptors() -> tuple[StrategyDescriptor, ...]:
    output = [
        StrategyDescriptor(
            metadata=_metadata(POLICY_IDS["POLICY1"], "Research · Core + D2 (policy 1)",
                               "Frozen Core + D2, Phase D integration ordering."),
            factory=CoreWithD2Policy1, parameters=_parameter("POLICY1"),
            required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"),
        StrategyDescriptor(
            metadata=_metadata(POLICY_IDS["POLICY2"], "Research · Core + D2 (policy 2)",
                               "Frozen Core + D2, D2 acts only where baseline Core was idle."),
            factory=CoreWithD2Policy2, parameters=_parameter("POLICY2"),
            required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
            execution_profile="EXNESS_SYNTHETIC_BID_ASK"),
    ]
    for arm, (label, values, builder) in SENSITIVITY_ARMS.items():
        for value in values:
            output.append(StrategyDescriptor(
                metadata=_metadata(SENSITIVITY_IDS[(arm, value)],
                                   f"Research · D2 {label} {value}",
                                   f"D2 standalone with {label} = {value}."),
                factory=(lambda builder=builder, value=value: builder(value)),
                parameters=_parameter(f"{arm}={value}"),
                required_timeframes=("15m", "1h"), warmup_resolver=_a4_warmup,
                execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
            output.append(StrategyDescriptor(
                metadata=_metadata(SENSITIVITY_CORE_IDS[(arm, value)],
                                   f"Research · Core + D2 {label} {value}",
                                   f"Frozen Core + D2 with {label} = {value}."),
                factory=(lambda arm=arm, value=value: CoreWithD2Sensitivity(arm, value)),
                parameters=_parameter(f"CORE:{arm}={value}"),
                required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
                execution_profile="EXNESS_SYNTHETIC_BID_ASK"))
    return tuple(output)


def phase_e_registry() -> StrategyRegistry:
    """An isolated registry, including the Phase D arms this phase builds on."""
    from strategies.btc_core_v2_phase_d_families import _descriptors as phase_d_descriptors

    registry = StrategyRegistry()
    for descriptor in discover_builtin_strategies().all():
        registry.register(descriptor)
    for descriptor in phase_d_descriptors():
        registry.register(descriptor)
    for descriptor in _descriptors():
        registry.register(descriptor)
    return registry


PHASE_E_STRATEGY_IDS = tuple(d.metadata.strategy_id for d in _descriptors())
