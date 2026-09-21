"""Trade-log timestamps are human-readable UTC ISO text, in both directions.

``_trade_row`` unwrapped any value exposing ``.value`` before its pd.Timestamp
branch could run. pd.Timestamp exposes ``.value`` as epoch nanoseconds, so every
trade timestamp was serialized as an integer like ``1701569700000000000`` and
the Timestamp branch was dead code. The Trades tab, its CSV export and the
Overview chart markers all rendered that integer.

Experiments written before the fix are still in the ledger, so every reader has
to accept both encodings. These tests pin the writer, the readers, and the fact
that nothing about the trades themselves changed.
"""
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from core.adapters.audited_engine import _trade_row, run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from core.trade_log import (
    serialize_timestamp, timestamp_series, timestamp_text, to_timestamp,
)
from engine.models import Direction, EntryModel, Trade
from research.robustness import RobustnessBlocked, trades_from_trade_log
from services import market_datasets as md
from ui.universal_workspace import _price_chart, trades_dataframe

ROOT = Path(__file__).resolve().parents[1]
STAMP = pd.Timestamp("2024-01-05T10:00:00Z")
TIMESTAMP_FIELDS = ("signal_time", "entry_time", "exit_time", "mfe_timestamp",
                    "mae_timestamp", "pending_created_time", "pending_expiry_time")


# --- the encoder -------------------------------------------------------------


@pytest.mark.parametrize("value", (
    STAMP, STAMP.value, str(STAMP.value), STAMP.isoformat(),
    "2024-01-05 10:00:00", "2024-01-05T10:00:00", STAMP.to_pydatetime(),
    datetime(2024, 1, 5, 10, tzinfo=timezone.utc),
))
def test_every_encoding_reads_back_to_the_same_instant(value):
    assert to_timestamp(value) == STAMP


def test_serialization_is_human_readable_utc_iso():
    assert serialize_timestamp(STAMP) == "2024-01-05T10:00:00+00:00"
    assert serialize_timestamp(STAMP.value) == "2024-01-05T10:00:00+00:00"


def test_a_naive_timestamp_is_read_as_utc_not_local_time():
    assert to_timestamp(pd.Timestamp("2024-01-05 10:00:00")).tzinfo is not None
    assert serialize_timestamp(pd.Timestamp("2024-01-05 10:00:00")).endswith("+00:00")


def test_a_non_utc_timestamp_is_converted_rather_than_relabelled():
    tokyo = STAMP.tz_convert("Asia/Tokyo")
    assert serialize_timestamp(tokyo) == "2024-01-05T10:00:00+00:00"


def test_an_absent_optional_timestamp_stays_absent():
    """Several Trade timestamp fields are genuinely optional."""
    assert serialize_timestamp(None) is None
    with pytest.raises(ValueError):
        to_timestamp(None)


@pytest.mark.parametrize("value", ("not-a-time", object(), True))
def test_display_text_never_raises_on_a_bad_value(value):
    assert timestamp_text(value) is value


@pytest.mark.parametrize("value", (object(), True))
def test_parsing_refuses_a_value_that_is_not_a_timestamp(value):
    with pytest.raises((TypeError, ValueError)):
        to_timestamp(value)


# --- the writer --------------------------------------------------------------


def _trade(**over) -> Trade:
    values = dict(
        trade_id=1, direction=Direction.LONG, signal_time=STAMP, entry_time=STAMP,
        entry_price=100.0, stop_loss=90.0, take_profit=130.0,
        exit_time=STAMP + pd.Timedelta(hours=2), exit_price=130.0, exit_reason="target",
        quantity=1.0, initial_risk=10.0, pnl=30.0, pnl_percent=0.3, r_multiple=3.0,
        bars_held=8, entry_commission=0.0, exit_commission=0.0,
        entry_model=EntryModel.STOP_ENTRY_PENDING, setup_id="X",
        mfe_timestamp=STAMP, mae_timestamp=None,
    )
    values.update(over)
    return Trade(**values)


