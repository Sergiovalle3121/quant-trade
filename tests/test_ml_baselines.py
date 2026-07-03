import pandas as pd

from quant_trade.ml.baselines import SimpleRankModel


def test_simple_rank_model_predicts_without_sklearn():
    x = pd.DataFrame({"rolling_momentum_10d": [0.1, -0.2, 0.3]})
    y = pd.Series([0.01, -0.01, 0.02])
    preds = SimpleRankModel().fit(x, y).predict(x)
    assert len(preds) == 3
    assert preds[0] > preds[1]
