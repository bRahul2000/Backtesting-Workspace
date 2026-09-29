# C — amendment 1 (post-outcome statistics plumbing fix; disclosed)

- **The failure.** The first development run (`c_dev_result_run1_nan.json`, kept in the session scratchpad; hashes of
  its events and controls are below) produced Δ = −0.187 σ but **NaN CI and p-value**.
- **The cause.** In `paired_stats` the day-cluster keys used for grouping (numpy datetime64) did not match the keys
  used for reindexing (a timezone-aware array), so every bootstrap sum was NaN.
- **The fix.** Day keys are now ISO date strings for both operations. **No event, control, outcome, threshold, seed
  or specification changed.** The rerun must reproduce the first run's events.csv and controls.csv byte-for-byte and
  the same Δ; this is verified in the result section of `ROUND2_RESULTS.md`.
- **Also reported, not changed:** 152 of 766 development events had **no** control candidate even at the ±30% size
  relaxation. They are extreme gold moves with no USD-explained move of similar size, and are excluded by the frozen
  code, leaving 614 events with controls. The preregistration did not state a zero-candidate rule; the frozen code's
  exclusion is reported as-is.
