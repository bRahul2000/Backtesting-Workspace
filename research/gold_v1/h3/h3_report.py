"""Gold V1 — H3 report: tables, event-vs-control comparison, SVG charts and the preregistered decision.

    venv/bin/python research/gold_v1/h3/h3_study.py && venv/bin/python research/gold_v1/h3/h3_report.py

The comparison, bootstrap and chart functions are imported unchanged from the H1 report, so the decision framework
is the H1 one. Reads only the development artifacts written by h3_study.py.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import json                                                                             # noqa: E402
from pathlib import Path                                                                # noqa: E402

import numpy as np                                                                      # noqa: E402
import pandas as pd                                                                     # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "h1"))
from h1_report import MIN_LIFT_PP, fmt, lift, md_breakdown, p_win, svg_curve, svg_months   # noqa: E402
from h1_study import HORIZONS, SEED, wilson                                            # noqa: E402

OUT = Path(__file__).resolve().parent


def rate(df, t):
    k, n = p_win(df, t)
    return k / n if n else np.nan


def ci_text(df, t):
    k, n = p_win(df, t)
    lo, hi = wilson(k, n)
    return f"{fmt(k / n if n else np.nan, True)} ({fmt(lo, True)}–{fmt(hi, True)}, n={n})"


def main() -> None:
    e = pd.read_csv(OUT / "h3_events_dev.csv")
    c = pd.read_csv(OUT / "h3_controls_dev.csv")
    counts = json.loads((OUT / "h3_counts_dev.json").read_text())
    gate = json.loads((OUT / "data_quality.json").read_text())
    assert e["entry_time"].max() < "2026-06-03", "non-development rows in the event set"

    lifts = {t: lift(e, c, t) for t in (1.0, 2.0, 3.0, 4.0)}
    slices = {"long": ("direction", "long"), "short": ("direction", "short")}      # preregistered slices

    def slice_lift(col, val, t):
        a, b = rate(e[e[col] == val], t), rate(c[c[col] == val], t)
        return (a - b) * 100 if not (np.isnan(a) or np.isnan(b)) else np.nan
    slice_tab = {k: {t: slice_lift(col, v, t) for t in (2.0, 3.0)} for k, (col, v) in slices.items()}

    months = sorted(e.month.unique())
    month_rows = []
    for m in months:
        em = e[e.month == m]
        cm = c[c.event_signal_index.isin(em.signal_index)]
        month_rows.append({"month": m, "n": len(em), "p1": rate(em, 1.0), "p2": rate(em, 2.0), "p3": rate(em, 3.0),
                           "mfe": em.mfe_32.median(), "mae": em.mae_32.median(), "c2": rate(cm, 2.0),
                           "d2": (rate(em, 2.0) - rate(cm, 2.0)) * 100})
    pos_months = sum(1 for r in month_rows if r["d2"] > 0)

    l2, l3 = lifts[2.0], lifts[3.0]
    promising = (l2["lift_pp"] >= MIN_LIFT_PP and l2["ci_lo_pp"] > 0 and pos_months >= 4
                 and all(v[2.0] > 0 for v in slice_tab.values()))
    positive = l2["lift_pp"] > 0 or l3["lift_pp"] > 0
    decision = "PROMISING" if promising else ("WEAK" if positive else "NO EDGE")

    svg_curve(e, c, OUT / "chart_target_curve.svg")
    svg_months([(r["month"], r["p2"], r["c2"]) for r in month_rows], OUT / "chart_months_2R.svg")

    groups = {"ALL": e, "long": e[e.direction == "long"], "short": e[e.direction == "short"],
              "two-sided (flagged)": e[e.two_sided], "one-sided": e[~e.two_sided],
              **{s: e[e.session == s] for s in ("London", "New York", "Overlap", "Asia", "Other")}}
    cgroups = {"ALL": c, "long": c[c.direction == "long"], "short": c[c.direction == "short"],
               "two-sided (flagged)": c[c.two_sided], "one-sided": c[~c.two_sided],
               **{s: c[c.session == s] for s in ("London", "New York", "Overlap", "Asia", "Other")}}

    exc = []
    for name, df in (("H3 events", e), ("controls", c)):
        for h in HORIZONS:
            exc.append(f"| {name} | {h} | {fmt(df[f'mfe_{h}'].median())} | {fmt(df[f'mfe_{h}'].mean())} "
                       f"| {fmt(df[f'mae_{h}'].median())} | {fmt(df[f'mae_{h}'].mean())} |")
        exc.append(f"| {name} | until −1R | {fmt(df['mfe_to_stop'].median())} | {fmt(df['mfe_to_stop'].mean())} "
                   f"| — | — |")

    ctx = []
    for col in ("acceptance_shape", "vol_regime", "regime", "toward_tvwap", "session"):
        for v, g in e.groupby(col):
            ctx.append(f"| {col} = {v} | {len(g)} | {fmt(rate(g, 2.0), True)} | {fmt(g['mfe_32'].median())} "
                       f"| {fmt(g['mae_32'].median())} |")
    for col in ("box_width_atr", "compression_pct", "compression_duration", "bars_since_expansion",
                "disp_range_atr", "disp_body_range", "disp_close_location", "dist_beyond_atr", "disp_tv_ratio",
                "er_h1", "atr_pct", "tvwap_dist_atr", "tvwap_slope", "tv_ratio", "spread_risk", "risk_atr",
                "pdh_dist_atr", "pdl_dist_atr"):
        q = pd.qcut(e[col].rank(method="first"), 3, labels=["low", "mid", "high"])
        for v, g in e.groupby(q, observed=True):
            ctx.append(f"| {col} tercile {v} ({g[col].min():.3g}–{g[col].max():.3g}) | {len(g)} "
                       f"| {fmt(rate(g, 2.0), True)} | {fmt(g['mfe_32'].median())} | {fmt(g['mae_32'].median())} |")

    by_month = e.groupby("month").size()
    full = by_month.drop(["2026-01", "2026-06"], errors="ignore")      # stubs: warm-up ends late Jan; June = 2 days
    amb_any = int((e[[c_ for c_ in e.columns if c_.startswith("r_")]] == "ambiguous").any(axis=1).sum())
    amb_ctrl = int((c[[c_ for c_ in c.columns if c_.startswith("r_")]] == "ambiguous").any(axis=1).sum())
    unresolved2 = int(e["r_2.0"].isin(["none", "truncated"]).sum())
    # detectable effect: 95 % two-sided, 80 % power, event n vs 5n controls at the control's +2R rate
    p0, n2 = lifts[2.0]["control_p"], lifts[2.0]["event_n"]
    mde = (1.96 + 0.84) * np.sqrt(p0 * (1 - p0) * (1 / n2 + 1 / (5 * n2))) * 100

    report = f"""# Gold V1 — H3 event study (COMPRESSION → DISPLACEMENT → ACCEPTANCE)

