"""Strategy Tester: the custom frontend only presents the audited Python result."""
import copy
from datetime import date
import json
from pathlib import Path
import re

import pandas as pd
import pytest

from core.config import BacktestConfig, DatasetRole
from core.result import UniversalBacktestResult
from core.trade_log import to_timestamp
from services.market_datasets import all_datasets, dataset
from strategies.registry import discover_builtin_strategies
from ui.tradingview_mode.component import tester
from ui.tradingview_mode.component.protocol import (
    EventValidationError, PayloadValidationError, parse_event, validate_payload,
)
from ui.tradingview_mode.component.state import TerminalState
from ui.tradingview_mode.component.terminal import (
    build_terminal_payload, consume_event, context_for, dataset_bounds, empty_tester_session, handle_tester_event,
)
from ui.tradingview_mode.timeframes import resolve_timeframe

REGISTRY = discover_builtin_strategies()
FRONTEND_SRC = Path(tester.__file__).with_name("frontend") / "src"


def request(**overrides):
    data = {"strategy_id": "BTC_V3_CORE_V1_FROZEN", "dataset_key": "EXNESS_BTCUSDM_M15",
            "broker_profile": "EXNESS_STANDARD", "dataset_role": "DEVELOPMENT",
            "start": "2026-06-01", "end": "2026-07-31", "parameters": {}, "settings": {}}
    data.update(overrides)
    return data


def validate(**overrides):
    return tester.validate_run_request(request(**overrides), registry=REGISTRY, lookup_dataset=dataset,
                                       bounds=dataset_bounds)


@pytest.fixture(scope="module")
def real_run(tmp_path_factory):
    """One real audited run (≈2 months, M15) into a throwaway ledger."""
    run = validate()
    result = tester.execute_run(run, ledger_path=tmp_path_factory.mktemp("ledger") / "ledger.sqlite3")
    assert result.total_trades > 0, "fixture period must contain trades"
    return run, result


# ---- 1. request validation -----------------------------------------------------

@pytest.mark.parametrize("data, message", [
    ({"strategy_id": 7}, "invalid strategy_id"),
    ({"start": "01/06/2026"}, "invalid start"),
    ({"settings": {"risk": [1]}}, "invalid settings"),
    ({"order": "buy"}, "unexpected field"),
])
def test_run_event_is_structurally_validated(data, message):
    with pytest.raises(EventValidationError, match=message):
        parse_event({"id": "r-1", "type": "run_backtest", "data": request(**data)})


