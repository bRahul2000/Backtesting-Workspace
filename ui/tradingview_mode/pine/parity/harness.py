"""Run parity fixtures through this engine and compare them with TradingView references.

Reference sources (``Reference.source``), strongest first:

* ``tradingview-export`` - ``tradingview/<fixture>.csv``: TradingView's "Export chart data" CSV
  captured by us from a chart with the fixture script added.
* ``tradingview-spot`` - ``tradingview/<fixture>.spot.csv``: values read from TradingView's Data
  Window by hand (``bar_index,output,value``).
* ``third-party-capture`` - ``external/*.json``: TradingView values captured and published by a
  third party (provenance recorded in the file).

Format: our outputs are written in the same wide layout as TradingView's export
(``time`` in UNIX seconds, ``open,high,low,close``, then one column per plot title;
an empty cell is ``na``). Shapes/chars/bgcolor/barcolor are ``1`` on bars where
they are drawn.

Comparison rules (never loosened to make a failure pass):

* ``na`` state must match exactly.
* When both values are integers (booleans plotted as 0/1, counts, bar offsets)
  they must be exactly equal.
* Otherwise ``|ours - tv| <= max(ABS_TOL, REL_TOL * |tv|, q)``. ``q`` is 0 for a
  full-precision file (some value printed with >= 12 decimals); for a file
  rounded to d decimals it is half a unit of the d-th decimal. A fixture whose
  compared non-integer values rely on q > ``MAX_RESOLUTION`` is INCONCLUSIVE, not PASS.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from .. import PineExecution, compile_script, run_script
from ..engine import data_context
from .fixtures import BY_NAME, FIXTURES, MANUAL_CHECKS, PERIOD, Fixture, synthetic_row

ABS_TOL = 1e-9
REL_TOL = 1e-9
MAX_RESOLUTION = 1e-6

ROOT = Path(__file__).parent
FIXTURE_DIR, DATA_DIR, OURS_DIR = ROOT / "fixtures", ROOT / "data", ROOT / "ours"
TV_DIR, EXTERNAL_DIR = ROOT / "tradingview", ROOT / "external"
REPORT = ROOT / "PARITY_REPORT.md"
SYNTHETIC_START = "2020-01-01"
SYNTHETIC_SECONDS = 86_400

CATEGORIES = ("parser bug", "type/qualifier bug", "series semantics bug", "built-in formula bug", "warm-up bug",
              "na behavior bug", "loop/control-flow bug", "render behavior bug", "TradingView-reference uncertainty")

#: (fixture, output) -> (category, note) for mismatches that remain after investigation.
CLASSIFICATIONS: dict[tuple[str, str], tuple[str, str]] = {}

#: Behaviour corrected in this phase, with the evidence that proved the old behaviour wrong.
FIXED = [
    ("ta.pivothigh / ta.pivotlow ties", "built-in formula bug",
     "Equal bars on both sides cancelled a pivot. TradingView: an equal bar on the LEFT keeps the pivot, an equal "
     "bar on the RIGHT cancels it (the later bar becomes the pivot).",
     "third-party TradingView capture (external/pinets_pr322_ties.json): all 4 pivot series mismatched before, 0 after"),
    ("ta.highestbars / ta.lowestbars ties", "built-in formula bug",
     "Ties returned the NEWEST bar. TradingView returns the OLDEST bar among equal extremes.",
     "third-party TradingView capture: all 4 offset series mismatched before, 0 after"),
    ("`for` end bound in v6", "loop/control-flow bug",
     "The end expression was evaluated once. v6 re-evaluates it before every iteration (direction fixed at the "
     "start); v5 evaluates it once.",
     "TradingView v6 migration guide, Loops page and release notes (March 2025); fixture s08/s09 for_dynamic_end"),
    ("v5 `const int / const int`", "type/qualifier bug",
     "7 / 2 returned 3.5 in v5. v5 truncates when both operands are `const int`; v6 keeps the fraction.",
     "TradingView v6 migration guide; fixture s08/s09 div_const"),
    ("v5 `and` / `or` evaluation", "series semantics bug",
     "Both versions short-circuited. v5 evaluates both operands (stateful calls on the right run every bar); "
     "v6 is lazy.", "TradingView v6 migration guide; fixture s08/s09 and_stateful"),
    ("na inside the source of ta.sma / ta.ema / ta.rma / ta.wma", "na behavior bug",
     "An na input poisoned the result: sma/wma stayed na while the na was in the window, ema/rma lost their "
     "state and re-seeded. TradingView: sma skips na (keeps 108.4 through the gap); ema/rma return na on na "
     "bars but keep their state; wma returns na on na bars and counts an na inside its window as the last "
     "value before it. Shared helpers, so functions built on them (rsi, atr, macd, bb, vwma, hma, dmi, "
     "supertrend, kc, tsi) follow the same rule for mid-series na; warm-up is unchanged.",
     "own TradingView capture: s01_averages page 2 / columns 2 (tradingview/s01_averages.spot.csv), "
     "failed on TradingView before the fix; 50 of 50 cells match after it"),
    ("ta.highest / ta.lowest on an na bar", "na behavior bug",
     "Returned the extreme of the other values in the window when the current value was na. TradingView "
     "returns na on an na bar and skips an older na inside the window.",
     "own TradingView quick check q1_main_v6: s11 na_highest failed at bars 5, 10, 15 (TradingView na); "
     "the fix changes exactly those 3 of 3824 expected cells; the rerun passed 3824/3824"),
    ("`barstate.isnew` on live bars", "series semantics bug",
     "After the first realtime tick it stayed false for every later bar, because it read a never-reset counter "
     "of forming-bar re-runs. It is now true on the first execution of each bar only.",
     "TradingView barstate.isnew definition; found by the var/varip live check (m01_live_varip, test_parity)"),
    ("`timeframe.period` in v6", "built-in formula bug",
     "Returned \"D\"/\"W\"/\"M\". v6 always includes the multiplier (\"1D\"); v5 keeps \"D\".",
     "TradingView v6 migration guide"),
]


#: Manual TradingView observations (tradingview/observations.json): key -> (question, this engine's behaviour).
OBSERVATIONS = {
    "plot_default_bridges_na": ("m02: does the default-style line (= plot.style_line) draw across the na bars?", True),
    "plot_style_line_bridges_na": ("s12: does `line_explicit` (explicit style=plot.style_line) draw across the na "
                                   "bars?", True),
    "plot_style_linebr_breaks_at_na": ("m02: does the plot.style_linebr line leave gaps at the na bars?", True),
    "varip_counts_ticks_within_bar": ("m03 live: do `varip count` / `varip ticks this bar` rise with every update "
                                      "of one forming bar?", True),
    "var_unchanged_within_realtime_bar": ("m03 live: does `var count` stay the same across updates of one forming "
                                          "bar?", True),
    "var_increments_on_new_bar": ("m03 live: does `var count` rise by exactly 1 and `varip ticks this bar` return "
                                  "to 1 when a new bar opens?", True),
    "isnew_first_update_only": ("m03 live: is `barstate.isnew` T on the first update of a bar and F afterwards?",
                                True),
}


def observations() -> dict:
    path = TV_DIR / "observations.json"
    return json.loads(path.read_text()) if path.exists() else {}


# ---- data ----------------------------------------------------------------------------------------------------

def synthetic_frame(n: int = PERIOD) -> pd.DataFrame:
    rows = [synthetic_row(i) for i in range(n)]
    frame = pd.DataFrame(rows).drop(columns="bar_index")
    frame.insert(0, "timestamp", pd.date_range(SYNTHETIC_START, periods=n, freq=f"{SYNTHETIC_SECONDS}s", tz="UTC"))
    return frame


def _seconds(frame: pd.DataFrame) -> int:
    if len(frame) < 2:
        return SYNTHETIC_SECONDS
    return int(pd.Series(frame["timestamp"]).diff().dt.total_seconds().dropna().median())


# ---- our side ------------------------------------------------------------------------------------------------

def run_ours(fixture: Fixture, frame: pd.DataFrame) -> pd.DataFrame:
    """Our outputs in TradingView's export layout (plus ``bi``), one row per bar."""
    result = compile_script(fixture.source)
    if not result.ok:
        raise RuntimeError(f"{fixture.name} does not compile: {[d.text() for d in result.errors]}")
    data = data_context(frame, timeframe_seconds=_seconds(frame), ticker="PARITY", tickerid="PARITY:PARITY",
                        mintick=0.01)
    run = run_script(PineExecution(result.program, {}), data, ("parity", fixture.name), "p")
    if run.error:
        raise RuntimeError(f"{fixture.name} failed at bar {run.error['bar_index']}: {run.error['message']}")
    times = [int(t.timestamp()) for t in frame["timestamp"]]
    out = pd.DataFrame({"time": times, "open": frame["open"].to_numpy(), "high": frame["high"].to_numpy(),
                        "low": frame["low"].to_numpy(), "close": frame["close"].to_numpy()})
    row_of = {t: i for i, t in enumerate(times)}
    for output in run.outputs:
        column = np.full(len(times), np.nan)
        if output["kind"] == "plot":
            for point in output["data"]:
                column[row_of[point["time"]]] = np.nan if point["value"] is None else point["value"]
        elif output["kind"] in ("shape", "char", "bgcolor", "barcolor"):
            for point in output["data"]:
                column[row_of[point["time"]]] = 1.0
        else:
            continue
        title = output.get("title") or f"{output['kind']}#{output['id']}"
        out[title] = column
    return out


