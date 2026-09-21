"""BTC Core V2 — Phase G: does a fixed 3R survive in the opposed/weak transition pools?

Phase F found the frequency and lost the edge: F3a reached 26.75 Core trades a
month with only 5.7% frozen-child interference, at incremental PF 0.9123. Every
family it tried was a *strategy*, so every rejection was ambiguous — a bad result
could be the pool or could be the construction. This module removes the
strategy. It takes fixed, predeclared events inside the two large target buckets
and measures, for each one, what price did next.

The measurement is deliberately the most favourable honest one. Entry is the
**next bar's open**, not a stop trigger, so nothing is lost to unfilled pending
orders and no entry filter is doing hidden selection. The stop is the repository's
own structural stop — T3's two-bar extreme with its 0.20 ATR buffer, kept inside
T3's 0.50-3.00 ATR validity band — and the target is 3R from entry. If a pool
cannot clear break-even under those conditions, no arrangement of entry rules on
top of it will save it.

Two honesty constraints shape the result and both are reported rather than
smoothed away. Closed-bar OHLC cannot order two touches inside one bar, so a bar
that spans both the target and the stop is counted as ``AMBIGUOUS_SAME_BAR`` and
never silently resolved in either direction. And the break-even rate for a fixed
3R with no ambiguity is **25%**: the whole question is whether any pool clears it.

Every event is measured twice, once trading toward the confirmed H1 lean and
once against it, because the open question is exactly whether the edge is
rotation back to H1 or continuation away from it.

DEVELOPMENT only.
"""
from __future__ import annotations

from collections import Counter
from math import exp, lgamma, log, log1p
from dataclasses import dataclass
from statistics import mean, median
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from core.trade_log import to_timestamp
from engine.models import Candle
from strategies.btc_core_v2_phase_f_families import frozen_bucket
from strategies.btc_v3_t3_breakout_short import V3T3FrozenParameters
from strategies.confirmed_h1_regime import ConfirmedH1Regime
from strategies.pine_indicators import ATR, DMI, EMA

#--- The two pools Phase F sized and the brief targets.
TARGET_BUCKET_REASONS = ("WIDE_BUT_M15_OPPOSED", "WIDE_BUT_WEAK_ADX")

#--- Every constant below is a frozen T3 parameter, not a Phase G choice.
_P = V3T3FrozenParameters()
STOP_LOOKBACK = _P.trend_stop_lookback           # 2
STOP_BUFFER_ATR = _P.stop_buffer_atr             # 0.20
MIN_STOP_ATR = _P.minimum_stop_atr               # 0.50
MAX_STOP_ATR = _P.maximum_stop_atr               # 3.00
REWARD_MULTIPLE = _P.reward_multiple             # 3.0
STRONG_BODY = _P.trend_minimum_body_percent      # 0.70
MIN_RANGE_ATR = _P.trend_minimum_range_atr       # 0.60
MAX_RANGE_ATR = _P.trend_maximum_range_atr       # 2.00

#--- Generous enough to resolve essentially every trade: the frozen Core's own
#--- winners reach 3R in a median of 22 bars, p90 118, longest 425.
HORIZON_BARS = 480

EVENTS = (
    "EMA_REALIGN_WITH_H1",
    "EMA_CROSS_AGAINST_H1",
    "STRUCTURE_BREAK_3_TOWARD_H1",
    "STRUCTURE_BREAK_5_TOWARD_H1",
    "STRUCTURE_BREAK_3_AGAINST_H1",
    "STRUCTURE_BREAK_5_AGAINST_H1",
    "STRONG_CLOSE_TOWARD_H1",
    "STRONG_CLOSE_AGAINST_H1",
    "EMA20_REJECTION",
    "EMA50_REJECTION",
)
DIRECTIONS = ("TOWARD_H1", "AGAINST_H1")


