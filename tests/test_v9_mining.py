"""Mining acceptance tests: units, cash flow, evidence ceiling, shadow window.

Each test names the specific way rented-hashrate economics is usually
overstated, and asserts that this code refuses to do it.
"""

from __future__ import annotations

import json
import math

import pytest

from quant_trade.v9.mining_cashflow import (
    B4_CORRECTIONS,
    DeliveryProfile,
    HashrateOrder,
    MarketplaceFees,
    MiningCashFlowError,
    MiningLedger,
    NetworkState,
    PoolTerms,
    run_campaign,
    run_order,
)
from quant_trade.v9.mining_evidence import (
    STATUS_BLOCKED,
    STATUS_CANDIDATE,
    STATUS_COLLECTING,
    STATUS_MARKET_ONLY,
    MiningEvidenceError,
    PoolEvidence,
    PoolPayoutRecord,
    evaluate_mining_evidence,
    mining_canary_manifest,
    parse_pool_payouts,
)
from quant_trade.v9.mining_shadow import (
    CLOCK_SYSTEM,
    GAP_THRESHOLD_SECONDS,
    MIN_SHADOW_DAYS,
    MIN_SHADOW_SNAPSHOTS,
    BiddingPolicy,
    MarketSnapshot,
    ShadowCollector,
    ShadowError,
)
from quant_trade.v9.mining_units import (
    CANONICAL_SHA256_UNIT,
    SPEED_UNIT_HASHES,
    MarketSpec,
    MiningUnitError,
    convert_speed,
    estimate_delivery,
    parse_buy_info,
    unit_hashes,
)

# --- fixtures ---------------------------------------------------------------

#: A golden ``public/buy/info`` response, shaped like the documented one.
BUY_INFO_BYTES = json.dumps(
    {
        "miningAlgorithms": [
            {
                "algorithm": "SHA256",
                "speedText": "PH",
                "minimalOrderAmount": 0.001,
                "minSpeedLimit": 0.1,
                "maxSpeedLimit": 1000.0,
                "minimalPrice": 0.0001,
                "maximalPrice": 10.0,
                "downStep": -0.0001,
                "enabled": True,
            },
            {
                "algorithm": "SCRYPT",
                "speedText": "GH",
                "minimalOrderAmount": 0.005,
                "minSpeedLimit": 0.01,
                "maxSpeedLimit": 50.0,
                "minimalPrice": 0.001,
                "maximalPrice": 5.0,
                "downStep": -0.001,
                "enabled": True,
            },
        ],
        "markets": [{"market": "EU"}, {"market": "USA"}],
    },
    sort_keys=True,
).encode("utf-8")


def sha256_spec() -> MarketSpec:
    return parse_buy_info(
        BUY_INFO_BYTES,
        algorithm="SHA256",
        market="EU",
        captured_at_utc="2026-07-28T00:00:00Z",
        evidence_class="RECORDED_TEST",
        source_url="https://api2.nicehash.com/main/api/v2/public/buy/info",
    )


def network() -> NetworkState:
    # Difficulty and reward in the right order of magnitude for mainnet.
    return NetworkState(
        network="bitcoin-mainnet",
        difficulty=1.1e14,
        block_reward_btc=3.125,
        difficulty_drift_per_day=0.0,
    )


def pool(minimum_payout_btc: float = 0.0) -> PoolTerms:
    return PoolTerms(
        pool_name="test-pool",
        payout_scheme="FPPS",
        pool_fee_rate=0.02,
        minimum_payout_btc=minimum_payout_btc,
    )


def fees(**overrides: float) -> MarketplaceFees:
    base = {
        "order_creation_fee_btc": 0.00001,
        "buyer_fee_rate_on_spend": 0.03,
        "deposit_fee_btc": 0.00002,
        "withdrawal_fee_btc": 0.00003,
        "cancellation_fee_btc": 0.00001,
        "refund_rate_on_cancellation": 1.0,
    }
    base.update(overrides)
    return MarketplaceFees(**base)  # type: ignore[arg-type]


def order(**overrides: object) -> HashrateOrder:
    spec = sha256_spec()
    base: dict[str, object] = {
        "spec": spec,
        "price_btc_per_speed_unit_day": 0.001,
        "amount_btc": 0.01,
        "speed_limit": 1.0,
        "duration_hours": 24.0,
    }
    base.update(overrides)
    return HashrateOrder(**base)  # type: ignore[arg-type]


# --- units ------------------------------------------------------------------


def test_golden_buy_info_parses_every_marketplace_term() -> None:
    spec = sha256_spec()
    assert spec.speed_text == "PH"
    assert spec.min_order_amount_btc == 0.001
    assert spec.min_speed_limit == 0.1
    assert spec.max_speed_limit == 1000.0
    assert spec.min_price_btc == 0.0001
    assert spec.max_price_btc == 10.0
    assert spec.down_step == -0.0001
    assert spec.raw_sha256


