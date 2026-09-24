"""Strategy Tester: the terminal only presents the audited Python result."""
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sqlite3

import pandas as pd
import pytest

from core.config import BacktestConfig, DatasetRole
from core.result import UniversalBacktestResult
from core.trade_log import to_timestamp
from services.market_datasets import all_datasets, dataset
from strategies.registry import discover_builtin_strategies
from ui.tradingview_mode.component import tester
from ui.tradingview_mode.component.protocol import (
    EVENT_SCHEMAS, EventValidationError, PayloadValidationError, parse_event, validate_payload,
)
from ui.tradingview_mode.component.state import TerminalState
from ui.tradingview_mode.component.terminal import (
    MAX_HISTORY, build_terminal_payload, consume_event, context_for, dataset_bounds, empty_tester_session,
    handle_tester_event,
)
from ui.tradingview_mode.timeframes import resolve_timeframe

REGISTRY = discover_builtin_strategies()
FRONTEND_SRC = Path(tester.__file__).with_name("frontend") / "src"
REAL_RESEARCH_LEDGER = tester.RESEARCH_LEDGER_PATH


def request(**overrides):
    data = {"strategy_id": "BTC_V3_CORE_V1_FROZEN", "dataset_key": "EXNESS_BTCUSDM_M15",
            "broker_profile": "EXNESS_STANDARD", "dataset_role": "DEVELOPMENT",
            "start": "2025-09-01", "end": "2026-09-20", "ledger_mode": "scratch", "parameters": {}, "settings": {}}
    data.update(overrides)
    return data


def validate(**overrides):
    return tester.validate_run_request(request(**overrides), registry=REGISTRY, lookup_dataset=dataset,
                                       bounds=dataset_bounds)


def event(event_id, kind, data):
    return parse_event({"id": event_id, "type": kind, "data": data})


@pytest.fixture(autouse=True)
def temporary_ledgers(tmp_path, monkeypatch):
    """No test writes to a repository ledger unless it says so explicitly."""
    monkeypatch.setattr(tester, "SCRATCH_LEDGER_PATH", tmp_path / "scratch.sqlite3")
    monkeypatch.setattr(tester, "RESEARCH_LEDGER_PATH", tmp_path / "research.sqlite3")
    return tmp_path


@pytest.fixture(scope="module")
def real_run(tmp_path_factory):
    """One real audited run spanning two continuous segments, into a throwaway ledger."""
    mp = pytest.MonkeyPatch()
    mp.setattr(tester, "SCRATCH_LEDGER_PATH", tmp_path_factory.mktemp("ledger") / "scratch.sqlite3")
    try:
        run = validate()
        result = tester.execute_run(run)
    finally:
        mp.undo()
    assert result.total_trades > 0
    assert len({row["trade_id"] for row in result.trade_log}) < result.total_trades, "fixture must repeat trade ids"
    return run, result


class RecordingRunner:
    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, data_path, config, *, ledger_path):
        self.calls.append((data_path, config, ledger_path))
        return self.result


def ledger_rows(path: Path) -> int:
    with sqlite3.connect(path) as conn:
        return conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]


# ---- request validation -----------------------------------------------------

@pytest.mark.parametrize("data, message", [
    ({"strategy_id": 7}, "invalid strategy_id"),
    ({"start": "01/06/2026"}, "invalid start"),
    ({"settings": {"risk": [1]}}, "invalid settings"),
    ({"order": "buy"}, "unexpected field"),
])
def test_run_event_is_structurally_validated(data, message):
    with pytest.raises(EventValidationError, match=message):
        parse_event({"id": "r-1", "type": "run_backtest", "data": request(**data)})


def test_run_event_requires_explicit_ledger_mode():
    data = request()
    del data["ledger_mode"]
    with pytest.raises(EventValidationError, match="missing field 'ledger_mode'"):
        parse_event({"id": "r-2", "type": "run_backtest", "data": data})


