# H3 independent replication — preregistration

Frozen 2026-09-29 **before any replication outcome was computed**. The only prior execution was
`run_replication.py --detect-only`. It printed detection counts and the number of replication-window events (526),
which are not outcomes: no forward race, control or rate was computed. This file is not edited after the outcome run.

## Hashes (SHA-256)

| item | hash |
|---|---|
| original H3 preregistration `research/gold_v1/h3/preregistration.md` (reused unchanged) | `c481f8a11da8428df4892d32c9ca3044e292726cb3f0320965f4fcc25339c59e` |
| H3 implementation `research/gold_v1/h3/h3_study.py` (`h3_features`, `detect`, `controls`, `h3_gate`), unchanged | `a6c8bb400f83a5af41fa92d63931878098c255f37298203a7aa65238a5262e99` |
| pipeline `research/gold_v1/h1/h1_study.py` (`features`, `forward`, `wilson`, `trading_days`), unchanged | `e2ec68842c142987f4c892727ed00393a372227a7d83ad1d9d6a3b3f03a94369` |
| control-comparison / bootstrap `research/gold_v1/h1/h1_report.py` (`lift`, `p_win`), unchanged | `71232d22e49e5ae73c9f3f39dfe63fccc70abb1d8c7aa40206b1c9df0e93d428` |
| replication runner `h3_replication/run_replication.py` | `958cc53990f2f3d2b97c44d6c06c5274520789f70c4262a6b19f8e02a085263e` |
| slice builder `h3_replication/prepare_slice.py` | `781b1f9f0fc6d0f0d25bfc9a9bedd9ce94a417108cd9108bce6cfdc1095028ba` |
| raw M15 export `history_expansion/raw/xauusd_XAUUSDm_M15.csv` | `010ac87504b2686ffd140764d19057611c1ffed2af4f8563b7407becab35aaf2` |
| raw H1 export (not used by H3) | `07d5d50fd12447845503a5aacf0089bca7b9073dbee056d69581cfdfde67f18f` |
| cleaned replication slice `h3_replication/data/xauusd_XAUUSDm_M15_h3_replication_slice.csv` | `a6a503ff479ba34bbe74e9377cec9787f3f3c39061870fdec405e36de09efa4e` |

## Data

- **Source.** Exness, server Exness-MT5Trial5, symbol XAUUSDm, M15, MT5 CopyRates (bid). The export is verified
  identical to Phase 2A on the overlap (see `HISTORY_QUALITY_AUDIT.md`).
- **Slice.** Lines with `2022.11.27 23:00:00 ≤ timestamp < 2025.12.22 23:00:00`, selected **by text before
  parsing**: 72,521 bars, from 2022-11-27 23:00 to 2025-12-22 21:45 UTC. No other line of the raw export is ever
  parsed.
- **Warm-up.** Sessions opening 2022-11-27 23:00 UTC through 2022-12-30. They initialise ATR(14), the 20-session
  compression percentile and the other causal state. Warm-up bars are **not** eligible as events, and they are
  **removed from the control pool**: their `atr_pct` is set to NaN in the copy of the feature frame passed to the
  frozen `controls()`, which already requires `atr_pct` to be present.
- **Replication window.** Events whose **acceptance (signal) bar** time is ≥ 2023-01-01 00:00 UTC and
  < 2025-12-22 23:00 UTC. In practice these are the sessions from the first 2023 session (opening 2023-01-02 23:00
  UTC) through the session ending 2025-12-22 21:45 UTC.
- **No development bar.** The slice ends before the 2025-12-23 development session (which opens 2025-12-22 23:00 UTC).
  Forward races and MFE/MAE therefore cannot use any development bar: a race reaching the end of the slice is
  `truncated` and excluded from P(...), as in development. No H3 outcome uses any development-period bar.
