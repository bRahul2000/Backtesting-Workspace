from __future__ import annotations

from dataclasses import asdict
from math import inf
from pathlib import Path
from statistics import mean
from typing import Iterable

import pandas as pd

from brokers.exness import EXNESS
from core.config import BacktestConfig, DatasetRole, ExecutionMode
from core.fingerprints import sha256_file, stable_fingerprint
from core.result import DirectionStatistics, UniversalBacktestResult
from engine.metrics import calculate_metrics
from engine.diagnostics import enrich_result
from engine.models import BacktestSettings, Direction, RiskCalculation, RiskMode, SameBarResolution
from experiments.ledger import ExperimentLedger
from instruments.btcusd import BTCUSD
from instruments.xauusd import XAUUSD
from research.exness_cost_calibrated import run_synthetic_segment
from research.v3_regime_adaptive_baseline import add_closed_trade_equity
from strategies.base_strategy import AuditedStrategyAdapter, effective_parameter_payload, parameter_fingerprint
from strategies.diagnostics import DiagnosticStrategyObserver
from strategies.btc_v3_core_diagnostics import (
    CoreFunnelReport, DEFAULT_XRAY_LIMIT as XRAY_ROW_LIMIT,
    instrument as instrument_strategy, lifecycle_from_order_events,
)
from strategies.registry import discover_builtin_strategies
from utils.data_validation import continuous_segments, load_ohlcv_csv

MONTH_DAYS = 30.436875


def _profit_factor(trades) -> float | None:
    profit = sum(t.pnl for t in trades if t.pnl > 1e-9)
    loss = sum(t.pnl for t in trades if t.pnl < -1e-9)
    return profit / abs(loss) if loss else inf if profit else None


def _direction_stats(trades) -> DirectionStatistics:
    trades = list(trades)
    return DirectionStatistics(
        trades=len(trades),
        win_rate=(100 * sum(t.pnl > 1e-9 for t in trades) / len(trades)) if trades else 0.0,
        profit_factor=_profit_factor(trades),
        average_r=(mean(t.realized_r for t in trades) if trades else 0.0),
        pnl=sum(t.pnl for t in trades),
    )


def _loss_streak(trades) -> int:
    current = worst = 0
    for trade in trades:
        if trade.pnl < -1e-9:
            current += 1
            worst = max(worst, current)
        elif abs(trade.pnl) > 1e-9:
            current = 0
    return worst


def _group_stats(trades, key):
    buckets = {}
    for trade in trades:
        label = key(trade)
        buckets.setdefault(label, []).append(trade)
    out = {}
    for label, group in sorted(buckets.items()):
        out[str(label)] = {
            "trades": len(group), "win_rate": 100 * sum(t.pnl > 1e-9 for t in group) / len(group),
            "profit_factor": _profit_factor(group), "average_r": mean(t.realized_r for t in group),
            "pnl": sum(t.pnl for t in group),
        }
    return out



def _broker_native_spread(path: Path, data: pd.DataFrame) -> pd.Series:
    """Real per-bar spread from a broker-native export, keyed by timestamp.

    Requires an explicit spread_price column: a broker-native run must never
    silently fall back to the calibrated constant.
    """
    raw = pd.read_csv(path)
    columns = {name.lower().strip(): name for name in raw.columns}
    stamp = columns.get("timestamp") or columns.get("timestamp_utc")
    price = columns.get("spread_price")
    if stamp is None or price is None:
        raise ValueError(
            "spread_source=BROKER_NATIVE_PER_BAR requires timestamp and spread_price "
            f"columns in {path.name}; found {sorted(raw.columns)}.")
    series = pd.Series(pd.to_numeric(raw[price], errors="coerce").to_numpy(),
                       index=pd.to_datetime(raw[stamp], utc=True))
    series = series[~series.index.duplicated(keep="last")]
    missing = [stamp for stamp in data.timestamp if stamp not in series.index]
    if missing:
        raise ValueError(f"{len(missing)} candles have no broker spread; first {missing[0]}.")
    if series.isna().any() or (series.dropna() < 0).any():
        raise ValueError("Broker spread column contains missing or negative values.")
    return series


