# R3 — Frozen BTC Core portability: Exness broker-native vs Bitstamp

The untouched frozen `BTC_V3_CORE_V1_FROZEN` was run on both feeds over the **exact same
timestamp set**. Nothing was tuned. The strategy fingerprint
`631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd` was asserted inside every
run; the module refuses to report if it ever differs.

**This is a portability measurement. It is not a live-profitability claim.**

## Design — separating feed from spread

Exness carries a real per-bar spread (median $21.60); Bitstamp is a venue feed with no spread
at all. Comparing them directly would confound a *feed* difference with a *cost* difference,
so three configurations were run:

| Variant | Candles | Spread model |
|---|---|---|
| **A · EXNESS_NATIVE** | Exness BTCUSDm | real per-bar broker spread |
| **B · EXNESS_FLAT10** | Exness BTCUSDm | calibrated constant $10 |
| **C · BITSTAMP_FLAT10** | Bitstamp BTC/USD | calibrated constant $10 |

- **C vs B** isolates the **feed** difference (identical spread model)
- **B vs A** isolates the **spread** difference (identical feed)
- **C vs A** is the total portability difference

Both datasets were first restricted to the exact intersection of their timestamps —
**99,897 M15 candles, 2023-11-10 23:15 → 2026-09-17 01:30 UTC** — so warmup boundaries and
continuous segments are identical in every run and cannot themselves explain a divergence.

## Headline results

| | A · EXNESS_NATIVE | B · EXNESS_FLAT10 | C · BITSTAMP_FLAT10 |
|---|---|---|---|
| Total trades | **304** | 295 | **354** |
| Long / Short | 145 / 159 | 137 / 158 | 149 / 205 |
| Win rate | 26.32% | 27.12% | 29.10% |
| Profit factor | **1.072** | 1.117 | **1.229** |
| Average R | **+0.0560** | +0.0884 | **+0.1626** |
| Total R | **+17.01** | +26.07 | **+57.55** |
| PnL | +$401.86 | +$630.93 | +$1,437.45 |
| Max drawdown | 3.65% | 3.65% | 3.75% |
| Max losing streak | 10 | 9 | 13 |

The frozen Core stays **positive on broker-native Exness data**, but materially less so than
on Bitstamp: Avg R falls from +0.163 to +0.056, PF from 1.23 to 1.07.

## Trade-by-trade matching

Trades are paired on `(signal timestamp, side)`. Full per-trade detail is in
`exness_btc_core_trade_matching.csv`.

### C vs B — the FEED difference (identical $10 spread)

| | |
|---|---|
| Trades | 354 (Bitstamp) vs 295 (Exness) |
| **Matched signals** | **149** |
| **Unmatched signals** | **351** (205 Bitstamp-only, 146 Exness-only) |
| Identical of matched | **0.0%** |
| Median entry-price difference | −$17.42 |
| Median absolute entry-price difference | $20.57 |
| Median absolute stop difference | $16.88 |
| Exit-reason changes | 7 |
| Total R difference | **−28.23** |

| Classification | Count |
|---|---|
| SIGNAL_DIFFERENCE | 351 |
| FEED_PRICE_DIFFERENCE | 111 |
| EXIT_DIFFERENCE | 30 |
| ENTRY_DIFFERENCE | 8 |
| IDENTICAL | 0 |

**Only about 42% of Bitstamp signals also occur on Exness.** This is the dominant effect:
the R2 divergence of ~$15 per bar — and especially the deeper Exness lows — is enough to
move candle geometry across the Core's thresholds, so the two feeds *see different setups*,
not merely the same setups at different prices. Of the 149 signals both feeds do produce,
**none is bit-identical**, which is expected when every bar differs by roughly $15.

### B vs A — the SPREAD difference (identical Exness feed)

| | |
|---|---|
| Trades | 295 (flat $10) vs 304 (real per-bar) |
| **Matched signals** | **295** |
| Unmatched signals | 9 |
| **Identical of matched** | **85.1%** |
| Median entry-price difference | $0.00 |
| Median absolute stop difference | $0.00 |
| Exit-reason changes | 2 |
| Total R difference | **−8.04** |

