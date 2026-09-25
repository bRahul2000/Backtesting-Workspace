"""Chart / Signal / Execution source roles (read-only; nothing here can trade).

Locked decision (feed-comparison research, 2026-09-25):

* Chart source   - what the chart draws. Binance Futures (default) or Exness MT5.
                   Never authoritative for Exness strategy triggers.
* Signal source  - ALWAYS Exness MT5 for the live market (XAUUSDm / BTCUSDm).
                   It is derived from the market alone, never from the chart
                   source; there is no way to make Binance the signal source.
* Execution      - Exness MT5. Always DISABLED in this phase (``enabled`` is
                   hard-wired to False); it only reports why it would not be ready.

``signal_authority_ready`` is True only when every check passes: provider is
Exness MT5, the symbol matches, the MT5 feed is LIVE (the existing live.py
health logic), the quote and heartbeat are fresh, the timeframe's bars are
present and current, timestamps are valid, and - after any start, outage or
feed restart - REQUIRED_FRESH_UPDATES consecutive fresh updates from one writer
have been seen. Readiness is dropped on the first failing observation and is
never restored just because a file appeared again.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from . import live as mt5
from .providers import MARKETS, SOURCES

SIGNAL_PROVIDER = "exness"
SIGNAL_PROVIDER_LABEL = SOURCES[SIGNAL_PROVIDER]           # "Exness MT5"
EXECUTION_PROVIDER_LABEL = SOURCES[SIGNAL_PROVIDER]
REQUIRED_FRESH_UPDATES = 2       # consecutive advancing updates before authority is (re)granted
REQUIRED_BARS = 200              # timeframe history needed for signals
LOG_LIMIT = 50
EXECUTION_NOT_ENABLED = "Live execution not enabled"
SIGNAL_UNAVAILABLE = "Exness signal source unavailable"
MISMATCH_NOTE = "Chart data and signal data come from different markets. Exness remains authoritative for strategy triggers."


def signal_symbol(market: str) -> str:
    """The authoritative signal symbol of a market (Exness MT5, by definition)."""
    return MARKETS[market][SIGNAL_PROVIDER]


@dataclass(frozen=True)
class SourceRole:
    role: str                    # chart | signal | execution
    provider: str
    symbol: str | None
    state: str
    is_authoritative: bool
    last_update: float | None
    reason: str
    timeframe: str | None = None
    feed_state: str | None = None   # underlying MT5 health for the signal role
    source: str | None = None       # provider key (binance | exness)


@dataclass(frozen=True)
class ExecutionReadiness:
    enabled: bool                # always False in this phase
    broker_connected: bool
    signal_authority_ready: bool
    symbol_match: bool
    market_data_fresh: bool
    reason: str


@dataclass(frozen=True)
class Observation:
    """What the signal feed looks like right now (built by ``observe_exness``)."""

    provider_source: str         # must be "exness"; anything else can never be authoritative
    market: str
    timeframe: str
    symbol: str | None           # symbol the feed reports
    feed_state: str              # LIVE | STALE | CONNECTING | DISCONNECTED | ERROR
    reason: str
    now: float
    writer_id: str | None = None
    seq: int | None = None
    heartbeat_utc: float | None = None
    tick_time_ms: int | None = None
    connected: bool = False
    bar_times: tuple[int, ...] = ()


@dataclass(frozen=True)
class AuthorityTracker:
    market: str | None = None
    timeframe: str | None = None
    ready: bool = False
    writer_id: str | None = None
    last_seq: int | None = None
    confirmations: int = 0
    feed_state: str | None = None
    ever_ready: bool = False
    execution_reason: str | None = None


@dataclass(frozen=True)
class Assessment:
    ready: bool
    checks: tuple[tuple[str, bool, str], ...]
    reason: str
    confirmations: int


# ---------------------------------------------------------------------------
# Reading the signal feed (read-only)
# ---------------------------------------------------------------------------

def observe_exness(market: str, timeframe: str, now: float, folder: Path | None = None) -> Observation:
    """Observe the Exness MT5 signal feed for a market/timeframe (never Binance)."""
    symbol = signal_symbol(market)
    feed = mt5.read_feed(folder or mt5.common_files_dir(), symbol, timeframe)
    snapshot = feed.snapshot
    bars = pd.DataFrame()
    if snapshot is not None and feed.error is None:
        bars = mt5.merge_bars(feed.seed, snapshot.bars[mt5.LIVE_TIMEFRAMES[timeframe][0]])
    state, reason = mt5.connection_status(file_found=feed.file_found, snapshot=snapshot, error=feed.error,
                                          has_bars=not bars.empty, now=now)
    return Observation(
        provider_source=SIGNAL_PROVIDER, market=market, timeframe=timeframe,
        symbol=snapshot.symbol if snapshot else None, feed_state=state, reason=reason, now=now,
        writer_id=snapshot.writer_id if snapshot else None, seq=snapshot.seq if snapshot else None,
        heartbeat_utc=snapshot.written_utc if snapshot else None,
        tick_time_ms=snapshot.tick_time_ms if snapshot else None, connected=bool(snapshot and snapshot.connected),
        bar_times=tuple(int(t) for t in bars["time"]) if not bars.empty else (),
    )


# ---------------------------------------------------------------------------
# Authority (pure)
# ---------------------------------------------------------------------------

def authority_checks(obs: Observation) -> list[tuple[str, bool, str]]:
    """Every condition for signal authority except revalidation, with reasons."""
    seconds = mt5.LIVE_TIMEFRAMES[obs.timeframe][1]
    expected = signal_symbol(obs.market)
    checks = [("provider", obs.provider_source == SIGNAL_PROVIDER,
               f"{SOURCES.get(obs.provider_source, obs.provider_source)} is not the signal source; "
               f"only {SIGNAL_PROVIDER_LABEL} is authoritative for Exness strategy triggers.")]
    checks.append(("symbol", obs.symbol == expected, f"feed symbol {obs.symbol!r} is not {expected}."))
    checks.append(("connection", obs.feed_state == "LIVE", f"Exness MT5 feed {obs.feed_state}: {obs.reason}"))
    heartbeat_age = None if obs.heartbeat_utc is None else obs.now - obs.heartbeat_utc
    tick_age = None if obs.tick_time_ms is None else obs.now - obs.tick_time_ms / 1000
    fresh = (heartbeat_age is not None and -mt5.MAX_FUTURE_SKEW_S <= heartbeat_age <= mt5.HEARTBEAT_STALE_S
             and tick_age is not None and tick_age <= mt5.TICK_STALE_S)
    checks.append(("fresh_quote", fresh, "the Exness quote or heartbeat is not fresh."))
    enough = len(obs.bar_times) >= REQUIRED_BARS
    checks.append(("timeframe_data", enough, f"{obs.timeframe} history has {len(obs.bar_times)} bars "
                                             f"(needs {REQUIRED_BARS})."))
    times = obs.bar_times
    valid = (bool(times) and all(t % seconds == 0 for t in times[-REQUIRED_BARS:])
             and all(b > a for a, b in zip(times, times[1:]))
             and times[-1] <= obs.now + mt5.MAX_FUTURE_SKEW_S and obs.now - times[-1] < 2 * seconds)
    checks.append(("timestamps", valid, f"{obs.timeframe} bar times are not current, aligned and increasing."))
    return checks


def advance(tracker: AuthorityTracker, obs: Observation) -> tuple[AuthorityTracker, Assessment, list[str]]:
    """Fold one observation into the tracker. Returns (tracker, assessment, log events)."""
    events: list[str] = []
    if (tracker.market, tracker.timeframe) != (obs.market, obs.timeframe):
        tracker = AuthorityTracker(market=obs.market, timeframe=obs.timeframe)
        events.append(f"Signal source: {SIGNAL_PROVIDER_LABEL} · {signal_symbol(obs.market)} · {obs.timeframe}")
    checks = authority_checks(obs)
    valid = all(ok for _, ok, _ in checks)
    confirmations = 0
    if valid:
        same_stream = obs.writer_id == tracker.writer_id and tracker.last_seq is not None
        if same_stream and obs.seq == tracker.last_seq:
            confirmations = tracker.confirmations            # nothing new yet: neither counts nor resets
        elif same_stream and obs.seq > tracker.last_seq:
            confirmations = tracker.confirmations + 1
        else:
            confirmations = 1                                # new writer, restart or first sight
    confirmed = confirmations >= REQUIRED_FRESH_UPDATES
    ready = valid and confirmed
    if not valid:
        reason = next(message for _, ok, message in checks if not ok)
    elif not confirmed:
        reason = f"Revalidating Exness feed ({confirmations}/{REQUIRED_FRESH_UPDATES} fresh updates)."
    else:
        reason = "Exness MT5 signal feed live and validated."
    if obs.feed_state != tracker.feed_state:
        events.append(f"Exness signal source {obs.feed_state}")
    if ready and not tracker.ready:
        events.append("Signal authority restored" if tracker.ever_ready else "Signal authority established")
    elif tracker.ready and not ready:
        events.append(f"Signal authority disabled: {reason}")
    new = replace(tracker, ready=ready, feed_state=obs.feed_state, ever_ready=tracker.ever_ready or ready,
                  confirmations=confirmations,
                  writer_id=obs.writer_id if valid else tracker.writer_id,
                  last_seq=obs.seq if valid else tracker.last_seq)
    return new, Assessment(ready, tuple(checks) + (("revalidated", confirmed, reason),), reason, confirmations), events


def execution_readiness(obs: Observation, assessment: Assessment) -> ExecutionReadiness:
    """Future execution gate. ``enabled`` is always False in this phase."""
    checks = dict((name, ok) for name, ok, _ in assessment.checks)
    return ExecutionReadiness(
        enabled=False, broker_connected=obs.connected, signal_authority_ready=assessment.ready,
        symbol_match=checks.get("symbol", False), market_data_fresh=checks.get("fresh_quote", False),
        reason=EXECUTION_NOT_ENABLED if assessment.ready else SIGNAL_UNAVAILABLE)


def chart_role(live_status: dict) -> SourceRole:
    """The chart role, from the streaming chart provider's status. Never authoritative."""
    return SourceRole("chart", live_status["source_label"], live_status["symbol"], live_status["status"], False,
                      live_status.get("updated_utc"), live_status.get("reason") or "", live_status["timeframe"],
                      source=live_status["source"])


