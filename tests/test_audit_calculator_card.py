"""The luck calculator's share card: figures from compute, cached, limited, cookieless."""

from __future__ import annotations

import html
import re
import socket
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from xml.etree import ElementTree as ET

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import funnel, public_card, raster, reading, reading_png  # noqa: E402
from quant_trade.audit.calculator import (
    # noqa: E402
    CALCULATOR_PATH,
    CARD_FIELDS,
    CARD_REQUESTS_PER_HOUR,
    COPY,
    CalculatorInput,
    calculator_copy,
    compute,
    parse_input,
    read_input,
    share_url,
    share_values,
)
from quant_trade.audit.calculator_card import calculator_card_svg  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
PAGES = tuple((CALCULATOR_PATH[locale], locale) for locale in LOCALES)
FORM = {"sharpe": "1.8", "years": "3", "trials": "100"}
#: Trial counts past float's range: ``int()`` overflows on them.
OVERFLOW = ("inf", "-inf", "1e999", "9" * 400)
CARD = {"sharpe": "1.8", "years": "3.0", "trials": "100", "periods_per_year": "252"}
MOCK_PNG = b"mocked PNG"
NS = {"s": "http://www.w3.org/2000/svg"}
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
#: Words the claims guard exists for; none may appear in the new copy.
BANNED = ("verificado", "certificado", "aprobado", "garantiza", "rentable")


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("quant_trade.audit.web.pdf_lib.available", lambda: False)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


