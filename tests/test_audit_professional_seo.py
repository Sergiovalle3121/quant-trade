"""Professional search metadata remains concise, specific and claim-free."""

from __future__ import annotations

import html
import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", base_url="https://audit.example"
    )
    return TestClient(create_app(settings, make_store(settings.database_url)))


@pytest.mark.parametrize(
    ("path", "title_phrase", "description_phrase"),
    [
        (
            "/en",
            "independent backtest audit",
            "statistical review of a trading strategy",
        ),
        ("/calculator", "deflated Sharpe ratio", "deflated Sharpe ratio"),
        (
            "/en/examples",
            "trading strategy review",
            "statistical review of a trading strategy",
        ),
        (
            "/for/funds-and-signal-providers",
            "independent backtest audit",
            "statistical review of a trading strategy",
        ),
        (
            "/articles/independent-backtest-audit",
            "independent backtest audit",
            "statistical review of a trading strategy",
        ),
        (
            "/articles/deflated-sharpe-ratio-track-record",
            "deflated Sharpe ratio",
            "deflated Sharpe ratio",
        ),
        (
            "/articles/audit-model-portfolio-signal-track-record",
            "independent backtest audit",
            "independent backtest audit",
        ),
    ],
)
def test_professional_metadata_lengths_phrases_and_guard(
    client: TestClient, path: str, title_phrase: str, description_phrase: str
) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "<html lang='en'>" in response.text
    title_match = re.search(r"<title>([^<]+)</title>", response.text)
    description_match = re.search(r"<meta name='description' content='([^']*)'>", response.text)
    assert title_match and description_match
    title = html.unescape(title_match.group(1))
    description = html.unescape(description_match.group(1))
    assert 1 <= len(title) <= 60
    assert 1 <= len(description) <= 155
    assert title.lower().count(title_phrase.lower()) == 1
    assert description.lower().count(description_phrase.lower()) == 1
    for key, value in (("title", title), ("description", description)):
        for prefix in ("og", "twitter"):
            assert f"'{prefix}:{key}' content='{html.escape(value, quote=True)}'" in response.text
        assert find_claims(value) == []
    assert f"rel='canonical' href='https://audit.example{path}'" in response.text
    assert find_claims(html.unescape(response.text)) == []
