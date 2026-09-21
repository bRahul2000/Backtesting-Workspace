from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class DirectionStatistics:
    trades: int = 0
    win_rate: float = 0.0
    profit_factor: float | None = None
    average_r: float = 0.0
    pnl: float = 0.0


@dataclass
class UniversalBacktestResult:
    run_id: str
    strategy_fingerprint: str
    parameter_fingerprint: str
    dataset_fingerprint: str
    broker_fingerprint: str
    instrument: str
    period: dict[str, str]
    dataset_role: str
    total_trades: int
    trades_per_month: float
    win_rate: float
    profit_factor: float | None
    average_r: float
    pnl: float
    max_drawdown_percent: float
    drawdown_duration: Any = None
    max_losing_streak: int = 0
    total_entries: int = 0
    open_positions_at_end: list[dict[str, Any]] = field(default_factory=list)
    long_statistics: DirectionStatistics = field(default_factory=DirectionStatistics)
    short_statistics: DirectionStatistics = field(default_factory=DirectionStatistics)
    yearly_statistics: dict[str, Any] = field(default_factory=dict)
    monthly_statistics: dict[str, Any] = field(default_factory=dict)
    trade_log: list[dict[str, Any]] = field(default_factory=list)
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    mfe_mae: dict[str, Any] = field(default_factory=dict)
    execution_diagnostics: dict[str, Any] = field(default_factory=dict)
    signal_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    xray_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    #--- Diagnostic-only pre-setup funnel. Populated for instrumented strategies
    #--- (see strategies/btc_v3_core_diagnostics.py); empty for every other one.
    core_funnel: dict[str, Any] = field(default_factory=dict)
    execution_ambiguities: list[dict[str, Any]] = field(default_factory=list)
    excursion_model: str = "UNAVAILABLE"
    legacy_segment_results: list[Any] = field(default_factory=list, repr=False)
    instrument_fingerprint: str = ""

    def as_dict(self) -> dict[str, Any]:
        output = asdict(self)
        output.pop("legacy_segment_results", None)
        return output
