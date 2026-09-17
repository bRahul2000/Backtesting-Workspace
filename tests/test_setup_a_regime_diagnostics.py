"""Deterministic tests for read-only frozen Setup A diagnostics."""
from collections import deque

import pandas as pd
import pytest

from research.setup_a_regime_diagnostics import (
    assign_regime_bucket, causal_percentile, cost_by_year, direction_by_year,
    feed_sensitivity_by_year, regime_buckets, run_diagnostic_trades,
    year_comparison,
)
from research.setup_b_failure_diagnostics import excursion
from research.exness_native_validation import engine_frame
from services.exness_m15 import PROCESSED


def _candles(highs, lows):
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=len(highs), freq="15min", tz="UTC"),
        "open": [100.] * len(highs), "high": highs, "low": lows,
        "close": [100.] * len(highs), "volume": [1.] * len(highs),
    })


@pytest.mark.parametrize("direction,highs,lows,exit_price", [
    ("LONG", [105, 112, 110], [95, 97, 90], 90),
    ("SHORT", [105, 104, 110], [95, 88, 90], 110),
])
def test_setup_a_post_fill_mfe_mae(direction, highs, lows, exit_price):
    result = excursion(_candles(highs, lows), direction=direction,
                       entry_price=100, exit_price=exit_price,
                       stop_price=90 if direction == "LONG" else 110,
                       quantity=1, gap_fill=False)
    assert result["mfe_r"] == pytest.approx(1.2)
    assert result["mae_r"] == pytest.approx(1)
    assert result["bars_to_mfe"] == 2
    assert result["bars_to_mae"] == 3
    assert result["reached_1r"]
    assert not result["reached_1.5r"]


def _trades():
    return pd.DataFrame({
        "signal_year": [2024, 2024, 2025],
        "direction": ["LONG", "SHORT", "LONG"],
        "gross_pnl": [25., -25., -25.],
        "realized_r": [1., -1., -1.],
        "quantity": [1., 1., 1.],
        "planned_risk": [25., 25., 25.],
        "planned_stop_distance_atr": [1., 1.5, 2.],
        "atr_percent": [.3, .4, .5],
        "h1_directional_slope_percent": [.1, .2, .3],
        "recent_volatility_24h_percent": [2., 3., 4.],
        "directional_efficiency_24h": [.2, .3, .4],
        "mfe_r": [1.2, .2, .8], "mae_r": [.3, 1., 1.],
        "reached_0.5r": [True, False, True],
        "reached_1r": [True, False, False],
        "adx": [20., 25., 40.],
        "atr_percentile": [25., 50., 75.],
        "h1_slope_percentile": [30., 55., 80.],
        "ema_separation_atr": [.2, .4, .6],
        "pullback_depth_atr": [.1, .2, .3],
    })


def test_year_and_direction_aggregation():
    trades = _trades()
    activity = pd.DataFrame({
        "signal_year": [2024, 2024, 2024, 2025, 2025],
        "kind": ["signal", "signal", "order", "signal", "order"],
        "status": ["", "", "triggered", "", "expired"],
    })
    years = year_comparison(trades, activity)
    row = years.loc[years.year.eq(2024)].iloc[0]
    assert (row.signals, row.pending_orders, row.fills, row.completed_trades) == (2, 1, 1, 2)
    assert row.average_r == 0
    by_side = direction_by_year(trades)
    assert by_side.query('year == 2024 and direction == "LONG"').iloc[0].profit_factor == float("inf")
    assert by_side.query('year == 2025 and direction == "LONG"').iloc[0].average_r == -1


def test_regime_percentile_causal_and_bucket_boundaries():
    past = deque([1., 2., 3.])
    observed = causal_percentile(past, 2.)
    past.append(100.)
    assert observed == pytest.approx(100 / 3 * 2)
    assert causal_percentile(past, 2.) != observed
    assert list(assign_regime_bucket(pd.Series([18., 20., 40.]), "adx")) == [
        "18–20", "20–25", "40+",
    ]
    assert list(assign_regime_bucket(pd.Series([.6, 1., 3.]),
                                     "planned_stop_distance_atr")) == [
        "0.6–1", "1–1.5", "2.5–3",
    ]
    bucket = regime_buckets(_trades())
    assert bucket.low_sample.all()


def test_cost_and_feed_year_aggregation():
    cost = cost_by_year(_trades())
    zero = cost.query('year == 2024 and spread_usd_per_btc == 0').iloc[0]
    assert zero.trades == 2 and zero.net_pnl == 0
    costly = cost.query('year == 2024 and spread_usd_per_btc == 10').iloc[0]
    assert costly.net_pnl < zero.net_pnl
    matches = pd.DataFrame({
        "classification": ["EXACT MATCH", "NEAR MATCH", "EXNESS ONLY", "BITSTAMP ONLY"],
        "exness_signal_time": ["2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z",
                               "2025-01-01T00:00:00Z", None],
        "bitstamp_signal_time": ["2024-01-01T00:00:00Z", "2024-01-02T00:15:00Z",
                                 None, "2025-01-01T00:00:00Z"],
    })
    feed = feed_sensitivity_by_year(matches)
    y2024 = feed.loc[feed.year.eq(2024)].iloc[0]
    assert y2024.exact_match_rate_percent == 50
    assert y2024.exact_plus_near_rate_percent == 100
    y2025 = feed.loc[feed.year.eq(2025)].iloc[0]
    assert y2025.exness_only == 1 and y2025.bitstamp_only == 1


def test_signal_descriptors_unaffected_by_future_candle():
    raw = pd.read_csv(PROCESSED, parse_dates=["timestamp_utc"])
    prefix = raw.loc[raw.timestamp_utc.lt(pd.Timestamp("2023-11-22T00:00:00Z"))].copy()
    source = engine_frame(prefix, exness=True)
    before, _, _ = run_diagnostic_trades(source)
    assert len(before) > 0
    altered = source.copy()
    last = altered.index[-1]
    altered.loc[last, ["open", "high", "low", "close"]] = [50000., 51000., 49000., 50500.]
    after, _, _ = run_diagnostic_trades(altered)
    first = before.iloc[0]
    counterpart = after.loc[after.signal_time.eq(first.signal_time)].iloc[0]
    for field in ("atr_percentile", "h1_slope_percentile",
                  "recent_volatility_24h_percent", "rsi", "adx",
                  "confirmed_h1_close", "confirmed_h1_hour"):
        assert first[field] == counterpart[field]
    assert first.confirmed_h1_hour < first.signal_candle_time.floor("h")
