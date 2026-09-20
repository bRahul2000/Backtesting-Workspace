"""Phase R1 BTCUSDm broker-dataset pipeline tests.

Fixtures here are small synthetic candle tables used to exercise the validators.
They are written only to tmp_path and never into data/; no synthetic value is
ever presented as broker data, and the real exports are read read-only.
"""
import json

import pandas as pd
import pytest

from core.fingerprints import sha256_file
from services.btc_broker_data import (
    MANIFEST_PATH, BrokerDataError, M15_FILE, H1_FILE, SPEC_FILE, build_phase_r1, load_btc_spec,
    phase_r1_inputs, phase_r1_status, read_broker_ohlcv, reconcile_m15_h1,
    segment_report, spread_statistics, tick_sample_assets, validate_candles,
)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
REAL_M15 = ROOT / "data/exness/raw/BTCUSDm_M15_202311090000_202609171715.csv"
POINT = 0.01


#: Logical fixture row order: (timestamp, open, high, low, close, tick_volume,
#: real_volume, spread). Each writer places those fields in its own layout's
#: column order -- the exporter puts spread before real_volume, the terminal
#: dump the other way round.
def _exporter_csv(path, rows):
    lines = ["timestamp,open,high,low,close,tick_volume,spread,real_volume"]
    for stamp, open_, high, low, close, tick_volume, real_volume, spread in rows:
        lines.append(",".join(str(value) for value in
                              (stamp, open_, high, low, close, tick_volume, spread, real_volume)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _terminal_csv(path, rows):
    header = "\t".join(("<DATE>", "<TIME>", "<OPEN>", "<HIGH>", "<LOW>", "<CLOSE>",
                        "<TICKVOL>", "<VOL>", "<SPREAD>"))
    lines = [header]
    for stamp, open_, high, low, close, tick_volume, real_volume, spread in rows:
        date, time = stamp.split(" ")
        lines.append("\t".join(str(v) for v in
                               (date, time, open_, high, low, close,
                                tick_volume, real_volume, spread)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


M15_ROWS = [
    ("2026.01.01 00:00:00", 100.0, 101.0, 99.0, 100.5, 10, 0, 500),
    ("2026.01.01 00:15:00", 100.5, 102.0, 100.0, 101.5, 12, 0, 520),
    ("2026.01.01 00:30:00", 101.5, 103.0, 101.0, 102.5, 14, 0, 540),
    ("2026.01.01 00:45:00", 102.5, 104.0, 102.0, 103.5, 16, 0, 560),
]
H1_ROWS = [("2026.01.01 00:00:00", 100.0, 104.0, 99.0, 103.5, 52, 0, 530)]


# --- reading -----------------------------------------------------------------------------


def test_reads_the_exporter_layout(tmp_path):
    frame = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", M15_ROWS), point=POINT)
    assert frame.attrs["layout"] == "MT5_EXPORTER_CSV"
    assert len(frame) == 4
    assert frame.timestamp_utc.iloc[0] == pd.Timestamp("2026-01-01 00:00", tz="UTC")
    assert frame.spread_price.iloc[0] == pytest.approx(500 * POINT)


def test_reads_the_mt5_terminal_dump_layout(tmp_path):
    frame = read_broker_ohlcv(_terminal_csv(tmp_path / "dump.csv", M15_ROWS), point=POINT)
    assert frame.attrs["layout"] == "MT5_TERMINAL_CSV_DUMP"
    assert len(frame) == 4
    assert frame.spread_points.iloc[-1] == 560


def test_both_layouts_produce_identical_canonical_frames(tmp_path):
    a = read_broker_ohlcv(_exporter_csv(tmp_path / "a.csv", M15_ROWS), point=POINT)
    b = read_broker_ohlcv(_terminal_csv(tmp_path / "b.csv", M15_ROWS), point=POINT)
    pd.testing.assert_frame_equal(a, b)


def test_unknown_schema_is_refused(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
    with pytest.raises(BrokerDataError, match="missing columns"):
        read_broker_ohlcv(path, point=POINT)


def test_a_non_positive_point_is_refused(tmp_path):
    with pytest.raises(BrokerDataError, match="point size"):
        read_broker_ohlcv(_exporter_csv(tmp_path / "m.csv", M15_ROWS), point=0.0)


# --- validation --------------------------------------------------------------------------


def test_a_clean_dataset_passes_every_check(tmp_path):
    frame = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", M15_ROWS), point=POINT)
    report = validate_candles(frame, timeframe="M15")
    assert report["passed"] is True
    assert report["duplicate_timestamps"] == 0
    assert report["invalid_ohlc_rows"] == 0
    assert report["segments"]["continuous_segments"] == 1


def test_out_of_order_timestamps_fail(tmp_path):
    rows = [M15_ROWS[1], M15_ROWS[0], M15_ROWS[2], M15_ROWS[3]]
    frame = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", rows), point=POINT)
    report = validate_candles(frame, timeframe="M15")
    assert report["timestamps_monotonic_increasing"] is False
    assert report["passed"] is False


def test_duplicate_timestamps_fail(tmp_path):
    rows = list(M15_ROWS) + [M15_ROWS[-1]]
    frame = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", rows), point=POINT)
    report = validate_candles(frame, timeframe="M15")
    assert report["duplicate_timestamps"] == 1
    assert report["passed"] is False


def test_invalid_ohlc_fails(tmp_path):
    rows = list(M15_ROWS)
    # high below low is structurally impossible.
    rows[2] = ("2026.01.01 00:30:00", 101.5, 99.0, 103.0, 102.5, 14, 0, 540)
    frame = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", rows), point=POINT)
    report = validate_candles(frame, timeframe="M15")
    assert report["invalid_ohlc_rows"] >= 1
    assert report["passed"] is False


def test_non_numeric_values_fail(tmp_path):
    rows = list(M15_ROWS)
    rows[1] = ("2026.01.01 00:15:00", 100.5, "n/a", 100.0, 101.5, 12, 0, 520)
    frame = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", rows), point=POINT)
    report = validate_candles(frame, timeframe="M15")
    assert report["non_numeric_rows"] == 1
    assert report["passed"] is False


def test_negative_spread_fails_and_zero_spread_is_only_counted(tmp_path):
    rows = list(M15_ROWS)
    rows[0] = ("2026.01.01 00:00:00", 100.0, 101.0, 99.0, 100.5, 10, 0, -5)
    rows[1] = ("2026.01.01 00:15:00", 100.5, 102.0, 100.0, 101.5, 12, 0, 0)
    frame = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", rows), point=POINT)
    report = validate_candles(frame, timeframe="M15")
    assert report["negative_spread_rows"] == 1
    assert report["zero_spread_rows"] == 1
    # A zero spread is suspicious but not structurally invalid, so it is
    # reported without failing the dataset.
    assert report["passed"] is False  # driven by the negative row


def test_off_grid_timestamps_fail(tmp_path):
    rows = list(M15_ROWS)
    rows[1] = ("2026.01.01 00:07:00", 100.5, 102.0, 100.0, 101.5, 12, 0, 520)
    frame = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", rows), point=POINT)
    report = validate_candles(frame, timeframe="M15")
    assert report["off_grid_timestamps"] == 1
    assert report["passed"] is False


def test_segments_and_gap_distribution(tmp_path):
    rows = [M15_ROWS[0], M15_ROWS[1],
            ("2026.01.01 01:15:00", 103.5, 105.0, 103.0, 104.5, 18, 0, 580)]
    frame = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", rows), point=POINT)
    report = segment_report(frame, timeframe="M15")
    assert report["continuous_segments"] == 2
    assert report["gap_count"] == 1
    assert report["missing_candles"] == 3
    assert report["gap_size_distribution"]["2-4"] == 1


# --- reconciliation ----------------------------------------------------------------------


def test_m15_h1_reconciliation_matches_a_correct_aggregate(tmp_path):
    m15 = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", M15_ROWS), point=POINT)
    h1 = read_broker_ohlcv(_exporter_csv(tmp_path / "h1.csv", H1_ROWS), point=POINT)
    report = reconcile_m15_h1(m15, h1)
    assert report["complete_m15_groups"] == 1
    assert report["groups_compared"] == 1
    assert report["matches"] == 1
    assert report["mismatches"] == 0


def test_m15_h1_reconciliation_reports_mismatch_magnitude(tmp_path):
    m15 = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", M15_ROWS), point=POINT)
    bad = [("2026.01.01 00:00:00", 100.0, 104.0, 99.0, 110.0, 52, 0, 530)]
    h1 = read_broker_ohlcv(_exporter_csv(tmp_path / "h1.csv", bad), point=POINT)
    report = reconcile_m15_h1(m15, h1)
    assert report["mismatches"] == 1
    assert report["mismatch_magnitude"]["max"] == pytest.approx(6.5)
    assert report["mismatch_timestamps"] == ["2026-01-01T00:00:00+00:00"]


def test_incomplete_m15_groups_are_not_compared(tmp_path):
    m15 = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", M15_ROWS[:3]), point=POINT)
    h1 = read_broker_ohlcv(_exporter_csv(tmp_path / "h1.csv", H1_ROWS), point=POINT)
    report = reconcile_m15_h1(m15, h1)
    assert report["complete_m15_groups"] == 0
    assert report["incomplete_m15_groups_not_checkable"] == 1
    assert report["groups_compared"] == 0
    assert report["h1_bars_without_a_complete_m15_group"] == 1


# --- spread ------------------------------------------------------------------------------


def test_spread_statistics_expose_every_required_percentile(tmp_path):
    frame = read_broker_ohlcv(_exporter_csv(tmp_path / "m15.csv", M15_ROWS), point=POINT)
    stats = spread_statistics(frame)
    required = {"min", "p25", "median", "mean", "p75", "p90", "p95", "p99", "max"}
    assert required.issubset(stats["spread_points"])
    assert required.issubset(stats["spread_price"])
    assert stats["spread_price"]["min"] == pytest.approx(5.0)


# --- specification -----------------------------------------------------------------------


def _spec(**overrides):
    payload = {
        "symbol": {"name": "BTCUSDm", "digits": 2, "point": 0.01,
                   "currency_profit": "USD", "currency_margin": "BTC"},
        "broker": {"company": "Exness Technologies Ltd", "server": "Exness-MT5Trial5"},
        "contract": {"tick_size": 0.01, "tick_value": 0.01, "contract_size": 1.0},
        "volume": {"minimum": 0.01, "maximum": 200.0, "step": 0.01},
        "trading": {"trade_mode_name": "FULL", "filling_modes": ["FOK", "IOC"]},
        "quote": {"spread_points": 1000.0},
    }
    payload.update(overrides)
    return payload


def test_spec_loader_accepts_a_valid_snapshot(tmp_path):
    path = tmp_path / SPEC_FILE
    path.write_text(json.dumps(_spec()), encoding="utf-8")
    spec = load_btc_spec(path)
    assert spec["symbol"]["name"] == "BTCUSDm"
    assert spec["profile_id"] == "EXNESS-BTCUSD-v1"


def test_spec_loader_forces_unverified_cost_assumptions(tmp_path):
    path = tmp_path / SPEC_FILE
    # Even an explicit zero capture must not become a verified assumption.
    payload = _spec()
    payload["unverified"] = {"leverage_status": "VERIFIED", "commission_status": "0.0"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    spec = load_btc_spec(path)
    assert spec["unverified"]["leverage_status"] == "UNVERIFIED"
    assert spec["unverified"]["commission_status"] == "UNVERIFIED"
    assert spec["unverified"]["margin_status"] == "UNVERIFIED"


def test_spec_loader_rejects_the_wrong_symbol(tmp_path):
    path = tmp_path / SPEC_FILE
    path.write_text(json.dumps(_spec(symbol={"name": "XAUUSDm", "point": 0.001})), encoding="utf-8")
    with pytest.raises(BrokerDataError, match="symbol"):
        load_btc_spec(path)


def test_spec_loader_rejects_credentials(tmp_path):
    path = tmp_path / SPEC_FILE
    payload = _spec()
    payload["login"] = 123456
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BrokerDataError, match="Credential"):
        load_btc_spec(path)


def test_spec_loader_requires_a_positive_point(tmp_path):
    path = tmp_path / SPEC_FILE
    path.write_text(json.dumps(_spec(symbol={"name": "BTCUSDm", "digits": 2, "point": 0})),
                    encoding="utf-8")
    with pytest.raises(BrokerDataError, match="point size"):
        load_btc_spec(path)


# --- the Phase R1 gate -------------------------------------------------------------------


def test_status_reports_every_missing_export(tmp_path):
    status = phase_r1_status(tmp_path)
    assert status["ready"] is False
    assert set(status["missing"]) == {"spec", "M15", "H1"}
    assert status["gate"].startswith("BLOCKED")


def test_status_is_ready_only_when_all_three_exports_exist(tmp_path):
    (tmp_path / SPEC_FILE).write_text(json.dumps(_spec()), encoding="utf-8")
    _exporter_csv(tmp_path / M15_FILE, M15_ROWS)
    assert phase_r1_status(tmp_path)["missing"] == ["H1"]
    _exporter_csv(tmp_path / H1_FILE, H1_ROWS)
    status = phase_r1_status(tmp_path)
    assert status["ready"] is True
    assert phase_r1_inputs(tmp_path).ready is True


def test_manifest_refuses_to_build_without_real_exports(tmp_path):
    with pytest.raises(BrokerDataError, match="missing: spec, M15, H1"):
        build_phase_r1(tmp_path, tmp_path / "processed", tmp_path / "manifest.json")


def test_manifest_refuses_a_dataset_that_fails_validation(tmp_path):
    (tmp_path / SPEC_FILE).write_text(json.dumps(_spec()), encoding="utf-8")
    broken = list(M15_ROWS) + [M15_ROWS[-1]]          # duplicate timestamp
    _exporter_csv(tmp_path / M15_FILE, broken)
    _exporter_csv(tmp_path / H1_FILE, H1_ROWS)
    with pytest.raises(BrokerDataError, match="failed validation"):
        build_phase_r1(tmp_path, tmp_path / "processed", tmp_path / "manifest.json")


def test_manifest_covers_every_required_fingerprint(tmp_path):
    (tmp_path / SPEC_FILE).write_text(json.dumps(_spec()), encoding="utf-8")
    _exporter_csv(tmp_path / M15_FILE, M15_ROWS)
    _exporter_csv(tmp_path / H1_FILE, H1_ROWS)
    manifest = build_phase_r1(tmp_path, tmp_path / "processed", tmp_path / "manifest.json")
    assert set(manifest["fingerprints"]) == {
        "raw_spec_sha256", "raw_m15_sha256", "raw_h1_sha256",
        "processed_m15_sha256", "processed_h1_sha256",
        "instrument_profile_sha256", "broker_profile_sha256", "manifest_sha256"}
    assert manifest["specification"]["leverage_status"] == "UNVERIFIED"
    assert manifest["specification"]["commission_status"] == "UNVERIFIED"
    assert manifest["alignment"]["matches"] == 1
    assert manifest["raw_files_preserved"] is True
    # Raw inputs are untouched; canonicalization goes to processed/.
    assert (tmp_path / "processed" / "btcusdm_M15.csv").exists()
    assert (tmp_path / M15_FILE).read_text().startswith("timestamp,open")


# --- real repository assets (read-only) ---------------------------------------------------


def test_the_five_real_tick_samples_are_present_and_fingerprinted():
    assets = tick_sample_assets()
    assert len(assets) == 5
    assert [item["sample_id"] for item in assets] == ["s01", "s02", "s03", "s04", "s05"]
    assert all(len(item["sha256"]) == 64 and item["ticks"] > 0 for item in assets)


@pytest.mark.skipif(not REAL_M15.exists(), reason="real Exness M15 export not present")
def test_the_real_exness_m15_export_passes_validation():
    frame = read_broker_ohlcv(REAL_M15, point=POINT)
    report = validate_candles(frame, timeframe="M15")
    assert report["passed"] is True
    assert report["rows"] == 100_180
    assert report["duplicate_timestamps"] == 0
    assert report["invalid_ohlc_rows"] == 0


def test_phase_r1_real_exports_are_present_and_the_gate_is_open():
    """The live gate: all three real MT5 exports now exist."""
    status = phase_r1_status()
    assert status["ready"] is True
    assert status["missing"] == []


@pytest.mark.skipif(not MANIFEST_PATH.exists(), reason="Phase R1 manifest not built")
def test_the_real_phase_r1_manifest_is_clean_and_reconciled():
    """Locks in the ingested broker dataset: both timeframes valid, M15 and H1
    agreeing on every complete four-bar group, and costs still UNVERIFIED."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    assert manifest["symbol"] == "BTCUSDm"
    assert manifest["broker"] == "Exness Technologies Ltd"
    assert manifest["specification"]["point"] == 0.01
    assert manifest["specification"]["contract_size"] == 1.0
    assert manifest["specification"]["leverage_status"] == "UNVERIFIED"
    assert manifest["specification"]["commission_status"] == "UNVERIFIED"
    assert manifest["datasets"]["M15"]["passed"] is True
    assert manifest["datasets"]["H1"]["passed"] is True
    assert manifest["datasets"]["M15"]["rows"] == 100_239
    assert manifest["datasets"]["H1"]["rows"] == 25_158
    assert manifest["alignment"]["mismatches"] == 0
    assert manifest["alignment"]["groups_compared"] == 25_054
    assert len(manifest["external_replay_assets"]["samples"]) == 5
    assert len(manifest["fingerprints"]) == 8


def test_the_raw_exports_are_preserved_byte_for_byte():
    """Ingestion is read-only: the recorded raw fingerprints still match."""
    manifest = json.loads(MANIFEST_PATH.read_text())
    raw = MANIFEST_PATH.parent / "raw"
    assert sha256_file(raw / SPEC_FILE) == manifest["fingerprints"]["raw_spec_sha256"]
    assert sha256_file(raw / M15_FILE) == manifest["fingerprints"]["raw_m15_sha256"]
    assert sha256_file(raw / H1_FILE) == manifest["fingerprints"]["raw_h1_sha256"]
