"""Research-only Exness cost and lot-size repricing of frozen Setup B trades.

No market data, strategy, signal, fill, stop, target, or execution rule is run.
Every scenario starts from the same completed frozen trade records.
"""
from __future__ import annotations

import hashlib
from decimal import Decimal, ROUND_FLOOR
from pathlib import Path

import numpy as np
import pandas as pd

from brokers.exness_standard_btcusdm import PROFILE


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reports/diagnostics/setup_b/trade_diagnostics.csv"
CALIBRATION = ROOT / "reports/broker/exness/multi_sample_summary.json"
OUTPUT = ROOT / "reports/broker/exness/cost_recalibration"
START_BALANCE = 10_000.0
SPREADS = (5.0, 10.0, 15.0, 20.0, 30.0)
IDENTITY = ("segment_id", "trade_id", "signal_time", "entry_time", "exit_time",
            "direction", "pending_trigger_price", "actual_fill_price", "exit_price",
            "structural_stop", "target", "exit_reason")


def floor_exness_lots(theoretical_btc: float) -> float:
    """One Exness BTCUSDm lot is one BTC; floor to its 0.01-lot step."""
    if not np.isfinite(theoretical_btc) or theoretical_btc < 0:
        raise ValueError("Theoretical BTC quantity must be finite and nonnegative.")
    step = Decimal(str(PROFILE.volume_step_lots))
    rounded = (Decimal(str(theoretical_btc)) / step).to_integral_value(rounding=ROUND_FLOOR) * step
    return float(rounded) if rounded >= Decimal(str(PROFILE.minimum_volume_lots)) else 0.0


def spread_round_trip_cost(quantity_btc: float, spread_usd_per_btc: float) -> float:
    """One full Bid/Ask spread per complete round trip, not one on each side."""
    if not np.isfinite(quantity_btc) or quantity_btc < 0 or not np.isfinite(spread_usd_per_btc) or spread_usd_per_btc < 0:
        raise ValueError("Quantity and spread must be finite and nonnegative.")
    return quantity_btc * spread_usd_per_btc


def research_set(signal_time: pd.Series) -> pd.Series:
    stamps = pd.to_datetime(signal_time, errors="raise")
    if not isinstance(stamps.dtype, pd.DatetimeTZDtype):
        raise ValueError("Frozen signal times must carry an explicit UTC offset.")
    stamps = stamps.dt.tz_convert("UTC")
    return pd.Series(np.where(stamps < pd.Timestamp("2025-01-01", tz="UTC"),
                              "development", "forward-validation"), index=signal_time.index)


