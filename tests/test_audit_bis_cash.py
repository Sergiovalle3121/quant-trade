"""Cash rates of more currencies from the BIS's policy rates. Offline: every
reply is stubbed in the shape the BIS sends."""

from __future__ import annotations

from dataclasses import replace
from html import escape

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes

from quant_trade.audit.cashrate import BIS_BASIS, LOCAL, local_span_cash
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.market import (
    BIS_POLICY_AREAS,
    CASH,
    LOCAL_CASH,
    MAX_LOCAL_RATE,
    SERIES,
    MarketData,
    parse_rates,
)
from quant_trade.audit.pages import method_page
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs

DAYS = pd.bdate_range("2023-01-02", periods=300)


def _bis(area: str, rows: list[tuple[str, str]]) -> str:
    body = "".join(f"M,{area},{month},{value}\n" for month, value in rows)
    return "FREQ,REF_AREA,TIME_PERIOD,OBS_VALUE\n" + body


def _months(first: str, last: str, value: str) -> list[tuple[str, str]]:
    return [(str(month), value) for month in pd.period_range(first, last, freq="M")]


def test_every_bis_currency_is_a_monthly_bis_series_with_its_own_day_count() -> None:
    assert set(BIS_BASIS) == set(BIS_POLICY_AREAS)
    by_code = {asset.label: asset for asset in LOCAL_CASH}
    for code, area in BIS_POLICY_AREAS.items():
        asset = by_code[code]
        assert asset.provider == "bis" and asset.series == area and asset.monthly
        assert asset.key in SERIES and LOCAL[code].asset is asset
        assert LOCAL[code].basis == BIS_BASIS[code] in (360.0, 365.0)
    ten = np.array([10.0])
    assert LOCAL["AUD"].yearly(ten)[0] == pytest.approx((1 + 0.10 / 365) ** 365 - 1)
    assert LOCAL["SEK"].yearly(ten)[0] == pytest.approx((1 + 0.10 / 360) ** 365 - 1)
    assert LOCAL["TRY"].yearly(ten)[0] == pytest.approx((1 + 0.10 / 365) ** 365 - 1)
    # Left out on purpose: no usable series, or not a cash rate.
    for code in ("RUB", "ARS", "PHP", "SGD", "CNY", "HKD"):
        assert code not in LOCAL


def test_a_bis_reply_is_read_on_month_ends_and_a_reply_out_of_range_is_refused() -> None:
    rates = parse_rates(_bis("AU", [("2026-07", "4.35"), ("2026-08", "4.35")]), "bis", "AU")
    assert list(rates.index) == [pd.Timestamp("2026-07-31"), pd.Timestamp("2026-08-31")]
    with pytest.raises(ValueError):
        parse_rates(_bis("NZ", [("2026-08", "2.5")]), "bis", "AU")
    turkey = MarketData(lambda series: _bis("TR", _months("2002-02", "2026-08", "57")))
    assert turkey.refresh("cash_try") is True
    broken = MarketData(lambda series: _bis("TR", [("2026-07", "40"), ("2026-08", "900")]))
    assert MAX_LOCAL_RATE < 900 and broken.refresh("cash_try") is False


def _account(currency: str, locale: str) -> tuple[object, dict[str, pd.Series]]:
    key = LOCAL[currency].asset.key
    start = (DAYS[0] - pd.Timedelta(days=62)).to_period("M")
    months = pd.period_range(start, DAYS[-1].to_period("M"), freq="M")
    rates = {
        key: pd.Series(6.0, index=months.to_timestamp(how="end").normalize()),
        CASH.key: pd.Series(5.0, index=pd.bdate_range(DAYS[0] - pd.Timedelta(days=30), DAYS[-1])),
    }
    stamps = pd.Series(DAYS.tz_localize("UTC") + pd.Timedelta(hours=21))
    own = local_span_cash(stamps, rates[key], currency)
    assert own is not None
    noise = np.random.default_rng(4).normal(0.0, 0.004, len(own))
    curve = pd.DataFrame(
        {"timestamp": stamps, "equity": 10_000 * np.cumprod(np.r_[1.0, 1.0 + own + noise])}
    )
    inputs = build_inputs(csv_bytes(curve), DeclaredMetadata(locale=locale))
    return replace(inputs, account_currency=currency), rates


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
@pytest.mark.parametrize("currency", ["AUD", "INR", "ZAR", "CLP", "TRY"])
def test_an_account_in_a_bis_currency_subtracts_its_policy_rate(currency: str, locale: str) -> None:
    inputs, rates = _account(currency, locale)
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=rates.get)
    cash = result.cash_rate
    assert cash is not None and cash["status"] == "MEASURED" and cash["currency"] == currency
    assert cash["series"] == BIS_POLICY_AREAS[currency] and cash["source_name"] == "BIS"
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    assert escape(LABELS[locale][f"cash_rate_{currency}"]) in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_every_bis_currency_is_named_and_credited_in_three_languages() -> None:
    for locale in ("es", "en", "pt"):
        for code in BIS_POLICY_AREAS:
            label = LABELS[locale][f"cash_rate_{code}"]
            assert label.endswith("(BIS)") and find_claims(label) == [], (locale, code)
    names = {
        "es": ("Australia", "Sudáfrica", "Corea del Sur", "Turquía", "Perú"),
        "en": ("Australia", "South Africa", "South Korea", "Türkiye", "Peru"),
        "pt": ("Austrália", "África do Sul", "Coreia do Sul", "Turquia", "Peru"),
    }
    for locale, words in names.items():
        page = method_page(locale=locale)
        assert "BIS" in page
        for name in words:
            assert escape(name) in page, (locale, name)
