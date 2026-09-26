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
from typing import Any, TypeVar

from quant_trade.audit import report_pt
from quant_trade.audit.account import is_account_history
from quant_trade.audit.engine import HOLDOUT_MIN_OBSERVATIONS
from quant_trade.audit.redflags import OBSERVATIONS_WARN, flag_title
from quant_trade.audit.schema import MIN_OBSERVATIONS, Dimension
from quant_trade.audit.verdict import (
    BENCHMARK,
    COSTS,
    DATA_QUALITY,
    FUND_OOS_REASON,
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

_T = TypeVar("_T")


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


def _say(locale: str, es: _T, en: _T, pt: _T) -> _T:
    """The Spanish, English or Portuguese version for ``locale`` (English by default)."""
    return {"es": es, "pt": pt}.get(locale, en)


#: Past this multiple of the history it has, the plan stops counting what is missing.
NEED_CAP = 10


def _plural(count: int, one: str, many: str) -> str:
    return f"{count} {one if count == 1 else many}"


def _duration(periods: float, periods_per_year: float | None, locale: str) -> str:
    """``periods`` of the uploaded frequency as a rough calendar span."""
    if not periods_per_year or periods_per_year <= 0:
        return ""
    months = periods / periods_per_year * 12.0
    if months < 1.0:
        weeks = max(1, round(months * 52.0 / 12.0))
        return "≈ " + _say(
            locale,
            _plural(weeks, "semana", "semanas"),
            _plural(weeks, "week", "weeks"),
            _plural(weeks, "semana", "semanas"),
        )
    if months < 24.0:
        whole = max(1, round(months))
        return "≈ " + _say(
            locale,
            _plural(whole, "mes", "meses"),
            _plural(whole, "month", "months"),
            _plural(whole, "mês", "meses"),
        )
    years = months / 12.0
    return f"≈ {years:.1f} " + _say(locale, "años", "years", "anos")


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

#: Titles that read differently when the upload is an account history.
ACCOUNT_TITLES: dict[str, dict[str, str]] = {
    "es": {OUT_OF_SAMPLE: "Averigua desde cuándo opera sin cambios"},
    "en": {OUT_OF_SAMPLE: "Find out since when it has run unchanged"},
}

#: Titles that read differently when the upload is a fund's track record.
FUND_TITLES: dict[str, dict[str, str]] = {
    "es": {
        OUT_OF_SAMPLE: "Averigua desde cuándo el gestor no cambia de proceso",
        COSTS: "Confirma si las cifras son netas de comisiones",
        MULTIPLICITY: "Pregunta cuántos fondos lleva el gestor",
        BENCHMARK: "Compara con el índice del fondo",
    },
    "en": {
        OUT_OF_SAMPLE: "Find out since when the manager's process is unchanged",
        COSTS: "Confirm whether the figures are net of fees",
        MULTIPLICITY: "Ask how many funds the manager runs",
        BENCHMARK: "Compare with the fund's index",
    },
}


def _fund_record(data: dict[str, Any]) -> bool:
    """True when a stored audit result was run on a fund's track record."""
    return bool((data.get("fund") or {}).get("track_record"))


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
        "es": (
            "Hay días en que la cuenta se mueve más de un 15 %: si vienen de depósitos, "
            "retiros o precios erróneos, corrígelos; si son operaciones reales, el tamaño "
            "es muy agresivo para la cuenta."
        ),
        "en": (
            "On some days the account moves more than 15 %: if they come from deposits, "
            "withdrawals or bad prices, fix them; if they are real trades, the size is very "
            "aggressive for the account."
        ),
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
    "PROFIT_CONCENTRATION": {
        "es": (
            "Revisa la mejor operación en el archivo (fecha, tamaño, precio) y pide más "
            "historial: con el resultado en una sola operación, el resto del sistema no está "
            "medido."
        ),
        "en": (
            "Check the best trade in the file (date, size, price) and ask for more history: "
            "with the result in one trade, the rest of the system is not measured."
        ),
    },
    "TRADES_OUTSIDE_EQUITY": {
        "es": "Sube la curva y las operaciones de la misma cuenta y el mismo periodo.",
        "en": "Upload the curve and the trades of the same account and period.",
    },
    "TRADES_EQUITY_UNRELATED": {
        "es": "Las operaciones no explican la curva: sube ambos archivos de la misma cuenta.",
        "en": "The trades do not explain the curve: upload both files from the same account.",
    },
    "GAIN_INFLATED_BY_FLOWS": {
        "es": (
            "El porcentaje sale de quitar depósitos y retiros: juzga la cuenta también por "
            "el dinero que ganó o perdió al operar."
        ),
        "en": (
            "The percentage comes from removing deposits and withdrawals: judge the account "
            "by the money its trading made or lost as well."
        ),
    },
    "DEPOSIT_DURING_DRAWDOWN": {
        "es": (
            "Hubo dinero nuevo en plena pérdida: mira el drawdown sin esos depósitos y "
            "pregunta por qué se añadieron."
        ),
        "en": (
            "New money arrived in a deep loss: look at the drawdown without those deposits "
            "and ask why they were added."
        ),
    },
    "FLOATING_LOSS_AT_END": {
        "es": (
            "Hay posiciones abiertas con pérdida: pide un historial impreso después de que "
            "se cierren para ver el resultado real."
        ),
        "en": (
            "Positions are open at a loss: ask for a history printed after they close to see "
            "the real result."
        ),
    },
    "COARSE_TICK_MODEL": {
        "es": (
            "Pide el mismo backtest con cada tick (o ticks reales en MT5); solo los robots "
            "que operan al abrir la vela se pueden juzgar con precios de apertura."
        ),
        "en": (
            "Ask for the same backtest on every tick (or real ticks in MT5); only robots that "
            "trade at the bar's open can be judged on open prices."
        ),
    },
    "TEST_DATA_QUALITY_LOW": {
        "es": (
            "Pide el backtest repetido con un historial completo, idealmente con ticks reales, "
            "y compara el resultado."
        ),
        "en": (
            "Ask for the backtest rerun on a complete history, ideally real ticks, and compare "
            "the result."
        ),
    },
    "ISOLATED_OPTIMUM": {
        "es": (
            "Elige valores en una zona donde los vecinos también ganen (una meseta), aunque el "
            "resultado sea menor, y compruébalos en un tramo fuera de muestra."
        ),
        "en": (
            "Pick values in a zone where the neighbours also end with a profit (a plateau), "
            "even at a lower result, and check them on an out-of-sample stretch."
        ),
    },
    "FORWARD_NOT_HELD": {
        "es": (
            "Las mejores pasadas del backtest no destacan con datos nuevos: optimiza menos "
            "parámetros o con rangos más amplios, y elige una configuración que también "
            "funcione en el periodo forward."
        ),
        "en": (
            "The best backtest passes do not stand out on new data: optimise fewer parameters "
            "or wider ranges, and pick settings that also work in the forward period."
        ),
    },
    "EDGE_FADING": {
        "es": (
            "Las operaciones recientes dejan de sumar: pregunta qué cambió (mercado, bróker, "
            "ajustes) y juzga el sistema por su último tramo, no por el total."
        ),
        "en": (
            "The recent trades stop adding up: ask what changed (market, broker, settings) and "
            "judge the system on its last stretch, not on the total."
        ),
    },
    "REPORT_HEADER_MISMATCH": {
        "es": (
            "Pide el archivo original que exporta MetaTrader, no una captura, y vuelve a "
            "subirlo tal cual."
        ),
        "en": (
            "Ask for the original file MetaTrader exports, not a screenshot, and upload it "
            "as it is."
        ),
    },
}

