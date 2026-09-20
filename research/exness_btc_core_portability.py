"""R3 — frozen BTC Core portability: Exness broker-native vs Bitstamp.

Runs the untouched frozen BTC_V3_CORE_V1_FROZEN on both feeds over the exact
same timestamp set and compares the resulting trades one by one. Nothing is
tuned: this is a portability measurement, not an optimization.

Three configurations are run so that feed effects and execution/spread effects
can be separated rather than confounded:

    A  EXNESS_NATIVE    Exness candles + real per-bar broker spread
    B  EXNESS_FLAT10    Exness candles + the calibrated constant $10 spread
    C  BITSTAMP_FLAT10  Bitstamp candles + the calibrated constant $10 spread

    C vs B  isolates the FEED difference   (identical spread model)
    B vs A  isolates the SPREAD difference (identical feed)
    C vs A  is the total portability difference

Both datasets are first restricted to the exact intersection of their
timestamps, so warmup boundaries and continuous segments are identical in every
run and cannot themselves explain a divergence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole
from core.fingerprints import sha256_file

ROOT = Path(__file__).resolve().parents[1]
EXNESS_M15 = ROOT / "data/exness/btc/phase_r1/processed/btcusdm_M15.csv"
BITSTAMP = ROOT / "data/btcusd_15m.csv"
SCRATCH = Path("/tmp/pb_r3_overlap")
REPORT_JSON = ROOT / "reports/validation/exness_btc_core_portability.json"
TRADES_CSV = ROOT / "reports/validation/exness_btc_core_trade_matching.csv"

STRATEGY_ID = "BTC_V3_CORE_V1_FROZEN"
FROZEN_CORE_HASH = "631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd"
CONSTANT_SPREAD = 10.0

#: Tolerances for calling two values "the same". Prices are 2-digit.
PRICE_TOLERANCE = 0.005
R_TOLERANCE = 1e-6


def build_overlap_datasets() -> dict[str, Any]:
    """Restrict both feeds to the exact intersection of their timestamps."""
    exness = pd.read_csv(EXNESS_M15)
    exness["timestamp"] = pd.to_datetime(exness.timestamp_utc, utc=True)
    bitstamp = pd.read_csv(BITSTAMP)
    bitstamp["timestamp"] = pd.to_datetime(bitstamp.timestamp, utc=True)

    shared = exness.timestamp[exness.timestamp.isin(set(bitstamp.timestamp))].sort_values()
    shared_set = set(shared)
    exness_overlap = exness.loc[exness.timestamp.isin(shared_set)].sort_values("timestamp")
    bitstamp_overlap = bitstamp.loc[bitstamp.timestamp.isin(shared_set)].sort_values("timestamp")

    SCRATCH.mkdir(parents=True, exist_ok=True)
    exness_path = SCRATCH / "exness_overlap_M15.csv"
    bitstamp_path = SCRATCH / "bitstamp_overlap_M15.csv"
    exness_overlap[["timestamp_utc", "open", "high", "low", "close",
                    "tick_volume", "spread_price"]].to_csv(exness_path, index=False)
    bitstamp_overlap[["timestamp", "open", "high", "low", "close",
                      "volume"]].to_csv(bitstamp_path, index=False)
    return {
        "matched_candles": int(len(shared)),
        "start_utc": shared.iloc[0].isoformat(), "end_utc": shared.iloc[-1].isoformat(),
        "exness_path": exness_path, "bitstamp_path": bitstamp_path,
        "exness_sha256": sha256_file(exness_path), "bitstamp_sha256": sha256_file(bitstamp_path),
        "note": ("Derived overlap datasets are written outside the repository; they are fully "
                 "reproducible from the committed inputs by rerunning this module."),
    }


def _config(start: pd.Timestamp, end: pd.Timestamp, *, spread_source: str,
            spread: float, notes: str) -> BacktestConfig:
    return BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=STRATEGY_ID,
        timeframe="15m", higher_timeframes=("1h",), start_date=start, end_date=end,
        # This window is broker-native reality, not a research split. It is not
        # DEVELOPMENT and no parameter decision may be taken from it.
        dataset_role=DatasetRole.PAPER,
        spread=spread, spread_source=spread_source, notes=notes,
    )


def run_variant(label: str, path: Path, config: BacktestConfig) -> dict[str, Any]:
    result = run_universal_backtest(path, config, ledger_path=SCRATCH / "r3_ledger.sqlite3")
    if result.strategy_fingerprint != FROZEN_CORE_HASH:
        raise ValueError(f"{label}: frozen Core fingerprint changed — refusing to report.")
    frame = pd.DataFrame(result.trade_log)
    for column in ("signal_time", "entry_time", "exit_time"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    longs = frame.loc[frame.direction == "LONG"]
    shorts = frame.loc[frame.direction == "SHORT"]
    return {
        "label": label,
        "strategy_fingerprint": result.strategy_fingerprint,
        "parameter_fingerprint": result.parameter_fingerprint,
        "dataset_fingerprint": result.dataset_fingerprint,
        "spread_source": config.spread_source,
        "constant_spread": config.spread if config.spread_source == "CONSTANT" else None,
        "metrics": {
            "total_trades": int(result.total_trades),
            "long_trades": int(len(longs)), "short_trades": int(len(shorts)),
            "total_entries": int(result.total_entries),
            "open_at_end": len(result.open_positions_at_end),
            "win_rate": float(result.win_rate),
            "profit_factor": result.profit_factor,
            "average_r": float(result.average_r),
            "total_r": float(frame.realized_r.sum()) if not frame.empty else 0.0,
            "pnl": float(result.pnl),
            "max_drawdown_percent": float(result.max_drawdown_percent),
            "max_losing_streak": int(result.max_losing_streak),
        },
        "_frame": frame,
    }


def _classify(left: pd.Series, right: pd.Series, *, spread_differs: bool,
              feed_differs: bool) -> str:
    """Why do these two matched trades differ? Most specific cause first."""
    entry_gap = abs(left.entry_price - right.entry_price)
    exit_gap = abs(left.exit_price - right.exit_price)
    stop_gap = abs(left.stop_loss - right.stop_loss)
    target_gap = abs(left.take_profit - right.take_profit)
    same_entry_time = left.entry_time == right.entry_time
    same_exit_time = left.exit_time == right.exit_time
    same_reason = left.exit_reason == right.exit_reason

    if (entry_gap <= PRICE_TOLERANCE and exit_gap <= PRICE_TOLERANCE
            and stop_gap <= PRICE_TOLERANCE and target_gap <= PRICE_TOLERANCE
            and same_entry_time and same_exit_time and same_reason
            and abs(left.realized_r - right.realized_r) <= R_TOLERANCE):
        return "IDENTICAL"
    if not same_reason:
        return "EXIT_DIFFERENCE"
    if not same_exit_time:
        return "EXIT_DIFFERENCE"
    if not same_entry_time:
        return "ENTRY_DIFFERENCE"
    # Same bars, same reason: the prices themselves moved. If the feeds are the
    # same, only the spread can have moved the fill; if the feeds differ, the
    # stop level (set from candle geometry, not spread) tells them apart.
    if not feed_differs and spread_differs:
        return "SPREAD_DIFFERENCE"
    if stop_gap > PRICE_TOLERANCE:
        return "FEED_PRICE_DIFFERENCE"
    return "SPREAD_DIFFERENCE" if spread_differs else "FEED_PRICE_DIFFERENCE"


def match_trades(left: dict[str, Any], right: dict[str, Any], *,
                 spread_differs: bool, feed_differs: bool) -> dict[str, Any]:
    """Pair trades on (signal timestamp, side) and describe every difference."""
    a, b = left["_frame"], right["_frame"]
    key = ["signal_time", "direction"]
    merged = a.merge(b, on=key, how="outer", suffixes=("_a", "_b"),
                     indicator="merge_side")

    rows, classifications = [], {}
    for record in merged.itertuples(index=False):
        side = record.merge_side
        if side != "both":
            label = "SIGNAL_DIFFERENCE"
            rows.append({
                "signal_time": record.signal_time, "direction": record.direction,
                "classification": label,
                "present_in": left["label"] if side == "left_only" else right["label"],
            })
            classifications[label] = classifications.get(label, 0) + 1
            continue
        first = pd.Series({name[:-2]: getattr(record, name) for name in merged.columns
                           if name.endswith("_a")})
        second = pd.Series({name[:-2]: getattr(record, name) for name in merged.columns
                            if name.endswith("_b")})
        label = _classify(first, second, spread_differs=spread_differs, feed_differs=feed_differs)
        classifications[label] = classifications.get(label, 0) + 1
        rows.append({
            "signal_time": record.signal_time, "direction": record.direction,
            "classification": label,
            "entry_time_difference_minutes":
                (second.entry_time - first.entry_time).total_seconds() / 60,
            "entry_price_difference": second.entry_price - first.entry_price,
            "stop_loss_difference": second.stop_loss - first.stop_loss,
            "take_profit_difference": second.take_profit - first.take_profit,
            "exit_time_difference_minutes":
                (second.exit_time - first.exit_time).total_seconds() / 60,
            "exit_reason_a": first.exit_reason, "exit_reason_b": second.exit_reason,
            "exit_reason_changed": first.exit_reason != second.exit_reason,
            "r_difference": second.realized_r - first.realized_r,
        })
    detail = pd.DataFrame(rows)
    paired = detail.loc[detail.classification != "SIGNAL_DIFFERENCE"]
    return {
        "comparison": f"{left['label']} vs {right['label']}",
        "isolates": ("FEED (identical spread model)" if feed_differs and not spread_differs
                     else "SPREAD (identical feed)" if spread_differs and not feed_differs
                     else "FEED + SPREAD combined"),
        "trades_a": int(len(a)), "trades_b": int(len(b)),
        "matched_signals": int(len(paired)),
        "unmatched_signals": int((detail.classification == "SIGNAL_DIFFERENCE").sum()),
        "matched_percent_of_a": float(100 * len(paired) / len(a)) if len(a) else None,
        "classifications": dict(sorted(classifications.items(), key=lambda kv: -kv[1])),
        "identical_percent_of_matched":
            float(100 * classifications.get("IDENTICAL", 0) / len(paired)) if len(paired) else None,
        "difference_summary": {
            "median_entry_price_difference": float(paired.entry_price_difference.median())
                if len(paired) else None,
            "median_absolute_entry_price_difference":
                float(paired.entry_price_difference.abs().median()) if len(paired) else None,
            "median_absolute_stop_difference":
                float(paired.stop_loss_difference.abs().median()) if len(paired) else None,
            "exit_reason_changes": int(paired.exit_reason_changed.sum()) if len(paired) else 0,
            "median_r_difference": float(paired.r_difference.median()) if len(paired) else None,
            "mean_r_difference": float(paired.r_difference.mean()) if len(paired) else None,
            "total_r_difference": float(paired.r_difference.sum()) if len(paired) else None,
        },
        "_detail": detail,
    }


def build() -> dict[str, Any]:
    overlap = build_overlap_datasets()
    start = pd.Timestamp(overlap["start_utc"])
    end = pd.Timestamp(overlap["end_utc"])

    variants = {
        "EXNESS_NATIVE": run_variant(
            "EXNESS_NATIVE", overlap["exness_path"],
            _config(start, end, spread_source="BROKER_NATIVE_PER_BAR", spread=CONSTANT_SPREAD,
                    notes="R3 Exness broker-native candles with real per-bar spread")),
        "EXNESS_FLAT10": run_variant(
            "EXNESS_FLAT10", overlap["exness_path"],
            _config(start, end, spread_source="CONSTANT", spread=CONSTANT_SPREAD,
                    notes="R3 Exness candles with the calibrated constant spread")),
        "BITSTAMP_FLAT10": run_variant(
            "BITSTAMP_FLAT10", overlap["bitstamp_path"],
            _config(start, end, spread_source="CONSTANT", spread=CONSTANT_SPREAD,
                    notes="R3 Bitstamp candles with the calibrated constant spread")),
    }

    comparisons = [
        match_trades(variants["BITSTAMP_FLAT10"], variants["EXNESS_FLAT10"],
                     spread_differs=False, feed_differs=True),
        match_trades(variants["EXNESS_FLAT10"], variants["EXNESS_NATIVE"],
                     spread_differs=True, feed_differs=False),
        match_trades(variants["BITSTAMP_FLAT10"], variants["EXNESS_NATIVE"],
                     spread_differs=True, feed_differs=True),
    ]
    details = pd.concat([item.pop("_detail").assign(comparison=item["comparison"])
                         for item in comparisons], ignore_index=True)
    TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    details.to_csv(TRADES_CSV, index=False)

    report = {
        "phase": "R3 — frozen BTC Core portability, Exness broker-native vs Bitstamp",
        "strategy_id": STRATEGY_ID,
        "frozen_core_fingerprint": FROZEN_CORE_HASH,
        "not_tuned": "No parameter was changed. The frozen Core is untouched.",
        "overlap": {k: v for k, v in overlap.items() if not isinstance(v, Path)},
        "variants": {name: {k: v for k, v in block.items() if k != "_frame"}
                     for name, block in variants.items()},
        "comparisons": comparisons,
        "cost_status": {
            "spread": "modelled — real per-bar broker spread in EXNESS_NATIVE",
            "commission": "NOT MODELLED — UNVERIFIED for BTCUSDm",
            "swap": "NOT MODELLED — UNVERIFIED; positions are intraday but overnight holds are possible",
            "leverage_margin": "NOT MODELLED — UNVERIFIED; engine caps leverage at 1.0",
            "slippage": "NOT MODELLED — 0.0 in this configuration",
        },
        "limitations": [
            "Exness candles are broker Bid quotes; the Ask stream is synthesized by adding the spread.",
            "MT5 bar spread is a bar-level descriptor, not the spread guaranteed at an execution tick, so EXNESS_NATIVE costs are indicative rather than tick-exact.",
            "This is a portability measurement over a broker-native window. It is not a live-profitability claim.",
        ],
    }
    REPORT_JSON.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


if __name__ == "__main__":
    output = build()
    print(f"overlap {output['overlap']['start_utc']} -> {output['overlap']['end_utc']} "
          f"({output['overlap']['matched_candles']:,} candles)")
    for name, block in output["variants"].items():
        m = block["metrics"]
        print(f"{name:16} trades={m['total_trades']:4} (L{m['long_trades']}/S{m['short_trades']}) "
              f"win={m['win_rate']:6.2f}% PF={m['profit_factor']!s:>7.7} "
              f"avgR={m['average_r']:+.4f} totR={m['total_r']:+8.2f} "
              f"PnL={m['pnl']:+9.2f} DD={m['max_drawdown_percent']:.2f}% "
              f"streak={m['max_losing_streak']}")
    for item in output["comparisons"]:
        print(f"\n{item['comparison']}  [isolates {item['isolates']}]")
        print(f"  matched {item['matched_signals']} / unmatched {item['unmatched_signals']} "
              f"| identical {item['identical_percent_of_matched']:.1f}% of matched")
        print(f"  {item['classifications']}")
        print(f"  total R difference {item['difference_summary']['total_r_difference']:+.2f}")
