"""Fee schedules as evidence: what may price a promotion, and what may not."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_trade.v9.cost_evidence import (
    COST_EVIDENCE_CLASSES,
    FEE_ENDPOINTS,
    PROMOTABLE_CLASSES,
    BundleSet,
    CostEvidenceBundle,
    CostEvidenceError,
    FeeSchedule,
    assumption_bundle,
    load_bundle,
    operator_capture_instructions,
    parse_bybit_fee_rate,
    parse_okx_trade_fee,
)

NOW = "2026-07-28T00:00:00Z"


def _schedule(**overrides) -> FeeSchedule:
    payload = {
        "venue": "bybit",
        "instrument": "BTCUSDT",
        "leg": "spot",
        "maker_bps": 2.0,
        "taker_bps": 6.0,
        "fee_tier": "VIP1",
        "currency": "USDT",
        "minimum_fee": 0.0,
        "effective_from_utc": "2026-01-01T00:00:00Z",
        "expires_at_utc": "2026-12-31T00:00:00Z",
        "source_url": FEE_ENDPOINTS["bybit"]["account_specific"],
        "raw_sha256": "a" * 64,
        "parser_version": "v9.1",
        "evidence_class": "REAL_ACCOUNT_SPECIFIC",
        "captured_at_utc": NOW,
    }
    payload.update(overrides)
    return FeeSchedule(**payload)


def _bundle(venue: str = "bybit", **overrides) -> CostEvidenceBundle:
    instrument = "BTCUSDT" if venue == "bybit" else "BTC-USDT"
    perp = "BTCUSDT" if venue == "bybit" else "BTC-USDT-SWAP"
    perp_overrides = {"taker_bps": 5.5, **overrides}
    return CostEvidenceBundle(
        venue=venue,
        captured_at_utc=NOW,
        schedules=(
            _schedule(venue=venue, instrument=instrument, leg="spot", **overrides),
            _schedule(venue=venue, instrument=perp, leg="perp", **perp_overrides),
        ),
    )


# --- evidence classes -----------------------------------------------------------------


def test_only_real_classes_can_promote() -> None:
    assert PROMOTABLE_CLASSES == ("REAL_PUBLIC_RETAIL", "REAL_ACCOUNT_SPECIFIC")
    assert _schedule(evidence_class="REAL_ACCOUNT_SPECIFIC").promotable
    assert _schedule(evidence_class="REAL_PUBLIC_RETAIL").promotable
    assert not _schedule(evidence_class="RECORDED_TEST", raw_sha256="").promotable
    assert not _schedule(evidence_class="ASSUMPTION", raw_sha256="").promotable


def test_a_real_class_without_raw_bytes_is_rejected() -> None:
    """A 'real' label with nothing behind it is an assumption in disguise."""
    with pytest.raises(CostEvidenceError, match="assumption wearing a better label"):
        _schedule(evidence_class="REAL_ACCOUNT_SPECIFIC", raw_sha256="")


def test_an_unknown_evidence_class_is_rejected() -> None:
    with pytest.raises(CostEvidenceError, match="evidence_class must be one of"):
        _schedule(evidence_class="PROBABLY_FINE")
    assert "ASSUMPTION" in COST_EVIDENCE_CLASSES


def test_a_schedule_needs_an_official_source() -> None:
    with pytest.raises(CostEvidenceError, match="official source URL"):
        _schedule(source_url="")


def test_negative_fees_are_rejected() -> None:
    with pytest.raises(CostEvidenceError, match="finite and >= 0"):
        _schedule(taker_bps=-1.0)


def test_an_expiry_before_the_effective_date_is_rejected() -> None:
    with pytest.raises(CostEvidenceError, match="must be after effective_from_utc"):
        _schedule(effective_from_utc="2026-06-01T00:00:00Z", expires_at_utc="2026-01-01T00:00:00Z")


# --- bundle validation ------------------------------------------------------------------


def test_a_verified_bundle_validates_clean() -> None:
    assert _bundle().validate(now_utc=NOW) == []
    assert _bundle().promotable


def test_an_assumed_bundle_cannot_promote() -> None:
    bundle = assumption_bundle("bybit", captured_at_utc=NOW)
    assert not bundle.promotable
    assert bundle.weakest_evidence_class == "ASSUMPTION"
    problems = bundle.validate(now_utc=NOW)
    assert any("cannot support a promotion" in p for p in problems)


def test_stale_evidence_blocks() -> None:
    bundle = _bundle(expires_at_utc="2026-02-01T00:00:00Z")
    problems = bundle.validate(now_utc=NOW)
    assert any("expired at" in p for p in problems)


def test_evidence_that_is_not_yet_effective_blocks() -> None:
    bundle = _bundle(
        effective_from_utc="2027-01-01T00:00:00Z", expires_at_utc="2028-01-01T00:00:00Z"
    )
    problems = bundle.validate(now_utc=NOW)
    assert any("not yet effective" in p for p in problems)


def test_a_missing_leg_blocks() -> None:
    bundle = CostEvidenceBundle(
        venue="bybit", captured_at_utc=NOW, schedules=(_schedule(leg="spot"),)
    )
    problems = bundle.validate(now_utc=NOW)
    assert any("no perp fee schedule" in p for p in problems)


def test_a_bundle_cannot_carry_another_venues_schedule() -> None:
    """The exact V8 bug: Bybit's fees charged on the OKX leg."""
    with pytest.raises(CostEvidenceError, match="may never price another venue"):
        CostEvidenceBundle(
            venue="okx",
            captured_at_utc=NOW,
            schedules=(_schedule(venue="bybit"),),
        )


