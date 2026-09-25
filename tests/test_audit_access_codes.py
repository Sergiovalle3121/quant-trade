"""Access codes: stored hashed, printed once, redeemed atomically."""

from __future__ import annotations

import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift, signed_in

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import (  # noqa: E402
    CODE_REFERENCE_PREFIX,
    hash_access_code,
    make_store,
    new_access_code,
    normalise_access_code,
)
from quant_trade.audit.web import create_app  # noqa: E402
from quant_trade.cli import app  # noqa: E402

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)
CODE_SHAPE = re.compile(r"^AUD-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}$")


def _store(tmp_path: Path):
    return make_store(f"sqlite:///{tmp_path}/audit.db")


def _insert_audit(store, audit_id: str, *, code: str | None = None, at: datetime = NOW) -> bool:
    return store.create_audit(
        audit_id=audit_id,
        created_at=at,
        token_hash="t" * 64,
        client_ip="1.2.3.4",
        declared_json="{}",
        result_json="{}",
        report_html="<html></html>",
        overall_class="C",
        digests={"equity.csv": "e" * 64},
        equity_csv=b"x",
        access_code=code,
    )


def test_codes_have_the_documented_shape_and_normalise() -> None:
    code = new_access_code()
    assert CODE_SHAPE.match(code)
    assert new_access_code() != code
    typed = " " + code.lower().replace("-", " ") + " "
    assert normalise_access_code(typed) == normalise_access_code(code)
    assert normalise_access_code(code[4:]) == normalise_access_code(code)
    assert hash_access_code(typed) == hash_access_code(code)


def test_the_clear_code_is_never_stored(tmp_path: Path) -> None:
    store = _store(tmp_path)
    code, record = store.create_access_code(credits=2, note="transfer 42", at=NOW)
    assert record.credits_left == 2
    with store.engine.connect() as conn:
        rows = [tuple(row) for row in conn.execute(store.access_codes.select())]
    dumped = repr(rows)
    assert code not in dumped
    assert normalise_access_code(code) not in dumped
    assert hash_access_code(code) in dumped
    listed = store.list_access_codes()
    assert [item.id for item in listed] == [record.id]
    assert code not in repr(listed)


def test_a_code_spends_exactly_its_credits(tmp_path: Path) -> None:
    store = _store(tmp_path)
    code, record = store.create_access_code(credits=2, note="", at=NOW)
    assert _insert_audit(store, "a1", code=code) is True
    assert _insert_audit(store, "a2", code=code.lower()) is True
    assert _insert_audit(store, "a3", code=code) is False
    paid = store.get_audit("a1")
    assert paid is not None and paid.paid
    assert paid.stripe_session_id == CODE_REFERENCE_PREFIX + record.id
    unpaid = store.get_audit("a3")
    assert unpaid is not None and not unpaid.paid and unpaid.stripe_session_id is None
    assert store.list_access_codes()[0].credits_used == 2


