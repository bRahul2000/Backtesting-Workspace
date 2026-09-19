"""PB2 SHORT research component — BTC_PB2_RECLAIM_SHORT_V1.

Short-only reclaim/acceptance continuation. The exact inverse of the LONG
component: requires H1 EMA50 < EMA200, a downward displacement closing below
the prior 12-bar structure low, a retest of that low, a bearish reclaim, and
one further bar of acceptance below it.

Independent of the LONG component: separate descriptor, separate instance,
separate state, pending orders, diagnostics and experiment results. The shared
state machine lives in strategies/btc_pb2_reclaim_acceptance.py so neither side
duplicates indicator or geometry calculations.
"""
from __future__ import annotations

from engine.models import Direction
from strategies.btc_pb2_reclaim_acceptance import PB2Parameters, PB2ReclaimAcceptance

STRATEGY_ID = "BTC_PB2_RECLAIM_SHORT_V1"
SETUP_ID = "PB2_RECLAIM_SHORT"


class BtcPB2ReclaimShort(PB2ReclaimAcceptance):
    direction = Direction.SHORT
    strategy_id = STRATEGY_ID
    setup_id = SETUP_ID


__all__ = ["BtcPB2ReclaimShort", "PB2Parameters", "STRATEGY_ID", "SETUP_ID"]
