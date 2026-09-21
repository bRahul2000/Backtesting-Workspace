"""Diagnostic-only pre-setup funnel and X-Ray for the frozen BTC V3 Core v1.

This module **observes** the frozen strategy. It never influences it:

* It wraps ``BtcV3CoreV1Frozen`` and forwards every call unchanged, returning
  the frozen strategy's own action byte-for-byte.
* Every pass/fail decision is taken by calling the frozen strategy's own *pure*
  predicates (``h1_bullish``, ``_context_valid``, ``_materially_below_ema50``,
  the A4 ``confirmation_passes`` overlay, ``classify_regime``, ``evaluate_v3``).
  Those functions read their arguments and mutate nothing, so calling them a
  second time cannot change a decision. The hand-written decomposition below is
  used only to *name* which source condition failed, never to decide.
* Indicator inputs come from a shadow indicator set fed the same candles in the
  same order. A4/T3 recompute RSI and DMI per bar and discard them, so they
  cannot be read back off the strategy; re-running ``update`` on the strategy's
  own instances would corrupt them.
* Every bar the observer cross-checks its own verdict against the action the
  frozen Core actually returned, and counts any disagreement in
  ``integrity``. A non-zero count means this instrumentation has drifted from
  the source and the funnel must not be trusted.

Counts are aggregated, never per-bar events: the result payload is persisted
into the experiment ledger, and 100k bars x ~18 gates of individual events
would be written into sqlite on every run.
"""
from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from engine.diagnostics import XRayEvaluation
from engine.models import Candle, ExecutionState, PendingOrder, Signal
from strategies.base import Strategy
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen, STRATEGY_ID as CORE_STRATEGY_ID
from strategies.btc_v3_a4_pullback_long import (
    SETUP_ID as A4_SETUP_ID,
    body_percent as a4_body_percent,
    confirmation_passes as a4_confirmation_passes,
    h1_bullish,
)
from strategies.btc_v3_t3_breakout_short import (
    TREND_SETUP_ID as T3_SETUP_ID,
    MarketRegime,
    V3Observation,
    _body_percent as t3_body_percent,
    _pending as t3_pending,
    classify_regime,
    evaluate_v3,
)
from strategies.confirmed_h1_regime import ConfirmedH1Regime
from strategies.pine_indicators import ATR, DMI, EMA, RSI

from engine.models import Direction


DEFAULT_XRAY_LIMIT = 20_000


@dataclass(frozen=True)
class Gate:
    """One sequential gate, in the order the frozen source evaluates it."""
    key: str
    label: str
    source: str


#--- A4: strategies/btc_v3_l2_trend_pullback_long.py::on_candle, with the A4
#--- overlays from strategies/btc_v3_a4_pullback_long.py.
A4_GATES: tuple[Gate, ...] = (
    Gate("bars_evaluated", "Bars evaluated", "on_candle entered"),
    Gate("warmup_window", "Warmup / backtest window", "candle.timestamp within [window_start, window_end]"),
    Gate("no_pending_order", "No pending order", "state.pending_order is None"),
    Gate("no_open_position", "No open position", "state.position is None"),
    Gate("in_session", "UTC session open", "session_start <= t < session_end"),
    Gate("daily_cap", "Daily trade cap", "trades_today < max_trades_per_day"),
    Gate("indicators_ready", "Indicators seeded", "atr > 0 and rsi is not None and adx is not None"),
    Gate("h1_regime_bullish", "Confirmed H1 bullish", "h1_bullish(h1, params)"),
    Gate("m15_ema_stack", "M15 EMA20 > EMA50", "ema20 > ema50"),
    Gate("adx_minimum", "ADX >= min_adx", "adx >= params.min_adx"),
    Gate("normalized_h1_slope", "Normalized H1 slope", "h1.slope / h1.atr >= MINIMUM_NORMALIZED_H1_SLOPE"),
    Gate("ema50_proximity", "Close not far below EMA50", "not _materially_below_ema50(...)"),
    Gate("pullback_depth_ok", "Pullback depth within limit", "not (pullback_active and depth > max_pullback_depth_below_ema20_atr)"),
    Gate("pullback_confirmable", "Armed pullback to confirm", "pullback_active and timestamp > pullback_start_time"),
    Gate("confirmation_candle", "Confirmation candle", "confirmation_passes(...) and body <= CONFIRMATION_MAX_BODY_PERCENT"),
    Gate("stop_distance_valid", "Stop distance in band", "minimum_stop_atr <= (trigger - stop)/atr <= maximum_stop_atr"),
    Gate("setup_detected", "Setup detected / order created", "Signal.pending_stop(LONG, ...)"),
)

