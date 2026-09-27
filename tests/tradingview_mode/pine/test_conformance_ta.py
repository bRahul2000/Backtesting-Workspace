"""Conformance: ta.* against independent reference implementations of the
formulas in Pine's documentation (plain NumPy/pandas, written separately from
the engine). Every bar is compared, including the warm-up (na) region."""
import math

import numpy as np
import pandas as pd
import pytest

from .helpers import bars, plots, run, script

FRAME = bars(700, seed=11)
C, H, L, O, V = (FRAME[k].to_numpy() for k in ("close", "high", "low", "open", "volume"))


def pine_sma(x, n):
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        window = x[i - n + 1:i + 1]
        if not np.isnan(window).any():
            out[i] = window.mean()
    return out


def pine_recursive(x, n, alpha):
    """sum := na(sum[1]) ? sma(x, n) : alpha*x + (1-alpha)*sum[1]"""
    sma = pine_sma(x, n)
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        prev = out[i - 1] if i else np.nan
        out[i] = sma[i] if np.isnan(prev) else alpha * x[i] + (1 - alpha) * prev
    return out


def pine_ema(x, n):
    return pine_recursive(x, n, 2 / (n + 1))


def pine_rma(x, n):
    return pine_recursive(x, n, 1 / n)


def true_range(handle_na):
    prev = np.r_[np.nan, C[:-1]]
    tr = np.maximum.reduce([H - L, np.abs(H - prev), np.abs(L - prev)])
    tr[0] = (H[0] - L[0]) if handle_na else np.nan
    return tr


def check(actual, expected, tol=1e-9):
    actual = np.array([np.nan if v is None else v for v in actual], dtype=float)
    expected = np.asarray(expected, dtype=float)
    assert len(actual) == len(expected)
    both_nan = np.isnan(actual) & np.isnan(expected)
    assert np.array_equal(np.isnan(actual), np.isnan(expected)), (
        f"na pattern differs at {np.flatnonzero(np.isnan(actual) != np.isnan(expected))[:5]}")
    assert np.allclose(actual[~both_nan], expected[~both_nan], rtol=tol, atol=tol)


def run_plots(body: str, frame=FRAME):
    out, _ = run(script(body), frame)
    return plots(out)


def test_moving_averages():
    p = run_plots("""
plot(ta.sma(close, 14), "sma")
plot(ta.ema(close, 14), "ema")
plot(ta.rma(close, 14), "rma")
plot(ta.wma(close, 10), "wma")
plot(ta.vwma(close, 10), "vwma")
""")
    check(p["sma"], pine_sma(C, 14))
    check(p["ema"], pine_ema(C, 14))
    check(p["rma"], pine_rma(C, 14))
    weights = np.arange(1, 11)
    wma = np.full(len(C), np.nan)
    for i in range(9, len(C)):
        wma[i] = (C[i - 9:i + 1] * weights).sum() / weights.sum()
    check(p["wma"], wma)
    check(p["vwma"], pine_sma(C * V, 10) / pine_sma(V, 10))


def test_rsi_atr_tr():
    p = run_plots("""
plot(ta.rsi(close, 14), "rsi")
plot(ta.atr(14), "atr")
plot(ta.tr(true), "tr_true")
plot(ta.tr, "tr_var")
""")
    change = np.r_[np.nan, np.diff(C)]
    up, down = pine_rma(np.maximum(change, 0), 14), pine_rma(np.maximum(-change, 0), 14)
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi = np.where(down == 0, 100.0, np.where(up == 0, 0.0, 100 - 100 / (1 + up / down)))
    rsi[np.isnan(up) | np.isnan(down)] = np.nan
    check(p["rsi"], rsi)
    check(p["atr"], pine_rma(true_range(True), 14))
    check(p["tr_true"], true_range(True))
    check(p["tr_var"], true_range(False))


def test_macd_bb_stdev_tuple_returns():
    p = run_plots("""
[m, s, h] = ta.macd(close, 12, 26, 9)
plot(m, "macd")
plot(s, "signal")
plot(h, "hist")
[basis, upper, lower] = ta.bb(close, 20, 2.0)
plot(upper, "upper")
plot(ta.stdev(close, 20), "stdev")
plot(ta.stdev(close, 20, false), "stdev_sample")
plot(ta.variance(close, 20), "variance")
""")
    macd = pine_ema(C, 12) - pine_ema(C, 26)
    signal = pine_ema(macd, 9)
    check(p["macd"], macd)
    check(p["signal"], signal)
    check(p["hist"], macd - signal)
    std = pd.Series(C).rolling(20).std(ddof=0).to_numpy()
    check(p["upper"], pine_sma(C, 20) + 2 * std)
    check(p["stdev"], std)
    check(p["stdev_sample"], pd.Series(C).rolling(20).std(ddof=1).to_numpy())
    check(p["variance"], std ** 2)


