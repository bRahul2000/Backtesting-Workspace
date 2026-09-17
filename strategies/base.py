from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from engine.models import CancelPendingOrder, Candle, ExecutionState, PendingOrder, Signal


class Strategy(ABC):
    def on_backtest_window(self, start: pd.Timestamp | None, end: pd.Timestamp | None) -> None:
        """Optional inclusive trading-window boundaries for strategy permissions."""

    def on_data_gap(self) -> None:
        """Reset indicator continuity; strategies with account state may override."""
        self.reset()

    def on_backtest_end(self, pending_order: PendingOrder) -> CancelPendingOrder | None:
        """Optional final cancellation of a still-pending order."""
        return None

    def on_execution_state(self, state: ExecutionState) -> None:
        """Optional account/order feedback before the next completed-candle signal."""

    @abstractmethod
    def reset(self) -> None:
        """Reset all indicator state before a backtest."""

    @abstractmethod
    def on_candle(self, candle: Candle) -> Signal | CancelPendingOrder | None:
        """Observe a completed candle; optionally signal or cancel pending entry."""
