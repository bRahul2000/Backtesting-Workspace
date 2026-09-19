from math import isclose
from pathlib import Path

import pandas as pd

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
