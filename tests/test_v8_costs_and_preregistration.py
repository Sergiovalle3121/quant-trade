"""V8 cost stack, break-even arithmetic, holdout guard and pre-registration."""

from __future__ import annotations

import pytest

from quant_trade.v8.costs import (
    COST_EVIDENCE_CLASSES,
    CostComponent,
    CostStack,
    break_even_funding,
    capital_requirement,
    conservative_cost_stack,
)
from quant_trade.v8.holdout import HoldoutGuard, HoldoutViolation, chronological_split
from quant_trade.v8.preregistration import (
    ADDITIONAL_HYPOTHESES,
    MAX_ADDITIONAL_VARIANTS,
    PRIMARY_HYPOTHESES,
    PROMOTION_GATES,
    additional_variant_budget,
    freeze_hash,
    hypothesis,
    preregistration,
)

# --- cost stack ----------------------------------------------------------------


def test_every_component_carries_its_evidence_class() -> None:
    stack = conservative_cost_stack("bybit")
    assert stack.components
    for component in stack.components:
        assert component.evidence_class in COST_EVIDENCE_CLASSES
        assert component.source.strip()


def test_assumed_costs_block_promotion() -> None:
    """The whole point: unverified fee inputs cannot support a promotion."""
    stack = conservative_cost_stack("okx")
    assert stack.weakest_evidence_class == "ASSUMPTION_UNVERIFIED"
    assert not stack.promotable


def test_verified_costs_are_promotable() -> None:
    stack = conservative_cost_stack("bybit", evidence_class="REAL")
    assert stack.promotable
    assert stack.weakest_evidence_class == "REAL"


def test_one_unverified_component_taints_the_stack() -> None:
    verified = conservative_cost_stack("bybit", evidence_class="REAL")
    tainted = CostStack(
        venue="bybit",
        components=(
            *verified.components,
            CostComponent(
                name="guess",
                value=1.0,
                unit="bps_per_fill",
                evidence_class="ASSUMPTION_UNVERIFIED",
                source="a hunch",
            ),
        ),
    )
    assert not tainted.promotable


def test_round_trip_charges_four_fills() -> None:
    stack = CostStack(
        venue="bybit",
        components=(
            CostComponent(
                name="fee",
                value=10.0,
                unit="bps_per_fill",
                evidence_class="REAL",
                source="test",
            ),
        ),
    )
    assert stack.round_trip_fraction == pytest.approx(4 * 10.0 / 10_000.0)


def test_cost_multiplier_scales_every_component() -> None:
    stack = conservative_cost_stack("bybit")
    doubled = stack.scaled(2.0)
    assert doubled.round_trip_fraction == pytest.approx(stack.round_trip_fraction * 2)
    assert doubled.annual_carrying_fraction == pytest.approx(stack.annual_carrying_fraction * 2)


def test_stress_multiplier_can_only_add_cost() -> None:
    with pytest.raises(ValueError, match="stress only adds cost"):
        CostStack(venue="bybit", components=(), multiplier=0.5)


def test_negative_costs_are_rejected() -> None:
    with pytest.raises(ValueError, match="finite and >= 0"):
        CostComponent(
            name="rebate",
            value=-1.0,
            unit="bps_per_fill",
            evidence_class="REAL",
            source="test",
        )


def test_cross_venue_stack_adds_a_transfer_cost() -> None:
    single = conservative_cost_stack("bybit")
    cross = conservative_cost_stack("bybit", cross_venue=True)
    names = {c.name for c in cross.components}
    assert "cross_venue_transfer" in names
    assert cross.round_trip_fraction > single.round_trip_fraction


# --- break-even -----------------------------------------------------------------


def test_break_even_is_positive_and_scales_with_cost() -> None:
    stack = conservative_cost_stack("bybit")
    one_x = break_even_funding(stack, holding_days=30.0)
    three_x = break_even_funding(stack, holding_days=30.0, multiplier=3.0)
    assert one_x.required_funding_rate_per_interval > 0
    assert three_x.required_funding_rate_per_interval == pytest.approx(
        one_x.required_funding_rate_per_interval * 3.0
    )


