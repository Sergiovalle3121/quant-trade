"""The trial count decides whether multiplicity can pass (verdict.assess_multiplicity), so
the upload form asks for it up front, and the landing mock is a class the rules can give."""

from __future__ import annotations

import html
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import _COPY, upload_page
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.web import create_app

LOCALES = ("es", "en", "pt")


@pytest.mark.parametrize(
    ("paths", "sentence", "free_report"),
    [
        (
            ("/", "/auditar"),
            "A veces pedimos validar una tarjeta; nunca se cobra.",
            "Tu primer informe completo, gratis al crear tu cuenta",
        ),
        (
            ("/en", "/en/audit"),
            "Sometimes we ask to verify a card; it is never charged.",
            "Your first full report, free when you create your account",
        ),
        (
            ("/pt", "/pt/auditar"),
            "Às vezes pedimos validar um cartão; nunca é cobrado.",
            "O seu primeiro relatório completo, grátis ao criar a sua conta",
        ),
    ],
)
def test_landing_and_upload_leave_the_card_to_the_step_that_asks_for_it(
    tmp_path: Path, paths: tuple[str, str], sentence: str, free_report: str
) -> None:
    # A card check is offered only on a report whose free unlock was refused
    # (account_pages.report_box, card_offer); the landing and the upload page do
    # not mention it.
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db")
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    for path in paths:
        response = client.get(path)
        assert response.status_code == 200
        page = html.unescape(response.text)
        assert sentence not in page
        if path == paths[1]:
            beside_drop = page.split("<div class='sticky'>", 1)[1].split(
                "<div class='panel' data-reveal>", 1
            )[0]
            assert free_report in beside_drop
            assert "<div class='drop drop-main'>" in page
        assert find_claims(response.text) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_the_form_asks_for_trials_outside_the_advanced_options(locale: str) -> None:
    page = html.unescape(upload_page(locale=locale, free_mode=False))
    field = page.index("name='trials'")
    assert field < page.index("<details class='adv'>")
    words = _COPY[locale]
    assert words["trials"] in page and words["trials_help"] in page
    assert find_claims(f"{words['trials']} {words['trials_help']}") == []


def test_the_landing_mock_is_a_class_the_rules_can_give() -> None:
    from quant_trade.audit.pages import _MOCK_STATUSES
    from quant_trade.audit.schema import Dimension
    from quant_trade.audit.verdict import Thresholds, overall_class

    dimensions = [
        Dimension(name=name, status=status, reasons=[], inputs={})  # type: ignore[arg-type]
        for name, status in _MOCK_STATUSES
    ]
    assert overall_class(dimensions) == "B"
    # The mock's deflated Sharpe tile must be one that lets multiplicity pass.
    for locale in LOCALES:
        from quant_trade.audit.pages import _UI

        value = float(_UI[locale]["mock_kpis"][0][0].replace(",", "."))
        assert value >= Thresholds().dsr_pass
