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


def test_loading_rejects_duplicate_bars_that_disagree(tmp_path):
    """One bar may not hold two different sets of values.

    Identical repeats are an appended rerun and are collapsed instead; see
    test_a_rerun_that_repeats_every_bar_is_recovered_not_refused.
    """
    path = tmp_path / "dupe.csv"
    stamp = "2026-01-01T00:00:00Z"
    first = _blank_row(stamp)
    _audit([first, dict(first, ema20="1.0")]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="conflicting"):
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
    """A gap INSIDE the MT5 range is a hard failure, wherever it falls."""
    python_audit = _audit([_blank_row("2026-01-01T00:00:00Z"),
                           _blank_row("2026-01-01T00:15:00Z"),
                           _blank_row("2026-01-01T00:30:00Z")])
    mt5_audit = _audit([_blank_row("2026-01-01T00:00:00Z"),
                        _blank_row("2026-01-01T00:30:00Z")])
    result = compare(python_audit, mt5_audit)
    assert result["bars_only_in_python"] == 1
    assert result["mismatch_counts"]["TIMESTAMP_ALIGNMENT"] == 1
    assert result["window_boundary_bars"] == []
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
        "SPREAD_MISMATCH", "ROUNDING_MISMATCH", "WINDOW_BOUNDARY", "UNKNOWN"}


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


def test_an_mt5_only_bar_is_always_a_hard_failure():
    """The twin logging a bar Python never produced is never excusable."""
    python_audit = _audit([_blank_row("2026-01-01T00:00:00Z")])
    mt5_audit = _audit([_blank_row("2026-01-01T00:00:00Z"),
                        _blank_row("2026-01-01T00:15:00Z")])
    result = compare(python_audit, mt5_audit)
    assert result["bars_only_in_mt5"] == 1
    assert result["mismatch_counts"]["TIMESTAMP_ALIGNMENT"] == 1
    assert result["full_parity"] is False


def test_a_decision_free_tail_past_the_last_logged_bar_is_a_boundary():
    """ProcessClosedBar(1) means a run can never log its own final bar.

    The allowance exists only for that: bars strictly after the last MT5 bar
    that carry no signal, pending order, entry or exit.
    """
    python_audit, mt5_audit = _pair()
    result = compare(python_audit, mt5_audit.iloc[:1])
    assert result["bars_matching"] == 1
    assert result["window_boundary_bars"] == ["2026-01-01T00:15:00Z"]
    assert result["unresolved_one_sided_bars"] == []
    assert result["mismatch_counts"]["WINDOW_BOUNDARY"] == 1
    assert result["full_parity"] is True


@pytest.mark.parametrize("column, value", [
    ("signal_side", "LONG"),
    ("signal_setup_id", "BTC_V3_A4_PULLBACK_LONG_FROZEN"),
    ("a4_signal_pass", "1"),
    ("t3_signal_pass", "1"),
    ("pending_status", "CREATED"),
    ("entry_time_utc", "2026-01-01T00:15:00Z"),
    ("exit_time_utc", "2026-01-01T00:15:00Z"),
])
def test_a_trailing_bar_holding_a_decision_is_never_written_off(column, value):
    """The boundary allowance must not swallow an unobserved decision."""
    tail = _blank_row("2026-01-01T00:15:00Z")
    tail[column] = value
    python_audit = _audit([_blank_row("2026-01-01T00:00:00Z"), tail])
    mt5_audit = _audit([_blank_row("2026-01-01T00:00:00Z")])
    result = compare(python_audit, mt5_audit)
    assert result["window_boundary_bars"] == []
    assert result["unresolved_one_sided_bars"] == ["2026-01-01T00:15:00Z"]
    assert result["mismatch_counts"]["TIMESTAMP_ALIGNMENT"] == 1
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
    assert report["header_columns"] == len(AUDIT_COLUMNS) == 76
    assert report["row_columns"] == 76
    assert report["row_columns_match_header"] is True


