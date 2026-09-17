"""Standalone frozen Pine Setup A research on real Exness Bid M15 history."""
from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal, ROUND_DOWN
from pathlib import Path

import pandas as pd

from engine.backtester import run_backtest
from engine.models import BacktestSettings, Signal
from research.exness_native_validation import (
    engine_frame, price_cost_view, signal_matches, summarize_trades,
)
from services.exness_m15 import PROCESSED, REPORT as NATIVE_REPORT, align_price_feeds
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v2_setup_a import BtcV2SetupA, SETUP_ID, SetupAParameters
from utils.data_validation import continuous_segments, load_ohlcv_csv


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/setup_a"
STEP = pd.Timedelta(minutes=15)
PARAMS = SetupAParameters()
SETTINGS = BacktestSettings(risk_percent=.25, risk_reward_ratio=3.,
                            commission_percent=0., slippage_percent=0.)


def setup_a_warmup(params: SetupAParameters, start: pd.Timestamp) -> tuple[int, pd.Timestamp]:
    """Derive the first searchable bar from confirmed H1 and M15 dependencies."""
    m15_bars = max(params.ema_fast, params.ema_slow, params.rsi_length + 1,
                   params.di_length + params.adx_smoothing, params.atr_length,
                   params.touch_lookback + 1)
    h1_bars = max(params.h1_fast_ema, params.h1_slow_ema) + params.h1_slope_lookback
    first = max(start + (m15_bars - 1) * STEP,
                start.ceil("h") + pd.Timedelta(hours=h1_bars))
    return int((first - start) / STEP) + 1, first


class CaptureSetupA(BtcV2SetupA):
    def reset(self) -> None:
        super().reset()
        self.captured_signals = []

    def on_candle(self, candle):
        action = super().on_candle(candle)
        if isinstance(action, Signal):
            trigger = float(action.pending_entry_price)
            stop = float(action.pending_stop_price)
            risk = abs(trigger - stop)
            self.captured_signals.append({
                "signal_time": candle.timestamp + STEP,
                "signal_candle_time": candle.timestamp,
                "direction": action.direction.value,
                "trigger": trigger,
                "structural_stop": stop,
                "planned_target_distance": self.params.reward_multiple * risk,
                "planned_risk_price": risk,
            })
        return action


def run_feed(data: pd.DataFrame, feed: str) -> dict:
    signals, orders, trades, segments = [], [], [], []
    diagnostics = Counter()
    filled_quantities = []
    for index, segment in enumerate(continuous_segments(data), 1):
        segment_id = f"{feed}-S{index:02d}"
        minimum, first_search = setup_a_warmup(PARAMS, segment.start)
        if segment.candles < minimum:
            segments.append({"segment_id": segment_id, "candles": segment.candles,
                             "usable": False, "reason": f"needs {minimum} candles for confirmed H1 and M15 warm-up"})
            continue
        fragment = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        strategy = CaptureSetupA(PARAMS)
        result = run_backtest(fragment, strategy, SETTINGS, trade_start=first_search)
        diagnostics.update(strategy.diagnostics)
        filled_quantities.extend(trade.quantity for trade in result.trades)
        if result.open_position is not None:
            filled_quantities.append(result.open_position.quantity)
        segments.append({"segment_id": segment_id, "candles": segment.candles,
                         "usable": True, "signals": len(strategy.captured_signals),
                         "open_position_at_end": result.open_position is not None,
                         "pending_at_end": result.pending_order is not None,
                         "max_drawdown_percent": max((p.drawdown_percent for p in result.equity_curve), default=0.)})
        signals.extend({"feed": feed, "segment_id": segment_id, **item}
                       for item in strategy.captured_signals)
        orders.extend({"feed": feed, "segment_id": segment_id,
                       "signal_time": event.signal_time, "direction": event.direction.value,
                       "status": event.status, "fill_time": event.fill_time,
                       "fill_price": event.fill_price, "cancel_reason": event.cancel_reason}
                      for event in result.order_events)
        for trade in result.trades:
            if not segment.start <= trade.entry_time <= trade.exit_time <= segment.end:
                raise AssertionError("Setup A trade crossed a missing-data gap.")
            trades.append({"feed": feed, "segment_id": segment_id,
                           "trade_id": trade.trade_id, "signal_time": trade.signal_time,
                           "entry_time": trade.entry_time, "exit_time": trade.exit_time,
                           "direction": trade.direction.value,
                           "entry_price": trade.entry_price,
                           "structural_stop": trade.stop_loss, "target": trade.take_profit,
                           "exit_price": trade.exit_price, "exit_reason": trade.exit_reason,
                           "quantity": trade.quantity, "planned_risk": trade.initial_risk,
                           "gross_pnl": trade.pnl, "realized_r": trade.realized_r})
    return {"signals": pd.DataFrame(signals), "orders": pd.DataFrame(orders),
            "trades": pd.DataFrame(trades), "segments": pd.DataFrame(segments),
            "diagnostics": diagnostics, "filled_quantities": filled_quantities}


