# Frozen BTC V2.2 Setup B failure diagnostics

This report describes the existing Phase 4B segment-aware pooled completed trades. No strategy parameters, execution rules, or trade outcomes were changed. The pooled result does not form a continuous compounded equity curve.

Source: `pooled_trades.csv` SHA-256 `f17c2929897828b83e26da092a9fc9448ea72739d2a50f7307e0c1c9e6c396f8`; canonical candles SHA-256 `3ab2cc48c91106e7b1bdd755a525fcc2b595cdf158259cee0c2889d00aab46f2`.

Baseline: 955 trades; WR 26.49%; PF 0.8474; average R -0.1102; net PnL $-2,636.44.

## Cost and breakeven analysis

Per-trade quantity is recovered from recorded net PnL, fill prices, and the frozen 0.05% per-side commission model. Raw price PnL reverses the audited slippage formula; this frozen baseline uses 0% slippage.

Pre-cost price-movement PnL $1,091.74; commission $3,728.18; slippage $0.00; total costs $3,728.18; final net PnL $-2,636.44.
The aggregate price movement is modestly positive before costs; modeled commissions more than offset it. This is attribution within the frozen execution model, not a strategy change.
Average winner R 2.3465; average loser R -0.9956; required breakeven WR 29.79%; actual WR 26.49%; gap -3.30 percentage points.

## MFE / MAE and exit diagnosis

Conservative path-known excursions. Normal entry-bar opposite extreme and exit-bar extremes are excluded when their order relative to fill/exit is unknown. Excursion R uses actual fill-to-structural-stop price distance; realized R uses the engine's planned dollar risk. Threshold rates are lower bounds.

| Population | Trades | Reached 0.5R | 1R | 1.5R | 2R | 2.5R | 3R |
|---|---:|---:|---:|---:|---:|---:|---:|
| All | 955 | 65.45% | 50.99% | 42.09% | 35.08% | 29.84% | 26.60% |
| Long | 466 | 66.52% | 52.36% | 40.99% | 33.91% | 29.83% | 26.39% |
| Short | 489 | 64.42% | 49.69% | 43.15% | 36.20% | 29.86% | 26.79% |
| Losing | 702 | 52.99% | 33.33% | 21.23% | 11.68% | 4.56% | 0.14% |
| Stopped | 701 | 52.92% | 33.24% | 21.11% | 11.55% | 4.42% | 0.00% |

Stopped trades: 701; median/average MFE 0.544R / 0.828R; never reached 0.25R 29.81%; never reached 0.5R 47.08%; median stop distance 1.860 ATR.

## Fill quality

| Fill | Trades | WR % | PF | Avg R | Net PnL |
|---|---:|---:|---:|---:|---:|
| B+1 | 852 | 26.41 | 0.842 | -0.114 | $-2,438.55 |
| B+2 | 103 | 27.18 | 0.893 | -0.078 | $-197.89 |
| Normal | 934 | 26.12 | 0.834 | -0.121 | $-2,821.36 |
| Gap-through-trigger | 21 | 42.86 | 1.622 | 0.375 | $184.93 |

## Winner and loser descriptor differences

Ranked by absolute median difference divided by the pooled interquartile range. This is descriptive and does not imply causation.

| Descriptor | Winner median | Loser median | Difference / pooled IQR |
|---|---:|---:|---:|
| Bars held | 18.0000 | 9.0000 | 0.474 |
| RSI | 45.9679 | 48.5697 | -0.101 |
| Structure breakout distance ATR | 0.3906 | 0.3464 | 0.098 |
| EMA20 extension ATR | 1.4421 | 1.5325 | -0.094 |
| Stop distance ATR | 1.9087 | 1.8589 | 0.072 |

## Analysis sets

Development set: 2021-01-01 through 2024-12-31 UTC. Forward-validation set for future changes: 2025-01-01 through latest 2026 data; previously observed, not pristine. Performance in both periods has already been observed; the latter is not an untouched holdout.

Bucket and time tables retain every category, including losing and small-sample groups (<20 trades). They are descriptive only. No bucket was selected or applied.

[trade_diagnostics.csv](trade_diagnostics.csv) · [winner_loser_profile.csv](winner_loser_profile.csv) · [bucket_analysis.csv](bucket_analysis.csv) · [time_analysis.csv](time_analysis.csv) · [fill_analysis.csv](fill_analysis.csv) · [mfe_mae_analysis.csv](mfe_mae_analysis.csv) · [cost_analysis.csv](cost_analysis.csv)