def test_the_ea_header_matches_the_python_schema_name_for_name_in_order():
    """The strongest schema guarantee: not just 76 columns, the same 76 in the
    same order as tools/core_audit_schema.py."""
    from tools.check_mt5_core_source import SOURCE, header_column_names

    assert header_column_names(SOURCE.read_text(encoding="utf-8")) == AUDIT_COLUMNS
    assert static_check()["header_matches_python_schema"] is True


def test_no_call_exceeds_the_mql5_parameter_limit():
    """MQL5 caps a function at 64 parameters. Passing all 76 audit columns to
    FileWrite is what failed to compile; rows are serialized as one string now."""
    from tools.check_mt5_core_source import SOURCE, file_write_calls

    for call in file_write_calls(SOURCE.read_text(encoding="utf-8")):
        assert len(call) <= 60, f"FileWrite with {len(call)} arguments will not compile"
    assert static_check()["no_oversized_file_write"] is True


def test_the_ea_serializes_rows_as_a_single_escaped_string():
    report = static_check()
    assert report["uses_string_serialization"] is True
    assert report["has_csv_escape"] is True
    assert report["has_csv_join"] is True
    assert report["has_write_audit_header"] is True
    assert report["has_write_audit_row"] is True
    assert report["declares_audit_column_count"] is True


def test_exactly_one_row_terminator_so_a_row_cannot_split():
    """One CsvJoin call site means one line per row: no accidental extra
    FileWrite that would emit a second row or change the delimiter."""
    assert static_check()["single_row_terminator"] is True


def test_the_reader_side_round_trips_escaped_fields(tmp_path):
    """Proves the schema survives what CsvEscape emits: a field containing a
    comma and a quote is quoted and doubled, and reads back unchanged."""
    import csv

    awkward = 'Stop loss (ambiguous, "SL First")'
    row = _blank_row("2026-01-01T00:00:00Z")
    row["exit_reason"] = awkward
    path = tmp_path / "escaped.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(AUDIT_COLUMNS)
        writer.writerow([row[column] for column in AUDIT_COLUMNS])
    reloaded = load_audit(path, label="MT5")
    assert len(reloaded.columns) == 76
    assert reloaded.loc[0, "exit_reason"] == awkward


def test_empty_fields_stay_empty_and_are_not_quoted(tmp_path):
    """Null behaviour is preserved: a blank column reads back as a blank
    string, not as a quoted empty or a NaN."""
    row = _blank_row("2026-01-01T00:00:00Z")
    assert row["entry_price"] == ""
    path = tmp_path / "blank.csv"
    _audit([row]).to_csv(path, index=False)
    reloaded = load_audit(path, label="MT5")
    assert reloaded.loc[0, "entry_price"] == ""
    assert reloaded.loc[0, "exit_reason"] == ""


def test_the_ea_evaluates_only_closed_bars_and_stamps_the_core_fingerprint():
    report = static_check()
    assert report["evaluates_only_closed_bars"] is True
    assert report["core_fingerprint_present"] is True


def test_the_ea_source_is_structurally_balanced():
    report = static_check()
    assert report["braces_balanced"] is True
    assert report["parens_balanced"] is True


# --- R4 Stage 2 parity corrections --------------------------------------------------------
#
# Each test below pins one divergence the first real MT5 audit run exposed, so
# the same class of defect fails here instead of in a two-month parity run.


