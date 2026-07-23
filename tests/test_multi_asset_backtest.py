import pandas as pd
import pytest

from quant_trade.backtest.costs import CostModel
from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.data.panel import load_canonical_dataset
from quant_trade.research.signals.trend import equal_weight_buy_and_hold

DATA = "examples/data/sample_multi_asset_ohlcv.csv"


def _two_asset_data():
    data = load_canonical_dataset(DATA).query("symbol in ['SPY','QQQ']")
    dates = sorted(data["timestamp"].unique())[:4]
    return data[data["timestamp"].isin(dates)].copy(), dates


def test_backtest_outputs_and_costs():
    data = load_canonical_dataset(DATA).query("symbol in ['SPY','QQQ']")
    w = equal_weight_buy_and_hold(data, {"max_weight_per_asset": 0.5})
    a = run_multi_asset_backtest(data, w, 10000, CostModel())
    b = run_multi_asset_backtest(data, w, 10000, CostModel(percentage_commission=0.01))
    assert {
        "timestamp",
        "equity",
        "cash",
        "gross_exposure",
        "net_exposure",
        "turnover",
        "number_of_positions",
    } <= set(a.equity_curve.columns)
    assert not a.positions.empty and not a.trades.empty
    assert b.equity_curve.equity.iloc[-1] < a.equity_curve.equity.iloc[-1]
    bad = w.copy()
    bad["target_weight"] = 0.75
    with pytest.raises(ValueError):
        run_multi_asset_backtest(data, bad, 10000, CostModel(), max_weight_per_asset=0.5)


def test_backtest_rejects_duplicate_target_weights():
    data = load_canonical_dataset(DATA).query("symbol in ['SPY','QQQ']")
    weights = equal_weight_buy_and_hold(data, {"max_weight_per_asset": 0.5})
    duplicate = pd.concat([weights, weights.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate timestamp/symbol"):
        run_multi_asset_backtest(data, duplicate)


def test_backtest_rejects_unknown_symbols():
    data = load_canonical_dataset(DATA).query("symbol in ['SPY','QQQ']")
    weights = equal_weight_buy_and_hold(data, {"max_weight_per_asset": 0.5})
    weights.loc[weights.index[0], "symbol"] = "UNKNOWN"

    with pytest.raises(ValueError, match="unknown symbols"):
        run_multi_asset_backtest(data, weights)


def test_backtest_rejects_non_numeric_target_weights():
    data = load_canonical_dataset(DATA).query("symbol in ['SPY','QQQ']")
    weights = equal_weight_buy_and_hold(data, {"max_weight_per_asset": 0.5})
    weights["target_weight"] = weights["target_weight"].astype(object)
    weights.loc[weights.index[0], "target_weight"] = "not-a-number"

    with pytest.raises(ValueError, match="missing or invalid values"):
        run_multi_asset_backtest(data, weights)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("fixed_commission", -1.0),
        ("percentage_commission", float("nan")),
        ("slippage_bps", float("inf")),
        ("min_commission", -0.01),
        ("spread_bps", -1.0),
    ],
)
def test_cost_model_rejects_invalid_fields(field, value):
    with pytest.raises(ValueError, match=field):
        CostModel(**{field: value})


def test_fully_invested_portfolio_reserves_costs_and_cash():
    data = load_canonical_dataset(DATA).query("symbol in ['SPY','QQQ']")
    weights = equal_weight_buy_and_hold(data, {"max_weight_per_asset": 0.5})

    result = run_multi_asset_backtest(
        data,
        weights,
        10_000,
        CostModel(percentage_commission=0.01, slippage_bps=25, spread_bps=10),
    )

    assert result.equity_curve["cash"].min() >= -1e-9
    assert result.equity_curve["gross_exposure"].max() <= 1 + 1e-9
    assert result.equity_curve["equity"].gt(0).all()
    assert result.equity_curve.notna().all().all()
    assert result.trades["cost"].sum() > 0


def test_rebalance_sells_before_buying():
    data, dates = _two_asset_data()
    weights = pd.DataFrame(
        [
            {"timestamp": dates[0], "symbol": "SPY", "target_weight": 1.0},
            {"timestamp": dates[1], "symbol": "QQQ", "target_weight": 1.0},
        ]
    )

    result = run_multi_asset_backtest(
        data, weights, 10_000, CostModel(percentage_commission=0.001)
    )
    rebalance = result.trades[result.trades["timestamp"] == dates[2]]

    assert list(rebalance["side"]) == ["sell", "buy"]
    assert result.equity_curve["cash"].min() >= -1e-9


def test_extreme_costs_reject_unaffordable_buys_without_negative_cash():
    data, dates = _two_asset_data()
    weights = pd.DataFrame(
        [{"timestamp": dates[0], "symbol": "SPY", "target_weight": 1.0}]
    )

    result = run_multi_asset_backtest(
        data, weights, 10_000, CostModel(fixed_commission=20_000)
    )

    assert result.trades.empty
    assert (result.equity_curve["cash"] == 10_000).all()


def test_integer_and_fractional_sizing_both_respect_cash():
    data, dates = _two_asset_data()
    weights = pd.DataFrame(
        [{"timestamp": dates[0], "symbol": "SPY", "target_weight": 1.0}]
    )
    cost = CostModel(percentage_commission=0.01)

    fractional = run_multi_asset_backtest(data, weights, 10_000, cost)
    integer = run_multi_asset_backtest(
        data, weights, 10_000, cost, fractional_shares=False
    )

    assert fractional.equity_curve["cash"].min() >= -1e-9
    assert integer.equity_curve["cash"].min() >= -1e-9
    assert integer.trades["quantity"].map(float.is_integer).all()


def test_short_and_leverage_flags_fail_closed():
    data, dates = _two_asset_data()
    short_weights = pd.DataFrame(
        [{"timestamp": dates[0], "symbol": "SPY", "target_weight": -0.5}]
    )
    leverage_weights = pd.DataFrame(
        [{"timestamp": dates[0], "symbol": "SPY", "target_weight": 1.2}]
    )

    with pytest.raises(ValueError, match="allow_short"):
        run_multi_asset_backtest(data, short_weights)
    short_result = run_multi_asset_backtest(
        data, short_weights, allow_short=True, cost_model=CostModel()
    )
    assert short_result.equity_curve["net_exposure"].min() < 0
    with pytest.raises(ValueError, match="leverage"):
        run_multi_asset_backtest(data, leverage_weights, max_weight_per_asset=2.0)
    leveraged = run_multi_asset_backtest(
        data,
        leverage_weights,
        allow_leverage=True,
        max_weight_per_asset=2.0,
        cost_model=CostModel(),
    )
    assert leveraged.equity_curve["gross_exposure"].max() > 1


def test_missing_execution_open_does_not_fallback_to_same_bar_close():
    data, dates = _two_asset_data()
    data = data[
        ~((data["timestamp"] == dates[1]) & (data["symbol"] == "QQQ"))
    ].copy()
    weights = pd.DataFrame(
        [{"timestamp": dates[0], "symbol": "QQQ", "target_weight": 1.0}]
    )

    result = run_multi_asset_backtest(data, weights, cost_model=CostModel())

    assert result.trades.empty

