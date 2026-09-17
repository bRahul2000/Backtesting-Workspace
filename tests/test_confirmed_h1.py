import unittest

import pandas as pd

from engine.models import Candle
from strategies.confirmed_h1 import ConfirmedH1Trend


def candle(hour, minute, close):
    timestamp = pd.Timestamp(f"2025-01-01T{hour:02d}:{minute:02d}:00Z")
    return Candle(timestamp, close, close + 1, close - 1, close, 1)


class ConfirmedH1Tests(unittest.TestCase):
    def test_unfinished_hour_never_leaks_into_any_of_its_m15_bars(self):
        trend = ConfirmedH1Trend(2, 3, 1)
        for hour, price in ((8, 100), (9, 101), (10, 102)):
            for minute in (0, 15, 30, 45):
                value = trend.update(candle(hour, minute, price))
                if hour == 10:
                    self.assertEqual(value.hour, pd.Timestamp("2025-01-01T09:00:00Z"))
                    self.assertEqual(value.close, 101)
                    self.assertTrue(value.long)
        at_11 = trend.update(candle(11, 0, 103))
        self.assertEqual(at_11.hour, pd.Timestamp("2025-01-01T10:00:00Z"))
        self.assertEqual(at_11.close, 102)

    def test_confirmed_short_trend(self):
        trend = ConfirmedH1Trend(2, 3, 1)
        for hour, price in ((8, 102), (9, 101), (10, 100)):
            for minute in (0, 15, 30, 45):
                trend.update(candle(hour, minute, price))
        self.assertTrue(trend.update(candle(11, 0, 99)).short)

    def test_partial_hour_is_not_accepted_as_confirmed(self):
        trend = ConfirmedH1Trend(2, 3, 1)
        trend.update(candle(8, 15, 100))
        trend.update(candle(8, 30, 100))
        self.assertIsNone(trend.update(candle(9, 0, 101)).close)


if __name__ == "__main__":
    unittest.main()
