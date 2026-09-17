"""Read-only Setup A chart behavior and feed boundaries."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from engine.models import Direction
from research.exness_setup_a_validation import CaptureSetupA
from services.live_chart_source import (ChartSource, FeedSnapshot, freshness,
                                        latest_completed, latest_window,
                                        load_bitstamp_reference, load_chart_source,
                                        load_exness_history)
from ui.live_chart import (ChartCaptureSetupA, analyze_history, chart_figure,
                           order_levels, signal_markers)


BASE = pd.Timestamp("2026-01-01 00:00:00", tz="UTC")


def bars(count=4):
    return pd.DataFrame({"timestamp": pd.date_range(BASE, periods=count, freq="15min"),
                         "open": [50000. + i for i in range(count)],
                         "high": [50005. + i for i in range(count)],
                         "low": [49995. + i for i in range(count)],
                         "close": [50001. + i for i in range(count)],
                         "volume": [10] * count})


def test_exness_history_loader_keeps_bid_and_bar_min_spread_distinct(tmp_path):
    source = bars(3).rename(columns={"timestamp": "timestamp_utc", "volume": "tick_volume"})
    source["spread_price"] = [10., 11., 12.]
    file = tmp_path / "exness.csv"
    source.to_csv(file, index=False)
    snapshot = load_exness_history(file, BASE + pd.Timedelta(minutes=40))
    assert snapshot.source is ChartSource.EXNESS_HISTORY
    assert len(snapshot.candles) == 2  # third candle is still developing
    assert snapshot.last_bid == source.close.iloc[1]
    assert snapshot.last_ask is None
    assert snapshot.spread == 11.
    assert snapshot.spread_label == "BAR MIN SPREAD"


def test_latest_bar_and_visible_window_selection():
    data = bars(4)
    complete = latest_completed(data, BASE + pd.Timedelta(minutes=45))
    assert list(complete.timestamp) == list(data.timestamp.iloc[:3])
    assert latest_window(data, 100).timestamp.iloc[-1] == data.timestamp.iloc[-1]


def test_live_source_never_falls_back_to_history(tmp_path):
    snapshot = load_chart_source(ChartSource.EXNESS_LIVE,
                                 exness_path=tmp_path / "history.csv")
    assert snapshot.candles.empty
    assert snapshot.status == "EXNESS LIVE CONNECTION — NOT CONNECTED"
    assert freshness(snapshot) == "NOT CONNECTED"


def test_historical_and_live_stale_feed_status():
    old = FeedSnapshot(ChartSource.EXNESS_HISTORY, bars(1), "history")
    assert freshness(old, BASE + pd.Timedelta(hours=2)) == "HISTORICAL · STALE"
    live = FeedSnapshot(ChartSource.EXNESS_LIVE, bars(1), "connected", is_live=True,
                        server_time=BASE)
    assert freshness(live, BASE + pd.Timedelta(hours=1)) == "STALE LIVE FEED"
    assert freshness(live, BASE + pd.Timedelta(seconds=10)) == "LIVE"


def test_bitstamp_is_explicit_reference_feed(tmp_path):
    file = tmp_path / "bitstamp.csv"
    bars(2).to_csv(file, index=False)
    snapshot = load_bitstamp_reference(file, BASE + pd.Timedelta(hours=1))
    assert snapshot.source is ChartSource.BITSTAMP_REFERENCE
    assert snapshot.status == "REFERENCE FEED — NOT EXECUTION FEED"
    assert snapshot.spread_label == "SPREAD UNAVAILABLE"


def test_signal_marker_direction_mapping():
    data = bars(2)
    signals = pd.DataFrame([{"signal_candle_time": BASE, "direction": "LONG"},
                            {"signal_candle_time": BASE + pd.Timedelta(minutes=15),
                             "direction": "SHORT"}])
    marked = signal_markers(signals, data)
    assert marked.marker_price.tolist() == [data.low.iloc[0], data.high.iloc[1]]


def test_structural_stop_and_three_r_target_mapping():
    plan = SimpleNamespace(direction=Direction.LONG, trigger_price=50000.,
                           stop_price=49900., quantity=.1234, planned_risk=12.34)
    result = order_levels(plan, BASE)
    assert result["stop"] == 49900.
    assert result["target"] == 50300.
    assert result["stop_distance"] == 100.
    assert result["rounded_lots"] == .12
    assert result["planned_risk"] == 12.34


def test_frozen_strategy_observer_and_confirmed_h1_causality():
    assert issubclass(ChartCaptureSetupA, CaptureSetupA)
    data = bars(900)
    analysis = analyze_history(data)
    assert len(analysis.candles) == 900
    assert analysis.h1_context["time"] < data.timestamp.iloc[-1].floor("h")
    assert analysis.h1_context["time"] == data.timestamp.iloc[-1].floor("h") - pd.Timedelta(hours=1)
    assert any(row["Rule"] == "Recent prior EMA touch" for row in analysis.rule_status)
    # H1 overlay for the first M15 candle of an hour still points to the prior hour.
    first_new_hour = analysis.overlays.loc[
        analysis.overlays.timestamp.dt.minute.eq(0) & analysis.overlays.h1_time.notna()].iloc[-1]
    assert first_new_hour.h1_time == first_new_hour.timestamp - pd.Timedelta(hours=1)


def test_plotly_candles_and_pending_levels():
    data = bars(900)
    analysis = analyze_history(data)
    analysis.order_levels = {"signal_time": data.timestamp.iloc[-1] + pd.Timedelta(minutes=15),
                             "trigger": 50050., "stop": 49950., "target": 50350.}
    figure = chart_figure(analysis, 100, False, True, True)
    names = [trace.name for trace in figure.data]
    assert "BTCUSDm Bid M15" in names
    assert "EMA20" in names
    assert "H1_EMA200 confirmed" in names
    assert "Structural SL" in names
    assert "Planned 3R TP" in names
    assert len(figure.data[0].x) == 100


def test_live_chart_contains_no_trade_submission_interface():
    root = Path(__file__).resolve().parents[1]
    modules = (root / "ui/live_chart.py", root / "services/live_chart_source.py")
    forbidden = {"order_send", "OrderSend", "PositionClose", "BuyStop", "SellStop"}
    for path in modules:
        tree = ast.parse(path.read_text())
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        assert not called.intersection(forbidden)
