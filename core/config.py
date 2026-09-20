from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

import pandas as pd


class DatasetRole(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"
    FORWARD_VALIDATION = "FORWARD_VALIDATION"
    HOLDOUT = "HOLDOUT"
    PAPER = "PAPER"
    LIVE = "LIVE"


class ExecutionMode(str, Enum):
    AUDITED_NATIVE = "AUDITED_NATIVE"
    SYNTHETIC_BID_ASK = "SYNTHETIC_BID_ASK"


@dataclass(frozen=True)
class BacktestConfig:
    instrument: str
    broker_profile: str
    strategy_id: str
    timeframe: str
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    dataset_role: DatasetRole
    higher_timeframes: tuple[str, ...] = ()
    initial_capital: float = 10_000.0
    risk_mode: str = "PERCENT_EQUITY"
    risk_per_trade_percent: float = 0.25
    fixed_risk_dollars: float = 100.0
    # Fixed-R exit horizon applied by the audited engine to strategy-defined
    # signals (engine/execution.py derives the target from the actual fill).
    # 3.0 is the V3 benchmark every existing run uses; it is configurable so an
    # exit-horizon experiment supplies it explicitly instead of a strategy
    # silently redefining its own target.
    risk_reward_ratio: float = 3.0
    spread: float = 10.0
    # CONSTANT keeps the historical calibrated single-spread assumption.
    # BROKER_NATIVE_PER_BAR uses the real per-bar spread carried by the
    # dataset, which is only meaningful for a broker-native export.
    spread_source: str = "CONSTANT"
    commission_percent: float = 0.0
    slippage_percent: float = 0.0
    leverage: float = 1.0
    max_trades_per_day: int = 3
    max_simultaneous_positions: int = 1
    session: str = "00:00-22:00 UTC"
    weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)
    weekends: bool = True
    execution_mode: ExecutionMode = ExecutionMode.SYNTHETIC_BID_ASK
    data_source: str = "canonical_btcusd_15m"
    strategy_parameters: Mapping[str, Any] = field(default_factory=dict)
    notes: str = ""

    def __post_init__(self) -> None:
        start, end = pd.Timestamp(self.start_date), pd.Timestamp(self.end_date)
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("BacktestConfig dates must be timezone-aware.")
        if start > end:
            raise ValueError("start_date must not exceed end_date.")
        if self.risk_per_trade_percent <= 0 or self.initial_capital <= 0:
            raise ValueError("Capital and risk must be positive.")
        if self.spread_source not in ("CONSTANT", "BROKER_NATIVE_PER_BAR"):
            raise ValueError("spread_source must be CONSTANT or BROKER_NATIVE_PER_BAR.")
        if self.risk_reward_ratio <= 0:
            raise ValueError("risk_reward_ratio must be positive.")
        if self.spread < 0 or self.commission_percent < 0 or self.slippage_percent < 0:
            raise ValueError("Costs cannot be negative.")
        if self.max_simultaneous_positions != 1:
            raise ValueError("Phase 1 audited adapter supports exactly one global position/pending order.")
