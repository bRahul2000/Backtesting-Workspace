# BTC Setup A V1 Research Candidate — frozen specification

**Status: RESEARCH FROZEN. Not live approved.** Next required stage: MT5 / Exness forward or demo execution validation.

This is standalone Setup A from `reference/BTC_Pullback_Trend_Breakout_V2_2_0.pine` (title **BTC Pullback + Trend Breakout 3R — V2.2.0**) as validated in `strategies/btc_v2_setup_a.py`. The earlier [Pine rule map](../pine_rule_map.md) identifies the source line ranges and Python equivalents. The Phase 4L source checkpoint is `f4a62662368b01519bf32e1345bdff8493cff342`, tag `btc-setup-a-long-history-v1.0`. The machine-readable defaults and source checksums are in [frozen_strategy.json](frozen_strategy.json); its SHA-256 freeze hash covers every field except the hash itself. A mismatched file or source checksum must fail validation, never be rewritten silently.

The original combined Pine UI defaults both Setup A and Setup B to enabled and its internal test dates to **2026-01-01 00:00 UTC through 2026-06-30 23:59 UTC**. This separately named **standalone A research candidate** deliberately disables Setup B and uses explicit historical research windows instead of that interactive date default. No Setup A threshold is changed.

## Feed, clocks, and calculations

- Primary research feed: Exness Standard **BTCUSDm**, 15-minute **Bid** OHLC candles; `1 lot = 1 BTC`. Bitstamp BTC/USD 15-minute candles are separate cross-feed evidence. Candle timestamps and session/day protections are UTC. Historical M15 Bid OHLC is not tick-exact Ask/Bid execution.
- Signals use a fully completed M15 candle. H1 trend values come only from the prior **complete** four-candle UTC H1 bar. `request.security`'s previous confirmed H1 values are reproduced without current-H1 lookahead. Incomplete H1 bars never enter the H1 EMA series.
- EMA uses `previous + 2/(length+1) × (close−previous)`, seeded from its first price. Wilder RMA seeds from the first `length` nonmissing observations and then updates by `(observation−previous)/length`. ATR(14) is RMA of true range; RSI(14) uses RMA of gains and losses; DI(14) uses Wilder-smoothed true range and directional movements, and ADX uses RMA(14) of DX. Indicator `na` warm-up prevents a signal until all required values exist.
- Every continuous 15-minute source segment starts with fresh M15/H1 indicators, strategy permissions, pending order, position, and audited account balance. No OHLC is fabricated, interpolated, or forward-filled across a gap. A trade is never carried across a source gap; a still-open position at the final candle stays unrealized under the existing end-of-test convention.

## Original Setup A defaults and signal rules

| Component | Frozen rule |
| --- | --- |
| Direction | Long and short both enabled. Standalone **A only**; Setup B disabled. No Phase 4K ATR% or 24-hour volatility gate. |
| H1 trend | EMA50 and EMA200 on confirmed H1 closes; EMA200 slope lookback **5 confirmed H1 bars**. Long requires confirmed H1 close > EMA200, EMA50 > EMA200, EMA200 > its value 5 H1 bars earlier. Short reverses all three inequalities. |
| M15 alignment | EMA20 > EMA50 for long; EMA20 < EMA50 for short. |
| ADX | DI length **14**, ADX smoothing **14**, current completed M15 ADX **≥18.0** for either direction. |
| RSI | RSI length **14**. Long **54–68** inclusive; short **32–46** inclusive. |
| Prior pullback | On either EMA20 or EMA50, a candle's high ≥ EMA and low ≤ EMA is a touch. `ta.barssince(touchesEither)[1]` excludes the current signal candle. Its preceding-bar touch age must be present and **<5**. |
| Long rejection | Positive candle range; close > open; `(close−low)/(high−low) ≥0.60`; low ≥ EMA50 − **0.50×ATR**. |
| Short rejection | Positive candle range; close < open; close location ≤**0.40**; high ≤ EMA50 + **0.50×ATR**. |
| Rejection range | Large-candle filter **on**; signal high−low ≤**2.50×ATR**. There is no Setup B body or structure-break filter. |
| Trigger | Long buy stop = signal high + **0.20×ATR**; short sell stop = signal low − **0.20×ATR**. |
| Structural stop | Long = signal low − **0.30×ATR**; short = signal high + **0.30×ATR**. Planned trigger-to-stop distance must be positive and **0.60–3.00×ATR**, inclusive; trigger and stop must be positive prices. |
| Target | Fixed **3.0R** from actual fill to the unchanged structural stop. No breakeven, partial exit, or trailing stop. |
| Session | **07:00–20:00 UTC**, start inclusive and end exclusive, on all seven UTC weekdays. |

The long and short conditions are complete conjunctions; either missing or false input blocks the signal. The original A-long then A-short priority is retained. Standalone A has no competing Setup B order.

## Order lifecycle and audited execution

On a qualifying candle close, submit a stop entry at the trigger above/below that candle. The order may fill on **B+1 or B+2** only; it expires unfilled after the second eligible subsequent candle. The planned quantity is fixed when the pending order is created. For a long, a later high crossing the trigger fills at `max(trigger, later open)`; for a short, a later low crossing fills at `min(trigger, later open)`. A gap through the trigger can therefore worsen the actual entry. The 3R target is calculated from that actual fill and the original structural stop; the pending quantity is not resized after a gap.

An unfilled order is cancelled, with a reason, when the UTC session or trading day becomes disallowed, the backtest ends, or a risk permission locks. A filled position is **not force-closed** by a subsequent permission lock. Only one position or pending entry may exist at a time; no pyramiding. The audited engine resolves same-bar stop/target ambiguity with **stop first**, preserves its existing opening-gap handling, and leaves an open end-of-test position unrealized.

## Position sizing and risk protections

Pine's default sizing mode is **Risk %** at **0.25% of strategy equity** per planned stop distance and `syminfo.pointvalue`; its fixed-quantity alternative is **0.01** and minimum Pine quantity is **0.000001**. The validated Python research runs use the audited **$10,000** starting balance, percentage-equity risk **0.25%**, **1×** maximum leverage, estimated-total-stop-loss sizing, and the same 3R exit. The generic engine's research baseline has **0% commission and 0% slippage**; separate Exness fixed-spread views are cost sensitivities, not changes to strategy rules. Pine's wrapper declares $100,000 initial capital, 0.05% commission and 2 ticks of slippage; those wrapper settings are not the audited Python/Exness research account. The separate Exness 0.01-lot executable-sizing audit is not silently substituted into theoretical backtest PnL.

- Count **filled positions**, not signals, toward the maximum **3 trades per UTC day**.
- At each new UTC day, reference that day's opening equity, reset filled-trade count and consecutive closed-loss count, and clear daily equity/streak locks. Daily equity drawdown = `(day-start equity − current marked equity)/day-start equity ×100`; lock new entries at **1.0%**.
- A completed losing trade increments the same-day streak; a winner resets it to zero; breakeven leaves it unchanged. Lock new entries after **3 consecutive closed losses** within the UTC day.
- At each new UTC month, reference that month's opening equity and clear the monthly lock. Monthly drawdown = `(month-start equity − current marked equity)/month-start equity ×100`; lock new entries at **6.0%**. This is not running-peak monthly drawdown.
- All-time equity protection is **off**. Its stored optional threshold is **10.0%** from a running equity high if enabled in a different, explicitly versioned strategy; it is not enabled here.

These locks restrict new signals or unfilled pending orders and never liquidate an already filled position. Data-segment resets are research boundaries, not exits triggered by a market gap.
