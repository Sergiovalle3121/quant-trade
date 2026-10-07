"""Costs and benchmark comparisons of supplied period returns, including the first.

No price, trade, cash-rate or intra-period observation is reconstructed. The
frequency and gross/net interpretation are declarations; arithmetic on those
inputs is measured, with its assumptions retained alongside the result.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from quant_trade.audit.return_series import FREQUENCIES, infer_return_frequency, return_performance
from quant_trade.audit.schema import IngestedSeries, declared, measured, not_measured

REASONS = {
    "period_path": {
        "en": "period returns do not establish an opening date or a within-period path",
        "es": (
            "los rendimientos por periodo no establecen una fecha inicial "
            "ni la trayectoria dentro del periodo"
        ),
        "pt": (
            "os retornos por período não estabelecem uma data inicial "
            "nem a trajetória dentro do período"
        ),
    },
    "period_curve": {
        "en": "compounded period returns on supplied dates; the opening unit has no assigned date",
        "es": (
            "rendimientos compuestos en las fechas aportadas; "
            "la unidad inicial no tiene fecha asignada"
        ),
        "pt": "retornos compostos nas datas fornecidas; a unidade inicial não tem data atribuída",
    },
    "missing_cost": {
        "en": "both gross and net period returns are required for cost stress",
        "es": "la prueba de costos requiere rendimientos brutos y netos por periodo",
        "pt": "o teste de custos requer retornos brutos e líquidos por período",
    },
    "negative_cost": {
        "en": "declared net return exceeds gross return; the cost difference is inconsistent",
        "es": "el neto supera al bruto; la diferencia de costo declarada es inconsistente",
        "pt": "o líquido supera o bruto; a diferença de custo declarada é inconsistente",
    },
    "invalid_returns": {
        "en": "the period returns or their dates are not usable for this comparison",
        "es": "los rendimientos por periodo o sus fechas no permiten esta comparación",
        "pt": "os retornos por período ou suas datas não permitem esta comparação",
    },
    "stress_loss": {
        "en": "cost stress exceeds a complete period loss; compounded results are not measured",
        "es": "los costos superan la pérdida completa del periodo; no se mide el total compuesto",
        "pt": "os custos superam a perda completa do período; não se mede o resultado composto",
    },
    "numeric_range": {
        "en": "the compounded period result exceeds the supported numeric range",
        "es": "el resultado compuesto por periodos supera el rango numérico admitido",
        "pt": "o resultado composto por períodos excede o intervalo numérico aceito",
    },
    "no_benchmark": {
        "en": "no benchmark uploaded",
        "es": "no se subió un benchmark",
        "pt": "nenhum benchmark foi enviado",
    },
    "frequency_mismatch": {
        "en": "strategy and benchmark frequencies differ; no forced alignment is applied",
        "es": "estrategia y benchmark tienen frecuencias distintas; no se fuerza la alineación",
        "pt": "as frequências da estratégia e do benchmark diferem; o alinhamento não é forçado",
    },
    "frequency_unknown": {
        "en": "strategy or benchmark frequency cannot be established from the supplied dates",
        "es": "las fechas no permiten establecer la frecuencia de la estrategia o del benchmark",
        "pt": "não é possível estabelecer a frequência da estratégia ou do benchmark pelas datas",
    },
    "overlap": {
        "en": "the benchmark has insufficient matching dates for a period return comparison",
        "es": "faltan fechas coincidentes del benchmark para comparar rendimientos por periodo",
        "pt": "faltam datas coincidentes do benchmark para comparar retornos por período",
    },
    "short": {
        "en": "fewer than three returns",
        "es": "menos de tres rendimientos",
        "pt": "menos de três retornos",
    },
    "variance": {
        "en": "zero variance",
        "es": "varianza nula",
        "pt": "variância nula",
    },
    "no_drawdown": {
        "en": "benchmark has no drawdown",
        "es": "el benchmark no tiene caída desde máximos",
        "pt": "o benchmark não tem queda desde máximas",
    },
    "jensen": {
        "en": "dated period-start cash-rate evidence was not supplied for this return table",
        "es": "no se aportaron tasas de efectivo fechadas al inicio de cada periodo de esta tabla",
        "pt": "não foram fornecidas taxas de caixa datadas no início de cada período desta tabela",
    },
    "benchmark_source": {
        "en": "uploaded benchmark file",
        "es": "archivo de benchmark aportado",
        "pt": "arquivo de benchmark fornecido",
    },
}


def _reason(code: str) -> str:
    return REASONS[code]["en"]


def _ratio(returns: pd.Series, ppy: float) -> dict[str, Any]:
    if len(returns) < 3:
        return not_measured(_reason("short"))
    deviation = float(returns.std(ddof=1))
    if deviation <= 0 or float(returns.max() - returns.min()) == 0:
        return not_measured(_reason("variance"))
    value = float(returns.mean()) / deviation * math.sqrt(ppy)
    return measured(value) if math.isfinite(value) else not_measured(_reason("numeric_range"))


def period_costs(equity: IngestedSeries, ppy: float) -> dict[str, Any]:
    """Stress the declared gross-minus-net difference, without monetary P&L."""
    section: dict[str, Any] = {
        "kind": "period_returns",
        "status": "NOT_MEASURED",
        "rows": [],
        "reference_basis": declared("gross_return - net_return"),
        "periods_per_year": declared(ppy),
    }
    frame = equity.frame
    if not {"gross_ret", "net_ret"} <= set(frame):
        return {**section, "reason": _reason("missing_cost")}
    gross = pd.to_numeric(frame["gross_ret"], errors="coerce")
    net = pd.to_numeric(frame["net_ret"], errors="coerce")
    if (
        len(frame) == 0
        or not math.isfinite(ppy)
        or ppy <= 0
        or not bool(np.isfinite(gross).all() and np.isfinite(net).all())
        or bool((gross <= -1).any() or (net <= -1).any())
    ):
        return {**section, "reason": _reason("invalid_returns")}
    if bool((gross < net).any()):
        return {**section, "reason": _reason("negative_cost")}
    rows = []
    for multiplier in (1, 2, 3):
        stressed = gross - multiplier * (gross - net)
        reason = _reason("stress_loss") if bool((stressed < -1).any()) else ""
        with np.errstate(over="ignore", invalid="ignore"):
            total = float((1.0 + stressed).prod()) if not reason else math.nan
        if not reason and not math.isfinite(total):
            reason = _reason("numeric_range")
        rows.append(
            {
                "multiplier": declared(multiplier),
                "total_return": not_measured(reason) if reason else measured(total - 1),
                "sharpe_annualised": not_measured(reason) if reason else _ratio(stressed, ppy),
            }
        )
    return {**section, "status": "MEASURED", "observations": measured(len(frame)), "rows": rows}


def _frequency(series: IngestedSeries) -> str | None:
    frequency = series.return_metadata.get("frequency_label")
    timestamps = series.frame["timestamp"]
    if (
        not series.return_metadata
        and "ret" in series.frame
        and len(series.frame)
        and pd.isna(series.frame["ret"].iloc[0])
    ):
        # A legacy opening balance is not a supplied return-period date.
        timestamps = timestamps.iloc[1:]
    return str(frequency) if frequency in FREQUENCIES else infer_return_frequency(timestamps)


def _points(series: IngestedSeries) -> pd.DataFrame:
    frame = series.frame
    returns = frame["ret"] if "ret" in frame else frame["equity"].pct_change()
    points = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(frame["timestamp"], utc=True, errors="coerce"),
            "ret": pd.to_numeric(returns, errors="coerce"),
        }
    )
    # Legacy curve readers (including their return-table adapter) carry an
    # opening balance without a return. Explicit period tables never do.
    if not series.return_metadata and len(points) and pd.isna(points["ret"].iloc[0]):
        points = points.iloc[1:]
    if (
        points.isna().any().any()
        or points["timestamp"].duplicated().any()
        or not bool(np.isfinite(points["ret"]).all())
        or bool((points["ret"] <= -1).any())
    ):
        raise ValueError(_reason("invalid_returns"))
    return points.sort_values("timestamp")


def period_benchmark(
    strategy: IngestedSeries,
    benchmark: IngestedSeries | None,
    ppy: float,
    *,
    min_overlap: float = 0.90,
) -> tuple[dict[str, Any], dict[str, float | None], str | None]:
    """Exact-date comparisons with a frequency check before any join."""
    values: dict[str, float | None] = {
        "excess_return": None,
        "drawdown_ratio": None,
        "information_ratio": None,
    }
    section: dict[str, Any] = {"status": "NOT_MEASURED"}

    def absent(code: str) -> tuple[dict[str, Any], dict[str, float | None], str]:
        reason = _reason(code)
        return {**section, "reason": reason}, values, reason

    if benchmark is None:
        return absent("no_benchmark")
    section["source"] = declared(_reason("benchmark_source"))
    try:
        s_frequency, b_frequency = _frequency(strategy), _frequency(benchmark)
    except (KeyError, TypeError, ValueError):
        return absent("invalid_returns")
    section["strategy_frequency"] = (
        declared(s_frequency) if s_frequency else not_measured(_reason("frequency_unknown"))
    )
    section["benchmark_frequency"] = (
        declared(b_frequency) if b_frequency else not_measured(_reason("frequency_unknown"))
    )
    if not s_frequency or not b_frequency:
        return absent("frequency_unknown")
    if s_frequency != b_frequency:
        return absent("frequency_mismatch")
    if (
        not math.isfinite(ppy)
        or ppy <= 0
        or (strategy.return_metadata and ppy != FREQUENCIES[s_frequency])
    ):
        return absent("frequency_mismatch")
    try:
        s_points, b_points = _points(strategy), _points(benchmark)
    except (KeyError, TypeError, ValueError):
        return absent("invalid_returns")
    joined = s_points.merge(b_points, on="timestamp", suffixes=("_s", "_b"))
    overlap = len(joined) / max(len(s_points), 1)
    section["overlap_share"] = measured(overlap)
    if overlap < min_overlap or len(joined) < 3:
        return absent("overlap")
    s_ret, b_ret = joined["ret_s"], joined["ret_b"]
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        s_metrics = return_performance(joined.rename(columns={"ret_s": "ret"}), ppy)
        b_metrics = return_performance(joined.rename(columns={"ret_b": "ret"}), ppy)
    if not all(
        math.isfinite(float(metrics[key]))
        for metrics in (s_metrics, b_metrics)
        for key in ("total_return", "max_drawdown")
    ):
        return absent("numeric_range")
    excess = float(s_metrics["total_return"] - b_metrics["total_return"])
    s_dd, b_dd = float(s_metrics["max_drawdown"]), float(b_metrics["max_drawdown"])
    ratio = s_dd / b_dd if b_dd < 0 else None
    difference = s_ret - b_ret
    information = _ratio(difference, ppy)
    tracking_error = float(difference.std(ddof=1)) * math.sqrt(ppy)
    values = {
        "excess_return": excess,
        "drawdown_ratio": ratio,
        "information_ratio": information["value"],
    }
    section.update(
        {
            "status": "MEASURED",
            "observations": measured(len(joined)),
            "periods_per_year": declared(ppy),
            "strategy_total_return": measured(s_metrics["total_return"]),
            "benchmark_total_return": measured(b_metrics["total_return"]),
            "excess_return": measured(excess),
            "strategy_sharpe": _ratio(s_ret, ppy),
            "benchmark_sharpe": _ratio(b_ret, ppy),
            "tracking_error": measured(tracking_error),
            "information_ratio": information,
            "strategy_max_drawdown": measured(s_dd),
            "benchmark_max_drawdown": measured(b_dd),
            "drawdown_ratio": measured(ratio)
            if ratio is not None
            else not_measured(_reason("no_drawdown")),
            "jensen": {"status": "NOT_MEASURED", "reason": _reason("jensen")},
        }
    )
    return section, values, None
