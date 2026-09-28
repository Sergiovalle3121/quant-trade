"""Fixes from the customer-style audit of the public pages: per-language legal
values, error pages, redirects, forms, descriptions and page chrome."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages  # noqa: E402
from quant_trade.audit import accounts as acct  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import PAGE_DESCRIPTIONS, error_page  # noqa: E402
from quant_trade.audit.seo import PUBLIC_PAGES, sitemap_xml  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.theme import STYLE  # noqa: E402
from quant_trade.audit.web import WAITLIST_PER_HOUR_PER_IP, create_app  # noqa: E402

BASE = "https://rigor.example"
OPERATOR = {
    "operator_name": "Operador de Prueba",
    "operator_contact": "hola@rigor.example",
    "operator_address": "Calle Falsa 123, Ciudad de Prueba, País de Prueba",
    "jurisdiction": "Leyes del País de Prueba; tribunales de la Ciudad de Prueba",
}
OVERRIDES = {
    "operator_address_en": "123 Fake Street, Test City, Test Country",
    "operator_address_pt": "Rua Falsa 123, Cidade de Teste, País de Teste",
    "jurisdiction_en": "Laws of Test Country; courts of Test City",
    "jurisdiction_pt": "Leis do País de Teste; tribunais da Cidade de Teste",
}
TERMS = {"es": "/terminos", "en": "/terms", "pt": "/pt/termos"}
PRIVACY = {"es": "/privacidad", "en": "/privacy", "pt": "/pt/privacidade"}
HOMES = {"es": "/", "en": "/en", "pt": "/pt"}


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **overrides
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _text(page: str) -> str:
    return re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S)


def _description(page: str) -> str:
    found = re.search(r"<meta name='description' content='([^']*)'>", page)
    assert found is not None
    return found.group(1)


def _headings(page: str) -> list[int]:
    return [int(level) for level in re.findall(r"<h([1-6])[\s>]", page)]


def _no_skipped_level(levels: list[int]) -> bool:
    return levels[:1] == [1] and all(b - a <= 1 for a, b in zip(levels, levels[1:], strict=False))


# -- K1: address and jurisdiction in the language of the page -----------------


def test_language_overrides_come_from_the_environment_and_have_no_default() -> None:
    assert AuditSettings.from_env({}).jurisdiction_en == ""
    assert AuditSettings.from_env({}).operator_address_pt == ""
    settings = AuditSettings.from_env(
        {
            "AUDIT_OPERATOR_ADDRESS": OPERATOR["operator_address"],
            "AUDIT_JURISDICTION": OPERATOR["jurisdiction"],
            "AUDIT_OPERATOR_ADDRESS_EN": "  123 Fake Street,\n Test City ",
            "AUDIT_OPERATOR_ADDRESS_PT": OVERRIDES["operator_address_pt"],
            "AUDIT_JURISDICTION_EN": OVERRIDES["jurisdiction_en"],
            "AUDIT_JURISDICTION_PT": OVERRIDES["jurisdiction_pt"],
        }
    )
    assert settings.operator_address_for("en") == "123 Fake Street, Test City"
    assert settings.operator_address_for("pt") == OVERRIDES["operator_address_pt"]
    assert settings.operator_address_for("es") == OPERATOR["operator_address"]
    assert settings.jurisdiction_for("en") == OVERRIDES["jurisdiction_en"]
    assert settings.jurisdiction_for("pt") == OVERRIDES["jurisdiction_pt"]
    assert settings.jurisdiction_for("es") == OPERATOR["jurisdiction"]


def test_an_empty_override_shows_the_base_value() -> None:
    settings = AuditSettings(**OPERATOR)
    for locale in ("es", "en", "pt"):
        assert settings.operator_address_for(locale) == OPERATOR["operator_address"]
        assert settings.jurisdiction_for(locale) == OPERATOR["jurisdiction"]


def test_an_override_alone_does_not_configure_the_legal_pages(tmp_path: Path) -> None:
    settings = AuditSettings(**OVERRIDES)
    assert not settings.legal_configured
    assert settings.jurisdiction_for("en") == "" and settings.operator_address_for("pt") == ""
    client = _client(tmp_path, **OVERRIDES)
    assert client.get("/health").json()["legal_configured"] is False
    assert "[not configured]" in client.get("/terms").text
    assert AuditSettings(**OPERATOR).legal_configured
    assert AuditSettings(**OPERATOR, **OVERRIDES).legal_configured


def test_each_language_prints_its_own_address_and_jurisdiction(tmp_path: Path) -> None:
    client = _client(tmp_path, **OPERATOR, **OVERRIDES)
    assert client.get("/health").json()["legal_configured"] is True
    own = {
        "es": (OPERATOR["operator_address"], OPERATOR["jurisdiction"]),
        "en": (OVERRIDES["operator_address_en"], OVERRIDES["jurisdiction_en"]),
        "pt": (OVERRIDES["operator_address_pt"], OVERRIDES["jurisdiction_pt"]),
    }
    for locale, (address, jurisdiction) in own.items():
        terms = _text(client.get(TERMS[locale]).text)
        privacy = _text(client.get(PRIVACY[locale]).text)
        home = _text(client.get(HOMES[locale]).text)
        assert address in terms and jurisdiction in terms, locale
        assert address in privacy and address in home, locale
        for other, (other_address, other_jurisdiction) in own.items():
            if other != locale:
                for page in (terms, privacy, home):
                    assert other_address not in page, (locale, other)
                    assert other_jurisdiction not in page, (locale, other)
        for page in (terms, privacy):
            assert find_claims(page) == [], locale


def test_without_overrides_every_language_keeps_the_base_value(tmp_path: Path) -> None:
    client = _client(tmp_path, **OPERATOR)
    for locale in ("es", "en", "pt"):
        terms = _text(client.get(TERMS[locale]).text)
        assert OPERATOR["jurisdiction"] in terms and OPERATOR["operator_address"] in terms


# -- K2, K3: error pages ------------------------------------------------------


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_error_pages_offer_the_three_languages(locale: str) -> None:
    page = error_page("x", locale=locale, kind="page")
    assert "/?lang=" not in page
    for lang, home in HOMES.items():
        link = f"href='{home}' hreflang='{lang}'"
        assert (link in page) is (lang != locale), (locale, lang)
    assert find_claims(_text(page)) == []


@pytest.mark.parametrize(
    ("path", "title", "home"),
    [
        ("/guias/no-existe", "Página no encontrada", "/"),
        ("/para/no-existe", "Página no encontrada", "/"),
        ("/guides/nope", "Page not found", "/en"),
        ("/for/nope", "Page not found", "/en"),
        ("/pt/guias/nao-existe", "Página não encontrada", "/pt"),
        ("/pt/para/nao-existe", "Página não encontrada", "/pt"),
    ],
)
def test_an_unknown_guide_or_audience_page_is_a_missing_page(
    tmp_path: Path, path: str, title: str, home: str
) -> None:
    client = _client(tmp_path)
    missing = client.get(path)
    other = client.get(f"{home.rstrip('/')}/no-such-page-xyz")
    assert missing.status_code == 404 and other.status_code == 404
    assert f"<title>{title}</title>" in missing.text
    for wrong in ("No se pudo auditar", "Could not audit", "Não foi possível auditar"):
        assert wrong not in missing.text
    assert f"<a class='btn btn-dark' href='{home}'>" in missing.text
    # The same words as any other address that does not exist.
    assert re.findall(r"<p class='err-msg'>.*?</p>", missing.text) == re.findall(
        r"<p class='err-msg'>.*?</p>", other.text
    )


def test_a_guide_slug_of_another_language_still_moves(tmp_path: Path) -> None:
    from quant_trade.audit.guides import GUIDES, guide_url

    guide = GUIDES[0]
    english = guide_url(guide.slug, "en")
    spanish = guide_url(guide.slug, "es")
    if english.rsplit("/", 1)[1] != spanish.rsplit("/", 1)[1]:
        moved = _client(tmp_path).get("/guias/" + english.rsplit("/", 1)[1], follow_redirects=False)
        assert moved.status_code == 301 and moved.headers["location"] == spanish


# -- K4: the trailing-slash redirect keeps https ------------------------------


@pytest.mark.parametrize("path", ["/en/", "/guias/", "/pt/guias/"])
def test_trailing_slash_redirect_keeps_https_behind_the_proxy(tmp_path: Path, path: str) -> None:
    client = _client(tmp_path, base_url=BASE, trusted_proxy_hops=1)
    moved = client.get(f"{path}?lang=en", headers={"host": "rigor.example"}, follow_redirects=False)
    assert moved.status_code == 307
    assert moved.headers["location"] == f"{BASE}{path.rstrip('/')}?lang=en"


def test_trailing_slash_redirect_ignores_what_the_client_sends(tmp_path: Path) -> None:
    client = _client(tmp_path, base_url=BASE, trusted_proxy_hops=1)
    spoofed = client.get(
        "/en/",
        headers={
            "host": "rigor.example",
            "x-forwarded-proto": "http",
            "x-forwarded-host": "evil.example",
            "x-forwarded-for": "203.0.113.9",
        },
        follow_redirects=False,
    )
    assert spoofed.headers["location"] == f"{BASE}/en"
    # Another host is never rewritten to look like the site.
    foreign = client.get("/en/", headers={"host": "evil.example"}, follow_redirects=False)
    assert foreign.status_code == 307
    assert not foreign.headers["location"].startswith(BASE)


def test_trailing_slash_redirect_keeps_https_when_the_host_carries_a_port(tmp_path: Path) -> None:
    client = _client(tmp_path, base_url=BASE, trusted_proxy_hops=1)
    moved = client.get(
        "/en/?lang=en", headers={"host": "rigor.example:443"}, follow_redirects=False
    )
    assert moved.status_code == 307
    assert moved.headers["location"] == f"{BASE}/en?lang=en"
    # A host that only starts like the site's is another host.
    for host in ("rigor.example.evil.example", "evil.example:443"):
        foreign = client.get("/en/", headers={"host": host}, follow_redirects=False)
        assert not foreign.headers.get("location", "").startswith(BASE), host


@pytest.mark.parametrize("path", ["/guias/gu%C3%ADa/", "/guias/a%20b/"])
def test_trailing_slash_redirect_keeps_https_on_an_encoded_path(tmp_path: Path, path: str) -> None:
    client = _client(tmp_path, base_url=BASE, trusted_proxy_hops=1)
    moved = client.get(path, headers={"host": "rigor.example"}, follow_redirects=False)
    assert moved.status_code == 307
    assert moved.headers["location"] == f"{BASE}{path.rstrip('/')}"


@pytest.mark.parametrize("path", ["//evil.example/", "/%2F%2Fevil.example/", "/en%0d%0aX:1/"])
def test_trailing_slash_redirect_never_leaves_the_site(tmp_path: Path, path: str) -> None:
    client = _client(tmp_path, base_url=BASE, trusted_proxy_hops=1)
    answer = client.get(path, headers={"host": "rigor.example"}, follow_redirects=False)
    location = answer.headers.get("location", "")
    assert location == "" or location.startswith(f"{BASE}/")
    assert not location.startswith(f"{BASE}//")
    assert "\r" not in location and "\n" not in location and "x" not in answer.headers


def test_trailing_slash_redirect_is_unchanged_without_an_https_base(tmp_path: Path) -> None:
    client = _client(tmp_path)
    moved = client.get("/en/", follow_redirects=False)
    assert moved.status_code == 307 and moved.headers["location"] == "http://testserver/en"


def test_client_address_logic_is_unchanged_by_the_redirect_fix(tmp_path: Path) -> None:
    client = _client(tmp_path, base_url=BASE, trusted_proxy_hops=1)
    for index in range(WAITLIST_PER_HOUR_PER_IP):
        sent = client.post(
            "/waitlist",
            data={"email": f"a{index}@b.co"},
            headers={"host": "rigor.example", "x-forwarded-for": "198.51.100.7"},
            follow_redirects=False,
        )
        assert sent.status_code == 303
    limited = {"host": "rigor.example", "x-forwarded-for": "198.51.100.7"}
    other = {"host": "rigor.example", "x-forwarded-for": "198.51.100.8"}
    data = {"email": "z@b.co"}
    assert client.post("/waitlist", data=data, headers=limited).status_code == 429
    assert (
        client.post("/waitlist", data=data, headers=other, follow_redirects=False).status_code
        == 303
    )


# -- K5, K10: sizes on a phone ------------------------------------------------


def test_form_fields_are_16px_on_small_screens() -> None:
    rule = re.search(
        r"@media \(max-width:620px\),\(hover:none\) and \(pointer:coarse\)\{(.*?)\}\}", STYLE, re.S
    )
    assert rule is not None
    body = rule.group(1)
    for field in ("input[type=email]", "input[type=password]", "input[type=text]", "select"):
        assert field in body
    assert "textarea{font-size:16px" in body.replace("\n", "")
    # A field with a smaller size of its own gets the same rule after it.
    small = "#invitar input[readonly]{font-family:var(--mono);font-size:.86rem"
    phone = (
        "@media (max-width:620px),(hover:none) and (pointer:coarse)"
        "{#invitar input[readonly]{font-size:16px}}"
    )
    css = account_pages.ACCOUNT_CSS
    assert small in css and phone in css
    assert css.index(small) < css.index(phone)


def test_no_table_header_is_smaller_than_the_phone_size() -> None:
    assert ".54rem" not in STYLE
    assert ".timing th{font-size:.62rem!important}" in STYLE


def test_navigation_tap_targets_are_40px_on_a_tablet() -> None:
    rule = re.search(r"@media \(min-width:521px\) and \(max-width:920px\)\{(.*?)\}\}", STYLE, re.S)
    assert rule is not None
    body = rule.group(1)
    assert ".nav .btn-sm{--h:40px}" in body
    assert ".langs>summary{min-height:40px}" in body
    assert ".nav-end>.lang,.nav-end>.nav-account{" in body and "min-height:40px" in body


# -- K6: the language switch of sign-up and sign-in ---------------------------


@pytest.mark.parametrize("kind", ["signup", "signin"])
@pytest.mark.parametrize("extras", ["", "?extras=1"])
@pytest.mark.parametrize("start", ["/auditar", "/en/audit", "/pt/auditar"])
def test_language_switch_moves_next_to_the_upload_page_of_the_language(
    kind: str, extras: str, start: str
) -> None:
    uploads = {"es": "/auditar", "en": "/en/audit", "pt": "/pt/auditar"}
    switch = account_pages._switch(kind, "es", start + extras)
    for lang, href in switch.items():
        page, _, query = href.partition("?next=")
        assert page == account_pages.path(kind, lang)
        from urllib.parse import unquote

        target = unquote(query)
        assert target == uploads[lang] + extras
        assert acct.safe_next(target) == target


def test_language_switch_keeps_any_other_next() -> None:
    for kept in ("/cuenta", "/audits/abc?token=t", "/en"):
        for href in account_pages._switch("signin", "es", kept).values():
            assert href.endswith("?next=" + account_pages._q(kept))
    assert account_pages._switch("signup", "en") == {
        lang: account_pages.path("signup", lang) for lang in ("es", "en", "pt")
    }


def test_sign_up_page_links_the_upload_page_of_each_language(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/registro?next=/auditar").text
    assert "href='/signup?next=/en/audit'" in page
    assert "href='/pt/cadastro?next=/pt/auditar'" in page
    assert "<input type='hidden' name='next' value='/auditar'>" in page


# -- K7: the news form --------------------------------------------------------


@pytest.mark.parametrize("home", ["/", "/en", "/pt"])
def test_news_form_field_and_error(tmp_path: Path, home: str) -> None:
    client = _client(tmp_path)
    field = re.search(
        r"<form class='inline-form' method='post' action='/waitlist'>(<input[^>]*>)",
        client.get(home).text,
    )
    assert field is not None
    assert "autocomplete='email'" in field.group(1) and "maxlength='254'" in field.group(1)
    # The error is shown at the address the form comes back to.
    back = {"/": "/?lang=es&error=email", "/en": "/?lang=en&error=email"}
    shown = client.get(back.get(home, f"{home}?error=email")).text
    assert "<div class='error' role='alert'>" in shown


def test_news_form_error_returns_to_the_form_in_every_language(tmp_path: Path) -> None:
    client = _client(tmp_path)
    expected = {"es": "/?lang=es&error=email#news", "en": "/?lang=en&error=email#news"}
    expected["pt"] = "/pt?error=email#news"
    for lang, location in expected.items():
        bad = client.post("/waitlist", data={"email": "nope", "lang": lang}, follow_redirects=False)
        assert bad.status_code == 303 and bad.headers["location"] == location


def test_news_form_limit_page_is_in_the_language_of_the_form(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for index in range(WAITLIST_PER_HOUR_PER_IP):
        client.post("/waitlist", data={"email": f"a{index}@b.co", "lang": "pt"})
    limited = client.post("/waitlist", data={"email": "z@b.co", "lang": "pt"})
    assert limited.status_code == 429
    assert "<html lang='pt'>" in limited.text
    assert "tente mais tarde" in limited.text
    assert "try again later" not in limited.text


# -- K8: descriptions ---------------------------------------------------------


def test_page_descriptions_are_short_distinct_and_pass_the_guard() -> None:
    seen = set()
    for kind, texts in PAGE_DESCRIPTIONS.items():
        assert set(texts) == {"es", "en", "pt"}, kind
        for locale, text in texts.items():
            assert 40 <= len(text) < 160, (kind, locale, len(text))
            assert find_claims(text) == [], (kind, locale)
            seen.add(text)
    assert len(seen) == 3 * len(PAGE_DESCRIPTIONS)


@pytest.mark.parametrize(
    ("kind", "paths"),
    [
        ("terms", TERMS),
        ("privacy", PRIVACY),
        ("compare", {"es": "/comparar", "en": "/compare", "pt": "/pt/comparar"}),
        ("signup", {"es": "/registro", "en": "/signup", "pt": "/pt/cadastro"}),
        ("signin", {"es": "/entrar", "en": "/login", "pt": "/pt/entrar"}),
        ("forgot", {"es": "/olvide", "en": "/forgot", "pt": "/pt/esqueci"}),
    ],
)
def test_each_page_serves_its_own_description(
    tmp_path: Path, kind: str, paths: dict[str, str]
) -> None:
    client = _client(tmp_path)
    for locale, path in paths.items():
        page = client.get(path)
        assert page.status_code == 200, path
        title = re.search(r"<title>(.*?)</title>", page.text)
        assert title is not None
        description = _description(page.text)
        assert description == PAGE_DESCRIPTIONS[kind][locale].replace("'", "&#x27;"), path
        assert description != title.group(1) and len(description) < 160, path
    private = kind not in ("terms", "privacy")
    assert ("content='noindex, nofollow'" in client.get(paths["es"]).text) is private


# -- K9: the sitemap declares the same default as the pages -------------------


def test_sitemap_lists_x_default_like_the_pages() -> None:
    xml = sitemap_xml(BASE)
    urls = re.findall(r"<url>(.*?)</url>", xml)
    assert len(urls) == sum(len(pair) for pair in PUBLIC_PAGES)
    for pair in PUBLIC_PAGES:
        default = f"<xhtml:link rel='alternate' hreflang='x-default' href='{BASE}{pair['es']}'/>"
        for path in pair.values():
            entry = next(url for url in urls if url.startswith(f"<loc>{BASE}{path}</loc>"))
            assert entry.count("hreflang='x-default'") == 1
            assert default in entry


# -- K10: headings and the skip link ------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/contacto",
        "/en/contact",
        "/pt/contato",
        "/registro",
        "/signup",
        "/pt/cadastro",
        "/entrar",
        "/login",
        "/pt/entrar",
        "/olvide",
        "/no-existe-xyz",
        "/en/nope-xyz",
        "/pt/nao-existe-xyz",
    ],
)
def test_headings_do_not_skip_levels(tmp_path: Path, path: str) -> None:
    client = _client(
        tmp_path,
        operator_contact="hola@rigor.example",
        contact_url="https://chat.example/rigor",
    )
    levels = _headings(client.get(path).text)
    assert levels.count(1) == 1
    assert _no_skipped_level(levels), (path, levels)


def test_heading_styles_follow_the_new_tags() -> None:
    assert ".foot h2{font:500 .7rem var(--mono)" in STYLE and ".foot h4" not in STYLE
    assert ".sr-only{position:absolute" in STYLE
    assert ".acct-stores h2{display:flex;align-items:center;margin:0 0 14px;font-size:1rem}" in (
        account_pages.ACCOUNT_CSS
    )


@pytest.mark.parametrize(
    ("path", "words"),
    [
        ("/ejemplo", "Saltar al contenido"),
        ("/sample", "Skip to content"),
        ("/pt/exemplo", "Pular para o conteúdo"),
    ],
)
def test_sample_report_has_the_skip_link(tmp_path: Path, path: str, words: str) -> None:
    page = _client(tmp_path).get(path).text
    link = f"<body><a class='skip no-print' href='#main'>{words}</a>"
    assert link in page
    assert page.count("id='main'") == 1
