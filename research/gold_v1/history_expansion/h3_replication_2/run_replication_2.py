"""Gold V1 — frozen H3 SECOND independent replication on the repaired 2017-06 → 2021-08 history.

    venv/bin/python research/gold_v1/history_expansion/h3_replication_2/run_replication_2.py [--detect-only]

Implements H3_REPLICATION_2_PREREGISTRATION.md. H3 rules, forward race, controls and bootstrap are the frozen
development functions, imported unchanged (bytecode writing disabled):
  h1_study.features / forward / wilson / trading_days,  h3_study.h3_features / detect / controls / h3_gate,
  h1_report.lift / p_win.
Replication-specific code = data window, provenance flags, tables and the preregistered two-gate classification.
Input: repaired/xauusd_XAUUSDm_M15_repaired.csv only (ends 2021-08-31 20:45 UTC — before the sealed holdout).
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
import json                                                                             # noqa: E402
from pathlib import Path                                                                # noqa: E402
from zoneinfo import ZoneInfo                                                           # noqa: E402

import numpy as np                                                                      # noqa: E402
import pandas as pd                                                                     # noqa: E402

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
GOLD = EXP.parent
sys.path.insert(0, str(GOLD / "h1"))
sys.path.insert(0, str(GOLD / "h3"))
import h1_study as h1                                                                   # noqa: E402
import h3_study as h3                                                                   # noqa: E402
from h1_report import fmt, lift, p_win                                                  # noqa: E402

DATA = EXP / "repaired" / "xauusd_XAUUSDm_M15_repaired.csv"
MANIFEST = EXP / "repaired" / "removal_manifest.csv"
WARMUP_START = pd.Timestamp("2017-05-01 00:00", tz="UTC")
REPL_START = pd.Timestamp("2017-06-01 00:00", tz="UTC")
REPL_END_EXCL = pd.Timestamp("2021-08-31 22:00", tz="UTC")
YEARS = (2017, 2018, 2019, 2020, 2021)
TARGETS = (1.0, 2.0, 3.0, 4.0)
PRACTICAL_PP = 5.0
NY = ZoneInfo("America/New_York")
OUTAGES = [("2018-01-31 14:00", "2018-02-02 12:45"), ("2018-08-16 08:45", "2018-08-16 09:30"),
           ("2018-08-27 02:15", "2018-08-27 05:30"), ("2018-08-27 09:30", "2018-08-27 10:45")]
BREAK_VARIANT_DAYS = ["2017-06-06", "2017-07-11", "2018-09-20", "2019-03-11", "2019-03-12", "2019-03-13"]


def load() -> pd.DataFrame:
    raw = pd.read_csv(DATA)
    raw["time"] = pd.to_datetime(raw["timestamp"], format="%Y.%m.%d %H:%M:%S", utc=True)
    assert raw["time"].min() >= WARMUP_START and raw["time"].max() < REPL_END_EXCL
    assert raw["time"].is_monotonic_increasing and not raw["time"].duplicated().any()
    return raw.drop(columns=["timestamp"]).reset_index(drop=True)


def rate(df, t):
    k, n = p_win(df, t)
    return k / n if n else np.nan


def wtext(df, t):
    k, n = p_win(df, t)
    lo, hi = h1.wilson(k, n)
    return f"{fmt(k / n if n else np.nan, True)} ({fmt(lo, True)}–{fmt(hi, True)}, n={n})"


def sub_c(c, e):
    return c[c["event_signal_index"].isin(e["signal_index"])]


def lift_row(label, e, c, extra=None):
    L = lift(e, c, 2.0) if len(e) and len(c) else None
    row = {"group": label, "events": len(e), "controls": len(c), "p2R": rate(e, 2.0), "control_p2R": rate(c, 2.0),
           "lift_2R_pp": L["lift_pp"] if L else np.nan, "ci_lo_pp": L["ci_lo_pp"] if L else np.nan,
           "ci_hi_pp": L["ci_hi_pp"] if L else np.nan}
    row.update(extra or {})
    return row


def provenance(f, events):
    """Descriptive flags only (never used to exclude)."""
    man = pd.read_csv(MANIFEST)
    removed = pd.to_datetime(man.loc[man["timeframe"] == "M15", "timestamp"], format="%Y.%m.%d %H:%M:%S", utc=True)
    outages = [pd.Timestamp(a, tz="UTC") for a, _ in OUTAGES]
    tday = f["tday"].to_numpy()
    first_bar = f.groupby("tday")["time"].first()
    # weekly-open regime transitions: first session of a week whose NY open time differs from the previous week's
    wk = f[f["time"].diff().dt.total_seconds().div(3600).fillna(99) > 40]["time"]
    opens = wk.dt.tz_convert(NY).dt.strftime("%H:%M").to_numpy()
    transitions = [wk.iloc[i] for i in range(1, len(wk)) if opens[i] != opens[i - 1]]
    variant_days = [pd.Timestamp(d, tz="UTC") for d in BREAK_VARIANT_DAYS]
    rows = []
    for e in events.itertuples():
        lo = first_bar.get(tday[e.compression_index] - 20, first_bar.iloc[0])
        hi = f["time"].iloc[e.signal_index]
        race_end = f["time"].iloc[min(len(f) - 1, e.entry_index + 96)]
        rows.append({
            "lookback_has_repaired_location": bool(((removed >= lo) & (removed <= hi)).any()),
            "lookback_has_genuine_outage": any(lo <= o <= hi for o in outages),
            "race_near_session_regime_transition": any(f["time"].iloc[e.entry_index] - pd.Timedelta(days=1) <= x <= race_end
                                                       for x in transitions + variant_days)})
    return pd.DataFrame(rows)


def main(detect_only=False):
    raw = load()
    f = h3.h3_features(h1.features(raw))
    all_events, counts, acc = h3.detect(f)
    win = (all_events["signal_time"] >= REPL_START) & (all_events["signal_time"] < REPL_END_EXCL)
    events = all_events[win].reset_index(drop=True)
    counts["events_in_warmup_excluded"] = int((~win).sum())
    if detect_only:
        print(json.dumps(counts), "window events:", len(events), "long", int((events.direction == "long").sum()),
              "short", int((events.direction == "short").sum()))
        return
    gate = h3.h3_gate(raw, f, all_events)
    gate["result"] = "PASS" if all(v["pass"] for v in gate.values()) else "BLOCKED"
    (HERE / "gate.json").write_text(json.dumps(gate, indent=1, default=str) + "\n")
    if gate["result"] != "PASS":
        raise SystemExit("GATE BLOCKED")

    fw = [h1.forward(f, int(e.entry_index), 1 if e.direction == "long" else -1, e.entry, e.risk)
          for e in events.itertuples()]
    events = pd.concat([events, pd.DataFrame(fw), provenance(f, events)], axis=1)
    events["year"] = events["signal_time"].dt.year
    events["month"] = events["signal_time"].dt.strftime("%Y-%m")
    f_ctrl = f.copy()
    f_ctrl.loc[f_ctrl["time"] < REPL_START, "atr_pct"] = np.nan       # warm-up never in the control pool
    ctrl = h3.controls(f_ctrl, events, acc)
    events.to_csv(HERE / "events.csv", index=False)
    ctrl.to_csv(HERE / "controls.csv", index=False)

    lifts = {t: lift(events, ctrl, t) for t in TARGETS}
    pooled = lifts[2.0]
    years = []
    for y in YEARS:
        ey = events[events.year == y]
        cy = sub_c(ctrl, ey)
        years.append(lift_row(str(y), ey, cy, {
            "long": int((ey.direction == "long").sum()), "short": int((ey.direction == "short").sum()),
            **{f"p{int(t)}R": rate(ey, t) for t in TARGETS},
            "median_mfe32": ey["mfe_32"].median(), "median_mae32": ey["mae_32"].median()}))
    years = pd.DataFrame(years)
    years.to_csv(HERE / "yearly_results.csv", index=False)
    loyo = pd.DataFrame([lift_row(f"excluding {y}", events[events.year != y], sub_c(ctrl, events[events.year != y]))
                         for y in YEARS])
    loyo.to_csv(HERE / "leave_one_year_out.csv", index=False)
    sides = pd.DataFrame([lift_row(d.upper(), events[events.direction == d], ctrl[ctrl.direction == d],
                                   {"median_mfe32": events.loc[events.direction == d, "mfe_32"].median(),
                                    "median_mae32": events.loc[events.direction == d, "mae_32"].median()})
                          for d in ("long", "short")])
    sides.to_csv(HERE / "side_results.csv", index=False)
    months = []
    for m, em in events.groupby("month"):
        cm = sub_c(ctrl, em)
        a, b = rate(em, 2.0), rate(cm, 2.0)
        months.append({"month": m, "events": len(em), "p2R": a, "control_p2R": b, "lift_2R_pp": (a - b) * 100,
                       "median_mfe32": em["mfe_32"].median(), "median_mae32": em["mae_32"].median()})
    months = pd.DataFrame(months)
    months.to_csv(HERE / "monthly_results.csv", index=False)

    # preregistered two-gate decision
    lp, lo_ci = pooled["lift_pp"], pooled["ci_lo_pp"]
    long_l = float(sides.loc[sides.group == "LONG", "lift_2R_pp"].iloc[0])
    short_l = float(sides.loc[sides.group == "SHORT", "lift_2R_pp"].iloc[0])
    persistence = {"pooled_lift_gt_0": bool(lp > 0), "ci_lower_gt_0": bool(lo_ci > 0),
                   "long_and_short_non_negative": bool(long_l >= 0 and short_l >= 0),
                   "not_dependent_on_one_year_all_loyo_positive": bool((loyo["lift_2R_pp"] > 0).all())}
    gate_a = all(persistence.values())
    gate_b = bool(lp >= PRACTICAL_PP)
    if lp <= 0:
        cls = "FAILED TO REPLICATE"
    elif gate_a and gate_b:
        cls = "STRONG REPLICATION"
    elif gate_a:
        cls = "PERSISTENT BUT SUB-THRESHOLD"
    else:
        cls = "INCONCLUSIVE"
    decision = {"classification": cls, "gate_A_statistical_persistence": gate_a, "gate_A_criteria": persistence,
                "gate_B_practical_size_ge_5pp": gate_b, "pooled_lift_2R_pp": lp, "ci_lo_pp": lo_ci,
                "ci_hi_pp": pooled["ci_hi_pp"], "long_lift_pp": long_l, "short_lift_pp": short_l,
                "loyo_min_lift_pp": float(loyo["lift_2R_pp"].min())}
    (HERE / "decision_gate.json").write_text(json.dumps(decision, indent=1, default=float) + "\n")
    amb_e = int((events[[f"r_{t}" for t in h1.TARGETS]] == "ambiguous").any(axis=1).sum())
    amb_c = int((ctrl[[f"r_{t}" for t in h1.TARGETS]] == "ambiguous").any(axis=1).sum())
    summary = {"classification": cls, "gate": gate["result"], "counts": counts, "events": len(events),
               "controls": len(ctrl), "unique_control_bars": int(ctrl.signal_index.nunique()),
               "lifts": {str(t): {k: (list(v) if isinstance(v, tuple) else v) for k, v in L.items()} for t, L in lifts.items()},
               "ambiguous_events_any_target": amb_e, "ambiguous_controls_any_target": amb_c,
               "unresolved_2R": int(events["r_2.0"].isin(["none", "truncated"]).sum()),
               "provenance_flags": {c: int(events[c].sum()) for c in ("lookback_has_repaired_location",
                                    "lookback_has_genuine_outage", "race_near_session_regime_transition")},
               "median_mfe32": events.mfe_32.median(), "median_mae32": events.mae_32.median(),
               "control_median_mfe32": ctrl.mfe_32.median(), "control_median_mae32": ctrl.mae_32.median()}
    (HERE / "summary.json").write_text(json.dumps(summary, indent=1, default=float) + "\n")
    write_report(events, ctrl, counts, gate, lifts, years, loyo, sides, months, decision, summary)
    print(cls, json.dumps(decision, default=float))


def write_report(e, c, counts, gate, lifts, years, loyo, sides, months, decision, summary):
    ok = {True: "PASS", False: "FAIL"}
    exc = []
    for name, df in (("H3 events", e), ("controls", c)):
        for hz in h1.HORIZONS:
            exc.append(f"| {name} | {hz} | {fmt(df[f'mfe_{hz}'].median())} | {fmt(df[f'mfe_{hz}'].mean())} "
                       f"| {fmt(df[f'mae_{hz}'].median())} | {fmt(df[f'mae_{hz}'].mean())} |")
        exc.append(f"| {name} | until −1R | {fmt(df['mfe_to_stop'].median())} | {fmt(df['mfe_to_stop'].mean())} | — | — |")
    L2 = lifts[2.0]
    pos, zero, neg = int((months.lift_2R_pp > 0).sum()), int((months.lift_2R_pp == 0).sum()), int((months.lift_2R_pp < 0).sum())
    nan_m = int(months.lift_2R_pp.isna().sum())
    pf = summary["provenance_flags"]
    report = f"""# Gold V1 — H3 second independent replication (repaired 2017-06 → 2021-08)

