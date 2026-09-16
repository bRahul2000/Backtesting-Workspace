"""Chronological backtest loop with close-confirmed signals and next-open fills."""
from __future__ import annotations

import pandas as pd

from engine.execution import close_position, exit_decision, open_position, validate_settings
from engine.models import (
    BacktestIssue, BacktestResult, BacktestSettings, Candle, EquityPoint, Signal,
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
    pending: tuple[Signal, pd.Timestamp] | None = None
    position = None
    previous_time = None
    for index, candle in enumerate(candles):
        if previous_time is not None and candle.timestamp - previous_time != pd.Timedelta(minutes=15):
            if position is not None:
                raise ValueError(
                    f"An open position crosses missing candles before {candle.timestamp}; "
                    "its exit cannot be determined. Select a contiguous date range."
                )
            if pending is not None:
                result.issues.append(BacktestIssue(candle.timestamp, "Pending signal cancelled across a data gap."))
                pending = None
            strategy.reset()
            result.issues.append(BacktestIssue(candle.timestamp, "Dataset has a time gap; indicators restarted without invented candles."))
        previous_time = candle.timestamp

        if pending is not None:
            signal, signal_time = pending
            pending = None
            try:
                position = open_position(signal, signal_time, candle.timestamp,
                                         candle.open, index,
                                         len(result.trades) + 1, balance, settings)
            except (ValueError, TypeError, OverflowError) as exc:
                result.issues.append(BacktestIssue(candle.timestamp, f"Signal rejected at entry: {exc}"))

        if position is not None:
            decision = exit_decision(position, candle, settings.same_bar_resolution)
            if decision is not None:
                raw_exit, reason = decision
                trade = close_position(position, candle, index, raw_exit, reason, settings)
                result.trades.append(trade)
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
        signal = strategy.on_candle(candle)
        if start is not None and candle.timestamp < start:
            continue
        if signal is not None:
            if not isinstance(signal, Signal):
                result.issues.append(BacktestIssue(candle.timestamp, "Strategy returned an invalid signal object."))
            elif position is not None or pending is not None:
                result.issues.append(BacktestIssue(candle.timestamp, "Signal ignored while a position is open."))
            elif index == len(candles) - 1:
                result.issues.append(BacktestIssue(candle.timestamp + pd.Timedelta(minutes=15), "Final signal has no next candle for entry."))
            else:
                pending = (signal, candle.timestamp + pd.Timedelta(minutes=15))

    result.open_position = position
    if position is not None:
        result.issues.append(BacktestIssue(candles[-1].timestamp, "Position remains open at dataset end; unrealized PnL is excluded."))
    return result
