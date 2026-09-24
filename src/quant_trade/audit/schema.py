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
from dataclasses import dataclass, field
from datetime import UTC, datetime
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
MAX_ROWS = 200_000
MAX_TRADES = 50_000
MAX_VARIANTS = 500
#: Longest CSV line read. Pandas infers columns in time that grows with the
#: square of their count, and a 5 MB line of fields pins a worker for minutes;
#: a header of 500 variant names, or a row of 500 returns, fits in 32 KB.
MAX_CSV_LINE_BYTES = 32_768
MIN_OBSERVATIONS = 30

TIMESTAMP_ALIASES = ("timestamp", "date", "datetime", "time", "ts", "fecha")
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
REPORT_EXTENSIONS = ("html", "htm", "csv", "xlsx", "txt", "xml")


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
    locale: Literal["es", "en"] = "es"
    #: Starting balance, used only when an imported report does not state one.
    initial_balance: float | None = Field(None, gt=0.0, le=1e12)
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


def _normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame.columns = [str(column).strip().lower().replace(" ", "_") for column in frame.columns]
    return frame


def _pick(frame: pd.DataFrame, aliases: tuple[str, ...]) -> str | None:
    for alias in aliases:
        if alias in frame.columns:
            return alias
    return None


def _read_csv(data: bytes, *, what: str) -> pd.DataFrame:
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
            message_es=f"El archivo {_file_es(what)} no se pudo leer como CSV: {exc}",
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


def parse_equity_csv(data: bytes, *, what: str = "equity") -> IngestedSeries:
    """Parse an equity-curve or return-series CSV into the canonical frame.

    Accepts a timestamp column plus either an equity column or a return
    column (see the alias tuples). With both present, equity wins and a
    warning is recorded. Percent-formatted returns are divided by 100.
    """
    raw = _read_csv(data, what=what)
    warnings: list[str] = []
    ts_col = _pick(raw, TIMESTAMP_ALIASES)
    if ts_col is None:
        raise ParseError(
            f"the {what} file needs a timestamp column (one of: {', '.join(TIMESTAMP_ALIASES)})",
            message_es=(
                f"El archivo {_file_es(what)} necesita una columna de fecha "
                f"(una de: {', '.join(TIMESTAMP_ALIASES)})."
            ),
            code="missing_timestamp",
        )
    equity_col = _pick(raw, EQUITY_ALIASES)
    return_col = _pick(raw, RETURN_ALIASES)
    if equity_col is None and return_col is None:
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
    #: Parameter variants a report says it holds (vectorbt), when more than one.
    report_variants: int | None = None


def report_digest_name(filename: str | None) -> str:
    """``report.<ext>`` with the upload's extension when it is a known one."""
    ext = (filename or "").rsplit(".", 1)[-1].lower() if filename and "." in filename else ""
    return f"report.{ext if ext in REPORT_EXTENSIONS else 'bin'}"


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
) -> AuditInputs:
    """Parse and hash every upload.

    A platform report (``report_bytes``) supplies the closed trades and, when
    no equity file is uploaded, the closed-trade balance curve. An MT5
    optimisation export (``optimization_bytes``) supplies the number of
    configurations tried, which the deflated Sharpe uses as a MEASURED trial
    count when it exceeds the declared one.
    """
    # Imported here: the importers build on this module's types.
    from quant_trade.audit.importers import import_report, parse_optimization

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
            report_bytes, report_filename, initial_balance=declared.initial_balance
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
        digests["optimization.xml"] = sha256_of_bytes(optimization_bytes)
        warnings.extend(f"optimization: {w}" for w in summary.warnings)
        extra["optimization_passes"] = summary.passes
        extra["optimization_parameters"] = list(summary.parameters)
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
    risk: dict[str, Any] | None = None
    challenge: dict[str, Any] | None = None
    vendor_questions: list[dict[str, str]] = Field(default_factory=list)


__all__ = [
    "DECLARED",
    "MAX_ROWS",
    "MAX_TRADES",
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
