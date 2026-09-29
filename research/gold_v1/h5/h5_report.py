"""Gold V1 — H5 report: tables, event-vs-control comparison, SVG charts and the preregistered decision.

    venv/bin/python research/gold_v1/h5/h5_study.py && venv/bin/python research/gold_v1/h5/h5_report.py

The comparison, bootstrap and chart functions are imported unchanged from the H1 report, so the decision framework
is the H1 one. Reads only the development artifacts written by h5_study.py.
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
    e = pd.read_csv(OUT / "h5_events_dev.csv")
    c = pd.read_csv(OUT / "h5_controls_dev.csv")
    counts = json.loads((OUT / "h5_counts_dev.json").read_text())
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
    need_months = int(np.ceil(len(month_rows) * 2 / 3))          # preregistered: 4 of 6, i.e. 5 of 7

    l2, l3 = lifts[2.0], lifts[3.0]
    promising = (l2["lift_pp"] >= MIN_LIFT_PP and l2["ci_lo_pp"] > 0 and pos_months >= need_months
                 and all(v[2.0] > 0 for v in slice_tab.values()))
    positive = l2["lift_pp"] > 0 or l3["lift_pp"] > 0
    decision = "PROMISING" if promising else ("WEAK" if positive else "NO EDGE")

    svg_curve(e, c, OUT / "chart_target_curve.svg")
    svg_months([(r["month"], r["p2"], r["c2"]) for r in month_rows], OUT / "chart_months_2R.svg")

    groups = {"ALL": e, "long": e[e.direction == "long"], "short": e[e.direction == "short"],
              "both-directions day": e[e.both_directions_day], "one-direction day": e[~e.both_directions_day],
              **{f"confirm {k}": g for k, g in e.groupby(pd.cut(e.signal_time_ny.str[:2].astype(int), [9, 10, 11, 13],
                                                                        labels=["10:xx", "11:xx", "12:xx"]), observed=True)}}
    cgroups = {"ALL": c, "long": c[c.direction == "long"], "short": c[c.direction == "short"],
               "both-directions day": c[c.both_directions_day], "one-direction day": c[~c.both_directions_day],
               }

    exc = []
    for name, df in (("H5 events", e), ("controls", c)):
        for h in HORIZONS:
            exc.append(f"| {name} | {h} | {fmt(df[f'mfe_{h}'].median())} | {fmt(df[f'mfe_{h}'].mean())} "
                       f"| {fmt(df[f'mae_{h}'].median())} | {fmt(df[f'mae_{h}'].mean())} |")
        exc.append(f"| {name} | until −1R | {fmt(df['mfe_to_stop'].median())} | {fmt(df['mfe_to_stop'].mean())} "
                   f"| — | — |")

    ctx = []
    for col in ("first_break", "opposite_swept_before", "or_vs_pd", "or_vs_asia", "vol_regime", "regime", "dow",
                "us_short_session"):
        for v, g in e.groupby(col):
            ctx.append(f"| {col} = {v} | {len(g)} | {fmt(rate(g, 2.0), True)} | {fmt(g['mfe_32'].median())} "
                       f"| {fmt(g['mae_32'].median())} |")
    for col in ("or_width_atr", "or_width_pct", "overnight_dist_atr", "close1_dist_atr", "close2_dist_atr",
                "close2_wick_atr", "close2_body_range", "close2_close_loc", "tv_ratio", "er_h1", "atr_pct",
                "tvwap_pos_atr", "tvwap_slope", "spread_risk", "risk_atr"):
        ok = e[col].notna()
        q = pd.qcut(e.loc[ok, col].rank(method="first"), 3, labels=["low", "mid", "high"])
        for v, g in e[ok].groupby(q, observed=True):
            ctx.append(f"| {col} tercile {v} ({g[col].min():.3g}–{g[col].max():.3g}) | {len(g)} "
                       f"| {fmt(rate(g, 2.0), True)} | {fmt(g['mfe_32'].median())} | {fmt(g['mae_32'].median())} |")

    by_month = e.groupby("month").size()
    full = by_month.drop(["2025-12", "2026-06"], errors="ignore")      # stubs: Dec starts 12-23; June = 2 days
    days = pd.read_csv(OUT / "h5_days_dev.csv")
    both_days = int((days.long_event & days.short_event).sum())
    long_only = int((days.long_event & ~days.short_event).sum())
    short_only = int((~days.long_event & days.short_event).sum())
    neither = int((~days.long_event & ~days.short_event).sum())
    brk = days[days.first_break.isin(["up", "down"])]
    opp = ((brk.first_break == "up") & brk.broke_down) | ((brk.first_break == "down") & brk.broke_up)
    broke_any = days.broke_up | days.broke_down
    first_conf = days[days.long_event | days.short_event]
    p_opp_conf = both_days / max(1, len(first_conf))
    ev_both, ev_single = e[e.both_directions_day], e[~e.both_directions_day]
    first_ev = e[~e.opposite_confirmed_earlier]
    tb = days.set_index("tday")
    e_trade_both = e[e.tday.map(tb.broke_up & tb.broke_down).astype(bool)]
    e_trade_single = e[~e.tday.map(tb.broke_up & tb.broke_down).astype(bool)]
    uniq_ctrl = c.signal_index.nunique()
    amb_any = int((e[[c_ for c_ in e.columns if c_.startswith("r_")]] == "ambiguous").any(axis=1).sum())
    amb_ctrl = int((c[[c_ for c_ in c.columns if c_.startswith("r_")]] == "ambiguous").any(axis=1).sum())
    unresolved2 = int(e["r_2.0"].isin(["none", "truncated"]).sum())
    # detectable effect: 95 % two-sided, 80 % power, event n vs 5n controls at the control's +2R rate
    p0, n2 = lifts[2.0]["control_p"], lifts[2.0]["event_n"]
    mde = (1.96 + 0.84) * np.sqrt(p0 * (1 - p0) * (1 / n2 + 1 / (5 * n2))) * 100

    report = f"""# Gold V1 — H5 event study (NEW YORK OPENING-RANGE ACCEPTANCE)

