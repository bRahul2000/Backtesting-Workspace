import json
from hashlib import sha256
from pathlib import Path

import pandas as pd

from brokers.exness import load_exness_xauusd_profile
from instruments.xauusd import load_xauusd_profile
from services.gold_spec import load_mt5_gold_snapshot


ROOT = Path(__file__).resolve().parents[1] / "data" / "exness" / "gold" / "phase2a"
RAW = ROOT / "raw"


def test_phase2a_profile_matches_captured_identity_and_contract():
    spec = load_mt5_gold_snapshot(RAW / "xauusd_mt5_spec.json")
    profile = load_xauusd_profile(RAW / "xauusd_mt5_spec.json")
    broker = load_exness_xauusd_profile(RAW / "xauusd_mt5_spec.json")
    assert spec["broker"] == {"company": "Exness Technologies Ltd", "server": "Exness-MT5Trial5"}
    assert spec["symbol"]["name"] == "XAUUSDm"
    assert profile.price_precision == 3
    assert profile.point == profile.tick_size == 0.001
    assert profile.tick_value == 0.1
    assert profile.contract_size == 100.0
    assert (profile.minimum_volume, profile.maximum_volume, profile.volume_step) == (0.01, 200.0, 0.01)
    assert broker.instrument("XAUUSD").known


def test_phase2a_raw_files_preserve_recorded_hashes():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    expected = manifest["fingerprints"]
    for filename, key in (
        ("xauusd_mt5_spec.json", "symbol_specification_sha256"),
        ("xauusd_XAUUSDm_M15.csv", "m15_dataset_sha256"),
        ("xauusd_XAUUSDm_H1.csv", "h1_dataset_sha256"),
    ):
        assert sha256((RAW / filename).read_bytes()).hexdigest() == expected[key]


def test_phase2a_m15_and_h1_have_clean_ohlc_and_align():
    m15 = pd.read_csv(RAW / "xauusd_XAUUSDm_M15.csv", parse_dates=["timestamp"])
    h1 = pd.read_csv(RAW / "xauusd_XAUUSDm_H1.csv", parse_dates=["timestamp"])
    assert not m15.isna().any().any()
    assert not h1.isna().any().any()
    assert not m15.timestamp.duplicated().any()
    assert not h1.timestamp.duplicated().any()
    assert (m15.high >= m15[["open", "close"]].max(axis=1)).all()
    assert (m15.low <= m15[["open", "close"]].min(axis=1)).all()
    assert (h1.high >= h1[["open", "close"]].max(axis=1)).all()
    assert (h1.low <= h1[["open", "close"]].min(axis=1)).all()

    m15_by_time = m15.set_index("timestamp")
    complete = mismatches = 0
    for row in h1.itertuples(index=False):
        stamps = pd.date_range(row.timestamp, periods=4, freq="15min")
        chunk = m15_by_time.reindex(stamps)
        if chunk[["open", "high", "low", "close"]].isna().any().any():
            continue
        complete += 1
        expected = (chunk.open.iloc[0], chunk.high.max(), chunk.low.min(), chunk.close.iloc[-1])
        actual = (row.open, row.high, row.low, row.close)
        mismatches += any(abs(left - right) > 1e-9 for left, right in zip(expected, actual))
    assert complete == 4366
    assert mismatches == 0


def test_phase2a_spread_is_historical_per_bar_price():
    manifest = json.loads((ROOT / "manifest.json").read_text())
    m15 = pd.read_csv(RAW / "xauusd_XAUUSDm_M15.csv")
    spread_price = m15.spread * 0.001
    assert spread_price.nunique() == 30
    assert spread_price.min() == manifest["datasets"]["M15"]["spread_price"]["min"]
    assert spread_price.max() == manifest["datasets"]["M15"]["spread_price"]["max"]
    assert spread_price.max() > spread_price.min()
