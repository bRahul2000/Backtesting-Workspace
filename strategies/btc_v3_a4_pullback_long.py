"""BTC V3 A4 Pullback Long — Frozen.

Faithful permanent wrapper around the original V3-L2 implementation that
produced the validated A4 research results. The original V3-L2 H1 regime,
pullback state machine, structure logic, pending timing, stops, session logic,
and execution behavior remain unchanged.

Validated A4 deltas only:
- confirmation_min_body_percent = 0.70
- maximum_stop_atr = 3.00
- confirmation body cap <= 0.90
- normalized confirmed-H1 EMA200 slope / H1 ATR >= 0.15, applied only inside
  _context_valid(), never inside h1_bullish().
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass

from engine.models import Candle
import strategies.btc_v3_l2_trend_pullback_long as _l2
from strategies.confirmed_h1_regime import H1RegimeValue

STRATEGY_ID = "BTC_V3_A4_PULLBACK_LONG_FROZEN"
SETUP_ID = "BTC_V3_A4_PULLBACK_LONG_FROZEN"
STRATEGY_NAME = "V3 A4 Pullback Long — Frozen"

CONFIRMATION_MIN_BODY_PERCENT = 0.70
CONFIRMATION_MAX_BODY_PERCENT = 0.90
MINIMUM_NORMALIZED_H1_SLOPE = 0.15
MAXIMUM_STOP_ATR = 3.00

# Re-export the unchanged original helper/constant for diagnostics/tests.
MATERIAL_EMA50_CLOSE_ATR = _l2.MATERIAL_EMA50_CLOSE_ATR
h1_bullish = _l2.h1_bullish
body_percent = _l2.body_percent


@dataclass(frozen=True)
class V3A4FrozenParameters(_l2.V3L2Parameters):
    """Original V3-L2 defaults with only the validated A4 parameter overrides."""

    confirmation_min_body_percent: float = CONFIRMATION_MIN_BODY_PERCENT
    maximum_stop_atr: float = MAXIMUM_STOP_ATR


def frozen_parameters() -> V3A4FrozenParameters:
    return V3A4FrozenParameters()


_BASE_CONFIRMATION = _l2.confirmation_passes


def confirmation_passes(
    candle: Candle,
    previous_candle: Candle | None,
    ema20: float,
    rsi: float | None,
    params: _l2.V3L2Parameters,
) -> bool:
    """Exact validated A4 confirmation overlay on the original L2 predicate."""
    return (
        _BASE_CONFIRMATION(candle, previous_candle, ema20, rsi, params)
        and _l2.body_percent(candle) <= CONFIRMATION_MAX_BODY_PERCENT
    )


@contextmanager
def _validated_a4_call_context():
    """Apply the same module-level overlay used by the validated A4 research run."""
    old_confirmation = _l2.confirmation_passes
    old_setup_id = _l2.SETUP_ID
    _l2.confirmation_passes = confirmation_passes
    _l2.SETUP_ID = SETUP_ID
    try:
        yield
    finally:
        _l2.confirmation_passes = old_confirmation
        _l2.SETUP_ID = old_setup_id


class BtcV3A4PullbackLongFrozen(_l2.BtcV3L2TrendPullbackLong):
    """Exact validated A4 wrapper over the original V3-L2 strategy."""

    def __init__(self) -> None:
        # No caller-supplied params: the production frozen strategy cannot be
        # retuned through construction.
        super().__init__(frozen_parameters())

    def _context_valid(
        self,
        h1: H1RegimeValue,
        e20: float,
        e50: float,
        adx: float | None,
    ) -> bool:
        # Critical recovered behavior: this filter is layered only here.
        return (
            super()._context_valid(h1, e20, e50, adx)
            and h1.slope is not None
            and h1.atr is not None
            and h1.atr > 0
            and h1.slope / h1.atr >= MINIMUM_NORMALIZED_H1_SLOPE
        )

    def on_candle(self, candle: Candle):
        # Preserve the original V3-L2 on_candle implementation unchanged while
        # applying the validated confirmation overlay used by the research run.
        with _validated_a4_call_context():
            return super().on_candle(candle)
