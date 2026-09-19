from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pandas as pd

from core.fingerprints import sha256_file, stable_fingerprint
from research.v3_l2_trend_pullback_baseline import warmup_plan as l2_warmup
from research.v3_m1_momentum_expansion_baseline import warmup_plan as m1_warmup
from research.v3_mr1_intraday_overshoot_mean_reversion_baseline import warmup_plan as mr1_warmup
from research.v3_r2_range_liquidity_sweep_baseline import warmup_plan as r2_warmup
from research.v3_regime_adaptive_baseline import v3_warmup_plan
from strategies.base_strategy import (
    ParameterType, StrategyDescriptor, StrategyMetadata, StrategyParameter,
    StrategyStatus,
)
from strategies.registry import register_strategy
from strategies.btc_v3_a4_pullback_long import (
    BtcV3A4PullbackLongFrozen, V3A4FrozenParameters,
)
from strategies.btc_v3_t3_breakout_short import (
    BtcV3T3BreakoutShortFrozen, V3T3FrozenParameters,
)
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.btc_v3_r2_range_liquidity_sweep import (
    BtcV3R2RangeLiquiditySweepReversal, V3R2Parameters,
)
from strategies.btc_v3_m1_momentum_expansion_continuation import (
    BtcV3M1MomentumExpansionContinuation, V3M1Parameters,
)
from strategies.btc_v3_mr1_intraday_overshoot_mean_reversion import (
    BtcV3MR1IntradayOvershootMeanReversion, V3MR1Parameters,
)
from strategies.btc_pb1_shallow_pullback import BtcPB1ShallowPullback, PB1Parameters
from strategies.btc_pb2_reclaim_acceptance import (
    ACCEPTANCE_MODES, ACCEPTANCE_STRICT, PB2Parameters,
)
from strategies.btc_pb2_reclaim_long import BtcPB2ReclaimLong
from strategies.btc_pb2_reclaim_short import BtcPB2ReclaimShort

ROOT = Path(__file__).resolve().parents[1]


def _source_hash(*filenames: str) -> str:
    """Fingerprint a strategy's source.

    A single-file strategy hashes exactly as before. A strategy split across a
    component file and a shared implementation core hashes all of its files, so
    the fingerprint still moves when any code the strategy actually runs
    changes — a thin subclass alone would not be a meaningful fingerprint.
    """
    hashes = [sha256_file(ROOT / "strategies" / filename) for filename in filenames]
    return hashes[0] if len(hashes) == 1 else stable_fingerprint(hashes)


def _frozen(name: str, typ: ParameterType, default, description: str = "") -> StrategyParameter:
    return StrategyParameter(name, typ, default, description=description,
                             optimization_allowed=False, frozen=True)


def _mutable(name: str, typ: ParameterType, default, minimum=None, maximum=None, step=None,
             description: str = "") -> StrategyParameter:
    return StrategyParameter(name, typ, default, minimum, maximum, step, description,
                             optimization_allowed=True, frozen=False)


def _meta(strategy_id, name, version, status, category, description, *filenames):
    return StrategyMetadata(
        strategy_id=strategy_id, name=name, version=version, status=status,
        category=category, supported_instruments=("BTCUSD",),
        supported_timeframes=("15m",), description=description,
        created_date="2026-09-18", strategy_fingerprint=_source_hash(*filenames),
    )


def _a4_warmup(start):
    return l2_warmup(V3A4FrozenParameters(), start).first_search_time


def _t3_warmup(start):
    return v3_warmup_plan(V3T3FrozenParameters(), start).first_search_time


def _core_warmup(start):
    return max(_a4_warmup(start), _t3_warmup(start))


