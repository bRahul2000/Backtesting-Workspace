"""Gold V1 — H2 report: tables, event-vs-control comparison, SVG charts and the preregistered decision.

    venv/bin/python research/gold_v1/h2/h2_study.py && venv/bin/python research/gold_v1/h2/h2_report.py

The comparison, bootstrap and chart functions are imported unchanged from the H1 report, so the decision framework
is the H1 one. Reads only the development artifacts written by h2_study.py.
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
    e = pd.read_csv(OUT / "h2_events_dev.csv")
    c = pd.read_csv(OUT / "h2_controls_dev.csv")
    counts = json.loads((OUT / "h2_counts_dev.json").read_text())
    gate = json.loads((OUT / "data_quality.json").read_text())
    assert e["entry_time"].max() < "2026-06-03", "non-development rows in the event set"

    lifts = {t: lift(e, c, t) for t in (1.0, 2.0, 3.0, 4.0)}
    slices = {"long": ("direction", "long"), "short": ("direction", "short"),
              "zone A (1σ)": ("zone", "A"), "zone B (TVWAP)": ("zone", "B")}

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
              "zone A (1σ)": e[e.zone == "A"], "zone B (TVWAP)": e[e.zone == "B"],
              **{s: e[e.session == s] for s in ("London", "New York", "Overlap", "Asia", "Other")}}
    cgroups = {"ALL": c, "long": c[c.direction == "long"], "short": c[c.direction == "short"],
               "zone A (1σ)": c[c.zone == "A"], "zone B (TVWAP)": c[c.zone == "B"],
               **{s: c[c.session == s] for s in ("London", "New York", "Overlap", "Asia", "Other")}}

    exc = []
    for name, df in (("H2 events", e), ("controls", c)):
        for h in HORIZONS:
            exc.append(f"| {name} | {h} | {fmt(df[f'mfe_{h}'].median())} | {fmt(df[f'mfe_{h}'].mean())} "
                       f"| {fmt(df[f'mae_{h}'].median())} | {fmt(df[f'mae_{h}'].mean())} |")
        exc.append(f"| {name} | until −1R | {fmt(df['mfe_to_stop'].median())} | {fmt(df['mfe_to_stop'].mean())} "
                   f"| — | — |")

    ctx = []
    for col in ("vol_regime", "first_zone", "h1_expansion_before", "session"):
        for v, g in e.groupby(col):
            ctx.append(f"| {col} = {v} | {len(g)} | {fmt(rate(g, 2.0), True)} | {fmt(g['mfe_32'].median())} "
                       f"| {fmt(g['mae_32'].median())} |")
    for col in ("er_h1", "atr_pct", "tvwap_slope", "pullback_depth_atr", "travel_atr", "pullback_bars",
                "body_range", "close_location", "tv_ratio", "spread_risk", "pdh_dist_atr", "pdl_dist_atr"):
        q = pd.qcut(e[col].rank(method="first"), 3, labels=["low", "mid", "high"])
        for v, g in e.groupby(q, observed=True):
            ctx.append(f"| {col} tercile {v} ({g[col].min():.3g}–{g[col].max():.3g}) | {len(g)} "
                       f"| {fmt(rate(g, 2.0), True)} | {fmt(g['mfe_32'].median())} | {fmt(g['mae_32'].median())} |")

    by_month = e.groupby("month").size()
    full = by_month.drop("2025-12", errors="ignore")
    amb_any = int((e[[c_ for c_ in e.columns if c_.startswith("r_")]] == "ambiguous").any(axis=1).sum())
    amb_ctrl = int((c[[c_ for c_ in c.columns if c_.startswith("r_")]] == "ambiguous").any(axis=1).sum())
    unresolved2 = int(e["r_2.0"].isin(["none", "truncated"]).sum())
    # detectable effect: 95 % two-sided, 80 % power, event n vs 5n controls at the control's +2R rate
    p0, n2 = lifts[2.0]["control_p"], lifts[2.0]["event_n"]
    mde = (1.96 + 0.84) * np.sqrt(p0 * (1 - p0) * (1 / n2 + 1 / (5 * n2))) * 100

    report = f"""# Gold V1 — H2 event study (TREND PULLBACK TO TVWAP)