@pytest.mark.parametrize(
    "field_name",
    [
        "speedText",
        "minimalOrderAmount",
        "minSpeedLimit",
        "maxSpeedLimit",
        "minimalPrice",
        "maximalPrice",
        "downStep",
    ],
)
def test_missing_market_term_is_an_error_not_a_default(field_name: str) -> None:
    payload = json.loads(BUY_INFO_BYTES.decode("utf-8"))
    del payload["miningAlgorithms"][0][field_name]
    with pytest.raises(MiningUnitError, match="cannot be defaulted"):
        parse_buy_info(
            json.dumps(payload).encode("utf-8"),
            algorithm="SHA256",
            market="EU",
            captured_at_utc="2026-07-28T00:00:00Z",
            evidence_class="RECORDED_TEST",
            source_url="https://example.invalid",
        )


def test_sha256_price_converts_by_the_venue_unit_not_by_assumption() -> None:
    """PH/s quoted, TH/s consumed: the factor is exactly 1,000."""
    spec = sha256_spec()
    per_th = spec.price_usd_per_canonical_unit_day(0.001, btc_usd=60_000.0)
    naive = 0.001 * 60_000.0
    assert math.isclose(per_th * 1000.0, naive, rel_tol=1e-12)
    assert per_th < naive


def test_unknown_speed_unit_refuses_to_guess() -> None:
    with pytest.raises(MiningUnitError, match="refusing to guess"):
        unit_hashes("ZH")


@pytest.mark.parametrize("unit", sorted(SPEED_UNIT_HASHES))
def test_speed_conversion_round_trips_for_every_known_unit(unit: str) -> None:
    amount = 3.7
    canonical = convert_speed(amount, from_unit=unit, to_unit=CANONICAL_SHA256_UNIT)
    back = convert_speed(canonical, from_unit=CANONICAL_SHA256_UNIT, to_unit=unit)
    assert math.isclose(back, amount, rel_tol=1e-9)


@pytest.mark.parametrize("exponent", range(-6, 7))
def test_conversion_is_exactly_the_ratio_of_unit_sizes(exponent: int) -> None:
    """Property check across magnitudes: no rounding shortcut sneaks in."""
    amount = 10.0**exponent
    for source, target in (("PH", "TH"), ("TH", "GH"), ("EH", "PH"), ("H", "MH")):
        expected = amount * SPEED_UNIT_HASHES[source] / SPEED_UNIT_HASHES[target]
        assert math.isclose(
            convert_speed(amount, from_unit=source, to_unit=target), expected, rel_tol=1e-12
        )


def test_speed_limit_is_a_request_not_available_supply() -> None:
    spec = sha256_spec()
    payload = spec.to_dict()
    assert "not" in payload["limit_semantics"]
    assert "available" in payload["limit_semantics"]
    # The limit says nothing about how much hashrate the market holds.
    assert "available_units" not in payload
    assert "supply" not in payload


def test_a_cheap_bid_is_not_a_fill() -> None:
    book = [0.0020, 0.0018, 0.0016, 0.0014, 0.0012]
    cheap = estimate_delivery(0.0005, book)
    rich = estimate_delivery(0.0025, book)
    assert cheap.expected_fill_ratio == 0.0
    assert rich.expected_fill_ratio == 1.0
    assert cheap.bids_above == len(book)
    assert "highest bids" in cheap.reason


def test_delivery_estimate_is_monotone_in_price() -> None:
    book = [0.0020, 0.0018, 0.0016, 0.0014, 0.0012]
    ratios = [estimate_delivery(p, book).expected_fill_ratio for p in sorted(book)]
    assert ratios == sorted(ratios)


def test_no_orderbook_means_no_delivery_estimate() -> None:
    estimate = estimate_delivery(0.001, [])
    assert estimate.expected_fill_ratio == 0.0
    assert "cannot be estimated" in estimate.reason


# --- cash flow --------------------------------------------------------------


def test_spend_is_proportional_to_accepted_hashrate() -> None:
    """Half the delivery costs half the money and mines half the coins."""
    full = run_order(
        order(),
        delivery=DeliveryProfile(fill_ratio_at_price=1.0),
        pool=pool(),
        network=network(),
        fees=fees(),
    )
    half = run_order(
        order(),
        delivery=DeliveryProfile(fill_ratio_at_price=0.5),
        pool=pool(),
        network=network(),
        fees=fees(),
    )
    assert math.isclose(half.spent_btc, full.spent_btc / 2.0, rel_tol=1e-9)
    assert math.isclose(half.gross_mined_btc, full.gross_mined_btc / 2.0, rel_tol=1e-9)
    assert half.refunded_btc > full.refunded_btc


def test_lower_delivery_reduces_income_and_spend_together() -> None:
    ratios = [1.0, 0.75, 0.5, 0.25]
    outcomes = [
        run_order(
            order(),
            delivery=DeliveryProfile(fill_ratio_at_price=r),
            pool=pool(),
            network=network(),
            fees=fees(),
        )
        for r in ratios
    ]
    spends = [o.spent_btc for o in outcomes]
    mined = [o.gross_mined_btc for o in outcomes]
    assert spends == sorted(spends, reverse=True)
    assert mined == sorted(mined, reverse=True)


