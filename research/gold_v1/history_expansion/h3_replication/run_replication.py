"""Gold V1 — frozen H3 independent replication on 2023-01-01 → 2025-12-22 (Exness XAUUSDm M15).

    venv/bin/python research/gold_v1/history_expansion/h3_replication/run_replication.py [--detect-only]

Implements H3_REPLICATION_PREREGISTRATION.md. The H3 rules, forward race, controls and bootstrap are the frozen
development functions, imported unchanged (bytecode writing disabled so frozen folders stay byte-identical):
  h1_study.features / forward / wilson,  h3_study.h3_features / detect / controls / h3_gate,  h1_report.lift / p_win
Replication-specific code is limited to the data window: loading the text slice, keeping only events whose
acceptance bar lies in the replication window, removing warm-up bars from the control pool, and reporting.
`--detect-only` prints event counts (no outcomes) to prove the frozen code runs on this data.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import json                                                                             # noqa: E402
from pathlib import Path                                                                # noqa: E402

import numpy as np                                                                      # noqa: E402
import pandas as pd                                                                     # noqa: E402

HERE = Path(__file__).resolve().parent
GOLD = HERE.parents[1]
sys.path.insert(0, str(GOLD / "h1"))
sys.path.insert(0, str(GOLD / "h3"))
import h1_study as h1                                                                   # noqa: E402
import h3_study as h3                                                                   # noqa: E402
from h1_report import fmt, lift, p_win                                                  # noqa: E402

SLICE = HERE / "data" / "xauusd_XAUUSDm_M15_h3_replication_slice.csv"
REPL_START = pd.Timestamp("2023-01-01 00:00", tz="UTC")      # first 2023 session opens 2023-01-02 23:00 UTC
REPL_END_EXCL = pd.Timestamp("2025-12-22 23:00", tz="UTC")   # development session opens here
TARGETS_REPORTED = (1.0, 2.0, 3.0, 4.0)
# decision thresholds (preregistered)
MIN_LIFT_PP = 5.0            # practical magnitude of the pooled +2R lift
FAIL_CI_HI_PP = 3.0          # CI upper bound below this rules out a practically meaningful effect
SIDE_FLOOR_PP = -5.0         # a side lift below this is "catastrophically contradictory"
# known missing-bar holes inside the loaded slice (HISTORY_QUALITY_AUDIT.md §4B): (last bar before, first bar after)
HOLES = [("2025-01-03 11:45", "2025-01-03 12:45"), ("2025-04-14 14:00", "2025-04-14 14:30"),
         ("2025-10-16 15:00", "2025-10-16 17:45"), ("2025-11-28 08:00", "2025-11-28 08:45"),
         ("2025-12-07 23:15", "2025-12-07 23:45")]


def load_slice() -> pd.DataFrame:
    raw = pd.read_csv(SLICE)
    raw["time"] = pd.to_datetime(raw["timestamp"], format="%Y.%m.%d %H:%M:%S", utc=True)
    assert raw["time"].min() >= pd.Timestamp("2022-11-27 23:00", tz="UTC") and raw["time"].max() < REPL_END_EXCL
    assert raw["time"].is_monotonic_increasing and not raw["time"].duplicated().any()
    return raw.drop(columns=["timestamp"]).reset_index(drop=True)


def hole_flags(f: pd.DataFrame, events: pd.DataFrame) -> list[bool]:
    """Provenance only: does the event's 20-session percentile lookback (the session 20 before the compression
    session → the acceptance bar) contain a known missing-bar hole?"""
    tday = f["tday"].to_numpy()
    first_bar = f.groupby("tday")["time"].first()
    holes = [pd.Timestamp(a, tz="UTC") for a, _ in HOLES]
    out = []
    for e in events.itertuples():
        k_day = tday[e.compression_index]
        lo = first_bar.get(k_day - 20, first_bar.iloc[0])
        hi = f["time"].iloc[e.signal_index]
        out.append(any(lo <= h <= hi for h in holes))
    return out


def rate(df, t):
    k, n = p_win(df, t)
    return k / n if n else np.nan


def wilson_text(df, t):
    k, n = p_win(df, t)
    lo, hi = h1.wilson(k, n)
    return f"{fmt(k / n if n else np.nan, True)} ({fmt(lo, True)}–{fmt(hi, True)}, n={n})"


def subset_controls(c, e):
    return c[c["event_signal_index"].isin(e["signal_index"])]


def table_row(label, e, c):
    L = lift(e, c, 2.0) if len(e) and len(c) else None
    return {"period": label, "events": len(e), "controls": len(c),
            **{f"p{int(t)}R": rate(e, t) for t in TARGETS_REPORTED},
            "control_p2R": rate(c, 2.0),
            "lift_2R_pp": L["lift_pp"] if L else np.nan,
            "ci_lo_pp": L["ci_lo_pp"] if L else np.nan, "ci_hi_pp": L["ci_hi_pp"] if L else np.nan,
            "median_mfe32": e["mfe_32"].median(), "median_mae32": e["mae_32"].median(),
            "control_median_mfe32": c["mfe_32"].median(), "control_median_mae32": c["mae_32"].median(),
            "long": int((e["direction"] == "long").sum()), "short": int((e["direction"] == "short").sum())}


def decide(pooled, years, side_lifts, e, c) -> tuple[str, dict]:
    lift_pp, lo, hi = pooled["lift_2R_pp"], pooled["ci_lo_pp"], pooled["ci_hi_pp"]
    year_pos = sum(1 for y in years if y["lift_2R_pp"] > 0)
    best = max(years, key=lambda y: y["lift_2R_pp"])["period"]
    rest_e = e[e["year"].astype(str) != str(best)]
    rest_c = subset_controls(c, rest_e)
    loo = (rate(rest_e, 2.0) - rate(rest_c, 2.0)) * 100
    tests = {
        "a_pooled_lift_positive_ci_above_0": bool(lift_pp > 0 and lo > 0),
        "b_pooled_lift_ge_5pp": bool(lift_pp >= MIN_LIFT_PP),
        "c1_positive_in_at_least_2_of_3_years": bool(year_pos >= 2),
        "c2_positive_without_best_year": bool(loo > 0),
        "d_no_side_below_minus_5pp": bool(all(v >= SIDE_FLOOR_PP for v in side_lifts.values())),
        "e_median_mfe32_event_ge_control": bool(e["mfe_32"].median() >= c["mfe_32"].median()),
    }
    info = {"years_positive": year_pos, "best_year": best, "lift_without_best_year_pp": loo}
    if lift_pp <= 0 or hi < FAIL_CI_HI_PP:
        return "FAILED TO REPLICATE", {**tests, **info}
    if all(tests.values()):
        return "REPLICATED", {**tests, **info}
    return "INCONCLUSIVE", {**tests, **info}


def main(detect_only: bool = False) -> None:
    dev = load_slice()
    base = h1.features(dev)
    f = h3.h3_features(base)
    all_events, counts, acc = h3.detect(f)
    in_window = (all_events["signal_time"] >= REPL_START) & (all_events["signal_time"] < REPL_END_EXCL)
    events = all_events[in_window].reset_index(drop=True)
    counts["events_in_warmup_excluded"] = int((~in_window).sum())
    if detect_only:
        print(json.dumps(counts), "replication-window events:", len(events),
              "first", events["signal_time"].min(), "last", events["signal_time"].max())
        return

    gate = h3.h3_gate(dev, f, all_events)      # invariance/causality checked on the full, unfiltered detection
    gate["result"] = "PASS" if all(v["pass"] for v in gate.values()) else "BLOCKED"
    (HERE / "gate.json").write_text(json.dumps(gate, indent=1, default=str) + "\n")
    if gate["result"] != "PASS":
        raise SystemExit("REPLICATION GATE BLOCKED")

    fw = [h1.forward(f, int(e.entry_index), 1 if e.direction == "long" else -1, e.entry, e.risk)
          for e in events.itertuples()]
    events = pd.concat([events, pd.DataFrame(fw)], axis=1)
    events["year"] = events["signal_time"].dt.year
    events["month"] = events["signal_time"].dt.strftime("%Y-%m")
    events["lookback_contains_hole"] = hole_flags(f, events)

    f_ctrl = f.copy()                                                  # warm-up bars are never control candidates
    f_ctrl.loc[f_ctrl["time"] < REPL_START, "atr_pct"] = np.nan
    ctrl = h3.controls(f_ctrl, events, acc)
    ctrl["year"] = ctrl["month"].str[:4].astype(int)

    events.to_csv(HERE / "events.csv", index=False)
    ctrl.to_csv(HERE / "controls.csv", index=False)

    years = [table_row(str(y), events[events.year == y], subset_controls(ctrl, events[events.year == y]))
             for y in (2023, 2024, 2025)]
    pooled = table_row("2023-2025 pooled", events, ctrl)
    pd.DataFrame(years + [pooled]).to_csv(HERE / "yearly_results.csv", index=False)
    months = []
    for m, em in events.groupby("month"):
        cm = subset_controls(ctrl, em)
        months.append({"month": m, "events": len(em), "p2R": rate(em, 2.0), "control_p2R": rate(cm, 2.0),
                       "diff_2R_pp": (rate(em, 2.0) - rate(cm, 2.0)) * 100, "median_mfe32": em["mfe_32"].median(),
                       "median_mae32": em["mae_32"].median()})
    months = pd.DataFrame(months)
    months.to_csv(HERE / "monthly_results.csv", index=False)

    lifts = {t: lift(events, ctrl, t) for t in TARGETS_REPORTED}
    side = {d: (rate(events[events.direction == d], 2.0) - rate(ctrl[ctrl.direction == d], 2.0)) * 100
            for d in ("long", "short")}
    decision, tests = decide(pooled, years, side, events, ctrl)

    dev_e = pd.read_csv(GOLD / "h3" / "h3_events_dev.csv")
    dev_c = pd.read_csv(GOLD / "h3" / "h3_controls_dev.csv")
    dev_row = table_row("development 2025-12-23 → 2026-06-02 (frozen H3 result)", dev_e, dev_c)
    dev_side = {d: (rate(dev_e[dev_e.direction == d], 2.0) - rate(dev_c[dev_c.direction == d], 2.0)) * 100
                for d in ("long", "short")}

    summary = {"decision": decision, "tests": tests, "gate": gate["result"], "counts": counts,
               "events": len(events), "controls": len(ctrl), "unique_control_bars": int(ctrl.signal_index.nunique()),
               "lifts": {str(t): {k: (list(v) if isinstance(v, tuple) else v) for k, v in L.items()}
                         for t, L in lifts.items()},
               "side_lift_2R_pp": side, "pooled": pooled, "years": years,
               "hole_flagged_events": int(events["lookback_contains_hole"].sum())}
    (HERE / "summary.json").write_text(json.dumps(summary, indent=1, default=float) + "\n")
    write_report(events, ctrl, counts, gate, lifts, side, years, pooled, months, decision, tests, dev_row, dev_side)
    print(decision, json.dumps(tests, default=float))


def write_report(e, c, counts, gate, lifts, side, years, pooled, months, decision, tests, dev_row, dev_side):
    def yrow(r):
        return (f"| {r['period']} | {r['events']} | {r['controls']} | {fmt(r['p1R'], True)} | {fmt(r['p2R'], True)} "
                f"| {fmt(r['p3R'], True)} | {fmt(r['p4R'], True)} | {fmt(r['control_p2R'], True)} "
                f"| {r['lift_2R_pp']:+.1f} | {r['ci_lo_pp']:+.1f} … {r['ci_hi_pp']:+.1f} | {fmt(r['median_mfe32'])} "
                f"| {fmt(r['median_mae32'])} | {r['long']} / {r['short']} |")
    exc = []
    for name, df in (("H3 events", e), ("controls", c)):
        for hz in h1.HORIZONS:
            exc.append(f"| {name} | {hz} | {fmt(df[f'mfe_{hz}'].median())} | {fmt(df[f'mfe_{hz}'].mean())} "
                       f"| {fmt(df[f'mae_{hz}'].median())} | {fmt(df[f'mae_{hz}'].mean())} |")
        exc.append(f"| {name} | until −1R | {fmt(df['mfe_to_stop'].median())} | {fmt(df['mfe_to_stop'].mean())} | — | — |")
    amb_e = int((e[[f"r_{t}" for t in h1.TARGETS]] == "ambiguous").any(axis=1).sum())
    amb_c = int((c[[f"r_{t}" for t in h1.TARGETS]] == "ambiguous").any(axis=1).sum())
    cons = {t: ((e[f"r_{t}"] == "win").sum() / max(1, e[f"r_{t}"].isin(["win", "loss", "ambiguous"]).sum()))
            for t in TARGETS_REPORTED}
    trunc = int(e["r_2.0"].isin(["none", "truncated"]).sum())
    p0, n2 = lifts[2.0]["control_p"], lifts[2.0]["event_n"]
    mde = (1.96 + 0.84) * np.sqrt(p0 * (1 - p0) * (1 / n2 + 1 / (5 * n2))) * 100
    t_lbl = {True: "PASS", False: "FAIL"}
    report = f"""# Gold V1 — H3 independent multi-year replication

