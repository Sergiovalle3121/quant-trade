"""The audit service: upload a backtest, read the verdict, optionally pay.

FastAPI, imported lazily so the core package never depends on the ``web``
extra. Every report URL carries a per-audit secret token; a wrong token is
a 404 (never a 403) so the service does not confirm that an id exists.
Stripe is optional: without every Stripe variable the service is in free
mode, serves watermarked reports and refuses to create checkouts, unless the
owner opts into selling access codes. The webhook signature is verified
locally with the documented HMAC scheme so the payment path needs no SDK to
be trustworthy.

Growth routes: an owner can publish a verification page (``/v/{public_id}``)
and its badge; those two routes are the only cacheable ones. ``/ejemplo``
and ``/sample`` serve a full report of synthetic data.
"""

# No ``from __future__ import annotations`` here: FastAPI resolves the route
# signatures at definition time, and the names it needs are imported inside
# ``create_app`` so the module stays importable without the ``web`` extra.

import base64
import contextlib
import dataclasses
import hashlib
import hmac
import ipaddress
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import OrderedDict
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from urllib.parse import quote, urlsplit

from pydantic import ValidationError

from quant_trade.audit import account_pages, funnel, mapping, payments, universal
from quant_trade.audit import accounts as acct
from quant_trade.audit import check as check_lib
from quant_trade.audit import pdf as pdf_lib
from quant_trade.audit import strategies as strategies_lib
from quant_trade.audit.audiences import AUDIENCES_BY_PATH, audience_url
from quant_trade.audit.compare import (
    COMPARE_PATH,
    compare_form,
    comparison_body,
    guard_page,
    parse_report_link,
)
from quant_trade.audit.compare import COPY as COMPARE_COPY
from quant_trade.audit.engine import run_audit
from quant_trade.audit.errors_pt import FILES_PT
from quant_trade.audit.guides import GUIDES_BY_PATH, guide_url
from quant_trade.audit.importers import detect_format
from quant_trade.audit.legal import LegalContext, privacy_text, terms_text
from quant_trade.audit.market import MarketData
from quant_trade.audit.owner import (
    MAX_CREDITS,
    MAX_EXPIRES_DAYS,
    MAX_FAILED_LOGINS_PER_HOUR,
    MAX_NOTE_CHARS,
    PANEL_PATH,
    funnel_section,
    login_page,
    panel_page,
)
from quant_trade.audit.pages import (
    LANDING_PATHS,
    SAMPLE_BANNER,
    audience_page,
    badge_svg,
    check_page,
    compare_page,
    error_page,
    guide_page,
    guides_index_page,
    landing,
    legal_page,
    method_page,
    sample_meta,
    verification_page,
)
from quant_trade.audit.payments import stripe_checkout
from quant_trade.audit.portuguese import MESSAGES_PT, link_locale
from quant_trade.audit.report import render, result_sha256
from quant_trade.audit.retention import RetentionWorker
from quant_trade.audit.sample import sample_result
from quant_trade.audit.schema import (
    AuditResult,
    DeclaredMetadata,
    ParseError,
    build_inputs,
    live_digest_name,
    report_digest_name,
)
from quant_trade.audit.seo import BRAND, DISALLOWED_PATHS, NOINDEX, robots_txt, sitemap_xml
from quant_trade.audit.settings import DEFAULT_BASE_URL, AuditSettings
from quant_trade.audit.store import (
    CODE_REFERENCE_PREFIX,
    REQUIRE_WEB,
    VIA_PAID,
    VIA_SAVED,
    VIA_UPLOAD,
    Store,
    make_store,
    strategy_name,
)
from quant_trade.audit.theme import STATIC_CACHE_CONTROL, static_file
from quant_trade.evidence.canonical_json import canonical_dumps, sha256_of_bytes

#: ``(settings, audit_id, token, *, plan, locale) -> Stripe Checkout URL``.
CheckoutFactory = Callable[..., str]
#: ``(settings, session_id) -> the Checkout session as Stripe returns it``.
SessionLookup = Callable[[AuditSettings, str], dict[str, Any]]

logger = logging.getLogger("quant_trade.audit.web")

STRIPE_TOLERANCE_SECONDS = 300
#: Webhook events that can mean a Checkout session was paid; ``fulfil``
#: still checks ``payment_status`` (a delayed method completes unpaid).
PAID_EVENTS = ("checkout.session.completed", "checkout.session.async_payment_succeeded")
#: The page languages; Spanish is the default everywhere.
LOCALES = ("es", "en")
#: The report's languages: its pages, its PDF and the sample. Screens with no
#: Portuguese yet (accounts, payments, messages) show a Portuguese reader English.
REPORT_LOCALES = ("es", "en", "pt")
_EMAIL_MAX = 254
#: Control characters, dropped from the column names a customer types.
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

#: Every message the service itself shows, in both locales. Parse errors
#: carry their own Spanish text (``ParseError.localized``).
MESSAGES: dict[str, dict[str, str]] = {
    "consent_required": {
        "es": "Tienes que aceptar las condiciones para enviar la auditoría.",
        "en": "You must accept the terms to submit the audit.",
    },
    "cross_site": {
        "es": "Esta subida no viene del formulario de este sitio. Abre la página y súbela ahí.",
        "en": "This upload does not come from this site's form. Open the page and upload there.",
    },
    "rate_limited": {
        "es": "Demasiadas auditorías desde esta dirección en la última hora; inténtalo más tarde.",
        "en": "Too many audits from this address in the last hour; try again later.",
    },
    "too_large": {
        "es": (
            "El archivo {what} pesa más de {limit}, el máximo que aceptamos: sube una versión "
            "más pequeña (por ejemplo, un periodo más corto o menos pasadas de optimización)."
        ),
        "en": (
            "The {what} file is larger than {limit}, the most we accept: upload a smaller "
            "version (for example a shorter period or fewer optimisation passes)."
        ),
    },
    "optimization_too_large": {
        "es": (
            "El XML de optimización pesa más de {limit} (unas {passes} pasadas), el máximo que "
            "aceptamos: vuelve a optimizar con el algoritmo genético o con rangos de "
            "parámetros más cortos y exporta de nuevo. También puedes subir el informe "
            "sin el XML y escribir el número de pasadas en «Configuraciones probadas»."
        ),
        "en": (
            "The optimisation XML is larger than {limit} (about {passes} passes), the most we "
            "accept: optimise again with the genetic algorithm or narrower parameter "
            "ranges and export it again. You can also upload the report without the "
            'XML and type the number of passes in "Configurations tried".'
        ),
    },
    "equity_required": {
        "es": (
            "Falta el archivo: sube el informe de tu plataforma (MetaTrader, TradingView...) "
            "o una curva de equity."
        ),
        "en": "A file is missing: upload your platform report (MetaTrader, TradingView...) "
        "or an equity curve.",
    },
    "invalid_declared": {
        "es": (
            "Algún dato declarado no es válido: el número de intentos debe ser 1 o más, "
            "el coste no puede ser negativo, el balance inicial debe ser positivo, el reto "
            "debe ser uno de la lista, la descripción tiene como máximo 2000 caracteres "
            "y la fecha fuera de muestra va como AAAA-MM-DD."
        ),
        "en": (
            "A declared field is invalid: trials must be 1 or more, the cost cannot be "
            "negative, the starting balance must be positive, the challenge must be one "
            "from the list, the description is at most 2000 characters and the "
            "out-of-sample date is YYYY-MM-DD."
        ),
    },
    "invalid_form": {
        "es": (
            "El formulario llegó incompleto o con un valor no válido; revísalo y vuelve a enviarlo."
        ),
        "en": "The form arrived incomplete or with an invalid value; check it and submit again.",
    },
    "invalid_upload": {
        "es": "No se pudo auditar lo que subiste tal como está; revisa el formato de los archivos.",
        "en": "What you uploaded could not be audited as supplied; check the file format.",
    },
    "invalid_email": {
        "es": "Esa dirección de correo no parece válida.",
        "en": "That e-mail address does not look valid.",
        "pt": "Esse endereço de e-mail não parece válido.",
    },
    "page_missing": {
        "es": "Esta página no existe. Revisa la dirección o vuelve al inicio.",
        "en": "This page does not exist. Check the address or go back to the home page.",
    },
    "not_found": {
        "es": "No encontramos esa auditoría. Revisa que el enlace esté completo.",
        "en": "We could not find that audit. Check that the link is complete.",
    },
    "purged": {
        "es": "Esta auditoría se borró al cumplirse el plazo de conservación.",
        "en": "This audit was deleted when its retention period ended.",
    },
    "payment_required": {
        "es": "El detalle completo de esta auditoría requiere el pago.",
        "en": "The full detail of this audit requires payment.",
    },
    "payments_disabled": {
        "es": "Los pagos no están activados en este servicio.",
        "en": "Payments are not enabled on this service.",
    },
    "card_paid": {
        "es": "Pago recibido: este es el informe completo. Stripe te envía el recibo por correo.",
        "en": "Payment received: this is the full report. Stripe emails you the receipt.",
    },
    "card_pending": {
        "es": (
            "Estamos confirmando tu pago con Stripe. Recarga esta página en unos segundos; "
            "no vuelvas a pagar."
        ),
        "en": (
            "We are confirming your payment with Stripe. Reload this page in a few seconds; "
            "do not pay again."
        ),
    },
    "card_cancelled": {
        "es": "Pago cancelado: no se hizo ningún cargo. Esta es la vista previa.",
        "en": "Payment cancelled: nothing was charged. This is the preview.",
    },
    "code_applied": {
        "es": "Código de acceso aplicado: este es el informe completo.",
        "en": "Access code applied: this is the full report.",
    },
    "codes_disabled": {
        "es": "Este servicio no acepta códigos de acceso.",
        "en": "This service does not accept access codes.",
    },
    "busy": {
        "es": (
            "El servicio está calculando otras auditorías en este momento; "
            "vuelve a enviar el archivo en un minuto."
        ),
        "en": "The service is busy with other audits right now; submit the file again in a minute.",
    },
    "pdf_busy": {
        "es": "Estamos preparando otros PDF en este momento. Vuelve a intentarlo en unos segundos.",
        "en": "Other PDFs are being prepared right now. Try again in a few seconds.",
    },
    "pdf_limit": {
        "es": "Preparaste varios PDF hace poco. Vuelve a intentarlo en unos minutos.",
        "en": "You prepared several PDFs a moment ago. Try again in a few minutes.",
    },
    "pdf_unavailable": {
        "es": (
            "La descarga en PDF no está disponible ahora mismo. Usa el botón de imprimir de la "
            "página del informe y elige guardar como PDF."
        ),
        "en": (
            "PDF download is not available right now. Use the report page's print button and "
            "choose save as PDF."
        ),
    },
    "server_error": {
        "es": (
            "Algo falló de nuestro lado al procesar la petición. No se guardó nada nuevo; "
            "inténtalo de nuevo y, si se repite, escríbenos."
        ),
        "en": (
            "Something failed on our side while handling the request. Nothing new was saved; "
            "try again and, if it happens again, contact us."
        ),
    },
    "body_too_large": {
        "es": (
            "La subida pesa más de {limit} en total, el tamaño máximo que aceptamos: sube menos "
            "archivos a la vez o versiones más pequeñas."
        ),
        "en": (
            "The upload is larger than {limit} in total, the maximum size we accept: upload "
            "fewer files at once or smaller versions."
        ),
    },
    "publish_locked": {
        "es": "Solo se puede publicar la verificación de un informe completo.",
        "en": "Only a full report can publish a verification.",
    },
}
for _key, _text in MESSAGES_PT.items():
    MESSAGES[_key].setdefault("pt", _text)

#: The only routes a browser or CDN may cache: public by design, no token.
PUBLIC_CACHE_CONTROL = "public, max-age=300"
_CODE_MAX = 40

#: The one piece of script on any page: the report's "print / save PDF"
#: button handler. The policy allows exactly this handler by its hash.
PRINT_HANDLER = "window.print()"
_PRINT_HANDLER_HASH = base64.b64encode(hashlib.sha256(PRINT_HANDLER.encode()).digest()).decode()

#: Script runs only from this site's own ``/static/app.js`` (progressive
#: enhancement: every page works without it) and as the print handler above;
#: no inline script and nothing from a third party. Fonts are self-hosted, so
#: no visitor request leaves for a font service. Inline styles are the other
#: relaxation (the report's CSS and chart colours are inline); forms post
#: here, or leave for Stripe Checkout through a redirect, and no page can be
#: framed.
CONTENT_SECURITY_POLICY = (
    f"default-src 'none'; script-src 'self' 'unsafe-hashes' 'sha256-{_PRINT_HANDLER_HASH}'; "
    "style-src 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'none'; "
    "form-action 'self' https://checkout.stripe.com; frame-ancestors 'none'; "
    "base-uri 'none'"
)
SECURITY_HEADERS: dict[str, str] = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
HSTS = "max-age=31536000"

#: Every upload attempt counts, whether or not it becomes an audit, up to
#: this multiple of the hourly upload limit: a customer can retry a file that
#: failed to parse, a script cannot spin the parsers without end.
UPLOAD_ATTEMPTS_PER_UPLOAD = 3
#: Waitlist sign-ups per address per hour.
WAITLIST_PER_HOUR_PER_IP = 5
#: Room for the form fields and multipart boundaries on top of the files.
FORM_OVERHEAD_BYTES = 1 << 20
#: How long a PDF download waits for a free render slot before the busy
#: page: ten customers downloading at once (a render takes 4-8 s, two run at
#: a time) all get their PDF instead of an error.
PDF_WAIT_SECONDS = 60.0
#: Finished PDFs kept in memory, so a double click or a second download of
#: the same report does not render again.
PDF_CACHE_SIZE = 16
#: Strategy summaries one account may render in the window below; a cached
#: one does not count. They share the report PDFs' render slots.
#: The page's "skip to content" link, which a PDF does not need.
_SKIP_LINK = re.compile(r"<a class='skip' href='#main'>[^<]*</a>")
#: Why an account's upload became a preview although its free full report is
#: unused: the file or the browser already had one, or the network's month is full.
WELCOME_REFUSALS = ("file", "device", "network")
STRATEGY_PDFS_PER_WINDOW = 10
STRATEGY_PDF_WINDOW = timedelta(minutes=10)
#: How many upload fields ``POST /audits`` takes.
UPLOAD_FIELDS = 7
#: The fields that may carry a platform report, and how much larger than
#: ``max_upload_bytes`` they may be. The MT5 optimisation XML is one: about
#: 900 bytes a pass, so 5 MB stopped at some 5,500 passes, fewer than a
#: common genetic run.
REPORT_FIELDS = frozenset({"equity", "report", "live", "optimization"})
#: Bytes a pass takes in an MT5 optimisation export, for the size refusal.
OPTIMIZATION_PASS_BYTES = 900
REPORT_SIZE_FACTOR = 2

_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?$")
#: Query values that are secrets: the owner token and an access code.
_SECRET_QUERY = re.compile(r"((?:^|[?&])(?:token|code)=)[^&\s\"]*", re.IGNORECASE)

#: The file names as the error sentences use them.
UPLOAD_NAMES: dict[str, dict[str, str]] = {
    "equity": {"es": "de la curva de equity", "en": "equity"},
    "trades": {"es": "de operaciones", "en": "trades"},
    "benchmark": {"es": "del benchmark", "en": "benchmark"},
    "variants": {"es": "de variantes", "en": "variants"},
    "report": {"es": "del informe", "en": "report"},
    "optimization": {"es": "de optimización", "en": "optimisation"},
    "live": {"es": "de la cuenta real", "en": "live statement"},
}
for _what, _name in FILES_PT.items():
    if _what in UPLOAD_NAMES:
        UPLOAD_NAMES[_what]["pt"] = _name


def _megabytes(size: int) -> str:
    """A byte limit as a customer reads it: 8 MB, 1.5 MB, 500 KB."""
    if size >= 1_000_000:
        return f"{size / 1_000_000:.1f}".rstrip("0").rstrip(".") + " MB"
    return f"{max(size // 1000, 1)} KB"


def message(key: str, locale: str, **values: Any) -> str:
    """The service's own message ``key`` in ``locale`` (Spanish by default)."""
    texts = MESSAGES[key]
    text = texts.get(locale) or texts.get(link_locale(locale)) or texts["es"]
    return text.format(**values)


def redact_secrets(text: str) -> str:
    """``text`` with the value of every ``token=`` and ``code=`` query parameter
    replaced, so an access log line never carries an owner token."""
    return _SECRET_QUERY.sub(r"\1[redacted]", text)