- **Data:** development data only, 2025-12-23 → 2026-06-02 (Exness XAUUSDm M15, bid). Events span
  {e.signal_time.min()[:10]} → {e.entry_time.max()[:10]}. Validation and final OOS were not loaded.
- **Rules:** implemented exactly as frozen in [preregistration.md](preregistration.md) (SHA-256 89e22514…, frozen
  before any H2 outcome was computed).
- **Data quality gate: {gate['result']}.** All 12 H1 checks were rerun, plus 3 H2 checks; see [data_quality.md](data_quality.md).

## Counts

| stage | long | short | total |
|---|---|---|---|
| pullback sequences started (new session extreme with ≥ 1 eligible zone) | {counts['sequences_started']['long']} | {counts['sequences_started']['short']} | {sum(counts['sequences_started'].values())} |
| unique pullback sequences (first touch of a zone while in the trend regime) | {counts['unique_sequences']['long']} | {counts['unique_sequences']['short']} | {sum(counts['unique_sequences'].values())} |
| raw qualifying bars (regime + touch + rejection, ignoring sequence/first-touch) | {counts['raw_qualifying_bars']['long']} | {counts['raw_qualifying_bars']['short']} | {sum(counts['raw_qualifying_bars'].values())} |
| **final unique H2 events** | {(e.direction == 'long').sum()} | {(e.direction == 'short').sum()} | **{len(e)}** |

