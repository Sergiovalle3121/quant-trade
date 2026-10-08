"""Report wording, upload guidance and refusals a customer audit found unclear."""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import account_pages, mapping, pdf_tables  # noqa: E402
from quant_trade.audit.engine import run_audit  # noqa: E402
from quant_trade.audit.forensics.copy import CHECK_NAMES  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.guides import GUIDES  # noqa: E402
from quant_trade.audit.pages import AUDIT_PATHS, upload_page, verification_page  # noqa: E402
from quant_trade.audit.prop_presets import PRESETS, preset_label  # noqa: E402
from quant_trade.audit.report import LABELS as REPORT_LABELS  # noqa: E402
from quant_trade.audit.report import (  # noqa: E402
    RECON_REASONS,
    _forensics_html,
    _reconciliation_html,
    _source_html,
    render,
    render_html,
)
from quant_trade.audit.schema import (  # noqa: E402
    MAX_UPLOAD_BYTES,
    DeclaredMetadata,
    build_inputs,
)
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store, public_view  # noqa: E402
from quant_trade.audit.verdict import MEANING, meaning, trials_undeclared  # noqa: E402
from quant_trade.audit.web import MESSAGES, PICTURE_SIGNATURES, create_app, message  # noqa: E402

NOW = datetime(2026, 1, 1, tzinfo=UTC)
LOCALES = ("es", "en", "pt")
PASSWORD = "una frase larga y segura"
CSRF_FIELD = re.compile(r"name='csrf' value='([^']+)'")
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _text(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def _undeclared(locale: str):
    inputs = build_inputs(
        csv_bytes(positive_drift(1500)),
        DeclaredMetadata(trials=1, trials_declared=False, locale=locale),
    )
    return run_audit(inputs, now=NOW, audit_id="undeclared", bootstrap_samples=50)


# -- I1: trials not declared ---------------------------------------------------


@pytest.mark.parametrize(
    ("locale", "said", "old", "old_plan"),
    [
        ("es", "la clase no puede pasar de B", "porque la significación no se midió", "medible"),
        ("en", "the class cannot go above B", "because significance was not", "is measurable"),
        ("pt", "a classe não pode passar de B", "porque a significância não foi", "mensurável"),
    ],
)
def test_undeclared_trials_are_explained_as_undeclared(
    locale: str, said: str, old: str, old_plan: str
) -> None:
    result = _undeclared(locale)
    by_name = {d.name: d for d in result.verdict.dimensions}
    assert by_name["statistical_significance"].status == "PASS"
    assert by_name["multiplicity"].status == "NOT_MEASURED"
    assert result.verdict.overall == "B"
    page, _ = render(result, watermark=False, locale=locale)
    text = _text(page)
    assert text.count(said) >= 2  # the plain text and the plan
    assert old not in text and old_plan not in text
    assert "(aunque sea 1)" in text or "(even if it is 1)" in text or "(mesmo que seja 1)" in text


def test_the_undeclared_wording_is_kept_for_that_case_only() -> None:
    measured = {"evidence": "MEASURED", "value": 0.99}
    unknown = {"evidence": "NOT_MEASURED", "value": 1}
    assert trials_undeclared({"trials_used": unknown, "dsr_at_trials_used": measured})
    assert not trials_undeclared({"trials_used": unknown, "dsr_at_trials_used": unknown})
    declared = {"evidence": "DECLARED", "value": 1}
    assert not trials_undeclared({"trials_used": declared, "dsr_at_trials_used": measured})
    assert not trials_undeclared(None)
    for locale in LOCALES:
        plain = meaning("multiplicity", "NOT_MEASURED", locale)
        assert plain == MEANING[locale]["multiplicity.NOT_MEASURED"]
        for status in ("NOT_MEASURED", "FAIL"):
            for fund in (False, True):
                text = meaning("multiplicity", status, locale, fund=fund, undeclared=True)
                assert text and text != meaning("multiplicity", status, locale)
                assert find_claims(text) == []
        # A status with no undeclared wording keeps its own.
        assert meaning("costs", "PASS", locale, undeclared=True) == meaning("costs", "PASS", locale)
        assert "tantas" not in meaning("multiplicity", "FAIL", locale, undeclared=True)


def test_the_public_page_explains_undeclared_trials_too() -> None:
    result = _undeclared("es").model_dump(mode="json")
    page = verification_page(
        result,
        public_id="abc123",
        published_at="2026-01-02T00:00:00+00:00",
        result_sha256="0" * 64,
        base_url="https://example.test",
        locale="es",
    )
    assert "la clase no puede pasar de B" in _text(page)


def test_the_kept_public_view_keeps_the_undeclared_fact_not_the_inputs() -> None:
    view, _ = public_view(_undeclared("es").model_dump_json())
    by_name = {d["name"]: d for d in view["verdict"]["dimensions"]}
    assert by_name["multiplicity"]["undeclared"] is True
    assert all(set(d) == {"name", "status", "undeclared"} for d in by_name.values())
    assert sum(d["undeclared"] for d in by_name.values()) == 1
    for locale, said in (
        ("es", "la clase no puede pasar de B"),
        ("en", "the class cannot go above B"),
        ("pt", "a classe não pode passar de B"),
    ):
        page = verification_page(
            view,
            public_id="abc123",
            published_at="2026-01-02T00:00:00+00:00",
            result_sha256="0" * 64,
            base_url="https://example.test",
            locale=locale,
        )
        assert said in _text(page)


def test_the_public_page_of_undeclared_trials_is_the_same_after_the_purge(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path, base_url="https://audit.example")
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(1500)), "text/csv")}
    location = client.post(
        "/audits", files=files, data={"consent": "on"}, follow_redirects=False
    ).headers["location"]
    audit_id, token = _audit_id(location), location.split("token=")[1]
    public_id = client.post(
        f"/audits/{audit_id}/publish?token={token}", headers={"accept": "application/json"}
    ).json()["public_id"]
    before = client.get(f"/v/{public_id}").text
    assert "la clase no puede pasar de B" in _text(before)
    assert "porque la significación no se midió" not in _text(before)
    store = client.app.state.store
    assert store.purge_expired(datetime(2100, 1, 1, tzinfo=UTC), retention_days=1) == 1
    after = client.get(f"/v/{public_id}").text
    assert after == before


