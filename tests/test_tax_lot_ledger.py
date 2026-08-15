from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from decimal import Decimal

import pytest

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.ops.tax_lot_ledger import (
    AfterTaxTcaRequest,
    MarkEvidence,
    TaxLotFill,
    TaxLotLedgerConfig,
    TaxScenario,
    evaluate_after_tax_tca,
)

VALUATION_AT = "2026-01-04T00:00:00Z"


def _fill(
    fill_id: str,
    side: str,
    quantity: object,
    price: object,
    when: str,
    **overrides: object,
) -> TaxLotFill:
    values: dict[str, object] = {
        "fill_id": fill_id,
        "instrument_id": "CMC:1",
        "executed_at_utc": when,
        "side": side,
        "quantity": quantity,
        "unit_price_quote": price,
        "quote_currency": "USDT",
        "mxn_per_quote": Decimal("20"),
        "quote_fx_source": "operator-supplied event-time USDT/MXN observation",
        "fee_amount": Decimal("0"),
        "fee_currency": "USDT",
        "reference_price_quote": price,
        "reference_at_utc": when,
        "reference_source": "operator-supplied pre-fill decision-price observation",
    }
    values.update(overrides)
    return TaxLotFill(**values)  # type: ignore[arg-type]


def _mark(**overrides: object) -> MarkEvidence:
    values: dict[str, object] = {
        "instrument_id": "CMC:1",
        "as_of_utc": VALUATION_AT,
        "unit_price_quote": Decimal("14"),
        "quote_currency": "USDT",
        "mxn_per_quote": Decimal("20"),
        "quote_fx_source": "operator-supplied mark-time USDT/MXN observation",
    }
    values.update(overrides)
    return MarkEvidence(**values)  # type: ignore[arg-type]


def _scenario(**overrides: object) -> TaxScenario:
    values: dict[str, object] = {
        "label": "operator 30 percent sensitivity only",
        "tax_rate_fraction": Decimal("0.30"),
        "taxable_base_mode": "POSITIVE_NET_REALIZED_PNL_MXN",
        "declared_by_user": True,
        "assumption_source": "operator input; not legal or tax advice",
    }
    values.update(overrides)
    return TaxScenario(**values)  # type: ignore[arg-type]


def _fifo_request(*, scenario: TaxScenario | None = None) -> AfterTaxTcaRequest:
    return AfterTaxTcaRequest(
        initial_capital_mxn=Decimal("4000"),
        config=TaxLotLedgerConfig(lot_method="FIFO"),
        fills=(
            _fill(
                "buy-1",
                "BUY",
                10,
                10,
                "2026-01-01T00:00:00Z",
                fee_amount=1,
                reference_price_quote=Decimal("9.5"),
            ),
            _fill(
                "buy-2",
                "BUY",
                5,
                12,
                "2026-01-02T00:00:00Z",
                mxn_per_quote=21,
                fee_amount=Decimal("0.5"),
                reference_price_quote=Decimal("11.5"),
            ),
            _fill(
                "sell-1",
                "SELL",
                12,
                15,
                "2026-01-03T00:00:00Z",
                fee_amount=Decimal("1.8"),
                reference_price_quote=Decimal("15.5"),
            ),
        ),
        marks=(_mark(),),
        valuation_as_of_utc=VALUATION_AT,
        tax_scenario=scenario,
    )


