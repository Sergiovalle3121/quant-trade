"""Original quantities and fixed-size copying; deterministic synthetic histories."""

from __future__ import annotations

import pytest
from test_audit_sizing import PROFITS, _trades

from quant_trade.audit.guard import find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.sizing import (
    COPY_MULTIPLIERS,
    capital_review,
    copy_fall_text,
    quantity_profile,
    quantity_text,
    scaled_quantity,
)


@pytest.mark.parametrize(
    ("unit", "median", "share", "expected"),
    [
        ("lot", 0.29, 1.0, 0.29),
        ("lot", 0.15, 0.5, 0.07),
        ("lot", 0.01, 0.5, 0.0),
        ("contract", 3.0, 0.5, 1.0),
        ("contract", 1.0, 0.5, 0.0),
        ("file", 12.345, 0.5, 6.17),
    ],
)
def test_quantities_round_down_in_original_units(
    unit: str, median: float, share: float, expected: float
) -> None:
    trades = _trades(PROFITS)
    profile = quantity_profile(trades, quantities=[median] * len(trades), unit=unit)
    assert scaled_quantity(profile, share)["value"] == expected
    assert profile["median"]["value"] == median


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_minimum_unit_messages_are_clean(locale: str) -> None:
    no_size = {"value": 0.0, "evidence": "MEASURED"}
    lot = quantity_text(no_size, "lot", locale)
    contract = quantity_text(no_size, "contract", locale)
    assert "0.01" in lot and "1" in contract
    phrase = {"es": "no cabe", "en": "does not fit", "pt": "não cabe"}[locale]
    assert phrase in lot and phrase in contract
    assert find_claims(lot + contract) == []
    assert "1.50" in quantity_text({"value": 1.5, "evidence": "MEASURED"}, "contract", locale)


def test_variable_size_uses_median_and_strict_p90_threshold() -> None:
    trades = _trades(PROFITS)
    profile = quantity_profile(trades, quantities=[0.1] * 40 + [0.4] * 20, unit="lot")
    assert profile["variable"] is True
    assert profile["median"]["value"] == pytest.approx(0.1)
    assert scaled_quantity(profile, 0.5)["value"] == 0.05
    assert not quantity_profile(trades, quantities=[1.0] * 40 + [3.0] * 20)["variable"]


@pytest.mark.parametrize("martingale", [False, True])
def test_capital_uses_original_median_and_withholds_martingale_quantities(martingale: bool) -> None:
    trades = _trades(PROFITS)
    review = capital_review(
        trades,
        fees=None,
        starting_balance=10_000.0,
        platform_fall=4_000.0,
        quantities=[0.29] * len(trades),
        quantity_unit="lot",
        samples=100,
        martingale=martingale,
    )
    if martingale:
        assert all(row["quantity"]["evidence"] == "NOT_MEASURED" for row in review["rows"])
        assert "size grows after losses" in review["quantity_profile"]["median"]["note"]
    else:
        assert review["rows"][1]["quantity"]["value"] == 0.14
    assert untranslated({"capital": review}) == []


def test_copy_fall_is_linear_in_money_and_marks_the_entire_account() -> None:
    review = capital_review(
        _trades(PROFITS), fees=None, starting_balance=10_000.0, platform_fall=4_000.0, samples=100
    )
    rows = review["copy_rows"]
    assert [row["multiplier"] for row in rows] == list(COPY_MULTIPLIERS)
    assert [row["fall_pct"]["value"] for row in rows] == pytest.approx([0.2, 0.4, 0.8, 1.2])
    assert [row["account_lost"] for row in rows] == [False, False, False, True]
    at_boundary = capital_review(
        _trades(PROFITS), fees=None, starting_balance=10_000.0, platform_fall=5_000.0, samples=100
    )["copy_rows"][2]
    assert at_boundary["account_lost"] is True
    for locale, notice in [
        ("es", "pierde la cuenta entera"),
        ("en", "loses the entire account"),
        ("pt", "perde a conta inteira"),
    ]:
        assert notice in copy_fall_text(at_boundary, locale)
        assert find_claims(copy_fall_text(rows[-1], locale)) == []


def test_unknown_balance_and_missing_quantities_are_not_invented() -> None:
    review = capital_review(_trades(PROFITS), fees=None, starting_balance=None, samples=100)
    assert all(row["quantity"]["evidence"] == "NOT_MEASURED" for row in review["rows"])
    assert all(row["fall_pct"]["evidence"] == "NOT_MEASURED" for row in review["copy_rows"])
    assert not any(row["account_lost"] for row in review["copy_rows"])
    assert quantity_profile(_trades(PROFITS), unit="lot")["median"]["evidence"] == "NOT_MEASURED"
    assert quantity_profile(_trades(PROFITS), quantities=[])["median"]["evidence"] == "NOT_MEASURED"
