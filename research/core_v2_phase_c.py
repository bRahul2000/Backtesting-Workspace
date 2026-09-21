"""BTC Core V2 — Phase C: is the T3 lookback-4 lead structural, or noise?

Phase B found one arm whose newly admitted trades had clearly positive
expectancy — T3 structure lookback 4 against the frozen 5 — and declined to
promote it on stability grounds. Phase C exists only to settle that, on
DEVELOPMENT data, and is designed so that a null result is a real outcome
rather than a failure.

Subperiods and rolling windows slice the trades of one continuous DEVELOPMENT
run rather than re-running the strategy on truncated data. Re-running would give
each window its own warmup and its own cold-start state, so a difference between
windows could come from the warmup rather than from the market. Slicing measures
what the strategy actually did.

Everything here is measured on twelve admitted trades. That is the whole point
of the phase and also its hard limit: no resampling method creates information
that twelve observations do not contain, and the bootstrap below is reported as
a description of that sample's spread, never as a significance test.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from statistics import mean, median
from typing import Any, Iterable, Sequence

import numpy as np
import pandas as pd

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig
from research.core_v2_phase_a import (
    DATASET_FINGERPRINT, DATASET_KEY, DEVELOPMENT_END, DEVELOPMENT_START,
    HOLDOUT_END, HOLDOUT_START, _timestamp, dataset_path, describe_stream,
    development_config, summarise, trade_delta,
)
from research.core_v2_phase_b import excursions
from strategies.btc_core_v2_phase_b_variants import (
    CORE_T3_LOOKBACK_IDS, T3_LOOKBACK_IDS, phase_b_registry,
)
from strategies.btc_core_v2_phase_c_variants import (
    BREAK_DEFINITIONS, BREAK_IDS, LOOKBACKS_UNDER_TEST, phase_c_registry,
)

ROOT = Path(__file__).resolve().parents[1]

BASELINE_LOOKBACK = 5
LEAD_LOOKBACK = 4

STARTING_BALANCE = 10_000.0
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_SEED = 20260921
#--- n^(1/3) for n=12 is 2.3, and the largest observed monthly cluster in the
#--- incremental stream is three trades. Three is reported as primary; 1 (iid),
#--- 2 and 4 are reported beside it so the choice is visible rather than assumed.
BOOTSTRAP_BLOCKS: tuple[int, ...] = (1, 2, 3, 4)
PRIMARY_BLOCK = 3

SUBPERIODS: tuple[tuple[str, str, str], ...] = (
    ("2023 partial", "2023-11-10 23:15", "2023-12-31 23:45"),
    ("2024 H1", "2024-01-01 00:00", "2024-06-30 23:45"),
    ("2024 H2", "2024-07-01 00:00", "2024-12-31 23:45"),
    ("2025 H1", "2025-01-01 00:00", "2025-06-30 23:45"),
)

#--- T3 is short-only with pending stop entries: the entry fills on the Bid
#--- candle at the trigger price and the exits sit at fixed stop/target levels,
#--- so spread only decides *whether* a level is touched inside a bar. A few
#--- dollars on a ~$60k instrument rarely changes that, and the +10%/+20% rows
#--- come back unchanged. The x3.00 row is not a realistic cost assumption; it
#--- is there to show the stress is capable of binding, so an unchanged +20%
#--- row reads as insensitivity rather than as a broken knob.
EXECUTION_STRESS: tuple[tuple[str, float, float], ...] = (
    ("NATIVE", 1.0, 0.0),
    ("SPREAD_x1.10", 1.10, 0.0),
    ("SPREAD_x1.20", 1.20, 0.0),
    ("SPREAD_x3.00_SEVERE", 3.00, 0.0),
    ("SLIPPAGE_0.02%", 1.0, 0.02),
    ("SLIPPAGE_0.05%", 1.0, 0.05),
    ("SPREAD_x1.20_SLIP_0.02%", 1.20, 0.02),
)


# --- running ------------------------------------------------------------------


def _guard(config: BacktestConfig) -> BacktestConfig:
    if config.end_date >= HOLDOUT_START:
        raise ValueError("Phase C must not read the holdout split.")
    return config


def run_arm(strategy_id: str, ledger_path: Path, registry, **overrides):
    config = _guard(replace(development_config(strategy_id), **overrides))
    return run_universal_backtest(dataset_path(), config, ledger_path=ledger_path,
                                  registry=registry)


def run_lookback(lookback: int, ledger_path: Path, **overrides):
    return run_arm(T3_LOOKBACK_IDS[lookback], ledger_path, phase_b_registry(), **overrides)


def run_core_lookback(lookback: int, ledger_path: Path, **overrides):
    return run_arm(CORE_T3_LOOKBACK_IDS[lookback], ledger_path, phase_b_registry(), **overrides)


def run_break(lookback: int, definition: str, ledger_path: Path, **overrides):
    return run_arm(BREAK_IDS[(lookback, definition)], ledger_path, phase_c_registry(),
                   **overrides)


# --- slicing and metrics -------------------------------------------------------


def _utc(value) -> pd.Timestamp:
    """The subperiod bounds are written as plain UTC text; make that explicit."""
    stamp = pd.Timestamp(value)
    return stamp.tz_localize("UTC") if stamp.tzinfo is None else stamp.tz_convert("UTC")


def slice_rows(rows: Sequence[dict], start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    """Trades whose *entry* falls in [start, end]."""
    return [row for row in rows if start <= _timestamp(row["entry_time"]) <= end]


def _months_between(start: pd.Timestamp, end: pd.Timestamp) -> float:
    return max((end - start).total_seconds() / (60 * 60 * 24 * 30.4375), 1e-9)


def _drawdown_percent(rows: Sequence[dict]) -> float:
    """Drawdown of a sliced PnL stream, from the run's starting balance.

    Approximate for a slice: position sizes were set by the running balance of
    the full run, not by this slice's own equity. It is comparable between two
    arms over the same slice, which is all it is used for.
    """
    balance = peak = STARTING_BALANCE
    worst = 0.0
    for row in sorted(rows, key=lambda item: _timestamp(item["entry_time"])):
        balance += row["pnl"]
        peak = max(peak, balance)
        if peak > 0:
            worst = max(worst, (peak - balance) / peak * 100)
    return worst


def metrics(rows: Sequence[dict], start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    stream = describe_stream(rows)
    stream.pop("months", None)
    stream["trades_per_month"] = len(rows) / _months_between(start, end)
    stream["max_drawdown_percent"] = _drawdown_percent(rows)
    return stream


@dataclass(frozen=True)
class Comparison:
    """One L5-vs-L4 comparison over a slice of the development run."""
    label: str
    start: pd.Timestamp
    end: pd.Timestamp
    baseline: dict[str, Any]
    lead: dict[str, Any]
    admitted: dict[str, Any]
    withdrawn: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "baseline": self.baseline, "lead": self.lead,
            "admitted": self.admitted, "withdrawn": self.withdrawn,
            "delta_trades": self.lead["trades"] - self.baseline["trades"],
            "delta_total_r": self.lead["total_r"] - self.baseline["total_r"],
            "net_delta_r": self.admitted["total_r"] - self.withdrawn["total_r"],
            "admitted_expectancy": self.admitted["average_r"],
        }


def compare(label: str, start, end, baseline_rows, lead_rows,
            admitted_rows, withdrawn_rows) -> Comparison:
    start, end = _utc(start), _utc(end)
    return Comparison(
        label, start, end,
        metrics(slice_rows(baseline_rows, start, end), start, end),
        metrics(slice_rows(lead_rows, start, end), start, end),
        metrics(slice_rows(admitted_rows, start, end), start, end),
        metrics(slice_rows(withdrawn_rows, start, end), start, end),
    )


# --- C. block bootstrap ---------------------------------------------------------


def _profit_factor(values: np.ndarray) -> float:
    gains = values[values > 0].sum()
    losses = -values[values < 0].sum()
    if losses <= 0:
        return float("inf") if gains > 0 else float("nan")
    return float(gains / losses)


def block_bootstrap(rows: Sequence[dict], *, block: int, samples: int = BOOTSTRAP_SAMPLES,
                    seed: int = BOOTSTRAP_SEED) -> dict[str, Any]:
    """Circular block bootstrap of one trade stream, in chronological order.

    Blocks preserve whatever adjacency the stream has; a block of 1 is the plain
    iid bootstrap and is reported alongside so the effect of blocking is visible.
    With twelve observations this describes the spread the sample implies. It is
    not a significance test and cannot become one by adding resamples.
    """
    ordered = sorted(rows, key=lambda item: _timestamp(item["entry_time"]))
    values = np.array([row["realized_r"] for row in ordered], dtype=float)
    n = len(values)
    if n == 0:
        return {"trades": 0, "block": block, "samples": 0}
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(samples, int(np.ceil(n / block))))
    offsets = np.arange(block)
    index = (starts[:, :, None] + offsets[None, None, :]) % n
    drawn = values[index.reshape(samples, -1)[:, :n]]

    total = drawn.sum(axis=1)
    average = drawn.mean(axis=1)
    factors = np.array([_profit_factor(row) for row in drawn])
    finite = factors[np.isfinite(factors)]

    def pct(array: np.ndarray, q: float) -> float | None:
        return float(np.percentile(array, q)) if array.size else None

    return {
        "trades": n, "block": block, "samples": samples,
        "observed": {"total_r": float(values.sum()), "average_r": float(values.mean()),
                     "profit_factor": _profit_factor(values)},
        "total_r": {"p5": pct(total, 5), "p25": pct(total, 25), "median": pct(total, 50),
                    "p75": pct(total, 75), "p95": pct(total, 95),
                    "probability_le_0": float((total <= 0).mean())},
        "average_r": {"p5": pct(average, 5), "p25": pct(average, 25), "median": pct(average, 50),
                      "p75": pct(average, 75), "p95": pct(average, 95),
                      "probability_le_0": float((average <= 0).mean())},
        "profit_factor": {
            "p5": pct(finite, 5), "p25": pct(finite, 25), "median": pct(finite, 50),
            "p75": pct(finite, 75), "p95": pct(finite, 95),
            #--- A resample with no losing trade has undefined PF; it is counted
            #--- as above 1, not discarded, so the probability stays honest.
            "probability_le_1": float((np.nan_to_num(factors, nan=0.0,
                                                     posinf=np.inf) <= 1).mean()),
            "undefined_samples": int((~np.isfinite(factors)).sum()),
        },
    }


# --- D. leave-one-out ------------------------------------------------------------


def leave_out(rows: Sequence[dict], *, drop: str, by: str = "month") -> dict[str, Any]:
    fmt = "%Y-%m" if by == "month" else "%Y"
    kept = [row for row in rows if _timestamp(row["entry_time"]).strftime(fmt) != drop]
    stream = describe_stream(kept)
    stream.pop("months", None)
    stream["dropped"] = drop
    stream["dropped_trades"] = len(rows) - len(kept)
    return stream


# --- the phase --------------------------------------------------------------------


def run_phase_c(ledger_path: Path) -> dict[str, Any]:
    baseline = run_lookback(BASELINE_LOOKBACK, ledger_path)
    lead = run_lookback(LEAD_LOOKBACK, ledger_path)
    delta = trade_delta(baseline.trade_log, lead.trade_log)
    admitted, withdrawn = delta.added, delta.displaced

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
        "lead": {"baseline_lookback": BASELINE_LOOKBACK, "lead_lookback": LEAD_LOOKBACK},
        "full_development": {
            "baseline": summarise(baseline), "lead": summarise(lead),
            "admitted": {**describe_stream(admitted), "excursions": excursions(admitted)},
            "withdrawn": {**describe_stream(withdrawn), "excursions": excursions(withdrawn)},
        },
    }

    # A. subperiods and calendar years
    payload["subperiods"] = [
        compare(label, start, end, baseline.trade_log, lead.trade_log,
                admitted, withdrawn).as_dict()
        for label, start, end in SUBPERIODS
    ]
    payload["calendar_years"] = [
        compare(str(year), f"{year}-01-01 00:00", f"{year}-12-31 23:45",
                baseline.trade_log, lead.trade_log, admitted, withdrawn).as_dict()
        for year in (2023, 2024, 2025)
    ]

    # B. rolling windows
    payload["rolling"] = {
        f"{length}m": _rolling(length, baseline.trade_log, lead.trade_log,
                               admitted, withdrawn)
        for length in (3, 6)
    }

    # C. bootstrap
    payload["bootstrap"] = {
        "primary_block": PRIMARY_BLOCK,
        "blocks": {str(block): block_bootstrap(admitted, block=block)
                   for block in BOOTSTRAP_BLOCKS},
        "caveat": ("Twelve observations. These quantiles describe the spread this "
                   "sample implies under resampling; they are not a significance test."),
    }

    # D. leave-one-out
    months = sorted({_timestamp(row["entry_time"]).strftime("%Y-%m") for row in admitted})
    payload["leave_one_month_out"] = [leave_out(admitted, drop=month) for month in months]
    payload["leave_year_out"] = [leave_out(admitted, drop=str(year), by="year")
                                 for year in ("2023", "2024", "2025")]

    # E. break-definition sensitivity
    payload["break_sensitivity"] = _break_sensitivity(ledger_path)

    # F. execution stress
    payload["execution_stress"] = _execution_stress(ledger_path)

    # G. Core
    payload["core"] = _core_impact(ledger_path)
    return payload


def _rolling(length_months: int, baseline_rows, lead_rows, admitted, withdrawn) -> dict[str, Any]:
    windows: list[dict[str, Any]] = []
    start = DEVELOPMENT_START
    while start + pd.DateOffset(months=length_months) <= DEVELOPMENT_END + pd.Timedelta(minutes=15):
        end = start + pd.DateOffset(months=length_months) - pd.Timedelta(minutes=15)
        windows.append(compare(f"{start.date()}→{end.date()}", start, min(end, DEVELOPMENT_END),
                               baseline_rows, lead_rows, admitted, withdrawn).as_dict())
        start = start + pd.DateOffset(months=1)
    deltas = [window["delta_total_r"] for window in windows]
    #--- "Roughly neutral" needs a threshold, and a third of one R is well below
    #--- the size of a single 3R win or 1R loss, so it cannot hide a real move.
    tolerance = 1 / 3
    return {
        "length_months": length_months, "step_months": 1, "windows": windows,
        "summary": {
            "count": len(windows),
            "improved": sum(1 for value in deltas if value > tolerance),
            "degraded": sum(1 for value in deltas if value < -tolerance),
            "neutral": sum(1 for value in deltas if abs(value) <= tolerance),
            "worst_delta_r": min(deltas) if deltas else None,
            "median_delta_r": median(deltas) if deltas else None,
            "best_delta_r": max(deltas) if deltas else None,
            "windows_with_admitted_trades": sum(1 for w in windows if w["admitted"]["trades"]),
            "neutral_tolerance_r": tolerance,
        },
    }


def _break_sensitivity(ledger_path: Path) -> dict[str, Any]:
    output: dict[str, Any] = {"definitions": [], "arms": {}}
    runs: dict[tuple[int, str], Any] = {}
    for lookback in LOOKBACKS_UNDER_TEST:
        for item in BREAK_DEFINITIONS:
            runs[(lookback, item.key)] = run_break(lookback, item.key, ledger_path)
    for item in BREAK_DEFINITIONS:
        base = runs[(BASELINE_LOOKBACK, item.key)]
        lead = runs[(LEAD_LOOKBACK, item.key)]
        admitted = trade_delta(base.trade_log, lead.trade_log).added
        withdrawn = trade_delta(base.trade_log, lead.trade_log).displaced
        output["definitions"].append(item.key)
        output["arms"][item.key] = {
            "label": item.label,
            "baseline": summarise(base), "lead": summarise(lead),
            "admitted": describe_stream(admitted),
            "withdrawn": describe_stream(withdrawn),
            "net_delta_r": (sum(row["realized_r"] for row in lead.trade_log)
                            - sum(row["realized_r"] for row in base.trade_log)),
        }
        for node in ("admitted", "withdrawn"):
            output["arms"][item.key][node].pop("months", None)
    return output


def _execution_stress(ledger_path: Path) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for label, multiplier, slippage in EXECUTION_STRESS:
        overrides = {"spread_multiplier": multiplier, "slippage_percent": slippage}
        base = run_lookback(BASELINE_LOOKBACK, ledger_path, **overrides)
        lead = run_lookback(LEAD_LOOKBACK, ledger_path, **overrides)
        delta = trade_delta(base.trade_log, lead.trade_log)
        admitted = describe_stream(delta.added)
        admitted.pop("months", None)
        output[label] = {
            "spread_multiplier": multiplier, "slippage_percent": slippage,
            "baseline": summarise(base), "lead": summarise(lead),
            "admitted": admitted,
            "net_delta_r": (sum(row["realized_r"] for row in lead.trade_log)
                            - sum(row["realized_r"] for row in base.trade_log)),
        }
    return output


def _core_impact(ledger_path: Path) -> dict[str, Any]:
    base = run_core_lookback(BASELINE_LOOKBACK, ledger_path)
    lead = run_core_lookback(LEAD_LOOKBACK, ledger_path)
    delta = trade_delta(base.trade_log, lead.trade_log)
    longs_base = [row for row in base.trade_log if row["direction"] == "LONG"]
    longs_lead = [row for row in lead.trade_log if row["direction"] == "LONG"]
    standalone_base = run_lookback(BASELINE_LOOKBACK, ledger_path)
    standalone_lead = run_lookback(LEAD_LOOKBACK, ledger_path)

    def identity(rows: Iterable[dict]) -> set:
        return {(row["setup_id"], row["direction"], row["entry_time"],
                 round(row["entry_price"], 6), round(row["exit_price"], 6),
                 round(row["realized_r"], 9)) for row in rows}

    admitted = describe_stream(delta.added)
    withdrawn = describe_stream(delta.displaced)
    for node in (admitted, withdrawn):
        node.pop("months", None)
    return {
        "baseline": summarise(base), "lead": summarise(lead),
        "admitted": admitted, "withdrawn": withdrawn,
        "net_delta_r": (sum(row["realized_r"] for row in lead.trade_log)
                        - sum(row["realized_r"] for row in base.trade_log)),
        "a4_trade_set_unchanged": identity(longs_base) == identity(longs_lead),
        "a4_trades": len(longs_base),
        "contention": {
            "baseline_core_is_union": identity(base.trade_log) == (
                identity(longs_base) | identity(standalone_base.trade_log)),
            "lead_core_is_union": identity(lead.trade_log) == (
                identity(longs_lead) | identity(standalone_lead.trade_log)),
            "baseline_lost": len((identity(longs_base) | identity(standalone_base.trade_log))
                                 - identity(base.trade_log)),
            "lead_lost": len((identity(longs_lead) | identity(standalone_lead.trade_log))
                             - identity(lead.trade_log)),
        },
    }


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.write_text(json.dumps(run_phase_c(args.ledger), default=str, indent=1))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
