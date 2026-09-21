"""BTC Core V2 — Phase F: what TRANSITION actually is, and what happens inside it.

Phase D's opportunity map counted 28,879 TRANSITION bars — 50.31% of the
development split, only 7.66% of them inside a Core position — and Phase F was
briefed to go and find a setup family there. Before building anything this
module answers two prior questions.

**What is TRANSITION?** It is not a concept in any frozen source. The frozen H1
classifier (``strategies/confirmed_h1_regime.py``) emits no regime names at all;
it emits ``fast_ema``, ``slow_ema``, ``slope`` and ``separation_atr``. The only
place the word exists is ``research/core_v2_opportunity_map.py``, where it is
the **else branch**: a bar that is not warmup, not a cleanly aligned strong
trend, and not narrow enough to be range. So TRANSITION is a residual, and a
residual can be reached for several unrelated reasons. ``transition_reason``
below splits it into the four disjoint ways a bar can fall through, each one
read straight off the frozen gates it failed.

**Where is the opportunity?** ``EventDetector`` counts fixed structural events on
those bars. Every threshold it uses is lifted from a frozen or previously
validated source — T3's 5-bar structure, 8-bar sweep window, 0.70 body and
0.60-2.00 ATR range; PB2's 5-bar retest window and 0.10 ATR tolerance — so the
census measures pools the repository already knows how to trade, not pools
invented to look large.

Overlap with the frozen children is measured against a *shadow* A4 and T3 run
with a permanently flat execution state. That is deliberately not the Core's
real signal stream: it is the unconstrained setup population, so the overlap
number is not confounded by whichever child happened to hold the position slot.

DEVELOPMENT only. Nothing here reads past ``DEVELOPMENT_END``.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

import pandas as pd

from core.trade_log import to_timestamp
from engine.models import Candle, ExecutionState, Signal
from research.core_v2_opportunity_map import (
    COMPRESSION_RATIO, EXPANSION_RATIO, MIN_ADX, RANGE_SEPARATION,
    STRUCTURE_LOOKBACK, TREND_SEPARATION, VOLATILITY_REFERENCE_BARS,
)
from strategies.btc_v3_a4_pullback_long import BtcV3A4PullbackLongFrozen
from strategies.btc_v3_t3_breakout_short import BtcV3T3BreakoutShortFrozen
from strategies.confirmed_h1_regime import ConfirmedH1Regime
from strategies.pine_indicators import ATR, DMI, EMA, RSI

#--- Lifted from the frozen T3 source (trend_structure_lookback is STRUCTURE_LOOKBACK).
SWEEP_LOOKBACK = 8              # V3T3FrozenParameters.range_sweep_lookback
STRONG_BODY_PERCENT = 0.70      # V3T3FrozenParameters.trend_minimum_body_percent
MIN_RANGE_ATR = 0.60            # V3T3FrozenParameters.trend_minimum_range_atr
MAX_RANGE_ATR = 2.00            # V3T3FrozenParameters.trend_maximum_range_atr
#--- Lifted from the PB2 descriptor in strategies/universal_catalog.py.
RETEST_WINDOW_BARS = 5          # PB2 retest_maximum_bars
RETEST_TOLERANCE_ATR = 0.10     # PB2 retest_tolerance_atr
#--- Descriptive only: how recent an EMA cross still counts as "recent".
RECENT_CROSS_BARS = 5

TRANSITION_REASONS = (
    "EMERGING_SEPARATION",
    "WIDE_BUT_WEAK_ADX",
    "WIDE_BUT_H1_UNALIGNED",
    "WIDE_BUT_M15_OPPOSED",
)


@dataclass
class FBar:
    """One development bar, described with information available at its close."""
    timestamp: pd.Timestamp
    bucket: str
    transition_reason: str | None = None
    lean: str = "NONE"                 # which way the confirmed H1 EMAs point
    slope_sign: str = "NONE"
    separation_move: str = "NONE"      # EXPANDING / CONTRACTING, vs the prior H1 bar
    slope_turn: str = "NONE"           # TURNED_POSITIVE / TURNED_NEGATIVE
    m15_alignment: str = "NONE"        # ALIGNED / OPPOSED, M15 stack vs the H1 lean
    recent_ema_cross: bool = False
    volatility: str = "WARMUP"
    events: tuple[str, ...] = ()
    core_busy: bool = False
    a4_setup: bool = False
    t3_setup: bool = False


class EventDetector:
    """Fixed structural events, all causal: a bar is judged at its own close.

    The break/retest/reclaim chain is a state machine rather than a per-bar
    predicate, because "retest" only means something relative to a break that
    already happened. A pending break expires after ``RETEST_WINDOW_BARS`` so a
    level cannot be retested indefinitely and inflate the count.
    """

    def __init__(self) -> None:
        self.up_level: float | None = None
        self.up_age = 0
        self.up_retested = False
        self.down_level: float | None = None
        self.down_age = 0
        self.down_retested = False
        self.previous_broke_up: tuple[float, ...] = ()
        self.previous_broke_down: tuple[float, ...] = ()

    def update(self, candle: Candle, prior_high: float | None, prior_low: float | None,
               sweep_high: float | None, sweep_low: float | None,
               atr: float | None, ema20: float, ema50: float,
               crossed_up: bool, crossed_down: bool) -> tuple[str, ...]:
        events: list[str] = []
        body = _body_percent(candle)

        #--- A break that already happened: did this bar reject it?
        for level in self.previous_broke_up:
            if candle.close < level:
                events.append("FAILED_BREAKOUT_REVERSAL_DOWN")
                break
        for level in self.previous_broke_down:
            if candle.close > level:
                events.append("FAILED_BREAKDOWN_REVERSAL_UP")
                break

        broke_up = prior_high is not None and candle.close > prior_high
        broke_down = prior_low is not None and candle.close < prior_low
        if broke_up:
            events.append("BREAKOUT_UP")
        if broke_down:
            events.append("BREAKDOWN")

        #--- Retest and continuation, against a break still inside its window.
        if self.up_level is not None and atr:
            if (not self.up_retested
                    and candle.low <= self.up_level + RETEST_TOLERANCE_ATR * atr):
                self.up_retested = True
                events.append("RETEST_AFTER_BREAKOUT_UP")
            elif (self.up_retested and candle.close > candle.open
                  and candle.close > self.up_level):
                events.append("RECLAIM_CONTINUATION_UP")
                self.up_level = None
        if self.down_level is not None and atr:
            if (not self.down_retested
                    and candle.high >= self.down_level - RETEST_TOLERANCE_ATR * atr):
                self.down_retested = True
                events.append("RETEST_AFTER_BREAKDOWN")
            elif (self.down_retested and candle.close < candle.open
                  and candle.close < self.down_level):
                events.append("RECLAIM_CONTINUATION_DOWN")
                self.down_level = None

        #--- Liquidity sweep: trade through an 8-bar extreme and close back inside.
        if sweep_high is not None and candle.high > sweep_high and candle.close < sweep_high:
            events.append("SWEEP_REJECTION_UP")
        if sweep_low is not None and candle.low < sweep_low and candle.close > sweep_low:
            events.append("SWEEP_REJECTION_DOWN")

        if crossed_up:
            events.append("EMA20_CROSS_UP")
        if crossed_down:
            events.append("EMA20_CROSS_DOWN")

        if ema20 > ema50 and candle.low <= ema20:
            events.append("PULLBACK_TOUCH_EMA20_LONG")
        if ema20 < ema50 and candle.high >= ema20:
            events.append("PULLBACK_TOUCH_EMA20_SHORT")
        if ema20 > ema50 and candle.low <= ema50:
            events.append("PULLBACK_TOUCH_EMA50_LONG")
        if ema20 < ema50 and candle.high >= ema50:
            events.append("PULLBACK_TOUCH_EMA50_SHORT")

        if atr and atr > 0:
            range_atr = (candle.high - candle.low) / atr
            if (body >= STRONG_BODY_PERCENT and MIN_RANGE_ATR <= range_atr <= MAX_RANGE_ATR):
                events.append("STRONG_CANDLE_UP" if candle.close > candle.open
                              else "STRONG_CANDLE_DOWN")

        #--- Advance the break state machine for the next bar.
        self.previous_broke_up = ((prior_high,) if broke_up else ())
        self.previous_broke_down = ((prior_low,) if broke_down else ())
        if broke_up:
            self.up_level, self.up_age, self.up_retested = prior_high, 0, False
        elif self.up_level is not None:
            self.up_age += 1
            if self.up_age > RETEST_WINDOW_BARS:
                self.up_level = None
        if broke_down:
            self.down_level, self.down_age, self.down_retested = prior_low, 0, False
        elif self.down_level is not None:
            self.down_age += 1
            if self.down_age > RETEST_WINDOW_BARS:
                self.down_level = None
        return tuple(events)


def _body_percent(candle: Candle) -> float:
    width = candle.high - candle.low
    return abs(candle.close - candle.open) / width if width > 0 else 0.0


class _ShadowChild:
    """A frozen child driven with a permanently flat execution state.

    It never receives a position, a pending order or a window, so every bar it
    could ever signal on is a bar it does signal on. That is the unconstrained
    setup population, which is what an overlap measurement wants: the real Core
    stream is throttled by whichever child holds the slot.
    """

    def __init__(self, strategy) -> None:
        self.strategy = strategy
        self.strategy.reset()

    def fired(self, candle: Candle) -> bool:
        self.strategy.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
        return isinstance(self.strategy.on_candle(candle), Signal)


def census(candles: Sequence[Candle]) -> list[FBar]:
    """Classify every bar, sub-bucket the TRANSITION ones and detect events."""
    h1 = ConfirmedH1Regime(50, 200, 14, 4)
    fast, slow = EMA(20), EMA(50)
    atr, rsi, dmi = ATR(14), RSI(14), DMI(14, 14)
    detector = EventDetector()
    a4 = _ShadowChild(BtcV3A4PullbackLongFrozen())
    t3 = _ShadowChild(BtcV3T3BreakoutShortFrozen())

    history: list[Candle] = []
    atr_history: list[float] = []
    previous_hour = previous_separation = previous_slope = None
    previous_stack: int | None = None
    bars_since_cross = RECENT_CROSS_BARS + 1
    output: list[FBar] = []

    for candle in candles:
        regime = h1.update(candle)
        ema20 = fast.update(candle.close)
        ema50 = slow.update(candle.close)
        atr_value = atr.update(candle)
        rsi.update(candle.close)
        adx = dmi.update(candle).adx

        prior = history[-STRUCTURE_LOOKBACK:]
        prior_high = max(b.high for b in prior) if len(prior) == STRUCTURE_LOOKBACK else None
        prior_low = min(b.low for b in prior) if len(prior) == STRUCTURE_LOOKBACK else None
        sweep = history[-SWEEP_LOOKBACK:]
        sweep_high = max(b.high for b in sweep) if len(sweep) == SWEEP_LOOKBACK else None
        sweep_low = min(b.low for b in sweep) if len(sweep) == SWEEP_LOOKBACK else None
        history.append(candle)

        stack = 1 if ema20 > ema50 else (-1 if ema20 < ema50 else 0)
        crossed_up = previous_stack is not None and previous_stack <= 0 and stack > 0
        crossed_down = previous_stack is not None and previous_stack >= 0 and stack < 0
        bars_since_cross = 0 if (crossed_up or crossed_down) else bars_since_cross + 1
        previous_stack = stack

        separation, slope = regime.separation_atr, regime.slope
        bucket = _bucket(separation, slope, adx, atr_value, regime, ema20, ema50)
        bar = FBar(timestamp=candle.timestamp, bucket=bucket,
                   recent_ema_cross=bars_since_cross <= RECENT_CROSS_BARS)

        if bucket == "TRANSITION":
            bar.transition_reason = _transition_reason(separation, slope, adx, regime,
                                                       ema20, ema50)
        if separation is not None and slope is not None:
            bar.lean = ("BULLISH_LEAN" if regime.fast_ema > regime.slow_ema
                        else "BEARISH_LEAN" if regime.fast_ema < regime.slow_ema else "FLAT")
            bar.slope_sign = ("SLOPE_POSITIVE" if slope > 0
                              else "SLOPE_NEGATIVE" if slope < 0 else "SLOPE_FLAT")
            bar.m15_alignment = _alignment(bar.lean, stack)
            #--- Only compare against the previous *confirmed* H1 bar, so the
            #--- reading changes once an hour rather than every M15 bar.
            if regime.hour != previous_hour:
                if previous_separation is not None:
                    bar.separation_move = ("SEPARATION_EXPANDING"
                                           if separation > previous_separation
                                           else "SEPARATION_CONTRACTING"
                                           if separation < previous_separation else "NONE")
                if previous_slope is not None:
                    if previous_slope <= 0 < slope:
                        bar.slope_turn = "TURNED_POSITIVE"
                    elif previous_slope >= 0 > slope:
                        bar.slope_turn = "TURNED_NEGATIVE"
                previous_hour, previous_separation, previous_slope = (
                    regime.hour, separation, slope)
            else:
                bar.separation_move = output[-1].separation_move if output else "NONE"
                bar.slope_turn = output[-1].slope_turn if output else "NONE"

        if atr_value is not None:
            reference = atr_history[-VOLATILITY_REFERENCE_BARS:]
            if len(reference) >= VOLATILITY_REFERENCE_BARS // 4:
                median = sorted(reference)[len(reference) // 2]
                if median > 0:
                    ratio = atr_value / median
                    bar.volatility = ("LOW_VOL_COMPRESSION" if ratio <= COMPRESSION_RATIO
                                      else "HIGH_VOL_EXPANSION" if ratio >= EXPANSION_RATIO
                                      else "NORMAL_VOL")
            atr_history.append(atr_value)

        bar.events = detector.update(candle, prior_high, prior_low, sweep_high, sweep_low,
                                     atr_value, ema20, ema50, crossed_up, crossed_down)
        bar.a4_setup = a4.fired(candle)
        bar.t3_setup = t3.fired(candle)
        output.append(bar)
    return output


def _bucket(separation, slope, adx, atr_value, regime, ema20, ema50) -> str:
    """The Phase D opportunity map's own buckets, reproduced exactly."""
    if separation is None or slope is None or adx is None or atr_value is None:
        return "WARMUP"
    if (separation >= TREND_SEPARATION and adx >= MIN_ADX
            and regime.fast_ema > regime.slow_ema and slope > 0 and ema20 > ema50):
        return "BULLISH_TREND"
    if (separation >= TREND_SEPARATION and adx >= MIN_ADX
            and regime.fast_ema < regime.slow_ema and slope < 0 and ema20 < ema50):
        return "BEARISH_TREND"
    if separation <= RANGE_SEPARATION:
        return "NEUTRAL_RANGE"
    return "TRANSITION"


