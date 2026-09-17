# MT5 live chart bridge contract

**Status: architecture only. EXNESS_LIVE is not connected.** The Streamlit Live Chart cannot send, close, or modify an MT5 order. No Bitstamp substitution is allowed for Exness live data.

## Source and ownership

- MT5 or a local companion process may publish **read-only** BTCUSDm quotes and M15 **Bid** bars to a local transport. That process must not accept trading commands from Streamlit.
- The Python interface is `ChartFeedProvider.read()` in `services/live_chart_source.py`; it returns a `FeedSnapshot` with `source=EXNESS_LIVE`. Today `UnconnectedMT5Feed` returns an explicit not-connected state and no candles.
- Exness historical M15 Bid bars at `data/exness/processed/btcusdm_m15.csv` remain the historical chart source. Bitstamp is available only by explicit reference-feed selection.
- The local bridge must identify the account, broker, symbol, clock offset, and feed health. It must not claim UTC until the server clock is verified as UTC+0. The existing Exness M15 export in this project was audited as UTC+0.

## Incoming records

Minimum tick record:

```csv
timestamp_utc,bid,ask
2026-09-18T12:00:03Z,63000.00,63010.00
```

Optional completed or developing Bid bar record:

```csv
timestamp_utc,open,high,low,close,tick_volume,bid,ask,bar_complete
2026-09-18T12:00:00Z,63000.00,63025.00,62995.00,63012.00,245,63012.00,63022.00,true
```

`timestamp_utc` is a UTC instant, not an unverified wall clock. The M15 bar timestamp is its **opening** time on a 00/15/30/45 UTC boundary. OHLC is Bid. Ask is a contemporaneous quote and must never be inferred by adding a historical bar-minimum spread. Require `bid > 0`, `ask >= bid`, monotonic timestamps, and valid OHLC. Keep raw messages distinguishable from reconstructed complete bars.

## Consumption rules

1. A future adapter validates the incoming records and atomically publishes a snapshot or reads a local IPC stream. It must not forward-fill across disconnects or gaps. A file publisher should write a temporary file and atomically replace the prior snapshot only after validation.
2. Streamlit may refresh its **display** every 5–10 seconds. The Setup A observer consumes each **new completed** M15 bar once, keyed by symbol and bar-open UTC timestamp. Repeated display refreshes do not create a new signal.
3. The current bar remains marked `DEVELOPING` and is excluded from Setup A evaluation. A completed bar is eligible only after its full 15 minutes have elapsed and the source marks it complete. H1 values come from the prior full four-bar H1 bucket through the frozen `ConfirmedH1Trend` implementation.
4. `LIVE SPREAD = ask - bid` uses the same tick. Historical `BAR MIN SPREAD` is a separate M15 research descriptor. A stale quote must say `STALE LIVE FEED`; it must not silently retain a green live status.
5. If verified server time is present, candle countdown is `next_UTC_quarter_hour - server_time`, shown as `MM:SS`. Without verified server time, countdown is unavailable.
6. If a gap appears, reset causal indicators at the new segment. Any displayed hypothetical pending level becomes invalid. The Streamlit chart does not manage broker orders or positions.

## Python versus MT5 parity monitor

The future MT5 EA decision feed should provide `signal_time_utc`, `symbol`, `magic`, `setup`, `direction`, `qualified`, `reason`, `trigger`, `stop`, `target`, and the freeze hash. Compare only matching completed M15 timestamps. Show `MATCH` or `MISMATCH` with the timestamp and reason; never infer a match from an absent EA record. Until this feed exists, the panel says **MT5 EA NOT CONNECTED**. The historical parity comparator in `tools/compare_mt5_setup_a.py` remains the separate Strategy Tester workflow.

## Security boundary

The bridge is read-only to the dashboard. There is no order endpoint, command queue, trading credential, stop modification, or strategy parameter mutation in Streamlit. The frozen Setup A manifest and active Python strategy are unchanged.
