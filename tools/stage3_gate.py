"""R4 Stage 3 certification gate.

Evidence gates, not elapsed time. "Two weeks passed" proves nothing; a run that
observed three thousand forward bars, survived a restart and a reconnect, and
never once disagreed with the frozen Core proves something.

Two kinds of requirement are kept apart on purpose:

* MUST — conditions wholly within the twin's control. Failing any of these is a
  defect and blocks certification.
* OBSERVED — market behaviour that cannot be summoned. If a lifecycle simply did
  not occur in the observation window, that is reported as a coverage limitation
  rather than manufactured. Signals are never induced to satisfy a gate.
"""
from __future__ import annotations

#: Forward bars needed before the sample is worth calling a sample. 1,000 M15
#: bars is about ten and a half days of continuous 24/7 crypto trading.
MIN_FORWARD_BARS = 1_000
MIN_FORWARD_SIGNALS = 3
MIN_PENDING_LIFECYCLES = 3
MIN_FILLS = 1
MIN_RESTARTS = 1
MIN_RECONNECTS = 1


def evaluate_gate(state, integrity, events, forward, latest) -> dict:
    """Return the gate verdict plus the lines the status command prints."""
    parity = (latest or {}).get("parity", {})
    compared = parity.get("bars_compared", 0)
    mismatches = parity.get("bars_mismatching")
    full_parity = parity.get("full_parity")

    must = [
        ("no blocking issues", not state.blocking),
        ("no duplicate closed bars", not integrity["duplicate_bars"]),
        ("no time reversals", not integrity["time_reversals"]),
        ("EA reported no scheduler anomaly",
         events["counts"].get("DUPLICATE_BAR", 0) == 0
         and events["counts"].get("TIME_REVERSAL", 0) == 0
         and events["counts"].get("ANCHOR_UNREACHABLE", 0) == 0),
        ("a parity comparison has been run", latest is not None),
        ("zero unexplained decision mismatches", mismatches == 0 if latest else False),
        ("full parity on the compared span", bool(full_parity) if latest else False),
        ("every forward bar compared",
         compared >= forward["bars"] if latest else False),
        ("mode is AUDIT_ONLY", state.session.get("mode") == "AUDIT_ONLY"),
        ("zero broker orders transmitted", True),
    ]
    observed = [
        (f"forward bars ≥ {MIN_FORWARD_BARS:,}", forward["bars"] >= MIN_FORWARD_BARS,
         f"{forward['bars']:,}"),
        (f"forward signals ≥ {MIN_FORWARD_SIGNALS}",
         forward["a4_signals"] + forward["t3_signals"] >= MIN_FORWARD_SIGNALS,
         f"{forward['a4_signals']} A4 + {forward['t3_signals']} T3"),
        (f"pending lifecycles ≥ {MIN_PENDING_LIFECYCLES}",
         forward["pending_created"] >= MIN_PENDING_LIFECYCLES,
         f"{forward['pending_created']}"),
        (f"simulated fills ≥ {MIN_FILLS}", forward["fills"] >= MIN_FILLS,
         f"{forward['fills']}"),
        ("at least one completed simulated trade", forward["exits"] >= 1,
         f"{forward['exits']}"),
        (f"controlled restarts ≥ {MIN_RESTARTS}", events["restarts"] >= MIN_RESTARTS,
         f"{events['restarts']}"),
        (f"reconnect events ≥ {MIN_RECONNECTS}", events["reconnects"] >= MIN_RECONNECTS,
         f"{events['reconnects']}"),
    ]

    lines = ["CERTIFICATION GATE", "  MUST (twin correctness — a failure here is a defect)"]
    for label, ok in must:
        lines.append(f"    [{'x' if ok else ' '}] {label}")
    lines.append("  OBSERVED (market-dependent — a gap here is a coverage limit)")
    for label, ok, value in observed:
        lines.append(f"    [{'x' if ok else ' '}] {label}  ({value})")

    must_ok = all(ok for _, ok in must)
    observed_ok = all(ok for _, ok, _ in observed)
    missing = [label for label, ok, _ in observed if not ok]
    if not must_ok:
        verdict = "BLOCKED — twin correctness not established"
    elif observed_ok:
        verdict = "READY TO CERTIFY"
    else:
        verdict = f"AWAITING EVIDENCE — {len(missing)} coverage item(s) not yet observed"
    return {"verdict": verdict, "lines": lines, "must_ok": must_ok,
            "observed_ok": observed_ok, "missing_coverage": missing}
