"""Phase 3E execution replay & forensics framework.

Post-backtest, optional layer that re-examines already-audited trades using finer-grained
data (true ticks, then lower-timeframe OHLC, then falling back to the existing conservative
SL_FIRST baseline policy) to resolve same-candle SL/TP and pending-entry ambiguities that the
audited candle engine (engine/execution.py::exit_decision, engine/diagnostics.py) cannot
disambiguate from OHLC alone.

This module never re-runs strategy signal logic, never mutates a baseline BacktestResult /
Experiment / Trade, and never feeds into the Phase 3B optimizer or Phase 3C walk-forward
selection. It produces a separate, clearly labeled derived view only.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import asdict, dataclass, field, replace as dataclass_replace
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
import sqlite3
from statistics import median
from typing import Any, Mapping, Sequence
import uuid

from core.fingerprints import sha256_file, stable_fingerprint
from engine.diagnostics import ExecutionAmbiguity, compare_trades
from engine.models import Direction, OrderEvent, Trade

TRUE_QUOTE = "TRUE_QUOTE"
SYNTHETIC_BID_ASK = "SYNTHETIC_BID_ASK"
REPLAY_ADJUSTED_SCENARIO = "REPLAY_ADJUSTED_SCENARIO"
RESERVED_DATASET_ROLES = ("FORWARD_VALIDATION", "HOLDOUT")


class ExecutionReplayBlocked(ValueError):
    """Raised whenever a replay safety invariant is violated. Never caught silently."""


class ReplayResolution(str, Enum):
    BASE_BAR = "BASE_BAR"
    LOWER_TIMEFRAME = "LOWER_TIMEFRAME"
    TICK = "TICK"


class ResolutionStatus(str, Enum):
    EXACT_TICK_RESOLUTION = "EXACT_TICK_RESOLUTION"
    LOWER_TF_RESOLUTION = "LOWER_TF_RESOLUTION"
    STILL_AMBIGUOUS = "STILL_AMBIGUOUS"
    REPLAY_DATA_MISSING = "REPLAY_DATA_MISSING"
    REPLAY_DATA_INCOMPLETE = "REPLAY_DATA_INCOMPLETE"
    FALLBACK_BASELINE_POLICY = "FALLBACK_BASELINE_POLICY"
    NOT_AMBIGUOUS = "NOT_AMBIGUOUS"


class ReplayMode(str, Enum):
    AMBIGUITIES_ONLY = "AMBIGUITIES_ONLY"
    SELECTED_TRADES = "SELECTED_TRADES"
    ALL_TRADES = "ALL_TRADES"


class GapType(str, Enum):
    MARKET_GAP = "MARKET_GAP"
    SESSION_GAP = "SESSION_GAP"
    REPLAY_DATA_GAP = "REPLAY_DATA_GAP"
    MISSING_DATA_GAP = "MISSING_DATA_GAP"


def reserved_data_warning(dataset_role: str) -> str | None:
    if dataset_role in RESERVED_DATASET_ROLES:
        return "RESERVED DATA EXECUTION REPLAY — DO NOT RETUNE FROM THESE RESULTS"
    return None


# ---------------------------------------------------------------------------
# Section 3: Normalized replay events / dataset
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayEvent:
    timestamp: datetime
    bid: float
    ask: float
    last: float | None
    source: str  # TRUE_QUOTE | SYNTHETIC_BID_ASK
    resolution: str  # ReplayResolution value
    parent_bar_timestamp: datetime | None
    sequence_number: int


@dataclass(frozen=True)
class ReplayDataset:
    fingerprint: str
    instrument: str
    broker: str
    timezone: str
    precision: str
    spread_provenance: str
    resolution: str  # ReplayResolution value
    coverage_start: datetime
    coverage_end: datetime
    events: tuple[ReplayEvent, ...]
    source_path: str | None = None


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def build_tick_dataset(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    broker: str,
    timezone_label: str = "UTC",
    precision: str = "millisecond",
    source_path: str | Path | None = None,
) -> ReplayDataset:
    """Builds a TICK-resolution ReplayDataset from true observed Bid/Ask rows.
    Never infers/interpolates a missing bid or ask; malformed rows block the whole dataset."""
    events: list[ReplayEvent] = []
    for index, row in enumerate(rows):
        if row.get("bid") is None or row.get("ask") is None or row.get("timestamp") is None:
            raise ExecutionReplayBlocked(f"REPLAY BLOCKED: malformed tick row at index {index}; missing bid/ask/timestamp.")
        events.append(ReplayEvent(
            timestamp=_parse_ts(row["timestamp"]), bid=float(row["bid"]), ask=float(row["ask"]),
            last=float(row["last"]) if row.get("last") not in (None, "") else None,
            source=TRUE_QUOTE, resolution=ReplayResolution.TICK.value,
            parent_bar_timestamp=None, sequence_number=index,
        ))
    for earlier, later in zip(events, events[1:]):
        if later.timestamp < earlier.timestamp:
            raise ExecutionReplayBlocked(
                "REPLAY BLOCKED: tick source is not in chronological order; malformed ordering blocks exact replay."
            )
    if not events:
        raise ExecutionReplayBlocked("REPLAY BLOCKED: no tick rows supplied.")
    if source_path is not None:
        fingerprint = sha256_file(source_path)
    else:
        fingerprint = stable_fingerprint([asdict(e) for e in events])
    return ReplayDataset(
        fingerprint=fingerprint, instrument=instrument, broker=broker, timezone=timezone_label,
        precision=precision, spread_provenance=TRUE_QUOTE, resolution=ReplayResolution.TICK.value,
        coverage_start=events[0].timestamp, coverage_end=events[-1].timestamp,
        events=tuple(events), source_path=str(source_path) if source_path else None,
    )


def build_lower_timeframe_dataset(
    bars: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    broker: str,
    spread: float,
    timezone_label: str = "UTC",
    precision: str = "bar",
) -> ReplayDataset:
    """Builds a LOWER_TIMEFRAME ReplayDataset from finer OHLC bars. Lower-TF OHLC is never
    tick-exact: each bar contributes two same-timestamp probe events (its low and its high),
    so the resolver can never infer which extreme was touched first within one finer bar."""
    events: list[ReplayEvent] = []
    seq = 0
    for row in bars:
        timestamp = _parse_ts(row["timestamp"])
        low, high = float(row["low"]), float(row["high"])
        for extreme in (low, high):
            events.append(ReplayEvent(
                timestamp=timestamp, bid=extreme, ask=extreme + spread, last=None,
                source=SYNTHETIC_BID_ASK, resolution=ReplayResolution.LOWER_TIMEFRAME.value,
                parent_bar_timestamp=None, sequence_number=seq,
            ))
            seq += 1
    if not events:
        raise ExecutionReplayBlocked("REPLAY BLOCKED: no lower-timeframe bars supplied.")
    fingerprint = stable_fingerprint([asdict(e) for e in events])
    return ReplayDataset(
        fingerprint=fingerprint, instrument=instrument, broker=broker, timezone=timezone_label,
        precision=precision, spread_provenance=SYNTHETIC_BID_ASK, resolution=ReplayResolution.LOWER_TIMEFRAME.value,
        coverage_start=events[0].timestamp, coverage_end=events[-1].timestamp, events=tuple(events),
    )


# ---------------------------------------------------------------------------
# Section 5: Parent-bar mapping
# ---------------------------------------------------------------------------


def map_to_parent_bar(timestamp: datetime, bar_timestamps: Sequence[datetime], interval_seconds: float) -> datetime | None:
    """Maps a replay event to the base strategy bar it belongs to: the latest bar_timestamp
    at-or-before the event, provided the event falls within one bar-width of it. Returns None
    for events before the first bar or inside a missing-bar gap wider than one interval."""
    if not bar_timestamps:
        return None
    idx = bisect_right(bar_timestamps, timestamp) - 1
    if idx < 0:
        return None
    candidate = bar_timestamps[idx]
    if (timestamp - candidate).total_seconds() >= interval_seconds:
        return None
    return candidate


def assign_parent_bars(events: Sequence[ReplayEvent], bar_timestamps: Sequence[datetime], interval_seconds: float) -> tuple[ReplayEvent, ...]:
    sorted_bars = sorted(bar_timestamps)
    return tuple(
        dataclass_replace(event, parent_bar_timestamp=map_to_parent_bar(event.timestamp, sorted_bars, interval_seconds))
        for event in events
    )


def events_for_parent_bar(dataset: ReplayDataset, parent_bar_timestamp: datetime) -> list[ReplayEvent]:
    return [event for event in dataset.events if event.parent_bar_timestamp == parent_bar_timestamp]


def with_parent_bars(dataset: ReplayDataset, bar_timestamps: Sequence[datetime], interval_seconds: float) -> ReplayDataset:
    return dataclass_replace(dataset, events=assign_parent_bars(dataset.events, bar_timestamps, interval_seconds))


# ---------------------------------------------------------------------------
# Section 4/6/7/8: Bid/Ask semantics + ambiguity resolution
# ---------------------------------------------------------------------------


def _level_touched(level_name: str, bid: float, ask: float, level_value: float, direction: Direction) -> bool:
    long = direction is Direction.LONG
    if level_name == "trigger":
        return ask >= level_value if long else bid <= level_value
    if level_name == "stop":
        return bid <= level_value if long else ask >= level_value
    if level_name == "target":
        return bid >= level_value if long else ask <= level_value
    raise ValueError(f"Unknown level name: {level_name}")


def _quote_side_for(level_name: str) -> str:
    return "ask" if level_name == "trigger" else "bid"


def _first_touch(
    levels: Mapping[str, float], direction: Direction, events: Sequence[ReplayEvent], resolution: ReplayResolution,
) -> tuple[str | None, ReplayEvent | None, tuple[str, ...]]:
    """Walks events chronologically; for TICK resolution, identical timestamps are ordered by
    the stable source sequence_number (section 8). For LOWER_TIMEFRAME, identical timestamps
    (the two probe events of one finer bar) are treated as simultaneous/unordered (section 7) —
    if two distinct levels are both first touched within the same timestamp batch, that batch is
    reported as ambiguous rather than guessing an order."""
    if resolution is ReplayResolution.TICK:
        # True ticks: identical timestamps are still strictly ordered via stable sequence_number,
        # never treated as simultaneous. Each tick is evaluated on its own.
        ordered = sorted(events, key=lambda e: (e.timestamp, e.sequence_number))
        for event in ordered:
            touched_now = [name for name, value in levels.items() if _level_touched(name, event.bid, event.ask, value, direction)]
            if len(touched_now) >= 2:
                return None, None, tuple(sorted(touched_now))
            if len(touched_now) == 1:
                return touched_now[0], event, ()
        return None, None, ()

    # LOWER_TIMEFRAME: identical timestamps are the two probe events of one finer bar and are
    # genuinely simultaneous/unordered — if two distinct levels are both first touched within the
    # same timestamp batch, that batch is reported as ambiguous rather than guessing an order.
    ordered = sorted(events, key=lambda e: (e.timestamp, 0))
    index, total = 0, len(ordered)
    while index < total:
        batch_ts = ordered[index].timestamp
        batch = []
        while index < total and ordered[index].timestamp == batch_ts:
            batch.append(ordered[index])
            index += 1
        touched: dict[str, ReplayEvent] = {}
        for event in batch:
            for name, value in levels.items():
                if name in touched:
                    continue
                if _level_touched(name, event.bid, event.ask, value, direction):
                    touched[name] = event
        if len(touched) >= 2:
            return None, None, tuple(sorted(touched))
        if len(touched) == 1:
            name, event = next(iter(touched.items()))
            return name, event, ()
    return None, None, ()


@dataclass(frozen=True)
class AmbiguityResolution:
    ambiguity_type: str
    trade_id: int | None
    order_id: str | None
    parent_bar_timestamp: datetime
    status: str  # ResolutionStatus value
    resolution_source: str  # ReplayResolution value actually used
    touched_level: str | None
    first_relevant_event_timestamp: datetime | None
    quote_side: str | None
    resolved_price: float | None
    resolved_outcome: str | None
    activation_timestamp: datetime | None = None
    activation_quote_side: str | None = None
    secondary_touched_level: str | None = None
    secondary_event_timestamp: datetime | None = None
    warnings: tuple[str, ...] = ()


_OUTCOME_LABEL = {"stop": "stop", "target": "target", "trigger": "trigger"}


def _resolve_competing_levels(ambiguity: ExecutionAmbiguity, direction: Direction, events: Sequence[ReplayEvent], resolution: ReplayResolution) -> AmbiguityResolution:
    name, event, tied = _first_touch(ambiguity.levels, direction, events, resolution)
    source_label = ResolutionStatus.EXACT_TICK_RESOLUTION if resolution is ReplayResolution.TICK else ResolutionStatus.LOWER_TF_RESOLUTION
    if name is not None:
        status = source_label
    elif tied:
        status = ResolutionStatus.STILL_AMBIGUOUS
    else:
        status = ResolutionStatus.REPLAY_DATA_INCOMPLETE
    return AmbiguityResolution(
        ambiguity_type=ambiguity.ambiguity_type, trade_id=ambiguity.trade_id, order_id=ambiguity.order_id,
        parent_bar_timestamp=ambiguity.timestamp, status=status.value, resolution_source=resolution.value,
        touched_level=name, first_relevant_event_timestamp=event.timestamp if event else None,
        quote_side=_quote_side_for(name) if name else None,
        resolved_price=(event.bid if _quote_side_for(name) == "bid" else event.ask) if event else None,
        resolved_outcome=_OUTCOME_LABEL.get(name) if name else None,
        warnings=("STILL_AMBIGUOUS_AT_THIS_RESOLUTION",) if tied else (),
    )


def _resolve_pending_entry(ambiguity: ExecutionAmbiguity, direction: Direction, events: Sequence[ReplayEvent], resolution: ReplayResolution) -> AmbiguityResolution:
    trigger_levels = {"trigger": ambiguity.levels["trigger"]}
    name, trigger_event, tied = _first_touch(trigger_levels, direction, events, resolution)
    source_label = ResolutionStatus.EXACT_TICK_RESOLUTION if resolution is ReplayResolution.TICK else ResolutionStatus.LOWER_TF_RESOLUTION
    if name is None:
        status = ResolutionStatus.REPLAY_DATA_INCOMPLETE
        return AmbiguityResolution(
            ambiguity_type=ambiguity.ambiguity_type, trade_id=ambiguity.trade_id, order_id=ambiguity.order_id,
            parent_bar_timestamp=ambiguity.timestamp, status=status.value, resolution_source=resolution.value,
            touched_level=None, first_relevant_event_timestamp=None, quote_side=None, resolved_price=None,
            resolved_outcome=None,
        )
    secondary_levels = {k: v for k, v in ambiguity.levels.items() if k != "trigger"}
    remaining = [e for e in events if e.timestamp > trigger_event.timestamp or (e.timestamp == trigger_event.timestamp and e.sequence_number > trigger_event.sequence_number and resolution is ReplayResolution.TICK)]
    secondary_name, secondary_event, secondary_tied = _first_touch(secondary_levels, direction, remaining, resolution)
    if secondary_name is not None:
        status = source_label
        resolved_outcome = "activated_then_" + _OUTCOME_LABEL.get(secondary_name, secondary_name)
    elif secondary_tied:
        status = ResolutionStatus.STILL_AMBIGUOUS
        resolved_outcome = "activated_then_ambiguous"
    else:
        status = source_label
        resolved_outcome = "activated_only"
    return AmbiguityResolution(
        ambiguity_type=ambiguity.ambiguity_type, trade_id=ambiguity.trade_id, order_id=ambiguity.order_id,
        parent_bar_timestamp=ambiguity.timestamp, status=status.value, resolution_source=resolution.value,
        touched_level="trigger", first_relevant_event_timestamp=trigger_event.timestamp,
        quote_side=_quote_side_for("trigger"),
        resolved_price=trigger_event.ask if direction is Direction.LONG else trigger_event.bid,
        resolved_outcome=resolved_outcome,
        activation_timestamp=trigger_event.timestamp, activation_quote_side=_quote_side_for("trigger"),
        secondary_touched_level=secondary_name, secondary_event_timestamp=secondary_event.timestamp if secondary_event else None,
        warnings=("STILL_AMBIGUOUS_AT_THIS_RESOLUTION",) if secondary_tied else (),
    )


def resolve_ambiguity(ambiguity: ExecutionAmbiguity, direction: Direction, events: Sequence[ReplayEvent], resolution: ReplayResolution) -> AmbiguityResolution:
    if ambiguity.ambiguity_type == "PENDING_ENTRY_AND_STOP_SAME_CANDLE":
        return _resolve_pending_entry(ambiguity, direction, events, resolution)
    return _resolve_competing_levels(ambiguity, direction, events, resolution)


def resolve_ambiguity_with_hierarchy(
    ambiguity: ExecutionAmbiguity,
    direction: Direction,
    *,
    tick_dataset_available: bool = False,
    tick_events: Sequence[ReplayEvent] = (),
    lower_tf_dataset_available: bool = False,
    lower_tf_events: Sequence[ReplayEvent] = (),
    baseline_policy: str = "SL_FIRST",
) -> AmbiguityResolution:
    """Applies the resolution hierarchy: true ticks -> lower-timeframe OHLC -> baseline policy.
    Never silently continues past an unresolved level; a status is always recorded.

    REPLAY_DATA_MISSING means no replay dataset was configured for this instrument/period at
    all. FALLBACK_BASELINE_POLICY means at least one dataset existed but did not resolve this
    specific ambiguity (empty/incomplete coverage of this bar, or still ambiguous at every
    available resolution), so the documented conservative baseline rule is applied explicitly."""
    if tick_dataset_available and tick_events:
        result = resolve_ambiguity(ambiguity, direction, tick_events, ReplayResolution.TICK)
        if result.status in (ResolutionStatus.EXACT_TICK_RESOLUTION.value, ResolutionStatus.STILL_AMBIGUOUS.value):
            return result
        # REPLAY_DATA_INCOMPLETE at tick level: fall through to lower-TF / baseline.
    if lower_tf_dataset_available and lower_tf_events:
        result = resolve_ambiguity(ambiguity, direction, lower_tf_events, ReplayResolution.LOWER_TIMEFRAME)
        if result.status in (ResolutionStatus.LOWER_TF_RESOLUTION.value, ResolutionStatus.STILL_AMBIGUOUS.value):
            return result
    if not tick_dataset_available and not lower_tf_dataset_available:
        return AmbiguityResolution(
            ambiguity_type=ambiguity.ambiguity_type, trade_id=ambiguity.trade_id, order_id=ambiguity.order_id,
            parent_bar_timestamp=ambiguity.timestamp, status=ResolutionStatus.REPLAY_DATA_MISSING.value,
            resolution_source=ReplayResolution.BASE_BAR.value, touched_level=None,
            first_relevant_event_timestamp=None, quote_side=None, resolved_price=None, resolved_outcome=None,
        )
    fallback_level = "target" if baseline_policy == "TP_FIRST" else "stop"
    if fallback_level not in ambiguity.levels:
        # e.g. a pending-entry ambiguity where the fallback only concerns "trigger"; nothing to fall back to.
        return AmbiguityResolution(
            ambiguity_type=ambiguity.ambiguity_type, trade_id=ambiguity.trade_id, order_id=ambiguity.order_id,
            parent_bar_timestamp=ambiguity.timestamp, status=ResolutionStatus.REPLAY_DATA_INCOMPLETE.value,
            resolution_source=ReplayResolution.BASE_BAR.value, touched_level=None,
            first_relevant_event_timestamp=None, quote_side=None, resolved_price=None, resolved_outcome=None,
        )
    return AmbiguityResolution(
        ambiguity_type=ambiguity.ambiguity_type, trade_id=ambiguity.trade_id, order_id=ambiguity.order_id,
        parent_bar_timestamp=ambiguity.timestamp, status=ResolutionStatus.FALLBACK_BASELINE_POLICY.value,
        resolution_source=ReplayResolution.BASE_BAR.value, touched_level=fallback_level,
        first_relevant_event_timestamp=None, quote_side=_quote_side_for(fallback_level),
        resolved_price=ambiguity.levels.get(fallback_level), resolved_outcome=_OUTCOME_LABEL.get(fallback_level),
    )


# ---------------------------------------------------------------------------
# Section 10: Gap semantics
# ---------------------------------------------------------------------------


def classify_gap(
    *, previous_bar: datetime | None, next_bar: datetime | None, interval_seconds: float,
    replay_coverage_start: datetime | None, replay_coverage_end: datetime | None, is_session_boundary: bool = False,
) -> str:
    if previous_bar is None or next_bar is None:
        return GapType.MARKET_GAP.value
    gap_seconds = (next_bar - previous_bar).total_seconds()
    if gap_seconds <= interval_seconds:
        return "NOT_A_GAP"
    if is_session_boundary:
        return GapType.SESSION_GAP.value
    if replay_coverage_start is not None and replay_coverage_end is not None:
        if previous_bar >= replay_coverage_start and next_bar <= replay_coverage_end:
            return GapType.REPLAY_DATA_GAP.value
        if previous_bar < replay_coverage_start or next_bar > replay_coverage_end:
            return GapType.MISSING_DATA_GAP.value
    return GapType.MARKET_GAP.value


# ---------------------------------------------------------------------------
# Section 11: Baseline vs replay trade comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TradeComparison:
    trade_id: int
    side: str
    baseline_entry: float
    replay_entry: float
    baseline_exit: float | None
    replay_exit: float | None
    baseline_exit_reason: str | None
    replay_exit_reason: str | None
    baseline_pnl: float | None
    replay_pnl: float | None
    baseline_r: float | None
    replay_r: float | None
    baseline_duration_minutes: float | None
    replay_duration_minutes: float | None
    resolution_source: str
    classification: str


def build_replay_trade(baseline: Trade, resolution: AmbiguityResolution) -> Trade:
    """Builds the derived, replay-resolved Trade. Never mutates the baseline Trade object."""
    if resolution.touched_level not in ("stop", "target") or resolution.resolved_price is None:
        return baseline
    exit_price = resolution.resolved_price
    label = "Stop loss" if resolution.touched_level == "stop" else "Take profit"
    reason = f"{label} ({resolution.resolution_source.lower()} replay)"
    risk = baseline.initial_risk or abs(baseline.entry_price - baseline.stop_loss) or 1.0
    direction_sign = 1 if baseline.direction is Direction.LONG else -1
    pnl = (exit_price - baseline.entry_price) * direction_sign * baseline.quantity - baseline.entry_commission - baseline.exit_commission
    r_multiple = ((exit_price - baseline.entry_price) * direction_sign) / risk if risk else baseline.r_multiple
    exit_time = resolution.first_relevant_event_timestamp or baseline.exit_time
    duration_minutes = (exit_time - baseline.entry_time).total_seconds() / 60 if exit_time else baseline.duration_minutes
    return dataclass_replace(
        baseline, exit_price=exit_price, exit_reason=reason, exit_time=exit_time,
        pnl=pnl, r_multiple=r_multiple, duration_minutes=duration_minutes,
    )


def classify_comparison(baseline: Trade, replay: Trade, resolution: AmbiguityResolution) -> str:
    if resolution.status == ResolutionStatus.STILL_AMBIGUOUS.value:
        return "STILL_AMBIGUOUS"
    if resolution.status in (
        ResolutionStatus.REPLAY_DATA_MISSING.value, ResolutionStatus.REPLAY_DATA_INCOMPLETE.value,
        ResolutionStatus.FALLBACK_BASELINE_POLICY.value,
    ):
        return "STILL_AMBIGUOUS"
    if resolution.status == ResolutionStatus.NOT_AMBIGUOUS.value:
        return "IDENTICAL"
    if baseline.entry_price != replay.entry_price or baseline.entry_time != replay.entry_time:
        return "ENTRY_CHANGED"
    if (baseline.pnl > 0) != (replay.pnl > 0):
        return "OUTCOME_CHANGED"
    baseline_level = "stop" if "Stop loss" in (baseline.exit_reason or "") else ("target" if "Take profit" in (baseline.exit_reason or "") else None)
    if resolution.touched_level is not None and resolution.touched_level == baseline_level:
        # Finer data confirms which level fired first, even if the exact fill price differs
        # slightly from the level itself (realistic slippage) — that's confirmation, not change.
        return "BASELINE_AMBIGUITY_RESOLVED"
    if baseline.exit_price != replay.exit_price or baseline.exit_reason != replay.exit_reason:
        return "EXIT_CHANGED"
    if baseline.exit_time != replay.exit_time:
        return "TIMING_CHANGED"
    if baseline.entry_commission != replay.entry_commission or baseline.exit_commission != replay.exit_commission:
        return "COST_CHANGED"
    return "IDENTICAL"


def compare_baseline_and_replay(baseline: Trade, replay: Trade, resolution: AmbiguityResolution) -> TradeComparison:
    classification = classify_comparison(baseline, replay, resolution)
    return TradeComparison(
        trade_id=baseline.trade_id, side=baseline.direction.value,
        baseline_entry=baseline.entry_price, replay_entry=replay.entry_price,
        baseline_exit=baseline.exit_price, replay_exit=replay.exit_price,
        baseline_exit_reason=baseline.exit_reason, replay_exit_reason=replay.exit_reason,
        baseline_pnl=baseline.pnl, replay_pnl=replay.pnl,
        baseline_r=baseline.r_multiple, replay_r=replay.r_multiple,
        baseline_duration_minutes=baseline.duration_minutes, replay_duration_minutes=replay.duration_minutes,
        resolution_source=resolution.resolution_source, classification=classification,
    )


# ---------------------------------------------------------------------------
# Section 14/15: Replay-adjusted scenario + execution sensitivity
# ---------------------------------------------------------------------------


def _profit_factor(trades: Sequence[Trade]) -> float | None:
    gross_win = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = -sum(t.pnl for t in trades if t.pnl < 0)
    return (gross_win / gross_loss) if gross_loss > 0 else None


def build_replay_adjusted_scenario(baseline_trades: Sequence[Trade], comparisons: Sequence[TradeComparison], replay_trades_by_id: Mapping[int, Trade]) -> dict[str, Any]:
    adjusted = [replay_trades_by_id.get(t.trade_id, t) for t in baseline_trades]
    winners_to_losers = sum(1 for c in comparisons if c.baseline_pnl is not None and c.replay_pnl is not None and c.baseline_pnl > 0 and c.replay_pnl <= 0)
    losers_to_winners = sum(1 for c in comparisons if c.baseline_pnl is not None and c.replay_pnl is not None and c.baseline_pnl <= 0 and c.replay_pnl > 0)
    changed = sum(1 for c in comparisons if c.classification not in ("IDENTICAL", "STILL_AMBIGUOUS"))
    unchanged = len(comparisons) - changed

    baseline_pnl_total = sum(t.pnl for t in baseline_trades)
    adjusted_pnl_total = sum(t.pnl for t in adjusted)
    baseline_r_total = sum(t.r_multiple for t in baseline_trades)
    adjusted_r_total = sum(t.r_multiple for t in adjusted)
    baseline_avg_r = baseline_r_total / len(baseline_trades) if baseline_trades else None
    adjusted_avg_r = adjusted_r_total / len(adjusted) if adjusted else None
    baseline_pf = _profit_factor(baseline_trades)
    adjusted_pf = _profit_factor(adjusted)

    return {
        "label": REPLAY_ADJUSTED_SCENARIO,
        "changed_trades": changed, "unchanged_trades": unchanged,
        "winners_to_losers": winners_to_losers, "losers_to_winners": losers_to_winners,
        "pnl_difference": adjusted_pnl_total - baseline_pnl_total,
        "r_difference": adjusted_r_total - baseline_r_total,
        "pf_difference": (adjusted_pf - baseline_pf) if (adjusted_pf is not None and baseline_pf is not None) else None,
        "avg_r_difference": (adjusted_avg_r - baseline_avg_r) if (adjusted_avg_r is not None and baseline_avg_r is not None) else None,
        "dd_difference": None,  # only mathematically valid with a full equity model; not fabricated here
    }


def execution_sensitivity_summary(ambiguities: Sequence[ExecutionAmbiguity], resolutions: Sequence[AmbiguityResolution], comparisons: Sequence[TradeComparison]) -> dict[str, Any]:
    resolved_statuses = {ResolutionStatus.EXACT_TICK_RESOLUTION.value, ResolutionStatus.LOWER_TF_RESOLUTION.value}
    resolved = sum(1 for r in resolutions if r.status in resolved_statuses)
    still_ambiguous = sum(1 for r in resolutions if r.status != ResolutionStatus.NOT_AMBIGUOUS.value and r.status not in resolved_statuses)
    outcome_changed = sum(1 for c in comparisons if c.classification == "OUTCOME_CHANGED")
    ambiguous_count = len(ambiguities)
    covered = len(resolutions)
    total_r_change = sum((c.replay_r or 0) - (c.baseline_r or 0) for c in comparisons)
    return {
        "ambiguous_trades": ambiguous_count,
        "replay_covered_ambiguities": covered,
        "resolved": resolved,
        "still_ambiguous": still_ambiguous,
        "outcome_changed": outcome_changed,
        "resolved_percent": (resolved / covered * 100) if covered else None,
        "outcome_change_percent": (outcome_changed / covered * 100) if covered else None,
        "total_r_change": total_r_change,
        "note": "Low sensitivity here is not proof of live profitability; it only reflects the trades and periods actually replayed.",
    }


# ---------------------------------------------------------------------------
# Section 16: Coverage
# ---------------------------------------------------------------------------


def coverage_report(
    *, baseline_period: tuple[datetime, datetime], replay_dataset: ReplayDataset | None,
    baseline_trades: Sequence[Trade], ambiguities: Sequence[ExecutionAmbiguity],
) -> dict[str, Any]:
    if replay_dataset is None:
        return {
            "baseline_period": [baseline_period[0].isoformat(), baseline_period[1].isoformat()],
            "replay_data_start": None, "replay_data_end": None,
            "baseline_trades_covered": 0, "baseline_trades_outside_coverage": len(baseline_trades),
            "ambiguities_covered": 0, "ambiguities_outside_coverage": len(ambiguities),
        }
    start, end = replay_dataset.coverage_start, replay_dataset.coverage_end

    def in_range(ts: datetime) -> bool:
        return start <= ts <= end

    trades_covered = sum(1 for t in baseline_trades if in_range(t.exit_time))
    ambiguities_covered = sum(1 for a in ambiguities if in_range(a.timestamp))
    return {
        "baseline_period": [baseline_period[0].isoformat(), baseline_period[1].isoformat()],
        "replay_data_start": start.isoformat(), "replay_data_end": end.isoformat(),
        "baseline_trades_covered": trades_covered,
        "baseline_trades_outside_coverage": len(baseline_trades) - trades_covered,
        "ambiguities_covered": ambiguities_covered,
        "ambiguities_outside_coverage": len(ambiguities) - ambiguities_covered,
    }


# ---------------------------------------------------------------------------
# Section 17: Forensic trace
# ---------------------------------------------------------------------------


def build_forensic_trace(trade: Trade, ambiguity: ExecutionAmbiguity | None, events: Sequence[ReplayEvent], resolution: AmbiguityResolution | None) -> list[dict[str, Any]]:
    trace: list[dict[str, Any]] = [
        {"stage": "strategy_signal", "timestamp": trade.signal_time.isoformat(), "price": None},
        {"stage": "order_creation", "timestamp": trade.entry_time.isoformat(), "price": trade.entry_price},
    ]
    for event in sorted(events, key=lambda e: (e.timestamp, e.sequence_number)):
        trace.append({
            "stage": "replay_event", "timestamp": event.timestamp.isoformat(),
            "bid": event.bid, "ask": event.ask, "source": event.source, "resolution": event.resolution,
        })
    if resolution and resolution.touched_level:
        trace.append({
            "stage": "entry_trigger" if resolution.touched_level == "trigger" else "sl_tp_state",
            "timestamp": resolution.first_relevant_event_timestamp.isoformat() if resolution.first_relevant_event_timestamp else None,
            "level": resolution.touched_level, "price": resolution.resolved_price, "quote_side": resolution.quote_side,
        })
    trace.append({
        "stage": "final_resolution", "timestamp": trade.exit_time.isoformat() if trade.exit_time else None,
        "exit_reason": trade.exit_reason, "exit_price": trade.exit_price,
        "status": resolution.status if resolution else ResolutionStatus.NOT_AMBIGUOUS.value,
    })
    return trace


# ---------------------------------------------------------------------------
# Section 12/2/13/18/19: Config, run, persistence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayConfig:
    mode: ReplayMode = ReplayMode.AMBIGUITIES_ONLY
    selected_trade_ids: tuple[int, ...] = ()
    baseline_policy: str = "SL_FIRST"

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["mode"] = self.mode.value
        payload["selected_trade_ids"] = list(self.selected_trade_ids)
        return payload


@dataclass(frozen=True)
class ReplayRun:
    replay_id: str
    created_at: str
    baseline_experiment_id: str
    baseline_fingerprint: str
    replay_dataset_fingerprint: str
    resolution: str
    mode: str
    config: dict[str, Any]
    engine_version: str
    dataset_role: str
    status: str


def guard_dataset_role(dataset_role: str) -> None:
    if dataset_role in RESERVED_DATASET_ROLES:
        # Replay of reserved data is explicitly allowed for post-hoc forensics (section 15);
        # this guard exists only to make the caller acknowledge the reserved status.
        return


def _order_for_ambiguity(ambiguity: ExecutionAmbiguity, orders: Sequence[OrderEvent]) -> OrderEvent | None:
    for order in orders:
        candidate_id = f"{order.signal_time.isoformat()}-{order.direction.value}"
        if candidate_id == ambiguity.order_id:
            return order
    return None


def _trade_id_for_order(order: OrderEvent | None, trades: Sequence[Trade]) -> int | None:
    if order is None or order.fill_time is None:
        return None
    for trade in trades:
        if trade.entry_time == order.fill_time:
            return trade.trade_id
    return None


def run_execution_replay(
    *,
    baseline_experiment_id: str,
    baseline_fingerprint: str,
    baseline_trades: Sequence[Trade],
    baseline_orders: Sequence[OrderEvent],
    ambiguities: Sequence[ExecutionAmbiguity],
    dataset_role: str,
    replay_dataset: ReplayDataset | None,
    lower_tf_dataset: ReplayDataset | None,
    config: ReplayConfig,
    engine_version: str,
) -> tuple[ReplayRun, list[AmbiguityResolution], list[TradeComparison], dict[str, Any]]:
    direction_by_trade = {t.trade_id: t.direction for t in baseline_trades}

    def resolve_trade_id(ambiguity: ExecutionAmbiguity) -> int | None:
        if ambiguity.trade_id is not None:
            return ambiguity.trade_id
        return _trade_id_for_order(_order_for_ambiguity(ambiguity, baseline_orders), baseline_trades)

    eligible = list(ambiguities)
    if config.mode is ReplayMode.SELECTED_TRADES:
        selected = set(config.selected_trade_ids)
        eligible = [a for a in eligible if resolve_trade_id(a) in selected]

    resolutions: list[AmbiguityResolution] = []
    comparisons: list[TradeComparison] = []
    replay_trades_by_id: dict[int, Trade] = {}

    for ambiguity in eligible:
        order = _order_for_ambiguity(ambiguity, baseline_orders) if ambiguity.trade_id is None else None
        direction = direction_by_trade.get(ambiguity.trade_id) if ambiguity.trade_id is not None else (order.direction if order else None)
        if direction is None:
            continue
        tick_available = replay_dataset is not None and replay_dataset.resolution == ReplayResolution.TICK.value
        lower_available = lower_tf_dataset is not None and lower_tf_dataset.resolution == ReplayResolution.LOWER_TIMEFRAME.value
        tick_events = events_for_parent_bar(replay_dataset, ambiguity.timestamp) if tick_available else []
        lower_events = events_for_parent_bar(lower_tf_dataset, ambiguity.timestamp) if lower_available else []
        resolution = resolve_ambiguity_with_hierarchy(
            ambiguity, direction, tick_dataset_available=tick_available, tick_events=tick_events,
            lower_tf_dataset_available=lower_available, lower_tf_events=lower_events, baseline_policy=config.baseline_policy,
        )
        resolutions.append(resolution)

        trade_id = resolve_trade_id(ambiguity)
        if trade_id is None:
            continue
        baseline_trade = next((t for t in baseline_trades if t.trade_id == trade_id), None)
        if baseline_trade is None:
            continue
        replay_trade = build_replay_trade(baseline_trade, resolution)
        replay_trades_by_id[trade_id] = replay_trade
        comparisons.append(compare_baseline_and_replay(baseline_trade, replay_trade, resolution))

    dataset_fingerprint = replay_dataset.fingerprint if replay_dataset else (lower_tf_dataset.fingerprint if lower_tf_dataset else "NONE")
    achieved_resolution = replay_dataset.resolution if replay_dataset else (lower_tf_dataset.resolution if lower_tf_dataset else ReplayResolution.BASE_BAR.value)

    run = ReplayRun(
        replay_id="RX-" + uuid.uuid4().hex[:10].upper(), created_at=datetime.now(timezone.utc).isoformat(),
        baseline_experiment_id=baseline_experiment_id, baseline_fingerprint=baseline_fingerprint,
        replay_dataset_fingerprint=dataset_fingerprint, resolution=achieved_resolution, mode=config.mode.value,
        config=config.as_dict(), engine_version=engine_version, dataset_role=dataset_role, status="COMPLETED",
    )

    period = (min((t.entry_time for t in baseline_trades), default=datetime.now(timezone.utc)),
              max((t.exit_time for t in baseline_trades), default=datetime.now(timezone.utc)))
    coverage = coverage_report(baseline_period=period, replay_dataset=replay_dataset or lower_tf_dataset,
                               baseline_trades=baseline_trades, ambiguities=ambiguities)
    scenario = build_replay_adjusted_scenario(baseline_trades, comparisons, replay_trades_by_id)
    sensitivity = execution_sensitivity_summary(ambiguities, resolutions, comparisons)
    warning = reserved_data_warning(dataset_role)

    summary = {
        "coverage": coverage, "replay_adjusted_scenario": scenario, "execution_sensitivity": sensitivity,
        "reserved_data_warning": warning,
    }
    return run, resolutions, comparisons, summary


# ---------------------------------------------------------------------------
# Section 18: Fingerprinting
# ---------------------------------------------------------------------------


def replay_fingerprint(*, baseline_fingerprint: str, replay_dataset_fingerprint: str, resolution: str, quote_model: str, config: Mapping[str, Any], engine_version: str) -> str:
    return stable_fingerprint({
        "baseline_fingerprint": baseline_fingerprint, "replay_dataset_fingerprint": replay_dataset_fingerprint,
        "resolution": resolution, "quote_model": quote_model, "config": dict(config), "engine_version": engine_version,
    })


# ---------------------------------------------------------------------------
# Section 19: Persistence / resume
# ---------------------------------------------------------------------------


def validate_replay_resume(run: ReplayRun, *, baseline_fingerprint: str, replay_dataset_fingerprint: str, config: dict[str, Any]) -> ReplayRun:
    mismatches = []
    if run.baseline_fingerprint != baseline_fingerprint:
        mismatches.append(f"baseline_fingerprint changed ({run.baseline_fingerprint} -> {baseline_fingerprint})")
    if run.replay_dataset_fingerprint != replay_dataset_fingerprint:
        mismatches.append(f"replay_dataset_fingerprint changed ({run.replay_dataset_fingerprint} -> {replay_dataset_fingerprint})")
    if run.config != config:
        mismatches.append("config changed")
    if mismatches:
        raise ExecutionReplayBlocked("RESUME BLOCKED: " + "; ".join(mismatches))
    return run


class ExecutionReplayStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS replay_runs (
                    replay_id TEXT PRIMARY KEY, metadata_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS replay_results (
                    replay_id TEXT PRIMARY KEY, result_json TEXT NOT NULL
                );
                """
            )

    def save_run(self, run: ReplayRun) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO replay_runs VALUES (?,?)",
                (run.replay_id, json.dumps(asdict(run), sort_keys=True, default=str)),
            )

    def save_result(self, replay_id: str, result: dict[str, Any]) -> None:
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO replay_results VALUES (?,?)",
                (replay_id, json.dumps(result, sort_keys=True, default=str)),
            )

    def load_run(self, replay_id: str) -> ReplayRun | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT metadata_json FROM replay_runs WHERE replay_id=?", (replay_id,)).fetchone()
        return ReplayRun(**json.loads(row[0])) if row else None

    def load_result(self, replay_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.path) as connection:
            row = connection.execute("SELECT result_json FROM replay_results WHERE replay_id=?", (replay_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_runs(self) -> list[ReplayRun]:
        with sqlite3.connect(self.path) as connection:
            rows = connection.execute("SELECT metadata_json FROM replay_runs ORDER BY replay_id DESC").fetchall()
        return [ReplayRun(**json.loads(row[0])) for row in rows]


# ---------------------------------------------------------------------------
# Section 23: Real-data loader (Exness BTC tick samples)
# ---------------------------------------------------------------------------


def load_exness_btc_tick_sample(path: str | Path, *, broker: str = "EXNESS_STANDARD") -> ReplayDataset:
    """Loads one real MT5-exported Exness BTCUSDm tick sample (processed CSV with
    timestamp_server/bid/ask columns). Validates finite bid>0 and ask>=bid, preserves the raw
    file bytes for fingerprinting (sha256 of the file on disk, not of any in-memory
    transformation), and reports the dataset's actual covered period only — no fabricated
    coverage beyond what the file contains."""
    import csv

    rows: list[dict[str, Any]] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw_row in reader:
            bid, ask = float(raw_row["bid"]), float(raw_row["ask"])
            if not (bid > 0 and ask >= bid):
                raise ExecutionReplayBlocked(f"REPLAY BLOCKED: malformed real tick row (bid={bid}, ask={ask}) in {path}.")
            rows.append({"timestamp": raw_row["timestamp_server"], "bid": bid, "ask": ask, "last": None})
    return build_tick_dataset(rows, instrument="BTCUSD", broker=broker, timezone_label="MT5_SERVER", source_path=path)
