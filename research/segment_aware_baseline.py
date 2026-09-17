"""Frozen Setup B runs per continuous M15 segment, with trade-level pooling."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from math import inf
from pathlib import Path
from statistics import mean, median

import pandas as pd

from engine.backtester import run_backtest
from engine.metrics import calculate_metrics
from engine.models import BacktestSettings, Direction, Signal
from research.setup_b_history_baseline import DEFAULT_REPORT_DIR
from services.history import CANONICAL_DATA_FILE
from strategies.btc_v2_setup_b import BtcV2SetupB, SETUP_ID, SetupBParameters
from utils.data_validation import (
    continuous_segments, load_ohlcv_csv, missing_gaps, validate_ohlcv,
)


STEP = pd.Timedelta(minutes=15)
MONTH_DAYS = 30.4375
OUTPUT_DIR = DEFAULT_REPORT_DIR / "segment_aware"


@dataclass(frozen=True)
class WarmupPlan:
    m15_bars: int
    confirmed_h1_bars: int
    first_search_time: pd.Timestamp
    warmup_candles: int
    minimum_segment_candles: int


def warmup_plan(params: SetupBParameters, segment_start: pd.Timestamp) -> WarmupPlan:
    """Count full source bars needed by the frozen M15 and confirmed H1 inputs."""
    m15_bars = max(
        params.ema_fast, params.ema_slow, params.atr_length,
        params.rsi_length + 1, params.di_length + params.adx_smoothing,
        params.structure_lookback + 1, params.structure_stop_lookback,
    )
    h1_bars = max(params.h1_fast_ema, params.h1_slow_ema) + params.h1_slope_lookback
    first_full_hour = segment_start.ceil("h")
    h1_ready = first_full_hour + pd.Timedelta(hours=h1_bars)
    m15_ready = segment_start + (m15_bars - 1) * STEP
    first_search = max(h1_ready, m15_ready)
    warmup_candles = int((first_search - segment_start) / STEP)
    return WarmupPlan(m15_bars, h1_bars, first_search,
                      warmup_candles, warmup_candles + 1)


class ObservedSetupB(BtcV2SetupB):
    """Capture completed signal-time indicators without changing decisions."""
    def reset(self) -> None:
        super().reset()
        self.signal_regimes: dict[pd.Timestamp, dict] = {}

    def on_candle(self, candle):
        action = super().on_candle(candle)
        if isinstance(action, Signal):
            h1 = self.h1.confirmed
            atr = self.atr._average.value
            adx = self.dmi._adx.value
            if h1.slow_ema is None or h1.slow_ema_lookback is None or atr is None:
                raise RuntimeError("A Setup B signal lacks confirmed signal-time indicators.")
            slope = h1.slow_ema - h1.slow_ema_lookback
            self.signal_regimes[candle.timestamp + STEP] = {
                "h1_ema200_slope": slope,
                "h1_ema200_slope_magnitude": abs(slope),
                "m15_atr_percent": atr / candle.close * 100,
                "adx": adx,
                "confirmed_h1_hour": h1.hour,
            }
        return action


def trade_statistics(trades: list) -> dict:
    """Pool trade outcomes only; deliberately has no equity or drawdown field."""
    wins = [t for t in trades if t.pnl > 1e-9]
    losses = [t for t in trades if t.pnl < -1e-9]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = sum(t.pnl for t in losses)
    count = len(trades)
    r_values = [t.realized_r for t in trades]
    return {
        "trades": count,
        "long_trades": sum(t.direction is Direction.LONG for t in trades),
        "short_trades": sum(t.direction is Direction.SHORT for t in trades),
        "wins": len(wins), "losses": len(losses),
        "breakeven": count - len(wins) - len(losses),
        "win_rate_percent": len(wins) / count * 100 if count else 0.0,
        "gross_profit": gross_profit, "gross_loss": gross_loss,
        "net_pnl": sum(t.pnl for t in trades),
        "profit_factor": gross_profit / abs(gross_loss) if losses else inf if wins else None,
        "average_r": mean(r_values) if r_values else 0.0,
        "median_r": median(r_values) if r_values else 0.0,
        "expectancy_r": mean(r_values) if r_values else 0.0,
        "average_winner_r": mean(t.realized_r for t in wins) if wins else 0.0,
        "average_loser_r": mean(t.realized_r for t in losses) if losses else 0.0,
        "average_bars_held": mean(t.bars_held for t in trades) if trades else 0.0,
    }


def local_drawdown_percent(trades: list, opening_balance: float) -> float:
    """A drawdown within one segment or one segment-period only."""
    balance = peak = opening_balance
    worst = 0.0
    for trade in trades:
        balance += trade.pnl
        peak = max(peak, balance)
        if peak > 0:
            worst = max(worst, (peak - balance) / peak * 100)
    return worst


def segment_exclusion_reason(candles: int, plan: WarmupPlan) -> str | None:
    if candles >= plan.minimum_segment_candles:
        return None
    return (f"Only {candles} {'candle' if candles == 1 else 'candles'}; needs {plan.minimum_segment_candles} "
            f"for M15 indicators, {plan.confirmed_h1_bars} confirmed H1 bars "
            "and one signal-search candle.")


def run_independent_segment(frame: pd.DataFrame, strategy: BtcV2SetupB,
                            settings: BacktestSettings,
                            trade_start: pd.Timestamp):
    if len(continuous_segments(frame)) != 1:
        raise ValueError("An independent segment run needs exactly one continuous M15 range.")
    return run_backtest(frame, strategy, settings, trade_start=trade_start)


def segment_drawdown_statistics(rows: list[dict]) -> dict[str, float]:
    values = [row["max_drawdown_percent"] for row in rows]
    return {
        "worst_segment_drawdown_percent": max(values, default=0.0),
        "median_segment_drawdown_percent": median(values) if values else 0.0,
        "average_segment_drawdown_percent": mean(values) if values else 0.0,
    }


def aggregate_yearly(data: pd.DataFrame, results: list, pooled_trades: list,
                     starting_balance: float) -> list[dict]:
    yearly = []
    for year in range(data.timestamp.iloc[0].year, data.timestamp.iloc[-1].year + 1):
        start = pd.Timestamp(year=year, month=1, day=1, tz="UTC")
        end = pd.Timestamp(year=year + 1, month=1, day=1, tz="UTC")
        annual_trades = [t for t in pooled_trades if start <= t.exit_time < end]
        annual = trade_statistics(annual_trades)
        annual_dd = []
        represented = 0
        usable_candles = 0
        for _, segment, plan, result, _ in results:
            eligible_start = max(plan.first_search_time, start)
            eligible_end = min(segment.end + STEP, end)
            if eligible_start >= eligible_end:
                continue
            represented += 1
            usable_candles += int((eligible_end - eligible_start) / STEP)
            subset = [t for t in result.trades if start <= t.exit_time < end]
            opening = starting_balance + sum(
                t.pnl for t in result.trades if t.exit_time < start)
            annual_dd.append(local_drawdown_percent(subset, opening))
        yearly.append({"year": year, "usable_candles": usable_candles,
                       "segments_represented": represented, **annual,
                       "worst_segment_drawdown_percent": max(annual_dd, default=0.0)})
    return yearly


def aggregate_monthly(data: pd.DataFrame, pooled_trades: list) -> list[dict]:
    monthly = []
    month = data.timestamp.iloc[0].normalize().replace(day=1)
    final_month = data.timestamp.iloc[-1].normalize().replace(day=1)
    while month <= final_month:
        end = month + pd.DateOffset(months=1)
        month_trades = [t for t in pooled_trades if month <= t.exit_time < end]
        observed = int(data.timestamp.between(month, end - STEP).sum())
        expected = int((end - month) / STEP)
        stats = trade_statistics(month_trades)
        monthly.append({"month": month.strftime("%Y-%m"), **stats,
                        "source_candles": observed, "expected_source_candles": expected,
                        "incomplete_source_coverage": observed != expected,
                        "no_trade_month": not month_trades})
        month = end
    return monthly


def summarize_gaps(gaps: list) -> dict:
    sizes = [gap.missing_candles for gap in gaps]
    return {
        "number_of_gaps": len(gaps),
        "total_missing_candles": sum(sizes),
        "median_gap_size": median(sizes) if sizes else 0,
        "largest_gap_size": max(sizes, default=0),
        "one_candle": sum(size == 1 for size in sizes),
        "two_to_four": sum(2 <= size <= 4 for size in sizes),
        "five_to_sixteen": sum(5 <= size <= 16 for size in sizes),
        "seventeen_plus": sum(size >= 17 for size in sizes),
    }


def _pf(value) -> str:
    return "—" if value is None else "∞" if value == inf else f"{value:.4f}"


def _cash(value: float) -> str:
    return f"${value:,.2f}" if value >= 0 else f"−${abs(value):,.2f}"


def _write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    pd.DataFrame(rows, columns=columns).to_csv(path, index=False)


def build_segment_aware_baseline(
    data_path: Path = CANONICAL_DATA_FILE,
    output_dir: Path = OUTPUT_DIR,
) -> dict:
    data = load_ohlcv_csv(data_path)
    quality = validate_ohlcv(data)
    segments = continuous_segments(data)
    gaps = missing_gaps(data)
    params = SetupBParameters()  # Exact frozen V2.2 defaults.
    settings = BacktestSettings(risk_percent=0.25, risk_reward_ratio=3.0,
                                commission_percent=0.05)
    output_dir.mkdir(parents=True, exist_ok=True)
    segment_rows = []
    results = []
    pooled_trade_rows = []
    pooled_trades = []
    for index, segment in enumerate(segments):
        segment_id = f"S{index + 1:02d}"
        gap = gaps[index - 1] if index else None
        plan = warmup_plan(params, segment.start)
        duration_days = segment.candles * 15 / (60 * 24)
        base = {
            "segment_id": segment_id,
            "start": segment.start, "end": segment.end,
            "candles": segment.candles,
            "calendar_days": duration_days,
            "months": duration_days / MONTH_DAYS,
            "gap_before_start": gap.start if gap else None,
            "gap_before_end": gap.end if gap else None,
            "gap_before_missing_candles": gap.missing_candles if gap else 0,
            "required_m15_bars": plan.m15_bars,
            "required_confirmed_h1_bars": plan.confirmed_h1_bars,
            "minimum_segment_candles": plan.minimum_segment_candles,
            "first_search_time": plan.first_search_time,
            "warmup_candles": plan.warmup_candles,
        }
        reason = segment_exclusion_reason(segment.candles, plan)
        if reason is not None:
            segment_rows.append({**base, "usable": False,
                                 "exclusion_reason": reason})
            continue
        fragment = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        strategy = ObservedSetupB(params)
        result = run_independent_segment(fragment, strategy, settings,
                                         plan.first_search_time)
        metrics = calculate_metrics(result)
        if any(t.entry_time < segment.start or t.exit_time > segment.end
               for t in result.trades):
            raise AssertionError(f"A completed trade crossed {segment_id} boundary.")
        if any(e.setup_id != SETUP_ID for e in result.order_events):
            raise AssertionError(f"Unexpected setup ID in {segment_id}.")
        orders = Counter(e.status for e in result.order_events)
        signals_long = strategy.diagnostics["Final Long Signals"]
        signals_short = strategy.diagnostics["Final Short Signals"]
        usable_candles = segment.candles - plan.warmup_candles
        usable_months = usable_candles * 15 / (60 * 24 * MONTH_DAYS)
        row = {
            **base, "usable": True, "exclusion_reason": "",
            "usable_candles": usable_candles, "usable_months": usable_months,
            "long_signals": signals_long, "short_signals": signals_short,
            "signals": signals_long + signals_short,
            "pending_created": len(result.order_events),
            "pending_filled": orders["triggered"],
            "pending_expired": orders["expired"],
            "pending_cancelled": orders["cancelled"],
            "completed_trades": metrics.total_trades,
            "long_trades": sum(t.direction is Direction.LONG for t in result.trades),
            "short_trades": sum(t.direction is Direction.SHORT for t in result.trades),
            "wins": metrics.winning_trades, "losses": metrics.losing_trades,
            "breakeven": metrics.breakeven_trades,
            "win_rate_percent": metrics.win_rate_percent,
            "net_pnl": metrics.net_pnl, "profit_factor": metrics.profit_factor,
            "average_r": metrics.average_r_multiple,
            "expectancy_r": metrics.expectancy_r,
            "max_drawdown_percent": metrics.max_drawdown_percent,
            "maximum_losing_streak": metrics.max_consecutive_losses,
            "trades_per_month": metrics.total_trades / usable_months,
            "open_position_at_end": result.open_position is not None,
            "open_position_handling": (
                "Retained as open; unrealized PnL excluded; no forced exit."
                if result.open_position is not None else "No open position at segment end."
            ),
            "pending_at_end": result.pending_order is not None,
        }
        segment_rows.append(row)
        results.append((segment_id, segment, plan, result, row))
        for trade in result.trades:
            regime = strategy.signal_regimes.get(trade.signal_time)
            if regime is None:
                raise AssertionError(f"Missing signal-time regime for trade {segment_id}/{trade.trade_id}.")
            pooled_trades.append(trade)
            pooled_trade_rows.append({
                "segment_id": segment_id, "trade_id": trade.trade_id,
                "setup_id": trade.setup_id,
                "signal_time": trade.signal_time,
                "entry_time": trade.entry_time, "exit_time": trade.exit_time,
                "direction": trade.direction.value,
                "entry_price": trade.entry_price, "stop_loss": trade.stop_loss,
                "take_profit": trade.take_profit, "exit_price": trade.exit_price,
                "exit_reason": trade.exit_reason, "pnl": trade.pnl,
                "realized_r": trade.realized_r, "bars_held": trade.bars_held,
                "signal_year": trade.signal_time.year,
                "signal_month": trade.signal_time.strftime("%Y-%m"),
                **regime,
            })

    usable = [row for row in segment_rows if row["usable"]]
    excluded = [row for row in segment_rows if not row["usable"]]
    if not usable:
        raise ValueError("No continuous segment meets the calculated Setup B warm-up.")
    primary = max(usable, key=lambda row: row["candles"])
    pooled = trade_statistics(pooled_trades)
    pooled.update({
        "segments_included": len(usable),
        "signals": sum(row["signals"] for row in usable),
        "pending_created": sum(row["pending_created"] for row in usable),
        "pending_filled": sum(row["pending_filled"] for row in usable),
        "pending_expired": sum(row["pending_expired"] for row in usable),
        "pending_cancelled": sum(row["pending_cancelled"] for row in usable),
        "maximum_consecutive_losses_within_segment": max(
            row["maximum_losing_streak"] for row in usable),
        **segment_drawdown_statistics(usable),
        "observed_usable_months": sum(row["usable_months"] for row in usable),
    })
    pooled["trades_per_observed_usable_month"] = (
        pooled["trades"] / pooled["observed_usable_months"])
    side_results = {}
    for direction in (Direction.LONG, Direction.SHORT):
        side_trades = [trade for trade in pooled_trades if trade.direction is direction]
        side = trade_statistics(side_trades)
        side_dd = []
        for _, _, _, result, _ in results:
            subset = [t for t in result.trades if t.direction is direction]
            side_dd.append(local_drawdown_percent(subset, settings.starting_balance))
        side.update({
            "worst_segment_drawdown_percent": max(side_dd),
            "profitable_segments": sum(sum(t.pnl for t in result.trades
                                           if t.direction is direction) > 1e-9
                                       for _, _, _, result, _ in results),
            "losing_segments": sum(sum(t.pnl for t in result.trades
                                       if t.direction is direction) < -1e-9
                                   for _, _, _, result, _ in results),
        })
        side_results[direction.value] = side

    yearly = aggregate_yearly(data, results, pooled_trades, settings.starting_balance)
    monthly = aggregate_monthly(data, pooled_trades)
    gap_summary = summarize_gaps(gaps)
    _write_csv(output_dir / "all_segments.csv", segment_rows,
               list(segment_rows[0]))
    _write_csv(output_dir / "segment_results.csv", usable,
               list(usable[0]))
    _write_csv(output_dir / "pooled_trades.csv", pooled_trade_rows,
               list(pooled_trade_rows[0]) if pooled_trade_rows else [
                   "segment_id", "trade_id", "signal_time", "exit_time", "direction", "pnl", "realized_r"])
    _write_csv(output_dir / "yearly_results.csv", yearly, list(yearly[0]))
    _write_csv(output_dir / "monthly_results.csv", monthly, list(monthly[0]))
    summary = {
        "historical_start": str(quality.first_candle),
        "historical_end": str(quality.last_candle),
        "total_candles": quality.total_candles,
        "missing_candles": quality.missing_candles,
        "segments": len(segments), "usable_segments": len(usable),
        "excluded_segments": len(excluded),
        "warmup": asdict(warmup_plan(params, segments[0].start)),
        "primary_continuous": primary,
        "segment_aware_pooled": pooled,
        "long_pooled": side_results["LONG"],
        "short_pooled": side_results["SHORT"],
        "profitable_years": sum(row["net_pnl"] > 1e-9 for row in yearly),
        "losing_years": sum(row["net_pnl"] < -1e-9 for row in yearly),
        "profitable_months": sum(row["net_pnl"] > 1e-9 for row in monthly),
        "losing_months": sum(row["net_pnl"] < -1e-9 for row in monthly),
        "no_trade_months": sum(row["no_trade_month"] for row in monthly),
        "gap_summary": gap_summary,
        "segments_with_open_position_at_end": [
            row["segment_id"] for row in usable if row["open_position_at_end"]],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    _write_markdown(output_dir / "baseline.md", summary, segment_rows, yearly, monthly)
    return summary


def _write_markdown(path: Path, summary: dict, segments: list[dict],
                    yearly: list[dict], monthly: list[dict]) -> None:
    primary = summary["primary_continuous"]
    pooled = summary["segment_aware_pooled"]
    long = summary["long_pooled"]
    short = summary["short_pooled"]
    gaps = summary["gap_summary"]
    lines = [
        "# Segment-aware frozen BTC V2.2 Setup B robustness baseline", "",
        "Every continuous M15 segment starts a separate frozen Setup B backtest with fresh indicators, risk state, pending state, position state, and $10,000 balance. Trading begins only after the calculated warm-up. The pooled result combines completed trade outcomes; it is **not a continuous compounded equity curve**. No drawdown is calculated across a gap.",
        "", f"History: {summary['historical_start']} to {summary['historical_end']}; {summary['total_candles']:,} candles, {summary['missing_candles']} missing, {summary['segments']} segments ({summary['usable_segments']} usable, {summary['excluded_segments']} excluded).",
        f"Warm-up: {summary['warmup']['m15_bars']} M15 bars and {summary['warmup']['confirmed_h1_bars']} confirmed H1 bars. A segment beginning on an hour needs at least {summary['warmup']['minimum_segment_candles']} candles including one search candle; a partial first hour increases that number.",
        "", "## Primary continuous baseline", "",
        f"{primary['segment_id']}: {primary['start']} to {primary['end']}; {primary['candles']:,} candles, {primary['months']:.2f} calendar months ({primary['usable_months']:.2f} usable months).",
        f"Trades {primary['completed_trades']}; WR {primary['win_rate_percent']:.2f}%; PF {_pf(primary['profit_factor'])}; average R {primary['average_r']:.4f}; net PnL {_cash(primary['net_pnl'])}; max DD {primary['max_drawdown_percent']:.4f}%.",
        "", "## Segment-Aware Pooled Baseline", "",
        f"{pooled['segments_included']} independent segments; {pooled['trades']} trades ({pooled['long_trades']} long, {pooled['short_trades']} short); WR {pooled['win_rate_percent']:.2f}%; PF {_pf(pooled['profit_factor'])}; average/expectancy R {pooled['average_r']:.4f}; summed independent-run net PnL {_cash(pooled['net_pnl'])}.",
        f"Wins {pooled['wins']}; losses {pooled['losses']}; breakeven {pooled['breakeven']}. Gross profit {_cash(pooled['gross_profit'])}; gross loss {_cash(pooled['gross_loss'])}; median R {pooled['median_r']:.4f}; average winner/loser R {pooled['average_winner_r']:.4f} / {pooled['average_loser_r']:.4f}; average bars held {pooled['average_bars_held']:.2f}; maximum losing streak within any segment {pooled['maximum_consecutive_losses_within_segment']}.",
        f"Signals {pooled['signals']}; pending created {pooled['pending_created']}, filled {pooled['pending_filled']}, expired {pooled['pending_expired']}, cancelled {pooled['pending_cancelled']}.",
        f"Worst/median/average segment DD {pooled['worst_segment_drawdown_percent']:.4f}% / {pooled['median_segment_drawdown_percent']:.4f}% / {pooled['average_segment_drawdown_percent']:.4f}%. Trades per observed usable month {pooled['trades_per_observed_usable_month']:.2f}.",
        "", "## Pooled direction breakdown", "",
        "Side-only drawdown below replays that direction's completed trade PnL within each segment, starting from $10,000. It is descriptive and does not represent a separately run strategy.", "",
        "| Direction | Trades | Wins | Losses | WR % | PF | Net PnL | Avg R | Expectancy R | Worst side-only segment DD % | Profitable segments | Losing segments |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *(
            f"| {name} | {side['trades']} | {side['wins']} | {side['losses']} | {side['win_rate_percent']:.2f} | {_pf(side['profit_factor'])} | {_cash(side['net_pnl'])} | {side['average_r']:.4f} | {side['expectancy_r']:.4f} | {side['worst_segment_drawdown_percent']:.4f} | {side['profitable_segments']} | {side['losing_segments']} |"
            for name, side in (("Long", long), ("Short", short))
        ),
        "", "## Every data segment", "",
        "| ID | Start UTC | End UTC | Candles | Days | Gap before UTC | Missing before | Usable | Reason if excluded |",
        "|---|---|---|---:|---:|---|---:|---|---|",
    ]
    for row in segments:
        gap_before = (f"{row['gap_before_start']} to {row['gap_before_end']}"
                      if row["gap_before_start"] is not None else "—")
        lines.append(f"| {row['segment_id']} | {row['start']} | {row['end']} | {row['candles']:,} | {row['calendar_days']:.2f} | {gap_before} | {row['gap_before_missing_candles']} | {'yes' if row['usable'] else 'no'} | {row['exclusion_reason']} |")
    lines += ["", "## Usable segment results", "",
              "Each row is a separate account starting at $10,000. An open position at the final candle remains unrealized and is excluded from completed-trade metrics.", "",
              "| ID | Months | Candles | Signals | Pending | Filled | Trades | Long | Short | Wins | Losses | WR % | Net PnL | PF | Avg R | Expectancy R | Max DD % | Max losses | Trades/usable month |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in segments:
        if row["usable"]:
            lines.append(
                f"| {row['segment_id']} | {row['months']:.2f} | {row['candles']:,} | "
                f"{row['signals']} | {row['pending_created']} | {row['pending_filled']} | "
                f"{row['completed_trades']} | {row['long_trades']} | {row['short_trades']} | "
                f"{row['wins']} | {row['losses']} | {row['win_rate_percent']:.2f} | "
                f"{_cash(row['net_pnl'])} | {_pf(row['profit_factor'])} | "
                f"{row['average_r']:.4f} | {row['expectancy_r']:.4f} | "
                f"{row['max_drawdown_percent']:.4f} | {row['maximum_losing_streak']} | "
                f"{row['trades_per_month']:.2f} |"
            )
    lines += ["", "## Calendar years", "",
              "| Year | Usable candles | Segments | Trades | Long | Short | WR % | PF | Average/expectancy R | Net PnL | Worst segment DD % |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in yearly:
        lines.append(f"| {row['year']} | {row['usable_candles']:,} | {row['segments_represented']} | {row['trades']} | {row['long_trades']} | {row['short_trades']} | {row['win_rate_percent']:.2f} | {_pf(row['profit_factor'])} | {row['average_r']:.4f} | {_cash(row['net_pnl'])} | {row['worst_segment_drawdown_percent']:.4f} |")
    lines += ["", "## Months and gaps", "",
              f"Months: {summary['profitable_months']} profitable, {summary['losing_months']} losing, {summary['no_trade_months']} without a completed trade. [monthly_results.csv](monthly_results.csv) marks incomplete source coverage.",
              f"Gaps: {gaps['number_of_gaps']}; {gaps['total_missing_candles']} missing candles; median {gaps['median_gap_size']}; largest {gaps['largest_gap_size']}. Groups: one={gaps['one_candle']}, two-to-four={gaps['two_to_four']}, five-to-sixteen={gaps['five_to_sixteen']}, seventeen-plus={gaps['seventeen_plus']}.",
              "", "[segment_results.csv](segment_results.csv) · [pooled_trades.csv](pooled_trades.csv) · [yearly_results.csv](yearly_results.csv) · [monthly_results.csv](monthly_results.csv)", ""]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=CANONICAL_DATA_FILE)
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    print(json.dumps(build_segment_aware_baseline(args.data, args.out), indent=2,
                     default=str))
