import unittest

from engine.backtester import run_backtest
from engine.metrics import calculate_metrics
from engine.models import BacktestSettings, Direction, RiskCalculation, Signal
from tests.test_execution import ScheduledStrategy, candles


class RiskSizingTests(unittest.TestCase):
    def stopped_trade(self, direction, *, stop=None, **settings):
        stop = stop if stop is not None else (95 if direction is Direction.LONG else 105)
        exit_bar = ((100, 102, 94, 96) if direction is Direction.LONG
                    else (100, 106, 98, 104))
        result = run_backtest(
            candles((100, 101, 99, 100), exit_bar),
            ScheduledStrategy({0: Signal(direction, stop)}),
            BacktestSettings(**settings),
        )
        self.assertEqual(len(result.trades), 1)
        return result.trades[0]

    def assert_total_risk(self, trade, expected_quantity):
        self.assertAlmostEqual(trade.planned_risk, 100, places=9)
        self.assertAlmostEqual(trade.quantity, expected_quantity, places=9)
        self.assertAlmostEqual(trade.estimated_stop_loss, 100, places=9)
        self.assertAlmostEqual(trade.pnl, -100, places=9)
        self.assertAlmostEqual(trade.realized_r, -1, places=9)
        self.assertFalse(trade.leverage_capped)

    def test_long_total_loss_zero_costs(self):
        self.assert_total_risk(self.stopped_trade(Direction.LONG), 20)

    def test_short_total_loss_zero_costs(self):
        self.assert_total_risk(self.stopped_trade(Direction.SHORT), 20)

    def test_long_commission_sizing(self):
        trade = self.stopped_trade(Direction.LONG, commission_percent=1)
        self.assert_total_risk(trade, 100 / (5 + .01 * (100 + 95)))

    def test_short_commission_sizing(self):
        trade = self.stopped_trade(Direction.SHORT, commission_percent=1)
        self.assert_total_risk(trade, 100 / (5 + .01 * (100 + 105)))

    def test_long_slippage_sizing(self):
        trade = self.stopped_trade(Direction.LONG, slippage_percent=1)
        self.assertEqual(trade.entry_price, 101)
        self.assertAlmostEqual(trade.exit_price, 94.05)
        self.assert_total_risk(trade, 100 / (101 - 94.05))

    def test_short_slippage_sizing(self):
        trade = self.stopped_trade(Direction.SHORT, slippage_percent=1)
        self.assertEqual(trade.entry_price, 99)
        self.assertAlmostEqual(trade.exit_price, 106.05)
        self.assert_total_risk(trade, 100 / (106.05 - 99))

    def test_combined_costs_both_directions(self):
        for direction, per_unit in (
            (Direction.LONG, (101 - 94.05) + .01 * (101 + 94.05)),
            (Direction.SHORT, (106.05 - 99) + .01 * (99 + 106.05)),
        ):
            with self.subTest(direction=direction):
                trade = self.stopped_trade(direction, commission_percent=1,
                                           slippage_percent=1)
                self.assert_total_risk(trade, 100 / per_unit)

    def test_leverage_cap_reduces_quantity_and_estimated_loss(self):
        result = run_backtest(
            candles((100, 101, 99, 100), (100, 101, 99, 100)),
            ScheduledStrategy({0: Signal(Direction.LONG, 99.5)}),
        )
        trade = result.trades[0]
        self.assertEqual(trade.planned_risk, 100)
        self.assertEqual(trade.quantity, 100)
        self.assertEqual(trade.entry_price * trade.quantity, 10000)
        self.assertTrue(trade.leverage_capped)
        self.assertEqual(trade.estimated_stop_loss, 50)
        self.assertEqual(trade.pnl, -50)
        self.assertEqual(trade.realized_r, -.5)

    def test_higher_leverage_allows_uncapped_risk_size(self):
        result = run_backtest(
            candles((100, 101, 99, 100), (100, 101, 99, 100)),
            ScheduledStrategy({0: Signal(Direction.LONG, 99.5)}),
            BacktestSettings(max_leverage=2),
        )
        trade = result.trades[0]
        self.assertEqual(trade.quantity, 200)
        self.assertFalse(trade.leverage_capped)
        self.assertEqual(trade.estimated_stop_loss, 100)

    def test_minimum_quantity_rejection_has_reason(self):
        result = run_backtest(
            candles((100, 101, 99, 100), (100, 102, 98, 100)),
            ScheduledStrategy({0: Signal(Direction.LONG, 95)}),
            BacktestSettings(min_quantity=21),
        )
        self.assertFalse(result.trades)
        self.assertIsNone(result.open_position)
        self.assertTrue(any("below the configured minimum" in issue.message
                            for issue in result.issues))

    def test_minimum_quantity_applies_after_leverage_cap(self):
        result = run_backtest(
            candles((100, 101, 99, 100), (100, 101, 99, 100)),
            ScheduledStrategy({0: Signal(Direction.LONG, 99.5)}),
            BacktestSettings(min_quantity=101),
        )
        self.assertFalse(result.trades)
        self.assertTrue(any("below the configured minimum" in issue.message
                            for issue in result.issues))

    def test_price_distance_mode_preserves_legacy_sizing(self):
        for direction, per_unit in (
            (Direction.LONG, (101 - 94.05) + .01 * (101 + 94.05)),
            (Direction.SHORT, (106.05 - 99) + .01 * (99 + 106.05)),
        ):
            with self.subTest(direction=direction):
                trade = self.stopped_trade(
                    direction, commission_percent=1, slippage_percent=1,
                    risk_calculation=RiskCalculation.PRICE_DISTANCE,
                )
                self.assertAlmostEqual(trade.quantity, 100 / 6)
                self.assertAlmostEqual(trade.estimated_stop_loss,
                                       (100 / 6) * per_unit)
                self.assertLess(trade.pnl, -100)
                self.assertAlmostEqual(trade.realized_r,
                                       trade.pnl / trade.planned_risk)

    def test_realized_r_uses_planned_budget_after_cap(self):
        result = run_backtest(
            candles((100, 101, 99, 100), (100, 101, 99, 100)),
            ScheduledStrategy({0: Signal(Direction.LONG, 99.5)}),
        )
        self.assertEqual(result.trades[0].realized_r, -.5)
        self.assertEqual(calculate_metrics(result).average_realized_losing_r, -.5)

    def test_gap_loss_can_exceed_planned_and_estimated_risk(self):
        result = run_backtest(
            candles((100, 101, 99, 100), (100, 102, 98, 100),
                    (90, 92, 89, 91)),
            ScheduledStrategy({0: Signal(Direction.LONG, 95)}),
        )
        trade = result.trades[0]
        self.assertEqual(trade.estimated_stop_loss, 100)
        self.assertEqual(trade.planned_risk, 100)
        self.assertEqual(trade.exit_price, 90)
        self.assertEqual(trade.pnl, -200)
        self.assertEqual(trade.realized_r, -2)

    def test_invalid_limits_are_rejected(self):
        for settings in (BacktestSettings(max_leverage=0),
                         BacktestSettings(min_quantity=-1)):
            with self.subTest(settings=settings):
                with self.assertRaises(ValueError):
                    run_backtest(candles((100, 101, 99, 100)),
                                 ScheduledStrategy({}), settings)


if __name__ == "__main__":
    unittest.main()