GENERIC_FLAG_HINT = {
    "es": "Revisa el detalle de la bandera en la tabla de banderas rojas.",
    "en": "Check the flag's detail in the red-flag table.",
}


def _significance_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    sig = data.get("significance") or {}
    n = _number(_value(sig.get("observations")))
    need = _number(_value(sig.get("min_track_record_length")))
    psr = _number(_value(sig.get("psr")))
    ppy = _number(_value((data.get("inputs") or {}).get("periods_per_year")))
    if sig.get("status") != "MEASURED" or n is None:
        finding = _say(
            locale,
            "No hay suficientes datos para medir si el resultado supera al azar.",
            "There is not enough data to measure whether the result beats chance.",
            "Não há dados suficientes para medir se o resultado supera o acaso.",
        )
        return finding, [FLAG_HINTS["TOO_FEW_OBSERVATIONS"][locale]]
    if psr is not None and need is not None and need > NEED_CAP * n:
        # Hundreds of years of history is not an ask anyone can meet: say so plainly.
        finding = _say(
            locale,
            f"PSR {_fmt(psr, 3)} con {n:.0f} observaciones. Con el mismo comportamiento, ni "
            f"con {NEED_CAP} veces más historial llegaría a 0.95: con estos datos el resultado "
            "no se distingue del azar.",
            f"PSR {_fmt(psr, 3)} with {n:.0f} observations. With the same behaviour, not even "
            f"{NEED_CAP} times more history would take it to 0.95: on this data the result "
            "cannot be told apart from chance.",
            f"PSR {_fmt(psr, 3)} com {n:.0f} observações. Com o mesmo comportamento, nem com "
            f"{NEED_CAP} vezes mais histórico chegaria a 0.95: com estes dados o resultado não "
            "se distingue do acaso.",
        )
    elif psr is not None and need is not None and need > n:
        extra = need - n
        span = _duration(extra, ppy, locale)
        span_text = f" ({span})" if span else ""
        finding = _say(
            locale,
            f"PSR {_fmt(psr, 3)} con {n:.0f} observaciones. Con el mismo comportamiento, "
            f"llegaría a 0.95 con unas {math.ceil(need):,} observaciones: faltan "
            f"{math.ceil(extra):,}{span_text}.",
            f"PSR {_fmt(psr, 3)} with {n:.0f} observations. With the same behaviour it "
            f"would reach 0.95 at about {math.ceil(need):,} observations: "
            f"{math.ceil(extra):,} more{span_text}.",
            f"PSR {_fmt(psr, 3)} com {n:.0f} observações. Com o mesmo comportamento, "
            f"chegaria a 0.95 com cerca de {math.ceil(need):,} observações: faltam "
            f"{math.ceil(extra):,}{span_text}.",
        )
    else:
        band = (data.get("bootstrap") or {}).get("sharpe_per_period") or {}
        p5 = _number(_value(band.get("p5")))
        p5_text = f" ({_fmt(p5, 3)})" if p5 is not None else ""
        finding = _say(
            locale,
            f"El PSR es {_fmt(psr or 0.0, 3)}, pero el percentil 5 del Sharpe en el bootstrap"
            f"{p5_text} no queda por encima de cero.",
            f"PSR is {_fmt(psr or 0.0, 3)}, but the bootstrap's 5th-percentile Sharpe"
            f"{p5_text} is not above zero.",
            f"O PSR é {_fmt(psr or 0.0, 3)}, mas o percentil 5 do Sharpe no bootstrap"
            f"{p5_text} não fica acima de zero.",
        )
    if (data.get("fund") or {}).get("track_record"):
        # A fund's record has no parameters or demo account: more of it is the
        # manager's full history, or the months still to come.
        return finding, _say(
            locale,
            [
                "Pide al gestor el historial completo del fondo desde su inicio, sin años "
                "recortados.",
                "Vuelve a auditarlo cuando el fondo publique más meses: cada mes nuevo cuenta "
                "como datos que nadie eligió de antemano.",
            ],
            [
                "Ask the manager for the fund's full record since inception, with no years "
                "left out.",
                "Audit it again once the fund publishes more months: each new month counts as "
                "data nobody picked in advance.",
            ],
            [
                "Peça ao gestor o histórico completo do fundo desde o início, sem anos "
                "cortados.",
                "Audite de novo quando o fundo publicar mais meses: cada mês novo conta como "
                "dados que ninguém escolheu de antemão.",
            ],
        )
    actions = _say(
        locale,
        [
            "Sube un periodo más largo del mismo sistema, sin cambiar parámetros.",
            "Mejor aún, añade historial de cuenta demo posterior al backtest: cuenta como "
            "datos que el optimizador nunca vio.",
        ],
        [
            "Upload a longer period of the same system, with unchanged parameters.",
            "Better still, add demo-account history from after the backtest: it counts as "
            "data the optimiser never saw.",
        ],
        [
            "Envie um período mais longo do mesmo sistema, sem mudar parâmetros.",
            "Melhor ainda, adicione histórico de conta demo posterior ao backtest: conta como "
            "dados que o otimizador nunca viu.",
        ],
    )
    return finding, actions


