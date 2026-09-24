import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from services.market_datasets import all_datasets, dataset, datasets_for_instrument
from utils.data_validation import load_ohlcv_csv
from .chart import render_tradingview_chart

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

    # 2. Timeframe Selector (Filtered by instrument)
    # Only show timeframes available for this specific instrument
    instrument_datasets = datasets_for_instrument(ds.instrument)
    
    # Create a mapping of purely the timeframe label (e.g., '15m') to the dataset key
    # We use a list of tuples to maintain order and handle potential duplicate labels
    tf_options_list = []
    for d in instrument_datasets:
        # Ensure we only use the timeframe part of the label
        tf_label = d.timeframe
        tf_options_list.append((tf_label, d.key))
    
    # For the selectbox, we use the labels. We must handle cases where multiple datasets 
    # have the same timeframe label (though rare in Phase 1).
    unique_tf_labels = [opt[0] for opt in tf_options_list]
    
    # Find current index
    try:
        current_tf_label = ds.timeframe
        default_index = unique_tf_labels.index(current_tf_label)
    except ValueError:
        default_index = 0

    selected_tf_label = st.sidebar.selectbox(
        "Timeframe", 
        options=unique_tf_labels, 
        index=default_index
    )
    
    # Map selected label back to the correct dataset key
    # In Phase 1, we assume 1:1 mapping for the selected instrument's TFs
    selected_key_tf = next(key for label, key in tf_options_list if label == selected_tf_label)
    active_ds = dataset(selected_key_tf)

    # 3. Date Range Selector
    col1, col2 = st.sidebar.columns(2)
    try:
        df_full = load_ohlcv_csv(active_ds.path)
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
        df = load_ohlcv_csv(active_ds.path)
        
        # Filter by date range
        mask = (df['timestamp'].dt.date >= start_date) & (df['timestamp'].dt.date <= end_date)
        df_filtered = df.loc[mask].copy()
        
        # Preserve UTC timestamps
        df_filtered['timestamp'] = pd.to_datetime(df_filtered['timestamp'], utc=True)

        # Render the chart
        render_tradingview_chart(df_filtered, show_volume=show_volume)

    except Exception as e:
        st.error(f"Error loading market data: {e}")
