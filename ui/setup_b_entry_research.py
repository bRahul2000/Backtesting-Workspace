"""Read-only Streamlit view of Phase 4E development-first entry research."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


REPORT_DIR = Path(__file__).resolve().parents[1] / "reports/research/setup_b_entry"


def _table(path: Path, columns: dict[str, str]) -> None:
    if not path.exists():
        st.caption(f"Report unavailable: {path.name}")
        return
    data = pd.read_csv(path)
    if data.empty:
        st.caption("No predefined combinations met the shortlist rule.")
        return
    data = data[[name for name in columns if name in data]].rename(columns=columns)
    st.dataframe(data.round(3), use_container_width=True, hide_index=True)


def render_entry_research(report_dir: Path = REPORT_DIR) -> None:
    st.divider()
    st.header("Entry Quality Research")
    st.info("RESEARCH ONLY — original V2.2 Setup B remains active in Backtest.")
    development_path = report_dir / "development_summary.json"
    if not development_path.exists():
        st.caption("Development research report has not been generated yet.")
        return
    summary = json.loads(development_path.read_text())
    control = summary["control"]
    st.caption("2021–2024 development · original structural stop, pending entry, fixed 3R target, audited current costs")

    st.subheader("Original control · development")
    cards = st.columns(4)
    cards[0].metric("Trades", f"{control['trades']:,}")
    cards[1].metric("PF", f"{control['profit_factor']:.3f}")
    cards[2].metric("Average R", f"{control['average_r']:.3f}")
    cards[3].metric("Worst segment DD", f"{control['worst_segment_dd_percent']:.2f}%")

    st.subheader("One-factor sensitivity")
    one = pd.read_csv(report_dir / "one_factor_sensitivity.csv")
    names = [x for x in one.parameter.unique() if x != "Control"]
    factor = st.selectbox("Entry factor", names, key="entry_research_factor")
    selected = one.loc[one.parameter == factor]
    st.caption(summary["factor_trends"].get(factor, ""))
    shown = selected[["value", "trades", "trade_retention_percent", "long_trades",
                      "short_trades", "win_rate_percent", "profit_factor", "average_r",
                      "net_pnl", "worst_segment_dd_percent", "max_losing_streak",
                      "positive_expectancy_years", "negative_expectancy_years",
                      "low_sample_for_development", "zero_cost_pf", "zero_cost_average_r"]].copy()
    shown.columns = ["Value", "Trades", "Retention %", "Long", "Short", "WR %",
                     "PF", "Avg R", "Net $", "Worst DD %", "Max losing streak",
                     "Positive years", "Negative years", "Low sample", "Zero-cost PF",
                     "Zero-cost Avg R"]
    st.dataframe(shown.round(3), use_container_width=True, hide_index=True)
    st.caption("LOW SAMPLE FOR DEVELOPMENT: fewer than 250 completed trades. No result is hidden.")

    a, b = st.columns(2)
    retention = px.line(selected, x="value", y="trade_retention_percent", markers=True,
                        title="Trade retention %", template="plotly_dark")
    a.plotly_chart(retention, use_container_width=True)
    performance = selected.melt(id_vars="value", value_vars=["profit_factor", "average_r"],
                                var_name="Measure", value_name="Value")
    figure = px.line(performance, x="value", y="Value", color="Measure", markers=True,
                     title="PF and average-R sensitivity", template="plotly_dark")
    b.plotly_chart(figure, use_container_width=True)

    with st.expander("Year stability", expanded=False):
        _table(report_dir / "year_stability.csv", {
            "variant": "Variant", "year": "Year", "trades": "Trades",
            "profit_factor": "PF", "average_r": "Avg R", "net_pnl": "Net $",
            "pnl_contribution_percent_of_absolute_years": "PnL contribution %",
        })
    with st.expander("Long vs short impact", expanded=False):
        _table(report_dir / "direction_analysis.csv", {
            "variant": "Variant", "direction": "Side", "trades": "Trades",
            "profit_factor": "PF", "average_r": "Avg R", "net_pnl": "Net $",
        })

    st.subheader("Development combinations")
    combinations = summary["combinations"]
    if combinations:
        _table(report_dir / "combination_development.csv", {
            "variant": "Combination", "changes": "Changes", "trades": "Trades",
            "trade_retention_percent": "Retention %", "win_rate_percent": "WR %",
            "profit_factor": "PF", "average_r": "Avg R", "net_pnl": "Net $",
            "worst_segment_dd_percent": "Worst DD %", "zero_cost_pf": "Zero-cost PF",
            "low_sample_for_development": "Low sample",
        })
    else:
        st.caption("No combination was predefined because fewer than two factors met the development shortlist rule.")
    st.caption("Frozen candidates: " +
               (", ".join(c["id"] for c in summary["frozen_candidates"])
                if summary["frozen_candidates"] else "none"))

    st.subheader("Forward validation · 2025–2026")
    st.caption("Candidates were frozen before this set was opened. This is not a pristine holdout.")
    _table(report_dir / "forward_validation.csv", {
        "variant": "Variant", "direction": "Side", "trades": "Trades",
        "win_rate_percent": "WR %", "profit_factor": "PF", "average_r": "Avg R",
        "net_pnl": "Net $", "worst_segment_dd_percent": "Worst DD %",
    })

    st.subheader("Cost sensitivity")
    st.caption("Same forward-validation trades and exits, repriced at each fee assumption; no cost scenario was used to select candidates.")
    _table(report_dir / "cost_crosscheck.csv", {
        "variant": "Variant", "cost_scenario": "Cost", "trades": "Trades",
        "profit_factor": "PF", "average_r": "Avg R", "net_pnl": "Net $",
    })
    with st.expander("Download entry research", expanded=False):
        for name in ("one_factor_sensitivity.csv", "year_stability.csv",
                     "direction_analysis.csv", "combination_development.csv",
                     "frozen_candidates.json", "forward_validation.csv",
                     "cost_crosscheck.csv", "entry_research_summary.md"):
            path = report_dir / name
            if path.exists():
                st.download_button(name, path.read_bytes(), file_name=name,
                                   mime="text/csv" if name.endswith(".csv") else "text/plain",
                                   key=f"entry_research_{name}")