def test_fifo_partial_sell_fx_fees_marks_and_tca_are_exact_mxn() -> None:
    result = evaluate_after_tax_tca(_fifo_request(scenario=_scenario()))

    assert result.status == "COMPLETE"
    assert result.gross_buy_notional_mxn == Decimal("3260")
    assert result.gross_sell_notional_mxn == Decimal("3600")
    assert result.total_fees_mxn == Decimal("66.5")
    assert result.signed_implementation_shortfall_mxn == Decimal("272.5")
    assert result.adverse_slippage_mxn == Decimal("272.5")
    assert result.transaction_cost_mxn == Decimal("339.0")
    assert result.realized_gross_pnl_mxn == Decimal("1096")
    assert result.realized_pre_tax_pnl_mxn == Decimal("1035.8")
    assert len(result.realizations) == 2
    assert result.realizations[0].source_buy_fill_id == "buy-1"
    assert result.realizations[0].quantity == Decimal("10")
    assert result.realizations[0].realized_pre_tax_pnl_mxn == Decimal("950")
    assert result.realizations[1].source_buy_fill_id == "buy-2"
    assert result.realizations[1].quantity == Decimal("2")
    assert result.realizations[1].realized_pre_tax_pnl_mxn == Decimal("85.8")
    assert len(result.open_lots) == 1
    assert result.open_lots[0].quantity_remaining == Decimal("3")
    assert result.open_lots[0].cost_basis_remaining_mxn == Decimal("762.3")
    assert result.mark_value_mxn == Decimal("840")
    assert result.unrealized_pre_tax_pnl_mxn == Decimal("77.7")
    assert result.equity_pnl_pre_tax_mxn == Decimal("1113.5")
    assert result.scenario_taxable_base_mxn == Decimal("1035.8")
    assert result.scenario_tax_mxn == Decimal("310.740")
    assert result.realized_after_tax_scenario_pnl_mxn == Decimal("725.060")
    assert result.equity_pnl_after_realized_tax_scenario_mxn == Decimal("802.760")
    assert result.return_on_initial_capital_pre_tax == Decimal("0.278375")
    assert result.return_on_initial_capital_after_realized_tax_scenario == Decimal("0.200690")
    assert result.minimum_funding_required_mxn == Decimal("3290.5")
    assert result.capital_shortfall_mxn == 0
    assert result.is_verified()

    payload = result.to_dict()
    assert payload["real_money_authorized"] is False
    assert payload["external_action_authorized"] is False
    assert payload["profit_claim_authorized"] is False
    assert payload["legal_or_tax_advice"] is False


def test_tax_outputs_do_not_exist_without_explicit_user_scenario() -> None:
    result = evaluate_after_tax_tca(_fifo_request())

    assert result.realized_pre_tax_pnl_mxn == Decimal("1035.8")
    assert result.scenario_taxable_base_mxn is None
    assert result.scenario_tax_mxn is None
    assert result.realized_after_tax_scenario_pnl_mxn is None
    assert result.equity_pnl_after_realized_tax_scenario_mxn is None
    assert result.return_on_initial_capital_after_realized_tax_scenario is None


def test_negative_realized_result_has_zero_tax_only_under_declared_mode() -> None:
    request = AfterTaxTcaRequest(
        initial_capital_mxn=1000,
        config=TaxLotLedgerConfig(),
        fills=(
            _fill("buy", "BUY", 1, 10, "2026-01-01T00:00:00Z"),
            _fill("sell", "SELL", 1, 5, "2026-01-02T00:00:00Z"),
        ),
        marks=(),
        valuation_as_of_utc=VALUATION_AT,
        tax_scenario=_scenario(),
    )

    result = evaluate_after_tax_tca(request)

    assert result.realized_pre_tax_pnl_mxn == Decimal("-100")
    assert result.scenario_taxable_base_mxn == 0
    assert result.scenario_tax_mxn == 0
    assert result.realized_after_tax_scenario_pnl_mxn == Decimal("-100")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
@pytest.mark.parametrize(
    "field",
    ["quantity", "unit_price_quote", "mxn_per_quote", "fee_amount", "fee_mxn_per_unit"],
)
def test_non_finite_or_boolean_fill_money_is_rejected(field: str, value: object) -> None:
    overrides: dict[str, object] = {field: value}
    quantity = overrides.pop("quantity", 1)
    if field == "fee_mxn_per_unit":
        overrides["fee_fx_source"] = "operator supplied"
    with pytest.raises(ValueError, match="finite|bool"):
        _fill("bad", "BUY", quantity, 10, "2026-01-01T00:00:00Z", **overrides)


@pytest.mark.parametrize("field", ["unit_price_quote", "mxn_per_quote"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), True])
def test_non_finite_or_boolean_mark_money_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="finite|bool"):
        _mark(**{field: value})


def test_currency_and_fee_fx_contradictions_fail_closed() -> None:
    with pytest.raises(ValueError, match="mxn_per_quote=1"):
        _fill(
            "mxn",
            "BUY",
            1,
            10,
            "2026-01-01T00:00:00Z",
            quote_currency="MXN",
            mxn_per_quote=20,
        )
    with pytest.raises(ValueError, match="fee FX"):
        _fill(
            "bnb-fee",
            "BUY",
            1,
            10,
            "2026-01-01T00:00:00Z",
            fee_amount=Decimal("0.01"),
            fee_currency="BNB",
        )
    with pytest.raises(ValueError, match="fee_fx_source"):
        _fill(
            "bnb-fee",
            "BUY",
            1,
            10,
            "2026-01-01T00:00:00Z",
            fee_amount=Decimal("0.01"),
            fee_currency="BNB",
            fee_mxn_per_unit=7000,
        )
    with pytest.raises(ValueError, match="contradictory"):
        _fill(
            "quote-fee",
            "BUY",
            1,
            10,
            "2026-01-01T00:00:00Z",
            fee_amount=1,
            fee_mxn_per_unit=19,
            fee_fx_source="contradictory operator input",
        )


