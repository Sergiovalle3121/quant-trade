"""The luck calculator's figures in each language's typography: a decimal comma in es
and pt, a point in en, on the page and on its share card. The values stay
``compute``'s and the share link and ``card.png`` keep their point parameters."""

from __future__ import annotations

import html
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from xml.etree import ElementTree as ET

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import raster  # noqa: E402
from quant_trade.audit.calculator import (  # noqa: E402
    CALCULATOR_PATH,
    COPY,
    SHARPE_RANGE,
    TRIALS_RANGE,
    YEARS_RANGE,
    CalculatorInput,
    compute,
    parse_input,
    share_values,
)
from quant_trade.audit.calculator_card import calculator_card_svg  # noqa: E402
from quant_trade.audit.examples import EXAMPLES, example_calculator_url  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.public_card import _num  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

BASE = "https://audit.example"
LOCALES = ("es", "en", "pt")
MOCK_PNG = b"mocked PNG"
NS = {"s": "http://www.w3.org/2000/svg"}
#: Counted results (one past a thousand years needed) and two single-configuration
#: cases, whose page and card show the "what if" table instead.
COUNTED = (
    CalculatorInput(1.8, 3.0, 100),
    CalculatorInput(1.0, 2.0, 1000),
    CalculatorInput(2.5, 0.75, 20, 52.0),
    CalculatorInput(0.05, 49.99, 9_999_999),
)
ONE_TRIAL = (CalculatorInput(1.9, 9 / 52, 1), CalculatorInput(0.8, 10.0, 1, 12.0))
CASES = COUNTED + ONE_TRIAL
#: A number written with a point as decimal mark, and one written with a comma.
POINT_DECIMAL = re.compile(r"(?<![\d.,])\d+\.\d{1,2}(?![\d.,])")
COMMA_DECIMAL = re.compile(r"(?<![\d.,])\d+,\d{1,2}(?![\d.,])")


def _mark(text: str, locale: str) -> str:
    """``text`` written with a point, in the page's typography (written here on its own,
    not with the code under test): unchanged in en, comma and point swapped in es/pt."""
    return text if locale == "en" else text.translate(str.maketrans({",": ".", ".": ","}))


def _value(text: str, locale: str) -> float:
    """A shown figure read back as a number."""
    if locale != "en":
        text = text.replace(".", "").replace(",", ".")
    return float(text.replace(",", "").removesuffix("%"))


def _expected_counted(result: dict, locale: str) -> dict[str, str]:
    return {
        "luck_sharpe": _mark(f"{result['luck_sharpe']['value']:,.2f}", locale),
        "sharpe_after": _mark(f"{result['sharpe_after']['value']:,.2f}", locale),
        "haircut": _mark(f"{result['haircut']['value']:.0%}", locale),
        "years_needed": _mark(f"{result['years_needed']['value']:,.1f}", locale),
    }


def _expected_rows(result: dict, locale: str) -> list[tuple[str, str, str]]:
    return [
        (
            _mark(f"{row['trials']:,}", locale),
            _mark(f"{row['luck_sharpe']['value']:.2f}", locale),
            _mark(f"{row['years_needed']['value']:,.1f}", locale),
        )
        for row in result["what_if"]
    ]


def _visible(fragment: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fragment))).strip()


def _cells(table: str) -> list[list[str]]:
    rows = re.findall(r"<tr>(.*?)</tr>", table, flags=re.S)
    return [[_visible(cell) for cell in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r)] for r in rows]


def _result_section(page: str, locale: str) -> str:
    """The verdict and figures table, or the single-configuration sentence and its table."""
    one_trial = re.escape(f"<p>{html.escape(COPY[locale]['one_trial'])}</p>")
    verdict = r"<p class='(?:flash|warning)' data-calc-verdict>.*?</table>"
    found = re.search(rf"{verdict}|{one_trial}<table>.*?</table>", page, flags=re.S)
    assert found is not None
    return found.group(0)


def _case_id(value: CalculatorInput) -> str:
    return f"{value.sharpe:g}-{value.years:.3g}-{value.trials}-{value.periods_per_year:g}"


