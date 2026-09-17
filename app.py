from __future__ import annotations

from datetime import date
from pathlib import Path
import json

import pandas as pd
import streamlit as st

from services.bitstamp import (
    BITSTAMP_STEP_SECONDS,
    BitstampAPIError,
    latest_complete_candle_open,
)
from services.history import sync_btc_history
from utils.data_validation import (
    DataValidationError,
    continuous_segments,
    format_timeframe,
    load_ohlcv_csv,
    merge_ohlcv,
    missing_gaps,
    prepare_ohlcv,
    save_ohlcv_csv,
    validate_ohlcv,
)
from ui.backtest_dashboard import render_backtest_panel


APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "data" / "btcusd_15m.csv"
PROVENANCE_FILE = APP_DIR / "data" / "btcusd_15m_provenance.json"
EARLIEST_SELECTABLE_DATE = date(2011, 8, 18)


def streamlit_supports_width() -> bool:
    try:
        major, minor = (int(part) for part in st.__version__.split(".")[:2])
        return (major, minor) >= (1, 50)
    except (TypeError, ValueError):
        return False


def full_width_dataframe(data: pd.DataFrame) -> None:
    if streamlit_supports_width():
        st.dataframe(data, width="stretch", hide_index=True)
    else:
        st.dataframe(data, use_container_width=True, hide_index=True)


st.set_page_config(
    page_title="BTC Strategy Backtester",
    page_icon="₿",
    layout="wide",
)

