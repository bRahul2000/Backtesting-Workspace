"""Deterministic MT5 M15, feed-alignment, and frozen-strategy research tests."""
import csv

import pandas as pd
import pytest

from research.exness_native_validation import (
    engine_frame, price_cost_view, run_independent_feed, signal_matches,
)
from services.exness_m15 import (
    PROCESSED, align_price_feeds, parse_mt5_m15, validate_tick_overlap,
)


HEADER = ("<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>",
          "<TICKVOL>", "<VOL>", "<SPREAD>")


def _m15_file(path):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerow(["2026.08.01", "12:00:00", 100, 110, 99, 105, 3, 0, 1000])
        writer.writerow(["2026.08.01", "12:30:00", 105, 112, 104, 111, 2, 0, 1200])
    return path


def test_mt5_parser_utc_spread_points_and_gaps(tmp_path):
    bars, audit = parse_mt5_m15(_m15_file(tmp_path / "m15.csv"))
    assert list(bars.columns) == ["timestamp_utc", "open", "high", "low", "close",
                                  "tick_volume", "real_volume", "spread_points", "spread_price"]
    assert bars.timestamp_utc.iloc[0] == pd.Timestamp("2026-08-01 12:00", tz="UTC")
    assert bars.spread_price.tolist() == [10., 12.]
    assert audit["raw_rows"] == 2
    assert audit["expected_intervals"] == 3
    assert audit["missing_intervals"] == 1
    assert audit["gap_count"] == 1


def test_tick_bid_ohlc_and_minimum_spread_match(tmp_path):
    bars, _ = parse_mt5_m15(_m15_file(tmp_path / "m15.csv"))
    bid = tmp_path / "btcusdm_s01_bid_15m_server_time.csv"
    pd.DataFrame([{"timestamp_server": "2026-08-01T12:00:00", "open": 100,
                   "high": 110, "low": 99, "close": 105}]).to_csv(bid, index=False)
    pd.DataFrame([{"timestamp_server": "2026-08-01T12:00:00", "spread_price": 10},
                  {"timestamp_server": "2026-08-01T12:00:01", "spread_price": 11}]).to_csv(
                      tmp_path / "btcusdm_s01_ticks_server_time.csv", index=False)
    summary, details = validate_tick_overlap(bars, tmp_path)
    assert summary["overlapping_candles"] == 1
    assert summary["exact_ohlc_matches"] == 1
    assert summary["spread_min_matches"] == 1
    assert details.ohlc_exact_match.iloc[0]


def test_exact_timestamp_alignment_and_price_differences():
    exness = pd.DataFrame({"timestamp_utc": pd.to_datetime([
        "2026-01-01T00:00Z", "2026-01-01T00:15Z"]),
        "open": [100., 110.], "high": [110., 120.],
        "low": [95., 105.], "close": [105., 115.],
        "tick_volume": [10, 10]})
    bitstamp = pd.DataFrame({"timestamp": pd.to_datetime([
        "2026-01-01T00:00Z", "2026-01-01T00:30Z"]),
        "open": [98., 130.], "high": [109., 135.],
        "low": [94., 125.], "close": [103., 132.], "volume": [1, 1]})
    common, stats = align_price_feeds(exness, bitstamp)
    assert stats["common_candles"] == 1
    assert stats["exness_only_timestamps"] == 1
    assert stats["bitstamp_only_timestamps"] == 1
    assert common.close_difference_usd.iloc[0] == 2
    assert common.close_difference_percent.iloc[0] == pytest.approx(2 / 103 * 100)


def test_signal_exact_near_opposite_and_unmatched():
    def frame(rows):
        return pd.DataFrame([{"signal_time": pd.Timestamp(t, tz="UTC"),
                              "direction": d, "trigger": 100.,
                              "structural_stop": 90., "planned_target_distance": 30.,
                              "planned_risk_price": 10.} for t, d in rows])

    exness = frame([("2026-01-01 00:00", "LONG"),
                    ("2026-01-01 00:30", "LONG"),
                    ("2026-01-01 01:00", "SHORT"),
                    ("2026-01-01 02:00", "LONG")])
    bitstamp = frame([("2026-01-01 00:00", "LONG"),
                      ("2026-01-01 00:45", "LONG"),
                      ("2026-01-01 02:00", "SHORT"),
                      ("2026-01-01 03:00", "LONG")])
    _, summary = signal_matches(exness, bitstamp)
    assert (summary["exact_matches"], summary["near_matches"], summary["opposite"],
            summary["exness_only"], summary["bitstamp_only"]) == (1, 1, 1, 1, 1)


def test_bar_minimum_spread_is_separate_from_fixed_or_zero_cost():
    trades = pd.DataFrame([{"entry_time": pd.Timestamp("2026-01-01", tz="UTC"),
                            "quantity": .1, "gross_pnl": 5.,
                            "planned_risk": 2.5, "direction": "LONG"}])
    minimum = pd.Series([10.], index=[pd.Timestamp("2026-01-01", tz="UTC")])
    zero = price_cost_view(trades)
    lower = price_cost_view(trades, spread_bars=minimum)
    fixed = price_cost_view(trades, fixed_spread=20.)
    assert zero.net_pnl.iloc[0] == 5
    assert lower.net_pnl.iloc[0] == 4
    assert fixed.net_pnl.iloc[0] == 3
    with pytest.raises(ValueError):
        price_cost_view(trades, spread_bars=minimum, fixed_spread=20.)


def test_exness_setup_b_prefix_is_causal():
    bars = pd.read_csv(PROCESSED, parse_dates=["timestamp_utc"]).iloc[:4000].copy()
    base = engine_frame(bars, exness=True)
    altered = base.copy()
    future = altered.index[-20:]
    altered.loc[future, ["open", "high", "low", "close"]] *= 1.15
    first = run_independent_feed(base, "original")["signals"]
    second = run_independent_feed(altered, "altered")["signals"]
    cutoff = base.timestamp.iloc[-21]
    left = first.loc[first.signal_time <= cutoff, ["signal_time", "direction", "trigger", "structural_stop"]]
    right = second.loc[second.signal_time <= cutoff, ["signal_time", "direction", "trigger", "structural_stop"]]
    assert not left.empty
    pd.testing.assert_frame_equal(left.reset_index(drop=True), right.reset_index(drop=True))
