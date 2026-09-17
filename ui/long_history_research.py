"""Read-only Streamlit view of the frozen segment-aware research artifacts."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st


REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "long_history" / "segment_aware"


def _cash(value: float) -> str:
    return f"${value:,.2f}" if value >= 0 else f"−${abs(value):,.2f}"


def render_long_history_research(report_dir: Path = REPORT_DIR) -> None:
    st.header("Long-History Research")
    summary_path = report_dir / "summary.json"
    if not summary_path.exists():
        st.caption("Run the segment-aware baseline to create research reports.")
        return
    summary = json.loads(summary_path.read_text())
    primary = summary["primary_continuous"]
    pooled = summary["segment_aware_pooled"]
    st.subheader("Historical Data Summary")
    st.caption(
        f"BTC/USD 15m · {summary['historical_start']} to {summary['historical_end']} UTC"
    )
    coverage = st.columns(4)
    coverage[0].metric("Total Candles", f"{summary['total_candles']:,}")
    coverage[1].metric("Usable Segments", summary["usable_segments"])
    coverage[2].metric("Excluded Segments", summary["excluded_segments"])
    coverage[3].metric("Missing Candles", summary["missing_candles"])

    gaps = summary["gap_summary"]
    st.subheader("Gap Summary")
    gap_cards = st.columns(4)
    gap_cards[0].metric("Internal Gaps", gaps["number_of_gaps"])
    gap_cards[1].metric("Missing Candles", gaps["total_missing_candles"])
    gap_cards[2].metric("Median Gap", f"{gaps['median_gap_size']:g} candles")
    gap_cards[3].metric("Largest Gap", f"{gaps['largest_gap_size']} candles")
    st.caption(
        f"1 candle: {gaps['one_candle']} · 2–4: {gaps['two_to_four']} · "
        f"5–16: {gaps['five_to_sixteen']} · 17+: {gaps['seventeen_plus']}"
    )

    left, right = st.columns(2)
    with left:
        st.subheader("PRIMARY CONTINUOUS BASELINE")
        st.caption(f"{primary['segment_id']} · {primary['start']} to {primary['end']}")
        st.metric("Completed Trades", primary["completed_trades"])
        st.write(
            f"Win rate {primary['win_rate_percent']:.2f}% · "
            f"PF {primary['profit_factor']:.4f} · "
            f"Average R {primary['average_r']:.4f} · "
            f"Net PnL {_cash(primary['net_pnl'])} · "
            f"Max segment DD {primary['max_drawdown_percent']:.2f}%"
        )
    with right:
        st.subheader("SEGMENT-AWARE POOLED BASELINE")
        st.caption(f"{pooled['segments_included']} independent usable segments")
        st.metric("Completed Trades", pooled["trades"])
        st.write(
            f"Win rate {pooled['win_rate_percent']:.2f}% · "
            f"PF {pooled['profit_factor']:.4f} · "
            f"Average R {pooled['average_r']:.4f} · "
            f"Summed trade PnL {_cash(pooled['net_pnl'])} · "
            f"Worst segment DD {pooled['worst_segment_drawdown_percent']:.2f}%"
        )
    st.info(
        "The pooled baseline combines independent continuous segments and is not "
        "one continuous compounded equity curve. Drawdown is reported by segment only."
    )

    segment_path = report_dir / "all_segments.csv"
    if segment_path.exists():
        st.subheader("Segment Table")
        rows = pd.read_csv(segment_path)
        columns = [
            "segment_id", "start", "end", "candles", "calendar_days",
            "gap_before_missing_candles", "usable", "exclusion_reason",
            "signals", "completed_trades", "net_pnl", "max_drawdown_percent",
        ]
        st.dataframe(rows[columns], width="stretch", hide_index=True)

    st.subheader("Year Results")
    yearly_path = report_dir / "yearly_results.csv"
    if yearly_path.exists():
        yearly = pd.read_csv(yearly_path)
        st.dataframe(yearly[[
            "year", "usable_candles", "segments_represented", "trades",
            "long_trades", "short_trades", "win_rate_percent",
            "profit_factor", "average_r", "expectancy_r", "net_pnl",
            "worst_segment_drawdown_percent",
        ]].round({
            "win_rate_percent": 2, "profit_factor": 3,
            "average_r": 3, "expectancy_r": 3, "net_pnl": 2,
            "worst_segment_drawdown_percent": 2,
        }), width="stretch", hide_index=True)

    st.subheader("Monthly Results")
    monthly_path = report_dir / "monthly_results.csv"
    if monthly_path.exists():
        monthly = pd.read_csv(monthly_path)
        st.caption(
            f"{summary['profitable_months']} profitable · "
            f"{summary['losing_months']} losing · "
            f"{summary['no_trade_months']} without a completed trade. "
            "Incomplete source coverage is marked per UTC month."
        )
        st.dataframe(monthly[[
            "month", "trades", "wins", "losses", "win_rate_percent",
            "profit_factor", "average_r", "net_pnl",
            "incomplete_source_coverage",
        ]].round({
            "win_rate_percent": 2, "profit_factor": 3,
            "average_r": 3, "net_pnl": 2,
        }), width="stretch", hide_index=True, height=280)

    st.subheader("Long vs Short")
    side_rows = []
    for name, key in (("Long", "long_pooled"), ("Short", "short_pooled")):
        side = summary[key]
        side_rows.append({
            "Direction": name, "Trades": side["trades"],
            "Wins": side["wins"], "Losses": side["losses"],
            "Win Rate %": side["win_rate_percent"],
            "Profit Factor": side["profit_factor"],
            "Net PnL $": side["net_pnl"],
            "Average R": side["average_r"],
            "Expectancy R": side["expectancy_r"],
            "Worst Segment DD %": side["worst_segment_drawdown_percent"],
            "Profitable Segments": side["profitable_segments"],
            "Losing Segments": side["losing_segments"],
        })
    st.dataframe(pd.DataFrame(side_rows).round({
        "Win Rate %": 2, "Profit Factor": 3, "Net PnL $": 2,
        "Average R": 3, "Expectancy R": 3, "Worst Segment DD %": 2,
    }), width="stretch", hide_index=True)

    st.subheader("Download Research CSV Files")
    files = (
        "segment_results.csv", "pooled_trades.csv",
        "yearly_results.csv", "monthly_results.csv",
    )
    buttons = [*st.columns(2), *st.columns(2)]
    for column, filename in zip(buttons, files):
        path = report_dir / filename
        column.download_button(
            filename, data=path.read_bytes() if path.exists() else b"",
            file_name=filename, mime="text/csv", disabled=not path.exists(),
        )
