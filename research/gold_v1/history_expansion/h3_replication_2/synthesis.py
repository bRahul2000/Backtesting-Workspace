"""Gold V1 — H3 evidence synthesis (SECONDARY, descriptive). Run only after replication #2 outputs are frozen.

    venv/bin/python research/gold_v1/history_expansion/h3_replication_2/synthesis.py

Preregistered method (H3_REPLICATION_2_PREREGISTRATION.md §Synthesis):
  * independent synthesis = replication #1 (2023-2025) + replication #2 (2017-2021) ONLY; development never pooled;
  * each study's +2R lift d_i with SE_i = (CI_hi − CI_lo) / (2 × 1.96) from its own event-clustered bootstrap CI;
  * fixed-effect inverse-variance estimate  d = Σ w_i d_i / Σ w_i,  w_i = 1/SE_i²,  95% CI d ± 1.96 / sqrt(Σ w_i);
  * heterogeneity: Cochran Q = Σ w_i (d_i − d)², I² = max(0, (Q − 1)/Q); DerSimonian–Laird random-effects estimate
    reported as a sensitivity; both study estimates are always shown next to the pooled figure.
Reads frozen summaries/CSVs only; writes evidence_synthesis.md and synthesis.json.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import json                                                                             # noqa: E402
import math                                                                             # noqa: E402
from pathlib import Path                                                                # noqa: E402

import numpy as np                                                                      # noqa: E402
import pandas as pd                                                                     # noqa: E402

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
GOLD = EXP.parent
sys.path.insert(0, str(GOLD / "h1"))
from h1_report import fmt, p_win                                                        # noqa: E402

Z = 1.96


def rate(df, t):
    k, n = p_win(df, t)
    return k / n if n else np.nan


def study(label, e, c, lifts):
    side = {d: (rate(e[e.direction == d], 2.0) - rate(c[c.direction == d], 2.0)) * 100 for d in ("long", "short")}
    return {"label": label, "events": len(e), **{f"p{int(t)}R": rate(e, t) for t in (1.0, 2.0, 3.0, 4.0)},
            "control_p2R": rate(c, 2.0), "lift": lifts["lift_pp"], "lo": lifts["ci_lo_pp"], "hi": lifts["ci_hi_pp"],
            "mfe32": e["mfe_32"].median(), "mae32": e["mae_32"].median(),
            "c_mfe32": c["mfe_32"].median(), "c_mae32": c["mae_32"].median(),
            "long": side["long"], "short": side["short"]}


def main() -> None:
    dev = study("development 2025-12-23 → 2026-06-02 (not pooled)",
                pd.read_csv(GOLD / "h3" / "h3_events_dev.csv"), pd.read_csv(GOLD / "h3" / "h3_controls_dev.csv"),
                json.loads((GOLD / "h3" / "h3_summary.json").read_text())["lifts"]["2.0"])
    r1 = study("replication #1 2023-01 → 2025-12",
               pd.read_csv(EXP / "h3_replication" / "events.csv"), pd.read_csv(EXP / "h3_replication" / "controls.csv"),
               json.loads((EXP / "h3_replication" / "summary.json").read_text())["lifts"]["2.0"])
    r2 = study("replication #2 2017-06 → 2021-08",
               pd.read_csv(HERE / "events.csv"), pd.read_csv(HERE / "controls.csv"),
               json.loads((HERE / "summary.json").read_text())["lifts"]["2.0"])
    reps = [r1, r2]
    d = np.array([s["lift"] for s in reps])
    se = np.array([(s["hi"] - s["lo"]) / (2 * Z) for s in reps])
    w = 1 / se ** 2
    fe = float((w * d).sum() / w.sum())
    fe_se = float(1 / math.sqrt(w.sum()))
    q = float((w * (d - fe) ** 2).sum())
    i2 = max(0.0, (q - 1) / q) if q > 0 else 0.0
    tau2 = max(0.0, (q - 1) / (w.sum() - (w ** 2).sum() / w.sum()))
    wr = 1 / (se ** 2 + tau2)
    re = float((wr * d).sum() / wr.sum())
    re_se = float(1 / math.sqrt(wr.sum()))
    out = {"fixed_effect": {"lift_pp": fe, "ci_lo_pp": fe - Z * fe_se, "ci_hi_pp": fe + Z * fe_se, "se_pp": fe_se},
           "random_effects_DL": {"lift_pp": re, "ci_lo_pp": re - Z * re_se, "ci_hi_pp": re + Z * re_se, "tau2": tau2},
           "cochran_Q": q, "I2": i2, "weights_share": (w / w.sum()).tolist(),
           "studies": {s["label"]: {"lift": s["lift"], "lo": s["lo"], "hi": s["hi"], "se": float(x), "events": s["events"]}
                       for s, x in zip(reps, se)},
           "total_independent_events": int(r1["events"] + r2["events"])}
    (HERE / "synthesis.json").write_text(json.dumps(out, indent=1) + "\n")
    rows = "\n".join(
        f"| {s['label']} | {s['events']} | {fmt(s['p1R'], True)} | {fmt(s['p2R'], True)} | {fmt(s['p3R'], True)} "
        f"| {fmt(s['p4R'], True)} | {fmt(s['control_p2R'], True)} | {s['lift']:+.1f} | {s['lo']:+.1f} … {s['hi']:+.1f} "
        f"| {fmt(s['mfe32'])} / {fmt(s['c_mfe32'])} | {fmt(s['mae32'])} / {fmt(s['c_mae32'])} | {s['long']:+.1f} / {s['short']:+.1f} |"
        for s in (dev, r1, r2))
    text = f"""# H3 evidence synthesis (secondary, descriptive)

