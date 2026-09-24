"""The audit service: upload a backtest, read the verdict, optionally pay.

FastAPI, imported lazily so the core package never depends on the ``web``
extra. Every report URL carries a per-audit secret token; a wrong token is
a 404 (never a 403) so the service does not confirm that an id exists.
Stripe is optional: without every Stripe variable the service is in free
mode, serves watermarked reports and refuses to create checkouts. The
webhook signature is verified locally with the documented HMAC scheme so
the payment path needs no SDK to be trustworthy.
"""

# No ``from __future__ import annotations`` here: FastAPI resolves the route
# signatures at definition time, and the names it needs are imported inside
# ``create_app`` so the module stays importable without the ``web`` extra.

import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from quant_trade.audit.engine import run_audit
from quant_trade.audit.pages import error_page, landing
from quant_trade.audit.report import render
from quant_trade.audit.schema import AuditResult, DeclaredMetadata, ParseError, build_inputs
from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import REQUIRE_WEB, Store, make_store
from quant_trade.evidence.canonical_json import canonical_dumps

CheckoutFactory = Callable[[AuditSettings, str, str], str]

STRIPE_TOLERANCE_SECONDS = 300
_EMAIL_MAX = 254


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


def _client_ip(request: Any) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _wants_json(request: Any) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _valid_email(value: str) -> bool:
    value = value.strip()
    return 3 <= len(value) <= _EMAIL_MAX and "@" in value and "." in value.rsplit("@", 1)[-1]


