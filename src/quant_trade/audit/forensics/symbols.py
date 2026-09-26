"""The closed symbol list of the market-hours check.

Only the 28 pairs of the eight major currencies are examined: their market
closes every weekend on every broker. Metals, indices, crypto, synthetic
indices, energies, stocks and any unknown name are not examined at all.
"""

from __future__ import annotations

import re

MAJORS = ("USD", "EUR", "GBP", "JPY", "CHF", "AUD", "CAD", "NZD")
FOREX_PAIRS: frozenset[str] = frozenset(
    base + quote for base in MAJORS for quote in MAJORS if base != quote
)
_SUFFIXES = frozenset(
    {"m", "micro", "mini", "c", "i", "r", "x", "ecn", "pro", "raw", "std", "plus", "!"}
)
_SUFFIX_MARKS = (".", "-", "_", "#", "+")


def normalise_pair(symbol: str) -> str | None:
    """``EURUSD`` for ``eurusd``, ``EURUSD.pro``, ``EURUSDm``, ``EURUSD (Euro vs US Dollar)``;
    ``None`` for anything not on the closed list (``EURUSDT``, ``XAUUSD``, ``R_75``)."""
    name = symbol.split("(")[0].strip().upper()
    if len(name) < 6:
        return None
    pair, rest = name[:6], name[6:]
    if pair not in FOREX_PAIRS:
        return None
    if rest == "" or rest.startswith(_SUFFIX_MARKS) or rest.lower() in _SUFFIXES:
        return pair
    return None


def quote_currency(pair: str) -> str:
    return pair[3:6]


def base_currency(pair: str) -> str:
    return pair[:3]


_METALS_USD = frozenset({"XAUUSD", "XAGUSD"})


def priced_in(symbol: str, account_currency: str | None) -> bool:
    """Whether one price unit of ``symbol`` is worth a fixed amount of the
    account currency: a listed pair quoted in it, or gold/silver on a USD
    account."""
    if not account_currency:
        return False
    pair = normalise_pair(symbol)
    if pair is not None:
        return quote_currency(pair) == account_currency.upper()
    name = re.sub(r"[^A-Z]", "", symbol.split("(")[0].upper())[:6]
    return name in _METALS_USD and account_currency.upper() == "USD"
