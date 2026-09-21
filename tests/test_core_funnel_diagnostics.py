"""Diagnostic-only pre-setup funnel and X-Ray for the frozen BTC V3 Core v1.

The whole point of this instrumentation is that it is inert. These tests exist
to prove that: the frozen Core's trade list, prices, R-multiples and headline
metrics must be bit-identical with instrumentation on and off, and the gate
verdicts must agree with the action the frozen Core actually returned on every
single bar. If either property breaks, the funnel is not evidence — it is a
second, divergent implementation of the strategy.
"""
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pandas as pd
import pytest

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from engine.models import Candle, ExecutionState
from services import market_datasets as md
from strategies import btc_v3_core_diagnostics as diag
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.btc_v3_a4_pullback_long import SETUP_ID as A4_SETUP_ID
from strategies.btc_v3_t3_breakout_short import TREND_SETUP_ID as T3_SETUP_ID
from strategies.registry import discover_builtin_strategies
from utils.data_validation import load_ohlcv_csv
from ui.universal_workspace import _reject_period_table

ROOT = Path(__file__).resolve().parents[1]
CORE = "BTC_V3_CORE_V1_FROZEN"
START = pd.Timestamp("2026-01-01", tz="UTC")
END = pd.Timestamp("2026-03-01", tz="UTC")

METRIC_FIELDS = (
    "total_trades", "total_entries", "trades_per_month", "win_rate", "profit_factor",
    "average_r", "pnl", "max_drawdown_percent", "max_losing_streak",
)


def _config(entry: md.MarketDataset, **over) -> BacktestConfig:
    values = dict(
        instrument=entry.instrument, broker_profile="EXNESS_STANDARD",
        strategy_id=CORE, timeframe=entry.timeframe, higher_timeframes=("1h",),
        start_date=START, end_date=END, dataset_role=DatasetRole.DEVELOPMENT,
        risk_per_trade_percent=0.25,
        spread=0.0 if entry.carries_per_bar_spread else 10.0,
        spread_source=entry.spread_source, data_source=entry.key)
    values.update(over)
    return BacktestConfig(**values)


@pytest.fixture(scope="module")
def exness() -> md.MarketDataset:
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    if not entry.exists:
        pytest.skip(f"validated Exness dataset missing at {entry.path}")
    return entry


@pytest.fixture(scope="module")
def instrumented(exness, tmp_path_factory):
    path = tmp_path_factory.mktemp("funnel") / "on.sqlite3"
    return run_universal_backtest(exness.path, _config(exness), ledger_path=path)


@pytest.fixture(scope="module")
def uninstrumented(exness, tmp_path_factory):
    """The same run with the observer removed from the registry."""
    saved = dict(diag.INSTRUMENTED_STRATEGIES)
    diag.INSTRUMENTED_STRATEGIES.clear()
    try:
        path = tmp_path_factory.mktemp("funnel") / "off.sqlite3"
        return run_universal_backtest(exness.path, _config(exness), ledger_path=path)
    finally:
        diag.INSTRUMENTED_STRATEGIES.update(saved)


# --- the instrumentation must not change a single number ---------------------


def test_instrumentation_leaves_the_trade_list_identical(instrumented, uninstrumented):
    assert uninstrumented.core_funnel == {}, "control run must be uninstrumented"
    assert instrumented.core_funnel.get("available") is True
    assert len(instrumented.trade_log) == len(uninstrumented.trade_log)
    assert instrumented.trade_log == uninstrumented.trade_log


@pytest.mark.parametrize("field", (
    "direction", "setup_id", "entry_time", "exit_time", "entry_price", "exit_price",
    "stop_loss", "take_profit", "quantity", "pnl", "realized_r", "exit_reason",
))
def test_every_trade_field_survives_instrumentation(instrumented, uninstrumented, field):
    if not instrumented.trade_log:
        pytest.skip("no trades in this window")
    if field not in instrumented.trade_log[0]:
        pytest.skip(f"{field} is not part of the trade log schema")
    assert ([row[field] for row in instrumented.trade_log]
            == [row[field] for row in uninstrumented.trade_log])


