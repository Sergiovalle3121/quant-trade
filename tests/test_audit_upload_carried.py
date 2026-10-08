"""Rejected uploads retain declarations in escaped controls, without retaining files."""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.mapping import Table, mapping_page
from quant_trade.audit.pages import upload_page
from quant_trade.audit.prop_presets import PRESETS


class FormValues(HTMLParser):
    def __init__(self, page: str) -> None:
        super().__init__(convert_charrefs=True)
        self.fields: dict[str, dict[str, str | None]] = {}
        self.select = ""
        self.textarea = ""
        self.tags: list[str] = []
        self.feed(page)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        attributes = dict(attrs)
        name = attributes.get("name", "") or ""
        if name:
            self.fields[name] = attributes
        if tag == "select":
            self.select = name
        elif tag == "option" and "selected" in attributes:
            self.fields[self.select]["value"] = attributes["value"]
        elif tag == "textarea":
            self.textarea = name
            self.fields[name]["value"] = ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "textarea":
            self.textarea = ""
        elif tag == "select":
            self.select = ""

    def handle_data(self, data: str) -> None:
        if self.textarea:
            self.fields[self.textarea]["value"] += data  # type: ignore[operator]


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_rejection_restores_declarations_and_opens_their_sections(locale: str) -> None:
    carried = {
        "trials": "17",
        "cost_bps": "2.5",
        "oos_start": "2025-02-01",
        "description": "Synthetic journal & its assumptions",
        "benchmark_applicable": "no",
        "challenge": next(iter(PRESETS)),
        "initial_balance": "10000",
        "locale": locale,
        "consent": "on",
        "net_of_fees": "on",
        "return_frequency": "monthly",
        "return_unit": "percent",
        "col_profit": "Result",
    }
    guidance = "<div role='alert'><a href='/guias/mt5'>HTML / CSV / XLSX</a></div>"
    page = upload_page(locale=locale, carried=carried, rejection_html=guidance)
    fields = FormValues(page).fields
    for name, expected in carried.items():
        assert fields[name]["value"] == expected
    assert "checked" in fields["consent"]
    assert "checked" in fields["net_of_fees"]
    for classes in ("adv", "adv extras", "adv map-columns"):
        assert f"<details class='{classes}' open>" in page
    assert page.index(guidance) < page.index("<form method='post' action='/audits'")
    assert find_claims(page) == []


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_carried_values_cannot_add_markup_and_secrets_and_files_are_not_restored(
    locale: str,
) -> None:
    malicious = "</textarea><img src=x onerror='alert(1)'>\"&"
    page = upload_page(
        locale=locale,
        access_codes=True,
        carried={
            "description": malicious,
            "col_profit": malicious,
            "trials": malicious,
            "access_code": "SECRET-NOT-RESTORED",
            "report": "private-file.csv",
            "unexpected": "UNLISTED-VALUE",
        },
    )
    fields = FormValues(page).fields
    for name in ("description", "col_profit", "trials"):
        assert fields[name]["value"] == malicious
        assert "onerror" not in fields[name]
    assert "<img src=x" not in page
    assert "SECRET-NOT-RESTORED" not in page
    assert "private-file.csv" not in page
    assert "UNLISTED-VALUE" not in page
    assert "value" not in fields["report"]
    assert "value" not in fields["access_code"]
    assert "checked" not in fields["consent"]
    assert "checked" not in fields["net_of_fees"]
    assert find_claims(page) == []


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_mapping_retains_series_declarations_with_guidance_above_the_form(locale: str) -> None:
    table = Table(header=["Day", "Value"], samples=[["2025-01-01", "100"]])
    carried = {"return_frequency": "monthly", "return_unit": "percent", "locale": locale}
    guidance = "<p role='alert'><a href='/guias/mt5'>HTML / CSV / XLSX</a></p>"
    page = mapping_page(table, "CSV", locale=locale, carried=carried, guidance_html=guidance)
    fields = FormValues(page).fields
    for name, expected in carried.items():
        assert fields[name]["value"] == expected
    assert page.index(guidance) < page.index("<form class='map-form'")
    assert find_claims(page) == []


def test_client_text_is_preserved_as_a_declaration_without_running_a_report_guard() -> None:
    claim = "guaranteed profit"
    page = upload_page(carried={"description": claim})
    assert FormValues(page).fields["description"]["value"] == claim
    # Arbitrary client words are not Rigor's fixed copy or report verdict.
    assert find_claims(upload_page()) == []
