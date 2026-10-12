"""The landing's card-payment line names exactly the countries the owner approved
(``AUDIT_APPROVED_MARKETS``), in every language, and nothing when none is approved."""

from __future__ import annotations

import pytest

from quant_trade.audit.card_markets import (
    CARD_MARKET_WORDS,
    EU_MARKETS,
    MARKET_NAMES,
    REVIEWED_MARKETS,
    spanish_and,
)
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


def test_spanish_joins_ireland_and_italy_with_e() -> None:
    assert card_markets_line(("MX", "IT"), "es") == "Por ahora solo en México e Italia."
    assert card_markets_line(("ES", "IE"), "es") == "Por ahora solo en España e Irlanda."
    assert card_markets_line(("DE", "IT"), "es") == "Por ahora solo en Alemania e Italia."
    assert (
        card_markets_line(("MX", "US", "BR", "ES", "IT"), "es")
        == "Por ahora solo en México, Estados Unidos, Brasil, España e Italia."
    )
    # Only the last joint changes; other countries and languages keep their word.
    assert card_markets_line(("IT", "SE"), "es") == "Por ahora solo en Italia y Suecia."
    assert card_markets_line(("DE", "HU"), "es") == "Por ahora solo en Alemania y Hungría."
    assert card_markets_line(("IE", "GB"), "es") == "Por ahora solo en Irlanda y el Reino Unido."
    assert card_markets_line(("MX", "IT"), "en") == "For now, in Mexico and Italy only."
    assert card_markets_line(("MX", "IT"), "pt") == "Por enquanto, só no México e na Itália."
    assert find_claims(card_markets_line(("ES", "IE"), "es")) == []


@pytest.mark.parametrize(
    ("word", "joiner"),
    [
        ("Irlanda", " e "),
        ("Italia", " e "),
        ("Ítaca", " e "),
        ("Hispania", " e "),
        ("hielo", " y "),
        ("hierro", " y "),
        ("Hungría", " y "),
        ("la Unión Europea", " y "),
        ("el Reino Unido", " y "),
    ],
)
def test_spanish_and_follows_the_sound_of_the_next_word(word: str, joiner: str) -> None:
    assert spanish_and(word) == joiner


def test_czechia_uses_the_brazilian_name_in_portuguese() -> None:
    assert MARKET_NAMES["CZ"]["pt"] == "Tchéquia"
    assert card_markets_line(("CZ",), "pt") == "Por enquanto, só na Tchéquia."


def test_line_is_empty_without_approved_countries() -> None:
    for locale in ("es", "en", "pt"):
        assert card_markets_line((), locale) == ""


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        (
            "es",
            "Por ahora solo en México, Estados Unidos, Brasil, la Unión Europea y el Reino Unido.",
        ),
        (
            "en",
            "For now, in Mexico, the United States, Brazil, "
            "the European Union and the United Kingdom only.",
        ),
        (
            "pt",
            "Por enquanto, só no México, nos Estados Unidos, no Brasil, "
            "na União Europeia e no Reino Unido.",
        ),
    ],
)
def test_complete_eu_is_grouped_before_the_united_kingdom(locale: str, expected: str) -> None:
    line = card_markets_line(REVIEWED_MARKETS, locale)
    assert line == expected
    assert find_claims(line) == []
    page = _card_landing(locale, tuple(REVIEWED_MARKETS))
    assert line in page
    assert "Declarado ·" not in page
    assert find_claims(page) == []


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        (
            "es",
            "Por ahora solo en México, Estados Unidos, Brasil, "
            "Alemania, Francia, Suecia y el Reino Unido.",
        ),
        (
            "en",
            "For now, in Mexico, the United States, Brazil, "
            "France, Germany, Sweden and the United Kingdom only.",
        ),
        (
            "pt",
            "Por enquanto, só no México, nos Estados Unidos, no Brasil, "
            "na Alemanha, na França, na Suécia e no Reino Unido.",
        ),
    ],
)
def test_partial_eu_names_each_country_and_keeps_the_uk_last(locale: str, expected: str) -> None:
    line = card_markets_line(("SE", "GB", "MX", "DE", "FR", "BR", "US"), locale)
    assert line == expected
    assert find_claims(line) == []


@pytest.mark.parametrize(
    ("locale", "eu_only", "uk_only"),
    [
        ("es", "Por ahora solo en la Unión Europea.", "Por ahora solo en el Reino Unido."),
        ("en", "For now, in the European Union only.", "For now, in the United Kingdom only."),
        ("pt", "Por enquanto, só na União Europeia.", "Por enquanto, só no Reino Unido."),
    ],
)
def test_eu_and_uk_can_each_be_the_only_approved_region(
    locale: str, eu_only: str, uk_only: str
) -> None:
    assert card_markets_line(EU_MARKETS, locale) == eu_only
    assert card_markets_line(("GB",), locale) == uk_only
    assert find_claims(eu_only) == find_claims(uk_only) == []


@pytest.mark.parametrize(
    ("locale", "eu_name"),
    [("es", "Unión Europea"), ("en", "European Union"), ("pt", "União Europeia")],
)
def test_even_one_missing_eu_country_prevents_grouping(locale: str, eu_name: str) -> None:
    approved = EU_MARKETS - {"MT"}
    line = card_markets_line(approved, locale)
    assert eu_name not in line
    assert "Malta" not in line
    assert all(CARD_MARKET_WORDS[country][locale] in line for country in approved)
    assert "Declarado ·" not in line
    assert find_claims(line) == []


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        ("es", "Por ahora solo en Grecia, los Países Bajos y el Reino Unido."),
        ("en", "For now, in Greece, the Netherlands and the United Kingdom only."),
        ("pt", "Por enquanto, só na Grécia, nos Países Baixos e no Reino Unido."),
    ],
)
def test_greece_netherlands_and_uk_use_natural_articles(locale: str, expected: str) -> None:
    line = card_markets_line(("NL", "GB", "GR"), locale)
    assert line == expected
    assert find_claims(line) == []


def test_landing_shows_the_approved_countries_and_passes_the_guard() -> None:
    for locale, spain in (("es", "España"), ("en", "Spain"), ("pt", "na Espanha")):
        page = _card_landing(locale, ("MX", "US", "BR", "ES"))
        assert spain in page
        assert find_claims(page) == []
        only_two = _card_landing(locale, ("MX", "US"))
        assert spain not in only_two