def shorten_client_address(address: str) -> str:
    """``address`` (uvicorn's ``host:port``) without its port and host part:
    the last IPv4 octet, or all but the first three IPv6 groups, become 0.
    Enough to read traffic by network; not enough to name a customer."""
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    for candidate in (address.rsplit(":", 1)[0], address):
        try:
            ip = ipaddress.ip_address(candidate.strip("[]"))
            break
        except ValueError:
            continue
    if ip is None:
        return "-"
    prefix = 24 if ip.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False).network_address)


class RedactSecretsFilter(logging.Filter):
    """Access-log filter: uvicorn logs the full path, query string included,
    and the client's full address first; both are cut down here."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            args = [redact_secrets(arg) if isinstance(arg, str) else arg for arg in record.args]
            if record.name == "uvicorn.access" and args and isinstance(args[0], str):
                args[0] = shorten_client_address(args[0])
            record.args = tuple(args)
        record.msg = redact_secrets(str(record.msg))
        return True


def looks_like_platform_report(filename: str | None, data: bytes) -> bool:
    """True for an HTML or XLSX platform report (not an equity CSV).

    MetaTrader saves its HTML reports as UTF-16, so the head is decoded by
    its byte-order mark before looking for the HTML tag.
    """
    name = (filename or "").lower()
    head = data[:4096]
    if head.startswith(b"PK\x03\x04") or name.endswith(".xlsx"):
        # A workbook is a report only when an importer knows it; a sheet
        # with a date and an equity column stays an equity curve.
        return detect_format(data) is not None
    if name.endswith((".htm", ".html")):
        return True
    if head[:2] in (b"\xff\xfe", b"\xfe\xff"):
        text = head.decode("utf-16", errors="ignore")
    else:
        text = head.decode("utf-8", errors="ignore")
    text = text.lstrip("\ufeff \r\n\t").lower()
    return text.startswith(("<!doctype html", "<html")) or "<html" in text[:512]


def uvicorn_log_config() -> dict[str, Any]:
    """uvicorn's default logging with the access log redacted."""
    import copy

    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    config.setdefault("filters", {})["redact_secrets"] = {"()": RedactSecretsFilter}
    for handler in config["handlers"].values():
        handler.setdefault("filters", []).append("redact_secrets")
    return config


class AttemptLog:
    """Attempts per key in a sliding hour, in memory and thread-safe.

    Per process, like the service itself (one Railway replica). Keys whose
    attempts have all expired are dropped, so the table cannot grow without
    bound.
    """

    def __init__(self, window: timedelta = timedelta(hours=1)) -> None:
        self.window = window
        self._log: dict[str, list[datetime]] = {}
        self._lock = threading.Lock()
        self._next_sweep: datetime | None = None

    def hit(self, key: str, now: datetime) -> int:
        """Record an attempt; return how many came before it in the window."""
        since = now - self.window
        with self._lock:
            if self._next_sweep is None or now >= self._next_sweep:
                self._log = {
                    k: kept for k, v in self._log.items() if (kept := [t for t in v if t >= since])
                }
                self._next_sweep = now + self.window
            recent = [at for at in self._log.get(key, []) if at >= since]
            before = len(recent)
            recent.append(now)
            self._log[key] = recent
        return before

    def count(self, key: str, now: datetime) -> int:
        """How many attempts ``key`` has in the window, without recording one."""
        since = now - self.window
        with self._lock:
            return sum(1 for at in self._log.get(key, []) if at >= since)

    def __len__(self) -> int:
        with self._lock:
            return len(self._log)


class StoredAttemptLog:
    """:class:`AttemptLog` kept in the database, so a deploy does not reset it.

    Used for the limits that guard passwords (sign-in, sign-up, the owner
    panel); ``name`` keeps each limit's keys apart.
    """

    def __init__(self, store: Any, name: str, window: timedelta = timedelta(hours=1)) -> None:
        self.store = store
        self.name = name
        self.window = window

    def hit(self, key: str, now: datetime) -> int:
        return int(self.store.attempt_hit(f"{self.name}|{key}", now, since=now - self.window))

    def count(self, key: str, now: datetime) -> int:
        return int(self.store.attempt_count(f"{self.name}|{key}", since=now - self.window))


async def _take_slot(slots: Any, wait_seconds: float) -> bool:
    """Take one of ``slots`` (an anyio ``CapacityLimiter``), waiting at most
    ``wait_seconds``; ``False`` when none came free in time."""
    import anyio

    try:
        slots.acquire_nowait()
        return True
    except anyio.WouldBlock:
        pass
    if wait_seconds <= 0:
        return False
    with anyio.move_on_after(wait_seconds):
        await slots.acquire()
        return True
    return False


class BodyTooLarge(Exception):
    """The request body passed the service's limit while it was being read."""


def request_body_limit(max_upload_bytes: int) -> int:
    """The largest ``POST /audits`` body: every field at its limit (the
    fields that may carry a platform report take ``REPORT_SIZE_FACTOR``
    times it, since MetaTrader writes UTF-16) plus the form overhead."""
    extra = max_upload_bytes * (REPORT_SIZE_FACTOR - 1) * len(REPORT_FIELDS)
    return max_upload_bytes * UPLOAD_FIELDS + extra + FORM_OVERHEAD_BYTES


# The report check takes one file of at most ``check.MAX_CHECK_BYTES``, so its
# body limit is that plus the form overhead: a bigger upload is refused before
# it is spooled, not after.
CHECK_PATHS = {"/comprobar": "es", "/check": "en", "/pt/comprovar": "pt"}


def check_body_limit() -> int:
    return check_lib.MAX_CHECK_BYTES + FORM_OVERHEAD_BYTES


