"""Terms of service and privacy policy of the audit web service.

The texts describe what the code does, not what a generic SaaS might do:
what the store keeps (audits, uploaded files, access codes, publications,
the waitlist), for how long (``audit purge``), the IP address used for the
upload limit, Stripe as the card processor, the public verification page,
and that no broker key is ever asked for. Every promise in the privacy
policy is one the operator can keep with a CLI command
(``audit purge --yes``, ``audit delete --yes``, ``audit waitlist-remove
--yes``, ``POST /audits/{id}/unpublish``).

Operator details come from the environment and have no default: until they
are set, the pages show a visible placeholder and a warning, never a name
that looks real. A lawyer should review both texts before anyone is
charged (docs/AUDIT_SAAS.md). Both texts must pass the profit-claim guard.
"""

from __future__ import annotations

import html
from dataclasses import dataclass

from quant_trade.audit.accounts import DEVICE_COOKIE, FREE_PREVIEWS_PER_MONTH
from quant_trade.audit.funnel import REF_COOKIE, REF_DAYS
from quant_trade.audit.settings import PACK_CREDITS

#: Date of the current wording. Change it whenever a text below changes.
LEGAL_UPDATED = "2026-09-25"

STRIPE_PRIVACY_URL = "https://stripe.com/privacy"

#: Paths of the two pages per locale; both answer either ``lang``.
LEGAL_PATHS: dict[str, dict[str, str]] = {
    "es": {"terms": "/terminos", "privacy": "/privacidad"},
    "en": {"terms": "/terms", "privacy": "/privacy"},
}

LINK_TEXT: dict[str, dict[str, str]] = {
    "es": {"terms": "Términos del servicio", "privacy": "Política de privacidad"},
    "en": {"terms": "Terms of service", "privacy": "Privacy policy"},
}

_NOT_SET = {"es": "[sin configurar]", "en": "[not configured]"}

_UNCONFIGURED_WARNING = {
    "es": (
        "El operador de este servicio aún no ha completado sus datos (nombre, contacto, "
        "domicilio y jurisdicción). Hasta entonces este texto es un borrador."
    ),
    "en": (
        "The operator of this service has not filled in its details yet (name, contact, "
        "address and jurisdiction). Until then this text is a draft."
    ),
}


@dataclass(frozen=True)
class LegalContext:
    """What the texts need from the settings; built by the web app."""

    operator_name: str = ""
    operator_contact: str = ""
    operator_address: str = ""
    jurisdiction: str = ""
    free_mode: bool = True
    price_usd: float = 0.0
    card_payments: bool = False
    access_codes: bool = False
    pack_price_usd: float = 0.0
    retention_days: int = 30
    max_uploads_per_hour_per_ip: int = 10

    @property
    def configured(self) -> bool:
        return bool(
            self.operator_name
            and self.operator_contact
            and self.operator_address
            and self.jurisdiction
        )


@dataclass(frozen=True)
class LegalText:
    title: str
    warning: str | None
    sections: tuple[tuple[str, tuple[str, ...]], ...]
    updated: str


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _locale(locale: str) -> str:
    return locale if locale in LEGAL_PATHS else "es"


def legal_url(kind: str, locale: str) -> str:
    locale = _locale(locale)
    return f"{LEGAL_PATHS[locale][kind]}?lang={locale}"


def legal_links_html(locale: str) -> str:
    """The two links every page carries next to its notice."""
    locale = _locale(locale)
    links = " · ".join(
        f"<a href='{_e(legal_url(kind, locale))}'>{_e(LINK_TEXT[locale][kind])}</a>"
        for kind in ("terms", "privacy")
    )
    return f"<p class='muted legal'>{links}</p>"


def _value(value: str, locale: str) -> str:
    return value or _NOT_SET[locale]


def _card_refund_es(ctx: LegalContext) -> str:
    """How a refund reaches a card, said only while card payment is on."""
    if not ctx.card_payments:
        return ""
    share = (
        f" Si el informe era parte de un paquete, devolvemos su parte (USD "
        f"{ctx.pack_price_usd / PACK_CREDITS:.2f}) o, si lo prefieres, un crédito nuevo."
        if ctx.pack_price_usd
        else ""
    )
    return (
        "Si pagaste con tarjeta, el reembolso vuelve a la misma tarjeta a través de Stripe; tu "
        f"banco puede tardar unos días en mostrarlo.{share}"
    )


