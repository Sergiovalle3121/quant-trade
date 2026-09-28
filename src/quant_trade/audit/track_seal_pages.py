"""The continuous track record's pages, behind ``TRACK_SEAL_ENABLED``.

Account pages (open, upload, publish, unpublish, end, delete, badge code),
the public page with its badge and ``chain.json``, the synthetic examples
and the owner's ``/panel/historiales``. ``register`` receives the app's own
closures from ``web.create_app`` (sessions, the cross-site check, the
signed-in action check with its CSRF and rate limit, the panel's failure
log, the settings, the store and the audit slots); no security logic is
copied here. While the switch is off nothing is registered and every path
answers 404.

What a page shows comes from the service's views only: dates, counts,
codes and hashes. Nothing read from an uploaded file (an account number, a
name, a broker, a symbol, a ticket) reaches a page or a log. On screen this
feature is never called a seal: "sello" is the ``/v`` badge.
"""

from __future__ import annotations

import hmac
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from quant_trade.audit import account_pages, importers
from quant_trade.audit import track_seal_service as service
from quant_trade.audit.account_pages import ACCOUNT_CSS
from quant_trade.audit.compare import guard_page
from quant_trade.audit.forensics import (
    METHOD_VERSION,
    STATUS_CLEAN,
    STATUS_INFO,
    STATUS_NOT_MEASURED,
    STATUS_SIGNAL,
    ForensicResult,
    edit,
    review,
    rows,
)
from quant_trade.audit.owner import MAX_FAILED_LOGINS_PER_HOUR, PANEL_PATH
from quant_trade.audit.owner import TEXT as PANEL_COPY
from quant_trade.audit.pages import (
    BADGE_NOTICE,
    _e,
    _field,
    _home,
    _page,
    _page_hero,
    _utc_time,
    error_page,
)
from quant_trade.audit.seo import BRAND
from quant_trade.audit.settings import DEFAULT_BASE_URL
from quant_trade.audit.store_hooks import STATUS_OPEN, STATUS_WITHDRAWN
from quant_trade.audit.theme import CLASS_COLOURS, class_ring, icon
from quant_trade.audit.track_seal import RECIPE_VERSION, Refusal
from quant_trade.audit.track_seal_copy import COPY, LANGUAGES, PATHS
from quant_trade.audit.track_seal_service import (
    EligibleReport,
    EventView,
    PublicView,
    RecordView,
    SealedStretch,
    UploadView,
)

#: A constant, not a Railway variable. The private use (account pages) and
#: the public page each wait for their own go-ahead.
TRACK_SEAL_ENABLED = False
#: The public page, badge and chain: after the legal review.
TRACK_SEAL_PUBLIC_ENABLED = False
#: The public page in Portuguese: after a review in Brazil.
TRACK_SEAL_PUBLIC_PT_ENABLED = False
#: The synthetic examples alone (invented data, no account): they may go
#: live with the file-consistency page before the private use is switched on.
TRACK_SEAL_EXAMPLES_ENABLED = False

#: Real re-export pairs the continuity core was measured on
#: (docs/AUDIT_TRACK_SEAL.md, "Corpus regression"); below
#: ``MIN_REAL_PAIRS`` the public page adds the calibration caveat to events.
REAL_PAIRS_DOCUMENTED = 15
MIN_REAL_PAIRS = 5

PANEL_RECORDS_PATH = PANEL_PATH + "/historiales"
#: Ids are ``secrets.token_urlsafe`` strings; anything else is a 404.
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
#: The action segments follow the account pages: Spanish in every language.
_ACTIONS = ("abrir", "cargar", "terminar", "borrar", "publicar", "despublicar")
_FLASHES = ("opened", "uploaded", "mismatch", "ended", "deleted", "published", "unpublished")
_PUBLIC_EVENTS = ("opened", "uploaded", "mismatch", "ended", "published", "unpublished")
_MAX_FLASH_COUNT = 1_000_000

TRACK_CSS = """
.ts-card{border:1px solid var(--border);border-radius:16px;padding:18px 20px;margin:16px 0}
.ts-card h2{margin:0 0 6px;font-size:1.2rem}
.ts-facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px 18px;
margin:12px 0}
.ts-facts b{display:block;font-size:.8rem;color:var(--muted);font-weight:600}
.ts-actions{display:flex;flex-wrap:wrap;gap:10px;align-items:flex-end;margin-top:12px}
.ts-actions form{margin:0}
.ts-events li{margin:4px 0}
.ts-hash{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.8rem;overflow-wrap:anywhere}
.ts-banner{border:2px dashed var(--border);border-radius:14px;padding:12px 16px;margin:0 0 16px;
font-weight:600}
.ts-ring{display:flex;gap:18px;align-items:center;flex-wrap:wrap;margin:12px 0}
.ts-code{margin:8px 0}
.ts-check{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:.8rem}
"""

#: The owner panel is in Spanish, like ``owner.TEXT``.
PANEL_TEXT: dict[str, str] = {
    "title": "Historiales continuos",
    "lead": (
        "Cada historial abierto en el servicio, con su id público, estado, publicación, "
        "ocultación y el resultado de recalcular su cadena. Aquí solo se oculta o se vuelve a "
        "mostrar una página pública, de forma reversible, mientras se aclara una queja; "
        "terminar o borrar lo decide quien abrió el historial o una orden legal."
    ),
    "none": "Todavía no hay historiales.",
    "cols": "Id público|Abierto|Estado|Publicado|Oculto|Cadena|Cargas|",
    "hide": "Ocultar",
    "unhide": "Mostrar",
    "hidden": "Página pública ocultada.",
    "shown": "Página pública vuelta a mostrar.",
    "not_found": "No hay un historial con ese id.",
    "yes": "sí",
    "no": "no",
    "chain_ok": "bien",
    "chain_broken": "ROTA: revisar",
    "broken_warning": (
        "Al menos una cadena no se recalcula: su página pública atribuye el error a "
        + BRAND
        + " y oculta la clase hasta que se revise."
    ),
    "back": "Volver al panel",
}

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _locale(locale: str) -> str:
    return locale if locale in COPY else "es"


def path(kind: str, locale: str) -> str:
    return PATHS[_locale(locale)][kind]


def _day(stamp: str) -> str:
    return (stamp or "")[:10]


def _when(stamp: str, locale: str) -> str:
    return _utc_time(stamp, locale) if stamp else "—"


def _hidden(name: str, value: str) -> str:
    return f"<input type='hidden' name='{name}' value='{_e(value)}'>"


def _fig(value: object, evidence: str) -> str:
    """A figure with its evidence tag, as the report shows figures."""
    return (
        f"<span class='vc'>{_e(value)} <span class='badge {_e(evidence)}'>{_e(evidence)}</span>"
        "</span>"
    )


