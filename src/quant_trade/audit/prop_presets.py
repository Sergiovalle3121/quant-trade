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

- ``best_day_limit`` with ``best_day_basis``: the best day's gain may not
  exceed that share of the profit target (``profit_target``) or of the
  positive days' summed gain (``positive_days``); checked at the pass.

``markets`` lists what a program lets the trader trade (``MARKETS``), only when
a page of the firm says so: ``markets_source`` is that page and
``markets_as_of`` the day it was read. ``None`` means the pages read do not
say, and the program is never left out for its markets. The numeric rules do
not depend on it.

Rules the simulator cannot see (news restrictions, intraday trailing) are
listed in ``notes``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

DailyLossBasis = Literal["initial_balance", "start_of_day", "none"]
TotalLossType = Literal["static", "trailing_eod", "trailing_eod_lock"]
BestDayBasis = Literal["profit_target", "positive_days"]

DAILY_LOSS_BASES: tuple[str, ...] = ("initial_balance", "start_of_day", "none")
TOTAL_LOSS_TYPES: tuple[str, ...] = ("static", "trailing_eod", "trailing_eod_lock")
#: What a program may let the trader trade, in the words its page uses: spot
#: currency pairs, spot metals, index CFDs, energy (oil) CFDs, crypto CFDs, and
#: exchange-traded futures.
MARKETS: tuple[str, ...] = ("fx", "metals", "indices", "energy", "crypto", "futures")


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
    #: Best-day (consistency) rule: the best day's gain may not exceed this
    #: share of the profit target or of the positive days' summed gain.
    best_day_limit: float | None = None
    best_day_basis: BestDayBasis | None = None
    #: What the program lets the trader trade (``MARKETS``), as the page at
    #: ``markets_source`` said on ``markets_as_of``; ``None`` when no page read says.
    markets: tuple[str, ...] | None = None
    markets_source: str | None = None
    markets_as_of: str | None = None

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
        if (self.best_day_limit is None) != (self.best_day_basis is None):
            raise ValueError(f"{self.key}: best_day_limit and best_day_basis go together")
        if self.best_day_limit is not None and not 0.0 < self.best_day_limit < 1.0:
            raise ValueError(f"{self.key}: best_day_limit must be a fraction in (0, 1)")
        if self.markets is not None:
            if not self.markets or any(market not in MARKETS for market in self.markets):
                raise ValueError(f"{self.key}: markets must be a non-empty subset of MARKETS")
            if not self.markets_source or not self.markets_as_of:
                raise ValueError(f"{self.key}: markets need markets_source and markets_as_of")
        elif self.markets_source or self.markets_as_of:
            raise ValueError(f"{self.key}: markets_source and markets_as_of need markets")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["notes"] = list(self.notes)
        if self.markets is not None:
            data["markets"] = list(self.markets)
        return data


DEFAULT_PRESET = "generic-2step-phase1"

AS_OF = "2026-09-25"

FTMO_URL = "https://ftmo.com/en/trading-objectives/"
FTMO_TIME_URL = "https://ftmo.com/en/faq/how-long-does-it-take-to-become-an-ftmo-trader/"
FUNDEDNEXT_URL = "https://fundednext.com/general-rules/cfds/trading-objectives"
THE5ERS_HIGH_STAKES_URL = "https://the5ers.com/high-stakes/"
THE5ERS_HYPER_GROWTH_URL = "https://the5ers.com/hyper-growth/"
THE5ERS_BOOTCAMP_URL = "https://the5ers.com/bootcamp/"
TOPSTEP_URL = "https://help.topstep.com/en/articles/8284204-what-is-the-maximum-loss-limit"
#: "Topstep is a Futures-only program": every CME Group product, no forex.
TOPSTEP_PRODUCTS_URL = (
    "https://help.topstep.com/en/articles/8284206-when-and-what-products-can-i-trade"
)
#: The day the markets of the programs that state them were read.
MARKETS_AS_OF = "2026-10-09"
#: "Assets available: FX, Metals, Indices Oil and Crypto." (High Stakes)
THE5ERS_HIGH_STAKES_MARKETS: tuple[str, ...] = ("fx", "metals", "indices", "energy", "crypto")
#: "Assets available: FX, Metals, Indices, crypto." (Hyper Growth)
THE5ERS_HYPER_GROWTH_MARKETS: tuple[str, ...] = ("fx", "metals", "indices", "crypto")

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
    "otherwise the target rises; checked when a path reaches the target, on daily closes.",
    "No time limit stated on the pages read.",
    "Source for the target and consistency rule: "
    "https://help.topstep.com/en/articles/8284208-what-is-the-consistency-target",
)