def test_the_bundle_hash_changes_with_any_rate() -> None:
    assert _bundle().bundle_sha256 != _bundle(taker_bps=9.9).bundle_sha256


def test_taker_lookup_is_per_leg() -> None:
    bundle = _bundle()
    assert bundle.taker_bps("spot") == 6.0
    assert bundle.taker_bps("perp") == 5.5
    with pytest.raises(CostEvidenceError, match="has no .* schedule"):
        bundle.schedule("futures")


# --- bundle sets (H3 needs two) ------------------------------------------------------------


def test_a_cross_venue_campaign_needs_two_independent_bundles() -> None:
    both = BundleSet()
    both.add(_bundle("bybit"))
    both.add(_bundle("okx"))
    assert both.require(("bybit", "okx"), now_utc=NOW) == []
    assert both.promotable


def test_a_missing_venue_bundle_blocks() -> None:
    only_one = BundleSet()
    only_one.add(_bundle("bybit"))
    problems = only_one.require(("bybit", "okx"), now_utc=NOW)
    assert any("no cost evidence bundle for okx" in p for p in problems)


def test_two_venues_sharing_one_schedule_are_detected() -> None:
    shared = BundleSet()
    bundle = _bundle("bybit")
    shared.bundles["bybit"] = bundle
    shared.bundles["okx"] = bundle  # the same object under both names
    problems = shared.require(("bybit", "okx"), now_utc=NOW)
    assert any("share one cost bundle" in p for p in problems)


def test_one_assumed_venue_taints_the_set() -> None:
    mixed = BundleSet()
    mixed.add(_bundle("bybit"))
    mixed.add(assumption_bundle("okx", captured_at_utc=NOW))
    assert not mixed.promotable
    assert mixed.require(("bybit", "okx"), now_utc=NOW)


# --- parsers -------------------------------------------------------------------------------


def test_bybit_fee_rates_are_converted_to_basis_points() -> None:
    raw = json.dumps(
        {
            "retCode": 0,
            "time": 1700000000000,
            "result": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "category": "linear",
                        "makerFeeRate": "0.0002",
                        "takerFeeRate": "0.00055",
                        "feeTier": "VIP1",
                    }
                ]
            },
        }
    ).encode()
    schedules = parse_bybit_fee_rate(
        raw,
        instrument="BTCUSDT",
        captured_at_utc=NOW,
        effective_from_utc="2026-01-01T00:00:00Z",
        expires_at_utc="2026-12-31T00:00:00Z",
    )
    assert len(schedules) == 1
    assert schedules[0].taker_bps == pytest.approx(5.5)
    assert schedules[0].maker_bps == pytest.approx(2.0)
    assert schedules[0].leg == "perp"
    assert schedules[0].raw_sha256