def test_buyer_fee_rides_on_spend_not_on_deposit() -> None:
    """Doubling the escrowed budget without spending it changes no fee."""
    small = run_order(
        order(amount_btc=0.01),
        delivery=DeliveryProfile(fill_ratio_at_price=1.0),
        pool=pool(),
        network=network(),
        fees=fees(),
    )
    large = run_order(
        order(amount_btc=0.05),
        delivery=DeliveryProfile(fill_ratio_at_price=1.0),
        pool=pool(),
        network=network(),
        fees=fees(),
    )
    assert math.isclose(small.buyer_fee_btc, large.buyer_fee_btc, rel_tol=1e-12)
    assert math.isclose(
        small.buyer_fee_btc, small.spent_btc * fees().buyer_fee_rate_on_spend, rel_tol=1e-12
    )
    assert large.refunded_btc > small.refunded_btc


def test_order_creation_fee_is_fixed_per_order() -> None:
    big = run_order(
        order(amount_btc=0.05),
        delivery=DeliveryProfile(),
        pool=pool(),
        network=network(),
        fees=fees(order_creation_fee_btc=0.0005),
    )
    small = run_order(
        order(amount_btc=0.01),
        delivery=DeliveryProfile(),
        pool=pool(),
        network=network(),
        fees=fees(order_creation_fee_btc=0.0005),
    )
    assert big.creation_fee_btc == small.creation_fee_btc == 0.0005


def test_a_fixed_fee_can_swallow_a_small_order_entirely() -> None:
    outcome = run_order(
        order(amount_btc=0.001),
        delivery=DeliveryProfile(),
        pool=pool(),
        network=network(),
        fees=fees(order_creation_fee_btc=0.001),
    )
    assert outcome.ended_because == "amount_below_creation_fee"
    assert outcome.spent_btc == 0.0
    assert outcome.gross_mined_btc == 0.0


def test_unspent_budget_is_refunded() -> None:
    outcome = run_order(
        order(amount_btc=0.05),
        delivery=DeliveryProfile(fill_ratio_at_price=1.0),
        pool=pool(),
        network=network(),
        fees=fees(),
    )
    expected = 0.05 - outcome.creation_fee_btc - outcome.spent_btc - outcome.buyer_fee_btc
    assert math.isclose(outcome.refunded_btc, expected, rel_tol=1e-12)


def test_cancellation_refunds_the_unspent_balance_minus_the_fee() -> None:
    outcome = run_order(
        order(amount_btc=0.05, duration_hours=48.0),
        delivery=DeliveryProfile(fill_ratio_at_price=1.0),
        pool=pool(),
        network=network(),
        fees=fees(cancellation_fee_btc=0.0002),
        cancel_after_hours=12.0,
    )
    assert outcome.ended_because == "cancelled"
    assert outcome.cancellation_fee_btc == 0.0002
    assert outcome.hours_run == 12.0
    unspent = 0.05 - outcome.creation_fee_btc - outcome.spent_btc - outcome.buyer_fee_btc - 0.0002
    assert math.isclose(outcome.refunded_btc, unspent, rel_tol=1e-12)


def test_a_partial_refund_rate_forfeits_the_difference() -> None:
    outcome = run_order(
        order(amount_btc=0.05, duration_hours=48.0),
        delivery=DeliveryProfile(fill_ratio_at_price=1.0),
        pool=pool(),
        network=network(),
        fees=fees(refund_rate_on_cancellation=0.5),
        cancel_after_hours=12.0,
    )
    assert any("not refunded" in note for note in outcome.notes)


def test_budget_exhaustion_ends_the_order_early() -> None:
    outcome = run_order(
        order(amount_btc=0.0015, duration_hours=48.0),
        delivery=DeliveryProfile(fill_ratio_at_price=1.0),
        pool=pool(),
        network=network(),
        fees=fees(order_creation_fee_btc=0.0),
    )
    assert outcome.ended_because == "budget_exhausted"
    assert outcome.hours_run < 48.0
    assert outcome.refunded_btc == pytest.approx(0.0, abs=1e-12)


def test_being_outbid_stops_delivery_until_repriced() -> None:
    """The repricing risk: a bid below the market mines nothing."""
    market_rose = tuple([0.0005] * 6 + [0.0050] * 18)
    stuck = run_order(
        order(price_btc_per_speed_unit_day=0.001, duration_hours=24.0),
        delivery=DeliveryProfile(market_price_path=market_rose),
        pool=pool(),
        network=network(),
        fees=fees(),
    )
    assert stuck.hours_outbid == 18.0
    assert stuck.hours_delivering == 6.0
    assert any("outbid" in note for note in stuck.notes)

    repriced = run_order(
        order(price_btc_per_speed_unit_day=0.001, duration_hours=24.0),
        delivery=DeliveryProfile(market_price_path=market_rose, reprice_up_to_btc=0.006),
        pool=pool(),
        network=network(),
        fees=fees(),
    )
    assert repriced.hours_outbid == 0.0
    assert repriced.repriced_to_btc == 0.0050
    # Staying in the book costs more per delivered hour than the original bid.
    assert repriced.spent_btc > stuck.spent_btc
    assert repriced.gross_mined_btc > stuck.gross_mined_btc