- **Data:** the approved repaired Exness XAUUSDm M15 history (`repaired/xauusd_XAUUSDm_M15_repaired.csv`), warm-up
  from 2017-05-01.
- **Event window:** events whose acceptance bar is in [2017-06-01 00:00, 2021-08-31 22:00) UTC.
- **End of data:** forward data stops at 2021-08-31 20:45, before the sealed holdout. Races reaching it are
  `truncated` and excluded from P(...).
- **Rules:** the frozen H3 rules, forward race, controls and bootstrap, unchanged. Preregistered in
  [H3_REPLICATION_2_PREREGISTRATION.md](H3_REPLICATION_2_PREREGISTRATION.md) before any outcome.
- **Gate:** {gate['result']}.
- **Costs:** spread is unavailable for most of this era, so this is a structural-edge test only.

## Counts

- **Replication events:** **{len(e)}** ({(e.direction == 'long').sum()} long / {(e.direction == 'short').sum()} short).
  Warm-up events excluded: {counts['events_in_warmup_excluded']}.
- **Controls:** {len(c)} draws, {c.signal_index.nunique()} unique bars.
- **Risk:** median {e.risk_atr.median():.2f} ATR (IQR {e.risk_atr.quantile(.25):.2f}–{e.risk_atr.quantile(.75):.2f}), {e.risk.median():.2f} USD.
- **AMBIGUOUS_INTRABAR** (any target): {summary['ambiguous_events_any_target']} events, {summary['ambiguous_controls_any_target']} controls. Excluded from
  P(...) for the affected target.