def _multiplicity_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    mult = data.get("multiplicity") or {}
    if status == "NOT_MEASURED" or mult.get("status") != "MEASURED":
        finding = _say(
            locale,
            "Se calcula en cuanto la significación sea medible: el paso de historial lo resuelve.",
            "It is computed once significance is measurable: the history step solves it.",
            "É calculado assim que a significância for mensurável: a etapa de histórico resolve "
            "isso.",
        )
        return finding, []
    trials = _number(_value(mult.get("trials_used"))) or 1.0
    dsr = _number(_value(mult.get("dsr_at_trials_used")))
    half = _number(_value(mult.get("trials_to_half")))
    pbo = _number(_value((data.get("cscv") or {}).get("pbo")))
    parts = []
    if dsr is not None:
        parts.append(
            _say(
                locale,
                f"DSR {_fmt(dsr, 3)} con {trials:.0f} {'intento' if trials == 1 else 'intentos'}; "
                "supera con 0.95 o más, y por debajo de 0.5 no supera.",
                f"DSR {_fmt(dsr, 3)} at {trials:.0f} {'trial' if trials == 1 else 'trials'}; "
                "it passes at 0.95 or more and fails below 0.5.",
                f"DSR {_fmt(dsr, 3)} com {trials:.0f} "
                f"{'tentativa' if trials == 1 else 'tentativas'}; "
                "passa com 0.95 ou mais e, abaixo de 0.5, não passa.",
            )
        )
    if half is not None and _fund_record(data):
        parts.append(
            _say(
                locale,
                f"Con {half:.0f} o más fondos o estrategias del mismo gestor cae por debajo "
                "de 0.5.",
                f"With {half:.0f} or more funds or strategies from the same manager it falls "
                "below 0.5.",
                f"Com {half:.0f} ou mais fundos ou estratégias do mesmo gestor cai abaixo de 0.5.",
            )
        )
    elif half is not None:
        parts.append(
            _say(
                locale,
                f"Con {half:.0f} o más configuraciones probadas cae por debajo de 0.5.",
                f"With {half:.0f} or more configurations tried it falls below 0.5.",
                f"Com {half:.0f} ou mais configurações testadas cai abaixo de 0.5.",
            )
        )
    if pbo is not None and pbo >= 0.5:
        parts.append(
            _say(
                locale,
                f"PBO {_fmt(pbo, 2)}: la mejor configuración dentro de muestra suele quedar por "
                "debajo de la mediana fuera de muestra.",
                f"PBO {_fmt(pbo, 2)}: the best in-sample configuration tends to land below "
                "the median out of sample.",
                f"PBO {_fmt(pbo, 2)}: a melhor configuração dentro da amostra costuma ficar "
                "abaixo da mediana fora da amostra.",
            )
        )
    counted = (mult.get("trials_used") or {}).get("evidence") == "MEASURED"
    if _fund_record(data):
        # A fund has no optimisation to export: its trials are the other funds
        # and strategies the same manager runs or has closed.
        return " ".join(parts), _say(
            locale,
            [
                "Pregunta al gestor cuántos fondos o estrategias lleva o ha cerrado y decláralo "
                "como número de intentos: un buen historial entre muchos pesa menos.",
            ],
            [
                "Ask the manager how many funds or strategies they run or have closed and "
                "declare it as the number of trials: one good record among many weighs less.",
            ],
            [
                "Pergunte ao gestor quantos fundos ou estratégias administra ou já encerrou e "
                "declare isso como número de tentativas: um bom histórico entre muitos pesa "
                "menos.",
            ],
        )
    if not counted:
        upload = _say(
            locale,
            "Sube el XML de la optimización de MT5 o la matriz de variantes: el número de "
            "intentos pasa a ser medido y se calcula el PBO.",
            "Upload the MT5 optimisation XML or the variants matrix: the trial count "
            "becomes measured and the PBO is computed.",
            "Envie o XML da otimização do MT5 ou a matriz de variantes: o número de "
            "tentativas passa a ser medido e o PBO é calculado.",
        )
    elif pbo is None:
        # The optimisation export gave the count; only the variants' own histories
        # give the PBO.
        upload = _say(
            locale,
            "El número de intentos ya sale de tus archivos; la matriz de variantes (el "
            "resultado de cada configuración a lo largo del tiempo) añadiría el PBO.",
            "The trial count already comes from your files; the variants matrix (each "
            "configuration's results over time) would add the PBO.",
            "O número de tentativas já sai dos seus arquivos; a matriz de variantes (o "
            "resultado de cada configuração ao longo do tempo) acrescentaria o PBO.",
        )
    else:
        upload = ""
    actions = [
        *([upload] if upload else []),
        *_say(
            locale,
            [
                "Menos parámetros y rangos más cortos reducen el número de intentos.",
                "Valida la configuración elegida en un tramo que no se usó al optimizar.",
            ],
            [
                "Fewer parameters and narrower ranges mean fewer trials.",
                "Validate the chosen configuration on a stretch not used while optimising.",
            ],
            [
                "Menos parâmetros e faixas mais curtas reduzem o número de tentativas.",
                "Valide a configuração escolhida em um trecho que não foi usado na otimização.",
            ],
        ),
    ]
    return " ".join(parts), actions