def test_the_twin_uses_the_frozen_descriptor_s_own_warmup_contract():
    """The EA's warmup constants must evaluate to the Python warmup plan.

    The first MT5 run searched for signals from bar 15 while the Python side
    would not search until 2026-01-09 12:00, so 800+ bars disagreed on context
    and five trades existed on one side only.
    """
    from strategies.universal_catalog import _core_warmup
    from research.v3_l2_trend_pullback_baseline import warmup_plan
    from strategies.btc_v3_a4_pullback_long import frozen_parameters

    report = static_check()
    plan = warmup_plan(frozen_parameters(), pd.Timestamp("2026-01-01", tz="UTC"))
    assert report["warmup_m15_bars"] == plan.m15_bars
    assert report["warmup_h1_bars"] == plan.confirmed_h1_bars
    assert report["honours_warmup_window"] is True
    assert report["emits_before_window_codes"] is True
    # The formula the EA implements, evaluated here against the real resolver.
    start = pd.Timestamp("2026-01-01", tz="UTC")
    h1_ready = start.ceil("h") + pd.Timedelta(hours=report["warmup_h1_bars"])
    m15_ready = start + (report["warmup_m15_bars"] - 1) * pd.Timedelta(minutes=15)
    assert max(h1_ready, m15_ready) == _core_warmup(start)


def test_the_twin_clears_the_pullback_when_the_session_or_daily_cap_closes():
    """btc_v3_l2_trend_pullback_long resets on both branches; so must the EA.

    Without it a pullback opened at 21:45 survived the 22:00 session close and
    produced confirmation decisions the frozen strategy never made.
    """
    report = static_check()
    assert report["resets_pullback_out_of_session"] is True
    assert report["resets_pullback_at_daily_cap"] is True


def test_directional_indices_are_published_before_adx_is_seeded():
    """pine_indicators.DMI returns +DI/-DI while adx is still None."""
    from engine.models import Candle
    from strategies.pine_indicators import DMI

    dmi = DMI(14, 14)
    seen_di_without_adx = False
    price = 100.0
    for index in range(40):
        price += 1.0 if index % 3 else -0.5
        value = dmi.update(Candle(pd.Timestamp("2026-01-01", tz="UTC"), price,
                                  price + 1, price - 1, price, 10.0))
        if value.plus_di is not None and value.adx is None:
            seen_di_without_adx = True
    assert seen_di_without_adx, "DI and ADX would become available on the same bar"
    assert static_check()["publishes_di_before_adx"] is True


def test_realized_r_divides_by_the_risk_budget_not_the_capped_loss():
    """Position.initial_risk is the budget and survives the leverage cap.

    Dividing by quantity*distance instead reported -1.019R for a stop that the
    audited engine scores -0.937R.
    """
    from engine.execution import open_position
    from engine.models import (BacktestSettings, Direction, RiskCalculation,
                               RiskMode, SameBarResolution, Signal)

    settings = BacktestSettings(
        starting_balance=10_000.0, risk_mode=RiskMode.PERCENT_EQUITY,
        risk_percent=0.25, fixed_risk_dollars=0.0, risk_reward_ratio=3.0,
        commission_percent=0.0, slippage_percent=0.0,
        same_bar_resolution=SameBarResolution.SL_FIRST,
        risk_calculation=RiskCalculation.ESTIMATED_TOTAL_STOP_LOSS,
        max_leverage=1.0, min_quantity=0.0)
    stamp = pd.Timestamp("2026-01-01", tz="UTC")
    # A stop 0.2% away needs far more notional than 1x leverage allows.
    position = open_position(Signal(Direction.LONG, stop_loss=99_800.0),
                             stamp, stamp, 100_000.0, 0, 1, 10_000.0, settings)
    assert position.leverage_capped is True
    budget = 10_000.0 * 0.25 / 100
    assert position.initial_risk == pytest.approx(budget)
    assert position.estimated_stop_loss < position.initial_risk
    assert static_check()["planned_risk_is_budget"] is True


def test_both_halves_of_the_twin_share_one_reject_vocabulary():
    """A code only one side can emit mismatches on every bar that reaches it.

    Five A4 codes existed only in MQL5, which is why 44 post-warmup bars
    disagreed on a4_reject_code while agreeing on every trade.
    """
    report = static_check()
    assert report["reject_codes_only_in_mt5"] == []
    assert report["reject_codes_only_in_python"] == []
    assert report["reject_codes_match_python"] is True


