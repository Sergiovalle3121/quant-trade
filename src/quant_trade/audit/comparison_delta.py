"""A stored-evidence change summary; never ranks a strategy's future results."""

from __future__ import annotations

import html
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from quant_trade.audit.guides import guides_index_url
from quant_trade.audit.redflags import flag_title
from quant_trade.audit.report import LABELS, _dimension_title
from quant_trade.audit.verdict import DIMENSION_ORDER

COPY = {
    "es": {
        "title": "Qué cambió entre estos informes",
        "class": "Clasificación: {a} → {b}",
        "dimensions": "Pruebas con resultado distinto: {n}",
        "added": "Banderas que aparecen en el informe 2",
        "removed": "Banderas del informe 1 ausentes en el informe 2",
        "none": "Ninguna",
        "delta": "Diferencia medida · informe 2 menos informe 1",
        "why": "Por qué no se calculan algunas diferencias",
        "report": "Informe {n}",
        "compatible": (
            "Mismas fechas, frecuencia y tipo de curva. Las diferencias son aritméticas, "
            "sin prueba de significancia."
        ),
        "incompatible": (
            "NOT_MEASURED · sin diferencia numérica: las fechas, frecuencia o tipo de "
            "curva no coinciden o falta su evidencia."
        ),
        "context": (
            "Cada informe conserva sus propios archivos y declaraciones. Una bandera "
            "ausente puede deberse a datos faltantes; no demuestra que el riesgo "
            "desapareció. La clase y las pruebas dependen también de los intentos y "
            "costos declarados."
        ),
    },
    "en": {
        "title": "What changed between these reports",
        "class": "Classification: {a} → {b}",
        "dimensions": "Tests with a different result: {n}",
        "added": "Flags appearing in report 2",
        "removed": "Flags from report 1 absent in report 2",
        "none": "None",
        "delta": "Measured difference · report 2 minus report 1",
        "why": "Why some differences are not calculated",
        "report": "Report {n}",
        "compatible": (
            "Same dates, frequency and curve type. Differences are arithmetic, without a "
            "significance test."
        ),
        "incompatible": (
            "NOT_MEASURED · no numeric difference: dates, frequency or curve type differ, "
            "or their evidence is missing."
        ),
        "context": (
            "Each report retains its own files and declarations. An absent flag may reflect "
            "missing data; it does not show that the risk disappeared. Classification and "
            "tests also depend on declared trials and costs."
        ),
    },
    "pt": {
        "title": "O que mudou entre estes relatórios",
        "class": "Classificação: {a} → {b}",
        "dimensions": "Testes com resultado diferente: {n}",
        "added": "Alertas que aparecem no relatório 2",
        "removed": "Alertas do relatório 1 ausentes no relatório 2",
        "none": "Nenhum",
        "delta": "Diferença medida · relatório 2 menos relatório 1",
        "why": "Por que algumas diferenças não são calculadas",
        "report": "Relatório {n}",
        "compatible": (
            "Mesmas datas, frequência e tipo de curva. As diferenças são aritméticas, "
            "sem teste de significância."
        ),
        "incompatible": (
            "NOT_MEASURED · sem diferença numérica: datas, frequência ou tipo de curva "
            "diferem, ou falta sua evidência."
        ),
        "context": (
            "Cada relatório mantém seus próprios arquivos e declarações. Um alerta "
            "ausente pode refletir dados faltantes; não demonstra que o risco desapareceu. "
            "A classificação e os testes também dependem das tentativas e dos custos "
            "declarados."
        ),
    },
}


