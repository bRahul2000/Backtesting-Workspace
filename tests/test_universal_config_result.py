import pandas as pd
import pytest

from core.config import BacktestConfig, DatasetRole
from core.result import DirectionStatistics, UniversalBacktestResult


def _config(**changes):
    values = dict(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD",
        strategy_id="BTC_V3_CORE_V1_FROZEN", timeframe="15m",
        start_date=pd.Timestamp("2021-01-01", tz="UTC"),
        end_date=pd.Timestamp("2021-01-31", tz="UTC"),
        dataset_role=DatasetRole.DEVELOPMENT,
    )
    values.update(changes)
    return BacktestConfig(**values)


def test_config_records_dataset_role_and_global_position_constraint():
    cfg = _config()
    assert cfg.dataset_role is DatasetRole.DEVELOPMENT
    assert cfg.max_simultaneous_positions == 1
    with pytest.raises(ValueError):
        _config(max_simultaneous_positions=2)


def test_result_has_universal_schema_fields():
    result = UniversalBacktestResult(
        run_id="BT-2026-000001", strategy_fingerprint="s", parameter_fingerprint="p",
        dataset_fingerprint="d", broker_fingerprint="b", instrument="BTCUSD",
        period={"start": "a", "end": "b"}, dataset_role="DEVELOPMENT",
        total_trades=1, trades_per_month=1.0, win_rate=100.0, profit_factor=2.0,
        average_r=1.0, pnl=10.0, max_drawdown_percent=0.0,
        long_statistics=DirectionStatistics(trades=1),
    )
    payload = result.as_dict()
    for key in ("run_id", "strategy_fingerprint", "parameter_fingerprint",
                "dataset_fingerprint", "broker_fingerprint", "yearly_statistics",
                "monthly_statistics", "trade_log", "equity_curve", "mfe_mae",
                "execution_diagnostics", "total_entries", "open_positions_at_end"):
        assert key in payload