@pytest.mark.parametrize("field", METRIC_FIELDS)
def test_every_headline_metric_survives_instrumentation(instrumented, uninstrumented, field):
    assert getattr(instrumented, field) == getattr(uninstrumented, field)


def test_direction_and_period_statistics_survive_instrumentation(instrumented, uninstrumented):
    assert asdict(instrumented.long_statistics) == asdict(uninstrumented.long_statistics)
    assert asdict(instrumented.short_statistics) == asdict(uninstrumented.short_statistics)
    assert instrumented.yearly_statistics == uninstrumented.yearly_statistics
    assert instrumented.monthly_statistics == uninstrumented.monthly_statistics


def test_order_events_and_equity_curve_survive_instrumentation(instrumented, uninstrumented):
    assert (instrumented.execution_diagnostics["order_events"]
            == uninstrumented.execution_diagnostics["order_events"])
    assert instrumented.equity_curve == uninstrumented.equity_curve


# --- the observer returns the frozen Core's own action ----------------------


def _candles(entry, limit: int = 4000) -> list[Candle]:
    frame = load_ohlcv_csv(entry.path)
    frame = frame.loc[frame.timestamp.between(START, END)].head(limit)
    return [Candle(row.timestamp, row.open, row.high, row.low, row.close, row.volume)
            for row in frame.itertuples(index=False)]


def test_observer_returns_the_frozen_action_on_every_bar(exness):
    """Drive both with an identical flat execution state and compare actions."""
    candles = _candles(exness)
    bare, observed = BtcV3CoreV1Frozen(), diag.CoreFunnelObserver(BtcV3CoreV1Frozen())
    for strategy in (bare, observed):
        strategy.reset()
        strategy.on_backtest_window(candles[0].timestamp, None)
    for candle in candles:
        state = ExecutionState(10_000.0, None, None, None, None)
        bare.on_execution_state(state)
        observed.on_execution_state(state)
        assert observed.on_candle(candle) == bare.on_candle(candle), candle.timestamp
    assert observed.report.children["A4"].entered["bars_evaluated"] == len(candles)


def test_the_run_reports_no_integrity_mismatch(instrumented):
    integrity = instrumented.core_funnel["integrity"]
    assert integrity["bars_cross_checked"] > 1000
    assert integrity.get("signal_mismatches", 0) == 0
    assert integrity.get("price_mismatches", 0) == 0


def test_shadow_indicators_reproduce_the_frozen_rsi_and_adx(exness, monkeypatch):
    """RSI/DMI are recomputed and discarded per bar, so the observer shadows them."""
    from strategies import pine_indicators

    seen: dict[int, list] = {}
    real_rsi, real_dmi = pine_indicators.RSI.update, pine_indicators.DMI.update

    def record_rsi(self, close):
        value = real_rsi(self, close)
        seen.setdefault(id(self), []).append(value)
        return value

    def record_dmi(self, candle):
        value = real_dmi(self, candle)
        seen.setdefault(id(self), []).append(value.adx)
        return value

    monkeypatch.setattr(pine_indicators.RSI, "update", record_rsi)
    monkeypatch.setattr(pine_indicators.DMI, "update", record_dmi)

    candles = _candles(exness, limit=1500)
    observer = diag.CoreFunnelObserver(BtcV3CoreV1Frozen())
    observer.reset()
    observer.on_backtest_window(candles[0].timestamp, None)
    for candle in candles:
        observer.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
        observer.on_candle(candle)

    a4 = observer.core.a4
    assert seen[id(observer._rsi)] == seen[id(a4.rsi)]
    assert seen[id(observer._dmi)] == seen[id(a4.dmi)]
    assert observer._fast.value == a4.fast.value
    assert observer._slow.value == a4.slow.value
    assert observer._h1.confirmed == a4.h1.confirmed


# --- the funnel is internally consistent ------------------------------------


