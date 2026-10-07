"""File-reading checks reconcile declarations only with valid measured row totals."""

from __future__ import annotations

import copy
import re
from html import unescape
from typing import Any

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.report import (
    LABELS,
    READING_CHECKS,
    _lead_number,
    _reading_html,
    _reading_rows,
    evidence_label,
    localize_text_nodes,
)


def _data() -> dict[str, Any]:
    return {
        "inputs": {
            "report_metadata": {
                "declared_total_trades": "40",
                "declared_total_net_profit": "-10.00",
            }
        },
        "trade_stats": {
            "trade_count": {"value": 40, "evidence": "MEASURED"},
            "net_pnl": {"value": -10.0, "evidence": "MEASURED"},
        },
    }


def test_check_contract_and_valid_negative_result_are_preserved() -> None:
    assert READING_CHECKS == (
        ("declared_total_trades", "trade_count", 0.5, True),
        ("declared_total_net_profit", "net_pnl", 0.011, False),
    )
    data = _data()
    before = copy.deepcopy(data)
    assert _reading_rows(data) == [
        ("trade_count", 40.0, 40.0, True),
        ("net_pnl", -10.0, -10.0, True),
    ]
    assert data == before


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("single", [False, True])
def test_comparisons_show_both_origins_and_scoped_success(locale: str, single: bool) -> None:
    data = _data()
    if single:
        del data["inputs"]["report_metadata"]["declared_total_net_profit"]
    before = copy.deepcopy(data)
    html = localize_text_nodes(_reading_html(data, LABELS[locale]), locale)
    count = 1 if single else 2
    assert html.count("recon-row ok") == count
    for tag in ("DECLARED", "MEASURED"):
        assert html.count(f'class="badge {tag}">{evidence_label(tag, locale)}</span>') == count
    assert LABELS[locale]["reading_all_ok"] in html
    assert LABELS[locale]["reading_scope"] in html
    assert find_claims(unescape(html)) == []
    assert "reading_closing_rows" not in html
    assert LABELS[locale]["reading_closing_rows"] not in html
    assert data == before


@pytest.mark.parametrize("tag", ["DECLARED", "UNKNOWN", "NOT_MEASURED", None, ""])
@pytest.mark.parametrize("key", ["trade_count", "net_pnl"])
def test_unmeasured_figures_never_produce_a_comparison(tag: str | None, key: str) -> None:
    data = _data()
    data["trade_stats"][key]["evidence"] = tag
    assert [row[0] for row in _reading_rows(data)] == [
        name for name in ("trade_count", "net_pnl") if name != key
    ]


@pytest.mark.parametrize(
    "value", [True, False, float("nan"), float("inf"), -float("inf"), 10**400, "40", None]
)
@pytest.mark.parametrize("key", ["trade_count", "net_pnl"])
def test_invalid_measured_values_are_absent_without_failure(value: object, key: str) -> None:
    data = _data()
    data["trade_stats"][key]["value"] = value
    assert key not in [row[0] for row in _reading_rows(data)]


@pytest.mark.parametrize("value", [-1, -0.5, 40.1])
def test_fractional_and_negative_measured_counts_are_absent(value: float) -> None:
    data = _data()
    data["trade_stats"]["trade_count"]["value"] = value
    assert [row[0] for row in _reading_rows(data)] == ["net_pnl"]


@pytest.mark.parametrize(
    "text",
    [
        True,
        float("nan"),
        float("inf"),
        -float("inf"),
        10**400,
        "1e309",
        "-1e309",
        "1E+309",
        "9" * 5000,
    ],
)
def test_nonfinite_or_overflowing_metadata_cannot_fall_back_to_a_prefix(text: object) -> None:
    assert _lead_number(text) is None
    data = _data()
    data["inputs"]["report_metadata"]["declared_total_trades"] = text
    data["trade_stats"]["trade_count"]["value"] = 1
    assert [row[0] for row in _reading_rows(data)] == ["net_pnl"]


