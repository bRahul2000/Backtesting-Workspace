"""Presentation of frozen Setup A low-volatility research artifacts."""
from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import streamlit as st

from research.setup_a_volatility_research import REPORT


def render_setup_a_regime_research() -> None:
    st.divider()
    st.subheader("Regime Research")
    st.caption("REGIME RESEARCH · NOT ACTIVE STRATEGY · Frozen Setup A entries and 3R exits")
    source = REPORT / "development_one_factor.csv"
    if not source.exists():
        st.caption("Volatility research reports are not available yet.")
        return
    one = pd.read_csv(source)
    validation = pd.read_csv(REPORT / "validation_results.csv")
    costs = pd.read_csv(REPORT / "cost_crosscheck.csv")
    participation = pd.read_csv(REPORT / "allowed_blocked_analysis.csv")
    monthly = pd.read_csv(REPORT / "monthly_participation.csv")
    direction = pd.read_csv(REPORT / "direction_analysis.csv")
    frozen = json.loads((REPORT / "frozen_candidates.json").read_text())
    control = one.loc[one.feature.eq("control")].iloc[0]
    cols = st.columns(4)
    cols[0].metric("Development trades", int(control.trades))
    cols[1].metric("Development PF", f"{control.profit_factor:.3f}")
    cols[2].metric("Development average R", f"{control.average_r:.3f}")
    cols[3].metric("Worst segment DD", f"{control.worst_segment_dd_percent:.2f}%")
    st.caption("Development: 2023–2024. Validation set for Phase 4K: 2025–2026; prior summaries have already been observed.")
    show = ["percentile", "threshold", "trades", "retention_percent",
            "profit_factor", "average_r", "average_mfe_r",
            "never_reached_0.5r_percent", "worst_segment_dd_percent", "low_sample"]
    for feature, title in (("atr_percent", "ATR% sensitivity"),
                           ("recent_volatility_24h_percent", "24h volatility sensitivity")):
        st.markdown(f"#### {title}")
        subset = one.loc[one.feature.eq(feature)]
        st.dataframe(subset[show].round(4), hide_index=True, use_container_width=True)
        charts = st.columns(2)
        charts[0].plotly_chart(px.line(subset, x="percentile", y="retention_percent",
                                      markers=True, title="Trade retention", template="plotly_dark"),
                               use_container_width=True)
        figures = subset.melt(id_vars="percentile", value_vars=["profit_factor", "average_r"],
                              var_name="metric", value_name="value")
        charts[1].plotly_chart(px.line(figures, x="percentile", y="value", color="metric",
                                      markers=True, title="PF and average R", template="plotly_dark"),
                               use_container_width=True)
    with st.expander("Development direction and monthly participation"):
        st.dataframe(direction.round(4), hide_index=True, use_container_width=True)
        st.dataframe(monthly, hide_index=True, use_container_width=True)
    st.markdown("#### Development candidate freeze")
    st.json({"freeze_hash_sha256": frozen["freeze_hash_sha256"],
             "candidates": frozen["candidates"]})
    st.caption("One ATR% candidate was frozen before validation. No 24h or combined candidate qualified.")
    st.markdown("#### 2025 and 2026 validation")
    st.dataframe(validation.loc[validation.period.isin(["2025", "2026", "2025–2026"])].round(4),
                 hide_index=True, use_container_width=True)
    st.caption("The frozen candidate did not materially improve 2025 per-trade quality and reduced 2026 average R.")
    st.markdown("#### Cost cross-check")
    st.dataframe(costs.loc[costs.spread_usd_per_btc.isin([0., 10., 20., 30.])].round(4),
                 hide_index=True, use_container_width=True)
    st.markdown("#### Allowed vs blocked original opportunities")
    st.dataframe(participation.round(4), hide_index=True, use_container_width=True)
    st.caption("Blocked-trade PnL is a counterfactual classification of original control trades. Gated-run PnL comes from an independent backtest; later opportunities can differ.")
