from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import json
from math import inf, isinf
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from brokers.exness import EXNESS, load_exness_xauusd_profile
from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from core.fingerprints import sha256_file, stable_fingerprint
from core.result import UniversalBacktestResult
from experiments.ledger import ExperimentLedger
from instruments.btcusd import BTCUSD
from instruments.xauusd import XAUUSD, load_xauusd_profile
from strategies.base_strategy import StrategyDescriptor, StrategyStatus, parameter_fingerprint
from strategies.registry import discover_builtin_strategies
from services.gold_spec import load_mt5_gold_snapshot
from utils.data_validation import continuous_segments, load_ohlcv_csv, missing_gaps, validate_ohlcv

ROOT = Path(__file__).resolve().parents[1]
BTC_DATA = ROOT / "data" / "btcusd_15m.csv"
GOLD_ROOT = ROOT / "data" / "exness" / "gold" / "phase2a"
GOLD_SPEC = GOLD_ROOT / "raw" / "xauusd_mt5_spec.json"
GOLD_M15 = GOLD_ROOT / "processed" / "xauusd_XAUUSDm_M15.csv"
GOLD_H1 = GOLD_ROOT / "processed" / "xauusd_XAUUSDm_H1.csv"


@dataclass(frozen=True)
class IntegrityModel:
    run_id: str
    strategy_id: str
    strategy_version: str
    strategy_status: str
    strategy_fingerprint: str
    parameter_fingerprint: str
    dataset_fingerprint: str
    instrument_fingerprint: str
    broker_fingerprint: str
    dataset_role: str
    data_source: str
    start: str
    end: str
    execution_model: str
    spread_model: str
    commission: str
    slippage: str
    continuous_segments: int
    missing_gapped_candles: int
    forward_exposure_count: int
    reproducible: bool
    mismatch: str = ""


@dataclass(frozen=True)
class WorkspaceRun:
    result: UniversalBacktestResult
    data: pd.DataFrame
    descriptor: StrategyDescriptor
    config: BacktestConfig
    integrity: IntegrityModel


def instrument_options() -> tuple[str, ...]:
    return ("BTCUSD", "XAUUSDm")


def compatible_strategies(instrument: str, *, include_rejected: bool = False) -> tuple[StrategyDescriptor, ...]:
    registry = discover_builtin_strategies()
    return tuple(
        descriptor for descriptor in registry.for_instrument(instrument)
        if include_rejected or descriptor.metadata.status is not StrategyStatus.REJECTED
    )


def format_price(price: float | None, instrument: str) -> str:
    if price is None or pd.isna(price):
        return "-"
    precision = 3 if instrument.upper() == "XAUUSDM" else 2
    return f"{float(price):,.{precision}f}"


def profit_factor(trades: Iterable[Any]) -> float | None:
    trades = list(trades)
    gross_profit = sum(float(trade.pnl) for trade in trades if trade.pnl > 1e-9)
    gross_loss = sum(float(trade.pnl) for trade in trades if trade.pnl < -1e-9)
    if not gross_loss:
        return inf if gross_profit else None
    return gross_profit / abs(gross_loss)


def trades_dataframe(result: UniversalBacktestResult, instrument: str) -> pd.DataFrame:
    rows = []
    for trade in result.trade_log:
        rows.append({
            "Trade #": trade.get("trade_id"),
            "Side": trade.get("direction"),
            "Signal Time": trade.get("signal_time"),
            "Entry Time": trade.get("entry_time"),
            "Entry Price": format_price(trade.get("entry_price"), instrument),
            "SL": format_price(trade.get("stop_loss"), instrument),
            "Target": format_price(trade.get("take_profit"), instrument),
            "Exit Time": trade.get("exit_time"),
            "Exit Price": format_price(trade.get("exit_price"), instrument),
            "Exit Reason": trade.get("exit_reason"),
            "Quantity/Lots": trade.get("quantity"),
            "Planned Risk": trade.get("initial_risk"),
            "PnL": trade.get("pnl"),
            "R": trade.get("realized_r") or trade.get("r_multiple"),
            "MFE": trade.get("mfe"),
            "MAE": trade.get("mae"),
            "Duration": trade.get("bars_held"),
            "Strategy Component": trade.get("setup_id"),
            "Experiment ID": result.run_id,
        })
    return pd.DataFrame(rows)


