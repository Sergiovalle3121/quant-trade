from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from quant_trade.audit.models import AuditCheck, AuditInput, AuditStatus, AuditVerdict


def test_public_contracts_are_frozen() -> None:
    check = AuditCheck("CODE", "category", AuditStatus.PASS, "ok")
    with pytest.raises(FrozenInstanceError):
        check.summary = "changed"  # type: ignore[misc]


def test_verdict_refuses_real_money_authorization() -> None:
    with pytest.raises(ValueError, match="never authorize"):
        AuditVerdict(AuditStatus.PASS, (), 1, 0, 0, real_money_authorized=True)


@pytest.mark.parametrize(
    "field",
    ["expected_profit_established", "external_action_authorized"],
)
def test_verdict_refuses_profit_claims_and_external_actions(field: str) -> None:
    with pytest.raises(ValueError, match="never"):
        AuditVerdict(AuditStatus.PASS, (), 1, 0, 0, **{field: True})


def test_input_serialization_preserves_tuples() -> None:
    audit_input = AuditInput(
        root_dir="root",
        dataset_path="data.csv",
        results_path="results.json",
        manifest_path=None,
        trial_ledger_path=None,
        evaluation_cutoff_utc="2024-01-01T00:00:00Z",
        required_columns=("timestamp", "close"),
    )
    assert audit_input.to_dict()["required_columns"] == ("timestamp", "close")
