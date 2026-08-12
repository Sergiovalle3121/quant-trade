"""Crypto research cannot bypass the causal evaluator and sealed Gate 3."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from quant_trade.cli import app
from quant_trade.research import runner as single_asset_runner
from quant_trade.research import walk_forward as single_asset_walk_forward
from quant_trade.research.candidate import CandidateStrategy
from quant_trade.research.crypto_route_guard import mapping_requires_sealed_crypto_route
from quant_trade.research.experiment_config import ExperimentConfig
from quant_trade.research.multi_asset_runner import run_multi_asset_research_experiment
from quant_trade.research.promotion import evaluate_promotion
from quant_trade.research.promotion_v2 import PromotionPolicyV2, evaluate_promotion_v2
from quant_trade.research.strategy_registry import get_research_signal_model
from quant_trade.research.walk_forward_multi import run_multi_asset_walk_forward


def _single_asset_config(data_path: str) -> ExperimentConfig:
    return ExperimentConfig(
        experiment_name="renamed_legacy_model",
        strategy="sma_crossover",
        strategy_params={"fast_window": 2, "slow_window": 3},
        parameter_grid={"fast_window": [2], "slow_window": [3]},
        data_path=data_path,
    )


def _single_asset_entrypoint(workflow: str):
    return (
        single_asset_runner.run_experiment
        if workflow == "experiment"
        else single_asset_walk_forward.run_walk_forward
    )


def _single_asset_module(workflow: str):
    return single_asset_runner if workflow == "experiment" else single_asset_walk_forward


def test_generic_runner_blocks_crypto_before_reading_a_dataset(tmp_path) -> None:
    with pytest.raises(ValueError, match="P&L generation is disabled"):
        run_multi_asset_research_experiment(
            {
                "mode": "multi_asset_research",
                "strategy": "crypto_capacity_illiquidity",
                "data_path": str(tmp_path / "missing.csv"),
            }
        )


@pytest.mark.parametrize("workflow", ["experiment", "walk_forward"])
def test_single_asset_runners_block_crypto_config_or_path_before_reading_bytes(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    workflow: str,
) -> None:
    def unexpected_read(*_args, **_kwargs):
        raise AssertionError("crypto route guard must run before dataset I/O")

    module = _single_asset_module(workflow)
    monkeypatch.setattr(module, "load_ohlcv", unexpected_read)
    cfg = _single_asset_config(str(tmp_path / "hidden_bybit_prices.csv"))

    with pytest.raises(ValueError, match="sealed crypto runner"):
        _single_asset_entrypoint(workflow)(cfg)

    cfg = _single_asset_config(str(tmp_path / "missing_prices.csv"))
    cfg.strategy = "crypto_capacity_illiquidity"
    with pytest.raises(ValueError, match="sealed crypto runner"):
        _single_asset_entrypoint(workflow)(cfg)


@pytest.mark.parametrize("workflow", ["experiment", "walk_forward"])
def test_single_asset_runners_block_crypto_columns_after_loading_renamed_strategy(
    tmp_path,
    workflow: str,
) -> None:
    data_path = tmp_path / "innocent_prices.csv"
    data_path.write_text(
        "timestamp,open,high,low,close,volume,symbol\n"
        "2024-01-01,10,11,9,10,1000,CMC:7\n"
        "2024-01-02,10,11,9,10,1000,CMC:7\n",
        encoding="utf-8",
    )
    cfg = _single_asset_config(str(data_path))

    with pytest.raises(ValueError, match="loaded crypto records"):
        _single_asset_entrypoint(workflow)(cfg)


@pytest.mark.parametrize("command", ["run-experiment", "walk-forward"])
def test_single_asset_cli_entrypoints_inherit_runner_crypto_guard(
    tmp_path,
    command: str,
) -> None:
    config_path = tmp_path / "experiment.json"
    config_path.write_text(
        json.dumps(
            {
                "experiment_name": "renamed_legacy_model",
                "strategy": "sma_crossover",
                "strategy_params": {"fast_window": 2, "slow_window": 3},
                "parameter_grid": {"fast_window": [2], "slow_window": [3]},
                "data_path": str(tmp_path / "missing_bybit_prices.csv"),
            }
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(app, [command, "--config", str(config_path)])

    assert result.exit_code != 0
    assert result.exception is not None
    assert "sealed crypto runner" in str(result.exception)


def test_generic_runner_blocks_renamed_crypto_from_config_identity(tmp_path) -> None:
    with pytest.raises(ValueError, match="P&L generation is disabled"):
        run_multi_asset_research_experiment(
            {
                "mode": "multi_asset_research",
                "strategy": "innocent_renamed_model",
                "asset_class": "crypto",
                "data_path": str(tmp_path / "missing.csv"),
            }
        )


def test_nested_universe_symbols_cannot_hide_crypto_identity() -> None:
    assert mapping_requires_sealed_crypto_route(
        {"strategy": "renamed_model", "universe": {"symbols": ["CMC:7"]}}
    )


def test_generic_walk_forward_blocks_crypto_before_reading_dataset(tmp_path) -> None:
    with pytest.raises(ValueError, match="generic walk-forward runner"):
        run_multi_asset_walk_forward(
            {
                "mode": "multi_asset_walk_forward",
                "strategy": "crypto_capacity_illiquidity",
                "data_path": str(tmp_path / "missing.csv"),
            }
        )


def test_registry_requires_explicit_sealed_crypto_capability() -> None:
    with pytest.raises(ValueError, match="sealed crypto runner"):
        get_research_signal_model("crypto_capacity_illiquidity")
    assert (
        get_research_signal_model("crypto_capacity_illiquidity", allow_sealed_crypto=True).name
        == "crypto_capacity_illiquidity"
    )


def _candidate(tmp_path) -> CandidateStrategy:
    return CandidateStrategy(
        candidate_id="crypto-h1",
        name="H1",
        strategy_name="crypto_capacity_illiquidity",
        strategy_params={},
        universe=["CMC:7"],
        benchmark="dual",
        data_start="2020-01-01",
        data_end="2022-01-01",
        research_run_dir=str(tmp_path),
        selected_at_utc="2026-08-11T00:00:00Z",
        selected_by="test",
        approval_notes="reviewed",
    )


def test_legacy_v1_promotion_rejects_crypto_even_with_friendly_artifacts(tmp_path) -> None:
    (tmp_path / "results.json").write_text("{}", encoding="utf-8")
    report = evaluate_promotion(
        _candidate(tmp_path),
        tmp_path,
        {"kill_switch_enabled": True},
    )
    check = next(c for c in report.checks if c.name == "crypto_requires_gate3_verdict")
    assert check.status == "fail"
    assert report.overall_status == "fail"


def test_legacy_v1_rejects_renamed_strategy_from_stable_instrument_identity(tmp_path) -> None:
    candidate = _candidate(tmp_path)
    candidate.strategy_name = "innocent_renamed_model"
    (tmp_path / "results.json").write_text("{}", encoding="utf-8")
    report = evaluate_promotion(candidate, tmp_path, {"kill_switch_enabled": True})
    check = next(c for c in report.checks if c.name == "crypto_requires_gate3_verdict")
    assert check.status == "fail"


def test_legacy_v2_promotion_rejects_crypto(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "results.json").write_text(
        json.dumps({"strategy": "crypto_capacity_illiquidity"}),
        encoding="utf-8",
    )
    decision = evaluate_promotion_v2(
        run_dir,
        PromotionPolicyV2(require_approval_notes=False),
        ledger_dir=tmp_path,
    )
    assert "crypto_requires_sealed_gate3" in decision.failed_gates
    assert decision.status == "rejected"


def test_legacy_v2_rejects_crypto_dataset_when_strategy_is_renamed(tmp_path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "results.json").write_text(
        json.dumps(
            {
                "strategy": "innocent_renamed_model",
                "dataset_binding": {"venue": "bybit", "dataset_id": "panel-v2"},
            }
        ),
        encoding="utf-8",
    )
    decision = evaluate_promotion_v2(
        run_dir,
        PromotionPolicyV2(require_approval_notes=False),
        ledger_dir=tmp_path,
    )
    assert "crypto_requires_sealed_gate3" in decision.failed_gates
    assert decision.status == "rejected"
