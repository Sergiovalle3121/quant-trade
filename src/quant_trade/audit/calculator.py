"""The public luck calculator: how much of a Sharpe the search could explain.

A visitor types three numbers they already know (the annualised Sharpe of a
backtest, how many years it covers and how many configurations were tried)
and gets the same three figures the report's luck section shows
(``audit/luck.py``): the Sharpe the best of that many unskilled tries would
show, the Sharpe left after the Bonferroni haircut, and the years of history
at which that luck falls below the observed Sharpe.

There is no file, so the calculator assumes what the report measures: returns
at the declared frequency, with no skew and normal tails. Every input is the
visitor's own claim, labelled Declared on the page, and every output is
computed from it. Nothing is stored. The page needs no account and links to
the upload form, where the same figures come from the real returns.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from quant_trade.audit.engine import sharpe_sampling_variance
from quant_trade.audit.luck import luck_review

#: The page's path in each language.
CALCULATOR_PATH: dict[str, str] = {
    "es": "/calculadora",
    "en": "/calculator",
    "pt": "/pt/calculadora",
}

#: Daily returns, as most strategy testers export.
PERIODS_PER_YEAR = 252.0
SUPPORTED_PERIODS_PER_YEAR = (252, 52, 12)
#: Normal returns: no skew, kurtosis 3. Fat tails and negative skew widen
#: the Sharpe's spread, so the real figure is usually worse than this one.
SKEW = 0.0
KURTOSIS = 3.0

#: Input bounds. Outside them the form says so instead of computing.
SHARPE_RANGE = (0.05, 10.0)
YEARS_RANGE = (0.1, 50.0)
TRIALS_RANGE = (1, 10_000_000)

#: The query fields that determine a result's share card, in cache-key order.
CARD_FIELDS = ("sharpe", "years", "trials", "periods_per_year")
#: Card renders per address and sliding hour, the reader's own limit. The page
#: itself is never refused: past the limit it keeps the static preview.
CARD_REQUESTS_PER_HOUR = 60


def calculator_url(locale: str) -> str:
    return CALCULATOR_PATH.get(locale, CALCULATOR_PATH["es"])


@dataclass(frozen=True)
class CalculatorInput:
    sharpe: float
    years: float
    trials: int
    periods_per_year: float = PERIODS_PER_YEAR


#: Digit groups of three after a dot or a comma: "1.000" and "12.500" as typed
#: in Spanish or Portuguese, "1,000" in English. Trials count whole
#: configurations, so such a separator is never a decimal point here.
_THOUSANDS = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
_SPACES = (" ", "\u00a0", "\u202f")  # space, no-break space, narrow no-break


def _trial_count(raw: Any) -> int:
    """A whole number of trials from what someone typed.

    "1.000", "1,000" and "1 000" are a thousand (before, "1.000" read as 1 and
    "1,5" as 15). A count with a fraction ("1,5", "12.5") is not a number of
    configurations: ``ValueError``. Past float's range ``int`` raises
    ``OverflowError``, which :func:`read_input` turns into ``error_number``."""
    text = str(raw).strip()
    for space in _SPACES:
        text = text.replace(space, "")
    if _THOUSANDS.fullmatch(text):
        return int(re.sub(r"[.,]", "", text))
    value = float(text.replace(",", "."))
    if math.isfinite(value) and not value.is_integer():
        raise ValueError("a trial count is a whole number")
    return int(value)


def parse_input(
    sharpe: str | None,
    years: str | None,
    trials: str | None,
    periods_per_year: str | None = None,
) -> CalculatorInput | str | None:
    """The three fields as numbers, ``None`` when the form is empty, or the
    key of the error to show when a field is missing or out of range."""
    if not any((sharpe, years, trials)):
        return None
    try:
        sr = float(str(sharpe).replace(",", "."))
        yrs = float(str(years).replace(",", "."))
        n = _trial_count(trials)
    except (TypeError, ValueError):
        return "error_number"
    if not all(math.isfinite(v) for v in (sr, yrs)):
        return "error_number"
    if not SHARPE_RANGE[0] <= sr <= SHARPE_RANGE[1]:
        return "error_sharpe"
    if not YEARS_RANGE[0] <= yrs <= YEARS_RANGE[1]:
        return "error_years"
    if not TRIALS_RANGE[0] <= n <= TRIALS_RANGE[1]:
        return "error_trials"
    try:
        frequency = float(periods_per_year) if periods_per_year is not None else PERIODS_PER_YEAR
    except (TypeError, ValueError):
        return "error_frequency"
    if frequency not in SUPPORTED_PERIODS_PER_YEAR:
        return "error_frequency"
    return CalculatorInput(sharpe=sr, years=yrs, trials=n, periods_per_year=frequency)


def read_input(
    sharpe: str | None,
    years: str | None,
    trials: str | None,
    periods_per_year: str | None = None,
) -> CalculatorInput | str | None:
    """``parse_input`` for values anyone can type into the address bar.

    A trial count past float's range (``inf``, ``1e999``, hundreds of digits)
    overflows ``int``: it is a bad number like any other, so the page shows
    ``error_number`` and ``card.png`` answers 404 instead of a 500.
    """
    try:
        return parse_input(sharpe, years, trials, periods_per_year)
    except OverflowError:
        return "error_number"


def share_values(value: CalculatorInput) -> dict[str, str]:
    """The validated inputs as query strings that parse back to the same numbers.

    ``repr`` of a float round-trips exactly, so a shared link reproduces the
    validated input, and "1.8" and "1.80" share one card in the cache.
    """
    return {
        "sharpe": repr(value.sharpe),
        "years": repr(value.years),
        "trials": str(value.trials),
        "periods_per_year": str(int(value.periods_per_year)),
    }


def share_url(locale: str, value: CalculatorInput) -> str:
    """The page's own address for a result, tagged so /panel counts the shares."""
    return calculator_url(locale) + "?" + urlencode({**share_values(value), "ref": "calculadora"})


