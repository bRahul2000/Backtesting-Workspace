"""Payload data files (component/blobs.py): exact round trip, stable slots, bounded storage."""
import json

from ui.tradingview_mode.component import blobs


class Store:
    def __init__(self):
        self.files, self.slots = {}, {}

    def add(self, data: bytes, coordinates: str) -> str:
        url = f"/media/{abs(hash(data))}.json"
        self.files[url] = data
        self.slots[coordinates] = url           # one file per slot: a new version replaces the old reference
        return url

    def fetch(self, url):
        return json.loads(self.files[url])


def payload(last_close=100.0, n=3000):
    bars = [{"time": 1_700_000_000 + i * 900, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 0}
            for i in range(n)]
    bars[-1]["close"] = last_close
    return {"contract": 1, "ack": "abc-1", "bars": bars, "logs": [{"level": "info", "message": "x"}] * 80,
            "tester": {"options": {"catalog": ["s" * 400] * 60}, "run": None}, "symbol": "BTCUSDm",
            "overlays": [{"id": 1, "series": [{"name": "EMA", "data": [{"time": b["time"], "value": 1.0} for b in bars]}]}]}


def test_round_trip_is_exact_and_small():
    store, original = Store(), payload()
    sent = blobs.externalize(original, store.add)
    assert blobs.hydrate(sent, store.fetch) == original
    assert len(json.dumps(sent)) < len(json.dumps(original)) / 20
    assert sent["ack"] == "abc-1" and sent["contract"] == 1 and sent["symbol"] == "BTCUSDm"
    assert isinstance(sent["logs"], list)                                   # small, changing: stays inline
    assert set(sent["bars"]) == {"$blob", "tail"} and len(sent["bars"]["tail"]) == blobs.TAIL
    assert set(sent["tester"]["options"]["catalog"]) == {"$json"}             # the large part, stored on its own


def test_live_tick_changes_only_the_inline_tail():
    store = Store()
    first = blobs.externalize(payload(100.0), store.add)
    second = blobs.externalize(payload(101.0), store.add)
    assert first["bars"]["$blob"] == second["bars"]["$blob"]                # same stored base: nothing refetched
    assert first["bars"]["tail"] != second["bars"]["tail"]
    assert blobs.hydrate(second, store.fetch)["bars"][-1]["close"] == 101.0


def test_one_file_per_slot_and_no_runtime_means_inline():
    store = Store()
    for close in range(10):
        blobs.externalize(payload(float(close)), store.add)
    assert len(store.slots) == 3                   # bars, EMA series, tester catalog - never one per rerun
    original = payload()
    assert blobs.externalize(original, add=None) is original or blobs._media_add() is None
