# MT5 validation checklist

Status: **EA SOURCE GENERATED; MT5 compile and parity pending.** Research freeze unchanged. No live trading approval.

## Before demo orders

- [ ] In MetaEditor, compile `BTC_Setup_A_V1.mq5` with **zero errors**. Record terminal/build number and warnings.
- [ ] Confirm BTCUSDm, M15, Bid chart, 2 digits, 0.01 point, contract 1 BTC/lot, 0.01 minimum/step, maximum at least 0.01. Confirm Exness server UTC+0 and demo hedging account.
- [ ] Verify the default `AUDIT_ONLY` submits **zero** broker orders. Ensure the Magic Number is unique on this account and the Gold EA has a different magic.
- [ ] Inspect journal initialization line for the exact freeze hash and `AUDIT_ONLY`.
- [ ] Confirm closed M15 indexing, confirmed H1 timestamp, indicator warm-up, prior EMA touch, session boundaries, both directions, and first signal after each data gap.
- [ ] Check every blocked reason and pending expiry after B+2; verify locks cancel only pending orders.
- [ ] Inspect order creation, trigger/stop, risk $, raw/rounded lot, and actual planned risk. Verify lot size always rounds down.
- [ ] In a **demo** tester run, inspect Buy Stop Ask trigger, Sell Stop Bid trigger, long Bid exit, short Ask exit, actual-fill 3R TP adjustment and any modification rejection.
- [ ] Verify every cancellation and position operation filters BTCUSDm plus the EA Magic Number; Gold EA orders/positions remain untouched.
- [ ] Restart tester/EA with a pending order and with a filled position; check broker-state reconstruction and persisted protection references.
- [ ] Check how a source gap with an own open position is logged and handled; no fabricated candle or forced close.
- [ ] Verify CSV fields contain signal time, direction, trigger, structural stop, target, fill and exit data, ticket, Magic Number, Bid, Ask, spread, PnL.

## Required historical comparisons

| Test | UTC dates | Status |
| --- | --- | --- |
| A: stronger period | 2026-01-01 through 2026-03-31 | Pending MT5 Strategy Tester export |
| B: weaker period | 2025-01-01 through 2025-03-31 | Pending MT5 Strategy Tester export |

- [ ] Use **Every tick based on real ticks** if Exness tester data supports it; record whether tick history is complete.
- [ ] Export EA audit CSV for each test and run `tools/compare_mt5_setup_a.py` with exact test dates.
- [ ] Review *every* missing/extra signal, direction mismatch, trigger/stop/target difference, fill/exit difference, and outcome mismatch.
- [ ] Do not label parity PASS until compile succeeds, both tests run, comparisons are reviewed, and any justified clock representation difference is explicitly documented.
- [ ] Only after parity review, decide separately whether to begin forward **demo** validation. There is no LIVE mode in this EA.
