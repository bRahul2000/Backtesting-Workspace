"""Read-only dashboard for the original standalone Pine Setup A research."""
from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from research.exness_setup_a_validation import REPORT


def render_setup_a_native_validation() -> None:
    st.divider()
    st.header("Setup A Native Validation")
    st.caption("FROZEN ORIGINAL V2.2 RULES · NO OPTIMIZATION · Standalone Setup A")
    summary_path = REPORT / "setup_a_validation_summary.json"
    native_path = REPORT / "native_results.csv"
    if not summary_path.exists() or not native_path.exists():
        st.caption("Standalone Setup A research reports are not available yet.")
        return
    summary = json.loads(summary_path.read_text())
    native = pd.read_csv(native_path)
    with st.expander("Pine rule parity", expanded=False):
        rule_path = REPORT / "pine_rule_map.md"
        if rule_path.exists():
            st.markdown(rule_path.read_text())
    full = native.loc[(native.feed == "exness_native") & (native.scope == "full_native")]
    zero = full.loc[full.cost_view == "zero_cost"].iloc[0]
    st.subheader("Exness zero-cost")
    cards = st.columns(4)
    cards[0].metric("Final signals", int(zero.signals))
    cards[1].metric("Completed trades", int(zero.trades))
    cards[2].metric("Profit factor", f"{zero.profit_factor:.3f}")
    cards[3].metric("Average R", f"{zero.average_r:.3f}")
    st.caption(f"Win rate {zero.win_rate_percent:.2f}% · Net PnL ${zero.net_pnl:,.2f} · "
               f"Worst segment DD {zero.worst_segment_dd_percent:.2f}%")
    st.subheader("Exness cost sensitivity")
    st.info("BAR SPREAD COST = LOWER-BOUND RESEARCH, NOT TICK-EXACT EXECUTION")
    st.dataframe(full[["cost_view", "trades", "profit_factor", "average_r", "net_pnl"]].round(4),
                 hide_index=True, width="stretch")
    st.subheader("Year stability")
    yearly = pd.read_csv(REPORT / "yearly_results.csv")
    st.dataframe(yearly[["year", "partial_year", "cost_view", "trades",
                         "win_rate_percent", "profit_factor", "average_r", "net_pnl"]].round(4),
                 hide_index=True, width="stretch")
    st.subheader("Long vs Short")
    direction = pd.read_csv(REPORT / "direction_results.csv")
    st.dataframe(direction[["direction", "cost_view", "trades", "win_rate_percent",
                            "profit_factor", "average_r", "net_pnl"]].round(4),
                 hide_index=True, width="stretch")
    st.subheader("Exness vs Bitstamp signal overlap")
    overlap = summary["signal_overlap"]
    st.caption(f"Exact {overlap['exact_matches']} · Near ±1 M15 {overlap['near_matches']} · "
               f"Exness-only {overlap['exness_only']} · Bitstamp-only {overlap['bitstamp_only']} · "
               f"Opposite {overlap['opposite']}")
    cards = st.columns(2)
    cards[0].metric("Exact match rate", f"{overlap['exact_signal_match_rate'] * 100:.2f}%")
    cards[1].metric("Exact + near rate", f"{overlap['exact_plus_near_match_rate'] * 100:.2f}%")
    st.dataframe(native.loc[native.scope == "exact_common_timestamps",
                            ["feed", "signals", "trades", "win_rate_percent",
                             "profit_factor", "average_r", "net_pnl"]].round(4),
                 hide_index=True, width="stretch")
    st.subheader("Setup A vs Setup B, separate strategies")
    comparison = pd.read_csv(REPORT / "setup_a_vs_b.csv")
    st.dataframe(comparison.round(4), hide_index=True, width="stretch")
    figure = px.bar(comparison, x="setup", y="profit_factor", color="cost_view",
                    barmode="group", template="plotly_dark",
                    title="Standalone PF on Exness Bid M15")
    st.plotly_chart(figure, width="stretch")
    lots = summary["lot_sizing"]
    st.caption(f"Filled positions: {lots['theoretical_filled_positions']} theoretical; "
               f"{lots['executable_filled_positions']} at or above 0.01 lot; "
               f"{lots['below_minimum_filled_positions']} below minimum. "
               "Lot rounding is a separate sizing audit; the PnL table retains the audited research sizing convention.")