def test_longer_holds_amortise_the_round_trip() -> None:
    stack = conservative_cost_stack("okx")
    short = break_even_funding(stack, holding_days=7.0)
    long = break_even_funding(stack, holding_days=180.0)
    assert long.required_funding_rate_per_interval < short.required_funding_rate_per_interval


def test_break_even_accounts_for_the_settlement_count() -> None:
    stack = conservative_cost_stack("bybit")
    eight_hourly = break_even_funding(stack, holding_days=30.0, funding_interval_hours=8.0)
    four_hourly = break_even_funding(stack, holding_days=30.0, funding_interval_hours=4.0)
    assert four_hourly.settlements_over_holding == pytest.approx(
        eight_hourly.settlements_over_holding * 2
    )
    # Twice as many settlements, so each needs to be half as large.
    assert four_hourly.required_funding_rate_per_interval == pytest.approx(
        eight_hourly.required_funding_rate_per_interval / 2
    )


def test_break_even_rejects_a_zero_holding_period() -> None:
    with pytest.raises(ValueError, match="holding_days must be > 0"):
        break_even_funding(conservative_cost_stack("bybit"), holding_days=0.0)


def test_capital_requirement_includes_a_margin_buffer() -> None:
    capital = capital_requirement(notional_usd=100_000.0, perp_leverage=3.0)
    assert capital["spot_capital_usd"] == 100_000.0
    assert capital["perp_initial_margin_usd"] == pytest.approx(100_000.0 / 3.0)
    assert capital["perp_buffer_usd"] > 0
    assert capital["total_capital_usd"] > capital["spot_capital_usd"]
    assert 0 < capital["capital_efficiency"] < 1


# --- holdout --------------------------------------------------------------------


def _rows(count: int) -> list[dict[str, int]]:
    return [{"start_ms": i, "timestamp_utc": f"t{i:04d}"} for i in range(count)]


def test_selection_cannot_see_the_holdout() -> None:
    guard = HoldoutGuard(_rows(100), holdout_fraction=0.2)
    assert len(guard.selection_rows) == 80
    assert max(r["start_ms"] for r in guard.selection_rows) == 79


def test_holdout_cannot_be_read_before_the_choice_is_frozen() -> None:
    guard = HoldoutGuard(_rows(100), holdout_fraction=0.2)
    with pytest.raises(HoldoutViolation, match="before the variant selection is frozen"):
        guard.reveal(reason="peeking")


def test_holdout_can_only_be_revealed_once() -> None:
    guard = HoldoutGuard(_rows(100), holdout_fraction=0.2)
    guard.freeze_selection("v1")
    assert len(guard.reveal(reason="final scoring")) == 20
    with pytest.raises(HoldoutViolation, match="already been revealed"):
        guard.reveal(reason="just one more look")


def test_freezing_after_revealing_is_a_violation() -> None:
    guard = HoldoutGuard(_rows(100), holdout_fraction=0.2)
    guard.freeze_selection("v1")
    guard.reveal(reason="final scoring")
    with pytest.raises(HoldoutViolation, match="no longer out-of-sample"):
        guard.freeze_selection("v2")


def test_holdout_report_records_the_access() -> None:
    guard = HoldoutGuard(_rows(50), holdout_fraction=0.2)
    guard.freeze_selection("chosen")
    guard.reveal(reason="final scoring", at_step="scoring")
    payload = guard.to_dict()
    assert payload["reveal_count"] == 1
    assert payload["selected"] == "chosen"
    assert payload["accesses"][0]["reason"] == "final scoring"
    assert payload["holdout_position"] == "most_recent"


