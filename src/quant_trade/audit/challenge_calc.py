"""The free prop-firm challenge calculator: declared figures, the report's simulator.

A visitor types what they already know about their trading (win rate,
average win and loss, trades per day) and picks a program from the
published presets (``prop_presets``). There is no file, so the page builds a
history of synthetic days from those figures, with a fixed seed, and runs the
report's own challenge simulator on it (``analytics.simulate_challenge``,
phase by phase, combined by ``firmfit.program_outcomes``): neither the
simulator nor the presets change here.

Every input is DECLARED and every result is computed from it, so the page
labels results the way the win-rate calculator does: Declared, computed from
the declared figures, or Not measured. Nothing is stored and no file, network
or database is touched. With the number of trades behind the win rate, the
same program is also run at the lower end of the win rate's 95 % Wilson
interval (``winrate.read``), which is the point of the page: with few trades
a 60 % win rate may really be much less.
"""

from __future__ import annotations

import inspect
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import numpy as np

from quant_trade.audit import firmfit, winrate
from quant_trade.audit.analytics import _day_limit, simulate_challenge
from quant_trade.audit.prop_presets import ACCOUNT_SIZES, PRESETS, ChallengeRules
from quant_trade.audit.public_card import PublicClaim

#: The page's path in each language.
CHALLENGE_PATH: dict[str, str] = {
    "es": "/calculadora-reto",
    "en": "/en/challenge-calculator",
    "pt": "/pt/calculadora-desafio",
}
#: One page per firm with a published preset: its path segment and its name in
#: ``prop_presets`` (``ChallengeRules.firm``), in the order the pages list them.
FIRMS: dict[str, str] = {
    "ftmo": "FTMO",
    "fundednext": "FundedNext",
    "the5ers": "The5ers",
    "topstep": "Topstep",
}
#: The query fields, in the order a shared link writes them.
FIELDS = ("win_rate", "unit", "avg_win", "avg_loss", "risk", "per_day", "trades", "program", "fee")
UNITS = ("pct", "r")
#: The funnel tag carried by a shared result (``funnel.REF_TAGS``).
SHARE_REF = "reto"
#: Synthetic days built from the declared figures; the simulator resamples them.
#: Their mix is fixed by the figures (``synthetic_daily_returns``); with this many,
#: how the seed orders them moves a probability about as much as the paths' own
#: sampling (about one point), where 1,000 days moved it by several.
SYNTHETIC_DAYS = 10_000
#: Paths per phase: ``firmfit.SAMPLES``, the firm table's own precision.
SAMPLES = firmfit.SAMPLES
#: One seed for the synthetic days and the resampling: the same link, the same figures.
SEED = 20261010
#: The sizes of the report's sizing table that the page shows.
SIZES = (0.5, 1.0, 2.0)
#: Computations per address and sliding hour; past it the page shows the form only.
REQUESTS_PER_HOUR = 120

#: Input bounds. Outside them the form says which field and why.
WIN_RATE_RANGE = (0.0, 100.0)  # both ends excluded
#: A single trade may win or lose at most this share of the balance.
MAX_TRADE_SHARE = 0.5
MAX_R = 100.0
RISK_RANGE = (0.0, 20.0)  # low end excluded
PER_DAY_RANGE = (0.1, 50.0)
TRADES_RANGE = (1, 10_000_000)
FEE_RANGE = (0.0, 100_000.0)  # low end excluded

_SPACES = (" ", " ", " ", " ")
#: Digit groups of three after a dot or a comma: "1.080" or "1,080" dollars, a
#: thousand and eighty, never one dollar and eight cents.
_THOUSANDS = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
_NUMBER = re.compile(r"-?(?:\d+(?:\.\d*)?|\.\d+)")


def _locale(locale: str) -> str:
    return locale if locale in CHALLENGE_PATH else "es"


def challenge_url(locale: str, firm: str = "") -> str:
    """The calculator's address in ``locale``; with ``firm``, that firm's page."""
    path = CHALLENGE_PATH[_locale(locale)]
    return f"{path}/{firm}" if firm else path


def page_paths(firm: str = "") -> dict[str, str]:
    """The page in every language, for canonical, hreflang and the sitemap."""
    return {locale: challenge_url(locale, firm) for locale in CHALLENGE_PATH}


#: Every page of the calculator by path: its language and firm ("" for the main page).
PAGES: dict[str, tuple[str, str]] = {
    challenge_url(locale, firm): (locale, firm)
    for firm in ("", *FIRMS)
    for locale in CHALLENGE_PATH
}


def _published(rules: ChallengeRules) -> bool:
    return rules.source_url.startswith("https://")


#: The programs a visitor can choose: the first phase of each published
#: (firm, program) in ``PRESETS`` order. The generic reference is not one.
PROGRAMS: tuple[str, ...] = tuple(
    dict.fromkeys(
        firmfit.program_keys(key)[0] for key, rules in PRESETS.items() if _published(rules)
    )
)


def firm_programs(firm: str = "") -> tuple[str, ...]:
    """The programs offered on a firm's page, or every program on the main page."""
    if not firm:
        return PROGRAMS
    name = FIRMS[firm]
    return tuple(key for key in PROGRAMS if PRESETS[key].firm == name)


def phase_count(key: str) -> int:
    """How many phases the program of ``key`` asks for (Bootcamp repeats one)."""
    return sum(firmfit.REPEATS.get(phase, 1) for phase in firmfit.program_keys(key))


#: The longest a phase runs without a time limit: ``simulate_challenge``'s own
#: ``max_days``, read from it so the page never states another horizon.
SIMULATOR_MAX_DAYS: int = inspect.signature(simulate_challenge).parameters["max_days"].default


def horizon(key: str) -> int:
    """Business days the simulator walks a phase of ``key`` (``horizon_business_days``)."""
    return _day_limit(PRESETS[key], SIMULATOR_MAX_DAYS)


@dataclass(frozen=True)
class ChallengeInput:
    """The declared figures, validated, as the visitor wrote them."""

    #: Win rate in percent, 0 < x < 100.
    win_rate_pct: float
    #: How the average win and loss are written: ``pct`` of the balance or ``r``.
    unit: str
    avg_win: float
    avg_loss: float
    #: Risk per trade in percent of the balance, only with ``unit == "r"``.
    risk: float | None
    per_day: float
    #: The program's first preset key (``PROGRAMS``).
    program: str
    #: Closed trades behind the win rate, when declared.
    trades: int | None = None
    #: The challenge fee in US dollars, when declared.
    fee: float | None = None

    @property
    def win_rate(self) -> float:
        return self.win_rate_pct / 100.0

    def _share(self, value: float) -> float:
        scale = (self.risk or 0.0) / 100.0 if self.unit == "r" else 0.01
        return value * scale

    @property
    def win(self) -> float:
        """A winning trade's gain, as a share of the balance."""
        return self._share(self.avg_win)

    @property
    def loss(self) -> float:
        """A losing trade's loss, as a share of the balance."""
        return self._share(self.avg_loss)


def _clean(raw: str) -> str:
    text = str(raw).strip()
    for space in _SPACES:
        text = text.replace(space, "")
    return text.removesuffix("%")


def _number(raw: str, *, money: bool = False) -> float:
    """A decimal from what someone typed: "0,8", "0.8", "1 000,5", "1.000,5".

    A comma alone is a decimal mark. With both marks, the last one is. In a
    money field a separator before groups of three digits is a thousands one.
    Anything else (``1_000``, ``nan``, ``1e5``) is ``ValueError``."""
    text = _clean(raw)
    if len(text) > 32:
        raise ValueError("number too long")
    if money and _THOUSANDS.fullmatch(text):
        return float(re.sub(r"[.,]", "", text))
    if "," in text and "." in text:
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        text = text.replace(thousands, "").replace(decimal, ".")
    else:
        text = text.replace(",", ".")
    if not _NUMBER.fullmatch(text):
        raise ValueError("not a number")
    value = float(text)
    if not math.isfinite(value):
        raise ValueError("not finite")
    return value


def _count(raw: str) -> int:
    """A whole number of trades: "40", "1.000", "1,000" or "1 000"."""
    text = _clean(raw)
    if len(text) > 32:
        raise ValueError("number too long")
    if _THOUSANDS.fullmatch(text):
        return int(re.sub(r"[.,]", "", text))
    if not re.fullmatch(r"-?\d+", text):
        raise ValueError("a trade count is a whole number")
    return int(text)


def _text(value: float) -> str:
    """A validated number as the shared link and the form write it back.

    The shortest digits that round-trip the float, never in exponent notation
    (``repr`` writes ``5e-05``, which ``_number`` refuses), so the link and the
    form parse back to the same input."""
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return np.format_float_positional(number, unique=True, trim="-")


@dataclass(frozen=True)
class Parsed:
    """What the form sent: the input when it is complete and valid, the error
    codes otherwise (``COPY[locale]["error_<code>"]``), and the values to show
    back in the form, only the ones that were valid."""

    value: ChallengeInput | None
    errors: tuple[str, ...]
    shown: dict[str, str]


