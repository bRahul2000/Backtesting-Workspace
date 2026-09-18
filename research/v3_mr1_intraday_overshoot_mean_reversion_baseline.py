"""Development-only baseline and diagnostics for V3-MR1 Intraday Overshoot Mean Reversion."""
from __future__ import annotations

from dataclasses import dataclass
from math import inf
from pathlib import Path
from statistics import mean

import pandas as pd

from engine.metrics import calculate_metrics
from engine.models import BacktestSettings, Candle, Direction, EquityPoint
from research.exness_cost_calibrated import run_synthetic_segment
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v3_mr1_intraday_overshoot_mean_reversion import (
    BtcV3MR1IntradayOvershootMeanReversion, FAIR_VALUE_REFERENCE, V3MR1Parameters,
)
from utils.data_validation import continuous_segments, load_ohlcv_csv

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "reports/v3_mr1_intraday_overshoot_mean_reversion"
DEVELOPMENT_START = pd.Timestamp("2021-01-01 00:00:00", tz="UTC")
DEVELOPMENT_END = pd.Timestamp("2024-12-31 23:45:00", tz="UTC")
STEP = pd.Timedelta(minutes=15)
MONTH_DAYS = 30.436875
SPREAD = 10.0
SETTINGS = BacktestSettings(
    starting_balance=10_000.0,
    risk_percent=0.25,
    risk_reward_ratio=2.0,
    commission_percent=0.0,
    slippage_percent=0.0,
    max_leverage=1.0,
)


@dataclass(frozen=True)
class WarmupPlan:
    m15_bars: int
    first_search_time: pd.Timestamp
    minimum_segment_candles: int


def warmup_plan(params: V3MR1Parameters, segment_start: pd.Timestamp) -> WarmupPlan:
    m15_bars = max(
        params.ema_slow,
        params.atr_length + 1,
        params.rsi_length + 1,
        params.di_length + params.adx_smoothing,
        params.excursion_lookback + 1,
    )
    first_search = segment_start + (m15_bars - 1) * STEP
    return WarmupPlan(m15_bars, first_search, m15_bars)


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


def _pf_from_values(values: pd.Series) -> float | None:
    profit = float(values[values > 1e-9].sum())
    loss = float(values[values < -1e-9].sum())
    return profit / abs(loss) if loss else inf if profit else None


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


def _mfe_mae_r(trade, frame_indexed: pd.DataFrame, spread: float) -> tuple[float, float]:
    side_frame = frame_indexed.loc[trade.entry_time:trade.exit_time]
    risk_distance = abs(trade.entry_price - trade.stop_loss)
    if risk_distance <= 0 or side_frame.empty:
        return float("nan"), float("nan")
    best = worst = 0.0
    rows = list(side_frame.iterrows())
    for j, (_, row) in enumerate(rows):
        bid = Candle(row.name if hasattr(row, "name") else None,
                     row.open, row.high, row.low, row.close, row.volume)
        if trade.direction is Direction.LONG:
            quote_high, quote_low = bid.high, bid.low
        else:
            quote_high, quote_low = bid.high + spread, bid.low + spread
        is_first = j == 0
        is_last = j == len(rows) - 1
        if is_last:
            move = ((trade.exit_price - trade.entry_price) if trade.direction is Direction.LONG
                    else (trade.entry_price - trade.exit_price))
            best = max(best, max(0.0, move))
            worst = max(worst, max(0.0, -move))
            continue
        if is_first and not trade.gap_through_trigger:
            continue
        if trade.direction is Direction.LONG:
            best = max(best, max(0.0, quote_high - trade.entry_price))
            worst = max(worst, max(0.0, trade.entry_price - quote_low))
        else:
            best = max(best, max(0.0, trade.entry_price - quote_low))
            worst = max(worst, max(0.0, quote_high - trade.entry_price))
    return best / risk_distance, worst / risk_distance


def _winner_loser_summary(diag: pd.DataFrame) -> pd.DataFrame:
    fields = [
        "distance_atr", "rsi", "adx", "ema20_ema50_separation_atr",
        "confirmation_body_percent", "confirmation_close_location_percent",
        "upper_wick_percent", "lower_wick_percent", "five_bar_excursion_atr",
        "stop_distance_atr", "mfe_r", "mae_r",
    ]
    rows = []
    for label, part in (("WINNER", diag.loc[diag.result_r > 0]),
                        ("LOSER", diag.loc[diag.result_r < 0])):
        for field in fields:
            s = pd.to_numeric(part[field], errors="coerce").dropna()
            rows.append({
                "result_group": label, "field": field, "count": len(s),
                "mean": s.mean() if len(s) else float("nan"),
                "median": s.median() if len(s) else float("nan"),
                "p25": s.quantile(.25) if len(s) else float("nan"),
                "p75": s.quantile(.75) if len(s) else float("nan"),
            })
    return pd.DataFrame(rows)