def _costs_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    costs = data.get("costs") or {}
    if (status == "NOT_MEASURED" or costs.get("status") != "MEASURED") and _fund_record(data):
        return _fund_costs(locale)
    if status == "NOT_MEASURED" or costs.get("status") != "MEASURED":
        finding = _say(
            locale,
            "Sin la lista de operaciones no se pueden volver a aplicar los costes; sin ellas la "
            "mejor clase posible es B.",
            "Without the list of trades the costs cannot be re-applied; without them the "
            "best possible class is B.",
            "Sem a lista de operações não é possível reaplicar os custos; sem elas a "
            "melhor classe possível é B.",
        )
        action = _say(
            locale,
            "Sube el informe de la plataforma (MT5, MT4, TradingView...) o el CSV de "
            "operaciones cerradas.",
            "Upload the platform report (MT5, MT4, TradingView...) or the closed-trades CSV.",
            "Envie o relatório da plataforma (MT5, MT4, TradingView...) ou o CSV de "
            "operações fechadas.",
        )
        return finding, [action]
    breakeven = _number(_value(costs.get("break_even_bps")))
    reference = _number(_value(costs.get("reference_bps"))) or 0.0
    needed = reference * 3.0
    pips = _number(_value(costs.get("break_even_pips")))
    reference_pips = _number(_value(costs.get("reference_pips")))
    pair = str(costs.get("pip_symbol") or "")
    if breakeven is None or breakeven <= 0:
        finding = _say(
            locale,
            "Incluso sin coste extra, el neto de las operaciones no queda por encima de cero "
            "tras las comisiones y el swap del archivo.",
            "Even with no extra cost, the trades do not net above zero after the "
            "commission and swap in the file.",
            "Mesmo sem custo extra, o líquido das operações não fica acima de zero "
            "após as comissões e o swap do arquivo.",
        )
    else:
        finding = _say(
            locale,
            f"El neto llega a cero con {_fmt(breakeven)} pb por lado de coste extra. Para "
            f"pasar esta dimensión tiene que seguir por encima de cero a 3x la referencia "
            f"({_fmt(needed)} pb por lado).",
            f"The net reaches zero at {_fmt(breakeven)} bps per side of extra cost. To "
            f"pass this dimension it has to stay above zero at 3x the reference "
            f"({_fmt(needed)} bps per side).",
            f"O líquido chega a zero com {_fmt(breakeven)} pb por lado de custo extra. Para "
            f"passar nesta dimensão, precisa continuar acima de zero a 3x a referência "
            f"({_fmt(needed)} pb por lado).",
        )
        if pips is not None and reference_pips is not None and pair:
            finding += _say(
                locale,
                f" En {pair}: {_fmt(pips)} pips por lado; el mínimo para pasar son "
                f"{_fmt(reference_pips * 3.0)} pips.",
                f" On {pair}: {_fmt(pips)} pips per side; passing needs "
                f"{_fmt(reference_pips * 3.0)} pips.",
                f" Em {pair}: {_fmt(pips)} pips por lado; o mínimo para passar são "
                f"{_fmt(reference_pips * 3.0)} pips.",
            )
    broker = (
        _say(
            locale,
            f"Compara ese margen con el spread y el deslizamiento reales de tu bróker en {pair}.",
            f"Compare that margin with your broker's real spread and slippage on {pair}.",
            f"Compare essa margem com o spread e o slippage reais da sua corretora em {pair}.",
        )
        if pips is not None and pair
        else _say(
            locale,
            "Compara ese margen con el spread y el deslizamiento reales de tu bróker: en "
            "EURUSD a 1.10, 1 pb por lado son unos 1.1 pips.",
            "Compare that margin with your broker's real spread and slippage: on EURUSD "
            "at 1.10, 1 bp per side is about 1.1 pips.",
            "Compare essa margem com o spread e o slippage reais da sua corretora: em "
            "EURUSD a 1.10, 1 pb por lado são cerca de 1.1 pips.",
        )
    )
    actions = _say(
        locale,
        [
            broker,
            "Declara el coste real por lado al subir: se suma a lo que el informe ya detalla.",
            "Menos operaciones o un recorrido mayor por operación hacen que el coste pese menos.",
        ],
        [
            broker,
            "Declare the real cost per side when uploading: it is added to what the report "
            "already itemises.",
            "Fewer trades or a larger move per trade make costs weigh less.",
        ],
        [
            broker,
            "Declare o custo real por lado ao enviar: ele se soma ao que o relatório já detalha.",
            "Menos operações ou um percurso maior por operação fazem o custo pesar menos.",
        ],
    )
    return finding, actions


