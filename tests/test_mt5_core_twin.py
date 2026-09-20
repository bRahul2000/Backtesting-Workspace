"""R4 Stage 1/2 — MT5 digital-twin audit export, comparator and EA source checks.

Fixtures are deterministic two-row audit tables built in-memory. They never
claim to be broker data and are never written into data/.
"""
from pathlib import Path

import pandas as pd
import pytest

from tools.check_mt5_core_source import check as static_check
from tools.compare_mt5_core import CLASSES, classify_row, compare, load_audit
from tools.core_audit_schema import (
    AUDIT_COLUMNS, EXACT_TOLERANCE, INDICATOR_TOLERANCE, KEY, ROUNDING_TOLERANCE,
    UNVERIFIED,
)

ROOT = Path(__file__).resolve().parents[1]
EXNESS_M15 = ROOT / "data/exness/btc/phase_r1/processed/btcusdm_M15.csv"


def _blank_row(stamp: str) -> dict:
    row = {column: "" for column in AUDIT_COLUMNS}
    row.update({
        KEY: stamp, "symbol": "BTCUSDm",
        "open": "100.0000000000", "high": "101.0000000000",
        "low": "99.0000000000", "close": "100.5000000000",
        "tick_volume": "10.0000000000",
        "spread_points": "1000.0000000000", "spread_price": "10.0000000000",
        "h1_time_utc": "2026-01-01T00:00:00Z",
        "h1_open": "100.0000000000", "h1_high": "102.0000000000",
        "h1_low": "98.0000000000", "h1_close": "100.5000000000",
        "ema20": "100.2500000000", "ema50": "100.1000000000",
        "atr": "2.0000000000", "rsi": "55.0000000000", "adx": "22.0000000000",
        "plus_di": "25.0000000000", "minus_di": "15.0000000000",
        "body_percent": "0.2500000000",
        "a4_context_pass": "1", "a4_signal_pass": "0", "a4_reject_code": "A4_NO_PULLBACK",
        "a4_in_session": "1", "a4_trades_today": "0",
        "a4_material_below_ema50": "0", "a4_pullback_active": "0",
        "a4_pullback_depth_atr": "0.0000000000", "a4_pullback_bars": "0",
        "t3_regime": "CHOP", "t3_context_pass": "0", "t3_signal_pass": "0",
        "t3_reject_code": "T3_REGIME_NOT_TREND",
        "pending_status": "",
        "commission_status": UNVERIFIED, "swap_status": UNVERIFIED,
        "realized_cost_status": UNVERIFIED,
    })
    return row


def _audit(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=AUDIT_COLUMNS)


def _pair(**mt5_overrides):
    """Two identical audits, with the MT5 side optionally perturbed."""
    base = [_blank_row("2026-01-01T00:00:00Z"), _blank_row("2026-01-01T00:15:00Z")]
    python_audit = _audit([dict(row) for row in base])
    mt5_rows = [dict(row) for row in base]
    if mt5_overrides:
        mt5_rows[1].update(mt5_overrides)
    return python_audit, _audit(mt5_rows)


def _classification(**overrides) -> str:
    python_audit, mt5_audit = _pair(**overrides)
    result = compare(python_audit, mt5_audit)
    assert result["bars_mismatching"] == 1
    return result["first_mismatch"]["classification"]


# --- schema -------------------------------------------------------------------------------


def test_the_schema_has_a_stable_key_and_no_duplicate_columns():
    assert AUDIT_COLUMNS[0] == KEY == "bar_time_utc"
    assert len(AUDIT_COLUMNS) == len(set(AUDIT_COLUMNS))


def test_cost_fields_stay_unverified():
    row = _blank_row("2026-01-01T00:00:00Z")
    assert row["commission_status"] == row["swap_status"] == "UNVERIFIED"
    assert row["realized_cost_status"] == "UNVERIFIED"