- **Data:** Exness XAUUSDm M15, the expanded MT5 history. Only the text slice `data/…_h3_replication_slice.csv` was
  loaded: warm-up from the session opening 2022-11-27 23:00 UTC, and events in sessions from 2023-01-02 23:00 UTC
  through the session ending 2025-12-22 21:45 UTC.
- **Never loaded:** the artifact era, the reserved 2021-09 → 2022-11 holdout, the development period, the sealed 2026
  validation/OOS windows and later bars.
- **Rules:** the H3 rules, forward race, controls and bootstrap are the frozen development functions, unchanged. The
  replication was preregistered in [H3_REPLICATION_PREREGISTRATION.md](H3_REPLICATION_PREREGISTRATION.md) before any
  outcome was computed.
- **Gate:** {gate['result']} (prefix invariance and structure causality, as in development).

## Counts

- **Detection over the whole loaded slice**, including warm-up:
  - compression structures {counts['raw_compression_structures']};
  - displacement bars {counts['raw_displacement_bars']};
  - candidates {sum(counts['candidate_displacements'].values())};
  - acceptance failed {sum(counts['acceptance_failed'].values())};
  - accepted {sum(counts['accepted_breakouts'].values())};
  - suppressed duplicates {counts['suppressed_duplicates']}; no entry bar {counts['no_entry_bar']}; risk ≤ 0 {counts['rejected_risk_le_0']}.