@pytest.mark.parametrize("overrides, message", [
    ({"broker_profile": "IC_MARKETS_RAW"}, "Unsupported broker profile"),
    ({"dataset_role": "PRODUCTION"}, "Unknown dataset role"),
    ({"ledger_mode": "production"}, "ledger_mode"),
    ({"start": "2026-08-01", "end": "2026-07-01"}, "after end"),
    ({"start": "2020-01-01"}, "outside"),
    ({"settings": {"risk_mode": "KELLY"}}, "risk_mode"),
    ({"settings": {"max_trades_per_day": 5}}, "Unsupported setting"),
    ({"settings": {"initial_capital": -5}}, "positive"),
    ({"settings": {"risk_per_trade_percent": "abc"}}, "finite number"),
    ({"settings": {"spread": 25.0}}, "per-bar broker spread"),
    ({"parameters": {"reward_multiple": 4.0}}, "Frozen parameter"),
    ({"parameters": {"lookback": 3}}, "Unknown parameter"),
])
def test_invalid_configurations_are_rejected_not_substituted(overrides, message):
    with pytest.raises(tester.TesterValidationError, match=message):
        validate(**overrides)


def test_valid_strategy_and_dataset_resolve_to_registry_objects():
    run = validate()
    assert run.descriptor is REGISTRY.get("BTC_V3_CORE_V1_FROZEN")
    assert run.dataset == dataset("EXNESS_BTCUSDM_M15")
    assert run.ledger_mode == "scratch"


def test_invalid_strategy_rejected():
    with pytest.raises(tester.TesterValidationError, match="Unknown strategy"):
        validate(strategy_id="NOT_A_STRATEGY")


@pytest.mark.parametrize("key, message", [
    ("BINANCE_BTCUSDT_15M", "Unknown dataset"),
    ("EXNESS_BTCUSDM_H1", "No timeframe is derived"),
    ("EXNESS_XAUUSDM_M15", "does not support"),
])
def test_invalid_dataset_rejected(key, message):
    with pytest.raises(tester.TesterValidationError, match=message):
        validate(dataset_key=key)


def test_options_expose_registry_strategies_datasets_and_ledger_modes():
    options = tester.tester_options(REGISTRY, all_datasets(), dataset_bounds)
    assert [s["strategy_id"] for s in options["strategies"]] == [d.metadata.strategy_id for d in REGISTRY.all()]
    assert {d["dataset_key"] for d in options["datasets"]} == {"BITSTAMP_BTCUSD_15M", "EXNESS_BTCUSDM_M15"}
    assert options["broker_profiles"] == [{"broker_id": "EXNESS_STANDARD", "name": "Exness Standard"}]
    assert set(options["defaults"]) == set(tester.SETTING_FIELDS)
    assert options["default_ledger_mode"] == "scratch"
    assert [m["mode"] for m in options["ledger_modes"]] == ["scratch", "research"]


def test_config_preserves_broker_provider_and_dataset_identity():
    exness = validate().config
    assert (exness.broker_profile, exness.data_source, exness.spread_source, exness.spread) == (
        "EXNESS_STANDARD", "EXNESS_BTCUSDM_M15", "BROKER_NATIVE_PER_BAR", 0.0)
    bitstamp = validate(dataset_key="BITSTAMP_BTCUSD_15M", start="2026-01-01", end="2026-02-01",
                        settings={"spread": 12.5}).config
    assert (bitstamp.broker_profile, bitstamp.data_source, bitstamp.spread_source, bitstamp.spread) == (
        "EXNESS_STANDARD", "BITSTAMP_BTCUSD_15M", "CONSTANT", 12.5)