def _account_oos(locale: str) -> tuple[str, list[str]]:
    """The out-of-sample step for an account history, which has no optimisation date."""
    finding = _say(
        locale,
        "El historial no dice desde qué fecha el robot opera sin cambios de configuración: "
        "sin esa fecha la mejor clase posible es B.",
        "The history does not say since when the robot has run with unchanged "
        "settings: without that date the best possible class is B.",
        "O histórico não diz desde que data o robô opera sem mudanças de configuração: "
        "sem essa data a melhor classe possível é B.",
    )
    actions = _say(
        locale,
        [
            "Pregunta al proveedor desde qué fecha no cambió la configuración y decláralo como "
            "inicio fuera de muestra: lo posterior se mide como datos nuevos.",
            "Pide el backtest del mismo robot y súbelo junto a la cuenta: el informe compara "
            "las dos operación por operación.",
        ],
        [
            "Ask the provider since when the settings have not changed and declare it as the "
            "out-of-sample start: what follows is measured as unseen data.",
            "Ask for the backtest of the same robot and upload it with the account: the "
            "report compares the two trade by trade.",
        ],
        [
            "Pergunte ao fornecedor desde que data a configuração não mudou e declare-a como "
            "início fora da amostra: o que vem depois é medido como dados novos.",
            "Peça o backtest do mesmo robô e envie-o junto com a conta: o relatório compara "
            "os dois operação por operação.",
        ],
    )
    return finding, actions