def ours_csv(fixture: Fixture, frame: pd.DataFrame | None = None) -> str:
    table = run_ours(fixture, synthetic_frame() if frame is None else frame)
    return table.to_csv(index=False, na_rep="", float_format="%.17g", lineterminator="\n")


# ---- references ------------------------------------------------------------------------------------------------

@dataclass
class Reference:
    source: str
    path: Path
    table: pd.DataFrame                 # numeric, NaN = na; has a ``bi`` column
    quantum: float = 0.0                # half a unit of the reference's printed precision (0 = full precision)
    present: pd.DataFrame | None = None # spot checks: which cells were actually recorded
    provenance: str = ""


FULL_PRECISION_DECIMALS = 12


def _quantum(raw: pd.DataFrame, skip=("time", "bi")) -> float:
    """TradingView prints either full precision or a fixed number of decimals. If any value shows at least
    FULL_PRECISION_DECIMALS decimals the file is full precision; otherwise every value may be rounded to the
    most decimals any value shows."""
    columns = [c for c in raw.columns if c not in skip]
    most = raw[columns].map(_decimals).max().max() if columns else np.nan
    if np.isnan(most) or most >= FULL_PRECISION_DECIMALS:
        return 0.0
    return 0.5 * 10.0 ** (-most)


def _decimals(text) -> float:
    if not isinstance(text, str) or text.strip() in ("", "NaN", "nan", "na"):
        return np.nan
    text = text.strip().lower()
    if "e" in text:
        mantissa, exponent = text.split("e")
        return max(0, len(mantissa.split(".")[1]) if "." in mantissa else 0) - int(exponent)
    return len(text.split(".")[1]) if "." in text else 0