def test_config_preserves_settings_dates_and_parameter_overrides():
    run = tester.validate_run_request(request(
        strategy_id="BTC_PB1_SHALLOW_PULLBACK_V1", start="2026-06-01", end="2026-06-30",
        parameters={"impulse_window_bars": 4, "pullback_maximum_bars": 3},
        settings={"initial_capital": 25_000, "risk_mode": "FIXED_DOLLARS", "fixed_risk_dollars": 40,
                  "risk_reward_ratio": 2.5, "commission_percent": 0.01, "slippage_percent": 0.02,
                  "leverage": 2, "spread_multiplier": 1.5},
    ), registry=REGISTRY, lookup_dataset=dataset, bounds=dataset_bounds)
    config = run.config
    assert dict(config.strategy_parameters) == {"impulse_window_bars": 4}
    assert (config.initial_capital, config.risk_mode, config.fixed_risk_dollars, config.risk_reward_ratio) == (
        25_000.0, "FIXED_DOLLARS", 40.0, 2.5)
    assert (config.commission_percent, config.slippage_percent, config.leverage, config.spread_multiplier) == (
        0.01, 0.02, 2.0, 1.5)
    assert config.start_date == pd.Timestamp("2026-06-01", tz="UTC")
    assert config.end_date == pd.Timestamp("2026-06-30 23:45", tz="UTC")
    assert config.dataset_role is DatasetRole.DEVELOPMENT


def test_frozen_strategy_is_read_only():
    options = tester.tester_options(REGISTRY, all_datasets(), dataset_bounds)
    frozen = next(s for s in options["strategies"] if s["strategy_id"] == "BTC_V3_CORE_V1_FROZEN")
    assert frozen["overridable"] is False and all(p["frozen"] for p in frozen["parameters"])
    assert dict(validate(parameters={"reward_multiple": 3.0}).config.strategy_parameters) == {}  # default only
    with pytest.raises(tester.TesterValidationError, match="Frozen parameter"):
        validate(parameters={"reward_multiple": 2.0})


def test_integer_parameter_rejects_fractions():
    with pytest.raises(tester.TesterValidationError, match="whole number"):
        validate(strategy_id="BTC_PB1_SHALLOW_PULLBACK_V1", parameters={"impulse_window_bars": 3.5})


# ---- execution: exactly once, through the audited adapter ----------------------

def test_run_event_executes_exactly_once_across_reruns(real_run):
    runner = RecordingRunner(real_run[1])
    raw = {"id": "ui-7", "type": "run_backtest", "data": request()}
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    last, session, runs = None, empty_tester_session(), {}
    for _ in range(4):
        state, _, last, pending = consume_event(state, raw, context_for(), last)
        if pending is not None:
            session, runs, _, _ = handle_tester_event(pending, session, runs, registry=REGISTRY, runner=runner)
    assert len(runner.calls) == 1 and session["status"] == "completed" and list(runs) == [1]


def test_authoritative_adapter_receives_the_validated_config_and_scratch_ledger(real_run, temporary_ledgers):
    runner = RecordingRunner(real_run[1])
    handle_tester_event(event("ui-8", "run_backtest", request()), empty_tester_session(), {},
                        registry=REGISTRY, runner=runner)
    (path, config, ledger), = runner.calls
    assert path == dataset("EXNESS_BTCUSDM_M15").path
    assert config == validate().config
    assert ledger == temporary_ledgers / "scratch.sqlite3"


def test_default_runner_is_run_universal_backtest(monkeypatch, real_run):
    import core.adapters.audited_engine as audited

    runner = RecordingRunner(real_run[1])
    monkeypatch.setattr(audited, "run_universal_backtest", runner)
    tester.execute_run(validate())
    assert len(runner.calls) == 1


def test_adapter_failures_and_invalid_requests_surface_as_errors():
    def failing(*args, **kwargs):
        raise ValueError("No continuous segment had enough warm-up data for this strategy.")

    session, runs, log, result = handle_tester_event(event("ui-9", "run_backtest", request()),
                                                     empty_tester_session(), {}, registry=REGISTRY, runner=failing)
    assert (session["status"], result, log.level, runs) == ("failed", None, "error", {})
    assert "warm-up" in session["error"]
    runner = RecordingRunner(None)
    session, _, _, _ = handle_tester_event(event("ui-10", "run_backtest", request(dataset_key="EXNESS_BTCUSDM_H1")),
                                           empty_tester_session(), {}, registry=REGISTRY, runner=runner)
    assert session["error"].startswith("Invalid configuration") and not runner.calls


