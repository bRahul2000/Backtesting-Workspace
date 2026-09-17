"""Exness Standard profile, explicit tick import, and Bid/Ask bar tests."""
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

from brokers.exness_standard_btcusdm import PROFILE, quote_side, research_quote_price
from services.exness_ticks import (
    TickColumns, TickImportError, import_tick_sources, inspect_tick_source,
    normalize_tick_chunk,
)


def test_standard_commission_and_known_contract_terms():
    assert PROFILE.account_type == "Standard"
    assert PROFILE.mt5_symbol == "BTCUSDm"
    assert PROFILE.commission_per_side_usd == 0
    assert PROFILE.btc_per_lot == 1
    assert PROFILE.volume_step_lots == .01
    assert PROFILE.minimum_volume_lots == .01
    assert PROFILE.server_timezone == "UTC+0 / GMT+0"
    assert PROFILE.swap_usd_conversion == "PENDING VERIFICATION"


@pytest.mark.parametrize("direction,event,side,price", [
    ("long", "entry", "ask", 101),
    ("short", "entry", "bid", 100),
    ("long", "close", "bid", 100),
    ("short", "close", "ask", 101),
    ("long", "pending_trigger", "ask", 101),
    ("short", "pending_trigger", "bid", 100),
    ("long", "stop_target", "bid", 100),
    ("short", "stop_target", "ask", 101),
])
def test_research_execution_quote_side(direction, event, side, price):
    assert quote_side(direction, event) == side
    assert research_quote_price(bid=100, ask=101, direction=direction, event=event) == price


def test_spread_price_percent_and_bps_and_timezone():
    raw = pd.DataFrame({"Time": ["2026-01-01 00:00:00+02:00"],
                        "BidPrice": [100.], "Offer": [101.]})
    values = normalize_tick_chunk(raw, TickColumns("Time", "BidPrice", "Offer"))
    assert values.timestamp_utc.iloc[0] == pd.Timestamp("2025-12-31 22:00", tz="UTC")
    assert values.spread_price.iloc[0] == 1.
    assert values.spread_pct.iloc[0] == 1.
    assert values.spread_bps.iloc[0] == 100.


def test_naive_timestamp_requires_explicit_timezone():
    raw = pd.DataFrame({"T": ["2026-01-01 00:00:00"], "B": [100], "A": [101]})
    mapping = TickColumns("T", "B", "A")
    with pytest.raises(TickImportError, match="timezone"):
        normalize_tick_chunk(raw, mapping)
    normalized = normalize_tick_chunk(raw, mapping, source_timezone="UTC")
    assert normalized.timestamp_utc.iloc[0] == pd.Timestamp("2026-01-01", tz="UTC")


def test_numeric_timestamp_requires_explicit_unit():
    raw = pd.DataFrame({"T": [1767225600000], "B": [100], "A": [101]})
    mapping = TickColumns("T", "B", "A")
    with pytest.raises(TickImportError, match="timestamp-unit"):
        normalize_tick_chunk(raw, mapping)
    normalized = normalize_tick_chunk(raw, mapping, timestamp_unit="ms")
    assert normalized.timestamp_utc.iloc[0] == pd.Timestamp("2026-01-01", tz="UTC")


@pytest.mark.parametrize("bid,ask", [(0, 1), (100, 99), (float("nan"), 101),
                                     (100, float("inf"))])
def test_malformed_bid_ask_rejected(bid, ask):
    raw = pd.DataFrame({"T": ["2026-01-01T00:00:00Z"], "B": [bid], "A": [ask]})
    with pytest.raises(TickImportError, match="Bid/Ask"):
        normalize_tick_chunk(raw, TickColumns("T", "B", "A"))


def _tick_csv(path: Path) -> None:
    pd.DataFrame([
        ["2026-01-01T00:00:02Z", 100., 101.],
        ["2026-01-01T00:00:01Z", 99., 100.],
        ["2026-01-01T00:00:01Z", 99., 100.],  # exact duplicate
        ["2026-01-01T00:00:02Z", 100.5, 101.5],  # same time, distinct quote
        ["2026-01-01T00:15:00Z", 110., 112.],
        ["2026-01-01T00:45:00Z", 120., 123.],
    ], columns=["ActualTime", "BestBid", "BestAsk"]).to_csv(path, index=False)


def _import(path: Path, tmp_path: Path):
    return import_tick_sources([path], TickColumns("ActualTime", "BestBid", "BestAsk"),
                               processed_dir=tmp_path / "processed",
                               report_dir=tmp_path / "reports", chunk_rows=2)


