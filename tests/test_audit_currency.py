"""The result in other currencies and after US inflation. Offline: FRED is stubbed."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes

from quant_trade.audit.currency import (
    ASSUMED_USD,
    CPI_NOT_COVERED,
    OTHER_CURRENCY,
    UNAVAILABLE,
    in_currencies,
    series_keys,
)
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.market import SERIES, MarketData
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs


def _curve(days: pd.DatetimeIndex, levels: np.ndarray) -> pd.DataFrame:
    stamps = pd.DatetimeIndex(days).tz_localize("UTC") + pd.Timedelta(hours=21)
    return pd.DataFrame({"timestamp": stamps, "equity": levels})


def _daily(days: pd.DatetimeIndex, start: float, end: float) -> pd.Series:
    """A rate moving in a straight line over the curve's days (flat the week before)."""
    before = pd.date_range(days[0] - pd.Timedelta(days=7), periods=7, freq="D")
    during = pd.date_range(days[0].normalize(), days[-1], freq="D")
    values = np.r_[np.full(len(before), start), np.linspace(start, end, len(during))]
    return pd.Series(values, index=before.append(during))


def _monthly(days: pd.DatetimeIndex, start: float, end: float) -> pd.Series:
    index = pd.date_range(days[0].to_period("M").to_timestamp(), days[-1], freq="MS")
    return pd.Series(np.linspace(start, end, len(index)), index=index)


