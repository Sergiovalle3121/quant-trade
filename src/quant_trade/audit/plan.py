"""What the audit would need to see for a better class: one step per open dimension.

The verdict says where a backtest stands; this module says, for every
dimension that did not pass, what evidence or change the audit's own rules
would need, with the numbers from the same result (observations short,
break-even cost, trials at which the deflated Sharpe halves, the flags to
clear). It is a reading of fixed thresholds, not advice to trade, and it
never says that fixing a step makes a strategy worth running: a better class
means the files answer more of the audit's questions, nothing more.

The plan is rebuilt from a stored result (the JSON dict), so every audit
already in the database gets one without re-running the engine. Every
sentence comes from the fixed templates below and passes the profit-claim
guard with the rest of the report.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from quant_trade.audit.engine import HOLDOUT_MIN_OBSERVATIONS
from quant_trade.audit.redflags import OBSERVATIONS_WARN, flag_title
from quant_trade.audit.schema import MIN_OBSERVATIONS, Dimension
from quant_trade.audit.verdict import (
    BENCHMARK,
    COSTS,
    DATA_QUALITY,
    MULTIPLICITY,
    OUT_OF_SAMPLE,
    STATISTICAL,
    overall_class,
)

#: The order in which open dimensions are worked: a data problem or a
#: significance failure decides class D by itself, so they come first.
PLAN_ORDER = (DATA_QUALITY, STATISTICAL, MULTIPLICITY, COSTS, OUT_OF_SAMPLE, BENCHMARK)
STATUS_RANK = {"FAIL": 0, "WEAK": 1, "NOT_MEASURED": 2}
CLASS_RANK = {"D": 0, "C": 1, "B": 2, "A": 3}


@dataclass(frozen=True)
class PlanStep:
    """One open dimension and what the audit would need to see for it."""

    dimension: str
    status: str
    title: str
    finding: str
    actions: list[str] = field(default_factory=list)
    #: The class with this dimension passing and every other one unchanged,
    #: only when that differs from the current class.
    class_if_passed: str | None = None


def _value(block: Any) -> Any:
    if isinstance(block, dict):
        return block.get("value")
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _fmt(value: float, digits: int = 2) -> str:
    return f"{value:,.{digits}f}"


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _duration(periods: float, periods_per_year: float | None, locale: str) -> str:
    """``periods`` of the uploaded frequency as a rough calendar span."""
    if not periods_per_year or periods_per_year <= 0:
        return ""
    es = locale == "es"
    months = periods / periods_per_year * 12.0
    if months < 1.0:
        weeks = max(1, round(months * 52.0 / 12.0))
        return "≈ " + (
            _plural(weeks, "semana", "semanas") if es else _plural(weeks, "week", "weeks")
        )
    if months < 24.0:
        whole = max(1, round(months))
        return "≈ " + (_plural(whole, "mes", "meses") if es else _plural(whole, "month", "months"))
    years = months / 12.0
    return f"≈ {years:.1f} " + ("años" if es else "years")


TITLES: dict[str, dict[str, str]] = {
    "es": {
        DATA_QUALITY: "Limpia las banderas de los datos",
        STATISTICAL: "Aporta más historial",
        MULTIPLICITY: "Mide cuántas configuraciones se probaron",
        COSTS: "Comprueba los costes reales",
        OUT_OF_SAMPLE: "Añade un tramo fuera de muestra",
        BENCHMARK: "Compara con una alternativa pasiva",
    },
    "en": {
        DATA_QUALITY: "Clear the data flags",
        STATISTICAL: "Supply more history",
        MULTIPLICITY: "Measure how many configurations were tried",
        COSTS: "Check the real costs",
        OUT_OF_SAMPLE: "Add an out-of-sample stretch",
        BENCHMARK: "Compare with a passive alternative",
    },
}

#: What the audit would need to see for each red flag, in both languages.
FLAG_HINTS: dict[str, dict[str, str]] = {
    "TOO_FEW_OBSERVATIONS": {
        "es": (
            f"Sube un historial más largo: al menos {MIN_OBSERVATIONS} retornos para medir, "
            f"y {OBSERVATIONS_WARN} o más para que la conclusión no sea frágil."
        ),
        "en": (
            f"Upload a longer history: at least {MIN_OBSERVATIONS} returns to measure, "
            f"and {OBSERVATIONS_WARN} or more for a conclusion that is not fragile."
        ),
    },
    "NON_POSITIVE_EQUITY": {
        "es": "La cuenta llegó a cero o menos: revisa el tamaño de posición y el saldo inicial.",
        "en": "The account reached zero or less: check the position size and starting balance.",
    },
    "DUPLICATE_TIMESTAMPS": {
        "es": "Exporta una fila por fecha; si hay varias cuentas o símbolos, súbelos por separado.",
        "en": "Export one row per date; upload several accounts or symbols separately.",
    },
    "NON_MONOTONIC_TIMESTAMPS": {
        "es": "Ordena la curva por fecha antes de exportarla.",
        "en": "Sort the curve by date before exporting it.",
    },
    "UNPARSEABLE_ROWS": {
        "es": "Vuelve a exportar desde la plataforma sin editar el archivo a mano.",
        "en": "Export again from the platform without editing the file by hand.",
    },
    "ZERO_VARIANCE": {
        "es": "La curva no se mueve: comprueba que subiste la columna de equity correcta.",
        "en": "The curve does not move: check that the right equity column was uploaded.",
    },
    "STALE_MARKS": {
        "es": "Hay tramos con el mismo valor repetido: usa datos con cotización en cada periodo.",
        "en": "Stretches repeat the same value: use data with a quote in every period.",
    },
    "MAD_SPIKES": {
        "es": "Hay saltos extremos: revisa depósitos, retiros o errores de precio en esas fechas.",
        "en": "There are extreme jumps: check deposits, withdrawals or bad prices on those dates.",
    },
    "IMPLAUSIBLE_SHARPE": {
        "es": (
            "Un Sharpe tan alto suele venir de datos de baja calidad, costes omitidos o un "
            "periodo corto: prueba con ticks reales, costes reales y un periodo más largo."
        ),
        "en": (
            "A Sharpe this high usually comes from poor data, missing costs or a short "
            "period: test with real ticks, real costs and a longer period."
        ),
    },
    "LARGE_GAPS": {
        "es": "Faltan tramos de fechas: exporta el periodo completo, sin cortes.",
        "en": "Date ranges are missing: export the whole period without cuts.",
    },
    "ZERO_DECLARED_COSTS": {
        "es": "Declara el coste por lado de tu bróker (spread, comisión y deslizamiento).",
        "en": "Declare your broker's cost per side (spread, commission and slippage).",
    },
    "TRIALS_BELOW_VARIANTS": {
        "es": "Declara el número real de configuraciones probadas; los archivos muestran más.",
        "en": "Declare the real number of configurations tried; the files show more.",
    },
    "INVALID_TRADE_ROWS": {
        "es": "Vuelve a exportar las operaciones desde la plataforma, sin filas editadas.",
        "en": "Export the trades again from the platform, with no edited rows.",
    },
    "TRADE_PNL_MISMATCH": {
        "es": (
            "El resultado por operación no cuadra con precios y tamaños: revisa el tamaño "
            "de contrato y la divisa de la cuenta."
        ),
        "en": (
            "The per-trade result does not match prices and sizes: check the contract size "
            "and the account currency."
        ),
    },
    "MARTINGALE_SIZING": {
        "es": (
            "El tamaño crece tras las pérdidas: con tamaño fijo o por riesgo fijo la curva "
            "muestra el riesgo real; súbela así para comparar."
        ),
        "en": (
            "Size grows after losses: with a fixed size or fixed risk the curve shows the "
            "real risk; upload that version to compare."
        ),
    },
    "GRID_AVERAGING": {
        "es": (
            "Se abren posiciones contra la posición perdedora: sube también un backtest sin "
            "promediar para ver cuánto depende de ello."
        ),
        "en": (
            "Positions are added against the losing one: also upload a backtest without "
            "averaging to see how much depends on it."
        ),
    },
    "MANY_CONCURRENT_POSITIONS": {
        "es": "Limita las posiciones abiertas a la vez o sube la curva de equity con flotante.",
        "en": "Limit the positions open at once or upload the equity curve with floating P&L.",
    },
    "HIDDEN_FLOATING_DRAWDOWN": {
        "es": (
            "La curva solo muestra el balance: sube la curva de equity (con flotante) para "
            "medir el drawdown real."
        ),
        "en": (
            "The curve shows only the balance: upload the equity curve (with floating P&L) "
            "to measure the real drawdown."
        ),
    },
    "NEGATIVE_PAYOFF_HIGH_WINRATE": {
        "es": (
            "Muchos aciertos pequeños y pérdidas grandes: una pérdida máxima por operación "
            "limitada haría visible el riesgo de cola."
        ),
        "en": (
            "Many small wins and large losses: a capped loss per trade would make the tail "
            "risk visible."
        ),
    },
    "NO_STOP_EVIDENCE": {
        "es": "La mayor pérdida es muy superior a la media: revisa si el stop de pérdida existe.",
        "en": "The largest loss far exceeds the average: check whether a stop loss exists.",
    },
    "TRADES_OUTSIDE_EQUITY": {
        "es": "Sube la curva y las operaciones de la misma cuenta y el mismo periodo.",
        "en": "Upload the curve and the trades of the same account and period.",
    },
    "TRADES_EQUITY_UNRELATED": {
        "es": "Las operaciones no explican la curva: sube ambos archivos de la misma cuenta.",
        "en": "The trades do not explain the curve: upload both files from the same account.",
    },
}

GENERIC_FLAG_HINT = {
    "es": "Revisa el detalle de la bandera en la tabla de banderas rojas.",
    "en": "Check the flag's detail in the red-flag table.",
}


def _significance_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    sig = data.get("significance") or {}
    es = locale == "es"
    n = _number(_value(sig.get("observations")))
    need = _number(_value(sig.get("min_track_record_length")))
    psr = _number(_value(sig.get("psr")))
    ppy = _number(_value((data.get("inputs") or {}).get("periods_per_year")))
    if sig.get("status") != "MEASURED" or n is None:
        finding = (
            "No hay suficientes datos para medir si el resultado supera al azar."
            if es
            else "There is not enough data to measure whether the result beats chance."
        )
        return finding, [FLAG_HINTS["TOO_FEW_OBSERVATIONS"][locale]]
    if psr is not None and need is not None and need > n:
        extra = need - n
        span = _duration(extra, ppy, locale)
        span_text = f" ({span})" if span else ""
        finding = (
            f"PSR {_fmt(psr, 3)} con {n:.0f} observaciones. Con el mismo comportamiento, "
            f"llegaría a 0.95 con unas {math.ceil(need):,} observaciones: faltan "
            f"{math.ceil(extra):,}{span_text}."
            if es
            else f"PSR {_fmt(psr, 3)} with {n:.0f} observations. With the same behaviour it "
            f"would reach 0.95 at about {math.ceil(need):,} observations: "
            f"{math.ceil(extra):,} more{span_text}."
        )
    else:
        band = (data.get("bootstrap") or {}).get("sharpe_per_period") or {}
        p5 = _number(_value(band.get("p5")))
        p5_text = f" ({_fmt(p5, 3)})" if p5 is not None else ""
        finding = (
            f"El PSR es {_fmt(psr or 0.0, 3)}, pero el percentil 5 del Sharpe en el bootstrap"
            f"{p5_text} no queda por encima de cero."
            if es
            else f"PSR is {_fmt(psr or 0.0, 3)}, but the bootstrap's 5th-percentile Sharpe"
            f"{p5_text} is not above zero."
        )
    actions = (
        [
            "Sube un periodo más largo del mismo sistema, sin cambiar parámetros.",
            "Mejor aún, añade historial de cuenta demo posterior al backtest: cuenta como "
            "datos que el optimizador nunca vio.",
        ]
        if es
        else [
            "Upload a longer period of the same system, with unchanged parameters.",
            "Better still, add demo-account history from after the backtest: it counts as "
            "data the optimiser never saw.",
        ]
    )
    return finding, actions


def _multiplicity_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    mult = data.get("multiplicity") or {}
    es = locale == "es"
    if status == "NOT_MEASURED" or mult.get("status") != "MEASURED":
        finding = (
            "Se calcula en cuanto la significación sea medible: el paso de historial lo resuelve."
            if es
            else "It is computed once significance is measurable: the history step solves it."
        )
        return finding, []
    trials = _number(_value(mult.get("trials_used"))) or 1.0
    dsr = _number(_value(mult.get("dsr_at_trials_used")))
    half = _number(_value(mult.get("trials_to_half")))
    pbo = _number(_value((data.get("cscv") or {}).get("pbo")))
    parts = []
    if dsr is not None:
        parts.append(
            f"DSR {_fmt(dsr, 3)} con {trials:.0f} intento(s); el umbral es 0.95."
            if es
            else f"DSR {_fmt(dsr, 3)} at {trials:.0f} trial(s); the bar is 0.95."
        )
    if half is not None:
        parts.append(
            f"Con {half:.0f} o más configuraciones probadas cae por debajo de 0.5."
            if es
            else f"With {half:.0f} or more configurations tried it falls below 0.5."
        )
    if pbo is not None and pbo >= 0.5:
        parts.append(
            f"PBO {_fmt(pbo, 2)}: la mejor configuración dentro de muestra suele quedar por "
            "debajo de la mediana fuera de muestra."
            if es
            else f"PBO {_fmt(pbo, 2)}: the best in-sample configuration tends to land below "
            "the median out of sample."
        )
    actions = (
        [
            "Sube el XML de la optimización de MT5 o la matriz de variantes: el número de "
            "intentos pasa a ser medido y se calcula el PBO.",
            "Menos parámetros y rangos más cortos reducen el número de intentos.",
            "Valida la configuración elegida en un tramo que no se usó al optimizar.",
        ]
        if es
        else [
            "Upload the MT5 optimisation XML or the variants matrix: the trial count becomes "
            "measured and the PBO is computed.",
            "Fewer parameters and narrower ranges mean fewer trials.",
            "Validate the chosen configuration on a stretch not used while optimising.",
        ]
    )
    return " ".join(parts), actions


def _costs_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    costs = data.get("costs") or {}
    es = locale == "es"
    if status == "NOT_MEASURED" or costs.get("status") != "MEASURED":
        finding = (
            "Sin la lista de operaciones no se pueden volver a aplicar los costes; sin ellas la "
            "mejor clase posible es B."
            if es
            else "Without the list of trades the costs cannot be re-applied; without them the "
            "best possible class is B."
        )
        action = (
            "Sube el informe de la plataforma (MT5, MT4, TradingView...) o el CSV de "
            "operaciones cerradas."
            if es
            else "Upload the platform report (MT5, MT4, TradingView...) or the closed-trades CSV."
        )
        return finding, [action]
    breakeven = _number(_value(costs.get("break_even_bps")))
    reference = _number(_value(costs.get("reference_bps"))) or 0.0
    needed = reference * 3.0
    if breakeven is None or breakeven <= 0:
        finding = (
            "Incluso sin coste extra, el neto de las operaciones no queda por encima de cero "
            "tras las comisiones y el swap del archivo."
            if es
            else "Even with no extra cost, the trades do not net above zero after the "
            "commission and swap in the file."
        )
    else:
        finding = (
            f"El neto llega a cero con {_fmt(breakeven)} pb por lado de coste extra. Para "
            f"pasar esta dimensión tiene que seguir por encima de cero a 3x la referencia "
            f"({_fmt(needed)} pb por lado)."
            if es
            else f"The net reaches zero at {_fmt(breakeven)} bps per side of extra cost. To "
            f"pass this dimension it has to stay above zero at 3x the reference "
            f"({_fmt(needed)} bps per side)."
        )
    actions = (
        [
            "Compara ese margen con el spread y el deslizamiento reales de tu bróker: en "
            "EURUSD a 1.10, 1 pb por lado son unos 1.1 pips.",
            "Declara el coste real por lado al subir: se suma a lo que el informe ya detalla.",
            "Menos operaciones o un recorrido mayor por operación hacen que el coste pese menos.",
        ]
        if es
        else [
            "Compare that margin with your broker's real spread and slippage: on EURUSD at "
            "1.10, 1 bp per side is about 1.1 pips.",
            "Declare the real cost per side when uploading: it is added to what the report "
            "already itemises.",
            "Fewer trades or a larger move per trade make costs weigh less.",
        ]
    )
    return finding, actions


def _oos_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    hold = data.get("holdout") or {}
    es = locale == "es"
    inputs = data.get("inputs") or {}
    if status == "NOT_MEASURED":
        reason = str(hold.get("reason", ""))
        if "fewer than" in reason:
            finding = (
                f"Uno de los dos tramos tiene menos de {HOLDOUT_MIN_OBSERVATIONS} retornos: mueve "
                "la fecha para que ambos lados tengan al menos esa cantidad."
                if es
                else f"One of the two stretches has fewer than {HOLDOUT_MIN_OBSERVATIONS} "
                "returns: move the date so that both sides have at least that many."
            )
        elif "outside" in reason:
            finding = (
                f"La fecha declarada cae fuera de la serie ({inputs.get('first_timestamp', '')} "
                f"→ {inputs.get('last_timestamp', '')})."
                if es
                else f"The declared date lies outside the series "
                f"({inputs.get('first_timestamp', '')} → {inputs.get('last_timestamp', '')})."
            )
        else:
            finding = (
                "No se declaró un tramo fuera de muestra: sin él la mejor clase posible es B."
                if es
                else "No out-of-sample stretch was declared: without it the best possible "
                "class is B."
            )
        actions = (
            [
                "Declara la fecha en que terminó la optimización: lo posterior se mide como "
                "fuera de muestra y queda sellado en el informe.",
                "Mejor aún, corre el EA sin cambios en un periodo posterior y sube ese "
                "informe con la fecha de corte.",
            ]
            if es
            else [
                "Declare the date the optimisation ended: what follows is measured out of "
                "sample and sealed in the report.",
                "Better still, run the EA unchanged on a later period and upload that report "
                "with the cut-off date.",
            ]
        )
        return finding, actions
    oos = _number(_value((hold.get("out_of_sample") or {}).get("sharpe_annualised")))
    gap = _number(_value(hold.get("gap")))
    parts = []
    if oos is not None:
        parts.append(
            f"Sharpe fuera de muestra {_fmt(oos)}; hace falta 0.5 o más."
            if es
            else f"Out-of-sample Sharpe {_fmt(oos)}; 0.5 or more is needed."
        )
    if gap is not None:
        parts.append(
            f"Diferencia dentro/fuera {_fmt(gap)}; el máximo es 1.0."
            if es
            else f"In/out gap {_fmt(gap)}; the maximum is 1.0."
        )
    actions = (
        [
            "Una caída fuerte fuera de muestra es la huella típica del sobreajuste: menos "
            "parámetros y una nueva validación en datos no vistos.",
        ]
        if es
        else [
            "A sharp drop out of sample is the usual mark of overfitting: fewer parameters "
            "and a fresh validation on unseen data.",
        ]
    )
    return " ".join(parts), actions


def _benchmark_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    bench = data.get("benchmark") or {}
    es = locale == "es"
    if status == "NOT_MEASURED":
        finding = (
            "No se subió una referencia con la que comparar."
            if es
            else "No reference was uploaded to compare against."
        )
        actions = (
            [
                "Sube la curva de una alternativa pasiva: comprar y mantener el mismo activo o "
                "un índice, con las mismas fechas.",
                "Si no existe una alternativa pasiva comparable (por ejemplo, un EA de forex), "
                "declara que no aplica: la clase A lo admite.",
            ]
            if es
            else [
                "Upload the curve of a passive alternative: buy-and-hold of the same asset or "
                "an index, over the same dates.",
                "If no comparable passive alternative exists (a forex EA, say), declare it "
                "not applicable: class A allows that.",
            ]
        )
        return finding, actions
    excess = _number(_value(bench.get("excess_return")))
    ratio = _number(_value(bench.get("drawdown_ratio")))
    parts = []
    if excess is not None:
        parts.append(
            f"Exceso sobre la referencia {excess:+.1%}."
            if es
            else f"Excess over the reference {excess:+.1%}."
        )
    if ratio is not None:
        parts.append(
            f"Drawdown {_fmt(ratio)} veces el de la referencia; el máximo es 1.0."
            if es
            else f"Drawdown {_fmt(ratio)} times the reference's; the maximum is 1.0."
        )
    actions = (
        ["Comprueba que la referencia es tu alternativa real, con las mismas fechas."]
        if es
        else ["Check that the reference is your real alternative, over the same dates."]
    )
    return " ".join(parts), actions


def _data_quality_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    flags = sorted(
        data.get("red_flags") or [], key=lambda flag: 0 if flag.get("severity") == "FAIL" else 1
    )
    es = locale == "es"
    fails = sum(1 for flag in flags if flag.get("severity") == "FAIL")
    warns = len(flags) - fails
    finding = (
        f"{_plural(fails, 'bandera grave', 'banderas graves')} y "
        f"{_plural(warns, 'aviso', 'avisos')} en los datos."
        if es
        else f"{_plural(fails, 'serious flag', 'serious flags')} and "
        f"{_plural(warns, 'warning', 'warnings')} in the data."
    )
    seen: set[str] = set()
    actions = []
    for flag in flags:
        code = str(flag.get("code", ""))
        if code in seen:
            continue
        seen.add(code)
        hint = FLAG_HINTS.get(code, GENERIC_FLAG_HINT)[locale]
        actions.append(f"{flag_title(code, locale)}. {hint}")
    return finding, actions


_BUILDERS = {
    DATA_QUALITY: _data_quality_step,
    STATISTICAL: _significance_step,
    MULTIPLICITY: _multiplicity_step,
    COSTS: _costs_step,
    OUT_OF_SAMPLE: _oos_step,
    BENCHMARK: _benchmark_step,
}


def _class_if_passed(dimensions: list[Dimension], name: str) -> str:
    changed = [d.model_copy(update={"status": "PASS"}) if d.name == name else d for d in dimensions]
    return overall_class(changed)


def improvement_plan(data: dict[str, Any], locale: str = "es") -> list[PlanStep]:
    """One step per dimension that did not pass, most decisive first.

    ``data`` is the stored result (``AuditResult.model_dump(mode="json")``).
    """
    locale = "en" if locale == "en" else "es"
    verdict = data.get("verdict") or {}
    dimensions = [Dimension.model_validate(d) for d in verdict.get("dimensions", [])]
    current = str(verdict.get("overall", ""))
    by_name = {d.name: d for d in dimensions}
    steps: list[PlanStep] = []
    for name in PLAN_ORDER:
        dimension = by_name.get(name)
        if dimension is None or dimension.status not in STATUS_RANK:
            continue
        finding, actions = _BUILDERS[name](data, dimension.status, locale)
        better = _class_if_passed(dimensions, name)
        steps.append(
            PlanStep(
                dimension=name,
                status=dimension.status,
                title=TITLES[locale][name],
                finding=finding,
                actions=actions,
                class_if_passed=better if better != current else None,
            )
        )
    steps.sort(
        key=lambda step: (
            -(CLASS_RANK.get(step.class_if_passed or current, 0) - CLASS_RANK.get(current, 0)),
            STATUS_RANK[step.status],
            PLAN_ORDER.index(step.dimension),
        )
    )
    return steps


__all__ = ["FLAG_HINTS", "PLAN_ORDER", "PlanStep", "TITLES", "improvement_plan"]
