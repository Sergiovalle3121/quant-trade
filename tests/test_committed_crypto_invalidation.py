"""The merged look-ahead panel stays visible but unusable."""

from pathlib import Path

import pytest

from quant_trade.research.holdout_seal import (
    HoldoutSealError,
    assert_dataset_not_invalidated,
    load_invalidation,
)

EXPERIMENT = Path(__file__).resolve().parents[1] / "data" / "experiments" / "crypto_lowcap_2026_08"


def test_committed_panel_digest_is_explicitly_invalidated() -> None:
    invalidation = load_invalidation(EXPERIMENT)
    assert invalidation is not None
    assert invalidation["status"] == "INVALID_LOOKAHEAD"
    assert invalidation["pnl_generation_allowed"] is False
    assert invalidation["holdout_reveal_allowed"] is False
    assert invalidation["candidate_promotion_allowed"] is False
    assert len(invalidation["seal"]) == 64
    with pytest.raises(HoldoutSealError, match="not usable or revealable"):
        assert_dataset_not_invalidated(EXPERIMENT, invalidation["dataset_digest"])
