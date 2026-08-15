from __future__ import annotations

import json
import sys
import types
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import pytest

import quant_trade.data.alpaca_spy_tom_collector as collector_module
from quant_trade.data.alpaca_spy_tom_collector import (
    API_KEY_ENV,
    API_SECRET_ENV,
    DATA_PLAN_ENV,
    AlpacaSpyTomCollectorConfig,
    AlpacaSpyTomCollectorError,
    AlpacaSpyTomTransportError,
    HttpResponse,
    RequestsReadOnlyTransport,
    collect_alpaca_spy_tom_bundle,
    verify_alpaca_spy_tom_collection_ledger,
)
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes
from quant_trade.research.prospective_spy_tom import (
    ExchangeSession,
    ExplicitExchangeCalendar,
    generate_spy_tom_targets,
    load_spy_tom_spec,
)
from quant_trade.research.prospective_spy_tom_development import (
    evaluate_spy_tom_development,
)

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "configs" / "experiments" / "spy_tom_dm1_p3_v1.yaml"
NY = ZoneInfo("America/New_York")
ENV = {
    API_KEY_ENV: "test-key-that-must-not-be-written",
    API_SECRET_ENV: "test-secret-that-must-not-be-written",
    DATA_PLAN_ENV: "BASIC",
}


def _json_bytes(value: Any) -> bytes:
    return canonical_dumps(value).encode("utf-8")


def _jsonl(rows: list[dict[str, Any]]) -> bytes:
    return ("".join(canonical_dumps(row) + "\n" for row in rows)).encode("utf-8")


