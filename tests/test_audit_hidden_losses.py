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
    assert page.count(text) == 2  # resampled risk and the prop simulator
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
