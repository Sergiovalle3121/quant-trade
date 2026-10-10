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
    ANON_PREVIEWS_PER_IPV4_PER_DAY,
    ANON_PREVIEWS_PER_NETWORK_PER_DAY,
    DEVICE_COOKIE,
    FREE_PREVIEWS_PER_MONTH,
    REFERRAL_CREDITS,
    REFERRAL_MONTHLY_CAP,
)
from quant_trade.audit.funnel import REF_COOKIE, REF_DAYS, SEEN_COOKIE
from quant_trade.audit.paid_offer import REFUND_DAYS
from quant_trade.audit.settings import PACK_CREDITS

#: Date of the current wording. Change it whenever a text below changes.
LEGAL_UPDATED = "2026-10-09"

STRIPE_PRIVACY_URL = "https://stripe.com/privacy"
RESEND_PRIVACY_URL = "https://resend.com/legal/privacy-policy"

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
    #: Street, number, postal code and city, printed before the country.
    operator_street_address: str = ""
    operator_phone: str = ""
    jurisdiction: str = ""
    free_mode: bool = True
    price_usd: float = 0.0
    card_payments: bool = False
    access_codes: bool = False
    pack_price_usd: float = 0.0
    email_delivery_ready: bool = False
    #: True when account e-mail goes out through Resend's API.
    email_via_resend: bool = False
    email_verification_required: bool = False
    retention_days: int = 30
    max_uploads_per_hour_per_ip: int = 10
    #: A new account's first upload is a free full report
    #: (``AUDIT_WELCOME_FULL_REPORT``); off, every full report is paid.
    welcome_full_report: bool = True
    #: A visitor without an account may see a file's class and red flags
    #: (``AUDIT_ANON_PREVIEW``).
    anon_preview: bool = False

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


def _address(ctx: LegalContext, locale: str) -> str:
    """The physical address: the street, then the country as ``locale`` words it."""
    country = _value(ctx.operator_address, locale)
    if ctx.operator_street_address and ctx.operator_address:
        return f"{ctx.operator_street_address}, {country}"
    return country


