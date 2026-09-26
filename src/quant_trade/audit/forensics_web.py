"""The private "Coherencia del archivo" page, behind ``FORENSICS_ENABLED``.

``register`` is called once from ``web.create_app`` with the app's own
closures (report loading, sessions, cross-site check, signed-in actions
and the panel's attempt log), so no security logic is copied here. While
the switch is off nothing is registered and every path answers 404.

The page opens exactly like the report (its token, or the signed-in owner)
and only when the report is paid or the service runs free; it re-reads the
stored platform file after checking its SHA-256 against the digest recorded
at upload, runs the battery under an audit slot, keeps results (never
bytes) in a small LRU, and limits uncached reviews per client address.
Everything it prints comes from ``forensics.copy`` and from the battery's
codes, counts and row indexes: no text of the file reaches the page.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from collections import OrderedDict
from collections.abc import Callable, Coroutine, Sequence
from datetime import UTC, datetime
from typing import Any

from quant_trade.audit import importers
from quant_trade.audit.compare import guard_page
from quant_trade.audit.forensics import copy as words
from quant_trade.audit.forensics.calibration import SIGNAL_CAPABLE
from quant_trade.audit.forensics.results import (
    STATUS_CLEAN,
    STATUS_INFO,
    STATUS_NOT_MEASURED,
    STATUS_SIGNAL,
    CheckResult,
    ForensicResult,
)
from quant_trade.audit.forensics.review import CHECK_ORDER, METHOD_VERSION, review
from quant_trade.audit.pages import _e, _page, _page_hero

logger = logging.getLogger("quant_trade.audit.forensics_web")

#: A constant, not a Railway variable: the page ships hidden and is turned
#: on by a change in the repository, after its reviews.
FORENSICS_ENABLED = False

#: The page's path under ``/audits/{audit_id}`` per language; ``?lang=``
#: overrides the path's language, as the report's does.
PATHS: dict[str, str] = {"es": "coherencia", "en": "consistency", "pt": "coerencia"}
LOCALES = words.LOCALES

#: Results kept per process: ``(audit_id, METHOD_VERSION, sha256)`` to result.
CACHE_SIZE = 256
#: Uncached reviews one client address may start in a sliding hour.
MAX_REVIEWS_PER_IP_PER_HOUR = 30
#: The attempt log's name in the store's table (kept apart from the panel's).
ATTEMPT_LOG_NAME = "forensics"

_CSS = """
.fx-note{border:1px solid var(--border);border-radius:18px;padding:22px 24px;background:#fff;
margin:0 0 22px}
.fx-note p{margin:0 0 10px}.fx-note p:last-child{margin-bottom:0}
.fx-meta{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:0;
padding:0;list-style:none}
.fx-meta li{border:1px solid var(--border);border-radius:14px;padding:12px 14px;background:#fff}
.fx-meta b{display:block;font:500 .68rem var(--mono);text-transform:uppercase;letter-spacing:.1em;
color:var(--text-3);margin-bottom:6px}
.fx-findings{padding-left:1.2em}.fx-findings li{margin:0 0 10px}
.fx-figs{list-style:none;padding:0;margin:0;display:grid;gap:4px;font-size:.82rem}
.fx-figs .badge{margin-left:4px}
.fx-k{color:var(--text-2)}
.fx-cal{display:block;margin-top:8px;font-size:.8rem;color:var(--text-3)}
.fx-ex{display:block;margin-top:6px;font-size:.82rem;color:var(--text-2)}
.badge.fx-SIGNAL{color:var(--bad);background:color-mix(in srgb,var(--bad) 9%,transparent);
border-color:color-mix(in srgb,var(--bad) 30%,transparent)}
.badge.fx-INFO{color:var(--warn);background:color-mix(in srgb,var(--warn) 10%,transparent);
border-color:color-mix(in srgb,var(--warn) 32%,transparent)}
.badge.fx-CLEAN{color:var(--ok);background:color-mix(in srgb,var(--ok) 10%,transparent);
border-color:color-mix(in srgb,var(--ok) 30%,transparent)}
.badge.fx-NOT_MEASURED{color:var(--text-3);background:var(--surface-2,#f4f4f6);
border-color:var(--border)}
.paper table.fx-checks td:first-child{font-weight:600;min-width:160px}
@media (max-width:759px){.paper table.fx-checks,.fx-checks tbody,.fx-checks tr,.fx-checks td{
display:block}.fx-checks thead{display:none}.paper table.fx-checks{overflow:visible;border:0;
background:none;box-shadow:none}.fx-checks tr{background:#fff;border:1px solid var(--border);
border-radius:14px;padding:12px 14px;margin:0 0 8px}.fx-checks td{border:0!important;
padding:4px 0!important}}
"""


class ResultCache:
    """An LRU of battery results (never bytes), thread-safe, per process."""

    def __init__(self, size: int = CACHE_SIZE) -> None:
        self.size = size
        self._items: OrderedDict[tuple[str, str, str], ForensicResult] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str, str]) -> ForensicResult | None:
        with self._lock:
            result = self._items.get(key)
            if result is not None:
                self._items.move_to_end(key)
            return result

    def put(self, key: tuple[str, str, str], result: ForensicResult) -> None:
        with self._lock:
            self._items[key] = result
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


class NothingToReview(Exception):
    """The record holds no file the battery reads; ``note`` names the page's text."""

    def __init__(self, note: str) -> None:
        super().__init__(note)
        self.note = note


def stored_target(record: Any) -> tuple[str, bytes] | None:
    """The blob the page reviews: the platform report, else the live statement,
    else the equity upload (a monthly table, when it is one)."""
    files: dict[str, bytes] = getattr(record, "files", None) or {}
    for stem in ("report.", "live."):
        for name in sorted(files):
            if name.startswith(stem) and files[name]:
                return name, files[name]
    equity = getattr(record, "equity_csv", None)
    if equity:
        return "equity.csv", bytes(equity)
    return None


def digest_matches(record: Any, name: str, blob: bytes) -> bool:
    digests: dict[str, str] = getattr(record, "digests", None) or {}
    return hashlib.sha256(blob).hexdigest() == digests.get(name)


def source_format_of(record: Any) -> str | None:
    """The importer format recorded in the result JSON, or None."""
    try:
        inputs = json.loads(getattr(record, "result_json", None) or "{}").get("inputs") or {}
    except ValueError:
        return None
    value = inputs.get("source_format")
    return str(value) if value else None


def _monthly_grid(data: bytes) -> Any:
    """A ``factsheet.MonthlyGrid`` when ``data`` is a year-by-month table, else None."""
    from quant_trade.audit.factsheet import monthly_grid
    from quant_trade.audit.schema import _read_csv

    try:
        return monthly_grid(_read_csv(data, what="equity"))
    except Exception:  # noqa: BLE001 - a table the reader refuses is not a grid
        return None


def review_blob(
    blob: bytes, name: str, source_format: str | None, *, audit_id: str
) -> ForensicResult:
    """Run the battery on one stored blob; raises ``NothingToReview`` with the
    note to show when the blob is not one the battery reads."""
    if name == "equity.csv":
        grid = _monthly_grid(blob)
        if grid is None:
            raise NothingToReview("nothing_to_review")
        try:
            return review(b"", source_format=None, monthly=grid)
        except Exception:
            logger.exception("forensics: monthly review failed for audit %s", audit_id)
            raise NothingToReview("review_failed") from None
    warnings: Sequence[str] = ()
    currency: str | None = None
    try:
        imported = importers.import_report(blob, name)
        warnings, currency = tuple(imported.warnings), imported.currency
    except Exception:  # noqa: BLE001 - the battery still runs, without the importer's notes
        logger.info("forensics: import failed for audit %s; battery runs without it", audit_id)
    try:
        return review(
            blob, source_format=source_format, imported_warnings=warnings, currency=currency
        )
    except Exception:
        logger.exception("forensics: review failed for audit %s", audit_id)
        raise NothingToReview("review_failed") from None


# ---------------------------------------------------------------- rendering


def _badge(kind: str, text: str) -> str:
    return f"<span class='badge {_e(kind)}'>{_e(text)}</span>"


def _figures_html(check: CheckResult, locale: str) -> str:
    ev = words.EVIDENCE_WORDS[locale]
    items = []
    for key, value, evidence in check.figures:
        shown = value if value != "" else "—"
        items.append(
            f"<li><span class='fx-k'>{_e(words.figure_label(key, locale))}:</span> "
            f"<code>{_e(shown)}</code>{_badge(evidence, ev.get(evidence, evidence))}</li>"
        )
    return f"<ul class='fx-figs'>{''.join(items)}</ul>" if items else ""


def _calibration_html(check: CheckResult, locale: str) -> str:
    copy = words.COPY[locale]
    cell = dict(check.calibration)
    if cell:
        text = copy["calibration"].format(
            n=cell.get("n", "0"),
            unexplained=cell.get("unexplained", "0"),
            cp95=cell.get("cp95_upper_pct", "100.0"),
        )
    elif check.id in SIGNAL_CAPABLE:
        text = copy["no_calibration"]
    else:
        return ""
    return f"<span class='fx-cal'>{_e(text)}</span>"


def _fact(check: CheckResult, locale: str) -> str:
    template = words.CHECK_FACTS[locale][check.id]
    return template.format(
        n_hits=check.figure("n_hits") or str(max(len(check.examples), 1)),
        n_rows=check.figure("n_rows") or "—",
    )


def finding_sentence(check: CheckResult, locale: str) -> str:
    """The summary sentence of a SIGNAL or INFO check: the measured fact, the
    legitimate-explanations sentence and, for INFO, why it is not a signal."""
    copy = words.COPY[locale]
    parts = [_fact(check, locale) + ".", copy["legit"]]
    if check.status == STATUS_INFO:
        if check.id in SIGNAL_CAPABLE:
            n = dict(check.calibration).get("n", "0")
            parts.append(copy["info_uncalibrated"].format(n=n))
        else:
            parts.append(copy["info_descriptive"])
    return " ".join(parts)


def _examples_html(check: CheckResult, locale: str) -> str:
    if not check.examples:
        return ""
    rows = ", ".join(str(index) for index in check.examples)
    return f"<span class='fx-ex'>{_e(words.COPY[locale]['examples'].format(rows=rows))}</span>"


def _notes_html(check: CheckResult, locale: str) -> str:
    copy = words.COPY[locale]
    if check.status == STATUS_NOT_MEASURED:
        reason = words.REASON_TEXT[locale].get(check.reason, check.reason.replace("_", " "))
        return _e(copy["not_measured_prefix"].format(reason=reason))
    if check.status == STATUS_CLEAN:
        return _e(copy["clean_note"]) + _calibration_html(check, locale)
    return (
        _e(finding_sentence(check, locale))
        + _examples_html(check, locale)
        + _calibration_html(check, locale)
    )


def _checks_table(result: ForensicResult, locale: str) -> str:
    copy = words.COPY[locale]
    names = words.CHECK_NAMES[locale]
    status_words = words.STATUS_WORDS[locale]
    head = (
        f"<thead><tr><th>{_e(copy['col_check'])}</th><th>{_e(copy['col_status'])}</th>"
        f"<th>{_e(copy['col_figures'])}</th><th>{_e(copy['col_notes'])}</th></tr></thead>"
    )
    rows = []
    by_id = {check.id: check for check in result.checks}
    for check_id in CHECK_ORDER:
        check = by_id.get(check_id)
        if check is None:
            continue
        rows.append(
            f"<tr><td>{_e(names[check_id])}</td>"
            f"<td>{_badge('fx-' + check.status, status_words[check.status])}</td>"
            f"<td>{_figures_html(check, locale)}</td>"
            f"<td>{_notes_html(check, locale)}</td></tr>"
        )
    return f"<table class='fx-checks'>{head}<tbody>{''.join(rows)}</tbody></table>"


def _summary_html(result: ForensicResult, locale: str) -> str:
    copy = words.COPY[locale]
    counts = copy["counts"].format(
        signal=result.count(STATUS_SIGNAL),
        info=result.count(STATUS_INFO),
        clean=result.count(STATUS_CLEAN),
        not_measured=result.count(STATUS_NOT_MEASURED),
    )
    hits = [c for c in result.checks if c.status in (STATUS_SIGNAL, STATUS_INFO)]
    if hits:
        names = words.CHECK_NAMES[locale]
        items = "".join(
            f"<li><b>{_e(names[c.id])}.</b> {_e(finding_sentence(c, locale))}"
            f"{_examples_html(c, locale)}</li>"
            for c in hits
        )
        body = f"<ul class='fx-findings'>{items}</ul>"
    else:
        body = f"<p>{_e(copy['no_findings'])}</p>"
    return (
        f"<h2>{_e(copy['summary_heading'])}</h2><p class='muted'>{_e(counts)}</p>{body}"
        f"<p><b>{_e(copy['method'])}</b></p>"
    )


def _file_html(result: ForensicResult, locale: str) -> str:
    copy = words.COPY[locale]
    families = words.FAMILY_NAMES[locale]
    measured = _badge("MEASURED", words.EVIDENCE_WORDS[locale]["MEASURED"])
    items = [
        (copy["family"], _e(families.get(result.family, families["other"]))),
        (copy["format"], f"<code>{_e(result.source_format)}</code>"),
        (copy["method_version"], f"<code>{_e(result.method_version)}</code>"),
        (copy["rows_read"], f"{result.rows_read} {measured}"),
    ]
    lis = "".join(f"<li><b>{_e(label)}</b>{value}</li>" for label, value in items)
    truncated = f"<p class='muted'>{_e(copy['truncated'])}</p>" if result.truncated else ""
    return f"<h2>{_e(copy['file_heading'])}</h2><ul class='fx-meta'>{lis}</ul>{truncated}"


def _evidence_html(locale: str) -> str:
    copy = words.COPY[locale]
    ev = words.EVIDENCE_WORDS[locale]
    lis = "".join(
        f"<li>{_badge(tag, ev[tag])} {_e(text)}</li>"
        for tag, text in words.EVIDENCE_HELP[locale].items()
    )
    return f"<h2>{_e(copy['evidence_heading'])}</h2><ul class='fx-findings'>{lis}</ul>"


def _limits_html(locale: str) -> str:
    copy = words.COPY[locale]
    lis = "".join(f"<li>{_e(item)}</li>" for item in copy["limits"].split("|"))
    return f"<h2>{_e(copy['limits_heading'])}</h2><ul class='fx-findings'>{lis}</ul>"


def _query(token: str | None, locale: str) -> str:
    return f"?token={token}&lang={locale}" if token else f"?lang={locale}"


def _frame(
    body: str, *, locale: str, audit_id: str, token: str | None, alternates: dict[str, str]
) -> str:
    copy = words.COPY[locale]
    report_url = f"/audits/{audit_id}{_query(token, locale)}"
    crumbs = f"<a href='{_e(report_url)}'>&larr; {_e(copy['back'])}</a>"
    hero = _page_hero(copy["eyebrow"], copy["title"], copy["lead"], crumbs)
    main = (
        f"<div class='paper page-main'><div class='wrap wrap-mid'><style>{_CSS}</style>"
        f"<div class='fx-note'><p><b>{_e(copy['method'])}</b></p>"
        f"<p>{_e(copy['no_change'])} {_e(copy['paid_note'])}</p></div>"
        f"{body}</div></div>"
    )
    return guard_page(
        _page(copy["title"], locale, hero + main, alternates=alternates, solid_nav=True)
    )


def render_result(result: ForensicResult, *, locale: str, audit_id: str, token: str | None) -> str:
    """The whole page for a battery result."""
    body = (
        _file_html(result, locale)
        + _summary_html(result, locale)
        + f"<h2>{_e(words.COPY[locale]['table_heading'])}</h2>"
        + _checks_table(result, locale)
        + _evidence_html(locale)
        + _limits_html(locale)
    )
    return _frame(
        body,
        locale=locale,
        audit_id=audit_id,
        token=token,
        alternates=_alternates(audit_id, token),
    )


def render_note(note: str, *, locale: str, audit_id: str, token: str | None) -> str:
    """The page with one note instead of a result (nothing to review, digest
    mismatch, review failed, busy, too many)."""
    body = f"<div class='fx-note'><p>{_e(words.COPY[locale][note])}</p></div>" + _limits_html(
        locale
    )
    return _frame(
        body,
        locale=locale,
        audit_id=audit_id,
        token=token,
        alternates=_alternates(audit_id, token),
    )


def _alternates(audit_id: str, token: str | None) -> dict[str, str]:
    return {
        locale: f"/audits/{audit_id}/{slug}{_query(token, locale)}"
        for locale, slug in PATHS.items()
    }


# ------------------------------------------------------------------- routes


async def _acquire(slots: Any, wait_seconds: float) -> bool:
    """One audit slot, through the app's own ``_take_slot`` (imported late:
    ``web`` imports this module)."""
    from quant_trade.audit.web import _take_slot

    return await _take_slot(slots, wait_seconds)


def _client_address(request: Any, trusted_proxy_hops: int) -> str:
    from quant_trade.audit.web import _client_ip

    return str(_client_ip(request, trusted_proxy_hops))


def _attempt_log(store: Any) -> Any:
    from quant_trade.audit.web import StoredAttemptLog

    return StoredAttemptLog(store, ATTEMPT_LOG_NAME)


Handler = Callable[..., Coroutine[Any, Any, Any]]


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
    """Mount the page on ``app``; returns whether anything was mounted.

    A GET page needs only ``load`` (token or signed-in owner), ``settings``
    (free mode, proxy hops, queue seconds), ``store`` (blobs and the attempt
    table) and ``slots``; the other closures are accepted for the common
    hook signature and left unused.
    """
    if not FORENSICS_ENABLED:
        return False
    # Imported here, as ``web.create_app`` does: the web extra is optional.
    from fastapi import HTTPException, Request, Response
    from fastapi.responses import HTMLResponse
    from starlette.concurrency import run_in_threadpool

    cache = ResultCache(CACHE_SIZE)
    attempts = _attempt_log(store)
    app.state.forensics_cache = cache
    headers = {"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex"}

    def _html(page: str, status: int = 200) -> Any:
        return HTMLResponse(page, status_code=status, headers=headers)

    def _handler(default_locale: str) -> Handler:
        async def consistency_page(
            request: Any, audit_id: str, token: str | None = None, lang: str | None = None
        ) -> Any:
            record = await run_in_threadpool(load, audit_id, token, request)
            locale = lang if lang in LOCALES else default_locale
            if not record.paid and not settings.free_mode:
                raise HTTPException(status_code=402, detail="payment_required")
            full = await run_in_threadpool(store.get_audit, record.id, with_blobs=True)
            target = stored_target(full)
            note_args = {"locale": locale, "audit_id": record.id, "token": token}
            if target is None:
                return _html(render_note("nothing_to_review", **note_args))
            name, blob = target
            if not digest_matches(full, name, blob):
                return _html(render_note("digest_mismatch", **note_args))
            key = (record.id, METHOD_VERSION, hashlib.sha256(blob).hexdigest())
            result = cache.get(key)
            if result is None:
                ip = _client_address(request, settings.trusted_proxy_hops)
                now = datetime.now(UTC)
                if attempts.count(ip, now) >= MAX_REVIEWS_PER_IP_PER_HOUR:
                    return _html(render_note("too_many", **note_args), 429)
                attempts.hit(ip, now)
                if not await _acquire(slots, float(settings.audit_queue_seconds)):
                    return _html(render_note("busy", **note_args), 503)
                try:
                    result = await run_in_threadpool(
                        review_blob, blob, name, source_format_of(full), audit_id=record.id
                    )
                except NothingToReview as skipped:
                    return _html(render_note(skipped.note, **note_args))
                finally:
                    slots.release()
                cache.put(key, result)
            return _html(render_result(result, **note_args))

        # FastAPI reads the annotations at registration and, under ``from
        # __future__ import annotations``, resolves their strings against this
        # module's globals, where the lazily imported ``Request`` does not
        # live: the real objects are set here so ``request`` is the request
        # and ``token`` and ``lang`` are optional query parameters.
        consistency_page.__annotations__ = {
            "request": Request,
            "audit_id": str,
            "token": str | None,
            "lang": str | None,
            "return": Response,
        }
        return consistency_page

    for locale, slug in PATHS.items():
        app.get(f"/audits/{{audit_id}}/{slug}", name=f"forensics_{locale}")(_handler(locale))
    return True


__all__ = [
    "ATTEMPT_LOG_NAME",
    "CACHE_SIZE",
    "FORENSICS_ENABLED",
    "MAX_REVIEWS_PER_IP_PER_HOUR",
    "PATHS",
    "NothingToReview",
    "ResultCache",
    "digest_matches",
    "finding_sentence",
    "register",
    "render_note",
    "render_result",
    "review_blob",
    "source_format_of",
    "stored_target",
]