#: Topstep's Trading Combine sizes: the account and its maximum loss, in US dollars.
_TOPSTEP_ACCOUNTS: tuple[tuple[str, int, int], ...] = (
    ("50K", 50_000, 2_000),
    ("100K", 100_000, 3_000),
    ("150K", 150_000, 4_500),
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
        best_day_limit=0.55,
        best_day_basis="profit_target",
        markets=("futures",),
        markets_source=TOPSTEP_PRODUCTS_URL,
        markets_as_of=MARKETS_AS_OF,
    )


# ---------------------------------------------------------------------------
# Firms read on 2026-10-10: FundingPips, Alpha Capital Group, E8 Markets, FXIFY
# and Maven Trading. Only the programs whose rules fit the simulator's types,
# exactly or by an approximation that is stricter than the firm's rule, are
# here; the programs left out and why are in docs/AUDIT_SAAS.md (a maximum loss
# that trails a high reached within the day, a daily profit cap, or a minimum of
# days that each close with a set gain).
# ---------------------------------------------------------------------------

#: The day the rules of these five firms, and the markets they name, were read.
NEW_FIRMS_AS_OF = "2026-10-10"

FUNDINGPIPS_STANDARD_URL = (
    "https://help.fundingpips.com/hc/en-us/articles/34501809112081-2-Step-Standard"
)
FUNDINGPIPS_PRO_URL = (
    "https://help.fundingpips.com/hc/en-us/articles/34502027344017-2-Step-Pro-Model"
)
FUNDINGPIPS_FLEX_URL = "https://help.fundingpips.com/hc/en-us/articles/47835196271249-2-Step-Flex"
FUNDINGPIPS_1STEP_FLEX_URL = (
    "https://help.fundingpips.com/hc/en-us/articles/34501697434385-1-Step-Flex"
)
FUNDINGPIPS_NEWS_URL = (
    "https://help.fundingpips.com/hc/en-us/articles/34504137479441-News-Trading-Weekend-Holding"
)
FUNDINGPIPS_LEGACY_URL = (
    "https://help.fundingpips.com/hc/en-us/articles/51307058233361-FundingPips-Legacy-Rules"
)
#: "41 instruments across 5 asset classes": "Forex, Metals, Indices, Energies,
#: and Crypto" (the Instruments section of each of the four programs' pages read).
FUNDINGPIPS_MARKETS: tuple[str, ...] = ("fx", "metals", "indices", "energy", "crypto")

ALPHA_PRO_URL = "https://help.alphacapitalgroup.uk/en/articles/8420429-alpha-pro-8-10"
ALPHA_PRO_6_URL = "https://help.alphacapitalgroup.uk/en/articles/11378706-alpha-pro-6"
ALPHA_SWING_URL = "https://help.alphacapitalgroup.uk/en/articles/9789907-alpha-swing"
ALPHA_DAILY_URL = (
    "https://help.alphacapitalgroup.uk/en/articles/"
    "6934210-what-are-the-daily-risk-limits-and-how-do-they-work"
)
#: "During the evaluation phases, you can trade freely during all news releases";
#: the 5-minute window is for the Qualified Analyst accounts (dated 2026-08-25).
ALPHA_NEWS_URL = "https://help.alphacapitalgroup.uk/en/articles/9293522-can-i-trade-news"
#: "Automated EAs that execute trades independently ... are strictly prohibited";
#: trade-management EAs are approved.
ALPHA_EA_URL = (
    "https://help.alphacapitalgroup.uk/en/articles/6934236-can-i-use-an-expert-advisor-ea"
)
#: "The following assets are tradeable with Alpha Capital Group": forex pairs,
#: index and oil CFDs (UKOIL, USOIL), gold and silver; no crypto.
ALPHA_ASSETS_URL = "https://help.alphacapitalgroup.uk/en/articles/8786240-tradeable-assets"
ALPHA_MARKETS: tuple[str, ...] = ("fx", "metals", "indices", "energy")

