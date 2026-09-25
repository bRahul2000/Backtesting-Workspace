"""Decision thresholds and metric definitions, LOCKED before any data was compared.

Written 2026-09-25 before the first real-data run (see REPORT.md "Method"). They
are descriptive research labels only and must not be tuned after seeing results.

Event agreement (swings, breakouts, crosses, signal proxies)
------------------------------------------------------------
Events are computed on each provider's OWN candle series (indicators never mix
feeds) and then restricted to timestamps where both feeds have a candle.
Events are matched one-to-one: first identical timestamps, then (for the ±1 bar
tolerance) the remaining events at most one bar interval apart, nearest first.

    agreement = matched / (matched + binance_only + exness_only)

This is the Jaccard overlap of the two event sets: every event either feed
fires and the other misses counts against agreement.

Candle direction
----------------
Bull: close > open. Bear: close < open. Flat: close == open at the feed's own
price precision. Direction agreement = candles with the same class (bull/bull,
bear/bear, flat/flat) / matched candles.

Headline settings (fixed, not chosen from results)
--------------------------------------------------
* breakout: close-based, N = 20, up and down pooled, ±1 bar
* EMA20 cross: close crossing EMA(20), up and down pooled, ±1 bar
* swing: fractal window N = 3, highs and lows pooled, ±1 bar
"""

EXCELLENT, STRONG, MODERATE, WEAK = "excellent", "strong", "moderate", "weak"

#: label -> ordered (minimum %, label) bands; the first band whose minimum is met wins.
THRESHOLDS: dict[str, tuple[tuple[float, str], ...]] = {
    # A. Candle direction agreement
    "direction": ((98.0, EXCELLENT), (95.0, STRONG), (90.0, MODERATE), (0.0, WEAK)),
    # B. Breakout same/±1-bar agreement
    "breakout": ((97.0, EXCELLENT), (94.0, STRONG), (90.0, MODERATE), (0.0, WEAK)),
    # C. EMA-cross same/±1-bar agreement (also applied to the other signal proxies)
    "ema_cross": ((97.0, EXCELLENT), (94.0, STRONG), (90.0, MODERATE), (0.0, WEAK)),
    "signal_proxy": ((97.0, EXCELLENT), (94.0, STRONG), (90.0, MODERATE), (0.0, WEAK)),
    # D. Swing agreement
    "swing": ((95.0, STRONG), (90.0, MODERATE), (0.0, WEAK)),
}

HEADLINE = {"breakout_n": 20, "breakout_basis": "close", "swing_window": 3, "tolerance_bars": 1}

#: Fixed parameters (not optimized).
SWING_WINDOWS = (2, 3, 5)
BREAKOUT_NS = (5, 10, 20)
EMA_LENGTHS = (20, 50, 200)
ATR_LENGTH = 14
ATR_EXPANSION_MEDIAN_BARS = 50   # proxy G: ATR(14) > median ATR(14) of the previous 50 bars
OUTLIERS_PER_KIND = 10
#: Indicator/event comparisons use only candles where BOTH feeds already have this
#: many of their own earlier candles (EMA200/ATR warm-up), so a feed that starts
#: later is not penalised for an unconverged indicator. Binance is fetched this many
#: candles before the overlap when its history allows.
WARMUP_BARS = 400
#: Outliers of close/high/low difference are measured against the median
#: difference of the surrounding UTC day, so the slowly varying price offset
#: between the two instruments is not reported as disagreement.
OUTLIER_BASELINE = "centered one-day rolling median of the difference"


def label(kind: str, percent: float | None) -> str | None:
    if percent is None:
        return None
    for minimum, name in THRESHOLDS[kind]:
        if percent >= minimum:
            return name
    return THRESHOLDS[kind][-1][1]
