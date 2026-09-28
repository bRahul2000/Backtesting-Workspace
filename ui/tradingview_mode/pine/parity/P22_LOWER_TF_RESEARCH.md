# P2.2-A4 `request.security_lower_tf()` — evidence and design (APPROVED, frozen)

Recorded 2026-09-28. Sources: the official Pine v6 manual (*Other timeframes and data*, *Limitations*, *Migration
guide to v6*), real TradingView observations (m06, section 2), the P2.1 engine (`pine/security.py`,
`pine/slicing.py`, `component/security_data.py`, SECURITY_SEMANTICS.md) and the frozen array model
(P22_ARRAY_ARCHITECTURE.md). Every statement is labelled: **documented**, **observed** (real TradingView),
**engine policy** (this terminal's locked data rules) or **engine limitation** (a compatibility gap, not
TradingView behaviour).

## 1. Official documentation (documented)

| topic | documented behaviour |
|---|---|
| signature | `request.security_lower_tf(symbol, timeframe, expression, ignore_invalid_symbol, currency, ignore_invalid_timeframe, calc_bars_count) → array<type>`; **no** `gaps`, **no** `lookahead` |
| return type | always arrays; the element type is the expression's type (`int` → `array<int>`, …) |
| tuples | a tuple expression (or a function returning one) → a tuple of arrays: `[float, string, color]` → `[array<float>, array<string>, array<color>]`, e.g. `[o, h, l, c] = request.security_lower_tf(…, [open, high, low, close])` |
| contents | "all available intrabars in each chart bar", one element per intrabar, "sorted in ascending order based on each intrabar's timestamp" |
| empty | a chart bar without accessible intrabar data → **empty array**; missing intrabars (no trades in an interval) → a shorter array |
| expression context | evaluated in the intrabar context, series state continuous across intrabars (the manual's `ta.change(close)` intrabar sum equals the chart bar's `ta.change(close)`) |
| expression restrictions | "excluding direct references to collections and mutable variables" |
| timeframe | lower than **or equal to** the chart timeframe; higher → runtime error, or "na results" with `ignore_invalid_timeframe = true` |
| history limit | the most recent 100K intrabars (Basic … Premium), 125K (Expert), 200K (Ultimate); `calc_bars_count` limits further; older chart bars get empty arrays |
| call limits | 40 unique `request.*()` calls (64 Ultimate); ≤ 127 tuple elements across all requests |
| realtime | intrabar data on realtime bars may repaint after a restart (separate historical / realtime feeds) |
| v5 / v6 | no function-specific change in the v6 migration guide |

## 2. Real TradingView observations — `manual/m06_live_lower_tf.pine` (v6)

Run by the user on BINANCE:BTCUSDT, **15-minute** chart (the script's header suggests 5 minutes; the observed
`n=15` for a confirmed bar confirms a 15-minute chart), 1-minute intrabars.

| id | observation |
|---|---|
| R1 realtime | during realtime executions: `n=10 first=0 last=9 formingMin=9 lastIsForming=T lastEqClose=T`; over the 3 realtime executions observed, `lastIsForming` and `lastEqClose` were true in 3 / 3 |
| R1 confirmed bar | previous (confirmed) bar: `n=15 first=0 last=14` |
| same timeframe | `"15"` on the 15-minute chart: `n=1 lastEqClose=T` |
| R2 | `ignore_invalid_timeframe = true` with a higher timeframe (3 × the chart's): **`na array`** |

Established:

1. On the realtime chart bar the array holds every intrabar of the bar so far **including the still-forming one**
   as the last element; its value updates with every realtime execution (`last == close` on every tick).
2. A confirmed chart bar holds all its completed intrabars, first at offset 0.
3. The same timeframe returns a one-element array holding the chart bar's own value.
4. An invalid higher timeframe with `ignore_invalid_timeframe = true` returns an **`na` array**, not an empty array.

The second screenshot (after changing the input) was a recalculation (`isrealtime F`, 0 realtime executions);
it does not replace R1.

### q7 — non-dividing lower timeframe (`quick/q7_lower_tf_straddle.pine`, v6, observed)

BINANCE:BTCUSDT, 15-minute chart, `request.security_lower_tf(…, "10", [time, time_close])`. Offsets are minutes
from each chart bar's open; the pattern repeated on every observed row (18:30 … 20:15):

| chart bar | n | intrabar opens | intrabar closes |
|---|---|---|---|
| hh:00 / hh:30 | 1 | 0 | 10 |
| hh:15 / hh:45 | 2 | -5, 5 | 5, 15 |

Established: an intrabar belongs to the chart bar in which it **closes**: `chart_open < intrabar_close ≤
chart_close`. The 10-minute intrabar 20:10–20:20 opens inside the 20:00 bar but belongs to the 20:15 bar; an
intrabar closing exactly at a chart bar's close belongs to that chart bar. (The open-time rule proposed
earlier is **wrong**.)

