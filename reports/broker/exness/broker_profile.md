# Exness Standard BTCUSDm broker profile

Source: specifications supplied from the user's MT5 terminal. This profile does not modify the strategy or generic backtester.

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
| MT5 server timezone | GMT+0 / UTC ([official Exness trading-hours guide](https://get.exness.help/hc/en-us/articles/4405235684498-Instrument-trading-hours)) |
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

The generic importer also has a provisional `--server-time-unverified` option for a future source whose timezone is genuinely unknown. For these Exness MT5 samples, the user confirmed that the export timestamps are Exness server time, and Exness's current [trading-hours documentation](https://get.exness.help/hc/en-us/articles/4405235684498-Instrument-trading-hours) states that its trading servers follow UTC+0. The CSV strings have no offset embedded; their equivalence to UTC follows from those two facts. The `*_server_time.csv` names preserve source-clock provenance. Original date and time strings remain in the reconstructed tick rows.

The generic importer preserves raw files, rejects malformed quotes and timestamps, removes exact duplicate `(timestamp, bid, ask)` ticks, retains different quotes at the same timestamp, sorts ticks chronologically, and leaves missing 15-minute buckets absent. For the collected MT5 files, use the multi-sample reconstruction below so partial Bid-only updates are retained. It does not touch the Bitstamp dataset or reports.

## MT5 multi-sample quote reconstruction

For the verified BTCUSDm MT5 export schema (`<DATE>`, `<TIME>`, `<BID>`, `<ASK>`, `<LAST>`, `<VOLUME>`, `<FLAGS>`), use:

```sh
venv/bin/python -m services.exness_mt5_samples
```

This processes each raw CSV independently and preserves file order, including distinct updates with the same timestamp. A populated Bid or Ask replaces only that side of the quote. A blank side retains its latest known value **within the same file and continuous 15-minute sequence**. The state resets at each file boundary and missing 15-minute interval, and no paired quote is emitted before both sides are known. Output tick rows include original raw Bid/Ask, reconstructed Bid/Ask, carry indicators, original MT5 timestamp, and source row number. Each sample has separate Bid and Ask bars. The source timezone status is `EXNESS_MT5_SERVER_TIME_UTC_PLUS_0_CONFIRMED`, based on the current Exness server documentation linked above.

The research-only `historical_spread_price` helper reads spread directly from a reconstructed Bid/Ask quote. The generic execution engine and the frozen strategy remain unchanged. The earlier single-file output records the initial import that excluded partial updates; the multi-sample outputs and reports are the authoritative reconstruction for these five MT5 samples.