def _tel(ctx: LegalContext, locale: str) -> str:
    """The telephone after the contact, in the provider's line only."""
    if not ctx.operator_phone:
        return ""
    return {"en": ", phone "}.get(locale, ", tel. ") + ctx.operator_phone


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
                "Si olvidas la contraseña, puedes usar tu clave de recuperación o pedir un "
                "enlace de un solo uso, que enviamos solo a un correo confirmado. Puedes "
                "borrar la cuenta desde su página."
            ),
            "en": (
                "If you forget your password, you can use your recovery key or request a "
                "one-time link, which we send only to a confirmed e-mail address. You can "
                "delete the account from its page."
            ),
            "pt": (
                "Se você esquecer a senha, pode usar sua chave de recuperação ou pedir um "
                "link de uso único, que enviamos apenas a um e-mail confirmado. Você pode "
                "excluir a conta pela própria página."
            ),
        }[locale]
    return {
        "es": (
            "Si la olvidas, puedes poner una nueva con tu clave de recuperación. Si no tienes "
            "clave, escríbenos: comprobamos que el correo de la cuenta es tuyo y te enviamos un "
            "enlace de un solo uso. Puedes borrar la cuenta cuando quieras desde su página."
        ),
        "en": (
            "If you forget it, you can set a new one with your recovery key. If you have no "
            "key, write to us: we check that the account's e-mail is yours and send you a "
            "one-time link. You can delete the account at any time from its page."
        ),
        "pt": (
            "Se você esquecê-la, pode criar uma nova com sua chave de recuperação. Se não "
            "tiver chave, escreva para nós: confirmamos que o e-mail da conta é seu e enviamos "
            "um link de uso único. Você pode excluir a conta pela própria página."
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


def _refund(ctx: LegalContext, locale: str) -> str:
    """The refund policy: a paid report or a single credit bought (used or not)
    within ``REFUND_DAYS`` days of the payment, a pack's unused credits, and
    always a duplicate charge or one that delivered no report. The operator
    refunds a card payment from Stripe; nothing locks the report again
    (``refund.created`` is recorded, ``record_stripe_refund``)."""
    contact = _value(ctx.operator_contact, locale)
    days = REFUND_DAYS
    pack = bool(ctx.pack_price_usd)
    if locale == "en":
        parts = [
            f"{days}-day refund: if a paid report, or a single credit you bought, is no use to "
            f"you, write to {contact} within {days} days of the payment, with the report's or "
            "the purchase's identifier, and we refund the full amount."
        ]
        if pack:
            parts.append(
                f"For a pack, if you used none of its credits within those {days} days, we "
                "refund the whole pack; if you used some, we refund the part of the unused "
                "credits"
                + (
                    " (a pack bought by card from a report has already used one credit: that "
                    "report's)."
                    if ctx.card_payments
                    else "."
                )
            )
        parts.append(
            "We also always refund a duplicate charge or a charge that delivered no report; if "
            "the report was not produced because of a fault in the service, you can also ask "
            "for a new code."
        )
        if ctx.card_payments:
            parts.append(
                "We make the refund of a card payment ourselves, from Stripe, and it reaches the "
                "same payment method within your bank's times."
            )
        if ctx.access_codes:
            parts.append(
                "A code paid outside the site is refunded through the method you paid with."
            )
        parts.append("This does not limit your rights under applicable law.")
        return " ".join(parts)
    if locale == "pt":
        parts = [
            f"Devolução em {days} dias: se um relatório pago, ou um crédito avulso que você "
            f"comprou, não servir para você, escreva para {contact} nos {days} dias seguintes "
            "ao pagamento, com o identificador do relatório ou da compra, e devolvemos o valor "
            "total."
        ]
        if pack:
            parts.append(
                f"No pacote, se nesses {days} dias você não usou nenhum crédito, devolvemos o "
                "pacote inteiro; se usou algum, devolvemos a parte dos créditos não usados"
                + (
                    " (um pacote comprado com cartão a partir de um relatório já usou um "
                    "crédito: o desse relatório)."
                    if ctx.card_payments
                    else "."
                )
            )
        parts.append(
            "Além disso, sempre devolvemos uma cobrança duplicada ou uma cobrança que não "
            "entregou nenhum relatório; se o relatório não foi gerado por uma falha do serviço, "
            "você também pode pedir um novo código."
        )
        if ctx.card_payments:
            parts.append(
                "Nós mesmos fazemos a devolução de um pagamento com cartão, pelo Stripe, e ela "
                "chega ao mesmo meio de pagamento nos prazos do seu banco."
            )
        if ctx.access_codes:
            parts.append("Um código pago fora do site é devolvido pelo mesmo meio do pagamento.")
        parts.append("Isso não limita os direitos previstos na lei aplicável.")
        return " ".join(parts)
    parts = [
        f"Devolución en {days} días: si un informe pagado, o un crédito suelto que compraste, "
        f"no te sirve, escribe a {contact} dentro de los {days} días siguientes al pago, con "
        "el identificador del informe o de la compra, y te devolvemos el importe completo."
    ]
    if pack:
        parts.append(
            f"En un paquete, si en esos {days} días no usaste ningún crédito, te devolvemos el "
            "paquete completo; si usaste alguno, te devolvemos la parte de los créditos sin usar"
            + (
                " (un paquete comprado con tarjeta desde un informe ya usó un crédito: el de ese "
                "informe)."
                if ctx.card_payments
                else "."
            )
        )
    parts.append(
        "Además, siempre devolvemos un cobro duplicado o un cobro que no entregó ningún "
        "informe; si el informe no se generó por un fallo del servicio, también puedes pedir "
        "un código nuevo."
    )
    if ctx.card_payments:
        parts.append(
            "La devolución de un pago con tarjeta la hacemos nosotros desde Stripe y llega al "
            "mismo medio de pago, en los plazos de tu banco."
        )
    if ctx.access_codes:
        parts.append("Un código pagado fuera de la web se devuelve por el mismo medio de pago.")
    parts.append("Esto no limita los derechos que te conceda la ley aplicable.")
    return " ".join(parts)


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
    if ctx.email_verification_required and ctx.welcome_full_report:
        lines.append(
            "Tu primer informe completo gratis llega cuando confirmas el correo de tu cuenta."
        )
    if ctx.card_payments and ctx.email_verification_required:
        lines.append("Para pagar con tarjeta debes confirmar el correo de tu cuenta.")
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
            "coinciden con lo que muestra tu plataforma), escríbenos con el identificador del "
            "informe: lo corregimos o, si no se puede, te damos un crédito nuevo."
        )
    lines.append(_refund(ctx, "es"))
    return tuple(lines)


def _price_en(ctx: LegalContext) -> tuple[str, ...]:
    if ctx.free_mode:
        return (
            "The service is currently free: the full report comes with a watermark. If that "
            "changes, the price is shown before you pay and audits already made are not "
            "affected.",
        )
    lines = [f"The preview is free. The full report costs USD {ctx.price_usd:.2f} per audit."]
    if ctx.email_verification_required and ctx.welcome_full_report:
        lines.append("Your first free full report comes once you confirm your account e-mail.")
    if ctx.card_payments and ctx.email_verification_required:
        lines.append("To pay by card, confirm your account e-mail.")
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
            "what your platform shows), write to us with the report's identifier: we fix it "
            "or, if that is not possible, give you a new credit."
        )
    lines.append(_refund(ctx, "en"))
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
    if ctx.email_verification_required and ctx.welcome_full_report:
        lines.append(
            "Seu primeiro relatório completo gratuito chega quando você confirma o e-mail da conta."
        )
    if ctx.card_payments and ctx.email_verification_required:
        lines.append("Para pagar com cartão, confirme o e-mail da sua conta.")
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
            "datas que não correspondem à plataforma), entre em contato com o identificador "
            "do relatório: nós o corrigimos ou, se não for possível, damos um novo crédito."
        )
    lines.append(_refund(ctx, "pt"))
    return tuple(lines)


