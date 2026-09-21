"""Where the frozen Core is not looking — a DEVELOPMENT-only census of M15 bars.

Phase D needs an *additive* opportunity pool, so before inventing a setup it is
worth measuring which market states A4 and T3 structurally cannot reach. This
module classifies every completed development bar and measures how much of each
bucket the frozen Core already occupies.

It is a census, not a strategy. Every classification uses only information a
strategy could have had at the close of that bar: the same shadow indicator set
the Core funnel observer uses, and the previously confirmed H1 value. The one
exception is the reclaim event, which is written causally — the break is
detected on the *previous* bar and the failure on the current one.

Thresholds here are descriptive, chosen to match the frozen children's own
constants where those exist (H1 separation 1.00 for trend, 0.80 for range, ADX
18, 5-bar structure) so the buckets line up with what the strategies actually
test. The volatility thresholds have no counterpart in the frozen source and are
stated as round numbers rather than tuned.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from core.trade_log import to_timestamp
from engine.models import Candle
from strategies.btc_v3_a4_pullback_long import SETUP_ID as A4_SETUP_ID
from strategies.btc_v3_t3_breakout_short import TREND_SETUP_ID as T3_SETUP_ID
from strategies.confirmed_h1_regime import ConfirmedH1Regime
from strategies.pine_indicators import ATR, DMI, EMA, RSI

#--- Matched to the frozen children so the buckets describe what they test.
TREND_SEPARATION = 1.00
RANGE_SEPARATION = 0.80
MIN_ADX = 18.0
STRUCTURE_LOOKBACK = 5
#--- No counterpart in the frozen source; round numbers, not tuned.
COMPRESSION_RATIO = 0.80
EXPANSION_RATIO = 1.25
VOLATILITY_REFERENCE_BARS = 480  # five days of M15


@dataclass
class BarState:
    timestamp: pd.Timestamp
    h1_regime: str
    volatility: str
    events: tuple[str, ...]
    covered: bool


def classify(candles: list[Candle]) -> list[BarState]:
    h1 = ConfirmedH1Regime(50, 200, 14, 4)
    fast, slow = EMA(20), EMA(50)
    atr, rsi, dmi = ATR(14), RSI(14), DMI(14, 14)
    history: list[Candle] = []
    atr_history: list[float] = []
    previous_broke_high = previous_broke_low = False
    previous_high_level = previous_low_level = None
    output: list[BarState] = []

    for candle in candles:
        regime = h1.update(candle)
        ema20 = fast.update(candle.close)
        ema50 = slow.update(candle.close)
        atr_value = atr.update(candle)
        rsi.update(candle.close)
        adx = dmi.update(candle).adx
        prior = history[-STRUCTURE_LOOKBACK:]
        prior_high = max(bar.high for bar in prior) if len(prior) == STRUCTURE_LOOKBACK else None
        prior_low = min(bar.low for bar in prior) if len(prior) == STRUCTURE_LOOKBACK else None
        history.append(candle)

        #--- H1 regime, using only the confirmed H1 value.
        separation, slope = regime.separation_atr, regime.slope
        if separation is None or slope is None or adx is None or atr_value is None:
            bucket = "WARMUP"
        elif (separation >= TREND_SEPARATION and adx >= MIN_ADX
              and regime.fast_ema > regime.slow_ema and slope > 0 and ema20 > ema50):
            bucket = "BULLISH_TREND"
        elif (separation >= TREND_SEPARATION and adx >= MIN_ADX
              and regime.fast_ema < regime.slow_ema and slope < 0 and ema20 < ema50):
            bucket = "BEARISH_TREND"
        elif separation <= RANGE_SEPARATION:
            bucket = "NEUTRAL_RANGE"
        else:
            bucket = "TRANSITION"

        #--- Volatility relative to this instrument's own recent ATR.
        volatility = "WARMUP"
        if atr_value is not None:
            reference = atr_history[-VOLATILITY_REFERENCE_BARS:]
            if len(reference) >= VOLATILITY_REFERENCE_BARS // 4:
                median = sorted(reference)[len(reference) // 2]
                if median > 0:
                    ratio = atr_value / median
                    volatility = ("LOW_VOL_COMPRESSION" if ratio <= COMPRESSION_RATIO
                                  else "HIGH_VOL_EXPANSION" if ratio >= EXPANSION_RATIO
                                  else "NORMAL_VOL")
            atr_history.append(atr_value)

        #--- Events. The reclaim is causal: the break happened on the bar before.
        events: list[str] = []
        broke_high = prior_high is not None and candle.close > prior_high
        broke_low = prior_low is not None and candle.close < prior_low
        if broke_high:
            events.append("BREAKOUT_UP")
        if broke_low:
            events.append("BREAKDOWN")
        if previous_broke_high and previous_high_level is not None and candle.close < previous_high_level:
            events.append("FAILED_BREAKOUT_RECLAIM_DOWN")
        if previous_broke_low and previous_low_level is not None and candle.close > previous_low_level:
            events.append("FAILED_BREAKDOWN_RECLAIM_UP")
        if atr_value and ema20 > ema50 and candle.low <= ema20:
            events.append("PULLBACK_TOUCH_LONG")
        if atr_value and ema20 < ema50 and candle.high >= ema20:
            events.append("PULLBACK_TOUCH_SHORT")
        previous_broke_high, previous_high_level = broke_high, prior_high
        previous_broke_low, previous_low_level = broke_low, prior_low

        output.append(BarState(candle.timestamp, bucket, volatility, tuple(events), False))
    return output


def mark_coverage(states: list[BarState], trade_log: list[dict]) -> None:
    """Flag every bar inside an open Core position, entry bar through exit bar."""
    intervals = [(to_timestamp(row["entry_time"]), to_timestamp(row["exit_time"]))
                 for row in trade_log]
    intervals.sort()
    index = 0
    for state in states:
        while index < len(intervals) and intervals[index][1] < state.timestamp:
            index += 1
        state.covered = any(start <= state.timestamp <= end
                            for start, end in intervals[index:index + 4])


def summarise(states: list[BarState], trade_log: list[dict]) -> dict[str, Any]:
    total = len(states)
    by_regime: Counter = Counter()
    by_volatility: Counter = Counter()
    by_event: Counter = Counter()
    covered_regime: Counter = Counter()
    covered_event: Counter = Counter()
    for state in states:
        by_regime[state.h1_regime] += 1
        by_volatility[state.volatility] += 1
        if state.covered:
            covered_regime[state.h1_regime] += 1
        for event in state.events:
            by_event[event] += 1
            if state.covered:
                covered_event[event] += 1

    entries: Counter = Counter()
    for row in trade_log:
        entries[row.get("setup_id") or "UNKNOWN"] += 1
    entry_regime: Counter = Counter()
    lookup = {state.timestamp: state for state in states}
    for row in trade_log:
        state = lookup.get(to_timestamp(row["entry_time"]))
        if state is not None:
            entry_regime[f"{row.get('setup_id')}|{state.h1_regime}"] += 1

    return {
        "bars": total,
        "regime": {name: {"bars": count, "percent_of_bars": round(100 * count / total, 3),
                          "bars_inside_a_core_position": covered_regime[name],
                          "percent_of_bucket_covered": round(
                              100 * covered_regime[name] / count, 3) if count else None}
                   for name, count in by_regime.most_common()},
        "volatility": {name: {"bars": count, "percent_of_bars": round(100 * count / total, 3)}
                       for name, count in by_volatility.most_common()},
        "events": {name: {"bars": count, "percent_of_bars": round(100 * count / total, 3),
                          "bars_inside_a_core_position": covered_event[name],
                          "percent_covered": round(
                              100 * covered_event[name] / count, 3) if count else None}
                   for name, count in by_event.most_common()},
        "core_position_bars": sum(1 for state in states if state.covered),
        "core_position_percent": round(
            100 * sum(1 for state in states if state.covered) / total, 3),
        "core_entries_by_setup": dict(entries),
        "core_entries_by_setup_and_regime": dict(entry_regime),
        "setup_ids": {"a4": A4_SETUP_ID, "t3": T3_SETUP_ID},
    }


def build(candles: list[Candle], trade_log: list[dict]) -> dict[str, Any]:
    states = classify(candles)
    mark_coverage(states, trade_log)
    return summarise(states, trade_log)