- **Events with the acceptance bar in warm-up (excluded):** {counts['events_in_warmup_excluded']}.
- **Replication events:** **{len(e)}** ({(e.direction == 'long').sum()} long / {(e.direction == 'short').sum()} short).
- **Controls:** {len(c)} draws, {c.signal_index.nunique()} unique bars.
- **Risk:**
  - in ATR units: median {e.risk_atr.median():.2f}, IQR {e.risk_atr.quantile(.25):.2f}–{e.risk_atr.quantile(.75):.2f};
  - in USD: median {e.risk.median():.2f}.
- **Spread / risk** (indicative): median {e.spread_risk.median() * 100:.2f}%.
- **AMBIGUOUS_INTRABAR** (any target): {amb_e} events, {amb_c} controls. Excluded from P(...) for the affected
  target.
- **Unresolved at +2R** (`none` or `truncated` at the end of the replication data): {trunc}.
- **Hole flag:** events whose 20-session lookback contains a known missing-bar hole: {int(e.lookback_contains_hole.sum())}.
  These are flagged for provenance and not excluded.

## Primary result

P(+2R before −1R), H3 minus matched controls: **{lifts[2.0]['lift_pp']:+.1f} pp**, 95% CI
{lifts[2.0]['ci_lo_pp']:+.1f} … {lifts[2.0]['ci_hi_pp']:+.1f} (event-clustered bootstrap, 5,000 samples). The
detectable lift at this sample size is about ±{mde:.1f} pp.

