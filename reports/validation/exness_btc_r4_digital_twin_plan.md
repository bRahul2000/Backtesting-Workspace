# R4 — MT5 digital-twin implementation plan

**Scope of this document: a plan only.** No strategy logic was converted into a live bot, no
stash was restored, and no new executable component was added. Converting the frozen Core
into a trading EA is a separate, explicitly authorized task.

**Goal.** Make the Python backtester and an Exness MT5 demo produce *comparable, auditable
decision streams* for the frozen `BTC_V3_CORE_V1_FROZEN`, so that any divergence can be
attributed to feed, execution or implementation rather than guessed at.

---

## 1. Inventory of existing infrastructure

| Component | Path | State |
|---|---|---|
| **MT5 EA — Setup A V1** | `mt5/BTC_Setup_A_V1.mq5` | Present, complete, frozen research EA. **Not the V3 Core.** |
| Parity rule map | `mt5/PARITY_RULE_MAP.md` | Present |
| MT5 operator README | `mt5/README.md` | Present — copy/compile, audit mode, Strategy Tester checks |
| Validation checklist | `mt5/VALIDATION_CHECKLIST.md` | Present — gates before demo orders |
| **Historical parity comparator** | `tools/compare_mt5_setup_a.py` | Present, Setup-A-specific. No timestamp/direction tolerance; price tolerance 1 point ($0.01) |
| Live bridge contract | `docs/mt5_live_bridge.md` | Present — read-only, explicit security boundary |
| Live feed provider | `services/live_chart_source.py` | Present — `UnconnectedMT5Feed` returns an explicit not-connected state |
| **`bridge/` package source** | `bridge/` | **ABSENT.** Only `__pycache__/` survives (`mt5_live_bridge`, `snapshot`, `__init__`) |
| WIP stash | `stash@{0}` | `docs/mt5_live_bridge.md`, `services/live_chart_source.py`, `ui/live_chart.py`. **Not restored, as instructed.** |
| Spec exporter | `mt5/Export_BTCUSD_Spec.mq5` | Added and used in R1 |
| History exporter | `mt5/Export_BTCUSD_History.mq5` | Added and used in R1 |

### What the Setup A EA already solves (reusable patterns)

- **Two-mode safety.** `enum EA_MODE { AUDIT_ONLY=0, DEMO_TRADE=1 }`, defaulting to
  `AUDIT_ONLY`. Audit mode maintains a paper order/position and never calls `OrderSend`.
- **Magic number.** `InpMagicNumber = 515010220`, stamped on every order and every log row.
- **Order logging.** `LogRecord(...)` writes a 35-column CSV: `event, event_time, signal_time,
  direction, qualified, reason, ema20, ema50, atr, rsi, adx, plus_di, minus_di, h1_time_utc,
  h1_close, h1_ema50, h1_ema200, h1_ema200_past, signal_price, trigger, stop, target,
  planned_cash_risk, raw_volume, volume, actual_planned_risk, ticket, magic, bid, ask, spread,
  fill_time, fill_price, exit_time, exit_price, pnl, realized_r`.
- **Event vocabulary.** `SIGNAL_EVALUATED, SIGNAL_BLOCKED, ORDER_CREATED, ORDER_BLOCKED,
  ORDER_REJECTED, ORDER_CANCELED, ORDER_EXPIRED, ORDER_FILLED, TARGET_SET, POSITION_CLOSED`.
- **Broker timestamps.** Server time via `TimeTradeServer()`; the R1 capture confirms
  Exness-MT5Trial5 runs at **UTC+0 offset 0**, so server time is directly comparable to the
  backtester's UTC. This must be re-asserted at every run, never assumed.
- **Lot sizing.** Normalized against live `SYMBOL_VOLUME_STEP`, `SYMBOL_VOLUME_MIN`,
  `SYMBOL_VOLUME_MAX` — matching the verified spec (0.01 / 0.01 / 200.0).
- **Pending-order semantics.** `BuyStop`/`SellStop` with `ORDER_TIME_SPECIFIED` and
  `expiry = bar.time + 3 × 900s`, which is the engine's two-completed-bar expiry. The EA
  refuses to run if BTCUSDm does not support specified expiry.
- **SL/TP handling.** Stop sent with the order; target set from the actual fill
  (`TARGET_SET`), matching `engine/execution.py` deriving the 3R target from the fill price.

### The gap

**No V3 Core EA exists.** `BTC_V3_CORE_V1_FROZEN` is a composition of `A4 Pullback Long` and
`T3 Breakout Short`; the only EA in the repository implements Setup A V1. The digital twin
therefore needs a new EA, and `tools/compare_mt5_setup_a.py` needs a Core-shaped sibling.

---

## 2. What R1–R3 already established for R4

| Established | Value for R4 |
|---|---|
| Verified BTCUSDm spec | Lot step, min/max, contract size 1.0 BTC, digits 2, stops level 0, FOK+IOC — the EA can assert against the same recorded values |
| Server offset 0 (UTC+0) | Backtester UTC timestamps are directly comparable to EA server timestamps |
| Real per-bar spread path | `spread_source="BROKER_NATIVE_PER_BAR"` lets the backtester price a demo window the way the broker actually quoted it |
| Feed divergence quantified | ~$15/bar, under 45% signal overlap vs Bitstamp — sets the expectation that a demo will *not* reproduce Bitstamp trades |
| Frozen Core on Exness data | 304 trades, PF 1.072, Avg R +0.056 — the reference the twin must reproduce |

