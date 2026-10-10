"""The landing and /precios for someone about to pay for a challenge or a robot.

The first screen shows the headline and the button from the first paint, names the
price after the free report and never mentions a card; the landing stays short; the
pricing page shows cards instead of a table; every promise points at something the
service does today. Offline: TestClient and a SQLite file only.
"""

from __future__ import annotations

import html
import re
from dataclasses import replace
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import pages, paid_offer, theme  # noqa: E402
from quant_trade.audit.account_pages import COPY as ACCOUNT_COPY  # noqa: E402
from quant_trade.audit.account_pages import path as account_path  # noqa: E402
from quant_trade.audit.account_pages import report_box  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.institutional import REVIEW_PATHS  # noqa: E402
from quant_trade.audit.pages import (  # noqa: E402
    _COPY,
    _UI,
    AUDIT_PATHS,
    CONTACT_PATHS,
    FOUNDER_COPY,
    FOUNDER_PHOTO,
    FOUNDER_X_URL,
    OPERATOR_LINE,
    SAMPLE_PAGE_PATHS,
    _founder,
    _sample_url,
    landing,
)
from quant_trade.audit.pricing import PRICING_COPY, PRICING_PATH, pricing_page, usd  # noqa: E402
from quant_trade.audit.prop_presets import PRESETS  # noqa: E402
from quant_trade.audit.report import localize_tags  # noqa: E402
from quant_trade.audit.settings import PACK_CREDITS, AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.theme import MOTION  # noqa: E402
from quant_trade.audit.tools_hub import tools_url  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
HOMES = {"es": "/", "en": "/en", "pt": "/pt"}
CARD_WORDS = ("tarjeta", "card", "cartão")


def _settings(tmp_path: Path, **environ: str) -> AuditSettings:
    settings = AuditSettings.from_env(
        {
            "AUDIT_BASE_URL": BASE,
            "AUDIT_FREE_MODE": "false",
            "AUDIT_ACCESS_CODES": "true",
            "AUDIT_PUBLIC_DATA": "false",
            "AUDIT_SKIP_EMAIL_DNS": "true",
            "AUDIT_EMAIL_VERIFICATION_REQUIRED": "true",
            "STRIPE_SECRET_KEY": "sk_live_compra_test_only",
            "STRIPE_WEBHOOK_SECRET": "whsec_compra_test_only",
            "AUDIT_APPROVED_MARKETS": "MX,US",
            **environ,
        }
    )
    return replace(settings, database_url=f"sqlite:///{tmp_path}/compra.db")


def _client(settings: AuditSettings) -> TestClient:
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _text(fragment: str) -> str:
    fragment = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", fragment, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", fragment))


def _main(page: str) -> str:
    return page.split("<main id='main'>", 1)[1].split("</main>", 1)[0]


def _first_section(page: str) -> str:
    main = _main(page)
    return main[main.index("<section") : main.index("</section>") + len("</section>")]


def _paid_landing(locale: str, **extra: object) -> str:
    values: dict[str, object] = {
        "locale": locale,
        "free_mode": False,
        "price_usd": 29.0,
        "access_codes": True,
        "card_payments": True,
        "contact_url": "https://wa.me/000",
        "pack_price_usd": 75.0,
        "card_markets": ("MX", "US", "BR", "ES"),
        "completed_audits": 1234,
    }
    values.update(extra)
    return landing(**values)  # type: ignore[arg-type]


@pytest.fixture
def with_photo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A static folder holding the founder's photo (and the files the pages read)."""
    folder = tmp_path / "static"
    folder.mkdir()
    (folder / FOUNDER_PHOTO).write_bytes(b"\xff\xd8\xff\xe0 not a real photo")
    monkeypatch.setattr(theme, "STATIC_DIR", folder)
    return folder


@pytest.fixture
def without_photo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path / "static-empty"
    folder.mkdir()
    monkeypatch.setattr(theme, "STATIC_DIR", folder)
    return folder


@pytest.mark.parametrize("locale", sorted(HOMES))
def test_the_first_screen_names_the_price_and_never_a_card(tmp_path: Path, locale: str) -> None:
    settings = _settings(tmp_path, AUDIT_PRICE_USD_CENTS="2900")
    client = _client(settings)
    page = client.get(HOMES[locale]).text
    first = _first_section(page)
    assert "hero" in first.split(">", 1)[0]
    lowered = _text(first).lower()
    assert not any(word in lowered for word in CARD_WORDS)
    h1 = first[first.index("<h1") : first.index("</h1>")]
    assert "rise" not in h1 and "rise" not in first.split("<div class='stage", 1)[0]
    anchor = _UI[locale]["hero_anchor"].format(price="USD 29")
    assert anchor in html.unescape(first)
    assert html.escape(_UI[locale]["hero_safe"], quote=True) in first
    assert find_claims(_text(page)) == []
    # With cents the anchor keeps them; in free mode there is no price to anchor.
    cents = _client(replace(settings, price_usd_cents=1735)).get(HOMES[locale]).text
    assert _UI[locale]["hero_anchor"].format(price="USD 17.35") in html.unescape(cents)
    free = _client(replace(settings, free_mode=True)).get(HOMES[locale]).text
    assert "class='hero-anchor'" not in free
    assert "USD 29" not in _text(_first_section(free))


