"""The path from the landing to paying, as a visitor on a phone walks it."""

from __future__ import annotations

import html
import re

import pytest

pytest.importorskip("fastapi")

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import _UI, AUDIT_PATHS, landing, upload_page  # noqa: E402
from quant_trade.audit.report import render_html  # noqa: E402
from quant_trade.audit.sample import sample_result  # noqa: E402
from quant_trade.audit.theme import REPORT  # noqa: E402

SIGNUP = {"es": "/registro", "en": "/signup", "pt": "/pt/cadastro"}


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_every_start_button_opens_the_upload_page(locale: str) -> None:
    # The web layer sends a visitor without an account from that page to sign-up.
    for kwargs in (
        {"free_mode": False, "signed_in": False},
        {"free_mode": False, "signed_in": True},
        {"free_mode": True, "signed_in": False},
    ):
        page = landing(locale=locale, access_codes=True, **kwargs)
        assert "#subir'" not in page and "action='/audits'" not in page
        # Hero, prices, the start band, the closing call, the top bar and the phone menu.
        assert page.count(f"href='{AUDIT_PATHS[locale]}'") >= 6


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_landing_sells_what_the_full_report_now_measures(locale: str) -> None:
    # The long feature cards left the landing (too much text); the price card still
    # names what the full report measures, and the language menu offers all three.
    ui = _UI[locale]
    words = {
        "es": ("efectivo", "VIX", "inflación"),
        "en": ("cash", "VIX", "inflation"),
        "pt": ("caixa", "VIX", "inflação"),
    }[locale]
    page = landing(locale=locale, free_mode=False, signed_in=False)
    text = _text(page)
    for word in words:
        assert word in " ".join(ui["full_items"]), word
        assert word in text, word
    assert "class='langs'" in page
    for name in ("Español", "English", "Português"):
        assert name in text
    assert find_claims(text) == []


@pytest.mark.parametrize(
    ("locale", "own_inflation", "available"),
    [
        ("es", "inflación propia", "con datos disponibles"),
        ("en", "its own inflation", "where data is available"),
        ("pt", "inflação própria", "com dados disponíveis"),
    ],
)
def test_landing_names_each_currency_inflation_and_its_data_limit(
    locale: str, own_inflation: str, available: str
) -> None:
    text = _text(landing(locale=locale, free_mode=False, signed_in=False))
    assert own_inflation in text
    assert available in text
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
    assert re.search(r"<a\b[^>]*hreflang='es'[^>]*data-short='ES'>Español</a>", page)
    assert re.search(r"<a\b[^>]*hreflang='en'[^>]*data-short='EN'>English</a>", page)
    assert ".report-languages .lang-switch[data-short]::before{content:attr(data-short)" in REPORT
    spanish = render_html(
        sample_result("es"), watermark=False, locale="es", switch_url="/audits/x?lang=en"
    )
    assert re.search(r"<a\b[^>]*hreflang='en'[^>]*data-short='EN'>English</a>", spanish)
    assert re.search(r"<a\b[^>]*hreflang='pt'[^>]*data-short='PT'>Português</a>", spanish)


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
    options = {"locale": locale, "free_mode": False, "price_usd": 29, "access_codes": True}
    # The landing or the upload page says it; the upload page accepts the file.
    page = html.unescape(landing(**options) + upload_page(**options))
    phrase = {
        "es": "un estado de cuenta en PDF con su tabla de operaciones",
        "en": "a PDF statement with its trade table",
        "pt": "um extrato em PDF com a tabela de operações",
    }[locale]
    # pdf_tables.py reads only a ruled trade table, and the column screen always opens.
    assert phrase in page.replace("\n", " ")
    assert "accept='.htm,.html,.csv,.txt,.tsv,.xlsx,.xls,.ods,.xml,.zip,.pdf'" in page
    assert not find_claims(page)


@pytest.mark.parametrize("locale", sorted(SIGNUP))
def test_the_landing_shows_what_rigor_catches_in_the_sample(locale: str) -> None:
    words = _UI[locale]["example_case"]
    page = html.unescape(landing(locale=locale, free_mode=False))
    texts = [words["eyebrow"], words["title"], words["text"], *words["points"], words["cta"]]
    assert all(text in page for text in texts)
    assert find_claims(" ".join(texts)) == []


def test_the_sample_case_on_the_landing_matches_the_sample_report() -> None:
    # Every figure in the landing's sample case is read here from the sample itself, so
    # the landing cannot drift from what /ejemplo shows.
    from quant_trade.audit.sample import sample_result

    result = sample_result("es").model_dump(mode="json")
    assert result["verdict"]["overall"] == "C"
    assert round(result["performance"]["sharpe"]["value"], 1) == 1.8
    multiplicity = result["multiplicity"]
    assert multiplicity["trials_used"]["value"] == 120
    dsr_pass = result["verdict"]["thresholds"]["dsr_pass"]
    assert multiplicity["dsr_at_trials_used"]["value"] < dsr_pass
    double = next(row for row in result["costs"]["rows"] if row["multiplier"] == 2.0)
    assert double["net_pnl"]["value"] < 0
    assert result["live"]["outcome"] == "INCONSISTENT"
    assert result["live"]["live"]["trades"]["value"] == 180
    for locale in SIGNUP:
        words = _UI[locale]["example_case"]
        text = " ".join(words["points"])
        assert "120" in text and "180" in text and "1,8" in words["title"].replace(".", ",")
        assert words["title"].rstrip(".").endswith(("C en Rigor", "C in Rigor", "C no Rigor"))
