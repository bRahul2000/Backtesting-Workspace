"""Feed comparison lab (research/feed_comparison): deterministic, no network."""
import hashlib
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

from research.feed_comparison import metrics as M
from research.feed_comparison import thresholds as TH
from research.feed_comparison.compare_feeds import analyse

T0 = pd.Timestamp("2026-06-01 00:00", tz="UTC")
S = 900


def feed(closes, start=T0, seconds=S, spread=1.0, volume=10.0, drop=()):
    closes = np.asarray(closes, dtype=float)
    opens = np.r_[closes[0], closes[:-1]]
    frame = pd.DataFrame({
        "timestamp": [start + pd.Timedelta(seconds=seconds * i) for i in range(len(closes))],
        "open": opens, "high": np.maximum(opens, closes) + spread, "low": np.minimum(opens, closes) - spread,
        "close": closes, "volume": volume,
    })
    return frame.drop(index=list(drop)).reset_index(drop=True)


def walk(n, seed=1, start=100.0):
    rng = np.random.default_rng(seed)
    return start + np.cumsum(rng.normal(0, 1, n))


# ---- UTC matching, duplicates, missing candles, overlap, no interpolation -------------------------

def test_feeds_must_be_utc_unique_and_on_the_grid():
    good = feed(walk(10))
    M.validate_feed(good, S, "ok")
    naive = good.assign(timestamp=good["timestamp"].dt.tz_localize(None))
    with pytest.raises(M.FeedError, match="UTC"):
        M.validate_feed(naive, S, "naive")
    with pytest.raises(M.FeedError, match="UTC"):
        M.validate_feed(good.assign(timestamp=good["timestamp"].dt.tz_convert("Asia/Kolkata")), S, "ist")
    with pytest.raises(M.FeedError, match="duplicate"):
        M.validate_feed(pd.concat([good, good.iloc[[3]]]).sort_values("timestamp"), S, "dup")
    with pytest.raises(M.FeedError, match="grid"):
        M.validate_feed(good.assign(timestamp=good["timestamp"] + pd.Timedelta(minutes=1)), S, "offgrid")


def test_matching_uses_identical_timestamps_in_the_overlap_only():
    b = feed(walk(100), start=T0)
    e = feed(walk(100, seed=2), start=T0 + pd.Timedelta(seconds=20 * S), drop=(5, 6, 7))
    m = M.match(b, e, S)
    c = m.coverage
    assert c["overlap_start"] == (T0 + pd.Timedelta(seconds=20 * S)).isoformat()
    assert c["overlap_end"] == b["timestamp"].iloc[-1].isoformat()
    assert c["binance_bars"] == 80 and c["exness_bars"] == 77 and c["matched_bars"] == 77
    assert c["unmatched_binance"] == 3 and c["unmatched_exness"] == 0
    # No interpolation / fill: the missing Exness candles are simply absent, values untouched.
    assert not m.frame["timestamp"].isin(e["timestamp"].iloc[[]]).any()
    assert len(m.frame) == len(set(b["timestamp"]) & set(e["timestamp"]))
    row = m.frame.iloc[10]
    source = e.set_index("timestamp").loc[row["timestamp"]]
    assert row["e_close"] == source["close"] and row["e_high"] == source["high"]
    with pytest.raises(M.FeedError, match="overlap"):
        M.match(b, feed(walk(5), start=T0 + pd.Timedelta(days=30)), S)


# ---- offsets and returns ----------------------------------------------------------------------------

def test_price_offsets_and_return_correlation():
    closes = walk(300)
    b, e = feed(closes + 5.0), feed(closes)
    m = M.match(b, e, S).frame
    off = M.price_offsets(m)
    assert off["close"]["absolute"]["median"] == pytest.approx(5.0) and off["close"]["absolute"]["std"] == pytest.approx(0.0)
    rc = M.return_correlations(M.match(feed(closes), feed(closes), S).frame, S)
    assert rc["1_bar"]["pearson"] == pytest.approx(1.0) and rc["5_bar"]["spearman"] == pytest.approx(1.0)
    assert rc["1_bar"]["pairs"] == 299 and rc["3_bar"]["pairs"] == 297
    gappy = M.match(feed(closes), feed(closes, drop=(100,)), S).frame
    assert M.return_correlations(gappy, S)["1_bar"]["pairs"] == 297  # no return across the missing candle
    opposite = M.match(feed(closes), feed(2 * closes[0] - closes + 50), S).frame
    assert M.return_correlations(opposite, S)["1_bar"]["pearson"] < -0.95  # mirrored path (log returns: not exactly -1)


