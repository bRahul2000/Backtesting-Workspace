"""Confirmed H1 context for BTC V3 without exposing the current H1 candle."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import pandas as pd

from engine.models import Candle
from strategies.pine_indicators import ATR, EMA


@dataclass(frozen=True)
class H1RegimeValue:
    hour: pd.Timestamp | None
    close: float | None
    fast_ema: float | None
    slow_ema: float | None
    slow_ema_lookback: float | None
    atr: float | None

    @property
    def slope(self) -> float | None:
        if self.slow_ema is None or self.slow_ema_lookback is None:
            return None
        return self.slow_ema - self.slow_ema_lookback

    @property
    def separation_atr(self) -> float | None:
        if (self.fast_ema is None or self.slow_ema is None or self.atr is None
                or self.atr <= 0):
            return None
        return abs(self.fast_ema - self.slow_ema) / self.atr


class ConfirmedH1Regime:
    """Aggregate M15 into complete UTC H1 bars and expose only the prior hour."""

    def __init__(self, fast_length: int = 50, slow_length: int = 200,
                 atr_length: int = 14, slope_lookback: int = 4) -> None:
        if min(fast_length, slow_length, atr_length, slope_lookback) < 1:
            raise ValueError("H1 regime lengths must be positive.")
        self.fast = EMA(fast_length)
        self.slow = EMA(slow_length)
        self.atr = ATR(atr_length)
        self.slope_lookback = slope_lookback
        self.slow_history: deque[float] = deque(maxlen=slope_lookback + 1)
        self.bucket: pd.Timestamp | None = None
        self.bucket_bars: list[Candle] = []
        self.confirmed = H1RegimeValue(None, None, None, None, None, None)

    def update(self, candle: Candle) -> H1RegimeValue:
        hour = candle.timestamp.floor("h")
        if self.bucket is not None and hour != self.bucket:
            self._complete_bucket()
            self.bucket_bars.clear()
        self.bucket = hour
        self.bucket_bars.append(candle)
        return self.confirmed

    def _complete_bucket(self) -> None:
        expected = [self.bucket + pd.Timedelta(minutes=15 * index) for index in range(4)]
        if [bar.timestamp for bar in self.bucket_bars] != expected:
            return
        bar = Candle(
            timestamp=self.bucket,
            open=self.bucket_bars[0].open,
            high=max(item.high for item in self.bucket_bars),
            low=min(item.low for item in self.bucket_bars),
            close=self.bucket_bars[-1].close,
            volume=sum(item.volume for item in self.bucket_bars),
        )
        fast = self.fast.update(bar.close)
        slow = self.slow.update(bar.close)
        atr = self.atr.update(bar)
        self.slow_history.append(slow)
        past = (self.slow_history[0]
                if len(self.slow_history) == self.slope_lookback + 1 else None)
        self.confirmed = H1RegimeValue(self.bucket, bar.close, fast, slow, past, atr)
