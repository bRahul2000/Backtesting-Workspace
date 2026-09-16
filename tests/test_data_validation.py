import unittest

import pandas as pd

from utils.data_validation import find_missing_ranges, prepare_ohlcv, validate_ohlcv


class DataValidationTests(unittest.TestCase):
    def test_prepare_sorts_and_removes_duplicate_timestamps(self):
        raw = pd.DataFrame(
            [
                {"timestamp": "2025-01-01T00:15:00Z", "open": 2, "high": 3, "low": 1, "close": 2, "volume": 1},
                {"timestamp": "2025-01-01T00:00:00Z", "open": 1, "high": 2, "low": 1, "close": 2, "volume": 1},
                {"timestamp": "2025-01-01T00:15:00Z", "open": 2, "high": 4, "low": 1, "close": 3, "volume": 1},
            ]
        )
        prepared, stats = prepare_ohlcv(raw)
        self.assertEqual(len(prepared), 2)
        self.assertEqual(stats.duplicates_removed, 1)
        self.assertTrue(prepared["timestamp"].is_monotonic_increasing)
        self.assertEqual(prepared.iloc[-1]["high"], 4)

    def test_validation_counts_missing_and_invalid_rows(self):
        raw = pd.DataFrame(
            [
                {"timestamp": "2025-01-01T00:00:00Z", "open": 2, "high": 3, "low": 1, "close": 2, "volume": 1},
                {"timestamp": "2025-01-01T00:30:00Z", "open": 2, "high": 1, "low": 2, "close": 2, "volume": 1},
            ]
        )
        prepared, _ = prepare_ohlcv(raw)
        report = validate_ohlcv(prepared)
        self.assertEqual(report.missing_candles, 1)
        self.assertEqual(report.invalid_ohlcv_rows, 1)

    def test_missing_ranges_are_grouped(self):
        existing, _ = prepare_ohlcv(
            pd.DataFrame(
                [
                    {"timestamp": "2025-01-01T00:00:00Z", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0},
                    {"timestamp": "2025-01-01T00:45:00Z", "open": 1, "high": 1, "low": 1, "close": 1, "volume": 0},
                ]
            )
        )
        ranges = find_missing_ranges(
            existing,
            pd.Timestamp("2025-01-01T00:00:00Z"),
            pd.Timestamp("2025-01-01T00:45:00Z"),
        )
        self.assertEqual(
            ranges,
            [(pd.Timestamp("2025-01-01T00:15:00Z"), pd.Timestamp("2025-01-01T00:30:00Z"))],
        )


if __name__ == "__main__":
    unittest.main()
