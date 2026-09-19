"""Read-only frozen Setup A Bitstamp long-history robustness view."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from research.setup_a_long_history import REPORT, ROOT


def render_setup_a_long_history() -> None:
    st.divider()
    st.subheader("Long-History Robustness")
    st.caption("FROZEN STRATEGY · NO OPTIMIZATION · Setup A standalone · Zero-cost primary baseline")
    st.info("BITSTAMP PRE-2023 HISTORY IS CROSS-FEED EVIDENCE, NOT EXNESS BROKER-NATIVE PERFORMANCE")
    if not (REPORT / "period_results.csv").exists():
        st.caption("Long-history reports are not available yet.")
        return
    periods = pd.read_csv(REPORT / "period_results.csv")
    yearly = pd.read_csv(REPORT / "yearly_results.csv")
    directions = pd.read_csv(REPORT / "direction_results.csv")
    mfe = pd.read_csv(REPORT / "mfe_mae.csv")
    pre = pd.read_csv(REPORT / "pre_exness_results.csv")
    regimes = pd.read_csv(REPORT / "regime_summary.csv")
    costs = pd.read_csv(REPORT / "cost_sensitivity.csv")
    segments = pd.read_csv(REPORT / "segment_results.csv")
    full = periods.loc[periods.period.eq("Full 2021–2026")].iloc[0]
    cards = st.columns(4)
    cards[0].metric("Completed trades", int(full.trades))
    cards[1].metric("Zero-cost PF", f"{full.profit_factor:.3f}")
    cards[2].metric("Average R", f"{full.average_r:.3f}")
    cards[3].metric("Worst segment DD", f"{full.worst_segment_dd_percent:.2f}%")
    st.caption(f"Net PnL ${full.net_pnl:,.2f}; {int(full.observed_months)} observed UTC months. "
               "Each source segment resets strategy and account state. Drawdown is never compounded across gaps.")
    st.markdown("#### Calendar years")
    st.dataframe(yearly[["year", "signals", "fills", "trades", "long_trades",
                         "short_trades", "win_rate_percent", "profit_factor", "average_r",
                         "median_r", "net_pnl", "worst_segment_dd_percent",
                         "max_losing_streak", "trades_per_observed_month"]].round(3),
                 hide_index=True, use_container_width=True)
    st.markdown("#### Independent periods")
    st.dataframe(periods[["period", "trades", "profit_factor", "average_r", "net_pnl",
                          "worst_segment_dd_percent", "signals_per_observed_month",
                          "fills_per_observed_month", "trades_per_observed_month"]].round(3),
                 hide_index=True, use_container_width=True)
    st.markdown("#### Long vs Short")
    st.dataframe(directions[["period", "direction", "trades", "profit_factor",
                             "average_r", "net_pnl"]].round(3),
                 hide_index=True, use_container_width=True)
    st.markdown("#### MFE / MAE after fill")
    st.caption("Conservative M15 OHLC excursions censor unknown entry- and exit-bar extremes.")
    st.dataframe(mfe.round(2), hide_index=True, use_container_width=True)
    st.markdown("#### Pre-Exness history · 2021 through 2023-11-08")
    st.dataframe(pre[["period", "direction", "trades", "win_rate_percent",
                      "profit_factor", "average_r", "net_pnl"]].round(3),
                 hide_index=True, use_container_width=True)
    st.markdown("#### Yearly signal-time regime medians")
    st.dataframe(regimes.round(3), hide_index=True, use_container_width=True)
    st.markdown("#### Existing exact-timestamp Exness overlap")
    native = pd.read_csv(ROOT / "reports/setup_a/native_results.csv")
    overlap = native.loc[native.scope.eq("exact_common_timestamps") &
                         native.cost_view.eq("zero_cost")]
    st.dataframe(overlap[["feed", "trades", "profit_factor", "average_r"]].round(3),
                 hide_index=True, use_container_width=True)
    match = json.loads((ROOT / "reports/setup_a/setup_a_validation_summary.json").read_text())["signal_overlap"]
    st.caption(f"Exact match {match['exact_percent_of_exness']:.2f}%; "
               f"exact + near match {100 * match['exact_plus_near_match_rate']:.2f}%. "
               "This comparison uses the saved Phase 4H exact-common-timestamp analysis.")
    st.markdown("#### HYPOTHETICAL COST SENSITIVITY")
    st.caption("Fixed $10/$20/$30 per BTC spread, $0 commission. These are not historical Exness costs for 2021–2023.")
    st.dataframe(costs.loc[costs.period.isin(["Full 2021–2026", "Pre-Exness"]),
                        ["period", "spread_usd_per_btc", "trades",
                         "profit_factor", "average_r", "net_pnl"]].round(3),
                 hide_index=True, use_container_width=True)
    with st.expander("Continuous segment coverage and excluded segments"):
        st.dataframe(segments, hide_index=True, use_container_width=True)
