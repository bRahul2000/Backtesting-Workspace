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


def _money(value) -> str:
    return "—" if value is None else f"${value:,.2f}"


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

    summary_path = report_dir / "tick_import_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {"status": "not_imported"}
    if summary.get("status") == "imported":
        st.caption(f"Imported source: {summary['source_file']} · UTC range: "
                   f"{summary['first_tick_utc']} to {summary['last_tick_utc']}")
        cards = st.columns(4)
        cards[0].metric("Ticks", f"{summary['tick_count']:,}")
        cards[1].metric("Median spread", _money(summary["median_spread_price"]))
        cards[2].metric("Mean spread", _money(summary["mean_spread_price"]))
        cards[3].metric("P95 spread", _money(summary["p95_spread_price"]))
        cards2 = st.columns(3)
        cards2[0].metric("Maximum spread", _money(summary["maximum_spread_price"]))
        cards2[1].metric("15m Bid candles", f"{summary['bid_15m_candles']:,}")
        cards2[2].metric("Missing 15m intervals", f"{summary['missing_15m_intervals']:,}")
        st.caption(f"Last imported {summary['imported_at_utc']} · "
                   f"{summary['duplicates_removed']:,} exact duplicate ticks removed · "
                   f"Median {summary['median_spread_bps']:.2f} bps")
        st.caption(summary["time_weighted_spread_note"])
        hourly_path = report_dir / "spread_by_hour.csv"
        if hourly_path.exists():
            hourly = pd.read_csv(hourly_path)
            if not hourly.empty:
                fig = px.line(hourly, x="utc_hour", y="median_spread_price", markers=True,
                              title="Median spread by UTC hour", template="plotly_dark")
                fig.update_xaxes(dtick=1)
                st.plotly_chart(fig, width="stretch")
                with st.expander("Spread by UTC hour and weekday", expanded=False):
                    st.dataframe(hourly.round(3), hide_index=True, width="stretch")
                    weekday_path = report_dir / "spread_by_weekday.csv"
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
        gaps_path = report_dir / "data_gaps.csv"
        if gaps_path.exists():
            with st.expander("15-minute data gaps and extreme spread periods", expanded=False):
                gaps = pd.read_csv(gaps_path)
                st.caption(f"{len(gaps):,} gaps · No candles were fabricated.")
                if not gaps.empty:
                    st.dataframe(gaps, hide_index=True, width="stretch")
                extremes = report_dir / "extreme_spread_periods.csv"
                if extremes.exists():
                    extreme_rows = pd.read_csv(extremes)
                    st.caption(f"{len(extreme_rows):,} UTC 15-minute periods contained ticks above P99 spread; none removed.")
                    if not extreme_rows.empty:
                        st.dataframe(extreme_rows.head(100), hide_index=True, width="stretch")
    else:
        st.info("No Exness BTCUSDm tick history has been imported. Historical spread and candle metrics are unavailable.")
    st.caption("MT5 screenshot sanity check: Ask ≈ 76839.14, Bid ≈ 76829.14, spread ≈ $10/BTC at that instant. Historical ticks determine research costs.")

    raw_dir.mkdir(parents=True, exist_ok=True)
    available = sorted(path for path in raw_dir.iterdir()
                       if path.is_file() and path.suffix.lower() in (".csv", ".zip"))
    with st.expander("Inspect and import raw Exness tick files", expanded=False):
        st.caption("Place untouched BTCUSDm CSV or ZIP files in data/exness/raw/. Inspect actual headers, then choose exact timestamp, Bid, and Ask columns. Naive timestamps need a verified source timezone.")
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
        common = sorted(set.intersection(*(set(schema.columns) for schema in schemas)))
        options = ["Choose column", *common]
        cols = st.columns(3)
        time_name = cols[0].selectbox("Timestamp column", options, key="exness_timestamp_column")
        bid_name = cols[1].selectbox("Bid column", options, key="exness_bid_column")
        ask_name = cols[2].selectbox("Ask column", options, key="exness_ask_column")
        timezone_name = st.text_input("Source timezone for naive timestamps", value="",
                                      help="Leave blank only when timestamps already include an offset or Z.")
        unit = st.selectbox("Numeric timestamp unit", ["None", "s", "ms", "us", "ns"])
        if st.button("Import Exness Tick History", type="primary"):
            if "Choose column" in (time_name, bid_name, ask_name):
                st.error("Choose exact timestamp, Bid, and Ask columns first.")
            else:
                try:
                    with st.spinner("Validating and importing Exness Bid/Ask ticks…"):
                        imported = import_tick_sources(
                            paths, TickColumns(time_name, bid_name, ask_name),
                            source_timezone=timezone_name.strip() or None,
                            timestamp_unit=None if unit == "None" else unit)
                    st.success(f"Imported {imported['tick_count']:,} unique ticks and "
                               f"{imported['bid_15m_candles']:,} Bid candles.")
                    st.rerun()
                except (TickImportError, OSError, ValueError, pd.errors.ParserError) as exc:
                    st.error(f"Exness tick import stopped: {exc}")
