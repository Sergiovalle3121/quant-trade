"""Shared test setup: nothing reaches the network."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_public_market_data(monkeypatch: pytest.MonkeyPatch) -> None:
    """Public market closes are never downloaded in tests (``audit/market.py``)."""

    def refuse(series: str, *_: object) -> str:
        raise RuntimeError(f"network is off in tests (asked for {series})")

    monkeypatch.setattr("quant_trade.audit.market._download", refuse)
