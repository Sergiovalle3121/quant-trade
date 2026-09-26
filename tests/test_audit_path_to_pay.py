"""The path from the landing to paying, as a visitor on a phone walks it."""

from __future__ import annotations

import html
import re

import pytest

pytest.importorskip("fastapi")

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import _UI, landing  # noqa: E402
from quant_trade.audit.report import render_html  # noqa: E402
from quant_trade.audit.sample import sample_result  # noqa: E402
from quant_trade.audit.theme import REPORT  # noqa: E402

SIGNUP = {"es": "/registro", "en": "/signup", "pt": "/pt/cadastro"}


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_start_free_goes_to_sign_up_when_an_upload_needs_an_account(locale: str) -> None:
    page = landing(locale=locale, free_mode=False, signed_in=False, access_codes=True)
    home = {"es": "/", "en": "/en", "pt": "/pt"}[locale]
    assert "href='#subir'" not in page and f"href='{home}#subir'" not in page
    # Hero, prices, the closing call, the top bar and the phone menu.
    assert page.count(f"href='{SIGNUP[locale]}'") >= 5
    # Signed in, or in free mode, the same buttons still open the form on the page.
    for kwargs in (
        {"free_mode": False, "signed_in": True},
        {"free_mode": True, "signed_in": False},
    ):
        other = landing(locale=locale, access_codes=True, **kwargs)
        assert "href='#subir'" in other and other.count(f"href='{home}#subir'") == 2


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_landing_sells_what_the_full_report_now_measures(locale: str) -> None:
    ui = _UI[locale]
    titles = [title for _, title, _ in ui["diffs"]]
    assert len(titles) == 7
    words = {
        "es": ("efectivo", "VIX", "inflación"),
        "en": ("cash", "VIX", "inflation"),
        "pt": ("caixa", "VIX", "inflação"),
    }[locale]
    text = _text(landing(locale=locale, free_mode=False, signed_in=False))
    for word in words:
        assert word in " ".join(t for _, _, t in ui["diffs"]), word
        assert word in " ".join(ui["full_items"]), word
    assert "FRED" in text and "3" in text
    # The report and its public page exist in three languages, and the chip says so.
    chip = " ".join(t for _, t in ui["trust"])
    assert {"es": "portugués", "en": "Portuguese", "pt": "português"}[locale] in chip
    assert find_claims(text) == []


def test_on_a_phone_the_price_comes_before_the_list_of_locked_sections() -> None:
    # The lockbox is a column on phones: heading, then every paybox except the code
    # form, then the list.
    assert ".lockbox{display:flex;flex-direction:column}" in REPORT
    assert ".lockbox>.paybox:not(.redeem){order:-1" in REPORT
    page = render_html(
        sample_result("pt"),
        watermark=True,
        free_mode=False,
        price_usd=29.0,
        contact_url="https://wa.me/1",
        redeem_url="/audits/x/redeem",
        locale="pt",
        switch_url="/audits/x?lang=es",
    )
    box = page.split("id='unlock'", 1)[1]
    assert "class='paybox buy'" in box
    assert box.index("<ul>") < box.index("class='paybox buy'")  # the order is the CSS's


def test_a_portuguese_report_fits_its_two_language_links_on_a_narrow_phone() -> None:
    page = render_html(
        sample_result("pt"), watermark=False, locale="pt", switch_url="/audits/x?lang=es"
    )
    assert "hreflang='es' data-short='ES'>Español</a>" in page
    assert "hreflang='en' data-short='EN'>English</a>" in page
    assert ".nav-end>.lang-switch[data-short]::before{content:attr(data-short)" in REPORT
    spanish = render_html(
        sample_result("es"), watermark=False, locale="es", switch_url="/audits/x?lang=en"
    )
    assert "data-short=" not in spanish


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_faq_says_a_forgotten_password_needs_no_email(locale: str) -> None:
    from quant_trade.audit.pages import _COPY

    words = {"es": "clave de recuperación", "en": "recovery key", "pt": "chave de recuperação"}
    answers = [answer for _, answer in _COPY[locale]["faq"] if words[locale] in answer]
    assert len(answers) == 1
    assert not find_claims(answers[0])
    # Two-step sign-in: the reset also asks for the code from the app.
    two_step = {"es": "dos pasos", "en": "two-step", "pt": "duas etapas"}
    assert two_step[locale] in answers[0]
    assert words[locale] in _text(landing(locale=locale, free_mode=False, signed_in=False))


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_cash_card_uses_the_accounts_currency_and_keeps_alpha_on_us_bills(
    locale: str,
) -> None:
    cash = next(text for icon, _, text in _UI[locale]["diffs"] if icon == "percent")
    currency, us_bills = {
        "es": ("moneda de tu cuenta", "frente a las letras de EE. UU."),
        "en": ("your account's currency", "against US bills"),
        "pt": ("moeda da sua conta", "frente às letras dos EUA"),
    }[locale]
    assert currency in cash and us_bills in cash
    assert not find_claims(cash)