- **Unresolved at +2R** (`none` or `truncated`): {summary['unresolved_2R']}.
- **Provenance flags** (descriptive; nothing excluded):
  - 20-session lookback contains a repaired pseudo-session location: {pf['lookback_has_repaired_location']};
  - lookback contains a genuine outage: {pf['lookback_has_genuine_outage']};
  - race within a day of a weekly-open regime transition or a break-variant day: {pf['race_near_session_regime_transition']}.

## Primary result (standalone)

P(+2R before −1R): H3 **{fmt(L2['event_p'], True)}** vs controls **{fmt(L2['control_p'], True)}** →
lift **{L2['lift_pp']:+.2f} pp**, 95% CI **{L2['ci_lo_pp']:+.2f} … {L2['ci_hi_pp']:+.2f}** (event-clustered bootstrap,
5,000 samples, seed 20260603).

| target | H3 | controls | lift (pp) | 95% CI |
|---|---|---|---|---|
""" + "\n".join(f"| +{t:g}R | {wtext(e, t)} | {wtext(c, t)} | {L['lift_pp']:+.1f} | {L['ci_lo_pp']:+.1f} … {L['ci_hi_pp']:+.1f} |"
                  for t, L in lifts.items()) + f"""

## Decision gates (preregistered)

| gate | criterion | result |
|---|---|---|
| A. statistical persistence | pooled +2R lift > 0 | {ok[decision['gate_A_criteria']['pooled_lift_gt_0']]} ({decision['pooled_lift_2R_pp']:+.2f} pp) |
| | 95% CI lower bound > 0 | {ok[decision['gate_A_criteria']['ci_lower_gt_0']]} ({decision['ci_lo_pp']:+.2f} pp) |
| | long and short point estimates ≥ 0 | {ok[decision['gate_A_criteria']['long_and_short_non_negative']]} (long {decision['long_lift_pp']:+.1f}, short {decision['short_lift_pp']:+.1f}) |
| | not dependent on one year: every leave-one-year-out lift > 0 | {ok[decision['gate_A_criteria']['not_dependent_on_one_year_all_loyo_positive']]} (minimum {decision['loyo_min_lift_pp']:+.1f} pp) |
| **A overall** | | **{ok[decision['gate_A_statistical_persistence']]}** |
| **B. practical size** | pooled +2R lift ≥ +5.0 pp | **{ok[decision['gate_B_practical_size_ge_5pp']]}** |

