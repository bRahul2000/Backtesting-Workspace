"""Workspace (chart) history refresh: stale detection, closed-bar-only incremental append from the MT5 sources,
validation, and strict separation from the frozen research datasets (workspace_data.py)."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from services.market_datasets import EXNESS_BTCUSDM_M15, EXNESS_XAUUSDM_H1, EXNESS_XAUUSDM_M15, dataset
from ui.tradingview_mode.component import protocol
from ui.tradingview_mode.component import workspace_data as W

ROOT = Path(__file__).resolve().parents[2]
T0 = pd.Timestamp("2026-09-18 19:00", tz="UTC")


def bars(start: pd.Timestamp, n: int, step_min: int = 15, price: float = 4380.0) -> list[tuple]:
    rows = []
    for i in range(n):
        o = price + i * 0.5
        rows.append((start + pd.Timedelta(minutes=step_min * i), o, o + 2.0, o - 1.5, o + 0.25, 100.0 + i))
    return rows


def write_frozen(path: Path, rows: list[tuple]) -> None:
    lines = ["timestamp,open,high,low,close,volume"]
    lines += [f"{t.strftime('%Y-%m-%dT%H:%M:%SZ')},{o},{h},{l},{c},{v}" for t, o, h, l, c, v in rows]
    path.write_text("\n".join(lines) + "\n")


def write_export(folder: Path, name: str, rows: list[tuple], *, captured: pd.Timestamp, offset: int = 0,
                 symbol: str = "XAUUSDm", period: str = "M15", meta: bool = True) -> None:
    lines = ["timestamp,open,high,low,close,tick_volume,spread,real_volume"]
    lines += [f"{(t + pd.Timedelta(seconds=offset)).strftime('%Y.%m.%d %H:%M:%S')},{o:.3f},{h:.3f},{l:.3f},{c:.3f},"
              f"{int(v)},240,0" for t, o, h, l, c, v in rows]
    (folder / name).write_text("\n".join(lines) + "\n")
    if meta:
        (folder / f"{name}.metadata.json").write_text(json.dumps({
            "symbol": symbol, "timeframe": period, "server_utc_offset_seconds_at_capture": offset,
            "current_incomplete_bar_excluded": True,
            "capture_server_time": (captured + pd.Timedelta(seconds=offset)).strftime("%Y.%m.%d %H:%M:%S")}))


def write_seed(folder: Path, symbol: str, period: str, rows: list[tuple], *, written: pd.Timestamp,
               offset: int = 0) -> None:
    lines = ["time,open,high,low,close,tick_volume,spread"]
    lines += [f"{int(t.timestamp()) + offset},{o:.3f},{h:.3f},{l:.3f},{c:.3f},{int(v)},240" for t, o, h, l, c, v in rows]
    path = folder / f"tv_live_{symbol}_{period}_seed.csv"
    path.write_text("\n".join(lines) + "\n")
    stamp = written.timestamp()
    import os
    os.utime(path, (stamp, stamp))
    (folder / f"tv_live_{symbol}_quote.json").write_text(json.dumps(
        {"symbol": symbol, "server_time": int(stamp) + offset, "gmt_time": int(stamp)}))


@pytest.fixture
def env(tmp_path, monkeypatch):
    common, workspace, frozen_dir = tmp_path / "common", tmp_path / "workspace", tmp_path / "frozen"
    for folder in (common, workspace, frozen_dir):
        folder.mkdir()
    monkeypatch.setenv("TV_MT5_COMMON_FILES", str(common))
    monkeypatch.setenv(W.WORKSPACE_ENV, str(workspace))
    frozen = frozen_dir / "xauusd_XAUUSDm_M15.csv"
    write_frozen(frozen, bars(T0, 7))                      # 19:00 ... 20:30 (the Phase 2A end)
    entry = replace(dataset(EXNESS_XAUUSDM_M15), path=frozen)
    return entry, common, workspace, frozen


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_no_source_is_unknown_and_never_current(env):
    entry, *_ = env
    status = W.freshness(entry)
    assert status["status"] == "UNKNOWN" and status["last_local"] == "2026-09-18 20:30"
    assert status["latest_available"] is None and status["refreshable"] is True
    with pytest.raises(W.RefreshError, match="no readable MT5 source"):
        W.refresh(entry)


def test_refresh_appends_only_new_closed_bars_from_export_and_seed(env):
    entry, common, workspace, frozen = env
    before = sha(frozen)
    history = bars(T0, 7) + bars(T0 + pd.Timedelta(minutes=105), 6)          # through 21:45 (overlap + new)
    write_export(common, "xauusd_XAUUSDm_M15.csv", history, captured=pd.Timestamp("2026-09-18 22:00", tz="UTC"))
    seed = bars(T0 + pd.Timedelta(minutes=150), 6)                            # 21:30 ... 22:45; 22:45 is forming
    write_seed(common, "XAUUSDm", "M15", seed, written=pd.Timestamp("2026-09-18 22:45", tz="UTC"))
    status = W.freshness(entry)
    assert (status["status"], status["last_local"], status["latest_available"]) == \
        ("STALE", "2026-09-18 20:30", "2026-09-18 22:30")
    result = W.refresh(entry, now=pd.Timestamp("2026-09-18 22:50", tz="UTC").to_pydatetime())
    assert result["appended"] == 8 and result["first_appended"] == "2026-09-18 20:45"
    assert result["last_closed"] == "2026-09-18 22:30"                     # the forming 22:45 bar is not stored
    merged = W.load(entry)
    assert len(merged) == 15 and not merged["timestamp"].duplicated().any()
    assert merged["timestamp"].is_monotonic_increasing
    assert merged["timestamp"].iloc[-1] == pd.Timestamp("2026-09-18 22:30", tz="UTC")
    assert sha(frozen) == before                                             # the frozen dataset is untouched
    assert W.freshness(entry)["status"] == "CURRENT"
    again = W.refresh(entry)
    assert again["appended"] == 0 and len(W.load(entry)) == 15
    meta = json.loads(W.metadata_path(entry).read_text())
    assert meta["role"].startswith("WORKSPACE") and meta["last_closed_bar_utc"] == "2026-09-18T22:30:00+00:00"
    assert meta["rows"] == 8 and len(meta["refreshes"]) == 1
    assert {s["kind"] for s in meta["refreshes"][0]["sources"]} == {"mt5_export", "mt5_live_seed"}
    assert meta["extension_sha256"] == sha(W.extension_path(entry))
    assert sorted(p.name for p in workspace.iterdir()) == ["EXNESS_XAUUSDM_M15.csv", "EXNESS_XAUUSDM_M15.metadata.json"]


def test_existing_workspace_rows_are_preserved_and_later_refreshes_append(env):
    entry, common, *_ = env
    write_export(common, "xauusd_XAUUSDm_M15.csv", bars(T0, 9), captured=pd.Timestamp("2026-09-18 21:15", tz="UTC"))
    assert W.refresh(entry)["appended"] == 2
    first = W.extension_path(entry).read_text()
    write_export(common, "xauusd_XAUUSDm_M15.csv", bars(T0, 12), captured=pd.Timestamp("2026-09-18 22:00", tz="UTC"))
    assert W.refresh(entry)["appended"] == 3
    assert W.extension_path(entry).read_text().startswith(first)            # earlier rows kept byte for byte
    assert len(json.loads(W.metadata_path(entry).read_text())["refreshes"]) == 2


def test_export_bars_after_its_capture_time_are_not_closed(env):
    entry, common, *_ = env
    write_export(common, "xauusd_XAUUSDm_M15.csv", bars(T0, 10), captured=pd.Timestamp("2026-09-18 21:10", tz="UTC"))
    assert W.refresh(entry)["last_closed"] == "2026-09-18 20:45"            # 21:00 closes at 21:15 > capture


def test_server_offset_is_converted_to_utc(env):
    entry, common, *_ = env
    write_export(common, "xauusd_XAUUSDm_M15.csv", bars(T0, 9), captured=pd.Timestamp("2026-09-18 21:15", tz="UTC"),
                 offset=7200)
    result = W.refresh(entry)
    assert (result["first_appended"], result["last_closed"]) == ("2026-09-18 20:45", "2026-09-18 21:00")


def test_export_without_offset_metadata_is_not_used(env):
    entry, common, *_ = env
    write_export(common, "xauusd_XAUUSDm_M15.csv", bars(T0, 9), captured=T0, meta=False)
    status = W.freshness(entry)
    assert status["status"] == "UNKNOWN" and "server UTC offset" in status["problems"][0]


@pytest.mark.parametrize("mutate, message", [
    (lambda r: (r[0], r[1], r[4] - 1, r[3], r[4], r[5]), "inconsistent high/low"),
    (lambda r: (r[0], -1.0, r[2], r[3], r[4], r[5]), "non-positive"),
    (lambda r: (r[0] + pd.Timedelta(minutes=5), *r[1:]), "grid"),
])
def test_invalid_bars_abort_the_refresh_and_write_nothing(env, mutate, message):
    entry, common, workspace, _ = env
    rows = bars(T0, 10)
    rows[8] = mutate(rows[8])
    write_export(common, "xauusd_XAUUSDm_M15.csv", rows, captured=pd.Timestamp("2026-09-18 22:00", tz="UTC"))
    with pytest.raises(W.RefreshError, match=message):
        W.refresh(entry)
    assert list(workspace.iterdir()) == []


def test_writes_are_confined_to_the_workspace_folder(env, tmp_path):
    with pytest.raises(W.RefreshError, match="outside the workspace"):
        W._guard(tmp_path / "elsewhere.csv")
    with pytest.raises(W.RefreshError, match="research"):
        W._guard(W.workspace_root() / "research" / "x.csv")


def test_default_workspace_folder_is_gitignored_and_outside_research():
    assert W.DEFAULT_WORKSPACE_ROOT == ROOT / "data" / "workspace"
    assert "/data/workspace/" in (ROOT / ".gitignore").read_text().splitlines()
    research = ROOT / "research"
    for path in research.rglob("*.py"):
        text = path.read_text(errors="replace")
        assert "workspace_data" not in text and "data/workspace" not in text, path


def test_only_mt5_backed_datasets_are_refreshable():
    assert W.refreshable(dataset(EXNESS_XAUUSDM_M15)) and W.refreshable(dataset(EXNESS_XAUUSDM_H1))
    assert W.refreshable(dataset(EXNESS_BTCUSDM_M15))
    assert not W.refreshable(dataset("BITSTAMP_BTCUSD_15M"))


def test_payload_data_status_validation():
    from tests.tradingview_mode.test_component_terminal import payload_for

    payload = payload_for()
    assert payload["data_status"] is None                                   # optional
    good = {"status": "STALE", "refreshable": True, "last_local": "2026-09-18 20:30",
            "latest_available": "2026-09-29 12:15", "source_captured": "2026-09-29 12:30"}
    protocol.validate_payload({**payload, "data_status": good})
    for bad, message in (({**good, "status": "FRESH"}, "CURRENT, STALE or UNKNOWN"),
                         ({**good, "status": "CURRENT", "latest_available": None}, "known latest available"),
                         ({**good, "refreshable": "yes"}, "boolean")):
        with pytest.raises(protocol.PayloadValidationError, match=message):
            protocol.validate_payload({**payload, "data_status": bad})
    parsed = protocol.parse_event({"id": "e1", "type": "refresh_data", "data": {}})
    assert parsed.type in protocol.DATA_EVENTS
    with pytest.raises(protocol.EventValidationError):
        protocol.parse_event({"id": "e2", "type": "refresh_data", "data": {"dataset_key": "X"}})


def test_refresh_is_rejected_outside_historical_mode():
    from ui.tradingview_mode.component.replay import ReplayState
    from ui.tradingview_mode.component.state import TerminalState
    from ui.tradingview_mode.component.terminal import refresh_workspace_data

    replaying = TerminalState(dataset_key=EXNESS_XAUUSDM_M15, timeframe="15m",
                              replay=ReplayState(EXNESS_XAUUSDM_M15, "15m", 0, 0, 0))
    entry = refresh_workspace_data(replaying)
    assert entry.level == "error" and "Historical mode" in entry.message
    bitstamp = refresh_workspace_data(TerminalState(dataset_key="BITSTAMP_BTCUSD_15M", timeframe="15m"))
    assert bitstamp.level == "error" and "no local MT5 source" in bitstamp.message