| Classification | Count |
|---|---|
| IDENTICAL | 251 |
| SPREAD_DIFFERENCE | 29 |
| EXIT_DIFFERENCE | 13 |
| SIGNAL_DIFFERENCE | 9 |
| ENTRY_DIFFERENCE | 2 |

Replacing the $10 constant with the broker's real per-bar spread leaves **85% of trades
completely unchanged** and costs **−8.04R** overall. That is the honest price of the old
calibrated assumption: the real median spread is $21.60, so the constant was optimistic by
roughly a factor of two, and the effect is a steady drag rather than a structural change.
The 9 extra trades under the real spread arise where a wider Ask triggers a pending order
that the narrow constant missed.

### C vs A — total portability difference

| | |
|---|---|
| Matched signals | 150 |
| Unmatched signals | 358 |
| Total R difference | **−28.34** |
| Median absolute entry-price difference | $20.46 |
| Exit-reason changes | 7 |

## Attribution

| Source | Total R impact | Share |
|---|---|---|
| **Feed** (different candles → different setups) | **−28.23** | ~78% |
| **Spread** (real per-bar vs $10 constant) | **−8.04** | ~22% |
| Combined (C → A) | −28.34 | — |

The two effects are not additive — the feed change alters *which* trades exist, so the
spread drag applies to a different population — but the ordering is unambiguous: **the feed
dominates, and the cost model is secondary.**

## Does the frozen Core behave materially differently on Exness?

**Yes, materially — but not adversely in sign.** It remains profitable on broker-native data
(PF 1.07, Avg R +0.056, +17.01R over ~2.85 years) with an unchanged drawdown profile (3.65%
vs 3.75%). What changes is:

1. **Which trades it takes.** Under 45% signal overlap. Any Bitstamp-derived trade-level
   expectation does not transfer trade-for-trade to Exness.
2. **How much edge survives.** Avg R roughly one third of the Bitstamp figure, mostly from
   the feed and partly from a spread that is twice the old assumption.
3. **Directional mix.** Bitstamp produced 205 shorts against Exness's 158–159; the T3 short
   component is the more feed-sensitive of the two.

The edge is thin enough on Exness (PF 1.07) that unmodelled costs could erase it — see below.

## Cost status

| Cost | Status |
|---|---|
| Spread | **Modelled** — real per-bar broker spread in EXNESS_NATIVE |
| Commission | **NOT MODELLED — UNVERIFIED** for BTCUSDm |
| Swap | **NOT MODELLED — UNVERIFIED**; positions are mostly intraday, but overnight holds occur |
| Leverage / margin | **NOT MODELLED — UNVERIFIED**; the engine caps leverage at 1.0 |
| Slippage | **NOT MODELLED** — 0.0 in this configuration |

With PF 1.07 and total R +17.01 over 304 trades, the broker-native result is **not robust to
unmodelled commission or swap**. No live-profitability conclusion may be drawn.

## Limitations

- Exness candles are broker **Bid** quotes; the Ask stream is synthesized by adding the
  per-bar spread. That is the repository's audited convention, not a tick-exact reconstruction.
- **MT5 bar spread is a bar-level descriptor**, not the spread guaranteed at an execution
  tick, so EXNESS_NATIVE costs are indicative rather than tick-exact. The five real tick
  samples remain the only tick-exact evidence, and they cover five days, not three years.
- `DatasetRole.PAPER` was used deliberately: this window is broker-native reality, not a
  research split, and **no parameter decision may be taken from it**.
- The derived overlap datasets are written outside the repository and are fully reproducible
  from the committed inputs by rerunning `research/exness_btc_core_portability.py`.
- The original Bitstamp benchmark (Development 472 / Forward 223) is a different window and
  configuration and is **unchanged**; nothing here supersedes it.
