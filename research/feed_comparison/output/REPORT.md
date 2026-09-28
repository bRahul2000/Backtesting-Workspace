# Binance Futures vs Exness MT5 — feed comparison

Generated 2026-09-25T08:58:34.345915+00:00 (runtime 76.1 s). Research output only.

## Method (fixed before the run)

- Candles are compared only where both feeds have the identical UTC timestamp; nothing is filled or interpolated.
- Indicators and events are computed on each feed's own candles (strategy Pine EMA/ATR; chart VWAP with daily UTC reset).
- Indicator/event comparisons skip the first 400 candles of each feed (warm-up).
- Event agreement = matched / (matched + Binance-only + Exness-only), one-to-one matching, same bar or ±1 bar.
- Headline settings: {'breakout_n': 20, 'breakout_basis': 'close', 'swing_window': 3, 'tolerance_bars': 1}.
- Labels (descriptive only): direction: ≥98% excellent, ≥95% strong, ≥90% moderate, below: weak; breakout: ≥97% excellent, ≥94% strong, ≥90% moderate, below: weak; ema_cross: ≥97% excellent, ≥94% strong, ≥90% moderate, below: weak; signal_proxy: ≥97% excellent, ≥94% strong, ≥90% moderate, below: weak; swing: ≥95% strong, ≥90% moderate, below: weak

## Suitability matrix

| pair / tf | matched | direction | breakout20 same / ±1 | EMA20 cross same / ±1 | swing(3) same / ±1 | VWAP state | median close diff (B−E) | 1-bar return corr |
|---|---|---|---|---|---|---|---|---|
| **Gold 15m** | 17,480 | 95.44% (strong) | 74.53% / 84.25% (weak) | 70.51% / 80.75% (weak) | 76.81% / 85.21% (weak) | 96.86% | 2.59 (0.058%) | 0.9910 |
| **Gold 30m** | 8,739 | 95.94% (strong) | 73.32% / 83.15% (weak) | 69.78% / 79.17% (weak) | 79.49% / 85.63% (weak) | 96.83% | 2.59 (0.058%) | 0.9925 |
| **Gold 1h** | 4,372 | 96.48% (strong) | 70.97% / 76.13% (weak) | 65.38% / 74.23% (weak) | 79.73% / 85.65% (weak) | 97.33% | 2.58 (0.058%) | 0.9941 |
| **BTC 15m** | 100,239 | 97.39% (strong) | 85.63% / 91.01% (moderate) | 83.05% / 90.56% (moderate) | 84.28% / 90.71% (moderate) | 96.39% | -7.14 (-0.009%) | 0.9968 |
| **BTC 30m** | 83,831 | 96.91% (strong) | 84.80% / 89.74% (weak) | 81.48% / 89.43% (weak) | 83.52% / 91.00% (moderate) | 96.05% | -4.55 (-0.011%) | 0.9968 |
| **BTC 1h** | 25,158 | 98.18% (excellent) | 91.24% / 94.58% (strong) | 88.40% / 93.28% (moderate) | 91.06% / 94.98% (moderate) | 96.81% | -6.63 (-0.009%) | 0.9981 |

**Diagnostic: session-aligned view** — Binance indicators/events computed only on candles where Exness also trades (weekend/break candles removed). Not the headline: an algo on Binance would see those candles.

| pair / tf | breakout20 same / ±1 | EMA20 cross same / ±1 | swing(3) same / ±1 | VWAP state |
|---|---|---|---|---|
| Gold 15m | 79.26% / 88.27% (weak) | 77.76% / 87.15% (weak) | 79.13% / 87.97% (weak) | 97.11% |
| Gold 30m | 84.32% / 91.27% (moderate) | 81.83% / 88.49% (weak) | 83.08% / 89.72% (weak) | 97.15% |
| Gold 1h | 86.60% / 91.87% (moderate) | 88.32% / 91.71% (moderate) | 85.64% / 92.43% (moderate) | 97.53% |
| BTC 15m | 85.66% / 91.04% (moderate) | 83.12% / 90.60% (moderate) | 84.28% / 90.72% (moderate) | 96.39% |
| BTC 30m | 84.82% / 89.76% (weak) | 81.54% / 89.46% (weak) | 83.53% / 91.01% (moderate) | 96.06% |
| BTC 1h | 91.24% / 94.58% (strong) | 88.40% / 93.28% (moderate) | 91.06% / 94.98% (moderate) | 96.81% |

## Gold (XAUUSDT Perp vs XAUUSDm) — 15m

- Overlap 2025-12-23T00:00:00+00:00 → 2026-09-18T20:30:00+00:00; Binance 25,907 candles, Exness 17,480, matched 17,480 (unmatched Binance 8,427, unmatched Exness 0); coverage 67.47% of Binance, 100.00% of Exness. 17,080 candles after warm-up.
- Exness source: EXNESS_XAUUSDM_M15 (Native); Binance: XAUUSDT Perpetual (Binance Futures), 26,307 candles 2025-12-18T20:00:00+00:00 → 2026-09-18T20:30:00+00:00.

**Price offset (Binance − Exness)**

| field | mean | median | std | p5 | p95 | p99 | min | max | median % | p95 % |
|---|---|---|---|---|---|---|---|---|---|---|
| open | 2.45 | 2.58 | 3.28 | -2.36 | 6.64 | 10.51 | -45.42 | 72.98 | 0.0578% | 0.1538% |
| high | 2.26 | 2.38 | 3.07 | -2.59 | 6.41 | 10.43 | -21.20 | 57.17 | 0.0535% | 0.1489% |
| low | 2.68 | 2.81 | 3.28 | -2.16 | 6.89 | 10.50 | -64.29 | 76.89 | 0.0635% | 0.1595% |
| close | 2.45 | 2.59 | 3.06 | -2.31 | 6.59 | 9.76 | -22.10 | 73.08 | 0.0581% | 0.1524% |

**Time alignment**: 1-bar return correlation peaks at lag 0 bars (-3: -0.029, -2: 0.002, -1: 0.003, 0: 0.991, 1: 0.000, 2: 0.003, 3: -0.035).