def _transition_reason(separation, slope, adx, regime, ema20, ema50) -> str:
    """Which frozen gate this bar failed, in the order the classifier tests them.

    The four reasons are disjoint and exhaustive over TRANSITION by construction:
    a TRANSITION bar has separation > 0.80 and failed both trend branches, and
    the only ways to fail a trend branch are a narrow-but-not-range separation,
    a weak ADX, an internally disagreeing H1, or an M15 stack facing the wrong
    way.
    """
    if separation < TREND_SEPARATION:
        return "EMERGING_SEPARATION"
    if adx < MIN_ADX:
        return "WIDE_BUT_WEAK_ADX"
    h1_up = regime.fast_ema > regime.slow_ema and slope > 0
    h1_down = regime.fast_ema < regime.slow_ema and slope < 0
    if not (h1_up or h1_down):
        return "WIDE_BUT_H1_UNALIGNED"
    return "WIDE_BUT_M15_OPPOSED"


def _alignment(lean: str, stack: int) -> str:
    if lean == "BULLISH_LEAN":
        return "ALIGNED" if stack > 0 else "OPPOSED" if stack < 0 else "NONE"
    if lean == "BEARISH_LEAN":
        return "ALIGNED" if stack < 0 else "OPPOSED" if stack > 0 else "NONE"
    return "NONE"