## Classification: **{decision['classification']}**

## Year by year

| year | events | long / short | +1R | +2R | +3R | +4R | control +2R | +2R lift (pp) | 95% CI | MFE32 med | MAE32 med |
|---|---|---|---|---|---|---|---|---|---|---|---|
""" + "\n".join(f"| {r.group} | {r.events} | {r.long} / {r.short} | {fmt(r.p1R, True)} | {fmt(r.p2R, True)} | {fmt(r.p3R, True)} "
                  f"| {fmt(r.p4R, True)} | {fmt(r.control_p2R, True)} | {r.lift_2R_pp:+.1f} | {r.ci_lo_pp:+.1f} … {r.ci_hi_pp:+.1f} "
                  f"| {fmt(r.median_mfe32)} | {fmt(r.median_mae32)} |" for r in years.itertuples()) + """

## Leave one year out (descriptive; no year is excluded from the primary result)

| sample | events | H3 +2R | control +2R | lift (pp) | 95% CI |
|---|---|---|---|---|---|
""" + "\n".join(f"| {r.group} | {r.events} | {fmt(r.p2R, True)} | {fmt(r.control_p2R, True)} | {r.lift_2R_pp:+.1f} "
                  f"| {r.ci_lo_pp:+.1f} … {r.ci_hi_pp:+.1f} |" for r in loyo.itertuples()) + """