def _bucket_rows(diag: pd.DataFrame, dimension: str, series: pd.Series,
                 bins, labels, *, side: str = "ALL") -> list[dict]:
    bucketed = pd.cut(series, bins=bins, labels=labels, include_lowest=True, right=True)
    rows = []
    for label in labels:
        part = diag.loc[bucketed == label]
        if part.empty:
            continue
        rows.append({
            "dimension": dimension,
            "side": side,
            "bucket": str(label),
            "trades": len(part),
            "wins": int((part.result_r > 0).sum()),
            "losses": int((part.result_r < 0).sum()),
            "win_rate_percent": float((part.result_r > 0).mean() * 100),
            "profit_factor": _pf_from_values(part.pnl),
            "average_r": float(part.result_r.mean()),
            "net_pnl": float(part.pnl.sum()),
        })
    return rows


def _bucket_analysis(diag: pd.DataFrame) -> pd.DataFrame:
    if diag.empty:
        return pd.DataFrame()
    rows: list[dict] = []
    specs = [
        ("distance_atr", diag.distance_atr,
         [1.75, 2.00, 2.50, 3.00, 3.50, 4.00], ["1.75-2.0", "2.0-2.5", "2.5-3.0", "3.0-3.5", "3.5-4.0"]),
        ("adx", diag.adx,
         [0, 14, 18, 22, 25, 28], ["<=14", "14-18", "18-22", "22-25", "25-28"]),
        ("ema20_ema50_separation_atr", diag.ema20_ema50_separation_atr,
         [0, .25, .50, .75, 1.00, 1.25, 1.50], ["<=0.25", ".25-.50", ".50-.75", ".75-1.0", "1.0-1.25", "1.25-1.5"]),
        ("confirmation_body_percent", diag.confirmation_body_percent,
         [.40, .50, .60, .70, .80, .90, 1.0], ["40-50%", "50-60%", "60-70%", "70-80%", "80-90%", "90-100%"]),
        ("stop_distance_atr", diag.stop_distance_atr,
         [.50, .75, 1.00, 1.25, 1.50, 2.00, 2.50], [".50-.75", ".75-1.0", "1.0-1.25", "1.25-1.5", "1.5-2.0", "2.0-2.5"]),
        ("hour_utc", diag.hour_utc,
         [-.5, 3.5, 7.5, 11.5, 15.5, 19.5, 21.5], ["00-03", "04-07", "08-11", "12-15", "16-19", "20-21"]),
    ]
    for name, series, bins, labels in specs:
        rows.extend(_bucket_rows(diag, name, pd.to_numeric(series, errors="coerce"), bins, labels))

    for side, rsi_bins, rsi_labels, loc_bins, loc_labels in (
        ("LONG", [0, 20, 25, 30, 35], ["<=20", "20-25", "25-30", "30-35"],
         [60, 70, 80, 90, 100], ["60-70%", "70-80%", "80-90%", "90-100%"]),
        ("SHORT", [65, 70, 75, 80, 100], ["65-70", "70-75", "75-80", "80+"],
         [0, 10, 20, 30, 40], ["<=10%", "10-20%", "20-30%", "30-40%"]),
    ):
        part = diag.loc[diag.side == side].copy()
        if not part.empty:
            rows.extend(_bucket_rows(part, "rsi", pd.to_numeric(part.rsi, errors="coerce"), rsi_bins, rsi_labels, side=side))
            rows.extend(_bucket_rows(part, "confirmation_close_location_percent",
                                     pd.to_numeric(part.confirmation_close_location_percent, errors="coerce"),
                                     loc_bins, loc_labels, side=side))
    return pd.DataFrame(rows)