@dataclass
class BarContext:
    """Everything Phase G needs about one bar, from closed-bar information only."""
    index: int
    timestamp: pd.Timestamp
    bucket: str
    reason: str | None
    lean: str
    atr: float | None
    ema20: float
    ema50: float
    stop_low: float
    stop_high: float
    events: tuple[str, ...]


def _transition_reason(separation, slope, adx, h1, ema20, ema50) -> str:
    from research.core_v2_phase_f_map import _transition_reason as reason
    return reason(separation, slope, adx, h1, ema20, ema50)


def contexts(candles: Sequence[Candle]) -> list[BarContext]:
    """One streaming pass: indicators, frozen bucket, sub-bucket reason, events."""
    h1 = ConfirmedH1Regime(_P.h1_fast_ema, _P.h1_slow_ema, _P.h1_atr_length,
                           _P.h1_slope_lookback)
    fast, slow = EMA(_P.ema_fast), EMA(_P.ema_slow)
    atr, dmi = ATR(_P.atr_length), DMI(_P.di_length, _P.adx_smoothing)
    history: list[Candle] = []
    previous_stack: int | None = None
    output: list[BarContext] = []

    for index, candle in enumerate(candles):
        regime = h1.update(candle)
        ema20 = fast.update(candle.close)
        ema50 = slow.update(candle.close)
        atr_value = atr.update(candle)
        adx = dmi.update(candle).adx

        prior3 = history[-3:]
        prior5 = history[-5:]
        high3 = max(b.high for b in prior3) if len(prior3) == 3 else None
        low3 = min(b.low for b in prior3) if len(prior3) == 3 else None
        high5 = max(b.high for b in prior5) if len(prior5) == 5 else None
        low5 = min(b.low for b in prior5) if len(prior5) == 5 else None
        stop_bars = history[-(STOP_LOOKBACK - 1):] if STOP_LOOKBACK > 1 else []
        stop_low = min(b.low for b in (*stop_bars, candle))
        stop_high = max(b.high for b in (*stop_bars, candle))
        history.append(candle)

        stack = 1 if ema20 > ema50 else (-1 if ema20 < ema50 else 0)
        crossed_up = previous_stack is not None and previous_stack <= 0 and stack > 0
        crossed_down = previous_stack is not None and previous_stack >= 0 and stack < 0
        previous_stack = stack

        bucket = frozen_bucket(regime, ema20, ema50, adx, atr_value)
        reason = (_transition_reason(regime.separation_atr, regime.slope, adx,
                                     regime, ema20, ema50)
                  if bucket == "TRANSITION" else None)
        lean = "NONE"
        if regime.fast_ema is not None and regime.slow_ema is not None:
            lean = ("BULLISH_LEAN" if regime.fast_ema > regime.slow_ema
                    else "BEARISH_LEAN" if regime.fast_ema < regime.slow_ema else "FLAT")

        events: list[str] = []
        if lean in ("BULLISH_LEAN", "BEARISH_LEAN") and atr_value:
            up_is_toward = lean == "BULLISH_LEAN"
            toward_cross = crossed_up if up_is_toward else crossed_down
            against_cross = crossed_down if up_is_toward else crossed_up
            if toward_cross:
                events.append("EMA_REALIGN_WITH_H1")
            if against_cross:
                events.append("EMA_CROSS_AGAINST_H1")

            broke_up_3 = high3 is not None and candle.close > high3
            broke_down_3 = low3 is not None and candle.close < low3
            broke_up_5 = high5 is not None and candle.close > high5
            broke_down_5 = low5 is not None and candle.close < low5
            if (broke_up_3 if up_is_toward else broke_down_3):
                events.append("STRUCTURE_BREAK_3_TOWARD_H1")
            if (broke_down_3 if up_is_toward else broke_up_3):
                events.append("STRUCTURE_BREAK_3_AGAINST_H1")
            if (broke_up_5 if up_is_toward else broke_down_5):
                events.append("STRUCTURE_BREAK_5_TOWARD_H1")
            if (broke_down_5 if up_is_toward else broke_up_5):
                events.append("STRUCTURE_BREAK_5_AGAINST_H1")

            width = candle.high - candle.low
            body = abs(candle.close - candle.open) / width if width > 0 else 0.0
            range_atr = width / atr_value
            if (body >= STRONG_BODY and MIN_RANGE_ATR <= range_atr <= MAX_RANGE_ATR):
                bullish_bar = candle.close > candle.open
                if bullish_bar == up_is_toward:
                    events.append("STRONG_CLOSE_TOWARD_H1")
                else:
                    events.append("STRONG_CLOSE_AGAINST_H1")

            #--- Symmetric touch: the bar's range contains the average. An
            #--- asymmetric "low <= ema20" only makes sense when the stack is
            #--- already aligned, and in these pools it mostly is not.
            if candle.low <= ema20 <= candle.high:
                events.append("EMA20_REJECTION")
            if candle.low <= ema50 <= candle.high:
                events.append("EMA50_REJECTION")

        output.append(BarContext(index, candle.timestamp, bucket, reason, lean,
                                 atr_value, ema20, ema50, stop_low, stop_high,
                                 tuple(events)))
    return output


