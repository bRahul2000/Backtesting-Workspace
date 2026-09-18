"""Backtest controls and results for the existing Streamlit app."""
from __future__ import annotations

from math import ceil, isinf
from dataclasses import replace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine.backtester import run_backtest
from core.config import DatasetRole
from engine.metrics import calculate_metrics
from engine.models import BacktestResult, BacktestSettings, RiskCalculation, RiskMode, SameBarResolution
from strategies.demo_strategy import DemoEmaCrossover, DemoParameters
from strategies.btc_v2_setup_b import BtcV2SetupB, STAGES
from strategies.btc_v3_regime_adaptive import (BtcV3RegimeAdaptive, RANGE_SETUP_ID,
                                               TREND_SETUP_ID)
from strategies.btc_v3_a4_pullback_long import BtcV3A4PullbackLongFrozen
from strategies.btc_v3_t3_breakout_short import BtcV3T3BreakoutShortFrozen
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen
from strategies.registry import discover_builtin_strategies
from strategies.base_strategy import StrategyStatus
from ui.universal_controls import render_dynamic_parameters, render_status_badge, dataset_role_selectbox
from ui.btc_setup_b_controls import render_setup_b_controls
from ui.btc_v3_controls import render_v3_controls
from utils.data_validation import continuous_segments


MAX_CHART_CANDLES = 2_000
STRATEGY_OPTIONS = ("Demo EMA Strategy", "BTC V2.2 — Setup B Trend Breakout")
V3_STRATEGY_NAME = "BTC V3.0 — Regime Adaptive"
_UNIVERSAL_REGISTRY = discover_builtin_strategies()
UNIVERSAL_STRATEGY_NAMES = tuple(
    item.metadata.name for item in _UNIVERSAL_REGISTRY.all()
    if item.metadata.status is not StrategyStatus.REJECTED
)
FROZEN_V3_STRATEGY_NAMES = tuple(
    item.metadata.name for item in _UNIVERSAL_REGISTRY.all()
    if item.metadata.status is StrategyStatus.FROZEN
)
BACKTEST_STRATEGY_OPTIONS = (*STRATEGY_OPTIONS, V3_STRATEGY_NAME, *UNIVERSAL_STRATEGY_NAMES)


def selected_strategy(name: str, btc_params: object = None, demo_params: object = None,
                      v3_params: object = None):
    if name == STRATEGY_OPTIONS[1]:
        return BtcV2SetupB(btc_params)
    if name == V3_STRATEGY_NAME:
        return BtcV3RegimeAdaptive(v3_params)
    try:
        descriptor = _UNIVERSAL_REGISTRY.by_name(name)
    except KeyError:
        descriptor = None
    if descriptor is not None:
        return descriptor.create()
    if name == STRATEGY_OPTIONS[0]:
        return DemoEmaCrossover(demo_params)
    raise ValueError(f"Unknown strategy: {name}")


def setup_b_diagnostic_counts(result: BacktestResult,
                              diagnostics: dict[str, int]) -> dict[str, int]:
    counts = {stage: diagnostics.get(stage, 0) for stage in STAGES}
    counts.update({
        "Pending Orders Created": len(result.order_events),
        "Pending Filled": sum(e.status == "triggered" for e in result.order_events),
        "Pending Expired": sum(e.status == "expired" for e in result.order_events),
        "Pending Cancelled": sum(e.status == "cancelled" for e in result.order_events),
        "Completed Trades": len(result.trades),
    })
    return counts


def setup_b_run_data(data: pd.DataFrame, selected: pd.DataFrame) -> pd.DataFrame:
    """Keep same-segment warm-up and execution candles at original M15 size."""
    if selected.empty or len(continuous_segments(selected)) != 1:
        raise ValueError("Select one continuous BTC 15-minute period.")
    first, last = selected.timestamp.iloc[0], selected.timestamp.iloc[-1]
    segment = next(item for item in continuous_segments(data)
                   if item.start <= first <= item.end)
    return data.loc[data.timestamp.between(segment.start, last)].reset_index(drop=True)


