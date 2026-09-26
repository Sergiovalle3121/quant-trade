"""Inputs, evidence tags and the result shape of a backtest audit.

The client supplies files; the audit supplies numbers. What keeps the two
apart is the evidence tag on every leaf value: ``MEASURED`` means it was
computed from the uploaded bytes, ``DECLARED`` means the client asserted it
and the audit could not check it, ``NOT_MEASURED`` means the audit could not
compute it from what was supplied and says why. A report that mixes the three
without labels is a report that can be read as more than it is.

Parsing is deliberately forgiving about column names (TradingView, MetaTrader
and hand-made exports disagree) and deliberately strict about what it
silently repairs: every repair is recorded as a warning that reaches the
report, and anything that cannot be repaired is a ``ParseError`` with a
message a non-programmer can act on.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator

from quant_trade.core.models import Trade
from quant_trade.evidence.canonical_json import sha256_of_bytes
from quant_trade.metrics.performance import periods_per_year

SCHEMA_VERSION = 2

EvidenceClass = Literal["MEASURED", "DECLARED", "NOT_MEASURED"]
MEASURED: EvidenceClass = "MEASURED"
DECLARED: EvidenceClass = "DECLARED"
NOT_MEASURED: EvidenceClass = "NOT_MEASURED"

#: Upload limits. Generous for a retail backtest, small enough that a single
#: request cannot pin the process.
MAX_UPLOAD_BYTES = 5_000_000
#: A platform report may be twice that: MetaTrader writes its HTML reports
#: in UTF-16, two bytes per character, so 5 MB held only ~6,000 trades.
MAX_REPORT_BYTES = 2 * MAX_UPLOAD_BYTES
MAX_ROWS = 200_000
MAX_TRADES = 50_000
MAX_VARIANTS = 500
#: Longest CSV line read. Pandas infers columns in time that grows with the
#: square of their count, and a 5 MB line of fields pins a worker for minutes;
#: a header of 500 variant names, or a row of 500 returns, fits in 32 KB.
MAX_CSV_LINE_BYTES = 32_768
#: Largest account value read, and largest return in one period. No account
#: holds a thousand trillion; a 1e308 balance overflowed every later sum and
#: left the report without figures to print.
MAX_ACCOUNT_VALUE = 1e15
MAX_PERIOD_RETURN = 1e6
MIN_OBSERVATIONS = 30

TIMESTAMP_ALIASES = ("timestamp", "date", "datetime", "time", "ts", "fecha", "observation_date")
EQUITY_ALIASES = ("equity", "nav", "balance", "value", "portfolio_value", "close", "capital")
RETURN_ALIASES = ("return", "returns", "ret", "pnl_pct", "daily_return", "retorno")

TRADE_ENTRY_TIME = ("entry_time", "entry_date", "open_time", "open_date", "entry", "fecha_entrada")
TRADE_EXIT_TIME = ("exit_time", "exit_date", "close_time", "close_date", "exit", "fecha_salida")
TRADE_QUANTITY = ("quantity", "qty", "size", "volume", "units", "cantidad", "lots")
TRADE_ENTRY_PRICE = ("entry_price", "open_price", "price_in", "precio_entrada")
TRADE_EXIT_PRICE = ("exit_price", "close_price", "price_out", "precio_salida")
TRADE_SIDE = ("side", "direction", "type", "lado")
TRADE_PNL = ("pnl", "profit", "net_profit", "p&l", "resultado")

LONG_SIDES = {"long", "buy", "compra", "b", "l"}
SHORT_SIDES = {"short", "sell", "venta", "s"}


#: Spanish names of the uploaded files, for ``ParseError.message_es``.
FILE_NAMES_ES = {
    "equity": "de la curva de equity",
    "benchmark": "del benchmark",
    "trades": "de operaciones",
    "variants": "de variantes",
    "report": "del informe",
    "optimization": "de optimización",
}

#: Report file extensions kept in the digest name; anything else is ``.bin``.
REPORT_EXTENSIONS = ("html", "htm", "csv", "xlsx", "xls", "txt", "tsv", "xml", "zip")


class ParseError(ValueError):
    """The upload cannot be audited as supplied; the message says why.

    ``str(error)`` is the English message; ``message_es`` is its Spanish
    twin and ``code`` a stable machine-readable reason. Callers that raise
    without a Spanish message (older code, third-party importers) fall back
    to the English text, so a page never shows an empty error.
    """

    def __init__(self, message: str, *, message_es: str | None = None, code: str = "parse") -> None:
        super().__init__(message)
        self.code = code
        self.message_es = message_es or message

    def localized(self, locale: str) -> str:
        return self.message_es if locale == "es" else str(self)


def _file_es(what: str) -> str:
    return FILE_NAMES_ES.get(what, what)


class Evidence(BaseModel):
    """One reported value and how much of it the audit actually measured."""

    model_config = ConfigDict(extra="forbid")

    value: float | int | str | bool | None = None
    evidence: EvidenceClass
    note: str = ""


def _finite(value: Any) -> float | int | str | bool | None:
    """NaN and infinities become ``None``: canonical JSON refuses them, and a
    minimum track record of +inf is better reported as "not reachable"."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, int):
        return value
    number = float(value)
    return number if math.isfinite(number) else None


def measured(value: Any, note: str = "") -> dict[str, Any]:
    return Evidence(value=_finite(value), evidence=MEASURED, note=note).model_dump()


def declared(value: Any, note: str = "") -> dict[str, Any]:
    return Evidence(value=_finite(value), evidence=DECLARED, note=note).model_dump()


def not_measured(reason: str) -> dict[str, Any]:
    return Evidence(value=None, evidence=NOT_MEASURED, note=reason).model_dump()


