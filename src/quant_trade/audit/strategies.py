""" "Mis estrategias": the versions of one strategy, one after the other.

An account names a strategy ("EA Gold") and files its reports under it. The
strategy page lists the versions oldest first with their class and three
measured figures, and beside each version says what changed against the one
before. Only what the audit itself measured is compared, and a figure is
called better or worse only when the change is larger than its own
measurement noise:

* the class (A to D) is already thresholded by the audit, so a different
  class is better or worse; a dimension's result (pass, weak, fail) is
  said to have "changed", since each report carries its own declarations;
* the Sharpe ratio is compared through the bootstrap's 5-95 % band: better
  or worse only when the two bands do not overlap, on the same data
  frequency and mostly the same dates, else "no clear change". On the same
  dates the rule is cautious, since the two versions share their noise.

A locked preview shows its class only; what changed in each test needs both
reports complete. Nothing here unlocks, predicts or ranks strategies by
money: every sentence is fixed text that passes the profit-claim guard.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from quant_trade.audit.report import STATUS_TEXT, _dimension_title
from quant_trade.audit.verdict import DIMENSION_ORDER

#: Better classes first.
CLASS_ORDER = ("A", "B", "C", "D")
#: Dimension results that can be ranked; the rest (not measured, not
#: applicable) are not compared.
STATUS_RANK = {"PASS": 2, "WEAK": 1, "FAIL": 0}

COPY: dict[str, dict[str, str]] = {
    "es": {
        "section_title": "Mis estrategias",
        "section_lead": (
            "Agrupa las versiones de una misma estrategia o robot. Cada estrategia muestra sus "
            "informes en orden y, junto a cada versión, qué cambió frente a la anterior."
        ),
        "none": "Aún no tienes estrategias. Crea una y guarda en ella tus informes.",
        "no_reports": "Sube un archivo primero: después podrás guardarlo en una estrategia.",
        "versions": "{n} versiones",
        "version_one": "1 versión",
        "latest": "Última clase",
        "open": "Ver estrategia",
        "file_title": "Guardar un informe en una estrategia",
        "report": "Informe",
        "strategy": "Estrategia",
        "new_strategy": "Nueva estrategia…",
        "new_name": "Nombre de la nueva estrategia",
        "new_name_help": "Por ejemplo: EA Oro, versión con stop más corto.",
        "file_button": "Guardar en la estrategia",
        "filed": "Informe guardado en la estrategia.",
        "file_bad": "Elige un informe de tu lista y una estrategia, o escribe un nombre.",
        "strategy_full": "Llegaste al máximo de estrategias de una cuenta.",
        "page_lead": (
            "Las versiones de esta estrategia en orden, con lo que midió cada informe. Una "
            "diferencia dice qué pruebas cambiaron, no cómo le irá a la estrategia."
        ),
        "col_version": "Versión",
        "col_date": "Fecha",
        "col_class": "Clase",
        "col_sharpe": "Sharpe anualizado",
        "col_dsr": "Sharpe deflactado",
        "col_dd": "Caída máxima",
        "locked": "Vista previa",
        "unlock": "Desbloquear para ver cifras",
        "changed_title": "Qué cambió frente a la versión {n}",
        "changed_locked": (
            "Clase {a} → {b}. Para ver qué cambió en cada prueba, las dos versiones tienen que "
            "ser informes completos."
        ),
        "class_line": "Clase: {a} → {b}",
        "sharpe_line": "Sharpe: {a} → {b}",
        "better": "mejor",
        "worse": "peor",
        "same": "igual",
        "unclear": "sin cambio claro",
        "different_frequency": "no comparable (distinta frecuencia de datos)",
        "different_periods": "periodos distintos (las fechas casi no coinciden)",
        "changed": "cambió",
        "tries_note": (
            "{n} versiones probadas: si eliges la mejor, cuenta como {n} intentos al declarar "
            "los intentos."
        ),
        "no_change": "Ninguna prueba cambió de resultado.",
        "side_by_side": "Comparar lado a lado",
        "remove": "Quitar de la estrategia",
        "rename": "Cambiar nombre",
        "rename_button": "Guardar nombre",
        "name_label": "Nombre",
        "delete": "Borrar estrategia",
        "delete_help": "Los informes siguen en tu lista; solo se quita la agrupación.",
        "back": "Volver a mi cuenta",
        "empty": "Esta estrategia aún no tiene informes. Guárdalos desde tu cuenta.",
        "note": (
            "Cada versión se lee con sus propios archivos y declaraciones. «Mejor» o «peor» en el "
            "Sharpe solo aparece cuando las bandas del bootstrap (5 % a 95 %) no se tocan; si se "
            "tocan, la diferencia cabe en el ruido de la medición; con los mismos datos esta "
            "regla es muy prudente. Si las fechas de dos versiones casi no coinciden, la "
            "diferencia puede venir del mercado de esas fechas y no del cambio. Cada prueba se "
            "lee con las declaraciones de su propio informe (intentos, costes, fuera de "
            "muestra), por eso sus líneas dicen «cambió» y no «mejor» o «peor»."
        ),
    },
    "en": {
        "section_title": "My strategies",
        "section_lead": (
            "Group the versions of one strategy or robot. Each strategy lists its reports in "
            "order and, next to each version, what changed against the previous one."
        ),
        "none": "No strategies yet. Create one and file your reports in it.",
        "no_reports": "Upload a file first: then you can file it under a strategy.",
        "versions": "{n} versions",
        "version_one": "1 version",
        "latest": "Latest class",
        "open": "Open strategy",
        "file_title": "File a report under a strategy",
        "report": "Report",
        "strategy": "Strategy",
        "new_strategy": "New strategy…",
        "new_name": "Name of the new strategy",
        "new_name_help": "For example: Gold EA, version with a tighter stop.",
        "file_button": "File under the strategy",
        "filed": "Report filed under the strategy.",
        "file_bad": "Pick a report from your list and a strategy, or type a name.",
        "strategy_full": "You reached the most strategies an account can have.",
        "page_lead": (
            "This strategy's versions in order, with what each report measured. A difference "
            "says which tests changed, not how the strategy will do."
        ),
        "col_version": "Version",
        "col_date": "Date",
        "col_class": "Class",
        "col_sharpe": "Annualised Sharpe",
        "col_dsr": "Deflated Sharpe",
        "col_dd": "Max drawdown",
        "locked": "Preview",
        "unlock": "Unlock to see figures",
        "changed_title": "What changed against version {n}",
        "changed_locked": (
            "Class {a} → {b}. To see what changed in each test, both versions have to be full "
            "reports."
        ),
        "class_line": "Class: {a} → {b}",
        "sharpe_line": "Sharpe: {a} → {b}",
        "better": "better",
        "worse": "worse",
        "same": "same",
        "unclear": "no clear change",
        "different_frequency": "not comparable (different data frequency)",
        "different_periods": "different periods (the dates barely overlap)",
        "changed": "changed",
        "tries_note": (
            "{n} versions tried: if you pick the best, it counts as {n} trials when you "
            "declare the trials."
        ),
        "no_change": "No test changed result.",
        "side_by_side": "Compare side by side",
        "remove": "Remove from strategy",
        "rename": "Rename",
        "rename_button": "Save name",
        "name_label": "Name",
        "delete": "Delete strategy",
        "delete_help": "The reports stay on your list; only the grouping goes.",
        "back": "Back to my account",
        "empty": "This strategy has no reports yet. File them from your account.",
        "note": (
            "Each version is read from its own files and declarations. 'Better' or 'worse' on "
            "the Sharpe appears only when the bootstrap bands (5 % to 95 %) do not touch; when "
            "they touch, the difference fits inside the measurement noise; on the same dates "
            "this rule is very cautious. When two versions' dates barely overlap, the "
            "difference may come from the market on those dates rather than from the change. "
            "Each test is read with its own report's declarations (trials, costs, "
            "out-of-sample), so its lines say 'changed' rather than 'better' or 'worse'."
        ),
    },
}


def _value(block: Any) -> float | None:
    """The number of an evidence-tagged figure, or ``None`` when not measured."""
    if not isinstance(block, dict) or block.get("evidence") == "NOT_MEASURED":
        return None
    value = block.get("value")
    return float(value) if isinstance(value, int | float) else None


def _number(field: Any) -> float | None:
    """A bare number, or the value of an evidence-tagged one."""
    if isinstance(field, dict):
        return _value(field)
    return float(field) if isinstance(field, int | float) else None


def headline(result: dict[str, Any]) -> dict[str, float | None]:
    """The three figures a version row shows."""
    return {
        "sharpe": _value((result.get("performance") or {}).get("sharpe")),
        "dsr": _value((result.get("multiplicity") or {}).get("dsr_at_trials_used")),
        "max_drawdown": _value((result.get("performance") or {}).get("max_drawdown")),
    }


def _rank_word(before: int, after: int) -> str:
    return "better" if after > before else "worse" if after < before else "same"


def class_change(before: str, after: str) -> str:
    """``better``, ``worse`` or ``same`` between two classes (A is best)."""
    if before not in CLASS_ORDER or after not in CLASS_ORDER:
        return "same"
    return _rank_word(-CLASS_ORDER.index(before), -CLASS_ORDER.index(after))


#: Two versions whose shared dates cover less than this share of the shorter
#: history are not compared: the market of those dates could explain the gap.
MIN_SHARED_SPAN = 0.8
#: Without a frequency label, periods per year within this relative gap
#: count as the same frequency (they are inferred from the timestamps, so two
#: daily files of different length never match exactly).
FREQUENCY_TOLERANCE = 0.10


def _same_frequency(inputs_a: dict[str, Any], inputs_b: dict[str, Any]) -> bool:
    label_a, label_b = inputs_a.get("frequency_label"), inputs_b.get("frequency_label")
    if label_a and label_b:
        return bool(label_a == label_b)
    freq_a = _number(inputs_a.get("periods_per_year"))
    freq_b = _number(inputs_b.get("periods_per_year"))
    if not freq_a or not freq_b:
        return True
    return abs(freq_a - freq_b) <= FREQUENCY_TOLERANCE * max(freq_a, freq_b)


def _span(inputs: dict[str, Any]) -> tuple[datetime, datetime] | None:
    try:
        first = datetime.fromisoformat(str(inputs["first_timestamp"]).replace("Z", "+00:00"))
        last = datetime.fromisoformat(str(inputs["last_timestamp"]).replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return None
    return (first, last) if last > first else None


def shared_share(inputs_a: dict[str, Any], inputs_b: dict[str, Any]) -> float | None:
    """The shared dates as a share of the shorter history, or ``None`` if unknown."""
    span_a, span_b = _span(inputs_a), _span(inputs_b)
    if span_a is None or span_b is None:
        return None
    shared = (min(span_a[1], span_b[1]) - max(span_a[0], span_b[0])).total_seconds()
    shorter = min((span_a[1] - span_a[0]).total_seconds(), (span_b[1] - span_b[0]).total_seconds())
    return max(shared, 0.0) / shorter


def sharpe_change(before: dict[str, Any], after: dict[str, Any]) -> str:
    """``better``/``worse`` only when the bootstrap 5-95 % bands do not overlap,
    on the same data frequency and mostly the same dates."""
    inputs_a, inputs_b = before.get("inputs") or {}, after.get("inputs") or {}
    if not _same_frequency(inputs_a, inputs_b):
        return "different_frequency"
    share = shared_share(inputs_a, inputs_b)
    if share is not None and share < MIN_SHARED_SPAN:
        return "different_periods"
    band_a = ((before.get("bootstrap") or {}).get("sharpe_per_period")) or {}
    band_b = ((after.get("bootstrap") or {}).get("sharpe_per_period")) or {}
    low_a, high_a = _value(band_a.get("p5")), _value(band_a.get("p95"))
    low_b, high_b = _value(band_b.get("p5")), _value(band_b.get("p95"))
    if None in (low_a, high_a, low_b, high_b):
        return "unclear"
    assert low_a is not None and high_a is not None and low_b is not None and high_b is not None
    if low_b > high_a:
        return "better"
    if high_b < low_a:
        return "worse"
    return "unclear"


def what_changed(
    before: dict[str, Any], after: dict[str, Any], locale: str
) -> list[tuple[str, str]]:
    """Lines ``(what, word)`` saying what changed from ``before`` to ``after``.

    The class always; each dimension whose ranked result changed; the Sharpe
    with its noise-aware word.
    """
    locale = "en" if locale == "en" else "es"
    copy = COPY[locale]
    status_text = STATUS_TEXT[locale]
    class_a = str(before["verdict"]["overall"])
    class_b = str(after["verdict"]["overall"])
    lines = [
        (copy["class_line"].format(a=class_a, b=class_b), copy[class_change(class_a, class_b)])
    ]
    dims_a = {d["name"]: d["status"] for d in before["verdict"]["dimensions"]}
    dims_b = {d["name"]: d["status"] for d in after["verdict"]["dimensions"]}
    for name in DIMENSION_ORDER:
        status_a, status_b = dims_a.get(name), dims_b.get(name)
        if status_a in STATUS_RANK and status_b in STATUS_RANK and status_a != status_b:
            assert status_a is not None and status_b is not None
            lines.append(
                (
                    f"{_dimension_title(name, locale)}: {status_text[status_a]} → "
                    f"{status_text[status_b]}",
                    # Each report is read with its own declarations: "changed", not a verdict.
                    copy["changed"],
                )
            )
    sharpe_a, sharpe_b = headline(before)["sharpe"], headline(after)["sharpe"]
    if sharpe_a is not None and sharpe_b is not None:
        lines.append(
            (
                copy["sharpe_line"].format(a=f"{sharpe_a:.2f}", b=f"{sharpe_b:.2f}"),
                copy[sharpe_change(before, after)],
            )
        )
    return lines


def load_result(result_json: str | None) -> dict[str, Any] | None:
    if not result_json:
        return None
    try:
        data = json.loads(result_json)
    except ValueError:
        return None
    return data if isinstance(data, dict) and "verdict" in data else None


def figures_text(values: dict[str, float | None]) -> tuple[str, str, str]:
    """The three headline figures as shown in the table (``—`` when not measured)."""
    sharpe, dsr, drawdown = values["sharpe"], values["dsr"], values["max_drawdown"]
    return (
        f"{sharpe:.2f}" if sharpe is not None else "—",
        f"{dsr:.0%}" if dsr is not None else "—",
        f"{drawdown:.1%}" if drawdown is not None else "—",
    )


__all__ = [
    "CLASS_ORDER",
    "COPY",
    "class_change",
    "figures_text",
    "headline",
    "load_result",
    "sharpe_change",
    "what_changed",
]
