"""A stored-evidence change summary; never ranks a strategy's future results."""

from __future__ import annotations

import html
import math
from datetime import datetime
from typing import Any

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


def _measured(block: Any) -> float | None:
    if not isinstance(block, dict) or block.get("evidence") != "MEASURED":
        return None
    value = block.get("value")
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def comparable_window(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Require full, equal timestamps and measured positive frequency on both sides."""
    left, right = a.get("inputs") or {}, b.get("inputs") or {}
    spans = []
    try:
        for inputs in (left, right):
            first = datetime.fromisoformat(str(inputs["first_timestamp"]).replace("Z", "+00:00"))
            last = datetime.fromisoformat(str(inputs["last_timestamp"]).replace("Z", "+00:00"))
            if first.tzinfo is None or last.tzinfo is None or first >= last:
                return False
            spans.append((first, last))
    except (KeyError, ValueError, TypeError):
        return False
    freq_a, freq_b = (
        _measured(left.get("periods_per_year")),
        _measured(right.get("periods_per_year")),
    )
    return bool(
        spans[0] == spans[1]
        and freq_a is not None
        and freq_b is not None
        and freq_a > 0
        and freq_b > 0
        and math.isclose(freq_a, freq_b, rel_tol=1e-6)
        and left.get("frequency_label") == right.get("frequency_label")
        and isinstance(left.get("balance_only"), bool)
        and left.get("balance_only") == right.get("balance_only")
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
    compatible = comparable_window(a, b)
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
            left = _measured((a.get("performance") or {}).get(name))
            right = _measured((b.get("performance") or {}).get(name))
            if left is not None and right is not None:
                diff = right - left
                if not math.isfinite(diff) or (percent and not math.isfinite(100 * diff)):
                    continue
                shown = f"{100 * diff:+.2f} pp" if percent else f"{diff:+.3f}"
                deltas.append(f"<li>{e(labels[label])}: {e(shown)} · MEASURED</li>")
    return (
        "<section class='cmp-summary' aria-labelledby='comparison-changes'>"
        f"<h2 id='comparison-changes'>{e(copy['title'])}</h2>"
        + "".join(f"<p>{line} · MEASURED</p>" for line in lines)
        + flags
        + f"<h3>{e(copy['delta'])}</h3>"
        + f"<p>{e(copy['compatible' if compatible else 'incompatible'])}</p>"
        + (
            "<ul>" + "".join(deltas) + "</ul>"
            if deltas
            else "<p>NOT_MEASURED</p>"
            if compatible
            else ""
        )
        + f"<p class='muted'>{e(copy['context'])}</p></section>"
    )
