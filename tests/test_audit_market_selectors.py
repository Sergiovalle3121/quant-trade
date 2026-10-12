"""Account and report billing selectors show only approved, localized countries."""

from __future__ import annotations

import re
import unicodedata
from html import unescape
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("sqlalchemy")

from audit_fixtures import csv_bytes, positive_drift, signed_in  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from quant_trade.audit.card_markets import MARKET_NAMES, REVIEWED_MARKETS  # noqa: E402
from quant_trade.audit.guard import find_claims  # noqa: E402
from quant_trade.audit.settings import AuditSettings  # noqa: E402
from quant_trade.audit.store import make_store  # noqa: E402
from quant_trade.audit.web import create_app  # noqa: E402

ACCOUNT_PATHS = {"es": "/cuenta", "en": "/account", "pt": "/pt/conta"}


def _client_and_report(tmp_path: Path, markets: frozenset[str]) -> tuple[TestClient, str]:
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db",
        bootstrap_samples=100,
        stripe_secret_key="sk_live_x",
        stripe_webhook_secret="whsec_test",
        free_mode=False,
        approved_markets=markets,
        base_url="https://rigor.example",
    )
    client = signed_in(TestClient(create_app(settings, make_store(settings.database_url))))
    response = client.post(
        "/audits",
        files={"equity": ("equity.csv", csv_bytes(positive_drift(500)), "text/csv")},
        data={"trials": "3", "cost_bps": "5", "consent": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = urlsplit(response.headers["location"])
    token = parse_qs(location.query)["token"][0]
    return client, f"{location.path}?{urlencode({'token': token})}"


def _options(page: str) -> list[tuple[str, str]]:
    select = re.search(r"<select[^>]+name='billing_country'[^>]*>(.*?)</select>", page, re.S)
    assert select is not None
    return [
        (code, unescape(name))
        for code, name in re.findall(
            r"<option value='([A-Z]{2})'>([^<]+)</option>", select.group(1)
        )
    ]


def _name_sort_key(name: str) -> str:
    return "".join(
        char
        for char in unicodedata.normalize("NFD", name.casefold())
        if not unicodedata.combining(char)
    )


def test_account_and_report_selectors_show_every_reviewed_market_in_each_language(
    tmp_path: Path,
) -> None:
    client, report_url = _client_and_report(tmp_path, REVIEWED_MARKETS)
    for locale, account_path in ACCOUNT_PATHS.items():
        for url in (account_path, f"{report_url}&lang={locale}"):
            response = client.get(url)
            assert response.status_code == 200
            options = _options(response.text)
            assert len(options) == len(REVIEWED_MARKETS) == 31
            assert {code for code, _ in options} == REVIEWED_MARKETS
            assert [code for code, _ in options[:3]] == ["MX", "US", "BR"]
            names = [name for _, name in options[3:]]
            assert names == sorted(names, key=_name_sort_key)
            assert all(name == MARKET_NAMES[code][locale] for code, name in options)
            assert "Declarado ·" not in response.text
            assert find_claims(response.text) == []


def test_both_selectors_use_only_approved_countries_and_sort_by_page_language(
    tmp_path: Path,
) -> None:
    markets = frozenset({"US", "DE", "FR", "GB", "AT", "ES", "SE"})
    client, report_url = _client_and_report(tmp_path, markets)
    expected = {
        "es": ["US", "DE", "AT", "ES", "FR", "GB", "SE"],
        "en": ["US", "AT", "FR", "DE", "ES", "SE", "GB"],
        "pt": ["US", "DE", "AT", "ES", "FR", "GB", "SE"],
    }
    for locale, account_path in ACCOUNT_PATHS.items():
        for url in (account_path, f"{report_url}&lang={locale}"):
            options = _options(client.get(url).text)
            assert [code for code, _ in options] == expected[locale]
            assert {code for code, _ in options} == markets
