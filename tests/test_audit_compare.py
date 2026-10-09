"""Comparing two reports: only the owner's links, only unlocked reports, never in a URL."""

from __future__ import annotations

import re
from copy import deepcopy
from html import escape, unescape
from pathlib import Path
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift, returns_frame, signed_in, trades_frame

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.compare import COPY, comparison_body, parse_report_link  # noqa: E402
from quant_trade.audit.comparison_delta import ACTION_COPY, EVIDENCE_STEPS, REASONS  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.report import LABELS, evidence_label  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

TOKEN = "A" * 43


def _stored_result() -> dict[str, Any]:
    return {
        "inputs": {
            "first_timestamp": "2024-01-01T00:00:00Z",
            "last_timestamp": "2024-12-31T00:00:00Z",
            "frequency_label": "daily",
            "periods_per_year": {"evidence": "MEASURED", "value": 252},
            "balance_only": False,
            "source_format": "csv",
        },
        "performance": {
            "sharpe": {"evidence": "MEASURED", "value": 0.5},
            "max_drawdown": {"evidence": "MEASURED", "value": -0.1},
        },
        "verdict": {"overall": "D", "dimensions": [{"name": "costs", "status": "FAIL"}]},
        "red_flags": [],
    }


def _figure_cells(body: str, label: str) -> list[str]:
    row = re.search(rf"<tr><td>{re.escape(escape(label))}</td>(.*?)</tr>", body, re.DOTALL)
    assert row is not None
    return re.findall(r"<td[^>]*>(.*?)</td>", row.group(1), re.DOTALL)


def _assert_badge(cell: str, tag: str, locale: str) -> None:
    assert f"class='badge {tag}'>{evidence_label(tag, locale)}</span>" in cell
    assert cell.count("class='badge ") == 1


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_equal_figures_show_each_reports_own_evidence_and_missing_is_not_measured(
    locale: str,
) -> None:
    a, b = _stored_result(), _stored_result()
    b["performance"]["sharpe"]["evidence"] = "DECLARED"
    b["performance"]["max_drawdown"] = {"evidence": "MEASURED", "value": None}
    original = deepcopy((a, b))
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale=locale)
    left, right = _figure_cells(body, LABELS[locale]["kpi_sharpe"])
    assert ">0.50<" in left and ">0.50<" in right
    _assert_badge(left, "MEASURED", locale)
    _assert_badge(right, "DECLARED", locale)
    left, right = _figure_cells(body, LABELS[locale]["kpi_drawdown"])
    _assert_badge(left, "MEASURED", locale)
    _assert_badge(right, "NOT_MEASURED", locale)
    assert ">—<" in right and ">0.0%<" not in right
    assert (a, b) == original and find_claims(body) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize(
    "count_tag,rate_tag,expected",
    [
        ("MEASURED", "MEASURED", "MEASURED"),
        ("MEASURED", "DECLARED", "DECLARED"),
        ("DECLARED", "MEASURED", "DECLARED"),
        ("DECLARED", "DECLARED", "DECLARED"),
        ("MEASURED", "NOT_MEASURED", "NOT_MEASURED"),
    ],
)
def test_trade_count_and_win_rate_use_the_lower_evidence_of_both_sources(
    locale: str, count_tag: str, rate_tag: str, expected: str
) -> None:
    a, b = _stored_result(), _stored_result()
    a["trade_stats"] = {
        "trade_count": {"evidence": "MEASURED", "value": 20},
        "win_rate": {"evidence": "MEASURED", "value": 0.5},
    }
    b["trade_stats"] = {
        "trade_count": {"evidence": count_tag, "value": 20},
        "win_rate": {"evidence": rate_tag, "value": 0.5},
    }
    original = deepcopy((a, b))
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale=locale)
    left, right = _figure_cells(body, LABELS[locale]["kpi_trades"])
    _assert_badge(left, "MEASURED", locale)
    _assert_badge(right, expected, locale)
    assert (
        ">—<" in right
        if expected == "NOT_MEASURED"
        else ">20 · 50%<" in left and ">20 · 50%<" in right
    )
    assert (a, b) == original


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("bps,expected", [(5.0, "DECLARED"), (0.0, "MEASURED")])
def test_break_even_evidence_includes_pips_only_when_that_number_is_displayed(
    locale: str, bps: float, expected: str
) -> None:
    a, b = _stored_result(), _stored_result()
    for result in (a, b):
        result["costs"] = {
            "break_even_bps": {"evidence": "MEASURED", "value": bps},
            "break_even_pips": {"evidence": "DECLARED", "value": 1.5},
            "reference_bps": {"evidence": "DECLARED", "value": 2.0},
        }
    label = LABELS[locale]["kpi_breakeven"]
    label += (
        f" ({LABELS[locale]['bps_side']}; 1.5 pips)"
        if bps > 0
        else f" ({LABELS[locale]['kpi_breakeven_negative']})"
    )
    original = deepcopy((a, b))
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale=locale)
    for cell in _figure_cells(body, label):
        _assert_badge(cell, expected, locale)
    assert (a, b) == original


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("tag", ["MEASURED", "DECLARED"])
@pytest.mark.parametrize("closed", [False, True])
def test_all_valid_key_figures_keep_their_source_evidence(
    locale: str, tag: str, closed: bool
) -> None:
    def evidence(value: float) -> dict[str, Any]:
        return {"evidence": tag, "value": value}

    a = _stored_result()
    a["inputs"]["balance_only"] = closed
    a["performance"] = {
        "total_return": evidence(0.05),
        "max_drawdown": evidence(-0.1),
        "platform_equity_drawdown": evidence(-0.2),
        "sharpe": evidence(0.5),
    }
    a["trade_stats"] = {
        "profit_factor": evidence(1.4),
        "trade_count": evidence(20),
        "win_rate": evidence(0.5),
    }
    a["risk"] = {"max_drawdown": {"p95": evidence(0.18)}}
    a["costs"] = {
        "break_even_bps": evidence(5),
        "break_even_pips": evidence(1.5),
        "reference_bps": evidence(2),
    }
    a["stress"] = {
        "trades": {"rows": [{"scenario": "best_5_trades", "result": evidence(10)}]},
        "returns": {"rows": [{"scenario": "best_5_periods", "result": evidence(0.01)}]},
    }
    b = deepcopy(a)
    original = deepcopy((a, b))
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale=locale)
    figures = body.rsplit("<table class='cmp'>", 1)[1].split("</table>", 1)[0]
    cells = re.findall(r"<tr><td>[^<]+</td>(.*?)</tr>", figures, re.DOTALL)
    assert len(cells) == 10
    for row in cells:
        for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL):
            _assert_badge(cell, tag, locale)
    assert (a, b) == original and find_claims(body) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("field", ["inputs", "performance"])
