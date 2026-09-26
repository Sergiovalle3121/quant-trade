"""The private "Coherencia del archivo" page, offline, behind its switch."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in, synthetic_mt5_report

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import forensics_web  # noqa: E402
from quant_trade.audit.forensics import copy as words  # noqa: E402
from quant_trade.audit.forensics.results import (  # noqa: E402
    STATUS_INFO,
    STATUS_SIGNAL,
    CheckResult,
)
from quant_trade.audit.forensics.review import CHECK_ORDER, METHOD_VERSION  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "audit_imports"
MT4 = FIXTURES / "mt4_statement.htm"
STRIPE = {
    "stripe_secret_key": "sk_live_x",
    "stripe_webhook_secret": "whsec_test",
    "stripe_price_id": "price_x",
}
#: Text of the fixtures (account, name, expert) and words the page never prints.
NEVER = (
    "12345678",
    "Demo Trader",
    "FixtureEA",
    "Synthetic Broker",
    "limpio",
    "auténtico",
    "falso",
    "manipulado",
    "authentic",
    "fake",
    "manipulated",
    "genuine",
)
SLUGS = {"es": "coherencia", "en": "consistency", "pt": "coerencia"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, on: bool = True, **overrides):
    monkeypatch.setattr(forensics_web, "FORENSICS_ENABLED", on)
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100, **overrides
    )
    return signed_in(TestClient(create_app(settings, make_store(settings.database_url))))


def _id_and_token(location: str) -> tuple[str, str]:
    path, _, query = location.partition("?")
    return path.rsplit("/", 1)[1], query.split("token=")[1]


def _upload_report(client: TestClient, name: str, data: bytes) -> tuple[str, str]:
    files = {"report": (name, data, "text/html")}
    response = client.post("/audits", files=files, data={"consent": "on"}, follow_redirects=False)
    assert response.status_code == 303, response.text
    return _id_and_token(response.headers["location"])


def _upload_equity(client: TestClient, data: bytes) -> tuple[str, str]:
    files = {"equity": ("equity.csv", data, "text/csv")}
    response = client.post("/audits", files=files, data={"consent": "on"}, follow_redirects=False)
    assert response.status_code == 303, response.text
    return _id_and_token(response.headers["location"])


def _grid_csv(n_months: int = 96, seed: int = 1) -> bytes:
    """A year-by-month table of returns written as percentages."""
    values = np.random.default_rng(seed).normal(0.008, 0.03, n_months)
    lines = [",".join(["Year", *MONTHS])]
    for row in range(0, n_months, 12):
        chunk = values[row : row + 12]
        cells = [f"{v * 100:.2f}%" for v in chunk] + [""] * (12 - len(chunk))
        lines.append(",".join([str(2016 + row // 12), *cells]))
    return ("\n".join(lines) + "\n").encode()


def _text(page: str) -> str:
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", "", page, flags=re.S))


def _reports() -> list[tuple[str, bytes]]:
    return [("ReportTester.html", synthetic_mt5_report(days=120)), (MT4.name, MT4.read_bytes())]


def test_switch_off_registers_nothing_and_answers_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, on=False)
    audit_id, token = _upload_report(client, *_reports()[0])
    for slug in SLUGS.values():
        assert client.get(f"/audits/{audit_id}/{slug}?token={token}").status_code == 404
    assert not any("coherencia" in getattr(r, "path", "") for r in client.app.routes)


@pytest.mark.parametrize("report", _reports(), ids=["mt5_tester", "mt4_statement"])
def test_the_page_reads_in_three_languages_and_passes_the_guard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, report: tuple[str, bytes]
) -> None:
    client = _client(tmp_path, monkeypatch)
    audit_id, token = _upload_report(client, *report)
    for locale, slug in SLUGS.items():
        page = client.get(f"/audits/{audit_id}/{slug}?token={token}")
        assert page.status_code == 200, page.text
        assert "no-store" in page.headers["cache-control"]
        assert "noindex" in page.headers["x-robots-tag"]
        assert "<meta name='robots' content='noindex, nofollow'>" in page.text
        copy = words.COPY[locale]
        text = _text(page.text)
        assert f"<title>{copy['title']}</title>" in page.text
        assert copy["method"] in text
        assert copy["no_findings"] in text or copy["legit"] in text
        assert "forensics-1" in text and METHOD_VERSION in text
        for check_id in CHECK_ORDER:
            assert words.CHECK_NAMES[locale][check_id] in text, check_id
        for word in NEVER:
            assert word not in page.text, word
        assert find_claims(page.text) == []
        # The report's link back and the two other languages of this page.
        assert f"href='/audits/{audit_id}?token={token}&amp;lang={locale}'" in page.text
        for other, other_slug in SLUGS.items():
            if other != locale:
                alternate = f"/audits/{audit_id}/{other_slug}?token={token}&amp;lang={other}"
                assert alternate in page.text
        # ``?lang=`` overrides the path's language, as on the report.
        switched = client.get(f"/audits/{audit_id}/coherencia?token={token}&lang={locale}")
        assert f"<title>{copy['title']}</title>" in switched.text


def test_the_page_shows_family_format_and_figures_with_evidence_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    audit_id, token = _upload_report(client, MT4.name, MT4.read_bytes())
    page = client.get(f"/audits/{audit_id}/coherencia?token={token}").text
    text = _text(page)
    assert words.FAMILY_NAMES["es"]["mt4_statement"] in text
    assert "<code>mt4_statement_html</code>" in page
    assert "<span class='badge MEASURED'>Medido</span>" in page
    assert "<span class='badge DECLARED'>Declarado</span>" in page
    assert "class='badge fx-CLEAN'>Sin hallazgo</span>" in page
    assert "class='badge fx-NOT_MEASURED'>No medido</span>" in page
    assert "No se pudo medir:" in text
    assert words.COPY["es"]["no_calibration"] in text
    assert words.COPY["es"]["limits"].split("|")[0] in text


def test_unpaid_report_answers_402_until_marked_paid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch, free_mode=False, **STRIPE)
    audit_id, token = _upload_report(client, *_reports()[0])
    assert client.get(f"/audits/{audit_id}/coherencia?token={token}").status_code == 402
    store = client.app.state.store
    assert store.mark_paid(audit_id, stripe_session_id="cs_test_1", at=datetime.now(UTC))
    assert client.get(f"/audits/{audit_id}/coherencia?token={token}").status_code == 200


def test_wrong_token_is_404_and_a_purged_report_is_410(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    audit_id, token = _upload_report(client, *_reports()[0])
    # A stranger (no session) needs the token; the signed-in owner does not.
    stranger = TestClient(client.app)
    assert stranger.get(f"/audits/{audit_id}/coherencia?token=wrong").status_code == 404
    assert stranger.get(f"/audits/{audit_id}/coherencia").status_code == 404
    assert stranger.get(f"/audits/{audit_id}/coherencia?token={token}").status_code == 200
    assert client.get(f"/audits/{audit_id}/coherencia").status_code == 200
    assert client.get("/audits/nothere/coherencia?token=x").status_code == 404
    store = client.app.state.store
    later = datetime.now(UTC) + timedelta(days=45)
    assert store.purge_expired(later, retention_days=30) == 1
    assert client.get(f"/audits/{audit_id}/coherencia?token={token}").status_code == 410


def test_a_second_get_is_served_from_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    audit_id, token = _upload_report(client, *_reports()[0])
    calls: list[str | None] = []
    original = forensics_web.review

    def spy(data: bytes, **kwargs):
        calls.append(kwargs.get("source_format"))
        return original(data, **kwargs)

    monkeypatch.setattr(forensics_web, "review", spy)
    for lang in ("es", "en", "pt", "es"):
        assert client.get(f"/audits/{audit_id}/coherencia?token={token}&lang={lang}").status_code
    assert calls == ["mt5_tester_html"]
    cache = client.app.state.forensics_cache
    assert len(cache) == 1
    (key,) = list(cache._items)
    assert key[0] == audit_id and key[1] == METHOD_VERSION and len(key[2]) == 64


def test_no_free_slot_answers_503_with_a_retry_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    audit_id, token = _upload_report(client, *_reports()[0])

    async def no_slot(slots, wait_seconds: float) -> bool:
        return False

    monkeypatch.setattr(forensics_web, "_acquire", no_slot)
    page = client.get(f"/audits/{audit_id}/consistency?token={token}")
    assert page.status_code == 503
    assert words.COPY["en"]["busy"] in _text(page.text)
    assert find_claims(page.text) == []


def test_uncached_reviews_are_limited_per_address(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(forensics_web, "MAX_REVIEWS_PER_IP_PER_HOUR", 2)
    client = _client(tmp_path, monkeypatch)
    ids = [_upload_report(client, "r.html", synthetic_mt5_report(days=d)) for d in (60, 61, 62)]
    first = client.get(f"/audits/{ids[0][0]}/coherencia?token={ids[0][1]}")
    second = client.get(f"/audits/{ids[1][0]}/coherencia?token={ids[1][1]}")
    third = client.get(f"/audits/{ids[2][0]}/coerencia?token={ids[2][1]}")
    assert (first.status_code, second.status_code, third.status_code) == (200, 200, 429)
    assert words.COPY["pt"]["too_many"] in _text(third.text)
    # Cached pages stay free while the limit holds.
    assert client.get(f"/audits/{ids[0][0]}/coherencia?token={ids[0][1]}").status_code == 200


def test_a_stored_file_whose_digest_moved_is_not_reviewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    audit_id, token = _upload_report(client, *_reports()[0])
    monkeypatch.setattr(forensics_web, "digest_matches", lambda record, name, blob: False)
    monkeypatch.setattr(
        forensics_web, "review", lambda *a, **k: pytest.fail("the battery must not run")
    )
    page = client.get(f"/audits/{audit_id}/coherencia?token={token}")
    assert page.status_code == 200
    assert words.COPY["es"]["digest_mismatch"] in _text(page.text)
    assert find_claims(page.text) == []


def test_digest_matches_compares_the_blob_with_the_recorded_sha256() -> None:
    import hashlib

    class Record:
        digests = {"report.html": hashlib.sha256(b"abc").hexdigest()}

    assert forensics_web.digest_matches(Record(), "report.html", b"abc")
    assert not forensics_web.digest_matches(Record(), "report.html", b"abd")
    assert not forensics_web.digest_matches(Record(), "report.xlsx", b"abc")


def test_an_equity_curve_alone_has_nothing_to_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    audit_id, token = _upload_equity(client, csv_bytes(positive_drift(300)))
    page = client.get(f"/audits/{audit_id}/coherencia?token={token}")
    assert page.status_code == 200
    assert words.COPY["es"]["nothing_to_review"] in _text(page.text)
    assert find_claims(page.text) == []


def test_a_monthly_table_is_reviewed_as_the_monthly_family(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    audit_id, token = _upload_equity(client, _grid_csv())
    page = client.get(f"/audits/{audit_id}/consistency?token={token}")
    assert page.status_code == 200, page.text
    text = _text(page.text)
    assert words.FAMILY_NAMES["en"]["monthly"] in text
    assert words.CHECK_NAMES["en"]["MONTHLY_DIGITS"] in text
    assert find_claims(page.text) == []


def test_stored_target_prefers_the_report_then_live_then_equity() -> None:
    class Record:
        def __init__(self, files, equity=None):
            self.files = files
            self.equity_csv = equity

    assert forensics_web.stored_target(Record({"live.csv": b"l", "report.xlsx": b"r"})) == (
        "report.xlsx",
        b"r",
    )
    assert forensics_web.stored_target(Record({"live.csv": b"l", "optimization.xml": b"o"})) == (
        "live.csv",
        b"l",
    )
    assert forensics_web.stored_target(Record({}, b"e")) == ("equity.csv", b"e")
    assert forensics_web.stored_target(Record({}, None)) is None
    assert forensics_web.stored_target(Record(None, b"")) is None


@pytest.mark.parametrize("locale", words.LOCALES)
def test_finding_sentences_and_notes_pass_the_guard(locale: str) -> None:
    signal = CheckResult(
        id="BALANCE_CHAIN",
        status=STATUS_SIGNAL,
        figures=(("n_rows", "99999", "MEASURED"), ("n_hits", "3", "MEASURED")),
        examples=(3, 7, 12),
        applies=True,
        calibration=(("n", "24"), ("unexplained", "0"), ("cp95_upper_pct", "14.2")),
    )
    sentence = forensics_web.finding_sentence(signal, locale)
    assert sentence.startswith(words.CHECK_FACTS[locale]["BALANCE_CHAIN"].split("{")[0])
    assert sentence.endswith(words.COPY[locale]["legit"])
    assert find_claims(sentence) == []
    for check_id in CHECK_ORDER:
        info = CheckResult(
            id=check_id,
            status=STATUS_INFO,
            figures=(("n_rows", "1", "MEASURED"), ("n_hits", "1", "MEASURED")),
            applies=True,
        )
        text = forensics_web.finding_sentence(info, locale)
        assert words.COPY[locale]["legit"] in text
        assert "{" not in text and find_claims(text) == [], check_id
    for note in ("nothing_to_review", "digest_mismatch", "review_failed", "busy", "too_many"):
        page = forensics_web.render_note(note, locale=locale, audit_id="abc", token=None)
        assert words.COPY[locale][note] in _text(page)
        assert words.COPY[locale]["method"] in _text(page)
        assert "href='/audits/abc?lang=" in page and "token=" not in page
        assert find_claims(page) == []


def test_source_format_is_read_from_the_result_json() -> None:
    class Record:
        result_json = '{"inputs": {"source_format": "mt4_statement_html"}}'

    class Empty:
        result_json = None

    class Broken:
        result_json = "{not json"

    assert forensics_web.source_format_of(Record()) == "mt4_statement_html"
    assert forensics_web.source_format_of(Empty()) is None
    assert forensics_web.source_format_of(Broken()) is None


def test_the_result_cache_is_an_lru_of_bounded_size() -> None:
    cache = forensics_web.ResultCache(size=2)
    marker = object()
    cache.put(("a", METHOD_VERSION, "1"), marker)  # type: ignore[arg-type]
    cache.put(("b", METHOD_VERSION, "2"), marker)  # type: ignore[arg-type]
    assert cache.get(("a", METHOD_VERSION, "1")) is marker
    cache.put(("c", METHOD_VERSION, "3"), marker)  # type: ignore[arg-type]
    assert cache.get(("b", METHOD_VERSION, "2")) is None  # the least recently used went
    assert cache.get(("a", METHOD_VERSION, "1")) is marker
    assert len(cache) == 2
