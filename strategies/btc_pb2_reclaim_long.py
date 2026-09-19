"""PB2 LONG research component — BTC_PB2_RECLAIM_LONG_V1.

Long-only reclaim/acceptance continuation. Requires H1 EMA50 > EMA200, an
upward displacement closing above the prior 12-bar structure high, a retest of
that high, a bullish reclaim, and one further bar of acceptance above it.

Independent of the SHORT component: separate descriptor, separate instance,
separate state, pending orders, diagnostics and experiment results. The shared
state machine lives in strategies/btc_pb2_reclaim_acceptance.py so neither side
duplicates indicator or geometry calculations.
"""
from __future__ import annotations

from engine.models import Direction
from strategies.btc_pb2_reclaim_acceptance import PB2Parameters, PB2ReclaimAcceptance

STRATEGY_ID = "BTC_PB2_RECLAIM_LONG_V1"
SETUP_ID = "PB2_RECLAIM_LONG"


class BtcPB2ReclaimLong(PB2ReclaimAcceptance):
    direction = Direction.LONG
    strategy_id = STRATEGY_ID
    setup_id = SETUP_ID


__all__ = ["BtcPB2ReclaimLong", "PB2Parameters", "STRATEGY_ID", "SETUP_ID"]