def test_trade_row_writes_iso_text_for_every_timestamp():
    row = _trade_row(_trade())
    assert row["entry_time"] == "2024-01-05T10:00:00+00:00"
    assert row["exit_time"] == "2024-01-05T12:00:00+00:00"
    assert row["mfe_timestamp"] == "2024-01-05T10:00:00+00:00"
    assert row["mae_timestamp"] is None


def test_trade_row_still_unwraps_the_enums_it_was_written_for():
    """The enum branch is why timestamps were swallowed; it must still work."""
    row = _trade_row(_trade())
    assert row["direction"] == "LONG"
    assert row["entry_model"] == "STOP_ENTRY_PENDING"
    assert row["realized_r"] == pytest.approx(3.0)


def test_no_trade_row_value_is_an_epoch_nanosecond_integer():
    row = _trade_row(_trade())
    for field in TIMESTAMP_FIELDS:
        assert not isinstance(row.get(field), int), field


# --- a real run --------------------------------------------------------------


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    if not entry.exists:
        pytest.skip("validated Exness dataset unavailable")
    config = BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD",
        strategy_id="BTC_V3_CORE_V1_FROZEN", timeframe="15m", higher_timeframes=("1h",),
        start_date=pd.Timestamp("2024-01-01", tz="UTC"),
        end_date=pd.Timestamp("2024-07-01", tz="UTC"),
        dataset_role=DatasetRole.DEVELOPMENT, risk_per_trade_percent=0.25,
        spread=0.0, spread_source=entry.spread_source, data_source=entry.key)
    path = tmp_path_factory.mktemp("ts") / "run.sqlite3"
    return run_universal_backtest(entry.path, config, ledger_path=path)


def test_a_real_run_writes_readable_timestamps(baseline):
    assert baseline.trade_log
    for row in baseline.trade_log:
        for field in ("signal_time", "entry_time", "exit_time"):
            assert isinstance(row[field], str), field
            assert row[field].endswith("+00:00"), row[field]
            assert to_timestamp(row[field]).year >= 2023


def test_trade_timestamps_survive_a_json_round_trip(baseline):
    import json

    payload = json.loads(json.dumps(baseline.as_dict(), sort_keys=True, default=str))
    assert payload["trade_log"] == baseline.trade_log


def test_trades_are_chronological_when_read_as_text(baseline):
    """ISO-8601 UTC sorts lexicographically in time order; nanoseconds did too."""
    entries = [row["entry_time"] for row in baseline.trade_log]
    assert entries == sorted(entries)


# --- the readers -------------------------------------------------------------


def test_the_trades_tab_shows_dates_not_integers(baseline):
    table = trades_dataframe(baseline, "BTCUSD")
    assert str(table["Entry Time"].iloc[0]).startswith("20")
    assert "+00:00" in str(table["Entry Time"].iloc[0])


def test_the_csv_export_contains_dates(baseline):
    csv = trades_dataframe(baseline, "BTCUSD").to_csv(index=False)
    assert "1704" not in csv.split("\n")[1].split(",")[2]
    assert csv.count("+00:00") >= len(baseline.trade_log)


def test_the_trades_tab_still_renders_a_legacy_record():
    """Experiments stored before the fix hold epoch nanoseconds."""
    legacy = type("R", (), {"trade_log": [{
        "trade_id": 1, "direction": "LONG", "signal_time": STAMP.value,
        "entry_time": STAMP.value, "exit_time": STAMP.value, "entry_price": 1.0,
        "realized_r": 1.0, "pnl": 1.0}], "run_id": "BT-OLD"})()
    table = trades_dataframe(legacy, "BTCUSD")
    assert table["Entry Time"].iloc[0] == "2024-01-05T10:00:00+00:00"