def _month_sequence(count: int) -> list[tuple[int, int]]:
    first = 2016 * 12
    return [((first + offset) // 12, (first + offset) % 12 + 1) for offset in range(count)]


def _calendar(month_count: int = 121, *, early_event_closes: int = 0) -> ExplicitExchangeCalendar:
    sessions: list[ExchangeSession] = []
    months = _month_sequence(month_count)
    event_early_dates: set[date] = set()
    monthly_dates: list[list[date]] = []
    for year, month in months:
        cursor = date(year, month, 1)
        dates: list[date] = []
        while cursor.month == month:
            if cursor.weekday() < 5:
                dates.append(cursor)
            cursor += timedelta(days=1)
        monthly_dates.append(dates)
    for pair_index in range(min(early_event_closes, len(monthly_dates) - 1)):
        event_early_dates.add(monthly_dates[pair_index + 1][2])
    for dates in monthly_dates:
        for day in dates:
            close_hour = 13 if day in event_early_dates else 16
            sessions.append(
                ExchangeSession(
                    session_date=day,
                    open_timestamp=datetime.combine(day, time(9, 30), tzinfo=NY),
                    close_timestamp=datetime.combine(day, time(close_hour), tzinfo=NY),
                )
            )
    return ExplicitExchangeCalendar(
        calendar_id="XNYS",
        complete_months=tuple(f"{year:04d}-{month:02d}" for year, month in months),
        sessions=tuple(sessions),
    )


def _fee_file(tmp_path: Path, calendar: ExplicitExchangeCalendar) -> tuple[Path, str]:
    payload = _jsonl(
        [
            {
                "effective_start": calendar.session_dates[0].isoformat(),
                "effective_end": calendar.session_dates[-1].isoformat(),
                "commission_bps_per_side": 0.0,
                "regulatory_sell_bps": 0.2,
                "regulatory_sell_fixed_cents": 0,
                "source_url": "https://alpaca.markets/disclosures/fees",
            }
        ]
    )
    path = tmp_path / "independently-captured-fees.jsonl"
    path.write_bytes(payload)
    return path, sha256_of_bytes(payload)


def _target_ticks(
    calendar: ExplicitExchangeCalendar,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    spec = load_spy_tom_spec(SPEC_PATH)
    cutoff = calendar.sessions[-1].close_timestamp.astimezone(UTC)
    observations = tuple(
        datetime.combine(session.session_date, time(15, 55), tzinfo=NY)
        for session in calendar.sessions
        if session.close_timestamp.astimezone(NY).time().replace(tzinfo=None) == time(16)
    )
    targets = generate_spy_tom_targets(spec, calendar, observations, as_of=cutoff)
    quotes: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    for target in targets:
        timestamp = target.earliest_execution_timestamp.astimezone(UTC)
        for offset in (timedelta(0), timedelta(minutes=1)):
            observed = (timestamp + offset).isoformat()
            quotes.append({"t": observed, "bp": "100", "ap": "101", "bs": "10", "as": "11"})
            trades.append({"t": observed, "p": "100.5", "s": "2", "x": "V"})
    return quotes, trades


class _FakeTransport:
    def __init__(
        self,
        calendar: ExplicitExchangeCalendar,
        *,
        fail_quote_token_once: str | None = None,
        rate_limit_calendar_once: bool = False,
    ) -> None:
        self.calendar = calendar
        self.quotes, self.trades = _target_ticks(calendar)
        self.calls: list[tuple[str, dict[str, str | int], dict[str, str]]] = []
        self.fail_quote_token_once = fail_quote_token_once
        self.rate_limit_calendar_once = rate_limit_calendar_once
        self._failed = False
        self._rate_limited = False
        self._pagination_started = False
        following = calendar.sessions_by_month()[calendar.complete_months[1]]
        self.dividend_date = following[1]

    def get(
        self,
        url: str,
        *,
        params: dict[str, str | int],
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> HttpResponse:
        assert timeout_seconds == 30.0
        self.calls.append((url, dict(params), dict(headers)))
        path = urlsplit(url).path
        if path == "/v2/calendar":
            if self.rate_limit_calendar_once and not self._rate_limited:
                self._rate_limited = True
                return HttpResponse(429, {"Retry-After": "0"}, b"{}")
            payload = [
                {
                    "date": session.session_date.isoformat(),
                    "open": session.open_timestamp.astimezone(NY).strftime("%H:%M"),
                    "close": session.close_timestamp.astimezone(NY).strftime("%H:%M"),
                }
                for session in self.calendar.sessions
            ]
            return HttpResponse(200, {}, _json_bytes(payload))
        if path in {"/v2/stocks/SPY/quotes", "/v2/stocks/SPY/trades"}:
            role = "quotes" if path.endswith("quotes") else "trades"
            token = params.get("page_token")
            if (
                role == "quotes"
                and self.fail_quote_token_once is not None
                and token == self.fail_quote_token_once
                and not self._failed
            ):
                self._failed = True
                raise AlpacaSpyTomTransportError("simulated and redacted")
            values = self.quotes if role == "quotes" else self.trades
            window_start = datetime.fromisoformat(str(params["start"]))
            window_end = datetime.fromisoformat(str(params["end"]))
            window_values = [
                row
                for row in values
                if window_start <= datetime.fromisoformat(str(row["t"])) <= window_end
            ]
            split = len(window_values) // 2
            if token is not None:
                assert token == f"{role}-page-2"
                rows = window_values[split:]
                next_token = None
            elif (
                role == "quotes"
                and self.fail_quote_token_once is not None
                and not self._pagination_started
            ):
                self._pagination_started = True
                rows = window_values[:split]
                next_token = f"{role}-page-2"
            else:
                rows = window_values
                next_token = None
            return HttpResponse(
                200,
                {},
                _json_bytes({role: rows, "symbol": "SPY", "next_page_token": next_token}),
            )
        if path == "/v2/corporate_actions/announcements":
            since = date.fromisoformat(str(params["since"]))
            until = date.fromisoformat(str(params["until"]))
            rows: list[dict[str, Any]] = []
            if since <= self.dividend_date <= until:
                rows.append(
                    {
                        "id": "announcement-v1",
                        "corporate_action_id": "spy-dividend-2016q1",
                        "ca_type": "Dividend",
                        "ca_sub_type": "cash",
                        "initiating_symbol": "SPY",
                        "declaration_date": "2016-01-15",
                        "ex_date": self.dividend_date.isoformat(),
                        "cash": "0.20",
                        "old_rate": "1",
                        "new_rate": "1",
                    }
                )
            return HttpResponse(200, {}, _json_bytes(rows))
        raise AssertionError(f"unexpected GET target {url}")


def _config(
    tmp_path: Path,
    calendar: ExplicitExchangeCalendar,
    *,
    max_retries: int = 4,
) -> AlpacaSpyTomCollectorConfig:
    fee_path, fee_sha = _fee_file(tmp_path, calendar)
    cutoff = calendar.sessions[-1].close_timestamp.astimezone(UTC)
    return AlpacaSpyTomCollectorConfig(
        output_root=tmp_path / "bundle",
        start=calendar.sessions[0].open_timestamp.astimezone(UTC),
        hard_cutoff=cutoff,
        as_of=cutoff + timedelta(days=3),
        fee_schedule_path=fee_path,
        expected_fee_schedule_sha256=fee_sha,
        max_retries=max_retries,
    )


def _clock(config: AlpacaSpyTomCollectorConfig) -> datetime:
    return config.hard_cutoff + timedelta(days=1)


def _collect(
    config: AlpacaSpyTomCollectorConfig,
    transport: _FakeTransport,
    *,
    sleeper: Any = lambda _: None,
) -> Any:
    return collect_alpaca_spy_tom_bundle(
        config,
        transport,
        environ=ENV,
        clock=lambda: _clock(config),
        sleeper=sleeper,
        monotonic=lambda: 0.0,
    )


def test_collector_publishes_evaluator_compatible_content_addressed_bundle(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    config = _config(tmp_path, calendar)
    transport = _FakeTransport(calendar, rate_limit_calendar_once=True)
    sleeps: list[float] = []

    result = _collect(config, transport, sleeper=sleeps.append)

    assert result.maximum_attestable_pairs == 120
    assert result.request_count > 5
    assert result.bundle_root == config.output_root.resolve()
    assert verify_alpaca_spy_tom_collection_ledger(result.bundle_root) != "0" * 64
    assert sleeps
    manifest_bytes = (result.bundle_root / "manifest.json").read_bytes()
    assert sha256_of_bytes(manifest_bytes) == result.manifest_sha256
    manifest = json.loads(manifest_bytes)
    assert manifest["feed"] == "SIP"
    assert manifest["end"] == config.hard_cutoff.astimezone(UTC).isoformat()

    verdict = evaluate_spy_tom_development(
        result.bundle_root,
        load_spy_tom_spec(SPEC_PATH),
        calendar,
        expected_manifest_sha256=result.manifest_sha256,
        development_cutoff=config.hard_cutoff,
        as_of=_clock(config),
    )
    assert verdict.status == "INSUFFICIENT_EVIDENCE"
    assert verdict.completed_pairs == 120
    assert verdict.scenarios
    assert not verdict.external_data_authority_verified
    assert not verdict.live_execution_authorized
    assert not verdict.real_money_authorized

    all_bytes = b"".join(
        path.read_bytes() for path in result.bundle_root.rglob("*") if path.is_file()
    )
    assert ENV[API_KEY_ENV].encode() not in all_bytes
    assert ENV[API_SECRET_ENV].encode() not in all_bytes
    for url, params, headers in transport.calls:
        path = urlsplit(url).path
        assert urlsplit(url).scheme == "https"
        assert path in {
            "/v2/calendar",
            "/v2/stocks/SPY/quotes",
            "/v2/stocks/SPY/trades",
            "/v2/corporate_actions/announcements",
        }
        assert headers["APCA-API-KEY-ID"] == ENV[API_KEY_ENV]
        assert headers["APCA-API-SECRET-KEY"] == ENV[API_SECRET_ENV]
        assert "account" not in path and "position" not in path and "order" not in path
        if path in {"/v2/stocks/SPY/quotes", "/v2/stocks/SPY/trades"}:
            assert params["feed"] == "sip"
            window_start = datetime.fromisoformat(str(params["start"]))
            window_end = datetime.fromisoformat(str(params["end"]))
            assert window_end - window_start == timedelta(minutes=2)
            assert window_start.astimezone(NY).time().replace(tzinfo=None) == time(15, 56)
            assert window_end.astimezone(NY).time().replace(tzinfo=None) == time(15, 58)
            assert config.start <= window_start < window_end <= config.hard_cutoff

    quote_windows = {
        (call[1]["start"], call[1]["end"])
        for call in transport.calls
        if call[0].endswith("/quotes")
    }
    trade_windows = {
        (call[1]["start"], call[1]["end"])
        for call in transport.calls
        if call[0].endswith("/trades")
    }
    assert quote_windows == trade_windows
    assert len(quote_windows) == 480
    receipt_rows = [
        json.loads(line)
        for line in (result.bundle_root / "raw" / "receipts.jsonl").read_text("utf-8").splitlines()
    ]
    quote_receipt = next(row for row in receipt_rows if row["artifact_role"] == "quotes")
    receipt_scope = quote_receipt["request_parameters"]
    canonical_windows = [{"end": end, "start": start} for start, end in sorted(quote_windows)]
    assert receipt_scope["collection_mode"] == "EXACT_EVENT_WINDOWS_1556_1558_ET"
    assert receipt_scope["event_window_count"] == 480
    assert receipt_scope["event_windows_sha256"] == sha256_of_bytes(
        canonical_dumps(canonical_windows).encode("utf-8")
    )
    assert "start" not in receipt_scope and "end" not in receipt_scope


@pytest.mark.parametrize(
    ("environment", "reason"),
    [
        ({DATA_PLAN_ENV: "BASIC"}, "ALPACA_DATA_CREDENTIAL_ENV_VARS_ARE_MISSING"),
        (
            {API_KEY_ENV: "key", API_SECRET_ENV: "secret"},
            "ALPACA_MARKET_DATA_PLAN_ENV_VAR_IS_MISSING",
        ),
        (
            {API_KEY_ENV: "key", API_SECRET_ENV: "secret", DATA_PLAN_ENV: "UNKNOWN"},
            "ALPACA_MARKET_DATA_PLAN_IS_NOT_RECOGNIZED",
        ),
    ],
)
def test_missing_credentials_or_sip_plan_fails_before_network(
    tmp_path: Path,
    environment: dict[str, str],
    reason: str,
) -> None:
    calendar = _calendar()
    config = _config(tmp_path, calendar)
    transport = _FakeTransport(calendar)

    with pytest.raises(AlpacaSpyTomCollectorError, match=reason):
        collect_alpaca_spy_tom_bundle(
            config,
            transport,
            environ=environment,
            clock=lambda: _clock(config),
            sleeper=lambda _: None,
            monotonic=lambda: 0.0,
        )

    assert not transport.calls
    assert not config.output_root.exists()


def test_generic_or_live_credential_names_fail_before_network(tmp_path: Path) -> None:
    calendar = _calendar()
    config = _config(tmp_path, calendar)
    transport = _FakeTransport(calendar)
    environment = {
        API_KEY_ENV: "paper-key",
        API_SECRET_ENV: "paper-secret",
        DATA_PLAN_ENV: "BASIC",
        "APCA_API_KEY_ID": "possibly-live-key",
        "APCA_API_SECRET_KEY": "possibly-live-secret",
    }

    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="GENERIC_OR_LIVE_ALPACA_CREDENTIAL_ENV_VARS_ARE_FORBIDDEN",
    ):
        collect_alpaca_spy_tom_bundle(
            config,
            transport,
            environ=environment,
            clock=lambda: _clock(config),
            sleeper=lambda _: None,
            monotonic=lambda: 0.0,
        )

    assert not transport.calls


def test_requests_transport_streams_and_enforces_decompressed_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    class FakeResponse:
        status_code = 200
        headers: dict[str, str] = {}
        closed = False

        @property
        def content(self) -> bytes:
            raise AssertionError("response.content must never be materialized")

        def iter_content(self, *, chunk_size: int) -> Any:
            assert chunk_size == 64 * 1024
            yield b"abcd"
            yield b"efgh"

        def close(self) -> None:
            self.closed = True

    response = FakeResponse()

    def fake_get(url: str, **kwargs: Any) -> FakeResponse:
        observed["url"] = url
        observed.update(kwargs)
        return response

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=fake_get))
    monkeypatch.setattr(collector_module, "_MAX_RESPONSE_BYTES", 5)

    with pytest.raises(AlpacaSpyTomCollectorError, match="ALPACA_RESPONSE_IS_TOO_LARGE"):
        RequestsReadOnlyTransport().get(
            "https://data.alpaca.markets/v2/stocks/SPY/quotes",
            params={"feed": "sip"},
            headers={"Accept": "application/json"},
            timeout_seconds=30.0,
        )

    assert observed["stream"] is True
    assert observed["allow_redirects"] is False
    assert response.closed


def test_requests_transport_rejects_compressed_content_before_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    iterated = False

    class CompressedResponse:
        status_code = 200
        headers = {"Content-Encoding": "gzip", "Content-Length": "100"}

        def iter_content(self, *, chunk_size: int) -> Any:
            del chunk_size
            nonlocal iterated
            iterated = True
            yield b"not-reached"

        def close(self) -> None:
            pass

    def fake_get(_url: str, **kwargs: Any) -> CompressedResponse:
        assert kwargs["headers"]["Accept-Encoding"] == "identity"
        return CompressedResponse()

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=fake_get))
    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="ALPACA_COMPRESSED_RESPONSE_IS_NOT_PERMITTED",
    ):
        RequestsReadOnlyTransport().get(
            "https://data.alpaca.markets/v2/stocks/SPY/quotes",
            params={"feed": "sip"},
            headers={"Accept": "application/json"},
            timeout_seconds=30.0,
        )
    assert not iterated