def _card_refund_en(ctx: LegalContext) -> str:
    if not ctx.card_payments:
        return ""
    share = (
        f" If the report was part of a pack, we refund its share (USD "
        f"{ctx.pack_price_usd / PACK_CREDITS:.2f}) or, if you prefer, issue a new credit."
        if ctx.pack_price_usd
        else ""
    )
    return (
        "If you paid by card, the refund goes back to the same card through Stripe; your bank "
        f"may take a few days to show it.{share}"
    )


def _price_es(ctx: LegalContext) -> tuple[str, ...]:
    if ctx.free_mode:
        return (
            "Ahora mismo el servicio es gratuito: el informe completo se entrega con marca "
            "de agua. Si eso cambia, el precio se muestra antes de pagar y no afecta a las "
            "auditorías ya hechas.",
        )
    lines = [
        "La vista previa es gratuita. El informe completo cuesta "
        f"USD {ctx.price_usd:.2f} por auditoría."
    ]
    if ctx.card_payments:
        lines.append(
            "El pago con tarjeta lo procesa Stripe en su propia página de pago. El cargo se "
            "hace en dólares estadounidenses (USD); tu banco puede cobrar una comisión por el "
            "cambio de moneda. Nosotros no vemos ni guardamos los datos de tu tarjeta."
        )
    if ctx.access_codes:
        lines.append(
            "También puedes pagar fuera de la web (transferencia, Mercado Pago u otro medio "
            "que acordemos) y recibir un código de acceso. Cada crédito del código desbloquea "
            "una auditoría. El código se entrega una sola vez: guárdalo."
        )
    if ctx.pack_price_usd and ctx.card_payments:
        lines.append(
            f"El paquete de {PACK_CREDITS} informes cuesta USD {ctx.pack_price_usd:.2f}. Si lo "
            "pagas con tarjeta desde un informe, ese informe queda desbloqueado y recibes un "
            f"código con {PACK_CREDITS - 1} créditos para los siguientes; el código aparece en "
            "ese informe cada vez que lo abres."
        )
    elif ctx.pack_price_usd and ctx.access_codes:
        lines.append(
            f"También vendemos códigos de {PACK_CREDITS} créditos por "
            f"USD {ctx.pack_price_usd:.2f}; cada crédito desbloquea una auditoría."
        )
    if ctx.card_payments or ctx.access_codes:
        lines.append(
            "Si el informe completo lee mal tu archivo (operaciones, saldo o fechas que no "
            "coinciden con lo que muestra tu plataforma) y no podemos corregirlo, escríbenos con "
            "el identificador del informe: devolvemos el importe de ese informe o, si lo "
            "prefieres, entregamos un crédito nuevo."
        )
    lines.append(
        "Si pagaste y el informe completo no se generó por un fallo del servicio, escríbenos: "
        "devolvemos el importe o entregamos un código nuevo. Como el informe se entrega al "
        "momento, un informe ya desbloqueado no se reembolsa, salvo que la ley aplicable "
        "diga otra cosa."
    )
    if ctx.card_payments:
        lines.append(_card_refund_es(ctx))
    return tuple(lines)


