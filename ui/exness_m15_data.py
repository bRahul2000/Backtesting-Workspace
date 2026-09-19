"""Read-only market-data view for the Exness Bid M15 export."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from services.exness_m15 import REPORT


def render_exness_m15_data(report_dir: Path = REPORT) -> None:
    st.divider()
    st.subheader("Exness M15 Dataset")
    st.caption("BROKER-NATIVE PRICE DATA · BTCUSDm Bid candles · Exness server UTC+0")
    audit_path = report_dir / "data_audit.json"
    spread_path = report_dir / "spread_history.csv"
    if not audit_path.exists() or not spread_path.exists():
        st.caption("No audited Exness M15 history is available.")
        return
    audit = json.loads(audit_path.read_text())
    spread = pd.read_csv(spread_path)
    overall = spread.loc[spread.group_type == "overall"].iloc[0]
    cards = st.columns(4)
    cards[0].metric("Candles", f"{audit['raw_rows']:,}")
    cards[1].metric("Missing M15", audit["missing_intervals"])
    cards[2].metric("Gaps", audit["gap_count"])
    cards[3].metric("Median bar-min spread", f"${overall['median']:.2f}")
    st.caption(f"{audit['first_timestamp_utc']} to {audit['last_timestamp_utc']} · "
               f"Largest gap {audit['largest_gap']} candles · "
               f"P95 bar-min spread ${overall['p95']:.2f} · Maximum ${overall['maximum']:.2f}")
    st.info("MT5 M15 SPREAD is a historical bar-minimum descriptor. It is not the spread guaranteed at an execution tick.")
    year = spread.loc[spread.group_type == "year"].copy()
    month = spread.loc[spread.group_type == "month"].copy()
    if not year.empty:
        st.markdown("**Annual spread history**")
        st.dataframe(year[["group", "candles", "minimum", "median", "mean", "p95", "maximum"]].round(2),
                 hide_index=True, use_container_width=True)
    if not month.empty:
        fig = px.line(month, x="group", y=["median", "p95"], markers=True,
                      title="Monthly minimum-spread descriptors", template="plotly_dark")
        st.plotly_chart(fig, use_container_width=True)
    gap_path = report_dir.parent / "m15_data_gaps.csv"
    if gap_path.exists():
        with st.expander("M15 missing intervals", expanded=False):
            st.dataframe(pd.read_csv(gap_path), hide_index=True, use_container_width=True)
