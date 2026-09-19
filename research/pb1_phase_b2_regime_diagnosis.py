"""PB1 Phase B.2 — DEVELOPMENT regime failure diagnosis.

Diagnoses *why* the three Phase B.1 stable-region representatives lose money in
2022 while making money in 2023. This is not an optimization phase: the three
parameter sets are fixed, no grid is run, PB1's defaults and execution logic are
untouched, and every measure is diagnostic only — nothing here filters or
changes a trading decision.

DEVELOPMENT (2021-01-01 .. 2023-12-31) only. No VALIDATION or
FORWARD_VALIDATION data is opened, loaded, queried, or backtested.

Method: for each representative, replay the DEVELOPMENT backtest, join every
closed trade to (a) the setup geometry PB1 itself logged at the confirmation
candle and (b) independently reconstructed signal-time market-regime features
(see research/pb1_phase_b2_regime_features.py), then test which — if any — of
those features separates winners from losers *consistently across all three
years and all three representatives*.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from research.pb1_phase_b2_regime_features import (
    ATR_EXPANSION_FORMULA, ATR_PERCENTILE_FORMULA, DATA, DEVELOPMENT_END,
    DEVELOPMENT_START, DIRECTIONAL_EFFICIENCY_FORMULA, REVERSAL_FREQUENCY_FORMULA,
    build_trade_frame, load_development_data, market_features,
)

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "pb1" / "phase_b2_report.json"
TRADES = ROOT / "reports" / "pb1" / "phase_b2_trades.csv"

STRATEGY_ID = "BTC_PB1_SHALLOW_PULLBACK_V1"

# Section 1: the three Phase B.1 representatives, fixed. No new combinations.
REPRESENTATIVES: dict[str, dict[str, float]] = {
    "R1": {"impulse_minimum_range_atr": 1.8, "pullback_minimum_retracement_percent": 0.20,
           "pullback_maximum_retracement_percent": 0.35, "confirmation_minimum_body_percent": 0.50},
    "R2": {"impulse_minimum_range_atr": 1.8, "pullback_minimum_retracement_percent": 0.25,
           "pullback_maximum_retracement_percent": 0.35, "confirmation_minimum_body_percent": 0.40},
    "R3": {"impulse_minimum_range_atr": 1.8, "pullback_minimum_retracement_percent": 0.20,
           "pullback_maximum_retracement_percent": 0.35, "confirmation_minimum_body_percent": 0.60},
}

# Phase B.1 reported these (engine convention: a trade belongs to its entry year).
PHASE_B1_TRADES = {"R1": 414, "R2": 321, "R3": 337}

REGIME_FEATURES = ("h1_separation_atr", "aligned_fast_slope_atr", "aligned_slow_slope_atr",
                   "directional_efficiency", "reversal_frequency", "m15_atr_percentile",
                   "m15_atr_expansion")
SETUP_FEATURES = ("impulse_size_atr", "retracement_percent", "confirmation_body_percent",
                  "confirmation_range_atr", "stop_atr")
FEATURES = REGIME_FEATURES + SETUP_FEATURES

# Section 7: failure taxonomy for losing continuation trades, by corrected MFE.
MFE_BUCKETS = ((-np.inf, 0.5, "<0.5R"), (0.5, 1.0, "0.5-1.0R"), (1.0, 2.0, "1.0-2.0R"),
               (2.0, 3.0, "2.0-3.0R"), (3.0, np.inf, ">=3.0R"))
FAILURE_CATEGORIES = (
    (-np.inf, 0.25, "IMMEDIATE_REVERSAL"),        # never went meaningfully favorable
    (0.25, 1.00, "LOW_MFE_FAILURE"),              # brief favorable excursion, then stopped
    (1.00, 2.00, "MID_EXCURSION_FAILURE"),        # real follow-through, then reversed
    (2.00, np.inf, "NEAR_TARGET_FAILURE"),        # reached >=2R of a 3R target, then stopped
)

# Section 9: one feature, three predefined one-sided thresholds. Chosen because
# m15_atr_expansion is the only screened bucket positive in all 9 rep x year
# cells; the thresholds bracket the compression/expansion boundary at 1.0.
PROBE_FEATURE = "m15_atr_expansion"
PROBE_THRESHOLDS = (0.90, 0.97, 1.05)


def _config(parameters: dict[str, float]) -> BacktestConfig:
    return BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=STRATEGY_ID,
        timeframe="15m", higher_timeframes=("1h",), start_date=DEVELOPMENT_START,
        end_date=DEVELOPMENT_END, dataset_role=DatasetRole.DEVELOPMENT,
        strategy_parameters=parameters,
    )


def _profit_factor(frame: pd.DataFrame) -> float | None:
    profit = frame.loc[frame.pnl > 1e-9, "pnl"].sum()
    loss = frame.loc[frame.pnl < -1e-9, "pnl"].sum()
    return float(profit / abs(loss)) if loss else (float("inf") if profit else None)


def _max_drawdown_r(frame: pd.DataFrame) -> float:
    """Peak-to-trough of the cumulative R curve, trades ordered by exit time."""
    curve = frame.sort_values("exit_time").r_multiple.cumsum()
    return float((curve.cummax() - curve).max()) if len(curve) else 0.0


def _losing_streak(frame: pd.DataFrame) -> int:
    worst = current = 0
    for pnl in frame.sort_values("exit_time").pnl:
        current = current + 1 if pnl < -1e-9 else 0
        worst = max(worst, current)
    return worst


def _block(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"trades": 0}
    longs, shorts = frame[frame.direction == "LONG"], frame[frame.direction == "SHORT"]
    return {
        "trades": int(len(frame)),
        "win_rate": float(100 * (frame.pnl > 1e-9).mean()),
        "profit_factor": _profit_factor(frame),
        "average_r": float(frame.r_multiple.mean()),
        "total_r": float(frame.r_multiple.sum()),
        "pnl": float(frame.pnl.sum()),
        "max_drawdown_r": _max_drawdown_r(frame),
        "max_losing_streak": _losing_streak(frame),
        "long": {"trades": int(len(longs)), "profit_factor": _profit_factor(longs),
                 "average_r": float(longs.r_multiple.mean()) if len(longs) else None,
                 "total_r": float(longs.r_multiple.sum())},
        "short": {"trades": int(len(shorts)), "profit_factor": _profit_factor(shorts),
                  "average_r": float(shorts.r_multiple.mean()) if len(shorts) else None,
                  "total_r": float(shorts.r_multiple.sum())},
    }


def yearly_statistics(frame: pd.DataFrame) -> dict[str, Any]:
    """Section 2: per-year breakdown, plus the full-period block for reference."""
    return {"all": _block(frame),
            **{str(year): _block(group) for year, group in frame.groupby("year")}}


def bucket_edges(pooled: pd.DataFrame) -> dict[str, list[float]]:
    """Quartile edges from the pooled three-representative sample.

    Pooled edges (rather than per-representative ones) keep every bucket
    comparable across representatives and guarantee non-tiny cells.
    """
    edges = {}
    for feature in FEATURES:
        values = np.unique(pooled[feature].quantile([0, .25, .5, .75, 1.0]).values)
        if len(values) >= 3:
            edges[feature] = [float(value) for value in values]
    return edges


def _bucketize(frame: pd.DataFrame, feature: str, edges: list[float]) -> pd.Series:
    return pd.cut(frame[feature], bins=edges, include_lowest=True, labels=False)


def consistency_screen(pooled: pd.DataFrame, edges: dict[str, list[float]]) -> list[dict[str, Any]]:
    """Section 8: does any feature bucket hold up across every year AND representative?

    Each bucket is scored by how many of the 9 (3 representatives x 3 years)
    cells have positive Avg R. The three representatives overlap heavily — they
    share the impulse and pullback-ceiling settings and most of their trades —
    so the three years are the only near-independent replications here; 9/9 is
    really "3 years, confirmed on 3 correlated variants", not nine independent
    confirmations.
    """
    rows = []
    for feature, values in edges.items():
        buckets = _bucketize(pooled, feature, values)
        for bucket, group in pooled.assign(_bucket=buckets).groupby("_bucket"):
            cells = group.groupby(["representative", "year"]).r_multiple.agg(["mean", "count"])
            per_year = {str(year): float(part.r_multiple.mean())
                        for year, part in group.groupby("year")}
            rows.append({
                "feature": feature, "bucket": int(bucket),
                "range": [values[int(bucket)], values[int(bucket) + 1]],
                "positive_cells": int((cells["mean"] > 0).sum()), "cells": int(len(cells)),
                "minimum_cell_trades": int(cells["count"].min()), "trades": int(len(group)),
                "average_r": float(group.r_multiple.mean()), "average_r_by_year": per_year,
            })
    return sorted(rows, key=lambda row: -row["positive_cells"])


def winner_loser_profile(frame: pd.DataFrame) -> dict[str, Any]:
    """Section 5: median/p25/p75/count for winners vs losers, per feature."""
    winners, losers = frame[frame.pnl > 1e-9], frame[frame.pnl < -1e-9]

    def summary(part: pd.DataFrame, feature: str) -> dict[str, Any]:
        values = part[feature].dropna()
        if values.empty:
            return {"n": 0}
        return {"n": int(len(values)), "median": float(values.median()),
                "p25": float(values.quantile(.25)), "p75": float(values.quantile(.75))}

    return {feature: {"winners": summary(winners, feature), "losers": summary(losers, feature),
                      "median_difference": (float(winners[feature].median() - losers[feature].median())
                                            if len(winners) and len(losers) else None)}
            for feature in FEATURES}


def separation_stability(pooled: pd.DataFrame) -> list[dict[str, Any]]:
    """Section 8: does the winner-minus-loser median difference keep its sign by year?"""
    rows = []
    for feature in FEATURES:
        by_year = {}
        for year, group in pooled.groupby("year"):
            winners, losers = group[group.pnl > 1e-9], group[group.pnl < -1e-9]
            by_year[str(year)] = float(winners[feature].median() - losers[feature].median())
        # A year where winners and losers share the same median separates
        # nothing, so an exact zero counts as failure rather than being skipped
        # (reversal_frequency is a k/19 ratio and ties often enough to matter).
        signs = {float(np.sign(value)) for value in by_year.values()}
        rows.append({"feature": feature, "median_difference_by_year": by_year,
                     "sign_consistent_across_years": len(signs) == 1 and 0.0 not in signs})
    return rows


def loss_attribution(frame: pd.DataFrame, edges: dict[str, list[float]]) -> dict[str, Any]:
    """Section 6: descriptive breakdown of one year's total R."""
    def totals(key: pd.Series) -> dict[str, dict[str, float]]:
        grouped = frame.groupby(key).r_multiple.agg(["sum", "mean", "count"])
        return {str(index): {"total_r": float(row["sum"]), "average_r": float(row["mean"]),
                             "trades": int(row["count"])}
                for index, row in grouped.iterrows()}

    output = {"direction": totals(frame.direction), "month": totals(frame.month)}
    for feature, values in edges.items():
        buckets = _bucketize(frame, feature, values)
        labels = buckets.map(lambda bucket: (f"[{values[int(bucket)]:.3f},{values[int(bucket) + 1]:.3f}]"
                                             if pd.notna(bucket) else "undefined"))
        output[feature] = totals(labels)
    return output


