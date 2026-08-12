from __future__ import annotations

from dataclasses import replace

import pytest

from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_text
from quant_trade.ops.crypto_capital import (
    CapitalFeasibilityRequest,
    CapitalInstrumentEvidence,
    FxEvidence,
    evaluate_capital_feasibility,
)

AS_OF = "2026-08-12T12:00:00Z"
CAPTURED = "2026-08-12T11:00:00Z"


def _fx(**overrides: object) -> FxEvidence:
    values: dict[str, object] = {
        "base_currency": "MXN",
        "quote_currency": "USDT",
        "quote_per_base": 0.054,
        "captured_at_utc": CAPTURED,
        "source": "operator-supplied MXN/USDT snapshot",
    }
    values.update(overrides)
    if "source_payload" not in overrides:
        values["source_payload"] = {
            "base_currency": values["base_currency"],
            "quote_currency": values["quote_currency"],
            "quote_per_base": values["quote_per_base"],
            "captured_at_utc": values["captured_at_utc"],
        }
    if "raw_sha256" not in overrides:
        values["raw_sha256"] = sha256_of_text(canonical_dumps(values["source_payload"]))
    return FxEvidence(**values)  # type: ignore[arg-type]


def _instrument(index: int, **overrides: object) -> CapitalInstrumentEvidence:
    values: dict[str, object] = {
        "instrument_id": f"CMC:{index}",
        "venue_symbol": f"COIN{index}USDT",
        "base_currency": f"COIN{index}",
        "quote_currency": "USDT",
        "reference_ask_quote": 1.0,
        "tick_size_quote": 0.01,
        "quantity_step": 0.1,
        "min_notional_quote": 1.0,
        "taker_fee_bps": 10.0,
        "fee_currency": "USDT",
        "fee_charging_mode": "QUOTE_ON_TOP",
        "minimum_fee_amount": 0.0,
        "captured_at_utc": CAPTURED,
        "source": "operator-supplied instrument and account-fee snapshot",
    }
    values.update(overrides)
    if "source_payload" not in overrides:
        values["source_payload"] = {
            "venue": "bybit",
            "market": "spot",
            "environment": "demo",
            "account_scope": "dedicated_subaccount",
            **{
                name: values[name]
                for name in (
                    "instrument_id",
                    "venue_symbol",
                    "base_currency",
                    "quote_currency",
                    "reference_ask_quote",
                    "tick_size_quote",
                    "quantity_step",
                    "min_notional_quote",
                    "taker_fee_bps",
                    "fee_currency",
                    "fee_charging_mode",
                    "minimum_fee_amount",
                    "captured_at_utc",
                )
            },
        }
    if "raw_sha256" not in overrides:
        values["raw_sha256"] = sha256_of_text(canonical_dumps(values["source_payload"]))
    return CapitalInstrumentEvidence(**values)  # type: ignore[arg-type]


def _request(
    *,
    count: int = 20,
    fx: FxEvidence | None = None,
    instruments: tuple[CapitalInstrumentEvidence, ...] | None = None,
    **overrides: object,
) -> CapitalFeasibilityRequest:
    values: dict[str, object] = {
        "sleeve_amount": 1_000.0,
        "sleeve_currency": "MXN",
        "as_of_utc": AS_OF,
        "fx": fx or _fx(),
        "instruments": instruments or tuple(_instrument(index) for index in range(1, count + 1)),
        "venue": "bybit",
        "market": "spot",
        "environment": "demo",
        "account_scope": "dedicated_subaccount",
        "quote_to_usd_fx": _fx(
            base_currency="USDT",
            quote_currency="USD",
            quote_per_base=0.999,
        ),
    }
    values.update(overrides)
    return CapitalFeasibilityRequest(**values)  # type: ignore[arg-type]


def test_mxn_1000_passes_only_with_twenty_reproducibly_feasible_symbols() -> None:
    result = evaluate_capital_feasibility(_request())

    assert result.status == "PASS"
    assert result.minimum_distinct_assets == 20
    assert result.per_asset_cap_sleeve == pytest.approx(50.0)
    assert result.per_asset_cap_quote == pytest.approx(2.7)
    assert result.sleeve_amount_quote == pytest.approx(54.0)
    assert result.sleeve_amount_usd == pytest.approx(53.946)
    assert len(result.feasible_symbols) == 20
    assert result.is_verified()
    payload = result.to_dict()
    assert payload["external_action_authorized"] is False
    assert payload["real_money_authorized"] is False


def test_nineteen_symbols_is_no_go_under_five_percent_cap() -> None:
    result = evaluate_capital_feasibility(_request(count=19))

    assert result.status == "NO_GO"
    assert any("19 instruments" in item for item in result.blocking_conditions)