E8_SIGNATURE_URL = "https://help.e8markets.com/en/articles/11755943-e8-signature"
E8_ZERO_URL = "https://helpfutures.e8markets.com/en/articles/15935817-e8-zero-starter-and-max"
E8_EOD_URL = "https://help.e8markets.com/en/articles/11864596-eod-dynamic-drawdown"
#: The product overview: "Daily limits | No", "Markets | Futures" and "Expert
#: Advisors | No" for E8 Zero; "Futures- No" expert advisors for E8 Signature.
E8_OVERVIEW_URL = (
    "https://help.e8markets.com/en/articles/"
    "13106558-all-product-overviews-e8-one-vs-e8-zero-vs-e8-pro-vs-e8-signature"
)

FXIFY_STATIC_URL = (
    "https://fxify.com/faqs/all-faqs/everything-you-need-to-know-about-the-2-phase-static-account/"
)
FXIFY_ASSESSMENT_URL = (
    "https://fxify.com/faqs/all-faqs/what-are-the-rules-for-the-assessment-account/"
)
FXIFY_BREACH_URL = (
    "https://fxify.com/faqs/all-faqs/"
    "why-was-my-account-breached-even-though-the-balance-shows-above-the-daily-max-drawdown/"
)

MAVEN_3STEP_URL = "https://maventrading.com/challenges/3-step"
#: "Including all majors in FX, commodities, indices, cryptocurrencies and
#: digital ETF's." (FAQ); its commodities are metals and energy.
MAVEN_FAQ_URL = "https://maventrading.com/faqs"
MAVEN_MARKETS: tuple[str, ...] = ("fx", "metals", "indices", "energy", "crypto")

_FUNDINGPIPS_NEWS = (
    "FundingPips' help pages say both that the evaluation has no news trading restrictions "
    "and that trading news on purpose is prohibited in the evaluation and in the master "
    "phase (" + FUNDINGPIPS_NEWS_URL + "); not simulated."
)
_FUNDINGPIPS_TIME = "No time limit on either phase."
_FUNDINGPIPS_NOTES: dict[str, tuple[str, ...]] = {
    "2-Step Standard": (
        "Daily loss: 5 % of the higher of the opening balance or equity, reset at 00:00 "
        "platform time (UTC+3); the 3 % daily loss add-on, not simulated here, has no "
        "minimum trading days.",
        _FUNDINGPIPS_NEWS,
        _FUNDINGPIPS_TIME,
    ),
    "2-Step Pro": (
        "Daily loss: 3 % of the higher of the opening balance or opening equity of the day.",
        "No minimum trading days on the current rules; accounts bought before them follow "
        "the Legacy Rules (" + FUNDINGPIPS_LEGACY_URL + ").",
        _FUNDINGPIPS_NEWS,
        _FUNDINGPIPS_TIME,
    ),
    "2-Step Flex": (
        "Daily loss: 4 % of the higher of the opening balance or opening equity of the day.",
        "Simulated with the 80 % split, which asks for 1 minimum trading day; the 95 % split "
        "asks instead for 3 days each with a gain of at least 0.5 % of the starting account "
        "size, which the simulator does not model.",
        _FUNDINGPIPS_NEWS,
        _FUNDINGPIPS_TIME,
    ),
    "1-Step Flex": (
        "Simulated with the 3 % daily loss configuration (a 2 % one is also sold): 3 % of "
        "the higher of the balance or equity at the start of the day.",
        "No minimum trading days and no time limit.",
        _FUNDINGPIPS_NEWS,
    ),
}
_FUNDINGPIPS_SOURCES = {
    "2-Step Standard": FUNDINGPIPS_STANDARD_URL,
    "2-Step Pro": FUNDINGPIPS_PRO_URL,
    "2-Step Flex": FUNDINGPIPS_FLEX_URL,
    "1-Step Flex": FUNDINGPIPS_1STEP_FLEX_URL,
}


