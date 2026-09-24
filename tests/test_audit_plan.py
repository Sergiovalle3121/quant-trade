"""The improvement plan: one step per open dimension, with the result's own figures."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from audit_fixtures import csv_bytes, positive_drift, returns_frame, trades_frame

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.plan import FLAG_HINTS, TITLES, improvement_plan
from quant_trade.audit.redflags import FLAG_TITLES
from quant_trade.audit.report import render_html
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.audit.verdict import DIMENSION_ORDER

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _result(frame, *, trades=None, locale="es", **declared):
    inputs = build_inputs(
        csv_bytes(frame),
        DeclaredMetadata(locale=locale, **declared),
        trades_bytes=csv_bytes(trades) if trades is not None else None,
    )
    return run_audit(inputs, now=NOW, audit_id="plan01", bootstrap_samples=200)


def _data(result):
    return result.model_dump(mode="json")


def test_every_open_dimension_gets_one_step_and_passes_are_left_out() -> None:
    data = _data(_result(positive_drift(600), trials=4, cost_bps_per_side=5))
    statuses = {d["name"]: d["status"] for d in data["verdict"]["dimensions"]}
    open_dims = {n for n, s in statuses.items() if s in ("FAIL", "WEAK", "NOT_MEASURED")}
    for locale in ("es", "en"):
        steps = improvement_plan(data, locale)
        assert {step.dimension for step in steps} == open_dims
        assert all(step.title == TITLES[locale][step.dimension] for step in steps)
        assert all(step.finding for step in steps)


def test_steps_are_ordered_fail_then_weak_then_not_measured() -> None:
    data = _data(_result(returns_frame(200, mean=0.0, seed=3), trades=trades_frame(20)))
    steps = improvement_plan(data, "es")
    ranks = [{"FAIL": 0, "WEAK": 1, "NOT_MEASURED": 2}[s.status] for s in steps]
    unlocking = [s for s in steps if s.class_if_passed]
    # Steps that change the class on their own come first, then by severity.
    assert steps[: len(unlocking)] == unlocking
    rest = ranks[len(unlocking) :]
    assert rest == sorted(rest)


def test_missing_out_of_sample_and_trades_say_the_class_cap() -> None:
    data = _data(_result(positive_drift(600)))
    steps = {s.dimension: s for s in improvement_plan(data, "es")}
    assert "B" in steps["out_of_sample"].finding
    assert "B" in steps["costs"].finding
    english = {s.dimension: s for s in improvement_plan(data, "en")}
    assert "class is B" in english["out_of_sample"].finding


def test_significance_step_counts_the_observations_still_needed() -> None:
    data = _data(_result(returns_frame(120, mean=0.0006, std=0.01, seed=8)))
    sig = data["significance"]
    need = sig["min_track_record_length"]["value"]
    have = sig["observations"]["value"]
    steps = {s.dimension: s for s in improvement_plan(data, "en")}
    if need is None or need <= have or "statistical_significance" not in steps:
        pytest.skip("this sample already reaches the PSR bar")
    step = steps["statistical_significance"]
    assert f"{have} observations" in step.finding
    assert "month" in step.finding or "year" in step.finding or "week" in step.finding


def test_costs_step_quotes_the_break_even_and_the_bar() -> None:
    data = _data(_result(positive_drift(600), trades=trades_frame(20), cost_bps_per_side=300))
    costs = data["costs"]
    steps = {s.dimension: s for s in improvement_plan(data, "en")}
    if "costs" not in steps:
        pytest.skip("costs pass on this sample")
    finding = steps["costs"].finding
    breakeven = costs["break_even_bps"]["value"]
    if breakeven is not None and breakeven > 0:
        assert f"{breakeven:,.2f} bps" in finding
        assert f"{costs['reference_bps']['value'] * 3:,.2f} bps" in finding


def test_class_if_passed_is_the_class_rule_applied_to_one_change() -> None:
    # Too few observations: data quality fails, so the class is D.
    data = _data(_result(positive_drift(40)))
    assert data["verdict"]["overall"] == "D"
    steps = {s.dimension: s for s in improvement_plan(data, "es")}
    for step in steps.values():
        assert step.class_if_passed in (None, "A", "B", "C")
        assert step.class_if_passed != "D"


def test_every_red_flag_has_a_hint_in_both_languages() -> None:
    assert set(FLAG_HINTS) == set(FLAG_TITLES)
    for hints in FLAG_HINTS.values():
        assert hints["es"] and hints["en"]


def test_titles_cover_every_dimension() -> None:
    for locale in ("es", "en"):
        assert set(TITLES[locale]) == set(DIMENSION_ORDER)


def test_every_template_passes_the_guard() -> None:
    texts = [t for titles in TITLES.values() for t in titles.values()]
    texts += [h for hints in FLAG_HINTS.values() for h in hints.values()]
    for frame, trades in (
        (positive_drift(600), None),
        (positive_drift(40), None),
        (returns_frame(200, mean=0.0, seed=3), trades_frame(20)),
    ):
        data = _data(_result(frame, trades=trades))
        for locale in ("es", "en"):
            for step in improvement_plan(data, locale):
                texts += [step.title, step.finding, *step.actions]
    assert find_claims("\n".join(texts)) == []


def test_all_passing_result_has_no_steps() -> None:
    data = _data(_result(positive_drift(600)))
    for dimension in data["verdict"]["dimensions"]:
        dimension["status"] = "PASS"
    assert improvement_plan(data, "es") == []


def test_report_shows_the_plan_and_locks_its_figures_until_paid() -> None:
    result = _result(positive_drift(600), trades=trades_frame(20), cost_bps_per_side=5)
    steps = improvement_plan(_data(result), "es")
    full = render_html(result, watermark=False, free_mode=False)
    assert "Plan para subir de clase" in full
    for step in steps:
        assert step.title in full
    locked = render_html(
        result, watermark=True, free_mode=False, checkout_url="/audits/plan01/checkout"
    )
    assert "Plan para subir de clase" in locked
    for step in steps:
        assert step.title in locked
        assert step.finding not in locked
    english = render_html(result, watermark=False, free_mode=False, locale="en")
    assert "Plan to reach a better class" in english