**The single most important R4 consequence of R3:** the twin must be compared against the
**Exness-native backtest**, never against the Bitstamp benchmark. R3 showed those are
different trade populations.

---

## 3. Implementation plan

### Stage 1 — Core decision-log EA in `AUDIT_ONLY` (no orders)

Create `mt5/BTC_V3_Core_V1.mq5`, modelled on `BTC_Setup_A_V1.mq5`:

- Implement A4 Pullback Long and T3 Breakout Short exactly as the frozen Python sources
  define them, with a new `PARITY_RULE_MAP` entry per rule.
- `EA_MODE` defaults to `AUDIT_ONLY`; `DEMO_TRADE` is compile-visible but gated behind the
  validation checklist.
- New magic number (do not reuse 515010220) so Setup A and Core orders never collide.
- Reuse the existing 35-column log schema verbatim, adding a `setup_id` column carrying
  `BTC_V3_A4_PULLBACK_LONG_FROZEN` or `BTC_V3_T3_BREAKOUT_SHORT_FROZEN`, plus a
  `strategy_fingerprint` column stamped with `631374d5…` so a log can never be silently
  matched against a different build.
- Assert at `OnInit`: symbol is BTCUSDm, digits 2, volume step 0.01, stops level 0, specified
  pending expiry supported, and `TimeTradeServer() - TimeGMT() == 0`. Refuse to start otherwise.

**Exit criterion:** the EA runs a Strategy Tester pass over an R1-covered window and emits a
decision log with zero orders sent.

### Stage 2 — Core parity comparator

Create `tools/compare_mt5_core.py`, modelled on `tools/compare_mt5_setup_a.py`:

- Load the EA log and run the frozen Core through `run_universal_backtest` on
  `data/exness/btc/phase_r1/processed/btcusdm_M15.csv` with
  `spread_source="BROKER_NATIVE_PER_BAR"` over the identical window.
- Match on `(signal_time, direction, setup_id)` with **no tolerance on timestamps or
  direction** and a 1-point ($0.01) price tolerance, as the Setup A comparator does.
- Reuse the R3 classification vocabulary — `IDENTICAL`, `FEED_PRICE_DIFFERENCE`,
  `SIGNAL_DIFFERENCE`, `ENTRY_DIFFERENCE`, `EXIT_DIFFERENCE`, `SPREAD_DIFFERENCE`,
  `DATA_GAP_DIFFERENCE` — so R3 and R4 results are directly readable against each other.
- Absence of an EA record is **never** a match.

**Exit criterion:** a signal-level parity report over a Strategy Tester window, with every
non-`IDENTICAL` row explained.

### Stage 3 — Restore a read-only bridge package

`bridge/` source is absent. Rebuild it to the committed contract in `docs/mt5_live_bridge.md`
rather than from the stash:

- `bridge/snapshot.py` — validated `FeedSnapshot`; no forward-fill across gaps; atomic
  temp-file-then-replace publishing.
- `bridge/mt5_live_bridge.py` — read-only publisher of BTCUSDm quotes and completed M15 Bid
  bars. **No order endpoint, no command queue, no credential handling** — the contract's
  security boundary is non-negotiable.
- Wire `services/live_chart_source.py` to consume it, replacing `UnconnectedMT5Feed` only
  when a real snapshot validates.

**Exit criterion:** the Streamlit Live Chart shows a verified live feed with a correct
server-clock offset and an explicit `STALE LIVE FEED` state, and still cannot place an order.

### Stage 4 — Demo digital twin

- Run the Core EA on an Exness **demo** account in `DEMO_TRADE`, after the
  `mt5/VALIDATION_CHECKLIST.md` gates pass.
- Export the demo order history and the EA decision log on a fixed cadence.
- Re-export BTCUSDm M15/H1 for the demo window with `mt5/Export_BTCUSD_History.mq5` and
  re-run R1 ingestion so the backtester replays *the broker's own bars for that window*.
- Run `tools/compare_mt5_core.py` over the demo window: backtester vs live demo.

**Exit criterion:** a rolling twin report giving signal-match rate, fill-price difference
distribution, and a classification of every divergence.

### Stage 5 — Cost truth

Commission, swap, leverage and margin remain **UNVERIFIED** and unmodelled. At the R3
broker-native PF of 1.072 this is decisive, not cosmetic. Resolve from the demo account's own
statement — realized commission and swap per closed position — and only then decide whether
to model them. Do not infer them from the symbol specification.

---

## 4. Sequencing and risk

| Stage | Depends on | Main risk |
|---|---|---|
| 1 Core EA (audit) | R1 spec | Re-implementation drift from the frozen Python rules |
| 2 Comparator | 1 | Silent mismatch masking — mitigated by "absence is never a match" |
| 3 Bridge | contract doc | Scope creep into an order path — mitigated by the security boundary |
| 4 Demo twin | 1, 2, 3 | Demo-vs-live fill differences; demo is not live |
| 5 Cost truth | 4 | Concluding profitability on an unverified cost base |

**Stage 1 is the only one that requires new strategy-shaped code, and it is exactly the work
this task was told not to start.** Stages 2 and 3 are infrastructure and could proceed
independently, but a comparator with no EA to compare against has nothing to validate it, so
Stage 1 should be authorized first.

## 5. Explicit non-goals

- No live-forward validation is claimed today.
- No stash is restored.
- No frozen strategy is modified; A4, T3 and Core hashes stay as recorded.
- No PB4, and no reopening of PB1/PB2/PB3.
- The Streamlit dashboard gains no order endpoint.
