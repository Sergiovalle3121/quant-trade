"""A spent code or credit always answers with its report, even if the account list fails."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in
from fastapi.testclient import TestClient

from quant_trade.audit import accounts as acct
from quant_trade.audit import pdf as pdf_lib
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import VIA_PAID, make_store
from quant_trade.audit.web import create_app

WARNING = "could not link a delivered report to the account"
PRIVATE = "synthetic SQL params password-value customer@example.test"


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setattr(pdf_lib, "available", lambda: False)
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _upload(client: TestClient, *, json_response: bool = False, **data: str) -> Any:
    return client.post(
        "/audits",
        files={"equity": ("synthetic.csv", csv_bytes(positive_drift(300)), "text/csv")},
        data={"consent": "on", **data},
        headers={"Accept": "application/json"} if json_response else {},
        follow_redirects=False,
    )


def _id_and_token(location: str) -> tuple[str, str]:
    parsed = urlsplit(location)
    return parsed.path.rsplit("/", 1)[1], parse_qs(parsed.query)["token"][0]


def _fail(*args: Any, **kwargs: Any) -> None:
    raise RuntimeError(PRIVATE)


def _assert_quiet_warning(caplog: pytest.LogCaptureFixture) -> None:
    assert WARNING in caplog.text
    assert PRIVATE not in caplog.text
    assert "password-value" not in caplog.text and "customer@example.test" not in caplog.text


@pytest.mark.parametrize("json_response", [False, True])
@pytest.mark.parametrize("failing", ["link_audit", "get_audit"])
@pytest.mark.parametrize("payment", ["code", "credit"])
def test_link_failure_after_redeeming_on_upload_still_returns_id_and_token(
    tmp_path, monkeypatch, caplog, payment: str, failing: str, json_response: bool
) -> None:
    with _client(tmp_path, monkeypatch) as client:
        signed_in(client)
        store = client.app.state.store
        account = store.find_account("tester@example.com")
        assert account is not None
        now = datetime.now(UTC)
        code, record = store.create_access_code(credits=1, note="synthetic", at=now)
        data = {"access_code": code} if payment == "code" else {}
        if payment == "credit":
            store.link_code(account.id, record.id, at=now)
            # With the month's previews used, the next upload spends the account credit.
            for _ in range(acct.FREE_PREVIEWS_PER_MONTH):
                assert _upload(client).status_code == 303
        before = store.count_audits()
        with monkeypatch.context() as patch:
            patch.setattr(store, failing, _fail)
            response = _upload(client, json_response=json_response, **data)
        assert response.status_code == (201 if json_response else 303)
        location = response.json()["location"] if json_response else response.headers["location"]
        audit_id, token = _id_and_token(location)
        assert len(token) >= 32
        if json_response:
            assert response.json()["audit_id"] == audit_id
            assert response.json()["token"] == token
        assert ("code=applied" if payment == "code" else "acct=upload_credit") in location
        paid = store.get_audit(audit_id)
        assert paid is not None and paid.paid
        assert store.count_audits() == before + 1
        assert store.get_access_code(code).credits_used == 1
        assert store.account_credits(account.id, datetime.now(UTC)) == 0
        # Only the account list lags: the report itself opens unlocked with its token.
        listed = [item.audit_id for item in store.account_audits_list(account.id)]
        assert audit_id not in listed
        report = client.get(location)
        assert report.status_code == 200 and "class='lockbox'" not in report.text
    _assert_quiet_warning(caplog)


@pytest.mark.parametrize("route", ["redeem", "credit"])
def test_link_failure_after_unlocking_from_the_report_still_answers(
    tmp_path, monkeypatch, caplog, route: str
) -> None:
    with _client(tmp_path, monkeypatch) as client:
        signed_in(client)
        store = client.app.state.store
        account = store.find_account("tester@example.com")
        assert account is not None
        preview = _upload(client)
        assert preview.status_code == 303
        audit_id, token = _id_and_token(preview.headers["location"])
        locked = store.get_audit(audit_id)
        assert locked is not None and not locked.paid
        now = datetime.now(UTC)
        code, record = store.create_access_code(credits=1, note="synthetic", at=now)
        if route == "redeem":
            data = {"code": code}
        else:
            store.link_code(account.id, record.id, at=now)
            page = client.get(preview.headers["location"]).text
            csrf = re.search(r"name='csrf' value='([^']+)'", page)
            assert csrf is not None
            data = {"csrf": csrf.group(1)}
        original = store.link_audit

        def fail_paid_link(*args: Any, **kwargs: Any) -> Any:
            # Saving the report before the credit is spent still works; only the
            # link after payment fails.
            if kwargs.get("via") == VIA_PAID:
                raise RuntimeError(PRIVATE)
            return original(*args, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(store, "link_audit", fail_paid_link)
            response = client.post(
                f"/audits/{audit_id}/{route}?token={token}", data=data, follow_redirects=False
            )
        assert response.status_code == 303
        location = response.headers["location"]
        assert _id_and_token(location) == (audit_id, token)
        assert ("code=applied" if route == "redeem" else "acct=credit") in location
        paid = store.get_audit(audit_id)
        assert paid is not None and paid.paid
        assert store.get_access_code(code).credits_used == 1
        report = client.get(location)
        assert report.status_code == 200 and "class='lockbox'" not in report.text
    _assert_quiet_warning(caplog)
