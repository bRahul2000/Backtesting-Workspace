"""Gold V1 — H1 report: tables, event-vs-control comparison, SVG charts and the pre-registered decision.

    python research/gold_v1/h1/h1_study.py && python research/gold_v1/h1/h1_report.py

Reads only the development artifacts written by h1_study.py.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from h1_study import SEED, TARGETS, summary, wilson

OUT = Path(__file__).resolve().parent
BOOT = 5000
# Decision rule, fixed before the results were looked at (see methodology.md)
MIN_LIFT_PP = 5.0


def p_win(df: pd.DataFrame, t: float) -> tuple[int, int]:
    col = df[f"r_{t}"]
    return int((col == "win").sum()), int(col.isin(["win", "loss"]).sum())


def lift(events: pd.DataFrame, controls: pd.DataFrame, t: float) -> dict:
    """Event minus control P(+tR before -1R), ambiguous and unresolved excluded; 95 % CI from a bootstrap that
    resamples events together with their own matched controls."""
    kw, nw = p_win(events, t)
    kc, nc = p_win(controls, t)
    pe, pc = (kw / nw if nw else np.nan), (kc / nc if nc else np.nan)
    rng = np.random.default_rng(SEED)
    ids = events["signal_index"].to_numpy()
    ev = events.set_index("signal_index")[f"r_{t}"]
    cg = {k: g[f"r_{t}"].to_numpy() for k, g in controls.groupby("event_signal_index")}
    diffs = []
    for _ in range(BOOT):
        pick = rng.choice(ids, size=len(ids), replace=True)
        e = ev.loc[pick].to_numpy()
        c = np.concatenate([cg.get(i, np.array([], dtype=object)) for i in pick])
        ew, en = (e == "win").sum(), np.isin(e, ["win", "loss"]).sum()
        cw, cn = (c == "win").sum(), np.isin(c, ["win", "loss"]).sum()
        if en and cn:
            diffs.append(ew / en - cw / cn)
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"event_p": pe, "event_n": nw, "control_p": pc, "control_n": nc, "lift_pp": (pe - pc) * 100,
            "ci_lo_pp": lo * 100, "ci_hi_pp": hi * 100, "event_wilson": wilson(kw, nw)}


def fmt(x, pct=False, d=2):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x * 100:.1f}%" if pct else f"{x:.{d}f}"


def md_breakdown(groups: dict[str, pd.DataFrame]) -> str:
    head = ("| group | n | P(+1R) | P(+2R) | P(+3R) | P(+4R) | amb | MFE32 med | MFE32 mean | MAE32 med | MAE32 mean "
            "| MFE→stop med |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n")
    rows = []
    for name, df in groups.items():
        if not len(df):
            continue
        s = summary(df)
        amb = int((df[[f"r_{t}" for t in TARGETS]] == "ambiguous").any(axis=1).sum())
        rows.append(f"| {name} | {s['n']} | {fmt(s['p1R'], True)} | {fmt(s['p2R'], True)} | {fmt(s['p3R'], True)} "
                    f"| {fmt(s['p4R'], True)} | {amb} | {fmt(s['mfe32_med'])} | {fmt(s['mfe32_mean'])} "
                    f"| {fmt(s['mae32_med'])} | {fmt(s['mae32_mean'])} | {fmt(df['mfe_to_stop'].median())} |")
    return head + "\n".join(rows) + "\n"


def svg_curve(e: pd.DataFrame, c: pd.DataFrame, path: Path) -> None:
    """P(+tR before -1R) for events vs controls across all targets, with the break-even curve 1/(1+t)."""
    w, h, pad = 560, 320, 44
    xs = list(TARGETS)
    x = lambda t: pad + (t - 0.5) / 3.5 * (w - 2 * pad)                 # noqa: E731
    y = lambda p: h - pad - p * (h - 2 * pad) / 0.8                    # noqa: E731
    def line(ps, colour, dash=""):
        pts = " ".join(f"{x(t):.1f},{y(p):.1f}" for t, p in zip(xs, ps))
        return f'<polyline fill="none" stroke="{colour}" stroke-width="2" {dash} points="{pts}"/>'
    pe = [p_win(e, t)[0] / max(1, p_win(e, t)[1]) for t in xs]
    pc = [p_win(c, t)[0] / max(1, p_win(c, t)[1]) for t in xs]
    be = [1 / (1 + t) for t in xs]
    grid = "".join(f'<line x1="{pad}" x2="{w - pad}" y1="{y(p):.1f}" y2="{y(p):.1f}" stroke="#ddd"/>'
                   f'<text x="6" y="{y(p) + 4:.1f}" font-size="11">{int(p * 100)}%</text>' for p in (0, .2, .4, .6, .8))
    ticks = "".join(f'<text x="{x(t) - 8:.1f}" y="{h - pad + 16}" font-size="11">{t:g}R</text>' for t in xs)
    legend = ('<text x="330" y="24" font-size="12" fill="#c0392b">H1 events</text>'
              '<text x="330" y="40" font-size="12" fill="#2471a3">matched controls</text>'
              '<text x="330" y="56" font-size="12" fill="#777">break-even 1/(1+t)</text>')
    body = grid + ticks + legend + line(pe, "#c0392b") + line(pc, "#2471a3") + line(be, "#777", 'stroke-dasharray="4 3"')
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                    f'style="background:#fff;font-family:sans-serif">{body}</svg>\n')


def svg_months(rows: list[tuple[str, float, float]], path: Path) -> None:
    w, h, pad = 560, 260, 44
    bw = (w - 2 * pad) / max(1, len(rows))
    y = lambda p: h - pad - p * (h - 2 * pad) / 0.8                    # noqa: E731
    parts = [f'<line x1="{pad}" x2="{w - pad}" y1="{y(1 / 3):.1f}" y2="{y(1 / 3):.1f}" stroke="#777" '
             f'stroke-dasharray="4 3"/><text x="{w - pad - 110}" y="{y(1 / 3) - 4:.1f}" font-size="11">'
             f'2R break-even 33.3%</text>']
    for k, (m, pe, pc) in enumerate(rows):
        x0 = pad + k * bw
        for off, p, colour in ((0.15, pe, "#c0392b"), (0.5, pc, "#2471a3")):
            if not np.isnan(p):
                parts.append(f'<rect x="{x0 + off * bw:.1f}" y="{y(p):.1f}" width="{0.33 * bw:.1f}" '
                             f'height="{y(0) - y(p):.1f}" fill="{colour}"/>')
        parts.append(f'<text x="{x0 + 0.2 * bw:.1f}" y="{h - pad + 16}" font-size="11">{m}</text>')
    parts.append('<text x="50" y="20" font-size="12">P(+2R before −1R) by month — red H1, blue control</text>')
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                    f'style="background:#fff;font-family:sans-serif">{"".join(parts)}</svg>\n')


def main() -> None:
    e = pd.read_csv(OUT / "h1_events_dev.csv")
    c = pd.read_csv(OUT / "h1_controls_dev.csv")
    raw = json.loads((OUT / "h1_raw_sweeps_dev.json").read_text())
    gate = json.loads((OUT / "data_quality.json").read_text())
    assert e["entry_time"].max() < "2026-06-03", "non-development rows in the event set"

    groups = {"ALL": e, **{r: e[e.reference == r] for r in ("Asia high", "Asia low", "PDH", "PDL")},
              "long": e[e.direction == "long"], "short": e[e.direction == "short"],
              **{s: e[e.session == s] for s in ("London", "New York", "Overlap", "Asia", "Other")}}
    cgroups = {"ALL": c, **{r: c[c.reference == r] for r in ("Asia high", "Asia low", "PDH", "PDL")},
               "long": c[c.direction == "long"], "short": c[c.direction == "short"],
               **{s: c[c.session == s] for s in ("London", "New York", "Overlap", "Asia", "Other")}}
    lifts = {t: lift(e, c, t) for t in (1.0, 2.0, 3.0, 4.0)}

    # consistency of the +2R and +3R lift across slices (sign only; slices are small)
    def slice_lift(mask_e, mask_c, t):
        kw, nw = p_win(e[mask_e], t)
        kc, nc = p_win(c[mask_c], t)
        return (kw / nw - kc / nc) * 100 if nw and nc else np.nan
    months = sorted(e.month.unique())
    month_rows = []
    for m in months:
        ce = c[c.event_signal_index.isin(e.loc[e.month == m, "signal_index"])]      # controls of that month's events
        kw, nw = p_win(e[e.month == m], 2.0)
        kc, nc = p_win(ce, 2.0)
        month_rows.append((m, kw / nw if nw else np.nan, kc / nc if nc else np.nan, nw))
    slices = {
        "long": (e.direction == "long", c.direction == "long"),
        "short": (e.direction == "short", c.direction == "short"),
        "Asia refs": (e.reference.str.startswith("Asia"), c.reference.str.startswith("Asia")),
        "PD refs": (e.reference.str.startswith("PD"), c.reference.str.startswith("PD")),
    }
    slice_tab = {name: {t: slice_lift(me, mc, t) for t in (2.0, 3.0)} for name, (me, mc) in slices.items()}
    pos_months = sum(1 for _, pe, pc, _ in month_rows if pe > pc)

    l2, l3 = lifts[2.0], lifts[3.0]
    promising = (l2["lift_pp"] >= MIN_LIFT_PP and l2["ci_lo_pp"] > 0 and pos_months >= 4
                 and all(v[2.0] > 0 for v in slice_tab.values()))
    positive = l2["lift_pp"] > 0 or l3["lift_pp"] > 0
    decision = "PROMISING" if promising else ("WEAK" if positive else "NO EDGE")

    svg_curve(e, c, OUT / "chart_target_curve.svg")
    svg_months([(m, pe, pc) for m, pe, pc, _ in month_rows], OUT / "chart_months_2R.svg")

    ctx = []
    for col, bins in (("regime", None), ("vol_regime", None), ("compression", None), ("expansion", None)):
        for v, g in e.groupby(col):
            kw, nw = p_win(g, 2.0)
            ctx.append(f"| {col} = {v} | {len(g)} | {fmt(kw / nw if nw else np.nan, True)} "
                       f"| {fmt(g['mfe_32'].median())} | {fmt(g['mae_32'].median())} |")
    for col in ("sweep_depth_atr", "reclaim_delay", "tvwap_slope", "tv_ratio", "risk_atr", "spread_risk"):
        q = pd.qcut(e[col].rank(method="first"), 3, labels=["low", "mid", "high"])
        for v, g in e.groupby(q, observed=True):
            kw, nw = p_win(g, 2.0)
            ctx.append(f"| {col} tercile {v} ({g[col].min():.3g}–{g[col].max():.3g}) | {len(g)} "
                       f"| {fmt(kw / nw if nw else np.nan, True)} | {fmt(g['mfe_32'].median())} "
                       f"| {fmt(g['mae_32'].median())} |")

    by_month = e.groupby("month").size()
    per_month_full = by_month.drop("2025-12", errors="ignore")                # December is a 6-trading-day stub
    amb_any = int((e[[f"r_{t}" for t in TARGETS]] == "ambiguous").any(axis=1).sum())
    unresolved2 = int(e["r_2.0"].isin(["none", "truncated"]).sum())

    report = f"""# Gold V1 — H1 event study (SWEEP + TVWAP RECLAIM)

