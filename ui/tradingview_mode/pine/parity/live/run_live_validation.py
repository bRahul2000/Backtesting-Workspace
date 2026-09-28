"""P2.2 real-Live validation of request.security_lower_tf() (see P22_LIVE_VALIDATION.md).

    venv/bin/python ui/tradingview_mode/pine/parity/live/run_live_validation.py binance [--minutes 17]
    venv/bin/python ui/tradingview_mode/pine/parity/live/run_live_validation.py exness  [--minutes 18]

Starts the real app (the production frontend build) exactly as a user would, drives it with headless Chrome and real
clicks (live_lower_tf.mjs): adds the live oracle scripts, goes Live on the real data source (Binance public market
data; Exness through the real MT5 bridge files), samples the terminal and evaluates every required property.
Binance runs with MT5 switched off (an empty MT5 folder); Exness uses this machine's real MT5 Common/Files folder.
Writes ``results/<mode>_<utc>.json`` (the evaluation plus the evidence excerpts). Read-only market data; nothing
trades. Not collected by pytest.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
CHROME = os.environ.get("CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def run_app_and_harness(mode: str, minutes: float, mt5_folder: str | None = None) -> dict:
    env = dict(os.environ)
    if mode == "binance":                       # MT5 off: nothing Exness can take part
        env["TV_MT5_COMMON_FILES"] = tempfile.mkdtemp(prefix="mt5-off-")
    elif mt5_folder:                            # harness dry run only (a synthetic feed): never evidence
        env["TV_MT5_COMMON_FILES"] = mt5_folder
    else:
        env.pop("TV_MT5_COMMON_FILES", None)     # the real MT5 bridge folder
    port = _port()
    server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"), "--server.headless",
                               "true", "--server.port", str(port), "--browser.gatherUsageStats", "false"],
                              cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(240):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        url = f"http://127.0.0.1:{port}/render_tradingview_mode"
        done = subprocess.run(["node", str(HERE / "live_lower_tf.mjs"), url, CHROME, mode, str(minutes), str(HERE)],
                              capture_output=True, text=True, timeout=int(minutes * 60) + 900)
        sys.stderr.write(done.stderr[-4000:])
        return json.loads(done.stdout or "{}")
    finally:
        server.terminate()
        server.wait(15)


# ---- evaluation ---------------------------------------------------------------------------------------------------

def _script(sample: dict, prefix: str) -> dict | None:
    return next((s for s in sample.get("pine") or [] if s["title"].startswith(prefix)), None)


def _row(sample: dict, prefix: str) -> dict | None:
    return next((r for r in sample.get("rows") or [] if (r.get("title") or "").startswith(prefix)), None)


def _forming(sample: dict, prefix: str) -> dict:
    """The script's plot values on the forming (last) chart bar, and on the previous bar."""
    script, bar = _script(sample, prefix), (sample.get("chart") or {}).get("last")
    now, prev = {}, {}
    for name, points in (script or {}).get("plots", {}).items():
        for t, v in points:
            if t == bar:
                now[name] = v
            elif bar is not None and t < bar:
                prev[name] = v
    return {"bar": bar, "now": now, "prev": prev}


def _check(checks: list, name: str, ok: bool, detail) -> None:
    checks.append({"property": name, "result": "PASS" if ok else "FAIL", "detail": detail})


def _live(samples: list) -> list:
    return [s for s in samples if s.get("status") == "LIVE" and s.get("pine")]


