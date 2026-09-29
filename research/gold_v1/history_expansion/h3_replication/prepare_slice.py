"""Cut the H3 replication slice out of the expanded raw export at TEXT level (no value is parsed).

    venv/bin/python research/gold_v1/history_expansion/h3_replication/prepare_slice.py

Keeps M15 lines with WARMUP_START <= timestamp < REPLICATION_END_EXCL. Everything else never leaves the raw file:
the artifact era (< 2021-09-01), the reserved holdout (2021-09-01 … 2022-11-26), the development period (the
session opening 2025-12-22 23:00 UTC onward), the sealed 2026 validation/OOS and later bars.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = HERE.parent / "raw" / "xauusd_XAUUSDm_M15.csv"
OUT = HERE / "data" / "xauusd_XAUUSDm_M15_h3_replication_slice.csv"
WARMUP_START = "2022.11.27 23:00:00"          # first warm-up session (preregistered)
REPLICATION_END_EXCL = "2025.12.22 23:00:00"  # the 2025-12-23 development session opens here


def main() -> None:
    kept = 0
    with open(RAW) as src, open(OUT, "w") as dst:
        dst.write(src.readline())             # header
        for line in src:
            ts = line[:19]
            if WARMUP_START <= ts < REPLICATION_END_EXCL:
                dst.write(line)
                kept += 1
    print(f"kept {kept} M15 lines {WARMUP_START} <= t < {REPLICATION_END_EXCL}")


if __name__ == "__main__":
    main()
