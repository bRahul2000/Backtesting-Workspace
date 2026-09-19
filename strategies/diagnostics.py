from __future__ import annotations

from dataclasses import dataclass

from engine.diagnostics import DiagnosticEvent
from engine.models import CancelPendingOrder, ExecutionState, Signal
from strategies.base import Strategy


class DiagnosticStrategyObserver(Strategy):
    """Transparent observer around an existing strategy.

    It records lifecycle events only; the wrapped strategy owns every decision.
    """

    def __init__(self, strategy: Strategy, strategy_id: str):
        self.strategy = strategy
        self.strategy_id = strategy_id
        self.events: list[DiagnosticEvent] = []

    def reset(self) -> None:
        self.events.clear()
        self.strategy.reset()

    def on_backtest_window(self, start, end) -> None:
        self.strategy.on_backtest_window(start, end)

    def on_data_gap(self) -> None:
        self.events.append(DiagnosticEvent("data_gap", False, "continuous segment reset", None, self.strategy_id))
        self.strategy.on_data_gap()

    def on_backtest_end(self, pending_order):
        return self.strategy.on_backtest_end(pending_order)

    def on_execution_state(self, state: ExecutionState) -> None:
        timestamp = state.opened_position.entry_time if state.opened_position else (
            state.closed_trade.exit_time if state.closed_trade else None
        )
        if state.opened_position:
            self.events.append(DiagnosticEvent("trade_entered", True, None, timestamp,
                                               state.opened_position.setup_id))
        if state.closed_trade:
            self.events.append(DiagnosticEvent("trade_exited", True, None, timestamp,
                                               state.closed_trade.setup_id))
        self.strategy.on_execution_state(state)

    def on_candle(self, candle):
        self.events.append(DiagnosticEvent("bars_evaluated", True, None, candle.timestamp,
                                           self.strategy_id))
        signal = self.strategy.on_candle(candle)
        if isinstance(signal, Signal):
            self.events.extend([
                DiagnosticEvent("setup_detected", True, None, candle.timestamp, signal.setup_id),
                DiagnosticEvent("order_created", True, None, candle.timestamp, signal.setup_id),
            ])
        elif isinstance(signal, CancelPendingOrder):
            self.events.append(DiagnosticEvent("order_cancelled", True, signal.reason,
                                               candle.timestamp, signal.setup_id))
        return signal