# -- I2: money reconciliation ---------------------------------------------------


@pytest.mark.parametrize(
    ("locale", "expected"),
    [
        (
            "es",
            "No se pudo cerrar la conciliación. Las operaciones cerradas no cubren el tramo "
            "final de la curva.",
        ),
        (
            "en",
            "The reconciliation could not be completed. The closed trades do not cover the "
            "final part of the curve.",
        ),
        (
            "pt",
            "Não foi possível concluir a conciliação. As operações fechadas não cobrem o "
            "trecho final da curva.",
        ),
    ],
)
def test_the_reconciliation_reason_is_translated_and_set_apart(locale: str, expected: str) -> None:
    recon = {
        "status": "NOT_MEASURED",
        "reason": "closed trades do not cover the final part of the curve",
    }
    text = " ".join(_text(_reconciliation_html(recon, locale)).split())
    assert expected in text
    if locale != "en":
        assert "closed trades" not in text
    assert find_claims(text) == []


def test_every_reconciliation_reason_the_engine_writes_has_its_sentence() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "quant_trade" / "audit" / "engine.py"
    body = source.read_text(encoding="utf-8")
    assert '"closed trades do not cover the final part of the curve"' in body
    for reason, sentences in RECON_REASONS.items():
        assert len(sentences) == 3 and all(sentences), reason
        for sentence in sentences:
            assert sentence.endswith(".") and find_claims(sentence) == []


def test_a_reconciliation_heading_without_reason_has_no_stray_stop() -> None:
    page = _reconciliation_html({"status": "MATCH", "reason": ""}, "es")
    assert "<strong>Cuadra dentro de la tolerancia</strong>" in page


# -- I3: comparing from a Portuguese report ------------------------------------