def test_loading_rejects_a_missing_column(tmp_path):
    path = tmp_path / "short.csv"
    _audit([_blank_row("2026-01-01T00:00:00Z")]).drop(columns=["atr"]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        load_audit(path, label="MT5")


def test_loading_rejects_duplicate_bars(tmp_path):
    path = tmp_path / "dupe.csv"
    stamp = "2026-01-01T00:00:00Z"
    _audit([_blank_row(stamp), _blank_row(stamp)]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="duplicate"):
        load_audit(path, label="Python")


# --- offline fixture matrix (specification section 15) --------------------------------------


def test_fixture_exact_match():
    python_audit, mt5_audit = _pair()
    result = compare(python_audit, mt5_audit)
    assert result["full_parity"] is True
    assert result["bars_compared"] == 2
    assert result["bars_mismatching"] == 0
    assert result["decision_parity_percent"] == 100.0


def test_fixture_indicator_mismatch():
    assert _classification(ema20="100.9000000000") == "INDICATOR_MISMATCH"


def test_fixture_h1_timestamp_mismatch():
    assert _classification(h1_time_utc="2026-01-01T01:00:00Z") == "H1_ALIGNMENT"


def test_fixture_missing_bar():
    python_audit, mt5_audit = _pair()
    mt5_audit = mt5_audit.iloc[:1]
    result = compare(python_audit, mt5_audit)
    assert result["bars_only_in_python"] == 1
    assert result["mismatch_counts"]["TIMESTAMP_ALIGNMENT"] == 1
    assert result["full_parity"] is False


def test_fixture_signal_mismatch():
    assert _classification(a4_signal_pass="1", signal_side="LONG") == "SIGNAL_MISMATCH"


def test_fixture_entry_mismatch():
    assert _classification(entry_time_utc="2026-01-01T00:15:00Z",
                           entry_price="150.0000000000") == "ENTRY_PRICE_MISMATCH"


def test_fixture_exit_mismatch():
    assert _classification(exit_time_utc="2026-01-01T00:15:00Z",
                           exit_price="90.0000000000",
                           exit_reason="Stop loss") == "EXIT_MISMATCH"


def test_fixture_rounding_only_mismatch():
    """One point on a derived price is reported, never silently matched."""
    python_audit, mt5_audit = _pair()
    python_audit.loc[1, "entry_price"] = "100.0000000000"
    mt5_audit.loc[1, "entry_price"] = "100.0100000000"
    result = compare(python_audit, mt5_audit)
    assert result["first_mismatch"]["classification"] == "ROUNDING_MISMATCH"
    assert result["full_parity"] is False


def test_fixture_data_mismatch_outranks_everything_downstream():
    """A raw OHLC difference explains the cascade, so it is reported first."""
    classification = _classification(high="105.0000000000", ema20="999.0000000000",
                                     a4_signal_pass="1")
    assert classification == "DATA_MISMATCH"


def test_fixture_spread_mismatch():
    assert _classification(spread_points="1500.0000000000",
                           spread_price="15.0000000000") == "SPREAD_MISMATCH"


def test_fixture_context_mismatch():
    assert _classification(a4_reject_code="A4_ADX_FAIL") == "CONTEXT_MISMATCH"


def test_fixture_pending_state_mismatch():
    assert _classification(pending_status="CREATED",
                           pending_trigger="123.0000000000") == "PENDING_STATE_MISMATCH"


def test_every_declared_class_is_reachable_or_documented():
    assert set(CLASSES) >= {
        "DATA_MISMATCH", "TIMESTAMP_ALIGNMENT", "H1_ALIGNMENT", "INDICATOR_MISMATCH",
        "CONTEXT_MISMATCH", "SIGNAL_MISMATCH", "PENDING_STATE_MISMATCH",
        "ENTRY_PRICE_MISMATCH", "SL_MISMATCH", "TP_MISMATCH", "EXIT_MISMATCH",
        "SPREAD_MISMATCH", "ROUNDING_MISMATCH", "UNKNOWN"}


# --- tolerances ----------------------------------------------------------------------------


def test_raw_market_data_must_be_bit_identical():
    """Both sides read the same broker bars, so no OHLC allowance is granted."""
    assert _classification(close="100.5000010000") == "DATA_MISMATCH"


def test_indicator_tolerance_absorbs_float_accumulation_only():
    python_audit, mt5_audit = _pair()
    mt5_audit.loc[1, "ema20"] = f"{100.25 * (1 + INDICATOR_TOLERANCE / 10):.10f}"
    assert compare(python_audit, mt5_audit)["full_parity"] is True


def test_indicator_tolerance_does_not_hide_a_real_port_defect():
    python_audit, mt5_audit = _pair()
    mt5_audit.loc[1, "ema20"] = f"{100.25 * (1 + INDICATOR_TOLERANCE * 100):.10f}"
    assert compare(python_audit, mt5_audit)["full_parity"] is False


def test_tolerances_are_tight_enough_to_be_meaningful():
    assert EXACT_TOLERANCE <= 1e-09
    assert INDICATOR_TOLERANCE <= 1e-06
    assert ROUNDING_TOLERANCE <= 0.01


# --- first-divergence behaviour --------------------------------------------------------------


def test_only_the_first_divergence_is_reported_per_bar():
    python_audit, mt5_audit = _pair(ema20="900.0000000000", rsi="9.0000000000",
                                    a4_reject_code="A4_ADX_FAIL")
    result = compare(python_audit, mt5_audit)
    assert len(result["first_20_mismatches"]) == 1
    assert result["first_mismatch"]["column"] == "ema20"


def test_worst_numeric_differences_are_ranked():
    base = [_blank_row("2026-01-01T00:00:00Z"), _blank_row("2026-01-01T00:15:00Z")]
    python_audit = _audit([dict(row) for row in base])
    rows = [dict(row) for row in base]
    rows[0]["ema20"] = "110.0000000000"
    rows[1]["ema20"] = "200.0000000000"
    result = compare(python_audit, _audit(rows))
    worst = result["worst_numeric_differences"]
    assert worst[0]["delta"] > worst[1]["delta"]


def test_a_missing_mt5_record_is_never_a_match():
    python_audit, mt5_audit = _pair()
    result = compare(python_audit, mt5_audit.iloc[:1])
    assert result["bars_matching"] == 1
    assert result["full_parity"] is False


# --- UTC alignment ---------------------------------------------------------------------------


def test_alignment_key_is_utc_iso8601_with_z():
    python_audit, _ = _pair()
    for stamp in python_audit[KEY]:
        parsed = pd.Timestamp(stamp)
        assert parsed.tzinfo is not None
        assert stamp.endswith("Z")


def test_bars_align_on_the_bar_open_time_not_the_close():
    python_audit, mt5_audit = _pair()
    shifted = mt5_audit.copy()
    shifted[KEY] = ["2026-01-01T00:15:00Z", "2026-01-01T00:30:00Z"]
    result = compare(python_audit, shifted)
    assert result["bars_only_in_python"] == 1
    assert result["bars_only_in_mt5"] == 1


# --- Python audit exporter against real broker data --------------------------------------------


@pytest.mark.skipif(not EXNESS_M15.exists(), reason="Phase R1 dataset not present")
def test_python_audit_export_matches_the_schema_and_the_audited_engine(tmp_path):
    """The exporter verifies its replay against run_universal_backtest and
    raises if they diverge, so a passing export is itself the parity proof."""
    from core.config import BacktestConfig, DatasetRole
    from tools.export_python_core_audit import export

    config = BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD",
        strategy_id="BTC_V3_CORE_V1_FROZEN", timeframe="15m", higher_timeframes=("1h",),
        start_date=pd.Timestamp("2026-01-01", tz="UTC"),
        end_date=pd.Timestamp("2026-02-01", tz="UTC"),
        dataset_role=DatasetRole.PAPER, spread_source="BROKER_NATIVE_PER_BAR")
    audit = export(EXNESS_M15, config, tmp_path / "audit.csv", verify=True)
    assert list(audit.columns) == AUDIT_COLUMNS
    assert len(audit) > 1000
    assert audit[KEY].is_monotonic_increasing
    assert audit[KEY].str.endswith("Z").all()
    assert (audit.symbol == "BTCUSDm").all()
    assert (audit.commission_status == UNVERIFIED).all()
    # Reject codes must be deterministic labels, never free text.
    assert audit.a4_reject_code.str.match(r"^A4_[A-Z0-9_]+$").all()
    assert audit.t3_reject_code.str.match(r"^T3_[A-Z0-9_]+$").all()


