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

from quant_trade.audit.costs import RecostRow, reference_note
from quant_trade.audit.redflags import RedFlag, flag_title
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


Reason = tuple[str, str]


def _same(text: str) -> Reason:
    """A reason made only of numbers and symbols reads the same in both languages."""
    return (text, text)


#: The engine's fixed not-measured reasons, in Spanish.
NOT_MEASURED_ES: dict[str, str] = {
    "fewer than three returns": "menos de tres retornos",
    "zero variance": "varianza cero",
    "PSR not computed": "PSR no calculado",
    "statistical significance not measured": "significación estadística no medida",
    "no trades uploaded; costs cannot be re-applied": (
        "no se subieron operaciones; no se pueden volver a aplicar los costes"
    ),
    "cost rows missing": "faltan filas de costes",
    "no out-of-sample start declared": "no se declaró un inicio fuera de muestra",
    "declared out-of-sample start lies outside the uploaded series": (
        "el inicio fuera de muestra declarado cae fuera de la serie subida"
    ),
    "out-of-sample window not evaluated": "tramo fuera de muestra no evaluado",
    "no benchmark uploaded": "no se subió un benchmark",
    "client declared no applicable benchmark": "el cliente declaró que no aplica benchmark",
    "no red flags": "sin banderas rojas",
}


def _reason(text: str) -> Reason:
    """An engine reason with its Spanish twin (itself when there is none)."""
    if text in NOT_MEASURED_ES:
        return (text, NOT_MEASURED_ES[text])
    if text.startswith("a side has fewer than"):
        return (text, "uno de los tramos tiene menos retornos de los necesarios: " + text)
    if text.startswith("benchmark overlaps only"):
        return (text, "el benchmark cubre muy pocas fechas de la estrategia: " + text)
    if text.startswith("split failed"):
        return (text, "no se pudo dividir la serie: " + text)
    return (text, text)


def _dimension(
    name: str, status: Status, reasons: list[Reason], inputs: dict[str, Any]
) -> Dimension:
    return Dimension(
        name=name,
        status=status,
        reasons=[english for english, _ in reasons],
        reasons_es=[spanish for _, spanish in reasons],
        inputs=inputs,
    )


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
        reason = _reason(not_measured_reason or "PSR not computed")
        return _dimension(STATISTICAL, "NOT_MEASURED", [reason], inputs)
    p5_positive = bootstrap_p5_sharpe is not None and bootstrap_p5_sharpe > 0
    p5: Reason = (
        ("bootstrap p5 Sharpe > 0", "Sharpe p5 del bootstrap > 0")
        if p5_positive
        else ("bootstrap p5 Sharpe <= 0", "Sharpe p5 del bootstrap <= 0")
    )
    if psr >= thresholds.psr_pass and p5_positive:
        return _dimension(
            STATISTICAL, "PASS", [_same(f"PSR {psr:.3f} >= {thresholds.psr_pass}"), p5], inputs
        )
    if psr >= thresholds.psr_weak or p5_positive:
        return _dimension(STATISTICAL, "WEAK", [_same(f"PSR {psr:.3f}"), p5], inputs)
    return _dimension(
        STATISTICAL, "FAIL", [_same(f"PSR {psr:.3f} < {thresholds.psr_weak}"), p5], inputs
    )


TRIAL_SOURCE: dict[str, dict[str, str]] = {
    "es": {
        "DECLARED": "declarados",
        "MEASURED": "contados en los archivos",
        "NOT_MEASURED": "sin declarar (el caso más favorable)",
    },
    "en": {
        "DECLARED": "declared",
        "MEASURED": "counted in the files",
        "NOT_MEASURED": "not declared (the most favourable case)",
    },
}


def trials_phrase(trials: int, evidence: str, locale: str) -> str:
    """``120 intentos declarados`` / ``1 declared trial``: the count with its
    source, singular or plural as the number asks."""
    one = trials == 1
    if locale == "es":
        noun = "intento" if one else "intentos"
        source = {
            "DECLARED": "declarado" if one else "declarados",
            "MEASURED": "contado en los archivos" if one else "contados en los archivos",
        }.get(evidence, TRIAL_SOURCE["es"]["NOT_MEASURED"])
        return f"{trials} {noun} {source}"
    noun = "trial" if one else "trials"
    if evidence == "DECLARED":
        return f"{trials} declared {noun}"
    source = TRIAL_SOURCE["en"].get(evidence, "declared")
    return f"{trials} {noun} {source}"