- **Never loaded:**
  - the artifact era 2019-12-23 → 2021-08-31 (Sunday future-bar artifact);
  - the **reserved holdout 2021-09-01 → 2022-11-26**;
  - development (2025-12-22 23:00 UTC onward);
  - the **sealed 2026 Validation** (2026-06-03 → 07-26) and **Final OOS** (2026-07-27 → 09-18);
  - later bars.

## H3 rules and controls

These are the original H3 preregistration, every rule unchanged, through the unchanged functions:
- 8-bar same-day compression window with rng8 at or below the 20th percentile of the trailing 20 sessions;
- Wilder ATR(14); displacement range ≥ 1.5 × ATR[D−1] and body/range ≥ 0.60, with the body in the breakout
  direction;
- the box intact until D; D closes beyond the box; acceptance D+1 closes beyond the box;
- stop at the opposite side of D; entry at the open of D+2;
- one event per structure and direction; the same reset behaviour and long/short treatment.

The controls use `h3_study.controls()` unchanged:
- 5 per event, drawn with replacement using seed 20260603;
- the same session and volatility regime, with an ATR percentile within ±10 (relaxed only as the function does);
- more than 8 bars from any event, and not an H3 acceptance bar;
- the event's direction and risk in ATR units;
- the forward race is `h1_study.forward()`.

## Policies

- **Missing bars.** The frozen session rule applies: bar starts ≥ 60 min apart begin a new session, so no compression
  box spans a hole. Nothing is interpolated or excluded. Events whose 20-session lookback (from the session 20 before
  the compression session to the acceptance bar) contains a known hole are flagged `lookback_contains_hole`. The
  holes are 2025-01-03, 2025-04-14, 2025-10-16, 2025-11-28 and 2025-12-07. The flag is provenance only; there is no
  rerun without these events.
- **Ambiguous intrabar.** When a target and −1R fall in the same M15 bar, that target is `ambiguous` for that event.
  It is excluded from P(+tR before −1R) for that target and never resolved favourably. A conservative variant
  (ambiguous = loss) is reported.
- **Costs.** Spread/risk is reported as indicative only. There are no cost filters and no entry-price adjustments.

## Metrics

- **Primary.** P(+2R before −1R) for H3 minus that of the matched controls, on the pooled 2023–2025 events. The 95% CI
  comes from the event-clustered bootstrap: 5,000 samples, seed 20260603, the unchanged `h1_report.lift`.
- **Secondary.** These never change the decision:
  - P(+1R), P(+3R) and P(+4R) before −1R, for H3 and controls, with differences and CIs;
  - MFE and MAE at 4, 8, 16 and 32 bars and until −1R;
  - long/short counts and +2R lifts;
  - ambiguous counts, risk distribution and spread/risk;
  - year-by-year (2023, 2024, 2025) and month-by-month tables;
  - a descriptive comparison with development.

## Decision rule (fixed now)

- **FAILED TO REPLICATE** if the pooled +2R lift is ≤ 0, **or** its 95% CI upper bound is < +3.0 pp (the data then
  rule out a practically meaningful effect).
- **REPLICATED** only if **all** of the following hold:
  - a. the pooled +2R lift is > 0 **and** the 95% CI lower bound is > 0;
  - b. the pooled +2R lift is ≥ +5.0 pp (practical magnitude, the same bar as development's PROMISING);
  - c1. the +2R lift is > 0 in at least 2 of the 3 calendar years;
  - c2. the pooled +2R lift, recomputed without the single most favourable year, is still > 0 (not driven by one
    year);
  - d. neither the long nor the short +2R lift is below −5.0 pp (not catastrophically contradictory);
  - e. H3's median MFE over 32 bars is ≥ the controls' median MFE over 32 bars (continuation supported).
- **INCONCLUSIVE** otherwise.

Expected power: with about 526 events and a control rate near development's 33.8%, the detectable lift is about
±6 pp.

## After the run

The run is repeated twice, and the event, control, yearly, monthly, summary and report files must be byte-identical.
Whatever the class, the work **stops for review**: no filters, no parameter changes, and no look at the reserved
holdout, Validation or OOS.
