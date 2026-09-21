"""BTC Architecture Reset B — M5 execution feasibility, DEVELOPMENT only.

The question is whether H1 context / M15 structure / M5 trigger can deliver both
frequency and edge, after M15's high-frequency search closed in Phase G and
Architecture Reset A.

Two things gate that question, and this module answers both before any setup is
examined, because the brief's own section A says to stop early if the cost
geometry is unusable.

**The data gate.** No validated broker-native Exness BTCUSDm M5 history exists in
this repository. ``audit_m5_availability`` establishes that rather than asserting
it, and states the acceptance criteria any future export must meet — measured
from the M15 and H1 files that were accepted, so the bar is the one already in
force and not a new one.

**The cost gate.** M5 helps only if a tighter entry does not make transaction
cost proportionally worse. That decomposes into three measurable pieces, and
two of them turn out to be scale-invariant on this instrument:

* the broker's bar spread does not change with bar size — median 28.80 on both
  the M15 and the H1 file, a ratio of exactly 1.0000;
* the repository's own structural stop is a near-constant multiple of ATR —
  0.952 to 0.971 ATR across a sixteen-fold range of bar durations;
* ATR itself scales as duration^h, and h is fitted here rather than assumed.

Those three together fix the M5 cost per unit of risk without needing a single
M5 bar, because the only quantity that changes is ATR. The projection is still an
extrapolation *below* the shortest bar in hand, so it is reported with the
random-walk bound (h = 0.5), which is the most favourable value M5 can have.

Nothing here reads past ``DEVELOPMENT_END``, and nothing resamples M15 downward:
every aggregate built below is an *upward* aggregation, used only to fit the
scaling law, and it is validated against the independent broker H1 file.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from core.fingerprints import sha256_file
from research.core_v2_phase_a import (
    DATASET_FINGERPRINT, DEVELOPMENT_END, DEVELOPMENT_START, HOLDOUT_START,
)
from research import core_v2_phase_g_outcomes as g
from services import market_datasets as md
from utils.data_validation import continuous_segments, invalid_ohlcv_mask, missing_gaps

ROOT = Path(__file__).resolve().parents[1]

#--- Bar duration in minutes, as a multiple of M15, for the scaling fit. Only
#--- upward aggregates: M5 is the extrapolation target, never a resample source.
AGGREGATES: tuple[tuple[str, str | None, int], ...] = (
    ("M15", None, 1), ("M30", "30min", 2), ("H1", "1h", 4),
    ("H2", "2h", 8), ("H4", "4h", 16), ("H6", "6h", 24),
)
M5_DURATION_RATIO = 1 / 3          # five minutes is a third of fifteen
RANDOM_WALK_EXPONENT = 0.5         # the most favourable h an M5 bar can have

#--- The MT5 exporter that produced every validated file in this repository.
EXPORTER = "mt5/Export_BTCUSD_History.mq5"


# --- the data gate ---------------------------------------------------------------------


def audit_m5_availability() -> dict[str, Any]:
    """Is there a validated broker-native M5 dataset? Measured, not assumed."""
    registered = {key: md.dataset(key).timeframe for key in
                  (md.EXNESS_BTCUSDM_M15, md.EXNESS_BTCUSDM_H1,
                   md.EXNESS_XAUUSDM_M15, md.EXNESS_XAUUSDM_H1,
                   md.BITSTAMP_BTCUSD_15M)}
    m5_registered = [key for key, frame in registered.items() if frame in ("5m", "M5")]
    #--- A filesystem sweep as well as a registry check: an unregistered file
    #--- would still be evidence, and its absence is part of the finding.
    candidates = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "data").rglob("*.csv")
        if any(token in path.name.lower() for token in ("_m5", "m5_", "_5m", "5min")))
    exporter = ROOT / EXPORTER
    timeframes = []
    if exporter.exists():
        #--- Whole-token matching: a plain substring test reports PERIOD_M1 for
        #--- every PERIOD_M15 in the file and would overstate what it exports.
        text = exporter.read_text()
        timeframes = sorted(set(re.findall(r"\bPERIOD_[A-Z0-9]+\b", text)))
    return {
        "validated_m5_dataset_registered": bool(m5_registered),
        "registered_timeframes": registered,
        "m5_files_on_disk": candidates,
        "exporter": EXPORTER,
        "exporter_present": exporter.exists(),
        "exporter_timeframes_emitted": timeframes,
        "acquisition_requires": (
            "a Windows MetaTrader 5 terminal logged into the Exness-MT5Trial5 "
            "account running the existing exporter with PERIOD_M5 added; "
            "CopyRates history is only reachable from the terminal itself"),
        "blocked": not m5_registered,
    }


def acceptance_criteria() -> dict[str, Any]:
    """What an M5 export must satisfy, measured from the files already accepted.

    Stating the bar from the M15 and H1 files means a future M5 export is held to
    the standard already in force rather than to one invented for it.
    """
    payload: dict[str, Any] = {}
    for key in (md.EXNESS_BTCUSDM_M15, md.EXNESS_BTCUSDM_H1):
        entry = md.dataset(key)
        frame = _load(key)
        stamps = frame["timestamp_utc"]
        step = pd.Timedelta(seconds=entry.step_seconds)
        deltas = stamps.diff().dropna()
        #--- ``invalid_ohlcv_mask`` speaks the canonical schema, where the
        #--- volume column is ``volume``; the broker export names it ``tick_volume``.
        ohlcv = frame.rename(columns={"timestamp_utc": "timestamp",
                                      "tick_volume": "volume"})
        payload[key] = {
            "path": str(entry.path.relative_to(ROOT)),
            "fingerprint": sha256_file(entry.path),
            "symbol": entry.symbol, "broker": entry.broker,
            "timeframe": entry.timeframe, "step_seconds": entry.step_seconds,
            "bars_in_development": len(frame),
            "first": stamps.iloc[0].isoformat(), "last": stamps.iloc[-1].isoformat(),
            "timezone": str(stamps.dt.tz),
            "monotonic_increasing": bool(stamps.is_monotonic_increasing),
            "duplicate_timestamps": int(stamps.duplicated().sum()),
            "bars_on_step_grid": int((deltas == step).sum()),
            "gap_count": int((deltas > step).sum()),
            "largest_gap_bars": (int(deltas.max() / step) if len(deltas) else 0),
            "invalid_ohlc_rows": int(invalid_ohlcv_mask(ohlcv).sum()),
            "zero_or_negative_tick_volume": int((frame["tick_volume"] <= 0).sum()),
            "spread_source": entry.spread_source,
            "spread_price_median": float(frame["spread_price"].median()),
            "spread_price_p95": float(frame["spread_price"].quantile(0.95)),
            "spread_price_max": float(frame["spread_price"].max()),
            "spread_non_positive": int((frame["spread_price"] <= 0).sum()),
        }
    return payload


def _load(key: str) -> pd.DataFrame:
    frame = pd.read_csv(md.dataset(key).path)
    frame["timestamp_utc"] = pd.to_datetime(frame["timestamp_utc"], utc=True)
    window = frame[frame["timestamp_utc"].between(DEVELOPMENT_START, DEVELOPMENT_END)]
    if window["timestamp_utc"].max() >= HOLDOUT_START:
        raise ValueError("Architecture Reset B must not read the holdout split.")
    return window.reset_index(drop=True)


# --- the cost gate ----------------------------------------------------------------------


def _atr(frame: pd.DataFrame, length: int = 14) -> pd.Series:
    previous = frame["close"].shift()
    true_range = pd.concat([frame["high"] - frame["low"],
                            (frame["high"] - previous).abs(),
                            (frame["low"] - previous).abs()], axis=1).max(axis=1)
    return true_range.rolling(length).mean()


def _aggregate(frame: pd.DataFrame, rule: str | None) -> pd.DataFrame:
    if rule is None:
        return frame
    return (frame.set_index("timestamp_utc")
            .resample(rule)
            .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                 close=("close", "last"), spread_price=("spread_price", "mean"))
            .dropna().reset_index())


def spread_invariance() -> dict[str, Any]:
    """Does the broker's bar spread depend on bar size? Two independent files say no."""
    payload: dict[str, Any] = {}
    for label, key in (("M15", md.EXNESS_BTCUSDM_M15), ("H1", md.EXNESS_BTCUSDM_H1)):
        spread = _load(key)["spread_price"]
        payload[label] = {"median": float(spread.median()), "mean": float(spread.mean()),
                          "p95": float(spread.quantile(0.95)),
                          "p99": float(spread.quantile(0.99)), "max": float(spread.max())}
    payload["h1_over_m15_median_ratio"] = round(
        payload["H1"]["median"] / payload["M15"]["median"], 6)
    #--- 1.00 means the descriptor is a typical spread, not a per-bar maximum, so
    #--- a shorter bar would quote the same number.
    payload["timeframe_invariant"] = abs(payload["h1_over_m15_median_ratio"] - 1.0) < 0.02
    return payload