def evaluate_binance(raw: dict) -> list:
    checks: list = []
    samples = _live(raw["samples"])
    step_ok = all(s["ok"] for s in raw["steps"])
    _check(checks, "0 harness steps (load, add script, Go Live, exit, re-enter)", step_ok,
           [s for s in raw["steps"] if not s["ok"]] or f"{len(raw['steps'])} steps ok")
    rows = [_row(s, "L1") for s in samples]
    ctx = [r["contexts"] or "" for r in rows if r]
    lower = [c for c in ctx if "BTCUSDT 1 · Binance Futures · native" in c]
    forming_flag = [c for c in lower if "BTCUSDT 1 · Binance Futures · native" in c and "forming bar" in c.split("BTCUSDT 1 ·")[1].split("\n")[0]]
    f = [(s, _forming(s, "L1")) for s in samples]
    cur = [(s, x) for s, x in f if x["now"].get("n1")]
    minute_now = lambda s, x: int((s["wall_ms"] / 1000 - x["bar"]) // 60)       # noqa: E731
    at_now = [1 for s, x in cur if x["now"].get("last1") == minute_now(s, x)]
    _check(checks, "1 the dedicated lower-interval (1m) stream is acquired",
           len(lower) == len(ctx) > 0 and len(forming_flag) >= 0.9 * len(lower) and len(at_now) >= 0.8 * len(cur),
           {"samples": len(samples), "context_1m_present": f"{len(lower)}/{len(ctx)}",
            "context_1m_forming_flag": f"{len(forming_flag)}/{len(lower)}",
            "last_intrabar_is_the_current_minute": f"{len(at_now)}/{len(cur)}", "context_example": (lower or [""])[0]})
    sets = {s["chart"]["stats"].get("setData") for s in samples}
    updates = [s["chart"]["stats"].get("updates") for s in samples]
    _check(checks, "2 the chart stream is not replaced or disturbed",
           len(samples) == len([s for s in raw["samples"] if not s.get("error")]) and len(sets) == 1
           and updates[-1] > updates[0],
           {"status_all_LIVE": len(samples) == len(raw["samples"]), "chart_reloads(setData) distinct": sorted(sets),
            "chart_updates": [updates[0], updates[-1]]})
    ordered = [x["now"].get("ordered1") for s, x in cur] + [x["prev"].get("ordered1") for s, x in f if x["prev"]]
    first0 = [x["now"].get("first1") for s, x in cur]
    _check(checks, "3 completed intrabars appear in order (1-minute steps from the chart bar's open)",
           all(o == 1 for o in ordered if o is not None) and all(v == 0 for v in first0),
           {"ordered_values": sorted({o for o in ordered if o is not None}), "first_offsets": sorted({v for v in first0})})
    eq = [x["now"].get("last1MinusClose") for s, x in cur]
    zero = [d for d in eq if d == 0]
    _check(checks, "4 the forming received intrabar is the last element",
           len(at_now) >= 0.8 * len(cur) and len(zero) >= 0.8 * len(eq),
           {"last_is_current_minute": f"{len(at_now)}/{len(cur)}", "last_close_equals_chart_close": f"{len(zero)}/{len(eq)}",
            "nonzero_differences": sorted({d for d in eq if d})[:10]})
    by_minute: dict = {}
    for s, x in cur:
        by_minute.setdefault((x["bar"], x["now"].get("last1")), set()).add(x["now"].get("last1Close"))
    changing = [k for k, v in by_minute.items() if len(v) > 1]
    _check(checks, "5 the last element updates as new kline updates arrive", len(changing) >= max(1, len(by_minute) // 3),
           {"minutes_observed": len(by_minute), "minutes_with_changing_last_value": len(changing)})
    steps, bad = 0, []
    for (s0, a), (s1, b) in zip(cur, cur[1:]):
        if a["bar"] == b["bar"] and b["now"].get("last1") != a["now"].get("last1"):
            steps += 1
            if not (b["now"]["last1"] == a["now"]["last1"] + 1 and b["now"]["n1"] == a["now"]["n1"] + 1):
                bad.append((a["now"], b["now"]))
    _check(checks, "6 a new lower-TF bar is appended at the minute boundary", steps >= 3 and not bad,
           {"boundaries_seen": steps, "bad_transitions": bad[:3]})
    rollovers, bad = [], []
    for (s0, a), (s1, b) in zip(cur, cur[1:]):
        if b["bar"] != a["bar"]:
            prev = b["prev"]
            rec = {"from_bar": a["bar"], "to_bar": b["bar"], "new_bar": {k: b["now"].get(k) for k in ("n1", "first1", "last1")},
                   "closed_bar": {k: prev.get(k) for k in ("n1", "first1", "last1", "ordered1")}}
            rollovers.append(rec)
            if not (prev.get("n1") == 15 and prev.get("first1") == 0 and prev.get("last1") == 14
                    and b["now"].get("first1") == 0 and b["now"].get("n1", 99) <= 2):
                bad.append(rec)
    _check(checks, "7 chart-bar rollover produces the correct new array", len(rollovers) >= 1 and not bad,
           {"rollovers": rollovers, "bad": bad})
    future = [x["now"].get("last1OpenMinusNowSec") for s, x in cur]
    ahead = [1 for s, x in cur if x["now"].get("last1", -1) > minute_now(s, x)]
    _check(checks, "8 no future / unreceived intrabar is synthesised",
           all(v is not None and v <= 0 for v in future) and not ahead,
           {"max(last intrabar open - timenow) s": max(v for v in future if v is not None) if future else None,
            "samples_ahead_of_wall_clock": len(ahead)})
    relive = _live(raw.get("relive") or [])
    rx = [_forming(s, "L1") for s in relive]
    _check(checks, "9 exit / re-enter Live (lease release and re-acquire) leaves the chart source intact",
           (raw.get("after_exit") or {}).get("status") != "LIVE" and len(relive) >= 8
           and all(x["now"].get("n1") and x["now"].get("ordered1") == 1 for x in rx),
           {"status_after_exit": (raw.get("after_exit") or {}).get("status"), "relive_samples_LIVE": len(relive),
            "relive_n1": sorted({x['now'].get('n1') for x in rx})})
    same = [(x["now"].get("sameN"), x["now"].get("sameMinusClose")) for s, x in cur]
    # request.security(..., "60", close) with lookahead_off (P2.1, TradingView q4 PPPPC): the forming hour's close only
    # on the hour's last 15m chart bar, otherwise the previous hour's close (= the close of that hour's last 15m bar)
    closes = {t: v for script in raw.get("history") or [] if script["title"].startswith("L1")
              for t, v in script["plots"].get("chartClose", [])}
    for s, x in f:
        closes.update({t: v for t, v in (_script(s, "L1") or {}).get("plots", {}).get("chartClose", [])})

    def expected(x):
        t = x["bar"]
        return x["now"].get("chartClose") if (t + 900) % 3600 == 0 else closes.get(t // 3600 * 3600 - 900)
    htf = [s for s, x in cur if expected(x) is not None and x["now"].get("htf60Close") == expected(x)]
    n10 = sorted({(x["now"].get("n10"), x["now"].get("last10")) for s, x in cur})
    _check(checks, "10 request.security and the chart behave as before (same-TF and HTF requests intact)",
           all(n == 1 and d == 0 for n, d in same) and len(htf) >= 0.8 * len(cur),
           {"same_timeframe(n, last-close)": sorted(set(same)), "htf60_close_as_P2.1_lookahead_off": f"{len(htf)}/{len(cur)}",
            "n10/last10 (custom 10m, aggregated from the received 5m stream)": n10})
    return checks


def evaluate_exness(raw: dict) -> list:
    checks: list = []
    samples = _live(raw["samples"])
    _check(checks, "0 harness steps", all(s["ok"] for s in raw["steps"]),
           [s for s in raw["steps"] if not s["ok"]] or f"{len(raw['steps'])} steps ok")
    ctx = [(_row(s, "L2") or {}).get("contexts") or "" for s in samples]
    f = [(s, _forming(s, "L2")) for s in samples]
    cur = [(s, x) for s, x in f if x["now"].get("n15")]
    slot = lambda s, x: int((s["wall_ms"] / 1000 - x["bar"]) // 900) * 15     # noqa: E731
    at_now = [1 for s, x in cur if x["now"].get("last15") == slot(s, x)]
    _check(checks, "1 request.security_lower_tf reads the MT5 snapshot path (received forming M15 bar)",
           len(cur) > 0 and len(at_now) >= 0.8 * len(cur) and all("forming bar" in c for c in ctx if c),
           {"samples": len(samples), "last15_is_the_current_M15": f"{len(at_now)}/{len(cur)}", "context_example": (ctx or [""])[0]})
    families = sorted({line.split(" · ")[1] for c in ctx for line in c.split("\n") if " · " in line})
    _check(checks, "2 only received / authoritative Exness M15/M30/H1 data is used", families == ["Exness MT5"],
           {"providers_in_contexts": families})
    l3 = [(_row(s, "L3") or {}).get("error") for s in samples]
    _check(checks, "3 no Binance fallback", all("Binance" not in c for c in ctx)
           and all(e and "Binance" not in e for e in l3), {"L3_error": (l3 or [None])[0]})
    prev = [x["prev"] for s, x in f if x["prev"]]
    sw = [(s, _forming(s, "L2")) for s in _live(raw.get("after_switch") or [])]
    _check(checks, "4 lower-TF combinations: 15m in 1h, 30m in 1h, 15m in 30m",
           prev and all(p.get("n15") == 4 and p.get("n30") == 2 and p.get("first15") == 0 for p in prev)
           and sw and all(x["prev"].get("n15") == 2 for s, x in sw if x["prev"]),
           {"1h_closed_bar(n15, n30)": sorted({(p.get('n15'), p.get('n30')) for p in prev}),
            "30m_closed_bar n15": sorted({x['prev'].get('n15') for s, x in sw if x['prev']}),
            "30m_forming n15": sorted({x['now'].get('n15') for s, x in sw})})
    same = [(x["now"].get("sameN"), x["now"].get("sameMinusClose")) for s, x in cur + sw]
    _check(checks, "5 same-timeframe behaviour (1h in 1h, 30m in 30m)", same and all(n == 1 and d == 0 for n, d in same),
           {"(n, last-close)": sorted(set(same))})
    _check(checks, "6 below-M15 requests fail explicitly", all(e and "finest dataset is 15m" in e for e in l3),
           {"L3_error": (l3 or [None])[0]})
    eq = [x["now"].get("last15MinusClose") for s, x in cur]
    vals = {}
    for s, x in cur:
        vals.setdefault((x["bar"], x["now"].get("last15")), set()).add(x["now"].get("last15Close"))
    _check(checks, "7 the latest received / forming Exness intrabar is last and updates",
           len([d for d in eq if d == 0]) >= 0.9 * len(eq) and any(len(v) > 1 for v in vals.values()),
           {"last_close_equals_chart_close": f"{len([d for d in eq if d == 0])}/{len(eq)}",
            "distinct_last_values_per_M15": {str(k): len(v) for k, v in vals.items()}})
    _check(checks, "8 chart source and lower-TF source are the same provider family", families == ["Exness MT5"]
           and all(s.get("reason") is None or "Binance" not in (s.get("reason") or "") for s in samples),
           {"providers_in_contexts": families})
    sets = {s["chart"]["stats"].get("setData") for s in samples}
    relive = _live(raw.get("relive") or [])
    _check(checks, "9 MT5 snapshot updates are reflected safely (no reloads; exit / re-enter Live works)",
           len(sets) == 1 and len(relive) >= 8 and all(_forming(s, "L2")["now"].get("n15") for s in relive),
           {"chart_reloads(setData) distinct": sorted(sets), "relive_samples_LIVE": len(relive)})
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("binance", "exness"))
    parser.add_argument("--minutes", type=float, default=None)
    parser.add_argument("--dry-run-mt5-folder", default=None,
                        help="harness self-test with a synthetic MT5 feed folder; the result is marked DRY RUN")
    args = parser.parse_args()
    minutes = args.minutes or (17 if args.mode == "binance" else 18)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip())
    raw = run_app_and_harness(args.mode, minutes, args.dry_run_mt5_folder)
    checks = (evaluate_binance if args.mode == "binance" else evaluate_exness)(raw)
    result = {"mode": args.mode, "dry_run": bool(args.dry_run_mt5_folder), "commit": commit, "tracked_changes_in_tree": dirty,
              "started_utc": raw.get("started_utc"), "finished_utc": raw.get("finished_utc"),
              "setup": {"binance": "BINANCE BTCUSDT Perpetual, Live 15m chart; requests 1m, 10m, 15m (same), 60 "
                                   "(request.security); MT5 switched off",
                        "exness": "EXNESS BTCUSDm, Live 1h chart then 30m; requests 15m, 30m, same timeframe, 5m "
                                  "(must fail); real MT5 bridge"}[args.mode],
              "checks": checks, "steps": raw.get("steps"), "samples": len(raw.get("samples") or []),
              "excerpt": {"first_sample": (raw.get("samples") or [None])[0], "last_sample": (raw.get("samples") or [None])[-1],
                          "history_last_bars": raw.get("history")}}
    stamp = f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    out = (Path(tempfile.gettempdir()) / f"DRYRUN_{args.mode}_{stamp}.json" if args.dry_run_mt5_folder
           else HERE / "results" / f"{args.mode}_{stamp}.json")
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str))
    raw_copy = Path(tempfile.gettempdir()) / f"p22_live_raw_{out.stem}.json"      # every sample, for re-evaluation
    raw_copy.write_text(json.dumps(raw, default=str))
    print(f"raw samples: {raw_copy}")
    for c in checks:
        print(f"{c['result']}  {c['property']}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
