from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from math import isfinite
from typing import Any, Iterable

import pandas as pd

from engine.models import Direction, OrderEvent, Trade


BAR_BASED_APPROXIMATION = "BAR_BASED_APPROXIMATION"


@dataclass(frozen=True)
class DiagnosticEvent:
    stage: str
    passed: bool | None
    reason: str | None
    timestamp: pd.Timestamp | None
    component: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class XRayEvaluation:
    timestamp: pd.Timestamp
    strategy_id: str
    component: str | None
    rule: str
    observed_value: Any
    threshold: Any
    result: str
    reason_code: str
    description: str


@dataclass(frozen=True)
class ExecutionAmbiguity:
    ambiguity_type: str
    timestamp: pd.Timestamp
    trade_id: int | None
    order_id: str | None
    levels: dict[str, float]
    resolution_policy: str


@dataclass(frozen=True)
class ExposureRecord:
    first_seen_at: str
    strategy_id: str
    strategy_version: str
    parameter_fingerprint: str
    dataset_fingerprint: str
    dataset_role: str
    exposure_count: int
    warning: str | None = None


def enrich_trade(trade: Trade, candles: pd.DataFrame, *, spread: float = 0.0,
                 atr_column: str | None = None) -> Trade:
    """Add OHLC excursion observations over the inclusive entry/exit interval.

    OHLC cannot reveal the intrabar path, so extrema are explicitly labeled as
    BAR_BASED_APPROXIMATION. Long exits observe Bid candles; short exits observe
    the synthetic Ask candle by adding the configured spread.
    """
    if candles.empty:
        return trade
    timestamps = pd.to_datetime(candles["timestamp"], utc=True)
    interval = candles.loc[timestamps.between(trade.entry_time, trade.exit_time)].copy()
    if interval.empty:
        return trade
    if trade.direction is Direction.SHORT:
        highs = interval["high"] + spread
        lows = interval["low"] + spread
    else:
        highs = interval["high"]
        lows = interval["low"]
    if trade.direction is Direction.LONG:
        mfe_index, mae_index = highs.idxmax(), lows.idxmin()
        mfe_price, mae_price = float(highs.loc[mfe_index]), float(lows.loc[mae_index])
        favorable_exit = max(float(trade.exit_price - trade.entry_price), 0.0)
        adverse_exit = max(float(trade.entry_price - trade.exit_price), 0.0)
    else:
        mfe_index, mae_index = lows.idxmin(), highs.idxmax()
        mfe_price, mae_price = float(lows.loc[mfe_index]), float(highs.loc[mae_index])
        favorable_exit = max(float(trade.entry_price - trade.exit_price), 0.0)
        adverse_exit = max(float(trade.exit_price - trade.entry_price), 0.0)
    mfe_amount = max(abs(mfe_price - trade.entry_price), 0.0)
    mae_amount = max(abs(mae_price - trade.entry_price), 0.0)
    # R-multiples must be normalized by the price-distance to stop, not by
    # trade.initial_risk (a dollar-denominated, quantity-scaled risk amount) —
    # dividing a raw price excursion by a dollar amount produced a bogus,
    # per-trade-varying ratio whenever quantity != 1.
    stop_distance = abs(float(trade.entry_price - trade.stop_loss))
    mfe_r = mfe_amount / stop_distance if stop_distance > 0 else None
    mae_r = mae_amount / stop_distance if stop_distance > 0 else None
    capture = favorable_exit / mfe_amount if mfe_amount > 0 else None
    adverse = adverse_exit / mae_amount if mae_amount > 0 else None
    entry_atr = None
    if atr_column and atr_column in interval:
        value = interval[atr_column].iloc[0]
        entry_atr = stop_distance / float(value) if float(value) > 0 else None
    return replace(
        trade,
        mfe_price=mfe_price, mfe_amount=mfe_amount, mfe_r=mfe_r,
        mfe_percent=mfe_amount / abs(trade.entry_price) * 100 if trade.entry_price else None,
        mae_price=mae_price, mae_amount=mae_amount, mae_r=mae_r,
        mae_percent=mae_amount / abs(trade.entry_price) * 100 if trade.entry_price else None,
        mfe_timestamp=pd.Timestamp(candles.loc[mfe_index, "timestamp"]),
        mae_timestamp=pd.Timestamp(candles.loc[mae_index, "timestamp"]),
        duration_minutes=(pd.Timestamp(trade.exit_time) - pd.Timestamp(trade.entry_time)).total_seconds() / 60,
        initial_stop_distance=stop_distance, initial_stop_distance_atr=entry_atr,
        highest_price_while_open=float(highs.max()), lowest_price_while_open=float(lows.min()),
        capture_efficiency=capture, adverse_efficiency=adverse,
        excursion_model=BAR_BASED_APPROXIMATION,
    )