def test_time_alignment_check_finds_a_shifted_feed():
    closes = walk(600, seed=4)
    aligned = M.match(feed(closes), feed(closes), S).frame
    assert M.lag_alignment(aligned, S)["peak_lag_bars"] == 0
    shifted = M.match(feed(closes), feed(closes, start=T0 + pd.Timedelta(seconds=S)), S).frame  # Exness stamped 1 bar late
    assert M.lag_alignment(shifted, S)["peak_lag_bars"] == 1


# ---- direction, shape, levels --------------------------------------------------------------------------

def test_direction_agreement_and_confusion():
    b = pd.DataFrame({"timestamp": [T0 + pd.Timedelta(seconds=S * i) for i in range(4)],
                      "open": [10, 10, 10, 10.0], "high": [12, 12, 12, 12.0], "low": [9, 9, 9, 9.0],
                      "close": [11, 9.5, 11, 10.0], "volume": 1.0})
    e = b.assign(close=[11.2, 11, 10.0, 10.0])
    m = M.match(b, e, S).frame
    d, db, de = M.direction_agreement(m, 2, 2)
    assert list(db) == [1, -1, 1, 0] and list(de) == [1, 1, 0, 0]
    assert d["same_pct"] == 50.0 and d["opposite_pct"] == 25.0 and d["flat_disagreement_pct"] == 25.0
    assert d["confusion"]["binance_bear__exness_bull"] == 1 and d["confusion"]["binance_bull__exness_bull"] == 1
    assert M.direction(pd.Series([10.0]), pd.Series([10.0004]), 3)[0] == 0  # flat at the feed's precision


def test_body_and_wick_percentages():
    frame = pd.DataFrame({"b_open": [10.0], "b_high": [14.0], "b_low": [9.0], "b_close": [12.0],
                          "e_open": [10.0], "e_high": [13.0], "e_low": [9.0], "e_close": [12.0]})
    b = M.shape("b", frame).iloc[0]
    assert (b["body"], b["upper"], b["lower"]) == (40.0, 40.0, 20.0)
    sim = M.shape_similarity(frame)
    assert sim["body_pct_abs_diff"]["median"] == pytest.approx(10.0)       # 40 vs 50
    assert sim["upper_pct_abs_diff"]["median"] == pytest.approx(15.0)      # 40 vs 25
    assert sim["range_ratio_binance_over_exness"]["median"] == pytest.approx(5 / 4)


def test_level_agreement_is_basis_adjusted_and_atr_normalised():
    closes = walk(50)
    b, e = feed(closes + 3.0), feed(closes)
    m = M.match(b, e, S).frame
    lv = M.level_agreement(m, pd.Series(2.0, index=m.index))
    assert lv["high"]["abs_median"] == pytest.approx(3.0) and lv["high"]["atr_median"] == pytest.approx(1.5)
    assert lv["high_excursion"]["abs_median"] == pytest.approx(0.0) and lv["range"]["abs_p95"] == pytest.approx(0.0)


# ---- indicators ------------------------------------------------------------------------------------------

def test_indicators_use_the_strategy_pine_implementations():
    from strategies.pine_indicators import EMA, ATR
    frame = feed(walk(60))
    ema = EMA(20)
    expected = [ema.update(c) for c in frame["close"]]
    got = M.pine_ema(frame["close"], 20)
    assert got.iloc[:19].isna().all() and got.iloc[19:].tolist() == pytest.approx(expected[19:])
    atr = ATR(14)
    from engine.models import Candle
    expected_atr = [atr.update(Candle(r.timestamp, r.open, r.high, r.low, r.close, r.volume)) for r in frame.itertuples()]
    assert M.pine_atr(frame).iloc[13:].tolist() == pytest.approx(expected_atr[13:])


def test_atr_comparison():
    frame = M.with_indicators(feed(walk(100)))
    doubled = frame.assign(atr=frame["atr"] * 2)
    ts = frame["timestamp"].iloc[20:]
    same = M.atr_comparison(frame, frame, ts)
    assert same["correlation"] == pytest.approx(1.0) and same["median_abs_pct_diff"] == 0.0
    assert M.atr_comparison(doubled, frame, ts)["median_pct_diff"] == pytest.approx(100.0)