def trades_table(result: BacktestResult) -> pd.DataFrame:
    columns = ["Trade ID", "Direction", "Signal Time", "Entry Time", "Entry Price",
               "Stop", "Target", "Exit Time", "Exit Price", "Exit Reason", "Quantity",
               "Risk $", "Net PnL $", "Net PnL %", "R Multiple", "Bars Held",
               "Planned Risk $", "Estimated Stop Loss $", "Realized PnL $",
               "Realized R", "Leverage Capped", "Entry Model",
               "Pending Trigger Price", "Pending Created Time", "Pending Expiry Time",
               "Pending Expiry Bar", "Actual Fill Time", "Actual Fill Price",
               "Gap Through Trigger", "Entry Gap Amount", "Setup / Strategy ID"]
    rows = []
    for trade in result.trades:
        rows.append([
            trade.trade_id, trade.direction.value, trade.signal_time, trade.entry_time,
            trade.entry_price, trade.stop_loss, trade.take_profit, trade.exit_time,
            trade.exit_price, trade.exit_reason, trade.quantity, trade.initial_risk,
            trade.pnl, trade.pnl_percent, trade.r_multiple, trade.bars_held,
            trade.planned_risk, trade.estimated_stop_loss, trade.pnl,
            trade.realized_r, trade.leverage_capped,
            trade.entry_model.value, trade.pending_trigger_price,
            trade.pending_created_time, trade.pending_expiry_time,
            trade.pending_expiry_bar_index, trade.actual_fill_time,
            trade.actual_fill_price, trade.gap_through_trigger,
            trade.entry_gap_amount, trade.setup_id,
        ])
    return pd.DataFrame(rows, columns=columns)


def order_events_table(result: BacktestResult) -> pd.DataFrame:
    columns = ["Signal Time", "Direction", "Trigger", "Stop", "Pending Created Time",
               "Expiry Time", "Expiry Bar", "Status", "Cancel Reason",
               "Fill Time", "Fill Price", "Setup / Strategy ID"]
    return pd.DataFrame([
        [event.signal_time, event.direction.value, event.trigger_price,
         event.stop_price, event.created_time, event.expiry_time,
         event.expiry_bar_index, event.status, event.cancel_reason,
         event.fill_time, event.fill_price, event.setup_id]
        for event in result.order_events
    ], columns=columns)


def equity_figure(result: BacktestResult, first_time: pd.Timestamp) -> go.Figure:
    points = result.equity_curve
    fig = go.Figure(go.Scatter(
        x=[point.timestamp if point.timestamp is not None else first_time for point in points],
        y=[point.balance for point in points], mode="lines+markers", name="Account equity",
    ))
    fig.update_layout(title="Equity Curve", xaxis_title="Trade exit time (UTC)",
                      yaxis_title="Account equity ($)", height=360)
    return fig


def drawdown_figure(result: BacktestResult, first_time: pd.Timestamp) -> go.Figure:
    points = result.equity_curve
    fig = go.Figure(go.Scatter(
        x=[point.timestamp if point.timestamp is not None else first_time for point in points],
        y=[point.drawdown_percent for point in points], mode="lines+markers",
        fill="tozeroy", name="Drawdown",
    ))
    fig.update_layout(title="Drawdown Curve", xaxis_title="Trade exit time (UTC)",
                      yaxis_title="Drawdown (%)", height=360)
    return fig


