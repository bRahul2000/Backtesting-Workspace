from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

from services.bitstamp import (
    BITSTAMP_STEP_SECONDS,
    BitstampAPIError,
    BitstampClient,
    latest_complete_candle_open,
)
from utils.data_validation import (
    DataValidationError,
    find_missing_ranges,
    format_timeframe,
    load_ohlcv_csv,
    merge_ohlcv,
    prepare_ohlcv,
    save_ohlcv_csv,
    validate_ohlcv,
)
from ui.backtest_dashboard import render_backtest_panel


APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "data" / "btcusd_15m.csv"
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
st.caption("Download and validate BTC/USD data, then run the demo engine test strategy.")

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
default_start = max(EARLIEST_SELECTABLE_DATE, default_end - timedelta(days=30))

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
    '<div class="data-source-note">Source: Bitstamp public OHLC API. '
    "The currently open 15-minute candle is excluded.</div>",
    unsafe_allow_html=True,
)

button_width = {"width": "stretch"} if streamlit_supports_width() else {"use_container_width": True}
download_clicked = st.button("Download / Update BTC Data", type="primary", **button_width)

active_data = saved_data

if download_clicked:
    if selected_start > selected_end:
        st.error("Start Date must be before or equal to End Date.")
    else:
        range_start, range_end = inclusive_utc_range(selected_start, selected_end)
        if range_start > range_end:
            st.error("The selected range does not contain a completed 15-minute candle yet.")
        else:
            missing_ranges = find_missing_ranges(
                saved_data,
                range_start,
                range_end,
                step_seconds=BITSTAMP_STEP_SECONDS,
            )

            if not missing_ranges:
                st.success("The selected period is already complete in the local dataset. No API request was needed.")
            else:
                requested_candles = sum(
                    int((range_finish - range_begin).total_seconds() // BITSTAMP_STEP_SECONDS) + 1
                    for range_begin, range_finish in missing_ranges
                )
                request_counts = [
                    int((finish - begin).total_seconds() // BITSTAMP_STEP_SECONDS) + 1
                    for begin, finish in missing_ranges
                ]
                total_requests = sum((count + 999) // 1000 for count in request_counts)
                progress = st.progress(0.0, text="Preparing Bitstamp download…")
                completed_requests = 0
                downloaded_parts: list[pd.DataFrame] = []

                try:
                    client = BitstampClient()
                    for gap_number, (gap_start, gap_end) in enumerate(missing_ranges, start=1):
                        def update_progress(chunk_number: int, chunk_total: int, rows_received: int) -> None:
                            del chunk_total
                            current = completed_requests + chunk_number
                            fraction = min(current / max(total_requests, 1), 1.0)
                            progress.progress(
                                fraction,
                                text=(
                                    f"Downloading gap {gap_number}/{len(missing_ranges)} · "
                                    f"API request {current}/{total_requests} · "
                                    f"{rows_received:,} rows received"
                                ),
                            )

                        part = client.download_ohlc(
                            gap_start,
                            gap_end,
                            progress_callback=update_progress,
                        )
                        downloaded_parts.append(part)
                        gap_candles = int(
                            (gap_end - gap_start).total_seconds() // BITSTAMP_STEP_SECONDS
                        ) + 1
                        completed_requests += (gap_candles + 999) // 1000

                    downloaded = merge_ohlcv(*downloaded_parts)
                    combined = merge_ohlcv(saved_data, downloaded)
                    if downloaded.empty and saved_data.empty:
                        raise DataValidationError(
                            "Bitstamp returned no candles for the selected period; the local file was not changed."
                        )
                    combined_report = validate_ohlcv(
                        combined,
                        expected_step_seconds=BITSTAMP_STEP_SECONDS,
                    )
                    if combined_report.invalid_ohlcv_rows:
                        raise DataValidationError(
                            "Bitstamp returned invalid OHLCV data; the local file was not changed."
                        )

                    save_ohlcv_csv(combined, DATA_FILE)
                    cached_load_saved_data.clear()
                    st.session_state.pop("demo_backtest", None)
                    active_data = combined
                    progress.progress(1.0, text="Download and validation complete.")
                    remaining_ranges = find_missing_ranges(
                        combined,
                        range_start,
                        range_end,
                        step_seconds=BITSTAMP_STEP_SECONDS,
                    )
                    remaining_candles = sum(
                        int((finish - begin).total_seconds() // BITSTAMP_STEP_SECONDS) + 1
                        for begin, finish in remaining_ranges
                    )
                    result_message = (
                        f"Downloaded {len(downloaded):,} unique candle(s) for "
                        f"{requested_candles:,} requested timestamp(s). "
                        f"Saved {len(combined):,} total candle(s) to {DATA_FILE.relative_to(APP_DIR)}."
                    )
                    if remaining_candles:
                        st.warning(
                            result_message
                            + f" Bitstamp did not return {remaining_candles:,} requested candle(s); "
                            "those gaps remain missing and were not fabricated."
                        )
                    else:
                        st.success(result_message)
                except (BitstampAPIError, DataValidationError, OSError, ValueError) as exc:
                    progress.empty()
                    st.error(f"BTC data could not be updated: {exc}")

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
