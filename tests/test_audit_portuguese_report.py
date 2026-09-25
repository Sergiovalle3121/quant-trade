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
