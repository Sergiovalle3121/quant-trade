"""The calibration table: which ``(check, family)`` cells may answer SIGNAL.

A cell is filled only from a run over real public files (never fixtures,
never client files) with the split, freeze and reserved third described in
``docs/AUDIT_FORENSICS.md``. Until a cell holds at least twenty files from
ten or more accounts or strategies, with no unexplained signal and a freeze
date, its check answers INFO on a hit.

A test pins the SHA-256 of this module together with ``thresholds.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

from quant_trade.audit.forensics.thresholds import (
    CALIBRATION_MIN_FILES,
    CALIBRATION_MIN_GROUPS,
    FREEZE_DATE,
)


@dataclass(frozen=True)
class Cell:
    n: int
    n_reserved: int
    unexplained: int
    frozen: str = ""
    #: Distinct accounts or strategies behind ``n`` (calibration files).
    groups: int = 0

    @property
    def granted(self) -> bool:
        return (
            bool(self.frozen)
            and self.n >= CALIBRATION_MIN_FILES
            and self.groups >= CALIBRATION_MIN_GROUPS
            and self.unexplained == 0
        )


#: Checks with a platform identity behind them: the only ones that can be
#: granted SIGNAL. The rest are descriptive by design.
SIGNAL_CAPABLE: frozenset[str] = frozenset(
    {
        "TOTALS_VS_ROWS",
        "SUMMARY_IDENTITIES",
        "BALANCE_CHAIN",
        "DEAL_SEQUENCE",
        "TESTER_NUMBERING",
        "DUPLICATE_TICKET",
        "TICKET_LINKS",
        "CROSS_COPIES",
        "SLTP_FILL",
        "PNL_SIGN",
        "PRICE_PRECISION",
        "TIME_SANITY",
        "MARKET_HOURS",
        "HIDDEN_CONTENT",
        "ROW_ORDER",
    }
)

#: ``(check_id, family) -> Cell``, from the run of 2026-09-26 over the public
#: corpus (never committed; ``docs/AUDIT_FORENSICS.md`` lists its URLs):
#: manifest ``genuine_manifest.json`` sha256
#: 3fcf50a65cbe40159fc643c4a4124f53
#: 76eaa11e5de09216855ca4d2536838c9, 197 genuine files in 122 groups
#: (an account or a strategy exported more than once is one group). Split
#: per family: groups sorted by their smallest sha256, every third group
#: (positions 2, 5, 8, ...) reserved: 157 calibration files, 40 reserved.
#: ``n`` counts calibration files on which the check measured (CLEAN or
#: INFO), ``n_reserved`` the reserved third, opened once after the freeze;
#: ``unexplained`` counts files with a hit that no scoping rule explains,
#: reserved hits included; ``groups`` counts the distinct accounts or
#: strategies behind ``n``. ``granted`` needs n >= CALIBRATION_MIN_FILES,
#: groups >= CALIBRATION_MIN_GROUPS and unexplained == 0.
CALIBRATION: dict[tuple[str, str], Cell] = {
    ("TOTALS_VS_ROWS", "mt4_statement"): Cell(
        n=65, groups=8, n_reserved=4, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TOTALS_VS_ROWS", "mt4_tester"): Cell(
        n=15, groups=15, n_reserved=7, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TOTALS_VS_ROWS", "mt5_history"): Cell(
        n=10, groups=6, n_reserved=1, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TOTALS_VS_ROWS", "mt5_tester"): Cell(
        n=26, groups=26, n_reserved=13, unexplained=0, frozen=FREEZE_DATE
    ),
    ("SUMMARY_IDENTITIES", "mt4_statement"): Cell(
        n=65, groups=8, n_reserved=4, unexplained=0, frozen=FREEZE_DATE
    ),
    ("SUMMARY_IDENTITIES", "mt4_tester"): Cell(
        n=15, groups=15, n_reserved=7, unexplained=0, frozen=FREEZE_DATE
    ),
    ("SUMMARY_IDENTITIES", "mt5_history"): Cell(
        n=11, groups=6, n_reserved=2, unexplained=0, frozen=FREEZE_DATE
    ),
    ("SUMMARY_IDENTITIES", "mt5_tester"): Cell(
        n=26, groups=26, n_reserved=13, unexplained=0, frozen=FREEZE_DATE
    ),
    ("BALANCE_CHAIN", "mt4_tester"): Cell(
        n=15, groups=15, n_reserved=7, unexplained=0, frozen=FREEZE_DATE
    ),
    ("BALANCE_CHAIN", "mt5_history"): Cell(
        n=11, groups=6, n_reserved=2, unexplained=1, frozen=FREEZE_DATE
    ),
    ("BALANCE_CHAIN", "mt5_tester"): Cell(
        n=26, groups=26, n_reserved=13, unexplained=0, frozen=FREEZE_DATE
    ),
    ("DEAL_SEQUENCE", "mt5_history"): Cell(
        n=11, groups=6, n_reserved=2, unexplained=0, frozen=FREEZE_DATE
    ),
    ("DEAL_SEQUENCE", "mt5_tester"): Cell(
        n=26, groups=26, n_reserved=13, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TESTER_NUMBERING", "mt4_tester"): Cell(
        n=15, groups=15, n_reserved=7, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TESTER_NUMBERING", "mt5_tester"): Cell(
        n=26, groups=26, n_reserved=13, unexplained=0, frozen=FREEZE_DATE
    ),
    ("DUPLICATE_TICKET", "mt4_statement"): Cell(
        n=65, groups=8, n_reserved=5, unexplained=0, frozen=FREEZE_DATE
    ),
    ("DUPLICATE_TICKET", "mt5_history"): Cell(
        n=11, groups=6, n_reserved=2, unexplained=0, frozen=FREEZE_DATE
    ),
    ("DUPLICATE_TICKET", "mt5_tester"): Cell(
        n=26, groups=26, n_reserved=13, unexplained=0, frozen=FREEZE_DATE
    ),
    ("DUPLICATE_TICKET", "myfxbook"): Cell(
        n=13, groups=9, n_reserved=3, unexplained=0, frozen=FREEZE_DATE
    ),
    ("CROSS_COPIES", "mt5_history"): Cell(
        n=8, groups=4, n_reserved=1, unexplained=0, frozen=FREEZE_DATE
    ),
    ("SLTP_FILL", "mt4_statement"): Cell(
        n=14, groups=6, n_reserved=1, unexplained=0, frozen=FREEZE_DATE
    ),
    ("SLTP_FILL", "mt5_history"): Cell(
        n=7, groups=3, n_reserved=2, unexplained=0, frozen=FREEZE_DATE
    ),
    ("SLTP_FILL", "mt5_tester"): Cell(
        n=23, groups=23, n_reserved=12, unexplained=0, frozen=FREEZE_DATE
    ),
    ("PNL_SIGN", "fxblue"): Cell(n=5, groups=2, n_reserved=0, unexplained=0, frozen=FREEZE_DATE),
    ("PNL_SIGN", "mql5_signal"): Cell(
        n=20, groups=16, n_reserved=8, unexplained=0, frozen=FREEZE_DATE
    ),
    ("PNL_SIGN", "mt4_statement"): Cell(
        n=65, groups=8, n_reserved=5, unexplained=0, frozen=FREEZE_DATE
    ),
    ("PNL_SIGN", "mt5_history"): Cell(
        n=8, groups=4, n_reserved=1, unexplained=0, frozen=FREEZE_DATE
    ),
    ("PNL_SIGN", "myfxbook"): Cell(
        n=15, groups=11, n_reserved=5, unexplained=0, frozen=FREEZE_DATE
    ),
    ("PRICE_PRECISION", "mt4_statement"): Cell(
        n=65, groups=8, n_reserved=5, unexplained=0, frozen=FREEZE_DATE
    ),
    ("PRICE_PRECISION", "mt4_tester"): Cell(
        n=15, groups=15, n_reserved=7, unexplained=0, frozen=FREEZE_DATE
    ),
    ("PRICE_PRECISION", "mt5_history"): Cell(
        n=10, groups=6, n_reserved=0, unexplained=0, frozen=FREEZE_DATE
    ),
    ("PRICE_PRECISION", "mt5_tester"): Cell(
        n=23, groups=23, n_reserved=12, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TIME_SANITY", "fxblue"): Cell(n=5, groups=2, n_reserved=0, unexplained=0, frozen=FREEZE_DATE),
    ("TIME_SANITY", "mql5_signal"): Cell(
        n=20, groups=16, n_reserved=8, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TIME_SANITY", "mt4_statement"): Cell(
        n=65, groups=8, n_reserved=5, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TIME_SANITY", "mt4_tester"): Cell(
        n=15, groups=15, n_reserved=7, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TIME_SANITY", "mt5_history"): Cell(
        n=11, groups=6, n_reserved=2, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TIME_SANITY", "mt5_tester"): Cell(
        n=26, groups=26, n_reserved=13, unexplained=0, frozen=FREEZE_DATE
    ),
    ("TIME_SANITY", "myfxbook"): Cell(
        n=15, groups=11, n_reserved=5, unexplained=0, frozen=FREEZE_DATE
    ),
    ("ROW_ORDER", "fxblue"): Cell(n=5, groups=2, n_reserved=0, unexplained=0, frozen=FREEZE_DATE),
    ("ROW_ORDER", "mql5_signal"): Cell(
        n=20, groups=16, n_reserved=8, unexplained=0, frozen=FREEZE_DATE
    ),
    ("ROW_ORDER", "mt4_statement"): Cell(
        n=65, groups=8, n_reserved=5, unexplained=0, frozen=FREEZE_DATE
    ),
    ("ROW_ORDER", "mt4_tester"): Cell(
        n=15, groups=15, n_reserved=7, unexplained=0, frozen=FREEZE_DATE
    ),
    ("ROW_ORDER", "mt5_history"): Cell(
        n=11, groups=6, n_reserved=2, unexplained=0, frozen=FREEZE_DATE
    ),
    ("ROW_ORDER", "mt5_tester"): Cell(
        n=26, groups=26, n_reserved=13, unexplained=0, frozen=FREEZE_DATE
    ),
    ("ROW_ORDER", "myfxbook"): Cell(
        n=15, groups=11, n_reserved=5, unexplained=0, frozen=FREEZE_DATE
    ),
    ("MARKET_HOURS", "fxblue"): Cell(
        n=5, groups=2, n_reserved=0, unexplained=0, frozen=FREEZE_DATE
    ),
    ("MARKET_HOURS", "mql5_signal"): Cell(
        n=7, groups=6, n_reserved=4, unexplained=0, frozen=FREEZE_DATE
    ),
    ("MARKET_HOURS", "mt4_statement"): Cell(
        n=16, groups=6, n_reserved=3, unexplained=0, frozen=FREEZE_DATE
    ),
    ("MARKET_HOURS", "mt4_tester"): Cell(
        n=14, groups=14, n_reserved=6, unexplained=0, frozen=FREEZE_DATE
    ),
    ("MARKET_HOURS", "mt5_history"): Cell(
        n=2, groups=2, n_reserved=1, unexplained=0, frozen=FREEZE_DATE
    ),
    ("MARKET_HOURS", "mt5_tester"): Cell(
        n=10, groups=10, n_reserved=6, unexplained=0, frozen=FREEZE_DATE
    ),
    ("MARKET_HOURS", "myfxbook"): Cell(
        n=13, groups=9, n_reserved=5, unexplained=0, frozen=FREEZE_DATE
    ),
    ("HIDDEN_CONTENT", "mt5_history"): Cell(
        n=10, groups=6, n_reserved=0, unexplained=0, frozen=FREEZE_DATE
    ),
    ("HIDDEN_CONTENT", "mt5_tester"): Cell(
        n=23, groups=23, n_reserved=12, unexplained=0, frozen=FREEZE_DATE
    ),
}

#: Hits a granted cell tolerates before SIGNAL; missing means 0 (any hit).
#: Nothing is tolerated in this freeze.
THRESHOLDS: dict[tuple[str, str], int] = {}


def clopper_pearson_upper_pct(signals: int, n: int) -> str:
    """The two-sided 95 % Clopper-Pearson upper bound of the signal rate, as
    a percentage with one decimal; ``"100.0"`` when nothing was measured."""
    if n <= 0:
        return "100.0"
    if signals >= n:
        return "100.0"
    if signals == 0:
        bound = 1 - 0.025 ** (1 / n)
    else:
        bound = _beta_quantile(0.975, signals + 1, n - signals)
    return f"{bound * 100:.1f}"


def _beta_quantile(p: float, a: float, b: float) -> float:
    """Inverse of the regularised incomplete beta by bisection (deterministic)."""
    low, high = 0.0, 1.0
    for _ in range(200):
        mid = (low + high) / 2
        if _regularised_beta(mid, a, b) < p:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def _regularised_beta(x: float, a: float, b: float) -> float:
    """I_x(a, b) by Lentz's continued fraction (Numerical Recipes betacf)."""
    import math

    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    if x > (a + 1) / (a + b + 2):
        return 1 - _regularised_beta(1 - x, b, a)
    tiny = 1e-300
    c, d = 1.0, 1 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > tiny else tiny)
    result = d
    for m in range(1, 300):
        m2 = 2 * m
        numerator = m * (b - m) * x / ((a + m2 - 1) * (a + m2))
        d = 1 + numerator * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + numerator / (c if abs(c) > tiny else tiny)
        result *= d * c
        numerator = -(a + m) * (a + b + m) * x / ((a + m2) * (a + m2 + 1))
        d = 1 + numerator * d
        d = 1 / (d if abs(d) > tiny else tiny)
        c = 1 + numerator / (c if abs(c) > tiny else tiny)
        delta = d * c
        result *= delta
        if abs(delta - 1) < 1e-12:
            break
    return front * result / a