def executable_lots(quantity: float) -> float:
    """One BTC per lot, 0.01-lot minimum and step, 200-lot cap; never round up."""
    if quantity <= 0:
        return 0.
    rounded = (Decimal(str(quantity)) / Decimal("0.01")).to_integral_value(
        rounding=ROUND_DOWN) * Decimal("0.01")
    return float(min(rounded, Decimal("200"))) if rounded >= Decimal("0.01") else 0.


def period_worst_drawdown(trades: pd.DataFrame, start_year: int, end_year: int,
                          *, costed: bool = False) -> float:
    """Compute closed-trade drawdown within each real segment, never across gaps."""
    worst = 0.
    pnl_column = "net_pnl" if costed else "gross_pnl"
    for _, segment in trades.groupby("segment_id"):
        before = segment.loc[segment.exit_time.dt.year < start_year, pnl_column].sum()
        balance = peak = SETTINGS.starting_balance + float(before)
        period = segment.loc[segment.exit_time.dt.year.between(start_year, end_year)]
        for pnl in period.sort_values("exit_time")[pnl_column]:
            balance += pnl
            peak = max(peak, balance)
            worst = max(worst, (peak - balance) / peak * 100)
    return worst


def _row(feed: str, scope: str, view: str, run: dict, trades: pd.DataFrame,
         *, costed: bool = False, worst_dd: float | None = None) -> dict:
    stats = summarize_trades(trades,
                             net_column="net_pnl" if costed else "gross_pnl",
                             r_column="realized_r_costed" if costed else "realized_r")
    stats["median_r"] = (float(trades["realized_r_costed" if costed else "realized_r"].median())
                         if len(trades) else 0.)
    statuses = Counter(run["orders"].status) if not run["orders"].empty else Counter()
    streak = current = 0
    for trade in trades.sort_values("exit_time").itertuples(index=False):
        current = current + 1 if (trade.net_pnl if costed else trade.gross_pnl) < 0 else 0
        streak = max(streak, current)
    return {"feed": feed, "scope": scope, "cost_view": view,
            "signals": len(run["signals"]), "orders": len(run["orders"]),
            "fills": statuses["triggered"], "expired": statuses["expired"],
            "cancelled": statuses["cancelled"], **stats,
            "max_losing_streak": streak, "worst_segment_dd_percent": worst_dd}