def _fundingpips(
    key: str,
    program: str,
    phase: str,
    target: float,
    daily: float,
    total: float,
    days: int,
) -> ChallengeRules:
    """A FundingPips phase: the daily limit is a share of the higher of the
    day's opening balance or equity, the maximum loss a static floor."""
    return ChallengeRules(
        key=key,
        firm="FundingPips",
        program=program,
        phase=phase,
        profit_target=target,
        max_daily_loss=daily,
        daily_loss_basis="start_of_day",
        max_total_loss=total,
        total_loss_type="static",
        min_trading_days=days,
        time_limit_days=None,
        notes=_FUNDINGPIPS_NOTES[program],
        source_url=_FUNDINGPIPS_SOURCES[program],
        as_of=NEW_FIRMS_AS_OF,
        markets=FUNDINGPIPS_MARKETS,
        markets_source=_FUNDINGPIPS_SOURCES[program],
        markets_as_of=NEW_FIRMS_AS_OF,
    )


_ALPHA_DAY = (
    "A trading day is a day on which a trade is opened and closed; the simulator counts every "
    "day with a non-zero return, so it may count more days than the firm does."
)
_ALPHA_DURATION = (
    "The average duration of all trades must be greater than 2 minutes; not simulated."
)
_ALPHA_TIME = "No time limit to reach the targets."
_ALPHA_NEWS = (
    "The news trading article says trading is free during the evaluation phases and the "
    "5-minute window applies to Qualified Analyst accounts (" + ALPHA_NEWS_URL + "); the "
    "plan page states the window without that distinction; not simulated."
)
_ALPHA_EA = (
    "Expert advisors that open trades on their own are prohibited; only trade-management "
    "EAs are allowed (" + ALPHA_EA_URL + ")."
)


def _alpha_balance_daily(value: str) -> str:
    return (
        f"Daily loss: {value} % of the balance at the start of the day (00:00 GMT+3), without "
        "the floating profit or loss carried from the day before; the breach is measured on "
        f"current equity ({ALPHA_DAILY_URL})."
    )


_ALPHA_NOTES: dict[str, tuple[str, ...]] = {
    "Alpha Pro 8%": (
        _alpha_balance_daily("4"),
        _ALPHA_DAY,
        _ALPHA_DURATION,
        _ALPHA_NEWS,
        _ALPHA_EA,
        _ALPHA_TIME,
    ),
    "Alpha Pro 10%": (
        _alpha_balance_daily("5"),
        _ALPHA_DAY,
        _ALPHA_DURATION,
        _ALPHA_NEWS,
        _ALPHA_EA,
        _ALPHA_TIME,
    ),
    "Alpha Pro 6%": (
        "Daily loss: 3 % of the higher of the balance or equity at the start of the day "
        f"(00:00 GMT+3); the breach is measured on current equity ({ALPHA_DAILY_URL}).",
        _ALPHA_DAY,
        _ALPHA_DURATION,
        _ALPHA_NEWS,
        _ALPHA_EA,
        _ALPHA_TIME,
    ),
    "Alpha Swing": (
        _alpha_balance_daily("5"),
        "A trade opened from 2 minutes before to 2 minutes after a news release must last "
        "more than 2 minutes to be valid; not simulated.",
        _ALPHA_DAY,
        _ALPHA_DURATION,
        _ALPHA_EA,
        _ALPHA_TIME,
    ),
}
_ALPHA_SOURCES = {
    "Alpha Pro 8%": ALPHA_PRO_URL,
    "Alpha Pro 10%": ALPHA_PRO_URL,
    "Alpha Pro 6%": ALPHA_PRO_6_URL,
    "Alpha Swing": ALPHA_SWING_URL,
}


