"""How much of the Sharpe is left once the luck of the search is taken out?

The deflated Sharpe answers with a probability, which few buyers can read.
This module restates the same question in three plain numbers, from the
return moments and the trial count the multiplicity dimension already uses:

* **Sharpe from luck**: the best annualised Sharpe that ``N`` configurations
  with no skill are expected to show, E[max Sharpe] (Bailey & López de
  Prado, 2014), with the same cross-trial variance as the deflated Sharpe.
* **Years of history needed**: the span at which that best-of-``N`` luck no
  longer reaches the observed Sharpe (the minimum backtest length of Bailey,
  Borwein, López de Prado and Zhu, 2014). The spread of unskilled Sharpes
  shrinks as ``1 / years``, so ``years x (luck / observed)^2``.
* **Sharpe after the haircut**: Harvey & Liu (2015) with the Bonferroni
  correction: the observed Sharpe's one-sided p-value multiplied by ``N``,
  turned back into a Sharpe. The standard error is the square root of the
  deflated Sharpe's variance, so the two never disagree: the haircut leaves
  nothing when the Sharpe does not clear the luck (DSR below 0.5), which is
  exactly when the multiplicity dimension fails.

When the files do not count the configurations, the section shows what a
search of 10, 100 or 1,000 would need instead.

Every figure describes the uploaded history. Nothing here is new statistics
and none of it changes the class: the multiplicity dimension already grades
the same evidence.
"""

from __future__ import annotations

import math
from typing import Any

from quant_trade.audit.schema import measured
from quant_trade.metrics.statistics import _phi, _phi_inv, expected_max_sharpe

#: Below this many configurations there is no search to discount.
MIN_TRIALS = 2
#: Fewer returns or days than this, and an annualised Sharpe means little.
MIN_OBSERVATIONS = 20
MIN_SPAN_DAYS = 28
#: Search sizes shown when the files do not say how many were tried.
WHAT_IF_TRIALS = (10, 100, 1000)

NOTE = (
    "E[max Sharpe] of unskilled trials (Bailey & Lopez de Prado); minimum backtest "
    "length (Bailey, Borwein, Lopez de Prado & Zhu); Bonferroni haircut (Harvey & Liu)"
)


def _not_measured(reason: str) -> dict[str, Any]:
    return {"status": "NOT_MEASURED", "reason": reason}


def luck_review(
    moments: dict[str, float] | None,
    *,
    trials: int,
    trials_source: str,
    sharpe_variance: float | None,
    periods_per_year: float,
    span_years: float,
) -> dict[str, Any]:
    """The observed Sharpe next to what ``trials`` unskilled tries would show."""
    if moments is None or sharpe_variance is None:
        return _not_measured("statistical significance not measured")
    sr = float(moments["sharpe_per_period"])
    n = int(moments["observations"])
    if not math.isfinite(sr) or sr <= 0:
        return _not_measured("the Sharpe ratio is zero or negative; there is no gain to discount")
    if (
        span_years * 365.25 < MIN_SPAN_DAYS
        or n < MIN_OBSERVATIONS
        or periods_per_year <= 0
        or sharpe_variance <= 0
    ):
        return _not_measured("too short a history to discount")
    scale = math.sqrt(periods_per_year)
    observed = sr * scale

    def luck_of(count: int) -> float:
        return expected_max_sharpe(count, sharpe_variance) * scale

    what_if = [
        {
            "trials": count,
            "luck_sharpe": measured(luck_of(count)),
            "years_needed": measured(span_years * (luck_of(count) / observed) ** 2),
        }
        for count in WHAT_IF_TRIALS
    ]
    base = {
        "status": "MEASURED",
        "counted": trials >= MIN_TRIALS,
        "trials": trials,
        "trials_source": trials_source,
        "sharpe": measured(observed, "annualised Sharpe of the uploaded history"),
        "span_years": measured(span_years, "first to last date of the uploaded history"),
        "what_if": what_if,
        "note": NOTE,
    }
    if trials < MIN_TRIALS:
        # No count to discount by: the table says what each search size would need.
        return base
    luck = luck_of(trials)
    years_needed = span_years * (luck / observed) ** 2

    # Harvey & Liu with the same Sharpe spread as the deflated Sharpe, so a
    # Sharpe left after the haircut always clears the luck above it.
    se = math.sqrt(sharpe_variance)
    p_value = 1.0 - _phi(sr / se)
    p_adjusted = min(1.0, p_value * trials)
    haircut_sr = max(0.0, _phi_inv(1.0 - p_adjusted) * se) if p_adjusted < 0.5 else 0.0
    if observed <= luck:
        haircut_sr = 0.0
    after = haircut_sr * scale
    return {
        **base,
        "beats_luck": observed > luck,
        "luck_sharpe": measured(
            luck, f"best annualised Sharpe {trials} trials with no skill would show"
        ),
        "years_needed": measured(
            years_needed,
            f"years of history at which the luck of {trials} trials falls below this Sharpe",
        ),
        "p_value": measured(
            p_value,
            "one-sided p-value of the Sharpe, one test, with the spread of the deflated Sharpe",
        ),
        "p_adjusted": measured(p_adjusted, f"p-value x {trials} (Bonferroni)"),
        "sharpe_after": measured(after, f"annualised Sharpe after discounting {trials} trials"),
        "haircut": measured(1.0 - after / observed, "share of the Sharpe the haircut removes"),
    }
