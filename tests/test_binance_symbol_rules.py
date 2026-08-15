from __future__ import annotations

import dataclasses
import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from quant_trade.data.binance_symbol_rules import (
    BINANCE_EXCHANGE_INFO_ENDPOINT,
    BINANCE_MAX_CAPTURE_SERVER_SKEW_SECONDS,
    BINANCE_SYMBOL_RULES_ADAPTER,
    BINANCE_SYMBOL_RULES_ADAPTER_VERSION,
    BINANCE_SYMBOL_RULES_SCHEMA_VERSION,
    BinanceSpotSymbolRulesLedger,
    BinanceSymbolRulesError,
    SymbolRuleAvailability,
    SymbolRuleLookup,
    load_binance_spot_symbol_rules_ledger,
    normalize_binance_spot_symbol_rules,
)
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes
from quant_trade.evidence.receipts import (
    IngestionReceipt,
    append_receipt,
    normalized_rows_sha256,
)


def _rule_filters(
    *,
    min_notional: str = "5.00000000",
    include_min_notional: bool = True,
    include_notional: bool = False,
    market_min: str = "0.00000000",
    market_max: str = "1000.00000000",
    market_step: str = "0.00000000",
) -> list[dict[str, Any]]:
    filters: list[dict[str, Any]] = [
        {
            "filterType": "PRICE_FILTER",
            "minPrice": "0.00010000",
            "maxPrice": "100000.00000000",
            "tickSize": "0.01000000",
        },
        {
            "filterType": "LOT_SIZE",
            "minQty": "0.10000000",
            "maxQty": "10000.00000000",
            "stepSize": "0.10000000",
        },
        {
            "filterType": "MARKET_LOT_SIZE",
            "minQty": market_min,
            "maxQty": market_max,
            "stepSize": market_step,
        },
    ]
    if include_min_notional:
        filters.append(
            {
                "filterType": "MIN_NOTIONAL",
                "minNotional": min_notional,
                "applyToMarket": True,
                "avgPriceMins": 5,
            }
        )
    if include_notional:
        filters.append(
            {
                "filterType": "NOTIONAL",
                "minNotional": "7.50000000",
                "applyMinToMarket": False,
                "maxNotional": "25000.00000000",
                "applyMaxToMarket": True,
                "avgPriceMins": 3,
            }
        )
    return filters


def _symbol(
    base: str = "ABC",
    *,
    status: str = "TRADING",
    spot: bool = True,
    filters: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "symbol": f"{base}USDT",
        "baseAsset": base,
        "quoteAsset": "USDT",
        "status": status,
        "isSpotTradingAllowed": spot,
        "filters": filters if filters is not None else _rule_filters(),
    }


