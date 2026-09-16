import unittest

import pandas as pd

from engine.backtester import run_backtest
from engine.manual_validation import run_known_example
from engine.models import BacktestSettings, Direction, RiskMode, Signal
from strategies.demo_strategy import DemoEmaCrossover, DemoParameters
from tests.test_execution import ScheduledStrategy, candles


def known_equity_sequence():
    """Five trades: +100, -100, +200, -300 via gap, +600."""
    data = candles(
        (100, 101, 99, 100), (100, 106, 99, 105),
        (100, 101, 99, 100), (100, 101, 94, 96),
        (100, 101, 99, 100), (100, 111, 99, 110),
        (100, 101, 99, 100), (100, 102, 98, 100),
        (85, 100, 84, 100), (100, 131, 99, 130),
    )
    signals = {
        0: Signal(Direction.LONG, 95, 105),
        2: Signal(Direction.LONG, 95, 110),
        4: Signal(Direction.LONG, 95, 110),
        6: Signal(Direction.LONG, 95, 110),
        8: Signal(Direction.LONG, 95, 130),
    }
    return run_backtest(data, ScheduledStrategy(signals), BacktestSettings(
        risk_mode=RiskMode.FIXED_DOLLARS, fixed_risk_dollars=100,
    ))


class BacktesterTests(unittest.TestCase):
    def test_percentage_risk_uses_current_balance(self):
        data = candles((100, 101, 99, 100), (100, 111, 99, 105),
                       (100, 101, 99, 100), (100, 102, 94, 96))
        result = run_backtest(data, ScheduledStrategy({0: Signal(Direction.LONG, 95),
                                                       2: Signal(Direction.LONG, 95)}))
        self.assertEqual([round(t.quantity, 4) for t in result.trades], [20, 20.4])
        self.assertAlmostEqual(result.trades[1].initial_risk, 102)
        self.assertAlmostEqual(result.final_balance, 10098)
        self.assertEqual([p.balance for p in result.equity_curve], [10000, 10200, 10098])

    def test_fixed_dollar_risk(self):
        result = run_backtest(candles((100, 101, 99, 100), (100, 111, 99, 105)),
                              ScheduledStrategy({0: Signal(Direction.LONG, 95)}),
                              BacktestSettings(risk_mode=RiskMode.FIXED_DOLLARS,
                                               fixed_risk_dollars=50))
        self.assertEqual(result.trades[0].quantity, 10)
        self.assertEqual(result.trades[0].initial_risk, 50)

    def test_drawdown_tracks_closed_trade_equity(self):
        data = candles((100, 101, 99, 100), (100, 111, 99, 105),
                       (100, 101, 99, 100), (100, 102, 94, 96))
        result = run_backtest(data, ScheduledStrategy({0: Signal(Direction.LONG, 95),
                                                       2: Signal(Direction.LONG, 95)}))
        self.assertEqual(result.equity_curve[-1].peak_equity, 10200)
        self.assertAlmostEqual(result.equity_curve[-1].drawdown_dollars, 102)
        self.assertAlmostEqual(result.equity_curve[-1].drawdown_percent, 1)

    def test_no_trade_dataset(self):
        result = run_backtest(candles((100, 101, 99, 100)), ScheduledStrategy({}))
        self.assertEqual(result.trades, [])
        self.assertEqual(result.final_balance, 10000)
        self.assertEqual(len(result.equity_curve), 1)

    def test_manual_known_sequence(self):
        result = run_known_example()
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.trades[0].quantity, 20)
        self.assertEqual(result.trades[0].pnl, 200)
        self.assertEqual(result.final_balance, 10200)

    def test_bad_candles_are_rejected(self):
        data = candles((100, 101, 99, 100), (100, 101, 99, 100))
        data.loc[1, "high"] = 90
        with self.assertRaisesRegex(ValueError, "invalid OHLCV"):
            run_backtest(data, ScheduledStrategy({}))

    def test_signal_while_position_open_is_reported(self):
        result = run_backtest(candles((100, 101, 99, 100), (100, 102, 99, 100),
                                      (100, 111, 99, 105)),
                              ScheduledStrategy({0: Signal(Direction.LONG, 95),
                                                 1: Signal(Direction.LONG, 95)}))
        self.assertEqual(len(result.trades), 1)
        self.assertTrue(any("position is open" in issue.message for issue in result.issues))

    def test_pending_signal_cannot_cross_missing_candles(self):
        data = candles((100, 101, 99, 100), (100, 111, 99, 105))
        data.loc[1, "timestamp"] += pd.Timedelta(minutes=15)
        result = run_backtest(data, ScheduledStrategy({0: Signal(Direction.LONG, 95)}))
        self.assertEqual(result.trades, [])
        self.assertTrue(any("cancelled" in issue.message for issue in result.issues))

    def test_open_position_across_gap_is_rejected(self):
        data = candles((100, 101, 99, 100), (100, 102, 99, 100),
                       (100, 111, 99, 105))
        data.loc[2, "timestamp"] += pd.Timedelta(minutes=15)
        with self.assertRaisesRegex(ValueError, "open position crosses missing candles"):
            run_backtest(data, ScheduledStrategy({0: Signal(Direction.LONG, 95)}))

    def test_peak_to_trough_drawdown_sequence(self):
        result = known_equity_sequence()
        self.assertEqual([round(p.balance) for p in result.equity_curve],
                         [10000, 10100, 10000, 10200, 9900, 10500])
        self.assertEqual([round(p.peak_equity) for p in result.equity_curve],
                         [10000, 10100, 10100, 10200, 10200, 10500])
        self.assertEqual([round(p.drawdown_dollars) for p in result.equity_curve],
                         [0, 0, 100, 0, 300, 0])
        self.assertAlmostEqual(result.equity_curve[2].drawdown_percent, 100 / 10100 * 100)
        self.assertAlmostEqual(result.equity_curve[4].drawdown_percent, 300 / 10200 * 100)

    def test_trading_window_uses_prior_candles_for_warmup_only(self):
        data = candles((10, 11, 9, 10), (10, 10, 8, 9), (9, 9, 7, 8),
                       (8, 10, 8, 9), (9, 11, 9, 10), (10, 11, 9, 10))
        start = data.timestamp.iloc[4]
        end = data.timestamp.iloc[5]
        result = run_backtest(data, DemoEmaCrossover(DemoParameters(2, 3, 2, 1.5)),
                              trade_start=start, trade_end=end)
        self.assertIsNotNone(result.open_position)
        self.assertEqual(result.open_position.entry_time, end)
        self.assertEqual(result.open_position.signal_time, end)
        self.assertFalse(result.trades)
        sliced = run_backtest(data.iloc[4:].reset_index(drop=True),
                              DemoEmaCrossover(DemoParameters(2, 3, 2, 1.5)))
        self.assertIsNone(sliced.open_position)

    def test_window_blocks_prestart_orders_and_postend_exits(self):
        data = candles((100, 101, 99, 100), (100, 101, 99, 100),
                       (100, 101, 99, 100), (100, 102, 99, 100),
                       (100, 111, 99, 105))
        result = run_backtest(data,
                              ScheduledStrategy({1: Signal(Direction.LONG, 95),
                                                 2: Signal(Direction.LONG, 95)}),
                              trade_start=data.timestamp.iloc[2],
                              trade_end=data.timestamp.iloc[3])
        self.assertEqual(result.trades, [])
        self.assertEqual(result.open_position.entry_time, data.timestamp.iloc[3])
        self.assertEqual(result.open_position.signal_time, data.timestamp.iloc[3])
        self.assertEqual(result.final_balance, 10000)

    def test_empty_window_is_rejected(self):
        data = candles((100, 101, 99, 100))
        with self.assertRaisesRegex(ValueError, "no candles"):
            run_backtest(data, ScheduledStrategy({}),
                         trade_start=pd.Timestamp("2025-02-01T00:00:00Z"))

    def test_final_window_signal_cannot_enter_after_end(self):
        data = candles((100, 101, 99, 100), (100, 101, 99, 100),
                       (100, 111, 99, 105))
        result = run_backtest(data,
                              ScheduledStrategy({1: Signal(Direction.LONG, 95)}),
                              trade_start=data.timestamp.iloc[1],
                              trade_end=data.timestamp.iloc[1])
        self.assertEqual(result.trades, [])
        self.assertIsNone(result.open_position)
        self.assertTrue(any("no next candle" in issue.message for issue in result.issues))

    def test_future_prices_after_window_cannot_affect_backtest(self):
        data = candles((100, 101, 99, 100), (100, 111, 99, 105),
                       (100, 101, 99, 100))
        end = data.timestamp.iloc[1]
        original = run_backtest(data, ScheduledStrategy({0: Signal(Direction.LONG, 95)}),
                                trade_end=end)
        data.loc[2, ["high", "low", "close"]] = [1, -100, -100]
        changed = run_backtest(data, ScheduledStrategy({0: Signal(Direction.LONG, 95)}),
                               trade_end=end)
        self.assertEqual(original.trades, changed.trades)
        self.assertEqual(original.final_balance, changed.final_balance)


if __name__ == "__main__":
    unittest.main()