# ---- ledger safety -----------------------------------------------------------------

def test_scratch_ledger_never_resolves_to_the_research_ledger(monkeypatch):
    monkeypatch.setattr(tester, "SCRATCH_LEDGER_PATH", tester.RESEARCH_LEDGER_PATH)
    with pytest.raises(tester.TesterValidationError, match="must differ"):
        tester.ledger_path_for("scratch")


def test_default_scratch_run_leaves_the_real_research_ledger_unchanged(monkeypatch, temporary_ledgers):
    """A real audited run in the default mode, with the real research ledger path in place."""
    monkeypatch.setattr(tester, "RESEARCH_LEDGER_PATH", REAL_RESEARCH_LEDGER)
    assert tester.DEFAULT_LEDGER_MODE == "scratch"
    before = hashlib.sha256(REAL_RESEARCH_LEDGER.read_bytes()).hexdigest() if REAL_RESEARCH_LEDGER.exists() else None
    session, _, _, _ = handle_tester_event(
        event("ui-11", "run_backtest", request(start="2026-06-01", end="2026-06-30")),
        empty_tester_session(), {}, registry=REGISTRY)
    assert session["status"] == "completed", session["error"]
    assert session["run"]["ledger"]["mode"] == "scratch"
    after = hashlib.sha256(REAL_RESEARCH_LEDGER.read_bytes()).hexdigest() if REAL_RESEARCH_LEDGER.exists() else None
    assert before == after
    assert ledger_rows(temporary_ledgers / "scratch.sqlite3") == 1


def test_explicit_research_mode_writes_the_research_ledger(temporary_ledgers):
    session, _, _, _ = handle_tester_event(
        event("ui-12", "run_backtest", request(start="2026-06-01", end="2026-06-30", ledger_mode="research")),
        empty_tester_session(), {}, registry=REGISTRY)
    assert session["status"] == "completed", session["error"]
    assert session["run"]["ledger"]["mode"] == "research"
    assert ledger_rows(temporary_ledgers / "research.sqlite3") == 1
    assert not (temporary_ledgers / "scratch.sqlite3").exists()


# ---- session history: restore / export never execute --------------------------------

def test_restore_and_export_use_the_stored_result_without_running(real_run):
    runner = RecordingRunner(real_run[1])
    session, runs, _, _ = handle_tester_event(event("h-1", "run_backtest", request()), empty_tester_session(), {},
                                              registry=REGISTRY, runner=runner)
    shown = session["run"]
    session, runs, _, _ = handle_tester_event(event("h-2", "clear_backtest", {}), session, runs, registry=REGISTRY, runner=runner)
    assert session["run"] is None and session["history"]
    session, runs, log, _ = handle_tester_event(event("h-3", "restore_run", {"history_id": 1}), session, runs,
                                                registry=REGISTRY, runner=runner)
    assert session["run"] is shown and "not re-run" in log.message
    for kind in ("trades_csv", "summary_json"):
        session, runs, _, _ = handle_tester_event(event(f"h-{kind}", "export_run", {"history_id": 1, "kind": kind}),
                                                  session, runs, registry=REGISTRY, runner=runner)
        assert session["export"]["id"] == f"h-{kind}"
    assert len(runner.calls) == 1
    session, _, log, _ = handle_tester_event(event("h-4", "restore_run", {"history_id": 99}), session, runs,
                                             registry=REGISTRY, runner=runner)
    assert log.level == "error" and len(runner.calls) == 1


def test_history_keeps_the_latest_runs_only(real_run):
    runner = RecordingRunner(real_run[1])
    session, runs = empty_tester_session(), {}
    for index in range(MAX_HISTORY + 2):
        session, runs, _, _ = handle_tester_event(event(f"m-{index}", "run_backtest", request()), session, runs,
                                                  registry=REGISTRY, runner=runner)
    assert len(session["history"]) == MAX_HISTORY == len(runs)
    assert [row["history_id"] for row in session["history"]][:2] == [MAX_HISTORY + 2, MAX_HISTORY + 1]
    assert set(runs) == {row["history_id"] for row in session["history"]}


