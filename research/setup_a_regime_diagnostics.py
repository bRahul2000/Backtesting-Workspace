"""Read-only signal-time and post-fill diagnostics for frozen Exness Setup A."""
from __future__ import annotations

import json
from collections import Counter, deque
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

from engine.backtester import run_backtest
from engine.models import Signal
from research.exness_native_validation import engine_frame, price_cost_view, summarize_trades
from research.exness_setup_a_validation import (PARAMS, REPORT as A_REPORT,
                                                SETTINGS, setup_a_warmup)
from research.setup_b_failure_diagnostics import THRESHOLDS, excursion
from services.exness_m15 import PROCESSED
from strategies.btc_v2_setup_a import BtcV2SetupA
from utils.data_validation import continuous_segments


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/setup_a/diagnostics"
STEP = pd.Timedelta(minutes=15)
PROFILE_FIELDS = (
    "atr", "atr_percent", "rsi", "directional_rsi_strength",
    "adx", "plus_di", "minus_di", "directional_di_advantage",
    "ema_separation_atr", "close_to_ema20_atr", "close_to_ema50_atr",
    "h1_directional_slope_percent", "h1_slope_percentile",
    "pullback_depth_atr", "pullback_distance_atr", "body_percent",
    "range_atr", "planned_stop_distance_atr", "entry_trigger_distance_atr",
    "atr_percentile", "recent_volatility_24h_percent",
    "directional_efficiency_24h", "range_chop_24h",
)
BUCKET_FIELDS = ("atr_percentile", "adx", "h1_slope_percentile",
                 "ema_separation_atr", "pullback_depth_atr",
                 "planned_stop_distance_atr")


def causal_percentile(history: deque[float], value: float) -> float:
    """Rank a present value against observations no later than this signal."""
    return sum(item <= value for item in history) / len(history) * 100 if history else float("nan")


