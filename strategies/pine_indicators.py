"""Streaming equivalents of Pine EMA, RMA, ATR, RSI, and DMI.

All updates consume one completed candle. RMA seeds with the simple mean of
its first ``length`` non-NaN observations, as Pine's ``ta.rma`` does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

from engine.models import Candle


@dataclass
class EMA:
    length: int
    value: float | None = None

    def __post_init__(self) -> None:
        if self.length < 1:
            raise ValueError("EMA length must be positive.")

    def update(self, price: float) -> float:
        if not isfinite(price):
            raise ValueError("EMA price must be finite.")
        self.value = (price if self.value is None else
                      self.value + 2 / (self.length + 1) * (price - self.value))
        return self.value


@dataclass
class RMA:
    length: int
    value: float | None = None
    _seed: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.length < 1:
            raise ValueError("RMA length must be positive.")

    def update(self, observation: float | None) -> float | None:
        if observation is None:
            return self.value
        if not isfinite(observation):
            raise ValueError("RMA observation must be finite.")
        if self.value is None:
            self._seed.append(observation)
            if len(self._seed) == self.length:
                self.value = sum(self._seed) / self.length
        else:
            self.value += (observation - self.value) / self.length
        return self.value


@dataclass
class ATR:
    length: int
    previous_close: float | None = None

    def __post_init__(self) -> None:
        self._average = RMA(self.length)

    def update(self, candle: Candle) -> float | None:
        tr = (candle.high - candle.low if self.previous_close is None else
              max(candle.high - candle.low,
                  abs(candle.high - self.previous_close),
                  abs(candle.low - self.previous_close)))
        self.previous_close = candle.close
        return self._average.update(tr)


@dataclass
class RSI:
    length: int
    previous_close: float | None = None

    def __post_init__(self) -> None:
        self._gain = RMA(self.length)
        self._loss = RMA(self.length)

    def update(self, close: float) -> float | None:
        if self.previous_close is None:
            self.previous_close = close
            return None
        change = close - self.previous_close
        self.previous_close = close
        gain = self._gain.update(max(change, 0.0))
        loss = self._loss.update(max(-change, 0.0))
        if gain is None or loss is None:
            return None
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)


@dataclass(frozen=True)
class DMIValue:
    plus_di: float | None
    minus_di: float | None
    adx: float | None


@dataclass
class DMI:
    di_length: int
    adx_smoothing: int
    previous: Candle | None = None

    def __post_init__(self) -> None:
        self._tr = RMA(self.di_length)
        self._plus = RMA(self.di_length)
        self._minus = RMA(self.di_length)
        self._adx = RMA(self.adx_smoothing)

    def update(self, candle: Candle) -> DMIValue:
        previous = self.previous
        self.previous = candle
        if previous is None:
            # Pine's ta.tr includes the first bar's high-low even though
            # directional movement needs a previous bar.
            self._tr.update(candle.high - candle.low)
            return DMIValue(None, None, None)
        up = candle.high - previous.high
        down = previous.low - candle.low
        plus = up if up > down and up > 0 else 0.0
        minus = down if down > up and down > 0 else 0.0
        tr = max(candle.high - candle.low,
                 abs(candle.high - previous.close),
                 abs(candle.low - previous.close))
        tr_avg = self._tr.update(tr)
        plus_avg = self._plus.update(plus)
        minus_avg = self._minus.update(minus)
        if tr_avg is None or plus_avg is None or minus_avg is None:
            return DMIValue(None, None, None)
        divisor = tr_avg if tr_avg != 0 else 1.0
        plus_di = 100 * plus_avg / divisor
        minus_di = 100 * minus_avg / divisor
        total = plus_di + minus_di
        dx = 100 * abs(plus_di - minus_di) / (total if total != 0 else 1.0)
        return DMIValue(plus_di, minus_di, self._adx.update(dx))