def assess_multiplicity(
    *,
    dsr: float | None,
    trials: int,
    pbo: float | None,
    statistical_status: Status,
    trials_evidence: str = "DECLARED",
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Dimension:
    """Deflated Sharpe at ``trials`` (the larger of the declared count and
    what the files show) and, when variants were uploaded, the PBO."""
    inputs = {
        "dsr_at_trials_used": (measured(dsr) if dsr is not None else not_measured("not computed")),
        "trials_used": {"value": trials, "evidence": trials_evidence, "note": ""},
        "pbo": measured(pbo) if pbo is not None else not_measured("no variants uploaded"),
    }
    if statistical_status == "NOT_MEASURED" or dsr is None:
        return _dimension(
            MULTIPLICITY,
            "NOT_MEASURED",
            [_reason("statistical significance not measured")],
            inputs,
        )

    def dsr_reason(relation: str, relation_es: str | None = None) -> Reason:
        return (
            f"DSR {dsr:.3f} {relation} with {trials_phrase(trials, trials_evidence, 'en')}",
            f"DSR {dsr:.3f} {relation_es or relation} con "
            f"{trials_phrase(trials, trials_evidence, 'es')}",
        )

    pbo_bad = pbo is not None and pbo >= thresholds.pbo_max
    if dsr < thresholds.dsr_weak or pbo_bad:
        reasons: list[Reason] = []
        if pbo_bad:
            reasons.append(_same(f"PBO {pbo:.2f} >= {thresholds.pbo_max}"))
        if dsr < thresholds.dsr_weak or not pbo_bad:
            reasons.append(dsr_reason(f"< {thresholds.dsr_weak}"))
        return _dimension(MULTIPLICITY, "FAIL", reasons, inputs)
    if dsr >= thresholds.dsr_pass:
        reasons = [dsr_reason(f">= {thresholds.dsr_pass}")]
        if pbo is not None:
            reasons.append(_same(f"PBO {pbo:.2f} < {thresholds.pbo_max}"))
        return _dimension(MULTIPLICITY, "PASS", reasons, inputs)
    return _dimension(
        MULTIPLICITY,
        "WEAK",
        [
            dsr_reason(
                f"between {thresholds.dsr_weak} and {thresholds.dsr_pass}",
                f"entre {thresholds.dsr_weak} y {thresholds.dsr_pass}",
            )
        ],
        inputs,
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
    fees_reported: bool = False,
    real_fills: bool = False,
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
) -> Dimension:
    if not rows:
        return _dimension(
            COSTS,
            "NOT_MEASURED",
            [_reason("no trades uploaded; costs cannot be re-applied")],
            {"reference_bps": not_measured("no trades uploaded")},
        )
    at_one = _row_at(rows, 1.0)
    at_pass = _row_at(rows, thresholds.cost_pass_multiplier)
    multiple = f"{thresholds.cost_pass_multiplier:g}x"
    inputs: dict[str, Any] = {
        "reference_bps_per_side": {
            "value": reference_bps,
            "evidence": "DECLARED",
            "note": reference_note(reference_is_assumption, fees_reported, real_fills),
        },
        "net_pnl_at_1x": measured(at_one.net_pnl) if at_one else not_measured("no 1x row"),
        f"net_pnl_at_{multiple}": (
            measured(at_pass.net_pnl) if at_pass else not_measured("no pass-multiplier row")
        ),
    }
    if at_one is None or at_pass is None:
        return _dimension(COSTS, "NOT_MEASURED", [_reason("cost rows missing")], inputs)
    if at_one.net_pnl <= 0:
        return _dimension(
            COSTS,
            "FAIL",
            [
                (
                    f"net pnl at 1x the reference cost is {at_one.net_pnl:.2f} <= 0",
                    f"el resultado neto a 1x el coste de referencia es {at_one.net_pnl:.2f} <= 0",
                )
            ],
            inputs,
        )
    if at_pass.net_pnl > 0:
        return _dimension(
            COSTS,
            "PASS",
            [
                (
                    f"net pnl at {multiple} the reference cost is {at_pass.net_pnl:.2f} > 0",
                    f"el resultado neto a {multiple} el coste de referencia es "
                    f"{at_pass.net_pnl:.2f} > 0",
                )
            ],
            inputs,
        )
    return _dimension(
        COSTS,
        "WEAK",
        [
            (
                f"net pnl at 1x is {at_one.net_pnl:.2f} > 0 but at {multiple} is "
                f"{at_pass.net_pnl:.2f} <= 0",
                f"el resultado neto a 1x es {at_one.net_pnl:.2f} > 0 pero a {multiple} es "
                f"{at_pass.net_pnl:.2f} <= 0",
            )
        ],
        inputs,
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
        reason = _reason(not_measured_reason or "out-of-sample window not evaluated")
        return _dimension(OUT_OF_SAMPLE, "NOT_MEASURED", [reason], inputs)
    oos: Reason = (
        f"out-of-sample Sharpe {oos_sharpe:.2f}",
        f"Sharpe fuera de muestra {oos_sharpe:.2f}",
    )
    if oos_sharpe <= 0:
        return _dimension(OUT_OF_SAMPLE, "FAIL", [(oos[0] + " <= 0", oos[1] + " <= 0")], inputs)
    if oos_sharpe >= thresholds.oos_sharpe_pass and gap <= thresholds.oos_gap_max:
        return _dimension(
            OUT_OF_SAMPLE,
            "PASS",
            [
                (
                    f"{oos[0]} >= {thresholds.oos_sharpe_pass}",
                    f"{oos[1]} >= {thresholds.oos_sharpe_pass}",
                ),
                (
                    f"in-sample minus out-of-sample gap {gap:.2f} <= {thresholds.oos_gap_max}",
                    f"diferencia entre dentro y fuera de muestra {gap:.2f} <= "
                    f"{thresholds.oos_gap_max}",
                ),
            ],
            inputs,
        )
    return _dimension(
        OUT_OF_SAMPLE,
        "WEAK",
        [(oos[0] + " > 0", oos[1] + " > 0"), (f"gap {gap:.2f}", f"diferencia {gap:.2f}")],
        inputs,
    )


def assess_data_quality(flags: list[RedFlag]) -> Dimension:
    """Flag codes are the English reasons; their Spanish names the Spanish ones."""
    fails = sorted({flag.code for flag in flags if flag.severity == "FAIL"})
    warns = sorted({flag.code for flag in flags if flag.severity == "WARN"})
    inputs = {
        "fail_flags": {"value": ",".join(fails), "evidence": "MEASURED", "note": ""},
        "warn_flags": {"value": ",".join(warns), "evidence": "MEASURED", "note": ""},
    }

    def named(codes: list[str]) -> list[Reason]:
        return [(flag_title(code, "en"), flag_title(code, "es")) for code in codes]

    if fails:
        return _dimension(DATA_QUALITY, "FAIL", named(fails), inputs)
    if warns:
        return _dimension(DATA_QUALITY, "WEAK", named(warns), inputs)
    return _dimension(DATA_QUALITY, "PASS", [_reason("no red flags")], inputs)


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
        return _dimension(
            BENCHMARK,
            "NOT_APPLICABLE",
            [_reason("client declared no applicable benchmark")],
            inputs,
        )
    if not_measured_reason or excess_return is None:
        reason = _reason(not_measured_reason or "no benchmark uploaded")
        return _dimension(BENCHMARK, "NOT_MEASURED", [reason], inputs)
    excess: Reason = (
        f"excess return {excess_return:.2%}",
        f"retorno en exceso {excess_return:.2%}",
    )
    if excess_return <= 0:
        return _dimension(BENCHMARK, "FAIL", [(excess[0] + " <= 0", excess[1] + " <= 0")], inputs)
    dd_ok = drawdown_ratio is not None and drawdown_ratio <= thresholds.benchmark_drawdown_ratio_max
    ir_ok = information_ratio is not None and information_ratio > 0
    if dd_ok and ir_ok:
        return _dimension(
            BENCHMARK,
            "PASS",
            [
                (excess[0] + " > 0", excess[1] + " > 0"),
                (
                    f"drawdown ratio {drawdown_ratio:.2f} <= "
                    f"{thresholds.benchmark_drawdown_ratio_max}",
                    f"ratio de drawdown {drawdown_ratio:.2f} <= "
                    f"{thresholds.benchmark_drawdown_ratio_max}",
                ),
                (
                    f"information ratio {information_ratio:.2f} > 0",
                    f"information ratio {information_ratio:.2f} > 0",
                ),
            ],
            inputs,
        )
    reasons: list[Reason] = [(excess[0] + " > 0", excess[1] + " > 0")]
    if not dd_ok:
        reasons.append(
            ("drawdown deeper than the benchmark", "drawdown más profundo que el del benchmark")
        )
    if not ir_ok:
        reasons.append(("information ratio <= 0", "information ratio <= 0"))
    return _dimension(BENCHMARK, "WEAK", reasons, inputs)


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
        # The same classes when the upload is a real or demo account history.
        "C.account": (
            "Clase C: hay una debilidad importante; no confiaríamos en este historial de "
            "cuenta sin resolverla."
        ),
        "D.account": (
            "Clase D: el historial de cuenta no supera la auditoría; los números de cabecera "
            "no se pueden tomar tal cual."
        ),
        f"{STATISTICAL}.PASS": "El Sharpe es estadísticamente distinguible de cero.",
        f"{STATISTICAL}.WEAK": (
            "El Sharpe no es concluyente: el intervalo bootstrap se acerca a cero."
        ),
        f"{STATISTICAL}.FAIL": "El Sharpe observado no se distingue de cero.",
        f"{STATISTICAL}.NOT_MEASURED": "Significación no medida: {reason}.",
        f"{MULTIPLICITY}.PASS": (
            "Con {trials_phrase}, el resultado sigue por encima de lo que "
            "produciría el mejor intento sin habilidad."
        ),
        f"{MULTIPLICITY}.WEAK": (
            "Con {trials_phrase}, el Sharpe deflactado no llega al umbral: "
            "si se probaron más configuraciones, el resultado puede venir de elegir la mejor."
        ),
        f"{MULTIPLICITY}.FAIL": (
            "Con {trials_phrase}, el resultado no supera lo que produciría "
            "el mejor de esos intentos sin habilidad."
        ),
        f"{MULTIPLICITY}.NOT_MEASURED": "Multiplicidad no medida: {reason}.",
        f"{MULTIPLICITY}.PASS.undeclared": (
            "No se declaró cuántas configuraciones se probaron; con 1, el caso más favorable, "
            "el resultado sigue por encima de lo que produciría un intento sin habilidad. Si "
            "se probaron más, declararlo puede cambiar esta conclusión."
        ),
        f"{MULTIPLICITY}.WEAK.undeclared": (
            "No se declaró cuántas configuraciones se probaron, e incluso con 1, el caso más "
            "favorable, el Sharpe deflactado no llega al umbral."
        ),
        f"{MULTIPLICITY}.FAIL.undeclared": (
            "No se declaró cuántas configuraciones se probaron, e incluso con 1, el caso más "
            "favorable, el resultado no supera lo que produciría un intento sin habilidad."
        ),
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
        "C.account": (
            "Class C: there is a material weakness; we would not rely on this account "
            "history until it is resolved."
        ),
        "D.account": (
            "Class D: the account history does not pass the audit; the headline numbers "
            "cannot be taken as they stand."
        ),
        f"{STATISTICAL}.PASS": "The Sharpe ratio is statistically distinguishable from zero.",
        f"{STATISTICAL}.WEAK": (
            "The Sharpe ratio is inconclusive: the bootstrap interval nears zero."
        ),
        f"{STATISTICAL}.FAIL": "The observed Sharpe ratio is not distinguishable from zero.",
        f"{STATISTICAL}.NOT_MEASURED": "Significance not measured: {reason}.",
        f"{MULTIPLICITY}.PASS": (
            "With {trials_phrase}, the result stays above what the best "
            "unskilled trial would produce."
        ),
        f"{MULTIPLICITY}.WEAK": (
            "With {trials_phrase}, the deflated Sharpe misses the bar: if "
            "more configurations were tried, the result may come from picking the best one."
        ),
        f"{MULTIPLICITY}.FAIL": (
            "With {trials_phrase}, the result does not exceed what the best "
            "of those trials would produce without skill."
        ),
        f"{MULTIPLICITY}.NOT_MEASURED": "Multiplicity not measured: {reason}.",
        f"{MULTIPLICITY}.PASS.undeclared": (
            "The number of configurations tried was not declared; with 1, the most favourable "
            "case, the result stays above what an unskilled trial would produce. If more were "
            "tried, declaring them may change this conclusion."
        ),
        f"{MULTIPLICITY}.WEAK.undeclared": (
            "The number of configurations tried was not declared, and even with 1, the most "
            "favourable case, the deflated Sharpe misses the bar."
        ),
        f"{MULTIPLICITY}.FAIL.undeclared": (
            "The number of configurations tried was not declared, and even with 1, the most "
            "favourable case, the result does not exceed what an unskilled trial would produce."
        ),
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


#: "What this means for you": two plain sentences per dimension and status,
#: fixed templates in both languages. They explain, they never promise.
MEANING: dict[str, dict[str, str]] = {
    "es": {
        f"{STATISTICAL}.PASS": (
            "Con tantos datos, un resultado así es difícil de obtener por pura suerte. "
            "Eso no dice nada de lo que pasará después: solo que el historial no es ruido."
        ),
        f"{STATISTICAL}.WEAK": (
            "El resultado podría deberse en parte a la suerte: no hay datos suficientes para "
            "separarlo del azar. Más historial, o historial real, lo aclararía."
        ),
        f"{STATISTICAL}.FAIL": (
            "Con estos datos, el resultado no se distingue de lanzar una moneda. "
            "La curva puede verse bien y aun así ser azar."
        ),
        f"{STATISTICAL}.NOT_MEASURED": (
            "No hubo datos suficientes para medir si el resultado supera al azar. "
            "Sube una curva más larga para obtener esta respuesta."
        ),
        f"{MULTIPLICITY}.PASS": (
            "Aun descontando las configuraciones probadas, el resultado sigue en pie. "
            "Si se probaron más de las indicadas, esta conclusión se debilita."
        ),
        f"{MULTIPLICITY}.WEAK": (
            "Parte del resultado puede venir de elegir la mejor de muchas configuraciones. "
            "Pregunta cuántas se probaron y pide el archivo de optimización."
        ),
        f"{MULTIPLICITY}.FAIL": (
            "Probando tantas configuraciones, un resultado así aparece aunque ninguna tenga "
            "ventaja real. Es la señal clásica de un backtest sobreajustado."
        ),
        f"{MULTIPLICITY}.NOT_MEASURED": (
            "No se pudo descontar el número de intentos porque la significación no se midió. "
            "Con una curva más larga se puede calcular."
        ),
        f"{COSTS}.PASS": (
            "Las operaciones aguantan aunque los costes se tripliquen. "
            "Los costes reales dependen de tu bróker y de la ejecución."
        ),
        f"{COSTS}.WEAK": (
            "Con costes normales el resultado sigue positivo, pero con costes altos desaparece. "
            "Un spread o una comisión mayores que los supuestos lo borrarían."
        ),
        f"{COSTS}.FAIL": (
            "Con el coste de referencia, las operaciones pierden dinero en neto. "
            "El resultado del backtest depende de no pagar costes."
        ),
        f"{COSTS}.NOT_MEASURED": (
            "Sin la lista de operaciones no se pueden volver a aplicar los costes. "
            "Sube el informe de la plataforma para medirlos."
        ),
        f"{OUT_OF_SAMPLE}.PASS": (
            "En el tramo que no se usó para ajustar, el comportamiento se mantiene parecido. "
            "Solo vale si ese tramo de verdad no se miró al optimizar."
        ),
        f"{OUT_OF_SAMPLE}.WEAK": (
            "Fuera de muestra el resultado sigue positivo, pero bastante peor que dentro. "
            "Es habitual en estrategias algo sobreajustadas."
        ),
        f"{OUT_OF_SAMPLE}.FAIL": (
            "En el tramo que no se usó para ajustar, el resultado es negativo. "
            "Lo que funcionó en el ajuste no se repitió fuera de él."
        ),
        f"{OUT_OF_SAMPLE}.NOT_MEASURED": (
            "No se indicó un tramo fuera de muestra, así que no hay prueba sobre datos nuevos. "
            "Indica la fecha en la que termina la optimización para medirlo."
        ),
        f"{OUT_OF_SAMPLE}.NOT_MEASURED.account": (
            "El historial no dice desde cuándo el robot opera sin cambios, así que no se sabe "
            "qué parte es prueba sobre datos nuevos. Pregunta esa fecha al proveedor y "
            "declárala para medirlo."
        ),
        f"{DATA_QUALITY}.PASS": (
            "No encontramos saltos, huecos ni patrones de riesgo oculto en los archivos. "
            "Eso no descarta errores que los archivos no muestren."
        ),
        f"{DATA_QUALITY}.WEAK": (
            "Hay avisos en los datos que conviene aclarar antes de confiar en las cifras. "
            "Revisa la lista de banderas rojas y las preguntas para el vendedor."
        ),
        f"{DATA_QUALITY}.FAIL": (
            "Hay problemas graves en los datos o en la forma de operar. "
            "Las cifras principales no se pueden tomar tal cual."
        ),
        f"{BENCHMARK}.PASS": (
            "Supera a la referencia aportada sin caer más que ella. "
            "Compara con otra referencia si esta no representa tu alternativa real."
        ),
        f"{BENCHMARK}.WEAK": (
            "Supera a la referencia en retorno, pero con más riesgo. "
            "Parte de la diferencia puede ser solo riesgo adicional."
        ),
        f"{BENCHMARK}.FAIL": (
            "No supera a la referencia aportada. "
            "Una alternativa pasiva habría dado un resultado igual o mejor en ese periodo."
        ),
        f"{BENCHMARK}.NOT_MEASURED": (
            "No se aportó una referencia con la que comparar. "
            "Sube la curva de un índice o de comprar y mantener para medirlo."
        ),
        f"{BENCHMARK}.NOT_APPLICABLE": (
            "Se declaró que no hay una referencia aplicable. "
            "La comparación con una alternativa pasiva queda fuera de este informe."
        ),
    },
    "en": {
        f"{STATISTICAL}.PASS": (
            "With this much data, a result like this is hard to get by pure luck. "
            "That says nothing about what happens next: only that the history is not noise."
        ),
        f"{STATISTICAL}.WEAK": (
            "The result could partly be luck: there is not enough data to separate it from "
            "chance. More history, or live history, would settle it."
        ),
        f"{STATISTICAL}.FAIL": (
            "With this data, the result cannot be told apart from coin flips. "
            "The curve can look good and still be chance."
        ),
        f"{STATISTICAL}.NOT_MEASURED": (
            "There was not enough data to measure whether the result beats chance. "
            "Upload a longer curve to get this answer."
        ),
        f"{MULTIPLICITY}.PASS": (
            "Even after discounting the configurations tried, the result still stands. "
            "If more were tried than stated, this conclusion weakens."
        ),
        f"{MULTIPLICITY}.WEAK": (
            "Part of the result may come from picking the best of many configurations. "
            "Ask how many were tried and request the optimisation file."
        ),
        f"{MULTIPLICITY}.FAIL": (
            "Trying this many configurations produces a result like this even when none has "
            "a real edge. It is the classic sign of an overfitted backtest."
        ),
        f"{MULTIPLICITY}.NOT_MEASURED": (
            "The number of trials could not be discounted because significance was not "
            "measured. A longer curve makes it computable."
        ),
        f"{COSTS}.PASS": (
            "The trades hold up even if costs triple. "
            "Real costs depend on your broker and on execution."
        ),
        f"{COSTS}.WEAK": (
            "At normal costs the result stays positive, but at high costs it disappears. "
            "A wider spread or higher commission than assumed would erase it."
        ),
        f"{COSTS}.FAIL": (
            "At the reference cost, the trades lose money net. "
            "The backtest result depends on paying no costs."
        ),
        f"{COSTS}.NOT_MEASURED": (
            "Without the list of trades the costs cannot be re-applied. "
            "Upload the platform report to measure them."
        ),
        f"{OUT_OF_SAMPLE}.PASS": (
            "In the stretch not used for tuning, behaviour stays similar. "
            "It only counts if that stretch was truly not looked at while optimising."
        ),
        f"{OUT_OF_SAMPLE}.WEAK": (
            "Out of sample the result stays positive, but much worse than in sample. "
            "This is common in somewhat overfitted strategies."
        ),
        f"{OUT_OF_SAMPLE}.FAIL": (
            "In the stretch not used for tuning, the result is negative. "
            "What worked during tuning did not repeat outside it."
        ),
        f"{OUT_OF_SAMPLE}.NOT_MEASURED": (
            "No out-of-sample stretch was given, so there is no test on unseen data. "
            "State the date the optimisation ends to measure it."
        ),
        f"{OUT_OF_SAMPLE}.NOT_MEASURED.account": (
            "The history does not say since when the robot has run unchanged, so it is not "
            "known which part is a test on unseen data. Ask the provider for that date and "
            "declare it to measure it."
        ),
        f"{DATA_QUALITY}.PASS": (
            "We found no jumps, gaps or hidden-risk patterns in the files. "
            "That does not rule out errors the files do not show."
        ),
        f"{DATA_QUALITY}.WEAK": (
            "There are warnings in the data worth clearing up before trusting the figures. "
            "Check the red flags and the questions for the vendor."
        ),
        f"{DATA_QUALITY}.FAIL": (
            "There are serious problems in the data or in the way it trades. "
            "The headline figures cannot be taken as they stand."
        ),
        f"{BENCHMARK}.PASS": (
            "It beats the supplied reference without falling further than it. "
            "Compare with another reference if this one is not your real alternative."
        ),
        f"{BENCHMARK}.WEAK": (
            "It beats the reference on return, but with more risk. "
            "Part of the difference may be extra risk only."
        ),
        f"{BENCHMARK}.FAIL": (
            "It does not beat the supplied reference. "
            "A passive alternative gave an equal or better result over that period."
        ),
        f"{BENCHMARK}.NOT_MEASURED": (
            "No reference was supplied to compare against. "
            "Upload an index or buy-and-hold curve to measure it."
        ),
        f"{BENCHMARK}.NOT_APPLICABLE": (
            "No applicable reference was declared. "
            "A comparison with a passive alternative is outside this report."
        ),
    },
}


def class_text(overall: str, locale: str = "es") -> str:
    """The fixed one-line explanation of a class (A to D)."""
    texts = _TEXT.get(locale, _TEXT["es"])
    return texts.get(overall, "")


def meaning(name: str, status: str, locale: str = "es", *, account: bool = False) -> str:
    """Two plain sentences on what a dimension's status means for the reader.

    ``account`` picks the wording for an account history where one exists."""
    texts = MEANING.get(locale, MEANING["es"])
    if account and f"{name}.{status}.account" in texts:
        return texts[f"{name}.{status}.account"]
    return texts.get(f"{name}.{status}", "")


def summary(
    dimensions: list[Dimension],
    overall: str,
    *,
    locale: Locale = "es",
    trials: int = 1,
    trials_evidence: str = "DECLARED",
    account: bool = False,
) -> str:
    """Plain-language summary from fixed templates; never a promise.

    ``account`` names the upload an account history rather than a backtest."""
    text = _TEXT[locale]
    source = TRIAL_SOURCE[locale].get(trials_evidence, TRIAL_SOURCE[locale]["DECLARED"])
    lines = [text.get(f"{overall}.account", text[overall]) if account else text[overall]]
    by_name = {dimension.name: dimension for dimension in dimensions}
    for name in DIMENSION_ORDER:
        dimension = by_name.get(name)
        if dimension is None:
            continue
        key = f"{name}.{dimension.status}"
        # Undeclared trials are computed at 1, the most favourable case; say so plainly.
        undeclared = f"{key}.undeclared"
        if name == MULTIPLICITY and trials_evidence == "NOT_MEASURED" and trials == 1:
            key = undeclared if undeclared in text else key
        template = text.get(key, f"{name}: {dimension.status}.")
        reasons = dimension.reasons_in(locale)
        lines.append(
            template.format(
                reason=reasons[0] if reasons else "",
                trials=trials,
                trials_source=source,
                trials_phrase=trials_phrase(trials, trials_evidence, locale),
                codes=", ".join(reasons),
            )
        )
    return " ".join(lines)


def build_verdict(
    dimensions: list[Dimension],
    *,
    locale: Locale,
    trials: int,
    trials_evidence: str = "DECLARED",
    thresholds: Thresholds = DEFAULT_THRESHOLDS,
    account: bool = False,
) -> Verdict:
    overall = overall_class(dimensions)
    return Verdict(
        overall=overall,
        summary=summary(
            dimensions,
            overall,
            locale=locale,
            trials=trials,
            trials_evidence=trials_evidence,
            account=account,
        ),
        thresholds=thresholds.model_dump(),
        dimensions=dimensions,
    )


__all__ = [
    "BENCHMARK",
    "COSTS",
    "DATA_QUALITY",
    "DEFAULT_THRESHOLDS",
    "DIMENSION_ORDER",
    "MEANING",
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
    "class_text",
    "meaning",
    "overall_class",
    "summary",
]
