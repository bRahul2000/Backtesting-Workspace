"""Read-only failure diagnostics for the frozen Phase 4B Setup B trade export.

This module never invokes the backtester or changes strategy decisions. Signal
indicators are replayed on each original continuous segment solely to observe
values available at the completed signal candle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import deque
from math import inf, isclose
from pathlib import Path

import pandas as pd

from engine.models import Candle, Direction
from research.segment_aware_baseline import OUTPUT_DIR as BASELINE_DIR
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v2_setup_b import SETUP_ID, SetupBParameters
from strategies.confirmed_h1 import ConfirmedH1Trend
from strategies.pine_indicators import ATR, DMI, EMA, RSI
from utils.data_validation import continuous_segments, load_ohlcv_csv


OUTPUT_DIR = Path(__file__).resolve().parents[1] / "reports" / "diagnostics" / "setup_b"
STEP = pd.Timedelta(minutes=15)
SMALL_SAMPLE = 20
THRESHOLDS = (0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0)
PROFILE_FIELDS = (
    ("ADX", "adx"), ("RSI", "rsi"), ("ATR %", "atr_percent"),
    ("EMA20 extension ATR", "ema20_extension_atr"),
    ("EMA20/EMA50 separation ATR", "ema_separation_atr"),
    ("H1 EMA200 slope", "h1_ema200_slope"),
    ("Breakout body %", "body_percent"),
    ("Breakout range ATR", "range_atr"),
    ("Structure breakout distance ATR", "structure_breakout_distance_atr"),
    ("Stop distance ATR", "planned_stop_distance_atr"),
    ("Trigger-to-fill gap ATR", "trigger_to_fill_difference_atr"),
    ("Trigger-to-fill gap price", "trigger_to_fill_difference"),
    ("Bars held", "bars_held"),
)


def analysis_set(signal_candle_time: pd.Timestamp) -> str:
    timestamp = pd.Timestamp(signal_candle_time)
    if timestamp.tzinfo is None:
        raise ValueError("Analysis-set tagging requires a UTC-aware signal candle.")
    timestamp = timestamp.tz_convert("UTC")
    return ("Development (2021–2024)" if timestamp < pd.Timestamp("2025-01-01", tz="UTC")
            else "Forward-validation (2025–2026)")


def classify_fill(signal_time: pd.Timestamp, entry_time: pd.Timestamp) -> str:
    """signal_time is the B+1 open, one step after the signal candle."""
    offset = pd.Timestamp(entry_time) - pd.Timestamp(signal_time)
    if offset == pd.Timedelta(0):
        return "B+1"
    if offset == STEP:
        return "B+2"
    raise ValueError(f"Pending fill is outside B+1/B+2: {offset}.")


def is_gap_fill(direction: str, entry_open: float, trigger: float) -> bool:
    return entry_open > trigger if direction == "LONG" else entry_open < trigger


def bucket_label(value: float, edges: tuple[float, ...],
                 labels: tuple[str, ...]) -> str:
    """Left-closed buckets; the last finite upper bound is inclusive."""
    if len(labels) != len(edges) - 1:
        raise ValueError("Bucket labels and edges disagree.")
    for index, label in enumerate(labels):
        lower, upper = edges[index:index + 2]
        if lower <= value < upper or (index == len(labels) - 1 and value == upper):
            return label
    return "Outside defined range"


def breakeven_win_rate(average_winner_r: float,
                       average_loser_r: float) -> float | None:
    if average_winner_r <= 0 or average_loser_r >= 0:
        return None
    loss = abs(average_loser_r)
    return loss / (average_winner_r + loss) * 100


def recover_quantity(net_pnl: float, direction: str, entry: float,
                     exit_price: float, commission_percent: float) -> float:
    """Invert the audited closed-trade PnL identity for this frozen export."""
    sign = 1 if direction == "LONG" else -1
    rate = commission_percent / 100
    net_per_unit = sign * (exit_price - entry) - rate * (entry + exit_price)
    if abs(net_per_unit) < 1e-10:
        raise ValueError("Cannot recover quantity from a zero net-PnL unit.")
    quantity = net_pnl / net_per_unit
    if quantity <= 0:
        raise ValueError("Recovered trade quantity is not positive.")
    return quantity


def decompose_costs(*, direction: str, quantity: float, trigger: float,
                    entry_open: float, entry_price: float, exit_price: float,
                    commission_percent: float, slippage_percent: float,
                    net_pnl: float) -> dict:
    """Separate raw price movement, adverse percentage slippage, and fees."""
    sign = 1 if direction == "LONG" else -1
    base_fill = max(trigger, entry_open) if sign == 1 else min(trigger, entry_open)
    slip = slippage_percent / 100
    expected_entry = base_fill * (1 + sign * slip)
    if not isclose(entry_price, expected_entry, rel_tol=1e-10, abs_tol=1e-7):
        raise ValueError("Recorded entry does not match the frozen fill model.")
    raw_exit = exit_price / (1 - sign * slip)
    gross_price_pnl = sign * (raw_exit - base_fill) * quantity
    after_slippage_pnl = sign * (exit_price - entry_price) * quantity
    slippage_cost = (0.0 if slippage_percent == 0 else
                     gross_price_pnl - after_slippage_pnl)
    entry_commission = entry_price * quantity * commission_percent / 100
    exit_commission = exit_price * quantity * commission_percent / 100
    commission_cost = entry_commission + exit_commission
    total_cost = commission_cost + slippage_cost
    if not isclose(gross_price_pnl - total_cost, net_pnl,
                   rel_tol=1e-9, abs_tol=1e-7):
        raise ValueError("Gross-to-net decomposition does not reconcile.")
    return {
        "quantity_recovered": quantity, "raw_entry_price": base_fill,
        "raw_exit_price": raw_exit, "gross_price_movement_pnl": gross_price_pnl,
        "entry_commission_cost": entry_commission,
        "exit_commission_cost": exit_commission,
        "commission_cost": commission_cost,
        "slippage_cost": slippage_cost, "total_transaction_cost": total_cost,
    }


def excursion(candles: pd.DataFrame, *, direction: str, entry_price: float,
              exit_price: float, stop_price: float, quantity: float,
              gap_fill: bool) -> dict:
    """Conservative path-known MFE/MAE from fill through exit, inclusive.

    A normal stop entry occurs inside its fill bar: only the directional
    breakout extreme is certainly after the fill. On the exit bar, only the
    actual exit price is certainly before exit. This intentionally understates
    excursions that depend on an unknown intrabar sequence.
    """
    if candles.empty:
        raise ValueError("An excursion needs at least the entry/exit candle.")
    sign = 1 if direction == "LONG" else -1
    risk_distance = abs(entry_price - stop_price)
    if risk_distance <= 0:
        raise ValueError("The actual fill needs positive structural risk.")
    best = worst = 0.0
    best_bar = worst_bar = 0
    last_index = len(candles) - 1
    for index, candle in enumerate(candles.itertuples(index=False)):
        if index == last_index:
            favorable = max(0.0, sign * (exit_price - entry_price))
            adverse = max(0.0, -sign * (exit_price - entry_price))
        elif index == 0 and not gap_fill:
            favorable_extreme = candle.high if sign == 1 else candle.low
            favorable = max(0.0, sign * (favorable_extreme - entry_price))
            adverse = 0.0  # The opposite extreme could precede the trigger.
        else:
            favorable_extreme = candle.high if sign == 1 else candle.low
            adverse_extreme = candle.low if sign == 1 else candle.high
            favorable = max(0.0, sign * (favorable_extreme - entry_price))
            adverse = max(0.0, -sign * (adverse_extreme - entry_price))
        if favorable > best:
            best, best_bar = favorable, index + 1
        if adverse > worst:
            worst, worst_bar = adverse, index + 1
    mfe_r, mae_r = best / risk_distance, worst / risk_distance
    result = {
        "mfe_price_distance": best, "mae_price_distance": worst,
        "mfe_dollars": best * quantity, "mae_dollars": worst * quantity,
        "mfe_r": mfe_r, "mae_r": mae_r,
        "bars_to_mfe": best_bar, "bars_to_mae": worst_bar,
        "excursion_path_conservative": True,
    }
    for threshold in THRESHOLDS:
        result[f"reached_{threshold:g}r"] = mfe_r + 1e-9 >= threshold
    return result


def _signal_descriptors(data: pd.DataFrame, segments: pd.DataFrame,
                        trades: pd.DataFrame) -> dict[tuple[str, pd.Timestamp], dict]:
    params = SetupBParameters()
    wanted = {(row.segment_id, row.signal_candle_time): row for row in
              trades.itertuples(index=False)}
    found = {}
    for segment in segments.itertuples(index=False):
        segment_id = segment.segment_id
        targets = {time for key, time in wanted if key == segment_id}
        if not targets:
            continue
        frame = data.loc[data.timestamp.between(segment.start, segment.end)]
        h1 = ConfirmedH1Trend(params.h1_fast_ema, params.h1_slow_ema,
                              params.h1_slope_lookback)
        fast, slow = EMA(params.ema_fast), EMA(params.ema_slow)
        atr_indicator = ATR(params.atr_length)
        rsi_indicator = RSI(params.rsi_length)
        dmi_indicator = DMI(params.di_length, params.adx_smoothing)
        prior = deque(maxlen=params.structure_lookback)
        for item in frame.itertuples(index=False):
            candle = Candle(item.timestamp, item.open, item.high, item.low,
                            item.close, item.volume)
            confirmed = h1.update(candle)
            ema20 = fast.update(candle.close)
            ema50 = slow.update(candle.close)
            atr = atr_indicator.update(candle)
            rsi = rsi_indicator.update(candle.close)
            dmi = dmi_indicator.update(candle)
            if candle.timestamp in targets:
                source = wanted[(segment_id, candle.timestamp)]
                if (atr is None or atr <= 0 or rsi is None or dmi.adx is None or
                    confirmed.slow_ema_lookback is None):
                    raise ValueError(f"Unwarmed signal descriptor {segment_id}/{candle.timestamp}.")
                sign = 1 if source.direction == "LONG" else -1
                previous_high = max(bar.high for bar in prior)
                previous_low = min(bar.low for bar in prior)
                structure = previous_high if sign == 1 else previous_low
                trigger = (candle.high + params.entry_buffer_atr * atr if sign == 1
                           else candle.low - params.entry_buffer_atr * atr)
                stop_bars = (list(prior)[-(params.structure_stop_lookback - 1):]
                             if params.structure_stop_lookback > 1 else [])
                structural_extreme = (min(bar.low for bar in (*stop_bars, candle))
                                      if sign == 1 else
                                      max(bar.high for bar in (*stop_bars, candle)))
                expected_stop = structural_extreme - sign * params.stop_buffer_atr * atr
                if not isclose(expected_stop, source.stop_loss, rel_tol=1e-10, abs_tol=1e-7):
                    raise ValueError(f"Structural stop disagrees with frozen {segment_id}/{source.trade_id}.")
                slope = confirmed.slow_ema - confirmed.slow_ema_lookback
                body_percent = (abs(candle.close - candle.open) /
                                (candle.high - candle.low) * 100)
                found[(segment_id, candle.timestamp)] = {
                    "signal_candle_time": candle.timestamp,
                    "signal_utc_hour": candle.timestamp.hour,
                    "signal_utc_weekday": candle.timestamp.day_name(),
                    "signal_utc_weekday_number": candle.timestamp.weekday(),
                    "signal_year": candle.timestamp.year,
                    "signal_month": candle.timestamp.strftime("%Y-%m"),
                    "analysis_set": analysis_set(candle.timestamp),
                    "signal_open": candle.open, "signal_high": candle.high,
                    "signal_low": candle.low, "signal_close": candle.close,
                    "ema20": ema20, "ema50": ema50,
                    "ema20_minus_ema50": ema20 - ema50,
                    "ema_separation_price": abs(ema20 - ema50),
                    "ema_separation_atr": abs(ema20 - ema50) / atr,
                    "rsi": rsi, "adx": dmi.adx,
                    "plus_di": dmi.plus_di, "minus_di": dmi.minus_di,
                    "atr": atr, "atr_percent": atr / candle.close * 100,
                    "body_percent": body_percent,
                    "range_atr": (candle.high - candle.low) / atr,
                    "structure_level": structure,
                    "structure_breakout_distance_atr": sign * (candle.close - structure) / atr,
                    "ema20_extension_atr": abs(candle.close - ema20) / atr,
                    "pending_trigger_price": trigger,
                    "planned_stop_distance_atr": abs(trigger - source.stop_loss) / atr,
                    "confirmed_h1_hour": confirmed.hour,
                    "confirmed_h1_close": confirmed.close,
                    "h1_ema50": confirmed.fast_ema,
                    "h1_ema200": confirmed.slow_ema,
                    "h1_ema200_slope": slope,
                    "h1_ema200_slope_percent": slope / confirmed.slow_ema * 100,
                }
                if not (isclose(dmi.adx, source.adx, rel_tol=1e-9) and
                        isclose(atr / candle.close * 100, source.m15_atr_percent, rel_tol=1e-9) and
                        isclose(slope, source.h1_ema200_slope, rel_tol=1e-9)):
                    raise ValueError(f"Signal-time replay disagrees with frozen {segment_id}/{source.trade_id}.")
            prior.append(candle)
    if len(found) != len(trades):
        raise ValueError(f"Found {len(found)} of {len(trades)} signal candles.")
    return found


def trade_statistics(frame: pd.DataFrame) -> dict:
    wins = frame.loc[frame.pnl > 1e-9]
    losses = frame.loc[frame.pnl < -1e-9]
    gross_profit = float(wins.pnl.sum())
    gross_loss = float(losses.pnl.sum())
    count = len(frame)
    return {
        "trades": count, "wins": len(wins), "losses": len(losses),
        "breakeven": count - len(wins) - len(losses),
        "win_rate_percent": len(wins) / count * 100 if count else 0.0,
        "gross_profit": gross_profit, "gross_loss": gross_loss,
        "net_pnl": float(frame.pnl.sum()),
        "profit_factor": (gross_profit / abs(gross_loss) if len(losses)
                          else inf if len(wins) else None),
        "average_r": float(frame.realized_r.mean()) if count else 0.0,
        "expectancy_r": float(frame.realized_r.mean()) if count else 0.0,
    }


def build_trade_diagnostics(data: pd.DataFrame, segments: pd.DataFrame,
                            source: pd.DataFrame,
                            commission_percent: float = 0.05,
                            slippage_percent: float = 0.0) -> pd.DataFrame:
    """Join the immutable completed-trade export to past-only indicators and candles."""
    trades = source.copy()
    for column in ("signal_time", "entry_time", "exit_time"):
        trades[column] = pd.to_datetime(trades[column], utc=True)
    trades["signal_candle_time"] = trades.signal_time - STEP
    segment_rows = segments.copy()
    for column in ("start", "end"):
        segment_rows[column] = pd.to_datetime(segment_rows[column], utc=True)
    descriptors = _signal_descriptors(data, segment_rows, trades)
    bounds = {row.segment_id: (row.start, row.end)
              for row in segment_rows.itertuples(index=False)}
    candles = data.set_index("timestamp", drop=False)
    records = []
    for trade in trades.itertuples(index=False):
        if trade.setup_id != SETUP_ID:
            raise ValueError("The frozen export contains another setup ID.")
        start, end = bounds[trade.segment_id]
        if not (start <= trade.signal_candle_time < trade.entry_time <= trade.exit_time <= end):
            raise ValueError(f"Trade {trade.segment_id}/{trade.trade_id} crosses a segment boundary.")
        signal = descriptors[(trade.segment_id, trade.signal_candle_time)]
        held = candles.loc[trade.entry_time:trade.exit_time]
        if len(held) != trade.bars_held or not held.timestamp.diff().iloc[1:].eq(STEP).all():
            raise ValueError(f"Trade {trade.segment_id}/{trade.trade_id} has a candle gap.")
        entry_open = float(held.iloc[0].open)
        trigger = signal["pending_trigger_price"]
        gap_fill = is_gap_fill(trade.direction, entry_open, trigger)
        fill_bar = classify_fill(trade.signal_time, trade.entry_time)
        quantity = recover_quantity(trade.pnl, trade.direction,
                                    trade.entry_price, trade.exit_price,
                                    commission_percent)
        costs = decompose_costs(
            direction=trade.direction, quantity=quantity, trigger=trigger,
            entry_open=entry_open, entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            commission_percent=commission_percent,
            slippage_percent=slippage_percent, net_pnl=trade.pnl,
        )
        movement = excursion(
            held, direction=trade.direction, entry_price=trade.entry_price,
            exit_price=trade.exit_price, stop_price=trade.stop_loss,
            quantity=quantity, gap_fill=gap_fill,
        )
        sign = 1 if trade.direction == "LONG" else -1
        trigger_to_fill = sign * (trade.entry_price - trigger)
        record = {
            "segment_id": trade.segment_id, "trade_id": trade.trade_id,
            "setup_id": trade.setup_id,
            "signal_time": trade.signal_time,
            **signal,
            "direction": trade.direction,
            "entry_time": trade.entry_time,
            "entry_open": entry_open,
            "actual_fill_price": trade.entry_price,
            "filled_on": fill_bar,
            "gap_through_trigger": gap_fill,
            "fill_quality": "Gap-through-trigger" if gap_fill else "Normal",
            "trigger_to_fill_difference": trigger_to_fill,
            "trigger_to_fill_difference_atr": trigger_to_fill / signal["atr"],
            "structural_stop": trade.stop_loss,
            "actual_risk_distance": abs(trade.entry_price - trade.stop_loss),
            "actual_risk_distance_atr": abs(trade.entry_price - trade.stop_loss) / signal["atr"],
            "target": trade.take_profit,
            "exit_time": trade.exit_time, "exit_price": trade.exit_price,
            "exit_reason": trade.exit_reason,
            "bars_held": trade.bars_held,
            "net_pnl": trade.pnl, "pnl": trade.pnl,
            "realized_r": trade.realized_r,
            "planned_risk_dollars": (trade.pnl / trade.realized_r
                                     if abs(trade.realized_r) > 1e-12 else None),
            **costs, **movement,
        }
        records.append(record)
    result = pd.DataFrame(records)
    if result.duplicated(["segment_id", "trade_id"]).any():
        raise ValueError("Duplicate segment/trade IDs in the frozen export.")
    return result


def winner_loser_profile(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, field in PROFILE_FIELDS:
        for outcome, subset in (("Winner", trades.loc[trades.net_pnl > 1e-9]),
                                ("Loser", trades.loc[trades.net_pnl < -1e-9])):
            values = subset[field].dropna()
            rows.append({
                "descriptor": label, "field": field, "outcome": outcome,
                "count": len(values),
                "mean": float(values.mean()) if len(values) else None,
                "median": float(values.median()) if len(values) else None,
                "percentile_25": float(values.quantile(.25)) if len(values) else None,
                "percentile_75": float(values.quantile(.75)) if len(values) else None,
            })
    return pd.DataFrame(rows)


FIXED_BUCKETS = (
    ("ADX", "adx", (18, 20, 25, 30, 40, inf),
     ("18-20", "20-25", "25-30", "30-40", "40+")),
    ("EMA20 extension ATR", "ema20_extension_atr", (0, .5, 1, 1.5, 2, 2.5),
     ("0-0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0", "2.0-2.5")),
    ("Stop distance ATR", "planned_stop_distance_atr", (.6, 1, 1.5, 2, 2.5, 3),
     ("0.6-1.0", "1.0-1.5", "1.5-2.0", "2.0-2.5", "2.5-3.0")),
    ("Breakout range ATR", "range_atr", (.6, 1, 1.5, 2, 2.75),
     ("0.6-1.0", "1.0-1.5", "1.5-2.0", "2.0-2.75")),
    ("Body %", "body_percent", (50, 60, 70, 80, 90, 100),
     ("50-60", "60-70", "70-80", "80-90", "90-100")),
    ("Structure breakout distance ATR", "structure_breakout_distance_atr",
     (0, .25, .5, 1, 1.5, inf),
     ("0-0.25", "0.25-0.5", "0.5-1.0", "1.0-1.5", "1.5+")),
)


def bucket_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    specs = list(FIXED_BUCKETS)
    for name, field in (("ATR %", "atr_percent"),
                        ("H1 EMA200 slope %", "h1_ema200_slope_percent")):
        unique_edges = sorted(set(float(value) for value in
                                  trades[field].quantile([0, .2, .4, .6, .8, 1])))
        if len(unique_edges) < 2:
            unique_edges = [unique_edges[0], unique_edges[0] + 1e-9]
        edges = tuple(unique_edges)
        labels = tuple(f"Q{i + 1}: {edges[i]:.4f}–{edges[i + 1]:.4f}"
                       for i in range(len(edges) - 1))
        specs.append((name, field, edges, labels))
    rows = []
    for name, field, edges, labels in specs:
        assigned = trades[field].map(lambda value: bucket_label(value, edges, labels))
        if (assigned == "Outside defined range").any():
            raise ValueError(f"Frozen {name} values fall outside defined buckets.")
        for label in labels:
            for side in ("All", "Long", "Short"):
                mask = assigned.eq(label)
                if side != "All":
                    mask &= trades.direction.eq(side.upper())
                stats = trade_statistics(trades.loc[mask])
                rows.append({"descriptor": name, "field": field,
                             "bucket": label, "direction": side,
                             **stats, "small_sample": stats["trades"] < SMALL_SAMPLE})
    return pd.DataFrame(rows)


def time_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    periods = (
        ("UTC signal hour", "signal_utc_hour", list(range(24))),
        ("UTC weekday", "signal_utc_weekday",
         ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]),
        ("Calendar year", "signal_year", sorted(trades.signal_year.unique())),
        ("Calendar month", "signal_month", sorted(trades.signal_month.unique())),
        ("Analysis set", "analysis_set", sorted(trades.analysis_set.unique())),
    )
    rows = []
    for period_type, field, values in periods:
        for value in values:
            for side in ("All", "Long", "Short"):
                subset = trades.loc[trades[field].eq(value)]
                if side != "All":
                    subset = subset.loc[subset.direction.eq(side.upper())]
                stats = trade_statistics(subset)
                rows.append({"period_type": period_type, "period": value,
                             "direction": side, **stats,
                             "small_sample": stats["trades"] < SMALL_SAMPLE})
    return pd.DataFrame(rows)


def fill_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    groups = (("Pending fill bar", "filled_on", ("B+1", "B+2")),
              ("Trigger crossing", "fill_quality", ("Normal", "Gap-through-trigger")))
    rows = []
    for group_name, field, labels in groups:
        for label in labels:
            for side in ("All", "Long", "Short"):
                subset = trades.loc[trades[field].eq(label)]
                if side != "All":
                    subset = subset.loc[subset.direction.eq(side.upper())]
                stats = trade_statistics(subset)
                rows.append({"comparison": group_name, "fill_type": label,
                             "direction": side, **stats,
                             "small_sample": stats["trades"] < SMALL_SAMPLE})
    return pd.DataFrame(rows)


def mfe_mae_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    stopped = trades.exit_reason.str.startswith("Stop loss")
    groups = (
        ("All", trades),
        ("Long", trades.loc[trades.direction.eq("LONG")]),
        ("Short", trades.loc[trades.direction.eq("SHORT")]),
        ("Losing", trades.loc[trades.net_pnl < -1e-9]),
        ("Losing Long", trades.loc[(trades.net_pnl < -1e-9) & trades.direction.eq("LONG")]),
        ("Losing Short", trades.loc[(trades.net_pnl < -1e-9) & trades.direction.eq("SHORT")]),
        ("Stopped", trades.loc[stopped]),
    )
    rows = []
    for name, group in groups:
        for threshold in THRESHOLDS:
            reached = int(group[f"reached_{threshold:g}r"].sum())
            rows.append({
                "population": name, "trades": len(group),
                "threshold_r": threshold, "reached": reached,
                "reached_percent": reached / len(group) * 100 if len(group) else 0.0,
                "never_reached_percent": (len(group) - reached) / len(group) * 100
                if len(group) else 0.0,
                "small_sample": len(group) < SMALL_SAMPLE,
            })
    return pd.DataFrame(rows)


def cost_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    groups = [("All", trades),
              ("Long", trades.loc[trades.direction.eq("LONG")]),
              ("Short", trades.loc[trades.direction.eq("SHORT")])]
    groups += [(name, trades.loc[trades.analysis_set.eq(name)])
               for name in sorted(trades.analysis_set.unique())]
    rows = []
    for name, group in groups:
        stats = trade_statistics(group)
        winners = group.loc[group.net_pnl > 1e-9]
        losers = group.loc[group.net_pnl < -1e-9]
        avg_winner = float(winners.realized_r.mean()) if len(winners) else 0.0
        avg_loser = float(losers.realized_r.mean()) if len(losers) else 0.0
        required_wr = breakeven_win_rate(avg_winner, avg_loser)
        gross = float(group.gross_price_movement_pnl.sum())
        fees = float(group.commission_cost.sum())
        slip = float(group.slippage_cost.sum())
        costs = fees + slip
        planned = group.planned_risk_dollars.dropna()
        cost_r = (float((group.total_transaction_cost /
                         group.planned_risk_dollars).mean()) if len(planned) == len(group)
                  and len(group) else None)
        absolute_gross = float(group.gross_price_movement_pnl.abs().sum())
        rows.append({
            "population": name, **stats,
            "gross_price_movement_pnl": gross,
            "commission_cost": fees, "slippage_cost": slip,
            "total_transaction_cost": costs,
            "cost_per_trade": costs / len(group) if len(group) else 0.0,
            "cost_r_per_trade": cost_r,
            "cost_percent_of_absolute_gross_pnl":
                costs / absolute_gross * 100 if absolute_gross else None,
            "average_winner_r": avg_winner,
            "average_loser_r": avg_loser,
            "required_breakeven_win_rate_percent": required_wr,
            "win_rate_gap_pp": (stats["win_rate_percent"] - required_wr
                                if required_wr is not None else None),
            "small_sample": len(group) < SMALL_SAMPLE,
        })
        if not isclose(gross - costs, stats["net_pnl"], rel_tol=1e-9, abs_tol=1e-6):
            raise ValueError(f"Cost totals do not reconcile for {name}.")
    return pd.DataFrame(rows)


def stopped_trade_summary(trades: pd.DataFrame) -> dict:
    stopped = trades.loc[trades.exit_reason.str.startswith("Stop loss")]
    count = len(stopped)
    return {
        "trades": count,
        "median_mfe_r": float(stopped.mfe_r.median()) if count else 0.0,
        "average_mfe_r": float(stopped.mfe_r.mean()) if count else 0.0,
        "never_reached_0.25r_percent":
            float((~stopped["reached_0.25r"]).mean() * 100) if count else 0.0,
        "never_reached_0.5r_percent":
            float((~stopped["reached_0.5r"]).mean() * 100) if count else 0.0,
        "median_stop_distance_atr":
            float(stopped.planned_stop_distance_atr.median()) if count else 0.0,
        **{f"reached_{threshold:g}r_percent":
           float(stopped[f"reached_{threshold:g}r"].mean() * 100) if count else 0.0
           for threshold in (.5, 1.0, 1.5, 2.0)},
    }


def descriptive_differences(profile: pd.DataFrame,
                            trades: pd.DataFrame) -> list[dict]:
    comparisons = []
    for label, field in PROFILE_FIELDS:
        rows = profile.loc[profile.field.eq(field)].set_index("outcome")
        winner = float(rows.loc["Winner", "median"])
        loser = float(rows.loc["Loser", "median"])
        iqr = float(trades[field].quantile(.75) - trades[field].quantile(.25))
        if iqr > 0:
            comparisons.append({
                "descriptor": label, "winner_median": winner,
                "loser_median": loser,
                "median_difference": winner - loser,
                "difference_over_pooled_iqr": (winner - loser) / iqr,
            })
    return sorted(comparisons,
                  key=lambda row: abs(row["difference_over_pooled_iqr"]),
                  reverse=True)[:5]


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_diagnostics(
    baseline_dir: Path = BASELINE_DIR,
    data_path: Path = CANONICAL_DATA_FILE,
    output_dir: Path = OUTPUT_DIR,
) -> dict:
    """Produce diagnostic files from frozen completed trades; no backtest run."""
    source_path = baseline_dir / "pooled_trades.csv"
    frozen = json.loads((baseline_dir / "summary.json").read_text())
    source = pd.read_csv(source_path)
    segments = pd.read_csv(baseline_dir / "all_segments.csv")
    data = load_ohlcv_csv(data_path)
    if len(continuous_segments(data)) != frozen["segments"]:
        raise ValueError("The canonical data segmentation changed since the frozen baseline.")
    if (len(source) != frozen["segment_aware_pooled"]["trades"] or
        source.direction.eq("LONG").sum() != frozen["segment_aware_pooled"]["long_trades"] or
        source.direction.eq("SHORT").sum() != frozen["segment_aware_pooled"]["short_trades"]):
        raise ValueError("The completed-trade export disagrees with frozen baseline counts.")
    trades = build_trade_diagnostics(data, segments, source)
    stats = trade_statistics(trades)
    if not (isclose(stats["net_pnl"], frozen["segment_aware_pooled"]["net_pnl"],
                    abs_tol=1e-6) and
            isclose(stats["profit_factor"],
                    frozen["segment_aware_pooled"]["profit_factor"], abs_tol=1e-9)):
        raise ValueError("Diagnostic outcomes disagree with the frozen baseline.")
    profile = winner_loser_profile(trades)
    buckets = bucket_analysis(trades)
    times = time_analysis(trades)
    fills = fill_analysis(trades)
    excursions = mfe_mae_analysis(trades)
    costs = cost_analysis(trades)
    stopped = stopped_trade_summary(trades)
    differences = descriptive_differences(profile, trades)
    excursion_summary = {
        name: {
            "trades": len(group),
            "average_mfe_r": float(group.mfe_r.mean()),
            "median_mfe_r": float(group.mfe_r.median()),
            "average_mae_r": float(group.mae_r.mean()),
            "median_mae_r": float(group.mae_r.median()),
            "average_bars_to_mfe": float(group.bars_to_mfe.mean()),
            "average_bars_to_mae": float(group.bars_to_mae.mean()),
        }
        for name, group in (
            ("All", trades),
            ("Long", trades.loc[trades.direction.eq("LONG")]),
            ("Short", trades.loc[trades.direction.eq("SHORT")]),
        )
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    exports = {
        "trade_diagnostics.csv": trades,
        "winner_loser_profile.csv": profile,
        "bucket_analysis.csv": buckets,
        "time_analysis.csv": times,
        "fill_analysis.csv": fills,
        "mfe_mae_analysis.csv": excursions,
        "cost_analysis.csv": costs,
    }
    for filename, frame in exports.items():
        frame.to_csv(output_dir / filename, index=False)
    all_costs = costs.loc[costs.population.eq("All")].iloc[0].to_dict()
    long_costs = costs.loc[costs.population.eq("Long")].iloc[0].to_dict()
    short_costs = costs.loc[costs.population.eq("Short")].iloc[0].to_dict()
    summary = {
        "source_baseline_commit": "bb8da1ab65130acbf1d53b37f6a672fc813fb320",
        "source_baseline_trade_sha256": _hash(source_path),
        "source_candles_sha256": _hash(data_path),
        "baseline": stats,
        "costs_and_breakeven": {"All": all_costs, "Long": long_costs,
                                "Short": short_costs},
        "stopped_trades": stopped,
        "excursion_summary": excursion_summary,
        "descriptive_differences": differences,
        "mfe_method": (
            "Conservative path-known excursions. Normal entry-bar opposite extreme and "
            "exit-bar extremes are excluded when their order relative to fill/exit is unknown. "
            "Excursion R uses actual fill-to-structural-stop price distance; realized R "
            "uses the engine's planned dollar risk. Threshold rates are lower bounds."
        ),
        "development_set": "2021-01-01 through 2024-12-31 UTC",
        "forward_validation_set": "2025-01-01 through latest 2026 data; previously observed, not pristine",
        "small_sample_threshold": SMALL_SAMPLE,
        "cost_method": (
            "Per-trade quantity is recovered from recorded net PnL, fill prices, and the "
            "frozen 0.05% per-side commission model. Raw price PnL reverses the audited "
            "slippage formula; this frozen baseline uses 0% slippage."
        ),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    _write_markdown(output_dir / "diagnostic_summary.md", summary,
                    excursions, fills, buckets, times)
    return summary


def _write_markdown(path: Path, summary: dict, excursions: pd.DataFrame,
                    fills: pd.DataFrame, buckets: pd.DataFrame,
                    times: pd.DataFrame) -> None:
    baseline = summary["baseline"]
    all_costs = summary["costs_and_breakeven"]["All"]
    stopped = summary["stopped_trades"]
    lines = [
        "# Frozen BTC V2.2 Setup B failure diagnostics", "",
        "This report describes the existing Phase 4B segment-aware pooled completed trades. No strategy parameters, execution rules, or trade outcomes were changed. The pooled result does not form a continuous compounded equity curve.",
        "", f"Source: `pooled_trades.csv` SHA-256 `{summary['source_baseline_trade_sha256']}`; canonical candles SHA-256 `{summary['source_candles_sha256']}`.",
        "", f"Baseline: {baseline['trades']} trades; WR {baseline['win_rate_percent']:.2f}%; PF {baseline['profit_factor']:.4f}; average R {baseline['average_r']:.4f}; net PnL ${baseline['net_pnl']:,.2f}.",
        "", "## Cost and breakeven analysis", "",
        summary["cost_method"], "",
        f"Pre-cost price-movement PnL ${all_costs['gross_price_movement_pnl']:,.2f}; commission ${all_costs['commission_cost']:,.2f}; slippage ${all_costs['slippage_cost']:,.2f}; total costs ${all_costs['total_transaction_cost']:,.2f}; final net PnL ${all_costs['net_pnl']:,.2f}.",
        "The aggregate price movement is modestly positive before costs; modeled commissions more than offset it. This is attribution within the frozen execution model, not a strategy change.",
        f"Average winner R {all_costs['average_winner_r']:.4f}; average loser R {all_costs['average_loser_r']:.4f}; required breakeven WR {all_costs['required_breakeven_win_rate_percent']:.2f}%; actual WR {all_costs['win_rate_percent']:.2f}%; gap {all_costs['win_rate_gap_pp']:.2f} percentage points.",
        "", "## MFE / MAE and exit diagnosis", "",
        summary["mfe_method"], "",
        "| Population | Trades | Reached 0.5R | 1R | 1.5R | 2R | 2.5R | 3R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("All", "Long", "Short", "Losing", "Stopped"):
        sub = excursions.loc[excursions.population.eq(name)].set_index("threshold_r")
        lines.append(f"| {name} | {int(sub.iloc[0].trades)} | " + " | ".join(
            f"{sub.loc[threshold, 'reached_percent']:.2f}%"
            for threshold in (.5, 1., 1.5, 2., 2.5, 3.)) + " |")
    lines += [
        "", f"Stopped trades: {stopped['trades']}; median/average MFE {stopped['median_mfe_r']:.3f}R / {stopped['average_mfe_r']:.3f}R; never reached 0.25R {stopped['never_reached_0.25r_percent']:.2f}%; never reached 0.5R {stopped['never_reached_0.5r_percent']:.2f}%; median stop distance {stopped['median_stop_distance_atr']:.3f} ATR.",
        "", "## Fill quality", "",
        "| Fill | Trades | WR % | PF | Avg R | Net PnL |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in fills.loc[fills.direction.eq("All")].itertuples(index=False):
        pf = "—" if row.profit_factor is None else f"{row.profit_factor:.3f}"
        lines.append(f"| {row.fill_type} | {row.trades} | {row.win_rate_percent:.2f} | {pf} | {row.average_r:.3f} | ${row.net_pnl:,.2f} |")
    lines += [
        "", "## Winner and loser descriptor differences", "",
        "Ranked by absolute median difference divided by the pooled interquartile range. This is descriptive and does not imply causation.", "",
        "| Descriptor | Winner median | Loser median | Difference / pooled IQR |",
        "|---|---:|---:|---:|",
    ]
    for row in summary["descriptive_differences"]:
        lines.append(f"| {row['descriptor']} | {row['winner_median']:.4f} | {row['loser_median']:.4f} | {row['difference_over_pooled_iqr']:.3f} |")
    lines += [
        "", "## Analysis sets", "",
        f"Development set: {summary['development_set']}. Forward-validation set for future changes: {summary['forward_validation_set']}. Performance in both periods has already been observed; the latter is not an untouched holdout.",
        "", f"Bucket and time tables retain every category, including losing and small-sample groups (<{SMALL_SAMPLE} trades). They are descriptive only. No bucket was selected or applied.",
        "", "[trade_diagnostics.csv](trade_diagnostics.csv) · [winner_loser_profile.csv](winner_loser_profile.csv) · [bucket_analysis.csv](bucket_analysis.csv) · [time_analysis.csv](time_analysis.csv) · [fill_analysis.csv](fill_analysis.csv) · [mfe_mae_analysis.csv](mfe_mae_analysis.csv) · [cost_analysis.csv](cost_analysis.csv)", "",
    ]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-dir", type=Path, default=BASELINE_DIR)
    parser.add_argument("--data", type=Path, default=CANONICAL_DATA_FILE)
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    print(json.dumps(build_diagnostics(args.baseline_dir, args.data, args.out),
                     indent=2, default=str))