def test_a_portuguese_report_compares_in_portuguese(tmp_path: Path) -> None:
    result = _undeclared("pt")
    page = render_html(
        result, watermark=False, locale="pt", compare_link="/audits/x?token=t", free_mode=True
    )
    form = page.split("name='link_a'")[0].rsplit("<form", 1)[1]
    assert "action='/pt/comparar'" in form
    assert "aria-label='Link do segundo relatório'" in page
    assert "Link to the second report" not in page
    spanish = render_html(
        _undeclared("es"), watermark=False, locale="es", compare_link="/audits/x?token=t"
    )
    assert "action='/comparar'" in spanish
    english = render_html(
        _undeclared("en"), watermark=False, locale="en", compare_link="/audits/x?token=t"
    )
    assert "action='/compare'" in english and "Link to the second report" in english
    # An older page that still posts to the English address stays Portuguese.
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", free_mode=True, bootstrap_samples=100
    )
    client = TestClient(create_app(settings, make_store(settings.database_url)))
    answer = client.post("/compare", data={"link_a": "x", "link_b": "y", "lang": "pt"})
    assert answer.status_code == 400 and "<html lang='pt'>" in answer.text


# -- I4: the table of checks ----------------------------------------------------


@pytest.mark.parametrize("locale", LOCALES)
def test_the_table_of_checks_names_each_check_for_the_reader(locale: str) -> None:
    forensics = {
        "method_version": "forensics-1",
        "family": "mt5_tester",
        "rows_read": 10,
        "checks": [
            {"id": "FILE_TRACE", "status": "CLEAR"},
            {"id": "TOTALS_VS_ROWS", "status": "CLEAR"},
            {"id": "BALANCE_CHAIN", "status": "CLEAR"},
            {"id": "SOMETHING_NEW", "status": "CLEAR"},
        ],
    }
    page = _forensics_html(forensics, locale)
    table = page.split("forensic-all", 1)[1]
    for code in ("FILE_TRACE", "TOTALS_VS_ROWS", "BALANCE_CHAIN"):
        name = html.escape(CHECK_NAMES[locale][code])
        assert f"{name} <small class='muted'><code>{code}</code></small>" in table
    # A check with no name yet reads as words, with its key beside it.
    assert "Something New <small class='muted'><code>SOMETHING_NEW</code>" in table
    assert find_claims(_text(page)) == []


# -- I5 and I6: the column page and the refusals --------------------------------


@pytest.mark.parametrize(
    ("locale", "said", "back"),
    [
        ("es", "¿Es la tabla mensual de un fondo (un año por fila", "/auditar#subir"),
        ("en", "Is it a fund's monthly table (a year per row", "/en/audit#subir"),
        ("pt", "É a tabela mensal de um fundo (um ano por linha", "/pt/auditar#subir"),
    ],
)
def test_the_column_page_points_a_monthly_table_to_the_curve_box(
    locale: str, said: str, back: str
) -> None:
    table = mapping.Table(["Year", "Jan", "Feb"], [["2021", "0.60%", "1.10%"]] * 3)
    page = mapping.mapping_page(table, "x", locale=locale)
    assert said in _text(page)
    assert f"href='{back}'" in page
    for key in ("monthly", "monthly_link", "one_row"):
        assert find_claims(mapping.COPY[locale][key]) == []


def _client(tmp_path: Path, **extra: object) -> TestClient:
    values: dict[str, object] = {
        "database_url": f"sqlite:///{tmp_path}/audit.db",
        "free_mode": True,
        "bootstrap_samples": 100,
    }
    values.update(extra)
    settings = AuditSettings(**values)  # type: ignore[arg-type]
    return TestClient(create_app(settings, make_store(settings.database_url)))


def test_report_http_toolbar_links_another_upload_in_each_language(tmp_path: Path) -> None:
    client = _client(tmp_path)
    uploaded = _upload(client)
    assert uploaded.status_code == 303
    location = uploaded.headers["location"]
    assert "?token=" in location
    for locale in LOCALES:
        response = client.get(location + f"&lang={locale}")
        assert response.status_code == 200
        toolbar = response.text.split("<div class='nav-end no-print report-toolbar'>", 1)[1]
        toolbar = toolbar.split("</div>", 1)[0]
        assert f"<a class='nav-account report-new-audit' href='{AUDIT_PATHS[locale]}'" in toolbar
        assert html.escape(REPORT_LABELS[locale]["new_audit"]) in toolbar
        assert find_claims(response.text) == []


