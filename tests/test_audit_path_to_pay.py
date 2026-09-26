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
    forgot = {"es": "olvido", "en": "forget", "pt": "esquecer"}[locale]
    answers = [answer for question, answer in _COPY[locale]["faq"] if forgot in question]
    assert len(answers) == 1 and words[locale] in answers[0]
    assert not find_claims(answers[0])
    # Two-step sign-in: the reset also asks for the code from the app.
    two_step = {"es": "dos pasos", "en": "two-step", "pt": "duas etapas"}
    assert two_step[locale] in answers[0]
    assert words[locale] in _text(landing(locale=locale, free_mode=False, signed_in=False))


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_cash_card_uses_the_accounts_currency_for_the_sharpe_and_the_alpha(
    locale: str,
) -> None:
    cash = next(text for icon, _, text in _UI[locale]["diffs"] if icon == "percent")
    currency, alpha = {
        "es": ("moneda de tu cuenta", "el alfa también"),
        "en": ("your account's currency", "the alpha too"),
        "pt": ("moeda da sua conta", "o alfa também"),
    }[locale]
    # Since #347 the alpha subtracts the account currency's cash rate too.
    assert currency in cash and alpha in cash
    # Since #352 another named currency without a local rate gets no cash line.
    no_line = {
        "es": "esa línea no se calcula",
        "en": "that line is not computed",
        "pt": "essa linha não é calculada",
    }[locale]
    assert no_line in cash
    assert not find_claims(cash)


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_landing_says_how_an_account_is_protected(locale: str) -> None:
    from quant_trade.audit.pages import _COPY

    two_of_three, sessions = {
        "es": ("dos de estas tres", "cierras cada sesión"),
        "en": ("two of these three", "sign out each session"),
        "pt": ("duas destas três", "encerra cada sessão"),
    }[locale]
    answers = [answer for _, answer in _COPY[locale]["faq"] if two_of_three in answer]
    assert len(answers) == 1 and sessions in answers[0] and "90" in answers[0]
    assert not find_claims(answers[0])
    # Passkeys (#362) and the protection card (#365) are named where Mi cuenta names them.
    passkey, card = {
        "es": ("llave de acceso", "Protección de tu cuenta"),
        "en": ("passkey", "Your account's protection"),
        "pt": ("chave de acesso", "Proteção da sua conta"),
    }[locale]
    assert passkey in answers[0] and card in answers[0]


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_full_report_list_names_the_fund_split(locale: str) -> None:
    words = {
        "es": ("cuánto es efectivo", "cuánto es mercado"),
        "en": ("how much is cash", "how much is the market"),
        "pt": ("quanto é caixa", "quanto é mercado"),
    }[locale]
    items = " ".join(_UI[locale]["full_items"])
    assert all(word in items for word in words)


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_fund_page_names_the_cash_market_and_alpha_split(locale: str) -> None:
    from quant_trade.audit.audiences import AUDIENCE_PAGES

    page = next(p for p in AUDIENCE_PAGES if p.slug == "inversores-gestores-fondos")
    checks = " ".join(f"{title} {text}" for title, text in page.text[locale].checks)
    assert "36" in checks and {"es": "alfa", "en": "alpha", "pt": "alfa"}[locale] in checks
    assert not find_claims(checks)


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_currency_card_says_each_currency_after_its_own_inflation(locale: str) -> None:
    card = next(text for icon, _, text in _UI[locale]["diffs"] if icon == "globe")
    own = {"es": "su propia inflación", "en": "its own inflation", "pt": "sua própria inflação"}
    # Since #346 and #358 each currency is deflated by its own prices, not US ones.
    assert own[locale] in card and "FRED" in card
    assert not find_claims(card)


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_full_report_list_names_the_mean_shift(locale: str) -> None:
    line = {
        "es": "Si su rentabilidad media cambió en algún momento, y cuándo (con 250 "
        "rentabilidades o más)",
        "en": "Whether its average return changed at some point, and when (with 250 "
        "returns or more)",
        "pt": "Se a sua rentabilidade média mudou em algum momento, e quando (com 250 "
        "rentabilidades ou mais)",
    }[locale]
    assert line in _UI[locale]["full_items"]


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_fund_page_says_its_own_index_cannot_make_an_a(locale: str) -> None:
    from quant_trade.audit.audiences import AUDIENCE_PAGES

    page = next(p for p in AUDIENCE_PAGES if p.slug == "inversores-gestores-fondos")
    title = {
        "es": "Frente a su propio índice",
        "en": "Against its own index",
        "pt": "Frente ao seu próprio índice",
    }[locale]
    text = dict(page.text[locale].checks)[title]
    # verdict.overall_class(own_index=True) never lets the file's own index give an A.
    assert "24" in text and {"es": "clase A", "en": "class A", "pt": "classe A"}[locale] in text
    assert not find_claims(f"{title} {text}")


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_landing_says_a_pdf_statement_is_accepted(locale: str) -> None:
    page = html.unescape(landing(locale=locale, free_mode=False, price_usd=29, access_codes=True))
    phrase = {
        "es": "un estado de cuenta en PDF con su tabla de operaciones",
        "en": "a PDF statement with its trade table",
        "pt": "um extrato em PDF com a tabela de operações",
    }[locale]
    # pdf_tables.py reads only a ruled trade table, and the column screen always opens.
    assert phrase in page.replace("\n", " ")
    assert "accept='.htm,.html,.csv,.txt,.tsv,.xlsx,.xls,.ods,.xml,.zip,.pdf'" in page
    assert not find_claims(page)