def _payload(
    symbols: list[dict[str, Any]] | None = None,
    *,
    server_time: str = "2026-08-13T00:00:00Z",
) -> bytes:
    server_ms = int(datetime.fromisoformat(server_time.replace("Z", "+00:00")).timestamp() * 1_000)
    return json.dumps(
        {
            "timezone": "UTC",
            "serverTime": server_ms,
            "rateLimits": [],
            "exchangeFilters": [],
            "symbols": symbols if symbols is not None else [_symbol()],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _append_snapshot(
    root: Path,
    *,
    raw: bytes | None = None,
    captured_at: str = "2026-08-13T00:00:05Z",
    source_kind: str = "fixture",
    receipt_overrides: dict[str, Any] | None = None,
) -> Path:
    body = raw if raw is not None else _payload()
    digest = sha256_of_bytes(body)
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{digest}.json"
    raw_path.write_bytes(body)
    values: dict[str, Any] = {
        "provider_or_venue": "binance",
        "endpoint": BINANCE_EXCHANGE_INFO_ENDPOINT,
        "request_parameters": {},
        "http_status": 200,
        "captured_at_utc": captured_at,
        "adapter_name": BINANCE_SYMBOL_RULES_ADAPTER,
        "adapter_version": BINANCE_SYMBOL_RULES_ADAPTER_VERSION,
        "raw_path": f"raw/{digest}.json",
        "raw_sha256": digest,
        "normalized_rows_sha256": normalized_rows_sha256(normalize_binance_spot_symbol_rules(body)),
        "source_kind": source_kind,
        "server_timestamp_utc": "",
    }
    values.update(receipt_overrides or {})
    receipts = root / "receipts.jsonl"
    append_receipt(receipts, IngestionReceipt(**values))
    return receipts


def test_v2_preserves_complete_notional_and_market_filters(tmp_path: Path) -> None:
    filters = _rule_filters(
        include_notional=True,
        market_min="0",
        market_max="1234.50000000",
        market_step="0",
    )
    receipts = _append_snapshot(tmp_path, raw=_payload([_symbol(filters=filters)]))

    ledger = load_binance_spot_symbol_rules_ledger(receipts)
    snapshot = ledger.snapshots[0]
    rule = snapshot.rules[0]

    assert ledger.schema_version == BINANCE_SYMBOL_RULES_SCHEMA_VERSION == 2
    assert BINANCE_SYMBOL_RULES_ADAPTER_VERSION == "2"
    assert rule.venue_symbol == "ABCUSDT"
    assert rule.quote_asset == "USDT"
    assert rule.tick_size == "0.01" and rule.tick_size_enabled
    assert rule.quantity_step == "0.1"
    assert rule.min_quantity == "0.1"
    assert rule.max_quantity == "10000"
    assert rule.market_min_quantity == "0"
    assert not rule.market_min_quantity_enabled
    assert rule.market_max_quantity == "1234.5"
    assert rule.market_max_quantity_enabled
    assert rule.market_quantity_step == "0"
    assert not rule.market_quantity_step_enabled
    assert rule.min_notional_quote == "5"
    assert rule.min_notional_apply_to_market is True
    assert rule.min_notional_avg_price_mins == 5
    assert rule.notional_min_quote == "7.5"
    assert rule.notional_apply_min_to_market is False
    assert rule.notional_max_quote == "25000"
    assert rule.notional_apply_max_to_market is True
    assert rule.notional_avg_price_mins == 3
    assert not hasattr(rule, "min_notional_usd")
    assert rule.receipt_declared_source_kind == "fixture"
    assert rule.source_raw_sha256 == snapshot.source_raw_sha256
    assert hashlib.sha256(canonical_dumps(ledger.sealed_content()).encode()).hexdigest() == (
        ledger.digest()
    )


def test_live_self_label_is_unattested_and_never_exposes_usable_rule(tmp_path: Path) -> None:
    receipts = _append_snapshot(tmp_path, source_kind="live")
    ledger = load_binance_spot_symbol_rules_ledger(receipts)

    result = ledger.lookup(
        "ABCUSDT",
        as_of_utc="2026-08-13T00:30:05Z",
        max_age=timedelta(hours=1),
    )

    assert ledger.attestation_status == "UNAVAILABLE"
    assert result.availability is SymbolRuleAvailability.UNATTESTED_SOURCE
    assert not result.available
    assert result.rule is None
    assert not result.real_money_authorized
    assert not result.pnl_evaluation_authorized
    assert not result.network_access_authorized


def test_available_real_cannot_be_fabricated_through_public_constructor() -> None:
    with pytest.raises(BinanceSymbolRulesError, match="external attestation"):
        SymbolRuleLookup(
            availability=SymbolRuleAvailability.AVAILABLE_REAL,
            venue_symbol="ABCUSDT",
            as_of_utc="2026-08-13T00:00:00Z",
        )
    with pytest.raises(BinanceSymbolRulesError, match="cannot claim external attestation"):
        BinanceSpotSymbolRulesLedger(snapshots=(), attestation_status="VERIFIED")


def test_direct_snapshot_copy_cannot_upgrade_to_available(tmp_path: Path) -> None:
    receipts = _append_snapshot(tmp_path, source_kind="live")
    loaded = load_binance_spot_symbol_rules_ledger(receipts)
    copied = BinanceSpotSymbolRulesLedger(snapshots=(dataclasses.replace(loaded.snapshots[0]),))
    result = copied.lookup(
        "ABCUSDT",
        as_of_utc="2026-08-13T00:00:06Z",
        max_age=timedelta(days=1),
    )
    assert result.availability is SymbolRuleAvailability.UNATTESTED_SOURCE
    assert result.rule is None


def test_snapshot_is_never_projected_before_its_capture_time(tmp_path: Path) -> None:
    receipts = _append_snapshot(tmp_path, source_kind="live")
    result = load_binance_spot_symbol_rules_ledger(receipts).lookup(
        "ABCUSDT",
        as_of_utc="2026-08-13T00:00:04Z",
        max_age=timedelta(days=1),
    )
    assert result.availability is SymbolRuleAvailability.NOT_YET_OBSERVED
    assert result.rule is None


def test_lookup_requires_explicit_freshness_and_fails_stale(tmp_path: Path) -> None:
    receipts = _append_snapshot(tmp_path, source_kind="live")
    ledger = load_binance_spot_symbol_rules_ledger(receipts)
    stale = ledger.lookup(
        "ABCUSDT",
        as_of_utc="2026-08-13T01:00:06Z",
        max_age=timedelta(hours=1),
    )
    assert stale.availability is SymbolRuleAvailability.STALE_SNAPSHOT
    assert stale.rule is None
    with pytest.raises(BinanceSymbolRulesError, match="positive timedelta"):
        ledger.lookup(
            "ABCUSDT",
            as_of_utc="2026-08-13T00:00:05Z",
            max_age=timedelta(0),
        )


def test_fixture_receipt_remains_test_only(tmp_path: Path) -> None:
    receipts = _append_snapshot(tmp_path, source_kind="fixture")
    result = load_binance_spot_symbol_rules_ledger(receipts).lookup(
        "ABCUSDT",
        as_of_utc="2026-08-13T00:00:06Z",
        max_age=timedelta(days=1),
    )
    assert result.availability is SymbolRuleAvailability.TEST_ONLY_PROVENANCE
    assert result.rule is None


def test_spot_disabled_row_is_preserved_and_blocks(tmp_path: Path) -> None:
    receipts = _append_snapshot(
        tmp_path,
        raw=_payload([_symbol(spot=False)]),
        source_kind="live",
    )
    ledger = load_binance_spot_symbol_rules_ledger(receipts)
    assert ledger.snapshots[0].rules[0].spot_trading_allowed is False
    result = ledger.lookup(
        "ABCUSDT",
        as_of_utc="2026-08-13T00:00:06Z",
        max_age=timedelta(days=1),
    )
    assert result.availability is SymbolRuleAvailability.SPOT_TRADING_DISABLED


def test_latest_full_snapshot_absence_blocks_without_old_rule_fallback(tmp_path: Path) -> None:
    receipts = _append_snapshot(tmp_path, source_kind="live")
    _append_snapshot(
        tmp_path,
        raw=_payload([_symbol("XYZ")], server_time="2026-08-13T01:00:00Z"),
        captured_at="2026-08-13T01:00:05Z",
        source_kind="live",
    )
    result = load_binance_spot_symbol_rules_ledger(receipts).lookup(
        "ABCUSDT",
        as_of_utc="2026-08-13T01:00:06Z",
        max_age=timedelta(days=1),
    )
    assert result.availability is SymbolRuleAvailability.SYMBOL_ABSENT_FROM_LATEST_SNAPSHOT
    assert result.rule is None


def test_non_trading_status_blocks_rule_use(tmp_path: Path) -> None:
    receipts = _append_snapshot(
        tmp_path,
        raw=_payload([_symbol(status="BREAK")]),
        source_kind="live",
    )
    result = load_binance_spot_symbol_rules_ledger(receipts).lookup(
        "ABCUSDT",
        as_of_utc="2026-08-13T00:00:06Z",
        max_age=timedelta(days=1),
    )
    assert result.availability is SymbolRuleAvailability.SYMBOL_NOT_TRADING
    assert result.rule is None


def test_future_append_cannot_change_prior_prefix_or_lookup(tmp_path: Path) -> None:
    receipts = _append_snapshot(tmp_path, source_kind="live")
    first = load_binance_spot_symbol_rules_ledger(receipts)
    cutoff = "2026-08-13T00:30:00Z"
    prefix = first.prefix_bytes(cutoff)
    lookup = first.lookup("ABCUSDT", as_of_utc=cutoff, max_age=timedelta(days=1))
    _append_snapshot(
        tmp_path,
        raw=_payload(
            [_symbol(filters=_rule_filters(min_notional="9"))],
            server_time="2026-08-13T01:00:00Z",
        ),
        captured_at="2026-08-13T01:00:05Z",
        source_kind="live",
    )
    extended = load_binance_spot_symbol_rules_ledger(receipts)
    assert extended.prefix_bytes(cutoff) == prefix
    assert extended.lookup("ABCUSDT", as_of_utc=cutoff, max_age=timedelta(days=1)) == lookup


def test_raw_byte_tamper_and_receipt_chain_tamper_fail_closed(tmp_path: Path) -> None:
    receipts = _append_snapshot(tmp_path)
    raw_path = next((tmp_path / "raw").iterdir())
    original = raw_path.read_bytes()
    raw_path.write_bytes(original + b" ")
    with pytest.raises(BinanceSymbolRulesError, match="raw source bytes"):
        load_binance_spot_symbol_rules_ledger(receipts)
    raw_path.write_bytes(original)
    record = json.loads(receipts.read_text(encoding="utf-8"))
    record["captured_at_utc"] = "2026-08-13T00:00:06Z"
    receipts.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(BinanceSymbolRulesError, match="receipt chain is invalid"):
        load_binance_spot_symbol_rules_ledger(receipts)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"endpoint": "https://example.invalid/api/v3/exchangeInfo"}, "endpoint"),
        ({"request_parameters": {"symbol": "ABCUSDT"}}, "full-universe"),
        ({"http_status": 500}, "http_status"),
        ({"http_status": 200.0}, "http_status"),
        ({"adapter_version": "1"}, "adapter_version"),
        ({"schema_version": 1.0}, "schema_version"),
        ({"normalized_rows_sha256": "0" * 64}, "normalized symbol rules"),
    ],
)
def test_wrong_receipt_contract_fails_closed(
    tmp_path: Path, overrides: dict[str, Any], match: str
) -> None:
    receipts = _append_snapshot(tmp_path, receipt_overrides=overrides)
    with pytest.raises(BinanceSymbolRulesError, match=match):
        load_binance_spot_symbol_rules_ledger(receipts)


