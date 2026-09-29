# Gold V1 — sealed data register

These samples were **not consumed** by Gold V1. They are **available for future, genuinely new hypotheses** (not
H1–H5 or their variants), under a new preregistration. Using one consumes it.

| sample | span (UTC) | status |
|---|---|---|
| Historical holdout | **2021-09-01 → 2022-11-26** (sessions through the one ending 2022-11-25) | **NOT PARSED FOR STRATEGY OUTCOMES · NOT CONSUMED · AVAILABLE FOR FUTURE GENUINELY NEW HYPOTHESES** |
| Validation | **2026-06-03 → 2026-07-26** | **NOT PARSED FOR STRATEGY OUTCOMES · NOT CONSUMED · AVAILABLE FOR FUTURE GENUINELY NEW HYPOTHESES** |
| Final OOS | **2026-07-27 → 2026-09-18** | **NOT PARSED FOR STRATEGY OUTCOMES · NOT CONSUMED · AVAILABLE FOR FUTURE GENUINELY NEW HYPOTHESES** |

## Exact contact history (full disclosure)

No H1–H5 event detection, forward race, control or outcome statistic was ever computed on any of these rows.
Non-strategy contact was limited to the following.

**Historical holdout (2021-09-01 → 2022-11-26):**
- **Data-quality statistics, before it was a holdout.** `history_expansion/HISTORY_QUALITY_AUDIT.md`
  (2026-09-29) parsed these rows for data-quality statistics only: bar counts, gaps, precision, spread, tick volume,
  price range and reopen jumps by calendar year (2021 and 2022). That audit is where the span was first proposed as a
  reserve; no outcome was ever computed on it.
- **Timestamp-only counts.** Session counts per candidate span.
- **Text-only comparisons since designation.** `audit_deep_history.py` compared the rows only as raw text lines
  against the `raw/` snapshot (29,364 / 29,364 identical M15 lines).
- **Kept out of the repair.** The deep-history repair window ends at 2021-08-31 22:00 UTC, before the first holdout
  session, and replication #2's data end at 2021-08-31 20:45 UTC.

**Validation and Final OOS (2026):**
- **Pre-existing file summaries.** The files exist inside Phase 2A (`data/exness/gold/phase2a/`), whose pre-existing
  `manifest.json` carries whole-file bar counts and spread summary statistics from the Phase 2A capture, before
  Gold V1.
- **Development-only analysis.** Every Gold V1 study loaded development rows only, cut at 2026-06-03 00:00 UTC before
  any computation.
- **Text-only comparisons.** The expanded-history audits compared these rows with the new exports only as raw text
  lines (equality counts). No value was parsed or summarised.

## Integrity anchors (SHA-256)

- **Phase 2A M15 / H1** (containing Validation and OOS): `dee9fb6f329c38c5029e2a4c5d79e85fe520a40b3b6b6e66f8958bd0c28ee4e4`
  / `824a2ce046be6becb975ee466941212ba561d04c7e454e91126542660f0d348b`.
- **`history_expansion/raw_full/` M15 / H1** (containing all three samples):
  `4724a019bf2c25c2f03e971034d6986de94174e602c3a15924dc167f3d193e43` /
  `7de0706efccf16eada36f5e3f26ec255eb9e11eb8407c38a650da6d034fc0bc5`.
- **Loading rule.** Any future use must load these spans by timestamp text slice under a new, hashed preregistration,
  and must record the consumption here.