**Returns**: 1_bar: Pearson 0.9910, Spearman 0.9859, same sign 95.73% (n=17,289); 3_bar: Pearson 0.9939, Spearman 0.9919, same sign 96.79% (n=16,907); 5_bar: Pearson 0.9948, Spearman 0.9932, same sign 97.10% (n=16,670)

**Direction**: same 95.44%, opposite 4.44%, flat disagreement 0.12%, same excluding flats 95.56%. Bull/Bull 8,442, Bull/Bear 373, Bear/Bull 403, Bear/Bear 8,241.

**Shape** (% of range, |B−E|): body median 4.45 p95 21.36; upper wick median 3.15 p95 16.39; lower wick median 3.19 p95 16.02; range ratio B/E median 0.947 (p5 0.799, p95 1.122), range correlation 0.9847.

**Levels** (|B−E|)

|  | abs median | abs p95 | % median | % p95 | ATR median | ATR p95 |
|---|---|---|---|---|---|---|
| high | 2.58 | 6.56 | 0.0573 | 0.1512 | 0.257 | 0.790 |
| low | 2.94 | 7.08 | 0.0660 | 0.1640 | 0.297 | 0.854 |
| range | 0.61 | 2.38 | 0.0137 | 0.0509 | 0.061 | 0.210 |
| high_excursion | 0.39 | 1.91 | 0.0086 | 0.0407 | 0.038 | 0.174 |
| low_excursion | 0.40 | 2.00 | 0.0089 | 0.0424 | 0.040 | 0.176 |

**ATR(14)**: correlation 0.9854, median diff -6.39%, median |diff| 6.43%, p95 |diff| 20.12%.

**EMA**

|  | level diff median (ATR) | |close−EMA| diff median / p95 (ATR) | slope agreement | close side agreement |
|---|---|---|---|---|
| ema20 | 0.262 | 0.049 / 0.318 | 97.20% | 97.28% |
| ema50 | 0.267 | 0.083 / 0.718 | 96.94% | 96.93% |
| ema200 | 0.321 | 0.317 / 3.714 | 94.16% | 94.19% |

**VWAP** — Binance: traded base-asset volume on the perpetual. Exness: MT5 tick volume (price-change count), not traded quantity. The two VWAPs weight prices differently and are NOT the same quantity; only the price-vs-VWAP state is compared. Price-vs-VWAP state agreement 96.86%; distance-from-VWAP difference median 0.156 ATR, p95 0.714 ATR.

**Events**

| event | Binance | Exness | same bar | ±1 bar | Binance-only | Exness-only |
|---|---|---|---|---|---|---|
| breakout close_5 | 2740 | 2662 | 76.54% | 86.34% | 237 | 159 |
| breakout close_10 | 1894 | 1831 | 77.21% | 85.32% | 179 | 116 |
| breakout close_20 | 1277 | 1238 | 74.53% | 84.25% | 127 | 88 |
| breakout wick_5 | 3922 | 3889 | 73.96% | 85.62% | 319 | 286 |
| breakout wick_10 | 2755 | 2710 | 72.18% | 84.19% | 257 | 212 |
| breakout wick_20 | 1896 | 1863 | 70.63% | 83.10% | 190 | 157 |
| swing 2 | 4661 | 4613 | 78.24% | 86.79% | 352 | 304 |
| swing 3 | 3328 | 3258 | 76.81% | 85.21% | 298 | 228 |
| swing 5 | 2152 | 2095 | 75.28% | 83.30% | 222 | 165 |
| A_close_cross_above_ema20 | 1162 | 1151 | 70.95% | 81.27% | 125 | 114 |
| B_close_cross_below_ema20 | 1174 | 1151 | 70.08% | 80.23% | 139 | 116 |
| C_close_moves_above_vwap | 881 | 884 | 59.73% | 74.75% | 126 | 129 |
| D_close_moves_below_vwap | 878 | 884 | 63.15% | 75.15% | 122 | 128 |
| E_20bar_breakout_up | 675 | 663 | 72.42% | 83.79% | 65 | 53 |
| F_20bar_breakout_down | 602 | 575 | 76.99% | 84.77% | 62 | 35 |
| G_atr_expansion | 474 | 504 | 26.36% | 41.33% | 188 | 218 |

**UTC hours with the most breakout disagreement**: 22:00 33.82% of 68 (direction 88.11%); 00:00 25.00% of 100 (direction 94.76%); 23:00 25.00% of 104 (direction 93.03%); 20:00 20.00% of 40 (direction 92.11%); 01:00 18.75% of 112 (direction 96.07%)

**Weekday**

| day | matched | direction | median |close diff| | breakout disagreement |
|---|---|---|---|---|
| Monday | 3456 | 95.25% | 2.69 | 11.24% of 249 |
| Tuesday | 3588 | 95.46% | 2.74 | 15.11% of 311 |
| Wednesday | 3565 | 95.54% | 2.68 | 16.51% of 315 |
| Thursday | 3404 | 96.12% | 2.71 | 10.33% of 242 |
| Friday | 3203 | 95.04% | 2.83 | 13.91% of 266 |
| Sunday | 264 | 92.42% | 3.42 | 43.86% of 57 |

- reopen candles (first/last hour around 40 market pauses ≥ 12 h): direction 89.38% vs 95.50% otherwise; median |close diff| 3.42 vs 2.73; breakout disagreement 53.85% vs 13.78%.
- pre pause candles (first/last hour around 40 market pauses ≥ 12 h): direction 85.62% vs 95.53% otherwise; median |close diff| 3.62 vs 2.73; breakout disagreement 27.27% vs 14.77%.

## Gold (XAUUSDT Perp vs XAUUSDm) — 30m

- Overlap 2025-12-23T00:00:00+00:00 → 2026-09-18T20:00:00+00:00; Binance 12,953 candles, Exness 8,739, matched 8,739 (unmatched Binance 4,214, unmatched Exness 0); coverage 67.47% of Binance, 100.00% of Exness. 8,339 candles after warm-up.
- Exness source: EXNESS_XAUUSDM_M15 (Derived from 15m); Binance: XAUUSDT Perpetual (Binance Futures), 13,353 candles 2025-12-14T16:00:00+00:00 → 2026-09-18T20:00:00+00:00.

