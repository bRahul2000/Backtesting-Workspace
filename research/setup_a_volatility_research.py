"""Research-only causal volatility gates around frozen Setup A.

Development and validation are separate commands. The development command
never runs a 2025+ candle. Validation refuses to run without a frozen file.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from engine.backtester import run_backtest
from engine.models import Signal
from research.exness_native_validation import engine_frame, price_cost_view, summarize_trades
from research.exness_setup_a_validation import PARAMS, SETTINGS, setup_a_warmup, period_worst_drawdown
from research.setup_a_regime_diagnostics import ObserveSetupA, STEP
from research.setup_b_failure_diagnostics import excursion
from services.exness_m15 import PROCESSED
from utils.data_validation import continuous_segments


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/setup_a/regime_research"
SPLIT = pd.Timestamp("2025-01-01T00:00:00Z")
FEATURES = {"atr_percent": "ATR % of price",
            "recent_volatility_24h_percent": "Recent 24h volatility %"}
PERCENTILES = (10, 20, 30, 40)


def atr_percent(atr: float, price: float) -> float:
    if atr < 0 or price <= 0:
        raise ValueError("ATR must be nonnegative and price positive.")
    return atr / price * 100


def recent_volatility(closes: pd.Series) -> float:
    """Same completed-97-close calculation used by Phase 4J."""
    values = np.asarray(closes, dtype=float)
    if len(values) < 97:
        return float("nan")
    returns = np.diff(values[-97:]) / values[-97:-1]
    return float(np.std(returns, ddof=1) * np.sqrt(96) * 100)


def development_thresholds(signals: pd.DataFrame) -> dict[str, dict[int, float]]:
    if signals.signal_candle_time.max() >= SPLIT:
        raise ValueError("Development thresholds cannot access validation signals.")
    return {feature: {percentile: float(signals[feature].quantile(percentile / 100))
                      for percentile in PERCENTILES}
            for feature in FEATURES}


def allowed(row, rules: list[dict]) -> bool:
    # Strictly above the development percentile, as specified.
    return all(pd.notna(row[rule["feature"]]) and
               float(row[rule["feature"]]) > rule["threshold"] for rule in rules)


class GatedSetupA(ObserveSetupA):
    """Suppress qualifying signals only; all Pine signal rules stay frozen."""

    def __init__(self, rules: list[dict]):
        self.rules = rules
        super().__init__(PARAMS)

    def reset(self) -> None:
        super().reset()
        self.signal_observations = []

    def on_candle(self, candle):
        action = super().on_candle(candle)
        if isinstance(action, Signal):
            descriptor = self.signal_descriptors[candle.timestamp + STEP]
            permit = allowed(descriptor, self.rules)
            self.signal_observations.append({"signal_time": candle.timestamp + STEP,
                                             **descriptor, "allowed": permit})
            return action if permit else None
        return action


def load_data(*, development_only: bool) -> pd.DataFrame:
    # The gate stage runs a truncated frame. No validation candle is passed to
    # the strategy or used in percentile calculation before candidate freeze.
    bars = pd.read_csv(PROCESSED, parse_dates=["timestamp_utc"])
    if development_only:
        bars = bars.loc[bars.timestamp_utc.lt(SPLIT)]
    return engine_frame(bars, exness=True)


def run_gate(data: pd.DataFrame, rules: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    trades, signals = [], []
    for index, segment in enumerate(continuous_segments(data), 1):
        minimum, first = setup_a_warmup(PARAMS, segment.start)
        if segment.candles < minimum:
            continue
        segment_id = f"exness_native-S{index:02d}"
        frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        strategy = GatedSetupA(rules)
        result = run_backtest(frame, strategy, SETTINGS, trade_start=first)
        signals.extend({"segment_id": segment_id, **item}
                       for item in strategy.signal_observations)
        for trade in result.trades:
            descriptor = strategy.signal_descriptors[trade.signal_time]
            path = frame.loc[frame.timestamp.between(trade.entry_time, trade.exit_time)]
            mfe = excursion(path, direction=trade.direction.value,
                            entry_price=trade.entry_price, exit_price=trade.exit_price,
                            stop_price=trade.stop_loss, quantity=trade.quantity,
                            gap_fill=trade.gap_through_trigger)
            if not segment.start <= trade.entry_time <= trade.exit_time <= segment.end:
                raise AssertionError("Volatility research trade crossed a source gap.")
            trades.append({"segment_id": segment_id, "trade_id": trade.trade_id,
                           "signal_time": trade.signal_time, **descriptor,
                           "entry_time": trade.entry_time, "exit_time": trade.exit_time,
                           "direction": trade.direction.value,
                           "entry_price": trade.entry_price, "exit_price": trade.exit_price,
                           "quantity": trade.quantity, "planned_risk": trade.initial_risk,
                           "gross_pnl": trade.pnl, "realized_r": trade.realized_r,
                           "bars_held": trade.bars_held, **mfe})
    return pd.DataFrame(trades), pd.DataFrame(signals)


def maximum_losing_streak(trades: pd.DataFrame) -> int:
    longest = 0
    for _, segment in trades.groupby("segment_id"):
        streak = 0
        for pnl in segment.sort_values("exit_time").gross_pnl:
            streak = streak + 1 if pnl < 0 else 0
            longest = max(longest, streak)
    return longest


def metrics(trades: pd.DataFrame, *, baseline_trades: int,
            start_year: int, end_year: int) -> dict:
    stats = summarize_trades(trades, net_column="gross_pnl", r_column="realized_r")
    side = {}
    for direction in ("LONG", "SHORT"):
        one = trades.loc[trades.direction.eq(direction)]
        side[direction.lower() + "_pf"] = summarize_trades(
            one, net_column="gross_pnl", r_column="realized_r")["profit_factor"]
        side[direction.lower() + "_average_r"] = float(one.realized_r.mean()) if len(one) else 0.
    return {**stats, "retention_percent": 100 * len(trades) / baseline_trades if baseline_trades else 0.,
            "median_r": float(trades.realized_r.median()) if len(trades) else 0.,
            "worst_segment_dd_percent": period_worst_drawdown(
                trades, start_year, end_year) if len(trades) else 0.,
            "max_losing_streak": maximum_losing_streak(trades) if len(trades) else 0,
            "average_mfe_r": float(trades.mfe_r.mean()) if len(trades) else 0.,
            "never_reached_0.5r_percent": 100 * (~trades["reached_0.5r"]).mean()
            if len(trades) else 0., **side}


def _setting(feature: str | None, percentile: int, threshold: float | None) -> dict:
    return {"feature": feature or "control", "percentile": percentile,
            "threshold": threshold, "candidate_id": "control" if feature is None else
            f"{feature}_p{percentile}"}


def _rules(setting: dict) -> list[dict]:
    if setting["feature"] == "control":
        return []
    if "rules" in setting:
        return setting["rules"]
    return [{"feature": setting["feature"], "threshold": setting["threshold"]}]


def _write_csv(frame: pd.DataFrame, name: str) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    frame.to_csv(REPORT / name, index=False)


def develop() -> pd.DataFrame:
    data = load_data(development_only=True)
    control_trades, control_signals = run_gate(data, [])
    if control_signals.signal_candle_time.max() >= SPLIT:
        raise AssertionError("Validation signal entered development run.")
    thresholds = development_thresholds(control_signals)
    settings = [_setting(None, 0, None)] + [
        _setting(feature, percentile, thresholds[feature][percentile])
        for feature in FEATURES for percentile in PERCENTILES]
    rows, direction_rows, monthly_rows, stability_rows = [], [], [], []
    base_count = len(control_trades)
    base_signals = len(control_signals)
    for setting in settings:
        rules = _rules(setting)
        trades, signals = ((control_trades, control_signals) if not rules else
                           run_gate(data, rules))
        row = {**setting, **metrics(trades, baseline_trades=base_count,
                                   start_year=2023, end_year=2024),
               "control_signals": base_signals,
               "control_signals_allowed": int(control_signals.apply(
                   lambda signal: allowed(signal, rules), axis=1).sum()),
               "signals_seen_in_gated_run": len(signals),
               "low_sample": len(trades) < 150}
        rows.append(row)
        for direction in ("LONG", "SHORT"):
            group = trades.loc[trades.direction.eq(direction)]
            direction_rows.append({**setting, "direction": direction,
                                   **summarize_trades(group, net_column="gross_pnl",
                                                      r_column="realized_r")})
        reference = control_signals.copy()
        reference["allowed"] = reference.apply(lambda signal: allowed(signal, rules), axis=1)
        reference["month"] = reference.signal_candle_time.dt.strftime("%Y-%m")
        for (month, direction), group in reference.groupby(["month", "direction"]):
            original_trades = control_trades.loc[
                control_trades.signal_month.eq(month) &
                control_trades.direction.eq(direction)]
            trade_mask = original_trades.apply(lambda trade: allowed(trade, rules), axis=1)
            monthly_rows.append({**setting, "month": month, "direction": direction,
                                 "control_signals": len(group),
                                 "allowed_signals": int(group.allowed.sum()),
                                 "blocked_signals": int((~group.allowed).sum()),
                                 "control_trades": len(original_trades),
                                 "allowed_control_trades": int(trade_mask.sum()),
                                 "blocked_control_trades": int((~trade_mask).sum())})
    results = pd.DataFrame(rows)
    control = results.iloc[0]
    for feature in FEATURES:
        subset = results.loc[results.feature.eq(feature)].sort_values("percentile")
        for _, item in subset.iterrows():
            neighbors = subset.loc[subset.percentile.sub(item.percentile).abs().eq(10)]
            neighboring_improvement = any(
                n.profit_factor > control.profit_factor and n.average_r > control.average_r
                for n in neighbors.itertuples())
            improves = (item.profit_factor > control.profit_factor and
                        item.average_r > control.average_r)
            stability_rows.append({"feature": feature, "percentile": item.percentile,
                                   "candidate_id": item.candidate_id,
                                   "pf_improves": bool(item.profit_factor > control.profit_factor),
                                   "average_r_improves": bool(item.average_r > control.average_r),
                                   "mfe_improves": bool(item.average_mfe_r > control.average_mfe_r),
                                   "fewer_never_reaching_half_r": bool(
                                       item["never_reached_0.5r_percent"] <
                                       control["never_reached_0.5r_percent"]),
                                   "adequate_sample": bool(item.trades >= 150),
                                   "neighboring_pf_and_r_improvement": bool(neighboring_improvement),
                                   "possible_overfit": bool(improves and not neighboring_improvement)})
    _write_csv(results, "development_one_factor.csv")
    _write_csv(pd.DataFrame(stability_rows), "threshold_stability.csv")
    _write_csv(pd.DataFrame(direction_rows), "direction_analysis.csv")
    _write_csv(pd.DataFrame(monthly_rows), "monthly_participation.csv")
    return results


def freeze_candidates(candidates: list[dict]) -> dict:
    """Immutable freeze; candidates are chosen only from saved development results."""
    target = REPORT / "frozen_candidates.json"
    if target.exists():
        raise FileExistsError("Frozen candidates already exist and may not be overwritten.")
    if len(candidates) > 3:
        raise ValueError("At most three candidates may be frozen.")
    development = pd.read_csv(REPORT / "development_one_factor.csv")
    for candidate in candidates:
        for rule in candidate["rules"]:
            row = development.loc[(development.feature.eq(rule["feature"])) &
                                  (development.percentile.eq(rule["percentile"]))]
            if len(row) != 1 or not np.isclose(row.iloc[0].threshold, rule["threshold"]):
                raise ValueError("Candidate rule does not match a development threshold.")
    document = {"development_start": "2023-11-09T00:00:00Z",
                "development_end": "2024-12-31T23:45:00Z",
                "validation_start": "2025-01-01T00:00:00Z",
                "validation_status": "previously observed; validation set for Phase 4K",
                "candidates": candidates}
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
    document["freeze_hash_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    return document


def load_frozen() -> dict:
    document = json.loads((REPORT / "frozen_candidates.json").read_text())
    saved_hash = document.pop("freeze_hash_sha256")
    payload = json.dumps(document, sort_keys=True, separators=(",", ":"))
    if hashlib.sha256(payload.encode()).hexdigest() != saved_hash:
        raise ValueError("Frozen candidate file was modified after the freeze.")
    document["freeze_hash_sha256"] = saved_hash
    return document


def participation_summary(control_signals: pd.DataFrame,
                          control_trades: pd.DataFrame,
                          gated_trades: pd.DataFrame,
                          rules: list[dict], year: int | None) -> dict:
    """Classify control opportunities using only their signal-time features."""
    original_signals = (control_signals if year is None else
                        control_signals.loc[control_signals.signal_year.eq(year)])
    original_trades = (control_trades if year is None else
                       control_trades.loc[control_trades.signal_year.eq(year)])
    signal_mask = original_signals.apply(lambda row: allowed(row, rules), axis=1)
    trade_mask = original_trades.apply(lambda row: allowed(row, rules), axis=1)
    permitted, blocked = original_trades.loc[trade_mask], original_trades.loc[~trade_mask]
    gated_year = (gated_trades if year is None else
                  gated_trades.loc[gated_trades.signal_year.eq(year)])
    return {"year": year if year is not None else "All",
            "control_signals": len(original_signals),
            "signals_allowed": int(signal_mask.sum()),
            "signals_blocked": int((~signal_mask).sum()),
            "signal_allowed_percent": 100 * signal_mask.mean() if len(signal_mask) else 0.,
            "control_trades_allowed": len(permitted),
            "control_trades_blocked": len(blocked),
            "allowed_counterfactual_pnl": permitted.gross_pnl.sum(),
            "blocked_counterfactual_pnl": blocked.gross_pnl.sum(),
            "allowed_counterfactual_pf": summarize_trades(
                permitted, net_column="gross_pnl", r_column="realized_r")["profit_factor"],
            "blocked_counterfactual_pf": summarize_trades(
                blocked, net_column="gross_pnl", r_column="realized_r")["profit_factor"],
            "gated_run_trades": len(gated_year),
            "gated_run_pnl": gated_year.gross_pnl.sum()}


def validate() -> pd.DataFrame:
    frozen = load_frozen()  # Must precede any validation data access.
    data = load_data(development_only=False)
    settings = [{"candidate_id": "control", "rules": []}] + frozen["candidates"]
    runs = {setting["candidate_id"]: run_gate(data, setting["rules"])
            for setting in settings}
    control_trades, control_signals = runs["control"]
    rows, participation, cost_rows = [], [], []
    for setting in settings:
        candidate_id, rules = setting["candidate_id"], setting["rules"]
        trades, signals = runs[candidate_id]
        for label, years in (("2025", (2025,)), ("2026", (2026,)),
                             ("2025–2026", (2025, 2026))):
            scoped = trades.loc[trades.signal_year.isin(years)]
            base = control_trades.loc[control_trades.signal_year.isin(years)]
            rows.append({"candidate_id": candidate_id, "period": label,
                         **metrics(scoped, baseline_trades=len(base),
                                   start_year=min(years), end_year=max(years))})
        for spread in (0., 10., 20., 30.):
            priced = price_cost_view(trades, fixed_spread=spread)
            for label, years in (("development", (2023, 2024)),
                                 ("2025", (2025,)), ("2026", (2026,)),
                                 ("2025–2026", (2025, 2026))):
                group = priced.loc[priced.signal_year.isin(years)]
                cost_rows.append({"candidate_id": candidate_id, "period": label,
                                  "spread_usd_per_btc": spread,
                                  **summarize_trades(group, net_column="net_pnl",
                                                     r_column="realized_r_costed")})
        # Participation is defined against frozen original control events;
        # blocked-trade PnL is counterfactual, not a second executed backtest.
        for year in (2023, 2024, 2025, 2026, None):
            participation.append({"candidate_id": candidate_id,
                                  **participation_summary(control_signals,
                                                          control_trades, trades,
                                                          rules, year)})
    _write_csv(pd.DataFrame(rows), "validation_results.csv")
    _write_csv(pd.DataFrame(participation), "allowed_blocked_analysis.csv")
    _write_csv(pd.DataFrame(cost_rows), "cost_crosscheck.csv")
    write_summary()
    return pd.DataFrame(rows)


def write_summary() -> None:
    one = pd.read_csv(REPORT / "development_one_factor.csv")
    stable = pd.read_csv(REPORT / "threshold_stability.csv")
    validation = pd.read_csv(REPORT / "validation_results.csv")
    costs = pd.read_csv(REPORT / "cost_crosscheck.csv")
    participation = pd.read_csv(REPORT / "allowed_blocked_analysis.csv")
    frozen = load_frozen()

    def table(frame: pd.DataFrame) -> str:
        columns = list(frame.columns)
        lines = ["| " + " | ".join(columns) + " |",
                 "| " + " | ".join("---" for _ in columns) + " |"]
        for values in frame.itertuples(index=False, name=None):
            lines.append("| " + " | ".join(
                f"{value:.4f}" if isinstance(value, float) else str(value)
                for value in values) + " |")
        return "\n".join(lines)

    columns = ["feature", "percentile", "threshold", "trades", "retention_percent",
               "profit_factor", "average_r", "net_pnl", "worst_segment_dd_percent",
               "average_mfe_r", "never_reached_0.5r_percent", "low_sample"]
    val_columns = ["candidate_id", "period", "trades", "retention_percent",
                   "profit_factor", "average_r", "net_pnl", "worst_segment_dd_percent",
                   "long_pf", "long_average_r", "short_pf", "short_average_r",
                   "average_mfe_r", "never_reached_0.5r_percent"]
    lines = ["# Setup A low-volatility regime robustness", "",
             "**REGIME RESEARCH — NOT ACTIVE STRATEGY.** Frozen Pine V2.2 Setup A standalone, original stop/pending/3R, both directions, zero commission. No active strategy or generic engine code changed.",
             "", "Development: 2023-11-09 through 2024-12-31. Validation set for Phase 4K: 2025-01-01 through latest 2026. The latter was observed in earlier phases and is not an untouched holdout.",
             "", "Threshold percentiles were computed from all original Setup A development signals, using causal signal-time ATR% and recent 24-hour volatility. A signal passes only when its value is strictly above the stored development threshold. Each candidate is a research-only strategy wrapper that suppresses a signal after frozen Setup A has evaluated it. The audited engine then handles positions, pending orders, risk locks and sizing without alteration. Continuous source segments reset indicators and accounts; no gap is filled.",
             "", "## Development one-factor results", "", table(one[columns]),
             "", "## Threshold stability", "", table(stable),
             "", "ATR% p20–p40 had adjacent aggregate PF and average-R values above control, but the meaningful gain was concentrated at p20. Drawdown worsened at p30/p40 and the long direction deteriorated there. The result is overfit-like rather than a convincing broad plateau. The 24-hour volatility thresholds did not show adjacent PF/average-R improvement. The p40 24-hour setting also fell below 150 development trades.",
             "", "## Candidate freeze", "", f"SHA-256: `{frozen['freeze_hash_sha256']}`", "",
             table(pd.DataFrame([{"candidate_id": c["candidate_id"],
                                  "rules": json.dumps(c["rules"], sort_keys=True)}
                                 for c in frozen["candidates"]])),
             "", "C1 was frozen from development because p20 and p30 met the neighboring aggregate criterion, p20 retained 82.2% of control trades, reduced development drawdown, and improved both directions. The isolated magnitude of the p20 gain is explicitly treated as an overfit risk. No 24-hour or combined candidate qualified.",
             "", "## Validation set", "", table(validation[val_columns]),
             "", "The frozen gate did not materially improve 2025 PF or average R and removed much of 2026's positive result. Its lower 2025 absolute loss reflects fewer trades, not better per-trade quality. Validation does not support this gate.",
             "", "## Cost sensitivity", "", table(costs[["candidate_id", "period",
                                                  "spread_usd_per_btc", "trades",
                                                  "profit_factor", "average_r", "net_pnl"]]),
             "", "Fixed spreads are research sensitivities on the same completed trades, not tick-exact execution. Costs did not select the threshold.",
             "", "## Original signal participation and blocked-trade counterfactual", "",
             table(participation),
             "", "Allowed/blocked control trades and their PnL are counterfactual classifications of the frozen original run. Gated-run trade and PnL columns are from independent strategy/engine reruns; they can differ because suppressing an order changes later position availability and account state. Drawdown is closed-trade, per source segment, with no synthetic equity continuity across gaps.",
             "", "Monthly removals and direction breakdowns are provided in CSV files. No entry, exit, or cost assumption was selected using validation performance.", ""]
    (REPORT / "regime_research_summary.md").write_text("\n".join(lines))


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "develop":
        print(develop().to_string(index=False))
    elif command == "validate":
        print(validate().to_string(index=False))
    else:
        raise SystemExit("Use develop or validate explicitly.")
