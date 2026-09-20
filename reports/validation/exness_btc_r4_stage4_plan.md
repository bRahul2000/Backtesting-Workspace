# R4 Stage 4 — demo execution, and Stage 5 — forward monitoring

Stage 4 is the first stage that could place an order. **It cannot today.** The
transmission call does not exist anywhere in the codebase, and a static check
requires it to stay absent.

## The safety decision

A gated `OrderSend` is one edited condition away from firing. An absent one is
not. So `mt5/BTC_V3_Stage4_Demo.mqh` contains every gate, validation,
normalisation, ownership and reconciliation hook a demo order needs — and no
send call. `Stage4Transmit()` evaluates all eight gates, validates the order,
checks for a duplicate, and then refuses:

```
STAGE 4 REFUSED (TRANSMISSION_NOT_IMPLEMENTED): every gate passed, but order
transmission is not implemented. Enabling it is a separate authorised change.
```

Activating Stage 4 means adding one call at the marked site, in a reviewed
commit carrying explicit authorisation. Everything around it is already written
and tested. The EA does not yet `#include` this file, so the layer is
unreachable as well as inert — a static check asserts that too.

`OrderCheck()` **is** used, for margin and request validation. It validates
without transmitting and is the strongest pre-flight that is not a send.

## Architecture

```
mt5/BTC_V3_Stage4_Demo.mqh      gates, validation, normalisation, ownership,
                                retcode policy, refusing transmit stub
tools/stage4_execution.py       the eight gates mirrored and testable,
                                twin-vs-broker reconciliation, append-only ledger
tools/stage5_monitor.py         execution quality, slippage, drawdown, streaks,
                                weekly summaries, readiness verdict
tools/stage4.py                 gate / status / reconcile / readiness
data/exness/btc/stage4/         btc_core_v1_executions.csv (26 columns)
reports/validation/stage4_execution_ledger.jsonl   append-only
```

The execution log is separate from the 76-column audit on purpose: the audit
records what the strategy **decided**, the execution log records what the broker
**did**. Reconciliation is the comparison of the two.

## The eight activation gates

All must pass; the first failure is reported so a refusal names one cause.
Evaluated in the same order in both halves, which a test enforces.

| # | Gate | Refusal code |
|---|---|---|
| 1 | `InpMode == DEMO_EXECUTION` | `MODE_NOT_DEMO_EXECUTION` |
| 2 | `ACCOUNT_TRADE_MODE == ACCOUNT_TRADE_MODE_DEMO` | `ACCOUNT_NOT_DEMO` |
| 3 | symbol is `BTCUSDm` | `SYMBOL_NOT_BTCUSDM` |
| 4 | broker and server match the recorded fingerprint | `BROKER_FINGERPRINT_MISMATCH` |
| 5 | Stage 3 certificate present | `STAGE3_CERTIFICATE_ABSENT` |
| 6 | certificate reports zero unresolved issues | `STAGE3_ISSUES_UNRESOLVED` |
| 7 | operator typed `I AUTHORISE EXNESS DEMO EXECUTION` exactly | `OPERATOR_ACKNOWLEDGEMENT_ABSENT` |
| 8 | running build matches the certified build | `STALE_BUILD` |

Gate 2 is the one that matters most: a real account can never pass. An
unreadable certificate certifies nothing and is treated as unresolved.

## Execution model

Frozen Core semantics are unchanged: stop-entry pending orders, structural stop,
fixed 3R target, one position at a time.

* **Volume** — risk budget ÷ stop distance, capped by leverage, rounded **down**
  to the broker's volume step, refused below the minimum, clipped at the
  maximum. Rounding down because rounding up would exceed the risk budget.
* **Prices** — normalised to tick size and digits.
* **Stops** — must clear `SYMBOL_TRADE_STOPS_LEVEL`, and be on the correct side.
* **Spread** — a submission is refused when the live spread exceeds the
  configured maximum. A fill taken at an abnormal spread is not evidence.
