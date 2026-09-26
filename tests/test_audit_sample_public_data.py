"""The sample report (/ejemplo, /sample, /pt/exemplo and their PDFs) shows the
public-data lines an upload gets, from the series already in memory; it never
waits on the network and stays the offline sample until a download lands."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from quant_trade.audit import web
from quant_trade.audit.market import CASH, MarketData
from quant_trade.audit.report import LABELS
from quant_trade.audit.sample import sample_result
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store

DAYS = pd.bdate_range("2015-01-01", "2027-01-01")
BILLS = "DATE,DTB3\n" + "".join(f"{day:%Y-%m-%d},4.00\n" for day in DAYS)
CASH_WORDS = LABELS["es"]["cash_sharpe"].split("(")[0].strip()


def _bills_only(series: str) -> str:
    if series != CASH.series:
        raise OSError("offline test: only the bill rate is served")
    return BILLS


class _Offline(MarketData):
    """Nothing in memory and no download ever succeeds."""

    def __init__(self) -> None:
        super().__init__(self._refuse)

    @staticmethod
    def _refuse(series: str) -> str:
        raise OSError("offline test")

    def warm(self):  # type: ignore[no-untyped-def]
        return None


class _Warmed(MarketData):
    """The bill rate in memory before the first request, as after the
    service's start-up download."""

    def __init__(self) -> None:
        super().__init__(_bills_only)

    def warm(self):  # type: ignore[no-untyped-def]
        self.refresh(CASH.key)
        return None


def _client(tmp_path: Path, monkeypatch, market: type[MarketData], public: bool = True):
    monkeypatch.setattr(web, "MarketData", market)
    settings = AuditSettings(
        database_url=f"sqlite:///{tmp_path}/audit.db", bootstrap_samples=60, public_data=public
    )
    return TestClient(web.create_app(settings, make_store(settings.database_url)))


def test_the_sample_reads_public_series_when_given_them() -> None:
    data = MarketData(_bills_only)
    assert data.ready() == ()
    assert data.refresh(CASH.key) and data.ready() == (CASH.key,)
    offline = sample_result("es", bootstrap_samples=60)
    online = sample_result("es", bootstrap_samples=60, market=data.closes)
    assert offline.cash_rate is None
    assert online.cash_rate is not None and online.cash_rate["status"] == "MEASURED"
    # Nothing else in the sample moves.
    assert online.verdict.overall == offline.verdict.overall
    assert online.performance == offline.performance


def test_the_sample_page_shows_the_cash_line_once_the_rate_is_in_memory(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch, _Warmed)
    for path in ("/ejemplo", "/pt/exemplo"):
        page = client.get(path)
        assert page.status_code == 200
    assert CASH_WORDS in client.get("/ejemplo").text


def test_the_sample_page_stays_offline_without_public_data(tmp_path: Path, monkeypatch) -> None:
    off = _client(tmp_path, monkeypatch, _Warmed, public=False)
    assert CASH_WORDS not in off.get("/ejemplo").text
    # Public data on but nothing downloaded yet: the offline sample, served at once.
    cold = _client(tmp_path / "cold", monkeypatch, _Offline)
    page = cold.get("/ejemplo")
    assert page.status_code == 200 and CASH_WORDS not in page.text


def test_the_sample_keeps_only_the_current_set_of_series(tmp_path: Path, monkeypatch) -> None:
    """A page built before the rate arrived is dropped once it is in memory."""
    holder: dict[str, MarketData] = {}

    class _Late(_Offline):
        def __init__(self) -> None:
            MarketData.__init__(self, _bills_only)
            holder["data"] = self

    client = _client(tmp_path, monkeypatch, _Late)
    assert CASH_WORDS not in client.get("/ejemplo").text
    assert holder["data"].refresh(CASH.key)
    assert CASH_WORDS in client.get("/ejemplo").text
    assert CASH_WORDS in client.get("/ejemplo").text
