from __future__ import annotations

from abc import ABC, abstractmethod

from engine.models import Candle, Signal


class Strategy(ABC):
    @abstractmethod
    def reset(self) -> None:
        """Reset all indicator state before a backtest."""

    @abstractmethod
    def on_candle(self, candle: Candle) -> Signal | None:
        """Observe one completed candle and optionally emit a close-confirmed signal."""
