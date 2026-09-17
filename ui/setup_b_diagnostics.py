"""Read-only Streamlit view of frozen Setup B failure-diagnostic reports."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "diagnostics" / "setup_b"
FILES = (
    "trade_diagnostics.csv", "winner_loser_profile.csv",
    "bucket_analysis.csv", "time_analysis.csv", "fill_analysis.csv",
    "mfe_mae_analysis.csv", "cost_analysis.csv",
)


def _cash(value: float) -> str:
    return f"${value:,.2f}" if value >= 0 else f"−${abs(value):,.2f}"


def _pf(value) -> str:
    return "—" if pd.isna(value) else "∞" if value == float("inf") else f"{value:.3f}"


def _bucket_table(buckets: pd.DataFrame, descriptor: str, heading: str) -> None:
    st.subheader(heading)
    rows = buckets.loc[(buckets.descriptor == descriptor) &
                       (buckets.direction == "All")]
    shown = rows[["bucket", "trades", "wins", "losses",
                  "win_rate_percent", "profit_factor", "average_r",
                  "expectancy_r", "net_pnl", "small_sample"]].copy()
    shown.columns = ["Bucket", "Trades", "Wins", "Losses", "WR %", "PF",
                     "Average R", "Expectancy R", "Net PnL $", "Small sample"]
    st.dataframe(shown.round({"WR %": 2, "PF": 3, "Average R": 3,
                              "Expectancy R": 3, "Net PnL $": 2}),
                 width="stretch", hide_index=True)


def render_setup_b_diagnostics(report_dir: Path = REPORT_DIR) -> None:
    st.header("Diagnostics")
    summary_path = report_dir / "summary.json"
    if not summary_path.exists():
        st.caption("Run the frozen Setup B diagnostic export to populate this view.")
        return
    summary = json.loads(summary_path.read_text())
    baseline = summary["baseline"]
    costs = summary["costs_and_breakeven"]["All"]
    st.caption("Frozen BTC V2.2 Setup B · Phase 4B segment-aware completed trades")

    st.subheader("BASELINE")
    first = st.columns(3)
    first[0].metric("Trades", f"{baseline['trades']:,}")
    first[1].metric("Win Rate", f"{baseline['win_rate_percent']:.2f}%")
    first[2].metric("Profit Factor", _pf(baseline["profit_factor"]))
    second = st.columns(2)
    second[0].metric("Average R", f"{baseline['average_r']:.3f}")
    second[1].metric("Net PnL", _cash(baseline["net_pnl"]))

    st.subheader("BREAKEVEN ANALYSIS")
    breakeven_cards = st.columns(3)
    breakeven_cards[0].metric("Actual WR", f"{costs['win_rate_percent']:.2f}%")
    breakeven_cards[1].metric("Required WR", f"{costs['required_breakeven_win_rate_percent']:.2f}%")
    breakeven_cards[2].metric("WR Gap", f"{costs['win_rate_gap_pp']:+.2f} pp")
    st.caption(
        f"Based on historical average winner {costs['average_winner_r']:.3f}R "
        f"and average loser {costs['average_loser_r']:.3f}R."
    )

    st.subheader("COST ATTRIBUTION")
    cost_cards = st.columns(4)
    cost_cards[0].metric("Pre-cost PnL", _cash(costs["gross_price_movement_pnl"]))
    cost_cards[1].metric("Commission", _cash(costs["commission_cost"]))
    cost_cards[2].metric("Slippage", _cash(costs["slippage_cost"]))
    cost_cards[3].metric("Net PnL", _cash(costs["net_pnl"]))
    st.caption(
        f"Total costs {_cash(costs['total_transaction_cost'])} · "
        f"{_cash(costs['cost_per_trade'])} per trade · "
        f"{costs['cost_r_per_trade']:.3f}R per trade · "
        f"{costs['cost_percent_of_absolute_gross_pnl']:.2f}% of absolute pre-cost trading PnL."
    )

    st.subheader("MFE / MAE SUMMARY")
    st.caption(summary["mfe_method"])
    all_excursions = summary["excursion_summary"]["All"]
    all_cards = st.columns(4)
    all_cards[0].metric("Average MFE", f"{all_excursions['average_mfe_r']:.3f}R")
    all_cards[1].metric("Median MFE", f"{all_excursions['median_mfe_r']:.3f}R")
    all_cards[2].metric("Average MAE", f"{all_excursions['average_mae_r']:.3f}R")
    all_cards[3].metric("Median MAE", f"{all_excursions['median_mae_r']:.3f}R")
    stopped = summary["stopped_trades"]
    st.caption(
        f"{stopped['trades']} stopped trades · median MFE before stop "
        f"{stopped['median_mfe_r']:.3f}R · "
        f"{stopped['never_reached_0.5r_percent']:.2f}% never reached +0.5R."
    )
    mfe = pd.read_csv(report_dir / "mfe_mae_analysis.csv")
    st.subheader("EXIT DIAGNOSIS")
    shown = mfe.loc[(mfe.population.isin(["All", "Long", "Short", "Losing", "Stopped"])) &
                    (mfe.threshold_r.isin([.5, 1., 1.5, 2., 2.5, 3.]))]
    pivot = shown.pivot(index="population", columns="threshold_r",
                        values="reached_percent").reindex(
                            ["All", "Long", "Short", "Losing", "Stopped"])
    pivot.columns = [f"+{value:g}R reached %" for value in pivot.columns]
    st.dataframe(pivot.round(2), width="stretch")
    st.caption(
        f"Stopped trades: {stopped['never_reached_0.25r_percent']:.2f}% never "
        f"reached +0.25R; average MFE {stopped['average_mfe_r']:.3f}R; "
        f"median stop distance {stopped['median_stop_distance_atr']:.3f} ATR."
    )

    buckets = pd.read_csv(report_dir / "bucket_analysis.csv")
    st.subheader("SIGNAL-TIME BUCKETS")
    st.caption("Descriptive groups only. Buckets with fewer than 20 trades are flagged; no bucket changes the strategy.")
    _bucket_table(buckets, "ADX", "ADX Bucket Performance")
    _bucket_table(buckets, "EMA20 extension ATR", "EMA Extension Bucket Performance")
    _bucket_table(buckets, "Stop distance ATR", "Stop-Distance Bucket Performance")
    _bucket_table(buckets, "ATR %", "Volatility Bucket Performance")
    with st.expander("Other signal-time buckets"):
        _bucket_table(buckets, "Breakout range ATR", "Breakout Range ATR")
        _bucket_table(buckets, "Body %", "Breakout Body %")
        _bucket_table(buckets, "H1 EMA200 slope %", "H1 EMA200 Slope %")
        _bucket_table(buckets, "Structure breakout distance ATR", "Structure Breakout Distance ATR")

    times = pd.read_csv(report_dir / "time_analysis.csv")
    st.subheader("UTC-HOUR PERFORMANCE")
    hours = times.loc[(times.period_type == "UTC signal hour") &
                      (times.direction == "All")].copy()
    hours["period"] = hours.period.astype(int)
    fig = go.Figure(go.Bar(
        x=hours.period, y=hours.average_r,
        marker_color=["#2ca58d" if value >= 0 else "#d76666"
                      for value in hours.average_r],
        customdata=hours.trades,
        hovertemplate="%{x}:00 UTC<br>Average R %{y:.3f}<br>Trades %{customdata}<extra></extra>",
    ))
    fig.update_layout(template="plotly_dark", height=300,
                      xaxis_title="Signal hour UTC", yaxis_title="Average R",
                      xaxis=dict(dtick=2), margin=dict(l=20, r=20, t=20, b=30))
    st.plotly_chart(fig, width="stretch")
    st.dataframe(hours[["period", "trades", "win_rate_percent", "profit_factor",
                        "average_r", "expectancy_r", "small_sample"]].round(3),
                 width="stretch", hide_index=True, height=250)
    st.subheader("DAY-OF-WEEK PERFORMANCE")
    days = times.loc[(times.period_type == "UTC weekday") &
                     (times.direction == "All")]
    st.dataframe(days[["period", "trades", "win_rate_percent", "profit_factor",
                       "average_r", "expectancy_r", "small_sample"]].round(3),
                 width="stretch", hide_index=True)
    with st.expander("Calendar year, month, and direction detail"):
        st.dataframe(times.loc[times.period_type.isin(
            ["Calendar year", "Calendar month", "Analysis set"])],
            width="stretch", hide_index=True, height=280)

    fills = pd.read_csv(report_dir / "fill_analysis.csv")
    st.subheader("FILL QUALITY")
    st.markdown("**B+1 vs B+2**")
    rows = fills.loc[(fills.comparison == "Pending fill bar") &
                     (fills.direction == "All")]
    st.dataframe(rows[["fill_type", "trades", "win_rate_percent",
                       "profit_factor", "average_r", "expectancy_r",
                       "net_pnl", "small_sample"]].round(3),
                 width="stretch", hide_index=True)
    st.markdown("**Normal vs gap-through-trigger**")
    rows = fills.loc[(fills.comparison == "Trigger crossing") &
                     (fills.direction == "All")]
    st.dataframe(rows[["fill_type", "trades", "win_rate_percent",
                       "profit_factor", "average_r", "expectancy_r",
                       "net_pnl", "small_sample"]].round(3),
                 width="stretch", hide_index=True)

    st.subheader("LONG VS SHORT")
    sides = pd.read_csv(report_dir / "cost_analysis.csv")
    st.dataframe(sides.loc[sides.population.isin(["Long", "Short"]), [
        "population", "trades", "win_rate_percent", "profit_factor",
        "average_r", "expectancy_r", "net_pnl",
        "required_breakeven_win_rate_percent", "win_rate_gap_pp",
    ]].round(3), width="stretch", hide_index=True)
    st.caption(
        "Development: 2021–2024. Forward-validation for future changes: "
        "2025–2026. These later years have already been observed and are not a pristine holdout."
    )

    with st.expander("Download diagnostic CSV files"):
        for filename in FILES:
            path = report_dir / filename
            st.download_button(filename, path.read_bytes(), file_name=filename,
                               mime="text/csv")