@pytest.fixture
def renders(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Each SVG handed to the PNG renderer; the mock returns fixed bytes."""
    calls: list[str] = []

    def render(svg: str) -> bytes:
        calls.append(svg)
        return MOCK_PNG

    monkeypatch.setattr(raster, "card_png", render)
    return calls


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, renders: list[str]) -> TestClient:
    monkeypatch.setattr("quant_trade.audit.web.pdf_lib.available", lambda: False)
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", base_url=BASE)
    return TestClient(create_app(settings, make_store(settings.database_url)))


def test_cases_cover_counted_and_single_configuration_results() -> None:
    for value in CASES:
        assert compute(value)["status"] == "MEASURED"
    assert all(compute(value)["counted"] for value in COUNTED)
    assert not any(compute(value)["counted"] for value in ONE_TRIAL)
    # One case needs more than a thousand years: its figure groups the thousands.
    assert compute(COUNTED[-1])["years_needed"]["value"] > 1000


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("value", CASES, ids=_case_id)
def test_page_figures_use_the_languages_decimal_mark(
    client: TestClient, locale: str, value: CalculatorInput
) -> None:
    result = compute(value)
    response = client.get(CALCULATOR_PATH[locale], params=share_values(value))
    assert response.status_code == 200
    section = _result_section(response.text, locale)
    count = _mark(f"{value.trials:,}", locale)
    if result["counted"]:
        expected = _expected_counted(result, locale)
        cells = _cells(section)
        assert [row[1] for row in cells] == list(expected.values())
        assert cells[0][0] == COPY[locale]["luck"].format(n=count)
        verdict = COPY[locale]["beats" if result["beats_luck"] else "loses"].format(n=count)
        assert html.escape(verdict) in section
        for key, shown in expected.items():
            digits = 0 if key == "haircut" else 1 if key == "years_needed" else 2
            scale = 100 if key == "haircut" else 1
            assert _value(shown, locale) == round(result[key]["value"] * scale, digits)
    else:
        assert html.escape(COPY[locale]["one_trial"]) in section
        rows = [tuple(row) for row in _cells(section)[1:]]
        assert rows == _expected_rows(result, locale)
        for (trials, luck, years), row in zip(rows, result["what_if"], strict=True):
            assert _value(trials, locale) == row["trials"]
            assert _value(luck, locale) == round(row["luck_sharpe"]["value"], 2)
            assert _value(years, locale) == round(row["years_needed"]["value"], 1)
    figures = _visible(section)
    wrong = POINT_DECIMAL if locale != "en" else COMMA_DECIMAL
    assert wrong.findall(figures) == []
    main = response.text.split("<main", 1)[1].split("</main>", 1)[0]
    assert find_claims(_visible(main)) == []


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("value", CASES, ids=_case_id)
def test_card_figures_use_the_languages_decimal_mark(locale: str, value: CalculatorInput) -> None:
    result = compute(value)
    root = ET.fromstring(calculator_card_svg(value, locale))
    inputs = {
        node.attrib["data-field"]: " ".join(node.itertext())
        for node in root.iter()
        if "data-field" in node.attrib
    }
    assert inputs["sharpe"].endswith(" " + _mark(f"{value.sharpe:g}", locale))
    assert inputs["years"].endswith(" " + _mark(f"{value.years:g}", locale))
    assert inputs["trials"].endswith(" " + _mark(f"{value.trials:,}", locale))
    if result["counted"]:
        for key, shown in _expected_counted(result, locale).items():
            group = root.find(f".//s:g[@data-reading='{key}']", NS)
            assert group is not None, key
            texts = [node.text for node in group.findall("s:text", NS)]
            assert texts[-1] == shown
    else:
        nodes = root.findall(".//s:g[@data-reading='what_if']", NS)
        words = COPY[locale]
        for (trials, luck, years), node in zip(_expected_rows(result, locale), nodes, strict=True):
            line = "".join(node.itertext())
            assert line == (
                f"{words['col_trials']} {trials} · {words['col_luck']} {luck} · "
                f"{words['col_years']} {years}"
            )
    numbers = " ".join(
        text
        for key in ("luck_sharpe", "sharpe_after", "haircut", "years_needed", "what_if")
        for group in root.findall(f".//s:g[@data-reading='{key}']", NS)
        for text in group.itertext()
    )
    wrong = POINT_DECIMAL if locale != "en" else COMMA_DECIMAL
    assert wrong.findall(numbers) == []
    assert find_claims(" ".join(root.itertext())) == []


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("value", (COUNTED[0], ONE_TRIAL[0]), ids=("counted", "one-trial"))
def test_png_card_keeps_point_parameters_and_one_cache_key(
    client: TestClient, renders: list[str], locale: str, value: CalculatorInput
) -> None:
    path = CALCULATOR_PATH[locale]
    page = client.get(path, params=share_values(value))
    assert page.status_code == 200
    found = re.search(r"<meta property=['\"]og:image['\"] content=['\"]([^'\"]*)", page.text)
    assert found is not None
    image = html.unescape(found.group(1))
    # The address keeps the point: it is the validated input, not a figure to read.
    assert image == BASE + path + "/card.png?" + urlencode(share_values(value))
    assert parse_qs(urlsplit(image).query)["sharpe"] == [repr(value.sharpe)]
    assert parse_input(*(parse_qs(urlsplit(image).query)[k][0] for k in share_values(value)))
    assert len(renders) == 1
    # The SVG the PNG renderer receives (the mock) carries the card's own figures.
    texts = [node.text for node in ET.fromstring(renders[0]).iter(f"{{{NS['s']}}}text")]
    result = compute(value)
    if result["counted"]:
        for shown in _expected_counted(result, locale).values():
            assert shown in texts
    else:
        words = COPY[locale]
        for trials, luck, years in _expected_rows(result, locale):
            assert (
                f"{words['col_trials']} {trials} · {words['col_luck']} {luck} · "
                f"{words['col_years']} {years}"
            ) in texts
    # The same card behind the preview and a padded copy of the input: no new render.
    assert client.get(image.removeprefix(BASE)).content == MOCK_PNG
    padded = {**share_values(value), "sharpe": repr(value.sharpe) + "0"}
    assert client.get(path + "/card.png", params=padded).content == MOCK_PNG
    assert len(renders) == 1


@pytest.mark.parametrize("locale", LOCALES)
def test_help_and_error_figures_follow_the_language(locale: str) -> None:
    words = COPY[locale]
    low, high = SHARPE_RANGE
    assert f"{_num(low, locale, 2)} " in words["error_sharpe"]
    assert f" {_num(high, locale, 0)}." in words["error_sharpe"]
    low, high = YEARS_RANGE
    assert f"{_num(low, locale, 1)} " in words["error_years"]
    assert f" {_num(high, locale, 0)}." in words["error_years"]
    assert words["error_trials"].endswith(f" {_num(TRIALS_RANGE[1], locale, 0)}.")
    assert words["sharpe_help"].endswith(f" {_num(1.8, locale, 1)}.")
    assert words["years_help"].endswith(f" {_num(0.5, locale, 1)}.")
    for key in ("sharpe_help", "years_help", "error_sharpe", "error_years", "error_trials"):
        assert find_claims(words[key]) == []
    # The example the help gives parses back to the number it shows.
    example = words["sharpe_help"].rsplit(" ", 1)[1].removesuffix(".")
    assert parse_input(example, "3", "10") == CalculatorInput(1.8, 3.0, 10)


@pytest.mark.parametrize("locale", LOCALES)
def test_examples_link_to_a_calculator_in_the_same_typography(
    client: TestClient, locale: str
) -> None:
    for example in EXAMPLES:
        value = example.calculator_input()
        if value is None:
            continue
        href = example_calculator_url(example, locale)
        # The link keeps the point; the page shows the figures with the language's mark.
        assert "," not in urlsplit(href).query
        response = client.get(href)
        assert response.status_code == 200
        # The link carries the years as /ejemplos shows them (9 weeks ≈ 0.17), so
        # the calculator answers for the figures in its own fields.
        query = {k: v[0] for k, v in parse_qs(urlsplit(href).query).items()}
        linked = parse_input(query["sharpe"], query["years"], query["trials"])
        assert isinstance(linked, CalculatorInput)
        assert linked.sharpe == value.sharpe and linked.trials == value.trials
        assert linked.years == pytest.approx(value.years, abs=0.005)
        result = compute(linked)
        section = _result_section(response.text, locale)
        if result["counted"]:
            for shown in _expected_counted(result, locale).values():
                assert f"<b>{html.escape(shown)}</b>" in section
        else:
            assert [tuple(row) for row in _cells(section)[1:]] == _expected_rows(result, locale)
