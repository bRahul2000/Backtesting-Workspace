"""P3.1 strategy parity tooling: run a Pine strategy on frozen bars and compare its trades with TradingView's
"List of trades" export, trade by trade.

    python -m ui.tradingview_mode.pine.parity.strategy_parity SCRIPT.pine TRADES.csv [--bars BARS.csv] [--mintick 0.1]

* Bars: a frozen CSV (``timestamp`` UTC, ``open``, ``high``, ``low``, ``close``, ``volume``) of the chart TradingView
  ran on. ``fetch_binance`` builds one from Binance USD-M futures public klines (no authentication, no account data).
* Pine Logs text (TradingView Basic has no CSV export): the ``*_logged.pine`` copies of the oracles emit
  ``ZF|<TAG>|TRADE|n|key=value|...`` lines from ``strategy.closedtrades.*`` on the last confirmed bar. Copied Pine
  Logs are parsed from the first ``ZF|`` of each line, so TradingView's timestamp prefixes and other noise are ignored.
  Times are UTC epoch milliseconds. Both inputs produce the same ``TvTrade`` records.
* TradingView CSV: the Strategy Tester's "List of trades" download. Column names differ between TradingView versions
  ("Date/Time" / "Date and time", "Contracts" / "Size (qty)", "Profit" / "Net P&L" ...); they are matched by meaning.
  Times are in the chart's timezone: the offset is detected from the bar times (every entry must be a bar open).
* Nothing is tolerated silently: prices within half a tick (provider precision), profits within 0.01 (TradingView
  rounds to cents); any bar/time difference is a mismatch.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import urllib.request

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE / "strategies" / "data"
BINANCE_KLINES = "https://fapi.binance.com/fapi/v1/klines"     # public market data only
SEQUENCE_FIELDS = {"direction", "entry signal", "entry time", "exit signal", "exit time", "qty", "entry bar", "exit bar"}
MONEY_TOLERANCE = 1e-6                # absolute: Pine Logs print 8 decimals; this is float noise, never a price step


# ---- bars ------------------------------------------------------------------------------------------------------------

def fetch_binance(symbol: str, interval: str, start_ms: int = 0, end_ms: int | None = None) -> pd.DataFrame:
    rows, start = [], start_ms
    while True:
        url = f"{BINANCE_KLINES}?symbol={symbol}&interval={interval}&limit=1500&startTime={start}"
        if end_ms is not None:
            url += f"&endTime={end_ms}"
        page = json.load(urllib.request.urlopen(url, timeout=30))
        if not page:
            break
        rows += page
        if len(page) < 1500:
            break
        start = page[-1][0] + 1
    return pd.DataFrame({"timestamp": pd.to_datetime([r[0] for r in rows], unit="ms", utc=True),
                         "open": [float(r[1]) for r in rows], "high": [float(r[2]) for r in rows],
                         "low": [float(r[3]) for r in rows], "close": [float(r[4]) for r in rows],
                         "volume": [float(r[5]) for r in rows], "close_time": [int(r[6]) for r in rows]})


def load_bars(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    return frame


class FrozenProvider:
    """request.security() data for parity runs: frozen bars of the chart's own symbol per requested timeframe (e.g.
    TradingView's exported 60-minute bars), so both engines see identical data. Other symbols and timeframes are
    refused, never synthesised."""

    family = "frozen"

    def __init__(self, tickerid: str, frames: dict[str, pd.DataFrame], mintick: float):
        self.tickerid, self.frames, self.mintick = tickerid, frames, mintick

    def check_symbol(self, symbol: str) -> str:
        ticker = self.tickerid.split(":")[-1]
        if symbol not in (self.tickerid, ticker):
            from ..security import SecurityDataError
            raise SecurityDataError(f"symbol `{symbol}` has no frozen bars (only `{self.tickerid}`).", "unknown_symbol")
        return ticker

    def request(self, symbol, timeframe, *, parent_tickerid, parent_seconds, knowable, until_ms, chart_end_ms,
                lower: bool = False):
        from ..security import BarGrid, Bars, Requested, SecurityDataError

        ticker = self.check_symbol(symbol)
        frame = self.frames.get(timeframe.text)
        if frame is None:
            raise SecurityDataError(f"no frozen `{timeframe.text}` bars for `{self.tickerid}`.", "missing_source")
        stamps = frame["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ms]").astype(np.int64)
        bars = Bars(stamps, stamps + timeframe.seconds * 1000, *(frame[c].to_numpy(dtype=float) for c in
                                                                 ("open", "high", "low", "close")),
                    frame["volume"].to_numpy(dtype=float) if "volume" in frame else np.zeros(len(frame)))
        if knowable:
            bars = bars.upto_close(until_ms)
        elif chart_end_ms is not None:                 # historical: nothing opening after the chart's last bar
            bars = bars.head(int(np.searchsorted(bars.time, chart_end_ms, side="right")))
        return Requested(bars, BarGrid(timeframe), ticker, self.tickerid,
                         {"provider_family": "frozen", "provider": "parity bars", "native": True,
                          "aggregation_base": None, "data_identity": f"frozen:{self.tickerid}:{timeframe.text}",
                          "fingerprint": None}, mintick=self.mintick, same_as_parent=True)


def run_strategy(source: str, frame: pd.DataFrame, *, mintick: float, timeframe_seconds: int,
                 tickerid: str = "BINANCE:BTCUSDT.P", inputs: dict | None = None,
                 security_frames: dict[str, pd.DataFrame] | None = None, currency: str = "USDT"):
    from ..engine import PineExecution, compile_script, data_context, resolve_inputs, run_script

    result = compile_script(source)
    if not result.ok:
        raise ValueError("; ".join(d.text() for d in result.diagnostics))
    values = resolve_inputs(result.program, inputs or {})[0]
    provider = FrozenProvider(tickerid, security_frames, mintick) if security_frames else None
    execution = PineExecution(result.program, values, provider)
    data = data_context(frame, timeframe_seconds=timeframe_seconds, ticker=tickerid.split(":")[-1], tickerid=tickerid,
                        mintick=mintick, currency=currency)
    out = run_script(execution, data, ("parity",), "p")
    if out.error:
        raise RuntimeError(out.error)
    return execution.runtime.strategy


# ---- TradingView "List of trades" ------------------------------------------------------------------------------------

@dataclass
class TvTrade:
    number: int
    direction: int
    entry_signal: str = ""
    entry_time: datetime | None = None
    entry_price: float | None = None
    exit_signal: str = ""
    exit_time: datetime | None = None
    exit_price: float | None = None
    qty: float | None = None
    profit: float | None = None
    open: bool = False
    entry_bar: int | None = None
    exit_bar: int | None = None
    commission: float | None = None
    runup: float | None = None
    drawdown: float | None = None


def _column(header: list[str], *keys: str, exclude: tuple = ()) -> int | None:
    for index, name in enumerate(header):
        low = name.strip().lower()
        if any(k in low for k in keys) and not any(x in low for x in exclude):
            return index
    return None


def _time(text: str) -> datetime:
    text = text.strip().replace(",", "")
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%b %d %Y %H:%M", "%d %b %Y %H:%M"):
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise ValueError(f"unrecognised TradingView time {text!r}")


def _number(text: str) -> float | None:
    text = (text or "").strip().replace(",", "").replace("−", "-").replace(" ", "")
    if text in ("", "-", "—"):
        return None
    return float(text.rstrip("%"))


def parse_tradingview_trades(path: Path) -> list[TvTrade]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.reader(handle))
    header, body = rows[0], rows[1:]
    c_num = _column(header, "trade #", "trade number")
    c_type = _column(header, "type")
    c_signal = _column(header, "signal")
    c_time = _column(header, "date")
    c_price = _column(header, "price")
    c_qty = _column(header, "contracts", "size (qty)", "quantity", "qty", exclude=("value",))
    c_profit = _column(header, "net p&l", "profit", exclude=("%", "cumulative", "cum."))
    if None in (c_num, c_type, c_time, c_price):
        raise ValueError(f"not a TradingView list of trades: {header}")
    trades: dict[int, TvTrade] = {}
    for row in body:
        if not row or not row[c_num].strip():
            continue
        number, kind = int(float(row[c_num])), row[c_type].strip().lower()
        trade = trades.setdefault(number, TvTrade(number, 1 if "long" in kind else -1))
        signal = row[c_signal].strip() if c_signal is not None else ""
        when, price = _time(row[c_time]), _number(row[c_price])
        if "entry" in kind:
            trade.entry_signal, trade.entry_time, trade.entry_price = signal, when, price
        else:
            trade.exit_signal, trade.exit_time, trade.exit_price = signal, when, price
            trade.open = signal.lower() == "open"
        if c_qty is not None and _number(row[c_qty]) is not None:
            trade.qty = _number(row[c_qty])
        if c_profit is not None and _number(row[c_profit]) is not None and "exit" in kind:
            trade.profit = _number(row[c_profit])
    return [trades[k] for k in sorted(trades)]


def parse_pine_logs(text: str, tag: str | None = None) -> tuple[list[TvTrade], dict]:
    """ZF records -> (closed and open trades in trade order, SUMMARY fields)."""
    trades, opens, summary = {}, {}, {}
    for line in text.splitlines():
        start = line.find("ZF|")
        if start < 0:
            continue
        parts = line[start:].strip().split("|")
        if len(parts) < 3 or (tag is not None and parts[1] != tag):
            continue
        kind = parts[2]
        fields = dict(item.split("=", 1) for item in parts[3:] if "=" in item)
        if kind == "SUMMARY":
            summary = fields
            continue
        if kind not in ("TRADE", "OPEN"):
            continue
        index = int(parts[3])
        size = _number(fields.get("size"))
        trade = TvTrade(index + 1, 1 if (size or 0) > 0 else -1, entry_signal=fields.get("entry_id", ""),
                        entry_time=_epoch(fields.get("entry_time")), entry_price=_number(fields.get("entry_price")),
                        qty=abs(size) if size is not None else None, open=kind == "OPEN",
                        entry_bar=_int(fields.get("entry_bar")))
        if kind == "TRADE":
            trade.exit_signal = fields.get("exit_id", "")
            trade.exit_time = _epoch(fields.get("exit_time"))
            trade.exit_price = _number(fields.get("exit_price"))
            trade.profit = _number(fields.get("profit"))
            trade.exit_bar = _int(fields.get("exit_bar"))
            trade.commission = _number(fields.get("commission"))
            trade.runup = _number(fields.get("runup"))
            trade.drawdown = _number(fields.get("drawdown"))
            trades[index] = trade
        else:
            opens[index] = trade
    closed = [trades[k] for k in sorted(trades)]
    for position, key in enumerate(sorted(opens)):
        opens[key].number = len(closed) + position + 1
    return closed + [opens[k] for k in sorted(opens)], summary


def _int(text) -> int | None:
    return None if text in (None, "", "na", "NaN") else int(float(text))


def _epoch(text) -> datetime | None:
    if text in (None, "", "na", "NaN"):
        return None
    return datetime.fromtimestamp(int(float(text)) / 1000, tz=timezone.utc).replace(tzinfo=None)


def parse_trades(path: Path) -> list[TvTrade]:
    """A TradingView CSV export or copied Pine Logs text, recognised by content."""
    text = path.read_text(encoding="utf-8-sig")
    if "ZF|" in text:
        return parse_pine_logs(text)[0]
    return parse_tradingview_trades(path)


def detect_offset(trades: list[TvTrade], bar_times: set[datetime]) -> timedelta:
    """The chart timezone offset: the one that puts every TradingView entry on a bar open (UTC)."""
    stamps = [t.entry_time for t in trades if t.entry_time is not None][:200]
    best, score = timedelta(0), -1
    for quarter in range(-12 * 4, 14 * 4 + 1):
        offset = timedelta(minutes=15 * quarter)
        hits = sum((s - offset).replace(tzinfo=timezone.utc) in bar_times for s in stamps)
        if hits > score:
            best, score = offset, hits
    return best


# ---- comparison ------------------------------------------------------------------------------------------------------

@dataclass
class Report:
    tradingview: int
    engine: int
    compared: int
    matched: int
    mismatches: list = field(default_factory=list)       # (trade number, field, tradingview, engine)
    offset: timedelta = timedelta(0)
    first_divergence: int | None = None
    sequence_matched: int = 0                            # same order, IDs, direction, size, bars and times
    aggregates: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """Machine-readable form (JSON-safe)."""
        return {"tradingview_trades": self.tradingview, "engine_trades": self.engine, "compared": self.compared,
                "sequence_matched": self.sequence_matched, "fully_matched": self.matched,
                "first_divergence": self.first_divergence,
                "timezone_offset_minutes": int(self.offset.total_seconds() // 60),
                "mismatches": [{"trade": n, "field": f, "tradingview": str(a), "engine": str(b)}
                               for n, f, a, b in self.mismatches],
                "aggregates": {k: {"tradingview": a, "engine": b} for k, (a, b) in self.aggregates.items()}}

    def text(self) -> str:
        lines = [f"TradingView trades {self.tradingview} | engine trades {self.engine} | compared {self.compared} | "
                 f"sequence matched {self.sequence_matched} | fully matched {self.matched} | "
                 f"chart timezone offset {self.offset}"]
        if self.first_divergence is not None:
            lines.append(f"first divergence: trade #{self.first_divergence}")
        for number, name, tv, ours in self.mismatches[:60]:
            lines.append(f"  #{number} {name}: TradingView {tv!r} vs engine {ours!r}")
        for name, (tv, ours) in self.aggregates.items():
            lines.append(f"  {name}: TradingView {tv} vs engine {ours}")
        return "\n".join(lines)


def compare(tv: list[TvTrade], broker, frame: pd.DataFrame, *, mintick: float, until: datetime | None = None) -> Report:
    bar_times = {t.to_pydatetime() for t in frame["timestamp"]}
    offset = detect_offset(tv, bar_times)
    times = frame["timestamp"].tolist()
    engine = list(broker.state.closed) + [None] * 0
    opens = list(broker.state.trades)
    tolerance = mintick / 2 + 1e-9
    tv_closed = [t for t in tv if not t.open]
    if until is not None:
        tv_closed = [t for t in tv_closed if (t.exit_time - offset).replace(tzinfo=timezone.utc) <= until]
    report = Report(len(tv_closed), len(engine), min(len(tv_closed), len(engine)), 0, offset=offset)
    for index in range(report.compared):
        a, b = tv_closed[index], engine[index]
        entry_time = times[b.entry_bar].to_pydatetime()
        exit_time = times[b.exit_bar].to_pydatetime()
        checks = [
            ("direction", a.direction, b.direction, a.direction == b.direction),
            ("entry signal", a.entry_signal, b.entry_id, a.entry_signal == b.entry_id),
            ("entry time", a.entry_time - offset, entry_time.replace(tzinfo=None),
             (a.entry_time - offset) == entry_time.replace(tzinfo=None)),
            ("entry price", a.entry_price, round(b.entry_price, 8), abs(a.entry_price - b.entry_price) <= tolerance),
            ("exit signal", a.exit_signal, b.exit_id, a.exit_signal == b.exit_id),
            ("exit time", a.exit_time - offset, exit_time.replace(tzinfo=None),
             (a.exit_time - offset) == exit_time.replace(tzinfo=None)),
            ("exit price", a.exit_price, round(b.exit_price, 8), abs(a.exit_price - b.exit_price) <= tolerance),
        ]
        if a.qty is not None:
            checks.append(("qty", a.qty, round(b.qty, 8), abs(a.qty - b.qty) <= 1e-6 * max(1.0, abs(b.qty))))
        money = MONEY_TOLERANCE if a.entry_bar is not None else 0.01 + 1e-9   # logs: full precision; CSV: cents
        if a.profit is not None:
            checks.append(("profit", a.profit, round(b.profit, 8), abs(a.profit - b.profit) <= money))
        if a.entry_bar is not None:
            checks.append(("entry bar", a.entry_bar, b.entry_bar, a.entry_bar == b.entry_bar))
        if a.exit_bar is not None:
            checks.append(("exit bar", a.exit_bar, b.exit_bar, a.exit_bar == b.exit_bar))
        for name, tv_value, ours in (("commission", a.commission, b.commission), ("run-up", a.runup, b.max_runup),
                                     ("drawdown", a.drawdown, b.max_drawdown)):
            if tv_value is not None:
                checks.append((name, tv_value, round(ours, 8), abs(tv_value - ours) <= MONEY_TOLERANCE))
        bad = [(a.number, name, x, y) for name, x, y, ok in checks if not ok]
        report.sequence_matched += not any(name in SEQUENCE_FIELDS for _, name, _, _ in bad)
        if bad and report.first_divergence is None:
            report.first_divergence = a.number
        report.mismatches += bad
        report.matched += not bad
    if len(tv_closed) != len(engine):
        report.mismatches.append((None, "trade count", len(tv_closed), len(engine)))
        if report.first_divergence is None:
            report.first_divergence = report.compared + 1
    tv_net = sum(t.profit or 0.0 for t in tv_closed)
    report.aggregates = {
        "net profit (closed)": (round(tv_net, 2), round(sum(t.profit for t in engine), 2)),
        "winning trades": (sum((t.profit or 0) > 0 for t in tv_closed), sum(t.profit > 1e-9 for t in engine)),
        "losing trades": (sum((t.profit or 0) < 0 for t in tv_closed), sum(t.profit < -1e-9 for t in engine)),
        "open trades at end": (sum(t.open for t in tv), len(opens)),
    }
    return report


SUMMARY_FIELDS = ("initial", "equity", "net", "gross_profit", "gross_loss", "closed", "wins", "losses", "even",
                  "max_drawdown", "position")


def engine_summary(broker) -> dict:
    """The engine's values for the fields of a ZF SUMMARY record (all positions closed at the report bar)."""
    s, capital = broker.state, broker.settings.initial_capital
    return {"initial": capital, "equity": capital + s.netprofit, "net": s.netprofit, "gross_profit": s.grossprofit,
            "gross_loss": s.grossloss, "closed": len(s.closed), "wins": s.wins, "losses": s.losses, "even": s.evens,
            "max_drawdown": s.max_drawdown, "position": broker.position()}