- **Data:** development data only, 2025-12-23 → 2026-06-02 (Exness XAUUSDm M15, bid). Validation and final OOS were not loaded.
- **Event span:** {e.signal_time.min()[:10]} → {e.entry_time.max()[:10]}. The compression percentile needs 20 trading days of
  history, so no event can occur before late January.
- **Rules:** implemented exactly as frozen in [preregistration.md](preregistration.md) (SHA-256 c481f8a1…, frozen
  before any H3 code ran).
- **Data quality gate: {gate['result']}.** All 12 H1 checks were rerun, plus 2 H3 checks; see [data_quality.md](data_quality.md).

## Counts

| stage | long | short | total |
|---|---|---|---|
| raw compression structures (runs of compressed bars) | — | — | {counts['raw_compression_structures']} |
| raw displacement bars (range ≥ 1.5 ATR, body ≥ 0.6; any context) | — | — | {counts['raw_displacement_bars']} |
| candidate displacements (live, intact box; close beyond it) | {counts['candidate_displacements']['long']} | {counts['candidate_displacements']['short']} | {sum(counts['candidate_displacements'].values())} |
| acceptance failed (next bar closed back inside) | {counts['acceptance_failed']['long']} | {counts['acceptance_failed']['short']} | {sum(counts['acceptance_failed'].values())} |
| accepted breakouts | {counts['accepted_breakouts']['long']} | {counts['accepted_breakouts']['short']} | {sum(counts['accepted_breakouts'].values())} |
| **final unique H3 events** | {(e.direction == 'long').sum()} | {(e.direction == 'short').sum()} | **{len(e)}** |

- **Dropped between accepted breakouts and final events:** duplicate suppression {counts['suppressed_duplicates']}; no
  entry bar in the session {counts['no_entry_bar']}; risk ≤ 0 {counts['rejected_risk_le_0']}.
- **Candidates that traded through both sides of the box:** {counts['candidates_two_sided']}. Among the final events
  {int(e.two_sided.sum())} are flagged `two_sided` (kept, and reported separately below).
