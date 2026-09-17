"""Frozen Setup B on Exness Bid M15 and exact-timestamp Bitstamp comparison.

The existing engine remains unchanged. Runs are independent per continuous
segment; no order, position, indicator, or balance crosses a missing bar.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd

from engine.backtester import run_backtest
from engine.models import BacktestSettings, Signal
from research.segment_aware_baseline import warmup_plan
from services.exness_m15 import PROCESSED, REPORT, align_price_feeds
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v2_setup_b import BtcV2SetupB, SetupBParameters
from utils.data_validation import continuous_segments, load_ohlcv_csv


STEP = pd.Timedelta(minutes=15)
PARAMS = SetupBParameters()
SETTINGS = BacktestSettings(risk_percent=.25, risk_reward_ratio=3.,
                            commission_percent=0., slippage_percent=0.)


class CaptureSetupB(BtcV2SetupB):
    """Observe final signals after the frozen strategy makes its decision."""

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
                "planned_target_distance": PARAMS.reward_multiple * risk,
                "planned_risk_price": risk,
            })
        return action


def engine_frame(data: pd.DataFrame, *, exness: bool) -> pd.DataFrame:
    if exness:
        time_column = "timestamp_utc" if "timestamp_utc" in data else "timestamp"
        return data[[time_column, "open", "high", "low", "close", "tick_volume"]].rename(
            columns={time_column: "timestamp", "tick_volume": "volume"}).copy()
    return data[["timestamp", "open", "high", "low", "close", "volume"]].copy()


def run_independent_feed(data: pd.DataFrame, feed: str) -> dict:
    signals = []
    trades = []
    orders = []
    segment_rows = []
    for index, segment in enumerate(continuous_segments(data), start=1):
        segment_id = f"{feed}-S{index:02d}"
        plan = warmup_plan(PARAMS, segment.start)
        if segment.candles < plan.minimum_segment_candles:
            segment_rows.append({"segment_id": segment_id, "start": segment.start,
                                 "end": segment.end, "candles": segment.candles,
                                 "usable": False, "reason": "insufficient confirmed-H1/M15 warm-up"})
            continue
        fragment = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        strategy = CaptureSetupB(PARAMS)
        result = run_backtest(fragment, strategy, SETTINGS,
                              trade_start=plan.first_search_time)
        segment_rows.append({"segment_id": segment_id, "start": segment.start,
                             "end": segment.end, "candles": segment.candles,
                             "usable": True, "reason": "",
                             "open_position_at_end": result.open_position is not None,
                             "pending_at_end": result.pending_order is not None})
        for item in strategy.captured_signals:
            signals.append({"feed": feed, "segment_id": segment_id, **item})
        for event in result.order_events:
            orders.append({"feed": feed, "segment_id": segment_id,
                           "signal_time": event.signal_time,
                           "direction": event.direction.value,
                           "status": event.status,
                           "fill_time": event.fill_time,
                           "fill_price": event.fill_price,
                           "cancel_reason": event.cancel_reason})
        for trade in result.trades:
            if not segment.start <= trade.entry_time <= trade.exit_time <= segment.end:
                raise AssertionError("A trade crossed an Exness research segment gap.")
            trades.append({"feed": feed, "segment_id": segment_id,
                           "trade_id": trade.trade_id,
                           "signal_time": trade.signal_time,
                           "entry_time": trade.entry_time,
                           "exit_time": trade.exit_time,
                           "direction": trade.direction.value,
                           "entry_price": trade.entry_price,
                           "structural_stop": trade.stop_loss,
                           "target": trade.take_profit,
                           "exit_price": trade.exit_price,
                           "exit_reason": trade.exit_reason,
                           "quantity": trade.quantity,
                           "planned_risk": trade.initial_risk,
                           "gross_pnl": trade.pnl,
                           "realized_r": trade.realized_r})
    return {"signals": pd.DataFrame(signals), "orders": pd.DataFrame(orders),
            "trades": pd.DataFrame(trades), "segments": pd.DataFrame(segment_rows)}


def summarize_trades(trades: pd.DataFrame, *, net_column: str = "net_pnl",
                     r_column: str = "realized_r") -> dict:
    if trades.empty:
        return {"trades": 0, "long_trades": 0, "short_trades": 0,
                "wins": 0, "losses": 0, "win_rate_percent": 0.,
                "profit_factor": None, "average_r": 0., "net_pnl": 0.}
    pnl = trades[net_column]
    wins = pnl > 1e-9
    losses = pnl < -1e-9
    profit = float(pnl.loc[wins].sum())
    loss = float(pnl.loc[losses].sum())
    return {"trades": len(trades),
            "long_trades": int(trades.direction.eq("LONG").sum()),
            "short_trades": int(trades.direction.eq("SHORT").sum()),
            "wins": int(wins.sum()), "losses": int(losses.sum()),
            "win_rate_percent": float(wins.mean() * 100),
            "profit_factor": profit / abs(loss) if loss else (float("inf") if profit else None),
            "average_r": float(trades[r_column].mean()),
            "net_pnl": float(pnl.sum())}


def signal_matches(exness: pd.DataFrame, bitstamp: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """One-to-one matching: exact, same-side nearby, opposite nearby, unmatched."""
    ex = exness.sort_values("signal_time").reset_index(drop=True)
    bs = bitstamp.sort_values("signal_time").reset_index(drop=True)
    remaining = set(bs.index)
    assigned = {}
    for label in ("EXACT MATCH", "NEAR MATCH", "OPPOSITE"):
        for i, row in ex.iterrows():
            if i in assigned:
                continue
            candidates = []
            for j in remaining:
                other = bs.iloc[j]
                delta = abs(row.signal_time - other.signal_time)
                if label == "EXACT MATCH" and delta == pd.Timedelta(0) and row.direction == other.direction:
                    candidates.append((delta, j))
                elif label == "NEAR MATCH" and pd.Timedelta(0) < delta <= STEP and row.direction == other.direction:
                    candidates.append((delta, j))
                elif label == "OPPOSITE" and delta <= STEP and row.direction != other.direction:
                    candidates.append((delta, j))
            if candidates:
                j = min(candidates)[1]
                assigned[i] = (j, label)
                remaining.remove(j)
    rows = []
    for i, row in ex.iterrows():
        pair = assigned.get(i)
        other = bs.iloc[pair[0]] if pair else None
        label = pair[1] if pair else "EXNESS ONLY"
        rows.append({"classification": label, "exness_signal_time": row.signal_time,
                     "bitstamp_signal_time": other.signal_time if pair else pd.NaT,
                     "exness_direction": row.direction,
                     "bitstamp_direction": other.direction if pair else None,
                     "exness_trigger": row.trigger,
                     "bitstamp_trigger": other.trigger if pair else None,
                     "trigger_difference_usd": row.trigger - other.trigger if pair else None,
                     "stop_difference_usd": row.structural_stop - other.structural_stop if pair else None,
                     "target_distance_difference_usd": row.planned_target_distance - other.planned_target_distance if pair else None,
                     "planned_risk_price_difference_usd_per_btc": row.planned_risk_price - other.planned_risk_price if pair else None})
    for j in sorted(remaining):
        other = bs.iloc[j]
        rows.append({"classification": "BITSTAMP ONLY", "exness_signal_time": pd.NaT,
                     "bitstamp_signal_time": other.signal_time,
                     "exness_direction": None, "bitstamp_direction": other.direction,
                     "exness_trigger": None, "bitstamp_trigger": other.trigger,
                     "trigger_difference_usd": None, "stop_difference_usd": None,
                     "target_distance_difference_usd": None,
                     "planned_risk_price_difference_usd_per_btc": None})
    table = pd.DataFrame(rows)
    counts = Counter(table.classification)
    summary = {"exness_signals": len(ex), "bitstamp_signals": len(bs),
               "exact_matches": counts["EXACT MATCH"],
               "near_matches": counts["NEAR MATCH"],
               "opposite": counts["OPPOSITE"],
               "exness_only": counts["EXNESS ONLY"],
               "bitstamp_only": counts["BITSTAMP ONLY"]}
    summary["exact_percent_of_exness"] = summary["exact_matches"] / len(ex) * 100 if len(ex) else 0.
    summary["near_percent_of_exness"] = summary["near_matches"] / len(ex) * 100 if len(ex) else 0.
    summary["opposite_percent_of_exness"] = summary["opposite"] / len(ex) * 100 if len(ex) else 0.
    summary["exness_only_percent"] = summary["exness_only"] / len(ex) * 100 if len(ex) else 0.
    summary["bitstamp_only_percent"] = summary["bitstamp_only"] / len(bs) * 100 if len(bs) else 0.
    return table, summary


def trade_matches(matched_signals: pd.DataFrame, exness: dict, bitstamp: dict) -> pd.DataFrame:
    def trade_lookup(frame):
        return {(r.signal_time, r.direction): r for r in frame.itertuples(index=False)}

    def filled_lookup(frame):
        return {(r.signal_time, r.direction) for r in frame.itertuples(index=False)
                if r.status == "triggered"}

    ex_trade = trade_lookup(exness["trades"])
    bs_trade = trade_lookup(bitstamp["trades"])
    ex_filled = filled_lookup(exness["orders"])
    bs_filled = filled_lookup(bitstamp["orders"])
    rows = []
    for pair in matched_signals.itertuples(index=False):
        if pair.classification != "EXACT MATCH":
            continue
        key_ex = (pair.exness_signal_time, pair.exness_direction)
        key_bs = (pair.bitstamp_signal_time, pair.bitstamp_direction)
        left, right = ex_trade.get(key_ex), bs_trade.get(key_bs)
        if left is not None and right is not None:
            outcome = ("both win" if left.gross_pnl > 0 and right.gross_pnl > 0 else
                       "both loss" if left.gross_pnl < 0 and right.gross_pnl < 0 else
                       "Exness win / Bitstamp loss" if left.gross_pnl > 0 else
                       "Exness loss / Bitstamp win" if right.gross_pnl > 0 else "other")
        else:
            outcome = "not both completed"
        rows.append({"signal_time": pair.exness_signal_time,
                     "same_signal": True, "same_direction": True,
                     "exness_filled": key_ex in ex_filled,
                     "bitstamp_filled": key_bs in bs_filled,
                     "same_fill_status": (key_ex in ex_filled) == (key_bs in bs_filled),
                     "exness_completed": left is not None,
                     "bitstamp_completed": right is not None,
                     "entry_difference_usd": left.entry_price - right.entry_price if left and right else None,
                     "stop_difference_usd": left.structural_stop - right.structural_stop if left and right else None,
                     "target_difference_usd": left.target - right.target if left and right else None,
                     "planned_risk_dollars_difference": left.planned_risk - right.planned_risk if left and right else None,
                     "outcome": outcome})
    return pd.DataFrame(rows)


def price_cost_view(trades: pd.DataFrame, *, spread_bars: pd.Series | None = None,
                    fixed_spread: float | None = None) -> pd.DataFrame:
    """Reprice native Bid-OHLC trades; bar minimum is explicitly optimistic."""
    if spread_bars is not None and fixed_spread is not None:
        raise ValueError("Bar-minimum and fixed spread are separate research views.")
    result = trades.copy()
    if spread_bars is not None:
        result["spread_descriptor"] = result.entry_time.map(spread_bars)
        if result.spread_descriptor.isna().any():
            raise ValueError("A native trade lacks its entry-bar minimum spread descriptor.")
    else:
        result["spread_descriptor"] = fixed_spread or 0.
    result["spread_cost"] = result.spread_descriptor * result.quantity
    result["net_pnl"] = result.gross_pnl - result.spread_cost
    result["realized_r_costed"] = result.net_pnl / result.planned_risk
    return result


def _result_row(feed: str, scope: str, view: str, signals: pd.DataFrame,
                orders: pd.DataFrame, trades: pd.DataFrame, *, costed: bool = False) -> dict:
    times = (trades.signal_time if not trades.empty else pd.Series(dtype="datetime64[ns, UTC]"))
    stats = summarize_trades(trades, net_column="net_pnl" if costed else "gross_pnl",
                             r_column="realized_r_costed" if costed else "realized_r")
    status = Counter(orders.status) if not orders.empty else Counter()
    return {"feed": feed, "scope": scope, "cost_view": view,
            "signals": len(signals), "pending_orders": len(orders),
            "filled_orders": status["triggered"],
            "expired_orders": status["expired"],
            "cancelled_orders": status["cancelled"],
            "spread_cost": float(trades.spread_cost.sum()) if costed else 0.,
            **stats}


def build_native_validation(exness_path: Path = PROCESSED,
                            bitstamp_path: Path = CANONICAL_DATA_FILE,
                            output_dir: Path = REPORT) -> dict:
    exness_bars = pd.read_csv(exness_path, parse_dates=["timestamp_utc"])
    bitstamp_bars = load_ohlcv_csv(bitstamp_path)
    common, price_stats = align_price_feeds(exness_bars, bitstamp_bars)
    output_dir.mkdir(parents=True, exist_ok=True)
    common.to_csv(output_dir / "price_feed_comparison.csv", index=False)
    ex_full = run_independent_feed(engine_frame(exness_bars, exness=True), "exness_native")
    ex_common = run_independent_feed(engine_frame(common.rename(columns={
        "open_exness": "open", "high_exness": "high", "low_exness": "low",
        "close_exness": "close"}), exness=True), "exness_overlap")
    bs_common = run_independent_feed(engine_frame(common.rename(columns={
        "open_bitstamp": "open", "high_bitstamp": "high", "low_bitstamp": "low",
        "close_bitstamp": "close"}), exness=False), "bitstamp_overlap")
    signal_table, signal_stats = signal_matches(ex_common["signals"], bs_common["signals"])
    signal_table.to_csv(output_dir / "signal_comparison.csv", index=False)
    trade_table = trade_matches(signal_table, ex_common, bs_common)
    trade_table.to_csv(output_dir / "trade_comparison.csv", index=False)
    bar_spreads = exness_bars.set_index("timestamp_utc").spread_price
    base = ex_full["trades"]
    cost_views = {"zero_cost": price_cost_view(base),
                  "bar_minimum_spread_lower_bound": price_cost_view(base, spread_bars=bar_spreads)}
    for spread in (10., 15., 20., 30.):
        cost_views[f"fixed_spread_${int(spread)}"] = price_cost_view(base, fixed_spread=spread)
    rows = []
    for view, trades in cost_views.items():
        rows.append(_result_row("exness_native", "full_native", view,
                                ex_full["signals"], ex_full["orders"], trades,
                                costed=view != "zero_cost"))
        for label, predicate in (("earlier_2023_2024", trades.signal_time.dt.year <= 2024),
                                 ("later_2025_2026", trades.signal_time.dt.year >= 2025)):
            subset = trades.loc[predicate]
            signal_subset = ex_full["signals"].loc[
                (ex_full["signals"].signal_time.dt.year <= 2024) if label.startswith("earlier")
                else (ex_full["signals"].signal_time.dt.year >= 2025)]
            order_subset = ex_full["orders"].loc[
                (ex_full["orders"].signal_time.dt.year <= 2024) if label.startswith("earlier")
                else (ex_full["orders"].signal_time.dt.year >= 2025)]
            rows.append(_result_row("exness_native", label, view,
                                    signal_subset, order_subset, subset,
                                    costed=view != "zero_cost"))
    for feed, run in (("exness_overlap", ex_common), ("bitstamp_overlap", bs_common)):
        rows.append(_result_row(feed, "exact_common_timestamps", "zero_cost",
                                run["signals"], run["orders"], run["trades"]))
    result_table = pd.DataFrame(rows)
    result_table.to_csv(output_dir / "native_setup_b_results.csv", index=False)
    yearly = []
    for view in ("zero_cost", "bar_minimum_spread_lower_bound"):
        priced = cost_views[view]
        for year in range(2023, 2027):
            subset = priced.loc[priced.signal_time.dt.year == year]
            yearly.append({"year": year, "partial_year": year == 2023 or year == 2026,
                           "cost_view": view,
                           **summarize_trades(subset,
                                              net_column="net_pnl" if view != "zero_cost" else "gross_pnl",
                                              r_column="realized_r_costed" if view != "zero_cost" else "realized_r")})
    pd.DataFrame(yearly).to_csv(output_dir / "yearly_results.csv", index=False)
    summary = {"price_feed": price_stats, "signals": signal_stats,
               "trade_matches": {"exact_signal_pairs": len(trade_table),
                                 "same_fill_status": int(trade_table.same_fill_status.sum()),
                                 "both_completed": int((trade_table.exness_completed & trade_table.bitstamp_completed).sum()),
                                 "outcomes": trade_table.outcome.value_counts().to_dict()},
               "exness_segments": ex_full["segments"].to_dict("records"),
               "comparison_segments": ex_common["segments"].to_dict("records"),
               "native_results": result_table.to_dict("records")}
    (output_dir / "native_validation_summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    _write_markdown(output_dir / "native_validation_summary.md", summary, result_table,
                    pd.DataFrame(yearly))
    return summary


def _write_markdown(path: Path, summary: dict, results: pd.DataFrame,
                    yearly: pd.DataFrame) -> None:
    price = summary["price_feed"]
    signals = summary["signals"]
    lines = ["# Exness BTCUSDm native-price Setup B validation", "",
             "**BROKER-NATIVE PRICE DATA.** The Setup B signal feed uses actual Exness BTCUSDm Bid M15 bars. Strategy defaults, H1 confirmation, pending entry, structural stop, 3R target, and generic execution rules are unchanged.",
             "", "**BAR SPREAD COST = LOWER-BOUND RESEARCH, NOT TICK-EXACT EXECUTION.** MT5 M15 SPREAD records a bar minimum. Charging one entry-bar minimum spread per completed trade is optimistic. The $10/$15/$20/$30 scenarios are separate fixed-spread sensitivities; none claims the same spread throughout history. Zero-cost results isolate the broker price feed.",
             "", "Each contiguous data segment is backtested independently after the programmatic confirmed-H1/M15 warm-up; account and indicator state reset at gaps. An open position at a segment's last candle remains open and is excluded from completed-trade PnL under existing end-of-test semantics. Results pooled across segments are trade sums, not one compounded equity curve.",
             "", f"Exact timestamp intersection: {price['common_candles']:,} candles; Exness-only "
             f"{price['exness_only_timestamps']:,}; Bitstamp-only {price['bitstamp_only_timestamps']:,}. "
             f"Close correlation {price['close_correlation']:.6f}; adjacent-return correlation "
             f"{price['return_correlation']:.6f}; median absolute close difference "
             f"${price['median_absolute_close_difference_usd']:.2f} "
             f"({price['median_relative_close_difference_percent']:.4f}%).",
             "", f"Common-window final signals: Exness {signals['exness_signals']}, Bitstamp "
             f"{signals['bitstamp_signals']}; exact {signals['exact_matches']}, near "
             f"{signals['near_matches']}, opposite {signals['opposite']}, Exness-only "
             f"{signals['exness_only']}, Bitstamp-only {signals['bitstamp_only']}. "
             f"Exact matches are {signals['exact_percent_of_exness']:.2f}% of Exness signals; "
             f"near {signals['near_percent_of_exness']:.2f}%, opposite "
             f"{signals['opposite_percent_of_exness']:.2f}%, Exness-only "
             f"{signals['exness_only_percent']:.2f}%; Bitstamp-only "
             f"{signals['bitstamp_only_percent']:.2f}% of Bitstamp signals.",
             "", "## Frozen Setup B results", "",
             "| Feed | Scope | Cost view | Signals | Fills | Trades | Long | Short | WR % | PF | Average R | Net PnL |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in results.itertuples(index=False):
        pf = "—" if pd.isna(row.profit_factor) else f"{row.profit_factor:.4f}"
        lines.append(f"| {row.feed} | {row.scope} | {row.cost_view} | {row.signals} | "
                     f"{row.filled_orders} | {row.trades} | {row.long_trades} | "
                     f"{row.short_trades} | {row.win_rate_percent:.2f} | {pf} | "
                     f"{row.average_r:.4f} | {row.net_pnl:.2f} |")
    lines += ["", "## Exness native yearly", "",
              "| Year | Cost view | Trades | WR % | PF | Average R | Net PnL |",
              "|---|---|---:|---:|---:|---:|---:|"]
    for row in yearly.itertuples(index=False):
        pf = "—" if pd.isna(row.profit_factor) else f"{row.profit_factor:.4f}"
        lines.append(f"| {row.year}{' partial' if row.partial_year else ''} | {row.cost_view} | "
                     f"{row.trades} | {row.win_rate_percent:.2f} | {pf} | "
                     f"{row.average_r:.4f} | {row.net_pnl:.2f} |")
    lines += ["", "Price correlation does not imply signal or trade agreement. This remains an M15 OHLC execution-convention comparison, not a tick-replayed broker execution backtest. No parameter was selected or optimized.", ""]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    print(json.dumps(build_native_validation(), indent=2, default=str)[:3000])