def _fund_oos(locale: str) -> tuple[str, list[str]]:
    """The out-of-sample step for a fund's track record, which has no optimisation date."""
    finding = _say(
        locale,
        "El historial del fondo no dice desde cuándo el gestor aplica el mismo proceso ni si "
        "algún tramo es simulado: sin esa fecha la mejor clase posible es B.",
        "The fund's record does not say since when the manager has applied the same process, "
        "or whether any stretch is simulated: without that date the best possible class is B.",
        "O histórico do fundo não diz desde quando o gestor aplica o mesmo processo nem se "
        "algum trecho é simulado: sem essa data a melhor classe possível é B.",
    )
    actions = _say(
        locale,
        [
            "Pregunta al gestor desde qué fecha no cambió el proceso de inversión y si algún "
            "tramo es simulado (pro forma); declara esa fecha como inicio fuera de muestra: lo "
            "posterior se mide como datos nuevos.",
        ],
        [
            "Ask the manager since when the investment process has not changed and whether "
            "any stretch is simulated (pro forma); declare that date as the out-of-sample "
            "start: what follows is measured as unseen data.",
        ],
        [
            "Pergunte ao gestor desde que data o processo de investimento não mudou e se algum "
            "trecho é simulado (pro forma); declare essa data como início fora da amostra: o "
            "que vem depois é medido como dados novos.",
        ],
    )
    return finding, actions


def _fund_costs(locale: str) -> tuple[str, list[str]]:
    """The cost step for a fund's track record, whose costs are inside each month."""
    finding = _say(
        locale,
        "Un historial mensual de fondo ya trae sus costes de operación dentro de cada mes, "
        "pero sin la lista de operaciones no se pueden volver a aplicar: la mejor clase "
        "posible es B.",
        "A fund's monthly record already carries its trading costs inside each month, but "
        "without the list of trades they cannot be re-applied: the best possible class is B.",
        "O histórico mensal de um fundo já traz os seus custos de operação dentro de cada "
        "mês, mas sem a lista de operações não é possível reaplicá-los: a melhor classe "
        "possível é B.",
    )
    action = _say(
        locale,
        "Confirma con el gestor si las cifras son netas de las comisiones de gestión y de "
        "éxito, y decláralo: el informe muestra cuánto pesan las comisiones.",
        "Confirm with the manager whether the figures are net of the management and "
        "performance fees, and declare it: the report shows how much the fees weigh.",
        "Confirme com o gestor se os números são líquidos das taxas de administração e de "
        "performance, e declare isso: o relatório mostra quanto pesam as taxas.",
    )
    return finding, [action]