def test_unknown_expired_and_disabled_codes_are_refused(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert _insert_audit(store, "u1", code="AUD-XXXX-XXXX-XXXX") is False
    assert _insert_audit(store, "u2", code="   ") is False
    expiring, _ = store.create_access_code(credits=5, note="", at=NOW, expires_days=1)
    assert _insert_audit(store, "e1", code=expiring, at=NOW + timedelta(hours=23)) is True
    assert _insert_audit(store, "e2", code=expiring, at=NOW + timedelta(days=2)) is False
    leaked, record = store.create_access_code(credits=5, note="", at=NOW)
    assert store.disable_access_code(record.id) is True
    assert store.disable_access_code(record.id) is False
    assert _insert_audit(store, "d1", code=leaked) is False
    with pytest.raises(ValueError):
        store.create_access_code(credits=0, note="", at=NOW)


def test_redeeming_for_an_existing_audit_is_atomic(tmp_path: Path) -> None:
    store = _store(tmp_path)
    code, _ = store.create_access_code(credits=1, note="", at=NOW)
    _insert_audit(store, "r1")
    _insert_audit(store, "r2")
    assert store.redeem_for_audit("missing", code, at=NOW) is False
    assert store.redeem_for_audit("r1", code, at=NOW) is True
    # Already paid: nothing is spent.
    assert store.redeem_for_audit("r1", code, at=NOW) is False
    assert store.redeem_for_audit("r2", code, at=NOW) is False
    assert store.list_access_codes()[0].credits_used == 1


def test_concurrent_redemptions_never_overspend(tmp_path: Path) -> None:
    store = _store(tmp_path)
    code, _ = store.create_access_code(credits=3, note="", at=NOW)
    for index in range(12):
        _insert_audit(store, f"c{index}")
    wins: list[bool] = []
    lock = threading.Lock()

    def attempt(audit_id: str) -> None:
        try:
            won = store.redeem_for_audit(audit_id, code, at=NOW)
        except Exception:  # sqlite may report "database is locked" under contention
            won = False
        with lock:
            wins.append(won)

    threads = [threading.Thread(target=attempt, args=(f"c{i}",)) for i in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    used = store.list_access_codes()[0].credits_used
    assert used == sum(wins) <= 3
    paid = [store.get_audit(f"c{i}") for i in range(12)]
    assert sum(1 for record in paid if record is not None and record.paid) == used


def test_settings_turn_on_code_sales_only_on_request() -> None:
    assert AuditSettings.from_env({}).free_mode is True
    only_codes = AuditSettings.from_env({"AUDIT_ACCESS_CODES": "true"})
    assert only_codes.free_mode is True and not only_codes.access_codes_enabled
    selling = AuditSettings.from_env(
        {
            "AUDIT_ACCESS_CODES": "true",
            "AUDIT_FREE_MODE": "false",
            "AUDIT_CONTACT_URL": "https://wa.me/000",
        }
    )
    assert selling.free_mode is False and selling.access_codes_enabled
    assert not selling.stripe_enabled
    assert selling.contact_url == "https://wa.me/000"
    # Without codes and without Stripe, free mode is still forced.
    assert AuditSettings.from_env({"AUDIT_FREE_MODE": "false"}).free_mode is True
    assert AuditSettings.from_env({"AUDIT_CONTACT_URL": "javascript:alert(1)"}).contact_url == ""


def test_cli_prints_a_code_once_and_lists_without_it(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/audit.db")
    runner = CliRunner()
    created = runner.invoke(
        app,
        ["audit", "codes", "create", "--credits", "3", "--note", "demo", "--expires-days", "30"],
    )
    assert created.exit_code == 0, created.output
    code = created.stdout.strip().splitlines()[0]
    assert CODE_SHAPE.match(code)
    listed = runner.invoke(app, ["audit", "codes", "list"])
    assert listed.exit_code == 0, listed.output
    assert "demo" in listed.output
    assert code not in listed.output
    assert normalise_access_code(code) not in listed.output
    record = make_store(f"sqlite:///{tmp_path}/audit.db").list_access_codes()[0]
    assert record.credits_total == 3 and record.expires_at is not None
    disabled = runner.invoke(app, ["audit", "codes", "disable", record.id])
    assert disabled.exit_code == 0
    again = runner.invoke(app, ["audit", "codes", "disable", record.id])
    assert again.exit_code == 1


def _selling_client(tmp_path: Path) -> tuple[TestClient, object]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
        contact_url="https://wa.me/000",
    )
    store = make_store(settings.database_url)
    return signed_in(TestClient(create_app(settings, store))), store


def _upload(client: TestClient, **data):
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    payload = {"trials": "3", "cost_bps": "5", "consent": "on", **data}
    return client.post("/audits", files=files, data=payload, follow_redirects=False)


def test_an_upload_with_a_code_is_born_paid(tmp_path: Path) -> None:
    client, store = _selling_client(tmp_path)
    landing = client.get("/")
    assert "name='access_code'" in landing.text and "https://wa.me/000" in landing.text
    code, _ = store.create_access_code(credits=1, note="", at=NOW)  # type: ignore[attr-defined]
    response = _upload(client, access_code=code)
    assert response.status_code == 303
    location = response.headers["location"]
    assert location.endswith("&code=applied")
    page = client.get(location)
    assert "class='lockbox'" not in page.text and "VISTA PREVIA" not in page.text
    assert "Código de acceso aplicado" in page.text
    assert find_claims(page.text) == []
    # The credit is spent: the same code now yields a preview.
    second = _upload(client, access_code=code)
    assert second.headers["location"].endswith("&code=rejected#canjear")
    preview = client.get(second.headers["location"])
    assert "class='lockbox'" in preview.text and "Ese código no desbloqueó" in preview.text
    assert "/redeem?token=" in preview.text
    assert find_claims(preview.text) == []
    # A client without a working code is told where to buy one, and the price.
    buy = preview.text.split("<div class='paybox buy'>", 1)[1].split("</div></div>", 1)[0]
    assert "<b>USD 49</b>" in buy and "Comprar por WhatsApp" in buy
    # The way to buy comes before the field for a code already bought.
    assert preview.text.index("paybox buy") < preview.text.index("id='redeem-code'")
    assert "href='https://wa.me/000?text=" in preview.text
    # The header of a locked preview offers the unlock, not printing a watermarked page.
    header = preview.text.split("<header", 1)[1].split("</header>", 1)[0]
    assert "href='#unlock'" in header and "window.print()" not in header
    # Engine and seed chips step aside on phones so the verdict comes first.
    assert preview.text.count("class='meta-x'") == 2
    assert client.get("/health").json()["access_codes"] is True
    # Tables scroll inside the page on a phone instead of widening it.
    for text in (landing.text, preview.text):
        assert "table{display:block;overflow-x:auto}" in text


def test_an_invalid_code_gives_a_preview_and_the_json_says_so(tmp_path: Path) -> None:
    client, _ = _selling_client(tmp_path)
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")}
    response = client.post(
        "/audits",
        files=files,
        data={"consent": "on", "access_code": "AUD-NOPE-NOPE-NOPE"},
        headers={"accept": "application/json"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["access_code"] == "rejected"
    locked = client.get(f"/audits/{body['audit_id']}.json?token={body['token']}")
    assert locked.status_code == 402


def test_a_code_unlocks_an_existing_preview(tmp_path: Path) -> None:
    client, store = _selling_client(tmp_path)
    response = _upload(client)
    location = response.headers["location"]
    audit_id = location.split("/audits/")[1].split("?")[0]
    token = location.split("token=")[1]
    wrong = client.post(
        f"/audits/{audit_id}/redeem?token={token}", data={"code": "x"}, follow_redirects=False
    )
    assert wrong.headers["location"].endswith("&code=rejected")
    code, _ = store.create_access_code(credits=1, note="", at=NOW)  # type: ignore[attr-defined]
    client.cookies.clear()  # a stranger: no account, a wrong token
    stranger = client.post(f"/audits/{audit_id}/redeem?token=bad", data={"code": code})
    assert stranger.status_code == 404
    right = client.post(
        f"/audits/{audit_id}/redeem?token={token}", data={"code": code}, follow_redirects=False
    )
    assert right.headers["location"].endswith("&code=applied")
    assert client.get(f"/audits/{audit_id}.json?token={token}").status_code == 200


def test_redeem_attempts_count_toward_the_hourly_limit(tmp_path: Path) -> None:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        free_mode=False,
        access_codes=True,
        max_uploads_per_hour_per_ip=3,
    )
    client = signed_in(TestClient(create_app(settings, make_store(settings.database_url))))
    location = _upload(client).headers["location"]
    audit_id = location.split("/audits/")[1].split("?")[0]
    token = location.split("token=")[1]
    url = f"/audits/{audit_id}/redeem?token={token}"
    statuses = [
        client.post(url, data={"code": f"AUD-{i}"}, follow_redirects=False).status_code
        for i in range(4)
    ]
    assert statuses == [303, 303, 429, 429]


def test_free_mode_ignores_codes_and_spends_nothing(tmp_path: Path) -> None:
    settings = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100)
    store = make_store(settings.database_url)
    client = signed_in(TestClient(create_app(settings, store)))
    assert "name='access_code'" not in client.get("/").text
    code, _ = store.create_access_code(credits=1, note="", at=NOW)
    response = _upload(client, access_code=code)
    assert "code=" not in response.headers["location"]
    assert store.list_access_codes()[0].credits_used == 0
    location = response.headers["location"]
    audit_id = location.split("/audits/")[1].split("?")[0]
    token = location.split("token=")[1]
    redeem = client.post(f"/audits/{audit_id}/redeem?token={token}", data={"code": code})
    assert redeem.status_code == 404


def test_every_buy_box_lists_what_the_payment_unlocks(tmp_path: Path) -> None:
    from quant_trade.audit.guard import find_claims
    from quant_trade.audit.report import LABELS

    client, _ = _selling_client(tmp_path)
    page = client.get(_upload(client).headers["location"]).text
    box = page.split("<div class='paybox buy'>", 1)[1].split("</div>", 2)
    included = page.split("<ul class='buy-incl'>", 1)[1].split("</ul>", 1)[0]
    assert "https://wa.me/000" in box[0] + box[1]
    items = LABELS["es"]["buy_includes"].split("|")
    assert len(items) == 4 and all(item in included for item in items)
    assert "Reembolso" in included
    assert find_claims(included) == []
    assert find_claims(LABELS["en"]["buy_includes"]) == []


@pytest.mark.parametrize(
    ("lang", "error", "done"),
    [
        ("es", "Ese código no desbloqueó el informe", "Código de acceso aplicado"),
        ("en", "That code did not unlock the report", "Access code applied"),
    ],
)
def test_a_wrong_code_is_answered_at_the_field_and_a_right_one_in_green(
    tmp_path: Path, lang: str, error: str, done: str
) -> None:
    client, store = _selling_client(tmp_path)
    location = _upload(client, locale=lang).headers["location"]
    audit_id = location.split("/audits/")[1].split("?")[0]
    token = location.split("token=")[1].split("&")[0]
    page = client.get(f"/audits/{audit_id}?token={token}&lang={lang}&code=rejected").text
    # The refusal sits under the code field, says what to do, and marks the field.
    form = page.split("id='canjear'", 1)[1].split("</form>", 1)[0]
    assert "#canjear'" in page and "class='code-error'" in form and error in form
    assert "aria-invalid='true' aria-describedby='redeem-error'" in form
    assert "https://wa.me/000" in page  # the button the refusal points to
    assert "class='notice" not in page
    assert find_claims(page) == []
    code, _ = store.create_access_code(credits=1, note="", at=NOW)  # type: ignore[attr-defined]
    client.post(f"/audits/{audit_id}/redeem?token={token}", data={"code": code})
    paid = client.get(f"/audits/{audit_id}?token={token}&lang={lang}&code=applied").text
    assert "<div class='notice ok' role='status'>" in paid and done in paid
    assert "class='code-error'" not in paid
    # A stale "rejected" link on a paid report shows no refusal.
    stale = client.get(f"/audits/{audit_id}?token={token}&lang={lang}&code=rejected").text
    assert "class='code-error'" not in stale and "class='notice" not in stale
