"""Original-file sizes and copier falls belong to the complete HTML and PDF."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

import pytest
from audit_fixtures import csv_bytes, positive_drift, trades_following

from quant_trade.audit import ownership, pdf
from quant_trade.audit.challenge_sizing import DAILY_NOTE, NO_BALANCE, NO_LIMIT
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
from quant_trade.audit.schema import (
    AuditResult,
    DeclaredMetadata,
    build_inputs,
    declared,
    measured,
)
from quant_trade.audit.sizing import capital_review
from quant_trade.audit.theme import STYLE
from quant_trade.core.models import Trade

LOCALES = ("es", "en", "pt")
NOW = datetime(2026, 1, 1, tzinfo=UTC)


def _text(page: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def _capital(
    unit: str = "lot",
    quantity: float = 2.0,
    *,
    starting_balance_override: float | None = 10_000.0,
    **kwargs: Any,
) -> dict[str, Any]:
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
        starting_balance=starting_balance_override,
        platform_fall=4000.0,
        quantities=kwargs.pop("quantities", [quantity] * len(trades)),
        quantity_unit=unit,
        samples=100,
        **kwargs,
    )


def _voiced(result: AuditResult, locale: str) -> dict[str, str]:
    """The labels in the voice the report speaks: no answer is the neutral one."""
    role = ownership.role_of(result.model_dump(mode="json"))
    return ownership.labels_for(LABELS[locale], locale, role)


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
    labels = _voiced(result, locale)
    assert labels["capital_median"] in text
    assert labels["capital_quantity"] in text
    assert labels["copy_title"] in text
    assert labels["copy_assumption"] in text
    assert labels["copy_fall"] in text
    assert labels[f"capital_quantity_help_{unit}"] in text
    table = re.search(r"<table class='copy-sizing'>.*?</table>", page)
    assert table is not None
    rows = re.findall(r"<tr><td>([\d.]+x)</td><td class='val'>([\d.]+%)", table.group(0))
    assert [row[0] for row in rows] == ["0.5x", "1x", "2x", "3x"]
    assert ("2x", "80.0%") in rows
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
def test_only_the_buyer_reads_the_copy_balance_as_the_providers(
    report_result: AuditResult, locale: str
) -> None:
    for role in (*ownership.ROLES, None):
        stated = {key: value for key, value in report_result.declared.items() if key != "ownership"}
        if role:
            stated["ownership"] = declared(role)
        result = report_result.model_copy(update={"capital": _capital(), "declared": stated})
        text = _text(render_html(result, watermark=False, locale=locale))
        assert _voiced(result, locale)["copy_assumption"] in text, role
        named = LABELS[locale]["copy_assumption"] in text
        assert named == (role == ownership.BUYER), role


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
    reason = localize(held["quantity_profile"]["median"]["note"], locale)
    # One badge and the reason as a sentence, not a bare lower-case line.
    assert f"{labels['capital_median']}: " in _text(page)
    assert reason[:1].upper() + reason[1:] + "." in _text(page)
    assert "lots" not in _text(page) and "lotes" not in _text(page)
    assert labels["capital_quantity"] not in page
    # Copying still scales each trade, but the provider's size was not fixed.
    assert labels["copy_assumption_martingale"] in _text(page)
    assert labels["copy_assumption"] not in _text(page)
    assert find_claims(page) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_unknown_balance_leaves_one_copy_line_and_no_empty_rows(locale: str) -> None:
    labels = LABELS[locale]
    capital = _capital(starting_balance_override=None)
    page = _capital_html(capital, locale, labels)
    assert "copy-sizing" not in page
    assert page.count(labels["copy_title"]) == 1
    assert f"{labels['copy_title']}: " in _text(page)
    assert labels["capital_quantity"] not in page
    assert find_claims(page) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_a_share_above_ten_times_shows_a_lower_bound_quantity(locale: str) -> None:
    labels = LABELS[locale]
    capital = _capital(starting_balance_override=100_000.0)
    text = _text(_capital_html(capital, locale, labels))
    word = {"es": "más de", "en": "more than", "pt": "mais de"}[locale]
    assert f"{word} 10x" in text
    assert f"{word} 20.00 " in text


@pytest.mark.parametrize("locale", LOCALES)
def test_preview_does_not_show_new_sizes_or_multiplier_table(
    report_result: AuditResult, locale: str
) -> None:
    result = report_result.model_copy(update={"capital": _capital()}, deep=True)
    assert result.challenge is not None and result.challenge["status"] == "MEASURED"
    result.challenge["sizing"]["daily_limit"] = _daily("contract")
    full = render_html(result, watermark=False, locale=locale)
    voiced = _voiced(result, locale)
    assert LABELS[locale]["ch_daily_size"] in full
    assert LABELS[locale]["copy_title"] in full
    assert voiced["copy_assumption"] in _text(full)
    page = render_html(result, watermark=True, free_mode=False, locale=locale)
    shown = _text(page)
    for labels in (LABELS[locale], voiced):
        for key in (
            "capital_median",
            "capital_quantity",
            "capital_variable",
            "copy_title",
            "copy_assumption",
            "copy_fall",
            "capital_quantity_help_lot",
            "copy_assumption_martingale",
            "ch_daily_size",
        ):
            assert labels[key] not in page and labels[key] not in shown, key
    assert "copy-sizing" not in page
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
def test_challenge_daily_size_names_the_balance_it_is_given_on(locale: str) -> None:
    labels = LABELS[locale]
    account = {
        **_daily("contract"),
        "basis": "account",
        "sized_on": {"value": 50_000.0, "evidence": "DECLARED"},
    }
    page = _challenge_daily_size_html(account, locale, labels)
    assert labels["ch_daily_on_account"].format(size="50,000") in _text(page)
    history = {
        **_daily("lot"),
        "basis": "history",
        "sized_on": measured(10_000.0),
    }
    text = _text(_challenge_daily_size_html(history, locale, labels))
    head = labels["ch_daily_on_history"].split("(")[0]
    assert head in text and "10,000" in text


@pytest.mark.parametrize("locale", LOCALES)
def test_challenge_daily_size_reasons_and_rules_without_a_daily_limit(locale: str) -> None:
    labels = LABELS[locale]
    no_rule = {"status": "NOT_MEASURED", "reason": NO_LIMIT, "unit": "lot"}
    assert _challenge_daily_size_html(no_rule, locale, labels) == ""
    missing = {"status": "NOT_MEASURED", "reason": NO_BALANCE, "unit": "lot"}
    page = _challenge_daily_size_html(missing, locale, labels)
    reason = localize(NO_BALANCE, locale)
    assert page.count("badge NOT_MEASURED") == 1
    assert reason[:1].upper() + reason[1:] + "." in _text(page)


@pytest.mark.parametrize("locale", LOCALES)
def test_a_daily_size_below_one_step_keeps_the_remark_out_of_the_headline(locale: str) -> None:
    labels = LABELS[locale]
    zero = {**_daily("lot"), "quantity": measured(0.0)}
    page = _challenge_daily_size_html(zero, locale, labels)
    headline = re.search(r"<b>([^<]*)</b>", page)
    assert headline is not None
    assert (
        headline.group(1)
        == {
            "es": "menos de 0.01 lotes",
            "en": "less than 0.01 lots",
            "pt": "menos de 0.01 lotes",
        }[locale]
    )
    remark = {"es": "no cabe con este límite", "en": "does not fit this limit"}.get(
        locale, "não cabe neste limite"
    )
    assert f"({remark})" in _text(page)
    assert ":" not in headline.group(1)


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
    assert "80.0%" in text
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