# --- forward excursion ----------------------------------------------------------------


@dataclass
class Outcome:
    timestamp: pd.Timestamp
    reason: str
    event: str
    direction: str
    long: bool
    risk: float
    risk_atr: float
    mfe_r: float
    mae_r: float
    resolution: str
    bars_to_resolution: int | None
    first_touch: dict[str, str]


def _walk(highs, lows, start: int, entry: float, stop: float, long: bool) -> dict:
    """Resolve one trade against closed bars, never ordering two touches in one bar."""
    risk = abs(entry - stop)
    end = min(start + HORIZON_BARS, len(highs))
    window_high = highs[start:end]
    window_low = lows[start:end]
    if len(window_high) == 0:
        return {"resolution": "UNRESOLVED", "bars": None, "mfe_r": 0.0, "mae_r": 0.0,
                "first_touch": {name: "NOT_REACHED" for name in ("1R", "2R", "3R")}}

    if long:
        favourable = (window_high - entry) / risk
        adverse = (window_low - entry) / risk
    else:
        favourable = (entry - window_low) / risk
        adverse = (entry - window_high) / risk

    stop_hits = np.flatnonzero(adverse <= -1.0)
    stop_bar = int(stop_hits[0]) if stop_hits.size else None

    first_touch: dict[str, str] = {}
    resolution, resolution_bar = "UNRESOLVED", None
    for label, level in (("1R", 1.0), ("2R", 2.0), ("3R", REWARD_MULTIPLE)):
        hits = np.flatnonzero(favourable >= level)
        target_bar = int(hits[0]) if hits.size else None
        if target_bar is None and stop_bar is None:
            first_touch[label] = "NOT_REACHED"
        elif target_bar is None:
            first_touch[label] = "STOP_FIRST"
        elif stop_bar is None or target_bar < stop_bar:
            first_touch[label] = "TARGET_FIRST"
        elif target_bar > stop_bar:
            first_touch[label] = "STOP_FIRST"
        else:
            #--- One bar spanned both. OHLC cannot say which came first.
            first_touch[label] = "AMBIGUOUS_SAME_BAR"
        if label == "3R":
            resolution = {"TARGET_FIRST": "TARGET_3R", "STOP_FIRST": "STOP_1R",
                          "AMBIGUOUS_SAME_BAR": "AMBIGUOUS_SAME_BAR",
                          "NOT_REACHED": "UNRESOLVED"}[first_touch[label]]
            resolution_bar = (min(x for x in (target_bar, stop_bar) if x is not None)
                              if (target_bar is not None or stop_bar is not None) else None)

    #--- MFE/MAE over the realised path only, which is what the engine reports.
    cutoff = (resolution_bar + 1) if resolution_bar is not None else len(favourable)
    return {"resolution": resolution, "bars": resolution_bar,
            "mfe_r": float(np.max(favourable[:cutoff])),
            "mae_r": float(np.min(adverse[:cutoff])),
            "first_touch": first_touch}


