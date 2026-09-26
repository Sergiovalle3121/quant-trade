"""The audit report in Portuguese: every text translated, the result unchanged."""

from __future__ import annotations

import html
import re
from functools import cache
from typing import Any

import pytest

from quant_trade.audit import analytics, charts, plan, redflags, report, report_pt, sizing, verdict
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize, untranslated
from quant_trade.audit.pdf import footer_text
from quant_trade.audit.report import render_html
from quant_trade.audit.sample import sample_result
from quant_trade.audit.schema import AuditResult

PLACEHOLDER = re.compile(r"\{[^{}]*\}")
MODULES = {"REPORT": report, "VERDICT": verdict, "PLAN": plan, "CHARTS": charts}
MODULES["REDFLAGS"] = redflags
#: Words that read the same in Portuguese and English.
SAME_IN_BOTH = {"Jan", "Status"}


def _leaves(node: Any) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [text for value in node.values() for text in _leaves(value)]
    if isinstance(node, list | tuple):
        return [text for value in node for text in _leaves(value)]
    return []


def _installed() -> list[tuple[str, str, Any, Any]]:
    """(table, key, English, Portuguese) for every text the report shows."""
    rows = []
    for name, module in MODULES.items():
        for constant in getattr(report_pt, name):
            table = getattr(module, constant)
            if "en" in table:
                pairs = [(constant, table["en"], table["pt"])]
            else:
                pairs = [
                    (f"{constant}.{key}", item["en"], item["pt"]) for key, item in table.items()
                ]
            for label, english, portuguese in pairs:
                if isinstance(english, dict):
                    rows += [(label, key, english[key], portuguese[key]) for key in english]
                else:
                    rows.append((label, "", english, portuguese))
    return rows


def test_every_english_text_has_its_own_portuguese() -> None:
    """A new English label must bring its Portuguese; the English fallback is a safety net."""
    missing = []
    for name, module in MODULES.items():
        for constant, portuguese in getattr(report_pt, name).items():
            table = getattr(module, constant)
            items = {"": table} if "en" in table else table
            for key, item in items.items():
                wanted = portuguese if "en" in table else portuguese.get(key)
                english = item["en"]
                if wanted is None:
                    missing.append(f"{constant}.{key}")
                elif isinstance(english, dict):
                    missing += [f"{constant}.{k}" for k in english if k not in wanted]
    assert missing == []


def test_placeholders_and_guard_hold_in_portuguese() -> None:
    for label, key, english, portuguese in _installed():
        for en_text, pt_text in zip(_leaves(english), _leaves(portuguese), strict=True):
            assert set(PLACEHOLDER.findall(en_text)) == set(PLACEHOLDER.findall(pt_text)), (
                label,
                key,
            )
            assert find_claims(pt_text) == [], (label, key, pt_text)
    for english, portuguese in report_pt.RULES + report_pt.REASONS:
        assert set(PLACEHOLDER.findall(english)) == set(PLACEHOLDER.findall(portuguese))
        assert find_claims(portuguese) == [], portuguese


def test_stored_questions_and_assumptions_read_in_portuguese() -> None:
    """A result keeps them in Spanish and English only; the report translates the English."""
    for key, texts in analytics._QUESTIONS.items():
        english = texts["en"].format(months=18)
        assert localize(english, "pt") != english, key
        assert ("18" in english) == ("18" in localize(english, "pt"))
    for table in (analytics.RISK_ASSUMPTIONS, analytics.CHALLENGE_ASSUMPTIONS, sizing.ASSUMPTIONS):
        assert "pt" not in table
        for english in table["en"]:
            assert localize(english, "pt") != english, english


