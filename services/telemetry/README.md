# Telemetry V1 — live algo telemetry and daily broker reconciliation

This is Stage 1 of [ROADMAP.md](../../ROADMAP.md), following decisions D006, D010, D011 and D014.

It captures raw facts about a live algo that could be impossible to reconstruct later. Each day it checks them
against MT5's own order and deal history. **Nothing here can place, change or close an order.**

## Architecture

```
MT5 terminal (the VPS)                                   Zoneflow (same machine)
----------------------                                   -----------------------
strategy EA  (unchanged, trades as before)
observer EA  ZoneflowTelemetryObserver ---- spool ---->  ingest     spool -> store (SQLite, append-only)
             . OnTradeTransaction: fills, orders,        reconcile  store vs broker export, per strategy per UTC day
               SL/TP changes                             tracker    14 consecutive PASS days = Stage 1 DONE
             . heartbeat every 60 s, MT5 connection      watchdog   stale heartbeat / MT5 disconnected (report only)
             . daily MT5 history export ---- broker -->  Diagnostics page: small read-only panel
```

**Why a separate observer rather than editing the strategy EA.**

- Every broker fact (fills, orders, SL/TP changes, exit reasons) is visible to any program in the terminal through
  `OnTradeTransaction`. So Telemetry V1 needs **no change to any trading EA**: the entries, exits, sizing, SL/TP,
  timing, signals and state transitions stay byte-for-byte the same.
- A strategy-side include (`mql5/ZoneflowTelemetry.mqh`, "strategy hooks") exists for the facts only the strategy
  knows: signals, requested prices, rejected requests and its own decision state.
- Adding those hooks to an EA is a separate, reviewed change. It follows the protected-EA procedure: back up and hash
  the source, isolate the instrumentation diff, compile, compare tester behaviour, prove the semantics are unchanged,
  and only then deploy.

## Files

| File | What it is |
|---|---|
| `mql5/ZoneflowTelemetry.mqh` | Spool writer: CRC-sealed JSON lines, identity, timestamps, strategy hooks. No trade calls. |
| `mql5/ZoneflowObserverCore.mqh` | Observer logic: transaction capture, heartbeat, connection, daily broker export. |
| `mql5/ZoneflowTelemetryObserver.mq5` | The EA you attach. It is a thin wrapper around the core. |
| `mql5/ZoneflowTelemetry_CompileCheck.mq5` | Script that compiles every hook. When run, it writes `selftest` events and sends nothing. |
| `schema.py` | The event schema, validation and line encoding. |
| `writer.py` | Python twin of the MQL5 writer, used by tests and future Python emitters. |
| `store.py` | Ingestion into an append-only store. Triggers refuse UPDATE and DELETE. |
| `reconcile.py` | Daily reconciliation and correction records. |
| `tracker.py` | The 14-day validation tracker. |
| `watchdog.py` | The heartbeat and connection observer. |
| `__main__.py` | Command line (`python -m services.telemetry ...`). |

## Raw event schema (schema_version 1)

**Line format.** One event is one line: `{"schema_version":1, ... ,"crc32":"xxxxxxxx"}\n`. The CRC-32 covers the exact
UTF-8 bytes before `,"crc32":"`, so a torn or edited line is detected.

**Missing values.** A value that is unknown or not applicable is simply absent (null). It is never guessed.
Unknown fields are refused.

