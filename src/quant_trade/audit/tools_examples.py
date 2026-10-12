"""Declared examples for the tools hub, computed by each tool's own reader.

Inputs below are illustrative declarations, not observations or client data.
Results retain the tools' assumptions, rounding and deterministic simulation
seeds. The report check requires an uploaded file, so its example points to
the public sample PDF the check already recognises and never invents a file,
hash or check result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal
from urllib.parse import urlencode

from quant_trade.audit import calculator, challenge_calc, reading, ruin_calc, rules_table, winrate
from quant_trade.audit.articles import win_rate_interval
from quant_trade.audit.public_card import _num, _pct, _readings

CALCULATOR_INPUT = calculator.CalculatorInput(sharpe=1.8, years=3.0, trials=100)
WINRATE_VALUES = {"trades": "40", "win_rate": "60", "target_r": "1.5", "stop_r": "1"}
# Not a saturated case: at 0.5 % risk every path reaches the target, which reads
# like a promise; at 1 % risk and 2 trades a day the losses show up as well.
CHALLENGE_INPUT = challenge_calc.ChallengeInput(
    win_rate_pct=45.0,
    unit="r",
    avg_win=1.5,
    avg_loss=1.0,
    risk=1.0,
    per_day=2.0,
    program="ftmo-2step-phase1",
)
RUIN_INPUT = ruin_calc.RuinInput(
    win_rate_pct=55.0,
    unit="r",
    avg_win=1.0,
    avg_loss=1.0,
    risk=1.0,
    ruin_pct=30.0,
    horizon=500,
    trades=60,
)
READING_VALUES = {
    "trades": "100",
    "win_rate": "60",
    "profit_factor": "1.5",
    "sharpe": "1.8",
    "years": "3",
    "trials": "100",
    "target_r": "1.5",
    "stop_r": "1",
}
#: The sample report as the PDF a buyer gets (web.SAMPLE_PDF_PATHS; web cannot be
#: imported here). /comprobar answers that it is the sample report, unchanged.
SAMPLE_PDF_PATHS = {"es": "/ejemplo.pdf", "en": "/sample.pdf", "pt": "/pt/exemplo.pdf"}


@dataclass(frozen=True)
class ToolExample:
    """A localized case and its existing destination; never measured evidence."""

    text: str
    url: str
    #: A public file the case refers to (the sample PDF for the check), or empty.
    download: str = ""
    evidence: Literal["DECLARED"] = "DECLARED"


_TEXT = {
    "es": {
        "calculator": (
            "Sharpe {sharpe}, {years} años y {trials} configuraciones, datos diarios "
            "→ Sharpe esperado por suerte: {luck}."
        ),
        "winrate": (
            "{rate} % de aciertos en {trades} operaciones → intervalo al 95 %: {interval}."
        ),
        "challenge": (
            "{rate} %, {win}R/{loss}R, riesgo {risk} %, {per_day}/día en {program} "
            "→ en el modelo, {chance} de las simulaciones alcanza ambos objetivos, "
            "{daily} toca el límite diario y {total} el límite total "
            "(hasta {days} días hábiles por fase)."
        ),
        "ruin": (
            "{rate} %, {win}R/{loss}R, historial de {trades} operaciones, riesgo {risk} % "
            "y horizonte de {horizon} operaciones → perder el {threshold} % del saldo inicial: "
            "{chance}; con el límite inferior al 95 % ({lower_rate}): {lower_chance}."
        ),
        "reading": (
            "{trades} operaciones, {rate} %, PF {pf}, Sharpe {sharpe}, {years} años, "
            "{trials} configuraciones y {target}R/{stop}R → intervalo al 95 %: {interval}; "
            "Sharpe por suerte {luck}; equilibrio antes de costos: {breakeven}."
        ),
        "check": (
            "PDF de ejemplo de Rigor → al elegirlo en el formulario, la comprobación responde "
            "que es el informe de ejemplo, sin cambios."
        ),
        "rules_table": (
            "Tabla completa → {firms} firmas y {programs} programas; "
            "lectura más reciente de las fuentes: {date}."
        ),
    },
    "en": {
        "calculator": (
            "Sharpe {sharpe}, {years} years and {trials} configurations, daily data "
            "→ expected Sharpe from luck: {luck}."
        ),
        "winrate": "{rate} % wins in {trades} trades → 95 % interval: {interval}.",
        "challenge": (
            "{rate} %, {win}R/{loss}R, {risk} % risk, {per_day}/day in {program} "
            "→ in the model, {chance} of simulations reach both targets, "
            "{daily} hit the daily limit and {total} the total limit "
            "(up to {days} business days per phase)."
        ),
        "ruin": (
            "{rate} %, {win}R/{loss}R, {trades} historical trades, {risk} % risk "
            "and a {horizon}-trade horizon → losing {threshold} % of the initial balance: "
            "{chance}; "
            "at the 95 % lower bound ({lower_rate}): {lower_chance}."
        ),
        "reading": (
            "{trades} trades, {rate} %, PF {pf}, Sharpe {sharpe}, {years} years, "
            "{trials} configurations and {target}R/{stop}R → 95 % interval: {interval}; "
            "Sharpe from luck {luck}; break-even before costs: {breakeven}."
        ),
        "check": (
            "Rigor's sample PDF → choose it in the form and the check answers that it is the "
            "sample report, unchanged."
        ),
        "rules_table": (
            "Full table → {firms} firms and {programs} programs; "
            "latest source reading date: {date}."
        ),
    },
    "pt": {
        "calculator": (
            "Sharpe {sharpe}, {years} anos e {trials} configurações, dados diários "
            "→ Sharpe esperado por sorte: {luck}."
        ),
        "winrate": ("{rate} % de acertos em {trades} operações → intervalo de 95 %: {interval}."),
        "challenge": (
            "{rate} %, {win}R/{loss}R, risco de {risk} %, {per_day}/dia em {program} "
            "→ no modelo, {chance} das simulações atingem ambas as metas, "
            "{daily} tocam o limite diário e {total} o limite total "
            "(até {days} dias úteis por fase)."
        ),
        "ruin": (
            "{rate} %, {win}R/{loss}R, histórico de {trades} operações, risco de {risk} % "
            "e horizonte de {horizon} operações → perder {threshold} % do saldo inicial: {chance}; "
            "no limite inferior de 95 % ({lower_rate}): {lower_chance}."
        ),
        "reading": (
            "{trades} operações, {rate} %, PF {pf}, Sharpe {sharpe}, {years} anos, "
            "{trials} configurações e {target}R/{stop}R → intervalo de 95 %: {interval}; "
            "Sharpe por sorte {luck}; equilíbrio antes dos custos: {breakeven}."
        ),
        "check": (
            "PDF de exemplo do Rigor → ao escolhê-lo no formulário, a comprovação responde "
            "que é o relatório de exemplo, sem alterações."
        ),
        "rules_table": (
            "Tabela completa → {firms} empresas e {programs} programas; "
            "data de leitura mais recente das fontes: {date}."
        ),
    },
}


def _input(value: float | str, locale: str) -> str:
    """The fixed declarations use at most one decimal; localize without padding."""
    return _num(float(value), locale, 1).rstrip("0").rstrip(".,")


def _fields(values: Mapping[str, str], names: tuple[str, ...]) -> dict[str, str]:
    """The validated strings as the tool's own share link orders them."""
    return {name: values.get(name, "").strip() for name in names}


