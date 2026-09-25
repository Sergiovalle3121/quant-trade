"""The strategy beside simply holding the market it trades. Offline: closes are stubbed."""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from audit_fixtures import business_days, csv_bytes, trades_following

from quant_trade.audit import market as market_lib
from quant_trade.audit.engine import run_audit
from quant_trade.audit.guard import assert_report_clean, find_claims
from quant_trade.audit.holding import MIN_DAYS, sharpe_gap_se, versus_holding
from quant_trade.audit.i18n import untranslated
from quant_trade.audit.market import BY_KEY, MarketData, asset_of, dominant_asset, parse_fred_csv
from quant_trade.audit.market import _download as real_download
from quant_trade.audit.report import LABELS, render
from quant_trade.audit.schema import DeclaredMetadata, build_inputs
from quant_trade.audit.settings import AuditSettings


@pytest.mark.parametrize(
    ("name", "key"),
    [
        ("US100.cash", "nasdaq100"),
        ("NAS100m", "nasdaq100"),
        ("USTEC", "nasdaq100"),
        ("NQZ4", "nasdaq100"),
        ("NQ 12-24", "nasdaq100"),
        ("MNQ", "nasdaq100"),
        ("US500", "sp500"),
        ("SPX500_i", "sp500"),
        ("ESH25", "sp500"),
        ("BTCUSDT", "bitcoin"),
        ("XBTUSD", "bitcoin"),
        ("EURUSD", None),
        ("ES35", None),
        ("ESP35", None),
        ("", None),
    ],
)
def test_symbol_names_map_to_a_public_market(name: str, key: str | None) -> None:
    asset = asset_of(name)
    assert (asset.key if asset else None) == key


def test_one_market_must_carry_two_thirds_of_the_trades() -> None:
    assert dominant_asset(["US100"] * 7 + ["EURUSD"] * 3).key == "nasdaq100"  # type: ignore[union-attr]
    assert dominant_asset(["US100"] * 6 + ["EURUSD"] * 4) is None
    assert dominant_asset(None, "BTCUSD").key == "bitcoin"  # type: ignore[union-attr]
    assert dominant_asset(None, "") is None


def test_fred_csv_drops_blanks() -> None:
    series = parse_fred_csv("observation_date,SP500\n2024-01-02,4742.83\n2024-01-03,.\n")
    assert list(series.round(2)) == [4742.83]


def test_market_data_caches_and_keeps_the_last_good_copy() -> None:
    calls: list[str] = []
    now = [0.0]
    replies = ["DATE,V\n2024-01-02,10\n2024-01-03,11\n"]

    def fetch(series: str) -> str:
        calls.append(series)
        if not replies:
            raise OSError("down")
        return replies.pop()

    data = MarketData(fetch, max_age=100.0, clock=lambda: now[0])
    first = data.closes("sp500")
    assert first is not None and len(first) == 2 and calls == ["SP500"]
    assert data.closes("sp500") is first and calls == ["SP500"]
    now[0] = 500.0  # stale: FRED is down, the last good copy stays
    assert data.closes("sp500") is first and calls == ["SP500", "SP500"]
    assert data.closes("unknown") is None
    assert MarketData(lambda s: "junk").closes("bitcoin") is None


def test_the_tests_never_reach_the_network() -> None:
    assert MarketData().closes("sp500") is None


def test_the_service_reads_public_data_unless_turned_off() -> None:
    assert AuditSettings.from_env({}).public_data is True
    assert AuditSettings.from_env({"AUDIT_PUBLIC_DATA": "false"}).public_data is False
    assert AuditSettings().public_data is False


def _market(n: int = 400, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        100 * np.cumprod(1 + rng.normal(0.0006, 0.012, n)), index=business_days(n).tz_localize(None)
    )


def _curve(returns: np.ndarray, days: pd.DatetimeIndex) -> pd.DataFrame:
    stamps = pd.DatetimeIndex(days).tz_localize("UTC") + pd.Timedelta(hours=21)
    return pd.DataFrame({"timestamp": stamps, "equity": 10_000 * np.cumprod(1 + returns)})


def test_a_leveraged_copy_of_the_market_rides_it() -> None:
    closes = _market()
    moves = np.r_[0.0, closes.pct_change().dropna().to_numpy()]
    out = versus_holding(_curve(2 * moves, closes.index), closes, BY_KEY["nasdaq100"])
    assert out["status"] == "MEASURED"
    assert out["correlation"]["value"] == pytest.approx(1.0, abs=0.01)
    assert out["beta"]["value"] == pytest.approx(2.0, rel=0.05)
    assert out["strategy_sharpe_shared_days"]["value"] == pytest.approx(
        out["market_sharpe"]["value"]
    )
    assert "strategy_sharpe" not in out
    assert out["market_return"]["value"] == pytest.approx(closes.iloc[-1] / closes.iloc[0] - 1)
    assert out["findings"] == ["rides_the_market"]