- **Data:** development data only, 2025-12-23 → 2026-06-02 (Exness XAUUSDm M15, bid). Validation and final OOS were not loaded.
- **Event span:** {e.signal_time.min()[:10]} → {e.entry_time.max()[:10]}.
- **Rules:** implemented exactly as frozen in [preregistration.md](preregistration.md) (SHA-256 cfeda52f…, frozen before any H5
  code ran).
- **Opening range:** the 09:30 and 09:45 New York bars, located by wall-clock time. That is 14:30/14:45 UTC under EST
  ({gate['h5_or_dst_mapping']['est_days']} days) and 13:30/13:45 UTC under EDT ({gate['h5_or_dst_mapping']['edt_days']} days).
- **Signal and stop:** confirmation by two consecutive closes strictly beyond the OR, at the 10:15–12:45 New York bars. Entry
  at the next open; stop at the OR midpoint.
- **Data quality gate: {gate['result']}.** All 12 H1 checks were rerun, plus 3 H5 checks; see [data_quality.md](data_quality.md).

## Counts

| stage | long | short | total |
|---|---|---|---|
| days studied / days with an OR | — | — | {counts['days_studied']} / {counts['days_with_or']} |
| raw outside closes (10:00–12:45 New York bars) | {counts['raw_outside_closes']['long']} | {counts['raw_outside_closes']['short']} | {sum(counts['raw_outside_closes'].values())} |
| two-close confirmations (incl. repeats) | {counts['confirmations']['long']} | {counts['confirmations']['short']} | {sum(counts['confirmations'].values())} |
| suppressed repeats (one event per direction per day) | {counts['suppressed_duplicates']['long']} | {counts['suppressed_duplicates']['short']} | {sum(counts['suppressed_duplicates'].values())} |
| **unique H5 events** | {(e.direction == 'long').sum()} | {(e.direction == 'short').sum()} | **{len(e)}** |

