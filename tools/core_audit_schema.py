"""Shared audit-record schema for the BTC Core MT5 digital twin.

Both sides of the twin emit this exact column set:

* Python  — tools/export_python_core_audit.py, driving the frozen strategy
  through the audited engine primitives.
* MT5     — mt5/BTC_V3_Core_V1.mq5 in AUDIT_ONLY mode.

Column names are stable and are the contract the comparator aligns on. Nothing
here executes strategy logic; it only names and orders fields.
"""
from __future__ import annotations

#: Alignment key: the M15 bar's OPEN time in UTC, ISO-8601 with a trailing Z.
KEY = "bar_time_utc"

#: Raw market data as each side saw it.
MARKET_COLUMNS = [
    "bar_time_utc", "symbol", "open", "high", "low", "close",
    "tick_volume", "spread_points", "spread_price",
]

#: The confirmed H1 context. Empty until the first complete four-bar hour.
H1_COLUMNS = [
    "h1_time_utc", "h1_open", "h1_high", "h1_low", "h1_close",
    "h1_ema50", "h1_ema200", "h1_ema200_past", "h1_atr",
    "h1_slope", "h1_slope_atr", "h1_separation_atr",
]

#: M15 indicator values after this bar's update.
INDICATOR_COLUMNS = [
    "ema20", "ema50", "atr", "rsi", "adx", "plus_di", "minus_di", "body_percent",
]

#: A4 long component.
A4_COLUMNS = [
    "a4_context_pass", "a4_signal_pass", "a4_reject_code",
    "a4_in_session", "a4_trades_today", "a4_material_below_ema50",
    "a4_pullback_active", "a4_pullback_low", "a4_pullback_depth_atr",
    "a4_pullback_bars", "a4_pullback_touch", "a4_structure_level",
    "a4_prior_high", "a4_trigger", "a4_stop", "a4_stop_atr",
]

#: T3 short component.
T3_COLUMNS = [
    "t3_regime", "t3_context_pass", "t3_signal_pass", "t3_reject_code",
    "t3_prev_high", "t3_prev_low", "t3_stop_high", "t3_stop_low",
    "t3_range_atr", "t3_extension_atr", "t3_trigger", "t3_stop", "t3_stop_atr",
]

#: Order lifecycle as simulated identically on both sides.
LIFECYCLE_COLUMNS = [
    "signal_side", "signal_setup_id", "signal_time_utc",
    "pending_status", "pending_trigger", "pending_stop", "pending_expiry_utc",
    "entry_time_utc", "entry_price", "entry_stop", "entry_target",
    "exit_time_utc", "exit_price", "exit_reason", "realized_r",
]

#: Broker cost fields. Deliberately carried as UNVERIFIED until a real demo
#: account statement supplies them; no rate is ever invented.
COST_COLUMNS = ["commission_status", "swap_status", "realized_cost_status"]

AUDIT_COLUMNS: list[str] = (
    MARKET_COLUMNS + H1_COLUMNS + INDICATOR_COLUMNS
    + A4_COLUMNS + T3_COLUMNS + LIFECYCLE_COLUMNS + COST_COLUMNS
)

#: Columns compared numerically, with the tolerance group each belongs to.
PRICE_COLUMNS = [
    "open", "high", "low", "close",
    "h1_open", "h1_high", "h1_low", "h1_close",
    "a4_pullback_low", "a4_structure_level", "a4_prior_high", "a4_trigger", "a4_stop",
    "t3_prev_high", "t3_prev_low", "t3_stop_high", "t3_stop_low",
    "t3_trigger", "t3_stop",
    "pending_trigger", "pending_stop",
    "entry_price", "entry_stop", "entry_target", "exit_price",
]
INDICATOR_NUMERIC_COLUMNS = [
    "ema20", "ema50", "atr", "rsi", "adx", "plus_di", "minus_di", "body_percent",
    "h1_ema50", "h1_ema200", "h1_ema200_past", "h1_atr",
    "h1_slope", "h1_slope_atr", "h1_separation_atr",
    "a4_pullback_depth_atr", "a4_stop_atr",
    "t3_range_atr", "t3_extension_atr", "t3_stop_atr",
    "realized_r",
]
BOOLEAN_COLUMNS = [
    "a4_context_pass", "a4_signal_pass", "a4_in_session", "a4_material_below_ema50",
    "a4_pullback_active", "t3_context_pass", "t3_signal_pass",
]
CATEGORICAL_COLUMNS = [
    "symbol", "a4_reject_code", "a4_pullback_touch", "t3_regime", "t3_reject_code",
    "signal_side", "signal_setup_id", "pending_status", "exit_reason",
    "commission_status", "swap_status", "realized_cost_status",
]
TIMESTAMP_COLUMNS = [
    "h1_time_utc", "signal_time_utc", "pending_expiry_utc",
    "entry_time_utc", "exit_time_utc",
]

#: Comparison tolerances. Deliberately tight: a loose tolerance would hide a
#: real parity failure, which is the one thing this twin exists to find.
#: BTCUSDm has 2 digits, so one point is 0.01.
#:
#: Raw market data must be bit-identical -- both sides read the same broker
#: bars, so any difference there is a data problem, not arithmetic.
EXACT_TOLERANCE = 1e-09
#: Indicators accumulate differently in float64 and double over thousands of
#: bars, so a relative allowance is legitimate. Anything larger is a real
#: porting defect.
INDICATOR_TOLERANCE = 1e-06
#: A derived price differing by at most one point is reported as
#: ROUNDING_MISMATCH rather than a structural divergence -- it is visible, and
#: it is never silently treated as a match.
ROUNDING_TOLERANCE = 0.01
PRICE_TOLERANCE = ROUNDING_TOLERANCE

UNVERIFIED = "UNVERIFIED"
