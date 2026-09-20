"""Export candle-by-candle audit records for the frozen BTC Core.

This is the Python half of the MT5 digital twin. It drives the real
BtcV3CoreV1Frozen through the audited engine's own execution primitives
(create_pending_order / fill_pending_order / exit_decision / close_position),
so order lifecycle behaviour is identical to run_universal_backtest by
construction rather than by imitation.

No frozen file is modified and no strategy logic is reimplemented: gate
outcomes are derived by calling the frozen predicates themselves
(h1_bullish, confirmation_passes, classify_regime, body_percent), and indicator
values come from a parallel instance of the same pine_indicators classes the
strategies use, fed the same candle sequence.

As a safety net the exporter re-runs run_universal_backtest over the same data
and asserts the resulting trade log matches, so a drifting replica cannot be
reported as parity evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.adapters.audited_engine import run_universal_backtest           # noqa: E402
from core.config import BacktestConfig, DatasetRole                       # noqa: E402
from engine.backtester import _validated_candles                          # noqa: E402
from engine.execution import (close_position, create_pending_order,       # noqa: E402
                              exit_decision, fill_pending_order)
from engine.models import (BacktestSettings, CancelPendingOrder, Direction,  # noqa: E402
                           EntryModel, ExecutionState, RiskCalculation,
                           RiskMode, SameBarResolution, Signal)
from strategies.btc_v3_a4_pullback_long import (                          # noqa: E402
    CONFIRMATION_MAX_BODY_PERCENT, MINIMUM_NORMALIZED_H1_SLOPE,
    BtcV3A4PullbackLongFrozen, frozen_parameters as a4_parameters,
)
from strategies.btc_v3_core_v1 import BtcV3CoreV1Frozen                   # noqa: E402
from strategies.btc_v3_l2_trend_pullback_long import (                    # noqa: E402
    MATERIAL_EMA50_CLOSE_ATR, body_percent, h1_bullish,
)
from strategies.btc_v3_t3_breakout_short import (                         # noqa: E402
    MarketRegime, V3Observation, V3T3FrozenParameters, classify_regime,
)
from strategies.confirmed_h1_regime import ConfirmedH1Regime              # noqa: E402
from strategies.pine_indicators import ATR, DMI, EMA, RSI                 # noqa: E402
from strategies.registry import discover_builtin_strategies               # noqa: E402
from tools.core_audit_schema import AUDIT_COLUMNS, UNVERIFIED             # noqa: E402
from utils.data_validation import continuous_segments, load_ohlcv_csv     # noqa: E402

#: The A4 blocked code and the T3 code derived from it. Spelled out so the whole
#: reject vocabulary is greppable from both halves of the twin, and so an
#: unrecognised pair fails loudly instead of reaching a row.
BLOCKED_CODE_PAIRS = (
    ("A4_BLOCKED_PENDING", "T3_BLOCKED_PENDING"),
    ("A4_BLOCKED_POSITION", "T3_BLOCKED_POSITION"),
    ("A4_BEFORE_WINDOW", "T3_BEFORE_WINDOW"),
)

EXNESS_M15 = ROOT / "data/exness/btc/phase_r1/processed/btcusdm_M15.csv"
STRATEGY_ID = "BTC_V3_CORE_V1_FROZEN"
FROZEN_CORE_HASH = "631374d50cfa75d46349c0e7e8b2f26ac482e2bbf6dc1cf74dc8e1a00e16a9fd"
A4_SETUP_ID = "BTC_V3_A4_PULLBACK_LONG_FROZEN"
T3_SETUP_ID = "BTC_V3_T3_BREAKOUT_SHORT_FROZEN"
SYMBOL = "BTCUSDm"
STEP = pd.Timedelta(minutes=15)


def _iso(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return pd.Timestamp(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def _num(value) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return f"{float(value):.10f}"


def _flag(value) -> str:
    return "" if value is None else ("1" if value else "0")


@dataclass
class _H1Bar:
    """The confirmed H1 bar's OHLC, rebuilt with the same four-bar rule the
    frozen ConfirmedH1Regime uses. Audit-only: the strategy never reads it."""
    time: pd.Timestamp | None = None
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None


class _Replica:
    """Parallel indicator set using the very classes the frozen strategies use.

    Both A4 and T3 declare identical indicator lengths (EMA 20/50, ATR 14,
    RSI 14, DMI 14/14, H1 50/200/14/4), so one replica reproduces both.
    """

    def __init__(self) -> None:
        p = a4_parameters()
        self.h1 = ConfirmedH1Regime(p.h1_fast_ema, p.h1_slow_ema, p.h1_atr_length,
                                    p.h1_slope_lookback)
        self.fast = EMA(p.ema_fast)
        self.slow = EMA(p.ema_slow)
        self.atr = ATR(p.atr_length)
        self.rsi = RSI(p.rsi_length)
        self.dmi = DMI(p.di_length, p.adx_smoothing)
        self._bucket: pd.Timestamp | None = None
        self._bars: list = []
        self.h1_bar = _H1Bar()

    def update(self, candle):
        hour = candle.timestamp.floor("h")
        if self._bucket is not None and hour != self._bucket:
            expected = [self._bucket + pd.Timedelta(minutes=15 * i) for i in range(4)]
            if [bar.timestamp for bar in self._bars] == expected:
                self.h1_bar = _H1Bar(
                    self._bucket, self._bars[0].open,
                    max(b.high for b in self._bars), min(b.low for b in self._bars),
                    self._bars[-1].close)
            self._bars = []
        self._bucket = hour
        self._bars.append(candle)

        regime = self.h1.update(candle)
        return {
            "h1": regime, "h1_bar": self.h1_bar,
            "ema20": self.fast.update(candle.close),
            "ema50": self.slow.update(candle.close),
            "atr": self.atr.update(candle),
            "rsi": self.rsi.update(candle.close),
            "dmi": self.dmi.update(candle),
        }


def _a4_reject(view, candle, prior, *, in_session, trades_today, blocked) -> tuple[str, bool, bool]:
    """Re-derive the A4 gate outcome using the frozen predicates only."""
    p = a4_parameters()
    h1, ema20, ema50 = view["h1"], view["ema20"], view["ema50"]
    atr, rsi, adx = view["atr"], view["rsi"], view["dmi"].adx
    if blocked:
        return blocked, False, False
    if not in_session:
        return "A4_OUT_OF_SESSION", False, False
    if trades_today >= p.max_trades_per_day:
        return "A4_MAX_TRADES_PER_DAY", False, False
    if atr is None or atr <= 0 or rsi is None or adx is None:
        return "A4_WARMUP", False, False

    bullish = h1_bullish(h1, p)
    if not bullish:
        return "A4_H1_NOT_BULLISH", False, False
    if not ema20 > ema50:
        return "A4_EMA_STACK_FAIL", False, False
    if adx < p.min_adx:
        return "A4_ADX_FAIL", False, False
    if h1.slope is None or h1.atr is None or h1.atr <= 0 or \
            h1.slope / h1.atr < MINIMUM_NORMALIZED_H1_SLOPE:
        return "A4_H1_SLOPE_NORM_FAIL", False, False
    if candle.close < ema50 - MATERIAL_EMA50_CLOSE_ATR * atr:
        return "A4_MATERIAL_BELOW_EMA50", True, False
    return "A4_CONTEXT_OK", True, False


def _a4_confirmation_reject(candle, previous_candle, ema20, rsi) -> str:
    """Which confirmation clause failed, in the frozen predicate's own order."""
    p = a4_parameters()
    if previous_candle is None or rsi is None:
        return "A4_WARMUP"
    if not candle.close > candle.open:
        return "A4_CONFIRM_NOT_BULLISH"
    body = body_percent(candle)
    if body < p.confirmation_min_body_percent:
        return "A4_BODY_TOO_SMALL"
    if not candle.close > ema20:
        return "A4_CLOSE_BELOW_EMA20"
    if not candle.close > previous_candle.high:
        return "A4_NO_BREAK_PREV_HIGH"
    if not p.confirmation_rsi_min <= rsi <= p.confirmation_rsi_max:
        return "A4_RSI_OUT_OF_BAND"
    if body > CONFIRMATION_MAX_BODY_PERCENT:
        return "A4_BODY_TOO_LARGE"
    return "A4_CONFIRM_OK"


