"""Read-only Setup A regime and failure diagnostics dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from research.setup_a_regime_diagnostics import REPORT
from ui.setup_a_regime_research import render_setup_a_regime_research
from ui.setup_a_long_history import render_setup_a_long_history


def render_setup_a_diagnostics() -> None:
    st.divider()
    st.header("Setup A Diagnostics")
    st.caption("DIAGNOSTIC ONLY · NO OPTIMIZATION · Original V2.2 standalone Setup A")
    if not (REPORT / "year_comparison.csv").exists():
        st.caption("Setup A diagnostic reports are not available yet.")
        return
    years = pd.read_csv(REPORT / "year_comparison.csv")
    profile = pd.read_csv(REPORT / "winner_loser_profile.csv")
    failure = pd.read_csv(REPORT / "failure_comparison.csv")
    excursions = pd.read_csv(REPORT / "mfe_mae.csv")
    direction = pd.read_csv(REPORT / "direction_by_year.csv")
    times = pd.read_csv(REPORT / "time_analysis.csv")
    buckets = pd.read_csv(REPORT / "regime_buckets.csv")
    costs = pd.read_csv(REPORT / "cost_by_year.csv")
    feeds = pd.read_csv(REPORT / "feed_sensitivity_by_year.csv")
    baseline = pd.read_csv(REPORT.parent / "native_results.csv")
    zero = baseline.loc[(baseline.feed == "exness_native") &
                        (baseline.scope == "full_native") &
                        (baseline.cost_view == "zero_cost")].iloc[0]
    fixed_ten = baseline.loc[(baseline.feed == "exness_native") &
                             (baseline.scope == "full_native") &
                             (baseline.cost_view == "fixed_spread_$10")].iloc[0]
    st.subheader("Frozen baseline")
    cards = st.columns(4)
    cards[0].metric("Trades", int(zero.trades))
    cards[1].metric("PF", f"{zero.profit_factor:.3f}")
    cards[2].metric("Average R", f"{zero.average_r:.3f}")
    cards[3].metric("Worst segment DD", f"{zero.worst_segment_dd_percent:.2f}%")
    st.caption(f"Zero-cost net PnL ${zero.net_pnl:,.2f}. Each continuous data segment resets strategy and account state.")
    st.caption(f"Fixed $10 spread sensitivity: PF {fixed_ten.profit_factor:.3f}, "
               f"average R {fixed_ten.average_r:.3f}, net PnL ${fixed_ten.net_pnl:,.2f}.")
    st.subheader("2024 vs 2025 vs 2026")
    show = years.loc[years.year.isin([2024, 2025, 2026])]
    st.dataframe(show[["year", "signals", "pending_orders", "fills",
                       "completed_trades", "fill_rate_percent", "win_rate_percent",
                       "profit_factor", "average_r", "median_mfe_r", "median_mae_r",
                       "never_reached_0.5r_percent", "losers_reached_1r_percent"]].round(3),
                 hide_index=True, width="stretch")
    st.caption("Median signal-time regime descriptors by year")
    st.dataframe(show[["year", "median_atr_percent", "median_adx",
                       "median_h1_slope_percent",
                       "median_recent_volatility_24h_percent",
                       "median_directional_efficiency_24h"]].round(3),
                 hide_index=True, width="stretch")
    st.subheader("Winner vs loser profile")
    scope = st.selectbox("Profile population", list(profile.scope.unique()),
                         key="setup_a_diagnostics_profile_scope")
    st.dataframe(profile.loc[profile.scope.eq(scope),
                             ["outcome", "descriptor", "count", "mean", "median",
                              "p25", "p75"]].round(3), hide_index=True, width="stretch")
    st.caption("2025 losing trades versus 2024 and 2026 completed trades; median differences are descriptive.")
    st.dataframe(failure[["descriptor", "losing_2025_count", "losing_2025_median",
                          "losing_2025_p25", "losing_2025_p75", "other_years_count",
                          "other_years_median", "other_years_p25", "other_years_p75",
                          "median_shift_over_reference_iqr", "adequate_sample"]].round(3),
                 hide_index=True, width="stretch")
    st.subheader("MFE / MAE")
    st.caption("Conservative post-fill M15 OHLC excursion; uncertain intrabar extremes are excluded.")
    st.dataframe(excursions.loc[excursions.direction.eq("All"),
                                ["year", "trades", "median_mfe_r", "median_mae_r",
                                 "never_reached_0.5r_percent",
                                 "losers_reached_0.5r_percent",
                                 "losers_reached_1r_percent",
                                 "losers_reached_1.5r_percent",
                                 "losers_reached_2r_percent"]].round(2),
                 hide_index=True, width="stretch")
    st.subheader("Long vs Short")
    st.dataframe(direction.loc[direction.year.isin([2024, 2025, 2026]),
                                ["year", "direction", "trades", "win_rate_percent",
                                 "profit_factor", "average_r", "net_pnl"]].round(3),
                 hide_index=True, width="stretch")
    st.subheader("Time analysis")
    dimension = st.selectbox("Time grouping", list(times.dimension.unique()),
                             key="setup_a_diagnostics_time_dimension")
    st.dataframe(times.loc[(times.scope.eq("All")) & times.dimension.eq(dimension),
                           ["value", "trades", "win_rate_percent", "profit_factor",
                            "average_r", "low_sample"]].round(3),
                 hide_index=True, width="stretch")
    st.subheader("Regime buckets")
    st.caption("Descriptive quartiles and fixed ADX/stop bins. Small samples are flagged; no bucket changes strategy decisions.")
    descriptor = st.selectbox("Regime descriptor", list(buckets.descriptor.unique()),
                              key="setup_a_diagnostics_bucket")
    chosen = buckets.loc[buckets.descriptor.eq(descriptor)]
    st.dataframe(chosen[["scope", "bucket", "trades", "profit_factor",
                         "average_r", "net_pnl", "low_sample"]].round(3),
                 hide_index=True, width="stretch")
    st.subheader("Cost resilience by year")
    fig = px.line(costs.loc[costs.year.isin([2024, 2025, 2026])],
                  x="spread_usd_per_btc", y="profit_factor", color="year",
                  markers=True, template="plotly_dark")
    st.plotly_chart(fig, width="stretch")
    st.caption("Fixed spreads are sensitivity views, not historical tick-exact costs.")
    st.subheader("Feed sensitivity by year")
    st.dataframe(feeds.loc[feeds.year.isin([2024, 2025, 2026])].round(2),
                 hide_index=True, width="stretch")
    render_setup_a_regime_research()
    render_setup_a_long_history()
