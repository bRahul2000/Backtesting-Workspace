# Phase 2 backtesting assumptions

This engine is a research simulator. The EMA crossover is a **DEMO / ENGINE TEST STRATEGY**, not a profitable trading claim. No live trading or parameter optimization is implemented.

## Candle timing

- CSV timestamps are **candle open times in UTC**. A strategy sees a candle only when it has closed, 15 minutes after its timestamp. A signal is stamped with that close time.
- **NEXT_OPEN** remains the default: a signal enters at the next available candle's open. A signal cannot cross a missing-candle gap. The engine resets indicator state after a gap; an open position crossing missing candles stops the backtest because its exit cannot be determined.
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

## Pending stop entries

Strategies can emit `Signal.pending_stop(direction, pending_entry_price, pending_stop_price, pending_expiry_bars, setup_id)` instead of a NEXT_OPEN signal. A long trigger must be above the signal candle's close; a short trigger must be below it. Only one position or pending order is allowed at a time. An explicit take-profit price on a pending signal is rejected because the target is calculated from the actual fill.

- Quantity is fixed **at signal close**, using the planned trigger as the base entry price, the structural stop, current closed-trade equity, selected risk calculation, configured costs, leverage cap, and minimum quantity. It is never resized after a gap. A worse gap fill can make actual notional exposure exceed the cap calculated at order creation. `planned_risk` and `estimated_stop_loss` in the eventual trade reflect this creation-time plan.
- The order first becomes active on the following candle. `pending_expiry_bars=2` allows a trigger on B+1 or B+2 and expires the order after B+2 if unfilled. `pending_expiry_time` is the open timestamp of the final eligible candle; `pending_expiry_bar_index` is its index in the supplied dataset. A missing-candle gap cancels an outstanding order.
- A long triggers when `high >= trigger`; its base fill is `max(trigger, candle open)`. A short triggers when `low <= trigger`; its base fill is `min(trigger, candle open)`. Adverse entry slippage is applied after that base fill. `entry_gap_amount` is the positive distance between the base fill and trigger, before slippage. Actual risk can exceed the creation-time estimate after an adverse gap.
- The final target is calculated **after filling**: long `actual slipped entry + reward ratio × (actual slipped entry − structural stop)`; short `actual slipped entry − reward ratio × (structural stop − actual slipped entry)`. A fill with nonpositive actual risk distance or an invalid target is cancelled with a recorded reason.
- If a stop entry triggers inside a candle, the same candle's full high/low range is used for possible stop and target exits. OHLC cannot establish whether a stop-side extreme occurred before or after the trigger. The selected SL First or TP First rule resolves a bar touching both; a stop-only touch is counted as a stop under the conservative model. For a gap through the entry trigger, the entry occurs at the open before subsequent bar movement.
- A strategy may return `CancelPendingOrder(reason, setup_id)` from `on_candle`. It is evaluated at that candle's close, **after** any trigger in that candle, and prevents fills on later candles. An optional setup ID must match the outstanding order. Triggered, expired, cancelled, and active-at-end orders appear in `BacktestResult.order_events` and the diagnostics table; only filled and subsequently exited positions become completed trades.
- `actual_fill_time` identifies the **fill candle's open timestamp**, not a known exact intrabar instant. `actual_fill_price` includes adverse entry slippage. Trade records retain all previous fields and add entry model, pending timestamps, trigger, gap flag/amount, and setup ID.

## Equity and metrics

The initial balance is the first equity point. Balance updates only after completed trades, using **net** PnL. Position sizing uses that balance at entry. The equity and drawdown curves are closed-trade curves; they do not mark open positions to market. Peak equity is the highest recorded closed-trade balance. Drawdown is peak minus balance, in dollars and as a percentage of peak. Profit factor is gross winning PnL divided by absolute gross losing PnL; it is undefined with no trades and infinite when there are wins but no losses.

## Developer check