@pytest.mark.parametrize(
    "captured_at",
    ["2026-08-13T00:00:05", "2026-08-12T18:00:05-06:00"],
)
def test_receipt_observation_time_must_be_explicit_utc(tmp_path: Path, captured_at: str) -> None:
    receipts = _append_snapshot(tmp_path, captured_at=captured_at)
    with pytest.raises(BinanceSymbolRulesError, match="explicit UTC"):
        load_binance_spot_symbol_rules_ledger(receipts)


def test_capture_cannot_precede_or_lag_server_beyond_sealed_skew(tmp_path: Path) -> None:
    receipts = _append_snapshot(tmp_path, captured_at="2026-08-12T23:59:59Z")
    with pytest.raises(BinanceSymbolRulesError, match="cannot precede"):
        load_binance_spot_symbol_rules_ledger(receipts)

    delayed = tmp_path / "delayed"
    receipts = _append_snapshot(delayed, captured_at="2026-08-13T00:05:01Z")
    assert BINANCE_MAX_CAPTURE_SERVER_SKEW_SECONDS == 300
    with pytest.raises(BinanceSymbolRulesError, match="skew exceeds"):
        load_binance_spot_symbol_rules_ledger(receipts)


def test_server_time_must_strictly_increase_even_when_capture_time_does(tmp_path: Path) -> None:
    receipts = _append_snapshot(
        tmp_path,
        raw=_payload(server_time="2026-08-13T01:00:00Z"),
        captured_at="2026-08-13T01:00:05Z",
    )
    _append_snapshot(
        tmp_path,
        raw=_payload(
            [_symbol(filters=_rule_filters(min_notional="6"))],
            server_time="2026-08-13T00:59:59Z",
        ),
        captured_at="2026-08-13T01:01:05Z",
    )
    with pytest.raises(BinanceSymbolRulesError, match="server_time_utc.*strictly increasing"):
        load_binance_spot_symbol_rules_ledger(receipts)