- **Rejected:** no entry bar {counts['no_entry_bar']}; risk ≤ 0 {counts['rejected_risk_le_0']}.
- **Missing OR:** the one trading day without an OR is the partial day that starts 2026-06-02 22:00 UTC, which the
  development cut truncates.
- **Day classes** ({counts['days_with_or']} OR days): long only {long_only}, short only {short_only}, both directions {both_days}, neither {neither}.
- **By month:** {', '.join(f'{m} {n}' for m, n in by_month.items())}. Full months (Jan–May): mean {full.mean():.1f}, median
  {full.median():.0f} per month, about 0.87 per trading day.
- **Confirmation time (New York):** {', '.join(f'{k} {v}' for k, v in e.signal_time_ny.value_counts().sort_index().items())}.
- **Risk** (entry − OR mid):
  - in USD: median {e.risk.median():.2f}, IQR {e.risk.quantile(.25):.2f}–{e.risk.quantile(.75):.2f}, max {e.risk.max():.2f};
  - in ATR units: median {e.risk_atr.median():.2f}, IQR {e.risk_atr.quantile(.25):.2f}–{e.risk_atr.quantile(.75):.2f}, max {e.risk_atr.max():.2f}.
  - The maximum is 2026-01-29, a genuine ~400-point crash in both the M15 and H1 data. The event is kept, and R
    normalization makes it a single event.
- **Spread / risk:** median {e.spread_risk.median() * 100:.2f}%, 90th percentile {e.spread_risk.quantile(.9) * 100:.2f}%, max
  {e.spread_risk.max() * 100:.2f}% (spread semantics unresolved; indicative only).
- **AMBIGUOUS_INTRABAR** (a target and −1R in one bar, any target): {amb_any} events, {amb_ctrl} controls. The affected
  target is excluded. Events without a +2R/−1R resolution in 96 bars: {unresolved2}.

## Primary analysis — events vs matched controls