def parse(values: Mapping[str, str], firm: str = "") -> Parsed:
    """Validate the query fields; ``firm`` restricts the programs to its own."""
    raw = {name: str(values.get(name, "") or "").strip() for name in FIELDS}
    programs = firm_programs(firm)
    errors: list[str] = []
    shown: dict[str, str] = {}
    numbers: dict[str, float] = {}

    def decimal(name: str, *, money: bool = False) -> float | None:
        if not raw[name]:
            return None
        try:
            return _number(raw[name], money=money)
        except ValueError:
            errors.append("number")
            return None

    unit = raw["unit"] or "pct"
    if unit not in UNITS:
        errors.append("unit")
        unit = "pct"
    shown["unit"] = unit
    program = raw["program"] or programs[0]
    if program not in programs:
        errors.append("program")
        program = programs[0]
    shown["program"] = program

    rate = decimal("win_rate")
    if rate is not None:
        if WIN_RATE_RANGE[0] < rate < WIN_RATE_RANGE[1]:
            numbers["win_rate"] = rate
        else:
            errors.append("win_rate")
    # The risk only matters in R: with % of the balance it is ignored, not checked.
    risk = decimal("risk") if unit == "r" else None
    if risk is not None:
        if RISK_RANGE[0] < risk <= RISK_RANGE[1]:
            numbers["risk"] = risk
        else:
            errors.append("risk")
    for name in ("avg_win", "avg_loss"):
        amount = decimal(name)
        if amount is None:
            continue
        if unit == "pct":
            fine = 0.0 < amount <= MAX_TRADE_SHARE * 100.0
        else:
            share = amount * numbers.get("risk", 0.0) / 100.0
            fine = 0.0 < amount <= MAX_R and share <= MAX_TRADE_SHARE
        if fine:
            numbers[name] = amount
        else:
            errors.append(name)
    per_day = decimal("per_day")
    if per_day is not None:
        if PER_DAY_RANGE[0] <= per_day <= PER_DAY_RANGE[1]:
            numbers["per_day"] = per_day
        else:
            errors.append("per_day")
    fee = decimal("fee", money=True)
    if fee is not None:
        if FEE_RANGE[0] < fee <= FEE_RANGE[1]:
            numbers["fee"] = fee
        else:
            errors.append("fee")
    trades: int | None = None
    if raw["trades"]:
        try:
            count = _count(raw["trades"])
        except ValueError:
            errors.append("trades")
        else:
            if TRADES_RANGE[0] <= count <= TRADES_RANGE[1]:
                trades = count
                shown["trades"] = str(count)
            else:
                errors.append("trades")
    shown.update({name: _text(value) for name, value in numbers.items()})
    required = ("win_rate", "avg_win", "avg_loss", "per_day") + (("risk",) if unit == "r" else ())
    if not errors and any(name not in numbers for name in required):
        errors.append("missing")
    if errors:
        return Parsed(None, tuple(dict.fromkeys(errors)), shown)
    value = ChallengeInput(
        win_rate_pct=numbers["win_rate"],
        unit=unit,
        avg_win=numbers["avg_win"],
        avg_loss=numbers["avg_loss"],
        risk=numbers.get("risk") if unit == "r" else None,
        per_day=numbers["per_day"],
        program=program,
        trades=trades,
        fee=numbers.get("fee"),
    )
    return Parsed(value, (), share_values(value))


def submitted(values: Mapping[str, str]) -> bool:
    """Whether the query carries any of the form's fields with a value."""
    return any(str(values.get(name, "") or "").strip() for name in FIELDS)


def share_values(value: ChallengeInput) -> dict[str, str]:
    """The validated input as query strings that parse back to the same numbers."""
    out = {
        "win_rate": _text(value.win_rate_pct),
        "unit": value.unit,
        "avg_win": _text(value.avg_win),
        "avg_loss": _text(value.avg_loss),
    }
    if value.risk is not None:
        out["risk"] = _text(value.risk)
    out["per_day"] = _text(value.per_day)
    if value.trades is not None:
        out["trades"] = str(value.trades)
    out["program"] = value.program
    if value.fee is not None:
        out["fee"] = _text(value.fee)
    return out


def share_url(locale: str, value: ChallengeInput, firm: str = "") -> str:
    """The page's own address for a result, tagged so /panel counts the shares."""
    return challenge_url(locale, firm) + "?" + urlencode({**share_values(value), "ref": SHARE_REF})


#: The return given to a day whose trades net exactly zero (one win and one loss
#: of the same size): the simulator counts a day as traded when its return is
#: not zero, and a firm counts it because there were trades. It moves no
#: balance, and it is the smallest normal float so the 0.5x size keeps it.
TRADED_FLAT_DAY = float(np.finfo(float).tiny)


def _binomial_cdf(trades: int, win_rate: float) -> np.ndarray:
    """P(at most j winners among ``trades``), j = 0..trades."""
    pmf = [
        math.comb(trades, j) * win_rate**j * (1.0 - win_rate) ** (trades - j)
        for j in range(trades + 1)
    ]
    return np.cumsum(pmf)


def synthetic_daily_returns(win_rate: float, win: float, loss: float, per_day: float) -> np.ndarray:
    """``SYNTHETIC_DAYS`` days of trading from the declared figures, seed ``SEED``.

    The days hold exactly ``round(per_day × SYNTHETIC_DAYS)`` trades: with a
    fraction, that many days have one trade more than the rest. Each trade
    wins ``win`` of the balance with probability ``win_rate`` or loses
    ``loss``, so the winners of a day with ``n`` trades follow a binomial.
    Rather than drawing them, which left the seed's 1,000 days with more or
    fewer winners than declared, each day takes a fixed quantile of that
    binomial: the days of each size cover its quantiles evenly, so the mix of
    days, the win rate and the mean return are the declared ones (the winners
    are off by at most one trade per trade a day holds) and do not depend on
    the seed, which only shuffles the days. A day's quantile does not depend on the win rate, so a
    lower win rate turns some of the same winning trades into losers and never
    the other way round. A day with trades that nets zero gets
    ``TRADED_FLAT_DAY`` so the simulator counts it as a trading day."""
    days = SYNTHETIC_DAYS
    whole = math.floor(per_day)
    longer = min(days, round((per_day - whole) * days))
    counts = np.full(days, whole, dtype=np.int64)
    counts[:longer] += 1
    wins = np.zeros(days, dtype=np.int64)
    for trades in (whole, whole + 1):
        group = np.flatnonzero(counts == trades)
        if trades == 0 or not len(group):
            continue
        quantiles = (np.arange(len(group)) + 0.5) / len(group)
        drawn = np.searchsorted(_binomial_cdf(trades, win_rate), quantiles, side="left")
        wins[group] = np.minimum(drawn, trades)
    order = np.random.default_rng(SEED).permutation(days)
    counts, wins = counts[order], wins[order]
    daily = np.asarray(wins * win - (counts - wins) * loss, dtype=float)
    daily[(counts > 0) & (daily == 0.0)] = TRADED_FLAT_DAY
    return daily


@dataclass(frozen=True)
class ProgramRun:
    """One program on one synthetic history: each phase's simulator result and
    the program's outcome (``firmfit.program_outcomes``)."""

    win_rate: float
    daily: np.ndarray
    phases: tuple[tuple[str, dict[str, Any]], ...]
    outcome: dict[str, Any]

    @property
    def measured(self) -> bool:
        return self.outcome.get("status") == "MEASURED"


def run_program(value: ChallengeInput, win_rate: float) -> ProgramRun:
    """Every phase of the chosen program on the synthetic days at ``win_rate``."""
    daily = synthetic_daily_returns(win_rate, value.win, value.loss, value.per_day)
    phases = tuple(
        (key, simulate_challenge(daily, PRESETS[key], samples=SAMPLES, seed=SEED))
        for key in firmfit.program_keys(value.program)
    )
    if all(result.get("method") for _, result in phases):
        outcome = firmfit.program_outcomes(
            daily, value.program, samples=SAMPLES, seed=SEED, known=dict(phases)
        )
    else:
        outcome = {"status": "NOT_MEASURED", "reason": "identical_days"}
    return ProgramRun(win_rate=win_rate, daily=daily, phases=phases, outcome=outcome)


@dataclass(frozen=True)
class ChallengeReading:
    """What the page shows, every figure from the simulator or ``winrate.read``."""

    declared: ProgramRun
    #: ``(size, program_outcomes)`` for each of ``SIZES``; 1x is ``declared``'s.
    sizes: tuple[tuple[float, dict[str, Any]], ...]
    #: The win rate's 95 % Wilson interval, with the declared trades.
    interval: tuple[float, float] | None
    #: The program at the interval's lower end.
    lower: ProgramRun | None
    #: 1 ÷ the chance of reaching every phase's target, when it is above zero.
    attempts: float | None
    #: The declared fee times ``attempts``.
    cost: float | None


#: Cached readings; each keeps its synthetic days (two arrays of ``SYNTHETIC_DAYS``).
CACHE_SIZE = 64


@lru_cache(maxsize=CACHE_SIZE)
def compute(value: ChallengeInput) -> ChallengeReading:
    """The declared program, its sizes and its lower-bound twin. Pure and cached:
    the same input (the same link) gives the same figures."""
    declared = run_program(value, value.win_rate)
    sizes: list[tuple[float, dict[str, Any]]] = []
    if declared.measured:
        for size in SIZES:
            outcome = (
                declared.outcome
                if size == 1.0
                else firmfit.program_outcomes(
                    declared.daily * size, value.program, samples=SAMPLES, seed=SEED
                )
            )
            sizes.append((size, outcome))
    interval = None
    lower = None
    if value.trades is not None:
        interval = winrate.read(PublicClaim(trades=value.trades, win_rate=value.win_rate)).interval
        if interval is not None:
            lower = run_program(value, interval[0])
    attempts = cost = None
    if declared.measured:
        chance = float(declared.outcome["pass"]["value"])
        if chance > 0:
            attempts = 1.0 / chance
            if value.fee is not None:
                cost = value.fee / chance
    return ChallengeReading(
        declared=declared,
        sizes=tuple(sizes),
        interval=interval,
        lower=lower,
        attempts=attempts,
        cost=cost,
    )


def account_size(key: str) -> float | None:
    """The account the program names, in US dollars (Topstep), when it names one."""
    return ACCOUNT_SIZES.get(key)


