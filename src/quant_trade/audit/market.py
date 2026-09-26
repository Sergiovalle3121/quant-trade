"""Public series the report reads at run time: rates, prices and the VIX.

Only sources whose terms allow reuse in a paid report with attribution are
read. US federal series (Treasury bills, consumer prices, the Federal
Reserve's exchange rates), the ECB's €STR, the Bank of England's SONIA and
Cboe's VIX come from the St. Louis Fed's FRED. Consumer prices outside the US
and the cash rates FRED only carried as OECD copies come from each original
publisher (Eurostat, the UK's ONS, the Bank of Canada, the Banco Central do
Brasil, Mexico's INEGI, Japan's Statistics Bureau through e-Stat, the BIS and
the ECB); they are read the same way and kept the same way.

The S&P 500, the Nasdaq 100 and bitcoin (``ASSETS``) are still recognised
from a file's symbols, but their closes are never read: FRED's copies need
the written permission of S&P Dow Jones Indices, Nasdaq and Coinbase for any
reproduction, and no public source allows reuse in a paid report. The report
says so in one NOT_MEASURED line. Everything read is kept in memory for a few
hours and never written to the repository or bundled with the package. No
key, no paid source.

The audit itself stays pure: ``engine.run_audit`` takes a ``market``
callable and calls it only when the file names one of these markets. The
web service passes :meth:`MarketData.closes` when public data is on; the
tests pass a stub, and ``tests/conftest.py`` blocks :func:`_download`.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
import threading
import time
import urllib.request
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
FRED_PAGE = "https://fred.stlouisfed.org/series/{series}"
#: The User-Agent sent to the providers other than FRED.
PROVIDER_AGENT = "Rigor-audit/1.0 (public statistics reader)"
#: Where each non-FRED provider serves a series (all public, no key) and the
#: page a reader can check it on.
PROVIDER_URLS: dict[str, tuple[str, str]] = {
    "eurostat": (
        "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_minr"
        "?geo={series}&coicop18=TOTAL&unit=I25&format=JSON",
        "https://ec.europa.eu/eurostat/databrowser/view/prc_hicp_minr/default/table",
    ),
    "ons": (
        "https://www.ons.gov.uk/generator?format=csv"
        "&uri=/economy/inflationandpriceindices/timeseries/{series}/mm23",
        "https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/{series}/mm23",
    ),
    "boc": (
        "https://www.bankofcanada.ca/valet/observations/{series}/csv",
        "https://www.bankofcanada.ca/rates/price-indexes/cpi/",
    ),
    "bcb": (
        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series}/dados?formato=json",
        "https://dadosabertos.bcb.gov.br/dataset/{series}-indice-nacional-de-precos-ao-"
        "consumidor-amplo-ipca",
    ),
    # INEGI's open-data zip of the INPC (base second half of July 2018); the
    # series name only labels it.
    "inegi": (
        "https://www.inegi.org.mx/contenidos/programas/inpc/2018a/datosabiertos/"
        "conjunto_de_datos_inpc_indicador_mensual_csv.zip",
        "https://www.inegi.org.mx/programas/inpc/2018a/",
    ),
    # e-Stat's long-term CPI file of Japan (1970 on, base 2025), by its file id.
    "estat": (
        "https://www.e-stat.go.jp/stat-search/file-download?statInfId={series}&fileKind=1",
        "https://www.e-stat.go.jp/stat-search/files?tstat=000001243876",
    ),
    # Brazil's Selic, accumulated in the month and annualised on 252 business
    # days (SGS 4189, ODbL).
    "bcb_rate": (
        "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{series}/dados?formato=json",
        "https://dadosabertos.bcb.gov.br/dataset/{series}-taxa-de-juros---selic-acumulada-no-"
        "mes-anualizada-base-252",
    ),
    # Canada's overnight repo rate average (CORRA), daily.
    "boc_rate": (
        "https://www.bankofcanada.ca/valet/observations/{series}/csv",
        "https://www.bankofcanada.ca/rates/interest-rates/corra/",
    ),
    # Central bank policy rates compiled by the BIS, monthly, end of period, by
    # the two-letter area code; unrestricted use with the BIS cited.
    "bis": (
        "https://stats.bis.org/api/v1/data/WS_CBPOL/M.{series}?format=csv&detail=dataonly",
        "https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.{series}",
    ),
    # An ECB series of its financial markets dataset (FM), by its key.
    "ecb": (
        "https://data-api.ecb.europa.eu/service/data/FM/{series}?format=csvdata&detail=dataonly",
        "https://data.ecb.europa.eu/data/datasets/FM/FM.{series}",
    ),
}
#: The providers that publish a rate in percent a year (zero and below kept).
RATE_PROVIDERS = frozenset({"bcb_rate", "boc_rate", "bis", "ecb"})
#: Who each source credits, as the report's link text names it.
PUBLISHERS: dict[str, str] = {
    "fred": "FRED",
    "eurostat": "Eurostat",
    "ons": "ONS",
    "boc": "Bank of Canada",
    "bcb": "Banco Central do Brasil",
    "inegi": "INEGI",
    "estat": "e-Stat",
    "bcb_rate": "Banco Central do Brasil",
    "boc_rate": "Bank of Canada",
    "bis": "BIS",
    "ecb": "ECB",
}
#: How each provider's bytes become text: INEGI sends a zip, carried byte for
#: byte as Latin-1 text and opened by :func:`parse_provider`; e-Stat's CSV is
#: Shift_JIS whatever its header says. The rest are UTF-8.
PROVIDER_ENCODING: dict[str, str] = {"inegi": "latin-1", "estat": "cp932"}
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
    #: Where the series is read: ``fred`` or a key of ``PROVIDER_URLS``.
    provider: str = "fred"
    #: For a monthly price index, the largest ratio between two consecutive
    #: values; a larger jump is a broken reply (Brazil's worst month, March
    #: 1990, was about x1.8).
    max_step: float | None = None
    #: False when no public source of the series allows reuse in a paid
    #: report: the market is recognised but its closes are never read.
    licensed: bool = True

    @property
    def source_url(self) -> str:
        if self.provider in PROVIDER_URLS:
            return PROVIDER_URLS[self.provider][1].format(series=self.series)
        return FRED_PAGE.format(series=self.series)

    @property
    def publisher(self) -> str:
        """The source the report credits by name."""
        return PUBLISHERS.get(self.provider, "FRED")


#: A futures contract month: a month code and year (``NQZ4``) or ``MMYY`` (``NQ 12-24``).
_FUTURES = r"([FGHJKMNQUVXZ]\d{1,2}|\d{4})?"
#: The markets a file's symbols are matched to. None has a public source whose
#: licence allows reuse in a paid report (FRED's ``SP500``, ``NASDAQ100`` and
#: ``CBBTCUSD`` need the written permission of S&P Dow Jones Indices, Nasdaq and
#: Coinbase), so none is ever read; the series ids only name what is missing.
ASSETS: tuple[Asset, ...] = (
    Asset(
        "sp500",
        "S&P 500",
        "SP500",
        re.compile(rf"^(US500|USA500|SPX500|SPX|SP500|SPXUSD|US500USD|M?ES{_FUTURES})$"),
        licensed=False,
    ),
    Asset(
        "nasdaq100",
        "Nasdaq 100",
        "NASDAQ100",
        re.compile(rf"^(US100|USTEC|USTECH|NAS100|NASDAQ100|NASUSD|NDX|NDX100|M?NQ{_FUTURES})$"),
        licensed=False,
    ),
    Asset(
        "bitcoin",
        "Bitcoin",
        "CBBTCUSD",
        re.compile(r"^(BTCUSD|BTCUSDT|BTCUSDC|XBTUSD|BTCPERP|BTCUSDTPERP|BTC)$"),
        licensed=False,
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
#: The largest ratio between two consecutive months of a price index.
MAX_PRICE_STEP = 3.0
#: US consumer prices (all items, not seasonally adjusted, 1982-84 = 100), monthly;
#: BLS recommends the unadjusted index for deflating between arbitrary dates.
CPI = Asset(
    "cpi",
    "US consumer prices",
    "CPIAUCNS",
    re.compile(r"(?!)"),
    ceiling=10_000.0,
    floor=1.0,
    max_step=MAX_PRICE_STEP,
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
#: Highest and lowest rate a local cash series may hold (Brazil's Selic reached
#: 85 % a year in April 1995; the Swiss policy rate went to -0.75 % in 2015).
MAX_LOCAL_RATE = 200.0
MIN_LOCAL_RATE = -5.0
#: What cash earned in each currency of ``FX``, in percent a year, from its
#: originator: the euro's €STR (ECB) and sterling's SONIA (Bank of England),
#: both through FRED; Canada's CORRA (Bank of Canada) and Brazil's monthly
#: Selic (Banco Central do Brasil); and, for the peso, the yen and the franc,
#: the central bank's policy rate as the BIS compiles it (an official rate,
#: not a market one; Japan has no value from May 2013 to August 2016, when the
#: Bank of Japan set no policy rate).
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
        provider=provider,
    )
    for code, series, provider in (
        ("MXN", "MX", "bis"),
        ("BRL", "4189", "bcb_rate"),
        ("EUR", "ECBESTRVOLWGTTRMDMNRT", "fred"),
        ("GBP", "IUDSOIA", "fred"),
        ("JPY", "JP", "bis"),
        ("CAD", "AVG.INTWO", "boc_rate"),
        ("CHF", "CH", "bis"),
    )
)
#: The ECB's deposit facility rate (daily, from 1999), for the years before
#: €STR starts in October 2019. It is a policy rate, not €STR: overnight market
#: rates sat above it, by about a point before 2008 and by less after, and €STR
#: has run about 10 bp below it.
EUR_CASH_HISTORY = Asset(
    "cash_eur_history",
    "EUR",
    "D.U2.EUR.4F.KR.DFR.LEV",
    re.compile(r"(?!)"),
    rate=True,
    ceiling=MAX_LOCAL_RATE,
    floor=MIN_LOCAL_RATE,
    negative=True,
    provider="ecb",
)
#: Consumer prices in the currencies of ``FX`` whose official index is current
#: and may be reused in a paid service with attribution (all items, monthly, not
#: seasonally adjusted): the euro area's and Switzerland's harmonised indexes
#: (Eurostat; the euro area's through FRED), the UK's CPI (ONS, Open Government
#: Licence), Canada's CPI (Statistics Canada, through the Bank of Canada) and
#: Brazil's IPCA (IBGE, through the Banco Central do Brasil, monthly changes
#: chained into an index), Mexico's INPC (INEGI's open data) and Japan's CPI
#: (Statistics Bureau, e-Stat's long-term file).
MAX_PRICE_INDEX = 10_000_000.0
LOCAL_CPI: tuple[Asset, ...] = tuple(
    Asset(
        f"cpi_{code.lower()}",
        code,
        series,
        re.compile(r"(?!)"),
        ceiling=MAX_PRICE_INDEX,
        floor=1.0,
        provider=provider,
        max_step=MAX_PRICE_STEP,
    )
    for code, series, provider in (
        ("EUR", "CP0000EZ19M086NEST", "fred"),
        ("GBP", "d7bt", "ons"),
        ("CAD", "V41690973", "boc"),
        ("CHF", "CH", "eurostat"),
        ("BRL", "433", "bcb"),
        ("MXN", "INPC", "inegi"),
        ("JPY", "000040482943", "estat"),
    )
)
#: Every series the service keeps in memory (never an unlicensed market).
SERIES: dict[str, Asset] = {
    **{asset.key: asset for asset in ASSETS if asset.licensed},
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


#: Brazil's monthly changes are chained from the Real plan on, after the
#: hyperinflation years; a month outside these bounds (in percent) is broken.
BCB_START = "1995-01-01"
MAX_MONTHLY_CHANGE = 50.0


def _monthly(stamps: pd.Series, values: pd.Series) -> pd.Series:
    series = pd.Series(
        pd.to_numeric(values, errors="coerce").to_numpy(dtype=float),
        index=pd.DatetimeIndex(pd.to_datetime(stamps, errors="coerce")),
    )
    series = series[series.index.notna() & np.isfinite(series)]
    return series[~series.index.duplicated(keep="last")].sort_index()


def parse_provider(text: str, provider: str) -> pd.Series:
    """A monthly price index from one provider's reply, indexed by each month's
    first day; blanks and values that are not above zero dropped."""
    if provider == "eurostat":
        data = json.loads(text)
        times = data["dimension"]["time"]["category"]["index"]
        by_position = {int(position): value for position, value in data["value"].items()}
        stamps = pd.Series(sorted(times, key=times.get))
        values = pd.Series([by_position.get(int(times[t])) for t in stamps], dtype=float)
        series = _monthly(stamps + "-01", values)
    elif provider == "ons":
        rows = re.findall(r'^"(\d{4}) ([A-Z]{3})","([^"]*)"\s*$', text, flags=re.M)
        stamps = pd.Series([f"01 {month} {year}" for year, month, _ in rows])
        series = _monthly(
            pd.Series(pd.to_datetime(stamps, format="%d %b %Y", errors="coerce")),
            pd.Series([value for *_, value in rows]),
        )
    elif provider == "boc":
        body = text.split('"OBSERVATIONS"', 1)[1]
        frame = pd.read_csv(io.StringIO(body.strip()), dtype=str)
        series = _monthly(frame.iloc[:, 0], frame.iloc[:, 1])
    elif provider == "bcb":
        frame = pd.DataFrame(json.loads(text))
        stamps = pd.to_datetime(frame["data"], format="%d/%m/%Y", errors="coerce")
        values = pd.to_numeric(frame["valor"], errors="coerce")
        kept = (stamps >= pd.Timestamp(BCB_START)).to_numpy()
        changes = pd.Series(
            values.to_numpy(dtype=float)[kept], index=pd.DatetimeIndex(stamps[kept])
        ).sort_index()
        # A chain is only as good as its links: a missing, repeated or unreadable
        # month would leave its inflation out of every later level.
        months = changes.index.to_period("M")
        expected = pd.period_range(months.min(), months.max(), freq="M") if len(months) else []
        if (
            bool(stamps.isna().any())
            or not bool(np.isfinite(changes.to_numpy()).all())
            or len(months) != len(expected)
            or not bool((months == expected).all())
        ):
            raise ValueError("IPCA months are not consecutive")
        if bool((changes.abs() > MAX_MONTHLY_CHANGE).any()):
            raise ValueError("monthly change out of range")
        series = 100.0 * (1.0 + changes / 100.0).cumprod()
    elif provider == "inegi":
        frame = pd.read_csv(io.StringIO(_inegi_table(text)), dtype=str)
        headline = frame["CONCEPTO"].str.endswith(INEGI_HEADLINE, na=False)
        if not bool(headline.any()):
            raise ValueError("no INPC rows")
        rows = frame[headline]
        if bool(rows["FECHA"].duplicated().any()):
            raise ValueError("an INPC month appears twice")
        series = _monthly(rows["FECHA"], rows["VALOR"])
    elif provider == "estat":
        lines = text.splitlines()
        codes = next((line for line in lines if line.startswith(ESTAT_CODE_ROW)), None)
        if codes is None:
            raise ValueError("no item codes")
        column = next(csv.reader([codes])).index(ESTAT_ALL_ITEMS)
        stamps, values = [], []
        for row in csv.reader(line for line in lines if re.match(r"^\d{6},", line)):
            stamps.append(pd.to_datetime(row[0], format="%Y%m", errors="coerce"))
            values.append(row[column] if column < len(row) else None)
        if len(set(stamps)) != len(stamps):
            raise ValueError("a CPI month appears twice")
        series = _monthly(pd.Series(stamps), pd.Series(values))
    else:
        raise ValueError(f"unknown provider {provider}")
    return series[series > 0]


def parse_rates(text: str, provider: str, series: str) -> pd.Series:
    """A rate in percent a year from one of ``RATE_PROVIDERS``, indexed by day;
    zero and negative values kept. A date that appears twice, a reply for
    another series, or an unreadable date or value refuses the reply.

    The BIS publishes a month's value as of its last day, so it is placed on
    that day (never at the start of the month it closed); Brazil's monthly
    Selic is the month's own average and stays on its first day."""
    if provider == "bcb_rate":
        rows = json.loads(text)
        if not isinstance(rows, list) or not rows:
            raise ValueError("no rates")
        frame = pd.DataFrame(rows)
        stamps = pd.Series(pd.to_datetime(frame["data"], format="%d/%m/%Y", errors="coerce"))
        values = frame["valor"]
        # Before the Real plan the monthly Selic ran in the thousands a year.
        kept = (stamps >= pd.Timestamp(BCB_START)) | stamps.isna()
        stamps, values = stamps[kept], values[kept]
    elif provider == "boc_rate":
        body = text.split('"OBSERVATIONS"', 1)[1]
        frame = pd.read_csv(io.StringIO(body.strip()), dtype=str)
        if frame.columns[1] != series:
            raise ValueError("a reply for another series")
        stamps = pd.Series(pd.to_datetime(frame.iloc[:, 0], format="%Y-%m-%d", errors="coerce"))
        values = frame.iloc[:, 1]
    elif provider == "bis":
        frame = pd.read_csv(io.StringIO(text), dtype=str)
        if not bool((frame["REF_AREA"] == series).all()) or not bool((frame["FREQ"] == "M").all()):
            raise ValueError("a reply for another series")
        months = pd.to_datetime(frame["TIME_PERIOD"], format="%Y-%m", errors="coerce")
        stamps = pd.Series(months + pd.offsets.MonthEnd(0))
        values = frame["OBS_VALUE"]
    elif provider == "ecb":
        frame = pd.read_csv(io.StringIO(text), dtype=str)
        if not bool((frame["KEY"] == f"FM.{series}").all()):
            raise ValueError("a reply for another series")
        stamps = pd.Series(pd.to_datetime(frame["TIME_PERIOD"], format="%Y-%m-%d", errors="coerce"))
        values = frame["OBS_VALUE"]
    else:
        raise ValueError(f"unknown rate provider {provider}")
    numbers = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    if len(numbers) == 0:
        raise ValueError("no rates")
    if bool(stamps.isna().any()) or not bool(np.isfinite(numbers).all()):
        raise ValueError("an unreadable date or rate")
    if bool(stamps.duplicated().any()):
        raise ValueError("a date appears twice")
    return pd.Series(numbers, index=pd.DatetimeIndex(stamps.to_numpy())).sort_index()