def test_an_independent_strategy_with_more_per_unit_of_risk_does_not() -> None:
    closes = _market()
    own = np.random.default_rng(9).normal(0.002, 0.006, len(closes))
    out = versus_holding(_curve(own, closes.index), closes, BY_KEY["sp500"])
    assert out["status"] == "MEASURED"
    assert abs(out["correlation"]["value"]) < 0.3
    assert out["strategy_sharpe_shared_days"]["value"] > out["market_sharpe"]["value"]
    assert out["findings"] == []


def _calendar_market(days: pd.DatetimeIndex, seed: int) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.012, len(days))), index=days)


def test_a_seven_day_strategy_is_read_on_the_markets_trading_days() -> None:
    """Weekend moves roll into Monday instead of pairing with Friday's close."""
    every_day = pd.date_range("2022-01-03", periods=560, freq="D")
    closes = _calendar_market(pd.bdate_range(every_day[0], every_day[-1]), seed=4)
    along = closes.reindex(every_day).ffill().to_numpy()
    weekend = np.random.default_rng(5).normal(0, 0.012, len(every_day))
    moves = 1.5 * np.r_[0.0, along[1:] / along[:-1] - 1] + np.where(
        every_day.dayofweek >= 5, weekend, 0.0
    )
    out = versus_holding(_curve(moves, every_day), closes, BY_KEY["sp500"])
    assert out["status"] == "MEASURED"
    assert out["days"]["value"] == len(closes) - 1
    assert out["correlation"]["value"] > 0.7
    # A weekday strategy beside bitcoin's seven-day calendar stays on its own days.
    btc = _calendar_market(every_day, seed=6)
    weekdays = pd.bdate_range(every_day[0], every_day[-1])
    own = np.random.default_rng(7).normal(0.001, 0.01, len(weekdays))
    out = versus_holding(_curve(own, weekdays), btc, BY_KEY["bitcoin"])
    assert out["days"]["value"] == len(weekdays) - 1


def test_a_day_of_offset_between_the_closes_does_not_hide_the_link() -> None:
    """Broker time read as UTC: the strategy's day is one market day late."""
    closes = _market(600, seed=11)
    moves = np.r_[0.0, closes.pct_change().dropna().to_numpy()]
    late = closes.index[1:].append(pd.DatetimeIndex([closes.index[-1] + pd.offsets.BDay()]))
    out = versus_holding(_curve(1.5 * moves, late), closes, BY_KEY["nasdaq100"])
    daily = np.corrcoef(1.5 * moves[2:], moves[1:-1])[0, 1]
    assert abs(daily) < 0.3  # what the daily returns, paired a day apart, would have read
    assert out["correlation"]["value"] > 0.7
    assert out["findings"] == ["rides_the_market"]


def test_a_small_sharpe_gap_is_no_clear_edge_and_a_large_one_is() -> None:
    closes = _market(1260, seed=21)
    moves = np.r_[0.0, closes.pct_change().dropna().to_numpy()]
    rng = np.random.default_rng(22)
    small = moves + rng.normal(0.0003, 0.004, len(moves))
    out = versus_holding(_curve(small, closes.index), closes, BY_KEY["sp500"])
    gap = out["strategy_sharpe_shared_days"]["value"] - out["market_sharpe"]["value"]
    assert gap > 0.1  # the old rule would have let it pass
    assert out["sharpe_gap_in_se"]["value"] < 2
    assert out["findings"] == ["rides_the_market"]
    large = moves + rng.normal(0.0025, 0.004, len(moves))
    out = versus_holding(_curve(large, closes.index), closes, BY_KEY["sp500"])
    assert out["correlation"]["value"] >= 0.7
    assert out["sharpe_gap_in_se"]["value"] >= 2
    assert out["findings"] == []


def test_the_gap_standard_error_matches_the_textbook_formula() -> None:
    # Two identical ratios, correlation 0.9, 250 periods: sqrt((0.2 + 0.5·s²·(2 - 2·0.81)) / 250).
    assert sharpe_gap_se(0.1, 0.1, 0.9, 250) == pytest.approx(
        np.sqrt((0.2 + 0.5 * 0.01 * (2 - 2 * 0.81)) / 250)
    )


def test_too_few_shared_days_is_not_measured() -> None:
    closes = _market()
    days = closes.index[: MIN_DAYS - 10]
    out = versus_holding(_curve(np.full(len(days), 0.001), days), closes, BY_KEY["sp500"])
    assert out["status"] == "NOT_MEASURED"
    # Days far from any market close are not paired.
    later = pd.bdate_range("2035-01-01", periods=200)
    out = versus_holding(_curve(np.full(200, 0.001), later), closes, BY_KEY["sp500"])
    assert out["status"] == "NOT_MEASURED"


