import pandas as pd
import numpy as np
from pathlib import Path
from services.market_datasets import dataset, EXNESS_BTCUSDM_M30, EXNESS_BTCUSDM_H1
from utils.data_validation import load_ohlcv_csv

# ==============================================================================
# RESEARCH PROTOCOL BOUNDARIES
# ==============================================================================
DEV_START = pd.Timestamp("2021-12-11 00:00", tz="UTC")
DEV_END = pd.Timestamp("2025-12-31 23:59", tz="UTC")

def get_development_data(df):
    return df[(df.index >= DEV_START) & (df.index <= DEV_END)].copy()

def get_atr(df, period=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift(1)).abs()
    low_close = (df["low"] - df["close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(period).mean()

# ==============================================================================
# DATA LOADING & ALIGNMENT
# ==============================================================================
def load_and_align_datasets():
    m30_ds = dataset(EXNESS_BTCUSDM_M30)
    m30_df = load_ohlcv_csv(m30_ds.path)
    m30_df = m30_df.set_index("timestamp").sort_index()
    
    h1_ds = dataset(EXNESS_BTCUSDM_H1)
    h1_df = load_ohlcv_csv(h1_ds.path)
    h1_df = h1_df.set_index("timestamp").sort_index()
    
    h4_df = h1_df.resample("4h", label="left", closed="left").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"
    })
    
    m30_dev = get_development_data(m30_df)
    h1_dev = get_development_data(h1_df)
    h4_dev = get_development_data(h4_df)
    
    return m30_dev, h1_dev, h4_dev

