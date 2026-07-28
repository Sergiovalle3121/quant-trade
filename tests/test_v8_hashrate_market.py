"""V8 rented-hashrate scanner and dynamic cash-flow engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.v8.hashrate_cashflow import (
    DeliveryAssumptions,
    NetworkState,
    PoolTerms,
    PurchaseTerms,
    cancellation_outcome,
    evaluate_mining_purchase,
    expected_coins_per_unit_day,
)
from quant_trade.v8.hashrate_market import (
    MINING_GATES,
    NICEHASH_ALGO_INFO_URL,
    STATUS_BLOCKED_NETWORK,
    STATUS_DISCOVERY_ONLY,
    STATUS_PAPER_CANDIDATE,
    STATUS_REJECTED,
    MarketplaceQuote,
    evaluate_opportunity,
    hashes_per_unit,
    parse_nicehash_algo_info,
    parse_nicehash_orderbook,
    scan_marketplace,
)


def _purchase(**overrides) -> PurchaseTerms:
    defaults = dict(
        algorithm_id="sha256",
        coin="BTC",
        network="bitcoin-mainnet",
        native_unit="TH/s",
        units=100_000.0,
        price_usd_per_unit_day=0.020,
        duration_hours=72.0,
        buyer_fee_rate=0.03,
    )
    defaults.update(overrides)
    return PurchaseTerms(**defaults)


def _pool(**overrides) -> PoolTerms:
    defaults = dict(
        pool_name="test-pool",
        payout_scheme="FPPS",
        pool_fee_rate=0.02,
        minimum_payout_coin=0.001,
        withdrawal_cost_coin=0.00005,
    )
    defaults.update(overrides)
    return PoolTerms(**defaults)


def _network(**overrides) -> NetworkState:
    defaults = dict(
        difficulty=90e12,
        block_reward_coin=3.125,
        coin_price_usd=64_000.0,
        price_volatility_daily=0.01,
    )
    defaults.update(overrides)
    return NetworkState(**defaults)


def _evaluate(purchase=None, delivery=None, pool=None, network=None, **kwargs):
    return evaluate_mining_purchase(
        purchase or _purchase(),
        delivery or DeliveryAssumptions(),
        pool or _pool(),
        network or _network(),
        hashes_per_unit=hashes_per_unit("sha256"),
        samples=4000,
        **kwargs,
    )


def _quote(**overrides) -> MarketplaceQuote:
    defaults = dict(
        provider="nicehash",
        algorithm_id="sha256",
        coin="BTC",
        network="bitcoin-mainnet",
        native_unit="TH/s",
        price_usd_per_unit_day=0.020,
        available_units=1e6,
        min_order_units=0.01,
        min_duration_hours=24.0,
        buyer_fee_rate=0.03,
        captured_at_utc="2026-07-28T00:00:00Z",
        raw_sha256="0" * 64,
        evidence_class="REAL",
        source_url=NICEHASH_ALGO_INFO_URL,
    )
    defaults.update(overrides)
    return MarketplaceQuote(**defaults)


# --- units ----------------------------------------------------------------------


def test_expected_coins_matches_the_difficulty_formula() -> None:
    """One TH/s at difficulty 90e12 with a 3.125 BTC reward."""
    per_day = expected_coins_per_unit_day(
        network="bitcoin-mainnet",
        difficulty=90e12,
        block_reward_coin=3.125,
        hashes_per_unit=1e12,
    )
    expected = 1e12 * 86_400.0 * 3.125 / (90e12 * 4_294_967_296.0)
    assert per_day == pytest.approx(expected, rel=1e-12)
    assert per_day == pytest.approx(6.98e-7, rel=0.02)


def test_unknown_network_refuses_to_guess_a_block_interval() -> None:
    with pytest.raises(ValueError, match="refusing to guess"):
        expected_coins_per_unit_day(
            network="dogecoin-mainnet",
            difficulty=1.0,
            block_reward_coin=1.0,
            hashes_per_unit=1e12,
        )


def test_algorithm_units_come_from_the_registry() -> None:
    assert hashes_per_unit("sha256") == pytest.approx(1e12)
    with pytest.raises(ValueError, match="unknown algorithm"):
        hashes_per_unit("scrypt")


# --- cash-flow engine -------------------------------------------------------------


def test_cash_flow_lines_sum_to_the_reported_profit() -> None:
    result = _evaluate()
    assert sum(line.usd for line in result.cash_flows) == pytest.approx(result.profit_usd)


def test_pool_fee_is_charged_exactly_once() -> None:
    """It is netted out of the coins AND listed as a cost; only one may count."""
    with_fee = _evaluate(pool=_pool(pool_fee_rate=0.02))
    without_fee = _evaluate(pool=_pool(pool_fee_rate=0.0))
    gross = next(c for c in with_fee.cash_flows if c.name == "gross_mining_revenue").usd
    fee = -next(c for c in with_fee.cash_flows if c.name == "pool_fee").usd
    assert fee == pytest.approx(gross * 0.02)
    assert without_fee.profit_usd > with_fee.profit_usd


def test_a_balance_below_the_pool_minimum_is_worth_nothing() -> None:
    result = _evaluate(purchase=_purchase(units=100.0))
    assert result.stranded_below_minimum
    assert result.coins_received == 0.0
    assert result.revenue_usd == 0.0
    assert result.profit_usd < 0
    assert any("below the pool minimum" in p for p in result.problems)


def test_withdrawal_cost_is_deducted_from_what_arrives() -> None:
    cheap = _evaluate(pool=_pool(withdrawal_cost_coin=0.0))
    dear = _evaluate(pool=_pool(withdrawal_cost_coin=0.01))
    assert dear.coins_received < cheap.coins_received
    assert dear.profit_usd < cheap.profit_usd


def test_delivery_shortfall_and_stale_shares_reduce_output() -> None:
    full = _evaluate(
        delivery=DeliveryAssumptions(
            delivered_ratio=1.0,
            delivered_ratio_p05=1.0,
            stale_share_rate=0.0,
            reject_share_rate=0.0,
        )
    )
    lossy = _evaluate(
        delivery=DeliveryAssumptions(
            delivered_ratio=0.9,
            delivered_ratio_p05=0.8,
            stale_share_rate=0.02,
            reject_share_rate=0.02,
        )
    )
    assert lossy.gross_coins_mined < full.gross_coins_mined
    assert lossy.profit_usd < full.profit_usd


def test_rising_difficulty_reduces_output() -> None:
    flat = _evaluate(network=_network(difficulty_drift_per_day=0.0))
    rising = _evaluate(network=_network(difficulty_drift_per_day=0.02))
    assert rising.gross_coins_mined < flat.gross_coins_mined


def test_committed_capital_includes_escrow_and_unused_funds() -> None:
    plain = _evaluate()
    encumbered = _evaluate(purchase=_purchase(escrow_usd=500.0, deposited_usd=10_000.0))
    assert encumbered.committed_capital_usd > plain.committed_capital_usd
    names = {line.name for line in encumbered.cash_flows}
    assert {"escrow_opportunity_cost", "unused_funds_opportunity_cost"} <= names
    assert encumbered.profit_usd < plain.profit_usd


def test_pplns_carries_luck_variance_and_pps_does_not() -> None:
    pps = _evaluate(pool=_pool(payout_scheme="FPPS", luck_volatility=0.25))
    pplns = _evaluate(pool=_pool(payout_scheme="PPLNS", luck_volatility=0.25))
    pps_spread = pps.scenarios["p95_profit_usd"] - pps.scenarios["p05_profit_usd"]
    pplns_spread = pplns.scenarios["p95_profit_usd"] - pplns.scenarios["p05_profit_usd"]
    assert pplns_spread > pps_spread


def test_scenarios_are_ordered_and_deterministic() -> None:
    first = _evaluate()
    second = _evaluate()
    assert first.scenarios == second.scenarios
    assert (
        first.scenarios["p05_profit_usd"]
        <= first.scenarios["p50_profit_usd"]
        <= first.scenarios["p95_profit_usd"]
    )
    assert first.cvar95_usd <= first.scenarios["p05_profit_usd"]


def test_result_is_never_annualized() -> None:
    payload = _evaluate().to_dict()
    assert payload["annualized"] is None
    assert "not annualized" in payload["annualization_note"]
    assert payload["horizon_days"] == pytest.approx(3.0)


def test_a_genuinely_cheap_purchase_is_profitable() -> None:
    """Without this the engine could be a constant 'no' and look rigorous."""
    result = _evaluate(purchase=_purchase(price_usd_per_unit_day=0.020))
    assert result.profitable
    assert result.scenarios["p05_profit_usd"] > 0
    assert result.loss_probability < 0.05
    assert result.problems == []


def test_an_expensive_purchase_loses_money() -> None:
    result = _evaluate(purchase=_purchase(price_usd_per_unit_day=0.30))
    assert not result.profitable
    assert result.loss_probability > 0.9


def test_order_below_the_marketplace_minimum_is_rejected() -> None:
    with pytest.raises(ValueError, match="below the marketplace minimum"):
        _purchase(units=0.001, min_order_units=1.0)
    with pytest.raises(ValueError, match="below the marketplace minimum"):
        _purchase(duration_hours=1.0, min_duration_hours=24.0)


def test_unknown_payout_scheme_is_rejected() -> None:
    with pytest.raises(ValueError, match="payout_scheme must be one of"):
        _pool(payout_scheme="TRUST_ME")


def test_cancellation_is_not_a_free_exit() -> None:
    purchase = _purchase(cancellation_refund_rate=0.5, cancellation_penalty_usd=10.0)
    outcome = cancellation_outcome(purchase, elapsed_hours=24.0)
    assert outcome["consumed_fraction"] == pytest.approx(1 / 3)
    assert outcome["refund_received_usd"] < outcome["refundable_usd"]
    assert outcome["unrecovered_usd"] > 0
    assert outcome["buyer_fee_refundable"] is False
    assert outcome["idle_capital_opportunity_cost_usd"] > 0


def test_cancelling_at_the_end_refunds_nothing() -> None:
    purchase = _purchase(cancellation_refund_rate=1.0)
    outcome = cancellation_outcome(purchase, elapsed_hours=1000.0)
    assert outcome["consumed_fraction"] == pytest.approx(1.0)
    assert outcome["refund_received_usd"] == pytest.approx(0.0)


# --- scanner -----------------------------------------------------------------------


def test_blocked_marketplace_records_the_verbatim_error() -> None:
    def blocked(_url: str):
        raise OSError("CONNECT tunnel failed, response 403")

    scan = scan_marketplace(scanned_at_utc="2026-07-28T00:00:00Z", fetcher=blocked)
    assert scan.status == STATUS_BLOCKED_NETWORK
    assert "api2.nicehash.com" in scan.blocked_hosts
    assert any("CONNECT tunnel failed, response 403" in e for e in scan.errors)
    assert scan.quotes == []
    assert scan.to_dict()["purchase_authorized"] is False


def test_scan_without_a_btc_rate_refuses_to_invent_one() -> None:
    payload = json.dumps({"miningAlgorithms": [{"name": "SHA256", "paying": "0.0000004"}]}).encode()
    scan = scan_marketplace(
        scanned_at_utc="2026-07-28T00:00:00Z",
        fetcher=lambda _url: (200, payload, {}),
    )
    assert scan.status == STATUS_DISCOVERY_ONLY
    assert any("BTC/USD rate from verified evidence" in e for e in scan.errors)
    assert scan.quotes == []


def test_scan_parses_quotes_and_stays_discovery_only(tmp_path: Path) -> None:
    payload = json.dumps(
        {"miningAlgorithms": [{"name": "SHA256", "paying": "0.0000004", "speed": "1"}]}
    ).encode()
    scan = scan_marketplace(
        scanned_at_utc="2026-07-28T00:00:00Z",
        btc_usd=64_000.0,
        fetcher=lambda _url: (200, payload, {}),
        evidence_dir=tmp_path,
    )
    assert scan.status == STATUS_DISCOVERY_ONLY
    assert len(scan.quotes) == 1
    assert scan.quotes[0].algorithm_id == "sha256"
    assert scan.quotes[0].price_usd_per_unit_day == pytest.approx(0.0000004 * 64_000.0)
    assert scan.quotes[0].evidence_class == "RECORDED_RESPONSE"
    assert (tmp_path / "scan.json").exists()


def test_orderbook_rungs_are_priced_in_usd() -> None:
    payload = json.dumps(
        {
            "stats": {
                "EU": {
                    "orders": [
                        {"price": "0.0000005", "limit": "10"},
                        {"price": "0.0000003", "limit": "5"},
                    ]
                }
            }
        }
    ).encode()
    quotes = parse_nicehash_orderbook(
        payload,
        algorithm_id="sha256",
        captured_at_utc="2026-07-28T00:00:00Z",
        evidence_class="RECORDED_RESPONSE",
        btc_usd=64_000.0,
        buyer_fee_rate=0.03,
        min_order_units=0.01,
        min_duration_hours=24.0,
    )
    assert [q.price_usd_per_unit_day for q in quotes] == sorted(
        q.price_usd_per_unit_day for q in quotes
    )
    assert quotes[0].price_usd_per_unit_day == pytest.approx(0.0000003 * 64_000.0)


def test_parsers_refuse_a_zero_btc_rate() -> None:
    with pytest.raises(ValueError, match="btc_usd must be > 0"):
        parse_nicehash_algo_info(
            b'{"miningAlgorithms":[]}',
            captured_at_utc="x",
            evidence_class="RECORDED_RESPONSE",
            btc_usd=0.0,
        )


# --- gating -------------------------------------------------------------------------


def test_no_delivery_history_caps_at_discovery_only() -> None:
    opportunity = evaluate_opportunity(
        _quote(), economics=_evaluate(), delivery_history_available=False
    )
    assert opportunity.status == STATUS_DISCOVERY_ONLY
    assert any("delivery_history_available" in r for r in opportunity.blocking_reasons)


def test_delivery_history_plus_good_economics_reaches_paper_candidate() -> None:
    opportunity = evaluate_opportunity(
        _quote(), economics=_evaluate(), delivery_history_available=True
    )
    assert opportunity.status == STATUS_PAPER_CANDIDATE
    assert opportunity.blocking_reasons == []
    assert opportunity.to_dict()["purchase_authorized"] is False
    assert opportunity.to_dict()["deposit_authorized"] is False


def test_bad_economics_are_rejected_even_with_delivery_history() -> None:
    economics = _evaluate(purchase=_purchase(price_usd_per_unit_day=0.30))
    opportunity = evaluate_opportunity(
        _quote(price_usd_per_unit_day=0.30),
        economics=economics,
        delivery_history_available=True,
    )
    assert opportunity.status == STATUS_REJECTED
    assert any("centre_profit_positive" in r for r in opportunity.blocking_reasons)


def test_mining_gates_are_conservative() -> None:
    assert MINING_GATES["require_delivery_history"] is True
    assert MINING_GATES["require_positive_p05_profit"] is True
    assert MINING_GATES["max_loss_probability"] <= 0.20
    assert MINING_GATES["require_beats_holding_coin"] is True
