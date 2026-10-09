"""Two or three audits side by side: before and after a change, or robots.

The customer pastes the links of two or three of their own reports; the
server reads each audit id and owner token from the link, checks each one
like any report page does, and shows the class, the six dimensions, the key
figures and the stress tests, one column per report. Only reports that are
paid (or every report in free mode) can be compared, so nothing locked is
revealed. The page is
private (``noindex``), the links travel in a POST body, never in a URL, and
every text is fixed and passes the profit-claim guard in every language.
"""

from __future__ import annotations

import html
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlsplit

from quant_trade.audit.comparison_delta import change_summary
from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.report import (
    LABELS,
    PDF_ROWS_WARNING,
    SOURCE_NAMES,
    STATUS_TEXT,
    _dimension_title,
    _kpi_list,
    evidence_label,
)
from quant_trade.audit.theme import class_ring
from quant_trade.audit.verdict import DIMENSION_ORDER

#: An audit id as the store issues it (hex) and a token (URL-safe base64).
_ID = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
MAX_LINK_CHARS = 600
#: The most reports one comparison shows side by side (the pack of three).
MAX_COMPARED = 3
#: The column names, in order.
_REPORT_KEYS = ("report_a", "report_b", "report_c")

COPY: dict[str, dict[str, Any]] = {
    "es": {
        "eyebrow": "Comparar informes",
        "title": "Dos informes, lado a lado",
        "title_three": "Tres informes, lado a lado",
        "title_form": "Dos o tres informes, lado a lado",
        "lead": (
            "Pega los enlaces de dos o tres de tus informes (la dirección de la página del "
            "informe, con su token). Sirve para ver qué cambió entre versiones de una "
            "estrategia o entre robots. Solo se comparan informes completos."
        ),
        "link_a": "Enlace del primer informe",
        "link_b": "Enlace del segundo informe",
        "link_c": "Enlace del tercer informe (opcional)",
        "placeholder": "https://…/audits/…?token=…",
        "submit": "Comparar",
        "bad_link": "No reconocemos uno de los enlaces: copia la dirección completa del informe.",
        "not_found": "No encontramos uno de los informes, o su enlace no es el correcto.",
        "locked": (
            "Uno de los informes aún no está desbloqueado; solo se comparan informes completos."
        ),
        "same": "Pegaste el mismo informe más de una vez.",
        "class": "Clase",
        "figure": "Cifra",
        "report_a": "Informe 1",
        "report_b": "Informe 2",
        "report_c": "Informe 3",
        "dimensions": "Dimensiones",
        "figures": "Cifras clave",
        "period": "Periodo",
        "source": "Archivo",
        "open": "Abrir informe",
        "again": "Comparar otros",
        "note": (
            "Cada informe se lee con sus propios archivos y declaraciones. Una diferencia de "
            "clase dice qué pruebas cambiaron, no que una versión vaya a funcionar mejor."
        ),
        "summary_three": (
            "Con tres informes, el resumen de qué cambió aparece solo si los tres son "
            "versiones de una misma estrategia de tu cuenta (Mis estrategias)."
        ),
        "from_report": "Comparar con otro informe tuyo",
        "from_report_help": "Pega el enlace de otro informe tuyo para verlos lado a lado.",
        "shows_title": "Qué vas a ver",
        "shows": (
            ("La clase de cada informe", "A, B, C o D, una junto a la otra."),
            ("Las dimensiones que cambiaron", "Qué pruebas cambiaron de resultado."),
            ("Las cifras clave", "Cada cifra con su etiqueta de evidencia, lado a lado."),
        ),
    },
    "en": {
        "eyebrow": "Compare reports",
        "title": "Two reports, side by side",
        "title_three": "Three reports, side by side",
        "title_form": "Two or three reports, side by side",
        "lead": (
            "Paste the links of two or three of your reports (the address of the report "
            "page, with its token). It shows what changed between versions of a strategy or "
            "between robots. Only full reports can be compared."
        ),
        "link_a": "Link to the first report",
        "link_b": "Link to the second report",
        "link_c": "Link to the third report (optional)",
        "placeholder": "https://…/audits/…?token=…",
        "submit": "Compare",
        "bad_link": "One of the links is not recognised: copy the report's whole address.",
        "not_found": "One of the reports was not found, or its link is not the right one.",
        "locked": "One of the reports is not unlocked yet; only full reports can be compared.",
        "same": "The same report was pasted more than once.",
        "class": "Class",
        "figure": "Figure",
        "report_a": "Report 1",
        "report_b": "Report 2",
        "report_c": "Report 3",
        "dimensions": "Dimensions",
        "figures": "Key figures",
        "period": "Period",
        "source": "File",
        "open": "Open report",
        "again": "Compare others",
        "note": (
            "Each report is read from its own files and declarations. A class difference says "
            "which tests changed, not that one version will work better."
        ),
        "summary_three": (
            "With three reports, the summary of what changed appears only when all three "
            "are versions of one strategy on your account (My strategies)."
        ),
        "from_report": "Compare with another of your reports",
        "from_report_help": "Paste the link of another of your reports to see them side by side.",
        "shows_title": "What you will see",
        "shows": (
            ("Each report's class", "A, B, C or D, next to each other."),
            ("The dimensions that changed", "Which tests changed result from one to the other."),
            ("The key figures", "Every figure with its evidence tag, side by side."),
        ),
    },
    "pt": {
        "eyebrow": "Comparar relatórios",
        "title": "Dois relatórios, lado a lado",
        "title_three": "Três relatórios, lado a lado",
        "title_form": "Dois ou três relatórios, lado a lado",
        "lead": (
            "Cole os links de dois ou três dos seus relatórios (o endereço da página do "
            "relatório, com o seu token). Serve para ver o que mudou entre versões de uma "
            "estratégia ou entre robôs. Só se comparam relatórios completos."
        ),
        "link_a": "Link do primeiro relatório",
        "link_b": "Link do segundo relatório",
        "link_c": "Link do terceiro relatório (opcional)",
        "placeholder": "https://…/audits/…?token=…",
        "submit": "Comparar",
        "bad_link": "Não reconhecemos um dos links: copie o endereço completo do relatório.",
        "not_found": "Não encontramos um dos relatórios, ou o link não é o correto.",
        "locked": (
            "Um dos relatórios ainda não está desbloqueado; só se comparam relatórios completos."
        ),
        "same": "Você colou o mesmo relatório mais de uma vez.",
        "class": "Classe",
        "figure": "Número",
        "report_a": "Relatório 1",
        "report_b": "Relatório 2",
        "report_c": "Relatório 3",
        "dimensions": "Dimensões",
        "figures": "Números principais",
        "period": "Período",
        "source": "Arquivo",
        "open": "Abrir relatório",
        "again": "Comparar outros",
        "note": (
            "Cada relatório é lido com os seus próprios arquivos e declarações. Uma diferença "
            "de classe diz quais testes mudaram, não que uma versão vá funcionar melhor."
        ),
        "summary_three": (
            "Com três relatórios, o resumo do que mudou aparece só se os três forem "
            "versões de uma mesma estratégia da sua conta (Minhas estratégias)."
        ),
        "from_report": "Comparar com outro relatório seu",
        "from_report_help": "Cole o link de outro relatório seu para vê-los lado a lado.",
        "shows_title": "O que você vai ver",
        "shows": (
            ("A classe de cada relatório", "A, B, C ou D, uma ao lado da outra."),
            ("As dimensões que mudaram", "Quais testes mudaram de resultado."),
            ("Os números principais", "Cada número com a sua etiqueta de evidência, lado a lado."),
        ),
    },
}

