"""Public daily closes of a few widely traded markets, read from FRED.

Consumer prices outside the US come from the IMF's public CPI dataset (the
national index each statistics office publishes, compiled by the IMF), where
FRED's copies stopped updating; they are read the same way and kept the same
way.

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

import numpy as np
import pandas as pd

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_PAGE = "https://fred.stlouisfed.org/series/{series}"
#: The IMF's public CPI dataset (SDMX), monthly, as CSV; no key.
IMF_CSV = (
    "https://api.imf.org/external/sdmx/2.1/data/IMF.STA,CPI/{series}"
    "?startPeriod=1990-01&detail=dataonly"
)
IMF_ACCEPT = "application/vnd.sdmx.data+csv;version=1.0.0"
IMF_PAGE = "https://data.imf.org/en/datasets/IMF.STA:CPI"
#: Seconds a whole FRED read may take before it is given up.
TIMEOUT = 5.0
#: Largest reply read (the longest series is about 0.3 MB).
MAX_BYTES = 4_000_000
#: Seconds before a series that failed is asked for again.
RETRY_AFTER = 600.0
#: How long a downloaded series is reused before it is read again.
MAX_AGE = 6 * 3600.0
#: Highest rate in percent a year a rate series may hold; above it the reply is
#: taken as broken (US bills peaked near 16 % in 1981).
MAX_RATE = 25.0
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
    #: A rate in percent, where zero is a real value (not a missing close).
    rate: bool = False
    #: A value above this means the download is broken, not the market.
    ceiling: float | None = None
    #: A value below this means the download is broken, not the market.
    floor: float | None = None
    #: A rate that can go below zero (some central banks' rates did).
    negative: bool = False
    #: Where the series is read: ``fred`` or ``imf``.
    provider: str = "fred"

    @property
    def source_url(self) -> str:
        return IMF_PAGE if self.provider == "imf" else FRED_PAGE.format(series=self.series)


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
#: What a US dollar in cash earned: the 3-month Treasury bill's secondary market
#: rate, in percent a year (discount basis), as FRED publishes it.
CASH = Asset(
    "tbill3m",
    "US 3-month Treasury bill",
    "DTB3",
    re.compile(r"(?!)"),
    rate=True,
    ceiling=MAX_RATE,
)
#: How much movement the options market expects from the S&P 500 over the next
#: month (CBOE's VIX), in percent a year, as FRED publishes it. Its record close
#: is 82.69 (March 2020), so a value above ``MAX_VIX`` is a broken download.
MAX_VIX = 200.0
VIX = Asset("vix", "VIX", "VIXCLS", re.compile(r"(?!)"), ceiling=MAX_VIX)
#: US consumer prices (all items, not seasonally adjusted, 1982-84 = 100), monthly;
#: BLS recommends the unadjusted index for deflating between arbitrary dates.
CPI = Asset(
    "cpi", "US consumer prices", "CPIAUCNS", re.compile(r"(?!)"), ceiling=10_000.0, floor=1.0
)
#: Noon buying rates in New York (Federal Reserve H.10), daily: units of the
#: currency per US dollar, or US dollars per unit for the euro and the pound.
FX: tuple[Asset, ...] = tuple(
    Asset(f"fx_{code.lower()}", code, series, re.compile(r"(?!)"), ceiling=10_000.0, floor=0.01)
    for code, series in (
        ("MXN", "DEXMXUS"),
        ("BRL", "DEXBZUS"),
        ("EUR", "DEXUSEU"),
        ("GBP", "DEXUSUK"),
        ("JPY", "DEXJPUS"),
        ("CAD", "DEXCAUS"),
        ("CHF", "DEXSZUS"),
    )
)
#: Highest and lowest rate a local cash series may hold (Mexico's call rate
#: reached 136 % in 1988; the Swiss 3-month rate went to -0.93 % in 2015).
MAX_LOCAL_RATE = 200.0
MIN_LOCAL_RATE = -5.0
#: What cash earned in each currency of ``FX``, in percent a year, as FRED
#: publishes it: the overnight or immediate rate where one is current, else
#: the 3-month interbank rate.
LOCAL_CASH: tuple[Asset, ...] = tuple(
    Asset(
        f"cash_{code.lower()}",
        code,
        series,
        re.compile(r"(?!)"),
        rate=True,
        ceiling=MAX_LOCAL_RATE,
        floor=MIN_LOCAL_RATE,
        negative=True,
    )
    for code, series in (
        ("MXN", "IRSTCI01MXM156N"),
        ("BRL", "IRSTCI01BRM156N"),
        ("EUR", "ECBESTRVOLWGTTRMDMNRT"),
        ("GBP", "IUDSOIA"),
        ("JPY", "IRSTCI01JPM156N"),
        ("CAD", "IRSTCI01CAM156N"),
        ("CHF", "IR3TIB01CHM156N"),
    )
)
#: The euro area's immediate rate (OECD, monthly), for the years before €STR
#: starts in October 2019; FRED's copy stops updating in 2026.
EUR_CASH_HISTORY = Asset(
    "cash_eur_history",
    "EUR",
    "IRSTCI01EZM156N",
    re.compile(r"(?!)"),
    rate=True,
    ceiling=MAX_LOCAL_RATE,
    floor=MIN_LOCAL_RATE,
    negative=True,
)
#: Consumer prices in each currency of ``FX`` (all items, monthly, not seasonally
#: adjusted): each country's national index from the IMF's CPI dataset, and the
#: euro area's harmonised index (Eurostat's HICP) from FRED. Brazil's index runs
#: from tiny values in 1990 (hyperinflation), so only a ceiling applies.
MAX_PRICE_INDEX = 10_000_000.0
LOCAL_CPI: tuple[Asset, ...] = (
    *(
        Asset(
            f"cpi_{code.lower()}",
            code,
            f"{country}.CPI._T.IX.M",
            re.compile(r"(?!)"),
            ceiling=MAX_PRICE_INDEX,
            provider="imf",
        )
        for code, country in (
            ("MXN", "MEX"),
            ("BRL", "BRA"),
            ("GBP", "GBR"),
            ("JPY", "JPN"),
            ("CAD", "CAN"),
            ("CHF", "CHE"),
        )
    ),
    Asset("cpi_eur", "EUR", "CP0000EZ19M086NEST", re.compile(r"(?!)"), ceiling=10_000.0, floor=1.0),
)
#: Every series the service keeps in memory.
SERIES: dict[str, Asset] = {
    **BY_KEY,
    CASH.key: CASH,
    VIX.key: VIX,
    CPI.key: CPI,
    **{asset.key: asset for asset in FX},
    **{asset.key: asset for asset in LOCAL_CASH},
    EUR_CASH_HISTORY.key: EUR_CASH_HISTORY,
    **{asset.key: asset for asset in LOCAL_CPI},
}

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


def parse_fred_csv(text: str, *, rate: bool = False, negative: bool = False) -> pd.Series:
    """FRED's two-column CSV as a float series indexed by day; blanks dropped
    (and zeros too, unless the series is a rate; values below zero too, unless
    the rate can be negative)."""
    frame = pd.read_csv(io.StringIO(text))
    if frame.shape[1] < 2:
        raise ValueError("not a FRED series")
    stamps = pd.to_datetime(frame.iloc[:, 0], errors="coerce")
    values = pd.to_numeric(frame.iloc[:, 1], errors="coerce")
    series = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(stamps))
    usable = series.notna() if negative else (series >= 0) if rate else (series > 0)
    series = series[series.index.notna() & np.isfinite(series) & usable]
    return series.sort_index()


def parse_imf_csv(text: str) -> pd.Series:
    """The IMF's SDMX CSV (``TIME_PERIOD`` as ``2024-M01``, ``OBS_VALUE``) as a
    float series indexed by each month's first day; blanks and values that are
    not above zero dropped."""
    frame = pd.read_csv(io.StringIO(text), usecols=["TIME_PERIOD", "OBS_VALUE"], dtype=str)
    months = frame["TIME_PERIOD"].str.strip().str.replace("-M", "-", regex=False)
    stamps = pd.to_datetime(months, format="%Y-%m", errors="coerce")
    values = pd.to_numeric(frame["OBS_VALUE"], errors="coerce")
    series = pd.Series(values.to_numpy(dtype=float), index=pd.DatetimeIndex(stamps))
    series = series[series.index.notna() & np.isfinite(series) & (series > 0)]
    return series[~series.index.duplicated(keep="last")].sort_index()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects, so a read never leaves its fixed https address."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _download(series: str, provider: str = "fred") -> str:
    """One FRED (or IMF) series as text, within about ``TIMEOUT`` seconds in all
    and at most ``MAX_BYTES``. ``read1`` returns whatever one receive brings, so
    the deadline is checked after every receive and a server that trickles
    bytes is cut off (each receive is itself bounded by the socket timeout)."""
    if provider == "imf":
        request = urllib.request.Request(
            IMF_CSV.format(series=series), headers={"Accept": IMF_ACCEPT}
        )
    else:
        request = urllib.request.Request(FRED_CSV.format(series=series))
    deadline = time.monotonic() + TIMEOUT
    chunks: list[bytes] = []
    size = 0
    # Python's default User-Agent: FRED stalls some custom ones until the timeout.
    with _OPENER.open(request, timeout=TIMEOUT) as response:
        if getattr(response, "status", 200) != 200:
            raise OSError(f"FRED answered {response.status}")
        while chunk := response.read1(64 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_BYTES:
                raise OSError("FRED reply too large")
            if time.monotonic() > deadline:
                raise TimeoutError("FRED too slow")
    return b"".join(chunks).decode("utf-8", "replace")


class MarketData:
    """Daily closes by asset key, downloaded in the background and kept in memory.

    Built so the public data can never hold a report back: :meth:`closes`
    never downloads; it answers at once with what is in memory (or None) and,
    when that copy is missing or older than ``max_age``, starts one background
    :meth:`refresh`. A refresh has a total deadline; only one runs per series
    at a time; after a failure the series is not asked for again for
    ``retry_after`` seconds; and :meth:`warm` downloads every series when the
    service starts."""

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
        self._locks = {key: threading.Lock() for key in SERIES}

    def closes(self, key: str) -> pd.Series | None:
        """The asset's closes in memory, or None; never waits on the network."""
        if key not in SERIES:
            return None
        cached = self._cache.get(key)
        now = self._clock()
        if cached is not None and now - cached[0] < self._max_age:
            return cached[1]
        if (
            now - self._failed.get(key, -math.inf) >= self._retry_after
            and not self._locks[key].locked()
        ):
            threading.Thread(
                target=self.refresh, args=(key,), name=f"market-data-{key}", daemon=True
            ).start()
        return cached[1] if cached is not None else None

    def ready(self) -> tuple[str, ...]:
        """The series already in memory, in a fixed order; starts no download."""
        return tuple(key for key in SERIES if key in self._cache)

    def refresh(self, key: str) -> bool:
        """Download one series now (in the calling thread); False when another
        refresh of it is running or the download failed."""
        asset = SERIES.get(key)
        if asset is None:
            return False
        lock = self._locks[key]
        if not lock.acquire(blocking=False):
            return False
        try:
            # An injected reader takes the series id alone; the IMF one also its provider.
            text = (
                self._download(asset.series)
                if self._download is not None
                else _download(asset.series, asset.provider)
            )
            if asset.provider == "imf":
                series = parse_imf_csv(text)
            else:
                series = parse_fred_csv(text, rate=asset.rate, negative=asset.negative)
            if len(series) < 2:
                raise ValueError("FRED series has no closes")
            if asset.ceiling is not None and bool((series > asset.ceiling).any()):
                raise ValueError("FRED value out of range")
            if asset.floor is not None and bool((series < asset.floor).any()):
                raise ValueError("FRED value out of range")
        except Exception:  # noqa: BLE001 (no network, slow, bad reply: keep what we had)
            self._failed[key] = self._clock()
            return False
        finally:
            lock.release()
        self._failed.pop(key, None)
        self._cache[key] = (self._clock(), series)
        return True

    def warm(self) -> threading.Thread:
        """Download every series in a background thread (at service start)."""

        def run() -> None:
            for key in SERIES:
                self.refresh(key)

        thread = threading.Thread(target=run, name="market-data-warm", daemon=True)
        thread.start()
        return thread


__all__ = [
    "ASSETS",
    "CASH",
    "CPI",
    "FX",
    "LOCAL_CPI",
    "SERIES",
    "VIX",
    "Asset",
    "MarketData",
    "asset_of",
    "dominant_asset",
    "parse_fred_csv",
    "parse_imf_csv",
]