def test_receipt_capture_order_cannot_move_backwards(tmp_path: Path) -> None:
    receipts = _append_snapshot(
        tmp_path,
        raw=_payload(server_time="2026-08-13T02:00:00Z"),
        captured_at="2026-08-13T02:00:05Z",
    )
    _append_snapshot(
        tmp_path,
        raw=_payload(
            [_symbol(filters=_rule_filters(min_notional="6"))],
            server_time="2026-08-13T01:00:00Z",
        ),
        captured_at="2026-08-13T01:00:05Z",
    )
    with pytest.raises(BinanceSymbolRulesError, match="strictly increasing"):
        load_binance_spot_symbol_rules_ledger(receipts)


def test_market_lot_zero_is_preserved_as_disabled_not_positive() -> None:
    rows = normalize_binance_spot_symbol_rules(
        _payload(
            [
                _symbol(
                    filters=_rule_filters(
                        market_min="0.00000000",
                        market_max="0.00000000",
                        market_step="0.00000000",
                    )
                )
            ]
        )
    )
    row = rows[0]
    assert row["market_min_quantity"] == "0"
    assert row["market_max_quantity"] == "0"
    assert row["market_quantity_step"] == "0"
    assert row["market_min_quantity_enabled"] is False
    assert row["market_max_quantity_enabled"] is False
    assert row["market_quantity_step_enabled"] is False


