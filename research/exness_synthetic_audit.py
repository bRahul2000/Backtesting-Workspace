"""Order-level audit of research-only synthetic Bid/Ask Setup B execution.

Historical prices are Bitstamp throughout. This module reads the frozen Phase
4E candidates and never changes the active strategy or generic engine.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
import json
import math

import pandas as pd

from engine.backtester import run_backtest
from engine.models import BacktestSettings, Direction, OrderEvent, Signal, Trade
from research.exness_cost_calibrated import (LABEL, OUTPUT as COST_OUTPUT,
                                             SETTINGS, run_synthetic_segment)
from research.exness_cost_recalibration import CALIBRATION
from research.segment_aware_baseline import warmup_plan
from research.setup_b_entry_research import (EntrySpec, ResearchSetupB,
                                             OUT as ENTRY_RESEARCH_OUT,
                                             read_frozen_candidates)
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v2_setup_b import SetupBParameters
from utils.data_validation import continuous_segments, load_ohlcv_csv


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/broker/exness/synthetic_audit"
SPREADS = (5., 10., 15., 20.)
CUTOFF = pd.Timestamp("2025-01-01", tz="UTC")
PRICE_TOLERANCE = .005  # BTCUSDm two-decimal tick precision.
OLD_SETTINGS = BacktestSettings(risk_percent=.25, risk_reward_ratio=3.,
                                commission_percent=.05, slippage_percent=0.)


@dataclass
class Case:
    candidate: str
    spread: float | None
    signals: int
    orders: pd.DataFrame
    trades: pd.DataFrame
    same_bar: pd.DataFrame
    signal_rows: pd.DataFrame
    states: dict[tuple[str, pd.Timestamp], str]


class AuditSetupB(ResearchSetupB):
    """Capture frozen decisions and the pre-decision state without changing them."""

    def __init__(self, spec: EntrySpec, *, capture_states: bool):
        self.capture_states = capture_states
        super().__init__(spec)

    def reset(self) -> None:
        super().reset()
        self.signal_rows: list[dict] = []
        self.state_rows: dict[pd.Timestamp, str] = {}

    def on_candle(self, candle):
        if self.capture_states:
            state = self.execution_state
            descriptions = []
            if state is not None and state.position is not None:
                pos = state.position
                descriptions.append(f"active {pos.direction.value} position from {pos.entry_time} "
                                    f"(signal {pos.signal_time})")
            if state is not None and state.pending_order is not None:
                order = state.pending_order
                descriptions.append(f"active {order.direction.value} pending order from "
                                    f"signal {order.signal_time}")
            if self.risk.lock_reason:
                descriptions.append(f"permission lock: {self.risk.lock_reason}")
            self.state_rows[candle.timestamp + pd.Timedelta(minutes=15)] = (
                "; ".join(descriptions) if descriptions else "flat, no pending order or active lock")
        action = super().on_candle(candle)
        if isinstance(action, Signal):
            self.signal_rows.append({"signal_time": candle.timestamp + pd.Timedelta(minutes=15),
                                     "direction": action.direction.value})
        return action


def frozen_specs() -> dict[str, EntrySpec]:
    frozen = read_frozen_candidates(ENTRY_RESEARCH_OUT / "frozen_candidates.json")
    if [item["id"] for item in frozen["candidates"]] != ["C2", "C3", "minimum_adx=25"]:
        raise ValueError("Frozen Phase 4E candidate identities changed.")
    return {"ORIGINAL": EntrySpec(), **{
        ("ADX25" if item["id"] == "minimum_adx=25" else item["id"]):
        EntrySpec.from_dict(item["changes"]) for item in frozen["candidates"]}}


def usable_frames(data: pd.DataFrame) -> list[tuple[str, pd.DataFrame, pd.Timestamp]]:
    frames = []
    for number, segment in enumerate(continuous_segments(data), 1):
        plan = warmup_plan(SetupBParameters(), segment.start)
        if segment.candles >= plan.minimum_segment_candles:
            frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
            frames.append((f"S{number:02d}", frame, plan.first_search_time))
    return frames


def classify_order(original: dict | None, synthetic: dict | None,
                   tolerance: float = PRICE_TOLERANCE) -> str:
    """Disjoint priority: exclusive fill, timing, price, exact, shared terminal state."""
    o = original or {}
    s = synthetic or {}
    of = o.get("status") == "triggered"
    sf = s.get("status") == "triggered"
    if sf and not of:
        return "SYNTHETIC_ONLY_FILL"
    if of and not sf:
        return "ORIGINAL_ONLY_FILL"
    if of and sf:
        if o["fill_time"] != s["fill_time"]:
            return "TIMING_CHANGED_FILL"
        if abs(o["fill_price"] - s["fill_price"]) > tolerance:
            return "PRICE_CHANGED_FILL"
        return "SAME_FILL"
    if o.get("status") == s.get("status") == "expired":
        return "EXPIRED_BOTH"
    if o.get("status") == s.get("status") == "cancelled":
        return "CANCELED_BOTH"
    return "OTHER_ORDER_STATE"


def _event_row(segment_id: str, event: OrderEvent) -> dict:
    return {"segment_id": segment_id, "signal_time": event.signal_time,
            "direction": event.direction.value, "setup_id": event.setup_id,
            "created_time": event.created_time, "trigger_price": event.trigger_price,
            "stop_price": event.stop_price, "status": event.status,
            "cancel_reason": event.cancel_reason, "fill_time": event.fill_time,
            "fill_price": event.fill_price}


def _trade_row(segment_id: str, trade: Trade) -> dict:
    direction = trade.direction.value
    sign = 1 if direction == "LONG" else -1
    expected = sign * (trade.exit_price - trade.entry_price) * trade.quantity
    if trade.entry_commission != 0 or trade.exit_commission != 0 or not math.isclose(
            trade.pnl, expected, rel_tol=1e-10, abs_tol=1e-7):
        raise AssertionError("Synthetic execution charged commission or an extra spread.")
    target = trade.entry_price + sign * 3 * abs(trade.entry_price - trade.stop_loss)
    if not math.isclose(trade.take_profit, target, rel_tol=1e-10, abs_tol=1e-7):
        raise AssertionError("Synthetic target is not 3R from actual quote-side fill.")
    return {"segment_id": segment_id, "trade_id": trade.trade_id,
            "signal_time": trade.signal_time, "direction": direction,
            "setup_id": trade.setup_id, "entry_time": trade.entry_time,
            "entry_price": trade.entry_price, "exit_time": trade.exit_time,
            "exit_price": trade.exit_price, "exit_reason": trade.exit_reason,
            "stop_price": trade.stop_loss, "target_price": trade.take_profit,
            "risk_distance": abs(trade.entry_price - trade.stop_loss),
            "initial_risk": trade.initial_risk, "quantity": trade.quantity,
            "pnl": trade.pnl, "realized_r": trade.realized_r,
            "entry_commission": trade.entry_commission,
            "exit_commission": trade.exit_commission,
            "pending_trigger": trade.pending_trigger_price}


def same_bar_row(segment_id: str, trade: Trade, bid_bars: pd.DataFrame,
                 spread: float) -> dict:
    if trade.entry_time != trade.exit_time:
        return {}
    bar = bid_bars.loc[trade.entry_time]
    if trade.direction is Direction.LONG:
        stop_hit = bar.low <= trade.stop_loss
        target_hit = bar.high >= trade.take_profit
    else:
        stop_hit = bar.high + spread >= trade.stop_loss
        target_hit = bar.low + spread <= trade.take_profit
    return {"segment_id": segment_id, "signal_time": trade.signal_time,
            "direction": trade.direction.value, "entry_time": trade.entry_time,
            "stop_touched": bool(stop_hit), "target_touched": bool(target_hit),
            "both_touched": bool(stop_hit and target_hit),
            "exit_reason": trade.exit_reason}


def run_case(frames: list[tuple[str, pd.DataFrame, pd.Timestamp]], candidate: str,
             spec: EntrySpec, spread: float | None,
             *, capture_states: bool = False) -> Case:
    if spread is not None and spread < 0:
        raise ValueError("Spread must be nonnegative.")
    orders, trades, same_bar = [], [], []
    signals = 0
    signal_rows = []
    states = {}
    for segment_id, frame, first_search in frames:
        strategy = AuditSetupB(spec, capture_states=capture_states)
        if spread is None:
            result = run_backtest(frame, strategy, OLD_SETTINGS, trade_start=first_search)
        else:
            result = run_synthetic_segment(frame, strategy, spread, first_search, SETTINGS)
        signals += (strategy.diagnostics["Final Long Signals"] +
                    strategy.diagnostics["Final Short Signals"])
        signal_rows.extend({"segment_id": segment_id, **row} for row in strategy.signal_rows)
        states.update({(segment_id, stamp): value for stamp, value in strategy.state_rows.items()})
        orders.extend(_event_row(segment_id, event) for event in result.order_events)
        bid_bars = frame.set_index("timestamp")
        for trade in result.trades:
            if spread is None:
                trades.append({"segment_id": segment_id, "trade_id": trade.trade_id,
                               "signal_time": trade.signal_time,
                               "direction": trade.direction.value, "setup_id": trade.setup_id,
                               "entry_time": trade.entry_time, "entry_price": trade.entry_price,
                               "exit_time": trade.exit_time, "exit_price": trade.exit_price,
                               "exit_reason": trade.exit_reason, "stop_price": trade.stop_loss,
                               "target_price": trade.take_profit,
                               "risk_distance": abs(trade.entry_price - trade.stop_loss),
                               "initial_risk": trade.initial_risk, "quantity": trade.quantity,
                               "pnl": trade.pnl, "realized_r": trade.realized_r,
                               "entry_commission": trade.entry_commission,
                               "exit_commission": trade.exit_commission,
                               "pending_trigger": trade.pending_trigger_price})
            else:
                trades.append(_trade_row(segment_id, trade))
                item = same_bar_row(segment_id, trade, bid_bars, spread)
                if item:
                    same_bar.append(item)
    if signals != len(signal_rows):
        raise AssertionError("Captured signal count differs from strategy diagnostics.")
    return Case(candidate, spread, signals, pd.DataFrame(orders),
                pd.DataFrame(trades), pd.DataFrame(same_bar),
                pd.DataFrame(signal_rows), states)


def _records(frame: pd.DataFrame) -> dict[tuple, dict]:
    if frame.empty:
        return {}
    result = {}
    for row in frame.to_dict("records"):
        key = (row["segment_id"], row["signal_time"], row["direction"], row["setup_id"])
        if key in result:
            raise AssertionError(f"Duplicate pending-order reconciliation key: {key}")
        result[key] = row
    return result


def explain_exclusive(row: dict, bid: pd.Series, spread: float,
                      *, synthetic_only: bool) -> tuple[str, str]:
    """Explain quote-side trigger or state divergence with concrete observed status."""
    direction = row["direction"]
    trigger = float(row["trigger_price"])
    original_status = row.get("original_status") or "ORDER_NOT_CREATED"
    synthetic_status = row.get("synthetic_status") or "ORDER_NOT_CREATED"
    if synthetic_only and direction == "LONG" and bid.high < trigger <= bid.high + spread:
        return "LONG_ASK_TRIGGER", (f"Ask high {bid.high + spread:.2f} reached {trigger:.2f}; "
                                    f"Bid high {bid.high:.2f} did not. Original status: {original_status}.")
    if synthetic_only and direction == "LONG" and bid.open + spread >= trigger:
        return "GAP_EFFECT", (f"Ask opened at {bid.open + spread:.2f} through {trigger:.2f}; "
                              f"original status: {original_status}.")
    if direction == "SHORT" and original_status != "ORDER_NOT_CREATED" and synthetic_status != "ORDER_NOT_CREATED":
        return "SHORT_BID_TRIGGER", (f"Both orders existed; sell stop is Bid-triggered in both models. "
                                     f"Bid low {bid.low:.2f}, trigger {trigger:.2f}; "
                                     f"original={original_status}, synthetic={synthetic_status}. "
                                     "This requires an order-state audit.")
    if direction == "SHORT":
        return "OTHER", (f"Sell stop uses Bid in both models; Bid low {bid.low:.2f}, "
                         f"trigger {trigger:.2f}. One model had no pending order: "
                         f"original={original_status}, synthetic={synthetic_status}.")
    return "OTHER", (f"Different order/position/account state or order timing: "
                     f"original={original_status}, synthetic={synthetic_status}; "
                     f"Bid OHLC={bid.open:.2f}/{bid.high:.2f}/{bid.low:.2f}/{bid.close:.2f}, "
                     f"Ask OHLC={bid.open+spread:.2f}/{bid.high+spread:.2f}/"
                     f"{bid.low+spread:.2f}/{bid.close+spread:.2f}, trigger={trigger:.2f}.")


def reconcile(original: Case, synthetic: Case,
              frames: list[tuple[str, pd.DataFrame, pd.Timestamp]],
              spread: float) -> pd.DataFrame:
    o, s = _records(original.orders), _records(synthetic.orders)
    prices = {sid: frame.set_index("timestamp") for sid, frame, _ in frames}
    rows = []
    for key in sorted(o.keys() | s.keys()):
        old, new = o.get(key), s.get(key)
        category = classify_order(old, new)
        row = {"segment_id": key[0], "signal_time": key[1], "direction": key[2],
               "setup_id": key[3], "classification": category,
               "original_status": old["status"] if old else None,
               "synthetic_status": new["status"] if new else None,
               "original_fill_time": old["fill_time"] if old else pd.NaT,
               "synthetic_fill_time": new["fill_time"] if new else pd.NaT,
               "original_fill_price": old["fill_price"] if old else None,
               "synthetic_fill_price": new["fill_price"] if new else None,
               "original_cancel_reason": old["cancel_reason"] if old else None,
               "synthetic_cancel_reason": new["cancel_reason"] if new else None,
               "created_time": (new or old)["created_time"],
               "trigger_price": (new or old)["trigger_price"],
               "structural_stop": (new or old)["stop_price"]}
        row["original_signal_state"] = original.states.get((key[0], key[1]), "state unavailable")
        row["synthetic_signal_state"] = synthetic.states.get((key[0], key[1]), "state unavailable")
        if category in ("SYNTHETIC_ONLY_FILL", "ORIGINAL_ONLY_FILL"):
            fill_time = (new or old)["fill_time"] if category == "SYNTHETIC_ONLY_FILL" else old["fill_time"]
            bid = prices[key[0]].loc[fill_time]
            row.update({"audit_fill_time": fill_time, "bid_open": bid.open,
                        "bid_high": bid.high, "bid_low": bid.low,
                        "bid_close": bid.close, "ask_open": bid.open + spread,
                        "ask_high": bid.high + spread, "ask_low": bid.low + spread,
                        "ask_close": bid.close + spread, "spread": spread})
            reason, explanation = explain_exclusive(row, bid, spread,
                                                     synthetic_only=category == "SYNTHETIC_ONLY_FILL")
            row["reason"] = reason
            row["explanation"] = (explanation + " Original at signal: " +
                                  row["original_signal_state"] + ". Synthetic at signal: " +
                                  row["synthetic_signal_state"] + ".")
        elif category == "OTHER_ORDER_STATE":
            row["reason"] = "STATE_DIVERGENCE"
            row["explanation"] = (
                f"Original order {row['original_status'] or 'not created'}; synthetic order "
                f"{row['synthetic_status'] or 'not created'}. Original at signal: "
                f"{row['original_signal_state']}. Synthetic at signal: "
                f"{row['synthetic_signal_state']}.")
        rows.append(row)
    table = pd.DataFrame(rows)
    table["prior_difference_signal_time"] = pd.Series(
        pd.NaT, index=table.index, dtype="datetime64[ns, UTC]")
    table["prior_difference_category"] = None
    for _, group in table.groupby("segment_id", sort=False):
        prior = None
        for index in group.sort_values("signal_time").index:
            if prior is not None:
                table.at[index, "prior_difference_signal_time"] = table.at[prior, "signal_time"]
                table.at[index, "prior_difference_category"] = table.at[prior, "classification"]
                if table.at[index, "classification"] in ("SYNTHETIC_ONLY_FILL", "ORIGINAL_ONLY_FILL",
                                                           "OTHER_ORDER_STATE"):
                    table.at[index, "explanation"] += (
                        f" Prior divergent order: {table.at[prior, 'signal_time']} "
                        f"({table.at[prior, 'classification']}).")
            if table.at[index, "classification"] in ("SYNTHETIC_ONLY_FILL", "ORIGINAL_ONLY_FILL",
                                                      "TIMING_CHANGED_FILL", "PRICE_CHANGED_FILL",
                                                      "OTHER_ORDER_STATE"):
                prior = index
    return table


def price_effects(original: Case, synthetic: Case) -> tuple[pd.DataFrame, pd.DataFrame]:
    old, new = _records(original.trades), _records(synthetic.trades)
    rows = []
    for key in sorted(old.keys() & new.keys()):
        a, b = old[key], new[key]
        rows.append({"segment_id": key[0], "signal_time": key[1],
                     "direction": key[2], "setup_id": key[3],
                     "entry_price_delta": b["entry_price"] - a["entry_price"],
                     "exit_price_delta": b["exit_price"] - a["exit_price"],
                     "risk_distance_delta": b["risk_distance"] - a["risk_distance"],
                     "target_price_delta": b["target_price"] - a["target_price"],
                     "stop_price_delta": b["stop_price"] - a["stop_price"],
                     "realized_r_delta": b["realized_r"] - a["realized_r"]})
    detail = pd.DataFrame(rows)
    summaries = []
    for direction, part in [("ALL", detail), *[(side, detail.loc[detail.direction == side])
                                                for side in ("LONG", "SHORT")]]:
        for field in ("entry_price_delta", "exit_price_delta", "risk_distance_delta",
                      "target_price_delta", "stop_price_delta", "realized_r_delta"):
            values = part[field].abs()
            summaries.append({"direction": direction, "field": field, "count": len(values),
                              "mean_abs": values.mean(), "median_abs": values.median(),
                              "p75_abs": values.quantile(.75), "p90_abs": values.quantile(.9),
                              "p95_abs": values.quantile(.95), "max_abs": values.max()})
    return detail, pd.DataFrame(summaries)


def _period(frame: pd.DataFrame, scope: str) -> pd.DataFrame:
    if scope == "development":
        return frame.loc[frame.signal_time < CUTOFF]
    if scope == "forward-validation":
        return frame.loc[frame.signal_time >= CUTOFF]
    return frame


def _max_losses(frame: pd.DataFrame) -> int:
    longest = 0
    for _, group in frame.groupby("segment_id"):
        current = 0
        for pnl in group.sort_values(["exit_time", "trade_id"]).pnl:
            current = current + 1 if pnl < 0 else 0
            longest = max(longest, current)
    return longest


def _worst_dd(frame: pd.DataFrame) -> float:
    worst = 0.
    for _, group in frame.groupby("segment_id"):
        balance = peak = 10_000.
        for pnl in group.sort_values(["exit_time", "trade_id"]).pnl:
            balance += pnl
            peak = max(peak, balance)
            worst = max(worst, (peak - balance) / peak * 100)
    return worst


def trade_metrics(frame: pd.DataFrame) -> dict:
    if frame.empty:
        return {"trades": 0, "long_trades": 0, "short_trades": 0,
                "win_rate_percent": 0., "profit_factor": None, "average_r": 0.,
                "median_r": 0., "net_pnl": 0., "worst_segment_dd_percent": 0.,
                "maximum_consecutive_losses": 0}
    wins = frame.pnl > 0
    profit = frame.loc[wins, "pnl"].sum()
    loss = -frame.loc[frame.pnl < 0, "pnl"].sum()
    return {"trades": len(frame), "long_trades": int(frame.direction.eq("LONG").sum()),
            "short_trades": int(frame.direction.eq("SHORT").sum()),
            "win_rate_percent": float(wins.mean() * 100),
            "profit_factor": float(profit / loss) if loss else (float("inf") if profit else None),
            "average_r": float(frame.realized_r.mean()),
            "median_r": float(frame.realized_r.median()),
            "net_pnl": float(frame.pnl.sum()),
            "worst_segment_dd_percent": _worst_dd(frame),
            "maximum_consecutive_losses": _max_losses(frame)}


def case_rows(case: Case, scope: str) -> dict:
    trades = _period(case.trades, scope)
    orders = _period(case.orders, scope)
    return {"label": LABEL, "candidate": case.candidate,
            "spread_usd_per_btc": case.spread, "scope": scope,
            "signals": len(_period(case.signal_rows, scope)),
            "pending_fills": int(orders.status.eq("triggered").sum()),
            "pending_expiries": int(orders.status.eq("expired").sum()),
            **trade_metrics(trades)}


def _write_summary(path: Path, reconcile_table: pd.DataFrame,
                   results: pd.DataFrame, sensitivity: pd.DataFrame,
                   same_bar: pd.DataFrame, flags: pd.DataFrame,
                   effects: pd.DataFrame, models: pd.DataFrame) -> None:
    counts = Counter(reconcile_table.classification)
    original = results.loc[(results.candidate == "ORIGINAL") &
                           (results.scope == "all")].iloc[0]
    lines = [f"# {LABEL} — synthetic execution audit", "",
             "RESEARCH ONLY · BITSTAMP HISTORICAL PRICES · SYNTHETIC EXNESS-LIKE BID/ASK. This is not a broker-native historical Exness backtest.",
             "", "Calibration: five Exness Standard BTCUSDm samples; 541,647 real ticks across 120 observed hours; observed spread $10/BTC. Synthetic tests also use $5, $15, and $20 as sensitivity scenarios. Commission is $0.",
             "", "## Order reconciliation hierarchy", "",
             "One primary category per (segment, signal timestamp, direction, setup ID): synthetic-only fill; original-only fill; timing-changed fill; price-changed fill; exact same fill; expired in both; canceled in both; otherwise different order state. A same-bar fill with a changed price is PRICE_CHANGED_FILL, not SAME_FILL. Counts are disjoint.",
             "", "| Category | Orders |", "|---|---:|"]
    for category in ("SAME_FILL", "SYNTHETIC_ONLY_FILL", "ORIGINAL_ONLY_FILL",
                     "TIMING_CHANGED_FILL", "PRICE_CHANGED_FILL", "EXPIRED_BOTH",
                     "CANCELED_BOTH", "OTHER_ORDER_STATE"):
        lines.append(f"| {category} | {counts[category]} |")
    lines += ["", "## Quote-side mathematics", "",
              "Long signals use Bid; buy-stop trigger and entry use Ask = Bid + spread; long SL, TP, and exit use Bid. Short signals, sell-stop trigger, and entry use Bid; short SL, TP, and exit use Ask.",
              "", "Target is derived from actual synthetic fill to original structural stop at 3R. The replay reuses the audited conservative same-bar SL-first decision function.",
              "", "Every completed synthetic trade was checked against direction × (exit price − entry price) × BTC quantity. Entry and exit commissions were zero. No post-trade spread was deducted. The one-spread equivalent in Phase 4F-B1 is descriptive and already embedded in these prices. DOUBLE-SPREAD CHECK: PASS.",
              "", "## Three-model comparison, identical Bitstamp source", "",
              "The single-price model uses 0.05% commission per side. Cost-only keeps its frozen fills and applies one $10 spread per BTC. Synthetic execution replays quote-side fills and exits with zero commission.",
              "", _markdown_table(models.round(4)),
              "", "## Original $10 synthetic result", "",
              f"Completed trades {original.trades}; PF {original.profit_factor:.4f}; average R {original.average_r:.4f}; net PnL ${original.net_pnl:.2f}; worst continuous-segment DD {original.worst_segment_dd_percent:.4f}%.",
              "", "## Same-bar completed trades", "",
              f"Entry-candle stop touched: {int(same_bar.stop_touched.sum()) if not same_bar.empty else 0}; target touched: {int(same_bar.target_touched.sum()) if not same_bar.empty else 0}; both touched: {int(same_bar.both_touched.sum()) if not same_bar.empty else 0}. These touch counts can overlap and use the appropriate exit quote side.",
              "", "## Matched-trade absolute price/R effects", "",
              "| Direction | Field | Count | Mean | Median | P75 | P90 | P95 | Max |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for row in effects.itertuples(index=False):
        lines.append(f"| {row.direction} | {row.field} | {row.count} | {row.mean_abs:.4f} | {row.median_abs:.4f} | {row.p75_abs:.4f} | {row.p90_abs:.4f} | {row.p95_abs:.4f} | {row.max_abs:.4f} |")
    lines += ["", "## Frozen candidate $10 development and forward results", "",
              "| Candidate | Scope | Signals | Fills | Trades | Long | Short | WR % | PF | Avg R | Median R | Net | Worst DD % | Max losses |",
              "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in results.itertuples(index=False):
        lines.append(f"| {row.candidate} | {row.scope} | {row.signals if pd.notna(row.signals) else '—'} | {row.pending_fills} | {row.trades} | {row.long_trades} | {row.short_trades} | {row.win_rate_percent:.2f} | {row.profit_factor:.4f} | {row.average_r:.4f} | {row.median_r:.4f} | {row.net_pnl:.2f} | {row.worst_segment_dd_percent:.4f} | {row.maximum_consecutive_losses} |")
    lines += ["", "## Robustness flags (descriptive; no selection)", "",
              _markdown_table(flags), "",
              "## Synthetic spread sensitivity", "",
              _markdown_table(sensitivity[["candidate", "scope", "spread_usd_per_btc",
                                           "trades", "profit_factor", "average_r",
                                           "net_pnl"]].round(4)), "",
              "No parameters, direction permissions, exit rules, or active strategy settings were changed. No deployment recommendation is made.", ""]
    path.write_text("\n".join(lines))


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    lines = ["| " + " | ".join(columns) + " |",
             "|" + "|".join("---" for _ in columns) + "|"]
    for values in frame.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value) for value in values) + " |")
    return "\n".join(lines)


def three_model_comparison(original: Case, central: Case) -> pd.DataFrame:
    """Reconcile saved B1 cost repricing with the unchanged B2 replays."""
    saved = pd.read_csv(COST_OUTPUT / "synthetic_execution_comparison.csv")
    old_cost = pd.read_csv(COST_OUTPUT / "cost_model_comparison.csv")
    rows = []
    for scope in ("development", "forward-validation", "all"):
        for case, model, view, scenario in (
            (original, "original_single_price", "cost_only", "old_0.05pct_per_side"),
            (original, "cost_only_$10", "cost_only", "spread_$10"),
            (central, "synthetic_$10", "SYNTHETIC EXNESS-LIKE BID/ASK EXECUTION", "spread_$10"),
        ):
            source = old_cost if model == "original_single_price" else saved
            part = source.loc[(source.scope == scope) & (source.view == view) &
                              (source.scenario == scenario)].iloc[0]
            if model != "cost_only_$10":
                actual = trade_metrics(_period(case.trades, scope))
                if part.trades != actual["trades"] or not math.isclose(
                        part.net_pnl, actual["net_pnl"], abs_tol=1e-6):
                    raise AssertionError(f"B1 and B2 {model} differ in {scope}.")
            orders = _period(case.orders, scope)
            rows.append({"scope": scope, "model": model,
                         "pending_fills": int(orders.status.eq("triggered").sum()),
                         "trades": int(part.trades), "profit_factor": part.profit_factor,
                         "average_r": part.average_r, "net_pnl": part.net_pnl})
    return pd.DataFrame(rows)


def build_reports(output: Path = OUTPUT, data_path: Path = CANONICAL_DATA_FILE) -> dict:
    audit = json.loads(CALIBRATION.read_text())
    if (audit["sample_count"], audit["total_ticks"], audit["total_observed_hours"],
        audit["combined_spread"]["median"]) != (5, 541647, 120., 10.):
        raise ValueError("Real-tick calibration does not match the five saved samples.")
    data = load_ohlcv_csv(data_path)
    frames = usable_frames(data)
    specs = frozen_specs()
    original = run_case(frames, "ORIGINAL", specs["ORIGINAL"], None,
                        capture_states=True)
    cases = {}
    for candidate, spec in specs.items():
        for spread in SPREADS:
            cases[(candidate, spread)] = run_case(
                frames, candidate, spec, spread,
                capture_states=(candidate == "ORIGINAL" and spread == 10.))
    central = cases[("ORIGINAL", 10.)]
    if (int(original.orders.status.eq("triggered").sum()), len(original.trades),
        int(central.orders.status.eq("triggered").sum()), len(central.trades)) != (958, 955, 983, 980):
        raise AssertionError("Frozen original or $10 synthetic control drifted from Phase 4F-B1.")
    reconciliation = reconcile(original, central, frames, 10.)
    synthetic_only = reconciliation.loc[reconciliation.classification == "SYNTHETIC_ONLY_FILL"]
    original_only = reconciliation.loc[reconciliation.classification == "ORIGINAL_ONLY_FILL"]
    if synthetic_only.explanation.isna().any() or original_only.explanation.isna().any():
        raise AssertionError("An exclusive fill lacks an explanation.")
    direction_rows = []
    for direction in ("LONG", "SHORT"):
        subset = reconciliation.loc[reconciliation.direction == direction]
        for case in (original, central):
            direction_rows.append({"direction": direction,
                                   "model": "original_single_price" if case.spread is None else "synthetic_$10",
                                   "pending_fills": int(case.orders.loc[case.orders.direction == direction].status.eq("triggered").sum()),
                                   "same_fill": int(subset.classification.eq("SAME_FILL").sum()),
                                   "synthetic_only": int(subset.classification.eq("SYNTHETIC_ONLY_FILL").sum()),
                                   "original_only": int(subset.classification.eq("ORIGINAL_ONLY_FILL").sum()),
                                   "timing_changed": int(subset.classification.eq("TIMING_CHANGED_FILL").sum()),
                                   "price_changed": int(subset.classification.eq("PRICE_CHANGED_FILL").sum()),
                                   **trade_metrics(case.trades.loc[case.trades.direction == direction])})
    results = pd.DataFrame(case_rows(cases[(candidate, 10.)], scope)
                           for candidate in specs for scope in ("development", "forward-validation", "all"))
    sensitivity = pd.DataFrame(case_rows(cases[(candidate, spread)], scope)
                               for candidate in specs for spread in SPREADS
                               for scope in ("development", "forward-validation"))
    directions = pd.DataFrame({"candidate": candidate, "scope": scope, "direction": direction,
                               **trade_metrics(_period(cases[(candidate, 10.)].trades, scope).loc[
                                   lambda x: x.direction == direction])}
                              for candidate in specs for scope in ("development", "forward-validation", "all")
                              for direction in ("LONG", "SHORT"))
    flag_rows = []
    for candidate in specs:
        dev = results.loc[(results.candidate == candidate) & (results.scope == "development")].iloc[0]
        fwd = results.loc[(results.candidate == candidate) & (results.scope == "forward-validation")].iloc[0]
        sides = directions.loc[directions.candidate == candidate]
        def side(scope, direction):
            return sides.loc[(sides.scope == scope) & (sides.direction == direction)].iloc[0]
        flag_rows.append({"candidate": candidate,
                          "development_pf_gt_1": bool(dev.profit_factor > 1),
                          "development_avg_r_gt_0": bool(dev.average_r > 0),
                          "forward_pf_gt_1": bool(fwd.profit_factor > 1),
                          "forward_avg_r_gt_0": bool(fwd.average_r > 0),
                          "long_development_pf_gt_1": bool(side("development", "LONG").profit_factor > 1),
                          "short_development_pf_gt_1": bool(side("development", "SHORT").profit_factor > 1),
                          "long_forward_pf_gt_1": bool(side("forward-validation", "LONG").profit_factor > 1),
                          "short_forward_pf_gt_1": bool(side("forward-validation", "SHORT").profit_factor > 1),
                          "adequate_sample": bool(dev.trades >= 250 and fwd.trades >= 100)})
    flags = pd.DataFrame(flag_rows)
    detail, effects = price_effects(original, central)
    models = three_model_comparison(original, central)
    output.mkdir(parents=True, exist_ok=True)
    reconciliation.to_csv(output / "fill_reconciliation.csv", index=False)
    synthetic_only.to_csv(output / "synthetic_only_fills.csv", index=False)
    original_only.to_csv(output / "original_only_fills.csv", index=False)
    reconciliation.loc[reconciliation.classification == "TIMING_CHANGED_FILL"].to_csv(
        output / "timing_changed_fills.csv", index=False)
    reconciliation.loc[reconciliation.classification == "PRICE_CHANGED_FILL"].to_csv(
        output / "price_changed_fills.csv", index=False)
    pd.DataFrame(direction_rows).to_csv(output / "direction_comparison.csv", index=False)
    results.to_csv(output / "candidate_synthetic_results.csv", index=False)
    directions.to_csv(output / "candidate_direction_results.csv", index=False)
    sensitivity.to_csv(output / "synthetic_spread_sensitivity.csv", index=False)
    detail.to_csv(output / "entry_price_effects.csv", index=False)
    effects.to_csv(output / "entry_effect_summary.csv", index=False)
    central.same_bar.to_csv(output / "same_bar_cases.csv", index=False)
    flags.to_csv(output / "robustness_flags.csv", index=False)
    models.to_csv(output / "three_model_comparison.csv", index=False)
    _write_summary(output / "audit_summary.md", reconciliation, results, sensitivity,
                   central.same_bar, flags, effects, models)
    return {"reconciliation": reconciliation, "original": original,
            "central": central, "results": results, "sensitivity": sensitivity,
            "directions": directions, "flags": flags, "effects": effects}


if __name__ == "__main__":
    build_reports()
