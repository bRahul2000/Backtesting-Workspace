import unittest
from unittest.mock import Mock

import pandas as pd

from services.bitstamp import BitstampClient


class BitstampClientTests(unittest.TestCase):
    def test_download_parses_and_filters_response(self):
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "data": {
                "ohlc": [
                    {"timestamp": "1735689600", "open": "1", "high": "2", "low": "1", "close": "2", "volume": "3"},
                    {"timestamp": "1735690500", "open": "2", "high": "3", "low": "2", "close": "3", "volume": "4"},
                ]
            }
        }
        session = Mock()
        session.headers = {}
        session.get.return_value = response
        client = BitstampClient(session=session)

        result = client.download_ohlc(
            pd.Timestamp("2025-01-01T00:00:00Z"),
            pd.Timestamp("2025-01-01T00:15:00Z"),
        )

        self.assertEqual(len(result), 2)
        self.assertIsNotNone(result["timestamp"].dt.tz)
        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["params"]["step"], 900)
        self.assertEqual(kwargs["params"]["exclude_current_candle"], "true")


if __name__ == "__main__":
    unittest.main()