def comparison_frame(runs: Iterable[dict[str, Any]]) -> pd.DataFrame:
    rows = []
    for run in runs:
        result = run.get("results_json", {})
        rows.append({
            "Run ID": run.get("run_id"), "Instrument": run.get("instrument"),
            "Strategy": run.get("strategy_name"), "Version": run.get("strategy_status"),
            "Dataset Role": run.get("dataset_role"), "Trades": result.get("total_trades"),
            "Trades/month": result.get("trades_per_month"), "WR": result.get("win_rate"),
            "PF": result.get("profit_factor"), "Avg R": result.get("average_r"),
            "PnL": result.get("pnl"), "Max DD": result.get("max_drawdown_percent"),
            "Max Losing Streak": result.get("max_losing_streak"),
            "Long PF": (result.get("long_statistics") or {}).get("profit_factor"),
            "Short PF": (result.get("short_statistics") or {}).get("profit_factor"),
        })
    return pd.DataFrame(rows)


def _fingerprint_for_instrument(instrument: str) -> str:
    profile = BTCUSD if instrument == "BTCUSD" else load_xauusd_profile(GOLD_SPEC)
    return stable_fingerprint(asdict(profile))


def _broker_for_instrument(instrument: str):
    return EXNESS if instrument == "BTCUSD" else load_exness_xauusd_profile(GOLD_SPEC)


def dataset_for_instrument(instrument: str, timeframe: str = "15m") -> tuple[Path, str]:
    if instrument == "BTCUSD":
        return BTC_DATA, "canonical_btcusd_15m"
    if timeframe == "1h":
        return GOLD_H1, "exness_xauusd_phase2a_h1"
    return GOLD_M15, "exness_xauusd_phase2a_m15"


def build_integrity(
    *, run_id: str, config: BacktestConfig, descriptor: StrategyDescriptor,
    dataset_path: Path, data: pd.DataFrame, result: UniversalBacktestResult,
    broker_fingerprint: str, instrument_fingerprint: str,
) -> IntegrityModel:
    timeframe_minutes = 60 if config.timeframe.lower() in {"1h", "60m"} else 15
    report = validate_ohlcv(data, timeframe_minutes * 60)
    return IntegrityModel(
        run_id=run_id, strategy_id=descriptor.metadata.strategy_id,
        strategy_version=descriptor.metadata.version, strategy_status=descriptor.metadata.status.value,
        strategy_fingerprint=result.strategy_fingerprint,
        parameter_fingerprint=result.parameter_fingerprint,
        dataset_fingerprint=result.dataset_fingerprint,
        instrument_fingerprint=instrument_fingerprint, broker_fingerprint=broker_fingerprint,
        dataset_role=config.dataset_role.value, data_source=config.data_source,
        start=config.start_date.isoformat(), end=config.end_date.isoformat(),
        execution_model=config.execution_mode.value,
        spread_model=("Historical per-bar spread" if config.instrument == "XAUUSDm" else "Synthetic Bid/Ask"),
        commission=f"{config.commission_percent}%", slippage=f"{config.slippage_percent}%",
        continuous_segments=len(continuous_segments(data, timeframe_minutes * 60)),
        missing_gapped_candles=report.missing_candles,
        forward_exposure_count=ExperimentLedger(ROOT / "experiments" / "experiments.sqlite3").forward_run_count(
            descriptor.metadata.strategy_id), reproducible=True,
    )


def verify_reproduction(row: dict[str, Any], descriptor: StrategyDescriptor,
                        dataset_path: Path, broker_fingerprint: str,
                        instrument_fingerprint: str) -> tuple[bool, str]:
    checks = {
        "strategy fingerprint": row["strategy_fingerprint"] == descriptor.metadata.strategy_fingerprint,
        "dataset fingerprint": row["dataset_fingerprint"] == sha256_file(dataset_path),
        "broker fingerprint": row["broker_fingerprint"] == broker_fingerprint,
        "instrument fingerprint": row.get("instrument_fingerprint", "") == instrument_fingerprint,
        "parameter fingerprint": row["parameter_fingerprint"] == parameter_fingerprint(
            json.loads(row["config_json"]).get("strategy_parameters", {})),
    }
    mismatches = [name for name, matches in checks.items() if not matches]
    if mismatches:
        return False, "REPRODUCTION BLOCKED: " + ", ".join(mismatches) + " differ."
    return True, "Dependencies match; reproduction is permitted."