Development data only: 2025-12-23 → 2026-06-02 (Exness XAUUSDm M15, bid); events span
{e.sweep_time.min()[:10]} → {e.entry_time.max()[:10]}. No validation or final-OOS row was loaded (the loader cuts at 2026-06-03 00:00 UTC before any computation).

**Data quality gate: {gate['result']}** (details: [data_quality.md](data_quality.md)).

## Counts

- Raw sweep bars (every bar meeting the sweep condition): {sum(raw.values())} — {', '.join(f'{k} {v}' for k, v in raw.items())}.
- Valid H1 events (first sweep per trading day and reference followed by a TVWAP reclaim within 4 bars, risk > 0):
  **{len(e)}**.
- Signals by month: {', '.join(f'{m} {n}' for m, n in by_month.items())}. Full months (Jan–May): mean
  {per_month_full.mean():.1f}, median {per_month_full.median():.0f} per month.
- Intrabar-ambiguous events (a target and −1R inside one M15 bar, any target): {amb_any}. Events with no +2R/−1R
  resolution within 96 bars: {unresolved2}. Both are excluded from the P(...) figures.
- Risk (entry − sweep extreme): median {e.risk.median():.2f} USD, IQR {e.risk.quantile(.25):.2f}–{e.risk.quantile(.75):.2f},
  max {e.risk.max():.2f}; in ATR units median {e.risk_atr.median():.2f}, IQR {e.risk_atr.quantile(.25):.2f}–{e.risk_atr.quantile(.75):.2f}.