def test_okx_negative_fee_signs_are_normalised() -> None:
    """OKX reports charges as negative; a rebate must never read as a cost."""
    raw = json.dumps(
        {
            "code": "0",
            "data": [
                {"maker": "-0.0002", "taker": "-0.0005", "level": "Lv1", "ts": "1700000000000"}
            ],
        }
    ).encode()
    schedules = parse_okx_trade_fee(
        raw,
        instrument="BTC-USDT-SWAP",
        leg="perp",
        captured_at_utc=NOW,
        effective_from_utc="2026-01-01T00:00:00Z",
        expires_at_utc="2026-12-31T00:00:00Z",
    )
    assert schedules[0].taker_bps == pytest.approx(5.0)
    assert schedules[0].maker_bps == pytest.approx(2.0)


def test_an_okx_rebate_does_not_become_a_negative_cost() -> None:
    raw = json.dumps(
        {"code": "0", "data": [{"maker": "0.0001", "taker": "-0.0005", "level": "Lv5"}]}
    ).encode()
    schedules = parse_okx_trade_fee(
        raw,
        instrument="BTC-USDT-SWAP",
        leg="perp",
        captured_at_utc=NOW,
        effective_from_utc="2026-01-01T00:00:00Z",
        expires_at_utc="2026-12-31T00:00:00Z",
    )
    assert schedules[0].maker_bps == 0.0  # a rebate is floored, never income


def test_a_venue_error_envelope_is_not_parsed_as_zero_fees() -> None:
    with pytest.raises(CostEvidenceError, match="bybit fee-rate error"):
        parse_bybit_fee_rate(
            b'{"retCode":10003,"retMsg":"invalid api key"}',
            instrument="BTCUSDT",
            captured_at_utc=NOW,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2026-12-31T00:00:00Z",
        )
    with pytest.raises(CostEvidenceError, match="okx trade-fee error"):
        parse_okx_trade_fee(
            b'{"code":"50111","msg":"invalid"}',
            instrument="BTC-USDT-SWAP",
            leg="perp",
            captured_at_utc=NOW,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2026-12-31T00:00:00Z",
        )


def test_a_response_for_the_wrong_instrument_is_rejected() -> None:
    raw = json.dumps(
        {
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "symbol": "ETHUSDT",
                        "category": "linear",
                        "makerFeeRate": "0.0002",
                        "takerFeeRate": "0.00055",
                    }
                ]
            },
        }
    ).encode()
    with pytest.raises(CostEvidenceError, match="carries no row for 'BTCUSDT'"):
        parse_bybit_fee_rate(
            raw,
            instrument="BTCUSDT",
            captured_at_utc=NOW,
            effective_from_utc="2026-01-01T00:00:00Z",
            expires_at_utc="2026-12-31T00:00:00Z",
        )


# --- round trip ---------------------------------------------------------------------------


def test_a_bundle_round_trips_through_disk(tmp_path: Path) -> None:
    bundle = _bundle()
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(bundle.to_dict()), encoding="utf-8")
    reloaded = load_bundle(path)
    assert reloaded.bundle_sha256 == bundle.bundle_sha256
    assert reloaded.promotable


# --- credential safety ----------------------------------------------------------------------


def test_the_operator_instructions_never_ask_for_a_secret() -> None:
    for venue in ("bybit", "okx"):
        instructions = operator_capture_instructions(venue)
        assert "read-only" in instructions["permissions_required"]
        assert "NO withdraw" in instructions["permissions_required"]
        assert "API secret" in instructions["never_send"]
        assert "seed phrase" in instructions["never_send"]
        assert instructions["what_to_send_back"] == "the raw response bytes only"


def test_the_module_contains_no_signing_code_or_credential_lookup() -> None:
    """Naming a secret in a "never send this" list is fine; USING one is not."""
    source = Path("src/quant_trade/v9/cost_evidence.py").read_text(encoding="utf-8")
    lowered = source.lower()
    for banned in (
        "import hmac",
        "hmac.new",
        "hashlib.sha256(secret",
        "os.environ",
        "getenv",
        "authorization",
        "x-bapi-sign",
        "ok-access-key",
    ):
        assert banned not in lowered, banned
