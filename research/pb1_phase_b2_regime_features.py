"""PB1 Phase B.2 — signal-time market-regime features for DEVELOPMENT diagnosis.

Builds a per-trade table for a PB1 configuration by joining three sources:

1. ``UniversalBacktestResult.trade_log`` — the executed trades, carrying the
   Phase A.1-corrected MFE/MAE semantics (excursion price distance / initial
   stop price distance, never quantity-scaled dollar risk).
2. PB1's own diagnostic events — the setup geometry exactly as the strategy
   measured it at the confirmation candle (impulse ATR, retracement, pullback
   duration, confirmation body/range, stop ATR, EMA distances, H1 context).
   Nothing here re-derives strategy logic; it reads what PB1 logged.
3. Independently computed market-regime features (H1 slopes, M15 volatility
   regime, directional efficiency, reversal frequency).

Everything is causal: each feature uses only bars at or before the signal
candle, and the H1 context comes from ``ConfirmedH1Regime``, which exposes
only the previously completed H1 bar. No forward-looking regime labels.

DEVELOPMENT (2021-01-01 .. 2023-12-31) only.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine.backtester import _validated_candles
from strategies.confirmed_h1_regime import ConfirmedH1Regime
from strategies.pine_indicators import ATR
from utils.data_validation import continuous_segments, load_ohlcv_csv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "btcusd_15m.csv"

DEVELOPMENT_START = pd.Timestamp("2021-01-01", tz="UTC")
DEVELOPMENT_END = pd.Timestamp("2023-12-31 23:45", tz="UTC")

# Diagnostic-only lookbacks, defined for this phase and used nowhere in any
# trading decision. Recorded explicitly so the measures are reproducible.
DIRECTIONAL_EFFICIENCY_BARS = 20   # 20 M15 bars = 5 hours
REVERSAL_FREQUENCY_BARS = 20       # same window as directional efficiency
ATR_PERCENTILE_BARS = 2880         # 2880 M15 bars = 30 days
ATR_PERCENTILE_MINIMUM = 200       # minimum observations before a percentile is defined
ATR_EXPANSION_BARS = 96            # 96 M15 bars = 24 hours

# Mirror PB1's own indicator configuration so the reconstructed H1/M15 context
# matches what the strategy saw bar for bar (cross-checked in build_trade_frame).
H1_FAST_LENGTH, H1_SLOW_LENGTH, H1_ATR_LENGTH, H1_SLOPE_LOOKBACK = 50, 200, 14, 4
M15_ATR_LENGTH = 14

DIRECTIONAL_EFFICIENCY_FORMULA = (
    "abs(close[t] - close[t-20]) / sum(abs(close[i] - close[i-1]) for i in t-19..t); "
    "1.0 = perfectly straight move, 0.0 = pure round trip; 20 M15 bars = 5 hours"
)
REVERSAL_FREQUENCY_FORMULA = (
    "count(adjacent close-to-close changes with opposite sign over the trailing "
    "20 bars) / 19"
)
ATR_PERCENTILE_FORMULA = (
    "fraction of the trailing 2880 M15 ATR(14) observations (>=200 required) "
    "that are <= the current ATR"
)
ATR_EXPANSION_FORMULA = "M15 ATR(14) / mean(M15 ATR(14) over the trailing 96 bars)"

# PB1 diagnostic stages consumed here. PB1 emits these in chronological order
# within each continuous segment; no other strategy or observer emits them.
SETUP_STAGES = ("h1_context_evaluated", "impulse_detected", "pullback_depth_valid",
                "confirmation_evaluated", "risk_stop_valid", "pending_order_created")


def _segment_frame(candles: list[Any]) -> pd.DataFrame:
    """Per-bar causal H1/M15 context for one continuous segment."""
    regime = ConfirmedH1Regime(H1_FAST_LENGTH, H1_SLOW_LENGTH, H1_ATR_LENGTH, H1_SLOPE_LOOKBACK)
    atr = ATR(M15_ATR_LENGTH)
    # ConfirmedH1Regime tracks slow-EMA history internally but not fast-EMA
    # history; observing confirmed-hour transitions reproduces exactly the same
    # bookkeeping for the fast EMA without duplicating the aggregation logic.
    fast_history: deque[float] = deque(maxlen=H1_SLOPE_LOOKBACK + 1)
    last_hour = None
    rows = []
    for candle in candles:
        confirmed = regime.update(candle)
        if confirmed.hour is not None and confirmed.hour != last_hour:
            last_hour = confirmed.hour
            fast_history.append(confirmed.fast_ema)
        fast_slope = (fast_history[-1] - fast_history[0]
                      if len(fast_history) == H1_SLOPE_LOOKBACK + 1 else None)
        h1_atr = confirmed.atr
        rows.append({
            "timestamp": candle.timestamp,
            "close": candle.close,
            "m15_atr": atr.update(candle),
            "h1_separation_atr": confirmed.separation_atr,
            "h1_slow_slope_atr": (confirmed.slope / h1_atr
                                  if confirmed.slope is not None and h1_atr else None),
            "h1_fast_slope_atr": (fast_slope / h1_atr
                                  if fast_slope is not None and h1_atr else None),
            "h1_atr": h1_atr,
        })
    frame = pd.DataFrame(rows)
    # Warmup emits None for every indicator, which makes the column object
    # dtype; coerce before any rolling/quantile work downstream.
    for column in frame.columns.drop("timestamp"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")

    close, atr_series = frame["close"], frame["m15_atr"]
    travelled = close.diff().abs().rolling(DIRECTIONAL_EFFICIENCY_BARS).sum()
    displacement = (close - close.shift(DIRECTIONAL_EFFICIENCY_BARS)).abs()
    frame["directional_efficiency"] = np.where(travelled > 0, displacement / travelled, np.nan)

    change = close.diff()
    flipped = (np.sign(change) * np.sign(change.shift()) < 0).astype(float)
    flipped[change.isna() | change.shift().isna()] = np.nan
    frame["reversal_frequency"] = (flipped.rolling(REVERSAL_FREQUENCY_BARS - 1).sum()
                                   / (REVERSAL_FREQUENCY_BARS - 1))

    frame["m15_atr_percentile"] = atr_series.rolling(
        ATR_PERCENTILE_BARS, min_periods=ATR_PERCENTILE_MINIMUM,
    ).apply(lambda window: float((window <= window[-1]).mean()), raw=True)
    frame["m15_atr_expansion"] = atr_series / atr_series.rolling(ATR_EXPANSION_BARS).mean()
    return frame


def market_features(data: pd.DataFrame) -> pd.DataFrame:
    """Causal per-bar regime features, computed inside continuous segments only.

    Segment-local computation mirrors the strategy, which resets every
    indicator on a data gap, and keeps rolling windows from spanning gaps.
    """
    frames = []
    for segment in continuous_segments(data):
        frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        frames.append(_segment_frame(_validated_candles(frame)))
    return pd.concat(frames, ignore_index=True).set_index("timestamp")


def setup_features(signal_diagnostics: list[dict[str, Any]]) -> pd.DataFrame:
    """Setup geometry per created pending order, as PB1 itself measured it.

    Replays PB1's logged event stream through its own single-structure state
    machine: at most one impulse/pullback is live at a time, so the most recent
    impulse and pullback readings are the ones the confirmation belongs to.
    """
    events = [event for event in signal_diagnostics if event["stage"] in SETUP_STAGES]
    context: dict[str, Any] = {}
    impulse: dict[str, Any] = {}
    pullback: dict[str, Any] = {}
    confirmation: dict[str, Any] = {}
    risk: dict[str, Any] = {}
    rows = []
    for event in events:
        stage, metadata = event["stage"], event.get("metadata") or {}
        if stage == "h1_context_evaluated":
            context = metadata
        elif stage == "impulse_detected":
            impulse = metadata
        elif stage == "pullback_depth_valid":
            pullback = metadata
        elif stage == "confirmation_evaluated":
            confirmation = metadata
        elif stage == "risk_stop_valid":
            risk = metadata
        elif stage == "pending_order_created":
            rows.append({
                "confirmation_time": pd.Timestamp(event["timestamp"]),
                "setup_direction": context.get("direction"),
                "pb1_h1_separation_atr": context.get("separation_atr"),
                "pb1_h1_slope": context.get("slope"),
                "pb1_h1_atr": context.get("h1_atr"),
                "impulse_size_atr": impulse.get("impulse_size_atr"),
                "retracement_percent": pullback.get("retracement_percent"),
                "retracement_atr": pullback.get("retracement_atr"),
                "pullback_bars": pullback.get("pullback_duration"),
                "distance_to_ema20": pullback.get("distance_to_ema20"),
                "distance_to_ema50": pullback.get("distance_to_ema50"),
                "confirmation_body_percent": confirmation.get("body_percent"),
                "confirmation_close_location": confirmation.get("close_location"),
                "confirmation_range_atr": confirmation.get("range_atr"),
                "stop_atr": risk.get("stop_atr"),
                "stop_distance": risk.get("stop_distance"),
            })
    return pd.DataFrame(rows).set_index("confirmation_time")


def build_trade_frame(result: Any, market: pd.DataFrame) -> pd.DataFrame:
    """One row per closed trade, with signal-time setup geometry and regime context.

    A pending stop order's ``signal_time`` is the bar *after* the confirmation
    candle (engine/execution.py sets ``signal_time = candle.timestamp + 15m``),
    so the join steps back one bar to reach the confirmation PB1 logged.
    """
    setups = setup_features(result.signal_diagnostics)
    trades = pd.DataFrame(result.trade_log)
    if trades.empty:
        return trades
    for column in ("signal_time", "entry_time", "exit_time"):
        trades[column] = pd.to_datetime(trades[column], utc=True)
    trades["confirmation_time"] = trades["signal_time"] - pd.Timedelta(minutes=15)
    frame = trades.join(setups, on="confirmation_time")
    frame = frame.join(market.drop(columns=["close"]), on="confirmation_time")
    frame["year"] = frame["exit_time"].dt.year
    frame["month"] = frame["exit_time"].dt.strftime("%Y-%m")
    frame["won"] = frame["pnl"] > 1e-9
    if frame["stop_atr"].isna().any():
        raise ValueError("Trade/diagnostic join failed: some trades have no logged setup.")
    mismatch = (frame["pb1_h1_separation_atr"] - frame["h1_separation_atr"]).abs().max()
    if mismatch > 1e-6:
        raise ValueError(
            f"Reconstructed H1 context disagrees with PB1's logged context by {mismatch}; "
            "the independent regime replay is not faithful."
        )
    return frame


def load_development_data() -> pd.DataFrame:
    data = load_ohlcv_csv(DATA)
    window = data.loc[data.timestamp.between(DEVELOPMENT_START, DEVELOPMENT_END)]
    if window.timestamp.max() > DEVELOPMENT_END or window.timestamp.min() < DEVELOPMENT_START:
        raise ValueError("DEVELOPMENT window leaked outside 2021-2023.")
    return window.reset_index(drop=True)
