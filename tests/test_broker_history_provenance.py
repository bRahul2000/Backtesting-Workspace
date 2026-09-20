"""Provenance comparison between a validated broker export and a fresh one.

Fixtures are tiny in-memory exports. They never touch data/ and never claim to
be broker data.
"""
from pathlib import Path

import pandas as pd
import pytest

from tools.compare_broker_history import CERTIFIED_WINDOWS, compare, load

ROOT = Path(__file__).resolve().parents[1]
HEADER = ["timestamp", "open", "high", "low", "close",
          "tick_volume", "spread", "real_volume"]


def _bar(stamp, close="100.50", volume="271", spread="1400"):
    return [stamp, "100.00", "101.00", "99.00", close, volume, spread, "0"]


def _export(rows, tmp_path, name):
    path = tmp_path / name
    pd.DataFrame(rows, columns=HEADER).to_csv(path, index=False)
    return load(path)


def _window_bars(name, count=3):
    """Bars inside one of the windows the comparator watches."""
    start = pd.Timestamp(CERTIFIED_WINDOWS[name][0], tz="UTC") + pd.Timedelta(days=5)
    return [(start + i * pd.Timedelta(minutes=15)).strftime("%Y.%m.%d %H:%M:%S")
            for i in range(count)]


def test_an_unchanged_export_compares_identical(tmp_path):
    rows = [_bar(s) for s in _window_bars("window1 (certified)")]
    report = compare(_export(rows, tmp_path, "a.csv"),
                     _export(rows, tmp_path, "b.csv"), 900)
    assert report["identical"] is True
    assert report["changed_bars"] == 0
    assert all(w["clean"] for w in report["windows"].values())


def test_a_revised_price_inside_a_certified_window_is_flagged(tmp_path):
    stamps = _window_bars("window1 (certified)")
    old = [_bar(s) for s in stamps]
    new = [_bar(s) for s in stamps]
    new[1][4] = "100.51"
    report = compare(_export(old, tmp_path, "o.csv"),
                     _export(new, tmp_path, "n.csv"), 900)
    assert report["identical"] is False
    assert report["price_fields_changed"] == ["close"]
    assert report["windows"]["window1 (certified)"]["clean"] is False
    assert report["windows"]["window1 (certified)"]["revised_fields"] == ["close"]


def test_a_revised_tick_volume_is_a_revision_but_not_a_price_change(tmp_path):
    stamps = _window_bars("window3 (daily cap)")
    old = [_bar(s) for s in stamps]
    new = [_bar(s) for s in stamps]
    new[0][5] = "270"
    report = compare(_export(old, tmp_path, "o.csv"),
                     _export(new, tmp_path, "n.csv"), 900)
    assert report["identical"] is False
    assert report["changes_per_field"] == {"tick_volume": 1}
    assert report["price_fields_changed"] == []
    assert report["windows"]["window3 (daily cap)"]["clean"] is False


def test_reformatting_the_same_value_is_not_reported_as_a_revision(tmp_path):
    stamps = _window_bars("window1 (certified)")
    old = [_bar(s, close="100.50") for s in stamps]
    new = [_bar(s, close="100.5") for s in stamps]
    report = compare(_export(old, tmp_path, "o.csv"),
                     _export(new, tmp_path, "n.csv"), 900)
    assert report["changed_bars"] == 0
    assert report["reformatted_only_fields"] == len(stamps)
    assert report["identical"] is True


def test_a_dropped_bar_is_reported_with_the_gap_it_creates(tmp_path):
    stamps = _window_bars("window2 (certified)", count=4)
    old = [_bar(s) for s in stamps]
    new = [_bar(s) for i, s in enumerate(stamps) if i != 2]
    report = compare(_export(old, tmp_path, "o.csv"),
                     _export(new, tmp_path, "n.csv"), 900)
    assert report["bars_only_in_old_count"] == 1
    assert report["bars_only_in_new_count"] == 0
    assert report["gaps_new"] > report["gaps_old"]
    assert report["windows"]["window2 (certified)"]["bars_removed"] == 1
    assert report["windows"]["window2 (certified)"]["clean"] is False
    assert report["identical"] is False


def test_an_added_bar_is_reported(tmp_path):
    stamps = _window_bars("window1 (certified)", count=4)
    old = [_bar(s) for i, s in enumerate(stamps) if i != 2]
    new = [_bar(s) for s in stamps]
    report = compare(_export(old, tmp_path, "o.csv"),
                     _export(new, tmp_path, "n.csv"), 900)
    assert report["bars_only_in_new_count"] == 1
    assert report["windows"]["window1 (certified)"]["bars_added"] == 1
    assert report["identical"] is False


def test_a_duplicate_bar_in_an_export_is_refused(tmp_path):
    stamps = _window_bars("window1 (certified)", count=2)
    rows = [_bar(stamps[0]), _bar(stamps[0]), _bar(stamps[1])]
    path = tmp_path / "dupe.csv"
    pd.DataFrame(rows, columns=HEADER).to_csv(path, index=False)
    with pytest.raises(ValueError, match="duplicate bar"):
        load(path)


def test_a_change_outside_every_watched_window_leaves_them_clean(tmp_path):
    stamps = ["2024.05.01 00:00:00", "2024.05.01 00:15:00"]
    old = [_bar(s) for s in stamps]
    new = [_bar(s) for s in stamps]
    new[0][4] = "100.51"
    report = compare(_export(old, tmp_path, "o.csv"),
                     _export(new, tmp_path, "n.csv"), 900)
    assert report["identical"] is False
    assert all(w["clean"] for w in report["windows"].values())


def test_the_validated_r1_export_still_matches_its_recorded_hashes():
    """The original raw export must never be modified by any provenance work."""
    import hashlib

    recorded = ROOT / "data/exness/btc/provenance/R1_BASELINE_HASHES.txt"
    if not recorded.exists():
        pytest.skip("baseline hash file not present in this checkout")
    checked = 0
    for line in recorded.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        digest, name = line.split(maxsplit=1)
        path = ROOT / name.strip()
        if not path.exists():
            pytest.skip(f"{name.strip()} not present in this checkout")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual == digest, f"{name.strip()} has been modified"
        checked += 1
    assert checked == 5
