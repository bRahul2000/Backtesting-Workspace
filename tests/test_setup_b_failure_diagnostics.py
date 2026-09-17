"""Deterministic checks for read-only Phase 4C diagnostics."""
from pathlib import Path

import pandas as pd
import pytest

from research.setup_b_failure_diagnostics import (
    BASELINE_DIR, _signal_descriptors, analysis_set, breakeven_win_rate,
    bucket_analysis, bucket_label, classify_fill, decompose_costs, excursion,
    is_gap_fill, recover_quantity,
)
from utils.data_validation import load_ohlcv_csv


def bars(start, highs, lows):
    count = len(highs)
    return pd.DataFrame({
        "timestamp": pd.date_range(start, periods=count, freq="15min"),
        "open": [100.] * count, "high": highs, "low": lows,
        "close": [100.] * count, "volume": [1.] * count,
    })


def test_long_mfe_mae_price_dollars_r_bars_and_thresholds():
    candles = bars("2025-01-01T00:00:00Z", [105, 112, 115], [95, 97, 90])
    result = excursion(candles, direction="LONG", entry_price=100,
                       exit_price=90, stop_price=90, quantity=2,
                       gap_fill=False)
    assert result["mfe_price_distance"] == 12
    assert result["mae_price_distance"] == 10
    assert result["mfe_dollars"] == 24
    assert result["mae_dollars"] == 20
    assert result["mfe_r"] == pytest.approx(1.2)
    assert result["mae_r"] == pytest.approx(1)
    assert result["bars_to_mfe"] == 2
    assert result["bars_to_mae"] == 3
    assert result["reached_0.5r"] and result["reached_1r"]
    assert not result["reached_1.5r"]


def test_short_mfe_mae_and_bars_to_extremes():
    candles = bars("2025-01-01T00:00:00Z", [105, 104, 115], [95, 88, 90])
    result = excursion(candles, direction="SHORT", entry_price=100,
                       exit_price=110, stop_price=110, quantity=3,
                       gap_fill=False)
    assert result["mfe_price_distance"] == 12
    assert result["mae_price_distance"] == 10
    assert result["mfe_dollars"] == 36
    assert result["mae_dollars"] == 30
    assert result["mfe_r"] == pytest.approx(1.2)
    assert result["mae_r"] == pytest.approx(1)
    assert (result["bars_to_mfe"], result["bars_to_mae"]) == (2, 3)


def test_excursion_excludes_prefill_and_postexit_extremes():
    candles = bars("2025-01-01T00:00:00Z", [101, 200], [80, 90])
    result = excursion(candles, direction="LONG", entry_price=100,
                       exit_price=90, stop_price=90, quantity=1,
                       gap_fill=False)
    assert result["mfe_price_distance"] == 1  # Entry low and exit high are not proven held.
    assert result["mae_price_distance"] == 10
    assert not result["reached_0.25r"]
    gap = excursion(candles.iloc[:1], direction="LONG", entry_price=100,
                    exit_price=104, stop_price=90, quantity=1, gap_fill=True)
    assert gap["mfe_price_distance"] == 4  # Exit bar is censored even on an opening fill.


def test_cost_decomposition_reconciles_commission_slippage_and_net():
    # Long: raw 100 -> 110, 1% adverse slippage gives 101 -> 108.9.
    quantity = 2
    entry, exit_price = 101., 108.9
    commission = (entry + exit_price) * quantity * .01
    net = (exit_price - entry) * quantity - commission
    assert recover_quantity(net, "LONG", entry, exit_price, 1) == pytest.approx(2)
    costs = decompose_costs(
        direction="LONG", quantity=quantity, trigger=100, entry_open=99,
        entry_price=entry, exit_price=exit_price,
        commission_percent=1, slippage_percent=1, net_pnl=net,
    )
    assert costs["gross_price_movement_pnl"] == pytest.approx(20)
    assert costs["entry_commission_cost"] == pytest.approx(2.02)
    assert costs["exit_commission_cost"] == pytest.approx(2.178)
    assert costs["commission_cost"] == pytest.approx(4.198)
    assert costs["slippage_cost"] == pytest.approx(4.2)
    assert costs["gross_price_movement_pnl"] - costs["total_transaction_cost"] == pytest.approx(net)


