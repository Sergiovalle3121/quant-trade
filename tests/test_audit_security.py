"""Security and robustness review of the audit service (thread M).

Each test pins one finding of docs/AUDIT_SECURITY_REVIEW.md: a hostile or
unlucky upload gets a clear refusal in the customer's language, never a
server error, a hung worker or an echoed secret. Offline and deterministic.
"""

from __future__ import annotations

import io
import logging
import struct
import time
import zipfile
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import csv_bytes, positive_drift, synthetic_mt5_report

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import engine  # noqa: E402
from quant_trade.audit.importers import (  # noqa: E402
    ReportFormatError,
    _read_delimited,
    _xml,
    read_xlsx,
)
from quant_trade.audit.schema import (  # noqa: E402
    MAX_CSV_LINE_BYTES,
    DeclaredMetadata,
    ParseError,
    build_inputs,
    parse_equity_csv,
)
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import (  # noqa: E402
    CODE_ALPHABET,
    CODE_GROUP_LENGTH,
    CODE_GROUPS,
    make_store,
)
from quant_trade.audit.web import (  # noqa: E402
    CONTENT_SECURITY_POLICY,
    FORM_OVERHEAD_BYTES,
    PRINT_HANDLER,
    SECURITY_HEADERS,
    UPLOAD_ATTEMPTS_PER_UPLOAD,
    UPLOAD_FIELDS,
    WAITLIST_PER_HOUR_PER_IP,
    AttemptLog,
    RedactSecretsFilter,
    create_app,
    message,
    redact_secrets,
    uvicorn_log_config,
)

XSS = "\"'><script>alert(1)</script><img src=x onerror=alert(2)>"


def _client(tmp_path: Path, **overrides) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **overrides
    )
    return TestClient(
        create_app(settings, make_store(settings.database_url)), raise_server_exceptions=False
    )


def _post(client: TestClient, files: dict, **form):
    data = {"consent": "on", **form}
    return client.post("/audits", files=files, data=data, follow_redirects=False)


def _equity_upload() -> dict:
    return {"equity": ("equity.csv", csv_bytes(positive_drift(300)), "text/csv")}


# ---------------------------------------------------------------------------
# Uploads: hostile files are refused plainly and quickly
# ---------------------------------------------------------------------------