def measure(candles: Sequence[Candle], bars: Sequence[BarContext],
            spreads: Sequence[float] | None = None) -> list[Outcome]:
    """Every event in the two target pools, traded both ways, resolved forward.

    ``spreads`` turns the measurement from gross to net. The dataset's OHLC is
    the **bid**, so a long buys at ask and sells at bid — one spread, paid by
    moving the entry up — while a short sells at bid and buys back at ask — one
    spread, paid by moving its stop and target down. Either way the trade pays
    exactly one crossing, taken at the entry bar's own quoted spread.

    This matters more than it looks. The median development spread is 0.125 ATR
    against a median stop of a little over 1 ATR, so the crossing is worth
    roughly a tenth of R — far larger than any gross edge in this phase.
    """
    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    opens = np.array([c.open for c in candles], dtype=float)
    cost = (np.asarray(spreads, dtype=float) if spreads is not None
            else np.zeros(len(candles)))
    outcomes: list[Outcome] = []
    rejected: Counter = Counter()

    for bar in bars:
        if bar.reason not in TARGET_BUCKET_REASONS or not bar.events or not bar.atr:
            continue
        entry_index = bar.index + 1
        if entry_index >= len(opens):
            continue
        spread = float(cost[entry_index])
        toward_long = bar.lean == "BULLISH_LEAN"
        for direction in DIRECTIONS:
            long = toward_long if direction == "TOWARD_H1" else not toward_long
            stop = (bar.stop_low - STOP_BUFFER_ATR * bar.atr if long
                    else bar.stop_high + STOP_BUFFER_ATR * bar.atr)
            #--- The costed side differs by direction; see the docstring.
            entry = float(opens[entry_index]) + (spread if long else 0.0)
            if not long:
                stop -= spread
            #--- A gap through the structural stop leaves no trade to measure.
            if (long and entry <= stop) or (not long and entry >= stop):
                rejected["entry_gapped_through_the_structural_stop"] += 1
                continue
            risk_atr = abs(entry - stop) / bar.atr
            if not MIN_STOP_ATR <= risk_atr <= MAX_STOP_ATR:
                rejected["stop_distance_outside_the_frozen_band"] += 1
                continue
            walk = _walk(highs, lows, entry_index, entry, stop, long)
            for event in bar.events:
                outcomes.append(Outcome(
                    timestamp=bar.timestamp, reason=bar.reason, event=event,
                    direction=direction, long=long, risk=abs(entry - stop),
                    risk_atr=risk_atr, mfe_r=walk["mfe_r"], mae_r=walk["mae_r"],
                    resolution=walk["resolution"], bars_to_resolution=walk["bars"],
                    first_touch=walk["first_touch"]))
    measure.rejected = dict(rejected)
    return outcomes


# --- summaries -------------------------------------------------------------------------


def _rates(rows: Sequence[Outcome], label: str) -> dict[str, Any]:
    counts = Counter(row.first_touch[label] for row in rows)
    total = len(rows)
    resolved = total - counts["AMBIGUOUS_SAME_BAR"] - counts["NOT_REACHED"]
    return {
        "target_first": counts["TARGET_FIRST"],
        "stop_first": counts["STOP_FIRST"],
        "ambiguous_same_bar": counts["AMBIGUOUS_SAME_BAR"],
        "not_reached": counts["NOT_REACHED"],
        "percent_target_first": round(100 * counts["TARGET_FIRST"] / total, 2) if total else None,
        "percent_stop_first": round(100 * counts["STOP_FIRST"] / total, 2) if total else None,
        "percent_ambiguous": round(100 * counts["AMBIGUOUS_SAME_BAR"] / total, 2) if total else None,
        #--- Ambiguity resolved both ways, so the reader sees the whole interval
        #--- rather than one convenient end of it.
        "percent_target_first_optimistic": round(
            100 * (counts["TARGET_FIRST"] + counts["AMBIGUOUS_SAME_BAR"]) / total, 2)
        if total else None,
        "resolved": resolved,
    }


