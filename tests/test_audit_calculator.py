"""The public luck calculator: the luck section's arithmetic on declared numbers."""

from __future__ import annotations

import html
import re

import pytest

from quant_trade.audit.calculator import (
    CALCULATOR_PATH,
    COPY,
    CalculatorInput,
    compute,
    parse_input,
)
from quant_trade.audit.guard import find_claims
from quant_trade.audit.seo import PUBLIC_PAGES

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.web import create_app  # noqa: E402


def _text(page: str) -> str:
    body = page.split("<main", 1)[1].split("</main>", 1)[0]
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body)))


def test_parse_input_reads_numbers_and_rejects_out_of_range() -> None:
    assert parse_input(None, None, None) is None
    assert parse_input("1,8", "3", "1,000") == CalculatorInput(sharpe=1.8, years=3.0, trials=1000)
    assert parse_input("abc", "3", "10") == "error_number"
    assert parse_input("1", "", "10") == "error_number"
    assert parse_input("0", "3", "10") == "error_sharpe"
    assert parse_input("1", "0.01", "10") == "error_years"
    assert parse_input("1", "3", "0") == "error_trials"
    assert parse_input("nan", "3", "10") == "error_number"


def test_trials_read_thousands_as_people_type_them() -> None:
    """ "1.000" is a thousand in es/pt and "1,000" in en: before, "1.000" read
    as one trial and gave a far smaller luck figure without any warning."""
    thousand = CalculatorInput(sharpe=1.8, years=3.0, trials=1000)
    nbsp, narrow = "\u00a0", "\u202f"
    for typed in ("1.000", "1,000", "1 000", f"1{nbsp}000", f"1{narrow}000", "1000", "1e3"):
        assert parse_input("1,8", "3", typed) == thousand, typed
    assert parse_input("1,8", "3", "12.500").trials == 12500
    assert parse_input("1,8", "3", "1.000.000").trials == 1_000_000
    assert parse_input("1,8", "3", "100.0").trials == 100
    # A fraction is not a number of configurations ("1,5" used to read as 15).
    for typed in ("1,5", "12.5", "1.0001"):
        assert parse_input("1,8", "3", typed) == "error_number", typed


def test_more_configurations_raise_the_luck_and_cut_more() -> None:
    small = compute(CalculatorInput(sharpe=1.8, years=3.0, trials=10))
    large = compute(CalculatorInput(sharpe=1.8, years=3.0, trials=1000))
    assert small["luck_sharpe"]["value"] < large["luck_sharpe"]["value"]
    assert small["sharpe_after"]["value"] > large["sharpe_after"]["value"]
    assert small["trials_source"] == "declared"


def test_a_sharpe_below_the_luck_keeps_nothing_after_the_haircut() -> None:
    result = compute(CalculatorInput(sharpe=1.0, years=2.0, trials=1000))
    assert result["beats_luck"] is False
    assert result["sharpe_after"]["value"] == 0.0
    assert result["haircut"]["value"] == 1.0


def test_one_configuration_shows_the_what_if_table() -> None:
    result = compute(CalculatorInput(sharpe=1.5, years=3.0, trials=1))
    assert result["counted"] is False
    assert [row["trials"] for row in result["what_if"]] == [10, 100, 1000]


def test_the_calculator_is_a_public_page_in_every_language() -> None:
    assert dict(CALCULATOR_PATH) in PUBLIC_PAGES
    assert set(COPY) == {"es", "en", "pt"}


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_calculator_page_renders_form_and_result_guard_clean(locale: str) -> None:
    client = TestClient(create_app())
    path = CALCULATOR_PATH[locale]
    empty = client.get(path)
    assert empty.status_code == 200
    assert "name='sharpe'" in empty.text and "data-calc-verdict" not in empty.text
    assert find_claims(_text(empty.text)) == []

    filled = client.get(path, params={"sharpe": "1.8", "years": "3", "trials": "100"})
    assert filled.status_code == 200
    text = _text(filled.text)
    assert "data-calc-verdict" in filled.text
    # The figures in the page's typography: a decimal comma in es and pt, a point in en.
    luck, after, other = ("1.47", "0.76", "1,47") if locale == "en" else ("1,47", "0,76", "1.47")
    assert luck in text and after in text and other not in text
    assert find_claims(text) == []
    # The inputs are the visitor's claim, never shown as measured.
    assert COPY[locale]["declared_note"] in text

    losing = _text(client.get(path, params={"sharpe": "1", "years": "2", "trials": "1000"}).text)
    assert COPY[locale]["loses"].format(n="1,000" if locale == "en" else "1.000") in losing
    assert find_claims(losing) == []

    error = _text(client.get(path, params={"sharpe": "1", "years": "0.01", "trials": "5"}).text)
    assert COPY[locale]["error_years"] in error


def test_calculator_values_are_escaped() -> None:
    client = TestClient(create_app())
    page = client.get("/calculadora", params={"sharpe": "<script>", "years": "3", "trials": "5"})
    assert page.status_code == 200
    assert "<script>" not in page.text.split("<main", 1)[1]