def _alpha(
    key: str, program: str, phase: str, target: float, daily: float, total: float
) -> ChallengeRules:
    """An Alpha Capital Group phase: static maximum loss, 3 trading days per phase."""
    return ChallengeRules(
        key=key,
        firm="Alpha Capital Group",
        program=program,
        phase=phase,
        profit_target=target,
        max_daily_loss=daily,
        daily_loss_basis="start_of_day",
        max_total_loss=total,
        total_loss_type="static",
        min_trading_days=3,
        time_limit_days=None,
        notes=_ALPHA_NOTES[program],
        source_url=_ALPHA_SOURCES[program],
        as_of=NEW_FIRMS_AS_OF,
        markets=ALPHA_MARKETS,
        markets_source=ALPHA_ASSETS_URL,
        markets_as_of=NEW_FIRMS_AS_OF,
    )


def _fxify_daily(value: str) -> str:
    return (
        f"Daily loss: {value} % of the balance recorded at 5 PM EST the day before; a breach "
        f"is measured on real-time equity ({FXIFY_BREACH_URL})."
    )


_FXIFY_CLASSIC_NOTES = (
    _fxify_daily("4"),
    "Static maximum loss: 10 % of the initial balance for the life of the account.",
    "Minimum trading days: the 2 Phase Static (Two Phase Classic) account page says 4, the "
    "general assessment rules say 5 for all accounts (" + FXIFY_ASSESSMENT_URL + "); the "
    "simulator uses 5 (stricter).",
    "No consistency rule in the evaluation phases; no maximum number of trading days.",
)


def _fxify_classic(key: str, phase: str, target: float) -> ChallengeRules:
    """FXIFY's two-phase account with a static drawdown (Classic)."""
    return ChallengeRules(
        key=key,
        firm="FXIFY",
        program="Two Phase Classic",
        phase=phase,
        profit_target=target,
        max_daily_loss=0.04,
        daily_loss_basis="start_of_day",
        max_total_loss=0.10,
        total_loss_type="static",
        min_trading_days=5,
        time_limit_days=None,
        notes=_FXIFY_CLASSIC_NOTES,
        source_url=FXIFY_STATIC_URL,
        as_of=NEW_FIRMS_AS_OF,
    )


#: E8 Markets states these programs' target and maximum loss in dollars at one
#: account size: the preset and that size.
_E8_ACCOUNTS: dict[str, int] = {"e8-signature-100k": 100_000, "e8-zero-100k": 100_000}

