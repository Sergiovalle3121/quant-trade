"""Account histories without stumbles: where they are dropped, what the money
reconciliation can say without a printed balance, the forensic wording and two
sentences of the plan.

Everything runs offline on the synthetic Myfxbook statement of the sample.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402
from test_audit_tracking_exports import MQL5_HISTORY, _fxblue  # noqa: E402

from quant_trade.audit import sample  # noqa: E402
from quant_trade.audit.engine import _NO_PRINTED_BALANCE_REASON, run_audit  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.i18n import localize  # noqa: E402
from quant_trade.audit.plan import improvement_plan  # noqa: E402
from quant_trade.audit.report import INTEGRITY_TEXT, RECON_REASONS  # noqa: E402
from quant_trade.audit.report_pt import RULES as PT_RULES  # noqa: E402
from quant_trade.audit.sample import synthetic_live_statement  # noqa: E402
from quant_trade.audit.schema import DeclaredMetadata, build_inputs  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.upload_rejections import REJECTION_COPY  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

NOW = datetime(2026, 10, 8, tzinfo=UTC)
LOCALES = ("es", "en", "pt")
#: The plan's sentence for a DSR already below 0.5 at a single trial, on an account:
#: its trials are the accounts or signals behind it, not configurations.
ONE_TRIAL = {
    "es": "Ya con 1 cuenta, el caso más favorable, queda por debajo de 0.5: aquí decide la "
    "falta de significación, no el número de intentos.",
    "en": "Even at 1 account, the most favourable case, it is below 0.5: what decides here "
    "is the lack of significance, not the number of trials.",
    "pt": "Já com 1 conta, o caso mais favorável, fica abaixo de 0.5: aqui quem decide é a "
    "falta de significância, não o número de tentativas.",
}
REOPTIMISE = {
    "es": "Los intentos que ya hiciste siguen contando: reoptimizar alrededor de la "
    "configuración elegida los suma, no los borra. En la próxima versión, menos parámetros y "
    "rangos más cortos desde el principio reducen el número de intentos.",
    "en": "The trials you already ran still count: re-optimising around the chosen "
    "configuration adds to them, it does not erase them. In the next version, fewer "
    "parameters and narrower ranges from the start mean fewer trials.",
    "pt": "As tentativas que você já fez continuam contando: reotimizar em torno da "
    "configuração escolhida soma tentativas, não as apaga. Na próxima versão, menos "
    "parâmetros e faixas mais curtas desde o início reduzem o número de tentativas.",
}
OLD_ACTION = {
    "es": "Menos parámetros y rangos más cortos reducen el número de intentos.",
    "en": "Fewer parameters and narrower ranges mean fewer trials.",
    "pt": "Menos parâmetros e faixas mais curtas reduzem o número de tentativas.",
}


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        base_url="https://audit.example",
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _post(client: TestClient, field: str, name: str, data: bytes) -> Any:
    return client.post(
        "/audits",
        files={field: (name, data, "text/csv")},
        data={"consent": "on", "locale": "es"},
        follow_redirects=False,
    )


def _result(client: TestClient, location: str) -> dict[str, Any]:
    audit_id = location.split("/audits/")[1].split("?")[0]
    token = location.split("token=")[1].split("&")[0]
    response = client.get(f"/audits/{audit_id}.json?token={token}")
    assert response.status_code == 200
    return response.json()


@pytest.fixture(scope="module")
def uploaded(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[TestClient, str]]:
    """The statement sent alone in the optional live box, uploaded once."""
    client = _client(tmp_path_factory.mktemp("account-upload"))
    with client:
        response = _post(client, "live", "statement.csv", synthetic_live_statement())
        assert response.status_code == 303, response.text[:500]
        yield client, response.headers["location"]


def _report(client: TestClient, location: str, locale: str) -> str:
    response = client.get(f"{location}&lang={locale}")
    assert response.status_code == 200
    return html.unescape(response.text)


def _section(page: str, title: str) -> str:
    start = page.index(f"<h2>{title}</h2>")
    end = page.find("<h2", start + 4)
    return page[start : end if end != -1 else len(page)]


def test_account_statement_alone_in_the_live_box_is_the_main_file(
    uploaded: tuple[TestClient, str],
) -> None:
    client, location = uploaded
    data = _result(client, location)
    assert data["inputs"]["source_format"] == "myfxbook_csv"
    assert data["live"] is None


def test_account_csv_in_the_curve_box_is_read_as_the_report(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post(client, "equity", "statement.csv", synthetic_live_statement())
        assert response.status_code == 303, response.text[:500]
        data = _result(client, response.headers["location"])
    assert data["inputs"]["source_format"] == "myfxbook_csv"


@pytest.mark.parametrize("box", ("report", "live", "equity"))
@pytest.mark.parametrize("source_format", ("mql5_signal_csv", "fxblue_csv"))
def test_every_account_export_opens_from_any_box(
    tmp_path: Path, box: str, source_format: str
) -> None:
    data = MQL5_HISTORY if source_format == "mql5_signal_csv" else _fxblue()
    with _client(tmp_path) as client:
        response = _post(client, box, "history.csv", data)
        assert response.status_code == 303, response.text[:500]
        result = _result(client, response.headers["location"])
    assert result["inputs"]["source_format"] == source_format
    assert result["live"] is None


def test_empty_live_file_alone_is_named_as_empty(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post(client, "live", "statement.csv", b"")
    assert response.status_code == 400
    page = html.unescape(response.text)
    assert 'data-upload-rejection="empty_file"' in page
    assert "de la cuenta real" in page
    for name in ("Myfxbook CSV", "MQL5 CSV", "FX Blue CSV"):
        assert name in page


@pytest.mark.parametrize(
    ("box", "name", "what"),
    [
        ("report", "backtest.html", "del informe"),
        ("equity", "curva.csv", "de la curva de equity"),
    ],
)
def test_an_empty_main_file_is_not_replaced_by_the_live_statement(
    tmp_path: Path, box: str, name: str, what: str
) -> None:
    # The three boxes as a browser sends them: the unused one with no name.
    files = {
        "report": ("", b"", "application/octet-stream"),
        "equity": ("", b"", "application/octet-stream"),
        "live": ("statement.csv", synthetic_live_statement(), "text/csv"),
    }
    files[box] = (name, b"", "text/csv")
    with _client(tmp_path) as client:
        response = client.post(
            "/audits",
            files=files,
            data={"consent": "on", "locale": "es"},
            follow_redirects=False,
        )
    assert response.status_code == 400
    page = html.unescape(response.text)
    assert f"El archivo {what} llegó vacío" in page
    assert 'data-upload-rejection="empty_file"' in page


def test_the_live_statement_with_two_unused_boxes_is_the_main_file(tmp_path: Path) -> None:
    files = {
        "report": ("", b"", "application/octet-stream"),
        "equity": ("", b"", "application/octet-stream"),
        "live": ("statement.csv", synthetic_live_statement(), "text/csv"),
    }
    with _client(tmp_path) as client:
        response = client.post(
            "/audits", files=files, data={"consent": "on", "locale": "es"}, follow_redirects=False
        )
        assert response.status_code == 303, response.text[:500]
        data = _result(client, response.headers["location"])
    assert data["inputs"]["source_format"] == "myfxbook_csv"
    assert data["live"] is None


def test_unreadable_live_file_alone_is_not_called_empty(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post(client, "live", "statement.csv", b"hola\nesto no es un informe\n")
    assert response.status_code in (400, 422)
    page = html.unescape(response.text)
    assert "llegó vacío" not in page
    assert REJECTION_COPY["es"]["empty_file"][0] not in page
    assert 'data-upload-rejection="empty_file"' not in page


def test_flow_adjusted_index_is_never_reconciled_as_money() -> None:
    inputs = build_inputs(
        None,
        DeclaredMetadata(trials_declared=False),
        report_bytes=synthetic_live_statement(),
        report_filename="statement.csv",
        now=NOW,
    )
    result = run_audit(inputs, now=NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=50)
    recon = result.reconciliation
    assert recon is not None
    assert recon["status"] == "NOT_MEASURED"
    assert recon["reason"] == _NO_PRINTED_BALANCE_REASON
    assert recon["observed_final"]["evidence"] == "NOT_MEASURED"
    assert recon["difference"]["evidence"] == "NOT_MEASURED"
    assert recon["expected_final"]["value"] == pytest.approx(
        float(inputs.report_metadata["reconstructed_final_balance"]), abs=0.05
    )
    assert not any(flag["code"].startswith("MONETARY_") for flag in result.red_flags)


@pytest.mark.parametrize(
    ("name", "status"),
    [("tradingview_g1.csv", "NOT_MEASURED"), ("mt5_history.html", "MATCH")],
)
def test_only_a_printed_balance_is_reconciled(name: str, status: str) -> None:
    path = Path(__file__).parent / "fixtures" / "audit_imports" / name
    inputs = build_inputs(
        None, DeclaredMetadata(), report_bytes=path.read_bytes(), report_filename=name, now=NOW
    )
    result = run_audit(inputs, now=NOW, bootstrap_samples=50, risk_samples=50, challenge_samples=50)
    assert result.reconciliation is not None
    assert result.reconciliation["status"] == status
    printed = status != "NOT_MEASURED"
    assert (result.reconciliation["reason"] == _NO_PRINTED_BALANCE_REASON) is not printed
    evidence = result.reconciliation["difference"]["evidence"]
    assert evidence == ("MEASURED" if printed else "NOT_MEASURED")


def test_no_printed_balance_reason_is_translated() -> None:
    sentences = RECON_REASONS[_NO_PRINTED_BALANCE_REASON]
    assert len(set(sentences)) == 3
    assert localize(_NO_PRINTED_BALANCE_REASON, "es") != _NO_PRINTED_BALANCE_REASON
    assert any(source == _NO_PRINTED_BALANCE_REASON for source, _ in PT_RULES)
    for text in (*sentences, *(INTEGRITY_TEXT[loc]["recon_no_balance"] for loc in LOCALES)):
        assert find_claims(text) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_report_says_there_is_no_printed_balance(
    uploaded: tuple[TestClient, str], locale: str
) -> None:
    client, location = uploaded
    page = _report(client, location, locale)
    section = _section(page, INTEGRITY_TEXT[locale]["recon_title"])
    sentence = RECON_REASONS[_NO_PRINTED_BALANCE_REASON][LOCALES.index(locale)]
    assert INTEGRITY_TEXT[locale]["recon_no_balance"] in section
    assert sentence in section
    assert INTEGRITY_TEXT[locale]["recon_unmeasured"] not in section
    assert "699.75" not in section
    assert "-195.05" not in section and "−195.05" not in section
    assert find_claims(re.sub(r"<[^>]+>", " ", section)) == []


@pytest.mark.parametrize("locale", LOCALES)
def test_uncalibrated_forensics_do_not_reassure(
    uploaded: tuple[TestClient, str], locale: str
) -> None:
    client, location = uploaded
    page = _report(client, location, locale)
    assert INTEGRITY_TEXT[locale]["forensic_none_uncalibrated"] in page
    assert INTEGRITY_TEXT[locale]["forensic_none"] not in page
    assert find_claims(INTEGRITY_TEXT[locale]["forensic_none_uncalibrated"]) == []
    if locale == "es":
        assert "Invariantes de TradingView" not in page
        assert "Invariantes de NinjaTrader" not in page


def test_platform_invariants_stay_listed_for_their_own_platform() -> None:
    from quant_trade.audit.report import _forensics_html

    checks = [
        {"id": "TV_INVARIANTS", "status": "NOT_MEASURED"},
        {"id": "NT_INVARIANTS", "status": "SIGNAL"},
        {"id": "TICKET_ORDER", "status": "CLEAN"},
    ]
    tradingview = _forensics_html({"family": "tradingview", "checks": checks}, "en")
    assert "TV_INVARIANTS" in tradingview
    # A signal is always shown, whatever the family.
    assert "NT_INVARIANTS" in tradingview
    other = _forensics_html({"family": "myfxbook", "checks": checks[::2]}, "en")
    assert "TV_INVARIANTS" not in other
    assert "TICKET_ORDER" in other


@pytest.mark.parametrize("locale", LOCALES)
def test_plan_speaks_plainly_about_trials(uploaded: tuple[TestClient, str], locale: str) -> None:
    client, location = uploaded
    data = _result(client, location)
    step = next(s for s in improvement_plan(data, locale) if s.dimension == "multiplicity")
    assert ONE_TRIAL[locale] in step.finding
    assert "Con 1 o más configuraciones" not in step.finding
    assert "With 1 or more configurations" not in step.finding
    assert "Com 1 ou mais configurações" not in step.finding
    for text in (step.finding, *step.actions):
        assert find_claims(text) == []

    example = sample.sample_result(locale).model_dump(mode="json")
    actions = [a for s in improvement_plan(example, locale) for a in s.actions]
    assert REOPTIMISE[locale] in actions
    assert OLD_ACTION[locale] not in actions
    assert find_claims(REOPTIMISE[locale]) == []
    assert find_claims(ONE_TRIAL[locale]) == []


def test_a_fund_says_one_fund() -> None:
    from quant_trade.audit.plan import _multiplicity_step

    data = {
        "fund": {"track_record": True},
        "multiplicity": {
            "status": "MEASURED",
            "trials_used": {"value": 1, "evidence": "DECLARED"},
            "dsr_at_trials_used": {"value": 0.2, "evidence": "MEASURED"},
            "trials_to_half": {"value": 1, "evidence": "MEASURED"},
        },
    }
    expected = {
        "es": "Ya con 1 cartera, el caso más favorable",
        "en": "Even at 1 portfolio, the most favourable case",
        "pt": "Já com 1 carteira, o caso mais favorável",
    }
    for locale in LOCALES:
        finding, _ = _multiplicity_step(data, "FAIL", locale)
        assert expected[locale] in finding
        assert "o más fondos" not in finding and "or more funds" not in finding
        assert find_claims(finding) == []
