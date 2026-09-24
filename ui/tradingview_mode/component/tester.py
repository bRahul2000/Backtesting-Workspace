"""Strategy Tester for the custom terminal: validation, execution and presentation.

The existing audited system is authoritative end to end:

    run_backtest event -> validate_run_request -> BacktestConfig
        -> core.adapters.audited_engine.run_universal_backtest
        -> UniversalBacktestResult -> build_run_payload (presentation only)

Nothing here fills orders, sizes positions or computes P&L. The presentation
layer only reshapes values the result already carries (epoch-second times,
JSON-safe numbers) and, where the result lacks a count the UI shows, derives it
from the result with the adapter's own thresholds, labelled as such.
"""
from __future__ import annotations

from dataclasses import MISSING, asdict, dataclass, fields
from datetime import date, timedelta
import math
import os
import time
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from brokers.exness import EXNESS
from core.config import BacktestConfig, DatasetRole, ExecutionMode
from core.result import UniversalBacktestResult
from core.trade_log import to_timestamp
from engine.models import RiskMode
from services.market_datasets import MarketDataset
from strategies.base_strategy import ParameterType, StrategyDescriptor
from strategies.registry import StrategyRegistry

ROOT = Path(__file__).resolve().parents[3]
#: Same ledger the Universal Workspace records into, so runs stay comparable.
#: TV_TESTER_LEDGER redirects it (e.g. for manual UI checks that must not add
#: rows to the research ledger's exposure counts).
LEDGER_PATH = Path(os.environ.get("TV_TESTER_LEDGER") or ROOT / "experiments" / "experiments.sqlite3")
#: Brokers the audited adapter accepts (it rejects every other profile).
BROKER_PROFILES = {EXNESS.broker_id: EXNESS}
#: BacktestConfig fields the audited adapter actually reads. Fields it ignores
#: (max_trades_per_day, session, weekdays, weekends) are deliberately not exposed.
SETTING_FIELDS = ("initial_capital", "risk_mode", "risk_per_trade_percent", "fixed_risk_dollars",
                  "risk_reward_ratio", "spread", "spread_multiplier", "commission_percent",
                  "slippage_percent", "leverage")
RISK_MODES = tuple(mode.name for mode in RiskMode)
MAX_CURVE_POINTS = 4_000
DEFAULT_RUN_DAYS = 365
_WIN = 1e-9  # the adapter's own win/loss threshold (core.adapters.audited_engine)


class TesterValidationError(ValueError):
    """A run request that the audited system must not execute as given."""


def config_defaults() -> dict[str, Any]:
    """Defaults straight from BacktestConfig, so none are invented here."""
    return {f.name: f.default for f in fields(BacktestConfig) if f.name in SETTING_FIELDS and f.default is not MISSING}


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------

def _parameter_spec(parameter) -> dict[str, Any]:
    kind = parameter.parameter_type.value
    return {
        "name": parameter.name, "label": parameter.display_name or parameter.name.replace("_", " ").title(),
        "type": "enum" if parameter.choices else kind, "default": parameter.default,
        "min": parameter.minimum, "max": parameter.maximum, "step": parameter.step,
        "choices": list(parameter.choices), "frozen": parameter.frozen,
        "description": parameter.description, "group": parameter.group,
    }


def compatible_datasets(descriptor: StrategyDescriptor, datasets: tuple[MarketDataset, ...]) -> tuple[MarketDataset, ...]:
    supported = {value.upper() for value in descriptor.metadata.supported_instruments}
    return tuple(entry for entry in datasets if entry.exists and entry.instrument.upper() in supported
                 and entry.timeframe in descriptor.metadata.supported_timeframes)