def _match_column(columns, title: str):
    for column in columns:
        if column == title:
            return column
    for column in columns:
        if column.strip().lower() == title.lower() or column.split(":")[-1].strip() == title:
            return column
    return None


def read_export(path: Path) -> Reference:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    raw.columns = [c.strip() for c in raw.columns]
    table = raw.apply(pd.to_numeric, errors="coerce")
    if "time" in raw.columns and table["time"].isna().any():
        table["time"] = pd.to_datetime(raw["time"], utc=True).astype("int64") // 10**9
    bi = _match_column(raw.columns, "bi")
    if bi is None:
        raise ValueError(f"{path.name}: no `bi` column (the fixture's first plot); was the right script exported?")
    table = table.rename(columns={bi: "bi"})
    return Reference("tradingview-export", path, table, _quantum(raw.rename(columns={bi: "bi"})))


def read_spot(path: Path) -> Reference:
    raw = pd.read_csv(path, dtype=str, keep_default_na=False)
    raw["bar_index"] = raw["bar_index"].astype(int)
    wide = raw.pivot(index="bar_index", columns="output", values="value").reset_index().rename(
        columns={"bar_index": "bi"})
    present = wide.notna()                               # a cell nobody wrote down is not compared
    table = wide.apply(pd.to_numeric, errors="coerce")
    return Reference("tradingview-spot", path, table, _quantum(raw.rename(columns={"value": "v"})[["v"]]), present)


def read_external(path: Path) -> Reference:
    spec = json.loads(path.read_text())
    period, first, last = spec["period"], spec["compare_from_bar"], spec["compare_to_bar"]
    rows = {"bi": list(range(first, last + 1))}
    for name, values in spec["outputs"].items():
        rows[name] = [np.nan if values[b % period] == "na" else float(values[b % period]) for b in rows["bi"]]
    return Reference("third-party-capture", path, pd.DataFrame(rows), provenance=spec.get("provenance", ""))