def _price_en(ctx: LegalContext) -> tuple[str, ...]:
    if ctx.free_mode:
        return (
            "The service is currently free: the full report comes with a watermark. If that "
            "changes, the price is shown before you pay and audits already made are not "
            "affected.",
        )
    lines = [f"The preview is free. The full report costs USD {ctx.price_usd:.2f} per audit."]
    if ctx.card_payments:
        lines.append(
            "Card payments are processed by Stripe on its own checkout page. The charge is in "
            "US dollars (USD); your bank may add a currency conversion fee. We never see or "
            "store your card details."
        )
    if ctx.access_codes:
        lines.append(
            "You can also pay outside the site (bank transfer, Mercado Pago or another method "
            "we agree on) and receive an access code. Each credit on the code unlocks one "
            "audit. The code is handed over once: keep it."
        )
    if ctx.pack_price_usd and ctx.card_payments:
        lines.append(
            f"The pack of {PACK_CREDITS} reports costs USD {ctx.pack_price_usd:.2f}. If you pay "
            "for it by card from a report, that report is unlocked and you get a code with "
            f"{PACK_CREDITS - 1} credits for the next ones; the code shows on that report every "
            "time you open it."
        )
    elif ctx.pack_price_usd and ctx.access_codes:
        lines.append(
            f"We also sell codes with {PACK_CREDITS} credits for USD {ctx.pack_price_usd:.2f}; "
            "each credit unlocks one audit."
        )
    if ctx.card_payments or ctx.access_codes:
        lines.append(
            "If the full report misreads your file (trades, balance or dates that do not match "
            "what your platform shows) and we cannot fix it, write to us with the report's "
            "identifier: we refund that report or, if you prefer, issue a new credit."
        )
    lines.append(
        "If you paid and the full report was not produced because of a fault in the service, "
        "write to us: we refund the amount or issue a new code. Because the report is "
        "delivered at once, a report already unlocked is not refunded unless the applicable "
        "law says otherwise."
    )
    if ctx.card_payments:
        lines.append(_card_refund_en(ctx))
    return tuple(lines)


