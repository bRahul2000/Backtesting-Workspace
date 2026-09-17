"""Chronological backtest loop with next-open and pending-stop entries."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from engine.execution import (
    close_position, create_pending_order, exit_decision, fill_pending_order,
    open_position, validate_settings,
)
from engine.models import (
    BacktestIssue, BacktestResult, BacktestSettings, CancelPendingOrder, Candle,
    EntryModel, EquityPoint, ExecutionState, OrderEvent, PendingOrder, Signal,
)
from strategies.base import Strategy
from utils.data_validation import OHLCV_COLUMNS, invalid_ohlcv_mask


def _validated_candles(data: pd.DataFrame) -> list[Candle]:
    if not isinstance(data, pd.DataFrame) or any(col not in data for col in OHLCV_COLUMNS):
        raise ValueError("Backtest data needs timestamp, open, high, low, close, and volume columns.")
    if data.empty:
        return []
    times = pd.to_datetime(data["timestamp"], errors="coerce", utc=True)
    if times.isna().any() or times.duplicated().any() or not times.is_monotonic_increasing:
        raise ValueError("Backtest timestamps must be valid, unique, and chronological.")
    numeric = data[["open", "high", "low", "close", "volume"]].apply(pd.to_numeric, errors="coerce")
    checked = data.copy()
    checked["timestamp"] = times
    checked[numeric.columns] = numeric
    if invalid_ohlcv_mask(checked).any():
        raise ValueError("Backtest data contains invalid OHLCV rows; repair the dataset first.")
    return [Candle(row.timestamp, float(row.open), float(row.high), float(row.low),
                   float(row.close), float(row.volume)) for row in checked.itertuples(index=False)]


def _utc_timestamp(value: pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("Trading window boundaries must be valid timestamps.")
    return timestamp.tz_localize("UTC") if timestamp.tzinfo is None else timestamp.tz_convert("UTC")


def _order_event(order: PendingOrder, status: str, *, reason: str | None = None,
                 fill_time: pd.Timestamp | None = None,
                 fill_price: float | None = None) -> OrderEvent:
    return OrderEvent(
        signal_time=order.signal_time, created_time=order.created_time,
        direction=order.direction,
        trigger_price=order.trigger_price, stop_price=order.stop_price,
        expiry_time=order.expiry_time, expiry_bar_index=order.expiry_bar_index,
        status=status, cancel_reason=reason, fill_time=fill_time,
        fill_price=fill_price, setup_id=order.setup_id,
    )


def run_backtest(data: pd.DataFrame, strategy: Strategy,
                 settings: BacktestSettings | None = None,
                 *, trade_start: pd.Timestamp | None = None,
                 trade_end: pd.Timestamp | None = None) -> BacktestResult:
    """Backtest a window, feeding earlier candles only to strategy warm-up.

    `trade_start` and `trade_end` are inclusive candle-open timestamps. No
    position may enter before the start or exit after the end. Pre-start
    candles update strategy state but cannot create pending orders.
    """
    settings = settings or BacktestSettings()
    validate_settings(settings)
    start = _utc_timestamp(trade_start)
    end = _utc_timestamp(trade_end)
    if start is not None and end is not None and start > end:
        raise ValueError("Trading window start must not exceed its end.")
    if end is not None and isinstance(data, pd.DataFrame) and "timestamp" in data:
        timestamps = pd.to_datetime(data["timestamp"], errors="coerce", utc=True)
        if timestamps.isna().any():
            raise ValueError("Backtest timestamps must be valid.")
        # Candles beyond the requested window are not even validated for OHLC:
        # their future prices cannot affect this run's entries or exits.
        data = data.loc[timestamps <= end]
    candles = _validated_candles(data)
    if (start is not None or end is not None) and not any(
        (start is None or candle.timestamp >= start) for candle in candles
    ):
        raise ValueError("The trading window contains no candles.")
    result = BacktestResult(settings=settings)
    balance = settings.starting_balance
    peak = balance
    result.equity_curve.append(EquityPoint(None, None, balance, peak, 0.0, 0.0))
    strategy.reset()
    strategy.on_backtest_window(start, end)
    pending_next: tuple[Signal, pd.Timestamp] | None = None
    pending_stop: PendingOrder | None = None
    position = None
    previous_time = None
    for index, candle in enumerate(candles):
        if previous_time is not None and candle.timestamp - previous_time != pd.Timedelta(minutes=15):
            if position is not None:
                raise ValueError(
                    f"An open position crosses missing candles before {candle.timestamp}; "
                    "its exit cannot be determined. Select a contiguous date range."
                )
            if pending_next is not None:
                result.issues.append(BacktestIssue(candle.timestamp, "Pending signal cancelled across a data gap."))
                pending_next = None
            if pending_stop is not None:
                result.order_events.append(_order_event(
                    pending_stop, "cancelled", reason="Data gap before trigger."))
                result.issues.append(BacktestIssue(candle.timestamp, "Pending stop order cancelled across a data gap."))
                pending_stop = None
            strategy.on_data_gap()
            result.issues.append(BacktestIssue(candle.timestamp, "Dataset has a time gap; indicators restarted without invented candles."))
        previous_time = candle.timestamp

        entered_intrabar = False
        opened_position = None
        closed_trade = None
        if pending_next is not None:
            signal, signal_time = pending_next
            pending_next = None
            try:
                position = open_position(signal, signal_time, candle.timestamp,
                                         candle.open, index,
                                         len(result.trades) + 1, balance, settings)
            except (ValueError, TypeError, OverflowError) as exc:
                result.issues.append(BacktestIssue(candle.timestamp, f"Signal rejected at entry: {exc}"))
            else:
                opened_position = position
        elif pending_stop is not None:
            order = pending_stop
            if index > order.expiry_bar_index:
                result.order_events.append(_order_event(
                    order, "expired", reason="Expiry bar passed without a trigger."))
                pending_stop = None
            else:
                try:
                    position = fill_pending_order(order, candle, index,
                                                  len(result.trades) + 1, settings)
                except (ValueError, TypeError, OverflowError) as exc:
                    result.order_events.append(_order_event(order, "cancelled", reason=str(exc)))
                    result.issues.append(BacktestIssue(candle.timestamp, f"Pending fill rejected: {exc}"))
                    pending_stop = None
                else:
                    if position is not None:
                        opened_position = position
                        entered_intrabar = (not position.gap_through_trigger and
                            ((position.direction.value == "LONG" and candle.open < order.trigger_price)
                             or (position.direction.value == "SHORT" and candle.open > order.trigger_price)))
                        result.order_events.append(_order_event(
                            order, "triggered", fill_time=candle.timestamp,
                            fill_price=position.entry_price))
                        pending_stop = None
                    elif index == order.expiry_bar_index:
                        result.order_events.append(_order_event(
                            order, "expired", reason="Not triggered by the end of the expiry bar."))
                        pending_stop = None

        if position is not None:
            decision = exit_decision(position, candle, settings.same_bar_resolution,
                                     entered_intrabar=entered_intrabar)
            if decision is not None:
                raw_exit, reason = decision
                trade = close_position(position, candle, index, raw_exit, reason, settings)
                result.trades.append(trade)
                closed_trade = trade
                balance += trade.pnl
                peak = max(peak, balance)
                drawdown = peak - balance
                result.equity_curve.append(EquityPoint(
                    candle.timestamp, trade.trade_id, balance, peak, drawdown,
                    drawdown / peak * 100,
                ))
                position = None

        # This call occurs only after execution for this candle. The strategy
        # receives exactly this completed candle, never future rows.
        strategy.on_execution_state(ExecutionState(
            balance=balance, pending_order=pending_stop, position=position,
            opened_position=opened_position, closed_trade=closed_trade,
        ))
        signal = strategy.on_candle(candle)
        if start is not None and candle.timestamp < start:
            continue
        if isinstance(signal, CancelPendingOrder):
            if not signal.reason.strip():
                result.issues.append(BacktestIssue(candle.timestamp, "Pending cancellation requires a reason."))
            elif pending_stop is None:
                result.issues.append(BacktestIssue(candle.timestamp, "No pending stop order exists to cancel."))
            elif signal.setup_id is not None and signal.setup_id != pending_stop.setup_id:
                result.issues.append(BacktestIssue(candle.timestamp, "Cancellation setup ID did not match the pending order."))
            else:
                result.order_events.append(_order_event(pending_stop, "cancelled", reason=signal.reason))
                pending_stop = None
        elif signal is not None:
            if not isinstance(signal, Signal):
                result.issues.append(BacktestIssue(candle.timestamp, "Strategy returned an invalid signal object."))
            elif position is not None:
                result.issues.append(BacktestIssue(candle.timestamp, "Signal ignored while a position is open."))
            elif pending_next is not None or pending_stop is not None:
                result.issues.append(BacktestIssue(candle.timestamp, "Signal ignored while an entry order is pending."))
            elif index == len(candles) - 1 and signal.entry_model is EntryModel.NEXT_OPEN:
                result.issues.append(BacktestIssue(candle.timestamp + pd.Timedelta(minutes=15), "Final signal has no next candle for entry."))
            elif signal.entry_model is EntryModel.NEXT_OPEN:
                signal = replace(signal, setup_id=signal.setup_id or type(strategy).__name__)
                pending_next = (signal, candle.timestamp + pd.Timedelta(minutes=15))
            elif signal.entry_model is EntryModel.STOP_ENTRY_PENDING:
                signal = replace(signal, setup_id=signal.setup_id or type(strategy).__name__)
                try:
                    pending_stop = create_pending_order(signal, candle, index, balance, settings)
                except (ValueError, TypeError, OverflowError) as exc:
                    result.issues.append(BacktestIssue(candle.timestamp, f"Pending order rejected: {exc}"))
            else:
                result.issues.append(BacktestIssue(candle.timestamp, "Unknown entry model in strategy signal."))

    result.open_position = position
    if pending_stop is not None:
        final_action = strategy.on_backtest_end(pending_stop)
        if isinstance(final_action, CancelPendingOrder) and final_action.reason.strip():
            if final_action.setup_id is None or final_action.setup_id == pending_stop.setup_id:
                result.order_events.append(_order_event(
                    pending_stop, "cancelled", reason=final_action.reason))
                pending_stop = None
    result.pending_order = pending_stop
    if pending_stop is not None:
        result.order_events.append(_order_event(
            pending_stop, "active_at_end", reason="Dataset ended before fill or expiry."))
        result.issues.append(BacktestIssue(candles[-1].timestamp, "Pending order remains active at dataset end."))
    if position is not None:
        result.issues.append(BacktestIssue(candles[-1].timestamp, "Position remains open at dataset end; unrealized PnL is excluded."))
    return result
