"""Deterministic aggregation and source-gap checks for frozen Setup A research."""
from types import SimpleNamespace

import pandas as pd
import pytest

import research.setup_a_long_history as history


def _data():
    times = pd.to_datetime(["2021-01-01T00:00:00Z", "2021-01-01T00:15:00Z",
                            "2021-01-01T00:30:00Z", "2022-01-01T00:00:00Z",
                            "2022-01-01T00:15:00Z", "2022-01-01T00:30:00Z"])
    return pd.DataFrame({"timestamp": times, "open": [100.] * 6,
                         "high": [101.] * 6, "low": [99.] * 6,
                         "close": [100.] * 6, "volume": [1.] * 6})


def _trades():
    return pd.DataFrame({
        "segment_id": ["bitstamp-S01", "bitstamp-S01", "bitstamp-S02"],
        "signal_year": [2021, 2021, 2022],
        "signal_time": pd.to_datetime(["2021-01-01T01:00:00Z",
                                       "2021-01-02T01:00:00Z", "2022-01-01T01:00:00Z"]),
        "exit_time": pd.to_datetime(["2021-01-01T02:00:00Z",
                                     "2021-01-02T02:00:00Z", "2022-01-01T02:00:00Z"]),
        "direction": ["LONG", "SHORT", "LONG"],
        "gross_pnl": [25., -25., 50.], "realized_r": [1., -1., 2.],
        "quantity": [1., 1., 1.], "planned_risk": [25., 25., 25.],
        "mfe_r": [1.2, .2, 2.2], "mae_r": [.3, 1., .4],
        "reached_0.5r": [True, False, True],
        "reached_1r": [True, False, True],
        "reached_1.5r": [False, False, True],
        "reached_2r": [False, False, True],
        "reached_3r": [False, False, False],
    })


def test_setup_a_resets_strategy_and_account_at_every_segment(monkeypatch):
    seen = []
    monkeypatch.setattr(history, "setup_a_warmup",
                        lambda params, start: (2, start + pd.Timedelta(minutes=15)))

    def fake_backtest(frame, strategy, settings, *, trade_start):
        seen.append((id(strategy), frame.timestamp.iloc[0], frame.timestamp.iloc[-1],
                     trade_start, settings.starting_balance))
        return SimpleNamespace(order_events=[], trades=[], equity_curve=[],
                               open_position=None, pending_order=None)

    monkeypatch.setattr(history, "run_backtest", fake_backtest)
    _, _, trades, segments = history.run_segments(_data())
    assert trades.empty
    assert len(seen) == 2 and seen[0][0] != seen[1][0]
    assert all(record[4] == history.SETTINGS.starting_balance for record in seen)
    assert seen[0][2] < seen[1][1]
    assert segments.usable.all()


def test_yearly_and_period_aggregation_and_trade_frequency():
    signals = pd.DataFrame({"signal_year": [2021, 2021, 2021, 2022]})
    fills = pd.DataFrame({"signal_year": [2021, 2021, 2022]})
    trades = _trades()
    annual = history.yearly_results(signals, fills, trades, _data())
    y2021 = annual.loc[annual.year.eq(2021)].iloc[0]
    assert (y2021.signals, y2021.fills, y2021.trades) == (3, 2, 2)
    assert y2021.observed_months == 1
    assert y2021.signals_per_observed_month == 3
    assert y2021.trades_per_observed_month == 2
    assert y2021.average_r == 0
    periods = history.period_results(signals, fills, trades, _data())
    early = periods.loc[periods.period.eq("2021–2022")].iloc[0]
    assert early.trades == 3 and early.signals == 4
    assert early.observed_months == 2
    assert early.trades_per_observed_month == 1.5
    assert early.worst_segment_dd_percent > 0


def test_pre_exness_classification_and_direction_by_year():
    trades = _trades()
    later = trades.iloc[[0]].assign(
        segment_id="bitstamp-S03", signal_year=2023,
        signal_time=pd.Timestamp("2023-11-09T00:00:00Z"),
        exit_time=pd.Timestamp("2023-11-09T01:00:00Z"))
    all_trades = pd.concat([trades, later], ignore_index=True)
    pre = history.pre_exness_results(all_trades)
    assert pre.query('period == "Full pre-Exness" and direction == "ALL"').iloc[0].trades == 3
    assert pre.query('period == "2023" and direction == "ALL"').iloc[0].trades == 0
    direction = history.direction_results(all_trades)
    assert direction.query('period == "2021" and direction == "LONG"').iloc[0].trades == 1
    assert direction.query('period == "2021" and direction == "SHORT"').iloc[0].trades == 1


def test_mfe_mae_yearly_and_losing_reach_rates():
    result = history.mfe_mae_results(_trades())
    y2021 = result.loc[result.period.eq("2021")].iloc[0]
    assert y2021.median_mfe_r == pytest.approx(.7)
    assert y2021.median_mae_r == pytest.approx(.65)
    assert y2021["reached_0.5r_percent"] == 50
    assert y2021["losers_reached_0.5r_percent"] == 0
    assert y2021["reached_2r_percent"] == 0


def test_hypothetical_cost_label_and_zero_cost_identity():
    result = history.cost_sensitivity(_trades())
    zero = result.query('period == "Full 2021–2026" and spread_usd_per_btc == 0').iloc[0]
    costly = result.query('period == "Full 2021–2026" and spread_usd_per_btc == 10').iloc[0]
    assert zero.net_pnl == 50
    assert zero.cost_label == "ZERO COST"
    assert costly.net_pnl == 20
    assert "HYPOTHETICAL" in costly.cost_label
    assert "NOT HISTORICAL EXNESS" in costly.cost_label


def test_drawdown_resets_at_source_gap():
    trades = _trades().iloc[[0, 2]].copy()
    trades["gross_pnl"] = [-1000., -1000.]
    # Each independent 10,000 account loses 10%; no synthetic 20% curve.
    assert history.worst_segment_dd(trades) == pytest.approx(10.)