def build_setup_a_validation(exness_path: Path = PROCESSED,
                             bitstamp_path: Path = CANONICAL_DATA_FILE,
                             output_dir: Path = REPORT) -> dict:
    exness = pd.read_csv(exness_path, parse_dates=["timestamp_utc"])
    bitstamp = load_ohlcv_csv(bitstamp_path)
    common, _ = align_price_feeds(exness, bitstamp)
    output_dir.mkdir(parents=True, exist_ok=True)
    full = run_feed(engine_frame(exness, exness=True), "exness_native")
    ex_common = run_feed(engine_frame(common.rename(columns={
        "open_exness": "open", "high_exness": "high", "low_exness": "low",
        "close_exness": "close"}), exness=True), "exness_overlap")
    bs_common = run_feed(engine_frame(common.rename(columns={
        "open_bitstamp": "open", "high_bitstamp": "high", "low_bitstamp": "low",
        "close_bitstamp": "close"}), exness=False), "bitstamp_overlap")
    matches, overlap = signal_matches(ex_common["signals"], bs_common["signals"])
    matches.to_csv(output_dir / "feed_signal_comparison.csv", index=False)
    overlap["exact_signal_match_rate"] = (overlap["exact_matches"] / overlap["exness_signals"]
                                           if overlap["exness_signals"] else 0.)
    overlap["exact_plus_near_match_rate"] = ((overlap["exact_matches"] + overlap["near_matches"])
                                             / overlap["exness_signals"] if overlap["exness_signals"] else 0.)
    base = full["trades"].copy()
    base["executable_lots"] = base.quantity.map(executable_lots)
    base["below_minimum"] = base.executable_lots.eq(0)
    base["quantity_retention_percent"] = base.executable_lots / base.quantity * 100
    base["estimated_zero_cost_pnl_at_rounded_lots"] = (
        base.gross_pnl * base.executable_lots / base.quantity)
    base[["segment_id", "trade_id", "signal_time", "direction", "quantity",
          "executable_lots", "below_minimum", "quantity_retention_percent",
          "gross_pnl", "estimated_zero_cost_pnl_at_rounded_lots"]].to_csv(
              output_dir / "lot_sizing_audit.csv", index=False)
    spread = exness.set_index("timestamp_utc").spread_price
    views = {"zero_cost": price_cost_view(base),
             "bar_minimum_spread_lower_bound": price_cost_view(base, spread_bars=spread)}
    for dollars in (10., 15., 20., 30.):
        views[f"fixed_spread_${int(dollars)}"] = price_cost_view(base, fixed_spread=dollars)
    native_rows = [_row("exness_native", "full_native", name, full, priced,
                        costed=name != "zero_cost",
                        worst_dd=period_worst_drawdown(priced, 2023, 2026,
                                                     costed=name != "zero_cost"))
                   for name, priced in views.items()]
    for label, predicate in (("earlier_2023_2024", base.signal_time.dt.year <= 2024),
                             ("later_2025_2026", base.signal_time.dt.year >= 2025)):
        for name in ("zero_cost", "fixed_spread_$10"):
            priced = views[name].loc[predicate]
            run = {"signals": full["signals"].loc[
                full["signals"].signal_time.dt.year.le(2024) if label.startswith("earlier")
                else full["signals"].signal_time.dt.year.ge(2025)],
                "orders": full["orders"].loc[
                    full["orders"].signal_time.dt.year.le(2024) if label.startswith("earlier")
                    else full["orders"].signal_time.dt.year.ge(2025)]}
            native_rows.append(_row("exness_native", label, name, run, priced,
                                    costed=name != "zero_cost",
                                    worst_dd=period_worst_drawdown(priced,
                                        2023 if label.startswith("earlier") else 2025,
                                        2024 if label.startswith("earlier") else 2026,
                                        costed=name != "zero_cost")))
    native_rows += [_row("exness_overlap", "exact_common_timestamps", "zero_cost",
                         ex_common, ex_common["trades"]),
                    _row("bitstamp_overlap", "exact_common_timestamps", "zero_cost",
                         bs_common, bs_common["trades"])]
    native = pd.DataFrame(native_rows)
    native.to_csv(output_dir / "native_results.csv", index=False)
    native.loc[native.scope.eq("full_native")].to_csv(output_dir / "cost_sensitivity.csv", index=False)
    yearly = []
    for year in range(2023, 2027):
        for view in ("zero_cost", "fixed_spread_$10"):
            priced = views[view].loc[views[view].signal_time.dt.year.eq(year)]
            yearly.append({"year": year, "partial_year": year in (2023, 2026),
                           "cost_view": view, **summarize_trades(
                               priced, net_column="net_pnl" if view != "zero_cost" else "gross_pnl",
                               r_column="realized_r_costed" if view != "zero_cost" else "realized_r")})
    pd.DataFrame(yearly).to_csv(output_dir / "yearly_results.csv", index=False)
    direction = []
    for side in ("LONG", "SHORT"):
        for view in ("zero_cost", "fixed_spread_$10"):
            priced = views[view].loc[views[view].direction.eq(side)]
            direction.append({"direction": side, "cost_view": view,
                              **summarize_trades(priced,
                                  net_column="net_pnl" if view != "zero_cost" else "gross_pnl",
                                  r_column="realized_r_costed" if view != "zero_cost" else "realized_r")})
    pd.DataFrame(direction).to_csv(output_dir / "direction_results.csv", index=False)
    # Read the immutable Phase 4G report; never rerun or alter Setup B here.
    b = pd.read_csv(NATIVE_REPORT / "native_setup_b_results.csv")
    compare = []
    for setup, table in (("A", native), ("B", b)):
        for view in ("zero_cost", "fixed_spread_$10"):
            row = table.loc[(table.feed == "exness_native") &
                            (table.scope == "full_native") & (table.cost_view == view)].iloc[0]
            compare.append({"setup": setup, "cost_view": view,
                            "signals": row.signals, "trades": row.trades,
                            "profit_factor": row.profit_factor,
                            "average_r": row.average_r, "net_pnl": row.net_pnl,
                            "exact_signal_match_rate": (overlap["exact_signal_match_rate"] if setup == "A"
                                else json.loads((NATIVE_REPORT / "native_validation_summary.json").read_text())
                                ["signals"]["exact_percent_of_exness"] / 100)})
    pd.DataFrame(compare).to_csv(output_dir / "setup_a_vs_b.csv", index=False)
    summary = {"native": native_rows, "signal_overlap": overlap,
               "lot_sizing": {"theoretical_filled_positions": len(full["filled_quantities"]),
                              "executable_filled_positions": sum(
                                  executable_lots(q) > 0 for q in full["filled_quantities"]),
                              "below_minimum_filled_positions": sum(
                                  executable_lots(q) == 0 for q in full["filled_quantities"]),
                              "theoretical_completed_trades": len(base),
                              "executable_completed_trades": int((~base.below_minimum).sum()),
                              "below_minimum_completed_trades": int(base.below_minimum.sum()),
                              "average_quantity_retention_percent": float(base.quantity_retention_percent.mean()),
                              "estimated_zero_cost_pnl_at_rounded_lots": float(
                                  base.estimated_zero_cost_pnl_at_rounded_lots.sum()),
                              "min_lots": .01, "step_lots": .01,
                              "contract_btc_per_lot": 1},
               "diagnostics": dict(full["diagnostics"]),
               "cancellation_reasons": full["orders"].loc[
                   full["orders"].status.eq("cancelled"), "cancel_reason"].value_counts().to_dict(),
               "segments": full["segments"].to_dict("records")}
    (output_dir / "setup_a_validation_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    _write_summary(output_dir / "setup_a_validation_summary.md", summary, native,
                   pd.DataFrame(yearly), pd.DataFrame(direction))
    return summary


