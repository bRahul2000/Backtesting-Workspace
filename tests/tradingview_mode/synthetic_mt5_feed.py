"""Synthetic stand-in for TradingViewLiveFeed.mq5 (tests and UI checks only).

Writes the same files, in the same format, as the MQL5 service. It is never
used by the application itself; point TV_MT5_COMMON_FILES at a scratch folder.

    python tests/tradingview_mode/synthetic_mt5_feed.py <folder> [--seconds 600]
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import random
import time

PERIODS = {"M15": 900, "M30": 1800, "H1": 3600}
SPECS = {"BTCUSDm": {"digits": 2, "point": 0.01, "price": 80350.0, "spread": 18.5},
         "XAUUSDm": {"digits": 3, "point": 0.001, "price": 4380.0, "spread": 0.16}}


class SyntheticFeed:
    def __init__(self, folder: Path, symbol: str, *, writer_id: str = "synthetic-1", seed_bars: int = 500):
        self.folder, self.symbol, self.writer_id = Path(folder), symbol, writer_id
        spec = SPECS[symbol]
        self.digits, self.point, self.price, self.spread = spec["digits"], spec["point"], spec["price"], spec["spread"]
        self.seq = 0
        self.seed_bars = seed_bars
        self.bars: dict[str, dict[int, list]] = {period: {} for period in PERIODS}

    def _round(self, value: float) -> float:
        return round(value, self.digits)

    def _touch_bar(self, period: str, now: float, price: float, volume: int = 1) -> None:
        seconds = PERIODS[period]
        start = int(now // seconds * seconds)
        bars = self.bars[period]
        if not bars:  # history before the first live bar
            for index in range(self.seed_bars - 1, 0, -1):
                t = start - index * seconds
                o = self._round(price + math.sin(t / 7200) * 40)
                c = self._round(o + math.cos(t / 3000) * 15)
                bars[t] = [t, o, max(o, c) + self.point * 100, min(o, c) - self.point * 100, c, 100, int(self.spread / self.point)]
        bar = bars.get(start)
        p = self._round(price)
        if bar is None:
            bars[start] = [start, p, p, p, p, volume, int(self.spread / self.point)]
        else:
            bar[2], bar[3], bar[4], bar[5] = max(bar[2], p), min(bar[3], p), p, bar[5] + volume

    def write(self, now: float, *, price: float | None = None, connected: bool = True, server_offset: int = 0,
              written: float | None = None, tick_time: float | None = None, seq: int | None = None,
              write_seed: bool = True) -> dict:
        """Write one quote (and the seed files) exactly like the service."""
        self.price = self.price if price is None else price
        bid = self._round(self.price)
        ask = self._round(bid + self.spread)
        for period in PERIODS:
            self._touch_bar(period, now, bid)
        self.seq = self.seq + 1 if seq is None else seq
        quote = {
            "schema": 1, "writer_id": self.writer_id, "seq": self.seq, "symbol": self.symbol,
            "written_gmt": int(written if written is not None else now), "server_time": int(now) + server_offset,
            "gmt_time": int(now), "connected": connected, "digits": self.digits, "point": self.point,
            "spread_points": int(round(self.spread / self.point)),
            "tick": {"time_msc": int((tick_time if tick_time is not None else now) * 1000), "bid": bid, "ask": ask, "volume": 0},
            "bars": {period: [bar for _, bar in sorted(bars.items())][-3:] for period, bars in self.bars.items()},
        }
        self._atomic(f"tv_live_{self.symbol}_quote.json", json.dumps(quote))
        if write_seed:
            for period, bars in self.bars.items():
                rows = [bar for _, bar in sorted(bars.items())][-self.seed_bars:]
                text = "time,open,high,low,close,tick_volume,spread\n" + "".join(
                    f"{r[0]},{r[1]:.{self.digits}f},{r[2]:.{self.digits}f},{r[3]:.{self.digits}f},{r[4]:.{self.digits}f},{r[5]},{r[6]}\n"
                    for r in rows)
                self._atomic(f"tv_live_{self.symbol}_{period}_seed.csv", text)
        return quote

    def _atomic(self, name: str, text: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / f"{name}.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, self.folder / name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--interval", type=float, default=0.5)
    args = parser.parse_args()
    feeds = [SyntheticFeed(Path(args.folder), symbol) for symbol in SPECS]
    end = time.time() + args.seconds
    while time.time() < end:
        now = time.time()
        for feed in feeds:
            feed.write(now, price=feed.price + random.uniform(-1, 1) * feed.spread / 3)
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