def test_a_split_that_would_empty_a_side_is_rejected() -> None:
    with pytest.raises(ValueError, match="one side would be empty"):
        HoldoutGuard(_rows(3), holdout_fraction=0.9)  # nothing left to select on
    with pytest.raises(ValueError, match="one side would be empty"):
        HoldoutGuard(_rows(1), holdout_fraction=0.2)  # too few rows to split at all


def test_holdout_fraction_must_be_a_proper_fraction() -> None:
    with pytest.raises(ValueError, match="holdout_fraction must be in"):
        HoldoutGuard(_rows(100), holdout_fraction=0.0)
    with pytest.raises(ValueError, match="holdout_fraction must be in"):
        HoldoutGuard(_rows(100), holdout_fraction=1.0)


def test_chronological_split_reports_boundaries() -> None:
    report = chronological_split(_rows(1000), train_fraction=0.5, walk_forward_fraction=0.3)
    assert report.train_rows == 500
    assert report.walk_forward_rows == 300
    assert report.holdout_rows == 200
    assert report.problems == []
    assert report.train_end_utc < report.walk_forward_end_utc < report.holdout_end_utc


# --- pre-registration -------------------------------------------------------------


def test_freeze_hash_is_stable() -> None:
    assert freeze_hash() == freeze_hash()
    assert len(freeze_hash()) == 64


def test_freeze_hash_changes_when_a_parameter_changes() -> None:
    import dataclasses

    original = preregistration()
    tampered = dataclasses.replace(original, gates={**original.gates, "min_span_days": 30.0})
    assert tampered.freeze_hash != original.freeze_hash


def test_gates_are_the_v7_gates_unchanged() -> None:
    """Any relaxation of these is the failure mode the repo exists to prevent."""
    assert PROMOTION_GATES["min_span_days"] == 730.0
    assert PROMOTION_GATES["min_unique_settlements"] == 1000
    assert PROMOTION_GATES["min_probabilistic_sharpe"] == 0.95
    assert PROMOTION_GATES["min_deflated_sharpe"] == 0.95
    assert PROMOTION_GATES["max_cscv_pbo"] == 0.50
    assert PROMOTION_GATES["min_walk_forward_windows"] == 5
    assert PROMOTION_GATES["require_positive_at_2x_costs"] is True


def test_primary_hypotheses_are_h1_h2_h3() -> None:
    assert [h.hypothesis_id for h in PRIMARY_HYPOTHESES] == ["H1", "H2", "H3"]
    assert all(h.priority == "PRIMARY" for h in PRIMARY_HYPOTHESES)


def test_additional_hypotheses_respect_the_variant_cap() -> None:
    assert [h.hypothesis_id for h in ADDITIONAL_HYPOTHESES] == ["H6", "H7"]
    assert additional_variant_budget() <= MAX_ADDITIONAL_VARIANTS


def test_carry_hypotheses_register_exactly_four_variants_each() -> None:
    for hypothesis_id in ("H1", "H2", "H3"):
        spec = hypothesis(hypothesis_id)
        assert len(spec.variants) == 4
        assert len({v.variant_id for v in spec.variants}) == 4


def test_h2_is_registered_on_the_settled_rate() -> None:
    assert "realizedRate" in hypothesis("H2").signal
    assert "realizedRate" in hypothesis("H2").thesis


def test_h3_must_beat_the_single_venue_carries() -> None:
    spec = hypothesis("H3")
    assert "H1" in spec.benchmarks and "H2" in spec.benchmarks
    assert any("max(H1, H2)" in f for f in spec.falsifiers)
    assert spec.cost_treatment.count("cross_venue=True") == 1


def test_every_hypothesis_declares_falsifiers_and_benchmarks() -> None:
    for spec in preregistration().hypotheses:
        assert spec.falsifiers, spec.hypothesis_id
        assert spec.benchmarks, spec.hypothesis_id
        assert spec.capacity_notes, spec.hypothesis_id


def test_unknown_hypothesis_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown hypothesis"):
        hypothesis("H99")