def mfe_failure_profile(frame: pd.DataFrame) -> dict[str, Any]:
    """Section 7: what losing continuation trades did after entry, before the stop."""
    losers = frame[frame.pnl < -1e-9]
    if losers.empty:
        return {}

    def distribution(part: pd.DataFrame) -> dict[str, Any]:
        counts = {label: int(((part.mfe_r > low) & (part.mfe_r <= high)).sum())
                  for low, high, label in MFE_BUCKETS}
        categories = {label: int(((part.mfe_r > low) & (part.mfe_r <= high)).sum())
                      for low, high, label in FAILURE_CATEGORIES}
        total = len(part)
        return {"losers": total, "median_mfe_r": float(part.mfe_r.median()),
                "mfe_buckets": counts,
                "mfe_bucket_share": {label: round(count / total, 4) for label, count in counts.items()},
                "failure_categories": categories,
                "failure_category_share": {label: round(count / total, 4)
                                           for label, count in categories.items()}}

    return {"all": distribution(losers),
            **{str(year): distribution(group) for year, group in losers.groupby("year")}}


def threshold_probe(frames: dict[str, pd.DataFrame], feature: str,
                    thresholds: tuple[float, ...]) -> list[dict[str, Any]]:
    """Sections 9/10: one feature, three predefined minimum thresholds.

    Applied post hoc to the executed trades, identically for all three
    representatives. This is an attribution view, not a re-executed strategy:
    skipping a signal would have freed the single position slot and could have
    admitted a different trade, which this view cannot show. Drawdown is
    therefore a reconstruction over the retained trades, not an engine result.
    """
    rows = []
    for threshold in thresholds:
        for name, frame in frames.items():
            retained = frame[frame[feature] >= threshold]
            baseline = _block(frame)
            block = _block(retained)
            rows.append({
                "feature": feature, "threshold": threshold, "representative": name,
                "trades_retained": block.get("trades", 0),
                "trades_retained_percent": round(100 * block.get("trades", 0) / len(frame), 2),
                "total_r": block.get("total_r"), "profit_factor": block.get("profit_factor"),
                "average_r": block.get("average_r"),
                "max_drawdown_r_post_hoc": block.get("max_drawdown_r"),
                "baseline_total_r": baseline["total_r"], "baseline_average_r": baseline["average_r"],
                "baseline_max_drawdown_r": baseline["max_drawdown_r"],
                "average_r_by_year": {str(year): float(group.r_multiple.mean())
                                      for year, group in retained.groupby("year")},
                "trades_by_year": {str(year): int(len(group))
                                   for year, group in retained.groupby("year")},
                "baseline_average_r_by_year": {str(year): float(group.r_multiple.mean())
                                               for year, group in frame.groupby("year")},
                "long_average_r": block.get("long", {}).get("average_r"),
                "short_average_r": block.get("short", {}).get("average_r"),
            })
    return rows