- **By month:** {', '.join(f'{m} {n}' for m, n in by_month.items())}. Full months (Feb–May): mean {full.mean():.1f}, median
  {full.median():.1f} per month, about 0.8 per trading day; the design's guide was 0.3–0.6 per day.
- **By session:** {', '.join(f'{k} {v}' for k, v in e.session.value_counts().items())}.
- **Acceptance shape:** {', '.join(f'{k} {v}' for k, v in e.acceptance_shape.value_counts().items())}.
- **Risk** (entry − opposite side of the displacement bar):
  - in USD: median {e.risk.median():.2f}, IQR {e.risk.quantile(.25):.2f}–{e.risk.quantile(.75):.2f}, max {e.risk.max():.2f};
  - in ATR units: median {e.risk_atr.median():.2f}, IQR {e.risk_atr.quantile(.25):.2f}–{e.risk_atr.quantile(.75):.2f}.
- **Spread / risk:** median {e.spread_risk.median() * 100:.2f}%, 90th percentile {e.spread_risk.quantile(.9) * 100:.2f}%, max
  {e.spread_risk.max() * 100:.2f}% (spread semantics unresolved; indicative only).
- **AMBIGUOUS_INTRABAR** (a target and −1R in one bar, any target): {amb_any} events, {amb_ctrl} controls. The affected
  target is excluded from the P(...) figures. Events without a +2R/−1R resolution in 96 bars: {unresolved2}.

## Primary analysis — events vs matched controls

