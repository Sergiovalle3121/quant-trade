"""The free risk-of-ruin calculator: declared figures, fixed-size paths, Wilson's lower end.

A visitor types what they already know about their trading (win rate,
average win and loss, a ruin threshold and a horizon in trades). There is no
file, so the page draws independent trades from those figures with a fixed
seed and measures, path by path, whether the balance touches the threshold
within the horizon and how deep it falls from its peak. Every trade has the
average size, counted on the initial balance, as the classic ruin formula
assumes; that formula is shown next to the simulation when it applies (an
average win equal to the average loss). The longest losing streak comes from
the engine's own ``streaks.longest_run_tail``, not from the paths.

Every input is DECLARED and every result is computed from it, so the page
labels results the way the challenge calculator does. Nothing is stored and
no file, network or database is touched. With the number of trades behind
the win rate, everything is computed again at the lower end of the win
rate's 95 % Wilson interval (``winrate.read``), which is the point of the
page: with few trades a 60 % win rate may really be much less, and the ruin
figure moves with it.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode

import numpy as np

from quant_trade.audit import winrate
from quant_trade.audit.challenge_calc import (
    MAX_R,
    MAX_TRADE_SHARE,
    RISK_RANGE,
    TRADES_RANGE,
    UNITS,
    WIN_RATE_RANGE,
    _count,
    _number,
    _text,
)
from quant_trade.audit.public_card import PublicClaim, _num, _wilson
from quant_trade.audit.streaks import RARE, _longest_at_least, longest_run_tail

#: The page's path in each language.
RUIN_PATH: dict[str, str] = {
    "es": "/calculadora-ruina",
    "en": "/en/risk-of-ruin-calculator",
    "pt": "/pt/calculadora-risco-de-ruina",
}
#: The query fields, in the order a shared link writes them.
FIELDS = ("win_rate", "unit", "avg_win", "avg_loss", "risk", "trades", "ruin", "horizon")
#: The funnel tag carried by a shared result (``funnel.REF_TAGS``).
SHARE_REF = "ruina"
#: The ruin threshold when the field is empty, in percent of the initial balance,
#: and the thresholds every result also shows (the ones a challenge sets).
DEFAULT_RUIN = 50.0
RUIN_SHORTCUTS: tuple[float, ...] = (20.0, 30.0, 50.0)
#: Trades each path walks when the field is empty.
DEFAULT_HORIZON = 500
#: Paths per computation and the one seed for all of them: the same link, the
#: same figures. The uniforms are drawn before the win rate is applied, so a
#: lower rate only turns winners into losers on the same paths.
SAMPLES = 4000
SEED = 20261010
#: Trades drawn per block, so a path of the longest horizon never sits in memory whole.
BLOCK = 200
#: Touching the threshold to within this: sums of equal steps land a hair off it.
TOUCH = 1e-9
#: Computations per address and sliding hour; past it the page shows the form only.
REQUESTS_PER_HOUR = 120
#: Cached readings per process.
CACHE_SIZE = 64

#: Input bounds beyond the challenge calculator's. Outside them the form says which.
#: The longest horizon keeps a request (two simulations, declared and lower end,
#: and two streaks) under a second or so on a small instance.
RUIN_RANGE = (0.0, 100.0)  # both ends excluded
HORIZON_RANGE = (10, 2_000)
#: Streak lengths asked of the engine's tail at once: its memory grows with their
#: square (about 8 MB here). Past it, win rates under about 1 % over the longest
#: horizon, the same recurrence runs one length at a time.
STREAK_TOP = 1024


def _locale(locale: str) -> str:
    return locale if locale in RUIN_PATH else "es"


def ruin_url(locale: str) -> str:
    return RUIN_PATH[_locale(locale)]


def _percent(value: float, locale: str) -> str:
    return f"{_num(value * 100, locale, 1)} %"


@dataclass(frozen=True)
class RuinInput:
    """The declared figures, validated, as the visitor wrote them."""

    #: Win rate in percent, 0 < x < 100.
    win_rate_pct: float
    #: How the average win and loss are written: ``pct`` of the balance or ``r``.
    unit: str
    avg_win: float
    avg_loss: float
    #: Risk per trade in percent of the balance, only with ``unit == "r"``.
    risk: float | None
    #: The ruin threshold in percent of the initial balance, 0 < x < 100.
    ruin_pct: float
    #: Trades each path walks.
    horizon: int
    #: Closed trades behind the win rate, when declared.
    trades: int | None = None

    @property
    def win_rate(self) -> float:
        return self.win_rate_pct / 100.0

    def _share(self, value: float) -> float:
        scale = (self.risk or 0.0) / 100.0 if self.unit == "r" else 0.01
        return value * scale

    @property
    def win(self) -> float:
        """A winning trade's gain, as a share of the initial balance."""
        return self._share(self.avg_win)

    @property
    def loss(self) -> float:
        """A losing trade's loss, as a share of the initial balance."""
        return self._share(self.avg_loss)

    @property
    def ruin(self) -> float:
        """The threshold as a share of the initial balance lost."""
        return self.ruin_pct / 100.0

    @property
    def equal_sizes(self) -> bool:
        """The classic formula's case: the average win equals the average loss."""
        return self.avg_win == self.avg_loss


@dataclass(frozen=True)
class Parsed:
    """What the form sent: the input when it is complete and valid, the error
    codes otherwise (``COPY[locale]["error_<code>"]``), and the values to show
    back in the form, only the ones that were valid."""

    value: RuinInput | None
    errors: tuple[str, ...]
    shown: dict[str, str]


def empty_form() -> dict[str, str]:
    """What the form shows before anything was typed: the defaults."""
    return {"unit": "pct", "ruin": _text(DEFAULT_RUIN), "horizon": str(DEFAULT_HORIZON)}