@pytest.mark.parametrize("child", ("A4", "T3"))
def test_gates_are_strictly_sequential(instrumented, child):
    """Whatever passes a gate is exactly what enters the next one."""
    gates = instrumented.core_funnel["children"][child]["gates"]
    for earlier, later in zip(gates, gates[1:]):
        assert later["entered"] == earlier["passed"], (earlier["gate"], later["gate"])
        assert earlier["failed"] == earlier["entered"] - earlier["passed"]


@pytest.mark.parametrize("child", ("A4", "T3"))
def test_reject_codes_account_for_every_rejected_bar(instrumented, child):
    node = instrumented.core_funnel["children"][child]
    failures = sum(row["failed"] for row in node["gates"])
    assert sum(node["reject_codes"].values()) == failures


@pytest.mark.parametrize("child", ("A4", "T3"))
@pytest.mark.parametrize("field", ("reject_monthly", "reject_yearly"))
def test_period_breakdowns_reconcile_with_the_totals(instrumented, child, field):
    node = instrumented.core_funnel["children"][child]
    pooled: Counter = Counter()
    for counts in node[field].values():
        pooled.update(counts)
    assert dict(pooled) == node["reject_codes"]


@pytest.mark.parametrize("child,setup_id", (("A4", A4_SETUP_ID), ("T3", T3_SETUP_ID)))
def test_setups_detected_match_the_orders_the_engine_created(instrumented, child, setup_id):
    node = instrumented.core_funnel["children"][child]
    detected = next(row["passed"] for row in node["gates"] if row["gate_key"] == "setup_detected")
    assert detected == node["lifecycle"].get("order_created", 0)
    assert node["setup_id"] == setup_id


def test_child_setups_and_fills_reconcile_with_the_run_total(instrumented):
    children = instrumented.core_funnel["children"].values()
    assert sum(node["lifecycle"].get("filled", 0) for node in children) == instrumented.total_entries
    for node in children:
        lifecycle = node["lifecycle"]
        terminal = sum(lifecycle.get(state, 0)
                       for state in ("filled", "expired", "cancelled", "active_at_end"))
        assert terminal == lifecycle.get("order_created", 0)


def test_the_funnel_covers_every_evaluated_bar(instrumented):
    total = instrumented.core_funnel["total_bars"]
    assert total > 1000
    for node in instrumented.core_funnel["children"].values():
        assert node["gates"][0]["entered"] == total
        assert node["gates"][0]["percent_of_all_bars"] == 100.0


def test_conversion_is_reported_against_the_prior_gate(instrumented):
    """A constant 100% would mean the metric is measuring nothing."""
    for node in instrumented.core_funnel["children"].values():
        gates = node["gates"]
        assert gates[0]["conversion_from_prior_percent"] is None
        for earlier, later in zip(gates, gates[1:]):
            if earlier["passed"]:
                assert later["conversion_from_prior_percent"] == pytest.approx(
                    100 * later["passed"] / earlier["passed"], abs=1e-3)
        assert any(row["conversion_from_prior_percent"] not in (None, 100.0) for row in gates)


# --- the gates mirror the frozen source -------------------------------------


def test_a4_gate_order_matches_the_frozen_source():
    assert [gate.key for gate in diag.A4_GATES] == [
        "bars_evaluated", "warmup_window", "no_pending_order", "no_open_position",
        "in_session", "daily_cap", "indicators_ready", "h1_regime_bullish",
        "m15_ema_stack", "adx_minimum", "normalized_h1_slope", "ema50_proximity",
        "pullback_depth_ok", "pullback_confirmable", "confirmation_candle",
        "stop_distance_valid", "setup_detected",
    ]


def test_t3_gate_order_matches_the_frozen_source():
    """T3 checks session and the daily cap before execution state; A4 does not."""
    assert [gate.key for gate in diag.T3_GATES] == [
        "bars_evaluated", "warmup_window", "in_session", "daily_cap",
        "no_open_position", "no_pending_order", "indicators_ready",
        "h1_regime_confirmed", "h1_separation", "adx_minimum", "bearish_alignment",
        "shorts_enabled", "structure_breakdown", "candle_bearish", "body_minimum",
        "range_band", "rsi_band", "extension_limit", "stop_distance_valid",
        "setup_detected",
    ]