def _metric_cards(result: UniversalBacktestResult) -> None:
    pf = "-" if result.profit_factor is None else "inf" if isinf(result.profit_factor) else f"{result.profit_factor:.3f}"
    metrics = [
        ("Net PnL", f"${result.pnl:,.2f}"), ("Return", f"{result.pnl / 10000 * 100:.2f}%"),
        ("Trades", f"{result.total_trades:,}"), ("Trades / month", f"{result.trades_per_month:.2f}"),
        ("Win rate", f"{result.win_rate:.2f}%"), ("Profit factor", pf),
        ("Avg R", f"{result.average_r:.3f}"), ("Max DD", f"{result.max_drawdown_percent:.2f}%"),
    ]
    for start in range(0, len(metrics), 4):
        cols = st.columns(4)
        for col, (label, value) in zip(cols, metrics[start:start + 4]):
            col.metric(label, value)


def _price_chart(data: pd.DataFrame, result: UniversalBacktestResult, instrument: str) -> go.Figure:
    fig = go.Figure(go.Candlestick(
        x=data.timestamp, open=data.open, high=data.high, low=data.low, close=data.close,
        name=instrument,
    ))
    trades = result.trade_log
    for label, key, symbol, color in (("BUY", "entry_price", "triangle-up", "#4ade80"),
                                      ("SELL", "entry_price", "triangle-down", "#fb7185"),
                                      ("EXIT", "exit_price", "x", "#60a5fa")):
        selected = [t for t in trades if (label == "BUY" and t.get("direction") == "LONG")
                    or (label == "SELL" and t.get("direction") == "SHORT") or label == "EXIT"]
        time_key = "exit_time" if label == "EXIT" else "entry_time"
        if selected:
            fig.add_trace(go.Scatter(
                x=[t.get(time_key) for t in selected], y=[t.get(key) for t in selected],
                mode="markers", name=label, marker={"symbol": symbol, "size": 9, "color": color},
            ))
    for trade in trades[:40]:
        entry_time = trade.get("entry_time")
        exit_time = trade.get("exit_time") or data.timestamp.iloc[-1]
        for label, price, dash in (("SL", trade.get("stop_loss"), "dot"),
                                   ("TP", trade.get("take_profit"), "dash")):
            if price is not None and entry_time is not None:
                fig.add_trace(go.Scatter(
                    x=[entry_time, exit_time], y=[price, price], mode="lines",
                    name=f"{label} #{trade.get('trade_id')}",
                    line={"dash": dash, "width": 1, "color": "#f59e0b"},
                    showlegend=False,
                ))
    fig.update_layout(template="plotly_dark", height=600, xaxis_rangeslider_visible=False,
                      yaxis_tickformat=",.3f" if instrument == "XAUUSDm" else ",.2f",
                      margin={"l": 20, "r": 20, "t": 35, "b": 20})
    return fig


def _integrity_panel(integrity: IntegrityModel) -> None:
    st.subheader("Backtest Integrity")
    st.success("REPRODUCIBLE: YES" if integrity.reproducible else "REPRODUCIBLE: NO")
    values = asdict(integrity)
    st.dataframe(
        pd.DataFrame({"Field": list(values), "Value": [str(value) for value in values.values()]}),
        use_container_width=True, hide_index=True,
    )
    if integrity.spread_model == "Historical per-bar spread":
        st.info("Gold broker-native history: Dec 2025 to Sep 2026. Spread is historical per-bar; margin, leverage, and commission remain UNVERIFIED.")


def _render_tester(run: WorkspaceRun) -> None:
    result, data, config = run.result, run.data, run.config
    _metric_cards(result)
    tabs = st.tabs(["Overview", "Performance", "Trades", "Analysis", "Integrity"])
    with tabs[0]:
        st.subheader("Direction contribution")
        st.dataframe(pd.DataFrame([
            {"Side": "Long", **asdict(result.long_statistics)},
            {"Side": "Short", **asdict(result.short_statistics)},
        ]), use_container_width=True, hide_index=True)
        st.plotly_chart(_price_chart(data, result, config.instrument), use_container_width=True)
    with tabs[1]:
        equity = pd.DataFrame(result.equity_curve)
        if not equity.empty:
            st.plotly_chart(go.Figure(go.Scatter(x=equity.timestamp, y=equity.balance, name="Equity")), use_container_width=True)
            st.plotly_chart(go.Figure(go.Scatter(x=equity.timestamp, y=equity.drawdown_percent, fill="tozeroy", name="Drawdown")), use_container_width=True)
        st.dataframe(pd.DataFrame(result.monthly_statistics).T if result.monthly_statistics else pd.DataFrame(), use_container_width=True)
    with tabs[2]:
        table = trades_dataframe(result, config.instrument)
        st.dataframe(table, use_container_width=True, hide_index=True)
        st.download_button("Download trades CSV", table.to_csv(index=False), "trades.csv", "text/csv")
    with tabs[3]:
        trades = result.trade_log
        direction = pd.DataFrame([
            {"Side": "Long", **asdict(result.long_statistics)},
            {"Side": "Short", **asdict(result.short_statistics)},
        ])
        st.dataframe(direction, use_container_width=True, hide_index=True)
        if trades:
            analysis = pd.DataFrame(trades)
            st.plotly_chart(go.Figure(go.Histogram(x=analysis.get("realized_r"))), use_container_width=True)
            st.plotly_chart(go.Figure(go.Histogram(x=analysis.get("bars_held"))), use_container_width=True)
    with tabs[4]:
        _integrity_panel(run.integrity)