def parse(values: Mapping[str, str]) -> Parsed:
    """Validate the query fields, with the challenge calculator's parser and bounds."""
    raw = {name: str(values.get(name, "") or "").strip() for name in FIELDS}
    errors: list[str] = []
    shown: dict[str, str] = {}
    numbers: dict[str, float] = {}

    def decimal(name: str) -> float | None:
        if not raw[name]:
            return None
        try:
            return _number(raw[name])
        except ValueError:
            errors.append("number")
            return None

    def count(name: str, low: int, high: int, default: int | None) -> int | None:
        if not raw[name]:
            if default is not None:
                shown[name] = str(default)
            return default
        try:
            value = _count(raw[name])
        except ValueError:
            errors.append(name)
            return None
        if low <= value <= high:
            shown[name] = str(value)
            return value
        errors.append(name)
        return None

    unit = raw["unit"] or "pct"
    if unit not in UNITS:
        errors.append("unit")
        unit = "pct"
    shown["unit"] = unit
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
    ruin = decimal("ruin")
    if ruin is None:
        if not raw["ruin"]:
            numbers["ruin"] = DEFAULT_RUIN
    elif RUIN_RANGE[0] < ruin < RUIN_RANGE[1]:
        numbers["ruin"] = ruin
    else:
        errors.append("ruin")
    horizon = count("horizon", *HORIZON_RANGE, DEFAULT_HORIZON)
    trades = count("trades", *TRADES_RANGE, None)
    shown.update({name: _text(value) for name, value in numbers.items()})
    required = ("win_rate", "avg_win", "avg_loss") + (("risk",) if unit == "r" else ())
    if not errors and any(name not in numbers for name in required):
        errors.append("missing")
    if errors or horizon is None:
        return Parsed(None, tuple(dict.fromkeys(errors)), shown)
    value = RuinInput(
        win_rate_pct=numbers["win_rate"],
        unit=unit,
        avg_win=numbers["avg_win"],
        avg_loss=numbers["avg_loss"],
        risk=numbers.get("risk") if unit == "r" else None,
        ruin_pct=numbers["ruin"],
        horizon=horizon,
        trades=trades,
    )
    return Parsed(value, (), share_values(value))


def submitted(values: Mapping[str, str]) -> bool:
    """Whether the query carries any of the form's fields with a value."""
    return any(str(values.get(name, "") or "").strip() for name in FIELDS)


def share_values(value: RuinInput) -> dict[str, str]:
    """The validated input as query strings that parse back to the same numbers."""
    out = {
        "win_rate": _text(value.win_rate_pct),
        "unit": value.unit,
        "avg_win": _text(value.avg_win),
        "avg_loss": _text(value.avg_loss),
    }
    if value.risk is not None:
        out["risk"] = _text(value.risk)
    if value.trades is not None:
        out["trades"] = str(value.trades)
    out["ruin"] = _text(value.ruin_pct)
    out["horizon"] = str(value.horizon)
    return out


def share_url(locale: str, value: RuinInput) -> str:
    """The page's own address for a result, tagged so /panel counts the shares."""
    return ruin_url(locale) + "?" + urlencode({**share_values(value), "ref": SHARE_REF})


@dataclass(frozen=True)
class Paths:
    """What each simulated path leaves behind."""

    #: The lowest balance each path reached, as a share of the initial one.
    lowest: np.ndarray
    #: The deepest fall from its own peak each path had, 0 to 1.
    drawdown: np.ndarray


def simulate(
    win_rate: float,
    win: float,
    loss: float,
    horizon: int,
    *,
    samples: int = SAMPLES,
    seed: int = SEED,
) -> Paths:
    """``samples`` paths of ``horizon`` independent trades that win ``win`` with
    probability ``win_rate`` or lose ``loss``, both shares of the initial balance.

    Trades have a fixed size, so a path is the initial balance plus a running
    sum; it walks the whole horizon, ruined or not, so the drawdown is the
    horizon's. The uniforms come out of the seed in blocks, before the rate is
    applied: the same seed at a lower rate gives the same paths with some
    winners turned into losers."""
    rng = np.random.default_rng(seed)
    balance = np.ones(samples)
    peak = np.ones(samples)
    lowest = np.ones(samples)
    deepest = np.zeros(samples)
    for start in range(0, horizon, BLOCK):
        width = min(BLOCK, horizon - start)
        wins = rng.random((samples, width)) < win_rate
        path = balance[:, None] + np.cumsum(np.where(wins, win, -loss), axis=1)
        peaks = np.maximum.accumulate(np.concatenate([peak[:, None], path], axis=1), axis=1)
        drawdown = 1.0 - path / peaks[:, 1:]
        deepest = np.maximum(deepest, drawdown.max(axis=1))
        lowest = np.minimum(lowest, path.min(axis=1))
        balance, peak = path[:, -1], peaks[:, -1]
    return Paths(lowest=lowest, drawdown=np.clip(deepest, 0.0, 1.0))


def ruin_share(paths: Paths, ruin: float) -> float:
    """The share of paths whose balance touched ``1 - ruin`` or fell below it."""
    return float(np.mean(paths.lowest <= 1.0 - ruin + TOUCH))


def classic_ruin(win_rate: float, units: int) -> float:
    """The textbook ruin probability without a horizon, for wins equal to losses:
    ``(q / p) ** units``, where ``units`` is the net losses it takes to touch the
    threshold: a whole number, since a path cannot lose half a trade (``run``
    rounds the threshold up to the next loss). With no edge or a negative one
    it is 1."""
    q = 1.0 - win_rate
    if win_rate <= q:
        return 1.0
    return float((q / win_rate) ** units)