def test_mxn_1000_cannot_clear_a_five_usdt_minimum_under_the_five_percent_cap() -> None:
    instruments = tuple(_instrument(index, min_notional_quote=5.0) for index in range(1, 21))

    result = evaluate_capital_feasibility(_request(instruments=instruments))

    assert result.status == "NO_GO"
    assert result.per_asset_cap_quote == pytest.approx(2.7)
    assert not result.feasible_symbols
    assert all(item.status == "INFEASIBLE" for item in result.assessments)


def test_fee_can_push_minimum_order_above_the_per_asset_cap() -> None:
    instruments = tuple(_instrument(index) for index in range(1, 20)) + (
        _instrument(20, min_notional_quote=2.7),
    )
    result = evaluate_capital_feasibility(_request(instruments=instruments))

    assert result.status == "NO_GO"
    assessment = result.assessments[-1]
    assert assessment.minimum_executable_notional_quote == pytest.approx(2.7)
    assert assessment.minimum_total_outlay_quote == pytest.approx(2.7027)
    assert assessment.status == "INFEASIBLE"


def test_base_currency_fee_floor_cannot_consume_the_entire_order() -> None:
    instruments = tuple(_instrument(index) for index in range(1, 20)) + (
        _instrument(
            20,
            fee_currency="COIN20",
            fee_charging_mode="RECEIVED_ASSET_DEDUCTION",
            minimum_fee_amount=1.0,
        ),
    )
    result = evaluate_capital_feasibility(_request(instruments=instruments))

    assert result.status == "NO_GO"
    assert result.assessments[-1].status == "INFEASIBLE"
    assert "consumes" in result.assessments[-1].reason


def test_tick_and_quantity_step_are_applied_to_the_real_minimum() -> None:
    instruments = tuple(_instrument(index) for index in range(1, 20)) + (
        _instrument(
            20,
            reference_ask_quote=1.001,
            tick_size_quote=0.01,
            quantity_step=1.0,
            min_notional_quote=2.65,
        ),
    )
    result = evaluate_capital_feasibility(_request(instruments=instruments))

    assert result.status == "NO_GO"
    assert result.assessments[-1].minimum_executable_notional_quote == pytest.approx(3.03)


def test_missing_or_stale_fx_is_insufficient_evidence() -> None:
    missing = evaluate_capital_feasibility(_request(fx=_fx(quote_per_base=None)))
    stale = evaluate_capital_feasibility(_request(fx=_fx(captured_at_utc="2026-08-10T11:00:00Z")))

    assert missing.status == "INSUFFICIENT_EVIDENCE"
    assert "fx.quote_per_base" in missing.missing_conditions
    assert stale.status == "INSUFFICIENT_EVIDENCE"
    assert "fx.current_snapshot" in stale.missing_conditions


def test_currency_or_fee_mode_contradictions_are_no_go() -> None:
    wrong_quote = tuple(_instrument(index) for index in range(1, 20)) + (
        _instrument(20, quote_currency="USDC"),
    )
    wrong_fee = tuple(_instrument(index) for index in range(1, 20)) + (
        _instrument(20, fee_currency="COIN20"),
    )

    quote_result = evaluate_capital_feasibility(_request(instruments=wrong_quote))
    fee_result = evaluate_capital_feasibility(_request(instruments=wrong_fee))
    assert quote_result.status == fee_result.status == "NO_GO"
    assert any("FX quote" in item for item in quote_result.blocking_conditions)
    assert any("QUOTE_ON_TOP" in item for item in fee_result.blocking_conditions)


@pytest.mark.parametrize(
    ("field", "altered"),
    [
        ("venue_symbol", "FAKEUSDT"),
        ("base_currency", "FAKE"),
        ("quote_currency", "USDC"),
        ("reference_ask_quote", 2.0),
        ("tick_size_quote", 0.02),
        ("quantity_step", 0.2),
        ("min_notional_quote", 999.0),
        ("taker_fee_bps", 20.0),
        ("fee_currency", "COIN20"),
        ("fee_charging_mode", "RECEIVED_ASSET_DEDUCTION"),
        ("minimum_fee_amount", 0.5),
        ("captured_at_utc", "2026-08-12T10:00:00Z"),
    ],
)
def test_source_payload_fields_are_cross_checked_after_hashing(
    field: str,
    altered: object,
) -> None:
    genuine = _instrument(20)
    altered_payload = dict(genuine.source_payload or {})
    altered_payload[field] = altered
    tampered = tuple(_instrument(index) for index in range(1, 20)) + (
        _instrument(
            20,
            source_payload=altered_payload,
            raw_sha256=sha256_of_text(canonical_dumps(altered_payload)),
        ),
    )
    result = evaluate_capital_feasibility(_request(instruments=tampered))

    assert result.status == "NO_GO"
    assert any("normalized evidence" in item for item in result.blocking_conditions)