@pytest.mark.parametrize("value", ["private-token/name/path", ["private-cell"], True, 1])
def test_complete_comparison_handles_non_mapping_context_and_performance(
    locale: str, field: str, value: Any
) -> None:
    a, b = _stored_result(), _stored_result()
    b[field] = value
    original = deepcopy((a, b))
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale=locale)
    reason = "context_invalid" if field == "inputs" else "metric_unmeasured"
    assert REASONS[locale][reason] in unescape(body)
    assert "NOT_MEASURED" in body and "private-" not in body
    assert find_claims(body) == []
    assert (a, b) == original


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("value", [10**400, float("inf"), float("nan"), True, "private-token"])
def test_complete_comparison_withholds_invalid_figure_and_keeps_valid_delta(
    locale: str, value: Any
) -> None:
    a, b = _stored_result(), _stored_result()
    b["performance"]["sharpe"]["value"] = value
    b["performance"]["max_drawdown"]["value"] = -0.08
    before = deepcopy(b)
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale=locale)
    assert REASONS[locale]["metric_invalid"] in body
    assert "+2.00 pp" in body and "NOT_MEASURED" in body
    assert ">nan<" not in body and ">inf<" not in body and "private-token" not in body
    assert find_claims(body) == []
    assert b == before


def test_comparison_kpi_copy_ignores_malformed_optional_sections_and_free_form_context() -> None:
    a, b = _stored_result(), _stored_result()
    for section in ("trade_stats", "costs", "risk", "stress"):
        b[section] = "private-secret"
    b["inputs"]["first_timestamp"] = "private-token"
    b["inputs"]["source_format"] = "private-file/name"
    original = deepcopy(b)
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale="en")
    assert REASONS["en"]["dates_invalid"] in unescape(body)
    assert "private-" not in body and "NOT_MEASURED" in body
    assert b == original


def test_comparison_preserves_declared_figure_without_a_measured_delta() -> None:
    a, b = _stored_result(), _stored_result()
    b["performance"]["sharpe"] = {"evidence": "DECLARED", "value": 0.8}
    b["performance"]["max_drawdown"]["value"] = -0.08
    original = deepcopy(b)
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale="en")
    assert ">0.80<" in body and "+0.300" not in body and "+2.00 pp" in body
    assert REASONS["en"]["metric_unmeasured"] in body
    assert b == original


def test_native_csv_format_and_parseable_dates_keep_fixed_card_labels() -> None:
    a, b = _stored_result(), _stored_result()
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale="en")
    assert body.count("File: CSV") == 2
    assert body.count("2024-01-01 → 2024-12-31") == 2


@pytest.mark.parametrize(
    "locale,guides", [("es", "/guias"), ("en", "/guides"), ("pt", "/pt/guias")]
)
def test_comparison_steps_link_existing_export_guides_and_keep_original_results(
    locale: str, guides: str
) -> None:
    a, b = _stored_result(), _stored_result()
    b["inputs"]["first_timestamp"] = "2024-01-02T00:00:00Z"
    b["performance"]["sharpe"]["value"] = 0.8
    original = deepcopy((a, b))
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale=locale)
    assert ACTION_COPY[locale]["title"] in body
    assert EVIDENCE_STEPS[locale]["dates_different"] in body
    assert f"href='{guides}'" in body
    assert ">0.50<" in body and ">0.80<" in body and "+0.300" not in body
    assert (a, b) == original and find_claims(body) == []


