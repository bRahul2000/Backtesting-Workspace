import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime

def render_tradingview_chart(df: pd.DataFrame, show_volume: bool = True, indicators=None):
    """
    Renders a TradingView-style candlestick chart with an optional volume pane.
    Expects df with columns: [timestamp, open, high, low, close, volume]
    """
    if df.empty:
        st.warning("No data available for the selected range.")
        return

    indicators = indicators or {}
    lower = list(indicators.get("lower", []))
    rows = 1 + int(show_volume) + len(lower)
    row_heights = [0.62] + ([0.14] if show_volume else []) + ([0.24 / len(lower)] * len(lower) if lower else [])
    
    fig = make_subplots(
        rows=rows, cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.04,
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

    for indicator in indicators.get("overlay", []):
        for name, values in indicator["values"].items():
            fig.add_trace(go.Scatter(x=df["timestamp"], y=values, mode="lines", name=f"{indicator['name']} {name}"), row=1, col=1)

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

    lower_start = 2 + int(show_volume)
    for offset, indicator in enumerate(lower):
        row = lower_start + offset
        for name, values in indicator["values"].items():
            if name == "histogram":
                trace = go.Bar(x=df["timestamp"], y=values, name=f"{indicator['name']} Histogram", opacity=0.55)
            else:
                trace = go.Scatter(x=df["timestamp"], y=values, mode="lines", name=f"{indicator['name']} {name}")
            fig.add_trace(trace, row=row, col=1)
        if indicator["key"] == "rsi":
            for level in (70, 50, 30):
                fig.add_hline(y=level, line_dash="dot", line_color="gray", row=row, col=1)

    # Styling to match TradingView "Dark Mode"
    fig.update_layout(
        template="plotly_dark",
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=10, t=20, b=10),
        height=800,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    
    fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)')
    fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.2)', side="right")
    
    # Specifically set the volume axis to be transparent/minimal
    if show_volume:
        fig.update_yaxes(showticklabels=False, row=2, col=1)

    st.plotly_chart(fig, use_container_width=True, config={'modeBarButtonsToAdd': ['drawline', 'drawopenpath', 'eraseshape']})
