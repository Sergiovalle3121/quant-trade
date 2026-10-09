"""Toward the first free report: pricing, the sample, sign-up and each article's next step.

Every page is read over HTTP with ``TestClient`` (no network), in Spanish, English
and Portuguese; every new text passes the profit-claim guard; a client's report
renders byte for byte as before when the sample's additions are off.
"""

from __future__ import annotations

import html
import re
import socket
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Any, get_args
from urllib.parse import parse_qs, urlsplit

import pytest
from audit_fixtures import csv_bytes, positive_drift, trades_frame

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages, accounts, web  # noqa: E402
from quant_trade.audit.articles import (  # noqa: E402
    ARTICLE_NEXT_STEPS,
    ARTICLES,
    ARTICLES_BY_KEY,
    ARTICLES_COPY,
    LUCK_EXAMPLE_INPUT,
    NEXT_STEP_COPY,
    WIN_RATE_EXAMPLE_VALUES,
    article_url,
    next_step_call,
    next_step_links,
)
from quant_trade.audit.calculator import CALCULATOR_PATH  # noqa: E402
from quant_trade.audit.check import COPY as CHECK_COPY  # noqa: E402
from quant_trade.audit.engine import run_audit  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import guide_url, guides_index_url  # noqa: E402
from quant_trade.audit.pages import (  # noqa: E402
    AUDIT_PATHS,
    PLATFORMS,
    SAMPLE_PAGE_PATHS,
    _articles_cta,
    upload_page,
)
from quant_trade.audit.portuguese import STATUS_TEXT_PT  # noqa: E402
from quant_trade.audit.pricing import PRICING_COPY, PRICING_PATH, start_cta  # noqa: E402
from quant_trade.audit.report import (  # noqa: E402
    LABELS,
    SAMPLE_CTA_COPY,
    STATUS_TEXT,
    evidence_label,
    render,
    sample_check_block,
    sample_cta_band,
    sample_signup_href,
)
from quant_trade.audit.sample_publication import sample_public_path  # noqa: E402
from quant_trade.audit.schema import DeclaredMetadata, build_inputs  # noqa: E402
from quant_trade.audit.seo import CHECK_PATH, SIGNAL_SAMPLE_PATHS  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.strategies import CLASS_ORDER  # noqa: E402
from quant_trade.audit.verdict import DIMENSION_ORDER, Status  # noqa: E402
from quant_trade.audit.winrate import WINRATE_PATH  # noqa: E402