def test_no_navigation_event_reaches_python():
    """Selecting, filtering, sorting and Prev/Next are frontend-only; only the
    run control can request a backtest."""
    assert not {"focus_trade", "select_trade", "next_trade", "previous_trade", "sort_trades"} & set(EVENT_SCHEMAS)
    senders = {path.name for path in (FRONTEND_SRC).rglob("*.js*") if 'sendEvent("run_backtest"' in path.read_text()}
    assert senders == {"useTesterForm.js"}


# ---- result payload ------------------------------------------------------------

def test_payload_matches_universal_backtest_result(real_run):
    run, result = real_run
    payload = tester.build_run_payload(result, run, duration_seconds=1.0)
    summary = payload["summary"]
    assert payload["run_id"] == result.run_id
    assert payload["fingerprints"] == {"strategy": result.strategy_fingerprint, "parameter": result.parameter_fingerprint,
                                       "dataset": result.dataset_fingerprint, "broker": result.broker_fingerprint,
                                       "instrument": result.instrument_fingerprint}
    for name in ("total_trades", "trades_per_month", "win_rate", "average_r", "pnl", "max_drawdown_percent",
                 "max_losing_streak", "total_entries"):
        assert summary[name] == tester.json_number(getattr(result, name)), name
    assert summary["profit_factor"] == tester.json_number(result.profit_factor)
    assert len(payload["trades"]) == len(result.trade_log) == result.total_trades
    json.dumps(payload, allow_nan=False)


def test_monthly_yearly_and_directional_statistics_serialize_exactly(real_run):
    run, result = real_run
    payload = tester.build_run_payload(result, run, duration_seconds=1.0)
    for name, source in (("monthly", result.monthly_statistics), ("yearly", result.yearly_statistics)):
        rows = payload["periods"][name]
        assert [row["period"] for row in rows] == list(source)
        for row in rows:
            expected = {key: tester.json_number(value) for key, value in source[row["period"]].items()}
            assert {key: value for key, value in row.items() if key != "period"} == expected
    for side, stats in (("long", result.long_statistics), ("short", result.short_statistics)):
        assert payload["directional"][side] == {k: tester.json_number(getattr(stats, k)) for k in
                                                 ("trades", "win_rate", "profit_factor", "average_r", "pnl")}


def test_diagnostics_serialize_result_fields_and_label_derived_values(real_run):
    run, result = real_run
    payload = tester.build_run_payload(result, run, duration_seconds=1.0)
    diagnostics, source = payload["diagnostics"], result.execution_diagnostics
    assert diagnostics["order_events"] == source["order_events"]
    assert diagnostics["segments"] == source["segments"]
    assert diagnostics["execution_adapter"] == source["execution_adapter"]
    assert diagnostics["execution_ambiguities"] == len(result.execution_ambiguities)
    assert len(diagnostics["ambiguities"]) == min(200, len(result.execution_ambiguities))
    derived = payload["python_derived"]
    assert derived["gap_through_fills"] == sum(bool(row["gap_through_trigger"]) for row in result.trade_log)
    assert "note" in derived and set(payload["derived_in_python"]) <= set(derived) | set(payload["summary"])
    json.dumps(diagnostics, allow_nan=False)


def test_python_streaks_mirror_the_adapter_rule(real_run):
    _, result = real_run
    segments = tester.trade_segments(result)
    assert tester.max_streak(result.trade_log, segments, winning=False) == result.max_losing_streak
    winning = tester.max_streak(result.trade_log, segments, winning=True)
    assert 0 < winning <= result.total_trades


def test_trade_keys_are_unique_and_segments_come_from_the_equity_curve(real_run):
    run, result = real_run
    trades = tester.build_run_payload(result, run, duration_seconds=1.0)["trades"]
    assert [t["key"] for t in trades] == list(range(len(result.trade_log)))
    assert len({(t["segment"], t["trade_id"]) for t in trades}) == len(trades)
    assert None not in {t["segment"] for t in trades}