register_strategy(StrategyDescriptor(
    metadata=_meta("BTC_V3_A4_PULLBACK_LONG_FROZEN", "BTC V3 — A4 Pullback Long [Frozen]", "1.0",
                   StrategyStatus.FROZEN, "trend_pullback",
                   "Validated long-side V3-L2 A4 pullback component.", "btc_v3_a4_pullback_long.py"),
    factory=BtcV3A4PullbackLongFrozen,
    parameters=(
        _frozen("confirmation_min_body_percent", ParameterType.PERCENTAGE, 0.70),
        _frozen("confirmation_max_body_percent", ParameterType.PERCENTAGE, 0.90),
        _frozen("minimum_normalized_h1_slope", ParameterType.ATR_MULTIPLE, 0.15),
        _frozen("maximum_stop_atr", ParameterType.ATR_MULTIPLE, 3.00),
        _frozen("reward_multiple", ParameterType.FLOAT, 3.0),
    ),
    required_indicators=("H1 EMA50", "H1 EMA200", "H1 ATR14", "M15 EMA20", "M15 EMA50", "ADX14", "RSI14", "ATR14"),
    required_timeframes=("15m", "1h"), warmup_resolver=_a4_warmup,
    execution_profile="EXNESS_SYNTHETIC_BID_ASK",
))

register_strategy(StrategyDescriptor(
    metadata=_meta("BTC_V3_T3_BREAKOUT_SHORT_FROZEN", "BTC V3 — T3 Breakout Short [Frozen]", "1.0",
                   StrategyStatus.FROZEN, "trend_breakout",
                   "Validated short-only T3 breakout component.", "btc_v3_t3_breakout_short.py"),
    factory=BtcV3T3BreakoutShortFrozen,
    parameters=(
        _frozen("trend_min_h1_separation_atr", ParameterType.ATR_MULTIPLE, 1.00),
        _frozen("trend_minimum_body_percent", ParameterType.PERCENTAGE, 0.70),
        _frozen("trend_maximum_range_atr", ParameterType.ATR_MULTIPLE, 2.00),
        _frozen("trend_maximum_extension_atr", ParameterType.ATR_MULTIPLE, 2.50),
        _frozen("reward_multiple", ParameterType.FLOAT, 3.0),
    ),
    required_indicators=("H1 EMA50", "H1 EMA200", "H1 ATR14", "M15 EMA20", "M15 EMA50", "ADX14", "RSI14", "ATR14"),
    required_timeframes=("15m", "1h"), warmup_resolver=_t3_warmup,
    execution_profile="EXNESS_SYNTHETIC_BID_ASK",
))

register_strategy(StrategyDescriptor(
    metadata=_meta("BTC_V3_CORE_V1_FROZEN", "BTC V3 Core v1 [Frozen]", "1.0",
                   StrategyStatus.FROZEN, "multi_component",
                   "Frozen composition of A4 Pullback Long + T3 Breakout Short.", "btc_v3_core_v1.py"),
    factory=BtcV3CoreV1Frozen,
    parameters=(_frozen("reward_multiple", ParameterType.FLOAT, 3.0),),
    required_indicators=("A4 requirements", "T3 requirements"),
    required_timeframes=("15m", "1h"), warmup_resolver=_core_warmup,
    execution_profile="EXNESS_SYNTHETIC_BID_ASK",
))


def _parameterized(cls, params_cls):
    def build(overrides):
        params = params_cls()
        return cls(replace(params, **dict(overrides)))
    return build


def _pb1_warmup(start):
    params = PB1Parameters()
    h1_bars = params.h1_slow_ema + params.h1_slope_lookback
    m15_bars = max(params.m15_ema_slow, params.m15_atr_length,
                   params.impulse_window_bars + params.pullback_maximum_bars + 1)
    first_full_hour = start.ceil("h")
    h1_ready = first_full_hour + pd.Timedelta(hours=h1_bars)
    m15_ready = start + pd.Timedelta(minutes=15 * (m15_bars - 1))
    return max(h1_ready, m15_ready)


