import math
import unittest
from dataclasses import replace

from engine.backtester import run_backtest
from engine.metrics import calculate_metrics
from engine.models import BacktestSettings, Direction, RiskMode, Signal
from tests.test_backtester import known_equity_sequence
from tests.test_execution import ScheduledStrategy, candles


class MetricsTests(unittest.TestCase):
    def test_profit_factor_and_expectancy(self):
        result = run_backtest(
            candles((100, 101, 99, 100), (100, 111, 99, 105),
                    (100, 101, 99, 100), (100, 102, 94, 96)),
            ScheduledStrategy({0: Signal(Direction.LONG, 95),
                               2: Signal(Direction.LONG, 95)}),
        )
        m = calculate_metrics(result)
        self.assertEqual(m.total_trades, 2)
        self.assertEqual((m.winning_trades, m.losing_trades, m.breakeven_trades), (1, 1, 0))
        self.assertEqual(m.win_rate_percent, 50)
        self.assertAlmostEqual(m.gross_profit, 200)
        self.assertAlmostEqual(m.gross_loss, -102)
        self.assertAlmostEqual(m.net_pnl, 98)
        self.assertAlmostEqual(m.profit_factor, 200 / 102)
        self.assertAlmostEqual(m.expectancy_dollars, 49)
        self.assertAlmostEqual(m.expectancy_r, 0.5)
        self.assertAlmostEqual(m.max_drawdown_percent, 1)
        self.assertEqual(m.final_balance, 10098)

    def test_consecutive_wins_and_losses(self):
        result = run_backtest(
            candles((100, 101, 99, 100), (100, 111, 99, 105),
                    (100, 111, 99, 105), (100, 102, 94, 96),
                    (100, 102, 94, 96)),
            ScheduledStrategy({i: Signal(Direction.LONG, 95) for i in range(4)}),
        )
        m = calculate_metrics(result)
        self.assertEqual(m.total_trades, 4)
        self.assertEqual(m.max_consecutive_wins, 2)
        self.assertEqual(m.max_consecutive_losses, 2)

    def test_no_losses_and_no_trades_are_safe(self):
        win = calculate_metrics(run_backtest(
            candles((100, 101, 99, 100), (100, 111, 99, 105)),
            ScheduledStrategy({0: Signal(Direction.LONG, 95)})))
        self.assertTrue(math.isinf(win.profit_factor))
        empty = calculate_metrics(run_backtest(
            candles((100, 101, 99, 100)), ScheduledStrategy({})))
        self.assertEqual(empty.total_trades, 0)
        self.assertIsNone(empty.profit_factor)
        self.assertEqual(empty.max_drawdown_percent, 0)
        self.assertEqual(empty.average_bars_held, 0)

    def test_every_reported_metric_on_known_equity_sequence(self):
        result = known_equity_sequence()
        m = calculate_metrics(result)
        self.assertEqual((m.total_trades, m.winning_trades, m.losing_trades,
                          m.breakeven_trades), (5, 3, 2, 0))
        self.assertEqual(m.win_rate_percent, 60)
        self.assertEqual(m.gross_profit, 900)
        self.assertEqual(m.gross_loss, -400)
        self.assertEqual(m.net_pnl, 500)
        self.assertEqual(m.profit_factor, 2.25)
        self.assertEqual(m.average_trade, 100)
        self.assertEqual(m.average_winner, 300)
        self.assertEqual(m.average_loser, -200)
        self.assertEqual(m.largest_winner, 600)
        self.assertEqual(m.largest_loser, -300)
        self.assertEqual(m.average_r_multiple, 1)
        self.assertEqual(m.expectancy_dollars, 100)
        self.assertEqual(m.expectancy_r, 1)
        self.assertEqual(m.max_drawdown_dollars, 300)
        self.assertAlmostEqual(m.max_drawdown_percent, 300 / 10200 * 100)
        self.assertEqual(m.max_consecutive_wins, 1)
        self.assertEqual(m.max_consecutive_losses, 1)
        self.assertEqual(m.average_bars_held, 1.2)
        self.assertEqual(m.total_return_percent, 5)
        self.assertEqual(m.final_balance, 10500)
        self.assertEqual(m.average_planned_risk, 100)
        self.assertEqual(m.average_realized_losing_r, -2)
        self.assertEqual(m.largest_losing_r, -3)

    def test_all_losers_and_only_breakeven_cases(self):
        losers = run_backtest(
            candles((100, 101, 99, 100), (100, 101, 94, 96),
                    (100, 101, 99, 100), (100, 101, 94, 96)),
            ScheduledStrategy({0: Signal(Direction.LONG, 95),
                               2: Signal(Direction.LONG, 95)}),
            BacktestSettings(risk_mode=RiskMode.FIXED_DOLLARS, fixed_risk_dollars=100),
        )
        loss_metrics = calculate_metrics(losers)
        self.assertEqual(loss_metrics.gross_profit, 0)
        self.assertEqual(loss_metrics.profit_factor, 0)
        self.assertEqual(loss_metrics.win_rate_percent, 0)
        self.assertEqual(loss_metrics.final_balance, 9800)

        base = known_equity_sequence()
        flat_point = replace(base.equity_curve[1], balance=10000,
                             peak_equity=10000, drawdown_dollars=0,
                             drawdown_percent=0)
        flat = replace(base, trades=[replace(base.trades[0], pnl=0, r_multiple=0)],
                       equity_curve=[base.equity_curve[0], flat_point])
        flat_metrics = calculate_metrics(flat)
        self.assertEqual(flat_metrics.breakeven_trades, 1)
        self.assertEqual(flat_metrics.gross_profit, 0)
        self.assertEqual(flat_metrics.gross_loss, 0)
        self.assertIsNone(flat_metrics.profit_factor)
        self.assertEqual(flat_metrics.expectancy_dollars, 0)
        self.assertEqual(flat_metrics.final_balance, 10000)
        self.assertEqual(flat_metrics.average_realized_losing_r, 0)
        self.assertEqual(flat_metrics.largest_losing_r, 0)


if __name__ == "__main__":
    unittest.main()
