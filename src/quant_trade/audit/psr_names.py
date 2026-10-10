"""Which probabilistic Sharpe a figure is, named the same in the plan, the tables and the detail.

The engine stores two probabilities that the true Sharpe is above zero: the
plain count, which takes the returns as independent (``significance.psr``),
and the one adjusted for the returns' dependence on each other
(``significance.dependence.psr``). Since policy 2026-09-27-dependence-1 the
statistical dimension uses the lower of the two (``engine.run_audit``), which
is the adjusted one whenever it is measured: widening the variance never
raises the probability. A result stored the day before that policy kept the
adjusted figure as information and classified with the plain count. This module
computes nothing; it reads which figure the stored result used and gives it
one name in Spanish, English and Portuguese, so the plan, the significance
table and the technical detail never show two figures under the same name.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

PLAIN = "plain"
ADJUSTED = "adjusted"

#: The name of each figure, verbatim wherever the report shows it.
NAMES: dict[str, dict[str, str]] = {
    PLAIN: {
        "es": "PSR (cuenta simple)",
        "en": "PSR (plain count)",
        "pt": "PSR (conta simples)",
    },
    ADJUSTED: {
        "es": "PSR ajustado por dependencia",
        "en": "PSR adjusted for dependence",
        "pt": "PSR ajustado por dependência",
    },
}

#: The note of the adjusted figure's row in the significance table when the class
#: used it (``class_psr`` says ADJUSTED); an engine-style English note: ``i18n``
#: and ``report_pt`` give its Spanish and Portuguese.
CLASS_NOTE = "the figure the class uses: the lower of the two, since it never reads higher"


def psr_name(kind: str, locale: str) -> str:
    """The name of the ``kind`` figure in ``locale`` (English by default)."""
    names = NAMES.get(kind, NAMES[PLAIN])
    return names.get(locale, names["en"])


def _measured(block: Any) -> float | None:
    if not isinstance(block, Mapping) or block.get("evidence") != "MEASURED":
        return None
    value = block.get("value")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _dimension_psr(data: Mapping[str, Any]) -> float | None:
    """The PSR the statistical dimension's inputs record, when they do."""
    for dimension in (data.get("verdict") or {}).get("dimensions") or []:
        if isinstance(dimension, Mapping) and dimension.get("name") == "statistical_significance":
            return _measured((dimension.get("inputs") or {}).get("psr"))
    return None


def class_psr(data: Mapping[str, Any]) -> tuple[float | None, float | None, str]:
    """``(psr, track, kind)``: the probability the statistical dimension uses,
    the track record length that goes with it and which of the two it is.

    Read from the stored result (its JSON dict): the dimension's own input when
    it is there, else the lower of the two measured figures, as the engine
    takes it. ``track`` is the minimum track record of the same figure."""
    significance = data.get("significance") or {}
    dependence = significance.get("dependence") or {}
    plain = _measured(significance.get("psr"))
    adjusted = _measured(dependence.get("psr"))
    used = _dimension_psr(data)
    if used is None:
        used = min(plain, adjusted) if plain is not None and adjusted is not None else plain
    kind = (
        ADJUSTED
        if adjusted is not None
        and used is not None
        and math.isclose(used, adjusted, rel_tol=0.0, abs_tol=1e-12)
        else PLAIN
    )
    track = _measured(
        dependence.get("min_track_record_length")
        if kind == ADJUSTED
        else significance.get("min_track_record_length")
    )
    return used, track, kind


def class_psr_name(data: Mapping[str, Any], locale: str) -> str:
    """The name of the figure the statistical dimension uses, in ``locale``."""
    return psr_name(class_psr(data)[2], locale)


__all__ = [
    "ADJUSTED",
    "CLASS_NOTE",
    "NAMES",
    "PLAIN",
    "class_psr",
    "class_psr_name",
    "psr_name",
]
