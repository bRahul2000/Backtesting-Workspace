# PB2 Phase A.1 — Acceptance Gate Selectivity & Frequency Audit

**Predeclared architecture ablation. Not an optimization — no parameter value was searched.**

**Dataset:** DEVELOPMENT 2021-01-01 .. 2023-12-31 only.
**Question:** is PB2's separate acceptance bar genuinely improving trade quality, or is it
just removing valid reclaim setups?

Three variants were declared in advance and exactly six runs were executed. Nothing was
added after seeing results.

| Variant | Acceptance rule |
|---|---|
| **A — STRICT** | Phase A baseline: the next completed bar must close beyond the structure level **and** beyond the reclaim close. |
| **B — LEVEL_HOLD** | The separate acceptance bar remains, but only has to close beyond the structure level. The expansion requirement is dropped. |
| **C — RECLAIM_ONLY** | The separate acceptance bar is removed entirely; the reclaim candle becomes the entry reference. |

Everything else is untouched: H1 context, structure lookback, displacement thresholds,
retest tolerance and window, stop bounds, RR, pending expiry.

## Implementation policy

The variant is supplied as `acceptance_mode`, a new field on `PB2Parameters` defaulting to
`STRICT`. Because it lives in the parameter payload it participates in the corrected
effective-parameter fingerprint, so **a variant run can never be mistaken for the
baseline**:

| Variant | Effective parameter fingerprint |
|---|---|
| A STRICT | `fd32325e36996c40ba56525122e1061d8f157f7a2d68e6069331ef13875bb40e` |
| B LEVEL_HOLD | `28c976b6a43d2b23ae3518eeb9a894ef9d5e35ce3d690ab9e48a9658b7800c3f` |
| C RECLAIM_ONLY | `804b0b31bddbb8fa88a3a36bbbd998e39de28999c6a82c5f64b5725d6a7d2130` |

`acceptance_mode` is registered as overridable but **never optimizable**
(`optimization_allowed=False`), so it cannot be swept by a later parameter search.

**PB2 default behaviour is unchanged**, and Variant A reproduces the stored Phase A
baseline exactly — 29 LONG trades / PF 1.8656360038448085 / Avg R +0.5410, and 14 SHORT
trades / PF 0.2309911155042199 / Avg R −0.7143. The ablation runner asserts this and
aborts otherwise, and a test asserts the LONG reproduction independently.

One consequence is recorded honestly: adding the mode changed the PB2 **source** hashes,
so the strategy fingerprints in the Phase A report
(`5c4a3f8e…` LONG, `bed29f83…` SHORT) are superseded by `668674ac…` and `1caf727a…`.
Phase A's stored artifacts were **not** overwritten; its *behaviour* reproduces bit-for-bit.

## Six-run results

| Component | Variant | Trades | T/mo | Win rate | PF | Avg R | Total R | PnL | Max DD | Streak | Hold avg/median |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LONG | A STRICT | 29 | 0.91 | 37.93% | 1.866 | **+0.5410** | +15.69 | +$393.18 | 0.77% | 3 | 188 / 105 min |
| LONG | B LEVEL_HOLD | 40 | 1.26 | 30.00% | 1.317 | +0.2225 | +8.90 | +$219.52 | 1.49% | 5 | 175 / 105 min |
| LONG | C RECLAIM_ONLY | 58 | 1.82 | 22.41% | 0.903 | −0.0714 | −4.14 | −$104.66 | 2.26% | 7 | 190 / 120 min |
| SHORT | A STRICT | 14 | 0.44 | 7.14% | 0.231 | −0.7143 | −10.00 | −$249.69 | 0.75% | 3 | 223 / 172 min |
| SHORT | B LEVEL_HOLD | 26 | 0.82 | 23.08% | 0.901 | −0.0769 | −2.00 | −$49.84 | 1.49% | 5 | 203 / 135 min |
| SHORT | C RECLAIM_ONLY | 32 | 1.01 | 25.00% | 1.013 | +0.0090 | +0.29 | +$6.38 | 2.23% | 5 | 219 / 150 min |

**LONG degrades monotonically as the gate is loosened** (+0.54 → +0.22 → −0.07 Avg R).
**SHORT improves monotonically** (−0.71 → −0.08 → +0.01). The two directions disagree,
which is why they are classified separately.

## Funnel comparison