def test_different_fee_currency_uses_its_own_explicit_mxn_rate() -> None:
    request = AfterTaxTcaRequest(
        initial_capital_mxn=1000,
        config=TaxLotLedgerConfig(),
        fills=(
            _fill(
                "buy",
                "BUY",
                1,
                10,
                "2026-01-01T00:00:00Z",
                fee_amount=Decimal("0.01"),
                fee_currency="BNB",
                fee_mxn_per_unit=7000,
                fee_fx_source="operator-supplied event-time BNB/MXN observation",
            ),
        ),
        marks=(_mark(unit_price_quote=10),),
        valuation_as_of_utc=VALUATION_AT,
    )

    result = evaluate_after_tax_tca(request)

    assert result.total_fees_mxn == Decimal("70")
    assert result.open_lots[0].cost_basis_remaining_mxn == Decimal("270")
    assert result.unrealized_pre_tax_pnl_mxn == Decimal("-70")


def test_missing_reference_or_mark_never_manufactures_complete_tca() -> None:
    request = AfterTaxTcaRequest(
        initial_capital_mxn=1000,
        config=TaxLotLedgerConfig(),
        fills=(
            _fill(
                "buy",
                "BUY",
                1,
                10,
                "2026-01-01T00:00:00Z",
                reference_price_quote=None,
                reference_at_utc=None,
                reference_source=None,
            ),
        ),
        marks=(),
        valuation_as_of_utc=VALUATION_AT,
    )

    result = evaluate_after_tax_tca(request)

    assert result.status == "INCOMPLETE_MARKS"
    assert result.missing_reference_fill_ids == ("buy",)
    assert result.missing_mark_instrument_ids == ("CMC:1",)
    assert result.signed_implementation_shortfall_mxn is None
    assert result.adverse_slippage_mxn is None
    assert result.transaction_cost_mxn is None
    assert result.mark_value_mxn is None
    assert result.equity_pnl_pre_tax_mxn is None


def test_missing_reference_with_complete_marks_is_explicitly_incomplete_tca() -> None:
    request = AfterTaxTcaRequest(
        initial_capital_mxn=1000,
        config=TaxLotLedgerConfig(),
        fills=(
            _fill(
                "buy",
                "BUY",
                1,
                10,
                "2026-01-01T00:00:00Z",
                reference_price_quote=None,
                reference_at_utc=None,
                reference_source=None,
            ),
        ),
        marks=(_mark(),),
        valuation_as_of_utc=VALUATION_AT,
    )

    result = evaluate_after_tax_tca(request)

    assert result.status == "INCOMPLETE_TCA"
    assert result.equity_pnl_pre_tax_mxn == Decimal("80")
    assert result.return_on_initial_capital_pre_tax == Decimal("0.08")
    assert result.signed_implementation_shortfall_mxn is None
    assert result.adverse_slippage_mxn is None
    assert result.transaction_cost_mxn is None


def test_reference_evidence_is_atomic_causal_and_source_bound() -> None:
    with pytest.raises(ValueError, match="supplied together"):
        _fill(
            "partial-reference",
            "BUY",
            1,
            10,
            "2026-01-01T00:00:00Z",
            reference_source=None,
        )
    with pytest.raises(ValueError, match="cannot be later"):
        _fill(
            "future-reference",
            "BUY",
            1,
            10,
            "2026-01-01T00:00:00Z",
            reference_at_utc="2026-01-01T00:00:01Z",
        )


def test_sell_larger_than_inventory_is_rejected_instead_of_creating_a_short() -> None:
    request = AfterTaxTcaRequest(
        initial_capital_mxn=1000,
        config=TaxLotLedgerConfig(),
        fills=(
            _fill("buy", "BUY", 1, 10, "2026-01-01T00:00:00Z"),
            _fill("sell", "SELL", 2, 11, "2026-01-02T00:00:00Z"),
        ),
        marks=(),
        valuation_as_of_utc=VALUATION_AT,
    )

    with pytest.raises(ValueError, match="exceeds long inventory"):
        evaluate_after_tax_tca(request)