def test_carried_state_is_compared_before_the_codes_it_explains():
    """A stale pullback must be reported as the cause, not its symptom."""
    from tools.compare_mt5_core import CHECKS

    order = [label for label, _, _ in CHECKS]
    assert order.index("STATE_MISMATCH") < order.index("CONTEXT_MISMATCH")
    assert order.index("CONTEXT_MISMATCH") < order.index("SIGNAL_MISMATCH")
    row = _classification(a4_pullback_active="1", a4_reject_code="A4_BODY_TOO_SMALL")
    assert row == "STATE_MISMATCH"


def test_state_and_level_columns_are_actually_compared():
    """Every schema column belongs to exactly one check, or parity is partial."""
    from tools.compare_mt5_core import CHECKS, H1_TIME_COLUMN
    from tools.core_audit_schema import COST_COLUMNS

    covered = {column for _, columns, _ in CHECKS for column in columns}
    covered |= {H1_TIME_COLUMN, KEY, "symbol"} | set(COST_COLUMNS)
    assert set(AUDIT_COLUMNS) - covered == set()


def test_the_pending_lifecycle_vocabulary_is_shared():
    """Python emitted only CREATED/ACTIVE while MT5 also emitted FILLED/EXPIRED."""
    import re
    from tools.core_audit_schema import PENDING_STATUSES

    exporter = (ROOT / "tools/export_python_core_audit.py").read_text()
    source = (ROOT / "mt5" / "BTC_V3_Core_V1.mq5").read_text()
    for status in ("CREATED", "FILLED", "EXPIRED", "ACTIVE"):
        assert status in PENDING_STATUSES
        assert re.search(rf'"{status}"', exporter), f"{status} missing from the exporter"
        assert re.search(rf'"{status}"', source), f"{status} missing from the EA"


# --- rerun hygiene ------------------------------------------------------------------------
#
# A rerun that appended into the existing common-files log doubled a 5,663-bar
# audit to 11,326 rows, and the stale .ex5 that produced it was invisible from
# the audit alone.


def test_a_rerun_that_repeats_every_bar_is_recovered_not_refused(tmp_path, capsys):
    rows = [_blank_row("2026-01-01T00:00:00Z"), _blank_row("2026-01-01T00:15:00Z")]
    doubled = pd.DataFrame(rows + rows, columns=AUDIT_COLUMNS)
    path = tmp_path / "doubled.csv"
    doubled.to_csv(path, index=False)

    frame = load_audit(path, label="MT5")
    assert len(frame) == 2
    assert frame.attrs["duplicates_collapsed"] == 2
    assert "collapsed 2 identical repeated bars" in capsys.readouterr().out


def test_two_different_runs_in_one_file_are_still_refused(tmp_path):
    first = _blank_row("2026-01-01T00:00:00Z")
    second = dict(first, close="100.6000000000")
    path = tmp_path / "conflicting.csv"
    pd.DataFrame([first, second], columns=AUDIT_COLUMNS).to_csv(path, index=False)

    with pytest.raises(ValueError, match="conflicting rows"):
        load_audit(path, label="MT5")


def test_the_ea_starts_a_fresh_audit_per_run_by_default():
    """FileOpen truncates without FILE_READ, so one run is one audit."""
    source = (ROOT / "mt5" / "BTC_V3_Core_V1.mq5").read_text()
    assert "input bool          InpAppendLog       = false;" in source
    open_log = source.split("bool OpenLog()")[1].split("\n  }")[0]
    assert "FILE_WRITE|FILE_TXT|FILE_ANSI" in open_log.replace(" ", "")
    # FILE_READ is only added when appending was explicitly requested.
    assert "if(InpAppendLog)      flags |= FILE_READ;" in open_log
    assert open_log.count("FileSeek(g_file,0,SEEK_END)") == 1