#: The page's path in each language.
COMPARE_PATH: dict[str, str] = {"es": "/comparar", "en": "/compare", "pt": "/pt/comparar"}


def _locale(locale: str) -> str:
    return locale if locale in COPY else "es"


COMPARE_CSS = (
    ".cmp-form{display:grid;gap:14px;max-width:720px}"
    ".cmp-mine{margin:0 0 22px;padding:14px 18px;border:1px solid var(--border);"
    "border-radius:16px;background:#fff}"
    ".cmp-mine p{margin:0;display:flex;flex-wrap:wrap;gap:10px 14px;align-items:center}"
    ".cmp-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(0,1fr);gap:28px;"
    "align-items:start}"
    ".cmp-grid .cmp-form{background:#fff;border:1px solid var(--border);border-radius:24px;"
    "padding:clamp(22px,3vw,36px);box-shadow:0 30px 60px -40px rgba(0,0,0,.25)}"
    ".cmp-aside h2{font-size:.72rem;font-family:var(--mono);text-transform:uppercase;"
    "letter-spacing:.16em;color:var(--text-3);font-weight:500;margin:6px 0 18px}"
    ".cmp-aside ol{list-style:none;margin:0;padding:0;counter-reset:s}"
    ".cmp-aside li{counter-increment:s;display:grid;grid-template-columns:34px 1fr;gap:2px 12px;"
    "padding:16px 0;border-top:1px solid var(--border)}"
    ".cmp-aside li::before{content:counter(s,decimal-leading-zero);grid-row:span 2;"
    "font-family:var(--mono);font-size:.78rem;color:var(--text-3);padding-top:2px}"
    ".cmp-aside b{font-weight:600;letter-spacing:-.01em}"
    ".cmp-aside span{color:var(--text-2);font-size:.9rem}"
    ".cmp-aside p{font-size:.84rem;color:var(--text-3);margin:18px 0 0}"
    "@media (max-width:860px){.cmp-grid{grid-template-columns:minmax(0,1fr)}}"
    ".cmp-head{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px;"
    "margin:0 0 22px}"
    ".cmp-card{border:1px solid var(--border);border-radius:18px;padding:18px;display:flex;"
    "gap:16px;align-items:center;background:#fff}"
    ".cmp-card .k{font-size:.8rem;color:var(--text-3);text-transform:uppercase;"
    "letter-spacing:.08em}.cmp-card p{margin:4px 0 0;font-size:.86rem;color:var(--text-2)}"
    "@media (max-width:620px){.cmp-head{grid-template-columns:minmax(0,1fr)}}"
    ".cmp td.diff{font-weight:600}"
    ".cmp-summary{border:1px solid var(--border);border-radius:18px;padding:18px;"
    "background:#fff;margin:24px 0}.cmp-summary h2{margin-top:0}"
    # Three reports: three cards in a row on a wide screen, one under the other
    # below a tablet; a table too wide for a phone scrolls inside its own box.
    ".cmp-head.cmp3{grid-template-columns:repeat(3,minmax(0,1fr))}"
    "@media (max-width:860px){.cmp-head.cmp3{grid-template-columns:minmax(0,1fr)}}"
    ".cmp-scroll{overflow-x:auto}"
    # On a phone the two report columns keep their badges inside the card.
    "@media screen and (max-width:620px){.cmp th,.cmp td{padding:10px 8px}"
    ".cmp th:first-child,.cmp td:first-child{padding-left:12px;width:42%}"
    ".cmp .badge{white-space:nowrap;font-size:.62rem;padding:2px 6px;letter-spacing:0}"
    ".cmp-card{padding:14px;gap:12px}"
    ".cmp.cmp3 th,.cmp.cmp3 td{padding:10px 5px}"
    ".cmp.cmp3 th:first-child,.cmp.cmp3 td:first-child{width:28%;padding-left:10px}"
    ".cmp.cmp3 .badge{font-size:.56rem;padding:2px 4px}}"
)


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def parse_report_link(text: str) -> tuple[str, str] | None:
    """``(audit_id, token)`` from a report address, or None.

    Accepts the full URL or just its path and query, as a customer copies it
    from the address bar.
    """
    text = (text or "").strip()
    if not text or len(text) > MAX_LINK_CHARS:
        return None
    parts = urlsplit(
        text if "://" in text else "https://x" + ("" if text.startswith("/") else "/") + text
    )
    match = re.search(r"/audits/([^/?#]+)/?$", parts.path)
    tokens = parse_qs(parts.query).get("token", [])
    if not match or len(tokens) != 1:
        return None
    audit_id, token = match.group(1), tokens[0]
    if not _ID.match(audit_id) or not _TOKEN.match(token):
        return None
    return audit_id, token