def references(fixture: Fixture) -> list[Reference]:
    found = []
    export, spot = TV_DIR / f"{fixture.name}.csv", TV_DIR / f"{fixture.name}.spot.csv"
    if export.exists():
        found.append(read_export(export))
    if spot.exists():
        found.append(read_spot(spot))
    for path in sorted(EXTERNAL_DIR.glob("*.json")):
        if json.loads(path.read_text()).get("fixture") == fixture.name:
            found.append(read_external(path))
    return found


# ---- comparison ------------------------------------------------------------------------------------------------

@dataclass
class OutputResult:
    title: str
    compared: int = 0
    mismatches: int = 0
    na_mismatches: int = 0
    max_abs_diff: float = 0.0
    first_bar: int | None = None
    first_time: int | None = None
    first_values: tuple | None = None
    resolution: float = 0.0


@dataclass
class FixtureResult:
    fixture: Fixture
    reference: Reference
    bars: int
    outputs: list[OutputResult] = field(default_factory=list)
    timing: list[OutputResult] = field(default_factory=list)
    missing_in_reference: list[str] = field(default_factory=list)
    problem: str = ""

    @property
    def mismatches(self) -> int:
        return sum(o.mismatches for o in self.outputs + self.timing)

    @property
    def resolution(self) -> float:
        return max([o.resolution for o in self.outputs] or [0.0])

    @property
    def verdict(self) -> str:
        if self.problem:
            return "NOT COMPARED"
        if self.mismatches:
            return "FAIL"
        if self.resolution > MAX_RESOLUTION:
            return "INCONCLUSIVE"
        return "PASS"


def _integral(x: float) -> bool:
    return math.isfinite(x) and float(x).is_integer()


def compare_values(ours: float, tv: float, quantum: float = 0.0) -> tuple[bool, float, float]:
    """(match, abs diff, reference quantum that applied). NaN means na."""
    if np.isnan(ours) or np.isnan(tv):
        return bool(np.isnan(ours) and np.isnan(tv)), 0.0, 0.0
    diff = abs(ours - tv)
    if _integral(ours) and _integral(tv):                  # booleans, counts, offsets: exact
        return ours == tv, diff, 0.0
    return diff <= max(ABS_TOL, REL_TOL * abs(tv), quantum), diff, quantum


def _our_frame(fixture: Fixture, ref: Reference) -> tuple[pd.DataFrame | None, str]:
    bis = ref.table["bi"].dropna().astype(int)
    if fixture.track == "synthetic":
        return synthetic_frame(int(bis.max()) + 1), ""
    table = ref.table
    needed = ["time", "open", "high", "low", "close"]
    volume = _match_column(table.columns, "vol")
    if any(c not in table.columns for c in needed) or volume is None:
        return None, "the export has no time/open/high/low/close/vol columns"
    if int(bis.iloc[0]) != 0 or not (bis.diff().dropna() == 1).all():
        return None, (f"the export starts at bar_index {int(bis.iloc[0])} (or skips bars); the chart track needs "
                      "every bar from bar_index 0 so warm-up is identical")
    frame = pd.DataFrame({"timestamp": pd.to_datetime(table["time"], unit="s", utc=True), "open": table["open"],
                          "high": table["high"], "low": table["low"], "close": table["close"],
                          "volume": table[volume]})
    return frame, ""


