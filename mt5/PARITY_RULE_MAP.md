# BTC Setup A V1 parity rule map

**Source:** [frozen strategy specification](../reports/setup_a/v1_candidate/strategy_specification.md), [manifest](../reports/setup_a/v1_candidate/frozen_strategy.json), [Python Setup A](../strategies/btc_v2_setup_a.py), and Pine V2.2.0. The immutable freeze hash is `b9c1f07ed3ec4b068f65d0ede59e6a94dc6985c4ad8824ae606c168c7f33b649`.

This is an implementation map, not evidence of compiled or Strategy Tester parity. MQL5 source is [BTC_Setup_A_V1.mq5](BTC_Setup_A_V1.mq5).

| Frozen rule | Python reference | MQL5 implementation |
| --- | --- | --- |
| Exness BTCUSDm, Bid M15, UTC+0 H1 | `services/exness_m15.py`, `ConfirmedH1Trend` | `ValidateEnvironment`, `UpdateH1`, `ProcessCompletedBar`; startup rejects wrong symbol/timeframe/spec/server offset |
| Completed M15 once; never inspect unfinished H1 | `BtcV2SetupA.on_candle`, `ConfirmedH1Trend.update` | `OnTick` new `iTime` boundary; `UpdateH1` completes only prior hour of four consecutive bars |
| Segment resets; at least 205 confirmed H1 bars | `setup_a_warmup`, `on_data_gap` | `ResetIndicators`, `FirstSearchTime`; no synthetic bar; pending canceled on gap |
| EMA20/50 and confirmed H1 EMA50/200, slope 5 | `EMA`, `ConfirmedH1Trend` | `UpdateIndicators`, `CompleteH1`; first close seed, alpha 2/(N+1), six-value slow history |
| ATR14, RSI14, DI14/ADX14 Wilder RMA | `ATR`, `RSI`, `DMI` | `RmaUpdate`, `UpdateIndicators`; arithmetic seed and subsequent RMA; no signal before warm-up |
| H1 long: close and EMA50 above EMA200, positive slope; short reversed | `H1TrendValue.long/short` | `EvaluateBar` H1 conjunctions |
| M15 EMA20>EMA50 long; EMA20<EMA50 short | `evaluate_setup_a` | `EvaluateBar` EMA alignment |
| ADX≥18; long RSI 54–68; short RSI 32–46 | `SetupAParameters`, `evaluate_setup_a` | `EvaluateBar` ADX and directional RSI checks, inclusive |
| Prior EMA20 or EMA50 touch, previous-bar age<5 | `_last_touch_index`, `bars_since_prior_touch` | `UpdateIndicators` computes `prior_touch` before recording current touch |
| Long bullish location≥.60, low≥EMA50−.50 ATR; short bearish location≤.40, high≤EMA50+.50 ATR | `evaluate_setup_a` | `EvaluateBar` rejection checks |
| Rejection candle range≤2.50 ATR | `evaluate_setup_a` | `EvaluateBar` range check |
| Long trigger high+.20 ATR; stop low−.30 ATR; short opposite | `evaluate_setup_a` | `EvaluateBar` trigger and stop |
| Planned stop distance .60–3.00 ATR, positive prices | `evaluate_setup_a` | `EvaluateBar` stop distance check |
| A-long before A-short; Setup B disabled | `evaluate_setup_a` | `EvaluateBar` long then short; first qualifying direction selected; no B code |
| Session 07:00–20:00 UTC; all weekdays | `BtcV2SetupA.on_candle` | `PermissionReason`, broker UTC startup check |
| Two pending bars B+1/B+2; cancel on permission loss | `Signal.pending_stop`, `on_candle`, generic execution | `PlaceSetupA` specified-time buy/sell stop, `CancelOwnPending`, `AuditTick`; expiry at B+3 open |
| Buy stop from Ask, sell stop from Bid; long exits Bid, short exits Ask | Exness broker model | Native broker stop orders; explicit quote sides in `AuditTick` |
| Structural SL; target fixed 3R from **actual** fill; no other exits | `engine/execution.py` | Initial broker SL and provisional 3R TP on pending; `ManageDemoTarget` adjusts TP from actual fill; no BE/partials/trailing |
| One own pending or position, no pyramiding | `BtcV2SetupA.on_candle` | `OwnStateActive`; all order and position operations filter **symbol + magic** |
| $10,000 isolated research balance, .25% equity risk, 1× notional cap, 0 commission | `BacktestSettings`, `plan_entry` | `START_BALANCE`, `RISK_PERCENT`, `PlaceSetupA`, `RefreshOwnHistory`; lots floored to symbol step/min/max |
| Three **fills** per UTC day; daily 1% DD; three closed losses; monthly 6% DD; all-time off | `SetupBRiskState` | `UpdateRisk`, `RefreshOwnHistory`, `PersistRisk`, `PermissionReason`; own deals only |
| Locks cancel pending, never close filled position | `BtcV2SetupA.on_candle` | `CancelOwnPending` only; no position close on permission lock |
| No future data or optimization controls | frozen manifest | Signal values only from completed bar and previous complete H1; constants match manifest |

## Index and execution details

- At the first tick of M15 bar `n+1`, `OnTick` processes completed bar `n`. `UpdateH1` makes H1 hour `h−1` available when the first bar of hour `h` is processed. The current H1 hour remains incomplete through all its M15 bars.
- The pending order carries the signal candle epoch in comment `A1|...`; CSV `signal_time` is **signal candle close** (`bar open + 900 s`) and `signal_candle_time` is its open. This matches Python's captured signal identifier.
- The Python historical engine has OHLC intrabar assumptions; MT5 demo and real-tick tester operate on actual Bid/Ask ticks. Fill and exit differences are expected research evidence and must be reported, never concealed by tolerance.
- Native MT5 broker stop and TP prices must lie on the tick grid. The EA rounds prices to the broker tick size and rounds volume **down**. This may differ from the theoretical Python quantity and raw-price control; the comparator reports price and execution differences.
- An MT5 pending order has a provisional 3R TP from planned trigger so it is protected before the first post-fill callback. `ManageDemoTarget` then changes it to 3R from the actual broker fill. A fill-to-modification interval remains a validation risk; inspect tester logs.
- Research segment account resets cannot be applied to a live demo account with an open position. After an M15 gap, the EA cancels its pending order and resets indicators; if its own position spans that gap, it halts new signals and leaves the broker position untouched for manual review.
- `AUDIT_ONLY` paper fills use quotes received after attachment; history cannot be recreated without Strategy Tester ticks. The terminal must be kept running. Restart loses paper-only state; `DEMO_TRADE` reconstructs broker orders/positions and stored daily/monthly lock references.