## 3. Semantic model (frozen for A4)

**M1 Contexts.** A lower-timeframe call owns a P2.1 context: a child `Runtime` runs the call's dependency slice
plus the expression over the requested (intrabar) bars and captures one value per intrabar. Series state
(`ta.*`, `var`, history) runs continuously across intrabars and chart bars.

**M2 Mapping algorithm (q7).** Intrabars are assigned to chart bars by close time: intrabar *k* belongs to chart
bar *i* when `open_i < close_k ≤ close_i`. The contiguous range is found with two binary searches on the intrabar
close times (first `close_k > open_i`, last `close_k ≤ close_i`) and returned in time order. This covers
dividing and non-dividing lower timeframes alike; no divisibility restriction.

**M3 Same timeframe.** One intrabar per chart bar → a one-element array (observed).

**M4 Empty.** A valid request with no intrabars in the chart bar (before the first available intrabar, data
gaps, sessions, beyond the history limit) → an **empty array** (documented).

**M5 na.** A higher timeframe → runtime error by default; with `ignore_invalid_timeframe = true` → an **`na`
array** (R2), and a tuple of `na` arrays for a tuple expression (engine inference from R2). Empty and `na` stay
distinct: `array.size()` of an empty array is 0, of an `na` array the A1 na-array error.

**M6 Tuples.** A tuple expression returns a tuple of arrays, one per element, all with the same length for a
given chart bar (one entry per intrabar). The ≤ 127 tuple-element limit is counted across all requests.

**M7 Array integration (A1).** Every chart-bar execution builds **new execution-local `PineArray`s** from the
captured values. A1 applies unchanged: slots snapshot them at the end of the execution; `ltf[1]` is the previous
bar's read-only copy (RE10051 on mutation); mutating a returned array changes only this execution's object;
`for … in` (A2) and method syntax (A3) work on them.

**M8 Historical run.** Each confirmed chart bar gets its completed intrabars (R1, documented).

**M9 Realtime / Live (received data only — engine policy + R1).** The forming chart bar's array holds the
completed intrabars of the bar received so far, then the **forming received intrabar as the last element**,
rebuilt on every tick. Only bars actually received by this terminal appear:

* completed intrabars: the provider's completed bars (close ≤ now);
* forming intrabar: **Exness** — the MT5 live snapshot already carries received M15/M30/H1 bars; **Binance** — a
  public kline stream at the requested interval (read-only market data, no authentication), subscribed while the
  request is active. Without a received forming intrabar the array ends at the last completed one (a documented
  difference, never a fetched or synthesised value).

Each tick rolls back and re-runs the forming chart bar (P1); the context re-runs only the forming intrabar.
Ownership stays by close time on the forming bar too (a forming intrabar that will close after the chart bar's
close belongs to the next chart bar). That combination (realtime + non-dividing) was not observed separately; it
is an **inference from R1 + q7**.

