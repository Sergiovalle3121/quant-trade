"""Prop-firm challenge rules as dated, sourced data.

Each preset is a transcription of a firm's publicly posted rules on the date
in ``as_of``, read at ``source_url``. Firms change their rules often; a preset
is a record of what the page said that day, not a statement about the firm
today, and the simulator that uses it says so in every result.

Amounts are fractions of the initial balance so the same simulator serves
every account size. Futures firms that state limits in dollars are converted
at the account size named in ``program``.

Loss rules the simulator understands:

- ``daily_loss_basis``:
  ``initial_balance`` - the day's floor is the start-of-day balance minus
  ``max_daily_loss`` times the initial balance (FTMO style);
  ``start_of_day`` - the floor is the start-of-day balance times
  ``1 - max_daily_loss``;
  ``none`` - no daily limit (``max_daily_loss`` is ``None``).
- ``total_loss_type``:
  ``static`` - the floor is the initial balance times ``1 - max_total_loss``;
  ``trailing_eod`` - the floor trails the highest end-of-day balance by
  ``max_total_loss`` times the initial balance;
  ``trailing_eod_lock`` - as ``trailing_eod`` but the floor stops rising
  once it reaches the initial balance.

Rules the simulator cannot see (consistency or best-day rules, news
restrictions, intraday trailing) are listed in ``notes``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

DailyLossBasis = Literal["initial_balance", "start_of_day", "none"]
TotalLossType = Literal["static", "trailing_eod", "trailing_eod_lock"]

DAILY_LOSS_BASES: tuple[str, ...] = ("initial_balance", "start_of_day", "none")
TOTAL_LOSS_TYPES: tuple[str, ...] = ("static", "trailing_eod", "trailing_eod_lock")


@dataclass(frozen=True)
class ChallengeRules:
    key: str
    firm: str
    program: str
    phase: str
    profit_target: float
    max_daily_loss: float | None
    daily_loss_basis: DailyLossBasis
    max_total_loss: float
    total_loss_type: TotalLossType
    min_trading_days: int
    time_limit_days: int | None
    notes: tuple[str, ...]
    source_url: str
    as_of: str

    def __post_init__(self) -> None:
        if not 0.0 < self.profit_target < 1.0:
            raise ValueError(f"{self.key}: profit_target must be a fraction in (0, 1)")
        if not 0.0 < self.max_total_loss < 1.0:
            raise ValueError(f"{self.key}: max_total_loss must be a fraction in (0, 1)")
        if self.daily_loss_basis not in DAILY_LOSS_BASES:
            raise ValueError(f"{self.key}: unknown daily_loss_basis {self.daily_loss_basis!r}")
        if self.total_loss_type not in TOTAL_LOSS_TYPES:
            raise ValueError(f"{self.key}: unknown total_loss_type {self.total_loss_type!r}")
        if (self.max_daily_loss is None) != (self.daily_loss_basis == "none"):
            raise ValueError(f"{self.key}: max_daily_loss is None exactly when the basis is none")
        if self.max_daily_loss is not None and not 0.0 < self.max_daily_loss < 1.0:
            raise ValueError(f"{self.key}: max_daily_loss must be a fraction in (0, 1)")
        if self.min_trading_days < 0:
            raise ValueError(f"{self.key}: min_trading_days must be >= 0")
        if self.time_limit_days is not None and self.time_limit_days < 1:
            raise ValueError(f"{self.key}: time_limit_days must be positive or None")
        if not self.source_url or not self.as_of:
            raise ValueError(f"{self.key}: every preset needs source_url and as_of")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["notes"] = list(self.notes)
        return data


DEFAULT_PRESET = "generic-2step-phase1"

AS_OF = "2026-09-24"

FTMO_URL = "https://ftmo.com/en/trading-objectives/"
FTMO_TIME_URL = "https://ftmo.com/en/faq/how-long-does-it-take-to-become-an-ftmo-trader/"
FUNDEDNEXT_URL = "https://fundednext.com/general-rules/cfds/trading-objectives"
THE5ERS_HIGH_STAKES_URL = "https://the5ers.com/high-stakes/"
THE5ERS_HYPER_GROWTH_URL = "https://the5ers.com/hyper-growth/"
THE5ERS_BOOTCAMP_URL = "https://the5ers.com/bootcamp/"
TOPSTEP_URL = "https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit"

_FTMO_NOTES = (
    "Daily loss: 5 % of the initial balance below the balance recorded at 00:00 CE(S)T.",
    "No time limit (" + FTMO_TIME_URL + ").",
)
_FUNDEDNEXT_NOTES = (
    "Daily loss: a percentage of the initial balance below the start-of-day balance, "
    "reset at 0:00 server time; it counts open losses, swap and commission.",
    "No deadline; accounts with no trade for 60 days are deactivated.",
)
_THE5ERS_HS_NOTES = (
    "Daily loss: 5 % below the higher of the previous day's closing balance or equity "
    "(help.the5ers.com/what-is-the-drawdown-rule-for-high-stakes/).",
    "Needs 3 days each closing at least 0.5 % of the initial balance in gain; the simulator "
    "counts any day with a non-zero return, so it is optimistic here.",
    "No trading from 2 minutes before to 2 minutes after high-impact news; not simulated.",
)
_TOPSTEP_NOTES = (
    "Maximum loss trails the highest end-of-day balance and locks once it reaches the "
    "starting balance; it is monitored in real time, which daily data cannot see.",
    "The daily loss limit is optional and not simulated.",
    "Consistency target: the best day must stay at or below 55 % of the profit target, "
    "otherwise the target rises; not simulated.",
    "No time limit stated on the pages read.",
    "Source for the target and consistency rule: "
    "https://help.topstep.com/en/articles/8284208-what-is-the-consistency-target",
)


def _topstep(size: str, maximum_loss: float) -> ChallengeRules:
    return ChallengeRules(
        key=f"topstep-{size.lower()}-combine",
        firm="Topstep",
        program=f"Trading Combine {size}",
        phase="1",
        profit_target=0.06,
        max_daily_loss=None,
        daily_loss_basis="none",
        max_total_loss=maximum_loss,
        total_loss_type="trailing_eod_lock",
        min_trading_days=2,
        time_limit_days=None,
        notes=_TOPSTEP_NOTES,
        source_url=TOPSTEP_URL,
        as_of=AS_OF,
    )


_PRESET_LIST: tuple[ChallengeRules, ...] = (
    ChallengeRules(
        key="generic-2step-phase1",
        firm="Generic",
        program="Two-step evaluation, phase 1",
        phase="1",
        profit_target=0.10,
        max_daily_loss=0.05,
        daily_loss_basis="initial_balance",
        max_total_loss=0.10,
        total_loss_type="static",
        min_trading_days=4,
        time_limit_days=None,
        notes=("Reference rules typical of two-step evaluations; not any one firm's terms.",),
        source_url="docs/AUDIT_ITERATION4_PLAN.md",
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="ftmo-2step-phase1",
        firm="FTMO",
        program="FTMO Challenge 2-Step",
        phase="1 (FTMO Challenge)",
        profit_target=0.10,
        max_daily_loss=0.05,
        daily_loss_basis="initial_balance",
        max_total_loss=0.10,
        total_loss_type="static",
        min_trading_days=4,
        time_limit_days=None,
        notes=_FTMO_NOTES,
        source_url=FTMO_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="ftmo-2step-phase2",
        firm="FTMO",
        program="FTMO Challenge 2-Step",
        phase="2 (Verification)",
        profit_target=0.05,
        max_daily_loss=0.05,
        daily_loss_basis="initial_balance",
        max_total_loss=0.10,
        total_loss_type="static",
        min_trading_days=4,
        time_limit_days=None,
        notes=_FTMO_NOTES,
        source_url=FTMO_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="ftmo-1step",
        firm="FTMO",
        program="FTMO Challenge 1-Step",
        phase="1",
        profit_target=0.10,
        max_daily_loss=0.03,
        daily_loss_basis="initial_balance",
        max_total_loss=0.10,
        total_loss_type="trailing_eod",
        min_trading_days=0,
        time_limit_days=None,
        notes=(
            "Maximum loss is an end-of-day trailing limit; whether it stops trailing was not "
            "stated on the page read, so the simulator lets it trail (stricter).",
            "Best Day Rule: the best day may not exceed 50 % of the positive days' profit; "
            "not simulated.",
            "No minimum trading days; no time limit (" + FTMO_TIME_URL + ").",
        ),
        source_url=FTMO_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="fundednext-stellar-2step-phase1",
        firm="FundedNext",
        program="Stellar 2-Step",
        phase="1",
        profit_target=0.08,
        max_daily_loss=0.05,
        daily_loss_basis="initial_balance",
        max_total_loss=0.10,
        total_loss_type="static",
        min_trading_days=5,
        time_limit_days=None,
        notes=(*_FUNDEDNEXT_NOTES, "Expert advisors are not allowed on this model."),
        source_url=FUNDEDNEXT_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="fundednext-stellar-2step-phase2",
        firm="FundedNext",
        program="Stellar 2-Step",
        phase="2",
        profit_target=0.05,
        max_daily_loss=0.05,
        daily_loss_basis="initial_balance",
        max_total_loss=0.10,
        total_loss_type="static",
        min_trading_days=5,
        time_limit_days=None,
        notes=(*_FUNDEDNEXT_NOTES, "Expert advisors are not allowed on this model."),
        source_url=FUNDEDNEXT_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="fundednext-stellar-1step",
        firm="FundedNext",
        program="Stellar 1-Step",
        phase="1",
        profit_target=0.10,
        max_daily_loss=0.03,
        daily_loss_basis="initial_balance",
        max_total_loss=0.06,
        total_loss_type="static",
        min_trading_days=2,
        time_limit_days=None,
        notes=(*_FUNDEDNEXT_NOTES, "Expert advisors allowed only on accounts below 50K."),
        source_url=FUNDEDNEXT_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="fundednext-stellar-lite-phase1",
        firm="FundedNext",
        program="Stellar Lite",
        phase="1",
        profit_target=0.08,
        max_daily_loss=0.04,
        daily_loss_basis="initial_balance",
        max_total_loss=0.08,
        total_loss_type="static",
        min_trading_days=5,
        time_limit_days=None,
        notes=_FUNDEDNEXT_NOTES,
        source_url=FUNDEDNEXT_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="fundednext-stellar-lite-phase2",
        firm="FundedNext",
        program="Stellar Lite",
        phase="2",
        profit_target=0.04,
        max_daily_loss=0.04,
        daily_loss_basis="initial_balance",
        max_total_loss=0.08,
        total_loss_type="static",
        min_trading_days=5,
        time_limit_days=None,
        notes=_FUNDEDNEXT_NOTES,
        source_url=FUNDEDNEXT_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="the5ers-high-stakes-step1",
        firm="The5ers",
        program="High Stakes",
        phase="1",
        profit_target=0.10,
        max_daily_loss=0.05,
        daily_loss_basis="start_of_day",
        max_total_loss=0.10,
        total_loss_type="static",
        min_trading_days=3,
        time_limit_days=None,
        notes=_THE5ERS_HS_NOTES,
        source_url=THE5ERS_HIGH_STAKES_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="the5ers-high-stakes-step2",
        firm="The5ers",
        program="High Stakes",
        phase="2",
        profit_target=0.05,
        max_daily_loss=0.05,
        daily_loss_basis="start_of_day",
        max_total_loss=0.10,
        total_loss_type="static",
        min_trading_days=3,
        time_limit_days=None,
        notes=_THE5ERS_HS_NOTES,
        source_url=THE5ERS_HIGH_STAKES_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="the5ers-hyper-growth",
        firm="The5ers",
        program="Hyper Growth",
        phase="1",
        profit_target=0.10,
        max_daily_loss=None,
        daily_loss_basis="none",
        max_total_loss=0.06,
        total_loss_type="static",
        min_trading_days=0,
        time_limit_days=None,
        notes=(
            "The 3 % daily limit suspends trading for the day instead of ending the account; "
            "not simulated.",
            "Static stop-out at 6 %: stated on The5ers' blog, not on the rules page.",
            "No minimum days; unlimited time.",
        ),
        source_url=THE5ERS_HYPER_GROWTH_URL,
        as_of=AS_OF,
    ),
    ChallengeRules(
        key="the5ers-bootcamp-step",
        firm="The5ers",
        program="Bootcamp",
        phase="each of steps 1-3",
        profit_target=0.06,
        max_daily_loss=None,
        daily_loss_basis="none",
        max_total_loss=0.05,
        total_loss_type="static",
        min_trading_days=0,
        time_limit_days=None,
        notes=(
            "No daily limit during the evaluation steps; static loss stated on The5ers' blog.",
            "No position may risk more than 2 % of the balance at its stop loss; not simulated.",
            "Unlimited time, but each level is reachable for 48 hours after the previous one.",
        ),
        source_url=THE5ERS_BOOTCAMP_URL,
        as_of=AS_OF,
    ),
    _topstep("50K", 2_000 / 50_000),
    _topstep("100K", 3_000 / 100_000),
    _topstep("150K", 4_500 / 150_000),
)

PRESETS: dict[str, ChallengeRules] = {rules.key: rules for rules in _PRESET_LIST}


def get_preset(key: str) -> ChallengeRules:
    """The preset named ``key``; the error lists the valid names."""
    try:
        return PRESETS[key]
    except KeyError:
        raise KeyError(
            f"unknown challenge preset {key!r}; choose one of: {', '.join(sorted(PRESETS))}"
        ) from None


def preset_label(firm: str, program: str, phase: str, locale: str = "es") -> str:
    """``firm · program · phase`` for a reader, without a phase that says nothing.

    The phase is shown only when another preset shares the firm and program
    (a two-step evaluation) or when it is not a bare number.
    """
    from quant_trade.audit.i18n import localize

    siblings = sum(1 for r in PRESETS.values() if (r.firm, r.program) == (firm, program))
    parts = [localize(firm, locale), localize(program, locale)]
    if phase and (siblings > 1 or not phase.isdigit()):
        word = "fase" if locale == "es" else "phase"
        parts.append(
            f"{word} {localize(phase, locale)}" if phase[0].isdigit() else localize(phase, locale)
        )
    return " · ".join(part for part in parts if part)


__all__ = [
    "preset_label",
    "DAILY_LOSS_BASES",
    "DEFAULT_PRESET",
    "AS_OF",
    "PRESETS",
    "TOTAL_LOSS_TYPES",
    "ChallengeRules",
    "DailyLossBasis",
    "TotalLossType",
    "get_preset",
]