| target | H3 | controls | difference (pp) | 95% CI | conservative H3 (ambiguous = loss) |
|---|---|---|---|---|---|
""" + "\n".join(f"| +{t:g}R | {wilson_text(e, t)} | {wilson_text(c, t)} | {L['lift_pp']:+.1f} | {L['ci_lo_pp']:+.1f} … "
                  f"{L['ci_hi_pp']:+.1f} | {fmt(cons[t], True)} |" for t, L in lifts.items()) + f"""

+2R lift by side: long {side['long']:+.1f} pp, short {side['short']:+.1f} pp.

## Year by year

| period | events | controls | +1R | +2R | +3R | +4R | control +2R | +2R lift (pp) | 95% CI | MFE32 med | MAE32 med | long / short |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
""" + "\n".join(yrow(r) for r in years + [pooled]) + f"""

## MFE / MAE (R)

| sample | bars | MFE median | MFE mean | MAE median | MAE mean |
|---|---|---|---|---|---|
""" + "\n".join(exc) + f"""

## Month by month (descriptive)

| month | events | +2R | control +2R | diff (pp) | MFE32 med | MAE32 med |
|---|---|---|---|---|---|---|
""" + "\n".join(f"| {r.month} | {r.events} | {fmt(r.p2R, True)} | {fmt(r.control_p2R, True)} | {fmt(r.diff_2R_pp, d=1)} "
                  f"| {fmt(r.median_mfe32)} | {fmt(r.median_mae32)} |" for r in months.itertuples()) + f"""

