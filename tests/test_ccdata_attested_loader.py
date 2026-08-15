"""Offline adversarial tests for the externally attested CCData loader."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from quant_trade.data.ccdata_attested_loader import (
    BUNDLE_TYPE,
    REQUIRED_LICENSE_USES,
    REQUIRED_PROVIDER_FIELDS,
    SIGNATURE_ALGORITHM,
    SOURCE_CONTRACT,
    STATEMENT_TYPE,
    AttestationTrustRoot,
    CCDataAttestedLoaderError,
    CCDataSourceReceipt,
    LoadedAttestedCCDataBundle,
    ParsedCCDataDelivery,
    load_attested_ccdata_bundle,
)
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes

PRODUCT = "ccdata-world-flow-contract-2026"
KNOWLEDGE = "2025-04-02T12:00:00Z"
VERIFICATION = "2025-04-06T12:00:00Z"


def _canonical_bytes(value: object) -> bytes:
    return (canonical_dumps(value) + "\n").encode()


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


class _ContractedFixtureParser:
    parser_name = "ccdata-world-flow-parser"
    parser_version = "1.0.0"
    provider_product_id = PRODUCT
    provider_schema_version = "2.1.2009-contract-1"

    def __init__(self, schema_sha256: str) -> None:
        self.provider_schema_sha256 = schema_sha256

    def parse(self, raw: bytes, *, receipt: CCDataSourceReceipt) -> ParsedCCDataDelivery:
        payload = json.loads(raw)
        observations: list[dict[str, Any]] = []
        venues: list[dict[str, Any]] = []
        seen_days: set[str] = set()
        for item in payload["observations"]:
            day = item["measurement_date"]
            row = {
                "schema_version": 1,
                "stable_asset_id": f"CMC:{item['cmc_id']}",
                "cmc_id": item["cmc_id"],
                "chain_id": item["chain_id"],
                "contract_or_native_id": item["contract_or_native_id"],
                "measurement_date": day,
                "fiat_currency": item["fiat_currency"],
                "buyer_initiated_volume": item["buyer_initiated_volume"],
                "seller_initiated_volume": item["seller_initiated_volume"],
                "contributing_venues": item["contributing_venues"],
                "signed_volume_definition": "BUYER_AND_SELLER_INITIATED",
                "source_scope": "MULTI_VENUE_FIAT",
                "computed_at_utc": item["computed_at_utc"],
                "published_at_utc": item["published_at_utc"],
                "available_at_utc": receipt.available_at_utc,
                "vintage_id": receipt.vintage_id,
                "revision_id": receipt.revision_id,
                "revision_sequence": receipt.revision_sequence,
                "source_receipt_sha256": receipt.receipt_sha256,
            }
            observations.append(row)
            if day not in seen_days:
                venues.append(
                    {
                        "schema_version": 1,
                        "measurement_date": day,
                        "contributing_venues": item["contributing_venues"],
                        "available_at_utc": receipt.available_at_utc,
                        "vintage_id": receipt.vintage_id,
                        "revision_id": receipt.revision_id,
                        "revision_sequence": receipt.revision_sequence,
                        "source_receipt_sha256": receipt.receipt_sha256,
                    }
                )
                seen_days.add(day)
        return ParsedCCDataDelivery(tuple(observations), tuple(venues))


@dataclass(frozen=True)
class _BuiltBundle:
    root: Path
    trust_root: AttestationTrustRoot
    private_key: Ed25519PrivateKey
    parser: _ContractedFixtureParser
    data_paths: tuple[Path, ...]


def _source_receipt(
    root: Path,
    *,
    sequence: int,
    role: str,
    raw: bytes,
    previous: str,
    available_at_utc: str,
    captured_at_utc: str,
    vintage_id: str = "",
    revision_id: str = "",
    revision_sequence: int = 0,
    supersedes: str = "",
) -> tuple[dict[str, Any], Path]:
    path = f"source/{sequence:02d}-{role.lower()}.bin"
    target = root / Path(path)
    _write(target, raw)
    body: dict[str, Any] = {
        "schema_version": 1,
        "sequence": sequence,
        "receipt_id": f"receipt-{sequence:02d}-{role.lower()}",
        "role": role,
        "path": path.replace("\\", "/"),
        "media_type": "application/octet-stream",
        "byte_length": len(raw),
        "sha256": sha256_of_bytes(raw),
        "captured_at_utc": captured_at_utc,
        "available_at_utc": available_at_utc,
        "vintage_id": vintage_id,
        "revision_id": revision_id,
        "revision_sequence": revision_sequence,
        "supersedes_receipt_sha256": supersedes,
        "previous_receipt_sha256": previous,
    }
    body["receipt_sha256"] = sha256_of_bytes(canonical_dumps(body).encode())
    return body, target


def _build_bundle(
    root: Path,
    *,
    include_future: bool = False,
    include_revision: bool = False,
) -> _BuiltBundle:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    trust_root = AttestationTrustRoot(
        root_id="ccdata-review-root-2026",
        issuer_id="independent-data-license-reviewer",
        key_id="review-key-2026-01",
        algorithm=SIGNATURE_ALGORITHM,
        verification_key=public_key,
        valid_from_utc="2025-01-01T00:00:00Z",
        valid_until_utc="2027-01-01T00:00:00Z",
        allowed_provider_product_ids=(PRODUCT,),
    )
    calendar_dates = [
        "2025-02-17",
        "2025-02-18",
        "2025-02-19",
        "2025-02-20",
        "2025-02-21",
        "2025-02-24",
        "2025-02-25",
        "2025-02-26",
        "2025-02-27",
        "2025-02-28",
        "2025-03-03",
        "2025-03-04",
    ]
    schema_raw = _canonical_bytes(
        {
            "openapi_version": "3.0.3",
            "operation": "spot_v1_historical_days",
            "provider_fields": list(REQUIRED_PROVIDER_FIELDS),
        }
    )
    externals = (
        ("COMMERCIAL_QUOTE", b"signed commercial quote"),
        ("LICENSE_TERMS", b"exact provider terms"),
        ("LICENSE_GRANT", b"executed own-account grant"),
        (
            "PAPER_CALENDAR",
            _canonical_bytes(
                {
                    "schema_version": 1,
                    "calendar_name": "WEEKDAYS_EXCLUDING_US_HOLIDAYS",
                    "method_version": "paper-calendar-v1",
                    "source_name": "reviewed-us-calendar",
                    "dates": calendar_dates,
                }
            ),
        ),
        ("PROVIDER_SCHEMA", schema_raw),
        ("REVISION_POLICY", b"append-only old/new revision policy"),
    )
    receipts: list[dict[str, Any]] = []
    previous = "0" * 64
    for role, raw in externals:
        receipt, _ = _source_receipt(
            root,
            sequence=len(receipts) + 1,
            role=role,
            raw=raw,
            previous=previous,
            available_at_utc="2025-01-10T00:00:00Z",
            captured_at_utc="2025-01-10T01:00:00Z",
        )
        receipts.append(receipt)
        previous = receipt["receipt_sha256"]

    data_specs: list[dict[str, Any]] = [
        {
            "measurement_date": "2025-03-03",
            "cmc_id": 1,
            "chain_id": "bitcoin",
            "contract_or_native_id": "native",
            "fiat_currency": "USD",
            "buyer_initiated_volume": "100.25",
            "seller_initiated_volume": "98.75",
            "contributing_venues": ["coinbase", "kraken"],
            "computed_at_utc": "2025-03-04T00:01:00Z",
            "published_at_utc": "2025-03-04T00:05:00Z",
            "available_at_utc": "2025-03-04T00:10:00Z",
            "vintage_id": "vintage-20250304",
            "revision_id": "revision-0",
            "revision_sequence": 0,
            "supersedes": "",
        }
    ]
    if include_revision:
        data_specs.append(
            {
                **data_specs[0],
                "buyer_initiated_volume": "101.25",
                "available_at_utc": "2025-03-20T00:10:00Z",
                "revision_id": "revision-1",
                "revision_sequence": 1,
                "supersedes": "PREVIOUS_DATA",
            }
        )
    if include_future:
        data_specs.append(
            {
                **data_specs[0],
                "measurement_date": "2025-04-03",
                "computed_at_utc": "2025-04-04T00:01:00Z",
                "published_at_utc": "2025-04-04T00:05:00Z",
                "available_at_utc": "2025-04-04T00:10:00Z",
                "vintage_id": "vintage-20250404",
                "revision_id": "revision-0-future",
                "revision_sequence": 0,
                "supersedes": "",
            }
        )

    parser = _ContractedFixtureParser(sha256_of_bytes(schema_raw))
    data_paths: list[Path] = []
    first_data_receipt = ""
    for spec in data_specs:
        raw_item = {
            key: spec[key]
            for key in (
                "measurement_date",
                "cmc_id",
                "chain_id",
                "contract_or_native_id",
                "fiat_currency",
                "buyer_initiated_volume",
                "seller_initiated_volume",
                "contributing_venues",
                "computed_at_utc",
                "published_at_utc",
            )
        }
        raw = _canonical_bytes({"observations": [raw_item]})
        supersedes = first_data_receipt if spec["supersedes"] else ""
        receipt, path = _source_receipt(
            root,
            sequence=len(receipts) + 1,
            role="SIGNED_VOLUME_RAW",
            raw=raw,
            previous=previous,
            available_at_utc=spec["available_at_utc"],
            captured_at_utc=spec["available_at_utc"].replace("10:00Z", "15:00Z"),
            vintage_id=spec["vintage_id"],
            revision_id=spec["revision_id"],
            revision_sequence=spec["revision_sequence"],
            supersedes=supersedes,
        )
        if not first_data_receipt:
            first_data_receipt = receipt["receipt_sha256"]
        receipts.append(receipt)
        data_paths.append(path)
        previous = receipt["receipt_sha256"]

    parsed_observations: list[dict[str, Any]] = []
    parsed_venues: list[dict[str, Any]] = []
    for receipt, path in zip(receipts[6:], data_paths, strict=True):
        typed = CCDataSourceReceipt(
            sequence=receipt["sequence"],
            receipt_id=receipt["receipt_id"],
            role=receipt["role"],
            path=receipt["path"],
            media_type=receipt["media_type"],
            byte_length=receipt["byte_length"],
            sha256=receipt["sha256"],
            captured_at_utc=receipt["captured_at_utc"],
            available_at_utc=receipt["available_at_utc"],
            vintage_id=receipt["vintage_id"],
            revision_id=receipt["revision_id"],
            revision_sequence=receipt["revision_sequence"],
            supersedes_receipt_sha256=receipt["supersedes_receipt_sha256"],
            previous_receipt_sha256=receipt["previous_receipt_sha256"],
            receipt_sha256=receipt["receipt_sha256"],
        )
        parsed = parser.parse(path.read_bytes(), receipt=typed)
        parsed_observations.extend(parsed.observations)
        parsed_venues.extend(parsed.venue_constituents)
    normalized_raw = b"".join(_canonical_bytes(row) for row in parsed_observations)
    venues_raw = b"".join(_canonical_bytes(row) for row in parsed_venues)
    data_by_receipt = {receipt["receipt_sha256"]: receipt for receipt in receipts[6:]}
    revision_events: list[dict[str, Any]] = []
    for receipt in receipts[6:]:
        if receipt["revision_sequence"] == 0:
            continue
        predecessor = data_by_receipt[receipt["supersedes_receipt_sha256"]]
        revision_events.append(
            {
                "schema_version": 1,
                "vintage_id": receipt["vintage_id"],
                "prior_revision_id": predecessor["revision_id"],
                "revision_id": receipt["revision_id"],
                "revision_sequence": receipt["revision_sequence"],
                "revised_at_utc": receipt["available_at_utc"],
                "old_source_receipt_sha256": predecessor["receipt_sha256"],
                "old_source_bytes_sha256": predecessor["sha256"],
                "new_source_receipt_sha256": receipt["receipt_sha256"],
                "new_source_bytes_sha256": receipt["sha256"],
            }
        )
    revisions_raw = _canonical_bytes({"schema_version": 1, "events": revision_events})
    _write(root / "derived/observations.jsonl", normalized_raw)
    _write(root / "derived/venues.jsonl", venues_raw)
    _write(root / "derived/revisions.json", revisions_raw)

    by_role = {receipt["role"]: receipt for receipt in receipts[:6]}
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "bundle_type": BUNDLE_TYPE,
        "provider_name": "CCData",
        "provider_product_id": PRODUCT,
        "delivery_id": "delivery-2025-04",
        "provider_schema_version": parser.provider_schema_version,
        "source_contract": SOURCE_CONTRACT,
        "provider_operation_ids": ["spot_v1_historical_days"],
        "required_provider_fields": list(REQUIRED_PROVIDER_FIELDS),
        "parser_name": parser.parser_name,
        "parser_version": parser.parser_version,
        "classification_method": "buyer-seller-initiator-classification",
        "classification_method_version": "contract-2026-01",
        "aggregation_method": "g11-multi-venue-sum",
        "aggregation_method_version": "contract-2026-01",
        "license": {
            "licensee_fingerprint_sha256": "a" * 64,
            "permitted_uses": list(REQUIRED_LICENSE_USES),
            "territories": ["MX"],
            "valid_from_utc": "2025-01-01T00:00:00Z",
            "valid_until_utc": "2026-01-01T00:00:00Z",
            "terms_receipt_sha256": by_role["LICENSE_TERMS"]["receipt_sha256"],
            "grant_receipt_sha256": by_role["LICENSE_GRANT"]["receipt_sha256"],
            "quote_receipt_sha256": by_role["COMMERCIAL_QUOTE"]["receipt_sha256"],
        },
        "vintage_policy": {
            "policy_id": "ccdata-replay-contract",
            "policy_version": "1.0.0",
            "revision_policy_receipt_sha256": by_role["REVISION_POLICY"]["receipt_sha256"],
            "historical_vintages_preserved": True,
            "corrections_are_append_only": True,
            "correction_log_includes_revised_at": True,
            "correction_log_includes_old_and_new_values": True,
            "revision_history_complete_through_utc": KNOWLEDGE,
        },
        "source_receipts": receipts,
        "derived_artifacts": {
            "normalized_observations": {
                "schema_version": 1,
                "path": "derived/observations.jsonl",
                "media_type": "application/x-ndjson",
                "byte_length": len(normalized_raw),
                "sha256": sha256_of_bytes(normalized_raw),
            },
            "venue_constituents": {
                "schema_version": 1,
                "path": "derived/venues.jsonl",
                "media_type": "application/x-ndjson",
                "byte_length": len(venues_raw),
                "sha256": sha256_of_bytes(venues_raw),
            },
            "revision_log": {
                "schema_version": 1,
                "path": "derived/revisions.json",
                "media_type": "application/json",
                "byte_length": len(revisions_raw),
                "sha256": sha256_of_bytes(revisions_raw),
            },
        },
    }
    manifest_raw = _canonical_bytes(manifest)
    _write(root / "manifest.json", manifest_raw)
    attestation = {
        "schema_version": 1,
        "statement_type": STATEMENT_TYPE,
        "statement_id": "review-statement-2025-04",
        "issuer_id": trust_root.issuer_id,
        "key_id": trust_root.key_id,
        "algorithm": SIGNATURE_ALGORITHM,
        "issued_at_utc": "2025-04-05T12:00:00Z",
        "expires_at_utc": "2026-01-01T00:00:00Z",
        "provider_name": "CCData",
        "provider_product_id": PRODUCT,
        "delivery_id": "delivery-2025-04",
        "manifest_sha256": sha256_of_bytes(manifest_raw),
        "claims": {
            "source_bytes_authentic": True,
            "provider_schema_authentic": True,
            "historical_vintages_authentic": True,
            "revision_history_complete": True,
            "historical_correction_log_authentic": True,
            "venue_constituents_authentic": True,
            "commercial_quote_authentic": True,
            "commercial_license_terms_authentic": True,
            "commercial_license_grant_executed": True,
            "financial_product_restriction_reviewed_and_own_account_trading_permitted": True,
        },
    }
    attestation_raw = _canonical_bytes(attestation)
    _write(root / "attestation.json", attestation_raw)
    _write(root / "attestation.sig", private_key.sign(attestation_raw))
    return _BuiltBundle(root, trust_root, private_key, parser, tuple(data_paths))


def _load(bundle: _BuiltBundle) -> LoadedAttestedCCDataBundle:
    return load_attested_ccdata_bundle(
        bundle.root,
        trust_root=bundle.trust_root,
        parser=bundle.parser,
        knowledge_cutoff_utc=KNOWLEDGE,
        verification_at_utc=VERIFICATION,
    )


def _resign_manifest(bundle: _BuiltBundle, mutate: Any) -> None:
    manifest_path = bundle.root / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    mutate(manifest)
    manifest_raw = _canonical_bytes(manifest)
    manifest_path.write_bytes(manifest_raw)
    attestation_path = bundle.root / "attestation.json"
    attestation = json.loads(attestation_path.read_bytes())
    attestation["manifest_sha256"] = sha256_of_bytes(manifest_raw)
    attestation_raw = _canonical_bytes(attestation)
    attestation_path.write_bytes(attestation_raw)
    (bundle.root / "attestation.sig").write_bytes(bundle.private_key.sign(attestation_raw))


def test_real_ed25519_bundle_is_rehashed_reparsed_and_remains_data_only(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path / "bundle")
    loaded = _load(bundle)

    assert loaded.external_signature_verified_to_supplied_root is True
    assert loaded.commercial_license_claim_signature_verified is True
    assert loaded.commercial_data_use_authorized is False
    assert len(loaded.rows) == 1
    assert loaded.rows[0].buyer_initiated_volume == "100.25"
    assert loaded.rows[0].source_bytes_sha256 == sha256_of_bytes(bundle.data_paths[0].read_bytes())
    assert loaded.preregistration_authorized is False
    assert loaded.signal_generation_authorized is False
    assert loaded.backtest_authorized is False
    assert loaded.pnl_evaluation_authorized is False
    assert loaded.holdout_access_authorized is False
    assert loaded.network_access_authorized is False
    assert loaded.real_money_authorized is False
    assert loaded.profitability_evidence is False


def test_signature_verifier_cannot_be_injected_and_direct_verified_result_is_rejected(
    tmp_path: Path,
) -> None:
    assert "verifier" not in inspect.signature(load_attested_ccdata_bundle).parameters
    loaded = _load(_build_bundle(tmp_path / "bundle"))
    with pytest.raises(CCDataAttestedLoaderError, match="only be constructed"):
        replace(loaded, _verification_token=object())


def test_tampered_provider_bytes_and_detached_signature_fail_closed(tmp_path: Path) -> None:
    first = _build_bundle(tmp_path / "raw-tamper")
    first.data_paths[0].write_bytes(first.data_paths[0].read_bytes() + b"tamper")
    with pytest.raises(CCDataAttestedLoaderError, match="byte length mismatch"):
        _load(first)

    second = _build_bundle(tmp_path / "signature-tamper")
    signature = second.root / "attestation.sig"
    signature.write_bytes(bytes([signature.read_bytes()[0] ^ 1]) + signature.read_bytes()[1:])
    with pytest.raises(CCDataAttestedLoaderError, match="signature is invalid"):
        _load(second)

    traversal = _build_bundle(tmp_path / "path-traversal")
    _resign_manifest(
        traversal,
        lambda manifest: manifest["derived_artifacts"]["normalized_observations"].update(
            {"path": "../outside-derived-bytes"}
        ),
    )
    with pytest.raises(CCDataAttestedLoaderError, match="contained POSIX path"):
        _load(traversal)


def test_self_bundled_key_and_untrusted_product_cannot_expand_trust(tmp_path: Path) -> None:
    bundle = _build_bundle(tmp_path / "bundle")
    attestation_path = bundle.root / "attestation.json"
    attestation = json.loads(attestation_path.read_bytes())
    attestation["verification_key"] = "self-asserted"
    raw = _canonical_bytes(attestation)
    attestation_path.write_bytes(raw)
    (bundle.root / "attestation.sig").write_bytes(bundle.private_key.sign(raw))
    with pytest.raises(CCDataAttestedLoaderError, match="wrong fields"):
        _load(bundle)

    other = replace(bundle.trust_root, allowed_provider_product_ids=("some-other-product",))
    with pytest.raises(CCDataAttestedLoaderError, match="outside the trust-root scope"):
        load_attested_ccdata_bundle(
            _build_bundle(tmp_path / "other").root,
            trust_root=other,
            parser=bundle.parser,
            knowledge_cutoff_utc=KNOWLEDGE,
            verification_at_utc=VERIFICATION,
        )


def test_license_entitlement_and_historical_revision_claims_are_explicit(tmp_path: Path) -> None:
    missing_use = _build_bundle(tmp_path / "missing-use")
    _resign_manifest(
        missing_use,
        lambda manifest: manifest["license"].update({"permitted_uses": ["COMMERCIAL_RESEARCH"]}),
    )
    with pytest.raises(CCDataAttestedLoaderError, match="explicit internal-use entitlement"):
        _load(missing_use)

    restated_only = _build_bundle(tmp_path / "restated-only")
    _resign_manifest(
        restated_only,
        lambda manifest: manifest["vintage_policy"].update(
            {"correction_log_includes_old_and_new_values": False}
        ),
    )
    with pytest.raises(CCDataAttestedLoaderError, match="pre- and post-revision"):
        _load(restated_only)


def test_parser_schema_version_and_normalized_projection_are_bound(tmp_path: Path) -> None:
    wrong_parser = _build_bundle(tmp_path / "wrong-parser")
    wrong_parser.parser.parser_version = "changed-after-review"
    with pytest.raises(CCDataAttestedLoaderError, match="parser_version"):
        _load(wrong_parser)

    changed_projection = _build_bundle(tmp_path / "changed-projection")
    normalized = changed_projection.root / "derived/observations.jsonl"
    row = json.loads(normalized.read_bytes())
    row["buyer_initiated_volume"] = "999.00"
    raw = _canonical_bytes(row)
    normalized.write_bytes(raw)

    def bind_changed_derived(manifest: dict[str, Any]) -> None:
        descriptor = manifest["derived_artifacts"]["normalized_observations"]
        descriptor["byte_length"] = len(raw)
        descriptor["sha256"] = sha256_of_bytes(raw)

    _resign_manifest(changed_projection, bind_changed_derived)
    with pytest.raises(CCDataAttestedLoaderError, match="not exactly re-derived"):
        _load(changed_projection)


def test_causal_projection_is_prefix_invariant_when_future_delivery_is_appended(
    tmp_path: Path,
) -> None:
    baseline = _load(_build_bundle(tmp_path / "baseline"))
    extended = _load(_build_bundle(tmp_path / "extended", include_future=True))

    assert extended.manifest_sha256 != baseline.manifest_sha256
    assert extended.source_receipt_chain_head_sha256 != baseline.source_receipt_chain_head_sha256
    assert extended.causal_source_receipts_sha256 == baseline.causal_source_receipts_sha256
    assert extended.causal_rows_sha256 == baseline.causal_rows_sha256
    assert tuple(row.to_dict() for row in extended.rows) == tuple(
        row.to_dict() for row in baseline.rows
    )


def test_revision_available_before_cutoff_replaces_only_its_prior_vintage(tmp_path: Path) -> None:
    loaded = _load(_build_bundle(tmp_path / "revision", include_revision=True))

    assert len(loaded.rows) == 1
    assert loaded.rows[0].buyer_initiated_volume == "101.25"
    assert loaded.rows[0].revision_sequence == 1