def _streak_guess(horizon: int, q: float) -> int:
    """About the longest losing streak 1 in 20 histories reach: the length past
    which ``horizon · p · q^k``, the expected count of such runs, falls under
    ``RARE``, with a margin. The whole horizon when that never happens."""
    p = 1.0 - q
    if horizon * p <= RARE:
        return horizon
    return math.ceil(1.1 * math.log(RARE / (horizon * p)) / math.log(q)) + 4


def _tail_at(horizon: int, q: float, k: int) -> float:
    """``P(longest run of losses >= k)`` in ``horizon`` independent trades, for
    one ``k``: the recurrence behind the engine's ``longest_run_tail``, the same
    operations in the same order, so both agree to the last digit. Linear time
    in the horizon and no memory to speak of."""
    if k <= 0:
        return 1.0
    if k > horizon:
        return 0.0
    p = 1.0 - q
    qk = q**k
    # none[m]: the probability of no run of k losses in m trades.
    none = [1.0] * (horizon + 1)
    none[k] = 1.0 - qk
    for m in range(k + 1, horizon + 1):
        none[m] = none[m - 1] - p * qk * none[m - k - 1]
    return min(1.0, max(0.0, 1.0 - none[horizon]))


@lru_cache(maxsize=CACHE_SIZE * 2)
def losing_streaks(horizon: int, win_rate: float) -> tuple[int, int]:
    """The longest losing streak of ``horizon`` independent trades: the length
    at least half the histories reach, and the one at least 1 in 20 reach, from
    the engine's exact ``longest_run_tail``.

    The tail is asked for up to about the rare length (``_streak_guess``), at
    most ``STREAK_TOP`` lengths at once; while its last value still reaches
    ``RARE`` the length asked doubles. Past ``STREAK_TOP`` (win rates under
    about 1 %, or Wilson's lower end with one trade behind the rate) both
    lengths come from the same recurrence one length at a time (``_tail_at``),
    so no request holds the tail's square in memory. Cached: the two runs of
    one reading share a horizon, and readings share both."""
    q = 1.0 - win_rate
    limit = min(horizon, STREAK_TOP)
    top = min(limit, max(8, _streak_guess(horizon, q)))
    tail = longest_run_tail(horizon, q, top)
    while top < limit and tail[-1] >= RARE:
        top = min(limit, top * 2)
        tail = longest_run_tail(horizon, q, top)
    if tail[-1] < RARE or top == horizon:
        median = int(np.max(np.nonzero(tail >= 0.5)[0]))
        rare = int(np.max(np.nonzero(tail >= RARE)[0]))
        return median, rare
    known: dict[int, float] = {}

    def at(k: int) -> float:
        if k not in known:
            known[k] = _tail_at(horizon, q, k)
        return known[k]

    return _longest_at_least(at, horizon, 0.5), _longest_at_least(at, horizon, RARE)


@dataclass(frozen=True)
class RuinRun:
    """The declared figures at one win rate: expectancy, ruin, drawdown and streak."""

    win_rate: float
    #: Expected result per trade, in R and as a share of the initial balance.
    expectancy_r: float
    expectancy_share: float
    #: The share of paths that touched the declared threshold within the horizon.
    ruin: float
    #: The same for each of ``RUIN_SHORTCUTS``, as (threshold in percent, share).
    shortcuts: tuple[tuple[float, float], ...]
    #: The classic formula, only when the average win equals the average loss.
    classic: float | None
    #: The horizon's deepest drawdown: the median path's and the 95th percentile's.
    drawdown_p50: float
    drawdown_p95: float
    #: The longest losing streak half the histories reach, and 1 in 20 reach.
    streak_median: int
    streak_rare: int


def run(value: RuinInput, win_rate: float) -> RuinRun:
    """Everything the page shows for ``value`` at ``win_rate`` (declared or Wilson's lower end)."""
    q = 1.0 - win_rate
    expectancy_share = win_rate * value.win - q * value.loss
    if value.unit == "r":
        expectancy_r = win_rate * value.avg_win - q * value.avg_loss
    else:
        # In percent of the balance, one R is the average loss.
        expectancy_r = expectancy_share / value.loss
    paths = simulate(win_rate, value.win, value.loss, value.horizon)
    classic = None
    if value.equal_sizes:
        # The net losses that touch the threshold, with the simulation's own tolerance:
        # half a loss still takes one, and 0.07 / 0.01 (7.000000000000001) takes seven.
        units = max(1, math.ceil((value.ruin - TOUCH) / value.loss))
        classic = classic_ruin(win_rate, units)
    median, rare = losing_streaks(value.horizon, win_rate)
    return RuinRun(
        win_rate=win_rate,
        expectancy_r=expectancy_r,
        expectancy_share=expectancy_share,
        ruin=ruin_share(paths, value.ruin),
        shortcuts=tuple((pct, ruin_share(paths, pct / 100.0)) for pct in RUIN_SHORTCUTS),
        classic=classic,
        drawdown_p50=float(np.percentile(paths.drawdown, 50)),
        drawdown_p95=float(np.percentile(paths.drawdown, 95)),
        streak_median=median,
        streak_rare=rare,
    )


@dataclass(frozen=True)
class RuinReading:
    """What the page shows, every figure from ``run`` or ``winrate.read``."""

    declared: RuinRun
    #: The win rate's 95 % Wilson interval, with the declared trades.
    interval: tuple[float, float] | None
    #: The same figures at the interval's lower end.
    lower: RuinRun | None


@lru_cache(maxsize=CACHE_SIZE)
def compute(value: RuinInput) -> RuinReading:
    """The declared figures and their lower-bound twin. Pure and cached: the same
    input (the same link) gives the same figures."""
    declared = run(value, value.win_rate)
    interval = None
    lower = None
    if value.trades is not None:
        interval = winrate.read(PublicClaim(trades=value.trades, win_rate=value.win_rate)).interval
        if interval is not None:
            lower = run(value, interval[0])
    return RuinReading(declared=declared, interval=interval, lower=lower)


