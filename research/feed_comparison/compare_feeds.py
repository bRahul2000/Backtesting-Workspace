"""Binance Futures vs Exness MT5 feed comparison lab (research only).

    ./venv/bin/python -m research.feed_comparison.compare_feeds [--refresh] [--pairs XAU BTC]
                                                                [--timeframes 15m 30m 1h] [--no-strategies]

Writes research/feed_comparison/output/: summary.json, REPORT.md,
<PAIR>_<TF>.csv (matched candles) and outliers.csv. Thresholds and metric
definitions were fixed beforehand in thresholds.py.
"""
from __future__ import annotations

import argparse
import json
import math
import time

import numpy as np
import pandas as pd

from ui.tradingview_mode.component.protocol import price_precision
from ui.tradingview_mode.timeframes import timeframe_seconds

from . import metrics as M
from . import thresholds as TH
from .data import OUTPUT, PAIRS, TIMEFRAMES, feeds

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _warm_times(frame: pd.DataFrame) -> np.ndarray:
    return M.epoch_seconds(frame["timestamp"].iloc[TH.WARMUP_BARS:])


def _rolling_deviation(diff: pd.Series, seconds: int) -> pd.Series:
    window = max(3, int(86400 // seconds)) | 1
    return diff - diff.rolling(window, center=True, min_periods=window // 2).median()


def analyse(pair: str, timeframe: str, binance: pd.DataFrame, exness: pd.DataFrame, *, binance_digits: int,
            exness_digits: int, with_view: bool = True) -> tuple[dict, pd.DataFrame, list[dict]]:
    """Every comparison for one pair/timeframe. Returns (summary, matched table, outliers)."""
    seconds = timeframe_seconds(timeframe)
    binance = M.validate_feed(binance, seconds, f"Binance {pair} {timeframe}")
    exness = M.validate_feed(exness, seconds, f"Exness {pair} {timeframe}")
    ib, ie = M.with_indicators(binance), M.with_indicators(exness)
    matched = M.match(binance, exness, seconds)
    m = matched.frame
    ts = m["timestamp"]
    matched_times = M.epoch_seconds(ts)
    warm = np.intersect1d(np.intersect1d(matched_times, _warm_times(ib)), _warm_times(ie))
    warm_mask = np.isin(matched_times, warm)
    mw = m[warm_mask].reset_index(drop=True)
    tsw = mw["timestamp"]

    direction, db, de = M.direction_agreement(m, binance_digits, exness_digits)
    atr_e = M.aligned(ie, "atr", ts)

    events_b, events_e = M.proxy_events(ib), M.proxy_events(ie)
    event_results = {name: M.match_events(M.event_times(ib, events_b[name], warm), M.event_times(ie, events_e[name], warm),
                                           seconds) for name in events_b}
    public = lambda r: {k: v for k, v in r.items() if not k.startswith("_")}  # noqa: E731

    breakout = {}
    for basis in ("close", "wick"):
        for n in TH.BREAKOUT_NS:
            up, down = event_results[f"breakout_{basis}_{n}_up"], event_results[f"breakout_{basis}_{n}_down"]
            breakout[f"{basis}_{n}"] = {"up": public(up), "down": public(down), "pooled": M.pooled(up, down)}
    swings = {}
    for window in TH.SWING_WINDOWS:
        high, low = event_results[f"swing_{window}_high"], event_results[f"swing_{window}_low"]
        swings[str(window)] = {"high": public(high), "low": public(low), "pooled": M.pooled(high, low)}
    proxies = {name: public(r) for name, r in event_results.items() if name[:2] in {f"{c}_" for c in "ABCDEFG"}}
    ema_cross = M.pooled(event_results["A_close_cross_above_ema20"], event_results["B_close_cross_below_ema20"])

    headline_breakout = breakout[f"{TH.HEADLINE['breakout_basis']}_{TH.HEADLINE['breakout_n']}"]["pooled"]
    headline_swing = swings[str(TH.HEADLINE["swing_window"])]["pooled"]

    # Where headline breakouts disagree, by UTC hour and weekday.
    up, down = event_results["breakout_close_20_up"], event_results["breakout_close_20_down"]
    only = set(up["_binance_only_times"] + up["_exness_only_times"] + down["_binance_only_times"] + down["_exness_only_times"])
    fired = set(M.event_times(ib, events_b["breakout_close_20_up"] | events_b["breakout_close_20_down"], warm)) | \
        set(M.event_times(ie, events_e["breakout_close_20_up"] | events_e["breakout_close_20_down"], warm))
    miss = np.isin(matched_times, list(only))
    any_event = np.isin(matched_times, list(fired))
    hourly = M.grouped_summary(m, db, de, miss, any_event, ts.dt.hour)
    weekday = M.grouped_summary(m, db, de, miss, any_event, ts.dt.weekday)
    for row in weekday:
        row["key"] = WEEKDAYS[row["key"]]
    edges = M.session_edges(m, seconds)
    session = {}
    for name, mask in edges.items():
        # The first/last hour around a market pause, and everything else.
        span = max(1, int(3600 // seconds))
        grown = mask.copy()
        for k in range(1, span):
            grown |= mask.shift(k if name == "reopen_candles" else -k, fill_value=False)
        rows = M.grouped_summary(m, db, de, miss, any_event, grown.map({True: "near_pause", False: "normal"}))
        session[name] = {"events": int(mask.sum()), "candles_counted": int(grown.sum()), "groups": rows}

    # Outliers (basis-adjusted: deviation from the surrounding day's median difference).
    rows: list[dict] = []
    for field in ("close", "high", "low"):
        deviation = _rolling_deviation(m[f"b_{field}"] - m[f"e_{field}"], seconds)
        rows += M.outliers(m, deviation, f"largest_{field}_difference")
    opposite = pd.Series(np.where(db * de == -1, np.minimum((m["b_close"] - m["b_open"]).abs() / m["b_close"],
                                                            (m["e_close"] - m["e_open"]).abs() / m["e_close"]) * 100, np.nan))
    rows += M.outliers(m, opposite, "opposite_direction_min_body_pct")
    index_of = {t: i for i, t in enumerate(matched_times)}
    close_dev = _rolling_deviation(m["b_close"] - m["e_close"], seconds)
    for who in ("binance", "exness"):
        times = up[f"_{who}_only_times"] + down[f"_{who}_only_times"]
        score = pd.Series(np.nan, index=m.index)
        positions = [index_of[t] for t in times]
        score.loc[positions] = close_dev.loc[positions].fillna(0.0)   # ranked by the close difference there
        rows += M.outliers(m, score, f"{who}_only_breakout_close_20")
    for row in rows:
        row.update({"pair": pair, "timeframe": timeframe})

    summary = {
        "pair": pair, "timeframe": timeframe, "coverage": matched.coverage,
        "comparison_candles_after_warmup": int(len(mw)),
        "price_offsets": M.price_offsets(m),
        "return_correlation": M.return_correlations(m, seconds),
        "time_alignment": M.lag_alignment(m, seconds),
        "direction": direction,
        "shape": M.shape_similarity(m),
        "levels": M.level_agreement(m, atr_e),
        "atr14": M.atr_comparison(ib, ie, tsw),
        "ema": M.ema_comparison(ib, ie, tsw),
        "vwap": M.vwap_comparison(ib, ie, tsw),
        "breakouts": breakout, "swings": swings, "ema20_cross": ema_cross, "signal_proxies": proxies,
        "hourly": hourly, "weekday": weekday, "session_edges": session,
        "headline": {
            "direction_agreement_pct": direction["same_pct"],
            "breakout_close20_same_bar_pct": headline_breakout["agreement_same_bar_pct"],
            "breakout_close20_pm1_pct": headline_breakout["agreement_tolerance_pct"],
            "ema20_cross_same_bar_pct": ema_cross["agreement_same_bar_pct"],
            "ema20_cross_pm1_pct": ema_cross["agreement_tolerance_pct"],
            "swing3_same_bar_pct": headline_swing["agreement_same_bar_pct"],
            "swing3_pm1_pct": headline_swing["agreement_tolerance_pct"],
            "vwap_state_agreement_pct": M.vwap_comparison(ib, ie, tsw)["state_agreement_pct"],
            "median_close_diff": M.distribution(m["b_close"] - m["e_close"])["median"],
            "median_close_diff_pct": M.distribution((m["b_close"] - m["e_close"]) / m["e_close"] * 100)["median"],
            "return_corr_1bar": M.return_correlations(m, seconds, (1,))["1_bar"]["pearson"],
        },
    }
    h = summary["headline"]
    summary["labels"] = {
        "direction": TH.label("direction", h["direction_agreement_pct"]),
        "breakout": TH.label("breakout", h["breakout_close20_pm1_pct"]),
        "ema_cross": TH.label("ema_cross", h["ema20_cross_pm1_pct"]),
        "swing": TH.label("swing", h["swing3_pm1_pct"]),
        "signal_proxies": {name: TH.label("signal_proxy", r["agreement_tolerance_pct"]) for name, r in proxies.items()},
    }

    if with_view:
        summary["session_aligned_view"] = session_aligned_view(pair, timeframe, binance, exness,
                                                               binance_digits=binance_digits, exness_digits=exness_digits)
    table = pd.DataFrame({"timestamp": ts, **{f"binance_{f}": m[f"b_{f}"] for f in ("open", "high", "low", "close", "volume")},
                          **{f"exness_{f}": m[f"e_{f}"] for f in ("open", "high", "low", "close", "volume")}})
    table["close_diff"] = m["b_close"] - m["e_close"]
    table["close_diff_pct"] = table["close_diff"] / m["e_close"] * 100
    table["binance_direction"], table["exness_direction"] = db, de
    for column in ("atr", "ema20", "vwap"):
        table[f"binance_{column}"] = M.aligned(ib, column, ts)
        table[f"exness_{column}"] = M.aligned(ie, column, ts)
    table["after_warmup"] = warm_mask
    table["breakout20_disagreement"] = miss
    return summary, table, rows


def session_aligned_view(pair: str, timeframe: str, binance: pd.DataFrame, exness: pd.DataFrame, **digits) -> dict:
    """Diagnostic second view: Binance indicators/events computed only on candles
    where Exness also has a candle (Binance's weekend/break candles removed), so
    closed-market effects are separated from same-hours price disagreement.
    The headline (as-traded) view is unchanged by this."""
    aligned_binance = binance[binance["timestamp"].isin(set(exness["timestamp"]))].reset_index(drop=True)
    view, _, _ = analyse(pair, timeframe, aligned_binance, exness, with_view=False, **digits)
    return {"description": session_aligned_view.__doc__.split("\n\n")[0].replace("\n", " "),
            "headline": view["headline"], "labels": view["labels"], "ema20_cross": view["ema20_cross"],
            "breakouts": {k: v["pooled"] for k, v in view["breakouts"].items()},
            "swings": {k: v["pooled"] for k, v in view["swings"].items()}, "signal_proxies": view["signal_proxies"]}


def jsonable(value):
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not math.isfinite(float(value)) else round(float(value), 6)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pairs", nargs="+", default=["XAU", "BTC"], choices=list(PAIRS))
    parser.add_argument("--timeframes", nargs="+", default=list(TIMEFRAMES), choices=list(TIMEFRAMES))
    parser.add_argument("--refresh", action="store_true", help="re-download Binance history")
    parser.add_argument("--no-strategies", action="store_true", help="skip the existing-strategy signal parity run")
    args = parser.parse_args(argv)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    started = time.time()
    summary = {"generated_at_utc": pd.Timestamp.now(tz="UTC").isoformat(), "thresholds": TH.THRESHOLDS,
               "headline_settings": TH.HEADLINE, "warmup_bars": TH.WARMUP_BARS, "results": {}, "sources": {}}
    outlier_rows: list[dict] = []
    for pair in args.pairs:
        for timeframe in args.timeframes:
            t0 = time.time()
            binance, meta, exness = feeds(pair, timeframe, refresh=args.refresh)
            exness_digits = price_precision(exness.frame["close"])
            result, table, rows = analyse(pair, timeframe, binance, exness.frame,
                                          binance_digits=PAIRS[pair]["binance_digits"], exness_digits=exness_digits)
            summary["results"][f"{pair}_{timeframe}"] = result
            summary["sources"][f"{pair}_{timeframe}"] = {
                "binance": {**meta, "symbol": PAIRS[pair]["binance_label"], "digits": PAIRS[pair]["binance_digits"]},
                "exness": {"dataset_key": exness.dataset_key, "native": exness.native, "resolution": exness.source_label,
                           "symbol": PAIRS[pair]["exness_label"], "digits": exness_digits,
                           "bars": int(len(exness.frame)), "first": exness.frame["timestamp"].iloc[0].isoformat(),
                           "last": exness.frame["timestamp"].iloc[-1].isoformat()},
            }
            table.to_csv(OUTPUT / f"{pair}_{timeframe}.csv", index=False)
            outlier_rows += rows
            print(f"{pair} {timeframe}: {result['coverage']['matched_bars']:,} matched candles, "
                  f"direction {result['headline']['direction_agreement_pct']}%, "
                  f"breakout20 ±1 {result['headline']['breakout_close20_pm1_pct']}% ({time.time() - t0:.0f}s)", flush=True)
    pd.DataFrame(outlier_rows).to_csv(OUTPUT / "outliers.csv", index=False)
    if not args.no_strategies and "BTC" in args.pairs and "15m" in args.timeframes:
        from .strategy_parity import strategy_parity

        summary["strategy_parity"] = strategy_parity()
    else:
        summary["strategy_parity"] = {"status": "SKIPPED", "reason": "not requested in this run"}
    summary["runtime_s"] = round(time.time() - started, 1)
    (OUTPUT / "summary.json").write_text(json.dumps(jsonable(summary), indent=1))
    from .report import write_report

    write_report(OUTPUT / "summary.json", OUTPUT / "REPORT.md")
    print(f"Wrote {OUTPUT}/summary.json, REPORT.md, per-timeframe CSVs and outliers.csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