def classify(report: dict[str, Any]) -> dict[str, Any]:
    """Section 11: derive A/B/C from the evidence rather than asserting it.

    A requires a probe threshold that makes every year positive for every
    representative while keeping a usable share of the trades. C requires the
    absence of any coherent, repeatable failure signature. Anything else is B.
    """
    probes: dict[float, list[dict[str, Any]]] = {}
    for row in report["threshold_probe"]:
        probes.setdefault(row["threshold"], []).append(row)

    repairing_thresholds = [
        threshold for threshold, rows in probes.items()
        if all(all(value > 0 for value in row["average_r_by_year"].values()) for row in rows)
        and min(row["trades_retained_percent"] for row in rows) >= 50
    ]
    # Does the probe merely relocate the losing year instead of removing it?
    relocated = sorted({
        threshold for threshold, rows in probes.items()
        for row in rows for year, value in row["average_r_by_year"].items()
        if value < 0 and row["baseline_average_r_by_year"][year] > 0
    })

    profile = report["mfe_failure_profile"]
    mechanism_consistent = all(
        profile[name]["2022"]["median_mfe_r"]
        > max(profile[name][year]["median_mfe_r"] for year in ("2021", "2023"))
        and profile[name]["2022"]["failure_category_share"]["NEAR_TARGET_FAILURE"]
        > max(profile[name][year]["failure_category_share"]["NEAR_TARGET_FAILURE"]
              for year in ("2021", "2023"))
        for name in REPRESENTATIVES
    )
    year_stable_features = [row["feature"] for row in report["separation_stability"]
                            if row["sign_consistent_across_years"]]
    all_cell_buckets = [row for row in report["consistency_screen"]
                        if row["positive_cells"] == row["cells"]]

    if repairing_thresholds:
        letter, label = "A", "CORE ARCHITECTURE PROMISING"
    elif mechanism_consistent or all_cell_buckets:
        letter, label = "B", "REGIME DEPENDENCE UNRESOLVED"
    else:
        letter, label = "C", "CORE ARCHITECTURE WEAK"

    return {
        "classification": letter, "label": label,
        "thresholds_making_every_year_positive_for_every_representative": repairing_thresholds,
        "thresholds_that_turned_a_previously_positive_year_negative": relocated,
        "failure_signature_consistent_across_representatives": mechanism_consistent,
        "features_with_year_stable_winner_loser_separation": year_stable_features,
        "buckets_positive_in_every_representative_year_cell": [
            {"feature": row["feature"], "range": row["range"], "trades": row["trades"],
             "average_r_by_year": row["average_r_by_year"]} for row in all_cell_buckets],
        "buckets_screened": len(report["consistency_screen"]),
        "note": ("The three representatives share the impulse threshold and pullback ceiling "
                 "and overlap heavily in their trades, so the three years are the only "
                 "near-independent replications; one bucket out of 48 clearing every cell is "
                 "within what screening this many buckets against three years produces by chance."),
    }


