"""Pre-registration: sealed before the run, revealable after, binding on promotion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.research.preregistration import (
    ExperimentPreregistration,
    PreregistrationError,
    assert_within_budget,
    budget_status,
    load_preregistration,
    seal_preregistration,
    trials_for_seal,
    verify,
)


def _prereg(**overrides) -> ExperimentPreregistration:
    payload = {
        "experiment_id": "lowcap-momentum-2026Q3",
        "hypothesis": "cross-sectional momentum on low-cap crypto beats equal weight net of costs",
        "universe": ["AAA", "BBB", "CCC"],
        "start_date": "2021-01-01",
        "end_date": "2025-12-31",
        "selection_criterion": {"min_deflated_sharpe": 0.95, "require_beats_benchmark": True},
        "max_trials": 12,
        "refutation": "deflated Sharpe below 0.95 after the full recorded trial count",
        "registered_at_utc": "2026-08-03T00:00:00Z",
    }
    payload.update(overrides)
    return ExperimentPreregistration(**payload)


# --- the declaration must actually declare something ----------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("hypothesis", "  "),
        ("universe", []),
        ("refutation", ""),
        ("selection_criterion", {}),
        ("max_trials", 0),
        ("experiment_id", ""),
    ],
)
def test_an_empty_declaration_is_refused(field: str, value) -> None:
    with pytest.raises(PreregistrationError):
        _prereg(**{field: value})


def test_a_backwards_date_range_is_refused() -> None:
    with pytest.raises(PreregistrationError):
        _prereg(start_date="2025-01-01", end_date="2021-01-01")


def test_refutation_is_mandatory_because_an_unfalsifiable_claim_is_not_a_test() -> None:
    with pytest.raises(PreregistrationError, match="refuted"):
        _prereg(refutation="   ")


# --- sealing --------------------------------------------------------------


def test_the_seal_covers_the_declaration_and_nothing_else() -> None:
    """Filing metadata must not move the seal; a claim change must."""
    base = _prereg()
    assert _prereg(notes=["filed by hand"]).seal() == base.seal()
    assert _prereg(hypothesis="something else entirely").seal() != base.seal()
    assert _prereg(max_trials=13).seal() != base.seal()
    assert _prereg(universe=["AAA", "BBB"]).seal() != base.seal()


def test_a_sealed_declaration_round_trips_and_verifies(tmp_path: Path) -> None:
    prereg = _prereg()
    path, seal = seal_preregistration(tmp_path, prereg)
    assert path.exists()
    assert verify(prereg, seal)

    loaded = load_preregistration(tmp_path)
    assert loaded.seal() == seal
    assert loaded.hypothesis == prereg.hypothesis


def test_a_sealed_declaration_is_never_rewritten(tmp_path: Path) -> None:
    """A document that can be replaced after the run is not a pre-registration."""
    seal_preregistration(tmp_path, _prereg())
    with pytest.raises(PreregistrationError, match="never rewritten"):
        seal_preregistration(tmp_path, _prereg(hypothesis="a more convenient claim"))


def test_editing_a_sealed_declaration_is_caught_on_load(tmp_path: Path) -> None:
    """The seal is re-derived from content, so a quiet edit cannot survive."""
    seal_preregistration(tmp_path, _prereg())
    path = tmp_path / "preregistration.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["max_trials"] = 500  # widen the budget after the fact
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(PreregistrationError, match="edited after sealing"):
        load_preregistration(tmp_path)


# --- 3.2: a failed pre-registered trial still counts ----------------------


def test_a_failed_preregistered_trial_counts_toward_the_budget() -> None:
    prereg = _prereg(max_trials=3)
    seal = prereg.seal()
    records = [
        {"preregistration_seal": seal, "status": "evaluated"},
        {"preregistration_seal": seal, "status": "failed"},
        {"preregistration_seal": seal, "status": "discarded"},
    ]
    assert len(trials_for_seal(records, seal)) == 3, (
        "failed and discarded attempts must count: deflation asks how many "
        "attempts were made, not how many worked"
    )
    status = budget_status(prereg, records)
    assert status["trials_spent"] == 3
    assert status["trials_remaining"] == 0
    assert status["over_budget"] is False


def test_spending_more_trials_than_declared_fails_closed() -> None:
    prereg = _prereg(max_trials=2)
    seal = prereg.seal()
    records = [{"preregistration_seal": seal, "status": "failed"} for _ in range(3)]
    assert budget_status(prereg, records)["over_budget"] is True
    with pytest.raises(PreregistrationError, match="no longer true"):
        assert_within_budget(prereg, records)


def test_trials_from_another_experiment_do_not_count() -> None:
    prereg = _prereg()
    other = _prereg(experiment_id="something-else")
    records = [
        {"preregistration_seal": prereg.seal()},
        {"preregistration_seal": other.seal()},
        {"preregistration_seal": ""},
        {},
    ]
    assert len(trials_for_seal(records, prereg.seal())) == 1


# --- the ledger binding ---------------------------------------------------


def test_the_ledger_carries_the_seal_and_defaults_to_unsealed() -> None:
    from quant_trade.research.ledger import build_trial_record

    sealed = build_trial_record(
        source="test", strategy="s", strategy_params={}, run_id="r",
        preregistration_seal="abc123",
    )
    assert sealed.preregistration_seal == "abc123"
    assert "preregistration_seal" in sealed.to_entry()

    undeclared = build_trial_record(
        source="test", strategy="s", strategy_params={}, run_id="r"
    )
    assert undeclared.preregistration_seal == "", (
        "the ledger records what happened; refusing an undeclared trial is "
        "promotion's job, not the ledger's"
    )


def test_the_committed_historical_ledger_stays_readable() -> None:
    """109 real records predate the mechanism and must not become unreadable."""
    from quant_trade.research.ledger import read_trials

    records = read_trials(Path("docs/real_data_evidence"))
    assert len(records) >= 100
    assert all("preregistration_seal" not in r for r in records), (
        "historical rows are expected to lack the field entirely"
    )