def load_frozen_trades(path: Path = SOURCE) -> pd.DataFrame:
    data = pd.read_csv(path)
    required = set(IDENTITY) | {"setup_id", "quantity_recovered", "planned_risk_dollars",
                                "gross_price_movement_pnl", "commission_cost", "slippage_cost",
                                "net_pnl", "realized_r"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Frozen trade export lacks {sorted(missing)}")
    if data.empty or data.duplicated(["segment_id", "trade_id"]).any():
        raise ValueError("Frozen completed-trade identity is empty or duplicated.")
    if not data.setup_id.eq("BTC_V2_SETUP_B").all():
        raise ValueError("Frozen trade export contains another strategy.")
    if not data.direction.isin(("LONG", "SHORT")).all():
        raise ValueError("Unexpected frozen trade direction.")
    if (data.quantity_recovered <= 0).any() or (data.planned_risk_dollars <= 0).any():
        raise ValueError("Frozen quantity and planned risk must be positive.")
    if not np.allclose(data.gross_price_movement_pnl - data.commission_cost - data.slippage_cost,
                       data.net_pnl, rtol=1e-9, atol=1e-6):
        raise ValueError("Frozen trade gross-to-net audit failed.")
    expected_fee = (data.actual_fill_price + data.exit_price) * data.quantity_recovered * .0005
    if not np.allclose(data.commission_cost, expected_fee, rtol=1e-9, atol=1e-6):
        raise ValueError("Frozen trade fee does not match 0.05% per side.")
    if not np.allclose(data.slippage_cost, 0, atol=1e-9):
        raise ValueError("This comparison requires the frozen zero-slippage baseline.")
    data["signal_time"] = pd.to_datetime(data.signal_time, errors="raise")
    if not isinstance(data.signal_time.dtype, pd.DatetimeTZDtype):
        raise ValueError("Frozen signals require offset-aware timestamps.")
    data["signal_time"] = data.signal_time.dt.tz_convert("UTC")
    data["entry_time"] = pd.to_datetime(data.entry_time, utc=True)
    data["exit_time"] = pd.to_datetime(data.exit_time, utc=True)
    data["research_set"] = research_set(data.signal_time)
    data["calendar_year"] = data.signal_time.dt.year
    if not data.calendar_year.between(2021, 2026).all():
        raise ValueError("Unexpected source years in frozen baseline.")
    return data


def lot_rounding_analysis(trades: pd.DataFrame) -> pd.DataFrame:
    """Keep theoretical risk intent and structural price risk visible separately."""
    result = trades[list(IDENTITY) + ["research_set", "calendar_year",
                                      "quantity_recovered", "planned_risk_dollars",
                                      "gross_price_movement_pnl", "commission_cost", "net_pnl"]].copy()
    result.rename(columns={"quantity_recovered": "theoretical_btc_qty",
                           "planned_risk_dollars": "planned_risk_before_rounding"}, inplace=True)
    result["exness_btc_qty"] = result.theoretical_btc_qty.map(floor_exness_lots)
    result["volume_status"] = np.where(result.exness_btc_qty < PROFILE.minimum_volume_lots,
                                        "BELOW_MINIMUM_VOLUME", "EXECUTABLE")
    ratio = result.exness_btc_qty / result.theoretical_btc_qty
    result["planned_risk_after_rounding"] = result.planned_risk_before_rounding * ratio
    distance = abs(result.actual_fill_price - result.structural_stop)
    result["structural_risk_before_rounding"] = distance * result.theoretical_btc_qty
    result["structural_risk_after_rounding"] = distance * result.exness_btc_qty
    result["risk_reduction_percent"] = (1 - ratio) * 100
    return result


def reprice(trades: pd.DataFrame, *, spread: float | None = None,
            executable: bool = False, old_cost: bool = False) -> pd.DataFrame:
    """Change only costs and optionally quantity, retaining frozen trade identity."""
    if old_cost and spread is not None:
        raise ValueError("Old commission and Exness spread are separate scenarios.")
    result = trades[list(IDENTITY) + ["research_set", "calendar_year", "quantity_recovered",
                                      "planned_risk_dollars", "gross_price_movement_pnl",
                                      "commission_cost", "slippage_cost", "net_pnl"]].copy()
    theoretical = result.quantity_recovered
    result["exness_btc_qty"] = theoretical.map(floor_exness_lots)
    result["executable"] = result.exness_btc_qty >= PROFILE.minimum_volume_lots
    result["apply_volume_rules"] = executable
    result["quantity_used"] = result.exness_btc_qty if executable else theoretical
    ratio = result.quantity_used / theoretical
    result["gross_pre_cost_pnl"] = result.gross_price_movement_pnl * ratio
    result["planned_risk_used"] = result.planned_risk_dollars * ratio
    if old_cost:
        result["spread_cost"] = 0.0
        result["commission_cost_used"] = result.commission_cost * ratio
    else:
        result["spread_cost"] = spread_round_trip_cost(1, spread or 0) * result.quantity_used
        result["commission_cost_used"] = 0.0
    result["total_cost"] = result.spread_cost + result.commission_cost_used
    result["net_pnl_repriced"] = result.gross_pre_cost_pnl - result.total_cost
    result["realized_r_repriced"] = np.where(result.planned_risk_used > 0,
                                              result.net_pnl_repriced / result.planned_risk_used,
                                              np.nan)
    if old_cost and not executable and not np.allclose(result.net_pnl_repriced, result.net_pnl, atol=1e-6):
        raise ValueError("Old-cost reference does not reproduce frozen net PnL.")
    return result


def metrics(frame: pd.DataFrame) -> dict:
    data = (frame.loc[frame.executable] if not frame.empty and bool(frame.apply_volume_rules.iloc[0])
            else frame)
    n = len(data)
    pnl = data.net_pnl_repriced if n else pd.Series(dtype=float)
    profit = float(pnl.loc[pnl > 0].sum())
    loss = float(pnl.loc[pnl < 0].sum())
    return {"trades": len(frame), "executable_trades": n,
            "gross_pre_cost_pnl": float(data.gross_pre_cost_pnl.sum()),
            "spread_cost": float(data.spread_cost.sum()),
            "commission_cost": float(data.commission_cost_used.sum()),
            "total_cost": float(data.total_cost.sum()),
            "net_pnl": float(pnl.sum()),
            "profit_factor": profit / abs(loss) if loss else (float("inf") if profit else None),
            "average_r": float(data.realized_r_repriced.mean()) if n else None,
            "expectancy_r": float(data.realized_r_repriced.mean()) if n else None,
            "cost_per_trade": float(data.total_cost.mean()) if n else None,
            "cost_r_per_trade": float((data.total_cost / data.planned_risk_used).mean()) if n else None,
            "final_balance_arithmetic_reference": START_BALANCE + float(pnl.sum())}


def _rows_for_scope(data: pd.DataFrame):
    yield "all", data
    yield "development", data.loc[data.research_set == "development"]
    yield "forward-validation", data.loc[data.research_set == "forward-validation"]


def build_reports(source: Path = SOURCE, output_dir: Path = OUTPUT) -> dict:
    import json

    trades = load_frozen_trades(source)
    calibration = json.loads(CALIBRATION.read_text())
    observed = calibration["combined_spread"]
    if calibration["sample_count"] != 5 or not all(np.isclose(observed[key], 10)
                                                     for key in ("minimum", "median", "maximum")):
        raise ValueError("Five-sample $10/BTC calibration does not match saved real tick audit.")
    cost_rows = []
    sensitivity_rows = []
    scenario_frames: dict[tuple[str, str], pd.DataFrame] = {}
    for view, executable in (("cost_only", False), ("executable", True)):
        scenarios = [("old_0.05pct_per_side", None, True), ("zero_cost", 0.0, False)]
        scenarios += [(f"spread_${int(value)}", value, False) for value in SPREADS]
        for name, spread, old in scenarios:
            priced = reprice(trades, spread=spread, executable=executable, old_cost=old)
            scenario_frames[(view, name)] = priced
            for scope, subset in _rows_for_scope(priced):
                row = {"view": view, "scope": scope, "scenario": name,
                       "spread_usd_per_btc": spread, **metrics(subset)}
                cost_rows.append(row)
                if spread in SPREADS and not old:
                    sensitivity_rows.append(row)
    comparison = pd.DataFrame(cost_rows)
    sensitivity = pd.DataFrame(sensitivity_rows)
    rounding = lot_rounding_analysis(trades)
    year_rows = []
    direction_rows = []
    for view in ("cost_only", "executable"):
        priced = scenario_frames[(view, "spread_$10")]
        for year in range(2021, 2027):
            year_rows.append({"view": view, "year": year,
                              **metrics(priced.loc[priced.calendar_year == year])})
        for direction in ("LONG", "SHORT"):
            direction_rows.append({"view": view, "direction": direction,
                                   **metrics(priced.loc[priced.direction == direction])})
    output_dir.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(output_dir / "cost_model_comparison.csv", index=False)
    sensitivity.to_csv(output_dir / "spread_sensitivity.csv", index=False)
    rounding.to_csv(output_dir / "lot_rounding_analysis.csv", index=False)
    pd.DataFrame(year_rows).to_csv(output_dir / "yearly_results.csv", index=False)
    pd.DataFrame(direction_rows).to_csv(output_dir / "direction_results.csv", index=False)
    _write_summary(output_dir / "cost_recalibration_summary.md", comparison, rounding,
                   pd.DataFrame(year_rows), pd.DataFrame(direction_rows),
                   hashlib.sha256(source.read_bytes()).hexdigest())
    return {"comparison": comparison, "rounding": rounding,
            "yearly": pd.DataFrame(year_rows), "direction": pd.DataFrame(direction_rows)}


def _write_summary(path: Path, comparison: pd.DataFrame, rounding: pd.DataFrame,
                   yearly: pd.DataFrame, direction: pd.DataFrame, source_hash: str) -> None:
    def number(value) -> str:
        return "—" if pd.isna(value) else f"{value:.4f}"

    full = comparison.loc[comparison.scope == "all"]
    lines = ["# Exness Standard BTCUSDm cost recalibration — research only", "",
             "**COST-CALIBRATED RESEARCH — NOT A BROKER-NATIVE BACKTEST**", "",
             "This is NOT a broker-native Exness historical backtest. Signals and market movement remain from Bitstamp BTC/USD. Only trading-cost and lot-size assumptions are replaced with a calibrated Exness Standard approximation. A broker-native result requires longer Exness Bid/Ask history and chronological tick-level execution replay.",
             "", f"Frozen source: `trade_diagnostics.csv` SHA-256 `{source_hash}`; {len(rounding)} completed trades. No signals, pending orders, fills, stops, targets, or exits were regenerated.",
             "", "Exness Standard BTCUSDm: 1 lot = 1 BTC; minimum 0.01 lot; step 0.01 lot; commission $0. Five observed 24-hour samples had a $10/BTC spread. The $10 value is a **CALIBRATED FIXED-SPREAD APPROXIMATION**, not a claim about 2021–2026 spread history.",
             "", "One full spread is charged per complete round trip: `spread cost = spread USD/BTC × BTC quantity`. At 1 BTC and $10 spread, cost is about $10 total, not $10 on entry plus $10 on exit. This reprices completed trade PnL without changing fill prices or stop/target events.",
             "", "Cost-only keeps theoretical BTC quantity. Executable floors quantity to 0.01-lot steps, excludes results below 0.01 lot, and scales price PnL and planned risk by the quantity ratio. It does not replay balance-dependent future sizing or risk locks. `final_balance_arithmetic_reference` is $10,000 plus summed trade PnL, not a compounded cross-gap equity curve.",
             "", "## All-history comparison", "",
             "| View | Scenario | Trades | Executable | Gross pre-cost | Cost | Net PnL | PF | Average R | Cost/trade | Cost R/trade | Arithmetic balance |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in full.itertuples(index=False):
        lines.append(f"| {row.view} | {row.scenario} | {row.trades} | {row.executable_trades} | "
                     f"{row.gross_pre_cost_pnl:.2f} | {row.total_cost:.2f} | {row.net_pnl:.2f} | "
                     f"{number(row.profit_factor)} | {number(row.average_r)} | {number(row.cost_per_trade)} | "
                     f"{number(row.cost_r_per_trade)} | {row.final_balance_arithmetic_reference:.2f} |")
    lines += ["", "## Lot sizing", "",
              f"Below 0.01 lot: {(rounding.volume_status == 'BELOW_MINIMUM_VOLUME').sum()} trades. "
              f"Mean quantity: {rounding.theoretical_btc_qty.mean():.6f} BTC theoretical, "
              f"{rounding.exness_btc_qty.mean():.6f} BTC floored. "
              f"Mean planned risk: ${rounding.planned_risk_before_rounding.mean():.2f} before, "
              f"${rounding.planned_risk_after_rounding.mean():.2f} after. "
              f"Mean risk reduction: {rounding.risk_reduction_percent.mean():.2f}%.",
              "", "## Development and forward validation · $10 spread", "",
              "| View | Set | Trades | PF | Average R | Net PnL |",
              "|---|---|---:|---:|---:|---:|"]
    split = comparison.loc[(comparison.scenario == "spread_$10") &
                           (comparison.scope != "all")]
    for row in split.itertuples(index=False):
        lines.append(f"| {row.view} | {row.scope} | {row.executable_trades} | "
                     f"{number(row.profit_factor)} | {number(row.average_r)} | {row.net_pnl:.2f} |")
    lines += [
              "", "## Calibrated $10 by year", "",
              "| View | Year | Trades | PF | Average R | Net PnL |", "|---|---:|---:|---:|---:|---:|"]
    for row in yearly.itertuples(index=False):
        lines.append(f"| {row.view} | {row.year} | {row.executable_trades} | "
                     f"{number(row.profit_factor)} | {number(row.average_r)} | {row.net_pnl:.2f} |")
    lines += ["", "## Calibrated $10 by direction", "",
              "| View | Direction | Trades | PF | Average R | Net PnL |", "|---|---|---:|---:|---:|---:|"]
    for row in direction.itertuples(index=False):
        lines.append(f"| {row.view} | {row.direction} | {row.executable_trades} | "
                     f"{number(row.profit_factor)} | {number(row.average_r)} | {row.net_pnl:.2f} |")
    lines += ["", "The old-cost net PnL is negative, while the $10 calibrated cost-only and lot-rounded approximations are slightly positive. Thus the headline sign changes under this assumption, but the edge is thin: the $15 spread case is negative, 2021/2022/2025 remain losing years, and the lot-rounded 2025–2026 result is close to flat. No live-deployment conclusion follows.",
              "", "The 2025–2026 forward-validation set has been seen in prior research and is not a pristine holdout. No parameter or exit selection is made here.", ""]
    path.write_text("\n".join(lines))


def main() -> None:
    result = build_reports()
    print(result["comparison"].loc[result["comparison"].scope == "all",
                                   ["view", "scenario", "net_pnl", "profit_factor", "average_r"]].to_string(index=False))


if __name__ == "__main__":
    main()
