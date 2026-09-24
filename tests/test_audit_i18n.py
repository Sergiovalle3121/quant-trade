"""Spanish for the engine's English sentences, and the English site.

The result JSON keeps the engine's notes in English; a Spanish page
translates them when it renders. These tests run every importer fixture and
a spread of synthetic uploads through ``untranslated`` so a new English
sentence without a Spanish rule fails here, not on a client's page.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from audit_fixtures import (
    benchmark_lower_drift,
    best_of_n_walks,
    csv_bytes,
    positive_drift,
    returns_frame,
    spiked,
    stale_marks,
    synthetic_mt5_optimization,
    synthetic_mt5_report,
    trades_frame,
    variants_bytes,
)

from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import _PLACEHOLDER, _RULES_SOURCE, localize, spanish, untranslated
from quant_trade.audit.report import _summary_in, render_html
from quant_trade.audit.sample import sample_result
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
OPTIMIZATION = FIXTURES / "mt5_optimization.xml"


def _filled(template: str) -> str:
    return _PLACEHOLDER.sub("7", template)


def test_every_rule_translates_its_own_sentence() -> None:
    """No rule is shadowed by an earlier, looser one."""
    for english, expected in _RULES_SOURCE:
        sample = _filled(english)
        translated = spanish(sample)
        assert translated is not None, english
        assert translated == _filled(expected), english
        assert "{" not in translated


def test_spanish_text_passes_the_guard() -> None:
    for english, expected in _RULES_SOURCE:
        assert find_claims(_filled(expected)) == [], expected
        assert find_claims(_filled(english)) == [], english


def test_prefixes_and_fixed_phrases_are_translated() -> None:
    assert (
        localize("report: 3 open trade(s) excluded", "es")
        == "informe: se excluyeron 3 operación(es) abiertas"
    )
    assert localize("report: 3 open trade(s) excluded", "en") == "report: 3 open trade(s) excluded"
    assert localize(
        "report: net profit: the report states 1,000.00 but the rows add up to 990.00", "es"
    ) == ("informe: resultado neto: el informe indica 1,000.00 pero las filas suman 990.00")
    assert localize("PSR against E[max Sharpe] of 4 trial(s), declared by the client", "es") == (
        "PSR frente a E[Sharpe máximo] de 4 intento(s), declarado por el cliente"
    )
    # A sentence no rule knows stays readable, in English.
    assert localize("something new", "es") == "something new"
    assert spanish("something new") is None


def _declared(**values) -> DeclaredMetadata:
    return DeclaredMetadata(locale="es", **values)


def _missing(inputs) -> list[str]:
    result = run_audit(inputs, bootstrap_samples=60)
    return untranslated(result.model_dump(mode="json"))


@pytest.mark.parametrize(
    "name", sorted(p.name for p in FIXTURES.iterdir() if p.suffix != ".xml"), ids=str
)
def test_every_importer_fixture_is_fully_translated(name: str) -> None:
    inputs = build_inputs(
        None,
        _declared(challenge="ftmo-2step-phase1"),
        report_bytes=(FIXTURES / name).read_bytes(),
        report_filename=name,
        optimization_bytes=OPTIMIZATION.read_bytes(),
    )
    assert _missing(inputs) == []


def test_synthetic_uploads_are_fully_translated() -> None:
    equity, matrix = best_of_n_walks(20, 480)
    cases = [
        build_inputs(
            csv_bytes(positive_drift(700)),
            _declared(trials=2, oos_start="2021-01-04"),
            trades_bytes=csv_bytes(trades_frame(40)),
            benchmark_bytes=csv_bytes(benchmark_lower_drift(700)),
        ),
        build_inputs(
            csv_bytes(equity),
            _declared(trials=1, challenge="topstep-50k-combine"),
            variants_bytes=variants_bytes(matrix),
        ),
        build_inputs(csv_bytes(stale_marks()), _declared(oos_start="2030-01-01")),
        build_inputs(csv_bytes(spiked()), _declared(benchmark_applicable=False)),
        build_inputs(csv_bytes(returns_frame(200)), _declared()),
        build_inputs(csv_bytes(positive_drift(8)), _declared()),
        build_inputs(
            None,
            _declared(challenge="the5ers-high-stakes-step1"),
            report_bytes=synthetic_mt5_report(days=120),
            report_filename="ReportTester.html",
            optimization_bytes=synthetic_mt5_optimization(40),
        ),
    ]
    for inputs in cases:
        assert _missing(inputs) == []


def test_the_sample_audit_is_fully_translated() -> None:
    result = sample_result("es", bootstrap_samples=60)
    assert untranslated(result.model_dump(mode="json")) == []


def _visible(html_text: str) -> str:
    return re.sub(r"<[^>]+>", " ", re.sub(r"<(style|svg)\b.*?</\1>", " ", html_text, flags=re.S))


def test_spanish_report_shows_spanish_warnings_and_notes() -> None:
    name = "mt5_tester.html"
    inputs = build_inputs(
        None,
        _declared(),
        report_bytes=(FIXTURES / name).read_bytes(),
        report_filename=name,
    )
    result = run_audit(inputs, bootstrap_samples=60)
    text = _visible(render_html(result, watermark=False))
    assert "Avisos de lectura: informe:" in text
    for english in (
        "the balance curve is built from closed trades only",
        "contract size inferred",
        "signed total the report itemises",
        "declared by the client",
        "report:",
    ):
        assert english not in text
    assert "no muestra el drawdown flotante" in text
    # The stored result keeps the English evidence record.
    assert any("closed trades only" in w for w in result.inputs["parse_warnings"])


def test_a_report_switches_language_without_changing_the_result() -> None:
    spanish_result = sample_result("es", bootstrap_samples=60)
    english_result = sample_result("en", bootstrap_samples=60)
    data = spanish_result.model_dump(mode="json")
    assert _summary_in(data, "es") == spanish_result.verdict.summary
    assert _summary_in(data, "en") == english_result.verdict.summary
    page = render_html(spanish_result, watermark=False, locale="en", switch_url="/x?lang=es")
    assert "<html lang='en'>" in page
    assert english_result.verdict.summary in page.replace("&#x27;", "'")
    assert "href='/x?lang=es'" in page and ">Español</a>" in page
    assert find_claims(page) == []
    default = render_html(spanish_result, watermark=False)
    assert "<html lang='es'>" in default and "class='lang-switch'" not in default
