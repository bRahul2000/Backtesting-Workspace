"""Hand-calculated Pine-style indicator seed and update fixtures."""
import unittest

import pandas as pd

from engine.models import Candle
from strategies.pine_indicators import ATR, DMI, EMA, RMA, RSI


def bar(index, high, low, close):
    return Candle(pd.Timestamp("2025-01-01T00:00:00Z") + pd.Timedelta(minutes=15 * index),
                  close, high, low, close, 1)


class PineIndicatorTests(unittest.TestCase):
    def test_ema_seeds_first_price_and_uses_standard_alpha(self):
        ema = EMA(3)
        self.assertEqual([ema.update(x) for x in (10, 12, 14, 16)],
                         [10, 11, 12.5, 14.25])

    def test_rma_seeds_with_sma_then_wilder_updates(self):
        rma = RMA(3)
        self.assertEqual([rma.update(x) for x in (1, 2, 3, 5)],
                         [None, None, 2, 3])

    def test_atr_includes_first_candle_true_range(self):
        atr = ATR(2)
        self.assertIsNone(atr.update(bar(0, 11, 9, 10)))
        self.assertEqual(atr.update(bar(1, 13, 10, 12)), 2.5)
        self.assertEqual(atr.update(bar(2, 15, 11, 14)), 3.25)

    def test_rsi_requires_length_price_changes_and_wilder_smoothing(self):
        rsi = RSI(2)
        self.assertEqual([rsi.update(x) for x in (10, 11, 12, 11, 10)],
                         [None, None, 100, 50, 25])

    def test_dmi_smoothing_seed_and_plus_di(self):
        dmi = DMI(2, 2)
        values = [dmi.update(candle) for candle in (
            bar(0, 11, 9, 10), bar(1, 13, 10, 12),
            bar(2, 15, 11, 14), bar(3, 16, 12, 15),
        )]
        self.assertIsNone(values[1].plus_di)
        self.assertAlmostEqual(values[2].plus_di, 100 * 2 / 3.25)
        self.assertEqual(values[2].minus_di, 0)
        self.assertIsNone(values[2].adx)
        self.assertAlmostEqual(values[3].plus_di, 100 * 1.5 / 3.625)
        self.assertEqual(values[3].adx, 100)


if __name__ == "__main__":
    unittest.main()
