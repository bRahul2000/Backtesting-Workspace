# Frozen BTC V2.2 Setup B history baseline

Largest continuous range: 2025-10-17 13:00:00+00:00 to 2026-08-05 09:00:00+00:00; 28,017 candles; 9.59 months.
Complete saved dataset: 200,084 candles, 83 missing, 24 segments.
Latest completed candle at report time: 2026-09-17 09:15:00+00:00; the archive is 31 candles behind it.

Original Setup B defaults and the audited account settings from the validated checkpoint were used.
The official Bitstamp OHLC endpoint was unreachable during this update. Expanded rows were conservatively aggregated from a documented Bitstamp one-minute archive; see `data/btcusd_15m_provenance.json`. The API-derived portion matched all 2,953 saved overlap candles. Differences in the older bulk portion on the isolated 2025-01-01 day are recorded in provenance, and saved canonical rows took precedence.

## Full period

Signals long/short: 84/125; pending created/filled/expired/cancelled: 209/160/48/1.
Trades 160; wins/losses/breakeven 44/116/0; win rate 27.50%.
Gross profit $2,491.90; gross loss $-2,808.69; net PnL $-316.79; PF 0.8872.
Average R -0.0776; median R -1.0000; expectancy R -0.0776; winner R 2.3490; loser R -0.9981.
Max DD $596.27 / 5.9277%; final balance $9,683.21; trades/month 16.69.
Maximum consecutive wins/losses 5/12; average bars held 24.89.

## Calendar years

| Year | Trades | Long | Short | WR % | Net PnL $ | PF | Average R | Expectancy R | Max DD % | Trades/month |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 44 | 14 | 30 | 20.45 | -320.20 | 0.6275 | -0.2933 | -0.2933 | 3.7703 | 17.75 |
| 2026 | 116 | 51 | 65 | 30.17 | 3.41 | 1.0018 | 0.0042 | 0.0042 | 3.8928 | 16.32 |

## Direction

| Side | Trades | WR % | Net PnL $ | PF | Average R | Expectancy R | Max losing streak |
|---|---:|---:|---:|---:|---:|---:|---:|
| LONG | 65 | 27.69 | -165.72 | 0.8549 | -0.0987 | -0.0987 | 14 |
| SHORT | 95 | 27.37 | -151.07 | 0.9094 | -0.0633 | -0.0633 | 12 |

## Non-overlapping six-month windows

| Period | Trades | WR % | PF | Average R | Net PnL $ | Max DD % |
|---|---:|---:|---:|---:|---:|---:|
| 2025-10-17 to 2026-04-17 | 105 | 23.81 | 0.7629 | -0.1769 | -460.54 | 5.5385 |

Monthly results: 5 profitable, 6 losing, 0 breakeven months. Download [monthly.csv](monthly.csv).

## Other continuous segments

9 other segments of at least 90 days were backtested independently with fresh account and indicator state. Their results are in [other_segments.csv](other_segments.csv), [other_segment_yearly.csv](other_segment_yearly.csv), and [other_segment_rolling_6m.csv](other_segment_rolling_6m.csv). They are not combined into the primary balance or PnL.

## Data integrity gaps

All 23 gaps are retained. Download [data_gaps.csv](data_gaps.csv) and [continuous_segments.csv](continuous_segments.csv).

| Gap start UTC | Gap end UTC | Missing candles |
|---|---|---:|
| 2021-04-14 08:15:00+00:00 | 2021-04-14 09:15:00+00:00 | 5 |
| 2021-09-22 10:15:00+00:00 | 2021-09-22 10:15:00+00:00 | 1 |
| 2021-10-20 08:15:00+00:00 | 2021-10-20 08:45:00+00:00 | 3 |
| 2021-11-24 09:15:00+00:00 | 2021-11-24 09:45:00+00:00 | 3 |
| 2022-01-05 08:15:00+00:00 | 2022-01-05 10:00:00+00:00 | 8 |
| 2022-02-16 09:15:00+00:00 | 2022-02-16 09:30:00+00:00 | 2 |
| 2022-05-11 08:15:00+00:00 | 2022-05-11 08:45:00+00:00 | 3 |
| 2022-07-13 11:00:00+00:00 | 2022-07-13 12:00:00+00:00 | 5 |
| 2022-07-27 08:15:00+00:00 | 2022-07-27 08:45:00+00:00 | 3 |
| 2022-08-10 08:15:00+00:00 | 2022-08-10 08:15:00+00:00 | 1 |
| 2022-12-07 08:15:00+00:00 | 2022-12-07 08:15:00+00:00 | 1 |
| 2023-03-23 10:15:00+00:00 | 2023-03-23 11:30:00+00:00 | 6 |
| 2023-06-28 09:15:00+00:00 | 2023-06-28 09:30:00+00:00 | 2 |
| 2023-07-03 10:45:00+00:00 | 2023-07-03 10:45:00+00:00 | 1 |
| 2023-07-03 11:15:00+00:00 | 2023-07-03 13:00:00+00:00 | 8 |
| 2024-02-18 16:45:00+00:00 | 2024-02-18 17:15:00+00:00 | 3 |
| 2024-03-29 10:30:00+00:00 | 2024-03-29 10:45:00+00:00 | 2 |
| 2024-04-07 08:15:00+00:00 | 2024-04-07 08:45:00+00:00 | 3 |
| 2024-12-07 01:30:00+00:00 | 2024-12-07 04:15:00+00:00 | 12 |
| 2024-12-11 10:15:00+00:00 | 2024-12-11 10:30:00+00:00 | 2 |
| 2025-03-23 08:45:00+00:00 | 2025-03-23 09:45:00+00:00 | 5 |
| 2025-10-17 12:30:00+00:00 | 2025-10-17 12:45:00+00:00 | 2 |
| 2026-08-05 09:15:00+00:00 | 2026-08-05 09:30:00+00:00 | 2 |