def compare_fixture(fixture: Fixture, ref: Reference) -> FixtureResult:
    frame, problem = _our_frame(fixture, ref)
    if frame is None:
        return FixtureResult(fixture, ref, 0, problem=problem)
    ours = run_ours(fixture, frame)
    ours["bi"] = range(len(ours))
    result = FixtureResult(fixture, ref, 0)
    rows = ref.table.dropna(subset=["bi"]).copy()
    rows["bi"] = rows["bi"].astype(int)
    rows = rows[rows["bi"] < len(ours)]
    result.bars = len(rows)
    skip = {"bi", "time", "open", "high", "low", "close"} | set(fixture.timing)
    for title in [c for c in ours.columns if c not in skip]:
        column = _match_column(ref.table.columns, title)
        if column is None:
            result.missing_in_reference.append(title)
            continue
        stat = OutputResult(title)
        for index, row in rows.iterrows():
            if ref.present is not None and not ref.present.at[index, column]:
                continue
            bar = int(row["bi"])
            ok, diff, quantum = compare_values(float(ours.at[bar, title]), float(row[column]), ref.quantum)
            stat.compared += 1
            stat.resolution = max(stat.resolution, quantum)
            if math.isfinite(diff):
                stat.max_abs_diff = max(stat.max_abs_diff, diff)
            if not ok:
                stat.mismatches += 1
                stat.na_mismatches += int(np.isnan(ours.at[bar, title]) != np.isnan(row[column]))
                if stat.first_bar is None:
                    stat.first_bar, stat.first_values = bar, (ours.at[bar, title], row[column])
                    stat.first_time = int(row["time"]) if "time" in row and not np.isnan(row["time"]) else int(
                        ours.at[bar, "time"])
        result.outputs.append(stat)
    for drawn, condition in fixture.timing.items():
        column = _match_column(ref.table.columns, condition)
        if column is None or drawn not in ours.columns:
            result.missing_in_reference.append(f"{drawn} (timing via {condition})")
            continue
        stat = OutputResult(f"{drawn} drawn on bars where {condition} = 1")
        for _, row in rows.iterrows():
            bar = int(row["bi"])
            drawn_here, expected = not np.isnan(ours.at[bar, drawn]), row[column] == 1
            stat.compared += 1
            if drawn_here != expected:
                stat.mismatches += 1
                if stat.first_bar is None:
                    stat.first_bar, stat.first_values = bar, (int(drawn_here), int(expected))
                    stat.first_time = int(ours.at[bar, "time"])
        result.timing.append(stat)
    return result


def compare_all() -> list[FixtureResult]:
    return [compare_fixture(f, ref) for f in FIXTURES for ref in references(f)]


# ---- report ----------------------------------------------------------------------------------------------------

def _fmt(x) -> str:
    if x is None:
        return "—"
    if isinstance(x, float) and np.isnan(x):
        return "na"
    return f"{x:.10g}" if isinstance(x, float) else str(x)


UNVERIFIED_REASON = {
    "c01_chart": "NOT VERIFIED — needs TradingView's chart-data export (not available on the Basic plan): ta.atr, "
                 "ta.tr, ta.vwma, ta.supertrend and the default-source overloads on real chart prices are unchecked",
    "s12_plots": "NOT VERIFIED numerically — only its na-gap drawing rule was observed (manual/m02); plotshape / "
                 "plotchar / bgcolor / barcolor timing is checked only against our own condition columns",
}


def verification_status() -> dict[str, str]:
    """Per fixture, what real TradingView evidence exists (manual tables, quick checks, third-party capture)."""
    from .manual import BY_FIXTURE
    from .quick import QUICK_SCRIPTS

    manual, quick = manual_results(), quick_results()
    status = {}
    for fixture in FIXTURES:
        parts, verified = [], False
        spec, entry = BY_FIXTURE.get(fixture.name), manual.get(fixture.name, {})
        if spec and entry.get("status") == "match":
            combos, checked = len(spec.pages) * len(spec.parts), len(set(entry.get("checked", [])))
            parts.append(f"manual tables {checked}/{combos} page·column settings")
            verified |= checked == combos
        for q in QUICK_SCRIPTS:
            result = quick.get(q.name, {}).get("fixtures", {}).get(fixture.name, "")
            if result.startswith("PASS"):
                parts.append(f"quick/{q.name} {result}")
                verified = True
        if verified:
            status[fixture.name] = "VERIFIED — " + "; ".join(parts)
        elif fixture.name == "x01_pinets_ties":
            status[fixture.name] = "third-party TradingView capture only (84 bars x 8 series, 0 mismatches)"
        else:
            status[fixture.name] = UNVERIFIED_REASON.get(
                fixture.name, "NOT VERIFIED" + (f" — partial: {'; '.join(parts)}" if parts else ""))
    return status


