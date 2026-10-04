"""The landing's card-payment line names exactly the countries the owner approved
(``AUDIT_APPROVED_MARKETS``), in every language, and nothing when none is approved."""

from __future__ import annotations

from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import card_markets_line, landing


def _card_landing(locale: str, markets: tuple[str, ...]) -> str:
    return landing(
        locale=locale,
        free_mode=False,
        price_usd=29,
        access_codes=False,
        card_payments=True,
        pack_price_usd=69,
        card_markets=markets,
    )


def test_line_names_the_approved_countries_in_a_fixed_order() -> None:
    assert card_markets_line(("US", "MX"), "es") == "Por ahora solo en México y Estados Unidos."
    assert card_markets_line(("MX", "US"), "en") == "For now, in Mexico and the United States only."
    assert (
        card_markets_line(("MX", "US"), "pt") == "Por enquanto, só no México e nos Estados Unidos."
    )
    assert (
        card_markets_line(("ES", "BR", "US", "MX"), "es")
        == "Por ahora solo en México, Estados Unidos, Brasil y España."
    )
    assert (
        card_markets_line(frozenset({"MX", "US", "BR", "ES"}), "en")
        == "For now, in Mexico, the United States, Brazil and Spain only."
    )
    assert (
        card_markets_line(("MX", "US", "BR", "ES"), "pt")
        == "Por enquanto, só no México, nos Estados Unidos, no Brasil e na Espanha."
    )
    assert card_markets_line(("BR",), "pt") == "Por enquanto, só no Brasil."


def test_line_is_empty_without_approved_countries() -> None:
    for locale in ("es", "en", "pt"):
        assert card_markets_line((), locale) == ""


def test_landing_shows_the_approved_countries_and_passes_the_guard() -> None:
    for locale, spain in (("es", "España"), ("en", "Spain"), ("pt", "na Espanha")):
        page = _card_landing(locale, ("MX", "US", "BR", "ES"))
        assert spain in page
        assert find_claims(page) == []
        only_two = _card_landing(locale, ("MX", "US"))
        assert spain not in only_two