@pytest.mark.skipif(not EXNESS_M15.exists(), reason="Phase R1 dataset not present")
def test_an_exported_audit_is_self_consistent_under_the_comparator(tmp_path):
    from core.config import BacktestConfig, DatasetRole
    from tools.export_python_core_audit import export

    config = BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD",
        strategy_id="BTC_V3_CORE_V1_FROZEN", timeframe="15m", higher_timeframes=("1h",),
        start_date=pd.Timestamp("2026-01-01", tz="UTC"),
        end_date=pd.Timestamp("2026-01-15", tz="UTC"),
        dataset_role=DatasetRole.PAPER, spread_source="BROKER_NATIVE_PER_BAR")
    path = tmp_path / "audit.csv"
    export(EXNESS_M15, config, path, verify=True)
    audit = load_audit(path, label="Python")
    assert compare(audit, audit.copy())["full_parity"] is True


# --- MQL5 source checks (not a compile) ---------------------------------------------------------


def test_the_ea_sends_no_orders_anywhere_in_code():
    report = static_check()
    assert report["forbidden_calls"] == []
    assert report["has_execution_guard"] is True


def test_the_ea_defaults_to_audit_only_and_says_so_on_the_chart():
    report = static_check()
    assert report["default_mode_is_audit_only"] is True
    assert report["declares_audit_only_status"] is True


def test_the_ea_log_row_matches_its_header_exactly():
    report = static_check()
    assert report["header_columns"] == len(AUDIT_COLUMNS)
    assert report["row_columns_match_header"] is True


def test_the_ea_evaluates_only_closed_bars_and_stamps_the_core_fingerprint():
    report = static_check()
    assert report["evaluates_only_closed_bars"] is True
    assert report["core_fingerprint_present"] is True


def test_the_ea_source_is_structurally_balanced():
    report = static_check()
    assert report["braces_balanced"] is True
    assert report["parens_balanced"] is True