def report(results: list[FixtureResult]) -> str:
    by_fixture: dict[str, list[FixtureResult]] = {}
    for r in results:
        by_fixture.setdefault(r.fixture.name, []).append(r)
    status = verification_status()
    remaining = [(r, o) for r in results for o in r.outputs + r.timing if o.mismatches]
    lines = [
        "# Pine P1 parity report",
        "",
        "Generated by `python -m ui.tradingview_mode.pine.parity`. Compares this engine with **actual TradingView "
        "output** captured into `tradingview/` (and third-party TradingView captures in `external/`). Rules: `na` "
        "state exact; integers/booleans exact; floats within "
        f"`max({ABS_TOL:g}, {REL_TOL:g}·|tv|, q)` where q = 0 for a full-precision export and half a unit of the "
        f"printed decimals for a rounded one; a reference coarser than {MAX_RESOLUTION:g} is INCONCLUSIVE.",
        "",
        "## Status",
        "",
        f"- Fixtures: {len(FIXTURES)} ({sum(f.track == 'synthetic' for f in FIXTURES)} synthetic-data, "
        f"{sum(f.track == 'chart' for f in FIXTURES)} chart-data).",
        f"- Verified on real TradingView (own runs): **{sum(v.startswith('VERIFIED') for v in status.values())} / "
        f"{len(FIXTURES)}** fixtures (third-party capture counted separately).",
        f"- Remaining mismatches against captured cell values: **{sum(o.mismatches for _, o in remaining)}** in "
        f"{len(remaining)} output(s).",
        "",
        "| fixture | real TradingView status |", "|---|---|",
        *[f"| `{name}` | {text} |" for name, text in status.items()],
        "",
        "Verified means: every cell of the listed check was compared on TradingView with 0 failures. It covers "
        "exactly the bars/outputs of that check, nothing broader. Manual tables and quick checks compare inside "
        "TradingView, so they do not appear as captured cell files in the table below.",
        "",
    ]
    lines += ["## Fixtures", "",
              "| fixture | covers | TradingView expected | bars compared | mismatches | max abs diff | "
              "first mismatch (bar / time) | verdict |", "|---|---|---|---|---|---|---|---|"]
    for f in FIXTURES:
        rows = by_fixture.get(f.name)
        if not rows:
            verdict = "see Status (compared inside TradingView)" if status[f.name].startswith("VERIFIED") \
                else "NOT COMPARED"
            lines.append(f"| `{f.name}` | {', '.join(f.covers)} | no captured cell file | 0 | — | — | — | {verdict} |")
            continue
        for r in rows:
            first = min((o for o in r.outputs + r.timing if o.first_bar is not None), key=lambda o: o.first_bar,
                        default=None)
            where = "—" if first is None else f"{first.first_bar} / {pd.to_datetime(first.first_time, unit='s', utc=True):%Y-%m-%d %H:%M}"
            max_diff = max([o.max_abs_diff for o in r.outputs] or [0.0])
            lines.append(f"| `{f.name}` | {', '.join(f.covers)} | {r.reference.source}: `{r.reference.path.name}` | "
                         f"{r.bars} | {r.mismatches} | {max_diff:.3g} | {where} | {r.verdict} |")
    lines.append("")
    for f in FIXTURES:
        rows = by_fixture.get(f.name, [])
        lines += [f"### `{f.name}` — {f.title}", "", f"Track: {f.track}, Pine v{f.version}. Script: "
                  f"`fixtures/{f.name}.pine`; our output: `ours/{f.name}.csv`." + (f" {f.notes}" if f.notes else ""), ""]
        if not rows:
            lines += [f"Real TradingView: {status[f.name]}.", ""]
            continue
        for r in rows:
            lines.append(f"Reference: {r.reference.source} `{r.reference.path.name}`"
                         + (f" — {r.reference.provenance}" if r.reference.provenance else "") + ".")
            if r.problem:
                lines += ["", f"Not compared: {r.problem}.", ""]
                continue
            lines += ["", "| output | bars | mismatches | na mismatches | max abs diff | first mismatch (bar: ours vs tv) "
                          "| classification |", "|---|---|---|---|---|---|---|"]
            for o in r.outputs + r.timing:
                first = "—" if o.first_bar is None else f"{o.first_bar}: {_fmt(o.first_values[0])} vs {_fmt(o.first_values[1])}"
                label = CLASSIFICATIONS.get((f.name, o.title), ("UNCLASSIFIED — investigate", ""))[0] if o.mismatches else ""
                lines.append(f"| `{o.title}` | {o.compared} | {o.mismatches} | {o.na_mismatches} | {o.max_abs_diff:.3g} "
                             f"| {first} | {label} |")
            if r.missing_in_reference:
                lines.append(f"\nNot in the reference (not compared): {', '.join(f'`{m}`' for m in r.missing_in_reference)}.")
            lines.append("")
    lines += ["## Fixed in this phase", "", "| behaviour | classification | what was wrong / TradingView rule | evidence |",
              "|---|---|---|---|"]
    lines += [f"| {name} | {category} | {what} | {evidence} |" for name, category, what, evidence in FIXED]
    seen = observations()
    lines += ["", "## Manual TradingView observations", "",
              "Recorded by hand in `tradingview/observations.json` (see README); these behaviours cannot be exported.",
              "", "| check | TradingView (observed) | this engine | result |", "|---|---|---|---|"]
    for key, (question, engine) in OBSERVATIONS.items():
        value = seen.get(key)
        observed = "not recorded" if value is None else ("yes" if value else "no")
        verdict = "PENDING" if value is None else ("PASS" if value == engine else "FAIL")
        lines.append(f"| {question} | {observed} | {'yes' if engine else 'no'} | {verdict} |")
    lines += _manual_section()
    lines += _quick_section()
    lines += _security_section()
    lines += ["", "## Rules under test", "",
              "| question | TradingView rule | evidence | engine |", "|---|---|---|---|",
              "| equal highs/lows inside a pivot window | left tie keeps the pivot, right tie cancels it | third-party "
              "capture; own run: quick/q1 s06_pivots 1404/1404 (1/1, 2/2, 3/3, 2/1, 1/3) | matches |",
              "| `for` end expression | v6: re-evaluated before every iteration, direction fixed at start; v5: "
              "evaluated once | own run: q2 for_dynamic_end = 7 (v6), q3 = 4 (v5) | matches |",
              "| `plot()` default style (= plot.style_line) across `na` | the line joins the last non-na value to the "
              "next one; `plot.style_linebr` leaves the gap | own observation: manual/m02 | matches (chart renderer "
              "bridges line styles, breaks *br styles) |",
              "| var / varip within one realtime bar | var keeps its value across updates of the forming bar; varip "
              "advances on every update | own observation: manual/m03, BTCUSDT 1-minute live | matches |",
              "| var / varip when a new realtime bar opens; `barstate.isnew` | var +1, varip per-bar counter resets; "
              "isnew only on the first update | TradingView documentation only (not observed) | implemented, "
              "engine-tested |",
              ""]
    return "\n".join(lines)