def compare_summary(summary: dict, broker) -> dict:
    ours = engine_summary(broker)
    return {name: {"tradingview": float(summary[name]), "engine": round(float(ours[name]), 8),
                   "match": abs(float(summary[name]) - float(ours[name])) <= MONEY_TOLERANCE}
            for name in SUMMARY_FIELDS if name in summary}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("script")
    parser.add_argument("trades", help="TradingView CSV export or a text file with copied Pine Logs (ZF| lines)")
    parser.add_argument("--bars", default=str(DATA / "BINANCE_BTCUSDT.P_1D.csv"))
    parser.add_argument("--mintick", type=float, default=0.1)
    parser.add_argument("--timeframe-seconds", type=int, default=86_400)
    parser.add_argument("--tickerid", default="BINANCE:BTCUSDT.P")
    parser.add_argument("--currency", default="USDT")
    parser.add_argument("--security-bars", action="append", default=[], metavar="TF=BARS.csv",
                        help="frozen bars for request.security() on the chart's symbol, e.g. 60=OANDA_XAUUSD_60.csv")
    parser.add_argument("--json", help="write the machine-readable report here")
    args = parser.parse_args(argv)
    frame = load_bars(Path(args.bars))
    security = {tf: load_bars(Path(path)) for tf, _, path in (item.partition("=") for item in args.security_bars)}
    broker = run_strategy(Path(args.script).read_text(), frame, mintick=args.mintick,
                          timeframe_seconds=args.timeframe_seconds, tickerid=args.tickerid,
                          security_frames=security or None, currency=args.currency)
    report = compare(parse_trades(Path(args.trades)), broker, frame, mintick=args.mintick,
                     until=frame["timestamp"].iloc[-1].to_pydatetime())
    print(report.text())
    if args.json:
        payload = report.as_dict()
        text = Path(args.trades).read_text(encoding="utf-8-sig")
        if "ZF|" in text:
            payload["summary"] = compare_summary(parse_pine_logs(text)[1], broker)
        Path(args.json).write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    return 0 if report.first_divergence is None else 1


if __name__ == "__main__":
    sys.exit(main())
