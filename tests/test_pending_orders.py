import unittest

import pandas as pd

from engine.backtester import run_backtest
from engine.models import (
    BacktestSettings, CancelPendingOrder, Direction, EntryModel,
    SameBarResolution, Signal,
)
from tests.test_execution import ScheduledStrategy, candles


class PendingOrderTests(unittest.TestCase):
    def run_order(self, direction, trigger, stop, bars, *, expiry=2,
                  actions=None, **settings):
        planned = Signal.pending_stop(direction, trigger, stop, expiry, "TEST_SETUP")
        scheduled = {0: planned}
        if actions:
            scheduled.update(actions)
        return run_backtest(candles(*bars), ScheduledStrategy(scheduled),
                            BacktestSettings(**settings))

    def test_long_normal_trigger_fill(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 106, 100, 105),
                                 (105, 126, 104, 120)])
        trade = result.trades[0]
        self.assertEqual(trade.entry_model, EntryModel.STOP_ENTRY_PENDING)
        self.assertEqual(trade.entry_price, 105)
        self.assertEqual(trade.take_profit, 125)
        self.assertEqual(trade.exit_price, 125)
        self.assertEqual(trade.quantity, 10)
        self.assertEqual(trade.pnl, 200)
        self.assertEqual(trade.setup_id, "TEST_SETUP")
        self.assertFalse(trade.gap_through_trigger)
        self.assertEqual(trade.entry_gap_amount, 0)
        self.assertEqual(result.order_events[0].status, "triggered")

    def test_short_normal_trigger_fill(self):
        result = self.run_order(Direction.SHORT, 95, 105,
                                [(100, 101, 99, 100), (100, 100, 94, 95),
                                 (95, 96, 74, 80)])
        trade = result.trades[0]
        self.assertEqual(trade.entry_price, 95)
        self.assertEqual(trade.take_profit, 75)
        self.assertEqual(trade.exit_price, 75)
        self.assertEqual(trade.quantity, 10)
        self.assertEqual(trade.pnl, 200)

    def test_long_gap_through_trigger_uses_open_then_slippage(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (108, 110, 107, 109)],
                                slippage_percent=1)
        position = result.open_position
        self.assertIsNotNone(position)
        self.assertAlmostEqual(position.entry_price, 108 * 1.01)
        self.assertAlmostEqual(position.quantity, 100 / ((105 * 1.01) - (95 * .99)))
        self.assertTrue(position.gap_through_trigger)
        self.assertEqual(position.entry_gap_amount, 3)
        self.assertAlmostEqual(position.take_profit,
                               position.entry_price + 2 * (position.entry_price - 95))

    def test_short_gap_through_trigger_uses_open_then_slippage(self):
        result = self.run_order(Direction.SHORT, 95, 105,
                                [(100, 101, 99, 100), (92, 93, 90, 91)],
                                slippage_percent=1)
        position = result.open_position
        self.assertIsNotNone(position)
        self.assertAlmostEqual(position.entry_price, 92 * .99)
        self.assertTrue(position.gap_through_trigger)
        self.assertEqual(position.entry_gap_amount, 3)
        self.assertAlmostEqual(position.take_profit,
                               position.entry_price - 2 * (105 - position.entry_price))

    def test_never_fills_on_signal_candle(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 110, 99, 100), (100, 104, 99, 100),
                                 (100, 104, 99, 100)], expiry=2)
        self.assertEqual(result.trades, [])
        self.assertIsNone(result.open_position)
        self.assertEqual(result.order_events[0].status, "expired")

    def test_two_bar_expiry_allows_b_plus_one(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 106, 100, 105)],
                                expiry=2)
        self.assertEqual(result.open_position.entry_time,
                         pd.Timestamp("2025-01-01T00:15:00Z"))
        self.assertEqual(result.order_events[0].status, "triggered")

    def test_two_bar_expiry_allows_b_plus_two(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 104, 99, 100),
                                 (100, 106, 100, 105)], expiry=2)
        self.assertEqual(result.open_position.entry_time,
                         pd.Timestamp("2025-01-01T00:30:00Z"))
        self.assertEqual(result.order_events[0].status, "triggered")
        self.assertEqual(result.open_position.pending_expiry_bar_index, 2)
        self.assertEqual(result.open_position.pending_expiry_time,
                         pd.Timestamp("2025-01-01T00:30:00Z"))

    def test_two_bar_expiry_unavailable_on_b_plus_three(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 104, 99, 100),
                                 (100, 104, 99, 100), (100, 106, 100, 105)],
                                expiry=2)
        self.assertEqual(result.trades, [])
        self.assertIsNone(result.open_position)
        self.assertEqual(result.order_events[0].status, "expired")
        self.assertEqual(result.order_events[0].expiry_bar_index, 2)
        self.assertEqual(result.order_events[0].expiry_time,
                         pd.Timestamp("2025-01-01T00:30:00Z"))

    def test_manual_cancellation_prevents_later_fill(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 104, 99, 100),
                                 (100, 106, 100, 105)], expiry=3,
                                actions={1: CancelPendingOrder("Session ended", "TEST_SETUP")})
        self.assertEqual(result.trades, [])
        self.assertEqual(result.order_events[0].status, "cancelled")
        self.assertEqual(result.order_events[0].cancel_reason, "Session ended")

    def test_cancellation_with_wrong_setup_id_does_not_cancel(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 104, 99, 100),
                                 (100, 106, 100, 105)], expiry=3,
                                actions={1: CancelPendingOrder("Wrong", "OTHER")})
        self.assertEqual(result.order_events[0].status, "triggered")
        self.assertTrue(any("did not match" in issue.message for issue in result.issues))

    def test_long_same_bar_stop(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 106, 94, 100)])
        self.assertEqual(result.trades[0].exit_price, 95)
        self.assertEqual(result.trades[0].pnl, -100)
        self.assertEqual(result.trades[0].bars_held, 1)

    def test_long_same_bar_target(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 126, 100, 120)])
        self.assertEqual(result.trades[0].exit_price, 125)
        self.assertEqual(result.trades[0].pnl, 200)

    def test_long_same_bar_both_sl_first(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 126, 94, 100)])
        self.assertEqual(result.trades[0].exit_price, 95)
        self.assertIn("SL First", result.trades[0].exit_reason)

    def test_long_same_bar_both_tp_first(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 126, 94, 100)],
                                same_bar_resolution=SameBarResolution.TP_FIRST)
        self.assertEqual(result.trades[0].exit_price, 125)
        self.assertIn("TP First", result.trades[0].exit_reason)

    def test_short_same_bar_stop(self):
        result = self.run_order(Direction.SHORT, 95, 105,
                                [(100, 101, 99, 100), (100, 106, 94, 100)])
        self.assertEqual(result.trades[0].exit_price, 105)
        self.assertEqual(result.trades[0].pnl, -100)

    def test_short_same_bar_target(self):
        result = self.run_order(Direction.SHORT, 95, 105,
                                [(100, 101, 99, 100), (100, 100, 74, 80)])
        self.assertEqual(result.trades[0].exit_price, 75)
        self.assertEqual(result.trades[0].pnl, 200)

    def test_short_same_bar_both_sl_first(self):
        result = self.run_order(Direction.SHORT, 95, 105,
                                [(100, 101, 99, 100), (100, 106, 74, 100)])
        self.assertEqual(result.trades[0].exit_price, 105)
        self.assertIn("SL First", result.trades[0].exit_reason)

    def test_short_same_bar_both_tp_first(self):
        result = self.run_order(Direction.SHORT, 95, 105,
                                [(100, 101, 99, 100), (100, 106, 74, 100)],
                                same_bar_resolution=SameBarResolution.TP_FIRST)
        self.assertEqual(result.trades[0].exit_price, 75)
        self.assertIn("TP First", result.trades[0].exit_reason)

    def test_pre_entry_low_is_conservatively_counted_as_stop(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (90, 106, 89, 100)])
        self.assertEqual(result.trades[0].entry_price, 105)
        self.assertEqual(result.trades[0].exit_price, 95)
        self.assertNotIn("opening gap", result.trades[0].exit_reason)

    def test_pre_entry_high_is_conservatively_counted_as_short_stop(self):
        result = self.run_order(Direction.SHORT, 95, 105,
                                [(100, 101, 99, 100), (110, 111, 94, 100)])
        self.assertEqual(result.trades[0].entry_price, 95)
        self.assertEqual(result.trades[0].exit_price, 105)
        self.assertNotIn("opening gap", result.trades[0].exit_reason)

    def test_quantity_fixed_before_long_gap_and_risk_can_exceed_budget(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (115, 116, 114, 115),
                                 (115, 116, 94, 100)])
        trade = result.trades[0]
        self.assertEqual(trade.quantity, 10)
        self.assertEqual(trade.entry_price, 115)
        self.assertEqual(trade.take_profit, 155)
        self.assertEqual(trade.planned_risk, 100)
        self.assertEqual(trade.estimated_stop_loss, 100)
        self.assertEqual(trade.pnl, -200)
        self.assertEqual(trade.realized_r, -2)

    def test_quantity_fixed_before_short_gap_and_target_recalculated(self):
        result = self.run_order(Direction.SHORT, 95, 105,
                                [(100, 101, 99, 100), (85, 86, 84, 85)])
        position = result.open_position
        self.assertEqual(position.quantity, 10)
        self.assertEqual(position.entry_price, 85)
        self.assertEqual(position.take_profit, 45)
        self.assertTrue(position.gap_through_trigger)

    def test_pending_quantity_uses_creation_equity_and_costs(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 104, 99, 100)],
                                commission_percent=1, slippage_percent=1)
        order = result.pending_order
        self.assertIsNotNone(order)
        planned_entry = 105 * 1.01
        stop_exit = 95 * .99
        per_unit = planned_entry - stop_exit + .01 * (planned_entry + stop_exit)
        self.assertAlmostEqual(order.quantity, 100 / per_unit)
        self.assertAlmostEqual(order.estimated_stop_loss, 100)
        self.assertEqual(order.setup_id, "TEST_SETUP")

    def test_pending_leverage_cap_and_minimum_quantity(self):
        capped = self.run_order(Direction.LONG, 105, 104.5,
                                [(100, 101, 99, 100), (106, 107, 105, 106)],
                                max_leverage=1)
        self.assertTrue(capped.open_position.leverage_capped)
        self.assertAlmostEqual(capped.open_position.quantity, 10000 / 105)
        rejected = self.run_order(Direction.LONG, 105, 104.5,
                                  [(100, 101, 99, 100), (106, 107, 105, 106)],
                                  min_quantity=200)
        self.assertEqual(rejected.trades, [])
        self.assertTrue(any("below the configured minimum" in issue.message
                            for issue in rejected.issues))

    def test_invalid_pending_trigger_is_reported(self):
        result = self.run_order(Direction.LONG, 99, 95,
                                [(100, 101, 99, 100), (100, 106, 99, 105)])
        self.assertEqual(result.trades, [])
        self.assertTrue(any("trigger must be above" in issue.message
                            for issue in result.issues))

    def test_pending_expiry_must_be_positive_integer(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 106, 99, 105)],
                                expiry=0)
        self.assertEqual(result.trades, [])
        self.assertTrue(any("positive integer" in issue.message
                            for issue in result.issues))

    def test_stop_only_signal_works_without_duplicate_stop_loss_field(self):
        signal = Signal(direction=Direction.LONG,
                        entry_model=EntryModel.STOP_ENTRY_PENDING,
                        pending_entry_price=105, pending_stop_price=95,
                        pending_expiry_bars=2, setup_id="ONLY_PENDING_FIELDS")
        result = run_backtest(
            candles((100, 101, 99, 100), (100, 106, 100, 105)),
            ScheduledStrategy({0: signal}),
        )
        self.assertEqual(result.open_position.setup_id, "ONLY_PENDING_FIELDS")

    def test_unfilled_order_at_dataset_end_is_diagnostic_not_trade(self):
        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 104, 99, 100)],
                                expiry=3)
        self.assertEqual(result.trades, [])
        self.assertIsNotNone(result.pending_order)
        self.assertEqual(result.order_events[0].status, "active_at_end")

    def test_invalid_actual_target_cancels_without_trade(self):
        result = self.run_order(Direction.SHORT, 95, 105,
                                [(100, 101, 99, 100), (90, 91, 89, 90)],
                                risk_reward_ratio=6)
        self.assertEqual(result.trades, [])
        self.assertIsNone(result.open_position)
        self.assertEqual(result.order_events[0].status, "cancelled")
        self.assertIn("invalid take profit", result.order_events[0].cancel_reason)

    def test_order_and_trade_tables_keep_existing_columns(self):
        from ui.backtest_dashboard import order_events_table, trades_table

        result = self.run_order(Direction.LONG, 105, 95,
                                [(100, 101, 99, 100), (100, 106, 100, 105),
                                 (105, 126, 104, 120)])
        trades = trades_table(result)
        events = order_events_table(result)
        for column in ("Trade ID", "Risk $", "Net PnL $", "R Multiple", "Bars Held"):
            self.assertIn(column, trades.columns)
        for column in ("Entry Model", "Pending Trigger Price", "Pending Created Time",
                       "Actual Fill Price", "Gap Through Trigger", "Setup / Strategy ID"):
            self.assertIn(column, trades.columns)
        self.assertEqual(trades.loc[0, "Entry Model"], "STOP_ENTRY_PENDING")
        self.assertEqual(events.loc[0, "Status"], "triggered")
        self.assertEqual(events.loc[0, "Pending Created Time"], result.trades[0].signal_time)


if __name__ == "__main__":
    unittest.main()