**Price offset (Binance − Exness)**

| field | mean | median | std | p5 | p95 | p99 | min | max | median % | p95 % |
|---|---|---|---|---|---|---|---|---|---|---|
| open | 2.44 | 2.58 | 3.49 | -2.45 | 6.69 | 11.22 | -45.42 | 72.98 | 0.0578% | 0.1553% |
| high | 2.24 | 2.35 | 3.06 | -2.62 | 6.46 | 10.25 | -20.50 | 55.32 | 0.0527% | 0.1499% |
| low | 2.73 | 2.86 | 3.40 | -2.13 | 6.96 | 10.99 | -43.88 | 76.89 | 0.0645% | 0.1606% |
| close | 2.45 | 2.59 | 3.06 | -2.30 | 6.58 | 9.72 | -22.10 | 73.08 | 0.0583% | 0.1524% |

**Time alignment**: 1-bar return correlation peaks at lag 0 bars (-3: 0.001, -2: -0.026, -1: 0.008, 0: 0.993, 1: 0.002, 2: -0.033, 3: -0.005).

**Returns**: 1_bar: Pearson 0.9925, Spearman 0.9903, same sign 96.34% (n=8,548); 3_bar: Pearson 0.9949, Spearman 0.9936, same sign 97.22% (n=8,311); 5_bar: Pearson 0.9965, Spearman 0.9951, same sign 97.43% (n=8,221)

**Direction**: same 95.94%, opposite 3.96%, flat disagreement 0.10%, same excluding flats 96.04%. Bull/Bull 4,188, Bull/Bear 176, Bear/Bull 170, Bear/Bear 4,196.

**Shape** (% of range, |B−E|): body median 3.48 p95 18.64; upper wick median 2.50 p95 13.62; lower wick median 2.51 p95 13.71; range ratio B/E median 0.957 (p5 0.839, p95 1.115), range correlation 0.9890.

**Levels** (|B−E|)

|  | abs median | abs p95 | % median | % p95 | ATR median | ATR p95 |
|---|---|---|---|---|---|---|
| high | 2.57 | 6.64 | 0.0571 | 0.1528 | 0.178 | 0.541 |
| low | 2.98 | 7.16 | 0.0669 | 0.1657 | 0.210 | 0.581 |
| range | 0.71 | 3.02 | 0.0159 | 0.0633 | 0.050 | 0.178 |
| high_excursion | 0.44 | 2.55 | 0.0097 | 0.0542 | 0.030 | 0.154 |
| low_excursion | 0.47 | 2.56 | 0.0104 | 0.0534 | 0.032 | 0.153 |

**ATR(14)**: correlation 0.9654, median diff -6.72%, median |diff| 6.73%, p95 |diff| 29.84%.

**EMA**

|  | level diff median (ATR) | |close−EMA| diff median / p95 (ATR) | slope agreement | close side agreement |
|---|---|---|---|---|
| ema20 | 0.190 | 0.048 / 0.357 | 97.15% | 97.11% |
| ema50 | 0.200 | 0.106 / 1.168 | 95.33% | 95.29% |
| ema200 | 0.280 | 0.551 / 3.463 | 93.16% | 93.22% |

**VWAP** — Binance: traded base-asset volume on the perpetual. Exness: MT5 tick volume (price-change count), not traded quantity. The two VWAPs weight prices differently and are NOT the same quantity; only the price-vs-VWAP state is compared. Price-vs-VWAP state agreement 96.83%; distance-from-VWAP difference median 0.101 ATR, p95 0.492 ATR.

**Events**

| event | Binance | Exness | same bar | ±1 bar | Binance-only | Exness-only |
|---|---|---|---|---|---|---|
| breakout close_5 | 1314 | 1287 | 79.26% | 87.39% | 101 | 74 |
| breakout close_10 | 900 | 877 | 76.99% | 86.27% | 77 | 54 |
| breakout close_20 | 602 | 561 | 73.32% | 83.15% | 74 | 33 |
| breakout wick_5 | 1899 | 1869 | 75.17% | 84.71% | 171 | 141 |
| breakout wick_10 | 1337 | 1305 | 73.59% | 85.40% | 120 | 88 |
| breakout wick_20 | 915 | 863 | 70.96% | 81.24% | 118 | 66 |
| swing 2 | 2334 | 2249 | 80.79% | 86.83% | 204 | 119 |
| swing 3 | 1654 | 1602 | 79.49% | 85.63% | 152 | 100 |
| swing 5 | 1075 | 1027 | 78.14% | 83.90% | 116 | 68 |
| A_close_cross_above_ema20 | 572 | 526 | 72.10% | 79.12% | 87 | 41 |
| B_close_cross_below_ema20 | 578 | 526 | 67.53% | 79.22% | 90 | 38 |
| C_close_moves_above_vwap | 609 | 598 | 69.05% | 80.42% | 71 | 60 |
| D_close_moves_below_vwap | 605 | 598 | 67.55% | 79.55% | 72 | 65 |
| E_20bar_breakout_up | 315 | 311 | 74.37% | 84.66% | 28 | 24 |
| F_20bar_breakout_down | 287 | 250 | 72.12% | 81.42% | 46 | 9 |
| G_atr_expansion | 268 | 296 | 33.97% | 48.03% | 85 | 113 |

**UTC hours with the most breakout disagreement**: 22:00 56.67% of 30 (direction 87.36%); 23:00 38.46% of 39 (direction 93.42%); 03:00 35.00% of 20 (direction 96.34%); 21:00 28.57% of 7 (direction 89.80%); 00:00 27.03% of 37 (direction 95.81%)

**Weekday**