def build() -> dict[str, Any]:
    data = load_development_data()
    market = market_features(data)

    frames: dict[str, pd.DataFrame] = {}
    for name, parameters in REPRESENTATIVES.items():
        result = run_universal_backtest(DATA, _config(parameters),
                                        ledger_path=Path("/tmp") / "pb1_phase_b2_scratch_ledger.sqlite3")
        frame = build_trade_frame(result, market)
        # Engine convention: a trade belongs to the year/month it was entered.
        frame["year"] = frame["entry_time"].dt.year
        frame["month"] = frame["entry_time"].dt.strftime("%Y-%m")
        direction_sign = np.where(frame.direction == "LONG", 1.0, -1.0)
        frame["aligned_fast_slope_atr"] = frame.h1_fast_slope_atr * direction_sign
        frame["aligned_slow_slope_atr"] = frame.h1_slow_slope_atr * direction_sign
        frame["representative"] = name
        if len(frame) != PHASE_B1_TRADES[name]:
            raise ValueError(f"{name} produced {len(frame)} trades, expected the Phase B.1 count "
                             f"{PHASE_B1_TRADES[name]}; the representative no longer reproduces.")
        frames[name] = frame

    pooled = pd.concat(frames.values(), ignore_index=True)
    edges = bucket_edges(pooled)
    columns = ["representative", "signal_time", "entry_time", "exit_time", "direction", "year",
               "month", "r_multiple", "pnl", "mfe_r", "mae_r", "exit_reason", *FEATURES]
    pooled[columns].to_csv(TRADES, index=False)

    report: dict[str, Any] = {
        "phase": "PB1 Phase B.2 — DEVELOPMENT regime failure diagnosis",
        "dataset_role": "DEVELOPMENT",
        "period": {"start": DEVELOPMENT_START.isoformat(), "end": DEVELOPMENT_END.isoformat()},
        "representatives": REPRESENTATIVES,
        "diagnostic_definitions": {
            "directional_efficiency": DIRECTIONAL_EFFICIENCY_FORMULA,
            "reversal_frequency": REVERSAL_FREQUENCY_FORMULA,
            "m15_atr_percentile": ATR_PERCENTILE_FORMULA,
            "m15_atr_expansion": ATR_EXPANSION_FORMULA,
            "aligned_slope": "H1 EMA slope over 4 confirmed H1 bars / H1 ATR, signed so that "
                             "positive always means the H1 trend moves in the trade's direction",
            "mfe_mae": "Phase A.1 semantics: excursion price distance / initial stop price distance",
        },
        "bucket_edges": edges,
        "yearly": {name: yearly_statistics(frame) for name, frame in frames.items()},
        "winner_loser_2022": {name: winner_loser_profile(frame[frame.year == 2022])
                              for name, frame in frames.items()},
        "winner_loser_all_years": {name: winner_loser_profile(frame) for name, frame in frames.items()},
        "separation_stability": separation_stability(pooled),
        "consistency_screen": consistency_screen(pooled, edges),
        "loss_attribution_2022": {name: loss_attribution(frame[frame.year == 2022], edges)
                                  for name, frame in frames.items()},
        "mfe_failure_profile": {name: mfe_failure_profile(frame) for name, frame in frames.items()},
        "threshold_probe": threshold_probe(frames, PROBE_FEATURE, PROBE_THRESHOLDS),
    }
    report["verdict"] = classify(report)
    REPORT.write_text(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    output = build()
    screen = output["consistency_screen"]
    best = [row for row in screen if row["positive_cells"] == row["cells"]]
    stable = [row for row in output["separation_stability"] if row["sign_consistent_across_years"]]
    print(f"buckets screened={len(screen)} all-cell-positive={len(best)} "
          f"features with year-stable winner/loser separation={len(stable)}")
    for name in REPRESENTATIVES:
        years = output["yearly"][name]
        print(name, {year: round(years[year]["average_r"], 4)
                     for year in ("2021", "2022", "2023")})
