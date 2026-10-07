"""Period return tables, with an implicit unit base and no invented dates.

The values in ``ret`` are authoritative, including the first supplied return.
The equity index ends each supplied period; its initial unit base has no date.
Unit and frequency detection are interpretations of client declarations, not
independent evidence of when or how the returns were generated.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.schema import (
    EQUITY_ALIASES,
    MAX_PERIOD_RETURN,
    RETURN_ALIASES,
    TIMESTAMP_ALIASES,
    IngestedSeries,
    ParseError,
    _benchmark_column,
    _date_order_note,
    _day_first,
    _pick,
    _read_csv,
    _to_numeric,
    _to_timestamps,
)

FREQUENCIES: dict[str, int] = {"daily": 252, "weekly": 52, "monthly": 12}
GROSS_ALIASES = ("gross_return", "gross_returns")
NET_ALIASES = ("net_return", "net_returns")

# Kept together so every new error can be checked by the claims guard.
ERRORS: dict[str, dict[str, str]] = {
    "return_columns": {
        "en": "Use a date column and a return, gross_return or net_return column.",
        "es": "Usa una columna date y una columna return, gross_return o net_return.",
        "pt": "Use uma coluna date e uma coluna return, gross_return ou net_return.",
    },
    "return_frequency": {
        "en": "Choose daily, weekly or monthly return frequency.",
        "es": "Elige una frecuencia de rendimientos diaria, semanal o mensual.",
        "pt": "Escolha uma frequência de retornos diária, semanal ou mensal.",
    },
    "return_frequency_unknown": {
        "en": "The dates do not identify a regular frequency; declare daily, weekly or monthly.",
        "es": (
            "Las fechas no identifican una frecuencia regular; declara diaria, semanal o mensual."
        ),
        "pt": "As datas não identificam uma frequência regular; declare diária, semanal ou mensal.",
    },
    "return_frequency_mismatch": {
        "en": "The selected return frequency differs from the dates; check the selection and file.",
        "es": "La frecuencia elegida difiere de las fechas; revisa la selección y el archivo.",
        "pt": "A frequência escolhida difere das datas; confira a seleção e o arquivo.",
    },
    "return_unit": {
        "en": "Choose fractions or percentages for the return unit.",
        "es": "Elige fracciones o porcentajes como unidad de los rendimientos.",
        "pt": "Escolha frações ou porcentagens como unidade dos retornos.",
    },
    "return_unit_mismatch": {
        "en": "The fraction selection conflicts with percentage signs in the file.",
        "es": "La selección de fracciones contradice los signos de porcentaje del archivo.",
        "pt": "A seleção de frações contradiz os sinais de porcentagem do arquivo.",
    },
    "return_unit_mixed": {
        "en": "The return column mixes percentage signs with unmarked values; use one unit.",
        "es": "La columna mezcla signos de porcentaje y valores sin unidad; usa una sola unidad.",
        "pt": "A coluna mistura sinais de porcentagem e valores sem unidade; use uma só unidade.",
    },
    "return_rows": {
        "en": "The return table needs at least two usable dates.",
        "es": "La tabla de rendimientos necesita al menos dos fechas utilizables.",
        "pt": "A tabela de retornos precisa de pelo menos duas datas utilizáveis.",
    },
    "return_values": {
        "en": "A return is outside the supported range; check the values and their unit.",
        "es": "Un rendimiento está fuera del rango admitido; revisa los valores y su unidad.",
        "pt": "Um retorno está fora do intervalo aceito; confira os valores e sua unidade.",
    },
    "return_compounding": {
        "en": "The compounded return index is outside the supported numeric range.",
        "es": "El índice de rendimientos compuestos está fuera del rango numérico admitido.",
        "pt": "O índice de retornos compostos está fora do intervalo numérico aceito.",
    },
}


class ReturnSeriesError(ParseError):
    """A return-table error with native copy in all customer languages."""

    def __init__(self, code: str) -> None:
        copy = ERRORS[code]
        super().__init__(copy["en"], message_es=copy["es"], code=code)

    def localized(self, locale: str) -> str:
        return ERRORS[self.code].get(locale, str(self))


def _columns(raw: pd.DataFrame) -> tuple[str | None, str | None, str | None, str | None]:
    return (
        _pick(raw, TIMESTAMP_ALIASES),
        _pick(raw, RETURN_ALIASES, percent=True),
        _pick(raw, GROSS_ALIASES, percent=True),
        _pick(raw, NET_ALIASES, percent=True),
    )


def is_return_series(data: bytes) -> bool:
    """Detect a dated return table by content; an explicit equity column wins."""
    try:
        raw = _read_csv(data, what="equity")
    except ParseError:
        return False
    stamp, plain, gross, net = _columns(raw)
    return stamp is not None and any((plain, gross, net)) and _pick(raw, EQUITY_ALIASES) is None


def infer_return_frequency(timestamps: pd.Series) -> str | None:
    """Identify a regular daily, weekly or monthly calendar without adding rows."""
    stamps = pd.to_datetime(timestamps, utc=True).sort_values().reset_index(drop=True)
    gaps = stamps.diff().dropna().dt.total_seconds() / 86400.0
    if gaps.empty or bool((gaps <= 0).any()):
        return None
    months = stamps.dt.year * 12 + stamps.dt.month
    if bool((months.diff().dropna() == 1).all()) and bool(gaps.between(24, 35).all()):
        return "monthly"
    if bool(gaps.between(5, 9).all()) and 6 <= float(gaps.median()) <= 8:
        return "weekly"
    # Weekends and short market holidays are gaps, not fabricated observations.
    if 1 <= float(gaps.median()) <= 3 and bool(gaps.between(1, 5).all()):
        return "daily"
    return None


def _values(raw: pd.DataFrame, column: str, unit: str | None) -> tuple[pd.Series, str, str]:
    values, has_percent = _to_numeric(raw[column])
    marked = has_percent or "%" in column
    if unit == "fraction" and marked:
        raise ReturnSeriesError("return_unit_mismatch")
    if has_percent and "%" not in column and unit is None:
        marked_cells = raw[column].astype(str).str.strip().str.endswith("%")
        if bool((~marked_cells & values.notna() & values.ne(0)).any()):
            raise ReturnSeriesError("return_unit_mixed")
    inferred = "percent" if marked or values.abs().median() > 0.5 else "fraction"
    selected = unit or inferred
    if selected == "percent":
        values = values / 100.0
    return values.where(np.isfinite(values)), selected, inferred


def import_return_series(
    data: bytes,
    *,
    frequency: str | None = None,
    unit: str | None = None,
    what: str = "equity",
) -> IngestedSeries:
    """Read CSV/XLSX returns, preserving every usable supplied period and date."""
    if frequency not in (None, *FREQUENCIES):
        raise ReturnSeriesError("return_frequency")
    if unit not in (None, "fraction", "percent"):
        raise ReturnSeriesError("return_unit")
    raw = _read_csv(data, what=what)
    stamp, plain, gross, net = _columns(raw)
    chosen = net or plain or gross
    if stamp is None or chosen is None:
        raise ReturnSeriesError("return_columns")
    day_first = _day_first([raw[stamp]], what=what)
    warnings = _date_order_note(day_first)
    timestamps = _to_timestamps(raw[stamp], day_first=day_first)
    values, selected_unit, inferred_unit = _values(raw, chosen, unit)
    frame = pd.DataFrame({"timestamp": timestamps, "ret": values})
    metadata: dict[str, Any] = {
        "unit": selected_unit,
        "unit_inferred": inferred_unit,
        "unit_confirmed": unit is not None,
        "basis": "net" if net else "gross" if chosen == gross else "return",
    }
    if gross is not None and net is not None:
        for column, target, key in (
            (gross, "gross_ret", "gross_unit"),
            (net, "net_ret", "net_unit"),
        ):
            frame[target], metadata[key], _ = _values(raw, column, unit)
    # Drop a damaged row as a unit: gross, net and the selected series never
    # acquire different calendars through independent filtering.
    unparseable = int(frame.isna().any(axis=1).sum())
    frame = frame.dropna()
    if unparseable:
        warnings.append(f"{unparseable} row(s) with an unreadable timestamp or value dropped")
    non_monotonic = not frame["timestamp"].is_monotonic_increasing
    frame = frame.sort_values("timestamp", kind="stable")
    duplicates = int(frame["timestamp"].duplicated().sum())
    frame = frame.drop_duplicates("timestamp", keep="last").reset_index(drop=True)
    if len(frame) < 2:
        raise ReturnSeriesError("return_rows")
    for column in frame.columns.difference(["timestamp"]):
        values = frame[column]
        if bool(((values <= -1) | (values.abs() > MAX_PERIOD_RETURN)).any()):
            raise ReturnSeriesError("return_values")
    inferred_frequency = infer_return_frequency(frame["timestamp"])
    if frequency and inferred_frequency and frequency != inferred_frequency:
        raise ReturnSeriesError("return_frequency_mismatch")
    selected_frequency = frequency or inferred_frequency
    if selected_frequency is None:
        raise ReturnSeriesError("return_frequency_unknown")
    metadata.update(
        periods_per_year=FREQUENCIES[selected_frequency],
        frequency_label=selected_frequency,
        frequency_inferred=inferred_frequency,
        frequency_confirmed=frequency is not None,
    )
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        frame["equity"] = (1.0 + frame["ret"]).cumprod()
    if bool((~np.isfinite(frame["equity"]) | frame["equity"].le(0)).any()):
        raise ReturnSeriesError("return_compounding")
    companion = _benchmark_column(
        raw,
        timestamps,
        "returns",
        fund=frame["ret"],
        skip={stamp, *(name for name in (plain, gross, net) if name is not None)},
        warnings=warnings,
    )
    return IngestedSeries(
        frame=frame,
        source="returns",
        raw_rows=len(raw),
        duplicate_timestamps=duplicates,
        unparseable_rows=unparseable,
        non_monotonic=bool(non_monotonic),
        warnings=warnings,
        benchmark=companion,
        return_metadata=metadata,
    )


def frame_returns(frame: pd.DataFrame) -> pd.Series:
    """Use supplied period returns, including the first, before curve differences."""
    values = frame["ret"] if "ret" in frame else frame["equity"].pct_change()
    return pd.to_numeric(values, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()


def return_performance(frame: pd.DataFrame, ppy: float) -> dict[str, float | int]:
    """Performance of all supplied returns; duration is period count / frequency.

    The unit starting base participates in drawdown without acquiring a made-up
    date. CAGR's annualisation horizon is a declared-frequency convention; the
    caller decides whether the supplied history is long enough to report it.
    """
    returns = frame_returns(frame).to_numpy(dtype=float)
    if ppy <= 0 or not math.isfinite(ppy) or not len(returns):
        raise ValueError("a positive frequency and at least one return are required")
    curve = np.concatenate(([1.0], np.cumprod(1.0 + returns)))
    total = float(curve[-1] - 1.0)
    mean = float(returns.mean())
    deviation = float(returns.std(ddof=1)) if len(returns) > 1 else 0.0
    downside = float(np.sqrt(np.mean(np.minimum(returns, 0.0) ** 2)))
    try:
        cagr = math.expm1(math.log(float(curve[-1])) * ppy / len(returns))
    except (OverflowError, ValueError):
        cagr = math.nan
    return {
        "total_return": total,
        "cagr": cagr,
        "volatility": deviation * math.sqrt(ppy),
        "sharpe": mean / deviation * math.sqrt(ppy) if deviation > 0 else 0.0,
        "sortino": mean / downside * math.sqrt(ppy) if downside > 0 else 0.0,
        "max_drawdown": float((curve / np.maximum.accumulate(curve) - 1.0).min()),
        "win_rate": 0.0,
        "trade_count": 0,
    }
