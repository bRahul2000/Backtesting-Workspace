"""Gold V1 — H4 report: live-TVWAP mean-reversion race vs controls, standard R study, economics, decision.

    venv/bin/python research/gold_v1/h4/h4_study.py && venv/bin/python research/gold_v1/h4/h4_report.py

The comparison/bootstrap helpers are imported unchanged from the H1 report; the primary outcome column `r_tv`
(hit→win, stop→loss, ambiguous, session_end→none) plugs into the same functions. Reads only the development
artifacts written by h4_study.py.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import json                                                                             # noqa: E402
from pathlib import Path                                                                # noqa: E402

import numpy as np                                                                      # noqa: E402
import pandas as pd                                                                     # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "h1"))
from h1_report import MIN_LIFT_PP, fmt, lift, md_breakdown, p_win, svg_curve             # noqa: E402
from h1_study import HORIZONS, SEED, wilson                                            # noqa: E402

OUT = Path(__file__).resolve().parent
PRIMARY = "tv"


def rate(df, t):
    k, n = p_win(df, t)
    return k / n if n else np.nan


def ci_text(df, t):
    k, n = p_win(df, t)
    lo, hi = wilson(k, n)
    return f"{fmt(k / n if n else np.nan, True)} ({fmt(lo, True)}–{fmt(hi, True)}, n={n})"


def cons_rate(df):
    v = df["tv_outcome"]
    n = int(v.isin(["hit", "stop", "ambiguous"]).sum())
    return (v == "hit").sum() / n if n else np.nan


def expectancy(df):
    return df["tv_outcome_r"].mean(), df["tv_outcome_r"].mean() - df["spread_risk"].mean()


def svg_primary_months(rows, path: Path) -> None:
    w, h, pad = 600, 260, 44
    bw = (w - 2 * pad) / max(1, len(rows))
    y = lambda p: h - pad - p * (h - 2 * pad)                           # noqa: E731
    parts = ['<text x="50" y="20" font-size="12">P(TVWAP before −1R) by month — red H4, blue control</text>']
    for p in (0, .5, 1):
        parts.append(f'<line x1="{pad}" x2="{w - pad}" y1="{y(p):.1f}" y2="{y(p):.1f}" stroke="#ddd"/>'
                     f'<text x="6" y="{y(p) + 4:.1f}" font-size="11">{int(p * 100)}%</text>')
    for k, (m, pe, pc) in enumerate(rows):
        x0 = pad + k * bw
        for off, p, colour in ((0.15, pe, "#c0392b"), (0.5, pc, "#2471a3")):
            if not np.isnan(p):
                parts.append(f'<rect x="{x0 + off * bw:.1f}" y="{y(p):.1f}" width="{0.33 * bw:.1f}" '
                             f'height="{y(0) - y(p):.1f}" fill="{colour}"/>')
        parts.append(f'<text x="{x0 + 0.1 * bw:.1f}" y="{h - pad + 16}" font-size="11">{m}</text>')
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                    f'style="background:#fff;font-family:sans-serif">{"".join(parts)}</svg>\n')


def svg_target_hist(e, c, path: Path) -> None:
    """Distribution of the natural TVWAP target in R at entry (events vs controls)."""
    edges = np.arange(0, 1.61, 0.1)
    he = np.histogram(e["target_r"].clip(upper=1.59), edges)[0] / len(e)
    hc = np.histogram(c["target_r"].clip(upper=1.59), edges)[0] / len(c)
    w, h, pad = 600, 260, 44
    bw = (w - 2 * pad) / len(he)
    top = max(he.max(), hc.max())
    y = lambda p: h - pad - p / top * (h - 2 * pad)                     # noqa: E731
    parts = ['<text x="50" y="20" font-size="12">natural TVWAP target at entry (R) — red H4, blue control; '
             'last bin = ≥1.5R</text>']
    for k in range(len(he)):
        x0 = pad + k * bw
        parts.append(f'<rect x="{x0 + 0.1 * bw:.1f}" y="{y(he[k]):.1f}" width="{0.38 * bw:.1f}" '
                     f'height="{y(0) - y(he[k]):.1f}" fill="#c0392b"/>')
        parts.append(f'<rect x="{x0 + 0.5 * bw:.1f}" y="{y(hc[k]):.1f}" width="{0.38 * bw:.1f}" '
                     f'height="{y(0) - y(hc[k]):.1f}" fill="#2471a3"/>')
        if k % 2 == 0:
            parts.append(f'<text x="{x0:.1f}" y="{h - pad + 16}" font-size="11">{edges[k]:.1f}</text>')
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                    f'style="background:#fff;font-family:sans-serif">{"".join(parts)}</svg>\n')


def main() -> None:
    e = pd.read_csv(OUT / "h4_events_dev.csv")
    c = pd.read_csv(OUT / "h4_controls_dev.csv")
    counts = json.loads((OUT / "h4_counts_dev.json").read_text())
    gate = json.loads((OUT / "data_quality.json").read_text())
    assert e["entry_time"].max() < "2026-06-03", "non-development rows in the event set"

    prim = lift(e, c, PRIMARY)
    std = {t: lift(e, c, t) for t in (1.0, 2.0, 3.0, 4.0)}
    slices = {"long (lower band)": "long", "short (upper band)": "short"}
    slice_tab = {}
    for k, v in slices.items():
        a, b = rate(e[e.direction == v], PRIMARY), rate(c[c.direction == v], PRIMARY)
        slice_tab[k] = (a - b) * 100 if not (np.isnan(a) or np.isnan(b)) else np.nan

    month_rows = []
    for m in sorted(e.month.unique()):
        em = e[e.month == m]
        cm = c[c.event_signal_index.isin(em.signal_index)]
        pe, pc = rate(em, PRIMARY), rate(cm, PRIMARY)
        month_rows.append({"month": m, "n": len(em), "p_tv": pe, "c_tv": pc,
                           "d_tv": (pe - pc) * 100 if not (np.isnan(pe) or np.isnan(pc)) else np.nan,
                           "target_med": em.target_r.median(), "p1": rate(em, 1.0), "p2": rate(em, 2.0),
                           "mfe": em.mfe_32.median(), "mae": em.mae_32.median()})
    pos_months = sum(1 for r in month_rows if r["d_tv"] > 0)
    need_months = int(np.ceil(len(month_rows) * 2 / 3))
    exp_gross, exp_net = expectancy(e)
    cexp_gross, cexp_net = expectancy(c)

    tests = {
        "1_lift_ge_5pp_ci_above_0": bool(prim["lift_pp"] >= MIN_LIFT_PP and prim["ci_lo_pp"] > 0),
        "2_months_two_thirds": bool(pos_months >= need_months),
        "2_both_slices_positive": bool(all(v > 0 for v in slice_tab.values())),
        "4_expectancy_after_spread_gt_0": bool(exp_net > 0),
    }
    decision = "PROMISING" if all(tests.values()) else ("WEAK" if prim["lift_pp"] > 0 else "NO EDGE")

    svg_curve(e, c, OUT / "chart_standard_r_curve.svg")
    svg_primary_months([(r["month"], r["p_tv"], r["c_tv"]) for r in month_rows], OUT / "chart_months_tvwap.svg")
    svg_target_hist(e, c, OUT / "chart_target_r.svg")

    hits = e[e.tv_outcome == "hit"]
    chits = c[c.tv_outcome == "hit"]
    exc = []
    for name, df in (("H4 events", e), ("controls", c)):
        for hz in HORIZONS:
            exc.append(f"| {name} | {hz} | {fmt(df[f'mfe_{hz}'].median())} | {fmt(df[f'mfe_{hz}'].mean())} "
                       f"| {fmt(df[f'mae_{hz}'].median())} | {fmt(df[f'mae_{hz}'].mean())} |")

    ctx = []
    for col in ("session", "vol_regime", "expansion_before", "reentry_delay", "dow"):
        for v, g in e.groupby(col):
            ctx.append(f"| {col} = {v} | {len(g)} | {fmt(rate(g, PRIMARY), True)} | {fmt(g.target_r.median())} "
                       f"| {fmt(g.tv_outcome_r.mean())} |")
    for col in ("exh_dist_sigma", "exh_dist_atr", "tvwap_slope", "sigma_atr", "er_h1", "atr_pct", "tv_ratio",
                "target_r", "spread_risk", "prior_touches_session"):
        q = pd.qcut(e[col].rank(method="first"), 3, labels=["low", "mid", "high"])
        for v, g in e.groupby(q, observed=True):
            ctx.append(f"| {col} tercile {v} ({g[col].min():.3g}–{g[col].max():.3g}) | {len(g)} "
                       f"| {fmt(rate(g, PRIMARY), True)} | {fmt(g.target_r.median())} | {fmt(g.tv_outcome_r.mean())} |")

    by_month = e.groupby("month").size()
    full = by_month.drop(["2025-12", "2026-06"], errors="ignore")
    amb_std = int((e[[x for x in e.columns if x.startswith("r_") and x != "r_tv"]] == "ambiguous").any(axis=1).sum())
    p0, n1 = prim["control_p"], prim["event_n"]
    mde = (1.96 + 0.84) * np.sqrt(p0 * (1 - p0) * (1 / n1 + 1 / (5 * n1))) * 100
    oc = e.tv_outcome.value_counts()
    occ = c.tv_outcome.value_counts()
    ks = counts

    def lr(key):
        return f"{ks[key]['long']} | {ks[key]['short']} | {ks[key]['long'] + ks[key]['short']}"

    report = f"""# Gold V1 — H4 event study (TVWAP BAND EXHAUSTION FADE)