| Stage | LONG A | LONG B | LONG C | SHORT A | SHORT B | SHORT C |
|---|---|---|---|---|---|---|
| Valid displacements | 540 | 462 | 312 | 538 | 341 | 175 |
| Retests | 308 | 263 | 182 | 354 | 223 | 121 |
| Reclaims | 130 | 112 | 79 | 138 | 87 | 45 |
| Acceptance evaluations | 130 | 112 | `NOT_APPLICABLE_ARCHITECTURE_ABLATION` | 138 | 87 | `NOT_APPLICABLE_ARCHITECTURE_ABLATION` |
| Acceptance confirmations | 58 | 91 | `NOT_APPLICABLE_ARCHITECTURE_ABLATION` | 62 | 75 | `NOT_APPLICABLE_ARCHITECTURE_ABLATION` |
| Acceptance failures | 72 | 21 | `NOT_APPLICABLE_ARCHITECTURE_ABLATION` | 76 | 12 | `NOT_APPLICABLE_ARCHITECTURE_ABLATION` |
| Risk-valid structures | 58 | 91 | 79 | 62 | 75 | 45 |
| Risk rejected | 19 | 21 | 3 | 34 | 22 | 2 |
| Pending orders | 39 | 70 | 76 | 28 | 53 | 43 |
| Expired pendings | 6 | 24 | 10 | 12 | 23 | 4 |
| Entries | 29 | 40 | 58 | 14 | 26 | 32 |
| Exits | 29 | 40 | 58 | 14 | 26 | 32 |
| Open at end | 0 | 0 | 0 | 0 | 0 | 0 |

Acceptance pass rate rises from 45% (58/130) under STRICT to 81% (91/112) under
LEVEL_HOLD on the LONG side, and 45% (62/138) to 86% (75/87) on the SHORT side.

**Displacement counts fall as variants trade more.** PB2 blocks new structure detection
while a pending order or position is open, so a looser gate means more time in exposure
and fewer observed opportunities (LONG 540 → 462 → 312). This is a genuine downstream
availability effect, not a change to the displacement rule, and it is why the funnels are
not a clean nested subset.

## Yearly comparison

**LONG**

| Variant | 2021 | 2022 | 2023 |
|---|---|---|---|
| A | n=4, PF 2.99, +1.000R | n=7, PF 0.49, −0.437R | n=18, PF 2.47, +0.819R |
| B | n=5, PF 1.99, +0.600R | n=8, PF 0.42, −0.507R | n=27, PF 1.56, +0.369R |
| C | n=13, PF 0.54, −0.396R | n=13, PF 0.53, −0.413R | n=32, PF 1.30, +0.199R |

**SHORT**

| Variant | 2021 | 2022 | 2023 |
|---|---|---|---|
| A | n=5, PF 0.00, −1.000R | n=6, PF 0.60, −0.333R | n=3, PF 0.00, −1.000R |
| B | n=8, PF 3.00, +1.000R | n=13, PF 0.25, −0.692R | n=5, PF 0.75, −0.200R |
| C | n=11, PF 0.30, −0.636R | n=8, PF 0.60, −0.245R | n=13, PF 2.31, +0.711R |

Extra frequency did **not** create a repeatable cross-year sample on either side. On LONG,
loosening turned 2021 from +1.000R to −0.396R while 2023 halved. On SHORT, B and C are
positive in different years (B in 2021, C in 2023) — the added trades move the good year
around rather than stabilising it. 2022 is negative in all six runs.

## Sample adequacy

| Component | A | B | C |
|---|---|---|---|
| LONG | 29 — `INSUFFICIENT` | 40 — `VERY_SMALL` | 58 — `VERY_SMALL` |
| SHORT | 14 — `INSUFFICIENT` | 26 — `INSUFFICIENT` | 32 — `VERY_SMALL` |

Descriptors only. Nothing here is large enough to claim robustness, and no verdict below
does.

## Incremental-trade analysis

Structures are matched across variants by their **displacement timestamp**, because
RECLAIM_ONLY enters a bar earlier on the same structure and entry-time matching alone
would misread those as new trades.

**LONG**

| vs A | Shared structures | Same structure, different entry | Trades added | Winners | Losers | Total R added | Avg R of added | PF of added | Lost to availability |
|---|---|---|---|---|---|---|---|---|---|
| B | 27 | 0 | 13 | **1** | **12** | **−8.79** | **−0.676** | 0.256 | 2 (−2.01R) |
| C | 18 | 18 | 40 | **5** | **35** | **−20.80** | **−0.520** | 0.397 | 11 (+0.64R) |

