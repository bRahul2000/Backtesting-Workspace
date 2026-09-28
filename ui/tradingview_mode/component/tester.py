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
import time
from datetime import datetime, timezone
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
#: Ledger modes. Every audited run is recorded in an experiment ledger; the
#: mode decides which one. Scratch is the default so UI work never adds rows
#: (or forward-exposure counts) to the research ledger. Research is an explicit
#: per-run choice. Paths are read at call time (tests redirect them).
RESEARCH_LEDGER_PATH = ROOT / "experiments" / "experiments.sqlite3"
SCRATCH_LEDGER_PATH = ROOT / "experiments" / "scratch" / "tradingview_mode.sqlite3"
LEDGER_MODES = {"scratch": "Development / Scratch", "research": "Research Ledger"}
DEFAULT_LEDGER_MODE = "scratch"
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
        "ledger_modes": [{"mode": mode, "label": label, "path": _relative(ledger_path_for(mode))}
                         for mode, label in LEDGER_MODES.items()],
        "default_ledger_mode": DEFAULT_LEDGER_MODE,
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
    ledger_mode: str


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
    ledger_mode = data.get("ledger_mode")
    if ledger_mode not in LEDGER_MODES:
        raise TesterValidationError(f"ledger_mode must be one of {list(LEDGER_MODES)}; got {ledger_mode!r}.")
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
    return ValidatedRun(config, entry, descriptor, overrides, dict(data), ledger_mode)


def _relative(path: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def ledger_path_for(mode: str) -> Path:
    """Ledger file for a mode. Scratch can never resolve to the research ledger."""
    if mode == "research":
        return Path(RESEARCH_LEDGER_PATH)
    if mode == "scratch":
        path = Path(SCRATCH_LEDGER_PATH)
        if path.resolve() == Path(RESEARCH_LEDGER_PATH).resolve():
            raise TesterValidationError("Scratch ledger path must differ from the research ledger.")
        return path
    raise TesterValidationError(f"Unknown ledger mode {mode!r}.")


def execute_run(run: ValidatedRun, *, runner: Callable[..., UniversalBacktestResult] | None = None
                ) -> UniversalBacktestResult:
    """Call the existing audited adapter. No other execution path exists here."""
    if runner is None:
        from core.adapters.audited_engine import run_universal_backtest as runner
    return runner(run.dataset.path, run.config, ledger_path=ledger_path_for(run.ledger_mode))


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


def jsonable(value: Any) -> Any:
    """Deep JSON-safe copy (UTC ISO timestamps, enum values, "inf" for infinities)."""
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime)):
        return to_timestamp(value).isoformat()
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return json_number(value)
    if hasattr(value, "__dataclass_fields__"):
        return jsonable(asdict(value))
    if hasattr(value, "value"):
        return jsonable(value.value)
    return str(value)


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


def trade_segments(result: UniversalBacktestResult) -> list[int | None]:
    """Continuous-data segment of each trade_log row.

    The engine restarts trade_id in every continuous segment, so trade_id alone
    is not unique. equity_curve records (segment, trade_id) for every closed
    trade in the same order as trade_log; if that ever disagrees, segments are
    reported as unknown rather than guessed.
    """
    closed = [(point["segment"], point["trade_id"]) for point in result.equity_curve
              if point.get("trade_id") is not None]
    if len(closed) != len(result.trade_log) or any(
            trade_id != row["trade_id"] for (_, trade_id), row in zip(closed, result.trade_log)):
        return [None] * len(result.trade_log)
    return [segment for segment, _ in closed]


