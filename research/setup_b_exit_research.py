"""Frozen-entry, segment-local exit and cost research. Never invokes strategy signals.

Counterfactual exits may overlap later frozen entries. Accordingly, trade PnL and
segment-local drawdowns are descriptive and are not a feasible compounded backtest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.setup_b_failure_diagnostics import breakeven_win_rate
from services.history import CANONICAL_DATA_FILE
from utils.data_validation import load_ohlcv_csv

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports/diagnostics/setup_b/trade_diagnostics.csv"
SEGMENTS = ROOT / "reports/long_history/segment_aware/all_segments.csv"
OUTPUT = ROOT / "reports/research/setup_b_exit"
CURRENT_FEE = 0.05  # percent per side, frozen baseline
START_BALANCE = 10_000.0
MODELS = {
    "E0": (3.0, None, False),
    "E1": (2.0, None, False),
    "E2": (1.5, None, False),
    "E3": (3.0, 1.0, False),
    "E4": (3.0, 1.5, False),
    "E5": (3.0, None, True),
    "E6": (3.0, 1.0, True),
    "E7": (2.0, 1.0, False),
}
SCENARIOS = {"A Current": 0.05, "B Zero": 0.0, "C 0.01%": 0.01,
             "D 0.025%": 0.025, "E 0.05%": 0.05, "F 0.10%": 0.10}


def research_set(signal_time) -> str:
    time = pd.Timestamp(signal_time)
    if time.tzinfo is None:
        raise ValueError("Signal time must be timezone aware.")
    return "development" if time.tz_convert("UTC") < pd.Timestamp("2025-01-01", tz="UTC") else "forward-validation"


def cost_reprice(trades: pd.DataFrame, fee_percent: float) -> pd.DataFrame:
    """Keep actual fill/exit prices, quantity and planned risk unchanged."""
    result = trades.copy()
    result["costs"] = (result.entry_price * result.quantity +
                       result.exit_notional) * fee_percent / 100
    result["net_pnl"] = result.gross_pnl - result.costs
    result["realized_r"] = result.net_pnl / result.planned_risk
    return result


def _event(row, candles: pd.DataFrame, model: str) -> dict | None:
    """Resolve one frozen fill using stop-first, conservative intrabar ordering.

    A newly activated BE stop wins over a target touched on the same candle.
    Initial stop wins over activation/partial whenever both are touched.
    """
    target_r, be_at, partial = MODELS[model]
    sign = 1 if row.direction == "LONG" else -1
    entry = float(row.actual_fill_price)
    initial_stop = float(row.structural_stop)
    risk = abs(entry - initial_stop)
    quantity = float(row.quantity_recovered)
    entry_time = pd.Timestamp(row.entry_time)
    if risk <= 0 or quantity <= 0:
        raise ValueError("Frozen entry has invalid risk or quantity.")
    target = entry + sign * target_r * risk
    activation = entry + sign * (be_at or 1.0) * risk
    stop = initial_stop
    remaining = 1.0
    legs: list[tuple[float, float, str]] = []
    activated = False
    entry_bar = candles.index.get_loc(entry_time)
    for offset, candle in enumerate(candles.iloc[entry_bar:].itertuples()):
        open_price, high, low = float(candle.open), float(candle.high), float(candle.low)
        entered_intrabar = offset == 0 and not bool(row.gap_through_trigger)
        if sign == 1:
            gap_stop = open_price <= stop
            gap_target = open_price >= target
            stop_hit = low <= stop
            target_hit = high >= target
            activation_hit = high >= activation
        else:
            gap_stop = open_price >= stop
            gap_target = open_price <= target
            stop_hit = high >= stop
            target_hit = low <= target
            activation_hit = low <= activation

        # Opening gaps use audited engine convention; no pre-fill gap check.
        if not entered_intrabar and gap_stop:
            legs.append((remaining, open_price, "stop opening gap"))
        elif not entered_intrabar and gap_target:
            if partial and remaining == 1.0:
                legs.append((0.5, activation, "partial 1R"))
                remaining = 0.5
            legs.append((remaining, target, "target opening gap"))
        elif stop_hit:
            legs.append((remaining, stop, "breakeven" if activated else "stop"))
        else:
            # Crossing a trigger and the old stop in one bar was handled above.
            if activation_hit and partial and remaining == 1.0:
                legs.append((0.5, activation, "partial 1R"))
                remaining = 0.5
            if activation_hit and be_at is not None and not activated:
                activated = True
                stop = entry  # price breakeven; transaction costs remain payable
                be_touched = low <= stop if sign == 1 else high >= stop
                if be_touched:
                    legs.append((remaining, stop, "breakeven same bar"))
            if not legs or sum(weight for weight, _, _ in legs) < 1 - 1e-9:
                if target_hit:
                    legs.append((remaining, target, "target"))
        if sum(weight for weight, _, _ in legs) >= 1 - 1e-9:
            gross = sum(sign * (price - entry) * quantity * weight
                        for weight, price, _ in legs)
            exit_notional = sum(price * quantity * weight for weight, price, _ in legs)
            costs = (entry * quantity + exit_notional) * CURRENT_FEE / 100
            net = gross - costs
            return {
                "segment_id": row.segment_id, "trade_id": int(row.trade_id),
                "model": model, "set": research_set(row.signal_candle_time),
                "signal_time": row.signal_time, "direction": row.direction,
                "pending_trigger": row.pending_trigger_price,
                "entry_time": row.entry_time, "entry_price": entry,
                "initial_stop": initial_stop, "quantity": quantity,
                "planned_risk": float(row.planned_risk_dollars),
                "exit_time": candle.Index, "exit_price": legs[-1][1],
                "exit_reason": legs[-1][2], "partial": partial and len(legs) > 1,
                "gross_pnl": gross, "exit_notional": exit_notional,
                "costs": costs, "net_pnl": net,
                "realized_r": net / float(row.planned_risk_dollars),
                "bars_held": offset + 1,
                "full_stop": len(legs) == 1 and legs[0][2].startswith("stop"),
                "breakeven_exit": "breakeven" in legs[-1][2],
            }
    return None  # position remains open at segment end, excluded from completed PnL


def simulate_model(entries: pd.DataFrame, candles_by_segment: dict[str, pd.DataFrame],
                   model: str) -> tuple[pd.DataFrame, list[tuple[str, int]]]:
    if model not in MODELS:
        raise ValueError(model)
    results, open_at_end = [], []
    for row in entries.itertuples(index=False):
        outcome = _event(row, candles_by_segment[row.segment_id], model)
        if outcome is None:
            open_at_end.append((row.segment_id, int(row.trade_id)))
        else:
            results.append(outcome)
    frame = pd.DataFrame(results)
    if not frame.empty:
        frozen = entries[["segment_id", "trade_id", "signal_time", "direction",
                          "pending_trigger_price", "entry_time", "actual_fill_price",
                          "structural_stop", "quantity_recovered", "planned_risk_dollars"]]
        check = frame.merge(frozen, on=["segment_id", "trade_id"], validate="one_to_one")
        if len(check) != len(frame):
            raise AssertionError("Experiment introduced a non-frozen entry.")
        for result_field, source_field in (("entry_price", "actual_fill_price"),
                                            ("initial_stop", "structural_stop"),
                                            ("pending_trigger", "pending_trigger_price"),
                                            ("quantity", "quantity_recovered"),
                                            ("planned_risk", "planned_risk_dollars")):
            if not np.allclose(check[result_field], check[source_field], atol=1e-8):
                raise AssertionError(f"Experiment changed frozen {result_field}.")
        if not (check.signal_time_x.astype(str).values == check.signal_time_y.astype(str).values).all():
            raise AssertionError("Experiment changed frozen signal time.")
        if not (check.direction_x.values == check.direction_y.values).all():
            raise AssertionError("Experiment changed frozen direction.")
        if not (check.entry_time_x.astype(str).values == check.entry_time_y.astype(str).values).all():
            raise AssertionError("Experiment changed frozen fill time.")
    return frame, open_at_end


def max_dd_percent(frame: pd.DataFrame) -> float:
    """Descriptive DD; invoke only on one continuous segment or year/segment."""
    balance = peak = START_BALANCE
    worst = 0.0
    for pnl in frame.sort_values("exit_time").net_pnl:
        balance += pnl
        peak = max(peak, balance)
        worst = max(worst, (peak - balance) / peak * 100)
    return worst


def _streak(values) -> int:
    run = maximum = 0
    for value in values:
        run = run + 1 if value < 0 else 0
        maximum = max(maximum, run)
    return maximum


def metrics(frame: pd.DataFrame, *, drawdown: bool = True) -> dict:
    n = len(frame)
    wins = int((frame.net_pnl > 1e-9).sum()) if n else 0
    losses = int((frame.net_pnl < -1e-9).sum()) if n else 0
    gains = float(frame.loc[frame.net_pnl > 0, "net_pnl"].sum()) if n else 0.0
    losses_cash = float(frame.loc[frame.net_pnl < 0, "net_pnl"].sum()) if n else 0.0
    return {
        "trades": n, "wins": wins, "losses": losses,
        "breakeven": n - wins - losses,
        "win_rate_percent": wins / n * 100 if n else 0.0,
        "gross_pnl": float(frame.gross_pnl.sum()) if n else 0.0,
        "costs": float(frame.costs.sum()) if n else 0.0,
        "net_pnl": float(frame.net_pnl.sum()) if n else 0.0,
        "profit_factor": gains / abs(losses_cash) if losses_cash else (float("inf") if gains else 0.0),
        "average_r": float(frame.realized_r.mean()) if n else 0.0,
        "median_r": float(frame.realized_r.median()) if n else 0.0,
        "expectancy_r": float(frame.realized_r.mean()) if n else 0.0,
        "max_dd_percent": (max((max_dd_percent(g) for _, g in frame.groupby("segment_id")),
                               default=0.0) if drawdown and n else 0.0),
        "maximum_consecutive_losses": (max((_streak(g.sort_values("exit_time").net_pnl)
                                            for _, g in frame.groupby("segment_id")),
                                          default=0) if n else 0),
        "average_bars_held": float(frame.bars_held.mean()) if n else 0.0,
        "full_stop_percent": float(frame.full_stop.mean() * 100) if n else 0.0,
        "breakeven_exit_percent": float(frame.breakeven_exit.mean() * 100) if n else 0.0,
        "partial_exit_percent": float(frame.partial.mean() * 100) if n else 0.0,
    }


def _load_sources() -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    entries = pd.read_csv(SOURCE, parse_dates=["signal_time", "signal_candle_time", "entry_time", "exit_time"])
    segments = pd.read_csv(SEGMENTS, parse_dates=["start", "end"])
    candles = load_ohlcv_csv(CANONICAL_DATA_FILE).set_index("timestamp")
    groups = {s.segment_id: candles.loc[s.start:s.end]
              for s in segments.itertuples(index=False) if bool(s.usable)}
    assert len(entries) == 955 and len(groups) == 21
    return entries, groups


def _source_digest() -> str:
    return hashlib.sha256(SOURCE.read_bytes()).hexdigest()


def possible_mfe_reach(entries: pd.DataFrame,
                       candles_by_segment: dict[str, pd.DataFrame]) -> dict[str, float]:
    """OHLC upper bound: extremes on fill and exit bars may be out of sequence."""
    counts = {threshold: 0 for threshold in (1., 1.5, 2., 3.)}
    for row in entries.itertuples(index=False):
        bars = candles_by_segment[row.segment_id].loc[row.entry_time:row.exit_time]
        sign = 1 if row.direction == "LONG" else -1
        extreme = bars.high.max() if sign == 1 else bars.low.min()
        possible_r = max(0., sign * (extreme - row.actual_fill_price) /
                         row.actual_risk_distance)
        for threshold in counts:
            counts[threshold] += possible_r + 1e-9 >= threshold
    return {f"{key:g}R": value / len(entries) * 100 for key, value in counts.items()}


def development_robust_models(dev: pd.DataFrame, yearly: pd.DataFrame) -> list[str]:
    """Predeclared development-only screen; forward rows are never an input."""
    e0_dd = float(dev.loc[dev.model == "E0", "max_dd_percent"].iloc[0])
    selected = []
    for row in dev.itertuples(index=False):
        years = yearly.loc[yearly.model == row.model]
        if (row.trades >= 100 and row.average_r > 0 and row.profit_factor > 1
                and (years.net_pnl > 0).sum() >= 2
                and row.max_dd_percent <= 1.25 * e0_dd):
            selected.append(row.model)
    return selected


def run() -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    entries, candles = _load_sources()
    full_control, full_control_open = simulate_model(entries, candles, "E0")
    full_check = full_control.merge(entries, on=["segment_id", "trade_id"], validate="one_to_one")
    if full_control_open or len(full_check) != len(entries) or not np.allclose(
            full_check.net_pnl_x, full_check.net_pnl_y, atol=1e-7):
        raise AssertionError("Full-history E0 differs from the frozen completed baseline.")
    if (not np.allclose(full_check.exit_price_x, full_check.exit_price_y, atol=1e-8)
            or not (pd.to_datetime(full_check.exit_time_x) ==
                    pd.to_datetime(full_check.exit_time_y)).all()
            or not (full_check.bars_held_x == full_check.bars_held_y).all()):
        raise AssertionError("Full-history E0 exit execution differs from baseline.")
    outcomes, open_positions = {}, {}
    # Entire fixed-entry simulation is performed before validation is inspected.
    for model in MODELS:
        frame, still_open = simulate_model(entries.loc[entries.signal_candle_time <
                    pd.Timestamp("2025-01-01", tz="UTC")], candles, model)
        outcomes[model] = frame
        open_positions[model] = still_open
    control = outcomes["E0"]
    frozen_dev = entries.loc[entries.signal_candle_time < pd.Timestamp("2025-01-01", tz="UTC")]
    merged = control.merge(frozen_dev, on=["segment_id", "trade_id"], validate="one_to_one")
    if len(merged) != len(frozen_dev) or not np.allclose(merged.net_pnl_x, merged.net_pnl_y, atol=1e-7):
        raise AssertionError("E0 does not exactly reconcile to the frozen completed baseline.")
    if not all(pd.to_datetime(merged.exit_time_x) == pd.to_datetime(merged.exit_time_y)):
        raise AssertionError("E0 exit times differ from frozen baseline.")

    development = []
    yearly = []
    direction_rows = []
    for model, frame in outcomes.items():
        development.append({"model": model, **metrics(frame),
                            "frozen_entries": len(frozen_dev),
                            "open_at_segment_end": len(open_positions[model])})
        for year in (2021, 2022, 2023, 2024):
            subset = frame.loc[pd.to_datetime(frame.signal_time).dt.year == year]
            yearly.append({"model": model, "year": year, **metrics(subset)})
        for direction in ("LONG", "SHORT"):
            direction_rows.append({"model": model, "direction": direction,
                                   **metrics(frame.loc[frame.direction == direction])})
    dev = pd.DataFrame(development)
    year_df = pd.DataFrame(yearly)
    # Predeclared research label: >=100 trades, PF and expectancy positive,
    # >=2 profitable calendar years, worst segment DD <= 1.25x control.
    robust = development_robust_models(dev, year_df)
    dev["development_robust"] = dev.model.isin(robust)
    dev.to_csv(OUTPUT / "development_exit_models.csv", index=False)
    year_df.to_csv(OUTPUT / "development_yearly.csv", index=False)
    pd.DataFrame(direction_rows).to_csv(OUTPUT / "development_long_short.csv", index=False)

    # Only the preselected robust candidates are evaluated on validation.
    forward_entries = entries.loc[entries.signal_candle_time >= pd.Timestamp("2025-01-01", tz="UTC")]
    forward_rows = []
    for model in robust:
        frame, open_end = simulate_model(forward_entries, candles, model)
        forward_rows.append({"model": model, **metrics(frame),
                             "frozen_entries": len(forward_entries),
                             "open_at_segment_end": len(open_end)})
    forward = pd.DataFrame(forward_rows, columns=list(dev.columns)) if not forward_rows else pd.DataFrame(forward_rows)
    forward.to_csv(OUTPUT / "forward_validation.csv", index=False)

    # E0 cost table is original historical entries AND exits across all years.
    original = pd.DataFrame({
        "entry_price": entries.actual_fill_price,
        "quantity": entries.quantity_recovered,
        "exit_notional": entries.exit_price * entries.quantity_recovered,
        "gross_pnl": entries.gross_price_movement_pnl,
        "planned_risk": entries.planned_risk_dollars,
    })
    cost_rows = []
    for name, rate in SCENARIOS.items():
        repriced = cost_reprice(original, rate)
        summary = metrics(repriced.assign(segment_id=entries.segment_id.values,
                        exit_time=entries.exit_time.values, bars_held=entries.bars_held.values,
                        full_stop=False, breakeven_exit=False, partial=False), drawdown=False)
        winners = repriced.loc[repriced.realized_r > 0, "realized_r"]
        losers = repriced.loc[repriced.realized_r < 0, "realized_r"]
        cost_rows.append({"scenario": name, "commission_percent_per_side": rate,
                          **summary, "required_breakeven_wr_percent":
                          breakeven_win_rate(winners.mean(), losers.mean())
                          if len(winners) and len(losers) else None})
    costs = pd.DataFrame(cost_rows)
    costs.to_csv(OUTPUT / "cost_sensitivity.csv", index=False)
    cross = []
    for model in ["E0", *[m for m in robust if m != "E0"]]:
        current = (full_control if model == "E0" else
                   pd.concat([outcomes[model], simulate_model(forward_entries, candles, model)[0]],
                             ignore_index=True))
        for name in ("A Current", "B Zero", "C 0.01%", "D 0.025%"):
            priced = cost_reprice(current, SCENARIOS[name])
            cross.append({"model": model, "scenario": name,
                          **metrics(priced)})
    pd.DataFrame(cross).to_csv(OUTPUT / "cost_exit_cross_check.csv", index=False)

    # Phase 4C conservative measured excursions are known-after-fill reach
    # rates; they are a lower bound on possible intrabar reach, not an upper.
    reach = {f"{threshold:g}R": float(entries[f"reached_{threshold:g}r"].mean() * 100)
             for threshold in (1., 1.5, 2., 3.)}
    possible_reach = possible_mfe_reach(entries, candles)
    summary = {"source_sha256": _source_digest(), "source_entries": len(entries),
               "development_entries": len(frozen_dev), "forward_entries": len(forward_entries),
               "development_robust": robust, "mfe_conservative_reach_percent": reach,
               "mfe_possible_upper_bound_percent": possible_reach,
               "development": dev.to_dict("records"),
               "forward": forward.to_dict("records"),
               "cost_sensitivity": costs.to_dict("records"),
               "direction": direction_rows, "open_at_segment_end": open_positions,
               "counterfactual_note": "Fixed frozen entries can overlap after exit changes; no continuous compounded equity curve."}
    (OUTPUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    _write_markdown(summary, entries)
    return summary


def _write_markdown(summary: dict, entries: pd.DataFrame) -> None:
    commission = entries.commission_cost
    risk = entries.planned_risk_dollars
    notional = entries.actual_fill_price * entries.quantity_recovered
    audit = f"""# Frozen Setup B cost audit