def test_negative_zero_does_not_masquerade_as_a_disabled_filter() -> None:
    symbol = _symbol()
    _update_filter(symbol, "MARKET_LOT_SIZE", {"stepSize": "-0.00000000"})
    with pytest.raises(BinanceSymbolRulesError, match="non-negative decimal string"):
        normalize_binance_spot_symbol_rules(_payload([symbol]))


def test_notional_only_filter_is_complete_and_preserved() -> None:
    row = normalize_binance_spot_symbol_rules(
        _payload(
            [
                _symbol(
                    filters=_rule_filters(
                        include_min_notional=False,
                        include_notional=True,
                    )
                )
            ]
        )
    )[0]
    assert row["min_notional_quote"] is None
    assert row["notional_min_quote"] == "7.5"
    assert row["notional_max_quote"] == "25000"


def _drop_filter(symbol: dict[str, Any], filter_type: str) -> None:
    symbol["filters"] = [
        item for item in symbol["filters"] if item.get("filterType") != filter_type
    ]


def _update_filter(symbol: dict[str, Any], filter_type: str, values: dict[str, Any]) -> None:
    next(item for item in symbol["filters"] if item.get("filterType") == filter_type).update(values)


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda symbol: symbol["filters"].append(dict(symbol["filters"][0])),
            "duplicate PRICE_FILTER",
        ),
        (lambda symbol: _drop_filter(symbol, "LOT_SIZE"), "requires PRICE_FILTER"),
        (lambda symbol: _drop_filter(symbol, "MARKET_LOT_SIZE"), "MARKET_LOT_SIZE"),
        (
            lambda symbol: _update_filter(symbol, "LOT_SIZE", {"stepSize": "0"}),
            "positive decimal string",
        ),
        (
            lambda symbol: symbol.update({"isSpotTradingAllowed": "true"}),
            "explicit boolean",
        ),
        (
            lambda symbol: _update_filter(symbol, "MARKET_LOT_SIZE", {"stepSize": -1.0}),
            "non-negative decimal string",
        ),
        (
            lambda symbol: _update_filter(symbol, "MIN_NOTIONAL", {"applyToMarket": 1}),
            "explicit boolean",
        ),
        (
            lambda symbol: _update_filter(symbol, "MIN_NOTIONAL", {"avgPriceMins": True}),
            "non-negative integer",
        ),
        (
            lambda symbol: _drop_filter(symbol, "MIN_NOTIONAL"),
            "requires MIN_NOTIONAL or NOTIONAL",
        ),
    ],
)
def test_ambiguous_or_incomplete_exchange_rules_are_rejected(
    mutator: Callable[[dict[str, Any]], None], match: str
) -> None:
    symbol = _symbol()
    mutator(symbol)
    with pytest.raises(BinanceSymbolRulesError, match=match):
        normalize_binance_spot_symbol_rules(_payload([symbol]))


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("maxNotional", None, "positive decimal string"),
        ("maxNotional", "7", "smaller than minNotional"),
        ("applyMinToMarket", "false", "explicit boolean"),
        ("applyMaxToMarket", 0, "explicit boolean"),
        ("avgPriceMins", -1, "non-negative integer"),
    ],
)
def test_notional_max_flags_and_window_are_mandatory(field: str, value: Any, match: str) -> None:
    symbol = _symbol(filters=_rule_filters(include_min_notional=False, include_notional=True))
    _update_filter(symbol, "NOTIONAL", {field: value})
    with pytest.raises(BinanceSymbolRulesError, match=match):
        normalize_binance_spot_symbol_rules(_payload([symbol]))


