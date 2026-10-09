"""The sign-in gate tells the truth about access codes. Offline."""

from __future__ import annotations

import html

from quant_trade.audit.account_pages import gate_page
from quant_trade.audit.guard import find_claims

#: Before, the page said a code needs no account, while ``create_audit`` asks
#: every upload, code or not, to come from an account ("Account first").
WRONG = {
    "es": "no necesitas cuenta",
    "en": "you need no account",
    "pt": "não precisa de conta",
}
RIGHT = {
    "es": "entra en tu cuenta y escríbelo en el formulario",
    "en": "sign in to your account and type it in the form",
    "pt": "entre na sua conta e digite-o no formulário",
}


def test_the_signin_gate_says_a_code_also_needs_the_account() -> None:
    for locale in ("es", "en", "pt"):
        page = html.unescape(gate_page(locale=locale, reason="signin", limit=3))
        assert WRONG[locale] not in page
        assert RIGHT[locale] in page
        assert find_claims(page) == []
