"""Offline tests for the ccxt crypto provider (no network, fake exchange)."""

from __future__ import annotations

import pandas as pd
import pytest

from quant_trade.data.providers.base import get_data_provider
from quant_trade.data.providers.ccxt_provider import (
    CcxtProvider,
    CcxtProviderError,
    to_ccxt_symbol,
)
from quant_trade.data.requests import HistoricalDataRequest

_DAY_MS = 86_400_000
_START_MS = 1_577_836_800_000  # 2020-01-01T00:00:00Z


class FakeExchange:
    """Deterministic in-memory exchange serving daily bars in pages."""

    def __init__(self, bars_by_symbol: dict[str, int], page_size: int = 5, fail_first: int = 0):
        self.bars_by_symbol = bars_by_symbol
        self.page_size = page_size
        self.remaining_failures = fail_first
        self.calls = 0
        self.has = {"fetchFundingRateHistory": True}

    def _bars(self, symbol: str) -> list[list[float]]:
        count = self.bars_by_symbol[symbol]
        return [
            [_START_MS + i * _DAY_MS, 100.0 + i, 101.0 + i, 99.0 + i, 100.5 + i, 1000.0]
            for i in range(count)
        ]

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.calls += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise ConnectionError("transient network blip")
        if symbol not in self.bars_by_symbol:
            return []
        rows = [r for r in self._bars(symbol) if r[0] >= (since or 0)]
        return rows[: min(limit or self.page_size, self.page_size)]

    def fetch_funding_rate_history(self, symbol, since=None, limit=None):
        self.calls += 1
        rows = [
            {"timestamp": _START_MS + i * (_DAY_MS // 3), "fundingRate": 0.0001 * (i % 5 - 2)}
            for i in range(12)
        ]
        rows = [r for r in rows if r["timestamp"] >= (since or 0)]
        return rows[: min(limit or self.page_size, self.page_size)]


def _request(symbols: list[str], end: str = "2020-01-20") -> HistoricalDataRequest:
    return HistoricalDataRequest(
        provider="ccxt-fake", symbols=symbols, start="2020-01-01", end=end, interval="1d"
    )


def test_symbol_mapping():
    assert to_ccxt_symbol("BTC-USD") == "BTC/USD"
    assert to_ccxt_symbol("btc-usdt") == "BTC/USDT"
    assert to_ccxt_symbol("ETH-USDT-PERP") == "ETH/USDT:USDT"
    with pytest.raises(ValueError):
        to_ccxt_symbol("BTCUSD")


def test_fetch_ohlcv_paginates_past_page_limit():
    fake = FakeExchange({"BTC/USD": 12}, page_size=5)
    provider = CcxtProvider("fake", client=fake)
    frame = provider.fetch_ohlcv(_request(["BTC-USD"]))
    assert len(frame) == 12
    assert frame["provider"].unique().tolist() == ["ccxt-fake"]
    assert frame["timestamp"].is_monotonic_increasing
    # pagination must walk the since-cursor, not refetch page one forever
    assert fake.calls >= 3


def test_fetch_ohlcv_retries_transient_errors():
    fake = FakeExchange({"BTC/USD": 6}, page_size=10, fail_first=2)
    provider = CcxtProvider("fake", client=fake)
    frame = provider.fetch_ohlcv(_request(["BTC-USD"]))
    assert len(frame) == 6


def test_fetch_ohlcv_fails_loudly_on_partial_panel():
    fake = FakeExchange({"BTC/USD": 6}, page_size=10)
    provider = CcxtProvider("fake", client=fake)
    with pytest.raises(CcxtProviderError, match="partial panel"):
        provider.fetch_ohlcv(_request(["BTC-USD", "MISSING-USD"]))


def test_fetch_ohlcv_respects_date_range():
    fake = FakeExchange({"BTC/USD": 30}, page_size=50)
    provider = CcxtProvider("fake", client=fake)
    frame = provider.fetch_ohlcv(_request(["BTC-USD"], end="2020-01-10"))
    assert frame["timestamp"].max() <= pd.Timestamp("2020-01-10T23:59:59", tz="UTC")


def test_fetch_funding_rates_schema_and_perp_guard():
    fake = FakeExchange({"BTC/USDT:USDT": 5}, page_size=5)
    provider = CcxtProvider("fake", client=fake)
    from datetime import date

    frame = provider.fetch_funding_rates(["BTC-USDT-PERP"], date(2020, 1, 1), date(2020, 1, 10))
    assert list(frame.columns) == ["timestamp", "symbol", "funding_rate", "provider"]
    assert (frame["symbol"] == "BTC-USDT-PERP").all()
    assert frame["timestamp"].is_monotonic_increasing
    with pytest.raises(ValueError, match="perpetuals only"):
        provider.fetch_funding_rates(["BTC-USDT"], date(2020, 1, 1), date(2020, 1, 10))


def test_registry_resolves_ccxt_exchanges():
    provider = get_data_provider("ccxt-binance")
    assert isinstance(provider, CcxtProvider)
    assert provider.exchange_id == "binance"
    assert provider.name == "ccxt-binance"
    assert provider.supports_interval("4h")
    assert not provider.supports_interval("2w")


def test_end_to_end_crypto_pipeline_fetch_cache_research(tmp_path):
    """Full offline crypto path: fake exchange -> cache -> research backtest."""
    from quant_trade.data.cache import write_cache
    from quant_trade.research.multi_asset_runner import run_multi_asset_research_experiment

    fake = FakeExchange({"BTC/USD": 200, "ETH/USD": 200}, page_size=90)
    provider = CcxtProvider("fake", client=fake)
    request = HistoricalDataRequest(
        provider="ccxt-fake",
        symbols=["BTC-USD", "ETH-USD"],
        start="2020-01-01",
        end="2020-07-01",
        interval="1d",
        output_dir=str(tmp_path / "cache"),
    )
    data = provider.fetch_ohlcv(request)
    cache_path = write_cache(data, request)
    assert cache_path.exists()
    assert cache_path.with_suffix(".manifest.json").exists()

    config = {
        "mode": "multi_asset_research",
        "experiment_name": "crypto_e2e",
        "data_path": str(cache_path),
        "strategy": "time_series_momentum",
        "strategy_params": {"lookback_days": 21, "rebalance_frequency": "weekly"},
        "initial_cash": 100_000,
        "costs": {"percentage_commission": 0.0010, "slippage_bps": 5.0, "spread_bps": 3.0},
        "output_dir": str(tmp_path / "outputs"),
    }
    result = run_multi_asset_research_experiment(config)
    assert result["symbols"] == ["BTC-USD", "ETH-USD"]
    assert result["dataset_binding"]["data_sha256"]
    assert "sharpe" in result["test_metrics"]
