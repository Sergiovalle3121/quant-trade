"""Six questions, one class, and a summary that says only what was measured.

The verdict is deliberately not a score. Each dimension answers one question
with PASS, WEAK, FAIL, NOT_MEASURED or NOT_APPLICABLE, the class A–D is a
fixed function of those answers, and every threshold is a named field that
is recorded in the JSON next to the values it was applied to. The summary is
assembled from fixed templates whose vocabulary never asserts that money was
or will be made; the guard in ``audit/guard.py`` enforces that.

Why these numbers: 0.95 for PSR and DSR is the repository's promotion bar
(``configs/selection/conservative_v2.yaml``); DSR 0.50 is the coin-flip line
against the best of N unskilled trials; 3x the reference cost is the "high"
level of the repository's cost sensitivity; an out-of-sample Sharpe of 0.5
and a one-unit in-sample/out-of-sample gap mirror ``min_oos_sharpe`` and a
one-Sharpe degradation.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from quant_trade.audit.costs import RecostRow
from quant_trade.audit.redflags import RedFlag
from quant_trade.audit.schema import Dimension, Verdict, measured, not_measured

Status = Literal["PASS", "WEAK", "FAIL", "NOT_MEASURED", "NOT_APPLICABLE"]
Locale = Literal["es", "en"]

STATISTICAL = "statistical_significance"
MULTIPLICITY = "multiplicity"
COSTS = "costs"
OUT_OF_SAMPLE = "out_of_sample"
DATA_QUALITY = "data_quality"
BENCHMARK = "benchmark"
DIMENSION_ORDER = (STATISTICAL, MULTIPLICITY, COSTS, OUT_OF_SAMPLE, DATA_QUALITY, BENCHMARK)


class Thresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    psr_pass: float = 0.95
    psr_weak: float = 0.80
    dsr_pass: float = 0.95
    dsr_weak: float = 0.50
    pbo_max: float = 0.50
    cost_pass_multiplier: float = 3.0
    oos_sharpe_pass: float = 0.5
    oos_gap_max: float = 1.0
    benchmark_drawdown_ratio_max: float = 1.0


DEFAULT_THRESHOLDS = Thresholds()


def assess_statistical(
    *,
    psr: float | None,
    bootstrap_p5_sharpe: float | None,
    observations: int,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    not_measured_reason: str | None = None,
) -> Dimension:
    inputs = {
        "psr": measured(psr) if psr is not None else not_measured("not computed"),
        "bootstrap_p5_sharpe_per_period": (
            measured(bootstrap_p5_sharpe)
            if bootstrap_p5_sharpe is not None
            else not_measured("not computed")
        ),
        "observations": measured(observations),
    }
    if not_measured_reason or psr is None:
        return Dimension(
            name=STATISTICAL,
            status="NOT_MEASURED",
            reasons=[not_measured_reason or "PSR not computed"],
            inputs=inputs,
        )
    p5_positive = bootstrap_p5_sharpe is not None and bootstrap_p5_sharpe > 0
    if psr >= thresholds.psr_pass and p5_positive:
        return Dimension(
            name=STATISTICAL,
            status="PASS",
            reasons=[f"PSR {psr:.3f} >= {thresholds.psr_pass}", "bootstrap p5 Sharpe > 0"],
            inputs=inputs,
        )
    if psr >= thresholds.psr_weak or p5_positive:
        reasons = [f"PSR {psr:.3f}"]
        reasons.append("bootstrap p5 Sharpe > 0" if p5_positive else "bootstrap p5 Sharpe <= 0")
        return Dimension(name=STATISTICAL, status="WEAK", reasons=reasons, inputs=inputs)
    return Dimension(
        name=STATISTICAL,
        status="FAIL",
        reasons=[f"PSR {psr:.3f} < {thresholds.psr_weak}", "bootstrap p5 Sharpe <= 0"],
        inputs=inputs,
    )


def assess_multiplicity(
    *,
    dsr_declared: float | None,
    declared_trials: int,
    pbo: float | None,
    statistical_status: Status,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Dimension:
    inputs = {
        "dsr_at_declared_trials": (
            measured(dsr_declared) if dsr_declared is not None else not_measured("not computed")
        ),
        "declared_trials": {"value": declared_trials, "evidence": "DECLARED", "note": ""},
        "pbo": measured(pbo) if pbo is not None else not_measured("no variants uploaded"),
    }
    if statistical_status == "NOT_MEASURED" or dsr_declared is None:
        return Dimension(
            name=MULTIPLICITY,
            status="NOT_MEASURED",
            reasons=["statistical significance not measured"],
            inputs=inputs,
        )
    pbo_bad = pbo is not None and pbo >= thresholds.pbo_max
    if dsr_declared < thresholds.dsr_weak or pbo_bad:
        reasons = [f"DSR({declared_trials}) {dsr_declared:.3f} < {thresholds.dsr_weak}"]
        if pbo_bad:
            reasons = [f"PBO {pbo:.2f} >= {thresholds.pbo_max}"] + (
                reasons if dsr_declared < thresholds.dsr_weak else []
            )
        return Dimension(name=MULTIPLICITY, status="FAIL", reasons=reasons, inputs=inputs)
    if dsr_declared >= thresholds.dsr_pass:
        reasons = [f"DSR({declared_trials}) {dsr_declared:.3f} >= {thresholds.dsr_pass}"]
        if pbo is not None:
            reasons.append(f"PBO {pbo:.2f} < {thresholds.pbo_max}")
        return Dimension(name=MULTIPLICITY, status="PASS", reasons=reasons, inputs=inputs)
    return Dimension(
        name=MULTIPLICITY,
        status="WEAK",
        reasons=[
            f"DSR({declared_trials}) {dsr_declared:.3f} in [{thresholds.dsr_weak}, "
            f"{thresholds.dsr_pass})"
        ],
        inputs=inputs,
    )


def _row_at(rows: list[RecostRow], multiplier: float) -> RecostRow | None:
    for row in rows:
        if row.multiplier == multiplier:
            return row
    return None


def assess_costs(
    *,
    rows: list[RecostRow] | None,
    reference_bps: float | None,
    reference_is_assumption: bool,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Dimension:
    if not rows:
        return Dimension(
            name=COSTS,
            status="NOT_MEASURED",
            reasons=["no trades uploaded; costs cannot be re-applied"],
            inputs={"reference_bps": not_measured("no trades uploaded")},
        )
    at_one = _row_at(rows, 1.0)
    at_pass = _row_at(rows, thresholds.cost_pass_multiplier)
    inputs: dict[str, Any] = {
        "reference_bps_per_side": {
            "value": reference_bps,
            "evidence": "DECLARED",
            "note": "assumed because the client declared zero cost"
            if reference_is_assumption
            else "declared by the client",
        },
        "net_pnl_at_1x": measured(at_one.net_pnl) if at_one else not_measured("no 1x row"),
        f"net_pnl_at_{thresholds.cost_pass_multiplier:g}x": (
            measured(at_pass.net_pnl) if at_pass else not_measured("no pass-multiplier row")
        ),
    }
    if at_one is None or at_pass is None:
        return Dimension(
            name=COSTS,
            status="NOT_MEASURED",
            reasons=["cost rows missing"],
            inputs=inputs,
        )
    if at_one.net_pnl <= 0:
        return Dimension(
            name=COSTS,
            status="FAIL",
            reasons=[f"net pnl at 1x the reference cost is {at_one.net_pnl:.2f} <= 0"],
            inputs=inputs,
        )
    if at_pass.net_pnl > 0:
        return Dimension(
            name=COSTS,
            status="PASS",
            reasons=[
                f"net pnl at {thresholds.cost_pass_multiplier:g}x the reference cost is "
                f"{at_pass.net_pnl:.2f} > 0"
            ],
            inputs=inputs,
        )
    return Dimension(
        name=COSTS,
        status="WEAK",
        reasons=[
            f"net pnl at 1x is {at_one.net_pnl:.2f} > 0 but at "
            f"{thresholds.cost_pass_multiplier:g}x is {at_pass.net_pnl:.2f} <= 0"
        ],
        inputs=inputs,
    )


def assess_out_of_sample(
    *,
    oos_sharpe: float | None,
    gap: float | None,
    not_measured_reason: str | None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Dimension:
    inputs = {
        "oos_sharpe_annualised": (
            measured(oos_sharpe) if oos_sharpe is not None else not_measured("not computed")
        ),
        "in_sample_minus_oos_sharpe": (
            measured(gap) if gap is not None else not_measured("not computed")
        ),
    }
    if not_measured_reason or oos_sharpe is None or gap is None:
        return Dimension(
            name=OUT_OF_SAMPLE,
            status="NOT_MEASURED",
            reasons=[not_measured_reason or "out-of-sample window not evaluated"],
            inputs=inputs,
        )
    if oos_sharpe <= 0:
        return Dimension(
            name=OUT_OF_SAMPLE,
            status="FAIL",
            reasons=[f"out-of-sample Sharpe {oos_sharpe:.2f} <= 0"],
            inputs=inputs,
        )
    if oos_sharpe >= thresholds.oos_sharpe_pass and gap <= thresholds.oos_gap_max:
        return Dimension(
            name=OUT_OF_SAMPLE,
            status="PASS",
            reasons=[
                f"out-of-sample Sharpe {oos_sharpe:.2f} >= {thresholds.oos_sharpe_pass}",
                f"in-sample minus out-of-sample gap {gap:.2f} <= {thresholds.oos_gap_max}",
            ],
            inputs=inputs,
        )
    return Dimension(
        name=OUT_OF_SAMPLE,
        status="WEAK",
        reasons=[f"out-of-sample Sharpe {oos_sharpe:.2f} > 0", f"gap {gap:.2f}"],
        inputs=inputs,
    )


def assess_data_quality(flags: list[RedFlag]) -> Dimension:
    fails = sorted({flag.code for flag in flags if flag.severity == "FAIL"})
    warns = sorted({flag.code for flag in flags if flag.severity == "WARN"})
    inputs = {
        "fail_flags": {"value": ",".join(fails), "evidence": "MEASURED", "note": ""},
        "warn_flags": {"value": ",".join(warns), "evidence": "MEASURED", "note": ""},
    }
    if fails:
        return Dimension(name=DATA_QUALITY, status="FAIL", reasons=fails, inputs=inputs)
    if warns:
        return Dimension(name=DATA_QUALITY, status="WEAK", reasons=warns, inputs=inputs)
    return Dimension(name=DATA_QUALITY, status="PASS", reasons=["no red flags"], inputs=inputs)


def assess_benchmark(
    *,
    applicable: bool,
    excess_return: float | None,
    drawdown_ratio: float | None,
    information_ratio: float | None,
    not_measured_reason: str | None,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Dimension:
    inputs = {
        "excess_return": (
            measured(excess_return) if excess_return is not None else not_measured("n/a")
        ),
        "drawdown_ratio": (
            measured(drawdown_ratio) if drawdown_ratio is not None else not_measured("n/a")
        ),
        "information_ratio": (
            measured(information_ratio) if information_ratio is not None else not_measured("n/a")
        ),
    }
    if not applicable:
        return Dimension(
            name=BENCHMARK,
            status="NOT_APPLICABLE",
            reasons=["client declared no applicable benchmark"],
            inputs=inputs,
        )
    if not_measured_reason or excess_return is None:
        return Dimension(
            name=BENCHMARK,
            status="NOT_MEASURED",
            reasons=[not_measured_reason or "no benchmark uploaded"],
            inputs=inputs,
        )
    if excess_return <= 0:
        return Dimension(
            name=BENCHMARK,
            status="FAIL",
            reasons=[f"excess return {excess_return:.2%} <= 0"],
            inputs=inputs,
        )
    dd_ok = drawdown_ratio is not None and drawdown_ratio <= thresholds.benchmark_drawdown_ratio_max
    ir_ok = information_ratio is not None and information_ratio > 0
    if dd_ok and ir_ok:
        return Dimension(
            name=BENCHMARK,
            status="PASS",
            reasons=[
                f"excess return {excess_return:.2%} > 0",
                f"drawdown ratio {drawdown_ratio:.2f} <= {thresholds.benchmark_drawdown_ratio_max}",
                f"information ratio {information_ratio:.2f} > 0",
            ],
            inputs=inputs,
        )
    return Dimension(
        name=BENCHMARK,
        status="WEAK",
        reasons=[f"excess return {excess_return:.2%} > 0"]
        + ([] if dd_ok else ["drawdown deeper than the benchmark"])
        + ([] if ir_ok else ["information ratio <= 0"]),
        inputs=inputs,
    )


def overall_class(dimensions: list[Dimension]) -> Literal["A", "B", "C", "D"]:
    status = {dimension.name: dimension.status for dimension in dimensions}
    fails = sum(1 for value in status.values() if value == "FAIL")
    if status.get(DATA_QUALITY) == "FAIL" or status.get(STATISTICAL) == "FAIL" or fails >= 2:
        return "D"
    if fails == 1 or status.get(STATISTICAL) == "WEAK" or status.get(MULTIPLICITY) == "WEAK":
        return "C"
    if status.get(STATISTICAL) != "PASS" or status.get(MULTIPLICITY) != "PASS":
        # NOT_MEASURED statistics with no FAIL flag cannot happen (too few
        # observations is a FAIL flag), but the rule is stated for completeness.
        return "C"
    rest = (status.get(COSTS), status.get(OUT_OF_SAMPLE), status.get(BENCHMARK))
    if (
        all(value in ("PASS", "NOT_APPLICABLE") for value in rest)
        and status.get(DATA_QUALITY) == "PASS"
    ):
        return "A"
    return "B"


_TEXT: dict[str, dict[str, str]] = {
    "es": {
        "A": (
            "Clase A: no encontramos evidencia de sobreajuste con lo aportado. "
            "Esto no es una predicción de resultados futuros."
        ),
        "B": (
            "Clase B: la estadística aguanta, pero faltan piezas (costes, fuera de muestra o "
            "benchmark) para una conclusión completa."
        ),
        "C": (
            "Clase C: hay una debilidad importante; no confiaríamos en este backtest sin "
            "resolverla."
        ),
        "D": (
            "Clase D: el backtest no supera la auditoría; los números de cabecera no se "
            "pueden tomar tal cual."
        ),
        f"{STATISTICAL}.PASS": "El Sharpe es estadísticamente distinguible de cero.",
        f"{STATISTICAL}.WEAK": (
            "El Sharpe no es concluyente: el intervalo bootstrap se acerca a cero."
        ),
        f"{STATISTICAL}.FAIL": "El Sharpe observado no se distingue de cero.",
        f"{STATISTICAL}.NOT_MEASURED": "Significación no medida: {reason}.",
        f"{MULTIPLICITY}.PASS": (
            "Con {trials} intento(s) declarado(s), el resultado sigue por encima de lo que "
            "produciría el mejor intento sin habilidad."
        ),
        f"{MULTIPLICITY}.WEAK": (
            "Con {trials} intento(s) declarado(s), el resultado es compatible con haber elegido "
            "el mejor de varios intentos."
        ),
        f"{MULTIPLICITY}.FAIL": (
            "Con {trials} intento(s) declarado(s), el resultado no supera lo que produciría el "
            "mejor de esos intentos sin habilidad."
        ),
        f"{MULTIPLICITY}.NOT_MEASURED": "Multiplicidad no medida: {reason}.",
        f"{COSTS}.PASS": (
            "Neto de 3x el coste de referencia, el resultado de las operaciones sigue positivo."
        ),
        f"{COSTS}.WEAK": (
            "Las operaciones sobreviven al coste de referencia pero no a 3x ese coste."
        ),
        f"{COSTS}.FAIL": "Con el coste de referencia, las operaciones pierden dinero en neto.",
        f"{COSTS}.NOT_MEASURED": "Costes no medidos: {reason}.",
        f"{OUT_OF_SAMPLE}.PASS": (
            "Fuera de muestra el Sharpe se mantiene y la degradación frente a la muestra es "
            "pequeña."
        ),
        f"{OUT_OF_SAMPLE}.WEAK": "Fuera de muestra el Sharpe es positivo pero se degrada.",
        f"{OUT_OF_SAMPLE}.FAIL": "Fuera de muestra el Sharpe es negativo.",
        f"{OUT_OF_SAMPLE}.NOT_MEASURED": "Fuera de muestra no medido: {reason}.",
        f"{DATA_QUALITY}.PASS": "Sin banderas rojas en los datos.",
        f"{DATA_QUALITY}.WEAK": "Banderas de aviso en los datos: {codes}.",
        f"{DATA_QUALITY}.FAIL": "Banderas graves en los datos: {codes}.",
        f"{BENCHMARK}.PASS": "Supera al benchmark aportado con un drawdown no peor.",
        f"{BENCHMARK}.WEAK": "Supera al benchmark aportado en retorno, pero no en riesgo.",
        f"{BENCHMARK}.FAIL": "No supera al benchmark aportado.",
        f"{BENCHMARK}.NOT_MEASURED": "Benchmark no medido: {reason}.",
        f"{BENCHMARK}.NOT_APPLICABLE": "Benchmark declarado como no aplicable.",
    },
    "en": {
        "A": (
            "Class A: no evidence of overfitting found in what was supplied. "
            "This is not a prediction of future results."
        ),
        "B": (
            "Class B: the statistics hold, but pieces are missing (costs, out-of-sample or "
            "benchmark) for a complete conclusion."
        ),
        "C": (
            "Class C: there is a material weakness; we would not rely on this backtest "
            "until it is resolved."
        ),
        "D": (
            "Class D: the backtest does not pass the audit; the headline numbers cannot be "
            "taken as they stand."
        ),
        f"{STATISTICAL}.PASS": "The Sharpe ratio is statistically distinguishable from zero.",
        f"{STATISTICAL}.WEAK": (
            "The Sharpe ratio is inconclusive: the bootstrap interval nears zero."
        ),
        f"{STATISTICAL}.FAIL": "The observed Sharpe ratio is not distinguishable from zero.",
        f"{STATISTICAL}.NOT_MEASURED": "Significance not measured: {reason}.",
        f"{MULTIPLICITY}.PASS": (
            "With {trials} declared trial(s), the result stays above what the best unskilled "
            "trial would produce."
        ),
        f"{MULTIPLICITY}.WEAK": (
            "With {trials} declared trial(s), the result is consistent with having picked the "
            "best of several attempts."
        ),
        f"{MULTIPLICITY}.FAIL": (
            "With {trials} declared trial(s), the result does not exceed what the best of "
            "those trials would produce without skill."
        ),
        f"{MULTIPLICITY}.NOT_MEASURED": "Multiplicity not measured: {reason}.",
        f"{COSTS}.PASS": "Net of 3x the reference cost, the trade ledger stays positive.",
        f"{COSTS}.WEAK": "The trades survive the reference cost but not 3x that cost.",
        f"{COSTS}.FAIL": "At the reference cost, the trades lose money net.",
        f"{COSTS}.NOT_MEASURED": "Costs not measured: {reason}.",
        f"{OUT_OF_SAMPLE}.PASS": (
            "Out of sample the Sharpe ratio holds and the degradation versus in-sample is small."
        ),
        f"{OUT_OF_SAMPLE}.WEAK": "Out of sample the Sharpe ratio is positive but degraded.",
        f"{OUT_OF_SAMPLE}.FAIL": "Out of sample the Sharpe ratio is negative.",
        f"{OUT_OF_SAMPLE}.NOT_MEASURED": "Out of sample not measured: {reason}.",
        f"{DATA_QUALITY}.PASS": "No red flags in the data.",
        f"{DATA_QUALITY}.WEAK": "Warning flags in the data: {codes}.",
        f"{DATA_QUALITY}.FAIL": "Serious flags in the data: {codes}.",
        f"{BENCHMARK}.PASS": "Beats the supplied benchmark with a drawdown no worse.",
        f"{BENCHMARK}.WEAK": "Beats the supplied benchmark on return, not on risk.",
        f"{BENCHMARK}.FAIL": "Does not beat the supplied benchmark.",
        f"{BENCHMARK}.NOT_MEASURED": "Benchmark not measured: {reason}.",
        f"{BENCHMARK}.NOT_APPLICABLE": "Benchmark declared not applicable.",
    },
}


def summary(
    dimensions: list[Dimension],
    overall: str,
    *,
    locale: Locale = "es",
    declared_trials: int = 1,
) -> str:
    """Plain-language summary from fixed templates; never a promise."""
    text = _TEXT[locale]
    lines = [text[overall]]
    by_name = {dimension.name: dimension for dimension in dimensions}
    for name in DIMENSION_ORDER:
        dimension = by_name.get(name)
        if dimension is None:
            continue
        template = text.get(f"{name}.{dimension.status}", f"{name}: {dimension.status}.")
        reason = dimension.reasons[0] if dimension.reasons else ""
        lines.append(
            template.format(
                reason=reason,
                trials=declared_trials,
                codes=", ".join(dimension.reasons) if dimension.reasons else "",
            )
        )
    return " ".join(lines)


def build_verdict(
    dimensions: list[Dimension],
    *,
    locale: Locale,
    declared_trials: int,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Verdict:
    overall = overall_class(dimensions)
    return Verdict(
        overall=overall,
        summary=summary(dimensions, overall, locale=locale, declared_trials=declared_trials),
        thresholds=thresholds.model_dump(),
        dimensions=dimensions,
    )


__all__ = [
    "BENCHMARK",
    "COSTS",
    "DATA_QUALITY",
    "DEFAULT_THRESHOLDS",
    "DIMENSION_ORDER",
    "MULTIPLICITY",
    "OUT_OF_SAMPLE",
    "STATISTICAL",
    "Thresholds",
    "assess_benchmark",
    "assess_costs",
    "assess_data_quality",
    "assess_multiplicity",
    "assess_out_of_sample",
    "assess_statistical",
    "build_verdict",
    "overall_class",
    "summary",
]