`venv/bin/python -m engine.manual_validation` runs a two-candle 100 entry / 95 stop / 110 target example. With default 1% risk on $10,000, expected quantity is 20 BTC units, net PnL is $200, and final balance is $10,200. This is an arithmetic fixture, not a realistic BTC position.

## BTC V2.2.0 Setup B

`strategies/btc_v2_setup_b.py` implements **Setup B only** from
`reference/BTC_Pullback_Trend_Breakout_V2_2_0.pine`. The demo strategy remains
separate. M15 EMA, ATR, RSI, and DMI/ADX are updated only from completed M15
candles. H1 candles are assembled from four consecutive M15 candles; every
M15 candle in the current H1 interval sees only the preceding confirmed H1
values, including the preceding H1 EMA200 value five H1 bars earlier. A
missing M15 candle resets the indicators without inventing data.

Setup B evaluates the Pine defaults: H1 trend; M15 EMA20/EMA50 and ADX;
inclusive RSI, body, range/ATR, extension, and stop-distance limits; previous
five-bar close breakout; and the two-bar structural stop including the signal
candle. A passing signal creates a two-bar pending stop order. The generic
engine fixes quantity when that order is created and computes the 3R target
from the actual fill. The source's Setup A is not implemented.

The UTC 07:00–20:00 session uses **candle open time**, with all seven days on by
default. Daily trade count increments on a fill. Daily and monthly equity
drawdown use the equity observed at the start of the respective UTC period;
the optional all-time guard uses the running peak. Equity for these strategy
permissions includes the open position's mark-to-market PnL at each completed
candle close and its entry commission. The day/month guards and the daily
closed-loss streak are sticky until their UTC reset; the all-time guard stays
locked for the run. Breakeven trades leave the loss streak unchanged. Guards
stop new signals and cancel unfilled pending orders at candle close. They do
not force-close positions. A pending order may fill within the first
out-of-session candle before a close-time cancellation, consistent with the
Pine script's close-based order evaluation and the audited OHLC engine.

The BTC preset keeps the audited engine's $10,000 starting balance, estimated
total stop-loss sizing, 1× maximum leverage, and zero minimum quantity; it
sets risk per trade to 0.25%, reward to 3R, and commission to the Pine
source's 0.05%. Pine specifies **two ticks** of slippage, whereas the audited
engine configures slippage as a **percentage**. The BTC preset therefore uses
0% percentage slippage and exposes it as an editable input; a percentage is
not silently passed off as two ticks. This baseline is an engine-model
backtest of Pine's signal and permission logic, not a byte-for-byte
TradingView strategy report. Each separate continuous segment seeds its own
indicators from its first available candle; no missing history is invented.

## Long BTC history

`python -m research.update_btc_history` resumes the canonical
`data/btcusd_15m.csv` from the public Bitstamp OHLC API, requesting only
missing 15-minute timestamps from 2023 onward and probing 2021 history.
Each successful API chunk is atomically saved, so an interrupted run resumes
at the next missing range. Requests use timeouts, retries, backoff, pacing,
and the API's incomplete-candle exclusion.

When the official endpoint was unreachable for the Phase 4A build, a
documented Bitstamp one-minute archive was aggregated conservatively: a
15-minute candle is retained only with all 15 unique, valid source minutes
and positive total volume. Existing saved Bitstamp candles take precedence.
The source URLs, licenses, SHA-256 hashes, and overlap checks are recorded in
`data/btcusd_15m_provenance.json`. The historical bulk archive is
Kaggle-derived; its recorded differences from the isolated 2025-01-01 saved
day mean it should be distinguished from directly fetched Bitstamp OHLC.

`python -m research.setup_b_history_baseline` writes the data-quality audit,
primary frozen Setup B baseline, yearly and monthly tables, six-month windows,
and separate runs for other continuous segments of at least 90 days to
`reports/long_history/`. The primary run uses the largest continuous segment.
Runs do not bridge gaps or combine segment balances. The Streamlit Market Data
view shows the saved range, gaps, segments, and last update; the backtest UI
requires a single continuous selected range for Setup B. Chart candles may be
downsampled for display, while execution always uses original M15 rows.
