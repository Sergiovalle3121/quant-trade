"""Public daily closes of a few widely traded markets, read from FRED.

A report on a strategy that trades the S&P 500, the Nasdaq 100 or bitcoin
can say what simply holding that market did over the same days. The closes
come from the St. Louis Fed's public FRED service at run time, are kept in
memory for a few hours and are never written to the repository or bundled
with the package. No key, no paid source.

The audit itself stays pure: ``engine.run_audit`` takes a ``market``
callable and calls it only when the file names one of these markets. The
web service passes :meth:`MarketData.closes` when public data is on; the
tests pass a stub, and ``tests/conftest.py`` blocks :func:`_download`.
"""

from __future__ import annotations

import io
import math
import re
import threading
import time
import urllib.request
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import pandas as pd

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_PAGE = "https://fred.stlouisfed.org/series/{series}"
#: Seconds a whole FRED read may take before it is given up.
TIMEOUT = 5.0
#: Largest reply read (the longest series is about 0.3 MB).
MAX_BYTES = 4_000_000
#: Seconds before a series that failed is asked for again.
RETRY_AFTER = 600.0
#: How long a downloaded series is reused before it is read again.
MAX_AGE = 6 * 3600.0
#: Share of the trades one market must carry to stand for the file.
DOMINANT = 2 / 3


@dataclass(frozen=True)
class Asset:
    key: str
    label: str
    series: str
    #: Symbol names that stand for this market once cleaned (upper case,
    #: letters and digits only, a broker suffix such as ``.cash`` dropped).
    pattern: re.Pattern[str]

    @property
    def source_url(self) -> str:
        return FRED_PAGE.format(series=self.series)


#: A futures contract month: a month code and year (``NQZ4``) or ``MMYY`` (``NQ 12-24``).
_FUTURES = r"([FGHJKMNQUVXZ]\d{1,2}|\d{4})?"
ASSETS: tuple[Asset, ...] = (
    Asset(
        "sp500",
        "S&P 500",
        "SP500",
        re.compile(rf"^(US500|USA500|SPX500|SPX|SP500|SPXUSD|US500USD|M?ES{_FUTURES})$"),
    ),
    Asset(
        "nasdaq100",
        "Nasdaq 100",
        "NASDAQ100",
        re.compile(rf"^(US100|USTEC|USTECH|NAS100|NASDAQ100|NASUSD|NDX|NDX100|M?NQ{_FUTURES})$"),
    ),
    Asset(
        "bitcoin",
        "Bitcoin (Coinbase)",
        "CBBTCUSD",
        re.compile(r"^(BTCUSD|BTCUSDT|BTCUSDC|XBTUSD|BTCPERP|BTCUSDTPERP|BTC)$"),
    ),
)
BY_KEY = {asset.key: asset for asset in ASSETS}

#: Broker suffixes after a dot or underscore (``US100.cash``, ``BTCUSD_i``).
_SUFFIX = re.compile(r"[._].*$")


def _clean(name: str) -> str:
    return "".join(ch for ch in _SUFFIX.sub("", name.strip().upper()) if ch.isalnum())


def asset_of(name: str) -> Asset | None:
    """The market a symbol name stands for, or None."""
    cleaned = _clean(name)
    if not cleaned:
        return None
    # A trailing "M", "+" or "PRO" account-type mark (``US100m``).
    for candidate in (cleaned, re.sub(r"(M|PRO|MICRO)$", "", cleaned)):
        for asset in ASSETS:
            if asset.pattern.match(candidate):
                return asset
    return None


def dominant_asset(symbols: Sequence[str] | None, metadata_symbol: str = "") -> Asset | None:
    """The one market that carries at least two thirds of the trades, else None.

    Without trade symbols, the report's own symbol (a tester report names
    one) decides."""
    names = [name for name in (symbols or []) if name]
    if not names:
        return asset_of(metadata_symbol) if metadata_symbol else None
    counts: dict[str, int] = {}
    for name in names:
        asset = asset_of(name)
        if asset is not None:
            counts[asset.key] = counts.get(asset.key, 0) + 1
    if not counts:
        return None
    key = max(sorted(counts), key=lambda k: counts[k])
    return BY_KEY[key] if counts[key] >= DOMINANT * len(names) else None