def cost_geometry() -> dict[str, Any]:
    """ATR, structural stop and cost per unit risk, across every duration in hand."""
    m15 = _load(md.EXNESS_BTCUSDM_M15)
    rows: list[dict[str, Any]] = []
    for label, rule, multiple in AGGREGATES:
        frame = _aggregate(m15, rule)
        atr = _atr(frame)
        stop = frame["low"].rolling(g.STOP_LOOKBACK).min() - g.STOP_BUFFER_ATR * atr
        risk_atr = ((frame["close"] - stop) / atr).replace([np.inf, -np.inf], np.nan).dropna()
        inside = risk_atr[(risk_atr >= g.MIN_STOP_ATR) & (risk_atr <= g.MAX_STOP_ATR)]
        median_atr = float(atr.median())
        median_risk = float(inside.median())
        spread = float(frame["spread_price"].median())
        rows.append({
            "frame": label, "duration_multiple": multiple, "bars": len(frame),
            "median_atr": round(median_atr, 4),
            "median_structural_stop_atr": round(median_risk, 4),
            "percent_inside_frozen_stop_band": round(100 * len(inside) / len(risk_atr), 2),
            "median_spread": round(spread, 4),
            "spread_over_atr": round(spread / median_atr, 6),
            "cost_per_r": round(spread / median_atr / median_risk, 6),
        })
    return {"rows": rows}


