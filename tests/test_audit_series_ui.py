"""Periodic series UI preserves declarations and translates supported metadata codes."""

from __future__ import annotations

import html
import re
from typing import Any

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.institutional import COPY as INTAKE_COPY
from quant_trade.audit.institutional import REVIEW_PATHS
from quant_trade.audit.pages import calculator_page, landing, upload_page
from quant_trade.audit.schema import declared, measured
from quant_trade.audit.series_ui import (
    SERIES_COPY,
    institutional_block,
    series_fields,
    series_report,
)


def _text(markup: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", markup))


def _series_data() -> dict[str, Any]:
    return {
        "inputs": {
            "return_series": {
                "frequency": declared("monthly"),
                "periods_per_year": declared(12),
                "unit": declared("percent"),
                "basis": declared("net"),
                "frequency_confirmed": declared(True),
                "benchmark_source": declared("uploaded file"),
                "benchmark_periods_per_year": declared(12),
                "gross": {"total_return": measured(0.24), "sharpe": measured(1.5)},
                "net": {"total_return": measured(0.21), "sharpe": measured(1.2)},
            },
        },
        "costs": {
            "kind": "period_returns",
            "status": "MEASURED",
            "reference_basis": declared("gross_return - net_return"),
            "rows": [
                {
                    "multiplier": declared(2),
                    "total_return": measured(0.18),
                    "sharpe_annualised": measured(0.9),
                }
            ],
        },
    }


def _strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [text for child in value.values() for text in _strings(child)]
    return [value] if isinstance(value, str) else []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_all_series_and_institutional_copy_passes_guard(locale: str) -> None:
    for text in _strings(SERIES_COPY[locale]):
        assert find_claims(text) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_series_form_supports_inference_and_explicit_declarations(locale: str) -> None:
    markup = series_fields(locale)
    assert "<fieldset" in markup
    assert "name='return_frequency'" in markup and "name='return_unit'" in markup
    assert len(re.findall(r"<option value=''>", markup)) == 2
    for value in ("daily", "weekly", "monthly", "fraction", "percent"):
        assert f"value='{value}'" in markup
    assert markup.count("DECLARED") >= 7
    assert SERIES_COPY[locale]["unit_help"] in markup
    assert find_claims(_text(markup)) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_series_report_shows_frequency_gross_net_and_costs_with_evidence(locale: str) -> None:
    markup = series_report(_series_data(), locale)
    copy = SERIES_COPY[locale]
    assert copy["frequencies"]["monthly"] in markup
    assert copy["units"]["percent"] in markup
    assert copy["bases"]["net"] in markup
    assert copy["sources"]["uploaded file"] in markup
    assert copy["yes"] in markup
    assert "12 <span class='badge DECLARED'>" in markup
    assert "24.00% <span class='badge MEASURED'>" in markup
    assert "21.00% <span class='badge MEASURED'>" in markup
    assert "18.00% <span class='badge MEASURED'>" in markup
    assert "2 <span class='badge DECLARED'>" in markup
    assert copy["cost_note"] in markup
    assert copy["cost_difference"] in markup
    assert "?periods_per_year=12" in markup
    assert find_claims(_text(markup)) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_inferred_frequency_and_missing_costs_do_not_become_measurements(locale: str) -> None:
    data = _series_data()
    data["inputs"]["return_series"]["frequency_confirmed"] = declared(False)
    data["inputs"]["return_series"]["benchmark_periods_per_year"] = declared(52)
    data["costs"] = {"kind": "period_returns", "status": "NOT_MEASURED"}
    markup = series_report(data, locale)
    copy = SERIES_COPY[locale]
    assert copy["no"] in markup
    assert copy["benchmark_mismatch"] in markup
    assert copy["cost_missing"] in markup
    assert "NOT_MEASURED" in markup
    assert find_claims(_text(markup)) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_report_does_not_echo_untrusted_codes_or_nonfinite_numbers(locale: str) -> None:
    data = _series_data()
    series = data["inputs"]["return_series"]
    for key in ("frequency", "unit", "basis", "benchmark_source"):
        series[key] = declared("<script>alert('raw-client-code')</script>")
    series["gross"]["sharpe"] = {"value": float("inf"), "evidence": "MEASURED"}
    markup = series_report(data, locale)
    assert "<script>" not in markup and "raw-client-code" not in markup
    assert "inf" not in _text(markup).lower()
    assert SERIES_COPY[locale]["missing"] in markup


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_institutional_block_is_localised_and_escapes_review_url(locale: str) -> None:
    markup = institutional_block(locale, "/contact?source='home'&type=model")
    copy = SERIES_COPY[locale]
    assert copy["institutional_title"] in markup
    assert copy["institutional_text"] in markup
    assert INTAKE_COPY[locale]["title"] in markup
    assert "href='/contact?source=&#x27;home&#x27;&amp;type=model'" in markup
    assert find_claims(_text(markup)) == []


def test_no_periodic_section_for_legacy_reports() -> None:
    assert series_report({"inputs": {}}, "es") == ""
    assert series_report({}, "en") == ""


@pytest.mark.parametrize("periods,frequency", [(252, "daily"), (52, "weekly"), (12, "monthly")])
def test_report_calculator_link_preserves_frequency(periods: int, frequency: str) -> None:
    data = _series_data()
    data["inputs"]["return_series"]["frequency"] = declared(frequency)
    data["inputs"]["return_series"]["periods_per_year"] = declared(periods)
    assert f"?periods_per_year={periods}" in series_report(data, "en")


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_upload_page_contains_periodic_return_declarations(locale: str) -> None:
    page = upload_page(locale=locale)
    assert "name='return_frequency'" in page and "name='return_unit'" in page
    fields = re.search(r"<fieldset class='return-series-fields'>.*?</fieldset>", page)
    assert fields is not None
    assert SERIES_COPY[locale]["title"] in fields.group()
    assert find_claims(_text(fields.group())) == []
    benchmark = re.search(r"<input[^>]*name='benchmark'[^>]*>", page)
    assert benchmark is not None
    assert "accept='.csv,.xlsx,text/csv'" in benchmark.group()
    assert "Benchmark (CSV/XLSX," in page


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_landing_footer_links_the_institutional_review_request(locale: str) -> None:
    # The institutional block left the short landing; the footer of every page links
    # the review request.
    page = landing(locale=locale)
    assert "class='card institutional'" not in page
    footer = page.split("</main>", 1)[1]
    link = f"<a href='{REVIEW_PATHS[locale]}'>{html.escape(INTAKE_COPY[locale]['title'])}</a>"
    assert link in footer
    assert find_claims(_text(footer)) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("periods", [252, 52, 12])
def test_calculator_page_preserves_declared_frequency(locale: str, periods: int) -> None:
    from quant_trade.audit.calculator import CalculatorInput, calculator_copy, compute

    page = calculator_page(
        locale=locale, sharpe="1.8", years="3", trials="100", periods_per_year=str(periods)
    )
    assert "name='periods_per_year'" in page
    assert f"value='{periods}' selected" in page
    copy = calculator_copy(locale, periods)
    # Page rendering translates evidence labels for the visitor.
    assumption = copy["assumptions"][0].split(" (DECLARED)")[0]
    assert assumption in _text(page)
    result = compute(CalculatorInput(1.8, 3, 100, periods))
    # The figure in the page's typography: a decimal comma in es and pt, a point in en.
    luck = f"{result['luck_sharpe']['value']:.2f}"
    assert (luck if locale == "en" else luck.replace(".", ",")) in page
    assert find_claims(_text(page.split("<main", 1)[1].split("</main>", 1)[0])) == []


def test_calculator_invalid_frequency_is_a_localised_error() -> None:
    page = calculator_page(sharpe="1.8", years="3", trials="100", periods_per_year="<script>")
    assert "Elige una frecuencia diaria, semanal o mensual." in page
    assert "data-calc-verdict" not in page
    assert "<script>" not in page


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_cost_failure_reason_and_unit_confirmation_are_translated(locale: str) -> None:
    from quant_trade.audit.period_analysis import REASONS

    data = _series_data()
    data["inputs"]["return_series"]["unit_confirmed"] = declared(False)
    data["inputs"]["return_series"]["benchmark_source"] = declared("embedded column")
    data["costs"].update(status="NOT_MEASURED", reason=REASONS["negative_cost"]["en"])
    markup = series_report(data, locale)
    assert REASONS["negative_cost"][locale] in markup
    assert SERIES_COPY[locale]["unit_no"] in markup
    assert SERIES_COPY[locale]["sources"]["embedded column"] in markup
    assert find_claims(_text(markup)) == []


def test_cost_failure_unknown_reason_is_not_echoed() -> None:
    data = _series_data()
    data["costs"].update(status="NOT_MEASURED", reason="<script>untrusted reason</script>")
    markup = series_report(data, "es")
    assert "untrusted reason" not in markup and "<script>" not in markup
    assert SERIES_COPY["es"]["cost_missing"] in markup