@dataclass(frozen=True)
class _A4Snapshot:
    """A4 pullback/structure state as it stood BEFORE on_candle saw this bar.

    The frozen strategy mutates this state while it decides, so the audit code
    has to be derived from the pre-call values — exactly what EvaluateA4 in the
    MQL5 twin reads. Using the post-call state reports the wrong reject code on
    every bar that changes the pullback.
    """
    pullback_active: bool
    pullback_low: float | None
    pullback_start_time: object


def _a4_state(strategy) -> _A4Snapshot:
    a4 = strategy.a4
    return _A4Snapshot(bool(a4.pullback_active), a4.pullback_low, a4.pullback_start_time)


def _a4_pullback_reject(state: _A4Snapshot, view, candle, previous_candle,
                        prior_high) -> tuple[str, tuple | None]:
    """Pullback-state-machine outcome, in btc_v3_l2_trend_pullback_long's own order.

    Mirrors on_candle from the depth test through the structure break, including
    the fall-through that lets a confirmation or same-bar rejection outrank
    A4_STRUCTURE_BREAK_BAR.
    """
    p = a4_parameters()
    atr, ema20, rsi = view["atr"], view["ema20"], view["rsi"]
    depth = max(0.0, (ema20 - candle.low) / atr)
    code = ""
    if state.pullback_active:
        if depth > p.max_pullback_depth_below_ema20_atr:
            return "A4_PULLBACK_TOO_DEEP", None
        if state.pullback_start_time is not None and candle.timestamp > state.pullback_start_time:
            code = _a4_confirmation_reject(candle, previous_candle, ema20, rsi)
            if code == "A4_CONFIRM_OK":
                pullback_low = (min(state.pullback_low, candle.low)
                                if state.pullback_low is not None else candle.low)
                trigger = candle.high + p.entry_buffer_atr * atr
                stop = pullback_low - p.stop_buffer_atr * atr
                risk_atr = (trigger - stop) / atr
                # Levels are published on every bar that computed them, which is
                # what Decision.has_levels means in the MQL5 twin.
                levels = (trigger, stop, risk_atr)
                if risk_atr < p.minimum_stop_atr:
                    return "A4_STOP_TOO_TIGHT", levels
                if risk_atr > p.maximum_stop_atr:
                    return "A4_STOP_TOO_WIDE", levels
                return "A4_SIGNAL_OK", levels
        else:
            code = "A4_SAME_BAR_AS_PULLBACK_START"
    if prior_high is not None and candle.close > prior_high:
        return code or "A4_STRUCTURE_BREAK_BAR", None
    return code or "A4_NO_PULLBACK", None


