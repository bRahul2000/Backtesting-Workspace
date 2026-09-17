"""Broker calibration display and explicit raw tick import controls."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from brokers.exness_standard_btcusdm import PROFILE
from services.exness_ticks import (
    RAW_DIR, REPORT_DIR, TickColumns, TickImportError, import_tick_sources,
    inspect_tick_source,
)
from services.exness_mt5_samples import process_mt5_samples


def _money(value) -> str:
    return "—" if value is None else f"${value:,.2f}"


def _render_mt5_samples(summary: dict, report_dir: Path) -> None:
    st.info("MT5 SERVER TIMEZONE — UNVERIFIED. All sample dates and hours are broker-server wall time, not UTC.")
    cards = st.columns(4)
    cards[0].metric("Samples", f"{summary['sample_count']:,}")
    cards[1].metric("Reconstructed ticks", f"{summary['total_ticks']:,}")
    cards[2].metric("Median spread", _money(summary['combined_spread']['median']))
    cards[3].metric("P95 spread", _money(summary['combined_spread']['p95']))
    cards = st.columns(4)
    cards[0].metric("Maximum spread", _money(summary['combined_spread']['maximum']))
    cards[1].metric("Median spread bps", f"{summary['median_spread_bps']:.3f}")
    cards[2].metric("15m intervals", f"{summary['total_15m_intervals']:,}")
    cards[3].metric("Observed bar-hours", f"{summary['total_observed_hours']:g}")
    st.caption(f"Commission $0 · Spread from reconstructed historical Bid/Ask quotes · "
               f"Bid-only {summary['bid_only_updates']:,} · Ask-only {summary['ask_only_updates']:,} · "
               f"Both-side {summary['both_side_updates']:,} · "
               f"Missing 15m intervals {summary['total_missing_15m_intervals']:,}")
    st.caption("Quote state resets at each file and missing 15-minute interval. Raw Bid/Ask fields remain separate from reconstructed values in the processed tick files.")
    coverage_path = report_dir / "sample_coverage.csv"
    if coverage_path.exists():
        coverage = pd.read_csv(coverage_path)
        st.markdown("**Sample coverage**")
        view = coverage[["sample_date", "day_type", "filename", "tick_count", "bid_15m_bars",
                         "missing_15m_intervals", "spread_median", "spread_p95",
                         "spread_maximum", "median_spread_bps"]]
        st.dataframe(view, hide_index=True, width="stretch")
        groups = coverage.groupby("day_type", as_index=False).agg(
            samples=("sample_id", "count"), ticks=("tick_count", "sum"),
            intervals=("bid_15m_bars", "sum"))
        st.markdown("**Weekend vs weekday observations (server calendar)**")
        st.dataframe(groups, hide_index=True, width="stretch")
    hourly_path = report_dir / "spread_by_hour.csv"
    if hourly_path.exists():
        hourly = pd.read_csv(hourly_path)
        if not hourly.empty:
            fig = px.line(hourly, x="server_hour", y="median_spread_price", markers=True,
                          title="Median spread by MT5 server hour", template="plotly_dark")
            fig.update_xaxes(dtick=1)
            st.plotly_chart(fig, width="stretch")
    distribution_path = report_dir / "spread_distribution.csv"
    if distribution_path.exists():
        distribution = pd.read_csv(distribution_path)
        price = distribution.loc[distribution.unit == "USD/BTC"]
        if not price.empty:
            fig = px.bar(price, x="metric", y="value",
                         title="Combined historical spread distribution", template="plotly_dark")
            fig.update_xaxes(tickangle=-30)
            st.plotly_chart(fig, width="stretch")
    gaps_path = report_dir / "sample_data_gaps.csv"
    if gaps_path.exists():
        with st.expander("Sample gaps and import details", expanded=False):
            gaps = pd.read_csv(gaps_path)
            st.caption(f"{len(gaps):,} internal gaps across {summary['sample_count']} separate samples.")
            if not gaps.empty:
                st.dataframe(gaps, hide_index=True, width="stretch")
            st.dataframe(pd.DataFrame(summary["samples"]), hide_index=True, width="stretch")


def render_exness_broker_data(report_dir: Path = REPORT_DIR,
                              raw_dir: Path = RAW_DIR) -> None:
    st.divider()
    st.subheader("Exness Broker Data")
    st.caption("BROKER CALIBRATION — STRATEGY UNCHANGED. Exness Standard BTCUSDm is separate from Bitstamp research.")
    identity = st.columns(4)
    identity[0].metric("Broker", PROFILE.broker)
    identity[1].metric("Account", PROFILE.account_type)
    identity[2].metric("MT5 symbol", PROFILE.mt5_symbol)
    identity[3].metric("Contract", "1 lot = 1 BTC")
    st.caption(f"Volume step {PROFILE.volume_step_lots:g} lot · Maximum {PROFILE.maximum_volume_lots:g} lots · "
               f"Commission $0 · Spread: floating historical Bid/Ask · Chart: Bid · "
               f"Swap dollar conversion: {PROFILE.swap_usd_conversion}")

    multi_path = report_dir / "multi_sample_summary.json"
    summary_path = multi_path if multi_path.exists() else report_dir / "tick_import_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"status": "not_imported"}
    server_time = summary.get("status") == "imported_server_time_unverified"
    if summary.get("status") == "mt5_samples_reconstructed":
        _render_mt5_samples(summary, report_dir)
    elif summary.get("status") in ("imported", "imported_server_time_unverified"):
        clock = "server" if server_time else "utc"
        clock_label = "unverified MT5 broker-server time" if server_time else "UTC"
        if server_time:
            st.info("Timestamp timezone is unverified. Dates, candles, hours, and weekdays below use MT5 broker-server wall time; they are not UTC data.")
        st.caption(f"Imported source: {summary['source_file']} · {clock_label} range: "
                   f"{summary[f'first_tick_{clock}']} to {summary[f'last_tick_{clock}']}")
        cards = st.columns(4)
        cards[0].metric("Ticks", f"{summary['tick_count']:,}")
        cards[1].metric("Median spread", _money(summary["median_spread_price"]))
        cards[2].metric("Mean spread", _money(summary["mean_spread_price"]))
        cards[3].metric("P95 spread", _money(summary["p95_spread_price"]))
        cards2 = st.columns(4)
        cards2[0].metric("Maximum spread", _money(summary["maximum_spread_price"]))
        cards2[1].metric("15m Bid candles", f"{summary['bid_15m_candles']:,}")
        cards2[2].metric("15m Ask candles", f"{summary['ask_15m_candles']:,}")
        cards2[3].metric("Missing 15m intervals", f"{summary['missing_15m_intervals']:,}")
        st.caption(f"Last imported {summary['imported_at_utc']} UTC · "
                   f"Raw rows {summary['input_rows']:,} · Invalid Bid/Ask {summary.get('invalid_bid_ask_rows', 0):,} · "
                   f"Duplicate full rows {summary.get('duplicate_full_rows', summary['duplicates_removed']):,} · "
                   f"Duplicate timestamps {summary.get('duplicate_timestamps_raw', 0):,} "
                   f"(including full-row duplicates) · Distinct quotes sharing a timestamp "
                   f"{summary.get('same_timestamp_distinct_quotes', 0):,} · "
                   f"Median {summary['median_spread_bps']:.2f} bps")
        st.caption(summary["time_weighted_spread_note"])
        hourly_path = report_dir / ("spread_by_server_hour.csv" if server_time else "spread_by_hour.csv")
        if hourly_path.exists():
            hourly = pd.read_csv(hourly_path)
            if not hourly.empty:
                fig = px.line(hourly, x=f"{clock}_hour", y="median_spread_price", markers=True,
                              title=f"Median spread by {clock_label} hour", template="plotly_dark")
                fig.update_xaxes(dtick=1)
                st.plotly_chart(fig, width="stretch")
                with st.expander(f"Spread by {clock_label} hour and weekday", expanded=False):
                    st.dataframe(hourly.round(3), hide_index=True, width="stretch")
                    weekday_path = report_dir / ("spread_by_server_weekday.csv" if server_time else "spread_by_weekday.csv")
                    if weekday_path.exists():
                        st.dataframe(pd.read_csv(weekday_path).round(3),
                                     hide_index=True, width="stretch")
        distribution_path = report_dir / "spread_distribution.csv"
        if distribution_path.exists():
            spread = pd.read_csv(distribution_path)
            price = spread.loc[spread.unit == "USD/BTC"]
            if not price.empty:
                fig = px.bar(price, x="metric", y="value", title="Tick spread distribution quantiles",
                             template="plotly_dark")
                fig.update_xaxes(tickangle=-30)
                st.plotly_chart(fig, width="stretch")
        gaps_path = report_dir / ("data_gaps_server_time.csv" if server_time else "data_gaps.csv")
        if gaps_path.exists():
            with st.expander("15-minute data gaps and extreme spread periods", expanded=False):
                gaps = pd.read_csv(gaps_path)
                st.caption(f"{len(gaps):,} gaps · No candles were fabricated.")
                if not gaps.empty:
                    st.dataframe(gaps, hide_index=True, width="stretch")
                extremes = report_dir / ("extreme_spread_periods_server_time.csv" if server_time
                                        else "extreme_spread_periods.csv")
                if extremes.exists():
                    extreme_rows = pd.read_csv(extremes)
                    st.caption(f"{len(extreme_rows):,} {clock_label} 15-minute periods contained ticks above P99 spread; none removed.")
                    if not extreme_rows.empty:
                        st.dataframe(extreme_rows.head(100), hide_index=True, width="stretch")
    else:
        st.info("No Exness BTCUSDm tick history has been imported. Historical spread and candle metrics are unavailable.")
    st.caption("MT5 screenshot sanity check: Ask ≈ 76839.14, Bid ≈ 76829.14, spread ≈ $10/BTC at that instant. Historical ticks determine research costs.")

    raw_dir.mkdir(parents=True, exist_ok=True)
    available = sorted(path for path in raw_dir.iterdir()
                       if path.is_file() and path.suffix.lower() in (".csv", ".zip"))
    with st.expander("Inspect and import raw Exness tick files", expanded=False):
        st.caption("Place untouched BTCUSDm CSV or ZIP files in data/exness/raw/. Inspect actual headers, then choose exact timestamp, Bid, and Ask columns. Naive timestamps may be preserved as unverified broker-server time until their offset is known.")
        if not available:
            st.caption("No CSV or ZIP files are present in data/exness/raw/.")
            return
        chosen = st.multiselect("Raw tick files", [path.name for path in available],
                                default=[path.name for path in available])
        if not chosen:
            return
        paths = [raw_dir / name for name in chosen]
        try:
            schemas = [schema for path in paths for schema in inspect_tick_source(path)]
        except (TickImportError, OSError, zipfile.BadZipFile) as exc:
            st.error(f"Tick schema inspection failed: {exc}")
            return
        for schema in schemas:
            label = f"{Path(schema.file).name}/{schema.member}" if schema.member else Path(schema.file).name
            st.caption(f"{label}: {', '.join(schema.columns)} · delimiter {schema.delimiter!r}")
            if schema.sample:
                st.dataframe(pd.DataFrame(schema.sample), hide_index=True, width="stretch")
        mt5_columns = ("<DATE>", "<TIME>", "<BID>", "<ASK>", "<LAST>", "<VOLUME>", "<FLAGS>")
        if all(schema.member is None and schema.columns == mt5_columns for schema in schemas):
            st.caption("MT5 mode reconstructs partial Bid/Ask updates in original row order. Each file is a separate sample; time remains unverified broker-server time.")
            if st.button("Reconstruct MT5 BTCUSDm Samples", type="primary"):
                try:
                    with st.spinner("Reconstructing independent MT5 quote samples…"):
                        imported = process_mt5_samples(paths)
                    st.success(f"Processed {imported['sample_count']} samples and "
                               f"{imported['total_ticks']:,} complete quote states.")
                    st.rerun()
                except (TickImportError, OSError, ValueError) as exc:
                    st.error(f"MT5 sample processing stopped: {exc}")
            return
        common = sorted(set.intersection(*(set(schema.columns) for schema in schemas)))
        options = ["Choose column", *common]
        cols = st.columns(2)
        timestamp_name = cols[0].selectbox("Timestamp or date column", options, key="exness_timestamp_column")
        time_name = cols[1].selectbox("Separate time column (optional)", ["None", *common],
                                      key="exness_time_column")
        quote_cols = st.columns(2)
        bid_name = quote_cols[0].selectbox("Bid column", options, key="exness_bid_column")
        ask_name = quote_cols[1].selectbox("Ask column", options, key="exness_ask_column")
        preserve_server_time = st.checkbox("Preserve naive timestamps as unverified MT5 broker-server time",
                                            value=False)
        if preserve_server_time:
            st.caption("This keeps the original wall-clock values and writes separate server-time files. No UTC conversion or UTC-hour claim is made.")
        timezone_name = st.text_input("Source timezone for naive timestamps", value="",
                                      disabled=preserve_server_time,
                                      help="Use only a verified timezone. Offset-aware timestamps need no source timezone.")
        unit = st.selectbox("Numeric timestamp unit", ["None", "s", "ms", "us", "ns"],
                            disabled=preserve_server_time)
        skip_incomplete = st.checkbox(
            "Exclude rows with missing Bid or Ask (report count; no forward fill)", value=False)
        if st.button("Import Exness Tick History", type="primary"):
            if "Choose column" in (timestamp_name, bid_name, ask_name):
                st.error("Choose exact timestamp, Bid, and Ask columns first.")
            else:
                try:
                    with st.spinner("Validating and importing Exness Bid/Ask ticks…"):
                        imported = import_tick_sources(
                            paths, TickColumns(timestamp_name, bid_name, ask_name,
                                               None if time_name == "None" else time_name),
                            source_timezone=None if preserve_server_time else timezone_name.strip() or None,
                            timestamp_unit=None if preserve_server_time or unit == "None" else unit,
                            server_time_unverified=preserve_server_time,
                            skip_incomplete_quotes=skip_incomplete)
                    st.success(f"Imported {imported['tick_count']:,} unique ticks and "
                               f"{imported['bid_15m_candles']:,} Bid candles.")
                    st.rerun()
                except (TickImportError, OSError, ValueError, pd.errors.ParserError) as exc:
                    st.error(f"Exness tick import stopped: {exc}")