- **Rejected events:** risk ≤ 0: {counts['rejected_risk_le_0']}; no next bar in the session: {counts['rejected_no_next_bar']}.
- **By month:** {', '.join(f'{m} {n}' for m, n in by_month.items())}. Full months (Jan–May): mean {full.mean():.1f}, median {full.median():.0f} per month
  (about 0.2 per trading day; the design's frequency guide of about 7 zone touches per day was before context and rejection).
- **By zone:** A (1σ) {(e.zone == 'A').sum()}, B (TVWAP) {(e.zone == 'B').sum()}. First zone touched in the sequence:
  {', '.join(f'{k} {v}' for k, v in e.first_zone.value_counts().items())}.
- **By session:** {', '.join(f'{k} {v}' for k, v in e.session.value_counts().items())}.
- **Rejection timing:** on the touch bar {(e.rejection_delay == 0).sum()}, on T+1 {(e.rejection_delay == 1).sum()}.
- **Risk:**
  - in USD: median {e.risk.median():.2f}, IQR {e.risk.quantile(.25):.2f}–{e.risk.quantile(.75):.2f}, max {e.risk.max():.2f};
  - in ATR units: median {e.risk_atr.median():.2f}, IQR {e.risk_atr.quantile(.25):.2f}–{e.risk_atr.quantile(.75):.2f}.
- **Spread / risk:** median {e.spread_risk.median() * 100:.2f}%, max {e.spread_risk.max() * 100:.2f}% (spread semantics unresolved;
  indicative only).
- **AMBIGUOUS_INTRABAR** (a target and −1R in one bar, any target): {amb_any} events, {amb_ctrl} controls. Excluded from
  the P(...) figures. Events without a +2R/−1R resolution in 96 bars: {unresolved2}.

## Primary analysis — events vs matched controls

- **Controls:** {len(c)} bars, {len(c) // max(1, len(e))} per event, fixed seed {SEED}.
- **Matching:** the same trend regime (ER ≥ 0.35), the same H1 direction, TVWAP slope in the trend direction, the
  same session and the same volatility regime.
- **Exclusions:** not a raw qualifying H2 bar, and more than 8 bars from any event.
- **Stop:** the event's risk in ATR units.

P(+tR before −1R), Wilson 95% CI in brackets. The lift CI comes from an event-clustered bootstrap (5,000 samples).

| target | H2 events | controls | lift (pp) | lift 95% CI | break-even |
|---|---|---|---|---|---|
""" + "\n".join(
        f"| +{t:g}R | {ci_text(e, t)} | {ci_text(c, t)} | {v['lift_pp']:+.1f} | {v['ci_lo_pp']:+.1f} … "
        f"{v['ci_hi_pp']:+.1f} | {100 / (1 + t):.1f}% |" for t, v in lifts.items()) + f"""

![target curve](chart_target_curve.svg)

### MFE / MAE (R)

| sample | bars | MFE median | MFE mean | MAE median | MAE mean |
|---|---|---|---|---|---|
""" + "\n".join(exc) + f"""

### Breakdown — H2 events

{md_breakdown(groups)}
### Breakdown — matched controls

{md_breakdown(cgroups)}
## Time stability

| month | events | +1R | +2R | +3R | MFE32 med | MAE32 med | control +2R | +2R diff (pp) |
|---|---|---|---|---|---|---|---|---|
""" + "\n".join(
        f"| {r['month']} | {r['n']} | {fmt(r['p1'], True)} | {fmt(r['p2'], True)} | {fmt(r['p3'], True)} "
        f"| {fmt(r['mfe'])} | {fmt(r['mae'])} | {fmt(r['c2'], True)} | {r['d2']:+.1f} |" for r in month_rows) + f"""

Months with event > control at +2R: {pos_months} of {len(month_rows)}. With 2–7 events a month, a single event
moves a monthly rate by 14–50 pp.

![months](chart_months_2R.svg)

| slice | lift +2R (pp) | lift +3R (pp) |
|---|---|---|
""" + "\n".join(f"| {k} | {fmt(v[2.0], d=1)} | {fmt(v[3.0], d=1)} |" for k, v in slice_tab.items()) + """

## Context features (recorded, not filtered)

| context | n | P(+2R) | MFE32 med | MAE32 med |
|---|---|---|---|---|
""" + "\n".join(ctx) + f"""

The tercile cells hold 9 events each, so any difference between them is noise. They are recorded for the
feature library only.

## Statistical power

With {n2} resolved events at +2R and a control rate of {fmt(p0, True)}, the smallest lift this sample could detect
(95% two-sided, 80% power) is about **±{mde:.0f} pp**. The preregistered PROMISING bar is +5 pp with a CI above 0,
so it is only reachable if the true lift is several times larger than any plausible intraday effect. The rule
is applied unchanged; this note explains how much the verdict can and cannot say.

## Decision: **{decision}**

The rule is the H1 one, unchanged, with slices long, short, zone A and zone B:
- **PROMISING** requires all of: a +2R lift ≥ {MIN_LIFT_PP:g} pp with the 95% CI above 0; event > control in at least 4 of 6 months; a positive +2R lift in every slice.
- **WEAK**: a positive lift at +2R or +3R that fails those tests.
- **NO EDGE**: no positive lift at +2R or +3R.

Observed:
- +2R lift {l2['lift_pp']:+.1f} pp (CI {l2['ci_lo_pp']:+.1f} … {l2['ci_hi_pp']:+.1f});
- +3R lift {l3['lift_pp']:+.1f} pp (CI {l3['ci_lo_pp']:+.1f} … {l3['ci_hi_pp']:+.1f});
- {pos_months}/{len(month_rows)} months positive;
- slice lifts at +2R: {', '.join(f"{k} {fmt(v[2.0], d=1)}" for k, v in slice_tab.items())}.

## Interpretation

- **The central question gets a negative answer.** Does a trend pullback to TVWAP / trend-side 1σ with an objective
  rejection continue better than comparable trending M15 bars? No. H2 events do worse than their controls at every
  target. At +2R the whole bootstrap CI is below zero. Each of the four preregistered slices is negative, and the only
  positive month is December, with 2 events.
- **Excursions point the same way.** Median MFE is lower than the controls' at every horizon, and median MAE is
  higher at every horizon. Price tends to come back through the rejection bar: 22 of 27 rejections are the T+1
  candle, so the stop sits just beyond a two-bar structure that is often retested.
- **The sample is small** ({len(e)} events; detectable lift about ±{mde:.0f} pp), so the size of the shortfall is imprecise.
  Its sign is not: no preregistered cut of the data is positive at +2R.
- **The controls are only a benchmark.** They are strong in their own right ({fmt(p0, True)} at +2R against a 33.3%
  break-even). That describes the trend-regime bars used for comparison, with the stop size borrowed from the
  events. It was not a preregistered hypothesis and is **not** a finding. It must not be turned into a strategy from
  this sample. If it is pursued, it needs its own preregistration and a test outside the development window.
- **No rescue.** Per the brief, H2 is not rescued with post-hoc filters (zone, direction, month, session, the
  context terciles). Validation and OOS were not inspected. The result is preserved as is.
"""
    (OUT / "report.md").write_text(report)
    (OUT / "h2_summary.json").write_text(json.dumps({
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
