"""PB1 Phase B.1 report generation.

Read-only: consumes the persisted Phase 3B optimizer artifacts written by
research.pb1_phase_b1_core_structure_search (the OptimizationStore run under
experiments/optimizations.sqlite3, plus the rich per-candidate metrics at
reports/pb1/phase_b1_candidate_metrics.json). Runs no backtests itself.
"""
from __future__ import annotations

import json
from pathlib import Path
from statistics import median
from typing import Any

from research.optimizer import OptimizationStore, apply_analysis_filters, stability_for
from research.pb1_phase_b1_core_structure_search import (
    BASELINE_AVERAGE_R, BASELINE_PF, BASELINE_TOTAL_R, BASELINE_TRADES,
    OPTIMIZATION_ID, RICH_METRICS_PATH, SEARCH_PARAMETERS, STORE_PATH, VIABILITY,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "pb1" / "phase_b1_report.json"

VIABILITY_LABELS = ("trades>=300", "trades_per_month>=8", "pf>1.00", "avg_r>0", "max_dd<=10")


def load() -> tuple[Any, list[Any], dict[str, dict[str, Any]]]:
    store = OptimizationStore(STORE_PATH)
    run = store.load_run(OPTIMIZATION_ID)
    candidates = [c for c in store.load_candidates(OPTIMIZATION_ID) if c.status != "FAILED"]
    rich = json.loads(RICH_METRICS_PATH.read_text())
    return run, candidates, rich


def viability_view(rich_row: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "trades>=300": rich_row["closed_trades"] >= 300,
        "trades_per_month>=8": rich_row["trades_per_month"] >= 8,
        "pf>1.00": rich_row["profit_factor"] is not None and rich_row["profit_factor"] > 1.00,
        "avg_r>0": rich_row["average_r"] > 0,
        "max_dd<=10": rich_row["max_drawdown_percent"] <= 10,
    }
    years = rich_row["yearly_statistics"]
    positive_years = [year for year, stats in years.items() if stats["average_r"] > 0]
    positive_pnl_total = sum(stats["pnl"] for stats in years.values() if stats["pnl"] > 0)
    one_year_dependency = None
    if positive_pnl_total > 0:
        for year, stats in years.items():
            if stats["pnl"] > 0 and stats["pnl"] / positive_pnl_total > 0.80:
                one_year_dependency = year
    return {
        "checks": checks, "meets_all_viability": all(checks.values()),
        "positive_avg_r_years": positive_years, "positive_avg_r_year_count": len(positive_years),
        "one_year_dependency_year": one_year_dependency,
    }


def parameter_surface(rich: dict[str, dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    names = [p.name for p in SEARCH_PARAMETERS]
    surfaces: dict[str, list[dict[str, Any]]] = {}
    for name in names:
        by_value: dict[Any, list[dict[str, Any]]] = {}
        for row in rich.values():
            by_value.setdefault(row["parameters"][name], []).append(row)
        rows = []
        for value, group in sorted(by_value.items()):
            pf = [g["profit_factor"] for g in group if g["profit_factor"] is not None]
            rows.append({
                "value": value, "n": len(group),
                "median_pf": median(pf) if pf else None,
                "median_average_r": median(g["average_r"] for g in group),
                "median_trades_per_month": median(g["trades_per_month"] for g in group),
                "median_max_dd": median(g["max_drawdown_percent"] for g in group),
                "profitable_count": sum(1 for g in group if g["profit_factor"] and g["profit_factor"] > 1.0),
            })
        surfaces[name] = rows
    return surfaces


def select_stable_regions(candidates: list[Any], rich: dict[str, dict[str, Any]],
                          stability: dict[str, dict[str, Any]], *, limit: int = 3) -> list[dict[str, Any]]:
    """Section 7: neighborhood robustness first, not peak performance.

    Candidate for a "stable region representative" must: be a real, executed
    candidate; have a stability classification of Broad Plateau or Moderate
    Stability; carry no isolated-peak or fragility warning; and meet the full
    viability view (section 5). BOUNDARY SENSITIVITY is not itself
    disqualifying here — with only 3-4 tested values per dimension almost
    every grid point sits at a boundary of at least one parameter, so treating
    it as an exclusion would empty the pool; it is instead reported per
    representative and discussed in the parameter-surface findings.
    Representatives are chosen to be spread across distinct impulse/
    confirmation values rather than adjacent points.
    """
    pool = []
    for c in candidates:
        s = stability[c.candidate_id]
        v = viability_view(rich[c.candidate_id])
        if s["classification"] not in ("Broad Plateau", "Moderate Stability"):
            continue
        if any(w in s["warnings"] for w in ("ISOLATED PEAK PATTERN", "FRAGILITY WARNING: UNSTABLE NEIGHBORING RESULTS")):
            continue
        if not v["meets_all_viability"]:
            continue
        pool.append((c, s, v))
    pool.sort(key=lambda item: (-(item[1]["stability_score"] or 0), -(item[0].average_r or -9)))
    chosen: list[dict[str, Any]] = []
    seen_keys: set[tuple] = set()
    for c, s, v in pool:
        key = (c.parameters["impulse_minimum_range_atr"], c.parameters["confirmation_minimum_body_percent"])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        chosen.append({"candidate": c, "stability": s, "viability": v})
        if len(chosen) >= limit:
            break
    return chosen


def build_report() -> dict[str, Any]:
    run, candidates, rich = load()
    stability = {c.candidate_id: stability_for(c, candidates, SEARCH_PARAMETERS) for c in candidates}
    filtered = apply_analysis_filters(candidates, **VIABILITY)
    viable = [c for c in filtered if c.status != "FILTERED"]

    by_pf = sorted((c for c in candidates if c.profit_factor is not None), key=lambda c: c.profit_factor, reverse=True)
    by_avg_r = sorted((c for c in candidates if c.average_r is not None), key=lambda c: c.average_r, reverse=True)
    by_dd_viable = sorted((c for c in viable if c.max_drawdown is not None), key=lambda c: c.max_drawdown)
    by_stability = sorted(
        (c for c in candidates if stability[c.candidate_id]["stability_score"] is not None),
        key=lambda c: stability[c.candidate_id]["stability_score"], reverse=True,
    )

    regions = select_stable_regions(candidates, rich, stability)

    pf_gt_1 = sum(1 for c in candidates if c.profit_factor and c.profit_factor > 1.0)
    avg_r_gt_0 = sum(1 for c in candidates if c.average_r and c.average_r > 0)

    plateau_count = sum(1 for s in stability.values() if s["classification"] == "Broad Plateau")
    moderate_count = sum(1 for s in stability.values() if s["classification"] == "Moderate Stability")
    fragile_count = sum(1 for s in stability.values() if s["classification"] == "Fragile Region")

    def describe(c) -> dict[str, Any]:
        row = rich[c.candidate_id]
        return {
            "parameters": c.parameters, "parameter_fingerprint": c.parameter_fingerprint,
            "closed_trades": row["closed_trades"], "trades_per_month": row["trades_per_month"],
            "profit_factor": row["profit_factor"], "average_r": row["average_r"],
            "total_r": row["total_r"], "pnl": row["pnl"], "max_dd": row["max_drawdown_percent"],
            "stability": stability[c.candidate_id],
        }

    report = {
        "optimization_id": OPTIMIZATION_ID,
        "baseline": {"trades": BASELINE_TRADES, "pf": BASELINE_PF, "average_r": BASELINE_AVERAGE_R,
                     "total_r": BASELINE_TOTAL_R},
        "run": run.__dict__ if run else None,
        "generated_candidates": run.candidate_count if run else None,
        "successful_candidates": len(candidates),
        "unique_fingerprints": len({c.parameter_fingerprint for c in candidates}),
        "candidates_pf_gt_1": pf_gt_1, "candidates_avg_r_gt_0": avg_r_gt_0,
        "candidates_meeting_full_viability": len(viable),
        "stability_distribution": {"Broad Plateau": plateau_count, "Moderate Stability": moderate_count,
                                   "Fragile Region": fragile_count,
                                   "Insufficient Neighbors": len(candidates) - plateau_count - moderate_count - fragile_count},
        "highest_pf_candidate": describe(by_pf[0]) if by_pf else None,
        "highest_average_r_candidate": describe(by_avg_r[0]) if by_avg_r else None,
        "lowest_dd_viable_candidate": describe(by_dd_viable[0]) if by_dd_viable else None,
        "highest_stability_candidate": describe(by_stability[0]) if by_stability else None,
        "stable_region_representatives": [
            {**describe(item["candidate"]), "viability": item["viability"],
             "yearly_statistics": rich[item["candidate"].candidate_id]["yearly_statistics"],
             "long_statistics": rich[item["candidate"].candidate_id]["long_statistics"],
             "short_statistics": rich[item["candidate"].candidate_id]["short_statistics"]}
            for item in regions
        ],
        "parameter_surfaces": parameter_surface(rich),
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=False, default=str))
    return report


if __name__ == "__main__":
    r = build_report()
    print(f"generated={r['generated_candidates']} successful={r['successful_candidates']} "
          f"unique={r['unique_fingerprints']} pf_gt_1={r['candidates_pf_gt_1']} "
          f"avg_r_gt_0={r['candidates_avg_r_gt_0']} viable={r['candidates_meeting_full_viability']} "
          f"stable_regions_found={len(r['stable_region_representatives'])}")
