"""First-class registry of selectable market datasets.

Before this existed the dataset was inferred from the instrument, so "BTCUSD"
silently meant the legacy Bitstamp CSV and nothing else. That is fine while
there is one BTC dataset and dangerous the moment there are two: an experiment
labelled Exness could quietly have run on Bitstamp candles.

A dataset is now an explicit selection with its own identity, and everything
downstream — spread handling, broker profile, experiment record — is derived
from that selection rather than guessed from the instrument name.

Nothing here downloads or writes market data. Bitstamp's update path stays
exactly where it was, in services/bitstamp.py, and is reachable only for the
Bitstamp dataset.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

#: Legacy Bitstamp BTC/USD. Downloadable and writable through the UI.
BITSTAMP_BTCUSD_15M = "BITSTAMP_BTCUSD_15M"
#: Validated Exness broker-native BTCUSDm. Read-only from the UI.
EXNESS_BTCUSDM_M15 = "EXNESS_BTCUSDM_M15"
EXNESS_BTCUSDM_H1 = "EXNESS_BTCUSDM_H1"
#: Existing Exness gold datasets, registered so the registry is the one place
#: that answers "what can I run on?".
EXNESS_XAUUSDM_M15 = "EXNESS_XAUUSDM_M15"
EXNESS_XAUUSDM_H1 = "EXNESS_XAUUSDM_H1"

EXNESS_BTC_ROOT = ROOT / "data" / "exness" / "btc" / "phase_r1"
GOLD_ROOT = ROOT / "data" / "exness" / "gold" / "phase2a"


@dataclass(frozen=True)
class MarketDataset:
    """One selectable dataset. `key` is what an experiment records."""

    key: str
    label: str
    instrument: str
    symbol: str
    broker: str
    source: str
    timeframe: str
    step_seconds: int
    path: Path
    #: CONSTANT keeps the calibrated single-spread assumption. A dataset that
    #: carries a real per-bar spread declares BROKER_NATIVE_PER_BAR, and the UI
    #: must not override it with a typed-in number.
    spread_source: str
    #: Read-only datasets are validated evidence. The UI never writes them.
    read_only: bool
    #: Only the Bitstamp dataset has a download/update path.
    supports_update: bool
    manifest_path: Path | None = None
    notes: str = ""

    @property
    def carries_per_bar_spread(self) -> bool:
        return self.spread_source == "BROKER_NATIVE_PER_BAR"

    @property
    def exists(self) -> bool:
        return self.path.exists()


_REGISTRY: tuple[MarketDataset, ...] = (
    MarketDataset(
        key=BITSTAMP_BTCUSD_15M,
        label="Bitstamp BTC/USD · 15m (legacy)",
        instrument="BTCUSD", symbol="BTC/USD",
        broker="Bitstamp (public exchange API)",
        source="Bitstamp public OHLC API",
        timeframe="15m", step_seconds=900,
        path=ROOT / "data" / "btcusd_15m.csv",
        spread_source="CONSTANT",
        read_only=False, supports_update=True,
        notes="Exchange mid candles. No broker spread in the file; the audited "
              "engine applies the configured constant spread as synthetic Bid/Ask.",
    ),
    MarketDataset(
        key=EXNESS_BTCUSDM_M15,
        label="Exness BTCUSDm · M15 (validated R1)",
        instrument="BTCUSD", symbol="BTCUSDm",
        broker="Exness Technologies Ltd",
        source="Exness MT5 broker history (Phase R1, validated)",
        timeframe="15m", step_seconds=900,
        path=EXNESS_BTC_ROOT / "processed" / "btcusdm_M15.csv",
        spread_source="BROKER_NATIVE_PER_BAR",
        read_only=True, supports_update=False,
        manifest_path=EXNESS_BTC_ROOT / "manifest.json",
        notes="Broker-native candles carrying a real per-bar spread. Read-only: "
              "this is the dataset the Stage 2 parity certifications rest on.",
    ),
    MarketDataset(
        key=EXNESS_BTCUSDM_H1,
        label="Exness BTCUSDm · H1 (validated R1)",
        instrument="BTCUSD", symbol="BTCUSDm",
        broker="Exness Technologies Ltd",
        source="Exness MT5 broker history (Phase R1, validated)",
        timeframe="1h", step_seconds=3600,
        path=EXNESS_BTC_ROOT / "processed" / "btcusdm_H1.csv",
        spread_source="BROKER_NATIVE_PER_BAR",
        read_only=True, supports_update=False,
        manifest_path=EXNESS_BTC_ROOT / "manifest.json",
        notes="Broker H1. The frozen Core derives its own H1 context from M15, "
              "so this is for inspection and reconciliation rather than backtests.",
    ),
    MarketDataset(
        key=EXNESS_XAUUSDM_M15,
        label="Exness XAUUSDm · M15",
        instrument="XAUUSDm", symbol="XAUUSDm",
        broker="Exness Technologies Ltd",
        source="Exness MT5 broker history (Phase 2A)",
        timeframe="15m", step_seconds=900,
        path=GOLD_ROOT / "processed" / "xauusd_XAUUSDm_M15.csv",
        spread_source="BROKER_NATIVE_PER_BAR",
        read_only=True, supports_update=False,
    ),
    MarketDataset(
        key=EXNESS_XAUUSDM_H1,
        label="Exness XAUUSDm · H1",
        instrument="XAUUSDm", symbol="XAUUSDm",
        broker="Exness Technologies Ltd",
        source="Exness MT5 broker history (Phase 2A)",
        timeframe="1h", step_seconds=3600,
        path=GOLD_ROOT / "processed" / "xauusd_XAUUSDm_H1.csv",
        spread_source="BROKER_NATIVE_PER_BAR",
        read_only=True, supports_update=False,
    ),
)


def all_datasets() -> tuple[MarketDataset, ...]:
    return _REGISTRY


def dataset(key: str) -> MarketDataset:
    for entry in _REGISTRY:
        if entry.key == key:
            return entry
    raise KeyError(f"Unknown market dataset {key!r}")


def datasets_for_instrument(instrument: str, timeframe: str | None = None
                            ) -> tuple[MarketDataset, ...]:
    return tuple(entry for entry in _REGISTRY
                 if entry.instrument == instrument
                 and (timeframe is None or entry.timeframe == timeframe))


def default_dataset(instrument: str, timeframe: str = "15m") -> MarketDataset:
    """Preserves the previous behaviour: BTCUSD still defaults to Bitstamp."""
    if instrument == "BTCUSD":
        return dataset(BITSTAMP_BTCUSD_15M if timeframe == "15m" else EXNESS_BTCUSDM_H1)
    options = datasets_for_instrument(instrument, timeframe)
    if not options:
        raise KeyError(f"No dataset registered for {instrument} {timeframe}")
    return options[0]


@lru_cache(maxsize=16)
def _manifest(path_text: str) -> dict:
    try:
        return json.loads(Path(path_text).read_text())
    except (OSError, ValueError):
        return {}


def manifest(entry: MarketDataset) -> dict:
    if entry.manifest_path is None or not entry.manifest_path.exists():
        return {}
    return _manifest(str(entry.manifest_path))


@dataclass(frozen=True)
class DatasetSummary:
    """What the UI shows so the active dataset is never ambiguous."""

    key: str
    label: str
    broker: str
    source: str
    symbol: str
    timeframe: str
    path: str
    bars: int
    first_candle: str
    last_candle: str
    segments: int
    gapped_candles: int
    fingerprint: str
    spread_source: str
    spread_points_median: float | None
    read_only: bool


def summarise(entry: MarketDataset) -> DatasetSummary:
    """Load and describe a dataset. Read-only; never writes or downloads."""
    from core.fingerprints import sha256_file
    from utils.data_validation import continuous_segments, load_ohlcv_csv, missing_gaps

    data = load_ohlcv_csv(entry.path)
    segments = continuous_segments(data, entry.step_seconds)
    gaps = missing_gaps(data, entry.step_seconds)
    median_spread = None
    if entry.carries_per_bar_spread:
        raw = pd.read_csv(entry.path)
        if "spread_points" in raw.columns:
            median_spread = float(pd.to_numeric(raw["spread_points"]).median())
    return DatasetSummary(
        key=entry.key, label=entry.label, broker=entry.broker, source=entry.source,
        symbol=entry.symbol, timeframe=entry.timeframe,
        path=str(entry.path.relative_to(ROOT)),
        bars=int(len(data)),
        first_candle=str(data["timestamp"].iloc[0]) if len(data) else "-",
        last_candle=str(data["timestamp"].iloc[-1]) if len(data) else "-",
        segments=len(segments),
        gapped_candles=sum(gap.missing_candles for gap in gaps),
        fingerprint=sha256_file(entry.path),
        spread_source=entry.spread_source,
        spread_points_median=median_spread,
        read_only=entry.read_only,
    )
