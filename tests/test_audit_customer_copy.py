"""Wording a customer audit found wrong: each language reads true and in its own words."""

from __future__ import annotations

import copy
import html
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages  # noqa: E402
from quant_trade.audit import pdf as pdf_lib  # noqa: E402
from quant_trade.audit.audiences import AUDIENCE_PAGES, audience_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import GUIDES, guide_url  # noqa: E402
from quant_trade.audit.legal import LegalContext, privacy_text, terms_text  # noqa: E402
from quant_trade.audit.market import SERIES  # noqa: E402
from quant_trade.audit.pages import SAMPLE_BANNER, landing, upload_page  # noqa: E402
from quant_trade.audit.report import (  # noqa: E402
    LABELS,
    PLATFORM_LABELS,
    _stress_html,
    platform_label,
    platform_value,
)
from quant_trade.audit.sample import sample_result  # noqa: E402
from quant_trade.audit.seo import OG_LOCALE  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

OPERATOR = {
    "operator_name": "Operador de Prueba SAS",
    "operator_contact": "ayuda@operador.example",
    "operator_address": "Calle Falsa 123, Ciudad Ejemplo",
    "jurisdiction": "Tribunales de Ciudad Ejemplo",
}
#: What the Portuguese site said while the report had no Portuguese.
STALE_PT = ("(em inglês)", "vêm em seguida", "relatório sai em inglês", "Por enquanto, em inglês")
BALANCE_FIELDS = (
    "balance_chain_breaks",
    "largest_balance_difference",
    "reconstructed_final_balance",
    "reported_final_balance",
)


