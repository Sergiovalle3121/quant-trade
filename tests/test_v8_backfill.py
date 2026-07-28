"""V8 backfill engine: pagination, resume, retries, dedup, receipts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from v8_venue_fakes import FakeVenue, no_sleep

from quant_trade.v8.backfill import (
    STATUS_NETWORK_BLOCKED,
    STATUS_OK,
    STATUS_PARSE_REJECTED,
    BackfillRequest,
    PageArchive,
    RateLimiter,
    RetryPolicy,
    evidence_dir_for,
    run_backfill,
)
from quant_trade.v8.venues import (
    IdentityMismatch,
    parse_bybit_funding,
    parse_bybit_kline,
    parse_okx_candles,
    parse_okx_funding,
    series_spec,
)

HOUR = 3_600_000
START = 1_700_000_000_000 - (1_700_000_000_000 % HOUR)


def _window(days: int) -> tuple[int, int]:
    return START, START + days * 24 * HOUR


def _run(tmp_path: Path, venue: str, days: int = 30, **kwargs):
    since, until = _window(days)
    fake = kwargs.pop("fake", None) or FakeVenue(venue=venue, start_ms=since, end_ms=until)
    request = BackfillRequest(venue=venue, symbol="BTC", since_ms=since, until_ms=until)
    result = run_backfill(
        request,
        tmp_path,
        fetcher=fake.fetch,
        sleeper=no_sleep,
        clock=lambda: 0.0,
        source_kind="recorded_test_response",
        captured_at_utc="2026-07-28T00:00:00Z",
        **kwargs,
    )
    return result, fake


# --- pagination ---------------------------------------------------------------


@pytest.mark.parametrize("venue", ["bybit", "okx"])
def test_backfill_paginates_to_the_lower_bound(tmp_path: Path, venue: str) -> None:
    result, _fake = _run(tmp_path, venue, days=30)
    assert result.status == STATUS_OK
    expected_bars = 30 * 24 + 1
    for kind in ("spot", "perp", "mark", "index"):
        series = result.series[kind]
        assert series.rows == expected_bars, kind
        assert series.reached_lower_bound, kind
    # 30 days of 8h settlements
    assert result.series["funding"].rows == 30 * 3


def test_okx_needs_more_pages_than_bybit_for_the_same_window(tmp_path: Path) -> None:
    """OKX caps candle pages at 100 rows, Bybit at 1000: the engine must walk
    the extra pages rather than silently truncating the history."""
    bybit, _ = _run(tmp_path / "a", "bybit", days=30)
    okx, _ = _run(tmp_path / "b", "okx", days=30)
    assert okx.series["spot"].pages_fetched > bybit.series["spot"].pages_fetched
    assert okx.series["spot"].rows == bybit.series["spot"].rows


@pytest.mark.parametrize("venue", ["bybit", "okx"])
def test_backfill_reaches_730_days_and_1000_settlements(tmp_path: Path, venue: str) -> None:
    """The pre-registered sufficiency window is actually reachable."""
    result, _ = _run(tmp_path, venue, days=730)
    assert result.status == STATUS_OK
    assert result.series["funding"].rows >= 1000
    assert result.series["spot"].rows == 730 * 24 + 1


# --- resume / idempotency ------------------------------------------------------


@pytest.mark.parametrize("venue", ["bybit", "okx"])
def test_rerun_is_idempotent_and_touches_no_network(tmp_path: Path, venue: str) -> None:
    first, _ = _run(tmp_path, venue, days=10)
    second, fake = _run(tmp_path, venue, days=10)
    assert sum(s.pages_fetched for s in second.series.values()) == 0
    assert sum(s.pages_replayed for s in second.series.values()) > 0
    assert fake.calls == []
    for kind, series in first.series.items():
        assert second.series[kind].rows == series.rows


def test_resume_continues_after_an_interrupted_run(tmp_path: Path) -> None:
    since, until = _window(10)
    request = BackfillRequest(venue="bybit", symbol="BTC", since_ms=since, until_ms=until)
    # First attempt dies on the very first page.
    broken = FakeVenue(venue="bybit", start_ms=since, end_ms=until, faults=["transport"] * 8)
    first = run_backfill(
        request,
        tmp_path,
        fetcher=broken.fetch,
        sleeper=no_sleep,
        clock=lambda: 0.0,
        retry=RetryPolicy(max_attempts=2),
        source_kind="recorded_test_response",
    )
    assert first.status == STATUS_NETWORK_BLOCKED
    # A healthy retry completes without re-downloading whatever landed.
    healthy = FakeVenue(venue="bybit", start_ms=since, end_ms=until)
    second = run_backfill(
        request,
        tmp_path,
        fetcher=healthy.fetch,
        sleeper=no_sleep,
        clock=lambda: 0.0,
        source_kind="recorded_test_response",
    )
    assert second.status == STATUS_OK
    assert second.series["spot"].rows == 10 * 24 + 1


def test_page_archive_detects_a_tampered_raw_page(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "bybit", days=2)
    archive = PageArchive(result.evidence_dir)
    raw_files = sorted(Path(result.evidence_dir).glob("raw/*.json"))
    assert raw_files
    index = json.loads(
        (Path(result.evidence_dir) / "pages_index.jsonl").read_text().splitlines()[0]
    )
    target = Path(result.evidence_dir) / "raw" / f"{index['raw_sha256']}.json"
    target.write_bytes(b'{"retCode":0,"result":{"symbol":"BTCUSDT","list":[]}}')
    with pytest.raises(ValueError, match="no longer hashes"):
        archive.lookup(index["request_key"])


# --- retries / blocked network -------------------------------------------------


def test_retry_recovers_from_a_rate_limit_then_succeeds(tmp_path: Path) -> None:
    since, until = _window(2)
    fake = FakeVenue(venue="bybit", start_ms=since, end_ms=until, faults=["429", "500"])
    result, _ = _run(tmp_path, "bybit", days=2, fake=fake)
    assert result.status == STATUS_OK
    attempts = [
        json.loads(line)
        for line in (Path(result.evidence_dir) / "attempts.jsonl").read_text().splitlines()
    ]
    assert any(a["outcome"] == "http_error" and a["http_status"] == 429 for a in attempts)
    assert any(a["outcome"] == "ok" for a in attempts)


def test_blocked_network_records_the_verbatim_error_and_host(tmp_path: Path) -> None:
    since, until = _window(2)
    request = BackfillRequest(venue="okx", symbol="BTC", since_ms=since, until_ms=until)

    def blocked(_url: str) -> tuple[int, bytes, dict[str, str]]:
        raise OSError("CONNECT tunnel failed, response 403")

    result = run_backfill(
        request,
        tmp_path,
        fetcher=blocked,
        sleeper=no_sleep,
        clock=lambda: 0.0,
        retry=RetryPolicy(max_attempts=2),
        source_kind="live",
    )
    assert result.status == STATUS_NETWORK_BLOCKED
    assert "www.okx.com" in result.blocked_hosts
    attempts = (Path(result.evidence_dir) / "attempts.jsonl").read_text()
    assert "CONNECT tunnel failed, response 403" in attempts
    assert result.series["spot"].error.endswith("CONNECT tunnel failed, response 403")


def test_retry_policy_backs_off_exponentially_and_caps() -> None:
    policy = RetryPolicy(max_attempts=6, base_delay_seconds=2.0, max_delay_seconds=16.0)
    assert [policy.delay_for(i) for i in range(1, 7)] == [2.0, 4.0, 8.0, 16.0, 16.0, 16.0]


def test_rate_limiter_paces_requests() -> None:
    now = [0.0]
    slept: list[float] = []

    def clock() -> float:
        return now[0]

    def sleeper(seconds: float) -> None:
        slept.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(2.0, clock=clock, sleeper=sleeper)
    limiter.acquire()
    limiter.acquire()
    assert slept == [0.5]


# --- identity / duplicates -----------------------------------------------------


def test_identity_mismatch_is_rejected_not_relabelled() -> None:
    payload = json.dumps({"retCode": 0, "result": {"symbol": "ETHUSDT", "list": []}}).encode()
    with pytest.raises(IdentityMismatch):
        parse_bybit_kline(payload, symbol="BTC", kind="perp")

    okx = json.dumps(
        {
            "code": "0",
            "data": [
                {
                    "instId": "ETH-USDT-SWAP",
                    "fundingRate": "0.0001",
                    "realizedRate": "0.0001",
                    "fundingTime": "1",
                }
            ],
        }
    ).encode()
    with pytest.raises(IdentityMismatch):
        parse_okx_funding(okx, symbol="BTC")


def test_conflicting_duplicate_bars_abort_the_series(tmp_path: Path) -> None:
    """Two pages disagreeing about the same stamp is corruption, not noise."""
    since, until = _window(1)
    pages = [
        json.dumps(
            {
                "retCode": 0,
                "result": {
                    "symbol": "BTCUSDT",
                    "list": [[str(until), "100", "101", "99", "100.5", "1", "1"]],
                },
            }
        ).encode(),
        json.dumps(
            {
                "retCode": 0,
                "result": {
                    "symbol": "BTCUSDT",
                    "list": [[str(until), "100", "101", "99", "100.7", "1", "1"]],
                },
            }
        ).encode(),
    ]
    calls = {"n": 0}

    def fetcher(url: str) -> tuple[int, bytes, dict[str, str]]:
        if "market/time" in url or "instruments" in url:
            return (
                200,
                json.dumps({"retCode": 0, "result": {"timeNano": "1", "list": []}}).encode(),
                {},
            )
        page = pages[min(calls["n"], len(pages) - 1)]
        calls["n"] += 1
        return 200, page, {}

    request = BackfillRequest(
        venue="bybit", symbol="BTC", since_ms=since, until_ms=until, kinds=("spot",)
    )
    result = run_backfill(
        request,
        tmp_path,
        fetcher=fetcher,
        sleeper=no_sleep,
        clock=lambda: 0.0,
        source_kind="recorded_test_response",
    )
    assert result.status == STATUS_PARSE_REJECTED
    assert result.series["spot"].conflicting_duplicates == 1
    assert "conflicting duplicate" in result.series["spot"].error


# --- parser semantics ----------------------------------------------------------


def test_okx_unconfirmed_candles_are_dropped() -> None:
    payload = json.dumps(
        {
            "code": "0",
            "data": [
                ["2000", "1", "2", "0.5", "1.5", "1", "1", "1", "0"],  # still forming
                ["1000", "1", "2", "0.5", "1.5", "1", "1", "1", "1"],  # closed
            ],
        }
    ).encode()
    rows = parse_okx_candles(payload, symbol="BTC", kind="spot")
    assert [r["start_ms"] for r in rows] == [1000]


def test_okx_prefers_realized_rate_over_announced() -> None:
    payload = json.dumps(
        {
            "code": "0",
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "fundingRate": "0.00020",
                    "realizedRate": "0.00018",
                    "fundingTime": "1000",
                },
                {
                    "instId": "BTC-USDT-SWAP",
                    "fundingRate": "0.00010",
                    "realizedRate": "",
                    "fundingTime": "2000",
                },
            ],
        }
    ).encode()
    rows = parse_okx_funding(payload, symbol="BTC")
    assert rows[0]["rate"] == pytest.approx(0.00018)
    assert rows[0]["rate_field"] == "realizedRate"
    assert rows[1]["rate_field"] == "fundingRate"


def test_bybit_funding_rows_are_settlements() -> None:
    raw = Path("tests/fixtures/bybit_funding_history.json").read_bytes()
    rows = parse_bybit_funding(raw, symbol="BTC")
    assert rows
    assert all(r["instrument"] == "BTCUSDT" for r in rows)
    assert rows == sorted(rows, key=lambda r: r["settled_at_ms"])


def test_venue_error_envelope_is_not_treated_as_empty_data() -> None:
    from quant_trade.v8.venues import VenueErrorResponse

    with pytest.raises(VenueErrorResponse):
        parse_bybit_kline(b'{"retCode":10001,"retMsg":"bad"}', symbol="BTC", kind="spot")
    with pytest.raises(VenueErrorResponse):
        parse_okx_candles(b'{"code":"51001","msg":"nope","data":[]}', symbol="BTC", kind="spot")


def test_ohlc_sanity_is_enforced() -> None:
    bad = json.dumps(
        {"retCode": 0, "result": {"symbol": "BTCUSDT", "list": [["1", "5", "2", "1", "3"]]}}
    ).encode()
    with pytest.raises(ValueError, match="low > high|outside"):
        parse_bybit_kline(bad, symbol="BTC", kind="mark")


# --- structural guarantees ------------------------------------------------------


def test_receipts_carry_url_parser_version_and_server_clock(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "okx", days=2)
    receipts = [
        json.loads(line)
        for line in (Path(result.evidence_dir) / "receipts.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert receipts
    for receipt in receipts:
        assert receipt["endpoint"].startswith("https://www.okx.com/")
        assert receipt["adapter_version"] == "v8.1"
        assert receipt["raw_sha256"]
        assert receipt["normalized_rows_sha256"]
        assert receipt["source_kind"] == "recorded_test_response"
    assert any(r["server_timestamp_utc"] for r in receipts)


def test_recorded_responses_can_never_claim_live_provenance(tmp_path: Path) -> None:
    result, _ = _run(tmp_path, "bybit", days=2)
    assert result.provenance == "test_only"
    receipts = (Path(result.evidence_dir) / "receipts.jsonl").read_text()
    assert '"source_kind":"live"' not in receipts.replace(" ", "")


def test_evidence_dir_is_derived_from_the_canonical_pair(tmp_path: Path) -> None:
    assert evidence_dir_for(tmp_path, "OKX", "BTC-USDT-SWAP").name == "okx_btc_usdt"
    assert evidence_dir_for(tmp_path, "bybit", "BTCUSDT").name == "bybit_btc_usdt"


def test_backfill_request_rejects_an_inverted_window() -> None:
    with pytest.raises(ValueError, match="until_ms must be after"):
        BackfillRequest(venue="bybit", symbol="BTC", since_ms=10, until_ms=5)


def test_only_official_documented_hosts_are_reachable() -> None:
    """No mirrors, no proxies, no third-party redistributors."""
    hosts = set()
    for venue in ("bybit", "okx"):
        for kind in ("spot", "perp", "mark", "index", "funding"):
            spec = series_spec(venue, kind)
            hosts.add(spec.endpoint.split("/")[2])
    assert hosts == {"api.bybit.com", "www.okx.com"}