#--- T3: strategies/btc_v3_t3_breakout_short.py::on_candle + evaluate_v3.
T3_GATES: tuple[Gate, ...] = (
    Gate("bars_evaluated", "Bars evaluated", "on_candle entered"),
    Gate("warmup_window", "Warmup / backtest window", "candle.timestamp within [window_start, window_end]"),
    Gate("in_session", "UTC session open", "session_start <= t < session_end"),
    Gate("daily_cap", "Daily trade cap", "trades_today < max_trades_per_day"),
    Gate("no_open_position", "No open position", "state.position is None"),
    Gate("no_pending_order", "No pending order", "state.pending_order is None"),
    Gate("indicators_ready", "Indicators seeded", "atr > 0 and rsi is not None"),
    Gate("h1_regime_confirmed", "H1 regime inputs present", "separation_atr, slope and adx are not None"),
    Gate("h1_separation", "H1 separation >= min", "sep >= trend_min_h1_separation_atr"),
    Gate("adx_minimum", "ADX >= min", "adx >= trend_min_adx"),
    Gate("bearish_alignment", "TREND SHORT alignment", "h1.fast < h1.slow and slope < 0 and ema20 < ema50"),
    Gate("shorts_enabled", "Shorts enabled", "params.shorts_enabled"),
    Gate("structure_breakdown", "Break of 5-bar low", "close < trend_previous_low"),
    Gate("candle_bearish", "Bearish candle", "close < open"),
    Gate("body_minimum", "Body >= min", "body >= trend_minimum_body_percent"),
    Gate("range_band", "Candle range in ATR band", "trend_minimum_range_atr <= (high-low)/atr <= trend_maximum_range_atr"),
    Gate("rsi_band", "RSI in short band", "trend_short_rsi_min <= rsi <= trend_short_rsi_max"),
    Gate("extension_limit", "Extension from EMA20", "abs(close - ema20)/atr <= trend_maximum_extension_atr"),
    Gate("stop_distance_valid", "Stop distance in band", "minimum_stop_atr <= (stop - trigger)/atr <= maximum_stop_atr"),
    Gate("setup_detected", "Setup detected / order created", "Signal.pending_stop(SHORT, ...)"),
)

GATES: dict[str, tuple[Gate, ...]] = {"A4": A4_GATES, "T3": T3_GATES}
SETUP_IDS: dict[str, str] = {"A4": A4_SETUP_ID, "T3": T3_SETUP_ID}
CHILD_NAMES: dict[str, str] = {"A4": "A4 Pullback Long", "T3": "T3 Breakout Short"}


@dataclass
class ChildFunnel:
    """Sequential gate counts and reject codes for one frozen child."""
    child: str
    entered: Counter = field(default_factory=Counter)
    passed: Counter = field(default_factory=Counter)
    reject_codes: Counter = field(default_factory=Counter)
    reject_monthly: dict[str, Counter] = field(default_factory=dict)
    reject_yearly: dict[str, Counter] = field(default_factory=dict)
    cancel_reasons: Counter = field(default_factory=Counter)
    lifecycle: Counter = field(default_factory=Counter)

    def record(self, fail_index: int | None, code: str | None, timestamp: pd.Timestamp) -> None:
        gates = GATES[self.child]
        limit = len(gates) if fail_index is None else fail_index
        for gate in gates[:limit]:
            self.entered[gate.key] += 1
            self.passed[gate.key] += 1
        if fail_index is None:
            return
        self.entered[gates[fail_index].key] += 1
        if code is None:
            return
        self.reject_codes[code] += 1
        month = timestamp.strftime("%Y-%m")
        year = timestamp.strftime("%Y")
        self.reject_monthly.setdefault(month, Counter())[code] += 1
        self.reject_yearly.setdefault(year, Counter())[code] += 1

    def merge(self, other: "ChildFunnel") -> None:
        self.entered.update(other.entered)
        self.passed.update(other.passed)
        self.reject_codes.update(other.reject_codes)
        self.cancel_reasons.update(other.cancel_reasons)
        self.lifecycle.update(other.lifecycle)
        for period, counts in other.reject_monthly.items():
            self.reject_monthly.setdefault(period, Counter()).update(counts)
        for period, counts in other.reject_yearly.items():
            self.reject_yearly.setdefault(period, Counter()).update(counts)

    def rows(self, total_bars: int) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        previous: int | None = None
        for gate in GATES[self.child]:
            entered = int(self.entered[gate.key])
            passed = int(self.passed[gate.key])
            output.append({
                "gate": gate.label,
                "gate_key": gate.key,
                "entered": entered,
                "passed": passed,
                "failed": entered - passed,
                #--- Survivors of this gate as a share of the previous gate's
                #--- survivors. entered == previous passed by construction, so
                #--- dividing entered by it would report a constant 100%.
                "conversion_from_prior_percent": (
                    None if previous in (None, 0) else round(100 * passed / previous, 4)),
                "pass_rate_percent": (
                    None if not entered else round(100 * passed / entered, 4)),
                "percent_of_all_bars": (
                    None if not total_bars else round(100 * entered / total_bars, 4)),
                "source_condition": gate.source,
            })
            previous = passed
        return output