def serialize_trade(row: dict[str, Any], key: int = 0, segment: int | None = None) -> dict[str, Any]:
    """One trade_log row -> chart/table trade. Prices and P&L are copied unchanged.

    ``key`` is the row's position in trade_log: the unique handle used for
    selection and chart markers (trade_id repeats across segments).
    """
    return {
        "key": key, "segment": segment,
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


def max_streak(trade_log: list[dict[str, Any]], segments: list[int | None], *, winning: bool) -> int:
    """Longest run of winning (or losing) trades within a continuous segment.

    Mirrors the audited adapter's max_losing_streak rule: ±1e-9 thresholds, a
    breakeven trade does not reset the streak, and streaks never span segments.
    """
    worst = current = 0
    previous: object = object()
    for row, segment in zip(trade_log, segments):
        if segment != previous:
            current, previous = 0, segment
        hit = row["pnl"] > _WIN if winning else row["pnl"] < -_WIN
        opposite = row["pnl"] < -_WIN if winning else row["pnl"] > _WIN
        if hit:
            current += 1
            worst = max(worst, current)
        elif opposite:
            current = 0
    return worst


def python_derived(result: UniversalBacktestResult, config: BacktestConfig, segments: list[int | None]) -> dict[str, Any]:
    """Values the result does not carry, derived here from the result itself."""
    log = result.trade_log
    return {
        "winning_trades": sum(1 for row in log if row["pnl"] > _WIN),
        "losing_trades": sum(1 for row in log if row["pnl"] < -_WIN),
        "pnl_percent": json_number(result.pnl / config.initial_capital * 100),
        "max_winning_streak": max_streak(log, segments, winning=True),
        "gap_through_fills": sum(1 for row in log if row.get("gap_through_trigger")),
        "leverage_capped_trades": sum(1 for row in log if row.get("leverage_capped")),
        "entry_models": dict(sorted(_count(row.get("entry_model") for row in log).items())),
        "total_entry_commission": json_number(sum(row["entry_commission"] for row in log)),
        "total_exit_commission": json_number(sum(row["exit_commission"] for row in log)),
        "note": "Derived in Python from UniversalBacktestResult.trade_log with the audited adapter's "
                "±1e-9 win/loss thresholds; not fields of the result itself.",
    }


def _count(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return counts


def _config_dict(config: BacktestConfig) -> dict[str, Any]:
    return jsonable({f.name: getattr(config, f.name) for f in fields(BacktestConfig)})


def build_run_payload(result: UniversalBacktestResult, run: ValidatedRun, *, duration_seconds: float) -> dict[str, Any]:
    """Presentation of an authoritative result. ``result`` is read, never modified."""
    config = run.config
    segments = trade_segments(result)
    trades = [serialize_trade(row, index, segment)
              for index, (row, segment) in enumerate(zip(result.trade_log, segments))]
    derived = python_derived(result, config, segments)
    diagnostics = result.execution_diagnostics
    return {
        "run_id": result.run_id,
        "ledger": {"mode": run.ledger_mode, "label": LEDGER_MODES[run.ledger_mode],
                   "path": _relative(ledger_path_for(run.ledger_mode))},
        "fingerprints": {
            "strategy": result.strategy_fingerprint, "parameter": result.parameter_fingerprint,
            "dataset": result.dataset_fingerprint, "broker": result.broker_fingerprint,
            "instrument": result.instrument_fingerprint,
        },
        "strategy": {"strategy_id": run.descriptor.metadata.strategy_id, "name": run.descriptor.metadata.name,
                     "version": run.descriptor.metadata.version, "status": run.descriptor.metadata.status.value,
                     "frozen": run.descriptor.parameterized_factory is None},
        "dataset": {"dataset_key": run.dataset.key, "label": run.dataset.label, "provider": run.dataset.broker,
                    "symbol": run.dataset.symbol, "instrument": run.dataset.instrument,
                    "timeframe": run.dataset.timeframe, "spread_source": run.dataset.spread_source,
                    "read_only": run.dataset.read_only},
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
            "total_trades": result.total_trades, "total_entries": result.total_entries,
            "trades_per_month": json_number(result.trades_per_month),
            "win_rate": json_number(result.win_rate), "profit_factor": json_number(result.profit_factor),
            "average_r": json_number(result.average_r),
            "max_drawdown_percent": json_number(result.max_drawdown_percent),
            "max_losing_streak": result.max_losing_streak,
            "open_positions_at_end": len(result.open_positions_at_end),
            # Python-derived (see python_derived); kept here for the metric row.
            "pnl_percent": derived["pnl_percent"],
            "winning_trades": derived["winning_trades"], "losing_trades": derived["losing_trades"],
        },
        "derived_in_python": ["winning_trades", "losing_trades", "pnl_percent", "max_winning_streak"],
        "python_derived": derived,
        "directional": {"long": _stats(result.long_statistics), "short": _stats(result.short_statistics)},
        "periods": {"yearly": _periods(result.yearly_statistics), "monthly": _periods(result.monthly_statistics)},
        "trades": trades,
        "curves": _curves(result),
        "open_positions": [{**row, "entry_time": epoch(row["entry_time"])} for row in result.open_positions_at_end],
        "diagnostics": {
            "segments": diagnostics.get("segments"), "order_events": diagnostics.get("order_events", {}),
            "execution_adapter": diagnostics.get("execution_adapter"),
            "spread_price": json_number(diagnostics.get("spread_price")),
            "effective_spread_price": json_number(diagnostics.get("effective_spread_price")),
            "spread_multiplier": json_number(diagnostics.get("spread_multiplier")),
            "commission_percent": json_number(diagnostics.get("commission_percent")),
            "slippage_percent": json_number(config.slippage_percent),
            "forward_runs_for_strategy": diagnostics.get("forward_runs_for_strategy"),
            "forward_validation_warning": diagnostics.get("forward_validation_warning"),
            "forward_exposure_warning": diagnostics.get("forward_exposure_warning"),
            "execution_ambiguities": len(result.execution_ambiguities),
            "ambiguities": jsonable(result.execution_ambiguities[:200]),
            "excursion_model": result.excursion_model,
        },
        "duration_seconds": round(duration_seconds, 2),
    }


# ---------------------------------------------------------------------------
# Exports (authoritative content, generated in Python)
# ---------------------------------------------------------------------------

def trades_csv(result: UniversalBacktestResult) -> str:
    """The complete trade_log, every field unchanged, plus a leading ``segment``
    column because trade_id repeats across continuous segments."""
    frame = pd.DataFrame(result.trade_log)
    frame.insert(0, "segment", trade_segments(result))
    return frame.to_csv(index=False)


def summary_export(result: UniversalBacktestResult, run: ValidatedRun) -> dict[str, Any]:
    """Run metadata, fingerprints, properties and every statistic of the result.

    Values the result does not carry are kept apart under ``python_derived``.
    """
    segments = trade_segments(result)
    return jsonable({
        "export": {"kind": "tradingview_mode_strategy_tester_summary", "source": "UniversalBacktestResult",
                   "generated_at": datetime.now(timezone.utc).isoformat()},
        "run": {"run_id": result.run_id, "ledger_mode": run.ledger_mode,
                "ledger_path": _relative(ledger_path_for(run.ledger_mode)),
                "strategy_id": run.descriptor.metadata.strategy_id, "strategy_name": run.descriptor.metadata.name,
                "strategy_version": run.descriptor.metadata.version,
                "strategy_status": run.descriptor.metadata.status.value,
                "dataset_key": run.dataset.key, "dataset_label": run.dataset.label,
                "market_data_provider": run.dataset.broker, "instrument": result.instrument,
                "period": result.period, "dataset_role": result.dataset_role},
        "fingerprints": {"strategy": result.strategy_fingerprint, "parameter": result.parameter_fingerprint,
                         "dataset": result.dataset_fingerprint, "broker": result.broker_fingerprint,
                         "instrument": result.instrument_fingerprint},
        "properties": _config_dict(run.config),
        "summary": {name: getattr(result, name) for name in (
            "total_trades", "total_entries", "trades_per_month", "win_rate", "profit_factor", "average_r",
            "pnl", "max_drawdown_percent", "drawdown_duration", "max_losing_streak")}
                   | {"open_positions_at_end": result.open_positions_at_end},
        "directional": {"long": result.long_statistics, "short": result.short_statistics},
        "yearly_statistics": result.yearly_statistics,
        "monthly_statistics": result.monthly_statistics,
        "execution_diagnostics": result.execution_diagnostics,
        "execution_ambiguities": result.execution_ambiguities,
        "excursion_model": result.excursion_model,
        "python_derived": python_derived(result, run.config, segments),
    })


# ---------------------------------------------------------------------------
# Replay-safe presentation (no information after the replay cursor)
# ---------------------------------------------------------------------------

#: Trade fields known once the position is open (levels are fixed at entry).
ENTRY_FIELDS = ("key", "segment", "trade_id", "direction", "setup_id", "signal_time", "entry_time", "entry_price",
                "stop_loss", "take_profit", "quantity", "initial_risk", "entry_commission", "entry_model")
#: Run fields that describe the request, not its outcome.
_RUN_IDENTITY = ("run_id", "history_id", "ledger", "fingerprints", "strategy", "dataset", "config",
                 "duration_seconds", "price_precision")
HIDDEN_DURING_REPLAY = "Full backtest statistics are hidden during Replay to prevent future-data leakage."


def replay_view(run_payload: dict[str, Any] | None, knowable_until: int) -> dict[str, Any] | None:
    """What of a stored run was knowable before ``knowable_until`` (exclusive,
    the close of the newest revealed bar). Returns a new dict; nothing is mutated.

    Closed trades are those with exit_time < knowable_until (shown in full).
    Trades entered before it but closing later are OPEN: only entry-time fields.
    Later trades are omitted, and no count of them is given. Every aggregate
    (summary, curves, periods, directional, derived, diagnostics) is dropped
    because it is computed over the whole run.
    """
    if run_payload is None:
        return None
    trades = []
    for trade in run_payload["trades"]:
        if trade["entry_time"] >= knowable_until:
            continue
        if trade["exit_time"] < knowable_until:
            trades.append({**trade, "status": "closed"})
        else:
            trades.append({**{name: trade.get(name) for name in ENTRY_FIELDS}, "status": "open"})
    view = {name: run_payload[name] for name in _RUN_IDENTITY if name in run_payload}
    view["trades"] = trades
    view["replay_view"] = {
        "knowable_until": knowable_until,
        "closed_trades": sum(1 for trade in trades if trade["status"] == "closed"),
        "open_trades": sum(1 for trade in trades if trade["status"] == "open"),
        "message": HIDDEN_DURING_REPLAY,
    }
    return view


def replay_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Session history without outcome columns (trades, P&L, win rate)."""
    keep = ("history_id", "run_id", "ledger_mode", "strategy", "instrument", "dataset", "start", "end")
    return [{name: row[name] for name in keep} for row in rows]


# ---------------------------------------------------------------------------
# Chart overlay
# ---------------------------------------------------------------------------

def trade_overlay(run_payload: dict[str, Any] | None, *, chart_identity: tuple[str, str, str],
                  bar_times: list[int], bar_seconds: int, chart_label: str) -> dict[str, Any]:
    """Place authoritative trades on the displayed chart.

    Markers need a bar time, so each exact entry/exit time is mapped to the
    chart bar that contains it (the bar opening at or before it). The exact
    times and prices are unchanged in the trade itself. Only a chart of the
    same instrument/provider/symbol as the backtest dataset gets markers, and
    only trades fully inside the loaded bars are placed. Items reference
    trades by their unique ``key``.
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
        if trade.get("status") == "open":  # replay: still open at the cursor, nothing to draw
            continue
        if trade["entry_time"] < first or trade["exit_time"] >= end:
            continue
        entry_pos = index.searchsorted(trade["entry_time"], side="right") - 1
        exit_pos = index.searchsorted(trade["exit_time"], side="right") - 1
        placed.append({"key": trade["key"], "entry_bar": int(bar_times[entry_pos]),
                       "exit_bar": int(bar_times[exit_pos])})
    return {"available": True, "reason": None, "trades": placed}


def timed_run(run: ValidatedRun, **kwargs) -> tuple[UniversalBacktestResult, float]:
    started = time.perf_counter()
    result = execute_run(run, **kwargs)
    return result, time.perf_counter() - started
