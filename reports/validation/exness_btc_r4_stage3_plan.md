# R4 Stage 3 — live forward shadow validation

Stage 2 proved the MQL5 twin reproduces the frozen BTC Core exactly on recorded
history: two certified windows, 14,388 bars, zero mismatches. Stage 3 proves it
on bars that did not exist when the code was written, and on the operational
events a Strategy Tester run can never produce — restarts, reconnects, tick
outages, back-filled bars.

**Nothing in Stage 3 sends a broker order.** `AUDIT_ONLY` remains the default,
`SendOrderGuard` refuses unconditionally, DEMO_EXECUTION is not enabled, and no
order-transmission call exists anywhere in the EA or the tooling.

## Architecture

```
MetaTrader (live BTCUSDm M15 chart)
  BTC_V3_Core_V1.mq5, AUDIT_ONLY
      ├── btc_core_v1_audit.csv     76-column audit, Stage 2 schema, append-only
      ├── btc_core_v1_session.csv   run identity, anchor, restart/reconnect counts
      └── btc_core_v1_events.csv    operational event log
                    │  ./scripts/stage3 collect
                    ▼
data/exness/btc/stage3/            (+ archive/ — every collection kept)
                    │  python -m tools.stage3 compare
                    ▼
frozen Python Core over the same bars ──► tools/compare_mt5_core.compare
                    │                      (Stage 2 comparator, unchanged)
                    ▼
reports/validation/stage3_evidence_ledger.jsonl   append-only
```

The 76-column audit schema is untouched. Stage 3 runtime metadata lives in two
separate versioned files, so a Stage 2 audit and a Stage 3 audit are the same
kind of artifact and the same comparator reads both.

## Safety model

| Property | How it is enforced |
|---|---|
| Default `AUDIT_ONLY` | `input ExecutionMode InpMode = AUDIT_ONLY`, static check `default_mode_is_audit_only` |
| No order transmission | `SendOrderGuard` refuses unconditionally; static check scans code (not comments) for `OrderSend`, `OrderSendAsync`, `PositionOpen`, `PositionClose`, `OrderModify`, `OrderDelete`, `CTrade`, `trade.Buy`, `trade.Sell` |
| Tooling cannot send either | test asserts none of those tokens appear in `tools/stage3*.py` |
| Mode is verified from evidence | the session file records the mode; `check_environment` blocks anything but `AUDIT_ONLY` |
| Frozen logic unchanged | all seven protected fingerprints asserted; the EA stamps A4/T3/Core hashes into the session file and the collector rejects a mismatch |

DEMO_EXECUTION remains declared but unimplemented, and refuses.

## Startup

The EA detects the Strategy Tester (`MQLInfoInteger(MQL_TESTER)`) and keeps the
exact Stage 2 behaviour there, so the certified windows stay reproducible bar
for bar. Live, it takes the Stage 3 path.

On a live start the EA:

1. reads the session file, recovering the **anchor** and the counters;
2. fixes the anchor on first start only — the deepest available M15 bar within
   `InpMaxReplayBars`;
3. opens the audit log in append mode (a live restart must never truncate
   forward evidence);
4. scans the audit log for the last bar already written;
5. replays every closed bar from the anchor forward, writing only bars newer
   than that last one;
6. writes the session file and logs `SESSION_START` or `RESTART`.

## Persistence and recovery

**Recovery is deterministic replay from a fixed anchor. No strategy state is
ever serialised.**

This was chosen over checkpointing deliberately. A checkpoint has to be written,
versioned, validated and kept in step with every change to the strategy state;
if it is stale, truncated, or written by a different build, the EA restores a
lie and the twin diverges silently. Replayed state cannot be stale, because it
is produced by running the same bars through the same code that produced it the
first time. State after recovery is identical to an uninterrupted run *by
construction* rather than by agreement with a file format.

Only two facts persist:

| Fact | Why it must survive |
|---|---|
| `anchor_utc` | every decision boundary, including the 204-hour warmup and the first search time, is derived from it. If the anchor moved, decisions would move. |
| `last_logged_bar_utc` | makes emission exactly-once, so a replayed bar rebuilds state without writing a second row. |

`tests/test_stage3_forward.py::test_replay_from_a_fixed_anchor_is_deterministic`
tests the claim the model rests on, on real Exness bars: two runs sharing an
anchor but ending at different times must agree on every one of the 76 columns
for every bar they share, including carried pullback state, the order lifecycle
and the simulated position.

If the anchor cannot be reached within `InpMaxReplayBars`, the EA **halts** and
logs `ANCHOR_UNREACHABLE` rather than quietly replaying from somewhere else.

### What recovery prevents

| Risk | Mechanism |
|---|---|
| duplicate processing | `bar.time == g_last_processed` is refused, counted, and logged as `DUPLICATE_BAR` |
| duplicate rows | emission is gated on `bar.time > g_last_logged` |
| duplicate pending creation | the pending order is part of replayed state, so a restart rebuilds the same one rather than creating a second |
| phantom fills | fills are derived from bars, not remembered; a replay re-derives exactly the same fill |
| lost state | replay rebuilds all of it |
| stale pending state | nothing is restored from a file, so nothing can be stale |
| daily counter corruption | `trades_today` is re-derived from the replayed bars and the day rollover |
| session-state corruption | the session file holds no strategy state at all |

### Bar scheduling