| Group | Fields |
|---|---|
| Identity | `schema_version`, `telemetry_event_id` (`writer:run:sequence`, unique), `writer_id`, `writer_run_id` (new each program start), `sequence` (1, 2, 3 …; a gap means an unwritten event), `event_type`, `capture_mode` (`realtime` = observer, `strategy` = strategy hook) |
| Strategy | `strategy_id`, `strategy_version`, `strategy_parameters_hash` |
| Account | `broker` (ACCOUNT_COMPANY), `account_server`, `account_environment` (demo/real/contest), `account_ref` (first 16 hex characters of SHA-256 of login and server; **the login itself is never written**) |
| Instrument | `symbol`, `magic_number` |
| Broker ids | `order_id`, `ticket_id`, `deal_id`, `position_id` (where available) |
| Time (UTC ISO-8601, `Z`) | `signal_utc`, `request_utc`, `broker_time_server` (the broker clock, as reported), `server_utc_offset_s`, `broker_utc` and `fill_utc` (milliseconds, from DEAL/ORDER `TIME_MSC`), `local_capture_utc` (whole seconds, from `TimeGMT()`) |
| Trade | `direction` (buy/sell; for fills, the deal's own side), `deal_entry` (in/out/inout/out_by), `signal_price`, `requested_price`, `fill_price`, `bid`, `ask`, `spread_points` (the quote **at capture time**, not at the fill), `requested_volume`, `filled_volume`, `stop_loss`, `take_profit` |
| Outcome | `broker_return_code` (MqlTradeResult.retcode), `broker_error_code` (GetLastError), `exit_reason` (sl/tp/stop_out/client/mobile/web/expert/…, straight from MT5 `DEAL_REASON`), `raw_error_code`, `message` |
| Objects | `runtime` (heartbeat/start/stop facts: status, connection, trade permission, ping, counters), `strategy_state` (**optional, explicitly the strategy's own decision state**) |

**Event types:**

- `ea_started`, `ea_stopped`, `heartbeat`
- `signal_generated`
- `order_requested`, `order_accepted`, `order_rejected`, `order_cancelled`, `order_expired`
- `position_opened`, `position_modified`, `exit_requested`, `position_closed`
- `broker_disconnect`, `broker_reconnect`
- `error`

**Never raw truth.** `regime`, `market_regime`, `trend_regime`, `volatility_regime`, `session`, `mfe`, `mae`,
`r_multiple`, `trade_quality` and `setup_quality` are refused as fields (D011).

## Where things live

| What | Windows VPS | Written by |
|---|---|---|
| Spool | `%APPDATA%\MetaQuotes\Terminal\Common\Files\Zoneflow\telemetry\spool\<writer>\<YYYY-MM-DD>.jsonl` (MT5 user) | MT5 only (append) |
| Broker export | `...\Common\Files\Zoneflow\telemetry\broker\<account_ref>\<YYYY-MM-DD>.json` | the observer, once per day, never replaced |
| Store | `C:\ZoneflowData\telemetry\store\telemetry.sqlite3` | ingestion (append-only) |
| Daily results | `C:\ZoneflowData\telemetry\reconciliation\<YYYY-MM-DD>.json`, `runs.jsonl`, `SUMMARY.md`, `summary.json` | daily job |
| Watchdog | `C:\ZoneflowData\telemetry\watchdog\status.json`, `events.jsonl` | watchdog job |
| Strategy map | `C:\ZoneflowData\telemetry\strategies.json` (template: `deployment/telemetry-strategies.example.json`) | Rahul |
| Validation start | `C:\ZoneflowData\telemetry\validation.json` | `start-validation`, once |

The MT5 folder comes from `TV_MT5_COMMON_FILES`, or from `ZONEFLOW_TELEMETRY_SPOOL` for the telemetry folder
directly. The store location is `ZONEFLOW_TELEMETRY_ROOT`. None of this is in Git.

## Reliability rules

- **The EA writes locally first.** It opens, appends, flushes and closes on every event. If Zoneflow, the internet or
  the consumer is down, lines simply accumulate and are ingested later.
- **A write failure never affects trading.** It is counted (`write_failures` in the heartbeat) and shows up as a gap
  in `sequence`.
- **Partial writes are recovered safely.**
  - A torn last line (a crash mid-write) is left alone until it can be judged.
  - The writer seals it with a newline before its next event.
  - Ingestion keeps the torn bytes as a *defect* and salvages any complete event joined onto it.
  - Nothing is invented.
- **Ingestion is idempotent.** The new lines and the new read offset are committed together. Re-reading the same bytes
  adds nothing. The same id arriving with different bytes is kept as a *conflict*, never an overwrite. A spool file
  that shrinks or changes is flagged and not re-read.
- **Raw telemetry is never rewritten.** Every discrepancy produces a separate correction record, holding the
  telemetry view next to the broker view. It only stops counting against the day when an explanation names it
  exactly (`explain`). Explanations are append-only too.

## Daily reconciliation

For each strategy (from `strategies.json`: magic numbers and optional symbols) and each finished UTC day, the job
compares:

- **Counts:** fills from telemetry against MT5 deals, by `deal_id`.
- **Fill details:** price (within half a point), volume, broker time (to the millisecond), symbol, magic, order id,
  position id, side, entry/exit and factual exit reason.
- **Orders** placed that day.
- **Positions.**
- **Heartbeat coverage:** a gap of more than 180 s is flagged.
- **Spool defects** and **id conflicts.**

Result fields include `broker_deal_count`, `telemetry_deal_count`, `matched_count`, `missing_from_telemetry`,
`unmatched_telemetry`, `duplicate_telemetry`, `price_mismatches`, `volume_mismatches`, `timestamp_mismatches`,
`field_mismatches`, `missing_orders`, `telemetry_gaps`, `status` and `reasons`.

Status:

- **PASS** means everything agrees or is explicitly explained.
- **FAIL** means at least one unexplained discrepancy.
- **INCOMPLETE** means the day is not over, the broker export is missing, or no strategy is configured.

Rerunning gives byte-identical results; the run times go to `runs.jsonl`, together with whether the run was late.

**The 14-day tracker.**

- Days are numbered from the validation start.
- A finished day with no result is **MISSED**: the job did not run. It breaks the run, just like a FAIL.
- For 48 hours after it ends, an unsettled day shows as **PENDING**, because its export may still be arriving.
- A day reconciled after its due time is marked *late*.
- If the daily job has not run for 26 hours, the tracker shows **OVERDUE**.

## Commands

The Windows scheduled tasks run these through `deployment/windows/run-telemetry.ps1`:

```
python -m services.telemetry daily                          # ingest + reconcile finished days + tracker + watchdog
python -m services.telemetry reconcile --date 2026-10-05    # (re)check one day
python -m services.telemetry tracker
python -m services.telemetry watchdog
python -m services.telemetry start-validation --date 2026-10-05
python -m services.telemetry explain --date 2026-10-05 --strategy btc_x --kind telemetry_gaps \
       --key "observer.btc_x@2026-10-05T02:00:00Z" --text "planned VPS reboot"
```

The tasks are registered by `deployment/windows/Register-ZoneflowTelemetry.ps1`, which `Install-Zoneflow.ps1` also
runs:

- **`Zoneflow-Telemetry-Daily`** runs at 00:45 UTC, and runs when the server is next available if it was off at that
  time.
- **`Zoneflow-Telemetry-Watchdog`** runs every 5 minutes.

## Known limits (V1)

- **Rejected requests.** A request the broker rejects creates no order. MT5 tells only the program that sent it, so
  the observer cannot see it; the Strategy Tester run confirmed this. Rejections, signals and requested prices come
  only from the strategy hooks.
- **`bid`/`ask`** are the quote the writer saw when it captured the event, not the quote at the fill. Slippage is
  derived later from `requested_price` against `fill_price`.
- **Heartbeats** prove the observer and terminal were alive and connected. They do not prove the strategy EA was
  attached. Strategy liveness needs the strategy hooks (a strategy heartbeat).
- **`local_capture_utc`** has whole-second precision (`TimeGMT()`). Broker times have milliseconds.
- **Timer events** are simulated in the Strategy Tester. Heartbeat regularity on the live terminal is exactly what the
  14-day validation measures.

## Evidence so far (2026-09-30)

Both programs compile in MetaEditor (build 6230) with **0 errors and 0 warnings**:
`ZoneflowTelemetryObserver.mq5` and `ZoneflowTelemetry_CompileCheck.mq5`.

In the MT5 Strategy Tester, on BTCUSDm M15, 2026-09-21 to 2026-09-23, on the demo server, the observer core ran
beside a tester-only toy trader (never committed; it refuses to run outside the tester). The results:

- 4,447 real MQL5 lines were written, and every one passed the CRC and schema checks.
- Reconciliation of 2026-09-21 and 2026-09-22 against the observer's own MT5 history export: **PASS** both days.
  - Fills: 16 of 16 deals matched (8 entry, 8 exit) on price, volume, millisecond time, side and exit reason.
  - Orders: 21 of 21 matched.
  - Heartbeats: 1,440 a day, with no gaps.
- The first run found a real defect, now fixed: a market order filled instantly is not reported by MT5 as "added",
  so its acceptance was missing. The observer now records acceptance the first time the order appears in history.

A 60-line sample of that output (account reference blanked, CRC resealed) is kept in `tests/fixtures/telemetry/`.
