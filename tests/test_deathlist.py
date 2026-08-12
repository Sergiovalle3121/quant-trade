"""Tests for the external death list: coin counts vs symbol counts, unknown
flags, ambiguous tickers, network/parse failure modes. Fixtures only."""

from __future__ import annotations

import json

import pytest

from quant_trade.data.deathlist import (
    DEATHLIST_FILENAME,
    collect_death_list,
    load_inactive_symbols,
    parse_coin_roster,
)


def _roster_bytes(entries: list[dict[str, object]]) -> bytes:
    return json.dumps(entries).encode()


def _fetcher(payload: bytes):
    def fetch(url: str) -> bytes:
        return payload

    return fetch


def test_parse_separates_coin_counts_from_symbol_counts() -> None:
    # Three dead coins share two tickers: the coin count and the symbol count
    # must not be the same number.
    raw = _roster_bytes(
        [
            {"id": "a", "symbol": "GONE", "is_active": False},
            {"id": "b", "symbol": "GONE", "is_active": False},
            {"id": "c", "symbol": "DEAD", "is_active": False},
            {"id": "d", "symbol": "LIVE", "is_active": True},
        ]
    )
    inactive, active, counts, warnings = parse_coin_roster(raw)
    assert inactive == ["DEAD", "GONE"]
    assert active == ["LIVE"]
    assert counts.total_coins == 4
    assert counts.inactive_coins == 3
    assert counts.active_coins == 1
    assert len(inactive) == 2 != counts.inactive_coins
    assert warnings == []


def test_unknown_activity_flag_is_excluded_not_guessed() -> None:
    raw = _roster_bytes(
        [
            {"id": "a", "symbol": "MAYBE"},
            {"id": "b", "symbol": "MAYBE2", "is_active": None},
            {"id": "c", "symbol": "DEAD", "is_active": False},
        ]
    )
    inactive, active, counts, warnings = parse_coin_roster(raw)
    assert inactive == ["DEAD"]
    assert active == []
    assert counts.unknown_flag_coins == 2
    assert any("is_active" in w for w in warnings)


def test_empty_or_non_list_payload_is_rejected() -> None:
    with pytest.raises(ValueError):
        parse_coin_roster(b"[]")
    with pytest.raises(ValueError):
        parse_coin_roster(b'{"data": []}')


def test_collect_records_ambiguous_tickers(tmp_path) -> None:
    raw = _roster_bytes(
        [
            {"id": "a", "symbol": "TWIN", "is_active": False},
            {"id": "b", "symbol": "TWIN", "is_active": True},
            {"id": "c", "symbol": "DEAD", "is_active": False},
        ]
    )
    result = collect_death_list(tmp_path, fetcher=_fetcher(raw))
    assert result.status == "OK"
    assert result.ambiguous_symbols == 1
    assert any("both a dead and a live coin" in w for w in result.warnings)
    payload = json.loads((tmp_path / DEATHLIST_FILENAME).read_text(encoding="utf-8"))
    assert payload["ambiguous_symbols"] == ["TWIN"]


def test_fixture_list_can_never_corroborate_real_deaths(tmp_path) -> None:
    raw = _roster_bytes([{"id": "a", "symbol": "DEAD", "is_active": False}])
    result = collect_death_list(tmp_path, fetcher=_fetcher(raw))
    assert result.provenance == "test_only"
    with pytest.raises(ValueError, match="fixture"):
        load_inactive_symbols(tmp_path)


def test_missing_list_raises_rather_than_reporting_no_deaths(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="NOT_MEASURED"):
        load_inactive_symbols(tmp_path)


def test_network_failure_records_verbatim_error_and_writes_nothing(tmp_path) -> None:
    def boom(url: str) -> bytes:
        raise OSError("egress blocked by policy")

    result = collect_death_list(tmp_path, fetcher=boom)
    assert result.status == "NOT_RUN_NETWORK_BLOCKED"
    assert "egress blocked by policy" in result.error
    assert result.inactive_coins == 0
    assert not (tmp_path / DEATHLIST_FILENAME).exists()


def test_parse_failure_is_distinct_from_network_failure(tmp_path) -> None:
    result = collect_death_list(tmp_path, fetcher=_fetcher(b"not json at all"))
    assert result.status == "NOT_RUN_PARSE_REJECTED"
    assert not (tmp_path / DEATHLIST_FILENAME).exists()


def test_receipt_is_written_for_the_raw_page(tmp_path) -> None:
    raw = _roster_bytes([{"id": "a", "symbol": "DEAD", "is_active": False}])
    result = collect_death_list(tmp_path, fetcher=_fetcher(raw))
    lines = [
        json.loads(line)
        for line in (tmp_path / "receipts.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(lines) == 1
    assert lines[0]["raw_sha256"] == result.raw_sha256
    assert lines[0]["source_kind"] == "fixture"
    assert (tmp_path / "raw" / f"{result.raw_sha256}.json").read_bytes() == raw
