"""Phase 4E: segment-local, development-first Setup B entry-quality research.

Run `development` first. It writes all one-factor and predefined-combination
results, then freezes at most three candidates. Only `validation` reads later
BTC candles. Neither mode modifies the active strategy or generic engine.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import pandas as pd

from engine.models import BacktestSettings, Direction, Signal
from research.segment_aware_baseline import warmup_plan, run_independent_segment
from strategies.btc_v2_setup_b import BtcV2SetupB, SetupBParameters
from utils.data_validation import continuous_segments, prepare_ohlcv

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/btcusd_15m.csv"
DIAGNOSTICS = ROOT / "reports/diagnostics/setup_b/trade_diagnostics.csv"
OUT = ROOT / "reports/research/setup_b_entry"
BOUNDARY = pd.Timestamp("2025-01-01", tz="UTC")
SETTINGS = BacktestSettings(risk_percent=.25, risk_reward_ratio=3., commission_percent=.05)
ORIGINAL = SetupBParameters()
FACTOR_LEVELS = {
    "minimum_adx": [18, 20, 22, 25, 28, 30],
    "maximum_extension_atr": [2.50, 2.25, 2.00, 1.75, 1.50, 1.25],
    "minimum_body_percent": [.50, .55, .60, .65, .70, .75],
    "minimum_range_atr": [.60, .75, .90, 1.05, 1.20],
    "maximum_range_atr": [2.75, 2.50, 2.25, 2.00, 1.75],
    "minimum_structure_break_atr": [0., .10, .20, .30, .40, .50],
    "minimum_stop_atr": [.60, .80, 1.00, 1.20, 1.40],
    "maximum_stop_atr": [3.00, 2.75, 2.50, 2.25, 2.00],
    "long_rsi_min": [50, 52.5, 55, 57.5, 60],
    "long_rsi_max": [75, 72.5, 70, 67.5],
    "short_rsi_max": [50, 47.5, 45, 42.5, 40],
    "short_rsi_min": [25, 27.5, 30, 32.5],
}
PROPOSED = {"minimum_structure_break_atr", "minimum_h1_slope_percent"}
ALLOWED_ENTRY_FACTORS = set(FACTOR_LEVELS) | {"minimum_h1_slope_percent"}
PROTOCOL = {
    "revision": "Development-only revision: evaluate adjacent plateaus with >=250 trades; initial >=50% retention screen was stricter than requested.",
    "minimum_development_trades": 250,
    "minimum_retention_percent": 50,
    "minimum_pf_gain": .05,
    "minimum_average_r_gain": .03,
    "minimum_years_improved": 2,
    "maximum_dd_multiple": 1.25,
    "adjacent_qualifying_values": 2,
    "shortlist_minimum_retention_percent": 40,
    "shortlist_minimum_pf_gain": .02,
    "shortlist_minimum_average_r_gain": .015,
    "maximum_combinations": 5,
    "maximum_modified_factors_per_combination": 3,
    "maximum_frozen_candidates": 3,
}


@dataclass(frozen=True)
class EntrySpec:
    changes: tuple[tuple[str, float], ...] = ()

    @classmethod
    def from_dict(cls, changes: dict[str, float]) -> "EntrySpec":
        if any(key not in ALLOWED_ENTRY_FACTORS for key in changes):
            raise ValueError("Unknown entry parameter.")
        if len(changes) != len(set(changes)):
            raise ValueError("Duplicate entry parameter.")
        return cls(tuple(sorted((key, float(value)) for key, value in changes.items())))

    def as_dict(self) -> dict[str, float]:
        return dict(self.changes)

    def strategy_params(self) -> SetupBParameters:
        native = {key: value for key, value in self.changes if key not in PROPOSED}
        return replace(ORIGINAL, **native)


def entry_filter_pass(signal: Signal, candle, *, previous_high: float | None,
                      previous_low: float | None, atr: float | None,
                      h1_slope_percent: float | None,
                      minimum_structure_break_atr: float = 0.,
                      minimum_h1_slope_percent: float = 0.) -> bool:
    """Signal-close descriptors only; native V2.2 gates have already passed."""
    if minimum_structure_break_atr < 0 or minimum_h1_slope_percent < 0:
        raise ValueError("Research thresholds must be nonnegative.")
    if atr is None or atr <= 0 or h1_slope_percent is None:
        return False
    if signal.direction is Direction.LONG:
        if previous_high is None:
            return False
        distance = (candle.close - previous_high) / atr
        directional_slope = h1_slope_percent
    else:
        if previous_low is None:
            return False
        distance = (previous_low - candle.close) / atr
        directional_slope = -h1_slope_percent
    return (distance + 1e-12 >= minimum_structure_break_atr and
            directional_slope + 1e-12 >= minimum_h1_slope_percent)


class ResearchSetupB(BtcV2SetupB):
    """Additional post-signal research gates; base Setup B stays untouched."""

    def __init__(self, spec: EntrySpec):
        self.spec = spec
        super().__init__(spec.strategy_params())

    def on_candle(self, candle):
        prior = list(self.previous)
        p = self.params
        previous_high = (max(x.high for x in prior[-p.structure_lookback:])
                         if len(prior) >= p.structure_lookback else None)
        previous_low = (min(x.low for x in prior[-p.structure_lookback:])
                        if len(prior) >= p.structure_lookback else None)
        action = super().on_candle(candle)
        if not isinstance(action, Signal):
            return action
        extra = self.spec.as_dict()
        if not any(key in extra for key in PROPOSED):
            return action
        confirmed = self.h1.confirmed
        slope = ((confirmed.slow_ema - confirmed.slow_ema_lookback) /
                 confirmed.slow_ema * 100
                 if confirmed.slow_ema is not None and
                 confirmed.slow_ema_lookback is not None and confirmed.slow_ema > 0
                 else None)
        if entry_filter_pass(action, candle, previous_high=previous_high,
                             previous_low=previous_low, atr=self.atr._average.value,
                             h1_slope_percent=slope,
                             minimum_structure_break_atr=extra.get("minimum_structure_break_atr", 0.),
                             minimum_h1_slope_percent=extra.get("minimum_h1_slope_percent", 0.)):
            return action
        return None


def trade_retention(trades: int, control_trades: int) -> float:
    if control_trades <= 0:
        raise ValueError("Control must have completed trades.")
    return trades / control_trades * 100


def low_sample(trades: int) -> bool:
    return trades < PROTOCOL["minimum_development_trades"]


def _read_range(start: pd.Timestamp | None, end: pd.Timestamp | None) -> pd.DataFrame:
    """Stop CSV reading after the requested range; no forward data in development."""
    chunks = []
    for chunk in pd.read_csv(DATA, chunksize=20_000):
        times = pd.to_datetime(chunk.timestamp, utc=True)
        mask = pd.Series(True, index=chunk.index)
        if start is not None:
            mask &= times >= start
        if end is not None:
            mask &= times < end
        selected = chunk.loc[mask]
        if not selected.empty:
            chunks.append(selected)
        if end is not None and (times >= end).any():
            break
    if not chunks:
        raise ValueError("No candles in requested research range.")
    prepared, _ = prepare_ohlcv(pd.concat(chunks, ignore_index=True))
    return prepared


def _frames(data: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    result = []
    for index, segment in enumerate(continuous_segments(data), 1):
        frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        plan = warmup_plan(ORIGINAL, segment.start)
        if len(frame) >= plan.minimum_segment_candles:
            result.append((f"S{index:02d}", frame))
    return result


def _trade_rows(segment_id, trades) -> list[dict]:
    return [{"segment_id": segment_id, "trade_id": t.trade_id,
             "signal_time": t.signal_time, "exit_time": t.exit_time,
             "direction": t.direction.value, "pnl": t.pnl,
             "zero_cost_pnl": t.pnl + t.entry_commission + t.exit_commission,
             "r": t.realized_r,
             "zero_cost_r": (t.pnl + t.entry_commission + t.exit_commission) / t.initial_risk,
             "entry_notional": t.entry_price * t.quantity,
             "exit_notional": t.exit_price * t.quantity,
             "risk": t.initial_risk}
            for t in trades]


def run_spec(spec: EntrySpec, frames: list[tuple[str, pd.DataFrame]],
             *, trade_start: pd.Timestamp | None = None) -> pd.DataFrame:
    rows = []
    for segment_id, frame in frames:
        strategy = ResearchSetupB(spec)
        start = warmup_plan(strategy.params, frame.timestamp.iloc[0]).first_search_time
        if trade_start is not None:
            start = max(start, trade_start)
        result = run_independent_segment(frame, strategy, SETTINGS, start)
        if any(t.entry_time < frame.timestamp.iloc[0] or t.exit_time > frame.timestamp.iloc[-1]
               for t in result.trades):
            raise AssertionError("Entry research trade crossed a gap.")
        rows.extend(_trade_rows(segment_id, result.trades))
    return pd.DataFrame(rows, columns=["segment_id", "trade_id", "signal_time", "exit_time",
                                       "direction", "pnl", "zero_cost_pnl", "r", "zero_cost_r",
                                       "entry_notional", "exit_notional", "risk"])


def _pf(pnl: pd.Series) -> float:
    gains = pnl.loc[pnl > 0].sum()
    losses = -pnl.loc[pnl < 0].sum()
    return float(gains / losses) if losses else (float("inf") if gains else 0.)


def _worst_segment_dd(trades: pd.DataFrame) -> float:
    worst = 0.
    for _, group in trades.groupby("segment_id"):
        balance = peak = SETTINGS.starting_balance
        for pnl in group.sort_values("exit_time").pnl:
            balance += pnl
            peak = max(peak, balance)
            worst = max(worst, (peak - balance) / peak * 100)
    return worst


def _streak(trades: pd.DataFrame) -> int:
    longest = 0
    for _, group in trades.groupby("segment_id"):
        current = 0
        for pnl in group.sort_values("exit_time").pnl:
            current = current + 1 if pnl < 0 else 0
            longest = max(longest, current)
    return longest


def summarize(trades: pd.DataFrame) -> dict:
    n = len(trades)
    if not n:
        return dict(trades=0, long_trades=0, short_trades=0, win_rate_percent=0.,
                    profit_factor=0., average_r=0., expectancy_r=0., net_pnl=0.,
                    worst_segment_dd_percent=0., max_losing_streak=0,
                    zero_cost_pf=0., zero_cost_average_r=0.)
    return dict(trades=n, long_trades=int((trades.direction == "LONG").sum()),
                short_trades=int((trades.direction == "SHORT").sum()),
                win_rate_percent=float((trades.pnl > 0).mean() * 100),
                profit_factor=_pf(trades.pnl), average_r=float(trades.r.mean()),
                expectancy_r=float(trades.r.mean()), net_pnl=float(trades.pnl.sum()),
                worst_segment_dd_percent=_worst_segment_dd(trades),
                max_losing_streak=_streak(trades),
                zero_cost_pf=_pf(trades.zero_cost_pnl),
                zero_cost_average_r=float(trades.zero_cost_r.mean()))


def annual_rows(trades: pd.DataFrame, variant: str) -> list[dict]:
    result = []
    total_absolute = 0.
    parts = {}
    for year in (2021, 2022, 2023, 2024):
        part = trades.loc[pd.to_datetime(trades.signal_time).dt.year == year]
        parts[year] = summarize(part)
        total_absolute += abs(parts[year]["net_pnl"])
    for year, stats in parts.items():
        result.append({"variant": variant, "year": year, **stats,
                       "pnl_contribution_percent_of_absolute_years":
                       stats["net_pnl"] / total_absolute * 100 if total_absolute else 0.})
    return result


def directional_rows(trades: pd.DataFrame, variant: str) -> list[dict]:
    return [{"variant": variant, "direction": side,
             **summarize(trades.loc[trades.direction == side])}
            for side in ("LONG", "SHORT")]


def slope_levels() -> list[float]:
    # Phase 4C completed-trade descriptors are signal-time values. Stop before
    # validation rows; quantiles describe development completed trades only.
    values = []
    with DIAGNOSTICS.open(newline="") as source:
        reader = csv.DictReader(source)
        for row in reader:
            if pd.Timestamp(row["signal_candle_time"]) >= BOUNDARY:
                break
            values.append(abs(float(row["h1_ema200_slope_percent"])))
    levels = [0.] + [float(np.quantile(values, q)) for q in (.2, .4, .6, .8)]
    return [float(x) for x in dict.fromkeys(round(v, 8) for v in levels)]


def factor_trend(group: pd.DataFrame, control: pd.Series) -> str:
    """Plain descriptive classification; never selects a peak value alone."""
    varied = group.loc[group.value != group.original_value].reset_index(drop=True)
    if varied.empty:
        return "No varied settings"
    better = ((varied.profit_factor > control.profit_factor) &
              (varied.average_r > control.average_r)).to_numpy()
    if not better.any():
        return "No joint PF and average-R improvement"
    if better.sum() == 1:
        return "POSSIBLE OVERFIT: isolated single-value improvement"
    if (varied.loc[better, "low_sample_for_development"].mean() >= .5 or
            varied.loc[better, "trade_retention_percent"].median() < 50):
        return "Improvement largely coincides with collapsing trade count"
    adjacent = any(better[i] and better[i + 1] for i in range(len(better) - 1))
    pf = group.profit_factor.to_numpy()
    avg_r = group.average_r.to_numpy()
    if (better.all() and np.all(np.diff(pf) >= -1e-9) and
            np.all(np.diff(avg_r) >= -1e-9)):
        return "Broad monotonic improvement across tested values"
    if adjacent:
        return "Stable adjacent-value plateau; not necessarily monotonic"
    return "Unstable/non-monotonic behavior"


def _qualifies(row: pd.Series, control: pd.Series, years: pd.DataFrame,
               control_years: pd.DataFrame) -> bool:
    same = years.set_index("year").net_pnl
    base = control_years.set_index("year").net_pnl
    return bool(
        row.trades >= PROTOCOL["minimum_development_trades"] and
        row.trade_retention_percent >= PROTOCOL["minimum_retention_percent"] and
        row.profit_factor >= control.profit_factor + PROTOCOL["minimum_pf_gain"] and
        row.average_r >= control.average_r + PROTOCOL["minimum_average_r_gain"] and
        row.worst_segment_dd_percent <= control.worst_segment_dd_percent *
            PROTOCOL["maximum_dd_multiple"] and
        int((same > base).sum()) >= PROTOCOL["minimum_years_improved"])


def shortlist_factors(one: pd.DataFrame, years: pd.DataFrame) -> list[dict]:
    control = one.loc[(one.parameter == "Control")].iloc[0]
    control_years = years.loc[years.variant == "CONTROL"]
    selected = []
    for parameter in FACTOR_LEVELS | {"minimum_h1_slope_percent": []}:
        group = one.loc[one.parameter == parameter].reset_index(drop=True)
        qualified = []
        for _, r in group.iterrows():
            own_years = years.loc[years.variant == r.variant].set_index("year").net_pnl
            baseline_years = control_years.set_index("year").net_pnl
            qualified.append(bool(
                r.trades >= PROTOCOL["minimum_development_trades"] and
                r.trade_retention_percent >= PROTOCOL["shortlist_minimum_retention_percent"] and
                r.profit_factor >= control.profit_factor + PROTOCOL["shortlist_minimum_pf_gain"] and
                r.average_r >= control.average_r + PROTOCOL["shortlist_minimum_average_r_gain"] and
                r.worst_segment_dd_percent <= control.worst_segment_dd_percent *
                    PROTOCOL["maximum_dd_multiple"] and
                int((own_years > baseline_years).sum()) >= PROTOCOL["minimum_years_improved"]
            ))
        adjacent = [i for i in range(1, len(group) - 1)
                    if qualified[i] and (qualified[i - 1] or qualified[i + 1])]
        if not adjacent:
            continue
        # Choose the nearest original threshold within a qualifying plateau.
        index = min(adjacent)
        selected.append({"parameter": parameter, "value": float(group.iloc[index].value),
                         "variant": group.iloc[index].variant,
                         "evidence": "adjacent qualifying development settings"})
    return selected


def predefined_combinations(shortlist: list[dict]) -> list[dict]:
    """Fixed factor order; no Cartesian search or post-result substitution."""
    factors = shortlist[:3]
    if len(factors) < 2:
        return []
    pairs = [(0, 1)] if len(factors) == 2 else [(0, 1), (0, 2), (1, 2), (0, 1, 2)]
    return [{"id": f"C{i}", "changes": {factors[j]["parameter"]: factors[j]["value"]
                                       for j in pair}} for i, pair in enumerate(pairs[:5], 1)]


def freeze_candidates(path: Path, candidates: list[dict], source_sha256: str) -> None:
    if path.exists():
        raise FileExistsError("Frozen candidates already exist; refusing overwrite.")
    if len(candidates) > PROTOCOL["maximum_frozen_candidates"]:
        raise ValueError("Too many frozen candidates.")
    payload = {"protocol": PROTOCOL, "development_source_sha256": source_sha256,
               "development_cutoff_utc": str(BOUNDARY), "candidates": candidates}
    encoded = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(encoded)
    path.with_suffix(".sha256").write_text(hashlib.sha256(encoded).hexdigest() + "\n")


def read_frozen_candidates(path: Path) -> dict:
    raw = path.read_bytes()
    expected = path.with_suffix(".sha256").read_text().strip()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("Frozen candidate file changed after development selection.")
    return json.loads(raw)


def _source_digest() -> str:
    return hashlib.sha256(DATA.read_bytes()).hexdigest()


def run_development() -> None:
    if (OUT / "frozen_candidates.json").exists():
        raise FileExistsError("Development candidates are already frozen.")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "research_protocol.json").write_text(json.dumps(PROTOCOL, indent=2) + "\n")
    frames = _frames(_read_range(None, BOUNDARY))
    control_trades = run_spec(EntrySpec(), frames)
    control = summarize(control_trades)
    if control["trades"] != 639:
        raise AssertionError(f"Development control changed: {control['trades']} != 639.")
    levels = {**FACTOR_LEVELS, "minimum_h1_slope_percent": slope_levels()}
    (OUT / "tested_levels.json").write_text(json.dumps(levels, indent=2) + "\n")
    one_rows, year_rows, side_rows = [], [], []

    def record(parameter, value, original_value, variant, trades):
        stats = summarize(trades)
        years = annual_rows(trades, variant)
        one_rows.append({"parameter": parameter, "value": value,
                         "original_value": original_value, "variant": variant,
                         **stats,
                         "trade_retention_percent": trade_retention(stats["trades"], control["trades"]),
                         "low_sample_for_development": low_sample(stats["trades"]),
                         "positive_expectancy_years": sum(y["average_r"] > 0 for y in years),
                         "negative_expectancy_years": sum(y["average_r"] < 0 for y in years),
                         **{f"{y['year']}_pf": y["profit_factor"] for y in years},
                         **{f"{y['year']}_average_r": y["average_r"] for y in years}})
        year_rows.extend(years)
        side_rows.extend(directional_rows(trades, variant))

    record("Control", 0., 0., "CONTROL", control_trades)
    for parameter, values in levels.items():
        original = values[0]
        for index, value in enumerate(values):
            variant = f"{parameter}={value:g}"
            trades = (control_trades if index == 0 else
                      run_spec(EntrySpec.from_dict({parameter: value}), frames))
            record(parameter, value, original, variant, trades)
    one = pd.DataFrame(one_rows)
    years = pd.DataFrame(year_rows)
    sides = pd.DataFrame(side_rows)
    one.to_csv(OUT / "one_factor_sensitivity.csv", index=False)
    years.to_csv(OUT / "year_stability.csv", index=False)
    sides.to_csv(OUT / "direction_analysis.csv", index=False)
    shortlist = shortlist_factors(one, years)
    combinations = predefined_combinations(shortlist)
    (OUT / "predefined_combinations.json").write_text(json.dumps(combinations, indent=2) + "\n")
    combo_rows = []
    for combination in combinations:
        trades = run_spec(EntrySpec.from_dict(combination["changes"]), frames)
        stats = summarize(trades)
        combo_rows.append({"variant": combination["id"],
                           "changes": json.dumps(combination["changes"], sort_keys=True),
                           **stats, "trade_retention_percent":
                           trade_retention(stats["trades"], control["trades"]),
                           "low_sample_for_development": low_sample(stats["trades"])})
        year_rows.extend(annual_rows(trades, combination["id"]))
        side_rows.extend(directional_rows(trades, combination["id"]))
    pd.DataFrame(combo_rows, columns=["variant", "changes", *control.keys(),
                                      "trade_retention_percent",
                                      "low_sample_for_development"]).to_csv(
        OUT / "combination_development.csv", index=False)
    pd.DataFrame(year_rows).to_csv(OUT / "year_stability.csv", index=False)
    pd.DataFrame(side_rows).to_csv(OUT / "direction_analysis.csv", index=False)
    # Candidate rule is fixed in the protocol. Prefer qualifying combinations,
    # then qualifying single factors, retaining factor order, not highest PF.
    candidates = []
    for combination in combinations:
        row = next(r for r in combo_rows if r["variant"] == combination["id"])
        yearly = pd.DataFrame(year_rows)
        if _qualifies(pd.Series(row), one.iloc[0],
                      yearly.loc[yearly.variant == combination["id"]],
                      yearly.loc[yearly.variant == "CONTROL"]):
            candidates.append(combination)
    for item in shortlist:
        row = one.loc[one.variant == item["variant"]].iloc[0]
        yearly = pd.DataFrame(year_rows)
        if _qualifies(row, one.iloc[0],
                      yearly.loc[yearly.variant == item["variant"]],
                      yearly.loc[yearly.variant == "CONTROL"]):
            candidates.append({"id": item["variant"],
                               "changes": {item["parameter"]: item["value"]}})
    candidates = candidates[:PROTOCOL["maximum_frozen_candidates"]]
    freeze_candidates(OUT / "frozen_candidates.json", candidates, _source_digest())
    trends = {name: factor_trend(one.loc[one.parameter == name], one.iloc[0])
              for name in levels}
    summary = {"checkpoint": "btc-v2-exit-research-v1.0", "control": control,
               "shortlist": shortlist, "combinations": combinations,
               "frozen_candidates": candidates, "factor_trends": trends,
               "development_candles": int(sum(len(frame) for _, frame in frames)),
               "development_segments": len(frames), "protocol": PROTOCOL}
    (OUT / "development_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    _write_summary(summary)


def run_validation() -> None:
    frozen = read_frozen_candidates(OUT / "frozen_candidates.json")
    if frozen["protocol"] != PROTOCOL or frozen["development_source_sha256"] != _source_digest():
        raise ValueError("Frozen protocol or source dataset changed.")
    # This is the first code path that loads 2025–2026 candles/results.
    frames = [(sid, frame) for sid, frame in _frames(_read_range(None, None))
              if frame.timestamp.iloc[-1] >= BOUNDARY]
    control = run_spec(EntrySpec(), frames, trade_start=BOUNDARY)
    rows = []
    for candidate in [{"id": "CONTROL", "changes": {}}, *frozen["candidates"]]:
        trades = control if candidate["id"] == "CONTROL" else run_spec(
            EntrySpec.from_dict(candidate["changes"]), frames, trade_start=BOUNDARY)
        rows.append({"variant": candidate["id"], "changes": json.dumps(candidate["changes"]),
                     **summarize(trades)})
        for side in ("LONG", "SHORT"):
            part = trades.loc[trades.direction == side]
            rows.append({"variant": candidate["id"], "changes": json.dumps(candidate["changes"]),
                         "direction": side, **summarize(part)})
    pd.DataFrame(rows).to_csv(OUT / "forward_validation.csv", index=False)
    _write_cost_crosscheck(frozen, frames, control)
    summary = json.loads((OUT / "development_summary.json").read_text())
    summary["forward_validation"] = rows
    (OUT / "validation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    _write_summary(summary)


def _write_cost_crosscheck(frozen: dict, frames, control) -> None:
    rows = []
    rates = {"Current": .05, "0.01%": .01, "0.025%": .025,
             "0.05%": .05, "Zero": 0.}
    for candidate in [{"id": "CONTROL", "changes": {}}, *frozen["candidates"]]:
        trades = control if candidate["id"] == "CONTROL" else run_spec(
            EntrySpec.from_dict(candidate["changes"]), frames, trade_start=BOUNDARY)
        for label, rate in rates.items():
            copy = trades.copy()
            gross = copy.zero_cost_pnl
            fee = (copy.entry_notional + copy.exit_notional) * rate / 100
            copy["pnl"] = gross - fee
            copy["r"] = copy.pnl / copy.risk
            rows.append({"variant": candidate["id"], "cost_scenario": label,
                         "commission_percent_per_side": rate,
                         **summarize(copy)})
    pd.DataFrame(rows).to_csv(OUT / "cost_crosscheck.csv", index=False)


def _write_summary(summary: dict) -> None:
    lines = ["# Setup B entry-quality research", "",
             "**RESEARCH ONLY — active Setup B remains at original V2.2 defaults and fixed 3R.**", "",
             "All one-factor and combination selection used only 2021–2024 candles. "
             "The frozen candidate file was written before any 2025–2026 run.", "",
             "Protocol note: the initial mechanical screen required at least 50% retention "
             "for a factor shortlist and produced no shortlist. Before viewing forward data, "
             "the screen was revised to admit adjacent development plateaus with at least "
             "250 trades and 40% retention; the initial result and protocol are archived "
             "in this folder. Final candidate qualification still uses the stricter rule.", "",
             "Segments reset account, indicators, pending orders and positions; no data gap is bridged.", "",
             "H1 slope levels are quantiles of the absolute normalized signal-time H1 EMA200 slope "
             "among Phase 4C development completed trades. Long and short use the same magnitude threshold.", "",
             "## Development control", "",
             "| Trades | PF | Avg R | Net PnL $ | Worst segment DD % | Zero-cost PF |",
             "|---:|---:|---:|---:|---:|---:|",
             f"| {summary['control']['trades']} | {summary['control']['profit_factor']:.3f} | "
             f"{summary['control']['average_r']:.3f} | {summary['control']['net_pnl']:.2f} | "
             f"{summary['control']['worst_segment_dd_percent']:.2f} | "
             f"{summary['control']['zero_cost_pf']:.3f} |", "",
             "## Factor trends", "",
             *[f"- {key}: {value}" for key, value in summary["factor_trends"].items()], "",
             "## Shortlist", "",
             *[f"- {item['parameter']} = {item['value']:.6g}: {item['evidence']}"
               for item in summary["shortlist"]], "",
             "## Predefined combinations", "",
             *[f"- {item['id']}: {json.dumps(item['changes'], sort_keys=True)}"
               for item in summary["combinations"]], "",
             "## Development combinations", "",
             "| Model | Trades | Retention % | WR % | PF | Avg R | Net PnL $ | Worst segment DD % | Low sample |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---|",
             *[f"| {row.variant} | {row.trades} | {row.trade_retention_percent:.1f} | "
               f"{row.win_rate_percent:.2f} | {row.profit_factor:.3f} | "
               f"{row.average_r:.3f} | {row.net_pnl:.2f} | "
               f"{row.worst_segment_dd_percent:.2f} | {row.low_sample_for_development} |"
               for row in pd.read_csv(OUT / "combination_development.csv").itertuples(index=False)], "",
             "## Frozen candidates", "",
             *[f"- {item['id']}: {json.dumps(item['changes'], sort_keys=True)}"
               for item in summary["frozen_candidates"]], "",
             "The forward-validation set was previously viewed in aggregate and is not a pristine holdout."]
    if "forward_validation" in summary:
        lines += ["", "## Forward validation · current costs", "",
                  "| Model | Side | Trades | WR % | PF | Avg R | Net PnL $ | Worst segment DD % |",
                  "|---|---|---:|---:|---:|---:|---:|---:|",
                  *[f"| {row['variant']} | {row.get('direction', 'All')} | {row['trades']} | "
                    f"{row['win_rate_percent']:.2f} | {row['profit_factor']:.3f} | "
                    f"{row['average_r']:.3f} | {row['net_pnl']:.2f} | "
                    f"{row['worst_segment_dd_percent']:.2f} |"
                    for row in summary["forward_validation"]], "",
                  "Cost sensitivity uses the same forward trades and exits under alternate commissions; "
                  "see `cost_crosscheck.csv`. Zero cost is diagnostic context only."]
    (OUT / "entry_research_summary.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["development", "validation"])
    args = parser.parse_args()
    run_development() if args.phase == "development" else run_validation()
