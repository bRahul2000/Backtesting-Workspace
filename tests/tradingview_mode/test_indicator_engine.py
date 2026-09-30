"""The generic indicator engine: every listed indicator works on BTC, gold and synthetic OHLC, presentation
primitives are generic, data requirements are declared (never faked), no lookahead, and the capability matrix is
complete and in sync with docs/INDICATOR_CAPABILITY_MATRIX.json."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from services.market_datasets import EXNESS_BTCUSDM_M15, EXNESS_XAUUSDM_M15, dataset
from strategies.pine_indicators import ATR, EMA, RSI
from ui.tradingview_mode import indicators as engine
from ui.tradingview_mode.component.protocol import validate_payload
from ui.tradingview_mode.component.state import IndicatorInstance
from ui.tradingview_mode.component.terminal import indicator_catalog, indicator_payload, volume_kind
from utils.data_validation import load_ohlcv_csv

from .pine.test_gold_range_hunter import _truncated

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "docs" / "INDICATOR_CAPABILITY_MATRIX.json"
LISTED = engine.CHARTABLE


def synthetic(n=1500, seed=7, price=100.0, step=900):
    rng = np.random.default_rng(seed)
    close = price * np.exp(np.cumsum(rng.normal(0, 0.002, n)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.001, n)) * close
    return pd.DataFrame({"timestamp": pd.date_range("2026-01-05", periods=n, freq=f"{step}s", tz="UTC"),
                         "open": open_, "high": np.maximum(open_, close) + spread,
                         "low": np.minimum(open_, close) - spread, "close": close,
                         "volume": rng.integers(1, 500, n).astype(float)})


@pytest.fixture(scope="module")
def markets():
    btc = load_ohlcv_csv(dataset(EXNESS_BTCUSDM_M15).path).tail(3000).reset_index(drop=True)
    gold = _truncated(dataset(EXNESS_XAUUSDM_M15).path).tail(3000).reset_index(drop=True)   # never the sealed window
    return {"btc": btc, "gold": gold, "synthetic": synthetic()}


def payload_item(frame, key, params=None, volume="traded"):
    spec = engine.INDICATORS[key]
    instance = IndicatorInstance(f"{key}-1", key, engine.validate_params(key, params), True, "#f5a623")
    times = [int(t.timestamp()) for t in frame["timestamp"]]
    overlays, panes, notices = indicator_payload(frame, times, (instance,),
                                                 engine.DataContext(volume=volume, timeframe_seconds=900))
    items = overlays if spec.placement == "overlay" else panes
    return items[0], notices


# ---- every listed indicator works everywhere it should ------------------------------------------------------------

@pytest.mark.parametrize("market", ["btc", "gold", "synthetic"])
@pytest.mark.parametrize("key", LISTED)
def test_every_listed_indicator_draws_on_every_market(markets, market, key):
    frame = markets[market]
    item, notices = payload_item(frame, key)
    assert item["status"] in ("ok", "limited"), (item["note"], notices)
    assert item["series"] or item["markers"], f"{key} on {market} drew nothing"
    for series in item["series"]:
        values = np.array([p["value"] for p in series["data"]])
        assert np.isfinite(values).all() and len(values) > len(frame) * 0.8
    spec = engine.INDICATORS[key]
    assert {s["name"] for s in item["series"]} == {p.key for p in spec.plots}
    assert item["label"].startswith(spec.display_name)


@pytest.mark.parametrize("key", ["ema", "sma", "wma", "bb", "keltner", "donchian", "atr", "macd"])
def test_price_indicators_scale_with_price_and_oscillators_do_not(markets, key):
    """Market independence: the same shape at a different price level gives proportional results."""
    base = markets["synthetic"]
    scaled = base.assign(**{c: base[c] * 37.5 for c in ("open", "high", "low", "close")})
    one, two = engine.compute(base, key).series, engine.compute(scaled, key).series
    for name in one:
        # MACD is a difference of averages (values near zero): compare with an absolute tolerance at price scale
        np.testing.assert_allclose(two[name].to_numpy() / 37.5, one[name].to_numpy(), rtol=1e-9, atol=1e-9,
                                   equal_nan=True)


@pytest.mark.parametrize("key", ["rsi", "stoch"])
def test_oscillators_are_scale_invariant(markets, key):
    base = markets["synthetic"]
    scaled = base.assign(**{c: base[c] * 1234.0 for c in ("open", "high", "low", "close")})
    one, two = engine.compute(base, key).series, engine.compute(scaled, key).series
    for name in one:
        np.testing.assert_allclose(two[name].to_numpy(), one[name].to_numpy(), rtol=1e-9, atol=1e-9, equal_nan=True)


def test_ema_rsi_atr_agree_with_the_independent_pine_implementations(markets):
    frame = markets["btc"]
    ema_ref, rsi_ref, atr_ref = EMA(20), RSI(14), ATR(14)
    from strategies.pine_indicators import Candle
    ema_v, rsi_v, atr_v = [], [], []
    for row in frame.itertuples():
        ema_v.append(ema_ref.update(row.close))
        rsi_v.append(rsi_ref.update(row.close))
        atr_v.append(atr_ref.update(Candle(row.timestamp, row.open, row.high, row.low, row.close, row.volume)))
    tail = slice(-500, None)
    np.testing.assert_allclose(engine.compute(frame, "ema").series["value"].to_numpy()[tail], ema_v[tail], rtol=1e-12)
    np.testing.assert_allclose(engine.compute(frame, "rsi").series["value"].to_numpy()[tail], rsi_v[tail], rtol=1e-6)
    np.testing.assert_allclose(engine.compute(frame, "atr").series["value"].to_numpy()[tail], atr_v[tail], rtol=1e-6)


# ---- presentation primitives -------------------------------------------------------------------------------------

def test_overlay_and_pane_primitives(markets):
    frame = markets["synthetic"]
    ema, _ = payload_item(frame, "ema")
    assert ema["series"][0]["type"] == "line" and ema["series"][0]["width"] == 2 and not ema["levels"]
    bb, _ = payload_item(frame, "bb")                                        # bands + fill between two outputs
    assert [s["name"] for s in bb["series"]] == ["basis", "upper", "lower"] and bb["series"][0]["style"] == "dashed"
    assert bb["fills"] == [{"upper": "upper", "lower": "lower", "color": "rgba(74,163,255,0.08)"}]
    rsi, _ = payload_item(frame, "rsi")                                      # pane line + levels + level fill
    assert [lv["value"] for lv in rsi["levels"]] == [70.0, 50.0, 30.0] and rsi["fills"][0]["upper"] == 70
    macd, _ = payload_item(frame, "macd")                                    # multiple pane outputs + histogram
    hist = next(s for s in macd["series"] if s["type"] == "histogram")
    assert {p["color"] for p in hist["data"]} <= {"#26a69a", "#b2dfdb", "#ffcdd2", "#ef5350"}
    assert len({p["color"] for p in hist["data"]}) == 4                      # conditional (4-colour) histogram
    stoch, _ = payload_item(frame, "stoch")
    assert [s["name"] for s in stoch["series"]] == ["k", "d"] and [lv["value"] for lv in stoch["levels"]] == [80.0, 20.0]
    st, _ = payload_item(frame, "supertrend")                                # conditional line colour + markers
    assert {p["color"] for p in st["series"][0]["data"]} == {"#26a69a", "#ef5350"} and st["markers"]
    pivots, _ = payload_item(frame, "pivots")                                # markers only
    assert not pivots["series"] and pivots["markers"]
    assert {m["position"] for m in pivots["markers"]} == {"aboveBar", "belowBar"}


def test_pivots_never_mark_the_unconfirmed_newest_bars(markets):
    frame = markets["synthetic"]
    item, _ = payload_item(frame, "pivots", {"left": 5, "right": 7})
    last_allowed = int(frame["timestamp"].iloc[-8].timestamp())
    assert max(m["time"] for m in item["markers"]) <= last_allowed


def test_multiple_instances_of_one_indicator_are_independent(markets):
    frame = markets["synthetic"]
    times = [int(t.timestamp()) for t in frame["timestamp"]]
    instances = (IndicatorInstance("ema-1", "ema", engine.validate_params("ema", {"length": 20}), True, "#f5a623"),
                 IndicatorInstance("ema-2", "ema", engine.validate_params("ema", {"length": 50}), False, "#4aa3ff"))
    overlays, _, _ = indicator_payload(frame, times, instances)
    assert [(o["id"], o["label"], o["visible"]) for o in overlays] == [("ema-1", "EMA 20", True), ("ema-2", "EMA 50", False)]
    assert overlays[0]["series"][0]["data"] != overlays[1]["series"][0]["data"]
    assert overlays[1]["series"][0]["color"] == "#4aa3ff"


# ---- data requirements -------------------------------------------------------------------------------------------

def test_volume_requirements_are_declared_and_never_faked(markets):
    frame = markets["btc"]
    ok, _ = payload_item(frame, "vwap", volume="traded")
    assert ok["status"] == "ok" and ok["series"]
    limited, _ = payload_item(frame, "vwap", volume="tick")
    assert limited["status"] == "limited" and "TICK volume" in limited["note"] and limited["series"]
    none, notices = payload_item(frame.assign(volume=0.0), "vwap", volume="none")
    assert none["status"] == "unavailable" and none["series"] == [] and "no" in none["note"].lower()
    assert any("VWAP" in n["message"] for n in notices)
    # an OHLC-only indicator is unaffected by the missing volume
    assert payload_item(frame.assign(volume=0.0), "ema", volume="none")[0]["status"] == "ok"
    assert volume_kind("Exness Technologies Ltd", frame) == "tick"
    assert volume_kind("Bitstamp (public exchange API)", frame) == "traded"
    assert volume_kind("Binance Futures", frame.assign(volume=0.0)) == "none"


def test_menu_marks_unusable_indicators_instead_of_offering_them():
    catalog = {item["key"]: item for item in indicator_catalog(engine.DataContext(volume="none"))}
    assert catalog["vwap"]["status"] == "unavailable" and catalog["vwap"]["note"]
    assert all(catalog[key]["status"] == "ok" for key in LISTED if key != "vwap")
    assert set(catalog) == set(LISTED) and "volume" not in catalog
    assert all(item["params"] is not None for item in catalog.values())


def test_vwap_anchors_reset_on_their_session(markets):
    frame = markets["synthetic"]
    for anchor, key in (("day", frame["timestamp"].dt.date), ("week", frame["timestamp"].dt.isocalendar().week)):
        value = engine.compute(frame, "vwap", {"anchor": anchor}).series["value"]
        first = frame.groupby(key.values).head(1).index
        typical = (frame["high"] + frame["low"] + frame["close"]) / 3
        np.testing.assert_allclose(value[first].to_numpy(), typical[first].to_numpy())


# ---- higher timeframe input: closed bars only --------------------------------------------------------------------

def test_higher_timeframe_values_appear_only_after_the_higher_bar_closes(markets):
    frame = markets["synthetic"]                     # 15m bars from Monday 00:00 UTC
    htf = engine.compute(frame, "ema", {"length": 3, "timeframe": "1h"}).series["value"]
    hourly = frame.set_index("timestamp")["close"].resample("1h").last()
    expected_hourly = hourly.ewm(span=3, adjust=False, min_periods=3).mean()
    for i in (40, 41, 42, 43, 44):                   # bars 40-43 are 10:00-10:45, bar 44 opens 11:00
        stamp = frame["timestamp"].iloc[i]
        closed = expected_hourly[expected_hourly.index + pd.Timedelta(hours=1) <= stamp + pd.Timedelta(minutes=15)]
        assert htf.iloc[i] == pytest.approx(closed.iloc[-1])
    # changing the future never changes the past
    changed = frame.copy()
    changed.loc[1000:, ["open", "high", "low", "close"]] *= 1.5
    again = engine.compute(changed, "ema", {"length": 3, "timeframe": "1h"}).series["value"]
    np.testing.assert_allclose(again.iloc[:1000].to_numpy(), htf.iloc[:1000].to_numpy(), equal_nan=True)


def test_higher_timeframe_must_be_a_multiple_of_the_chart():
    frame = synthetic(step=3600)
    with pytest.raises(ValueError, match="multiple"):
        engine.compute(frame, "ema", {"timeframe": "30m"}, engine.DataContext(timeframe_seconds=3600))


# ---- params, payload validity, matrix ----------------------------------------------------------------------------

@pytest.mark.parametrize("key, params, message", [
    ("macd", {"fast": 30, "slow": 26}, "shorter"), ("ema", {"length": 0}, "between"), ("bb", {"stddev": 99}, "between"),
    ("vwap", {"anchor": "year"}, "one of"), ("ema", {"colour": 1}, "unknown"), ("stoch", {"smooth_k": 1.5}, "whole"),
])
def test_invalid_parameters_are_rejected(key, params, message):
    with pytest.raises(ValueError, match=message):
        engine.validate_params(key, params)


def test_payload_with_every_primitive_validates(markets):
    """The full terminal payload with one of each indicator passes the frontend contract."""
    from .test_component_terminal import payload_for
    instances = tuple(IndicatorInstance(f"{key}-{n}", key, engine.validate_params(key, {}), n % 2 == 0, "#f5a623")
                      for n, key in enumerate(LISTED, start=1))
    payload = payload_for(indicators=instances, data=markets["synthetic"])
    validate_payload(payload)
    assert {i["key"] for i in payload["overlays"] + payload["panes"]} == set(LISTED)


def test_capability_matrix_covers_every_listed_indicator_and_is_committed():
    rows = engine.capability_matrix()
    assert [row["key"] for row in rows] == list(LISTED)
    assert all(row["implementation_status"] in ("WORKING", "DISABLED") for row in rows)
    assert all(row["implementation_status"] == "WORKING" or row["disabled_reason"] for row in rows)
    committed = json.loads(MATRIX.read_text())
    assert committed == rows, "regenerate: python -m ui.tradingview_mode.indicator_matrix"