_NEW_FIRM_PRESETS: tuple[ChallengeRules, ...] = (
    _fundingpips("fundingpips-2step-standard-phase1", "2-Step Standard", "1", 0.08, 0.05, 0.10, 3),
    _fundingpips("fundingpips-2step-standard-phase2", "2-Step Standard", "2", 0.05, 0.05, 0.10, 3),
    _fundingpips("fundingpips-2step-pro-phase1", "2-Step Pro", "1", 0.06, 0.03, 0.06, 0),
    _fundingpips("fundingpips-2step-pro-phase2", "2-Step Pro", "2", 0.06, 0.03, 0.06, 0),
    _fundingpips("fundingpips-2step-flex-phase1", "2-Step Flex", "1", 0.10, 0.04, 0.12, 1),
    _fundingpips("fundingpips-2step-flex-phase2", "2-Step Flex", "2", 0.08, 0.04, 0.12, 1),
    _fundingpips("fundingpips-1step-flex", "1-Step Flex", "1", 0.12, 0.03, 0.12, 0),
    _alpha("alpha-pro-8-phase1", "Alpha Pro 8%", "1", 0.08, 0.04, 0.08),
    _alpha("alpha-pro-8-phase2", "Alpha Pro 8%", "2", 0.05, 0.04, 0.08),
    _alpha("alpha-pro-10-phase1", "Alpha Pro 10%", "1", 0.10, 0.05, 0.10),
    _alpha("alpha-pro-10-phase2", "Alpha Pro 10%", "2", 0.05, 0.05, 0.10),
    _alpha("alpha-pro-6-phase1", "Alpha Pro 6%", "1", 0.06, 0.03, 0.06),
    _alpha("alpha-pro-6-phase2", "Alpha Pro 6%", "2", 0.06, 0.03, 0.06),
    _alpha("alpha-swing-phase1", "Alpha Swing", "1", 0.10, 0.05, 0.10),
    _alpha("alpha-swing-phase2", "Alpha Swing", "2", 0.05, 0.05, 0.10),
    ChallengeRules(
        key="e8-signature-100k",
        firm="E8 Markets",
        program="Signature 100K",
        phase="1",
        # "$6,000 Profit Target - $100,000 account"; "$3,000 EOD - $100,000 account".
        profit_target=6_000 / _E8_ACCOUNTS["e8-signature-100k"],
        max_daily_loss=None,
        daily_loss_basis="none",
        max_total_loss=3_000 / _E8_ACCOUNTS["e8-signature-100k"],
        total_loss_type="trailing_eod_lock",
        min_trading_days=0,
        time_limit_days=None,
        notes=(
            "No daily loss limit in the challenge: the daily pause applies only to the "
            "Performance account (" + E8_OVERVIEW_URL + ").",
            "The maximum loss trails the highest end-of-day balance, updates once a day at "
            "market close and locks at the initial balance; a breach is checked whenever "
            "equity or balance reaches the level (" + E8_EOD_URL + ").",
            "All positions are closed by 23:00 server time: no overnight or weekend holding.",
            "No best-day rule in the challenge; the 35 % best-day rule applies to the "
            "Performance account's payouts.",
            "No minimum trading days and no time limit; at least one trade must be placed and "
            "closed every 60 days.",
            "Expert advisors are allowed on Classic Markets and not on Futures ("
            + E8_OVERVIEW_URL
            + ").",
        ),
        source_url=E8_SIGNATURE_URL,
        as_of=NEW_FIRMS_AS_OF,
    ),
    ChallengeRules(
        key="e8-zero-100k",
        firm="E8 Markets",
        program="Zero 100K",
        phase="1",
        # "$100,000 - $6,500" (target); "$100,000 - $3,000" (EOD drawdown).
        profit_target=6_500 / _E8_ACCOUNTS["e8-zero-100k"],
        max_daily_loss=None,
        daily_loss_basis="none",
        max_total_loss=3_000 / _E8_ACCOUNTS["e8-zero-100k"],
        total_loss_type="trailing_eod",
        min_trading_days=0,
        time_limit_days=None,
        notes=(
            "No daily loss limit (" + E8_OVERVIEW_URL + ").",
            "The maximum loss trails the highest end-of-day balance; the drawdown article "
            "says it does not lock at the initial balance in the challenge, the product "
            "overview says it does, and the simulator lets it trail without locking "
            "(stricter) (" + E8_EOD_URL + ").",
            "Best-day rule: no day may exceed 40 % of the total profit; checked against the "
            "profit target when a path reaches it, on daily closes, which is stricter.",
            "All open positions are closed every day at 15:10 CT: no overnight holding.",
            "No minimum trading days; at least one trade must be placed and closed every 7 days.",
            "Expert advisors are not allowed (" + E8_OVERVIEW_URL + ").",
        ),
        source_url=E8_ZERO_URL,
        as_of=NEW_FIRMS_AS_OF,
        best_day_limit=0.40,
        best_day_basis="profit_target",
        markets=("futures",),
        markets_source=E8_OVERVIEW_URL,
        markets_as_of=NEW_FIRMS_AS_OF,
    ),
    _fxify_classic("fxify-2phase-classic-phase1", "1", 0.05),
    _fxify_classic("fxify-2phase-classic-phase2", "2", 0.10),
    ChallengeRules(
        key="fxify-3phase-step",
        firm="FXIFY",
        program="Three Phase",
        phase="each of phases 1-3",
        profit_target=0.05,
        max_daily_loss=0.05,
        daily_loss_basis="start_of_day",
        max_total_loss=0.05,
        total_loss_type="static",
        min_trading_days=5,
        time_limit_days=None,
        notes=(
            _fxify_daily("5"),
            "Static maximum loss: 5 % of the initial balance for the life of the account.",
            "No maximum number of trading days in any of the three phases.",
        ),
        source_url=FXIFY_ASSESSMENT_URL,
        as_of=NEW_FIRMS_AS_OF,
    ),
    ChallengeRules(
        key="maven-3step-step",
        firm="Maven Trading",
        program="3-Step",
        phase="each of steps 1-3",
        profit_target=0.03,
        max_daily_loss=0.02,
        daily_loss_basis="start_of_day",
        max_total_loss=0.03,
        total_loss_type="static",
        min_trading_days=0,
        time_limit_days=None,
        notes=(
            "Daily loss: 2 % of the higher of the equity or balance at 00:00 UTC; the trading "
            "day runs from 00:00 to 23:59 UTC (" + MAVEN_FAQ_URL + ").",
            "The pages read state no minimum trading days or time limit for the 3-Step; "
            "accounts may not be dormant for more than 30 calendar days.",
            "No trade may be opened or closed from 2 minutes before to 2 minutes after a "
            "red-folder news release; not simulated.",
            "Expert advisors are not allowed on this model.",
            "A single trade without a stop-loss, or risking more than 2 % (the 3-Step "
            "drawdown limit), counts as prohibited all-in trading (" + MAVEN_FAQ_URL + "); not "
            "simulated.",
        ),
        source_url=MAVEN_3STEP_URL,
        as_of=NEW_FIRMS_AS_OF,
        markets=MAVEN_MARKETS,
        markets_source=MAVEN_FAQ_URL,
        markets_as_of=NEW_FIRMS_AS_OF,
    ),
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
            "checked when a path reaches the target, on daily closes.",
            "No minimum trading days; no time limit (" + FTMO_TIME_URL + ").",
        ),
        source_url=FTMO_URL,
        as_of=AS_OF,
        best_day_limit=0.50,
        best_day_basis="positive_days",
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
        markets=THE5ERS_HIGH_STAKES_MARKETS,
        markets_source=THE5ERS_HIGH_STAKES_URL,
        markets_as_of=MARKETS_AS_OF,
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
        markets=THE5ERS_HIGH_STAKES_MARKETS,
        markets_source=THE5ERS_HIGH_STAKES_URL,
        markets_as_of=MARKETS_AS_OF,
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
            "The rules page table asks for 3 days that close in gain, while its text says there "
            "is no minimum days requirement; the simulator uses none (optimistic if the table "
            "applies).",
            "Unlimited time.",
        ),
        source_url=THE5ERS_HYPER_GROWTH_URL,
        as_of=AS_OF,
        markets=THE5ERS_HYPER_GROWTH_MARKETS,
        markets_source=THE5ERS_HYPER_GROWTH_URL,
        markets_as_of=MARKETS_AS_OF,
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
    *(_topstep(size, loss / account) for size, account, loss in _TOPSTEP_ACCOUNTS),
    *_NEW_FIRM_PRESETS,
)

PRESETS: dict[str, ChallengeRules] = {rules.key: rules for rules in _PRESET_LIST}

#: The account size, in US dollars, of the presets whose program names one (the
#: firm states its limits in dollars at that size). Every other preset's rules
#: are shares of whatever balance the account starts with.
ACCOUNT_SIZES: dict[str, float] = {
    **{f"topstep-{size.lower()}-combine": float(account) for size, account, _ in _TOPSTEP_ACCOUNTS},
    **{key: float(account) for key, account in _E8_ACCOUNTS.items()},
}


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
        word = "fase" if locale in ("es", "pt") else "phase"
        parts.append(
            f"{word} {localize(phase, locale)}" if phase[0].isdigit() else localize(phase, locale)
        )
    return " · ".join(part for part in parts if part)


__all__ = [
    "preset_label",
    "ACCOUNT_SIZES",
    "DAILY_LOSS_BASES",
    "DEFAULT_PRESET",
    "AS_OF",
    "MARKETS",
    "MARKETS_AS_OF",
    "NEW_FIRMS_AS_OF",
    "PRESETS",
    "TOTAL_LOSS_TYPES",
    "ChallengeRules",
    "DailyLossBasis",
    "TotalLossType",
    "get_preset",
]
