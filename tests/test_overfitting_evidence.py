import json

import pytest

from quant_trade.research.candidate import SelectionCriteria
from quant_trade.research.multi_asset_runner import _load_overfitting_evidence
from quant_trade.research.overfitting import assess_walk_forward_overfitting
from quant_trade.research.selection import _statistical_reasons


def test_walk_forward_overfitting_evidence_passes_stable_train_winners():
    evidence = assess_walk_forward_overfitting(
        [1.0, 0.75, 1.0, 0.75],
        [0.1, -0.1, 0.2, 0.0],
        parameter_variants=4,
        max_walk_forward_pbo=0.25,
        min_windows=4,
    )
    assert evidence.decision == "PASS"
    assert evidence.walk_forward_pbo == 0.0
    assert evidence.authorized_for_live_trading is False


def test_walk_forward_overfitting_evidence_rejects_rank_collapse_and_thin_history():
    evidence = assess_walk_forward_overfitting(
        [0.25, 0.50, 0.25],
        [1.0, 2.0, 3.0],
        parameter_variants=3,
        max_walk_forward_pbo=0.50,
        min_windows=4,
    )
    assert evidence.decision == "NO-GO"
    assert evidence.walk_forward_pbo == 1.0
    assert any("at least 4" in reason for reason in evidence.reasons)
    assert any("exceeds" in reason for reason in evidence.reasons)


def test_overfitting_evidence_binding_rejects_wrong_dataset_or_strategy(tmp_path):
    path = tmp_path / "evidence.json"
    payload = {
        "strategy": "time_series_momentum",
        "dataset_binding": {"data_sha256": "abc"},
        "decision": "PASS",
        "walk_forward_pbo": 0.0,
        "windows": 4,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    config = {"overfitting_evidence_path": str(path)}

    assert (
        _load_overfitting_evidence(
            config,
            {"data_sha256": "abc"},
            "time_series_momentum",
        )
        == payload
    )
    with pytest.raises(ValueError, match="dataset hash"):
        _load_overfitting_evidence(
            config,
            {"data_sha256": "different"},
            "time_series_momentum",
        )
    with pytest.raises(ValueError, match="strategy"):
        _load_overfitting_evidence(config, {"data_sha256": "abc"}, "other")


def test_conservative_selection_can_require_matching_overfitting_evidence():
    criteria = SelectionCriteria(
        require_walk_forward_overfitting_evidence=True,
        max_walk_forward_pbo=0.50,
        min_walk_forward_windows=4,
    )
    result = {
        "strategy": "time_series_momentum",
        "dataset_binding": {"data_sha256": "abc"},
        "overfitting_evidence": {
            "strategy": "time_series_momentum",
            "dataset_binding": {"data_sha256": "abc"},
            "decision": "PASS",
            "walk_forward_pbo": 0.25,
            "windows": 6,
        },
    }
    assert _statistical_reasons(result, criteria, None) == []

    result["overfitting_evidence"]["walk_forward_pbo"] = 0.75
    result["overfitting_evidence"]["decision"] = "NO-GO"
    reasons = _statistical_reasons(result, criteria, None)
    assert any("did not pass" in reason for reason in reasons)
    assert any("exceeds" in reason for reason in reasons)
