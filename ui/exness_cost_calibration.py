"""Read-only dashboard for frozen-trade Exness cost research."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from brokers.exness_standard_btcusdm import PROFILE
from research.exness_cost_recalibration import OUTPUT


def render_exness_cost_calibration(report_dir: Path = OUTPUT) -> None:
    st.header("Exness Cost Calibration")
    st.info("COST-CALIBRATED RESEARCH · NOT BROKER-NATIVE BACKTEST")
    required = ["cost_model_comparison.csv", "spread_sensitivity.csv",
                "lot_rounding_analysis.csv", "yearly_results.csv", "direction_results.csv"]
    if any(not (report_dir / name).exists() for name in required):
        st.caption("Frozen-trade Exness cost reports are not available yet.")
        return
    comparison = pd.read_csv(report_dir / required[0])
    sensitivity = pd.read_csv(report_dir / required[1])
    rounding = pd.read_csv(report_dir / required[2])
    yearly = pd.read_csv(report_dir / required[3])
    direction = pd.read_csv(report_dir / required[4])
    all_rows = comparison.loc[comparison.scope == "all"]
    old = all_rows.loc[(all_rows.view == "cost_only") &
                       (all_rows.scenario == "old_0.05pct_per_side")].iloc[0]
    calibrated = all_rows.loc[(all_rows.view == "cost_only") &
                              (all_rows.scenario == "spread_$10")].iloc[0]
    cards = st.columns(4)
    cards[0].metric("Frozen trades", f"{old.trades:,}")
    cards[1].metric("Old 0.05%/side net", f"${old.net_pnl:,.2f}")
    cards[2].metric("Exness $10 cost-only net", f"${calibrated.net_pnl:,.2f}")
    cards[3].metric("Below 0.01 lot", f"{(rounding.volume_status == 'BELOW_MINIMUM_VOLUME').sum():,}")
    st.caption(f"{PROFILE.broker} {PROFILE.account_type} · {PROFILE.mt5_symbol} · "
               f"1 lot = {PROFILE.btc_per_lot:g} BTC · Minimum {PROFILE.minimum_volume_lots:g} lot · "
               f"Step {PROFILE.volume_step_lots:g} lot · Commission $0")
    st.caption("Old generic model: 0.05% commission on entry notional and 0.05% on exit notional, with 0% slippage. Five Exness samples observed a $10/BTC spread; $10 is a CALIBRATED FIXED-SPREAD APPROXIMATION for this research only.")
    st.caption("A full round trip pays approximately one spread: $10 × BTC quantity, not $10 separately on entry and exit.")

    st.subheader("Cost comparison")
    st.dataframe(all_rows[["view", "scenario", "trades", "executable_trades",
                           "profit_factor", "average_r", "net_pnl", "cost_per_trade",
                           "cost_r_per_trade"]].round(4), hide_index=True, width="stretch")
    st.subheader("$5–$30 spread sensitivity")
    whole = sensitivity.loc[sensitivity.scope == "all"]
    fig = px.line(whole, x="spread_usd_per_btc", y="net_pnl", color="view", markers=True,
                  title="Frozen-trade net PnL by assumed spread", template="plotly_dark")
    st.plotly_chart(fig, width="stretch")
    st.dataframe(whole[["view", "spread_usd_per_btc", "trades", "executable_trades",
                        "gross_pre_cost_pnl", "spread_cost", "net_pnl", "profit_factor",
                        "average_r", "expectancy_r", "final_balance_arithmetic_reference"]].round(4),
                 hide_index=True, width="stretch")

    st.subheader("Theoretical quantity vs Exness lot size")
    cards = st.columns(3)
    cards[0].metric("Mean theoretical BTC", f"{rounding.theoretical_btc_qty.mean():.5f}")
    cards[1].metric("Mean floored BTC", f"{rounding.exness_btc_qty.mean():.5f}")
    cards[2].metric("Mean risk reduction", f"{rounding.risk_reduction_percent.mean():.2f}%")
    with st.expander("Per-trade lot rounding audit", expanded=False):
        st.dataframe(rounding[["segment_id", "trade_id", "signal_time", "direction",
                               "theoretical_btc_qty", "exness_btc_qty", "volume_status",
                               "planned_risk_before_rounding", "planned_risk_after_rounding",
                               "structural_risk_before_rounding", "structural_risk_after_rounding",
                               "risk_reduction_percent"]].round(6),
                     hide_index=True, width="stretch")

    st.subheader("Development vs forward validation")
    split = comparison.loc[(comparison.scenario == "spread_$10") & (comparison.scope != "all")]
    st.dataframe(split[["view", "scope", "trades", "executable_trades",
                        "profit_factor", "average_r", "net_pnl"]].round(4),
                 hide_index=True, width="stretch")
    st.subheader("Year by year · $10 spread")
    st.dataframe(yearly[["view", "year", "executable_trades", "profit_factor",
                         "average_r", "net_pnl"]].round(4), hide_index=True, width="stretch")
    st.subheader("Long vs short · $10 spread")
    st.dataframe(direction[["view", "direction", "executable_trades", "profit_factor",
                            "average_r", "net_pnl"]].round(4), hide_index=True, width="stretch")
    st.caption("Signals and historical movement remain from Bitstamp BTC/USD. This reprices frozen completed trades only. A broker-native backtest requires longer Exness Bid/Ask history and tick-level execution replay. The arithmetic final balance is not a compounded equity curve across data gaps.")