def _client(tmp_path: Path, **overrides: object) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        contact_url="https://wa.me/000",
        **overrides,  # type: ignore[arg-type]
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _text(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _paid(locale: str) -> str:
    return landing(
        locale=locale,
        free_mode=False,
        price_usd=29,
        access_codes=True,
        contact_url="https://wa.me/000",
        pack_price_usd=69,
        signed_in=False,
    )


def _legal_words(locale: str, ctx: LegalContext) -> str:
    words = []
    for text in (terms_text(ctx, locale), privacy_text(ctx, locale)):
        for title, paragraphs in text.sections:
            words += [title, *paragraphs]
    return " ".join(words)


def test_the_portuguese_site_says_the_report_comes_in_portuguese(tmp_path: Path) -> None:
    client = _client(tmp_path)
    paths = ["/pt", "/pt/guias"]
    paths += [audience_url(page.slug, "pt") for page in AUDIENCE_PAGES]
    paths += [guide_url(guide.slug, "pt") for guide in GUIDES]
    pages = {path: client.get(path).text for path in paths}
    pages["upload"] = upload_page(locale="pt", free_mode=False, price_usd=29, access_codes=True)
    for path, page in pages.items():
        text = _text(page)
        for stale in STALE_PT:
            assert stale not in text, (path, stale)
    landing_text = _text(pages["/pt"])
    assert "Em português, espanhol ou inglês, à sua escolha no formulário." in landing_text
    assert "Leia antes de enviar:" in _text(pages["upload"])
    # The two pages to read before sending are the Portuguese ones.
    assert "href='/pt/termos?lang=pt'" in pages["upload"]
    assert "href='/pt/privacidade?lang=pt'" in pages["upload"]
    # The guide names the section as the Portuguese report titles it.
    assert LABELS["pt"]["account"] == "O dinheiro real da conta"
    guide = _text(pages["/pt/guias/conta-de-fornecedor"])
    assert "'O dinheiro real da conta'" in guide and "The account's real money" not in guide


def test_spanish_reads_as_latin_american_spanish() -> None:
    ctx = LegalContext(**OPERATOR, free_mode=False, price_usd=29, access_codes=True)
    texts = {
        "landing": _text(_paid("es")),
        "banner": SAMPLE_BANNER["es"],
        "legal": _legal_words("es", ctx),
        "report": " ".join(LABELS["es"].values()),
    }
    for name, text in texts.items():
        for word in ("Comprobáis", "ordenador", "vídeo", "Inflación y tipos"):
            assert word not in text, (name, word)
        # No "vosotros" verb form anywhere.
        assert re.findall(r"\b\w+(?:áis|éis)\b", text) == [], name
    assert "¿Comprueban mis operaciones con el bróker?" in texts["landing"]
    assert "generados por computadora" in texts["banner"]
    assert LABELS["es"]["fund_stress_rates_2022"] == "Inflación y tasas, 2022"
    assert OG_LOCALE == {"es": "es_MX", "en": "en_US", "pt": "pt_BR"}
    assert "Paquete de 3 informes: USD 69 (USD 23 cada uno)." in texts["landing"]


def test_the_spanish_report_uses_one_word_for_each_thing() -> None:
    words = " ".join(LABELS["es"].values())
    assert "período" not in words.lower() and "tómelos" not in words
    assert "tómalos solo como contexto" in LABELS["es"]["crises_market_note"]
    assert LABELS["es"]["kpi_pf"] == "Factor de beneficio"
    assert platform_label("declared_profit_factor", "es") == "Factor de beneficio"
    assert LABELS["pt"]["kpi_pf"] == platform_label("declared_profit_factor", "pt")
    assert LABELS["pt"]["kpi_pf"] == "Fator de lucro"


@pytest.mark.parametrize(
    ("locale", "one", "many"),
    [
        ("es", "de 8 escenarios queda en cero", "de 8 escenarios quedan en cero"),
        ("en", "of 8 scenarios ends at zero", "of 8 scenarios end at zero"),
        ("pt", "de 8 cenários termina em zero", "de 8 cenários terminam em zero"),
    ],
)
def test_the_stress_count_agrees_in_number(locale: str, one: str, many: str) -> None:
    stress = sample_result("es", bootstrap_samples=60).model_dump(mode="json")["stress"]
    total = sum(len(part["rows"]) for part in stress.values() if part.get("status") == "MEASURED")
    assert total == 8

    def block(broken: int) -> dict[str, object]:
        changed = copy.deepcopy(stress)
        rows = [
            row
            for part in changed.values()
            if part.get("status") == "MEASURED"
            for row in part["rows"]
        ]
        for i, row in enumerate(rows):
            row["stays_positive"] = i >= broken
        return changed

    def count_line(broken: int) -> str:
        page = _stress_html(block(broken), locale, LABELS[locale])
        return html.unescape(page.split("</p>")[1])

    assert f"<strong>1</strong> {one}" in count_line(1)
    for broken in (0, 2, 8):
        assert f"<strong>{broken}</strong> {many}" in count_line(broken)
    assert find_claims(count_line(1)) == []


def test_the_landing_writes_numbers_as_the_report_does() -> None:
    for locale in ("es", "en", "pt"):
        text = _text(_paid(locale))
        assert "0.97" in text and "1.8" in text, locale
        for comma in ("0,97", "3,2 pb", "1,8"):
            assert comma not in text, (locale, comma)
    assert "3.2 pb" in _text(_paid("es")) and "3.2 pb" in _text(_paid("pt"))


def test_platform_balance_fields_have_a_name_in_three_languages() -> None:
    for locale in ("es", "en", "pt"):
        for key in BALANCE_FIELDS:
            assert key in PLATFORM_LABELS[locale], (locale, key)
            assert find_claims(platform_label(key, locale)) == []
    for locale in ("es", "pt"):
        shown = {platform_label(key, locale) for key in BALANCE_FIELDS}
        english = {platform_label(key, "en") for key in BALANCE_FIELDS}
        assert shown.isdisjoint(english), locale
    assert platform_label("reconstructed_final_balance", "es") == "Balance final reconstruido"
    assert platform_label("balance_chain_breaks", "en") == "Balance cells that do not match"


def test_platform_balance_values_are_rounded_for_display_only() -> None:
    assert platform_value("reconstructed_final_balance", "27369.750000") == "27,369.75"
    assert platform_value("reported_final_balance", "27369.750000") == "27,369.75"
    assert platform_value("largest_balance_difference", "0.000000") == "0.00"
    assert platform_value("largest_balance_difference", "-12.5") == "-12.50"
    assert platform_value("balance_chain_breaks", "3") == "3"
    assert platform_value("balance_chain_breaks", "3.0") == "3"
    # Anything that is not a plain number, and every other field, is shown as stored.
    assert platform_value("reported_final_balance", "n/a") == "n/a"
    assert platform_value("reported_final_balance", "nan") == "nan"
    assert platform_value("declared_balance", "27369.750000") == "27369.750000"
    assert platform_value("symbol", "EURUSD") == "EURUSD"


def test_the_brazilian_series_link_their_own_public_page() -> None:
    pages = {asset.series: asset.source_url for asset in SERIES.values() if "bcb" in asset.provider}
    assert pages["433"] == (
        "https://www3.bcb.gov.br/sgspub/consultarvalores/consultarValoresSeries.do"
        "?method=consultarGraficoPorId&hdOidSeriesSelecionadas=433"
    )
    assert pages["4189"].startswith("https://dadosabertos.bcb.gov.br/dataset/4189-taxa-de-juros")
    assert all(
        asset.publisher == "Banco Central do Brasil"
        for asset in SERIES.values()
        if ("bcb" in asset.provider)
    )


@pytest.mark.parametrize(
    ("locale", "words"),
    [
        ("es", "Escribir a ayuda@operador.example"),
        ("en", "Write to ayuda@operador.example"),
        ("pt", "Escrever para ayuda@operador.example"),
    ],
)
def test_forgot_page_offers_the_operator_mail_before_the_chat(locale: str, words: str) -> None:
    page = account_pages.forgot_page(
        locale=locale,
        contact_url="https://wa.me/000",
        csrf="c",
        contact_email="ayuda@operador.example",
    )
    assert "href='mailto:ayuda@operador.example'" in page and words in _text(page)
    assert page.index("mailto:ayuda@operador.example") < page.index("https://wa.me/000")
    assert find_claims(_text(page)) == []
    # With no address configured, or one that is not an address, nothing is shown.
    for missing in ("", "not an address", "https://example.test"):
        bare = account_pages.forgot_page(
            locale=locale, contact_url="https://wa.me/000", csrf="c", contact_email=missing
        )
        assert "mailto:" not in bare and "wa.me/000" in bare
    # Once the automatic link works, neither detour is offered.
    on = account_pages.forgot_page(
        locale=locale,
        contact_url="https://wa.me/000",
        csrf="c",
        contact_email="ayuda@operador.example",
        email_delivery_ready=True,
    )
    assert "mailto:" not in on and "wa.me" not in on


def test_forgot_page_escapes_the_configured_address() -> None:
    page = account_pages.forgot_page(
        locale="es", contact_url="", csrf="c", contact_email="a'><b>@operador.example"
    )
    assert "<b>@operador" not in page and "a&#x27;&gt;&lt;b&gt;@operador.example" in page


@pytest.mark.parametrize("path", ["/olvide", "/forgot", "/pt/esqueci"])
def test_forgot_routes_show_the_configured_operator_mail(tmp_path: Path, path: str) -> None:
    client = _client(tmp_path, **OPERATOR)
    page = client.get(path).text
    assert "href='mailto:ayuda@operador.example'" in page
    assert "mailto:" not in _client(tmp_path / "bare").get(path).text


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_terms_describe_password_recovery_as_the_site_does_it(locale: str) -> None:
    key = {"es": "clave de recuperación", "en": "recovery key", "pt": "chave de recuperação"}
    write = {"es": "escríbenos", "en": "write to us", "pt": "escreva para nós"}
    confirmed = {
        "es": "solo a un correo confirmado",
        "en": "only to a confirmed e-mail address",
        "pt": "apenas a um e-mail confirmado",
    }
    off = _legal_words(locale, LegalContext(**OPERATOR))
    assert key[locale] in off and write[locale] in off
    on = _legal_words(locale, LegalContext(**OPERATOR, email_delivery_ready=True))
    assert key[locale] in on and confirmed[locale] in on and write[locale] not in on
    assert find_claims(off) == [] and find_claims(on) == []


def test_small_wording_fixes_in_english_and_portuguese() -> None:
    ctx = LegalContext(**OPERATOR, free_mode=False, price_usd=29, access_codes=True)
    english = _legal_words("en", ctx)
    assert "gets a free full report: once per account, browser and file, and only a few" in english
    assert "browser and file, and a few per network address each month" not in english
    portuguese = _legal_words("pt", ctx)
    for feminine in ("A cookie", "a cookie", "As cookies", "Nenhuma acompanha", "mblema"):
        assert feminine not in portuguese, feminine
    assert "Os cookies são nossos" in portuguese and "Selo e página de verificação" in portuguese
    pages = {page.slug: page for page in AUDIENCE_PAGES}
    words = {
        locale: repr([page.text[locale] for page in pages.values()]) for locale in ("en", "pt")
    }
    assert "the daily or the total loss limit would be hit" in words["en"]
    assert "the daily loss, the total loss would be hit" not in words["en"]
    assert "tabela da lâmina" in words["pt"] and "tabela da ficha" not in words["pt"]
    assert find_claims(english) == [] and find_claims(portuguese) == []


def test_the_sample_pdf_is_titled_with_the_word_of_its_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    titles: dict[str, str] = {}

    def render(page: str, *, audit_id: str, locale: str, wait_seconds: float = 0.0) -> bytes:
        titles[locale] = page.split("<title>", 1)[1].split("</title>", 1)[0]
        return b"%PDF-" + locale.encode()

    monkeypatch.setattr(pdf_lib, "report_pdf", render)
    client = _client(tmp_path)
    for path in ("/ejemplo.pdf", "/sample.pdf", "/pt/exemplo.pdf"):
        assert client.get(path).status_code == 200
    assert titles["es"].endswith(" · ejemplo")
    assert titles["en"].endswith(" · sample")
    assert titles["pt"].endswith(" · exemplo")