def manual_results() -> dict:
    path = TV_DIR / "manual_results.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _manual_section() -> list[str]:
    from .manual import BY_FIXTURE, LIVE_TABLE, VISUAL_NA_GAP

    recorded = manual_results()
    lines = ["", "## Manual table checks (TradingView Basic plan)", "",
             "Recorded by hand in `tradingview/manual_results.json` (see README, *TradingView Basic plan — manual "
             "parity*) as `\"checked\": [\"page/columns\", ...]`. A fixture is confirmed only when every page × "
             "column group was compared.", "",
             "| manual script | page/columns combinations | status | checked (page/columns) | note |",
             "|---|---|---|---|---|"]
    for name, spec in BY_FIXTURE.items():
        entry = recorded.get(name, {})
        combos = {f"{page}/{part}" for page in range(len(spec.pages)) for part in range(1, len(spec.parts) + 1)}
        checked = [c for c in entry.get("checked", []) if c in combos]
        status = entry.get("status", "not checked")
        if status == "match" and set(checked) != combos:
            status = f"match (partial: {len(checked)} of {len(combos)})"
        lines.append(f"| `manual/{name}.pine` | {len(spec.pages)} × {len(spec.parts)} = {len(combos)} | {status} | "
                     f"{', '.join(checked) or '—'} | {entry.get('note', '')} |")
    for name in (VISUAL_NA_GAP, LIVE_TABLE):
        entry = recorded.get(name, {})
        lines.append(f"| `manual/{name}.pine` | visual | {entry.get('status', 'not checked')} | — | "
                     f"{entry.get('note', '')} |")
    return lines