def test_every_reject_code_is_prefixed_with_its_component(instrumented):
    for child, node in instrumented.core_funnel["children"].items():
        assert all(code.startswith(f"{child}_") for code in node["reject_codes"])


def test_the_two_children_trade_opposite_directions(instrumented):
    children = instrumented.core_funnel["children"]
    assert children["A4"]["direction"] == "LONG"
    assert children["T3"]["direction"] == "SHORT"
    assert instrumented.core_funnel["core_counters"].get("both_children_signalled", 0) == 0


# --- X-Ray -------------------------------------------------------------------


def test_xray_emits_structured_rule_evaluations_for_the_frozen_core(instrumented):
    rows = instrumented.xray_diagnostics
    assert rows, "frozen Core must now emit X-Ray evaluations"
    components = {row["component"] for row in rows}
    assert components == {A4_SETUP_ID, T3_SETUP_ID}
    for row in rows:
        assert row["strategy_id"] == CORE
        assert row["result"] in {"PASS", "FAIL"}
        assert row["rule"] and row["description"]
    assert {row["rule"] for row in rows} >= {
        "a4_confirmation_body_percent", "t3_structure_breakdown", "t3_range_atr"}


def test_xray_failure_codes_are_funnel_reject_codes(instrumented):
    known = set()
    for node in instrumented.core_funnel["children"].values():
        known.update(node["reject_codes"])
    for row in instrumented.xray_diagnostics:
        if row["result"] == "FAIL" and row["reason_code"]:
            assert row["reason_code"] in known


def test_xray_output_is_capped(exness):
    candles = _candles(exness)
    observer = diag.CoreFunnelObserver(BtcV3CoreV1Frozen(), xray_limit=25)
    observer.reset()
    observer.on_backtest_window(candles[0].timestamp, None)
    for candle in candles:
        observer.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
        observer.on_candle(candle)
    assert len(observer.xray_evaluations) <= 25 + len(diag.A4_GATES)
    assert observer.report.xray_truncated is True


def test_the_xray_cap_is_enforced_per_run_not_per_segment(exness, tmp_path, monkeypatch):
    """Each data segment builds its own observer, so a per-segment cap would let a
    multi-segment run write N x the cap into the experiment ledger."""
    from core.adapters import audited_engine

    monkeypatch.setattr(audited_engine, "XRAY_ROW_LIMIT", 40)
    result = audited_engine.run_universal_backtest(
        exness.path, _config(exness), ledger_path=tmp_path / "capped.sqlite3")
    assert len(result.xray_diagnostics) == 40
    assert result.core_funnel["xray_truncated"] is True


# --- wiring ------------------------------------------------------------------


def test_only_the_frozen_core_is_instrumented():
    assert set(diag.INSTRUMENTED_STRATEGIES) == {CORE}
    other = object()
    assert diag.instrument(other, "BTC_V3_A4_PULLBACK_LONG_FROZEN") is other
    core = BtcV3CoreV1Frozen()
    assert isinstance(diag.instrument(core, CORE), diag.CoreFunnelObserver)


def test_the_observer_refuses_any_other_strategy():
    with pytest.raises(TypeError):
        diag.CoreFunnelObserver(object())


def test_the_observer_forwards_attribute_reads_to_the_frozen_core():
    core = BtcV3CoreV1Frozen()
    observer = diag.CoreFunnelObserver(core)
    assert observer.a4 is core.a4
    assert observer.t3 is core.t3
    assert observer.diagnostics is core.diagnostics


