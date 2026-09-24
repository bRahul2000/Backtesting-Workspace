import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime

def render_tradingview_chart(df: pd.DataFrame, show_volume: bool = True):
    """
    Renders a TradingView-style candlestick chart with an optional volume pane.
    Expects df with columns: [timestamp, open, high, low, close, volume]
    """
    if df.empty:
        st.warning("No data available for the selected range.")
        return

    # Create subplots: Row 1 for candles, Row 2 for volume (if enabled)
    rows = 2 if show_volume else 1
    # Adjusted row heights: Volume slightly larger for visibility, but still secondary
    row_heights = [0.75, 0.25] if show_volume else [1.0]
    
    fig = make_subplots(
        rows=rows, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.05, 
        row_heights=row_heights
    )

    # Candlestick Chart
    fig.add_trace(
        go.Candlestick(
            x=df['timestamp'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name="Price"
        ),
        row=1, col=1
    )

    # Volume Chart
    if show_volume and 'volume' in df.columns:
        # Color volume bars based on price direction
        colors = ['green' if row['close'] >= row['open'] else 'red' for _, row in df.iterrows()]
        
        fig.add_trace(
            go.Bar(
                x=df['timestamp'],
                y=df['volume'],
                marker_color=colors,
                name="Volume",
                opacity=0.6
            ),
            row=2, col=1
        )

    # Styling to match TradingView "Dark Mode"
    fig.update_layout(
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=20, b=10),
        height=800, # Fixed height to better use available area
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)', side="right")
    
    # Specifically set the volume axis to be transparent/minimal
    if show_volume:
        fig.update_yaxes(showticklabels=False, row=2, col=1)

    st.plotly_chart(fig, use_container_width=True, config={'modeBarButtonsToAdd': ['drawline', 'drawopenpath', 'eraseshape']})