* **Margin** — `OrderCheck()` pre-flight; a failure is classified, not retried
  blindly.
* **Retcodes** — classified into `REQUOTE`, `PRICE_OFF`, `INSUFFICIENT_MARGIN`,
  `INVALID_VOLUME`, `INVALID_STOPS`, `MARKET_CLOSED`, `TRADE_DISABLED`,
  `TIMEOUT`, `OTHER`. Only `REQUOTE` and `TIMEOUT` are retryable: a rejection
  for volume, stops or margin means the request was wrong, and resending it
  unchanged would repeat the error.

## Exactly-once and ownership

Every order carries `STAGE4_MAGIC` (20260921) and a client tag
`S4|<setup_id>|<signal epoch>`. Before building a request the layer asks the
broker whether that tag already exists as an order or a position; if it does,
the submission is refused as `DUPLICATE_SUPPRESSED`. That is what makes a
restart safe: the twin recognises its own work at the broker rather than
remembering it.

`Stage4OrphanCount()` reports broker objects carrying our magic that the twin
does not expect. They are **reported, never auto-closed** — deciding what to do
with one is an operator decision, and silently closing a position to tidy the
books is exactly the kind of automatic repair this project refuses.

## Restart and recovery

Stage 3's model is unchanged: state is rebuilt by deterministic replay from a
fixed anchor. Stage 4 adds one step — after replaying, the twin queries the
broker for orders and positions carrying its magic and reconciles them against
what replay says should exist. Three outcomes:

| Broker | Twin | Action |
|---|---|---|
| order/position with a known tag | expects it | adopt, no new submission |
| nothing | expects an order | submit (subject to every gate) |
| order/position with an unknown tag | expects nothing | report as orphan, do nothing |

## Reconciliation

Per client tag: expected entry vs actual fill (slippage), expected SL/TP vs
broker SL/TP, expected exit vs actual exit, realized PnL and R, commission,
swap, partial fills, duplicate tags. Every difference is reported; none is
absorbed. A run with a duplicate tag or a moved stop is never `clean`.

## Broker cost capture

`commission`, `swap` and `profit` are recorded per close. These are the fields
that have been carried as `UNVERIFIED` since Stage 1 — Stage 4 is where they
stop being estimates and become measurements.

## Stage 4 certification criteria

**MUST** — no duplicate client tags; no SL or TP placement mismatch; no
strategy-versus-broker divergence; commission and swap captured on every close;
zero orders on any non-demo account.

**OBSERVED** — enough completed demo trades for execution quality to mean
anything.

## Stage 5 — forward monitoring

Answers "over enough trades, is this worth deploying?" with counted evidence.

* completed demo trades, target **20 minimum, 30 preferred** — below ~20 the
  slippage distribution is noise and one bad fill dominates every statistic
* slippage distribution including the 95th percentile and worst case, not just
  the mean
* commission and swap totals
* maximum drawdown and longest losing streak
* duplicate and missed-trade checks
* weekly summaries
* strategy-versus-broker divergence count

Verdict is `BLOCKED`, `AWAITING EVIDENCE`, or `READY FOR DEPLOYMENT REVIEW`.
"Ready for review" is not "ready to deploy": it means the evidence is sufficient
for a human to make that decision.

## What is blocked only by Stage 3 certification

Gates 5, 6 and 8 all read the Stage 3 certificate, which does not exist yet.
Everything else — the layer, the tooling, the tests, the ledger — is complete
and running now.

## Activation, when the time comes

1. Stage 3 certifies; the certificate is written to `Common\Files`.
2. A separate authorised commit adds the single transmission call at the marked
   site and `#include`s the layer in the EA.
3. Recompile, attach with `InpMode = DEMO_EXECUTION` and the acknowledgement
   phrase typed exactly.
4. `python -m tools.stage4 gate` must show all eight gates passing first.

Steps 2 and 3 each require explicit authorisation. Neither is implied by Stage 3
passing.