def _status_cell(status: str, locale: str) -> str:
    text = STATUS_TEXT.get(locale, STATUS_TEXT["es"]).get(status, status)
    return f"<span class='badge {_e(status)}'>{_e(text)}</span>"


def _card(data: dict[str, Any], name: str, href: str, locale: str) -> str:
    copy = COPY[locale]
    inputs = _mapping(data.get("inputs"))
    first = _display_date(inputs.get("first_timestamp"))
    last = _display_date(inputs.get("last_timestamp"))
    source_format = inputs.get("source_format")
    warnings = inputs.get("parse_warnings")
    pdf = inputs.get("source_is_pdf") is True or (
        isinstance(warnings, list)
        and any(isinstance(item, str) and item.endswith(PDF_ROWS_WARNING) for item in warnings)
    )
    if pdf:
        source = "PDF"
    elif isinstance(data.get("inputs"), Mapping) and source_format in (None, "csv"):
        source = "CSV"
    else:
        source = (
            SOURCE_NAMES.get(source_format, "NOT_MEASURED")
            if isinstance(source_format, str)
            else "NOT_MEASURED"
        )
    overall = str(data["verdict"]["overall"])
    return (
        "<div class='cmp-card'>" + class_ring(overall) + f"<div><div class='k'>{_e(name)}</div>"
        f"<strong>{_e(copy['class'])} {_e(overall)}</strong>"
        f"<p>{_e(copy['period'])}: {_e(first)} → {_e(last)} · {_e(copy['source'])}: "
        f"{_e(source)}</p>"
        f"<p><a href='{_e(href)}'>{_e(copy['open'])}</a></p></div></div>"
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _display_date(value: Any) -> str:
    if not isinstance(value, str):
        return "NOT_MEASURED"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return "NOT_MEASURED"


def _display_evidence(block: Any, *, percent: bool = False) -> dict[str, Any]:
    """A numeric tile keeps its existing evidence or becomes unavailable."""
    block = _mapping(block)
    evidence, value = block.get("evidence"), block.get("value")
    unavailable = {"evidence": "NOT_MEASURED", "value": None}
    if evidence not in ("MEASURED", "DECLARED") or isinstance(value, bool):
        return unavailable
    if not isinstance(value, int | float):
        return unavailable
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return unavailable
    if not math.isfinite(number) or (percent and not math.isfinite(100 * number)):
        return unavailable
    return {"evidence": evidence, "value": number}


def _display_data(data: dict[str, Any]) -> dict[str, Any]:
    """Copy only fields needed by KPI rendering; diagnostics use the original."""
    out: dict[str, Any] = {
        "inputs": {"balance_only": _mapping(data.get("inputs")).get("balance_only") is True},
        "red_flags": [
            {"code": "HIDDEN_FLOATING_DRAWDOWN"}
            for flag in data.get("red_flags", [])
            if isinstance(flag, Mapping) and flag.get("code") == "HIDDEN_FLOATING_DRAWDOWN"
        ],
    }
    for section, fields in (
        ("performance", ("total_return", "max_drawdown", "platform_equity_drawdown", "sharpe")),
        ("trade_stats", ("profit_factor", "trade_count", "win_rate")),
        ("costs", ("break_even_bps", "reference_bps", "break_even_pips")),
    ):
        values = _mapping(data.get(section))
        out[section] = {
            field: _display_evidence(
                values.get(field),
                percent=field
                in ("total_return", "max_drawdown", "platform_equity_drawdown", "win_rate"),
            )
            for field in fields
        }
    risk = _mapping(_mapping(data.get("risk")).get("max_drawdown"))
    out["risk"] = {"max_drawdown": {"p95": _display_evidence(risk.get("p95"), percent=True)}}
    out["stress"] = {}
    for section, scenario in (("trades", "best_5_trades"), ("returns", "best_5_periods")):
        rows = _mapping(_mapping(data.get("stress")).get(section)).get("rows")
        out["stress"][section] = {
            "rows": [
                {
                    "scenario": scenario,
                    "result": _display_evidence(row.get("result"), percent=section == "returns"),
                }
                for row in (rows if isinstance(rows, list) else [])
                if isinstance(row, Mapping) and row.get("scenario") == scenario
            ]
        }
    return out


def _combined_evidence(*blocks: Any) -> str:
    tags = [_mapping(block).get("evidence") for block in blocks]
    if not tags or any(tag not in ("MEASURED", "DECLARED") for tag in tags):
        return "NOT_MEASURED"
    if any(_mapping(block).get("value") is None for block in blocks):
        return "NOT_MEASURED"
    return "DECLARED" if "DECLARED" in tags else "MEASURED"


def _breakeven_row(labels: dict[str, str]) -> str:
    """The break-even's row: one fixed name, so every report lands on it."""
    return f"{labels['kpi_breakeven']} ({labels['bps_side']})"


def _breakeven_cell(costs: Mapping[str, Any], labels: dict[str, str]) -> tuple[str, str]:
    """``(shown, evidence)`` of one report's break-even, its pips inside the cell.

    The pips depend on the pair (a JPY pip is another scale), so they belong
    to the report, not to the row's name: a name with the number in it split
    the row in one per report and marked as not measured a figure that was.
    """
    bps, pips = costs["break_even_bps"], costs["break_even_pips"]
    if bps["value"] <= 0:
        # Negative already before any extra cost: the row's 0, and why.
        return f"0 · {labels['kpi_breakeven_negative']}", _combined_evidence(bps)
    if pips["value"] is None:
        return f"{bps['value']:,.2f}", _combined_evidence(bps)
    shown = f"{bps['value']:,.2f} · {pips['value']:,.1f} pips"
    return shown, _combined_evidence(bps, pips)


def _kpi_cells(data: dict[str, Any], labels: dict[str, str]) -> dict[str, tuple[str, str]]:
    """Preserve the evidence of every numeric source used in a displayed figure.

    Every row is keyed by a fixed name, never by a number one report shows,
    so the same figure of two or three reports always shares one row.
    """
    display = _display_data(data)
    perf, stats, costs = (display[name] for name in ("performance", "trade_stats", "costs"))
    closed = display["inputs"]["balance_only"]
    sources = {
        labels[key]: _combined_evidence(block)
        for key, block in (
            ("kpi_return", perf["total_return"]),
            ("kpi_drawdown_closed" if closed else "kpi_drawdown", perf["max_drawdown"]),
            ("kpi_dd_platform", perf["platform_equity_drawdown"]),
            (
                "kpi_dd_p95_closed" if closed else "kpi_dd_p95",
                display["risk"]["max_drawdown"]["p95"],
            ),
            ("kpi_sharpe", perf["sharpe"]),
            ("kpi_pf", stats["profit_factor"]),
        )
    }
    sources[labels["kpi_trades"]] = _combined_evidence(stats["trade_count"], stats["win_rate"])
    for section, key in (("trades", "kpi_stress"), ("returns", "kpi_stress_curve")):
        rows = display["stress"][section]["rows"]
        sources[labels[key]] = _combined_evidence(rows[0]["result"]) if rows else "NOT_MEASURED"
    breakeven = labels["kpi_breakeven"] + " ("
    cells = {}
    for label, shown, _ in _kpi_list(display, labels):
        if label.startswith(breakeven):
            # The tile's name carries the pips; the row keeps a fixed one.
            label, (shown, tag) = _breakeven_row(labels), _breakeven_cell(costs, labels)
        else:
            tag = sources.get(label, "NOT_MEASURED")
        cells[label] = (shown if tag != "NOT_MEASURED" else "—", tag)
    for key in ("kpi_sharpe", "kpi_drawdown_closed" if closed else "kpi_drawdown"):
        cells.setdefault(labels[key], ("—", "NOT_MEASURED"))
    return cells


def _figure_cell(value: tuple[str, str] | None, locale: str, different: bool) -> str:
    shown, tag = value or ("—", "NOT_MEASURED")
    return (
        f"<td{' class=diff' if different else ''}><span>{_e(shown)}</span> "
        f"<span class='badge {_e(tag)}'>{_e(evidence_label(tag, locale))}</span></td>"
    )


def comparison_body(
    results: Sequence[dict[str, Any]],
    *,
    hrefs: Sequence[str],
    locale: str,
    same_system: bool = False,
) -> str:
    """The comparison's main content for two or three stored results.

    One column per report, in the order given, each opened by ``hrefs``. A
    figure is marked different (bold) when it is not the same in every report.
    The change summary stays between two reports: with two it always follows
    the cards. With three it is shown only when ``same_system`` says they are
    versions of one strategy (the caller reads the account's "Mis
    estrategias"), once per consecutive pair (1 to 2, 2 to 3); otherwise a
    fixed line says why it is left out.
    """
    if not 2 <= len(results) <= MAX_COMPARED or len(hrefs) != len(results):
        raise ValueError("a comparison takes two or three results, each with its link")
    locale = _locale(locale)
    copy = COPY[locale]
    labels = LABELS[locale]
    three = len(results) == 3
    # Two reports keep the markup they always had; three add a class for the layout.
    extra = " cmp3" if three else ""
    names = [copy[key] for key in _REPORT_KEYS[: len(results)]]
    head = (
        f"<div class='cmp-head{extra}'>"
        + "".join(
            _card(data, name, href, locale)
            for data, name, href in zip(results, names, hrefs, strict=True)
        )
        + "</div>"
    )
    dims = [{d["name"]: d["status"] for d in data["verdict"]["dimensions"]} for data in results]
    dim_rows = "".join(
        f"<tr><td>{_e(_dimension_title(name, locale))}</td>"
        + "".join(
            f"<td>{_status_cell(column.get(name, 'NOT_MEASURED'), locale)}</td>" for column in dims
        )
        + "</tr>"
        for name in DIMENSION_ORDER
    )
    kpis = [_kpi_cells(data, labels) for data in results]
    order: list[str] = []
    for column in kpis:
        order += [label for label in column if label not in order]
    figure_rows = ""
    for label in order:
        values = [column.get(label) for column in kpis]
        different = any(value != values[0] for value in values[1:])
        figure_rows += (
            f"<tr><td>{_e(label)}</td>"
            + "".join(_figure_cell(value, locale, different) for value in values)
            + "</tr>"
        )
    header = "<tr><th></th>" + "".join(f"<th>{_e(name)}</th>" for name in names) + "</tr>"
    if not three:
        summary = change_summary(results[0], results[1], locale)
    elif same_system:
        summary = change_summary(results[0], results[1], locale, numbers=(1, 2))
        summary += change_summary(results[1], results[2], locale, numbers=(2, 3))
    else:
        summary = f"<p class='muted'>{_e(copy['summary_three'])}</p>"

    def table(rows: str) -> str:
        markup = f"<table class='cmp{extra}'>{header}{rows}</table>"
        return f"<div class='cmp-scroll'>{markup}</div>" if three else markup

    return (
        head
        + summary
        + f"<h2>{_e(copy['dimensions'])}</h2>{table(dim_rows)}"
        + f"<h2>{_e(copy['figures'])}</h2>{table(figure_rows)}"
        + f"<p class='muted'>{_e(copy['note'])}</p>"
    )


def compare_form(locale: str, *, link_a: str = "", error: str = "") -> str:
    """The form with two link fields and an optional third (``link_a`` prefilled)."""
    locale = _locale(locale)
    copy = COPY[locale]
    action = COMPARE_PATH[locale]
    error_html = f"<div class='error'>{_e(error)}</div>" if error else ""
    form = (
        f"<form class='cmp-form' method='post' action='{action}'>{error_html}"
        f"<input type='hidden' name='lang' value='{locale}'>"
        f"<div class='field'><label for='link_a'>{_e(copy['link_a'])}</label>"
        f"<input id='link_a' type='url' name='link_a' required maxlength='{MAX_LINK_CHARS}' "
        f"autocomplete='off' spellcheck='false' placeholder='{_e(copy['placeholder'])}' "
        f"value='{_e(link_a)}'></div>"
        f"<div class='field'><label for='link_b'>{_e(copy['link_b'])}</label>"
        f"<input id='link_b' type='url' name='link_b' required maxlength='{MAX_LINK_CHARS}' "
        f"autocomplete='off' spellcheck='false' placeholder='{_e(copy['placeholder'])}'></div>"
        f"<div class='field'><label for='link_c'>{_e(copy['link_c'])}</label>"
        f"<input id='link_c' type='url' name='link_c' maxlength='{MAX_LINK_CHARS}' "
        f"autocomplete='off' spellcheck='false' placeholder='{_e(copy['placeholder'])}'></div>"
        f"<div><button class='btn btn-primary' type='submit'>{_e(copy['submit'])}</button></div>"
        "</form>"
    )
    shows = "".join(f"<li><b>{_e(k)}</b><span>{_e(v)}</span></li>" for k, v in copy["shows"])
    aside = (
        f"<aside class='cmp-aside'><h2>{_e(copy['shows_title'])}</h2><ol>{shows}</ol>"
        f"<p>{_e(copy['note'])}</p></aside>"
    )
    return f"<div class='cmp-grid'>{form}{aside}</div>"


def guard_page(page: str) -> str:
    """``page`` after the profit-claim guard; raises ``AuditReportError`` on a hit."""
    assert_report_clean(page, "")
    return page


__all__ = [
    "COMPARE_CSS",
    "COMPARE_PATH",
    "COPY",
    "MAX_COMPARED",
    "MAX_LINK_CHARS",
    "compare_form",
    "comparison_body",
    "guard_page",
    "parse_report_link",
]