def mark_coverage(bars: Sequence[FBar], trade_log: Iterable[dict]) -> None:
    """Flag every bar inside an open Core position, entry bar through exit bar."""
    intervals = sorted((to_timestamp(row["entry_time"]), to_timestamp(row["exit_time"]))
                       for row in trade_log)
    index = 0
    for bar in bars:
        while index < len(intervals) and intervals[index][1] < bar.timestamp:
            index += 1
        bar.core_busy = any(start <= bar.timestamp <= end
                            for start, end in intervals[index:index + 4])


def summarise(bars: Sequence[FBar], months: float) -> dict[str, Any]:
    total = len(bars)
    transition = [bar for bar in bars if bar.bucket == "TRANSITION"]
    buckets: Counter = Counter(bar.bucket for bar in bars)
    covered: Counter = Counter(bar.bucket for bar in bars if bar.core_busy)

    def share(counter: Counter, denominator: int) -> dict[str, Any]:
        return {name: {"bars": count,
                       "percent": round(100 * count / denominator, 3) if denominator else None}
                for name, count in counter.most_common()}

    events: dict[str, Any] = {}
    for bar in transition:
        for name in bar.events:
            bucket = events.setdefault(name, {
                "events": 0, "bullish_lean": 0, "bearish_lean": 0,
                "while_core_busy": 0, "while_core_flat": 0,
                "coincides_with_an_a4_setup": 0, "coincides_with_a_t3_setup": 0})
            bucket["events"] += 1
            bucket["bullish_lean"] += bar.lean == "BULLISH_LEAN"
            bucket["bearish_lean"] += bar.lean == "BEARISH_LEAN"
            bucket["while_core_busy"] += bar.core_busy
            bucket["while_core_flat"] += not bar.core_busy
            bucket["coincides_with_an_a4_setup"] += bar.a4_setup
            bucket["coincides_with_a_t3_setup"] += bar.t3_setup
    for payload in events.values():
        payload["events_per_month"] = round(payload["events"] / months, 2)
        payload["percent_while_core_flat"] = round(
            100 * payload["while_core_flat"] / payload["events"], 2)

    return {
        "bars": total,
        "development_months": round(months, 3),
        "buckets": share(buckets, total),
        "bars_inside_a_core_position": {name: {
            "bars": covered[name],
            "percent_of_bucket": round(100 * covered[name] / buckets[name], 3)}
            for name in buckets},
        "transition": {
            "bars": len(transition),
            "percent_of_development": round(100 * len(transition) / total, 3),
            "reason": share(Counter(bar.transition_reason for bar in transition),
                            len(transition)),
            "lean": share(Counter(bar.lean for bar in transition), len(transition)),
            "slope_sign": share(Counter(bar.slope_sign for bar in transition), len(transition)),
            "separation_move": share(Counter(bar.separation_move for bar in transition),
                                     len(transition)),
            "slope_turn": share(Counter(bar.slope_turn for bar in transition), len(transition)),
            "m15_alignment": share(Counter(bar.m15_alignment for bar in transition),
                                   len(transition)),
            "recent_ema_cross": share(
                Counter("RECENT_EMA_CROSS" if bar.recent_ema_cross else "NO_RECENT_CROSS"
                        for bar in transition), len(transition)),
            "volatility": share(Counter(bar.volatility for bar in transition), len(transition)),
            "bars_while_core_flat": sum(1 for bar in transition if not bar.core_busy),
        },
        "events_on_transition_bars": dict(
            sorted(events.items(), key=lambda item: -item[1]["events"])),
        #--- The headline overlap claim, measured rather than asserted.
        "frozen_child_setups_on_transition_bars": {
            "a4": sum(1 for bar in transition if bar.a4_setup),
            "t3": sum(1 for bar in transition if bar.t3_setup),
            "a4_total_shadow_setups": sum(1 for bar in bars if bar.a4_setup),
            "t3_total_shadow_setups": sum(1 for bar in bars if bar.t3_setup),
        },
    }


def build(candles: Sequence[Candle], trade_log: Iterable[dict], months: float) -> dict[str, Any]:
    bars = census(candles)
    mark_coverage(bars, trade_log)
    return summarise(bars, months)
