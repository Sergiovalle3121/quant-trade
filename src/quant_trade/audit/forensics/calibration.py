"""The calibration table: which ``(check, family)`` cells may answer SIGNAL.

A cell is filled only from a run over real public files (never fixtures,
never client files) with the split, freeze and reserved third described in
``docs/AUDIT_FORENSICS.md``. Until a cell holds at least twenty files with no
unexplained signal and a freeze date, its check answers INFO on a hit.

A test pins the SHA-256 of this module together with ``thresholds.py``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Cell:
    n: int
    n_reserved: int
    unexplained: int
    frozen: str = ""

    @property
    def granted(self) -> bool:
        from quant_trade.audit.forensics.thresholds import CALIBRATION_MIN_FILES

        return bool(self.frozen) and self.n >= CALIBRATION_MIN_FILES and self.unexplained == 0


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

#: ``(check_id, family) -> Cell``. Empty until the first corpus run is frozen.
CALIBRATION: dict[tuple[str, str], Cell] = {}

#: Hits a granted cell tolerates before SIGNAL; missing means 0 (any hit).
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
