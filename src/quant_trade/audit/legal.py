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

from quant_trade.audit.accounts import (
    DEVICE_COOKIE,
    FREE_PREVIEWS_PER_MONTH,
    REFERRAL_CREDITS,
    REFERRAL_MONTHLY_CAP,
)
from quant_trade.audit.funnel import REF_COOKIE, REF_DAYS, SEEN_COOKIE
from quant_trade.audit.settings import PACK_CREDITS

#: Date of the current wording. Change it whenever a text below changes.
LEGAL_UPDATED = "2026-09-27"

STRIPE_PRIVACY_URL = "https://stripe.com/privacy"

#: Paths of the two pages per locale; both answer either ``lang``.
LEGAL_PATHS: dict[str, dict[str, str]] = {
    "es": {"terms": "/terminos", "privacy": "/privacidad"},
    "en": {"terms": "/terms", "privacy": "/privacy"},
    "pt": {"terms": "/pt/termos", "privacy": "/pt/privacidade"},
}

LINK_TEXT: dict[str, dict[str, str]] = {
    "es": {"terms": "Términos del servicio", "privacy": "Política de privacidad"},
    "en": {"terms": "Terms of service", "privacy": "Privacy policy"},
    "pt": {"terms": "Termos do serviço", "privacy": "Política de privacidade"},
}

_NOT_SET = {"es": "[sin configurar]", "en": "[not configured]", "pt": "[não configurado]"}

_LOCAL_REVIEW_PT = "Versão em português pendente de revisão jurídica local."

