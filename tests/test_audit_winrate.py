"""The free win-rate calculator: the reader's Wilson interval and break-even, in three languages."""

from __future__ import annotations

import html
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import funnel, owner_card, raster, reading, winrate  # noqa: E402
from quant_trade.audit.articles import _num, article_url, win_rate_interval  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.public_card import (  # noqa: E402
    PublicClaim,
    _wilson,
    breakeven_rate,
    public_card_svg,
)
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402
from quant_trade.audit.winrate import TABLE_TRADES, WINRATE_PATH, read  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
BROWSER = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0"}
FIGURES = {"trades": "40", "win_rate": "60", "target_r": "1.5", "stop_r": "1"}


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("quant_trade.audit.web.pdf_lib.available", lambda: False)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _visible(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _links(page: str) -> list[str]:
    return [html.unescape(value) for value in re.findall(r"\bhref=['\"]([^'\"]*)", page)]


def _meta(page: str, prop: str) -> str:
    found = re.search(rf"<meta property='{re.escape(prop)}' content='([^']*)'>", page)
    assert found is not None, prop
    return html.unescape(found.group(1))


def _textarea(page: str, ident: str) -> str:
    found = re.search(rf"<textarea\b[^>]*\bid='{ident}'[^>]*>(.*?)</textarea>", page, flags=re.S)
    assert found is not None, ident
    return html.unescape(found.group(1))


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _strings(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _strings(item)]
    return []


def test_breakeven_rate_is_the_reader_expression() -> None:
    assert breakeven_rate(1.5, 1) == 0.4
    assert breakeven_rate(1, 1) == 0.5
    assert "40.0 %" in public_card_svg(PublicClaim(target_r=1.5, stop_r=1))


def test_read_uses_repository_functions() -> None:
    claim = PublicClaim(trades=40, win_rate=0.60, target_r=1.5, stop_r=1)
    result = read(claim)
    assert result.interval == _wilson(0.6, 40)
    assert result.breakeven == breakeven_rate(1.5, 1)
    assert result.position == "above"
    assert result.trades_needed == 30
    assert result.never is False
    assert result.rows == tuple((n, _wilson(0.6, n)) for n in TABLE_TRADES)


def test_inside_and_never_cases() -> None:
    inside = read(PublicClaim(trades=100, win_rate=0.55, target_r=1, stop_r=1))
    assert inside.position == "inside"
    assert inside.trades_needed == 500
    below = read(PublicClaim(trades=1000, win_rate=0.40, target_r=1, stop_r=1))
    assert below.position == "below"
    assert below.never is True
    assert below.trades_needed is None
    # Missing inputs stay absent instead of being invented.
    empty = read(PublicClaim())
    assert (empty.interval, empty.breakeven, empty.position, empty.rows) == (None, None, None, ())
    assert empty.trades_needed is None and empty.never is False


def test_page_shows_the_figures_in_each_language(client: TestClient) -> None:
    claim = PublicClaim(trades=40, win_rate=0.60, target_r=1.5, stop_r=1)
    result = read(claim)
    assert result.breakeven is not None and result.trades_needed is not None
    for locale in LOCALES:
        response = client.get(WINRATE_PATH[locale], params=FIGURES)
        assert response.status_code == 200
        text = _visible(response.text)
        assert win_rate_interval(0.6, 40, locale) in text
        assert f"{_num(result.breakeven * 100, locale, 1)} %" in text
        assert _num(result.trades_needed, locale, 0) in text
        for trades in TABLE_TRADES:
            assert win_rate_interval(0.6, trades, locale) in text
        words = winrate.COPY[locale]
        assert words["above"] in text
        needed = words["needed"].format(
            rate=f"{_num(0.6 * 100, locale, 1)} %", n=_num(result.trades_needed, locale, 0)
        )
        assert needed in text
        assert "data-winrate-position" in response.text
        assert "class='flash'" in response.text
        assert find_claims(text) == []
    # The formats themselves, checked once by hand.
    es = _visible(client.get(WINRATE_PATH["es"], params=FIGURES).text)
    assert "44,6–73,7 %" in es and "40,0 %" in es and "30" in es
    en = _visible(client.get(WINRATE_PATH["en"], params=FIGURES).text)
    assert "44.6–73.7 %" in en and "40.0 %" in en
    pt = _visible(client.get(WINRATE_PATH["pt"], params=FIGURES).text)
    assert "44,6–73,7 %" in pt


def test_missing_inputs_are_not_measured(client: TestClient) -> None:
    from quant_trade.audit.public_card import COPY as CARD_COPY

    response = client.get(WINRATE_PATH["es"], params={"win_rate": "55", "trades": ""})
    assert response.status_code == 200
    text = _visible(response.text)
    assert CARD_COPY["es"]["wilson_missing"] in text
    assert CARD_COPY["es"]["breakeven_missing"] in text
    assert "badge NOT_MEASURED" in response.text
    # The rate alone still fills the table of sample sizes.
    for trades in TABLE_TRADES:
        assert win_rate_interval(0.55, trades, "es") in text
    assert "data-winrate-position" not in response.text
    assert "data-winrate-needed" not in response.text
    # The share text names the interval and the break-even: never offered without both.
    partial = (
        {"win_rate": "55"},
        {"target_r": "2", "stop_r": "1"},
        {"trades": "40", "win_rate": "60"},
        {"trades": "40", "target_r": "1.5", "stop_r": "1"},
    )
    for locale in LOCALES:
        for params in partial:
            page = client.get(WINRATE_PATH[locale], params=params)
            assert page.status_code == 200, (locale, params)
            assert "badge NOT_MEASURED" in page.text, (locale, params)
            assert "winrate-share-text" not in page.text, (locale, params)
            assert "winrate-share-link" not in page.text, (locale, params)
            assert "data-public-share" not in page.text, (locale, params)
            assert not any(
                href.startswith("https://x.com/intent/") for href in _links(page.text)
            ), (locale, params)
            # The reader's card, which shows NOT_MEASURED itself, stays linked.
            assert "data-winrate-card" in page.text, (locale, params)


@pytest.mark.parametrize("locale", LOCALES)
def test_needed_sentence_never_contradicts_a_sample_already_above(
    client: TestClient, locale: str
) -> None:
    # 25 declared trades already clear break-even; the grid's first size that does is 30.
    figures = {"trades": "25", "win_rate": "60", "target_r": "1.5", "stop_r": "1"}
    result = read(PublicClaim(trades=25, win_rate=0.60, target_r=1.5, stop_r=1))
    assert result.position == "above"
    assert result.trades_needed is not None and result.trades_needed > 25
    response = client.get(WINRATE_PATH[locale], params=figures)
    assert response.status_code == 200
    words = winrate.COPY[locale]
    text = _visible(response.text)
    assert words["above"] in text
    assert "data-winrate-needed" not in response.text
    assert find_claims(text) == []
    # With 40 trades the grid's 30 is below the sample: the sentence agrees and stays.
    assert "data-winrate-needed" in client.get(WINRATE_PATH[locale], params=FIGURES).text


def test_needed_sentence_rule_over_a_sweep() -> None:
    from quant_trade.audit.pages import _winrate_result

    shown = 0
    for trades in (*range(2, 60), 99, 150, 10_000_000):
        for rate in (0.55, 0.60, 0.65, 0.70, 0.401):
            for target in (1.0, 1.5, 3.0):
                claim = PublicClaim(trades=trades, win_rate=rate, target_r=target, stop_r=1)
                figures = read(claim)
                body, _ = _winrate_result(claim, {}, "es", BASE)
                if "data-winrate-needed" not in body:
                    # Only skipped when the declared sample already clears break-even.
                    assert figures.position == "above", (trades, rate, target)
                    assert figures.trades_needed is None or figures.trades_needed > trades
                    continue
                shown += 1
                if figures.position == "above":
                    assert figures.trades_needed is not None
                    assert figures.trades_needed <= trades, (trades, rate, target)
                elif figures.position == "inside" and figures.trades_needed is not None:
                    assert figures.trades_needed > trades, (trades, rate, target)
    assert shown > 0


@pytest.mark.parametrize("locale", LOCALES)
def test_empty_page_is_indexable_and_has_the_breakeven_table(
    client: TestClient, locale: str
) -> None:
    path = WINRATE_PATH[locale]
    response = client.get(path)
    assert response.status_code == 200
    assert "x-robots-tag" not in response.headers
    assert "<meta name='robots' content='index, follow'>" in response.text
    assert f"<link rel='canonical' href='{BASE}{path}'>" in response.text
    text = _visible(response.text)
    assert f"{_num(breakeven_rate(2.0, 1.0) * 100, locale, 1)} %" in text
    if locale == "en":
        assert "33.3 %" in text
    else:
        assert "33,3 %" in text and "25,0 %" in text
    words = winrate.COPY[locale]
    assert f"{html.escape(words['result_title'])}</h2>" not in response.text
    assert f"{html.escape(words['table_title'])}</h2>" not in response.text
    assert "winrate-share-text" not in response.text
    assert response.text.count("<h1") == 1


@pytest.mark.parametrize("locale", LOCALES)
def test_invalid_inputs_return_localized_400(client: TestClient, locale: str) -> None:
    path = WINRATE_PATH[locale]
    cases = (
        ({**FIGURES, "win_rate": "150"}, "rate_error"),
        ({**FIGURES, "trades": "abc"}, "counts"),
        ([("trades", "40"), ("trades", "41")], "invalid"),
        ({**FIGURES, "stop_r": "0"}, "positive"),
    )
    for params, code in cases:
        response = client.get(path, params=params)
        assert response.status_code == 400, (params, response.status_code)
        assert owner_card.COPY[locale][code] in _visible(response.text)
        assert "<p class='error' role='alert'>" in response.text
        assert find_claims(_visible(response.text)) == []
        # A rejected value is never echoed back into the form.
        assert "value='150'" not in response.text and "value='abc'" not in response.text


def test_share_link_reproduces_inputs_and_is_tagged(client: TestClient) -> None:
    response = client.get(WINRATE_PATH["es"], params=FIGURES)
    shared = f"{BASE}/calculadora-aciertos?trades=40&win_rate=60&target_r=1.5&stop_r=1&ref=aciertos"
    assert _textarea(response.text, "winrate-share-text").endswith(shared)
    assert _textarea(response.text, "winrate-share-link") == shared
    assert any(href.startswith("https://x.com/intent/post?") for href in _links(response.text))
    assert "aciertos" in funnel.REF_TAGS
    browser = TestClient(client.app, headers=BROWSER)
    again = browser.get(shared)
    assert again.status_code == 200
    assert win_rate_interval(0.6, 40, "es") in _visible(again.text)
    assert "40,0 %" in _visible(again.text)
    assert any(
        cookie.startswith(f"{funnel.REF_COOKIE}=aciertos")
        for cookie in again.headers.get_list("set-cookie")
    )


def test_card_link_and_og_image_reuse_the_reader_card(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(raster, "card_png", lambda svg: b"png")
    response = client.get(WINRATE_PATH["es"], params=FIGURES)
    image = _meta(response.text, "og:image")
    assert image.startswith(f"{BASE}/lectura/card.png?")
    assert "trades=40" in image and "ref=" not in image
    card = reading.reading_url("es", {name: FIGURES.get(name, "") for name in reading.FIELDS})
    assert card in _links(response.text)
    # The reader's own card route answers that address.
    assert client.get(image.removeprefix(BASE)).status_code == 200
    monkeypatch.setattr(raster, "card_png", lambda svg: None)
    response = client.get(WINRATE_PATH["es"], params=FIGURES)
    assert _meta(response.text, "og:image") == f"{BASE}/static/og-es.png"
    assert card in _links(response.text)
    empty = client.get(WINRATE_PATH["es"])
    assert _meta(empty.text, "og:image") == f"{BASE}/static/og-es.png"


@pytest.mark.parametrize("locale", LOCALES)
def test_metadata_json_ld_and_guard(client: TestClient, locale: str) -> None:
    response = client.get(WINRATE_PATH[locale], params=FIGURES)
    page = response.text
    for lang, path in WINRATE_PATH.items():
        assert f"hreflang='{lang}' href='{BASE}{path}'" in page
    assert f"hreflang='x-default' href='{BASE}{WINRATE_PATH['es']}'" in page
    blocks = re.findall(r"<script type='application/ld\+json'>(.*?)</script>", page, flags=re.S)
    data = [json.loads(block) for block in blocks]
    app = next(item for item in data if item.get("@type") == "WebApplication")
    assert app["url"] == BASE + WINRATE_PATH[locale]
    assert app["inLanguage"] == locale
    assert app["isAccessibleForFree"] is True
    assert app["offers"]["price"] == "0"
    title = f"{winrate.COPY[locale]['seo_title']} · Rigor"
    assert f"<title>{html.escape(title)}</title>" in page
    assert len(title) <= 65
    assert 50 <= len(winrate.COPY[locale]["summary"]) <= 160
    assert find_claims(html.unescape(page)) == []
    assert find_claims(_visible(page)) == []
    for text in _strings(winrate.COPY[locale]):
        assert find_claims(text) == [], text
    if locale == "pt":
        visible = _visible(page)
        for word in ("informe", "archivo", "Sube "):
            assert word not in visible, word
            for text in _strings(winrate.COPY["pt"]):
                assert word not in text, (word, text)


@pytest.mark.parametrize("locale", LOCALES)
def test_articles_link_the_calculator(client: TestClient, locale: str) -> None:
    for key in ("cuantas-operaciones-porcentaje-aciertos", "cuantos-intentos-reto-prop-firm"):
        response = client.get(article_url(key, locale))
        assert response.status_code == 200
        assert WINRATE_PATH[locale] in _links(response.text), (key, locale)


def test_winrate_visits_count(tmp_path: Path) -> None:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db")
    client = TestClient(create_app(settings, make_store(settings.database_url)), headers=BROWSER)

    def browser() -> TestClient:
        return TestClient(client.app, headers=BROWSER)

    tagged = browser().get(WINRATE_PATH["es"] + "?ref=aciertos")
    assert tagged.cookies.get(funnel.REF_COOKIE) == "aciertos"
    assert browser().get(WINRATE_PATH["en"]).status_code == 200
    assert browser().get(WINRATE_PATH["pt"], params=FIGURES).status_code == 200
    client.app.state.visits.flush()  # type: ignore[attr-defined]
    day = funnel.day_of(datetime.now(UTC))
    rows = client.app.state.store.funnel_events(day)["visits"]  # type: ignore[attr-defined]
    counts = {(locale, ref): count for _, locale, ref, count in rows}
    assert counts == {("es", "aciertos"): 1, ("en", ""): 1, ("pt", ""): 1}