`ProcessPendingBars()` consumes **every** closed bar not yet processed,
oldest-first, and never shift 0 (the forming bar). It replaced a rule that
processed exactly one bar per new-bar tick, which had three live defects:

* the first closed bar after an attach was silently dropped;
* bars that closed while the terminal was down were dropped, and the resulting
  discontinuity was then mistaken for a data gap, resetting 204 hours of warmup;
* a restart could not back-fill at all.

Bars genuinely absent from broker history remain a real gap and still reset
state, exactly as in Stage 2 — that path is already certified by window 2.

## Reconnect model

`PollConnectivity()` watches `TERMINAL_CONNECTED` and the time since the last
tick. Transitions are recorded as `DISCONNECT` / `RECONNECT`, and a silence
longer than `InpTickOutageSecs` (default 900s) as `TICK_OUTAGE` /
`TICK_RESUMED`. Reconnection needs no special handling beyond this: whatever
bars closed during the outage are back-filled by the ordinary scheduler on the
next tick.

## Forward Python side

`python -m tools.stage3 compare` drives the **real frozen Core** through
`tools/export_python_core_audit.py` over the same anchor-to-last-bar span, then
hands both audits to the unchanged Stage 2 comparator. Tolerances are untouched:
`EXACT_TOLERANCE = 1e-09`, `INDICATOR_TOLERANCE = 1e-06`, `ROUNDING_TOLERANCE =
0.01` as a label only.

Two modes:

| Mode | Python input | Detects |
|---|---|---|
| `FULL` (`--market <fresh export>`) | an independent fresh broker M15 export | market-data *and* decision divergence |
| `LOGIC_ONLY` (no `--market`) | the market columns of the MT5 audit itself | decision divergence only — it cannot detect a data error, and says so on every run |

`LOGIC_ONLY` exists so parity can be checked daily without a manual export.
Certification requires `FULL`.

The comparator reports every dimension Stage 2 reports — OHLC, spread, H1,
indicators, carried state, A4 context and signal, T3 context and signal, signal,
pending lifecycle, entry, stop/target, exit, realized R, full trades — plus the
earliest causal mismatch.

## Evidence ledger

`reports/validation/stage3_evidence_ledger.jsonl`, append-only. Every comparison
records the window, the session identity, SHA-256 of all four artifacts, the
integrity report, event counts, forward lifecycle counts, the full parity
result, and any issues. Historical entries are never rewritten.

`./scripts/stage3 collect` also archives the previous copy of every evidence
file under `data/exness/btc/stage3/archive/` before replacing it.

## Failure conditions

`check_environment`, `check_audit` and `summarise_events` classify each as
BLOCKING or WARNING. BLOCKING refuses to compare at all.

| Condition | Severity |
|---|---|
| stale or wrong EA build (any of the three fingerprints) | BLOCKING |
| mode is not `AUDIT_ONLY` | BLOCKING |
| wrong symbol / digits / point | BLOCKING |
| non-UTC server clock | BLOCKING |
| EA-reported duplicate or reversed bars | BLOCKING |
| duplicate closed bar in the audit | BLOCKING |
| time reversal in the audit | BLOCKING |
| `ANCHOR_UNREACHABLE` | BLOCKING |
| audit schema mismatch / corruption | BLOCKING |
| missing session file | BLOCKING |
| internal gap in the audit | WARNING |
| session/audit skew | WARNING |
| unknown session schema version | WARNING |
| disconnects, tick outages, data gaps, back-fills | recorded, not penalised |

Nothing is auto-repaired. A failed run cannot be made to look clean by the
tooling.

## Certification gate

Evidence gates, not elapsed time. Two categories, kept apart on purpose.

**MUST — twin correctness. A failure here is a defect.**

* no blocking issues
* no duplicate closed bars, no time reversals
* no EA scheduler anomaly
* a parity comparison has been run
* zero unexplained decision mismatches
* full parity on the compared span
* every forward bar compared
* mode is `AUDIT_ONLY`
* zero broker orders transmitted

**OBSERVED — market-dependent. A gap here is a coverage limit, not a defect.**

* forward bars ≥ 1,000 (about 10.5 days of 24/7 M15)
* forward signals ≥ 3
* pending lifecycles ≥ 3
* simulated fills ≥ 1
* at least one completed simulated trade
* controlled restarts ≥ 1
* reconnect events ≥ 1

If a lifecycle does not occur naturally in the window, the gate reports
`AWAITING EVIDENCE` and names what is missing. **Signals are never induced to
satisfy a gate.** A rare path that never occurs is reported as a coverage
limitation, exactly as the T3 cancellation path was in Stage 2 — it has never
fired in 2.9 years of real data, and nothing was done to make it fire.

## Transition gate into Stage 4

Stage 4 (demo execution) may be proposed only when **all** of the following hold:

1. Stage 3 gate reads `READY TO CERTIFY` on a `FULL`-mode comparison.
2. At least one `FULL` comparison used an independent fresh broker export.
3. The evidence ledger contains at least two collection periods separated by a
   controlled restart, both at full parity.
4. Zero broker orders transmitted, confirmed by the forbidden-call scan and by
   the account showing no order history for the session.
5. Broker cost fields are still `UNVERIFIED` — Stage 4 is where they stop being.
6. A separate explicit authorization to enable DEMO_EXECUTION. It is not implied
   by Stage 3 passing.

Stage 3 passing proves the twin is faithful. It does not prove the strategy is
worth trading, and it is not a validation result.