def test_the_anchor_needs_the_free_first_report() -> None:
    assert "class='hero-anchor'" in _paid_landing("es")
    assert "class='hero-anchor'" not in _paid_landing("es", price_usd=0.0)
    paid = paid_offer.Offer(kind="paid", price_usd=29.0)
    assert "class='hero-anchor'" not in _paid_landing("es", offer=paid)


@pytest.mark.parametrize("locale", sorted(HOMES))
def test_the_landing_is_short_and_keeps_its_ways_out(locale: str, with_photo: Path) -> None:
    page = _paid_landing(locale, operator=("Sergio Valle", "Ciudad de México"))
    main = _main(page)
    if locale == "es":
        assert len(_text(main).split()) <= 1300
    assert main.count("data-reveal") <= 25
    for href in (_sample_url(locale), tools_url(locale), PRICING_PATH[locale]):
        assert f"href='{href}" in main, href
    # Links shared as /#subir still land on the closing call, with its button.
    closing = main.split("id='subir'", 1)[1]
    assert f"href='{AUDIT_PATHS[locale]}'" in closing
    assert html.escape(_UI[locale]["final_tools"], quote=True) in closing
    footer = page.split("</main>", 1)[1]
    assert f"href='{REVIEW_PATHS[locale]}'" in footer
    # The blocks that left the first page.
    for gone in ("id='herramientas'", "id='measure'", "id='confianza'", "class='specs'"):
        assert gone not in main, gone
    assert "institutional" not in main
    assert find_claims(_text(page)) == []


@pytest.mark.parametrize("locale", sorted(HOMES))
def test_the_landing_asks_six_questions_and_links_the_rest(locale: str) -> None:
    from quant_trade.audit.faq import FAQ_PATH, faq_page

    page = _paid_landing(locale)
    faq = page.split("id='faq'", 1)[1].split("</section>", 1)[0]
    assert faq.count("<details>") == 6
    shown = {html.unescape(q) for q in re.findall(r"<summary>(.*?)</summary>", faq)}
    copy = _COPY[locale]["faq"]
    # What you get, which file, what happens to it, the evidence labels, no forecast
    # and no broker: the same six topics in every language.
    expected = {
        "es": (2, 0, 7, 4, 5, 6),
        "en": (2, 0, 7, 4, 5, 6),
        "pt": (2, 0, 8, 5, 6, 7),
    }[locale]
    assert shown == {localize_tags(copy[i][0], locale) for i in expected}
    assert f"href='{FAQ_PATH[locale]}'" in faq
    # What Rigor does not do is said here, with or without "who is behind it".
    assert html.escape(_COPY[locale]["not"], quote=True) in faq
    # The link leads to the rest: every other landing question is answered there,
    # so none of them is left off the site.
    rest = [pair for i, pair in enumerate(copy) if i not in expected]
    assert len(rest) == len(copy) - 6 >= 5
    questions = faq_page(AuditSettings(), locale=locale)
    for question, answer in rest:
        assert f"<summary>{html.escape(question, quote=True)}</summary>" in questions
        assert f"<p>{html.escape(answer, quote=True)}</p>" in questions


def test_the_landing_example_comes_right_after_the_first_screen() -> None:
    main = _main(_paid_landing("es"))
    sections = re.findall(r"<section[^>]*>", main)
    assert "hero" in sections[0] and "id='ejemplo'" in sections[1]
    example = main.split("id='ejemplo'", 1)[1].split("</section>", 1)[0]
    assert "Sharpe de 1.8 en el probador. Clase C en Rigor." in html.unescape(example)


@pytest.mark.parametrize("locale", sorted(HOMES))
def test_founder_block_shows_with_the_operator_and_the_photo(locale: str, with_photo: Path) -> None:
    block = _founder(locale, operator=("Sergio Valle", "México"), contact_url="")
    assert "Sergio Valle" in block
    assert f"href='{FOUNDER_X_URL}' rel='noopener me'" in block
    assert f"href='{CONTACT_PATHS[locale]}'" in block
    assert f"<img class='founder-photo' src='/static/{FOUNDER_PHOTO}'" in block
    assert "width='88' height='88'" in block and "alt='Sergio Valle'" in block
    assert html.escape(FOUNDER_COPY[locale]["title"], quote=True) in block
    assert find_claims(_text(block)) == []
    page = _paid_landing(locale, operator=("Sergio Valle", "México"))
    # After the prices, before the questions; the address goes with it.
    assert page.index("id='pricing'") < page.index("id='quien'") < page.index("id='faq'")
    assert "México · <a" in page.split("id='quien'", 1)[1].split("</section>", 1)[0]
    assert "class='muted faq-who'" not in page
    # Without an operator name nothing is shown, photo or not.
    assert _founder(locale, operator=("", "México"), contact_url="") == ""
    assert "id='quien'" not in _paid_landing(locale)