| day | matched | direction | median |close diff| | breakout disagreement |
|---|---|---|---|---|
| Monday | 1728 | 95.83% | 2.68 | 20.00% of 95 |
| Tuesday | 1794 | 95.76% | 2.71 | 14.29% of 140 |
| Wednesday | 1782 | 96.07% | 2.69 | 7.48% of 147 |
| Thursday | 1702 | 96.47% | 2.69 | 13.16% of 114 |
| Friday | 1601 | 95.88% | 2.83 | 11.68% of 137 |
| Sunday | 132 | 91.67% | 3.40 | 68.42% of 38 |

- reopen candles (first/last hour around 40 market pauses ≥ 12 h): direction 86.25% vs 96.03% otherwise; median |close diff| 3.35 vs 2.72; breakout disagreement 70.83% vs 13.91%.
- pre pause candles (first/last hour around 40 market pauses ≥ 12 h): direction 91.25% vs 95.98% otherwise; median |close diff| 3.51 vs 2.72; breakout disagreement 25.00% vs 15.89%.

## Gold (XAUUSDT Perp vs XAUUSDm) — 1h

- Overlap 2025-12-23T00:00:00+00:00 → 2026-09-18T19:00:00+00:00; Binance 6,476 candles, Exness 4,372, matched 4,372 (unmatched Binance 2,104, unmatched Exness 0); coverage 67.51% of Binance, 100.00% of Exness. 3,972 candles after warm-up.
- Exness source: EXNESS_XAUUSDM_H1 (Native); Binance: XAUUSDT Perpetual (Binance Futures), 6,756 candles 2025-12-11T08:00:00+00:00 → 2026-09-18T19:00:00+00:00 (start of Binance history reached).

**Price offset (Binance − Exness)**

| field | mean | median | std | p5 | p95 | p99 | min | max | median % | p95 % |
|---|---|---|---|---|---|---|---|---|---|---|
| open | 2.43 | 2.56 | 3.84 | -2.52 | 6.86 | 12.00 | -45.42 | 55.78 | 0.0575% | 0.1590% |
| high | 2.20 | 2.31 | 3.21 | -2.71 | 6.48 | 10.36 | -19.88 | 55.32 | 0.0521% | 0.1510% |
| low | 2.77 | 2.91 | 3.58 | -2.26 | 7.08 | 11.03 | -43.88 | 63.56 | 0.0657% | 0.1631% |
| close | 2.44 | 2.58 | 3.00 | -2.29 | 6.63 | 9.76 | -22.10 | 54.23 | 0.0578% | 0.1520% |

**Time alignment**: 1-bar return correlation peaks at lag 0 bars (-3: 0.034, -2: -0.031, -1: -0.005, 0: 0.994, 1: -0.017, 2: -0.035, 3: 0.037).

**Returns**: 1_bar: Pearson 0.9941, Spearman 0.9913, same sign 96.99% (n=4,181); 3_bar: Pearson 0.9972, Spearman 0.9957, same sign 98.07% (n=4,091); 5_bar: Pearson 0.9982, Spearman 0.9969, same sign 98.13% (n=4,009)

**Direction**: same 96.48%, opposite 3.43%, flat disagreement 0.09%, same excluding flats 96.57%. Bull/Bull 2,091, Bull/Bear 72, Bear/Bull 78, Bear/Bear 2,127.

**Shape** (% of range, |B−E|): body median 2.75 p95 17.89; upper wick median 1.96 p95 12.40; lower wick median 2.10 p95 12.74; range ratio B/E median 0.966 (p5 0.862, p95 1.105), range correlation 0.9903.

**Levels** (|B−E|)

|  | abs median | abs p95 | % median | % p95 | ATR median | ATR p95 |
|---|---|---|---|---|---|---|
| high | 2.55 | 6.68 | 0.0567 | 0.1549 | 0.122 | 0.372 |
| low | 3.04 | 7.28 | 0.0682 | 0.1687 | 0.150 | 0.395 |
| range | 0.86 | 4.00 | 0.0191 | 0.0843 | 0.040 | 0.162 |
| high_excursion | 0.53 | 3.69 | 0.0117 | 0.0779 | 0.024 | 0.156 |
| low_excursion | 0.57 | 3.62 | 0.0127 | 0.0779 | 0.027 | 0.154 |

**ATR(14)**: correlation 0.9330, median diff -7.32%, median |diff| 7.33%, p95 |diff| 45.62%.

**EMA**

|  | level diff median (ATR) | |close−EMA| diff median / p95 (ATR) | slope agreement | close side agreement |
|---|---|---|---|---|
| ema20 | 0.138 | 0.055 / 0.577 | 96.42% | 96.30% |
| ema50 | 0.155 | 0.144 / 1.745 | 93.86% | 93.93% |
| ema200 | 0.157 | 0.682 / 2.630 | 94.86% | 94.81% |

**VWAP** — Binance: traded base-asset volume on the perpetual. Exness: MT5 tick volume (price-change count), not traded quantity. The two VWAPs weight prices differently and are NOT the same quantity; only the price-vs-VWAP state is compared. Price-vs-VWAP state agreement 97.33%; distance-from-VWAP difference median 0.063 ATR, p95 0.351 ATR.

**Events**

| event | Binance | Exness | same bar | ±1 bar | Binance-only | Exness-only |
|---|---|---|---|---|---|---|
| breakout close_5 | 634 | 604 | 80.20% | 87.01% | 58 | 28 |
| breakout close_10 | 431 | 403 | 75.58% | 82.89% | 53 | 25 |
| breakout close_20 | 312 | 271 | 70.97% | 76.13% | 60 | 19 |
| breakout wick_5 | 924 | 895 | 74.57% | 86.95% | 78 | 49 |
| breakout wick_10 | 654 | 612 | 72.01% | 83.48% | 78 | 36 |
| breakout wick_20 | 462 | 415 | 68.98% | 79.35% | 74 | 27 |
| swing 2 | 1118 | 1089 | 82.55% | 88.96% | 79 | 50 |
| swing 3 | 816 | 762 | 79.73% | 85.65% | 88 | 34 |
| swing 5 | 527 | 500 | 79.86% | 86.39% | 51 | 24 |
| A_close_cross_above_ema20 | 275 | 266 | 65.95% | 75.65% | 42 | 33 |
| B_close_cross_below_ema20 | 268 | 266 | 64.81% | 72.82% | 43 | 41 |
| C_close_moves_above_vwap | 392 | 382 | 78.75% | 85.17% | 36 | 26 |
| D_close_moves_below_vwap | 388 | 381 | 77.19% | 83.53% | 38 | 31 |
| E_20bar_breakout_up | 161 | 144 | 73.30% | 78.36% | 27 | 10 |
| F_20bar_breakout_down | 151 | 127 | 68.48% | 73.75% | 33 | 9 |
| G_atr_expansion | 110 | 157 | 20.81% | 28.99% | 50 | 97 |