- Spread / risk: median {e.spread_risk.median() * 100:.2f}%, 90th pct {e.spread_risk.quantile(.9) * 100:.2f}%, max
  {e.spread_risk.max() * 100:.2f}% (spread field semantics unresolved; treat as indicative).

## Breakdown — H1 events

P(+tR) = P(+tR reached before −1R), ambiguous and unresolved excluded. MFE/MAE in R over 32 bars (8 h); MFE→stop
= maximum favourable excursion until −1R (or 96 bars).

{md_breakdown(groups)}
## Breakdown — matched controls

Controls: {len(c)} bars ({len(c) // max(1, len(e))} per event), same session and volatility regime, same direction and
same risk in ATR units, not within ±8 bars of any event, fixed seed {SEED}.

{md_breakdown(cgroups)}
## Edge test — events vs controls

| target | event P | n | control P | n | lift (pp) | 95% CI (event-clustered bootstrap) | break-even |
|---|---|---|---|---|---|---|---|
""" + "\n".join(
        f"| +{t:g}R | {fmt(v['event_p'], True)} | {v['event_n']} | {fmt(v['control_p'], True)} | {v['control_n']} "
        f"| {v['lift_pp']:+.1f} | {v['ci_lo_pp']:+.1f} … {v['ci_hi_pp']:+.1f} | {100 / (1 + t):.1f}% |"
        for t, v in lifts.items()) + f"""

![target curve](chart_target_curve.svg)

MFE vs MAE (32 bars, medians): events MFE {e.mfe_32.median():.2f}R / MAE {e.mae_32.median():.2f}R; controls
MFE {c.mfe_32.median():.2f}R / MAE {c.mae_32.median():.2f}R.

### Consistency

| month | event P(+2R) | n | control P(+2R) |
|---|---|---|---|
""" + "\n".join(f"| {m} | {fmt(pe, True)} | {n} | {fmt(pc, True)} |" for m, pe, pc, n in month_rows) + f"""

Months with event > control at +2R: {pos_months} of {len(month_rows)}.

![months](chart_months_2R.svg)

| slice | lift +2R (pp) | lift +3R (pp) |
|---|---|---|
""" + "\n".join(f"| {k} | {v[2.0]:+.1f} | {v[3.0]:+.1f} |" for k, v in slice_tab.items()) + """

## Context features (descriptive only — nothing was filtered or tuned)

| context | n | P(+2R) | MFE32 med | MAE32 med |
|---|---|---|---|---|
""" + "\n".join(ctx) + f"""

With ~100 events, context cells hold 9–93 events; a ±15 pp difference between cells is within noise
(Wilson half-width at n = 30 is about ±17 pp). These rows are recorded for later hypotheses, not for selection.

## Decision: **{decision}**

Pre-registered rule (methodology.md): PROMISING needs a +2R lift ≥ {MIN_LIFT_PP:g} pp over the matched control with the
95% CI above 0, event > control in at least 4 of 6 months, and a positive +2R lift in long, short, Asia-reference and
PD-reference slices. WEAK = positive lift that fails those tests. NO EDGE = no positive lift at +2R or +3R.

Observed: +2R lift {l2['lift_pp']:+.1f} pp (CI {l2['ci_lo_pp']:+.1f} … {l2['ci_hi_pp']:+.1f}), +3R lift
{l3['lift_pp']:+.1f} pp (CI {l3['ci_lo_pp']:+.1f} … {l3['ci_hi_pp']:+.1f}), {pos_months}/{len(month_rows)} months positive.

## Interpretation

- H1 events reach +tR before −1R at the same rate as ordinary M15 bars in the same session and volatility regime,
  with the same direction and the same ATR-scaled stop. The sweep + TVWAP reclaim adds nothing measurable at +2R/+3R;
  at +1R it is worse ({lifts[1.0]['lift_pp']:+.1f} pp), and median 32-bar MFE is lower than the control's
  ({e.mfe_32.median():.2f}R vs {c.mfe_32.median():.2f}R) with similar MAE — the favourable-MFE-vs-MAE criterion also fails.
- Raw event P(+2R) ({fmt(l2['event_p'], True)}) sits on the 1:2 break-even (33.3%) before spread and commission.
- The sign is not stable in time: Dec–Mar every month is below control, Apr–May above. That is a regime pattern in
  the underlying market, not a property of the setup.
- Short / PD-reference slices show +5 … +8 pp and long / Asia-reference slices −8 … −10 pp. These are post-hoc
  subsets of a null overall result, each with n ≈ 50 and CIs spanning ±15 pp; they are **not** grounds to keep H1 and
  must not be promoted to filters. The context-feature terciles are recorded for the feature library only.
- Per the brief, validation and final-OOS data were not inspected and will not be used to rescue H1. H1 stops here.
"""
    (OUT / "report.md").write_text(report)
    (OUT / "h1_summary.json").write_text(json.dumps({
        "decision": decision, "events": len(e), "controls": len(c), "raw_sweeps": raw,
        "lifts": {str(k): {kk: (vv if not isinstance(vv, tuple) else list(vv)) for kk, vv in v.items()}
                  for k, v in lifts.items()},
        "months_positive_2R": pos_months, "slices": {k: {str(t): x for t, x in v.items()} for k, v in slice_tab.items()},
    }, indent=1, default=float) + "\n")
    print(decision)
    print(json.dumps({str(k): {kk: v[kk] for kk in ("event_p", "control_p", "lift_pp", "ci_lo_pp", "ci_hi_pp")}
                      for k, v in lifts.items()}, indent=1, default=float))
    print("months", month_rows)
    print("slices", slice_tab)


if __name__ == "__main__":
    main()
