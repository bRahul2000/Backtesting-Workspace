"""Development-only baseline and diagnostics for BTC V3-L2 Trend Pullback Long."""
from __future__ import annotations

from dataclasses import dataclass
from math import inf
from pathlib import Path
from statistics import mean

import pandas as pd

from engine.metrics import calculate_metrics
from engine.models import BacktestSettings, Candle, Direction, EquityPoint
from research.exness_cost_calibrated import ask_from_bid, run_synthetic_segment
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v3_l2_trend_pullback_long import (
    BtcV3L2TrendPullbackLong, SETUP_ID, V3L2Parameters,
)
from utils.data_validation import continuous_segments, load_ohlcv_csv

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/v3_l2_trend_pullback_long"
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
class WarmupPlan:
    m15_bars: int
    confirmed_h1_bars: int
    first_search_time: pd.Timestamp
    minimum_segment_candles: int


def warmup_plan(params: V3L2Parameters, segment_start: pd.Timestamp) -> WarmupPlan:
    m15_bars = max(
        params.ema_slow,
        params.atr_length,
        params.rsi_length + 1,
        params.di_length + params.adx_smoothing,
        params.local_structure_lookback + 1,
    )
    h1_bars = max(params.h1_slow_ema + params.h1_slope_lookback,
                  params.h1_atr_length)
    first_full_hour = segment_start.ceil("h")
    h1_ready = first_full_hour + pd.Timedelta(hours=h1_bars)
    m15_ready = segment_start + (m15_bars - 1) * STEP
    first_search = max(h1_ready, m15_ready)
    warmup_candles = int((first_search - segment_start) / STEP)
    return WarmupPlan(m15_bars, h1_bars, first_search, warmup_candles + 1)


def _add_closed_trade_equity(result) -> None:
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


def run_segment(frame: pd.DataFrame, strategy: BtcV3L2TrendPullbackLong,
                trade_start: pd.Timestamp):
    result = run_synthetic_segment(frame, strategy, SPREAD, trade_start, SETTINGS)
    _add_closed_trade_equity(result)
    return result


def _pf(trades) -> float | None:
    profit = sum(t.pnl for t in trades if t.pnl > 1e-9)
    loss = sum(t.pnl for t in trades if t.pnl < -1e-9)
    return profit / abs(loss) if loss else inf if profit else None


def _stats(trades) -> dict:
    n = len(trades)
    wins = sum(t.pnl > 1e-9 for t in trades)
    return {
        "trades": n,
        "wins": wins,
        "losses": sum(t.pnl < -1e-9 for t in trades),
        "win_rate_percent": wins / n * 100 if n else 0.0,
        "profit_factor": _pf(trades),
        "average_r": mean(t.realized_r for t in trades) if trades else 0.0,
        "net_pnl": sum(t.pnl for t in trades),
    }


def _max_losing_streak(trades) -> int:
    current = worst = 0
    for t in trades:
        if t.pnl < -1e-9:
            current += 1
            worst = max(worst, current)
        elif abs(t.pnl) > 1e-9:
            current = 0
    return worst


def _mfe_mae_r(trade, frame_indexed: pd.DataFrame) -> tuple[float, float]:
    """Conservative quote-side excursion after actual fill.

    For a normal intrabar stop fill, entry-bar extremes are skipped because their
    ordering relative to entry is unknown. On the exit bar only the actual exit
    price is treated as path-certain. This intentionally understates excursion.
    """
    side_frame = frame_indexed.loc[trade.entry_time:trade.exit_time]
    risk_distance = abs(trade.entry_price - trade.stop_loss)
    if risk_distance <= 0 or side_frame.empty:
        return float("nan"), float("nan")
    best = worst = 0.0
    rows = list(side_frame.iterrows())
    for j, (ts, row) in enumerate(rows):
        bid = Candle(ts, row.open, row.high, row.low, row.close, row.volume)
        quote = bid  # long exits/marks on Bid
        is_first = j == 0
        is_last = j == len(rows) - 1
        if is_last:
            move = trade.exit_price - trade.entry_price
            best = max(best, max(0.0, move))
            worst = max(worst, max(0.0, -move))
            continue
        if is_first and not trade.gap_through_trigger:
            continue
        best = max(best, max(0.0, quote.high - trade.entry_price))
        worst = max(worst, max(0.0, trade.entry_price - quote.low))
    return best / risk_distance, worst / risk_distance


