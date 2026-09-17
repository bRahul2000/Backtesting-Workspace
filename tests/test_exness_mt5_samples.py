"""Deterministic MT5 quote-state tests; fixtures are not broker observations."""
import csv

import pandas as pd
import pytest

from brokers.exness_standard_btcusdm import historical_spread_price
from services.exness_mt5_samples import (
    TIMEZONE_STATUS, process_mt5_samples, process_sample,
)


HEADER = ("<DATE>", "<TIME>", "<BID>", "<ASK>", "<LAST>", "<VOLUME>", "<FLAGS>")


def _source(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(HEADER)
        for stamp, bid, ask in rows:
            date, clock = stamp.split(" ")
            writer.writerow([date, clock, bid, ask, "", "", "6" if bid and ask else "2"])
    return path


def _ticks(tmp_path, sample_id):
    return pd.read_csv(tmp_path / f"btcusdm_{sample_id}_ticks_server_time.csv",
                       keep_default_na=False)


def test_bid_ask_partial_updates_and_same_timestamp_order(tmp_path):
    source = _source(tmp_path / "a.csv", [
        ("2026.08.01 12:00:00.000", "100", "110"),
        ("2026.08.01 12:00:00.000", "101", ""),
        ("2026.08.01 12:00:00.000", "", "111"),
        ("2026.08.01 12:00:00.000", "102", "112"),
        ("2026.08.01 12:00:00.000", "102", "112"),
    ])
    original = source.read_bytes()
    summary, spreads, _, _ = process_sample(source, "s01", tmp_path / "out")
    ticks = pd.read_csv(tmp_path / "out/btcusdm_s01_ticks_server_time.csv",
                        keep_default_na=False)
    assert source.read_bytes() == original
    assert summary["raw_rows"] == 5
    assert summary["bid_only_updates"] == 1
    assert summary["ask_only_updates"] == 1
    assert summary["both_side_updates"] == 2
    assert summary["duplicate_full_rows"] == 1
    assert summary["duplicate_timestamps"] == 4
    assert summary["tick_count"] == 4
    assert ticks.bid.tolist() == [100, 101, 101, 102]
    assert ticks.ask.tolist() == [110, 110, 111, 112]
    assert ticks.bid_carried.tolist() == [False, False, True, False]
    assert ticks.ask_carried.tolist() == [False, True, False, False]
    assert ticks.ask_raw.iloc[1] == ""
    assert ticks.bid_raw.iloc[2] == ""
    assert spreads == [10, 9, 10, 10]
    assert historical_spread_price(bid=101, ask=110) == 9


def test_no_carry_before_first_complete_quote_or_across_file(tmp_path):
    first = _source(tmp_path / "first.csv", [
        ("2026.08.01 12:00:00.000", "100", "110")])
    second = _source(tmp_path / "second.csv", [
        ("2026.08.02 12:00:00.000", "200", ""),
        ("2026.08.02 12:00:01.000", "", "210")])
    summary = process_mt5_samples([first, second], processed_dir=tmp_path / "processed",
                                  report_dir=tmp_path / "reports")
    assert summary["timezone_status"] == TIMEZONE_STATUS
    assert summary["sample_count"] == 2
    assert summary["total_ticks"] == 2
    ticks = _ticks(tmp_path / "processed", "s02")
    assert len(ticks) == 1
    assert ticks.iloc[0]["timestamp_raw"] == "2026.08.02 12:00:01.000"
    assert ticks.iloc[0]["bid"] == 200
    assert ticks.iloc[0]["ask"] == 210


def test_gap_resets_quote_state_and_never_fabricates_bar(tmp_path):
    source = _source(tmp_path / "gap.csv", [
        ("2026.08.01 12:00:00.000", "100", "110"),
        ("2026.08.01 12:30:00.000", "200", ""),
        ("2026.08.01 12:30:01.000", "", "210")])
    summary, _, _, gaps = process_sample(source, "s01", tmp_path / "out")
    ticks = pd.read_csv(tmp_path / "out/btcusdm_s01_ticks_server_time.csv")
    bars = pd.read_csv(tmp_path / "out/btcusdm_s01_bid_15m_server_time.csv")
    assert summary["tick_count"] == 2
    assert summary["bid_15m_bars"] == 2
    assert summary["missing_15m_intervals"] == 1
    assert gaps[0]["gap_start_server"] == "2026-08-01T12:15:00"
    assert ticks.ask.tolist() == [110, 210]
    assert "2026-08-01T12:15:00" not in bars.timestamp_server.tolist()


def test_historical_spread_rejects_invalid_quote():
    assert TIMEZONE_STATUS == "EXNESS_MT5_SERVER_TIME_UTC_PLUS_0_CONFIRMED"
    with pytest.raises(ValueError):
        historical_spread_price(bid=100, ask=99)
