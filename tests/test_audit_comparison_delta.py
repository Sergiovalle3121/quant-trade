"""Useful stored-result differences fail closed on missing/mismatched evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from html import unescape
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in
from fastapi.testclient import TestClient

from quant_trade.audit.comparison_delta import (
    COPY,
    REASONS,
    change_summary,
    comparability_diagnostic,
    comparable_window,
)
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import spanish
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.web import create_app


def _result() -> dict[str, Any]:
    return {
        "inputs": {
            "first_timestamp": "2024-01-01T00:00:00Z",
            "last_timestamp": "2024-12-31T00:00:00Z",
            "periods_per_year": {"evidence": "MEASURED", "value": 252.0},
            "frequency_label": "daily",
            "balance_only": False,
        },
        "performance": {
            "sharpe": {"evidence": "MEASURED", "value": 0.5},
            "max_drawdown": {"evidence": "MEASURED", "value": -0.1},
        },
        "verdict": {
            "overall": "D",
            "dimensions": [{"name": "costs", "status": "FAIL"}],
        },
        "red_flags": [{"code": "UNDECLARED_TRIALS"}],
    }


def test_comparison_notes_have_registered_spanish_rules() -> None:
    for key in ("compatible", "incompatible", "context"):
        assert spanish(COPY["en"][key]) == COPY["es"][key]
    for key, english in REASONS["en"].items():
        assert spanish(english) == REASONS["es"][key]


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_summary_counts_evidence_changes_without_claiming_significance(locale: str) -> None:
    a, b = _result(), _result()
    b["verdict"]["overall"] = "C"
    b["verdict"]["dimensions"][0]["status"] = "PASS"
    b["performance"]["sharpe"]["value"] = 0.8
    b["performance"]["max_drawdown"]["value"] = -0.08
    b["red_flags"] = [{"code": "COST_FRAGILE"}]
    original = deepcopy((a, b))
    summary = change_summary(a, b, locale)
    assert COPY[locale]["title"] in summary
    assert "D → C" in summary and "+0.300" in summary and "+2.00 pp" in summary
    assert COPY[locale]["dimensions"].format(n=1) in summary
    assert COPY[locale]["compatible"] in summary
    assert find_claims(summary) == []
    assert (a, b) == original


@pytest.mark.parametrize(
    "field,value",
    [
        ("first_timestamp", "2024-01-02T00:00:00Z"),
        ("last_timestamp", "2024-12-31"),
        ("balance_only", True),
        ("frequency_label", "monthly"),
        ("periods_per_year", {"evidence": "DECLARED", "value": 252}),
        ("periods_per_year", {"evidence": "MEASURED", "value": float("nan")}),
        ("periods_per_year", {"evidence": "MEASURED", "value": True}),
        ("periods_per_year", {"evidence": "MEASURED", "value": 12}),
    ],
)
def test_different_or_missing_context_suppresses_numeric_differences(field, value) -> None:
    a, b = _result(), _result()
    b["inputs"][field] = value
    b["performance"]["sharpe"]["value"] = 1.0
    assert not comparable_window(a, b)
    summary = change_summary(a, b, "en")
    assert COPY["en"]["incompatible"] in summary
    assert "+0.500" not in summary


@pytest.mark.parametrize("evidence,value", [("DECLARED", 1), ("MEASURED", float("inf"))])
def test_unmeasured_or_nonfinite_figures_do_not_get_numeric_delta(evidence, value) -> None:
    a, b = _result(), _result()
    b["performance"]["sharpe"] = {"evidence": evidence, "value": value}
    assert "+0.500" not in change_summary(a, b, "es")


def test_extreme_finite_inputs_do_not_overflow_the_difference() -> None:
    a, b = _result(), _result()
    a["performance"]["sharpe"]["value"] = -1e308
    b["performance"]["sharpe"]["value"] = 1e308
    assert "+inf" not in change_summary(a, b, "en")
    assert REASONS["en"]["difference_invalid"] in change_summary(a, b, "en")


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("first_timestamp", None, "dates_missing"),
        ("first_timestamp", "not-a-date", "dates_invalid"),
        ("first_timestamp", "2024-01-01", "dates_timezone"),
        ("first_timestamp", "2025-01-01T00:00:00Z", "dates_order"),
        ("first_timestamp", "2024-01-01T01:00:00Z", "dates_different"),
        ("periods_per_year", {"evidence": "DECLARED", "value": 252}, "frequency_missing"),
        ("periods_per_year", {"evidence": "MEASURED", "value": 0}, "frequency_invalid"),
        ("periods_per_year", {"evidence": "MEASURED", "value": 10**400}, "frequency_invalid"),
        ("periods_per_year", {"evidence": "MEASURED", "value": 12}, "frequency_different"),
        ("frequency_label", None, "label_missing"),
        ("frequency_label", "monthly", "label_different"),
        ("balance_only", 0, "curve_invalid"),
        ("balance_only", True, "curve_different"),
    ],
)
def test_diagnostic_explains_the_specific_context_failure(field, value, reason) -> None:
    a, b = _result(), _result()
    b["inputs"][field] = value
    original = deepcopy((a, b))
    diagnostic = comparability_diagnostic(a, b)
    assert not diagnostic.window_comparable
    assert reason in {issue.code for issue in diagnostic.issues}
    assert not diagnostic.metric_comparable("sharpe")
    for locale in ("es", "en", "pt"):
        summary = change_summary(a, b, locale)
        assert REASONS[locale][reason] in unescape(summary)
        assert find_claims(summary) == []
    assert (a, b) == original


def test_same_instants_with_different_offsets_remain_comparable() -> None:
    a, b = _result(), _result()
    b["inputs"]["first_timestamp"] = "2023-12-31T18:00:00-06:00"
    b["inputs"]["last_timestamp"] = "2024-12-30T18:00:00-06:00"
    b["performance"]["sharpe"]["value"] = 0.8
    diagnostic = comparability_diagnostic(a, b)
    assert diagnostic.window_comparable and diagnostic.issues == ()
    assert "+0.300" in change_summary(a, b, "es")


def test_frequency_tolerance_is_unchanged() -> None:
    a, b = _result(), _result()
    b["inputs"]["periods_per_year"]["value"] = 252 * (1 + 0.9e-6)
    assert comparable_window(a, b)
    b["inputs"]["periods_per_year"]["value"] = 252 * (1 + 1.1e-6)
    assert not comparable_window(a, b)


def test_missing_frequency_labels_on_both_reports_are_incomplete_evidence() -> None:
    a, b = _result(), _result()
    for result in (a, b):
        del result["inputs"]["frequency_label"]
    diagnostic = comparability_diagnostic(a, b)
    assert not diagnostic.window_comparable
    assert [(issue.code, issue.report) for issue in diagnostic.issues] == [
        ("label_missing", 1),
        ("label_missing", 2),
    ]


@pytest.mark.parametrize("field", ["inputs", "performance"])
@pytest.mark.parametrize("value", ["private-token/path/name", ["private-cell"], True, 1])
def test_truthy_non_mapping_blocks_fail_closed_without_rendering_values(field, value) -> None:
    a, b = _result(), _result()
    b[field] = value
    diagnostic = comparability_diagnostic(a, b)
    assert not diagnostic.metric_comparable("sharpe")
    summary = change_summary(a, b, "en")
    assert "private-" not in summary
    assert "Report 2" in summary and COPY["en"]["why"] in summary
    assert find_claims(summary) == []


@pytest.mark.parametrize(
    "block,reason",
    [
        ({"evidence": "DECLARED", "value": 0.8}, "metric_unmeasured"),
        ({"evidence": "MEASURED", "value": float("nan")}, "metric_invalid"),
        ({"evidence": "MEASURED", "value": float("inf")}, "metric_invalid"),
        ({"evidence": "MEASURED", "value": True}, "metric_invalid"),
        ({"evidence": "MEASURED", "value": "private-token"}, "metric_invalid"),
        ({"evidence": "MEASURED", "value": 10**400}, "metric_invalid"),
    ],
)
def test_metric_failure_explains_only_that_delta_and_preserves_the_other(block, reason) -> None:
    a, b = _result(), _result()
    b["performance"]["sharpe"] = block
    b["performance"]["max_drawdown"]["value"] = -0.08
    diagnostic = comparability_diagnostic(a, b)
    assert diagnostic.window_comparable
    assert not diagnostic.metric_comparable("sharpe")
    assert diagnostic.metric_comparable("max_drawdown")
    summary = change_summary(a, b, "en")
    assert REASONS["en"][reason] in summary
    assert "+2.00 pp" in summary and "private-token" not in summary


def test_diagnostics_do_not_echo_untrusted_context_values() -> None:
    a, b = _result(), _result()
    b["inputs"]["first_timestamp"] = "<script>secret-token</script>"
    b["inputs"]["frequency_label"] = "private-file/client-name"
    b["inputs"]["balance_only"] = {"hidden": "secret-db-url"}
    summary = change_summary(a, b, "en")
    assert all(value not in summary for value in ("secret-token", "private-file", "secret-db-url"))
    assert find_claims(summary) == []


def test_private_comparison_keeps_customer_rights_and_consumes_no_credits(tmp_path) -> None:
    cfg = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
        contact_url="https://wa.me/0",
        email_verification_required=True,
    )
    store = make_store(cfg.database_url)
    app = create_app(cfg, store)
    client = signed_in(TestClient(app), welcome=True)
    account = store.find_account("tester@example.com")
    assert account is not None and not store.email_verified(account.id)
    ids = []
    for size in (200, 210):
        upload = client.post(
            "/audits",
            files={"equity": ("equity.csv", csv_bytes(positive_drift(size)), "text/csv")},
            data={"consent": "on"},
            follow_redirects=False,
        )
        assert upload.status_code == 303
        ids.append(upload.headers["location"].split("?")[0].split("/")[-1])
    query = f"?id={ids[0]}&id={ids[1]}"
    locked = client.get("/cuenta/comparar" + query, follow_redirects=False)
    assert locked.status_code == 303 and "compare_pick" in locked.headers["location"]
    for audit_id in ids:
        store.mark_paid(
            audit_id, stripe_session_id="cs-synthetic-" + audit_id, at=datetime.now(UTC)
        )
    balance = store.account_credits(account.id, datetime.now(UTC))
    for path, locale in (("/cuenta", "es"), ("/account", "en"), ("/pt/conta", "pt")):
        page = client.get(path + "/comparar" + query)
        assert page.status_code == 200 and COPY[locale]["title"] in page.text
        assert find_claims(page.text) == []
        assert "token=" not in page.text
        assert page.headers["Cache-Control"] == "no-store"
        assert page.headers["Referrer-Policy"] == "no-referrer"
        assert "noindex" in page.text
    assert store.account_credits(account.id, datetime.now(UTC)) == balance
    other = signed_in(TestClient(app), email="other@example.com")
    refused = other.get("/account/comparar" + query, follow_redirects=False)
    assert refused.status_code == 303 and "compare_pick" in refused.headers["location"]
    assert COPY["en"]["title"] not in refused.text
