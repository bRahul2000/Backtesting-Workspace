import unittest

from engine.models import Candle
from strategies.demo_strategy import DemoEmaCrossover, DemoParameters


class DemoIndicatorTests(unittest.TestCase):
    def test_ema_and_atr_use_only_observed_candles(self):
        strategy = DemoEmaCrossover(DemoParameters(2, 3, 2, 1.5))
        bars = [
            Candle(None, 100, 101, 99, 100, 1),
            Candle(None, 100, 103, 100, 102, 1),
            Candle(None, 102, 104, 100, 101, 1),
        ]
        strategy.on_candle(bars[0])
        self.assertEqual((strategy.fast, strategy.slow, strategy.atr), (100, 100, None))
        strategy.on_candle(bars[1])
        self.assertAlmostEqual(strategy.fast, 100 + (102 - 100) * 2 / 3)
        self.assertEqual(strategy.slow, 101)
        self.assertEqual(strategy.atr, 2.5)
        strategy.on_candle(bars[2])
        self.assertAlmostEqual(strategy.fast, 101.11111111111111)
        self.assertEqual(strategy.slow, 101)
        self.assertEqual(strategy.atr, 3.25)

    def test_future_candle_change_cannot_revise_prior_state(self):
        first = Candle(None, 100, 101, 99, 100, 1)
        second = Candle(None, 100, 103, 100, 102, 1)
        a = DemoEmaCrossover(DemoParameters(2, 3, 2, 1.5))
        b = DemoEmaCrossover(DemoParameters(2, 3, 2, 1.5))
        for candle in (first, second):
            self.assertEqual(a.on_candle(candle), b.on_candle(candle))
        before = (a.fast, a.slow, a.atr, a.previous_spread)
        self.assertEqual(before, (b.fast, b.slow, b.atr, b.previous_spread))
        b.on_candle(Candle(None, 102, 150, 50, 120, 1))
        self.assertEqual((a.fast, a.slow, a.atr, a.previous_spread), before)


if __name__ == "__main__":
    unittest.main()