**UTC hours with the most breakout disagreement**: 23:00 69.57% of 23 (direction 93.68%); 22:00 65.38% of 26 (direction 84.89%); 21:00 50.00% of 4 (direction 91.84%); 07:00 42.86% of 7 (direction 95.29%); 03:00 37.50% of 8 (direction 95.81%)

**Weekday**

| day | matched | direction | median |close diff| | breakout disagreement |
|---|---|---|---|---|
| Monday | 866 | 97.00% | 2.68 | 37.10% of 62 |
| Tuesday | 897 | 96.21% | 2.68 | 14.29% of 77 |
| Wednesday | 892 | 96.30% | 2.66 | 8.06% of 62 |
| Thursday | 851 | 96.94% | 2.72 | 18.87% of 53 |
| Friday | 800 | 97.00% | 2.82 | 8.47% of 59 |
| Sunday | 66 | 83.33% | 3.16 | 89.29% of 28 |

- reopen candles (first/last hour around 40 market pauses ≥ 12 h): direction 75.00% vs 96.68% otherwise; median |close diff| 3.15 vs 2.71; breakout disagreement 90.48% vs 18.75%.
- pre pause candles (first/last hour around 40 market pauses ≥ 12 h): direction 92.50% vs 96.51% otherwise; median |close diff| 3.52 vs 2.71; breakout disagreement 100.00% vs 22.94%.

## BTC (BTCUSDT Perp vs BTCUSDm) — 15m

- Overlap 2023-11-10T23:15:00+00:00 → 2026-09-20T07:15:00+00:00; Binance 100,257 candles, Exness 100,239, matched 100,239 (unmatched Binance 18, unmatched Exness 0); coverage 99.98% of Binance, 100.00% of Exness. 99,839 candles after warm-up.
- Exness source: EXNESS_BTCUSDM_M15 (Native); Binance: BTCUSDT Perpetual (Binance Futures), 100,657 candles 2023-11-06T19:15:00+00:00 → 2026-09-20T07:15:00+00:00.

**Price offset (Binance − Exness)**

| field | mean | median | std | p5 | p95 | p99 | min | max | median % | p95 % |
|---|---|---|---|---|---|---|---|---|---|---|
| open | -5.78 | -7.23 | 57.67 | -98.32 | 88.05 | 126.00 | -738.22 | 449.94 | -0.0095% | 0.1372% |
| high | -7.95 | -9.16 | 58.46 | -101.82 | 85.72 | 124.99 | -1,445.80 | 812.44 | -0.0120% | 0.1329% |
| low | -2.16 | -3.47 | 59.80 | -95.72 | 94.31 | 134.92 | -2,210.62 | 440.05 | -0.0045% | 0.1494% |
| close | -5.75 | -7.14 | 57.73 | -98.42 | 88.30 | 126.37 | -738.68 | 449.92 | -0.0093% | 0.1373% |

**Time alignment**: 1-bar return correlation peaks at lag 0 bars (-3: -0.009, -2: -0.004, -1: -0.008, 0: 0.997, 1: 0.001, 2: -0.004, 3: -0.008).

**Returns**: 1_bar: Pearson 0.9968, Spearman 0.9949, same sign 97.40% (n=100,232); 3_bar: Pearson 0.9984, Spearman 0.9973, same sign 98.06% (n=100,225); 5_bar: Pearson 0.9987, Spearman 0.9980, same sign 98.28% (n=100,221)

**Direction**: same 97.39%, opposite 2.55%, flat disagreement 0.06%, same excluding flats 97.45%. Bull/Bull 48,921, Bull/Bear 1,298, Bear/Bull 1,257, Bear/Bear 48,704.

**Shape** (% of range, |B−E|): body median 3.12 p95 16.62; upper wick median 2.21 p95 11.99; lower wick median 2.33 p95 12.88; range ratio B/E median 0.972 (p5 0.805, p95 1.059), range correlation 0.9958.

**Levels** (|B−E|)

|  | abs median | abs p95 | % median | % p95 | ATR median | ATR p95 |
|---|---|---|---|---|---|---|
| high | 40.70 | 113.15 | 0.0532 | 0.1435 | 0.167 | 0.602 |
| low | 40.28 | 112.87 | 0.0529 | 0.1550 | 0.166 | 0.618 |
| range | 8.03 | 33.83 | 0.0102 | 0.0563 | 0.034 | 0.173 |
| high_excursion | 5.50 | 23.38 | 0.0070 | 0.0378 | 0.023 | 0.120 |
| low_excursion | 5.99 | 26.78 | 0.0076 | 0.0445 | 0.025 | 0.136 |

**ATR(14)**: correlation 0.9984, median diff -2.20%, median |diff| 2.33%, p95 |diff| 11.28%.

**EMA**

|  | level diff median (ATR) | |close−EMA| diff median / p95 (ATR) | slope agreement | close side agreement |
|---|---|---|---|---|
| ema20 | -0.030 | 0.030 / 0.120 | 98.63% | 98.63% |
| ema50 | -0.030 | 0.038 / 0.152 | 98.97% | 98.97% |
| ema200 | -0.030 | 0.055 / 0.214 | 99.34% | 99.34% |

**VWAP** — Binance: traded base-asset volume on the perpetual. Exness: MT5 tick volume (price-change count), not traded quantity. The two VWAPs weight prices differently and are NOT the same quantity; only the price-vs-VWAP state is compared. Price-vs-VWAP state agreement 96.39%; distance-from-VWAP difference median 0.178 ATR, p95 0.919 ATR.

