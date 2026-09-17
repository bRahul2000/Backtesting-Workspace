"""Segment eligibility, isolation, and trade-only aggregation fixtures."""
from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest

from engine.models import BacktestSettings, Direction, Signal
from research.segment_aware_baseline import (
    ObservedSetupB,
    aggregate_monthly, aggregate_yearly, local_drawdown_percent,
    run_independent_segment, segment_drawdown_statistics,
    segment_exclusion_reason, trade_statistics, warmup_plan,
)
from strategies.btc_v2_setup_b import BtcV2SetupB, SETUP_ID, SetupBParameters
from utils.data_validation import continuous_segments, load_ohlcv_csv


def candles(start, count, price=100):
    times = pd.date_range(start, periods=count, freq="15min")
    return pd.DataFrame({
        "timestamp": times, "open": [price] * count,
        "high": [price + 1] * count, "low": [price - 1] * count,
        "close": [price] * count, "volume": [1] * count,
    })


def trade(when, pnl, realized_r, direction=Direction.LONG):
    return SimpleNamespace(
        exit_time=pd.Timestamp(when), pnl=pnl, realized_r=realized_r,
        direction=direction, bars_held=2,
    )


def test_warmup_is_derived_from_frozen_lengths_and_partial_h1_start():
    params = SetupBParameters()
    aligned = warmup_plan(params, pd.Timestamp("2025-01-01T00:00:00Z"))
    partial = warmup_plan(params, pd.Timestamp("2025-01-01T00:15:00Z"))
    assert aligned.m15_bars == 50
    assert aligned.confirmed_h1_bars == 205
    assert aligned.warmup_candles == 820
    assert aligned.minimum_segment_candles == 821
    assert partial.warmup_candles == 823
    assert partial.minimum_segment_candles == 824


def test_short_segment_is_listed_with_calculated_exclusion_reason():
    plan = warmup_plan(SetupBParameters(), pd.Timestamp("2025-01-01T00:00:00Z"))
    reason = segment_exclusion_reason(820, plan)
    assert "820 candles" in reason and "821" in reason and "205 confirmed H1" in reason
    assert segment_exclusion_reason(821, plan) is None


def test_independent_runs_reset_m15_h1_and_daily_state_at_gap():
    strategy = BtcV2SetupB()
    settings = BacktestSettings()
    first = candles("2025-01-01T00:00:00Z", 8, 100)
    second = candles("2025-01-02T00:00:00Z", 4, 200)
    run_independent_segment(first, strategy, settings, first.timestamp.iloc[0])
    assert strategy.h1.confirmed.hour == pd.Timestamp("2025-01-01T00:00:00Z")
    assert strategy.fast.value == 100
    run_independent_segment(second, strategy, settings, second.timestamp.iloc[0])
    assert strategy.h1.confirmed.hour is None
    assert strategy.fast.value == 200
    assert strategy.risk.day_key == (2025, 1, 2)
    assert strategy.risk.trades_today == 0


def test_pending_and_open_position_end_at_segment_boundary_without_forced_exit():
    signal_time = pd.Timestamp("2025-01-01T10:00:00Z")

    class Forced(BtcV2SetupB):
        def on_candle(self, candle):
            super().on_candle(candle)
            if candle.timestamp == signal_time:
                return Signal.pending_stop(Direction.LONG, 105, 95, 2, SETUP_ID)
            return None

    first = candles("2025-01-01T10:00:00Z", 2)
    first.loc[1, ["high", "close"]] = [106, 104]
    second = candles("2025-01-02T10:00:00Z", 2)
    strategy = Forced()
    settings = BacktestSettings(risk_reward_ratio=3)
    a = run_independent_segment(first, strategy, settings, first.timestamp.iloc[0])
    assert a.open_position is not None
    assert a.trades == [] and a.final_balance == settings.starting_balance
    assert any("remains open" in issue.message for issue in a.issues)
    b = run_independent_segment(second, strategy, settings, second.timestamp.iloc[0])
    assert b.open_position is None and b.pending_order is None
    assert b.order_events == [] and b.final_balance == settings.starting_balance
    with pytest.raises(ValueError, match="exactly one continuous"):
        run_independent_segment(pd.concat([first, second]), strategy, settings,
                                first.timestamp.iloc[0])


def test_final_pending_order_is_cancelled_and_not_carried_to_next_segment():
    signal_time = pd.Timestamp("2025-01-01T10:00:00Z")

    class Forced(BtcV2SetupB):
        def on_candle(self, candle):
            super().on_candle(candle)
            if candle.timestamp == signal_time:
                return Signal.pending_stop(Direction.LONG, 105, 95, 2, SETUP_ID)
            return None

    strategy = Forced()
    settings = BacktestSettings()
    first = candles("2025-01-01T10:00:00Z", 1)
    second = candles("2025-01-02T10:00:00Z", 1)
    a = run_independent_segment(first, strategy, settings, first.timestamp.iloc[0])
    assert a.order_events[0].status == "cancelled"
    assert a.pending_order is None
    b = run_independent_segment(second, strategy, settings, second.timestamp.iloc[0])
    assert b.order_events == [] and b.pending_order is None


