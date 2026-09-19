# PB2 v1 — Research Summary and Closure

**Strategies:** `BTC_PB2_RECLAIM_LONG_V1`, `BTC_PB2_RECLAIM_SHORT_V1`
**Final status:** both `REJECTED`
**Evidence base:** DEVELOPMENT 2021-01-01 .. 2023-12-31 only.

PB2 v1 is closed for **sample scarcity**, not because its central idea was disproved.
All parameters, defaults, architecture modes and source behaviour are preserved unchanged
so every historical PB2 result stays reproducible.

---

## Final decisions

### LONG — `BTC_PB2_RECLAIM_LONG_V1`

> **REJECTED — DEVELOPMENT sample insufficiency and unresolved cross-regime robustness.**
> Strict reclaim acceptance showed localized positive selectivity, but the architecture
> generated only 29 closed LONG trades across 2021–2023 and remained negative in 2022. The
> sample is insufficient for responsible parameter optimization or robustness claims.

### SHORT — `BTC_PB2_RECLAIM_SHORT_V1`

> **REJECTED — DEVELOPMENT sample insufficiency and no stable positive expectancy.**
> The SHORT architecture produced only 14 baseline trades; acceptance ablations increased
> frequency only modestly and did not establish coherent cross-year positive expectancy.

---

## Hypothesis

An entry should be permitted only after price proves it can hold a level it broke:

    H1 trend context -> displacement through a prior 12-bar M15 structure level
    -> retest of that level -> reclaim -> one further bar of acceptance beyond it
    -> stop entry

No percentage retracement appears anywhere, and the sequence cannot complete inside a
single candle because acceptance always requires the next completed bar.

## Phase A — baseline (commit `566cc15`)

Two independent DEVELOPMENT-only runs, one per direction, at frozen defaults.

**LONG: 29 closed trades · PF 1.866 · Avg R +0.541** · total R +15.69 · PnL +$393.18 ·
0.91 trades/month · win rate 37.93% · max DD 0.77%.

| Year | Trades | PF | Avg R | Total R |
|---|---|---|---|---|
| 2021 | 4 | 2.986 | +0.9996 | +4.00 |
| **2022** | **7** | **0.493** | **−0.4370** | **−3.06** |
| 2023 | **18** | 2.465 | +0.8194 | +14.75 |

**2022 was negative, and 18 of the 29 trades occurred in 2023** — the headline ratios rest
on one favourable year.

**SHORT: 14 closed trades · PF 0.231 · Avg R −0.714** · total R −10.00 · PnL −$249.69 ·
0.44 trades/month · win rate 7.14% (one winner) · max DD 0.75%. Negative in all three
years (2021 −1.000R, 2022 −0.333R, 2023 −1.000R).

Both were classified `INSUFFICIENT_SAMPLE` at the time. The funnel showed why frequency was
so low — LONG: 38,861 context-qualified bars → 540 displacements → 308 retests →
130 reclaims → 58 acceptances → 39 pendings → 29 entries (a 5.4% displacement-to-trade
conversion). SHORT: 40,330 → 538 → 354 → 138 → 62 → 28 → 14.

## Phase A.1 — acceptance ablation (commit `c907f22`)

A predeclared architecture ablation, six runs, no parameter searched. Three variants:
**A STRICT** (baseline: acceptance bar must close beyond the level *and* beyond the reclaim
close), **B LEVEL_HOLD** (acceptance bar need only hold the level), **C RECLAIM_ONLY** (no
separate acceptance bar; the reclaim candle is the entry reference).

| Component | A STRICT | B LEVEL_HOLD | C RECLAIM_ONLY |
|---|---|---|---|
| LONG trades | 29 | 40 | 58 |
| LONG PF | 1.866 | 1.317 | 0.903 |
| LONG Avg R | **+0.5410** | +0.2225 | −0.0714 |
| SHORT trades | 14 | 26 | 32 |
| SHORT PF | 0.231 | 0.901 | 1.013 |
| SHORT Avg R | −0.7143 | −0.0769 | +0.0090 |

### LONG — the strict gate rejected predominantly losing setups

Trades added over the baseline, matched by originating displacement:

| vs A | Trades added | Winners | Losers | Total R added | Avg R of added |
|---|---|---|---|---|---|
| **B LEVEL_HOLD** | 13 | **1** | **12** | **−8.79** | **−0.676** |
| C RECLAIM_ONLY | 40 | 5 | 35 | −20.80 | −0.520 |

Of the 72 structures that reclaimed but failed strict acceptance, the 13 admitted by
LEVEL_HOLD went **1 winner / 12 losers / −8.79R**, and the 27 admitted by RECLAIM_ONLY went
2 winners / 25 losers / −18.75R. **RECLAIM_ONLY materially degraded LONG expectancy**
(+0.541R → −0.071R). Shared structures were untouched by B (+17.69R → +17.69R), confirming
B is an exact superset of A and the comparison is a clean ablation.

Classification recorded: **A — STRICT ACCEPTANCE EARNS ITS PLACE** — on the gate's
selectivity, explicitly not on tradeability.

### SHORT — relaxation raised frequency without coherence

