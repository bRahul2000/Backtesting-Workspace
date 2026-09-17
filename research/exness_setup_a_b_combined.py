"""Frozen Pine V2.2 A+B priority on independent Exness Bid M15 segments."""
from __future__ import annotations

import json
import hashlib
from collections import Counter
from pathlib import Path

import pandas as pd

from engine.backtester import run_backtest
from research.exness_native_validation import (engine_frame, price_cost_view,
                                               run_independent_feed, summarize_trades)
from research.exness_setup_a_validation import (PARAMS as A_PARAMS, SETTINGS,
                                                period_worst_drawdown, run_feed as run_a_feed,
                                                setup_a_warmup)
from research.segment_aware_baseline import warmup_plan
from services.exness_m15 import PROCESSED
from strategies.btc_v2_combined import BtcV2Combined
from strategies.btc_v2_setup_a import SETUP_ID as A_ID
from strategies.btc_v2_setup_b import SETUP_ID as B_ID, SetupBParameters
from utils.data_validation import continuous_segments


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/research/setup_a_b_combined"
B_PARAMS = SetupBParameters()


def run_combined_feed(data: pd.DataFrame) -> dict:
    signals, orders, trades, priority, blocked, segments = [], [], [], [], [], []
    for index, segment in enumerate(continuous_segments(data), 1):
        segment_id = f"exness_native-S{index:02d}"
        a_minimum, a_first = setup_a_warmup(A_PARAMS, segment.start)
        b_plan = warmup_plan(B_PARAMS, segment.start)
        first_search = max(a_first, b_plan.first_search_time)
        minimum = max(a_minimum, b_plan.minimum_segment_candles)
        if segment.candles < minimum:
            segments.append({"segment_id": segment_id, "candles": segment.candles,
                             "usable": False, "reason": f"needs {minimum} causal warm-up candles"})
            continue
        frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        strategy = BtcV2Combined(A_PARAMS, B_PARAMS)
        result = run_backtest(frame, strategy, SETTINGS, trade_start=first_search)
        segments.append({"segment_id": segment_id, "candles": segment.candles,
                         "usable": True, "first_search": first_search,
                         "open_at_end": result.open_position is not None,
                         "pending_at_end": result.pending_order is not None})
        signals.extend({"segment_id": segment_id, **x} for x in strategy.captured_signals)
        priority.extend({"segment_id": segment_id, **x} for x in strategy.priority_suppressed)
        blocked.extend({"segment_id": segment_id, **x} for x in strategy.blocked_by_a)
        orders.extend({"segment_id": segment_id, "setup_id": e.setup_id,
                       "signal_time": e.signal_time, "status": e.status,
                       "cancel_reason": e.cancel_reason, "fill_time": e.fill_time}
                      for e in result.order_events)
        for t in result.trades:
            if not segment.start <= t.entry_time <= t.exit_time <= segment.end:
                raise AssertionError("Combined trade crossed a source gap.")
            trades.append({"segment_id": segment_id, "trade_id": t.trade_id,
                           "setup_id": t.setup_id, "signal_time": t.signal_time,
                           "entry_time": t.entry_time, "exit_time": t.exit_time,
                           "direction": t.direction.value, "entry_price": t.entry_price,
                           "structural_stop": t.stop_loss, "target": t.take_profit,
                           "exit_price": t.exit_price, "exit_reason": t.exit_reason,
                           "quantity": t.quantity, "planned_risk": t.initial_risk,
                           "gross_pnl": t.pnl, "realized_r": t.realized_r})
    return {"signals": pd.DataFrame(signals), "orders": pd.DataFrame(orders),
            "trades": pd.DataFrame(trades), "priority": pd.DataFrame(priority),
            "blocked": pd.DataFrame(blocked), "segments": pd.DataFrame(segments)}


def _view(trades: pd.DataFrame, spread: float) -> pd.DataFrame:
    return price_cost_view(trades, fixed_spread=spread)


def _stats(frame: pd.DataFrame, *, costed: bool = False) -> dict:
    return summarize_trades(frame, net_column="net_pnl" if costed else "gross_pnl",
                            r_column="realized_r_costed" if costed else "realized_r")


def _row(scope: str, view: str, frame: pd.DataFrame, *, costed: bool = False) -> dict:
    stats = _stats(frame, costed=costed)
    return {"scope": scope, "cost_view": view, **stats,
            "worst_segment_dd_percent": period_worst_drawdown(frame, 2023, 2026,
                                                               costed=costed),
            "sum_r": float(frame["realized_r_costed" if costed else "realized_r"].sum())}