register_strategy(StrategyDescriptor(
    metadata=_meta("BTC_PB1_SHALLOW_PULLBACK_V1", "BTC PB1 — Shallow Trend Pullback Continuation [Rejected]", "1.0",
                   StrategyStatus.REJECTED, "trend_continuation",
                   "Impulse -> shallow controlled retracement -> continuation trigger. "
                   "REJECTED — DEVELOPMENT cross-regime robustness failure: the hypothesis showed "
                   "localized signal but no configuration was robust across 2021/2022/2023. "
                   "Parameters, defaults and source are preserved unchanged so every historical "
                   "PB1 result stays reproducible. See reports/pb1/RESEARCH_SUMMARY.md.",
                   "btc_pb1_shallow_pullback.py"),
    factory=BtcPB1ShallowPullback,
    parameters=(
        _mutable("impulse_window_bars", ParameterType.INTEGER, 3, 2, 5, 1,
                 "M15 candles spanning the measured impulse leg."),
        _mutable("impulse_minimum_range_atr", ParameterType.ATR_MULTIPLE, 1.5, 1.0, 3.0, 0.1,
                 "Minimum impulse range (high-low across the window) in ATR."),
        _mutable("pullback_maximum_bars", ParameterType.INTEGER, 3, 1, 5, 1,
                 "Maximum M15 candles allowed for the pullback before timeout."),
        _mutable("pullback_minimum_retracement_percent", ParameterType.PERCENTAGE, 0.20, 0.05, 0.40, 0.05,
                 "Minimum retracement of the impulse range."),
        _mutable("pullback_maximum_retracement_percent", ParameterType.PERCENTAGE, 0.45, 0.30, 0.70, 0.05,
                 "Maximum retracement of the impulse range before invalidation."),
        _mutable("confirmation_close_location_percent", ParameterType.PERCENTAGE, 0.35, 0.10, 0.49, 0.05,
                 "Confirmation candle must close within this fraction of its extreme."),
        _mutable("confirmation_minimum_body_percent", ParameterType.PERCENTAGE, 0.50, 0.30, 0.90, 0.05,
                 "Minimum confirmation candle body as a percent of its range."),
        _mutable("confirmation_maximum_range_atr", ParameterType.ATR_MULTIPLE, 2.0, 1.0, 4.0, 0.25,
                 "Maximum confirmation candle range in ATR."),
        _mutable("entry_buffer_atr", ParameterType.ATR_MULTIPLE, 0.10, 0.0, 0.50, 0.05,
                 "Entry trigger buffer beyond the confirmation candle extreme, in ATR."),
        _mutable("stop_buffer_atr", ParameterType.ATR_MULTIPLE, 0.20, 0.0, 0.50, 0.05,
                 "Structural stop buffer beyond the deepest pullback price, in ATR."),
        _mutable("minimum_stop_atr", ParameterType.ATR_MULTIPLE, 0.50, 0.25, 1.00, 0.05,
                 "Minimum accepted stop distance, in ATR."),
        _mutable("maximum_stop_atr", ParameterType.ATR_MULTIPLE, 2.50, 1.50, 4.00, 0.25,
                 "Maximum accepted stop distance, in ATR."),
        _frozen("reward_multiple", ParameterType.FLOAT, 3.0,
                "Fixed R-multiple target applied by the audited engine."),
    ),
    required_indicators=("H1 EMA50", "H1 EMA200", "H1 ATR14", "M15 EMA20", "M15 EMA50", "M15 ATR14"),
    required_timeframes=("15m", "1h"), warmup_resolver=_pb1_warmup,
    parameterized_factory=_parameterized(BtcPB1ShallowPullback, PB1Parameters),
    execution_profile="EXNESS_SYNTHETIC_BID_ASK",
))


def _pb2_warmup(start):
    params = PB2Parameters()
    h1_bars = params.h1_slow_ema + params.h1_slope_lookback
    m15_bars = max(params.m15_ema50_length, params.m15_atr_length,
                   params.structure_lookback + params.retest_maximum_bars + 2)
    h1_ready = start.ceil("h") + pd.Timedelta(hours=h1_bars)
    m15_ready = start + pd.Timedelta(minutes=15 * (m15_bars - 1))
    return max(h1_ready, m15_ready)