def _write_summary(path: Path, summary: dict, native: pd.DataFrame,
                   yearly: pd.DataFrame, direction: pd.DataFrame) -> None:
    def markdown_table(frame: pd.DataFrame) -> str:
        columns = list(frame.columns)
        rows = ["| " + " | ".join(columns) + " |",
                "| " + " | ".join("---" for _ in columns) + " |"]
        for values in frame.itertuples(index=False, name=None):
            rows.append("| " + " | ".join(
                f"{value:.4f}" if isinstance(value, float) else str(value)
                for value in values) + " |")
        return "\n".join(rows)

    lines = ["# Frozen Pine V2.2.0 Setup A standalone validation", "",
             "FROZEN ORIGINAL V2.2 RULES · NO OPTIMIZATION. Setup B is disabled in this run. The strategy, 3R exit, pending entry, and generic execution code are unchanged.",
             "", "Exness Bid M15 source; each contiguous segment starts a fresh account, indicator state, and pending/position state. Pooled trade sums are not a continuous compounded equity curve.",
             "", "Zero cost isolates the Bid feed. Historical M15 spread is a bar-minimum lower-bound descriptor, not a tick-exact execution cost. Fixed spreads are separate sensitivity views. Commission is $0.",
             "", "Theoretical completed trades and 0.01-lot executable counts are reported separately. Post-hoc lot rounding does not rerun strategy permissions or the account path; native PnL tables use the audited theoretical sizing convention for Setup B comparability.",
             "", f"Completed trades: {summary['lot_sizing']['theoretical_completed_trades']} theoretical, "
             f"{summary['lot_sizing']['executable_completed_trades']} at/above 0.01 lot, "
             f"{summary['lot_sizing']['below_minimum_completed_trades']} below minimum.",
             "", f"Filled positions including one open final position: {summary['lot_sizing']['theoretical_filled_positions']} theoretical, "
             f"{summary['lot_sizing']['executable_filled_positions']} at/above 0.01 lot, "
             f"{summary['lot_sizing']['below_minimum_filled_positions']} below minimum.",
             "", f"Rounding down retains {summary['lot_sizing']['average_quantity_retention_percent']:.2f}% of theoretical quantity on average. "
             f"A trade-by-trade zero-cost PnL rescale gives ${summary['lot_sizing']['estimated_zero_cost_pnl_at_rounded_lots']:,.2f}; "
             "this is a sizing audit, not an account-path rerun, so it is excluded from strategy comparison metrics.",
             "", "## Pine risk and permission impact", "",
             "The original daily/monthly and session permissions are active. Risk-block counts are diagnostic candles, not cancelled filled positions.",
             "", *[f"- {key}: {value}" for key, value in sorted(summary["diagnostics"].items())
                    if key.startswith("Blocked:")],
             "", f"Pending cancellation reasons: {summary['cancellation_reasons']}.",
             "", "## Native and same-period results", "",
             markdown_table(native),
             "", "## Yearly results", "", markdown_table(yearly),
             "", "## Long and short", "", markdown_table(direction),
             "", f"Signal overlap: {summary['signal_overlap']}", ""]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    print(json.dumps(build_setup_a_validation(), indent=2, default=str)[:4000])