def terms_text(ctx: LegalContext, locale: str = "es") -> LegalText:
    locale = _locale(locale)
    name = _value(ctx.operator_name, locale)
    address = _value(ctx.operator_address, locale)
    contact = _value(ctx.operator_contact, locale)
    jurisdiction = _value(ctx.jurisdiction, locale)
    warning = None if ctx.configured else _UNCONFIGURED_WARNING[locale]
    if locale == "en":
        sections: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("Provider", (f'{name}, {address}. Contact: {contact} ("we").',)),
            (
                "What the service is",
                (
                    "An automated statistical analysis of the backtest or account files you "
                    "upload: a platform report, an optimisation export, an equity curve or "
                    "returns and, if you supply them, trades, a benchmark and variants. The "
                    "output is a report with a verdict by dimension and every value labelled "
                    "by its evidence (MEASURED, DECLARED or NOT_MEASURED).",
                ),
            ),
            (
                "What it is not",
                (
                    "The service is not investment, financial, legal or tax advice. It "
                    "recommends no purchase, sale or trade. It executes nothing, holds no "
                    "funds, asks for no broker or exchange keys and connects to no broker or "
                    "exchange. It does not predict future results: a favourable verdict means "
                    "we found no evidence of overfitting in what you supplied, nothing more. "
                    "The prop-firm challenge simulator and the resampled risk are estimates "
                    "from your own data, not forecasts.",
                ),
            ),
            (
                "Your files",
                (
                    "You confirm you have the right to upload the files and that they contain "
                    "no third-party personal data. They are used only to produce your report. "
                    "What we keep and for how long is set out in the privacy policy.",
                    f"Uploads are limited to {ctx.max_uploads_per_hour_per_ip} per hour per IP "
                    "address. Do not upload files that are not backtest or account results.",
                ),
            ),
            (
                "Your account",
                (
                    (
                        "A new account's first file is a free full report, once per account, "
                        "browser and file, and a few per network address each month. "
                        f"After it, the free preview needs an account: {FREE_PREVIEWS_PER_MONTH} "
                        "a calendar month per account, also counted per network address. Past "
                        "that, each file is a paid report. "
                        + (
                            "A report paid with an access code works without an account. "
                            if ctx.access_codes
                            else ""
                        )
                        + "Each report's private link works without an account."
                        if not ctx.free_mode
                        else "The account is optional while the service is in free mode."
                    ),
                    "The account shows your reports, credits and purchases in one place.",
                    "You are responsible for your password. If you forget it, we send you a "
                    "one-time link after checking that you write from the account's e-mail. "
                    "You can delete the account at any time from its page.",
                    *(
                        (
                            "An access code saved on an account still belongs to the code's "
                            "holder: its credits are used from that account or by typing the "
                            "code.",
                        )
                        if ctx.access_codes
                        else ()
                    ),
                ),
            ),
            (
                "Accuracy",
                (
                    "The report depends entirely on the files you upload, which are not "
                    "checked against any broker. Values marked DECLARED come from your own "
                    "statements. Values marked NOT_MEASURED could not be computed. We do not "
                    "warrant that the report detects every error in a backtest.",
                ),
            ),
            ("Price and payment", _price_en(ctx)),
            (
                "Your private link",
                (
                    "Your report's link carries a secret token. Anyone holding the link can "
                    "open the report, unlock it and publish its verification page: keep it "
                    "like a password. We store only a hash of the token, so we cannot resend "
                    "a lost link.",
                ),
            ),
            (
                "Badge and verification page",
                (
                    "If you publish the verification, the page shows the class, the "
                    "dimensions, the hashes, the date and a fixed notice; never your files, "
                    "trades or description. You may use the badge on your site, Telegram, "
                    "forums or videos, always linked to the verification page. You may not "
                    "present it as a promise of results, as an endorsement of a product, or "
                    "next to return claims; if you do, we may remove the publication.",
                ),
            ),
            (
                "Limitation of liability",
                (
                    "To the fullest extent permitted by law, our total liability to you is "
                    "limited to the amount paid for the audit in question. We are not liable "
                    "for investment losses or for decisions taken on the basis of the report.",
                ),
            ),
            (
                "Ownership",
                (
                    "The report is yours. The engine, wording and format are ours. You may "
                    "share the report; you may not resell the service without written "
                    "agreement.",
                ),
            ),
            ("Governing law and venue", (f"{jurisdiction}.",)),
            (
                "Changes",
                (
                    "Changes are posted on this page with a new date. An audit is governed "
                    "by the terms in force on the day it was made.",
                ),
            ),
        )
        return LegalText("Terms of service", warning, sections, LEGAL_UPDATED)
    sections = (
        ("Prestador", (f'{name}, {address}. Contacto: {contact} ("nosotros").',)),
        (
            "Qué es el servicio",
            (
                "Un análisis estadístico automatizado de los archivos de backtest o de cuenta "
                "que subes: el informe de tu plataforma, una exportación de optimización, una "
                "curva de equity o de retornos y, si los aportas, operaciones, benchmark y "
                "variantes. El resultado es un informe con un veredicto por dimensiones y "
                "cada valor etiquetado según su evidencia (MEASURED, DECLARED o NOT_MEASURED).",
            ),
        ),
        (
            "Qué no es",
            (
                "El servicio no es asesoría de inversión, financiera, legal ni fiscal. No "
                "recomienda comprar, vender ni operar ningún instrumento. No ejecuta "
                "operaciones, no custodia fondos, no pide claves de bróker ni de exchange y no "
                "se conecta a tu bróker ni a tu exchange. No predice resultados futuros: un "
                "veredicto favorable significa que no encontramos evidencia de sobreajuste en "
                "lo que aportaste, nada más. El simulador de reto de prop firm y el riesgo "
                "remuestreado son estimaciones hechas con tus propios datos, no predicciones.",
            ),
        ),
        (
            "Tus archivos",
            (
                "Declaras que tienes derecho a subir los archivos y que no contienen datos "
                "personales de terceros. Se usan solo para producir tu informe. Qué guardamos "
                "y durante cuánto tiempo se explica en la política de privacidad.",
                f"Las subidas se limitan a {ctx.max_uploads_per_hour_per_ip} por hora por "
                "dirección IP. No subas archivos que no sean resultados de backtest o de "
                "cuenta.",
            ),
        ),
        (
            "Tu cuenta",
            (
                (
                    "El primer archivo de una cuenta nueva es un informe completo gratis, una vez "
                    "por cuenta, navegador y archivo, y unos pocos por dirección de red al mes. "
                    "Después, la vista previa gratis necesita una cuenta: "
                    f"{FREE_PREVIEWS_PER_MONTH} por mes calendario y por cuenta, "
                    "contadas también por dirección de red. "
                    "Pasado ese número, cada archivo es un informe de pago. "
                    + (
                        "Un informe pagado con código de acceso funciona sin cuenta. "
                        if ctx.access_codes
                        else ""
                    )
                    + "El enlace privado de cada informe funciona sin cuenta."
                    if not ctx.free_mode
                    else "La cuenta es opcional mientras el servicio está en modo gratuito."
                ),
                "La cuenta sirve para ver en un solo lugar tus informes, tus créditos y tus "
                "compras.",
                "Eres responsable de tu contraseña. Si la olvidas, te enviamos un enlace de un "
                "solo uso después de comprobar que nos escribes desde el correo de la cuenta. "
                "Puedes borrar la cuenta cuando quieras desde su página.",
                *(
                    (
                        "Un código de acceso guardado en una cuenta sigue siendo del titular "
                        "del código: sus créditos se usan desde esa cuenta o escribiendo el "
                        "código.",
                    )
                    if ctx.access_codes
                    else ()
                ),
            ),
        ),
        (
            "Exactitud",
            (
                "El informe depende por completo de los archivos que subes, que no se cotejan "
                "con ningún bróker. Los valores marcados DECLARED provienen de tus propias "
                "declaraciones. Los valores marcados NOT_MEASURED no pudieron calcularse. No "
                "garantizamos que el informe detecte todos los errores de un backtest.",
            ),
        ),
        ("Precio y pago", _price_es(ctx)),
        (
            "Tu enlace privado",
            (
                "El enlace de tu informe lleva un token secreto. Quien tenga el enlace puede "
                "abrir el informe, desbloquearlo y publicar su página de verificación: "
                "guárdalo como una contraseña. Solo guardamos un hash del token, así que no "
                "podemos reenviarte un enlace perdido.",
            ),
        ),
        (
            "Sello y página de verificación",
            (
                "Si publicas la verificación, la página muestra la clase, las dimensiones, "
                "los hashes, la fecha y un aviso fijo; nunca tus archivos, operaciones ni "
                "descripción. Puedes usar el sello en tu web, Telegram, foros o vídeos, "
                "siempre enlazado a la página de verificación. No puedes presentarlo como "
                "promesa de resultados, como respaldo de un producto ni junto a afirmaciones "
                "de rentabilidad; si lo haces, podemos retirar la publicación.",
            ),
        ),
        (
            "Limitación de responsabilidad",
            (
                "En la máxima medida que permita la ley, nuestra responsabilidad total frente "
                "a ti se limita al importe pagado por la auditoría en cuestión. No respondemos "
                "de pérdidas de inversión ni de decisiones tomadas con base en el informe.",
            ),
        ),
        (
            "Propiedad",
            (
                "El informe es tuyo. El motor, los textos y el formato son nuestros. Puedes "
                "compartir el informe; no puedes revender el servicio sin acuerdo escrito.",
            ),
        ),
        ("Ley aplicable y jurisdicción", (f"{jurisdiction}.",)),
        (
            "Cambios",
            (
                "Publicamos cualquier cambio en esta página con una fecha nueva. Cada "
                "auditoría se rige por los términos vigentes el día en que se hizo.",
            ),
        ),
    )
    return LegalText("Términos del servicio", warning, sections, LEGAL_UPDATED)


