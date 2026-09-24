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

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from pydantic import ValidationError

from quant_trade.audit.engine import run_audit
from quant_trade.audit.legal import LegalContext, privacy_text, terms_text
from quant_trade.audit.pages import (
    SAMPLE_BANNER,
    badge_svg,
    error_page,
    landing,
    legal_page,
    verification_page,
)
from quant_trade.audit.report import render, result_sha256
from quant_trade.audit.sample import sample_result
from quant_trade.audit.schema import (
    AuditResult,
    DeclaredMetadata,
    ParseError,
    build_inputs,
    report_digest_name,
)
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import REQUIRE_WEB, Store, make_store
from quant_trade.evidence.canonical_json import canonical_dumps

CheckoutFactory = Callable[[AuditSettings, str, str], str]

STRIPE_TOLERANCE_SECONDS = 300
_EMAIL_MAX = 254

#: Every message the service itself shows, in both locales. Parse errors
#: carry their own Spanish text (``ParseError.localized``).
MESSAGES: dict[str, dict[str, str]] = {
    "consent_required": {
        "es": "Tienes que aceptar las condiciones para enviar la auditoría.",
        "en": "You must accept the terms to submit the audit.",
    },
    "rate_limited": {
        "es": "Demasiadas auditorías desde esta dirección en la última hora; inténtalo más tarde.",
        "en": "Too many audits from this address in the last hour; try again later.",
    },
    "too_large": {
        "es": "El archivo {what} supera el límite de {limit} bytes.",
        "en": "The {what} file exceeds {limit} bytes.",
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
    "code_applied": {
        "es": "Código de acceso aplicado: este es el informe completo.",
        "en": "Access code applied: this is the full report.",
    },
    "code_rejected": {
        "es": (
            "No se pudo aplicar el código de acceso (no válido, agotado o caducado). "
            "Esta es la vista previa."
        ),
        "en": (
            "The access code could not be applied (invalid, used up or expired). "
            "This is the preview."
        ),
    },
    "codes_disabled": {
        "es": "Este servicio no acepta códigos de acceso.",
        "en": "This service does not accept access codes.",
    },
    "publish_locked": {
        "es": "Solo se puede publicar la verificación de un informe completo.",
        "en": "Only a full report can publish a verification.",
    },
}

#: The only routes a browser or CDN may cache: public by design, no token.
PUBLIC_CACHE_CONTROL = "public, max-age=300"
_CODE_MAX = 40

#: The file names as the error sentences use them.
UPLOAD_NAMES: dict[str, dict[str, str]] = {
    "equity": {"es": "de la curva de equity", "en": "equity"},
    "trades": {"es": "de operaciones", "en": "trades"},
    "benchmark": {"es": "del benchmark", "en": "benchmark"},
    "variants": {"es": "de variantes", "en": "variants"},
    "report": {"es": "del informe", "en": "report"},
    "optimization": {"es": "de optimización", "en": "optimisation"},
}


def message(key: str, locale: str, **values: Any) -> str:
    """The service's own message ``key`` in ``locale`` (Spanish by default)."""
    texts = MESSAGES[key]
    return texts.get(locale, texts["es"]).format(**values)


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


def stripe_checkout(settings: AuditSettings, audit_id: str, token: str) -> str:
    """Create a Stripe Checkout session and return its URL (needs the SDK)."""
    import stripe

    stripe.api_key = settings.stripe_secret_key
    base = settings.base_url
    session = stripe.checkout.Session.create(
        mode="payment",
        line_items=[{"price": settings.stripe_price_id, "quantity": 1}],
        success_url=f"{base}/audits/{audit_id}?token={token}&paid=1",
        cancel_url=f"{base}/audits/{audit_id}?token={token}",
        metadata={"audit_id": audit_id},
        client_reference_id=audit_id,
    )
    return str(session.url)


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
    return 3 <= len(value) <= _EMAIL_MAX and "@" in value and "." in value.rsplit("@", 1)[-1]


def create_app(settings: AuditSettings | None = None, store: Store | None = None) -> Any:
    try:
        from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
        from fastapi.exceptions import RequestValidationError
        from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
        from starlette.concurrency import run_in_threadpool
        from starlette.exceptions import HTTPException as StarletteHTTPException
    except ImportError as exc:
        raise ImportError(REQUIRE_WEB) from exc

    cfg = settings or AuditSettings.from_env()
    db = store or make_store(cfg.database_url)
    app = FastAPI(
        title="Backtest audit",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.settings = cfg
    app.state.store = db
    app.state.checkout_factory = stripe_checkout

    @app.middleware("http")
    async def no_store(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        public = request.url.path.startswith("/v/") and response.status_code == 200
        response.headers["Cache-Control"] = PUBLIC_CACHE_CONTROL if public else "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def _locale(value: str | None) -> str:
        return value if value in ("es", "en") else "es"

    def _html_error(request: Request, status: int, message: str, locale: str) -> Response:
        if _wants_json(request):
            return JSONResponse({"error": message}, status_code=status)
        return HTMLResponse(error_page(message, locale=locale), status_code=status)

    def _not_found() -> HTTPException:
        return HTTPException(status_code=404, detail="not_found")

    @app.exception_handler(RequestValidationError)
    async def form_error(request: Request, exc: RequestValidationError) -> Response:
        locale = _locale(request.query_params.get("lang"))
        return _html_error(request, 400, message("invalid_form", locale), locale)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> Response:
        # Route errors carry a MESSAGES key as detail; anything else (a
        # FastAPI-generated 404 or 405) is shown as the generic not-found.
        key = str(exc.detail) if str(exc.detail) in MESSAGES else "not_found"
        if exc.status_code == 400 and request.url.path.startswith("/webhooks/"):
            return JSONResponse({"error": str(exc.detail)}, status_code=400)
        locale = _locale(request.query_params.get("lang"))
        return _html_error(request, exc.status_code, message(key, locale), locale)

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
            if size > cfg.max_upload_bytes:
                raise UploadTooLarge(what)
            chunks.append(chunk)
        data = b"".join(chunks)
        return data or None

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "free_mode": cfg.free_mode,
            "stripe_enabled": cfg.stripe_enabled,
            "access_codes": cfg.access_codes_enabled,
            "database": cfg.database_kind,
            "legal_configured": cfg.legal_configured,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(lang: str | None = None, joined: int = 0, error: str | None = None) -> str:
        locale = _locale(lang)
        # Only known codes are shown, so the query string cannot inject text.
        shown = message("invalid_email", locale) if error == "email" else None
        return landing(
            locale=locale,
            free_mode=cfg.free_mode,
            price_usd=cfg.price_usd,
            joined=bool(joined),
            error=shown,
            access_codes=cfg.access_codes_enabled,
            card_payments=cfg.stripe_enabled,
            contact_url=cfg.contact_url,
            retention_days=cfg.retention_days,
        )

    @app.post("/waitlist")
    def waitlist(email: Annotated[str, Form()], lang: Annotated[str, Form()] = "es") -> Response:
        locale = _locale(lang)
        if not _valid_email(email):
            return RedirectResponse(f"/?lang={locale}&error=email", status_code=303)
        db.add_waitlist(email, at=datetime.now(UTC))
        return RedirectResponse(f"/?lang={locale}&joined=1", status_code=303)

    def _run_and_store(
        inputs: Any,
        ip: str,
        uploads: dict[str, bytes | None],
        report_name: str | None,
        access_code: str | None,
    ) -> tuple[str, str, bool]:
        """The CPU- and IO-bound part of an upload; runs in the thread pool."""
        now = datetime.now(UTC)
        result = run_audit(inputs, bootstrap_samples=cfg.bootstrap_samples, now=now)
        extra_files: dict[str, bytes] = {}
        if uploads["report"] and report_name:
            extra_files[report_name] = uploads["report"]
        if uploads["optimization"]:
            extra_files["optimization.xml"] = uploads["optimization"]
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

    @app.post("/audits")
    async def create_audit(
        request: Request,
        equity: Annotated[UploadFile | None, File()] = None,
        report: Annotated[UploadFile | None, File()] = None,
        optimization: Annotated[UploadFile | None, File()] = None,
        trades: Annotated[UploadFile | None, File()] = None,
        benchmark: Annotated[UploadFile | None, File()] = None,
        variants: Annotated[UploadFile | None, File()] = None,
        trials: Annotated[int, Form()] = 1,
        cost_bps: Annotated[float, Form()] = 0.0,
        oos_start: Annotated[str, Form()] = "",
        description: Annotated[str, Form()] = "",
        benchmark_applicable: Annotated[str, Form()] = "yes",
        locale: Annotated[str, Form()] = "es",
        consent: Annotated[str, Form()] = "",
        challenge: Annotated[str, Form()] = "",
        initial_balance: Annotated[str, Form()] = "",
        access_code: Annotated[str, Form()] = "",
    ) -> Response:
        loc = _locale(locale)
        if consent.lower() not in ("on", "yes", "true", "1"):
            return _html_error(request, 400, message("consent_required", loc), loc)
        ip = _client_ip(request, cfg.trusted_proxy_hops)
        since = datetime.now(UTC) - timedelta(hours=1)
        recent = await run_in_threadpool(db.count_uploads_since, ip, since)
        if recent >= cfg.max_uploads_per_hour_per_ip:
            return _html_error(request, 429, message("rate_limited", loc), loc)
        try:
            uploads = {
                "equity": await _read_limited(equity, what="equity"),
                "report": await _read_limited(report, what="report"),
                "optimization": await _read_limited(optimization, what="optimization"),
                "trades": await _read_limited(trades, what="trades"),
                "benchmark": await _read_limited(benchmark, what="benchmark"),
                "variants": await _read_limited(variants, what="variants"),
            }
        except UploadTooLarge as exc:
            text = message(
                "too_large",
                loc,
                what=UPLOAD_NAMES[exc.what][loc],
                limit=f"{cfg.max_upload_bytes:,}",
            )
            return _html_error(request, 413, text, loc)
        if not uploads["equity"] and not uploads["report"]:
            return _html_error(request, 400, message("equity_required", loc), loc)
        try:
            declared = DeclaredMetadata(
                trials=trials,
                cost_bps_per_side=cost_bps,
                oos_start=oos_start.strip() or None,
                description=description,
                benchmark_applicable=benchmark_applicable.lower() not in ("no", "false", "0"),
                locale=loc,
                initial_balance=_positive_or_none(initial_balance),
                challenge=challenge.strip() or None,
            )
        except (ValidationError, ValueError):
            return _html_error(request, 400, message("invalid_declared", loc), loc)
        report_filename = report.filename if report is not None and uploads["report"] else None
        try:
            inputs = await run_in_threadpool(
                build_inputs,
                uploads["equity"],
                declared,
                trades_bytes=uploads["trades"],
                benchmark_bytes=uploads["benchmark"],
                variants_bytes=uploads["variants"],
                report_bytes=uploads["report"],
                report_filename=report_filename,
                optimization_bytes=uploads["optimization"],
            )
        except ParseError as exc:
            return _html_error(request, 400, exc.localized(loc), loc)
        except ValueError:
            return _html_error(request, 400, message("invalid_upload", loc), loc)
        report_name = report_digest_name(report_filename) if uploads["report"] else None
        # A code is only redeemed where something is locked; in free mode it
        # is ignored so no credit is spent on a report that is free anyway.
        code = access_code.strip()[:_CODE_MAX] if cfg.access_codes_enabled else ""
        audit_id, token, paid = await run_in_threadpool(
            _run_and_store, inputs, ip, uploads, report_name, code or None
        )
        location = f"/audits/{audit_id}?token={token}"
        if code:
            location += "&code=" + ("applied" if paid else "rejected")
        if _wants_json(request):
            body: dict[str, Any] = {"audit_id": audit_id, "token": token, "location": location}
            if code:
                body["access_code"] = "applied" if paid else "rejected"
            return JSONResponse(body, status_code=201)
        return RedirectResponse(location, status_code=303)

    def _load(audit_id: str, token: str | None) -> Any:
        record = db.get_audit(audit_id)
        if record is None or not token_matches(record.token_hash, token):
            raise _not_found()
        if record.purged_at or not record.result_json:
            raise HTTPException(status_code=410, detail="purged")
        return record

    def _report_html(record: Any, token: str, *, notice: str | None = None) -> str:
        result = AuditResult.model_validate_json(record.result_json)
        unlockable = not record.paid and cfg.stripe_enabled
        redeemable = not record.paid and cfg.access_codes_enabled
        publishable = record.paid or cfg.free_mode
        html_text, _ = render(
            result,
            watermark=not record.paid,
            free_mode=cfg.free_mode,
            price_usd=cfg.price_usd,
            checkout_url=f"/audits/{record.id}/checkout?token={token}" if unlockable else None,
            redeem_url=f"/audits/{record.id}/redeem?token={token}" if redeemable else None,
            publish_url=f"/audits/{record.id}/publish?token={token}" if publishable else None,
            notice=notice,
            contact_url=cfg.contact_url if redeemable else None,
            legal_links=True,
        )
        return html_text

    # The ``.json`` route is registered first: ``{audit_id}`` would otherwise
    # swallow the suffix.
    @app.get("/audits/{audit_id}.json")
    def audit_json(audit_id: str, token: str | None = None) -> Response:
        record = _load(audit_id, token)
        if not record.paid and not cfg.free_mode:
            raise HTTPException(status_code=402, detail="payment_required")
        return Response(content=record.result_json, media_type="application/json")

    @app.get("/audits/{audit_id}", response_class=HTMLResponse)
    def audit_page(audit_id: str, token: str | None = None, code: str | None = None) -> str:
        record = _load(audit_id, token)
        locale = _record_locale(record)
        # Only the two known values are shown, so the query cannot inject text.
        notice = None
        if code == "applied" and record.paid:
            notice = message("code_applied", locale)
        elif code == "rejected" and not record.paid:
            notice = message("code_rejected", locale)
        return _report_html(record, token or "", notice=notice)

    def _record_locale(record: Any) -> str:
        try:
            return _locale(json.loads(record.declared_json or "{}").get("locale"))
        except ValueError:
            return "es"

    @app.post("/audits/{audit_id}/redeem")
    def redeem(
        request: Request,
        audit_id: str,
        code: Annotated[str, Form()],
        token: str | None = None,
    ) -> Response:
        record = _load(audit_id, token)
        if not cfg.access_codes_enabled:
            raise HTTPException(status_code=404, detail="codes_disabled")
        location = f"/audits/{audit_id}?token={token}"
        if record.paid:
            return RedirectResponse(location, status_code=303)
        # Each attempt counts toward the hourly per-IP limit, like an upload.
        ip = _client_ip(request, cfg.trusted_proxy_hops)
        now = datetime.now(UTC)
        if _redeem_attempts(ip, now) >= cfg.max_uploads_per_hour_per_ip:
            locale = _record_locale(record)
            return _html_error(request, 429, message("rate_limited", locale), locale)
        applied = db.redeem_for_audit(audit_id, code.strip()[:_CODE_MAX], at=now)
        outcome = "applied" if applied else "rejected"
        if _wants_json(request):
            return JSONResponse({"access_code": outcome})
        return RedirectResponse(f"{location}&code={outcome}", status_code=303)

    redeem_log: dict[str, list[datetime]] = {}
    redeem_lock = threading.Lock()

    def _redeem_attempts(ip: str, now: datetime) -> int:
        """Attempts in the last hour from ``ip``, this one included, plus its uploads."""
        since = now - timedelta(hours=1)
        with redeem_lock:
            recent = [at for at in redeem_log.get(ip, []) if at >= since]
            recent.append(now)
            redeem_log[ip] = recent
            attempts = len(recent) - 1
        return attempts + db.count_uploads_since(ip, since)

    @app.post("/audits/{audit_id}/publish")
    def publish(request: Request, audit_id: str, token: str | None = None) -> Response:
        record = _load(audit_id, token)
        if not (record.paid or cfg.free_mode):
            raise HTTPException(status_code=402, detail="publish_locked")
        publication = db.publish(audit_id, at=datetime.now(UTC))
        location = f"/v/{publication.public_id}?lang={_record_locale(record)}"
        if _wants_json(request):
            return JSONResponse(
                {"public_id": publication.public_id, "location": location}, status_code=201
            )
        return RedirectResponse(location, status_code=303)

    @app.post("/audits/{audit_id}/unpublish")
    def unpublish(request: Request, audit_id: str, token: str | None = None) -> Response:
        _load(audit_id, token)
        removed = db.unpublish(audit_id)
        if _wants_json(request):
            return JSONResponse({"unpublished": removed})
        return RedirectResponse(f"/audits/{audit_id}?token={token}", status_code=303)

    def _published(public_id: str) -> tuple[Any, Any]:
        publication = db.get_publication(public_id)
        if publication is None:
            raise _not_found()
        record = db.get_audit(publication.audit_id)
        if record is None:
            raise _not_found()
        if record.purged_at or not record.result_json:
            raise HTTPException(status_code=410, detail="purged")
        return publication, record

    @app.get("/v/{public_id}/badge.svg")
    def badge(public_id: str, lang: str | None = None) -> Response:
        publication, record = _published(public_id)
        svg = badge_svg(
            overall=record.overall_class,
            public_id=publication.public_id,
            audited_on=record.created_at[:10],
            locale=_locale(lang),
        )
        return Response(content=svg, media_type="image/svg+xml")

    @app.get("/v/{public_id}", response_class=HTMLResponse)
    def verification(public_id: str, lang: str | None = None) -> str:
        publication, record = _published(public_id)
        result = AuditResult.model_validate_json(record.result_json)
        return verification_page(
            result.model_dump(mode="json"),
            public_id=publication.public_id,
            published_at=publication.created_at,
            result_sha256=result_sha256(result),
            base_url=cfg.base_url,
            locale=_locale(lang),
        )

    sample_cache: dict[str, str] = {}
    sample_lock = threading.Lock()

    def _sample_html(locale: str) -> str:
        """Built once per locale and kept: the input and the clock are fixed."""
        with sample_lock:
            if locale not in sample_cache:
                html_text, _ = render(
                    sample_result(locale),
                    watermark=False,
                    free_mode=True,
                    notice=SAMPLE_BANNER[locale],
                    legal_links=True,
                )
                sample_cache[locale] = html_text
            return sample_cache[locale]

    @app.get("/ejemplo", response_class=HTMLResponse)
    async def sample_es(lang: str | None = None) -> str:
        return await run_in_threadpool(_sample_html, _locale(lang or "es"))

    @app.get("/sample", response_class=HTMLResponse)
    async def sample_en(lang: str | None = None) -> str:
        return await run_in_threadpool(_sample_html, _locale(lang or "en"))

    def _legal_context() -> LegalContext:
        return LegalContext(
            operator_name=cfg.operator_name,
            operator_contact=cfg.operator_contact,
            operator_address=cfg.operator_address,
            jurisdiction=cfg.jurisdiction,
            free_mode=cfg.free_mode,
            price_usd=cfg.price_usd,
            card_payments=cfg.stripe_enabled,
            access_codes=cfg.access_codes_enabled,
            retention_days=cfg.retention_days,
            max_uploads_per_hour_per_ip=cfg.max_uploads_per_hour_per_ip,
        )

    def _terms(locale: str) -> str:
        return legal_page(terms_text(_legal_context(), locale), locale=locale)

    def _privacy(locale: str) -> str:
        return legal_page(privacy_text(_legal_context(), locale), locale=locale)

    @app.get("/terminos", response_class=HTMLResponse)
    def terms_es(lang: str | None = None) -> str:
        return _terms(_locale(lang or "es"))

    @app.get("/terms", response_class=HTMLResponse)
    def terms_en(lang: str | None = None) -> str:
        return _terms(_locale(lang or "en"))

    @app.get("/privacidad", response_class=HTMLResponse)
    def privacy_es(lang: str | None = None) -> str:
        return _privacy(_locale(lang or "es"))

    @app.get("/privacy", response_class=HTMLResponse)
    def privacy_en(lang: str | None = None) -> str:
        return _privacy(_locale(lang or "en"))

    @app.post("/audits/{audit_id}/checkout")
    def checkout(audit_id: str, token: str | None = None) -> Response:
        record = _load(audit_id, token)
        if not cfg.stripe_enabled:
            raise HTTPException(status_code=503, detail="payments_disabled")
        if record.paid:
            return RedirectResponse(f"/audits/{audit_id}?token={token}", status_code=303)
        factory: CheckoutFactory = app.state.checkout_factory
        url = factory(cfg, audit_id, token or "")
        return RedirectResponse(url, status_code=303)

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request) -> Response:
        if not cfg.stripe_configured:
            raise _not_found()
        payload = await request.body()
        header = request.headers.get("stripe-signature")
        if not verify_stripe_signature(payload, header, cfg.stripe_webhook_secret):
            raise HTTPException(status_code=400, detail="invalid signature")
        try:
            event = json.loads(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid payload") from exc
        if event.get("type") == "checkout.session.completed":
            session = event.get("data", {}).get("object", {})
            audit_id = str((session.get("metadata") or {}).get("audit_id") or "")
            if audit_id:
                await run_in_threadpool(
                    db.mark_paid,
                    audit_id,
                    stripe_session_id=str(session.get("id", "")),
                    at=datetime.now(UTC),
                )
        return JSONResponse({"received": True})

    return app


__all__ = [
    "MESSAGES",
    "client_ip",
    "create_app",
    "message",
    "hash_token",
    "sign_stripe_payload",
    "stripe_checkout",
    "token_matches",
    "verify_stripe_signature",
]
