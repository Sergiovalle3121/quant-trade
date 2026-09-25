"""The capital section's wording next to the rest of the report.

It sees closed trades only, so it says so when the platform prints a deeper
drawdown with open trades, and it speaks of the account's size, not the
backtest's, when the file is an account history.
"""

from __future__ import annotations

import html

import pytest

from quant_trade.audit.guard import find_claims
from quant_trade.audit.report import LABELS, _capital_html, _capital_shown, _fmt
from quant_trade.audit.schema import measured

CAPITAL = {
    "status": "MEASURED",
    "method": {"samples": 2000},
    "fall_reference": measured(5748.06),
    "fall_history": measured(918.6),
    "trades_per_year": measured(611, "closed trades per year in the history"),
    "starting_balance": measured(2000.0),
    "rows": [
        {"limit": 0.1, "capital": measured(57480.6), "size_share": measured(0.0348)},
        {"limit": 0.5, "capital": measured(11496.1), "size_share": measured(0.174)},
    ],
}


@pytest.mark.parametrize("locale", ["es", "en"])
def test_open_losses_the_platform_prints_are_called_out(locale: str) -> None:
    labels = LABELS[locale]
    page = _capital_html(CAPITAL, locale, labels, closed_dd=-0.2896, platform_dd=-0.4051)
    assert "40.5%" in page and "29.0%" in page
    assert html.escape(labels["open_loss_badge"]) in page
    assert find_claims(page) == []
    # Same depth (within half a point): nothing to say.
    quiet = _capital_html(CAPITAL, locale, labels, closed_dd=-0.29, platform_dd=-0.292)
    assert html.escape(labels["open_loss_badge"]) not in quiet


@pytest.mark.parametrize("locale", ["es", "en"])
def test_a_closed_trade_balance_says_open_losses_are_left_out(locale: str) -> None:
    labels = LABELS[locale]
    page = _capital_html(CAPITAL, locale, labels, closed_only=True)
    assert html.escape(labels["capital_closed_only"]) in page
    assert html.escape(labels["capital_closed_only"]) not in _capital_html(CAPITAL, locale, labels)


@pytest.mark.parametrize("locale", ["es", "en"])
def test_an_account_history_is_sized_at_the_account_size(locale: str) -> None:
    labels = LABELS[locale]
    page = _capital_html(CAPITAL, locale, labels, account=True)
    for key in ("capital_fall", "capital_needed", "capital_scale_help"):
        assert html.escape(labels[f"{key}_account"]) in page
        assert html.escape(labels[key]) not in page
    assert find_claims(page) == []


def test_a_short_file_says_why_there_are_no_capital_figures() -> None:
    capital = {
        "status": "NOT_MEASURED",
        "reason": "needs trades spread over at least 90 days; a shorter history stretched "
        "to a year gives capital figures too uncertain to act on",
    }
    assert _capital_shown(capital)
    assert not _capital_shown({"status": "NOT_MEASURED", "reason": "no trades uploaded"})
    es = _capital_html(capital, "es", LABELS["es"])
    assert "NOT_MEASURED" in es and "al menos 90 días" in es and "3 meses o más" in es
    en = _capital_html(capital, "en", LABELS["en"])
    assert "at least 90 days" in en and "3 months or more" in en
    flat = {"status": "NOT_MEASURED", "reason": "the trades show no fall to size against"}
    assert "3 meses" not in _capital_html(flat, "es", LABELS["es"])


def test_observation_counts_read_as_whole_numbers() -> None:
    assert _fmt(84.69, key="min_track_record_length") == "85"
    assert _fmt(58.69, key="observations_short_by") == "59"