def test_invocation_time_budget_fails_closed() -> None:
    observed = iter((0.0, 3_601.0))
    budget = collector_module._InvocationBudget(lambda: next(observed), 3_600.0)

    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="COLLECTION_INVOCATION_TIME_BUDGET_EXCEEDED",
    ):
        budget.before_http_attempt()


def test_basic_recent_sip_and_fee_hash_fail_before_network(tmp_path: Path) -> None:
    calendar = _calendar()
    config = _config(tmp_path, calendar)
    transport = _FakeTransport(calendar)
    recent_now = config.hard_cutoff + timedelta(minutes=5)
    recent = replace(config, as_of=config.hard_cutoff + timedelta(days=1))

    with pytest.raises(AlpacaSpyTomCollectorError, match="AT_LEAST_15_MINUTES"):
        collect_alpaca_spy_tom_bundle(
            recent,
            transport,
            environ=ENV,
            clock=lambda: recent_now,
            sleeper=lambda _: None,
            monotonic=lambda: 0.0,
        )
    assert not transport.calls

    bad_hash = replace(config, expected_fee_schedule_sha256="f" * 64)
    with pytest.raises(AlpacaSpyTomCollectorError, match="FEE_SCHEDULE_SHA256_MISMATCH"):
        _collect(bad_hash, transport)
    assert not transport.calls


