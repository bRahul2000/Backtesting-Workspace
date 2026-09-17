"""Pine V2.2.0 UTC permission references and cancellation fixtures."""
from types import SimpleNamespace

import pandas as pd
import pytest

from engine.backtester import run_backtest
from engine.models import Candle, Direction, ExecutionState, PendingOrder, Signal
from strategies.btc_v2_setup_b import BtcV2SetupB, SETUP_ID, SetupBParameters, SetupBRiskState


def bar(when, close=100):
    return Candle(pd.Timestamp(when), close, close + 1, close - 1, close, 1)


def state(balance=10_000, *, opened=False, pnl=None, pending=None):
    return ExecutionState(
        balance, pending, None,
        SimpleNamespace(direction=Direction.LONG) if opened else None,
        SimpleNamespace(pnl=pnl) if pnl is not None else None,
    )


def pending(when):
    t = pd.Timestamp(when)
    return PendingOrder(Direction.LONG, t, t, 105, 95,
                        t + pd.Timedelta(minutes=30), 0, 2, 1, 100, 100,
                        False, SETUP_ID)


def test_trade_count_counts_fills_and_resets_at_utc_day():
    p = SetupBParameters(max_trades_per_day=2)
    r = SetupBRiskState(p)
    r.advance(bar("2025-01-01T07:00:00Z"), 10_000, state(opened=True))
    assert r.trades_today == 1 and r.lock_reason is None
    r.advance(bar("2025-01-01T08:00:00Z"), 10_000, state(opened=True))
    assert r.trades_today == 2 and "trades" in r.lock_reason
    r.advance(bar("2025-01-02T00:00:00Z"), 10_000, state())
    assert r.trades_today == 0 and r.lock_reason is None


def test_daily_drawdown_is_from_start_of_day_not_intraday_peak():
    r = SetupBRiskState(SetupBParameters(maximum_daily_drawdown_percent=1))
    r.advance(bar("2025-01-01T00:00:00Z"), 10_000, state())
    r.advance(bar("2025-01-01T01:00:00Z"), 10_500, state())
    r.advance(bar("2025-01-01T02:00:00Z"), 9_901, state())
    assert not r.daily_equity_locked
    r.advance(bar("2025-01-01T03:00:00Z"), 9_900, state())
    assert r.daily_equity_locked
    r.advance(bar("2025-01-01T04:00:00Z"), 10_100, state())
    assert r.daily_equity_locked  # Pine lock is sticky until new UTC day.
    r.advance(bar("2025-01-02T00:00:00Z"), 10_100, state())
    assert not r.daily_equity_locked and r.day_start_equity == 10_100


def test_monthly_drawdown_is_from_month_open_and_resets_next_month():
    r = SetupBRiskState(SetupBParameters(maximum_monthly_drawdown_percent=6))
    r.advance(bar("2025-01-01T00:00:00Z"), 10_000, state())
    r.advance(bar("2025-01-20T00:00:00Z"), 11_000, state())
    r.advance(bar("2025-01-21T00:00:00Z"), 9_401, state())
    assert not r.monthly_locked
    r.advance(bar("2025-01-22T00:00:00Z"), 9_400, state())
    assert r.monthly_locked
    r.advance(bar("2025-02-01T00:00:00Z"), 9_400, state())
    assert not r.monthly_locked and r.month_start_equity == 9_400


def test_all_time_protection_uses_running_peak_and_does_not_reset():
    p = SetupBParameters(all_time_protection=True,
                         maximum_all_time_drawdown_percent=10)
    r = SetupBRiskState(p)
    r.advance(bar("2025-01-01T00:00:00Z"), 10_000, state())
    r.advance(bar("2025-01-02T00:00:00Z"), 11_000, state())
    r.advance(bar("2025-02-01T00:00:00Z"), 9_900, state())
    assert r.all_time_locked and r.all_time_peak_equity == 11_000
    r.advance(bar("2025-03-01T00:00:00Z"), 12_000, state())
    assert r.all_time_locked


def test_daily_loss_streak_counts_closed_losses_and_resets_on_profit_or_day():
    r = SetupBRiskState(SetupBParameters(maximum_daily_losing_streak=3))
    for hour in (7, 8):
        r.advance(bar(f"2025-01-01T{hour:02d}:00:00Z"), 10_000,
                  state(pnl=-10))
    assert r.consecutive_losses_today == 2
    r.advance(bar("2025-01-01T09:00:00Z"), 10_000, state(pnl=0))
    assert r.consecutive_losses_today == 2
    r.advance(bar("2025-01-01T10:00:00Z"), 10_000, state(pnl=-10))
    assert r.daily_streak_locked
    r.advance(bar("2025-01-02T00:00:00Z"), 10_000, state())
    assert not r.daily_streak_locked and r.consecutive_losses_today == 0
    r.advance(bar("2025-01-02T01:00:00Z"), 10_000, state(pnl=-10))
    r.advance(bar("2025-01-02T02:00:00Z"), 10_000, state(pnl=10))
    assert r.consecutive_losses_today == 0


def test_default_all_time_protection_is_off():
    r = SetupBRiskState(SetupBParameters())
    r.advance(bar("2025-01-01T00:00:00Z"), 10_000, state())
    r.advance(bar("2025-01-02T00:00:00Z"), 8_000, state())
    assert not r.all_time_locked