def _account_terms(ctx: LegalContext, locale: str) -> str:
    """The free tier as the code applies it: the free first full report (while
    ``welcome_full_report``), the account's monthly previews and, with
    ``anon_preview``, the previews without an account of each network."""
    n = FREE_PREVIEWS_PER_MONTH
    per_net, per_ipv4 = ANON_PREVIEWS_PER_NETWORK_PER_DAY, ANON_PREVIEWS_PER_IPV4_PER_DAY
    if locale == "en":
        if ctx.free_mode:
            return "The account is optional while the service is in free mode."
        lead = (
            "The first file of a new account gets a free full report: once per account, "
            "browser and file, and only a few times a month from the same network address. "
            if ctx.welcome_full_report
            else "Every full report is paid, the first one too. "
        )
        if not ctx.anon_preview:
            first = "After it, the free preview" if ctx.welcome_full_report else "The free preview"
            previews = (
                first + f" needs an account: {n} a calendar month per account, also counted per "
                "network address. Past that, each file is a paid report. "
            )
        else:
            previews = (
                f"With an account you get {n} free previews a calendar month, also counted per "
                "network address; past that, each file is a paid report. Without an account, "
                f"each network can see the class and red flags of {per_net} files a day "
                f"({per_ipv4} from an IPv4 address, which is often shared); the full report "
                "needs an account. "
                + (
                    "If you create it from the browser that uploaded the file, that report can "
                    "open as your free report, under the same limits; otherwise it takes one of "
                    "the month's previews while any are left. "
                    if ctx.welcome_full_report
                    else "If you move one of those previews to your account, it takes one of the "
                    "month's previews while any are left. "
                )
            )
        return lead + previews + "Each report's private link works without an account."
    if locale == "pt":
        if ctx.free_mode:
            return "A conta é opcional enquanto o serviço estiver no modo gratuito."
        lead = (
            "O primeiro arquivo de uma conta nova dá direito a um relatório completo "
            "gratuito, uma vez por conta, navegador e arquivo, sujeito também aos limites "
            "mensais por endereço de rede. Uma rede compartilhada, por si só, não impede "
            "o acesso. "
            if ctx.welcome_full_report
            else "Todo relatório completo é pago, também o primeiro. "
        )
        if not ctx.anon_preview:
            first = "Depois disso, a prévia" if ctx.welcome_full_report else "A prévia"
            previews = (
                first
                + f" gratuita exige uma conta: {n} por mês civil por conta, também sujeitas aos "
                "limites por rede. Após esses limites, cada arquivo exige pagamento. "
            )
        else:
            previews = (
                f"Com uma conta, você tem {n} prévias gratuitas por mês civil, também sujeitas "
                "aos limites por rede; após esses limites, cada arquivo exige pagamento. Sem "
                f"conta, cada rede pode ver a classe e os alertas de {per_net} arquivos por dia "
                f"({per_ipv4} a partir de um endereço IPv4, que costuma ser compartilhado); o "
                "relatório completo exige uma conta. "
                + (
                    "Se você criá-la no navegador que enviou o arquivo, esse relatório pode abrir "
                    "como o seu relatório gratuito, com os mesmos limites; se não, ocupa uma das "
                    "prévias do mês enquanto houver. "
                    if ctx.welcome_full_report
                    else "Se você passar uma dessas prévias para a sua conta, ela ocupa uma das "
                    "prévias do mês enquanto houver. "
                )
            )
        return lead + previews + "O link privado de cada relatório funciona sem conta."
    if ctx.free_mode:
        return "La cuenta es opcional mientras el servicio está en modo gratuito."
    lead = (
        "El primer archivo de una cuenta nueva es un informe completo gratis, una vez "
        "por cuenta, navegador y archivo, y unos pocos por dirección de red al mes. "
        if ctx.welcome_full_report
        else "Cada informe completo es de pago, también el primero. "
    )
    if not ctx.anon_preview:
        first = "Después, la vista previa" if ctx.welcome_full_report else "La vista previa"
        previews = (
            first
            + f" gratis necesita una cuenta: {n} por mes calendario y por cuenta, contadas también "
            "por dirección de red. Pasado ese número, cada archivo es un informe de pago. "
        )
    else:
        previews = (
            f"Con una cuenta tienes {n} vistas previas gratis por mes calendario, contadas "
            "también por dirección de red; pasado ese número, cada archivo es un informe de "
            f"pago. Sin cuenta, cada red puede ver la clase y las banderas rojas de {per_net} "
            f"archivos al día ({per_ipv4} desde una dirección IPv4, que suele ser compartida); "
            "el informe completo necesita una cuenta. "
            + (
                "Si la creas desde el navegador con el que subiste el archivo, ese informe puede "
                "abrirse como tu informe gratis, con los mismos límites; si no, ocupa una de las "
                "vistas previas del mes mientras queden. "
                if ctx.welcome_full_report
                else "Si pasas una de esas vistas previas a tu cuenta, ocupa una de las vistas "
                "previas del mes mientras queden. "
            )
        )
    return lead + previews + "El enlace privado de cada informe funciona sin cuenta."