def test_oversized_local_state_and_fee_files_fail_before_materialization_or_network(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    state_path = bundle / ".collector" / "state.json"
    state_path.parent.mkdir(parents=True)
    with state_path.open("wb") as handle:
        handle.truncate(collector_module._MAX_STATE_BYTES + 1)
    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="COLLECTOR_STATE_IS_MISSING_UNSAFE_OR_TOO_LARGE",
    ):
        verify_alpaca_spy_tom_collection_ledger(bundle)

    calendar = _calendar()
    fee_root = tmp_path / "fee"
    fee_root.mkdir()
    config = _config(fee_root, calendar)
    with config.fee_schedule_path.open("wb") as handle:
        handle.truncate(collector_module._MAX_FEE_SCHEDULE_BYTES + 1)
    transport = _FakeTransport(calendar)
    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="FEE_SCHEDULE_IS_UNREADABLE_OR_TOO_LARGE",
    ):
        _collect(config, transport)
    assert not transport.calls


def test_calendar_capacity_aborts_before_any_tick_download(tmp_path: Path) -> None:
    calendar = _calendar(month_count=120)
    config = _config(tmp_path, calendar)
    transport = _FakeTransport(calendar)

    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="MAXIMUM_ATTESTABLE_PAIRS_BELOW_120",
    ):
        _collect(config, transport)

    assert [urlsplit(call[0]).path for call in transport.calls] == ["/v2/calendar"]
    assert not config.output_root.exists()


