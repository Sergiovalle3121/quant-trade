"""Crypto research cannot bypass the causal evaluator and sealed Gate 3."""

from __future__ import annotations

import json

import pytest

from quant_trade.research.candidate import CandidateStrategy
from quant_trade.research.multi_asset_runner import run_multi_asset_research_experiment
from quant_trade.research.promotion import evaluate_promotion
from quant_trade.research.promotion_v2 import PromotionPolicyV2, evaluate_promotion_v2


def test_generic_runner_blocks_crypto_before_reading_a_dataset(tmp_path) -> None:
    with pytest.raises(ValueError, match="P&L generation is disabled"):
        run_multi_asset_research_experiment(
            {
                "mode": "multi_asset_research",
                "strategy": "crypto_capacity_illiquidity",
                "data_path": str(tmp_path / "missing.csv"),
            }
        )


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
