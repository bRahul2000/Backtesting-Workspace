# Risk-safeguard audit — MT5 Expert Advisors

- **Date:** 2026-09-30, sources at commit `8008239`.
- **Method:** a read-only code review of every EA source in `mt5/`. The key line references were checked by hand.
- **Changes:** none. No trading behaviour was changed by this audit or by Telemetry V1 (D014, D015).

## What is actually running

| EA | Role | Can it send orders? | Recently running? |
|---|---|---|---|
| `BTC_V3_Core_V1.mq5` | Stage 3 forward shadow / audit twin | **No.** It has no `OrderSend` or `CTrade`, and `SendOrderGuard()` always refuses (`:664-673`). | Yes, on the demo account, BTCUSDm M15 (terminal log 2026-09-25 to 2026-09-28). The deployed copy is byte-identical to the repository. |
| `BTC_V3_Stage4_Demo.mqh` | Demo-execution layer, deliberately not wired in | **No.** `Stage4Transmit()` refuses unconditionally (`:405-437`). It uses `OrderCheck` only. | No. Only the compile-check script includes it. |
| `BTC_Setup_A_V1.mq5` | Setup A EA | **Only in `DEMO_TRADE` on a demo hedging account** (`:759-765`), via `CTrade.BuyStop`/`SellStop` (`:539-541`). The default is `AUDIT_ONLY`. | No. Its README says it has never been compiled. |

No EA in this repository can place an order on a real account. Magic numbers:

- Setup A: `515010220` (input, `:13`).
- Stage 4 layer: `20260921`.
- Core: none, because it never trades.

## BTC_V3_Core_V1 (running, shadow only)

| Safeguard | Status | Evidence |
|---|---|---|
| Max position size | NOT APPLICABLE | Only the simulated size is capped (0.25% risk, 1× leverage, `:680-695`). Nothing is sent. |
| Max daily loss | NOT APPLICABLE | It never trades. |
| Duplicate-order protection | NOT APPLICABLE | There are no orders. Its audit rows are exactly-once (`LastLoggedBar`, `:1863-1871`). |
| Aggregate exposure | NOT APPLICABLE | There is no broker exposure. |
| Disconnect handling | PRESENT (logging only) | `PollConnectivity` logs DISCONNECT, RECONNECT and TICK_OUTAGE (`:1782-1814`). |
| Restart handling | PRESENT (audit state) | It restores its session file and replays from a fixed anchor (`:1058-1090`, `:1851-1896`). |

## BTC_V3_Stage4_Demo.mqh (not wired in)

| Safeguard | Status | Evidence |
|---|---|---|
| Max position size | PRESENT | Size comes from the risk budget, capped at 1× leverage (`:268-271`). Volume is rounded down to the step, refused below the minimum and clamped to the maximum (`:199-211`). |
| Max daily loss | **MISSING** | There is no day-reference equity or loss limit in `Stage4Config` or the gates (`:46-59`, `:96-146`). |
| Duplicate-order protection | PRESENT, with a gap | `Stage4AlreadySubmitted` checks open orders and positions for the magic plus the comment tag (`:347-364`). It does not check history, so a signal could be re-sent after its position closes. It is also UNCLEAR whether the broker keeps comments intact. |
| Aggregate exposure | **MISSING** | There is no cap on concurrent positions or total volume. `Stage4OrphanCount` only reports orphans (`:368-386`). |
| Disconnect handling | **MISSING** | There are no `TERMINAL_CONNECTED` or trade-permission gates. A `TRADE_DISABLED` reply is only classified afterwards (`:319`). |
| Restart handling | UNCLEAR | The client tag is meant to let a restart recognise its own orders (`:336-338`), but there is no recovery code in this file. |

## BTC_Setup_A_V1 (order-capable, demo only, not compiled)

| Safeguard | Status | Evidence |
|---|---|---|
| Max position size | PRESENT | Size is the minimum of 0.25% risk and 1× virtual balance (`:503-507`). `FloorVolume` rounds down to the step and clamps (`:479-488`). The broker volume specification is checked at start (`:744-746`). |
| Max daily loss | PRESENT, with caveats | There is a 1% daily drawdown lock, a lock after 3 consecutive losses, a 6% monthly lock and a limit of 3 trades per day (`:379-390`, enforced at `:559-566`). Caveats: 1. The equity is strategy-virtual, not account equity. 2. The all-time lock is off (`:385`). 3. It is evaluated at M15 bar close only. 4. With missing global variables and no open position, the day reference resets. |
| Duplicate-order protection | PRESENT (own symbol and magic) | There is one own order or position at a time (`:495-499`, `:568`). Warm-up does not evaluate signals (`:795`). |
| Aggregate exposure | PRESENT per EA; **MISSING** across the account | Other symbols and magics (for example a Gold EA) are not considered. |
| Disconnect handling | **MISSING** | There are no connection or trade-permission checks before sending. A failed send is logged (`:544-549`), and a failed modify halts (`:700-706`). |
| Restart handling | PRESENT, with a caveat | It restores risk from global variables and halts if they are missing while own orders exist (`:785-788`). It rebuilds balance from broker history (`:316-362`). Caveat: a data gap during warm-up calls `CancelOwnPending` on a live pending order (`:715-716`); whether that is intended is UNCLEAR. |

## Isolated improvements prepared for review (not applied)

These are proposals only. Each would change trading code in `mt5/` (a protected area), so none is written until Rahul approves it and it passes the compile → tester → parity checks. Telemetry V1 needs none of them.

1. **Stage 4 daily-loss gate.** Add a day-reference equity and a maximum daily loss to `Stage4EvaluateGates` before any transmission exists.
2. **Stage 4 exactly-once over history.** Also look for the client tag in `HistorySelect` orders and deals.
3. **Connection and permission gates for Stage 4 and Setup A.** Before any send or modify, refuse when `TERMINAL_CONNECTED`, `TERMINAL_TRADE_ALLOWED` or `MQL_TRADE_ALLOWED` is false.
4. **Account-level exposure cap, independent of any strategy (D014).** A separate observer-style guard that reports aggregate exposure across magics. Following the watchdog principle, it would only report until a policy for acting is approved.
5. **Setup A warm-up gap handling.** Decide explicitly whether a warm-up data gap may cancel a live pending order.

## Telemetry V1 itself

- `ZoneflowTelemetryObserver` and `ZoneflowTelemetry.mqh` contain no trade function. `tests/test_telemetry.py` scans them for `OrderSend`, `CTrade`, `PositionClose`/`Modify`, `OrderDelete` and similar calls.
- The observer runs as its own program. It does not change, pause or depend on any strategy EA.
- The watchdog only reports. It never flattens, closes, disables trading or modifies orders.