def test_tick_zero_is_recorded_as_disabled() -> None:
    symbol = _symbol()
    _update_filter(symbol, "PRICE_FILTER", {"tickSize": "0.00000000"})
    row = normalize_binance_spot_symbol_rules(_payload([symbol]))[0]
    assert row["tick_size"] == "0"
    assert row["tick_size_enabled"] is False


def test_duplicate_venue_symbol_is_rejected() -> None:
    with pytest.raises(BinanceSymbolRulesError, match="duplicate venue_symbol"):
        normalize_binance_spot_symbol_rules(_payload([_symbol(), _symbol()]))


def test_public_lookup_constructor_rejects_status_rule_and_authorization(
    tmp_path: Path,
) -> None:
    arbitrary_status: Any = "PASS"
    with pytest.raises(BinanceSymbolRulesError, match="closed SymbolRuleAvailability"):
        SymbolRuleLookup(
            availability=arbitrary_status,
            venue_symbol="ABCUSDT",
            as_of_utc="2026-08-13T00:00:00Z",
        )
    rule = load_binance_spot_symbol_rules_ledger(_append_snapshot(tmp_path)).snapshots[0].rules[0]
    with pytest.raises(BinanceSymbolRulesError, match="must not expose"):
        SymbolRuleLookup(
            availability=SymbolRuleAvailability.UNATTESTED_SOURCE,
            venue_symbol="ABCUSDT",
            as_of_utc="2026-08-13T00:00:05Z",
            snapshot_observed_at_utc="2026-08-13T00:00:05Z",
            rule=rule,
        )
    with pytest.raises(TypeError, match="unexpected keyword"):
        SymbolRuleLookup(
            availability=SymbolRuleAvailability.NOT_YET_OBSERVED,
            venue_symbol="ABCUSDT",
            as_of_utc="2026-08-13T00:00:00Z",
            real_money_authorized=True,  # type: ignore[call-arg]
        )


def test_lookup_rejects_naive_or_non_utc_as_of(tmp_path: Path) -> None:
    ledger = load_binance_spot_symbol_rules_ledger(_append_snapshot(tmp_path, source_kind="live"))
    for invalid in ("2026-08-13T00:00:06", "2026-08-12T18:00:06-06:00"):
        with pytest.raises(BinanceSymbolRulesError, match="explicit UTC"):
            ledger.lookup("ABCUSDT", as_of_utc=invalid, max_age=timedelta(days=1))


def test_lookup_binds_exact_symbol_cutoff_and_selected_snapshot(tmp_path: Path) -> None:
    ledger = load_binance_spot_symbol_rules_ledger(_append_snapshot(tmp_path, source_kind="live"))
    result = ledger.lookup(
        "ABCUSDT",
        as_of_utc="2026-08-13T00:00:06+00:00",
        max_age=timedelta(days=1),
    )
    assert result.venue_symbol == "ABCUSDT"
    assert result.as_of_utc == "2026-08-13T00:00:06Z"
    assert result.snapshot_observed_at_utc == "2026-08-13T00:00:05Z"
    with pytest.raises(BinanceSymbolRulesError, match="canonical upper-case"):
        ledger.lookup(
            "abcusdt",
            as_of_utc="2026-08-13T00:00:06Z",
            max_age=timedelta(days=1),
        )


def test_replayed_raw_bytes_are_not_a_new_observation(tmp_path: Path) -> None:
    raw = _payload()
    receipts = _append_snapshot(tmp_path, raw=raw)
    _append_snapshot(tmp_path, raw=raw, captured_at="2026-08-13T00:01:05Z")
    with pytest.raises(BinanceSymbolRulesError, match="replayed source bytes"):
        load_binance_spot_symbol_rules_ledger(receipts)


def test_server_timestamp_receipt_must_match_raw_payload(tmp_path: Path) -> None:
    receipts = _append_snapshot(
        tmp_path,
        receipt_overrides={"server_timestamp_utc": "2026-08-13T00:00:01Z"},
    )
    with pytest.raises(BinanceSymbolRulesError, match="disagrees"):
        load_binance_spot_symbol_rules_ledger(receipts)


def test_source_sha_is_exact_hash_of_bytes() -> None:
    raw = _payload()
    rows = normalize_binance_spot_symbol_rules(raw)
    assert rows[0]["venue_symbol"] == "ABCUSDT"
    assert sha256_of_bytes(raw) == hashlib.sha256(raw).hexdigest()