def test_engine_notes_and_reasons_read_in_portuguese() -> None:
    assert localize("PSR 1.000 >= 0.95; bootstrap p5 Sharpe > 0", "pt") == (
        "PSR 1.000 >= 0.95; Sharpe p5 do bootstrap > 0"
    )
    reason = "DSR 0.914 between 0.5 and 0.95 with 120 trials counted in the files"
    assert localize(reason, "pt") == (
        "DSR 0.914 entre 0.5 e 0.95 com 120 tentativas contadas nos arquivos"
    )
    title = redflags.FLAG_TITLES["MAD_SPIKES"]
    assert localize(f"{title['en']}; {redflags.FLAG_TITLES['ZERO_VARIANCE']['en']}", "pt") == (
        f"{title['pt']}; {redflags.FLAG_TITLES['ZERO_VARIANCE']['pt']}"
    )
    # One item reads as one, in Portuguese as in English.
    one = localize("1 trade row(s) dropped as unreadable", "pt")
    assert one.startswith("1 ") and "(s)" not in one
    # A sentence no rule knows stays in English rather than going blank.
    assert localize("a sentence nobody wrote a rule for", "pt") == (
        "a sentence nobody wrote a rule for"
    )
    assert verdict.trials_phrase(1, "MEASURED", "pt") == "1 tentativa contada nos arquivos"
    assert verdict.trials_phrase(120, "DECLARED", "pt") == "120 tentativas declaradas"
    assert sizing.scale_text(40.0, "pt") == "mais de 10x"
    assert footer_text("abc", "pt").endswith("relatório abc")


@cache
def _sample() -> AuditResult:
    return sample_result("es", bootstrap_samples=200)


def _text_nodes(page: str) -> set[str]:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    parts = (html.unescape(part).strip() for part in re.split(r"<[^>]+>", page))
    return {part for part in parts if re.search(r"[A-Za-z]{3}", part)}


def test_the_sample_report_reads_in_portuguese() -> None:
    result = _sample()
    data = result.model_dump(mode="json")
    page = render_html(result, watermark=False, locale="pt")
    assert page.startswith("<!doctype html><html lang='pt'>")
    assert find_claims(page) == []
    assert report.LABELS["pt"]["verdict"] in page
    assert "Passa" in page and "Fora da amostra" in page
    assert untranslated(data, "pt") == []
    # No English-only sentence is left: every text the English page shows and the
    # Spanish one does not is gone from the Portuguese page.
    english = _text_nodes(render_html(result, watermark=False, locale="en"))
    spanish = _text_nodes(render_html(result, watermark=False, locale="es"))
    leftovers = (_text_nodes(page) & english) - spanish - SAME_IN_BOTH
    assert leftovers == set()


def test_the_verdict_sentence_gives_its_reasons_in_portuguese() -> None:
    """A bare curve leaves costs, out-of-sample and benchmark unmeasured; the
    headline sentence says why in Portuguese, not in the stored English."""
    from datetime import UTC, datetime

    from audit_fixtures import csv_bytes, positive_drift

    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    inputs = build_inputs(csv_bytes(positive_drift(300)), DeclaredMetadata())
    result = run_audit(
        inputs, now=datetime(2026, 1, 1, tzinfo=UTC), audit_id="pt", bootstrap_samples=100
    )
    english = [
        reason
        for dimension in result.verdict.dimensions
        if dimension.status == "NOT_MEASURED"
        for reason in dimension.reasons
    ]
    assert english
    summary = report._summary_in(result.model_dump(mode="json"), "pt")
    page = render_html(result, watermark=False, locale="pt")
    for reason in english:
        assert reason not in summary and reason not in page, reason
        assert localize(reason, "pt") in summary, reason


def test_a_report_uploaded_in_portuguese_gives_its_reasons_in_portuguese() -> None:
    """Uploaded from /pt, the stored summary holds English reasons (and red-flag
    titles); the Portuguese page and PDF rebuild it instead of showing it."""
    from datetime import UTC, datetime

    from audit_fixtures import csv_bytes, positive_drift

    from quant_trade.audit.engine import run_audit
    from quant_trade.audit.schema import DeclaredMetadata, build_inputs

    inputs = build_inputs(
        csv_bytes(positive_drift(300)), DeclaredMetadata(locale="pt", cost_bps_per_side=0)
    )
    result = run_audit(
        inputs, now=datetime(2026, 1, 1, tzinfo=UTC), audit_id="ptup", bootstrap_samples=100
    )
    assert result.declared["locale"] == "pt"
    english = [
        reason
        for dimension in result.verdict.dimensions
        if dimension.status != "PASS"
        for reason in dimension.reasons
        if localize(reason, "pt") != reason
    ]
    assert english
    page = render_html(result, watermark=False, locale="pt")
    for reason in english:
        assert reason not in page, reason
        assert localize(reason, "pt") in page, reason


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_result_is_the_same_whatever_language_reads_it(locale: str) -> None:
    """Portuguese is added at render time: the stored result carries no "pt" text."""
    data = sample_result(locale, bootstrap_samples=200).model_dump(mode="json")
    assert '"pt"' not in repr(data).replace("'", '"')
    for question in data["vendor_questions"]:
        assert set(question) == {"code", "es", "en"}