def test_selected_trade_fields_are_exact_trade_log_values(real_run):
    run, result = real_run
    trades = tester.build_run_payload(result, run, duration_seconds=1.0)["trades"]
    for trade in trades:
        row = result.trade_log[trade["key"]]
        for name in ("trade_id", "direction", "entry_price", "stop_loss", "take_profit", "exit_price", "exit_reason",
                     "quantity", "pnl", "pnl_percent", "r_multiple", "bars_held", "entry_commission",
                     "exit_commission", "setup_id"):
            assert trade[name] == row[name], name
        for name in ("signal_time", "entry_time", "exit_time"):
            assert type(trade[name]) is int
            assert pd.Timestamp(trade[name], unit="s", tz="UTC") == to_timestamp(row[name])


def test_exit_labels_and_json_numbers():
    assert tester.exit_label("Take profit (opening gap)") == "TP"
    assert tester.exit_label("Stop loss (ambiguous bar, SL First)") == "SL"
    assert tester.exit_label("End of data") == "Exit"
    assert tester.json_number(float("inf")) == "inf" and tester.json_number(float("nan")) is None


def test_build_payload_and_exports_do_not_mutate_the_result(real_run):
    run, result = real_run
    before = copy.deepcopy(result.as_dict())
    tester.build_run_payload(result, run, duration_seconds=1.0)
    tester.trades_csv(result)
    tester.summary_export(result, run)
    assert result.as_dict() == before


def test_curves_are_strictly_increasing_and_downsampling_is_flagged(real_run):
    run, result = real_run
    curves = tester.build_run_payload(result, run, duration_seconds=1.0)["curves"]
    times = [p["time"] for p in curves["equity"]]
    assert times == sorted(set(times)) and not curves["downsampled"]
    many = UniversalBacktestResult(**{**{k: getattr(result, k) for k in result.__dataclass_fields__},
                                      "equity_curve": [{"timestamp": "2026-01-01T00:00:00+00:00", "balance": 1.0,
                                                        "drawdown_percent": 0.0}] + [
                                          {"timestamp": (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i)).isoformat(),
                                           "balance": float(i), "drawdown_percent": 0.0} for i in range(1, 9001)]})
    big = tester._curves(many)
    assert big["downsampled"] and big["points_total"] == 9001 and big["equity"][-1]["value"] == 9000.0


# ---- exports -------------------------------------------------------------------

def test_trades_csv_equals_the_complete_trade_log(real_run):
    _, result = real_run
    rows = list(csv.DictReader(io.StringIO(tester.trades_csv(result))))
    assert len(rows) == len(result.trade_log)
    columns = list(result.trade_log[0])
    assert list(rows[0]) == ["segment", *columns]
    segments = tester.trade_segments(result)
    for exported, row, segment in zip(rows, result.trade_log, segments):
        assert int(exported["segment"]) == segment
        for name in columns:
            value = row[name]
            if value is None:
                assert exported[name] == ""
            elif isinstance(value, bool):
                assert exported[name] == str(value)
            elif isinstance(value, (int, float)):
                assert float(exported[name]) == float(value), name  # exact round trip
            else:
                assert exported[name] == str(value), name


def test_summary_export_carries_fingerprints_and_authoritative_statistics(real_run):
    run, result = real_run
    text = json.dumps(tester.summary_export(result, run), allow_nan=False)
    summary = json.loads(text)
    assert summary["fingerprints"] == {"strategy": result.strategy_fingerprint, "parameter": result.parameter_fingerprint,
                                       "dataset": result.dataset_fingerprint, "broker": result.broker_fingerprint,
                                       "instrument": result.instrument_fingerprint}
    assert summary["run"]["run_id"] == result.run_id and summary["run"]["ledger_mode"] == "scratch"
    assert summary["summary"]["pnl"] == result.pnl and summary["summary"]["total_trades"] == result.total_trades
    assert summary["summary"]["max_losing_streak"] == result.max_losing_streak
    assert summary["monthly_statistics"].keys() == result.monthly_statistics.keys()
    assert summary["yearly_statistics"].keys() == result.yearly_statistics.keys()
    assert summary["directional"]["long"]["pnl"] == result.long_statistics.pnl
    assert summary["execution_diagnostics"]["order_events"] == result.execution_diagnostics["order_events"]
    assert summary["properties"]["strategy_id"] == run.config.strategy_id
    assert summary["properties"]["broker_profile"] == "EXNESS_STANDARD"
    # Python-derived values are kept apart from the result's own statistics.
    assert "winning_trades" not in summary["summary"] and "max_winning_streak" in summary["python_derived"]