REASONS = {
    "es": {
        "context_invalid": "Falta el contexto de los datos o su formato no es válido.",
        "dates_missing": "Falta la fecha inicial o final del historial.",
        "dates_invalid": "No se puede leer la fecha inicial o final del historial.",
        "dates_timezone": "Las fechas del historial no incluyen zona horaria.",
        "dates_order": "La fecha final debe ser posterior a la inicial.",
        "dates_different": (
            "Las fechas y horas de inicio o fin de los dos historiales no coinciden."
        ),
        "frequency_missing": "La frecuencia necesita un número positivo con evidencia medida.",
        "frequency_invalid": "El valor de la frecuencia no es un número positivo y finito.",
        "frequency_different": "Las frecuencias medidas de los dos historiales no coinciden.",
        "label_missing": "Falta una etiqueta de frecuencia válida para el historial.",
        "label_different": "Las etiquetas de frecuencia de los dos historiales no coinciden.",
        "curve_invalid": (
            "Falta indicar si el historial es una curva de equity o de balance cerrado."
        ),
        "curve_different": (
            "Un historial usa equity y el otro, balance de operaciones cerradas. "
            "El balance cerrado no muestra las posiciones abiertas."
        ),
        "metric_unmeasured": "La cifra necesita evidencia medida en ambos informes.",
        "metric_invalid": "La cifra no contiene un valor numérico finito válido.",
        "difference_invalid": "La diferencia excede el rango numérico que se puede representar.",
    },
    "en": {
        "context_invalid": "The data context is missing or its format is invalid.",
        "dates_missing": "The history's start or end timestamp is missing.",
        "dates_invalid": "The history's start or end timestamp cannot be read.",
        "dates_timezone": "The history's timestamps do not include a time zone.",
        "dates_order": "The end timestamp must be later than the start timestamp.",
        "dates_different": "The start or end dates and times of the two histories do not match.",
        "frequency_missing": "Frequency needs a positive number with MEASURED evidence.",
        "frequency_invalid": "The frequency value is not a positive, finite number.",
        "frequency_different": "The measured frequencies of the two histories do not match.",
        "label_missing": "The history is missing a valid frequency label.",
        "label_different": "The frequency labels of the two histories do not match.",
        "curve_invalid": "The history must identify an equity curve or a closed-trade balance.",
        "curve_different": (
            "One history uses equity and the other uses a closed-trade balance. "
            "A closed-trade balance does not show open positions."
        ),
        "metric_unmeasured": "The figure needs MEASURED evidence in both reports.",
        "metric_invalid": "The figure does not contain a valid, finite numeric value.",
        "difference_invalid": "The difference exceeds the numeric range that can be represented.",
    },
    "pt": {
        "context_invalid": "Falta o contexto dos dados ou seu formato é inválido.",
        "dates_missing": "Falta a data inicial ou final do histórico.",
        "dates_invalid": "Não é possível ler a data inicial ou final do histórico.",
        "dates_timezone": "As datas do histórico não incluem fuso horário.",
        "dates_order": "A data final deve ser posterior à inicial.",
        "dates_different": "As datas e horas de início ou fim dos dois históricos não coincidem.",
        "frequency_missing": "A frequência exige um número positivo com evidência medida.",
        "frequency_invalid": "O valor da frequência não é um número positivo e finito.",
        "frequency_different": "As frequências medidas dos dois históricos não coincidem.",
        "label_missing": "Falta uma etiqueta de frequência válida para o histórico.",
        "label_different": "As etiquetas de frequência dos dois históricos não coincidem.",
        "curve_invalid": (
            "O histórico deve indicar uma curva de equity ou saldo de operações fechadas."
        ),
        "curve_different": (
            "Um histórico usa equity e o outro, saldo de operações fechadas. "
            "O saldo fechado não mostra as posições abertas."
        ),
        "metric_unmeasured": "O número exige evidência medida nos dois relatórios.",
        "metric_invalid": "O número não contém um valor numérico finito válido.",
        "difference_invalid": "A diferença excede o intervalo numérico que pode ser representado.",
    },
}


ACTION_COPY = {
    "es": {
        "title": "Qué revisar ahora",
        "notice": (
            "Estas indicaciones revisan evidencia. Conserva los originales y estos informes; "
            "sus resultados siguen iguales."
        ),
        "guides": "Ver guías de exportación",
    },
    "en": {
        "title": "What to check now",
        "notice": (
            "These steps review evidence. Keep the originals and these reports; "
            "their results stay unchanged."
        ),
        "guides": "See export guides",
    },
    "pt": {
        "title": "O que revisar agora",
        "notice": (
            "Estas orientações revisam evidências. Preserve os originais e estes relatórios; "
            "seus resultados continuam iguais."
        ),
        "guides": "Ver guias de exportação",
    },
}

