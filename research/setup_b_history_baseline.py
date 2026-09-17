"""Describe the largest continuous BTC history with frozen V2.2 Setup B."""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from math import inf
from pathlib import Path
from statistics import median

import pandas as pd

from engine.backtester import run_backtest
from engine.metrics import calculate_metrics
from engine.models import BacktestSettings, Direction
from services.bitstamp import latest_complete_candle_open
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v2_setup_b import BtcV2SetupB, SetupBParameters
from utils.data_validation import (
    continuous_segments, largest_continuous_segment, load_ohlcv_csv,
    missing_gaps, validate_ohlcv,
)


DEFAULT_REPORT_DIR = Path(__file__).resolve().parents[1] / "reports" / "long_history"


def period_summary(trades, opening_balance: float) -> dict[str, float | int | None]:
    wins = [trade for trade in trades if trade.pnl > 1e-9]
    losses = [trade for trade in trades if trade.pnl < -1e-9]
    profit = sum(trade.pnl for trade in wins)
    loss = sum(trade.pnl for trade in losses)
    balance = peak = opening_balance
    drawdown_pct = 0.0
    longest_loss = streak = 0
    for trade in trades:
        balance += trade.pnl
        peak = max(peak, balance)
        if peak > 0:
            drawdown_pct = max(drawdown_pct, (peak - balance) / peak * 100)
        streak = streak + 1 if trade.pnl < -1e-9 else 0
        longest_loss = max(longest_loss, streak)
    count = len(trades)
    return {
        "trades": count,
        "long_trades": sum(t.direction is Direction.LONG for t in trades),
        "short_trades": sum(t.direction is Direction.SHORT for t in trades),
        "wins": len(wins), "losses": len(losses),
        "breakeven": count - len(wins) - len(losses),
        "win_rate": len(wins) / count * 100 if count else 0.0,
        "gross_profit": profit, "gross_loss": loss,
        "net_pnl": sum(trade.pnl for trade in trades),
        "profit_factor": profit / abs(loss) if losses else inf if wins else None,
        "average_r": sum(t.realized_r for t in trades) / count if count else 0.0,
        "median_r": median(t.realized_r for t in trades) if count else 0.0,
        "expectancy_r": sum(t.realized_r for t in trades) / count if count else 0.0,
        "average_winner_r": sum(t.realized_r for t in wins) / len(wins) if wins else 0.0,
        "average_loser_r": sum(t.realized_r for t in losses) / len(losses) if losses else 0.0,
        "max_drawdown_percent": drawdown_pct,
        "maximum_losing_streak": longest_loss,
    }


def _balance_before(trades, start: pd.Timestamp, initial: float) -> float:
    return initial + sum(t.pnl for t in trades if t.exit_time < start)


def _period_trades(trades, start: pd.Timestamp, end: pd.Timestamp):
    return [t for t in trades if start <= t.exit_time < end]


def _pf_text(value: float | None) -> str:
    return "—" if value is None else "∞" if value == inf else f"{value:.4f}"


