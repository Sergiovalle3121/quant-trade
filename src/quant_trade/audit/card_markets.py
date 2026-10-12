"""Reviewed billing markets and their ES/EN/PT names for card payments.

Review makes a country eligible for configuration; only ``approved_markets``
opens Checkout there. ISO codes follow Stripe: Greece is GR and the UK is GB.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable

EU_MARKETS = frozenset(
    {
        "AT",
        "BE",
        "BG",
        "HR",
        "CY",
        "CZ",
        "DK",
        "EE",
        "FI",
        "FR",
        "DE",
        "GR",
        "HU",
        "IE",
        "IT",
        "LV",
        "LT",
        "LU",
        "MT",
        "NL",
        "PL",
        "PT",
        "RO",
        "SK",
        "SI",
        "ES",
        "SE",
    }
)
PRIORITY_MARKETS = ("MX", "US", "BR")
REVIEWED_MARKETS = EU_MARKETS | frozenset((*PRIORITY_MARKETS, "GB"))

MARKET_NAMES: dict[str, dict[str, str]] = {
    "MX": {"es": "México", "en": "Mexico", "pt": "México"},
    "US": {"es": "Estados Unidos", "en": "United States", "pt": "Estados Unidos"},
    "BR": {"es": "Brasil", "en": "Brazil", "pt": "Brasil"},
    "AT": {"es": "Austria", "en": "Austria", "pt": "Áustria"},
    "BE": {"es": "Bélgica", "en": "Belgium", "pt": "Bélgica"},
    "BG": {"es": "Bulgaria", "en": "Bulgaria", "pt": "Bulgária"},
    "HR": {"es": "Croacia", "en": "Croatia", "pt": "Croácia"},
    "CY": {"es": "Chipre", "en": "Cyprus", "pt": "Chipre"},
    "CZ": {"es": "Chequia", "en": "Czechia", "pt": "Chéquia"},
    "DK": {"es": "Dinamarca", "en": "Denmark", "pt": "Dinamarca"},
    "EE": {"es": "Estonia", "en": "Estonia", "pt": "Estônia"},
    "FI": {"es": "Finlandia", "en": "Finland", "pt": "Finlândia"},
    "FR": {"es": "Francia", "en": "France", "pt": "França"},
    "DE": {"es": "Alemania", "en": "Germany", "pt": "Alemanha"},
    "GR": {"es": "Grecia", "en": "Greece", "pt": "Grécia"},
    "HU": {"es": "Hungría", "en": "Hungary", "pt": "Hungria"},
    "IE": {"es": "Irlanda", "en": "Ireland", "pt": "Irlanda"},
    "IT": {"es": "Italia", "en": "Italy", "pt": "Itália"},
    "LV": {"es": "Letonia", "en": "Latvia", "pt": "Letônia"},
    "LT": {"es": "Lituania", "en": "Lithuania", "pt": "Lituânia"},
    "LU": {"es": "Luxemburgo", "en": "Luxembourg", "pt": "Luxemburgo"},
    "MT": {"es": "Malta", "en": "Malta", "pt": "Malta"},
    "NL": {"es": "Países Bajos", "en": "Netherlands", "pt": "Países Baixos"},
    "PL": {"es": "Polonia", "en": "Poland", "pt": "Polônia"},
    "PT": {"es": "Portugal", "en": "Portugal", "pt": "Portugal"},
    "RO": {"es": "Rumanía", "en": "Romania", "pt": "Romênia"},
    "SK": {"es": "Eslovaquia", "en": "Slovakia", "pt": "Eslováquia"},
    "SI": {"es": "Eslovenia", "en": "Slovenia", "pt": "Eslovênia"},
    "ES": {"es": "España", "en": "Spain", "pt": "Espanha"},
    "SE": {"es": "Suecia", "en": "Sweden", "pt": "Suécia"},
    "GB": {"es": "Reino Unido", "en": "United Kingdom", "pt": "Reino Unido"},
}

# Portuguese places need their own preposition/article in the shared sentence.
_PT_PREPOSITIONS = {
    "MX": "no",
    "US": "nos",
    "BR": "no",
    "CY": "em",
    "LU": "em",
    "MT": "em",
    "NL": "nos",
    "PT": "em",
    "GB": "no",
}
CARD_MARKET_WORDS: dict[str, dict[str, str]] = {
    country: {
        "es": ("el " if country == "GB" else "los " if country == "NL" else "") + names["es"],
        "en": ("the " if country in {"US", "GB", "NL"} else "") + names["en"],
        "pt": f"{_PT_PREPOSITIONS.get(country, 'na')} {names['pt']}",
    }
    for country, names in MARKET_NAMES.items()
}


def ordered_markets(markets: Iterable[str], locale: str) -> tuple[str, ...]:
    """Reviewed choices: MX/US/BR first, then names ignoring case and accents.

    Unicode normalization avoids process-wide locale state in concurrent pages.
    """
    approved = set(markets) & REVIEWED_MARKETS

    def name_key(country: str) -> str:
        return "".join(
            char
            for char in unicodedata.normalize("NFKD", MARKET_NAMES[country][locale].casefold())
            if not unicodedata.combining(char)
        )

    priority = tuple(country for country in PRIORITY_MARKETS if country in approved)
    return priority + tuple(sorted(approved.difference(priority), key=name_key))