def test_finite_but_overflowing_percentage_is_not_rendered_as_infinity() -> None:
    a, b = _stored_result(), _stored_result()
    b["performance"]["max_drawdown"]["value"] = 1e308
    b["performance"]["sharpe"]["value"] = 0.8
    original = deepcopy(b)
    body = comparison_body([a, b], hrefs=["/synthetic-a", "/synthetic-b"], locale="en")
    assert REASONS["en"]["difference_invalid"] in body
    assert "+0.300" in body and "inf%" not in body and "NOT_MEASURED" in body
    assert b == original


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **overrides
    )
    return signed_in(TestClient(create_app(settings, make_store(settings.database_url))))


def _upload(client: TestClient, frame, *, trades: bool = True) -> str:
    files = {"equity": ("equity.csv", csv_bytes(frame), "text/csv")}
    if trades:
        files["trades"] = ("trades.csv", csv_bytes(trades_frame(20)), "text/csv")
    data = {"trials": "3", "cost_bps": "5", "consent": "on"}
    response = client.post("/audits", files=files, data=data, follow_redirects=False)
    assert response.status_code == 303
    return "https://rigor.example" + response.headers["location"]


def test_links_are_read_from_urls_and_paths() -> None:
    assert parse_report_link(f"https://x.app/audits/abc123def?token={TOKEN}&lang=es") == (
        "abc123def",
        TOKEN,
    )
    assert parse_report_link(f"/audits/abc123def?token={TOKEN}") == ("abc123def", TOKEN)
    assert parse_report_link(f"  audits/abc123def?token={TOKEN}  ") == ("abc123def", TOKEN)
    for bad in (
        "",
        "https://x.app/audits/abc123def",
        f"https://x.app/v/abc123def?token={TOKEN}",
        f"https://x.app/audits/abc123def?token={TOKEN}&token={TOKEN}",
        "https://x.app/audits/abc123def?token=short",
        f"https://x.app/audits/a'b<c?token={TOKEN}",
        "https://x.app/audits/" + "a" * 700 + f"?token={TOKEN}",
    ):
        assert parse_report_link(bad) is None, bad


def test_two_reports_side_by_side_in_both_languages(tmp_path: Path) -> None:
    client = _client(tmp_path)
    first = _upload(client, positive_drift(500))
    second = _upload(client, returns_frame(300, mean=0.0, seed=4), trades=False)
    for path, locale in (("/comparar", "es"), ("/compare", "en")):
        page = client.post(path, data={"link_a": first, "link_b": second, "lang": locale})
        assert page.status_code == 200, page.text[:300]
        assert COPY[locale]["dimensions"] in page.text
        assert COPY[locale]["report_b"] in page.text
        assert "noindex" in page.text
        assert find_claims(page.text) == []


def test_form_pages_exist_in_both_languages(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path, locale in (("/comparar", "es"), ("/compare", "en")):
        page = client.get(path)
        assert page.status_code == 200
        assert COPY[locale]["submit"] in page.text
        assert find_claims(page.text) == []


def test_wrong_token_same_report_and_bad_links_are_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    first = _upload(client, positive_drift(500))
    second = _upload(client, positive_drift(400))
    forged = second.split("token=")[0] + "token=" + TOKEN
    refused = client.post("/comparar", data={"link_a": first, "link_b": forged})
    assert refused.status_code == 404
    assert COPY["es"]["not_found"] in refused.text
    same = client.post("/comparar", data={"link_a": first, "link_b": first})
    assert same.status_code == 400
    bad = client.post("/comparar", data={"link_a": first, "link_b": "hola"})
    assert bad.status_code == 400
    assert COPY["es"]["bad_link"] in bad.text


def test_locked_reports_cannot_be_compared(tmp_path: Path) -> None:
    client = _client(tmp_path, free_mode=False, access_codes=True, contact_url="https://wa.me/0")
    first = _upload(client, positive_drift(500))
    second = _upload(client, positive_drift(400))
    page = client.post("/comparar", data={"link_a": first, "link_b": second})
    assert page.status_code == 402
    assert COPY["es"]["locked"] in page.text
    # A locked report offers no compare form either.
    report = client.get(first.replace("https://rigor.example", ""))
    assert "name='link_b'" not in report.text


def test_an_unlocked_report_offers_the_compare_form(tmp_path: Path) -> None:
    client = _client(tmp_path)
    first = _upload(client, positive_drift(500))
    report = client.get(first.replace("https://rigor.example", ""))
    assert "action='/comparar'" in report.text
    assert "name='link_b'" in report.text