def parse_fred_csv(text: str) -> pd.Series:
    """FRED's two-column CSV as a float series indexed by day; blanks dropped."""
    frame = pd.read_csv(io.StringIO(text))
    if frame.shape[1] < 2:
        raise ValueError("not a FRED series")
    stamps = pd.to_datetime(frame.iloc[:, 0], errors="coerce")
    values = pd.to_numeric(frame.iloc[:, 1], errors="coerce")
    series = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(stamps))
    series = series[series.index.notna() & series.notna() & (series > 0)]
    return series.sort_index()


def _download(series: str) -> str:
    """One FRED series as text, within ``TIMEOUT`` seconds in all (a server that
    trickles bytes is cut off too) and at most ``MAX_BYTES``."""
    url = FRED_CSV.format(series=series)
    deadline = time.monotonic() + TIMEOUT
    chunks: list[bytes] = []
    size = 0
    # Python's default User-Agent: FRED stalls some custom ones until the timeout.
    with urllib.request.urlopen(url, timeout=TIMEOUT) as response:  # noqa: S310 (fixed https host)
        if getattr(response, "status", 200) != 200:
            raise OSError(f"FRED answered {response.status}")
        while chunk := response.read(64 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise OSError("FRED reply too large")
            if time.monotonic() > deadline:
                raise TimeoutError("FRED too slow")
    return b"".join(chunks).decode("utf-8", "replace")


class MarketData:
    """Daily closes by asset key, downloaded on first use and kept in memory.

    Built so the public data can never hold a report back: each read has a
    total deadline; while one audit downloads a series, others get what is
    cached (or nothing) at once instead of waiting; after a failure the series
    is not asked for again for ``retry_after`` seconds; and :meth:`warm`
    downloads every series in the background when the service starts."""

    def __init__(
        self,
        download: Callable[[str], str] | None = None,
        *,
        max_age: float = MAX_AGE,
        retry_after: float = RETRY_AFTER,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._download = download
        self._max_age = max_age
        self._retry_after = retry_after
        self._clock = clock
        self._cache: dict[str, tuple[float, pd.Series]] = {}
        self._failed: dict[str, float] = {}
        self._locks = {asset.key: threading.Lock() for asset in ASSETS}

    def closes(self, key: str) -> pd.Series | None:
        """The asset's closes, or None when they cannot be read now."""
        asset = BY_KEY.get(key)
        if asset is None:
            return None
        cached = self._cache.get(key)
        now = self._clock()
        if cached is not None and now - cached[0] < self._max_age:
            return cached[1]
        stale = cached[1] if cached is not None else None
        if now - self._failed.get(key, -math.inf) < self._retry_after:
            return stale
        lock = self._locks[key]
        if not lock.acquire(blocking=False):
            return stale  # another audit is downloading it: never wait
        try:
            fetch = self._download or _download
            series = parse_fred_csv(fetch(asset.series))
            if len(series) < 2:
                raise ValueError("FRED series has no closes")
        except Exception:  # noqa: BLE001 (no network, slow, bad reply: keep what we had)
            self._failed[key] = self._clock()
            return stale
        finally:
            lock.release()
        self._failed.pop(key, None)
        self._cache[key] = (self._clock(), series)
        return series

    def warm(self) -> threading.Thread:
        """Download every series in a background thread (at service start)."""

        def run() -> None:
            for asset in ASSETS:
                self.closes(asset.key)

        thread = threading.Thread(target=run, name="market-data-warm", daemon=True)
        thread.start()
        return thread


__all__ = [
    "ASSETS",
    "Asset",
    "MarketData",
    "asset_of",
    "dominant_asset",
    "parse_fred_csv",
]