def _stripe_keeps(ctx: LegalContext, locale: str) -> tuple[str, ...]:
    """What a card payment leaves with us and what Stripe receives; empty while off."""
    if not ctx.card_payments:
        return ()
    if locale == "en":
        return (
            "When you pay by card: the Stripe checkout session id, the payment date and, for "
            "a pack, the hash of the pack's access code.",
            "Stripe receives your card details, the e-mail address you type on its checkout "
            "page (it sends the receipt there) and your card's country, plus the report id and "
            "whether you bought one report or the pack. Stripe processes them under its own "
            f"policy: {STRIPE_PRIVACY_URL}. We never see your card details.",
        )
    return (
        "Si pagas con tarjeta: el identificador de la sesión de pago de Stripe, la fecha del "
        "pago y, si compras el paquete, el hash de su código de acceso.",
        "Stripe recibe los datos de tu tarjeta, el correo que escribes en su página de pago "
        "(ahí te envía el recibo) y el país de tu tarjeta, además del identificador del "
        "informe y si compraste un informe o el paquete. Stripe los trata según su propia "
        f"política: {STRIPE_PRIVACY_URL}. Nosotros nunca vemos los datos de tu tarjeta.",
    )


def privacy_text(ctx: LegalContext, locale: str = "es") -> LegalText:
    locale = _locale(locale)
    name = _value(ctx.operator_name, locale)
    address = _value(ctx.operator_address, locale)
    contact = _value(ctx.operator_contact, locale)
    days = ctx.retention_days
    limit = ctx.max_uploads_per_hour_per_ip
    warning = None if ctx.configured else _UNCONFIGURED_WARNING[locale]
    if locale == "en":
        sections: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("Who is responsible", (f"{name}, {address}. Contact: {contact}.",)),
            (
                "What we keep",
                (
                    "The files you upload (platform report, optimisation export, equity "
                    "curve, trades, benchmark, variants) and the SHA-256 hash of each.",
                    "What you declare in the form, including the optional description, and "
                    "the report produced from it.",
                    "The IP address the upload came from, to enforce the limit of "
                    f"{limit} uploads per hour per address and to stop abuse.",
                    "A hash of your report's private token, never the token itself.",
                    *_stripe_keeps(ctx, "en"),
                    "When you redeem an access code: which code unlocked the audit, by its "
                    "internal id. Codes are stored only as a hash.",
                    "When you publish a verification page: its public id and the date.",
                    "When you download your report as a PDF or JSON: the SHA-256 hash of that "
                    "file, so anyone holding it can check at /check that it was not edited. "
                    "A file checked there is read and discarded, never kept.",
                    "When you join the updates list: your e-mail address.",
                    "If you create an account: your e-mail address, a scrypt hash of your "
                    "password (never the password), which reports and access codes are on it, "
                    "and a hash of each sign-in session. There is no e-mail check yet and we "
                    "send no e-mail.",
                    "To count free previews: which account used each one, when, and the "
                    "network address it came from. The address is cleared with the rest "
                    f"after {days} days.",
                    "For the free first full report: a random identifier of your browser "
                    f"(a cookie named {DEVICE_COOKIE}, stored by us only as a hash), the "
                    "SHA-256 of the file and the network address, so the same browser or file "
                    "gets it only once. The address is cleared after "
                    f"{days} days; the two hashes stay, even if you delete your account and "
                    "without your e-mail, so the offer cannot be repeated.",
                    "To know which of our own links brings visitors: visits to the home "
                    "and case pages are counted per day, language and link tag (such as "
                    "?ref=f4 in a link we posted), with no address and no cookie. When you "
                    f"arrive from a tagged link, a cookie named {REF_COOKIE} keeps only that "
                    f"tag for {REF_DAYS} days, and if you create an account the tag is kept "
                    "with it until you delete the account.",
                ),
            ),
            (
                "What we do not keep",
                (
                    "We never ask for or store broker or exchange keys, trading account "
                    "passwords or card details. There is no third-party analytics or "
                    "advertising on these pages. The only cookies are our own: one that keeps "
                    "you signed in, one that protects the sign-in forms, one that marks "
                    "your browser for the free first report and one that remembers which of "
                    "our links brought you; none tracks you across sites "
                    "or is shared. Our own access "
                    "log keeps only a shortened address (the last part of the IP is "
                    "removed) and never the report link's secret. Our hosting provider may "
                    "keep its own request logs, with full IP addresses, for its own "
                    "retention period.",
                ),
            ),
            (
                "What it is used for",
                (
                    "To produce and show your report, to enforce the upload limit, to record "
                    "a payment or a redeemed code, to show a verification page you chose to "
                    "publish, and to write to the updates list. We do not sell or share your "
                    "data and do not use it for advertising.",
                ),
            ),
            (
                "How long we keep it",
                (
                    f"Unpaid audits: after {days} days we delete the files, the report, what "
                    "you declared and the description. The id, the file hashes, the class "
                    "and the date remain so the record stays checkable.",
                    f"The upload IP address is deleted in that same clean-up after {days} "
                    "days, for paid audits too.",
                    "Paid audits and your free first full report: kept so you can reopen the "
                    "report, until you delete them with your account or ask us to delete them.",
                    "Verification page: public until you withdraw it from your report or ask us to"
                    " withdraw it or to delete the audit. If you published it, the clean-up keeps "
                    "only what that page shows (class, dimension statuses, hashes, dates, trial "
                    "counts and engine version), so the page and its badge keep working.",
                    "Updates list: until you ask to be removed.",
                    "Account: until you delete it from your account page or ask us to. "
                    "Deleting it removes the e-mail, the password hash, the sessions and the "
                    "list of your reports and codes; the reports follow the rules above unless "
                    "you choose to delete them too. A sign-in session ends after 30 days or "
                    "when you sign out.",
                ),
            ),
            (
                "Who can see it",
                (
                    "Only the operator, and the hosting and database providers that store "
                    "it for us."
                    + (
                        " Stripe sees what it needs to take a card payment."
                        if ctx.card_payments
                        else ""
                    )
                    + " A verification page, only if you publish it, shows the class, the "
                    "dimensions, the hashes, the date and a fixed notice; never your files, "
                    "trades, description or token.",
                    "The data may be hosted outside your country, on the servers of our "
                    "hosting provider.",
                ),
            ),
            (
                "Your rights",
                (
                    f"Write to {contact} to ask for access to, a copy of, or the deletion of "
                    "your data. To show the audit is yours, include its private link. "
                    "Deletion removes everything we hold on that audit: files, report, "
                    "hashes, class and verification page. To leave the updates list, write "
                    "from that address. You can delete your account yourself from your "
                    "account page, and download a copy of what it holds there ('Download my "
                    "data'). We answer within 30 days.",
                    "You can also complain to the data protection authority of your country.",
                ),
            ),
            (
                "Changes",
                ("Changes are posted on this page with a new date.",),
            ),
        )
        return LegalText("Privacy policy", warning, sections, LEGAL_UPDATED)
    sections = (
        ("Responsable", (f"{name}, {address}. Contacto: {contact}.",)),
        (
            "Qué guardamos",
            (
                "Los archivos que subes (informe de la plataforma, exportación de "
                "optimización, curva de equity, operaciones, benchmark, variantes) y el hash "
                "SHA-256 de cada uno.",
                "Lo que declaras en el formulario, incluida la descripción opcional, y el "
                "informe que se genera.",
                "La dirección IP desde la que subes, para aplicar el límite de "
                f"{limit} subidas por hora por dirección y frenar abusos.",
                "Un hash del token privado de tu informe, nunca el token.",
                *_stripe_keeps(ctx, "es"),
                "Si canjeas un código de acceso: qué código desbloqueó la auditoría, por su "
                "identificador interno. Los códigos se guardan solo como hash.",
                "Si publicas una página de verificación: su identificador público y la fecha.",
                "Si descargas tu informe en PDF o JSON: el hash SHA-256 de ese archivo, para "
                "que quien lo tenga pueda comprobar en /comprobar que no se editó. Un archivo "
                "que se comprueba ahí se lee y se descarta, nunca se guarda.",
                "Si te apuntas a la lista de avisos: tu correo.",
                "Si creas una cuenta: tu correo, un hash scrypt de tu contraseña (nunca la "
                "contraseña), qué informes y códigos de acceso tiene y un hash de cada sesión "
                "iniciada. Todavía no comprobamos el correo ni enviamos correos.",
                "Para contar las vistas previas gratis: qué cuenta usó cada una, cuándo y "
                f"desde qué dirección de red. La dirección se borra con lo demás a los {days} "
                "días.",
                "Para el primer informe completo gratis: un identificador al azar de tu "
                f"navegador (una cookie llamada {DEVICE_COOKIE}, que guardamos solo como hash), "
                "el SHA-256 del archivo y la dirección de red, para que el mismo navegador o "
                f"archivo lo reciba una sola vez. La dirección se borra a los {days} días; los "
                "dos hashes se quedan, aunque borres tu cuenta y sin tu correo, para que la "
                "oferta no se repita.",
                "Para saber cuál de nuestros propios enlaces trae visitas: las visitas a la "
                "página principal y a las de cada caso se cuentan por día, idioma y etiqueta "
                "del enlace (como ?ref=f4 en un enlace que publicamos), sin dirección ni "
                f"cookie. Si llegas desde un enlace con etiqueta, una cookie llamada {REF_COOKIE} "
                f"guarda solo esa etiqueta durante {REF_DAYS} días y, si creas una cuenta, la "
                "etiqueta se queda con ella hasta que la borres.",
            ),
        ),
        (
            "Qué no guardamos",
            (
                "Nunca pedimos ni guardamos claves de bróker ni de exchange, contraseñas de "
                "cuentas de trading ni datos de tarjeta. No hay analítica ni publicidad de "
                "terceros en estas páginas. Las únicas cookies son nuestras: una que mantiene "
                "tu sesión iniciada, otra que protege los formularios de acceso, otra que "
                "marca tu navegador para el primer informe gratis y otra que recuerda cuál de "
                "nuestros enlaces te trajo; ninguna te sigue por otros "
                "sitios ni se comparte. Nuestro propio "
                "registro de accesos guarda solo una dirección acortada (se quita la última "
                "parte de la IP) y nunca el secreto del enlace al informe. Nuestro proveedor "
                "de alojamiento puede guardar sus propios registros de peticiones, con la IP "
                "completa, durante su propio plazo de conservación.",
            ),
        ),
        (
            "Para qué los usamos",
            (
                "Para producir y mostrarte tu informe, aplicar el límite de subidas, "
                "registrar un pago o un código canjeado, mostrar la página de verificación "
                "que decidiste publicar y escribir a la lista de avisos. No vendemos ni "
                "cedemos tus datos y no los usamos para publicidad.",
            ),
        ),
        (
            "Cuánto tiempo los guardamos",
            (
                f"Auditorías no pagadas: a los {days} días borramos los archivos, el informe, "
                "lo que declaraste y la descripción. Quedan el identificador, los hashes de "
                "los archivos, la clase y la fecha, para que el registro siga siendo "
                "comprobable.",
                f"La IP de la subida se borra en esa misma limpieza a los {days} días, también "
                "en las auditorías pagadas.",
                "Auditorías pagadas y tu primer informe completo gratis: se conservan para que "
                "puedas volver a abrir el informe, hasta que los borres con tu cuenta o nos "
                "pidas borrarlos.",
                "Página de verificación: pública hasta que la retires desde tu informe o nos pidas"
                " retirarla o borrar la auditoría. Si la publicaste, la limpieza conserva solo lo "
                "que muestra esa página (clase, estado de cada dimensión, hashes, fechas, número "
                "de intentos y versión del motor), para que la página y su sello sigan "
                "funcionando.",
                "Lista de avisos: hasta que pidas darte de baja.",
                "Cuenta: hasta que la borres desde la página de tu cuenta o nos pidas "
                "borrarla. El borrado elimina el correo, el hash de la contraseña, las sesiones "
                "y la lista de tus informes y códigos; los informes siguen las reglas de arriba "
                "salvo que elijas borrarlos también. Una sesión termina a los 30 días o cuando "
                "sales.",
            ),
        ),
        (
            "Quién puede verlos",
            (
                "Solo el operador y los proveedores de alojamiento y de base de datos que los "
                "guardan por nosotros."
                + (
                    " Stripe ve lo que necesita para cobrar con tarjeta."
                    if ctx.card_payments
                    else ""
                )
                + " Una página de verificación, solo si la publicas, muestra la clase, las "
                "dimensiones, los hashes, la fecha y un aviso fijo; nunca tus archivos, "
                "operaciones, descripción ni el token.",
                "Los datos pueden alojarse fuera de tu país, en los servidores de nuestro "
                "proveedor de alojamiento.",
            ),
        ),
        (
            "Tus derechos",
            (
                f"Escribe a {contact} para pedir acceso, una copia o el borrado de tus datos. "
                "Para demostrar que la auditoría es tuya, incluye su enlace privado. El "
                "borrado elimina todo lo que tenemos de esa auditoría: archivos, informe, "
                "hashes, clase y página de verificación. Para darte de baja de la lista de "
                "avisos, escribe desde ese correo. Tu cuenta la puedes borrar tú desde la "
                "página de tu cuenta, y ahí mismo descargar una copia de lo que guarda "
                "(«Descargar mis datos»). Respondemos en un plazo de 30 días.",
                "También puedes reclamar ante la autoridad de protección de datos de tu país.",
            ),
        ),
        (
            "Cambios",
            ("Publicamos cualquier cambio en esta página con una fecha nueva.",),
        ),
    )
    return LegalText("Política de privacidad", warning, sections, LEGAL_UPDATED)


__all__ = [
    "LEGAL_PATHS",
    "LEGAL_UPDATED",
    "LINK_TEXT",
    "STRIPE_PRIVACY_URL",
    "LegalContext",
    "LegalText",
    "legal_links_html",
    "legal_url",
    "privacy_text",
    "terms_text",
]
