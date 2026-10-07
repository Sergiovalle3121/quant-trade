"""Version comparisons keep provenance and require complete measured context."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

import pytest

from quant_trade.audit.account_pages import STRATEGY_CSS, strategy_page
from quant_trade.audit.guard import find_claims
from quant_trade.audit.report import evidence_label
from quant_trade.audit.store import AccountAudit, StrategyRecord
from quant_trade.audit.strategies import (
    FREQUENCY_TOLERANCE,
    MIN_SHARED_SPAN,
    figures_text,
    headline,
    headline_evidence,
    sharpe_change,
    what_changed,
)


def _block(value: Any, tag: str = "MEASURED") -> dict[str, Any]:
    return {"evidence": tag, "value": value}


def _result(low: float = 0.02, high: float = 0.06, sharpe: float = 0.5) -> dict[str, Any]:
    return {
        "inputs": {
            "first_timestamp": "2024-01-01T00:00:00Z",
            "last_timestamp": "2024-12-31T00:00:00Z",
            "frequency_label": "daily_calendar",
            "periods_per_year": _block(365.25),
            "balance_only": False,
        },
        "performance": {"sharpe": _block(sharpe), "max_drawdown": _block(-0.1)},
        "multiplicity": {"dsr_at_trials_used": _block(0.8)},
        "bootstrap": {"sharpe_per_period": {"p5": _block(low), "p95": _block(high)}},
        "verdict": {"overall": "C", "dimensions": []},
        "red_flags": [],
    }


def _pair() -> tuple[dict[str, Any], dict[str, Any]]:
    return _result(), _result(0.07, 0.11, 0.9)


def _page(result: dict[str, Any], locale: str, *, paid: bool = True, printable: bool = False):
    item = AccountAudit(
        audit_id="synthetic-audit",
        created_at="2024-01-01T00:00:00Z",
        linked_at="2024-01-01T00:00:00Z",
        overall_class="C",
        paid=paid,
        paid_at="2024-01-01T00:00:00Z" if paid else None,
        paid_with="card" if paid else "",
        purged=False,
        published=False,
        description="",
    )
    strategy = StrategyRecord(
        id="synthetic-strategy",
        name="Synthetic",
        created_at=item.created_at,
        audit_ids=(item.audit_id,),
    )
    return strategy_page(
        locale=locale,
        csrf="synthetic-csrf",
        strategy=strategy,
        versions=[(item, result)],
        printable=printable,
        generated_at="2026-10-06T00:00:00Z",
    )


def _figure_cells(page: str) -> list[str]:
    return re.findall(r"<td class='strat-fig'[^>]*>(.*?)</td>", page, re.DOTALL)


def test_valid_measurements_retain_better_worse_and_overlapping_band_control() -> None:
    before, after = _pair()
    original = deepcopy((before, after))
    assert sharpe_change(before, after) == "better"
    assert sharpe_change(after, before) == "worse"
    assert sharpe_change(before, _result(0.06, 0.1, 0.8)) == "unclear"
    assert headline(after) == {"sharpe": 0.9, "dsr": 0.8, "max_drawdown": -0.1}
    assert figures_text(headline(after)) == ("0.90", "80%", "-10.0%")
    assert (before, after) == original


@pytest.mark.parametrize("scope", ["sharpe", "p5", "p95"])
@pytest.mark.parametrize("tag", ["DECLARED", "UNKNOWN", "NOT_MEASURED"])
def test_unmeasured_metric_or_band_cannot_rank_a_version(scope: str, tag: str) -> None:
    before, after = _pair()
    block = (
        after["performance"]["sharpe"]
        if scope == "sharpe"
        else after["bootstrap"]["sharpe_per_period"][scope]
    )
    block["evidence"] = tag
    original = deepcopy((before, after))
    assert sharpe_change(before, after) == "unclear"
    assert sharpe_change(after, before) == "unclear"
    assert (before, after) == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("first_timestamp", None),
        ("first_timestamp", "private-invalid-timestamp"),
        ("first_timestamp", "2024-01-01"),
        ("last_timestamp", "2024-12-31"),
        ("last_timestamp", "2023-12-31T00:00:00Z"),
        ("balance_only", None),
        ("balance_only", 0),
        ("balance_only", True),
        ("periods_per_year", None),
        ("periods_per_year", _block(365.25, "DECLARED")),
        ("periods_per_year", _block(True)),
        ("periods_per_year", _block(float("inf"))),
        ("periods_per_year", _block(10**400)),
    ],
)
def test_missing_invalid_or_incompatible_context_fails_closed_without_exception(
    field: str, value: Any
) -> None:
    before, after = _pair()
    after["inputs"][field] = value
    original = deepcopy((before, after))
    assert sharpe_change(before, after) == "unclear"
    assert sharpe_change(after, before) == "unclear"
    assert (before, after) == original


@pytest.mark.parametrize("container", ["inputs", "performance", "bootstrap", "multiplicity"])
@pytest.mark.parametrize("value", [None, "private-token", ["private-cell"], True])
def test_malformed_containers_do_not_escape_into_version_table(container: str, value: Any) -> None:
    before, after = _pair()
    after[container] = value
    assert sharpe_change(before, after) == ("better" if container == "multiplicity" else "unclear")
    page = _page(after, "es")
    assert "private-token" not in page and "private-cell" not in page
    assert find_claims(page) == []


@pytest.mark.parametrize("field", ["sharpe", "dsr", "max_drawdown"])
@pytest.mark.parametrize("value", [True, "private-token", float("inf"), float("nan"), 10**400])
def test_invalid_figures_become_not_measured_placeholders(field: str, value: Any) -> None:
    result = _result()
    block = (
        result["multiplicity"]["dsr_at_trials_used"]
        if field == "dsr"
        else result["performance"][field]
    )
    block["value"] = value
    assert headline(result)[field] is None
    assert headline_evidence(result)[field] == (None, "NOT_MEASURED")
    cell = _figure_cells(_page(result, "en"))[("sharpe", "dsr", "max_drawdown").index(field)]
    assert ">—<" in cell and "class='badge NOT_MEASURED'" in cell
    assert "private-token" not in cell and ">nan<" not in cell and ">inf<" not in cell


@pytest.mark.parametrize("field", ["dsr", "max_drawdown"])
def test_finite_but_overflowing_percentage_is_unavailable(field: str) -> None:
    result = _result()
    block = (
        result["multiplicity"]["dsr_at_trials_used"]
        if field == "dsr"
        else result["performance"][field]
    )
    block["value"] = 1e308
    assert headline(result)[field] is None
    assert "inf%" not in _page(result, "en")


@pytest.mark.parametrize("bound", ["p5", "p95"])
@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), 10**400])
def test_invalid_or_reversed_bands_cannot_rank(bound: str, value: Any) -> None:
    before, after = _pair()
    after["bootstrap"]["sharpe_per_period"][bound]["value"] = value
    assert sharpe_change(before, after) == "unclear"
    after["bootstrap"]["sharpe_per_period"] = {"p5": _block(0.12), "p95": _block(0.11)}
    assert sharpe_change(before, after) == "unclear"


def test_timezone_offsets_with_identical_instants_remain_compatible() -> None:
    before, after = _pair()
    after["inputs"].update(
        first_timestamp="2023-12-31T18:00:00-06:00",
        last_timestamp="2024-12-30T18:00:00-06:00",
    )
    assert sharpe_change(before, after) == "better"


def test_existing_eighty_percent_shared_span_threshold_is_preserved() -> None:
    before, after = _pair()
    before["inputs"].update(
        first_timestamp="2024-01-01T00:00:00Z", last_timestamp="2024-01-11T00:00:00Z"
    )
    after["inputs"].update(
        first_timestamp="2024-01-03T00:00:00Z", last_timestamp="2024-01-13T00:00:00Z"
    )
    assert MIN_SHARED_SPAN == 0.8 and sharpe_change(before, after) == "better"
    after["inputs"].update(
        first_timestamp="2024-01-03T00:00:01Z", last_timestamp="2024-01-13T00:00:01Z"
    )
    assert sharpe_change(before, after) == "different_periods"


def test_existing_label_and_ten_percent_frequency_rules_are_preserved() -> None:
    before, after = _pair()
    after["inputs"]["frequency_label"] = "hourly"
    assert sharpe_change(before, after) == "different_frequency"
    for result in (before, after):
        result["inputs"].pop("frequency_label")
    before["inputs"]["periods_per_year"] = _block(252)
    after["inputs"]["periods_per_year"] = _block(280)
    assert FREQUENCY_TOLERANCE == 0.10 and sharpe_change(before, after) == "better"
    after["inputs"]["periods_per_year"] = _block(280.001)
    assert sharpe_change(before, after) == "different_frequency"


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("printable", [False, True])
@pytest.mark.parametrize("tag", ["MEASURED", "DECLARED", "UNKNOWN"])
def test_html_and_printable_version_cells_keep_each_sources_own_evidence(
    locale: str, printable: bool, tag: str
) -> None:
    before, after = _pair()
    for block in (
        after["performance"]["sharpe"],
        after["performance"]["max_drawdown"],
        after["multiplicity"]["dsr_at_trials_used"],
    ):
        block["evidence"] = tag
    original = deepcopy((before, after))
    page = _page(after, locale, printable=printable)
    cells = _figure_cells(page)
    expected = tag if tag in ("MEASURED", "DECLARED") else "NOT_MEASURED"
    assert len(cells) == 3
    for cell in cells:
        assert f"class='badge {expected}'>{evidence_label(expected, locale)}</span>" in cell
        assert cell.count("class='badge ") == 1
    assert (">0.90<" in cells[0]) is (expected != "NOT_MEASURED")
    assert find_claims(page) == [] and (before, after) == original
    if printable:
        assert "<form" not in page
    if tag == "DECLARED":
        line = what_changed(before, after, locale)[-1]
        assert evidence_label("DECLARED", locale) in line[0]
        assert line[1] not in ("better", "mejor", "melhor")


def test_locked_preview_does_not_expose_numbers_or_evidence_badges() -> None:
    page = _page(_result(), "en", paid=False)
    assert not _figure_cells(page)
    assert "class='badge MEASURED'" not in page and ">0.50<" not in page


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_printable_dates_and_figures_keep_print_only_unbroken_layout(locale: str) -> None:
    page = _page(_result(), locale, printable=True)
    assert "<td class='strat-date'>2024-01-01</td>" in page
    cells = _figure_cells(page)
    assert len(cells) == 3
    assert all("<span>" in cell and "class='badge MEASURED'" in cell for cell in cells)
    screen, printed = STRATEGY_CSS.split("@media print{", maxsplit=1)
    for rule in (
        ".strat-table .strat-date{white-space:nowrap;overflow-wrap:normal}",
        ".strat-table .strat-fig>span:first-child{display:block;white-space:nowrap;"
        "overflow-wrap:normal}",
        ".strat-table .strat-fig .badge{margin-top:3pt}",
    ):
        assert rule in printed and rule not in screen


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_phone_figures_line_up_beside_their_label_and_evidence(locale: str) -> None:
    # On a phone each figure is a labelled row: name, evidence badge, then the value
    # against the right edge, so the three values line up whatever the badge says.
    cells = _figure_cells(_page(_result(), locale))
    assert len(cells) == 3
    badge = f"<span class='badge MEASURED'>{evidence_label('MEASURED', locale)}</span>"
    assert all(re.fullmatch(rf"<span>[^<]+</span> {badge}", cell) for cell in cells)
    screen, printed = STRATEGY_CSS.split("@media print{", maxsplit=1)
    phone = screen[screen.index("@media (max-width:620px){") :]
    for rule in (
        ".strat-table .strat-fig{display:grid;grid-template-columns:minmax(0,1fr) auto auto;",
        ".strat-table .strat-fig::before{content:attr(data-label);grid-area:1/1;",
        ".strat-table .strat-fig .badge{grid-area:1/2;margin:0}",
        ".strat-table .strat-fig>span:first-child{grid-area:1/3;text-align:right}",
    ):
        assert rule in phone and rule not in printed, rule
    # Spread across the row, a third child left the value floating in the middle.
    figure = phone[phone.index(".strat-table .strat-fig{") :]
    assert "space-between" not in figure[: figure.index("}")]