def test_capital_shortfall_is_measured_but_never_authorizes_funding() -> None:
    request = replace(_fifo_request(), initial_capital_mxn=Decimal("2000"))

    result = evaluate_after_tax_tca(request)

    assert result.status == "INSUFFICIENT_FUNDING"
    assert result.minimum_funding_required_mxn == Decimal("3290.5")
    assert result.capital_shortfall_mxn == Decimal("1290.5")
    assert result.equity_pnl_pre_tax_mxn == Decimal("1113.5")
    assert result.return_on_initial_capital_pre_tax is None
    assert result.return_on_initial_capital_after_realized_tax_scenario is None
    assert result.to_dict()["real_money_authorized"] is False


def test_underfunded_round_trip_never_reports_an_impossible_return() -> None:
    request = AfterTaxTcaRequest(
        initial_capital_mxn=1,
        config=TaxLotLedgerConfig(),
        fills=(
            _fill("buy", "BUY", 1, 5, "2026-01-01T00:00:00Z"),
            _fill("sell", "SELL", 1, 10, "2026-01-02T00:00:00Z"),
        ),
        marks=(),
        valuation_as_of_utc=VALUATION_AT,
        tax_scenario=_scenario(),
    )

    result = evaluate_after_tax_tca(request)

    # The historical fills encode MXN 100 out and MXN 200 back.  With only
    # MXN 1 declared, a 100x return would require unreported external capital.
    assert result.realized_pre_tax_pnl_mxn == Decimal("100")
    assert result.equity_pnl_pre_tax_mxn == Decimal("100")
    assert result.minimum_funding_required_mxn == Decimal("100")
    assert result.capital_shortfall_mxn == Decimal("99")
    assert result.status == "INSUFFICIENT_FUNDING"
    assert result.return_on_initial_capital_pre_tax is None
    assert result.return_on_initial_capital_after_realized_tax_scenario is None
    payload = result.to_dict()
    assert payload["return_on_initial_capital_pre_tax"] is None
    assert payload["return_on_initial_capital_after_realized_tax_scenario"] is None
    assert payload["real_money_authorized"] is False


def test_sell_fee_that_exceeds_proceeds_is_included_in_funding_requirement() -> None:
    request = AfterTaxTcaRequest(
        initial_capital_mxn=1000,
        config=TaxLotLedgerConfig(),
        fills=(
            _fill("buy", "BUY", 1, 10, "2026-01-01T00:00:00Z"),
            _fill(
                "sell",
                "SELL",
                1,
                10,
                "2026-01-02T00:00:00Z",
                fee_amount=20,
            ),
        ),
        marks=(),
        valuation_as_of_utc=VALUATION_AT,
    )

    result = evaluate_after_tax_tca(request)

    assert result.minimum_funding_required_mxn == Decimal("400")


def test_price_improvement_is_signed_but_never_a_negative_transaction_cost() -> None:
    request = AfterTaxTcaRequest(
        initial_capital_mxn=1000,
        config=TaxLotLedgerConfig(),
        fills=(
            _fill(
                "buy",
                "BUY",
                1,
                9,
                "2026-01-01T00:00:00Z",
                reference_price_quote=10,
                fee_amount=1,
            ),
            _fill(
                "sell",
                "SELL",
                1,
                11,
                "2026-01-02T00:00:00Z",
                reference_price_quote=10,
            ),
        ),
        marks=(),
        valuation_as_of_utc=VALUATION_AT,
    )

    result = evaluate_after_tax_tca(request)

    assert result.status == "COMPLETE"
    assert result.signed_implementation_shortfall_mxn == Decimal("-40")
    assert result.adverse_slippage_mxn == 0
    assert result.total_fees_mxn == Decimal("20")
    assert result.transaction_cost_mxn == Decimal("20")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), True, 0, -1])
def test_initial_capital_must_be_finite_and_positive(value: object) -> None:
    with pytest.raises(ValueError, match="finite|bool|greater than zero"):
        replace(_fifo_request(), initial_capital_mxn=value)  # type: ignore[arg-type]