def test_pool_fee_is_taken_from_mined_coins_once() -> None:
    outcome = run_order(
        order(),
        delivery=DeliveryProfile(),
        pool=pool(),
        network=network(),
        fees=fees(),
    )
    assert math.isclose(outcome.pool_fee_btc, outcome.gross_mined_btc * 0.02, rel_tol=1e-12)
    assert math.isclose(
        outcome.net_mined_btc, outcome.gross_mined_btc - outcome.pool_fee_btc, rel_tol=1e-12
    )


def test_order_below_the_btc_minimum_is_rejected() -> None:
    with pytest.raises(MiningCashFlowError, match="below the marketplace minimum"):
        order(amount_btc=0.0001)


def test_order_beyond_the_maximum_duration_is_rejected() -> None:
    with pytest.raises(MiningCashFlowError, match="exceeds the venue maximum"):
        order(duration_hours=1_000.0, max_duration_hours=720.0)


def test_speed_limit_outside_the_venue_range_is_rejected() -> None:
    with pytest.raises(MiningCashFlowError, match="exceeds the maximum"):
        order(speed_limit=5_000.0)
    with pytest.raises(MiningCashFlowError, match="below the"):
        order(speed_limit=0.01)


def test_price_amount_and_limit_move_independently() -> None:
    base = run_order(
        order(), delivery=DeliveryProfile(), pool=pool(), network=network(), fees=fees()
    )
    pricier = run_order(
        order(price_btc_per_speed_unit_day=0.002),
        delivery=DeliveryProfile(),
        pool=pool(),
        network=network(),
        fees=fees(),
    )
    faster = run_order(
        order(speed_limit=2.0, amount_btc=0.05),
        delivery=DeliveryProfile(),
        pool=pool(),
        network=network(),
        fees=fees(),
    )
    # Price doubles the spend and leaves the hashrate alone.
    assert math.isclose(pricier.spent_btc, base.spent_btc * 2.0, rel_tol=1e-9)
    assert math.isclose(pricier.gross_mined_btc, base.gross_mined_btc, rel_tol=1e-9)
    # Speed doubles both.
    assert math.isclose(faster.spent_btc, base.spent_btc * 2.0, rel_tol=1e-9)
    assert math.isclose(faster.gross_mined_btc, base.gross_mined_btc * 2.0, rel_tol=1e-9)


# --- ledger -----------------------------------------------------------------


def test_withdrawal_fee_is_charged_once_across_many_orders() -> None:
    orders = [(order(), DeliveryProfile()) for _ in range(3)]
    ledger, outcomes = run_campaign(
        orders,
        deposit_btc=0.2,
        fees=fees(),
        pool=pool(),
        network=network(),
        btc_usd=60_000.0,
    )
    assert len(outcomes) == 3
    assert ledger.withdrawals == 1
    withdrawal_rows = [r for r in ledger.rows if r.event == "withdrawal_fee"]
    assert len(withdrawal_rows) == 1
    assert withdrawal_rows[0].btc == -fees().withdrawal_fee_btc


def test_deposit_fee_is_charged_on_the_way_in() -> None:
    ledger = MiningLedger(btc_usd=60_000.0, fees=fees(deposit_fee_btc=0.0005), pool=pool())
    ledger.deposit(0.1)
    assert math.isclose(ledger.wallet_btc, 0.0995, rel_tol=1e-12)
    assert any(r.event == "deposit_fee" and r.btc == -0.0005 for r in ledger.rows)


def test_a_deposit_fee_larger_than_the_deposit_is_refused() -> None:
    ledger = MiningLedger(btc_usd=60_000.0, fees=fees(deposit_fee_btc=0.5), pool=pool())
    with pytest.raises(MiningCashFlowError, match="consumes the whole"):
        ledger.deposit(0.1)


def test_balances_accumulate_across_orders_toward_the_payout_minimum() -> None:
    """Two orders that each mine half the minimum reach it together."""
    single_ledger, single_outcomes = run_campaign(
        [(order(), DeliveryProfile())],
        deposit_btc=0.2,
        fees=fees(),
        pool=pool(minimum_payout_btc=0.0),
        network=network(),
        btc_usd=60_000.0,
    )
    per_order = single_outcomes[0].net_mined_btc
    minimum = per_order * 1.5

    stranded, _ = run_campaign(
        [(order(), DeliveryProfile())],
        deposit_btc=0.2,
        fees=fees(),
        pool=pool(minimum_payout_btc=minimum),
        network=network(),
        btc_usd=60_000.0,
    )
    assert stranded.withdrawals == 0
    assert stranded.stranded_btc > 0
    assert any("not spendable" in p for p in stranded.problems)

    together, _ = run_campaign(
        [(order(), DeliveryProfile()), (order(), DeliveryProfile())],
        deposit_btc=0.2,
        fees=fees(),
        pool=pool(minimum_payout_btc=minimum),
        network=network(),
        btc_usd=60_000.0,
    )
    assert together.withdrawals == 1
    assert together.stranded_btc == 0.0
    assert single_ledger.withdrawals == 1


