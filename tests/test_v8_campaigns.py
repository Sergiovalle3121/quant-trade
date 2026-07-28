"""V8 campaigns: sufficiency gating, gate evaluation, holdout, H3 relativity.

One integration fixture builds a 731-day recorded dataset for both venues and
runs all three primary campaigns once; the rest of the suite asserts against
that single run so the expensive path is paid for exactly once.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from v8_venue_fakes import FakeVenue, no_sleep

from quant_trade.v8.backfill import BackfillRequest, run_backfill
from quant_trade.v8.campaigns import (
    STATUS_INSUFFICIENT,
    STATUS_NO_EVIDENCE,
    STATUS_PAPER_CANDIDATE,
    STATUS_REJECTED,
    CampaignResult,
    _evaluate_gates,
    additional_hypotheses_unlocked,
    apply_relative_gates,
    run_all_campaigns,
    run_campaign,
)
from quant_trade.v8.costs import conservative_cost_stack
from quant_trade.v8.panel_builder import build_panel_from_evidence
from quant_trade.v8.preregistration import freeze_hash

HOUR = 3_600_000
START = 1_600_000_000_000 - (1_600_000_000_000 % HOUR)
DAYS = 731
END = START + DAYS * 24 * HOUR
BAR_MINUTES = 240


def _build_evidence(root: Path, source_kind: str, rates: dict[str, float]) -> None:
    for venue, base in rates.items():
        fake = FakeVenue(
            venue=venue,
            start_ms=START,
            end_ms=END,
            interval_minutes=BAR_MINUTES,
            funding_rate_base=base,
        )
        request = BackfillRequest(
            venue=venue,
            symbol="BTC",
            since_ms=START,
            until_ms=END,
            interval_minutes=BAR_MINUTES,
        )
        result = run_backfill(
            request,
            root,
            fetcher=fake.fetch,
            sleeper=no_sleep,
            clock=lambda: 0.0,
            source_kind=source_kind,
            captured_at_utc="2026-07-28T00:00:00Z",
        )
        assert result.status == "OK", result.errors
        built = build_panel_from_evidence(
            result.evidence_dir,
            venue=venue,
            symbol="BTC",
            interval_minutes=BAR_MINUTES,
            since_ms=START,
            until_ms=END,
            provenance="real" if source_kind == "live" else "test_only",
        )
        assert built.status == "OK", built.problems


@pytest.fixture(scope="module")
def executed_campaigns(tmp_path_factory) -> tuple[Path, list[CampaignResult]]:
    """A full sufficient dataset so the campaigns actually execute.

    ``source_kind="live"`` is legitimate here only because the transport is a
    recorded stand-in inside a test; the CLI never lets a caller choose it.
    """
    root = tmp_path_factory.mktemp("v8-campaigns")
    _build_evidence(root, "live", {"bybit": 0.0004, "okx": 0.0002})
    results = run_all_campaigns(
        evidence_root=root, trial_registry_path=root / "trial_registry.jsonl"
    )
    return root, results


# --- not-run paths --------------------------------------------------------------


def test_absent_evidence_is_not_an_economic_verdict(tmp_path: Path) -> None:
    result = run_campaign("H1", evidence_root=tmp_path)
    assert result.status == STATUS_NO_EVIDENCE
    assert not result.ran
    assert any("acquisition failure, not an economic verdict" in r for r in result.blocking_reasons)
    # Break-even is still produced: it needs no price history.
    assert result.break_even["scenarios"]["1x"]["required_funding_rate_per_interval"] > 0


def test_recorded_provenance_cannot_satisfy_the_sufficiency_gate(tmp_path: Path) -> None:
    _build_evidence(tmp_path, "recorded_test_response", {"bybit": 0.0004})
    result = run_campaign("H1", evidence_root=tmp_path)
    assert result.status == STATUS_INSUFFICIENT
    assert not result.ran
    assert any("only receipt-verified live capture" in r for r in result.blocking_reasons)


def test_short_history_reports_the_exact_shortfall(tmp_path: Path) -> None:
    fake = FakeVenue(venue="bybit", start_ms=START, end_ms=START + 30 * 24 * HOUR)
    request = BackfillRequest(
        venue="bybit", symbol="BTC", since_ms=START, until_ms=START + 30 * 24 * HOUR
    )
    backfilled = run_backfill(
        request,
        tmp_path,
        fetcher=fake.fetch,
        sleeper=no_sleep,
        clock=lambda: 0.0,
        source_kind="live",
    )
    build_panel_from_evidence(
        backfilled.evidence_dir,
        venue="bybit",
        symbol="BTC",
        since_ms=START,
        until_ms=START + 30 * 24 * HOUR,
        provenance="real",
    )
    result = run_campaign("H1", evidence_root=tmp_path)
    assert result.status == STATUS_INSUFFICIENT
    assert any("90 unique settlement(s) < required 1000" in r for r in result.blocking_reasons)
    assert any("shortfall" in r for r in result.blocking_reasons)


# --- executed campaigns ----------------------------------------------------------


def test_all_three_primary_campaigns_execute(executed_campaigns) -> None:
    _root, results = executed_campaigns
    assert [r.hypothesis_id for r in results] == ["H1", "H2", "H3"]
    for result in results:
        assert result.ran, (result.hypothesis_id, result.blocking_reasons)
        assert result.preregistration_hash == freeze_hash()


def test_executed_campaigns_report_a_full_cost_decomposition(executed_campaigns) -> None:
    _root, results = executed_campaigns
    economics = results[0].economics
    assert economics["gross_return"] != 0
    assert set(economics["gross_components"]) >= {
        "funding_settled",
        "spot_leg_pnl",
        "perp_leg_pnl",
    }
    assert set(economics["cost_components"]) >= {"trading_fees", "carrying_costs"}
    assert economics["total_costs"] > 0
    assert economics["max_drawdown"] <= 0
    assert economics["reconciled"] is True
    assert "net_return_2x_costs" in economics and "net_return_3x_costs" in economics


def test_higher_cost_scenarios_reduce_the_net_return(executed_campaigns) -> None:
    _root, results = executed_campaigns
    economics = results[0].economics
    assert (
        economics["net_return"]
        > economics["net_return_2x_costs"]
        > economics["net_return_3x_costs"]
    )


def test_statistics_are_computed_not_declared(executed_campaigns) -> None:
    _root, results = executed_campaigns
    statistics = results[0].statistics
    assert statistics["bootstrap"]["available"] is True
    assert statistics["bootstrap"]["method"] == "stationary_block"
    assert "total_return_p05" in statistics["bootstrap"]
    assert 0.0 <= statistics["probabilistic_sharpe"] <= 1.0
    assert 0.0 <= statistics["deflated_sharpe"] <= 1.0
    assert statistics["cscv"]["available"] is True
    assert statistics["cscv"]["method"] == "cscv_rank_based"
    assert statistics["cscv"]["parameter_variants"] == 4
    assert statistics["walk_forward_window_count"] >= 5


def test_holdout_is_revealed_exactly_once_after_the_choice(executed_campaigns) -> None:
    _root, results = executed_campaigns
    for result in results:
        holdout = result.holdout
        assert holdout["selection_frozen"] is True
        assert holdout["reveal_count"] == 1
        assert holdout["holdout_position"] == "most_recent"
        assert holdout["holdout_rows"] > 0
        assert holdout["selected"] in {v["variant_id"] for v in result.variants_evaluated}


def test_every_variant_reaches_the_trial_registry(executed_campaigns) -> None:
    root, results = executed_campaigns
    registry = (root / "trial_registry.jsonl").read_text()
    for result in results:
        for variant in result.variants_evaluated:
            assert variant["variant_id"] in registry


def test_benchmarks_and_capacity_are_present(executed_campaigns) -> None:
    _root, results = executed_campaigns
    for result in results:
        assert result.benchmarks["cash"]["available"] is True
        assert result.benchmarks["buy_and_hold_btc"]["available"] is True
        assert result.capacity["available"] is True
        assert result.capacity["capacity_notional_usd"] > 0


def test_h3_is_measured_against_the_single_venue_carries(executed_campaigns) -> None:
    _root, results = executed_campaigns
    h3 = next(r for r in results if r.hypothesis_id == "H3")
    gate = next(g for g in h3.gate_results if g["gate"] == "beats_best_single_venue_carry")
    assert gate["passed"] is False  # the fixture's H1 carry is richer than the spread
    assert h3.status == STATUS_REJECTED
    assert "switches" in h3.economics


def test_h3_prices_the_cross_venue_transfer(executed_campaigns) -> None:
    _root, results = executed_campaigns
    h3 = next(r for r in results if r.hypothesis_id == "H3")
    names = {c["name"] for c in h3.cost_stack["components"]}
    assert "cross_venue_transfer" in names
    assert h3.economics["cost_components"]["transfer_costs"] >= 0


def test_assumed_cost_evidence_blocks_every_promotion(executed_campaigns) -> None:
    """Even a dataset that clears every economic gate cannot promote while the
    fee schedule is an assumption rather than a capture."""
    _root, results = executed_campaigns
    for result in results:
        assert not result.promoted
        failed = {g["gate"] for g in result.gate_results if not g["passed"]}
        assert "cost_evidence_promotable" in failed


def test_additional_hypotheses_stay_locked_until_the_primaries_run() -> None:
    not_run = [
        CampaignResult(
            hypothesis_id=h, title=h, status=STATUS_NO_EVIDENCE, preregistration_hash="x"
        )
        for h in ("H1", "H2", "H3")
    ]
    unlocked, reason = additional_hypotheses_unlocked(not_run)
    assert not unlocked
    assert "did not run for want of evidence" in reason


def test_additional_hypotheses_unlock_after_measured_rejections(executed_campaigns) -> None:
    _root, results = executed_campaigns
    unlocked, reason = additional_hypotheses_unlocked(results)
    assert unlocked
    assert "executed and were rejected" in reason


def test_additional_hypotheses_stay_locked_if_a_primary_promoted() -> None:
    results = [
        CampaignResult(
            hypothesis_id="H1", title="H1", status=STATUS_PAPER_CANDIDATE, preregistration_hash="x"
        ),
        CampaignResult(
            hypothesis_id="H2", title="H2", status=STATUS_REJECTED, preregistration_hash="x"
        ),
        CampaignResult(
            hypothesis_id="H3", title="H3", status=STATUS_REJECTED, preregistration_hash="x"
        ),
    ]
    unlocked, reason = additional_hypotheses_unlocked(results)
    assert not unlocked
    assert "already produced a candidate" in reason


# --- the gates are not a no-op ----------------------------------------------------


def _passing_result() -> CampaignResult:
    """A campaign whose every observation clears its gate."""
    return CampaignResult(
        hypothesis_id="H1",
        title="t",
        status=STATUS_REJECTED,
        preregistration_hash="x",
        economics={
            "net_return": 0.20,
            "net_return_2x_costs": 0.10,
            "net_return_3x_costs": 0.05,
            "reconciled": True,
            "aborted_entries": 0,
        },
        statistics={
            "bootstrap": {"p05_positive": True, "total_return_p05": 0.05},
            "probabilistic_sharpe": 0.99,
            "deflated_sharpe": 0.97,
            "cscv": {"available": True, "pbo": 0.1, "decision": "PASS"},
            "walk_forward_window_count": 8,
            "walk_forward_positive": 7,
        },
        benchmarks={
            "cash": {"net_return": 0.08},
            "buy_and_hold_btc": {"net_return": 0.05},
        },
        capacity={"available": True, "capacity_notional_usd": 1_000_000.0},
        holdout={"reveal_count": 1, "selection_frozen": True},
    )


def test_a_fully_passing_campaign_promotes() -> None:
    """Without this, 'every campaign was rejected' would be unfalsifiable."""
    gates = _evaluate_gates(
        _passing_result(), conservative_cost_stack("bybit", evidence_class="REAL")
    )
    failed = [g.gate for g in gates if not g.passed]
    assert failed == []


@pytest.mark.parametrize(
    ("field", "key", "value", "expected_gate"),
    [
        ("economics", "net_return", -0.01, "net_return_positive"),
        ("economics", "net_return_2x_costs", -0.01, "net_return_2x_costs_positive"),
        ("economics", "reconciled", False, "ledger_reconciled"),
        ("economics", "aborted_entries", 3, "zero_aborted_entries"),
        ("statistics", "probabilistic_sharpe", 0.5, "probabilistic_sharpe"),
        ("statistics", "deflated_sharpe", 0.5, "deflated_sharpe"),
        ("statistics", "walk_forward_window_count", 2, "walk_forward_windows"),
        ("statistics", "walk_forward_positive", 1, "walk_forward_majority_positive"),
        ("holdout", "reveal_count", 2, "holdout_revealed_once_after_freeze"),
    ],
)
def test_each_gate_fails_when_its_own_condition_fails(
    field: str, key: str, value: object, expected_gate: str
) -> None:
    result = _passing_result()
    getattr(result, field)[key] = value
    gates = _evaluate_gates(result, conservative_cost_stack("bybit", evidence_class="REAL"))
    failed = {g.gate for g in gates if not g.passed}
    assert expected_gate in failed


def test_a_failing_cscv_blocks_promotion() -> None:
    result = _passing_result()
    result.statistics["cscv"] = {"available": True, "pbo": 0.8, "decision": "FAIL"}
    gates = _evaluate_gates(result, conservative_cost_stack("bybit", evidence_class="REAL"))
    assert "cscv_pbo" in {g.gate for g in gates if not g.passed}


def test_losing_to_cash_blocks_promotion() -> None:
    result = _passing_result()
    result.benchmarks["cash"]["net_return"] = 0.9
    gates = _evaluate_gates(result, conservative_cost_stack("bybit", evidence_class="REAL"))
    assert "beats_cash" in {g.gate for g in gates if not g.passed}


def test_relative_gate_can_demote_but_never_promote_h3() -> None:
    h1 = CampaignResult("H1", "t", STATUS_REJECTED, "x", economics={"net_return": 0.30})
    h2 = CampaignResult("H2", "t", STATUS_REJECTED, "x", economics={"net_return": 0.10})
    h3 = CampaignResult("H3", "t", STATUS_PAPER_CANDIDATE, "x", economics={"net_return": 0.20})
    apply_relative_gates([h1, h2, h3])
    assert h3.status == STATUS_REJECTED
    assert any("beats_best_single_venue_carry" in r for r in h3.blocking_reasons)

    better = CampaignResult("H3", "t", STATUS_REJECTED, "x", economics={"net_return": 0.40})
    apply_relative_gates([h1, h2, better])
    # It clears the relative gate but stays REJECTED: the gate cannot promote.
    assert better.status == STATUS_REJECTED