def enrich_result(result: Any, candles: pd.DataFrame, *, spread: float = 0.0) -> Any:
    result.trades = [enrich_trade(trade, candles, spread=spread) for trade in result.trades]
    result.execution_ambiguities = detect_execution_ambiguities(candles, result.trades, result.order_events)
    return result


def funnel_summary(events: Iterable[DiagnosticEvent]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        row = grouped.setdefault(event.stage, {"stage": event.stage, "passed": 0, "failed": 0, "events": 0})
        row["events"] += 1
        if event.passed is True:
            row["passed"] += 1
        elif event.passed is False:
            row["failed"] += 1
    ordered = list(grouped.values())
    previous = None
    for row in ordered:
        row["conversion_percent"] = None if previous in (None, 0) else row["passed"] / previous * 100
        previous = row["passed"] or previous
    return ordered


def detect_execution_ambiguities(candles: pd.DataFrame, trades: Iterable[Trade],
                                 orders: Iterable[OrderEvent], *,
                                 resolution_policy: str = "SL_FIRST") -> list[ExecutionAmbiguity]:
    output: list[ExecutionAmbiguity] = []
    by_time = {pd.Timestamp(row.timestamp): row for row in candles.itertuples(index=False)}
    for trade in trades:
        candle = by_time.get(pd.Timestamp(trade.exit_time))
        if candle is None:
            continue
        stop_hit = (candle.low <= trade.stop_loss if trade.direction is Direction.LONG
                    else candle.high >= trade.stop_loss)
        target_hit = (candle.high >= trade.take_profit if trade.direction is Direction.LONG
                      else candle.low <= trade.take_profit)
        if stop_hit and target_hit:
            output.append(ExecutionAmbiguity(
                "SL_AND_TP_SAME_CANDLE", pd.Timestamp(trade.exit_time), trade.trade_id, None,
                {"stop": trade.stop_loss, "target": trade.take_profit}, resolution_policy,
            ))
    for order in orders:
        if order.fill_time is None:
            continue
        candle = by_time.get(pd.Timestamp(order.fill_time))
        if candle is None:
            continue
        entry_hit = (candle.high >= order.trigger_price if order.direction is Direction.LONG
                     else candle.low <= order.trigger_price)
        stop_hit = (candle.low <= order.stop_price if order.direction is Direction.LONG
                    else candle.high >= order.stop_price)
        if entry_hit and stop_hit:
            output.append(ExecutionAmbiguity(
                "PENDING_ENTRY_AND_STOP_SAME_CANDLE", pd.Timestamp(order.fill_time), None,
                f"{order.signal_time.isoformat()}-{order.direction.value}",
                {"trigger": order.trigger_price, "stop": order.stop_price}, resolution_policy,
            ))
    return output


def compare_trades(left: Iterable[Trade], right: Iterable[Trade], *,
                   timestamp_tolerance: timedelta = timedelta(0)) -> list[dict[str, Any]]:
    """Match by direction, setup, and entry timestamp, never by trade number."""
    left_rows, right_rows = list(left), list(right)
    used: set[int] = set()
    output: list[dict[str, Any]] = []
    for trade_a in left_rows:
        candidates = [
            (abs(pd.Timestamp(trade_a.entry_time) - pd.Timestamp(trade_b.entry_time)), index, trade_b)
            for index, trade_b in enumerate(right_rows)
            if index not in used and trade_a.direction == trade_b.direction
            and trade_a.setup_id == trade_b.setup_id
            and abs(pd.Timestamp(trade_a.entry_time) - pd.Timestamp(trade_b.entry_time)) <= timestamp_tolerance
        ]
        if not candidates:
            output.append({"status": "ONLY_IN_A", "trade_a": trade_a.trade_id, "trade_b": None})
            continue
        _, index, trade_b = min(candidates, key=lambda item: item[0])
        used.add(index)
        changes = []
        for label, attr in (("entry", "entry_price"), ("exit", "exit_price"),
                            ("SL", "stop_loss"), ("target", "take_profit"),
                            ("size", "quantity"), ("outcome", "pnl"), ("R", "r_multiple")):
            if getattr(trade_a, attr) != getattr(trade_b, attr):
                changes.append(f"CHANGED_{label.upper()}")
        output.append({"status": "MATCHING" if not changes else "CHANGED",
                       "trade_a": trade_a.trade_id, "trade_b": trade_b.trade_id,
                       "changes": changes})
    output.extend({"status": "ONLY_IN_B", "trade_a": None, "trade_b": trade.trade_id}
                  for index, trade in enumerate(right_rows) if index not in used)
    return output


def serialize_diagnostics(events: Iterable[DiagnosticEvent]) -> list[dict[str, Any]]:
    return [asdict(event) for event in events]
