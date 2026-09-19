"""Read-only BTC Setup A V1 chart and future MT5 feed presentation."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine.backtester import run_backtest
from engine.execution import create_pending_order
from engine.models import Signal
from research.exness_setup_a_validation import (CaptureSetupA, PARAMS, SETTINGS,
                                                executable_lots, setup_a_warmup)
from services.live_chart_source import (ChartSource, FeedSnapshot, freshness,
                                        latest_window, load_chart_source)
from strategies.btc_v2_setup_a import STAGES, SetupAObservation, evaluate_setup_a
from utils.data_validation import continuous_segments


STEP = pd.Timedelta(minutes=15)
FREEZE_HASH = "b9c1f07ed3ec4b068f65d0ede59e6a94dc6985c4ad8824ae606c168c7f33b649"
COLORS = {"LONG": "#2dd4bf", "SHORT": "#fb7185"}


class ChartCaptureSetupA(CaptureSetupA):
    """Observe frozen decisions; `super().on_candle` remains authoritative."""

    def __init__(self, visible_start: pd.Timestamp):
        self.visible_start = visible_start
        super().__init__(PARAMS)

    def reset(self) -> None:
        super().reset()
        self.overlay_rows: list[dict] = []
        self.order_plans: dict[pd.Timestamp, object] = {}
        self.latest_observation: SetupAObservation | None = None
        self.latest_counters: Counter = Counter()
        self.latest_action = None
        self.latest_lock_reason: str | None = None
        self.latest_state = None

    def on_candle(self, candle):
        prior_touch = (None if self._last_touch_index is None else
                       self._bar_index - self._last_touch_index)
        state = self.execution_state
        action = super().on_candle(candle)
        h1 = self.h1.confirmed  # previous fully confirmed H1 for this M15 bar
        gain, loss = self.rsi._gain.value, self.rsi._loss.value
        rsi = (None if gain is None or loss is None else
               100. if loss == 0 and gain > 0 else
               50. if loss == 0 else 100. - 100. / (1. + gain / loss))
        obs = SetupAObservation(candle, h1, self.fast.value, self.slow.value,
                                self.dmi._adx.value, rsi, self.atr._average.value,
                                prior_touch)
        self.latest_observation = obs
        self.latest_counters = Counter()
        evaluate_setup_a(obs, self.params, self.latest_counters)
        self.latest_action = action
        self.latest_lock_reason = self.risk.lock_reason
        self.latest_state = state
        if candle.timestamp >= self.visible_start:
            self.overlay_rows.append({"timestamp": candle.timestamp,
                                      "ema20": self.fast.value, "ema50": self.slow.value,
                                      "h1_time": h1.hour, "h1_close": h1.close,
                                      "h1_ema50": h1.fast_ema,
                                      "h1_ema200": h1.slow_ema,
                                      "h1_ema200_past": h1.slow_ema_lookback})
        if isinstance(action, Signal) and state is not None:
            plan = create_pending_order(action, candle, self._bar_index - 1,
                                        state.balance, SETTINGS)
            self.order_plans[candle.timestamp + STEP] = plan
        return action


@dataclass
class ChartAnalysis:
    candles: pd.DataFrame
    overlays: pd.DataFrame
    signals: pd.DataFrame
    trades: list
    rule_status: list[dict]
    setup_state: str
    final_status: str
    order_levels: dict | None
    h1_context: dict
    segment_start: pd.Timestamp | None


def rule_rows(strategy: ChartCaptureSetupA) -> list[dict]:
    obs = strategy.latest_observation
    if obs is None:
        return []
    stamp = obs.candle.timestamp
    allowed_day = stamp.weekday() in strategy.params.allowed_days
    session = strategy.params.session_start <= stamp.time() < strategy.params.session_end
    permission = strategy.latest_lock_reason is None
    state = strategy.latest_state
    free = state is not None and state.position is None and state.pending_order is None
    rows = [
        {"Rule": "UTC weekday", "Status": "PASS" if allowed_day else "FAIL"},
        {"Rule": "UTC session 07:00–20:00", "Status": "PASS" if session else "FAIL"},
        {"Rule": "Daily/monthly trade permission", "Status": "PASS" if permission else "FAIL"},
        {"Rule": "One own order or position", "Status": "PASS" if free else "FAIL"},
    ]
    for stage in STAGES:
        if stage in ("Eligible candles", "Final Long Signals", "Final Short Signals"):
            continue
        if strategy.latest_counters[stage]:
            status = "PASS"
        elif (strategy.latest_counters[f"Failed: {stage}"] or
              strategy.latest_counters[f"Failed: {stage} (invalid price)"]):
            status = "FAIL"
        else:
            status = "N/A"
        rows.append({"Rule": stage, "Status": status})
    return rows


def signal_markers(signals: pd.DataFrame, candles: pd.DataFrame) -> pd.DataFrame:
    if signals.empty or candles.empty:
        return pd.DataFrame(columns=["signal_candle_time", "direction", "marker_price"])
    prices = candles.set_index("timestamp")
    visible = signals.loc[signals.signal_candle_time.isin(prices.index)].copy()
    if visible.empty:
        return pd.DataFrame(columns=["signal_candle_time", "direction", "marker_price"])
    visible["marker_price"] = [float(prices.loc[t, "low"] if d == "LONG" else
                                     prices.loc[t, "high"])
                               for t, d in zip(visible.signal_candle_time, visible.direction)]
    return visible


def order_levels(plan, signal_time: pd.Timestamp) -> dict:
    distance = abs(plan.trigger_price - plan.stop_price)
    direction = plan.direction.value
    target = plan.trigger_price + (1 if direction == "LONG" else -1) * 3.0 * distance
    lots = executable_lots(float(plan.quantity))
    return {"direction": direction, "signal_time": signal_time,
            "trigger": float(plan.trigger_price), "stop": float(plan.stop_price),
            "target": float(target), "stop_distance": float(distance),
            "rr": 3.0, "theoretical_btc": float(plan.quantity),
            "rounded_lots": lots, "planned_risk": float(plan.planned_risk),
            "executable_risk": lots * distance}


def analyze_history(candles: pd.DataFrame) -> ChartAnalysis:
    if candles.empty:
        return ChartAnalysis(candles.copy(), pd.DataFrame(), pd.DataFrame(), [], [],
                             "NO SETUP", "NO DATA", None, {}, None)
    segments = continuous_segments(candles)
    segment = segments[-1]
    fragment = candles.loc[candles.timestamp.between(segment.start, segment.end)].reset_index(drop=True)
    _, first_search = setup_a_warmup(PARAMS, segment.start)
    visible_start = fragment.timestamp.iloc[max(0, len(fragment) - 1000)]
    strategy = ChartCaptureSetupA(visible_start)
    if fragment.timestamp.iloc[-1] < first_search:
        # Run warm-up through frozen strategy even when the segment is too short.
        return ChartAnalysis(fragment, pd.DataFrame(), pd.DataFrame(), [], [],
                             "NO SETUP", "INDICATORS WARMING", None, {}, segment.start)
    engine_data = fragment.rename(columns={"tick_volume": "volume"}) if "tick_volume" in fragment else fragment
    result = run_backtest(engine_data, strategy, SETTINGS, trade_start=first_search)
    signal_frame = pd.DataFrame(strategy.captured_signals)
    latest_plan = None
    setup_state = "NO SETUP"
    if result.open_position is not None:
        setup_state = "POSITION OPEN"
        position = result.open_position
        latest_plan = {"direction": position.direction.value,
                       "signal_time": position.signal_time,
                       "trigger": position.pending_trigger_price or position.entry_price,
                       "stop": position.stop_loss, "target": position.take_profit,
                       "stop_distance": abs(position.entry_price-position.stop_loss),
                       "rr": 3.0, "theoretical_btc": position.quantity,
                       "rounded_lots": executable_lots(position.quantity),
                       "planned_risk": position.initial_risk,
                       "executable_risk": executable_lots(position.quantity) *
                       abs(position.entry_price-position.stop_loss)}
    elif result.order_events:
        last = result.order_events[-1]
        if last.status == "cancelled" and last.cancel_reason == "Backtest range ended.":
            setup_state = "PENDING LONG" if last.direction.value == "LONG" else "PENDING SHORT"
            plan = strategy.order_plans.get(last.signal_time)
            if plan is not None:
                latest_plan = order_levels(plan, last.signal_time)
    if setup_state == "NO SETUP" and isinstance(strategy.latest_action, Signal):
        setup_state = "LONG CANDIDATE" if strategy.latest_action.direction.value == "LONG" else "SHORT CANDIDATE"
    final = ("WAITING FOR LONG TRIGGER" if setup_state == "PENDING LONG" else
             "WAITING FOR SHORT TRIGGER" if setup_state == "PENDING SHORT" else
             "POSITION OPEN" if setup_state == "POSITION OPEN" else
             "LONG SETUP QUALIFIED" if setup_state == "LONG CANDIDATE" else
             "SHORT SETUP QUALIFIED" if setup_state == "SHORT CANDIDATE" else
             "NO VALID SETUP")
    h1 = strategy.h1.confirmed
    context = {"time": h1.hour, "close": h1.close, "ema50": h1.fast_ema,
               "ema200": h1.slow_ema, "ema200_past": h1.slow_ema_lookback,
               "trend": "LONG" if h1.long else "SHORT" if h1.short else "NEUTRAL"}
    return ChartAnalysis(fragment, pd.DataFrame(strategy.overlay_rows), signal_frame,
                         list(result.trades), rule_rows(strategy), setup_state, final,
                         latest_plan, context, segment.start)


@st.cache_data(show_spinner=False)
def _cached_history(source_name: str, path: str, modified_ns: int) -> FeedSnapshot:
    del modified_ns
    source = ChartSource(source_name)
    if source is ChartSource.EXNESS_HISTORY:
        return load_chart_source(source, exness_path=Path(path))
    return load_chart_source(source, bitstamp_path=Path(path))


@st.cache_data(show_spinner=False)
def _cached_analysis(source_name: str, path: str, modified_ns: int,
                     last_complete_time: str) -> ChartAnalysis:
    snap = _cached_history(source_name, path, modified_ns)
    completed = snap.candles.loc[snap.candles.timestamp <= pd.Timestamp(last_complete_time)]
    return analyze_history(completed)


def chart_figure(analysis: ChartAnalysis, count: int, show_trades: bool,
                 show_m15_ema: bool, show_h1_ema: bool) -> go.Figure:
    window = latest_window(analysis.candles, count)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=window.timestamp, open=window.open, high=window.high,
                                 low=window.low, close=window.close,
                                 name="BTCUSDm Bid M15",
                                 increasing_line_color="#2dd4bf",
                                 decreasing_line_color="#fb7185"))
    if not analysis.overlays.empty:
        overlay = analysis.overlays.loc[analysis.overlays.timestamp.isin(window.timestamp)]
        if show_m15_ema:
            for name, color in (("ema20", "#60a5fa"), ("ema50", "#fbbf24")):
                fig.add_trace(go.Scatter(x=overlay.timestamp, y=overlay[name],
                                         name=name.upper(), mode="lines",
                                         line={"color": color, "width": 1.5}))
        if show_h1_ema:
            for name, color in (("h1_ema50", "#a78bfa"), ("h1_ema200", "#f97316")):
                fig.add_trace(go.Scatter(x=overlay.timestamp, y=overlay[name],
                                         name=name.upper() + " confirmed", mode="lines",
                                         line={"color": color, "width": 1.2, "dash": "dot"}))
    markers = signal_markers(analysis.signals, window)
    for direction, symbol in (("LONG", "triangle-up"), ("SHORT", "triangle-down")):
        part = markers.loc[markers.direction.eq(direction)] if not markers.empty else markers
        if not part.empty:
            fig.add_trace(go.Scatter(x=part.signal_candle_time, y=part.marker_price,
                                     mode="markers", name=f"Setup A {direction} signal",
                                     marker={"symbol": symbol, "size": 13,
                                             "color": COLORS[direction]},
                                     hovertext=[f"{direction} · trigger {v:.2f} · SL {s:.2f}"
                                                for v, s in zip(part.trigger, part.structural_stop)]))
    levels = analysis.order_levels
    if levels is not None and levels["signal_time"] >= window.timestamp.iloc[0]:
        left = levels["signal_time"] - STEP
        right = levels["signal_time"] + 2 * STEP
        for label, price, color, dash in (("Trigger", levels["trigger"], "#60a5fa", "solid"),
                                          ("Structural SL", levels["stop"], "#fb7185", "dash"),
                                          ("Planned 3R TP", levels["target"], "#2dd4bf", "dash")):
            fig.add_trace(go.Scatter(x=[left, right], y=[price, price], mode="lines",
                                     name=label, line={"color": color, "width": 1.5,
                                                      "dash": dash}))
    if show_trades:
        visible_trades = [t for t in analysis.trades if
                          t.entry_time >= window.timestamp.iloc[0] or
                          t.exit_time >= window.timestamp.iloc[0]]
        for direction, color in COLORS.items():
            chosen = [t for t in visible_trades if t.direction.value == direction]
            if chosen:
                fig.add_trace(go.Scatter(x=[t.entry_time for t in chosen],
                                         y=[t.entry_price for t in chosen], mode="markers",
                                         name=f"{direction} fill",
                                         marker={"symbol": "circle", "size": 9, "color": color},
                                         hovertext=[f"Trade {t.trade_id} · SL {t.stop_loss:.2f} · TP {t.take_profit:.2f}"
                                                    for t in chosen]))
        if visible_trades:
            fig.add_trace(go.Scatter(x=[t.exit_time for t in visible_trades],
                                     y=[t.exit_price for t in visible_trades], mode="markers",
                                     name="Exit", marker={"symbol": "x", "size": 10,
                                                          "color": "#e5e7eb"},
                                     hovertext=[f"{t.exit_reason} · {t.r_multiple:+.2f}R"
                                                for t in visible_trades]))
    fig.update_layout(template="plotly_dark", height=650, margin=dict(l=8,r=8,t=26,b=8),
                      hovermode="x unified", dragmode="pan",
                      xaxis={"title": "UTC", "rangeslider": {"visible": False}},
                      yaxis={"title": "USD per BTC", "side": "right"},
                      legend={"orientation": "h", "y": 1.08},
                      modebar_add=["drawline", "eraseshape"])
    return fig


def _render_loaded(snapshot: FeedSnapshot, count: int, show_trades: bool,
                   show_m15: bool, show_h1: bool, path: Path) -> None:
    stamp = snapshot.candles.timestamp.iloc[-1]
    analysis = _cached_analysis(snapshot.source.value, str(path), path.stat().st_mtime_ns,
                                stamp.isoformat())
    source_name = ("Exness history" if snapshot.source is ChartSource.EXNESS_HISTORY else
                   "Bitstamp reference")
    metrics = [
        ("Symbol", "BTCUSDm" if snapshot.source is ChartSource.EXNESS_HISTORY else "BTC/USD"),
        ("Timeframe", "M15"), ("Strategy", "BTC Setup A V1"),
        ("Freeze status", "RESEARCH FROZEN"), ("Data source", source_name),
        ("Setup state", analysis.setup_state),
        ("Last candle UTC", stamp.strftime("%Y-%m-%d %H:%M")),
        ("Feed freshness", freshness(snapshot)),
        ("Last Bid", f"${snapshot.last_bid:,.2f}" if snapshot.last_bid is not None else "—"),
        ("Last Ask", f"${snapshot.last_ask:,.2f}" if snapshot.last_ask is not None else "—"),
        (snapshot.spread_label,
         f"${snapshot.spread:,.2f}" if snapshot.spread is not None else "—"),
        ("M15 candle status", "LAST COMPLETED · HISTORICAL"),
    ]
    for offset in (0, 4, 8):
        for column, (label, value) in zip(st.columns(4), metrics[offset:offset + 4]):
            column.metric(label, value)
    st.caption("Historical replay only. Markers and pending levels are theoretical; no broker order is submitted.")
    st.plotly_chart(chart_figure(analysis, count, show_trades, show_m15, show_h1),
                    use_container_width=True, config={"scrollZoom": True, "displaylogo": False})
    left, middle, right = st.columns([1.25, 1, 1])
    with left:
        st.subheader("Setup A rule status")
        st.caption("Latest completed M15 candle · frozen evaluator stages")
        if analysis.rule_status:
            st.dataframe(pd.DataFrame(analysis.rule_status), use_container_width=True, hide_index=True,
                         height=510)
        else:
            st.caption("Indicator warm-up is incomplete for this segment.")
        st.markdown(f"**FINAL STATUS: {analysis.final_status}**")
    with middle:
        st.subheader("Order levels")
        levels = analysis.order_levels
        if levels is None:
            st.caption("No active historical setup or position at the final candle.")
        else:
            st.caption("Theoretical research values · READ ONLY")
            data = {"Direction": levels["direction"],
                    "Signal candle UTC": str(levels["signal_time"] - STEP),
                    "Pending trigger": f"${levels['trigger']:,.2f}",
                    "Structural SL": f"${levels['stop']:,.2f}",
                    "Planned 3R TP": f"${levels['target']:,.2f}",
                    "Stop distance": f"${levels['stop_distance']:,.2f}",
                    "Planned R:R": "3:1",
                    "Theoretical BTC quantity": f"{levels['theoretical_btc']:.6f}",
                    "Exness rounded lot": f"{levels['rounded_lots']:.2f}",
                    "Planned risk": f"${levels['planned_risk']:,.2f}"}
            st.dataframe(pd.DataFrame(data.items(), columns=["Field", "Value"]),
                         use_container_width=True, hide_index=True)
    with right:
        st.subheader("Confirmed H1 context")
        h1 = analysis.h1_context
        if not h1 or h1["time"] is None:
            st.caption("Waiting for a fully confirmed H1 candle.")
        else:
            st.metric("Last confirmed H1 UTC", str(h1["time"]))
            st.metric("H1 trend", h1["trend"])
            st.caption(f"Close ${h1['close']:,.2f} · EMA50 ${h1['ema50']:,.2f} · "
                       f"EMA200 ${h1['ema200']:,.2f} · EMA200 five H1 ago "
                       f"${h1['ema200_past']:,.2f}" if h1["ema200_past"] is not None else
                       "EMA200 slope warm-up incomplete")
        st.subheader("Python vs MT5")
        st.caption("MT5 EA NOT CONNECTED")
        st.caption("Latest Python decision is displayed above. Comparison begins only after an MT5 decision feed is connected.")


@st.fragment(run_every="10s")
def _render_live_unconnected() -> None:
    snapshot = load_chart_source(ChartSource.EXNESS_LIVE)
    st.warning(snapshot.status)
    st.caption("No live Bid/Ask, candle countdown, or Python versus MT5 decision is available. "
               "The chart will not substitute Bitstamp or historical Exness data.")
    st.metric("Python vs MT5", "MT5 EA NOT CONNECTED")


def render_live_chart() -> None:
    st.title("BTC Setup A V1 · Live Chart")
    st.caption(f"RESEARCH FROZEN · VIEW ONLY · Freeze {FREEZE_HASH}")
    selectors = st.columns([2, 1])
    source = ChartSource(selectors[0].selectbox("Data source", [s.value for s in ChartSource],
                                               index=0, key="live_chart_source"))
    count = selectors[1].selectbox("Visible M15 candles", [100, 200, 300, 500, 1000],
                                   index=2, key="live_chart_count")
    toggles = st.columns(3)
    show_trades = toggles[0].toggle("Completed trades", value=False,
                                    key="live_chart_trades")
    show_m15 = toggles[1].toggle("M15 EMA20 / EMA50", value=True,
                                 key="live_chart_m15_ema")
    show_h1 = toggles[2].toggle("Confirmed H1 EMAs", value=False,
                                key="live_chart_h1_ema")
    if source is ChartSource.EXNESS_LIVE:
        _render_live_unconnected()
        return
    path = (Path(__file__).resolve().parents[1] / "data/exness/processed/btcusdm_m15.csv"
            if source is ChartSource.EXNESS_HISTORY else
            Path(__file__).resolve().parents[1] / "data/btcusd_15m.csv")
    if not path.exists():
        st.warning(f"{source.value} data file is unavailable: {path}")
        return
    snapshot = _cached_history(source.value, str(path), path.stat().st_mtime_ns)
    if snapshot.candles.empty:
        st.warning(snapshot.status)
        return
    if source is ChartSource.BITSTAMP_REFERENCE:
        st.info("REFERENCE FEED — NOT EXECUTION FEED. Setup A markers use Bitstamp candles only for comparison.")
    _render_loaded(snapshot, count, show_trades, show_m15, show_h1, path)
