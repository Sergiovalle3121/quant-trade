"""End-to-end safe supervised ML baseline workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from quant_trade.backtest.multi_asset import run_multi_asset_backtest
from quant_trade.data.csv_loader import load_ohlcv_csv
from quant_trade.data.providers import get_data_provider
from quant_trade.data.requests import HistoricalDataRequest
from quant_trade.ml.baselines import make_model
from quant_trade.ml.config import MLConfig, dump_ml_config
from quant_trade.ml.evaluation import prediction_metrics, predictions_to_weights
from quant_trade.ml.features import FEATURE_COLUMNS, generate_features
from quant_trade.ml.labels import generate_labels
from quant_trade.ml.leakage import check_leakage
from quant_trade.ml.reports import write_model_card
from quant_trade.ml.splits import chronological_split


def load_data(config: MLConfig) -> pd.DataFrame:
    if config.data_path:
        return load_ohlcv_csv(Path(config.data_path))
    request = HistoricalDataRequest(
        provider=config.provider,
        symbols=config.symbols,
        start=config.start,
        end=config.end,
        interval=config.interval,
        seed=config.seed,
    )
    return get_data_provider(config.provider).fetch_ohlcv(request)


def build_dataset(data: pd.DataFrame, config: MLConfig) -> pd.DataFrame:
    features = generate_features(data)
    labels = generate_labels(data, config.horizon_days)
    return features.merge(labels, on=["timestamp", "symbol"], how="inner")


def fit_predict(
    train: pd.DataFrame, test: pd.DataFrame, model_name: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    x_train = train[FEATURE_COLUMNS].fillna(0.0)
    y_train = (
        train["direction"]
        if model_name == "logistic_regression"
        else train["forward_return"]
    )
    model = make_model(model_name).fit(x_train, y_train.fillna(0.0))

    def attach(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame[["timestamp", "symbol", "forward_return", "direction"]].copy()
        out["prediction"] = model.predict(frame[FEATURE_COLUMNS].fillna(0.0))
        return out

    return attach(train), attach(test)


def run_ml_workflow(config: MLConfig, *, stage: str = "run") -> dict[str, Any]:
    data = load_data(config)
    features = generate_features(data)
    labels = generate_labels(data, config.horizon_days)
    dataset = features.merge(labels, on=["timestamp", "symbol"], how="inner").dropna(
        subset=["forward_return"]
    )
    train, test = chronological_split(
        dataset, config.train_fraction, config.embargo_days
    )
    leakage = check_leakage(features, labels, train, test)
    out = config.output_dir
    out.mkdir(parents=True, exist_ok=True)
    dump_ml_config(config, out / "ml_config_used.yaml")
    features.to_csv(out / "features.csv", index=False)
    labels.to_csv(out / "labels.csv", index=False)
    (out / "leakage_report.json").write_text(
        json.dumps(leakage, indent=2), encoding="utf-8"
    )
    result: dict[str, Any] = {"output_dir": str(out), "leakage_report": leakage}
    if stage in {"features", "leakage-check"}:
        return result
    pred_train, pred_test = fit_predict(train, test, config.model)
    pred_train.to_csv(out / "predictions_train.csv", index=False)
    pred_test.to_csv(out / "predictions_test.csv", index=False)
    mt = prediction_metrics(pred_train, config.prediction_bucket_count) | {
        "leakage_check_status": leakage["status"],
        "real_money_ready": False,
    }
    ms = prediction_metrics(pred_test, config.prediction_bucket_count) | {
        "leakage_check_status": leakage["status"],
        "real_money_ready": False,
    }
    (out / "metrics_train.json").write_text(json.dumps(mt, indent=2), encoding="utf-8")
    (out / "metrics_test.json").write_text(json.dumps(ms, indent=2), encoding="utf-8")
    weights = predictions_to_weights(pred_test, config.top_fraction)
    bt = (
        run_multi_asset_backtest(
            data, weights, initial_cash=config.initial_cash
        ).metrics
        if not weights.empty
        else {}
    )
    bt["real_money_ready"] = False
    (out / "backtest_metrics.json").write_text(
        json.dumps(bt, indent=2), encoding="utf-8"
    )
    write_model_card(config, out, ms, leakage)
    result.update({"metrics_test": ms, "backtest_metrics": bt})
    return result