@pytest.fixture
def renders(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each SVG handed to the renderer; the mock returns fixed PNG bytes."""
    calls: list[str] = []

    def render(svg: str) -> bytes:
        calls.append(svg)
        return MOCK_PNG

    monkeypatch.setattr(raster, "card_png", render)
    return calls


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, renders: list[str]) -> TestClient:
    return _client(tmp_path, monkeypatch)


def _meta(page: str, name: str) -> str:
    found = re.search(
        rf"<meta (?:property|name)=['\"]{re.escape(name)}['\"] content=['\"]([^'\"]*)",
        page,
    )
    assert found is not None, name
    return html.unescape(found.group(1))


def _visible(page: str) -> str:
    body = page.split("<main", 1)[1].split("</main>", 1)[0]
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)))


def _links(page: str) -> list[str]:
    return [html.unescape(link) for link in re.findall(r"href=['\"]([^'\"]+)['\"]", page)]


def _mark(text: str, locale: str) -> str:
    """``text`` written with a point, in the page's typography: a decimal comma (and a
    point between thousands) in es and pt, unchanged in en."""
    return text if locale == "en" else text.translate(str.maketrans({",": ".", ".": ","}))


def _figures(result: dict, locale: str) -> tuple[str, str, str, str]:
    return (
        _mark(f"{result['luck_sharpe']['value']:.2f}", locale),
        _mark(f"{result['sharpe_after']['value']:.2f}", locale),
        _mark(f"{result['haircut']['value']:.0%}", locale),
        _mark(f"{result['years_needed']['value']:.1f}", locale),
    )


def _parsed(*values: str) -> CalculatorInput:
    parsed = parse_input(*values)
    assert isinstance(parsed, CalculatorInput)
    return parsed


@pytest.mark.parametrize("locale", LOCALES)
def test_card_figures_come_from_compute(locale: str) -> None:
    value = CalculatorInput(1.8, 3.0, 100)
    r = compute(value)
    svg = calculator_card_svg(value, locale)
    root = ET.fromstring(svg)
    for key, figure in zip(
        ("luck_sharpe", "sharpe_after", "haircut", "years_needed"),
        _figures(r, locale),
        strict=True,
    ):
        assert figure in svg
        group = root.find(f".//s:g[@data-reading='{key}']", NS)
        assert group is not None, key
        assert figure in "".join(group.itertext())
    assert (root.attrib["width"], root.attrib["height"]) == ("1200", "675")
    assert root.attrib["viewBox"] == "0 0 1200 675"
    assert root.attrib[XML_LANG] == locale
    assert root.attrib["role"] == "img" and root.attrib["aria-labelledby"]
    evidence = {
        node.attrib["data-evidence"] for node in root.iter() if "data-evidence" in node.attrib
    }
    assert evidence == {"DECLARED", "NOT_MEASURED"}
    inputs = {
        node.attrib["data-field"]: " ".join(node.itertext())
        for node in root.iter()
        if "data-field" in node.attrib
    }
    assert set(inputs) == set(CARD_FIELDS)
    assert all("DECLARED" in shown for shown in inputs.values())
    assert inputs["sharpe"].endswith(_mark("1.8", locale))
    assert inputs["trials"].endswith("100")
    assert COPY[locale]["frequency_options"][252] in inputs["periods_per_year"]
    text = " ".join(root.itertext())
    assert find_claims(text) == []
    assert not re.search(r"\bMEASURED\b", svg)
    assert not re.search(r"\b(?:clase|class|classe)\s+[A-D]\b", text, flags=re.I)
    assert public_card.COPY[locale]["cta"] in text
    assert f"rigorscore.com{CALCULATOR_PATH[locale]}" in text
    assert COPY[locale]["beats"].format(n="100").split(".")[0] in " ".join(text.split())
    assert "href" not in svg and "<image" not in svg and "@import" not in svg


@pytest.mark.parametrize("locale", LOCALES)
def test_one_configuration_card_shows_the_what_if_rows(locale: str) -> None:
    value = CalculatorInput(1.9, 9 / 52, 1)
    result = compute(value)
    assert result["status"] == "MEASURED" and result["counted"] is False
    svg = calculator_card_svg(value, locale)
    root = ET.fromstring(svg)
    rows = root.findall(".//s:g[@data-reading='what_if']", NS)
    assert len(rows) == len(result["what_if"]) == 3
    for row, node in zip(result["what_if"], rows, strict=True):
        shown = "".join(node.itertext())
        luck = _mark(f"{row['luck_sharpe']['value']:.2f}", locale)
        assert luck in svg
        assert luck in shown
        assert _mark(f"{row['trials']:,}", locale) in shown
        assert _mark(f"{row['years_needed']['value']:.1f}", locale) in shown
        # A hypothetical count is neither measured nor declared: no evidence tag.
        assert node.get("data-evidence") is None and "DECLARED" not in shown
    assert root.find(".//s:g[@data-reading='sharpe_after']", NS) is None
    text = " ".join(root.itertext())
    assert find_claims(text) == []
    assert not re.search(r"\bMEASURED\b", svg)


def test_card_refuses_inputs_without_a_measured_result() -> None:
    value = _parsed("1", "0.1", "10", "12")  # two monthly returns: too short to discount
    assert compute(value)["status"] == "NOT_MEASURED"
    with pytest.raises(ValueError):
        calculator_card_svg(value, "es")
    with pytest.raises(ValueError):
        calculator_card_svg(CalculatorInput(1.8, 3.0, 100), "fr")


@pytest.mark.parametrize("locale", LOCALES)
def test_card_lines_fit(locale: str) -> None:
    limits = {"17": 48, "12": 76, "15": 120}
    values = (
        CalculatorInput(1.8, 3.0, 100),
        CalculatorInput(1.0, 2.0, 1000, 52.0),
        CalculatorInput(10.0, 50.0, 10_000_000, 12.0),
        CalculatorInput(0.05, 49.99, 9_999_999, 252.0),
        CalculatorInput(1.9, 9 / 52, 1),
    )
    for value in values:
        root = ET.fromstring(calculator_card_svg(value, locale))
        texts = root.findall(".//s:text", NS)
        assert texts
        for node in texts:
            line = node.text or ""
            limit = limits.get(node.attrib["font-size"])
            if limit is not None:
                assert len(line) <= limit, (node.attrib["font-size"], line)
            assert 0 < float(node.attrib["x"]) <= 1160
            assert 0 < float(node.attrib["y"]) < 675
            assert node.attrib["font-family"] == "Arial, sans-serif"


def test_share_values_reproduce_the_validated_input() -> None:
    assert share_values(_parsed(*FORM.values())) == CARD
    assert share_values(_parsed("1.80", "3", "100")) == CARD
    for value in (
        CalculatorInput(0.1 + 0.2, 1 / 3, 7, 52.0),
        CalculatorInput(9.999999999999998, 49.99, 10_000_000, 12.0),
    ):
        assert parse_input(*share_values(value).values()) == value
    url = share_url("pt", _parsed(*FORM.values()))
    assert url == "/pt/calculadora?" + urlencode({**CARD, "ref": "calculadora"})


@pytest.mark.parametrize("locale", LOCALES)
def test_new_copy_passes_the_guard_and_reuses_the_reader_notice(locale: str) -> None:
    words = COPY[locale]
    assert words["card_public"] == reading.COPY[locale]["public"]
    for key in ("share_title", "share_text", "card_title", "card_public"):
        assert find_claims(words[key]) == []
        assert not any(word in words[key].lower() for word in BANNED)
    assert "{url}" in words["share_text"]


def test_reader_cache_keeps_its_fields() -> None:
    assert reading_png.ReadingPNGCache()._fields == reading.FIELDS
    assert reading_png.ReadingPNGCache(fields=CARD_FIELDS)._fields == CARD_FIELDS


@pytest.mark.parametrize(("path", "locale"), PAGES)
def test_page_points_og_image_to_its_card(
    client: TestClient, renders: list[str], path: str, locale: str
) -> None:
    response = client.get(path, params=FORM)
    assert response.status_code == 200
    expected = BASE + path + "/card.png?" + urlencode(share_values(_parsed(*FORM.values())))
    assert expected.endswith("?sharpe=1.8&years=3.0&trials=100&periods_per_year=252")
    assert _meta(response.text, "og:image") == expected
    assert _meta(response.text, "twitter:image") == expected
    assert _meta(response.text, "og:image:width") == "1200"
    assert _meta(response.text, "og:image:height") == "630"
    # The canonical address stays the bare page, as before the card.
    assert f"<link rel='canonical' href='{BASE}{path}'>" in response.text
    # The page warmed the cache: the preview fetch renders nothing new.
    assert len(renders) == 1
    assert f'xml:lang="{locale}"' in renders[0]
    png = client.get(expected)
    assert png.status_code == 200 and png.content == MOCK_PNG
    assert len(renders) == 1


@pytest.mark.parametrize(("path", "locale"), PAGES)
def test_png_route_is_public_cacheable_and_cookieless(
    client: TestClient, renders: list[str], path: str, locale: str
) -> None:
    response = client.get(f"{path}/card.png?" + urlencode({**CARD, "ref": "x"}))
    assert response.status_code == 200
    assert response.content == MOCK_PNG
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "public, max-age=86400"
    assert "set-cookie" not in response.headers
    assert "content-disposition" not in response.headers
    again = client.get(f"{path}/card.png", params={**CARD, "sharpe": "1.80"})
    assert again.status_code == 200 and again.content == MOCK_PNG
    assert "set-cookie" not in again.headers
    # "1.8" and "1.80" are one validated input: the cache holds one card.
    assert len(renders) == 1
    root = ET.fromstring(renders[0])
    assert (root.attrib["width"], root.attrib["height"]) == ("1200", "630")
    card = root.find("s:svg", NS)
    assert card is not None and card.attrib[XML_LANG] == locale


@pytest.mark.parametrize("locale", LOCALES)
def test_png_route_rejects_bad_input(client: TestClient, locale: str) -> None:
    path = CALCULATOR_PATH[locale] + "/card.png"
    unmeasured = {"sharpe": "1", "years": "0.1", "trials": "10", "periods_per_year": "12"}
    assert isinstance(parse_input(*unmeasured.values()), CalculatorInput)
    invalid = (
        {},
        {"ref": "calculadora"},
        {**CARD, "sharpe": "0.01"},
        {**CARD, "years": "99"},
        {**CARD, "trials": "0"},
        {**CARD, "periods_per_year": "7"},
        {**CARD, "sharpe": "abc"},
        {**CARD, "sharpe": "nan"},
        {**CARD, "sharpe": "<script>alert(1)</script>"},
        {**CARD, "years": ""},
        *({**CARD, "trials": trials} for trials in OVERFLOW),
        unmeasured,
    )
    for params in invalid:
        response = client.get(path, params=params)
        assert response.status_code == 404, params
        assert response.content == b""
    for field in CARD_FIELDS:
        repeated = [*CARD.items(), (field, CARD[field])]
        response = client.get(path, params=repeated)
        assert response.status_code == 404, field
        assert response.content == b""


def test_png_limit_is_sixty_per_hour_and_page_never_429(
    client: TestClient, renders: list[str]
) -> None:
    assert CARD_REQUESTS_PER_HOUR == reading.MAX_REQUESTS_PER_HOUR == 60
    for _ in range(60):
        assert client.get("/calculadora/card.png", params=CARD).status_code == 200
    blocked = client.get("/calculadora/card.png", params=CARD)
    assert blocked.status_code == 429
    assert blocked.headers["retry-after"] == "3600"
    assert blocked.text == calculator_copy("es")["card_limited"]
    assert "public" not in blocked.headers.get("cache-control", "")
    for locale in ("en", "pt"):
        other = client.get(CALCULATOR_PATH[locale] + "/card.png", params=CARD)
        assert other.status_code == 429
        assert other.text == calculator_copy(locale)["card_limited"]
    page = client.get("/calculadora", params=FORM)
    assert page.status_code == 200
    assert _meta(page.text, "og:image") == f"{BASE}/static/og-es.png"
    assert "data-calc-verdict" in page.text
    for figure in _figures(compute(_parsed(*FORM.values())), "es"):
        assert figure in _visible(page.text)
    # The limit is per address, and the reader keeps its own.
    second_ip = TestClient(client.app, client=("192.0.2.2", 50000))
    assert second_ip.get("/calculadora/card.png", params=CARD).status_code == 200
    assert client.get("/lectura/card.png", params={"sharpe": "1.8"}).status_code == 200


@pytest.mark.parametrize("locale", LOCALES)
def test_render_failure_keeps_the_static_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, locale: str
) -> None:
    monkeypatch.setattr(raster, "card_png", lambda svg: None)
    client = _client(tmp_path, monkeypatch)
    path = CALCULATOR_PATH[locale]
    page = client.get(path, params=FORM)
    assert page.status_code == 200
    assert _meta(page.text, "og:image") == f"{BASE}/static/og-{locale}.png"
    assert "data-calc-verdict" in page.text
    # Sharing still works without the image; only the PNG download is gone.
    assert COPY[locale]["share_title"] in page.text
    assert reading.COPY[locale]["download_png"] not in _visible(page.text)
    response = client.get(path + "/card.png", params=CARD)
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == reading.COPY[locale]["png_unavailable"]
    assert "public" not in response.headers.get("cache-control", "")
    # A failed render is not cached: the next request can recover.
    monkeypatch.setattr(raster, "card_png", lambda svg: MOCK_PNG)
    assert client.get(path + "/card.png", params=CARD).content == MOCK_PNG


@pytest.mark.parametrize(("path", "locale"), PAGES)
def test_share_block_reproduces_the_result(client: TestClient, path: str, locale: str) -> None:
    page = client.get(path, params=FORM)
    assert page.status_code == 200
    shared = f"{BASE}{path}?sharpe=1.8&years=3.0&trials=100&periods_per_year=252&ref=calculadora"
    field = re.search(
        r"<textarea\b([^>]*\bid=['\"]calculator-share-text['\"][^>]*)>(.*?)</textarea>",
        page.text,
        flags=re.S,
    )
    assert field is not None and "readonly" in field.group(1)
    text = html.unescape(field.group(2))
    assert shared in text
    assert text == COPY[locale]["share_text"].format(url=shared)
    assert COPY[locale]["card_public"] in _visible(page.text)
    assert "data-copy='calculator-share-text'" in page.text
    links = _links(page.text)
    intent = next(link for link in links if link.startswith("https://x.com/intent/post?"))
    assert parse_qs(urlsplit(intent).query)["text"] == [text]
    assert any(link.startswith("https://wa.me/?text=") for link in links)
    telegram = next(link for link in links if link.startswith("https://t.me/share/url?url="))
    assert parse_qs(urlsplit(telegram).query)["url"] == [shared]
    for href in (intent, telegram):
        assert re.search(
            r"<a\b[^>]*href='" + re.escape(html.escape(href)) + r"'[^>]*rel='noopener noreferrer'",
            page.text,
        )
    png = BASE + path + "/card.png?" + urlencode(CARD)
    assert png.removeprefix(BASE) in links
    assert reading.COPY[locale]["download_png"] in _visible(page.text)
    assert find_claims(_visible(page.text)) == []
    # The shared link opens the same result, with the same four figures.
    repeated = client.get(shared.removeprefix(BASE))
    assert repeated.status_code == 200
    for figure in _figures(compute(_parsed(*FORM.values())), locale):
        assert figure in _visible(repeated.text)
    assert "calculadora" in funnel.REF_TAGS
    browser = TestClient(client.app)
    arrived = browser.get(shared.removeprefix(BASE))
    assert arrived.status_code == 200
    assert f"{funnel.REF_COOKIE}=calculadora" in arrived.headers.get("set-cookie", "")


@pytest.mark.parametrize(("path", "locale"), PAGES)
def test_empty_and_invalid_forms_have_no_share_or_dynamic_image(
    client: TestClient, renders: list[str], path: str, locale: str
) -> None:
    for params in (
        {},
        {"sharpe": "abc", "years": "3", "trials": "10"},
        {"sharpe": "1", "years": "0.1", "trials": "10", "periods_per_year": "12"},
        {**FORM, "periods_per_year": "7"},
        *({**FORM, "trials": trials} for trials in OVERFLOW),
    ):
        page = client.get(path, params=params)
        assert page.status_code == 200
        assert COPY[locale]["share_title"] not in page.text
        assert "data-public-share" not in page.text
        assert "/card.png" not in page.text
        assert _meta(page.text, "og:image") == f"{BASE}/static/og-{locale}.png"
    assert renders == []


def test_overflowing_trials_are_a_bad_number() -> None:
    # parse_input stays as it is; read_input turns int()'s OverflowError into
    # the same error a non-number gets, and passes everything else through.
    for trials in OVERFLOW:
        with pytest.raises(OverflowError):
            parse_input("1.8", "3", trials)
        assert read_input("1.8", "3", trials) == "error_number"
    for values in ((None, None, None), ("1,8", "3", "1,000", "52"), ("abc", "3", "10")):
        assert read_input(*values) == parse_input(*values)


@pytest.mark.parametrize(("path", "locale"), PAGES)
def test_overflowing_trials_show_the_number_error(
    client: TestClient, path: str, locale: str
) -> None:
    for trials in OVERFLOW:
        page = client.get(path, params={**FORM, "trials": trials})
        assert page.status_code == 200
        assert COPY[locale]["error_number"] in _visible(page.text)
        card = client.get(path + "/card.png", params={**CARD, "trials": trials})
        assert card.status_code == 404 and card.content == b""


def test_png_generation_uses_no_network_database_or_files(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("The calculator card must not use the database, network, files or visits")

    store = client.app.state.store
    monkeypatch.setattr(store.engine, "begin", forbidden)
    monkeypatch.setattr(store.engine, "connect", forbidden)
    monkeypatch.setattr(client.app.state.visits, "add", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    preview = {"user-agent": "Twitterbot/1.0"}
    for locale in LOCALES:
        path = CALCULATOR_PATH[locale]
        page = client.get(path, params={**FORM, "ref": "calculadora"}, headers=preview)
        assert page.status_code == 200
        image = _meta(page.text, "og:image")
        assert urlsplit(image).path == path + "/card.png"
        response = client.get(image.removeprefix(BASE) + "&ref=calculadora", headers=preview)
        assert response.status_code == 200
        assert response.content == MOCK_PNG
    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_card_limit_message_speaks_of_calculator_cards(locale: str) -> None:
    from quant_trade.audit.calculator import calculator_copy

    words = calculator_copy(locale)["card_limited"]
    assert find_claims(words) == []
    assert {"es": "calculadora", "en": "calculator", "pt": "calculadora"}[locale] in words
    assert "lectura" not in words.lower() and "reading" not in words.lower()
