"""Tests for electricity tariffs and pool payout economics."""

from __future__ import annotations

import pytest

from quant_trade.mining.pool import PayoutScheme, PoolModel, expected_pool_revenue
from quant_trade.mining.tariffs import ElectricityTariff, cfe_receipt_template

# --- tariffs --------------------------------------------------------------


def test_flat_tariff_blended_rate_includes_pue_and_tax():
    t = ElectricityTariff(flat_rate_usd_per_kwh=0.10, pue=1.1, tax_surcharge_rate=0.16)
    assert t.blended_energy_rate() == pytest.approx(0.10 * 1.1 * 1.16)


def test_tou_tariff_weights_peak_and_offpeak():
    t = ElectricityTariff(
        peak_rate_usd_per_kwh=0.20, offpeak_rate_usd_per_kwh=0.05, peak_hours_per_day=6.0
    )
    expected = (6 / 24) * 0.20 + (18 / 24) * 0.05
    assert t.blended_energy_rate() == pytest.approx(expected)


def test_demand_charge_and_monthly_cost():
    t = ElectricityTariff(flat_rate_usd_per_kwh=0.08, demand_charge_usd_per_kw_month=10.0)
    cost = t.monthly_cost(load_kw=3.5, requested_uptime=1.0)
    assert cost["demand_charge_usd"] == pytest.approx(35.0)
    assert cost["kwh"] == pytest.approx(3.5 * 24 * 30)
    assert cost["total_usd"] > cost["energy_cost_usd"]


def test_curtailment_reduces_uptime():
    t = ElectricityTariff(flat_rate_usd_per_kwh=0.08, curtailment_hours_per_day=6.0)
    assert t.effective_uptime(1.0) == pytest.approx(0.75)


def test_max_contracted_demand_is_enforced():
    t = ElectricityTariff(flat_rate_usd_per_kwh=0.08, max_contracted_demand_kw=3.0)
    with pytest.raises(ValueError, match="max contracted demand"):
        t.monthly_cost(load_kw=5.0)


def test_tariff_requires_some_energy_rate():
    with pytest.raises(ValueError, match="flat, TOU, or all-inclusive"):
        ElectricityTariff()


def test_cfe_template_is_placeholders_not_a_rate():
    template = cfe_receipt_template()
    assert template["peak_rate_usd_per_kwh"] is None  # must be filled per-site
    assert "tariff_class" in template


# --- pool -----------------------------------------------------------------


def test_pps_does_not_pay_tx_fees():
    model = PoolModel(scheme=PayoutScheme.PPS, pool_fee_rate=0.02)
    payout = expected_pool_revenue(
        subsidy_revenue_usd=100.0, tx_fee_revenue_usd=20.0, model=model
    )
    assert payout.tx_fees_paid is False
    assert payout.revenue_before_fee_usd == pytest.approx(100.0)
    assert payout.pool_fee_usd == pytest.approx(2.0)


def test_fpps_pays_tx_fees():
    model = PoolModel(scheme=PayoutScheme.FPPS, pool_fee_rate=0.02)
    payout = expected_pool_revenue(
        subsidy_revenue_usd=100.0, tx_fee_revenue_usd=20.0, model=model
    )
    assert payout.tx_fees_paid is True
    assert payout.revenue_before_fee_usd == pytest.approx(120.0)


def test_pplns_flags_variance():
    model = PoolModel(scheme=PayoutScheme.PPLNS)
    payout = expected_pool_revenue(subsidy_revenue_usd=100.0, tx_fee_revenue_usd=20.0, model=model)
    assert payout.variance_note is not None
    assert "PPLNS" in payout.variance_note


def test_stale_reject_reduces_effective_revenue():
    model = PoolModel(scheme=PayoutScheme.FPPS, pool_fee_rate=0.0, stale_reject_rate=0.05)
    payout = expected_pool_revenue(subsidy_revenue_usd=100.0, tx_fee_revenue_usd=0.0, model=model)
    assert payout.effective_after_stale_usd == pytest.approx(95.0)


def test_counterparty_risk_is_surfaced():
    model = PoolModel(scheme=PayoutScheme.FPPS, counterparty_risk_score=0.8)
    payout = expected_pool_revenue(subsidy_revenue_usd=50.0, tx_fee_revenue_usd=5.0, model=model)
    assert payout.counterparty_risk_score == 0.8
