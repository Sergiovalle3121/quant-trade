"""An upload from /pt is refused in Portuguese, and /pt's error pages are Portuguese."""

from __future__ import annotations

import ast
import html
import io
import re
import zipfile
from pathlib import Path

import pytest
from audit_fixtures import csv_bytes, positive_drift

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import errors_pt  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.importers import ReportFormatError  # noqa: E402
from quant_trade.audit.mapping import COPY as MAPPING_COPY  # noqa: E402
from quant_trade.audit.pages import error_page, landing  # noqa: E402
from quant_trade.audit.schema import ParseError  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import MESSAGES, create_app  # noqa: E402

AUDIT = Path(__file__).resolve().parents[1] / "src" / "quant_trade" / "audit"
#: The calls that raise an upload refusal, and which argument is the English.
REFUSALS = {"ParseError": 0, "ReportFormatError": 1, "imp.ReportFormatError": 1, "_no_grid": 0}
LEGACY_XLS = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 600


def _zip(*names: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name in names:
            archive.writestr(name, "time,profit\n2024-01-02,5\n")
    return buffer.getvalue()


def _template(node: ast.expr) -> str | None:
    """The English of a literal or f-string, each value as ``{x}``."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "{x}" for part in node.values
        )
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _template(node.left), _template(node.right)
        return None if left is None or right is None else left + right
    return None


def _refusals() -> list[tuple[str, str]]:
    found = []
    for path in sorted(AUDIT.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            at = REFUSALS.get(ast.unparse(node.func))
            if at is None or len(node.args) <= at:
                continue
            english = _template(node.args[at])
            if english is not None:
                found.append((f"{path.name}:{node.lineno}", english.replace("{x}", "X1")))
    return found


def test_every_refusal_the_importers_write_has_its_portuguese() -> None:
    refusals = _refusals()
    assert len(refusals) >= 60
    missing = [
        (where, text)
        for where, text in refusals
        # The live statement's wrapper is checked with a real refusal inside, below.
        if text != errors_pt.LIVE_PREFIX[0] + "X1" and errors_pt.portuguese(text) is None
    ]
    assert missing == []


def test_refusals_built_from_parts_have_their_portuguese() -> None:
    samples = {
        MAPPING_COPY["en"]["few_rows"]: "Seu arquivo: com essas colunas",
        "the trades file is missing column(s): quantity (entry_time, exit_time, quantity, "
        "entry_price, exit_price are required)": "faltam colunas no arquivo de operações",
        "the file has no closed trades: 1 position opened and never closed in the file": (
            "1 posição foi aberta"
        ),
        "the file has no closed trades: 4 positions opened and never closed in the file": (
            "4 posições foram abertas"
        ),
        "the live account statement: the zip is damaged or encrypted and could not be read": (
            "extrato da conta real: o zip está danificado"
        ),
    }
    for english, portuguese in samples.items():
        assert portuguese in (errors_pt.portuguese(english) or ""), english


def test_fixed_words_inside_a_refusal_are_translated_too() -> None:
    assert errors_pt.portuguese("the equity file is empty") == (
        "o arquivo da curva de equity está vazio"
    )
    text = errors_pt.portuguese(
        "the column 'Hora' was chosen for two fields (entry time and exit time); "
        "choose a different column for each"
    )
    assert text is not None and "(hora de entrada e hora de saída)" in text
    text = errors_pt.portuguese('the column "Lotes" you chose as quantity holds no numbers')
    assert text == 'a coluna "Lotes" que você escolheu como quantidade não tem números'


def test_an_unknown_refusal_stays_in_english_never_half_translated() -> None:
    error = ParseError("something no rule knows", message_es="algo", code="x")
    assert error.localized("pt") == "something no rule knows"
    assert error.localized("es") == "algo"
    assert error.localized("en") == "something no rule knows"
    known = ReportFormatError(
        "bad_zip", "the zip is damaged or encrypted and could not be read", ""
    )
    assert known.localized("pt") == "o zip está danificado ou criptografado e não pôde ser lido"


def test_the_portuguese_refusals_and_messages_pass_the_guard() -> None:
    for _, portuguese in errors_pt.RULES:
        assert find_claims(portuguese) == [], portuguese
    for key, texts in MESSAGES.items():
        assert "pt" in texts, key
        assert find_claims(texts["pt"]) == [], key


def _client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", free_mode=True, bootstrap_samples=100
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


def _text(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def test_the_pt_form_sends_the_portuguese_language() -> None:
    page = landing(locale="pt", free_mode=True)
    assert "<option value='pt' selected>Português</option>" in page


@pytest.mark.parametrize(
    ("files", "expected"),
    [
        ({"report": ("conta.xls", LEGACY_XLS, "application/vnd.ms-excel")}, "planilha antiga"),
        ({"report": ("conta.zip", _zip("a.csv", "b.csv"), "application/zip")}, "2 exportações"),
        ({"equity": ("curva.csv", b"", "text/csv")}, "Falta o arquivo"),
    ],
)
def test_an_upload_from_pt_is_refused_in_portuguese(
    tmp_path: Path, files: dict[str, tuple[str, bytes, str]], expected: str
) -> None:
    client = _client(tmp_path)
    data = {"trials": "3", "consent": "on", "locale": "pt"}
    response = client.post("/audits", files=files, data=data)
    assert response.status_code == 400, response.text[:300]
    assert "<html lang='pt'>" in response.text
    text = _text(response.text)
    assert expected in text
    assert "Não foi possível auditar" in text
    assert "the file" not in text.lower() and "el archivo" not in text.lower()


def test_the_same_upload_in_spanish_and_english_is_unchanged(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"report": ("conta.xls", LEGACY_XLS, "application/vnd.ms-excel")}
    for locale, expected in (("es", "libro de Excel antiguo"), ("en", "old Excel workbook")):
        data = {"trials": "3", "consent": "on", "locale": locale}
        response = client.post("/audits", files=files, data=data)
        assert expected in _text(response.text), locale


def test_a_pt_upload_without_consent_is_answered_in_portuguese(tmp_path: Path) -> None:
    client = _client(tmp_path)
    files = {"equity": ("curva.csv", csv_bytes(positive_drift(300)), "text/csv")}
    response = client.post("/audits", files=files, data={"locale": "pt"})
    assert response.status_code == 400
    assert "Você precisa aceitar as condições" in _text(response.text)


def test_the_error_card_splits_a_portuguese_fix_into_what_to_do() -> None:
    page = error_page(
        errors_pt.portuguese(
            "the zip holds 2 exports; upload the one with the trades on its own (CSV, Excel "
            "or HTML)"
        )
        or "",
        locale="pt",
    )
    assert "O que fazer:" in page
    assert find_claims(_text(page)) == []


def test_a_missing_pt_page_says_so_in_portuguese(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get("/pt/nao-existe")
    assert response.status_code == 404
    assert "<html lang='pt'>" in response.text
    assert "Página não encontrada" in _text(response.text)
    # The bar offers Spanish and English; Spanish pages keep their own.
    assert "href='/' hreflang='es'" in response.text
    assert "href='/en' hreflang='en'" in response.text
    spanish = client.get("/no-existe")
    assert "<html lang='es'>" in spanish.text and "Página no encontrada" in spanish.text


def test_the_pt_trust_cards_open_the_portuguese_sample(tmp_path: Path) -> None:
    page = _client(tmp_path).get("/pt").text
    trust = page.split("class='card spot'", 1)[1] if "class='card spot'" in page else page
    assert "/pt/exemplo" in trust
    assert "/sample?lang=en" not in page