class DeclaredMetadata(BaseModel):
    """What the client asserts and the audit records verbatim as DECLARED."""

    model_config = ConfigDict(extra="forbid")

    trials: int = Field(1, ge=1, le=1_000_000)
    #: False when the form's trials field was left blank: 1 is then assumed,
    #: tagged NOT_MEASURED, and never held against the client.
    trials_declared: bool = True
    cost_bps_per_side: float = Field(0.0, ge=0.0, le=1000.0)
    oos_start: datetime | None = None
    description: str = Field("", max_length=2000)
    benchmark_applicable: bool = True
    locale: Literal["es", "en", "pt"] = "es"
    #: Starting balance, used only when an imported report does not state one.
    initial_balance: float | None = Field(None, gt=0.0, le=1e12)
    #: The returns are a fund's own figures after its fees (a monthly track
    #: record only; ``engine.fund_record`` decides, and anything else keeps
    #: the cost check).
    net_of_fees: bool = False
    #: Prop-firm challenge preset to simulate; ``None`` means the default preset.
    challenge: str | None = Field(None, max_length=64)

    @field_validator("challenge")
    @classmethod
    def _known_preset(cls, value: str | None) -> str | None:
        from quant_trade.audit.prop_presets import PRESETS

        if value is None or not value.strip():
            return None
        key = value.strip()
        if key not in PRESETS:
            raise ValueError(f"unknown challenge preset {key!r}")
        return key

    @field_validator("oos_start")
    @classmethod
    def _utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @field_validator("description")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


@dataclass(frozen=True)
class IngestedSeries:
    """An equity curve normalised to ``timestamp``, ``equity``, ``ret``."""

    frame: pd.DataFrame
    source: Literal["equity", "returns"]
    raw_rows: int
    duplicate_timestamps: int
    unparseable_rows: int
    non_monotonic: bool
    warnings: list[str] = field(default_factory=list)
    #: A benchmark the same file carries (``timestamp``, ``ret``): a column
    #: beside the returns, or a factsheet's benchmark rows. Read only by the
    #: fund section; it never feeds the benchmark dimension.
    benchmark: pd.DataFrame | None = None

    @property
    def observations(self) -> int:
        return int(len(self.frame))

    @property
    def returns(self) -> pd.Series:
        return self.frame["ret"].dropna()


@dataclass(frozen=True)
class ParsedTrades:
    trades: list[Trade]
    sides: list[str]
    client_pnl: list[float | None]
    invalid_rows: int
    warnings: list[str] = field(default_factory=list)
    #: Per-trade costs the platform already charged (commission, swap, fees;
    #: positive is a cost), aligned with ``trades``. ``None`` when the file
    #: does not itemise them.
    fees: list[float] | None = None

    @property
    def reports_fees(self) -> bool:
        """True when the file itemises a non-zero cost for some trade."""
        return self.fees is not None and any(fee != 0 for fee in self.fees)


def printed_step(value: float, *, max_decimals: int = 8) -> float:
    """The last printed digit of a figure, as a platform wrote it.

    TradingView prints small P&L with few digits, so a one-unit forex trade
    that made 0.00127 shows 0.001; a difference inside half that step is
    rounding, not a different contract size or a hidden cost.
    """
    if not value or not math.isfinite(value):
        return 10.0**-max_decimals
    for decimals in range(0, max_decimals + 1):
        scaled = abs(value) * 10.0**decimals
        if abs(scaled - round(scaled)) < 1e-6 * max(scaled, 1.0):
            return 10.0**-decimals
    return 10.0**-max_decimals


def _normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).strip().lower().replace(" ", "_") for column in frame.columns]
    return frame