def test_extremes_and_oscillators():
    p = run_plots("""
plot(ta.highest(high, 10), "hh")
plot(ta.lowest(10), "ll")
plot(ta.highestbars(high, 10), "hhb")
plot(ta.stoch(close, high, low, 14), "stoch")
plot(ta.cci(close, 20), "cci")
plot(ta.mom(close, 5), "mom")
plot(ta.roc(close, 5), "roc")
plot(ta.change(close), "chg")
plot(ta.cum(volume), "cum")
plot(ta.wpr(14), "wpr")
""")
    hh = pd.Series(H).rolling(10).max().to_numpy()
    ll = pd.Series(L).rolling(10).min().to_numpy()
    check(p["hh"], hh)
    check(p["ll"], ll)
    hhb = np.full(len(H), np.nan)
    for i in range(9, len(H)):
        window = H[i - 9:i + 1][::-1]
        hhb[i] = -int(np.argmax(window))
    check(p["hhb"], hhb)
    h14, l14 = pd.Series(H).rolling(14).max().to_numpy(), pd.Series(L).rolling(14).min().to_numpy()
    check(p["stoch"], 100 * (C - l14) / (h14 - l14))
    sma20 = pine_sma(C, 20)
    dev = pd.Series(C).rolling(20).apply(lambda w: np.mean(np.abs(w - w.mean())), raw=True).to_numpy()
    check(p["cci"], (C - sma20) / (0.015 * dev), tol=1e-8)
    check(p["mom"], C - np.r_[np.full(5, np.nan), C[:-5]])
    check(p["roc"], 100 * (C - np.r_[np.full(5, np.nan), C[:-5]]) / np.r_[np.full(5, np.nan), C[:-5]])
    check(p["chg"], np.r_[np.nan, np.diff(C)])
    check(p["cum"], np.cumsum(V))
    check(p["wpr"], 100 * (C - h14) / (h14 - l14))


def test_crosses_barssince_valuewhen_pivots():
    p = run_plots("""
fast = ta.sma(close, 5)
slow = ta.sma(close, 20)
up = ta.crossover(fast, slow)
dn = ta.crossunder(fast, slow)
plot(up ? 1 : 0, "up")
plot(dn ? 1 : 0, "dn")
plot(ta.barssince(up), "since")
plot(ta.valuewhen(up, close, 0), "vw0")
plot(ta.valuewhen(up, close, 1), "vw1")
plot(ta.pivothigh(high, 3, 3), "ph")
plot(ta.rising(close, 3) ? 1 : 0, "rising")
""")
    fast, slow = pine_sma(C, 5), pine_sma(C, 20)
    prev_fast, prev_slow = np.r_[np.nan, fast[:-1]], np.r_[np.nan, slow[:-1]]
    valid = ~np.isnan(fast) & ~np.isnan(slow) & ~np.isnan(prev_fast) & ~np.isnan(prev_slow)
    up = valid & (fast > slow) & (prev_fast <= prev_slow)
    dn = valid & (fast < slow) & (prev_fast >= prev_slow)
    check(p["up"], up.astype(float))
    check(p["dn"], dn.astype(float))
    since, vw0, vw1, hits = np.full(len(C), np.nan), np.full(len(C), np.nan), np.full(len(C), np.nan), []
    for i in range(len(C)):
        if up[i]:
            hits.append(C[i])
        last_hit = max((j for j in range(i + 1) if up[j]), default=None)
        since[i] = np.nan if last_hit is None else i - last_hit
        vw0[i] = hits[-1] if hits else np.nan
        vw1[i] = hits[-2] if len(hits) > 1 else np.nan
    check(p["since"], since)
    check(p["vw0"], vw0)
    check(p["vw1"], vw1)
    ph = np.full(len(H), np.nan)
    for i in range(6, len(H)):
        center = H[i - 3]
        others = np.r_[H[i - 6:i - 3], H[i - 2:i + 1]]
        if (center > others).all():
            ph[i] = center
    check(p["ph"], ph)
    rising = np.zeros(len(C))
    for i in range(3, len(C)):
        rising[i] = float(all(C[i] > C[i - k] for k in (1, 2, 3)))
    check(p["rising"], rising)


