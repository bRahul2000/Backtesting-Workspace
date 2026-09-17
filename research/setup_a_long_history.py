"""Frozen Setup A across independent continuous Bitstamp BTC/USD M15 segments."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pandas as pd

from engine.backtester import run_backtest
from research.exness_native_validation import price_cost_view, summarize_trades
from research.exness_setup_a_validation import PARAMS, SETTINGS, setup_a_warmup
from research.setup_a_regime_diagnostics import ObserveSetupA
from research.setup_b_failure_diagnostics import excursion
from services.history import CANONICAL_DATA_FILE
from utils.data_validation import continuous_segments, load_ohlcv_csv


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/setup_a/long_history"
EXNESS_START = pd.Timestamp("2023-11-09T00:00:00Z")
REGIME_FIELDS = ("atr_percent", "recent_volatility_24h_percent", "adx",
                 "h1_directional_slope_percent", "ema_separation_atr")
PERIODS = (("2021–2022", 2021, 2022), ("2023–2024", 2023, 2024),
           ("2025–2026", 2025, 2026), ("Full 2021–2026", 2021, 2026))


def run_segments(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """One strategy, account, pending state, and indicator history per segment."""
    signal_rows, fill_rows, trade_rows, segment_rows = [], [], [], []
    for index, segment in enumerate(continuous_segments(data), 1):
        segment_id = f"bitstamp-S{index:02d}"
        minimum, first = setup_a_warmup(PARAMS, segment.start)
        row = {"segment_id": segment_id, "start": segment.start, "end": segment.end,
               "candles": segment.candles, "minimum_warmup_candles": minimum,
               "first_search_time": first, "usable": segment.candles >= minimum,
               "reason": "" if segment.candles >= minimum else
               "insufficient confirmed-H1 and M15 warm-up"}
        if not row["usable"]:
            segment_rows.append(row)
            continue
        frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        strategy = ObserveSetupA(PARAMS)
        result = run_backtest(frame, strategy, SETTINGS, trade_start=first)
        signals = list(strategy.signal_descriptors.values())
        statuses = Counter(event.status for event in result.order_events)
        row.update({"signals": len(signals), "filled_orders": statuses["triggered"],
                    "completed_trades": len(result.trades),
                    "open_position_at_end": result.open_position is not None,
                    "pending_at_end": result.pending_order is not None,
                    "engine_max_drawdown_percent": max(
                        (point.drawdown_percent for point in result.equity_curve), default=0.)})
        segment_trades = pd.DataFrame([
            {"direction": trade.direction.value, "gross_pnl": trade.pnl,
             "realized_r": trade.realized_r} for trade in result.trades])
        segment_stats = summarize_trades(segment_trades, net_column="gross_pnl",
                                         r_column="realized_r")
        row.update({"long_trades": segment_stats["long_trades"],
                    "short_trades": segment_stats["short_trades"],
                    "win_rate_percent": segment_stats["win_rate_percent"],
                    "profit_factor": segment_stats["profit_factor"],
                    "average_r": segment_stats["average_r"],
                    "net_pnl": segment_stats["net_pnl"]})
        segment_rows.append(row)
        signal_rows.extend({"segment_id": segment_id, "signal_year": signal["signal_year"],
                            "signal_time": signal["signal_candle_time"] + pd.Timedelta(minutes=15),
                            "direction": signal["direction"]} for signal in signals)
        fill_rows.extend({"segment_id": segment_id,
                          "signal_year": (event.signal_time - pd.Timedelta(minutes=15)).year,
                          "signal_time": event.signal_time, "direction": event.direction.value}
                         for event in result.order_events if event.status == "triggered")
        for trade in result.trades:
            if not segment.start <= trade.entry_time <= trade.exit_time <= segment.end:
                raise AssertionError("Bitstamp Setup A trade crossed a source gap.")
            descriptor = strategy.signal_descriptors[trade.signal_time]
            path = frame.loc[frame.timestamp.between(trade.entry_time, trade.exit_time)]
            mfe = excursion(path, direction=trade.direction.value,
                            entry_price=trade.entry_price, exit_price=trade.exit_price,
                            stop_price=trade.stop_loss, quantity=trade.quantity,
                            gap_fill=trade.gap_through_trigger)
            trade_rows.append({"segment_id": segment_id, "trade_id": trade.trade_id,
                               "signal_time": trade.signal_time, **descriptor,
                               "entry_time": trade.entry_time, "exit_time": trade.exit_time,
                               "entry_price": trade.entry_price, "exit_price": trade.exit_price,
                               "quantity": trade.quantity, "planned_risk": trade.initial_risk,
                               "gross_pnl": trade.pnl, "realized_r": trade.realized_r,
                               "exit_reason": trade.exit_reason, **mfe})
    return (pd.DataFrame(signal_rows), pd.DataFrame(fill_rows),
            pd.DataFrame(trade_rows), pd.DataFrame(segment_rows))


def worst_segment_dd(trades: pd.DataFrame, *, start: pd.Timestamp | None = None,
                     end: pd.Timestamp | None = None) -> float:
    """Closed-trade drawdown; each segment starts at audited account balance."""
    worst = 0.
    if trades.empty:
        return worst
    for _, group in trades.groupby("segment_id"):
        group = group.sort_values("exit_time")
        prior = group.loc[group.signal_time.lt(start), "gross_pnl"].sum() if start is not None else 0.
        balance = peak = SETTINGS.starting_balance + float(prior)
        selected = group
        if start is not None:
            selected = selected.loc[selected.signal_time.ge(start)]
        if end is not None:
            selected = selected.loc[selected.signal_time.lt(end)]
        for pnl in selected.gross_pnl:
            balance += pnl
            peak = max(peak, balance)
            worst = max(worst, (peak - balance) / peak * 100)
    return worst


def max_losing_streak(trades: pd.DataFrame) -> int:
    longest = 0
    for _, group in trades.groupby("segment_id"):
        streak = 0
        for pnl in group.sort_values("exit_time").gross_pnl:
            streak = streak + 1 if pnl < 0 else 0
            longest = max(longest, streak)
    return longest


def observed_months(data: pd.DataFrame) -> pd.DataFrame:
    """Distinct UTC months with usable source candles; partial months count once."""
    return data[["timestamp"]].assign(
        year=data.timestamp.dt.year,
        month=data.timestamp.dt.strftime("%Y-%m")).drop_duplicates(["year", "month"])


def performance(trades: pd.DataFrame) -> dict:
    stats = summarize_trades(trades, net_column="gross_pnl", r_column="realized_r")
    return {**stats, "median_r": float(trades.realized_r.median()) if len(trades) else 0.,
            "max_losing_streak": max_losing_streak(trades) if len(trades) else 0}


def yearly_results(signals: pd.DataFrame, fills: pd.DataFrame, trades: pd.DataFrame,
                   usable_data: pd.DataFrame) -> pd.DataFrame:
    months = observed_months(usable_data)
    rows = []
    for year in range(2021, 2027):
        s, f = signals.loc[signals.signal_year.eq(year)], fills.loc[fills.signal_year.eq(year)]
        t = trades.loc[trades.signal_year.eq(year)]
        count = int(months.year.eq(year).sum())
        rows.append({"year": year, "partial_year": year == 2026,
                     "signals": len(s), "fills": len(f),
                     "observed_months": count,
                     "signals_per_observed_month": len(s) / count if count else 0.,
                     "fills_per_observed_month": len(f) / count if count else 0.,
                     "trades_per_observed_month": len(t) / count if count else 0.,
                     **performance(t),
                     "worst_segment_dd_percent": worst_segment_dd(
                         trades, start=pd.Timestamp(f"{year}-01-01T00:00:00Z"),
                         end=pd.Timestamp(f"{year+1}-01-01T00:00:00Z"))})
    return pd.DataFrame(rows)


def period_results(signals: pd.DataFrame, fills: pd.DataFrame, trades: pd.DataFrame,
                   usable_data: pd.DataFrame) -> pd.DataFrame:
    months = observed_months(usable_data)
    rows = []
    for label, first, last in PERIODS:
        s = signals.loc[signals.signal_year.between(first, last)]
        f = fills.loc[fills.signal_year.between(first, last)]
        t = trades.loc[trades.signal_year.between(first, last)]
        count = int(months.year.between(first, last).sum())
        rows.append({"period": label, "signals": len(s), "fills": len(f),
                     "observed_months": count,
                     "signals_per_observed_month": len(s) / count if count else 0.,
                     "fills_per_observed_month": len(f) / count if count else 0.,
                     "trades_per_observed_month": len(t) / count if count else 0.,
                     **performance(t), "worst_segment_dd_percent": worst_segment_dd(
                         trades, start=pd.Timestamp(f"{first}-01-01T00:00:00Z"),
                         end=pd.Timestamp(f"{last+1}-01-01T00:00:00Z"))})
    return pd.DataFrame(rows)


def direction_results(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, group in [("Full", trades)] + [
        (str(year), trades.loc[trades.signal_year.eq(year)]) for year in range(2021, 2027)]:
        for side in ("LONG", "SHORT"):
            scoped = group.loc[group.direction.eq(side)]
            rows.append({"period": label, "direction": side, **performance(scoped)})
    return pd.DataFrame(rows)


def mfe_mae_results(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, group in [("Full", trades)] + [
        (str(year), trades.loc[trades.signal_year.eq(year)]) for year in range(2021, 2027)]:
        losers = group.loc[group.gross_pnl.lt(0)]
        row = {"period": label, "trades": len(group), "losing_trades": len(losers),
               "mean_mfe_r": group.mfe_r.mean(), "median_mfe_r": group.mfe_r.median(),
               "mean_mae_r": group.mae_r.mean(), "median_mae_r": group.mae_r.median()}
        for threshold in (.5, 1., 1.5, 2., 3.):
            field = f"reached_{threshold:g}r"
            row[field + "_percent"] = 100 * group[field].mean() if len(group) else 0.
            if threshold in (.5, 1., 2.):
                row["losers_" + field + "_percent"] = (
                    100 * losers[field].mean() if len(losers) else 0.)
        rows.append(row)
    return pd.DataFrame(rows)


def pre_exness_results(trades: pd.DataFrame) -> pd.DataFrame:
    pre = trades.loc[trades.signal_time.lt(EXNESS_START)]
    rows = []
    for period, subset in [("Full pre-Exness", pre)] + [
        (str(year), pre.loc[pre.signal_year.eq(year)]) for year in (2021, 2022, 2023)]:
        for side, group in [("ALL", subset), ("LONG", subset.loc[subset.direction.eq("LONG")]),
                            ("SHORT", subset.loc[subset.direction.eq("SHORT")])]:
            rows.append({"period": period, "direction": side, **performance(group)})
    return pd.DataFrame(rows)


def regime_summary(trades: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in range(2021, 2027):
        group = trades.loc[trades.signal_year.eq(year)]
        candles = source.loc[source.timestamp.dt.year.eq(year)]
        price_change = (100 * (candles.close.iloc[-1] / candles.close.iloc[0] - 1)
                        if len(candles) else float("nan"))
        rows.append({"year": year, "trades": len(group),
                     "observed_btc_price_change_percent": price_change,
                     **{f"median_{field}": group[field].median()
                        for field in REGIME_FIELDS}})
    return pd.DataFrame(rows)


def cost_sensitivity(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for spread in (0., 10., 20., 30.):
        priced = price_cost_view(trades, fixed_spread=spread)
        for label, group in [("Full 2021–2026", priced),
                             ("Pre-Exness", priced.loc[priced.signal_time.lt(EXNESS_START)])] + [
            (str(year), priced.loc[priced.signal_year.eq(year)]) for year in range(2021, 2027)]:
            rows.append({"period": label, "spread_usd_per_btc": spread,
                         "cost_label": "ZERO COST" if spread == 0 else
                         "HYPOTHETICAL COST SENSITIVITY — NOT HISTORICAL EXNESS SPREAD",
                         **summarize_trades(group, net_column="net_pnl",
                                            r_column="realized_r_costed")})
    return pd.DataFrame(rows)


def build_long_history(path: Path = CANONICAL_DATA_FILE,
                       output_dir: Path = REPORT) -> dict:
    data = load_ohlcv_csv(path)
    signals, fills, trades, segments = run_segments(data)
    if trades.empty:
        raise AssertionError("Frozen Setup A generated no completed Bitstamp trades.")
    usable = segments.loc[segments.usable]
    usable_data = pd.concat([data.loc[data.timestamp.between(row.start, row.end)]
                             for row in usable.itertuples()], ignore_index=True)
    # Existing exact-common-timestamp comparison is reused unchanged.
    native = pd.read_csv(ROOT / "reports/setup_a/native_results.csv")
    overlap = native.loc[(native.scope.eq("exact_common_timestamps")) &
                         native.cost_view.eq("zero_cost")]
    ex = overlap.loc[overlap.feed.eq("exness_overlap")].iloc[0]
    bs = overlap.loc[overlap.feed.eq("bitstamp_overlap")].iloc[0]
    match = json.loads((ROOT / "reports/setup_a/setup_a_validation_summary.json").read_text())["signal_overlap"]
    years = yearly_results(signals, fills, trades, usable_data)
    periods = period_results(signals, fills, trades, usable_data)
    if (int(usable.signals.sum()) != len(signals) or
        int(usable.filled_orders.sum()) != len(fills) or
        int(usable.completed_trades.sum()) != len(trades) or
        int(years.trades.sum()) != len(trades) or
        int(periods.loc[periods.period.eq("Full 2021–2026"), "trades"].iloc[0]) != len(trades)):
        raise AssertionError("Long-history segment, year, and full-period counts disagree.")
    directions = direction_results(trades)
    excursions = mfe_mae_results(trades)
    pre = pre_exness_results(trades)
    regimes = regime_summary(trades, usable_data)
    costs = cost_sensitivity(trades)
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, frame in (("segment_results.csv", segments),
                            ("yearly_results.csv", years), ("period_results.csv", periods),
                            ("direction_results.csv", directions), ("mfe_mae.csv", excursions),
                            ("pre_exness_results.csv", pre), ("regime_summary.csv", regimes),
                            ("cost_sensitivity.csv", costs)):
        frame.to_csv(output_dir / filename, index=False)
    summary = {"source_start": str(data.timestamp.iloc[0]),
               "source_end": str(data.timestamp.iloc[-1]),
               "source_candles": len(data), "segments": len(segments),
               "usable_segments": len(usable), "excluded_segments": len(segments) - len(usable),
               "exness_overlap_pf": float(ex.profit_factor),
               "exness_overlap_average_r": float(ex.average_r),
               "bitstamp_overlap_pf": float(bs.profit_factor),
               "bitstamp_overlap_average_r": float(bs.average_r),
               "exact_match_percent": float(match["exact_percent_of_exness"]),
               "exact_plus_near_match_percent": 100 * float(match["exact_plus_near_match_rate"])}
    write_summary(output_dir / "long_history_summary.md", summary,
                  years, periods, directions, excursions, pre, regimes, costs, segments)
    return summary


def write_summary(path: Path, summary: dict, years: pd.DataFrame,
                  periods: pd.DataFrame, directions: pd.DataFrame,
                  excursions: pd.DataFrame, pre: pd.DataFrame,
                  regimes: pd.DataFrame, costs: pd.DataFrame,
                  segments: pd.DataFrame) -> None:
    def table(frame: pd.DataFrame) -> str:
        cols = list(frame.columns)
        lines = ["| " + " | ".join(cols) + " |",
                 "| " + " | ".join("---" for _ in cols) + " |"]
        for row in frame.itertuples(index=False, name=None):
            lines.append("| " + " | ".join(
                f"{value:.4f}" if isinstance(value, float) else str(value)
                for value in row) + " |")
        return "\n".join(lines)
    lines = ["# Frozen Setup A long-history cross-feed robustness", "",
             "**FROZEN STRATEGY — NO OPTIMIZATION.** Setup A standalone, original Pine V2.2 rules, original pending order, structural stop, fixed 3R, both directions, zero-cost primary results. Phase 4K volatility gate is inactive.",
             "", "**BITSTAMP PRE-2023 HISTORY IS CROSS-FEED EVIDENCE, NOT EXNESS BROKER-NATIVE PERFORMANCE.** The hypothetical fixed-spread sensitivities are not historical Exness prices. Commission is zero in those sensitivities.",
             "", f"Source {summary['source_start']} to {summary['source_end']}; {summary['source_candles']:,} M15 candles; {summary['segments']} continuous segments, {summary['usable_segments']} usable and {summary['excluded_segments']} excluded after calculated warm-up. Every segment resets indicators, strategy state, pending orders, positions and account; no gap is filled.",
             "", "Year, period and pre-Exness membership use the completed signal candle's UTC year/time. Counts of signals and fills are attributed to that signal. Drawdown uses closed trades, starts from the audited account balance in each independent segment, and never compounds across gaps. Observed months count each UTC month containing usable candles once, including partial months.",
             "", "## Yearly zero-cost results", "", table(years),
             "", "## Period zero-cost results", "", table(periods),
             "", "## Direction results", "", table(directions),
             "", "## MFE and MAE after actual fill", "", table(excursions),
             "", "M15 OHLC excursion uses the established conservative intrabar convention; unknown entry/exit-bar extremes are censored, so reach rates can be understated.",
             "", "## Pre-Exness 2021-01-01 through 2023-11-08", "", table(pre),
             "", "## Signal-time regime descriptors, yearly medians", "", table(regimes),
             "", "Observed BTC price change uses the first and last available candle in each UTC year as market context; it is not a signal-time feature or a trading filter. Positive zero-cost Setup A years include large upward-price years (2021, 2023, 2024), a large downward-price year (2022), and smaller downward endpoint-change years (2025 and partial 2026). This does not prove performance in every intrayear regime.",
             "", "## Stability description", "",
             "Full-period zero-cost expectancy is positive, and every calendar year has positive zero-cost PnL. Both directions contribute over the full history. The weakest period is 2021–2022 and 2022 long average R is near zero; 2025 short is also weak. The two strongest calendar years, 2024 and partial 2026, contribute about 60% of summed segment PnL, so performance is uneven even though it does not depend on one year alone. The maximum observed losing streak is 19 completed losses within a segment (2022). These are descriptive cross-feed results, not broker-native proof or criteria chosen after the run.",
             "", "## Existing Exness exact-common-timestamp overlap", "",
             f"Exness PF {summary['exness_overlap_pf']:.4f}, average R {summary['exness_overlap_average_r']:.4f}; Bitstamp PF {summary['bitstamp_overlap_pf']:.4f}, average R {summary['bitstamp_overlap_average_r']:.4f}. Exact signal match {summary['exact_match_percent']:.2f}%; exact plus ±1 M15 near match {summary['exact_plus_near_match_percent']:.2f}%. The overlap comparison comes from unchanged Phase 4H artifacts, not the full Bitstamp run.",
             "", "## HYPOTHETICAL COST SENSITIVITY", "", table(costs),
             "", "## Source segments", "", table(segments), ""]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    print(json.dumps(build_long_history(), indent=2))
