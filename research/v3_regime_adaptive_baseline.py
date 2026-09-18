"""First development-only baseline for BTC V3.0 — Regime Adaptive.

Uses Bitstamp historical Bid candles with the already-audited synthetic Exness
quote-side replay at a fixed $10/BTC spread and $0 separate commission.
Forward-validation data (2025+) is deliberately excluded from this module.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import inf
from pathlib import Path
from statistics import mean

import pandas as pd

from engine.metrics import calculate_metrics
from engine.models import BacktestSettings, Direction, EquityPoint
from research.exness_cost_calibrated import run_synthetic_segment
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v3_regime_adaptive import (BtcV3RegimeAdaptive, RANGE_SETUP_ID,
                                                TREND_SETUP_ID, V3Parameters)
from utils.data_validation import continuous_segments, load_ohlcv_csv


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/v3_regime_adaptive"
DEVELOPMENT_START = pd.Timestamp("2021-01-01 00:00:00", tz="UTC")
DEVELOPMENT_END = pd.Timestamp("2024-12-31 23:45:00", tz="UTC")
STEP = pd.Timedelta(minutes=15)
MONTH_DAYS = 30.436875
SPREAD = 10.0
SETTINGS = BacktestSettings(
    starting_balance=10_000.0,
    risk_percent=0.25,
    risk_reward_ratio=3.0,
    commission_percent=0.0,
    slippage_percent=0.0,
    max_leverage=1.0,
)


@dataclass(frozen=True)
class V3WarmupPlan:
    m15_bars: int
    confirmed_h1_bars: int
    first_search_time: pd.Timestamp
    warmup_candles: int
    minimum_segment_candles: int


def v3_warmup_plan(params: V3Parameters, segment_start: pd.Timestamp) -> V3WarmupPlan:
    m15_bars = max(
        params.ema_slow,
        params.atr_length,
        params.rsi_length + 1,
        params.di_length + params.adx_smoothing,
        params.trend_structure_lookback + 1,
        params.range_sweep_lookback + 1,
        params.trend_stop_lookback,
    )
    h1_bars = max(params.h1_slow_ema + params.h1_slope_lookback,
                  params.h1_atr_length)
    first_full_hour = segment_start.ceil("h")
    h1_ready = first_full_hour + pd.Timedelta(hours=h1_bars)
    m15_ready = segment_start + (m15_bars - 1) * STEP
    first_search = max(h1_ready, m15_ready)
    warmup_candles = int((first_search - segment_start) / STEP)
    return V3WarmupPlan(m15_bars, h1_bars, first_search,
                        warmup_candles, warmup_candles + 1)


def add_closed_trade_equity(result) -> None:
    """Populate display metrics without changing the audited synthetic replay."""
    balance = peak = result.settings.starting_balance
    result.equity_curve = [EquityPoint(None, None, balance, peak, 0.0, 0.0)]
    for trade in result.trades:
        balance += trade.pnl
        peak = max(peak, balance)
        dd = peak - balance
        result.equity_curve.append(EquityPoint(
            trade.exit_time, trade.trade_id, balance, peak, dd,
            dd / peak * 100 if peak else 0.0,
        ))


def run_v3_synthetic_segment(frame: pd.DataFrame, strategy: BtcV3RegimeAdaptive,
                             spread: float, trade_start: pd.Timestamp,
                             settings: BacktestSettings = SETTINGS):
    result = run_synthetic_segment(frame, strategy, spread, trade_start, settings)
    add_closed_trade_equity(result)
    return result


def _pf(trades) -> float | None:
    wins = sum(t.pnl for t in trades if t.pnl > 1e-9)
    losses = sum(t.pnl for t in trades if t.pnl < -1e-9)
    return wins / abs(losses) if losses else inf if wins else None


def _trade_stats(trades) -> dict:
    count = len(trades)
    wins = sum(t.pnl > 1e-9 for t in trades)
    return {
        "trades": count,
        "wins": wins,
        "losses": sum(t.pnl < -1e-9 for t in trades),
        "win_rate_percent": wins / count * 100 if count else 0.0,
        "profit_factor": _pf(trades),
        "average_r": mean([t.realized_r for t in trades]) if trades else 0.0,
        "net_pnl": sum(t.pnl for t in trades),
    }


def _max_losing_streak(trades) -> int:
    current = worst = 0
    for trade in trades:
        if trade.pnl < -1e-9:
            current += 1
            worst = max(worst, current)
        elif abs(trade.pnl) > 1e-9:
            current = 0
    return worst


def _worst_segment_dd(results) -> float:
    return max((calculate_metrics(result).max_drawdown_percent
                for _, _, result in results), default=0.0)


def build_development_baseline(data_path: Path = CANONICAL_DATA_FILE,
                               output_dir: Path = OUTPUT) -> dict:
    data = load_ohlcv_csv(data_path)
    data = data.loc[data.timestamp.between(DEVELOPMENT_START, DEVELOPMENT_END)].reset_index(drop=True)
    if data.empty:
        raise ValueError("Development dataset is empty.")
    params = V3Parameters()
    output_dir.mkdir(parents=True, exist_ok=True)

    segment_rows: list[dict] = []
    results = []
    pooled_trades = []
    total_usable_months = 0.0
    for index, segment in enumerate(continuous_segments(data)):
        segment_id = f"D{index + 1:02d}"
        plan = v3_warmup_plan(params, segment.start)
        fragment = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        if len(fragment) < plan.minimum_segment_candles or plan.first_search_time > segment.end:
            segment_rows.append({
                "segment_id": segment_id, "start": segment.start, "end": segment.end,
                "candles": len(fragment), "usable": False,
                "first_search_time": plan.first_search_time,
                "reason": "Insufficient V3 warm-up",
            })
            continue
        strategy = BtcV3RegimeAdaptive(params)
        result = run_v3_synthetic_segment(fragment, strategy, SPREAD,
                                          plan.first_search_time, SETTINGS)
        usable_candles = len(fragment.loc[fragment.timestamp >= plan.first_search_time])
        usable_months = usable_candles * 15 / (60 * 24 * MONTH_DAYS)
        total_usable_months += usable_months
        stats = _trade_stats(result.trades)
        segment_rows.append({
            "segment_id": segment_id, "start": segment.start, "end": segment.end,
            "candles": len(fragment), "usable": True,
            "first_search_time": plan.first_search_time,
            "usable_months": usable_months,
            **stats,
            "max_drawdown_percent": calculate_metrics(result).max_drawdown_percent,
            "max_losing_streak": calculate_metrics(result).max_consecutive_losses,
            "trend_trades": sum(t.setup_id == TREND_SETUP_ID for t in result.trades),
            "range_trades": sum(t.setup_id == RANGE_SETUP_ID for t in result.trades),
        })
        results.append((segment_id, strategy, result))
        pooled_trades.extend(result.trades)

    if not results:
        raise ValueError("No development segment has enough V3 warm-up.")

    overall = _trade_stats(pooled_trades)
    overall.update({
        "max_drawdown_percent": _worst_segment_dd(results),
        "max_losing_streak": max((_max_losing_streak(result.trades)
                                   for _, _, result in results), default=0),
        "trades_per_month": len(pooled_trades) / total_usable_months if total_usable_months else 0.0,
        "usable_months": total_usable_months,
        "usable_segments": len(results),
    })
    trend = _trade_stats([t for t in pooled_trades if t.setup_id == TREND_SETUP_ID])
    range_ = _trade_stats([t for t in pooled_trades if t.setup_id == RANGE_SETUP_ID])
    long_ = _trade_stats([t for t in pooled_trades if t.direction is Direction.LONG])
    short_ = _trade_stats([t for t in pooled_trades if t.direction is Direction.SHORT])

    pd.DataFrame(segment_rows).to_csv(output_dir / "development_segments.csv", index=False)
    pd.DataFrame([{
        "segment_id": segment_id, "trade_id": t.trade_id, "setup_id": t.setup_id,
        "direction": t.direction.value, "signal_time": t.signal_time,
        "entry_time": t.entry_time, "entry_price": t.entry_price,
        "stop_loss": t.stop_loss, "take_profit": t.take_profit,
        "exit_time": t.exit_time, "exit_price": t.exit_price,
        "exit_reason": t.exit_reason, "quantity": t.quantity,
        "pnl": t.pnl, "realized_r": t.realized_r, "bars_held": t.bars_held,
    } for segment_id, _, result in results for t in result.trades]).to_csv(
        output_dir / "development_trades.csv", index=False)

    summary = {"overall": overall, "trend": trend, "range": range_,
               "long": long_, "short": short_, "segments": segment_rows}
    _write_summary(output_dir / "development_baseline.md", summary)
    return summary


def _fmt_pf(value) -> str:
    return "—" if value is None else "∞" if value == inf else f"{value:.4f}"


def _write_summary(path: Path, summary: dict) -> None:
    o, trend, range_, long_, short_ = (summary[key] for key in
                                       ("overall", "trend", "range", "long", "short"))
    lines = [
        "# BTC V3.0 — Regime Adaptive · first development baseline", "",
        "Development only: 2021-01-01 through 2024-12-31. Forward-validation data was not run.",
        "Execution: Bitstamp historical Bid candles + synthetic Exness-like Ask = Bid + $10/BTC; $0 separate commission; 0.25% risk; 3R; segments reset independently across data gaps.",
        "", "## Overall", "",
        "| Trades | Trades/month | WR % | PF | Avg R | Net PnL | Worst segment DD % | Max losing streak |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {o['trades']} | {o['trades_per_month']:.2f} | {o['win_rate_percent']:.2f} | {_fmt_pf(o['profit_factor'])} | {o['average_r']:.4f} | {o['net_pnl']:.2f} | {o['max_drawdown_percent']:.4f} | {o['max_losing_streak']} |",
        "", "## Engine split", "",
        "| Engine | Trades | WR % | PF | Avg R | Net PnL |",
        "|---|---:|---:|---:|---:|---:|",
        f"| TREND | {trend['trades']} | {trend['win_rate_percent']:.2f} | {_fmt_pf(trend['profit_factor'])} | {trend['average_r']:.4f} | {trend['net_pnl']:.2f} |",
        f"| RANGE | {range_['trades']} | {range_['win_rate_percent']:.2f} | {_fmt_pf(range_['profit_factor'])} | {range_['average_r']:.4f} | {range_['net_pnl']:.2f} |",
        "", "## Direction split", "",
        "| Direction | Trades | WR % | PF | Avg R | Net PnL |",
        "|---|---:|---:|---:|---:|---:|",
        f"| LONG | {long_['trades']} | {long_['win_rate_percent']:.2f} | {_fmt_pf(long_['profit_factor'])} | {long_['average_r']:.4f} | {long_['net_pnl']:.2f} |",
        f"| SHORT | {short_['trades']} | {short_['win_rate_percent']:.2f} | {_fmt_pf(short_['profit_factor'])} | {short_['average_r']:.4f} | {short_['net_pnl']:.2f} |",
        "", "No parameter optimization and no 2025–2026 forward validation were performed.", "",
    ]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    result = build_development_baseline()
    print(result["overall"])
