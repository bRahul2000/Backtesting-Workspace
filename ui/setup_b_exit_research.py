"""Read-only presentation of frozen-entry Phase 4D research files."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st


REPORT_DIR = Path(__file__).resolve().parents[1] / "reports/research/setup_b_exit"


def _table(path: Path, columns: dict[str, str]) -> None:
    if not path.exists():
        st.caption(f"Report unavailable: {path.name}")
        return
    frame = pd.read_csv(path)
    if frame.empty:
        st.caption("No development-robust candidates; forward validation was not run.")
        return
    shown = frame[list(columns)].rename(columns=columns)
    st.dataframe(shown.round(3), hide_index=True, width="stretch")


def render_exit_research(report_dir: Path = REPORT_DIR) -> None:
    st.divider()
    st.header("Exit Research")
    st.info("RESEARCH ONLY — NOT ACTIVE STRATEGY. Frozen entries; no active Backtest settings changed.")
    summary_path = report_dir / "summary.json"
    if not summary_path.exists():
        st.caption("Run the frozen-entry exit research export to populate this view.")
        return
    summary = json.loads(summary_path.read_text())
    st.caption("Development: 2021–2024 · Forward-validation: 2025–2026 (previously viewed summary data).")
    st.caption(summary["counterfactual_note"])

    development = pd.read_csv(report_dir / "development_exit_models.csv")
    original = development.loc[development.model == "E0"].iloc[0]
    st.subheader("Original 3R baseline · development")
    cards = st.columns(4)
    cards[0].metric("Trades", f"{int(original.trades):,}")
    cards[1].metric("PF", f"{original.profit_factor:.3f}")
    cards[2].metric("Average R", f"{original.average_r:.3f}")
    cards[3].metric("Worst segment DD", f"{original.max_dd_percent:.2f}%")

    st.subheader("Development exit comparison")
    _table(report_dir / "development_exit_models.csv", {
        "model": "Model", "trades": "Trades", "wins": "Wins", "losses": "Losses",
        "breakeven": "BE", "win_rate_percent": "WR %", "gross_pnl": "Gross $",
        "costs": "Costs $", "net_pnl": "Net $", "profit_factor": "PF",
        "average_r": "Avg R", "median_r": "Median R",
        "max_dd_percent": "Worst segment DD %",
        "full_stop_percent": "Full stop %", "breakeven_exit_percent": "BE exit %",
        "partial_exit_percent": "Partial %", "development_robust": "Robust label",
    })
    st.caption("E0 3R · E1 2R · E2 1.5R · E3 3R+BE@1R · E4 3R+BE@1.5R · "
               "E5 half@1R/rest 3R · E6 half@1R+BE/rest 3R · E7 2R+BE@1R")
    fig = px.bar(development, x="model", y="average_r", color="model",
                 title="Development average R", template="plotly_dark")
    fig.update_layout(showlegend=False, height=320)
    st.plotly_chart(fig, width="stretch")

    with st.expander("Year-by-year stability", expanded=False):
        _table(report_dir / "development_yearly.csv", {
            "model": "Model", "year": "Year", "trades": "Trades",
            "profit_factor": "PF", "average_r": "Avg R", "net_pnl": "Net $",
            "max_dd_percent": "Worst segment DD %",
        })
    with st.expander("Long / short comparison", expanded=False):
        _table(report_dir / "development_long_short.csv", {
            "model": "Model", "direction": "Side", "trades": "Trades",
            "profit_factor": "PF", "average_r": "Avg R", "net_pnl": "Net $",
        })

    st.subheader("Forward validation")
    robust = summary["development_robust"]
    st.caption("Development-robust candidates: " + (", ".join(robust) if robust else "none"))
    _table(report_dir / "forward_validation.csv", {
        "model": "Model", "trades": "Trades", "profit_factor": "PF",
        "average_r": "Avg R", "net_pnl": "Net $",
        "max_dd_percent": "Worst segment DD %",
    })

    st.subheader("Cost sensitivity · unchanged E0 fills and exits")
    _table(report_dir / "cost_sensitivity.csv", {
        "scenario": "Scenario", "commission_percent_per_side": "Fee %/side",
        "trades": "Trades", "gross_pnl": "Gross $", "costs": "Costs $",
        "net_pnl": "Net $", "profit_factor": "PF", "average_r": "Avg R",
        "required_breakeven_wr_percent": "Required WR %",
    })
    with st.expander("Cost × exit cross-check", expanded=False):
        _table(report_dir / "cost_exit_cross_check.csv", {
            "model": "Model", "scenario": "Scenario", "trades": "Trades",
            "profit_factor": "PF", "average_r": "Avg R", "net_pnl": "Net $",
        })
    st.caption("MFE reach: path-known lower / OHLC possible upper: " +
               " · ".join(f"+{key} {value:.1f}% / "
                          f"{summary['mfe_possible_upper_bound_percent'][key]:.1f}%" for key, value in
                          summary["mfe_conservative_reach_percent"].items()))
    with st.expander("Research downloads", expanded=False):
        for name in ("cost_audit.md", "cost_sensitivity.csv", "development_exit_models.csv",
                     "development_yearly.csv", "development_long_short.csv",
                     "forward_validation.csv", "cost_exit_cross_check.csv",
                     "exit_research_summary.md"):
            path = report_dir / name
            if path.exists():
                st.download_button(name, path.read_bytes(), file_name=name,
                                   mime="text/csv" if name.endswith(".csv") else "text/markdown",
                                   key=f"exit_research_{name}")
