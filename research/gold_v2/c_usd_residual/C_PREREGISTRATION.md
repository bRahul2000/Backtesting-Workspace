# C — Gold-vs-USD residual reversal: preregistration

A new external-information family. **No C outcome has been computed anywhere.** The development and replication
years were used by Gold V1 and round 1 for other XAUUSDm-only hypotheses; this is disclosed. The only execution
before freezing was `c_study.py --dry`: counts and the cost scale.

## Mechanism

A large gold move that the **contemporaneous USD move does not explain** contains a non-fundamental, idiosyncratic
(liquidity or order-imbalance) component that should partially reverse. The fundamental, USD-explained component
persists. The analogue is short-term reversal concentrated in the residual, non-fundamental return (Da, Liu &
Schaumburg 2014, *MS*). **This is not generic gold mean reversion.** The control holds gold's own move size,
direction, volatility regime and time of day fixed, so the USD residual is the only differentiating information.

**Caveat, disclosed:** the USD factor explains only about 13–22% of gold M15 variance, so "residual" is not purely
"non-fundamental" for gold.

## Data

- **Series.** XAUUSDm and **DXYm (the PRIMARY USD factor)** M1 from `data/raw/`, verified by SHA256SUMS and
  aggregated to the UTC M15 grid.
- **Development.** Events in [2023-01-01, 2025-01-01). Warm-up bars from 2022-11-27 23:00 are state only.
- **Replication.** Events in [2025-01-01, 2026-06-02 20:00). Warm-up from 2024-10-01 is state only, taken from
  development-period prices; the forward windows lie inside the data, which ends before 2026-06-03.
- **Sealed data.** Nothing from 2026-06-03 onward is loaded.

## Exact model (ONE; every number chosen before outcomes)

| item | definition | why this number |
|---|---|---|
| bars | common M15 bars where both XAU and DXY have a bar; a missing cross-market bar drops that bar | same-clock alignment is 99.98% (audit) |
| returns | g = Δ log close(XAU), u = Δ log close(DXY), **only between consecutive same-session bars** (15 min apart) | no returns across breaks or weekends |
| rolling state | from the **previous 480 valid returns, excluding t** (≈ 20 sessions): β = cov(g, u)/var(u), α = mean(g) − β·mean(u), sd_e = std of the previous 480 residuals, sd_g = std(g) | ≈ one trading month: stable, yet adaptive; the same 20-session span as the V1/V2 lookbacks |
| residual | e_t = g_t − (α + β·u_t); z_t = e_t / sd_e | causal |
| event | \|z_t\| ≥ **2.5** **and** sign(e_t) = sign(g_t) (the gold move itself carries the residual) | 2.5σ ≈ the 1% two-sided tail; about 630 per year in the power screen; not tuned on outcomes |
| spacing | at most one event per 8 bars (the first qualifying bar) | no overlapping outcome windows |
| direction | expected reversal: s = −sign(g_t) | — |
| horizon / outcome | entry at the **open of bar t+1**, exit at the **close of bar t+8** (2 h, all bars consecutive in the session, otherwise the bar is not eligible). y = s · log(exit/entry) / sd_g,t (gold σ units) | 2 h is long relative to the M1/M15 spread burden and short enough for liquidity reversal |
| volatility regime | sd_g,t relative to the median sd_g of the previous 2,400 valid bars: high if > 1.25×, low if < 0.8×, else mid; bars without enough history are excluded | causal regime |
| time of day | UTC buckets: 00–07 (Asia), 07–12 (London), 12–17 (NY/overlap), 17–24 (late) | — |
| **controls** | 5 per event (seed 20261001; with replacement only if fewer than 5 candidates) from the same period's eligible bars with **\|z\| < 1** (USD-explained moves), the **same gold direction**, the **same time bucket**, the **same volatility regime**, and **\|g\|/sd_g within ±15%** of the event's (±30% if fewer than 5; relaxations counted). Not within ±8 bars of any event. The control outcome y_c uses the same entry, exit and s = −sign(g_c) | isolates the USD-residual information while matching gold's own move and state |

## Primary metric (one)

**Δ = mean over events of (y_event − mean y of its controls)**, in gold-σ units.

- **CI.** A day-clustered bootstrap: 5,000 draws, seed 20261001, 95% percentile interval.
- **p-value.** One-sided (H1: Δ > 0), normal approximation. It enters the Holm family.

## Practical threshold (cost-based, frozen formula)

Δ ≥ **2 × median over development events of spread_t / (price_t · sd_g,t)**: the M15 bar's last M1 spread × 0.001,
in σ units. **Development dry run: 0.224 σ** (median cost 0.112 σ). **The development numeric threshold is reused
unchanged for replication.**

## Power and sample

- **Expected sample.** About 766 development events (374 in 2023, 392 in 2024; 366 up, 400 down) and about 564
  replication events.
- **Power.** SE ≈ √(8 + 8/5)/√766 ≈ 0.112 σ, so the detectable Δ ≈ **0.31 σ**. **Power at the 0.224 σ threshold is
  about 45%, disclosed.**
- **Minimum usable sample.** ≥ 500 development events and ≥ 400 replication events.

## Pass rules

- **Development: PASS** only if **all** of these hold:
  1. Holm rejection in the round-2 family;
  2. Δ ≥ 0.224 σ (the frozen formula's development value);
  3. Δ ≥ 0 for up-moves and for down-moves;
  4. leave-one-year-out Δ > 0 for both 2023 and 2024;
  5. ≥ 500 events.
- **Replication** (2025-01 → 2026-06-02; identical code; runs automatically only after a development pass). It
  **PASSES** only if one-sided p < 0.05, Δ ≥ 0.224 σ, both directions ≥ 0, and ≥ 400 events. Otherwise C closes.
- **USDJPYm SECONDARY (non-decisional).** The identical pipeline with USDJPYm as the factor, on the same periods. It
  is reported only as a compatibility check of the direction of the DXY finding. It **cannot** make C pass, replace
  DXY, redefine the residual or justify other thresholds. **If DXY fails, C fails.**
- **Forbidden after outcomes:**
  - other z thresholds, windows or horizons;
  - other proxies as primary;
  - direction, session or volatility subsets;
  - magnitude filters;
  - a different control.