def signal_role(obs: Observation, assessment: Assessment, chart: SourceRole) -> SourceRole:
    if assessment.ready:
        reason = assessment.reason
    elif obs.feed_state != "LIVE":
        reason = ("Exness signal feed unavailable. "
                  + ("Binance chart remains live, but Exness strategy signals are disabled."
                     if chart.source == "binance" and chart.state == "LIVE" else "Exness strategy signals are disabled.")
                  + f" ({obs.reason})")
    else:
        reason = assessment.reason
    return SourceRole("signal", SIGNAL_PROVIDER_LABEL, signal_symbol(obs.market), "LIVE" if assessment.ready else "UNAVAILABLE",
                      True, obs.heartbeat_utc, reason, obs.timeframe, feed_state=obs.feed_state, source=SIGNAL_PROVIDER)


def execution_role(market: str, readiness: ExecutionReadiness) -> SourceRole:
    return SourceRole("execution", EXECUTION_PROVIDER_LABEL, signal_symbol(market), "DISABLED", True, None,
                      readiness.reason, source=SIGNAL_PROVIDER)


def source_payload(chart: SourceRole, signal: SourceRole, execution: SourceRole, readiness: ExecutionReadiness,
                   assessment: Assessment, log: list[dict]) -> dict[str, Any]:
    as_dict = lambda role: {k: v for k, v in role.__dict__.items()}  # noqa: E731
    return {
        "chart": as_dict(chart), "signal": as_dict(signal), "execution": as_dict(execution),
        "signal_authority_ready": assessment.ready,
        "checks": [{"name": name, "ok": ok, "reason": reason} for name, ok, reason in assessment.checks],
        "readiness": dict(readiness.__dict__),
        "note": MISMATCH_NOTE if chart.source != SIGNAL_PROVIDER else None,
        "log": list(log[-LOG_LIMIT:]),
    }


def log_entry(message: str, now: float) -> dict:
    return {"time": datetime.fromtimestamp(now, timezone.utc).strftime("%H:%M:%S"), "message": message}


def append_log(log: list[dict], messages: list[str], now: float) -> list[dict]:
    return (log + [log_entry(m, now) for m in messages])[-LOG_LIMIT:]