Loosening increased trades from 14 to 26 to 32, but the evidence contradicts itself: the
setups strict acceptance discarded were *profitable* under LEVEL_HOLD (15 added trades,
5W/10L, **+5.00R**, Avg R +0.333) yet unprofitable under RECLAIM_ONLY (26 added, 5W/21L,
−3.90R). Positive years were 0/3, 1/3 and 1/3, and the single good year moved from 2021
(B) to 2023 (C). **No stable cross-year architecture emerged.**

Classification recorded: **D — ARCHITECTURE STILL TOO SPARSE / UNRESOLVED**.

### Downstream availability

PB2 blocks new structure detection while a pending order or position is open, so looser
variants observe *fewer* opportunities (LONG displacements 540 → 462 → 312; SHORT
538 → 341 → 175). The funnels are therefore not a clean nested subset.

---

## Transferable conclusion

**Reclaim + strict acceptance is a potentially useful continuation-quality concept.**

The failure of PB2 v1 was primarily **opportunity-generation / sample scarcity**, not
evidence that the strict acceptance gate itself was ineffective on LONG. On the long side
the gate demonstrably removed setups that went on to lose 12-of-13 and 25-of-27 — it was
doing real selection work. What the architecture could not do was produce enough
opportunities to evaluate that work.

**PB2 should not be parameter-optimized: the DEVELOPMENT sample is too small.** Searching
parameters over 29 LONG or 14 SHORT trades would fit noise, and Phase A.1 already showed
that the obvious way to buy frequency — weakening the acceptance gate — costs more
expectancy than it gains on the long side.

## PB1 vs PB2 — lessons

- **PB1** (`BTC_PB1_SHALLOW_PULLBACK_V1`, REJECTED): adequate frequency (810 DEVELOPMENT
  trades at baseline, 25/month) but weak cross-regime continuation quality — no
  configuration was robust across 2021/2022/2023.
- **PB2** (REJECTED): much stronger apparent LONG selectivity, but extremely low
  opportunity frequency (29 LONG and 14 SHORT trades across three years).

The two failures are opposite and complementary: PB1 had trades without quality, PB2 had
quality signals without trades.

**PB3 implication:** retain the proof-of-acceptance concept and **redesign opportunity
generation** rather than weakening acceptance. Historical research reasoning only — PB3 is
not implemented and not started.

## Fingerprint history

Phase A's fingerprints predate the research-only `acceptance_mode` field added in Phase
A.1. Both generations are preserved; old experiment artifacts were **not** rewritten.

| | LONG | SHORT |
|---|---|---|
| Original Phase A source era | `5c4a3f8ec34d97d660dae83f783539467d5dba58841b8936c9c7fe5b403a6a72` | `bed29f83b41ec2016033bf925a4a81c157e30bb765ecf6ab8359879b8a9f3eef` |
| Phase A.1 source era (current) | `668674ac4cc77cbab07d4922ce1c14e8e79ee921e27739e21535fa510e2236d5` | `1caf727ad08e9d77bf0f0855c006e41daa7777ef269e4af2e21cf9b035260503` |

Effective parameter fingerprints: Phase A (pre-mode) `a103f11b…`; Phase A.1 onward
STRICT `fd32325e…`, LEVEL_HOLD `28c976b6…`, RECLAIM_ONLY `804b0b31…`.

**STRICT remains behaviourally identical to Phase A despite the source fingerprint
change.** The fingerprint moved only because the shared implementation core gained the
`acceptance_mode` field; the default is `STRICT`, and a default run still reproduces the
Phase A baseline exactly — 29 LONG trades / PF 1.8656360038448085 / Avg R +0.5410 and
14 SHORT trades / PF 0.2309911155042199 / Avg R −0.7143. That reproduction is asserted by
the Phase A.1 runner (which aborts otherwise) and by a dedicated test.

## Data exposure chronology

| Phase | Data used |
|---|---|
| Phase A (baseline) | DEVELOPMENT 2021-2023 only |
| Phase A.1 (acceptance ablation) | DEVELOPMENT 2021-2023 only |

**2024 VALIDATION and 2025-2026 FORWARD_VALIDATION were never loaded, queried,
backtested, inspected or summarized for PB2 at any point in its life.** PB2's 2024 dataset
remains genuinely unseen, and no out-of-sample result contributed to this rejection — it
rests entirely on DEVELOPMENT evidence.

## Governance

Both components are registered `REJECTED`. The platform's existing status guards refuse to
start new research workflows for either:

- `research.optimizer.guard_optimization` → `OPTIMIZATION DISABLED - REJECTED STRATEGY`
- `research.walk_forward.guard_walk_forward` → `WALK-FORWARD DISABLED — REJECTED STRATEGY`

No new guard was required. Historical results stay readable and reproducible:
`run_universal_backtest` applies no status guard, the universal workspace exposes rejected
strategies behind its "Show rejected/research history" toggle, and the Phase A and A.1
reports are unmodified.

## Artifacts

| Phase | Commit | Reports |
|---|---|---|
| A — baseline | `566cc15` | `PHASE_A_BASELINE.md`, `phase_a_baseline.json` |
| A.1 — acceptance ablation | `c907f22` | `PHASE_A1_ACCEPTANCE_ABLATION.md`, `phase_a1_acceptance_ablation.json` |

Research tag: `btc-pb2-v1-rejected`.