COPY: dict[str, dict[str, Any]] = {
    "es": {
        "nav": "Calculadora de reto de prop firm",
        "eyebrow": "Calculadora gratis",
        "title": "¿Con qué frecuencia alcanzarías el objetivo de un reto de prop firm?",
        "seo_title": "Calculadora de reto de prop firm: objetivo y límites",
        "summary": (
            "Calculadora gratis e independiente, no afiliada a ninguna firma: frecuencia de "
            "alcanzar el objetivo de FTMO, FundedNext, The5ers o Topstep o de tocar límites."
        ),
        "lead": (
            "Escribe tu % de aciertos, tu ganancia y tu pérdida medias y cuántas operaciones "
            "haces al día. El simulador del informe recorre trayectorias sintéticas con las "
            "reglas publicadas de la firma. Sin registro ni archivo."
        ),
        "form_title": "Tus cifras",
        "optional": (
            "Los campos opcionales pueden quedar vacíos: lo que dependa de ellos aparecerá "
            "como NOT_MEASURED."
        ),
        "win_rate": "% de aciertos",
        "win_rate_help": "El porcentaje de operaciones ganadoras. Por ejemplo 55.",
        "unit": "Cómo escribes la ganancia y la pérdida",
        "unit_help": "En % del balance por operación, o en R con tu riesgo por operación.",
        "unit_options": {"pct": "En % del balance", "r": "En R, con el riesgo por operación"},
        "avg_win": "Ganancia media por operación ganadora",
        "avg_win_help": "En % del balance (por ejemplo 0,8) o en R (por ejemplo 1,5).",
        "avg_loss": "Pérdida media por operación perdedora",
        "avg_loss_help": "En % del balance (por ejemplo 0,5) o en R (normalmente 1).",
        "risk": "Riesgo por operación (% del balance)",
        "risk_help": (
            "Solo si escribes en R: cuánto del balance arriesgas en cada operación. "
            "Por ejemplo 0,5."
        ),
        "per_day": "Operaciones por día",
        "per_day_help": (
            "Promedio por día de trading. Admite decimales: 0,5 es una operación cada dos días."
        ),
        "trades": "Operaciones de tu historial (opcional)",
        "trades_help": (
            "Cuántas operaciones cerradas hay detrás de tu % de aciertos. Con este dato "
            "también vemos el resultado con el límite inferior de su intervalo."
        ),
        "program": "Firma y programa",
        "program_help": "Reglas publicadas por la firma que Rigor transcribió, con fuente y fecha.",
        "phases": {1: "1 fase", 2: "2 fases", 3: "3 fases"},
        "fee": "Cuota del reto en USD (opcional)",
        "fee_help": (
            "La que pagarías, declarada por ti. Con ella calculamos los intentos esperados y el "
            "costo esperado por cuenta."
        ),
        "submit": "Calcular",
        "error_number": "Revisa los números: escribe cifras como 55, 0,8 o 1.5.",
        "error_missing": (
            "Faltan cifras: escribe el % de aciertos, la ganancia media, la pérdida media y las "
            "operaciones por día (y el riesgo por operación si escribes en R)."
        ),
        "error_win_rate": "El % de aciertos debe ser mayor que 0 y menor que 100.",
        "error_unit": "Elige si escribes la ganancia y la pérdida en % del balance o en R.",
        "error_avg_win": (
            "La ganancia media debe ser mayor que 0 y, por operación, como mucho el 50 % del "
            "balance (en R, como mucho 100 R)."
        ),
        "error_avg_loss": (
            "La pérdida media debe ser mayor que 0 y, por operación, como mucho el 50 % del "
            "balance (en R, como mucho 100 R)."
        ),
        "error_risk": "El riesgo por operación debe ser mayor que 0 y como mucho 20 %.",
        "error_per_day": "Las operaciones por día deben estar entre 0,1 y 50.",
        "error_trades": (
            "Las operaciones del historial deben ser un número entero entre 1 y 10.000.000."
        ),
        "error_fee": "La cuota debe ser mayor que 0 y como mucho USD 100.000.",
        "error_program": "Elige una firma y un programa de la lista.",
        "error_invalid": "Revisa los campos: cada uno debe aparecer una sola vez.",
        "limited": (
            "Demasiados cálculos desde esta dirección en la última hora. Inténtalo más tarde."
        ),
        "result_title": "Resultado",
        "simulated": "Programa simulado: {program} ({phases}).",
        "row_target": "Alcanzar el objetivo",
        "row_target_all": "Alcanzar el objetivo en todas las fases",
        "row_best_day": "Alcanzar el objetivo dentro de la regla del mejor día",
        "row_daily": "Tocar el límite de pérdida diaria",
        "row_total": "Tocar el límite de pérdida total",
        "row_unfinished": "Quedar sin terminar en {days} días hábiles",
        "row_days": "Días hábiles medianos hasta el objetivo",
        "row_attempts": "Intentos esperados (1 ÷ probabilidad de alcanzar el objetivo)",
        "row_cost": "Costo esperado por cuenta (cuota ÷ probabilidad)",
        "row_fee": "Cuota declarada",
        "phase_value": "fase {n}: {value}",
        "days_unit": "{n} días",
        "attempts_unit": "{n} intentos",
        "computed": "Calculado a partir de lo declarado",
        "lower_computed": "calculado con tus operaciones y tu % de aciertos declarados (Wilson)",
        "no_daily": "la calculadora no simula un límite diario en este programa (ver notas)",
        "no_target": "ninguna trayectoria alcanzó el objetivo",
        "no_fee": "escribe la cuota para calcularlo",
        "identical_days": (
            "Con estas cifras todos los días sintéticos son iguales y el simulador no puede "
            "remuestrearlos. Cambia el % de aciertos o las operaciones por día."
        ),
        "paths_note": (
            "Cifras del mismo simulador que el informe, sobre {samples} trayectorias por fase "
            "remuestreadas de {days} días sintéticos hechos con tus cifras. Semilla fija: el "
            "mismo enlace da el mismo resultado. Cada fase empieza de cero y solo se llega a ella "
            "alcanzando el objetivo de la anterior."
        ),
        "fee_note": (
            "Es el promedio de intentos independientes con tus cifras declaradas: no limita "
            "cuántos podrían hacer falta, no cuenta reembolsos ni descuentos y no es una "
            "recomendación de comprar un reto."
        ),
        "phase_title": "Fase por fase",
        "col_phase": "Fase",
        "col_target": "Alcanzar el objetivo",
        "col_daily": "Límite diario",
        "col_total": "Límite total",
        "col_unfinished": "Sin terminar",
        "col_days": "Días medianos",
        "col_size": "Tamaño",
        "lower_title": "Con el límite inferior de tu % de aciertos",
        "lower_text": (
            "Con {n} operaciones, un {rate} de aciertos declarado es compatible con un {low} "
            "real: es el límite inferior del intervalo de confianza al 95 % (Wilson). Con ese "
            "{low} y las mismas cifras, el programa queda así:"
        ),
        "lower_missing": (
            "Escribe cuántas operaciones tiene tu historial: con pocas, un 60 % de aciertos "
            "puede ser en realidad bastante menos, y el resultado del reto cambia con él."
        ),
        "lower_link": "Calcular el intervalo de mi % de aciertos",
        "size_title": "¿A qué tamaño? El reto a 0,5x, 1x y 2x",
        "size_text": (
            "Cada fila es el programa con todas las ganancias y pérdidas diarias multiplicadas "
            "por el tamaño: 0,5x es la mitad de tu riesgo por operación y 2x el doble. Es la "
            "misma lógica que la tabla de tamaños del informe y supone que todo escala en la "
            "misma proporción."
        ),
        "share_title": "Compartir este resultado",
        "share_text": (
            "Mis cifras declaradas en la calculadora de reto de Rigor, con las reglas publicadas "
            "de {program}. No es una auditoría ni una recomendación. {url}"
        ),
        "share_public": (
            "El enlace contiene las cifras que escribiste; cualquiera con el enlace puede leerlas."
        ),
        "rules_title": "Reglas usadas",
        "firm_rules_title": "Reglas de {firm} que usa la calculadora",
        "col_rule_program": "Programa y fase",
        "col_rule_target": "Objetivo",
        "col_rule_daily": "Pérdida diaria máxima",
        "col_rule_total": "Pérdida total máxima",
        "col_rule_days": "Días mínimos",
        "col_rule_time": "Plazo",
        "col_rule_best": "Mejor día",
        "daily_initial": "{value} del balance inicial",
        "daily_day": "{value} del balance al empezar el día",
        "daily_none": "no se simula (ver notas)",
        "total_static": "{value}, fija",
        "total_trailing": "{value}, sigue al mayor cierre diario",
        "total_lock": "{value}, sigue al mayor cierre diario hasta el balance inicial",
        "time_none": "sin plazo",
        "time_days": "{n} días",
        "best_none": "sin regla",
        "best_target": "como mucho el {value} del objetivo",
        "best_positive": "como mucho el {value} de la ganancia de los días positivos",
        "account": "cuenta de USD {amount}",
        "source": "Fuente de {programs}: {link}, leída el {date}.",
        "source_link": "página de {firm}",
        "note_link": "página de {host}",
        "not_affiliated": (
            "Rigor no está afiliado a ninguna firma; las reglas cambian, comprueba la página de "
            "la firma."
        ),
        "notes_title": "Notas de las reglas de {program}",
        "faq_title": "Preguntas frecuentes",
        "how_title": "Qué calcula y qué supone",
        "how": [
            "Cada día sintético tiene tus operaciones por día; en conjunto, la parte de ellas que "
            "gana tu ganancia media es tu % de aciertos y el resto pierde tu pérdida media. Con "
            "decimales, unos días tienen una operación más que otros para que el promedio sea el "
            "tuyo.",
            "El simulador del informe remuestrea esos días y revisa cada cierre diario: primero el "
            "límite diario, después el total y al final el objetivo con los días mínimos. Todo día "
            "con operaciones cuenta como día de trading, aunque su resultado neto sea cero.",
            "Todas las ganancias y pérdidas tienen el tamaño medio: sin colas, deslizamiento, "
            "costos ni flotante dentro del día. Las pérdidas reales varían, así que con un "
            "historial real los límites suelen tocarse más a menudo.",
            "Las operaciones son independientes: sin rachas más largas que las del azar.",
            "Las reglas son las publicadas por cada firma en la fecha indicada; pueden haber "
            "cambiado.",
            "No guardamos tus cifras en ninguna base de datos ni archivo; como van en el enlace, "
            "el registro de acceso del servidor puede contener la dirección pedida. Es un cálculo "
            "con cifras declaradas, no una auditoría ni una previsión.",
        ],
        "cta_title": "Con tu historial real",
        "cta": (
            "Con tu historial real, el simulador usa tus días de verdad, el flotante al cierre de "
            "cada día y los costos: sube tu archivo. El informe remuestrea tus propios días con "
            "las reglas de la firma, compara las firmas publicadas y prueba los tamaños."
        ),
        "cta_button": "Subir mi archivo",
        "sample_link": "Ver un informe de ejemplo",
        "read_title": "Para seguir",
        "firm_link": "Calculadora del reto {firm}",
        "main_link": "Calculadora con todas las firmas",
        "other_firms": "Otras firmas:",
    },
    "en": {
        "nav": "Prop firm challenge calculator",
        "eyebrow": "Free calculator",
        "title": "How often would you reach a prop firm challenge target?",
        "seo_title": "Prop firm challenge calculator: target and limits",
        "summary": (
            "Free, independent calculator, not affiliated with any firm: how often you would reach "
            "the FTMO, FundedNext, The5ers or Topstep target or hit a loss limit."
        ),
        "lead": (
            "Enter your win rate, your average win and loss and how many trades you take a "
            "day. The report's simulator walks synthetic paths through the firm's published "
            "rules. No signup, no file."
        ),
        "form_title": "Your figures",
        "optional": (
            "Optional fields can stay empty: whatever depends on them will appear as NOT_MEASURED."
        ),
        "win_rate": "Win rate (%)",
        "win_rate_help": "The share of winning trades. For example 55.",
        "unit": "How you write the win and the loss",
        "unit_help": "As % of the balance per trade, or in R with your risk per trade.",
        "unit_options": {"pct": "As % of the balance", "r": "In R, with the risk per trade"},
        "avg_win": "Average win per winning trade",
        "avg_win_help": "As % of the balance (for example 0.8) or in R (for example 1.5).",
        "avg_loss": "Average loss per losing trade",
        "avg_loss_help": "As % of the balance (for example 0.5) or in R (usually 1).",
        "risk": "Risk per trade (% of the balance)",
        "risk_help": (
            "Only when you write in R: how much of the balance each trade risks. For example 0.5."
        ),
        "per_day": "Trades per day",
        "per_day_help": "Average per trading day. Decimals work: 0.5 is one trade every two days.",
        "trades": "Trades in your history (optional)",
        "trades_help": (
            "How many closed trades are behind your win rate. With it we also show the result "
            "at the lower end of its interval."
        ),
        "program": "Firm and program",
        "program_help": "Rules the firm posted, transcribed by Rigor with their source and date.",
        "phases": {1: "1 phase", 2: "2 phases", 3: "3 phases"},
        "fee": "Challenge fee in USD (optional)",
        "fee_help": (
            "The fee you would pay, as you declare it. With it we compute the expected attempts "
            "and the expected cost per account."
        ),
        "submit": "Calculate",
        "error_number": "Check the numbers: write figures such as 55, 0.8 or 1,5.",
        "error_missing": (
            "Some figures are missing: enter the win rate, the average win, the average loss "
            "and the trades per day (and the risk per trade when you write in R)."
        ),
        "error_win_rate": "The win rate must be above 0 and below 100.",
        "error_unit": "Choose whether you write the win and the loss as % of the balance or in R.",
        "error_avg_win": (
            "The average win must be above 0 and, per trade, at most 50 % of the balance "
            "(in R, at most 100 R)."
        ),
        "error_avg_loss": (
            "The average loss must be above 0 and, per trade, at most 50 % of the balance "
            "(in R, at most 100 R)."
        ),
        "error_risk": "The risk per trade must be above 0 and at most 20 %.",
        "error_per_day": "The trades per day must be between 0.1 and 50.",
        "error_trades": "The trades in your history must be a whole number from 1 to 10,000,000.",
        "error_fee": "The fee must be above 0 and at most USD 100,000.",
        "error_program": "Choose a firm and a program from the list.",
        "error_invalid": "Check the fields: each one must appear only once.",
        "limited": "Too many calculations from this address in the last hour. Try again later.",
        "result_title": "Result",
        "simulated": "Program simulated: {program} ({phases}).",
        "row_target": "Reach the target",
        "row_target_all": "Reach the target in every phase",
        "row_best_day": "Reach the target within the best-day rule",
        "row_daily": "Hit the daily loss limit",
        "row_total": "Hit the total loss limit",
        "row_unfinished": "Left unfinished after {days} business days",
        "row_days": "Median business days to the target",
        "row_attempts": "Expected attempts (1 ÷ chance of reaching the target)",
        "row_cost": "Expected cost per account (fee ÷ chance)",
        "row_fee": "Declared fee",
        "phase_value": "phase {n}: {value}",
        "days_unit": "{n} days",
        "attempts_unit": "{n} attempts",
        "computed": "Computed from declared figures",
        "lower_computed": "computed from your declared trades and win rate (Wilson)",
        "no_daily": "the calculator simulates no daily limit in this program (see the notes)",
        "no_target": "no path reached the target",
        "no_fee": "enter the fee to compute it",
        "identical_days": (
            "With these figures every synthetic day is the same and the simulator cannot "
            "resample them. Change the win rate or the trades per day."
        ),
        "paths_note": (
            "Figures from the report's own simulator, over {samples} paths per phase resampled "
            "from {days} synthetic days built from your figures. Fixed seed: the same link gives "
            "the same result. Each phase starts afresh and is reached only by reaching the "
            "previous phase's target."
        ),
        "fee_note": (
            "This is the average of independent attempts with your declared figures: it does "
            "not cap how many could be needed, counts no refunds or discounts and is not a "
            "recommendation to buy a challenge."
        ),
        "phase_title": "Phase by phase",
        "col_phase": "Phase",
        "col_target": "Reach the target",
        "col_daily": "Daily limit",
        "col_total": "Total limit",
        "col_unfinished": "Unfinished",
        "col_days": "Median days",
        "col_size": "Size",
        "lower_title": "At the lower end of your win rate",
        "lower_text": (
            "With {n} trades, a declared {rate} win rate is compatible with a real {low}: the "
            "lower end of the 95 % confidence interval (Wilson). At that {low}, with the same "
            "figures, the program looks like this:"
        ),
        "lower_missing": (
            "Enter how many trades your history has: with few of them, a 60 % win rate may "
            "really be a good deal less, and the challenge result changes with it."
        ),
        "lower_link": "Compute my win rate's interval",
        "size_title": "At what size? The challenge at 0.5x, 1x and 2x",
        "size_text": (
            "Each row is the program with every daily win and loss multiplied by the size: 0.5x "
            "is half your risk per trade and 2x double. It is the same logic as the report's "
            "sizing table and assumes everything scales in the same proportion."
        ),
        "share_title": "Share this result",
        "share_text": (
            "My declared figures in Rigor's challenge calculator, with the published rules of "
            "{program}. This is not an audit or a recommendation. {url}"
        ),
        "share_public": (
            "The link contains the figures you entered; anyone with the link can read them."
        ),
        "rules_title": "Rules used",
        "firm_rules_title": "{firm} rules the calculator uses",
        "col_rule_program": "Program and phase",
        "col_rule_target": "Target",
        "col_rule_daily": "Maximum daily loss",
        "col_rule_total": "Maximum total loss",
        "col_rule_days": "Minimum days",
        "col_rule_time": "Time limit",
        "col_rule_best": "Best day",
        "daily_initial": "{value} of the initial balance",
        "daily_day": "{value} of the balance at the start of the day",
        "daily_none": "not simulated (see the notes)",
        "total_static": "{value}, static",
        "total_trailing": "{value}, trailing the highest daily close",
        "total_lock": "{value}, trailing the highest daily close up to the initial balance",
        "time_none": "none",
        "time_days": "{n} days",
        "best_none": "no rule",
        "best_target": "at most {value} of the target",
        "best_positive": "at most {value} of the positive days' gain",
        "account": "USD {amount} account",
        "source": "Source for {programs}: {link}, read on {date}.",
        "source_link": "{firm} page",
        "note_link": "{host} page",
        "not_affiliated": (
            "Rigor is not affiliated with any firm; rules change, so check the firm's own page."
        ),
        "notes_title": "Notes on the {program} rules",
        "faq_title": "Frequently asked questions",
        "how_title": "What it computes and assumes",
        "how": [
            "Each synthetic day has your trades per day; across them, the share that wins your "
            "average win is your win rate and the rest lose your average loss. With decimals, some "
            "days have one more trade than others so the average is yours.",
            "The report's simulator resamples those days and checks every daily close: first the "
            "daily limit, then the total one and last the target with the minimum days. Every day "
            "with trades counts as a trading day, even when it nets zero.",
            "Every win and loss has the average size: no tails, slippage, costs or intraday "
            "floating loss. Real losses vary, so with a real history the limits are usually hit "
            "more often.",
            "Trades are independent: no streaks longer than chance.",
            "The rules are those each firm posted on the date shown; they may have changed.",
            "We keep your figures in no database or file; since they travel in the link, the "
            "server's access log may hold the address requested. It is a calculation with declared "
            "figures, not an audit or a forecast.",
        ],
        "cta_title": "With your real history",
        "cta": (
            "With your real history, the simulator uses your actual days, the floating loss at "
            "each daily close and the costs: upload your file. The report resamples your own "
            "days with the firm's rules, compares the published firms and tries the sizes."
        ),
        "cta_button": "Upload my file",
        "sample_link": "See a sample report",
        "read_title": "Keep reading",
        "firm_link": "{firm} challenge calculator",
        "main_link": "Calculator with every firm",
        "other_firms": "Other firms:",
    },
    "pt": {
        "nav": "Calculadora de desafio de prop firm",
        "eyebrow": "Calculadora grátis",
        "title": "Com que frequência você atingiria a meta de um desafio de prop firm?",
        "seo_title": "Calculadora de desafio de prop firm: meta e limites",
        "summary": (
            "Calculadora grátis e independente, não afiliada a nenhuma empresa: frequência de "
            "atingir a meta da FTMO, FundedNext, The5ers ou Topstep ou de tocar os limites."
        ),
        "lead": (
            "Digite a sua taxa de acerto, o seu ganho e a sua perda médios e quantas operações "
            "você faz por dia. O simulador do relatório percorre trajetórias sintéticas com as "
            "regras publicadas da empresa. Sem cadastro nem arquivo."
        ),
        "form_title": "Seus números",
        "optional": (
            "Os campos opcionais podem ficar vazios: o que depender deles aparecerá como "
            "NOT_MEASURED."
        ),
        "win_rate": "Taxa de acerto (%)",
        "win_rate_help": "A porcentagem de operações vencedoras. Por exemplo 55.",
        "unit": "Como você escreve o ganho e a perda",
        "unit_help": "Em % do saldo por operação, ou em R com o seu risco por operação.",
        "unit_options": {"pct": "Em % do saldo", "r": "Em R, com o risco por operação"},
        "avg_win": "Ganho médio por operação vencedora",
        "avg_win_help": "Em % do saldo (por exemplo 0,8) ou em R (por exemplo 1,5).",
        "avg_loss": "Perda média por operação perdedora",
        "avg_loss_help": "Em % do saldo (por exemplo 0,5) ou em R (normalmente 1).",
        "risk": "Risco por operação (% do saldo)",
        "risk_help": (
            "Só se você escrever em R: quanto do saldo cada operação arrisca. Por exemplo 0,5."
        ),
        "per_day": "Operações por dia",
        "per_day_help": (
            "Média por dia de trading. Aceita decimais: 0,5 é uma operação a cada dois dias."
        ),
        "trades": "Operações do seu histórico (opcional)",
        "trades_help": (
            "Quantas operações fechadas estão por trás da sua taxa de acerto. Com esse número "
            "também mostramos o resultado no limite inferior do intervalo."
        ),
        "program": "Empresa e programa",
        "program_help": (
            "Regras publicadas pela empresa e transcritas pelo Rigor, com fonte e data."
        ),
        "phases": {1: "1 fase", 2: "2 fases", 3: "3 fases"},
        "fee": "Taxa do desafio em USD (opcional)",
        "fee_help": (
            "A que você pagaria, declarada por você. Com ela calculamos as tentativas esperadas "
            "e o custo esperado por conta."
        ),
        "submit": "Calcular",
        "error_number": "Revise os números: escreva valores como 55, 0,8 ou 1.5.",
        "error_missing": (
            "Faltam números: digite a taxa de acerto, o ganho médio, a perda média e as "
            "operações por dia (e o risco por operação se escrever em R)."
        ),
        "error_win_rate": "A taxa de acerto deve ser maior que 0 e menor que 100.",
        "error_unit": "Escolha se você escreve o ganho e a perda em % do saldo ou em R.",
        "error_avg_win": (
            "O ganho médio deve ser maior que 0 e, por operação, no máximo 50 % do saldo "
            "(em R, no máximo 100 R)."
        ),
        "error_avg_loss": (
            "A perda média deve ser maior que 0 e, por operação, no máximo 50 % do saldo "
            "(em R, no máximo 100 R)."
        ),
        "error_risk": "O risco por operação deve ser maior que 0 e no máximo 20 %.",
        "error_per_day": "As operações por dia devem estar entre 0,1 e 50.",
        "error_trades": (
            "As operações do histórico devem ser um número inteiro entre 1 e 10.000.000."
        ),
        "error_fee": "A taxa deve ser maior que 0 e no máximo USD 100.000.",
        "error_program": "Escolha uma empresa e um programa da lista.",
        "error_invalid": "Revise os campos: cada um deve aparecer uma só vez.",
        "limited": (
            "Cálculos demais a partir deste endereço na última hora. Tente novamente mais tarde."
        ),
        "result_title": "Resultado",
        "simulated": "Programa simulado: {program} ({phases}).",
        "row_target": "Atingir a meta",
        "row_target_all": "Atingir a meta em todas as fases",
        "row_best_day": "Atingir a meta dentro da regra do melhor dia",
        "row_daily": "Tocar o limite de perda diária",
        "row_total": "Tocar o limite de perda total",
        "row_unfinished": "Ficar sem terminar em {days} dias úteis",
        "row_days": "Dias úteis medianos até a meta",
        "row_attempts": "Tentativas esperadas (1 ÷ probabilidade de atingir a meta)",
        "row_cost": "Custo esperado por conta (taxa ÷ probabilidade)",
        "row_fee": "Taxa declarada",
        "phase_value": "fase {n}: {value}",
        "days_unit": "{n} dias",
        "attempts_unit": "{n} tentativas",
        "computed": "Calculado a partir do declarado",
        "lower_computed": (
            "calculado com as suas operações e a sua taxa de acerto declaradas (Wilson)"
        ),
        "no_daily": "a calculadora não simula um limite diário neste programa (veja as notas)",
        "no_target": "nenhuma trajetória atingiu a meta",
        "no_fee": "digite a taxa para calcular",
        "identical_days": (
            "Com esses números todos os dias sintéticos são iguais e o simulador não consegue "
            "reamostrá-los. Mude a taxa de acerto ou as operações por dia."
        ),
        "paths_note": (
            "Números do mesmo simulador do relatório, sobre {samples} trajetórias por fase "
            "reamostradas de {days} dias sintéticos feitos com os seus números. Semente fixa: o "
            "mesmo link dá o mesmo resultado. Cada fase começa do zero e só se chega a ela "
            "atingindo a meta da anterior."
        ),
        "fee_note": (
            "É a média de tentativas independentes com os seus números declarados: não limita "
            "quantas poderiam ser necessárias, não conta reembolsos nem descontos e não é uma "
            "recomendação de comprar um desafio."
        ),
        "phase_title": "Fase por fase",
        "col_phase": "Fase",
        "col_target": "Atingir a meta",
        "col_daily": "Limite diário",
        "col_total": "Limite total",
        "col_unfinished": "Sem terminar",
        "col_days": "Dias medianos",
        "col_size": "Tamanho",
        "lower_title": "No limite inferior da sua taxa de acerto",
        "lower_text": (
            "Com {n} operações, uma taxa de acerto declarada de {rate} é compatível com uma real "
            "de {low}: o limite inferior do intervalo de confiança de 95 % (Wilson). Com esses "
            "{low} e os mesmos números, o programa fica assim:"
        ),
        "lower_missing": (
            "Digite quantas operações o seu histórico tem: com poucas, uma taxa de acerto de "
            "60 % pode ser bem menor na realidade, e o resultado do desafio muda com ela."
        ),
        "lower_link": "Calcular o intervalo da minha taxa de acerto",
        "size_title": "Em que tamanho? O desafio a 0,5x, 1x e 2x",
        "size_text": (
            "Cada linha é o programa com todos os ganhos e perdas diários multiplicados pelo "
            "tamanho: 0,5x é a metade do seu risco por operação e 2x o dobro. É a mesma lógica "
            "da tabela de tamanhos do relatório e supõe que tudo escala na mesma proporção."
        ),
        "share_title": "Compartilhar este resultado",
        "share_text": (
            "Meus números declarados na calculadora de desafio do Rigor, com as regras "
            "publicadas de {program}. Não é uma auditoria nem uma recomendação. {url}"
        ),
        "share_public": (
            "O link contém os números que você digitou; qualquer pessoa com o link pode lê-los."
        ),
        "rules_title": "Regras usadas",
        "firm_rules_title": "Regras da {firm} que a calculadora usa",
        "col_rule_program": "Programa e fase",
        "col_rule_target": "Meta",
        "col_rule_daily": "Perda diária máxima",
        "col_rule_total": "Perda total máxima",
        "col_rule_days": "Dias mínimos",
        "col_rule_time": "Prazo",
        "col_rule_best": "Melhor dia",
        "daily_initial": "{value} do saldo inicial",
        "daily_day": "{value} do saldo no início do dia",
        "daily_none": "não simulado (veja as notas)",
        "total_static": "{value}, fixa",
        "total_trailing": "{value}, acompanha o maior fechamento diário",
        "total_lock": "{value}, acompanha o maior fechamento diário até o saldo inicial",
        "time_none": "sem prazo",
        "time_days": "{n} dias",
        "best_none": "sem regra",
        "best_target": "no máximo {value} da meta",
        "best_positive": "no máximo {value} do ganho dos dias positivos",
        "account": "conta de USD {amount}",
        "source": "Fonte de {programs}: {link}, lida em {date}.",
        "source_link": "página da {firm}",
        "note_link": "página de {host}",
        "not_affiliated": (
            "O Rigor não é afiliado a nenhuma empresa; as regras mudam, confira a página da "
            "empresa."
        ),
        "notes_title": "Notas das regras de {program}",
        "faq_title": "Perguntas frequentes",
        "how_title": "O que calcula e o que supõe",
        "how": [
            "Cada dia sintético tem as suas operações por dia; no conjunto, a parte delas que "
            "ganha o seu ganho médio é a sua taxa de acerto e o resto perde a sua perda média. Com "
            "decimais, alguns dias têm uma operação a mais que outros para que a média seja a sua.",
            "O simulador do relatório reamostra esses dias e confere cada fechamento diário: "
            "primeiro o limite diário, depois o total e por fim a meta com os dias mínimos. Todo "
            "dia com operações conta como dia de trading, mesmo que o resultado líquido seja zero.",
            "Todos os ganhos e perdas têm o tamanho médio: sem caudas, slippage, custos nem perda "
            "flutuante dentro do dia. As perdas reais variam, então com um histórico real os "
            "limites costumam ser tocados com mais frequência.",
            "As operações são independentes: sem sequências mais longas que as do acaso.",
            "As regras são as publicadas por cada empresa na data indicada; podem ter mudado.",
            "Não guardamos os seus números em nenhum banco de dados nem arquivo; como vão no link, "
            "o registro de acesso do servidor pode conter o endereço pedido. É um cálculo com "
            "números declarados, não uma auditoria nem uma previsão.",
        ],
        "cta_title": "Com o seu histórico real",
        "cta": (
            "Com o seu histórico real, o simulador usa os seus dias de verdade, a perda "
            "flutuante no fechamento de cada dia e os custos: envie o seu arquivo. O relatório "
            "reamostra os seus próprios dias com as regras da empresa, compara as empresas "
            "publicadas e testa os tamanhos."
        ),
        "cta_button": "Enviar meu arquivo",
        "sample_link": "Ver um relatório de exemplo",
        "read_title": "Para continuar",
        "firm_link": "Calculadora do desafio {firm}",
        "main_link": "Calculadora com todas as empresas",
        "other_firms": "Outras empresas:",
    },
}


