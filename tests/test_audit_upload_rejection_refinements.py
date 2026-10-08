"""Unreadable values and untouched defaults keep upload refusals actionable."""

from __future__ import annotations

from html import unescape
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from quant_trade.audit import web
from quant_trade.audit.guard import find_claims
from quant_trade.audit.prop_presets import DEFAULT_PRESET, PRESETS
from quant_trade.audit.schema import ParseError, parse_equity_csv
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.upload_rejections import REJECTION_COPY, rejection_guidance
from quant_trade.audit.web import create_app


def _app(tmp_path: Path) -> Any:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        free_mode=True,
        bootstrap_samples=100,
    )
    return create_app(settings, make_store(settings.database_url))


@pytest.mark.parametrize(
    ("rows", "expected_code"),
    (
        ("2024-01-01,abc\n2024-01-02,def\n", "invalid_values"),
        ("2024-01-01,100\n2024-01-02,def\n", "invalid_values"),
        ("2024-01-01,inf\n2024-01-02,100\n", "invalid_values"),
        ("2024-01-01,100\n", "too_few_rows"),
        ("2024-01-01,100\n2024-01-01,101\n", "too_few_rows"),
        ("2024-01-01,100\nnot-a-date,101\n", "too_few_rows"),
    ),
)
def test_row_shortage_distinguishes_unreadable_values_from_too_few_dates(
    rows: str, expected_code: str
) -> None:
    with pytest.raises(ParseError) as caught:
        parse_equity_csv(f"timestamp,equity\n{rows}".encode())
    assert caught.value.code == expected_code
    for locale in ("es", "en", "pt"):
        assert find_claims(caught.value.localized(locale)) == []


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
@pytest.mark.parametrize("values", (("abc", "def"), ("100", "def")))
def test_unreadable_numeric_rows_use_invalid_value_guidance_over_http(
    tmp_path: Path, locale: str, values: tuple[str, str]
) -> None:
    app = _app(tmp_path)
    content = f"timestamp,equity\n2024-01-01,{values[0]}\n2024-01-02,{values[1]}\n".encode()
    with TestClient(app) as client:
        response = client.post(
            "/audits",
            files={"equity": ("curve.csv", content)},
            data={"consent": "on", "locale": locale},
        )
        assert response.status_code == 400
        assert rejection_guidance("invalid_values", "csv", locale) in response.text
        assert 'data-upload-rejection="too_few_rows"' not in response.text
        assert REJECTION_COPY[locale]["too_few_rows"][1] not in unescape(response.text)
        assert find_claims(response.text) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert row["category"] == "invalid_values"
        assert row["detected_format"] == "csv"
        assert row["detector"] == "schema"


@pytest.mark.parametrize("locale", ("es", "en", "pt"))
@pytest.mark.parametrize(
    ("changed_fields", "advanced_open", "extras_open"),
    (
        ({}, False, False),
        ({"benchmark_applicable": "no"}, True, False),
        ({"cost_bps": "2.5"}, True, False),
        ({"description": "Synthetic declaration"}, True, False),
        (
            {"challenge": next(preset for preset in PRESETS if preset != DEFAULT_PRESET)},
            False,
            True,
        ),
    ),
)
def test_rejected_form_opens_only_sections_with_nondefault_declarations(
    tmp_path: Path,
    locale: str,
    changed_fields: dict[str, str],
    advanced_open: bool,
    extras_open: bool,
) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.post(
            "/audits",
            files={"report": ("image.png", b"\x89PNG\r\n\x1a\n")},
            data={
                "consent": "on",
                "locale": locale,
                "benchmark_applicable": "yes",
                "challenge": DEFAULT_PRESET,
                **changed_fields,
            },
        )
    assert response.status_code == 400
    assert ("<details class='adv' open>" in response.text) == advanced_open
    assert ("<details class='adv extras' open>" in response.text) == extras_open
    assert ("<details class='adv'>" in response.text) == (not advanced_open)
    assert ("<details class='adv extras'>" in response.text) == (not extras_open)
    assert find_claims(response.text) == []


@pytest.mark.parametrize(("field", "detector"), (("equity", "schema"), ("report", "importers")))
@pytest.mark.parametrize("error_type", (ParseError, RuntimeError))
def test_unexpected_parse_failure_uses_the_same_detector_as_a_known_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    detector: str,
    error_type: type[Exception],
) -> None:
    def broken(*args: Any, **kwargs: Any) -> Any:
        if error_type is ParseError:
            raise ParseError("Too few rows.", message_es="Hay pocas filas.", code="too_few_rows")
        raise error_type("PRIVATE-parser-detail")

    monkeypatch.setattr(web, "build_inputs", broken)
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/audits",
            files={field: ("PRIVATE-file.csv", b"timestamp,equity\n2024-01-01,100\n")},
            data={"consent": "on"},
            headers={"Accept": "application/json"},
        )
        assert response.status_code == 400
        category = "too_few_rows" if error_type is ParseError else "invalid_upload"
        assert response.json()["category"] == category
        assert response.json()["guidance_html"] == rejection_guidance(category, "csv", "es")
        assert "PRIVATE" not in response.text
        assert find_claims(response.text) == []
        app.state.operations.flush()
        (row,) = app.state.store.upload_rejection_rows("2000-01-01")
        assert row["detector"] == detector
