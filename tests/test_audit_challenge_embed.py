"""The iframe calculator keeps the public computation and a narrow framing exception."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import accounts, challenge_embed, funnel  # noqa: E402
from quant_trade.audit import challenge_calc as calc  # noqa: E402
from quant_trade.audit.articles import _num  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import localize  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.tools_hub import TOOLS_PATH  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
BROWSER = {"User-Agent": "Mozilla/5.0 Firefox/130.0"}
FIGURES = {
    "win_rate": "45",
    "unit": "r",
    "avg_win": "1.5",
    "avg_loss": "1",
    "risk": "1",
    "per_day": "2",
    "trades": "60",
    "program": "ftmo-2step-phase1",
    "fee": "155",
}
NOT_AFFILIATED = {
    "es": "Rigor no está afiliado a FTMO.",
    "en": "Rigor is not affiliated with FTMO.",
    "pt": "O Rigor não é afiliado à FTMO.",
}
FORBIDDEN = re.compile(
    r"\b(verific\w*|certific\w*|garantiza\w*|rentables?|aprobar\w*|pasar|"
    r"pass|passed|passes|passing|approved|profitable|guarantee\w*|aprovar\w*)\b",
    re.IGNORECASE,
)


class _Markup(HTMLParser):
    def __init__(self, page: str) -> None:
        super().__init__()
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.feed(page)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, dict(attrs)))

    def all(self, tag: str) -> list[dict[str, str | None]]:
        return [attrs for name, attrs in self.tags if name == tag]


def _visible(page: str) -> str:
    page = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _result(page: str) -> str:
    found = re.search(r"<table class='calc-result' data-challenge-result>.*?</table>", page, re.S)
    assert found is not None
    return found.group(0)


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)), headers=BROWSER)


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    return _client(tmp_path_factory.mktemp("challenge-embed"))


def test_embedded_routes_cover_every_public_firm_and_language() -> None:
    assert set(challenge_embed.PAGES.values()) == set(calc.PAGES.values())
    assert challenge_embed.PATHS == {
        "es": "/insertar/calculadora-reto",
        "en": "/embed/challenge-calculator",
        "pt": "/pt/incorporar/calculadora-desafio",
    }


@pytest.mark.parametrize("key", ("intro", "height", "credit_note"))
def test_new_english_widget_notes_have_spanish_translation_rules(key: str) -> None:
    assert localize(challenge_embed.COPY["en"][key], "es") == challenge_embed.COPY["es"][key]


@pytest.mark.parametrize("path", list(challenge_embed.PAGES))
def test_widgets_allow_framing_are_noindex_and_canonical_to_the_normal_page(
    site: TestClient, path: str
) -> None:
    locale, firm = challenge_embed.PAGES[path]
    response = site.get(path, params={"ref": "embed"})
    assert response.status_code == 200
    policy = response.headers["content-security-policy"]
    assert "frame-ancestors *" in policy
    assert "frame-ancestors 'none'" not in policy
    # The frameable document runs no script and its forms only reach itself.
    assert "script-src 'none'" in policy
    assert "form-action 'self';" in policy
    assert "checkout.stripe.com" not in policy and "sha256-" not in policy
    assert "x-frame-options" not in response.headers
    assert "noindex" in response.headers["x-robots-tag"]
    assert "set-cookie" not in response.headers
    markup = _Markup(response.text)
    assert markup.all("html") == [{"lang": locale}]
    assert any(
        link.get("rel") == "canonical"
        and link.get("href") == BASE + calc.challenge_url(locale, firm)
        for link in markup.all("link")
    )
    assert any(
        meta.get("name") == "robots" and "noindex" in (meta.get("content") or "")
        for meta in markup.all("meta")
    )
    assert len(markup.all("h1")) == 1
    assert not markup.all("nav") and not markup.all("header")
    assert markup.all("form")
    assert all(form.get("method") == "get" for form in markup.all("form"))
    anchored = f"{path}#{challenge_embed.RESULT_ANCHOR[locale]}"
    assert any(form.get("action") == anchored for form in markup.all("form"))
    assert not markup.all("script") and len(markup.all("iframe")) == 0
    assert find_claims(_visible(response.text)) == []
    assert not FORBIDDEN.findall(_visible(response.text))
    assert "Declarado ·" not in _visible(response.text)


@pytest.mark.parametrize("locale", LOCALES)
def test_only_known_widget_routes_change_the_framing_policy(site: TestClient, locale: str) -> None:
    for path in (
        calc.challenge_url(locale),
        challenge_embed.HELP_PATHS[locale],
        challenge_embed.PATHS[locale] + "/not-a-firm",
        challenge_embed.PATHS[locale] + "-unrelated",
    ):
        response = site.get(path)
        assert "frame-ancestors 'none'" in response.headers["content-security-policy"], path
        assert response.headers["x-frame-options"] == "DENY", path
    help_page = site.get(challenge_embed.HELP_PATHS[locale])
    assert "frame-src 'self'" in help_page.headers["content-security-policy"]
    normal = site.get(calc.challenge_url(locale))
    assert "frame-src 'self'" not in normal.headers["content-security-policy"]


@pytest.mark.parametrize("locale", LOCALES)
def test_widget_is_get_only_and_never_sets_a_cookie_with_existing_browser_cookies(
    tmp_path: Path, locale: str
) -> None:
    client = _client(tmp_path)
    client.cookies.set(accounts.SESSION_COOKIE, "existing-session")
    client.cookies.set(funnel.REF_COOKIE, "reto")
    client.cookies.set(funnel.SEEN_COOKIE, "2026-01-01")
    path = challenge_embed.PATHS[locale]
    for params in ({"ref": "embed"}, {**FIGURES, "ref": "embed"}):
        response = client.get(path, params=params)
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert all(form.get("method") == "get" for form in _Markup(response.text).all("form"))
    for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
        refused = client.request(method, path, data=FIGURES)
        assert refused.status_code == 405, method
        assert "set-cookie" not in refused.headers
        # The site's error page on a widget path is not the widget: never framed.
        assert "frame-ancestors 'none'" in refused.headers["content-security-policy"], method
        assert refused.headers["x-frame-options"] == "DENY", method


def test_a_server_error_on_a_widget_path_cannot_be_framed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    client = TestClient(
        create_app(settings, make_store(settings.database_url)),
        headers=BROWSER,
        raise_server_exceptions=False,
    )

    def broken(**kwargs: object) -> str:
        raise RuntimeError("render failed")

    monkeypatch.setattr(challenge_embed, "widget_page", broken)
    response = client.get(challenge_embed.PATHS["en"] + "/ftmo")
    assert response.status_code == 500
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-frame-options"] == "DENY"


@pytest.mark.parametrize("locale", LOCALES)
def test_firm_widget_shows_its_lead_with_the_non_affiliation_line(
    site: TestClient, locale: str
) -> None:
    page = site.get(challenge_embed.PATHS[locale] + "/ftmo").text
    # Visible without opening anything: review sites are often a firm's affiliates.
    outside = _visible(re.sub(r"<details>.*?</details>", "", page, flags=re.S))
    assert calc.firm_copy("ftmo", locale)["lead"] in outside
    assert NOT_AFFILIATED[locale] in outside
    rules = calc.COPY[locale]["firm_rules_title"].format(firm=calc.FIRMS["ftmo"])
    assert f"<summary>{html.escape(rules)}</summary>" in page
    general = site.get(challenge_embed.PATHS[locale]).text
    assert f"<summary>{html.escape(calc.COPY[locale]['rules_title'])}</summary>" in general


def test_portuguese_embed_copy_says_empresa_like_the_calculator() -> None:
    words = " ".join(challenge_embed.COPY["pt"].values())
    assert not re.search(r"firmas?", words, re.IGNORECASE)
    assert "empresa" in challenge_embed.COPY["pt"]["credit_note"]


@pytest.mark.parametrize("locale", LOCALES)
def test_widget_uses_compute_and_shows_the_same_result_as_the_normal_page(
    site: TestClient, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    parsed = calc.parse(FIGURES, "ftmo")
    assert not parsed.errors and parsed.value is not None
    expected = calc.compute(parsed.value)
    calls: list[calc.ChallengeInput] = []
    original = calc.compute

    def compute(value: calc.ChallengeInput) -> calc.ChallengeReading:
        calls.append(value)
        return original(value)

    monkeypatch.setattr(calc, "compute", compute)
    embedded = site.get(challenge_embed.PATHS[locale] + "/ftmo", params=FIGURES)
    assert embedded.status_code == 200
    assert calls == [parsed.value]
    normal = site.get(calc.challenge_url(locale, "ftmo"), params=FIGURES)
    assert normal.status_code == 200
    assert _result(embedded.text) == _result(normal.text)
    visible_result = _visible(_result(embedded.text))
    for key in ("pass", "fail_daily_loss", "fail_total_loss", "unfinished"):
        value = float(expected.declared.outcome[key]["value"])
        assert f"{_num(value * 100, locale, 1)} %" in visible_result
    assert find_claims(_visible(embedded.text)) == []
    assert not FORBIDDEN.findall(_visible(embedded.text))


@pytest.mark.parametrize("path", list(challenge_embed.PAGES))
def test_attribution_opens_the_same_firm_on_rigor_with_the_embed_tag(
    site: TestClient, path: str
) -> None:
    locale, firm = challenge_embed.PAGES[path]
    page = site.get(path).text
    footer = re.search(r"<footer\b[^>]*>(.*?)</footer>", page, re.S)
    assert footer is not None
    links = _Markup(footer.group(1)).all("a")
    link = next(item for item in links if "ref=embed" in (item.get("href") or ""))
    target = urlsplit(link["href"] or "")
    assert target.path == calc.challenge_url(locale, firm)
    assert parse_qs(target.query) == {"ref": ["embed"]}
    assert link.get("target") == "_blank"
    assert "noopener" in (link.get("rel") or "").split()
    assert "Rigor" in _visible(footer.group(1))
    if locale == "es":
        assert "Hecho con Rigor · reglas publicadas por la firma, con fuente y fecha" in _visible(
            footer.group(1)
        )


@pytest.mark.parametrize("locale", LOCALES)
def test_auxiliary_links_open_outside_the_widget_while_the_form_stays_inside(
    site: TestClient, locale: str
) -> None:
    path = challenge_embed.PATHS[locale] + "/ftmo"
    response = site.get(path, params=FIGURES)
    assert response.status_code == 200
    markup = _Markup(response.text)
    links = markup.all("a")
    assert any("data-challenge-winrate" in link for link in links)
    assert any("nofollow" in (link.get("rel") or "").split() for link in links)
    for link in links:
        assert link.get("target") == "_blank"
        tokens = (link.get("rel") or "").split()
        assert "noopener" in tokens
        assert len(tokens) == len(set(tokens))
    for tag in re.findall(r"<a\b[^>]*>", response.text):
        assert len(re.findall(r"\srel=", tag)) == 1
        assert len(re.findall(r"\starget=", tag)) == 1
    form = markup.all("form")[0]
    anchor = challenge_embed.RESULT_ANCHOR[locale]
    # After «Calcular» the iframe opens on the result, not on the form again.
    assert form["action"] == f"{path}#{anchor}"
    assert form["method"] == "get"
    assert form.get("target") in (None, "_self")
    result = re.search(rf"<section id='{anchor}'>(.*?)</section>", response.text, re.S)
    assert result is not None and "data-challenge-result" in result.group(1)
    assert response.text.count(f"id='{anchor}'") == 1


@pytest.mark.parametrize("locale", LOCALES)
def test_installation_page_has_a_live_preview_copyable_code_and_no_script_dependency(
    site: TestClient, locale: str
) -> None:
    response = site.get(challenge_embed.HELP_PATHS[locale], params={"firm": "ftmo"})
    assert response.status_code == 200
    markup = _Markup(response.text)
    assert markup.all("html") == [{"lang": locale}]
    preview = markup.all("iframe")
    assert len(preview) == 1
    assert preview[0].get("src") == BASE + challenge_embed.PATHS[locale] + "/ftmo"
    code = re.search(
        r"<textarea\b[^>]*\bid='embed-code'[^>]*>(.*?)</textarea>", response.text, re.S
    )
    assert code is not None
    snippet = _Markup(html.unescape(code.group(1))).all("iframe")
    assert len(snippet) == 1
    assert snippet[0]["src"] == preview[0]["src"]
    assert snippet[0]["width"] == "100%"
    assert int(snippet[0]["height"] or "0") >= 600
    assert snippet[0]["loading"] == "lazy"
    assert snippet[0].get("style") == "border:0"
    assert snippet[0].get("title")
    # One accessible name for the code: the heading, not a repeated label.
    assert "for='embed-code'" not in response.text
    textarea = next(item for item in markup.all("textarea") if item.get("id") == "embed-code")
    labelled = textarea.get("aria-labelledby")
    assert labelled and f"<h2 id='{labelled}'>" in response.text
    assert any(form.get("method") == "get" for form in markup.all("form"))
    assert {select.get("name") for select in markup.all("select")} >= {"firm", "locale"}
    assert find_claims(_visible(response.text)) == []
    tools = site.get(TOOLS_PATH[locale]).text
    tool_links = _Markup(tools).all("a")
    assert any(link.get("href") == challenge_embed.HELP_PATHS[locale] for link in tool_links)
    # The link sits with the challenge calculator's own links, before the rules table.
    challenge = tools.split("id='tool-challenge'", 1)[1].split("id='tool-rules_table'", 1)[0]
    assert f"href='{challenge_embed.HELP_PATHS[locale]}'" in challenge
    assert challenge_embed.COPY[locale]["link"] in html.unescape(challenge)


def test_sitemap_includes_instructions_but_no_embedded_calculators(site: TestClient) -> None:
    response = site.get("/sitemap.xml")
    assert response.status_code == 200
    root = ElementTree.fromstring(response.text)
    namespace = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    paths = {
        urlsplit(element.text or "").path for element in root.findall("s:url/s:loc", namespace)
    }
    assert set(challenge_embed.HELP_PATHS.values()) <= paths
    assert not set(challenge_embed.PAGES) & paths


def test_installation_get_selects_the_widgets_language_and_firm(site: TestClient) -> None:
    response = site.get(
        challenge_embed.HELP_PATHS["es"], params={"locale": "pt", "firm": "topstep"}
    )
    assert response.status_code == 200
    markup = _Markup(response.text)
    assert markup.all("html") == [{"lang": "es"}]
    assert markup.all("iframe")[0]["src"] == BASE + challenge_embed.PATHS["pt"] + "/topstep"
    for params in ({"firm": "unknown"}, {"locale": "unknown"}, [("firm", "ftmo")] * 2):
        assert site.get(challenge_embed.HELP_PATHS["es"], params=params).status_code == 400


def test_installation_language_links_keep_the_chosen_firm_and_widget_language(
    site: TestClient,
) -> None:
    def language_links(page: str) -> dict[str, str]:
        return {
            str(link["hreflang"]): str(link["href"])
            for link in _Markup(page).all("a")
            if link.get("hreflang")
            and urlsplit(link.get("href") or "").path in challenge_embed.HELP_PATHS.values()
        }

    chosen = site.get(challenge_embed.HELP_PATHS["es"], params={"locale": "pt", "firm": "topstep"})
    links = language_links(chosen.text)
    assert set(links) == {"en", "pt"}
    for lang, href in links.items():
        target = urlsplit(href)
        assert target.path == challenge_embed.HELP_PATHS[lang]
        assert parse_qs(target.query) == {"firm": ["topstep"], "locale": ["pt"]}
    # By default the widget follows the page: plain links to the other languages.
    plain = language_links(site.get(challenge_embed.HELP_PATHS["en"]).text)
    assert plain == {lang: challenge_embed.HELP_PATHS[lang] for lang in ("es", "pt")}


def test_widget_views_stay_off_until_privacy_disclosure_covers_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert funnel.CHALLENGE_EMBED_VIEWS_ENABLED is False
    client = _client(tmp_path)
    day = funnel.day_of(datetime.now(UTC))
    counter = client.app.state.challenge_embed_views
    store = client.app.state.store
    assert client.get(challenge_embed.PATHS["es"] + "/ftmo?ref=embed").status_code == 200
    counter.flush()
    client.app.state.visits.flush()
    assert store.challenge_embed_view_rows(day) == []
    assert store.funnel_events(day)["visits"] == []
    monkeypatch.setattr(funnel, "CHALLENGE_EMBED_VIEWS_ENABLED", True)
    for locale, firm in (("es", "ftmo"), ("en", "ftmo"), ("pt", "topstep")):
        response = client.get(
            challenge_embed.PATHS[locale] + "/" + firm,
            headers={"Referer": "https://publisher.example/private-reader-page"},
        )
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
    counter.flush()
    assert store.challenge_embed_view_rows(day) == [(day, "ftmo", 2), (day, "topstep", 1)]
    assert {column.name for column in store.challenge_embed_views.columns} == {
        "day",
        "firm",
        "views",
    }
    client.app.state.visits.flush()
    assert store.funnel_events(day)["visits"] == []


@pytest.mark.parametrize("locale", LOCALES)
def test_invalid_and_duplicate_fields_are_rejected_without_computing(
    site: TestClient, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(calc, "compute", lambda value: calls.append(value))
    path = challenge_embed.PATHS[locale]
    for params in ({**FIGURES, "win_rate": "150"}, [*FIGURES.items(), ("win_rate", "50")]):
        response = site.get(path, params=params)
        assert response.status_code == 400
        assert "data-challenge-result" not in response.text
        assert "set-cookie" not in response.headers
        assert "frame-ancestors *" in response.headers["content-security-policy"]
    assert calls == []
    assert site.get(path + "/not-a-firm").status_code == 404


def test_widget_computations_share_the_normal_calculators_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(calc, "REQUESTS_PER_HOUR", 1)
    client = _client(tmp_path)
    assert client.get(calc.challenge_url("es"), params=FIGURES).status_code == 200
    calls: list[object] = []
    monkeypatch.setattr(calc, "compute", lambda value: calls.append(value))
    path = challenge_embed.PATHS["es"]
    response = client.get(path, params=FIGURES)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "3600"
    assert "data-challenge-result" not in response.text and not calls
    assert "frame-ancestors *" in response.headers["content-security-policy"]
    assert "set-cookie" not in response.headers
    assert client.get(path).status_code == 200
