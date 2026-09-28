# `request.security()` — P2.1 contracts and semantics under test

Status: **implemented (P2.1).** The historical mapping in §8 was confirmed on real TradingView (q4:
134,400 / 134,400 cells, self-test failing exactly one cell as designed) and this engine reproduces all
134,400 cells (`ours/q4_engine_parity.json`). Replay and Live (§4, §5) are this engine's knowable-per-bar
semantics; they are tested locally (no future leak, incremental = fresh / full) and were checked by the
user in this terminal (Replay step by step, Binance Live forming bar: `terminal/p21_terminal_results.json`),
but they are **not** TradingView-verified. Implementation: `pine/security.py` (contexts, mapping), `pine/slicing.py`
(dependency slices), `component/security_data.py` (providers).

## 1. Data policy (locked)

| chart family | requested timeframe | source |
|---|---|---|
| Exness | a native authoritative dataset exists (today M15, M30, H1; any later one registered as authoritative) | that dataset, unchanged |
| Exness | anything else (2H, 4H, D, …) | aggregated from the **finest approved authoritative Exness dataset** for the symbol (today M15) — never from a coarser one merely because it is closer (2H/4H come from M15, not H1) |
| Exness | no native dataset and no approved finer dataset | **explicit error** naming the missing source |
| Binance | an interval Binance serves natively (1m 3m 5m 15m 30m 1h 2h 4h 6h 8h 12h 1d 3d 1w 1M) | read-only public market-data klines (no authentication, no private or order endpoints) |
| Binance | a custom interval (e.g. 90m) | aggregated only from Binance-family data (a base interval that divides it) |
| either | the other family | **never** — see §6 |

Aggregation base selection is deterministic: the finest approved authoritative dataset of the same
family and symbol whose timeframe divides the requested one and whose bar boundaries align with it.

## 2. Timeframe contract

Canonical form = `(unit, multiplier)` → duration and boundary rule.

| Pine string | canonical | duration | boundary |
|---|---|---|---|
| `"1"` `"5"` `"15"` `"30"` | minutes ×1/5/15/30 | 60 / 300 / 900 / 1800 s | provider clock, multiples of the duration from the provider day start |
| `"60"` `"120"` `"240"` | minutes ×60/120/240 (= 1H / 2H / 4H) | 3600 / 7200 / 14400 s | same |
| `"D"` / `"1D"` | days ×1 | provider trading day | provider day start |
| `"W"` / `"1W"` | weeks ×1 | provider week | provider week start |
| `"M"` / `"1M"` | months ×1 | calendar month | provider month start |

Provider boundaries — **not assumed to be UTC**:

* **Binance:** klines are aligned in UTC (day 00:00 UTC, week Monday 00:00 UTC, month the 1st 00:00 UTC).
* **Exness:** boundaries follow the MT5 **trade-server** clock. The datasets record it:
  `server_utc_offset_seconds_at_capture = 0` (Exness-MT5Trial5), so today's intraday, H4 and daily
  boundaries coincide with UTC. Aggregation must read the offset from the dataset's metadata and refuse a
  dataset that does not record it. Market sessions (gold closes Friday ~21:00 UTC and reopens Sunday
  22:00/23:00 UTC) create gaps; they do not move boundaries.
* **Exness weekly/monthly:** MT5 W1 bars start on the server's Sunday; this has **not been verified**
  against a native Exness W1/MN1 export, so `"W"` and `"M"` on Exness are **blocked** (explicit error)
  until a native sample is captured.

Rules:

* The requested timeframe must be ≥ the chart timeframe. Lower timeframes are `request.security_lower_tf`
  (P2.2, needs arrays) → explicit error in P2.1.
* A requested timeframe must be an exact multiple of its aggregation base and aligned to the same
  boundaries (45m from 30m is rejected; from 15m it is allowed).
* Seconds (`"1S"`…), tick and range charts, and non-time bar types are unsupported → explicit error.
* A timeframe that is not a whole multiple of a day but longer than a day (e.g. `"2880"`) → explicit error
  unless the provider serves it natively (Binance `3d` = `"3D"`).

## 3. Provenance contract (every security context)

`{family, provider, symbol, requested_timeframe, native | aggregated, aggregation_base_timeframe,
bar_count, max_source_time, data_identity, data_fingerprint}` where

* `data_identity` names the exact source: the dataset key + file for Exness (e.g.
  `EXNESS_BTCUSDM_M15 · data/exness/btc/phase_r1/processed/btcusdm_M15.csv`), or
  `binance:fapi:klines:<symbol>:<interval>` plus the fetched time range for Binance;