def test_the_ea_prints_a_build_banner_so_a_stale_binary_is_visible():
    """MetaTrader runs the .ex5; an un-recompiled source change is silent."""
    source = (ROOT / "mt5" / "BTC_V3_Core_V1.mq5").read_text()
    assert "#define TWIN_BUILD" in source
    assert "__DATETIME__" in source
    assert 'Print("Twin build ",TWIN_BUILD' in source


# --- pending-order cancellation -----------------------------------------------------------
#
# The certification run agreed on every indicator, gate, signal and trade but
# kept a pending order alive for one bar after the frozen strategy had cancelled
# it. Letting an order expire is not the same as withdrawing it: on another
# price path the twin would fill an order the frozen Core had already pulled.


def test_the_frozen_core_really_does_cancel_on_invalidated_context():
    """Guards the premise: A4 withdraws its own order when context breaks."""
    from engine.models import CancelPendingOrder
    from strategies.btc_v3_a4_pullback_long import frozen_parameters
    import inspect
    from strategies import btc_v3_l2_trend_pullback_long as l2

    body = inspect.getsource(l2.BtcV3L2TrendPullbackLong.on_candle)
    pending_branch = body.split("if state.pending_order is not None:")[1]
    pending_branch = pending_branch.split("if state.position is not None:")[0]
    for clause in ("UTC trading session ended.",
                   "Maximum filled trades per UTC day reached.",
                   "V3-L2 bullish trend context invalidated."):
        assert clause in pending_branch
    assert CancelPendingOrder is not None
    assert frozen_parameters().min_adx == 18.0


def test_only_the_owning_child_may_cancel_and_t3_never_cancels_on_context():
    """btc_v3_core_v1 forwards a cancellation only from the order's owner."""
    import inspect
    from strategies import btc_v3_core_v1, btc_v3_t3_breakout_short as t3

    core = inspect.getsource(btc_v3_core_v1.BtcV3CoreV1Frozen.on_candle)
    assert "if pending.setup_id == A4_SETUP_ID:" in core
    assert "if pending.setup_id == T3_SETUP_ID:" in core

    body = inspect.getsource(t3.BtcV3T3BreakoutShortFrozen.on_candle)
    assert "UTC trading session ended." in body
    assert "Maximum filled trades per UTC day reached." in body
    # T3 has no context-invalidation cancel; the asymmetry is deliberate.
    assert "context invalidated" not in body

    report = static_check()
    assert report["implements_pending_cancellation"] is True
    assert report["cancellation_respects_order_ownership"] is True
    assert report["only_a4_cancels_on_context"] is True
    assert report["emits_cancelled_status"] is True


def test_a_cancelled_order_is_not_reported_as_merely_expired():
    python_row = _blank_row("2026-01-01T00:00:00Z")
    python_row["pending_status"] = "CANCELLED"
    mt5_row = dict(python_row, pending_status="ACTIVE")
    result = classify_row(pd.Series(python_row), pd.Series(mt5_row))
    assert result["classification"] == "PENDING_STATE_MISMATCH"
    assert result["column"] == "pending_status"


def test_every_created_pending_reaches_a_terminal_state(tmp_path):
    """CREATED == FILLED + EXPIRED + CANCELLED + still open at the end.

    A pending order that simply stops being mentioned is a lost order, and the
    ledger is what makes that visible.
    """
    from tools.core_audit_schema import PENDING_STATUSES

    audit = ROOT / "data/exness/btc/r4/python_core_audit_20260101_20260301.csv"
    if not audit.exists():
        pytest.skip("parity export not present in this checkout")
    frame = load_audit(audit, label="Python")
    counts = frame.pending_status.value_counts()
    assert set(counts.index) - {""} <= set(PENDING_STATUSES)
    terminal = sum(int(counts.get(state, 0)) for state in ("FILLED", "EXPIRED", "CANCELLED"))
    open_at_end = frame.pending_status.iloc[-1] in ("CREATED", "ACTIVE")
    assert int(counts.get("CREATED", 0)) == terminal + int(open_at_end)


