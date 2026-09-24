"""Render an ``AuditResult`` as JSON and as a self-contained HTML page.

The JSON is the record: canonical, NaN-free, hashed, and the thing a client
can hand to a third party together with the file digests to prove what was
audited. The HTML is the same numbers with labels, an evidence badge on every
value, and a fixed disclaimer. The client's free-text description never
reaches the HTML (only its length and hash do); it lives in the JSON, where
it is theirs.

Both renderings pass the profit-claim guard before they are returned. A
report that fails the guard is a bug in this module, not a report.
"""

from __future__ import annotations

import html
from typing import Any

from quant_trade.audit.guard import assert_report_clean
from quant_trade.audit.schema import AuditResult
from quant_trade.evidence.canonical_json import (
    canonical_dumps,
    pretty_dumps,
    sha256_of_text,
)

WATERMARK_TEXT = {"es": "VISTA PREVIA — SIN PAGAR", "en": "PREVIEW — UNPAID"}

DISCLAIMER = {
    "es": (
        "Esta auditoría es una herramienta de investigación estadística aplicada a datos "
        "aportados por el cliente. No es asesoría de inversión, no ejecuta operaciones, no "
        "custodia fondos ni claves, y no predice resultados futuros. Cada valor lleva su "
        "etiqueta de evidencia: MEASURED se calculó desde el archivo, DECLARED lo afirmó el "
        "cliente y no se pudo verificar, NOT_MEASURED no se pudo calcular con lo aportado."
    ),
    "en": (
        "This audit is a statistical research tool applied to client-supplied data. It is "
        "not investment advice, executes no trades, holds no funds or keys, and does not "
        "predict future results. Every value carries its evidence tag: MEASURED was computed "
        "from the file, DECLARED was asserted by the client and could not be verified, "
        "NOT_MEASURED could not be computed from what was supplied."
    ),
}

LABELS: dict[str, dict[str, str]] = {
    "es": {
        "title": "Auditoría de backtest",
        "generated": "Generada",
        "audit_id": "Identificador",
        "inputs": "Archivos auditados (sha256)",
        "verdict": "Veredicto",
        "dimensions": "Dimensiones",
        "dimension": "Dimensión",
        "status": "Estado",
        "reasons": "Razones",
        "performance": "Rendimiento anualizado",
        "significance": "Significación estadística",
        "multiplicity": "Multiplicidad (número de intentos)",
        "sensitivity": "Sensibilidad del Sharpe deflactado al número de intentos",
        "bootstrap": "Bootstrap estacionario (por período)",
        "holdout": "Fuera de muestra declarado",
        "costs": "Costes de operación",
        "benchmark": "Benchmark aportado",
        "cscv": "Sobreajuste por validación cruzada combinatoria (CSCV)",
        "subperiods": "Subperíodos (años naturales)",
        "rolling": "Ventanas móviles",
        "red_flags": "Banderas rojas",
        "not_measured": "No medido",
        "declared": "Declarado por el cliente",
        "metric": "Métrica",
        "value": "Valor",
        "evidence": "Evidencia",
        "note": "Nota",
        "none": "ninguna",
        "trials": "intentos",
        "expected_max": "Sharpe máximo esperado sin habilidad",
        "dsr": "Sharpe deflactado (DSR)",
        "multiplier": "Multiplicador",
        "bps": "pb por lado",
        "gross": "Bruto",
        "cost": "Coste",
        "net": "Neto",
        "win_rate": "Aciertos",
        "trades": "Operaciones",
        "in_sample": "En muestra",
        "out_of_sample": "Fuera de muestra",
        "year": "Año",
        "return": "Retorno",
        "max_drawdown": "Drawdown máximo",
        "window": "Ventana",
        "min_return": "Retorno mínimo",
        "min_drawdown": "Drawdown mínimo",
        "share_negative": "Fracción negativa",
        "code": "Código",
        "severity": "Severidad",
        "detail": "Detalle",
        "warnings": "Avisos de lectura",
        "client_text": "Descripción del cliente",
        "client_text_note": (
            "La descripción no se reproduce en este informe; consta en el JSON. Expresiones de "
            "promesa de resultados detectadas en ella"
        ),
        "seal": "Sello del holdout declarado",
        "pay": "Desbloquear el informe completo",
        "locked": "Sección disponible en el informe completo",
        "disclaimer": "Aviso",
        "json_sha": "sha256 del JSON de la auditoría",
        "thresholds": "Umbrales aplicados",
    },
    "en": {
        "title": "Backtest audit",
        "generated": "Generated",
        "audit_id": "Identifier",
        "inputs": "Audited files (sha256)",
        "verdict": "Verdict",
        "dimensions": "Dimensions",
        "dimension": "Dimension",
        "status": "Status",
        "reasons": "Reasons",
        "performance": "Annualised performance",
        "significance": "Statistical significance",
        "multiplicity": "Multiplicity (number of trials)",
        "sensitivity": "Deflated Sharpe sensitivity to the number of trials",
        "bootstrap": "Stationary bootstrap (per period)",
        "holdout": "Declared out-of-sample",
        "costs": "Trading costs",
        "benchmark": "Supplied benchmark",
        "cscv": "Combinatorially symmetric cross-validation (CSCV) overfitting",
        "subperiods": "Sub-periods (calendar years)",
        "rolling": "Rolling windows",
        "red_flags": "Red flags",
        "not_measured": "Not measured",
        "declared": "Declared by the client",
        "metric": "Metric",
        "value": "Value",
        "evidence": "Evidence",
        "note": "Note",
        "none": "none",
        "trials": "trials",
        "expected_max": "Expected max Sharpe without skill",
        "dsr": "Deflated Sharpe (DSR)",
        "multiplier": "Multiplier",
        "bps": "bps per side",
        "gross": "Gross",
        "cost": "Cost",
        "net": "Net",
        "win_rate": "Win rate",
        "trades": "Trades",
        "in_sample": "In sample",
        "out_of_sample": "Out of sample",
        "year": "Year",
        "return": "Return",
        "max_drawdown": "Max drawdown",
        "window": "Window",
        "min_return": "Min return",
        "min_drawdown": "Min drawdown",
        "share_negative": "Share negative",
        "code": "Code",
        "severity": "Severity",
        "detail": "Detail",
        "warnings": "Parse warnings",
        "client_text": "Client description",
        "client_text_note": (
            "The description is not reproduced here; it is in the JSON. Result-promise "
            "expressions detected in it"
        ),
        "seal": "Declared holdout seal",
        "pay": "Unlock the full report",
        "locked": "Section available in the full report",
        "disclaimer": "Notice",
        "json_sha": "sha256 of the audit JSON",
        "thresholds": "Thresholds applied",
    },
}