#: The INPC rows among the other indexes of INEGI's file, and the name of the
#: monthly table inside the zip.
INEGI_HEADLINE = "Precios al Consumidor (INPC)"
INEGI_TABLE = "conjunto_de_datos_inpc_mensual.csv"
#: The row of e-Stat's file that gives each column's item code, and the code of
#: all items.
ESTAT_CODE_ROW = "類・品目符号"
ESTAT_ALL_ITEMS = "0001"


def _inegi_table(text: str) -> str:
    """The monthly table inside INEGI's zip, refused when the zip is broken
    or the table would open larger than ``MAX_BYTES``."""
    with zipfile.ZipFile(io.BytesIO(text.encode("latin-1"))) as archive:
        name = next((n for n in archive.namelist() if n.endswith(INEGI_TABLE)), None)
        if name is None:
            raise ValueError("no INPC table in the zip")
        with archive.open(name) as table:
            body = table.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise ValueError("INPC table too large")
    return body.decode("utf-8-sig")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse redirects, so a read never leaves its fixed https address."""

    def redirect_request(self, *args: object, **kwargs: object) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _download(series: str, provider: str = "fred") -> str:
    """One FRED (or other provider's) series as text, within about ``TIMEOUT`` seconds in all
    and at most ``MAX_BYTES``. ``read1`` returns whatever one receive brings, so
    the deadline is checked after every receive and a server that trickles
    bytes is cut off (each receive is itself bounded by the socket timeout)."""
    if provider in PROVIDER_URLS:
        url = PROVIDER_URLS[provider][0].format(series=series)
    else:
        url = FRED_CSV.format(series=series)
    # FRED gets Python's default User-Agent (it stalls some custom ones); the ONS
    # refuses that one, so the other providers get a plain name.
    headers = {"User-Agent": PROVIDER_AGENT} if provider in PROVIDER_URLS else {}
    request = urllib.request.Request(url, headers=headers)
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
    return b"".join(chunks).decode(PROVIDER_ENCODING.get(provider, "utf-8"), "replace")


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
            # An injected reader takes the series id alone; the real one also its provider.
            text = (
                self._download(asset.series)
                if self._download is not None
                else _download(asset.series, asset.provider)
            )
            if asset.provider in RATE_PROVIDERS:
                series = parse_rates(text, asset.provider, asset.series)
            elif asset.provider in PROVIDER_URLS:
                series = parse_provider(text, asset.provider)
            else:
                series = parse_fred_csv(text, rate=asset.rate, negative=asset.negative)
            if len(series) < 2:
                raise ValueError("FRED series has no closes")
            if asset.ceiling is not None and bool((series > asset.ceiling).any()):
                raise ValueError("FRED value out of range")
            if asset.floor is not None and bool((series < asset.floor).any()):
                raise ValueError("FRED value out of range")
            if asset.max_step is not None and len(series) > 1:
                steps = series.to_numpy(dtype=float)[1:] / series.to_numpy(dtype=float)[:-1]
                if bool((steps > asset.max_step).any() or (steps < 1 / asset.max_step).any()):
                    raise ValueError("price index jumps")
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
    "PROVIDER_ENCODING",
    "PUBLISHERS",
    "RATE_PROVIDERS",
    "SERIES",
    "VIX",
    "Asset",
    "MarketData",
    "asset_of",
    "dominant_asset",
    "parse_fred_csv",
    "parse_provider",
    "parse_rates",
]
