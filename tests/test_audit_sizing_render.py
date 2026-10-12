"""Original-file sizes and copier falls belong to the complete HTML and PDF."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift, trades_following

from quant_trade.audit import pdf
from quant_trade.audit.challenge_sizing import DAILY_NOTE
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import localize
from quant_trade.audit.report import (
    LABELS,
    _capital_html,
    _challenge_daily_size_html,
    render_html,
    result_sha256,
)
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, build_inputs, measured
from quant_trade.audit.sizing import capital_review
from quant_trade.audit.theme import STYLE
from quant_trade.core.models import Trade

LOCALES = ("es", "en", "pt")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _text(page: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _capital(unit: str = "lot", quantity: float = 2.0, **kwargs: Any) -> dict[str, Any]:
    start = datetime(2024, 1, 2, tzinfo=UTC)
    profits = [60.0, -40.0] * 25 + [-100.0] * 5 + [50.0] * 5
    trades = [
        Trade(
            entry_time=start + timedelta(days=2 * index),
            exit_time=start + timedelta(days=2 * index, hours=4),
            quantity=quantity,
            entry_price=1000.0,
            exit_price=1000.0 + profit,
            pnl=profit,
            return_pct=profit / 1000.0,
        )
        for index, profit in enumerate(profits)
    ]
    return capital_review(
        trades,
        fees=None,
        starting_balance=10_000.0,
        platform_fall=4000.0,
        quantities=kwargs.pop("quantities", [quantity] * len(trades)),
        quantity_unit=unit,
        samples=100,
        **kwargs,
    )


@pytest.fixture(scope="module")
def report_result() -> AuditResult:
    curve = positive_drift(300)
    inputs = build_inputs(
        csv_bytes(curve),
        DeclaredMetadata(),
        trades_bytes=csv_bytes(trades_following(curve, every=3)),
    )
    return run_audit(
        inputs,
        now=NOW,
        audit_id="sizes",
        bootstrap_samples=100,
        risk_samples=100,
        challenge_samples=100,
    )


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("unit", ("lot", "contract", "file"))
def test_complete_report_shows_file_sizes_and_copy_falls(
    report_result: AuditResult, locale: str, unit: str
) -> None:
    capital = _capital(unit)
    result = report_result.model_copy(update={"capital": capital})
    page = render_html(result, watermark=False, locale=locale)
    text = _text(page)
    labels = LABELS[locale]
    assert labels["capital_median"] in text
    assert labels["capital_quantity"] in text
    assert labels["copy_title"] in text
    assert labels["copy_assumption"] in text
    assert "0.5x" in text and "1x" in text and "2x" in text and "3x" in text
    assert "80.0 %" in text
    assert {
        "es": "pierde la cuenta entera",
        "en": "loses the entire account",
        "pt": "perde a conta inteira",
    }[locale] in text
    size = {
        "lot": "0.50 lots" if locale == "en" else "0.50 lotes",
        "contract": "1 contract" if locale == "en" else "1 contrato",
        "file": {
            "es": "0.50 unidades del archivo",
            "en": "0.50 file units",
            "pt": "0.50 unidades do arquivo",
        }[locale],
    }[unit]
    assert size in text
    assert find_claims(page) == []


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("unit, quantity", (("lot", 0.01), ("contract", 1.0)))
def test_below_step_size_says_it_does_not_fit(locale: str, unit: str, quantity: float) -> None:
    page = _capital_html(_capital(unit, quantity), locale, LABELS[locale])
    expected = {
        "es": "no cabe con este límite",
        "en": "does not fit this limit",
        "pt": "não cabe neste limite",
    }[locale]
    assert expected in _text(page)
    assert ("0.01" if unit == "lot" else "1 contract" if locale == "en" else "1 contrato") in page
    assert find_claims(page) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_variable_size_and_martingale_are_explained(locale: str) -> None:
    labels = LABELS[locale]
    capital = _capital(quantities=[2.0] * 45 + [10.0] * 15)
    assert labels["capital_variable"] in _capital_html(capital, locale, labels)
    held = _capital(martingale=True)
    page = _capital_html(held, locale, labels)
    assert localize(held["quantity_profile"]["median"]["note"], locale) in _text(page)
    assert "lots" not in _text(page) and "lotes" not in _text(page)
    assert find_claims(page) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_preview_does_not_show_new_sizes_or_multiplier_table(
    report_result: AuditResult, locale: str
) -> None:
    result = report_result.model_copy(update={"capital": _capital()}, deep=True)
    assert result.challenge is not None and result.challenge["status"] == "MEASURED"
    result.challenge["sizing"]["daily_limit"] = _daily("contract")
    full = render_html(result, watermark=False, locale=locale)
    assert LABELS[locale]["ch_daily_size"] in full
    assert LABELS[locale]["copy_title"] in full
    page = render_html(result, watermark=True, free_mode=False, locale=locale)
    for key in (
        "capital_median",
        "capital_quantity",
        "capital_variable",
        "copy_title",
        "copy_assumption",
        "ch_daily_size",
    ):
        assert LABELS[locale][key] not in page
    assert "copy-sizing" not in page
    assert "80.0 %" not in page
    legacy = result.model_copy(deep=True)
    assert legacy.capital is not None and legacy.challenge is not None
    legacy.capital.pop("copy_rows")
    legacy.capital.pop("quantity_profile")
    for row in legacy.capital["rows"]:
        row.pop("quantity")
    legacy.challenge["sizing"].pop("daily_limit")
    old_page = render_html(legacy, watermark=True, free_mode=False, locale=locale)
    # Adding evidence changes the JSON digest; all other preview bytes stay identical.
    assert page.replace(result_sha256(result), "JSON_DIGEST") == old_page.replace(
        result_sha256(legacy), "JSON_DIGEST"
    )


def _daily(unit: str) -> dict[str, Any]:
    return {
        "status": "MEASURED",
        "unit": unit,
        "quantity": measured(0.49 if unit == "lot" else 2.0),
        "note": DAILY_NOTE,
    }


@pytest.mark.parametrize("locale", LOCALES)
@pytest.mark.parametrize("unit", ("lot", "contract"))
def test_challenge_daily_size_carries_its_unit_and_assumption(locale: str, unit: str) -> None:
    page = _challenge_daily_size_html(_daily(unit), locale, LABELS[locale])
    assert LABELS[locale]["ch_daily_size"] in page
    assert (
        ("0.49 lots" if locale == "en" else "0.49 lotes") in page
        if unit == "lot"
        else ("2 contracts" if locale == "en" else "2 contratos") in page
    )
    assert localize(DAILY_NOTE, locale) in _text(page)
    assert find_claims(page) == []


@pytest.mark.skipif(not pdf.available(), reason="WeasyPrint/Pango not installed")
@pytest.mark.parametrize("locale", LOCALES)
def test_pdf_contains_the_sizes_copy_table_and_daily_limit(locale: str) -> None:
    pdfplumber = pytest.importorskip("pdfplumber")
    labels = LABELS[locale]
    body = _capital_html(_capital("contract"), locale, labels)
    body += _challenge_daily_size_html(_daily("lot"), locale, labels)
    page = f"<html><head></head><body>{body}</body></html>"
    content = pdf.report_pdf(page, audit_id="sizes", locale=locale)
    with pdfplumber.open(BytesIO(content)) as document:
        text = " ".join(" ".join((page.extract_text() or "").split()) for page in document.pages)
    assert labels["capital_median"] in text
    assert labels["copy_title"] in text
    assert labels["copy_assumption"] in text
    assert labels["ch_daily_size"] in text
    assert "80.0 %" in text
    assert ("0.49 lots" if locale == "en" else "0.49 lotes") in text
    assert find_claims(text) == []


@pytest.mark.skipif(not pdf.available(), reason="WeasyPrint/Pango not installed")
@pytest.mark.parametrize("locale", LOCALES)
def test_pdf_keeps_copy_title_assumption_and_all_multipliers_on_one_page(locale: str) -> None:
    pdfplumber = pytest.importorskip("pdfplumber")
    labels = LABELS[locale]
    capital = _capital_html(_capital(), locale, labels)
    copy = re.search(r"<div class='copy-sizing-block'>.*?</div>", capital)
    assert copy is not None
    page = (
        f"<html><head><style>{STYLE}</style></head><body>"
        "<div style='height:235mm'>A</div>" + copy.group(0) + "</body></html>"
    )
    content = pdf.report_pdf(page, audit_id="copy-page", locale=locale)
    with pdfplumber.open(BytesIO(content)) as document:
        pages = [" ".join((page.extract_text() or "").split()) for page in document.pages]
    assert len(pages) >= 2
    copy_pages = [text for text in pages if labels["copy_title"] in text]
    assert len(copy_pages) == 1
    text = copy_pages[0]
    assert labels["copy_assumption"] in text
    assert all(f"{multiplier}x" in text for multiplier in ("0.5", "1", "2", "3"))
    assert {
        "es": "pierde la cuenta entera",
        "en": "loses the entire account",
        "pt": "perde a conta inteira",
    }[locale] in text