**Events**

| event | Binance | Exness | same bar | ±1 bar | Binance-only | Exness-only |
|---|---|---|---|---|---|---|
| breakout close_5 | 15392 | 15042 | 84.68% | 91.34% | 864 | 514 |
| breakout close_10 | 10319 | 10143 | 84.89% | 91.02% | 569 | 393 |
| breakout close_20 | 6566 | 6562 | 85.63% | 91.01% | 311 | 307 |
| breakout wick_5 | 22529 | 22506 | 83.24% | 91.96% | 955 | 932 |
| breakout wick_10 | 15402 | 15441 | 82.83% | 91.81% | 639 | 678 |
| breakout wick_20 | 10108 | 10195 | 82.91% | 91.72% | 395 | 482 |
| swing 2 | 27118 | 27202 | 84.58% | 91.48% | 1167 | 1251 |
| swing 3 | 19388 | 19517 | 84.28% | 90.71% | 883 | 1012 |
| swing 5 | 12346 | 12406 | 84.13% | 90.17% | 610 | 670 |
| A_close_cross_above_ema20 | 7210 | 7056 | 83.23% | 90.52% | 432 | 278 |
| B_close_cross_below_ema20 | 7212 | 7056 | 82.88% | 90.60% | 430 | 274 |
| C_close_moves_above_vwap | 5541 | 5176 | 57.93% | 72.24% | 1046 | 681 |
| D_close_moves_below_vwap | 5542 | 5176 | 59.07% | 71.96% | 1057 | 691 |
| E_20bar_breakout_up | 3445 | 3460 | 85.42% | 91.12% | 153 | 168 |
| F_20bar_breakout_down | 3121 | 3102 | 85.87% | 90.89% | 158 | 139 |
| G_atr_expansion | 2345 | 2330 | 65.19% | 81.62% | 244 | 229 |

**UTC hours with the most breakout disagreement**: 10:00 13.54% of 288 (direction 97.20%); 06:00 13.24% of 287 (direction 96.72%); 11:00 11.60% of 293 (direction 97.22%); 05:00 11.49% of 235 (direction 97.20%); 04:00 10.04% of 239 (direction 97.03%)

**Weekday**

| day | matched | direction | median |close diff| | breakout disagreement |
|---|---|---|---|---|
| Monday | 14303 | 97.87% | 40.44 | 7.72% of 1011 |
| Tuesday | 14304 | 97.99% | 41.95 | 7.52% of 1050 |
| Wednesday | 14302 | 97.82% | 41.02 | 6.93% of 1039 |
| Thursday | 14293 | 98.02% | 42.01 | 6.90% of 1014 |
| Friday | 14307 | 97.41% | 40.16 | 8.86% of 1027 |
| Saturday | 14396 | 95.92% | 37.81 | 13.81% of 876 |
| Sunday | 14334 | 96.73% | 39.13 | 10.14% of 1055 |


## BTC (BTCUSDT Perp vs BTCUSDm) — 30m

- Overlap 2021-12-11T00:00:00+00:00 → 2026-09-22T16:30:00+00:00; Binance 83,842 candles, Exness 83,831, matched 83,831 (unmatched Binance 11, unmatched Exness 0); coverage 99.99% of Binance, 100.00% of Exness. 83,431 candles after warm-up.
- Exness source: EXNESS_BTCUSDM_M30 (Native); Binance: BTCUSDT Perpetual (Binance Futures), 84,242 candles 2021-12-02T16:00:00+00:00 → 2026-09-22T16:30:00+00:00.

**Price offset (Binance − Exness)**

| field | mean | median | std | p5 | p95 | p99 | min | max | median % | p95 % |
|---|---|---|---|---|---|---|---|---|---|---|
| open | -4.50 | -4.61 | 46.97 | -83.23 | 75.13 | 113.75 | -738.22 | 678.68 | -0.0114% | 0.1272% |
| high | -3.73 | -3.39 | 49.45 | -86.16 | 75.17 | 116.65 | -659.94 | 2,244.28 | -0.0082% | 0.1388% |
| low | -2.47 | -3.49 | 49.93 | -81.75 | 80.26 | 122.13 | -2,081.39 | 784.40 | -0.0084% | 0.1350% |
| close | -4.41 | -4.55 | 47.17 | -83.33 | 75.13 | 114.25 | -755.39 | 681.01 | -0.0110% | 0.1278% |

**Time alignment**: 1-bar return correlation peaks at lag 0 bars (-3: -0.005, -2: -0.006, -1: -0.009, 0: 0.997, 1: -0.006, 2: -0.008, 3: -0.005).

**Returns**: 1_bar: Pearson 0.9968, Spearman 0.9941, same sign 96.89% (n=83,825); 3_bar: Pearson 0.9984, Spearman 0.9972, same sign 97.79% (n=83,818); 5_bar: Pearson 0.9988, Spearman 0.9979, same sign 98.15% (n=83,815)

**Direction**: same 96.91%, opposite 3.05%, flat disagreement 0.04%, same excluding flats 96.95%. Bull/Bull 41,026, Bull/Bear 1,289, Bear/Bull 1,268, Bear/Bear 40,212.

**Shape** (% of range, |B−E|): body median 3.22 p95 16.21; upper wick median 2.40 p95 12.98; lower wick median 2.45 p95 13.29; range ratio B/E median 0.987 (p5 0.838, p95 1.144), range correlation 0.9956.

**Levels** (|B−E|)

|  | abs median | abs p95 | % median | % p95 | ATR median | ATR p95 |
|---|---|---|---|---|---|---|
| high | 24.82 | 101.16 | 0.0508 | 0.1508 | 0.110 | 0.407 |
| low | 23.74 | 101.45 | 0.0500 | 0.1526 | 0.107 | 0.410 |
| range | 7.93 | 38.91 | 0.0148 | 0.0894 | 0.035 | 0.186 |
| high_excursion | 5.64 | 28.53 | 0.0108 | 0.0665 | 0.025 | 0.143 |
| low_excursion | 6.01 | 29.16 | 0.0116 | 0.0647 | 0.026 | 0.144 |

