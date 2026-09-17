"""User-observed MT5 specification and research-only quote-side rules.

These are broker calibration facts supplied by the user, not a live contract
query. Unknown swap conversion, tick value, and historical spread are left
unfilled deliberately.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal


QuoteSide = Literal["bid", "ask"]
TradeSide = Literal["long", "short"]


@dataclass(frozen=True)
class ExnessStandardBTCUSDm:
    broker: str = "Exness"
    account_type: str = "Standard"
    mt5_symbol: str = "BTCUSDm"
    digits: int = 2
    btc_per_lot: float = 1.0
    volume_step_lots: float = 0.01
    maximum_volume_lots: float = 200.0
    spread_model: str = "Floating historical Bid/Ask ticks"
    stops_level_points: int = 0
    margin_currency: str = "BTC"
    profit_currency: str = "USD"
    execution: str = "Market"
    chart_quote_side: QuoteSide = "bid"
    trade_access: str = "Full access"
    displayed_sessions: str = "Sunday–Saturday, 00:00–24:00 (displayed MT5 specification)"
    commission_per_side_usd: float = 0.0
    swap_mode: str = "points"
    long_swap_points: float = -1609.2
    short_swap_points: float = 0.0
    friday_swap_multiplier: int = 3
    swap_usd_conversion: str = "PENDING VERIFICATION"


PROFILE = ExnessStandardBTCUSDm()


def historical_spread_price(*, bid: float, ask: float) -> float:
    """Read spread from a reconstructed historical quote; never assume a fixed value."""
    if not math.isfinite(bid) or not math.isfinite(ask) or bid <= 0 or ask < bid:
        raise ValueError("A valid historical Bid/Ask quote is required.")
    return ask - bid


def quote_side(direction: TradeSide, event: Literal["entry", "close", "pending_trigger", "stop_target"]) -> QuoteSide:
    """Research specification only; this does not change engine fills."""
    if direction not in ("long", "short"):
        raise ValueError("Direction must be long or short.")
    if event in ("entry", "pending_trigger"):
        return "ask" if direction == "long" else "bid"
    if event in ("close", "stop_target"):
        return "bid" if direction == "long" else "ask"
    raise ValueError("Unknown execution event.")


def research_quote_price(*, bid: float, ask: float, direction: TradeSide,
                         event: Literal["entry", "close", "pending_trigger", "stop_target"]) -> float:
    """Select the broker quote side without simulating an order or stop."""
    if bid <= 0 or ask < bid:
        raise ValueError("A valid Bid/Ask quote is required.")
    return ask if quote_side(direction, event) == "ask" else bid
