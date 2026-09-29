"""Gold Range Hunter semantics parity: run strategies/grh_semantics_probe_v6.pine on Zoneflow's EXNESS XAUUSDm M15 bars
and compare its ``ZF|GRH|`` log lines with the same probe's TradingView Pine Logs, bar by bar.

    python -m ui.tradingview_mode.pine.parity.grh_probe [TV_PINE_LOGS.txt] [--json REPORT.json]

Every logged value depends only on the bar's time (input.time date filter, time(timeframe.period, session,
"Asia/Kolkata"), month / dayofweek / hour / minute in Asia/Kolkata, input.color defaults), so the comparison is
independent of the price feed:

* PINE SEMANTIC PARITY - a bar present in both logs whose fields differ is a semantic mismatch;
* DATA-SOURCE DIFFERENCE - a bar present on only one side (the feeds' trading hours / missing bars differ) is listed
  separately and is never counted as a semantic result.

Only rows before 2026-06-03 are read from the dataset (Gold V2 sealed windows start there).
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys

import pandas as pd

HERE = Path(__file__).resolve().parent
PROBE = HERE / "strategies" / "grh_semantics_probe_v6.pine"
CUTOFF = "2026-06-03"
FIELDS = ("time_close", "in_backtest", "morning_session_time", "ny_session_time", "month", "dayofweek_close",
          "hour_close", "minute_close", "box_fill_rgbt", "box_border_t")


def read_until(path: Path, cutoff: str = CUTOFF) -> pd.DataFrame:
    """The dataset's rows before ``cutoff`` (the sorted file is read line by line and never past it)."""
    keep = []
    with open(path) as handle:
        keep.append(handle.readline())
        for line in handle:
            if line[:10] >= cutoff:
                break
            keep.append(line)
    frame = pd.read_csv(io.StringIO("".join(keep)))
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


def parse(text: str) -> dict[int, dict]:
    """``ZF|GRH|time|...`` lines (TradingView timestamp prefixes and other noise are ignored) -> time -> fields."""
    rows = {}
    for line in text.splitlines():
        if "ZF|GRH|" not in line:
            continue
        parts = line[line.index("ZF|GRH|"):].strip().split("|")[2:]
        if len(parts) != len(FIELDS) + 1:
            raise ValueError(f"malformed probe line: {line!r}")
        rows[int(parts[0])] = dict(zip(FIELDS, parts[1:]))
    return rows


def ours() -> dict[int, dict]:
    from ...component.security_data import all_datasets
    from ..engine import PineExecution, compile_script, data_context, run_script

    entry = next(d for d in all_datasets() if d.key == "EXNESS_XAUUSDM_M15")
    frame = read_until(entry.path)
    result = compile_script(PROBE.read_text())
    if not result.ok:
        raise ValueError("; ".join(d.text() for d in result.diagnostics))
    execution = PineExecution(result.program, {})
    data = data_context(frame, timeframe_seconds=900, ticker="XAUUSDm", tickerid="EXNESS:XAUUSDm", mintick=0.001,
                        kind="cfd")
    out = run_script(execution, data, ("grh-probe",), "p")
    if out.error:
        raise RuntimeError(out.error)
    return parse("\n".join(text for _, _, text in execution.runtime.logs))


def compare(tv: dict[int, dict], zf: dict[int, dict]) -> dict:
    both = sorted(set(tv) & set(zf))
    mismatches = [{"time": t, "field": f, "tradingview": tv[t][f], "zoneflow": zf[t][f]}
                  for t in both for f in FIELDS if tv[t][f] != zf[t][f]]
    return {"bars_compared": len(both), "semantic_mismatches": mismatches,
            "data_source_only_tradingview": sorted(set(tv) - set(zf)),
            "data_source_only_zoneflow": sorted(set(zf) - set(tv)),
            "semantic_parity": bool(both) and not mismatches}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("tradingview_logs", nargs="?", help="copied TradingView Pine Logs of the probe")
    parser.add_argument("--json", help="write the machine-readable report here")
    args = parser.parse_args(argv)
    zf = ours()
    if not args.tradingview_logs:
        for t, row in sorted(zf.items()):
            print(t, *row.values())
        return 0
    report = compare(parse(Path(args.tradingview_logs).read_text(encoding="utf-8-sig")), zf)
    print(f"bars compared: {report['bars_compared']} · semantic mismatches: {len(report['semantic_mismatches'])} · "
          f"only on TradingView: {len(report['data_source_only_tradingview'])} · "
          f"only on Zoneflow: {len(report['data_source_only_zoneflow'])}")
    for m in report["semantic_mismatches"][:20]:
        print("  MISMATCH", m)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1) + "\n")
    return 0 if report["semantic_parity"] else 1


if __name__ == "__main__":
    sys.exit(main())
