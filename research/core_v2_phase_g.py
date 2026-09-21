"""BTC Core V2 — Phase G: the fixed-3R feasibility gate, DEVELOPMENT only.

Phase F ended with a contradiction worth resolving before any more code: the
transition pool delivered the frequency target (F3a, 26.75 Core trades/month,
5.7% frozen-child interference) and failed on edge (incremental PF 0.9123).
Either the pool has no 3R edge, or three particular constructions missed it.

This phase answers that without building a strategy. ``core_v2_phase_g_outcomes``
resolves fixed, predeclared events forward from the next bar's open against the
repository's own structural stop, and this module aggregates: the raw outcome
map, the same map cut by subperiod, and the capacity and frozen-Core overlap of
each pool. The strategy-building stage in the brief is conditional on that map
showing something, and the gate is stated before the numbers: a fixed 3R against
a 1R stop breaks even at **25%**.

Nothing here reads past ``DEVELOPMENT_END``.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from core.trade_log import to_timestamp
from research.core_v2_phase_a import (
    DATASET_FINGERPRINT, DATASET_KEY, DEVELOPMENT_END, DEVELOPMENT_START,
    HOLDOUT_END, HOLDOUT_START, dataset_path, development_config,
)
from research.core_v2_phase_c import _utc
from research.core_v2_phase_f import development_candles, months, run_arm
from utils.data_validation import load_ohlcv_csv
from research import core_v2_phase_f_map as fmap
from research import core_v2_phase_g_outcomes as outcomes

ROOT = Path(__file__).resolve().parents[1]
CORE_BASELINE_ID = "BTC_V3_CORE_V1_FROZEN"

SUBPERIODS: tuple[tuple[str, str, str], ...] = (
    ("2023 partial", "2023-11-10 23:15", "2023-12-31 23:45"),
    ("2024 H1", "2024-01-01 00:00", "2024-06-30 23:45"),
    ("2024 H2", "2024-07-01 00:00", "2024-12-31 23:45"),
    ("2025 H1", "2025-01-01 00:00", "2025-06-30 23:45"),
)

#--- Brief section F: a pool may become a family only if it clears all of these.
MIN_3R_RATE_PERCENT = 25.0          # the arithmetic break-even, stated in the brief
MIN_POSITIVE_SUBPERIODS = 2
MIN_EVENTS_PER_MONTH = 4.0
#--- Twenty event x direction cells are tested, so an unadjusted 5% would be
#--- expected to fire once on noise alone. Reported alongside the Bonferroni
#--- floor rather than instead of it.
SIGNIFICANCE_LEVEL = 0.05


def _span(start: pd.Timestamp, end: pd.Timestamp) -> float:
    return (end - start).total_seconds() / (60 * 60 * 24 * 30.4375)


def development_spreads() -> list[float]:
    """The broker's own quoted spread for each development bar.

    Read from the raw CSV rather than the prepared frame because ``load_ohlcv_csv``
    keeps only the canonical OHLCV columns, and the spread is the whole point of
    using the Exness dataset over the legacy Bitstamp one.
    """
    frame = pd.read_csv(dataset_path())
    stamps = pd.to_datetime(frame["timestamp_utc"], utc=True)
    window = frame.loc[stamps.between(DEVELOPMENT_START, DEVELOPMENT_END)]
    return window["spread_price"].astype(float).tolist()


def spread_effect(gross: Sequence[outcomes.Outcome], net: Sequence[outcomes.Outcome],
                  span_months: float) -> dict[str, Any]:
    """What one spread crossing does to each pool.

    The counts differ slightly between the two passes: shifting the entry moves
    some trades in or out of T3's 0.50-3.00 ATR stop band. That is the honest
    behaviour, not a bug, and it is why both sample sizes are reported.
    """
    payload: dict[str, Any] = {}
    for key in sorted({f"{row.reason}|{row.direction}" for row in gross}):
        reason, direction = key.split("|")
        pick = lambda rows: [row for row in rows
                             if row.reason == reason and row.direction == direction]
        before, after = outcomes.summarise_group(pick(gross), span_months), \
            outcomes.summarise_group(pick(net), span_months)
        payload[key] = {
            "gross_events": before["events"],
            "gross_percent_3r_first": before["reaching_3r"]["percent_target_first"],
            "gross_expectancy_r": before["expectancy_r_pessimistic"],
            "gross_binomial_p": round(outcomes.binomial_tail_p(
                before["reaching_3r"]["target_first"], before["events"],
                outcomes.BREAK_EVEN_3R_RATE / 100.0), 6),
            "net_events": after["events"],
            "net_percent_3r_first": after["reaching_3r"]["percent_target_first"],
            "net_expectancy_r": after["expectancy_r_pessimistic"],
            "net_binomial_p": round(outcomes.binomial_tail_p(
                after["reaching_3r"]["target_first"], after["events"],
                outcomes.BREAK_EVEN_3R_RATE / 100.0), 6),
        }
    return payload


def outcome_map(rows: Sequence[outcomes.Outcome], span_months: float) -> dict[str, Any]:
    """Every event x direction cell, and the same cells pooled across events."""
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(f"{row.event}|{row.direction}", []).append(row)
    payload = {key: outcomes.summarise_group(group, span_months)
               for key, group in sorted(grouped.items())}
    for direction in outcomes.DIRECTIONS:
        pooled = [row for row in rows if row.direction == direction]
        payload[f"ALL_EVENTS|{direction}"] = outcomes.summarise_group(pooled, span_months)
    return payload


def by_reason(rows: Sequence[outcomes.Outcome], span_months: float) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for reason in outcomes.TARGET_BUCKET_REASONS:
        for direction in outcomes.DIRECTIONS:
            group = [row for row in rows
                     if row.reason == reason and row.direction == direction]
            payload[f"{reason}|{direction}"] = outcomes.summarise_group(group, span_months)
    return payload


def subperiod_stability(rows: Sequence[outcomes.Outcome]) -> dict[str, Any]:
    """The same cells, cut by subperiod.

    Brief section C: a pool whose 3R behaviour appears in only one subperiod is
    not a lead. The check is applied to the *rate*, not to a total, because a
    total is dominated by however many events a subperiod happened to contain.
    """
    payload: dict[str, Any] = {}
    for label, start, end in SUBPERIODS:
        lower, upper = _utc(start), _utc(end)
        span = _span(lower, upper)
        window = [row for row in rows if lower <= row.timestamp <= upper]
        payload[label] = outcome_map(window, span)
    return payload


def capacity_and_overlap(rows: Sequence[outcomes.Outcome],
                         census_bars: Sequence[fmap.FBar],
                         span_months: float) -> dict[str, Any]:
    """Events per month, and how many of them the frozen Core was busy for."""
    state = {bar.timestamp: bar for bar in census_bars}
    payload: dict[str, Any] = {}
    grouped: dict[str, list] = {}
    for row in rows:
        grouped.setdefault(row.event, []).append(row)
    for event, group in sorted(grouped.items()):
        #--- One bar produces the same event in both directions; capacity is a
        #--- property of the bar, so count bars, not (bar, direction) pairs.
        stamps = {row.timestamp for row in group}
        busy = sum(1 for stamp in stamps if state[stamp].core_busy)
        payload[event] = {
            "event_bars": len(stamps),
            "events_per_month": round(len(stamps) / span_months, 2),
            "while_core_busy": busy,
            "while_core_flat": len(stamps) - busy,
            "free_opportunities_per_month": round((len(stamps) - busy) / span_months, 2),
            "percent_core_flat": round(100 * (len(stamps) - busy) / len(stamps), 2),
            "a4_setup_overlap": sum(1 for stamp in stamps if state[stamp].a4_setup),
            "t3_setup_overlap": sum(1 for stamp in stamps if state[stamp].t3_setup),
        }
    return payload


def leads(payload: dict[str, Any], stability: dict[str, Any],
          capacity: dict[str, Any]) -> dict[str, Any]:
    """Brief section F, applied mechanically: which cells may become a family.

    A cell qualifies only if its pessimistic 3R rate clears break-even, its
    pessimistic expectancy is positive, it clears the frequency floor, and it
    does so in at least two subperiods. Pessimistic means every ambiguous
    same-bar resolution is counted as a loss, which is the only reading that
    cannot flatter the pool.
    """
    verdict: dict[str, Any] = {}
    for key, cell in payload.items():
        if not cell.get("events"):
            continue
        event = key.split("|")[0]
        rate = cell["reaching_3r"]["percent_target_first"]
        expectancy = cell["expectancy_r_pessimistic"]
        per_month = (capacity.get(event, {}).get("free_opportunities_per_month")
                     if event != "ALL_EVENTS" else cell["events_per_month"])
        positive_subperiods = sum(
            1 for label in stability
            if (stability[label].get(key, {}).get("events", 0)
                and stability[label][key]["reaching_3r"]["percent_target_first"]
                >= MIN_3R_RATE_PERCENT))
        successes = cell["reaching_3r"]["target_first"]
        p_value = outcomes.binomial_tail_p(successes, cell["events"],
                                           outcomes.BREAK_EVEN_3R_RATE / 100.0)
        failures: list[str] = []
        #--- The gate the brief did not name but the arithmetic demands. Twenty
        #--- cells are tested; at the 10% level two of them land above break-even
        #--- by chance, so a rate above 25% is not on its own evidence of an edge.
        if p_value > SIGNIFICANCE_LEVEL:
            failures.append(f"rate is not distinguishable from the {MIN_3R_RATE_PERCENT}% "
                            f"break-even (exact binomial p = {p_value:.4f})")
        if rate is None or rate < MIN_3R_RATE_PERCENT:
            failures.append(f"3R-before-1R rate {rate}% is below break-even "
                            f"{MIN_3R_RATE_PERCENT}%")
        if expectancy is None or expectancy <= 0:
            failures.append(f"pessimistic fixed-3R expectancy {expectancy}R is not positive")
        if per_month is None or per_month < MIN_EVENTS_PER_MONTH:
            failures.append(f"free capacity {per_month}/month is below "
                            f"{MIN_EVENTS_PER_MONTH}/month")
        if positive_subperiods < MIN_POSITIVE_SUBPERIODS:
            failures.append(f"clears break-even in only {positive_subperiods} subperiod(s)")
        verdict[key] = {
            "qualifies": not failures,
            "failures": failures,
            "percent_3r_first": rate,
            "binomial_p_value": round(p_value, 6),
            "percent_3r_first_optimistic": cell["reaching_3r"]["percent_target_first_optimistic"],
            "expectancy_r_pessimistic": expectancy,
            "expectancy_r_optimistic": cell["expectancy_r_optimistic"],
            "free_opportunities_per_month": per_month,
            "subperiods_clearing_break_even": positive_subperiods,
        }
    return verdict


def controls(candles, bars) -> dict[str, Any]:
    """Does this measurement detect an edge that is known to exist?

    A feasibility gate that returns "no edge" everywhere is worthless unless it
    can be shown to return "edge" somewhere. The controls below run the identical
    machinery — next-open entry, T3 structural stop, 3R target, same horizon — on
    pools whose answer is already known: every development bar with no filter at
    all (the null), each regime bucket, and the two frozen children's own
    unconstrained setup bars. T3 is frozen because it passed validation, so if
    anything clears the 25% line it should.
    """
    import numpy as np
    from engine.models import ExecutionState, Signal
    from strategies.btc_v3_a4_pullback_long import BtcV3A4PullbackLongFrozen
    from strategies.btc_v3_t3_breakout_short import BtcV3T3BreakoutShortFrozen

    highs = np.array([c.high for c in candles], dtype=float)
    lows = np.array([c.low for c in candles], dtype=float)
    opens = np.array([c.open for c in candles], dtype=float)

    def resolve(selector, long_for) -> dict[str, Any]:
        counts: Counter = Counter()
        for bar in bars:
            if not bar.atr or not selector(bar):
                continue
            index = bar.index + 1
            if index >= len(opens):
                continue
            long = long_for(bar)
            if long is None:
                continue
            entry = float(opens[index])
            stop = (bar.stop_low - outcomes.STOP_BUFFER_ATR * bar.atr if long
                    else bar.stop_high + outcomes.STOP_BUFFER_ATR * bar.atr)
            if (long and entry <= stop) or (not long and entry >= stop):
                continue
            risk_atr = abs(entry - stop) / bar.atr
            if not outcomes.MIN_STOP_ATR <= risk_atr <= outcomes.MAX_STOP_ATR:
                continue
            counts[outcomes._walk(highs, lows, index, entry, stop, long)["resolution"]] += 1
        total = sum(counts.values())
        hits = counts["TARGET_3R"]
        return {
            "samples": total, "reached_3r_first": hits,
            "percent_3r_first": round(100 * hits / total, 2) if total else None,
            "binomial_p_value": round(
                outcomes.binomial_tail_p(hits, total,
                                         outcomes.BREAK_EVEN_3R_RATE / 100.0), 6)
            if total else None,
            "resolution": dict(counts),
        }

    bullish = lambda bar: bar.lean == "BULLISH_LEAN"
    bearish = lambda bar: bar.lean != "BULLISH_LEAN"
    any_lean = lambda bar: bar.lean in ("BULLISH_LEAN", "BEARISH_LEAN")
    payload = {
        "every_bar_no_filter_toward_h1": resolve(any_lean, bullish),
        "every_bar_no_filter_against_h1": resolve(any_lean, bearish),
        "trend_buckets_toward_h1": resolve(
            lambda bar: bar.bucket in ("BULLISH_TREND", "BEARISH_TREND") and bool(bar.events),
            bullish),
        "neutral_range_toward_h1": resolve(
            lambda bar: bar.bucket == "NEUTRAL_RANGE" and bool(bar.events), bullish),
    }
    for label, factory, long in (("frozen_a4_setup_bars_long", BtcV3A4PullbackLongFrozen, True),
                                 ("frozen_t3_setup_bars_short", BtcV3T3BreakoutShortFrozen, False)):
        strategy = factory()
        strategy.reset()
        fired: set = set()
        for candle in candles:
            strategy.on_execution_state(ExecutionState(10_000.0, None, None, None, None))
            if isinstance(strategy.on_candle(candle), Signal):
                fired.add(candle.timestamp)
        payload[label] = resolve(lambda bar, f=fired: bar.timestamp in f,
                                 lambda bar, value=long: value)
    return payload


def run_phase_g(ledger_path: Path) -> dict[str, Any]:
    candles = development_candles()
    span = months()
    baseline = run_arm(CORE_BASELINE_ID, ledger_path)

    census_bars = fmap.census(candles)
    fmap.mark_coverage(census_bars, baseline.trade_log)

    bars = outcomes.contexts(candles)
    #--- Gross first, because it is the brief's question; net second, because it
    #--- is the one a strategy would actually live in.
    gross = outcomes.measure(candles, bars)
    excluded_gross = dict(getattr(outcomes.measure, "rejected", {}))
    rows = outcomes.measure(candles, bars, development_spreads())
    reasons = Counter(bar.reason for bar in bars if bar.reason)

    payload: dict[str, Any] = {
        "split": {
            "development_start": DEVELOPMENT_START.isoformat(),
            "development_end": DEVELOPMENT_END.isoformat(),
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_end": HOLDOUT_END.isoformat(),
            "holdout_touched": False,
        },
        "dataset": {"key": DATASET_KEY, "path": str(dataset_path().relative_to(ROOT)),
                    "fingerprint": DATASET_FINGERPRINT},
        "method": {
            "entry": "next bar open, plus the bar's quoted spread on the costed side",
            "primary_measurement": "net of the dataset's per-bar spread",
            "excluded_gross": excluded_gross,
            "stop": f"T3 {outcomes.STOP_LOOKBACK}-bar structural extreme "
                    f"+/- {outcomes.STOP_BUFFER_ATR} ATR",
            "stop_band_atr": [outcomes.MIN_STOP_ATR, outcomes.MAX_STOP_ATR],
            "reward_multiple": outcomes.REWARD_MULTIPLE,
            "horizon_bars": outcomes.HORIZON_BARS,
            "break_even_3r_rate_percent": outcomes.BREAK_EVEN_3R_RATE,
            "excluded": getattr(outcomes.measure, "rejected", {}),
        },
        "target_bucket_counts": {name: reasons.get(name, 0)
                                 for name in outcomes.TARGET_BUCKET_REASONS},
        "all_transition_reason_counts": dict(reasons),
        "core_baseline": {
            "closed_trades": baseline.total_trades,
            "trades_per_month": baseline.trades_per_month,
            "profit_factor": baseline.profit_factor,
            "average_r": baseline.average_r,
            "total_r": sum(row["realized_r"] for row in baseline.trade_log),
            "max_drawdown_percent": baseline.max_drawdown_percent,
        },
        "outcome_map": outcome_map(rows, span),
        "outcome_map_gross": outcome_map(gross, span),
        "by_target_bucket": by_reason(rows, span),
        "by_target_bucket_gross": by_reason(gross, span),
        "spread_effect": spread_effect(gross, rows, span),
        "capacity_and_overlap": capacity_and_overlap(rows, census_bars, span),
    }
    payload["controls"] = controls(candles, bars)
    payload["subperiod_stability"] = subperiod_stability(rows)
    payload["leads"] = leads({**payload["outcome_map"], **payload["by_target_bucket"]},
                             payload["subperiod_stability"],
                             payload["capacity_and_overlap"])
    payload["qualifying_leads"] = sorted(
        key for key, value in payload["leads"].items() if value["qualifies"])
    cells = {key: value for key, value in payload["leads"].items()
             if not key.startswith("ALL_EVENTS")}
    best = min((value["binomial_p_value"] for value in cells.values()), default=1.0)
    payload["multiple_comparisons"] = {
        "cells_tested": len(cells),
        "significance_level": SIGNIFICANCE_LEVEL,
        "cells_expected_below_level_by_chance": round(len(cells) * SIGNIFICANCE_LEVEL, 2),
        "cells_below_level": sum(1 for value in cells.values()
                                 if value["binomial_p_value"] <= SIGNIFICANCE_LEVEL),
        "best_p_value": best,
        "best_p_value_bonferroni": round(min(1.0, best * len(cells)), 4),
    }
    return payload


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    payload = run_phase_g(args.ledger)
    args.out.write_text(json.dumps(payload, default=str, indent=1))
    print(f"wrote {args.out}")
    print(f"qualifying leads: {payload['qualifying_leads'] or 'NONE'}")


if __name__ == "__main__":
    main()