@pytest.mark.parametrize("text", ["-1", "40.1", "-0.5"])
def test_declared_counts_must_also_be_nonnegative_whole_figures(text: str) -> None:
    data = _data()
    data["inputs"]["report_metadata"]["declared_total_trades"] = text
    assert [row[0] for row in _reading_rows(data)] == ["net_pnl"]


def test_valid_locale_and_scientific_figures_still_parse() -> None:
    assert _lead_number("1 279,20 (38,80%)") == 1279.20
    assert _lead_number("1e2") == 100.0
    assert _lead_number(0) == 0.0


@pytest.mark.parametrize("block", [None, [], 1, "40", {"value": 40}])
def test_missing_or_malformed_metric_blocks_remain_unavailable(block: object) -> None:
    data = _data()
    data["trade_stats"]["trade_count"] = block
    assert [row[0] for row in _reading_rows(data)] == ["net_pnl"]


@pytest.mark.parametrize("section", ["inputs", "trade_stats"])
@pytest.mark.parametrize("value", [None, [], "invalid", 1])
def test_malformed_containers_and_old_reports_without_metadata_have_no_section(
    section: str, value: object
) -> None:
    data = _data()
    data[section] = value
    assert _reading_html(data, LABELS["es"]) == ""
    assert _reading_rows({"inputs": {}, "trade_stats": _data()["trade_stats"]}) == []


@pytest.mark.parametrize(
    "tag,value",
    [
        ("DECLARED", 40),
        ("UNKNOWN", 40),
        ("MEASURED", True),
        ("MEASURED", -40),
        ("MEASURED", 40.1),
        ("MEASURED", float("inf")),
    ],
)
def test_rounding_tolerance_does_not_use_unavailable_counts(tag: str, value: object) -> None:
    data = _data()
    data["trade_stats"]["trade_count"] = {"value": value, "evidence": tag}
    data["trade_stats"]["net_pnl"]["value"] = -9.98
    assert _reading_rows(data) == [("net_pnl", -10.0, -9.98, False)]
    control = _data()
    control["trade_stats"]["net_pnl"]["value"] = -9.98
    assert _reading_rows(control)[1][3] is True


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_mt5_partial_close_row_count_is_measured_and_explained(locale: str) -> None:
    data = _data()
    data["inputs"]["report_metadata"].update({"declared_total_trades": "61", "closing_deals": "61"})
    data["trade_stats"]["trade_count"]["value"] = 60
    before = copy.deepcopy(data)
    assert _reading_rows(data)[0] == ("trade_count", 61.0, 61.0, True)
    html = localize_text_nodes(_reading_html(data, LABELS[locale]), locale)
    assert unescape(LABELS[locale]["reading_closing_rows"]) in unescape(html)
    assert data == before
    del data["inputs"]["report_metadata"]["closing_deals"]
    assert _reading_rows(data)[0] == ("trade_count", 61.0, 60.0, False)


@pytest.mark.parametrize(
    "tag,value",
    [
        ("DECLARED", 60),
        ("UNKNOWN", 60),
        ("MEASURED", True),
        ("MEASURED", -1),
        ("MEASURED", 60.1),
        ("MEASURED", float("nan")),
    ],
)
def test_closing_metadata_never_overrides_an_invalid_or_unmeasured_count(
    tag: str, value: object
) -> None:
    data = _data()
    data["inputs"]["report_metadata"].update({"declared_total_trades": "61", "closing_deals": "61"})
    data["trade_stats"]["trade_count"] = {"value": value, "evidence": tag}
    assert [row[0] for row in _reading_rows(data)] == ["net_pnl"]


def test_metadata_and_unrelated_private_fields_are_not_rendered() -> None:
    data = _data()
    data["inputs"]["report_metadata"]["private_path"] = "C:/private/customer-secret.csv"
    data["performance"] = {"secret": "private-audit-detail"}
    html = _reading_html(data, LABELS["en"])
    assert "customer-secret" not in html and "private-audit-detail" not in html
    assert len(re.findall(r"class=\"badge (?:MEASURED|DECLARED)\"", html)) == 4
