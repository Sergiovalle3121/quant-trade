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
import math
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from quant_trade.audit.account_pt import STRATEGIES_PT
from quant_trade.audit.portuguese import STATUS_TEXT_PT
from quant_trade.audit.report import STATUS_TEXT, evidence_label, shared_dimension_title
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
        "missing_title": "No encontramos esa estrategia",
        "missing_lead": (
            "Puede que la hayas borrado o que el enlace no sea de tu cuenta. Tus estrategias "
            "están en «Mi cuenta»."
        ),
        "pdf_button": "Descargar resumen en PDF",
        "pdf_generated": (
            "Resumen de la estrategia generado el {date} a partir de los informes guardados. "
            "Cada informe completo tiene su propio PDF con el detalle."
        ),
        "empty": "Esta estrategia aún no tiene informes. Guárdalos desde tu cuenta.",
        "note": (
            "Cada versión se lee con sus propios archivos y declaraciones. «Mejor» o «peor» en el "
            "Sharpe solo aparece cuando las bandas del bootstrap (5 % a 95 %) no se tocan; si se "
            "tocan, la diferencia cabe en el ruido de la medición; con los mismos datos esta "
            "regla es muy prudente. Si las fechas de dos versiones casi no coinciden, la "
            "diferencia puede venir del mercado de esas fechas y no del cambio. Cada prueba se "
            "lee con las declaraciones de su propio informe (intentos, costos, fuera de "
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
        "missing_title": "We could not find that strategy",
        "missing_lead": (
            "You may have deleted it, or the link is not from your account. Your strategies are "
            "under 'My account'."
        ),
        "pdf_button": "Download PDF summary",
        "pdf_generated": (
            "Strategy summary made on {date} from the saved reports. Each full report has its "
            "own PDF with the detail."
        ),
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

COPY["pt"] = STRATEGIES_PT


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _value(block: Any) -> float | None:
    """A finite measured or declared figure; never infer an absent evidence tag."""
    block = _mapping(block)
    if block.get("evidence") not in ("MEASURED", "DECLARED"):
        return None
    return _finite_number(block.get("value"))


def _number(field: Any) -> float | None:
    """A bare number, or the value of an evidence-tagged one."""
    if isinstance(field, Mapping):
        return _value(field) if field.get("evidence") == "MEASURED" else None
    return _finite_number(field)


def headline_evidence(result: dict[str, Any]) -> dict[str, tuple[float | None, str]]:
    """The displayed value and retained provenance of each version-table figure."""
    out = {}
    for name, section, field in (
        ("sharpe", "performance", "sharpe"),
        ("dsr", "multiplicity", "dsr_at_trials_used"),
        ("max_drawdown", "performance", "max_drawdown"),
    ):
        block = _mapping(_mapping(result.get(section)).get(field))
        value = _value(block)
        if value is not None and name != "sharpe" and not math.isfinite(100 * value):
            value = None
        tag = str(block["evidence"]) if value is not None else "NOT_MEASURED"
        out[name] = (value, tag)
    return out


def headline(result: dict[str, Any]) -> dict[str, float | None]:
    """The three figures a version row shows."""
    return {name: value for name, (value, _) in headline_evidence(result).items()}


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


def _same_frequency(inputs_a: Mapping[str, Any], inputs_b: Mapping[str, Any]) -> bool:
    inputs_a, inputs_b = _mapping(inputs_a), _mapping(inputs_b)
    label_a, label_b = inputs_a.get("frequency_label"), inputs_b.get("frequency_label")
    freq_a = _number(inputs_a.get("periods_per_year"))
    freq_b = _number(inputs_b.get("periods_per_year"))
    if freq_a is None or freq_b is None or freq_a <= 0 or freq_b <= 0:
        return False
    if label_a is not None and (not isinstance(label_a, str) or not label_a.strip()):
        return False
    if label_b is not None and (not isinstance(label_b, str) or not label_b.strip()):
        return False
    if label_a is not None and label_b is not None:
        return label_a == label_b
    return abs(freq_a - freq_b) <= FREQUENCY_TOLERANCE * max(freq_a, freq_b)


def _span(inputs: Mapping[str, Any]) -> tuple[datetime, datetime] | None:
    inputs = _mapping(inputs)
    try:
        first_text, last_text = inputs["first_timestamp"], inputs["last_timestamp"]
        if not isinstance(first_text, str) or not isinstance(last_text, str):
            return None
        first = datetime.fromisoformat(first_text.replace("Z", "+00:00"))
        last = datetime.fromisoformat(last_text.replace("Z", "+00:00"))
        if first.tzinfo is None or last.tzinfo is None:
            return None
        return (first, last) if last > first else None
    except (KeyError, ValueError, TypeError, OverflowError):
        return None


def shared_share(inputs_a: Mapping[str, Any], inputs_b: Mapping[str, Any]) -> float | None:
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
    inputs_a, inputs_b = _mapping(before.get("inputs")), _mapping(after.get("inputs"))
    curves = (inputs_a.get("balance_only"), inputs_b.get("balance_only"))
    if not all(isinstance(curve, bool) for curve in curves) or curves[0] != curves[1]:
        return "unclear"
    if any(
        (frequency := _number(inputs.get("periods_per_year"))) is None or frequency <= 0
        for inputs in (inputs_a, inputs_b)
    ):
        return "unclear"
    if not _same_frequency(inputs_a, inputs_b):
        return "different_frequency"
    share = shared_share(inputs_a, inputs_b)
    if share is None:
        return "unclear"
    if share < MIN_SHARED_SPAN:
        return "different_periods"
    for result in (before, after):
        metric = _mapping(_mapping(result.get("performance")).get("sharpe"))
        if metric.get("evidence") != "MEASURED" or _value(metric) is None:
            return "unclear"
    band_a = _mapping(_mapping(before.get("bootstrap")).get("sharpe_per_period"))
    band_b = _mapping(_mapping(after.get("bootstrap")).get("sharpe_per_period"))
    if any(
        _mapping(band.get(bound)).get("evidence") != "MEASURED"
        for band in (band_a, band_b)
        for bound in ("p5", "p95")
    ):
        return "unclear"
    low_a, high_a = _value(band_a.get("p5")), _value(band_a.get("p95"))
    low_b, high_b = _value(band_b.get("p5")), _value(band_b.get("p95"))
    if None in (low_a, high_a, low_b, high_b):
        return "unclear"
    assert low_a is not None and high_a is not None and low_b is not None and high_b is not None
    if low_a > high_a or low_b > high_b:
        return "unclear"
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
    locale = locale if locale in COPY else "es"
    copy = COPY[locale]
    status_text = STATUS_TEXT_PT if locale == "pt" else STATUS_TEXT[locale]
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
                    f"{shared_dimension_title(name, locale, (before, after))}: "
                    f"{status_text[status_a]} → "
                    f"{status_text[status_b]}",
                    # Each report is read with its own declarations: "changed", not a verdict.
                    copy["changed"],
                )
            )
    (sharpe_a, tag_a), (sharpe_b, tag_b) = (
        headline_evidence(before)["sharpe"],
        headline_evidence(after)["sharpe"],
    )
    if sharpe_a is not None and sharpe_b is not None:
        lines.append(
            (
                copy["sharpe_line"].format(
                    a=f"{sharpe_a:.2f} · {evidence_label(tag_a, locale)}",
                    b=f"{sharpe_b:.2f} · {evidence_label(tag_b, locale)}",
                ),
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
    sharpe, dsr, drawdown = (
        _finite_number(values.get(key)) for key in ("sharpe", "dsr", "max_drawdown")
    )
    dsr = dsr if dsr is not None and math.isfinite(100 * dsr) else None
    drawdown = drawdown if drawdown is not None and math.isfinite(100 * drawdown) else None
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
    "headline_evidence",
    "load_result",
    "sharpe_change",
    "what_changed",
]
