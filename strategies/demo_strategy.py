"""DEMO / ENGINE TEST STRATEGY. This is not a profitability claim."""
from __future__ import annotations

from dataclasses import dataclass
import math

from engine.models import Candle, Direction, Signal
from strategies.base import Strategy


@dataclass(frozen=True)
class DemoParameters:
    fast_ema: int = 20
    slow_ema: int = 50
    atr_length: int = 14
    stop_atr_multiplier: float = 1.5

    def __post_init__(self) -> None:
        if self.fast_ema < 1 or self.slow_ema <= self.fast_ema or self.atr_length < 1:
            raise ValueError("Require fast EMA >= 1, slow EMA > fast EMA, and ATR length >= 1.")
        if not math.isfinite(self.stop_atr_multiplier) or self.stop_atr_multiplier <= 0:
            raise ValueError("Stop ATR multiplier must be positive and finite.")


class DemoEmaCrossover(Strategy):
    def __init__(self, params: DemoParameters | None = None) -> None:
        self.params = params or DemoParameters()
        self.reset()

    def reset(self) -> None:
        self.bars = 0
        self.fast = self.slow = self.atr = self.previous_close = None
        self.previous_spread = None
        self.true_range_seed: list[float] = []

    def on_candle(self, candle: Candle) -> Signal | None:
        p = self.params
        true_range = (candle.high - candle.low if self.previous_close is None else
                      max(candle.high - candle.low,
                          abs(candle.high - self.previous_close),
                          abs(candle.low - self.previous_close)))
        self.bars += 1
        if self.atr is None:
            self.true_range_seed.append(true_range)
            if len(self.true_range_seed) == p.atr_length:
                self.atr = sum(self.true_range_seed) / p.atr_length
        else:
            self.atr = ((p.atr_length - 1) * self.atr + true_range) / p.atr_length
        self.fast = candle.close if self.fast is None else self.fast + (2 / (p.fast_ema + 1)) * (candle.close - self.fast)
        self.slow = candle.close if self.slow is None else self.slow + (2 / (p.slow_ema + 1)) * (candle.close - self.slow)
        spread = self.fast - self.slow
        direction = None
        if self.bars >= p.slow_ema and self.atr is not None and self.previous_spread is not None:
            if self.previous_spread <= 0 < spread:
                direction = Direction.LONG
            elif self.previous_spread >= 0 > spread:
                direction = Direction.SHORT
        self.previous_spread = spread
        self.previous_close = candle.close
        if direction is None:
            return None
        stop_distance = self.atr * p.stop_atr_multiplier
        stop = candle.close - stop_distance if direction is Direction.LONG else candle.close + stop_distance
        if stop <= 0:
            return None
        return Signal(direction, stop)
