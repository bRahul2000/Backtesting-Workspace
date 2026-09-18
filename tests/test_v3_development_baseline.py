from __future__ import annotations

import pandas as pd

from research.v3_regime_adaptive_baseline import (DEVELOPMENT_END, DEVELOPMENT_START,
                                                   V3WarmupPlan, v3_warmup_plan)
from strategies.btc_v3_regime_adaptive import V3Parameters


def test_v3_development_window_never_includes_forward_validation():
    assert DEVELOPMENT_START == pd.Timestamp("2021-01-01 00:00:00", tz="UTC")
    assert DEVELOPMENT_END == pd.Timestamp("2024-12-31 23:45:00", tz="UTC")
    assert DEVELOPMENT_END < pd.Timestamp("2025-01-01", tz="UTC")


def test_v3_warmup_requires_h1_ema200_plus_four_closed_h1_bars():
    start = pd.Timestamp("2021-01-01 00:00:00", tz="UTC")
    plan = v3_warmup_plan(V3Parameters(), start)
    assert isinstance(plan, V3WarmupPlan)
    assert plan.confirmed_h1_bars == 204
    assert plan.m15_bars >= 50
    assert plan.first_search_time == pd.Timestamp("2021-01-09 12:00:00", tz="UTC")
