"""Resumable Bitstamp history and continuous-range safeguards."""
import pandas as pd
import pytest

from services.history import sync_btc_history
from utils.data_validation import (
    continuous_segments, find_missing_ranges, largest_continuous_segment,
    load_ohlcv_csv, merge_ohlcv, missing_gaps, prepare_ohlcv, validate_ohlcv,
)


def candles(times):
    return pd.DataFrame([
        {"timestamp": pd.Timestamp(t), "open": 100, "high": 101,
         "low": 99, "close": 100, "volume": 1}
        for t in times
    ])


class FakeClient:
    def __init__(self, rows, fail_on=None):
        self.rows = rows
        self.fail_on = fail_on
        self.calls = []

    def download_ohlc(self, start, end):
        self.calls.append((start, end))
        if self.fail_on == len(self.calls):
            raise RuntimeError("interrupted")
        # Include an overlapping duplicate to exercise canonical merging.
        return self.rows[self.rows.timestamp.between(start, end)].copy()


def test_incremental_sync_overlaps_deduplicates_and_skips_saved_ranges(tmp_path):
    path = tmp_path / "btcusd_15m.csv"
    times = pd.date_range("2025-01-01T00:00:00Z", periods=4, freq="15min")
    source = candles([times[0], times[1], times[1], times[2], times[3]])
    client = FakeClient(source)
    first = sync_btc_history(times[0], times[3], path=path, client=client)
    saved = load_ohlcv_csv(path)
    assert first.saved_candles == 4 and first.remaining_candles == 0
    assert len(saved) == 4 and saved.timestamp.is_unique
    assert saved.timestamp.is_monotonic_increasing
    assert saved.timestamp.dt.tz is not None
    again = sync_btc_history(times[0], times[3], path=path, client=client)
    assert again.requested_chunks == 0
    assert len(client.calls) == 1


def test_interrupted_sync_resumes_from_last_saved_chunk(tmp_path):
    path = tmp_path / "btcusd_15m.csv"
    times = pd.date_range("2025-01-01T00:00:00Z", periods=1002, freq="15min")
    source = candles(times)
    with pytest.raises(RuntimeError, match="interrupted"):
        sync_btc_history(times[0], times[-1], path=path,
                         client=FakeClient(source, fail_on=2))
    assert len(load_ohlcv_csv(path)) == 1000
    resumed = FakeClient(source)
    result = sync_btc_history(times[0], times[-1], path=path, client=resumed)
    assert result.requested_chunks == 1 and result.saved_candles == 1002
    assert resumed.calls == [(times[1000], times[1001])]


def test_missing_api_rows_remain_gaps_and_segments_are_reported(tmp_path):
    times = pd.date_range("2025-01-01T00:00:00Z", periods=5, freq="15min")
    path = tmp_path / "btcusd_15m.csv"
    result = sync_btc_history(times[0], times[-1], path=path,
                              client=FakeClient(candles([times[0], times[1], times[4]])))
    saved = load_ohlcv_csv(path)
    assert result.remaining_candles == 2
    assert validate_ohlcv(saved).expected_candles == 5
    assert validate_ohlcv(saved).missing_candles == 2
    assert len(continuous_segments(saved)) == 2
    assert missing_gaps(saved)[0].start == times[2]
    assert missing_gaps(saved)[0].end == times[3]
    assert missing_gaps(saved)[0].missing_candles == 2


def test_largest_continuous_segment_filters_multi_year_fragments():
    first = pd.date_range("2023-01-01T00:00:00Z", periods=2, freq="15min")
    second = pd.date_range("2024-01-01T00:00:00Z", periods=4, freq="15min")
    data, _ = prepare_ohlcv(candles([*first, *second]))
    selected, segment = largest_continuous_segment(data)
    assert len(continuous_segments(data)) == 2
    assert segment.start == second[0] and segment.end == second[-1]
    assert selected.timestamp.tolist() == list(second)
    gaps = missing_gaps(data)
    assert gaps[0].missing_candles > 35_000