def test_the_plan_reads_in_portuguese() -> None:
    steps = plan.improvement_plan(_sample().model_dump(mode="json"), "pt")
    assert steps
    for step in steps:
        texts = [step.title, step.finding, *step.actions]
        assert find_claims(" ".join(texts)) == []
        assert step.title in plan.TITLES["pt"].values()


def _web_client(tmp_path: Any) -> Any:
    pytest.importorskip("fastapi")
    pytest.importorskip("sqlalchemy")
    from audit_fixtures import signed_in
    from fastapi.testclient import TestClient

    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.store import make_store
    from quant_trade.audit.web import create_app

    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100)
    return signed_in(TestClient(create_app(settings, make_store(settings.database_url))))


def test_an_upload_in_portuguese_opens_a_portuguese_report(tmp_path: Any) -> None:
    from audit_fixtures import csv_bytes, positive_drift

    client = _web_client(tmp_path)
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")}
    posted = client.post(
        "/audits", files=files, data={"consent": "on", "locale": "pt"}, follow_redirects=False
    )
    assert posted.status_code == 303
    location = posted.headers["location"]
    page = client.get(location).text
    assert page.startswith("<!doctype html><html lang='pt'>")
    assert report.LABELS["pt"]["verdict"] in page
    assert find_claims(page) == []
    # The same report opens in Spanish and English on request, and back in Portuguese.
    assert "<html lang='es'>" in client.get(f"{location}&lang=es").text
    assert "<html lang='pt'>" in client.get(f"{location}&lang=pt").text
    # A language no report has falls back to the one chosen at upload.
    assert "<html lang='pt'>" in client.get(f"{location}&lang=fr").text


def test_the_sample_report_has_a_portuguese_address(tmp_path: Any) -> None:
    client = _web_client(tmp_path)
    page = client.get("/pt/exemplo")
    assert page.status_code == 200
    assert page.text.startswith("<!doctype html><html lang='pt'>")
    assert "dados sintéticos" in page.text
    assert "href='/pt/exemplo.pdf'" in page.text or "pdf" not in page.text.lower()
    assert find_claims(page.text) == []
    # The Portuguese landing links it, and search engines see all three languages.
    assert "href='/pt/exemplo'" in client.get("/pt").text
    assert "/pt/exemplo" in client.get("/sitemap.xml").text


def test_a_portuguese_report_speaks_of_the_account_in_portuguese(tmp_path: Any) -> None:
    from audit_fixtures import csv_bytes, positive_drift

    client = _web_client(tmp_path)
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")}
    posted = client.post(
        "/audits", files=files, data={"consent": "on", "locale": "pt"}, follow_redirects=False
    )
    page = client.get(posted.headers["location"] + "&acct=saved").text
    assert "<html lang='pt'>" in page
    assert "Relatório salvo na sua conta." in page
    assert "href='/pt/conta'" in page
    assert "Report saved to your account." not in page


def test_portuguese_pages_link_english_where_there_is_no_portuguese(tmp_path: Any) -> None:
    from audit_fixtures import csv_bytes, positive_drift

    client = _web_client(tmp_path)
    sample = client.get("/pt/exemplo").text
    # The terms exist in Spanish and English: a Portuguese reader gets English.
    assert "?lang=en'" in sample and "/terminos?lang=es" not in sample
    assert "hreflang='en'>English</a>" in sample and ">Español</a>" in sample
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")}
    posted = client.post(
        "/audits", files=files, data={"consent": "on", "locale": "pt"}, follow_redirects=False
    )
    location = posted.headers["location"]
    audit_id = location.split("/audits/")[1].split("?")[0]
    query = location.split("?", 1)[1]
    published = client.post(f"/audits/{audit_id}/publish?{query}", follow_redirects=False)
    public = client.get(published.headers["location"]).text
    assert "<html lang='en'>" in public


def test_the_compare_box_speaks_portuguese() -> None:
    page = render_html(_sample(), watermark=False, locale="pt", compare_link="https://x/a")
    assert report.LABELS["pt"]["compare_help"] in html.unescape(page)
    assert "Paste the link" not in page