def tester_options(registry: StrategyRegistry, datasets: tuple[MarketDataset, ...],
                   bounds: Callable[[MarketDataset], tuple[date, date] | None]) -> dict[str, Any]:
    strategies = []
    dataset_keys: set[str] = set()
    for descriptor in registry.all():
        meta = descriptor.metadata
        compatible = compatible_datasets(descriptor, datasets)
        dataset_keys.update(entry.key for entry in compatible)
        strategies.append({
            "strategy_id": meta.strategy_id, "name": meta.name, "version": meta.version,
            "status": meta.status.value, "category": meta.category, "description": meta.description,
            "supported_instruments": list(meta.supported_instruments),
            "supported_timeframes": list(meta.supported_timeframes),
            "required_timeframes": list(descriptor.required_timeframes),
            "strategy_fingerprint": meta.strategy_fingerprint,
            "parameters": [_parameter_spec(p) for p in descriptor.parameters],
            "overridable": descriptor.parameterized_factory is not None,
            "datasets": [entry.key for entry in compatible],
        })
    dataset_rows = []
    for entry in datasets:
        if entry.key not in dataset_keys:
            continue
        span = bounds(entry)
        dataset_rows.append({
            "dataset_key": entry.key, "label": entry.label, "instrument": entry.instrument,
            "symbol": entry.symbol, "provider": entry.broker, "timeframe": entry.timeframe,
            "spread_source": entry.spread_source, "per_bar_spread": entry.carries_per_bar_spread,
            "min": span[0].isoformat() if span else None, "max": span[1].isoformat() if span else None,
            # Suggested form range only; the run uses exactly what the request states.
            "default_start": max(span[0], span[1] - timedelta(days=DEFAULT_RUN_DAYS - 1)).isoformat() if span else None,
        })
    return {
        "strategies": strategies,
        "datasets": dataset_rows,
        "broker_profiles": [{"broker_id": key, "name": f"{profile.name} {profile.account_type}"}
                            for key, profile in BROKER_PROFILES.items()],
        "dataset_roles": [role.value for role in DatasetRole],
        "risk_modes": list(RISK_MODES),
        "defaults": config_defaults(),
    }


# ---------------------------------------------------------------------------
# Request validation -> BacktestConfig
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ValidatedRun:
    config: BacktestConfig
    dataset: MarketDataset
    descriptor: StrategyDescriptor
    parameter_overrides: dict[str, Any]
    request: dict[str, Any]


def _coerce_parameter(parameter, value: Any) -> Any:
    kind = parameter.parameter_type
    if parameter.choices:
        if value not in parameter.choices:
            raise TesterValidationError(f"{parameter.name} must be one of {list(parameter.choices)}.")
        return value
    if kind is ParameterType.BOOLEAN:
        if not isinstance(value, bool):
            raise TesterValidationError(f"{parameter.name} must be true or false.")
        return value
    if kind in (ParameterType.STRING, ParameterType.TIMEFRAME, ParameterType.SESSION, ParameterType.ENUM):
        if not isinstance(value, str):
            raise TesterValidationError(f"{parameter.name} must be text.")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise TesterValidationError(f"{parameter.name} must be a finite number.")
    if kind is ParameterType.INTEGER:
        if float(value) != int(value):
            raise TesterValidationError(f"{parameter.name} must be a whole number.")
        return int(value)
    return float(value)


def _parameter_overrides(descriptor: StrategyDescriptor, values: dict[str, Any]) -> dict[str, Any]:
    known = {p.name: p for p in descriptor.parameters}
    unknown = sorted(set(values) - set(known))
    if unknown:
        raise TesterValidationError(f"Unknown parameter(s) for {descriptor.metadata.name}: {', '.join(unknown)}.")
    overrides = {}
    for name, raw in values.items():
        parameter = known[name]
        value = _coerce_parameter(parameter, raw)
        try:
            parameter.validate(value)
        except ValueError as exc:
            raise TesterValidationError(str(exc)) from exc
        if value != parameter.default:
            overrides[name] = value
    try:
        descriptor.create(overrides)  # the registry's own override rules
    except ValueError as exc:
        raise TesterValidationError(str(exc)) from exc
    return overrides


def _settings(dataset: MarketDataset, raw: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(raw) - set(SETTING_FIELDS))
    if unknown:
        raise TesterValidationError(f"Unsupported setting(s): {', '.join(unknown)}.")
    settings = config_defaults()
    for name, value in raw.items():
        if name == "risk_mode":
            if value not in RISK_MODES:
                raise TesterValidationError(f"risk_mode must be one of {list(RISK_MODES)}.")
            settings[name] = value
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise TesterValidationError(f"{name} must be a finite number.")
        settings[name] = float(value)
    if dataset.carries_per_bar_spread:
        # A broker-native dataset carries its own spread; a typed value must not override it.
        if raw.get("spread", 0.0) != 0.0:
            raise TesterValidationError(f"{dataset.label} carries a per-bar broker spread; a fixed spread cannot be set.")
        settings["spread"] = 0.0
    if settings["leverage"] <= 0:
        raise TesterValidationError("leverage must be positive.")
    if settings["fixed_risk_dollars"] <= 0:
        raise TesterValidationError("fixed_risk_dollars must be positive.")
    if settings["risk_per_trade_percent"] > 100:
        raise TesterValidationError("risk_per_trade_percent cannot exceed 100.")
    return settings