**ATR(14)**: correlation 0.9986, median diff -0.65%, median |diff| 2.28%, p95 |diff| 9.57%.

**EMA**

|  | level diff median (ATR) | |close−EMA| diff median / p95 (ATR) | slope agreement | close side agreement |
|---|---|---|---|---|
| ema20 | -0.025 | 0.029 / 0.117 | 98.48% | 98.48% |
| ema50 | -0.025 | 0.036 / 0.141 | 98.98% | 98.98% |
| ema200 | -0.026 | 0.050 / 0.190 | 99.52% | 99.52% |

**VWAP** — Binance: traded base-asset volume on the perpetual. Exness: MT5 tick volume (price-change count), not traded quantity. The two VWAPs weight prices differently and are NOT the same quantity; only the price-vs-VWAP state is compared. Price-vs-VWAP state agreement 96.05%; distance-from-VWAP difference median 0.126 ATR, p95 0.734 ATR.

**Events**

| event | Binance | Exness | same bar | ±1 bar | Binance-only | Exness-only |
|---|---|---|---|---|---|---|
| breakout close_5 | 11805 | 12042 | 84.22% | 90.08% | 504 | 741 |
| breakout close_10 | 7547 | 7873 | 84.60% | 89.74% | 254 | 580 |
| breakout close_20 | 4785 | 5074 | 84.80% | 89.74% | 122 | 411 |
| breakout wick_5 | 18838 | 18843 | 82.90% | 91.79% | 804 | 809 |
| breakout wick_10 | 12619 | 12718 | 82.42% | 91.37% | 522 | 621 |
| breakout wick_20 | 8203 | 8303 | 82.75% | 91.40% | 321 | 421 |
| swing 2 | 23354 | 23251 | 83.92% | 91.58% | 1076 | 973 |
| swing 3 | 16751 | 16705 | 83.52% | 91.00% | 811 | 765 |
| swing 5 | 10829 | 10753 | 83.40% | 90.64% | 568 | 492 |
| A_close_cross_above_ema20 | 5965 | 5939 | 80.91% | 89.43% | 345 | 319 |
| B_close_cross_below_ema20 | 5964 | 5939 | 82.06% | 89.42% | 345 | 320 |
| C_close_moves_above_vwap | 6528 | 6274 | 65.06% | 77.04% | 957 | 703 |
| D_close_moves_below_vwap | 6528 | 6274 | 64.68% | 76.90% | 963 | 709 |
| E_20bar_breakout_up | 2450 | 2635 | 84.17% | 89.03% | 55 | 240 |
| F_20bar_breakout_down | 2335 | 2439 | 85.47% | 90.50% | 67 | 171 |
| G_atr_expansion | 2389 | 2340 | 64.32% | 79.67% | 292 | 243 |

**UTC hours with the most breakout disagreement**: 05:00 14.38% of 160 (direction 96.22%); 07:00 12.80% of 211 (direction 95.96%); 16:00 11.86% of 253 (direction 97.51%); 12:00 11.72% of 256 (direction 97.22%); 17:00 11.43% of 245 (direction 97.16%)

**Weekday**

| day | matched | direction | median |close diff| | breakout disagreement |
|---|---|---|---|---|
| Monday | 12000 | 97.39% | 24.50 | 7.88% of 825 |
| Tuesday | 11986 | 97.46% | 23.82 | 9.64% of 788 |
| Wednesday | 11949 | 97.32% | 23.88 | 10.53% of 807 |
| Thursday | 11948 | 97.28% | 25.76 | 10.09% of 793 |
| Friday | 11952 | 97.32% | 24.11 | 8.81% of 783 |
| Saturday | 11996 | 95.38% | 21.73 | 13.46% of 535 |
| Sunday | 12000 | 96.21% | 21.80 | 10.70% of 804 |


## BTC (BTCUSDT Perp vs BTCUSDm) — 1h

- Overlap 2023-11-07T00:00:00+00:00 → 2026-09-20T06:00:00+00:00; Binance 25,159 candles, Exness 25,158, matched 25,158 (unmatched Binance 1, unmatched Exness 0); coverage 100.00% of Binance, 100.00% of Exness. 24,758 candles after warm-up.
- Exness source: EXNESS_BTCUSDM_H1 (Native); Binance: BTCUSDT Perpetual (Binance Futures), 25,559 candles 2023-10-21T08:00:00+00:00 → 2026-09-20T06:00:00+00:00.

**Price offset (Binance − Exness)**

| field | mean | median | std | p5 | p95 | p99 | min | max | median % | p95 % |
|---|---|---|---|---|---|---|---|---|---|---|
| open | -5.64 | -6.92 | 58.09 | -97.83 | 88.10 | 125.50 | -738.22 | 839.36 | -0.0091% | 0.1382% |
| high | -7.02 | -8.34 | 59.76 | -102.00 | 87.60 | 131.38 | -498.51 | 812.44 | -0.0111% | 0.1376% |
| low | -2.63 | -3.26 | 63.61 | -96.73 | 93.36 | 133.69 | -2,081.39 | 380.80 | -0.0043% | 0.1481% |
| close | -5.71 | -6.63 | 59.58 | -98.04 | 88.46 | 126.53 | -2,271.29 | 370.58 | -0.0088% | 0.1390% |

**Time alignment**: 1-bar return correlation peaks at lag 0 bars (-3: -0.007, -2: -0.005, -1: -0.011, 0: 0.998, 1: -0.010, 2: -0.006, 3: -0.007).

**Returns**: 1_bar: Pearson 0.9981, Spearman 0.9975, same sign 98.19% (n=25,156); 3_bar: Pearson 0.9990, Spearman 0.9988, same sign 98.58% (n=25,154); 5_bar: Pearson 0.9993, Spearman 0.9991, same sign 98.86% (n=25,152)

**Direction**: same 98.18%, opposite 1.80%, flat disagreement 0.03%, same excluding flats 98.20%. Bull/Bull 12,443, Bull/Bear 246, Bear/Bull 206, Bear/Bear 12,256.

