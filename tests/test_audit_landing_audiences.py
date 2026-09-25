"""The landing answers, for each kind of visitor, who it is for, what to upload
and what they get, and says nothing about payment that is not true today."""

from __future__ import annotations

import re

from quant_trade.audit.guard import find_claims
from quant_trade.audit.pages import AUDIENCES, landing


def _paid_landing(locale: str, *, card_payments: bool) -> str:
    return landing(
        locale=locale,
        free_mode=False,
        price_usd=29,
        access_codes=True,
        card_payments=card_payments,
        contact_url="https://wa.me/10000000000",
        pack_price_usd=69,
    )


def test_every_audience_shows_in_both_languages() -> None:
    assert set(AUDIENCES) == {"es", "en"}
    assert len(AUDIENCES["es"]["items"]) == len(AUDIENCES["en"]["items"]) == 4
    for locale in ("es", "en"):
        page = _paid_landing(locale, card_payments=False)
        assert "id='para-quien'" in page
        for _icon, title, *_rest in AUDIENCES[locale]["items"]:
            assert title in page
        assert find_claims(page) == []


def test_audience_texts_pass_the_guard() -> None:
    for words in AUDIENCES.values():
        text = " ".join(" ".join(item[1:5]) for item in words["items"])
        assert find_claims(text) == []
        assert not re.search(r"\bganar|\bearn|\bprofits?\b", text.lower())


def test_landing_names_no_payment_method_it_cannot_show() -> None:
    for locale in ("es", "en"):
        page = _paid_landing(locale, card_payments=False)
        assert "Mercado Pago" not in page
        assert "Pago seguro" not in page and "Secure payment" not in page
    # With cards on, the Stripe line appears.
    assert "Stripe" in _paid_landing("es", card_payments=True)