EVIDENCE_STEPS = {
    "es": {
        "context_invalid": (
            "Abre el informe individual y revisa sus advertencias de importación "
            "junto a la exportación original."
        ),
        "dates_missing": (
            "Busca la columna de fecha en la exportación original y comprueba que el "
            "historial conserve su inicio y fin."
        ),
        "dates_invalid": (
            "Comprueba el formato y la interpretación de las fechas en el archivo original "
            "y en las advertencias de importación."
        ),
        "dates_timezone": (
            "Consulta la zona horaria usada al exportar; confirma el desfase de las horas "
            "con la documentación de la plataforma."
        ),
        "dates_order": (
            "Revisa las fechas inicial y final en la exportación original y la "
            "interpretación indicada en el informe."
        ),
        "dates_different": (
            "Comprueba los períodos de ambos archivos originales. Si son distintos, "
            "conserva ambos informes y léelos por separado."
        ),
        "frequency_missing": (
            "Revisa las fechas y la separación entre filas del historial original; "
            "la auditoría infiere la frecuencia de esos datos."
        ),
        "frequency_invalid": (
            "Verifica la continuidad temporal del archivo original y revisa las "
            "advertencias sobre fechas y filas descartadas."
        ),
        "frequency_different": (
            "Comprueba la frecuencia de observaciones de ambas exportaciones originales. "
            "Si es distinta, lee las cifras por separado."
        ),
        "label_missing": (
            "Consulta la frecuencia inferida en cada informe individual y sus advertencias; "
            "conserva la exportación original para revisarla."
        ),
        "label_different": (
            "Comprueba qué periodicidad describe cada informe con el archivo original; "
            "mantén ambas etiquetas tal como se muestran."
        ),
        "curve_invalid": (
            "Identifica en la exportación original si los valores incluyen posiciones "
            "abiertas o sólo operaciones cerradas."
        ),
        "curve_different": (
            "Revisa qué curva exporta cada archivo. Si tienes una curva de equity original "
            "del mismo historial, consérvala junto al balance cerrado."
        ),
        "metric_unmeasured": (
            "Abre la sección de la cifra en su informe individual y revisa qué evidencia "
            "falta; contrástala con el historial original."
        ),
        "metric_invalid": (
            "Comprueba unidades y formato numérico en la exportación original y revisa "
            "las advertencias del informe individual."
        ),
        "difference_invalid": (
            "Contrasta las unidades y las cifras de ambos informes con sus archivos "
            "originales; conserva la diferencia como no medida mientras se revisa."
        ),
    },
    "en": {
        "context_invalid": (
            "Open the individual report and review its import warnings alongside "
            "the original export."
        ),
        "dates_missing": (
            "Find the date column in the original export and check that the history "
            "retains its start and end."
        ),
        "dates_invalid": (
            "Check the date format and interpretation in the original file and the import warnings."
        ),
        "dates_timezone": (
            "Check the time zone used for the export; confirm the hour offset "
            "with the platform documentation."
        ),
        "dates_order": (
            "Review the start and end dates in the original export and "
            "the interpretation stated in the report."
        ),
        "dates_different": (
            "Check the periods of both original files. If they differ, "
            "keep both reports and read them separately."
        ),
        "frequency_missing": (
            "Review the dates and spacing between rows in the original history; "
            "the audit infers frequency from those data."
        ),
        "frequency_invalid": (
            "Check the original file's time continuity and review "
            "warnings about dates and discarded rows."
        ),
        "frequency_different": (
            "Check the observation frequency of both original exports. "
            "If it differs, read the figures separately."
        ),
        "label_missing": (
            "Check the inferred frequency in each individual report and its warnings; "
            "keep the original export for review."
        ),
        "label_different": (
            "Check the periodicity described by each report against the original file; "
            "keep both labels as displayed."
        ),
        "curve_invalid": (
            "Identify whether the original export's values include "
            "open positions or only closed trades."
        ),
        "curve_different": (
            "Check which curve each file exports. If you have an original equity curve "
            "from the same history, keep it alongside the closed-trade balance."
        ),
        "metric_unmeasured": (
            "Open the figure's section in its individual report and check "
            "which evidence is missing against the original history."
        ),
        "metric_invalid": (
            "Check units and numeric format in the original export and review "
            "the individual report's warnings."
        ),
        "difference_invalid": (
            "Check both reports' units and figures against their original files; "
            "keep the difference unmeasured while reviewing."
        ),
    },
    "pt": {
        "context_invalid": (
            "Abra o relatório individual e revise os avisos de importação "
            "junto à exportação original."
        ),
        "dates_missing": (
            "Localize a coluna de data na exportação original e confira se o "
            "histórico preserva seu início e fim."
        ),
        "dates_invalid": (
            "Confira o formato e a interpretação das datas no arquivo original "
            "e nos avisos de importação."
        ),
        "dates_timezone": (
            "Consulte o fuso horário usado na exportação; confirme o deslocamento "
            "das horas com a documentação da plataforma."
        ),
        "dates_order": (
            "Revise as datas inicial e final na exportação original "
            "e a interpretação indicada no relatório."
        ),
        "dates_different": (
            "Confira os períodos dos dois arquivos originais. Se forem diferentes, "
            "preserve ambos os relatórios e leia-os separadamente."
        ),
        "frequency_missing": (
            "Revise as datas e o intervalo entre linhas do histórico original; "
            "a auditoria infere a frequência desses dados."
        ),
        "frequency_invalid": (
            "Confira a continuidade temporal do arquivo original e revise "
            "os avisos sobre datas e linhas descartadas."
        ),
        "frequency_different": (
            "Confira a frequência das observações nas duas exportações originais. "
            "Se for diferente, leia os números separadamente."
        ),
        "label_missing": (
            "Consulte a frequência inferida em cada relatório individual e seus avisos; "
            "preserve a exportação original para revisão."
        ),
        "label_different": (
            "Confira a periodicidade descrita por cada relatório com o arquivo original; "
            "mantenha ambas as etiquetas como são exibidas."
        ),
        "curve_invalid": (
            "Identifique na exportação original se os valores incluem "
            "posições abertas ou apenas operações fechadas."
        ),
        "curve_different": (
            "Confira qual curva cada arquivo exporta. Se tiver uma curva de equity original "
            "do mesmo histórico, preserve-a junto ao saldo fechado."
        ),
        "metric_unmeasured": (
            "Abra a seção do número no relatório individual e revise qual evidência "
            "falta; confira com o histórico original."
        ),
        "metric_invalid": (
            "Confira as unidades e o formato numérico na exportação original "
            "e revise os avisos do relatório individual."
        ),
        "difference_invalid": (
            "Confira as unidades e os números dos dois relatórios com seus arquivos "
            "originais; mantenha a diferença não medida durante a revisão."
        ),
    },
}