Written by `synthesis.py` after the standalone replication #2 outputs were frozen. The standalone replication #2
result in [report.md](report.md) remains primary. Development is shown for comparison only and **is never pooled**.

## Side by side

| study | events | +1R | +2R | +3R | +4R | control +2R | +2R lift (pp) | 95% CI | MFE32 med (H3 / ctrl) | MAE32 med (H3 / ctrl) | long / short lift (pp) |
|---|---|---|---|---|---|---|---|---|---|---|---|
{rows}

## Independent-replication synthesis (replication #1 + replication #2 only)

The method was preregistered: fixed-effect inverse-variance pooling of the two standalone +2R lifts. Each study's
SE is its bootstrap-CI half-width divided by 1.96.

| estimate | +2R lift (pp) | 95% CI |
|---|---|---|
| replication #1 (2023–2025), {r1['events']} events, weight {out['weights_share'][0] * 100:.0f}% | {r1['lift']:+.2f} | {r1['lo']:+.2f} … {r1['hi']:+.2f} |
| replication #2 (2017–2021), {r2['events']} events, weight {out['weights_share'][1] * 100:.0f}% | {r2['lift']:+.2f} | {r2['lo']:+.2f} … {r2['hi']:+.2f} |
| **fixed-effect pooled**, {out['total_independent_events']} independent events | **{fe:+.2f}** | **{fe - Z * fe_se:+.2f} … {fe + Z * fe_se:+.2f}** |
| random-effects (DerSimonian–Laird), sensitivity | {re:+.2f} | {re - Z * re_se:+.2f} … {re + Z * re_se:+.2f} |

Heterogeneity: Cochran Q = {q:.2f} (1 df), I² = {i2 * 100:.0f}%, τ² = {tau2:.2f}. Both study estimates are shown so the
pooled figure cannot hide disagreement between them.

This synthesis is secondary and descriptive. It does not change the standalone classification of replication #2,
it does not use development, and it does not authorize strategy construction.
"""
    (HERE / "evidence_synthesis.md").write_text(text)
    print(json.dumps(out, default=float))


if __name__ == "__main__":
    main()
