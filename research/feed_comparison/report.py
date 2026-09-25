"""Render summary.json as REPORT.md (metrics only; conclusions live in FINDINGS.md)."""
from __future__ import annotations

import json
from pathlib import Path


ORDER = ("XAU", "BTC")
TFS = ("15m", "30m", "1h")


def _f(value, digits=2, suffix=""):
    if value is None:
        return "—"
    if isinstance(value, (int,)) and not isinstance(value, bool):
        return f"{value:,}{suffix}"
    return f"{value:,.{digits}f}{suffix}"


def _pct(value):
    return _f(value, 2, "%")


def _table(header, rows):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def write_report(summary_path: Path, out_path: Path) -> None:
    s = json.loads(Path(summary_path).read_text())
    r, src = s["results"], s["sources"]
    lines = ["# Binance Futures vs Exness MT5 — feed comparison", "",
             f"Generated {s['generated_at_utc']} (runtime {s.get('runtime_s')} s). Research output only.", ""]

    lines += ["## Method (fixed before the run)", "",
              "- Candles are compared only where both feeds have the identical UTC timestamp; nothing is filled or interpolated.",
              "- Indicators and events are computed on each feed's own candles (strategy Pine EMA/ATR; chart VWAP with daily UTC reset).",
              f"- Indicator/event comparisons skip the first {s['warmup_bars']} candles of each feed (warm-up).",
              "- Event agreement = matched / (matched + Binance-only + Exness-only), one-to-one matching, same bar or ±1 bar.",
              f"- Headline settings: {s['headline_settings']}.",
              "- Labels (descriptive only): " + "; ".join(
                  f"{k}: " + ", ".join(f"≥{lo:g}% {name}" for lo, name in bands if lo > 0) + ", below: weak"
                  for k, bands in s["thresholds"].items()), ""]

    lines += ["## Suitability matrix", ""]
    rows = []
    for pair in ORDER:
        for tf in TFS:
            key = f"{pair}_{tf}"
            if key not in r:
                continue
            h, lab = r[key]["headline"], r[key]["labels"]
            rows.append([f"**{'Gold' if pair == 'XAU' else 'BTC'} {tf}**", _f(r[key]["coverage"]["matched_bars"], 0),
                         f"{_pct(h['direction_agreement_pct'])} ({lab['direction']})",
                         f"{_pct(h['breakout_close20_same_bar_pct'])} / {_pct(h['breakout_close20_pm1_pct'])} ({lab['breakout']})",
                         f"{_pct(h['ema20_cross_same_bar_pct'])} / {_pct(h['ema20_cross_pm1_pct'])} ({lab['ema_cross']})",
                         f"{_pct(h['swing3_same_bar_pct'])} / {_pct(h['swing3_pm1_pct'])} ({lab['swing']})",
                         _pct(h["vwap_state_agreement_pct"]),
                         f"{_f(h['median_close_diff'])} ({_f(h['median_close_diff_pct'], 3, '%')})",
                         _f(h["return_corr_1bar"], 4)])
    lines += [_table(["pair / tf", "matched", "direction", "breakout20 same / ±1", "EMA20 cross same / ±1",
                      "swing(3) same / ±1", "VWAP state", "median close diff (B−E)", "1-bar return corr"], rows), ""]
    view_rows = []
    for pair in ORDER:
        for tf in TFS:
            key = f"{pair}_{tf}"
            if key in r and "session_aligned_view" in r[key]:
                v = r[key]["session_aligned_view"]
                h, lab = v["headline"], v["labels"]
                view_rows.append([f"{'Gold' if pair == 'XAU' else 'BTC'} {tf}",
                                  f"{_pct(h['breakout_close20_same_bar_pct'])} / {_pct(h['breakout_close20_pm1_pct'])} ({lab['breakout']})",
                                  f"{_pct(h['ema20_cross_same_bar_pct'])} / {_pct(h['ema20_cross_pm1_pct'])} ({lab['ema_cross']})",
                                  f"{_pct(h['swing3_same_bar_pct'])} / {_pct(h['swing3_pm1_pct'])} ({lab['swing']})",
                                  _pct(h["vwap_state_agreement_pct"])])
    if view_rows:
        lines += ["**Diagnostic: session-aligned view** — Binance indicators/events computed only on candles where Exness "
                  "also trades (weekend/break candles removed). Not the headline: an algo on Binance would see those candles.", "",
                  _table(["pair / tf", "breakout20 same / ±1", "EMA20 cross same / ±1", "swing(3) same / ±1", "VWAP state"], view_rows), ""]

    for pair in ORDER:
        for tf in TFS:
            key = f"{pair}_{tf}"
            if key not in r:
                continue
            x, so = r[key], src[key]
            cov = x["coverage"]
            name = "Gold (XAUUSDT Perp vs XAUUSDm)" if pair == "XAU" else "BTC (BTCUSDT Perp vs BTCUSDm)"
            lines += [f"## {name} — {tf}", "",
                      f"- Overlap {cov['overlap_start']} → {cov['overlap_end']}; Binance {cov['binance_bars']:,} candles, "
                      f"Exness {cov['exness_bars']:,}, matched {cov['matched_bars']:,} (unmatched Binance {cov['unmatched_binance']:,}, "
                      f"unmatched Exness {cov['unmatched_exness']:,}); coverage {_pct(cov['coverage_of_binance_pct'])} of Binance, "
                      f"{_pct(cov['coverage_of_exness_pct'])} of Exness. {x['comparison_candles_after_warmup']:,} candles after warm-up.",
                      f"- Exness source: {so['exness']['dataset_key']} ({so['exness']['resolution']}); Binance: {so['binance']['symbol']}, "
                      f"{so['binance']['received_bars']:,} candles {so['binance']['first']} → {so['binance']['last']}"
                      + (" (start of Binance history reached)" if so["binance"]["history_start_reached"] else "") + ".", ""]
            off = x["price_offsets"]
            lines += ["**Price offset (Binance − Exness)**", "",
                      _table(["field", "mean", "median", "std", "p5", "p95", "p99", "min", "max", "median %", "p95 %"],
                             [[f, _f(off[f]["absolute"]["mean"]), _f(off[f]["absolute"]["median"]), _f(off[f]["absolute"]["std"]),
                               _f(off[f]["absolute"]["p5"]), _f(off[f]["absolute"]["p95"]), _f(off[f]["absolute"]["p99"]),
                               _f(off[f]["absolute"]["min"]), _f(off[f]["absolute"]["max"]),
                               _f(off[f]["relative_pct"]["median"], 4, "%"), _f(off[f]["relative_pct"]["p95"], 4, "%")]
                              for f in ("open", "high", "low", "close")]), ""]
            al = x["time_alignment"]
            lines += [f"**Time alignment**: 1-bar return correlation peaks at lag {al['peak_lag_bars']} bars "
                      f"({', '.join(f'{k}: {_f(v, 3)}' for k, v in al['correlation_by_lag_bars'].items())}).", ""]
            rc = x["return_correlation"]
            lines += ["**Returns**: " + "; ".join(f"{k}: Pearson {_f(v['pearson'], 4)}, Spearman {_f(v['spearman'], 4)}, "
                                                  f"same sign {_pct(v['sign_agreement_pct'])} (n={v['pairs']:,})" for k, v in rc.items()), ""]
            d = x["direction"]
            c = d["confusion"]
            lines += [f"**Direction**: same {_pct(d['same_pct'])}, opposite {_pct(d['opposite_pct'])}, flat disagreement "
                      f"{_pct(d['flat_disagreement_pct'])}, same excluding flats {_pct(d['same_pct_excluding_flats'])}. "
                      f"Bull/Bull {c['binance_bull__exness_bull']:,}, Bull/Bear {c['binance_bull__exness_bear']:,}, "
                      f"Bear/Bull {c['binance_bear__exness_bull']:,}, Bear/Bear {c['binance_bear__exness_bear']:,}.", ""]
            sh = x["shape"]
            lines += [f"**Shape** (% of range, |B−E|): body median {_f(sh['body_pct_abs_diff']['median'])} p95 {_f(sh['body_pct_abs_diff']['p95'])}; "
                      f"upper wick median {_f(sh['upper_pct_abs_diff']['median'])} p95 {_f(sh['upper_pct_abs_diff']['p95'])}; "
                      f"lower wick median {_f(sh['lower_pct_abs_diff']['median'])} p95 {_f(sh['lower_pct_abs_diff']['p95'])}; "
                      f"range ratio B/E median {_f(sh['range_ratio_binance_over_exness']['median'], 3)} "
                      f"(p5 {_f(sh['range_ratio_binance_over_exness']['p5'], 3)}, p95 {_f(sh['range_ratio_binance_over_exness']['p95'], 3)}), "
                      f"range correlation {_f(sh['range_correlation'], 4)}.", ""]
            lv = x["levels"]
            lines += ["**Levels** (|B−E|)", "", _table(["", "abs median", "abs p95", "% median", "% p95", "ATR median", "ATR p95"],
                      [[k, _f(v["abs_median"]), _f(v["abs_p95"]), _f(v["pct_median"], 4), _f(v["pct_p95"], 4), _f(v["atr_median"], 3), _f(v["atr_p95"], 3)]
                       for k, v in lv.items()]), ""]
            a = x["atr14"]
            lines += [f"**ATR(14)**: correlation {_f(a['correlation'], 4)}, median diff {_f(a['median_pct_diff'], 2, '%')}, "
                      f"median |diff| {_f(a['median_abs_pct_diff'], 2, '%')}, p95 |diff| {_f(a['p95_abs_pct_diff'], 2, '%')}.", ""]
            lines += ["**EMA**", "", _table(["", "level diff median (ATR)", "|close−EMA| diff median / p95 (ATR)", "slope agreement", "close side agreement"],
                      [[k, _f(v["level_diff_atr"]["median"], 3), f"{_f(v['close_distance_diff_atr']['abs_median'], 3)} / {_f(v['close_distance_diff_atr']['abs_p95'], 3)}",
                        _pct(v["slope_direction_agreement_pct"]), _pct(v["close_side_agreement_pct"])] for k, v in x["ema"].items()]), ""]
            v = x["vwap"]
            lines += [f"**VWAP** — {v['volume_semantics']} Price-vs-VWAP state agreement {_pct(v['state_agreement_pct'])}; "
                      f"distance-from-VWAP difference median {_f(v['distance_diff_atr']['abs_median'], 3)} ATR, p95 {_f(v['distance_diff_atr']['abs_p95'], 3)} ATR.", ""]
            ev_rows = []
            for basis_n, b in x["breakouts"].items():
                p = b["pooled"]
                ev_rows.append([f"breakout {basis_n}", p["binance_events"], p["exness_events"], _pct(p["agreement_same_bar_pct"]),
                                _pct(p["agreement_tolerance_pct"]), p["binance_only"], p["exness_only"]])
            for w, b in x["swings"].items():
                p = b["pooled"]
                ev_rows.append([f"swing {w}", p["binance_events"], p["exness_events"], _pct(p["agreement_same_bar_pct"]),
                                _pct(p["agreement_tolerance_pct"]), p["binance_only"], p["exness_only"]])
            for name, p in x["signal_proxies"].items():
                ev_rows.append([name, p["binance_events"], p["exness_events"], _pct(p["agreement_same_bar_pct"]),
                                _pct(p["agreement_tolerance_pct"]), p["binance_only"], p["exness_only"]])
            lines += ["**Events**", "", _table(["event", "Binance", "Exness", "same bar", "±1 bar", "Binance-only", "Exness-only"], ev_rows), ""]
            worst = sorted((h for h in x["hourly"] if h["breakout_events"]), key=lambda h: -(h["breakout_disagreement_pct"] or 0))[:5]
            lines += ["**UTC hours with the most breakout disagreement**: " + "; ".join(
                f"{h['key']:02d}:00 {_pct(h['breakout_disagreement_pct'])} of {h['breakout_events']} (direction {_pct(h['direction_agreement_pct'])})"
                for h in worst), ""]
            lines += ["**Weekday**", "", _table(["day", "matched", "direction", "median |close diff|", "breakout disagreement"],
                      [[w["key"], w["matched_bars"], _pct(w["direction_agreement_pct"]), _f(w["median_abs_close_diff"]),
                        f"{_pct(w['breakout_disagreement_pct'])} of {w['breakout_events']}"] for w in x["weekday"]]), ""]
            for edge, info in x["session_edges"].items():
                groups = {g["key"]: g for g in info["groups"]}
                if "near_pause" in groups:
                    g, n = groups["near_pause"], groups.get("normal", {})
                    lines.append(f"- {edge.replace('_', ' ')} (first/last hour around {info['events']} market pauses ≥ 12 h): "
                                 f"direction {_pct(g['direction_agreement_pct'])} vs {_pct(n.get('direction_agreement_pct'))} otherwise; "
                                 f"median |close diff| {_f(g['median_abs_close_diff'])} vs {_f(n.get('median_abs_close_diff'))}; "
                                 f"breakout disagreement {_pct(g['breakout_disagreement_pct'])} vs {_pct(n.get('breakout_disagreement_pct'))}.")
            lines.append("")

    sp = s.get("strategy_parity", {})
    lines += ["## Existing-strategy signal parity (BTC 15m)", "", f"Status: **{sp.get('status')}**. {sp.get('note', sp.get('reason', ''))}", ""]
    if sp.get("strategies"):
        lines += [f"Window {sp['window']['start']} → {sp['window']['end']}.", "",
                  _table(["strategy", "Binance trades", "Exness trades", "same bar", "±1 bar", "Binance-only", "Exness-only"],
                         [[k, v.get("binance_trades", "—"), v.get("exness_trades", "—"),
                           _pct(v.get("pooled", {}).get("agreement_same_bar_pct")), _pct(v.get("pooled", {}).get("agreement_tolerance_pct")),
                           v.get("pooled", {}).get("binance_only", v.get("error", "—")), v.get("pooled", {}).get("exness_only", "—")]
                          for k, v in sp["strategies"].items()]), ""]
    lines += ["Outlier candles: `outliers.csv`. Matched candles per pair/timeframe: `<PAIR>_<TF>.csv`.", ""]
    Path(out_path).write_text("\n".join(lines))
