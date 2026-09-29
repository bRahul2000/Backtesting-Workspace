# C4 — US → next-Asia session momentum: preregistration

Frozen before any C4 outcome was computed. The only prior execution was `c4_study.py --dry`, which printed pair
counts only: development 741 pairs (151 across a weekend), replication 1,040 (208). No Asia-window return was
computed. Part of the two-hypothesis family in `../FAMILY_PREREGISTRATION.md` (Holm). Implementation: `c4_study.py`
(hash recorded in the family file).

## Mechanism

Information and order-flow persistence from the US trading period into the following Asian session. Gold-specific
evidence of session-level continuation into Asia (Wei, SSRN 7257240) is consistent with:
- late-informed trading and infrequent portfolio rebalancing (Gao et al. 2018, *JFE*; Bogousslavsky 2016);
- an eastward shift of marginal physical-gold pricing.

**Prediction:** the sign of the US-window return predicts the sign of the next Asia-window return.

## Data

- **Development.** The committed slice (`a6a503ff…`). Pairs whose US window starts on or after 2023-01-01 and whose
  Asia window ends before 2025-12-22 23:00 UTC.
- **Replication.** The repaired 2017–2021 file (`e4dc5770…`). US window from 2017-06-01, Asia window before
  2021-08-31 22:00.
- **Sealed data.** No sealed bar exists in either input.

## Exact definitions

| item | definition |
|---|---|
| session (trading day) | the frozen rule: a new session when bar starts are ≥ 60 min apart (the broker day opens 18:00 New York, or 19:00–20:00 in 2017–18) |
| US window | session D's bars starting 08:00 … 16:45 **America/New_York local time** (zoneinfo; DST handled by wall clock). The 08:00 and 16:45 bars must both be present, with ≥ 30 of 36 bars |
| r_US | close(16:45 bar) − open(08:00 bar), USD |
| next-Asia window | session D+1's bars starting 00:00 … 06:45 **UTC** (fixed UTC; unaffected by DST). The 00:00 and 06:45 bars must both be present, with ≥ 24 of 28 bars. D+1 is the next session whatever the calendar gap (weekends and holidays included; weekend pairs are flagged) |
| gap treatment | the interval 17:00 New York → 00:00 UTC (the daily break plus early evening) belongs to neither window and is ignored |
| predictor | s = sign(r_US) ∈ {+1, −1}; days with r_US = 0 are excluded |
| outcome | y = (close(06:45 UTC bar) − open(00:00 UTC bar)) / ATR14, where ATR14 is Wilder ATR(14) of M15 at the bar before the 00:00 bar (a scale known at entry) |
| missing sessions | any window failing its completeness rule drops the pair; nothing is interpolated |

## Primary metric (one)

**Effect = E[s·y] − E[s]·E[y]**, the sample covariance of the US sign with the next-Asia return, in ATR units. It is
the predictive component of a "trade in the US direction" rule, net of the drift × sign-imbalance term.

**Null / control: an exact circular-shift test**
- The US-sign series is circularly shifted against the Asia-outcome series by every k with 5 ≤ k ≤ n − 5 (at least
  one trading week).
- This preserves exactly:
  - the marginal distribution, serial dependence, volatility clustering, drift and calendar structure of the
    next-Asia returns;
  - the serial dependence of the US signs.

  It breaks only the alignment between a US session and its following Asia session.
- One-sided p = (1 + #{null ≥ observed}) / (1 + #shifts). It is deterministic (no RNG) and enters the Holm family.

**CI.** A week-block bootstrap (ISO weeks of the US date, resampled with replacement, 5,000 draws, seed 20260929,
95% percentile).

## Secondary (they cannot rescue a failed primary)

- the long contribution E[y | s=+1] − E[y] and the short contribution E[y] − E[y | s=−1];
- corr(s, y);
- by-year effects and leave-one-year-out;
- the effect excluding weekend pairs.

## Power and minimum sample

- **Expected sample.** 741 development pairs.
- **Power.** The detectable correlation is ≈ 2.8/√741 ≈ **0.10**. The literature's gold lag-1 session value is about
  0.13, so the test is adequately powered for an effect of the reported size and not for smaller ones.
- **Minimum usable sample.** ≥ 500 pairs.

## Cost screening (before outcomes)

- **Horizon.** 7 hours, one trade per day.
- **Scale.** Window σ ≈ several M15 ATRs (√28 bars). Spread is recorded in development and empty in replication.
- **Burden.** The round-trip spread per trade is about 3–11% of **one** M15 ATR, so it is small relative to a 7-hour
  window.

## Practical threshold

The effect must be ≥ **2 × median(spread_entry / ATR14_entry)** over the development pairs: costs covered twice, in
ATR units. It is computed from non-outcome inputs (spread and ATR at entry) by a frozen formula, and it is reused
numerically for replication, whose spread is unavailable.

## Pass rules

- **Development: STRUCTURAL PASS**, only if **all** of these hold:
  1. Holm-adjusted rejection within the family (α = 0.05, one-sided);
  2. effect ≥ the practical threshold;
  3. long contribution ≥ 0 and short contribution ≥ 0;
  4. every leave-one-year-out effect > 0;
  5. ≥ 500 pairs.
- **Replication** (repaired 2017-06 → 2021-08; identical code; the practical threshold is passed numerically from the
  development result). It **PASSES** only if circular-shift one-sided p < 0.05, effect ≥ threshold, and both
  contributions ≥ 0. Otherwise **FAILED** (effect ≤ 0) or **INCONCLUSIVE**, and C4 is closed without rescue.
  Replication is pre-2022, so a post-2022-only effect would correctly fail here.
- **Forbidden after outcomes:**
  - other US or Asia windows;
  - positive-only or negative-only US days;
  - magnitude thresholds on r_US;
  - volatility, weekday or trend filters;
  - a different null.
