"""Optional column preferences must not strand an already paid audit."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in
from fastapi.testclient import TestClient

from quant_trade.audit import mapping
from quant_trade.audit import pdf as pdf_lib
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.web import create_app

HEADERS = ["SessionDate", "EndOfDayEquity"]
CHOSEN = {"col_date": HEADERS[0], "col_balance": HEADERS[1]}
WARNING = "could not save upload column mapping"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(pdf_lib, "available", lambda: False)
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _files() -> dict[str, tuple[str, bytes, str]]:
    curve = positive_drift(300).rename(columns={"timestamp": HEADERS[0], "equity": HEADERS[1]})
    return {"report": ("synthetic-curve.csv", csv_bytes(curve), "text/csv")}


@pytest.mark.parametrize("json_response", [False, True])
@pytest.mark.parametrize("failure", ["save", "read_after_store"])
def test_preference_failure_delivers_paid_report_and_links_account(
    tmp_path, monkeypatch, caplog, json_response: bool, failure: str
) -> None:
    with _client(tmp_path, monkeypatch) as client:
        signed_in(client)
        store = client.app.state.store
        account = store.find_account("tester@example.com")
        assert account is not None
        code, _ = store.create_access_code(credits=1, note="synthetic", at=datetime.now(UTC))
        private_detail = "synthetic SQL params password-value customer@example.test"

        def failed_save(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError(private_detail)

        if failure == "save":
            monkeypatch.setattr(store, "save_column_map", failed_save)
        else:
            original_read = mapping.read_table

            def failed_optional_read(*args: Any, **kwargs: Any) -> Any:
                if store.count_audits():
                    raise RuntimeError(private_detail)
                return original_read(*args, **kwargs)

            monkeypatch.setattr(mapping, "read_table", failed_optional_read)
        response = client.post(
            "/audits",
            files=_files(),
            data={"consent": "on", "access_code": code, **CHOSEN},
            headers={"Accept": "application/json"} if json_response else {},
            follow_redirects=False,
        )
        assert response.status_code == (201 if json_response else 303)
        location = response.json()["location"] if json_response else response.headers["location"]
        parsed = urlsplit(location)
        audit_id = parsed.path.rsplit("/", 1)[1]
        token = parse_qs(parsed.query)["token"][0]
        assert len(token) >= 32
        if json_response:
            assert response.json()["audit_id"] == audit_id
            assert response.json()["token"] == token
        audit = store.get_audit(audit_id)
        assert audit is not None and audit.paid
        assert store.get_access_code(code).credits_used == 1
        assert store.count_audits() == 1
        linked = store.account_audits_list(account.id)
        assert len(linked) == 1 and linked[0].audit_id == audit_id and linked[0].own
        assert client.get(location).status_code == 200
        assert client.get(parsed.path).status_code == 200
        assert store.get_access_code(code).credits_used == 1
        assert store.column_map(account.id, mapping.header_signature(HEADERS)) is None
    assert WARNING in caplog.text
    assert private_detail not in caplog.text
    assert "password-value" not in caplog.text and "customer@example.test" not in caplog.text


def test_successful_column_preference_is_saved_and_reused(tmp_path, monkeypatch) -> None:
    with _client(tmp_path, monkeypatch) as client:
        signed_in(client)
        store = client.app.state.store
        account = store.find_account("tester@example.com")
        assert account is not None
        code, _ = store.create_access_code(credits=1, note="synthetic", at=datetime.now(UTC))
        response = client.post(
            "/audits",
            files=_files(),
            data={"consent": "on", "access_code": code, **CHOSEN},
            follow_redirects=False,
        )
        assert response.status_code == 303
        saved = store.column_map(account.id, mapping.header_signature(HEADERS))
        assert mapping.loads(saved) == {"date": HEADERS[0], "balance": HEADERS[1]}
        again = client.post(
            "/audits", files=_files(), data={"consent": "on"}, follow_redirects=False
        )
        assert again.status_code == 303
        assert store.count_audits() == 2
        assert store.get_access_code(code).credits_used == 1


def test_audit_storage_failure_is_not_swallowed_by_optional_preference_guard(
    tmp_path, monkeypatch, caplog
) -> None:
    with _client(tmp_path, monkeypatch) as client:
        signed_in(client)
        store = client.app.state.store
        code, _ = store.create_access_code(credits=1, note="synthetic", at=datetime.now(UTC))

        def fail_storage(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("synthetic core audit storage unavailable")

        def forbidden_preference(*args: Any, **kwargs: Any) -> None:
            pytest.fail("a failed audit must not reach optional preference persistence")

        monkeypatch.setattr(store, "create_audit", fail_storage)
        monkeypatch.setattr(store, "save_column_map", forbidden_preference)
        response = client.post(
            "/audits",
            files=_files(),
            data={"consent": "on", "access_code": code, **CHOSEN},
            follow_redirects=False,
        )
        assert response.status_code == 500
        assert "location" not in response.headers
        assert store.count_audits() == 0
        assert store.get_access_code(code).credits_used == 0
    assert WARNING not in caplog.text