def test_ema_cross_and_vwap_state():
    closes = np.r_[np.full(30, 100.0), np.full(10, 110.0), np.full(10, 90.0)]
    frame = M.with_indicators(feed(closes, spread=0.5))
    up, down = M.crosses(frame["close"], frame["ema20"])
    assert list(frame.index[up]) == [30] and list(frame.index[down]) == [40]
    ts = frame["timestamp"].iloc[25:]
    same = M.vwap_comparison(frame, frame, ts)
    assert same["state_agreement_pct"] == 100.0 and "tick volume" in same["volume_semantics"]
    flipped = frame.assign(vwap=2 * frame["close"] - frame["vwap"])  # price on the other side of VWAP
    moved = M.vwap_comparison(flipped, frame, ts)
    assert moved["binance_above_exness_below"] + moved["binance_below_exness_above"] > 0 and moved["state_agreement_pct"] < 100


# ---- events: swings, breakouts, matching -----------------------------------------------------------

def test_swing_detection_and_one_bar_tolerance():
    highs = [1, 2, 3, 9, 3, 2, 1, 2, 3, 4, 3, 2]
    frame = pd.DataFrame({"high": np.array(highs, float), "low": np.array(highs, float) - 1})
    sh, sl = M.swings(frame, 3)
    assert list(np.flatnonzero(sh)) == [3]
    times_b = np.array([10 * S, 20 * S])
    times_e = np.array([11 * S, 20 * S, 40 * S])
    r = M.match_events(times_b, times_e, S)
    assert (r["same_bar"], r["within_tolerance"], r["binance_only"], r["exness_only"]) == (1, 2, 0, 1)
    assert r["agreement_same_bar_pct"] == pytest.approx(25.0) and r["agreement_tolerance_pct"] == pytest.approx(200 / 3)
    assert r["offset_bars_exness_minus_binance"] == {"1": 1}


def test_event_matching_is_one_to_one():
    r = M.match_events(np.array([10 * S]), np.array([9 * S, 11 * S]), S)
    assert r["within_tolerance"] == 1 and r["exness_only"] == 1  # one Binance event cannot match two


def test_breakout_onsets_on_each_feed():
    closes = np.r_[np.full(25, 100.0), 106.0, 107.0, 108.0, np.full(5, 100.0), 90.0]
    frame = feed(closes, spread=1.0)
    up, down = M.breakouts(frame, 20, "close")
    assert list(frame.index[up]) == [25]      # onset only, not every candle above the level
    assert list(frame.index[down]) == [33]
    shifted = feed(np.r_[np.full(26, 100.0), 106.0, 107.0, 108.0, np.full(4, 100.0), 90.0], spread=1.0)
    upb, _ = M.breakouts(shifted, 20, "close")
    r = M.match_events(M.event_times(frame, up, M.epoch_seconds(frame["timestamp"])),
                       M.event_times(shifted, upb, M.epoch_seconds(shifted["timestamp"])), S)
    assert (r["same_bar"], r["within_tolerance"]) == (0, 1)


def test_events_outside_the_matched_candles_are_not_counted():
    frame = feed(walk(50))
    flags = pd.Series(False, index=frame.index)
    flags.iloc[[5, 30]] = True
    allowed = M.epoch_seconds(frame["timestamp"].iloc[10:])
    assert list(M.event_times(frame, flags, allowed)) == [M.epoch_seconds(frame["timestamp"])[30]]


# ---- grouping and outliers --------------------------------------------------------------------------

def test_hourly_grouping_and_outliers():
    closes = walk(96 * 2)
    e = feed(closes)
    b = feed(closes + np.where(np.arange(len(closes)) == 50, 40.0, 0.0))
    m = M.match(b, e, S).frame
    _, db, de = M.direction_agreement(m, 2, 2)
    miss = np.zeros(len(m), bool)
    miss[50] = True
    hours = M.grouped_summary(m, db, de, miss, miss.copy(), m["timestamp"].dt.hour)
    assert [h["key"] for h in hours] == list(range(24)) and sum(h["matched_bars"] for h in hours) == len(m)
    hour_50 = m["timestamp"].iloc[50].hour
    assert next(h for h in hours if h["key"] == hour_50)["breakout_disagreements"] == 1
    top = M.outliers(m, m["b_close"] - m["e_close"], "largest_close_difference", count=3)
    assert top[0]["timestamp"] == m["timestamp"].iloc[50].isoformat() and top[0]["difference"] == pytest.approx(40.0)
    assert {"binance_open", "exness_close", "kind"} <= set(top[0])


def test_thresholds_label_without_tuning():
    assert TH.label("direction", 98.0) == "excellent" and TH.label("direction", 97.9) == "strong"
    assert TH.label("breakout", 89.99) == "weak" and TH.label("swing", 95.0) == "strong" and TH.label("swing", 50) == "weak"