def _oos_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    hold = data.get("holdout") or {}
    inputs = data.get("inputs") or {}
    if status == "NOT_MEASURED":
        reason = str(hold.get("reason", ""))
        if "fewer than" in reason:
            finding = _say(
                locale,
                f"Uno de los dos tramos tiene menos de {HOLDOUT_MIN_OBSERVATIONS} retornos: mueve "
                "la fecha para que ambos lados tengan al menos esa cantidad.",
                f"One of the two stretches has fewer than {HOLDOUT_MIN_OBSERVATIONS} "
                "returns: move the date so that both sides have at least that many.",
                f"Um dos dois trechos tem menos de {HOLDOUT_MIN_OBSERVATIONS} retornos: mova "
                "a data para que os dois lados tenham pelo menos essa quantidade.",
            )
        elif "outside" in reason:
            finding = _say(
                locale,
                f"La fecha declarada cae fuera de la serie ({inputs.get('first_timestamp', '')} "
                f"→ {inputs.get('last_timestamp', '')}).",
                f"The declared date lies outside the series "
                f"({inputs.get('first_timestamp', '')} → {inputs.get('last_timestamp', '')}).",
                f"A data declarada cai fora da série "
                f"({inputs.get('first_timestamp', '')} → {inputs.get('last_timestamp', '')}).",
            )
        elif is_account_history(data):
            return _account_oos(locale)
        elif reason == FUND_OOS_REASON:
            return _fund_oos(locale)
        else:
            finding = _say(
                locale,
                "No se declaró un tramo fuera de muestra: sin él la mejor clase posible es B.",
                "No out-of-sample stretch was declared: without it the best possible class is B.",
                "Não foi declarado um trecho fora da amostra: sem ele a melhor classe possível "
                "é B.",
            )
        actions = _say(
            locale,
            [
                "Declara la fecha en que terminó la optimización: lo posterior se mide como "
                "fuera de muestra y queda sellado en el informe.",
                "Mejor aún, corre el EA sin cambios en un periodo posterior y sube ese "
                "informe con la fecha de corte.",
            ],
            [
                "Declare the date the optimisation ended: what follows is measured out of "
                "sample and sealed in the report.",
                "Better still, run the EA unchanged on a later period and upload that report "
                "with the cut-off date.",
            ],
            [
                "Declare a data em que a otimização terminou: o que vem depois é medido como "
                "fora da amostra e fica selado no relatório.",
                "Melhor ainda, rode o EA sem mudanças em um período posterior e envie esse "
                "relatório com a data de corte.",
            ],
        )
        return finding, actions
    oos = _number(_value((hold.get("out_of_sample") or {}).get("sharpe_annualised")))
    gap = _number(_value(hold.get("gap")))
    parts = []
    if oos is not None:
        parts.append(
            _say(
                locale,
                f"Sharpe fuera de muestra {_fmt(oos)}; hace falta 0.5 o más "
                f"({'cumple' if oos >= 0.5 else 'no cumple'}).",
                f"Out-of-sample Sharpe {_fmt(oos)}; 0.5 or more is needed "
                f"({'met' if oos >= 0.5 else 'not met'}).",
                f"Sharpe fora da amostra {_fmt(oos)}; é preciso 0.5 ou mais "
                f"({'cumpre' if oos >= 0.5 else 'não cumpre'}).",
            )
        )
    if gap is not None:
        parts.append(
            _say(
                locale,
                f"Diferencia dentro/fuera {_fmt(gap)}; el máximo es 1.0 "
                f"({'cumple' if gap <= 1.0 else 'no cumple'}).",
                f"In/out gap {_fmt(gap)}; the maximum is 1.0 "
                f"({'met' if gap <= 1.0 else 'not met'}).",
                f"Diferença dentro/fora {_fmt(gap)}; o máximo é 1.0 "
                f"({'cumpre' if gap <= 1.0 else 'não cumpre'}).",
            )
        )
    actions = _say(
        locale,
        [
            "Una caída fuerte fuera de muestra aparece a menudo cuando se ajustaron demasiados "
            "parámetros: menos parámetros y una nueva validación en datos no vistos.",
        ],
        [
            "A sharp drop out of sample often appears when too many parameters were tuned: "
            "fewer parameters and a fresh validation on unseen data.",
        ],
        [
            "Uma queda forte fora da amostra aparece com frequência quando se ajustaram "
            "parâmetros demais: menos parâmetros e uma nova validação em dados não vistos.",
        ],
    )
    return " ".join(parts), actions