def compute(value: CalculatorInput) -> dict[str, Any]:
    """The luck section's figures for the declared Sharpe, span and search."""
    if value.periods_per_year not in SUPPORTED_PERIODS_PER_YEAR:
        raise ValueError("unsupported return frequency")
    observations = max(2, round(value.years * value.periods_per_year))
    per_period = value.sharpe / math.sqrt(value.periods_per_year)
    variance = sharpe_sampling_variance(per_period, SKEW, KURTOSIS, observations)
    return luck_review(
        {"sharpe_per_period": per_period, "observations": observations},
        trials=value.trials,
        trials_source="declared",
        sharpe_variance=variance,
        periods_per_year=value.periods_per_year,
        span_years=value.years,
    )


COPY: dict[str, dict[str, Any]] = {
    "es": {
        "nav": "Calculadora de suerte",
        "eyebrow": "Calculadora gratis",
        "title": "¿Ventaja o suerte? Calculadora de Sharpe deflactado",
        "summary": (
            "Escribe el Sharpe de tu backtest, sus años y cuántas configuraciones probaste: "
            "te decimos cuánto de ese Sharpe podría explicar la suerte. Sin registro."
        ),
        "form_title": "Tus números",
        "sharpe": "Sharpe anual del backtest",
        "sharpe_help": "El que muestra tu plataforma, anualizado. Por ejemplo 1,8.",
        "years": "Años de historial",
        "years_help": "Del primer al último día del backtest. Por ejemplo 3 o 0,5.",
        "frequency": "Frecuencia de los rendimientos",
        "frequency_help": "Usa la frecuencia de tu serie. Es una declaración, no una medición.",
        "frequency_options": {
            252: "Diaria · 252 periodos/año (DECLARED)",
            52: "Semanal · 52 periodos/año (DECLARED)",
            12: "Mensual · 12 periodos/año (DECLARED)",
        },
        "frequency_assumption": (
            "{frequency}. Se suponen rendimientos sin asimetría y con colas normales. Las colas "
            "gruesas y la asimetría negativa hacen que el resultado real sea más exigente."
        ),
        "trials": "Configuraciones probadas",
        "trials_help": (
            "Cada combinación de parámetros que corriste, cada versión que descartaste y cada "
            "pasada del optimizador. Si no lo sabes, pon tu mejor estimación; suele ser más de "
            "lo que uno cree."
        ),
        "submit": "Calcular",
        "result_title": "Resultado",
        "declared_note": (
            "Las cifras y la frecuencia de entrada son Declaradas: las escribiste tú y no "
            "vemos tu archivo."
        ),
        "luck": "Sharpe que daría la pura suerte con {n} configuraciones",
        "after": "Sharpe que queda después del descuento",
        "haircut": "Parte del Sharpe que se descuenta",
        "years_needed": "Años de historial para que la suerte quede por debajo de tu Sharpe",
        "beats": (
            "Tu Sharpe supera lo que daría la mejor de {n} pruebas sin ninguna ventaja. "
            "Es una condición necesaria, no suficiente: falta ver costos, fuera de muestra y "
            "calidad de datos."
        ),
        "loses": (
            "Tu Sharpe no supera lo que daría la mejor de {n} pruebas sin ninguna ventaja. "
            "Con estos números, no se distingue de haber elegido la mejor de muchas "
            "configuraciones al azar."
        ),
        "one_trial": (
            "Con una sola configuración no hay búsqueda que descontar. Así cambiaría si "
            "hubieras probado más:"
        ),
        "col_trials": "Configuraciones",
        "col_luck": "Sharpe de la suerte",
        "col_years": "Años necesarios",
        "not_measured": "No se puede calcular con estos números: {reason}.",
        "error_number": "Escribe los tres campos con números.",
        "error_sharpe": "El Sharpe debe estar entre 0,05 y 10.",
        "error_years": "Los años deben estar entre 0,1 y 50.",
        "error_trials": "Las configuraciones deben estar entre 1 y 10.000.000.",
        "error_frequency": "Elige una frecuencia diaria, semanal o mensual.",
        "cta_title": "Con tu archivo, las cifras son medidas",
        "cta": (
            "La calculadora usa la frecuencia que declaras y supone rendimientos normales. "
            "Tu archivo tiene "
            "asimetría, colas, costos y huecos de datos reales, y el informe los mide, junto "
            "con el número de pasadas del optimizador de MT5 cuando lo subes. Tu primer "
            "informe completo es gratis al crear cuenta."
        ),
        "cta_button": "Auditar mi archivo",
        "sample_link": "Ver un informe de ejemplo",
        "read_more": "Lee también:",
        "reader_link": "Crear una tarjeta de cifras para compartir",
        "share_title": "Compartir este resultado",
        "share_text": (
            "Mi Sharpe declarado frente a la suerte de las configuraciones probadas, calculado "
            "con Rigor. Esta tarjeta no es una auditoría. {url}"
        ),
        "card_title": "Rigor · calculadora de suerte",
        "card_limited": (
            "Demasiadas tarjetas de la calculadora desde esta dirección. "
            "Inténtalo de nuevo más tarde."
        ),
        # The reader's own notice, word for word: the link carries the figures.
        "card_public": (
            "El enlace compartido contiene las cifras que escribes; "
            "cualquiera con el enlace puede leerlas."
        ),
        "why_title": "Por qué la búsqueda importa",
        "why": [
            "Si pruebas 100 configuraciones sin ninguna ventaja real, la mejor de ellas casi "
            "siempre muestra un Sharpe alto. Es la que eliges y la que publicas.",
            "El Sharpe deflactado compara tu Sharpe con el que daría esa mejor de N al azar. "
            "Cuantas más configuraciones pruebas, más alto tiene que ser para contar.",
            "Más historial ayuda: la dispersión de la suerte baja con los años, así que un "
            "backtest más largo necesita menos Sharpe para superar la misma búsqueda.",
        ],
        "assumptions_title": "Supuestos y límites",
        "assumptions": [
            "Rendimientos diarios, 252 por año, sin asimetría y con colas normales. Las colas "
            "gruesas y la asimetría negativa hacen que el resultado real sea más exigente.",
            "Las configuraciones se tratan como pruebas independientes con la misma "
            "dispersión que la de tu Sharpe.",
            "Descuento de Harvey y Liu con corrección de Bonferroni; suerte esperada de Bailey "
            "y López de Prado; longitud mínima de Bailey, Borwein, López de Prado y Zhu.",
            "No guardamos lo que escribes. Es la misma fórmula que la sección de suerte del "
            "informe; el informe usa la frecuencia real de tu archivo.",
            "Describe el pasado que declaras; no dice nada del futuro.",
        ],
    },
    "en": {
        "nav": "Luck calculator",
        "eyebrow": "Free calculator",
        "title": "Deflated Sharpe ratio calculator",
        "summary": (
            "Explore the deflated Sharpe ratio using declared Sharpe, years of history and "
            "research attempts. Assumptions and limits are explicit."
        ),
        "form_title": "Your numbers",
        "sharpe": "Backtest annual Sharpe",
        "sharpe_help": "The one your platform shows, annualised. For example 1.8.",
        "years": "Years of history",
        "years_help": "From the backtest's first to its last day. For example 3 or 0.5.",
        "frequency": "Return frequency",
        "frequency_help": "Use your series frequency. This is a declaration, not a measurement.",
        "frequency_options": {
            252: "Daily · 252 periods/year (DECLARED)",
            52: "Weekly · 52 periods/year (DECLARED)",
            12: "Monthly · 12 periods/year (DECLARED)",
        },
        "frequency_assumption": (
            "{frequency}. Returns are assumed to have no skew and normal tails. Fat tails "
            "and negative skew make the real result stricter."
        ),
        "trials": "Configurations tried",
        "trials_help": (
            "Every parameter combination you ran, every version you dropped and every optimizer "
            "pass. If you don't know, give your best estimate; it is usually more than it seems."
        ),
        "submit": "Calculate",
        "result_title": "Result",
        "declared_note": (
            "The input figures and frequency are Declared: you typed them and we do not "
            "see your file."
        ),
        "luck": "Sharpe that pure luck would show with {n} configurations",
        "after": "Sharpe left after the haircut",
        "haircut": "Share of the Sharpe the haircut removes",
        "years_needed": "Years of history for luck to fall below your Sharpe",
        "beats": (
            "Your Sharpe beats what the best of {n} tries with no edge at all would show. "
            "That is necessary, not sufficient: costs, out-of-sample and data quality "
            "are still to check."
        ),
        "loses": (
            "Your Sharpe does not beat what the best of {n} tries with no edge at all would "
            "show. With these numbers it cannot be told apart from picking the best of many "
            "random configurations."
        ),
        "one_trial": (
            "With a single configuration there is no search to discount. Here is how it would "
            "change if you had tried more:"
        ),
        "col_trials": "Configurations",
        "col_luck": "Luck Sharpe",
        "col_years": "Years needed",
        "not_measured": "These numbers cannot be computed: {reason}.",
        "error_number": "Fill in all three fields with numbers.",
        "error_sharpe": "The Sharpe must be between 0.05 and 10.",
        "error_years": "The years must be between 0.1 and 50.",
        "error_trials": "The configurations must be between 1 and 10,000,000.",
        "error_frequency": "Choose a daily, weekly or monthly frequency.",
        "cta_title": "With your file, the figures are measured",
        "cta": (
            "The calculator uses your declared frequency and assumes normal returns. "
            "Your file has real skew, "
            "tails, costs and data gaps, and the report measures them, along with the number "
            "of MT5 optimizer passes when you upload it. Your first full report is free with "
            "an account."
        ),
        "cta_button": "Audit my file",
        "sample_link": "See a sample report",
        "read_more": "Read next:",
        "reader_link": "Create a shareable figures card",
        "share_title": "Share this result",
        "share_text": (
            "My declared Sharpe against the luck of the configurations tried, computed with "
            "Rigor. This card is not an audit. {url}"
        ),
        "card_title": "Rigor · luck calculator",
        "card_limited": "Too many calculator cards from this address. Try again later.",
        "card_public": (
            "The shared link contains the figures you enter; anyone with the link can read them."
        ),
        "why_title": "Why the search matters",
        "why": [
            "Try 100 configurations with no real edge and the best of them almost always shows "
            "a high Sharpe. That is the one you pick and the one you publish.",
            "The deflated Sharpe compares your Sharpe with the one the best of N random tries "
            "would show. The more configurations you try, the higher it must be to count.",
            "More history helps: the spread of luck shrinks with the years, so a longer "
            "backtest needs less Sharpe to beat the same search.",
        ],
        "assumptions_title": "Assumptions and limits",
        "assumptions": [
            "Daily returns, 252 a year, no skew and normal tails. Fat tails and negative skew "
            "make the real result stricter.",
            "Configurations are treated as independent tries with the same spread as your Sharpe.",
            "Harvey and Liu haircut with the Bonferroni correction; expected luck from Bailey "
            "and López de Prado; minimum length from Bailey, Borwein, López de Prado and Zhu.",
            "We do not store what you type. It is the same formula as the report's luck "
            "section; the report uses your file's actual frequency.",
            "It describes the past you declare; it says nothing about the future.",
        ],
    },
    "pt": {
        "nav": "Calculadora de sorte",
        "eyebrow": "Calculadora grátis",
        "title": "Vantagem ou sorte? Calculadora de Sharpe deflacionado",
        "summary": (
            "Digite o Sharpe do seu backtest, quantos anos ele cobre e quantas configurações "
            "você testou: veja quanto desse Sharpe a sorte poderia explicar. Sem cadastro."
        ),
        "form_title": "Seus números",
        "sharpe": "Sharpe anual do backtest",
        "sharpe_help": "O que a sua plataforma mostra, anualizado. Por exemplo 1,8.",
        "years": "Anos de histórico",
        "years_help": "Do primeiro ao último dia do backtest. Por exemplo 3 ou 0,5.",
        "frequency": "Frequência dos retornos",
        "frequency_help": "Use a frequência da sua série. É uma declaração, não uma medição.",
        "frequency_options": {
            252: "Diária · 252 períodos/ano (DECLARED)",
            52: "Semanal · 52 períodos/ano (DECLARED)",
            12: "Mensal · 12 períodos/ano (DECLARED)",
        },
        "frequency_assumption": (
            "{frequency}. Supõem-se retornos sem assimetria e com caudas normais. Caudas "
            "grossas e assimetria negativa tornam o resultado real mais exigente."
        ),
        "trials": "Configurações testadas",
        "trials_help": (
            "Cada combinação de parâmetros que você rodou, cada versão descartada e cada "
            "passagem do otimizador. Se não souber, dê a sua melhor estimativa; costuma ser "
            "mais do que parece."
        ),
        "submit": "Calcular",
        "result_title": "Resultado",
        "declared_note": (
            "Os números e a frequência de entrada são Declarados: você os digitou e não "
            "vemos o seu arquivo."
        ),
        "luck": "Sharpe que a pura sorte mostraria com {n} configurações",
        "after": "Sharpe que sobra depois do desconto",
        "haircut": "Parte do Sharpe que o desconto remove",
        "years_needed": "Anos de histórico para a sorte ficar abaixo do seu Sharpe",
        "beats": (
            "O seu Sharpe supera o que a melhor de {n} tentativas sem nenhuma vantagem "
            "mostraria. É uma condição necessária, não suficiente: faltam custos, fora da "
            "amostra e qualidade dos dados."
        ),
        "loses": (
            "O seu Sharpe não supera o que a melhor de {n} tentativas sem nenhuma vantagem "
            "mostraria. Com esses números, não se distingue de ter escolhido a melhor de "
            "muitas configurações ao acaso."
        ),
        "one_trial": (
            "Com uma só configuração não há busca a descontar. Veja como mudaria se você "
            "tivesse testado mais:"
        ),
        "col_trials": "Configurações",
        "col_luck": "Sharpe da sorte",
        "col_years": "Anos necessários",
        "not_measured": "Não é possível calcular com esses números: {reason}.",
        "error_number": "Preencha os três campos com números.",
        "error_sharpe": "O Sharpe deve estar entre 0,05 e 10.",
        "error_years": "Os anos devem estar entre 0,1 e 50.",
        "error_trials": "As configurações devem estar entre 1 e 10.000.000.",
        "error_frequency": "Escolha uma frequência diária, semanal ou mensal.",
        "cta_title": "Com o seu arquivo, os números são medidos",
        "cta": (
            "A calculadora usa a frequência que você declara e supõe retornos normais. "
            "O seu arquivo tem "
            "assimetria, caudas, custos e falhas de dados reais, e o relatório os mede, junto "
            "com o número de passagens do otimizador do MT5 quando você o envia. O seu "
            "primeiro relatório completo é grátis ao criar a conta."
        ),
        "cta_button": "Auditar meu arquivo",
        "sample_link": "Ver um relatório de exemplo",
        "read_more": "Leia também:",
        "reader_link": "Criar um cartão de números para compartilhar",
        "share_title": "Compartilhar este resultado",
        "share_text": (
            "Meu Sharpe declarado contra a sorte das configurações testadas, calculado com o "
            "Rigor. Este cartão não é uma auditoria. {url}"
        ),
        "card_title": "Rigor · calculadora de sorte",
        "card_limited": (
            "Cartões da calculadora demais a partir deste endereço. Tente novamente mais tarde."
        ),
        "card_public": (
            "O link compartilhado contém os números que você informa; "
            "qualquer pessoa com o link pode lê-los."
        ),
        "why_title": "Por que a busca importa",
        "why": [
            "Teste 100 configurações sem nenhuma vantagem real e a melhor delas quase sempre "
            "mostra um Sharpe alto. É a que você escolhe e a que você publica.",
            "O Sharpe deflacionado compara o seu Sharpe com o que a melhor de N tentativas ao "
            "acaso mostraria. Quanto mais configurações você testa, mais alto ele precisa ser.",
            "Mais histórico ajuda: a dispersão da sorte diminui com os anos, então um backtest "
            "mais longo precisa de menos Sharpe para superar a mesma busca.",
        ],
        "assumptions_title": "Suposições e limites",
        "assumptions": [
            "Retornos diários, 252 por ano, sem assimetria e com caudas normais. Caudas "
            "grossas e assimetria negativa tornam o resultado real mais exigente.",
            "As configurações são tratadas como tentativas independentes com a mesma "
            "dispersão do seu Sharpe.",
            "Desconto de Harvey e Liu com a correção de Bonferroni; sorte esperada de Bailey "
            "e López de Prado; comprimento mínimo de Bailey, Borwein, López de Prado e Zhu.",
            "Não guardamos o que você digita. É a mesma fórmula da seção de sorte do "
            "relatório; o relatório usa a frequência real do seu arquivo.",
            "Descreve o passado que você declara; não diz nada sobre o futuro.",
        ],
    },
}

#: The engine's not-measured reasons, in each page language.
REASONS: dict[str, dict[str, str]] = {
    "es": {
        "too short a history to discount": "el historial es demasiado corto para descontar",
    },
    "en": {},
    "pt": {
        "too short a history to discount": "o histórico é curto demais para descontar",
    },
}


def calculator_copy(locale: str, periods_per_year: float = PERIODS_PER_YEAR) -> dict[str, Any]:
    """Localised assumptions for the frequency actually used in the calculation."""
    if periods_per_year not in SUPPORTED_PERIODS_PER_YEAR:
        raise ValueError("unsupported return frequency")
    copy = dict(COPY.get(locale, COPY["es"]))
    assumption = copy["frequency_assumption"].format(
        frequency=copy["frequency_options"][periods_per_year]
    )
    copy["assumptions"] = [assumption, *copy["assumptions"][1:]]
    return copy


__all__ = [
    "CALCULATOR_PATH",
    "CARD_FIELDS",
    "CARD_REQUESTS_PER_HOUR",
    "COPY",
    "CalculatorInput",
    "calculator_copy",
    "calculator_url",
    "compute",
    "parse_input",
    "read_input",
    "share_url",
    "share_values",
]
