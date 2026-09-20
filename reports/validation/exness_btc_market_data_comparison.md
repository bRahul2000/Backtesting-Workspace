# R2 — Exness BTCUSDm vs Bitstamp BTC/USD market-data comparison

Quantifies **feed divergence** on the exact overlapping timestamps. No attempt is made to
reconcile the two feeds: they are different venues with different pricing bases, so a
systematic offset is an expected finding, not a defect.

| | Source | SHA-256 |
|---|---|---|
| Exness M15 | `data/exness/btc/phase_r1/processed/btcusdm_M15.csv` | `80735a2c…` |
| Exness H1 | `data/exness/btc/phase_r1/processed/btcusdm_H1.csv` | `6d35fe9d…` |
| Bitstamp M15 | `data/btcusd_15m.csv` | `3ab2cc48…` |
| Bitstamp H1 | derived — complete four-bar aggregation of Bitstamp M15 (no native H1 series exists) | — |

**Timezone basis.** Both series are UTC. The Exness capture metadata records
`server_utc_offset_seconds_at_capture: 0`, so no shift is applied and timestamps are joined
exactly.

## Overlap and alignment

| | M15 | H1 |
|---|---|---|
| Overlap window (UTC) | 2023-11-10 23:15 → 2026-09-17 01:30 | 2023-11-07 00:00 → 2026-09-17 00:00 |
| Exness candles in window | 99,928 | 25,080 |
| Bitstamp candles in window | 99,915 | 25,068 |
| **Matched candles** | **99,897** | **25,067** |
| Matched % of Exness | 99.97% | 99.95% |
| Matched % of Bitstamp | 99.98% | 100.00% |
| Exness-only timestamps | 31 | 13 |
| Bitstamp-only timestamps | 18 | 1 |

Timestamp alignment is essentially total. The handful of unmatched bars are each venue's
own gaps, not an offset or grid mismatch.

## Correlation

| | M15 | H1 |
|---|---|---|
| Close level | 0.999999 | 0.999999 |
| Close **return** | **0.992812** | **0.997476** |
| High–low range | 0.987139 | 0.991159 |
| ATR(14) | 0.996484 | 0.997827 |

Level correlation is near-unity and uninformative at this price scale; the return
correlation is the meaningful figure, and it is high at both timeframes, rising from M15 to
H1 as microstructure noise averages out.

## Price-difference distribution (Exness − Bitstamp, absolute)

**M15**

| Field | median | mean | p90 | p95 | max | median % | median ÷ ATR |
|---|---|---|---|---|---|---|---|
| open | $14.72 | $24.29 | $59.30 | $76.84 | $1,028.62 | 0.0191% | 0.066 |
| high | $13.83 | $23.08 | $56.90 | $72.91 | $1,554.90 | 0.0181% | 0.061 |
| **low** | **$21.01** | $31.11 | $69.79 | $89.71 | $6,087.11 | 0.0268% | 0.096 |
| close | $15.50 | $24.50 | $58.85 | $76.48 | $1,445.30 | 0.0203% | 0.069 |

**H1**

| Field | median | mean | p90 | p95 | max | median % | median ÷ ATR |
|---|---|---|---|---|---|---|---|
| open | $14.72 | $24.42 | $59.52 | $76.66 | $941.46 | 0.0193% | 0.031 |
| high | $15.30 | $24.54 | $58.96 | $75.60 | $904.67 | 0.0201% | 0.032 |
| **low** | **$23.27** | $34.11 | $74.35 | $94.55 | $6,085.11 | 0.0298% | 0.050 |
| close | $15.32 | $24.56 | $58.83 | $76.06 | $2,146.29 | 0.0200% | 0.033 |

Typical divergence is **about 0.02% of price**, roughly **7% of one M15 ATR**. The **low is
consistently the most divergent field** at both timeframes — Exness prints deeper lows than
Bitstamp — which matters for stop placement and is picked up again in R3.

## Pricing basis: Bid versus last traded

Exness candles are broker **Bid** quotes; Bitstamp reports **last traded** price. A Bid feed
should sit below a last/mid feed by roughly half the quoted spread.

