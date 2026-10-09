"""Why a stranger can trust Rigor, on the short landing: who is behind it (once the
founder's photo is in), what Rigor does not do, and links to the pages that prove it;
nothing in it promises a result."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

from quant_trade.audit import theme
from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import _COPY, FOUNDER_PHOTO, landing


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
    return page.split("id='quien'", 1)[1].split("</section>", 1)[0]


@pytest.fixture
def photo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / FOUNDER_PHOTO).write_bytes(b"photo")
    monkeypatch.setattr(theme, "STATIC_DIR", tmp_path)


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_founder_block_signs_with_the_operator_and_links_whatsapp(
    locale: str, photo: None
) -> None:
    section = _section(_paid(locale, operator=("Ana Pérez", "México")))
    assert "https://wa.me/000" in section
    text = html.unescape(re.sub(r"<[^>]+>", " ", section))
    assert "Ana Pérez" in text
    assert find_claims(text) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_what_rigor_does_not_do_shows_without_the_founder_block(locale: str) -> None:
    page = _paid(locale, operator=("Ana Pérez", "México"))
    assert "id='quien'" not in page  # the repository ships no founder photo
    faq = page.split("id='faq'", 1)[1].split("</section>", 1)[0]
    assert html.escape(_COPY[locale]["not"], quote=True) in faq


def test_the_whatsapp_link_needs_a_contact(photo: None) -> None:
    section = _section(_paid("es", operator=("Ana Pérez", "México"), contact_url=""))
    assert "wa.me" not in section


def test_the_trust_cards_left_the_landing() -> None:
    # The sample, the privacy policy and the method stay linked from the hero, the
    # prices, the questions and the footer.
    page = _paid("es", operator=("Ana Pérez", "México"))
    assert "id='confianza'" not in page and "trust-who" not in page
    for href in ("/ejemplo?lang=es", "/privacidad"):
        assert f"href='{href}" in page, href


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