class ObserveSetupA(BtcV2SetupA):
    """Observe frozen A decisions without altering the signal returned to engine."""

    def reset(self) -> None:
        super().reset()
        self.signal_descriptors: dict[pd.Timestamp, dict] = {}
        self._recent_candles = deque(maxlen=97)
        self._recent_tr = deque(maxlen=96)
        self._atr_pct_history = deque(maxlen=2880)  # trailing 30 calendar days
        self._slope_history = deque(maxlen=720)     # trailing 30 days of H1
        self._seen_h1_hour = None
        self._last_touch_type = None

    def on_candle(self, candle):
        previous_close = self._recent_candles[-1].close if self._recent_candles else None
        tr = (candle.high - candle.low if previous_close is None else
              max(candle.high - candle.low, abs(candle.high - previous_close),
                  abs(candle.low - previous_close)))
        prior_touch_age = (None if self._last_touch_index is None else
                           self._bar_index - self._last_touch_index)
        prior_touch_type = self._last_touch_type
        prior_five = list(self._recent_candles)[-5:]
        action = super().on_candle(candle)
        self._recent_candles.append(candle)
        self._recent_tr.append(tr)
        atr = self.atr._average.value
        atr_pct = atr / candle.close * 100 if atr is not None and atr > 0 else None
        if atr_pct is not None:
            self._atr_pct_history.append(atr_pct)
        h1 = self.h1.confirmed
        if h1.hour is not None and h1.hour != self._seen_h1_hour:
            self._seen_h1_hour = h1.hour
            if h1.slow_ema_lookback is not None:
                slope_pct = abs((h1.slow_ema - h1.slow_ema_lookback) / h1.slow_ema * 100)
                self._slope_history.append(slope_pct)
        touched_fast = candle.high >= self.fast.value >= candle.low
        touched_slow = candle.high >= self.slow.value >= candle.low
        self._last_touch_type = ("both" if touched_fast and touched_slow else
                                 "EMA20" if touched_fast else
                                 "EMA50" if touched_slow else self._last_touch_type)
        if not isinstance(action, Signal):
            return action
        if atr is None or atr <= 0 or h1.slow_ema_lookback is None:
            raise AssertionError("Frozen A signal lacks causal indicator history.")
        sign = 1 if action.direction.value == "LONG" else -1
        dmi_tr = self.dmi._tr.value
        plus_di = 100 * self.dmi._plus.value / dmi_tr if dmi_tr else 0.
        minus_di = 100 * self.dmi._minus.value / dmi_tr if dmi_tr else 0.
        slope = h1.slow_ema - h1.slow_ema_lookback
        slope_pct = sign * slope / h1.slow_ema * 100
        gain, loss = self.rsi._gain.value, self.rsi._loss.value
        rsi_value = (100 - 100 / (1 + gain / loss) if loss else
                     100. if gain else 50.)
        recent = list(self._recent_candles)
        closes = np.array([c.close for c in recent], dtype=float)
        returns = np.diff(closes) / closes[:-1]
        efficiency = (abs(closes[-1] - closes[0]) /
                      np.abs(np.diff(closes)).sum() if len(closes) >= 97 and
                      np.abs(np.diff(closes)).sum() > 0 else float("nan"))
        range_width = max(c.high for c in recent[-96:]) - min(c.low for c in recent[-96:])
        chop = (sum(self._recent_tr) / range_width if len(self._recent_tr) == 96
                and range_width > 0 else float("nan"))
        body_pct = (abs(candle.close - candle.open) / (candle.high - candle.low) * 100
                    if candle.high > candle.low else 0.)
        trigger = float(action.pending_entry_price)
        stop = float(action.pending_stop_price)
        self.signal_descriptors[candle.timestamp + STEP] = {
            "signal_candle_time": candle.timestamp,
            "signal_utc_hour": candle.timestamp.hour,
            "signal_utc_weekday": candle.timestamp.day_name(),
            "signal_utc_weekday_number": candle.timestamp.weekday(),
            "signal_year": candle.timestamp.year,
            "signal_month": candle.timestamp.strftime("%Y-%m"),
            "direction": action.direction.value,
            "signal_open": candle.open, "signal_high": candle.high,
            "signal_low": candle.low, "signal_close": candle.close,
            "ema20": self.fast.value, "ema50": self.slow.value,
            "ema20_minus_ema50": self.fast.value - self.slow.value,
            "ema_separation_atr": abs(self.fast.value - self.slow.value) / atr,
            "close_to_ema20_atr": abs(candle.close - self.fast.value) / atr,
            "close_to_ema50_atr": abs(candle.close - self.slow.value) / atr,
            "rsi": rsi_value,
            "directional_rsi_strength": sign * (rsi_value - 50),
            "adx": self.dmi._adx.value, "plus_di": plus_di, "minus_di": minus_di,
            "directional_di_advantage": sign * (plus_di - minus_di),
            "atr": atr, "atr_percent": atr_pct,
            "atr_percentile": causal_percentile(self._atr_pct_history, atr_pct),
            "confirmed_h1_hour": h1.hour, "confirmed_h1_close": h1.close,
            "h1_ema50": h1.fast_ema, "h1_ema200": h1.slow_ema,
            "h1_ema200_slope": slope,
            "h1_directional_slope_percent": slope_pct,
            "h1_slope_percentile": causal_percentile(self._slope_history, abs(slope_pct)),
            "bars_since_prior_ema_touch": prior_touch_age,
            "prior_ema_touch_type": prior_touch_type,
            "signal_touches_ema20": touched_fast,
            "signal_touches_ema50": touched_slow,
            "pullback_depth_atr": max(0., sign * (self.fast.value -
                (candle.low if sign == 1 else candle.high))) / atr,
            "pullback_distance_atr": abs((candle.low if sign == 1 else candle.high) -
                                         self.slow.value) / atr,
            "prior_five_high": max((c.high for c in prior_five), default=float("nan")),
            "prior_five_low": min((c.low for c in prior_five), default=float("nan")),
            "body_percent": body_pct,
            "close_location": (candle.close - candle.low) /
                (candle.high - candle.low) if candle.high > candle.low else float("nan"),
            "range_atr": (candle.high - candle.low) / atr,
            "planned_stop_distance_atr": abs(trigger - stop) / atr,
            "entry_trigger_distance_atr": abs(trigger - candle.close) / atr,
            "pending_trigger": trigger, "structural_stop": stop,
            "recent_volatility_24h_percent": float(np.std(returns[-96:], ddof=1) *
                sqrt(96) * 100) if len(returns) >= 96 else float("nan"),
            "directional_efficiency_24h": efficiency,
            "range_chop_24h": chop,
        }
        return action