# ---- end to end, data loading --------------------------------------------------------------------------

def test_identical_feeds_agree_everywhere_and_a_constant_basis_is_only_an_offset():
    closes = walk(1500, seed=7, start=4000.0).round(2)  # on both feeds' price grid
    # Varied wicks (with a fixed wick every high ties a neighbour and no strict swing exists).
    wicks = np.random.default_rng(3).uniform(0.5, 4.0, 1500).round(2)
    e = feed(closes, spread=wicks, volume=5.0)
    b = feed(closes + 7.5, spread=wicks, volume=50.0)
    summary, table, outliers = analyse("XAU", "15m", b, e, binance_digits=2, exness_digits=3)
    h = summary["headline"]
    assert summary["swings"]["3"]["pooled"]["binance_events"] > 50
    assert h["direction_agreement_pct"] == 100.0 and h["breakout_close20_pm1_pct"] == 100.0
    assert h["ema20_cross_pm1_pct"] == 100.0 and h["swing3_pm1_pct"] == 100.0 and h["vwap_state_agreement_pct"] == 100.0
    assert h["median_close_diff"] == pytest.approx(7.5)
    assert all(p["agreement_tolerance_pct"] in (100.0, None) for p in summary["signal_proxies"].values())
    assert summary["comparison_candles_after_warmup"] == 1500 - TH.WARMUP_BARS
    assert len(table) == 1500 and table["close_diff"].tolist() == pytest.approx([7.5] * 1500)
    assert summary["labels"]["direction"] == "excellent"
    assert summary["session_aligned_view"]["headline"]["breakout_close20_pm1_pct"] == 100.0


def test_session_aligned_view_removes_only_closed_market_candles():
    closes = walk(1500, seed=9, start=4000.0).round(2)
    wicks = np.random.default_rng(5).uniform(0.5, 4.0, 1500).round(2)
    b = feed(closes, spread=wicks)
    e = feed(closes, spread=wicks, drop=range(600, 700))   # Exness closed for 100 candles; Binance trades on
    summary, _, _ = analyse("XAU", "15m", b, e, binance_digits=2, exness_digits=2)
    view = summary["session_aligned_view"]["headline"]
    assert view["breakout_close20_pm1_pct"] == 100.0 and view["ema20_cross_pm1_pct"] == 100.0
    assert summary["coverage"]["unmatched_binance"] == 100


def test_exness_gold_30m_is_derived_by_the_project_aggregator_without_writing():
    from research.feed_comparison.data import exness_feed
    from services.market_datasets import dataset
    path = dataset("EXNESS_XAUUSDM_M15").path
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    gold30 = exness_feed("XAU", "30m")
    assert gold30.native is False and gold30.dataset_key == "EXNESS_XAUUSDM_M15"
    assert (M.epoch_seconds(gold30.frame["timestamp"]) % 1800 == 0).all()
    assert exness_feed("BTC", "30m").native is True
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_binance_history_is_paged_and_cached_offline(tmp_path):
    sys.path.insert(0, str(Path(__file__).parent / "tradingview_mode"))
    from fake_binance import Clock, FakeMarket, FakeRest
    from research.feed_comparison.data import binance_feed
    clock = Clock()
    rest = FakeRest(FakeMarket(clock, count=3000))
    now = pd.Timestamp(int(clock()) // 900 * 900, unit="s", tz="UTC")
    start, end = now - pd.Timedelta(days=20), now - pd.Timedelta(days=1)
    frame, meta = binance_feed("XAU", "15m", start, end, rest=rest, cache=tmp_path)
    times = M.epoch_seconds(frame["timestamp"])
    assert len(frame) == meta["received_bars"] == int((end - start).total_seconds() // 900) + 1
    assert frame["timestamp"].iloc[0] == start and frame["timestamp"].iloc[-1] == end and np.all(np.diff(times) == 900)
    again, meta2 = binance_feed("XAU", "15m", start, end, rest=None, cache=tmp_path)
    assert meta2["from_cache"] is True and again.equals(frame)


def test_strategy_windows_split_at_data_gaps():
    from research.feed_comparison.strategy_parity import contiguous_windows
    frame = feed(walk(20), drop=(8, 9))
    windows = contiguous_windows(frame["timestamp"], frame["timestamp"].iloc[2], frame["timestamp"].iloc[-1])
    assert windows == [(T0 + pd.Timedelta(seconds=2 * S), T0 + pd.Timedelta(seconds=7 * S)),
                       (T0 + pd.Timedelta(seconds=10 * S), T0 + pd.Timedelta(seconds=19 * S))]