def test_reports_merge_across_data_segments():
    left, right = diag.CoreFunnelReport(), diag.CoreFunnelReport()
    stamp = pd.Timestamp("2026-01-05T10:00:00Z")
    left.children["A4"].record(4, "A4_OUTSIDE_SESSION", stamp)
    right.children["A4"].record(4, "A4_OUTSIDE_SESSION", pd.Timestamp("2026-02-05T10:00:00Z"))
    right.integrity["bars_cross_checked"] += 3
    left.merge(right)
    assert left.children["A4"].reject_codes["A4_OUTSIDE_SESSION"] == 2
    assert sorted(left.children["A4"].reject_monthly) == ["2026-01", "2026-02"]
    assert left.children["A4"].reject_yearly["2026"]["A4_OUTSIDE_SESSION"] == 2
    assert left.integrity["bars_cross_checked"] == 3


def test_lifecycle_is_taken_from_the_engines_own_order_events():
    from engine.models import Direction, OrderEvent

    stamp = pd.Timestamp("2026-01-05T10:00:00Z")
    events = [
        OrderEvent(stamp, stamp, Direction.SHORT, 1.0, 2.0, stamp, 3, "triggered",
                   None, stamp, 1.0, T3_SETUP_ID),
        OrderEvent(stamp, stamp, Direction.SHORT, 1.0, 2.0, stamp, 3, "expired",
                   "gone", None, None, T3_SETUP_ID),
        OrderEvent(stamp, stamp, Direction.LONG, 1.0, 0.5, stamp, 3, "cancelled",
                   "why", None, None, A4_SETUP_ID),
        OrderEvent(stamp, stamp, Direction.LONG, 1.0, 0.5, stamp, 3, "triggered",
                   None, stamp, 1.0, "SOMETHING_ELSE"),
    ]
    lifecycle = diag.lifecycle_from_order_events(events)
    assert lifecycle["T3"] == Counter({"order_created": 2, "filled": 1, "expired": 1})
    assert lifecycle["A4"] == Counter({"order_created": 1, "cancelled": 1})


def test_an_uninstrumented_strategy_produces_no_funnel(tmp_path):
    entry = md.dataset(md.EXNESS_BTCUSDM_M15)
    if not entry.exists:
        pytest.skip("validated Exness dataset missing")
    result = run_universal_backtest(
        entry.path, _config(entry, strategy_id="BTC_V3_T3_BREAKOUT_SHORT_FROZEN"),
        ledger_path=tmp_path / "plain.sqlite3")
    assert result.core_funnel == {}


# --- UI helpers --------------------------------------------------------------


def test_period_table_survives_an_empty_or_unknown_code_selection():
    """An empty multiselect is a normal state; it must not blank the page."""
    child = {"reject_monthly": {"2026-01": {"A4_OUTSIDE_SESSION": 3},
                                "2026-02": {"A4_DAILY_TRADE_CAP": 1}}}
    full = _reject_period_table(child, "reject_monthly", ["A4_OUTSIDE_SESSION"])
    assert list(full.index) == ["2026-01", "2026-02"]
    assert full.loc["2026-01", "total rejects"] == 3
    assert _reject_period_table(child, "reject_monthly", []).empty is False
    assert _reject_period_table(child, "reject_monthly", ["NOPE"]).empty is False
    assert _reject_period_table({}, "reject_monthly", []).empty is True


# --- the frozen strategies are untouched -------------------------------------


def test_protected_strategy_fingerprints_are_unchanged():
    expected = {
        "BTC_V3_A4_PULLBACK_LONG_FROZEN": "55fedf85",
        "BTC_V3_T3_BREAKOUT_SHORT_FROZEN": "4c4ab845",
        "BTC_V3_CORE_V1_FROZEN": "631374d5",
    }
    registry = discover_builtin_strategies()
    for strategy_id, prefix in expected.items():
        assert registry.get(strategy_id).metadata.strategy_fingerprint.startswith(prefix)


@pytest.mark.parametrize("module", (
    "btc_v3_core_v1.py", "btc_v3_a4_pullback_long.py", "btc_v3_t3_breakout_short.py",
    "btc_v3_l2_trend_pullback_long.py",
))
def test_frozen_sources_never_reference_their_own_instrumentation(module):
    """Diagnostics observe from outside. A frozen file importing them would make
    the instrumentation part of the decision path and change its fingerprint."""
    source = (ROOT / "strategies" / module).read_text()
    assert "btc_v3_core_diagnostics" not in source
    assert "CoreFunnelObserver" not in source