def test_stranded_coins_are_not_counted_as_income() -> None:
    ledger, outcomes = run_campaign(
        [(order(), DeliveryProfile())],
        deposit_btc=0.2,
        fees=fees(),
        pool=pool(minimum_payout_btc=10.0),
        network=network(),
        btc_usd=60_000.0,
    )
    assert ledger.pool_balance_btc > 0
    # Wallet holds only the refund; nothing mined made it out of the pool.
    assert ledger.net_btc < 0
    assert ledger.net_btc == pytest.approx(ledger.wallet_btc - ledger.deposited_btc, abs=1e-15)


def test_the_ledger_is_btc_with_usd_as_a_parallel_view() -> None:
    ledger, _ = run_campaign(
        [(order(), DeliveryProfile())],
        deposit_btc=0.2,
        fees=fees(),
        pool=pool(),
        network=network(),
        btc_usd=60_000.0,
    )
    for row in ledger.rows:
        assert math.isclose(row.usd, row.btc * 60_000.0, rel_tol=1e-12)
    summary = ledger.summary(horizon_days=1.0)
    assert math.isclose(
        summary["net_usd_at_start_rate"], summary["net_btc"] * 60_000.0, rel_tol=1e-12
    )


def test_benchmarks_are_holding_btc_and_holding_cash() -> None:
    ledger, _ = run_campaign(
        [(order(), DeliveryProfile())],
        deposit_btc=0.2,
        fees=fees(),
        pool=pool(),
        network=network(),
        btc_usd=60_000.0,
    )
    summary = ledger.summary(horizon_days=1.0, btc_usd_end=66_000.0)
    # Against BTC, a rental wins only by producing more coins.
    assert math.isclose(
        summary["versus_holding_btc_usd"], summary["net_btc"] * 66_000.0, rel_tol=1e-9
    )
    # Against cash, the BTC price move counts because the alternative was USD.
    assert summary["versus_holding_cash_usd"] > summary["versus_holding_btc_usd"]
    assert summary["annualization_note"].startswith("Deliberately not annualized")


def test_every_b4_correction_is_documented() -> None:
    assert len(B4_CORRECTIONS) == 16
    assert len(set(B4_CORRECTIONS)) == 16


# --- evidence ceiling -------------------------------------------------------


PAYOUT_BYTES = json.dumps(
    {
        "payouts": [
            {
                "worker": "w1",
                "periodStartMs": 1_750_000_000_000,
                "periodEndMs": 1_750_086_400_000,
                "acceptedHashesPerSecond": 1.0e15,
                "payoutBtc": 0.004,
            },
            {
                "worker": "w1",
                "periodStartMs": 1_750_086_400_000,
                "periodEndMs": 1_750_172_800_000,
                "acceptedHashesPerSecond": 1.0e15,
                "payoutBtc": 0.0039,
            },
        ]
    },
    sort_keys=True,
).encode("utf-8")


def real_pool_evidence() -> PoolEvidence:
    records = parse_pool_payouts(
        PAYOUT_BYTES,
        pool_name="test-pool",
        evidence_class="REAL_PUBLIC_RETAIL",
        source_url="https://pool.example/api/payouts",
        captured_at_ms=1_750_172_800_000,
    )
    return PoolEvidence(records=records)


def test_blocked_marketplace_is_blocked_evidence() -> None:
    gate = evaluate_mining_evidence(market_quotes=0, market_blocked=True, pool=None)
    assert gate.status == STATUS_BLOCKED


def test_without_pool_evidence_the_ceiling_is_market_only() -> None:
    gate = evaluate_mining_evidence(
        market_quotes=25,
        market_blocked=False,
        pool=None,
        shadow_days=365.0,
        shadow_snapshots=1_000_000,
    )
    assert gate.status == STATUS_MARKET_ONLY
    assert any("no parsed pool payout record" in r for r in gate.reasons)


def test_a_declared_delivery_boolean_cannot_stand_in_for_a_payout() -> None:
    gate = evaluate_mining_evidence(
        market_quotes=25,
        market_blocked=False,
        pool=PoolEvidence(records=[], declared_delivery_ok=True),
        shadow_days=365.0,
        shadow_snapshots=1_000_000,
    )
    assert gate.status == STATUS_MARKET_ONLY