def test_digest_binds_every_fill_fx_fee_mark_and_tax_assumption() -> None:
    baseline = evaluate_after_tax_tca(_fifo_request(scenario=_scenario()))
    same_numbers = evaluate_after_tax_tca(
        replace(_fifo_request(scenario=_scenario()), initial_capital_mxn=Decimal("4000.00"))
    )
    altered_fill = replace(
        baseline.request.fills[0],
        mxn_per_quote=Decimal("20.01"),
    )
    altered = evaluate_after_tax_tca(
        replace(baseline.request, fills=(altered_fill, *baseline.request.fills[1:]))
    )
    altered_reference = evaluate_after_tax_tca(
        replace(
            baseline.request,
            fills=(
                replace(baseline.request.fills[0], reference_source="different source"),
                *baseline.request.fills[1:],
            ),
        )
    )
    altered_valuation = evaluate_after_tax_tca(
        replace(
            baseline.request,
            marks=(_mark(as_of_utc="2026-01-05T00:00:00Z"),),
            valuation_as_of_utc="2026-01-05T00:00:00Z",
        )
    )

    assert baseline.request_digest == same_numbers.request_digest
    assert baseline.measurement_digest == same_numbers.measurement_digest
    assert baseline.request_digest != altered.request_digest
    assert baseline.measurement_digest != altered.measurement_digest
    assert baseline.request_digest != altered_reference.request_digest
    assert baseline.measurement_digest != altered_reference.measurement_digest
    assert baseline.request_digest != altered_valuation.request_digest
    assert baseline.measurement_digest != altered_valuation.measurement_digest
    payload = baseline.to_dict()
    digest = payload.pop("measurement_digest")
    assert digest == sha256_of_text(canonical_dumps(payload))
    assert baseline.is_verified()


def test_request_and_result_are_deeply_immutable() -> None:
    fills = list(_fifo_request().fills)
    marks = [_mark()]
    request = AfterTaxTcaRequest(
        initial_capital_mxn=4000,
        config=TaxLotLedgerConfig(),
        fills=fills,  # type: ignore[arg-type]
        marks=marks,  # type: ignore[arg-type]
        valuation_as_of_utc=VALUATION_AT,
    )
    result = evaluate_after_tax_tca(request)
    fills.clear()
    marks.clear()

    assert len(request.fills) == 3
    assert len(request.marks) == 1
    assert isinstance(request.fills, tuple)
    assert isinstance(result.open_lots, tuple)
    with pytest.raises(FrozenInstanceError):
        request.initial_capital_mxn = Decimal("1")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.total_fees_mxn = Decimal("0")  # type: ignore[misc]


def test_duplicates_out_of_order_marks_and_unsupported_policies_are_rejected() -> None:
    buy = _fill("duplicate", "BUY", 1, 10, "2026-01-02T00:00:00Z")
    earlier = _fill("earlier", "BUY", 1, 10, "2026-01-01T00:00:00Z")
    with pytest.raises(ValueError, match="unique"):
        AfterTaxTcaRequest(1000, TaxLotLedgerConfig(), (buy, buy), (), VALUATION_AT)
    with pytest.raises(ValueError, match="execution order"):
        AfterTaxTcaRequest(1000, TaxLotLedgerConfig(), (buy, earlier), (), VALUATION_AT)
    with pytest.raises(ValueError, match="cannot predate"):
        AfterTaxTcaRequest(
            1000,
            TaxLotLedgerConfig(),
            (buy,),
            (),
            "2026-01-01T00:00:00Z",
        )
    with pytest.raises(ValueError, match="exact valuation"):
        AfterTaxTcaRequest(
            1000,
            TaxLotLedgerConfig(),
            (buy,),
            (_mark(as_of_utc="2026-01-03T00:00:00Z"),),
            VALUATION_AT,
        )
    with pytest.raises(ValueError, match="exact valuation"):
        AfterTaxTcaRequest(
            1000,
            TaxLotLedgerConfig(),
            (buy,),
            (
                _mark(),
                _mark(
                    instrument_id="CMC:2",
                    as_of_utc="2026-01-03T23:59:59Z",
                ),
            ),
            VALUATION_AT,
        )
    with pytest.raises(ValueError, match="FIFO"):
        TaxLotLedgerConfig(lot_method="LIFO")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="explicitly declared"):
        _scenario(declared_by_user=False)
    with pytest.raises(ValueError, match="between zero and one"):
        _scenario(tax_rate_fraction=Decimal("1.01"))