def _pb2_parameters() -> tuple[StrategyParameter, ...]:
    """One schema, registered independently on both PB2 components."""
    return (
        _mutable("structure_lookback", ParameterType.INTEGER, 12, 6, 24, 1,
                 "Completed M15 bars preceding the displacement that define the structure level."),
        _mutable("displacement_minimum_range_atr", ParameterType.ATR_MULTIPLE, 1.30, 0.80, 2.50, 0.10,
                 "Minimum displacement candle range in ATR."),
        _mutable("displacement_minimum_body_percent", ParameterType.PERCENTAGE, 0.70, 0.40, 0.90, 0.05,
                 "Minimum displacement body as a share of its range."),
        _mutable("displacement_close_location_percent", ParameterType.PERCENTAGE, 0.20, 0.05, 0.45, 0.05,
                 "Displacement must close within this fraction of its extreme."),
        _mutable("retest_tolerance_atr", ParameterType.ATR_MULTIPLE, 0.10, 0.0, 0.50, 0.05,
                 "How far short of the structure level still counts as a retest, in ATR."),
        _mutable("retest_maximum_bars", ParameterType.INTEGER, 5, 2, 12, 1,
                 "Completed M15 bars allowed for retest and reclaim before the structure expires."),
        _mutable("reclaim_minimum_body_percent", ParameterType.PERCENTAGE, 0.50, 0.30, 0.90, 0.05,
                 "Minimum reclaim candle body as a share of its range."),
        _mutable("reclaim_close_location_percent", ParameterType.PERCENTAGE, 0.35, 0.10, 0.49, 0.05,
                 "Reclaim must close within this fraction of its extreme."),
        _mutable("reclaim_maximum_range_atr", ParameterType.ATR_MULTIPLE, 2.00, 1.00, 4.00, 0.25,
                 "Maximum reclaim candle range in ATR."),
        _mutable("entry_buffer_atr", ParameterType.ATR_MULTIPLE, 0.05, 0.0, 0.50, 0.05,
                 "Stop-entry trigger beyond the acceptance candle extreme, in ATR."),
        _mutable("stop_buffer_atr", ParameterType.ATR_MULTIPLE, 0.20, 0.0, 0.50, 0.05,
                 "Structural stop buffer beyond the retest/reclaim/acceptance extreme, in ATR."),
        _mutable("minimum_stop_atr", ParameterType.ATR_MULTIPLE, 0.50, 0.25, 1.00, 0.05,
                 "Minimum accepted stop distance, in ATR."),
        _mutable("maximum_stop_atr", ParameterType.ATR_MULTIPLE, 2.50, 1.50, 4.00, 0.25,
                 "Maximum accepted stop distance, in ATR."),
        _frozen("reward_multiple", ParameterType.FLOAT, 3.0,
                "Fixed R-multiple target applied by the audited engine."),
        # Architecture mode, not a search dimension: overridable so a predeclared
        # ablation can run, but never optimizable. STRICT is the Phase A baseline.
        StrategyParameter(
            "acceptance_mode", ParameterType.ENUM, ACCEPTANCE_STRICT,
            choices=ACCEPTANCE_MODES, optimization_allowed=False, frozen=False,
            description="Acceptance architecture: STRICT (baseline), LEVEL_HOLD, RECLAIM_ONLY.",
        ),
    )


_PB2_INDICATORS =("H1 EMA50", "H1 EMA200", "H1 ATR14", "M15 EMA20", "M15 EMA50", "M15 ATR14")
_PB2_CORE_FILE = "btc_pb2_reclaim_acceptance.py"

register_strategy(StrategyDescriptor(
    metadata=_meta("BTC_PB2_RECLAIM_LONG_V1", "BTC PB2 — Reclaim & Acceptance Long [Rejected]", "1.0",
                   StrategyStatus.REJECTED, "trend_continuation",
                   "Displacement through a prior M15 structure high -> retest -> reclaim -> one "
                   "acceptance bar above the level -> stop entry. "
                   "REJECTED — DEVELOPMENT sample insufficiency and unresolved cross-regime "
                   "robustness. Strict reclaim acceptance showed localized positive selectivity, "
                   "but the architecture generated only 29 closed LONG trades across 2021-2023 "
                   "and remained negative in 2022. The sample is insufficient for responsible "
                   "parameter optimization or robustness claims. Parameters, defaults, "
                   "architecture modes and source behavior are preserved unchanged for "
                   "historical reproduction. See reports/pb2/RESEARCH_SUMMARY.md.",
                   "btc_pb2_reclaim_long.py", _PB2_CORE_FILE),
    factory=BtcPB2ReclaimLong,
    parameters=_pb2_parameters(),
    required_indicators=_PB2_INDICATORS,
    required_timeframes=("15m", "1h"), warmup_resolver=_pb2_warmup,
    parameterized_factory=_parameterized(BtcPB2ReclaimLong, PB2Parameters),
    execution_profile="EXNESS_SYNTHETIC_BID_ASK",
))