**Shape** (% of range, |B−E|): body median 1.86 p95 9.36; upper wick median 1.38 p95 7.16; lower wick median 1.40 p95 7.56; range ratio B/E median 0.987 (p5 0.893, p95 1.057), range correlation 0.9969.

**Levels** (|B−E|)

|  | abs median | abs p95 | % median | % p95 | ATR median | ATR p95 |
|---|---|---|---|---|---|---|
| high | 41.17 | 114.08 | 0.0541 | 0.1480 | 0.082 | 0.276 |
| low | 40.11 | 113.44 | 0.0531 | 0.1553 | 0.080 | 0.279 |
| range | 9.93 | 46.29 | 0.0126 | 0.0712 | 0.021 | 0.101 |
| high_excursion | 7.02 | 34.32 | 0.0090 | 0.0513 | 0.014 | 0.075 |
| low_excursion | 7.54 | 36.25 | 0.0098 | 0.0556 | 0.016 | 0.081 |

**ATR(14)**: correlation 0.9992, median diff -0.91%, median |diff| 1.12%, p95 |diff| 4.74%.

**EMA**

|  | level diff median (ATR) | |close−EMA| diff median / p95 (ATR) | slope agreement | close side agreement |
|---|---|---|---|---|
| ema20 | -0.015 | 0.020 / 0.078 | 99.16% | 99.16% |
| ema50 | -0.015 | 0.026 / 0.098 | 99.39% | 99.39% |
| ema200 | -0.017 | 0.039 / 0.134 | 99.56% | 99.56% |

**VWAP** — Binance: traded base-asset volume on the perpetual. Exness: MT5 tick volume (price-change count), not traded quantity. The two VWAPs weight prices differently and are NOT the same quantity; only the price-vs-VWAP state is compared. Price-vs-VWAP state agreement 96.81%; distance-from-VWAP difference median 0.072 ATR, p95 0.492 ATR.

**Events**

| event | Binance | Exness | same bar | ±1 bar | Binance-only | Exness-only |
|---|---|---|---|---|---|---|
| breakout close_5 | 3531 | 3537 | 91.08% | 94.71% | 93 | 99 |
| breakout close_10 | 2374 | 2405 | 91.16% | 94.35% | 54 | 85 |
| breakout close_20 | 1551 | 1570 | 91.24% | 94.58% | 34 | 53 |
| breakout wick_5 | 5581 | 5588 | 89.79% | 95.36% | 129 | 136 |
| breakout wick_10 | 3815 | 3827 | 89.39% | 95.10% | 90 | 102 |
| breakout wick_20 | 2570 | 2596 | 88.82% | 95.02% | 53 | 79 |
| swing 2 | 6933 | 6896 | 91.17% | 95.21% | 188 | 151 |
| swing 3 | 4992 | 4991 | 91.06% | 94.98% | 129 | 128 |
| swing 5 | 3135 | 3135 | 90.98% | 94.48% | 89 | 89 |
| A_close_cross_above_ema20 | 1639 | 1641 | 88.18% | 93.28% | 56 | 58 |
| B_close_cross_below_ema20 | 1639 | 1641 | 88.61% | 93.28% | 56 | 58 |
| C_close_moves_above_vwap | 2538 | 2418 | 74.94% | 84.93% | 262 | 142 |
| D_close_moves_below_vwap | 2538 | 2418 | 75.25% | 85.13% | 259 | 139 |
| E_20bar_breakout_up | 835 | 849 | 91.36% | 94.23% | 18 | 32 |
| F_20bar_breakout_down | 716 | 721 | 91.09% | 94.98% | 16 | 21 |
| G_atr_expansion | 682 | 672 | 71.18% | 88.58% | 46 | 36 |

**UTC hours with the most breakout disagreement**: 21:00 14.81% of 54 (direction 98.28%); 02:00 13.21% of 53 (direction 98.19%); 23:00 10.00% of 50 (direction 97.71%); 09:00 8.77% of 57 (direction 97.52%); 07:00 8.70% of 46 (direction 98.09%)

**Weekday**

| day | matched | direction | median |close diff| | breakout disagreement |
|---|---|---|---|---|
| Monday | 3576 | 98.27% | 40.81 | 4.38% of 297 |
| Tuesday | 3600 | 98.42% | 41.59 | 5.73% of 227 |
| Wednesday | 3600 | 98.44% | 40.94 | 5.86% of 222 |
| Thursday | 3599 | 98.56% | 42.26 | 4.35% of 230 |
| Friday | 3600 | 98.39% | 40.34 | 4.45% of 247 |
| Saturday | 3600 | 97.31% | 38.12 | 10.57% of 123 |
| Sunday | 3583 | 97.85% | 39.26 | 4.90% of 286 |


## Existing-strategy signal parity (BTC 15m)

Status: **PASS**. Each frozen BTC strategy is run by the unmodified ``engine.backtester.run_backtest`` on each feed separately, with default settings, on the IDENTICAL time grid (the candles both feeds have), so only prices differ. The backtester refuses a position that crosses missing candles, so every contiguous segment between the Exness data gaps is its own trading window, identical for both feeds (earlier candles are warm-up). Only signal timestamps and directions are compared, not PnL. Because a strategy does not signal while in a position, one diverging trade can shift later ones. No Gold strategy exists in the registry, so Gold has no strategy parity.

Window 2023-12-12T05:15:00+00:00 → 2026-09-20T07:15:00+00:00.

| strategy | Binance trades | Exness trades | same bar | ±1 bar | Binance-only | Exness-only |
|---|---|---|---|---|---|---|
| BTC_V3_CORE_V1_FROZEN | 341 | 320 | 53.72% | 55.53% | 105 | 84 |
| BTC_V3_A4_PULLBACK_LONG_FROZEN | 154 | 148 | 44.50% | 45.89% | 59 | 53 |
| BTC_V3_T3_BREAKOUT_SHORT_FROZEN | 187 | 172 | 62.44% | 64.68% | 46 | 31 |

Outlier candles: `outliers.csv`. Matched candles per pair/timeframe: `<PAIR>_<TF>.csv`.