def _benchmark_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    bench = data.get("benchmark") or {}
    if status == "NOT_MEASURED" and _fund_record(data):
        finding = _say(
            locale,
            "No hay un índice con el que comparar el fondo.",
            "There is no index to compare the fund with.",
            "Não há um índice com o qual comparar o fundo.",
        )
        actions = _say(
            locale,
            [
                "Añade al archivo los meses del índice que el fondo declara como referencia (el "
                "de su folleto o ficha), o súbelo como archivo de benchmark.",
            ],
            [
                "Add the months of the index the fund names as its benchmark (the one in its "
                "prospectus or factsheet) to the file, or upload it as a benchmark file.",
            ],
            [
                "Acrescente ao arquivo os meses do índice que o fundo declara como referência (o "
                "do seu prospecto ou lâmina), ou envie-o como arquivo de benchmark.",
            ],
        )
        return finding, actions
    if status == "NOT_MEASURED":
        finding = _say(
            locale,
            "No se subió una referencia con la que comparar.",
            "No reference was uploaded to compare against.",
            "Não foi enviada uma referência para comparar.",
        )
        actions = _say(
            locale,
            [
                "Sube la curva de una alternativa pasiva: comprar y mantener el mismo activo o "
                "un índice, con las mismas fechas.",
                "Si no existe una alternativa pasiva comparable (por ejemplo, un EA de forex), "
                "declara que no aplica: la clase A lo admite.",
            ],
            [
                "Upload the curve of a passive alternative: buy-and-hold of the same asset or "
                "an index, over the same dates.",
                "If no comparable passive alternative exists (a forex EA, say), declare it "
                "not applicable: class A allows that.",
            ],
            [
                "Envie a curva de uma alternativa passiva: comprar e manter o mesmo ativo ou "
                "um índice, com as mesmas datas.",
                "Se não existe uma alternativa passiva comparável (por exemplo, um EA de forex), "
                "declare que não se aplica: a classe A admite isso.",
            ],
        )
        return finding, actions
    excess = _number(_value(bench.get("excess_return")))
    ratio = _number(_value(bench.get("drawdown_ratio")))
    parts = []
    if bench.get("source") == "file":
        parts.append(
            _say(
                locale,
                "La referencia es el índice que trae el propio archivo.",
                "The reference is the index the file itself carries.",
                "A referência é o índice que o próprio arquivo traz.",
            )
        )
    if excess is not None:
        parts.append(
            _say(
                locale,
                f"Exceso sobre la referencia {excess:+.1%}.",
                f"Excess over the reference {excess:+.1%}.",
                f"Excesso sobre a referência {excess:+.1%}.",
            )
        )
    if ratio is not None:
        parts.append(
            _say(
                locale,
                f"Drawdown {_fmt(ratio)} veces el de la referencia; el máximo es 1.0.",
                f"Drawdown {_fmt(ratio)} times the reference's; the maximum is 1.0.",
                f"Drawdown {_fmt(ratio)} vezes o da referência; o máximo é 1.0.",
            )
        )
    actions = _say(
        locale,
        ["Comprueba que la referencia es tu alternativa real, con las mismas fechas."],
        ["Check that the reference is your real alternative, over the same dates."],
        ["Confira se a referência é a sua alternativa real, com as mesmas datas."],
    )
    return " ".join(parts), actions


def _data_quality_step(data: dict[str, Any], status: str, locale: str) -> tuple[str, list[str]]:
    flags = sorted(
        data.get("red_flags") or [], key=lambda flag: 0 if flag.get("severity") == "FAIL" else 1
    )
    fails = sum(1 for flag in flags if flag.get("severity") == "FAIL")
    warns = len(flags) - fails
    finding = _say(
        locale,
        f"{_plural(fails, 'bandera grave', 'banderas graves')} y "
        f"{_plural(warns, 'aviso', 'avisos')} en los datos.",
        f"{_plural(fails, 'serious flag', 'serious flags')} and "
        f"{_plural(warns, 'warning', 'warnings')} in the data.",
        f"{_plural(fails, 'sinal grave', 'sinais graves')} e "
        f"{_plural(warns, 'aviso', 'avisos')} nos dados.",
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
    locale = locale if locale in ("en", "pt") else "es"
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
                title=(
                    FUND_TITLES[locale].get(name, TITLES[locale][name])
                    if _fund_record(data)
                    else ACCOUNT_TITLES[locale].get(name, TITLES[locale][name])
                    if is_account_history(data)
                    else TITLES[locale][name]
                ),
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


# The Portuguese of the tables above, over their English (see ``report_pt``).
report_pt.install(globals(), report_pt.PLAN)

__all__ = ["FLAG_HINTS", "PLAN_ORDER", "PlanStep", "TITLES", "improvement_plan"]