@pytest.mark.parametrize("locale", sorted(HOMES))
def test_without_the_photo_there_is_no_founder_block(locale: str, without_photo: Path) -> None:
    assert _founder(locale, operator=("Sergio Valle", "México"), contact_url="x") == ""
    page = _paid_landing(locale, operator=("Sergio Valle", "México"))
    assert "id='quien'" not in page and "<img" not in _main(page)
    assert FOUNDER_X_URL not in page
    text = FOUNDER_COPY[locale]["text"].format(name="Sergio Valle")
    assert html.escape(text, quote=True) not in page
    # The operator's name and address stay, in one plain line under the questions,
    # worded without the block's heading: "who is behind it" is nowhere on the page.
    faq = page.split("id='faq'", 1)[1].split("</section>", 1)[0]
    line = OPERATOR_LINE[locale].format(name="Sergio Valle", address="México")
    assert html.escape(line, quote=True) in faq
    title = FOUNDER_COPY[locale]["title"]
    assert not line.startswith(title) and title.lower() not in line.lower()
    free = _paid_landing(locale, free_mode=True, operator=("Sergio Valle", "México"))
    for shown in (page, free):
        assert title.lower() not in _text(shown).lower()
        assert find_claims(_text(shown)) == []
    assert "href='https://wa.me/000' rel='noopener'" in faq
    assert "wa.me" not in _paid_landing(locale, contact_url="").split("id='faq'", 1)[1]


@pytest.mark.parametrize("locale", sorted(HOMES))
def test_the_served_landing_without_the_photo_never_says_who_is_behind_it(
    tmp_path: Path, locale: str, without_photo: Path
) -> None:
    settings = _settings(
        tmp_path,
        AUDIT_OPERATOR_NAME="Sergio Valle",
        AUDIT_OPERATOR_ADDRESS="Ciudad de México, México",
        AUDIT_CONTACT_URL="https://wa.me/000",
    )
    for served in (settings, replace(settings, free_mode=True)):
        page = _client(served).get(HOMES[locale]).text
        assert "id='quien'" not in page
        assert FOUNDER_COPY[locale]["title"].lower() not in _text(page).lower()
        faq = page.split("id='faq'", 1)[1].split("</section>", 1)[0]
        assert "Sergio Valle" in _text(faq)


def test_the_repository_ships_no_founder_photo() -> None:
    # The founder adds the photo himself: no placeholder and no stock picture.
    assert not (theme.STATIC_DIR / FOUNDER_PHOTO).exists()
    assert "id='quien'" not in _paid_landing("es", operator=("Sergio Valle", "México"))


def test_the_photo_is_served_only_while_it_is_there(tmp_path: Path, with_photo: Path) -> None:
    client = _client(_settings(tmp_path))
    photo = client.get(f"/static/{FOUNDER_PHOTO}")
    assert photo.status_code == 200 and photo.headers["content-type"] == "image/jpeg"
    (with_photo / FOUNDER_PHOTO).unlink()
    assert client.get(f"/static/{FOUNDER_PHOTO}").status_code == 404
    assert client.get("/static/otra.jpg").status_code == 404


@pytest.mark.parametrize("locale", sorted(PRICING_PATH))
def test_pricing_shows_cards_with_the_settings_prices(tmp_path: Path, locale: str) -> None:
    for cents, pack in (("2900", "7500"), ("1735", "4155")):
        settings = _settings(tmp_path, AUDIT_PRICE_USD_CENTS=cents, AUDIT_PACK_PRICE_USD_CENTS=pack)
        page = _client(settings).get(PRICING_PATH[locale]).text
        main = _main(page)
        assert "<table" not in main and "overflow-x" not in main
        cards = re.findall(r"<div class='plan-card'>.*?</a></div>", main)
        assert len(cards) == 3
        prices = [usd(settings.price_usd), usd(settings.pack_price_usd)]
        assert prices[0] in cards[1] and prices[1] in cards[2]
        each = usd(settings.pack_price_usd / PACK_CREDITS)
        assert PRICING_COPY[locale]["pack_each"].format(each=each) in html.unescape(cards[2])
        for card in cards:
            assert re.findall(r"href='([^']*)'", card) == [AUDIT_PATHS[locale]]
        visible = _text(main)
        assert "DECLARED ·" not in visible and "Declarado ·" not in visible
        assert "Declared ·" not in visible
        assert find_claims(_text(page)) == []