def test_csv_import_sort_exact_duplicates_bid_ask_bars_and_gap(tmp_path):
    source = tmp_path / "raw.csv"
    _tick_csv(source)
    original = source.read_bytes()
    schema = inspect_tick_source(source)[0]
    assert schema.columns == ("ActualTime", "BestBid", "BestAsk")
    summary = _import(source, tmp_path)
    assert source.read_bytes() == original
    assert summary["input_rows"] == 6
    assert summary["duplicates_removed"] == 1
    assert summary["tick_count"] == 5
    assert summary["median_spread_price"] == 1.
    assert summary["mean_spread_price"] == pytest.approx(1.6)
    assert summary["p90_spread_price"] == pytest.approx(2.6)
    assert summary["p95_spread_price"] == pytest.approx(2.8)
    assert summary["p99_spread_price"] == pytest.approx(2.96)
    assert summary["maximum_spread_price"] == 3.
    assert summary["time_weighted_spread"] is None
    assert summary["bid_15m_candles"] == 3
    assert summary["missing_15m_intervals"] == 1
    ticks = pd.read_csv(tmp_path / "processed/btcusdm_ticks.csv", parse_dates=["timestamp_utc"])
    assert ticks.timestamp_utc.is_monotonic_increasing
    assert len(ticks.loc[ticks.timestamp_utc == pd.Timestamp("2026-01-01T00:00:02Z")]) == 2
    bid = pd.read_csv(tmp_path / "processed/btcusdm_bid_15m.csv")
    ask = pd.read_csv(tmp_path / "processed/btcusdm_ask_15m.csv")
    assert bid.iloc[0][["open", "high", "low", "close", "tick_count"]].tolist() == [99., 100.5, 99., 100.5, 3]
    assert ask.iloc[0][["open", "high", "low", "close", "tick_count"]].tolist() == [100., 101.5, 100., 101.5, 3]
    assert bid.spread_median.iloc[0] == 1.
    assert pd.read_csv(tmp_path / "reports/data_gaps.csv").missing_15m_intervals.tolist() == [1]


def test_zip_member_import_and_schema_inspection(tmp_path):
    source = tmp_path / "ticks.csv"
    _tick_csv(source)
    archive = tmp_path / "ticks.zip"
    with ZipFile(archive, "w") as zipped:
        zipped.write(source, "nested/day.csv")
    schema = inspect_tick_source(archive)
    assert schema[0].member == "nested/day.csv"
    assert _import(archive, tmp_path)["tick_count"] == 5


def test_unverified_server_time_keeps_utc_labels_absent(tmp_path):
    source = tmp_path / "server.tsv"
    pd.DataFrame([
        ["2026-08-01 12:00:00", 100, 110],
        ["2026-08-01 12:00:00", 100, 110],
        ["2026-08-01 12:00:00", 101, 111],
        ["2026-08-01 12:15:00", 102, 112],
    ], columns=["Date", "Bid", "Ask"]).to_csv(source, sep="\t", index=False)
    # The format, not the filename extension, is inspected before import.
    source = source.rename(tmp_path / "server.csv")
    summary = import_tick_sources(
        [source], TickColumns("Date", "Bid", "Ask"),
        server_time_unverified=True, processed_dir=tmp_path / "processed",
        report_dir=tmp_path / "reports")
    assert summary["status"] == "imported_server_time_unverified"
    assert summary["input_rows"] == 4
    assert summary["duplicate_full_rows"] == 1
    assert summary["duplicate_timestamps_raw"] == 2
    assert summary["same_timestamp_distinct_quotes"] == 1
    assert summary["first_tick_server"] == "2026-08-01T12:00:00"
    assert "first_tick_utc" not in summary
    assert summary["bid_15m_candles"] == 2
    ticks = pd.read_csv(tmp_path / "processed/btcusdm_ticks_server_time.csv")
    assert ticks.columns[0] == "timestamp_server"
    assert not (tmp_path / "processed/btcusdm_ticks.csv").exists()
    assert (tmp_path / "processed/btcusdm_bid_15m_server_time.csv").exists()
    assert (tmp_path / "processed/btcusdm_ask_15m_server_time.csv").exists()
    assert (tmp_path / "reports/spread_by_server_hour.csv").exists()
    assert not (tmp_path / "reports/spread_by_hour.csv").exists()


def test_unknown_mapping_and_invalid_import_do_not_write_processed_data(tmp_path):
    source = tmp_path / "bad.csv"
    pd.DataFrame({"When": ["2026-01-01T00:00:00Z"], "Bid": [100],
                  "Ask": [99]}).to_csv(source, index=False)
    with pytest.raises(TickImportError):
        import_tick_sources([source], TickColumns("When", "Bid", "Ask"),
                            processed_dir=tmp_path / "processed",
                            report_dir=tmp_path / "reports")
    assert not (tmp_path / "processed/btcusdm_ticks.csv").exists()
    with pytest.raises(TickImportError, match="Mapped"):
        import_tick_sources([source], TickColumns("Time", "Bid", "Ask"),
                            processed_dir=tmp_path / "processed",
                            report_dir=tmp_path / "reports")