@dataclass(frozen=True)
class ComparisonIssue:
    """A fixed reason code; only report indices and fixed metric names are retained."""

    code: str
    report: int | None = None
    metric: str | None = None


@dataclass(frozen=True)
class ComparabilityDiagnostic:
    issues: tuple[ComparisonIssue, ...]

    @property
    def window_comparable(self) -> bool:
        return not any(issue.metric is None for issue in self.issues)

    def metric_comparable(self, name: str) -> bool:
        return (
            name in ("sharpe", "max_drawdown")
            and self.window_comparable
            and not any(issue.metric == name for issue in self.issues)
        )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _measured(block: Any) -> float | None:
    block = _mapping(block)
    if block.get("evidence") != "MEASURED":
        return None
    value = block.get("value")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def comparability_diagnostic(a: dict[str, Any], b: dict[str, Any]) -> ComparabilityDiagnostic:
    """Diagnose strict context and metric checks without retaining free-form data."""
    reports = (a, b)
    inputs = [_mapping(report.get("inputs")) for report in reports]
    issues: list[ComparisonIssue] = []
    spans: list[tuple[datetime, datetime] | None] = []
    frequencies: list[float | None] = []
    labels: list[str | None] = []
    curves: list[bool | None] = []
    for index, values in enumerate(inputs, start=1):
        if not isinstance(reports[index - 1].get("inputs"), Mapping):
            issues.append(ComparisonIssue("context_invalid", index))
            spans.append(None)
            frequencies.append(None)
            labels.append(None)
            curves.append(None)
            continue
        span = None
        first, last = values.get("first_timestamp"), values.get("last_timestamp")
        if first is None or last is None:
            issues.append(ComparisonIssue("dates_missing", index))
        else:
            try:
                start = datetime.fromisoformat(str(first).replace("Z", "+00:00"))
                end = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                if start.tzinfo is None or end.tzinfo is None:
                    issues.append(ComparisonIssue("dates_timezone", index))
                elif start >= end:
                    issues.append(ComparisonIssue("dates_order", index))
                else:
                    span = (start, end)
            except (ValueError, TypeError):
                issues.append(ComparisonIssue("dates_invalid", index))
        spans.append(span)
        frequency = _measured(values.get("periods_per_year"))
        frequency_block = _mapping(values.get("periods_per_year"))
        if frequency_block.get("evidence") != "MEASURED":
            issues.append(ComparisonIssue("frequency_missing", index))
        elif frequency is None or frequency <= 0:
            issues.append(ComparisonIssue("frequency_invalid", index))
        frequencies.append(frequency)
        label = values.get("frequency_label")
        if not isinstance(label, str) or not label.strip():
            issues.append(ComparisonIssue("label_missing", index))
            label = None
        labels.append(label)
        curve = values.get("balance_only")
        if not isinstance(curve, bool):
            issues.append(ComparisonIssue("curve_invalid", index))
            curve = None
        curves.append(curve)
    if all(span is not None for span in spans) and spans[0] != spans[1]:
        issues.append(ComparisonIssue("dates_different"))
    freq_a, freq_b = frequencies
    if (
        freq_a is not None
        and freq_b is not None
        and freq_a > 0
        and freq_b > 0
        and not math.isclose(freq_a, freq_b, rel_tol=1e-6)
    ):
        issues.append(ComparisonIssue("frequency_different"))
    if all(label is not None for label in labels) and labels[0] != labels[1]:
        issues.append(ComparisonIssue("label_different"))
    if all(curve is not None for curve in curves) and curves[0] != curves[1]:
        issues.append(ComparisonIssue("curve_different"))
    for name in ("sharpe", "max_drawdown"):
        numbers = []
        for index, report in enumerate(reports, start=1):
            block = _mapping(_mapping(report.get("performance")).get(name))
            number = _measured(block)
            if block.get("evidence") != "MEASURED":
                issues.append(ComparisonIssue("metric_unmeasured", index, name))
            elif number is None:
                issues.append(ComparisonIssue("metric_invalid", index, name))
            numbers.append(number)
        if numbers[0] is not None and numbers[1] is not None:
            difference = numbers[1] - numbers[0]
            if not math.isfinite(difference) or (
                name == "max_drawdown" and not math.isfinite(100 * difference)
            ):
                issues.append(ComparisonIssue("difference_invalid", metric=name))
    return ComparabilityDiagnostic(tuple(issues))