- **Controls:** {len(c)} draws, {len(c) // max(1, len(e))} per event, fixed seed {SEED}.
- **Matching:** bars starting 10:15–12:45 New York on OR days, with the same volatility regime, an ATR percentile
  within ±10 of the event's, and the same OR-width tercile where practical.
- **Exclusions:** not a confirming bar, and more than 8 bars from any event.
- **Direction and stop:** each control takes the event's direction and its risk in ATR units.
- **Relaxations:** the OR-tercile condition was relaxed for {int(c.or_pct_relaxed.sum())} draws and the ATR-percentile condition for
  {int(c.atr_pct_relaxed.sum())}.
- **Thin pool.** The ±8-bar exclusion, kept unchanged from H1–H3, removes most of the 3-hour window on event days, so
  controls come mainly from non-event days and from event days' other directions or times. Only **{uniq_ctrl} unique bars**
  stand behind the {len(c)} draws. Repeated draws make the control rates less precise than their Wilson CIs suggest. The event-clustered
  bootstrap resamples events together with their own draws, but it does not model draws shared between events.

P(+tR before −1R), Wilson 95% CI in brackets. The lift CI comes from an event-clustered bootstrap (5,000 samples).

| target | H5 events | controls | lift (pp) | lift 95% CI | break-even |
|---|---|---|---|---|---|
""" + "\n".join(
        f"| +{t:g}R | {ci_text(e, t)} | {ci_text(c, t)} | {v['lift_pp']:+.1f} | {v['ci_lo_pp']:+.1f} … "
        f"{v['ci_hi_pp']:+.1f} | {100 / (1 + t):.1f}% |" for t, v in lifts.items()) + f"""

![target curve](chart_target_curve.svg)

### MFE / MAE (R)

| sample | bars | MFE median | MFE mean | MAE median | MAE mean |
|---|---|---|---|---|---|
""" + "\n".join(exc) + f"""

### Breakdown — H5 events

{md_breakdown(groups)}
### Breakdown — matched controls

{md_breakdown(cgroups)}
## Monthly stability

| month | events | +1R | +2R | +3R | MFE32 med | MAE32 med | control +2R | +2R diff (pp) |
|---|---|---|---|---|---|---|---|---|
""" + "\n".join(
        f"| {r['month']} | {r['n']} | {fmt(r['p1'], True)} | {fmt(r['p2'], True)} | {fmt(r['p3'], True)} "
        f"| {fmt(r['mfe'])} | {fmt(r['mae'])} | {fmt(r['c2'], True)} | {fmt(r['d2'], d=1)} |" for r in month_rows) + f"""

Months with event > control at +2R: {pos_months} of {len(month_rows)}. The preregistered requirement for {len(month_rows)} months is
{need_months}. December (from 12-23) and June (one day) are stubs.

![months](chart_months_2R.svg)

| slice | lift +2R (pp) | lift +3R (pp) |
|---|---|---|
""" + "\n".join(f"| {k} | {fmt(v[2.0], d=1)} | {fmt(v[3.0], d=1)} |" for k, v in slice_tab.items()) + f"""

## Special analysis — double breaks (descriptive only, not a filter)

**Trade-through breaks** of the OR, from 10:00 New York to the end of the trading day ({counts['days_with_or']} OR days):
- **Broke at least one side:** {int(broke_any.sum())} days ({broke_any.mean() * 100:.0f}%). Up {int(days.broke_up.sum())} ({days.broke_up.mean() * 100:.0f}%), down {int(days.broke_down.sum())}
  ({days.broke_down.mean() * 100:.0f}%), both {int((days.broke_up & days.broke_down).sum())} ({(days.broke_up & days.broke_down).mean() * 100:.0f}%).
- **First break:** {', '.join(f'{k} {v}' for k, v in days.first_break.value_counts().items())}.
- **P(opposite-side trade-through after the first break)** = {opp.sum()}/{len(brk)} = **{opp.mean() * 100:.0f}%**. Days whose first bar
  broke both sides at once are excluded from this ratio.

**Close-based:** P(opposite-direction two-close confirmation | a first confirmation that day) = {both_days}/{len(first_conf)} =
**{p_opp_conf * 100:.0f}%**.

**Outcomes by day type.** The day type is only known after the entry, so these rows use future information and
describe the setup; they are not a usable filter.

| group | n | P(+1R) | P(+2R) | P(+3R) | MFE32 med | MAE32 med |
|---|---|---|---|---|---|---|
""" + "\n".join(
        f"| {name} | {len(g)} | {fmt(rate(g, 1.0), True)} | {fmt(rate(g, 2.0), True)} | {fmt(rate(g, 3.0), True)} "
        f"| {fmt(g.mfe_32.median())} | {fmt(g.mae_32.median())} |"
        for name, g in (("events on single-direction-confirmation days", ev_single),
                        ("events on both-direction-confirmation days", ev_both),
                        ("  of which: the first confirmation that day", ev_both[~ev_both.opposite_confirmed_earlier]),
                        ("  of which: the second (opposite) confirmation", ev_both[ev_both.opposite_confirmed_earlier]),
                        ("events on single-side trade-through days", e_trade_single),
                        ("events on both-side trade-through days", e_trade_both))) + """

## Context features (recorded, not filtered)

| context | n | P(+2R) | MFE32 med | MAE32 med |
|---|---|---|---|---|
""" + "\n".join(ctx) + f"""

Tercile cells hold about 30 events each; a Wilson half-width at n = 30 is about ±17 pp. These rows are for the
feature library only.

## Statistical power

With {n2} resolved events at +2R and a control rate of {fmt(p0, True)}, the smallest lift this sample could detect
(95% two-sided, 80% power) is about **±{mde:.0f} pp**, before accounting for the reused control draws. The rule is
applied unchanged.

## Decision: **{decision}**

The rule is the H1/H2/H3 one, unchanged, with the preregistered slices long and short:
- **PROMISING** requires all of: a +2R lift ≥ {MIN_LIFT_PP:g} pp with the 95% CI above 0; event > control in at least two-thirds of months ({need_months} of {len(month_rows)}); a positive +2R lift in both slices.
- **WEAK**: a positive lift at +2R or +3R that fails those tests.
- **NO EDGE**: no positive lift at +2R or +3R.

Observed:
- +2R lift {l2['lift_pp']:+.1f} pp (CI {l2['ci_lo_pp']:+.1f} … {l2['ci_hi_pp']:+.1f});
- +3R lift {l3['lift_pp']:+.1f} pp (CI {l3['ci_lo_pp']:+.1f} … {l3['ci_hi_pp']:+.1f});
- {pos_months}/{len(month_rows)} months positive;
- slice lifts at +2R: {', '.join(f"{k} {fmt(v[2.0], d=1)}" for k, v in slice_tab.items())}.

## Interpretation

- **The central question gets a negative answer.** Does two-close acceptance outside the New York opening range beat
  comparable New York M15 bars? No. At +2R the events trail the controls by {-l2['lift_pp']:.1f} pp, and the whole bootstrap CI is
  below zero. The +1R, +3R and +4R lifts are negative too. Both preregistered slices are negative
  (long {fmt(slice_tab['long'][2.0], d=1)}, short {fmt(slice_tab['short'][2.0], d=1)} pp), and only {pos_months} of {len(month_rows)} months are positive.
- **The result holds without the controls.** The raw event P(+2R) of {fmt(l2['event_p'], True)} is below the 33.3% 1:2 break-even,
  before any cost. So the verdict does not rest on the thin control pool.
- **Excursions.** Median MFE matches the controls over 32 bars ({e.mfe_32.median():.2f}R vs {c.mfe_32.median():.2f}R), but median MAE is larger
  ({e.mae_32.median():.2f}R vs {c.mae_32.median():.2f}R). After acceptance, price tends to come back toward the OR midpoint rather than run.
- **Double breaks.** These are real and common:
  - the OR is traded through on both sides on {(days.broke_up & days.broke_down).mean() * 100:.0f}% of days, and
    {opp.mean() * 100:.0f}% of first breaks are followed by an opposite trade-through the same day;
  - the design's "75% up / 70% down" observation reproduces ({days.broke_up.mean() * 100:.0f}% / {days.broke_down.mean() * 100:.0f}%);
  - two-close confirmation in both directions before 13:00 New York is rare ({p_opp_conf * 100:.0f}% of confirmation days).
  Events on both-side trade-through days do worse, as expected: a later opposite break usually passes the OR-midpoint
  stop. That split uses post-entry information and is descriptive only.
- **Other cuts.** The month, direction and confirmation-hour cuts are shown in full. March is the only positive
  month (+4.9 pp). None of these cuts was preregistered and none is used. The context terciles are recorded for the
  feature library only.
- **No rescue.** Per the brief, H5 is not rescued with OR-width, direction, weekday, first-break, TVWAP, volume or
  time filters. Validation and OOS were not inspected. H4 can be evaluated separately after review.
"""
    (OUT / "report.md").write_text(report)
    (OUT / "h5_summary.json").write_text(json.dumps({
        "decision": decision, "events": len(e), "controls": len(c), "counts": counts,
        "lifts": {str(k): {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in v.items()}
                  for k, v in lifts.items()},
        "months": month_rows, "months_positive_2R": pos_months, "months_needed": need_months, "mde_pp": mde,
        "day_classes": {"long_only": long_only, "short_only": short_only, "both": both_days, "neither": neither},
        "p_opposite_trade_through_after_first": float(opp.mean()), "p_opposite_confirmation": p_opp_conf,
        "unique_control_bars": int(uniq_ctrl),
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