def test_a_flat_dollar_curve_gains_in_a_currency_that_fell() -> None:
    days = pd.date_range("2023-01-02", periods=200, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    out = in_currencies(
        frame,
        {"fx_mxn": _daily(days, 20.0, 25.0), "fx_eur": _daily(days, 1.10, 1.00)},
        "USD",
    )
    assert out["status"] == "MEASURED"
    by_code = {item["code"]: item for item in out["currencies"]}
    # Pesos per dollar 20 -> 25: the same dollars buy 25 % more pesos.
    assert by_code["MXN"]["total_return"]["value"] == pytest.approx(0.25, rel=1e-3)
    # Dollars per euro 1.10 -> 1.00: the same dollars buy 10 % more euros.
    assert by_code["EUR"]["total_return"]["value"] == pytest.approx(0.10, rel=1e-3)
    assert out["dollars"]["total_return"]["value"] == 0.0
    assert "yearly_return" not in out["dollars"]  # under a year of history
    assert set(by_code) == {"MXN", "EUR"}  # a currency not read is left out
    assert "assumption" not in out


def test_a_currency_that_rose_deepens_the_worst_fall() -> None:
    days = pd.date_range("2022-01-03", periods=400, freq="D")
    levels = 10_000 * np.r_[np.linspace(1.0, 0.9, 200), np.linspace(0.9, 1.0, 200)]
    out = in_currencies(_curve(days, levels), {"fx_brl": _daily(days, 5.0, 4.0)}, None)
    brl = out["currencies"][0]
    assert out["dollars"]["worst_fall"]["value"] == pytest.approx(-0.10, abs=1e-3)
    assert brl["worst_fall"]["value"] < out["dollars"]["worst_fall"]["value"] - 0.05
    assert "yearly_return" in brl
    assert out["assumption"] == ASSUMED_USD


def test_us_inflation_is_taken_out_of_the_dollar_result() -> None:
    days = pd.date_range("2022-01-01", periods=731, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    cpi = _monthly(days, 300.0, 318.0)
    out = in_currencies(frame, {"cpi": cpi}, "USD")
    real = out["real"]
    assert real["status"] == "MEASURED"
    inflation = real["inflation"]["value"]
    assert inflation == pytest.approx(318.0 / 300.0 - 1.0, rel=1e-6)
    assert real["total_return"]["value"] == pytest.approx(1.0 / (1.0 + inflation) - 1.0)
    assert real["yearly_inflation"]["value"] > 0
    # Only the dollar row carries a deflator; no FX read still measures it.
    assert out["status"] == "MEASURED" and out["currencies"] == []


def test_prices_that_stop_early_do_not_deflate() -> None:
    days = pd.date_range("2022-01-01", periods=400, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    early = pd.Series(300.0, index=pd.date_range("2021-01-01", "2022-06-01", freq="MS"))
    assert in_currencies(frame, {"cpi": early}, "USD")["real"]["reason"] == CPI_NOT_COVERED


def test_an_account_in_another_currency_is_left_out_and_cents_count_as_dollars() -> None:
    days = pd.date_range("2023-01-02", periods=200, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    series = {"fx_mxn": _daily(days, 20.0, 25.0)}
    assert in_currencies(frame, series, "EUR")["reason"] == OTHER_CURRENCY
    assert in_currencies(frame, series, "usc")["status"] == "MEASURED"


def test_rates_that_stop_early_leave_that_currency_out() -> None:
    days = pd.date_range("2023-01-02", periods=200, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    stale = _daily(days, 20.0, 25.0).iloc[:100]
    out = in_currencies(frame, {"fx_mxn": stale}, "USD")
    assert out["status"] == "NOT_MEASURED" and out["reason"] == UNAVAILABLE


def test_the_series_are_kept_by_the_service_and_bounded() -> None:
    for key in series_keys():
        assert key in SERIES
    bad = MarketData(lambda series: "DATE,DEXMXUS\n2024-01-02,17.1\n2024-01-03,99999\n")
    assert bad.refresh("fx_mxn") is False and bad.closes("fx_mxn") is None
    tiny = MarketData(lambda series: "DATE,DEXMXUS\n2024-01-02,17.1\n2024-01-03,1e-300\n")
    assert tiny.refresh("fx_mxn") is False and tiny.closes("fx_mxn") is None
    good = MarketData(lambda series: "DATE,DEXMXUS\n2024-01-02,17.1\n2024-01-03,17.2\n")
    assert good.refresh("fx_mxn") is True


def _market(days: pd.DatetimeIndex) -> dict[str, pd.Series]:
    return {
        "fx_mxn": _daily(days, 18.0, 20.0),
        "fx_brl": _daily(days, 5.0, 5.5),
        "fx_eur": _daily(days, 1.08, 1.12),
        "fx_gbp": _daily(days, 1.25, 1.30),
        "fx_jpy": _daily(days, 140.0, 150.0),
        "fx_cad": _daily(days, 1.35, 1.40),
        "fx_chf": _daily(days, 0.90, 0.88),
        "cpi": _monthly(days, 300.0, 310.0),
    }


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_the_report_shows_the_currencies(locale: str) -> None:
    days = pd.bdate_range("2022-01-03", periods=400)
    rng = np.random.default_rng(3)
    frame = _curve(days, 10_000 * np.cumprod(1 + rng.normal(0.0005, 0.006, len(days))))
    inputs = build_inputs(csv_bytes(frame), DeclaredMetadata(locale=locale))
    series = _market(days)
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=series.get)
    assert result.in_currencies is not None and result.in_currencies["status"] == "MEASURED"
    assert len(result.in_currencies["currencies"]) == 7
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    for key in ("currency", "currency_MXN", "currency_real", "currency_assumed"):
        assert labels[key] in html, key
    for key, text in labels.items():
        if key.startswith("currency"):
            assert find_claims(text) == [], key
    assert untranslated(result.model_dump(mode="json")) == []
    plain = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert plain.in_currencies is None
    assert labels["currency"] not in render(plain, watermark=False)[0]


def test_public_data_down_is_not_measured_in_words() -> None:
    days = pd.bdate_range("2022-01-03", periods=300)
    frame = _curve(days, 10_000 * np.cumprod(1 + np.full(len(days), 0.0004)))
    inputs = build_inputs(csv_bytes(frame), DeclaredMetadata(locale="es"))

    def broken(key: str) -> pd.Series:
        raise OSError("down")

    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=broken)
    assert result.in_currencies is not None
    assert result.in_currencies["status"] == "NOT_MEASURED"
    html = render(result, watermark=False)[0]
    assert_report_clean(html)
    assert "no se pudieron leer los tipos de cambio" in html
    assert untranslated(result.model_dump(mode="json")) == []


def test_an_imported_report_names_the_account_currency() -> None:
    from pathlib import Path

    data = (Path(__file__).parent / "fixtures" / "audit_imports" / "mt5_tester.html").read_bytes()
    inputs = build_inputs(
        None, DeclaredMetadata(locale="es"), report_bytes=data, report_filename="r.html"
    )
    assert inputs.account_currency == "USD"
    days = pd.date_range("2023-01-02", periods=200, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    out = in_currencies(frame, {"fx_mxn": _daily(days, 20.0, 25.0)}, inputs.account_currency)
    assert "assumption" not in out


def test_broken_public_data_never_stops_the_audit() -> None:
    days = pd.bdate_range("2022-01-03", periods=300)
    frame = _curve(days, 10_000 * np.cumprod(1 + np.full(len(days), 0.0004)))
    inputs = build_inputs(csv_bytes(frame), DeclaredMetadata(locale="es"))
    words = pd.Series(["x"] * len(days), index=days)

    def market(key: str) -> pd.Series | None:
        return words if key == "vix" or key in series_keys() else None

    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=market)
    assert result.in_currencies is not None and result.in_currencies["status"] == "NOT_MEASURED"
    assert result.vix_regime is not None and result.vix_regime["status"] == "NOT_MEASURED"
    assert untranslated(result.model_dump(mode="json")) == []


def test_a_long_account_currency_is_cut() -> None:
    days = pd.date_range("2023-01-02", periods=200, freq="D")
    frame = _curve(days, np.full(len(days), 10_000.0))
    out = in_currencies(frame, {}, "<b>" * 2000)
    assert out["reason"] == OTHER_CURRENCY and len(out["account_currency"]) <= 8
