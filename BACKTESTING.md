# Phase 2 backtesting assumptions

This engine is a research simulator. The EMA crossover is a **DEMO / ENGINE TEST STRATEGY**, not a profitable trading claim. No live trading or parameter optimization is implemented.

## Candle timing

- CSV timestamps are **candle open times in UTC**. A strategy sees a candle only when it has closed, 15 minutes after its timestamp. A signal is stamped with that close time.
- A signal enters at the **next available candle's open**. The engine rejects signals that would cross a missing-candle gap, and resets indicator state after a gap. If an open position crosses missing candles, the backtest stops because its exit cannot be determined.
- The entry candle's high and low can trigger a stop or target after entry at its open. Only one position is held at a time. Signals during a position are reported and ignored.
- A position still open at dataset end remains open and is reported. Unrealized PnL is excluded. There is no forced final close.
- A selected date range is a trading window. Earlier saved candles are passed to the strategy for EMA/ATR warm-up, but cannot produce orders. Candles after the selected end are excluded; any position still open then remains open. Missing history is not fabricated. Indicator state resets after a data gap.
- `exit_time` identifies the **15-minute exit candle's open timestamp**. The exact intrabar stop/target time is unknowable from OHLC data.

## Fills and costs

The exact processing order is: **signal after candle N closes → candle N+1 open → adverse entry slippage → validate stop and calculate position size from current closed-trade equity → apply the leverage and minimum-quantity limits → derive/validate SL and TP → check the entry candle and later candles for exits → apply exit slippage and both commissions → record net PnL and update equity**. A strategy-supplied target stays at its supplied level; the default target is derived from the slipped entry and stop distance.

- Long stops trigger at `low <= stop`; long targets at `high >= target`. Short stops trigger at `high >= stop`; short targets at `low <= target`.
- When a bar touches both, **SL First** is the default. **TP First** is optional. The simulator does not infer an intrabar path.
- An opening gap through a stop fills at the opening price, even if this exceeds planned risk. A favorable gap beyond a target fills at the target price. The open is known to occur before the rest of its bar.
- Slippage moves long entry and short exit prices **up** by the configured percentage; it moves short entry and long exit prices **down**. Commission is charged on `abs(fill price × quantity)` at both entry and exit.
- The planned risk budget is `balance × risk %` or a fixed dollar amount. **Estimated Total Stop Loss** is the default calculation. Let `E` be the slipped entry price, `S` the stop level, `F` the adverse slipped stop-exit fill, and `c` the commission rate as a fraction. Estimated stop loss per unit is `E − F + c × (E + F)` for a long, or `F − E + c × (E + F)` for a short. Quantity before exposure limits is `planned risk / estimated stop loss per unit`. With no gap and no change to configured costs, the estimated net stop loss equals planned risk within floating-point tolerance.
- **Price Distance Only** is the backward-compatible calculation: `quantity = planned risk / abs(E − S)`. It excludes exit slippage and commissions from the risk budget, so a normal stop can lose more than planned risk.
- Notional exposure is capped at `current closed-trade equity × maximum leverage`, with a default maximum leverage of 1×. If necessary, quantity is reduced to `maximum exposure / E`, and the trade records `leverage_capped=True`. The estimated stop loss then falls below planned risk. Quantity below a configured minimum is rejected after the cap; zero disables the minimum. There is no lot-step, borrowing, liquidation, or exchange margin model yet.
- `planned_risk` (and the retained `initial_risk` field) is the selected budget before a leverage cap. `estimated_stop_loss` is the projected net loss at the stop for the **actual** quantity, including configured costs. `realized_r` (and the retained `r_multiple` field) is `net PnL / planned_risk`, even when leverage-capped. Adverse gaps can make realized loss exceed this estimate and planned risk. Floating-point calculations may differ by roughly machine precision; no fixed quantity rounding is applied.
- If a strategy does not supply a target, the engine sets it at `slipped entry ± risk/reward × abs(slipped entry − stop)` in the trade direction. Invalid entry, stop, target, quantity, or settings are rejected with a reported issue or error.
- Net PnL is signed price change × quantity, less both commissions. Net PnL % is net PnL divided by entry notional.
- Bars held counts the entry candle as one, including a trade that enters and exits within that same candle.

## Equity and metrics

The initial balance is the first equity point. Balance updates only after completed trades, using **net** PnL. Position sizing uses that balance at entry. The equity and drawdown curves are closed-trade curves; they do not mark open positions to market. Peak equity is the highest recorded closed-trade balance. Drawdown is peak minus balance, in dollars and as a percentage of peak. Profit factor is gross winning PnL divided by absolute gross losing PnL; it is undefined with no trades and infinite when there are wins but no losses.

## Developer check

`venv/bin/python -m engine.manual_validation` runs a two-candle 100 entry / 95 stop / 110 target example. With default 1% risk on $10,000, expected quantity is 20 BTC units, net PnL is $200, and final balance is $10,200. This is an arithmetic fixture, not a realistic BTC position.