@pytest.mark.parametrize(
    ("locale", "box", "said"),
    [
        ("es", "equity", "El archivo de la curva de equity llegó vacío (0 bytes)"),
        ("es", "report", "El archivo del informe llegó vacío (0 bytes)"),
        ("en", "equity", "The equity file arrived empty (0 bytes)"),
        ("pt", "report", "O arquivo do relatório chegou vazio (0 bytes)"),
    ],
)
def test_an_empty_file_is_called_empty_not_missing(
    tmp_path: Path, locale: str, box: str, said: str
) -> None:
    client = _client(tmp_path)
    files = {box: ("vacio.csv", b"", "text/csv")}
    answer = client.post("/audits", files=files, data={"consent": "on", "locale": locale})
    assert answer.status_code == 400
    assert said in _text(answer.text)


def test_no_file_at_all_is_still_a_missing_file(tmp_path: Path) -> None:
    client = _client(tmp_path)
    answer = client.post("/audits", data={"consent": "on", "locale": "es"})
    assert answer.status_code == 400
    assert "Falta el archivo" in _text(answer.text)


@pytest.mark.parametrize(
    ("locale", "said"),
    [
        ("es", "es una imagen, no una tabla"),
        ("en", "is a picture, not a table"),
        ("pt", "é uma imagem, não uma tabela"),
    ],
)
def test_a_picture_in_the_curve_box_is_called_a_picture(
    tmp_path: Path, locale: str, said: str
) -> None:
    client = _client(tmp_path)
    files = {"equity": ("curva.png", PNG, "image/png")}
    answer = client.post("/audits", files=files, data={"consent": "on", "locale": locale})
    assert answer.status_code == 400
    text = _text(answer.text)
    assert said in text
    assert "timestamp, date" not in text
    assert "PDF" not in message("curve_is_picture", locale)


