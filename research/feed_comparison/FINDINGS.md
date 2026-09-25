# Binance Futures vs Exness MT5: can Binance drive signals while Exness executes?

Research run 2026-09-25. The generated metrics are in `output/REPORT.md` and
`output/summary.json`; this page states what they support. Thresholds and
definitions were fixed in `thresholds.py` before the first run and were not changed.

## Data used

| pair / tf | overlap (UTC) | Binance candles | Exness candles | matched | Exness source |
|---|---|---|---|---|---|
| Gold 15m | 2025-12-23 00:00 → 2026-09-18 20:30 | 25,907 | 17,480 | 17,480 | EXNESS_XAUUSDM_M15 |
| Gold 30m | 2025-12-23 00:00 → 2026-09-18 20:00 | 12,953 | 8,739 | 8,739 | derived from M15 (project `aggregate_ohlcv`, complete buckets) |
| Gold 1h | 2025-12-23 00:00 → 2026-09-18 19:00 | 6,476 | 4,372 | 4,372 | EXNESS_XAUUSDM_H1 |
| BTC 15m | 2023-11-10 23:15 → 2026-09-20 07:15 | 100,257 | 100,239 | 100,239 | EXNESS_BTCUSDM_M15 |
| BTC 30m | 2021-12-11 00:00 → 2026-09-22 16:30 | 83,842 | 83,831 | 83,831 | EXNESS_BTCUSDM_M30 |
| BTC 1h | 2023-11-07 00:00 → 2026-09-20 06:00 | 25,159 | 25,158 | 25,158 | EXNESS_BTCUSDM_H1 |

- **Every Exness candle has a Binance candle at the same UTC time.** The unmatched Binance
  Gold candles are weekend and daily-break hours when Exness Gold is closed.
- **Binance XAUUSDT history starts on 2025-12-11**, so Gold covers about 9 months.
- **The timestamps are aligned.** 1-bar return correlation peaks at lag 0 for every pair and
  timeframe (Gold 0.991–0.994, BTC 0.997–0.998), with every other lag near 0.

## Headline metrics (as traded: each feed's own candles; ±1 bar event agreement)

| | direction | breakout20 ±1 | EMA20 cross ±1 | swing(3) ±1 | VWAP state | median close diff (B−E) |
|---|---|---|---|---|---|---|
| **Gold 15m** | 95.44% | 84.25% | 80.75% | 85.21% | 96.86% | +2.59 (+0.058%) |
| **Gold 30m** | 95.94% | 83.15% | 79.17% | 85.63% | 96.83% | +2.59 |
| **Gold 1h** | 96.48% | 76.13% | 74.23% | 85.65% | 97.33% | +2.58 |
| BTC 15m | 97.39% | 91.01% | 90.56% | 90.71% | 96.39% | −7.14 (−0.009%) |
| BTC 30m | 96.91% | 89.74% | 89.43% | 91.00% | 96.05% | −4.55 |
| BTC 1h | 98.18% | 94.58% | 93.28% | 94.98% | 96.81% | −6.63 |

**Gold with Binance's weekend and break candles removed** (a diagnostic view, not how a
Binance-driven algo would see the market):

| | breakout20 ±1 | EMA20 cross ±1 | swing(3) ±1 |
|---|---|---|---|
| 15m | 88.27% | 87.15% | 87.97% |
| 30m | 91.27% | 88.49% | 89.72% |
| 1h | 91.87% | 91.71% | 92.43% |

Removing those candles recovers only part of the gap: even in hours when both
feeds trade, about 1 in 8 Gold 15m breakouts and EMA20 crosses happen on only one feed.

**Existing strategies (BTC 15m, unmodified backtester, identical time grid):**

| strategy | trades (Binance / Exness) | signals matching within ±1 bar |
|---|---|---|
| BTC_V3_CORE_V1 | 341 / 320 | 55.5% |
| A4 pullback long | 154 / 148 | 45.9% |
| T3 breakout short | 187 / 172 | 64.7% |

No Gold strategy exists, so Gold has no strategy parity result.

## Where it breaks

- **Gold at the daily break and the reopen.**
  - 20:00–23:00 UTC is the worst window: direction agreement is 84.9–88.1% at 22:00 against ~96% otherwise.
  - The first hour after a weekend reopen is worst of all: at 15m, 54% of breakouts disagree against
    14% in normal hours, and at 1h the figure is 90%.
  - Sunday candles show 44–89% breakout disagreement.
- **Gold dislocation episodes.** On 2026-01-30 17:30–18:15 UTC, during a sharp sell-off, Binance closed
  $51–$73 above Exness, where the median offset is +$2.59.
- **Gold volatility is systematically lower on Binance.**
  - ATR(14) is 6.4–7.3% lower in the median, with a p95 absolute difference of 20–46%.
  - The median candle range is 0.95× Exness's.
  - The ATR-expansion proxy agrees only 29–48% of the time (±1 bar), so ATR-based sizing, stops or
    filters would differ.
- **BTC crash candles.**
  - 2025-10-10 21:15 UTC: Binance's low was 101,516 against Exness's 103,598.
  - 2024-08-03 15:45 UTC: Binance closed 739 below Exness.
  - Breakout disagreement is highest on Saturdays (13.8% at 15m).
- **VWAP.** The two VWAPs use different volume (Binance traded quantity, Exness tick volume), so their
  values aren't comparable. Price-vs-VWAP state agrees 96–97%, but VWAP crossing events agree only
  72–85% within ±1 bar.

## Answer

**Not as a drop-in signal feed, and least of all for Gold.**

- **Gold:**
  - Candle direction (95–96.5%) and slow indicator state are similar:
    - EMA20 slope and price side agree ~97%.
    - EMA200 agrees 93–95%.
    - VWAP state agrees ~97%.
  - Every event-timing metric that would trigger a trade is **weak** on the locked scale: breakouts
    76–84%, EMA20 crosses 74–81%, swings ~85%, and ATR expansion 29–48%.
  - Disagreement concentrates exactly where an Exness Gold algo is most exposed: the daily break, the
    Sunday reopen, and fast markets.
  - A strategy validated on Exness Gold data should not be assumed to fire the same trades from
    Binance XAUUSDT.
- **BTC:**
  - Parity is better. 1h is moderate to strong: breakouts 94.6%, swings 95.0%. 15m is moderate: ~90–91%.
  - The frozen BTC strategies still produce only 46–65% of the same signals, because small candle
    differences compound through strategy state.
- **Reasonable use:** Binance as a contextual, visual and higher-timeframe analysis feed:
  - trend and EMA state
  - VWAP side
  - rough structure
- **Not supported by these metrics:** Binance as the trigger feed for a strategy that executes on
  Exness. Such a strategy would need to be validated on Binance data itself, or the signals generated
  on the Exness feed.

**Caveats:**
- Gold covers about 9 months, from Binance's listing.
- Swings are simple fractals, and the proxies are neutral, not any production strategy.
- Strategy parity covers BTC 15m only.