def _chart_candles(data: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    factor = max(1, ceil(len(data) / MAX_CHART_CANDLES))
    if factor == 1:
        return data, factor
    groups = pd.Series(range(len(data))) // factor
    chart = data.groupby(groups, sort=True).agg({
        "timestamp": "first", "open": "first", "high": "max",
        "low": "min", "close": "last", "volume": "sum",
    })
    return chart.reset_index(drop=True), factor


def price_figure(data: pd.DataFrame, result: BacktestResult) -> tuple[go.Figure, int]:
    chart, factor = _chart_candles(data)
    fig = go.Figure(go.Candlestick(
        x=chart["timestamp"], open=chart["open"], high=chart["high"],
        low=chart["low"], close=chart["close"], name="BTC/USD",
    ))
    for label, trades, time_attr, price_attr, color, symbol in (
        ("LONG ENTRY", [t for t in result.trades if t.direction.value == "LONG"],
         "entry_time", "entry_price", "#2ca02c", "triangle-up"),
        ("SHORT ENTRY", [t for t in result.trades if t.direction.value == "SHORT"],
         "entry_time", "entry_price", "#d62728", "triangle-down"),
        ("EXIT", result.trades, "exit_time", "exit_price", "#1f77b4", "x"),
    ):
        if trades:
            fig.add_trace(go.Scatter(
                x=[getattr(trade, time_attr) for trade in trades],
                y=[getattr(trade, price_attr) for trade in trades],
                mode="markers", name=label,
                marker={"color": color, "symbol": symbol, "size": 10},
                text=[f"Trade #{trade.trade_id}" for trade in trades],
            ))
    fig.update_layout(title="BTC/USD Price and Completed Trades", height=620,
                      xaxis_title="Candle open time (UTC)", yaxis_title="BTC/USD ($)",
                      xaxis_rangeslider_visible=False)
    return fig, factor


def _money(value: float) -> str:
    return f"${value:,.2f}"


def _subset_performance(trades) -> dict:
    winners = [trade for trade in trades if trade.pnl > 1e-9]
    losers = [trade for trade in trades if trade.pnl < -1e-9]
    profit = sum(trade.pnl for trade in winners)
    loss = sum(trade.pnl for trade in losers)
    count = len(trades)
    return {
        "trades": count,
        "win_rate": len(winners) / count * 100 if count else 0.0,
        "profit_factor": (profit / abs(loss) if losers else float("inf") if winners else None),
        "average_r": sum(trade.realized_r for trade in trades) / count if count else 0.0,
        "net_pnl": sum(trade.pnl for trade in trades),
    }


def _render_v3_split(result: BacktestResult, data: pd.DataFrame) -> None:
    trend = _subset_performance([t for t in result.trades if t.setup_id == TREND_SETUP_ID])
    range_ = _subset_performance([t for t in result.trades if t.setup_id == RANGE_SETUP_ID])
    long_ = _subset_performance([t for t in result.trades if t.direction.value == "LONG"])
    short_ = _subset_performance([t for t in result.trades if t.direction.value == "SHORT"])
    months = len(data) * 15 / (60 * 24 * 30.436875) if len(data) else 0.0
    metrics = calculate_metrics(result)
    st.subheader("BTC V3 Regime Split")
    overall = st.columns(4)
    overall[0].metric("Average R", f"{metrics.average_r_multiple:.4f}")
    overall[1].metric("Max Losing Streak", f"{metrics.max_consecutive_losses}")
    overall[2].metric("Trades / Month", f"{metrics.total_trades / months:.2f}" if months else "—")
    overall[3].metric("Execution", "$10 Synthetic Bid/Ask")
    table = pd.DataFrame([
        {"Split": "TREND", **trend},
        {"Split": "RANGE", **range_},
        {"Split": "LONG", **long_},
        {"Split": "SHORT", **short_},
    ])
    table = table.rename(columns={"trades": "Trades", "win_rate": "WR %",
                                  "profit_factor": "PF", "average_r": "Avg R",
                                  "net_pnl": "PnL $"})
    st.dataframe(table, width="stretch", hide_index=True)


def render_results(result: BacktestResult, data: pd.DataFrame, start, end,
                   strategy_name: str = "Demo EMA Strategy",
                   diagnostics: dict[str, int] | None = None) -> None:
    metrics = calculate_metrics(result)
    st.header("Backtest Results")
    st.caption(f"{strategy_name} · {start} to {end} UTC · Closed-trade equity")
    top = st.columns(3)
    top[0].metric("Total Trades", f"{metrics.total_trades:,}")
    top[1].metric("Win Rate", f"{metrics.win_rate_percent:.2f}%")
    top[2].metric("Net PnL", _money(metrics.net_pnl))
    bottom = st.columns(3)
    factor_text = ("—" if metrics.profit_factor is None else
                   "∞" if isinf(metrics.profit_factor) else f"{metrics.profit_factor:.2f}")
    bottom[0].metric("Profit Factor", factor_text)
    bottom[1].metric("Max Drawdown", f"{metrics.max_drawdown_percent:.2f}%")
    bottom[2].metric("Final Balance", _money(metrics.final_balance))

    if result.issues:
        with st.expander(f"Validation / execution notes ({len(result.issues)})"):
            for issue in result.issues[:100]:
                st.write(f"{issue.timestamp or 'Dataset'}: {issue.message}")
            if len(result.issues) > 100:
                st.caption(f"Showing first 100 of {len(result.issues)} notes.")
    if result.open_position:
        st.warning("A position remains open at the final candle. Its unrealized PnL is excluded from results.")
    capped_count = sum(trade.leverage_capped for trade in result.trades)
    if capped_count:
        st.caption(f"{capped_count} completed trade(s) were reduced by the maximum leverage limit.")

    st.subheader("Detailed Statistics")
    details = {
        "Winning Trades": metrics.winning_trades,
        "Losing Trades": metrics.losing_trades,
        "Breakeven Trades": metrics.breakeven_trades,
        "Gross Profit": _money(metrics.gross_profit),
        "Gross Loss": _money(metrics.gross_loss),
        "Total Return": f"{metrics.total_return_percent:.2f}%",
        "Average Trade": _money(metrics.average_trade),
        "Average Winner": _money(metrics.average_winner),
        "Average Loser": _money(metrics.average_loser),
        "Largest Winner": _money(metrics.largest_winner),
        "Largest Loser": _money(metrics.largest_loser),
        "Average R Multiple": f"{metrics.average_r_multiple:.2f}",
        "Expectancy $": _money(metrics.expectancy_dollars),
        "Expectancy R": f"{metrics.expectancy_r:.2f}",
        "Maximum Drawdown $": _money(metrics.max_drawdown_dollars),
        "Maximum Consecutive Wins": metrics.max_consecutive_wins,
        "Maximum Consecutive Losses": metrics.max_consecutive_losses,
        "Average Bars Held": f"{metrics.average_bars_held:.2f}",
        "Average Planned Risk $": _money(metrics.average_planned_risk),
        "Average Realized Losing R": f"{metrics.average_realized_losing_r:.2f}",
        "Largest Losing R": f"{metrics.largest_losing_r:.2f}",
    }
    st.dataframe(pd.DataFrame([(key, str(value)) for key, value in details.items()],
                            columns=["Statistic", "Value"]),
                 width="stretch", hide_index=True)

    if strategy_name == V3_STRATEGY_NAME:
        _render_v3_split(result, data)

    first_time = data["timestamp"].iloc[0]
    st.plotly_chart(equity_figure(result, first_time), width="stretch")
    st.plotly_chart(drawdown_figure(result, first_time), width="stretch")
    chart, factor = price_figure(data, result)
    st.plotly_chart(chart, width="stretch")
    if factor > 1:
        st.caption(f"Price chart aggregates up to {factor} source candles per plotted candle; trade markers retain exact times and prices.")

    st.subheader("Completed Trade Log")
    table = trades_table(result)
    st.dataframe(table, width="stretch", hide_index=True)
    st.download_button("Download Trades CSV", table.to_csv(index=False).encode("utf-8"),
                       file_name="demo_backtest_trades.csv", mime="text/csv",
                       disabled=table.empty)
    if result.order_events:
        st.subheader("Pending Order Diagnostics")
        st.caption("Triggered, expired, cancelled, and still-active orders are listed separately from completed trades.")
        st.dataframe(order_events_table(result), width="stretch", hide_index=True)
    if diagnostics is not None:
        st.subheader("Signal Diagnostics / Filter Funnel")
        if strategy_name == V3_STRATEGY_NAME:
            counts = dict(diagnostics)
            counts.update({
                "Pending Orders Created": len(result.order_events),
                "Pending Filled": sum(e.status == "triggered" for e in result.order_events),
                "Pending Expired": sum(e.status == "expired" for e in result.order_events),
                "Pending Cancelled": sum(e.status == "cancelled" for e in result.order_events),
                "Completed Trades": len(result.trades),
            })
            labels = [
                "Eligible candles", "Regime TREND", "Regime RANGE", "Regime CHOP",
                "Trend LONG Signals", "Trend SHORT Signals",
                "Range LONG Signals", "Range SHORT Signals",
                "Pending Orders Created", "Pending Filled", "Pending Expired",
                "Pending Cancelled", "Completed Trades",
            ]
            file_name = "btc_v3_diagnostics.csv"
        else:
            counts = setup_b_diagnostic_counts(result, diagnostics)
            labels = [*STAGES, "Pending Orders Created", "Pending Filled",
                      "Pending Expired", "Pending Cancelled", "Completed Trades"]
            file_name = "btc_setup_b_diagnostics.csv"
        diagnostic_table = pd.DataFrame(
            [(label, counts.get(label, 0)) for label in labels],
            columns=["Stage", "Candles / Orders / Trades"],
        )
        st.dataframe(diagnostic_table, width="stretch", hide_index=True)
        st.download_button("Download Signal Diagnostics CSV",
                           diagnostic_table.to_csv(index=False).encode("utf-8"),
                           file_name=file_name, mime="text/csv")


def render_backtest_panel(data: pd.DataFrame) -> None:
    st.header("Backtest")
    if data.empty:
        st.info("Download BTC/USD data before running a demo backtest.")
        return
    earliest = data["timestamp"].iloc[0].date()
    latest = data["timestamp"].iloc[-1].date()
    recent_start = max(earliest, latest - pd.Timedelta(days=30))
    with st.form("backtest_form"):
        top_controls = st.columns(3)
        instrument_name = top_controls[0].selectbox("Instrument", ("BTC/USD", "XAU/USD"))
        broker_profile = top_controls[1].selectbox("Broker Profile", ("EXNESS_STANDARD",))
        dataset_role = DatasetRole(top_controls[2].selectbox("Dataset Role", [role.value for role in DatasetRole]))
        if instrument_name == "BTC/USD":
            strategy_options = BACKTEST_STRATEGY_OPTIONS
        else:
            strategy_options = tuple()
            st.info("Gold profile exists as a Phase-1 placeholder. Exact Exness XAUUSD specifications and Gold strategies are not enabled yet.")
        strategy_name = st.selectbox(
            "Strategy", strategy_options if strategy_options else ("No XAUUSD strategy available yet",),
            disabled=not bool(strategy_options),
        )
        v2_selected = strategy_name == STRATEGY_OPTIONS[1]
        v3_selected = strategy_name == V3_STRATEGY_NAME
        universal_selected = strategy_name in UNIVERSAL_STRATEGY_NAMES
        frozen_v3_selected = strategy_name in FROZEN_V3_STRATEGY_NAMES
        v3_synthetic_selected = v3_selected or universal_selected
        btc_selected = v2_selected or v3_synthetic_selected
        date_cols = st.columns(2)
        start = date_cols[0].date_input("Backtest Start Date", value=recent_start,
                                       min_value=earliest, max_value=latest)
        end = date_cols[1].date_input("Backtest End Date", value=latest,
                                     min_value=earliest, max_value=latest)
        st.subheader("Account / Risk Settings")
        a, b, c = st.columns(3)
        starting_balance = a.number_input("Starting Balance ($)", min_value=0.01, value=10000.0)
        risk_mode = b.selectbox("Risk Mode", [mode.value for mode in RiskMode])
        risk_percent = c.number_input("Risk Per Trade (%)", min_value=0.001,
                                      value=0.25 if btc_selected else 1.0,
                                      key="btc_risk_percent" if btc_selected else "demo_risk_percent")
        d, e, f = st.columns(3)
        fixed_risk = d.number_input("Fixed Risk ($)", min_value=0.01, value=100.0)
        rr = e.number_input("Risk Reward Ratio", min_value=0.01,
                            value=3.0 if btc_selected else 2.0,
                            key="btc_reward" if btc_selected else "demo_reward")
        commission = f.number_input(
            "Commission (%)", min_value=0.0, max_value=99.0,
            value=0.0 if v3_synthetic_selected else 0.05 if v2_selected else 0.0,
            key="v3_commission" if v3_synthetic_selected else "btc_commission" if v2_selected else "demo_commission",
            disabled=v3_synthetic_selected,
        )
        g, h = st.columns(2)
        slippage = g.number_input("Slippage (%)", min_value=0.0, max_value=99.0, value=0.0)
        same_bar = h.selectbox("Same-Bar Resolution", [mode.value for mode in SameBarResolution])
        sizing_cols = st.columns(3)
        risk_calculation = sizing_cols[0].selectbox(
            "Risk Calculation", [mode.value for mode in RiskCalculation],
        )
        max_leverage = sizing_cols[1].number_input(
            "Maximum Leverage", min_value=0.01, value=1.0,
        )
        min_quantity = sizing_cols[2].number_input(
            "Minimum Quantity", min_value=0.0, value=0.0, format="%.8f",
        )
        st.caption(
            "Price Distance Only excludes trading costs from configured risk. "
            "Estimated Total Stop Loss attempts to keep projected stop-out loss, "
            "including configured costs, near the selected risk amount. "
            "An adverse gap can still cause a larger loss."
        )
        st.subheader("Strategy Parameters")
        if v2_selected:
            st.caption("Pine commission defaults to 0.05%. Its two-tick slippage cannot be expressed exactly by the audited percentage-slippage model; set a percentage above if desired.")
            btc_params = render_setup_b_controls()
        elif v3_selected:
            st.caption("V3 research execution uses the audited synthetic Exness-like Bid/Ask replay: $10/BTC spread and $0 separate commission. Forward data is not used automatically.")
            v3_params = render_v3_controls()
        elif strategy_name in UNIVERSAL_STRATEGY_NAMES:
            descriptor = _UNIVERSAL_REGISTRY.by_name(strategy_name)
            render_status_badge(descriptor)
            render_dynamic_parameters(descriptor)
            if descriptor.metadata.status is StrategyStatus.FROZEN:
                st.caption("Frozen validated strategy: parameters are read-only. Execution remains the audited synthetic Exness Bid/Ask path.")
            else:
                st.caption("Historical research/rejected strategy. Universal metadata is available; production use is not implied.")
        else:
            st.caption("Demo EMA crossover validates the engine.")
            p1, p2, p3, p4 = st.columns(4)
            fast = p1.number_input("Fast EMA", min_value=1, value=20, step=1)
            slow = p2.number_input("Slow EMA", min_value=2, value=50, step=1)
            atr_length = p3.number_input("ATR Length", min_value=1, value=14, step=1)
            stop_multiple = p4.number_input("Stop ATR Multiplier", min_value=0.01, value=1.5)
        clicked = st.form_submit_button("RUN BACKTEST", type="primary")

    if clicked:
        try:
            if start > end:
                raise ValueError("Backtest start date must be on or before end date.")
            selected = data.loc[(data["timestamp"].dt.date >= start) &
                                (data["timestamp"].dt.date <= end)].reset_index(drop=True)
            if selected.empty:
                raise ValueError("The selected dates have no saved candles.")
            if btc_selected:
                segments = continuous_segments(selected)
                if len(segments) > 1:
                    largest = max(segments, key=lambda segment: segment.candles)
                    raise ValueError(
                        f"The selected BTC range contains {len(segments)} separate 15-minute "
                        f"segments. Select one continuous period; the largest is "
                        f"{largest.start} to {largest.end} ({largest.candles:,} candles)."
                    )
            if v2_selected:
                params = replace(btc_params, reward_multiple=float(rr))
                strategy = selected_strategy(strategy_name, params, None)
                run_data = setup_b_run_data(data, selected)
            elif v3_selected:
                params = replace(v3_params, reward_multiple=float(rr))
                strategy = selected_strategy(strategy_name, None, None, params)
                run_data = setup_b_run_data(data, selected)
            elif universal_selected:
                strategy = selected_strategy(strategy_name)
                run_data = setup_b_run_data(data, selected)
            else:
                params = DemoParameters(int(fast), int(slow), int(atr_length), float(stop_multiple))
                strategy = selected_strategy(strategy_name, None, params)
                run_data = data
            settings = BacktestSettings(
                starting_balance=float(starting_balance), risk_mode=RiskMode(risk_mode),
                risk_percent=float(risk_percent), fixed_risk_dollars=float(fixed_risk),
                risk_reward_ratio=float(rr), commission_percent=float(commission),
                slippage_percent=float(slippage), same_bar_resolution=SameBarResolution(same_bar),
                risk_calculation=RiskCalculation(risk_calculation),
                max_leverage=float(max_leverage), min_quantity=float(min_quantity),
            )
            start_time = pd.Timestamp(start, tz="UTC")
            end_time = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(minutes=15)
            if v3_synthetic_selected:
                from research.v3_regime_adaptive_baseline import run_v3_synthetic_segment
                if frozen_v3_selected:
                    v3_settings = replace(
                        settings, risk_mode=RiskMode.PERCENT_EQUITY, risk_percent=0.25,
                        risk_reward_ratio=3.0, commission_percent=0.0, slippage_percent=0.0,
                        same_bar_resolution=SameBarResolution.SL_FIRST,
                        risk_calculation=RiskCalculation.ESTIMATED_TOTAL_STOP_LOSS,
                        max_leverage=1.0, min_quantity=0.0,
                    )
                else:
                    v3_settings = replace(settings, commission_percent=0.0, slippage_percent=0.0)
                result = run_v3_synthetic_segment(
                    run_data, strategy, 10.0, start_time, v3_settings)
            else:
                result = run_backtest(run_data, strategy, settings,
                                      trade_start=start_time, trade_end=end_time)
            diagnostics = dict(strategy.diagnostics) if (v2_selected or v3_selected) else None
            st.session_state["demo_backtest"] = (result, selected, start, end,
                                                  strategy_name, diagnostics)
        except ValueError as exc:
            st.error(f"Backtest could not run: {exc}")
    if "demo_backtest" in st.session_state:
        render_results(*st.session_state["demo_backtest"])