@pytest.mark.parametrize("module,digest", (
    ("btc_v3_core_v1.py", "631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd"),
    ("btc_v3_a4_pullback_long.py", "55fedf8564537549f076e726916286256f504749283a2b587b3cdc964926f3d9"),
    ("btc_v3_t3_breakout_short.py", "4c4ab845852ff973530f30ebee86061ea72bd29d68ff6165970dd5a9efde7910"),
))
def test_frozen_source_files_are_byte_for_byte_unchanged(module, digest):
    """The certified fingerprint is the SHA-256 of the file, not of the class body."""
    assert sha256((ROOT / "strategies" / module).read_bytes()).hexdigest() == digest


# --- the page actually renders ------------------------------------------------


def _funnel_page(funnel, xray):
    """Minimal page exercising both renderers the way the Analysis tab does."""
    import types

    from ui.universal_workspace import _render_core_funnel, _render_xray

    _render_core_funnel(funnel)
    _render_xray(types.SimpleNamespace(xray_diagnostics=xray, core_funnel=funnel))


def _app(instrumented):
    from streamlit.testing.v1 import AppTest

    return AppTest.from_function(
        _funnel_page, default_timeout=60,
        kwargs={"funnel": instrumented.core_funnel,
                "xray": instrumented.xray_diagnostics[:400]})


def test_the_funnel_page_renders_without_an_exception(instrumented):
    app = _app(instrumented).run()
    assert not app.exception, [item.value for item in app.exception]
    assert any("pre-setup funnel" in block.value for block in app.markdown)


def test_switching_component_does_not_break_the_page(instrumented):
    """A widget without a stable key can collide on rerun and blank the page."""
    app = _app(instrumented).run()
    for option in ("T3", "A4"):
        app.radio(key="core_funnel_child").set_value(option).run()
        assert not app.exception, [item.value for item in app.exception]


@pytest.mark.parametrize("selection", ([], ["A4_OUTSIDE_SESSION"], ["NOT_A_REAL_CODE"]))
def test_changing_the_reject_subset_does_not_break_the_page(instrumented, selection):
    app = _app(instrumented).run()
    widget = app.multiselect(key="core_funnel_codes_A4")
    widget.set_value([code for code in selection if code in widget.options]).run()
    assert not app.exception, [item.value for item in app.exception]


def test_changing_the_xray_subset_does_not_break_the_page(instrumented):
    app = _app(instrumented).run()
    for outcome in ("FAIL", "PASS", "All"):
        app.radio(key="xray_outcome").set_value(outcome).run()
        assert not app.exception, [item.value for item in app.exception]
    app.multiselect(key="xray_component").set_value([]).run()
    assert not app.exception, [item.value for item in app.exception]


def test_every_diagnostic_widget_declares_a_stable_key():
    """Streamlit derives an implicit id from a widget's arguments, so two widgets
    that momentarily look alike raise DuplicateWidgetID and blank the browser."""
    import ast

    interactive = {"radio", "multiselect", "selectbox", "checkbox", "slider",
                   "text_input", "number_input", "plotly_chart"}
    inspected = {"_funnel_child_choice", "_render_core_funnel", "_render_xray",
                 "_render_tester"}
    tree = ast.parse((ROOT / "ui" / "universal_workspace.py").read_text())
    checked = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in inspected:
            continue
        for call in ast.walk(node):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = getattr(func, "attr", None)
            if name not in interactive:
                continue
            owner = getattr(getattr(func, "value", None), "id", None)
            if owner not in {"st", None} and not isinstance(func.value, ast.Subscript):
                continue
            assert any(kw.arg == "key" for kw in call.keywords), (
                f"{node.name}: st.{name} is missing an explicit key")
            checked += 1
    assert checked >= 6