| | M15 | H1 |
|---|---|---|
| Median signed close difference (Exness − Bitstamp) | **−$6.54** | **−$6.48** |
| Share of bars where Exness is below Bitstamp | 63.8% | 63.7% |
| Median half-spread (real per-bar broker spread ÷ 2) | $10.80 | $10.80 |
| Median (difference + half-spread) | +$3.13 | +$3.04 |

The sign and magnitude are consistent with the Bid-versus-last hypothesis: Exness sits below
Bitstamp on about two thirds of bars, and adding back half the quoted spread moves the median
from −$6.54 to +$3.13 — i.e. **the pricing basis accounts for most of the systematic offset**,
slightly overshooting it. The residual few dollars is genuine venue difference.

## Range and volatility

| | M15 | H1 |
|---|---|---|
| Median range, Exness | $206.28 | $419.06 |
| Median range, Bitstamp | $180.00 | $388.00 |
| Median range ratio | **1.130** | **1.075** |
| Median ATR(14), Exness | $226.95 | $485.94 |
| Median ATR(14), Bitstamp | $200.93 | $455.07 |
| Median ATR ratio | **1.121** | **1.067** |

**Exness bars are systematically wider** — about 12% more ATR at M15, 7% at H1. The effect
shrinks with timeframe, which is what one expects if it is driven by wider intrabar wicks
(broker Bid feed, retail liquidity) rather than by a genuinely different price path.

## Discontinuities

| | Exness | Bitstamp | Matched |
|---|---|---|---|
| M15 candles | 99,928 | 99,915 | 99,897 |
| M15 continuous segments | 7 | 9 | 15 |
| M15 largest segment | 32,192 | 28,017 | 28,017 |
| H1 candles | 25,080 | 25,068 | 25,067 |
| H1 continuous segments | 2 | 9 | 10 |
| H1 largest segment | 17,032 | 7,004 | 7,004 |

The two venues have **different gaps**. The matched series is broken at the union of both
gap sets, so it fragments more than either source — 15 M15 segments against 7 and 9. This
matters for R3: any strategy holding indicator state resets at each break, and the Exness and
Bitstamp runs do not break in the same places.

## Weekend behaviour

Both venues trade through the weekend; Exness pauses only briefly. Weekend bars are 28.6% of
the matched M15 set, and divergence is **not** elevated on weekends (median absolute close
difference $15.55 weekend vs $15.48 weekday). No weekend adjustment is warranted.

## Notable divergence periods

Worst months by median absolute close difference (M15):

| Month | Candles | Median \|Δclose\| | p95 \|Δclose\| |
|---|---|---|---|
| 2025-05 | 2,976 | $47.78 | $124.37 |
| 2024-11 | 2,880 | $43.08 | $104.05 |
| 2024-03 | 2,974 | $40.38 | $114.38 |
| 2025-02 | 2,688 | $39.75 | $100.29 |
| 2024-02 | 2,781 | $39.18 | $90.02 |

H1 ranks the same five months in the same order. These are high-volatility periods, so the
absolute divergence rises while the *relative* divergence stays near 0.02%.

## Limitations

- Exness candles are broker **Bid** quotes; Bitstamp reports **last traded** price. A
  systematic offset is expected and is quantified above rather than removed.
- Bitstamp publishes **no native H1 series**; its H1 is aggregated from complete four-bar
  M15 groups. The Exness H1 is broker-native. This asymmetry is intrinsic to the comparison.
- Exness `tick_volume` is a tick count and `real_volume` is 0 throughout; Bitstamp volume is
  traded BTC. **Volume is not compared** — the two are not the same quantity.
- ATR here is a descriptive 14-bar true-range mean reset across gaps, not a strategy input.
- Maximum differences (up to $6,087 on the low) are single-bar outliers during fast moves,
  not representative; medians and percentiles carry the signal.

## Conclusion

The two feeds **agree on direction and structure** (return correlation 0.9928 M15 / 0.9975
H1) and **disagree on level by about 0.02%**, most of which is explained by the Bid-versus-last
pricing basis. Exness bars are systematically wider, especially at the low, and the two
venues gap in different places. None of this is a defect in either dataset; it is the
divergence a strategy must be portable across, and R3 measures exactly that.
