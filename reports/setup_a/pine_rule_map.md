# BTC Pullback + Trend Breakout 3R — V2.2.0: standalone Setup A rule map

Authoritative source: `reference/BTC_Pullback_Trend_Breakout_V2_2_0.pine` (all 4,483 lines reviewed). Python: `strategies/btc_v2_setup_a.py`. The native research runner is `research/exness_setup_a_validation.py`. Setup B is disabled for these standalone runs; Pine's A-before-B priority (line 2719) has no competing B signal here.

| Pine line / rule | Python equivalent | Original default | Notes |
|---|---|---|---|
| 143–191: side and setup switches | `SetupAParameters.longs_enabled`, `shorts_enabled`; standalone `BtcV2SetupA` | both sides on; A on | B excluded only for standalone validation. |
| 199–253: higher timeframe | `ConfirmedH1Trend` | 60m, EMA50, EMA200, slope lookback 5 | Only complete UTC H1 candles are accepted. |
| 263–359: M15 indicators | `EMA`, `RSI`, `ATR`, `DMI` | EMA20/50, RSI14, DI14, ADX smoothing14, minimum ADX18, ATR14 | Existing Pine-compatible streaming implementations, reset per data segment. |
| 371–399: touch lookback | `_last_touch_index`, `bars_since_prior_touch` | 5 bars | `ta.barssince(touchesEither)[1]` excludes the current candle. Earlier touch qualifies when prior-bar distance `< 5`. |
| 405–453: RSI ranges | `evaluate_setup_a` | long 54–68; short 32–46 | Inclusive bounds, independent per direction. |
| 459–507: rejection close location | `evaluate_setup_a` | long ≥0.60; short ≤0.40 | `(close-low)/(high-low)` on a positive-range candle. |
| 495–507, 2185–2417: EMA50 tolerance | `evaluate_setup_a` | 0.50 ATR | Long low ≥ EMA50−tolerance; short high ≤ EMA50+tolerance. |
| 511–547: large candle filter | `evaluate_setup_a` | enabled; max range 2.50 ATR | Rejection range cannot exceed 2.5 ATR when enabled. |
| 555–583: entry/stop buffers and expiry | `evaluate_setup_a`, `Signal.pending_stop` | entry 0.20 ATR; stop 0.30 ATR; two pending bars | Long trigger above rejection high; short below rejection low. Stop outside rejection low/high. |
| 831–877: universal stop and target | `evaluate_setup_a`; `BacktestSettings` | stop 0.60–3.00 ATR; fixed 3R | Inclusive stop distance; target uses actual fill-to-structural-stop distance. No BE, trailing, or partial exit. |
| 887–1011: sizing | audited `BacktestSettings(risk_percent=.25, RR=3)`; separate `executable_lots` audit | Pine risk 0.25%; minimum Pine quantity 0.000001 | Research uses the project's audited 10,000 USD account, 1× leverage, price-distance stop convention at zero cost; not Pine's 100,000 USD `initial_capital`. Exness 0.01-lot step/minimum is reported separately and rounded down. No generic-engine change. |
| 1023–1067: daily/monthly/all-time protection inputs | shared `SetupBRiskState` used by A | 3 fills/day; daily DD 1%; 3 consecutive losses; monthly DD 6%; all-time off at 10% threshold | Same Pine V2.2 account permissions already audited for B. Locks suppress new orders, not filled positions. |
| 1079–1119: session and weekdays | `BtcV2SetupA.on_candle` | 07:00–20:00 UTC; all seven days | Session and day tested at signal candle, pending permission rechecked thereafter. |
| 1127–1151: internal backtest dates | segment `trade_start` after causal warm-up | Pine UI default Jan–Jun 2026 | Explicit full native research period overrides Pine's narrow interactive default; no strategy threshold is changed. |
| 1213–1281: M15 calculations | streaming `EMA`, `RSI`, `ATR`, `DMI` | lengths above | Current completed M15 candle only. ATR, RSI, and DMI retain Pine `na` warm-up behavior. |
| 1291–1395: `request.security` and H1 trend | `ConfirmedH1Trend.update` | previous confirmed H1 close/EMA50/EMA200; EMA200 slope over five H1 bars | Pine `close[1]`, EMA `[1]`, EMA `[1+lookback]`, `lookahead_on`: the current incomplete H1 is never exposed. |
| 1401–1475: UTC session/day/backtest | `on_candle` window and permission checks | values above | Existing engine feeds completed M15 bars chronologically; no future data. |
| 1587–1849: risk reference/reset/locks | shared `SetupBRiskState.advance` | values above | Start-of-UTC-day/month equity, running all-time high if enabled, sticky locks. Breakeven leaves loss streak unchanged. |
| 1857–2015: common permission | `on_candle`, `evaluate_setup_a` | EMA alignment, ADX≥18; no position/pending | Position and pending order prevent new searches. |
| 2021–2139: pending cancellation and expiry | `CancelPendingOrder`, existing pending-stop engine | two bars | Reasons include session, weekday, backtest end, risk lock. Filled trades stay open. Engine checks bars B+1 and B+2, then expires. |
| 2143–2181: `touchesEither` | fast/slow EMA touch in `on_candle` | current high/low straddles either EMA | Current touch is saved **after** reading prior touch age. Touch history resets at gaps. |
| 2185–2291: full long conjunction | `evaluate_setup_a` LONG branch | H1 bull, EMA20>50, ADX, RSI, prior touch, bullish rejection, range, stop filter | Exact signal candle high/low define buffered entry/stop. |
| 2293–2391: full short conjunction | `evaluate_setup_a` SHORT branch | symmetric H1 bear, EMA20<50, RSI32–46, bearish rejection | Exact signal candle low/high define buffered entry/stop. |
| 2719–2889: order creation priority | `evaluate_setup_a` LONG then SHORT; `Signal.pending_stop` | A before B in combined Pine | B is absent here. No next-open substitution. |
| 2917–3201: fill, trade count, bracket | existing audited pending engine, shared risk state | actual fill; structural SL; fixed 3R TP | Fills counted, not signals. Pending trigger is fixed at signal time. Target recalculated from actual fill. |
| 3207–3491: closed trades | shared risk state; research statistics | losses increment, wins reset, breakeven unchanged | Daily streak lock affects future searches only. |

## Research execution boundaries

The generic OHLC engine retains its audited conservative same-bar convention. Exness Bid M15 bars generate signals; M15 Bid OHLC is **not** tick-exact Bid/Ask execution. Zero-cost isolates entry logic. Historical M15 bar SPREAD is a bar minimum and is shown only as a lower-bound cost descriptor. Fixed $10/$15/$20/$30 spreads are sensitivities, not claims about historical execution. Commission is zero. Each continuous segment resets indicators, account, orders and positions; one open final-segment position remains unrealized under existing end-of-test semantics.
