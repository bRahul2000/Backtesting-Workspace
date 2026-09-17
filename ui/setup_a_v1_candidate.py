"""Compact read-only card for the frozen Setup A V1 research candidate."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from research.setup_a_v1_candidate import REPORT, validate_frozen


def render_setup_a_v1_candidate() -> None:
    st.divider()
    st.header("Setup A V1 Candidate")
    path = REPORT / "frozen_strategy.json"
    if not path.exists():
        st.caption("The Setup A V1 candidate manifest is not available yet.")
        return
    config = validate_frozen(path)
    st.caption("RESEARCH FROZEN · NOT LIVE APPROVED · NO OPTIMIZATION")
    cards = st.columns(4)
    cards[0].metric("Primary feed", "Exness BTCUSDm")
    cards[1].metric("Timeframe", "M15")
    cards[2].metric("Target", "3R")
    cards[3].metric("Setup", "A only")
    native = pd.read_csv(REPORT.parent / "native_results.csv")
    exness = native.loc[native.feed.eq("exness_native") &
                        native.scope.eq("full_native") & native.cost_view.eq("zero_cost")].iloc[0]
    periods = pd.read_csv(REPORT.parent / "long_history/period_results.csv")
    bitstamp = periods.loc[periods.period.eq("Full 2021–2026")].iloc[0]
    st.caption(f"Exness native: {int(exness.trades)} trades · zero-cost PF {exness.profit_factor:.3f} · "
               f"average R {exness.average_r:+.3f}. Bitstamp cross-feed 2021–2026: "
               f"{int(bitstamp.trades)} trades · zero-cost PF {bitstamp.profit_factor:.3f} · "
               f"average R {bitstamp.average_r:+.3f}.")
    with st.expander("Known limitations and next stage", expanded=False):
        st.markdown("Exness-native 2025 was negative; Exness and Bitstamp signals differ. "
                    "Full historical tick-exact Bid/Ask execution and spread are unavailable. "
                    "Backtests do not establish forward fills or live reliability. "
                    "The Phase 4K volatility gate and Setup B are excluded.")
        st.markdown("**Next required stage:** MT5 / Exness forward or demo execution validation.")
        st.caption(f"Freeze SHA-256: {config['freeze_hash_sha256']}")
