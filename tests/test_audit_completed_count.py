"""The public counter counts evidenced completions, never fixtures or guesses."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from quant_trade.audit.completed_count import (  # noqa: E402
    CACHE_SECONDS,
    CompletedAuditCounter,
    completed_count_html,
)
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.store import Store, make_store  # noqa: E402

NOW = datetime(2026, 10, 7, tzinfo=UTC)


def _create(store: Store, audit_id: str, **changes) -> None:
    values = {
        "audit_id": audit_id,
        "created_at": NOW,
        "token_hash": "h" * 64,
        "client_ip": "",
        "declared_json": "{}",
        "result_json": f'{{"audit_id": "{audit_id}"}}',
        "report_html": "<html>completed report</html>",
        "overall_class": "C",
        "digests": {"equity.csv": "e" * 64},
        "equity_csv": b"timestamp,equity\n",
    }
    values.update(changes)
    store.create_audit(**values)


def test_completed_count_excludes_unknown_samples_tests_and_incomplete(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/counter.db")
    _create(store, "legacy-or-fixture")
    _create(store, "sample", public_count_eligible=True)
    _create(store, "operator-test", public_count_eligible=True)
    _create(store, "incomplete", public_count_eligible=True, result_json="")
    _create(store, "no-report", public_count_eligible=True, report_html="")
    _create(store, "no-class", public_count_eligible=True, overall_class="")
    _create(store, "customer", public_count_eligible=True)

    assert store.count_audits() == 7
    assert store.count_completed_audits(excluded_ids=("operator-test",)) == 1
    assert store.count_completed_audits() == 2


def test_completed_count_preserves_completions_after_purge_and_ignores_deletions(
    tmp_path: Path,
) -> None:
    store = make_store(f"sqlite:///{tmp_path}/counter.db")
    _create(store, "kept", public_count_eligible=True)
    _create(store, "deleted", public_count_eligible=True)
    _create(store, "unknown-purged")
    with store.engine.begin() as connection:
        connection.execute(
            store.audits.update()
            .where(store.audits.c.id.in_(("kept", "unknown-purged")))
            .values(result_json=None, report_html=None, purged_at="2026-10-08T00:00:00Z")
        )
        connection.execute(store.audits.delete().where(store.audits.c.id == "deleted"))

    assert store.count_completed_audits() == 1


def test_eligibility_is_additive_and_does_not_backfill_existing_database(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path}/counter.db"
    old_store = make_store(url)
    _create(old_store, "legacy")
    old_store.audit_count_eligibility.drop(old_store.engine)
    old_store.engine.dispose()

    new_store = make_store(url)
    assert new_store.count_audits() == 1
    assert new_store.count_completed_audits() == 0
    _create(new_store, "customer", public_count_eligible=True)
    assert new_store.count_completed_audits() == 1


def test_delete_cleans_eligibility_and_reused_id_does_not_inherit_it(tmp_path: Path) -> None:
    store = make_store(f"sqlite:///{tmp_path}/counter.db")
    _create(store, "customer", public_count_eligible=True)
    assert store.count_completed_audits() == 1
    assert store.delete_audit("customer") is True
    with store.engine.connect() as connection:
        assert connection.execute(store.audit_count_eligibility.select()).first() is None

    _create(store, "customer")
    assert store.count_completed_audits() == 0
    assert store.delete_audit("customer") is True
    _create(store, "customer", public_count_eligible=True)
    assert store.count_completed_audits() == 1


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
def test_counter_threshold_and_guard_with_test_store(tmp_path: Path, locale: str) -> None:
    store = make_store(f"sqlite:///{tmp_path}/counter.db")
    for index in range(24):
        _create(store, f"customer-{index}", public_count_eligible=True)
    assert completed_count_html(store.count_completed_audits(), locale) == ""

    _create(store, "customer-24", public_count_eligible=True)
    html = completed_count_html(store.count_completed_audits(), locale)
    expected = "25 backtests audited" if locale == "en" else "25 backtests auditados"
    assert expected in html
    assert 'data-evidence="MEASURED"' in html
    assert ">MEASURED</span>" in html
    assert find_claims(html) == []


@pytest.mark.parametrize("total", (None, -1, 0, 24, True, 25.5, "25"))
def test_absent_or_invalid_totals_render_nothing(total) -> None:
    assert completed_count_html(total) == ""


class _Clock:
    now = 0.0

    def __call__(self) -> float:
        return self.now


class _CountingStore:
    def __init__(self) -> None:
        self.total = 24
        self.calls = 0
        self.excluded: Sequence[str] = ()
        self.unavailable = False

    def count_completed_audits(self, *, excluded_ids: Sequence[str] = ()) -> int:
        self.calls += 1
        self.excluded = excluded_ids
        if self.unavailable:
            raise RuntimeError("database unavailable")
        return self.total


def test_cache_refreshes_after_ten_minutes_and_passes_test_exclusions() -> None:
    store, clock = _CountingStore(), _Clock()
    counter = CompletedAuditCounter(store, clock=clock, excluded_ids={"operator-test"})
    assert counter.get() == 24
    assert store.excluded == ("operator-test",)
    store.total = 25
    clock.now = CACHE_SECONDS - 0.001
    assert counter.get() == 24
    assert store.calls == 1
    clock.now = CACHE_SECONDS
    assert counter.get() == 25
    assert store.calls == 2


def test_cache_is_per_store_and_failure_hides_stale_total_until_next_refresh() -> None:
    first, second, clock = _CountingStore(), _CountingStore(), _Clock()
    first.total = 25
    first_counter = CompletedAuditCounter(first, clock=clock)
    second_counter = CompletedAuditCounter(second, clock=clock)
    assert first_counter.get() == 25
    assert second_counter.get() == 24
    first.unavailable = True
    clock.now = CACHE_SECONDS
    assert first_counter.get() is None
    assert completed_count_html(first_counter.get()) == ""
    assert first.calls == 2
    first.unavailable = False
    first.total = 26
    clock.now = CACHE_SECONDS * 2
    assert first_counter.get() == 26
    assert first.calls == 3


def test_home_pages_use_one_cached_store_count_and_exclude_operator_tests(tmp_path: Path) -> None:
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from quant_trade.audit.report import evidence_label
    from quant_trade.audit.settings import AuditSettings
    from quant_trade.audit.web import create_app

    store = make_store(f"sqlite:///{tmp_path}/counter.db")
    for index in range(24):
        _create(store, f"customer-{index}", public_count_eligible=True)
    _create(store, "operator-test", public_count_eligible=True)
    _create(store, "sample", public_count_eligible=True)
    _create(store, "fixture")
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/counter.db",
        stripe_test_audits=frozenset({"operator-test"}),
    )
    app = create_app(settings, store)
    clock = _Clock()
    app.state.completed_counter._clock = clock
    client = TestClient(app)
    for path in ("/", "/en", "/pt"):
        response = client.get(path)
        assert response.status_code == 200
        assert 'class="completed-count"' not in response.text

    _create(store, "customer-24", public_count_eligible=True)
    assert 'class="completed-count"' not in client.get("/").text
    clock.now = CACHE_SECONDS
    for path, text, locale in (
        ("/", "25 backtests auditados", "es"),
        ("/en", "25 backtests audited", "en"),
        ("/pt", "25 backtests auditados", "pt"),
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert text in response.text
        label = evidence_label("MEASURED", locale)
        assert f'{text} <span class="tag MEASURED">{label}</span>' in response.text
        assert find_claims(response.text) == []