def quick_results() -> dict:
    path = TV_DIR / "quick_results.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _quick_section() -> list[str]:
    from .quick import QUICK_SCRIPTS, check_bars, outputs

    recorded = quick_results()
    lines = ["", "## Fast self-checking TradingView scripts", "",
             "Recorded from the summary-table screenshot in `tradingview/quick_results.json`. Only a real "
             "TradingView run changes a status; local tests never do.", "",
             "| quick script | fixture | cells | TradingView result | note |", "|---|---|---|---|---|"]
    for quick in QUICK_SCRIPTS:
        entry = recorded.get(quick.name, {})
        for fixture in quick.fixtures:
            cells = len(check_bars(quick, fixture)) * len(outputs(fixture))
            status = entry.get("fixtures", {}).get(fixture, "not run")
            lines.append(f"| `quick/{quick.name}.pine` | {fixture} | {cells} | {status} | {entry.get('note', '')} |")
    return lines


def _security_section() -> list[str]:
    from .security_fixture import SCRIPT_NAME

    entry = quick_results().get(SCRIPT_NAME, {})
    lines = ["", "## P2.1 request.security() semantics (historical)", "",
             f"`quick/{SCRIPT_NAME}.pine` establishes TradingView's historical request.security() mapping "
             "(see `SECURITY_SEMANTICS.md`).", "",
             f"TradingView result: **{entry.get('status', 'not run')}**" + (f" — {entry['note']}" if entry.get("note") else ""),
             ""]
    path = OURS_DIR / "q4_engine_parity.json"
    if path.exists():
        engine = json.loads(path.read_text())
        lines += [f"This engine against the frozen q4 oracle: **{engine['matched']} / {engine['cells']}** cells "
                  f"({engine['contexts']} requested contexts).", "", "| mapping | matched / checked |", "|---|---|"]
        lines += [f"| `{key}` | {m} / {c} |" for key, (m, c) in engine["by_group"].items()]
        lines.append("")
    terminal = ROOT / "terminal" / "p21_terminal_results.json"
    if terminal.exists():
        record = json.loads(terminal.read_text())
        tiers = record["evidence_tiers"]
        lines += ["### Evidence tiers", "",
                  "**Real TradingView verified:** " + "; ".join(tiers["real_tradingview_verified"]) + ".", "",
                  "**Zoneflow terminal verified** (run by the user in this terminal, `terminal/p21_terminal_results.json`; "
                  "not TradingView evidence):", ""]
        lines += [f"- {item}" for item in tiers["zoneflow_terminal_verified"]]
        lines += ["", "**Automated only** (tests, not observed manually):", ""]
        lines += [f"- {item}" for item in tiers["automated_only"]]
        lines += ["", "| terminal check | chart | result |", "|---|---|---|"]
        lines += [f"| `manual/{name}.pine` | {check['chart']} | {check['result']} |"
                  for name, check in record["checks"].items()]
        lines.append("")
    return lines


def write_all() -> list[FixtureResult]:
    """Regenerate fixtures, fixture data, our outputs and the report (deterministic)."""
    FIXTURE_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)
    OURS_DIR.mkdir(exist_ok=True)
    TV_DIR.mkdir(exist_ok=True)
    for name, source in MANUAL_CHECKS.items():
        (FIXTURE_DIR / f"{name}.pine").write_text(source)
    for f in FIXTURES:
        (FIXTURE_DIR / f"{f.name}.pine").write_text(f.source)
        (OURS_DIR / f"{f.name}.csv").write_text(ours_csv(f))
    frame = synthetic_frame()
    frame.insert(1, "bar_index", range(len(frame)))
    (DATA_DIR / "synthetic_ohlcv.csv").write_text(
        frame.assign(timestamp=frame["timestamp"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")).to_csv(
            index=False, float_format="%.17g", lineterminator="\n"))
    from .manual import write_manual
    from .quick import write_quick
    from .security_fixture import write as write_security
    write_manual()
    write_quick()
    write_security()
    from .security_fixture import engine_parity
    parity = engine_parity()
    (OURS_DIR / "q4_engine_parity.json").write_text(json.dumps(
        {"matched": parity["matched"], "cells": parity["cells"], "contexts": parity["contexts"],
         "by_group": parity["by_group"], "first_mismatches": parity["first_mismatches"]}, indent=1) + "\n")
    results = compare_all()
    REPORT.write_text(report(results))
    return results


__all__ = ["ABS_TOL", "REL_TOL", "BY_NAME", "FIXTURES", "compare_all", "compare_fixture", "compare_values",
           "read_export", "report", "run_ours", "synthetic_frame", "write_all"]