def _inputs(locale: str, symbol: str):  # type: ignore[no-untyped-def]
    closes = _market(600, seed=3)
    moves = np.r_[0.0, closes.pct_change().dropna().to_numpy()]
    curve = _curve(1.5 * moves, closes.index)
    inputs = build_inputs(
        csv_bytes(curve),
        DeclaredMetadata(locale=locale),
        trades_bytes=csv_bytes(trades_following(curve, every=10)),
    )
    count = len(inputs.trades.trades)
    return dataclasses.replace(inputs, trade_symbols=[symbol] * count), closes


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_report_shows_the_market_beside_the_strategy(locale: str) -> None:
    inputs, closes = _inputs(locale, "US100.cash")
    asked: list[str] = []

    def market(key: str) -> pd.Series:
        asked.append(key)
        return closes

    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=market)
    assert asked == ["nasdaq100"]
    assert result.holding is not None and result.holding["status"] == "MEASURED"
    assert result.holding["findings"] == ["rides_the_market"]
    html, _ = render(result, watermark=False)
    assert_report_clean(html)
    labels = LABELS[locale]
    assert labels["holding"] in html and "Nasdaq 100" in html
    assert "href='https://fred.stlouisfed.org/series/NASDAQ100'" in html
    assert labels["holding_rides"].split("({gap}")[0].format(label="Nasdaq 100") in html
    assert labels["holding_sharpe"].format(days=int(result.holding["days"]["value"])) in html
    assert untranslated(result.model_dump(mode="json")) == []
    for key, text in labels.items():
        if key.startswith("holding"):
            assert find_claims(text) == [], key


def test_without_market_data_or_a_known_market_there_is_no_section() -> None:
    inputs, closes = _inputs("es", "US100")
    result = run_audit(inputs, bootstrap_samples=200, risk_samples=300)
    assert result.holding is None
    html, _ = render(result, watermark=False)
    assert LABELS["es"]["holding"] not in html
    fx, _ = _inputs("es", "EURUSD")
    called: list[str] = []
    result = run_audit(
        fx, bootstrap_samples=200, risk_samples=300, market=lambda k: called.append(k) or closes
    )
    assert result.holding is None and called == []


@pytest.mark.parametrize("locale", ["es", "en"])
def test_fred_down_is_a_plain_not_measured_line(locale: str) -> None:
    inputs, _ = _inputs(locale, "US100")

    def broken(key: str) -> pd.Series:
        raise OSError("down")

    for market in (lambda k: None, broken):
        result = run_audit(inputs, bootstrap_samples=200, risk_samples=300, market=market)
        assert result.holding is not None and result.holding["status"] == "NOT_MEASURED"
        html, _ = render(result, watermark=False)
        assert_report_clean(html)
        assert LABELS[locale]["holding_not_measured"].split("{")[0] in html
        assert untranslated(result.model_dump(mode="json")) == []


class _Reply:
    def __init__(self, chunk: bytes, *, status: int = 200, count: int = 10**9) -> None:
        self.chunk, self.status, self.left = chunk, status, count

    def __enter__(self) -> _Reply:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if self.left <= 0:
            return b""
        self.left -= 1
        return self.chunk


def _serve(monkeypatch: pytest.MonkeyPatch, reply: _Reply, step: float = 0.0) -> None:
    clock = [0.0]

    def tick() -> float:
        clock[0] += step
        return clock[0]

    monkeypatch.setattr(market_lib.urllib.request, "urlopen", lambda url, timeout: reply)
    monkeypatch.setattr(market_lib.time, "monotonic", tick)


def test_a_server_that_trickles_is_cut_off_at_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _Reply(b"x" * 10), step=1.0)
    with pytest.raises(TimeoutError):
        real_download("SP500")


def test_a_huge_or_failed_reply_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _Reply(b"x" * 1_000_000))
    with pytest.raises(OSError, match="too large"):
        real_download("SP500")
    _serve(monkeypatch, _Reply(b"", status=429))
    with pytest.raises(OSError, match="429"):
        real_download("SP500")
    _serve(monkeypatch, _Reply(b"DATE,V\n2024-01-02,10\n", count=1))
    assert real_download("SP500").startswith("DATE")


def test_a_failure_is_not_retried_at_once_and_nobody_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    now = [0.0]

    def fetch(series: str) -> str:
        calls.append(series)
        return "<html>rate limited</html>"

    data = MarketData(fetch, retry_after=600.0, clock=lambda: now[0])
    assert data.closes("bitcoin") is None and len(calls) == 1
    now[0] = 300.0
    assert data.closes("bitcoin") is None and len(calls) == 1  # inside the back-off
    now[0] = 700.0
    assert data.closes("bitcoin") is None and len(calls) == 2
    # Another audit downloading the series: this one gets nothing at once.
    busy = MarketData(fetch, clock=lambda: now[0])
    busy._locks["sp500"].acquire()
    assert busy.closes("sp500") is None and len(calls) == 2
    busy._locks["sp500"].release()


def test_warm_downloads_every_series_in_the_background() -> None:
    asked: list[str] = []
    data = MarketData(lambda s: asked.append(s) or "DATE,V\n2024-01-02,10\n2024-01-03,11\n")
    data.warm().join(timeout=5)
    assert sorted(asked) == sorted(asset.series for asset in market_lib.ASSETS)


def test_download_is_blocked_by_the_test_guard() -> None:
    with pytest.raises(RuntimeError):
        market_lib._download("SP500")