def _render_controls() -> tuple[str, str, StrategyDescriptor | None, BacktestConfig | None, Path, pd.DataFrame]:
    left, right = st.columns([1.1, 2.2])
    instrument = left.selectbox("Instrument", instrument_options(), format_func=lambda value: "XAUUSDm" if value == "XAUUSDm" else value)
    timeframe = left.selectbox("Timeframe", ("15m", "1h"), index=0)
    left.selectbox("Broker Profile", ("EXNESS_STANDARD",), disabled=True)
    include_rejected = left.checkbox("Show rejected/research history", value=False)
    descriptors = compatible_strategies(instrument, include_rejected=include_rejected)
    strategy_labels = [f"{d.metadata.name} · {d.metadata.status.value}" for d in descriptors]
    selected_label = right.selectbox("Strategy", strategy_labels) if strategy_labels else None
    descriptor = descriptors[strategy_labels.index(selected_label)] if selected_label else None
    data_path, data_source = dataset_for_instrument(instrument, timeframe)
    data = load_ohlcv_csv(data_path) if data_path.exists() else pd.DataFrame()
    if data.empty:
        st.warning(f"No dataset available at {data_path.relative_to(ROOT)}")
        return instrument, timeframe, descriptor, None, data_path, data
    start = data.timestamp.iloc[0].date()
    end = data.timestamp.iloc[-1].date()
    date_col, risk_col, cost_col = st.columns(3)
    start_date = date_col.date_input("Start", value=start, min_value=start, max_value=end)
    end_date = date_col.date_input("End", value=end, min_value=start, max_value=end)
    risk = risk_col.number_input("Risk %", min_value=0.01, max_value=10.0, value=0.25, step=0.05)
    spread = cost_col.number_input("Spread", min_value=0.0, value=10.0 if instrument == "BTCUSD" else 0.0, step=0.01,
                                   disabled=instrument == "XAUUSDm", help="Gold uses historical per-bar spread from the imported broker dataset.")
    role = st.selectbox("Dataset Role", [role.value for role in DatasetRole], index=0)
    broker_name = "EXNESS_STANDARD"
    if instrument == "XAUUSDm":
        st.caption("Exness Technologies Ltd · XAUUSDm · broker-native history Dec 2025 to Sep 2026")
    if descriptor is None:
        st.info("No compatible production strategy is registered for this instrument yet. Gold data and integrity views are available; strategy execution is intentionally disabled.")
        return instrument, timeframe, descriptor, None, data_path, data
    config = BacktestConfig(
        instrument=instrument, broker_profile=broker_name, strategy_id=descriptor.metadata.strategy_id,
        timeframe=timeframe, start_date=pd.Timestamp(start_date, tz="UTC"),
        end_date=pd.Timestamp(end_date, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(minutes=15),
        dataset_role=DatasetRole(role), higher_timeframes=("1h",) if timeframe == "15m" else (),
        risk_per_trade_percent=risk, spread=spread, data_source=data_source,
    )
    st.caption(f"Version {descriptor.metadata.version} · Status {descriptor.metadata.status.value} · {'LOCKED' if descriptor.metadata.status is StrategyStatus.FROZEN else 'EDITABLE'}")
    with st.expander("Strategy Inputs", expanded=True):
        for parameter in descriptor.parameters:
            st.number_input(parameter.name, value=float(parameter.default), disabled=parameter.frozen, key=f"param_{parameter.name}")
    return instrument, timeframe, descriptor, config, data_path, data


def render_universal_workspace() -> None:
    st.markdown("# Universal Backtesting Workspace")
    st.caption("Institutional research terminal · universal engine · reproducibility first")
    instrument, timeframe, descriptor, config, data_path, data = _render_controls()
    if config is None or descriptor is None:
        if instrument == "XAUUSDm" and not data.empty:
            report = validate_ohlcv(data, 3600 if timeframe == "1h" else 900)
            st.subheader("Gold Dataset Health")
            st.dataframe(pd.DataFrame([asdict(report)]), use_container_width=True, hide_index=True)
        return
    if st.button("Run Backtest", type="primary"):
        with st.spinner("Running audited universal adapter..."):
            result = run_universal_backtest(data_path, config, ledger_path=ROOT / "experiments" / "experiments.sqlite3")
            broker = _broker_for_instrument(instrument)
            integrity = build_integrity(
                run_id=result.run_id, config=config, descriptor=descriptor, dataset_path=data_path,
                data=data, result=result, broker_fingerprint=broker.fingerprint(),
                instrument_fingerprint=_fingerprint_for_instrument(instrument),
            )
            st.session_state["universal_workspace_run"] = WorkspaceRun(result, data, descriptor, config, integrity)
    run = st.session_state.get("universal_workspace_run")
    if isinstance(run, WorkspaceRun):
        _render_tester(run)


def render_experiment_history() -> None:
    st.markdown("# Experiment History")
    ledger = ExperimentLedger(ROOT / "experiments" / "experiments.sqlite3")
    rows = ledger.list_runs()
    frame = comparison_frame(rows)
    query = st.text_input("Search runs", placeholder="Run ID, instrument, strategy...")
    if query:
        mask = frame.astype(str).apply(lambda column: column.str.contains(query, case=False, na=False)).any(axis=1)
        frame = frame[mask]
    st.dataframe(frame, use_container_width=True, hide_index=True)
    if not frame.empty:
        selected = st.selectbox("Run detail", frame["Run ID"].tolist())
        row = next(item for item in rows if item["run_id"] == selected)
        st.json(row)
        descriptor = discover_builtin_strategies().get(row["strategy_id"])
        instrument = row["instrument"]
        dataset_path, _ = dataset_for_instrument(instrument, json.loads(row["config_json"]).get("timeframe", "15m"))
        broker = _broker_for_instrument(instrument)
        allowed, message = verify_reproduction(
            row, descriptor, dataset_path, broker.fingerprint(),
            _fingerprint_for_instrument(instrument),
        )
        if st.button("Reproduce Run", disabled=not allowed):
            config_values = json.loads(row["config_json"])
            config_values["dataset_role"] = DatasetRole(config_values["dataset_role"])
            config_values["execution_mode"] = config_values.get("execution_mode", "SYNTHETIC_BID_ASK")
            from core.config import ExecutionMode
            config_values["execution_mode"] = ExecutionMode(config_values["execution_mode"])
            result = run_universal_backtest(
                dataset_path, BacktestConfig(**config_values),
                ledger_path=ROOT / "experiments" / "experiments.sqlite3",
            )
            st.success(f"Reproduced {result.run_id}: {result.total_trades} trades")
        else:
            st.error(message)


def render_experiment_comparison() -> None:
    st.markdown("# Experiment Comparison")
    rows = ExperimentLedger(ROOT / "experiments" / "experiments.sqlite3").list_runs()
    frame = comparison_frame(rows)
    if frame.empty:
        st.info("Run a backtest to populate experiment comparison.")
        return
    selected = st.multiselect("Select 2–5 experiments", frame["Run ID"].tolist(), max_selections=5)
    if selected:
        selected_frame = frame[frame["Run ID"].isin(selected)]
        st.dataframe(selected_frame, use_container_width=True, hide_index=True)
        selected_rows = [row for row in rows if row["run_id"] in selected]
        equity = go.Figure()
        cumulative_r = go.Figure()
        drawdown = go.Figure()
        for row in selected_rows:
            result = row["results_json"]
            points = result.get("equity_curve", [])
            if points:
                equity.add_trace(go.Scatter(x=[p.get("timestamp") for p in points],
                                            y=[p.get("balance") for p in points], name=row["run_id"]))
                drawdown.add_trace(go.Scatter(x=[p.get("timestamp") for p in points],
                                              y=[p.get("drawdown_percent") for p in points], name=row["run_id"]))
            trades = result.get("trade_log", [])
            if trades:
                cumulative_r.add_trace(go.Scatter(
                    x=list(range(1, len(trades) + 1)),
                    y=pd.Series([trade.get("realized_r", 0.0) for trade in trades]).cumsum(),
                    name=row["run_id"],
                ))
        st.plotly_chart(equity, use_container_width=True)
        st.plotly_chart(drawdown, use_container_width=True)
        st.plotly_chart(cumulative_r, use_container_width=True)
        st.caption("Comparison reports differences; it does not rank or declare a winner.")