* `data_fingerprint` is the dataset's recorded `dataset_sha256` (Exness metadata) or a hash of the fetched
  bars (Binance);
* `max_source_time` is the latest source-bar close time the context consumed.

An old result therefore always says which source produced it, even after finer history is added.

## 4. Replay contract — knowable at cursor (locked)

At replay cursor T:

* a completed requested bar is used only if it closed at or before T;
* the forming requested bar is **rebuilt from revealed chart-timeframe bars only** (open time ≥ the
  requested bar's start and ≤ T) — a native final bar is never injected because it exists on disk;
* no final future open/high/low/close/volume can reach an earlier bar;
* the provider refuses later data; the payload validator independently checks every context's
  `max_source_time ≤ T`.

TradingView's *historical* `lookahead_on` shows a requested bar's final value from its first chart bar (a
known future leak on history). In Replay that is not allowed: `lookahead_on` shows the forming value, like
TradingView does in realtime. Historical semantics and Replay semantics are documented and tested
separately.

## 5. Live contract (locked)

The forming requested candle contains only what this terminal has received:

* **Binance:** built from the received live chart/feed updates; the exchange's own already-formed native
  candle is not substituted when it contains trades our stream has not seen;
* **Exness:** built from received MT5 live updates; historical files are used for completed bars only.

Each chart tick rolls back and re-runs only the forming requested bar of each context (the P1
commit/rollback model); a full recompute on the same bars must equal the incremental state.

## 6. Cross-family contract (locked)

No cross-family contexts: Binance chart → Exness symbol and Exness chart → Binance symbol are rejected.

* literal symbol → rejected at analysis time;
* dynamic symbol (input, string expression) → validated at run time.

Diagnostic, e.g.: ``request.security(): symbol `XAUUSDm` belongs to Exness MT5, but this chart's source is
Binance Futures. Requests across data sources are not allowed.`` — naming the requested symbol, its family,
the chart's family and the restriction. Pine on Binance charts stays visual context only and never feeds
the Exness signal authority.

## 7. Dependency-slice contract (first accepted subset)

The requested expression runs in the requested context together with the global statements it depends
on (its *slice*). P2.1 accepts:

* OHLCV / time / bar variables, constants, inputs;
* arithmetic, comparisons, ternaries, `if` / `switch` whose dependencies are immutable scalars;
* history references;
* `ta.*` built-ins supported by P1 (they keep their own state in the requested context);
* tuples;
* supported user functions (with their own call-site state and `var`);
* ordinary scalar state (`var`, `:=`) that can be isolated: every assignment to a sliced variable is itself
  sliceable.

Not yet accepted (explicit capability error, never approximated): arrays, maps, matrices, drawings, object
or UDT mutation, a global variable reassigned in a way the slice cannot isolate (ambiguous global
mutation), and side effects (plots, alerts, `runtime.error`) inside the slice.

## 8. Historical semantics under test (fixture `quick/q4_security_historical.pine`)

Chart: `BINANCE:BTCUSDT`, 1 minute, the last 1200 historical bars (the forming bar is excluded), with
1500 bars of history before them. Every value derives from `time`, so the chart context computes the
value of any requested bar itself; `request.security()` is only the value under test.

Documented hypotheses (TradingView documentation, **to be confirmed**) for chart bar *i* inside the
requested period that opens at *Hc* (position 0 = first chart bar of the period):

| gaps | lookahead | pattern (5m) | meaning |
|---|---|---|---|
| off | off | `PPPPC` | previous requested bar until the chart bar that closes the period, then the current one |
| on | off | `nnnnC` | na except on the chart bar that closes the period |
| off | on | `CCCCC` | the current (final) requested bar from its first chart bar — future leak on history |
| on | on | `Cnnnn` | the current requested bar only on its first chart bar |

Same timeframe (`"1"` on a 1-minute chart): `C` on every bar.

The table records the pattern TradingView actually produced per position (`C` current, `P` previous,
`n` na, `*` mixed), so the result establishes the semantics even where a hypothesis is wrong. Cases per
mapping: direct value, `src[1]` in the requested context, arithmetic, `ta.sma` / `ta.ema` / `ta.rsi` in the
requested context, a user function with history, a user function with `var` state, a tuple of four
OHLC-like values including one from `time_close`, and a global variable evaluated in the requested context.
Mappings: `"1"` (same timeframe), `"5"` and `"15"` × gaps on/off × lookahead on/off (tuple calls), plus the
four `"5"` mappings as single-value calls.

This fixture covers **historical** semantics only. Replay (no future leak) and live (forming requested bar)
get their own checks later; nothing here verifies them.