- **Data:** development data only, 2025-12-23 → 2026-06-02 (Exness XAUUSDm M15, bid). Validation and final OOS were not loaded.
- **Event span:** {e.reentry_time.min()[:10]} → {e.entry_time.max()[:10]}.
- **Rules:** implemented exactly as frozen in [preregistration.md](preregistration.md) (SHA-256 92f25167…, frozen before any H4
  code ran).
- **Signal:** range regime (H1 ER ≤ 0.15), a close strictly outside TVWAP ± 2σ, then a close strictly inside ± 1σ
  within 2 bars. The New York open hour is excluded. Entry at the next open; stop at the extreme of the exhaustion
  streak through the reentry bar, with no buffer.
- **Primary target:** the live causal TVWAP. During each bar the level is TVWAP at the previous close.
- **Data quality gate: {gate['result']}.** All 12 H1 checks were rerun, plus 2 H4 checks; see [data_quality.md](data_quality.md).

## Counts

| stage | long (lower band) | short (upper band) | total |
|---|---|---|---|
| raw closes outside ±2σ (all bars) | {lr('raw_2sigma_closes')} |
| eligible outside closes (≥ 5th session bar) | {lr('eligible_2sigma_closes')} |
| exhaustion streaks | {lr('streaks')} |
| expired without reentry in 2 bars | {lr('expired_no_reentry')} |
| cancelled by an opposite-side 2σ close | {lr('cancelled_opposite_2sigma')} |
| reentries inside ±1σ within 2 bars | {lr('reentries_within_2')} |
| excluded: not range regime at the reentry | {lr('excluded_not_range_regime')} |
| excluded: New York open hour (design) | {lr('excluded_ny_open_hour')} |
| **unique H4 events** | {ks['events']['long']} | {ks['events']['short']} | **{len(e)}** |

