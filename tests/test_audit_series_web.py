"""Return-table uploads and calculator frequency through the real web forms."""

from __future__ import annotations

import io
import math
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pandas as pd
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit import web  # noqa: E402
from quant_trade.audit.calculator import CalculatorInput, compute  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402


def _client(tmp_path: Path) -> TestClient:
    cfg = AuditSettings(database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=100)
    return TestClient(web.create_app(cfg, make_store(cfg.database_url)))


def _monthly_file(kind: str) -> bytes:
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2022-01-31", periods=24, freq="ME").strftime("%Y-%m-%d"),
            "return": [1.0, -2.0, 3.0, 1.5] * 6,
        }
    )
    if kind == "csv":
        return frame.to_csv(index=False).encode()
    output = io.BytesIO()
    rows = [list(frame.columns), *frame.itertuples(index=False, name=None)]
    xml_rows = []
    for index, row in enumerate(rows, 1):
        cells = "".join(
            f'<c r="{chr(65 + column)}{index}" t="inlineStr">'
            f"<is><t>{escape(str(value))}</t></is></c>"
            for column, value in enumerate(row)
        )
        xml_rows.append(f'<row r="{index}">{cells}</row>')
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Returns" sheetId="1" r:id="rId1"/></sheets></workbook>',
        )
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(xml_rows)}</sheetData></worksheet>",
        )
    return output.getvalue()


@pytest.mark.parametrize("field,kind", [("report", "csv"), ("report", "xlsx"), ("equity", "xlsx")])
def test_primary_picker_detects_monthly_returns_before_platform_sniffing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    kind: str,
) -> None:
    original = web.run_audit

    def small_audit(*args, **kwargs):
        return original(*args, **kwargs, risk_samples=100, challenge_samples=100)

    monkeypatch.setattr(web, "run_audit", small_audit)
    client = _client(tmp_path)
    answer = client.post(
        "/audits",
        files={field: (f"periods.{kind}", _monthly_file(kind))},
        data={"consent": "on", "return_frequency": "monthly", "return_unit": "percent"},
        follow_redirects=False,
    )
    assert answer.status_code == 303, answer.text[:500]
    location = answer.headers["location"]
    path, _, query = location.partition("?")
    report = client.get(f"{path}.json?{query}")
    assert report.status_code == 200
    result = report.json()
    conventions = result["inputs"]["return_series"]
    assert conventions["frequency"]["value"] == "monthly"
    assert conventions["frequency"]["evidence"] == "DECLARED"
    assert conventions["frequency_confirmed"]["value"] is True
    assert conventions["unit"]["value"] == "percent"
    assert conventions["unit"]["evidence"] == "DECLARED"
    assert conventions["unit_confirmed"]["value"] is True
    assert result["inputs"]["observations"]["value"] == 24
    assert result["inputs"]["periods_per_year"]["value"] == 12
    assert result["inputs"]["periods_per_year"]["evidence"] == "DECLARED"
    assert result["inputs"]["return_series"]["unit"]["value"] == "percent"
    returns = pd.Series([0.01, -0.02, 0.03, 0.015] * 6)
    expected = float(returns.mean() / returns.std(ddof=1) * math.sqrt(12))
    assert result["performance"]["sharpe"]["value"] == pytest.approx(expected)
    page = client.get(location)
    assert page.status_code == 200
    assert find_claims(page.text) == []


@pytest.mark.parametrize("locale", ["es", "en", "pt"])
def test_declared_frequency_mismatch_is_a_localized_safe_error(tmp_path: Path, locale: str) -> None:
    client = _client(tmp_path)
    answer = client.post(
        "/audits",
        files={"report": ("periods.csv", _monthly_file("csv"))},
        data={
            "consent": "on",
            "locale": locale,
            "return_frequency": "weekly",
            "return_unit": "percent",
        },
    )
    assert answer.status_code == 400
    assert find_claims(answer.text) == []
    assert {
        "es": "frecuencia elegida",
        "en": "selected return frequency",
        "pt": "frequência escolhida",
    }[locale] in answer.text


@pytest.mark.parametrize("path", ["/calculadora", "/calculator", "/pt/calculadora"])
def test_calculator_route_uses_the_frequency_query(tmp_path: Path, path: str) -> None:
    client = _client(tmp_path)
    answer = client.get(
        path, params={"sharpe": "1.8", "years": "3", "trials": "1000", "periods_per_year": "52"}
    )
    assert answer.status_code == 200
    assert "<option value='52' selected>" in answer.text
    result = compute(CalculatorInput(1.8, 3, 1000, 52))
    assert f"<td><b>{result['luck_sharpe']['value']:.2f}</b></td>" in answer.text
    assert find_claims(answer.text) == []