#: The worked figure of the questions: Wilson's lower end for 60 % in 50 trades.
FAQ_EXAMPLE = (0.60, 50)


def faq(locale: str) -> tuple[tuple[str, str], ...]:
    """The page's questions with the figure in them computed, never typed."""
    low = _percent(_wilson(*FAQ_EXAMPLE)[0], locale)
    rate = _percent(FAQ_EXAMPLE[0], locale)
    return tuple(
        (question, answer.format(rate=rate, n=FAQ_EXAMPLE[1], low=low))
        for question, answer in COPY[_locale(locale)]["faq"]
    )


COPY: dict[str, dict[str, Any]] = {
    "es": {
        "nav": "Calculadora de riesgo de ruina",
        "eyebrow": "Calculadora gratis",
        "title": "¿Qué probabilidad tienes de tocar tu umbral de ruina?",
        "seo_title": "Calculadora de riesgo de ruina y esperanza matemática",
        "summary": (
            "Calculadora gratis de riesgo de ruina, esperanza matemática, drawdown y racha con "
            "cifras declaradas, y cuánto cambian en el límite inferior del % de aciertos."
        ),
        "lead": (
            "Escribe tu % de aciertos, tu ganancia y tu pérdida medias y un umbral de ruina: "
            "calculamos la esperanza matemática por operación, la probabilidad de tocar el "
            "umbral dentro del horizonte, el drawdown máximo y la racha perdedora. Sin "
            "registro ni archivo."
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
        "trades": "Operaciones de tu historial (opcional)",
        "trades_help": (
            "Cuántas operaciones cerradas hay detrás de tu % de aciertos. Con este dato "
            "también vemos el resultado con el límite inferior de su intervalo."
        ),
        "ruin": "Umbral de ruina (% del balance inicial)",
        "ruin_help": (
            "Quedar en ese porcentaje del balance inicial, o por debajo, cuenta como tocar el "
            "umbral. Por defecto 50 %; para un reto prueba 20 % o 30 %: el resultado muestra "
            "también esos umbrales."
        ),
        "horizon": "Horizonte (operaciones)",
        "horizon_help": (
            "Cuántas operaciones recorre cada trayectoria. Por defecto 500; como mucho 2.000."
        ),
        "submit": "Calcular",
        "error_number": "Revisa los números: escribe cifras como 55, 0,8 o 1.5.",
        "error_missing": (
            "Faltan cifras: escribe el % de aciertos, la ganancia media y la pérdida media (y "
            "el riesgo por operación si escribes en R)."
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
        "error_ruin": "El umbral de ruina debe ser mayor que 0 y menor que 100 % del balance.",
        "error_horizon": "El horizonte debe ser un número entero de operaciones entre 10 y 2.000.",
        "error_trades": (
            "Las operaciones del historial deben ser un número entero entre 1 y 10.000.000."
        ),
        "error_invalid": "Revisa los campos: cada uno debe aparecer una sola vez.",
        "limited": (
            "Demasiados cálculos desde esta dirección en la última hora. Inténtalo más tarde."
        ),
        "result_title": "Resultado",
        "simulated": (
            "Cifras declaradas: {rate} de aciertos, {win} por operación ganadora, {loss} por "
            "perdedora, umbral del {ruin} del balance inicial, horizonte de {horizon} "
            "operaciones."
        ),
        "row_expectancy_r": "Esperanza por operación (R)",
        "row_expectancy_pct": "Esperanza por operación (% del balance inicial)",
        "row_ruin": "Tocar el umbral del {ruin} en {horizon} operaciones",
        "row_classic": "Fórmula clásica sin horizonte (ganancia = pérdida)",
        "row_dd_median": "Drawdown máximo del horizonte, mediana",
        "row_dd_p95": "Drawdown máximo del horizonte, p95 (el 5 % peor)",
        "row_streak": "Racha perdedora más larga, mediana",
        "row_streak_rare": "Racha perdedora más larga, 1 de cada 20 historiales",
        "r_unit": "{n} R",
        "trades_unit": "{n} operaciones",
        "r_is_loss": "En % del balance, 1 R es tu pérdida media.",
        "no_classic": "solo cuando la ganancia media es igual a la pérdida media",
        "classic_note": (
            "La fórmula clásica, (q ÷ p) elevado al número de pérdidas netas necesarias para "
            "tocar el umbral, cuenta las trayectorias que lo tocan en cualquier momento, sin "
            "límite de operaciones. En teoría es igual o mayor que la simulada; la cifra "
            "simulada lleva además el error de muestreo de sus trayectorias, de alrededor de "
            "un punto."
        ),
        "thresholds_title": "Otros umbrales con las mismas cifras",
        "col_threshold": "Umbral (% del balance inicial)",
        "col_touch": "Tocarlo en {horizon} operaciones",
        "computed": "Calculado a partir de lo declarado",
        "paths_note": (
            "Cifras de {samples} trayectorias de {horizon} operaciones independientes con tus "
            "cifras, cada operación del tamaño medio sobre el balance inicial. Semilla fija: el "
            "mismo enlace da el mismo resultado. La racha sale de la función del motor para "
            "operaciones independientes, no de las trayectorias."
        ),
        "lower_title": "Con el límite inferior de tu % de aciertos",
        "lower_text": (
            "Con {n} operaciones, un {rate} de aciertos declarado es compatible con uno real "
            "de {low}: es el límite inferior del intervalo de confianza al 95 % (Wilson). Con "
            "ese {low} y las mismas cifras, la probabilidad de tocar el umbral cambia de "
            "{ruin} a {ruin_low}."
        ),
        "lower_text_same": (
            "Con {n} operaciones, un {rate} de aciertos declarado es compatible con uno real "
            "de {low}: es el límite inferior del intervalo de confianza al 95 % (Wilson). Con "
            "ese {low} y las mismas cifras, la probabilidad de tocar el umbral sigue en {ruin}."
        ),
        "lower_computed": "calculado con tus operaciones y tu % de aciertos declarados (Wilson)",
        "lower_missing": (
            "Escribe cuántas operaciones tiene tu historial: con pocas, un 60 % de aciertos "
            "puede ser en realidad bastante menos, y la ruina cambia con él."
        ),
        "lower_link": "Calcular el intervalo de mi % de aciertos",
        "col_figure": "Cifra",
        "share_title": "Compartir este resultado",
        "share_text": (
            "Mis cifras declaradas en la calculadora de riesgo de ruina de Rigor: esperanza, "
            "umbral, drawdown y racha. No es una auditoría ni una recomendación. {url}"
        ),
        "share_public": (
            "El enlace contiene las cifras que escribiste; cualquiera con el enlace puede leerlas."
        ),
        "faq_title": "Preguntas frecuentes",
        "faq": [
            (
                "¿Qué es el riesgo de ruina?",
                "Es la probabilidad de que el balance quede en un umbral que tú fijas, o por "
                "debajo, dentro de un número de operaciones: por ejemplo, el 50 % del balance "
                "inicial en 500 operaciones. Aquí se calcula con trayectorias de operaciones "
                "independientes hechas con tus cifras declaradas, y se muestra al lado la "
                "fórmula clásica cuando la ganancia media es igual a la pérdida media.",
            ),
            (
                "¿Por qué pide cuántas operaciones tiene mi historial?",
                "Porque un % de aciertos medido en pocas operaciones tiene un intervalo ancho: "
                "con {n} operaciones, un {rate} declarado es compatible con un {low}. La "
                "calculadora repite todo con el límite inferior del intervalo de Wilson al "
                "95 % y muestra las dos cifras lado a lado.",
            ),
            (
                "¿En qué se diferencia del drawdown?",
                "El umbral de ruina se mide desde el balance inicial; el drawdown, desde el "
                "máximo alcanzado hasta ese momento. La tabla muestra el drawdown máximo de la "
                "trayectoria mediana y el del 5 % de trayectorias peores (p95) dentro del "
                "horizonte.",
            ),
        ],
        "how_title": "Qué calcula y qué supone",
        "how": [
            "Cada trayectoria tiene operaciones independientes: cada una gana tu ganancia "
            "media con tu % de aciertos o pierde tu pérdida media. Tamaño fijo, calculado "
            "sobre el balance inicial, como en la fórmula clásica de ruina.",
            "Tocar el umbral es quedar en el porcentaje del balance inicial que fijaste, o por "
            "debajo, en cualquier operación del horizonte; la trayectoria sigue hasta el final "
            "para medir el drawdown.",
            "El drawdown máximo se mide desde el máximo alcanzado por cada trayectoria; la "
            "racha perdedora más larga sale de longest_run_tail, la función del motor de Rigor "
            "para operaciones independientes.",
            "Todas las ganancias y pérdidas tienen el tamaño medio: sin colas, deslizamiento ni "
            "costos. Las pérdidas reales varían, así que con un historial real el umbral suele "
            "tocarse más a menudo.",
            "El intervalo de Wilson al 95 % da el rango de % de aciertos compatible con tu "
            "muestra si las operaciones son independientes; con pocas operaciones es ancho.",
            "No guardamos tus cifras en ninguna base de datos ni archivo; como van en el "
            "enlace, el registro de acceso del servidor puede contener la dirección pedida. Es "
            "un cálculo con cifras declaradas, no una auditoría, una previsión ni una "
            "recomendación de tamaño.",
        ],
        "cta_title": "Con tu historial real",
        "cta": (
            "Con tu historial real, el informe mide la racha, el drawdown y la ruina con tus "
            "operaciones de verdad: sube tu archivo. El informe remuestrea tus propios días y "
            "compara tu racha con tus operaciones en orden aleatorio."
        ),
        "cta_button": "Subir mi archivo",
        "sample_link": "Ver un informe de ejemplo",
        "read_title": "Para seguir",
    },
    "en": {
        "nav": "Risk of ruin calculator",
        "eyebrow": "Free calculator",
        "title": "How likely are you to touch your ruin threshold?",
        "seo_title": "Risk of ruin and expectancy calculator",
        "summary": (
            "Free risk of ruin, expectancy, drawdown and losing streak calculator from your "
            "declared figures, and how much they change at the lower end of your win rate."
        ),
        "lead": (
            "Enter your win rate, your average win and loss and a ruin threshold: we compute "
            "the expectancy per trade, the chance of touching the threshold within the "
            "horizon, the maximum drawdown and the losing streak. No signup, no file."
        ),
        "form_title": "Your figures",
        "optional": (
            "Optional fields may stay empty: whatever depends on them will show as NOT_MEASURED."
        ),
        "win_rate": "Win rate (%)",
        "win_rate_help": "The share of winning trades. For example 55.",
        "unit": "How you write the win and the loss",
        "unit_help": "In % of the balance per trade, or in R with your risk per trade.",
        "unit_options": {"pct": "In % of the balance", "r": "In R, with the risk per trade"},
        "avg_win": "Average win per winning trade",
        "avg_win_help": "In % of the balance (for example 0.8) or in R (for example 1.5).",
        "avg_loss": "Average loss per losing trade",
        "avg_loss_help": "In % of the balance (for example 0.5) or in R (usually 1).",
        "risk": "Risk per trade (% of the balance)",
        "risk_help": (
            "Only when you write in R: how much of the balance you risk on each trade. For "
            "example 0.5."
        ),
        "trades": "Trades in your history (optional)",
        "trades_help": (
            "How many closed trades sit behind your win rate. With it we also show the result "
            "at the lower end of its interval."
        ),
        "ruin": "Ruin threshold (% of the initial balance)",
        "ruin_help": (
            "Reaching that share of the initial balance, or falling below it, at any point "
            "counts as touching the threshold. 50 % by default; for a challenge try 20 % or "
            "30 %: the result shows those thresholds too."
        ),
        "horizon": "Horizon (trades)",
        "horizon_help": "How many trades each path walks. 500 by default; at most 2,000.",
        "submit": "Calculate",
        "error_number": "Check the numbers: write figures like 55, 0.8 or 1,5.",
        "error_missing": (
            "Figures are missing: enter the win rate, the average win and the average loss "
            "(and the risk per trade when you write in R)."
        ),
        "error_win_rate": "The win rate must be above 0 and below 100.",
        "error_unit": "Choose whether you write the win and the loss in % of the balance or in R.",
        "error_avg_win": (
            "The average win must be above 0 and, per trade, at most 50 % of the balance (in "
            "R, at most 100 R)."
        ),
        "error_avg_loss": (
            "The average loss must be above 0 and, per trade, at most 50 % of the balance (in "
            "R, at most 100 R)."
        ),
        "error_risk": "The risk per trade must be above 0 and at most 20 %.",
        "error_ruin": "The ruin threshold must be above 0 and below 100 % of the balance.",
        "error_horizon": "The horizon must be a whole number of trades between 10 and 2,000.",
        "error_trades": "The trades in your history must be a whole number from 1 to 10,000,000.",
        "error_invalid": "Check the fields: each one must appear once.",
        "limited": "Too many calculations from this address in the last hour. Try again later.",
        "result_title": "Result",
        "simulated": (
            "Declared figures: {rate} win rate, {win} per winning trade, {loss} per losing "
            "trade, threshold at {ruin} of the initial balance, horizon of {horizon} trades."
        ),
        "row_expectancy_r": "Expectancy per trade (R)",
        "row_expectancy_pct": "Expectancy per trade (% of the initial balance)",
        "row_ruin": "Touching the {ruin} threshold within {horizon} trades",
        "row_classic": "Classic formula without a horizon (win = loss)",
        "row_dd_median": "Maximum drawdown of the horizon, median",
        "row_dd_p95": "Maximum drawdown of the horizon, p95 (the worst 5 %)",
        "row_streak": "Longest losing streak, median",
        "row_streak_rare": "Longest losing streak, 1 in 20 histories",
        "r_unit": "{n} R",
        "trades_unit": "{n} trades",
        "r_is_loss": "In % of the balance, one R is your average loss.",
        "no_classic": "only when the average win equals the average loss",
        "classic_note": (
            "The classic formula, (q ÷ p) to the power of the net losses it takes to touch "
            "the threshold, counts the paths that touch it at any time, with no limit on "
            "trades. In theory it is equal to or above the simulated figure; the simulated "
            "figure also carries the sampling error of its paths, around one point."
        ),
        "thresholds_title": "Other thresholds with the same figures",
        "col_threshold": "Threshold (% of the initial balance)",
        "col_touch": "Touching it within {horizon} trades",
        "computed": "Computed from declared figures",
        "paths_note": (
            "Figures from {samples} paths of {horizon} independent trades with your figures, "
            "each trade of the average size on the initial balance. Fixed seed: the same link "
            "gives the same result. The streak comes from the engine's function for "
            "independent trades, not from the paths."
        ),
        "lower_title": "At the lower end of your win rate",
        "lower_text": (
            "With {n} trades, a declared {rate} win rate is compatible with a real {low}: the "
            "lower end of the 95 % confidence interval (Wilson). At that {low}, with the same "
            "figures, the chance of touching the threshold moves from {ruin} to {ruin_low}."
        ),
        "lower_text_same": (
            "With {n} trades, a declared {rate} win rate is compatible with a real {low}: the "
            "lower end of the 95 % confidence interval (Wilson). At that {low}, with the same "
            "figures, the chance of touching the threshold stays at {ruin}."
        ),
        "lower_computed": "computed with your declared trades and win rate (Wilson)",
        "lower_missing": (
            "Enter how many trades your history has: with few of them, a 60 % win rate may "
            "really be a good deal less, and the ruin figure moves with it."
        ),
        "lower_link": "Compute my win rate's interval",
        "col_figure": "Figure",
        "share_title": "Share this result",
        "share_text": (
            "My declared figures in Rigor's risk of ruin calculator: expectancy, threshold, "
            "drawdown and streak. This is not an audit or a recommendation. {url}"
        ),
        "share_public": "The link holds the figures you typed; anyone with the link can read them.",
        "faq_title": "Frequently asked questions",
        "faq": [
            (
                "What is the risk of ruin?",
                "The chance that the balance reaches a threshold you set, or falls below it, "
                "at any point within a number of trades: for example, 50 % of the initial "
                "balance within 500 trades. Here it is computed on paths of independent trades "
                "built from your declared figures, with the classic formula next to it when "
                "the average win equals the average loss.",
            ),
            (
                "Why does it ask how many trades my history has?",
                "Because a win rate measured on few trades has a wide interval: with {n} "
                "trades, a declared {rate} is compatible with {low}. The calculator repeats "
                "everything at the lower end of the 95 % Wilson interval and shows both "
                "figures side by side.",
            ),
            (
                "How is it different from the drawdown?",
                "The ruin threshold is measured from the initial balance; the drawdown, from "
                "the highest balance reached so far. The table shows the maximum drawdown of "
                "the median path and of the worst 5 % of paths (p95) within the horizon.",
            ),
        ],
        "how_title": "What it computes and assumes",
        "how": [
            "Each path has independent trades: each one wins your average win with your win "
            "rate or loses your average loss. Fixed size, counted on the initial balance, as "
            "in the classic ruin formula.",
            "Touching the threshold is reaching the share of the initial balance you set, or "
            "falling below it, on any trade of the horizon; the path walks on to the end so "
            "the drawdown is measured.",
            "The maximum drawdown is measured from each path's own peak; the longest losing "
            "streak comes from longest_run_tail, Rigor's engine function for independent "
            "trades.",
            "Every win and loss has the average size: no tails, slippage or costs. Real losses "
            "vary, so with a real history the threshold is usually touched more often.",
            "The Wilson 95 % interval is the range of win rates compatible with your sample "
            "if trades are independent; with few trades it is wide.",
            "We keep your figures in no database or file; since they travel in the link, the "
            "server's access log may hold the address requested. It is a calculation with "
            "declared figures, not an audit, a forecast or a sizing recommendation.",
        ],
        "cta_title": "With your real history",
        "cta": (
            "With your real history, the report measures the streak, the drawdown and the "
            "ruin with your actual trades: upload your file. The report resamples your own "
            "days and compares your streak with your trades in random order."
        ),
        "cta_button": "Upload my file",
        "sample_link": "See a sample report",
        "read_title": "Keep reading",
    },
    "pt": {
        "nav": "Calculadora de risco de ruína",
        "eyebrow": "Calculadora grátis",
        "title": "Qual é a probabilidade de tocar o seu limite de ruína?",
        "seo_title": "Calculadora de risco de ruína e esperança matemática",
        "summary": (
            "Calculadora grátis de risco de ruína, esperança matemática, drawdown e sequência "
            "com números declarados, e quanto mudam no limite inferior da taxa de acerto."
        ),
        "lead": (
            "Digite a sua taxa de acerto, o seu ganho e a sua perda médios e um limite de "
            "ruína: calculamos a esperança matemática por operação, a probabilidade de tocar "
            "o limite dentro do horizonte, o drawdown máximo e a sequência de perdas. Sem "
            "cadastro nem arquivo."
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
            "Só se escrever em R: quanto do saldo você arrisca em cada operação. Por exemplo 0,5."
        ),
        "trades": "Operações do seu histórico (opcional)",
        "trades_help": (
            "Quantas operações fechadas estão por trás da sua taxa de acerto. Com esse número "
            "também mostramos o resultado no limite inferior do intervalo."
        ),
        "ruin": "Limite de ruína (% do saldo inicial)",
        "ruin_help": (
            "Ficar nessa porcentagem do saldo inicial, ou abaixo, conta como tocar o limite. "
            "Por padrão 50 %; para um desafio, experimente 20 % ou 30 %: o resultado mostra "
            "também esses limites."
        ),
        "horizon": "Horizonte (operações)",
        "horizon_help": (
            "Quantas operações cada trajetória percorre. Por padrão 500; no máximo 2.000."
        ),
        "submit": "Calcular",
        "error_number": "Revise os números: escreva valores como 55, 0,8 ou 1.5.",
        "error_missing": (
            "Faltam números: digite a taxa de acerto, o ganho médio e a perda média (e o risco "
            "por operação se escrever em R)."
        ),
        "error_win_rate": "A taxa de acerto deve ser maior que 0 e menor que 100.",
        "error_unit": "Escolha se escreve o ganho e a perda em % do saldo ou em R.",
        "error_avg_win": (
            "O ganho médio deve ser maior que 0 e, por operação, no máximo 50 % do saldo (em "
            "R, no máximo 100 R)."
        ),
        "error_avg_loss": (
            "A perda média deve ser maior que 0 e, por operação, no máximo 50 % do saldo (em "
            "R, no máximo 100 R)."
        ),
        "error_risk": "O risco por operação deve ser maior que 0 e no máximo 20 %.",
        "error_ruin": "O limite de ruína deve ser maior que 0 e menor que 100 % do saldo.",
        "error_horizon": "O horizonte deve ser um número inteiro de operações entre 10 e 2.000.",
        "error_trades": (
            "As operações do histórico devem ser um número inteiro entre 1 e 10.000.000."
        ),
        "error_invalid": "Revise os campos: cada um deve aparecer uma só vez.",
        "limited": "Cálculos demais deste endereço na última hora. Tente mais tarde.",
        "result_title": "Resultado",
        "simulated": (
            "Números declarados: {rate} de acerto, {win} por operação vencedora, {loss} por "
            "perdedora, limite de {ruin} do saldo inicial, horizonte de {horizon} operações."
        ),
        "row_expectancy_r": "Esperança por operação (R)",
        "row_expectancy_pct": "Esperança por operação (% do saldo inicial)",
        "row_ruin": "Tocar o limite de {ruin} em {horizon} operações",
        "row_classic": "Fórmula clássica sem horizonte (ganho = perda)",
        "row_dd_median": "Drawdown máximo do horizonte, mediana",
        "row_dd_p95": "Drawdown máximo do horizonte, p95 (os 5 % piores)",
        "row_streak": "Maior sequência de perdas, mediana",
        "row_streak_rare": "Maior sequência de perdas, 1 em cada 20 históricos",
        "r_unit": "{n} R",
        "trades_unit": "{n} operações",
        "r_is_loss": "Em % do saldo, 1 R é a sua perda média.",
        "no_classic": "só quando o ganho médio é igual à perda média",
        "classic_note": (
            "A fórmula clássica, (q ÷ p) elevado ao número de perdas líquidas necessárias para "
            "tocar o limite, conta as trajetórias que o tocam em qualquer momento, sem limite "
            "de operações. Em teoria é igual ou maior que a simulada; o número simulado "
            "carrega além disso o erro de amostragem das suas trajetórias, de cerca de um "
            "ponto."
        ),
        "thresholds_title": "Outros limites com os mesmos números",
        "col_threshold": "Limite (% do saldo inicial)",
        "col_touch": "Tocá-lo em {horizon} operações",
        "computed": "Calculado a partir do declarado",
        "paths_note": (
            "Números de {samples} trajetórias de {horizon} operações independentes com os seus "
            "números, cada operação do tamanho médio sobre o saldo inicial. Semente fixa: o "
            "mesmo link dá o mesmo resultado. A sequência vem da função do motor para "
            "operações independentes, não das trajetórias."
        ),
        "lower_title": "Com o limite inferior da sua taxa de acerto",
        "lower_text": (
            "Com {n} operações, uma taxa de acerto declarada de {rate} é compatível com uma "
            "real de {low}: é o limite inferior do intervalo de confiança de 95 % (Wilson). "
            "Com esse {low} e os mesmos números, a probabilidade de tocar o limite muda de "
            "{ruin} para {ruin_low}."
        ),
        "lower_text_same": (
            "Com {n} operações, uma taxa de acerto declarada de {rate} é compatível com uma "
            "real de {low}: é o limite inferior do intervalo de confiança de 95 % (Wilson). "
            "Com esse {low} e os mesmos números, a probabilidade de tocar o limite continua "
            "em {ruin}."
        ),
        "lower_computed": (
            "calculado com as suas operações e a sua taxa de acerto declaradas (Wilson)"
        ),
        "lower_missing": (
            "Digite quantas operações o seu histórico tem: com poucas, uma taxa de acerto de "
            "60 % pode ser na verdade bem menos, e a ruína muda com ela."
        ),
        "lower_link": "Calcular o intervalo da minha taxa de acerto",
        "col_figure": "Número",
        "share_title": "Compartilhar este resultado",
        "share_text": (
            "Meus números declarados na calculadora de risco de ruína do Rigor: esperança, "
            "limite, drawdown e sequência. Não é uma auditoria nem uma recomendação. {url}"
        ),
        "share_public": (
            "O link contém os números que você digitou; qualquer pessoa com o link pode lê-los."
        ),
        "faq_title": "Perguntas frequentes",
        "faq": [
            (
                "O que é o risco de ruína?",
                "É a probabilidade de o saldo ficar num limite que você define, ou abaixo, "
                "dentro de um número de operações: por exemplo, 50 % do saldo inicial em 500 "
                "operações. Aqui ele é calculado com trajetórias de operações independentes "
                "feitas com os seus números declarados, e a fórmula clássica aparece ao lado "
                "quando o ganho médio é igual à perda média.",
            ),
            (
                "Por que pede quantas operações o meu histórico tem?",
                "Porque uma taxa de acerto medida em poucas operações tem um intervalo largo: "
                "com {n} operações, {rate} declarados são compatíveis com {low}. A calculadora "
                "repete tudo com o limite inferior do intervalo de Wilson de 95 % e mostra os "
                "dois números lado a lado.",
            ),
            (
                "Qual é a diferença para o drawdown?",
                "O limite de ruína é medido a partir do saldo inicial; o drawdown, a partir do "
                "máximo atingido até aquele momento. A tabela mostra o drawdown máximo da "
                "trajetória mediana e o dos 5 % piores (p95) dentro do horizonte.",
            ),
        ],
        "how_title": "O que calcula e o que supõe",
        "how": [
            "Cada trajetória tem operações independentes: cada uma ganha o seu ganho médio com "
            "a sua taxa de acerto ou perde a sua perda média. Tamanho fixo, calculado sobre o "
            "saldo inicial, como na fórmula clássica de ruína.",
            "Tocar o limite é ficar na porcentagem do saldo inicial que você definiu, ou "
            "abaixo, em qualquer operação do horizonte; a trajetória segue até o fim para "
            "medir o drawdown.",
            "O drawdown máximo é medido a partir do máximo atingido por cada trajetória; a "
            "maior sequência de perdas vem de longest_run_tail, a função do motor do Rigor "
            "para operações independentes.",
            "Todos os ganhos e perdas têm o tamanho médio: sem caudas, slippage nem custos. As "
            "perdas reais variam, então com um histórico real o limite costuma ser tocado "
            "mais vezes.",
            "O intervalo de Wilson de 95 % dá a faixa de taxas de acerto compatível com a sua "
            "amostra se as operações forem independentes; com poucas operações é largo.",
            "Não guardamos os seus números em nenhum banco de dados nem arquivo; como vão no "
            "link, o registro de acesso do servidor pode conter o endereço pedido. É um "
            "cálculo com números declarados, não uma auditoria, uma previsão nem uma "
            "recomendação de tamanho.",
        ],
        "cta_title": "Com o seu histórico real",
        "cta": (
            "Com o seu histórico real, o relatório mede a sequência, o drawdown e a ruína com "
            "as suas operações de verdade: envie o seu arquivo. O relatório reamostra os seus "
            "próprios dias e compara a sua sequência com as suas operações em ordem aleatória."
        ),
        "cta_button": "Enviar meu arquivo",
        "sample_link": "Ver um relatório de exemplo",
        "read_title": "Para continuar",
    },
}


__all__ = [
    "BLOCK",
    "CACHE_SIZE",
    "COPY",
    "DEFAULT_HORIZON",
    "DEFAULT_RUIN",
    "FAQ_EXAMPLE",
    "FIELDS",
    "HORIZON_RANGE",
    "REQUESTS_PER_HOUR",
    "RUIN_PATH",
    "RUIN_RANGE",
    "RUIN_SHORTCUTS",
    "SAMPLES",
    "SEED",
    "SHARE_REF",
    "STREAK_TOP",
    "TOUCH",
    "Parsed",
    "Paths",
    "RuinInput",
    "RuinReading",
    "RuinRun",
    "classic_ruin",
    "compute",
    "empty_form",
    "faq",
    "losing_streaks",
    "parse",
    "ruin_share",
    "ruin_url",
    "run",
    "share_url",
    "share_values",
    "simulate",
    "submitted",
]