def run_diagnostic_trades(data: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Rerun frozen A solely to attach current-signal indicators and after-fill path."""
    records, activity, segment_rows = [], [], []
    for index, segment in enumerate(continuous_segments(data), 1):
        segment_id = f"exness_native-S{index:02d}"
        minimum, first = setup_a_warmup(PARAMS, segment.start)
        if segment.candles < minimum:
            continue
        frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        strategy = ObserveSetupA(PARAMS)
        result = run_backtest(frame, strategy, SETTINGS, trade_start=first)
        statuses = Counter(e.status for e in result.order_events)
        segment_rows.append({"segment_id": segment_id, "start": segment.start,
                             "end": segment.end, "signals": len(strategy.signal_descriptors),
                             "orders": len(result.order_events), "fills": statuses["triggered"],
                             "completed_trades": len(result.trades)})
        activity.extend({"segment_id": segment_id, "signal_year": (stamp - STEP).year,
                         "kind": "signal", "status": ""}
                        for stamp in strategy.signal_descriptors)
        activity.extend({"segment_id": segment_id,
                         "signal_year": (event.signal_time - STEP).year,
                         "kind": "order", "status": event.status}
                        for event in result.order_events)
        for trade in result.trades:
            descriptor = strategy.signal_descriptors.get(trade.signal_time)
            if descriptor is None:
                raise AssertionError("Completed A trade lacks its signal-time observation.")
            held = frame.loc[frame.timestamp.between(trade.entry_time, trade.exit_time)]
            path = excursion(held, direction=trade.direction.value,
                             entry_price=trade.entry_price, exit_price=trade.exit_price,
                             stop_price=trade.stop_loss, quantity=trade.quantity,
                             gap_fill=trade.gap_through_trigger)
            if not segment.start <= trade.entry_time <= trade.exit_time <= segment.end:
                raise AssertionError("Trade or excursion crossed a source gap.")
            records.append({"segment_id": segment_id, "trade_id": trade.trade_id,
                            "signal_time": trade.signal_time, **descriptor,
                            "entry_time": trade.entry_time, "exit_time": trade.exit_time,
                            "entry_price": trade.entry_price, "exit_price": trade.exit_price,
                            "target": trade.take_profit, "quantity": trade.quantity,
                            "planned_risk": trade.initial_risk,
                            "gross_pnl": trade.pnl, "realized_r": trade.realized_r,
                            "bars_held": trade.bars_held, "exit_reason": trade.exit_reason,
                            "gap_fill": trade.gap_through_trigger, **path})
    return pd.DataFrame(records), pd.DataFrame(activity), pd.DataFrame(segment_rows)


def winner_loser_profile(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    scopes = [("All", trades), ("Long", trades.loc[trades.direction.eq("LONG")]),
              ("Short", trades.loc[trades.direction.eq("SHORT")])]
    for year in (2024, 2025, 2026):
        annual = trades.loc[trades.signal_year.eq(year)]
        scopes += [(f"{year} All", annual),
                   (f"{year} Long", annual.loc[annual.direction.eq("LONG")]),
                   (f"{year} Short", annual.loc[annual.direction.eq("SHORT")])]
    for scope, group in scopes:
        for outcome, population in (("Winner", group.loc[group.gross_pnl.gt(0)]),
                                    ("Loser", group.loc[group.gross_pnl.lt(0)])):
            for field in PROFILE_FIELDS:
                values = population[field].dropna()
                rows.append({"scope": scope, "outcome": outcome, "descriptor": field,
                             "count": len(values), "mean": values.mean(),
                             "median": values.median(), "p25": values.quantile(.25),
                             "p75": values.quantile(.75)})
    return pd.DataFrame(rows)


def failure_comparison(trades: pd.DataFrame) -> pd.DataFrame:
    """2025 losing trades versus all 2024+2026 trades; descriptive only."""
    bad = trades.loc[trades.signal_year.eq(2025) & trades.gross_pnl.lt(0)]
    reference = trades.loc[trades.signal_year.isin([2024, 2026])]
    rows = []
    for field in PROFILE_FIELDS:
        left, right = bad[field].dropna(), reference[field].dropna()
        iqr = right.quantile(.75) - right.quantile(.25)
        effect = abs(left.median() - right.median()) / iqr if iqr > 0 else 0.
        rows.append({"descriptor": field, "losing_2025_count": len(left),
                     "losing_2025_median": left.median(),
                     "losing_2025_p25": left.quantile(.25),
                     "losing_2025_p75": left.quantile(.75),
                     "other_years_count": len(right),
                     "other_years_median": right.median(),
                     "other_years_p25": right.quantile(.25),
                     "other_years_p75": right.quantile(.75),
                     "median_shift_over_reference_iqr": effect,
                     "adequate_sample": len(left) >= 50 and len(right) >= 100})
    return pd.DataFrame(rows).sort_values("median_shift_over_reference_iqr", ascending=False)


def mfe_mae_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in ("All", 2023, 2024, 2025, 2026):
        annual = trades if year == "All" else trades.loc[trades.signal_year.eq(year)]
        for side in ("All", "LONG", "SHORT"):
            group = annual if side == "All" else annual.loc[annual.direction.eq(side)]
            losers = group.loc[group.gross_pnl.lt(0)]
            row = {"year": year, "direction": side, "trades": len(group),
                   "losing_trades": len(losers),
                   "median_mfe_r": group.mfe_r.median(),
                   "median_mae_r": group.mae_r.median(),
                   "mean_mfe_r": group.mfe_r.mean(), "mean_mae_r": group.mae_r.mean(),
                   "median_bars_to_mfe": group.bars_to_mfe.median(),
                   "median_bars_to_mae": group.bars_to_mae.median(),
                   "never_reached_0.5r_percent": (100 * (~group["reached_0.5r"]).mean()
                                                  if len(group) else 0.)}
            for threshold in THRESHOLDS:
                field = f"reached_{threshold:g}r"
                row[f"{field}_percent"] = group[field].mean() * 100 if len(group) else 0.
                if threshold in (.5, 1., 1.5, 2.):
                    row[f"losers_{field}_percent"] = (losers[field].mean() * 100
                                                       if len(losers) else 0.)
            rows.append(row)
    return pd.DataFrame(rows)


def year_comparison(trades: pd.DataFrame, activity: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in (2023, 2024, 2025, 2026):
        annual = trades.loc[trades.signal_year.eq(year)]
        actions = activity.loc[activity.signal_year.eq(year)]
        orders = actions.loc[actions.kind.eq("order")]
        fills = int(orders.status.eq("triggered").sum())
        stats = summarize_trades(annual, net_column="gross_pnl", r_column="realized_r")
        losing = annual.loc[annual.gross_pnl.lt(0)]
        rows.append({"year": year, "partial_year": year in (2023, 2026),
                     "signals": int(actions.kind.eq("signal").sum()),
                     "pending_orders": len(orders), "fills": fills,
                     "fill_rate_percent": fills / len(orders) * 100 if len(orders) else 0.,
                     "completed_trades": len(annual),
                     "median_stop_distance_atr": annual.planned_stop_distance_atr.median(),
                     "median_mfe_r": annual.mfe_r.median(),
                     "median_mae_r": annual.mae_r.median(),
                     "median_atr_percent": annual.atr_percent.median(),
                     "median_adx": annual.adx.median(),
                     "median_h1_slope_percent": annual.h1_directional_slope_percent.median(),
                     "median_recent_volatility_24h_percent": annual.recent_volatility_24h_percent.median(),
                     "median_directional_efficiency_24h": annual.directional_efficiency_24h.median(),
                     "never_reached_0.5r_percent": (~annual["reached_0.5r"]).mean() * 100,
                     "losers_reached_1r_percent": (losing["reached_1r"].mean() * 100
                                                  if len(losing) else 0.), **stats})
    return pd.DataFrame(rows)


def time_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for scope, population in [("All", trades)] + [
        (str(year), trades.loc[trades.signal_year.eq(year)]) for year in (2024, 2025, 2026)]:
        for dimension, field in (("UTC hour", "signal_utc_hour"),
                                 ("UTC weekday", "signal_utc_weekday"),
                                 ("UTC calendar month", "signal_month")):
            for key, group in population.groupby(field):
                rows.append({"scope": scope, "dimension": dimension, "value": key,
                             **summarize_trades(group, net_column="gross_pnl",
                                                r_column="realized_r"),
                             "low_sample": len(group) < 20})
    return pd.DataFrame(rows)


def direction_by_year(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for year in (2023, 2024, 2025, 2026):
        for direction in ("LONG", "SHORT"):
            group = trades.loc[trades.signal_year.eq(year) & trades.direction.eq(direction)]
            rows.append({"year": year, "direction": direction,
                         **summarize_trades(group, net_column="gross_pnl",
                                            r_column="realized_r")})
    return pd.DataFrame(rows)


def cost_by_year(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for spread in (0., 10., 15., 20., 30.):
        priced = price_cost_view(trades, fixed_spread=spread)
        for year in (2023, 2024, 2025, 2026):
            group = priced.loc[priced.signal_year.eq(year)]
            rows.append({"year": year, "spread_usd_per_btc": spread,
                         **summarize_trades(group, net_column="net_pnl",
                                            r_column="realized_r_costed")})
    return pd.DataFrame(rows)


def feed_sensitivity_by_year(matches: pd.DataFrame) -> pd.DataFrame:
    data = matches.copy()
    data["exness_signal_time"] = pd.to_datetime(data.exness_signal_time, utc=True)
    data["bitstamp_signal_time"] = pd.to_datetime(data.bitstamp_signal_time, utc=True)
    rows = []
    for year in (2023, 2024, 2025, 2026):
        ex = data.loc[data.exness_signal_time.dt.year.eq(year)]
        bs = data.loc[data.bitstamp_signal_time.dt.year.eq(year)]
        exact = int(ex.classification.eq("EXACT MATCH").sum())
        near = int(ex.classification.eq("NEAR MATCH").sum())
        rows.append({"year": year, "exness_signals": len(ex),
                     "bitstamp_signals": len(bs), "exact_matches": exact,
                     "near_matches": near,
                     "exness_only": int(ex.classification.eq("EXNESS ONLY").sum()),
                     "bitstamp_only": int(bs.classification.eq("BITSTAMP ONLY").sum()),
                     "opposite": int(ex.classification.eq("OPPOSITE").sum()),
                     "exact_match_rate_percent": exact / len(ex) * 100 if len(ex) else 0.,
                     "exact_plus_near_rate_percent": (exact + near) / len(ex) * 100
                     if len(ex) else 0.})
    return pd.DataFrame(rows)


def assign_regime_bucket(series: pd.Series, descriptor: str) -> pd.Series:
    if descriptor == "adx":
        return pd.cut(series, bins=[18, 20, 25, 30, 40, float("inf")],
                      labels=["18–20", "20–25", "25–30", "30–40", "40+"],
                      right=False, include_lowest=True).astype(str)
    if descriptor == "planned_stop_distance_atr":
        return pd.cut(series, bins=[.6, 1, 1.5, 2, 2.5, 3.000001],
                      labels=["0.6–1", "1–1.5", "1.5–2", "2–2.5", "2.5–3"],
                      right=False, include_lowest=True).astype(str)
    valid = series.dropna()
    if valid.nunique() < 2:
        return pd.Series("one observed value", index=series.index)
    return pd.qcut(series, q=4, duplicates="drop").astype(str)


def regime_buckets(trades: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for descriptor in BUCKET_FIELDS:
        bucket = assign_regime_bucket(trades[descriptor], descriptor)
        for scope, scoped in [("All", trades)] + [
            (str(year), trades.loc[trades.signal_year.eq(year)])
            for year in (2024, 2025, 2026)]:
            for label, group in scoped.groupby(bucket.loc[scoped.index]):
                if label == "nan":
                    continue
                rows.append({"scope": scope, "descriptor": descriptor,
                             "bucket": label,
                             **summarize_trades(group, net_column="gross_pnl",
                                                r_column="realized_r"),
                             "low_sample": len(group) < 20})
    return pd.DataFrame(rows)


def build_diagnostics(data_path: Path = PROCESSED, output_dir: Path = REPORT) -> dict:
    bars = pd.read_csv(data_path, parse_dates=["timestamp_utc"])
    data = engine_frame(bars, exness=True)
    trades, activity, segments = run_diagnostic_trades(data)
    saved = pd.read_csv(A_REPORT / "native_results.csv")
    for view, spread in (("zero_cost", 0.), ("fixed_spread_$10", 10.)):
        expected = saved.loc[(saved.feed == "exness_native") &
                             (saved.scope == "full_native") &
                             (saved.cost_view == view)].iloc[0]
        priced = price_cost_view(trades, fixed_spread=spread)
        actual = summarize_trades(priced, net_column="net_pnl",
                                  r_column="realized_r_costed")
        if (actual["trades"] != int(expected.trades) or
            abs(actual["profit_factor"] - float(expected.profit_factor)) > 1e-10 or
            abs(actual["average_r"] - float(expected.average_r)) > 1e-10 or
            abs(actual["net_pnl"] - float(expected.net_pnl)) > 1e-7):
            raise AssertionError(f"Frozen Setup A baseline changed for {view}.")
    profile = winner_loser_profile(trades)
    failure = failure_comparison(trades)
    years = year_comparison(trades, activity)
    excursions = mfe_mae_analysis(trades)
    times = time_analysis(trades)
    direction = direction_by_year(trades)
    costs = cost_by_year(trades)
    matches = pd.read_csv(A_REPORT / "feed_signal_comparison.csv")
    feeds = feed_sensitivity_by_year(matches)
    buckets = regime_buckets(trades)
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in (
        ("trade_diagnostics.csv", trades),
        ("winner_loser_profile.csv", profile),
        ("year_comparison.csv", years),
        ("mfe_mae.csv", excursions),
        ("time_analysis.csv", times),
        ("direction_by_year.csv", direction),
        ("cost_by_year.csv", costs),
        ("feed_sensitivity_by_year.csv", feeds),
        ("regime_buckets.csv", buckets),
        ("failure_comparison.csv", failure),
        ("segment_activity.csv", segments),
    ):
        frame.to_csv(output_dir / name, index=False)
    normalized = failure.loc[
        failure.adequate_sample &
        ~failure.descriptor.isin(("atr", "rsi", "plus_di", "minus_di")) &
        failure.median_shift_over_reference_iqr.ge(.20)]
    top = normalized.head(5).to_dict("records")
    baseline = saved.loc[(saved.feed == "exness_native") &
                         (saved.scope == "full_native") &
                         (saved.cost_view == "zero_cost")].iloc[0]
    summary = {
        "baseline": {"trades": int(baseline.trades),
                     "profit_factor": float(baseline.profit_factor),
                     "average_r": float(baseline.average_r),
                     "net_pnl": float(baseline.net_pnl),
                     "worst_segment_dd_percent": float(baseline.worst_segment_dd_percent)},
        "2025_failure": top,
        "excursion_convention": "Conservative M15 OHLC path after actual fill; unknown intrabar sequence is excluded.",
        "regime_bucket_rule": "Descriptive fixed ADX/stop bins and full-sample quartiles; sample <20 flagged. No bucket is applied to trading.",
    }
    (output_dir / "diagnostic_summary.json").write_text(
        json.dumps(summary, indent=2, default=str, allow_nan=False) + "\n")
    _write_summary(output_dir / "diagnostic_summary.md", summary, years,
                   excursions, direction, costs, feeds, failure)
    return summary


def _write_summary(path: Path, summary: dict, years: pd.DataFrame,
                   excursions: pd.DataFrame, direction: pd.DataFrame,
                   costs: pd.DataFrame, feeds: pd.DataFrame,
                   failure: pd.DataFrame) -> None:
    def table(frame: pd.DataFrame) -> str:
        cols = list(frame.columns)
        lines = ["| " + " | ".join(cols) + " |",
                 "| " + " | ".join("---" for _ in cols) + " |"]
        for values in frame.itertuples(index=False, name=None):
            lines.append("| " + " | ".join(
                f"{v:.3f}" if isinstance(v, float) else str(v) for v in values) + " |")
        return "\n".join(lines)
    base = summary["baseline"]
    year_cols = ["year", "signals", "pending_orders", "fills",
                 "completed_trades", "fill_rate_percent", "win_rate_percent",
                 "profit_factor", "average_r", "median_stop_distance_atr",
                 "median_mfe_r", "median_mae_r", "median_atr_percent",
                 "median_adx", "median_h1_slope_percent",
                 "median_recent_volatility_24h_percent",
                 "median_directional_efficiency_24h",
                 "never_reached_0.5r_percent", "losers_reached_1r_percent"]
    mfe_cols = ["year", "direction", "trades", "median_mfe_r", "median_mae_r",
                "never_reached_0.5r_percent", "losers_reached_0.5r_percent",
                "losers_reached_1r_percent", "losers_reached_1.5r_percent",
                "losers_reached_2r_percent"]
    lines = ["# Frozen Setup A regime and failure diagnostics", "",
             "**DIAGNOSTIC ONLY — NO OPTIMIZATION.** Real Exness BTCUSDm Bid M15, original V2.2 Setup A standalone. Every source gap resets indicators and the account; no OHLC is filled. The saved zero-cost and $10 baselines were verified exactly before analysis.",
             "", f"Zero-cost baseline: {base['trades']} trades; PF {base['profit_factor']:.4f}; average R {base['average_r']:.4f}; net ${base['net_pnl']:,.2f}; worst segment DD {base['worst_segment_dd_percent']:.2f}%.",
             "", "Signal descriptors use only the completed signal candle and earlier observations. ATR and H1 slope percentiles use trailing histories, including the signal's current known observation. Twenty-four-hour volatility, efficiency and chop use completed M15 history only. These variables never change entry decisions.",
             "", "MFE/MAE begin after fill. With unknown M15 intrabar order, entry and exit bar extremes are conservatively censored; recorded reach rates can understate the true path. No exit is changed.",
             "", "## Entry quality by year", "", table(years[year_cols]),
             "", "## Excursions and losing-trade reversals", "",
             table(excursions.loc[excursions.direction.eq("All"), mfe_cols]),
             "", "## Long and short by year", "",
             table(direction[["year", "direction", "trades", "win_rate_percent",
                              "profit_factor", "average_r", "net_pnl"]]),
             "", "## Cost resilience by year", "",
             table(costs[["year", "spread_usd_per_btc", "trades",
                          "profit_factor", "average_r", "net_pnl"]]),
             "", "Fixed spreads are sensitivities on identical completed trades. They are not tick-exact historical execution costs.",
             "", "## Signal feed sensitivity by year", "", table(feeds),
             "", "## Visible 2025 losing-trade descriptor differences", "",
             "Comparator: all 2024+2026 completed trades. Median shift is scaled by comparator IQR; these are descriptive associations, not causes or filter proposals.",
             "", table(failure.loc[failure.descriptor.isin(
                 [r["descriptor"] for r in summary["2025_failure"]]),
                 ["descriptor", "losing_2025_count", "losing_2025_median",
                  "other_years_count", "other_years_median",
                  "median_shift_over_reference_iqr"]]),
             "", "Profiles, time groups, buckets and every trade are in the accompanying CSV files. Low-sample groups (<20 trades) are flagged. No clustering was added because it would not improve this causal diagnostic audit.", ""]
    path.write_text("\n".join(lines))


if __name__ == "__main__":
    print(json.dumps(build_diagnostics(), indent=2, default=str)[:3000])