def _parse(stamp: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _status_word(copy: dict[str, str], status: str) -> str:
    return copy.get(f"status_{status}", status)


def _freshness(copy: dict[str, str], view: RecordView | PublicView, now: datetime) -> str:
    state, last = service.freshness(view, now)
    if state == service.FRESHNESS_CURRENT:
        return _e(copy["fresh_current"])
    return _e(copy["fresh_stale"].format(date=_day(last)))


def _stretch_html(copy: dict[str, str], sealed: SealedStretch | None, *, chain_ok: bool) -> str:
    """The class of the stretch after the opening, its observations, the
    time-to-know line and the whole file's class, each figure tagged."""
    if sealed is None:
        return f"<p class='muted'>{_e(copy['class_pending'].format(n=0, m=30))}</p>"
    if not chain_ok:
        return f"<div class='error' role='alert'>{_e(copy['chain_broken'])}</div>"
    if sealed.stretch_class:
        colour = CLASS_COLOURS.get(sealed.stretch_class, "#64748b")
        shown = (
            f"<span class='acct-cls' style='color:{colour}'>{_e(sealed.stretch_class)}</span> "
            f"<span class='badge MEASURED'>MEASURED</span>"
        )
    else:
        shown = _e(copy["class_pending"].format(n=sealed.observations, m=sealed.min_observations))
    if sealed.months_to_know == "0":
        ttk = _e(copy["ttk_reached"])
    elif sealed.months_to_know:
        ttk = _e(
            copy["ttk_months"].format(months=sealed.months_to_know, pace=sealed.pace_per_month)
        )
    elif sealed.months_reason == service.NO_POSITIVE_MEAN:
        ttk = _e(copy["ttk_no_mean"])
    else:
        ttk = _e(copy["ttk_too_few"])
    ttk += f" <span class='badge {_e(sealed.months_to_know_evidence)}'>"
    ttk += f"{_e(sealed.months_to_know_evidence)}</span>"
    full = (
        f"<span class='acct-cls' style='color:{CLASS_COLOURS.get(sealed.full_class, '#64748b')}'>"
        f"{_e(sealed.full_class)}</span> "
        f"<span class='badge {_e(sealed.full_class_evidence)}'>{_e(sealed.full_class_evidence)}"
        "</span>"
        if sealed.full_class
        else "—"
    )
    return (
        "<div class='ts-facts'>"
        f"<div><b>{_e(copy['class_stretch'])}</b>{shown}</div>"
        f"<div><b>{_e(copy['observations'])}</b>"
        f"{_fig(sealed.observations, sealed.observations_evidence)} / "
        f"{_fig(sealed.min_observations, sealed.min_observations_evidence)}</div>"
        f"<div><b>{_e(copy['time_to_know'])}</b>{ttk}</div>"
        f"<div><b>{_e(copy['class_full'])}</b>{full}<br><span class='muted'>"
        f"{_e(copy['class_full_note'])}</span></div></div>"
    )


def _operations_text(copy: dict[str, str], event: EventView) -> str:
    """Kinds and counts of a mismatch's operations, never the operations."""
    groups: dict[tuple[str, str], list[str]] = {}
    for operation in event.detail:
        fields = groups.setdefault((operation.kind, operation.k), [])
        for name in operation.fields:
            if name not in fields:
                fields.append(name)
    parts = []
    for (kind, k), fields in groups.items():
        count = sum(1 for op in event.detail if op.kind == kind and op.k == k)
        text = copy.get(f"op_{kind}", "{n}").format(n=count) + " · " + copy.get(f"k_{k}", k)
        if fields:
            text += f" ({copy['fields']}: {', '.join(fields)})"
        parts.append(text)
    return "; ".join(parts)


def _events_html(
    copy: dict[str, str], events: Sequence[EventView], locale: str, *, private: bool
) -> str:
    items = []
    for event in events:
        if not private and event.kind not in _PUBLIC_EVENTS:
            continue
        label = copy.get(f"event_{event.kind}", event.kind)
        line = f"{_when(event.at, locale)} · {_e(label)}"
        if event.kind == "mismatch":
            line += f" · {_fig(event.count, 'MEASURED')} {_e(copy['count_label'])}"
            sentence = copy["mismatch_line"].format(n=event.count)
            line += f"<br><span class='muted'>{_e(sentence)}"
            if private and event.detail:
                line += f" {_e(_operations_text(copy, event))}"
            line += "</span>"
        items.append(f"<li>{line}</li>")
    if not items:
        return ""
    return f"<h3>{_e(copy['events_title'])}</h3><ul class='ts-events'>{''.join(items)}</ul>"


def _uploads_table(copy: dict[str, str], uploads: Sequence[UploadView], locale: str) -> str:
    head = "".join(f"<th>{_e(col)}</th>" for col in copy["upload_cols"].split("|"))
    body = "".join(
        f"<tr><td>{upload.position}</td><td>{_when(upload.at, locale)}</td>"
        f"<td>{_when(upload.cutoff, locale)}</td>"
        f"<td>{_fig(upload.closed_count, 'MEASURED')}</td>"
        f"<td>{_fig(upload.flow_count, 'MEASURED')}</td>"
        f"<td class='ts-hash'>{_e(upload.hash)}</td></tr>"
        for upload in uploads
    )
    return (
        f"<h3>{_e(copy['uploads_title'])}</h3><div style='overflow-x:auto'>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def _badge_code(copy: dict[str, str], page_url: str, badge_url: str, locale: str) -> str:
    alt = BADGE_NOTICE[locale]
    snippets = (
        (copy["badge_html"], f"<a href='{page_url}'><img src='{badge_url}' alt='{alt}'></a>"),
        (copy["badge_bbcode"], f"[url={page_url}][img]{badge_url}[/img][/url]"),
        (copy["badge_markdown"], f"[![{alt}]({badge_url})]({page_url})"),
    )
    return (
        f"<h3>{_e(copy['badge_title'])}</h3><p class='muted'>{_e(copy['badge_lead'])}</p>"
        + "".join(
            f"<div class='ts-code'><b>{_e(label)}</b><pre><code>{_e(code)}</code></pre></div>"
            for label, code in snippets
        )
    )


# ---------------------------------------------------------------------------
# Account pages
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordPageData:
    """One record with everything its account page shows."""

    record: RecordView
    events: tuple[EventView, ...]
    uploads: tuple[UploadView, ...]
    chain_ok: bool


def _report_select(copy: dict[str, str], reports: Sequence[EligibleReport]) -> str:
    options = "".join(
        f"<option value='{_e(item.audit_id)}'>"
        + _e(
            copy["report_option"].format(
                id=item.audit_id, cls=item.overall_class or "—", date=_day(item.created_at)
            )
        )
        + "</option>"
        for item in reports
    )
    return _field(copy["report_label"], f"<select name='audit_id' required>{options}</select>")


def _record_card(
    copy: dict[str, str],
    locale: str,
    data: RecordPageData,
    *,
    csrf: str,
    now: datetime,
    eligible: Sequence[EligibleReport],
    public_on: bool,
    base_url: str,
    full: bool,
) -> str:
    record = data.record
    base = f"{path('records', locale)}/{record.id}"
    title = f"{_e(copy['title'])} · {_e(_status_word(copy, record.status))}"
    heading = title if full else f"<a href='{base}'>{title}</a>"
    facts = (
        "<div class='ts-facts'>"
        f"<div><b>{_e(copy['opened_on'])}</b>{_when(record.opened_at, locale)}</div>"
        f"<div><b>{_e(copy['uploads'])}</b>{_fig(record.upload_count, 'MEASURED')}</div>"
        f"<div><b>{_e(copy['last_upload'])}</b>{_when(record.last_upload_at, locale)}<br>"
        f"{_freshness(copy, record, now)}</div>"
        f"<div><b>{_e(copy['method'])}</b>{_e(record.method_version)} · "
        f"{_e(record.recipe_version)}</div>"
        f"<div><b>{_e(copy['head'])}</b><span class='ts-hash'>{_e(record.head_hash)}</span></div>"
        "</div>"
    )
    if record.ended_at:
        frozen = copy["ended_frozen"].format(date=_day(record.ended_at))
        facts += f"<p class='muted'>{_e(frozen)}</p>"
    chain = (
        f"<p class='muted'>{_e(copy['chain_ok'])}</p>"
        if data.chain_ok
        else f"<div class='error' role='alert'>{_e(copy['chain_broken'])}</div>"
    )
    body = facts + _stretch_html(copy, record.sealed, chain_ok=data.chain_ok) + chain
    if record.hidden_at:
        body += f"<div class='notice'>{_e(copy['hidden_note'])}</div>"
    body += _events_html(copy, data.events, locale, private=True)
    if full:
        body += _uploads_table(copy, data.uploads, locale)
    actions = []
    linked = {upload.audit_id for upload in data.uploads}
    if record.status == STATUS_OPEN:
        free = [item for item in eligible if item.audit_id not in linked]
        if free:
            actions.append(
                f"<form method='post' action='{base}/cargar'>{_hidden('csrf', csrf)}"
                f"<h3>{_e(copy['add_title'])}</h3><p class='muted'>{_e(copy['add_lead'])}</p>"
                + _report_select(copy, free)
                + f"<button class='btn btn-primary' type='submit'>{_e(copy['add_button'])}"
                "</button></form>"
            )
        else:
            actions.append(f"<p class='muted'>{_e(copy['add_none'])}</p>")
        actions.append(
            f"<form method='post' action='{base}/terminar'>{_hidden('csrf', csrf)}"
            f"<button class='btn btn-ghost' type='submit'>{_e(copy['end_button'])}</button>"
            f"<div class='help'>{_e(copy['end_help'])}</div></form>"
        )
    if record.published:
        actions.append(
            f"<form method='post' action='{base}/despublicar'>{_hidden('csrf', csrf)}"
            f"<button class='btn btn-ghost' type='submit'>{_e(copy['unpublish_button'])}"
            "</button></form>"
        )
    elif record.status != STATUS_WITHDRAWN:
        actions.append(
            f"<form method='post' action='{base}/publicar'>{_hidden('csrf', csrf)}"
            f"<h3>{_e(copy['publish_title'])}</h3><p class='muted'>{_e(copy['publish_lead'])}</p>"
            "<label><input type='checkbox' name='holder' value='on'> "
            f"{_e(copy['holder_checkbox'])}</label><br>"
            f"<button class='btn btn-dark' type='submit'>{_e(copy['publish_button'])}</button>"
            "</form>"
        )
    actions.append(
        f"<form method='post' action='{base}/borrar'>{_hidden('csrf', csrf)}"
        f"<button class='btn btn-ghost' type='submit'>{_e(copy['delete_button'])}</button></form>"
    )
    body += "<div class='ts-actions'>" + "".join(actions) + "</div>"
    if record.published:
        if public_on:
            page_path = f"{path('public', locale)}/{record.public_id}"
            page_url = base_url + page_path
            body += (
                f"<p><b>{_e(copy['published_since'])}</b> {_when(record.published_since, locale)}"
                f" · <a href='{_e(page_path)}'>{_e(copy['public_link'])}</a></p>"
                + _badge_code(copy, page_url, f"{page_url}/badge.svg?lang={locale}", locale)
            )
        else:
            body += f"<p class='muted'>{_e(copy['public_off'])}</p>"
    return f"<div class='ts-card'><h2>{heading}</h2>{body}</div>"


def _alert(copy: dict[str, str], flash: str, error: str, count: int) -> str:
    out = ""
    if flash == "mismatch":
        out += f"<div class='flash' role='status'>{_e(copy['mismatch_line'].format(n=count))}</div>"
    elif flash in _FLASHES:
        out += f"<div class='flash' role='status'>{_e(copy['done_' + flash])}</div>"
    if error and f"refusal_{error}" in copy:
        text = copy[f"refusal_{error}"].format(allowed=service.MAX_RECORDS_PER_ACCOUNT)
        out += f"<div class='error' role='alert'>{_e(text)}</div>"
    return out


def _switch(kind: str, locale: str, suffix: str = "") -> dict[str, str]:
    return {lang: path(kind, lang) + suffix for lang in LANGUAGES}


def _account_shell(locale: str, title: str, body: str, switch: dict[str, str]) -> str:
    copy = COPY[locale]
    content = (
        _page_hero(copy["eyebrow"], title, copy["lead"])
        + f"<div class='paper page-main'><div class='wrap'><style>{ACCOUNT_CSS}{TRACK_CSS}"
        "</style>" + body + "</div></div>"
    )
    return guard_page(_page(title, locale, content, alternates=switch, solid_nav=True))


def records_page(
    *,
    locale: str,
    records: Sequence[RecordPageData],
    eligible: Sequence[EligibleReport],
    quota: tuple[int, int],
    csrf: str,
    now: datetime,
    flash: str = "",
    error: str = "",
    count: int = 0,
    public_on: bool = False,
    base_url: str = "",
) -> str:
    """The account's records with every action."""
    locale = _locale(locale)
    copy = COPY[locale]
    opened, allowed = quota
    body = _alert(copy, flash, error, count)
    body += (
        f"<p><a href='{account_pages.path('account', locale)}'>{_e(copy['back_account'])}</a></p>"
    )
    body += f"<p class='muted'>{_e(copy['quota'].format(opened=opened, allowed=allowed))}</p>"
    if opened < allowed:
        form = (
            f"<div class='ts-card'><h2>{_e(copy['open_title'])}</h2>"
            f"<p class='muted'>{_e(copy['open_lead'])}</p>"
        )
        if eligible:
            form += (
                f"<form method='post' action='{path('records', locale)}/abrir'>"
                + _hidden("csrf", csrf)
                + _report_select(copy, eligible)
                + f"<button class='btn btn-primary' type='submit'>{_e(copy['open_button'])}"
                "</button></form>"
            )
        else:
            form += f"<p class='muted'>{_e(copy['open_none'])}</p>"
        body += form + f"<p class='muted'>{_e(copy['paying_note'])}</p></div>"
    if not records:
        body += f"<p class='muted'>{_e(copy['none'])}</p>"
    for data in records:
        body += _record_card(
            copy,
            locale,
            data,
            csrf=csrf,
            now=now,
            eligible=eligible,
            public_on=public_on,
            base_url=base_url,
            full=False,
        )
    return _account_shell(locale, copy["title"], body, _switch("records", locale))


def record_page(
    *,
    locale: str,
    data: RecordPageData,
    eligible: Sequence[EligibleReport],
    csrf: str,
    now: datetime,
    flash: str = "",
    error: str = "",
    count: int = 0,
    public_on: bool = False,
    base_url: str = "",
) -> str:
    """One record: everything the list shows plus its uploads table."""
    locale = _locale(locale)
    copy = COPY[locale]
    body = _alert(copy, flash, error, count)
    body += f"<p><a href='{path('records', locale)}'>{_e(copy['back_records'])}</a></p>"
    body += _record_card(
        copy,
        locale,
        data,
        csrf=csrf,
        now=now,
        eligible=eligible,
        public_on=public_on,
        base_url=base_url,
        full=True,
    )
    return _account_shell(
        locale, copy["title"], body, _switch("records", locale, f"/{data.record.id}")
    )


def delete_confirm_page(*, locale: str, seal_id: str, csrf: str) -> str:
    locale = _locale(locale)
    copy = COPY[locale]
    base = f"{path('records', locale)}/{seal_id}"
    body = (
        f"<div class='ts-card'><h2>{_e(copy['delete_confirm_title'])}</h2>"
        f"<p>{_e(copy['delete_confirm_lead'])}</p>"
        f"<form method='post' action='{base}/borrar'>{_hidden('csrf', csrf)}"
        f"{_hidden('confirm', 'yes')}<div class='inline-form'>"
        f"<button class='btn btn-dark' type='submit'>{_e(copy['delete_confirm_button'])}</button>"
        f" <a class='btn btn-ghost' href='{base}'>{_e(copy['cancel'])}</a></div></form></div>"
    )
    return _account_shell(locale, copy["title"], body, _switch("records", locale, f"/{seal_id}"))


# ---------------------------------------------------------------------------
# Public page, badge, chain
# ---------------------------------------------------------------------------


def _unpublished_periods(copy: dict[str, str], events: Sequence[EventView]) -> str:
    periods = []
    start = ""
    for event in sorted(events, key=lambda item: item.at):
        if event.kind == "unpublished" and not start:
            start = event.at
        elif event.kind == "published" and start:
            periods.append(copy["unpublished_period"].format(start=_day(start), end=_day(event.at)))
            start = ""
    if not periods:
        return ""
    return "<ul>" + "".join(f"<li>{_e(item)}</li>" for item in periods) + "</ul>"


def _public_shell(
    locale: str, title: str, body: str, alternates: dict[str, str], *, banner: str = ""
) -> str:
    copy = COPY[locale]
    head = f"<div class='ts-banner'>{_e(banner)}</div>" if banner else ""
    content = (
        _page_hero(copy["public_eyebrow"], title)
        + f"<div class='paper page-main'><div class='wrap wrap-mid'><style>{ACCOUNT_CSS}"
        f"{TRACK_CSS}</style>{head}{body}</div></div>"
    )
    return guard_page(_page(title, locale, content, alternates=alternates, solid_nav=True))


def public_page(
    view: PublicView,
    *,
    locale: str,
    now: datetime,
    alternates: dict[str, str],
    banner: str = "",
    with_badge: bool = True,
) -> str:
    """The public page, built from the public view's allow-list only."""
    locale = _locale(locale)
    copy = COPY[locale]
    title = copy["public_title"]
    if view.status == STATUS_WITHDRAWN:
        body = f"<p>{_e(copy['withdrawn'].format(date=_day(view.withdrawn_at)))}</p>"
        return _public_shell(locale, title, body, alternates, banner=banner)
    sealed = view.sealed
    stretch_class = sealed.stretch_class if sealed is not None and view.chain_ok else ""
    ring_word = stretch_class or copy["in_progress"]
    ring = class_ring(stretch_class, size="xl") if stretch_class else ""
    opened = _parse(view.opened_at)
    since = _parse(view.published_since)
    days = (since - opened).days if opened is not None and since is not None else 0
    since_text = copy["public_since"].format(date=_day(view.published_since), days=days)
    top = (
        "<div class='ts-ring'>"
        + ring
        + f"<div><div class='verdict-k'>{_e(copy['class_stretch'])}: "
        f"{_e(ring_word)}</div>"
        f"<p class='muted'>{_e(since_text)}</p></div></div>"
    )
    notice = (
        f"<div class='disclaimer'><strong>{_e(copy['public_notice_label'])}.</strong> "
        f"{_e(copy['public_notice'])}</div>"
    )
    facts = (
        "<div class='ts-facts'>"
        f"<div><b>{_e(copy['opened_on'])}</b>{_when(view.opened_at, locale)}</div>"
        f"<div><b>{_e(copy['uploads'])}</b>{_fig(view.upload_count, 'MEASURED')}</div>"
        f"<div><b>{_e(copy['last_upload'])}</b>{_when(view.last_upload_at, locale)}<br>"
        f"{_freshness(copy, view, now)}</div>"
        f"<div><b>{_e(copy['method'])}</b>{_e(view.method_version)} · {_e(view.recipe_version)}"
        "</div>"
        f"<div><b>{_e(copy['head'])}</b><span class='ts-hash'>{_e(view.head_hash)}</span></div>"
        "</div>"
    )
    if view.ended_at:
        facts += f"<p>{_e(copy['ended_frozen'].format(date=_day(view.ended_at)))}</p>"
    stretch = _stretch_html(copy, sealed, chain_ok=view.chain_ok)
    events = _events_html(copy, view.events, locale, private=False)
    if REAL_PAIRS_DOCUMENTED < MIN_REAL_PAIRS:
        events += f"<p class='muted'>{_e(copy['calibration_caveat'])}</p>"
    events += _unpublished_periods(copy, view.events)
    notes = (
        f"<p>{_e(copy['account_records'].format(n=view.account_records))} "
        f"<span class='badge MEASURED'>MEASURED</span></p>"
        f"<p class='muted'>{_e(copy['paid_note'])}</p>"
    )
    limits = (
        f"<h3>{_e(copy['limits_title'])}</h3><ul>"
        + "".join(f"<li>{_e(item)}</li>" for item in copy["limits"].split("|"))
        + "</ul>"
    )
    tail = ""
    if with_badge:
        prefix = f"{path('public', locale)}/{view.public_id}"
        tail = (
            f"<p><a href='{_e(prefix)}/chain.json'>{_e(copy['chain_link'])}</a> · "
            f"<span class='muted'>{_e(copy['chain_help'])}</span></p>"
            f"<div class='badge-preview'><img src='{_e(prefix)}/badge.svg?lang={locale}' "
            f"alt='{_e(BADGE_NOTICE[locale])}' width='480' height='72'></div>"
        )
    footer = (
        f"<p class='check-cta'>{icon('shield')}<span><a href='{_home(locale)}#subir'>"
        f"{_e(copy['other_record'])}</a></span></p>"
    )
    body = top + notice + facts + stretch + events + notes + limits + tail + footer
    return _public_shell(locale, title, body, alternates, banner=banner)


def record_badge_svg(*, overall: str, public_id: str, last_upload: str, locale: str) -> str:
    """The record's badge: the stretch's class (or "in progress"), the
    public id, the last upload and ``BADGE_NOTICE`` intact."""
    locale = _locale(locale)
    copy = COPY[locale]
    word = overall or copy["badge_in_progress"]
    colour = CLASS_COLOURS.get(overall, "#475569")
    notice = BADGE_NOTICE[locale]
    font = "Inter,Segoe UI,Roboto,Helvetica,Arial,sans-serif"
    label = f"{BRAND} · {copy['public_title']} · {word}"
    box = overall or "·"
    return (
        "<svg xmlns='http://www.w3.org/2000/svg' width='480' height='72' viewBox='0 0 480 72' "
        f"role='img' aria-label='{_e(f'{label} · {notice}')}'>"
        f"<title>{_e(f'{label} · {notice}')}</title>"
        "<rect x='.5' y='.5' width='479' height='71' rx='16' fill='#0b0b0d' stroke='#2a2a2f'/>"
        "<rect x='8' y='8' width='56' height='56' rx='12' fill='#141416' "
        f"stroke='{colour}' stroke-width='2'/>"
        f"<text x='36' y='49' font-family='{font}' font-size='34' font-weight='600' "
        f"fill='{colour}' text-anchor='middle' letter-spacing='-1'>{_e(box)}</text>"
        f"<text x='78' y='26' font-family='{font}' font-size='14' font-weight='650' "
        f"fill='#f4f4f6' letter-spacing='-.3'>{_e(label)}</text>"
        "<rect x='78' y='33' width='42' height='1.5' rx='.75' fill='#8a8a90'/>"
        f"<text x='128' y='37' font-family='{font}' font-size='10.5' fill='#a3a3aa'>"
        f"{_e(last_upload)} · ID {_e(public_id)}</text>"
        f"<text x='78' y='58' font-family='{font}' font-size='9' fill='#86868c' "
        f"textLength='390' lengthAdjust='spacingAndGlyphs'>{_e(notice)}</text>"
        "</svg>"
    )


# ---------------------------------------------------------------------------
# Examples: invented data, never anyone's record
# ---------------------------------------------------------------------------

EXAMPLE_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
_EXAMPLE_HEAD = "3f1c9a0d5b7e2c4a6f8d1b3e5a7c9e0f2b4d6a8c0e1f3a5b7d9c1e3f5a7b9d1c"
EXAMPLE_VIEW = PublicView(
    public_id="ejemplo",
    status=STATUS_OPEN,
    withdrawn_at="",
    opened_at="2026-03-02T09:14:00Z",
    source_format=importers.MT4_STATEMENT_HTML,
    method_version=METHOD_VERSION,
    recipe_version=RECIPE_VERSION,
    upload_count=4,
    head_hash=_EXAMPLE_HEAD,
    last_upload_at="2026-06-20T08:02:00Z",
    last_cutoff="2026-06-19T21:59:58Z",
    sealed=SealedStretch(
        computed_at="2026-06-20T08:02:00Z",
        start="2026-03-03T09:14:00Z",
        observations="41",
        observations_evidence="MEASURED",
        min_observations="30",
        min_observations_evidence="DECLARED",
        stretch_class="B",
        pending_reason="",
        months_to_know="7",
        months_to_know_evidence="MEASURED",
        months_reason="",
        pace_per_month="11.5",
        pace_evidence="MEASURED",
        first_observation="2026-03-04T10:20:00Z",
        last_observation="2026-06-19T21:59:58Z",
        full_class="C",
        full_class_evidence="MEASURED",
        full_class_scope="whole_file_including_uncovered_pre_opening_stretch",
    ),
    ended_at="",
    published_since="2026-03-20T10:00:00Z",
    chain_ok=True,
    account_records=2,
    events=(
        EventView(id="e1", at="2026-03-02T09:14:00Z", kind="opened", count=0, detail=()),
        EventView(id="e2", at="2026-03-20T10:00:00Z", kind="published", count=0, detail=()),
        EventView(id="e3", at="2026-04-01T08:30:00Z", kind="uploaded", count=0, detail=()),
        EventView(id="e4", at="2026-04-10T18:00:00Z", kind="unpublished", count=0, detail=()),
        EventView(id="e5", at="2026-04-25T09:00:00Z", kind="published", count=0, detail=()),
        EventView(id="e6", at="2026-05-04T07:45:00Z", kind="mismatch", count=2, detail=()),
        EventView(id="e7", at="2026-06-20T08:02:00Z", kind="uploaded", count=0, detail=()),
    ),
)


def example_page(locale: str) -> str:
    """``/historial/ejemplo``: one mismatch, a stale stretch, a class and a
    time-to-know line, all invented."""
    locale = _locale(locale)
    return public_page(
        EXAMPLE_VIEW,
        locale=locale,
        now=EXAMPLE_NOW,
        alternates=_switch("example", locale),
        banner=COPY[locale]["example_banner"],
        with_badge=False,
    )


#: An invented MT4 statement (four trades, one deposit) that lives here so
#: the coherence example never reads a fixture at runtime. Names, account
#: and broker are made up.
_ROWS = (
    (
        "3000101",
        "2025.02.03 09:15:02",
        "buy",
        "0.50",
        "eurusd",
        "1.03400",
        "1.03000",
        "1.03800",
        "2025.02.03 14:40:31",
        "1.03800",
        "-3.50",
        "-1.10",
        "200.00",
        "[tp]",
    ),
    (
        "3000102",
        "2025.02.04 10:00:00",
        "sell",
        "0.50",
        "eurusd",
        "1.03600",
        "1.04000",
        "1.03200",
        "2025.02.04 16:02:44",
        "1.03200",
        "-3.50",
        "0.00",
        "200.00",
        "[tp]",
    ),
    (
        "3000103",
        "2025.02.05 08:30:00",
        "buy",
        "0.20",
        "gbpusd",
        "1.24500",
        "1.24000",
        "1.25100",
        "2025.02.05 12:45:10",
        "1.24000",
        "-1.40",
        "0.00",
        "-100.00",
        "[sl]",
    ),
    (
        "3000104",
        "2025.02.06 11:05:00",
        "sell",
        "0.30",
        "usdjpy",
        "152.400",
        "153.000",
        "151.600",
        "2025.02.06 18:20:00",
        "151.600",
        "-2.10",
        "-0.80",
        "158.05",
        "[tp]",
    ),
)


def _trade_row(cells: tuple[str, ...]) -> str:
    (ticket, opened, side, size, symbol, px_in, sl, tp, closed, px_out, comm, swap, pnl, kind) = (
        cells
    )
    return (
        f'<tr align=right><td title="{kind}">{ticket}</td><td class=msdate nowrap>{opened}</td>'
        f"<td>{side}</td><td class=mspt>{size}</td><td>{symbol}</td><td>{px_in}</td><td>{sl}</td>"
        f"<td>{tp}</td><td class=msdate nowrap>{closed}</td><td>{px_out}</td>"
        f"<td class=mspt>{comm}</td><td class=mspt>0.00</td><td class=mspt>{swap}</td>"
        f"<td class=mspt>{pnl}</td></tr>"
    )


SYNTHETIC_STATEMENT: bytes = (
    '<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" "http://www.w3.org/TR/html4/strict.dtd">\n'
    "<html>\n  <head>\n    <title>Statement: 90000001 - Ejemplo Inventado</title>\n"
    '    <meta name="generator" content="MetaQuotes Software Corp.">\n  </head>\n'
    "<body topmargin=1 marginheight=1>\n<div align=center>\n"
    '<div style="font: 20pt Times New Roman"><b>Invented Broker Example</b></div><br>\n'
    "<table cellspacing=1 cellpadding=3 border=0>\n<tr align=left>\n"
    "    <td colspan=2><b>Account: 90000001</b></td>\n"
    "    <td colspan=5><b>Name: Ejemplo Inventado</b></td>\n"
    "    <td colspan=2><b>Currency: USD</b></td>\n    <td colspan=2><b>Leverage: 1:100</b></td>\n"
    "    <td colspan=3 align=right><b>2025 February 7, 18:30</b></td></tr>\n"
    "<tr align=left><td colspan=13><b>Closed Transactions:</b></td></tr>\n"
    '<tr align=center bgcolor="#C0C0C0">\n'
    "   <td>Ticket</td><td nowrap>Open Time</td><td>Type</td><td>Size</td><td>Item</td>\n"
    "   <td>Price</td><td>S / L</td><td>T / P</td><td nowrap>Close Time</td>\n"
    "   <td>Price</td><td>Commission</td><td>Taxes</td><td>Swap</td><td>Profit</td></tr>\n"
    '<tr align=right><td title="Deposit">3000100</td><td class=msdate nowrap>2025.02.01 08:00:00'
    "</td><td>balance</td><td colspan=10 align=left>Deposit</td><td class=mspt>5 000.00</td></tr>\n"
    + "\n".join(_trade_row(cells) for cells in _ROWS)
    + "\n<tr align=right>\n    <td colspan=10>&nbsp;</td>\n    <td class=mspt>-10.50</td>\n"
    "    <td class=mspt>0.00</td>\n    <td class=mspt>-1.90</td>\n    <td class=mspt>458.05</td>\n"
    "</tr>\n<tr align=right>\n    <td colspan=12 align=right><b>Closed P/L:</b></td>\n"
    '    <td colspan=2 align=right title="Commission + Swap + Profit + Taxes" class=mspt>'
    "<b>445.65</b></td>\n</tr>\n"
    "<tr align=left><td colspan=14><b>Open Trades:</b></td></tr>\n"
    '<tr align=center bgcolor="#C0C0C0"><td>Ticket</td><td nowrap>Open Time</td><td>Type</td>'
    "<td>Size</td><td>Item</td><td>Price</td><td>S / L</td><td>T / P</td><td>&nbsp;</td>"
    "<td>Price</td><td>Commission</td><td>Taxes</td><td>Swap</td><td>Profit</td></tr>\n"
    "<tr align=right><td colspan=13 align=center>No transactions</td></tr>\n"
    "<tr align=left><td colspan=14><b>Summary:</b></td></tr>\n"
    "<tr align=right><td colspan=2><b>Deposit/Withdrawal:</b></td><td colspan=2 class=mspt>"
    "<b>5 000.00</b></td><td colspan=4><b>Credit Facility:</b></td><td class=mspt><b>0.00</b>"
    "</td><td colspan=5>&nbsp;</td></tr>\n"
    "<tr align=right><td colspan=2><b>Closed Trade P/L:</b></td><td colspan=2 class=mspt>"
    "<b>445.65</b></td><td colspan=4><b>Floating P/L:</b></td><td class=mspt><b>0.00</b></td>"
    "<td colspan=3><b>Margin:</b></td><td colspan=2 class=mspt><b>0.00</b></td></tr>\n"
    "<tr align=right><td colspan=2><b>Balance:</b></td><td colspan=2 class=mspt><b>5 445.65</b>"
    "</td><td colspan=4><b>Equity:</b></td><td class=mspt><b>5 445.65</b></td><td colspan=3>"
    "<b>Free Margin:</b></td><td colspan=2 class=mspt><b>5 445.65</b></td></tr>\n"
    "</table>\n</div></body></html>\n"
).encode("utf-8")

_VARIANT_KEYS = ("coh_original", "coh_copied", "coh_changed", "coh_careful")


def _row_index(data: bytes, kind: str, first_cell: str) -> int:
    table = rows.load(data, importers.MT4_STATEMENT_HTML)
    for row in table.rows:
        if row.kind == kind and row.text(0) == first_cell:
            return row.index
    raise KeyError(first_cell)


def _set_label(data: bytes, label: str, column: int, text: str) -> bytes:
    return edit.set_cell(data, _row_index(data, rows.KIND_LABEL, label), column, text)


def coherence_variants() -> tuple[bytes, bytes, bytes, bytes]:
    """The invented statement and its three edits, made with the same
    helpers the forgery lab uses: a duplicated ticket an hour later, a
    changed result with the summary left alone, and a deleted trade whose
    totals are rewritten by hand (the careful edit)."""
    original = SYNTHETIC_STATEMENT
    fmt = importers.MT4_STATEMENT_HTML
    second = _row_index(original, rows.KIND_MT4_TRADE, "3000102")
    third = _row_index(original, rows.KIND_MT4_TRADE, "3000103")
    copied = edit.duplicate_row(original, second, shift=timedelta(hours=1))
    changed = edit.set_cell(original, third, 13, "100.00")
    careful = edit.delete_row(original, third)
    footer = next(row.index for row in rows.load(careful, fmt).rows if row.kind == rows.KIND_FOOTER)
    careful = edit.set_cell(careful, footer, 1, "-9.10")
    careful = edit.set_cell(careful, footer, 3, "558.05")
    careful = _set_label(careful, "Closed P/L:", 1, "547.05")
    careful = _set_label(careful, "Closed Trade P/L:", 1, "547.05")
    for column in (1, 3, 5):
        careful = _set_label(careful, "Balance:", column, "5 547.05")
    return original, copied, changed, careful


_COHERENCE_CACHE: dict[str, tuple[ForensicResult, ...]] = {}


def coherence_results() -> tuple[ForensicResult, ...]:
    """The battery on each variant, computed once (pure and deterministic)."""
    if "results" not in _COHERENCE_CACHE:
        found = []
        for data in coherence_variants():
            imported = importers.import_report(data, "statement.htm")
            found.append(
                review(
                    data,
                    source_format=importers.MT4_STATEMENT_HTML,
                    imported_warnings=imported.warnings,
                )
            )
        _COHERENCE_CACHE["results"] = tuple(found)
    return _COHERENCE_CACHE["results"]


def _status_cell(copy: dict[str, str], status: str, hits: str | None) -> str:
    if status == STATUS_CLEAN:
        return _e(copy["coh_clean"])
    if status == STATUS_INFO:
        return _e(copy["coh_info"].format(n=hits or "0"))
    if status == STATUS_SIGNAL:
        return _e(copy["coh_signal"].format(n=hits or "0"))
    return _e(copy["coh_not_measured"])


def coherence_example_page(locale: str) -> str:
    """``/coherencia/ejemplo``: a statement and the same statement with
    three edits; what is detected, what is not, and the limits."""
    locale = _locale(locale)
    copy = COPY[locale]
    results = coherence_results()
    cards = []
    for key, result in zip(_VARIANT_KEYS, results, strict=True):
        found = result.count(STATUS_INFO) + result.count(STATUS_SIGNAL)
        verdict = (
            copy["coh_found"].format(n=found) + " " + copy["coh_signal_sentence"]
            if found
            else copy["coh_none"]
        )
        cards.append(
            f"<div class='ts-card'><h2>{_e(copy[key])}</h2><p>{_e(verdict)}</p>"
            f"<p class='muted'>{_e(copy['coh_rows'].format(n=result.rows_read))} "
            "<span class='badge MEASURED'>MEASURED</span></p></div>"
        )
    head = "".join(f"<th>{_e(col)}</th>" for col in copy["coh_cols"].split("|"))
    body_rows = []
    for check in results[0].checks:
        cells = [
            _status_cell(copy, item.check(check.id).status, item.check(check.id).figure("n_hits"))
            for item in results
        ]
        if all(item.check(check.id).status == STATUS_NOT_MEASURED for item in results):
            continue
        body_rows.append(
            f"<tr><td class='ts-check'>{_e(check.id)}</td>"
            + "".join(f"<td>{cell}</td>" for cell in cells)
            + "</tr>"
        )
    details = (
        f"<details><summary>{_e(copy['coh_details'])}</summary><div style='overflow-x:auto'>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"
        f"</div><p class='muted'>{_e(copy['coh_method_version'])}: {_e(results[0].method_version)}"
        "</p></details>"
    )
    explain = (
        f"<h3>{_e(copy['coh_what_detected'])}</h3><p>{_e(copy['coh_detected_text'])}</p>"
        f"<h3>{_e(copy['coh_what_not'])}</h3><p>{_e(copy['coh_not_text'])}</p>"
        f"<h3>{_e(copy['coh_limits'])}</h3><p>{_e(copy['coh_limits_text'])} "
        f"{_e(copy['coh_uncalibrated'].format(n=0))}</p>"
        f"<p class='muted'>{_e(copy['coh_method'])}</p>"
        f"<p class='muted'>{_e(copy['coh_example_note'])}</p>"
    )
    content = (
        _page_hero(copy["public_eyebrow"], copy["coherence_title"], copy["coherence_lead"])
        + f"<div class='paper page-main'><div class='wrap wrap-mid'><style>{ACCOUNT_CSS}"
        f"{TRACK_CSS}</style><div class='ts-banner'>{_e(copy['example_banner'])}</div>"
        + "".join(cards)
        + explain
        + details
        + "</div></div>"
    )
    return guard_page(
        _page(
            copy["coherence_title"],
            locale,
            content,
            alternates=_switch("coherence", locale),
            solid_nav=True,
        )
    )


# ---------------------------------------------------------------------------
# Owner panel
# ---------------------------------------------------------------------------


def _panel_shell(body: str) -> str:
    content = (
        _page_hero(PANEL_COPY["eyebrow"], PANEL_TEXT["title"])
        + f"<div class='paper page-main'><div class='wrap'><style>{TRACK_CSS}</style>{body}"
        "</div></div>"
    )
    return guard_page(_page(PANEL_TEXT["title"], "es", content, solid_nav=True))


def panel_login_page(*, error: str = "") -> str:
    err = f"<div class='error'>{_e(PANEL_COPY[error])}</div>" if error else ""
    return _panel_shell(
        err
        + f"<p>{_e(PANEL_COPY['login_lead'])}</p>"
        + f"<form method='post' action='{PANEL_RECORDS_PATH}'>"
        + _field(
            PANEL_COPY["key"],
            "<input type='password' name='key' required autocomplete='current-password' "
            "maxlength='256'>",
        )
        + f"<button class='btn btn-dark' type='submit'>{_e(PANEL_COPY['enter'])}</button></form>"
    )


def panel_records_page(
    *, key: str, records: Sequence[tuple[RecordView, bool]], flash: str = "", error: str = ""
) -> str:
    """Every record with its chain verification; hide or show its page."""
    notice = f"<div class='flash'>{_e(PANEL_TEXT[flash])}</div>" if flash else ""
    err = f"<div class='error'>{_e(PANEL_TEXT[error])}</div>" if error else ""
    if any(not ok for _, ok in records):
        err += f"<div class='error'>{_e(PANEL_TEXT['broken_warning'])}</div>"
    head = "".join(f"<th>{_e(col)}</th>" for col in PANEL_TEXT["cols"].split("|"))
    lines = []
    for record, ok in records:
        action = ""
        if record.status != STATUS_WITHDRAWN:
            verb = "unhide" if record.hidden_at else "hide"
            action = (
                f"<form method='post' action='{PANEL_RECORDS_PATH}'>"
                f"<input type='hidden' name='key' value='{_e(key)}'>"
                f"<input type='hidden' name='action' value='{verb}'>"
                f"<input type='hidden' name='seal_id' value='{_e(record.id)}'>"
                f"<button class='btn btn-ghost' type='submit'>{_e(PANEL_TEXT[verb])}</button>"
                "</form>"
            )
        cells = (
            record.public_id,
            _day(record.opened_at),
            record.status,
            PANEL_TEXT["yes"] if record.published else PANEL_TEXT["no"],
            _day(record.hidden_at) if record.hidden_at else PANEL_TEXT["no"],
            PANEL_TEXT["chain_ok"] if ok else PANEL_TEXT["chain_broken"],
            str(record.upload_count),
        )
        tds = "".join(f"<td>{_e(cell)}</td>" for cell in cells)
        lines.append(f"<tr>{tds}<td>{action}</td></tr>")
    table = (
        f"<div style='overflow-x:auto'><table><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(lines)}</tbody></table></div>"
        if lines
        else f"<p class='muted'>{_e(PANEL_TEXT['none'])}</p>"
    )
    return _panel_shell(
        err
        + notice
        + f"<p>{_e(PANEL_TEXT['lead'])}</p>"
        + table
        + f"<p><a href='{PANEL_PATH}'>{_e(PANEL_TEXT['back'])}</a></p>"
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _register_examples(app: Any) -> None:
    """The synthetic examples, in the three languages, before any public id."""

    def _example_get(locale: str) -> Callable[..., Response]:
        def handler() -> Response:
            return HTMLResponse(example_page(locale))

        return handler

    def _coherence_get(locale: str) -> Callable[..., Response]:
        def handler() -> Response:
            return HTMLResponse(coherence_example_page(locale))

        return handler

    html_get = {"methods": ["GET"], "response_class": HTMLResponse}
    for locale in LANGUAGES:
        app.add_api_route(path("example", locale), _example_get(locale), **html_get)
        app.add_api_route(path("coherence", locale), _coherence_get(locale), **html_get)


def register(
    app: Any,
    *,
    load: Any,
    session: Any,
    cross_site: Any,
    signed_in_action: Any,
    panel_failures: Any,
    settings: Any,
    store: Any,
    slots: Any,
) -> bool:
    """Mount the pages on ``app``; returns whether anything was mounted."""
    if not (TRACK_SEAL_ENABLED or TRACK_SEAL_EXAMPLES_ENABLED):
        return False
    _register_examples(app)
    if not TRACK_SEAL_ENABLED:
        return True
    # The app's own slot wait, address reader and message table: imported
    # here, once the app module is loaded, rather than copied.
    from quant_trade.audit.web import _client_ip, _take_slot, message

    public_on = TRACK_SEAL_PUBLIC_ENABLED
    public_locales = tuple(
        lang for lang in LANGUAGES if lang != "pt" or TRACK_SEAL_PUBLIC_PT_ENABLED
    )
    html_get = {"methods": ["GET"], "response_class": HTMLResponse}

    def _now() -> datetime:
        return datetime.now(UTC)

    def _base_url() -> str:
        # Absolute links only from the configured address, never from Host.
        return "" if settings.base_url == DEFAULT_BASE_URL else str(settings.base_url)

    def _lang(path_locale: str, lang: str | None) -> str:
        return lang if lang in LANGUAGES else path_locale

    def _signin(locale: str, next_path: str) -> Response:
        from urllib.parse import quote

        target = account_pages.path("signin", locale) + "?next=" + quote(next_path, safe="")
        return RedirectResponse(target, status_code=303)

    def _not_found() -> HTTPException:
        return HTTPException(status_code=404, detail="not_found")

    def _busy(locale: str) -> Response:
        return HTMLResponse(error_page(message("busy", locale), locale=locale), status_code=503)

    def _flash_count(value: str) -> int:
        try:
            return max(0, min(int(value), _MAX_FLASH_COUNT))
        except ValueError:
            return 0

    def _data(record: RecordView) -> RecordPageData:
        ok, _ = service.verify(store, record.id)
        return RecordPageData(
            record=record,
            events=service.record_events(store, record.id),
            uploads=service.record_uploads(store, record.id),
            chain_ok=ok,
        )

    def _redirect(locale: str, seal_id: str = "", **query: str) -> Response:
        target = path("records", locale) + (f"/{seal_id}" if seal_id else "")
        if query:
            target += "?" + "&".join(f"{name}={value}" for name, value in query.items())
        return RedirectResponse(target, status_code=303)

    # -- account: list and detail -------------------------------------------
    def _records_get(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request, lang: str | None = None, done: str = "", error: str = "", n: str = ""
        ) -> Response:
            locale = _lang(path_locale, lang)
            found = session(request)
            if found is None:
                return _signin(locale, path("records", locale))
            account, csrf, _ = found
            records = [_data(record) for record in service.list_records(store, account.id)]
            return HTMLResponse(
                records_page(
                    locale=locale,
                    records=records,
                    eligible=service.eligible_reports(store, account.id),
                    quota=service.quota(store, account.id),
                    csrf=csrf,
                    now=_now(),
                    flash=done if done in _FLASHES else "",
                    error=error if f"refusal_{error}" in COPY[locale] else "",
                    count=_flash_count(n),
                    public_on=public_on,
                    base_url=_base_url(),
                )
            )

        return handler

    def _record_get(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            seal_id: str,
            lang: str | None = None,
            done: str = "",
            error: str = "",
            n: str = "",
        ) -> Response:
            locale = _lang(path_locale, lang)
            found = session(request)
            if found is None:
                return _signin(locale, f"{path('records', locale)}/{seal_id}")
            account, csrf, _ = found
            if not _ID.match(seal_id):
                raise _not_found()
            record = service.get_record(store, seal_id, account_id=account.id)
            if record is None:
                raise _not_found()
            return HTMLResponse(
                record_page(
                    locale=locale,
                    data=_data(record),
                    eligible=service.eligible_reports(store, account.id),
                    csrf=csrf,
                    now=_now(),
                    flash=done if done in _FLASHES else "",
                    error=error if f"refusal_{error}" in COPY[locale] else "",
                    count=_flash_count(n),
                    public_on=public_on,
                    base_url=_base_url(),
                )
            )

        return handler

    # -- account: actions ----------------------------------------------------
    def _open_post(path_locale: str) -> Callable[..., Any]:
        async def handler(
            request: Request,
            audit_id: Annotated[str, Form(max_length=64)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            checked = signed_in_action(request, path_locale, lang, csrf)
            if not isinstance(checked, tuple):
                return checked
            account, _, locale, _ = checked
            if not _ID.match(audit_id):
                return _redirect(locale, error="not_found")
            # Re-importing and re-auditing take a slot, like an upload.
            if not await _take_slot(slots, settings.audit_queue_seconds):
                return _busy(locale)
            try:
                outcome = await run_in_threadpool(
                    service.open_record,
                    store,
                    account_id=account.id,
                    audit_id=audit_id,
                    now=_now(),
                    bootstrap_samples=settings.bootstrap_samples,
                )
            finally:
                slots.release()
            if isinstance(outcome, Refusal):
                return _redirect(locale, error=outcome.code)
            return _redirect(locale, outcome.seal_id, done="opened")

        return handler

    def _upload_post(path_locale: str) -> Callable[..., Any]:
        async def handler(
            request: Request,
            seal_id: str,
            audit_id: Annotated[str, Form(max_length=64)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            checked = signed_in_action(request, path_locale, lang, csrf)
            if not isinstance(checked, tuple):
                return checked
            account, _, locale, _ = checked
            if not _ID.match(seal_id) or not _ID.match(audit_id):
                return _redirect(locale, error="not_found")
            if not await _take_slot(slots, settings.audit_queue_seconds):
                return _busy(locale)
            try:
                outcome = await run_in_threadpool(
                    service.add_upload,
                    store,
                    seal_id=seal_id,
                    account_id=account.id,
                    audit_id=audit_id,
                    now=_now(),
                    bootstrap_samples=settings.bootstrap_samples,
                )
            finally:
                slots.release()
            if isinstance(outcome, Refusal):
                return _redirect(locale, seal_id, error=outcome.code)
            if outcome.count:
                return _redirect(locale, seal_id, done="mismatch", n=str(outcome.count))
            return _redirect(locale, seal_id, done="uploaded")

        return handler

    def _simple_post(
        path_locale: str, act: Callable[[str, str, datetime], Refusal | None], done: str
    ) -> Callable[..., Response]:
        def handler(
            request: Request,
            seal_id: str,
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            checked = signed_in_action(request, path_locale, lang, csrf)
            if not isinstance(checked, tuple):
                return checked
            account, _, locale, _ = checked
            if not _ID.match(seal_id):
                return _redirect(locale, error="record_not_found")
            refusal = act(seal_id, account.id, _now())
            if refusal is not None:
                return _redirect(locale, seal_id, error=refusal.code)
            return _redirect(locale, seal_id, done=done)

        return handler

    def _end(seal_id: str, account_id: str, now: datetime) -> Refusal | None:
        return service.end_record(store, seal_id=seal_id, account_id=account_id, now=now)

    def _unpublish(seal_id: str, account_id: str, now: datetime) -> Refusal | None:
        return service.unpublish(store, seal_id=seal_id, account_id=account_id, now=now)

    def _publish_post(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            seal_id: str,
            holder: Annotated[str, Form(max_length=10)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            checked = signed_in_action(request, path_locale, lang, csrf)
            if not isinstance(checked, tuple):
                return checked
            account, _, locale, _ = checked
            if not _ID.match(seal_id):
                return _redirect(locale, error="record_not_found")
            outcome = service.publish(
                store,
                seal_id=seal_id,
                account_id=account.id,
                now=_now(),
                holder_confirmed=holder == "on",
            )
            if isinstance(outcome, Refusal):
                return _redirect(locale, seal_id, error=outcome.code)
            return _redirect(locale, seal_id, done="published")

        return handler

    def _delete_post(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            seal_id: str,
            confirm: Annotated[str, Form(max_length=10)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            checked = signed_in_action(request, path_locale, lang, csrf)
            if not isinstance(checked, tuple):
                return checked
            account, _, locale, _ = checked
            if not _ID.match(seal_id):
                return _redirect(locale, error="record_not_found")
            if confirm != "yes":
                # The confirmation step: the same CSRF token, one more form.
                if service.get_record(store, seal_id, account_id=account.id) is None:
                    return _redirect(locale, error="record_not_found")
                return HTMLResponse(delete_confirm_page(locale=locale, seal_id=seal_id, csrf=csrf))
            refusal = service.delete_record(
                store, seal_id=seal_id, account_id=account.id, now=_now()
            )
            if refusal is not None:
                return _redirect(locale, error=refusal.code)
            return _redirect(locale, done="deleted")

        return handler

    for path_locale in LANGUAGES:
        base = path("records", path_locale)
        app.add_api_route(base, _records_get(path_locale), **html_get)
        app.add_api_route(base + "/abrir", _open_post(path_locale), methods=["POST"])
        app.add_api_route(base + "/{seal_id}", _record_get(path_locale), **html_get)
        app.add_api_route(base + "/{seal_id}/cargar", _upload_post(path_locale), methods=["POST"])
        app.add_api_route(
            base + "/{seal_id}/terminar",
            _simple_post(path_locale, _end, "ended"),
            methods=["POST"],
        )
        app.add_api_route(base + "/{seal_id}/borrar", _delete_post(path_locale), methods=["POST"])
        app.add_api_route(
            base + "/{seal_id}/publicar", _publish_post(path_locale), methods=["POST"]
        )
        app.add_api_route(
            base + "/{seal_id}/despublicar",
            _simple_post(path_locale, _unpublish, "unpublished"),
            methods=["POST"],
        )

    # (the examples were mounted first, before the public ids)

    # -- public page, badge and chain ----------------------------------------
    def _public_view(public_id: str) -> PublicView:
        if not _ID.match(public_id):
            raise _not_found()
        view = service.public_record(store, public_id)
        if view is None:
            raise _not_found()
        return view

    def _public_get(locale: str) -> Callable[..., Response]:
        def handler(public_id: str) -> Response:
            view = _public_view(public_id)
            alternates = {lang: f"{path('public', lang)}/{public_id}" for lang in public_locales}
            return HTMLResponse(public_page(view, locale=locale, now=_now(), alternates=alternates))

        return handler

    def _badge_get(locale: str) -> Callable[..., Response]:
        def handler(public_id: str, lang: str | None = None) -> Response:
            view = _public_view(public_id)
            sealed = view.sealed
            overall = sealed.stretch_class if sealed is not None and view.chain_ok else ""
            if view.status == STATUS_WITHDRAWN:
                raise _not_found()
            svg = record_badge_svg(
                overall=overall,
                public_id=view.public_id,
                last_upload=_day(view.last_upload_at),
                locale=lang if lang in public_locales else locale,
            )
            return Response(content=svg, media_type="image/svg+xml")

        return handler

    def _chain_get() -> Callable[..., Response]:
        def handler(public_id: str) -> Response:
            if not _ID.match(public_id):
                raise _not_found()
            seal_id = service.public_seal_id(store, public_id)
            if seal_id is None:
                raise _not_found()
            return JSONResponse(service.chain_json(store, seal_id))

        return handler

    if public_on:
        for locale in public_locales:
            prefix = path("public", locale) + "/{public_id}"
            app.add_api_route(prefix, _public_get(locale), **html_get)
            app.add_api_route(prefix + "/badge.svg", _badge_get(locale), methods=["GET"])
            app.add_api_route(prefix + "/chain.json", _chain_get(), methods=["GET"])

    # -- owner panel ---------------------------------------------------------
    @app.get(PANEL_RECORDS_PATH, response_class=HTMLResponse)
    def panel_records_login() -> str:
        if not settings.admin_enabled:
            raise _not_found()
        return panel_login_page()

    @app.post(PANEL_RECORDS_PATH, response_class=HTMLResponse)
    def panel_records(
        request: Request,
        key: Annotated[str, Form(max_length=256)],
        action: Annotated[str, Form(max_length=16)] = "list",
        seal_id: Annotated[str, Form(max_length=64)] = "",
    ) -> Response:
        """Protected exactly like ``/panel``: the key in the body, compared
        in constant time, wrong keys limited per address in the same log."""
        if not settings.admin_enabled:
            raise _not_found()
        ip = _client_ip(request, settings.trusted_proxy_hops)
        now = _now()
        if panel_failures.count(ip, now) >= MAX_FAILED_LOGINS_PER_HOUR:
            return HTMLResponse(panel_login_page(error="too_many"), status_code=429)
        if not hmac.compare_digest(key.encode(), settings.admin_key.encode()):
            panel_failures.hit(ip, now)
            return HTMLResponse(panel_login_page(error="wrong_key"), status_code=403)
        flash = error = ""
        if action in ("hide", "unhide"):
            if not _ID.match(seal_id):
                error = "not_found"
            else:
                act = service.hide if action == "hide" else service.unhide
                refusal = act(store, seal_id=seal_id, now=now)
                if refusal is None:
                    flash = "hidden" if action == "hide" else "shown"
                else:
                    error = "not_found"
        records = [
            (record, service.verify(store, record.id)[0]) for record in service.all_records(store)
        ]
        return HTMLResponse(panel_records_page(key=key, records=records, flash=flash, error=error))

    return True


__all__ = [
    "EXAMPLE_NOW",
    "EXAMPLE_VIEW",
    "MIN_REAL_PAIRS",
    "PANEL_RECORDS_PATH",
    "PANEL_TEXT",
    "PATHS",
    "REAL_PAIRS_DOCUMENTED",
    "SYNTHETIC_STATEMENT",
    "TRACK_CSS",
    "TRACK_SEAL_ENABLED",
    "TRACK_SEAL_PUBLIC_ENABLED",
    "TRACK_SEAL_PUBLIC_PT_ENABLED",
    "TRACK_SEAL_EXAMPLES_ENABLED",
    "RecordPageData",
    "coherence_example_page",
    "coherence_results",
    "coherence_variants",
    "delete_confirm_page",
    "example_page",
    "panel_login_page",
    "panel_records_page",
    "path",
    "public_page",
    "record_badge_svg",
    "record_page",
    "records_page",
    "register",
]