st.markdown(
    """
    <style>
        .block-container {max-width: 1280px; padding-top: 2rem; padding-bottom: 3rem;}
        [data-testid="stMetric"] {
            border: 1px solid rgba(128, 128, 128, 0.25);
            border-radius: 0.75rem;
            padding: 0.85rem 1rem;
            background: rgba(128, 128, 128, 0.06);
        }
        .data-source-note {
            padding: 0.85rem 1rem;
            border-left: 3px solid #ffb000;
            background: rgba(255, 176, 0, 0.08);
            border-radius: 0.35rem;
        }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def cached_load_saved_data(path: str, modified_ns: int) -> pd.DataFrame:
    """Load a saved dataset, with file modification time as the cache key."""
    del modified_ns
    return load_ohlcv_csv(Path(path))


@st.cache_data(show_spinner=False)
def parse_uploaded_csv(file_bytes: bytes) -> pd.DataFrame:
    from io import BytesIO

    raw = pd.read_csv(BytesIO(file_bytes))
    prepared, _ = prepare_ohlcv(raw)
    return prepared


def get_saved_data() -> tuple[pd.DataFrame, str | None]:
    if not DATA_FILE.exists():
        return pd.DataFrame(), None

    try:
        modified_ns = DATA_FILE.stat().st_mtime_ns
        return cached_load_saved_data(str(DATA_FILE), modified_ns), None
    except (OSError, DataValidationError, pd.errors.ParserError) as exc:
        return pd.DataFrame(), str(exc)


def inclusive_utc_range(start_day: date, end_day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(start_day, tz="UTC")
    end = pd.Timestamp(end_day, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(
        seconds=BITSTAMP_STEP_SECONDS
    )
    end = min(end, latest_complete_candle_open())
    return start, end


def display_dataset(data: pd.DataFrame) -> None:
    report = validate_ohlcv(data, expected_step_seconds=BITSTAMP_STEP_SECONDS)

    st.subheader("Dataset Summary")
    row_one = st.columns(3)
    row_one[0].metric("Total Candles", f"{report.total_candles:,}")
    row_one[1].metric(
        "First Candle (UTC)",
        report.first_candle.strftime("%Y-%m-%d %H:%M") if report.first_candle else "—",
    )
    row_one[2].metric(
        "Last Candle (UTC)",
        report.last_candle.strftime("%Y-%m-%d %H:%M") if report.last_candle else "—",
    )

    row_two = st.columns(3)
    row_two[0].metric("Detected Timeframe", format_timeframe(report.detected_timeframe_minutes))
    row_two[1].metric("Missing 15m Candles", f"{report.missing_candles:,}")
    row_two[2].metric("Invalid OHLCV Rows", f"{report.invalid_ohlcv_rows:,}")

    segments = continuous_segments(data, BITSTAMP_STEP_SECONDS)
    st.caption(
        f"Expected candles: {report.expected_candles:,} · "
        f"Duplicate timestamps: {report.duplicate_timestamps:,} · "
        f"Continuous segments: {len(segments):,} · "
        f"Last update: {pd.Timestamp(DATA_FILE.stat().st_mtime, unit='s', tz='UTC'):%Y-%m-%d %H:%M UTC}"
    )
    if PROVENANCE_FILE.exists():
        provenance = json.loads(PROVENANCE_FILE.read_text())
        st.caption(
            f"Archive provenance: {provenance['source']}; "
            f"{provenance['api_derived_overlap_checked']:,} API-derived "
            "overlap candles matched the saved data. See "
            "data/btcusd_15m_provenance.json for source details."
        )
    st.subheader("Continuous Segments")
    full_width_dataframe(pd.DataFrame([
        {"Start UTC": segment.start, "End UTC": segment.end, "Candles": segment.candles}
        for segment in segments
    ]))
    gaps = missing_gaps(data, BITSTAMP_STEP_SECONDS)
    if gaps:
        with st.expander(f"Missing-data gaps ({len(gaps):,})"):
            full_width_dataframe(pd.DataFrame([
                {"Gap Start UTC": gap.start, "Gap End UTC": gap.end,
                 "Missing Candles": gap.missing_candles}
                for gap in gaps
            ]))

    if report.detected_timeframe_minutes is not None and not report.is_expected_timeframe:
        st.warning("The dominant interval in this dataset is not 15 minutes.")
    if report.missing_candles:
        st.warning(
            f"Detected {report.missing_candles:,} missing 15-minute candle(s). "
            "They are reported only; no candles were fabricated."
        )
    else:
        st.success("No missing 15-minute candles were detected between the first and last row.")
    if report.invalid_ohlcv_rows:
        st.error(
            f"Detected {report.invalid_ohlcv_rows:,} invalid OHLCV row(s). "
            "Review the source before using this data for a backtest."
        )

    st.subheader("Data Preview")
    full_width_dataframe(data.head(100))
    st.caption("Showing the first 100 rows, sorted oldest to newest. Timestamps are UTC.")


st.title("BTC Strategy Backtester")
st.caption("Download and validate BTC/USD data, then run the demo or BTC V2.2 Setup B backtest.")

st.subheader("Market Data")
symbol_col, timeframe_col, location_col = st.columns([1, 1, 2])
symbol_col.text_input("Symbol", value="BTC/USD", disabled=True)
timeframe_col.text_input("Timeframe", value="15 Minutes", disabled=True)
location_col.text_input("Local Dataset", value=str(DATA_FILE.relative_to(APP_DIR)), disabled=True)

saved_data, saved_data_error = get_saved_data()
if saved_data_error:
    st.error(f"The saved dataset could not be loaded: {saved_data_error}")

today_utc = pd.Timestamp.now(tz="UTC").date()
default_end = today_utc
default_start = date(2023, 1, 1)

date_col, end_col = st.columns(2)
selected_start = date_col.date_input(
    "Start Date",
    value=default_start,
    min_value=EARLIEST_SELECTABLE_DATE,
    max_value=today_utc,
)
selected_end = end_col.date_input(
    "End Date",
    value=default_end,
    min_value=EARLIEST_SELECTABLE_DATE,
    max_value=today_utc,
)

st.markdown(
    '<div class="data-source-note">Update BTC History uses the Bitstamp public OHLC API. '
    "The saved file may include documented archive-derived candles; its provenance is shown below. "
    "The currently open 15-minute candle is excluded.</div>",
    unsafe_allow_html=True,
)

button_width = {"width": "stretch"} if streamlit_supports_width() else {"use_container_width": True}
download_clicked = st.button("Update BTC History", type="primary", **button_width)

active_data = saved_data

if download_clicked:
    if selected_start > selected_end:
        st.error("Start Date must be before or equal to End Date.")
    else:
        range_start, range_end = inclusive_utc_range(selected_start, selected_end)
        if range_start > range_end:
            st.error("The selected range does not contain a completed 15-minute candle yet.")
        else:
            progress_bar = st.progress(0.0, text="Preparing resumable Bitstamp history update…")
            try:
                def show_progress(completed: int, total: int, saved: int) -> None:
                    progress_bar.progress(
                        completed / max(total, 1),
                        text=f"API chunk {completed:,}/{total:,} · {saved:,} candles checkpointed",
                    )

                sync = sync_btc_history(
                    range_start, range_end, path=DATA_FILE, progress=show_progress,
                )
                cached_load_saved_data.clear()
                st.session_state.pop("demo_backtest", None)
                active_data = load_ohlcv_csv(DATA_FILE) if DATA_FILE.exists() else saved_data
                progress_bar.progress(1.0, text="History update finished.")
                message = (
                    f"Processed {sync.completed_chunks:,} API chunks; "
                    f"saved {sync.saved_candles:,} unique candles to "
                    f"{DATA_FILE.relative_to(APP_DIR)}."
                )
                if sync.remaining_candles:
                    st.warning(
                        message + f" {sync.remaining_candles:,} requested candles remain "
                        "missing; no candles were fabricated. Run the update again to retry."
                    )
                else:
                    st.success(message)
            except (BitstampAPIError, DataValidationError, OSError, ValueError) as exc:
                progress_bar.empty()
                cached_load_saved_data.clear()
                active_data = load_ohlcv_csv(DATA_FILE) if DATA_FILE.exists() else saved_data
                st.error(
                    f"BTC history update stopped: {exc}. Completed chunks are already "
                    "saved; use Update BTC History to resume."
                )

st.divider()

with st.expander("Manual CSV Upload (fallback)", expanded=False):
    st.write(
        "Use this only when the automatic download is unavailable. The CSV must contain "
        "timestamp, open, high, low, close, and volume columns."
    )
    uploaded_file = st.file_uploader("Choose a BTC 15-minute CSV", type=["csv"])
    if uploaded_file is not None:
        try:
            uploaded_data = parse_uploaded_csv(uploaded_file.getvalue())
            upload_report = validate_ohlcv(uploaded_data, BITSTAMP_STEP_SECONDS)
            full_width_dataframe(uploaded_data.head(100))
            st.caption(
                f"{len(uploaded_data):,} rows · {upload_report.missing_candles:,} missing candles · "
                f"{upload_report.invalid_ohlcv_rows:,} invalid rows"
            )
            if upload_report.invalid_ohlcv_rows:
                st.error("This CSV contains invalid OHLCV rows and cannot be added to the local dataset.")
            elif st.button("Add Uploaded Data to Local Dataset"):
                combined = merge_ohlcv(saved_data, uploaded_data)
                save_ohlcv_csv(combined, DATA_FILE)
                cached_load_saved_data.clear()
                st.session_state.pop("demo_backtest", None)
                active_data = combined
                st.success(f"Saved {len(combined):,} unique candles to {DATA_FILE.relative_to(APP_DIR)}.")
        except (DataValidationError, pd.errors.ParserError, UnicodeDecodeError) as exc:
            st.error(f"The uploaded CSV could not be used: {exc}")

if not active_data.empty:
    st.divider()
    display_dataset(active_data)
else:
    st.info("No local BTC/USD dataset is available yet. Select a date range and download it above.")

render_backtest_panel(active_data)