LOCALES = ("es", "en", "pt")
SIGNUP = {"es": "/registro", "en": "/signup", "pt": "/pt/cadastro"}
SITE = "https://rigor.example"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
PASSWORD = "una frase larga y segura"
#: What a confirmation e-mail needs; nothing is sent (no worker runs in tests).
MAIL = {
    "base_url": SITE,
    "email_verification_required": True,
    "email_token_secret": "stable secret shared across replicas 1234567890",
    "smtp_host": "smtp.example",
    "smtp_from": "Rigor <hello@example.com>",
}
#: Spanish words that must not appear on a Portuguese page.
SPANISH_ON_PT = ("Sube ", "archivo", "Precios", "Empezar", "cuenta gratis", "informe", "artículo")
#: Endorsement and result words the copy must never use, in any language.
ENDORSEMENT = re.compile(
    r"verifica|certifica|aprobad|aprovad|garant|rentab|rentáve|lucrativ|profitab|guarante"
    r"|certified|approved|verified",
    re.I,
)
#: A processing time nobody measured.
DURATION = re.compile(r"\b(?:segundos?|minutos?|seconds?|minutes?|horas?|hours?)\b", re.I)
#: The next step of each article, as the brief assigns it.
EXPECTED_STEPS: dict[str, tuple[dict[str, str], ...]] = {
    "leer-informe-probador-mt5": ({"kind": "audit"}, {"kind": "guide", "slug": "mt5"}),
    "ea-sobreoptimizado": ({"kind": "audit"}, {"kind": "guide", "slug": "mt5-optimization"}),
    "lo-eligio-el-optimizador": (
        {"kind": "audit"},
        {"kind": "guide", "slug": "mt5-optimization"},
    ),
    "backtest-costos-reales": ({"kind": "audit"},),
    "copiar-senales-mql5-myfxbook": ({"kind": "guide", "slug": "myfxbook"}, {"kind": "audit"}),
    "cuantas-operaciones-porcentaje-aciertos": ({"kind": "winrate", "example": "win-rate"},),
    "cuantos-intentos-reto-prop-firm": ({"kind": "audience", "slug": "retos-prop-firm"},),
    "sharpe-deflactado-track-record": ({"kind": "calculator", "example": "luck"},),
    "bot-ia-backtest-suerte": ({"kind": "calculator", "example": "luck"},),
    "auditoria-independiente-backtest": ({"kind": "audit"}, {"kind": "sample"}),
    "que-hacer-despues-del-backtest": ({"kind": "audit"}, {"kind": "sample"}),
    "auditar-cartera-modelo-senales": ({"kind": "audit"}, {"kind": "sample"}),
    "monte-carlo-backtest": ({"kind": "audit"}, {"kind": "sample"}),
    "rachas-perdedoras": ({"kind": "winrate", "example": "win-rate"},),
}
PRICING_KEYS = (
    "start_title",
    "start_text",
    "start_button",
    "start_text_free",
    "start_button_free",
    "start_sample",
    "start_guides",
    "start_calculator",
)
ACCOUNT_KEYS = (
    "welcome_confirm_guides",
    "next_title",
    "next_account",
    "next_confirm_welcome",
    "next_confirm",
    "next_upload",
    "next_guides",
    "next_report",
    "next_free_welcome",
    "next_free_all",
    "next_sample",
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Only loopback: TestClient talks to the app in process."""
    original = socket.getaddrinfo

    def local_only(host: str, *args: Any, **kwargs: Any) -> Any:
        assert host in {"localhost", "127.0.0.1", "::1"}, host
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", local_only)
    monkeypatch.setattr(
        "quant_trade.audit.market._download",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no market download")),
    )
    yield


def _visible(page: str) -> str:
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _hrefs(fragment: str) -> list[str]:
    return [html.unescape(href) for href in re.findall(r"href='([^']*)'", fragment)]


def _between(page: str, start: str, end: str) -> str:
    assert start in page, start
    return page.split(start, 1)[1].split(end, 1)[0]


def _settings(tmp_path: Path, **extra: Any) -> AuditSettings:
    tmp_path.mkdir(parents=True, exist_ok=True)
    values: dict[str, Any] = {"database_url": f"sqlite:///{tmp_path}/audit.db"}
    values.update(extra)
    return AuditSettings(**values)


def _paid(tmp_path: Path, **extra: Any) -> AuditSettings:
    """Outside free mode: the first full report is free with an account."""
    return _settings(tmp_path, free_mode=False, access_codes=True, **extra)


def _client(settings: AuditSettings, base_url: str = "http://testserver") -> TestClient:
    return TestClient(
        web.create_app(settings, make_store(settings.database_url)), base_url=base_url
    )


def _resolves(client: TestClient, href: str) -> bool:
    """The link answers 200, after the redirects a visitor follows."""
    return client.get(href).status_code == 200


def _csrf(page: str) -> str:
    match = re.search(r"name='csrf' value='([^']+)'", page)
    assert match is not None
    return match.group(1)


# -- Every new text ---------------------------------------------------------------


def _new_texts(locale: str) -> list[str]:
    return [
        *(PRICING_COPY[locale][key] for key in PRICING_KEYS),
        *SAMPLE_CTA_COPY[locale].values(),
        *(account_pages.COPY[locale][key] for key in ACCOUNT_KEYS),
        *NEXT_STEP_COPY[locale].values(),
    ]


@pytest.mark.parametrize("locale", LOCALES)
def test_every_new_text_passes_the_guard_and_promises_nothing(locale: str) -> None:
    for text in _new_texts(locale):
        assert find_claims(text) == [], text
        assert ENDORSEMENT.search(text) is None, text
        assert DURATION.search(text) is None, text
        if locale == "pt":
            assert not any(word in text for word in SPANISH_ON_PT), text


# -- 1. Pricing -------------------------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_pricing_closes_with_the_free_report_over_http(tmp_path: Path, locale: str) -> None:
    client = _client(_paid(tmp_path))
    response = client.get(PRICING_PATH[locale])
    assert response.status_code == 200
    page = response.text
    words = PRICING_COPY[locale]
    close = _between(page, "<section class='article-cta'>", "</section>")
    shown = _visible(close)
    for key in ("start_title", "start_text", "start_button", "start_sample", "start_guides"):
        assert words[key] in shown, key
    assert words["start_calculator"] in shown
    assert words["start_text_free"] not in shown
    # The main button asks for the free report; the calculator is a text link.
    assert f"<a class='btn btn-dark' href='{AUDIT_PATHS[locale]}'>" in close
    assert f"<a href='{CALCULATOR_PATH[locale]}'>" in close
    links = _hrefs(close)
    assert links == [
        AUDIT_PATHS[locale],
        SAMPLE_PAGE_PATHS[locale],
        guides_index_url(locale),
        CALCULATOR_PATH[locale],
    ]
    # The old close led with the calculator; it is gone from this page.
    assert ARTICLES_COPY[locale]["calculator"] not in _visible(page)
    assert find_claims(html.unescape(page)) == []
    for href in links:
        assert _resolves(client, href), href
    # The button goes through sign-up, with the form as the way back.
    first = client.get(AUDIT_PATHS[locale], follow_redirects=False)
    assert first.status_code == 303
    assert first.headers["location"] == f"{SIGNUP[locale]}?next={AUDIT_PATHS[locale]}"


@pytest.mark.parametrize("locale", LOCALES)
def test_pricing_close_follows_the_configuration(
    tmp_path: Path, locale: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    words = PRICING_COPY[locale]
    paid = _paid(tmp_path)
    welcome = _visible(start_cta(paid, locale))
    assert words["start_text"] in welcome and words["email_note"] not in welcome
    confirm = _visible(start_cta(replace(paid, email_verification_required=True), locale))
    assert f"{words['start_text']} {words['email_note']}" in confirm
    # Free mode: every full report is free and the form needs no account.
    free = _visible(start_cta(_settings(tmp_path), locale))
    assert words["start_text_free"] in free and words["start_button_free"] in free
    assert words["start_text"] not in free and words["email_note"] not in free
    client = _client(_settings(tmp_path))
    assert client.get(AUDIT_PATHS[locale], follow_redirects=False).status_code == 200
    # Without a free first report the page keeps the articles' close.
    monkeypatch.setattr(accounts, "WELCOME_FULL_REPORT", False)
    assert start_cta(paid, locale) == _articles_cta(locale)


# -- 2. The sample report ---------------------------------------------------------


@cache
def _real_result(locale: str) -> Any:
    inputs = build_inputs(
        csv_bytes(positive_drift(600)),
        DeclaredMetadata(trials=4, cost_bps_per_side=5, locale=locale),  # type: ignore[arg-type]
        trades_bytes=csv_bytes(trades_frame(20)),
    )
    return run_audit(inputs, now=NOW, audit_id="abc123", bootstrap_samples=200)


#: The shapes a client's report takes: paid with its PDF, locked, and free mode.
VARIANTS: dict[str, dict[str, Any]] = {
    "full": {"watermark": False, "free_mode": False, "pdf_url": "/audits/abc123/report.pdf"},
    "locked": {"watermark": True, "free_mode": False, "checkout_url": "/audits/abc123/checkout"},
    "free": {"watermark": True, "free_mode": True, "notice": "Aviso"},
}


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_a_real_report_is_byte_for_byte_the_same_without_the_sample_additions(
    locale: str, variant: str
) -> None:
    result = _real_result(locale)
    kwargs = VARIANTS[variant]
    before, before_json = render(result, locale=locale, legal_links=True, **kwargs)
    off, off_json = render(result, locale=locale, legal_links=True, sample_cta=False, **kwargs)
    assert off == before and off_json == before_json
    for marker in ("sample-cta", "sample-check", sample_signup_href(locale)):
        assert marker not in off
    assert f">{html.escape(LABELS[locale]['my_account'])}</a>" in off
    # On, the page gains exactly the band, the closing block and the sign-up link.
    on, on_json = render(result, locale=locale, legal_links=True, sample_cta=True, **kwargs)
    assert on_json == off_json
    labels = LABELS[locale]
    account = {"es": "/cuenta", "pt": "/pt/conta"}.get(locale, "/account")
    restored = on.replace(sample_cta_band(locale), "", 1)
    if kwargs.get("pdf_url"):
        block = sample_check_block(locale, kwargs["pdf_url"], labels["pdf_busy"])
        assert block in on
        restored = restored.replace(block, "", 1)
    signup = (
        f"<a class='nav-account' href='{html.escape(sample_signup_href(locale))}'>"
        f"{html.escape(SAMPLE_CTA_COPY[locale]['signup'])}</a>"
    )
    assert signup in on
    restored = restored.replace(
        signup,
        f"<a class='nav-account' href='{account}'>{html.escape(labels['my_account'])}</a>",
        1,
    )
    assert restored == off


@pytest.fixture
def pdf_pages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A stand-in PDF renderer: the sample page it was given, and a few fixed bytes."""
    seen: list[str] = []

    def fake_pdf(page: str, **kwargs: Any) -> bytes:
        seen.append(page)
        return f"%PDF-1.4\n% rigor sample {kwargs.get('locale')}\n".encode()

    monkeypatch.setattr(web.pdf_lib, "available", lambda: True)
    monkeypatch.setattr(web.pdf_lib, "report_pdf", fake_pdf)
    return seen


@pytest.mark.parametrize("locale", LOCALES)
def test_the_sample_offers_the_free_report_and_a_check_of_its_pdf(
    tmp_path: Path, locale: str, pdf_pages: list[str]
) -> None:
    client = _client(_paid(tmp_path))
    response = client.get(SAMPLE_PAGE_PATHS[locale])
    assert response.status_code == 200
    page = response.text
    words = SAMPLE_CTA_COPY[locale]
    # (a) Under the synthetic-data notice, before the class: hidden when printed.
    band = _between(page, "<div class='sample-cta no-print'>", "</div>")
    hero = _between(page, "<section class='report-hero'>", "</section>")
    assert hero.index("<div class='notice'>") < hero.index("sample-cta no-print")
    assert hero.index("sample-cta no-print") < hero.index("<h1")
    assert words["lead_welcome"] in _visible(band)
    assert f"<a class='btn btn-primary btn-sm' href='{AUDIT_PATHS[locale]}'>" in band
    assert words["button_welcome"] in _visible(band)
    assert words["files"] in _visible(band)
    assert _hrefs(band) == [
        AUDIT_PATHS[locale],
        guide_url("mt5", locale),
        guide_url("mt5-optimization", locale),
        # The public page this report would get (sample_publication).
        sample_public_path("ejemplo", locale),
        # Whoever is about to copy a signal goes on to the other sample.
        SIGNAL_SAMPLE_PATHS[locale],
    ]
    # (b) "Create account" where a client's report says "My account".
    toolbar = _between(page, "<div class='nav-end no-print report-toolbar'>", "</div>")
    assert f"href='{sample_signup_href(locale)}'>{html.escape(words['signup'])}</a>" in toolbar
    assert LABELS[locale]["my_account"] not in toolbar
    assert sample_signup_href(locale) == f"{SIGNUP[locale]}?next={AUDIT_PATHS[locale]}"
    # (c) The closing block, after the seal and before the footer.
    block = _between(page, "<section class='rsec no-print sample-check'>", "</section>")
    assert page.index("sample-check") < page.index("<div class='report-foot'>")
    assert words["check_title"] in _visible(block) and words["check_text"] in _visible(block)
    pdf = web.SAMPLE_PDF_PATHS[locale]
    assert f"href='{pdf}' download" in block
    assert _hrefs(block) == [pdf, CHECK_PATH[locale]]
    shown = _visible(page)
    assert find_claims(shown) == [] and find_claims(html.unescape(page)) == []
    for href in _hrefs(band) + [sample_signup_href(locale), CHECK_PATH[locale]]:
        assert _resolves(client, href), href
    # The PDF a visitor downloads carries none of it.
    download = client.get(pdf)
    assert download.status_code == 200 and download.content.startswith(b"%PDF")
    assert pdf_pages and all("sample-cta" not in seen for seen in pdf_pages)
    assert all("sample-check" not in seen for seen in pdf_pages)
    # "Check it yourself" says what the check page answers for the sample.
    checked = client.post(
        CHECK_PATH[locale],
        files={"report": ("rigor-sample.pdf", download.content, "application/pdf")},
        data={"lang": locale},
    )
    assert checked.status_code == 200
    answer = html.unescape(checked.text)
    assert CHECK_COPY[locale]["found_title"] in answer
    assert CHECK_COPY[locale]["sample"] in answer


@pytest.mark.parametrize("locale", LOCALES)
def test_the_sample_band_follows_the_configuration(
    tmp_path: Path, locale: str, pdf_pages: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    words = SAMPLE_CTA_COPY[locale]
    free = _client(_settings(tmp_path / "free")).get(SAMPLE_PAGE_PATHS[locale]).text
    band = _visible(_between(free, "<div class='sample-cta no-print'>", "</div>"))
    assert words["lead_free"] in band and words["button_free"] in band
    assert words["lead_welcome"] not in band
    monkeypatch.setattr(accounts, "WELCOME_FULL_REPORT", False)
    paid = _client(_paid(tmp_path / "paid")).get(SAMPLE_PAGE_PATHS[locale]).text
    band = _visible(_between(paid, "<div class='sample-cta no-print'>", "</div>"))
    assert words["lead_paid"] in band and "gratis" not in band and "grátis" not in band
    assert "free" not in band


def test_without_a_pdf_renderer_the_sample_has_no_check_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web.pdf_lib, "available", lambda: False)
    page = _client(_paid(tmp_path)).get("/ejemplo").text
    assert "sample-check" not in page
    assert "<div class='sample-cta no-print'>" in page


# -- 3. Sign-up -------------------------------------------------------------------


def _steps(page: str) -> list[str]:
    side = _between(page, "<div class='acct-card acct-perks acct-next'>", "</div>")
    return re.findall(r"<li><span>(.*?)</span></li>", side)


@pytest.mark.parametrize("locale", LOCALES)
def test_sign_up_on_the_way_to_the_form_says_what_happens_next(tmp_path: Path, locale: str) -> None:
    client = _client(_paid(tmp_path))
    # How a visitor arrives: the form sends them to sign up first.
    first = client.get(AUDIT_PATHS[locale], follow_redirects=False)
    response = client.get(first.headers["location"])
    assert response.status_code == 200
    page = response.text
    copy = account_pages.COPY[locale]
    side = _between(page, "<div class='acct-side'>", "<div class='acct-card acct-stores'>")
    assert copy["next_title"] in _visible(side)
    steps = [_visible(step) for step in _steps(page)]
    # No e-mail step: this configuration does not require a confirmed address.
    assert len(steps) == 3
    assert steps[0] == copy["next_account"]
    for platform in PLATFORMS:
        assert platform in steps[1]
    assert copy["next_guides"] in steps[1]
    count = {"es": "seis", "en": "six", "pt": "seis"}[locale] if len(DIMENSION_ORDER) == 6 else ""
    assert f" {count or len(DIMENSION_ORDER)} " in steps[2]
    assert f"{CLASS_ORDER[0]} " in steps[2] and f" {CLASS_ORDER[-1]}," in steps[2]
    # Each check comes out with a status, as the report's badges name it; the
    # evidence labels belong to each figure, never to a check.
    statuses = STATUS_TEXT_PT if locale == "pt" else STATUS_TEXT[locale]
    for status in get_args(Status):
        assert statuses[status] in steps[2]
    assert evidence_label("DECLARED", locale) not in steps[2]
    assert "PDF" in steps[2] and steps[2].endswith(copy["next_free_welcome"])
    assert DURATION.search(_visible(side)) is None
    links = _hrefs(side)
    assert links == [guides_index_url(locale), SAMPLE_PAGE_PATHS[locale]]
    for href in links:
        assert _resolves(client, href), href
    # The account benefits give way; what is kept still shows.
    assert copy["benefits"].split("|")[0] not in page
    assert html.escape(copy["stores_title"]) in page
    assert find_claims(html.unescape(page)) == []
    # A form sent back with a mistake keeps the same panel.
    again = client.post(
        SIGNUP[locale],
        data={
            "email": "no-es-un-correo",
            "password": PASSWORD,
            "csrf": _csrf(page),
            "next": AUDIT_PATHS[locale],
        },
    )
    assert again.status_code == 400
    assert copy["next_title"] in _visible(again.text)


@pytest.mark.parametrize("locale", LOCALES)
def test_any_other_next_keeps_the_account_benefits(tmp_path: Path, locale: str) -> None:
    client = _client(_paid(tmp_path))
    copy = account_pages.COPY[locale]
    for query in ("", f"?next={account_pages.path('account', locale)}"):
        page = client.get(SIGNUP[locale] + query).text
        assert copy["next_title"] not in _visible(page)
        assert html.escape(copy["benefits"].split("|")[0]) in page


@pytest.mark.parametrize("locale", LOCALES)
def test_the_steps_come_from_the_configuration(tmp_path: Path, locale: str) -> None:
    copy = account_pages.COPY[locale]
    path = f"{SIGNUP[locale]}?next={AUDIT_PATHS[locale]}"
    confirmed = _client(_paid(tmp_path / "a", email_verification_required=True)).get(path).text
    steps = [_visible(step) for step in _steps(confirmed)]
    assert len(steps) == 4 and steps[1] == copy["next_confirm_welcome"]
    free = _client(_settings(tmp_path / "b")).get(path).text
    steps = [_visible(step) for step in _steps(free)]
    assert len(steps) == 3 and steps[2].endswith(copy["next_free_all"])
    free_confirmed = _client(_settings(tmp_path / "c", email_verification_required=True))
    steps = [_visible(step) for step in _steps(free_confirmed.get(path).text)]
    assert len(steps) == 4 and steps[1] == copy["next_confirm"]
    # Without a free first report the panel keeps the benefits.
    page = account_pages.signup_page(
        locale=locale, csrf="c", next_path=AUDIT_PATHS[locale], offer="paid"
    )
    assert copy["next_title"] not in _visible(page)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_confirmation_notice_points_to_the_export_guides(tmp_path: Path, locale: str) -> None:
    client = _client(_paid(tmp_path, **MAIL), base_url=SITE)
    form = client.get(SIGNUP[locale], params={"next": AUDIT_PATHS[locale]})
    steps = [_visible(step) for step in _steps(form.text)]
    assert steps[1] == account_pages.COPY[locale]["next_confirm_welcome"]
    done = client.post(
        SIGNUP[locale],
        data={
            "email": "ana@example.com",
            "password": PASSWORD,
            "csrf": _csrf(form.text),
            "next": AUDIT_PATHS[locale],
        },
        follow_redirects=False,
    )
    where = done.headers["location"]
    assert where == f"{AUDIT_PATHS[locale]}?done=welcome_confirm"
    copy = account_pages.COPY[locale]
    link = f"<a href='{guides_index_url(locale)}'>{html.escape(copy['welcome_confirm_guides'])}</a>"
    for target in (where, f"{account_pages.path('account', locale)}?done=welcome_confirm"):
        page = client.get(target)
        assert page.status_code == 200, target
        flashes = re.findall(r"<div class='flash'[^>]*>(.*?)</div>", page.text, re.S)
        notice = [text for text in flashes if copy["welcome_confirm"] in html.unescape(text)]
        assert len(notice) == 1, target
        assert link in notice[0], target
        assert find_claims(html.unescape(page.text)) == []
    assert _resolves(client, guides_index_url(locale))
    # Without a notice, the upload page shows no such link.
    assert link not in upload_page(locale=locale, free_mode=False)


# -- 4. Each article's next step --------------------------------------------------


def test_every_article_has_the_next_step_the_brief_assigns() -> None:
    assert set(ARTICLE_NEXT_STEPS) == set(EXPECTED_STEPS) == {a.key for a in ARTICLES}
    for article in ARTICLES:
        assert article.next_step == EXPECTED_STEPS[article.key], article.key


@pytest.fixture(scope="module")
def site(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    directory = tmp_path_factory.mktemp("conversion")
    return _client(_settings(directory))


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("key", sorted(EXPECTED_STEPS))
def test_the_next_step_is_the_side_button_and_the_closing_call(
    site: TestClient, key: str, locale: str
) -> None:
    article = ARTICLES_BY_KEY[key]
    response = site.get(article_url(key, locale))
    assert response.status_code == 200
    page = response.text
    steps = next_step_links(article, locale)
    label, href = steps[0]
    aside = _between(page, "<aside class='toc'", "</aside>")
    assert f"<a class='btn btn-dark btn-sm toc-cta' href='{html.escape(href)}'>" in aside
    assert html.escape(label) in aside
    close = _between(page, "<section class='article-cta'>", "</section>")
    title, text = next_step_call(article, locale)
    assert f"<h2>{html.escape(title)}</h2><p>{html.escape(text)}</p>" in close
    report = (ARTICLES_COPY[locale]["report"], AUDIT_PATHS[locale])
    expected = [link for _, link in steps]
    if report not in steps:
        expected.append(AUDIT_PATHS[locale])
    assert _hrefs(close) == expected
    assert f"<a class='btn btn-dark' href='{html.escape(href)}'>" in close
    assert find_claims(html.unescape(page)) == []
    for link in expected:
        assert _resolves(site, link), (key, locale, link)


@pytest.mark.parametrize("locale", LOCALES)
def test_the_calculators_open_with_the_articles_own_example(site: TestClient, locale: str) -> None:
    for key in ("sharpe-deflactado-track-record", "bot-ia-backtest-suerte"):
        href = next_step_links(ARTICLES_BY_KEY[key], locale)[0][1]
        assert urlsplit(href).path == CALCULATOR_PATH[locale]
        assert parse_qs(urlsplit(href).query) == {
            "sharpe": [f"{LUCK_EXAMPLE_INPUT.sharpe:g}"],
            "years": [f"{LUCK_EXAMPLE_INPUT.years:g}"],
            "trials": [str(LUCK_EXAMPLE_INPUT.trials)],
        }
        page = site.get(href).text
        for name in ("sharpe", "years", "trials"):
            value = parse_qs(urlsplit(href).query)[name][0]
            assert re.search(rf"id='c-{name}'[^>]*value='{re.escape(value)}'", page), name
    href = next_step_links(ARTICLES_BY_KEY["cuantas-operaciones-porcentaje-aciertos"], locale)[0][1]
    assert urlsplit(href).path == WINRATE_PATH[locale]
    query = parse_qs(urlsplit(href).query)
    assert query == {name: [WIN_RATE_EXAMPLE_VALUES[name]] for name in ("trades", "win_rate")}
    page = site.get(href)
    assert page.status_code == 200
    for name, (value,) in query.items():
        assert re.search(rf"id='w-{name}'[^>]*value='{value}'", page.text), name


@pytest.mark.parametrize("locale", LOCALES)
def test_the_form_link_of_an_article_goes_through_sign_up_outside_free_mode(
    tmp_path: Path, locale: str
) -> None:
    client = _client(_paid(tmp_path))
    page = client.get(article_url("backtest-costos-reales", locale)).text
    close = _between(page, "<section class='article-cta'>", "</section>")
    assert _hrefs(close) == [AUDIT_PATHS[locale]]
    first = client.get(AUDIT_PATHS[locale], follow_redirects=False)
    assert first.status_code == 303
    signup = client.get(first.headers["location"])
    assert signup.status_code == 200
    assert account_pages.COPY[locale]["next_title"] in _visible(signup.text)
