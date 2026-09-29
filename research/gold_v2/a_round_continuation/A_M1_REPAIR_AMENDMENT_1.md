# A M1 repair — amendment 1 (audit implementation correction; disclosed)

Written after the **first audit run returned FAIL on R6 only** (`m1_repair_audit_run1_FAILED.json`, kept unchanged),
and before any continuation outcome. **No data, rule, removal or criterion changes.** The frozen preregistration
(`A_M1_REPAIR_PREREGISTRATION.md`, `9195817c…`) is not edited.

## What failed and why

R6 flagged six gaps. Every one is **named in the frozen criterion** or documented beforehand, and failed only
because the audit code matched them at the wrong granularity:

| flagged gap (M1 last bar → next bar) | what it is | why the code missed it |
|---|---|---|
| 2018-01-31 14:09 → 02-02 12:59 | preregistered known outage "2018-01-31 14:00" | known outages are listed by **M15 bar start**; M1's last bar is 14:09 (inside the 14:00 M15 bar) |
| 2018-08-27 02:29 → 05:32 | preregistered known outage "2018-08-27 02:15" | same (inside the 02:15 M15 bar) |
| 2018-08-27 09:33 → 10:55 | preregistered known outage "2018-08-27 09:30" | same (inside the 09:30 M15 bar) |
| 2019-03-11/12/13 20:58 → 23:01 (122 min) | the documented 2-hour daily-break variant after the US DST change (`DEEP_HISTORY_REPAIR_AUDIT.md`: New York 17:00 → 19:00) | R6 allows "daily break or variant", but V1's variant classifier caps variants at 120 min at M15 granularity. At M1 the same break measures 122 min (the last bar is 16:59 and the first 19:01, New York) |

## Correction (implementation only)

1. A known outage matches when the M1 gap's last bar falls **inside the listed M15 bar** (floor to 15 min).
2. A daily-break variant at M1 is a gap whose last bar is at New York 16:30–17:15, whose first bar is at 17:45–19:15,
   and which lasts ≤ 150 min. The existing classifier remains for everything else.

The first run's failure and this correction are both reported with the A result.