def test_early_close_event_reduces_capacity_and_aborts_before_ticks(tmp_path: Path) -> None:
    calendar = _calendar(early_event_closes=1)
    config = _config(tmp_path, calendar)
    transport = _FakeTransport(calendar)

    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="MAXIMUM_ATTESTABLE_PAIRS_BELOW_120",
    ):
        _collect(config, transport)

    assert len(transport.calls) == 1
    state = json.loads(
        (tmp_path / ".bundle.partial" / ".collector" / "state.json").read_text("utf-8")
    )
    assert state["roles"]["calendar"]["maximum_attestable_pairs"] == 119


def test_pagination_checkpoint_resumes_without_refetching_completed_page(
    tmp_path: Path,
) -> None:
    calendar = _calendar()
    config = _config(tmp_path, calendar, max_retries=0)
    first = _FakeTransport(calendar, fail_quote_token_once="quotes-page-2")

    with pytest.raises(AlpacaSpyTomCollectorError, match="ALPACA_GET_FAILED_RESUME_SAFE"):
        _collect(config, first)
    first_quote_calls = [call for call in first.calls if call[0].endswith("/quotes")]
    assert len(first_quote_calls) == 2
    assert "page_token" not in first_quote_calls[0][1]
    assert first_quote_calls[1][1]["page_token"] == "quotes-page-2"

    second = _FakeTransport(calendar)
    result = _collect(config, second)

    resumed_quote_calls = [call for call in second.calls if call[0].endswith("/quotes")]
    assert len(resumed_quote_calls) == 480
    assert resumed_quote_calls[0][1]["page_token"] == "quotes-page-2"
    assert all("page_token" not in call[1] for call in resumed_quote_calls[1:])
    assert result.bundle_root.exists()


