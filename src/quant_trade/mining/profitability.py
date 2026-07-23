"""Conservative mining profitability calculations with explicit shutdown gates."""

from __future__ import annotations

from datetime import UTC, datetime

from quant_trade.mining.models import (
    MiningEvaluation,
    MiningMarketSnapshot,
    MiningPolicy,
    MiningRig,
)

_DAYS_PER_MONTH = 30.0
_DAYS_PER_YEAR = 365.0
_UNATTRIBUTABLE_SOURCE_MARKERS = (
    "manual",
    "placeholder",
    "replace",
    "illustrative",
    "unknown",
    "example",
)


def _evaluation_time(value: datetime | None) -> datetime:
    evaluated_at = datetime.now(UTC) if value is None else value
    if evaluated_at.tzinfo is None:
        raise ValueError("evaluated_at_utc must be timezone-aware")
    return evaluated_at.astimezone(UTC)


def _snapshot_evidence(
    market: MiningMarketSnapshot,
    policy: MiningPolicy,
    evaluated_at: datetime,
) -> tuple[float | None, list[str]]:
    reasons: list[str] = []
    normalized_source = market.source.strip().casefold()
    if policy.require_attributable_market_source and (
        not normalized_source
        or any(marker in normalized_source for marker in _UNATTRIBUTABLE_SOURCE_MARKERS)
    ):
        reasons.append("market snapshot source is missing or not attributable")

    captured_at: datetime | None = None
    if market.captured_at_utc.strip():
        try:
            parsed = datetime.fromisoformat(market.captured_at_utc.strip().replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("timestamp has no timezone")
            captured_at = parsed.astimezone(UTC)
        except ValueError:
            captured_at = None

    age_hours: float | None = None
    if captured_at is not None:
        age_hours = (evaluated_at - captured_at).total_seconds() / 3600
    if policy.require_fresh_market_snapshot:
        if captured_at is None:
            reasons.append("market snapshot capture time is missing or invalid")
        elif age_hours is not None:
            future_tolerance = policy.max_future_clock_skew_minutes / 60
            if age_hours < -future_tolerance:
                reasons.append("market snapshot capture time is in the future")
            elif age_hours > policy.max_market_snapshot_age_hours:
                reasons.append(
                    "market snapshot is stale: "
                    f"{age_hours:.2f}h exceeds "
                    f"{policy.max_market_snapshot_age_hours:.2f}h"
                )
    return (max(0.0, age_hours) if age_hours is not None else None), reasons


def _present_value(
    *,
    capex_usd: float,
    daily_cash_flow_usd: float,
    residual_value_usd: float,
    horizon_days: int,
    annual_rate: float,
) -> float:
    """Present value of a level daily cash flow plus terminal residual value."""
    daily_rate = (1 + annual_rate) ** (1 / _DAYS_PER_YEAR) - 1
    if abs(daily_rate) < 1e-15:
        cash_flow_pv = daily_cash_flow_usd * horizon_days
    else:
        cash_flow_pv = daily_cash_flow_usd * (1 - (1 + daily_rate) ** (-horizon_days)) / daily_rate
    residual_pv = residual_value_usd * (1 + daily_rate) ** (-horizon_days)
    return -capex_usd + cash_flow_pv + residual_pv


def _annual_irr(
    *,
    capex_usd: float,
    daily_cash_flow_usd: float,
    residual_value_usd: float,
    horizon_days: int,
) -> float | None:
    """Return an annualized IRR by deterministic bisection, or None if undefined."""
    if capex_usd <= 0 or daily_cash_flow_usd <= 0:
        return None

    def value(rate: float) -> float:
        return _present_value(
            capex_usd=capex_usd,
            daily_cash_flow_usd=daily_cash_flow_usd,
            residual_value_usd=residual_value_usd,
            horizon_days=horizon_days,
            annual_rate=rate,
        )

    low = -0.999999
    high = 1.0
    if value(low) <= 0:
        return None
    while value(high) > 0 and high < 1_000_000:
        high *= 2
    if value(high) > 0:
        return None
    for _ in range(100):
        middle = (low + high) / 2
        if value(middle) > 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def evaluate_mining(
    rig: MiningRig,
    market: MiningMarketSnapshot,
    policy: MiningPolicy,
    evaluated_at_utc: datetime | None = None,
) -> MiningEvaluation:
    """Evaluate a rig/coin pair without network calls or process execution."""
    if rig.algorithm.casefold() != market.algorithm.casefold():
        raise ValueError(
            f"incompatible algorithms: rig={rig.algorithm!r}, market={market.algorithm!r}"
        )

    evaluated_at = _evaluation_time(evaluated_at_utc)
    snapshot_age_hours, evidence_reasons = _snapshot_evidence(market, policy, evaluated_at)

    expected_coin = (
        rig.hashrate_hs
        / market.network_hashrate_hs
        * market.block_reward_coin
        * market.blocks_per_day
        * rig.uptime_rate
    )
    realized_coin = expected_coin * (1 - rig.stale_reject_rate)
    gross = realized_coin * market.coin_price_usd
    pool_fee = gross * market.pool_fee_rate
    energy_kwh = rig.power_watts / 1000 * 24 * rig.uptime_rate * rig.pue
    electricity = 0.0 if rig.electricity_included else energy_kwh * policy.electricity_usd_per_kwh
    infrastructure = rig.infrastructure_hourly_cost_usd * 24 * rig.uptime_rate
    maintenance = rig.daily_maintenance_cost_usd
    demand_charge = rig.monthly_demand_charge_usd / _DAYS_PER_MONTH
    depreciable_capex = rig.total_capex_usd - rig.residual_value_usd
    depreciation = depreciable_capex / rig.useful_life_days
    pre_tax_net = (
        gross
        - pool_fee
        - electricity
        - infrastructure
        - rig.daily_operating_cost_usd
        - maintenance
        - demand_charge
        - depreciation
    )
    tax = max(0.0, pre_tax_net) * policy.tax_rate
    net = pre_tax_net - tax
    net_cash = net + depreciation

    difficulty_factor = (1 + policy.monthly_difficulty_growth_rate) ** (
        policy.stress_horizon_days / _DAYS_PER_MONTH
    )
    stressed_gross = gross * (1 - policy.price_haircut_rate) / difficulty_factor
    stressed_pool_fee = stressed_gross * market.pool_fee_rate
    stressed_pre_tax_net = (
        stressed_gross
        - stressed_pool_fee
        - electricity
        - infrastructure
        - rig.daily_operating_cost_usd
        - maintenance
        - demand_charge
        - depreciation
    )
    stressed_tax = max(0.0, stressed_pre_tax_net) * policy.tax_rate
    stressed_net = stressed_pre_tax_net - stressed_tax
    stressed_net_cash = stressed_net + depreciation
    margin = net / gross if gross else float("-inf")
    daily_non_energy_cost = (
        pool_fee
        + infrastructure
        + rig.daily_operating_cost_usd
        + maintenance
        + demand_charge
        + depreciation
    )

    break_even_electricity = None
    if not rig.electricity_included and energy_kwh > 0:
        available_for_energy = gross - daily_non_energy_cost
        break_even_electricity = max(0.0, available_for_energy / energy_kwh)

    fixed_cost_excluding_pool = (
        electricity
        + infrastructure
        + rig.daily_operating_cost_usd
        + maintenance
        + demand_charge
        + depreciation
    )
    net_coin_after_pool = realized_coin * (1 - market.pool_fee_rate)
    break_even_coin_price = (
        fixed_cost_excluding_pool / net_coin_after_pool if net_coin_after_pool > 0 else None
    )
    effective_th_per_day = rig.hashrate_hs / 1e12 * rig.uptime_rate * (1 - rig.stale_reject_rate)
    break_even_hashprice = (
        fixed_cost_excluding_pool / (effective_th_per_day * (1 - market.pool_fee_rate))
        if effective_th_per_day > 0 and market.pool_fee_rate < 1
        else None
    )
    production_cost = (
        (
            pool_fee
            + electricity
            + infrastructure
            + rig.daily_operating_cost_usd
            + maintenance
            + demand_charge
            + depreciation
        )
        / realized_coin
        if realized_coin > 0
        else None
    )
    npv = _present_value(
        capex_usd=rig.total_capex_usd,
        daily_cash_flow_usd=net_cash,
        residual_value_usd=rig.residual_value_usd,
        horizon_days=policy.analysis_horizon_days,
        annual_rate=policy.annual_discount_rate,
    )
    irr = _annual_irr(
        capex_usd=rig.total_capex_usd,
        daily_cash_flow_usd=net_cash,
        residual_value_usd=rig.residual_value_usd,
        horizon_days=policy.analysis_horizon_days,
    )
    annualized_roi = (
        net_cash * _DAYS_PER_YEAR / rig.total_capex_usd if rig.total_capex_usd > 0 else None
    )
    payback_days = (
        rig.total_capex_usd / net_cash if rig.total_capex_usd > 0 and net_cash > 0 else None
    )

    reasons: list[str] = list(evidence_reasons)
    if net < policy.min_daily_profit_usd:
        reasons.append("expected net profit is below the policy minimum")
    if margin < policy.min_margin_rate:
        reasons.append("expected net margin is below the policy minimum")
    if stressed_net <= 0:
        reasons.append("stressed net profit is not positive")
    if policy.require_positive_npv and npv <= 0:
        reasons.append("discounted project NPV is not positive")
    if rig.infrastructure_hourly_cost_usd > policy.max_cloud_hourly_cost_usd:
        reasons.append("cloud hourly cost exceeds the policy maximum")
    if rig.temperature_c is None and policy.require_temperature:
        reasons.append("temperature telemetry is required")
    elif rig.temperature_c is not None and rig.temperature_c > policy.max_temperature_c:
        reasons.append("temperature exceeds the policy maximum")

    return MiningEvaluation(
        rig=rig.name,
        coin=market.coin,
        decision="GO" if not reasons else "NO-GO",
        reasons=tuple(reasons),
        expected_coin_per_day=expected_coin,
        realized_coin_per_day=realized_coin,
        gross_revenue_usd=gross,
        monthly_revenue_usd=gross * _DAYS_PER_MONTH,
        annual_revenue_usd=gross * _DAYS_PER_YEAR,
        pool_fee_usd=pool_fee,
        electricity_cost_usd=electricity,
        infrastructure_cost_usd=infrastructure,
        operating_cost_usd=rig.daily_operating_cost_usd,
        maintenance_cost_usd=maintenance,
        demand_charge_usd=demand_charge,
        depreciation_usd=depreciation,
        tax_cost_usd=tax,
        net_profit_usd=net,
        net_cash_profit_usd=net_cash,
        monthly_net_profit_usd=net * _DAYS_PER_MONTH,
        annual_net_profit_usd=net * _DAYS_PER_YEAR,
        stressed_net_profit_usd=stressed_net,
        stressed_net_cash_profit_usd=stressed_net_cash,
        net_margin_rate=margin,
        break_even_electricity_usd_per_kwh=break_even_electricity,
        break_even_coin_price_usd=break_even_coin_price,
        break_even_hashprice_usd_per_th_day=break_even_hashprice,
        production_cost_usd_per_coin=production_cost,
        total_capex_usd=rig.total_capex_usd,
        efficiency_j_per_th=rig.efficiency_j_per_th,
        annualized_hardware_roi_rate=annualized_roi,
        payback_days=payback_days,
        npv_usd=npv,
        irr_annual_rate=irr,
        net_profit_mxn=net * policy.usd_mxn_rate if policy.usd_mxn_rate else None,
        market_source=market.source,
        market_captured_at_utc=market.captured_at_utc,
        market_snapshot_age_hours=snapshot_age_hours,
        market_snapshot_sha256=market.snapshot_sha256,
        evaluated_at_utc=evaluated_at.replace(microsecond=0).isoformat(),
    )


def evaluate_all(
    rigs: tuple[MiningRig, ...],
    markets: tuple[MiningMarketSnapshot, ...],
    policy: MiningPolicy,
    evaluated_at_utc: datetime | None = None,
) -> list[MiningEvaluation]:
    """Evaluate compatible pairs and rank by stressed profitability."""
    evaluated_at = _evaluation_time(evaluated_at_utc)
    evaluations = [
        evaluate_mining(rig, market, policy, evaluated_at)
        for rig in rigs
        for market in markets
        if rig.algorithm.casefold() == market.algorithm.casefold()
    ]
    if not evaluations:
        raise ValueError("no compatible rig/market algorithm pairs")
    return sorted(
        evaluations,
        key=lambda item: (item.stressed_net_profit_usd, item.net_profit_usd),
        reverse=True,
    )