register_strategy(StrategyDescriptor(
    metadata=_meta("BTC_PB2_RECLAIM_SHORT_V1", "BTC PB2 — Reclaim & Acceptance Short [Rejected]", "1.0",
                   StrategyStatus.REJECTED, "trend_continuation",
                   "Displacement through a prior M15 structure low -> retest -> reclaim -> one "
                   "acceptance bar below the level -> stop entry. "
                   "REJECTED — DEVELOPMENT sample insufficiency and no stable positive "
                   "expectancy. The SHORT architecture produced only 14 baseline trades; "
                   "acceptance ablations increased frequency only modestly and did not establish "
                   "coherent cross-year positive expectancy. Parameters, defaults, architecture "
                   "modes and source behavior are preserved unchanged for historical "
                   "reproduction. See reports/pb2/RESEARCH_SUMMARY.md.",
                   "btc_pb2_reclaim_short.py", _PB2_CORE_FILE),
    factory=BtcPB2ReclaimShort,
    parameters=_pb2_parameters(),
    required_indicators=_PB2_INDICATORS,
    required_timeframes=("15m", "1h"), warmup_resolver=_pb2_warmup,
    parameterized_factory=_parameterized(BtcPB2ReclaimShort, PB2Parameters),
    execution_profile="EXNESS_SYNTHETIC_BID_ASK",
))


for descriptor in (
    StrategyDescriptor(
        metadata=_meta("BTC_V3_R2_RANGE_LIQUIDITY_SWEEP", "BTC V3-R2 — Range Liquidity Sweep Reversal [Rejected]", "1.0",
                       StrategyStatus.REJECTED, "range_reversal", "Historical rejected R2 research branch.", "btc_v3_r2_range_liquidity_sweep.py"),
        factory=BtcV3R2RangeLiquiditySweepReversal,
        parameters=(), required_timeframes=("15m", "1h"),
        warmup_resolver=lambda start: r2_warmup(V3R2Parameters(), start).first_search_time,
        parameterized_factory=_parameterized(BtcV3R2RangeLiquiditySweepReversal, V3R2Parameters),
        execution_profile="EXNESS_SYNTHETIC_BID_ASK",
    ),
    StrategyDescriptor(
        metadata=_meta("BTC_V3_M1_MOMENTUM_EXPANSION", "BTC V3-M1 — Momentum Expansion Continuation [Rejected]", "1.0",
                       StrategyStatus.REJECTED, "momentum_expansion", "Historical rejected M1 research branch.", "btc_v3_m1_momentum_expansion_continuation.py"),
        factory=BtcV3M1MomentumExpansionContinuation,
        parameters=(), required_timeframes=("15m",),
        warmup_resolver=lambda start: m1_warmup(V3M1Parameters(), start).first_search_time,
        parameterized_factory=_parameterized(BtcV3M1MomentumExpansionContinuation, V3M1Parameters),
        execution_profile="EXNESS_SYNTHETIC_BID_ASK",
    ),
    StrategyDescriptor(
        metadata=_meta("BTC_V3_MR1_INTRADAY_OVERSHOOT", "BTC V3-MR1 — Intraday Overshoot Mean Reversion [Rejected]", "1.0",
                       StrategyStatus.REJECTED, "mean_reversion", "Historical rejected MR1 research branch.", "btc_v3_mr1_intraday_overshoot_mean_reversion.py"),
        factory=BtcV3MR1IntradayOvershootMeanReversion,
        parameters=(), required_timeframes=("15m",),
        warmup_resolver=lambda start: mr1_warmup(V3MR1Parameters(), start).first_search_time,
        parameterized_factory=_parameterized(BtcV3MR1IntradayOvershootMeanReversion, V3MR1Parameters),
        execution_profile="EXNESS_SYNTHETIC_BID_ASK",
    ),
):
    register_strategy(descriptor)
