"""The landing tells a stranger why to trust Rigor, and each point links to
the page where they can check it; nothing in it promises a result."""

from __future__ import annotations

import html
import re

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import TRUST_COPY, landing


def _paid(locale: str, **extra: object) -> str:
    values: dict[str, object] = {
        "locale": locale,
        "free_mode": False,
        "price_usd": 29,
        "access_codes": True,
        "contact_url": "https://wa.me/000",
        "pack_price_usd": 69,
        "retention_days": 30,
    }
    values.update(extra)
    return landing(**values)  # type: ignore[arg-type]


def _section(page: str) -> str:
    return page.split("id='confianza'", 1)[1].split("</section>", 1)[0]


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_every_landing_has_the_trust_section_with_its_proofs(locale: str) -> None:
    section = _section(_paid(locale))
    words = TRUST_COPY[locale]
    for _icon, title, _text, label, target in words["items"]:
        assert html.escape(title, quote=True) in section
        if target:
            assert html.escape(label, quote=True) in section
    text = html.unescape(re.sub(r"<[^>]+>", " ", section))
    assert find_claims(text) == []
    assert "30" in text  # the retention days are the real setting
    assert "https://wa.me/000" in section


def test_trust_links_point_to_pages_that_exist_in_the_page_language() -> None:
    es = _section(_paid("es"))
    for href in ("/ejemplo?lang=es", "/metodologia", "/comprobar", "/privacidad", "/terminos"):
        assert f"href='{href}" in es, href
    # The sample is in Portuguese; pages not translated yet open in English.
    pt = _section(_paid("pt"))
    for href in ("/pt/exemplo", "/methodology", "/check", "/privacy", "/terms"):
        assert f"href='{href}" in pt, href


def test_who_is_behind_shows_only_when_the_operator_is_configured() -> None:
    assert "trust-who" not in _paid("es")
    assert "trust-who" not in _paid("es", operator=("Ana", ""))
    page = _paid("es", operator=("Ana Pérez", "México"))
    assert "Quién está detrás: Ana Pérez, México." in page
    assert "Who is behind it: Ana Pérez, México." in _paid("en", operator=("Ana Pérez", "México"))


def test_the_whatsapp_line_needs_a_contact() -> None:
    assert "trust-ask" not in _paid("es", contact_url="")


def test_platform_figure_counts_readers_and_recognised_exports() -> None:
    """The landing's platform figure counts each named platform once, never the generic CSV."""
    from quant_trade.audit.audiences import RECOGNISED_PLATFORMS
    from quant_trade.audit.pages import PLATFORMS, _specs

    names = {*PLATFORMS, *RECOGNISED_PLATFORMS} - {"CSV"}
    assert len(names) == len(PLATFORMS) - 1 + len(RECOGNISED_PLATFORMS)  # none twice
    total = len(names)
    for locale, label in (
        ("es", "plataformas que reconoce"),
        ("en", "platforms it recognises"),
        ("pt", "plataformas que reconhece"),
    ):
        html = _specs(locale)
        assert f"<b data-count>{total}</b><span>{label}</span>" in html
