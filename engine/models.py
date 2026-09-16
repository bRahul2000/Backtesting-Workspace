from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class RiskMode(str, Enum):
    PERCENT_EQUITY = "Percentage equity risk"
    FIXED_DOLLARS = "Fixed dollar risk"


class RiskCalculation(str, Enum):
    ESTIMATED_TOTAL_STOP_LOSS = "Estimated Total Stop Loss"
    PRICE_DISTANCE = "Price Distance Only"


class SameBarResolution(str, Enum):
    SL_FIRST = "SL First"
    TP_FIRST = "TP First"


@dataclass(frozen=True)
class BacktestSettings:
    starting_balance: float = 10_000.0
    risk_mode: RiskMode = RiskMode.PERCENT_EQUITY
    risk_percent: float = 1.0
    fixed_risk_dollars: float = 100.0
    risk_reward_ratio: float = 2.0
    commission_percent: float = 0.0
    slippage_percent: float = 0.0
    same_bar_resolution: SameBarResolution = SameBarResolution.SL_FIRST
    risk_calculation: RiskCalculation = RiskCalculation.ESTIMATED_TOTAL_STOP_LOSS
    max_leverage: float = 1.0
    min_quantity: float = 0.0


@dataclass(frozen=True)
class Candle:
    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Signal:
    direction: Direction
    stop_loss: float
    take_profit: float | None = None


@dataclass
class Position:
    trade_id: int
    direction: Direction
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float
    quantity: float
    initial_risk: float
    entry_commission: float
    entry_bar_index: int
    estimated_stop_loss: float = 0.0
    leverage_capped: bool = False

    @property
    def planned_risk(self) -> float:
        return self.initial_risk


@dataclass(frozen=True)
class Trade:
    trade_id: int
    direction: Direction
    signal_time: pd.Timestamp
    entry_time: pd.Timestamp
    entry_price: float
    stop_loss: float
    take_profit: float
    exit_time: pd.Timestamp
    exit_price: float
    exit_reason: str
    quantity: float
    initial_risk: float
    pnl: float
    pnl_percent: float
    r_multiple: float
    bars_held: int
    entry_commission: float
    exit_commission: float
    estimated_stop_loss: float = 0.0
    leverage_capped: bool = False

    @property
    def planned_risk(self) -> float:
        return self.initial_risk

    @property
    def realized_r(self) -> float:
        return self.r_multiple


@dataclass(frozen=True)
class EquityPoint:
    timestamp: pd.Timestamp | None
    trade_id: int | None
    balance: float
    peak_equity: float
    drawdown_dollars: float
    drawdown_percent: float


@dataclass(frozen=True)
class BacktestIssue:
    timestamp: pd.Timestamp | None
    message: str


@dataclass
class BacktestResult:
    settings: BacktestSettings
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    issues: list[BacktestIssue] = field(default_factory=list)
    open_position: Position | None = None

    @property
    def final_balance(self) -> float:
        return self.equity_curve[-1].balance