def test_pool_records_with_no_payout_do_not_promote() -> None:
    payload = json.loads(PAYOUT_BYTES.decode("utf-8"))
    for row in payload["payouts"]:
        row["payoutBtc"] = 0.0
    records = parse_pool_payouts(
        json.dumps(payload).encode("utf-8"),
        pool_name="test-pool",
        evidence_class="REAL_PUBLIC_RETAIL",
        source_url="https://pool.example/api/payouts",
        captured_at_ms=1_750_172_800_000,
    )
    gate = evaluate_mining_evidence(
        market_quotes=25,
        market_blocked=False,
        pool=PoolEvidence(records=records),
        shadow_days=30.0,
        shadow_snapshots=10_000,
    )
    assert gate.status == STATUS_MARKET_ONLY
    assert any("nothing was received" in r for r in gate.reasons)


def test_synthetic_pool_records_never_count_as_real() -> None:
    records = parse_pool_payouts(
        PAYOUT_BYTES,
        pool_name="test-pool",
        evidence_class="SYNTHETIC",
        source_url="fixture",
        captured_at_ms=1_750_172_800_000,
    )
    evidence = PoolEvidence(records=records)
    assert evidence.real_records == []
    assert evidence.realized_btc_per_hash_second_day() is None
    gate = evaluate_mining_evidence(
        market_quotes=25,
        market_blocked=False,
        pool=evidence,
        shadow_days=30.0,
        shadow_snapshots=10_000,
    )
    assert gate.status == STATUS_MARKET_ONLY


def test_a_real_class_record_must_carry_its_source_bytes() -> None:
    with pytest.raises(MiningEvidenceError, match="a real class without bytes is a claim"):
        PoolPayoutRecord(
            pool_name="p",
            worker="w",
            period_start_ms=0,
            period_end_ms=86_400_000,
            hashrate_accepted_hashes_per_second=1e15,
            payout_btc=0.004,
            raw_sha256="",
            captured_at_ms=86_400_000,
            evidence_class="REAL_ACCOUNT_SPECIFIC",
            source_url="https://pool.example",
        )


def test_stale_evidence_blocks_promotion() -> None:
    gate = evaluate_mining_evidence(
        market_quotes=25,
        market_blocked=False,
        pool=real_pool_evidence(),
        shadow_days=30.0,
        shadow_snapshots=10_000,
        evidence_ages_seconds={"buy_info": 48 * 3600.0},
    )
    assert gate.status == STATUS_COLLECTING
    assert any("freshness window" in r for r in gate.reasons)


def test_quote_and_economics_must_agree() -> None:
    gate = evaluate_mining_evidence(
        market_quotes=25,
        market_blocked=False,
        pool=real_pool_evidence(),
        shadow_days=30.0,
        shadow_snapshots=10_000,
        quote_price_btc=0.001,
        economics_price_btc=0.002,
    )
    assert gate.status == STATUS_MARKET_ONLY
    assert gate.quote_economics_agree is False
    assert any("disagree" in r for r in gate.reasons)


def test_a_short_window_is_collecting_not_a_candidate() -> None:
    gate = evaluate_mining_evidence(
        market_quotes=25,
        market_blocked=False,
        pool=real_pool_evidence(),
        shadow_days=3.0,
        shadow_snapshots=10_000,
    )
    assert gate.status == STATUS_COLLECTING
    assert any("real days observed" in r for r in gate.reasons)


def test_a_sparse_window_is_collecting_not_a_candidate() -> None:
    gate = evaluate_mining_evidence(
        market_quotes=25,
        market_blocked=False,
        pool=real_pool_evidence(),
        shadow_days=30.0,
        shadow_snapshots=10,
    )
    assert gate.status == STATUS_COLLECTING
    assert any("snapshots of the" in r for r in gate.reasons)


def test_a_complete_window_reaches_shadow_candidate() -> None:
    gate = evaluate_mining_evidence(
        market_quotes=25,
        market_blocked=False,
        pool=real_pool_evidence(),
        shadow_days=21.0,
        shadow_snapshots=5_000,
        quote_price_btc=0.001,
        economics_price_btc=0.001,
    )
    assert gate.status == STATUS_CANDIDATE
    assert gate.to_dict()["purchase_authorized"] is False


def test_realized_payout_rate_comes_only_from_records() -> None:
    evidence = real_pool_evidence()
    rate = evidence.realized_btc_per_hash_second_day()
    assert rate is not None
    weight = sum(
        r.hashrate_accepted_hashes_per_second * r.duration_days for r in evidence.real_records
    )
    assert math.isclose(rate, evidence.total_payout_btc / weight, rel_tol=1e-12)


def test_canary_manifest_authorises_nothing() -> None:
    gate = evaluate_mining_evidence(
        market_quotes=25,
        market_blocked=False,
        pool=real_pool_evidence(),
        shadow_days=21.0,
        shadow_snapshots=5_000,
    )
    manifest = mining_canary_manifest(gate)
    assert manifest["purchase_authorized"] is False
    assert manifest["deposit_authorized"] is False
    assert manifest["withdrawal_authorized"] is False
    assert manifest["wallet_signing_authorized"] is False
    assert manifest["aws_alibaba_hashing"] == "PROHIBITED"
    assert manifest["orders_placed"] == 0
    assert manifest["btc_moved"] == 0.0
    assert manifest["requires_human_authorisation"] is True


# --- shadow collector -------------------------------------------------------