@dataclass
class CoreFunnelReport:
    """Everything the observer collected, mergeable across data segments."""
    children: dict[str, ChildFunnel] = field(
        default_factory=lambda: {name: ChildFunnel(name) for name in GATES})
    core_counters: Counter = field(default_factory=Counter)
    integrity: Counter = field(default_factory=Counter)
    xray_truncated: bool = False

    def merge(self, other: "CoreFunnelReport") -> None:
        for name, funnel in other.children.items():
            self.children[name].merge(funnel)
        self.core_counters.update(other.core_counters)
        self.integrity.update(other.integrity)
        self.xray_truncated = self.xray_truncated or other.xray_truncated

    @property
    def total_bars(self) -> int:
        return int(self.children["A4"].entered["bars_evaluated"])

    def to_payload(self) -> dict[str, Any]:
        total = self.total_bars
        return {
            "available": bool(total),
            "total_bars": total,
            "children": {
                name: {
                    "child": name,
                    "name": CHILD_NAMES[name],
                    "setup_id": SETUP_IDS[name],
                    "direction": "LONG" if name == "A4" else "SHORT",
                    "gates": funnel.rows(total),
                    "reject_codes": dict(funnel.reject_codes.most_common()),
                    "reject_monthly": {period: dict(counts)
                                       for period, counts in sorted(funnel.reject_monthly.items())},
                    "reject_yearly": {period: dict(counts)
                                      for period, counts in sorted(funnel.reject_yearly.items())},
                    "cancel_reasons": dict(funnel.cancel_reasons.most_common()),
                    "lifecycle": dict(funnel.lifecycle),
                }
                for name, funnel in self.children.items()
            },
            "core_counters": dict(self.core_counters),
            "integrity": dict(self.integrity),
            "xray_truncated": self.xray_truncated,
        }


@dataclass(frozen=True)
class _A4Snapshot:
    window_start: Any
    window_end: Any
    pullback_active: bool
    pullback_start_time: Any
    pullback_low: float | None
    last_broken_structure_level: float | None


@dataclass(frozen=True)
class _Verdict:
    fail_index: int | None
    code: str | None
    rules: tuple[tuple[str, Any, Any, bool, str], ...] = ()
    trigger: float | None = None
    stop: float | None = None


def _fail(index: int, code: str, rules=()) -> _Verdict:
    return _Verdict(index, code, tuple(rules))


