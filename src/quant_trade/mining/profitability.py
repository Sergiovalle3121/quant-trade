"""Conservative mining profitability calculations with explicit shutdown gates."""

from __future__ import annotations

from quant_trade.mining.models import (
    MiningEvaluation,
    MiningMarketSnapshot,
    MiningPolicy,
    MiningRig,
)


def evaluate_mining(
    rig: MiningRig,
    market: MiningMarketSnapshot,
    policy: MiningPolicy,
) -> MiningEvaluation:
    """Evaluate a rig/coin pair without network calls or process execution."""
    if rig.algorithm.casefold() != market.algorithm.casefold():
        raise ValueError(
            f"incompatible algorithms: rig={rig.algorithm!r}, market={market.algorithm!r}"
        )

    expected_coin = (
        rig.hashrate_hs
        / market.network_hashrate_hs
        * market.block_reward_coin
        * market.blocks_per_day
        * rig.uptime_rate
    )
    gross = expected_coin * market.coin_price_usd
    pool_fee = gross * market.pool_fee_rate
    energy_kwh = rig.power_watts / 1000 * 24 * rig.uptime_rate
    electricity = 0.0 if rig.electricity_included else energy_kwh * policy.electricity_usd_per_kwh
    infrastructure = rig.infrastructure_hourly_cost_usd * 24 * rig.uptime_rate
    depreciation = rig.hardware_cost_usd / rig.useful_life_days
    net = (
        gross
        - pool_fee
        - electricity
        - infrastructure
        - rig.daily_operating_cost_usd
        - depreciation
    )

    difficulty_factor = (1 + policy.monthly_difficulty_growth_rate) ** (
        policy.stress_horizon_days / 30
    )
    stressed_gross = gross * (1 - policy.price_haircut_rate) / difficulty_factor
    stressed_pool_fee = stressed_gross * market.pool_fee_rate
    stressed_net = (
        stressed_gross
        - stressed_pool_fee
        - electricity
        - infrastructure
        - rig.daily_operating_cost_usd
        - depreciation
    )
    margin = net / gross if gross else float("-inf")

    break_even_electricity = None
    if not rig.electricity_included and energy_kwh > 0:
        available_for_energy = (
            gross
            - pool_fee
            - infrastructure
            - rig.daily_operating_cost_usd
            - depreciation
        )
        break_even_electricity = max(0.0, available_for_energy / energy_kwh)

    annualized_roi = (
        net * 365 / rig.hardware_cost_usd if rig.hardware_cost_usd > 0 else None
    )
    payback_days = rig.hardware_cost_usd / net if rig.hardware_cost_usd > 0 and net > 0 else None

    reasons: list[str] = []
    if net < policy.min_daily_profit_usd:
        reasons.append("expected net profit is below the policy minimum")
    if margin < policy.min_margin_rate:
        reasons.append("expected net margin is below the policy minimum")
    if stressed_net <= 0:
        reasons.append("stressed net profit is not positive")
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
        gross_revenue_usd=gross,
        pool_fee_usd=pool_fee,
        electricity_cost_usd=electricity,
        infrastructure_cost_usd=infrastructure,
        operating_cost_usd=rig.daily_operating_cost_usd,
        depreciation_usd=depreciation,
        net_profit_usd=net,
        stressed_net_profit_usd=stressed_net,
        net_margin_rate=margin,
        break_even_electricity_usd_per_kwh=break_even_electricity,
        annualized_hardware_roi_rate=annualized_roi,
        payback_days=payback_days,
    )


def evaluate_all(
    rigs: tuple[MiningRig, ...],
    markets: tuple[MiningMarketSnapshot, ...],
    policy: MiningPolicy,
) -> list[MiningEvaluation]:
    """Evaluate compatible pairs and rank by stressed profitability."""
    evaluations = [
        evaluate_mining(rig, market, policy)
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