Months with H3 > control at +2R: {int((months.diff_2R_pp > 0).sum())} of {len(months)}. The row counts include months
where both rates are equal or undefined.

## Decision: **{decision}**

The preregistered rule. **FAILED TO REPLICATE** if the pooled lift is ≤ 0 or its CI upper bound is < +{FAIL_CI_HI_PP:g} pp.
**REPLICATED** only if every test below passes. Otherwise **INCONCLUSIVE**.

| test | result |
|---|---|
| a. pooled +2R lift > 0 and 95% CI lower bound > 0 | {t_lbl[tests['a_pooled_lift_positive_ci_above_0']]}: {pooled['lift_2R_pp']:+.1f} pp, CI {pooled['ci_lo_pp']:+.1f} … {pooled['ci_hi_pp']:+.1f} |
| b. pooled +2R lift ≥ +{MIN_LIFT_PP:g} pp | {t_lbl[tests['b_pooled_lift_ge_5pp']]} |
| c1. lift > 0 in ≥ 2 of 3 years | {t_lbl[tests['c1_positive_in_at_least_2_of_3_years']]}: {tests['years_positive']} of 3 |
| c2. pooled lift > 0 without the best year ({tests['best_year']}) | {t_lbl[tests['c2_positive_without_best_year']]}: {tests['lift_without_best_year_pp']:+.1f} pp |
| d. neither side's +2R lift < {SIDE_FLOOR_PP:+g} pp | {t_lbl[tests['d_no_side_below_minus_5pp']]}: long {side['long']:+.1f}, short {side['short']:+.1f} |
| e. H3 median MFE32 ≥ control median MFE32 | {t_lbl[tests['e_median_mfe32_event_ge_control']]}: {e.mfe_32.median():.2f} vs {c.mfe_32.median():.2f} |

## Development vs replication (descriptive only)

| | events | +1R | +2R | +3R | +4R | control +2R | +2R lift | 95% CI | MFE32 med | MAE32 med | long / short lift at +2R |
|---|---|---|---|---|---|---|---|---|---|---|---|
| {dev_row['period']} | {dev_row['events']} | {fmt(dev_row['p1R'], True)} | {fmt(dev_row['p2R'], True)} | {fmt(dev_row['p3R'], True)} | {fmt(dev_row['p4R'], True)} | {fmt(dev_row['control_p2R'], True)} | {dev_row['lift_2R_pp']:+.1f} | {dev_row['ci_lo_pp']:+.1f} … {dev_row['ci_hi_pp']:+.1f} | {fmt(dev_row['median_mfe32'])} | {fmt(dev_row['median_mae32'])} | {dev_side['long']:+.1f} / {dev_side['short']:+.1f} |
| replication 2023-01-01 → 2025-12-22 | {pooled['events']} | {fmt(pooled['p1R'], True)} | {fmt(pooled['p2R'], True)} | {fmt(pooled['p3R'], True)} | {fmt(pooled['p4R'], True)} | {fmt(pooled['control_p2R'], True)} | {pooled['lift_2R_pp']:+.1f} | {pooled['ci_lo_pp']:+.1f} … {pooled['ci_hi_pp']:+.1f} | {fmt(pooled['median_mfe32'])} | {fmt(pooled['median_mae32'])} | {side['long']:+.1f} / {side['short']:+.1f} |

The development row is recomputed here from the frozen development CSVs with the same functions, and it matches the
frozen H3 report.
"""
    (HERE / "report.md").write_text(report)


if __name__ == "__main__":
    main(detect_only="--detect-only" in sys.argv)