def validate_run_request(data: dict[str, Any], *, registry: StrategyRegistry,
                         lookup_dataset: Callable[[str], MarketDataset],
                         bounds: Callable[[MarketDataset], tuple[date, date] | None]) -> ValidatedRun:
    """Turn a structurally valid run_backtest event into the authoritative BacktestConfig."""
    try:
        descriptor = registry.get(data["strategy_id"])
    except KeyError as exc:
        raise TesterValidationError(f"Unknown strategy {data['strategy_id']!r}.") from exc
    try:
        entry = lookup_dataset(data["dataset_key"])
    except KeyError as exc:
        raise TesterValidationError(f"Unknown dataset {data['dataset_key']!r}.") from exc
    if not entry.exists:
        raise TesterValidationError(f"Dataset file for {entry.key} is missing.")
    meta = descriptor.metadata
    if entry.instrument.upper() not in {value.upper() for value in meta.supported_instruments}:
        raise TesterValidationError(f"{meta.name} does not support {entry.instrument} ({entry.key}).")
    if entry.timeframe not in meta.supported_timeframes:
        raise TesterValidationError(f"{meta.name} runs on {', '.join(meta.supported_timeframes)} data; "
                                    f"{entry.key} is {entry.timeframe}. No timeframe is derived for a backtest.")
    if data["broker_profile"] not in BROKER_PROFILES:
        raise TesterValidationError(f"Unsupported broker profile {data['broker_profile']!r}; "
                                    f"the audited adapter accepts {', '.join(BROKER_PROFILES)}.")
    try:
        role = DatasetRole(data["dataset_role"])
    except ValueError as exc:
        raise TesterValidationError(f"Unknown dataset role {data['dataset_role']!r}.") from exc

    start, end = date.fromisoformat(data["start"]), date.fromisoformat(data["end"])
    if start > end:
        raise TesterValidationError("Start date is after end date.")
    span = bounds(entry)
    if span is None:
        raise TesterValidationError(f"{entry.key} contains no bars.")
    if start < span[0] or end > span[1]:
        raise TesterValidationError(f"Range {start}..{end} is outside {entry.key} data {span[0]}..{span[1]}.")

    overrides = _parameter_overrides(descriptor, dict(data.get("parameters", {})))
    settings = _settings(entry, dict(data.get("settings", {})))
    try:
        config = BacktestConfig(
            instrument=entry.instrument, broker_profile=data["broker_profile"], strategy_id=meta.strategy_id,
            timeframe=entry.timeframe,
            start_date=pd.Timestamp(start, tz="UTC"),
            # Inclusive last bar of the end date, exactly as the Universal Workspace builds it.
            end_date=pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(seconds=entry.step_seconds),
            dataset_role=role, higher_timeframes=("1h",) if entry.timeframe == "15m" else (),
            spread_source=entry.spread_source, data_source=entry.key,
            execution_mode=ExecutionMode.SYNTHETIC_BID_ASK,
            strategy_parameters=overrides, notes="TradingView Mode Strategy Tester",
            **settings,
        )
    except ValueError as exc:
        raise TesterValidationError(str(exc)) from exc
    return ValidatedRun(config, entry, descriptor, overrides, dict(data))


def execute_run(run: ValidatedRun, *, runner: Callable[..., UniversalBacktestResult] | None = None,
                ledger_path: Path = LEDGER_PATH) -> UniversalBacktestResult:
    """Call the existing audited adapter. No other execution path exists here."""
    if runner is None:
        from core.adapters.audited_engine import run_universal_backtest as runner
    return runner(run.dataset.path, run.config, ledger_path=ledger_path)


# ---------------------------------------------------------------------------
# Presentation payload (reshaping only)
# ---------------------------------------------------------------------------

