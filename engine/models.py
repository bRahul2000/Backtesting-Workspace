from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class EntryModel(str, Enum):
    NEXT_OPEN = "NEXT_OPEN"
    STOP_ENTRY_PENDING = "STOP_ENTRY_PENDING"


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
    stop_loss: float | None = None
    take_profit: float | None = None
    entry_model: EntryModel = EntryModel.NEXT_OPEN
    pending_entry_price: float | None = None
    pending_stop_price: float | None = None
    pending_expiry_bars: int | None = None
    setup_id: str | None = None

    @classmethod
    def pending_stop(
        cls, direction: Direction, pending_entry_price: float,
        pending_stop_price: float, pending_expiry_bars: int,
        setup_id: str | None = None,
    ) -> Signal:
        """Create a stop entry signal without changing NEXT_OPEN defaults."""
        return cls(
            direction=direction, stop_loss=pending_stop_price,
            entry_model=EntryModel.STOP_ENTRY_PENDING,
            pending_entry_price=pending_entry_price,
            pending_stop_price=pending_stop_price,
            pending_expiry_bars=pending_expiry_bars, setup_id=setup_id,
        )


@dataclass(frozen=True)
class CancelPendingOrder:
    """Strategy action at candle close; cancellation applies to later bars."""
    reason: str
    setup_id: str | None = None


@dataclass(frozen=True)
class PendingOrder:
    direction: Direction
    signal_time: pd.Timestamp
    created_time: pd.Timestamp
    trigger_price: float
    stop_price: float
    expiry_time: pd.Timestamp
    created_bar_index: int
    expiry_bar_index: int
    quantity: float
    planned_risk: float
    estimated_stop_loss: float
    leverage_capped: bool
    setup_id: str | None = None


@dataclass(frozen=True)
class OrderEvent:
    signal_time: pd.Timestamp
    created_time: pd.Timestamp
    direction: Direction
    trigger_price: float
    stop_price: float
    expiry_time: pd.Timestamp
    expiry_bar_index: int
    status: str
    cancel_reason: str | None = None
    fill_time: pd.Timestamp | None = None
    fill_price: float | None = None
    setup_id: str | None = None


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
    entry_model: EntryModel = EntryModel.NEXT_OPEN
    pending_trigger_price: float | None = None
    pending_created_time: pd.Timestamp | None = None
    pending_expiry_time: pd.Timestamp | None = None
    pending_expiry_bar_index: int | None = None
    gap_through_trigger: bool = False
    entry_gap_amount: float = 0.0
    setup_id: str | None = None

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
    entry_model: EntryModel = EntryModel.NEXT_OPEN
    pending_trigger_price: float | None = None
    pending_created_time: pd.Timestamp | None = None
    pending_expiry_time: pd.Timestamp | None = None
    pending_expiry_bar_index: int | None = None
    gap_through_trigger: bool = False
    entry_gap_amount: float = 0.0
    setup_id: str | None = None
    mfe_price: float | None = None
    mfe_amount: float | None = None
    mfe_r: float | None = None
    mfe_percent: float | None = None
    mae_price: float | None = None
    mae_amount: float | None = None
    mae_r: float | None = None
    mae_percent: float | None = None
    mfe_timestamp: pd.Timestamp | None = None
    mae_timestamp: pd.Timestamp | None = None
    duration_minutes: float | None = None
    initial_stop_distance: float | None = None
    initial_stop_distance_atr: float | None = None
    highest_price_while_open: float | None = None
    lowest_price_while_open: float | None = None
    capture_efficiency: float | None = None
    adverse_efficiency: float | None = None
    excursion_model: str | None = None

    @property
    def planned_risk(self) -> float:
        return self.initial_risk

    @property
    def realized_r(self) -> float:
        return self.r_multiple

    @property
    def actual_fill_time(self) -> pd.Timestamp:
        return self.entry_time

    @property
    def actual_fill_price(self) -> float:
        return self.entry_price


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


@dataclass(frozen=True)
class ExecutionState:
    """Read-only state delivered to strategies after this candle's execution."""
    balance: float
    pending_order: PendingOrder | None
    position: Position | None
    opened_position: Position | None = None
    closed_trade: Trade | None = None


@dataclass
class BacktestResult:
    settings: BacktestSettings
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)
    issues: list[BacktestIssue] = field(default_factory=list)
    open_position: Position | None = None
    pending_order: PendingOrder | None = None
    order_events: list[OrderEvent] = field(default_factory=list)
    diagnostic_events: list[object] = field(default_factory=list)
    execution_ambiguities: list[object] = field(default_factory=list)

    @property
    def final_balance(self) -> float:
        return self.equity_curve[-1].balance