def test_cost_decomposition_short_and_zero_slippage():
    # Short: raw 100 -> 90, 1% adverse slippage gives 99 -> 90.9.
    net = (99 - 90.9) * 2 - (99 + 90.9) * 2 * .01
    costs = decompose_costs(
        direction="SHORT", quantity=2, trigger=100, entry_open=101,
        entry_price=99, exit_price=90.9,
        commission_percent=1, slippage_percent=1, net_pnl=net,
    )
    assert costs["gross_price_movement_pnl"] == pytest.approx(20)
    assert costs["slippage_cost"] == pytest.approx(3.8)
    no_slip = decompose_costs(
        direction="LONG", quantity=1, trigger=100, entry_open=99,
        entry_price=100, exit_price=110,
        commission_percent=0, slippage_percent=0, net_pnl=10,
    )
    assert no_slip["slippage_cost"] == 0


def test_breakeven_win_rate():
    assert breakeven_win_rate(3, -1) == pytest.approx(25)
    assert breakeven_win_rate(2.5, -1) == pytest.approx(100 / 3.5)
    assert breakeven_win_rate(0, -1) is None


def test_bucket_boundaries_and_small_sample_flag():
    labels = ("18-20", "20-25", "25-30", "30-40", "40+")
    edges = (18, 20, 25, 30, 40, float("inf"))
    assert bucket_label(18, edges, labels) == "18-20"
    assert bucket_label(20, edges, labels) == "20-25"
    assert bucket_label(40, edges, labels) == "40+"
    assert bucket_label(17.99, edges, labels) == "Outside defined range"
    sample = pd.DataFrame({
        "direction": ["LONG", "SHORT"], "pnl": [10., -5.],
        "realized_r": [1., -1.], "adx": [18., 19.],
        "ema20_extension_atr": [.5, .7],
        "planned_stop_distance_atr": [1., 1.2],
        "range_atr": [1., 1.2], "body_percent": [60., 70.],
        "structure_breakout_distance_atr": [.1, .2],
        "atr_percent": [.5, .6], "h1_ema200_slope_percent": [-.1, .1],
    })
    row = bucket_analysis(sample).query(
        'descriptor == "ADX" and bucket == "18-20" and direction == "All"'
    ).iloc[0]
    assert row.trades == 2 and row.small_sample


def test_fill_and_gap_classification():
    signal = pd.Timestamp("2025-01-01T00:15:00Z")
    assert classify_fill(signal, signal) == "B+1"
    assert classify_fill(signal, signal + pd.Timedelta(minutes=15)) == "B+2"
    with pytest.raises(ValueError, match="outside"):
        classify_fill(signal, signal + pd.Timedelta(minutes=30))
    assert is_gap_fill("LONG", 101, 100)
    assert not is_gap_fill("LONG", 100, 100)
    assert is_gap_fill("SHORT", 99, 100)
    assert not is_gap_fill("SHORT", 100, 100)


def test_development_and_forward_validation_tagging():
    assert analysis_set(pd.Timestamp("2024-12-31T23:45:00Z")) == "Development (2021–2024)"
    assert analysis_set(pd.Timestamp("2025-01-01T00:00:00Z")) == "Forward-validation (2025–2026)"
    with pytest.raises(ValueError, match="UTC-aware"):
        analysis_set(pd.Timestamp("2025-01-01"))


def test_signal_descriptors_do_not_change_when_future_candle_changes():
    root = Path(__file__).resolve().parents[1]
    data = load_ohlcv_csv(root / "data" / "btcusd_15m.csv")
    source = pd.read_csv(BASELINE_DIR / "pooled_trades.csv").iloc[[0]].copy()
    source["signal_time"] = pd.to_datetime(source.signal_time, utc=True)
    source["signal_candle_time"] = source.signal_time - pd.Timedelta(minutes=15)
    start = pd.Timestamp("2021-01-01T00:00:00Z")
    end = source.signal_candle_time.iloc[0] + pd.Timedelta(minutes=15)
    original = data.loc[data.timestamp.between(start, end)].copy()
    altered = original.copy()
    last = altered.index[-1]
    altered.loc[last, ["open", "high", "low", "close"]] = [50_000., 51_000., 49_000., 50_500.]
    segments = pd.DataFrame([{"segment_id": "S01", "start": start, "end": end}])
    before = _signal_descriptors(original, segments, source)
    after = _signal_descriptors(altered, segments, source)
    assert before == after
    observed = next(iter(before.values()))
    assert observed["confirmed_h1_hour"] < observed["signal_candle_time"].floor("h")