def _pick(frame: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        if alias in frame.columns:
            return alias
    return None


def _as_utf8_csv(data: bytes) -> bytes:
    """A curve saved as an Excel workbook, or by Excel as "Unicode text"
    (UTF-16 with tabs) or in a Windows code page, as UTF-8 CSV bytes.
    Plain UTF-8 comes back unchanged."""
    # Imported here: the importers build on this module's types.
    from quant_trade.audit.importers import decode_text, xlsx_as_csv

    if data.startswith(b"PK\x03\x04"):
        return xlsx_as_csv(data, TIMESTAMP_ALIASES)
    if data.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in data[:4000]:
        return decode_text(data).encode("utf-8")
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return decode_text(data).encode("utf-8")
    return data


def _read_csv(data: bytes, *, what: str) -> pd.DataFrame:
    if data and len(data) <= MAX_UPLOAD_BYTES:
        data = _as_utf8_csv(data)
    if not data or not data.strip():
        raise ParseError(
            f"the {what} file is empty",
            message_es=f"El archivo {_file_es(what)} está vacío.",
            code="empty",
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise ParseError(
            f"the {what} file is {len(data):,} bytes; the limit is {MAX_UPLOAD_BYTES:,}",
            message_es=(
                f"El archivo {_file_es(what)} pesa {len(data):,} bytes; "
                f"el límite es {MAX_UPLOAD_BYTES:,}."
            ),
            code="too_large",
        )
    if max(len(line) for line in data.splitlines()) > MAX_CSV_LINE_BYTES:
        raise ParseError(
            f"a line of the {what} file is longer than {MAX_CSV_LINE_BYTES:,} bytes; "
            "it does not look like a CSV with one row per line",
            message_es=(
                f"Una línea del archivo {_file_es(what)} supera los {MAX_CSV_LINE_BYTES:,} "
                "bytes; no parece un CSV con una fila por línea."
            ),
            code="line_too_long",
        )
    try:
        frame = pd.read_csv(io.BytesIO(data), sep=None, engine="python", encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ParseError(
            f"the {what} file is not UTF-8 text",
            message_es=f"El archivo {_file_es(what)} no es texto UTF-8.",
            code="encoding",
        ) from exc
    except (pd.errors.ParserError, pd.errors.EmptyDataError, ValueError) as exc:
        raise ParseError(
            f"the {what} file could not be read as CSV: {exc}",
            # The parser's own words are English; the Spanish message says
            # what to check instead of repeating them.
            message_es=(
                f"El archivo {_file_es(what)} no se pudo leer como CSV: revisa que tenga una "
                "fila de encabezado y el mismo número de columnas en cada fila."
            ),
            code="not_csv",
        ) from exc
    if len(frame) > MAX_ROWS:
        raise ParseError(
            f"the {what} file has {len(frame):,} rows; the limit is {MAX_ROWS:,}",
            message_es=(
                f"El archivo {_file_es(what)} tiene {len(frame):,} filas; "
                f"el límite es {MAX_ROWS:,}."
            ),
            code="too_many_rows",
        )
    return _normalise_columns(frame)


def _to_numeric(series: pd.Series) -> tuple[pd.Series, bool]:
    """Coerce a possibly formatted column to floats; report whether ``%`` appeared."""
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").astype(float), False
    text = series.astype(str).str.strip()
    percent = bool(text.str.endswith("%").any())
    cleaned = text.str.replace(r"[%$,\s]", "", regex=True).replace({"": np.nan, "nan": np.nan})
    return pd.to_numeric(cleaned, errors="coerce").astype(float), percent


def _to_timestamps(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="coerce")
        unit = "ms" if numeric.abs().max() > 1e11 else "s"
        return pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
    return pd.to_datetime(series, utc=True, errors="coerce", format="mixed")


def _factsheet_grid(raw: pd.DataFrame) -> Any:
    # Imported here: ``factsheet`` is a leaf module but keeps this one light.
    from quant_trade.audit.factsheet import monthly_grid

    return monthly_grid(raw)


def _is_trade_list(raw: pd.DataFrame) -> bool:
    # Imported here: ``universal`` pulls in the importers, which import this module.
    from quant_trade.audit.universal import looks_like_trades

    return looks_like_trades([str(name) for name in raw.columns])


def parse_equity_csv(data: bytes, *, what: str = "equity") -> IngestedSeries:
    """Parse an equity-curve or return-series CSV into the canonical frame.

    Accepts a timestamp column plus either an equity column or a return
    column (see the alias tuples). With both present, equity wins and a
    warning is recorded. Percent-formatted returns are divided by 100.
    """
    raw = _read_csv(data, what=what)
    warnings: list[str] = []
    ts_col = _pick(raw, TIMESTAMP_ALIASES)
    grid = _factsheet_grid(raw) if ts_col is None else None
    companion: pd.DataFrame | None = None
    if grid is not None:
        companion = grid.benchmark
        # A factsheet's year-by-month table becomes a dated return series.
        raw = pd.DataFrame(
            {
                "timestamp": grid.frame["timestamp"].dt.strftime("%Y-%m-%d"),
                "return": grid.frame["ret"],
            }
        )
        warnings.extend(grid.warnings)
        ts_col = "timestamp"
    equity_col = _pick(raw, EQUITY_ALIASES)
    return_col = _pick(raw, RETURN_ALIASES)
    no_values = equity_col is None and return_col is None
    if (ts_col is None or no_values) and what == "equity" and _is_trade_list(raw):
        raise ParseError(
            "the equity curve file looks like a list of trades, not a curve: upload it "
            'in the "Your platform report" box',
            message_es=(
                "El archivo de la curva de equity parece una lista de operaciones, no una "
                "curva: súbelo en la casilla «Informe de tu plataforma»."
            ),
            code="trade_list_as_curve",
        )
    if ts_col is None:
        raise ParseError(
            f"the {what} file needs a timestamp column (one of: {', '.join(TIMESTAMP_ALIASES)})",
            message_es=(
                f"El archivo {_file_es(what)} necesita una columna de fecha "
                f"(una de: {', '.join(TIMESTAMP_ALIASES)})."
            ),
            code="missing_timestamp",
        )
    if no_values:
        raise ParseError(
            f"the {what} file needs an equity column (one of: {', '.join(EQUITY_ALIASES)}) "
            f"or a return column (one of: {', '.join(RETURN_ALIASES)})",
            message_es=(
                f"El archivo {_file_es(what)} necesita una columna de equity "
                f"(una de: {', '.join(EQUITY_ALIASES)}) o de retornos "
                f"(una de: {', '.join(RETURN_ALIASES)})."
            ),
            code="missing_value",
        )
    if equity_col is not None and return_col is not None:
        warnings.append(f"both {equity_col!r} and {return_col!r} present; using {equity_col!r}")
    source: Literal["equity", "returns"] = "equity" if equity_col is not None else "returns"
    value_col = equity_col if equity_col is not None else return_col
    assert value_col is not None

    timestamps = _to_timestamps(raw[ts_col])
    values, percent = _to_numeric(raw[value_col])
    if source == "returns":
        if percent:
            values = values / 100.0
            warnings.append("returns were percent-formatted; divided by 100")
        elif values.abs().median() > 0.5:
            values = values / 100.0
            warnings.append("returns look like percentages (median |r| > 0.5); divided by 100")
    if grid is None:
        companion = _benchmark_column(
            raw,
            timestamps,
            source,
            fund=values,
            skip={ts_col, value_col},
            warnings=warnings,
        )
    # "inf" and "1e400" read as numbers but are not values an account can hold.
    values = values.where(np.isfinite(values.astype(float)))
    frame = pd.DataFrame({"timestamp": timestamps, "value": values})
    unparseable = int(frame.isna().any(axis=1).sum())
    frame = frame.dropna()
    if unparseable:
        warnings.append(f"{unparseable} row(s) with an unreadable timestamp or value dropped")
    non_monotonic = bool(not frame["timestamp"].is_monotonic_increasing)
    frame = frame.sort_values("timestamp", kind="stable")
    duplicates = int(frame["timestamp"].duplicated().sum())
    frame = frame.drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    if len(frame) < 2:
        raise ParseError(
            f"the {what} file has fewer than two usable rows",
            message_es=f"El archivo {_file_es(what)} tiene menos de dos filas utilizables.",
            code="too_few_rows",
        )

    values = frame["value"].astype(float)
    limit = MAX_ACCOUNT_VALUE if source == "equity" else MAX_PERIOD_RETURN
    huge = values.abs() > limit
    if bool(huge.any()):
        when = frame.loc[huge.idxmax(), "timestamp"].strftime("%Y-%m-%d")
        raise ParseError(
            f"the {what} file has a value too large to be real on {when} (over {limit:,.0f}): "
            "check that the file's values were exported correctly and upload it again",
            message_es=(
                f"El archivo {_file_es(what)} tiene un valor demasiado grande para ser real "
                f"el {when} (más de {limit:,.0f}): revisa que los valores del archivo se hayan "
                "exportado bien y vuelve a subirlo."
            ),
            code="value_too_large",
        )
    bad = values <= 0 if source == "equity" else values <= -1
    if bool(bad.any()):
        when = frame.loc[bad.idxmax(), "timestamp"].strftime("%Y-%m-%d")
        if source == "equity":
            raise ParseError(
                f"the {what} file reaches zero or a negative value on {when}; the audit needs "
                "the account balance (for example 10000 growing to 12500), not a cumulative "
                "profit that starts at 0",
                message_es=(
                    f"El archivo {_file_es(what)} llega a cero o a un valor negativo el {when}; "
                    "la auditoría necesita el saldo de la cuenta (por ejemplo 10000 que sube a "
                    "12500), no la ganancia acumulada que empieza en 0."
                ),
                code="equity_not_positive",
            )
        raise ParseError(
            f"the {what} file has a return of -100 % or worse on {when}, which would leave "
            "the account at zero or below",
            message_es=(
                f"El archivo {_file_es(what)} tiene un retorno de -100 % o peor el {when}, "
                "lo que dejaría la cuenta en cero o menos."
            ),
            code="return_below_total_loss",
        )

    if source == "equity":
        equity = frame["value"].astype(float)
        ret = equity.pct_change().replace([np.inf, -np.inf], np.nan)
        out = pd.DataFrame({"timestamp": frame["timestamp"], "equity": equity, "ret": ret})
    else:
        ret = frame["value"].astype(float)
        spacing = frame["timestamp"].diff().dropna().median()
        base_time = frame["timestamp"].iloc[0] - spacing
        equity = (1.0 + ret).cumprod()
        out = pd.DataFrame(
            {
                "timestamp": pd.concat(
                    [pd.Series([base_time]), frame["timestamp"]], ignore_index=True
                ),
                "equity": pd.concat([pd.Series([1.0]), equity], ignore_index=True),
                "ret": pd.concat([pd.Series([np.nan]), ret], ignore_index=True),
            }
        )
    out = out.reset_index(drop=True)
    return IngestedSeries(
        frame=out,
        source=source,
        raw_rows=int(len(raw)),
        duplicate_timestamps=duplicates,
        unparseable_rows=unparseable,
        non_monotonic=non_monotonic,
        warnings=warnings,
        benchmark=companion,
    )


#: A column that carries a benchmark beside the fund's own values.
BENCHMARK_COLUMN = re.compile(r"^(benchmark|bench|bmk|index|indice|índice|referencia)(_\S*)?$")


#: A benchmark period above this return (1,000 %) is not an index's.
MAX_BENCHMARK_RETURN = 10.0


def _nearer_scale(values: pd.Series, fund: pd.Series) -> pd.Series:
    """Bare returns as they are, or divided by 100: whichever puts their
    median size nearer the fund's (compared as a ratio)."""
    own = float(values.abs().median())
    target = float(fund.abs().median())
    if not (own > 0 and target > 0) or not (np.isfinite(own) and np.isfinite(target)):
        return values
    as_is = abs(math.log(own / target))
    divided = abs(math.log(own / 100.0 / target))
    return values / 100.0 if divided < as_is else values


def _benchmark_column(
    raw: pd.DataFrame,
    timestamps: pd.Series,
    source: str,
    *,
    fund: pd.Series,
    skip: set[str | None],
    warnings: list[str],
) -> pd.DataFrame | None:
    """A benchmark column's returns (``timestamp``, ``ret``).

    Levels beside levels, returns beside returns; a ``%`` in the column's
    own cells marks returns in percent, even beside a curve of levels. Bare
    returns take the scale (as is, or divided by 100) that puts their median
    size nearer the fund's own returns, so each column's scale rests on its
    own evidence."""
    column = next(
        (str(c) for c in raw.columns if str(c) not in skip and BENCHMARK_COLUMN.match(str(c))),
        None,
    )
    if column is None:
        return None
    values, percent = _to_numeric(raw[column])
    numbers = values.dropna()
    counter = numbers.to_numpy()
    if len(counter) and np.array_equal(counter, np.arange(counter[0], counter[0] + len(counter))):
        return None  # a row number, not a benchmark
    as_returns = source == "returns" or percent
    if percent:
        values = values / 100.0
    elif as_returns:
        values = _nearer_scale(values, fund)
    frame = pd.DataFrame({"timestamp": timestamps, "value": values})
    frame = frame[np.isfinite(frame["value"].astype(float))].dropna()
    frame = frame.sort_values("timestamp", kind="stable").drop_duplicates("timestamp", keep="last")
    if as_returns:
        valid = bool(((frame["value"] > -1) & (frame["value"] <= MAX_BENCHMARK_RETURN)).all())
        ret = frame["value"].astype(float)
    else:
        valid = bool((frame["value"] > 0).all())
        ret = frame["value"].astype(float).pct_change()
        valid = valid and bool((ret.dropna() <= MAX_BENCHMARK_RETURN).all())
    if len(frame) < 2 or not valid:
        warnings.append(f"the benchmark column {column!r} could not be read; left out")
        return None
    warnings.append(f"benchmark column {column!r} read: the fund section compares the fund with it")
    return (
        pd.DataFrame({"timestamp": frame["timestamp"], "ret": ret}).dropna().reset_index(drop=True)
    )


def _side(value: Any) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "long"
    text = str(value).strip().lower()
    if text in LONG_SIDES or text == "":
        return "long"
    if text in SHORT_SIDES:
        return "short"
    return None


def parse_trades_csv(data: bytes) -> ParsedTrades:
    """Parse closed round trips (what MetaTrader and TradingView export).

    Required: entry time, exit time, quantity, entry price, exit price.
    Optional: side (long by default) and the client's own pnl, which is kept
    only to compare against the recomputed figure.
    """
    raw = _read_csv(data, what="trades")
    if len(raw) > MAX_TRADES:
        raise ParseError(
            f"the trades file has {len(raw):,} rows; the limit is {MAX_TRADES:,}",
            message_es=(
                f"El archivo de operaciones tiene {len(raw):,} filas; el límite es {MAX_TRADES:,}."
            ),
            code="too_many_trades",
        )
    columns = {
        "entry_time": _pick(raw, TRADE_ENTRY_TIME),
        "exit_time": _pick(raw, TRADE_EXIT_TIME),
        "quantity": _pick(raw, TRADE_QUANTITY),
        "entry_price": _pick(raw, TRADE_ENTRY_PRICE),
        "exit_price": _pick(raw, TRADE_EXIT_PRICE),
    }
    missing = [name for name, column in columns.items() if column is None]
    if missing:
        raise ParseError(
            "the trades file is missing column(s): "
            + ", ".join(missing)
            + " (entry_time, exit_time, quantity, entry_price, exit_price are required)",
            message_es=(
                "Al archivo de operaciones le faltan columnas: "
                + ", ".join(missing)
                + " (se requieren entry_time, exit_time, quantity, entry_price y exit_price)."
            ),
            code="missing_trade_columns",
        )
    side_col = _pick(raw, TRADE_SIDE)
    pnl_col = _pick(raw, TRADE_PNL)
    warnings: list[str] = []
    if side_col is None:
        warnings.append("no side column; every trade treated as long")

    entry_time = _to_timestamps(raw[columns["entry_time"]])
    exit_time = _to_timestamps(raw[columns["exit_time"]])
    quantity, _ = _to_numeric(raw[columns["quantity"]])
    entry_price, _ = _to_numeric(raw[columns["entry_price"]])
    exit_price, _ = _to_numeric(raw[columns["exit_price"]])
    client_pnl_series = _to_numeric(raw[pnl_col])[0] if pnl_col else None

    trades: list[Trade] = []
    sides: list[str] = []
    client_pnl: list[float | None] = []
    invalid = 0
    for index in range(len(raw)):
        side = _side(raw[side_col].iloc[index]) if side_col else "long"
        qty = float(quantity.iloc[index])
        price_in = float(entry_price.iloc[index])
        price_out = float(exit_price.iloc[index])
        t_in = entry_time.iloc[index]
        t_out = exit_time.iloc[index]
        if (
            side is None
            or pd.isna(t_in)
            or pd.isna(t_out)
            or t_out < t_in
            or not all(math.isfinite(v) for v in (qty, price_in, price_out))
        ):
            invalid += 1
            continue
        qty = abs(qty)
        sign = 1.0 if side == "long" else -1.0
        pnl = sign * (price_out - price_in) * qty
        notional = price_in * qty
        try:
            trade = Trade(
                entry_time=t_in.to_pydatetime(),
                exit_time=t_out.to_pydatetime(),
                quantity=qty,
                entry_price=price_in,
                exit_price=price_out,
                pnl=pnl,
                return_pct=pnl / notional if notional > 0 else 0.0,
            )
        except ValueError:
            invalid += 1
            continue
        trades.append(trade)
        sides.append(side)
        if client_pnl_series is None:
            client_pnl.append(None)
        else:
            reported = float(client_pnl_series.iloc[index])
            client_pnl.append(reported if math.isfinite(reported) else None)
    if invalid:
        warnings.append(f"{invalid} trade row(s) with unreadable or non-positive fields dropped")
    if not trades:
        raise ParseError(
            "the trades file contains no usable trades",
            message_es="El archivo de operaciones no contiene ninguna operación utilizable.",
            code="no_trades",
        )
    return ParsedTrades(
        trades=trades,
        sides=sides,
        client_pnl=client_pnl,
        invalid_rows=invalid,
        warnings=warnings,
    )


def parse_variants_csv(data: bytes) -> np.ndarray:
    """Parse an observations-by-variants return matrix for CSCV.

    A leading timestamp column is dropped; every remaining column must be a
    finite numeric return series on the same rows.
    """
    raw = _read_csv(data, what="variants")
    ts_col = _pick(raw, TIMESTAMP_ALIASES)
    if ts_col is not None:
        raw = raw.drop(columns=[ts_col])
    numeric = raw.apply(lambda column: _to_numeric(column)[0])
    numeric = numeric.dropna(axis=1, how="all")
    if numeric.shape[1] < 2:
        raise ParseError(
            "the variants file needs at least two numeric return columns",
            message_es=(
                "El archivo de variantes necesita al menos dos columnas numéricas de retornos."
            ),
            code="too_few_variants",
        )
    if numeric.shape[1] > MAX_VARIANTS:
        raise ParseError(
            f"the variants file has {numeric.shape[1]} columns; the limit is {MAX_VARIANTS}",
            message_es=(
                f"El archivo de variantes tiene {numeric.shape[1]} columnas; "
                f"el límite es {MAX_VARIANTS}."
            ),
            code="too_many_variants",
        )
    matrix = numeric.to_numpy(dtype=float)
    if not np.isfinite(matrix).all():
        raise ParseError(
            "the variants file contains empty or non-numeric cells",
            message_es="El archivo de variantes contiene celdas vacías o no numéricas.",
            code="variants_not_numeric",
        )
    if len(matrix) < 16:
        raise ParseError(
            "the variants file needs at least 16 rows",
            message_es="El archivo de variantes necesita al menos 16 filas.",
            code="too_few_variant_rows",
        )
    return matrix


FREQUENCY_LABELS: tuple[tuple[float, str], ...] = (
    (14.0, "monthly"),
    (60.0, "weekly"),
    (270.0, "daily_trading"),
    (400.0, "daily_calendar"),
    (9000.0, "hourly"),
)


def infer_frequency(timestamps: pd.Series) -> tuple[float, str]:
    ppy = float(periods_per_year(timestamps))
    for upper, label in FREQUENCY_LABELS:
        if ppy <= upper:
            return ppy, label
    return ppy, "intraday"


@dataclass(frozen=True)
class AuditInputs:
    """Everything the engine needs, already parsed and hashed."""

    equity: IngestedSeries
    declared: DeclaredMetadata
    digests: dict[str, str]
    periods_per_year: float
    frequency_label: str
    trades: ParsedTrades | None = None
    benchmark: IngestedSeries | None = None
    variants: np.ndarray | None = None
    warnings: list[str] = field(default_factory=list)
    #: ``csv`` for hand-made uploads, else the importer's format name.
    source_format: str = "csv"
    #: The instrument of each trade when the source names it.
    trade_symbols: list[str] | None = None
    #: Signed cost totals a platform report itemises (negative is a cost).
    reported_fees: dict[str, float] = field(default_factory=dict)
    #: The platform's descriptive fields and own summary figures (DECLARED).
    report_metadata: dict[str, str] = field(default_factory=dict)
    #: Starting balance of an imported report and where it came from.
    initial_balance: float | None = None
    #: True when the equity curve was rebuilt from closed trades.
    balance_only: bool = False
    #: Configurations an MT5 optimisation export lists (MEASURED trials).
    optimization_passes: int | None = None
    optimization_parameters: list[str] = field(default_factory=list)
    #: Numeric cells of each optimisation pass (``OptimizationSummary.table``).
    optimization_table: list[dict[str, float]] = field(default_factory=list)
    #: Parameter variants a report says it holds (vectorbt), when more than one.
    report_variants: int | None = None
    #: Deposits and withdrawals an imported account history lists.
    cash_flows: list[tuple[datetime, float]] = field(default_factory=list)
    #: Closed trades of a live (or demo) account statement, compared with the
    #: backtest (``audit/live.py``); never mixed into the backtest's figures.
    live_trades: ParsedTrades | None = None
    live_symbols: list[str] | None = None
    live_format: str | None = None
    #: Deposits, platform summary and balance curve of the live statement,
    #: for the account review when the main upload is a backtest.
    live_cash_flows: list[tuple[datetime, float]] = field(default_factory=list)
    live_metadata: dict[str, str] = field(default_factory=dict)
    live_equity_csv: bytes | None = None


def report_digest_name(filename: str | None, stem: str = "report") -> str:
    """``report.<ext>`` with the upload's extension when it is a known one."""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    return f"{stem}.{ext if ext in REPORT_EXTENSIONS else 'bin'}"


def live_digest_name(filename: str | None) -> str:
    """``live.<ext>``: the stored name of a live account statement."""
    return report_digest_name(filename, "live")


#: A date this far past the moment of the upload is not a record: a file
#: written in a server's time zone can be up to a day ahead of UTC.
FUTURE_SLACK = timedelta(days=1)
FUTURE_FLAT_WARNING = "future period(s) with no change dropped (they have not happened yet)"

_FILE_EN = {"equity": "equity", "report": "report", "benchmark": "benchmark",
            "trades": "trades", "live": "live account statement"}  # fmt: skip
_FILE_ES = {"equity": "de la curva de equity", "report": "del informe",
            "benchmark": "del benchmark", "trades": "de operaciones",
            "live": "del estado de cuenta real"}  # fmt: skip


def _future_error(what: str, when: datetime) -> ParseError:
    day = when.strftime("%Y-%m-%d")
    return ParseError(
        f"the {_FILE_EN[what]} file has a date in the future ({day}): a track record can "
        "only hold dates that have already happened; check the file's dates and upload it again",
        message_es=(
            f"El archivo {_FILE_ES[what]} tiene una fecha en el futuro ({day}): un historial "
            "solo puede tener fechas que ya pasaron; revisa las fechas del archivo y vuelve a "
            "subirlo."
        ),
        code="future_dates",
    )


def _without_future(series: IngestedSeries, what: str, now: datetime) -> tuple[IngestedSeries, int]:
    """The series without its trailing flat future rows, and how many were
    dropped; refused if a future row moves the account.

    A fund's year-by-month table prints this year's months that have not
    happened yet as 0; they say nothing and are dropped. Any other future
    date is a damaged file. A monthly series dates each month by its last
    day, so this month's row is not in the future.
    """
    frame = series.frame
    cutoff = now + FUTURE_SLACK
    if len(frame) >= 3 and infer_frequency(frame["timestamp"])[0] < 20:
        month_end = (pd.Timestamp(now) + pd.offsets.MonthEnd(0)).to_pydatetime()
        cutoff = max(cutoff, month_end + FUTURE_SLACK)
    future = frame["timestamp"] > cutoff
    if not bool(future.any()):
        return series, 0
    flat = future & (frame["ret"] == 0)
    first_future = int(future.to_numpy().argmax())
    if bool(flat.iloc[first_future:].all()) and first_future >= 2:
        kept = frame.iloc[:first_future].reset_index(drop=True)
        return replace(series, frame=kept), int(len(frame) - first_future)
    raise _future_error(what, frame.loc[future.to_numpy().argmax(), "timestamp"].to_pydatetime())


def _refuse_future_trades(trades: ParsedTrades | None, what: str, cutoff: datetime) -> None:
    if trades is None:
        return
    late = [trade.exit_time for trade in trades.trades if trade.exit_time > cutoff]
    if late:
        raise _future_error(what, min(late))


def build_inputs(
    equity_bytes: bytes | None,
    declared: DeclaredMetadata,
    *,
    trades_bytes: bytes | None = None,
    benchmark_bytes: bytes | None = None,
    variants_bytes: bytes | None = None,
    report_bytes: bytes | None = None,
    report_filename: str | None = None,
    optimization_bytes: bytes | None = None,
    live_bytes: bytes | None = None,
    live_filename: str | None = None,
    report_columns: dict[str, str] | None = None,
    now: datetime | None = None,
) -> AuditInputs:
    """Parse and hash every upload.

    A platform report (``report_bytes``) supplies the closed trades and, when
    no equity file is uploaded, the closed-trade balance curve. An MT5
    optimisation export (``optimization_bytes``) supplies the number of
    configurations tried, which the deflated Sharpe uses as a MEASURED trial
    count when it exceeds the declared one. A live account statement
    (``live_bytes``, any format a report can have) is read for its closed
    trades only and compared with the backtest; it changes no other figure.
    ``report_columns`` is the customer's own mapping of the report's columns
    (``universal.ROLES`` to column names), for a platform no importer knows.
    A date more than a day after ``now`` (the upload's time) is refused.
    """
    # Imported here: the importers build on this module's types.
    from quant_trade.audit.importers import (
        MT5_TESTER_HTML,
        MT5_TESTER_XLSX,
        import_report,
        optimization_mismatch,
        parse_optimization,
    )

    digests: dict[str, str] = {}
    warnings: list[str] = []
    trades = None
    extra: dict[str, Any] = {}
    imported = None
    if report_bytes:
        if trades_bytes:
            raise ParseError(
                "upload either a platform report or a trades file, not both",
                message_es="Sube un informe de plataforma o un archivo de operaciones, no ambos.",
                code="trades_and_report",
            )
        imported = import_report(
            report_bytes,
            report_filename,
            initial_balance=declared.initial_balance,
            columns=report_columns or None,
        )
        digests[report_digest_name(report_filename)] = sha256_of_bytes(report_bytes)
        trades = imported.trades
        warnings.extend(f"report: {w}" for w in imported.warnings)
        extra = {
            "source_format": imported.source_format,
            "trade_symbols": list(imported.symbols) or None,
            "reported_fees": dict(imported.fees),
            "report_metadata": dict(imported.metadata),
            "initial_balance": imported.initial_balance,
            "cash_flows": list(imported.cash_flows),
        }
        variants_in_report = imported.metadata.get("variants", "")
        if variants_in_report.isdigit() and int(variants_in_report) > 1:
            extra["report_variants"] = int(variants_in_report)
    if equity_bytes:
        equity = parse_equity_csv(equity_bytes)
        digests["equity.csv"] = sha256_of_bytes(equity_bytes)
        warnings[:0] = [f"equity: {w}" for w in equity.warnings]
        if imported is not None:
            warnings.append(
                "equity: the uploaded equity file is used for returns; the report supplies "
                "the trades"
            )
    elif imported is not None:
        equity = parse_equity_csv(imported.equity_csv, what="report")
        warnings.extend(f"equity: {w}" for w in equity.warnings)
        extra["balance_only"] = True
    else:
        raise ParseError(
            "an equity curve or a platform report is required",
            message_es="Hace falta una curva de equity o un informe de la plataforma.",
            code="equity_required",
        )
    if trades_bytes:
        trades = parse_trades_csv(trades_bytes)
        digests["trades.csv"] = sha256_of_bytes(trades_bytes)
        warnings.extend(f"trades: {w}" for w in trades.warnings)
    benchmark = None
    if benchmark_bytes:
        benchmark = parse_equity_csv(benchmark_bytes, what="benchmark")
        digests["benchmark.csv"] = sha256_of_bytes(benchmark_bytes)
        warnings.extend(f"benchmark: {w}" for w in benchmark.warnings)
    variants = None
    if variants_bytes:
        variants = parse_variants_csv(variants_bytes)
        digests["variants.csv"] = sha256_of_bytes(variants_bytes)
    if optimization_bytes:
        summary = parse_optimization(optimization_bytes)
        # Checked against an MT5 tester report only: that is the file the
        # export comes from, and the one whose inputs the plateau matches.
        mismatch = (
            optimization_mismatch(summary, imported.metadata)
            if imported is not None and imported.source_format in {MT5_TESTER_HTML, MT5_TESTER_XLSX}
            else None
        )
        if mismatch is not None:
            what, theirs, ours = mismatch
            what_es = {"robot": "robot", "symbol": "símbolo", "timeframe": "marco temporal",
                       "inputs": "parámetros"}[what]  # fmt: skip
            raise ParseError(
                f"the optimisation file is for another test ({what} {theirs}; the report says "
                f"{ours}): upload the optimisation of the same robot, symbol and timeframe",
                message_es=f"El archivo de optimización es de otra prueba ({what_es} {theirs}; "
                f"el informe dice {ours}): sube la optimización del mismo robot, símbolo y "
                "marco temporal.",
                code="optimization_mismatch",
            )
        digests["optimization.xml"] = sha256_of_bytes(optimization_bytes)
        warnings.extend(f"optimization: {w}" for w in summary.warnings)
        extra["optimization_passes"] = summary.passes
        extra["optimization_parameters"] = list(summary.parameters)
        extra["optimization_table"] = list(summary.table)
    if live_bytes:
        try:
            live = import_report(live_bytes, live_filename)
        except ParseError as exc:
            # Said of the live statement: the same words about the backtest
            # would send the customer to fix the wrong file.
            raise ParseError(
                f"the live account statement: {exc}",
                message_es=f"Estado de cuenta real: {exc.message_es}",
                code=exc.code,
            ) from exc
        digests[live_digest_name(live_filename)] = sha256_of_bytes(live_bytes)
        warnings.extend(f"live: {w}" for w in live.warnings)
        extra["live_trades"] = live.trades
        extra["live_symbols"] = list(live.symbols) or None
        extra["live_format"] = live.source_format
        extra["live_cash_flows"] = list(live.cash_flows)
        extra["live_metadata"] = dict(live.metadata)
        extra["live_equity_csv"] = live.equity_csv
    now = now or datetime.now(UTC)
    cutoff = now + FUTURE_SLACK
    equity, dropped = _without_future(
        equity, "report" if extra.get("balance_only") else "equity", now
    )
    if dropped:
        warnings.append(f"equity: {dropped} {FUTURE_FLAT_WARNING}")
    if benchmark is not None:
        benchmark, dropped = _without_future(benchmark, "benchmark", now)
        if dropped:
            warnings.append(f"benchmark: {dropped} {FUTURE_FLAT_WARNING}")
    _refuse_future_trades(trades, "trades" if trades_bytes else "report", cutoff)
    if "live_trades" in extra:
        _refuse_future_trades(extra["live_trades"], "live", cutoff)
    ppy, label = infer_frequency(equity.frame["timestamp"])
    return AuditInputs(
        equity=equity,
        declared=declared,
        digests=digests,
        periods_per_year=ppy,
        frequency_label=label,
        trades=trades,
        benchmark=benchmark,
        variants=variants,
        warnings=warnings,
        **extra,
    )


class Dimension(BaseModel):
    """One of the six questions the verdict answers."""

    model_config = ConfigDict(extra="forbid")

    name: str
    status: Literal["PASS", "WEAK", "FAIL", "NOT_MEASURED", "NOT_APPLICABLE"]
    reasons: list[str] = Field(default_factory=list)
    #: The same reasons in Spanish; empty in results written before schema 2.
    reasons_es: list[str] = Field(default_factory=list)
    inputs: dict[str, Any] = Field(default_factory=dict)

    def reasons_in(self, locale: str) -> list[str]:
        """The reasons in ``locale``; English when no Spanish text was stored."""
        if locale == "es" and self.reasons_es:
            return list(self.reasons_es)
        return list(self.reasons)


class Verdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: Literal["A", "B", "C", "D"]
    summary: str
    thresholds: dict[str, float]
    dimensions: list[Dimension]


class AuditResult(BaseModel):
    """The whole audit, JSON-serialisable and NaN-free by construction."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str
    schema_version: int = SCHEMA_VERSION
    generated_at_utc: str
    engine: dict[str, Any]
    inputs: dict[str, Any]
    declared: dict[str, Any]
    performance: dict[str, Any]
    significance: dict[str, Any]
    multiplicity: dict[str, Any]
    bootstrap: dict[str, Any]
    subperiods: list[dict[str, Any]]
    rolling: list[dict[str, Any]]
    holdout: dict[str, Any]
    costs: dict[str, Any]
    benchmark: dict[str, Any]
    cscv: dict[str, Any]
    red_flags: list[dict[str, Any]]
    client_text_findings: list[dict[str, Any]]
    seal: dict[str, Any]
    verdict: Verdict
    # Schema 2. Optional so that results stored under schema 1 still load.
    series: dict[str, Any] | None = None
    trade_stats: dict[str, Any] | None = None
    #: Robustness stress tests (``audit/stress.py``); None on older results.
    stress: dict[str, Any] | None = None
    #: Trades by entry weekday and time of day (``audit/timing.py``).
    timing: dict[str, Any] | None = None
    #: A live account statement against the backtest (``audit/live.py``);
    #: ``None`` when no statement was uploaded.
    live: dict[str, Any] | None = None
    risk: dict[str, Any] | None = None
    challenge: dict[str, Any] | None = None
    #: Deposits, withdrawals and open positions of an account history
    #: (``audit/account.py``); None on older results.
    account: dict[str, Any] | None = None
    #: Tick model, data quality and test window of a MetaTrader tester
    #: report (``audit/testdata.py``); None on older results.
    test_data: dict[str, Any] | None = None
    #: Capital and size for each loss limit (``audit/sizing.py``); None on
    #: older results.
    capital: dict[str, Any] | None = None
    #: The chosen settings against their neighbours in an MT5 optimisation
    #: export (``audit/plateau.py``); None on older results.
    plateau: dict[str, Any] | None = None
    #: The optimisation's back against forward results (``audit/forward.py``);
    #: None on older results.
    forward: dict[str, Any] | None = None
    #: The recent third of the history against the earlier two (``audit/decay.py``).
    recent: dict[str, Any] | None = None
    #: Hold times, re-entries and streaks around losses (``audit/behaviour.py``).
    behaviour: dict[str, Any] | None = None
    #: Count, net result and hit rate per instrument (``audit/instruments.py``).
    instruments: dict[str, Any] | None = None
    #: Calendar table and fund-investor checks of a monthly track record (``audit/fund.py``).
    fund: dict[str, Any] | None = None
    #: A dated curve through fixed market-fall windows (``audit/crises.py``),
    #: when the fund section does not already show them.
    crises: dict[str, Any] | None = None
    #: The strategy beside simply holding the market it trades (``audit/holding.py``).
    holding: dict[str, Any] | None = None
    #: The Sharpe ratio after what a US Treasury bill paid (``audit/cashrate.py``).
    cash_rate: dict[str, Any] | None = None
    vix_regime: dict[str, Any] | None = None
    #: The Sharpe next to the luck of the configurations tried (``audit/luck.py``).
    luck: dict[str, Any] | None = None
    #: Time under water, worst day and month, monthly hit rate (``audit/ride.py``).
    ride: dict[str, Any] | None = None
    vendor_questions: list[dict[str, str]] = Field(default_factory=list)


__all__ = [
    "printed_step",
    "DECLARED",
    "MAX_ROWS",
    "MAX_TRADES",
    "MAX_REPORT_BYTES",
    "MAX_UPLOAD_BYTES",
    "MAX_CSV_LINE_BYTES",
    "MAX_VARIANTS",
    "MEASURED",
    "MIN_OBSERVATIONS",
    "NOT_MEASURED",
    "SCHEMA_VERSION",
    "AuditInputs",
    "AuditResult",
    "DeclaredMetadata",
    "Dimension",
    "Evidence",
    "IngestedSeries",
    "ParseError",
    "ParsedTrades",
    "Verdict",
    "build_inputs",
    "declared",
    "infer_frequency",
    "measured",
    "not_measured",
    "parse_equity_csv",
    "parse_trades_csv",
    "parse_variants_csv",
    "report_digest_name",
]