def _workbook_with_lying_size() -> bytes:
    """A deflated member that inflates to 3 MB but declares 100 bytes."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "<workbook>" + " " * 3_000_000 + "</workbook>")
    raw = bytearray(buffer.getvalue())
    central = raw.rfind(b"PK\x01\x02")
    struct.pack_into("<I", raw, central + 24, 100)  # uncompressed size, central directory
    struct.pack_into("<I", raw, 22, 100)  # uncompressed size, local header
    return bytes(raw)


def test_a_workbook_that_lies_about_its_size_is_refused_not_a_server_error(
    tmp_path: Path,
) -> None:
    with pytest.raises(ReportFormatError) as caught:
        read_xlsx(_workbook_with_lying_size())
    assert caught.value.code == "bad_xlsx"
    response = _post(
        _client(tmp_path),
        {"report": ("report.xlsx", _workbook_with_lying_size(), "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "dañado o cifrado" in response.text


def test_a_utf16_doctype_inside_a_workbook_is_refused_before_any_entity() -> None:
    bomb = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;">]>'
        "<workbook>&b;</workbook>"
    )
    data = b"\xff\xfe" + bomb.encode("utf-16-le")
    # The cheap byte check cannot see it: every ASCII byte has a NUL after it.
    assert b"<!DOCTYPE" not in data
    with pytest.raises(ReportFormatError) as caught:
        _xml(data)
    assert caught.value.code == "xml_doctype"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", data)
    with pytest.raises(ReportFormatError) as caught:
        read_xlsx(buffer.getvalue())
    assert caught.value.code == "xml_doctype"


def test_plain_xml_without_a_doctype_still_parses() -> None:
    root = _xml(b"\xff\xfe" + "<a><b>1</b></a>".encode("utf-16-le"))
    assert root.find("b").text == "1"


def test_a_csv_line_past_the_limit_is_refused_at_once() -> None:
    # A 5 MB line of fields used to keep pandas busy for minutes.
    data = b"date,equity\n" + b"1," * 2_000_000
    started = time.perf_counter()
    with pytest.raises(ParseError) as caught:
        parse_equity_csv(data)
    assert caught.value.code == "line_too_long"
    assert time.perf_counter() - started < 5
    assert f"{MAX_CSV_LINE_BYTES:,}" in caught.value.localized("es")


def test_a_legit_wide_variants_header_is_within_the_line_limit() -> None:
    header = ",".join(["date", *[f"variant_{index:03d}_fast_slow" for index in range(500)]])
    assert len(header) < MAX_CSV_LINE_BYTES


def test_an_unreadable_delimited_report_is_a_format_error() -> None:
    # An unbalanced quote swallows the file into one field past csv's limit.
    text = 'Trade #,Type\n"' + "a" * 200_000
    with pytest.raises(ReportFormatError) as caught:
        _read_delimited(text)
    assert caught.value.code == "bad_csv"


def test_the_bootstrap_work_is_bounded_and_recorded(monkeypatch) -> None:
    assert engine.bootstrap_samples_used(1000, 5_000) == 1000
    assert engine.bootstrap_samples_used(1000, 200_000) == engine.BOOTSTRAP_MIN_SAMPLES
    assert engine.bootstrap_samples_used(1000, 20_000) == 500
    # Shrink the budget so a small curve exercises the reduction quickly.
    monkeypatch.setattr(engine, "BOOTSTRAP_MAX_CELLS", 60_000)
    frame = positive_drift(600)
    inputs = build_inputs(csv_bytes(frame), DeclaredMetadata())
    result = engine.run_audit(inputs, bootstrap_samples=1000)
    assert result.bootstrap["samples_requested"] == 1000
    assert result.bootstrap["samples"] == 100
    assert result.engine["bootstrap_samples"] == 1000


def test_a_long_intraday_curve_finishes_within_a_time_budget() -> None:
    rng = np.random.default_rng(3)
    n = 60_000
    stamps = pd.date_range("2015-01-01", periods=n, freq="h")
    equity = 10_000 * np.exp(np.cumsum(rng.normal(0, 0.001, n)))
    data = pd.DataFrame({"date": stamps.strftime("%Y-%m-%d %H:%M"), "equity": equity.round(2)})
    inputs = build_inputs(data.to_csv(index=False).encode(), DeclaredMetadata())
    started = time.perf_counter()
    result = engine.run_audit(inputs, bootstrap_samples=1000)
    # 1,000 samples x 60,000 returns took about 12 s; the budget keeps it short.
    assert time.perf_counter() - started < 20
    assert result.bootstrap["samples"] < 1000


# ---------------------------------------------------------------------------
# Request size, rate limits and the busy state
# ---------------------------------------------------------------------------


def test_a_declared_oversized_body_is_refused_before_it_is_read(tmp_path: Path) -> None:
    client = _client(tmp_path, max_upload_bytes=1_000)
    limit = 1_000 * UPLOAD_FIELDS + FORM_OVERHEAD_BYTES
    body = b"x" * (limit + 1)
    response = client.post(
        "/audits?lang=en",
        content=body,
        headers={"content-type": "multipart/form-data; boundary=zz"},
    )
    assert response.status_code == 413
    assert "maximum size" in response.text
    assert response.headers["Content-Security-Policy"] == CONTENT_SECURITY_POLICY


def test_a_streamed_oversized_body_is_cut_off_with_a_clear_message(tmp_path: Path) -> None:
    client = _client(tmp_path, max_upload_bytes=1_000)
    limit = 1_000 * UPLOAD_FIELDS + FORM_OVERHEAD_BYTES

    def chunks():
        sent = 0
        while sent <= limit:
            yield b"--zz\r\n" + b"x" * 65_536
            sent += 65_542

    response = client.post(
        "/audits",
        content=chunks(),
        headers={"content-type": "multipart/form-data; boundary=zz", "accept": "application/json"},
    )
    assert response.status_code == 413
    assert "tamaño máximo" in response.json()["error"]


def test_failed_uploads_count_toward_the_attempt_limit(tmp_path: Path) -> None:
    client = _client(tmp_path, max_uploads_per_hour_per_ip=1)
    junk = {"report": ("report.htm", b"<html>nothing</html>", "text/html")}
    for _ in range(UPLOAD_ATTEMPTS_PER_UPLOAD):
        assert _post(client, junk).status_code == 400
    refused = _post(client, junk)
    assert refused.status_code == 429
    assert refused.text.count(message("rate_limited", "es")) == 1


def test_waitlist_sign_ups_are_rate_limited(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for index in range(WAITLIST_PER_HOUR_PER_IP):
        response = client.post(
            "/waitlist", data={"email": f"a{index}@example.com"}, follow_redirects=False
        )
        assert response.status_code == 303
    assert client.post("/waitlist", data={"email": "z@example.com"}).status_code == 429
    assert len(client.app.state.store.waitlist_emails()) == WAITLIST_PER_HOUR_PER_IP


def test_a_busy_service_says_so_instead_of_piling_up(tmp_path: Path) -> None:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        max_concurrent_audits=1,
        audit_queue_seconds=0,
    )
    app = create_app(settings, make_store(settings.database_url))
    slots = app.state.audit_slots
    with TestClient(app) as client:
        # Another audit holds the only slot.
        client.portal.call(slots.acquire_on_behalf_of_nowait, "running-audit")
        try:
            busy = _post(client, _equity_upload(), locale="en")
        finally:
            client.portal.call(slots.release_on_behalf_of, "running-audit")
        assert busy.status_code == 503
        assert message("busy", "en") in busy.text
        assert _post(client, _equity_upload()).status_code == 303


def test_a_waiting_upload_gets_the_slot_when_it_frees(tmp_path: Path) -> None:
    import anyio

    from quant_trade.audit.web import _take_slot

    async def scenario() -> tuple[bool, bool]:
        slots = anyio.CapacityLimiter(1)
        await slots.acquire_on_behalf_of("first")
        refused = await _take_slot(slots, 0.05)

        async def free_soon() -> None:
            await anyio.sleep(0.05)
            slots.release_on_behalf_of("first")

        async with anyio.create_task_group() as group:
            group.start_soon(free_soon)
            waited = await _take_slot(slots, 5)
        slots.release()
        return refused, waited

    assert anyio.run(scenario) == (False, True)


def test_the_attempt_log_forgets_old_addresses() -> None:
    log = AttemptLog()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for index in range(50):
        log.hit(f"10.0.0.{index}", start)
    assert len(log) == 50
    assert log.hit("10.0.0.1", start + timedelta(hours=2)) == 0
    assert len(log) == 1


# ---------------------------------------------------------------------------
# Errors, headers and hosts
# ---------------------------------------------------------------------------


def test_an_unexpected_failure_is_a_localised_page_without_a_traceback(
    tmp_path: Path, monkeypatch
) -> None:
    from quant_trade.audit import web

    def explode(*args, **kwargs):
        raise RuntimeError("internal detail /app/src/secret.py")

    monkeypatch.setattr(web, "run_audit", explode)
    response = _post(_client(tmp_path), _equity_upload(), locale="en")
    assert response.status_code == 500
    assert message("server_error", "en") in response.text
    assert "Traceback" not in response.text and "secret.py" not in response.text
    assert response.headers["X-Frame-Options"] == "DENY"


def test_an_importer_crash_is_a_format_message(tmp_path: Path, monkeypatch) -> None:
    from quant_trade.audit import web

    def explode(*args, **kwargs):
        raise KeyError("column")

    monkeypatch.setattr(web, "build_inputs", explode)
    response = _post(_client(tmp_path), _equity_upload())
    assert response.status_code == 400
    assert message("invalid_upload", "es") in response.text


@pytest.mark.parametrize("path", ["/", "/ejemplo", "/nope", "/health"])
def test_every_response_carries_the_security_headers(tmp_path: Path, path: str) -> None:
    response = _client(tmp_path).get(path)
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert "Strict-Transport-Security" not in response.headers
    # Script runs only as the print button's handler, allowed by its hash.
    assert "script-src 'unsafe-hashes' 'sha256-" in CONTENT_SECURITY_POLICY
    assert "'unsafe-inline'" not in CONTENT_SECURITY_POLICY.split("style-src")[0]


def test_hsts_is_sent_when_the_site_is_https(tmp_path: Path) -> None:
    response = _client(tmp_path, base_url="https://audit.example.com").get("/")
    assert response.headers["Strict-Transport-Security"].startswith("max-age=")


def test_no_page_carries_a_script(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path in ("/", "/en", "/ejemplo", "/sample", "/guias", "/terminos", "/privacidad"):
        assert _active_markup(client.get(path).text) == [], path


def test_the_print_handler_hash_matches_the_report_button() -> None:
    import base64
    import hashlib

    digest = base64.b64encode(hashlib.sha256(PRINT_HANDLER.encode()).digest()).decode()
    assert f"'sha256-{digest}'" in CONTENT_SECURITY_POLICY
    from quant_trade.audit.report import render
    from quant_trade.audit.sample import sample_result

    html_text, _ = render(sample_result("es"), watermark=False, free_mode=True)
    assert f"onclick='{PRINT_HANDLER}'" in html_text


def test_a_forged_host_header_is_not_echoed_into_links(tmp_path: Path) -> None:
    client = _client(tmp_path)
    forged = "evil.example'><b>x"
    for path in ("/", "/ejemplo", "/robots.txt", "/sitemap.xml"):
        text = client.get(path, headers={"host": forged}).text
        assert "evil.example" not in text, path


# ---------------------------------------------------------------------------
# Secrets: tokens and codes
# ---------------------------------------------------------------------------


def test_access_log_lines_never_carry_a_token_or_code() -> None:
    line = '1.2.3.4:5 - "GET /audits/abc?token=SECRET_T&lang=es&code=applied HTTP/1.1" 200'
    assert "SECRET_T" not in redact_secrets(line)
    assert redact_secrets("/audits/abc?lang=es&token=SECRET_T") == (
        "/audits/abc?lang=es&token=[redacted]"
    )
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/audits/abc?token=SECRET_T", "1.1", 200),
        None,
    )
    assert RedactSecretsFilter().filter(record)
    assert "SECRET_T" not in record.getMessage()
    config = uvicorn_log_config()
    assert "redact_secrets" in config["handlers"]["access"]["filters"]


def test_tokens_and_codes_have_enough_entropy(tmp_path: Path) -> None:
    response = _post(_client(tmp_path), _equity_upload())
    token = response.headers["location"].split("token=")[1]
    assert len(token) >= 43  # 32 random bytes, URL-safe base64
    code_bits = CODE_GROUPS * CODE_GROUP_LENGTH * np.log2(len(CODE_ALPHABET))
    assert code_bits > 58


class _TagScan(HTMLParser):
    """Collects every script tag and event-handler attribute a browser would run."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script":
            self.found.append(tag)
        self.found.extend(
            f"{tag}[{key}]"
            for key, value in attrs
            # The print button's handler is the one the policy allows by hash.
            if key.startswith("on") and not (key == "onclick" and value == PRINT_HANDLER)
        )


