import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from services.market_datasets import all_datasets, dataset
from utils.data_validation import load_ohlcv_csv
from .chart import render_tradingview_chart
from .timeframes import (
    UnsupportedTimeframeError,
    available_timeframes,
    load_resolution_data,
    resolve_timeframe,
)

def render_tradingview_mode():
    st.title("TradingView Mode")
    
    # Mode Label
    st.caption("Mode: Historical")
    
    # --- Sidebar Configuration ---
    st.sidebar.header("Chart Settings")
    
    # 1. Symbol/Dataset Selector
    datasets = all_datasets()
    dataset_options = {d.label: d.key for d in datasets}
    selected_label = st.sidebar.selectbox(
        "Dataset", 
        options=list(dataset_options.keys()), 
        index=0
    )
    selected_key = dataset_options[selected_label]
    ds = dataset(selected_key)

    # 2. Timeframe Selector: native or safely derivable for this provider/symbol.
    timeframe_options = available_timeframes(ds)
    default_index = timeframe_options.index(ds.timeframe)

    selected_tf_label = st.sidebar.selectbox(
        "Timeframe", 
        options=list(timeframe_options),
        index=default_index
    )
    try:
        resolution = resolve_timeframe(ds, selected_tf_label)
        active_ds = resolution.source
    except UnsupportedTimeframeError as exc:
        st.error(str(exc))
        return
    st.sidebar.caption(f"Source: {resolution.source_label}")

    # 3. Date Range Selector
    col1, col2 = st.sidebar.columns(2)
    try:
        df_full = load_resolution_data(resolution, load_ohlcv_csv)
        min_date = df_full['timestamp'].min().date()
        max_date = df_full['timestamp'].max().date()
    except Exception:
        min_date = datetime.now().date() - timedelta(days=365)
        max_date = datetime.now().date()

    with col1:
        start_date = st.date_input("Start Date", value=max_date - timedelta(days=30), min_value=min_date, max_value=max_date)
    with col2:
        end_date = st.date_input("End Date", value=max_date, min_value=min_date, max_value=max_date)

    # 4. Optional Volume
    show_volume = st.sidebar.checkbox("Show Volume", value=True)

    # --- Data Loading & Processing ---
    try:
        # Load data
        df = load_resolution_data(resolution, load_ohlcv_csv)
        
        # Filter by date range
        mask = (df['timestamp'].dt.date >= start_date) & (df['timestamp'].dt.date <= end_date)
        df_filtered = df.loc[mask].copy()
        
        # Preserve UTC timestamps
        df_filtered['timestamp'] = pd.to_datetime(df_filtered['timestamp'], utc=True)

        # Render the chart
        render_tradingview_chart(df_filtered, show_volume=show_volume)

    except Exception as e:
        st.error(f"Error loading market data: {e}")
