# Exness Standard BTCUSDm broker profile

Source: specifications supplied from the user's MT5 terminal. Historical tick files have not yet been supplied. This profile does not modify the strategy or generic backtester.

| Field | User-observed value |
|---|---|
| Broker | Exness |
| Account type | Standard |
| MT5 symbol | BTCUSDm |
| Digits | 2 |
| Contract size | 1 lot = 1 BTC |
| Volume step | 0.01 lot |
| Maximum volume | 200 lots |
| Spread | Floating |
| Commission | 0 |
| Stops level | 0 |
| Margin currency | BTC |
| Profit currency | USD |
| Execution | Market |
| Chart mode | Bid price |
| Trade access | Full access |
| Displayed sessions | Sunday–Saturday, 00:00–24:00 |
| Swap mode | Points |
| Long swap | −1609.2 points |
| Short swap | 0 points |
| Friday swap multiplier | 3 |
| Swap dollar conversion | **PENDING VERIFICATION** |

The displayed sessions are recorded as shown; historical session availability must be established from ticks. No fixed spread, percentage commission, minimum fee, or swap dollar value is inferred.

## Research-only Bid/Ask execution specification

Signals and the broker's M15 chart use completed **Bid** candles. A long buy entry and buy-stop trigger use **Ask**; a long position's close and SL/TP checks use **Bid**. A short sell entry and sell-stop trigger use **Bid**; a short position's close and SL/TP checks use **Ask**. The generic engine still uses its prior model and is unchanged.

Phase 4F-B can calculate signals from completed M15 Bid candles and evaluate pending triggers, entries, stops, targets, and exits chronologically against raw Bid/Ask ticks. It must preserve the original signal time, pending lifetime, stop, and 3R target, and handle exact-timestamp quote ordering explicitly. This phase does not perform that strategy rerun.

## Live screenshot sanity observation

Approximate best Ask: **76839.14**. Approximate best Bid: **76829.14**. Observed spread: approximately **$10 per BTC** at that instant. It is not a backtest spread assumption; historical ticks will determine the research distribution.

## Import procedure

Place untouched BTCUSDm CSV or ZIP tick files under `data/exness/raw/`. Inspect each source's actual headers before mapping:

```sh
venv/bin/python -m services.exness_ticks inspect data/exness/raw/your_file.csv
```

Then specify the exact timestamp, Bid, and Ask column names. If timestamps have no offset, provide their documented source timezone; numeric timestamps require an explicit unit. For example, **only if the file is verified UTC**:

```sh
venv/bin/python -m services.exness_ticks import data/exness/raw/your_file.csv --timestamp-column Time --bid-column Bid --ask-column Ask --source-timezone UTC
```

The importer preserves the raw file, rejects malformed quotes and timestamps, removes only exact duplicate `(timestamp, bid, ask)` ticks, retains different quotes at the same timestamp, sorts ticks in UTC, and leaves missing 15-minute buckets absent. It writes normalized ticks and Bid/Ask M15 bars under `data/exness/processed/`, plus the broker audit files here. It does not touch the Bitstamp dataset or reports.