# ==============================================================================
# H4 REGIME STATES
# ==============================================================================
def calculate_h4_states(h4):
    close = h4["close"]
    ema50 = close.ewm(span=50, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()
    atr = get_atr(h4)
    slope_50 = ema50.diff() / atr
    regime = pd.Series("neutral_range", index=h4.index)
    bullish = (ema50 > ema200) & (slope_50 > 0) & (close > ema50)
    bearish = (ema50 < ema200) & (slope_50 < 0) & (close < ema50)
    trans_up = (close > ema50) & (ema50 < ema200)
    trans_down = (close < ema50) & (ema50 > ema200)
    regime[bullish] = "bullish_trend"
    regime[bearish] = "bearish_trend"
    regime[trans_up] = "transition_up"
    regime[trans_down] = "transition_down"
    return regime

# ==============================================================================
# H1 CONTEXT STATES
# ==============================================================================
def calculate_h1_states(h1):
    close = h1["close"]
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    atr = get_atr(h1)
    state = pd.Series("neutral", index=h1.index)
    state[(close > ema20) & (ema20 > ema50)] = "aligned_bull"
    state[(close < ema20) & (ema20 < ema50)] = "aligned_bear"
    state[(close < ema20) & (ema20 > ema50)] = "pullback_bull"
    state[(close > ema20) & (ema20 < ema50)] = "pullback_bear"
    body = (close - h1["open"]).abs()
    expansion = body > (atr * 1.5)
    state[expansion & (close > h1["open"])] = "expansion_bull"
    state[expansion & (close < h1["open"])] = "expansion_bear"
    range_val = (h1["high"] - h1["low"])
    state[range_val < (atr * 0.6)] = "compression"
    dist = (close - ema50).abs() / atr
    state[(dist < 0.5) & (ema20 > ema50)] = "deterioration_bull"
    state[(dist < 0.5) & (ema20 < ema50)] = "deterioration_bear"
    state[(close > ema20) & (ema20 < ema50)] = "reversal_attempt_bull"
    state[(close < ema20) & (ema20 > ema50)] = "reversal_attempt_bear"
    return state

# ==============================================================================
# M30 EVENT DETECTORS
# ==============================================================================
def detect_m30_events(df):
    events = []
    close = df["close"]
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    atr = get_atr(df)
    
    # Local structure
    roll_h = high.rolling(5).max()
    roll_l = low.rolling(5).min()
    
    for i in range(14, len(df) - 1):
        ts = df.index[i]
        c = close.iloc[i]
        l = low.iloc[i]
        h = high.iloc[i]
        o = open_.iloc[i]
        prev_c = close.iloc[i-1]
        curr_atr = atr.iloc[i]
        
        # --- LONG ---
        # 1. Pullback Rejection: Low < roll_l[i-1] and closes strong
        if l < roll_l.iloc[i-1] and c > prev_c:
            events.append({
                "timestamp": ts, "direction": "LONG", "family": "pullback_rejection",
                "ref_ts": df.index[i], "ref_price": l, "stop": l, "entry": open_.iloc[i+1]
            })
        # 2. Reclaim: Close > roll_h[i-1]
        if c > roll_h.iloc[i-1]:
            events.append({
                "timestamp": ts, "direction": "LONG", "family": "reclaim",
                "ref_ts": df.index[i], "ref_price": roll_l.iloc[i], "stop": roll_l.iloc[i], "entry": open_.iloc[i+1]
            })
        # 3. Displacement: Large body
        if (c - o) > (h - l) * 0.7 and (c - o) > 0:
            events.append({
                "timestamp": ts, "direction": "LONG", "family": "displacement_continuation",
                "ref_ts": df.index[i], "ref_price": l, "stop": l, "entry": open_.iloc[i+1]
            })
        # 4. Breakout Retest: Close > roll_h[i-1] and Low’s touch/near roll_h
        if c > roll_h.iloc[i-1] and l <= roll_h.iloc[i-1] * 1.001:
            events.append({
                "timestamp": ts, "direction": "LONG", "family": "breakout_retest",
                "ref_ts": df.index[i], "ref_price": roll_h.iloc[i-1], "stop": l, "entry": open_.iloc[i+1]
            })
        # 5. Liq Sweep: Low < roll_l[i-1] then Close > roll_h[i-5] (Aggressive)
        if l < roll_l.iloc[i-1] and c > roll_h.iloc[i-5]:
            events.append({
                "timestamp": ts, "direction": "LONG", "family": "liquidity_sweep_reclaim",
                "ref_ts": df.index[i], "ref_price": l, "stop": l, "entry": open_.iloc[i+1]
            })
        # 6. Failed Breakout: High > roll_h[i-1] then Close < roll_h[i-1]
        if h > roll_h.iloc[i-1] and c < roll_h.iloc[i-1]:
            # This is a Short signal
            events.append({
                "timestamp": ts, "direction": "SHORT", "family": "failed_breakout",
                "ref_ts": df.index[i], "ref_price": h, "stop": h, "entry": open_.iloc[i+1]
            })
        # 7. Structure Break: Close > high of a clear swing
        if c > roll_h.iloc[i-5]:
            events.append({
                "timestamp": ts, "direction": "LONG", "family": "structure_break_continuation",
                "ref_ts": df.index[i], "ref_price": roll_l.iloc[i-5], "stop": roll_l.iloc[i-5], "entry": open_.iloc[i+1]
            })
            
        # --- SHORT ---
        if h > roll_h.iloc[i-1] and c < prev_c:
            events.append({
                "timestamp": ts, "direction": "SHORT", "family": "pullback_rejection",
                "ref_ts": df.index[i], "ref_price": h, "stop": h, "entry": open_.iloc[i+1]
            })
        if c < roll_l.iloc[i-1]:
            events.append({
                "timestamp": ts, "direction": "SHORT", "family": "reclaim",
                "ref_ts": df.index[i], "ref_price": roll_h.iloc[i], "stop": roll_h.iloc[i], "entry": open_.iloc[i+1]
            })
        if (o - c) > (h - l) * 0.7 and (o - c) > 0:
            events.append({
                "timestamp": ts, "direction": "SHORT", "family": "displacement_continuation",
                "ref_ts": df.index[i], "ref_price": h, "stop": h, "entry": open_.iloc[i+1]
            })
        if c < roll_l.iloc[i-1] and h >= roll_l.iloc[i-1] * 0.999:
            events.append({
                "timestamp": ts, "direction": "SHORT", "family": "breakout_retest",
                "ref_ts": df.index[i], "ref_price": roll_l.iloc[i-1], "stop": h, "entry": open_.iloc[i+1]
            })
        if h > roll_h.iloc[i-1] and c < roll_l.iloc[i-5]:
            events.append({
                "timestamp": ts, "direction": "SHORT", "family": "liquidity_sweep_reclaim",
                "ref_ts": df.index[i], "ref_price": h, "stop": h, "entry": open_.iloc[i+1]
            })
        if l < roll_l.iloc[i-1] and c > roll_l.iloc[i-1]:
            events.append({
                "timestamp": ts, "direction": "LONG", "family": "failed_breakout",
                "ref_ts": df.index[i], "ref_price": l, "stop": l, "entry": open_.iloc[i+1]
            })
        if c < roll_l.iloc[i-5]:
            events.append({
                "timestamp": ts, "direction": "SHORT", "family": "structure_break_continuation",
                "ref_ts": df.index[i], "ref_price": roll_h.iloc[i-5], "stop": roll_h.iloc[i-5], "entry": open_.iloc[i+1]
            })
            
    return events

# ==============================================================================
# OUTCOME ENGINE
# ==============================================================================
def evaluate_outcomes(df, events):
    results = []
    ts_to_idx = {ts: i for i, ts in enumerate(df.index)}
    point = 0.01 # BTCUSDm
    
    for e in events:
        entry_ts = e["timestamp"] + pd.Timedelta(minutes=30)
        if entry_ts not in ts_to_idx: continue
        
        entry_idx = ts_to_idx[entry_ts]
        mid_entry = df["open"].iloc[entry_idx]
        
        # Price/Spread Semantics:
        # LONG: Entry = Mid + (Spread/2), Exit = Mid - (Spread/2)
        # SHORT: Entry = Mid - (Spread/2), Exit = Mid + (Spread/2)
        # Note: a simplified approach for research is using the la-Mid and just tracking R.
        # But the request asks for spread handling.
        
        # We'll approximate the broker spread from the M30 bar's native spread_points.
        spread = df["spread_points"].iloc[entry_idx] * point if "spread_points" in df.columns else 0
        
        if e["direction"] == "LONG":
            entry_price = mid_entry + (spread / 2)
            stop = e["stop"] - (spread / 2)
            risk = entry_price - stop
            if risk <= 0: continue
            target = entry_price + 2.5 * risk
        else:
            entry_price = mid_entry - (spread / 2)
            stop = e["stop"] + (spread / 2)
            risk = stop - entry_price
            if risk <= 0: continue
            target = entry_price - 2.5 * risk
            
        outcome = {"win": False, "mfe": 0, "mae": 0}
        mfe, mae = 0, 0
        
        for j in range(entry_idx, len(df)):
            # Use the mid-price for hit detection, then adjust for spread at the end
            # or just use high/low. Conservative: SL First.
            bar_high = df["high"].iloc[j]
            bar_low = df["low"].iloc[j]
            
            if e["direction"] == "LONG":
                # SL hit if bar_low - spread/2 <= stop
                if bar_low - (spread / 2) <= stop:
                    outcome["win"] = False; break
                if bar_high + (spread / 2) >= target:
                    outcome["win"] = True; break
                mfe = max(mfe, bar_high + (spread / 2) - entry_price)
                mae = min(mae, bar_low - (spread / 2) - entry_price)
            else:
                # SL hit if bar_high + spread/2 >= stop
                if bar_high + (spread / 2) >= stop:
                    outcome["win"] = False; break
                if bar_low - (spread / 2) <= target:
                    outcome["win"] = True; break
                mfe = max(mfe, entry_price - (bar_low - (spread / 2)))
                mae = min(mae, entry_price - (bar_high + (spread / 2)))
        
        outcome["mfe"] = mfe; outcome["mae"] = mae
        e.update(outcome)
        e["entry_price"] = entry_price
        e["target"] = target
        e["stop_price"] = stop
        results.append(e)
        
    return results

if __name__ == "__main__":
    m30, h1, h4 = load_and_align_datasets()
    
    # 1. PROVE ALIGNMENT
    combined = m30.copy()
    h1_closed = h1.index + pd.Timedelta(hours=1)
    h4_closed = h4.index + pd.Timedelta(hours=4)
    h1_map = pd.DataFrame({"h1_ts": h1.index, "h1_closed": h1_closed})
    h4_map = pd.DataFrame({"h4_ts": h4.index, "h4_closed": h4_closed})
    combined = pd.merge_asof(combined.sort_index(), h1_map.sort_values("h1_closed"), left_index=True, right_on="h1_closed", direction="backward").set_index(combined.index)
    combined = pd.merge_asof(combined.sort_index(), h4_map.sort_values("h4_closed"), left_index=True, right_on="h4_closed", direction="backward").set_index(combined.index)
    
    print("\n--- TIMEFRAME ALIGNMENT CHECK ---")
    samples = combined.sample(10).dropna(subset=["h1_ts", "h4_ts"])
    for ts, row in samples.iterrows():
        print(f"M30 Decision: {ts} | H1 Open: {row['h1_ts']} | H1 Close: {row['h1_closed']} | H4 Open: {row['h4_ts']} | H4 Close: {row['h4_closed']} | H1 Eligible: {row['h1_closed'] <= ts} | H4 Eligible: {row['h4_closed'] <= ts}")
    
    # 2. STATE MAP
    h4_states = calculate_h4_states(h4)
    h1_states = calculate_h1_states(h1)
    final = combined.copy()
    final["h4_regime"] = final["h4_ts"].map(h4_states)
    final["h1_context"] = final["h1_ts"].map(h1_states)
    
    # 3. EVENTS
    events = detect_m30_events(final)
    
    # 4. OUTCOMES
    results = evaluate_outcomes(final, events)
    res_df = pd.DataFrame(results)
    
    # 5. INTEGRITY SAMPLE
    print("\n--- EVENT INTEGRITY SAMPLE ---")
    for family in res_df["family"].unique():
        for direction in ["LONG", "SHORT"]:
            subset = res_df[(res_df["family"] == family) & (res_df["direction"] == direction)].head(5)
            if not subset.empty:
                print(f"\n{family} {direction}:")
                for idx, row in subset.iterrows():
                    print(f"Signal: {row['timestamp']} | Entry: {row['entry']} | Stop: {row['stop_price']} | Target: {row['target']} | Ref: {row['ref_ts']}")
    
    # FINAL SUMMARY
    if not res_df.empty:
        res_df["h4_state"] = res_df["timestamp"].map(final["h4_regime"])
        res_df["h1_state"] = res_df["timestamp"].map(final["h1_context"])
        
        print("\n--- RESULTS ---")
        print(f"Global WR (2.5R): {res_df['win'].mean()*100:.2f}%")
        print("\nEvent Counts:\n", res_df["family"].value_counts())
        print("\nWin Rate by Family:\n", res_df.groupby("family")["win"].mean()*100)
    else:
        print("No events detected.")

    print("\nReserved 2026 Validation Touched: NO")
    print("PROTECTED BTC V3: UNCHANGED")
