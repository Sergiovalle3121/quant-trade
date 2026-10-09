"""The first upload is not lost: unknown columns are named on the same page,
with the file still chosen, and a refusal is said above the fields.

Everything runs offline with TestClient; the browser half is checked on the
script's text, since no browser runs here.
"""

from __future__ import annotations

import html
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from test_audit_column_mapping_web import MAPPING, _own_journal  # noqa: E402

from quant_trade.audit import account_pages, account_pt, mapping  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.pages import upload_page  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.theme import STATIC_DIR  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

LOCALES = ("es", "en", "pt")
CONTACT = "https://wa.me/000?text=hola&lang=es"


def _client(tmp_path: Path, **extra: object) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        **extra,  # type: ignore[arg-type]
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _directives(policy: str) -> dict[str, str]:
    parts = (part.strip() for part in policy.split(";"))
    return {name: rest.strip() for name, _, rest in (part.partition(" ") for part in parts if part)}


def test_the_policy_lets_scripts_call_only_this_site(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for path in ("/", "/auditar"):
        policy = client.get(path).headers["content-security-policy"]
        directives = _directives(policy)
        assert directives["connect-src"] == "'self'"
        assert "connect-src 'none'" not in policy
        # The only address anywhere in the policy is Stripe's, as a form target.
        for name, sources in directives.items():
            if name != "form-action":
                assert "http" not in sources and "*" not in sources, name


def test_unknown_columns_come_back_as_menus_and_the_same_file_goes_through(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, contact_url=CONTACT)
    files = {"report": ("mi_diario.csv", _own_journal(), "text/csv")}
    headers = {"Accept": "application/json"}
    refused = client.post("/audits", files=files, data={"consent": "on"}, headers=headers)
    assert refused.status_code == 422
    body = refused.json()
    # The keys a client already read are still there.
    for key in ("error", "code", "columns", "category", "format", "guidance_html"):
        assert key in body
    assert body["problem"] == body["error"]
    fields = body["fields_html"]
    assert "name='col_" in fields and "<select" in fields
    assert "<form" not in fields and "type='file'" not in fields
    for name in body["columns"]:
        assert f"value='{html.escape(name, quote=True)}'" in fields
    assert f"href='{html.escape(CONTACT, quote=True)}'" in fields
    assert find_claims(html.unescape(fields)) == []
    # The browser sends the very same bytes with the chosen columns.
    posted = client.post(
        "/audits",
        files=files,
        data={"consent": "on", "initial_balance": "20000", **MAPPING},
        headers=headers,
    )
    assert posted.status_code == 201, posted.text[:500]
    assert posted.json()["location"].startswith("/audits/")


def test_a_column_name_is_escaped_in_the_menus() -> None:
    data = (
        b'Fecha,"<img src=x onerror=alert(1)>",it\'s\n'
        b"2025-01-02,1,5\n2025-01-03,2,-3\n2025-01-04,3,4\n"
    )
    table = mapping.read_table(data)
    assert table is not None
    fields = mapping.mapping_fields(table, locale="es")
    assert "<img" not in fields
    assert "&lt;img src=x onerror=alert(1)&gt;" in fields
    assert "it&#x27;s" in fields


@pytest.mark.parametrize("locale", LOCALES)
def test_the_form_has_its_two_places_and_works_without_script(locale: str) -> None:
    page = upload_page(locale=locale)
    assert "data-inplace" in page
    assert "<div id='upload-alert' role='alert' hidden></div>" in page
    assert "<div id='map-fields' hidden></div>" in page
    # The places sit inside the form, the menus right after the main file field.
    form = page[page.index("<form method='post' action='/audits'") :]
    form = form[: form.index("</form>")]
    assert form.index("id='upload-alert'") < form.index("name='report'")
    assert form.index("name='report'") < form.index("id='map-fields'")
    assert form.index("id='map-fields'") < form.index("name='equity'")
    assert find_claims(page) == []


def test_the_script_answers_in_place_and_falls_back_to_the_ordinary_post() -> None:
    script = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    assert "form[data-inplace]" in script
    assert "fields_html" in script and "application/json" in script
    assert "HTMLFormElement.prototype.submit" in script
    assert 'credentials: "same-origin"' in script
    # Markup from the server goes in from two keys only.
    assert script.count(".innerHTML") == 1
    assert "fields.innerHTML = json.fields_html" in script
    assert script.count("insertAdjacentHTML") == 1
    assert 'insertAdjacentHTML("beforeend", guidance)' in script
    assert "line.textContent = problem" in script


@pytest.mark.parametrize("locale", LOCALES)
def test_the_way_to_a_person_shows_only_with_a_contact(locale: str) -> None:
    data = _own_journal()
    table = mapping.read_table(data)
    assert table is not None
    escaped = html.escape(CONTACT, quote=True)
    with_contact = mapping.mapping_fields(table, locale=locale, contact_url=CONTACT)
    without = mapping.mapping_fields(table, locale=locale)
    line = mapping.COPY[locale]["human"]
    assert f"<a href='{escaped}' rel='noopener'>" in with_contact
    assert html.unescape(with_contact).count(line.split("? ", 1)[1]) == 1
    assert "rel='noopener'" not in without
    assert line.split("? ", 1)[0] not in without
    page = mapping.mapping_page(table, "x", locale=locale, contact_url=CONTACT)
    assert page.count(f"<a href='{escaped}' rel='noopener'>") == 1
    bare = mapping.mapping_page(table, "x", locale=locale)
    assert f"href='{escaped}'" not in bare
    assert find_claims(line) == []


def test_every_new_sentence_passes_the_guard() -> None:
    texts = [mapping.COPY[locale]["human"] for locale in LOCALES]
    for key in (
        "email_verified_report",
        "welcome_refused_unverified",
        "welcome_confirm",
        "welcome_pending_other",
        "welcome_pending_confirmed",
    ):
        texts += [account_pages.COPY[locale][key] for locale in ("es", "en")]
        texts.append(account_pt.COPY_PT[key])
    assert len(set(texts)) == len(texts)
    for text in texts:
        assert find_claims(text) == [], text