def comparable_window(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Require full, equal timestamps and measured positive frequency on both sides."""
    return comparability_diagnostic(a, b).window_comparable


def _evidence_actions(diagnostic: ComparabilityDiagnostic, a: dict[str, Any], locale: str) -> str:
    steps = []
    seen = set()
    for issue in diagnostic.issues:
        key = (issue.code, issue.report, issue.metric)
        if key in seen:
            continue
        seen.add(key)
        text = EVIDENCE_STEPS[locale][issue.code]
        if issue.report is not None:
            text = f"{COPY[locale]['report'].format(n=issue.report)}: {text}"
        if issue.metric is not None:
            closed = _mapping(a.get("inputs")).get("balance_only") is True
            label = (
                "kpi_sharpe"
                if issue.metric == "sharpe"
                else "kpi_drawdown_closed"
                if closed
                else "kpi_drawdown"
            )
            text = f"{LABELS[locale][label]} · {text}"
        steps.append(f"<li>{html.escape(text, quote=True)}</li>")
    if not steps:
        return ""
    copy = ACTION_COPY[locale]
    return (
        "<section class='cmp-actions' aria-labelledby='comparison-evidence-actions'>"
        f"<h4 id='comparison-evidence-actions'>{html.escape(copy['title'])}</h4>"
        f"<p class='muted'>{html.escape(copy['notice'])}</p><ol>"
        + "".join(steps)
        + f"</ol><p><a href='{guides_index_url(locale)}'>{html.escape(copy['guides'])}</a></p>"
        + "</section>"
    )


def change_summary(a: dict[str, Any], b: dict[str, Any], locale: str) -> str:
    """Read stored results only; all text is escaped, no account/credit writes."""
    locale = locale if locale in COPY else "es"
    copy, labels = COPY[locale], LABELS[locale]
    e = lambda value: html.escape(str(value), quote=True)  # noqa: E731
    before, after = a["verdict"], b["verdict"]
    dims_a = {item["name"]: item["status"] for item in before["dimensions"]}
    dims_b = {item["name"]: item["status"] for item in after["dimensions"]}
    changed = [name for name in DIMENSION_ORDER if dims_a.get(name) != dims_b.get(name)]
    lines = [
        e(copy["class"].format(a=before["overall"], b=after["overall"])),
        e(copy["dimensions"].format(n=len(changed))),
    ]
    if changed:
        lines.append(e(" · ".join(_dimension_title(name, locale) for name in changed)))
    flag_sets = [
        {str(flag["code"]) for flag in data.get("red_flags", []) if flag.get("code")}
        for data in (a, b)
    ]
    flags = ""
    for key, codes in (
        ("added", flag_sets[1] - flag_sets[0]),
        ("removed", flag_sets[0] - flag_sets[1]),
    ):
        content = ", ".join(flag_title(code, locale) for code in sorted(codes)) or copy["none"]
        flags += f"<p><b>{e(copy[key])}</b>: {e(content)}</p>"
    diagnostic = comparability_diagnostic(a, b)
    compatible = diagnostic.window_comparable
    deltas = []
    if compatible:
        for name, label, percent in (
            ("sharpe", "kpi_sharpe", False),
            (
                "max_drawdown",
                "kpi_drawdown_closed" if a["inputs"]["balance_only"] else "kpi_drawdown",
                True,
            ),
        ):
            if not diagnostic.metric_comparable(name):
                continue
            left = _measured(_mapping(a.get("performance")).get(name))
            right = _measured(_mapping(b.get("performance")).get(name))
            if left is not None and right is not None:
                diff = right - left
                if not math.isfinite(diff) or (percent and not math.isfinite(100 * diff)):
                    continue
                shown = f"{100 * diff:+.2f} pp" if percent else f"{diff:+.3f}"
                deltas.append(f"<li>{e(labels[label])}: {e(shown)} · MEASURED</li>")
    reasons = []
    for issue in diagnostic.issues:
        text = REASONS[locale][issue.code]
        if issue.report is not None:
            text = f"{copy['report'].format(n=issue.report)}: {text}"
        if issue.metric is not None:
            closed = _mapping(a.get("inputs")).get("balance_only") is True
            label = (
                "kpi_sharpe"
                if issue.metric == "sharpe"
                else "kpi_drawdown_closed"
                if closed
                else "kpi_drawdown"
            )
            text = f"{labels[label]} · {text}"
        reasons.append(f"<li>{e(text)} · NOT_MEASURED</li>")
    return (
        "<section class='cmp-summary' aria-labelledby='comparison-changes'>"
        f"<h2 id='comparison-changes'>{e(copy['title'])}</h2>"
        + "".join(f"<p>{line} · MEASURED</p>" for line in lines)
        + flags
        + f"<h3>{e(copy['delta'])}</h3>"
        + f"<p>{e(copy['compatible' if compatible else 'incompatible'])}</p>"
        + (
            f"<h4>{e(copy['why'])}</h4><ul class='cmp-reasons'>" + "".join(reasons) + "</ul>"
            if reasons
            else ""
        )
        + _evidence_actions(diagnostic, a, locale)
        + (
            "<ul>" + "".join(deltas) + "</ul>"
            if deltas
            else "<p>NOT_MEASURED</p>"
            if compatible
            else ""
        )
        + f"<p class='muted'>{e(copy['context'])}</p></section>"
    )
