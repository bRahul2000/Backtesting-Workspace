"""Pinned BTC demo baseline from the audited NEXT_OPEN checkpoint."""
import unittest
from pathlib import Path

import pandas as pd

from engine.backtester import run_backtest
from engine.metrics import calculate_metrics
from engine.models import BacktestSettings, EntryModel, RiskCalculation
from strategies.demo_strategy import DemoEmaCrossover
from utils.data_validation import load_ohlcv_csv


class NextOpenRegressionTests(unittest.TestCase):
    def test_prior_38_trade_demo_baseline(self):
        root = Path(__file__).resolve().parents[1]
        data = load_ohlcv_csv(root / "data" / "btcusd_15m.csv")
        result = run_backtest(
            data, DemoEmaCrossover(),
            BacktestSettings(risk_calculation=RiskCalculation.PRICE_DISTANCE,
                             max_leverage=100),
            trade_start=pd.Timestamp("2026-08-17T00:00:00Z"),
            trade_end=pd.Timestamp("2026-09-16T23:45:00Z"),
        )
        metrics = calculate_metrics(result)
        self.assertEqual(metrics.total_trades, 38)
        self.assertAlmostEqual(metrics.net_pnl, 681.0033719778113, places=7)
        self.assertTrue(all(trade.entry_model is EntryModel.NEXT_OPEN
                            for trade in result.trades))
        self.assertEqual(result.order_events, [])
        self.assertEqual(result.trades[0].entry_price, 64358.7)
        self.assertEqual(result.trades[0].pnl, 200)


if __name__ == "__main__":
    unittest.main()