def build_baseline(data_path: Path = CANONICAL_DATA_FILE,
                   output_dir: Path = OUTPUT) -> dict:
    params = V3L2Parameters()
    data = load_ohlcv_csv(data_path)
    data = data.loc[data.timestamp.between(DEVELOPMENT_START, DEVELOPMENT_END)].reset_index(drop=True)
    if data.empty:
        raise ValueError("V3-L2 development dataset is empty.")
    output_dir.mkdir(parents=True, exist_ok=True)

    pooled = []
    diagnostics = []
    segment_rows = []
    results = []
    total_usable_months = 0.0

    for idx, seg in enumerate(continuous_segments(data), 1):
        sid = f"D{idx:02d}"
        frame = data.loc[data.timestamp.between(seg.start, seg.end)].reset_index(drop=True)
        plan = warmup_plan(params, seg.start)
        if len(frame) < plan.minimum_segment_candles or plan.first_search_time > seg.end:
            segment_rows.append({"segment_id": sid, "start": seg.start, "end": seg.end,
                                 "candles": len(frame), "usable": False})
            continue
        strategy = BtcV3L2TrendPullbackLong(params)
        result = run_segment(frame, strategy, plan.first_search_time)
        results.append(result)
        pooled.extend(result.trades)
        usable_candles = len(frame.loc[frame.timestamp >= plan.first_search_time])
        usable_months = usable_candles * 15 / (60 * 24 * MONTH_DAYS)
        total_usable_months += usable_months
        metrics = calculate_metrics(result)
        segment_rows.append({
            "segment_id": sid, "start": seg.start, "end": seg.end,
            "candles": len(frame), "usable": True,
            "first_search_time": plan.first_search_time,
            "usable_months": usable_months,
            **_stats(result.trades),
            "max_drawdown_percent": metrics.max_drawdown_percent,
            "max_losing_streak": metrics.max_consecutive_losses,
            "open_at_end": result.open_position is not None,
        })
        indexed = frame.set_index("timestamp")
        for trade in result.trades:
            diag = strategy.signal_diagnostics.get(pd.Timestamp(trade.signal_time))
            if diag is None:
                raise RuntimeError(f"Missing V3-L2 signal diagnostics for {sid} {trade.signal_time}")
            mfe_r, mae_r = _mfe_mae_r(trade, indexed)
            diagnostics.append({
                "segment_id": sid,
                "trade_id": trade.trade_id,
                "setup_id": trade.setup_id,
                "signal_time": trade.signal_time,
                "entry_time": trade.entry_time,
                "exit_time": trade.exit_time,
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit,
                "pnl": trade.pnl,
                "realized_r": trade.realized_r,
                "exit_reason": trade.exit_reason,
                "bars_held": trade.bars_held,
                "mfe_r": mfe_r,
                "mae_r": mae_r,
                **diag,
            })

    if not results:
        raise ValueError("No V3-L2 development segment has enough warm-up.")

    overall = _stats(pooled)
    overall.update({
        "trades_per_month": len(pooled) / total_usable_months if total_usable_months else 0.0,
        "max_drawdown_percent": max(calculate_metrics(r).max_drawdown_percent for r in results),
        "max_losing_streak": max((_max_losing_streak(r.trades) for r in results), default=0),
        "usable_months": total_usable_months,
        "usable_segments": len(results),
        "open_positions_at_segment_end": sum(r.open_position is not None for r in results),
    })

    yearly_rows = []
    for year in (2021, 2022, 2023, 2024):
        part = [t for t in pooled if pd.Timestamp(t.signal_time).year == year]
        yearly_rows.append({"year": year, **_stats(part)})

    diag_frame = pd.DataFrame(diagnostics)
    segment_frame = pd.DataFrame(segment_rows)
    yearly_frame = pd.DataFrame(yearly_rows)
    segment_frame.to_csv(output_dir / "development_segments.csv", index=False)
    yearly_frame.to_csv(output_dir / "yearly_results.csv", index=False)
    diag_frame.to_csv(output_dir / "trade_diagnostics.csv", index=False)

    summary = {"overall": overall, "yearly": yearly_rows}
    _write_summary(output_dir / "baseline.md", summary)
    return summary


def _fmt_pf(value) -> str:
    return "—" if value is None else "∞" if value == inf else f"{value:.4f}"


def _write_summary(path: Path, summary: dict) -> None:
    o = summary["overall"]
    lines = [
        "# BTC V3-L2 Trend Pullback Long — first development baseline", "",
        "Development only: 2021-01-01 through 2024-12-31. No forward validation and no parameter optimization.",
        "Execution: Bitstamp historical Bid candles + synthetic Exness-like Ask = Bid + $10/BTC; $0 commission; 0.25% risk; fixed 3R.",
        "Operational definitions: local structure = most recent prior 5-bar high broken by a bullish-trend close; a material EMA50 close violation = 0.20 ATR below EMA50; confirmation must occur on a bar after pullback activation.",
        "", "## Overall", "",
        "| Trades | Trades/month | WR % | PF | Avg R | Net PnL | Worst segment DD % | Max losing streak |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {o['trades']} | {o['trades_per_month']:.2f} | {o['win_rate_percent']:.2f} | {_fmt_pf(o['profit_factor'])} | {o['average_r']:.4f} | {o['net_pnl']:.2f} | {o['max_drawdown_percent']:.4f} | {o['max_losing_streak']} |",
        "", "## Yearly", "",
        "| Year | Trades | WR % | PF | Avg R | Net PnL |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["yearly"]:
        lines.append(f"| {row['year']} | {row['trades']} | {row['win_rate_percent']:.2f} | {_fmt_pf(row['profit_factor'])} | {row['average_r']:.4f} | {row['net_pnl']:.2f} |")
    lines.extend(["", "No 2025–2026 data was run and no parameter was optimized after this baseline.", ""])
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    import json
    print(json.dumps(build_baseline(), indent=2, default=str))