def _expectancy(rows: Sequence[Outcome]) -> dict[str, Any]:
    """Fixed-3R expectancy per event, with ambiguity resolved three ways.

    A trade is +3R if the target came first, -1R if the stop did. An unresolved
    trade is marked to its final excursion, which is the only defensible thing to
    do with a path that never hit either level.
    """
    if not rows:
        return {"expectancy_r": None}

    def value(row: Outcome, ambiguous: float) -> float:
        if row.resolution == "TARGET_3R":
            return REWARD_MULTIPLE
        if row.resolution == "STOP_1R":
            return -1.0
        if row.resolution == "AMBIGUOUS_SAME_BAR":
            return ambiguous
        return max(-1.0, min(REWARD_MULTIPLE, row.mfe_r if row.mfe_r > 0 else row.mae_r))

    return {
        "expectancy_r_pessimistic": round(mean(value(row, -1.0) for row in rows), 4),
        "expectancy_r_midpoint": round(mean(value(row, 1.0) for row in rows), 4),
        "expectancy_r_optimistic": round(mean(value(row, REWARD_MULTIPLE) for row in rows), 4),
        "total_r_pessimistic": round(sum(value(row, -1.0) for row in rows), 2),
    }


def summarise_group(rows: Sequence[Outcome], span_months: float) -> dict[str, Any]:
    if not rows:
        return {"events": 0}
    return {
        "events": len(rows),
        "events_per_month": round(len(rows) / span_months, 2),
        "median_mfe_r": round(median(row.mfe_r for row in rows), 3),
        "median_mae_r": round(median(row.mae_r for row in rows), 3),
        "mean_mfe_r": round(mean(row.mfe_r for row in rows), 3),
        "mean_mae_r": round(mean(row.mae_r for row in rows), 3),
        "median_risk_atr": round(median(row.risk_atr for row in rows), 3),
        "reaching_1r": _rates(rows, "1R"),
        "reaching_2r": _rates(rows, "2R"),
        "reaching_3r": _rates(rows, "3R"),
        "resolution": dict(Counter(row.resolution for row in rows)),
        "median_bars_to_resolution": median(
            [row.bars_to_resolution for row in rows if row.bars_to_resolution is not None] or [0]),
        **_expectancy(rows),
    }


#--- A fixed 3R with a 1R stop pays 3 and costs 1, so it needs better than one
#--- win in four. Everything in Phase G is read against this number.
BREAK_EVEN_3R_RATE = 100.0 / (1.0 + REWARD_MULTIPLE)


def binomial_tail_p(successes: int, trials: int, probability: float) -> float:
    """Exact one-sided P(X >= successes) for X ~ Binomial(trials, probability).

    Written out rather than imported: scipy is not a dependency of this
    repository and a feasibility gate is a bad reason to add one. The sum runs
    in log space so the tail does not underflow at these sample sizes.

    This is the number that decides Phase G. A pool "beats" a fixed 3R only if
    its rate is distinguishable from the 25% a driftless path would produce, and
    across twenty cells some will sit above 25% by chance — so the tail
    probability, not the rate, is what has to be read.
    """
    if trials <= 0:
        return 1.0
    successes = max(0, min(successes, trials))
    log_coefficient = lgamma(trials + 1)
    log_p, log_q = log(probability), log1p(-probability)
    total = 0.0
    for k in range(successes, trials + 1):
        term = (log_coefficient - lgamma(k + 1) - lgamma(trials - k + 1)
                + k * log_p + (trials - k) * log_q)
        total += exp(term)
    return min(1.0, total)


def build(candles: Sequence[Candle], span_months: float) -> tuple[list[BarContext], list[Outcome]]:
    bars = contexts(candles)
    return bars, measure(candles, bars)