Baseline: 955 completed frozen trades. Entry and exit prices, quantities, and planned risk are held fixed in cost repricing.

- Commission: **0.05% per side**, entry notional `entry fill × BTC quantity`, exit notional `exit fill × BTC quantity`.
- Formula: `(entry fill × quantity + exit fill × quantity) × 0.0005`.
- Charged on entry and exit. No minimum commission.
- Slippage: **0%**. Engine can worsen entry and exit by a configured percent; current baseline has none.
- Spread: no separate spread model. Market OHLC candles do not represent bid/ask.
- Average entry notional: ${notional.mean():,.2f}; median ${notional.median():,.2f}.
- Average round-trip commission: ${commission.mean():,.2f}; median ${commission.median():,.2f}.
- Average commission as percentage of planned risk: {(commission / risk).mean() * 100:.2f}%.
- Commission drag: {(commission / risk).mean():.4f}R/trade; slippage drag 0R/trade.

Cost scenarios reprice the same historical fills and exits. They do not resize positions or model a new spread. This isolates fees but is not an execution-quality forecast.
"""
    (OUTPUT / "cost_audit.md").write_text(audit)
    development_lines = [
        "| Model | Trades | Wins | Losses | BE | WR % | Gross $ | Costs $ | Net $ | PF | Avg R | Median R | Worst segment DD % | Max losses | Avg bars | Full initial stop % | Price BE exits % | Partial exits % |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in summary["development"]:
        development_lines.append(
            f"| {item['model']} | {item['trades']} | {item['wins']} | {item['losses']} | "
            f"{item['breakeven']} | {item['win_rate_percent']:.2f} | "
            f"{item['gross_pnl']:.2f} | {item['costs']:.2f} | {item['net_pnl']:.2f} | "
            f"{item['profit_factor']:.3f} | {item['average_r']:.3f} | "
            f"{item['median_r']:.3f} | {item['max_dd_percent']:.2f} | "
            f"{item['maximum_consecutive_losses']} | {item['average_bars_held']:.1f} | "
            f"{item['full_stop_percent']:.1f} | {item['breakeven_exit_percent']:.1f} | "
            f"{item['partial_exit_percent']:.1f} |"
        )
    cost_lines = ["| Scenario | Fee % per side | Trades | Gross $ | Costs $ | Net $ | PF | Avg R | Required WR % |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for item in summary["cost_sensitivity"]:
        cost_lines.append(
            f"| {item['scenario']} | {item['commission_percent_per_side']:.3f} | "
            f"{item['trades']} | {item['gross_pnl']:.2f} | {item['costs']:.2f} | "
            f"{item['net_pnl']:.2f} | {item['profit_factor']:.3f} | "
            f"{item['average_r']:.3f} | {item['required_breakeven_wr_percent']:.2f} |"
        )
    lines = ["# Setup B frozen-entry exit research", "",
             "**RESEARCH ONLY — NOT ACTIVE STRATEGY.** No entry, strategy, or generic engine rule was changed.", "",
             "Development: 2021–2024. Forward-validation: 2025–latest available 2026; previously viewed summary data, not a pristine holdout.", "",
             f"Source SHA256: `{summary['source_sha256']}`. Frozen entries: {summary['source_entries']}.", "",
             "Each experiment uses the exact signal, pending trigger, actual fill, structural initial stop, direction, quantity, and planned risk of each frozen completed trade.",
             "Alternative exits may overlap other frozen entries. These are trade-level counterfactuals, not feasible account backtests. Drawdown is worst within a continuous source segment, starting at $10,000 each segment; no equity continuity across gaps.", "",
             "Opening stop gaps fill at open; opening target gaps fill at target. Intrabar stop wins over target, partial, or BE activation. A newly activated price-BE stop wins over another target on the same ambiguous candle. Partial exits charge commission on each leg; entry commission is charged once. Open positions at segment end remain open and are excluded from completed PnL.", "",
             "MFE reach sanity check: the lower bound is Phase 4C's path-known excursion. The OHLC possible upper bound includes fill/exit bar extremes that might occur before entry or after exit, so it is not an observed fillable rate.", "",
             *[f"- +{k}: lower {v:.2f}%, possible upper {summary['mfe_possible_upper_bound_percent'][k]:.2f}%" for k, v in summary["mfe_conservative_reach_percent"].items()], "",
             "## Development results", "", *development_lines, "",
             "## Original-exit cost sensitivity · full frozen history", "", *cost_lines, "",
             "Development-robust rule, fixed before viewing validation: at least 100 completed trades, average R > 0, PF > 1, positive net PnL in at least 2 development calendar years, and worst segment DD no more than 1.25× E0. This is a descriptive label, not a live recommendation.", "",
             "Development-robust models: " + (", ".join(summary["development_robust"]) or "none"), "",
             "Only these models were simulated on forward-validation after development selection. E0 full-history costs are a separate unchanged-exit sensitivity audit.", "",
             "The optional ATR trailing experiment was omitted: it requires extra path-sensitive exit state and adds a trailing parameter beyond the clean E0–E7 isolation."]
    (OUTPUT / "exit_research_summary.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    print(json.dumps(run(), default=str)[:1000])