def json_number(value: Any) -> float | int | str | None:
    """JSON-safe number; infinities become "inf"/"-inf" (e.g. a loss-free profit factor)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    value = float(value)
    if math.isnan(value):
        return None
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    return value


def epoch(value: Any) -> int | None:
    return None if value is None else int(to_timestamp(value).timestamp())


def exit_label(reason: str | None) -> str:
    """Chart label from the engine's own exit reason text (never from prices)."""
    text = (reason or "").lower()
    if text.startswith("take profit"):
        return "TP"
    if text.startswith("stop loss"):
        return "SL"
    return "Exit"


def _stats(stats: Any) -> dict[str, Any]:
    values = asdict(stats) if hasattr(stats, "__dataclass_fields__") else dict(stats)
    return {key: json_number(value) for key, value in values.items()}


def serialize_trade(row: dict[str, Any]) -> dict[str, Any]:
    """One trade_log row -> chart/table trade. Prices and P&L are copied unchanged."""
    return {
        "trade_id": row["trade_id"], "direction": row["direction"], "setup_id": row.get("setup_id"),
        "signal_time": epoch(row.get("signal_time")), "entry_time": epoch(row["entry_time"]),
        "exit_time": epoch(row["exit_time"]),
        "entry_price": row["entry_price"], "stop_loss": row["stop_loss"], "take_profit": row["take_profit"],
        "exit_price": row["exit_price"], "exit_reason": row["exit_reason"], "exit_label": exit_label(row["exit_reason"]),
        "quantity": row["quantity"], "initial_risk": row.get("initial_risk"),
        "pnl": row["pnl"], "pnl_percent": row["pnl_percent"],
        "r_multiple": row["r_multiple"], "bars_held": row["bars_held"],
        "entry_commission": row["entry_commission"], "exit_commission": row["exit_commission"],
        "entry_model": row.get("entry_model"),
    }


def _curves(result: UniversalBacktestResult) -> dict[str, Any]:
    """Closed-trade equity and drawdown from result.equity_curve, keyed by epoch seconds.

    Segment-start points carry no timestamp; they take the run start. When two
    points share a second, the later (as recorded) wins so the series is
    strictly increasing for the chart. Downsampling only affects drawing.
    """
    start = epoch(result.period["start"])
    by_time: dict[int, dict[str, Any]] = {}
    for point in result.equity_curve:
        stamp = epoch(point["timestamp"]) if point.get("timestamp") else start
        by_time[stamp] = point
    ordered = sorted(by_time.items())
    total = len(ordered)
    if total > MAX_CURVE_POINTS:
        step = math.ceil(total / MAX_CURVE_POINTS)
        keep = set(range(0, total, step)) | {total - 1}
        ordered = [item for index, item in enumerate(ordered) if index in keep]
    return {
        "equity": [{"time": t, "value": float(p["balance"])} for t, p in ordered],
        "drawdown": [{"time": t, "value": -float(p["drawdown_percent"])} for t, p in ordered],
        "points_total": len(result.equity_curve), "downsampled": total > MAX_CURVE_POINTS,
    }


def _periods(stats: dict[str, Any]) -> list[dict[str, Any]]:
    return [{"period": period, **{key: json_number(value) for key, value in row.items()}}
            for period, row in stats.items()]