@pytest.mark.parametrize("locale", sorted(PRICING_PATH))
def test_pricing_without_a_pack_shows_two_cards(locale: str) -> None:
    settings = AuditSettings.from_env(
        {"AUDIT_FREE_MODE": "false", "AUDIT_ACCESS_CODES": "true", "AUDIT_PUBLIC_DATA": "false"}
    )
    settings = replace(settings, pack_price_usd_cents=0)
    page = pricing_page(settings, locale=locale)
    assert page.count("<div class='plan-card'>") == 2
    assert html.escape(_COPY[locale]["price_full"], quote=True) in page


def test_money_drops_zero_cents_and_keeps_real_ones() -> None:
    assert usd(29) == "USD 29"
    assert usd(29.0) == "USD 29"
    assert usd(17.35) == "USD 17.35"
    assert usd(48.6) == "USD 48.60"
    assert usd(75 / 3) == "USD 25"


@pytest.mark.parametrize("locale", sorted(PRICING_PATH))
def test_one_list_says_what_every_full_report_includes(locale: str) -> None:
    from quant_trade.audit.report import DIMENSION_TITLES

    settings = AuditSettings.from_env(
        {"AUDIT_FREE_MODE": "false", "AUDIT_ACCESS_CODES": "true", "AUDIT_PUBLIC_DATA": "false"}
    )
    page = html.unescape(pricing_page(settings, locale=locale))
    words = PRICING_COPY[locale]
    listing = page.split(words["includes_title"], 1)[1].split("</ul>", 1)[0]
    for title in DIMENSION_TITLES[locale].values():
        assert title in listing
    for key in ("evidence_text", "optional", "compare_note"):
        assert words[key] in listing, key
    assert "PDF" in listing and words["support"] in listing
    assert listing.count("<li>") == len(DIMENSION_TITLES[locale]) + 5


def test_motion_never_blurs_and_the_hero_text_does_not_rise() -> None:
    assert "blur(" not in MOTION and "filter" not in MOTION
    assert "prefers-reduced-motion" in MOTION
    hero = pages._hero("es", SAMPLE_PAGE_PATHS["es"])
    assert hero.count(" rise") == 1 and "class='stage rise'" in hero


@pytest.mark.parametrize("locale", sorted(HOMES))
def test_the_full_report_lines_name_only_what_exists(locale: str) -> None:
    items = pages._full_items(locale)
    assert len(items) == 5
    firms = {rules.firm for rules in PRESETS.values() if rules.firm != "Generic"}
    # Three firms by name and how many others: the card does not grow with each firm.
    assert pages.challenge.firms_short(locale) in items[0]
    assert set(pages.challenge.NAMED_FIRMS) <= firms
    assert f" {len(firms) - len(pages.challenge.NAMED_FIRMS)} " in items[0]
    assert "{" not in " ".join(items)
    prices = _paid_landing(locale).split("id='pricing'", 1)[1].split("</section>", 1)[0]
    assert f"href='{_sample_url(locale)}'" in prices
    assert html.escape(_UI[locale]["full_more"], quote=True) in prices
    assert find_claims(" ".join(items)) == []


@pytest.mark.parametrize("locale", sorted(HOMES))
def test_comparing_with_the_previous_report_is_a_page_of_the_account(
    tmp_path: Path, locale: str
) -> None:
    # The price card says the account compares two reports side by side: that page
    # exists (it asks a visitor without a session to sign in) and the list offers it.
    client = _client(_settings(tmp_path))
    response = client.get(account_path("account", locale) + "/comparar", follow_redirects=False)
    assert response.status_code in (302, 303)
    assert ACCOUNT_COPY[locale if locale in ACCOUNT_COPY else "es"]["compare_button"]


@pytest.mark.parametrize("locale", sorted(HOMES))
def test_the_card_check_is_still_offered_where_it_is_asked(locale: str) -> None:
    # The first screen and the upload page no longer mention a card; the report box,
    # where a card check would free the first report, still says it is never charged.
    box = report_box(
        locale=locale, state="mine", audit_id="abc123", query="", locked=True, card_offer=True
    )
    assert html.escape(ACCOUNT_COPY[locale]["card_offer"], quote=True) in box
    assert "/tarjeta" in box
    sentences = {
        "es": "A veces pedimos validar una tarjeta",
        "en": "Sometimes we ask to verify a card",
        "pt": "Às vezes pedimos validar um cartão",
    }
    for point in _UI[locale]["upload_points"]:
        assert sentences[locale] not in point
