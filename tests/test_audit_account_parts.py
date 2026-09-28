""" "Mi cuenta" in four parts: fixed links, stable ids and a message that stays in view."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import (  # noqa: E402
    AccountEvent,
    AccountRecord,
    InviteSummary,
    PasskeyRecord,
    SessionView,
    make_store,
)
from quant_trade.audit.web import create_app  # noqa: E402

PARTS = ("informes", "creditos", "seguridad", "datos")
TITLES = {
    "es": ("Informes", "Créditos y compras", "Seguridad", "Tus datos"),
    "en": ("Reports", "Credits and purchases", "Security", "Your data"),
    "pt": ("Relatórios", "Créditos e compras", "Segurança", "Seus dados"),
}
ACCOUNT_PATHS = {"es": "/cuenta", "en": "/account", "pt": "/pt/conta"}
#: The ids that links, e-mails and redirects used before the page had parts.
OLD_IDS = {
    "informes": "informes",
    "estrategias": "informes",
    "invitar": "creditos",
    "verificar-correo": "seguridad",
    "proteccion": "seguridad",
    "recuperacion": "seguridad",
    "dos-pasos": "seguridad",
    "llaves": "seguridad",
    "sesiones": "seguridad",
    "actividad": "seguridad",
    "correo": "datos",
}
PART = re.compile(r"<section class='acct-part' id='([a-z]+)'")
HEADING = re.compile(r"<h([1-6])[ >]")
STAMP = "2026-09-27T10:00:00Z"
PASSWORD = "una frase larga y segura"


def _page(locale: str, **extra: object) -> str:
    values: dict[str, object] = dict(
        locale=locale,
        account=AccountRecord("a1", "ana@example.com", locale, STAMP),
        audits=(),
        codes=(),
        credits=2,
        csrf="test-csrf",
        now=STAMP,
        access_codes=True,
        contact_url="https://wa.me/000",
        price_cents=2900,
        pack_price_cents=6900,
        invite=account_pages.InviteView(
            link="https://example.test/registro?invita=abc12345",
            summary=InviteSummary(),
            credits=1,
            monthly_cap=5,
        ),
        sessions=(SessionView("h1", "Chrome en Windows", "203.0.113.0", STAMP, STAMP, True),),
        events=(AccountEvent("signin", "Chrome en Windows", "203.0.113.0", STAMP),),
        passkey_site="example.test",
        email_delivery_ready=True,
        email_verification_required=True,
    )
    values.update(extra)
    return account_pages.account_page(**values)  # type: ignore[arg-type]


def _parts(page: str) -> dict[str, str]:
    """Each part's HTML by id, in the order the page shows them."""
    found = list(PART.finditer(page))
    ends = [match.start() for match in found[1:]] + [len(page)]
    return {
        match.group(1): page[match.start() : end] for match, end in zip(found, ends, strict=True)
    }


@pytest.mark.parametrize("locale", account_pages.LANGUAGES)
def test_the_page_has_four_titled_parts_and_their_links(locale: str) -> None:
    page = _page(locale)
    parts = _parts(page)
    assert tuple(parts) == PARTS
    nav = page[page.index("<div class='acct-parts") :].split("</nav>")[0]
    label = account_pages.COPY[locale]["parts_label"]
    assert f"<nav aria-label='{label}'>" in nav
    assert re.findall(r"<a href='#([a-z]+)'>([^<]+)</a>", nav) == list(
        zip(PARTS, TITLES[locale], strict=True)
    )
    for anchor, title in zip(PARTS, TITLES[locale], strict=True):
        assert page.count(f"id='{anchor}'") == 1
        assert parts[anchor].startswith(
            f"<section class='acct-part' id='{anchor}' aria-labelledby='{anchor}-titulo'>"
            f"<h2 id='{anchor}-titulo'>{title}</h2>"
        )
    # The links come before the parts and need no script.
    assert page.index("<div class='acct-parts") < page.index("<section class='acct-part'")
    assert "<script" not in nav
    assert not find_claims(re.sub(r"<[^>]+>", " ", page))


@pytest.mark.parametrize("locale", account_pages.LANGUAGES)
def test_headings_go_down_one_level_at_a_time(locale: str) -> None:
    page = _page(locale)
    for anchor, html in _parts(page).items():
        levels = [int(level) for level in HEADING.findall(html.split("<footer")[0])]
        assert levels[0] == 2, anchor
        assert levels.count(2) == 1, anchor
        for before, after in zip(levels, levels[1:], strict=False):
            assert after <= before + 1, (anchor, levels)


@pytest.mark.parametrize("locale", account_pages.LANGUAGES)
def test_every_old_fragment_id_still_exists_in_its_part(locale: str) -> None:
    page = _page(locale)
    parts = _parts(page)
    for old, part in OLD_IDS.items():
        assert page.count(f"id='{old}'") == 1, old
        assert f"id='{old}'" in parts[part], (old, part)
    # The protection card keeps its id when nothing is left to turn on.
    protected = _page(
        locale,
        recovery_created=STAMP,
        two_step_since=STAMP,
        passkeys=(PasskeyRecord("c1", "Laptop", "example.test", STAMP, ""),),
    )
    assert protected.count("id='proteccion'") == 1
    assert "id='proteccion'" in _parts(protected)["seguridad"]


