import unittest

import pandas as pd

from engine.backtester import run_backtest
from engine.models import BacktestSettings, Direction, RiskCalculation, SameBarResolution, Signal
from strategies.base import Strategy


def candles(*bars):
    return pd.DataFrame([
        {"timestamp": pd.Timestamp("2025-01-01T00:00:00Z") + pd.Timedelta(minutes=15 * i),
         "open": o, "high": h, "low": l, "close": c, "volume": 1}
        for i, (o, h, l, c) in enumerate(bars)
    ])


class ScheduledStrategy(Strategy):
    def __init__(self, signals):
        self.signals = signals
        self.reset()

    def reset(self):
        self.index = -1
        self.seen = []

    def on_candle(self, candle):
        self.index += 1
        self.seen.append(candle.timestamp)
        return self.signals.get(self.index)


class ExecutionTests(unittest.TestCase):
    def run_case(self, direction, stop, bars, **settings):
        return run_backtest(candles(*bars), ScheduledStrategy({0: Signal(direction, stop)}),
                            BacktestSettings(**settings))

    def test_long_take_profit(self):
        result = self.run_case(Direction.LONG, 95, [(100, 101, 99, 100), (100, 111, 99, 105)])
        self.assertEqual(result.trades[0].exit_price, 110)
        self.assertAlmostEqual(result.trades[0].pnl, 200)
        self.assertEqual(result.trades[0].bars_held, 1)
        self.assertEqual(result.trades[0].entry_time, result.trades[0].exit_time)

    def test_long_stop_loss(self):
        result = self.run_case(Direction.LONG, 95, [(100, 101, 99, 100), (100, 102, 94, 96)])
        self.assertEqual(result.trades[0].exit_price, 95)
        self.assertAlmostEqual(result.trades[0].pnl, -100)

    def test_short_take_profit(self):
        result = self.run_case(Direction.SHORT, 105, [(100, 101, 99, 100), (100, 101, 89, 95)])
        self.assertEqual(result.trades[0].exit_price, 90)
        self.assertAlmostEqual(result.trades[0].pnl, 200)

    def test_short_stop_loss(self):
        result = self.run_case(Direction.SHORT, 105, [(100, 101, 99, 100), (100, 106, 98, 104)])
        self.assertEqual(result.trades[0].exit_price, 105)
        self.assertAlmostEqual(result.trades[0].pnl, -100)

    def test_both_touched_long_defaults_to_stop(self):
        result = self.run_case(Direction.LONG, 95, [(100, 101, 99, 100), (100, 111, 94, 100)])
        self.assertAlmostEqual(result.trades[0].pnl, -100)
        self.assertIn("ambiguous", result.trades[0].exit_reason)

    def test_both_touched_short_defaults_to_stop(self):
        result = self.run_case(Direction.SHORT, 105, [(100, 101, 99, 100), (100, 106, 89, 100)])
        self.assertAlmostEqual(result.trades[0].pnl, -100)

    def test_tp_first_for_both_directions(self):
        for direction, stop in ((Direction.LONG, 95), (Direction.SHORT, 105)):
            with self.subTest(direction=direction):
                result = self.run_case(direction, stop,
                                       [(100, 101, 99, 100), (100, 111, 89, 100)],
                                       same_bar_resolution=SameBarResolution.TP_FIRST)
                self.assertAlmostEqual(result.trades[0].pnl, 200)

    def test_next_bar_open_and_no_lookahead(self):
        strategy = ScheduledStrategy({0: Signal(Direction.LONG, 95)})
        result = run_backtest(candles((100, 120, 90, 100), (102, 103, 100, 102),
                                      (102, 114, 101, 110)), strategy)
        position = result.open_position
        self.assertIsNotNone(position)
        self.assertEqual(position.signal_time, pd.Timestamp("2025-01-01T00:15:00Z"))
        self.assertEqual(position.entry_time, pd.Timestamp("2025-01-01T00:15:00Z"))
        self.assertEqual(position.entry_price, 102)
        self.assertEqual(position.take_profit, 116)
        self.assertEqual(result.trades, [])
        self.assertEqual(len(strategy.seen), 3)

    def test_commission_is_charged_on_both_sides(self):
        result = self.run_case(Direction.LONG, 95, [(100, 101, 99, 100), (100, 111, 99, 105)],
                               commission_percent=1,
                               risk_calculation=RiskCalculation.PRICE_DISTANCE)
        trade = result.trades[0]
        self.assertAlmostEqual(trade.entry_commission, 20)
        self.assertAlmostEqual(trade.exit_commission, 22)
        self.assertAlmostEqual(trade.pnl, 158)

    def test_slippage_worsens_entry_and_exit(self):
        result = self.run_case(Direction.LONG, 95, [(100, 101, 99, 100), (100, 114, 99, 110)],
                               slippage_percent=1,
                               risk_calculation=RiskCalculation.PRICE_DISTANCE)
        trade = result.trades[0]
        self.assertEqual(trade.entry_price, 101)
        self.assertEqual(trade.take_profit, 113)
        self.assertAlmostEqual(trade.quantity, 100 / 6)
        self.assertAlmostEqual(trade.exit_price, 111.87)
        self.assertAlmostEqual(trade.pnl, (111.87 - 101) * (100 / 6))

    def test_short_slippage_direction(self):
        result = self.run_case(Direction.SHORT, 105, [(100, 101, 99, 100), (100, 101, 87, 95)],
                               slippage_percent=1)
        trade = result.trades[0]
        self.assertEqual(trade.entry_price, 99)
        self.assertAlmostEqual(trade.exit_price, trade.take_profit * 1.01)

    def test_opening_gap_through_stop_fills_at_open(self):
        result = self.run_case(Direction.LONG, 95,
                               [(100, 101, 99, 100), (100, 102, 98, 100), (90, 92, 89, 91)])
        self.assertEqual(result.trades[0].exit_price, 90)
        self.assertAlmostEqual(result.trades[0].pnl, -200)

    def test_long_target_gap_fills_at_target(self):
        result = self.run_case(Direction.LONG, 95,
                               [(100, 101, 99, 100), (100, 102, 98, 100),
                                (120, 121, 119, 120)])
        self.assertEqual(result.trades[0].exit_price, 110)
        self.assertIn("opening gap", result.trades[0].exit_reason)
        self.assertEqual(result.trades[0].pnl, 200)

    def test_short_stop_gap_fills_at_open(self):
        result = self.run_case(Direction.SHORT, 105,
                               [(100, 101, 99, 100), (100, 102, 98, 100),
                                (110, 111, 109, 110)])
        self.assertEqual(result.trades[0].exit_price, 110)
        self.assertIn("opening gap", result.trades[0].exit_reason)
        self.assertEqual(result.trades[0].pnl, -200)

    def test_short_target_gap_fills_at_target(self):
        result = self.run_case(Direction.SHORT, 105,
                               [(100, 101, 99, 100), (100, 102, 98, 100),
                                (80, 81, 79, 80)])
        self.assertEqual(result.trades[0].exit_price, 90)
        self.assertIn("opening gap", result.trades[0].exit_reason)
        self.assertEqual(result.trades[0].pnl, 200)

    def test_opening_gap_takes_priority_over_intrabar_both_touch(self):
        long = self.run_case(Direction.LONG, 95,
                             [(100, 101, 99, 100), (100, 102, 98, 100),
                              (120, 121, 94, 100)])
        self.assertEqual(long.trades[0].exit_price, 110)
        short = self.run_case(Direction.SHORT, 105,
                              [(100, 101, 99, 100), (100, 102, 98, 100),
                               (80, 106, 79, 100)])
        self.assertEqual(short.trades[0].exit_price, 90)

    def test_short_risk_budget_and_two_r_profit(self):
        result = self.run_case(Direction.SHORT, 105,
                               [(100, 101, 99, 100), (100, 101, 89, 95)])
        trade = result.trades[0]
        self.assertEqual(trade.initial_risk, 100)
        self.assertEqual(trade.quantity, 20)
        self.assertEqual(trade.take_profit, 90)
        self.assertEqual(trade.pnl, 200)
        self.assertEqual(trade.r_multiple, 2)

    def test_stop_loss_costs_can_exceed_planned_risk(self):
        long = self.run_case(Direction.LONG, 95,
                             [(100, 101, 99, 100), (100, 102, 94, 96)],
                             slippage_percent=1, commission_percent=1,
                             risk_calculation=RiskCalculation.PRICE_DISTANCE).trades[0]
        self.assertEqual(long.entry_price, 101)
        self.assertEqual(long.stop_loss, 95)
        self.assertEqual(long.take_profit, 113)
        self.assertAlmostEqual(long.quantity, 100 / 6)
        self.assertAlmostEqual(long.exit_price, 94.05)
        expected_long = (94.05 - 101) * (100 / 6) - (101 + 94.05) * (100 / 6) * .01
        self.assertAlmostEqual(long.pnl, expected_long)
        self.assertLess(long.pnl, -100)

        short = self.run_case(Direction.SHORT, 105,
                              [(100, 101, 99, 100), (100, 106, 98, 104)],
                              slippage_percent=1, commission_percent=1,
                              risk_calculation=RiskCalculation.PRICE_DISTANCE).trades[0]
        self.assertEqual(short.entry_price, 99)
        self.assertEqual(short.stop_loss, 105)
        self.assertEqual(short.take_profit, 87)
        self.assertAlmostEqual(short.quantity, 100 / 6)
        self.assertAlmostEqual(short.exit_price, 106.05)
        expected_short = (99 - 106.05) * (100 / 6) - (99 + 106.05) * (100 / 6) * .01
        self.assertAlmostEqual(short.pnl, expected_short)
        self.assertLess(short.pnl, -100)

    def test_next_open_entry_ignores_next_candle_future_prices(self):
        first = (100, 101, 99, 100)
        a = self.run_case(Direction.LONG, 95, [first, (100, 102, 98, 101)])
        b = self.run_case(Direction.LONG, 95, [first, (100, 104, 96, 103)])
        self.assertEqual(a.open_position.entry_price, b.open_position.entry_price)
        self.assertEqual(a.open_position.quantity, b.open_position.quantity)
        self.assertEqual(a.open_position.take_profit, b.open_position.take_profit)

    def test_invalid_stop_is_reported(self):
        result = self.run_case(Direction.LONG, 100, [(100, 101, 99, 100), (100, 102, 98, 100)])
        self.assertFalse(result.trades)
        self.assertIsNone(result.open_position)
        self.assertTrue(any("rejected" in issue.message for issue in result.issues))

    def test_nan_stop_is_reported(self):
        result = self.run_case(Direction.SHORT, float("nan"), [(100, 101, 99, 100), (100, 102, 98, 100)])
        self.assertTrue(any("finite" in issue.message for issue in result.issues))

    def test_final_signal_is_reported(self):
        result = run_backtest(candles((100, 101, 99, 100)),
                              ScheduledStrategy({0: Signal(Direction.LONG, 95)}))
        self.assertEqual(len(result.trades), 0)
        self.assertIn("no next candle", result.issues[0].message)


if __name__ == "__main__":
    unittest.main()