_UNCONFIGURED_WARNING = {
    "es": (
        "El operador de este servicio aún no ha completado sus datos (nombre, contacto, "
        "domicilio y jurisdicción). Hasta entonces este texto es un borrador."
    ),
    "en": (
        "The operator of this service has not filled in its details yet (name, contact, "
        "address and jurisdiction). Until then this text is a draft."
    ),
    "pt": (
        "O operador ainda não informou seus dados (nome, contato, endereço e jurisdição). "
        "Até lá, este texto é um rascunho."
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
    email_delivery_ready: bool = False
    email_verification_required: bool = False
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


def _warning(ctx: LegalContext, locale: str) -> str | None:
    if locale == "pt":
        return (
            f"{_UNCONFIGURED_WARNING['pt']} {_LOCAL_REVIEW_PT}"
            if not ctx.configured
            else _LOCAL_REVIEW_PT
        )
    return None if ctx.configured else _UNCONFIGURED_WARNING[locale]


def _account_recovery(ctx: LegalContext, locale: str) -> str:
    if ctx.email_delivery_ready:
        return {
            "es": (
                "Si olvidas la contraseña, puedes pedir un enlace de un solo uso por correo "
                "o usar tu clave de recuperación. Puedes borrar la cuenta desde su página."
            ),
            "en": (
                "If you forget your password, you can request a one-time e-mail link or use "
                "your recovery key. You can delete the account from its page."
            ),
            "pt": (
                "Se você esquecer a senha, pode pedir um link de uso único por e-mail ou usar "
                "sua chave de recuperação. Você pode excluir a conta pela própria página."
            ),
        }[locale]
    return {
        "es": (
            "Si la olvidas, te enviamos un enlace de un solo uso después de comprobar que nos "
            "escribes desde el correo de la cuenta. Puedes borrar la cuenta cuando quieras "
            "desde su página."
        ),
        "en": (
            "If you forget it, we send you a one-time link after checking that you write from "
            "the account's e-mail. You can delete the account at any time from its page."
        ),
        "pt": (
            "Se você esquecê-la, enviamos um link de uso único depois de confirmar que você "
            "escreve do e-mail da conta. Você pode excluir a conta pela própria página."
        ),
    }[locale]


def _account_email_status(ctx: LegalContext, locale: str) -> str:
    if ctx.email_delivery_ready:
        return {
            "es": (
                "Enviamos enlaces de confirmación, cambio de correo y recuperación de "
                "contraseña cuando se solicitan; también avisos de compra o cargo adicional "
                "a correos confirmados. No son mensajes publicitarios."
            ),
            "en": (
                "We send confirmation, e-mail change and password recovery links when "
                "requested; confirmed addresses also receive purchase or additional-charge "
                "notices. These are not advertising messages."
            ),
            "pt": (
                "Enviamos links de confirmação, troca de e-mail e recuperação de senha "
                "quando solicitados; endereços confirmados também recebem avisos de compra "
                "ou cobrança adicional. Não são mensagens publicitárias."
            ),
        }[locale]
    return {
        "es": "Todavía no comprobamos el correo ni enviamos correos.",
        "en": "There is no e-mail check yet and we send no e-mail.",
        "pt": "Ainda não verificamos o e-mail nem enviamos mensagens por e-mail.",
    }[locale]


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


def _card_refund_pt(ctx: LegalContext) -> str:
    if not ctx.card_payments:
        return ""
    share = (
        f" Se o relatório fazia parte de um pacote, devolvemos sua parte (USD "
        f"{ctx.pack_price_usd / PACK_CREDITS:.2f}) ou, se você preferir, emitimos um novo crédito."
        if ctx.pack_price_usd
        else ""
    )
    return (
        "Se você pagou com cartão, o reembolso volta para o mesmo cartão pelo Stripe; "
        f"o banco pode levar alguns dias para mostrá-lo.{share}"
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
    if ctx.card_payments and ctx.email_verification_required:
        lines.append(
            "Para pagar con tarjeta debes confirmar el correo de tu cuenta. Tu primer informe "
            "completo gratis sigue disponible antes de confirmarlo."
        )
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
        "momento, no devolvemos un informe ya desbloqueado por cambio de opinión. Sí "
        "atendemos errores del informe que no podamos corregir, fallos de entrega y los "
        "derechos que conceda la ley aplicable."
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
    if ctx.card_payments and ctx.email_verification_required:
        lines.append(
            "To pay by card, confirm your account e-mail. Your first free full report "
            "remains available before confirmation."
        )
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
        "delivered at once, we do not refund an unlocked report for a change of mind. "
        "We do address report errors we cannot fix, failed delivery and rights under "
        "applicable law."
    )
    if ctx.card_payments:
        lines.append(_card_refund_en(ctx))
    return tuple(lines)


def _price_pt(ctx: LegalContext) -> tuple[str, ...]:
    if ctx.free_mode:
        return (
            "No momento, o serviço é gratuito: o relatório completo tem marca d'água. "
            "Se isso mudar, o preço será mostrado antes do pagamento e não afetará as "
            "auditorias já feitas.",
        )
    lines = [
        f"A prévia é gratuita. O relatório completo custa USD {ctx.price_usd:.2f} por auditoria."
    ]
    if ctx.card_payments and ctx.email_verification_required:
        lines.append(
            "Para pagar com cartão, confirme o e-mail da sua conta. Seu primeiro relatório "
            "completo gratuito continua disponível antes da confirmação."
        )
    if ctx.card_payments:
        lines.append(
            "O pagamento com cartão é processado pelo Stripe na página de pagamento dele. "
            "A cobrança é em dólares dos Estados Unidos (USD); seu banco pode cobrar pela "
            "conversão de moeda. Não vemos nem guardamos os dados do seu cartão."
        )
    if ctx.access_codes:
        lines.append(
            "Você também pode pagar fora do site (transferência, Mercado Pago ou outro meio "
            "acordado) e receber um código de acesso. Cada crédito do código libera uma "
            "auditoria. O código é entregue uma vez; guarde-o."
        )
    if ctx.pack_price_usd and ctx.card_payments:
        lines.append(
            f"O pacote de {PACK_CREDITS} relatórios custa USD {ctx.pack_price_usd:.2f}. "
            "Se você comprar o pacote com cartão a partir de um relatório, esse relatório "
            f"será liberado e você receberá um código com {PACK_CREDITS - 1} créditos para "
            "os próximos; o código aparece no relatório sempre que você o abrir."
        )
    elif ctx.pack_price_usd and ctx.access_codes:
        lines.append(
            f"Também vendemos códigos com {PACK_CREDITS} créditos por "
            f"USD {ctx.pack_price_usd:.2f}; cada crédito libera uma auditoria."
        )
    if ctx.card_payments or ctx.access_codes:
        lines.append(
            "Se o relatório completo ler seu arquivo incorretamente (operações, saldo ou "
            "datas que não correspondem à plataforma) e não conseguirmos corrigir, entre "
            "em contato com o identificador do relatório: devolvemos o valor desse relatório "
            "ou, se você preferir, emitimos um novo crédito."
        )
    lines.append(
        "Se você pagou e o relatório completo não foi gerado por uma falha do serviço, "
        "entre em contato: devolvemos o valor ou emitimos um novo código. Como o relatório "
        "é entregue na hora, não reembolsamos um relatório já liberado por mudança de "
        "ideia. Atendemos erros que não possamos corrigir, falhas na entrega e direitos "
        "previstos na lei aplicável."
    )
    if ctx.card_payments:
        lines.append(_card_refund_pt(ctx))
        lines.append(
            "Se houver cobrança duplicada, entre em contato com os identificadores dos "
            "pagamentos para analisarmos o reembolso manualmente."
        )
    return tuple(lines)


def terms_text(ctx: LegalContext, locale: str = "es") -> LegalText:
    locale = _locale(locale)
    name = _value(ctx.operator_name, locale)
    address = _value(ctx.operator_address, locale)
    contact = _value(ctx.operator_contact, locale)
    jurisdiction = _value(ctx.jurisdiction, locale)
    warning = _warning(ctx, locale)
    if locale == "pt":
        return _terms_pt(ctx, name, address, contact, jurisdiction, warning)
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
                        "A new account's first eligible upload is a free full report, once "
                        "per account and browser, with a monthly network limit. The same "
                        "file on another eligible account does not by itself block it. "
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
                    "You are responsible for your password. " + _account_recovery(ctx, "en"),
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
                    "La primera carga elegible de una cuenta nueva da un informe completo "
                    "gratis, una vez por cuenta y navegador, con límite mensual por red. "
                    "El mismo archivo en otra cuenta elegible no la bloquea por sí solo. "
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
                "Eres responsable de tu contraseña. " + _account_recovery(ctx, "es"),
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


def _terms_pt(
    ctx: LegalContext,
    name: str,
    address: str,
    contact: str,
    jurisdiction: str,
    warning: str | None,
) -> LegalText:
    account = (
        (
            "O primeiro arquivo de uma conta nova dá direito a um relatório completo "
            "gratuito, uma vez por conta e navegador, sujeito também aos limites "
            "mensais por endereço de rede. O mesmo arquivo em outra conta elegível não "
            "a bloqueia por si só. Uma rede compartilhada, por si só, não impede "
            "o acesso. Depois disso, a prévia gratuita exige uma conta: "
            f"{FREE_PREVIEWS_PER_MONTH} por mês civil por conta, também sujeitas aos limites "
            "por rede. Após esses limites, cada arquivo exige pagamento. "
            + (
                "Um relatório pago com código de acesso funciona sem conta. "
                if ctx.access_codes
                else ""
            )
            + "O link privado de cada relatório funciona sem conta."
        )
        if not ctx.free_mode
        else "A conta é opcional enquanto o serviço estiver no modo gratuito."
    )
    sections: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Prestador", (f'{name}, {address}. Contato: {contact} ("nós").',)),
        (
            "O que é o serviço",
            (
                "Uma análise estatística automatizada dos arquivos de backtest ou de conta "
                "que você envia: relatório da plataforma, exportação de otimização, curva de "
                "patrimônio ou retornos e, se fornecidos, operações, benchmark e variantes. "
                "O resultado é um relatório com avaliação por dimensão e cada valor marcado "
                "pela evidência disponível (MEASURED, DECLARED ou NOT_MEASURED).",
            ),
        ),
        (
            "O que o serviço não é",
            (
                "O serviço não presta aconselhamento de investimento, financeiro, jurídico "
                "ou tributário. Não recomenda compra, venda ou operação. Não executa ordens, "
                "não custodia recursos, não pede chaves da corretora ou da bolsa e não se "
                "conecta a elas. Não prevê resultados futuros: uma avaliação favorável "
                "significa apenas que não encontramos evidência de sobreajuste nos dados "
                "enviados. A simulação de desafios de prop firm e o risco por reamostragem "
                "são estimativas desses dados, não previsões.",
            ),
        ),
        (
            "Seus arquivos",
            (
                "Você declara ter direito de enviar os arquivos e que eles não contêm "
                "dados pessoais de terceiros. Os arquivos são usados para produzir seu "
                "relatório. A política de privacidade explica o que guardamos e por quanto tempo.",
                f"Há um limite de {ctx.max_uploads_per_hour_per_ip} envios por hora por endereço "
                "IP. Envie apenas resultados de backtest ou de conta.",
            ),
        ),
        (
            "Sua conta e indicações",
            (
                account,
                "A conta reúne seus relatórios, créditos e compras. Você é responsável pela "
                "senha. " + _account_recovery(ctx, "pt"),
                (
                    "Ao indicar um colega, você recebe "
                    f"{REFERRAL_CREDITS} crédito quando a pessoa indicada concluir seu "
                    "primeiro relatório completo gratuito, até "
                    f"{REFERRAL_MONTHLY_CAP} créditos por mês civil. Indicações feitas pelo "
                    "mesmo navegador não contam como novas pessoas. Compartilhar uma rede "
                    "não invalida uma indicação por si só."
                    + (
                        " Para receber o crédito, seu e-mail precisa estar confirmado."
                        if ctx.email_verification_required
                        else ""
                    )
                ),
                *(
                    (
                        "Um código de acesso salvo na conta continua pertencendo ao titular "
                        "do código; os créditos podem ser usados pela conta ou digitando o código.",
                    )
                    if ctx.access_codes
                    else ()
                ),
            ),
        ),
        (
            "Limites da análise",
            (
                "O relatório depende dos arquivos enviados, que não são conferidos com a "
                "corretora. Valores DECLARED vêm de declarações do usuário; valores "
                "NOT_MEASURED não puderam ser calculados. Não garantimos identificar todos "
                "os erros de um backtest.",
            ),
        ),
        ("Preço e pagamento", _price_pt(ctx)),
        (
            "Seu link privado",
            (
                "O link do relatório contém um token secreto. Quem o possui pode abrir e "
                "liberar o relatório e publicar sua página de verificação; guarde-o como uma "
                "senha. Guardamos apenas um hash do token e não podemos reenviar um link perdido.",
            ),
        ),
        (
            "Emblema e página de verificação",
            (
                "Se você publicar a verificação, a página mostra a classe, as dimensões, "
                "os hashes, a data e um aviso fixo, nunca arquivos, operações ou descrição. "
                "Você pode usar o emblema em seu site, Telegram, fóruns ou vídeos, sempre "
                "ligado à página de verificação. Não pode apresentá-lo como promessa de "
                "resultado, endosso de um produto ou junto de alegações de rentabilidade; "
                "nesse caso, podemos retirar a publicação.",
            ),
        ),
        (
            "Limitação de responsabilidade",
            (
                "Na medida permitida pela lei aplicável, nossa responsabilidade total é "
                "limitada ao valor pago pela auditoria em questão. Não respondemos por perdas "
                "de investimento ou decisões tomadas com base no relatório.",
            ),
        ),
        (
            "Titularidade",
            (
                "O relatório é seu. O mecanismo de análise, os textos e o formato são nossos. "
                "Você pode compartilhar o relatório; não pode revender o serviço sem "
                "acordo escrito.",
            ),
        ),
        ("Lei aplicável e foro", (f"{jurisdiction}.",)),
        (
            "Alterações",
            (
                "Publicamos alterações nesta página com uma nova data. Cada auditoria segue "
                "os termos vigentes no dia em que foi realizada.",
            ),
        ),
    )
    return LegalText("Termos do serviço", warning, sections, LEGAL_UPDATED)


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
    if locale == "pt":
        return (
            "Quando você paga com cartão: guardamos o identificador da sessão de pagamento "
            "do Stripe, a data e, no caso de um pacote, o hash do código de acesso.",
            "O Stripe recebe os dados do cartão, o e-mail digitado em sua página de pagamento "
            "(para enviar o recibo), o país do cartão, o identificador do relatório e a "
            "informação de que você comprou um relatório ou o pacote. O Stripe trata esses "
            f"dados conforme sua política: {STRIPE_PRIVACY_URL}. Não vemos os dados do cartão.",
        )
    return (
        "Si pagas con tarjeta: el identificador de la sesión de pago de Stripe, la fecha del "
        "pago y, si compras el paquete, el hash de su código de acceso.",
        "Stripe recibe los datos de tu tarjeta, el correo que escribes en su página de pago "
        "(ahí te envía el recibo) y el país de tu tarjeta, además del identificador del "
        "informe y si compraste un informe o el paquete. Stripe los trata según su propia "
        f"política: {STRIPE_PRIVACY_URL}. Nosotros nunca vemos los datos de tu tarjeta.",
    )


def _email_keeps(ctx: LegalContext, locale: str) -> tuple[str, ...]:
    if not (ctx.email_delivery_ready or ctx.email_verification_required):
        return ()
    return {
        "es": (
            "Si confirmas tu correo: la dirección confirmada y la fecha, hasta que borres "
            "la cuenta.",
            "Para enviar confirmaciones, cambios de correo, recuperación y avisos de compra "
            "o cargo adicional: el destinatario, "
            "propósito, idioma, estado, intentos de envío, caducidad y, cuando corresponde, "
            "el correo nuevo pendiente. Los enlaces de un solo uso se derivan de un "
            "identificador aleatorio y un secreto del servidor; no guardamos el enlace ni "
            "el token en claro ni adjuntamos archivos del informe. Los enlaces de confirmación "
            "y cambio caducan a las 24 horas; los de recuperación, a la hora. Los avisos de "
            "compra incluyen referencia, importe y plan, nunca token ni resultado. Las filas de "
            "envío se programan para borrarse 30 días después de caducar, mediante la limpieza "
            "periódica, o antes si borras la cuenta.",
        ),
        "en": (
            "If you confirm your e-mail: the confirmed address and date, until you delete "
            "the account.",
            "To send confirmations, e-mail changes, recovery and purchase or additional-charge "
            "notices: the recipient, purpose, "
            "language, delivery state, retry count, expiry and, where relevant, the pending "
            "new address. One-time links are derived from a random id and a server secret; "
            "we do not keep the link or token in clear text or attach report files. "
            "Confirmation and change links expire after 24 hours; recovery links after one "
            "hour. Purchase notices include reference, amount and plan, never a token or "
            "result. Delivery rows are scheduled for deletion 30 days after expiry by periodic "
            "cleanup, or sooner when you delete the account.",
        ),
        "pt": (
            "Se você confirmar o e-mail: o endereço confirmado e a data, até a exclusão da conta.",
            "Para enviar confirmações, trocas de e-mail, recuperação e avisos de compra ou "
            "cobrança adicional: destinatário, "
            "finalidade, idioma, estado, tentativas de envio, vencimento e, quando houver, "
            "o novo e-mail pendente. Os links de uso único são derivados de um identificador "
            "aleatório e de um segredo do servidor; não guardamos o link nem o token em "
            "texto claro nem anexamos arquivos do relatório. Links de confirmação e troca "
            "vencem em 24 horas; os de recuperação, em uma hora. Avisos de compra incluem "
            "referência, valor e plano, nunca token ou resultado. Os registros de envio estão "
            "programados para exclusão 30 dias após o vencimento pela limpeza periódica, "
            "ou antes com a exclusão da conta.",
        ),
    }[locale]


def privacy_text(ctx: LegalContext, locale: str = "es") -> LegalText:
    locale = _locale(locale)
    name = _value(ctx.operator_name, locale)
    address = _value(ctx.operator_address, locale)
    contact = _value(ctx.operator_contact, locale)
    days = ctx.retention_days
    limit = ctx.max_uploads_per_hour_per_ip
    warning = _warning(ctx, locale)
    if locale == "pt":
        return _privacy_pt(ctx, name, address, contact, days, limit, warning)
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
                    "and a hash of each sign-in session. " + _account_email_status(ctx, "en"),
                    *_email_keeps(ctx, "en"),
                    "To count free previews: which account used each one, when, and the "
                    "network address it came from. The address is cleared with the rest "
                    f"after {days} days.",
                    "For the free first full report: a random identifier of your browser "
                    f"(a cookie named {DEVICE_COOKIE}, stored by us only as a hash), the "
                    "SHA-256 of the file and the network address. The browser and account "
                    "limits prevent repeat claims; the same file on another eligible account "
                    "does not block it by itself. The address is cleared after "
                    f"{days} days; the two hashes stay without your e-mail even if you "
                    "delete your account. The browser hash helps prevent a repeat claim; "
                    "the file hash records what was previously used.",
                    "For 'Invite a colleague': each account's invite link, and for an account "
                    "created through someone's link, the date, whether its free first report "
                    "happened and the hash of its browser identifier, to refuse self-invites. "
                    "The inviter sees only counts, never who joined. It is deleted with the "
                    "inviter's account; when the account that joined is deleted, its row "
                    "keeps only the dates and the outcome under a random id (no e-mail, no "
                    "browser hash), so the monthly limit still holds.",
                    "If you make a recovery key: only its SHA-256 and the date it was made, "
                    "never the key, which is shown to you once. It is deleted when you use it, "
                    "when you make a new one or with your account.",
                    "If you turn on two-step sign-in: the secret your authenticator app shares "
                    "(needed to check its codes) and the last code step used, so a code works "
                    "once. It is deleted when you turn it off, when you use your recovery key "
                    "or with your account.",
                    "If you add a passkey: its credential id, its public key (never the "
                    "private key, which stays on your device), the name you give it, the site "
                    "address it was made for, the device's counter and when it was added and "
                    "last used. It is deleted when you remove it or with your account.",
                    "For 'Open sessions' in your account: for each session, a short device "
                    "label (such as 'Chrome · Windows', never the browser's full string), the "
                    "network address (an IPv6 address counts as its /64) and when it was last "
                    "used. It is deleted when the session is signed out or expires, or with your "
                    "account.",
                    "For 'Recent activity' in your account: each sign-in (with or without a "
                    "code, or with a passkey), each change of password, two-step sign-in, "
                    "recovery key or passkeys and each "
                    "session signed out, with its date, the short device label and the network "
                    "address. We keep the latest 50, and delete them after 90 days and with your "
                    "account. Separately, when someone types a wrong password for your account: "
                    "how many tries there were per network and hour, the device label and the "
                    "time of the last one, never the e-mail or password typed; we keep the "
                    "latest 20 lines, and delete them after 90 days and with your account. And "
                    "for each browser you open 'My account' with, the time of its last visit and "
                    "its label, kept under the hash of its random mark (the same cookie as the "
                    "free report), only to tell you what happened since; it is deleted after 90 "
                    "days without a visit or with your account.",
                    "To know which of our own links brings visitors: visits to the home "
                    "and case pages are counted per day, language and link tag (such as "
                    "?ref=f4 in a link we posted), with no address; a cookie named "
                    f"{SEEN_COOKIE} holds only today's date so a browser counts once a day. "
                    "When you "
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
                    "your browser for the free first report, one that remembers which of "
                    "our links brought you and one with today's date to count a visit once; "
                    "none tracks you across sites "
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
                "iniciada. " + _account_email_status(ctx, "es"),
                *_email_keeps(ctx, "es"),
                "Para contar las vistas previas gratis: qué cuenta usó cada una, cuándo y "
                f"desde qué dirección de red. La dirección se borra con lo demás a los {days} "
                "días.",
                "Para el primer informe completo gratis: un identificador al azar de tu "
                f"navegador (una cookie llamada {DEVICE_COOKIE}, que guardamos solo como hash), "
                "el SHA-256 del archivo y la dirección de red. Los límites por cuenta y "
                "navegador evitan repetir la oferta; el mismo archivo en otra cuenta elegible "
                f"no la bloquea por sí solo. La dirección se borra a los {days} días; los "
                "dos hashes se quedan sin tu correo aunque borres la cuenta. La marca del "
                "navegador ayuda a impedir un segundo regalo; el hash del archivo deja "
                "constancia de lo usado.",
                "Para «Invita a un colega»: el enlace de invitación de cada cuenta y, para una "
                "cuenta creada con el enlace de alguien, la fecha, si ya recibió su primer "
                "informe gratis y el hash del identificador de su navegador, para rechazar "
                "autoinvitaciones. Quien invita ve solo cifras, nunca quién se unió. Se borra "
                "con la cuenta de quien invita; si se borra la cuenta que se unió, su fila "
                "guarda solo las fechas y el resultado bajo un id al azar (sin correo ni hash "
                "del navegador), para que el límite mensual se mantenga.",
                "Si creas una clave de recuperación: solo su SHA-256 y la fecha en que la "
                "creaste, nunca la clave, que te mostramos una sola vez. Se borra al usarla, "
                "al crear una nueva o con tu cuenta.",
                "Si activas la verificación en dos pasos: la clave secreta que comparte tu app "
                "de autenticación (necesaria para comprobar sus códigos) y el último paso de "
                "código usado, para que cada código sirva una vez. Se borra al desactivarla, al "
                "usar tu clave de recuperación o con tu cuenta.",
                "Si añades una llave de acceso: su identificador, su clave pública (nunca la "
                "privada, que se queda en tu dispositivo), el nombre que le pongas, la dirección "
                "del sitio para la que se creó, el contador del dispositivo y cuándo se añadió y "
                "se usó por última vez. Se borra al quitarla o con tu cuenta.",
                "Para «Sesiones abiertas» en tu cuenta: de cada sesión, una etiqueta corta del "
                "dispositivo (como «Chrome · Windows», nunca el texto completo del navegador), la "
                "dirección de red (una IPv6 cuenta como su /64) y cuándo se usó por última vez. "
                "Se borra al cerrar la sesión o al caducar, o con tu cuenta.",
                "Para «Actividad reciente» en tu cuenta: cada entrada (con o sin código, o con "
                "llave de acceso), cada cambio de contraseña, de verificación en dos pasos, de "
                "clave de recuperación o de llaves de acceso "
                "y cada sesión cerrada, con su fecha, la etiqueta corta del dispositivo y la "
                "dirección de red. Guardamos las últimas 50, las borramos a los 90 días y "
                "con tu cuenta. Aparte, cuando alguien escribe una contraseña incorrecta para "
                "tu cuenta: cuántos intentos hubo por red y por hora, la etiqueta del "
                "dispositivo y la hora del último, nunca el correo ni la contraseña escritos; "
                "guardamos las últimas 20 líneas, las borramos a los 90 días y con tu cuenta. "
                "Y, por cada navegador con el que abres «Mi cuenta», la hora de su última visita "
                "y su etiqueta, guardado bajo el hash de su marca aleatoria (la misma cookie del "
                "informe gratis), solo para avisarte de lo que pasó desde entonces; se borra a "
                "los 90 días sin visitas o con tu cuenta.",
                "Para saber cuál de nuestros propios enlaces trae visitas: las visitas a la "
                "página principal y a las de cada caso se cuentan por día, idioma y etiqueta "
                "del enlace (como ?ref=f4 en un enlace que publicamos), sin dirección; una "
                f"cookie llamada {SEEN_COOKIE} guarda solo la fecha de hoy para contar cada "
                "navegador una vez al día. Si llegas desde un enlace con etiqueta, una cookie "
                f"llamada {REF_COOKIE} guarda solo esa etiqueta durante {REF_DAYS} días y, si "
                "creas una cuenta, la etiqueta se queda con ella hasta que la borres.",
            ),
        ),
        (
            "Qué no guardamos",
            (
                "Nunca pedimos ni guardamos claves de bróker ni de exchange, contraseñas de "
                "cuentas de trading ni datos de tarjeta. No hay analítica ni publicidad de "
                "terceros en estas páginas. Las únicas cookies son nuestras: una que mantiene "
                "tu sesión iniciada, otra que protege los formularios de acceso, otra que "
                "marca tu navegador para el primer informe gratis, otra que recuerda cuál de "
                "nuestros enlaces te trajo y otra con la fecha de hoy para contar una visita "
                "una sola vez; ninguna te sigue por otros "
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


def _privacy_pt(
    ctx: LegalContext,
    name: str,
    address: str,
    contact: str,
    days: int,
    limit: int,
    warning: str | None,
) -> LegalText:
    sections: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Responsável", (f"{name}, {address}. Contato: {contact}.",)),
        (
            "O que guardamos",
            (
                "Os arquivos enviados (relatório da plataforma, exportação de otimização, "
                "curva de patrimônio, operações, benchmark e variantes) e o hash SHA-256 "
                "de cada um.",
                "O que você declara no formulário, inclusive a descrição opcional, e o "
                "relatório gerado.",
                f"O endereço IP do envio, para aplicar o limite de {limit} envios por hora "
                "por endereço e evitar abusos.",
                "Um hash do token privado do relatório, nunca o próprio token.",
                *_stripe_keeps(ctx, "pt"),
                "Quando você usa um código de acesso: o identificador interno do código que "
                "liberou a auditoria. Os códigos são guardados apenas como hash.",
                "Quando você publica uma página de verificação: o identificador público e a data.",
                "Quando você baixa o relatório em PDF ou JSON: o hash SHA-256 do arquivo, "
                "para que quem o possui confira em /pt/comprovar se ele foi alterado. "
                "Um arquivo enviado para essa conferência é lido e descartado, sem ser guardado.",
                "Se você entra na lista de novidades: seu e-mail.",
                "Se você cria uma conta: seu e-mail, um hash scrypt da senha (nunca a senha), "
                "os relatórios e códigos de acesso associados e o hash de cada sessão iniciada. "
                + _account_email_status(ctx, "pt"),
                *_email_keeps(ctx, "pt"),
                "Para contar as prévias gratuitas: qual conta usou cada uma, quando e de qual "
                f"endereço de rede. O endereço é eliminado com os demais dados após {days} dias.",
                "Para o primeiro relatório completo gratuito: um identificador aleatório do "
                f"navegador (cookie {DEVICE_COOKIE}, guardado por nós apenas como hash), "
                "o SHA-256 do arquivo e o endereço de rede. Os limites por conta e navegador "
                "evitam repetição; o mesmo arquivo em outra conta elegível não a bloqueia "
                f"por si só. O endereço é eliminado após {days} dias; "
                "os dois hashes permanecem sem o e-mail mesmo se você excluir a conta. "
                "A marca do navegador ajuda a impedir outro presente; o hash do arquivo "
                "registra o que já foi usado.",
                "Para 'Indique um colega': o link de indicação de cada conta e, para uma conta "
                "criada por esse link, a data, se seu primeiro relatório gratuito foi concluído "
                "e o hash do identificador do navegador, para impedir autoindicações. Quem "
                "indicou vê apenas totais, não a identidade de quem entrou. Esses dados são "
                "eliminados com a conta de quem indicou. Se a conta indicada for excluída, "
                "seu registro conserva apenas datas e resultado sob um identificador aleatório "
                "(sem e-mail nem hash do navegador), para manter o limite mensal.",
                "Se você cria uma chave de recuperação: apenas seu SHA-256 e a data de criação, "
                "nunca a chave, mostrada uma única vez. Ela é eliminada quando usada, substituída "
                "ou quando a conta é excluída.",
                "Se você ativa a verificação em duas etapas: o segredo compartilhado com o "
                "aplicativo autenticador, necessário para conferir os códigos, e a última etapa "
                "de código usada, para impedir sua reutilização. Esses dados são eliminados ao "
                "desativar a função, usar a chave de recuperação ou excluir a conta.",
                "Se você cadastra uma chave de acesso: o identificador da credencial, a chave "
                "pública (nunca a chave privada, que permanece no dispositivo), o nome dado "
                "por você, o endereço do site, o contador do dispositivo e as datas de cadastro "
                "e último uso. Esses dados são eliminados ao remover a chave ou excluir a conta.",
                "Em 'Sessões abertas': de cada sessão, uma identificação breve do dispositivo "
                "(como 'Chrome · Windows', nunca a identificação completa do navegador), "
                "o endereço de rede (IPv6 considerada por /64) e a data do último uso. "
                "Os dados são eliminados quando a sessão termina, expira ou a conta é excluída.",
                "Em 'Atividade recente': entradas na conta, mudanças de senha, verificação "
                "em duas etapas, chave de recuperação e chaves de acesso, além de sessões "
                "encerradas, com data, identificação breve do dispositivo e endereço de rede. "
                "Guardamos os 50 registros mais recentes por até 90 dias ou até a exclusão da "
                "conta. Tentativas de senha incorreta são contadas por rede e hora, sem guardar "
                "o e-mail ou a senha digitada; mantemos as 20 linhas mais recentes por até "
                "90 dias ou até a exclusão da conta. Para cada navegador que abre 'Minha conta', "
                "guardamos a data da última visita e uma identificação breve sob o hash de "
                "sua marca aleatória, para mostrar o que ocorreu desde então; o registro é "
                "eliminado após 90 dias sem visita ou com a conta.",
                "Para contar visitas vindas de nossos próprios links: as visitas à página "
                "inicial e às páginas de casos são contadas por dia, idioma e etiqueta do "
                "link (como ?ref=f4), sem endereço de rede. A cookie "
                f"{SEEN_COOKIE} guarda só a data de hoje para contar um navegador uma vez "
                "por dia. Se você chega por um link etiquetado, a cookie "
                f"{REF_COOKIE} guarda a etiqueta por {REF_DAYS} dias; se você criar uma conta, "
                "a etiqueta permanece nela até a exclusão.",
            ),
        ),
        (
            "O que não guardamos",
            (
                "Não pedimos nem guardamos chaves de corretora ou bolsa, senhas de conta de "
                "trading ou dados de cartão. Estas páginas não usam analítica ou publicidade "
                "de terceiros. As cookies são nossas: sessão, proteção dos formulários, marca "
                "do navegador para a oferta gratuita, origem de nossos próprios links e data "
                "para contar uma visita por dia. Nenhuma acompanha você entre sites ou é "
                "compartilhada. Nosso registro de acessos guarda apenas o endereço abreviado "
                "(sem a parte final do IP) e nunca o segredo do link do relatório. O provedor "
                "de hospedagem pode manter seus próprios registros de requisições com IP "
                "completo pelo prazo definido por ele.",
            ),
        ),
        (
            "Para que usamos os dados",
            (
                "Para produzir e mostrar o relatório, aplicar os limites de envio, registrar "
                "pagamentos ou códigos usados, mostrar uma página de verificação publicada "
                "por você e administrar a lista de novidades. Não vendemos dados nem os "
                "usamos para publicidade; o acesso dos fornecedores está descrito abaixo.",
            ),
        ),
        (
            "Por quanto tempo guardamos",
            (
                f"Auditorias não pagas: após {days} dias, eliminamos arquivos, relatório, "
                "declarações e descrição. Permanecem o identificador, os hashes dos arquivos, "
                "a classe e a data, para que o registro ainda possa ser conferido.",
                f"O IP do envio é eliminado nessa mesma limpeza após {days} dias, inclusive "
                "nas auditorias pagas.",
                "Auditorias pagas e primeiro relatório completo gratuito: guardados para que "
                "você possa reabri-los até excluí-los com sua conta ou solicitar a exclusão.",
                "Página de verificação: pública até você retirá-la no relatório, pedir sua "
                "retirada ou pedir a exclusão da auditoria. Se publicada, a limpeza conserva "
                "apenas o que ela mostra (classe, estados das dimensões, hashes, datas, "
                "número de tentativas e versão do mecanismo), para manter a página e o emblema.",
                "Lista de novidades: até você pedir a remoção.",
                "Conta: até você excluí-la na própria página ou pedir sua exclusão. Isso "
                "elimina e-mail, hash da senha, sessões e a lista de relatórios e códigos. "
                "Os relatórios seguem as regras acima, a menos que você também escolha "
                "excluí-los. Uma sessão termina em 30 dias ou quando você sai da conta.",
            ),
        ),
        (
            "Quem pode acessar",
            (
                "O operador e os provedores de hospedagem e banco de dados que guardam os "
                "dados para nós."
                + (
                    " O Stripe recebe os dados necessários para o pagamento com cartão."
                    if ctx.card_payments
                    else ""
                )
                + " Uma página de verificação, apenas se você a publicar, mostra classe, "
                "dimensões, hashes, data e aviso fixo; nunca arquivos, operações, descrição "
                "ou token.",
                "Os dados podem ser hospedados fora do seu país, nos servidores do provedor "
                "de hospedagem.",
            ),
        ),
        (
            "Seus direitos",
            (
                f"Escreva para {contact} para pedir acesso, cópia, correção ou exclusão de "
                "seus dados. Para demonstrar que a auditoria é sua, inclua o link privado. "
                "A exclusão da auditoria remove arquivos, relatório, hashes, classe e página "
                "de verificação. Para sair da lista de novidades, escreva do e-mail inscrito. "
                "Você pode excluir a conta pela própria página e baixar uma cópia dos dados "
                "guardados nela em 'Baixar meus dados'. Responderemos nos prazos da lei aplicável.",
                "Você também pode apresentar uma reclamação à autoridade de proteção de "
                "dados competente.",
            ),
        ),
        ("Alterações", ("Publicamos alterações nesta página com uma nova data.",)),
    )
    return LegalText("Política de privacidade", warning, sections, LEGAL_UPDATED)


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