- **Controls:** {len(c)} bars, {len(c) // max(1, len(e))} per event, fixed seed {SEED}.
- **Matching:** the same session, the same volatility regime and an ATR percentile within ±10 of the event's. The ATR
  condition was relaxed for {int(c.atr_pct_relaxed.sum())} controls.
- **Exclusions:** not an H3 acceptance bar, and more than 8 bars from any event.
- **Direction and stop:** each control takes the event's direction and its risk in ATR units.
- **No H3 requirement:** controls need not have compression, displacement or acceptance.

P(+tR before −1R), Wilson 95% CI in brackets. The lift CI comes from an event-clustered bootstrap (5,000 samples).

| target | H3 events | controls | lift (pp) | lift 95% CI | break-even |
|---|---|---|---|---|---|
""" + "\n".join(
        f"| +{t:g}R | {ci_text(e, t)} | {ci_text(c, t)} | {v['lift_pp']:+.1f} | {v['ci_lo_pp']:+.1f} … "
        f"{v['ci_hi_pp']:+.1f} | {100 / (1 + t):.1f}% |" for t, v in lifts.items()) + f"""

![target curve](chart_target_curve.svg)

### MFE / MAE (R)

| sample | bars | MFE median | MFE mean | MAE median | MAE mean |
|---|---|---|---|---|---|
""" + "\n".join(exc) + f"""

### Breakdown — H3 events

{md_breakdown(groups)}
### Breakdown — matched controls

{md_breakdown(cgroups)}
## Time stability

| month | events | +1R | +2R | +3R | MFE32 med | MAE32 med | control +2R | +2R diff (pp) |
|---|---|---|---|---|---|---|---|---|
""" + "\n".join(
        f"| {r['month']} | {r['n']} | {fmt(r['p1'], True)} | {fmt(r['p2'], True)} | {fmt(r['p3'], True)} "
        f"| {fmt(r['mfe'])} | {fmt(r['mae'])} | {fmt(r['c2'], True)} | {fmt(r['d2'], d=1)} |" for r in month_rows) + f"""

Months with event > control at +2R: {pos_months} of {len(month_rows)}. January and June hold 2 events each.

![months](chart_months_2R.svg)

| slice | lift +2R (pp) | lift +3R (pp) |
|---|---|---|
""" + "\n".join(f"| {k} | {fmt(v[2.0], d=1)} | {fmt(v[3.0], d=1)} |" for k, v in slice_tab.items()) + """

## Context features (recorded, not filtered)

| context | n | P(+2R) | MFE32 med | MAE32 med |
|---|---|---|---|---|
""" + "\n".join(ctx) + f"""

Tercile cells hold about 25 events each; a Wilson half-width at n = 25 is about ±18 pp. These rows are for the
feature library only.

## Statistical power

With {n2} resolved events at +2R and a control rate of {fmt(p0, True)}, the smallest lift this sample could detect
(95% two-sided, 80% power) is about **±{mde:.0f} pp**. The rule is applied unchanged; this note only says how much
the verdict can and cannot say.

## Decision: **{decision}**

The rule is the H1/H2 one, unchanged, with the preregistered slices long and short:
- **PROMISING** requires all of: a +2R lift ≥ {MIN_LIFT_PP:g} pp with the 95% CI above 0; event > control in at least 4 of 6 months; a positive +2R lift in both slices.
- **WEAK**: a positive lift at +2R or +3R that fails those tests.
- **NO EDGE**: no positive lift at +2R or +3R.

Observed:
- +2R lift {l2['lift_pp']:+.1f} pp (CI {l2['ci_lo_pp']:+.1f} … {l2['ci_hi_pp']:+.1f});
- +3R lift {l3['lift_pp']:+.1f} pp (CI {l3['ci_lo_pp']:+.1f} … {l3['ci_hi_pp']:+.1f});
- {pos_months}/{len(month_rows)} months positive;
- slice lifts at +2R: {', '.join(f"{k} {fmt(v[2.0], d=1)}" for k, v in slice_tab.items())}.

WEAK because the +2R lift is positive and passes the size, month and slice tests, but its 95% CI includes zero.

## Interpretation — where the lift is and where it disappears

- **Direction of the effect.** Confirmed breakouts from compression continued slightly better than comparable M15
  bars. The point estimates are positive from +1R to +4R. The lift is similar for long ({fmt(slice_tab['long'][2.0], d=1)} pp) and
  short ({fmt(slice_tab['short'][2.0], d=1)} pp), even though longs and shorts have very different base rates in this period (the
  controls show the same long/short gap). So the lift is not simply the period's directional drift.
- **It is not established.** Every bootstrap CI crosses zero. The sample can only detect lifts of about
  ±{mde:.0f} pp, and the observed +{l2['lift_pp']:.1f} pp is well inside the noise band.
- **It fades with target distance.** The lift is +{lifts[1.0]['lift_pp']:.1f} / +{l2['lift_pp']:.1f} / +{l3['lift_pp']:.1f} / +{lifts[4.0]['lift_pp']:.1f} pp at
  +1R to +4R, and is essentially gone at +4R. Median MFE is higher than the controls' at every horizon (4 to 32 bars). Mean MAE at 32
  bars is *higher* than the controls' ({e.mae_32.mean():.2f}R vs {c.mae_32.mean():.2f}R): the adverse tail is fatter, even
  though the median is lower. This looks like a short follow-through, not a larger move.
- **It is uneven over time.** Of the four full months, February (+23.5 pp) and May (+12.6 pp) are positive, April is
  flat (+0.5 pp) and March is negative (−15.1 pp). The 5-of-6 month count relies on January and June, which hold 2
  events each. Without the two stub months the lift would rest on two months.
- **Session cells look different but are post-hoc.** Asia events outperform their controls; London events
  underperform theirs. These cells hold 22–35 events. They were not preregistered and are **not** candidate
  filters. The same goes for the context terciles.
- **Economics are not tested here.** The event P(+2R) of {fmt(l2['event_p'], True)} is above the 33.3% break-even, but the
  control is at break-even too ({fmt(l2['control_p'], True)}). A gross +2R race implies about +0.24R per event before costs;
  median spread/risk is {e.spread_risk.median() * 100:.1f}% of R. That is neither a strategy result nor evidence of one.
- **No rescue.** Per the brief, H3 is not rescued or refined with filters. Validation and OOS were not inspected.
  H4/H5 wait for review.
"""
    (OUT / "report.md").write_text(report)
    (OUT / "h3_summary.json").write_text(json.dumps({
        "decision": decision, "events": len(e), "controls": len(c), "counts": counts,
        "lifts": {str(k): {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in v.items()}
                  for k, v in lifts.items()},
        "months": month_rows, "months_positive_2R": pos_months, "mde_pp": mde,
        "slices": {k: {str(t): x for t, x in v.items()} for k, v in slice_tab.items()},
    }, indent=1, default=float) + "\n")
    print(decision, f"MDE ±{mde:.0f}pp")
    for t, v in lifts.items():
        print(t, round(v["event_p"], 3), v["event_n"], round(v["control_p"], 3), round(v["lift_pp"], 1),
              round(v["ci_lo_pp"], 1), round(v["ci_hi_pp"], 1))
    print([(r["month"], r["n"], round(r["d2"], 1)) for r in month_rows])
    print(slice_tab)


if __name__ == "__main__":
    main()