def test_completed_capture_can_publish_offline_after_as_of_without_new_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calendar = _calendar()
    config = _config(tmp_path, calendar)
    staging = tmp_path / ".bundle.partial"
    staging.mkdir()
    state = collector_module._new_state("a" * 64)
    for role in collector_module._SOURCE_ROLES:
        state["roles"][role]["complete"] = True
    state["manifest_captured_at"] = _clock(config).isoformat()
    transport = _FakeTransport(calendar)

    monkeypatch.setattr(
        collector_module,
        "_load_or_create_state",
        lambda _staging, _config_sha: state,
    )
    monkeypatch.setattr(
        collector_module,
        "_pair_capacity_preflight",
        lambda _staging, _state: 120,
    )

    def fail_if_collection_runs(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("offline publication must not collect new evidence")

    for name in (
        "_collect_calendar",
        "_collect_market_role",
        "_collect_corporate_actions",
        "_append_local_fee_receipt",
    ):
        monkeypatch.setattr(collector_module, name, fail_if_collection_runs)

    expected = collector_module.CollectionResult(
        bundle_root=config.output_root.resolve(),
        manifest_sha256="b" * 64,
        captured_at_utc=_clock(config).isoformat(),
        request_count=0,
        maximum_attestable_pairs=120,
    )

    def publish_offline(*_args: Any, **kwargs: Any) -> Any:
        assert kwargs["maximum_attestable_pairs"] == 120
        return expected

    monkeypatch.setattr(collector_module, "_publish_bundle", publish_offline)
    result = collect_alpaca_spy_tom_bundle(
        config,
        transport,
        environ=ENV,
        clock=lambda: config.as_of + timedelta(seconds=1),
        sleeper=lambda _: None,
        monotonic=lambda: 0.0,
    )

    assert result == expected
    assert not transport.calls

    state["roles"]["quotes"]["complete"] = False
    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="COLLECTION_CLOCK_IS_OUTSIDE_CUTOFF_AND_AS_OF",
    ):
        collect_alpaca_spy_tom_bundle(
            config,
            transport,
            environ=ENV,
            clock=lambda: config.as_of + timedelta(seconds=1),
            sleeper=lambda _: None,
            monotonic=lambda: 0.0,
        )
    assert not transport.calls