- **Rejected:** risk ≤ 0 {ks['rejected_risk_le_0']}; no natural target (entry at or beyond TVWAP, target_R ≤ 0)
  {ks['rejected_target_le_0']}; no entry bar {ks['no_entry_bar']}.
- **By month:** {', '.join(f'{m} {n}' for m, n in by_month.items())}. Full months (Jan–May): mean {full.mean():.1f}, median
  {full.median():.0f} per month, about 0.3 per trading day (the design's guide: 0.3–0.8 per day).
- **By session:** {', '.join(f'{k} {v}' for k, v in e.session.value_counts().items())}.
- **Risk:**
  - in USD: median {e.risk.median():.2f}, IQR {e.risk.quantile(.25):.2f}–{e.risk.quantile(.75):.2f}, max {e.risk.max():.2f};
  - in ATR units: median {e.risk_atr.median():.2f}, IQR {e.risk_atr.quantile(.25):.2f}–{e.risk_atr.quantile(.75):.2f}.
- **Primary outcomes:** events {', '.join(f'{k} {v}' for k, v in oc.items())}; controls {', '.join(f'{k} {v}' for k, v in occ.items())}.
- **AMBIGUOUS_INTRABAR:** {int(oc.get('ambiguous', 0))} events in the primary race and {amb_std} events at some standard R target.
  They are excluded from the P(...) figures and counted as −1R in the expectancy.

## Natural TVWAP target (critical)

| | H4 events | controls |
|---|---|---|
| target R at entry — median | **{e.target_r.median():.2f}R** | {c.target_r.median():.2f}R |
| target R at entry — mean | {e.target_r.mean():.2f}R | {c.target_r.mean():.2f}R |
| target R — IQR | {e.target_r.quantile(.25):.2f}–{e.target_r.quantile(.75):.2f}R | {c.target_r.quantile(.25):.2f}–{c.target_r.quantile(.75):.2f}R |
| share of events with target ≥ 1R | {(e.target_r >= 1).mean() * 100:.0f}% | {(c.target_r >= 1).mean() * 100:.0f}% |
| realized R when TVWAP is hit — median | {hits.tv_realized_r.median():.2f}R | {chits.tv_realized_r.median():.2f}R |
| realized R when TVWAP is hit — mean | {hits.tv_realized_r.mean():.2f}R | {chits.tv_realized_r.mean():.2f}R |
| time to TVWAP (hits) — median | {hits.tv_bars.median():.0f} bars / {hits.tv_minutes.median():.0f} min | {chits.tv_bars.median():.0f} bars / {chits.tv_minutes.median():.0f} min |
| time to TVWAP (hits) — mean | {hits.tv_bars.mean():.1f} bars / {hits.tv_minutes.mean():.0f} min | {chits.tv_bars.mean():.1f} bars / {chits.tv_minutes.mean():.0f} min |

The design expected TVWAP to sit about 1–1.5R away. With a structural stop at the exhaustion extreme, it sits about
{e.target_r.median():.2f}R away. The target is live and usually moves toward the entry, so realized R at a hit is similar
to or smaller than the target at entry.

![target R](chart_target_r.svg)

## Primary analysis — P(TVWAP before −1R)

- **Controls:** {len(c)} draws, deterministic (seed {SEED}), 5 per event.
- **Matching:** range-regime bars (ER ≤ 0.15) in the same session, with an ATR percentile within ±10, TVWAP on the
  trade's target side, and a TVWAP distance within ±0.25 ATR of the event's.
- **Exclusions:** no H4 reentry bars, not the New York open hour, at least the 5th bar of the session, and more than 8
  bars from any event.
- **Direction and stop:** each control takes the event's direction and its risk in ATR units.
- **Relaxations:** the distance condition was relaxed for {ks['controls']['dist_relaxed_events']} events and the ATR condition for
  {ks['controls']['atr_relaxed_events']}. {ks['controls']['discarded_target_le_0']} control draw was discarded for target_R ≤ 0. Only {c.signal_index.nunique()} unique control bars were drawn.

| outcome | H4 events | controls | lift (pp) | lift 95% CI (event-clustered bootstrap) |
|---|---|---|---|---|
| **P(TVWAP before −1R)** | {ci_text(e, PRIMARY)} | {ci_text(c, PRIMARY)} | **{prim['lift_pp']:+.1f}** | {prim['ci_lo_pp']:+.1f} … {prim['ci_hi_pp']:+.1f} |
| conservative (ambiguous = stop) | {fmt(cons_rate(e), True)} | {fmt(cons_rate(c), True)} | {(cons_rate(e) - cons_rate(c)) * 100:+.1f} | — |

### Economics (indicative; spread semantics unresolved)

| | H4 events | controls |
|---|---|---|
| spread as % of 1R — median | {e.spread_risk.median() * 100:.2f}% | {c.spread_risk.median() * 100:.2f}% |
| spread as % of the natural TVWAP target — median | {e.spread_target.median() * 100:.1f}% | {(c.spread_risk / c.target_r).median() * 100:.1f}% |
| spread as % of the natural TVWAP target — mean | {e.spread_target.mean() * 100:.1f}% | {(c.spread_risk / c.target_r).mean() * 100:.1f}% |
| expectancy per trade, gross (R) | {exp_gross:+.3f} | {cexp_gross:+.3f} |
| expectancy per trade, after mean spread/risk (R) | **{exp_net:+.3f}** | {cexp_net:+.3f} |

Expectancy is the mean outcome R over all events: realized R at a TVWAP hit, −1 at the stop, −1 when ambiguous, and
mark-to-market at the session end.

## Standard R study (comparability only; not the H4 criterion)

| target | H4 events | controls | lift (pp) | lift 95% CI | break-even |
|---|---|---|---|---|---|
""" + "\n".join(
        f"| +{t:g}R | {ci_text(e, t)} | {ci_text(c, t)} | {v['lift_pp']:+.1f} | {v['ci_lo_pp']:+.1f} … "
        f"{v['ci_hi_pp']:+.1f} | {100 / (1 + t):.1f}% |" for t, v in std.items()) + f"""

![standard R curve](chart_standard_r_curve.svg)

| sample | bars | MFE median | MFE mean | MAE median | MAE mean |
|---|---|---|---|---|---|
""" + "\n".join(exc) + f"""

### Breakdown — H4 events (standard R)

{md_breakdown({"ALL": e, "long (lower band)": e[e.direction == "long"], "short (upper band)": e[e.direction == "short"],
               **{s: e[e.session == s] for s in ("Asia", "London", "Overlap", "New York", "Other")}})}
## Monthly stability

| month | events | P(TVWAP first) | control | diff (pp) | median target R | +1R | +2R | MFE32 med | MAE32 med |
|---|---|---|---|---|---|---|---|---|---|
""" + "\n".join(
        f"| {r['month']} | {r['n']} | {fmt(r['p_tv'], True)} | {fmt(r['c_tv'], True)} | {fmt(r['d_tv'], d=1)} "
        f"| {fmt(r['target_med'])} | {fmt(r['p1'], True)} | {fmt(r['p2'], True)} | {fmt(r['mfe'])} | {fmt(r['mae'])} |"
        for r in month_rows) + f"""

Months with event > control on the primary rate: {pos_months} of {len(month_rows)}; the preregistered requirement is {need_months} of {len(month_rows)}.
December (from 12-23) and June (2 days) are stubs; March has a single event.

![months](chart_months_tvwap.svg)

| slice | primary lift (pp) |
|---|---|
""" + "\n".join(f"| {k} | {fmt(v, d=1)} |" for k, v in slice_tab.items()) + """

## Context features (recorded, not filtered)

| context | n | P(TVWAP first) | median target R | mean outcome R |
|---|---|---|---|---|
""" + "\n".join(ctx) + f"""

Tercile cells hold 11 events each, so they are noise at this sample size. They are for the feature library only.

## Statistical power

With {n1} resolved events and a control rate of {fmt(p0, True)}, the smallest primary lift this sample could detect
(95% two-sided, 80% power) is about **±{mde:.0f} pp**.

## Decision: **{decision}**

The preregistered H4 rule, unchanged:

| test | result |
|---|---|
| 1. primary lift ≥ {MIN_LIFT_PP:g} pp and 95% CI above 0 | {'PASS' if tests['1_lift_ge_5pp_ci_above_0'] else 'FAIL'}: {prim['lift_pp']:+.1f} pp (CI {prim['ci_lo_pp']:+.1f} … {prim['ci_hi_pp']:+.1f}) |
| 2a. event > control in ≥ {need_months} of {len(month_rows)} months | {'PASS' if tests['2_months_two_thirds'] else 'FAIL'}: {pos_months} of {len(month_rows)} |
| 2b. positive lift in both slices | {'PASS' if tests['2_both_slices_positive'] else 'FAIL'}: {', '.join(f'{k} {fmt(v, d=1)}' for k, v in slice_tab.items())} |
| 3. uncertainty (covered by test 1's CI) | {'PASS' if tests['1_lift_ge_5pp_ci_above_0'] else 'FAIL'} |
| 4. expectancy after spread > 0 | {'PASS' if tests['4_expectancy_after_spread_gt_0'] else 'FAIL'}: {exp_net:+.3f} R per trade |

PROMISING needs all of these. WEAK means a positive primary lift that fails any test. NO EDGE means a primary lift ≤ 0.

## Interpretation — where the effect is and where it disappears

- **Mean reversion looks real in direction, not in significance.** After a ±2σ exhaustion and a ±1σ reentry, price
  reached TVWAP before the stop more often than comparable range-regime bars ({fmt(prim['event_p'], True)} vs
  {fmt(prim['control_p'], True)}). But with {len(e)} events the CI runs from {prim['ci_lo_pp']:+.1f} to {prim['ci_hi_pp']:+.1f} pp, and the sample could only detect
  about ±{mde:.0f} pp.
- **The lift is one-sided.** Lower-band fades (long, {ks['events']['long']} events) carry it ({fmt(slice_tab['long (lower band)'], d=1)} pp). Upper-band fades
  (short, {ks['events']['short']} events) do not ({fmt(slice_tab['short (upper band)'], d=1)} pp). Development gold was flat end to end (4466 → 4474), but it
  rallied from December to February and declined from March to May. The months where H4 beats its controls are
  the rally months, so regime drift may be part of the long-side number. That is not tested here, and it is **not** a
  reason to keep long-only fades.
- **It fades over time.** December to March are positive, April is flat (+1.0), and May (−10.0) and June (−44.4) are
  negative. The 5-of-7 month pass relies on December (2 events) and March (1 event).
- **It fails on economics.** The natural target is small: median {e.target_r.median():.2f}R at entry, {hits.tv_realized_r.median():.2f}R realized at a
  median hit, and only {(e.target_r >= 1).mean() * 100:.0f}% of events had a target of 1R or more. So a ~77% hit rate still gives a
  negative expectancy: {exp_gross:+.3f}R gross and {exp_net:+.3f}R after the indicative spread. The median spread is 1.6% of
  1R but 5.8% of the natural target. The mean (38%) is dominated by one event with a 0.003R target. The design's
  "≈ 1–1.5R" TVWAP distance does not hold with a structural stop at the exhaustion extreme.
- **The controls lose too** ({cexp_gross:+.3f}R gross). A fade toward TVWAP in the range regime is not a positive-expectancy
  baseline on this data at these stop sizes. H4 improves the hit rate but not enough to pay for a target a third of
  the risk.
- **No rescue.** Per the brief, H4 is not rescued with side, session, σ-distance, TVWAP-slope, volatility, volume or
  time filters. Validation and OOS were not inspected. The consolidated H1–H5 comparison is deferred until H4 has
  been reviewed, as instructed.
"""
    (OUT / "report.md").write_text(report)
    (OUT / "h4_summary.json").write_text(json.dumps({
        "decision": decision, "tests": tests, "events": len(e), "controls": len(c), "counts": counts,
        "primary": {k: (list(v) if isinstance(v, tuple) else v) for k, v in prim.items()},
        "standard": {str(k): {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in v.items()}
                     for k, v in std.items()},
        "target_r": {"median": e.target_r.median(), "mean": e.target_r.mean()},
        "expectancy": {"gross": exp_gross, "net": exp_net, "control_gross": cexp_gross, "control_net": cexp_net},
        "months": month_rows, "months_positive": pos_months, "months_needed": need_months,
        "slices": slice_tab, "mde_pp": mde,
    }, indent=1, default=float) + "\n")
    print(decision, tests)
    print({k: prim[k] for k in ("event_p", "control_p", "lift_pp", "ci_lo_pp", "ci_hi_pp")})
    print("exp", round(exp_gross, 3), round(exp_net, 3), "ctrl", round(cexp_gross, 3), round(cexp_net, 3))
    print([(r["month"], r["n"], None if np.isnan(r["d_tv"]) else round(r["d_tv"], 1)) for r in month_rows])
    print(slice_tab, "MDE", round(mde, 1))


if __name__ == "__main__":
    main()