@pytest.mark.parametrize("locale", account_pages.LANGUAGES)
def test_each_block_is_in_the_part_where_a_customer_looks_for_it(locale: str) -> None:
    base = ACCOUNT_PATHS[locale]
    parts = _parts(_page(locale))
    where = {
        f"action='{base}/estrategias": None,
        f"action='{base}/codigo'": "creditos",
        "wa.me/000": "creditos",
        "id='invite-link'": "creditos",
        f"action='{base}/contrasena'": "seguridad",
        f"action='{base}/recuperacion'": "seguridad",
        f"action='{base}/dos-pasos'": "seguridad",
        f"action='{base}/llaves": "seguridad",
        f"action='{base}/verificar-correo'": "seguridad",
        f"action='{base}/sesiones": "seguridad",
        f"action='{base}/correo'": "datos",
        f"href='{base}/datos' download": "datos",
        f"action='{base}/borrar'": "datos",
    }
    for marker, part in where.items():
        if part is None:
            continue
        holders = [anchor for anchor, html in parts.items() if marker in html]
        assert holders == [part], (marker, holders)
    copy = account_pages.COPY[locale]
    assert copy["reports_title"] in parts["informes"]
    assert copy["purchases_title"] in parts["creditos"]
    assert copy["stores_title"] in parts["datos"]


@pytest.mark.parametrize("locale", account_pages.LANGUAGES)
def test_a_message_is_shown_with_the_links_that_follow_the_reader(locale: str) -> None:
    copy = account_pages.COPY[locale]
    for kind, key, role in (
        ("flash", "passkey_added", "status"),
        ("error", "wrong", "alert"),
        ("flash", "email_pending", "status"),
    ):
        page = _page(locale, **{kind: key})
        bar = page[page.index("<div class='acct-parts") : page.index("<section class='acct-part'")]
        assert bar.startswith("<div class='acct-parts has-alert'>")
        shown = f"<div class='{kind}' role='{role}'>"
        assert page.count(shown) == 1
        # Inside the bar that stays on screen, right after the four links.
        assert f"</nav>{shown}" in bar
        assert re.sub(r"<[^>]+>", "", bar.split(shown)[1]).startswith(
            re.sub(r"<[^>]+>", "", account_pages._e(copy[key]))
        )
    quiet = _page(locale)
    assert "<div class='acct-parts'>" in quiet and "has-alert" not in quiet.split("</style>")[-1]
    assert "role='alert'" not in quiet


def test_the_bar_sticks_below_the_top_bar_and_scrolls_sideways_on_a_phone() -> None:
    css = account_pages.ACCOUNT_CSS
    assert ".acct-parts{position:sticky;top:60px" in css
    assert ".acct-parts nav{display:flex;gap:4px;overflow-x:auto" in css
    assert "white-space:nowrap" in css.split(".acct-parts a{")[1].split("}")[0]
    # A block a redirect points to is not hidden under the two bars.
    assert ".acct-part,.acct-part [id]{scroll-margin-top:" in css
    assert ".acct-parts.has-alert~.acct-part" in css


def test_without_credits_buying_still_comes_before_the_reports() -> None:
    assert tuple(_parts(_page("es", credits=0))) == ("creditos", "informes", "seguridad", "datos")
    assert tuple(_parts(_page("es", credits=1))) == PARTS


def _signed_in(tmp_path: Path) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
    )
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    form = client.get("/registro").text
    match = re.search(r"name='csrf' value='([^']+)'", form)
    assert match
    client.post(
        "/registro",
        data={"email": "ana@example.com", "password": PASSWORD, "csrf": match.group(1)},
        follow_redirects=False,
    )
    return client


def test_a_redirect_to_an_old_fragment_lands_on_a_page_with_its_message(tmp_path: Path) -> None:
    client = _signed_in(tmp_path)
    page = client.get("/cuenta").text
    match = re.search(r"name='csrf' value='([^']+)'", page)
    assert match
    # A wrong password on "two-step" sends the browser to ``#dos-pasos``.
    refused = client.post(
        "/cuenta/dos-pasos",
        data={"csrf": match.group(1), "current": "otra frase equivocada"},
        follow_redirects=False,
    )
    assert refused.status_code == 303
    location = refused.headers["location"]
    assert location == "/cuenta?error=wrong#dos-pasos"
    landed = client.get(location.split("#")[0]).text
    bar = landed[
        landed.index("<div class='acct-parts") : landed.index("<section class='acct-part'")
    ]
    assert account_pages.COPY["es"]["wrong"] in bar and "role='alert'" in bar
    assert "id='dos-pasos'" in _parts(landed)["seguridad"]
    for locale, path in ACCOUNT_PATHS.items():
        shown = client.get(path).text
        assert tuple(sorted(_parts(shown))) == tuple(sorted(PARTS))
        for title in TITLES[locale]:
            assert f">{title}</a>" in shown and f">{title}</h2>" in shown