def test_checkpoint_persists_receipt_and_cursor_in_one_atomic_state_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / "partial"
    (staging / ".collector").mkdir(parents=True)
    config_sha = "a" * 64
    state = collector_module._new_state(config_sha)
    collector_module._atomic_state_write(staging / ".collector" / "state.json", state)
    original_write = collector_module._atomic_state_write

    def fail_state_write(path: Path, value: dict[str, Any]) -> None:
        del path, value
        raise OSError("simulated crash before atomic replace")

    monkeypatch.setattr(collector_module, "_atomic_state_write", fail_state_write)
    with pytest.raises(OSError, match="simulated crash"):
        collector_module._checkpoint_response(
            staging,
            state,
            role="quotes",
            endpoint="/v2/stocks/SPY/quotes",
            params={"start": "2016-01-04T20:56:00+00:00", "end": "2016-01-04T20:58:00+00:00"},
            response=HttpResponse(200, {}, b'{"next_page_token":null,"quotes":[]}'),
            captured_at=datetime(2016, 2, 1, tzinfo=UTC),
            rows=None,
            role_state_updates={
                "next_chunk_index": 1,
                "next_page_token": None,
                "next_sequence": 0,
                "last_timestamp": None,
                "complete": False,
            },
        )

    persisted = json.loads((staging / ".collector" / "state.json").read_text("utf-8"))
    assert persisted["requests"] == []
    assert persisted["roles"]["quotes"]["next_chunk_index"] == 0

    monkeypatch.setattr(collector_module, "_atomic_state_write", original_write)
    resumed = collector_module._load_or_create_state(staging, config_sha)
    collector_module._checkpoint_response(
        staging,
        resumed,
        role="quotes",
        endpoint="/v2/stocks/SPY/quotes",
        params={"start": "2016-01-04T20:56:00+00:00", "end": "2016-01-04T20:58:00+00:00"},
        response=HttpResponse(200, {}, b'{"next_page_token":null,"quotes":[]}'),
        captured_at=datetime(2016, 2, 1, tzinfo=UTC),
        rows=None,
        role_state_updates={
            "next_chunk_index": 1,
            "next_page_token": None,
            "next_sequence": 0,
            "last_timestamp": None,
            "complete": False,
        },
    )
    persisted = json.loads((staging / ".collector" / "state.json").read_text("utf-8"))
    assert len(persisted["requests"]) == 1
    assert persisted["roles"]["quotes"]["next_chunk_index"] == 1

    persisted["roles"]["quotes"]["complete"] = True
    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="COLLECTOR_ROLE_CURSOR_DOES_NOT_MATCH_CHAIN",
    ):
        collector_module._verify_state(staging, persisted)


def test_collection_mutex_rejects_a_concurrent_fork(tmp_path: Path) -> None:
    lock_path = tmp_path / ".bundle.collector.lock"

    with (
        collector_module._CollectionMutex(lock_path),
        pytest.raises(
            AlpacaSpyTomCollectorError,
            match="COLLECTION_OUTPUT_IS_LOCKED_BY_ANOTHER_PROCESS",
        ),
        collector_module._CollectionMutex(lock_path),
    ):
        raise AssertionError("unreachable")


def test_collection_mutex_rejects_a_hardlinked_lock_without_touching_victim(
    tmp_path: Path,
) -> None:
    victim = tmp_path / "victim.bin"
    lock_path = tmp_path / ".bundle.collector.lock"
    victim.write_bytes(b"")
    try:
        lock_path.hardlink_to(victim)
    except OSError as exc:
        pytest.skip(f"hardlinks are unavailable: {exc}")

    with (
        pytest.raises(
            AlpacaSpyTomCollectorError,
            match="COLLECTION_LOCK_FILE_IS_UNSAFE",
        ),
        collector_module._CollectionMutex(lock_path),
    ):
        raise AssertionError("unreachable")

    assert victim.read_bytes() == b""


