from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs" / "data" / "ccdata_world_order_flow_request_v1.yaml"


def _contract() -> dict[str, object]:
    loaded = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def test_procurement_contract_is_non_executing_and_requires_a_quote() -> None:
    contract = _contract()

    assert contract["commercial_status"] == "QUOTE_REQUIRED"
    assert contract["purchase_authorized"] is False
    assert contract["credentials_required_in_repo"] is False
    acceptance = contract["acceptance"]
    assert isinstance(acceptance, dict)
    assert acceptance["pnl_or_real_money_authorized"] is False
    economics = contract["economic_acceptance"]
    assert isinstance(economics, dict)
    assert economics["purchase_gate"] == "INSUFFICIENT_EVIDENCE"
    assert economics["maximum_fixed_data_cost_usd"] is None


def test_procurement_contract_requests_exact_flow_and_vintage_evidence() -> None:
    contract = _contract()
    delivery = contract["required_delivery"]
    assert isinstance(delivery, dict)

    fields = set(delivery["fields"])
    assert {
        "VOLUME_BUY",
        "VOLUME_SELL",
        "VOLUME_UNKNOWN",
        "QUOTE_VOLUME_BUY",
        "QUOTE_VOLUME_SELL",
        "QUOTE_VOLUME_UNKNOWN",
        "BASE_ID",
        "QUOTE_ID",
        "TRANSFORM_FUNCTION",
    } <= fields
    correction_fields = set(delivery["correction_fields"])
    assert {
        "CCSEQ",
        "SIDE",
        "SOURCE",
        "STATUS",
        "RECEIVED_TIMESTAMP",
        "revised_at_utc",
        "prior_status",
        "new_status",
    } <= correction_fields

    licence = contract["licence_requirements"]
    assert isinstance(licence, dict)
    assert licence["own_account_trading"] == "explicitly_permitted_in_writing"
    assert licence["redistribution"] == "not_requested"


def test_procurement_contract_contains_no_contact_identity_or_secret() -> None:
    text = CONTRACT.read_text(encoding="utf-8").lower()
    for forbidden in (
        "api_key",
        "password",
        "authorization:",
        "first_name",
        "last_name",
        "email_address",
    ):
        assert forbidden not in text