class HeadAsGetMiddleware:
    """Answer ``HEAD`` like ``GET`` with the body left out.

    Link-preview bots (WhatsApp, Slack, Facebook) and uptime monitors often
    probe a page with ``HEAD`` first; FastAPI routes answer only ``GET``, so
    they got a 405 and could drop the preview.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") != "HEAD":
            await self.app(scope, receive, send)
            return

        async def send_headers_only(message: Any) -> None:
            if message.get("type") == "http.response.body":
                message = {**message, "body": b""}
            await send(message)

        await self.app({**scope, "method": "GET"}, receive, send_headers_only)


class BodyLimitMiddleware:
    """Refuse a request body over ``limit`` bytes before anything spools it.

    Starlette writes every multipart file to a temporary file before the
    route runs, so the per-file limit in the route comes too late to protect
    the disk. A declared ``Content-Length`` over the limit is refused at
    once; a chunked body is counted as it streams and cut off at the limit.
    ``path_limits`` gives a path its own, smaller limit.
    """

    def __init__(
        self,
        app: Any,
        *,
        limit: int,
        reject: Callable[[Any], Any],
        path_limits: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        self.limit = limit
        self.reject = reject
        self.path_limits = dict(path_limits or {})

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.path_limits.get(scope.get("path", ""), self.limit)
        declared = dict(scope.get("headers") or []).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > limit
            except ValueError:
                too_big = True
            if too_big:
                await self.reject(scope)(scope, receive, send)
                return
        seen = 0
        started = False
        exceeded = False

        async def counted_receive() -> Any:
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    exceeded = True
                    raise BodyTooLarge
            return message

        async def tracked_send(message: Any) -> None:
            nonlocal started
            if exceeded:
                # Whatever the app answers to a cut-off body is replaced below.
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted_receive, tracked_send)
        except Exception:
            # The framework may wrap the cut-off in its own error; only an
            # error unrelated to the limit is re-raised.
            if not exceeded:
                raise
        if exceeded and not started:
            await self.reject(scope)(scope, receive, send)


class UploadTooLarge(Exception):
    def __init__(self, what: str) -> None:
        super().__init__(what)
        self.what = what


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def token_matches(token_hash: str, token: str | None) -> bool:
    if not token:
        return False
    return hmac.compare_digest(token_hash, hash_token(token))


def verify_stripe_signature(
    payload: bytes,
    header: str | None,
    secret: str,
    *,
    tolerance_s: int = STRIPE_TOLERANCE_SECONDS,
    now: float | None = None,
) -> bool:
    """Stripe's documented scheme: ``t=<ts>,v1=<hex>``; HMAC-SHA256 over
    ``"<ts>.<payload>"`` with the endpoint secret; reject stale timestamps."""
    if not header or not secret:
        return False
    timestamp = ""
    signatures: list[str] = []
    for part in header.split(","):
        key, _, value = part.strip().partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1":
            signatures.append(value)
    if not timestamp or not signatures:
        return False
    try:
        stamp = int(timestamp)
    except ValueError:
        return False
    current = time.time() if now is None else now
    if abs(current - stamp) > tolerance_s:
        return False
    expected = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in signatures)


def sign_stripe_payload(payload: bytes, secret: str, *, timestamp: int) -> str:
    """Build a ``Stripe-Signature`` header; used by tests and local tooling."""
    digest = hmac.new(
        secret.encode("utf-8"), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return f"t={timestamp},v1={digest}"


def client_ip(
    forwarded_for: str | None, socket_host: str | None, *, trusted_proxy_hops: int
) -> str:
    """The address the rate limit counts.

    With no trusted proxy the header is client-controlled and ignored. Each
    trusted proxy appends the address it received the request from, so the
    N-th entry from the right is the first one a trusted hop wrote; anything
    to its left is whatever the client chose to send. When the header is
    shorter than the hop count, the request did not come through the
    expected proxies and the socket address is used.
    """
    fallback = (socket_host or "unknown")[:64]
    if trusted_proxy_hops <= 0 or not forwarded_for:
        return fallback
    entries = [entry.strip() for entry in forwarded_for.split(",")]
    if len(entries) < trusted_proxy_hops:
        return fallback
    chosen = entries[-trusted_proxy_hops]
    return chosen[:64] if chosen else fallback


def _client_ip(request: Any, trusted_proxy_hops: int) -> str:
    return client_ip(
        # Repeated headers are one list per RFC 9110; the proxy's entry is last.
        ", ".join(request.headers.getlist("x-forwarded-for")),
        request.client.host if request.client else None,
        trusted_proxy_hops=trusted_proxy_hops,
    )


_COMMIT_SHA = re.compile(r"^[0-9a-f]{7,40}$")


def deployed_version(environ: Any = None) -> str:
    """The short commit this process runs, from ``RAILWAY_GIT_COMMIT_SHA``
    (set by Railway on every deploy), or ``unknown`` off Railway."""
    env = os.environ if environ is None else environ
    sha = str(env.get("RAILWAY_GIT_COMMIT_SHA", "")).strip().lower()
    return sha[:7] if _COMMIT_SHA.match(sha) else "unknown"


def _wants_json(request: Any) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _positive_or_none(value: str) -> float | None:
    """A form number that is optional: blank means not declared."""
    text = value.strip().replace(",", ".")
    if not text:
        return None
    number = float(text)  # ValueError reaches the caller as an invalid field
    if not number > 0:
        raise ValueError("must be positive")
    return number


def _valid_email(value: str) -> bool:
    value = value.strip()
    if any(char.isspace() or not char.isprintable() for char in value):
        return False
    return 3 <= len(value) <= _EMAIL_MAX and "@" in value and "." in value.rsplit("@", 1)[-1]


def _sentence(text: str) -> str:
    """An error message as a sentence: capitalised and ending in a full stop."""
    text = text.strip()
    if not text:
        return text
    text = text[0].upper() + text[1:]
    return text if text[-1] in ".!?" else text + "."


#: Where the sample report's PDF is served, per language.
SAMPLE_PDF_PATHS = {"es": "/ejemplo.pdf", "en": "/sample.pdf", "pt": "/pt/exemplo.pdf"}
#: The sample PDF's name inside the file and on download.
SAMPLE_PDF_NAMES = {"es": "ejemplo", "en": "sample", "pt": "exemplo"}


def create_app(settings: AuditSettings | None = None, store: Store | None = None) -> Any:
    try:
        import anyio
        from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import (
            HTMLResponse,
            JSONResponse,
            PlainTextResponse,
            RedirectResponse,
            Response,
        )
        from starlette.concurrency import run_in_threadpool
        from starlette.exceptions import HTTPException as StarletteHTTPException
    except ImportError as exc:
        raise ImportError(REQUIRE_WEB) from exc

    cfg = settings or AuditSettings.from_env()
    market_data = MarketData() if cfg.public_data else None
    if market_data is not None:
        market_data.warm()
    # Checked once: WeasyPrint needs Pango, which a bare install may lack.
    pdf_ok = pdf_lib.available()
    db = store or make_store(cfg.database_url)
    retention = RetentionWorker(db, retention_days=cfg.retention_days)
    visits = funnel.VisitCounter(db)

    @contextlib.asynccontextmanager
    async def lifespan(_: Any) -> AsyncIterator[None]:
        if cfg.auto_purge:
            retention.start()
        visits.start()
        try:
            yield
        finally:
            retention.stop()
            visits.stop()

    app = FastAPI(
        title=BRAND,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    app.state.store = db
    app.state.retention = retention
    app.state.visits = visits
    app.state.checkout_factory = payments.stripe_checkout
    app.state.session_lookup = payments.stripe_session
    upload_attempts = AttemptLog()
    redeem_attempts = AttemptLog()
    waitlist_attempts = AttemptLog()
    panel_failures = StoredAttemptLog(db, "panel")
    check_attempts = AttemptLog()
    card_lookups = AttemptLog()
    failed_card_sessions = AttemptLog()
    app.state.attempt_logs = (upload_attempts, redeem_attempts, waitlist_attempts, panel_failures)
    # Waiting for a slot happens in the event loop (an await, not a blocked
    # thread), so a queue of uploads never starves the pages that share the
    # thread pool.
    audit_slots = anyio.CapacityLimiter(cfg.max_concurrent_audits)
    app.state.audit_slots = audit_slots
    report_upload_bytes = cfg.max_upload_bytes * REPORT_SIZE_FACTOR
    body_limit = request_body_limit(cfg.max_upload_bytes)

    def _secure(response: Any, *, path: str = "") -> Any:
        """The headers every response carries, errors included."""
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        if cfg.base_url.startswith("https://"):
            response.headers["Strict-Transport-Security"] = HSTS
        if "Cache-Control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        if path.startswith(DISALLOWED_PATHS) or response.status_code >= 400:
            response.headers["X-Robots-Tag"] = NOINDEX
        return response

    def _scope_locale(scope: Any) -> str:
        query = scope.get("query_string", b"").decode("latin-1")
        match = re.search(r"(?:^|&)lang=(es|en|pt)(?:&|$)", query)
        return match.group(1) if match else "es"

    def _too_large_response(scope: Any) -> Any:
        path = scope.get("path", "")
        if path in CHECK_PATHS:
            # The check page keeps its own form and message, in the page's language.
            check_locale = CHECK_PATHS[path]
            too_large = check_lib.COPY[check_locale]["too_large"]
            form = check_lib.check_form(check_locale, error=too_large)
            request = Request(scope)
            page = check_page(form, locale=check_locale, base_url=_site_url(request))
            check_response = HTMLResponse(guard_page(page), status_code=413)
            check_response.headers["Connection"] = "close"
            return _secure(check_response, path=path)
        locale = _scope_locale(scope)
        text = message("body_too_large", locale, limit=_megabytes(body_limit))
        accept = dict(scope.get("headers") or []).get(b"accept", b"").decode("latin-1")
        response: Any
        if "application/json" in accept:
            response = JSONResponse({"error": text}, status_code=413)
        else:
            response = HTMLResponse(error_page(text, locale=locale), status_code=413)
        response.headers["Connection"] = "close"
        return _secure(response, path=scope.get("path", ""))

    app.add_middleware(
        BodyLimitMiddleware,
        limit=body_limit,
        reject=_too_large_response,
        path_limits=dict.fromkeys(CHECK_PATHS, check_body_limit()),
    )
    app.add_middleware(HeadAsGetMiddleware)

    #: Where a visit counts for the owner's funnel, and in which language.
    visit_paths: dict[str, str] = {path: loc for loc, path in LANDING_PATHS.items()}
    for audience_locale, pages_by_slug in AUDIENCES_BY_PATH.items():
        for audience_slug in pages_by_slug:
            visit_paths[audience_url(audience_slug, audience_locale)] = audience_locale

    def _funnel_visit(request: Request, response: Any) -> None:
        """Count a person's visit to the landing or a case page; remember its tag.

        Only a counter per day, language and tag is kept, in memory until
        the background flush: nothing here waits on the database. A browser
        counts once a day (a cookie holds only the date), and the tag of the
        first listed link it arrives with is kept in a cookie that holds
        nothing else, so an account created later carries it.
        """
        if request.method != "GET" or response.status_code != 200:
            return
        path = request.url.path
        kept = funnel.clean_ref(request.cookies.get(funnel.REF_COOKIE))
        arrived = funnel.clean_ref(request.query_params.get("ref"))
        if arrived and not kept:
            _cookie(response, funnel.REF_COOKIE, arrived, max_age=funnel.REF_DAYS * 86400)
        locale = visit_paths.get(path)
        if locale is None or not funnel.is_person(request.headers.get("user-agent")):
            return
        if request.headers.get("sec-purpose") or request.headers.get("purpose"):
            return  # a prefetch, not a visit
        today = funnel.day_of(datetime.now(UTC))
        if request.cookies.get(funnel.SEEN_COOKIE) == today:
            return  # this browser was already counted today
        _cookie(response, funnel.SEEN_COOKIE, today, max_age=86400)
        # "/" renders Spanish or English; Portuguese lives at /pt.
        if path == "/" and request.query_params.get("lang") in ("es", "en"):
            locale = request.query_params["lang"]
        visits.add(day=today, locale=locale, ref=kept or arrived)

    @app.middleware("http")
    async def no_store(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        _funnel_visit(request, response)
        ok = response.status_code == 200
        if request.url.path.startswith("/static/") and ok:
            response.headers["Cache-Control"] = STATIC_CACHE_CONTROL
        else:
            public = request.url.path.startswith("/v/") and ok
            response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL if public else "no-store"
        return _secure(response, path=request.url.path)

    def _site_url(request: Request) -> str:
        """The public address for absolute links (canonical, previews, sitemap).

        ``AUDIT_BASE_URL`` when it is set; otherwise the address this request
        reached, with ``https`` assumed behind a trusted proxy.
        """
        if cfg.base_url != DEFAULT_BASE_URL:
            return cfg.base_url
        # The Host header is the client's to choose: anything but a plain
        # host name drops the absolute links rather than echoing it.
        if not _HOST.match(request.url.netloc or ""):
            return ""
        base = str(request.base_url).rstrip("/")
        if cfg.trusted_proxy_hops > 0 and base.startswith("http://"):
            base = "https://" + base[len("http://") :]
        return base

    def _locale(value: str | None) -> str:
        return value if value in LOCALES else "es"

    def _error_locale(request: Request) -> str:
        """The language of an error page: ``?lang=``, else Portuguese under ``/pt``."""
        lang = request.query_params.get("lang")
        if lang in REPORT_LOCALES:
            return str(lang)
        path = request.url.path
        return "pt" if path == "/pt" or path.startswith("/pt/") else "es"

    def _html_error(
        request: Request, status: int, message: str, locale: str, *, kind: str = "audit"
    ) -> Response:
        if _wants_json(request):
            return JSONResponse({"error": message}, status_code=status)
        return HTMLResponse(error_page(message, locale=locale, kind=kind), status_code=status)

    def _not_found() -> HTTPException:
        return HTTPException(status_code=404, detail="not_found")

    @app.exception_handler(RequestValidationError)
    async def form_error(request: Request, exc: RequestValidationError) -> Response:
        locale = _error_locale(request)
        return _html_error(request, 400, message("invalid_form", locale), locale)

    @app.exception_handler(Exception)
    async def server_error(request: Request, exc: Exception) -> Response:
        # Logged with the path only: the query string may hold the token.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        locale = _error_locale(request)
        return _secure(
            _html_error(request, 500, message("server_error", locale), locale, kind="server"),
            path=request.url.path,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        # Route errors carry a MESSAGES key as detail; anything else (a
        # FastAPI-generated 404 or 405) is shown as a missing page.
        key = str(exc.detail) if str(exc.detail) in MESSAGES else "page_missing"
        if exc.status_code == 400 and request.url.path.startswith("/webhooks/"):
            return JSONResponse({"error": str(exc.detail)}, status_code=400)
        locale = _error_locale(request)
        kind = "page" if key == "page_missing" else "audit"
        return _html_error(request, exc.status_code, message(key, locale), locale, kind=kind)

    def _field_limit(what: str) -> int:
        return report_upload_bytes if what in REPORT_FIELDS else cfg.max_upload_bytes

    async def _read_limited(upload: UploadFile | None, *, what: str) -> bytes | None:
        if upload is None or not upload.filename:
            return None
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = await upload.read(1 << 16)
            if not chunk:
                break
            size += len(chunk)
            if size > _field_limit(what):
                raise UploadTooLarge(what)
            chunks.append(chunk)
        data = b"".join(chunks)
        return data or None

    def _record_issued(content: bytes, *, audit_id: str, kind: str) -> None:
        """Remember a handed-out file's hash; a failure never blocks the download."""
        try:
            db.record_issued(content, audit_id=audit_id, kind=kind, at=datetime.now(UTC))
        except Exception:  # noqa: BLE001 - the customer still gets the file
            logger.warning("could not record an issued %s file", kind)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "free_mode": cfg.free_mode,
            "stripe_enabled": cfg.stripe_enabled,
            "card_mode": payments.card_mode(cfg),
            "card_via": payments.card_via(cfg),
            "access_codes": cfg.access_codes_enabled,
            "database": cfg.database_kind,
            "legal_configured": cfg.legal_configured,
            "auto_purge": cfg.auto_purge,
            "version": deployed_version(),
        }

    @app.get(PANEL_PATH, response_class=HTMLResponse)
    def panel_login() -> str:
        if not cfg.admin_enabled:
            raise _not_found()
        return login_page()

    @app.post(PANEL_PATH, response_class=HTMLResponse)
    def panel(
        request: Request,
        key: Annotated[str, Form()],
        action: Annotated[str, Form()] = "list",
        credits: Annotated[str, Form()] = "1",
        note: Annotated[str, Form()] = "",
        expires_days: Annotated[str, Form()] = "",
        code_id: Annotated[str, Form()] = "",
        email: Annotated[str, Form(max_length=320)] = "",
    ) -> Response:
        """The owner panel. The key comes in the body on every request, is
        compared in constant time, and wrong keys are limited per address."""
        if not cfg.admin_enabled:
            raise _not_found()
        ip = _client_ip(request, cfg.trusted_proxy_hops)
        now = datetime.now(UTC)
        if panel_failures.count(ip, now) >= MAX_FAILED_LOGINS_PER_HOUR:
            return HTMLResponse(login_page(error="too_many"), status_code=429)
        if not hmac.compare_digest(key.encode(), cfg.admin_key.encode()):
            panel_failures.hit(ip, now)
            return HTMLResponse(login_page(error="wrong_key"), status_code=403)
        new_code = flash = error = ""
        if action == "create":
            try:
                total = int(credits)
                days = int(expires_days) if expires_days.strip() else None
            except ValueError:
                total, days = 0, None
            clean_note = note.strip()
            if (
                1 <= total <= MAX_CREDITS
                and len(clean_note) <= MAX_NOTE_CHARS
                # A NUL or control character cannot be stored in PostgreSQL.
                and clean_note.isprintable()
                and (days is None or 1 <= days <= MAX_EXPIRES_DAYS)
            ):
                new_code, _ = db.create_access_code(
                    credits=total, note=clean_note, at=now, expires_days=days
                )
            else:
                error = "invalid"
        elif action == "disable":
            flash = "disabled" if db.disable_access_code(code_id.strip()[:64]) else ""
            error = "" if flash else "not_found"
        reset_link = ""
        if action == "reset":
            account = db.find_account(acct.normalise_email(email))
            if account is None:
                error = "reset_unknown"
            else:
                secret = acct.new_secret()
                db.create_reset(
                    account.id,
                    token_sha256=acct.hash_secret(secret),
                    at=now,
                    hours=acct.RESET_HOURS,
                )
                reset_path = account_pages.path("reset", account.locale)
                reset_link = f"{_site_url(request)}{reset_path}?token={secret}"
        visits.flush()
        return HTMLResponse(
            panel_page(
                key=key,
                codes=db.list_access_codes(),
                refused=db.list_refused_payments(),
                new_code=new_code,
                flash=flash,
                error=error,
                reset_link=reset_link,
                accounts=db.count_accounts(),
                funnel=funnel_section(
                    funnel.build(db.funnel_events(funnel.since_day(now))),
                    days=funnel.FUNNEL_DAYS,
                    example=f"{_site_url(request)}{audience_url('retos-prop-firm', 'es')}?ref=f6",
                ),
            )
        )

    @app.get("/static/{name:path}")
    def static(name: str) -> Response:
        """Fonts and the enhancement script, looked up in a fixed allow-list."""
        found = static_file(name)
        if found is None:
            raise _not_found()
        content, media_type = found
        return Response(content=content, media_type=media_type)

    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots(request: Request) -> str:
        return robots_txt(_site_url(request))

    @app.get("/sitemap.xml")
    def sitemap(request: Request) -> Response:
        return Response(content=sitemap_xml(_site_url(request)), media_type="application/xml")

    @app.get("/", response_class=HTMLResponse)
    def index(
        request: Request,
        lang: str | None = None,
        joined: int = 0,
        error: str | None = None,
        extras: int = 0,
    ) -> str:
        return _landing(request, _locale(lang), joined=joined, error=error, extras=extras)

    def _landing(
        request: Request, locale: str, *, joined: int = 0, error: str | None = None, extras: int = 0
    ) -> str:
        # Only known codes are shown, so the query string cannot inject text.
        shown = message("invalid_email", locale) if error == "email" else None
        return landing(
            locale=locale,
            free_mode=cfg.free_mode,
            price_usd=cfg.price_usd,
            joined=bool(joined),
            error=shown,
            access_codes=cfg.access_codes_enabled,
            card_payments=cfg.card_public,
            contact_url=cfg.contact_url,
            retention_days=cfg.retention_days,
            base_url=_site_url(request),
            pack_price_usd=cfg.pack_price_usd,
            extras_open=bool(extras),
            signed_in=_session(request) is not None,
            operator=(cfg.operator_name, cfg.operator_address),
        )

    @app.get("/en", response_class=HTMLResponse)
    def index_en(request: Request) -> str:
        """A short address to share with English-speaking traders."""
        return index(request, lang="en")

    @app.get("/pt", response_class=HTMLResponse)
    def index_pt(
        request: Request, joined: int = 0, error: str | None = None, extras: int = 0
    ) -> str:
        """The landing in Portuguese; the pages it links to that are not
        translated yet (report, account, sample, terms) open in English."""
        return _landing(request, "pt", joined=joined, error=error, extras=extras)

    @app.post("/waitlist")
    def waitlist(
        request: Request, email: Annotated[str, Form()], lang: Annotated[str, Form()] = "es"
    ) -> Response:
        # The Portuguese landing comes back to itself; its error page is in English.
        home = "/pt?" if lang == "pt" else f"/?lang={_locale(lang)}&"
        locale = "en" if lang == "pt" else _locale(lang)
        ip = _client_ip(request, cfg.trusted_proxy_hops)
        if waitlist_attempts.hit(ip, datetime.now(UTC)) >= WAITLIST_PER_HOUR_PER_IP:
            return _html_error(request, 429, message("rate_limited", locale), locale)
        if not _valid_email(email):
            return RedirectResponse(f"{home}error=email", status_code=303)
        db.add_waitlist(email, at=datetime.now(UTC))
        return RedirectResponse(f"{home}joined=1#news", status_code=303)

    # -- customer accounts -------------------------------------------------
    secure_cookies = cfg.base_url.startswith("https://")
    signin_failures = StoredAttemptLog(db, "signin")
    signin_email_failures = StoredAttemptLog(db, "signin_email")
    signin_ip_failures = StoredAttemptLog(db, "signin_ip")
    signup_attempts = StoredAttemptLog(db, "signup")
    account_actions = AttemptLog()
    strategy_pdf_renders = AttemptLog(window=STRATEGY_PDF_WINDOW)
    strategy_pdf_cache: OrderedDict[tuple[Any, ...], bytes] = OrderedDict()
    strategy_pdf_lock = threading.Lock()

    def _session(request: Request) -> tuple[Any, str, str] | None:
        """``(account, csrf, session hash)`` for a signed-in request, else ``None``."""
        token = request.cookies.get(acct.SESSION_COOKIE) or ""
        if not token or len(token) > 128:
            return None
        digest = acct.hash_secret(token)
        found = db.session_account(digest, datetime.now(UTC))
        return (found[0], found[1], digest) if found else None

    def _cookie(response: Any, name: str, value: str, *, max_age: int) -> None:
        response.set_cookie(
            name,
            value,
            max_age=max_age,
            httponly=True,
            secure=secure_cookies,
            samesite="lax",
            path="/",
        )

    def _anon_csrf(request: Request) -> str:
        """The double-submit token for forms shown before sign-in."""
        current = request.cookies.get(acct.CSRF_COOKIE) or ""
        return current if 20 <= len(current) <= 128 else acct.new_secret()

    def _anon_page(page: str, csrf: str, status: int = 200) -> Response:
        response = HTMLResponse(page, status_code=status)
        _cookie(response, acct.CSRF_COOKIE, csrf, max_age=2 * 3600)
        return response

    def _anon_ok(request: Request, field: str) -> bool:
        return acct.same_secret(request.cookies.get(acct.CSRF_COOKIE), field)

    def _start_session(response: Any, account: Any) -> None:
        token = acct.new_secret()
        now = datetime.now(UTC)
        db.create_session(
            account.id,
            token_sha256=acct.hash_secret(token),
            csrf=acct.new_secret(),
            at=now,
            days=acct.SESSION_DAYS,
        )
        _cookie(response, acct.SESSION_COOKIE, token, max_age=acct.SESSION_DAYS * 86400)
        response.delete_cookie(acct.CSRF_COOKIE, path="/")

    def _account_redirect(locale: str, done: str = "") -> Response:
        target = account_pages.path("account", locale) + (f"?done={done}" if done else "")
        return RedirectResponse(target, status_code=303)

    def _signin_redirect(locale: str, *, done: str = "", next_path: str = "") -> Response:
        query = []
        if done:
            query.append(f"done={done}")
        if next_path:
            query.append("next=" + quote(next_path, safe=""))
        target = account_pages.path("signin", locale) + ("?" + "&".join(query) if query else "")
        return RedirectResponse(target, status_code=303)

    def _account_email(account_id: str) -> str:
        found = db.get_account(account_id)
        return found.email if found is not None else ""

    def _account_locale(path_locale: str, lang: str | None) -> str:
        # The account screens exist in Portuguese too (``/pt/conta``).
        return lang if lang in account_pages.LANGUAGES else path_locale

    #: Flash keys a redirect may name; anything else in ``done`` is ignored.
    signin_flashes = ("signed_out", "deleted", "reset_done")
    account_flashes = ("welcome", "code_linked", "password_changed", "filed")
    account_errors = (
        "code_already",
        "code_other",
        "code_unknown",
        "wrong",
        "csrf",
        "too_many",
        "compare_pick",
        "password_common",
        "password_short",
        "file_bad",
        "strategy_full",
    )

    def _referrals_on() -> bool:
        # The reward is paid when the invitee's free first report exists.
        return not cfg.free_mode and acct.WELCOME_FULL_REPORT

    def _note_invite(request: Request, account_id: str, token: str, now: datetime) -> None:
        """Note who invited a new account; a failure never breaks the sign-up."""
        try:
            inviter = db.inviter_for_token(token)
            signed_in = _session(request)
            if inviter is None or (signed_in is not None and signed_in[0].id == inviter):
                return  # the inviter's own browser, still signed in
            device = request.cookies.get(acct.DEVICE_COOKIE) or ""
            db.record_referral(
                account_id,
                inviter,
                device_sha256=acct.hash_secret(device) if 0 < len(device) <= 128 else "",
                at=now,
            )
        except Exception:  # noqa: BLE001 - an invite never breaks a sign-up
            logger.warning("could not note an invite")

    def _invite(token: str) -> str:
        """An invite token that names an account, else ``""``."""
        token = token.strip()[:40]
        return token if token and db.inviter_for_token(token) else ""

    def _reward_invite(account_id: str, device_sha256: str, ip: str, now: datetime) -> None:
        """Credit whoever invited this account, now that its free report exists."""
        try:
            db.reward_referral(
                account_id,
                device_sha256=device_sha256,
                client_ip=ip,
                at=now,
                credits=acct.REFERRAL_CREDITS,
                monthly_cap=acct.REFERRAL_MONTHLY_CAP,
            )
        except Exception:  # noqa: BLE001 - the customer's report comes first
            logger.warning("could not settle an invite")

    def _signup_get(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request, lang: str | None = None, next: str = "", invita: str = ""
        ) -> Response:
            locale = _account_locale(path_locale, lang)
            if _session(request):
                return _account_redirect(locale)
            csrf = _anon_csrf(request)
            page = account_pages.signup_page(
                retention_days=cfg.retention_days,
                locale=locale,
                csrf=csrf,
                next_path=acct.safe_next(next),
                invite=_invite(invita) if _referrals_on() else "",
            )
            return _anon_page(page, csrf)

        return handler

    def _signup_post(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            email: Annotated[str, Form(max_length=320)] = "",
            password: Annotated[str, Form(max_length=1024)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            next: Annotated[str, Form(max_length=1000)] = "",
            invite: Annotated[str, Form(max_length=40)] = "",
            lang: str | None = None,
        ) -> Response:
            locale = _account_locale(path_locale, lang)
            next_path = acct.safe_next(next)
            clean = acct.normalise_email(email)
            new_csrf = _anon_csrf(request)
            invite = _invite(invite) if _referrals_on() else ""

            def again(error: str, status: int) -> Response:
                page = account_pages.signup_page(
                    retention_days=cfg.retention_days,
                    locale=locale,
                    csrf=new_csrf,
                    error=error,
                    email=clean if acct.valid_email(clean) else "",
                    next_path=next_path,
                    invite=invite,
                )
                return _anon_page(page, new_csrf, status)

            if not _anon_ok(request, csrf):
                return again("csrf", 400)
            ip = _client_ip(request, cfg.trusted_proxy_hops)
            now = datetime.now(UTC)
            # Counted per network: an IPv6 /64 is one household or server.
            if signup_attempts.hit(acct.network_address(ip), now) >= acct.MAX_SIGNUPS_PER_HOUR:
                return again("too_many", 429)
            if not acct.valid_email(clean):
                return again("email_bad", 400)
            problem = acct.password_problem(password, email=clean)
            if problem:
                return again(problem, 400)
            account = db.create_account(
                email=clean, password_hash=acct.hash_password(password), locale=locale, at=now
            )
            if account is None:
                return again("taken", 409)
            if invite:
                _note_invite(request, account.id, invite, now)
            ref = funnel.clean_ref(request.cookies.get(funnel.REF_COOKIE))
            if ref:
                try:
                    db.set_account_ref(account.id, ref, at=now)
                except Exception:  # noqa: BLE001 - the account and its session come first
                    logger.warning("could not keep a sign-up tag")
            if next_path:
                response: Response = RedirectResponse(next_path, status_code=303)
            else:
                response = _account_redirect(locale, "welcome")
            _start_session(response, account)
            return response

        return handler

    def _signin_get(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request, lang: str | None = None, next: str = "", done: str = ""
        ) -> Response:
            locale = _account_locale(path_locale, lang)
            next_path = acct.safe_next(next)
            if _session(request):
                return (
                    RedirectResponse(next_path, status_code=303)
                    if next_path
                    else _account_redirect(locale)
                )
            csrf = _anon_csrf(request)
            page = account_pages.signin_page(
                locale=locale,
                csrf=csrf,
                flash=done if done in signin_flashes else "",
                next_path=next_path,
            )
            return _anon_page(page, csrf)

        return handler

    def _signin_post(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            email: Annotated[str, Form(max_length=320)] = "",
            password: Annotated[str, Form(max_length=1024)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            next: Annotated[str, Form(max_length=1000)] = "",
            lang: str | None = None,
        ) -> Response:
            locale = _account_locale(path_locale, lang)
            next_path = acct.safe_next(next)
            clean = acct.normalise_email(email)
            new_csrf = _anon_csrf(request)

            def again(error: str, status: int) -> Response:
                page = account_pages.signin_page(
                    locale=locale,
                    csrf=new_csrf,
                    error=error,
                    email=clean if acct.valid_email(clean) else "",
                    next_path=next_path,
                )
                return _anon_page(page, new_csrf, status)

            if not _anon_ok(request, csrf):
                return again("csrf", 400)
            ip = _client_ip(request, cfg.trusted_proxy_hops)
            now = datetime.now(UTC)
            # Keyed on (address, e-mail) so that failures from elsewhere never
            # lock the real owner out; the per-address and per-e-mail ceilings
            # are higher and only slow wide guessing. The per-e-mail ceiling
            # stops only an address that has already failed on this e-mail
            # (SIGNIN_TRIES_PAST_EMAIL_CEILING), so someone who knows a customer's
            # e-mail cannot lock the customer out from another network.
            pair = f"{ip}|{clean}"
            own_failures = signin_failures.count(pair, now)
            if (
                own_failures >= acct.MAX_FAILED_SIGNINS_PER_HOUR
                or signin_ip_failures.count(ip, now) >= acct.MAX_FAILED_SIGNINS_PER_IP
                or (
                    own_failures >= acct.SIGNIN_TRIES_PAST_EMAIL_CEILING
                    and signin_email_failures.count(clean, now) >= acct.MAX_FAILED_SIGNINS_PER_EMAIL
                )
            ):
                return again("too_many", 429)
            found = db.account_with_hash(clean) if acct.valid_email(clean) else None
            if found is None:
                acct.burn_time(password)
                ok = False
            else:
                ok = acct.verify_password(found[1], password)
            if not ok or found is None:
                signin_failures.hit(pair, now)
                signin_ip_failures.hit(ip, now)
                signin_email_failures.hit(clean, now)
                return again("wrong", 401)
            db.purge_sessions(now)
            if next_path:
                response: Response = RedirectResponse(next_path, status_code=303)
            else:
                response = _account_redirect(found[0].locale if lang is None else locale)
            _start_session(response, found[0])
            return response

        return handler

    def _signout_post(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            locale = _account_locale(path_locale, lang)
            session = _session(request)
            if session is None:
                return _signin_redirect(locale)
            if not acct.same_secret(session[1], csrf):
                return _account_redirect(locale)
            db.delete_session(session[2])
            response = _signin_redirect(locale, done="signed_out")
            response.delete_cookie(acct.SESSION_COOKIE, path="/")
            return response

        return handler

    def _account_get(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request, lang: str | None = None, done: str = "", error: str = ""
        ) -> Response:
            locale = _account_locale(path_locale, lang)
            session = _session(request)
            if session is None:
                return _signin_redirect(locale, next_path=account_pages.path("account", locale))
            account, csrf, _ = session
            now = datetime.now(UTC)
            return HTMLResponse(
                account_pages.account_page(
                    locale=locale,
                    account=account,
                    audits=db.account_audits_list(account.id),
                    codes=db.account_codes_list(account.id),
                    credits=db.account_credits(account.id, now),
                    csrf=csrf,
                    now=now.isoformat().replace("+00:00", "Z"),
                    flash=done if done in account_flashes else "",
                    error=error if error in account_errors else "",
                    access_codes=cfg.access_codes_enabled,
                    card_payments=cfg.stripe_enabled,
                    contact_url=cfg.contact_url,
                    free_mode=cfg.free_mode,
                    price_cents=cfg.price_usd_cents,
                    pack_price_cents=cfg.pack_price_usd_cents,
                    free_left=max(
                        0,
                        acct.FREE_PREVIEWS_PER_MONTH
                        - db.free_previews_since(acct.month_start(now), account_id=account.id),
                    ),
                    free_limit=0 if cfg.free_mode else acct.FREE_PREVIEWS_PER_MONTH,
                    retention_days=cfg.retention_days,
                    welcome=(
                        ""
                        if cfg.free_mode or not acct.WELCOME_FULL_REPORT
                        else ("used" if db.welcome_used(account.id) else "available")
                    ),
                    strategies=db.list_strategies(account.id),
                    invite=(
                        account_pages.InviteView(
                            link=(
                                f"{_site_url(request)}{account_pages.path('signup', locale)}"
                                f"?{acct.INVITE_PARAM}={db.invite_token(account.id, at=now)}"
                            ),
                            summary=db.invite_summary(account.id, now),
                            credits=acct.REFERRAL_CREDITS,
                            monthly_cap=acct.REFERRAL_MONTHLY_CAP,
                        )
                        if _referrals_on()
                        else None
                    ),
                )
            )

        return handler

    def _account_data(path_locale: str) -> Callable[..., Response]:
        def handler(request: Request, lang: str | None = None) -> Response:
            # "Descargar mis datos": the signed-in account's own rows only,
            # read-only (a GET), never stored or cached on the way.
            locale = _account_locale(path_locale, lang)
            session = _session(request)
            if session is None:
                return _signin_redirect(locale, next_path=account_pages.path("account", locale))
            if _cross_site(request):
                # Another site cannot make the browser fetch the file.
                return RedirectResponse(account_pages.path("account", locale), status_code=303)
            data = db.account_export(session[0].id)
            if data is None:
                raise _not_found()
            now = datetime.now(UTC)
            payload = {
                "service": BRAND,
                "exported_at": now.isoformat().replace("+00:00", "Z"),
                "not_included": (
                    "Your password (kept only as a scrypt hash), session and reset tokens and "
                    "report link tokens (kept only as hashes) and card details (never received: "
                    "card payments go through Stripe)."
                ),
                "retention_days_for_unpaid_reports_and_ips": cfg.retention_days,
                **data,
            }
            body = json.dumps(payload, ensure_ascii=False, indent=2)
            name = f"{BRAND.lower()}-data-{now:%Y%m%d}.json"
            return Response(
                body,
                media_type="application/json; charset=utf-8",
                headers={
                    "Content-Disposition": f'attachment; filename="{name}"',
                    "Cache-Control": "no-store",
                    "X-Content-Type-Options": "nosniff",
                },
            )

        return handler

    # -- "Mis estrategias" ---------------------------------------------------
    def _strategy_file_post(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            audit_id: Annotated[str, Form(max_length=64)] = "",
            strategy: Annotated[str, Form(max_length=64)] = "",
            name: Annotated[str, Form(max_length=200)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            checked = _signed_in_action(request, path_locale, lang, csrf)
            if not isinstance(checked, tuple):
                return checked
            account, _, locale, _ = checked
            base = account_pages.path("account", locale)
            now = datetime.now(UTC)
            strategy_id = strategy
            # Only a report on the account's own list can be filed: check it
            # before a new strategy is made, so a refused filing leaves nothing.
            listed = {item.audit_id for item in db.account_audits_list(account.id)}
            if audit_id not in listed:
                return RedirectResponse(f"{base}?error=file_bad#estrategias", 303)
            if strategy in ("", "new") or name.strip():
                if not strategy_name(name):
                    return RedirectResponse(f"{base}?error=file_bad#estrategias", 303)
                strategy_id = db.create_strategy(account.id, name, at=now)
                if not strategy_id:
                    return RedirectResponse(f"{base}?error=strategy_full#estrategias", 303)
            if not db.file_report(account.id, audit_id, strategy_id, at=now):
                return RedirectResponse(f"{base}?error=file_bad#estrategias", 303)
            where = f"{account_pages.strategies_path(locale)}/{strategy_id}"
            return RedirectResponse(where, status_code=303)

        return handler

    def _strategy_get(path_locale: str, *, as_pdf: bool = False) -> Callable[..., Response]:
        def handler(request: Request, strategy_id: str, lang: str | None = None) -> Response:
            locale = _account_locale(path_locale, lang)
            session = _session(request)
            here = f"{account_pages.strategies_path(locale)}/{strategy_id}"
            if session is None:
                return _signin_redirect(locale, next_path=here)
            account, csrf, _ = session
            strategy = db.get_strategy(account.id, strategy_id[:64])
            if strategy is None:
                return HTMLResponse(account_pages.strategy_missing_page(locale), status_code=404)
            listed = {item.audit_id: item for item in db.account_audits_list(account.id)}
            versions = []
            for audit_id in strategy.audit_ids:
                item = listed.get(audit_id)
                if item is None:
                    continue
                record = db.get_audit(audit_id)
                result = (
                    strategies_lib.load_result(record.result_json)
                    if record is not None and not record.purged_at
                    else None
                )
                versions.append((item, result))
            now = datetime.now(UTC)
            # The same strategy, versions, unlocks and day print the same PDF.
            pdf_key = (
                account.id,
                strategy.id,
                strategy.name,
                locale,
                now.date().isoformat(),
                tuple((item.audit_id, item.paid, result is None) for item, result in versions),
            )
            if as_pdf:
                with strategy_pdf_lock:
                    cached = strategy_pdf_cache.get(pdf_key)
                    if cached is not None:
                        strategy_pdf_cache.move_to_end(pdf_key)
                if cached is not None:
                    return _strategy_pdf_answer(cached, strategy.id)
                if strategy_pdf_renders.hit(account.id, now) >= STRATEGY_PDFS_PER_WINDOW:
                    view = link_locale(locale)
                    return _html_error(request, 429, message("pdf_limit", view), view)
            page = guard_page(
                account_pages.strategy_page(
                    locale=locale,
                    csrf=csrf,
                    strategy=strategy,
                    versions=versions,
                    free_mode=cfg.free_mode,
                    printable=as_pdf,
                    generated_at=now.isoformat().replace("+00:00", "Z"),
                )
            )
            if not as_pdf:
                return HTMLResponse(page)
            page = _SKIP_LINK.sub("", page, count=1)
            # The summary as a PDF: the owner's own page, laid out like a report
            # PDF (no network, the shared render slots), never cached.
            view = link_locale(locale)
            try:
                word = {"en": "strategy", "pt": "estratégia"}.get(locale, "estrategia")
                content = pdf_lib.report_pdf(
                    page,
                    audit_id=strategy.id,
                    locale=view,
                    wait_seconds=PDF_WAIT_SECONDS,
                    footer=f"{BRAND} · {word} {strategy.id}",
                )
            except pdf_lib.PdfBusy:
                return _html_error(request, 503, message("pdf_busy", view), view)
            except pdf_lib.PdfUnavailable:
                return _html_error(request, 503, message("pdf_unavailable", view), view)
            with strategy_pdf_lock:
                strategy_pdf_cache[pdf_key] = content
                while len(strategy_pdf_cache) > PDF_CACHE_SIZE:
                    strategy_pdf_cache.popitem(last=False)
            return _strategy_pdf_answer(content, strategy.id)

        return handler

    def _strategy_pdf_answer(content: bytes, strategy_id: str) -> Response:
        name = pdf_lib.filename(f"strategy{strategy_id}")
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "private, no-store",
                "X-Robots-Tag": "noindex",
            },
        )

    def _strategy_action(path_locale: str, action: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            strategy_id: str,
            audit_id: Annotated[str, Form(max_length=64)] = "",
            name: Annotated[str, Form(max_length=200)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            checked = _signed_in_action(request, path_locale, lang, csrf)
            if not isinstance(checked, tuple):
                return checked
            account, _, locale, _ = checked
            here = f"{account_pages.strategies_path(locale)}/{strategy_id}"
            strategy = db.get_strategy(account.id, strategy_id[:64])
            if strategy is None:
                return HTMLResponse(account_pages.strategy_missing_page(locale), status_code=404)
            if action == "remove" and audit_id in strategy.audit_ids:
                db.file_report(account.id, audit_id, "", at=datetime.now(UTC))
            elif action == "rename":
                db.rename_strategy(account.id, strategy.id, name)
            elif action == "delete":
                db.delete_strategy(account.id, strategy.id)
                base = account_pages.path("account", locale)
                return RedirectResponse(f"{base}#estrategias", status_code=303)
            return RedirectResponse(here, status_code=303)

        return handler

    def _account_compare(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            id: Annotated[list[str] | None, Query(max_length=40)] = None,
            lang: str | None = None,
        ) -> Response:
            # Read-only, so a GET: nothing changes, and the reports must be on
            # the signed-in account's own list.
            locale = _account_locale(path_locale, lang)
            session = _session(request)
            base = account_pages.path("account", locale)
            if session is None:
                # Back to this comparison after signing in, not to the list.
                here = request.url.path + (f"?{request.url.query}" if request.url.query else "")
                return _signin_redirect(locale, next_path=here)
            picked = list(dict.fromkeys(id or []))
            mine = {item.audit_id: item for item in db.account_audits_list(session[0].id)}
            ready = {
                audit_id
                for audit_id, item in mine.items()
                if account_pages.comparable(item, free_mode=cfg.free_mode)
            }
            if len(picked) != 2 or not ready.issuperset(picked):
                return RedirectResponse(f"{base}?error=compare_pick", status_code=303)
            results = []
            for audit_id in picked:
                record = db.get_audit(audit_id)
                if record is None or record.purged_at or not record.result_json:
                    return RedirectResponse(f"{base}?error=compare_pick", status_code=303)
                result = AuditResult.model_validate_json(record.result_json)
                results.append(result.model_dump(mode="json"))
            # The comparison itself is not in Portuguese yet: it reads in English.
            view = link_locale(locale)
            body = comparison_body(
                results[0],
                results[1],
                href_a=account_pages.report_href(picked[0], locale),
                href_b=account_pages.report_href(picked[1], locale),
                locale=view,
            )
            copy = account_pages.COPY[view]
            body += f"<p><a class='btn btn-ghost' href='{base}'>{copy['compare_back']}</a></p>"
            other = account_pages.path("account", "en" if view == "es" else "es")
            query = "&".join(f"id={audit_id}" for audit_id in picked)
            page = compare_page(
                body,
                locale=view,
                lead=copy["compare_lead"],
                switch_href=f"{other}/comparar?{query}",
            )
            return HTMLResponse(guard_page(page))

        return handler

    def _signed_in_action(
        request: Request, path_locale: str, lang: str | None, csrf: str
    ) -> tuple[Any, str, str, str] | Response:
        """The session behind an account form, or the redirect that answers it."""
        locale = _account_locale(path_locale, lang)
        session = _session(request)
        if session is None:
            return _signin_redirect(locale, next_path=account_pages.path("account", locale))
        # The CSRF token decides; the browser's own cross-site signal is a
        # second layer, with the same rules as uploads (Origin: null passes).
        if not acct.same_secret(session[1], csrf) or _cross_site(request):
            return RedirectResponse(
                account_pages.path("account", locale) + "?error=csrf", status_code=303
            )
        ip = _client_ip(request, cfg.trusted_proxy_hops)
        if account_actions.hit(ip, datetime.now(UTC)) >= acct.MAX_ACCOUNT_ACTIONS_PER_HOUR:
            return RedirectResponse(
                account_pages.path("account", locale) + "?error=too_many", status_code=303
            )
        return session[0], session[2], locale, ip

    def _code_post(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            code: Annotated[str, Form(max_length=200)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            checked = _signed_in_action(request, path_locale, lang, csrf)
            if not isinstance(checked, tuple):
                return checked
            account, _, locale, _ = checked
            base = account_pages.path("account", locale)
            code_id = db.code_id(code.strip()[:_CODE_MAX])
            if code_id is None:
                return RedirectResponse(f"{base}?error=code_unknown", status_code=303)
            outcome = db.link_code(account.id, code_id, at=datetime.now(UTC))
            if outcome == "linked":
                return RedirectResponse(f"{base}?done=code_linked", status_code=303)
            return RedirectResponse(f"{base}?error=code_{outcome}", status_code=303)

        return handler

    def _password_post(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            current: Annotated[str, Form(max_length=1024)] = "",
            password: Annotated[str, Form(max_length=1024)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            checked = _signed_in_action(request, path_locale, lang, csrf)
            if not isinstance(checked, tuple):
                return checked
            account, session_hash, locale, _ = checked
            base = account_pages.path("account", locale)
            if not acct.verify_password(db.password_hash(account.id) or "", current):
                return RedirectResponse(f"{base}?error=wrong", status_code=303)
            problem = acct.password_problem(password, email=account.email)
            if problem:
                shown = problem if problem in account_errors else "wrong"
                return RedirectResponse(f"{base}?error={shown}", status_code=303)
            db.set_password(account.id, acct.hash_password(password))
            db.delete_sessions(account.id, keep=session_hash)
            return RedirectResponse(f"{base}?done=password_changed", status_code=303)

        return handler

    def _delete_post(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            current: Annotated[str, Form(max_length=1024)] = "",
            with_reports: Annotated[str, Form(max_length=10)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            checked = _signed_in_action(request, path_locale, lang, csrf)
            if not isinstance(checked, tuple):
                return checked
            account, _, locale, _ = checked
            if not acct.verify_password(db.password_hash(account.id) or "", current):
                return RedirectResponse(
                    account_pages.path("account", locale) + "?error=wrong", status_code=303
                )
            db.delete_account(account.id, with_reports=with_reports == "yes")
            response = _signin_redirect(locale, done="deleted")
            response.delete_cookie(acct.SESSION_COOKIE, path="/")
            return response

        return handler

    def _forgot_get(path_locale: str) -> Callable[..., Response]:
        def handler(lang: str | None = None) -> Response:
            locale = _account_locale(path_locale, lang)
            return HTMLResponse(
                account_pages.forgot_page(locale=locale, contact_url=cfg.contact_url)
            )

        return handler

    def _reset_get(path_locale: str) -> Callable[..., Response]:
        def handler(request: Request, token: str = "", lang: str | None = None) -> Response:
            locale = _account_locale(path_locale, lang)
            csrf = _anon_csrf(request)
            valid = (
                bool(token)
                and len(token) <= 128
                and (db.reset_account(acct.hash_secret(token), datetime.now(UTC)) is not None)
            )
            page = account_pages.reset_page(
                locale=locale, csrf=csrf, token=token if valid else "", valid=valid
            )
            return _anon_page(page, csrf, 200 if valid else 410)

        return handler

    def _reset_post(path_locale: str) -> Callable[..., Response]:
        def handler(
            request: Request,
            token: Annotated[str, Form(max_length=200)] = "",
            password: Annotated[str, Form(max_length=1024)] = "",
            csrf: Annotated[str, Form(max_length=200)] = "",
            lang: str | None = None,
        ) -> Response:
            locale = _account_locale(path_locale, lang)
            new_csrf = _anon_csrf(request)
            now = datetime.now(UTC)
            digest = acct.hash_secret(token) if token else ""
            resetting = db.reset_account(digest, now) if token else None
            if resetting is None:
                page = account_pages.reset_page(locale=locale, csrf=new_csrf, token="", valid=False)
                return _anon_page(page, new_csrf, 410)
            error = (
                "csrf"
                if not _anon_ok(request, csrf)
                else acct.password_problem(password, email=_account_email(resetting))
            )
            if error:
                page = account_pages.reset_page(
                    locale=locale, csrf=new_csrf, token=token, error=error
                )
                return _anon_page(page, new_csrf, 400)
            account_id = db.use_reset(digest, now)
            if account_id is None:  # pragma: no cover - spent between the two reads
                page = account_pages.reset_page(locale=locale, csrf=new_csrf, token="", valid=False)
                return _anon_page(page, new_csrf, 410)
            db.set_password(account_id, acct.hash_password(password))
            db.delete_sessions(account_id)
            return _signin_redirect(locale, done="reset_done")

        return handler

    for path_locale in account_pages.LANGUAGES:
        paths = account_pages.PATHS[path_locale]
        html_get = {"methods": ["GET"], "response_class": HTMLResponse}
        app.add_api_route(paths["signup"], _signup_get(path_locale), **html_get)
        app.add_api_route(paths["signup"], _signup_post(path_locale), methods=["POST"])
        app.add_api_route(paths["signin"], _signin_get(path_locale), **html_get)
        app.add_api_route(paths["signin"], _signin_post(path_locale), methods=["POST"])
        app.add_api_route(paths["signout"], _signout_post(path_locale), methods=["POST"])
        app.add_api_route(paths["account"], _account_get(path_locale), **html_get)
        app.add_api_route(paths["account"] + "/codigo", _code_post(path_locale), methods=["POST"])
        app.add_api_route(paths["account"] + "/comparar", _account_compare(path_locale), **html_get)
        app.add_api_route(
            paths["account"] + "/contrasena", _password_post(path_locale), methods=["POST"]
        )
        app.add_api_route(paths["account"] + "/borrar", _delete_post(path_locale), methods=["POST"])
        app.add_api_route(paths["account"] + "/datos", _account_data(path_locale), methods=["GET"])
        strategies_base = account_pages.strategies_path(path_locale)
        app.add_api_route(
            strategies_base + "/guardar", _strategy_file_post(path_locale), methods=["POST"]
        )
        app.add_api_route(
            strategies_base + "/{strategy_id}", _strategy_get(path_locale), **html_get
        )
        app.add_api_route(
            strategies_base + "/{strategy_id}/pdf",
            _strategy_get(path_locale, as_pdf=True),
            methods=["GET"],
        )
        for suffix, action in (("quitar", "remove"), ("nombre", "rename"), ("borrar", "delete")):
            app.add_api_route(
                f"{strategies_base}/{{strategy_id}}/{suffix}",
                _strategy_action(path_locale, action),
                methods=["POST"],
            )
        app.add_api_route(paths["forgot"], _forgot_get(path_locale), **html_get)
        app.add_api_route(paths["reset"], _reset_get(path_locale), **html_get)
        app.add_api_route(paths["reset"], _reset_post(path_locale), methods=["POST"])

    def _link_to_session(
        request: Request, audit_id: str, reference: str | None = None, *, via: str = VIA_SAVED
    ) -> None:
        """Put a report (and the code that paid it) on the signed-in account, if any.

        ``via`` says whether it is the account's own report (uploaded or paid
        while signed in) or only saved there; only its own can be deleted with it.
        """
        session = _session(request)
        if session is None:
            return
        now = datetime.now(UTC)
        db.link_audit(session[0].id, audit_id, at=now, via=via)
        if reference and reference.startswith(CODE_REFERENCE_PREFIX):
            db.link_code(session[0].id, reference[len(CODE_REFERENCE_PREFIX) :], at=now)

    def _run_and_store(
        inputs: Any,
        ip: str,
        uploads: dict[str, bytes | None],
        report_name: str | None,
        access_code: str | None,
        live_name: str | None = None,
    ) -> tuple[str, str, bool]:
        """The CPU- and IO-bound part of an upload; runs in the thread pool."""
        now = datetime.now(UTC)
        result = run_audit(
            inputs,
            bootstrap_samples=cfg.bootstrap_samples,
            now=now,
            market=market_data.closes if market_data is not None else None,
        )
        extra_files: dict[str, bytes] = {}
        if uploads["report"] and report_name:
            extra_files[report_name] = uploads["report"]
        if uploads["optimization"]:
            extra_files["optimization.xml"] = uploads["optimization"]
        live_bytes = uploads.get("live")
        if live_bytes and live_name:
            extra_files[live_name] = live_bytes
        token = secrets.token_urlsafe(32)
        # Stored without any checkout link: the token must never be persisted
        # in clear, so the page is re-rendered per request with the caller's.
        html_text, json_text = render(
            result,
            watermark=True,
            free_mode=cfg.free_mode,
            price_usd=cfg.price_usd,
            checkout_url=None,
        )
        paid = db.create_audit(
            audit_id=result.audit_id,
            created_at=now,
            token_hash=hash_token(token),
            client_ip=ip,
            declared_json=canonical_dumps(result.declared),
            result_json=json_text,
            report_html=html_text,
            overall_class=result.verdict.overall,
            digests=result.inputs["digests"],
            equity_csv=uploads["equity"],
            trades_csv=uploads["trades"],
            benchmark_csv=uploads["benchmark"],
            variants_csv=uploads["variants"],
            files=extra_files,
            access_code=access_code,
        )
        return result.audit_id, token, paid

    def _cross_site(request: Request) -> bool:
        """True when the browser says the upload was posted from another site.

        A second layer beside the SameSite cookie (the service's domain sits
        on the Public Suffix List). ``Sec-Fetch-Site`` decides when present
        (every current browser sends it, whatever the referrer policy):
        only ``same-origin`` and ``none`` pass; ``same-site`` is refused too,
        since other apps on the same parent domain would count as same site.
        Without it, the Origin (else the Referer) must be this service. Our
        pages send ``Referrer-Policy: no-referrer``, so a genuine form post
        carries ``Origin: null``: that, like no header at all (a script,
        curl), is no signal and goes through.
        """
        fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
        if fetch_site:
            return fetch_site not in ("same-origin", "none")
        source = request.headers.get("origin") or request.headers.get("referer") or ""
        if not source or source == "null":
            return False
        host = urlsplit(source).netloc.lower()
        allowed = {request.headers.get("host", "").lower()}
        if cfg.base_url:
            allowed.add(urlsplit(cfg.base_url).netloc.lower())
        return host not in allowed

    @app.post("/audits")
    async def create_audit(
        request: Request,
        equity: Annotated[UploadFile | None, File()] = None,
        report: Annotated[UploadFile | None, File()] = None,
        optimization: Annotated[UploadFile | None, File()] = None,
        live: Annotated[UploadFile | None, File()] = None,
        trades: Annotated[UploadFile | None, File()] = None,
        benchmark: Annotated[UploadFile | None, File()] = None,
        variants: Annotated[UploadFile | None, File()] = None,
        trials: Annotated[str, Form(max_length=12)] = "",
        cost_bps: Annotated[str, Form(max_length=20)] = "",
        oos_start: Annotated[str, Form()] = "",
        description: Annotated[str, Form()] = "",
        benchmark_applicable: Annotated[str, Form()] = "yes",
        locale: Annotated[str, Form()] = "es",
        consent: Annotated[str, Form()] = "",
        challenge: Annotated[str, Form()] = "",
        initial_balance: Annotated[str, Form()] = "",
        access_code: Annotated[str, Form()] = "",
        net_of_fees: Annotated[str, Form(max_length=8)] = "",
    ) -> Response:
        # The report's language, which the refusals below also speak.
        report_loc = _report_locale(locale)
        if _cross_site(request):
            return _html_error(request, 403, message("cross_site", report_loc), report_loc)
        if consent.lower() not in ("on", "yes", "true", "1"):
            return _html_error(request, 400, message("consent_required", report_loc), report_loc)
        # The hourly limit counts a network (an IPv6 /64), and the upload
        # stores that network, not the exact address.
        ip = acct.network_address(_client_ip(request, cfg.trusted_proxy_hops))
        now = datetime.now(UTC)
        since = now - timedelta(hours=1)
        attempts = upload_attempts.hit(ip, now)
        recent = await run_in_threadpool(db.count_uploads_since, ip, since)
        if (
            recent >= cfg.max_uploads_per_hour_per_ip
            or attempts >= cfg.max_uploads_per_hour_per_ip * UPLOAD_ATTEMPTS_PER_UPLOAD
        ):
            return _html_error(request, 429, message("rate_limited", report_loc), report_loc)
        # The free tier: without a code that still works, an upload needs an
        # account, and each account gets FREE_PREVIEWS_PER_MONTH previews a
        # calendar month (also capped per network address). Past it, a
        # credit on the account turns the upload into a full report.
        gate_account: Any = None
        welcome = False
        free_preview = False
        spend_credit = False
        device = request.cookies.get(acct.DEVICE_COOKIE) or ""
        new_device = ""
        if not (0 < len(device) <= 128):
            device = new_device = acct.new_secret()
        if not cfg.free_mode:
            typed = access_code.strip()[:_CODE_MAX] if cfg.access_codes_enabled else ""
            usable = bool(typed) and await run_in_threadpool(db.code_usable, typed, now)
            session = _session(request)
            if not usable and session is None:
                return _gate(request, report_loc, "code" if typed else "signin", 401)
            if not usable and session is not None:
                gate_account = session[0]
        try:
            uploads = {
                "equity": await _read_limited(equity, what="equity"),
                "report": await _read_limited(report, what="report"),
                "optimization": await _read_limited(optimization, what="optimization"),
                "live": await _read_limited(live, what="live"),
                "trades": await _read_limited(trades, what="trades"),
                "benchmark": await _read_limited(benchmark, what="benchmark"),
                "variants": await _read_limited(variants, what="variants"),
            }
        except UploadTooLarge as exc:
            limit = _field_limit(exc.what)
            if exc.what == "optimization":
                count = limit // OPTIMIZATION_PASS_BYTES
                passes = f"{round(count, -3) if count >= 1_000 else count:,}"
                text = message(
                    "optimization_too_large", report_loc, limit=_megabytes(limit), passes=passes
                )
            else:
                text = message(
                    "too_large",
                    report_loc,
                    what=UPLOAD_NAMES[exc.what][report_loc],
                    limit=_megabytes(limit),
                )
            return _html_error(request, 413, text, report_loc)
        if not uploads["equity"] and not uploads["report"]:
            return _html_error(request, 400, message("equity_required", report_loc), report_loc)
        # A new account's first file is a free full report (once per account,
        # browser and file); then the month's free previews; then a credit;
        # else the way to buy. This first look answers at once; the claims
        # taken after parsing are what make the limits hold when uploads
        # arrive together.
        start = acct.month_start(now)
        device_sha256 = acct.hash_secret(device)
        reservation = acct.new_secret()
        fingerprint = ""
        # The free tier counts networks: an IPv6 address stands for its /64.
        net = acct.network_address(ip) if ip else ""
        #: Why this upload was not the account's free full report, when it
        #: could have been: told on the preview it becomes.
        welcome_refused = ""

        def preview_or_credit(account_id: str) -> Response | None:
            """The first look at the monthly previews and the credits."""
            nonlocal free_preview, spend_credit
            used = db.free_previews_since(start, account_id=account_id)
            network = db.free_previews_since(start, client_ip=net)
            if (
                used < acct.FREE_PREVIEWS_PER_MONTH
                and network < acct.FREE_PREVIEWS_PER_IP_PER_MONTH
            ):
                free_preview = True
            elif db.account_credits(account_id, now) > 0:
                spend_credit = True
            else:
                reason = "quota" if used >= acct.FREE_PREVIEWS_PER_MONTH else "network"
                return _gate(request, report_loc, reason, 402)
            return None

        def claim_preview(account_id: str) -> str:
            month = acct.claim_month(now)
            slots = {
                "account": [
                    f"preview:account:{account_id}:{month}:{n}"
                    for n in range(acct.FREE_PREVIEWS_PER_MONTH)
                ]
            }
            if ip:
                net_key = acct.network_key(ip)
                slots["network"] = [
                    f"preview:ip:{net_key}:{month}:{n}"
                    for n in range(acct.FREE_PREVIEWS_PER_IP_PER_MONTH)
                ]
            return db.claim_free(reservation, keys=(), slots=slots, at=now)

        def claim_free_use(account_id: str, inputs: Any) -> Response | None:
            """Take the free full report or a free preview, atomically."""
            nonlocal welcome, free_preview, spend_credit, fingerprint, welcome_refused
            fingerprint = acct.content_fingerprint(inputs.equity.frame)
            if welcome:
                refused = db.welcome_refusal(
                    account_id,
                    device_sha256=device_sha256,
                    file_sha256=fingerprint,
                    client_ip=net,
                    since=start,
                    per_ip=acct.WELCOME_REPORTS_PER_IP_PER_MONTH,
                )
                if not refused:
                    month = acct.claim_month(now)
                    slots = (
                        {
                            "network": [
                                f"welcome:ip:{acct.network_key(ip)}:{month}:{n}"
                                for n in range(acct.WELCOME_REPORTS_PER_IP_PER_MONTH)
                            ]
                        }
                        if ip
                        else {}
                    )
                    keys = (
                        f"welcome:account:{account_id}",
                        f"welcome:device:{device_sha256}",
                        f"welcome:file:{fingerprint}",
                    )
                    if not db.claim_free(reservation, keys=keys, slots=slots, at=now):
                        return None
                welcome = False
                welcome_refused = refused
                refusal = preview_or_credit(account_id)
                if refusal is not None:
                    return refusal
            if free_preview:
                full = claim_preview(account_id)
                if not full:
                    return None
                free_preview = False
                if db.account_credits(account_id, now) > 0:
                    spend_credit = True
                    return None
                return _gate(request, report_loc, "quota" if full == "account" else "network", 402)
            return None

        if gate_account is not None:
            first_look = (
                db.welcome_refusal(
                    gate_account.id,
                    device_sha256=device_sha256,
                    file_sha256="",
                    client_ip=net,
                    since=start,
                    per_ip=acct.WELCOME_REPORTS_PER_IP_PER_MONTH,
                )
                if acct.WELCOME_FULL_REPORT
                else "off"
            )
            if not first_look:
                welcome = True
            else:
                welcome_refused = first_look
                refusal = preview_or_credit(gate_account.id)
                if refusal is not None:
                    return refusal
        try:
            # A blank field is not a declaration: 1 trial is assumed (and never
            # held against the client) and no extra cost is added.
            declared = DeclaredMetadata(
                trials=int(trials) if trials.strip() else 1,
                trials_declared=bool(trials.strip()),
                cost_bps_per_side=float(cost_bps) if cost_bps.strip() else 0.0,
                oos_start=oos_start.strip() or None,
                description=description,
                benchmark_applicable=benchmark_applicable.lower() not in ("no", "false", "0"),
                locale=report_loc,
                initial_balance=_positive_or_none(initial_balance),
                challenge=challenge.strip() or None,
                net_of_fees=net_of_fees.lower() in ("on", "yes", "true", "1"),
            )
        except (ValidationError, ValueError):
            return _html_error(request, 400, message("invalid_declared", report_loc), report_loc)
        report_filename = report.filename if report is not None and uploads["report"] else None
        # A platform report dropped in the equity-curve field is read as the
        # report, instead of failing as a malformed CSV.
        equity_name = equity.filename if equity is not None else None
        if (
            uploads["equity"]
            and not uploads["report"]
            and looks_like_platform_report(equity_name, uploads["equity"])
        ):
            uploads["report"], uploads["equity"] = uploads["equity"], None
            report_filename = equity_name
        report_name = report_digest_name(report_filename) if uploads["report"] else None
        live_filename = live.filename if live is not None and uploads["live"] else None
        live_name = live_digest_name(live_filename) if uploads["live"] else None
        # A code is only redeemed where something is locked; in free mode it
        # is ignored so no credit is spent on a report that is free anyway.
        code = access_code.strip()[:_CODE_MAX] if cfg.access_codes_enabled else ""
        # "Name its columns": the customer's mapping for a platform no importer knows.
        form = await request.form()
        # Control characters (a NUL) cannot be in a decoded header; dropped
        # so a pasted name still matches and never reaches a page.
        report_columns = {
            role: _CONTROL.sub("", str(form.get(f"col_{role}") or "")).strip()[:200]
            for role in mapping.FORM_ROLES
            if _CONTROL.sub("", str(form.get(f"col_{role}") or "")).strip()
        }
        # Named columns belong to the report: a file sent with them in the
        # curve field is read with them, before any automatic reader.
        if report_columns and uploads["equity"] and not uploads["report"]:
            uploads["report"], uploads["equity"] = uploads["equity"], None
            report_filename = equity_name
            report_name = report_digest_name(report_filename)

        # A signed-in customer's column choice is remembered per header.
        signed_in = _session(request)
        mapper = signed_in[0].id if signed_in is not None else ""
        carried = {
            "locale": report_loc,
            "consent": consent,
            "trials": trials,
            "cost_bps": cost_bps,
            "oos_start": oos_start,
            "description": description,
            "benchmark_applicable": benchmark_applicable,
            "challenge": challenge,
            "initial_balance": initial_balance,
            "access_code": access_code,
            "net_of_fees": net_of_fees,
        }

        def build(columns: dict[str, str] | None) -> Any:
            return build_inputs(
                uploads["equity"],
                declared,
                trades_bytes=uploads["trades"],
                benchmark_bytes=uploads["benchmark"],
                variants_bytes=uploads["variants"],
                report_bytes=uploads["report"],
                report_filename=report_filename,
                optimization_bytes=uploads["optimization"],
                live_bytes=uploads["live"],
                live_filename=live_filename,
                report_columns=columns if uploads["report"] else None,
            )

        def attempt(columns: dict[str, str]) -> Any:
            """The report read with the customer's columns: a date with a
            balance or with each trade's result becomes the equity curve, any
            other choice goes to the universal reader."""
            if not columns or not uploads["report"] or mapping.curve_kind(columns) is None:
                known = {role: name for role, name in columns.items() if role in universal.ROLES}
                return build(known or None)
            curve, notes = mapping.curve_from_columns(
                uploads["report"], columns, initial_balance=declared.initial_balance
            )
            inputs = build_inputs(
                curve,
                declared,
                trades_bytes=uploads["trades"],
                benchmark_bytes=uploads["benchmark"],
                variants_bytes=uploads["variants"],
                optimization_bytes=uploads["optimization"],
                live_bytes=uploads["live"],
                live_filename=live_filename,
            )
            # The digest is the customer's own file, not the curve built from it.
            digests = {
                name: digest for name, digest in inputs.digests.items() if name != "equity.csv"
            }
            digests[report_digest_name(report_filename)] = sha256_of_bytes(uploads["report"])
            return dataclasses.replace(
                inputs,
                digests=digests,
                warnings=[*(f"report: {note}" for note in notes), *inputs.warnings],
            )

        def parse_and_audit() -> tuple[str, str, bool] | Response:
            """Parse, audit and store; runs in the thread pool under a slot."""
            try:
                inputs = attempt(report_columns)
            except ParseError as exc:
                # A "curve" that starts at 0 or crosses it is a list of
                # results, and a curve file with no value column may be one:
                # both are offered to name, a result list preselected as such.
                lone = bool(uploads["report"]) != bool(uploads["equity"])
                sheet = uploads["report"] or uploads["equity"]
                curve_like = (
                    exc.code == "equity_not_positive"
                    and sheet is not None
                    and mapping.looks_like_results(sheet)
                ) or (exc.code in ("missing_value", "missing_timestamp") and not uploads["report"])
                if curve_like and lone and not report_columns:
                    results = mapping.read_table(sheet) if sheet else None
                    if results is not None:
                        guess = mapping.results_guess(
                            results, with_result=exc.code == "equity_not_positive"
                        )
                        # A curve file with no date in sight keeps its plain refusal.
                        if "date" in guess or exc.code == "equity_not_positive":
                            return _mapping_answer(
                                request, results, exc, report_loc, carried, guess
                            )
                table = (
                    mapping.read_table(uploads["report"])
                    if uploads["report"] and exc.code in mapping.MAPPABLE_CODES
                    else None
                )
                if table is None:
                    return _html_error(
                        request, 400, _sentence(exc.localized(report_loc)), report_loc
                    )
                # The columns this account chose before for the same header.
                saved = (
                    mapping.usable_mapping(
                        mapping.loads(
                            db.column_map(mapper, mapping.header_signature(table.header))
                        ),
                        table,
                    )
                    if mapper and not report_columns
                    else {}
                )
                if saved:
                    try:
                        inputs = attempt(saved)
                    except Exception:
                        # A saved choice that no longer reads the file is offered again.
                        logger.info("a saved column mapping did not read the file")
                        return _mapping_answer(request, table, exc, report_loc, carried, saved)
                else:
                    return _mapping_answer(request, table, exc, report_loc, carried, report_columns)
            except ValueError:
                return _html_error(request, 400, message("invalid_upload", report_loc), report_loc)
            except Exception:
                # A file no importer anticipated: the customer gets the
                # format message, the operator gets the traceback.
                logger.exception("upload could not be parsed")
                return _html_error(request, 400, message("invalid_upload", report_loc), report_loc)
            if gate_account is not None:
                refusal = claim_free_use(gate_account.id, inputs)
                if refusal is not None:
                    return refusal
            try:
                return _run_and_store(
                    inputs, ip, uploads, report_name, code or None, live_name=live_name
                )
            except Exception:
                logger.exception("audit failed")
                return _html_error(request, 500, message("server_error", report_loc), report_loc)

        # The slot bounds CPU and memory: a burst of uploads waits here and,
        # past the queue time, is told the service is busy instead of piling up.
        if not await _take_slot(audit_slots, cfg.audit_queue_seconds):
            return _html_error(request, 503, message("busy", report_loc), report_loc)
        try:
            outcome = await run_in_threadpool(parse_and_audit)
        finally:
            audit_slots.release()
        if not isinstance(outcome, tuple):
            if gate_account is not None:
                db.release_free(reservation)
            return outcome
        audit_id, token, paid = outcome
        if mapper and report_columns and uploads["report"]:
            table = mapping.read_table(uploads["report"])
            chosen = mapping.usable_mapping(report_columns, table) if table else {}
            if table is not None and chosen:
                db.save_column_map(
                    mapper, mapping.header_signature(table.header), mapping.dumps(chosen), at=now
                )
        credit_used = False
        welcomed = False
        if gate_account is not None and paid:
            db.release_free(reservation)
        elif gate_account is not None:
            if welcome:
                welcomed = db.grant_welcome(
                    audit_id,
                    gate_account.id,
                    device_sha256=device_sha256,
                    file_sha256=fingerprint,
                    client_ip=net,
                    at=now,
                )
                paid = welcomed
                if welcomed:
                    _reward_invite(gate_account.id, device_sha256, net, now)
            elif spend_credit:
                credit_used = db.redeem_with_account(
                    audit_id, gate_account.id, at=datetime.now(UTC)
                )
                paid = credit_used
            if not paid and not free_preview:
                # The free report or the credit went to a simultaneous upload:
                # this one is a free preview if the month still has one.
                db.release_free(reservation)
                full = claim_preview(gate_account.id)
                if full:
                    db.delete_audit(audit_id)
                    return _gate(
                        request, report_loc, "quota" if full == "account" else "network", 402
                    )
                free_preview = True
            if free_preview:
                db.record_free_preview(audit_id, gate_account.id, client_ip=net, at=now)
        if paid or _session(request) is not None:
            linked = db.get_audit(audit_id)
            _link_to_session(
                request, audit_id, linked.stripe_session_id if linked else None, via=VIA_UPLOAD
            )
        location = f"/audits/{audit_id}?token={token}"
        if welcomed:
            location += "&acct=welcome"
        elif credit_used:
            location += "&acct=upload_credit"
        elif free_preview and welcome_refused in WELCOME_REFUSALS:
            location += f"&acct=preview_{welcome_refused}"
        elif code:
            location += "&code=" + ("applied" if paid else "rejected")
        if _wants_json(request):
            body: dict[str, Any] = {"audit_id": audit_id, "token": token, "location": location}
            if code:
                body["access_code"] = "applied" if paid else "rejected"
            answer: Response = JSONResponse(body, status_code=201)
        else:
            if code and not paid:
                # Open the preview at the code field, where the refusal and its fix are shown.
                location += "#canjear"
            answer = RedirectResponse(location, status_code=303)
        if new_device:
            # A random id for this browser: one free full report per browser.
            _cookie(answer, acct.DEVICE_COOKIE, new_device, max_age=acct.DEVICE_DAYS * 86400)
        return answer

    def _mapping_answer(
        request: Request,
        table: mapping.Table,
        exc: ParseError,
        locale: str,
        carried: dict[str, str],
        chosen: dict[str, str],
    ) -> Response:
        """A file whose columns were not recognised: its columns and first
        rows, to name them. Nothing is spent: no preview, no free report."""
        if exc.code in ("unknown_format", "universal_columns_missing"):
            # Said on this page, not as "name them on the form".
            if chosen:
                text = mapping.missing_fields(chosen, locale)
            elif "profit" in mapping.preselected(table)[0]:
                text = mapping.COPY[locale]["results"]
            else:
                text = mapping.COPY[locale]["unknown"]
        elif exc.code == "equity_not_positive":
            text = mapping.COPY[locale]["results"]
        elif exc.code in ("missing_value", "missing_timestamp"):
            results = "profit" in chosen or "profit" in mapping.preselected(table)[0]
            text = mapping.COPY[locale]["results" if results else "unknown"]
        else:
            text = _sentence(exc.localized(locale))
        if _wants_json(request):
            return JSONResponse(
                {"error": text, "code": exc.code, "columns": table.names}, status_code=422
            )
        page = mapping.mapping_page(table, text, locale=locale, carried=carried, chosen=chosen)
        return HTMLResponse(page, status_code=422)

    def _gate(request: Request, locale: str, reason: str, status: int) -> Response:
        """The answer to an upload the free tier does not cover."""
        if _wants_json(request):
            return JSONResponse({"error": f"free_tier_{reason}"}, status_code=status)
        page = account_pages.gate_page(
            locale=locale, reason=reason, limit=acct.FREE_PREVIEWS_PER_MONTH
        )
        return HTMLResponse(page, status_code=status)

    def _owns(request: Request | None, audit_id: str) -> bool:
        """Whether the signed-in account holds this report."""
        if request is None:
            return False
        session = _session(request)
        return session is not None and db.account_for_audit(audit_id) == session[0].id

    def _load(audit_id: str, token: str | None, request: Request | None = None) -> Any:
        """The audit, opened by its private token or by the account that holds it."""
        record = db.get_audit(audit_id)
        if record is None or not (
            token_matches(record.token_hash, token) or _owns(request, record.id)
        ):
            raise _not_found()
        if record.purged_at or not record.result_json:
            raise HTTPException(status_code=410, detail="purged")
        return record

    def _report_html(
        record: Any,
        token: str,
        locale: str,
        *,
        notice: str | None = None,
        code_error: bool = False,
        notice_ok: bool = False,
        account_box: str = "",
    ) -> str:
        result = AuditResult.model_validate_json(record.result_json)
        unlockable = not record.paid and cfg.stripe_enabled and cfg.card_for(record.id)
        link_single, link_pack = (
            payments.payment_link_urls(cfg, record.id, locale)
            if not record.paid and cfg.links_enabled and cfg.card_for(record.id)
            else ("", "")
        )
        redeemable = not record.paid and cfg.access_codes_enabled
        publishable = record.paid or cfg.free_mode
        pack_code, pack_left = (
            payments.pack_for(db, cfg, record.stripe_session_id) if record.paid else ("", 0)
        )
        base = f"/audits/{record.id}"
        query = f"?token={token}&lang={locale}"
        other = "en" if locale == "es" else "es"
        html_text, _ = render(
            result,
            watermark=not record.paid,
            free_mode=cfg.free_mode,
            price_usd=cfg.price_usd,
            checkout_url=f"{base}/checkout{query}" if unlockable else None,
            pay_links=(link_single, link_pack, f"{base}{query}&pay=done") if link_single else None,
            redeem_url=f"{base}/redeem{query}" if redeemable else None,
            publish_url=f"{base}/publish{query}" if publishable else None,
            notice=notice,
            contact_url=cfg.contact_url if redeemable else None,
            pack_price_usd=(
                cfg.pack_price_usd if (redeemable or unlockable or link_single) else 0.0
            ),
            pack_code=pack_code,
            pack_credits_left=pack_left,
            code_error=code_error and not record.paid,
            notice_ok=notice_ok and record.paid,
            legal_links=True,
            locale=locale,
            switch_url=f"{base}?token={token}&lang={other}",
            compare_link=(
                f"{base}?token={token}" if token and (record.paid or cfg.free_mode) else None
            ),
            account_box=account_box,
            pdf_url=f"{base}/pdf{query}" if (record.paid or cfg.free_mode) and pdf_ok else None,
        )
        return html_text

    pdf_cache: OrderedDict[tuple[str, str, bool], bytes] = OrderedDict()
    pdf_cache_lock = threading.Lock()

    @app.get("/audits/{audit_id}/pdf")
    def audit_pdf(
        request: Request, audit_id: str, token: str | None = None, lang: str | None = None
    ) -> Response:
        record = _load(audit_id, token, request)
        locale = _view_locale(record, lang)
        if not record.paid and not cfg.free_mode:
            raise HTTPException(status_code=402, detail="payment_required")
        key = (record.id, locale, bool(record.paid))
        with pdf_cache_lock:
            content = pdf_cache.get(key)
            if content is not None:
                pdf_cache.move_to_end(key)
        if content is None:
            result = AuditResult.model_validate_json(record.result_json)
            page, _ = render(
                result,
                watermark=not record.paid,
                free_mode=cfg.free_mode,
                legal_links=True,
                locale=locale,
            )
            try:
                content = pdf_lib.report_pdf(
                    page, audit_id=record.id, locale=locale, wait_seconds=PDF_WAIT_SECONDS
                )
            except pdf_lib.PdfBusy:
                return _html_error(request, 503, message("pdf_busy", locale), locale)
            except pdf_lib.PdfUnavailable:
                return _html_error(request, 503, message("pdf_unavailable", locale), locale)
            _record_issued(content, audit_id=record.id, kind="pdf")
            with pdf_cache_lock:
                pdf_cache[key] = content
                while len(pdf_cache) > PDF_CACHE_SIZE:
                    pdf_cache.popitem(last=False)
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{pdf_lib.filename(record.id)}"',
                "Cache-Control": "private, no-store",
                "X-Robots-Tag": "noindex",
            },
        )

    # The ``.json`` route is registered first: ``{audit_id}`` would otherwise
    # swallow the suffix.
    @app.get("/audits/{audit_id}.json")
    def audit_json(request: Request, audit_id: str, token: str | None = None) -> Response:
        record = _load(audit_id, token, request)
        if not record.paid and not cfg.free_mode:
            raise HTTPException(status_code=402, detail="payment_required")
        content = record.result_json.encode("utf-8")
        _record_issued(content, audit_id=record.id, kind="json")
        return Response(content=content, media_type="application/json")

    @app.get("/audits/{audit_id}", response_class=HTMLResponse)
    def audit_page(
        request: Request,
        audit_id: str,
        token: str | None = None,
        code: str | None = None,
        lang: str | None = None,
        session_id: str | None = None,
        pay: str | None = None,
        acct_done: Annotated[str | None, Query(alias="acct")] = None,
    ) -> str:
        record = _load(audit_id, token, request)
        locale = _view_locale(record, lang)
        ui = locale
        # Only known values are shown, so the query cannot inject text.
        notice = None
        if session_id and cfg.stripe_enabled:
            if not record.paid:
                record = _confirm_card_payment(record, session_id, request)
            notice = message("card_paid" if record.paid else "card_pending", locale)
        elif pay == "done" and cfg.links_enabled:
            # Back from a Payment Link: the webhook unlocks, this page only reports.
            notice = message("card_paid" if record.paid else "card_pending", locale)
        elif pay == "cancelled" and not record.paid:
            notice = message("card_cancelled", locale)
        elif code == "applied" and record.paid:
            notice = message("code_applied", locale)
        elif acct_done == "credit" and record.paid:
            notice = account_pages.COPY[ui]["credit_used"]
        elif acct_done == "upload_credit" and record.paid:
            notice = account_pages.COPY[ui]["credit_on_upload"]
        elif acct_done == "welcome" and record.paid:
            notice = account_pages.COPY[ui]["welcome_notice"].format(
                limit=acct.FREE_PREVIEWS_PER_MONTH,
                price=f"USD {cfg.price_usd:.0f}",
                pack=f"USD {cfg.pack_price_usd:.0f}",
            )
        elif acct_done == "saved":
            notice = account_pages.COPY[ui]["saved_notice"]
        elif (
            acct_done
            and acct_done.startswith("preview_")
            and acct_done[8:] in WELCOME_REFUSALS
            and not record.paid
        ):
            notice = account_pages.COPY[ui][f"welcome_refused_{acct_done[8:]}"]
        elif acct_done == "nocredit" and not record.paid:
            notice = account_pages.COPY[ui]["credit_none"]
        # A rejected code is answered next to the code field, not in this banner.
        code_error = code == "rejected" and not record.paid
        valid_token = token if token_matches(record.token_hash, token) else ""
        return _report_html(
            record,
            valid_token or "",
            locale,
            notice=notice,
            code_error=code_error,
            notice_ok=(record.paid or acct_done == "saved") and notice is not None,
            account_box=_account_box(request, record, valid_token or "", locale),
        )

    def _account_box(request: Request, record: Any, token: str, locale: str) -> str:
        """The account line on a report: sign up, save, saved, or unlock with a credit."""
        session = _session(request)
        owner = db.account_for_audit(record.id)
        query = f"?token={token}&lang={locale}" if token else f"?lang={locale}"
        locked = not record.paid and cfg.access_codes_enabled
        if session is None:
            if not token:
                return ""
            return account_pages.report_box(
                locale=locale,
                state="anon",
                audit_id=record.id,
                query=query,
                next_path=f"/audits/{record.id}{query}",
            )
        account, csrf, _ = session
        state = "mine" if owner == account.id else ("unsaved" if owner is None else "other")
        credits = db.account_credits(account.id, datetime.now(UTC)) if locked else 0
        return account_pages.report_box(
            locale=locale,
            state=state,
            audit_id=record.id,
            query=query,
            csrf=csrf,
            credits=credits,
            locked=locked,
        )

    def _report_action(
        request: Request, audit_id: str, token: str | None, csrf: str
    ) -> tuple[Any, Any] | Response:
        """The audit and the session behind a report's account form."""
        record = _load(audit_id, token, request)
        session = _session(request)
        locale = _view_locale(record, request.query_params.get("lang"))
        back = f"/audits/{audit_id}?token={token}" if token else f"/audits/{audit_id}?"
        if session is None:
            return _signin_redirect(locale, next_path=f"{back}&lang={locale}")
        if not acct.same_secret(session[1], csrf):
            return RedirectResponse(f"{back}&lang={locale}", status_code=303)
        return record, session

    @app.post("/audits/{audit_id}/save")
    def save_to_account(
        request: Request,
        audit_id: str,
        csrf: Annotated[str, Form(max_length=200)] = "",
        token: str | None = None,
        lang: str | None = None,
    ) -> Response:
        checked = _report_action(request, audit_id, token, csrf)
        if not isinstance(checked, tuple):
            return checked
        record, session = checked
        locale = _view_locale(record, lang)
        outcome = db.link_audit(session[0].id, record.id, at=datetime.now(UTC))
        back = f"/audits/{audit_id}?token={token}" if token else f"/audits/{audit_id}?"
        done = "&acct=saved" if outcome in ("linked", "already") else ""
        return RedirectResponse(f"{back}&lang={locale}{done}", status_code=303)

    @app.post("/audits/{audit_id}/credit")
    def unlock_with_credit(
        request: Request,
        audit_id: str,
        csrf: Annotated[str, Form(max_length=200)] = "",
        token: str | None = None,
        lang: str | None = None,
    ) -> Response:
        checked = _report_action(request, audit_id, token, csrf)
        if not isinstance(checked, tuple):
            return checked
        record, session = checked
        if not cfg.access_codes_enabled:
            raise HTTPException(status_code=404, detail="codes_disabled")
        locale = _view_locale(record, lang)
        back = f"/audits/{audit_id}?token={token}" if token else f"/audits/{audit_id}?"
        if record.paid:
            return RedirectResponse(f"{back}&lang={locale}", status_code=303)
        now = datetime.now(UTC)
        account_id = session[0].id
        if db.link_audit(account_id, record.id, at=now) == "other":
            return RedirectResponse(f"{back}&lang={locale}", status_code=303)
        applied = db.redeem_with_account(record.id, account_id, at=now)
        if applied:
            db.link_audit(account_id, record.id, at=now, via=VIA_PAID)
        done = "credit" if applied else "nocredit"
        return RedirectResponse(f"{back}&lang={locale}&acct={done}", status_code=303)

    def _confirm_card_payment(record: Any, session_id: str, request: Request) -> Any:
        """Back from Stripe: ask Stripe about that session and unlock what it paid.

        Only a session Stripe reports as paid, for this very audit, unlocks
        anything; a Stripe outage leaves the page locked and the webhook
        finishes the job. Lookups are limited per address and per audit, and
        a session that did not unlock is not asked again within the hour, so
        a script looping the return URL cannot use up the Stripe API rate.
        """
        if not session_id.startswith(payments.SESSION_PREFIX) or len(session_id) > 255:
            return record
        now = datetime.now(UTC)
        if failed_card_sessions.count(session_id, now):
            return record
        ip = _client_ip(request, cfg.trusted_proxy_hops)
        limit = payments.CARD_LOOKUPS_PER_HOUR
        if (
            card_lookups.count(f"ip:{ip}", now) >= limit
            or card_lookups.count(f"audit:{record.id}", now) >= limit
        ):
            return record
        card_lookups.hit(f"ip:{ip}", now)
        card_lookups.hit(f"audit:{record.id}", now)
        lookup: SessionLookup = app.state.session_lookup
        try:
            session = lookup(cfg, session_id)
        except Exception:  # noqa: BLE001 - any SDK or network failure: stay locked
            logger.warning("checkout session lookup failed for audit %s", record.id)
            failed_card_sessions.hit(session_id, now)
            return record
        if str((session.get("metadata") or {}).get("audit_id") or "") != record.id:
            failed_card_sessions.hit(session_id, now)
            return record
        payments.fulfil(db, cfg, session, at=now)
        paid = db.get_audit(record.id) or record
        if not paid.paid:
            failed_card_sessions.hit(session_id, now)
        return paid

    def _report_locale(value: str | None) -> str:
        return value if value in REPORT_LOCALES else "es"

    def _record_locale(record: Any) -> str:
        try:
            return _report_locale(json.loads(record.declared_json or "{}").get("locale"))
        except ValueError:
            return "es"

    def _view_locale(record: Any, lang: str | None) -> str:
        """The report's language: ``lang`` when given, else the one chosen at upload."""
        return _report_locale(lang) if lang in REPORT_LOCALES else _record_locale(record)

    @app.post("/audits/{audit_id}/redeem")
    def redeem(
        request: Request,
        audit_id: str,
        code: Annotated[str, Form()],
        token: str | None = None,
        lang: str | None = None,
    ) -> Response:
        record = _load(audit_id, token, request)
        if not cfg.access_codes_enabled:
            raise HTTPException(status_code=404, detail="codes_disabled")
        locale = _view_locale(record, lang)
        location = f"/audits/{audit_id}?token={token or ''}&lang={locale}"
        if record.paid:
            return RedirectResponse(location, status_code=303)
        # Each attempt counts toward the hourly per-IP limit, like an upload.
        ip = acct.network_address(_client_ip(request, cfg.trusted_proxy_hops))
        now = datetime.now(UTC)
        attempts = redeem_attempts.hit(ip, now) + db.count_uploads_since(
            ip, now - timedelta(hours=1)
        )
        if attempts >= cfg.max_uploads_per_hour_per_ip:
            return _html_error(request, 429, message("rate_limited", locale), locale)
        applied = db.redeem_for_audit(audit_id, code.strip()[:_CODE_MAX], at=now)
        if applied:
            paid_record = db.get_audit(audit_id)
            _link_to_session(
                request,
                audit_id,
                paid_record.stripe_session_id if paid_record else None,
                via=VIA_PAID,
            )
        outcome = "applied" if applied else "rejected"
        if _wants_json(request):
            return JSONResponse({"access_code": outcome})
        return RedirectResponse(f"{location}&code={outcome}", status_code=303)

    @app.post("/audits/{audit_id}/publish")
    def publish(
        request: Request, audit_id: str, token: str | None = None, lang: str | None = None
    ) -> Response:
        record = _load(audit_id, token, request)
        if not (record.paid or cfg.free_mode):
            raise HTTPException(status_code=402, detail="publish_locked")
        publication = db.publish(audit_id, at=datetime.now(UTC))
        location = f"/v/{publication.public_id}?lang={_view_locale(record, lang)}"
        if _wants_json(request):
            return JSONResponse(
                {"public_id": publication.public_id, "location": location}, status_code=201
            )
        return RedirectResponse(location, status_code=303)

    @app.post("/audits/{audit_id}/unpublish")
    def unpublish(request: Request, audit_id: str, token: str | None = None) -> Response:
        # Only the token is checked: the owner can withdraw a page whose
        # audit was already purged and kept only its public view.
        record = db.get_audit(audit_id)
        if record is None or not token_matches(record.token_hash, token):
            raise _not_found()
        removed = db.unpublish(audit_id)
        if _wants_json(request):
            return JSONResponse({"unpublished": removed})
        if record.purged_at:
            return RedirectResponse(f"/?lang={_record_locale(record)}", status_code=303)
        return RedirectResponse(f"/audits/{audit_id}?token={token}", status_code=303)

    def _published(public_id: str) -> tuple[Any, Any, dict[str, Any], str]:
        """Publication, record, the page's data and the result's SHA-256.

        A purged audit is served from the view the purge kept; without one
        the page is gone (410).
        """
        publication = db.get_publication(public_id)
        if publication is None:
            raise _not_found()
        record = db.get_audit(publication.audit_id)
        if record is None:
            raise _not_found()
        if record.purged_at or not record.result_json:
            kept = db.publication_view(record.id)
            if kept is None:
                raise HTTPException(status_code=410, detail="purged")
            return publication, record, kept[0], kept[1]
        result = AuditResult.model_validate_json(record.result_json)
        return publication, record, result.model_dump(mode="json"), result_sha256(result)

    @app.get("/v/{public_id}/badge.svg")
    def badge(public_id: str, lang: str | None = None) -> Response:
        publication, record, _, _ = _published(public_id)
        svg = badge_svg(
            overall=record.overall_class,
            public_id=publication.public_id,
            audited_on=record.created_at[:10],
            locale=_locale(link_locale(lang or "es")),
        )
        return Response(content=svg, media_type="image/svg+xml")

    @app.get("/v/{public_id}", response_class=HTMLResponse)
    def verification(request: Request, public_id: str, lang: str | None = None) -> str:
        publication, _, data, digest = _published(public_id)
        return verification_page(
            data,
            public_id=publication.public_id,
            published_at=publication.created_at,
            result_sha256=digest,
            base_url=_site_url(request),
            # The public page has Spanish and English; a Portuguese reader gets English.
            locale=_locale(link_locale(lang or "es")),
        )

    sample_cache: dict[tuple[str, str, tuple[str, ...]], str] = {}
    sample_lock = threading.Lock()

    def _sample_market() -> tuple[Callable[[str], Any] | None, tuple[str, ...]]:
        """The public series already in memory for the sample, never waiting on
        the network; none (the offline sample) until the first download lands."""
        ready = market_data.ready() if market_data is not None else ()
        return (market_data.closes if market_data is not None and ready else None), ready

    def _sample_html(locale: str, base_url: str) -> str:
        """Built once per locale, address and set of public series in memory, and
        kept: the input and the clock are fixed."""
        market, ready = _sample_market()
        with sample_lock:
            key = (locale, base_url, ready)
            if key not in sample_cache:
                html_text, _ = render(
                    sample_result(locale, market=market),
                    watermark=False,
                    free_mode=True,
                    notice=SAMPLE_BANNER[locale],
                    legal_links=True,
                    switch_url="/sample?lang=en" if locale == "es" else "/ejemplo?lang=es",
                    locale=locale,
                    head_meta=sample_meta(locale, base_url),
                    pdf_url=(SAMPLE_PDF_PATHS[locale] if pdf_ok else None),
                )
                sample_cache[key] = html_text
            return sample_cache[key]

    sample_pdfs: dict[tuple[str, tuple[str, ...]], bytes] = {}

    def _sample_pdf(locale: str) -> Response:
        """The sample report as the PDF a buyer gets, built once per language and
        set of public series in memory."""
        market, ready = _sample_market()
        with sample_lock:
            key = (locale, ready)
            if key not in sample_pdfs:
                page, _ = render(
                    sample_result(locale, market=market),
                    watermark=False,
                    free_mode=True,
                    notice=SAMPLE_BANNER[locale],
                    legal_links=True,
                    locale=locale,
                )
                try:
                    sample_pdfs[key] = pdf_lib.report_pdf(
                        page,
                        audit_id=SAMPLE_PDF_NAMES[locale],
                        locale=locale,
                        wait_seconds=PDF_WAIT_SECONDS,
                    )
                    _record_issued(
                        sample_pdfs[key], audit_id=check_lib.SAMPLE_AUDIT_ID, kind="pdf"
                    )
                except (pdf_lib.PdfBusy, pdf_lib.PdfUnavailable):
                    return HTMLResponse(
                        error_page(message("pdf_busy", locale), locale=locale), status_code=503
                    )
        name = f"rigor-{SAMPLE_PDF_NAMES[locale]}.pdf"
        return Response(
            content=sample_pdfs[key],
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{name}"',
                "Cache-Control": "public, max-age=3600",
            },
        )

    @app.get("/ejemplo.pdf")
    async def sample_pdf_es() -> Response:
        return await run_in_threadpool(_sample_pdf, "es")

    @app.get("/sample.pdf")
    async def sample_pdf_en() -> Response:
        return await run_in_threadpool(_sample_pdf, "en")

    @app.get("/pt/exemplo.pdf")
    async def sample_pdf_pt() -> Response:
        return await run_in_threadpool(_sample_pdf, "pt")

    @app.get("/pt/exemplo", response_class=HTMLResponse)
    async def sample_pt(request: Request) -> str:
        return await run_in_threadpool(_sample_html, "pt", _site_url(request))

    @app.get("/ejemplo", response_class=HTMLResponse)
    async def sample_es(request: Request, lang: str | None = None) -> str:
        return await run_in_threadpool(_sample_html, _locale(lang or "es"), _site_url(request))

    @app.get("/sample", response_class=HTMLResponse)
    async def sample_en(request: Request, lang: str | None = None) -> str:
        return await run_in_threadpool(_sample_html, _locale(lang or "en"), _site_url(request))

    @app.get("/guias", response_class=HTMLResponse)
    def guides_es(request: Request, lang: str | None = None) -> str:
        return guides_index_page(locale=_locale(lang or "es"), base_url=_site_url(request))

    @app.get("/metodologia", response_class=HTMLResponse)
    def method_es(request: Request, lang: str | None = None) -> str:
        return method_page(locale=_locale(lang or "es"), base_url=_site_url(request))

    @app.get("/methodology", response_class=HTMLResponse)
    def method_en(request: Request, lang: str | None = None) -> str:
        return method_page(locale=_locale(lang or "en"), base_url=_site_url(request))

    @app.get("/pt/metodologia", response_class=HTMLResponse)
    def method_pt(request: Request) -> str:
        return method_page(locale="pt", base_url=_site_url(request))

    @app.get("/guides", response_class=HTMLResponse)
    def guides_en(request: Request, lang: str | None = None) -> str:
        return guides_index_page(locale=_locale(lang or "en"), base_url=_site_url(request))

    def _guide(request: Request, slug: str, path_locale: str, locale: str) -> Response:
        guide = GUIDES_BY_PATH[path_locale].get(slug)
        if guide is None:
            # A guide's slug in another language moves to this language's own.
            other = next(
                (
                    found
                    for lang, guides in GUIDES_BY_PATH.items()
                    if lang != path_locale and (found := guides.get(slug)) is not None
                ),
                None,
            )
            if other is None:
                raise _not_found()
            return RedirectResponse(guide_url(other.slug, path_locale), status_code=301)
        return HTMLResponse(guide_page(guide, locale=locale, base_url=_site_url(request)))

    def _audience(request: Request, slug: str, path_locale: str, locale: str) -> Response:
        page = AUDIENCES_BY_PATH[path_locale].get(slug)
        if page is None:
            # A page's slug in another language moves to this language's own.
            other = next(
                (
                    found
                    for lang, pages in AUDIENCES_BY_PATH.items()
                    if lang != path_locale and (found := pages.get(slug)) is not None
                ),
                None,
            )
            if other is None:
                raise _not_found()
            return RedirectResponse(audience_url(other.slug, path_locale), status_code=301)
        return HTMLResponse(
            audience_page(
                page,
                locale=locale,
                base_url=_site_url(request),
                free_mode=cfg.free_mode,
                price_usd=cfg.price_usd,
                pack_price_usd=cfg.pack_price_usd,
            )
        )

    @app.get("/para/{slug}", response_class=HTMLResponse)
    def audience_es(request: Request, slug: str, lang: str | None = None) -> Response:
        return _audience(request, slug, "es", _locale(lang or "es"))

    @app.get("/for/{slug}", response_class=HTMLResponse)
    def audience_en(request: Request, slug: str, lang: str | None = None) -> Response:
        return _audience(request, slug, "en", _locale(lang or "en"))

    @app.get("/pt/guias", response_class=HTMLResponse)
    def guides_pt(request: Request) -> str:
        return guides_index_page(locale="pt", base_url=_site_url(request))

    @app.get("/pt/guias/{slug}", response_class=HTMLResponse)
    def guide_pt(request: Request, slug: str) -> Response:
        return _guide(request, slug, "pt", "pt")

    @app.get("/pt/para/{slug}", response_class=HTMLResponse)
    def audience_pt(request: Request, slug: str) -> Response:
        return _audience(request, slug, "pt", "pt")

    @app.get("/guias/{slug}", response_class=HTMLResponse)
    def guide_es(request: Request, slug: str, lang: str | None = None) -> Response:
        return _guide(request, slug, "es", _locale(lang or "es"))

    @app.get("/guides/{slug}", response_class=HTMLResponse)
    def guide_en(request: Request, slug: str, lang: str | None = None) -> Response:
        return _guide(request, slug, "en", _locale(lang or "en"))

    def _legal_context() -> LegalContext:
        return LegalContext(
            operator_name=cfg.operator_name,
            operator_contact=cfg.operator_contact,
            operator_address=cfg.operator_address,
            jurisdiction=cfg.jurisdiction,
            free_mode=cfg.free_mode,
            price_usd=cfg.price_usd,
            card_payments=cfg.card_public,
            access_codes=cfg.access_codes_enabled,
            pack_price_usd=cfg.pack_price_usd,
            retention_days=cfg.retention_days,
            max_uploads_per_hour_per_ip=cfg.max_uploads_per_hour_per_ip,
        )

    def _terms(request: Request, locale: str) -> str:
        return legal_page(
            terms_text(_legal_context(), locale),
            locale=locale,
            kind="terms",
            base_url=_site_url(request),
        )

    def _privacy(request: Request, locale: str) -> str:
        return legal_page(
            privacy_text(_legal_context(), locale),
            locale=locale,
            kind="privacy",
            base_url=_site_url(request),
        )

    def _compare_form_page(
        locale: str, *, error: str = "", status: int = 200, request: Request | None = None
    ) -> Response:
        form = compare_form(locale, error=error)
        if request is not None and _session(request) is not None:
            # Signed in: their own reports compare without pasting links.
            form = account_pages.compare_mine_note(locale) + form
        page = compare_page(form, locale=locale)
        return HTMLResponse(page, status_code=status)

    @app.get("/comparar", response_class=HTMLResponse)
    def compare_es(request: Request, lang: str | None = None) -> Response:
        return _compare_form_page(_locale(lang or "es"), request=request)

    @app.get("/compare", response_class=HTMLResponse)
    def compare_en(request: Request, lang: str | None = None) -> Response:
        return _compare_form_page(_locale(lang or "en"), request=request)

    @app.get("/pt/comparar", response_class=HTMLResponse)
    def compare_pt(request: Request) -> Response:
        return _compare_form_page("pt", request=request)

    def _compare(link_a: str, link_b: str, lang: str | None, default: str) -> Response:
        locale = "pt" if default == "pt" else _locale(lang or default)
        copy = COMPARE_COPY[locale]
        first, second = parse_report_link(link_a), parse_report_link(link_b)
        if first is None or second is None:
            return _compare_form_page(locale, error=copy["bad_link"], status=400)
        parsed = [first, second]
        if first[0] == second[0]:
            return _compare_form_page(locale, error=copy["same"], status=400)
        results = []
        for audit_id, token in parsed:
            record = db.get_audit(audit_id)
            if (
                record is None
                or not token_matches(record.token_hash, token)
                or record.purged_at
                or not record.result_json
            ):
                return _compare_form_page(locale, error=copy["not_found"], status=404)
            if not (record.paid or cfg.free_mode):
                return _compare_form_page(locale, error=copy["locked"], status=402)
            result = AuditResult.model_validate_json(record.result_json)
            results.append((result.model_dump(mode="json"), f"/audits/{audit_id}?token={token}"))
        (data_a, href_a), (data_b, href_b) = results
        body = comparison_body(
            data_a,
            data_b,
            href_a=f"{href_a}&lang={locale}",
            href_b=f"{href_b}&lang={locale}",
            locale=locale,
        )
        again = COMPARE_PATH[locale] + ("" if locale == "pt" else f"?lang={locale}")
        body += f"<p><a class='btn btn-ghost' href='{again}'>{copy['again']}</a></p>"
        return HTMLResponse(guard_page(compare_page(body, locale=locale)))

    @app.post("/comparar", response_class=HTMLResponse)
    def compare_post_es(
        link_a: Annotated[str, Form(max_length=1000)],
        link_b: Annotated[str, Form(max_length=1000)],
        lang: Annotated[str | None, Form()] = None,
    ) -> Response:
        return _compare(link_a, link_b, lang, "es")

    @app.post("/compare", response_class=HTMLResponse)
    def compare_post_en(
        link_a: Annotated[str, Form(max_length=1000)],
        link_b: Annotated[str, Form(max_length=1000)],
        lang: Annotated[str | None, Form()] = None,
    ) -> Response:
        return _compare(link_a, link_b, lang, "en")

    @app.post("/pt/comparar", response_class=HTMLResponse)
    def compare_post_pt(
        link_a: Annotated[str, Form(max_length=1000)],
        link_b: Annotated[str, Form(max_length=1000)],
        lang: Annotated[str | None, Form()] = None,
    ) -> Response:
        return _compare(link_a, link_b, lang, "pt")

    def _check_page(request: Request, locale: str, content: str, status: int = 200) -> Response:
        page = check_page(content, locale=locale, base_url=_site_url(request))
        return HTMLResponse(guard_page(page), status_code=status)

    @app.get("/comprobar", response_class=HTMLResponse)
    def check_es(request: Request, lang: str | None = None) -> Response:
        locale = _locale(lang or "es")
        return _check_page(request, locale, check_lib.check_form(locale))

    @app.get("/check", response_class=HTMLResponse)
    def check_en(request: Request, lang: str | None = None) -> Response:
        locale = _locale(lang or "en")
        return _check_page(request, locale, check_lib.check_form(locale))

    @app.get("/pt/comprovar", response_class=HTMLResponse)
    def check_pt(request: Request) -> Response:
        return _check_page(request, "pt", check_lib.check_form("pt"))

    async def _check(request: Request, report: UploadFile | None, locale: str) -> Response:
        copy = check_lib.COPY[locale]
        ip = _client_ip(request, cfg.trusted_proxy_hops)
        if check_attempts.hit(ip, datetime.now(UTC)) >= check_lib.CHECKS_PER_HOUR_PER_IP:
            return _html_error(request, 429, message("rate_limited", locale), locale)
        if report is None or not report.filename:
            return _check_page(
                request, locale, check_lib.check_form(locale, error=copy["no_file"]), 400
            )
        digest = hashlib.sha256()
        size = 0
        while chunk := await report.read(1 << 16):
            size += len(chunk)
            if size > check_lib.MAX_CHECK_BYTES:
                return _check_page(
                    request, locale, check_lib.check_form(locale, error=copy["too_large"]), 413
                )
            digest.update(chunk)
        if size == 0:
            return _check_page(
                request, locale, check_lib.check_form(locale, error=copy["no_file"]), 400
            )
        hexdigest = digest.hexdigest()
        found = await run_in_threadpool(db.find_issued, hexdigest)
        return _check_page(request, locale, check_lib.check_result(found, hexdigest, locale))

    @app.post("/comprobar", response_class=HTMLResponse)
    async def check_post_es(
        request: Request,
        report: Annotated[UploadFile | None, File()] = None,
        lang: Annotated[str | None, Form()] = None,
    ) -> Response:
        return await _check(request, report, _locale(lang or "es"))

    @app.post("/check", response_class=HTMLResponse)
    async def check_post_en(
        request: Request,
        report: Annotated[UploadFile | None, File()] = None,
        lang: Annotated[str | None, Form()] = None,
    ) -> Response:
        return await _check(request, report, _locale(lang or "en"))

    @app.post("/pt/comprovar", response_class=HTMLResponse)
    async def check_post_pt(
        request: Request,
        report: Annotated[UploadFile | None, File()] = None,
        lang: Annotated[str | None, Form()] = None,
    ) -> Response:
        return await _check(request, report, "pt")

    @app.get("/terminos", response_class=HTMLResponse)
    def terms_es(request: Request, lang: str | None = None) -> str:
        return _terms(request, _locale(lang or "es"))

    @app.get("/terms", response_class=HTMLResponse)
    def terms_en(request: Request, lang: str | None = None) -> str:
        return _terms(request, _locale(lang or "en"))

    @app.get("/privacidad", response_class=HTMLResponse)
    def privacy_es(request: Request, lang: str | None = None) -> str:
        return _privacy(request, _locale(lang or "es"))

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy_en(request: Request, lang: str | None = None) -> str:
        return _privacy(request, _locale(lang or "en"))

    @app.post("/audits/{audit_id}/checkout")
    def checkout(
        request: Request,
        audit_id: str,
        token: str | None = None,
        lang: str | None = None,
        plan: Annotated[str, Form()] = payments.PLAN_SINGLE,
    ) -> Response:
        record = _load(audit_id, token, request)
        if not (cfg.stripe_enabled and cfg.card_for(audit_id)):
            raise HTTPException(status_code=503, detail="payments_disabled")
        locale = _view_locale(record, lang)
        # Bought while signed in: the report (and a pack's code) lands on the account.
        _link_to_session(request, audit_id)
        if record.paid:
            return RedirectResponse(
                f"/audits/{audit_id}?token={token}&lang={locale}", status_code=303
            )
        # The pack is sold only while it is on sale; anything else is one audit.
        if plan != payments.PLAN_PACK or not cfg.pack_price_usd:
            plan = payments.PLAN_SINGLE
        factory: CheckoutFactory = app.state.checkout_factory
        url = factory(cfg, audit_id, token or "", plan=plan, locale=locale)
        return RedirectResponse(url, status_code=303)

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request) -> Response:
        if not (cfg.stripe_configured or cfg.links_configured):
            raise _not_found()
        payload = await request.body()
        header = request.headers.get("stripe-signature")
        if not verify_stripe_signature(payload, header, cfg.stripe_webhook_secret):
            raise HTTPException(status_code=400, detail="invalid signature")
        try:
            event = json.loads(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid payload") from exc
        if event.get("type") in PAID_EVENTS:
            session = event.get("data", {}).get("object", {})
            if isinstance(session, dict):
                await run_in_threadpool(payments.fulfil, db, cfg, session, at=datetime.now(UTC))
        return JSONResponse({"received": True})

    return app


__all__ = [
    "CONTENT_SECURITY_POLICY",
    "MESSAGES",
    "PRINT_HANDLER",
    "SECURITY_HEADERS",
    "AttemptLog",
    "BodyLimitMiddleware",
    "RedactSecretsFilter",
    "redact_secrets",
    "shorten_client_address",
    "uvicorn_log_config",
    "client_ip",
    "create_app",
    "message",
    "hash_token",
    "sign_stripe_payload",
    "stripe_checkout",
    "token_matches",
    "verify_stripe_signature",
]