def atr_scaling(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Fit ATR ~ duration^h, and check it against the independent broker H1 file."""
    x = np.log([row["duration_multiple"] for row in rows])
    y = np.log([row["median_atr"] for row in rows])
    exponent, intercept = np.polyfit(x, y, 1)
    predicted = np.exp(intercept + exponent * x)
    broker_h1 = float(_atr(_load(md.EXNESS_BTCUSDM_H1)).median())
    aggregated_h1 = next(row["median_atr"] for row in rows if row["frame"] == "H1")
    return {
        "exponent_h": round(float(exponent), 6),
        "fit": [{"frame": row["frame"], "actual": row["median_atr"],
                 "fitted": round(float(value), 4),
                 "error_percent": round(100 * (float(value) / row["median_atr"] - 1), 4)}
                for row, value in zip(rows, predicted)],
        "worst_fit_error_percent": round(
            max(abs(100 * (float(v) / r["median_atr"] - 1)) for r, v in zip(rows, predicted)), 4),
        #--- The aggregation itself is validated, not just the fit: an upward
        #--- aggregate of M15 must reproduce the broker's own H1 bars.
        "broker_h1_median_atr": round(broker_h1, 4),
        "aggregated_h1_median_atr": aggregated_h1,
        "aggregation_agreement_percent": round(100 * aggregated_h1 / broker_h1, 4),
    }


def project_m5(rows: Sequence[dict[str, Any]], exponent: float,
               spread: float) -> dict[str, Any]:
    """Carry the two scale-invariants down to M5 and let only ATR move."""
    m15 = next(row for row in rows if row["frame"] == "M15")
    projections: dict[str, Any] = {}
    for label, value in (("random_walk_h_0.50", RANDOM_WALK_EXPONENT),
                         (f"fitted_h_{exponent:.3f}", exponent)):
        ratio = M5_DURATION_RATIO ** value
        atr_m5 = m15["median_atr"] * ratio
        #--- The stop stays at the same ATR multiple because it is measured to be
        #--- scale-free; only ATR shrinks, so only the cost ratio moves.
        cost = spread / atr_m5 / m15["median_structural_stop_atr"]
        projections[label] = {
            "h": round(float(value), 6),
            "atr_m5_over_atr_m15": round(float(ratio), 6),
            "projected_median_atr_m5": round(float(atr_m5), 4),
            "projected_spread_over_atr": round(spread / atr_m5, 6),
            "projected_cost_per_r": round(float(cost), 6),
            "versus_m15": round(float(cost) / m15["cost_per_r"], 4),
        }
    return {
        "m15_cost_per_r": m15["cost_per_r"],
        "m15_median_structural_stop_atr": m15["median_structural_stop_atr"],
        "spread_used": spread,
        "projections": projections,
        "favourable_bound_multiplier": projections["random_walk_h_0.50"]["versus_m15"],
    }


def required_win_rates(cost_per_r: float, targets: Sequence[float]) -> dict[str, Any]:
    """Break-even win rate at each target once the cost is charged.

    Frictionless it is 1/(1+R). With a cost c charged per trade the condition is
    ``R*w - (1-w) - c = 0``, so ``w = (1 + c) / (1 + R)``.
    """
    return {f"{target:.2f}": {
        "frictionless": round(100 / (1 + target), 3),
        "with_cost": round(100 * (1 + cost_per_r) / (1 + target), 3),
        "uplift_points": round(100 * cost_per_r / (1 + target), 3),
    } for target in targets}


#--- The decisive experiment. The projected M5 cost multiplier is applied to the
#--- M15 spread, which reproduces M5's cost *geometry* exactly — the spread is
#--- invariant and the stop is a fixed ATR multiple, so a smaller ATR and a
#--- larger spread are the same thing in R terms. It does not reproduce M5's
#--- signal population, which no data in this repository can.
M5_COST_PLAN: tuple[tuple[str, str, tuple[float, ...]], ...] = (
    ("CORE", "BTC_V3_CORE_V1_FROZEN", (1.75, 2.0, 3.0)),
    ("T3", "BTC_V3_T3_BREAKOUT_SHORT_FROZEN", (2.0, 3.0)),
)
M5_COST_ARMS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("M15 native", {}),
    ("M15 stress x1.20", {"spread_multiplier": 1.20}),
    ("M5-equivalent x1.73", {"spread_multiplier": 1.73}),
    ("M5-equivalent x1.80", {"spread_multiplier": 1.80}),
    ("M5-equivalent x1.73 + slippage 0.01%",
     {"spread_multiplier": 1.73, "slippage_percent": 0.01}),
)


def m5_equivalent_cost_stress(ledger_path: Path) -> dict[str, Any]:
    """What the projected M5 cost does to the only proven edge in the repository."""
    from research.architecture_reset_a import run_stream

    payload: dict[str, Any] = {}
    for label, strategy_id, targets in M5_COST_PLAN:
        arms: dict[str, Any] = {}
        for target in targets:
            row: dict[str, Any] = {}
            for name, stress in M5_COST_ARMS:
                result = run_stream(strategy_id, target, ledger_path, **stress)
                row[name] = {
                    "trades": result.total_trades,
                    "profit_factor": result.profit_factor,
                    "total_r": round(sum(item["realized_r"]
                                         for item in result.trade_log), 4),
                    "max_drawdown_percent": round(result.max_drawdown_percent, 4),
                }
            arms[f"{target:.2f}"] = row
        payload[label] = arms
    return payload


def run_study(ledger_path: Path | None = None) -> dict[str, Any]:
    geometry = cost_geometry()
    scaling = atr_scaling(geometry["rows"])
    spreads = spread_invariance()
    projection = project_m5(geometry["rows"], scaling["exponent_h"],
                            spreads["M15"]["median"])
    targets = (1.0, 1.25, 1.5, 1.75, 2.0)
    m15_cost = projection["m15_cost_per_r"]
    m5_cost = projection["projections"]["random_walk_h_0.50"]["projected_cost_per_r"]
    return {
        "split": {
            "development_start": DEVELOPMENT_START.isoformat(),
            "development_end": DEVELOPMENT_END.isoformat(),
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_touched": False,
        },
        "m15_dataset_fingerprint": DATASET_FINGERPRINT,
        "m5_data_audit": audit_m5_availability(),
        "acceptance_criteria_from_accepted_files": acceptance_criteria(),
        "spread_invariance": spreads,
        "cost_geometry": geometry,
        "atr_scaling": scaling,
        "m5_projection": projection,
        "required_win_rates": {
            "m15": required_win_rates(m15_cost, targets),
            "m5_favourable_bound": required_win_rates(m5_cost, targets),
        },
        "m5_equivalent_cost_stress": (m5_equivalent_cost_stress(ledger_path)
                                      if ledger_path is not None else None),
    }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ledger", type=Path,
                        help="run the M5-equivalent cost stress as well")
    args = parser.parse_args()
    payload = run_study(args.ledger)
    args.out.write_text(json.dumps(payload, default=str, indent=1))
    print(f"wrote {args.out}")
    print(f"M5 data blocked: {payload['m5_data_audit']['blocked']}")
    print(f"M5 cost multiplier (favourable bound): "
          f"{payload['m5_projection']['favourable_bound_multiplier']}x")


if __name__ == "__main__":
    main()
