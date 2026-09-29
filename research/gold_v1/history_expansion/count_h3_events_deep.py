"""Count frozen-H3 events in a candidate older era — DETECTION ONLY (no forward race, no outcomes, no controls).

    venv/bin/python research/gold_v1/history_expansion/count_h3_events_deep.py <warmup_start> <era_start> <era_end_excl>
    e.g.  … 2014.02.01 2014.03.01 2019.12.01          (timestamps as YYYY.MM.DD[ HH:MM:SS], UTC)

Reads raw_full/xauusd_XAUUSDm_M15.csv by TEXT slice [warmup_start, era_end_excl), which must end before 2019-12-23
(the known artifact era and everything later are refused). Runs the frozen h1_study.features / h3_study.h3_features /
h3_study.detect unchanged and prints event counts per year and side. `h1_study.forward` is never called.
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True
from pathlib import Path                                                                # noqa: E402

import pandas as pd                                                                     # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "h1"))
sys.path.insert(0, str(HERE.parent / "h3"))
import h1_study as h1                                                                   # noqa: E402
import h3_study as h3                                                                   # noqa: E402

LIMIT = "2019.12.23"


def main(warmup: str, start: str, end_excl: str) -> None:
    assert warmup <= start < end_excl <= LIMIT, "era must end on or before 2019-12-23"
    lines = []
    with open(HERE / "raw_full" / "xauusd_XAUUSDm_M15.csv") as fh:
        header = fh.readline().rstrip("\n").split(",")
        for line in fh:
            if warmup <= line[:19] < end_excl:
                lines.append(line.rstrip("\n").split(","))
    raw = pd.DataFrame(lines, columns=header)
    raw["time"] = pd.to_datetime(raw["timestamp"], format="%Y.%m.%d %H:%M:%S", utc=True)
    for c in ("open", "high", "low", "close"):
        raw[c] = raw[c].astype(float)
    for c in ("tick_volume", "spread", "real_volume"):
        raw[c] = raw[c].astype(int)
    f = h3.h3_features(h1.features(raw.drop(columns=["timestamp"]).reset_index(drop=True)))
    events, counts, _ = h3.detect(f)
    t0 = pd.Timestamp(start.replace(".", "-"), tz="UTC")
    ev = events[events["signal_time"] >= t0]
    sessions = f[f["time"] >= t0].groupby("tday").size()
    print(f"bars loaded {len(raw)}; sessions in era {len(sessions)} (>=60 bars: {(sessions >= 60).sum()})")
    print("events in era:", len(ev), "| warm-up events excluded:", len(events) - len(ev))
    print(ev.groupby([ev["signal_time"].dt.year, "direction"]).size().unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main(*sys.argv[1:4])