def build_baseline(data_path: Path = CANONICAL_DATA_FILE,
                   output_dir: Path = OUTPUT) -> dict:
    params = V3MR1Parameters()
    data = load_ohlcv_csv(data_path)
    data = data.loc[data.timestamp.between(DEVELOPMENT_START, DEVELOPMENT_END)].reset_index(drop=True)
    if data.empty:
        raise ValueError("V3-MR1 development dataset is empty.")
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
        strategy = BtcV3MR1IntradayOvershootMeanReversion(params)
        result = run_synthetic_segment(frame, strategy, SPREAD, plan.first_search_time, SETTINGS)
        _add_closed_trade_equity(result)
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
                raise RuntimeError(f"Missing V3-MR1 diagnostics for {sid} {trade.signal_time}")
            mfe_r, mae_r = _mfe_mae_r(trade, indexed, SPREAD)
            st = pd.Timestamp(diag["signal_candle_time"])
            diagnostics.append({
                "segment_id": sid,
                "trade_id": trade.trade_id,
                "setup_id": trade.setup_id,
                "signal_time": trade.signal_time,
                "entry_time": trade.entry_time,
                "exit_time": trade.exit_time,
                "side": trade.direction.value,
                "fair_value_reference": FAIR_VALUE_REFERENCE,
                "year": st.year,
                "hour_utc": st.hour,
                "time_of_day_utc": st.strftime("%H:%M"),
                "day_of_week": st.day_name(),
                "entry_price": trade.entry_price,
                "exit_price": trade.exit_price,
                "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit,
                "pnl": trade.pnl,
                "result_r": trade.realized_r,
                "exit_reason": trade.exit_reason,
                "bars_held": trade.bars_held,
                "mfe_r": mfe_r,
                "mae_r": mae_r,
                **diag,
            })

    if not results:
        raise ValueError("No V3-MR1 development segment has enough warm-up.")

    overall = _stats(pooled)
    overall.update({
        "trades_per_month": len(pooled) / total_usable_months if total_usable_months else 0.0,
        "max_drawdown_percent": max(calculate_metrics(r).max_drawdown_percent for r in results),
        "max_losing_streak": max((_max_losing_streak(r.trades) for r in results), default=0),
        "usable_months": total_usable_months,
        "usable_segments": len(results),
        "open_positions_at_segment_end": sum(r.open_position is not None for r in results),
    })
    long_stats = _stats([t for t in pooled if t.direction is Direction.LONG])
    short_stats = _stats([t for t in pooled if t.direction is Direction.SHORT])
    yearly_rows = []
    for year in (2021, 2022, 2023, 2024):
        part = [t for t in pooled if pd.Timestamp(t.signal_time).year == year]
        yearly_rows.append({"year": year, **_stats(part)})

    segment_frame = pd.DataFrame(segment_rows)
    yearly_frame = pd.DataFrame(yearly_rows)
    diag_frame = pd.DataFrame(diagnostics)
    profile = _winner_loser_summary(diag_frame) if not diag_frame.empty else pd.DataFrame()
    buckets = _bucket_analysis(diag_frame) if not diag_frame.empty else pd.DataFrame()

    segment_frame.to_csv(output_dir / "development_segments.csv", index=False)
    yearly_frame.to_csv(output_dir / "yearly_results.csv", index=False)
    diag_frame.to_csv(output_dir / "trade_diagnostics.csv", index=False)
    profile.to_csv(output_dir / "winner_loser_profile.csv", index=False)
    buckets.to_csv(output_dir / "diagnostic_buckets.csv", index=False)

    summary = {
        "fair_value_reference": FAIR_VALUE_REFERENCE,
        "overall": overall, "long": long_stats, "short": short_stats,
        "yearly": yearly_rows, "diagnostics": diag_frame,
        "winner_loser_profile": profile, "diagnostic_buckets": buckets,
    }
    _write_summary(output_dir / "baseline.md", summary)
    return summary


def _fmt_pf(value) -> str:
    return "—" if value is None else "∞" if value == inf else f"{value:.4f}"


def _write_summary(path: Path, summary: dict) -> None:
    o, l, s = summary["overall"], summary["long"], summary["short"]
    lines = [
        "# BTC V3-MR1 — Intraday Overshoot Mean Reversion · development baseline", "",
        "Development only: 2021-01-01 through 2024-12-31. No forward validation and no optimization.",
        f"Fair-value reference: {summary['fair_value_reference']} (no audited session VWAP exists in the codebase).",
        "Execution: historical Bid candles + synthetic Exness Ask = Bid + $10/BTC; $0 commission; 0.25% risk; fixed 2R.",
        "", "## Overall", "",
        "| Trades | Trades/month | WR % | PF | Avg R | Net PnL | Worst segment DD % | Max losing streak |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {o['trades']} | {o['trades_per_month']:.2f} | {o['win_rate_percent']:.2f} | {_fmt_pf(o['profit_factor'])} | {o['average_r']:.4f} | {o['net_pnl']:.2f} | {o['max_drawdown_percent']:.4f} | {o['max_losing_streak']} |",
        "", "## Direction split", "",
        "| Side | Trades | WR % | PF | Avg R | Net PnL |",
        "|---|---:|---:|---:|---:|---:|",
        f"| Long | {l['trades']} | {l['win_rate_percent']:.2f} | {_fmt_pf(l['profit_factor'])} | {l['average_r']:.4f} | {l['net_pnl']:.2f} |",
        f"| Short | {s['trades']} | {s['win_rate_percent']:.2f} | {_fmt_pf(s['profit_factor'])} | {s['average_r']:.4f} | {s['net_pnl']:.2f} |",
        "", "## Yearly", "",
        "| Year | Trades | PF | Avg R | Net PnL |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in summary["yearly"]:
        lines.append(f"| {row['year']} | {row['trades']} | {_fmt_pf(row['profit_factor'])} | {row['average_r']:.4f} | {row['net_pnl']:.2f} |")
    lines += ["", "Winner/loser and bucket diagnostics are exported separately."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    result = build_baseline()
    print(result["overall"])
    print("LONG", result["long"])
    print("SHORT", result["short"])
    print(pd.DataFrame(result["yearly"]).to_string(index=False))