def build_combined_baseline(data_path: Path = PROCESSED,
                            output_dir: Path = REPORT) -> dict:
    exness = pd.read_csv(data_path, parse_dates=["timestamp_utc"])
    frame = engine_frame(exness, exness=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    combined = run_combined_feed(frame)
    # B is rerun with the exact frozen Phase 4G strategy to identify which
    # standalone B completed trades encountered an A blocker in the combined run.
    b_alone = run_independent_feed(frame, "exness_native")
    a_alone = run_a_feed(frame, "exness_native")
    a_saved = pd.read_csv(ROOT / "reports/setup_a/native_results.csv")
    b_saved = pd.read_csv(ROOT / "reports/broker/exness/native_validation/native_setup_b_results.csv")
    for name, fresh, saved in (("A", a_alone, a_saved), ("B", b_alone, b_saved)):
        row = saved.loc[(saved.feed == "exness_native") &
                        (saved.scope == "full_native") &
                        (saved.cost_view == "zero_cost")].iloc[0]
        current = _stats(fresh["trades"])
        if (current["trades"] != int(row.trades) or
            abs(current["net_pnl"] - float(row.net_pnl)) > 1e-7 or
            abs(current["average_r"] - float(row.average_r)) > 1e-10):
            raise AssertionError(f"Frozen standalone {name} report differs from a current-data rerun.")
    trades = combined["trades"]
    views = {"zero_cost": price_cost_view(trades),
             "fixed_spread_$10": _view(trades, 10.),
             "fixed_spread_$20": _view(trades, 20.)}
    combined_rows = [_row("A+B", name, priced, costed=name != "zero_cost")
                     for name, priced in views.items()]
    pd.DataFrame(combined_rows).to_csv(output_dir / "combined_results.csv", index=False)
    attributed = []
    for name, priced in views.items():
        for setup_id, label in ((A_ID, "A"), (B_ID, "B")):
            attributed.append({"setup": label, "cost_view": name,
                               **_stats(priced.loc[priced.setup_id.eq(setup_id)],
                                        costed=name != "zero_cost")})
    pd.DataFrame(attributed).to_csv(output_dir / "attributed_results.csv", index=False)
    yearly = []
    for year in (2023, 2024, 2025, 2026):
        for name in ("zero_cost", "fixed_spread_$10", "fixed_spread_$20"):
            priced = views[name]
            subset = priced.loc[priced.signal_time.dt.year.eq(year)]
            yearly.append({"year": year, "partial_year": year in (2023, 2026),
                           "cost_view": name, **_stats(subset, costed=name != "zero_cost"),
                           "worst_segment_dd_percent": period_worst_drawdown(
                               priced, year, year, costed=name != "zero_cost")})
    pd.DataFrame(yearly).to_csv(output_dir / "yearly_results.csv", index=False)
    periods = []
    for label, start, end in (("earlier_2023_2024", 2023, 2024),
                              ("later_2025_2026", 2025, 2026)):
        for name in ("zero_cost", "fixed_spread_$10", "fixed_spread_$20"):
            priced = views[name]
            subset = priced.loc[priced.signal_time.dt.year.between(start, end)]
            periods.append({"period": label, "cost_view": name,
                            **_stats(subset, costed=name != "zero_cost"),
                            "worst_segment_dd_percent": period_worst_drawdown(
                                priced, start, end, costed=name != "zero_cost")})
    pd.DataFrame(periods).to_csv(output_dir / "period_results.csv", index=False)
    compare = []
    for setup, saved in (("A", a_saved), ("B", b_saved)):
        for name in views:
            row = saved.loc[(saved.feed == "exness_native") &
                            (saved.scope == "full_native") &
                            (saved.cost_view == name)].iloc[0]
            compare.append({"setup": setup, "cost_view": name,
                            "trades": int(row.trades), "profit_factor": float(row.profit_factor),
                            "average_r": float(row.average_r), "net_pnl": float(row.net_pnl),
                            "worst_segment_dd_percent": (float(row.worst_segment_dd_percent)
                                if setup == "A" else period_worst_drawdown(
                                    _view(b_alone["trades"], 0 if name == "zero_cost" else
                                          10 if name == "fixed_spread_$10" else 20),
                                    2023, 2026, costed=name != "zero_cost"))})
    for row in combined_rows:
        compare.append({"setup": "A+B", "cost_view": row["cost_view"],
                        **{key: row[key] for key in ("trades", "profit_factor", "average_r",
                                                   "net_pnl", "worst_segment_dd_percent")}})
    pd.DataFrame(compare).to_csv(output_dir / "standalone_vs_combined.csv", index=False)
    b_keys = {(t.signal_time, t.direction) for t in b_alone["trades"].itertuples(index=False)}
    priority = combined["priority"]
    blocked = combined["blocked"]
    blocked_trade_keys = {(r.signal_time, r.direction) for r in blocked.itertuples(index=False)}
    priority_trade_keys = {(r.signal_time, r.direction) for r in priority.itertuples(index=False)}
    pending_trade_keys = {(r.signal_time, r.direction) for r in
                          blocked.loc[blocked.blocker.eq("A_PENDING")].itertuples(index=False)}
    position_trade_keys = {(r.signal_time, r.direction) for r in
                           blocked.loc[blocked.blocker.eq("A_POSITION")].itertuples(index=False)}
    priority.to_csv(output_dir / "b_priority_suppressed.csv", index=False)
    blocked.to_csv(output_dir / "b_blocked_by_a.csv", index=False)
    trades.to_csv(output_dir / "combined_trades.csv", index=False)
    combined["signals"].to_csv(output_dir / "combined_signals.csv", index=False)
    a_zero = a_saved.loc[(a_saved.feed == "exness_native") &
                         (a_saved.scope == "full_native") &
                         (a_saved.cost_view == "zero_cost")].iloc[0]
    combined_zero = combined_rows[0]
    marginal = {"combined_minus_a_pnl": combined_zero["net_pnl"] - float(a_zero.net_pnl),
                "combined_minus_a_sum_r": combined_zero["sum_r"] -
                    float(a_zero.average_r) * int(a_zero.trades),
                "combined_minus_a_average_r": combined_zero["average_r"] - float(a_zero.average_r),
                "combined_b_attributed_pnl": float(trades.loc[trades.setup_id.eq(B_ID), "gross_pnl"].sum()),
                "combined_b_attributed_sum_r": float(trades.loc[trades.setup_id.eq(B_ID), "realized_r"].sum())}
    segment_records = [{key: None if pd.isna(value) else value
                        for key, value in record.items()}
                       for record in combined["segments"].to_dict("records")]
    summary = {"data_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
               "data_start_utc": str(exness.timestamp_utc.iloc[0]),
               "data_end_utc": str(exness.timestamp_utc.iloc[-1]),
               "results": combined_rows, "marginal_b_vs_a": marginal,
               "a_priority_suppressed_b_signals": len(priority),
               "a_priority_suppressed_b_standalone_completed_trades": len(priority_trade_keys & b_keys),
               "b_candidates_blocked_by_a_pending": int(blocked.blocker.eq("A_PENDING").sum()),
               "b_candidates_blocked_by_a_position": int(blocked.blocker.eq("A_POSITION").sum()),
               "b_standalone_completed_trades_blocked_by_a": len(blocked_trade_keys & b_keys),
               "b_standalone_completed_trades_blocked_by_a_pending": len(pending_trade_keys & b_keys),
               "b_standalone_completed_trades_blocked_by_a_position": len(position_trade_keys & b_keys),
               "segments": segment_records,
               "orders": dict(Counter(combined["orders"].status))}
    (output_dir / "combined_summary.json").write_text(
        json.dumps(summary, indent=2, default=str, allow_nan=False) + "\n")
    _write_markdown(output_dir / "combined_summary.md", summary, pd.DataFrame(compare),
                    pd.DataFrame(attributed), pd.DataFrame(yearly), pd.DataFrame(periods))
    return summary


def _write_markdown(path: Path, summary: dict, compare: pd.DataFrame,
                    attributed: pd.DataFrame, yearly: pd.DataFrame, periods: pd.DataFrame) -> None:
    def table(frame):
        cols = list(frame.columns)
        lines = ["| " + " | ".join(cols) + " |",
                 "| " + " | ".join("---" for _ in cols) + " |"]
        for values in frame.itertuples(index=False, name=None):
            lines.append("| " + " | ".join(
                f"{v:.4f}" if isinstance(v, float) else str(v) for v in values) + " |")
        return "\n".join(lines)
    lines = ["# Frozen Pine V2.2 Setup A+B priority baseline", "",
             f"Source: {summary['data_start_utc']} through {summary['data_end_utc']}; processed dataset SHA-256 `{summary['data_sha256']}`.",
             "",
             "Exness BTCUSDm Bid M15; six source gaps remain unfilled. Each usable continuous segment resets account, indicators, pending order, position, and risk permissions. A long, A short, B long, B short priority follows Pine section 43. No standalone setup, parameter, or generic execution code changed.",
             "", "Zero cost is the primary feed comparison. Fixed $10 and $20 spreads are separate completed-trade sensitivities, not tick-exact execution. Commission is zero. Drawdowns are worst within a segment, never a compounded curve across gaps.",
             "", "## Standalone versus combined", "", table(compare),
             "", "## Combined trade attribution", "", table(attributed),
             "", "## Marginal B contribution", "", str(summary["marginal_b_vs_a"]),
             "", "Combined B trade attribution is not the same as combined-minus-A marginal change: A+B changes which trades can occur and the account path.",
             "", "## B displacement", "",
             f"Same-candle B signals suppressed by A priority: {summary['a_priority_suppressed_b_signals']}.",
             f"B candidates blocked by A pending/position: {summary['b_candidates_blocked_by_a_pending']} / {summary['b_candidates_blocked_by_a_position']}.",
             f"Frozen standalone B completed trades among those blocked candidates: {summary['b_standalone_completed_trades_blocked_by_a']}.",
             f"Of those, {summary['b_standalone_completed_trades_blocked_by_a_pending']} coincide with A pending and {summary['b_standalone_completed_trades_blocked_by_a_position']} with an A position.",
             "", "## Yearly", "", table(yearly),
             "", "## Earlier and later", "", table(periods), ""]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    print(json.dumps(build_combined_baseline(), indent=2, default=str)[:5000])
