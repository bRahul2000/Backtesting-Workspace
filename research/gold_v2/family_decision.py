"""Gold V2 round-1 family decision: Holm across the two primary development tests (C1, C4) + each hypothesis's
preregistered development pass rule. Reads the frozen development result.json files only.

    venv/bin/python research/gold_v2/family_decision.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALPHA = 0.05


def holm(pvals: dict[str, float]) -> dict[str, dict]:
    order = sorted(pvals, key=lambda k: pvals[k])
    m, out, stop = len(order), {}, False
    for rank, k in enumerate(order):
        thr = ALPHA / (m - rank)
        reject = (not stop) and pvals[k] <= thr
        if not reject:
            stop = True
        out[k] = {"p_raw": pvals[k], "holm_threshold": thr, "holm_reject": reject, "rank": rank + 1}
    return out


def main() -> None:
    c1 = json.loads((HERE / "c1_round_number/dev/result.json").read_text())
    c4 = json.loads((HERE / "c4_session_momentum/dev/result.json").read_text())
    h = holm({"C1": c1["primary"]["p_one_sided"], "C4": c4["primary"]["p_one_sided_circular_shift"]})
    p1 = c1["primary"]
    c1_rules = {"holm_reject": h["C1"]["holm_reject"], "delta_ge_5pp": p1["delta_pp"] >= 5.0,
                "both_sides_ge_0": all(v["delta_pp"] >= 0 for v in c1["by_side"].values()),
                "loyo_all_gt_0": all(v["delta_pp"] > 0 for v in c1["leave_one_year_out"].values()),
                "resolved_round_ge_400": p1["n_round"] >= 400}
    c1_cost = None
    if "cost" in c1:
        c1_cost = p1["p_rev_round"] >= c1["cost"]["breakeven_p_rev_1to1"]
    p4 = c4["primary"]
    c4_rules = {"holm_reject": h["C4"]["holm_reject"], "effect_ge_threshold": p4["effect_atr"] >= p4["threshold_atr"],
                "long_and_short_contributions_ge_0": p4["long_contribution"] >= 0 and p4["short_contribution"] >= 0,
                "loyo_all_gt_0": all(v["effect_atr"] > 0 for v in c4["leave_one_year_out"].values()),
                "pairs_ge_500": p4["n_pairs"] >= 500}

    def cls(rules, effect_pos):
        if all(rules.values()):
            return "STRUCTURAL PASS"
        return "FAILED (effect <= 0)" if not effect_pos else "NOT PASSED"
    out = {"holm": h,
           "C1": {"rules": c1_rules, "cost_plausible": c1_cost, "decision": cls(c1_rules, p1["delta_pp"] > 0)},
           "C4": {"rules": c4_rules, "decision": cls(c4_rules, p4["effect_atr"] > 0)}}
    (HERE / "family_decision.json").write_text(json.dumps(out, indent=1, default=bool) + "\n")
    print(json.dumps(out, indent=1, default=bool))


if __name__ == "__main__":
    main()