class CoreFunnelObserver(Strategy):
    """Transparent instrumentation wrapper around the frozen BTC V3 Core v1."""

    def __init__(self, core: BtcV3CoreV1Frozen, *, xray_limit: int = DEFAULT_XRAY_LIMIT) -> None:
        if not isinstance(core, BtcV3CoreV1Frozen):
            raise TypeError("CoreFunnelObserver only instruments BtcV3CoreV1Frozen.")
        self.core = core
        self.xray_limit = xray_limit
        self.report = CoreFunnelReport()
        self.xray_evaluations: list[XRayEvaluation] = []
        self._state: ExecutionState | None = None
        self._reset_shadow()

    #--- Strategy delegation -------------------------------------------------
    def reset(self) -> None:
        self.core.reset()
        self.report = CoreFunnelReport()
        self.xray_evaluations = []
        self._state = None
        self._reset_shadow()

    def on_data_gap(self) -> None:
        self.core.on_data_gap()
        self._reset_shadow()

    def on_backtest_window(self, start, end) -> None:
        self.core.on_backtest_window(start, end)

    def on_execution_state(self, state: ExecutionState) -> None:
        self._state = state
        self.core.on_execution_state(state)

    def on_backtest_end(self, pending_order: PendingOrder):
        return self.core.on_backtest_end(pending_order)

    def __getattr__(self, name: str) -> Any:
        # Anything the engine or research code reads off a strategy (diagnostics,
        # signal_diagnostics, a4, t3, ...) resolves to the frozen Core itself.
        core = self.__dict__.get("core")
        if core is None:
            raise AttributeError(name)
        return getattr(core, name)

    #--- Shadow indicator set ------------------------------------------------
    def _reset_shadow(self) -> None:
        a4 = self.core.a4.params
        self._h1 = ConfirmedH1Regime(a4.h1_fast_ema, a4.h1_slow_ema,
                                     a4.h1_atr_length, a4.h1_slope_lookback)
        self._fast = EMA(a4.ema_fast)
        self._slow = EMA(a4.ema_slow)
        self._atr = ATR(a4.atr_length)
        self._rsi = RSI(a4.rsi_length)
        self._dmi = DMI(a4.di_length, a4.adx_smoothing)
        t3 = self.core.t3.params
        depth = max(a4.local_structure_lookback, t3.trend_structure_lookback,
                    t3.range_sweep_lookback, t3.trend_stop_lookback)
        self._history: deque[Candle] = deque(maxlen=depth)

    #--- The instrumented bar ------------------------------------------------
    def on_candle(self, candle: Candle):
        state = self._state
        if state is None:
            raise RuntimeError("CoreFunnelObserver needs execution state from the backtester.")

        h1 = self._h1.update(candle)
        ema20 = self._fast.update(candle.close)
        ema50 = self._slow.update(candle.close)
        atr = self._atr.update(candle)
        rsi = self._rsi.update(candle.close)
        dmi = self._dmi.update(candle)
        prior = list(self._history)
        self._history.append(candle)

        snapshot = _A4Snapshot(
            window_start=self.core.a4.window_start,
            window_end=self.core.a4.window_end,
            pullback_active=self.core.a4.pullback_active,
            pullback_start_time=self.core.a4.pullback_start_time,
            pullback_low=self.core.a4.pullback_low,
            last_broken_structure_level=self.core.a4.last_broken_structure_level,
        )
        t3_window = (self.core.t3.window_start, self.core.t3.window_end)

        #--- The frozen strategy runs here, untouched. Everything above is a read.
        action = self.core.on_candle(candle)

        a4_verdict = self._a4_verdict(candle, state, snapshot,
                                      self.core.a4.trades_today, h1, ema20, ema50,
                                      atr, rsi, dmi.adx, prior)
        t3_verdict = self._t3_verdict(candle, state, t3_window,
                                      self.core.t3.trades_today, h1, ema20, ema50,
                                      atr, rsi, dmi.adx, prior)
        self.report.children["A4"].record(a4_verdict.fail_index, a4_verdict.code, candle.timestamp)
        self.report.children["T3"].record(t3_verdict.fail_index, t3_verdict.code, candle.timestamp)
        self._record_cancel(action, state)
        self._emit_xray(candle, "A4", a4_verdict)
        self._emit_xray(candle, "T3", t3_verdict)
        self._cross_check(action, state, a4_verdict, t3_verdict)
        return action

    def _record_cancel(self, action, state: ExecutionState) -> None:
        from engine.models import CancelPendingOrder
        if not isinstance(action, CancelPendingOrder):
            return
        pending = state.pending_order
        if pending is None:
            return
        child = "A4" if pending.setup_id == A4_SETUP_ID else "T3"
        self.report.children[child].cancel_reasons[action.reason] += 1

    def _cross_check(self, action, state: ExecutionState,
                     a4_verdict: _Verdict, t3_verdict: _Verdict) -> None:
        """Compare the instrumentation's verdict with the Core's real action."""
        a4_setup = a4_verdict.fail_index is None
        t3_setup = t3_verdict.fail_index is None
        if a4_setup and t3_setup:
            self.report.core_counters["both_children_signalled"] += 1
        expected = A4_SETUP_ID if a4_setup else (T3_SETUP_ID if t3_setup else None)
        if state.pending_order is not None or state.position is not None:
            if expected is not None:
                self.report.core_counters["child_setup_suppressed_by_execution_state"] += 1
            return
        self.report.integrity["bars_cross_checked"] += 1
        if isinstance(action, Signal):
            if expected != action.setup_id:
                self.report.integrity["signal_mismatches"] += 1
                return
            verdict = a4_verdict if a4_setup else t3_verdict
            if (action.pending_entry_price != verdict.trigger
                    or action.pending_stop_price != verdict.stop):
                self.report.integrity["price_mismatches"] += 1
        elif expected is not None:
            self.report.integrity["signal_mismatches"] += 1

    #--- A4 ------------------------------------------------------------------
    def _a4_verdict(self, candle, state, snap, trades_today, h1, ema20, ema50,
                    atr, rsi, adx, prior) -> _Verdict:
        a4 = self.core.a4
        p = a4.params
        ts = candle.timestamp

        if ((snap.window_start is not None and ts < snap.window_start)
                or (snap.window_end is not None and ts > snap.window_end)):
            return _fail(1, "A4_OUTSIDE_WARMUP_WINDOW")
        if state.pending_order is not None:
            owned = state.pending_order.setup_id == A4_SETUP_ID
            return _fail(2, "A4_BLOCKED_BY_OWN_PENDING" if owned else "A4_BLOCKED_BY_T3_PENDING")
        if state.position is not None:
            return _fail(3, "A4_POSITION_OPEN")
        if not p.session_start <= ts.time() < p.session_end:
            return _fail(4, "A4_OUTSIDE_SESSION")
        if trades_today >= p.max_trades_per_day:
            return _fail(5, "A4_DAILY_TRADE_CAP")
        if atr is None or atr <= 0:
            return _fail(6, "A4_ATR_WARMING_UP")
        if rsi is None:
            return _fail(6, "A4_RSI_WARMING_UP")
        if adx is None:
            return _fail(6, "A4_ADX_WARMING_UP")

        #--- The frozen predicates decide; the decomposition only names the cause.
        context_valid = a4._context_valid(h1, ema20, ema50, adx)
        material_below = a4._materially_below_ema50(candle, ema50, atr)
        if not context_valid:
            return _fail(*self._a4_context_cause(h1, ema20, ema50, adx, p))
        if material_below:
            return _fail(11, "A4_CLOSE_MATERIALLY_BELOW_EMA50")

        depth = max(0.0, (ema20 - candle.low) / atr)
        if snap.pullback_active and depth > p.max_pullback_depth_below_ema20_atr:
            return _fail(12, "A4_PULLBACK_TOO_DEEP")

        if not snap.pullback_active:
            prior_high = (max(x.high for x in prior[-p.local_structure_lookback:])
                          if len(prior) >= p.local_structure_lookback else None)
            if prior_high is not None and candle.close > prior_high:
                return _fail(13, "A4_STRUCTURE_BREAK_IMPULSE_BAR")
            touched = (candle.low <= ema20 or candle.low <= ema50
                       or (snap.last_broken_structure_level is not None
                           and candle.low <= snap.last_broken_structure_level))
            if not touched:
                return _fail(13, "A4_NO_PULLBACK_TOUCH")
            if depth > p.max_pullback_depth_below_ema20_atr:
                return _fail(13, "A4_PULLBACK_START_TOO_DEEP")
            return _fail(13, "A4_PULLBACK_STARTED_THIS_BAR")
        if snap.pullback_start_time is None or ts <= snap.pullback_start_time:
            return _fail(13, "A4_PULLBACK_SAME_BAR")

        previous_candle = prior[-1] if prior else None
        rules, cause = self._a4_confirmation_cause(candle, previous_candle, ema20, rsi, p)
        confirmed = a4_confirmation_passes(candle, previous_candle, ema20, rsi, p)
        if not confirmed:
            return _Verdict(14, cause, tuple(rules))

        pullback_low = (min(snap.pullback_low, candle.low)
                        if snap.pullback_low is not None else candle.low)
        trigger = candle.high + p.entry_buffer_atr * atr
        stop = pullback_low - p.stop_buffer_atr * atr
        risk_atr = (trigger - stop) / atr
        rules.append(("stop_distance_atr", risk_atr,
                      [p.minimum_stop_atr, p.maximum_stop_atr],
                      p.minimum_stop_atr <= risk_atr <= p.maximum_stop_atr,
                      "Structural stop distance in ATR band"))
        if risk_atr < p.minimum_stop_atr:
            return _Verdict(15, "A4_STOP_DISTANCE_TOO_TIGHT", tuple(rules))
        if risk_atr > p.maximum_stop_atr:
            return _Verdict(15, "A4_STOP_DISTANCE_TOO_WIDE", tuple(rules))
        return _Verdict(None, None, tuple(rules), trigger, stop)

    @staticmethod
    def _a4_context_cause(h1, ema20, ema50, adx, p) -> tuple[int, str]:
        if (h1.close is None or h1.fast_ema is None or h1.slow_ema is None
                or h1.slope is None or h1.separation_atr is None):
            return 7, "A4_H1_UNCONFIRMED"
        if not h1.fast_ema > h1.slow_ema:
            return 7, "A4_H1_EMA50_BELOW_EMA200"
        if not h1.close > h1.slow_ema:
            return 7, "A4_H1_CLOSE_BELOW_EMA200"
        if not h1.slope > 0:
            return 7, "A4_H1_EMA200_SLOPE_NOT_POSITIVE"
        if h1.separation_atr < p.h1_min_separation_atr:
            return 7, "A4_H1_SEPARATION_BELOW_MIN"
        if not ema20 > ema50:
            return 8, "A4_M15_EMA20_BELOW_EMA50"
        if adx < p.min_adx:
            return 9, "A4_ADX_BELOW_MINIMUM"
        if h1.atr is None or h1.atr <= 0:
            return 10, "A4_H1_ATR_UNAVAILABLE"
        return 10, "A4_NORMALIZED_H1_SLOPE_BELOW_MIN"

    @staticmethod
    def _a4_confirmation_cause(candle, previous_candle, ema20, rsi, p):
        from strategies.btc_v3_a4_pullback_long import CONFIRMATION_MAX_BODY_PERCENT
        rules: list[tuple[str, Any, Any, bool, str]] = []
        if previous_candle is None or rsi is None:
            return rules, "A4_CONFIRM_NO_PREVIOUS_CANDLE"
        bullish = candle.close > candle.open
        rules.append(("confirmation_candle_bullish", candle.close - candle.open, 0.0,
                      bullish, "Reclaim candle must close above its open"))
        if not bullish:
            return rules, "A4_CONFIRM_CANDLE_NOT_BULLISH"
        body = a4_body_percent(candle)
        rules.append(("confirmation_body_percent", body, p.confirmation_min_body_percent,
                      body >= p.confirmation_min_body_percent, "Body >= confirmation_min_body_percent"))
        if body < p.confirmation_min_body_percent:
            return rules, "A4_CONFIRM_BODY_BELOW_MIN"
        above = candle.close > ema20
        rules.append(("confirmation_close_vs_ema20", candle.close - ema20, 0.0, above,
                      "Reclaim closes above EMA20"))
        if not above:
            return rules, "A4_CONFIRM_CLOSE_BELOW_EMA20"
        broke = candle.close > previous_candle.high
        rules.append(("confirmation_break_previous_high", candle.close - previous_candle.high,
                      0.0, broke, "Close above the previous candle high"))
        if not broke:
            return rules, "A4_CONFIRM_NO_BREAK_OF_PREVIOUS_HIGH"
        in_band = p.confirmation_rsi_min <= rsi <= p.confirmation_rsi_max
        rules.append(("confirmation_rsi", rsi,
                      [p.confirmation_rsi_min, p.confirmation_rsi_max], in_band,
                      "RSI within the confirmation band"))
        if rsi < p.confirmation_rsi_min:
            return rules, "A4_CONFIRM_RSI_BELOW_BAND"
        if rsi > p.confirmation_rsi_max:
            return rules, "A4_CONFIRM_RSI_ABOVE_BAND"
        capped = body <= CONFIRMATION_MAX_BODY_PERCENT
        rules.append(("confirmation_body_cap", body, CONFIRMATION_MAX_BODY_PERCENT, capped,
                      "A4 overlay: body <= CONFIRMATION_MAX_BODY_PERCENT"))
        if not capped:
            return rules, "A4_CONFIRM_BODY_ABOVE_MAX"
        return rules, None

    #--- T3 ------------------------------------------------------------------
    def _t3_verdict(self, candle, state, window, trades_today, h1, ema20, ema50,
                    atr, rsi, adx, prior) -> _Verdict:
        p = self.core.t3.params
        ts = candle.timestamp
        window_start, window_end = window

        if ((window_start is not None and ts < window_start)
                or (window_end is not None and ts > window_end)):
            return _fail(1, "T3_OUTSIDE_WARMUP_WINDOW")
        if not p.session_start <= ts.time() < p.session_end:
            return _fail(2, "T3_OUTSIDE_SESSION")
        if trades_today >= p.max_trades_per_day:
            return _fail(3, "T3_DAILY_TRADE_CAP")
        if state.position is not None:
            return _fail(4, "T3_POSITION_OPEN")
        if state.pending_order is not None:
            owned = state.pending_order.setup_id == T3_SETUP_ID
            return _fail(5, "T3_BLOCKED_BY_OWN_PENDING" if owned else "T3_BLOCKED_BY_A4_PENDING")
        if atr is None or atr <= 0:
            return _fail(6, "T3_ATR_WARMING_UP")
        if rsi is None:
            return _fail(6, "T3_RSI_WARMING_UP")

        trend_high = (max(x.high for x in prior[-p.trend_structure_lookback:])
                      if len(prior) >= p.trend_structure_lookback else None)
        trend_low = (min(x.low for x in prior[-p.trend_structure_lookback:])
                     if len(prior) >= p.trend_structure_lookback else None)
        range_high = (max(x.high for x in prior[-p.range_sweep_lookback:])
                      if len(prior) >= p.range_sweep_lookback else None)
        range_low = (min(x.low for x in prior[-p.range_sweep_lookback:])
                     if len(prior) >= p.range_sweep_lookback else None)
        stop_bars = prior[-(p.trend_stop_lookback - 1):] if p.trend_stop_lookback > 1 else []
        observation = V3Observation(
            candle=candle, h1=h1, ema_fast=ema20, ema_slow=ema50, adx=adx, rsi=rsi, atr=atr,
            trend_previous_high=trend_high, trend_previous_low=trend_low,
            range_previous_high=range_high, range_previous_low=range_low,
            trend_stop_low=min(x.low for x in (*stop_bars, candle)),
            trend_stop_high=max(x.high for x in (*stop_bars, candle)),
        )
        #--- classify_regime and evaluate_v3 are pure; the frozen source decides.
        regime = classify_regime(observation, p)
        if regime.state is not MarketRegime.TREND or regime.direction is not Direction.SHORT:
            return _fail(*self._t3_regime_cause(h1, ema20, ema50, adx, regime, p))
        if not p.shorts_enabled:
            return _fail(11, "T3_SHORTS_DISABLED")

        rules, cause, index = self._t3_breakout_cause(observation, p)
        if cause is not None:
            return _Verdict(index, cause, tuple(rules))

        trigger = candle.low - p.entry_buffer_atr * atr
        stop = observation.trend_stop_high + p.stop_buffer_atr * atr
        signal = evaluate_v3(observation, p)
        if signal is None:
            risk_atr = (stop - trigger) / atr if atr > 0 else None
            rules.append(("stop_distance_atr", risk_atr,
                          [p.minimum_stop_atr, p.maximum_stop_atr], False,
                          "Structural stop distance in ATR band"))
            if not (trigger > 0 and stop > 0):
                return _Verdict(18, "T3_INVALID_PENDING_PRICES", tuple(rules))
            if risk_atr is not None and risk_atr < p.minimum_stop_atr:
                return _Verdict(18, "T3_STOP_DISTANCE_TOO_TIGHT", tuple(rules))
            return _Verdict(18, "T3_STOP_DISTANCE_TOO_WIDE", tuple(rules))
        rules.append(("stop_distance_atr", (stop - trigger) / atr,
                      [p.minimum_stop_atr, p.maximum_stop_atr], True,
                      "Structural stop distance in ATR band"))
        return _Verdict(None, None, tuple(rules),
                        signal.pending_entry_price, signal.pending_stop_price)

    @staticmethod
    def _t3_regime_cause(h1, ema20, ema50, adx, regime, p) -> tuple[int, str]:
        if h1.separation_atr is None or h1.slope is None or adx is None:
            return 7, "T3_H1_REGIME_UNCONFIRMED"
        if h1.separation_atr < p.trend_min_h1_separation_atr:
            return 8, "T3_H1_SEPARATION_BELOW_MIN"
        if adx < p.trend_min_adx:
            return 9, "T3_ADX_BELOW_MINIMUM"
        if regime.direction is Direction.LONG:
            return 10, "T3_TREND_DIRECTION_LONG"
        if not h1.fast_ema < h1.slow_ema:
            return 10, "T3_H1_EMA50_ABOVE_EMA200"
        if not h1.slope < 0:
            return 10, "T3_H1_EMA200_SLOPE_NOT_NEGATIVE"
        return 10, "T3_M15_EMA20_ABOVE_EMA50"

    @staticmethod
    def _t3_breakout_cause(obs, p):
        c, atr = obs.candle, obs.atr
        rules: list[tuple[str, Any, Any, bool, str]] = []
        if obs.trend_previous_low is None:
            return rules, "T3_NO_STRUCTURE_LOW", 12
        broke = c.close < obs.trend_previous_low
        rules.append(("structure_breakdown", c.close - obs.trend_previous_low, 0.0, broke,
                      "Close below the prior 5-bar low"))
        if not broke:
            return rules, "T3_NO_BREAKDOWN_OF_STRUCTURE_LOW", 12
        bearish = c.close < c.open
        rules.append(("candle_bearish", c.close - c.open, 0.0, bearish,
                      "Breakout candle must close below its open"))
        if not bearish:
            return rules, "T3_CANDLE_NOT_BEARISH", 13
        body = t3_body_percent(c)
        rules.append(("body_percent", body, p.trend_minimum_body_percent,
                      body >= p.trend_minimum_body_percent, "Body >= trend_minimum_body_percent"))
        if body < p.trend_minimum_body_percent:
            return rules, "T3_BODY_BELOW_MIN", 14
        range_atr = (c.high - c.low) / atr
        in_range = p.trend_minimum_range_atr <= range_atr <= p.trend_maximum_range_atr
        rules.append(("range_atr", range_atr,
                      [p.trend_minimum_range_atr, p.trend_maximum_range_atr], in_range,
                      "Candle range within the ATR band"))
        if range_atr < p.trend_minimum_range_atr:
            return rules, "T3_RANGE_BELOW_MIN", 15
        if range_atr > p.trend_maximum_range_atr:
            return rules, "T3_RANGE_ABOVE_MAX", 15
        in_band = p.trend_short_rsi_min <= obs.rsi <= p.trend_short_rsi_max
        rules.append(("rsi", obs.rsi, [p.trend_short_rsi_min, p.trend_short_rsi_max], in_band,
                      "RSI within the short band"))
        if obs.rsi < p.trend_short_rsi_min:
            return rules, "T3_RSI_BELOW_MIN", 16
        if obs.rsi > p.trend_short_rsi_max:
            return rules, "T3_RSI_ABOVE_MAX", 16
        extension = abs(c.close - obs.ema_fast) / atr
        within = extension <= p.trend_maximum_extension_atr
        rules.append(("extension_atr", extension, p.trend_maximum_extension_atr, within,
                      "Distance from EMA20 within the extension cap"))
        if not within:
            return rules, "T3_OVEREXTENDED_FROM_EMA20", 17
        return rules, None, None

    #--- X-Ray ---------------------------------------------------------------
    def _emit_xray(self, candle: Candle, child: str, verdict: _Verdict) -> None:
        if not verdict.rules:
            return
        if len(self.xray_evaluations) >= self.xray_limit:
            self.report.xray_truncated = True
            return
        for rule, observed, threshold, ok, description in verdict.rules:
            self.xray_evaluations.append(XRayEvaluation(
                timestamp=candle.timestamp,
                strategy_id=CORE_STRATEGY_ID,
                component=SETUP_IDS[child],
                rule=f"{child.lower()}_{rule}",
                observed_value=observed,
                threshold=threshold,
                result="PASS" if ok else "FAIL",
                reason_code="" if ok else (verdict.code or ""),
                description=description,
            ))


#--- Registry ---------------------------------------------------------------
INSTRUMENTED_STRATEGIES = {CORE_STRATEGY_ID: CoreFunnelObserver}


def instrument(strategy: Strategy, strategy_id: str) -> Strategy:
    """Wrap a strategy in its diagnostic observer, or return it unchanged."""
    observer = INSTRUMENTED_STRATEGIES.get(strategy_id)
    return strategy if observer is None else observer(strategy)


def lifecycle_from_order_events(events) -> dict[str, Counter]:
    """Per-child pending-order outcomes, taken from the engine's own events."""
    output = {name: Counter() for name in GATES}
    by_setup = {setup_id: name for name, setup_id in SETUP_IDS.items()}
    for event in events:
        child = by_setup.get(event.setup_id)
        if child is None:
            continue
        output[child]["order_created"] += 1
        output[child][{"triggered": "filled", "expired": "expired",
                       "cancelled": "cancelled",
                       "active_at_end": "active_at_end"}.get(event.status, event.status)] += 1
    return output
