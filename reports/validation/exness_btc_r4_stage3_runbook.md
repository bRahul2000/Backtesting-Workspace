# R4 Stage 3 — operator runbook

Written for the person running MetaTrader, not for the person who wrote the
code. Every step is either a click in MetaTrader or one command in Terminal.

**The EA never sends an order.** It watches the market and writes down what the
strategy *would* have done. Nothing reaches the broker.

---

## Starting a fresh forward session

Use this when there is no session yet, or when a previous session must be
abandoned (for example it anchored somewhere unusable).

1. In MetaTrader, right-click the chart → **Expert Advisors** → **Remove**.
2. Drag `BTC_V3_Core_V1` back onto the BTCUSDm M15 chart.
3. On the **Inputs** tab set **`InpNewSession` = `true`**. Leave everything else
   alone. Click OK.
4. Read the Journal. You should see three `Rotated …` lines and then a normal
   `SESSION_START`.
5. **Remove the EA and re-attach it with `InpNewSession` back to `false`.**
   Leaving it `true` would rotate the evidence again on every restart.

Nothing is deleted. Each previous file is renamed in place with a UTC stamp and
a `.bak` suffix, in the same `Common\Files` folder.

---

## One-time setup

**1. Copy the EA across.**
Copy `mt5/BTC_V3_Core_V1.mq5` into MetaTrader's Experts folder:
MetaTrader → File → Open Data Folder → `MQL5` → `Experts`.
**Copy it, do not move it.**

**2. Compile it.**
Open it in MetaEditor and press **F7**. Check the `.ex5` file's timestamp
updates. If it does not, MetaTrader is still running the old build and
everything after this is meaningless.

**3. Attach it to a live chart.**
Open a **BTCUSDm M15** chart. Drag `BTC_V3_Core_V1` onto it.
In the dialog, on the **Common** tab, leave *Allow Algo Trading* **unticked** —
the EA does not need it and does not use it.
On the **Inputs** tab, confirm `InpMode` is `AUDIT_ONLY`. Click OK.

**4. Check the Journal (the Experts tab).** You should see:

```
BTC CORE V1 — AUDIT ONLY — NO ORDERS. Fingerprint 631374d5...
Twin build R4-S2-2 warmup+session-reset+DI+risk-budget, compiled <date> ...
Segment start <date> — first signal search at <date>
Stage 3 live forward ready. Session <timestamp>  restarts 0  bars replayed to <bar>
EVENT SESSION_START: anchor <timestamp>, last logged bar , build R4-S2-2 ...
```

If you see `BTC CORE V1 HALTED:` instead, read the reason and stop — do not
work around it.

**5. Confirm the chart corner** shows `BTC CORE V1 — AUDIT ONLY — NO ORDERS`.

Stage 3 is now running. Leave MetaTrader open.

---

## Is it running?

Look at the chart corner. It updates on every new bar with the bar count, the
pending state and the simulated balance.

---

## Routine check (takes about a minute)

In Terminal, from the project folder:

```bash
./scripts/stage3 collect     # copy the evidence out of MetaTrader
./scripts/stage3 check       # is the evidence usable?
./scripts/stage3 compare     # quick parity check (logic only)
./scripts/stage3 status      # where does Stage 3 stand?
```

`status` ends with two lines that are the whole point:

```
PASS / INVESTIGATE  : PASS
CERTIFICATION GATE  : AWAITING EVIDENCE — 2 coverage item(s) not yet observed
```

`PASS` means the twin and the frozen Core agree on every bar so far.
`INVESTIGATE` means stop and read the issues listed above it.

Doing this once a day is plenty.

---

## Full check (do this weekly, and before certifying)

The quick check compares decisions only. The full check also re-reads the market
independently, so it can catch a data problem too.

**In MetaTrader:** open `Export_BTCUSD_History.mq5` in MetaEditor, set
`InpFilePrefix` to `btcusd_stage3`, press **F7**, then run the script on the
BTCUSDm chart. Copy `btcusd_stage3_BTCUSDm_M15.csv` from
File → Open Data Folder → `Common\Files` into `data/exness/btc/stage3/`.

**In Terminal:**

```bash
./scripts/stage3 full data/exness/btc/stage3/btcusd_stage3_BTCUSDm_M15.csv
./scripts/stage3 status
```

---

## Restart test (required for certification — do this once)

1. Run `./scripts/stage3 collect` and note the "bars observed" from `status`.
2. In MetaTrader, right-click the chart → **Expert Advisors** → **Remove**.
3. Wait for at least two M15 bars to close (30 minutes).
4. Drag the EA back onto the same BTCUSDm M15 chart.
5. In the Journal you should see:

```
EVENT RESTART: anchor <same timestamp as before>, last logged bar <recent bar>, build ...
EVENT BACKFILL: N closed bars pending since <bar>
Stage 3 live forward ready. Session <same session id>  restarts 1  ...
```

The **anchor and session id must be unchanged** and `restarts` must have gone
up. That is the recovery working.

6. `./scripts/stage3 collect && ./scripts/stage3 compare && ./scripts/stage3 status`

The bars that closed while the EA was off must now be present, exactly once, and
parity must still be `True`. A full MetaTrader restart, or a machine restart,
tests the same path and counts equally.

---

## Reconnect test (required for certification — do this once)

1. Turn off Wi-Fi (or unplug the network) for two to three minutes.
2. Turn it back on and let MetaTrader reconnect — the connection indicator in
   the bottom-right corner goes green again.
3. Journal should show `EVENT DISCONNECT:` then `EVENT RECONNECT:`.
4. `./scripts/stage3 collect && ./scripts/stage3 status` — `reconnects` ≥ 1.

Do not do this while a bar is closing if you can avoid it; any bars missed are
back-filled anyway, but it keeps the evidence tidier.

---

## Stopping Stage 3

Right-click the chart → Expert Advisors → Remove, or just close MetaTrader.
Run `./scripts/stage3 collect` first so the final bars are captured.

Stopping is safe at any time. Restarting resumes the same session from the same
anchor.

---

## Files you should see

In MetaTrader's `Common\Files`:

| File | What it is |
|---|---|
| `btc_core_v1_audit.csv` | the 76-column bar-by-bar audit, grows by one row per 15 minutes |
| `btc_core_v1_session.csv` | run identity: build, hashes, anchor, restart and reconnect counts |
| `btc_core_v1_events.csv` | one line per restart, reconnect, gap, back-fill |

After `collect`, the same three under `data/exness/btc/stage3/`, with the
previous copies kept in `data/exness/btc/stage3/archive/`.

---

## If something looks wrong

Run `./scripts/stage3 check`. It prints one line per problem, most serious
first, and says `INVESTIGATE` if anything blocks. Send that output — do not
delete or edit any evidence file. A failed run is useful; a tidied-up one is
not.

The two that matter most:

* `STALE_OR_WRONG_BUILD` — MetaTrader is running an old compiled EA. Recompile
  with F7 and confirm the `.ex5` timestamp changes.
* `DUPLICATE_CLOSED_BAR` / `TIME_REVERSAL` — a real defect in the twin. Stop and
  report it.

---

## What certification needs

`./scripts/stage3 status` prints the gate. It needs, on a **full** check:

* about 1,000 forward bars — roughly 10 days of the EA running
* at least 3 signals, 3 pending orders, 1 filled simulated trade, 1 completed one
* the restart test done at least once
* the reconnect test done at least once
* zero mismatches throughout

The market decides when the trade conditions are met. If a signal simply does
not happen in that window, the gate says so and we report it as a coverage
limit — we do not go looking for ways to make one happen.