PERCENT_KEYS = {
    "total_return",
    "cagr",
    "volatility",
    "max_drawdown",
    "win_rate",
    "excess_return",
    "strategy_total_return",
    "benchmark_total_return",
    "tracking_error",
    "strategy_max_drawdown",
    "benchmark_max_drawdown",
    "overlap_share",
    "return",
    "min_return",
    "min_drawdown",
    "share_negative",
    "psr",
    "dsr",
    "pbo",
    "p5",
    "p50",
    "p95",
    "point_estimate",
}

_CSS = """
body{font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:auto;padding:24px;
color:#1a1a1a;background:#fff;max-width:1000px;line-height:1.45}
h1{font-size:1.6rem;margin:.2em 0}
h2{font-size:1.15rem;margin-top:1.6em;border-bottom:1px solid #ddd;padding-bottom:.2em}
table{border-collapse:collapse;width:100%;margin:.4em 0;font-size:.92rem}
th,td{border:1px solid #e3e3e3;padding:5px 8px;text-align:left;vertical-align:top}
th{background:#f5f5f5}
code{font-size:.85em;word-break:break-all}
.badge{display:inline-block;padding:1px 6px;border-radius:4px;font-size:.75rem;font-weight:600}
.MEASURED{background:#e3f2e6;color:#1b5e20}
.DECLARED{background:#fff3cd;color:#7a5200}
.NOT_MEASURED{background:#eee;color:#555}
.PASS{background:#e3f2e6;color:#1b5e20}
.WEAK{background:#fff3cd;color:#7a5200}
.FAIL{background:#fde2e1;color:#8b1a10}
.NOT_APPLICABLE{background:#eee;color:#555}
.WARN{background:#fff3cd;color:#7a5200}
.verdict{border:2px solid #333;padding:14px 18px;border-radius:8px;margin:1em 0}
.verdict .cls{font-size:2.4rem;font-weight:800;margin-right:12px}
.muted{color:#666;font-size:.9rem}
.disclaimer{background:#f7f7f7;border-left:4px solid #999;padding:10px 14px;margin:1.6em 0;
font-size:.9rem}
.watermark{position:fixed;top:40%;left:5%;right:5%;text-align:center;font-size:5rem;
font-weight:900;color:rgba(200,0,0,.12);transform:rotate(-25deg);pointer-events:none;z-index:9}
.banner{background:#fde2e1;color:#8b1a10;padding:8px 12px;border-radius:6px;margin-bottom:1em;
font-weight:600}
.locked{filter:blur(5px);user-select:none;pointer-events:none}
.paybox{border:1px dashed #8b1a10;padding:10px 14px;margin:.6em 0;border-radius:6px}
.paybox button{background:#8b1a10;color:#fff;border:0;padding:8px 14px;border-radius:5px;
font-weight:600;cursor:pointer}
"""