def test_the_price_chart_places_markers_on_the_time_axis(baseline):
    stamps = [row[field] for row in baseline.trade_log
              for field in ("entry_time", "exit_time")]
    data = pd.DataFrame({"timestamp": pd.to_datetime(stamps, utc=True).sort_values(),
                         "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5})
    figure = _price_chart(data, baseline, "BTCUSD")
    marker_traces = [trace for trace in figure.data
                     if getattr(trace, "mode", None) == "markers"]
    assert marker_traces
    axis_low, axis_high = data.timestamp.min(), data.timestamp.max()
    for trace in marker_traces:
        assert trace.x is not None and len(trace.x)
        for value in trace.x:
            #--- An epoch-nanosecond integer here puts the marker ~1.7e18 off the
            #--- candlestick axis, which is what the defect did.
            assert not isinstance(value, (int, float)), value
            assert axis_low <= pd.Timestamp(value) <= axis_high


def test_timestamp_series_reads_a_whole_column_in_either_encoding():
    parsed = timestamp_series([STAMP.value, STAMP.isoformat()])
    assert list(parsed) == [STAMP, STAMP]


# --- robustness reads stored experiments -------------------------------------


def _log_row(timestamp):
    return {"trade_id": 1, "realized_r": 1.0, "pnl": 100.0, "direction": "LONG",
            "setup_id": "X", "initial_risk": 10.0, "duration_minutes": 30.0,
            "entry_time": timestamp, "exit_time": timestamp}


@pytest.mark.parametrize("timestamp", (STAMP.isoformat(), STAMP.value, str(STAMP.value)))
def test_robustness_accepts_both_stored_encodings(timestamp):
    trades = trades_from_trade_log([_log_row(timestamp)],
                                   dataset_role="DEVELOPMENT", source_run_id="BT-1")
    assert len(trades) == 1


def test_robustness_still_refuses_an_unparseable_timestamp():
    with pytest.raises(RobustnessBlocked):
        trades_from_trade_log([_log_row("never")], dataset_role="DEVELOPMENT",
                              source_run_id="BT-1")


def test_robustness_still_refuses_an_out_of_order_sequence():
    rows = [_log_row(STAMP.isoformat()), _log_row((STAMP - pd.Timedelta(days=1)).isoformat())]
    with pytest.raises(RobustnessBlocked):
        trades_from_trade_log(rows, dataset_role="DEVELOPMENT", source_run_id="BT-1")


# --- research consumers ------------------------------------------------------


def test_research_frames_read_both_encodings_identically():
    """Research code goes through pd.to_datetime(..., utc=True), which takes both."""
    legacy = pd.DataFrame([{"entry_time": STAMP.value, "exit_time": STAMP.value}])
    current = pd.DataFrame([{"entry_time": STAMP.isoformat(), "exit_time": STAMP.isoformat()}])
    for frame in (legacy, current):
        for column in ("entry_time", "exit_time"):
            frame[column] = pd.to_datetime(frame[column], utc=True)
    assert legacy.equals(current)
    assert legacy.entry_time.iloc[0] == STAMP


def test_phase_a_analysis_matches_trades_across_encodings():
    from research import core_v2_phase_a as phase_a

    baseline = [{"setup_id": "A", "direction": "LONG", "entry_time": STAMP.value,
                 "realized_r": 1.0, "pnl": 1.0, "entry_price": 1.0, "exit_price": 2.0}]
    variant = [{"setup_id": "A", "direction": "LONG", "entry_time": STAMP.isoformat(),
                "realized_r": 1.0, "pnl": 1.0, "entry_price": 1.0, "exit_price": 2.0}]
    delta = phase_a.trade_delta(baseline, variant)
    assert delta.added == [] and delta.displaced == []


# --- nothing about the trades changed ----------------------------------------


def test_the_frozen_core_baseline_is_unchanged(baseline):
    """Serialization must not touch a single trade result."""
    assert baseline.total_trades == 54
    assert [round(row["entry_price"], 8) for row in baseline.trade_log]
    assert all(row["realized_r"] is not None for row in baseline.trade_log)
    assert baseline.profit_factor == 0.9532554010296652


def test_diagnostics_payloads_are_untouched_by_the_fix(baseline):
    assert baseline.core_funnel.get("available") is True
    assert baseline.core_funnel["integrity"].get("signal_mismatches", 0) == 0
    assert baseline.signal_diagnostics
    assert baseline.xray_diagnostics