def _trade_row(trade):
    row = asdict(trade)
    for key, value in list(row.items()):
        if hasattr(value, "value"):
            row[key] = value.value
        elif isinstance(value, pd.Timestamp):
            row[key] = value.isoformat()
    row["realized_r"] = trade.realized_r
    return row


def _equity_rows(results):
    rows = []
    for segment_index, result in enumerate(results, 1):
        for point in result.equity_curve:
            rows.append({
                "segment": segment_index,
                "timestamp": point.timestamp.isoformat() if point.timestamp is not None else None,
                "trade_id": point.trade_id, "balance": point.balance,
                "peak_equity": point.peak_equity, "drawdown_dollars": point.drawdown_dollars,
                "drawdown_percent": point.drawdown_percent,
            })
    return rows


def run_universal_backtest(
    data_path: str | Path,
    config: BacktestConfig,
    *,
    ledger_path: str | Path | None = None,
) -> UniversalBacktestResult:
    """Run through an adapter that delegates execution to the audited replay.

    No fill, gap, stop/target, risk, or Bid/Ask semantics are reimplemented here.
    """
    registry = discover_builtin_strategies()
    descriptor = registry.get(config.strategy_id)
    if config.instrument not in descriptor.metadata.supported_instruments:
        raise ValueError(f"{descriptor.metadata.name} does not support {config.instrument}.")
    if config.instrument != "BTCUSD":
        raise ValueError("Phase 1 Gold profile is a placeholder; no XAUUSD execution run is enabled yet.")
    if config.broker_profile != EXNESS.broker_id:
        raise ValueError("Phase 1 audited adapter currently supports EXNESS_STANDARD only.")
    broker_instrument = EXNESS.instrument(config.instrument)
    if not broker_instrument.known:
        raise ValueError(f"Broker specification for {config.instrument} is incomplete.")
    if config.execution_mode is not ExecutionMode.SYNTHETIC_BID_ASK:
        raise ValueError("Frozen V3 migration must use the audited synthetic Bid/Ask adapter.")
    if config.max_simultaneous_positions != 1:
        raise ValueError("Audited engine migration supports one global position/pending order.")

    path = Path(data_path)
    data = load_ohlcv_csv(path)
    start, end = pd.Timestamp(config.start_date), pd.Timestamp(config.end_date)
    data = data.loc[data.timestamp.between(start, end)].reset_index(drop=True)
    if data.empty:
        raise ValueError("No data in requested date range.")
    # Opt-in broker-native spread. load_ohlcv_csv keeps only the OHLCV columns,
    # so the real per-bar spread is read from the same file separately. The
    # default CONSTANT path is untouched.
    broker_spread = _broker_native_spread(path, data) if \
        config.spread_source == "BROKER_NATIVE_PER_BAR" else None

    # Fingerprint the *effective* configuration (defaults merged with overrides),
    # not the raw override mapping — a default-only run must not fingerprint as
    # an empty payload. See strategies.base_strategy.effective_parameter_payload.
    parameter_hash = parameter_fingerprint(effective_parameter_payload(descriptor, config.strategy_parameters))
    dataset_hash = sha256_file(path)
    broker_hash = EXNESS.fingerprint()
    instrument_hash = stable_fingerprint(asdict(BTCUSD if config.instrument == "BTCUSD" else XAUUSD))
    adapter = AuditedStrategyAdapter(descriptor)
    ledger = ExperimentLedger(ledger_path or Path("experiments") / "experiments.sqlite3")
    config_dict = asdict(config)
    config_dict["dataset_role"] = config.dataset_role.value
    config_dict["execution_mode"] = config.execution_mode.value
    run_id = ledger.start_run(
        strategy_id=descriptor.metadata.strategy_id,
        strategy_version=descriptor.metadata.version,
        strategy_name=descriptor.metadata.name,
        strategy_status=descriptor.metadata.status.value,
        strategy_fingerprint=descriptor.metadata.strategy_fingerprint,
        parameter_fingerprint=parameter_hash,
        dataset_fingerprint=dataset_hash,
        broker_fingerprint=broker_hash,
        instrument_fingerprint=instrument_hash,
        broker_profile=config.broker_profile,
        instrument=config.instrument,
        date_start=start.isoformat(), date_end=end.isoformat(),
        dataset_role=config.dataset_role.value, config=config_dict, notes=config.notes,
    )

    settings = BacktestSettings(
        starting_balance=config.initial_capital,
        risk_mode=RiskMode.PERCENT_EQUITY if config.risk_mode == "PERCENT_EQUITY" else RiskMode.FIXED_DOLLARS,
        risk_percent=config.risk_per_trade_percent,
        fixed_risk_dollars=config.fixed_risk_dollars,
        # Strategy-defined signals use the audited fixed-R target logic; the
        # config default is 3.0, matching the V3 benchmark every prior run used.
        risk_reward_ratio=config.risk_reward_ratio,
        commission_percent=config.commission_percent,
        slippage_percent=config.slippage_percent,
        same_bar_resolution=SameBarResolution.SL_FIRST,
        risk_calculation=RiskCalculation.ESTIMATED_TOTAL_STOP_LOSS,
        max_leverage=config.leverage,
        min_quantity=0.0,
    )

    pooled, results, usable_months, xray_evaluations = [], [], 0.0, []
    funnel = CoreFunnelReport()
    order_status = {}
    for segment in continuous_segments(data):
        frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        trade_start = descriptor.warmup_resolver(segment.start) if descriptor.warmup_resolver else segment.start
        if trade_start > segment.end:
            continue
        inner_strategy = instrument_strategy(
            adapter.create_legacy_strategy(config.strategy_parameters),
            descriptor.metadata.strategy_id)
        strategy = DiagnosticStrategyObserver(inner_strategy, descriptor.metadata.strategy_id)
        segment_spread = (config.spread if broker_spread is None
                          else [broker_spread[stamp] for stamp in frame.timestamp])
        result = run_synthetic_segment(frame, strategy, segment_spread, trade_start, settings)
        # Strategies may optionally emit their own rule-level diagnostics/X-Ray evaluations
        # (see strategies/btc_pb1_shallow_pullback.py). This never changes fill/risk/target
        # behavior — frozen strategies without these attributes are unaffected.
        result.diagnostic_events = list(strategy.events) + list(getattr(inner_strategy, "diagnostic_events", ()))
        xray_evaluations.extend(getattr(inner_strategy, "xray_evaluations", ()))
        segment_funnel = getattr(inner_strategy, "report", None)
        if isinstance(segment_funnel, CoreFunnelReport):
            for child, counts in lifecycle_from_order_events(result.order_events).items():
                segment_funnel.children[child].lifecycle.update(counts)
            funnel.merge(segment_funnel)
        # Excursion enrichment mirrors the execution spread so short-side
        # excursions are measured against the same Ask stream that filled them.
        enrich_result(result, frame,
                      spread=config.spread if broker_spread is None
                      else float(pd.Series(segment_spread).median()))
        add_closed_trade_equity(result)
        results.append(result)
        pooled.extend(result.trades)
        usable_months += len(frame.loc[frame.timestamp >= trade_start]) * 15 / (60 * 24 * MONTH_DAYS)
        for event in result.order_events:
            order_status[event.status] = order_status.get(event.status, 0) + 1

    if not results:
        raise ValueError("No continuous segment had enough warm-up data for this strategy.")

    #--- Each segment gets its own observer, so the observer's own cap bounds a
    #--- segment, not a run. The whole result is persisted into the experiment
    #--- ledger, so the run-level cap is the one that matters.
    if len(xray_evaluations) > XRAY_ROW_LIMIT:
        del xray_evaluations[XRAY_ROW_LIMIT:]
        funnel.xray_truncated = True

    max_dd = max(calculate_metrics(item).max_drawdown_percent for item in results)
    total = len(pooled)
    # "trade_entered" is emitted generically by DiagnosticStrategyObserver for every
    # strategy. total_entries can exceed total_trades (closed only) when a position
    # is still open when its continuous segment ends — the engine never fabricates
    # an exit at a segment/dataset boundary, so that position has no closed Trade.
    total_entries = sum(1 for segment in results for event in segment.diagnostic_events
                        if event.stage == "trade_entered")
    open_positions_at_end = [
        {
            "segment_index": index, "trade_id": segment.open_position.trade_id,
            "direction": segment.open_position.direction.value,
            "setup_id": segment.open_position.setup_id,
            "entry_time": segment.open_position.entry_time.isoformat(),
            "entry_price": segment.open_position.entry_price,
            "state": "OPEN_AT_DATASET_END",
            "reason": "Position remained open when its continuous data segment ended; "
                      "no closed Trade exists because the engine does not fabricate "
                      "exits at segment or dataset boundaries.",
        }
        for index, segment in enumerate(results, 1) if segment.open_position is not None
    ]
    forward_count = ledger.forward_run_count(descriptor.metadata.strategy_id)
    forward_warning = None
    if (config.dataset_role is DatasetRole.FORWARD_VALIDATION
            and descriptor.metadata.status.value in {"RESEARCH", "CANDIDATE"}
            and forward_count > 1):
        forward_warning = (
            f"Forward validation has been run {forward_count} times for this strategy/version. "
            "Repeated forward inspection can contaminate validation."
        )

    result = UniversalBacktestResult(
        run_id=run_id,
        strategy_fingerprint=descriptor.metadata.strategy_fingerprint,
        parameter_fingerprint=parameter_hash,
        dataset_fingerprint=dataset_hash,
        broker_fingerprint=broker_hash,
        instrument_fingerprint=instrument_hash,
        instrument=config.instrument,
        period={"start": start.isoformat(), "end": end.isoformat()},
        dataset_role=config.dataset_role.value,
        total_trades=total,
        total_entries=total_entries,
        open_positions_at_end=open_positions_at_end,
        trades_per_month=total / usable_months if usable_months else 0.0,
        win_rate=100 * sum(t.pnl > 1e-9 for t in pooled) / total if total else 0.0,
        profit_factor=_profit_factor(pooled),
        average_r=mean(t.realized_r for t in pooled) if pooled else 0.0,
        pnl=sum(t.pnl for t in pooled),
        max_drawdown_percent=max_dd,
        max_losing_streak=max((_loss_streak(item.trades) for item in results), default=0),
        long_statistics=_direction_stats(t for t in pooled if t.direction is Direction.LONG),
        short_statistics=_direction_stats(t for t in pooled if t.direction is Direction.SHORT),
        yearly_statistics=_group_stats(pooled, lambda t: t.entry_time.year),
        monthly_statistics=_group_stats(pooled, lambda t: t.entry_time.strftime("%Y-%m")),
        trade_log=[_trade_row(t) for t in pooled],
        equity_curve=_equity_rows(results),
        mfe_mae={"available": bool(pooled), "model": "BAR_BASED_APPROXIMATION"},
        signal_diagnostics=[asdict(event) for segment in results for event in segment.diagnostic_events],
        xray_diagnostics=[asdict(event) for event in xray_evaluations],
        core_funnel=funnel.to_payload() if funnel.total_bars else {},
        execution_ambiguities=[asdict(item) for segment in results for item in segment.execution_ambiguities],
        excursion_model="BAR_BASED_APPROXIMATION" if pooled else "UNAVAILABLE",
        execution_diagnostics={
            "segments": len(results), "order_events": order_status,
            "execution_adapter": "research.exness_cost_calibrated.run_synthetic_segment",
            "spread_price": config.spread,
            "commission_percent": config.commission_percent,
            "forward_runs_for_strategy": forward_count,
            "forward_validation_warning": forward_warning,
            "forward_exposure_warning": ledger.exposure_warning(
                descriptor.metadata.strategy_id, parameter_hash, config.dataset_role.value
            ),
        },
        legacy_segment_results=results,
    )
    ledger.finish_run(run_id, result.as_dict())
    return result