def create_app(settings: AuditSettings | None = None, store: Store | None = None) -> Any:
    try:
        from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
        from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
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
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def _locale(value: str | None) -> str:
        return value if value in ("es", "en") else "es"

    def _html_error(request: Request, status: int, message: str, locale: str) -> Response:
        if _wants_json(request):
            return JSONResponse({"error": message}, status_code=status)
        return HTMLResponse(error_page(message, locale=locale), status_code=status)

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
                raise HTTPException(
                    status_code=413,
                    detail=f"the {what} file exceeds {cfg.max_upload_bytes:,} bytes",
                )
            chunks.append(chunk)
        data = b"".join(chunks)
        return data or None

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "free_mode": cfg.free_mode,
            "stripe_enabled": cfg.stripe_enabled,
            "database": cfg.database_kind,
        }

    @app.get("/", response_class=HTMLResponse)
    def index(lang: str | None = None, joined: int = 0, error: str | None = None) -> str:
        return landing(
            locale=_locale(lang),
            free_mode=cfg.free_mode,
            price_usd=cfg.price_usd,
            joined=bool(joined),
            error=error,
        )

    @app.post("/waitlist")
    def waitlist(email: Annotated[str, Form()], lang: Annotated[str, Form()] = "es") -> Response:
        locale = _locale(lang)
        if not _valid_email(email):
            return RedirectResponse(f"/?lang={locale}&error=email", status_code=303)
        db.add_waitlist(email, at=datetime.now(UTC))
        return RedirectResponse(f"/?lang={locale}&joined=1", status_code=303)

    @app.post("/audits")
    async def create_audit(
        request: Request,
        equity: Annotated[UploadFile, File()],
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
    ) -> Response:
        loc = _locale(locale)
        if consent.lower() not in ("on", "yes", "true", "1"):
            return _html_error(request, 400, "consent is required", loc)
        ip = _client_ip(request)
        since = datetime.now(UTC) - timedelta(hours=1)
        if db.count_uploads_since(ip, since) >= cfg.max_uploads_per_hour_per_ip:
            return _html_error(request, 429, "too many audits from this address; try later", loc)
        try:
            equity_bytes = await _read_limited(equity, what="equity")
            trades_bytes = await _read_limited(trades, what="trades")
            benchmark_bytes = await _read_limited(benchmark, what="benchmark")
            variants_bytes = await _read_limited(variants, what="variants")
        except HTTPException as exc:
            return _html_error(request, exc.status_code, str(exc.detail), loc)
        if not equity_bytes:
            return _html_error(request, 400, "the equity file is required", loc)
        try:
            declared = DeclaredMetadata(
                trials=trials,
                cost_bps_per_side=cost_bps,
                oos_start=oos_start.strip() or None,
                description=description,
                benchmark_applicable=benchmark_applicable.lower() not in ("no", "false", "0"),
                locale=loc,
            )
            inputs = build_inputs(
                equity_bytes,
                declared,
                trades_bytes=trades_bytes,
                benchmark_bytes=benchmark_bytes,
                variants_bytes=variants_bytes,
            )
        except (ParseError, ValueError) as exc:
            return _html_error(request, 400, str(exc), loc)
        now = datetime.now(UTC)
        result = run_audit(inputs, bootstrap_samples=cfg.bootstrap_samples, now=now)
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
        db.create_audit(
            audit_id=result.audit_id,
            created_at=now,
            token_hash=hash_token(token),
            client_ip=ip,
            declared_json=canonical_dumps(result.declared),
            result_json=json_text,
            report_html=html_text,
            overall_class=result.verdict.overall,
            digests=result.inputs["digests"],
            equity_csv=equity_bytes,
            trades_csv=trades_bytes,
            benchmark_csv=benchmark_bytes,
            variants_csv=variants_bytes,
        )
        location = f"/audits/{result.audit_id}?token={token}"
        if _wants_json(request):
            return JSONResponse(
                {"audit_id": result.audit_id, "token": token, "location": location},
                status_code=201,
            )
        return RedirectResponse(location, status_code=303)

    def _load(audit_id: str, token: str | None) -> Any:
        record = db.get_audit(audit_id)
        if record is None or not token_matches(record.token_hash, token):
            raise HTTPException(status_code=404, detail="not found")
        if record.purged_at or not record.result_json:
            raise HTTPException(status_code=410, detail="this audit was purged")
        return record

    def _report_html(record: Any, token: str) -> str:
        result = AuditResult.model_validate_json(record.result_json)
        unlockable = not record.paid and cfg.stripe_enabled
        html_text, _ = render(
            result,
            watermark=not record.paid,
            free_mode=cfg.free_mode,
            price_usd=cfg.price_usd,
            checkout_url=f"/audits/{record.id}/checkout?token={token}" if unlockable else None,
        )
        return html_text

    # The ``.json`` route is registered first: ``{audit_id}`` would otherwise
    # swallow the suffix.
    @app.get("/audits/{audit_id}.json")
    def audit_json(audit_id: str, token: str | None = None) -> Response:
        record = _load(audit_id, token)
        if not record.paid and not cfg.free_mode:
            return JSONResponse({"error": "payment required"}, status_code=402)
        return Response(content=record.result_json, media_type="application/json")

    @app.get("/audits/{audit_id}", response_class=HTMLResponse)
    def audit_page(audit_id: str, token: str | None = None) -> str:
        record = _load(audit_id, token)
        return _report_html(record, token or "")

    @app.post("/audits/{audit_id}/checkout")
    def checkout(audit_id: str, token: str | None = None) -> Response:
        record = _load(audit_id, token)
        if not cfg.stripe_enabled:
            return JSONResponse({"error": "payments are not enabled"}, status_code=503)
        if record.paid:
            return RedirectResponse(f"/audits/{audit_id}?token={token}", status_code=303)
        factory: CheckoutFactory = app.state.checkout_factory
        url = factory(cfg, audit_id, token or "")
        return RedirectResponse(url, status_code=303)

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request) -> Response:
        if not cfg.stripe_configured:
            raise HTTPException(status_code=404, detail="not found")
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
                db.mark_paid(
                    audit_id,
                    stripe_session_id=str(session.get("id", "")),
                    at=datetime.now(UTC),
                )
        return JSONResponse({"received": True})

    return app


__all__ = [
    "create_app",
    "hash_token",
    "sign_stripe_payload",
    "stripe_checkout",
    "token_matches",
    "verify_stripe_signature",
]