# ---- chart overlay -----------------------------------------------------------------

def _terminal_payload(run_payload, key="EXNESS_BTCUSDM_M15", timeframe="15m", start="2025-09-01", days=385):
    selected = dataset(key)
    resolution = resolve_timeframe(selected, timeframe)
    periods = days * 86_400 // resolution.target_seconds
    times = pd.date_range(start, periods=periods, freq=f"{resolution.target_seconds}s", tz="UTC")
    frame = pd.DataFrame({"timestamp": times, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0})
    return build_terminal_payload(
        state=TerminalState(dataset_key=key, timeframe=timeframe), selected=selected, resolution=resolution,
        frame=frame, bounds=None, shown=None, logs=[], notices=[], watchlist=[],
        tester_payload={"status": "completed", "error": None, "form": None, "run": run_payload,
                        "options": {"strategies": []}, "history": []})


def test_markers_reference_unique_keys_on_the_tested_market_only(real_run):
    run, result = real_run
    run_payload = tester.build_run_payload(result, run, duration_seconds=1.0)
    overlay = _terminal_payload(run_payload)["trade_overlay"]
    assert overlay["available"] and len(overlay["trades"]) == len(run_payload["trades"])
    assert len({item["key"] for item in overlay["trades"]}) == len(overlay["trades"])
    for item in overlay["trades"]:
        trade = run_payload["trades"][item["key"]]
        assert item["entry_bar"] <= trade["entry_time"] < item["entry_bar"] + 900
        assert item["exit_bar"] <= trade["exit_time"] < item["exit_bar"] + 900
    other = _terminal_payload(run_payload, key="BITSTAMP_BTCUSD_15M")["trade_overlay"]
    assert not other["available"] and other["trades"] == [] and "backtest ran on" in other["reason"]


def test_payload_validation_rejects_tampered_trades(real_run):
    run, result = real_run
    payload = _terminal_payload(tester.build_run_payload(result, run, duration_seconds=1.0), days=40)
    bad = copy.deepcopy(payload)
    bad["tester"]["run"]["trades"][0]["entry_time"] = float(bad["tester"]["run"]["trades"][0]["entry_time"])
    with pytest.raises(PayloadValidationError, match="epoch seconds"):
        validate_payload(bad)
    bad = copy.deepcopy(payload)
    bad["trade_overlay"]["trades"].append({"key": 99999, "entry_bar": 0, "exit_bar": 0})
    with pytest.raises(PayloadValidationError, match="unknown trade key"):
        validate_payload(bad)


def test_frontend_does_not_derive_trade_results():
    """Lightweight guard: no P&L / price arithmetic or aggregation in the React tester."""
    sources = "\n".join(path.read_text() for path in (FRONTEND_SRC / "components" / "tester").glob("*.js*"))
    sources += (FRONTEND_SRC / "chart" / "ChartEngine.js").read_text() + (FRONTEND_SRC / "tradeView.js").read_text()
    forbidden = [r"exit_price\s*[-+*/]", r"entry_price\s*[-+*/]", r"[-+*/]\s*\w*\.?(entry|exit)_price",
                 r"\.reduce\(", r"pnl\s*[-+*/]=?", r"win_rate\s*=", r"profit_factor\s*="]
    for pattern in forbidden:
        assert not re.search(pattern, sources), pattern