def test_a_pdf_statement_in_the_curve_box_still_reaches_the_column_screen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PDF is not a picture: its table is read (the PDF extraction stands
    in for itself here) and offered to name, as it was before the refusal."""
    rows = [["Fecha", "Balance"]] + [
        [f"2024-01-{day:02d}", f"{10000 + day * 7 - (day % 3) * 5}"] for day in range(2, 30)
    ]
    monkeypatch.setattr(pdf_tables, "rows", lambda data: [list(row) for row in rows])
    assert b"%PDF-" not in PICTURE_SIGNATURES
    client = _client(tmp_path)
    pdf = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF\n"
    files = {"equity": ("estado.pdf", pdf, "application/pdf")}
    screen = client.post("/audits", files=files, data={"consent": "on", "locale": "es"})
    assert screen.status_code == 422, screen.text[:300]
    assert "no es una tabla" not in _text(screen.text)
    assert "Dinos qué es cada columna" in screen.text
    named = {"consent": "on", "locale": "es", "col_date": "Fecha", "col_balance": "Balance"}
    posted = client.post("/audits", files=files, data=named, follow_redirects=False)
    assert posted.status_code == 303, posted.text[:300]


@pytest.mark.parametrize(
    ("locale", "said"),
    [
        ("es", "Tu archivo tiene menos de dos filas con datos"),
        ("en", "Your file has fewer than two rows of data"),
        ("pt", "Seu arquivo tem menos de duas linhas com dados"),
    ],
)
def test_a_one_row_file_in_the_main_box_says_it_is_too_short(
    tmp_path: Path, locale: str, said: str
) -> None:
    client = _client(tmp_path)
    files = {"report": ("una.csv", b"cuando,cuanto\n2024-01-02,10000\n", "text/csv")}
    answer = client.post("/audits", files=files, data={"consent": "on", "locale": locale})
    assert answer.status_code in (400, 422)
    assert said in _text(answer.text)


# -- I7 and I8: limits and guidance on the upload page ---------------------------


@pytest.mark.parametrize(
    ("locale", "small", "large", "hint"),
    [
        ("es", "Hasta 5 MB", "Hasta 10 MB", "año-mes-día (2026-03-31)"),
        ("en", "Up to 5 MB", "Up to 10 MB", "year-month-day (2026-03-31)"),
        ("pt", "Até 5 MB", "Até 10 MB", "ano-mês-dia (2026-03-31)"),
    ],
)
def test_every_box_states_its_limit_and_the_date_guidance(
    locale: str, small: str, large: str, hint: str
) -> None:
    page = upload_page(locale=locale, free_mode=True)

    def box(name: str) -> str:
        return _text(page.split(f"id='f-{name}'", 1)[1].split("class='field'", 1)[0])

    for name in ("equity", "trades", "benchmark", "variants"):
        assert small in box(name), name
    for name in ("optimization", "live"):
        assert large in box(name), name
    for name in ("equity", "trades"):
        assert hint in box(name), name
    # The curve box says a platform report dropped there may reach 10 MB.
    assert "10 MB" in box("equity")
    assert "soltado" not in box("equity") and "solto aqui" not in box("equity")
    assert find_claims(_text(page)) == []


@pytest.mark.parametrize(
    ("locale", "said"),
    [
        ("es", "pesa más de 5 MB, el máximo que aceptamos para una curva"),
        ("en", "is larger than 5 MB, the most we accept for a curve"),
        ("pt", "passa de 5 MB, o máximo que aceitamos para uma curva"),
    ],
)
def test_a_curve_over_the_limit_is_told_the_real_limit(
    tmp_path: Path, locale: str, said: str
) -> None:
    client = _client(tmp_path)
    line = b"2024-01-02 00:00:00,10000.123456\n"
    middle = b"timestamp,equity\n" + line * (MAX_UPLOAD_BYTES // len(line) + 10)
    assert MAX_UPLOAD_BYTES < len(middle) < 2 * MAX_UPLOAD_BYTES
    for data, status in ((middle, 400), (middle * 2 + line * 100, 413)):
        files = {"equity": ("curva.csv", data, "text/csv")}
        answer = client.post("/audits", files=files, data={"consent": "on", "locale": locale})
        assert answer.status_code == status
        # The retry form now includes the other fields' limits too. The refusal
        # itself must still name only the limit of the rejected file.
        text = _text(answer.text.split("<p role='alert'>", 1)[1].split("</p>", 1)[0])
        assert said in text
        assert "10 MB" not in text and "bytes" not in text


@pytest.mark.parametrize(
    ("locale", "said"),
    [
        ("es", "El archivo del informe pesa más de 10 MB"),
        ("en", "The report file is larger than 10 MB"),
        ("pt", "O arquivo do relatório passa de 10 MB"),
    ],
)
def test_an_oversized_platform_report_in_the_curve_box_is_told_the_report_limit(
    tmp_path: Path, locale: str, said: str
) -> None:
    """The help beside the curve box promises 10 MB for a platform report
    dropped there, so its refusal says 10 MB and names the report."""
    client = _client(tmp_path)
    row = b"<tr><td>2024.01.02 00:00</td><td>10000.00</td></tr>\n"
    page = b"<!DOCTYPE html><html><body><table>" + row * (2 * MAX_UPLOAD_BYTES // len(row) + 100)
    assert len(page) > 2 * MAX_UPLOAD_BYTES
    files = {"equity": ("ReportTester.html", page, "text/html")}
    answer = client.post("/audits", files=files, data={"consent": "on", "locale": locale})
    assert answer.status_code == 413
    text = _text(answer.text.split("<p role='alert'>", 1)[1].split("</p>", 1)[0])
    assert said in text
    assert "5 MB" not in text


def test_the_new_messages_exist_in_three_languages_and_pass_the_guard() -> None:
    for key in ("empty_upload", "curve_too_large", "curve_is_picture"):
        for locale in LOCALES:
            assert find_claims(MESSAGES[key][locale]) == [], (key, locale)


# -- I9: the list of challenges -------------------------------------------------


def test_the_challenge_list_speaks_the_page_language() -> None:
    page = upload_page(locale="pt", free_mode=True)
    options = page.split("name='challenge'", 1)[1].split("</select>", 1)[0]
    assert "phase 1" not in options and "fase 1" in options
    assert "Two-step evaluation" not in options and "each of steps" not in options
    # The option chosen by default is the generic one, in Portuguese.
    chosen = re.search(r"<option value='([^']+)' selected>([^<]+)</option>", options)
    assert chosen is not None and chosen.group(1) == "generic-2step-phase1"
    assert html.unescape(chosen.group(2)).startswith("Genérico")
    spanish = upload_page(locale="es", free_mode=True)
    assert "fase 1" in spanish.split("name='challenge'", 1)[1].split("</select>", 1)[0]
    english = upload_page(locale="en", free_mode=True)
    assert "phase 1" in english.split("name='challenge'", 1)[1].split("</select>", 1)[0]
    for rules in PRESETS.values():
        assert "phase" not in preset_label(rules.firm, rules.program, rules.phase, "pt")


# -- I10: small wording ---------------------------------------------------------


@pytest.mark.parametrize(
    ("locale", "one", "many"),
    [
        ("es", "1 configuración probada", "12 configuraciones probadas"),
        ("en", "1 configuration tried", "12 configurations tried"),
        ("pt", "1 configuração testada", "12 configurações testadas"),
    ],
)
def test_one_configuration_is_singular(locale: str, one: str, many: str) -> None:
    def shown(count: int) -> str:
        data = {"inputs": {"optimization": {"passes": {"value": count, "evidence": "MEASURED"}}}}
        return " ".join(_text(_source_html(data, REPORT_LABELS[locale])).split())

    assert one in shown(1) and many in shown(12)


def test_the_provider_guide_is_named_in_one_language_at_a_time() -> None:
    guide = next(g for g in GUIDES if g.slug == "cuenta-proveedor")
    assert guide.platform_for("es") == "Cuenta de un proveedor"
    assert guide.platform_for("en") == "Provider's account"
    assert guide.platform_for("pt") == "Conta de um fornecedor"
    optimisation = next(g for g in GUIDES if g.slug == "mt5-optimization")
    assert optimisation.platform_for("es") == "MetaTrader 5 (optimización)"
    assert optimisation.platform_for("en") == "MetaTrader 5 (optimisation)"
    assert optimisation.platform_for("pt") == "MetaTrader 5 (otimização)"
    for any_guide in GUIDES:
        for locale in LOCALES:
            assert " / " not in any_guide.platform_for(locale), (any_guide.slug, locale)


def test_the_portuguese_report_uses_one_word_for_optimisation_passes() -> None:
    source = Path(__file__).resolve().parents[1] / "src" / "quant_trade" / "audit"
    body = (source / "report_pt.py").read_text(encoding="utf-8")
    assert re.search(r"\b[Pp]assadas?\b", body) is None


@pytest.mark.parametrize(
    ("locale", "link"),
    [
        ("es", "<a href='https://example.test/v/abc123'>"),
        ("en", "<a href='https://example.test/v/abc123?lang=en'>"),
        ("pt", "<a href='https://example.test/v/abc123?lang=pt'>"),
    ],
)
def test_the_badge_code_opens_the_page_in_its_language(locale: str, link: str) -> None:
    page = verification_page(
        _undeclared(locale).model_dump(mode="json"),
        public_id="abc123",
        published_at="2026-01-02T00:00:00+00:00",
        result_sha256="0" * 64,
        base_url="https://example.test",
        locale=locale,
    )
    assert html.escape(link) in page or link in html.unescape(page)
    assert f"badge.svg?lang={locale}" in html.unescape(page)


# -- I11: the same file again ---------------------------------------------------


def _csrf(page: str) -> str:
    match = CSRF_FIELD.search(page)
    assert match, "the form has no CSRF field"
    return match.group(1)


def _signup(client: TestClient, email: str) -> None:
    csrf = _csrf(client.get("/registro").text)
    client.post(
        "/registro",
        data={"email": email, "password": PASSWORD, "csrf": csrf},
        follow_redirects=False,
    )
    account = client.app.state.store.find_account(email)
    client.app.state.store.spend_welcome(account.id, at=datetime.now(UTC))


def _upload(client: TestClient, rows: int = 500):
    files = {"equity": ("equity.csv", csv_bytes(positive_drift(rows)), "text/csv")}
    data = {"trials": "3", "consent": "on"}
    return client.post("/audits", files=files, data=data, follow_redirects=False)


def _audit_id(location: str) -> str:
    return location.split("/audits/")[1].split("?")[0]


def test_the_same_file_again_links_the_report_the_account_already_has(tmp_path: Path) -> None:
    client = _client(tmp_path, free_mode=False, access_codes=True, contact_url="https://wa.me/0")
    _signup(client, "ana@example.com")
    first = _upload(client)
    again = _upload(client)
    other = _upload(client, rows=400)
    assert first.status_code == again.status_code == other.status_code == 303
    first_id = _audit_id(first.headers["location"])
    # The behaviour is unchanged: the second upload is its own preview.
    assert _audit_id(again.headers["location"]) != first_id
    account = client.app.state.store.find_account("ana@example.com")
    assert len(client.app.state.store.account_audits_list(account.id)) == 3
    for locale, said, link in (
        ("es", "Ya habías auditado este mismo archivo", "Abrir el informe que ya tienes"),
        ("en", "You had already audited this same file", "Open the report you already have"),
        ("pt", "Você já tinha auditado este mesmo arquivo", "Abrir o relatório que você já tem"),
    ):
        page = client.get(again.headers["location"] + f"&lang={locale}").text
        assert said in _text(page)
        assert f"<a href='/audits/{first_id}?lang={locale}'>{html.escape(link)}</a>" in page
        assert find_claims(account_pages.COPY[locale]["same_file_note"]) == []
    # The first report and a different file say nothing of the kind.
    assert "Ya habías auditado" not in client.get(first.headers["location"]).text
    assert "Ya habías auditado" not in client.get(other.headers["location"]).text


def test_a_report_of_another_account_is_never_named(tmp_path: Path) -> None:
    client = _client(tmp_path, free_mode=False, access_codes=True, contact_url="https://wa.me/0")
    _signup(client, "ana@example.com")
    first = _upload(client)
    client.cookies.clear()
    _signup(client, "luis@example.com")
    second = _upload(client)
    assert second.status_code == 303
    page = client.get(second.headers["location"]).text
    assert "Ya habías auditado" not in page
    assert _audit_id(first.headers["location"]) not in page
    # Opened by its link without a session, the note is not shown either.
    client.cookies.clear()
    assert "Ya habías auditado" not in client.get(second.headers["location"]).text


def _report_audit(store, audit_id: str, digest: str, *, at: datetime) -> None:
    """An upload made from a platform report: no curve digest of its own."""
    store.create_audit(
        audit_id=audit_id,
        created_at=at,
        token_hash="h" * 64,
        client_ip="",
        declared_json="{}",
        result_json=f'{{"audit_id": "{audit_id}"}}',
        report_html="<html></html>",
        overall_class="B",
        digests={"report.html": digest},
        equity_csv=None,
        files={"report.html": b"<html></html>"},
    )


def test_a_platform_report_uploaded_again_finds_its_earlier_report(tmp_path: Path) -> None:
    """The prefilter uses the report's own digest, so the earlier report is
    found past any number of other report uploads of the same account."""
    store = make_store(f"sqlite:///{tmp_path}/audit.db")
    account = store.create_account(
        email="ana@example.com", password_hash="x" * 64, locale="es", at=NOW
    )
    assert account is not None
    when = NOW
    for index in range(25):
        when = when.replace(day=1 + index % 28, month=1 + index // 28)
        _report_audit(store, f"other{index:02d}", f"{index:064x}", at=when)
        store.link_audit(account.id, f"other{index:02d}", at=when)
    first = datetime(2026, 3, 1, tzinfo=UTC)
    _report_audit(store, "first", "f" * 64, at=first)
    store.link_audit(account.id, "first", at=first)
    again = datetime(2026, 3, 2, tzinfo=UTC)
    _report_audit(store, "again", "f" * 64, at=again)
    store.link_audit(account.id, "again", at=again)
    assert store.earlier_audit_of_same_files(account.id, "again") == "first"
    # A different report, or the first upload itself, names nothing.
    assert store.earlier_audit_of_same_files(account.id, "first") is None
    assert store.earlier_audit_of_same_files(account.id, "other24") is None
    # Another account never sees it.
    other = store.create_account(
        email="luis@example.com", password_hash="x" * 64, locale="es", at=NOW
    )
    assert other is not None
    assert store.earlier_audit_of_same_files(other.id, "again") is None