def _active_markup(page: str) -> list[str]:
    scan = _TagScan()
    scan.feed(page)
    return scan.found


def _published(client: TestClient, files: dict, **form) -> tuple[str, str, str]:
    created = client.post(
        "/audits",
        files=files,
        data={"consent": "on", **form},
        headers={"accept": "application/json"},
    ).json()
    audit_id, token = created["audit_id"], created["token"]
    public = client.post(
        f"/audits/{audit_id}/publish?token={token}", headers={"accept": "application/json"}
    ).json()
    return audit_id, token, public["public_id"]


def test_hostile_report_fields_are_escaped_everywhere(tmp_path: Path) -> None:
    text = synthetic_mt5_report(120)[2:].decode("utf-16-le")
    text = text.replace("SyntheticEA", XSS.replace("<", "&lt;").replace(">", "&gt;"))
    text = text.replace("<td>EURUSD</td>", "<td>EUR&lt;script&gt;x&lt;/script&gt;USD</td>")
    report = b"\xff\xfe" + text.encode("utf-16-le")
    client = _client(tmp_path)
    audit_id, token, public_id = _published(
        client, {"report": (XSS + ".htm", report, "text/html")}, description=XSS
    )
    pages = {
        "report": client.get(f"/audits/{audit_id}?token={token}").text,
        "report_en": client.get(f"/audits/{audit_id}?token={token}&lang=en").text,
        "verification": client.get(f"/v/{public_id}").text,
        "badge": client.get(f"/v/{public_id}/badge.svg").text,
    }
    for name, page in pages.items():
        assert _active_markup(page) == [], name
    for name in ("verification", "badge"):
        assert token not in pages[name]
        assert "alert(" not in pages[name]


def test_the_token_and_a_rejected_code_never_reach_public_or_error_pages(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    audit_id, token, public_id = _published(client, _equity_upload())
    code = "AUD-ZZZZ-ZZZZ-ZZZZ"
    wrong = client.get(f"/audits/{audit_id}?token=wrong{code}")
    assert wrong.status_code == 404 and code not in wrong.text
    verification = client.get(f"/v/{public_id}")
    assert token not in verification.text and audit_id not in verification.text


def test_the_audit_slot_settings_come_from_the_environment() -> None:
    settings = AuditSettings.from_env(
        {"AUDIT_MAX_CONCURRENT_AUDITS": "3", "AUDIT_QUEUE_SECONDS": "5"}
    )
    assert (settings.max_concurrent_audits, settings.audit_queue_seconds) == (3, 5)
    defaults = AuditSettings.from_env({})
    assert (defaults.max_concurrent_audits, defaults.audit_queue_seconds) == (2, 30)
    with pytest.raises(ValueError):
        AuditSettings(max_concurrent_audits=0)
