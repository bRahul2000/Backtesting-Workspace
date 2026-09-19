from math import isclose
from pathlib import Path

import pandas as pd
import pytest

from core.adapters.audited_engine import run_universal_backtest
from core.config import BacktestConfig, DatasetRole

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "btcusd_15m.csv"


def _run(start, end, role, tmp_path):
    cfg = BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD",
        strategy_id="BTC_V3_CORE_V1_FROZEN", timeframe="15m", higher_timeframes=("1h",),
        start_date=pd.Timestamp(start, tz="UTC"), end_date=pd.Timestamp(end, tz="UTC"),
        dataset_role=role,
    )
    return run_universal_backtest(DATA, cfg, ledger_path=tmp_path / "ledger.sqlite3")


def test_universal_adapter_reproduces_core_development(tmp_path):
    r = _run("2021-01-01", "2024-12-31 23:45", DatasetRole.DEVELOPMENT, tmp_path)
    assert r.total_trades == 472
    assert isclose(r.profit_factor, 1.224225831450077, abs_tol=1e-12)
    assert isclose(r.average_r, 0.1566547327105722, abs_tol=1e-12)
    assert isclose(r.max_drawdown_percent, 3.2036378489188793, abs_tol=1e-12)
    # entries can exceed closed trades only by positions still open when their
    # continuous segment ended — never fabricated, always reconciled explicitly.
    assert r.total_entries == r.total_trades + len(r.open_positions_at_end)


def test_universal_adapter_reproduces_core_forward(tmp_path):
    r = _run("2025-01-01", "2026-09-17 01:30", DatasetRole.FORWARD_VALIDATION, tmp_path)
    assert r.total_trades == 223
    assert isclose(r.profit_factor, 1.1688791449202893, abs_tol=1e-12)
    assert isclose(r.average_r, 0.12097903854454335, abs_tol=1e-12)
    assert isclose(r.max_drawdown_percent, 3.7455941320390216, abs_tol=1e-12)
    assert r.total_entries == r.total_trades + len(r.open_positions_at_end)


def test_exit_horizon_is_configuration_not_a_strategy_default(tmp_path):
    """The audited fixed-R target reads BacktestConfig.risk_reward_ratio.

    The default stays at the 3.0 V3 benchmark, and a supplied ratio reaches the
    actual fills — so an exit-horizon experiment configures the engine instead
    of a strategy rewriting its own target.
    """
    assert BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id="X", timeframe="15m",
        start_date=pd.Timestamp("2021-01-01", tz="UTC"), end_date=pd.Timestamp("2021-02-01", tz="UTC"),
        dataset_role=DatasetRole.DEVELOPMENT,
    ).risk_reward_ratio == 3.0

    with pytest.raises(ValueError, match="risk_reward_ratio"):
        BacktestConfig(
            instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id="X", timeframe="15m",
            start_date=pd.Timestamp("2021-01-01", tz="UTC"), end_date=pd.Timestamp("2021-02-01", tz="UTC"),
            dataset_role=DatasetRole.DEVELOPMENT, risk_reward_ratio=0.0,
        )

    cfg = BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD",
        strategy_id="BTC_PB1_SHALLOW_PULLBACK_V1", timeframe="15m", higher_timeframes=("1h",),
        start_date=pd.Timestamp("2021-01-01", tz="UTC"),
        end_date=pd.Timestamp("2021-06-30 23:45", tz="UTC"),
        dataset_role=DatasetRole.DEVELOPMENT, risk_reward_ratio=1.5,
    )
    result = run_universal_backtest(DATA, cfg, ledger_path=tmp_path / "ledger.sqlite3")
    assert result.total_trades > 0
    for trade in result.trade_log:
        reward = abs(trade["take_profit"] - trade["entry_price"])
        risk = abs(trade["entry_price"] - trade["stop_loss"])
        assert isclose(reward, 1.5 * risk, rel_tol=1e-9)
