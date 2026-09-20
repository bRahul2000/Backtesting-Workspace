"""Research-only Bitstamp/Exness cost comparison for frozen Setup B.

The synthetic replay uses Bitstamp OHLC as Bid and a constant Ask offset. It
is an approximation, never broker-native Exness history. Neither the audited
engine nor the frozen strategy is modified.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import json

import pandas as pd

from engine.backtester import _validated_candles
from engine.backtester import run_backtest
from engine.execution import (close_position, create_pending_order, exit_decision,
                              fill_pending_order)
from engine.models import (BacktestResult, BacktestSettings, CancelPendingOrder,
                           Candle, Direction, EntryModel, ExecutionState,
                           OrderEvent, Signal)
from research.exness_cost_recalibration import CALIBRATION, load_frozen_trades, reprice
from research.segment_aware_baseline import warmup_plan
from research.setup_b_entry_research import (EntrySpec, ResearchSetupB,
                                             OUT as ENTRY_RESEARCH_OUT,
                                             read_frozen_candidates)
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v2_setup_b import BtcV2SetupB, SetupBParameters
from utils.data_validation import continuous_segments, load_ohlcv_csv


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/broker/exness/cost_calibrated"
LABEL = "EXNESS STANDARD COST-CALIBRATED APPROXIMATION"
SYNTHETIC_LABEL = "SYNTHETIC EXNESS-LIKE BID/ASK EXECUTION"
SPREADS = (0., 5., 10., 15., 20., 30., 50.)
SETTINGS = BacktestSettings(risk_percent=.25, risk_reward_ratio=3.,
                            commission_percent=0., slippage_percent=0.)


def ask_from_bid(bid: Candle, spread: float) -> Candle:
    if spread < 0:
        raise ValueError("Spread must be nonnegative.")
    return Candle(bid.timestamp, bid.open + spread, bid.high + spread,
                  bid.low + spread, bid.close + spread, bid.volume)


def entry_candle(bid: Candle, spread: float, direction: Direction) -> Candle:
    return ask_from_bid(bid, spread) if direction is Direction.LONG else bid


def exit_candle(bid: Candle, spread: float, direction: Direction) -> Candle:
    return bid if direction is Direction.LONG else ask_from_bid(bid, spread)


def _event(order, status: str, reason: str | None = None,
           fill_time=None, fill_price=None) -> OrderEvent:
    return OrderEvent(order.signal_time, order.created_time, order.direction,
                      order.trigger_price, order.stop_price, order.expiry_time,
                      order.expiry_bar_index, status, reason, fill_time, fill_price,
                      order.setup_id)


def _spread_at(spread, index: int) -> float:
    """Resolve the spread for one bar.

    A scalar keeps the original constant-spread behaviour exactly. A sequence
    supplies the broker's real per-bar spread, one value per candle.
    """
    if isinstance(spread, (int, float)):
        return float(spread)
    return float(spread[index])


def run_synthetic_segment(frame: pd.DataFrame, strategy: BtcV2SetupB,
                          spread, trade_start: pd.Timestamp,
                          settings: BacktestSettings = SETTINGS) -> BacktestResult:
    """Replay one continuous segment with Bid signals and quote-side execution.

    Conservative same-bar resolution and position sizing reuse audited engine
    primitives. The only new rule is selecting the Bid or synthetic Ask stream.

    ``spread`` is either a constant (the historical calibrated assumption) or a
    per-bar sequence carrying the broker's real historical spread.
    """
    candles = _validated_candles(frame)
    if isinstance(spread, (int, float)):
        if spread < 0:
            raise ValueError("Spread must be nonnegative.")
    else:
        spread = [float(value) for value in spread]
        if len(spread) != len(candles):
            raise ValueError("Per-bar spread must supply exactly one value per candle.")
        if any(value < 0 for value in spread):
            raise ValueError("Spread must be nonnegative.")
    if any(b.timestamp - a.timestamp != pd.Timedelta(minutes=15)
           for a, b in zip(candles, candles[1:])):
        raise ValueError("Synthetic replay requires one continuous M15 segment.")
    result = BacktestResult(settings)
    balance = settings.starting_balance
    strategy.reset()
    strategy.on_backtest_window(trade_start, None)
    pending = position = None
    for index, bid in enumerate(candles):
        opened = closed = None
        entered_intrabar = False
        if pending is not None:
            order = pending
            if index > order.expiry_bar_index:
                result.order_events.append(_event(order, "expired", "Expiry bar passed without a trigger."))
                pending = None
            else:
                side = entry_candle(bid, _spread_at(spread, index), order.direction)
                try:
                    position = fill_pending_order(order, side, index, len(result.trades) + 1,
                                                  settings)
                except (ValueError, TypeError, OverflowError) as exc:
                    result.order_events.append(_event(order, "cancelled", str(exc)))
                    pending = None
                else:
                    if position is not None:
                        opened = position
                        entered_intrabar = (not position.gap_through_trigger and
                            ((order.direction is Direction.LONG and side.open < order.trigger_price)
                             or (order.direction is Direction.SHORT and side.open > order.trigger_price)))
                        result.order_events.append(_event(order, "triggered",
                                                           fill_time=bid.timestamp,
                                                           fill_price=position.entry_price))
                        pending = None
                    elif index == order.expiry_bar_index:
                        result.order_events.append(_event(order, "expired",
                                                           "Not triggered by the end of the expiry bar."))
                        pending = None
        if position is not None:
            side = exit_candle(bid, _spread_at(spread, index), position.direction)
            decision = exit_decision(position, side, settings.same_bar_resolution,
                                     entered_intrabar=entered_intrabar)
            if decision is not None:
                price, reason = decision
                closed = close_position(position, side, index, price, reason, settings)
                result.trades.append(closed)
                balance += closed.pnl
                position = None
        strategy.on_execution_state(ExecutionState(balance, pending, position, opened, closed))
        signal = strategy.on_candle(bid)
        if bid.timestamp < trade_start:
            continue
        if isinstance(signal, CancelPendingOrder):
            if pending is not None and signal.reason.strip() and (signal.setup_id is None or
                    signal.setup_id == pending.setup_id):
                result.order_events.append(_event(pending, "cancelled", signal.reason))
                pending = None
        elif isinstance(signal, Signal) and position is None and pending is None:
            if signal.entry_model is not EntryModel.STOP_ENTRY_PENDING:
                raise ValueError("Frozen Setup B must emit pending stop entries.")
            signal = replace(signal, setup_id=signal.setup_id or type(strategy).__name__)
            try:
                pending = create_pending_order(signal, bid, index, balance, settings)
            except (ValueError, TypeError, OverflowError):
                pass
    result.open_position = position
    if pending is not None:
        final_action = strategy.on_backtest_end(pending)
        if isinstance(final_action, CancelPendingOrder) and final_action.reason.strip() and (
                final_action.setup_id is None or final_action.setup_id == pending.setup_id):
            result.order_events.append(_event(pending, "cancelled", final_action.reason))
            pending = None
    result.pending_order = pending
    if pending is not None:
        result.order_events.append(_event(pending, "active_at_end",
                                           "Dataset ended before fill or expiry."))
    return result


def _drawdown(frame: pd.DataFrame, pnl_column: str) -> float:
    worst = 0.
    for _, group in frame.groupby("segment_id", sort=False):
        balance = peak = SETTINGS.starting_balance
        for pnl in group.sort_values(["exit_time", "trade_id"])[pnl_column]:
            balance += pnl
            peak = max(peak, balance)
            worst = max(worst, (peak - balance) / peak * 100)
    return worst


def _summary(frame: pd.DataFrame, *, synthetic: bool,
             synthetic_spread: float = 0.) -> dict:
    if synthetic:
        pnl, risk = frame.pnl, frame.initial_risk
        # Already embedded in side-correct entry and exit prices. This is a
        # descriptive one-spread equivalent, never subtracted a second time.
        spread_cost = frame.quantity * synthetic_spread
        commission_cost = pd.Series(0., index=frame.index)
    else:
        pnl, risk = frame.net_pnl_repriced, frame.planned_risk_used
        spread_cost = frame.spread_cost
        commission_cost = frame.commission_cost_used
    cost = spread_cost + commission_cost
    profit = float(pnl[pnl > 0].sum())
    loss = float(pnl[pnl < 0].sum())
    return {"trades": len(frame), "win_rate_percent": float((pnl > 0).mean() * 100) if len(frame) else 0.,
            "profit_factor": profit / abs(loss) if loss else (float("inf") if profit else None),
            "average_r": float((pnl / risk).mean()) if len(frame) else 0.,
            "net_pnl": float(pnl.sum()), "total_spread_cost": float(spread_cost.sum()),
            "total_commission_cost": float(commission_cost.sum()),
            "total_cost": float(cost.sum()),
            "average_spread_cost": float(spread_cost.mean()) if len(frame) else 0.,
            "average_total_cost": float(cost.mean()) if len(frame) else 0.,
            "spread_cost_r_per_trade": float((spread_cost / risk).mean()) if len(frame) else 0.,
            "cost_r_per_trade": float((cost / risk).mean()) if len(frame) else 0.,
            "worst_segment_dd_percent": _drawdown(frame.assign(_pnl=pnl), "_pnl") if len(frame) else 0.}


def synthetic_history(data: pd.DataFrame, spread: float,
                      params: SetupBParameters | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    params = params or SetupBParameters()
    trades, orders = [], []
    for number, segment in enumerate(continuous_segments(data), 1):
        plan = warmup_plan(params, segment.start)
        if segment.candles < plan.minimum_segment_candles:
            continue
        sid = f"S{number:02d}"
        fragment = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        result = run_synthetic_segment(fragment, BtcV2SetupB(params), spread,
                                       plan.first_search_time)
        for t in result.trades:
            trades.append({"segment_id": sid, "trade_id": t.trade_id,
                           "signal_time": t.signal_time, "entry_time": t.entry_time,
                           "exit_time": t.exit_time, "direction": t.direction.value,
                           "entry_price": t.entry_price, "exit_price": t.exit_price,
                           "quantity": t.quantity, "initial_risk": t.initial_risk,
                           "pnl": t.pnl, "realized_r": t.realized_r,
                           "exit_reason": t.exit_reason})
        for e in result.order_events:
            orders.append({"segment_id": sid, "status": e.status,
                           "signal_time": e.signal_time, "direction": e.direction.value})
    return pd.DataFrame(trades), pd.DataFrame(orders)


def _scope(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if name == "development":
        return frame.loc[frame.signal_time < pd.Timestamp("2025-01-01", tz="UTC")]
    if name == "forward-validation":
        return frame.loc[frame.signal_time >= pd.Timestamp("2025-01-01", tz="UTC")]
    return frame


def _frozen_candidates(data: pd.DataFrame) -> pd.DataFrame:
    """Secondary cost-only views of candidates frozen before validation."""
    frozen = read_frozen_candidates(ENTRY_RESEARCH_OUT / "frozen_candidates.json")
    if [item["id"] for item in frozen["candidates"]] != ["C2", "C3", "minimum_adx=25"]:
        raise ValueError("The Phase 4E frozen candidate identities changed.")
    old_settings = replace(SETTINGS, commission_percent=.05)
    rows = []
    for item in frozen["candidates"]:
        spec = EntrySpec.from_dict(item["changes"])
        trades = []
        for number, segment in enumerate(continuous_segments(data), 1):
            params = spec.strategy_params()
            plan = warmup_plan(params, segment.start)
            if segment.candles < plan.minimum_segment_candles:
                continue
            frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
            result = run_backtest(frame, ResearchSetupB(spec), old_settings,
                                  trade_start=plan.first_search_time)
            for trade in result.trades:
                gross = trade.pnl + trade.entry_commission + trade.exit_commission
                trades.append({"segment_id": f"S{number:02d}", "trade_id": trade.trade_id,
                               "signal_time": trade.signal_time, "exit_time": trade.exit_time,
                               "direction": trade.direction.value,
                               "quantity": trade.quantity, "initial_risk": trade.initial_risk,
                               "pnl": gross - 10 * trade.quantity})
        frame = pd.DataFrame(trades)
        for scope in ("all", "development", "forward-validation"):
            part = _scope(frame, scope)
            values = _summary(part, synthetic=True, synthetic_spread=10.)
            rows.append({"label": LABEL, "candidate": item["id"],
                         "changes": json.dumps(item["changes"], sort_keys=True),
                         "view": "SECONDARY FROZEN CANDIDATE COST-ONLY", "scope": scope,
                         **values})
    return pd.DataFrame(rows)


def build_reports(output: Path = OUTPUT, source: Path = CANONICAL_DATA_FILE) -> dict:
    audit = json.loads(CALIBRATION.read_text())
    if audit["sample_count"] != 5 or audit["total_ticks"] != 541647 or audit["combined_spread"]["median"] != 10:
        raise ValueError("Real-tick calibration audit does not match the frozen five samples.")
    output.mkdir(parents=True, exist_ok=True)
    frozen = load_frozen_trades()
    scopes = ("all", "development", "forward-validation")
    rows, spread_rows = [], []
    for scenario, spread, old in [("old_0.05pct_per_side", None, True)] + [
            (f"spread_${int(s)}", s, False) for s in SPREADS]:
        priced = reprice(frozen, spread=spread, old_cost=old)
        for name in scopes:
            subset = _scope(priced, name)
            row = {"label": LABEL, "view": "cost_only", "scenario": scenario,
                   "scope": name, "spread_usd_per_btc": spread,
                   **_summary(subset, synthetic=False)}
            rows.append(row)
            if not old:
                spread_rows.append(row)
    comparison = pd.DataFrame(rows)
    comparison.to_csv(output / "cost_model_comparison.csv", index=False)
    pd.DataFrame(spread_rows).to_csv(output / "spread_sensitivity.csv", index=False)
    comparison.loc[comparison.scope == "all"].to_csv(output / "original_control.csv", index=False)
    yearly = frozen.assign(year=frozen.signal_time.dt.year,
                           spread_bps=10 / frozen.actual_fill_price * 10000).groupby("year").agg(
                               trades=("trade_id", "count"), median_spread_bps=("spread_bps", "median"))
    yearly.reset_index().to_csv(output / "yearly_spread_bps.csv", index=False)
    data = load_ohlcv_csv(source)
    synthetic, orders = synthetic_history(data, 10.)
    synthetic_rows = []
    for name in scopes:
        subset = _scope(synthetic, name)
        selected_orders = _scope(orders, name)
        synthetic_rows.append({"label": LABEL, "view": SYNTHETIC_LABEL,
                               "scenario": "spread_$10", "scope": name,
                               "pending_fills": int(selected_orders.status.eq("triggered").sum()),
                               "pending_expiries": int(selected_orders.status.eq("expired").sum()),
                               **_summary(subset, synthetic=True,
                                          synthetic_spread=10.)})
    synthetic_table = pd.DataFrame(synthetic_rows)
    frozen_segments = pd.read_csv(ROOT / "reports/long_history/segment_aware/segment_results.csv")
    frozen_segments = frozen_segments.loc[frozen_segments.usable]
    mechanics = []
    for name in scopes:
        prior = comparison.loc[(comparison.scope == name) &
                               (comparison.scenario == "spread_$10")].iloc[0].to_dict()
        prior["pending_fills"] = (int(frozen_segments.pending_filled.sum())
                                  if name == "all" else None)
        prior["pending_expiries"] = (int(frozen_segments.pending_expired.sum())
                                     if name == "all" else None)
        mechanics.append(prior)
        mechanics.append(synthetic_table.loc[synthetic_table.scope == name].iloc[0].to_dict())
    pd.DataFrame(mechanics).to_csv(output / "synthetic_execution_comparison.csv", index=False)
    candidates = _frozen_candidates(data)
    control_candidate = comparison.loc[comparison.scenario == "spread_$10"].copy()
    control_candidate["candidate"] = "ORIGINAL"
    control_candidate["changes"] = "{}"
    control_candidate["view"] = "FROZEN ORIGINAL COST-ONLY"
    candidates = pd.concat([control_candidate[candidates.columns], candidates],
                           ignore_index=True)
    candidates.to_csv(output / "frozen_candidate_comparison.csv", index=False)
    _write_summary(output / "summary.md", comparison, synthetic_table, yearly,
                   orders, candidates)
    return {"comparison": comparison, "synthetic": synthetic_table,
            "yearly_spread_bps": yearly, "orders": orders,
            "candidates": candidates}


def _write_summary(path: Path, comparison: pd.DataFrame, synthetic: pd.DataFrame,
                   yearly: pd.DataFrame, orders: pd.DataFrame,
                   candidates: pd.DataFrame) -> None:
    all_synth = synthetic.loc[synthetic.scope == "all"].iloc[0]
    lines = [f"# {LABEL}", "",
             "Bitstamp BTC/USD historical prices remain the market source. The synthetic view treats each Bid OHLC as a synthetic Bid and adds a constant $10 Ask. Neither view is a broker-native historical Exness backtest. Segments reset independently; no equity curve crosses missing candles.",
             "", "Observed calibration: 5 real files, 541,647 ticks, $10/BTC spread; commission $0. The spread sensitivity is hypothetical outside the observed samples.",
             "", "The cost-only view retains exact frozen fills and exits. The synthetic view replays pending triggers and exits on the appropriate quote side, with the audited conservative same-bar convention. Its reported one-spread equivalent is embedded in trade PnL and is never subtracted twice.",
             "", "## Original frozen control", "",
             "| Scope | Model | Trades | WR % | PF | Avg R | Net PnL | Cost R/trade | Worst segment DD % |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for scope in ("all", "development", "forward-validation"):
        for scenario in ("old_0.05pct_per_side", "spread_$10"):
            row = comparison.loc[(comparison.scope == scope) &
                                 (comparison.scenario == scenario)].iloc[0]
            lines.append(f"| {scope} | {scenario} cost-only | {int(row.trades)} | {row.win_rate_percent:.2f} | {row.profit_factor:.4f} | {row.average_r:.4f} | {row.net_pnl:.2f} | {row.cost_r_per_trade:.4f} | {row.worst_segment_dd_percent:.4f} |")
        row = synthetic.loc[synthetic.scope == scope].iloc[0]
        lines.append(f"| {scope} | $10 synthetic Bid/Ask | {int(row.trades)} | {row.win_rate_percent:.2f} | {row.profit_factor:.4f} | {row.average_r:.4f} | {row.net_pnl:.2f} | {row.cost_r_per_trade:.4f} | {row.worst_segment_dd_percent:.4f} |")
    lines += ["", "## Fixed-spread cost-only sensitivity · all usable segments", "",
              "| Spread USD/BTC | Trades | PF | Avg R | Net PnL | Spread cost | Worst segment DD % |",
              "|---:|---:|---:|---:|---:|---:|---:|"]
    for spread in SPREADS:
        row = comparison.loc[(comparison.scope == "all") &
                             (comparison.scenario == f"spread_${int(spread)}")].iloc[0]
        lines.append(f"| {spread:g} | {int(row.trades)} | {row.profit_factor:.4f} | {row.average_r:.4f} | {row.net_pnl:.2f} | {row.total_spread_cost:.2f} | {row.worst_segment_dd_percent:.4f} |")
    lines += ["", "## $10 spread bps at frozen trade entry", "",
              "| Year | Trades | Median bps |", "|---:|---:|---:|"]
    for year, row in yearly.iterrows():
        lines.append(f"| {year} | {int(row.trades)} | {row.median_spread_bps:.4f} |")
    lines += ["", "## Quote-side mechanics", "",
              "Frozen cost-only pending fills: 958; expiries: 267; completed trades: 955.",
              f"Synthetic $10 pending fills: {int((orders.status == 'triggered').sum())}; expiries: {int((orders.status == 'expired').sum())}; completed trades: {int(all_synth.trades)}.",
              "The change includes altered trigger timing, exits, account state, and risk-lock feedback; it is not a broker-native Exness execution result.",
              "", "## Previously frozen Phase 4E candidates · secondary $10 cost-only view", "",
              "| Candidate | Scope | Trades | PF | Avg R | Net PnL |",
              "|---|---|---:|---:|---:|---:|"]
    for row in candidates.itertuples(index=False):
        lines.append(f"| {row.candidate} | {row.scope} | {row.trades} | {row.profit_factor:.4f} | {row.average_r:.4f} | {row.net_pnl:.2f} |")
    lines += ["", "The old 0.05%-per-side research and all frozen strategy reports are preserved. No candidate is selected for deployment.", ""]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    build_reports()