Shared structures are untouched by B (total R +17.69 → +17.69), confirming B is an exact
superset of A. Under C the same 18 structures improved slightly (+15.05 → +16.66R) from
entering a bar earlier — but C also admits 40 additional structures that lose 20.80R.

**SHORT**

| vs A | Shared structures | Same structure, different entry | Trades added | Winners | Losers | Total R added | Avg R of added | PF of added | Lost to availability |
|---|---|---|---|---|---|---|---|---|---|
| B | 11 | 0 | 15 | 5 | 10 | **+5.00** | **+0.333** | 1.501 | 3 (−3.00R) |
| C | 6 | 6 | 26 | 5 | 21 | −3.90 | −0.150 | 0.792 | 8 (−4.00R) |

On SHORT the trades strict acceptance removes are *better* than the ones it keeps under B
(+0.333R added vs the baseline's −0.714R), but worse under C. The evidence contradicts
itself.

## Strict-acceptance rejection cohort

Setups that achieved a valid reclaim but failed Variant A's strict acceptance:

| Component | Cohort size | Under B: entries | W | L | Avg R | Total R | Under C: entries | W | L | Avg R | Total R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LONG | 72 | 13 | 1 | 12 | **−0.676** | **−8.79** | 27 | 2 | 25 | **−0.694** | **−18.75** |
| SHORT | 76 | 15 | 5 | 10 | +0.333 | +5.00 | 13 | 4 | 9 | +0.279 | +3.62 |

**This is the direct answer to the phase's question.** On the LONG side the strict gate
discards setups that go on to lose 12-of-13 and 25-of-27 — it is removing mostly bad
trades. On the SHORT side it discards setups that would have been modestly profitable
under both loosenings — there it is removing potentially useful trades.

## Architecture decision

Classification is derived in code from stated criteria, never from the highest PF.

> A loosened variant counts as an improvement only if its sample is at least VERY_SMALL,
> its overall Avg R is positive, the trades it adds over the baseline are themselves
> positive on average, and at least two DEVELOPMENT years are positive. Strict acceptance
> earns its place only if the baseline is positive with at least two positive years and
> both loosenings add at least 10 trades each (≥30 combined) whose Avg R is at least 0.25R
> below the baseline's.

The evidence about a *gate* lives in the population it rejects, so the strict-acceptance
test keys off the incremental trades (53 LONG, 41 SHORT) rather than the baseline's own
trade count — a gate can be demonstrably selective while the surviving sample is still too
small to trade.

### LONG → **A — STRICT ACCEPTANCE EARNS ITS PLACE**

Baseline positive (+0.5410R) with 2 of 3 years positive; both loosenings add trades whose
Avg R sits 1.217R and 1.061R *below* the baseline, across 53 incremental trades. Loosening
the gate increased frequency 1.4× and 2.0× while monotonically destroying expectancy.

This says the acceptance bar is doing real selection work on the long side. **It does not
say PB2 LONG has a tradeable edge** — 29 trades over three years remains `INSUFFICIENT`,
concentrated in 2023, with a negative 2022.

### SHORT → **D — ARCHITECTURE STILL TOO SPARSE / UNRESOLVED**

No variant has a credible positive result: A is −0.714R, B is −0.077R, C is +0.009R on 32
trades (noise). Positive years are 0/3, 1/3 and 1/3. The incremental evidence is
self-contradictory — B's added trades are positive, C's are negative — and the best sample
is 32 trades. There is nothing here to endorse in either direction.

## Limitations

- Every sample is `INSUFFICIENT` or `VERY_SMALL`. No variant supports a robustness claim.
- 2022 is negative in all six runs; the ablation does not address that.
- The LONG and SHORT verdicts disagree, and each rests on tens of trades.
- Variants differ in observed opportunities because of the single-exposure availability
  effect, so funnel stages are not directly subtractable.
- Nothing here recommends a parameter change, and no parameter was searched.

## Data policy

DEVELOPMENT 2021-01-01 .. 2023-12-31 only. The runner refuses any window reaching 2024,
re-checks every trade timestamp after each run, and records the years actually present as
`[2021, 2022, 2023]`. **2024, 2025 and 2026 were never loaded, queried or backtested.**