def terms_text(ctx: LegalContext, locale: str = "es") -> LegalText:
    locale = _locale(locale)
    name = _value(ctx.operator_name, locale)
    address = _address(ctx, locale)
    contact = _value(ctx.operator_contact, locale)
    jurisdiction = _value(ctx.jurisdiction, locale)
    warning = _warning(ctx, locale)
    if locale == "pt":
        return _terms_pt(ctx, name, address, contact, jurisdiction, warning)
    if locale == "en":
        sections: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("Provider", (f'{name}, {address}. Contact: {contact}{_tel(ctx, "en")} ("we").',)),
            (
                "What the service is",
                (
                    "An automated statistical analysis of the backtest or account files you "
                    "upload: a platform report, an optimisation export, an equity curve or "
                    "returns and, if you supply them, trades, a benchmark and variants. The "
                    "output is a report with a verdict by dimension and every value labelled "
                    "by its evidence (“Measured”, “Declared” or “Not measured”).",
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
                    _account_terms(ctx, "en"),
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
                    "checked against any broker. Values marked “Declared” come from your own "
                    "statements. Values marked “Not measured” could not be computed. We do not "
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
        ("Prestador", (f'{name}, {address}. Contacto: {contact}{_tel(ctx, "es")} ("nosotros").',)),
        (
            "Qué es el servicio",
            (
                "Un análisis estadístico automatizado de los archivos de backtest o de cuenta "
                "que subes: el informe de tu plataforma, una exportación de optimización, una "
                "curva de equity o de retornos y, si los aportas, operaciones, benchmark y "
                "variantes. El resultado es un informe con un veredicto por dimensiones y "
                "cada valor etiquetado según su evidencia («Medido», «Declarado» o «No medido»).",
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
                _account_terms(ctx, "es"),
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
                "con ningún bróker. Los valores marcados «Declarado» provienen de tus propias "
                "declaraciones. Los valores marcados «No medido» no pudieron calcularse. No "
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
                "descripción. Puedes usar el sello en tu web, Telegram, foros o videos, "
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
    account = _account_terms(ctx, "pt")
    # Invites pay a credit once the invitee's free first report exists: without
    # that report (the paid offer) there is no invite to describe.
    invites = ctx.free_mode or ctx.welcome_full_report
    sections: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Prestador", (f'{name}, {address}. Contato: {contact}{_tel(ctx, "pt")} ("nós").',)),
        (
            "O que é o serviço",
            (
                "Uma análise estatística automatizada dos arquivos de backtest ou de conta "
                "que você envia: relatório da plataforma, exportação de otimização, curva de "
                "patrimônio ou retornos e, se fornecidos, operações, benchmark e variantes. "
                "O resultado é um relatório com avaliação por dimensão e cada valor marcado "
                "pela evidência disponível («Medido», «Declarado» ou «Não medido»).",
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
            "Sua conta e indicações" if invites else "Sua conta",
            (
                account,
                "A conta reúne seus relatórios, créditos e compras. Você é responsável pela "
                "senha. " + _account_recovery(ctx, "pt"),
                *(
                    (
                        "Ao indicar um colega, você recebe "
                        f"{REFERRAL_CREDITS} crédito quando a pessoa indicada concluir seu "
                        "primeiro relatório completo gratuito, até "
                        f"{REFERRAL_MONTHLY_CAP} créditos por mês civil. Indicações feitas pelo "
                        "mesmo navegador não contam como novas pessoas. Compartilhar uma rede "
                        "não invalida uma indicação por si só. Para receber o crédito, o seu "
                        "e-mail e o da pessoa indicada precisam estar confirmados.",
                    )
                    if invites
                    else ()
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
                "corretora. Valores «Declarado» vêm de declarações do usuário; valores "
                "«Não medido» não puderam ser calculados. Não garantimos identificar todos "
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
            "Selo e página de verificação",
            (
                "Se você publicar a verificação, a página mostra a classe, as dimensões, "
                "os hashes, a data e um aviso fixo, nunca arquivos, operações ou descrição. "
                "Você pode usar o selo em seu site, Telegram, fóruns ou vídeos, sempre "
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
            "For a Checkout order, we keep the billing country you declare before payment and, "
            "when Stripe provides it, the billing country observed by Stripe. Both are linked "
            "to the order to check market availability and reconcile a charge.",
            "Stripe receives your card details, the e-mail address you type on its checkout "
            "page (it sends the receipt there) and your card's country, plus the report id and "
            "whether you bought one report or the pack. Stripe processes them under its own "
            f"policy: {STRIPE_PRIVACY_URL}. We never see your card details.",
        )
    if locale == "pt":
        return (
            "Quando você paga com cartão: guardamos o identificador da sessão de pagamento "
            "do Stripe, a data e, no caso de um pacote, o hash do código de acesso.",
            "Em um pedido do Checkout, guardamos o país de cobrança que você declara antes do "
            "pagamento e, quando o Stripe o informa, o país de cobrança observado pelo Stripe. "
            "Ambos ficam associados ao pedido para verificar a disponibilidade nesse mercado "
            "e conciliar uma cobrança.",
            "O Stripe recebe os dados do cartão, o e-mail digitado em sua página de pagamento "
            "(para enviar o recibo), o país do cartão, o identificador do relatório e a "
            "informação de que você comprou um relatório ou o pacote. O Stripe trata esses "
            f"dados conforme sua política: {STRIPE_PRIVACY_URL}. Não vemos os dados do cartão.",
        )
    return (
        "Si pagas con tarjeta: el identificador de la sesión de pago de Stripe, la fecha del "
        "pago y, si compras el paquete, el hash de su código de acceso.",
        "En un pedido de Checkout guardamos el país de facturación que declaras antes de pagar "
        "y, cuando Stripe lo comunica, el país de facturación observado por Stripe. Ambos "
        "quedan asociados al pedido para comprobar la disponibilidad en ese mercado y "
        "conciliar un cargo.",
        "Stripe recibe los datos de tu tarjeta, el correo que escribes en su página de pago "
        "(ahí te envía el recibo) y el país de tu tarjeta, además del identificador del "
        "informe y si compraste un informe o el paquete. Stripe los trata según su propia "
        f"política: {STRIPE_PRIVACY_URL}. Nosotros nunca vemos los datos de tu tarjeta.",
    )


def _email_keeps(ctx: LegalContext, locale: str) -> tuple[str, ...]:
    if not (ctx.email_delivery_ready or ctx.email_verification_required):
        return ()
    return _email_keeps_text(locale) + _email_provider(ctx, locale)


def _email_provider(ctx: LegalContext, locale: str) -> tuple[str, ...]:
    """Who carries the mail; only said when that provider is in use."""
    if not (ctx.email_delivery_ready and ctx.email_via_resend):
        return ()
    return {
        "es": (
            "Los correos los entrega Resend, que recibe la dirección de destino, el asunto y "
            "el texto de cada mensaje y los trata según su propia política: "
            f"{RESEND_PRIVACY_URL}.",
        ),
        "en": (
            "Resend delivers these e-mails. It receives the recipient address, subject and "
            "text of each message and processes them under its own policy: "
            f"{RESEND_PRIVACY_URL}.",
        ),
        "pt": (
            "Os e-mails são entregues pela Resend, que recebe o endereço de destino, o assunto "
            "e o texto de cada mensagem e os trata segundo a própria política: "
            f"{RESEND_PRIVACY_URL}.",
        ),
    }[locale]


def _email_keeps_text(locale: str) -> tuple[str, ...]:
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


def _anon_keeps(ctx: LegalContext, locale: str, days: int) -> tuple[str, ...]:
    """What an upload without an account keeps (``AUDIT_ANON_PREVIEW``): the
    ``anon_previews`` row, the ``welcome_pending`` row and the day's network
    claims, all gone with the report or at the retention purge. Under the paid
    offer no file fingerprint is kept: there is no free report to check it for."""
    if not ctx.anon_preview or ctx.free_mode:
        return ()
    welcome = ctx.welcome_full_report
    if locale == "en":
        marks = (
            ", the file's SHA-256 and the network address, to open it as the free report if you "
            "create the account"
            if welcome
            else " and the network address, so that only that browser can move it to an "
            "account, where it takes one of the month's previews"
        )
        return (
            "If you upload a file without an account: the language, the link tag you came "
            f"with ({REF_COOKIE} cookie), the date and, if you later move it to an account, "
            f"when; also your browser's identifier (as a hash only){marks}; and a hash of "
            "the network per day, to count its previews without an account. All of it is "
            f"deleted with the report or after {days} days; the network hash, after {days} "
            "days.",
        )
    if locale == "pt":
        marks = (
            ", o SHA-256 do arquivo e o endereço de rede, para abri-lo como relatório grátis se "
            "você criar a conta"
            if welcome
            else " e o endereço de rede, para que só esse navegador possa passá-lo para uma "
            "conta, onde ocupa uma das prévias do mês"
        )
        return (
            "Se você enviar um arquivo sem conta: o idioma, a etiqueta do link com que você "
            f"chegou (cookie {REF_COOKIE}), a data e, se depois você o passar para uma conta, "
            f"quando; além disso, o identificador do seu navegador (só como hash){marks}; e "
            "um hash da rede por dia, para contar as prévias sem conta. Tudo é apagado com o "
            f"relatório ou após {days} dias; o hash da rede, após {days} dias.",
        )
    marks = (
        ", el SHA-256 del archivo y la dirección de red, para abrirlo como informe gratis si "
        "creas la cuenta"
        if welcome
        else " y la dirección de red, para que solo ese navegador pueda pasarlo a una cuenta, "
        "donde ocupa una de las vistas previas del mes"
    )
    return (
        "Si subes un archivo sin cuenta: el idioma, la etiqueta del enlace con la que "
        f"llegaste (cookie {REF_COOKIE}), la fecha y, si luego lo pasas a una cuenta, cuándo; "
        f"además, el identificador de tu navegador (solo como hash){marks}; y un hash de la "
        "red por día, para contar las vistas previas sin cuenta. Todo se borra con el informe "
        f"o a los {days} días; el hash de la red, a los {days} días.",
    )


def _paid_offer(ctx: LegalContext) -> bool:
    """The paid offer (``paid_offer``): no free first report, card check or invite,
    so what they kept is said only of the accounts that had them, back when we
    offered them."""
    return not ctx.free_mode and not ctx.welcome_full_report


def _device_cookie_use(ctx: LegalContext, locale: str) -> str:
    """What the browser mark (``DEVICE_COOKIE``) is for, in the list of cookies."""
    if not _paid_offer(ctx):
        return {
            "es": "marca tu navegador para el primer informe gratis",
            "en": "marks your browser for the free first report",
            "pt": "marca do navegador para a oferta gratuita",
        }[locale]
    if ctx.anon_preview:
        return {
            "es": (
                "marca tu navegador, para que solo el que subió una vista previa sin cuenta "
                "pueda pasarla a una cuenta y para avisarte de las visitas a «Mi cuenta»"
            ),
            "en": (
                "marks your browser, so that only the one that uploaded a preview without an "
                "account can move it to an account, and for the notice of visits to 'My account'"
            ),
            "pt": (
                "marca do navegador (para que só o navegador que enviou uma prévia sem conta "
                "possa passá-la para uma conta e para o aviso de visitas a 'Minha conta')"
            ),
        }[locale]
    return {
        "es": "marca tu navegador para avisarte de las visitas a «Mi cuenta»",
        "en": "marks your browser for the notice of visits to 'My account'",
        "pt": "marca do navegador para o aviso de visitas a 'Minha conta'",
    }[locale]


def privacy_text(ctx: LegalContext, locale: str = "es") -> LegalText:
    locale = _locale(locale)
    name = _value(ctx.operator_name, locale)
    address = _address(ctx, locale)
    contact = _value(ctx.operator_contact, locale)
    days = ctx.retention_days
    limit = ctx.max_uploads_per_hour_per_ip
    warning = _warning(ctx, locale)
    paid = _paid_offer(ctx)
    if locale == "pt":
        return _privacy_pt(ctx, name, address, contact, days, limit, warning)
    if locale == "en":
        sections: tuple[tuple[str, tuple[str, ...]], ...] = (
            ("Who is responsible", (f"{name}, {address}. Contact: {contact}{_tel(ctx, 'en')}.",)),
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
                    *_anon_keeps(ctx, "en", days),
                    (
                        "If you got the free first full report when we offered it: we keep the "
                        "three hashes taken then, of your browser's random identifier (the "
                        f"{DEVICE_COOKIE} cookie), of the file and of your e-mail in its basic "
                        "form, even if you delete your account and without your e-mail in "
                        "clear text, so that it is not repeated. The network address of then "
                        f"is cleared after {days} days."
                        if paid
                        else "For the free first full report: a random identifier of your "
                        f"browser (a cookie named {DEVICE_COOKIE}, stored by us only as a hash), "
                        "the SHA-256 of the file, a SHA-256 of your e-mail in its basic form "
                        "(lower case, without anything after a '+' and, for Gmail, without dots) "
                        "and the network address, so the same browser, file or inbox gets it "
                        f"only once. The address is cleared after {days} days; the three hashes "
                        "stay, even if you delete your account and without your e-mail in clear "
                        "text, so the offer cannot be repeated."
                    ),
                    *(
                        (
                            (
                                "If you had a card checked for that free report when we offered "
                                "it: we keep only a SHA-256 of the fingerprint Stripe gives that "
                                "card (never its number) and, until you delete your account, the "
                                "date. We no longer check cards for it."
                            )
                            if paid
                            else "If a shared browser or network holds back that free report "
                            "and you verify a card for it: Stripe checks the card without "
                            "charging it, and we keep only a SHA-256 of the fingerprint Stripe "
                            "gives that card (never its number) and the date, so each card "
                            "gives one free report. The date goes with your account; the hash "
                            "stays, like the three above.",
                        )
                        if ctx.card_payments
                        else ()
                    ),
                    (
                        "If you had an invite link, or joined through a colleague's, when there "
                        "were invites: that link and, for the account that joined, the date, "
                        "whether its first report happened and the hash of its browser "
                        "identifier. The inviter sees only counts, never who joined. It is "
                        "deleted with the inviter's account; when the account that joined is "
                        "deleted, its row keeps only the dates and the outcome under a random id "
                        "(no e-mail, no browser hash)."
                        if paid
                        else "For 'Invite a colleague': each account's invite link, and for an "
                        "account created through someone's link, the date, whether its free "
                        "first report happened and the hash of its browser identifier, to "
                        "refuse self-invites. The inviter sees only counts, never who joined. It "
                        "is deleted with the inviter's account; when the account that joined is "
                        "deleted, its row keeps only the dates and the outcome under a random id "
                        "(no e-mail, no browser hash), so the monthly limit still holds."
                    ),
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
                    "its label, kept under the hash of its random mark ("
                    + (
                        f"the {DEVICE_COOKIE} cookie"
                        if paid
                        else "the same cookie as the free report"
                    )
                    + "), only to tell you what happened since; it is deleted after 90 "
                    "days without a visit or with your account.",
                    "To know which of our own links brings visitors: visits to the home "
                    "page, the case pages and the free tools (calculator, figures card, "
                    "examples and the tools page) are counted per day, language and link "
                    "tag (such as "
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
                    "you signed in, one that protects the sign-in forms, one that for up to "
                    "an hour remembers which report to return to after you sign in, one that "
                    + _device_cookie_use(ctx, "en")
                    + ", one that remembers which of "
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
                    (
                        "Paid audits, and the free first full report of whoever got it when we "
                        "offered it: kept so you can reopen the report, until you delete them "
                        "with your account or ask us to delete them."
                        if paid
                        else "Paid audits and your free first full report: kept so you can "
                        "reopen the report, until you delete them with your account or ask us "
                        "to delete them."
                    ),
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
        ("Responsable", (f"{name}, {address}. Contacto: {contact}{_tel(ctx, 'es')}.",)),
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
                *_anon_keeps(ctx, "es", days),
                (
                    "Si recibiste el primer informe completo gratis cuando lo ofrecíamos: "
                    "conservamos los tres hashes que tomamos entonces, del identificador al azar "
                    f"de tu navegador (la cookie {DEVICE_COOKIE}), del archivo y de tu correo en "
                    "su forma básica, aunque borres tu cuenta y sin tu correo en claro, para que "
                    f"no se repita. La dirección de red de entonces se borra a los {days} días."
                    if paid
                    else "Para el primer informe completo gratis: un identificador al azar de tu "
                    f"navegador (una cookie llamada {DEVICE_COOKIE}, que guardamos solo como "
                    "hash), el SHA-256 del archivo, un SHA-256 de tu correo en su forma básica "
                    "(en minúsculas, sin lo que va tras un «+» y, en Gmail, sin puntos) y la "
                    "dirección de red, para que el mismo navegador, archivo o buzón lo reciba una "
                    f"sola vez. La dirección se borra a los {days} días; los tres hashes se "
                    "quedan, aunque borres tu cuenta y sin tu correo en claro, para que la oferta "
                    "no se repita."
                ),
                *(
                    (
                        (
                            "Si verificaste una tarjeta para recibir ese informe gratis cuando lo "
                            "ofrecíamos: conservamos solo un SHA-256 de la huella que Stripe da a "
                            "esa tarjeta (nunca su número) y, hasta que borres tu cuenta, la "
                            "fecha. Ya no verificamos tarjetas para eso."
                        )
                        if paid
                        else "Si un navegador o una red compartidos frenan ese informe gratis y "
                        "verificas una tarjeta para recibirlo: Stripe revisa la tarjeta sin "
                        "cobrarla y nosotros guardamos solo un SHA-256 de la huella que Stripe da"
                        " a esa tarjeta (nunca su número) y la fecha, para que cada tarjeta dé un"
                        " solo informe gratis. La fecha se borra con tu cuenta; el hash se queda,"
                        " como los tres de arriba.",
                    )
                    if ctx.card_payments
                    else ()
                ),
                (
                    "Si tuviste un enlace de invitación, o te uniste con el de un colega, cuando "
                    "había invitaciones: ese enlace y, para la cuenta que se unió, la fecha, si ya "
                    "recibió su primer informe y el hash del identificador de su navegador. Quien "
                    "invitó ve solo cifras, nunca quién se unió. Se borra con la cuenta de quien "
                    "invitó; si se borra la cuenta que se unió, su fila guarda solo las fechas y "
                    "el resultado bajo un id al azar (sin correo ni hash del navegador)."
                    if paid
                    else "Para «Invita a un colega»: el enlace de invitación de cada cuenta y, "
                    "para una cuenta creada con el enlace de alguien, la fecha, si ya recibió su "
                    "primer informe gratis y el hash del identificador de su navegador, para "
                    "rechazar autoinvitaciones. Quien invita ve solo cifras, nunca quién se unió. "
                    "Se borra con la cuenta de quien invita; si se borra la cuenta que se unió, "
                    "su fila guarda solo las fechas y el resultado bajo un id al azar (sin correo "
                    "ni hash del navegador), para que el límite mensual se mantenga."
                ),
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
                "y su etiqueta, guardado bajo el hash de su marca aleatoria ("
                + (f"la cookie {DEVICE_COOKIE}" if paid else "la misma cookie del informe gratis")
                + "), solo para avisarte de lo que pasó desde entonces; se borra a "
                "los 90 días sin visitas o con tu cuenta.",
                "Para saber cuál de nuestros propios enlaces trae visitas: las visitas a la "
                "página principal, a las de cada caso y a las herramientas gratis (calculadora, "
                "tarjeta de cifras, ejemplos y página de herramientas) se cuentan por día, idioma "
                "y etiqueta "
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
                "durante una hora como máximo recuerda a qué informe volver después de entrar, "
                "otra que " + _device_cookie_use(ctx, "es") + ", otra que recuerda cuál de "
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
                (
                    "Auditorías pagadas, y el primer informe completo gratis de quien lo recibió "
                    "cuando lo ofrecíamos: se conservan para que puedas volver a abrir el informe, "
                    "hasta que los borres con tu cuenta o nos pidas borrarlos."
                    if paid
                    else "Auditorías pagadas y tu primer informe completo gratis: se conservan "
                    "para que puedas volver a abrir el informe, hasta que los borres con tu "
                    "cuenta o nos pidas borrarlos."
                ),
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
    paid = _paid_offer(ctx)
    sections: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("Responsável", (f"{name}, {address}. Contato: {contact}{_tel(ctx, 'pt')}.",)),
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
                *_anon_keeps(ctx, "pt", days),
                (
                    "Se você recebeu o primeiro relatório completo gratuito quando o "
                    "oferecíamos: guardamos os três hashes registrados então, do identificador "
                    f"aleatório do navegador (cookie {DEVICE_COOKIE}), do arquivo e do seu "
                    "e-mail na forma básica, mesmo se você excluir a conta e sem o seu e-mail em "
                    "texto claro, para que ele não se repita. O endereço de rede daquela época é "
                    f"eliminado após {days} dias."
                    if paid
                    else "Para o primeiro relatório completo gratuito: um identificador aleatório "
                    f"do navegador (cookie {DEVICE_COOKIE}, guardado por nós apenas como hash), "
                    "o SHA-256 do arquivo, um SHA-256 do seu e-mail na forma básica (em "
                    "minúsculas, sem o que vem após um '+' e, no Gmail, sem pontos) e o endereço "
                    "de rede, para que o mesmo navegador, arquivo ou caixa de entrada o receba "
                    f"uma só vez. O endereço é eliminado após {days} dias; os três hashes "
                    "permanecem, mesmo se você excluir a conta e sem o seu e-mail em texto claro, "
                    "para que a oferta não se repita."
                ),
                *(
                    (
                        (
                            "Se você verificou um cartão para receber esse relatório grátis "
                            "quando o oferecíamos: guardamos só um SHA-256 da impressão que o "
                            "Stripe dá a esse cartão (nunca o número) e, até a exclusão da sua "
                            "conta, a data. Não verificamos mais cartões para isso."
                        )
                        if paid
                        else "Se um navegador ou uma rede compartilhados impedirem esse "
                        "relatório grátis e você verificar um cartão para recebê-lo: o Stripe "
                        "confere o cartão sem cobrar, e guardamos só um SHA-256 da impressão que "
                        "o Stripe dá a esse cartão (nunca o número) e a data, para que cada "
                        "cartão dê um único relatório grátis. A data é eliminada com a sua "
                        "conta; o hash permanece, como os três acima.",
                    )
                    if ctx.card_payments
                    else ()
                ),
                (
                    "Se você teve um link de indicação, ou entrou pelo de um colega, quando havia "
                    "indicações: esse link e, para a conta que entrou, a data, se seu primeiro "
                    "relatório foi concluído e o hash do identificador do navegador. Quem indicou "
                    "vê apenas totais, não a identidade de quem entrou. Esses dados são "
                    "eliminados com a conta de quem indicou. Se a conta indicada for excluída, "
                    "seu registro conserva apenas datas e resultado sob um identificador "
                    "aleatório (sem e-mail nem hash do navegador)."
                    if paid
                    else "Para 'Indique um colega': o link de indicação de cada conta e, para uma "
                    "conta criada por esse link, a data, se seu primeiro relatório gratuito foi "
                    "concluído e o hash do identificador do navegador, para impedir "
                    "autoindicações. Quem indicou vê apenas totais, não a identidade de quem "
                    "entrou. Esses dados são eliminados com a conta de quem indicou. Se a conta "
                    "indicada for excluída, seu registro conserva apenas datas e resultado sob um "
                    "identificador aleatório (sem e-mail nem hash do navegador), para manter o "
                    "limite mensal."
                ),
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
                "inicial, às páginas de casos e às ferramentas grátis (calculadora, cartão de "
                "números, exemplos e página de ferramentas) são contadas por dia, idioma e "
                "etiqueta do "
                "link (como ?ref=f4), sem endereço de rede. O cookie "
                f"{SEEN_COOKIE} guarda só a data de hoje para contar um navegador uma vez "
                "por dia. Se você chega por um link etiquetado, o cookie "
                f"{REF_COOKIE} guarda a etiqueta por {REF_DAYS} dias; se você criar uma conta, "
                "a etiqueta permanece nela até a exclusão.",
            ),
        ),
        (
            "O que não guardamos",
            (
                "Não pedimos nem guardamos chaves de corretora ou bolsa, senhas de conta de "
                "trading ou dados de cartão. Estas páginas não usam analítica ou publicidade "
                "de terceiros. Os cookies são nossos: sessão, proteção dos formulários, "
                "relatório ao qual voltar depois de entrar (por até uma hora), "
                + _device_cookie_use(ctx, "pt")
                + ", origem de nossos próprios links e data "
                "para contar uma visita por dia. Nenhum acompanha você entre sites ou é "
                "compartilhado. Nosso registro de acessos guarda apenas o endereço abreviado "
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
                (
                    "Auditorias pagas, e o primeiro relatório completo gratuito de quem o recebeu "
                    "quando o oferecíamos: guardados para que você possa reabri-los até excluí-los "
                    "com sua conta ou solicitar a exclusão."
                    if paid
                    else "Auditorias pagas e primeiro relatório completo gratuito: guardados para "
                    "que você possa reabri-los até excluí-los com sua conta ou solicitar a "
                    "exclusão."
                ),
                "Página de verificação: pública até você retirá-la no relatório, pedir sua "
                "retirada ou pedir a exclusão da auditoria. Se publicada, a limpeza conserva "
                "apenas o que ela mostra (classe, estados das dimensões, hashes, datas, "
                "número de tentativas e versão do mecanismo), para manter a página e o selo.",
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