@pytest.mark.parametrize("overrides, message", [
    ({"broker_profile": "IC_MARKETS_RAW"}, "Unsupported broker profile"),
    ({"dataset_role": "PRODUCTION"}, "Unknown dataset role"),
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


# ---- 2-5. strategy and dataset lookup -----------------------------------------

def test_valid_strategy_and_dataset_resolve_to_registry_objects():
    run = validate()
    assert run.descriptor is REGISTRY.get("BTC_V3_CORE_V1_FROZEN")
    assert run.dataset == dataset("EXNESS_BTCUSDM_M15")


def test_invalid_strategy_rejected():
    with pytest.raises(tester.TesterValidationError, match="Unknown strategy"):
        validate(strategy_id="NOT_A_STRATEGY")


@pytest.mark.parametrize("key, message", [
    ("BINANCE_BTCUSDT_15M", "Unknown dataset"),
    ("EXNESS_BTCUSDM_H1", "No timeframe is derived"),   # strategy is 15m-only
    ("EXNESS_XAUUSDM_M15", "does not support"),
])
def test_invalid_dataset_rejected(key, message):
    with pytest.raises(tester.TesterValidationError, match=message):
        validate(dataset_key=key)


def test_options_expose_only_registry_strategies_and_compatible_datasets():
    options = tester.tester_options(REGISTRY, all_datasets(), dataset_bounds)
    assert [s["strategy_id"] for s in options["strategies"]] == [d.metadata.strategy_id for d in REGISTRY.all()]
    assert {d["dataset_key"] for d in options["datasets"]} == {"BITSTAMP_BTCUSD_15M", "EXNESS_BTCUSDM_M15"}
    assert options["broker_profiles"] == [{"broker_id": "EXNESS_STANDARD", "name": "Exness Standard"}]
    assert set(options["defaults"]) == set(tester.SETTING_FIELDS)
    assert options["defaults"]["risk_per_trade_percent"] == BacktestConfig.__dataclass_fields__["risk_per_trade_percent"].default


# ---- 6-7. identities and parameters preserved ----------------------------------

def test_config_preserves_broker_provider_and_dataset_identity():
    exness = validate().config
    assert (exness.broker_profile, exness.data_source, exness.spread_source) == (
        "EXNESS_STANDARD", "EXNESS_BTCUSDM_M15", "BROKER_NATIVE_PER_BAR")
    assert exness.spread == 0.0
    bitstamp = validate(dataset_key="BITSTAMP_BTCUSD_15M", settings={"spread": 12.5}).config
    assert (bitstamp.broker_profile, bitstamp.data_source, bitstamp.spread_source, bitstamp.spread) == (
        "EXNESS_STANDARD", "BITSTAMP_BTCUSD_15M", "CONSTANT", 12.5)
    assert exness.timeframe == bitstamp.timeframe == "15m"


def test_config_preserves_settings_dates_and_parameter_overrides():
    run = tester.validate_run_request(request(
        strategy_id="BTC_PB1_SHALLOW_PULLBACK_V1", start="2026-06-01", end="2026-06-30",
        parameters={"impulse_window_bars": 4, "pullback_maximum_bars": 3},
        settings={"initial_capital": 25_000, "risk_mode": "FIXED_DOLLARS", "fixed_risk_dollars": 40,
                  "risk_reward_ratio": 2.5, "commission_percent": 0.01, "slippage_percent": 0.02,
                  "leverage": 2, "spread_multiplier": 1.5},
    ), registry=REGISTRY, lookup_dataset=dataset, bounds=dataset_bounds)
    config = run.config
    assert dict(config.strategy_parameters) == {"impulse_window_bars": 4}  # defaults are not overrides
    assert (config.initial_capital, config.risk_mode, config.fixed_risk_dollars, config.risk_reward_ratio) == (
        25_000.0, "FIXED_DOLLARS", 40.0, 2.5)
    assert (config.commission_percent, config.slippage_percent, config.leverage, config.spread_multiplier) == (
        0.01, 0.02, 2.0, 1.5)
    assert config.start_date == pd.Timestamp("2026-06-01", tz="UTC")
    assert config.end_date == pd.Timestamp("2026-06-30 23:45", tz="UTC")  # inclusive last M15 bar
    assert config.dataset_role is DatasetRole.DEVELOPMENT


def test_integer_parameter_rejects_fractions():
    with pytest.raises(tester.TesterValidationError, match="whole number"):
        validate(strategy_id="BTC_PB1_SHALLOW_PULLBACK_V1", parameters={"impulse_window_bars": 3.5})


# ---- 8-9. exactly once, through the audited adapter -----------------------------

class RecordingRunner:
    def __init__(self, result):
        self.result, self.calls = result, []

    def __call__(self, data_path, config, *, ledger_path):
        self.calls.append((data_path, config, ledger_path))
        return self.result


def test_run_event_executes_exactly_once_across_reruns(real_run, tmp_path):
    runner = RecordingRunner(real_run[1])
    raw = {"id": "ui-7", "type": "run_backtest", "data": request()}
    state = TerminalState(dataset_key="EXNESS_BTCUSDM_M15", timeframe="15m")
    last, session = None, empty_tester_session()
    for _ in range(4):  # Streamlit re-delivers the same component value on every rerun
        state, _, last, event = consume_event(state, raw, context_for(), last)
        if event is not None:
            session, _, _ = handle_tester_event(event, session, registry=REGISTRY, runner=runner, ledger_path=tmp_path / "l")
    assert len(runner.calls) == 1
    assert session["status"] == "completed"


def test_authoritative_adapter_receives_the_validated_config(real_run, tmp_path):
    runner = RecordingRunner(real_run[1])
    event = parse_event({"id": "ui-8", "type": "run_backtest", "data": request()})
    handle_tester_event(event, empty_tester_session(), registry=REGISTRY, runner=runner, ledger_path=tmp_path / "l")
    (path, config, ledger), = runner.calls
    assert path == dataset("EXNESS_BTCUSDM_M15").path
    assert config == validate().config
    assert ledger == tmp_path / "l"


def test_default_runner_is_run_universal_backtest(monkeypatch, real_run):
    import core.adapters.audited_engine as audited

    runner = RecordingRunner(real_run[1])
    monkeypatch.setattr(audited, "run_universal_backtest", runner)
    tester.execute_run(validate(), ledger_path=Path("unused"))
    assert len(runner.calls) == 1


def test_adapter_failures_and_invalid_requests_surface_as_errors(tmp_path):
    def failing(*args, **kwargs):
        raise ValueError("No continuous segment had enough warm-up data for this strategy.")

    event = parse_event({"id": "ui-9", "type": "run_backtest", "data": request()})
    session, log, result = handle_tester_event(event, empty_tester_session(), registry=REGISTRY, runner=failing, ledger_path=tmp_path / "l")
    assert (session["status"], result, log.level) == ("failed", None, "error")
    assert "warm-up" in session["error"]
    bad = parse_event({"id": "ui-10", "type": "run_backtest", "data": request(dataset_key="EXNESS_BTCUSDM_H1")})
    runner = RecordingRunner(None)
    session, _, _ = handle_tester_event(bad, empty_tester_session(), registry=REGISTRY, runner=runner)
    assert session["status"] == "failed" and session["error"].startswith("Invalid configuration") and not runner.calls


# ---- 10-16. result payload ------------------------------------------------------

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
    assert payload["directional"]["long"]["pnl"] == result.long_statistics.pnl
    assert payload["directional"]["short"]["trades"] == result.short_statistics.trades
    assert [row["period"] for row in payload["periods"]["monthly"]] == list(result.monthly_statistics)
    assert len(payload["trades"]) == len(result.trade_log) == result.total_trades
    assert payload["curves"]["equity"][-1]["value"] == result.equity_curve[-1]["balance"]
    json.dumps(payload, allow_nan=False)


def test_trade_serialization_preserves_prices_and_utc_times_exactly(real_run):
    _, result = real_run
    for row in result.trade_log:
        trade = tester.serialize_trade(row)
        for name in ("entry_price", "stop_loss", "take_profit", "exit_price", "pnl", "pnl_percent",
                     "r_multiple", "quantity", "entry_commission", "exit_commission", "bars_held"):
            assert trade[name] == row[name], name  # identical values, no rounding
        for name in ("signal_time", "entry_time", "exit_time"):
            assert type(trade[name]) is int
            assert pd.Timestamp(trade[name], unit="s", tz="UTC") == to_timestamp(row[name])
        assert trade["exit_label"] in {"TP", "SL", "Exit"}


def test_exit_labels_come_from_engine_reason_text():
    assert tester.exit_label("Take profit (opening gap)") == "TP"
    assert tester.exit_label("Stop loss (ambiguous bar, SL First)") == "SL"
    assert tester.exit_label("End of data") == "Exit"


def test_json_number_encodes_infinite_profit_factor():
    assert tester.json_number(float("inf")) == "inf"
    assert tester.json_number(None) is None
    assert tester.json_number(float("nan")) is None


def test_build_payload_does_not_mutate_the_result(real_run):
    run, result = real_run
    before = copy.deepcopy(result.as_dict())
    tester.build_run_payload(result, run, duration_seconds=1.0)
    assert result.as_dict() == before


def test_curves_are_strictly_increasing_and_downsampling_is_flagged(real_run):
    run, result = real_run
    curves = tester.build_run_payload(result, run, duration_seconds=1.0)["curves"]
    times = [p["time"] for p in curves["equity"]]
    assert times == sorted(set(times)) and not curves["downsampled"]
    many = UniversalBacktestResult(**{**{k: getattr(result, k) for k in result.__dataclass_fields__},
                                      "equity_curve": [{"timestamp": f"2026-01-01T00:00:00+00:00", "balance": 1.0,
                                                        "drawdown_percent": 0.0}] + [
                                          {"timestamp": (pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(minutes=15 * i)).isoformat(),
                                           "balance": float(i), "drawdown_percent": 0.0} for i in range(1, 9001)]})
    big = tester._curves(many)
    assert big["downsampled"] and big["points_total"] == 9001 and len(big["equity"]) <= tester.MAX_CURVE_POINTS + 1
    assert big["equity"][-1]["value"] == 9000.0


# ---- chart overlay ---------------------------------------------------------------

def _terminal_payload(run_payload, key="EXNESS_BTCUSDM_M15", timeframe="15m", periods=24 * 4 * 61):
    selected = dataset(key)
    resolution = resolve_timeframe(selected, timeframe)
    step = f"{resolution.target_seconds}s"
    times = pd.date_range("2026-06-01", periods=periods, freq=step, tz="UTC")
    frame = pd.DataFrame({"timestamp": times, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0})
    return build_terminal_payload(
        state=TerminalState(dataset_key=key, timeframe=timeframe), selected=selected, resolution=resolution,
        frame=frame, bounds=None, shown=None, logs=[], notices=[], watchlist=[],
        tester_payload={"status": "completed", "error": None, "form": None, "run": run_payload,
                        "options": {"strategies": []}})


def test_markers_only_on_the_tested_market_and_on_containing_bars(real_run):
    run, result = real_run
    run_payload = tester.build_run_payload(result, run, duration_seconds=1.0)
    same = _terminal_payload(run_payload)
    overlay = same["trade_overlay"]
    assert overlay["available"] and len(overlay["trades"]) == len(run_payload["trades"])
    trades = {t["trade_id"]: t for t in run_payload["trades"]}
    for item in overlay["trades"]:
        trade = trades[item["trade_id"]]
        assert item["entry_bar"] <= trade["entry_time"] < item["entry_bar"] + 900
        assert item["exit_bar"] <= trade["exit_time"] < item["exit_bar"] + 900
    hourly = _terminal_payload(run_payload, timeframe="1h", periods=24 * 61)["trade_overlay"]
    for item in hourly["trades"]:
        assert item["entry_bar"] <= trades[item["trade_id"]]["entry_time"] < item["entry_bar"] + 3600
    other = _terminal_payload(run_payload, key="BITSTAMP_BTCUSD_15M")["trade_overlay"]
    assert not other["available"] and other["trades"] == [] and "backtest ran on" in other["reason"]


def test_payload_validation_rejects_tampered_trades(real_run):
    run, result = real_run
    payload = _terminal_payload(tester.build_run_payload(result, run, duration_seconds=1.0))
    bad = copy.deepcopy(payload)
    bad["tester"]["run"]["trades"][0]["entry_time"] = float(bad["tester"]["run"]["trades"][0]["entry_time"])
    with pytest.raises(PayloadValidationError, match="epoch seconds"):
        validate_payload(bad)
    bad = copy.deepcopy(payload)
    bad["trade_overlay"]["trades"].append({"trade_id": 99999, "entry_bar": 0, "exit_bar": 0})
    with pytest.raises(PayloadValidationError, match="unknown trade"):
        validate_payload(bad)


def test_frontend_does_not_derive_trade_results():
    """Lightweight guard: no P&L / price arithmetic or trade aggregation in the React tester."""
    sources = "\n".join(path.read_text() for path in (FRONTEND_SRC / "components" / "tester").glob("*.js*"))
    sources += (FRONTEND_SRC / "chart" / "ChartEngine.js").read_text()
    forbidden = [r"exit_price\s*[-+*/]", r"entry_price\s*[-+*/]", r"[-+*/]\s*\w*\.?(entry|exit)_price",
                 r"\.reduce\(", r"pnl\s*[-+*/]=?"]
    for pattern in forbidden:
        assert not re.search(pattern, sources), pattern