def test_materialization_rehashes_each_chunk_from_the_same_read_handle(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "partial"
    (staging / ".collector").mkdir(parents=True)
    state = collector_module._new_state("a" * 64)
    collector_module._atomic_state_write(staging / ".collector" / "state.json", state)
    original_rows = _jsonl([{"date": "2016-01-04", "value": 1}])
    collector_module._checkpoint_response(
        staging,
        state,
        role="calendar",
        endpoint="/v2/calendar",
        params={"start": "2016-01-04", "end": "2016-01-04"},
        response=HttpResponse(200, {}, b"[]"),
        captured_at=datetime(2016, 2, 1, tzinfo=UTC),
        rows=original_rows,
        role_state_updates={"next_chunk_index": 1},
    )
    collector_module._verify_state(staging, state)
    rows_path = staging / state["requests"][0]["rows_path"]
    tampered_rows = _jsonl([{"date": "2016-01-04", "value": 2}])
    assert len(tampered_rows) == len(original_rows)
    rows_path.write_bytes(tampered_rows)

    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="COLLECTOR_ROWS_SHA256_MISMATCH",
    ):
        collector_module._materialize_role_rows(
            staging,
            state,
            "calendar",
            "raw/calendar.jsonl",
        )

    assert not (staging / "raw" / "calendar.jsonl").exists()


def test_unique_page_tokens_stop_at_per_window_budget(tmp_path: Path) -> None:
    calendar = _calendar()
    config = _config(tmp_path, calendar)

    class EndlessTokenTransport(_FakeTransport):
        quote_pages = 0

        def get(
            self,
            url: str,
            *,
            params: dict[str, str | int],
            headers: dict[str, str],
            timeout_seconds: float,
        ) -> HttpResponse:
            if url.endswith("/quotes"):
                self.calls.append((url, dict(params), dict(headers)))
                self.quote_pages += 1
                timestamp = str(params["start"])
                return HttpResponse(
                    200,
                    {},
                    _json_bytes(
                        {
                            "quotes": [
                                {"t": timestamp, "bp": "100", "ap": "101", "bs": "1", "as": "1"}
                            ],
                            "symbol": "SPY",
                            "next_page_token": f"unique-{self.quote_pages}",
                        }
                    ),
                )
            return super().get(
                url,
                params=params,
                headers=headers,
                timeout_seconds=timeout_seconds,
            )

    transport = EndlessTokenTransport(calendar)
    with pytest.raises(
        AlpacaSpyTomCollectorError,
        match="ALPACA_QUOTES_WINDOW_PAGE_BUDGET_EXCEEDED",
    ):
        _collect(config, transport)

    assert transport.quote_pages == collector_module._MAX_PAGES_PER_MARKET_WINDOW


def test_no_overwrite_and_ledger_tamper_fail_closed(tmp_path: Path) -> None:
    calendar = _calendar()
    config = _config(tmp_path, calendar)
    first = _FakeTransport(calendar)
    result = _collect(config, first)
    second = _FakeTransport(calendar)

    with pytest.raises(AlpacaSpyTomCollectorError, match="NO_OVERWRITE"):
        _collect(config, second)
    assert not second.calls

    response_file = next((result.bundle_root / ".collector" / "responses").rglob("*.json"))
    response_file.write_bytes(response_file.read_bytes() + b" ")
    with pytest.raises(AlpacaSpyTomCollectorError, match="FILE_EXCEEDS_BYTE_LIMIT"):
        verify_alpaca_spy_tom_collection_ledger(result.bundle_root)


def test_collector_has_no_execution_or_order_adapter_imports() -> None:
    source = (ROOT / "src" / "quant_trade" / "data" / "alpaca_spy_tom_collector.py").read_text(
        encoding="utf-8"
    )
    assert "quant_trade.execution" not in source
    assert "submit_order" not in source
    assert "paper-api.alpaca.markets/v2/account" not in source
    assert "api.alpaca.markets/v2/orders" not in source