def snapshot(captured_at_ms: int, price: float = 0.001) -> MarketSnapshot:
    return MarketSnapshot(
        captured_at_ms=captured_at_ms,
        algorithm="SHA256",
        market="EU",
        best_price_btc=price,
        orderbook_depth=5,
        raw_sha256="0" * 64,
        evidence_class="RECORDED_TEST",
        source_url="https://api2.nicehash.com/main/api/v2/hashpower/orderBook",
    )


def policy() -> BiddingPolicy:
    return BiddingPolicy(
        name="p50-frozen",
        bid_percentile=0.5,
        max_price_btc=0.005,
        speed_limit=1.0,
        amount_btc=0.01,
        duration_hours=24.0,
    )


class FakeClock:
    def __init__(self, start: float = 1_750_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_replaying_snapshots_advances_the_count_but_not_the_window(tmp_path) -> None:
    """The forgery this design exists to stop."""
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    for i in range(500):
        collector.capture(snapshot(1_750_000_000_000 + i * 1000))
    assert collector.stats.snapshots == 500
    assert collector.stats.observed_days == 0.0
    report = collector.report(pool_evidence_present=True)
    assert report["status"] == STATUS_COLLECTING
    assert any("real days observed" in r for r in report["blocking_reasons"])


def test_real_elapsed_time_accumulates_across_captures(tmp_path) -> None:
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    collector.capture(snapshot(1_750_000_000_000))
    for i in range(1, 25):
        clock.advance(600.0)
        collector.capture(snapshot(1_750_000_000_000 + i * 600_000))
    assert math.isclose(collector.stats.observed_seconds, 24 * 600.0, rel_tol=1e-9)


def test_an_injected_clock_can_never_support_promotion(tmp_path) -> None:
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    collector.capture(snapshot(1_750_000_000_000))
    for i in range(1, MIN_SHADOW_SNAPSHOTS + 1):
        clock.advance(900.0)
        collector.capture(snapshot(1_750_000_000_000 + i * 900_000))
    assert collector.stats.observed_days > MIN_SHADOW_DAYS
    assert collector.stats.snapshots > MIN_SHADOW_SNAPSHOTS
    report = collector.report(pool_evidence_present=True)
    assert report["status"] == STATUS_COLLECTING
    assert any("injected for testing" in r for r in report["blocking_reasons"])
    assert report["clock_source"] != CLOCK_SYSTEM


def test_a_downtime_gap_is_recorded_and_excluded(tmp_path) -> None:
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    collector.capture(snapshot(1_750_000_000_000))
    clock.advance(600.0)
    collector.capture(snapshot(1_750_000_600_000))
    clock.advance(GAP_THRESHOLD_SECONDS * 4)
    collector.capture(snapshot(1_750_010_000_000))
    assert collector.stats.gaps == 1
    assert collector.stats.gap_seconds == GAP_THRESHOLD_SECONDS * 4
    # Only the 600s of genuine observation counted.
    assert math.isclose(collector.stats.observed_seconds, 600.0, rel_tol=1e-9)


def test_the_journal_chain_detects_an_edited_record(tmp_path) -> None:
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    for i in range(5):
        clock.advance(600.0)
        collector.capture(snapshot(1_750_000_000_000 + i * 600_000))
    ok, problems = collector.verify_chain()
    assert ok and not problems

    lines = collector.journal_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[2])
    record["payload"]["best_price_btc"] = 0.9
    lines[2] = json.dumps(record, sort_keys=True)
    collector.journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    ok, problems = collector.verify_chain()
    assert not ok
    assert any("edited after it was written" in p for p in problems)


def test_the_journal_chain_detects_a_removed_record(tmp_path) -> None:
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    for i in range(5):
        clock.advance(600.0)
        collector.capture(snapshot(1_750_000_000_000 + i * 600_000))
    lines = collector.journal_path.read_text(encoding="utf-8").splitlines()
    del lines[2]
    collector.journal_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ok, problems = collector.verify_chain()
    assert not ok
    assert any("removed or reordered" in p for p in problems)


def test_a_torn_final_line_is_survivable(tmp_path) -> None:
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    for i in range(5):
        clock.advance(600.0)
        collector.capture(snapshot(1_750_000_000_000 + i * 600_000))
    with collector.journal_path.open("a", encoding="utf-8") as handle:
        handle.write('{"sequence": 99, "kind": "snap')

    revived = ShadowCollector(tmp_path, clock=clock)
    revived.resume()
    assert revived.stats.snapshots == 5
    assert any("torn journal line" in p for p in revived.problems)


def test_resume_rebuilds_the_window_from_the_journal(tmp_path) -> None:
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    for i in range(10):
        clock.advance(600.0)
        collector.capture(snapshot(1_750_000_000_000 + i * 600_000))
    observed = collector.stats.observed_seconds
    collector.release()

    revived = ShadowCollector(tmp_path, clock=clock)
    revived.resume()
    assert revived.stats.snapshots == 10
    assert math.isclose(revived.stats.observed_seconds, observed, rel_tol=1e-9)
    assert revived.sequence == collector.sequence


