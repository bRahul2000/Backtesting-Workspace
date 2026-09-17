"""Read-only comparison of Exness Bid M15 and Bitstamp Setup B research."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from services.exness_m15 import REPORT


def render_exness_native_validation(report_dir: Path = REPORT) -> None:
    st.header("Exness vs Bitstamp")
    st.caption("BROKER-NATIVE PRICE DATA · Original BTC V2.2 Setup B · No parameter changes")
    summary_path = report_dir / "native_validation_summary.json"
    results_path = report_dir / "native_setup_b_results.csv"
    if not summary_path.exists() or not results_path.exists():
        st.caption("Exness native validation reports are not available yet.")
        return
    summary = json.loads(summary_path.read_text())
    results = pd.read_csv(results_path)
    price = summary["price_feed"]
    signals = summary["signals"]
    st.subheader("Exact timestamp price comparison")
    cards = st.columns(4)
    cards[0].metric("Common candles", f"{price['common_candles']:,}")
    cards[1].metric("Median close gap", f"${price['median_absolute_close_difference_usd']:.2f}")
    cards[2].metric("Median relative gap", f"{price['median_relative_close_difference_percent']:.4f}%")
    cards[3].metric("Return correlation", f"{price['return_correlation']:.4f}")
    st.caption(f"Exness-only timestamps {price['exness_only_timestamps']:,} · "
               f"Bitstamp-only timestamps {price['bitstamp_only_timestamps']:,} · "
               f"Close correlation {price['close_correlation']:.6f}. No interpolation.")
    differences = pd.DataFrame(price["absolute_difference_summary"]).T.reset_index().rename(columns={"index": "price_field"})
    st.dataframe(differences.round(4), hide_index=True, width="stretch")

    st.subheader("Signal overlap")
    cards = st.columns(4)
    cards[0].metric("Exness signals", signals["exness_signals"])
    cards[1].metric("Bitstamp signals", signals["bitstamp_signals"])
    cards[2].metric("Exact", signals["exact_matches"])
    cards[3].metric("Near ±1 M15", signals["near_matches"])
    st.caption(f"Exness-only {signals['exness_only']} · Bitstamp-only {signals['bitstamp_only']} · "
               f"Opposite within ±1 M15 {signals['opposite']}. Matches are one-to-one.")
    trade = summary["trade_matches"]
    st.subheader("Trade overlap from exact signal pairs")
    st.caption(f"{trade['exact_signal_pairs']} exact signal pairs · {trade['same_fill_status']} same fill status · "
               f"{trade['both_completed']} both completed")
    st.dataframe(pd.DataFrame([{"outcome": key, "pairs": value}
                               for key, value in trade["outcomes"].items()]),
                 hide_index=True, width="stretch")

    st.header("Exness Native Setup B")
    st.info("BAR SPREAD COST = LOWER-BOUND RESEARCH, NOT TICK-EXACT EXECUTION")
    st.caption("The zero-cost views isolate broker price-feed effects. Cost views reprice completed native Bid-OHLC trades without replaying tick-level entries or exits.")
    comparison = results.loc[results.scope == "exact_common_timestamps"]
    st.subheader("Same-period zero-cost comparison")
    st.dataframe(comparison[["feed", "signals", "pending_orders", "filled_orders", "trades",
                             "long_trades", "short_trades", "wins", "losses",
                             "win_rate_percent", "profit_factor", "average_r", "net_pnl"]].round(4),
                 hide_index=True, width="stretch")
    native = results.loc[(results.feed == "exness_native") & (results.scope == "full_native")]
    st.subheader("Full Exness native-price results")
    st.dataframe(native[["cost_view", "signals", "filled_orders", "trades", "win_rate_percent",
                         "profit_factor", "average_r", "spread_cost", "net_pnl"]].round(4),
                 hide_index=True, width="stretch")
    fixed = native.loc[native.cost_view.str.startswith("fixed_spread")]
    if not fixed.empty:
        fig = px.bar(fixed, x="cost_view", y="net_pnl",
                     title="Fixed-spread sensitivity on frozen native trades",
                     template="plotly_dark")
        st.plotly_chart(fig, width="stretch")
    st.subheader("Earlier vs later Exness periods")
    periods = results.loc[(results.feed == "exness_native") &
                          (results.scope.isin(["earlier_2023_2024", "later_2025_2026"])) &
                          (results.cost_view.isin(["zero_cost", "bar_minimum_spread_lower_bound"]))]
    st.dataframe(periods[["scope", "cost_view", "trades", "win_rate_percent",
                          "profit_factor", "average_r", "net_pnl"]].round(4),
                 hide_index=True, width="stretch")
    yearly_path = report_dir / "yearly_results.csv"
    if yearly_path.exists():
        st.subheader("Yearly Exness results")
        year = pd.read_csv(yearly_path)
        st.dataframe(year[["year", "partial_year", "cost_view", "trades", "win_rate_percent",
                           "profit_factor", "average_r", "net_pnl"]].round(4),
                     hide_index=True, width="stretch")
    st.caption("Signals are calculated from Exness Bid M15 bars. The existing generic OHLC execution convention remains in use. A tick-replayed Exness execution backtest has not been performed.")