def test_nonpositive_reference_equity_does_not_divide_by_zero():
    r = SetupBRiskState(SetupBParameters(all_time_protection=True))
    r.advance(bar("2025-01-01T00:00:00Z"), 0, state(balance=0))
    r.advance(bar("2025-01-01T01:00:00Z"), -10, state(balance=-10))
    assert not r.daily_equity_locked
    assert not r.monthly_locked
    assert not r.all_time_locked


def test_session_end_cancels_pending_at_candle_close():
    s = BtcV2SetupB()
    s.on_execution_state(state(pending=pending("2025-01-01T19:45:00Z")))
    action = s.on_candle(bar("2025-01-01T20:00:00Z"))
    assert action.setup_id == SETUP_ID
    assert "session" in action.reason


def test_session_start_is_inclusive_and_end_is_exclusive():
    s = BtcV2SetupB()
    for timestamp, expected in (
        ("2025-01-01T06:45:00Z", 0),
        ("2025-01-01T07:00:00Z", 1),
        ("2025-01-01T19:45:00Z", 2),
        ("2025-01-01T20:00:00Z", 2),
    ):
        s.on_execution_state(state())
        s.on_candle(bar(timestamp))
        assert s.diagnostics["Eligible candles"] == expected


def test_disallowed_utc_day_cancels_pending():
    p = SetupBParameters(allowed_days=frozenset({0}))  # Monday only.
    s = BtcV2SetupB(p)
    s.on_execution_state(state(pending=pending("2025-01-07T19:45:00Z")))
    action = s.on_candle(bar("2025-01-07T19:45:00Z"))
    assert "day" in action.reason


def test_risk_lock_cancels_pending_without_closing_existing_position():
    p = SetupBParameters(maximum_daily_drawdown_percent=1)
    s = BtcV2SetupB(p)
    s.on_execution_state(state(pending=pending("2025-01-01T07:00:00Z")))
    s.on_candle(bar("2025-01-01T07:00:00Z"))
    s.on_execution_state(state(balance=9_900,
                               pending=pending("2025-01-01T07:00:00Z")))
    action = s.on_candle(bar("2025-01-01T07:15:00Z"))
    assert "drawdown" in action.reason


@pytest.mark.parametrize("lock_kind,expected", [
    ("trades", "trades"),
    ("streak", "closed-loss"),
    ("monthly", "Monthly equity"),
    ("all_time", "All-time equity"),
])
def test_pending_cancellation_identifies_each_risk_permission(lock_kind, expected):
    overrides = {
        "trades": {"max_trades_per_day": 1},
        "streak": {"maximum_daily_losing_streak": 1},
        "monthly": {"maximum_monthly_drawdown_percent": 6},
        "all_time": {"all_time_protection": True,
                     "maximum_all_time_drawdown_percent": 10},
    }
    s = BtcV2SetupB(SetupBParameters(**overrides[lock_kind]))
    s.on_execution_state(state())
    s.on_candle(bar("2025-01-01T07:00:00Z"))
    if lock_kind == "all_time":
        s.on_execution_state(state(balance=11_000))
        s.on_candle(bar("2025-01-02T07:00:00Z"))
        when, current = "2025-02-01T07:00:00Z", state(
            balance=9_900, pending=pending("2025-01-02T07:00:00Z"))
    elif lock_kind == "monthly":
        when, current = "2025-01-02T07:00:00Z", state(
            balance=9_400, pending=pending("2025-01-01T07:00:00Z"))
    else:
        when = "2025-01-01T07:15:00Z"
        current = state(pending=pending("2025-01-01T07:00:00Z"),
                        opened=lock_kind == "trades",
                        pnl=-10 if lock_kind == "streak" else None)
    s.on_execution_state(current)
    action = s.on_candle(bar(when))
    assert expected in action.reason
    assert action.setup_id == SETUP_ID


def test_open_position_is_marked_for_permission_but_not_force_closed():
    s = BtcV2SetupB(SetupBParameters(maximum_daily_drawdown_percent=1))
    s.on_execution_state(state())
    s.on_candle(bar("2025-01-01T07:00:00Z", 100))
    open_position = SimpleNamespace(direction=Direction.LONG, entry_price=100,
                                    quantity=50, entry_commission=0)
    s.on_execution_state(ExecutionState(10_000, None, open_position))
    assert s.on_candle(bar("2025-01-01T07:15:00Z", 98)) is None
    assert s.risk.daily_equity_locked
    assert s.execution_state.position is open_position


def test_end_of_backtest_cancels_unfilled_pending_order():
    s = BtcV2SetupB()
    s.on_execution_state(state(pending=pending("2025-01-01T19:45:00Z")))
    action = s.on_backtest_end(pending("2025-01-01T19:45:00Z"))
    assert action.setup_id == SETUP_ID
    assert "range ended" in action.reason


def test_final_candle_pending_signal_is_created_then_cancelled_at_range_end():
    class FinalSignal(BtcV2SetupB):
        def on_candle(self, candle):
            super().on_candle(candle)
            return Signal.pending_stop(Direction.LONG, 105, 95, 2, SETUP_ID)

    data = pd.DataFrame([{
        "timestamp": pd.Timestamp("2025-01-01T10:00:00Z"),
        "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1,
    }])
    result = run_backtest(data, FinalSignal())
    assert result.trades == []
    assert result.order_events[0].status == "cancelled"
    assert result.order_events[0].cancel_reason == "Backtest range ended."