def test_a_second_collector_cannot_hold_the_lease(tmp_path) -> None:
    clock = FakeClock()
    first = ShadowCollector(tmp_path, clock=clock)
    first.start(policy())
    second = ShadowCollector(tmp_path, clock=clock)
    with pytest.raises(ShadowError, match="another collector holds the shadow lease"):
        second.start(policy())


def test_changing_the_policy_mid_window_is_refused(tmp_path) -> None:
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    clock.advance(600.0)
    collector.capture(snapshot(1_750_000_600_000))
    collector.release()

    other = BiddingPolicy(
        name="p90-frozen",
        bid_percentile=0.9,
        max_price_btc=0.005,
        speed_limit=1.0,
        amount_btc=0.01,
        duration_hours=24.0,
    )
    revived = ShadowCollector(tmp_path, clock=clock)
    with pytest.raises(ShadowError, match="policy changed mid-window"):
        revived.start(other)


def test_the_shadow_records_a_bid_it_would_not_have_placed(tmp_path) -> None:
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    record = collector.capture(
        snapshot(1_750_000_000_000, price=0.05),
        orderbook_prices_btc=[0.06, 0.055, 0.05, 0.045, 0.04],
    )
    assert record["payload"]["would_have_bid"] is False
    assert record["payload"]["purchased"] is False
    assert collector.stats.would_have_bid == 0


def test_capture_before_freezing_a_policy_is_refused(tmp_path) -> None:
    collector = ShadowCollector(tmp_path, clock=FakeClock())
    with pytest.raises(ShadowError, match="must be frozen first"):
        collector.capture(snapshot(1_750_000_000_000))


def test_the_shadow_report_never_claims_a_purchase(tmp_path) -> None:
    clock = FakeClock()
    collector = ShadowCollector(tmp_path, clock=clock)
    collector.start(policy())
    clock.advance(600.0)
    collector.capture(snapshot(1_750_000_600_000))
    report = collector.report(pool_evidence_present=False)
    assert report["status"] == STATUS_MARKET_ONLY
    assert report["orders_placed"] == 0
    assert report["btc_spent"] == 0.0
    assert report["purchase_authorized"] is False


# --- safety boundary --------------------------------------------------------


@pytest.mark.parametrize(
    "module_name",
    [
        "quant_trade.v9.mining_units",
        "quant_trade.v9.mining_cashflow",
        "quant_trade.v9.mining_evidence",
        "quant_trade.v9.mining_shadow",
    ],
)
def test_no_mining_module_exposes_a_transacting_verb(module_name: str) -> None:
    import importlib

    module = importlib.import_module(module_name)
    forbidden = (
        "buy",
        "buy_hashrate",
        "place_order",
        "submit_order",
        "create_order",
        "deposit_funds",
        "withdraw_funds",
        "sign",
        "sign_transaction",
        "transfer",
    )
    for name in forbidden:
        assert not hasattr(module, name), f"{module_name} exposes {name}"


@pytest.mark.parametrize(
    "module_name",
    [
        "quant_trade.v9.mining_units",
        "quant_trade.v9.mining_cashflow",
        "quant_trade.v9.mining_evidence",
        "quant_trade.v9.mining_shadow",
    ],
)
def test_no_mining_module_reads_credentials_or_signs(module_name: str) -> None:
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module_name)).lower()
    for pattern in (
        "import hmac",
        "hmac.new",
        "os.environ",
        "getenv",
        "x-api-key",
        "authorization",
        "private_key",
    ):
        assert pattern not in source, f"{module_name} contains {pattern!r}"


def test_no_mining_module_reaches_a_cloud_hashing_provider() -> None:
    """No endpoint, SDK or instance API for a provider that could be made to hash."""
    import inspect
    import re

    from quant_trade.v9 import mining_cashflow, mining_evidence, mining_shadow, mining_units

    reaches_provider = re.compile(
        r"amazonaws\.com|aliyuncs\.com|\bboto3\b|\bec2\b|run_instances|create_instance",
        re.IGNORECASE,
    )
    for module in (mining_units, mining_cashflow, mining_evidence, mining_shadow):
        source = inspect.getsource(module)
        assert not reaches_provider.search(source), f"{module.__name__} reaches a cloud provider"


def test_no_mining_module_opens_a_network_connection() -> None:
    """Snapshots are supplied by the caller; these modules parse, they do not fetch."""
    import inspect
    import re

    from quant_trade.v9 import mining_cashflow, mining_evidence, mining_shadow, mining_units

    networking = re.compile(
        r"\bimport requests\b|\bimport httpx\b|\bimport urllib\b|http\.client|"
        r"urlopen|socket\.socket|\.post\(|\.put\(|\.delete\(",
        re.IGNORECASE,
    )
    for module in (mining_units, mining_cashflow, mining_evidence, mining_shadow):
        source = inspect.getsource(module)
        assert not networking.search(source), f"{module.__name__} opens a connection"
