"""Gold V2 round-2 family decision: Holm across exactly two primary tests (A first independent test, C development)
plus each hypothesis's preregistered pass rule. Reads frozen result.json files only.

    venv/bin/python research/gold_v2/round2_family_decision.py
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ALPHA = 0.05
C_THRESHOLD = None  # read from the C development result (frozen formula value)


def holm(p: dict[str, float]) -> dict:
    order = sorted(p, key=p.get)
    out, stop = {}, False
    for r, k in enumerate(order):
        thr = ALPHA / (len(order) - r)
        rej = (not stop) and p[k] <= thr
        stop = stop or not rej
        out[k] = {"p_raw": p[k], "holm_threshold": thr, "holm_reject": rej}
    return out


def main() -> None:
    a = json.loads((HERE / "a_round_continuation/first_test/result.json").read_text())
    c = json.loads((HERE / "c_usd_residual/dev/result.json").read_text())
    pa, pc = a["primary_from_above"], c["primary"]
    h = holm({"A": pa["p_one_sided"], "C": pc["p_one_sided"]})
    a_rules = {"holm_reject": h["A"]["holm_reject"], "delta_ge_5pp": pa["delta_pp"] >= 5.0,
               "resolved_round_ge_300": pa["n_round"] >= 300,
               "loyo_all_gt_0": all(v["delta_pp"] > 0 for v in a["leave_one_year_out"].values())}
    thr = c["info"]["threshold_sigma"]
    c_rules = {"holm_reject": h["C"]["holm_reject"], "delta_ge_threshold": pc["delta_sigma"] >= thr,
               "up_and_down_ge_0": c["up_moves"]["delta_sigma"] >= 0 and c["down_moves"]["delta_sigma"] >= 0,
               "loyo_2023_2024_gt_0": all(v["delta_sigma"] > 0 for v in c["leave_one_year_out"].values()),
               "events_ge_500": pc["n_events"] >= 500}
    a_dec = ("INDEPENDENT FIRST CONFIRMATION PASSED" if all(a_rules.values())
             else ("FAILED" if pa["delta_pp"] <= 0 else "NOT PASSED"))
    c_dec = "DEVELOPMENT PASS" if all(c_rules.values()) else ("FAILED" if pc["delta_sigma"] <= 0 else "NOT PASSED")
    out = {"holm": h, "A": {"rules": a_rules, "decision": a_dec}, "C": {"rules": c_rules, "threshold_sigma": thr,
                                                                        "decision": c_dec}}
    (HERE / "round2_family_decision.json").write_text(json.dumps(out, indent=1, default=bool) + "\n")
    print(json.dumps(out, indent=1, default=bool))


if __name__ == "__main__":
    main()
