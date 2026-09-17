"""Build complete UTC H1 candles from M15 bars without exposing the current hour."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

import pandas as pd

from engine.models import Candle
from strategies.pine_indicators import EMA


@dataclass(frozen=True)
class H1TrendValue:
    hour: pd.Timestamp | None
    close: float | None
    fast_ema: float | None
    slow_ema: float | None
    slow_ema_lookback: float | None

    @property
    def long(self) -> bool:
        return (self.close is not None and self.slow_ema_lookback is not None
                and self.close > self.slow_ema
                and self.fast_ema > self.slow_ema
                and self.slow_ema > self.slow_ema_lookback)

    @property
    def short(self) -> bool:
        return (self.close is not None and self.slow_ema_lookback is not None
                and self.close < self.slow_ema
                and self.fast_ema < self.slow_ema
                and self.slow_ema < self.slow_ema_lookback)


class ConfirmedH1Trend:
    def __init__(self, fast_length: int = 50, slow_length: int = 200,
                 slope_lookback: int = 5) -> None:
        if fast_length < 1 or slow_length < 1 or slope_lookback < 1:
            raise ValueError("H1 lengths and slope lookback must be positive.")
        self.fast = EMA(fast_length)
        self.slow = EMA(slow_length)
        self.slope_lookback = slope_lookback
        self.slow_history: deque[float] = deque(maxlen=slope_lookback + 1)
        self.bucket: pd.Timestamp | None = None
        self.bucket_bars: list[Candle] = []
        self.confirmed = H1TrendValue(None, None, None, None, None)

    def update(self, candle: Candle) -> H1TrendValue:
        """Return prior confirmed H1 trend for this M15 candle's hour."""
        hour = candle.timestamp.floor("h")
        if self.bucket is not None and hour != self.bucket:
            self._complete_bucket()
            self.bucket_bars.clear()
        self.bucket = hour
        self.bucket_bars.append(candle)
        return self.confirmed

    def _complete_bucket(self) -> None:
        times = [bar.timestamp for bar in self.bucket_bars]
        expected = [self.bucket + pd.Timedelta(minutes=15 * index) for index in range(4)]
        if times != expected:
            return  # An incomplete H1 candle must never enter the EMA series.
        close = self.bucket_bars[-1].close
        fast = self.fast.update(close)
        slow = self.slow.update(close)
        self.slow_history.append(slow)
        lookback = (self.slow_history[0] if len(self.slow_history) ==
                    self.slope_lookback + 1 else None)
        self.confirmed = H1TrendValue(self.bucket, close, fast, slow, lookback)