def build_report(data_path: Path = CANONICAL_DATA_FILE,
                 output_dir: Path = DEFAULT_REPORT_DIR) -> dict:
    data = load_ohlcv_csv(data_path)
    quality = validate_ohlcv(data)
    segments = continuous_segments(data)
    gaps = missing_gaps(data)
    latest_complete = latest_complete_candle_open()
    trailing_missing = max(0, int((latest_complete - quality.last_candle) /
                                  pd.Timedelta(minutes=15))) if quality.last_candle is not None else 0
    output_dir.mkdir(parents=True, exist_ok=True)
    quality_json = {
        "first_candle": str(quality.first_candle),
        "last_candle": str(quality.last_candle),
        "total_candles": quality.total_candles,
        "expected_candles": quality.expected_candles,
        "missing_candles": quality.missing_candles,
        "latest_complete_at_report": str(latest_complete),
        "trailing_unavailable_candles": trailing_missing,
        "duplicate_timestamps": quality.duplicate_timestamps,
        "invalid_ohlc_rows": quality.invalid_ohlcv_rows,
        "continuous_segments": [asdict(segment) for segment in segments],
        "gaps": [asdict(gap) for gap in gaps],
        "last_update_utc": str(pd.Timestamp(data_path.stat().st_mtime, unit="s", tz="UTC")),
    }
    provenance = data_path.parent / "btcusd_15m_provenance.json"
    if provenance.exists():
        quality_json["provenance_file"] = str(provenance)
    (output_dir / "data_quality.json").write_text(json.dumps(quality_json, indent=2, default=str) + "\n")
    pd.DataFrame([asdict(segment) for segment in segments]).to_csv(
        output_dir / "continuous_segments.csv", index=False)
    pd.DataFrame([asdict(gap) for gap in gaps]).to_csv(
        output_dir / "data_gaps.csv", index=False)
    selected, largest = largest_continuous_segment(data)
    if largest is None:
        raise ValueError("No saved BTC candles are available.")
    settings = BacktestSettings(risk_percent=0.25, risk_reward_ratio=3.0,
                                commission_percent=0.05)
    strategy = BtcV2SetupB(SetupBParameters())
    result = run_backtest(selected, strategy, settings)
    metrics = calculate_metrics(result)
    trades = result.trades
    first, last = largest.start, largest.end
    finish = last + pd.Timedelta(minutes=15)
    month_equivalent = largest.candles * 15 / (60 * 24 * 30.4375)

    yearly = []
    for year in range(first.year, last.year + 1):
        start = max(first, pd.Timestamp(year=year, month=1, day=1, tz="UTC"))
        end = min(finish, pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC"))
        if start >= end:
            continue
        row = period_summary(_period_trades(trades, start, end),
                             _balance_before(trades, start, settings.starting_balance))
        covered_months = (end - start) / pd.Timedelta(days=30.4375)
        yearly.append({"year": year, **row,
                       "trades_per_month": row["trades"] / covered_months})

    monthly = []
    month = first.normalize().replace(day=1)
    while month < finish:
        end = month + pd.DateOffset(months=1)
        start = max(first, month)
        period_end = min(finish, end)
        if start < period_end:
            row = period_summary(_period_trades(trades, start, period_end),
                                 _balance_before(trades, start, settings.starting_balance))
            monthly.append({"month": month.strftime("%Y-%m"), **row})
        month = end

    rolling = []
    start = first
    while start + pd.DateOffset(months=6) <= finish:
        end = start + pd.DateOffset(months=6)
        row = period_summary(_period_trades(trades, start, end),
                             _balance_before(trades, start, settings.starting_balance))
        rolling.append({"period": f"{start:%Y-%m-%d} to {(end - pd.Timedelta(minutes=15)):%Y-%m-%d}",
                        **row})
        start = end

    sides = {
        direction.value: period_summary([t for t in trades if t.direction is direction],
                                        settings.starting_balance)
        for direction in (Direction.LONG, Direction.SHORT)
    }
    pd.DataFrame(yearly).to_csv(output_dir / "yearly.csv", index=False)
    pd.DataFrame(monthly).to_csv(output_dir / "monthly.csv", index=False)
    pd.DataFrame(rolling).to_csv(output_dir / "rolling_6m.csv", index=False)

    # Separate runs preserve the account and indicator boundary at each gap.
    # These rows are descriptive; their PnL must not be added to the primary run.
    additional_segments = []
    additional_yearly = []
    additional_rolling = []
    for segment_number, segment in enumerate(segments, 1):
        if segment == largest or segment.candles < 90 * 96:
            continue
        fragment = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        separate_strategy = BtcV2SetupB(SetupBParameters())
        separate_result = run_backtest(fragment, separate_strategy, settings)
        separate_metrics = calculate_metrics(separate_result)
        segment_key = f"segment_{segment_number:02d}"
        additional_segments.append({
            "segment": segment_key, "start": segment.start, "end": segment.end,
            "candles": segment.candles,
            "months": segment.candles * 15 / (60 * 24 * 30.4375),
            "long_signals": separate_strategy.diagnostics["Final Long Signals"],
            "short_signals": separate_strategy.diagnostics["Final Short Signals"],
            "trades": separate_metrics.total_trades,
            "win_rate": separate_metrics.win_rate_percent,
            "net_pnl": separate_metrics.net_pnl,
            "profit_factor": separate_metrics.profit_factor,
            "average_r": separate_metrics.average_r_multiple,
            "max_drawdown_percent": separate_metrics.max_drawdown_percent,
        })
        for year in range(segment.start.year, segment.end.year + 1):
            year_start = max(segment.start, pd.Timestamp(year=year, month=1, day=1, tz="UTC"))
            year_end = min(segment.end + pd.Timedelta(minutes=15),
                           pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC"))
            if year_start >= year_end:
                continue
            row = period_summary(_period_trades(separate_result.trades, year_start, year_end),
                                 _balance_before(separate_result.trades, year_start,
                                                 settings.starting_balance))
            additional_yearly.append({
                "segment": segment_key, "segment_start": segment.start,
                "segment_end": segment.end, "year": year, **row,
                "trades_per_month": row["trades"] /
                    ((year_end - year_start) / pd.Timedelta(days=30.4375)),
            })
        rolling_start = segment.start
        while rolling_start + pd.DateOffset(months=6) <= segment.end + pd.Timedelta(minutes=15):
            rolling_end = rolling_start + pd.DateOffset(months=6)
            row = period_summary(_period_trades(separate_result.trades,
                                                rolling_start, rolling_end),
                                 _balance_before(separate_result.trades, rolling_start,
                                                 settings.starting_balance))
            additional_rolling.append({
                "segment": segment_key, "start": rolling_start,
                "end_exclusive": rolling_end, **row,
            })
            rolling_start = rolling_end
    pd.DataFrame(additional_segments).to_csv(output_dir / "other_segments.csv", index=False)
    pd.DataFrame(additional_yearly).to_csv(output_dir / "other_segment_yearly.csv", index=False)
    pd.DataFrame(additional_rolling).to_csv(output_dir / "other_segment_rolling_6m.csv", index=False)
    orders = result.order_events
    summary = {
        "data_start": str(first), "data_end": str(last),
        "candles": largest.candles, "months": month_equivalent,
        "setup_id": "BTC_V2_SETUP_B",
        "signals_long": strategy.diagnostics["Final Long Signals"],
        "signals_short": strategy.diagnostics["Final Short Signals"],
        "pending_created": len(orders),
        "pending_filled": sum(e.status == "triggered" for e in orders),
        "pending_expired": sum(e.status == "expired" for e in orders),
        "pending_cancelled": sum(e.status == "cancelled" for e in orders),
        "trades_per_month": len(trades) / month_equivalent,
        "median_r": median(t.realized_r for t in trades) if trades else 0.0,
        "average_winner_r": sum(t.realized_r for t in trades if t.pnl > 1e-9) /
            max(sum(t.pnl > 1e-9 for t in trades), 1),
        "average_loser_r": sum(t.realized_r for t in trades if t.pnl < -1e-9) /
            max(sum(t.pnl < -1e-9 for t in trades), 1),
        "metrics": asdict(metrics), "long": sides["LONG"], "short": sides["SHORT"],
        "profitable_years": sum(row["net_pnl"] > 1e-9 for row in yearly),
        "losing_years": sum(row["net_pnl"] < -1e-9 for row in yearly),
        "profitable_months": sum(row["net_pnl"] > 1e-9 for row in monthly),
        "losing_months": sum(row["net_pnl"] < -1e-9 for row in monthly),
        "breakeven_months": sum(abs(row["net_pnl"]) <= 1e-9 for row in monthly),
        "rolling_window_count": len(rolling),
        "separately_tested_segments": len(additional_segments),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    lines = [
        "# Frozen BTC V2.2 Setup B history baseline", "",
        f"Largest continuous range: {first} to {last}; {largest.candles:,} candles; {month_equivalent:.2f} months.",
        f"Complete saved dataset: {quality.total_candles:,} candles, {quality.missing_candles:,} missing, {len(segments)} segments.",
        f"Latest completed candle at report time: {latest_complete}; the archive is {trailing_missing:,} candles behind it.",
        "", "Original Setup B defaults and the audited account settings from the validated checkpoint were used.",
        "The official Bitstamp OHLC endpoint was unreachable during this update. Expanded rows were conservatively aggregated from a documented Bitstamp one-minute archive; see `data/btcusd_15m_provenance.json`. The API-derived portion matched all 2,953 saved overlap candles. Differences in the older bulk portion on the isolated 2025-01-01 day are recorded in provenance, and saved canonical rows took precedence.",
        "", "## Full period", "",
        f"Signals long/short: {summary['signals_long']}/{summary['signals_short']}; pending created/filled/expired/cancelled: {summary['pending_created']}/{summary['pending_filled']}/{summary['pending_expired']}/{summary['pending_cancelled']}.",
        f"Trades {metrics.total_trades}; wins/losses/breakeven {metrics.winning_trades}/{metrics.losing_trades}/{metrics.breakeven_trades}; win rate {metrics.win_rate_percent:.2f}%.",
        f"Gross profit ${metrics.gross_profit:,.2f}; gross loss ${metrics.gross_loss:,.2f}; net PnL ${metrics.net_pnl:,.2f}; PF {_pf_text(metrics.profit_factor)}.",
        f"Average R {metrics.average_r_multiple:.4f}; median R {summary['median_r']:.4f}; expectancy R {metrics.expectancy_r:.4f}; winner R {summary['average_winner_r']:.4f}; loser R {summary['average_loser_r']:.4f}.",
        f"Max DD ${metrics.max_drawdown_dollars:,.2f} / {metrics.max_drawdown_percent:.4f}%; final balance ${metrics.final_balance:,.2f}; trades/month {summary['trades_per_month']:.2f}.",
        f"Maximum consecutive wins/losses {metrics.max_consecutive_wins}/{metrics.max_consecutive_losses}; average bars held {metrics.average_bars_held:.2f}.",
        "", "## Calendar years", "",
        "| Year | Trades | Long | Short | WR % | Net PnL $ | PF | Average R | Expectancy R | Max DD % | Trades/month |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in yearly:
        lines.append(f"| {row['year']} | {row['trades']} | {row['long_trades']} | {row['short_trades']} | {row['win_rate']:.2f} | {row['net_pnl']:,.2f} | {_pf_text(row['profit_factor'])} | {row['average_r']:.4f} | {row['expectancy_r']:.4f} | {row['max_drawdown_percent']:.4f} | {row['trades_per_month']:.2f} |")
    lines += ["", "## Direction", "",
              "| Side | Trades | WR % | Net PnL $ | PF | Average R | Expectancy R | Max losing streak |",
              "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for side, row in sides.items():
        lines.append(f"| {side} | {row['trades']} | {row['win_rate']:.2f} | {row['net_pnl']:,.2f} | {_pf_text(row['profit_factor'])} | {row['average_r']:.4f} | {row['expectancy_r']:.4f} | {row['maximum_losing_streak']} |")
    lines += ["", "## Non-overlapping six-month windows", "",
              "| Period | Trades | WR % | PF | Average R | Net PnL $ | Max DD % |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for row in rolling:
        lines.append(f"| {row['period']} | {row['trades']} | {row['win_rate']:.2f} | {_pf_text(row['profit_factor'])} | {row['average_r']:.4f} | {row['net_pnl']:,.2f} | {row['max_drawdown_percent']:.4f} |")
    if not rolling:
        lines.append("| No complete six-month window in this segment | — | — | — | — | — | — |")
    lines += ["", f"Monthly results: {summary['profitable_months']} profitable, {summary['losing_months']} losing, {summary['breakeven_months']} breakeven months. Download [monthly.csv](monthly.csv).", "",
              "## Other continuous segments", "",
              f"{len(additional_segments)} other segments of at least 90 days were backtested independently with fresh account and indicator state. Their results are in [other_segments.csv](other_segments.csv), [other_segment_yearly.csv](other_segment_yearly.csv), and [other_segment_rolling_6m.csv](other_segment_rolling_6m.csv). They are not combined into the primary balance or PnL.", ""]
    lines += ["## Data integrity gaps", "",
              f"All {len(gaps)} gaps are retained. Download [data_gaps.csv](data_gaps.csv) and [continuous_segments.csv](continuous_segments.csv).", "",
              "| Gap start UTC | Gap end UTC | Missing candles |",
              "|---|---|---:|"]
    for gap in gaps:
        lines.append(f"| {gap.start} | {gap.end} | {gap.missing_candles} |")
    lines.append("")
    (output_dir / "baseline.md").write_text("\n".join(lines))
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=CANONICAL_DATA_FILE)
    parser.add_argument("--out", type=Path, default=DEFAULT_REPORT_DIR)
    args = parser.parse_args()
    print(json.dumps(build_report(args.data, args.out), indent=2, default=str))
