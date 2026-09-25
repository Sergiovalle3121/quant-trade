"""What the report says when a balance-only file hides open losses.

A balance rebuilt from closed trades cannot see a position while it is
losing. When the red flags find that (grid or many open positions on a
balance-only file), the headline tiles, the resampled risk and the prop
simulator must say so instead of printing a flattering 0.0 %.
"""

from __future__ import annotations

import html
import re
from typing import Any

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.report import LABELS, _account_html, _pct, render_html
from quant_trade.audit.sample import sample_result
from quant_trade.audit.schema import AuditResult

HIDDEN = {
    "code": "HIDDEN_FLOATING_DRAWDOWN",
    "severity": "WARN",
    "title": "Hidden floating drawdown",
    "detail": "balance-only curve with overlapping positions",
}


def _visible(page: str) -> str:
    page = re.sub(r"<(style|svg|script)\b.*?</\1>", " ", page, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _result(**changes: Any) -> AuditResult:
    data = sample_result("es", bootstrap_samples=60).model_dump(mode="json")
    data.update(changes)
    return AuditResult.model_validate(data)


@pytest.mark.parametrize("locale", ["es", "en"])
def test_hidden_open_losses_are_called_out(locale: str) -> None:
    base = sample_result("es", bootstrap_samples=60).model_dump(mode="json")
    flags = [*base["red_flags"], HIDDEN]
    page = _visible(render_html(_result(red_flags=flags), watermark=False, locale=locale))
    text = LABELS[locale]["hidden_loss"]
    assert page.count(text) == 3  # resampled risk, capital and the prop simulator
    assert LABELS[locale]["kpi_drawdown_closed"] in page
    assert find_claims(text) == []
    clean = _visible(render_html(_result(), watermark=False, locale=locale))
    assert text not in clean


def test_a_closed_trade_curve_says_so_on_the_tiles() -> None:
    page = _visible(render_html(_result(), watermark=False, locale="es"))
    assert "Drawdown máximo (solo cerradas)" in page
    assert "Drawdown p95 a 1 año (solo cerradas)" in page


def test_a_tiny_fall_never_prints_minus_zero() -> None:
    assert _pct(-0.0001) == "0.0%"
    assert _pct(-0.012) == "-1.2%"


@pytest.mark.parametrize("locale", ["es", "en"])
def test_a_clean_account_without_a_floating_figure_does_not_vouch_for_it(locale: str) -> None:
    account = sample_result("es", bootstrap_samples=60).model_dump(mode="json")["account"]
    account.update(clean=True, flags=[], deposit_list=[])
    account["floating_pnl"] = {"evidence": "NOT_MEASURED", "value": None, "note": ""}
    account["floating_share"] = {"evidence": "NOT_MEASURED", "value": None, "note": ""}
    labels = LABELS[locale]
    unseen = _account_html(account, labels)
    assert html.escape(labels["account_clean_unseen"], quote=True) in unseen
    assert html.escape(labels["account_clean"], quote=True) not in unseen
    account["floating_pnl"] = {"evidence": "DECLARED", "value": -3.0, "note": ""}
    account["floating_share"] = {"evidence": "MEASURED", "value": 0.001, "note": ""}
    seen = _account_html(account, labels)
    assert html.escape(labels["account_clean"], quote=True) in seen
    assert find_claims(labels["account_clean_unseen"]) == []


def test_a_losing_file_does_not_show_a_negative_extra_cost() -> None:
    data = sample_result("es", bootstrap_samples=60).model_dump(mode="json")
    data["costs"]["break_even_bps"] = {"evidence": "MEASURED", "value": -0.56, "note": ""}
    for locale in ("es", "en"):
        page = _visible(
            render_html(AuditResult.model_validate(data), watermark=False, locale=locale)
        )
        assert LABELS[locale]["kpi_breakeven_negative"] in page
        assert "-0.56" not in page.split(LABELS[locale]["kpi_breakeven_negative"])[0][-300:]


def test_large_percentages_carry_thousands_separators() -> None:
    data = sample_result("es", bootstrap_samples=60).model_dump(mode="json")
    data["performance"]["total_return"]["value"] = 1911.36
    page = _visible(render_html(AuditResult.model_validate(data), watermark=False, locale="es"))
    assert "+191,136.0%" in page
    assert "191136" not in page


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_capital_section_carries_the_open_loss_callout(locale: str) -> None:
    base = sample_result("es", bootstrap_samples=60).model_dump(mode="json")
    assert base["capital"]["status"] == "MEASURED"
    page = render_html(
        _result(red_flags=[*base["red_flags"], HIDDEN]), watermark=False, locale=locale
    )
    capital = page.split(html.escape(LABELS[locale]["capital"], quote=True))[-1]
    capital = capital.split("</section>")[0]
    assert html.escape(LABELS[locale]["hidden_loss"], quote=True) in capital
    # The softer closed-trades note gives way to the red callout.
    assert html.escape(LABELS[locale]["capital_closed_only"], quote=True) not in capital


def test_the_trade_pace_is_a_fact_card() -> None:
    page = render_html(_result(), watermark=False, locale="es")
    assert (
        "Operaciones cerradas por año en el historial "
        '<span class="badge MEASURED">MEASURED</span></p></div>' in page
    )
    assert "Operaciones por año:" not in _visible(page)


def test_every_fact_card_carries_its_evidence_tag() -> None:
    page = render_html(_result(), watermark=False, locale="es")
    cards = re.findall(r"<div class='fact[^']*'><b>.*?</p></div>", page, flags=re.S)
    assert len(cards) >= 5
    for card in cards:
        assert 'class="badge ' in card, card


@pytest.mark.parametrize(
    ("value", "signed", "places", "shown"),
    [
        (-0.00001, True, 1, "0.0%"),
        (0.00001, True, 1, "0.0%"),
        (-0.003, False, 0, "0%"),
        (-0.997, False, 0, "-99.7%"),
        (-1.0, False, 0, "-100%"),
        (0.9996, False, 0, ">99.9%"),
        (-0.9996, False, 0, "<-99.9%"),
        (0.99999999998, False, 1, ">99.99%"),
        (-0.99994, True, 1, "-99.99%"),
        (12.5, True, 1, "+1,250.0%"),
    ],
)
def test_shares_read_right_at_the_edges(
    value: float, signed: bool, places: int, shown: str
) -> None:
    assert _pct(value, signed=signed, places=places) == shown


def test_ratios_and_break_even_pips_carry_thousands_separators() -> None:
    from quant_trade.audit.report import _fmt

    assert _fmt(877194.39, key="profit_factor") == "877,194.39"
    assert _fmt(10985.5, key="break_even_pips") == "10,985.50"


@pytest.mark.parametrize(
    ("value", "percent", "shown"),
    [
        (-0.00001, True, "0.0%"),
        (-0.001, False, "0.00"),
        (-0.997, True, "-99.7%"),
        (-12_562.1, False, "-12,562.10"),
    ],
)
def test_stress_figures_never_print_a_signed_zero(value: float, percent: bool, shown: str) -> None:
    from quant_trade.audit.report import _stress_value

    assert _stress_value(value, percent=percent, signed=True) == shown


def test_the_class_plan_reads_in_spanish() -> None:
    assert "PASS" not in LABELS["es"]["plan_class"]
