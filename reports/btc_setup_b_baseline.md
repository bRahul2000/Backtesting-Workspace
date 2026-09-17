# BTC V2.2.0 Setup B baseline

This unoptimized run uses the broadest contiguous saved Bitstamp BTC/USD 15-minute
segment: **2026-08-17 00:00 through 2026-09-16 18:00 UTC**, inclusive, with
**2,953 candles** (30.7604 days, approximately **1.01 normalized months**).
The CSV contains 3,049 candles overall, including an isolated 96-candle day
on 2025-01-01. The long gap makes that day unsuitable for continuous indicator
warm-up or trading, so it was excluded.

- Pine authority: `reference/BTC_Pullback_Trend_Breakout_V2_2_0.pine`
- Data: `data/btcusd_15m.csv` (SHA-256 `efcc58c7420da49aebc7f8c46dd84d6e0c47a1e75338530dd2eb2b777e084da3`)
- Setup B signal, indicator, session, day, and permission parameters: original V2.2.0 defaults
- Audited engine account model: $10,000 start; 0.25% equity risk; estimated total stop-loss sizing; 3R reward; 1× maximum leverage; no minimum quantity; 0.05% commission per side; 0% percentage slippage; SL First
- Pine's two-tick slippage cannot be represented exactly by the engine's percentage-slippage input. No tick-to-percent conversion was invented.
- H1 EMA200 is seeded from the first available completed H1 candle in this segment. Earlier market history is unavailable.

## Results

| Measure | Baseline |
|---|---:|
| Data start / end | 2026-08-17 00:00 / 2026-09-16 18:00 UTC |
| Total candles / approximate months | 2,953 / 1.01 |
| Long / short / total final signals | 9 / 4 / 13 |
| Pending created / filled / expired / cancelled | 13 / 6 / 7 / 0 |
| Completed / long / short trades | 6 / 4 / 2 |
| Wins / losses / breakeven | 2 / 4 / 0 |
| Win rate | 33.33% |
| Gross profit | +$110.53 |
| Gross loss | −$100.57 |
| Net PnL | +$9.96 |
| Profit factor | 1.0990 |
| Average R / expectancy R | +0.0693 R / +0.0693 R |
| Maximum closed-trade drawdown | $75.45 / 0.7481% |
| Final closed-trade balance | $10,009.96 |
| Average trades per normalized month | 5.94 |
| Maximum consecutive losses | 3 |

The normalized month is 30.4375 days. Trade frequency is
`6 / (2,953 × 15 minutes / 30.4375 days) = 5.94` per month.

| Direction | Trades | Wins | Losses | Win rate | Net PnL | Profit factor | Average R |
|---|---:|---:|---:|---:|---:|---:|---:|
| LONG | 4 | 2 | 2 | 50.00% | +$60.20 | 2.1960 | +0.6039 |
| SHORT | 2 | 0 | 2 | 0.00% | −$50.24 | 0.0000 | −1.0000 |

## Signal funnel

Counts are cumulative within each direction: each stage counts eligible
candles that passed all earlier stages for that direction. Shared stages add
the long and short streams.

| Stage | Count |
|---|---:|
| Eligible candles | 1,556 |
| H1 long trend / H1 short trend | 1,049 / 307 |
| M15 long alignment / M15 short alignment | 599 / 204 |
| ADX pass | 580 |
| Long RSI pass / Short RSI pass | 313 / 93 |
| Strong bullish candle / Strong bearish candle | 74 / 24 |
| Range ATR pass | 84 |
| Long structure breakout / Short structure breakout | 17 / 6 |
| Anti-chase pass | 14 |
| Long stop-distance pass / Short stop-distance pass | 9 / 4 |
| Final Long Signals / Final Short Signals | 9 / 4 |

## Candle-level validation

The [event audit](btc_setup_b_event_audit.csv) records all **13 real Setup B
events** with the M15 signal OHLC, preceding confirmed H1 hour and values,
five-candle structure, breakout close, RSI, ADX, ATR, body and range ratios,
trigger, structural stop, first eligible trigger touch, fill candle OHLC,
actual fill, target, exit candle OHLC, exit price, and exit reason. Every
recorded value was checked against the saved candles and Pine conditions:
**13/13 events passed**. All **6/6 completed trades** passed fill, target,
and exit checks. The other seven pending orders had no B+1 or B+2 trigger
touch and expired; fill, target, and exit fields do not exist for those orders.
Only six completed trades are available in this reliable saved segment, so
ten distinct completed trades cannot be inspected from this dataset.

This short baseline is a reference run, not evidence of profitability.