def test_fx_source_payload_fields_are_cross_checked_after_hashing() -> None:
    genuine = _fx()
    altered_payload = dict(genuine.source_payload or {})
    altered_payload["quote_per_base"] = 99.0
    result = evaluate_capital_feasibility(
        _request(
            fx=_fx(
                source_payload=altered_payload,
                raw_sha256=sha256_of_text(canonical_dumps(altered_payload)),
            )
        )
    )

    assert result.status == "NO_GO"
    assert any("fx.source_payload.quote_per_base" in item for item in result.blocking_conditions)


def test_claimed_source_hash_must_match_canonical_payload_bytes() -> None:
    result = evaluate_capital_feasibility(_request(fx=_fx(raw_sha256="0" * 64)))

    assert result.status == "NO_GO"
    assert any(
        "contradicts canonical source_payload" in item for item in result.blocking_conditions
    )


def test_missing_payload_is_insufficient_and_sensitive_payload_is_no_go() -> None:
    missing = evaluate_capital_feasibility(_request(fx=_fx(source_payload=None)))
    sensitive = evaluate_capital_feasibility(
        _request(fx=_fx(source_payload={"api_key": "must-not-be-here"}))
    )

    assert missing.status == "INSUFFICIENT_EVIDENCE"
    assert "fx.source_payload" in missing.missing_conditions
    assert sensitive.status == "NO_GO"
    assert any("sensitive-looking" in item for item in sensitive.blocking_conditions)


def test_string_payload_is_insufficient_even_when_its_hash_matches() -> None:
    payload = "MXN/USDT=0.054"
    result = evaluate_capital_feasibility(
        _request(
            fx=_fx(
                source_payload=payload,  # type: ignore[arg-type]
                raw_sha256=sha256_of_text(canonical_dumps(payload)),
            )
        )
    )

    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert "fx.source_payload.mapping" in result.missing_conditions


def test_non_usd_execution_quote_requires_byte_bound_quote_to_usd_fx() -> None:
    result = evaluate_capital_feasibility(_request(quote_to_usd_fx=None))

    assert result.status == "INSUFFICIENT_EVIDENCE"
    assert "quote_to_usd_fx" in result.missing_conditions


def test_invalid_fx_object_fails_closed_without_crashing() -> None:
    result = evaluate_capital_feasibility(_request(fx="not-fx-evidence"))  # type: ignore[arg-type]

    assert result.status == "NO_GO"
    assert any("fx must be FxEvidence" in item for item in result.blocking_conditions)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("venue", "binance"),
        ("market", "linear"),
        ("environment", "live"),
        ("account_scope", "shared_account"),
    ],
)
def test_capital_evidence_cannot_be_reused_outside_bybit_demo_spot(
    field: str,
    value: str,
) -> None:
    result = evaluate_capital_feasibility(_request(**{field: value}))

    assert result.status == "NO_GO"
    assert any(field in item for item in result.blocking_conditions)


@pytest.mark.parametrize("duplicate_field", ["venue_symbol", "base_currency"])
def test_aliases_cannot_manufacture_twenty_distinct_assets(duplicate_field: str) -> None:
    duplicate_value = getattr(_instrument(19), duplicate_field)
    instruments = tuple(_instrument(index) for index in range(1, 20)) + (
        _instrument(20, **{duplicate_field: duplicate_value}),
    )
    result = evaluate_capital_feasibility(_request(instruments=instruments))

    assert result.status == "NO_GO"
    assert any(duplicate_field in item for item in result.blocking_conditions)


@pytest.mark.parametrize("value", [True, -1.0, float("nan"), float("inf")])
def test_invalid_sleeve_never_passes(value: object) -> None:
    result = evaluate_capital_feasibility(_request(sleeve_amount=value))
    assert result.status == "NO_GO"


def test_a_caller_cannot_relax_the_five_percent_hard_ceiling() -> None:
    result = evaluate_capital_feasibility(_request(maximum_asset_fraction=0.5))

    assert result.status == "NO_GO"
    assert result.maximum_asset_fraction == 0.05
    assert any("hard ceiling" in item for item in result.blocking_conditions)


def test_tampered_result_fails_recomputation() -> None:
    genuine = evaluate_capital_feasibility(_request(count=19))
    forged = replace(genuine, status="PASS", blocking_conditions=())

    assert genuine.is_verified()
    assert not forged.is_verified()
