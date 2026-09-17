"""Archive aggregation and descriptive period metrics are deterministic."""
from types import SimpleNamespace

import pandas as pd
import pytest

from research.import_bitstamp_archive import aggregate_archive, import_archive
from research.setup_b_history_baseline import period_summary
from utils.data_validation import load_ohlcv_csv


def minute_rows(times):
    return pd.DataFrame({
        "timestamp": [int(t.timestamp()) for t in times],
        "open": [100.0] * len(times), "high": [101.0] * len(times),
        "low": [99.0] * len(times), "close": [100.0] * len(times),
        "volume": [1.0] * len(times),
    })


def test_archive_aggregation_keeps_complete_bins_without_filling_missing_minutes(tmp_path):
    times = pd.date_range("2025-01-01T00:00:00Z", periods=30, freq="1min")
    first = minute_rows(times[:15])
    second = minute_rows(times[15:]).drop(index=5)
    historical = tmp_path / "historical.csv"
    updates = tmp_path / "updates.csv"
    first.to_csv(historical, index=False)
    second.to_csv(updates, index=False)
    data, details = aggregate_archive(
        [historical, updates], times[0], times[-1].floor("15min"),
    )
    assert len(data) == 1
    assert data.timestamp.iloc[0] == times[0]
    assert data.volume.iloc[0] == 15
    assert details["source_minutes_in_range"] == 29


def test_archive_rejects_disagreement_with_api_derived_saved_candle(tmp_path):
    times = pd.date_range("2025-01-07T00:00:00Z", periods=15, freq="1min")
    historical = tmp_path / "historical.csv"
    updates = tmp_path / "updates.csv"
    minute_rows(times).iloc[:0].to_csv(historical, index=False)
    minute_rows(times).to_csv(updates, index=False)
    saved = tmp_path / "canonical.csv"
    pd.DataFrame([{
        "timestamp": times[0], "open": 102, "high": 102,
        "low": 99, "close": 100, "volume": 15,
    }]).to_csv(saved, index=False)
    with pytest.raises(ValueError, match="disagrees"):
        import_archive(historical, updates, start=times[0], end=times[0],
                       canonical=saved, dry_run=True)
    assert load_ohlcv_csv(saved).open.iloc[0] == 102


def test_period_summary_uses_period_open_equity_and_trade_order():
    trades = [
        SimpleNamespace(pnl=50, realized_r=2, direction=None),
        SimpleNamespace(pnl=-25, realized_r=-1, direction=None),
        SimpleNamespace(pnl=-25, realized_r=-1, direction=None),
    ]
    summary = period_summary(trades, 1000)
    assert summary["trades"] == 3
    assert summary["wins"] == 1 and summary["losses"] == 2
    assert summary["net_pnl"] == 0
    assert summary["profit_factor"] == 1
    assert summary["average_r"] == 0
    assert summary["maximum_losing_streak"] == 2
    assert summary["max_drawdown_percent"] == pytest.approx(50 / 1050 * 100)