#: The firm pages' own words. ``faq`` answers are templates: ``{rules[key]}``
#: is the rules sentence of that program (:func:`rules_sentence`), so a figure
#: in an answer is always the preset's.
FIRM_COPY: dict[str, dict[str, dict[str, Any]]] = {
    "ftmo": {
        "es": {
            "title": "Calculadora del reto FTMO",
            "seo_title": "Calculadora del reto FTMO: objetivo y límites",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a FTMO: frecuencia de alcanzar el "
                "objetivo del FTMO Challenge 1-Step o 2-Step o de tocar sus límites."
            ),
            "lead": (
                "La calculadora de reto con las reglas publicadas de FTMO: escribe tu % de "
                "aciertos, tu ganancia y tu pérdida medias y tus operaciones por día. Rigor no "
                "está afiliado a FTMO."
            ),
            "faq": (
                (
                    "¿Qué objetivo y qué límites tiene el FTMO Challenge 2-Step?",
                    "Según la página de FTMO leída el {as_of}: {rules[ftmo-2step-phase1]}.",
                ),
                (
                    "¿Qué cambia en el FTMO Challenge 1-Step?",
                    "Según la página de FTMO leída el {as_of}, en el 1-Step: {rules[ftmo-1step]}. "
                    "La calculadora deja que esa pérdida total siga al mayor cierre sin detenerse, "
                    "que es lo más estricto, porque la página leída no dice si se detiene.",
                ),
                (
                    "¿Cómo cuenta la calculadora la pérdida diaria de FTMO?",
                    "Según la página de FTMO leída el {as_of}: en el 2-Step, "
                    "{daily[ftmo-2step-phase1]}, contada desde el balance registrado a las 00:00 "
                    "CE(S)T; en el 1-Step, {daily[ftmo-1step]}. La calculadora la revisa en cada "
                    "cierre diario: no ve el flotante dentro del día, así que frente a ese límite "
                    "es optimista.",
                ),
                (
                    "¿La calculadora dice cuántos retos de FTMO comprar?",
                    "No. Con la cuota que declaras divide entre la probabilidad de alcanzar el "
                    "objetivo en todas las fases: es un promedio de intentos independientes con "
                    "cifras declaradas, no un presupuesto ni una recomendación de compra.",
                ),
            ),
        },
        "en": {
            "title": "FTMO challenge calculator",
            "seo_title": "FTMO challenge calculator: target and limits",
            "summary": (
                "Free, independent calculator, not affiliated with FTMO: how often you would reach "
                "the FTMO Challenge 1-Step or 2-Step target or hit a limit."
            ),
            "lead": (
                "The challenge calculator with FTMO's published rules: enter your win rate, "
                "your average win and loss and your trades per day. Rigor is not affiliated "
                "with FTMO."
            ),
            "faq": (
                (
                    "What target and limits does the FTMO Challenge 2-Step have?",
                    "According to the FTMO page read on {as_of}: {rules[ftmo-2step-phase1]}.",
                ),
                (
                    "What changes in the FTMO Challenge 1-Step?",
                    "According to the FTMO page read on {as_of}, in the 1-Step: "
                    "{rules[ftmo-1step]}. The calculator lets that total loss trail without "
                    "stopping, the stricter reading, because the page read does not say whether it "
                    "stops.",
                ),
                (
                    "How does the calculator count FTMO's daily loss?",
                    "According to the FTMO page read on {as_of}: in the 2-Step, "
                    "{daily[ftmo-2step-phase1]}, counted from the balance recorded at 00:00 "
                    "CE(S)T; in the 1-Step, {daily[ftmo-1step]}. The calculator checks it at every "
                    "daily close: it does not see the intraday floating loss, so it is optimistic "
                    "against that limit.",
                ),
                (
                    "Does the calculator say how many FTMO challenges to buy?",
                    "No. It divides the fee you declare by the chance of reaching the target in "
                    "every phase: an average of independent attempts with declared figures, not a "
                    "budget or a recommendation to buy.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do desafio FTMO",
            "seo_title": "Calculadora do desafio FTMO: meta e limites",
            "summary": (
                "Calculadora grátis e independente, não afiliada à FTMO: frequência de atingir a "
                "meta do FTMO Challenge 1-Step ou 2-Step ou de tocar os limites."
            ),
            "lead": (
                "A calculadora de desafio com as regras publicadas da FTMO: digite a sua taxa "
                "de acerto, o seu ganho e a sua perda médios e as suas operações por dia. O "
                "Rigor não é afiliado à FTMO."
            ),
            "faq": (
                (
                    "Que meta e que limites tem o FTMO Challenge 2-Step?",
                    "Segundo a página da FTMO lida em {as_of}: {rules[ftmo-2step-phase1]}.",
                ),
                (
                    "O que muda no FTMO Challenge 1-Step?",
                    "Segundo a página da FTMO lida em {as_of}, no 1-Step: {rules[ftmo-1step]}. A "
                    "calculadora deixa essa perda total acompanhar o maior fechamento sem parar, a "
                    "leitura mais estrita, porque a página lida não diz se ela para.",
                ),
                (
                    "Como a calculadora conta a perda diária da FTMO?",
                    "Segundo a página da FTMO lida em {as_of}: no 2-Step, "
                    "{daily[ftmo-2step-phase1]}, contada a partir do saldo registrado às 00:00 "
                    "CE(S)T; no 1-Step, {daily[ftmo-1step]}. A calculadora a confere em cada "
                    "fechamento diário: não vê a perda flutuante dentro do dia, então é otimista "
                    "diante desse limite.",
                ),
                (
                    "A calculadora diz quantos desafios da FTMO comprar?",
                    "Não. Ela divide a taxa que você declara pela probabilidade de atingir a meta "
                    "em todas as fases: é uma média de tentativas independentes com números "
                    "declarados, não um orçamento nem uma recomendação de compra.",
                ),
            ),
        },
    },
    "fundednext": {
        "es": {
            "title": "Calculadora del reto FundedNext Stellar",
            "seo_title": "Calculadora del reto FundedNext Stellar",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a FundedNext: frecuencia de "
                "alcanzar el objetivo de Stellar 2-Step, 1-Step o Lite o de tocar sus límites."
            ),
            "lead": (
                "La calculadora de reto con las reglas publicadas de FundedNext: escribe tu % "
                "de aciertos, tu ganancia y tu pérdida medias y tus operaciones por día. Rigor "
                "no está afiliado a FundedNext."
            ),
            "faq": (
                (
                    "¿Qué objetivo y qué límites tiene Stellar 2-Step?",
                    "Según la página de FundedNext leída el {as_of}: "
                    "{rules[fundednext-stellar-2step-phase1]}.",
                ),
                (
                    "¿En qué se diferencian Stellar 1-Step y Stellar Lite?",
                    "Según la página de FundedNext leída el {as_of}, Stellar 1-Step: "
                    "{rules[fundednext-stellar-1step]}. Stellar Lite: "
                    "{rules[fundednext-stellar-lite-phase1]}.",
                ),
                (
                    "¿Cómo cuenta la calculadora la pérdida diaria de FundedNext?",
                    "Según la página de FundedNext leída el {as_of}, la regla es un porcentaje del "
                    "balance inicial ({field[fundednext-stellar-2step-phase1.max_daily_loss]} en "
                    "Stellar 2-Step, {field[fundednext-stellar-1step.max_daily_loss]} en Stellar "
                    "1-Step y {field[fundednext-stellar-lite-phase1.max_daily_loss]} en Stellar "
                    "Lite) por debajo del balance al empezar el día, reiniciado a las 0:00 hora "
                    "del servidor, y cuenta pérdidas abiertas, swap y comisión. La calculadora "
                    "revisa cierres diarios sin costos ni flotante, así que frente a ese límite es "
                    "optimista.",
                ),
                (
                    "¿Hay plazo para terminar el reto de FundedNext?",
                    "Según la página de FundedNext leída el {as_of}, no hay plazo, pero las "
                    "cuentas sin operaciones durante 60 días se desactivan. La calculadora simula "
                    "hasta {horizon} días hábiles y cuenta lo que queda abierto como sin terminar.",
                ),
            ),
        },
        "en": {
            "title": "FundedNext Stellar challenge calculator",
            "seo_title": "FundedNext Stellar challenge calculator",
            "summary": (
                "Free, independent calculator, not affiliated with FundedNext: how often you would "
                "reach the Stellar 2-Step, 1-Step or Lite target or hit a limit."
            ),
            "lead": (
                "The challenge calculator with FundedNext's published rules: enter your win "
                "rate, your average win and loss and your trades per day. Rigor is not "
                "affiliated with FundedNext."
            ),
            "faq": (
                (
                    "What target and limits does Stellar 2-Step have?",
                    "According to the FundedNext page read on {as_of}: "
                    "{rules[fundednext-stellar-2step-phase1]}.",
                ),
                (
                    "How do Stellar 1-Step and Stellar Lite differ?",
                    "According to the FundedNext page read on {as_of}, Stellar 1-Step: "
                    "{rules[fundednext-stellar-1step]}. Stellar Lite: "
                    "{rules[fundednext-stellar-lite-phase1]}.",
                ),
                (
                    "How does the calculator count FundedNext's daily loss?",
                    "According to the FundedNext page read on {as_of}, the rule is a share of the "
                    "initial balance ({field[fundednext-stellar-2step-phase1.max_daily_loss]} on "
                    "Stellar 2-Step, {field[fundednext-stellar-1step.max_daily_loss]} on Stellar "
                    "1-Step and {field[fundednext-stellar-lite-phase1.max_daily_loss]} on Stellar "
                    "Lite) below the start-of-day balance, reset at 0:00 server time, and it "
                    "counts open losses, swap and commission. The calculator checks daily closes "
                    "with no costs or floating loss, so it is optimistic against that limit.",
                ),
                (
                    "Is there a deadline to finish a FundedNext challenge?",
                    "According to the FundedNext page read on {as_of}, there is none, but accounts "
                    "with no trade for 60 days are deactivated. The calculator simulates up to "
                    "{horizon} business days and counts whatever is still open as unfinished.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do desafio FundedNext Stellar",
            "seo_title": "Calculadora do desafio FundedNext Stellar",
            "summary": (
                "Calculadora grátis e independente, não afiliada à FundedNext: frequência de "
                "atingir a meta do Stellar 2-Step, 1-Step ou Lite ou de tocar os limites."
            ),
            "lead": (
                "A calculadora de desafio com as regras publicadas da FundedNext: digite a sua "
                "taxa de acerto, o seu ganho e a sua perda médios e as suas operações por dia. "
                "O Rigor não é afiliado à FundedNext."
            ),
            "faq": (
                (
                    "Que meta e que limites tem o Stellar 2-Step?",
                    "Segundo a página da FundedNext lida em {as_of}: "
                    "{rules[fundednext-stellar-2step-phase1]}.",
                ),
                (
                    "Em que o Stellar 1-Step e o Stellar Lite diferem?",
                    "Segundo a página da FundedNext lida em {as_of}, Stellar 1-Step: "
                    "{rules[fundednext-stellar-1step]}. Stellar Lite: "
                    "{rules[fundednext-stellar-lite-phase1]}.",
                ),
                (
                    "Como a calculadora conta a perda diária da FundedNext?",
                    "Segundo a página da FundedNext lida em {as_of}, a regra é uma porcentagem do "
                    "saldo inicial ({field[fundednext-stellar-2step-phase1.max_daily_loss]} no "
                    "Stellar 2-Step, {field[fundednext-stellar-1step.max_daily_loss]} no Stellar "
                    "1-Step e {field[fundednext-stellar-lite-phase1.max_daily_loss]} no Stellar "
                    "Lite) abaixo do saldo no início do dia, reiniciada às 0:00 do horário do "
                    "servidor, e conta perdas abertas, swap e comissão. A calculadora confere "
                    "fechamentos diários sem custos nem perda flutuante, então é otimista diante "
                    "desse limite.",
                ),
                (
                    "Há prazo para terminar o desafio da FundedNext?",
                    "Segundo a página da FundedNext lida em {as_of}, não há prazo, mas as contas "
                    "sem operações por 60 dias são desativadas. A calculadora simula até {horizon} "
                    "dias úteis e conta o que fica aberto como sem terminar.",
                ),
            ),
        },
    },
    "the5ers": {
        "es": {
            "title": "Calculadora del reto The5ers",
            "seo_title": "Calculadora del reto The5ers: High Stakes y más",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a The5ers: frecuencia de alcanzar "
                "el objetivo de High Stakes, Hyper Growth o Bootcamp o de tocar sus límites."
            ),
            "lead": (
                "La calculadora de reto con las reglas publicadas de The5ers: escribe tu % de "
                "aciertos, tu ganancia y tu pérdida medias y tus operaciones por día. Rigor no "
                "está afiliado a The5ers."
            ),
            "faq": (
                (
                    "¿Qué objetivo y qué límites tiene High Stakes?",
                    "Según la página de The5ers leída el {as_of}: "
                    "{rules[the5ers-high-stakes-step1]}.",
                ),
                (
                    "¿Y Hyper Growth y Bootcamp?",
                    "Según la página de The5ers leída el {as_of}, Hyper Growth: "
                    "{rules[the5ers-hyper-growth]}; la página indica además un límite diario del 3 "
                    "% que suspende la operativa del día en lugar de cerrar la cuenta, y la "
                    "calculadora no lo simula. Bootcamp: {rules[the5ers-bootcamp-step]}; la "
                    "calculadora encadena las tres fases. La pérdida total de los dos la indica el "
                    "blog de The5ers.",
                ),
                (
                    "¿Cuenta la calculadora los días mínimos como The5ers?",
                    "No del todo. Según la página de The5ers leída el {as_of}, High Stakes pide "
                    "{field[the5ers-high-stakes-step1.min_trading_days]} días que cierren con al "
                    "menos un 0,5 % del balance inicial de ganancia; la calculadora cuenta como "
                    "día de trading cualquier día con operaciones, así que ahí es optimista.",
                ),
                (
                    "¿Aplica la regla de noticias de The5ers?",
                    "No. Según la página de The5ers leída el {as_of}, High Stakes no permite "
                    "operar desde 2 minutos antes hasta 2 minutos después de noticias de alto "
                    "impacto; con cifras diarias declaradas eso no se puede simular.",
                ),
            ),
        },
        "en": {
            "title": "The5ers challenge calculator",
            "seo_title": "The5ers challenge calculator: High Stakes and more",
            "summary": (
                "Free, independent calculator, not affiliated with The5ers: how often you would "
                "reach the High Stakes, Hyper Growth or Bootcamp target or hit a limit."
            ),
            "lead": (
                "The challenge calculator with The5ers' published rules: enter your win rate, "
                "your average win and loss and your trades per day. Rigor is not affiliated "
                "with The5ers."
            ),
            "faq": (
                (
                    "What target and limits does High Stakes have?",
                    "According to The5ers' page read on {as_of}: "
                    "{rules[the5ers-high-stakes-step1]}.",
                ),
                (
                    "What about Hyper Growth and Bootcamp?",
                    "According to The5ers' page read on {as_of}, Hyper Growth: "
                    "{rules[the5ers-hyper-growth]}; the page also states a 3 % daily limit that "
                    "suspends trading for the day instead of ending the account, and the "
                    "calculator does not simulate it. Bootcamp: {rules[the5ers-bootcamp-step]}; "
                    "the calculator chains the three steps. The5ers' blog states the total loss of "
                    "both.",
                ),
                (
                    "Does the calculator count minimum days the way The5ers does?",
                    "Not quite. According to The5ers' page read on {as_of}, High Stakes asks for "
                    "{field[the5ers-high-stakes-step1.min_trading_days]} days that each close at "
                    "least 0.5 % of the initial balance in gain; the calculator counts any day "
                    "with trades as a trading day, so it is optimistic there.",
                ),
                (
                    "Does it apply The5ers' news rule?",
                    "No. According to The5ers' page read on {as_of}, High Stakes allows no trading "
                    "from 2 minutes before to 2 minutes after high-impact news; declared daily "
                    "figures cannot simulate that.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do desafio The5ers",
            "seo_title": "Calculadora do desafio The5ers: High Stakes e mais",
            "summary": (
                "Calculadora grátis e independente, não afiliada à The5ers: frequência de atingir "
                "a meta do High Stakes, Hyper Growth ou Bootcamp ou de tocar os limites."
            ),
            "lead": (
                "A calculadora de desafio com as regras publicadas da The5ers: digite a sua "
                "taxa de acerto, o seu ganho e a sua perda médios e as suas operações por dia. "
                "O Rigor não é afiliado à The5ers."
            ),
            "faq": (
                (
                    "Que meta e que limites tem o High Stakes?",
                    "Segundo a página da The5ers lida em {as_of}: "
                    "{rules[the5ers-high-stakes-step1]}.",
                ),
                (
                    "E o Hyper Growth e o Bootcamp?",
                    "Segundo a página da The5ers lida em {as_of}, Hyper Growth: "
                    "{rules[the5ers-hyper-growth]}; a página indica ainda um limite diário de 3 % "
                    "que suspende as operações do dia em vez de encerrar a conta, e a calculadora "
                    "não o simula. Bootcamp: {rules[the5ers-bootcamp-step]}; a calculadora "
                    "encadeia as três fases. A perda total dos dois é indicada no blog da The5ers.",
                ),
                (
                    "A calculadora conta os dias mínimos como a The5ers?",
                    "Não exatamente. Segundo a página da The5ers lida em {as_of}, o High Stakes "
                    "pede {field[the5ers-high-stakes-step1.min_trading_days]} dias que fechem com "
                    "pelo menos 0,5 % do saldo inicial de ganho; a calculadora conta como dia de "
                    "trading qualquer dia com operações, então ali é otimista.",
                ),
                (
                    "Ela aplica a regra de notícias da The5ers?",
                    "Não. Segundo a página da The5ers lida em {as_of}, o High Stakes não permite "
                    "operar de 2 minutos antes a 2 minutos depois de notícias de alto impacto; com "
                    "números diários declarados isso não pode ser simulado.",
                ),
            ),
        },
    },
    "topstep": {
        "es": {
            "title": "Calculadora del Trading Combine de Topstep",
            "seo_title": "Calculadora del Trading Combine de Topstep",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a Topstep: frecuencia de alcanzar "
                "el objetivo del Trading Combine o de tocar su pérdida máxima trailing."
            ),
            "lead": (
                "La calculadora de reto con las reglas publicadas de Topstep: escribe tu % de "
                "aciertos, tu ganancia y tu pérdida medias y tus operaciones por día. Rigor no "
                "está afiliado a Topstep."
            ),
            "faq": (
                (
                    "¿Cuál es la pérdida máxima de cada Trading Combine?",
                    "Según la página de Topstep leída el {as_of}: {accounts}. Sigue al mayor "
                    "cierre diario y se detiene al llegar al balance inicial.",
                ),
                (
                    "¿Qué es el objetivo de consistencia de Topstep?",
                    "Según la página de ayuda de Topstep leída el {as_of}, el mejor día debe "
                    "quedar en el {field[topstep-50k-combine.best_day_limit]} del objetivo de "
                    "ganancia o menos; si no, el objetivo sube. La calculadora lo revisa en "
                    "cierres diarios cuando una trayectoria alcanza el objetivo y lo muestra como "
                    "«dentro de la regla del mejor día».",
                ),
                (
                    "¿Simula la calculadora el límite de pérdida diaria de Topstep?",
                    "No. Según la página de Topstep leída el {as_of}, en el Trading Combine ese "
                    "límite es opcional, y la calculadora no lo simula.",
                ),
                (
                    "¿Por qué la calculadora es optimista con Topstep?",
                    "Según la página de Topstep leída el {as_of}, la pérdida máxima se vigila en "
                    "tiempo real, y una cifra por cierre diario no ve lo que ocurre dentro del "
                    "día. Además, la calculadora usa la pérdida media de tus operaciones, sin "
                    "colas ni costos.",
                ),
            ),
        },
        "en": {
            "title": "Topstep Trading Combine calculator",
            "seo_title": "Topstep Trading Combine calculator",
            "summary": (
                "Free, independent calculator, not affiliated with Topstep: how often you would "
                "reach the Trading Combine target or hit its trailing maximum loss."
            ),
            "lead": (
                "The challenge calculator with Topstep's published rules: enter your win rate, "
                "your average win and loss and your trades per day. Rigor is not affiliated "
                "with Topstep."
            ),
            "faq": (
                (
                    "What is the maximum loss of each Trading Combine?",
                    "According to the Topstep page read on {as_of}: {accounts}. It trails the "
                    "highest daily close and stops once it reaches the starting balance.",
                ),
                (
                    "What is Topstep's consistency target?",
                    "According to Topstep's help page read on {as_of}, the best day must stay at "
                    "or below {field[topstep-50k-combine.best_day_limit]} of the profit target; "
                    "otherwise the target rises. The calculator checks it on daily closes when a "
                    "path reaches the target and shows it as within the best-day rule.",
                ),
                (
                    "Does the calculator simulate Topstep's daily loss limit?",
                    "No. According to the Topstep page read on {as_of}, that limit is optional in "
                    "the Trading Combine, and the calculator does not simulate it.",
                ),
                (
                    "Why is the calculator optimistic with Topstep?",
                    "According to the Topstep page read on {as_of}, the maximum loss is monitored "
                    "in real time, and one figure per daily close cannot see what happens within "
                    "the day. The calculator also uses your trades' average loss, with no tails or "
                    "costs.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do Trading Combine da Topstep",
            "seo_title": "Calculadora do Trading Combine da Topstep",
            "summary": (
                "Calculadora grátis e independente, não afiliada à Topstep: frequência de atingir "
                "a meta do Trading Combine ou de tocar a perda máxima trailing."
            ),
            "lead": (
                "A calculadora de desafio com as regras publicadas da Topstep: digite a sua "
                "taxa de acerto, o seu ganho e a sua perda médios e as suas operações por dia. "
                "O Rigor não é afiliado à Topstep."
            ),
            "faq": (
                (
                    "Qual é a perda máxima de cada Trading Combine?",
                    "Segundo a página da Topstep lida em {as_of}: {accounts}. Ela acompanha o "
                    "maior fechamento diário e para ao chegar ao saldo inicial.",
                ),
                (
                    "O que é a meta de consistência da Topstep?",
                    "Segundo a página de ajuda da Topstep lida em {as_of}, o melhor dia deve ficar "
                    "em até {field[topstep-50k-combine.best_day_limit]} da meta de lucro; senão, a "
                    "meta sobe. A calculadora confere isso em fechamentos diários quando uma "
                    "trajetória atinge a meta e mostra como «dentro da regra do melhor dia».",
                ),
                (
                    "A calculadora simula o limite de perda diária da Topstep?",
                    "Não. Segundo a página da Topstep lida em {as_of}, no Trading Combine esse "
                    "limite é opcional, e a calculadora não o simula.",
                ),
                (
                    "Por que a calculadora é otimista com a Topstep?",
                    "Segundo a página da Topstep lida em {as_of}, a perda máxima é monitorada em "
                    "tempo real, e um número por fechamento diário não vê o que acontece dentro do "
                    "dia. Além disso, a calculadora usa a perda média das suas operações, sem "
                    "caudas nem custos.",
                ),
            ),
        },
    },
}


def _pct(value: float, locale: str) -> str:
    """A rule's share as the site writes it: "10 %", "2,5 %" ("2.5 %" in English)."""
    text = f"{value * 100:.2f}".rstrip("0").rstrip(".")
    return (text if locale == "en" else text.replace(".", ",")) + " %"


def _amount(value: float, locale: str) -> str:
    """Whole dollars with the language's thousands mark: 2,000 or 2.000."""
    text = f"{value:,.0f}"
    return text if locale == "en" else text.replace(",", ".")


#: The rules sentence's words, per language.
_RULE_WORDS: dict[str, dict[str, str]] = {
    "es": {
        "target": "objetivo de {value}",
        "target_phases": "objetivo de {values}",
        "in_phase": "{value} en la fase {n}",
        "each": "{value} en cada una de las {n} fases",
        "daily_initial": "pérdida diaria máxima de {value} del balance inicial",
        "daily_day": "pérdida diaria máxima de {value} del balance al empezar el día",
        "daily_none": "límite de pérdida diaria no simulado",
        "total_static": "pérdida total máxima de {value}, fija",
        "total_trailing": "pérdida total máxima de {value}, que sigue al mayor cierre diario",
        "total_lock": (
            "pérdida total máxima de {value}, que sigue al mayor cierre diario hasta el balance "
            "inicial"
        ),
        "days": "mínimo {n} días de trading",
        "no_days": "sin mínimo de días",
        "time": "plazo de {n} días",
        "no_time": "sin plazo",
        "best_target": "el mejor día como mucho el {value} del objetivo",
        "best_positive": "el mejor día como mucho el {value} de la ganancia de los días positivos",
        "and": " y ",
    },
    "en": {
        "target": "a {value} target",
        "target_phases": "a target of {values}",
        "in_phase": "{value} in phase {n}",
        "each": "{value} in each of the {n} phases",
        "daily_initial": "a maximum daily loss of {value} of the initial balance",
        "daily_day": "a maximum daily loss of {value} of the start-of-day balance",
        "daily_none": "daily loss limit not simulated",
        "total_static": "a maximum total loss of {value}, static",
        "total_trailing": "a maximum total loss of {value} trailing the highest daily close",
        "total_lock": (
            "a maximum total loss of {value} trailing the highest daily close up to the initial "
            "balance"
        ),
        "days": "at least {n} trading days",
        "no_days": "no minimum days",
        "time": "a {n}-day time limit",
        "no_time": "no time limit",
        "best_target": "a best day of at most {value} of the target",
        "best_positive": "a best day of at most {value} of the positive days' gain",
        "and": " and ",
    },
    "pt": {
        "target": "meta de {value}",
        "target_phases": "meta de {values}",
        "in_phase": "{value} na fase {n}",
        "each": "{value} em cada uma das {n} fases",
        "daily_initial": "perda diária máxima de {value} do saldo inicial",
        "daily_day": "perda diária máxima de {value} do saldo no início do dia",
        "daily_none": "limite de perda diária não simulado",
        "total_static": "perda total máxima de {value}, fixa",
        "total_trailing": "perda total máxima de {value}, que acompanha o maior fechamento diário",
        "total_lock": (
            "perda total máxima de {value}, que acompanha o maior fechamento diário até o saldo "
            "inicial"
        ),
        "days": "mínimo de {n} dias de trading",
        "no_days": "sem mínimo de dias",
        "time": "prazo de {n} dias",
        "no_time": "sem prazo",
        "best_target": "o melhor dia no máximo {value} da meta",
        "best_positive": "o melhor dia no máximo {value} do ganho dos dias positivos",
        "and": " e ",
    },
}


def daily_clause(key: str, locale: str) -> str:
    """The daily loss rule of ``key`` as the simulator applies it, from its preset.

    A preset without one says it is not simulated, which is all the calculator
    knows: the firm's page may still have a limit that pauses the day (its notes)."""
    locale = _locale(locale)
    words = _RULE_WORDS[locale]
    rules = PRESETS[key]
    if rules.max_daily_loss is None:
        return words["daily_none"]
    basis = "daily_day" if rules.daily_loss_basis == "start_of_day" else "daily_initial"
    return words[basis].format(value=_pct(rules.max_daily_loss, locale))


def rules_sentence(key: str, locale: str) -> str:
    """The program of ``key`` as one clause, from its presets only: it starts in
    lower case and has no full stop, so a template puts it after a colon."""
    locale = _locale(locale)
    words = _RULE_WORDS[locale]
    phases = [PRESETS[phase] for phase in firmfit.program_keys(key)]
    first = phases[0]
    targets = [_pct(rules.profit_target, locale) for rules in phases]
    repeats = phase_count(key)
    if repeats > 1 and len(phases) == 1:
        target = words["target_phases"].format(
            values=words["each"].format(value=targets[0], n=repeats)
        )
    elif len(set(targets)) == 1:
        target = words["target"].format(value=targets[0])
    else:
        values = [words["in_phase"].format(value=v, n=i) for i, v in enumerate(targets, 1)]
        target = words["target_phases"].format(
            values=", ".join(values[:-1]) + words["and"] + values[-1]
        )
    parts = [target, daily_clause(key, locale)]
    total = {"trailing_eod": "total_trailing", "trailing_eod_lock": "total_lock"}.get(
        first.total_loss_type, "total_static"
    )
    parts.append(words[total].format(value=_pct(first.max_total_loss, locale)))
    days = first.min_trading_days
    parts.append(words["days"].format(n=days) if days else words["no_days"])
    time = first.time_limit_days
    parts.append(words["time"].format(n=time) if time else words["no_time"])
    if first.best_day_limit is not None:
        best = "best_positive" if first.best_day_basis == "positive_days" else "best_target"
        parts.append(words[best].format(value=_pct(first.best_day_limit, locale)))
    return "; ".join(parts)


def _accounts_sentence(locale: str) -> str:
    """Topstep's sizes and maximum losses, from ``ACCOUNT_SIZES`` and the presets."""
    pieces = []
    for key in firm_programs("topstep"):
        account = ACCOUNT_SIZES[key]
        loss = PRESETS[key].max_total_loss * account
        pieces.append(
            {
                "es": "{program}, USD {loss} ({share} de {account})",
                "en": "{program}, USD {loss} ({share} of {account})",
                "pt": "{program}, USD {loss} ({share} de {account})",
            }[locale].format(
                program=PRESETS[key].program,
                loss=_amount(loss, locale),
                share=_pct(PRESETS[key].max_total_loss, locale),
                account=_amount(account, locale),
            )
        )
    return "; ".join(pieces)


class _Lookup(dict[str, str]):
    """``{name[key]}`` in a FAQ template: ``fill(key)``, worked out from the presets."""

    def __init__(self, fill: Callable[[str], str]) -> None:
        super().__init__()
        self.fill = fill

    def __missing__(self, key: str) -> str:
        return self.fill(key)


def _field(spec: str, locale: str) -> str:
    """``key.attribute`` of a preset as the page writes it: a share as a percentage."""
    key, _, name = spec.rpartition(".")
    value = getattr(PRESETS[key], name)
    if isinstance(value, float):
        return _pct(value, locale)
    return str(value)


def firm_faq(firm: str, locale: str) -> tuple[tuple[str, str], ...]:
    """The firm page's questions with their answers filled from the presets.

    An answer names its figures through ``{rules[key]}`` (the program's rules
    sentence), ``{daily[key]}`` (its daily loss rule), ``{field[key.name]}``
    (one preset field), ``{accounts}`` (Topstep's sizes) and ``{horizon}`` (the
    simulator's business days), and its date through ``{as_of}``; the few
    figures that are only in a preset's notes are written out, and a test
    checks each one against those notes."""
    locale = _locale(locale)
    keys = firm_programs(firm)
    fill = {
        "rules": _Lookup(lambda key: rules_sentence(key, locale)),
        "daily": _Lookup(lambda key: daily_clause(key, locale)),
        "field": _Lookup(lambda spec: _field(spec, locale)),
        "as_of": PRESETS[keys[0]].as_of,
        "accounts": _accounts_sentence(locale) if firm == "topstep" else "",
        "horizon": str(horizon(keys[0])),
    }
    return tuple(
        (question, answer.format(**fill)) for question, answer in FIRM_COPY[firm][locale]["faq"]
    )


def firm_copy(firm: str, locale: str) -> dict[str, Any]:
    return FIRM_COPY[firm][_locale(locale)]


__all__ = [
    "CHALLENGE_PATH",
    "COPY",
    "FIELDS",
    "FIRMS",
    "FIRM_COPY",
    "PAGES",
    "PROGRAMS",
    "REQUESTS_PER_HOUR",
    "SAMPLES",
    "SEED",
    "SHARE_REF",
    "SIMULATOR_MAX_DAYS",
    "SIZES",
    "SYNTHETIC_DAYS",
    "TRADED_FLAT_DAY",
    "ChallengeInput",
    "ChallengeReading",
    "Parsed",
    "ProgramRun",
    "account_size",
    "challenge_url",
    "compute",
    "daily_clause",
    "firm_copy",
    "firm_faq",
    "firm_programs",
    "horizon",
    "page_paths",
    "parse",
    "phase_count",
    "rules_sentence",
    "run_program",
    "share_url",
    "share_values",
    "submitted",
    "synthetic_daily_returns",
]