**M10 Replay (knowable at cursor — engine policy).** At cursor T only intrabars with `close ≤ T` are used (the
provider cut-off, the context and the payload validator's `max_source_time ≤ T` check, as in P2.1). Because
ownership is by close time (q7), a revealed chart bar owns exactly the intrabars closed by its close, so Replay and
the historical run agree, for non-dividing timeframes too; no later intrabar can leak.

**M11 Expression restrictions.** As documented: no collections (existing slicing rule) and no direct references
to mutable variables (`var`/`varip` or reassigned with `:=`) in the expression → compile error. P2.1 slice rules
otherwise (OHLCV, arithmetic, `ta.*`, history, tuples, supported user functions).

**M12 Arguments.** `gaps` / `lookahead` are not parameters of this function (compile error, as for any unknown
argument). `currency` → not implemented (as P2.1). `ignore_invalid_symbol` as P2.1. `calc_bars_count` limits the
intrabars requested (the most recent ones).

## 4. Source / data authority (engine policy, P2.1 unchanged)

| chart | requested lower timeframe | source |
|---|---|---|
| Binance | a native interval (1m, 3m, 5m, 15m, 30m, 1h …) | public USD-M klines (read-only) |
| Binance | a custom interval (e.g. 10m) | aggregated from a dividing native Binance interval (existing rule; must divide the day) |
| Exness | M15 (BTCUSDm, XAUUSDm), M30 (BTCUSDm native; XAUUSDm aggregated from M15), H1 | authoritative Exness datasets only |
| Exness | anything below M15 | **explicit missing-source error — never Binance** |
| either | the other family | rejected (cross-family rule) |

So on Exness charts (15m/30m/1h) the useful requests are `"15"` on 30m/1h, `"30"` on 1h and the chart's own
timeframe. Pine on Binance charts stays visual only; it never feeds the Exness signal authority.

## 5. Limits

| limit | TradingView | this engine |
|---|---|---|
| intrabars per request | 100K–200K (plan), `calc_bars_count` | **engine limitation:** `MAX_BARS_PER_CONTEXT` = 10,000 (and `calc_bars_count` when smaller). Older chart bars get empty arrays, as TradingView does beyond its own limit. The Binance fetch per lower-timeframe context must be raised from 3,000 toward it. |
| request calls | 40 unique (64 Ultimate) | existing engine limit: 16 contexts per script (P2.1) |
| tuple elements | 127 | same limit, enforced at analysis time |
| nesting | — | P2.1 depth limit (2) |

## 6. Diagnostics

* compile: collection or mutable-variable reference in the expression; `gaps`/`lookahead` arguments; a literal
  cross-family symbol; tuple limit;
* runtime: higher timeframe without `ignore_invalid_timeframe` (engine wording; TradingView's text not
  captured); missing Exness source; dynamic cross-family symbol; engine limits (explicit "Current Pine engine
  limit" messages).

## 7. Compatibility gaps after A4

Seconds / tick / range timeframes; `currency`; UDT-wrapped collections
(P2.5); intrabar history beyond 10,000 bars; Exness timeframes below M15 (no authoritative data); TradingView's
exact error texts.

## 8. Live validation status (handoff)

**NOT YET REAL-LIVE VERIFIED:**

* the Binance lower-interval kline stream (`BinanceHub.lower_kline`, `providers.lower_tf_received`) in an actual
  Live terminal session;
* the Exness lower-timeframe MT5 snapshot path (`providers.lower_tf_received`, received M15/M30/H1 bars) in an
  actual Live terminal session.

Both paths are covered by fake-stream and synthetic-MT5-feed tests (`test_lower_tf.py`). This is not a blocker
for the A4 implementation checkpoint, but it **is** a blocker for declaring P2.2 live integration fully validated:
both must be exercised in a real Live session before the final P2.2 tag.

## 9. Oracle scripts

| script | status | sha256 |
|---|---|---|
| `manual/m06_live_lower_tf.pine` | run (R1, R2) | `1d68988c1ea287441461fae8ea9f68f67450fe13baadb25c88341abd6341b3a2` |
| `quick/q7_lower_tf_straddle.pine` | run (close-time ownership) | `7fe1baed3ac2c72bc166e4511b6c77a41423168bc481f704b01dbe7235211b9a` |