def build_run_payload(result: UniversalBacktestResult, run: ValidatedRun, *, duration_seconds: float) -> dict[str, Any]:
    """Presentation of an authoritative result. ``result`` is read, never modified."""
    config = run.config
    trades = [serialize_trade(row) for row in result.trade_log]
    wins = sum(1 for row in result.trade_log if row["pnl"] > _WIN)
    losses = sum(1 for row in result.trade_log if row["pnl"] < -_WIN)
    diagnostics = result.execution_diagnostics
    return {
        "run_id": result.run_id,
        "fingerprints": {
            "strategy": result.strategy_fingerprint, "parameter": result.parameter_fingerprint,
            "dataset": result.dataset_fingerprint, "broker": result.broker_fingerprint,
            "instrument": result.instrument_fingerprint,
        },
        "strategy": {"strategy_id": run.descriptor.metadata.strategy_id, "name": run.descriptor.metadata.name,
                     "version": run.descriptor.metadata.version, "status": run.descriptor.metadata.status.value},
        "dataset": {"dataset_key": run.dataset.key, "label": run.dataset.label, "provider": run.dataset.broker,
                    "symbol": run.dataset.symbol, "instrument": run.dataset.instrument,
                    "timeframe": run.dataset.timeframe, "spread_source": run.dataset.spread_source},
        "config": {
            "instrument": config.instrument, "broker_profile": config.broker_profile,
            "strategy_id": config.strategy_id, "timeframe": config.timeframe,
            "higher_timeframes": list(config.higher_timeframes),
            "start": config.start_date.isoformat(), "end": config.end_date.isoformat(),
            "dataset_role": config.dataset_role.value, "execution_mode": config.execution_mode.value,
            "data_source": config.data_source, "spread_source": config.spread_source,
            **{name: getattr(config, name) for name in SETTING_FIELDS},
            "strategy_parameters": dict(config.strategy_parameters),
        },
        "summary": {
            "pnl": json_number(result.pnl),
            "pnl_percent": json_number(result.pnl / config.initial_capital * 100),
            "total_trades": result.total_trades, "total_entries": result.total_entries,
            "winning_trades": wins, "losing_trades": losses,
            "trades_per_month": json_number(result.trades_per_month),
            "win_rate": json_number(result.win_rate), "profit_factor": json_number(result.profit_factor),
            "average_r": json_number(result.average_r),
            "max_drawdown_percent": json_number(result.max_drawdown_percent),
            "max_losing_streak": result.max_losing_streak,
            "open_positions_at_end": len(result.open_positions_at_end),
        },
        "derived_in_python": ["winning_trades", "losing_trades", "pnl_percent"],
        "directional": {"long": _stats(result.long_statistics), "short": _stats(result.short_statistics)},
        "periods": {"yearly": _periods(result.yearly_statistics), "monthly": _periods(result.monthly_statistics)},
        "trades": trades,
        "curves": _curves(result),
        "open_positions": [{**row, "entry_time": epoch(row["entry_time"])} for row in result.open_positions_at_end],
        "diagnostics": {
            "segments": diagnostics.get("segments"), "order_events": diagnostics.get("order_events", {}),
            "execution_adapter": diagnostics.get("execution_adapter"),
            "effective_spread_price": json_number(diagnostics.get("effective_spread_price")),
            "spread_multiplier": json_number(diagnostics.get("spread_multiplier")),
            "commission_percent": json_number(diagnostics.get("commission_percent")),
            "forward_validation_warning": diagnostics.get("forward_validation_warning"),
            "forward_exposure_warning": diagnostics.get("forward_exposure_warning"),
            "execution_ambiguities": len(result.execution_ambiguities),
            "excursion_model": result.excursion_model,
        },
        "duration_seconds": round(duration_seconds, 2),
    }


def trade_overlay(run_payload: dict[str, Any] | None, *, chart_identity: tuple[str, str, str],
                  bar_times: list[int], bar_seconds: int, chart_label: str) -> dict[str, Any]:
    """Place authoritative trades on the displayed chart.

    Markers need a bar time, so each exact entry/exit time is mapped to the
    chart bar that contains it (the bar opening at or before it). The exact
    times and prices are unchanged in the trade itself. Only a chart of the
    same instrument/provider/symbol as the backtest dataset gets markers, and
    only trades fully inside the loaded bars are placed.
    """
    if not run_payload:
        return {"available": False, "reason": None, "trades": []}
    ds = run_payload["dataset"]
    identity = (ds["instrument"], ds["provider"], ds["symbol"])
    if identity != chart_identity:
        return {"available": False, "trades": [],
                "reason": f"Chart shows {chart_label}; the backtest ran on {ds['label']}."}
    if not bar_times:
        return {"available": True, "reason": None, "trades": []}
    index = pd.Index(bar_times)
    first, end = bar_times[0], bar_times[-1] + bar_seconds
    placed = []
    for trade in run_payload["trades"]:
        if trade["entry_time"] < first or trade["exit_time"] >= end:
            continue
        entry_pos = index.searchsorted(trade["entry_time"], side="right") - 1
        exit_pos = index.searchsorted(trade["exit_time"], side="right") - 1
        placed.append({"trade_id": trade["trade_id"], "entry_bar": int(bar_times[entry_pos]),
                       "exit_bar": int(bar_times[exit_pos])})
    return {"available": True, "reason": None, "trades": placed}


def timed_run(run: ValidatedRun, **kwargs) -> tuple[UniversalBacktestResult, float]:
    started = time.perf_counter()
    result = execute_run(run, **kwargs)
    return result, time.perf_counter() - started