def _t3_reject(view, candle, obs, *, in_session, trades_today, blocked) -> tuple[str, str, bool, bool, tuple | None]:
    """Re-derive the T3 gate outcome using classify_regime and the frozen rules."""
    p = V3T3FrozenParameters()
    atr, rsi = view["atr"], view["rsi"]
    if blocked:
        return "", blocked, False, False, None
    if not in_session:
        return "", "T3_OUT_OF_SESSION", False, False, None
    if trades_today >= p.max_trades_per_day:
        return "", "T3_MAX_TRADES_PER_DAY", False, False, None
    if obs is None:
        return "", "T3_WARMUP", False, False, None
    regime = classify_regime(obs, p)
    label = regime.state.value
    if atr is None or atr <= 0 or rsi is None:
        return label, "T3_WARMUP", False, False, None
    if regime.state is not MarketRegime.TREND:
        return label, "T3_REGIME_NOT_TREND", False, False, None
    if regime.direction is Direction.LONG:
        return label, "T3_DIRECTION_LONG_DISABLED", True, False, None
    if obs.trend_previous_low is None:
        return label, "T3_WARMUP", True, False, None
    if not candle.close < obs.trend_previous_low:
        return label, "T3_NO_BREAK_PREV_LOW", True, False, None
    if not candle.close < candle.open:
        return label, "T3_NOT_BEARISH_CANDLE", True, False, None
    if body_percent(candle) < p.trend_minimum_body_percent:
        return label, "T3_BODY_FAIL", True, False, None
    range_atr = (candle.high - candle.low) / atr
    if range_atr < p.trend_minimum_range_atr:
        return label, "T3_RANGE_TOO_SMALL", True, False, None
    if range_atr > p.trend_maximum_range_atr:
        return label, "T3_RANGE_TOO_LARGE", True, False, None
    if not p.trend_short_rsi_min <= rsi <= p.trend_short_rsi_max:
        return label, "T3_RSI_OUT_OF_BAND", True, False, None
    if abs(candle.close - obs.ema_fast) / atr > p.trend_maximum_extension_atr:
        return label, "T3_EXTENSION_FAIL", True, False, None
    trigger = candle.low - p.entry_buffer_atr * atr
    stop = obs.trend_stop_high + p.stop_buffer_atr * atr
    risk_atr = (stop - trigger) / atr
    levels = (trigger, stop, risk_atr)
    if risk_atr < p.minimum_stop_atr:
        return label, "T3_STOP_TOO_TIGHT", True, False, levels
    if risk_atr > p.maximum_stop_atr:
        return label, "T3_STOP_TOO_WIDE", True, False, levels
    return label, "T3_SIGNAL_OK", True, True, levels