def _link(path: str, values: Mapping[str, str]) -> str:
    """The destination with the example's query and no ``ref`` tag.

    The tools' ``share_url`` tag their links so /panel counts real shares; a
    click inside the site must not attribute the visitor to a share.
    """
    return path + "?" + urlencode(values)


@lru_cache(maxsize=3)
def _examples(locale: str) -> tuple[tuple[str, ToolExample], ...]:
    # check imports seo, which imports the hub. Wait until rendering to load it.
    from quant_trade.audit.check import check_path

    copy = _TEXT[locale]
    luck = calculator.compute(CALCULATOR_INPUT)
    claim = winrate.parse(WINRATE_VALUES, locale)
    challenge = challenge_calc.compute(CHALLENGE_INPUT)
    ruin = ruin_calc.compute(RUIN_INPUT)
    card = {
        key: value for key, value, _ in _readings(reading.claim_from_query(READING_VALUES, locale))
    }
    assert claim.win_rate is not None and claim.trades is not None and ruin.lower is not None
    program = challenge_calc.PRESETS[CHALLENGE_INPUT.program]
    outcome = challenge.declared.outcome
    values: dict[str, dict[str, object]] = {
        "calculator": {
            "sharpe": _input(CALCULATOR_INPUT.sharpe, locale),
            "years": _input(CALCULATOR_INPUT.years, locale),
            "trials": str(CALCULATOR_INPUT.trials),
            "luck": _num(float(luck["luck_sharpe"]["value"]), locale, 2),
        },
        "winrate": {
            "rate": _input(WINRATE_VALUES["win_rate"], locale),
            "trades": WINRATE_VALUES["trades"],
            # The same string the win-rate page writes, so the link shows it literally.
            "interval": win_rate_interval(claim.win_rate, claim.trades, locale),
        },
        "challenge": {
            "rate": _input(CHALLENGE_INPUT.win_rate_pct, locale),
            "win": _input(CHALLENGE_INPUT.avg_win, locale),
            "loss": _input(CHALLENGE_INPUT.avg_loss, locale),
            "risk": _input(CHALLENGE_INPUT.risk or 0.0, locale),
            "per_day": _input(CHALLENGE_INPUT.per_day, locale),
            "program": program.program,
            "days": str(challenge_calc.horizon(CHALLENGE_INPUT.program)),
            "chance": _pct(float(outcome["pass"]["value"]), locale),
            "daily": _pct(float(outcome["fail_daily_loss"]["value"]), locale),
            "total": _pct(float(outcome["fail_total_loss"]["value"]), locale),
        },
        "ruin": {
            "rate": _input(RUIN_INPUT.win_rate_pct, locale),
            "win": _input(RUIN_INPUT.avg_win, locale),
            "loss": _input(RUIN_INPUT.avg_loss, locale),
            "trades": str(RUIN_INPUT.trades),
            "risk": _input(RUIN_INPUT.risk or 0.0, locale),
            "horizon": str(RUIN_INPUT.horizon),
            "threshold": _input(RUIN_INPUT.ruin_pct, locale),
            "chance": _pct(ruin.declared.ruin, locale),
            "lower_rate": _pct(ruin.lower.win_rate, locale),
            "lower_chance": _pct(ruin.lower.ruin, locale),
        },
        "reading": {
            "trades": READING_VALUES["trades"],
            "rate": _input(READING_VALUES["win_rate"], locale),
            "pf": _input(READING_VALUES["profit_factor"], locale),
            "sharpe": _input(READING_VALUES["sharpe"], locale),
            "years": READING_VALUES["years"],
            "trials": READING_VALUES["trials"],
            "target": _input(READING_VALUES["target_r"], locale),
            "stop": _input(READING_VALUES["stop_r"], locale),
            "interval": card["wilson"],
            "luck": card["luck"],
            "breakeven": card["breakeven"],
        },
        "check": {},
        "rules_table": {**rules_table.counts(), "date": rules_table.latest_as_of()},
    }
    urls = {
        "calculator": _link(
            calculator.calculator_url(locale), calculator.share_values(CALCULATOR_INPUT)
        ),
        "winrate": _link(winrate.WINRATE_PATH[locale], _fields(WINRATE_VALUES, winrate.FIELDS)),
        "challenge": _link(
            challenge_calc.challenge_url(locale), challenge_calc.share_values(CHALLENGE_INPUT)
        ),
        "ruin": _link(ruin_calc.ruin_url(locale), ruin_calc.share_values(RUIN_INPUT)),
        "reading": _link(reading.READING_PATH[locale], _fields(READING_VALUES, reading.FIELDS)),
        "check": check_path(locale),
        "rules_table": rules_table.rules_table_url(locale),
    }
    downloads = {"check": SAMPLE_PDF_PATHS[locale]}
    return tuple(
        (
            key,
            ToolExample(
                text=copy[key].format(**fields), url=urls[key], download=downloads.get(key, "")
            ),
        )
        for key, fields in values.items()
    )


def examples(locale: str) -> dict[str, ToolExample]:
    """Return a fresh mapping of immutable examples; compute once per language."""
    return dict(_examples(locale if locale in _TEXT else "es"))


__all__ = [
    "CALCULATOR_INPUT",
    "CHALLENGE_INPUT",
    "READING_VALUES",
    "RUIN_INPUT",
    "SAMPLE_PDF_PATHS",
    "WINRATE_VALUES",
    "ToolExample",
    "examples",
]