## Long / short

| side | events | H3 +2R | control +2R | lift (pp) | 95% CI | MFE32 med | MAE32 med |
|---|---|---|---|---|---|---|---|
""" + "\n".join(f"| {r.group} | {r.events} | {fmt(r.p2R, True)} | {fmt(r.control_p2R, True)} | {r.lift_2R_pp:+.1f} "
                  f"| {r.ci_lo_pp:+.1f} … {r.ci_hi_pp:+.1f} | {fmt(r.median_mfe32)} | {fmt(r.median_mae32)} |" for r in sides.itertuples()) + f"""

## MFE / MAE (R)

| sample | bars | MFE median | MFE mean | MAE median | MAE mean |
|---|---|---|---|---|---|
""" + "\n".join(exc) + f"""

## Month by month (descriptive)

Months with lift > 0: **{pos}**, = 0: **{zero}**, < 0: **{neg}**, undefined: {nan_m}, out of {len(months)}.

| month | events | H3 +2R | control +2R | lift (pp) | MFE32 med | MAE32 med |
|---|---|---|---|---|---|---|
""" + "\n".join(f"| {r.month} | {r.events} | {fmt(r.p2R, True)} | {fmt(r.control_p2R, True)} | {fmt(r.lift_2R_pp, d=1)} "
                  f"| {fmt(r.median_mfe32)} | {fmt(r.median_mae32)} |" for r in months.itertuples()) + "\n"
    (HERE / "report.md").write_text(report)


if __name__ == "__main__":
    main(detect_only="--detect-only" in sys.argv)