def test_vwap_is_anchored_to_each_utc_day_and_obv_accumulates():
    frame = bars(300, seed=5, freq="1h")
    p = run_plots("""
plot(ta.vwap, "vwap_var")
plot(ta.vwap(hlc3), "vwap_fn")
plot(ta.obv, "obv")
""", frame)
    hlc3 = (frame["high"] + frame["low"] + frame["close"]) / 3
    day = frame["timestamp"].dt.date
    pv = (hlc3 * frame["volume"]).groupby(day).cumsum()
    vv = frame["volume"].groupby(day).cumsum()
    check(p["vwap_var"], (pv / vv).to_numpy())
    check(p["vwap_fn"], (pv / vv).to_numpy())
    close = frame["close"].to_numpy()
    obv = np.cumsum(np.r_[0, np.sign(np.diff(close)) * frame["volume"].to_numpy()[1:]])
    check(p["obv"], obv)


def test_dmi_supertrend_and_sar_run_and_stay_in_range():
    p = run_plots("""
[diplus, diminus, adx] = ta.dmi(14, 14)
plot(diplus, "plus")
plot(adx, "adx")
[st, dir] = ta.supertrend(3, 10)
plot(st, "st")
plot(dir, "dir")
plot(ta.sar(0.02, 0.02, 0.2), "sar")
""")
    adx = np.array([np.nan if v is None else v for v in p["adx"]], dtype=float)
    assert np.nanmin(adx) >= 0 and np.nanmax(adx) <= 100 and np.isnan(adx[:20]).all() and not np.isnan(adx[-1])
    assert set(v for v in p["dir"] if v is not None) <= {1.0, -1.0}
    st = np.array([np.nan if v is None else v for v in p["st"]], dtype=float)
    assert not np.isnan(st[-100:]).any()
    sar = np.array([np.nan if v is None else v for v in p["sar"]], dtype=float)
    assert not np.isnan(sar[5:]).any()


def ref_sma_skipna(x, n):
    """TradingView (observed, parity fixture s01): the mean of the last n non-na values."""
    out, seen = np.full(len(x), np.nan), []
    for i, value in enumerate(x):
        if not np.isnan(value):
            seen.append(value)
        if len(seen) >= n:
            out[i] = np.mean(seen[-n:])
    return out


def ref_recursive_skipna(x, n, alpha):
    """TradingView (observed): na on na bars; the recursion runs over the non-na values only."""
    out, prev, seen = np.full(len(x), np.nan), np.nan, []
    for i, value in enumerate(x):
        if np.isnan(value):
            continue
        seen.append(value)
        if np.isnan(prev):
            prev = np.mean(seen[-n:]) if len(seen) >= n else np.nan
        else:
            prev = alpha * value + (1 - alpha) * prev
        out[i] = prev
    return out


def ref_wma_fill(x, n):
    """TradingView (observed): na on na bars; an na inside the window counts as the last value before it."""
    filled = pd.Series(x).ffill().to_numpy()
    weights = np.arange(1, n + 1)
    out = np.full(len(x), np.nan)
    for i in range(n - 1, len(x)):
        window = filled[i - n + 1:i + 1]
        if not np.isnan(x[i]) and not np.isnan(window).any():
            out[i] = (window * weights).sum() / weights.sum()
    return out


def test_mid_series_na_follows_tradingview():
    frame = FRAME.copy()
    frame.loc[[100, 101, 250], "close"] = np.nan
    frame.loc[[100, 101, 250], ["open", "high", "low"]] = np.nan
    p = run_plots('plot(ta.sma(close, 5), "sma")\nplot(ta.ema(close, 5), "ema")\nplot(ta.rma(close, 7), "rma")\n'
                  'plot(ta.wma(close, 6), "wma")', frame)
    closes = frame["close"].to_numpy()
    check(p["sma"], ref_sma_skipna(closes, 5))
    check(p["ema"], ref_recursive_skipna(closes, 5, 2 / 6))
    check(p["rma"], ref_recursive_skipna(closes, 7, 1 / 7))
    check(p["wma"], ref_wma_fill(closes, 6))
    assert p["sma"][100] is not None and p["ema"][100] is None and p["ema"][102] is not None