def to_json(result: AuditResult) -> str:
    return pretty_dumps(result.model_dump(mode="json")) + "\n"


def result_sha256(result: AuditResult) -> str:
    return sha256_of_text(canonical_dumps(result.model_dump(mode="json")))


def _e(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _fmt(value: Any, *, key: str = "") -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if key in PERCENT_KEYS:
            return f"{value:.2%}"
        if abs(value) >= 1000:
            return f"{value:,.1f}"
        return f"{value:.4f}"
    return _e(value)


def _badge(cls: str) -> str:
    return f'<span class="badge {_e(cls)}">{_e(cls)}</span>'


def _is_evidence(value: Any) -> bool:
    return isinstance(value, dict) and "evidence" in value and "value" in value


def _evidence_rows(section: dict[str, Any], labels: dict[str, str], *, skip: set[str]) -> str:
    rows = []
    for key, value in section.items():
        if key in skip or not _is_evidence(value):
            continue
        rows.append(
            f"<tr><td>{_e(key)}</td><td>{_fmt(value['value'], key=key)}</td>"
            f"<td>{_badge(value['evidence'])}</td><td class='muted'>{_e(value.get('note', ''))}"
            "</td></tr>"
        )
    if not rows:
        return f"<p class='muted'>{_e(labels['none'])}</p>"
    return (
        f"<table><tr><th>{_e(labels['metric'])}</th><th>{_e(labels['value'])}</th>"
        f"<th>{_e(labels['evidence'])}</th><th>{_e(labels['note'])}</th></tr>"
        + "".join(rows)
        + "</table>"
    )


def _status_line(section: dict[str, Any], labels: dict[str, str]) -> str:
    status = section.get("status")
    if status == "NOT_MEASURED":
        return (
            f"<p>{_badge('NOT_MEASURED')} <span class='muted'>{_e(section.get('reason', ''))}"
            "</span></p>"
        )
    return ""


def _section(title: str, body: str, *, locked: bool, labels: dict[str, str]) -> str:
    if locked:
        return (
            f"<h2>{_e(title)}</h2><p class='muted'>{_e(labels['locked'])}</p>"
            f"<div class='locked'>{body}</div>"
        )
    return f"<h2>{_e(title)}</h2>{body}"


def render_html(
    result: AuditResult,
    *,
    watermark: bool,
    free_mode: bool = True,
    price_usd: float | None = None,
    checkout_url: str | None = None,
) -> str:
    """The audit as one HTML document. Detail sections are blurred when the
    audit is unpaid in paid mode; everything is visible under a watermark in
    free mode."""
    data = result.model_dump(mode="json")
    locale = data["declared"].get("locale", "es")
    labels = LABELS.get(locale, LABELS["es"])
    locked = watermark and not free_mode
    verdict = data["verdict"]

    paybox = ""
    if locked and checkout_url:
        price = f" (USD {price_usd:,.0f})" if price_usd else ""
        paybox = (
            f"<form class='paybox' method='post' action='{_e(checkout_url)}'>"
            f"<button type='submit'>{_e(labels['pay'])}{_e(price)}</button></form>"
        )

    dims = "".join(
        f"<tr><td>{_e(d['name'])}</td><td>{_badge(d['status'])}</td>"
        f"<td>{_e('; '.join(d['reasons']))}</td></tr>"
        for d in verdict["dimensions"]
    )
    verdict_html = (
        f"<div class='verdict'><span class='cls'>{_e(verdict['overall'])}</span>"
        f"<span>{_e(verdict['summary'])}</span></div>"
        f"<table><tr><th>{_e(labels['dimension'])}</th><th>{_e(labels['status'])}</th>"
        f"<th>{_e(labels['reasons'])}</th></tr>{dims}</table>"
        f"<p class='muted'>{_e(labels['thresholds'])}: "
        + _e(", ".join(f"{k}={v}" for k, v in verdict["thresholds"].items()))
        + "</p>"
    )

    inputs_html = (
        "<table>"
        + "".join(
            f"<tr><td>{_e(name)}</td><td><code>{_e(digest)}</code></td></tr>"
            for name, digest in data["inputs"]["digests"].items()
        )
        + (
            f"<tr><td>dataset_digest</td><td><code>{_e(data['inputs']['dataset_digest'])}</code>"
            "</td></tr></table>"
        )
    )
    inputs_html += (
        f"<p class='muted'>{_e(data['inputs']['first_timestamp'])} → "
        f"{_e(data['inputs']['last_timestamp'])}, {_e(data['inputs']['frequency_label'])}, "
        f"{_fmt(data['inputs']['observations']['value'])} obs, "
        f"source={_e(data['inputs']['source'])}</p>"
    )
    if data["inputs"]["parse_warnings"]:
        inputs_html += (
            f"<p class='muted'>{_e(labels['warnings'])}: "
            + _e("; ".join(data["inputs"]["parse_warnings"]))
            + "</p>"
        )

    declared_html = _evidence_rows(data["declared"], labels, skip=set())
    description = data["declared"].get("description", "")
    findings = data.get("client_text_findings", [])
    declared_html += (
        f"<p class='muted'>{_e(labels['client_text'])}: {len(description)} chars, sha256 "
        f"<code>{_e(sha256_of_text(description))}</code>. {_e(labels['client_text_note'])}: "
        f"{len(findings)}.</p>"
    )

    sens = data["multiplicity"].get("sensitivity", [])
    sens_html = ""
    if sens:
        sens_html = (
            f"<table><tr><th>{_e(labels['trials'])}</th><th>{_e(labels['expected_max'])}</th>"
            f"<th>{_e(labels['dsr'])}</th></tr>"
            + "".join(
                f"<tr><td>{_fmt(row['n_trials'])}</td>"
                f"<td>{_fmt(row['expected_max_sharpe_per_period']['value'])}</td>"
                f"<td>{_fmt(row['dsr']['value'], key='dsr')}</td></tr>"
                for row in sens
            )
            + "</table>"
        )
    multiplicity_html = (
        _status_line(data["multiplicity"], labels)
        + _evidence_rows(data["multiplicity"], labels, skip={"sensitivity"})
        + f"<p class='muted'>variance policy: {_e(data['multiplicity']['variance_policy'])}</p>"
        + sens_html
    )

    boot = data["bootstrap"]
    boot_html = _status_line(boot, labels)
    if boot.get("status") == "MEASURED":
        boot_html += (
            f"<p class='muted'>method={_e(boot['method'])}, samples={_fmt(boot['samples'])}, "
            f"block={_fmt(boot['block_size'])}</p><table><tr><th></th><th>point</th><th>p5</th>"
            "<th>p50</th><th>p95</th></tr>"
        )
        for stat in ("sharpe_per_period", "total_return"):
            band = boot[stat]
            key = "p5" if stat == "total_return" else ""
            boot_html += (
                f"<tr><td>{_e(stat)}</td>"
                + "".join(
                    f"<td>{_fmt(band[p]['value'], key=key)} {_badge(band[p]['evidence'])}</td>"
                    for p in ("point_estimate", "p5", "p50", "p95")
                )
                + "</tr>"
            )
        boot_html += "</table>"

    hold = data["holdout"]
    hold_html = _status_line(hold, labels) + _evidence_rows(
        hold, labels, skip={"in_sample", "out_of_sample"}
    )
    if hold.get("status") == "MEASURED":
        for side in ("in_sample", "out_of_sample"):
            hold_html += f"<h3>{_e(labels[side])}</h3>" + _evidence_rows(
                hold[side], labels, skip=set()
            )

    cost = data["costs"]
    cost_html = _status_line(cost, labels) + _evidence_rows(cost, labels, skip={"rows"})
    if cost.get("rows"):
        cost_html += (
            f"<table><tr><th>{_e(labels['multiplier'])}</th><th>{_e(labels['bps'])}</th>"
            f"<th>{_e(labels['gross'])}</th><th>{_e(labels['cost'])}</th><th>{_e(labels['net'])}"
            f"</th><th>{_e(labels['win_rate'])}</th><th>{_e(labels['trades'])}</th></tr>"
            + "".join(
                f"<tr><td>{_fmt(row['multiplier'])}x</td><td>{_fmt(row['cost_bps_per_side'])}</td>"
                f"<td>{_fmt(row['gross_pnl']['value'])}</td><td>{_fmt(row['total_cost']['value'])}"
                f"</td><td>{_fmt(row['net_pnl']['value'])}</td>"
                f"<td>{_fmt(row['win_rate']['value'], key='win_rate')}</td>"
                f"<td>{_fmt(row['trades'])}</td></tr>"
                for row in cost["rows"]
            )
            + "</table>"
        )

    bench_html = _status_line(data["benchmark"], labels) + _evidence_rows(
        data["benchmark"], labels, skip=set()
    )
    cscv_html = _status_line(data["cscv"], labels) + _evidence_rows(
        data["cscv"], labels, skip=set()
    )
    if data["cscv"].get("status") == "MEASURED":
        cscv_html += (
            "<p class='muted'>"
            + _e(
                ", ".join(
                    f"{k}={data['cscv'][k]}"
                    for k in (
                        "partitions",
                        "combinations",
                        "parameter_variants",
                        "observations_used",
                    )
                )
            )
            + "</p>"
        )

    sub_html = (
        f"<table><tr><th>{_e(labels['year'])}</th><th>{_e(labels['return'])}</th>"
        f"<th>{_e(labels['max_drawdown'])}</th></tr>"
        + "".join(
            f"<tr><td>{row['year']}</td><td>{_fmt(row['return']['value'], key='return')}</td>"
            f"<td>{_fmt(row['max_drawdown']['value'], key='max_drawdown')}</td></tr>"
            for row in data["subperiods"]
        )
        + "</table>"
        if data["subperiods"]
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )
    roll_html = (
        f"<table><tr><th>{_e(labels['window'])}</th><th>{_e(labels['min_return'])}</th>"
        f"<th>{_e(labels['min_drawdown'])}</th><th>{_e(labels['share_negative'])}</th></tr>"
        + "".join(
            f"<tr><td>{row['window']}</td>"
            f"<td>{_fmt(row['min_return']['value'], key='min_return')}</td>"
            f"<td>{_fmt(row['min_drawdown']['value'], key='min_drawdown')}</td>"
            f"<td>{_fmt(row['share_negative']['value'], key='share_negative')}</td></tr>"
            for row in data["rolling"]
        )
        + "</table>"
        if data["rolling"]
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )

    flags_html = (
        f"<table><tr><th>{_e(labels['code'])}</th><th>{_e(labels['severity'])}</th>"
        f"<th>{_e(labels['detail'])}</th></tr>"
        + "".join(
            f"<tr><td>{_e(flag['code'])}</td><td>{_badge(flag['severity'])}</td>"
            f"<td>{_e(flag['detail'])}</td></tr>"
            for flag in data["red_flags"]
        )
        + "</table>"
        if data["red_flags"]
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )

    seal = data["seal"]
    seal_html = _status_line(seal, labels)
    if seal.get("holdout_seal"):
        hs = seal["holdout_seal"]
        seal_html += (
            "<table>"
            + "".join(
                f"<tr><td>{_e(k)}</td><td><code>{_e(hs[k])}</code></td></tr>"
                for k in (
                    "seal_id",
                    "selection_start",
                    "selection_end",
                    "holdout_start",
                    "holdout_end",
                    "sealed_at_utc",
                    "seal",
                )
            )
            + "</table>"
        )

    not_measured = [
        f"{name}: {section.get('reason', '')}"
        for name, section in (
            ("significance", data["significance"]),
            ("multiplicity", data["multiplicity"]),
            ("bootstrap", data["bootstrap"]),
            ("holdout", data["holdout"]),
            ("costs", data["costs"]),
            ("benchmark", data["benchmark"]),
            ("cscv", data["cscv"]),
        )
        if section.get("status") == "NOT_MEASURED"
    ]
    nm_html = (
        "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in not_measured) + "</ul>"
        if not_measured
        else f"<p class='muted'>{_e(labels['none'])}</p>"
    )

    watermark_html = ""
    if watermark:
        text = WATERMARK_TEXT.get(locale, WATERMARK_TEXT["es"])
        watermark_html = (
            f"<div class='watermark'>{_e(text)}</div><div class='banner'>{_e(text)}</div>"
        )

    body = [
        watermark_html,
        f"<h1>{_e(labels['title'])} · {_e(verdict['overall'])}</h1>",
        f"<p class='muted'>{_e(labels['audit_id'])}: <code>{_e(data['audit_id'])}</code> · "
        f"{_e(labels['generated'])}: {_e(data['generated_at_utc'])} · engine "
        f"{_e(data['engine']['name'])} {_e(data['engine']['package_version'])} · seed "
        f"{_e(data['engine']['seed'])}</p>",
        f"<h2>{_e(labels['verdict'])}</h2>{verdict_html}{paybox}",
        f"<h2>{_e(labels['inputs'])}</h2>{inputs_html}",
        f"<h2>{_e(labels['declared'])}</h2>{declared_html}",
        _section(
            labels["performance"],
            _evidence_rows(data["performance"], labels, skip=set()),
            locked=locked,
            labels=labels,
        ),
        _section(
            labels["significance"],
            _status_line(data["significance"], labels)
            + _evidence_rows(data["significance"], labels, skip=set()),
            locked=locked,
            labels=labels,
        ),
        _section(labels["multiplicity"], multiplicity_html, locked=locked, labels=labels),
        _section(labels["bootstrap"], boot_html, locked=locked, labels=labels),
        _section(labels["holdout"], hold_html, locked=locked, labels=labels),
        _section(labels["costs"], cost_html, locked=locked, labels=labels),
        _section(labels["benchmark"], bench_html, locked=locked, labels=labels),
        _section(labels["cscv"], cscv_html, locked=locked, labels=labels),
        _section(labels["subperiods"], sub_html, locked=locked, labels=labels),
        _section(labels["rolling"], roll_html, locked=locked, labels=labels),
        f"<h2>{_e(labels['red_flags'])}</h2>{flags_html}",
        f"<h2>{_e(labels['not_measured'])}</h2>{nm_html}",
        f"<h2>{_e(labels['seal'])}</h2>{seal_html}",
        f"<div class='disclaimer'><strong>{_e(labels['disclaimer'])}.</strong> "
        f"{_e(DISCLAIMER.get(locale, DISCLAIMER['es']))}</div>",
        f"<p class='muted'>{_e(labels['json_sha'])}: <code>{_e(result_sha256(result))}</code></p>",
    ]
    return (
        "<!doctype html><html lang='"
        + _e(locale)
        + "'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, "
        "initial-scale=1'><title>"
        + _e(f"{labels['title']} {verdict['overall']} · {data['audit_id'][:8]}")
        + "</title><style>"
        + _CSS
        + "</style></head><body>"
        + "".join(body)
        + "</body></html>"
    )


def guard_texts(result: AuditResult, html_text: str) -> None:
    """Run the profit-claim guard over the HTML and over the JSON with the
    client's own text withheld (it is reported, never repeated)."""
    payload = result.model_dump(mode="json")
    payload["declared"]["description"] = "<client description withheld from guard>"
    payload["client_text_findings"] = [
        {"count": len(result.client_text_findings), "note": "withheld from guard"}
    ]
    assert_report_clean(html_text, canonical_dumps(payload))


def render(
    result: AuditResult,
    *,
    watermark: bool,
    free_mode: bool = True,
    price_usd: float | None = None,
    checkout_url: str | None = None,
) -> tuple[str, str]:
    """``(html, json)`` for a result, both guarded. Raises ``AuditReportError``."""
    html_text = render_html(
        result,
        watermark=watermark,
        free_mode=free_mode,
        price_usd=price_usd,
        checkout_url=checkout_url,
    )
    guard_texts(result, html_text)
    return html_text, to_json(result)


__all__ = [
    "DISCLAIMER",
    "LABELS",
    "WATERMARK_TEXT",
    "guard_texts",
    "render",
    "render_html",
    "result_sha256",
    "to_json",
]