def test_account_balance_resets_after_profitable_segment():
    signal_time = pd.Timestamp("2025-01-01T10:00:00Z")

    class Forced(BtcV2SetupB):
        def on_candle(self, candle):
            super().on_candle(candle)
            if candle.timestamp == signal_time:
                return Signal.pending_stop(Direction.LONG, 105, 95, 2, SETUP_ID)
            return None

    first = candles("2025-01-01T10:00:00Z", 2)
    first.loc[1, ["high", "close"]] = [136, 110]
    second = candles("2025-01-02T10:00:00Z", 2)
    strategy = Forced()
    settings = BacktestSettings(risk_reward_ratio=3)
    profitable = run_independent_segment(first, strategy, settings,
                                          first.timestamp.iloc[0])
    fresh = run_independent_segment(second, strategy, settings,
                                    second.timestamp.iloc[0])
    assert len(profitable.trades) == 1 and profitable.final_balance > 10_000
    assert fresh.final_balance == 10_000 and fresh.trades == []


def test_regime_descriptors_are_captured_at_real_signal_time():
    root = Path(__file__).resolve().parents[1]
    data = load_ohlcv_csv(root / "data" / "btcusd_15m.csv")
    fragment = data.loc[data.timestamp.between(
        pd.Timestamp("2026-08-17T00:00:00Z"),
        pd.Timestamp("2026-08-17T23:45:00Z"),
    )].reset_index(drop=True)
    strategy = ObservedSetupB()
    result = run_independent_segment(
        fragment, strategy,
        BacktestSettings(risk_percent=.25, risk_reward_ratio=3,
                         commission_percent=.05),
        fragment.timestamp.iloc[0],
    )
    assert result.trades
    regime = strategy.signal_regimes[result.trades[0].signal_time]
    assert regime["h1_ema200_slope_magnitude"] == abs(regime["h1_ema200_slope"])
    assert regime["m15_atr_percent"] > 0
    assert regime["adx"] >= 18
    assert regime["confirmed_h1_hour"] < result.trades[0].signal_time.floor("h")


def test_pooled_pf_expectancy_and_segment_only_drawdown():
    trades = [
        trade("2025-01-01T01:00:00Z", 30, 3),
        trade("2025-01-01T02:00:00Z", -10, -1),
        trade("2025-01-02T01:00:00Z", -10, -1, Direction.SHORT),
    ]
    pooled = trade_statistics(trades)
    assert pooled["trades"] == 3
    assert pooled["profit_factor"] == 1.5
    assert pooled["expectancy_r"] == pytest.approx(1 / 3)
    assert pooled["net_pnl"] == 10
    assert "max_drawdown_percent" not in pooled  # No fake pooled equity curve.
    drawdowns = segment_drawdown_statistics([
        {"max_drawdown_percent": 2.0}, {"max_drawdown_percent": 4.0},
    ])
    assert drawdowns == {
        "worst_segment_drawdown_percent": 4.0,
        "median_segment_drawdown_percent": 3.0,
        "average_segment_drawdown_percent": 3.0,
    }


def test_annual_aggregation_counts_two_independent_segments():
    first = candles("2023-01-01T00:00:00Z", 3)
    second = candles("2023-01-02T00:00:00Z", 2)
    data = pd.concat([first, second], ignore_index=True)
    segments = continuous_segments(data)
    a = trade("2023-01-01T00:15:00Z", 10, 1)
    b = trade("2023-01-02T00:15:00Z", -5, -1, Direction.SHORT)
    results = [
        ("S01", segments[0], SimpleNamespace(first_search_time=segments[0].start),
         SimpleNamespace(trades=[a]), {}),
        ("S02", segments[1], SimpleNamespace(first_search_time=segments[1].start),
         SimpleNamespace(trades=[b]), {}),
    ]
    row = aggregate_yearly(data, results, [a, b], 10_000)[0]
    assert row["segments_represented"] == 2
    assert row["usable_candles"] == 5
    assert row["trades"] == 2 and row["net_pnl"] == 5
    assert row["worst_segment_drawdown_percent"] == pytest.approx(0.05)


def test_monthly_rows_mark_incomplete_source_and_no_trade_months():
    complete = candles("2025-01-01T00:00:00Z", 31 * 96)
    complete_row = aggregate_monthly(complete, [])[0]
    assert complete_row["incomplete_source_coverage"] is False
    assert complete_row["no_trade_month"] is True
    incomplete = complete.drop(index=10).reset_index(drop=True)
    incomplete_row = aggregate_monthly(incomplete, [])[0]
    assert incomplete_row["incomplete_source_coverage"] is True
    assert incomplete_row["source_candles"] == 31 * 96 - 1