# --- whole-trade pairing ------------------------------------------------------------------
#
# The second certification window crosses a real data gap. A segment reset
# abandons the open position, leaving an entry with no exit, and from that point
# on entries and exits can no longer be zipped by position.


def _entry(stamp, price="100.0"):
    row = _blank_row(stamp)
    row.update({"entry_time_utc": stamp, "entry_price": price,
                "entry_stop": "99.0", "entry_target": "103.0"})
    return row


def _exit(stamp, price="103.0", r="3.0"):
    row = _blank_row(stamp)
    row.update({"exit_time_utc": stamp, "exit_price": price,
                "exit_reason": "Take profit", "realized_r": r})
    return row


def _trades_of(frame):
    from tools.compare_mt5_core import _trade_table
    return _trade_table(frame)


def test_an_abandoned_position_is_recorded_not_silently_dropped():
    """A new entry while one is open means the previous position was lost."""
    frame = _audit([_entry("2026-01-01T00:00:00Z"),
                    _entry("2026-01-01T00:15:00Z", price="200.0"),
                    _exit("2026-01-01T00:30:00Z")])
    trades, orphans = _trades_of(frame)
    assert len(trades) == 2
    assert trades[0][1] == "100.0" and trades[0][-1] is None   # abandoned
    assert trades[1][1] == "200.0" and trades[1][-1] == "3.0"  # closed
    assert orphans == 0


def test_a_trade_still_open_at_the_end_of_the_run_is_recorded():
    frame = _audit([_entry("2026-01-01T00:00:00Z")])
    trades, _ = _trades_of(frame)
    assert len(trades) == 1 and trades[0][-1] is None


def test_an_entry_and_exit_on_the_same_bar_is_one_trade():
    row = _entry("2026-01-01T00:00:00Z")
    row.update({"exit_time_utc": "2026-01-01T00:00:00Z", "exit_price": "99.0",
                "exit_reason": "Stop loss", "realized_r": "-1.0"})
    trades, orphans = _trades_of(_audit([row]))
    assert len(trades) == 1 and trades[0][-1] == "-1.0" and orphans == 0


def test_an_exit_with_no_open_entry_is_surfaced():
    trades, orphans = _trades_of(_audit([_exit("2026-01-01T00:00:00Z")]))
    assert trades == [] and orphans == 1


def test_matching_sides_reach_full_trade_parity_despite_an_abandoned_position():
    """Regression: positional zipping under-counted a perfectly matching run.

    Both sides abandon the same position at a segment reset. Entries and exits
    then differ in length, and zipping them by index reported a false mismatch.
    """
    rows = [_entry("2026-01-01T00:00:00Z"),
            _entry("2026-01-01T00:15:00Z", price="200.0"),
            _exit("2026-01-01T00:30:00Z")]
    result = compare(_audit([dict(r) for r in rows]), _audit([dict(r) for r in rows]))
    assert result["python_trades"] == result["mt5_trades"] == 2
    assert result["python_unclosed_trades"] == result["mt5_unclosed_trades"] == 1
    assert result["full_trade_matches"] == 2
    assert result["full_trade_parity"] is True


def test_a_differing_abandoned_position_still_fails():
    """The allowance must not make unclosed trades unverified."""
    theirs = [_entry("2026-01-01T00:00:00Z"),
              _entry("2026-01-01T00:15:00Z", price="200.0"),
              _exit("2026-01-01T00:30:00Z")]
    mine = [dict(r) for r in theirs]
    mine[0] = _entry("2026-01-01T00:00:00Z", price="123.0")
    result = compare(_audit(mine), _audit(theirs))
    assert result["full_trade_matches"] == 1
    assert result["full_trade_parity"] is False