def _settings(config: BacktestConfig) -> BacktestSettings:
    return BacktestSettings(
        starting_balance=config.initial_capital,
        risk_mode=RiskMode.PERCENT_EQUITY if config.risk_mode == "PERCENT_EQUITY"
        else RiskMode.FIXED_DOLLARS,
        risk_percent=config.risk_per_trade_percent,
        fixed_risk_dollars=config.fixed_risk_dollars,
        risk_reward_ratio=config.risk_reward_ratio,
        commission_percent=config.commission_percent,
        slippage_percent=config.slippage_percent,
        same_bar_resolution=SameBarResolution.SL_FIRST,
        risk_calculation=RiskCalculation.ESTIMATED_TOTAL_STOP_LOSS,
        max_leverage=config.leverage, min_quantity=0.0,
    )


def export(data_path: Path, config: BacktestConfig, output: Path,
           *, verify: bool = True) -> pd.DataFrame:
    descriptor = discover_builtin_strategies().get(config.strategy_id)
    if descriptor.metadata.strategy_fingerprint != FROZEN_CORE_HASH:
        raise ValueError("Frozen Core fingerprint changed — refusing to export an audit.")
    settings = _settings(config)
    data = load_ohlcv_csv(data_path)
    data = data.loc[data.timestamp.between(pd.Timestamp(config.start_date),
                                           pd.Timestamp(config.end_date))].reset_index(drop=True)
    spread = pd.read_csv(data_path)
    stamp = "timestamp_utc" if "timestamp_utc" in spread.columns else "timestamp"
    spread_points = pd.Series(
        pd.to_numeric(spread.get("spread_points", pd.Series(dtype=float))).to_numpy(),
        index=pd.to_datetime(spread[stamp], utc=True)) if "spread_points" in spread else None
    spread_price = pd.Series(
        pd.to_numeric(spread.get("spread_price", pd.Series(dtype=float))).to_numpy(),
        index=pd.to_datetime(spread[stamp], utc=True)) if "spread_price" in spread else None

    rows: list[dict] = []
    all_trades = []
    for segment in continuous_segments(data):
        frame = data.loc[data.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
        trade_start = descriptor.warmup_resolver(segment.start)
        if trade_start > segment.end:
            continue
        rows.extend(_replay_segment(frame, trade_start, settings, config,
                                    spread_points, spread_price, all_trades))

    audit = pd.DataFrame(rows, columns=AUDIT_COLUMNS)
    output.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(output, index=False)

    if verify:
        reference = run_universal_backtest(data_path, config,
                                           ledger_path=Path("/tmp/pb_r4/audit_ledger.sqlite3"))
        if reference.total_trades != len(all_trades):
            raise ValueError(f"Replay produced {len(all_trades)} trades; engine produced "
                             f"{reference.total_trades}. The audit replay has drifted.")
        for engine_trade, replay in zip(reference.trade_log, all_trades):
            if abs(engine_trade["entry_price"] - replay.entry_price) > 1e-9 or \
                    abs(engine_trade["exit_price"] - replay.exit_price) > 1e-9:
                raise ValueError("Replay trade prices differ from the audited engine.")
    return audit


def _replay_segment(frame, trade_start, settings, config, spread_points, spread_price,
                    all_trades) -> list[dict]:
    """One continuous segment, mirroring research.exness_cost_calibrated.run_synthetic_segment."""
    from research.exness_cost_calibrated import entry_candle, exit_candle

    candles = _validated_candles(frame)
    strategy = BtcV3CoreV1Frozen()
    strategy.reset()
    strategy.on_backtest_window(trade_start, None)
    replica = _Replica()
    a4_params, t3_params = a4_parameters(), V3T3FrozenParameters()
    prior: list = []
    balance = settings.starting_balance
    pending = position = None
    rows: list[dict] = []

    for index, bid in enumerate(candles):
        opened = closed = None
        expired = False
        entered_intrabar = False
        bar_spread = (float(spread_price.get(bid.timestamp, config.spread))
                      if spread_price is not None else config.spread)
        if config.spread_source != "BROKER_NATIVE_PER_BAR":
            bar_spread = config.spread

        if pending is not None:
            order = pending
            if index > order.expiry_bar_index:
                pending = None
                expired = True
            else:
                side = entry_candle(bid, bar_spread, order.direction)
                position = fill_pending_order(order, side, index, len(all_trades) + 1, settings)
                if position is not None:
                    opened = position
                    entered_intrabar = (not position.gap_through_trigger and (
                        (order.direction is Direction.LONG and side.open < order.trigger_price)
                        or (order.direction is Direction.SHORT and side.open > order.trigger_price)))
                    pending = None
                elif index == order.expiry_bar_index:
                    pending = None
                    expired = True
        if position is not None:
            side = exit_candle(bid, bar_spread, position.direction)
            decision = exit_decision(position, side, settings.same_bar_resolution,
                                     entered_intrabar=entered_intrabar)
            if decision is not None:
                price, reason = decision
                closed = close_position(position, side, index, price, reason, settings)
                all_trades.append(closed)
                balance += closed.pnl
                position = None

        strategy.on_execution_state(ExecutionState(balance, pending, position, opened, closed))

        view = replica.update(bid)
        previous_candle = prior[-1] if prior else None
        prior_high = (max(x.high for x in prior[-a4_params.local_structure_lookback:])
                      if len(prior) >= a4_params.local_structure_lookback else None)
        t3_high = (max(x.high for x in prior[-t3_params.trend_structure_lookback:])
                   if len(prior) >= t3_params.trend_structure_lookback else None)
        t3_low = (min(x.low for x in prior[-t3_params.trend_structure_lookback:])
                  if len(prior) >= t3_params.trend_structure_lookback else None)
        range_high = (max(x.high for x in prior[-t3_params.range_sweep_lookback:])
                      if len(prior) >= t3_params.range_sweep_lookback else None)
        range_low = (min(x.low for x in prior[-t3_params.range_sweep_lookback:])
                     if len(prior) >= t3_params.range_sweep_lookback else None)
        stop_bars = prior[-(t3_params.trend_stop_lookback - 1):] \
            if t3_params.trend_stop_lookback > 1 else []
        stop_low = min(x.low for x in (*stop_bars, bid))
        stop_high = max(x.high for x in (*stop_bars, bid))

        a4_state = _a4_state(strategy)
        signal = strategy.on_candle(bid)
        prior.append(bid)
        if len(prior) > 16:
            prior.pop(0)

        in_window = bid.timestamp >= trade_start
        in_session = a4_params.session_start <= bid.timestamp.time() < a4_params.session_end
        blocked = ("A4_BLOCKED_PENDING" if pending is not None else
                   "A4_BLOCKED_POSITION" if position is not None else
                   "" if in_window else "A4_BEFORE_WINDOW")
        t3_blocked = blocked.replace("A4_", "T3_") if blocked else ""
        if blocked and (blocked, t3_blocked) not in BLOCKED_CODE_PAIRS:
            raise ValueError(f"Unknown blocked code pair {(blocked, t3_blocked)}.")

        observation = None
        if view["atr"] is not None and view["h1"].fast_ema is not None:
            observation = V3Observation(
                candle=bid, h1=view["h1"], ema_fast=view["ema20"], ema_slow=view["ema50"],
                adx=view["dmi"].adx, rsi=view["rsi"], atr=view["atr"],
                trend_previous_high=t3_high, trend_previous_low=t3_low,
                range_previous_high=range_high, range_previous_low=range_low,
                trend_stop_low=stop_low, trend_stop_high=stop_high)

        a4_code, a4_context, _ = _a4_reject(
            view, bid, prior, in_session=in_session,
            trades_today=strategy.a4.trades_today, blocked=blocked)
        a4_signal_pass = isinstance(signal, Signal) and signal.setup_id == A4_SETUP_ID
        a4_levels = None
        if a4_context and a4_code == "A4_CONTEXT_OK":
            a4_code, a4_levels = _a4_pullback_reject(
                a4_state, view, bid, previous_candle, prior_high)
        # The frozen strategy, not this derivation, decides whether a signal
        # fired. If the two disagree the derivation is wrong and the audit would
        # be misleading parity evidence, so fail loudly instead of papering over.
        if (a4_code == "A4_SIGNAL_OK") != a4_signal_pass:
            raise ValueError(
                f"A4 audit derivation says {a4_code!r} but the frozen strategy "
                f"{'emitted' if a4_signal_pass else 'did not emit'} a signal at "
                f"{bid.timestamp}.")

        t3_regime, t3_code, t3_context, _, t3_levels = _t3_reject(
            view, bid, observation, in_session=in_session,
            trades_today=strategy.t3.trades_today, blocked=t3_blocked)
        t3_signal_pass = isinstance(signal, Signal) and signal.setup_id == T3_SETUP_ID

        new_pending = None
        if isinstance(signal, Signal) and in_window and pending is None and position is None:
            if signal.entry_model is not EntryModel.STOP_ENTRY_PENDING:
                raise ValueError("Frozen Core must emit pending stop entries.")
            new_pending = create_pending_order(signal, bid, index, balance, settings)
            pending = new_pending
        elif isinstance(signal, CancelPendingOrder) and pending is not None:
            pending = None

        atr = view["atr"]
        rows.append(_row(bid, view, spread_points, spread_price, config,
                         strategy, a4_code, a4_context, a4_signal_pass, in_session,
                         prior_high, t3_regime, t3_code, t3_context, t3_signal_pass,
                         t3_high, t3_low, stop_high, stop_low, atr, observation,
                         signal, new_pending, pending, opened, closed, expired,
                         a4_levels, t3_levels))
    return rows


def _row(bid, view, spread_points, spread_price, config, strategy, a4_code, a4_context,
         a4_signal_pass, in_session, prior_high, t3_regime, t3_code, t3_context,
         t3_signal_pass, t3_high, t3_low, stop_high, stop_low, atr, observation,
         signal, new_pending, pending, opened, closed, expired,
         a4_levels, t3_levels) -> dict:
    h1, h1_bar = view["h1"], view["h1_bar"]
    dmi = view["dmi"]
    p4, p3 = a4_parameters(), V3T3FrozenParameters()
    # Levels appear only on bars that reached the point of computing them, so
    # the two sides publish on the same condition instead of one side filling
    # every bar with a hypothetical level the other never evaluated.
    a4_trigger, a4_stop, a4_stop_atr = a4_levels if a4_levels else (None, None, None)
    t3_trigger, t3_stop, t3_stop_atr = t3_levels if t3_levels else (None, None, None)
    if a4_signal_pass and isinstance(signal, Signal):
        # The frozen signal is authoritative for the level it actually carries.
        if (a4_trigger, a4_stop) != (signal.pending_entry_price, signal.pending_stop_price):
            raise ValueError(f"Derived A4 levels disagree with the frozen signal at {bid.timestamp}.")
    return {
        "bar_time_utc": _iso(bid.timestamp), "symbol": SYMBOL,
        "open": _num(bid.open), "high": _num(bid.high), "low": _num(bid.low),
        "close": _num(bid.close), "tick_volume": _num(bid.volume),
        "spread_points": _num(spread_points.get(bid.timestamp) if spread_points is not None else None),
        "spread_price": _num(spread_price.get(bid.timestamp) if spread_price is not None else None),
        "h1_time_utc": _iso(h1.hour), "h1_open": _num(h1_bar.open), "h1_high": _num(h1_bar.high),
        "h1_low": _num(h1_bar.low), "h1_close": _num(h1.close),
        "h1_ema50": _num(h1.fast_ema), "h1_ema200": _num(h1.slow_ema),
        "h1_ema200_past": _num(h1.slow_ema_lookback), "h1_atr": _num(h1.atr),
        "h1_slope": _num(h1.slope),
        "h1_slope_atr": _num(h1.slope / h1.atr if h1.slope is not None and h1.atr else None),
        "h1_separation_atr": _num(h1.separation_atr),
        "ema20": _num(view["ema20"]), "ema50": _num(view["ema50"]), "atr": _num(atr),
        "rsi": _num(view["rsi"]), "adx": _num(dmi.adx), "plus_di": _num(dmi.plus_di),
        "minus_di": _num(dmi.minus_di), "body_percent": _num(body_percent(bid)),
        "a4_context_pass": _flag(a4_context), "a4_signal_pass": _flag(a4_signal_pass),
        "a4_reject_code": a4_code, "a4_in_session": _flag(in_session),
        "a4_trades_today": str(strategy.a4.trades_today),
        "a4_material_below_ema50": _flag(
            atr is not None and atr > 0
            and bid.close < view["ema50"] - MATERIAL_EMA50_CLOSE_ATR * atr),
        "a4_pullback_active": _flag(strategy.a4.pullback_active),
        "a4_pullback_low": _num(strategy.a4.pullback_low),
        "a4_pullback_depth_atr": _num(strategy.a4.pullback_max_depth_atr),
        "a4_pullback_bars": str(strategy.a4.pullback_bars),
        "a4_pullback_touch": strategy.a4.pullback_touch,
        "a4_structure_level": _num(strategy.a4.last_broken_structure_level),
        "a4_prior_high": _num(prior_high), "a4_trigger": _num(a4_trigger),
        "a4_stop": _num(a4_stop), "a4_stop_atr": _num(a4_stop_atr),
        "t3_regime": t3_regime, "t3_context_pass": _flag(t3_context),
        "t3_signal_pass": _flag(t3_signal_pass), "t3_reject_code": t3_code,
        "t3_prev_high": _num(t3_high), "t3_prev_low": _num(t3_low),
        "t3_stop_high": _num(stop_high), "t3_stop_low": _num(stop_low),
        "t3_range_atr": _num((bid.high - bid.low) / atr if atr else None),
        "t3_extension_atr": _num(abs(bid.close - view["ema20"]) / atr if atr else None),
        "t3_trigger": _num(t3_trigger), "t3_stop": _num(t3_stop),
        "t3_stop_atr": _num(t3_stop_atr),
        "signal_side": (signal.direction.value if isinstance(signal, Signal) else ""),
        "signal_setup_id": (signal.setup_id if isinstance(signal, Signal) else ""),
        "signal_time_utc": _iso(bid.timestamp + STEP if isinstance(signal, Signal) else None),
        # CREATED / FILLED / EXPIRED / ACTIVE, in the order the twin resolves
        # them: a fill or expiry is recorded on the bar it happens, and a
        # replacement order created on that same bar supersedes the label.
        "pending_status": ("CREATED" if new_pending is not None else
                           "FILLED" if opened is not None else
                           "EXPIRED" if expired else
                           "ACTIVE" if pending is not None else ""),
        "pending_trigger": _num(pending.trigger_price if pending is not None else None),
        "pending_stop": _num(pending.stop_price if pending is not None else None),
        "pending_expiry_utc": _iso(pending.expiry_time if pending is not None else None),
        "entry_time_utc": _iso(opened.entry_time if opened is not None else None),
        "entry_price": _num(opened.entry_price if opened is not None else None),
        "entry_stop": _num(opened.stop_loss if opened is not None else None),
        "entry_target": _num(opened.take_profit if opened is not None else None),
        "exit_time_utc": _iso(closed.exit_time if closed is not None else None),
        "exit_price": _num(closed.exit_price if closed is not None else None),
        "exit_reason": (closed.exit_reason if closed is not None else ""),
        "realized_r": _num(closed.realized_r if closed is not None else None),
        "commission_status": UNVERIFIED, "swap_status": UNVERIFIED,
        "realized_cost_status": UNVERIFIED,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=EXNESS_M15)
    parser.add_argument("--start", default="2026-01-01")
    parser.add_argument("--end", default="2026-03-01")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "reports/validation/python_core_audit.csv")
    parser.add_argument("--spread-source", default="BROKER_NATIVE_PER_BAR")
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args()
    config = BacktestConfig(
        instrument="BTCUSD", broker_profile="EXNESS_STANDARD", strategy_id=STRATEGY_ID,
        timeframe="15m", higher_timeframes=("1h",),
        start_date=pd.Timestamp(args.start, tz="UTC"), end_date=pd.Timestamp(args.end, tz="UTC"),
        dataset_role=DatasetRole.PAPER, spread_source=args.spread_source,
        notes="R4 Stage 1 Python audit export")
    audit = export(args.data, config, args.output, verify=not args.no_verify)
    print(f"{len(audit):,} audit rows -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
