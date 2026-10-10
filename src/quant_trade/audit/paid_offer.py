"""The paid offer: every full report is paid, from the first one.

With ``AUDIT_WELCOME_FULL_REPORT=false`` (``AuditSettings.welcome_full_report``)
no path grants a free full report: not the first upload, not confirming the
e-mail, not a card check, not an invite. The free tier is the preview, the
class from A to D and the red flags of the file: without an account while
``AUDIT_ANON_PREVIEW`` is on, with a free account otherwise (and the account's
monthly previews, as always). The full report costs the configured price and,
if it is no use, the terms refund it when asked within ``REFUND_DAYS`` days of
the payment (``legal._refund``).

Every page words that offer with the sentences here, in es/en/pt with the same
meaning. The pages built around the offer (pricing, the landing's cards, the
upload form, sign-up, the report's box, the questions) take their paid variant
from :func:`paid_text` and :data:`COPY`. The other public pages keep their own
copy and, under the paid offer only, :func:`rewrite_html` swaps each sentence
that promised the free first report (:data:`PROMISES`) for the paid one; with
the free first report on (``welcome``) or in free mode nothing is rewritten.
"""

from __future__ import annotations

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

#: Days after the payment within which a paid report is refunded on request.
REFUND_DAYS = 7

#: What a new visitor's first file gets: every full report free (free mode),
#: the free first full report with an account, or neither (paid from the first).
OFFER_KINDS: tuple[str, ...] = ("free", "welcome", "paid")


@dataclass(frozen=True)
class Offer:
    """The offer as the pages word it, from the settings (:func:`offer_of`).

    ``kind`` is one of :data:`OFFER_KINDS`. The price is the full report's (and
    the pack's when it is on sale). ``anon_preview`` says whether the preview
    needs no account; ``email_verification`` whether an account must confirm
    its e-mail. The default is the welcome offer with no price, so a page built
    without an offer keeps the copy it always had.
    """

    kind: str = "welcome"
    price_usd: float = 0.0
    pack_price_usd: float = 0.0
    anon_preview: bool = False
    email_verification: bool = False

    @property
    def paid(self) -> bool:
        return self.kind == "paid"


def offer_kind(settings: Any) -> str:
    """``free`` in free mode, ``welcome`` with the free first full report, else ``paid``."""
    if settings.free_mode:
        return "free"
    return "welcome" if settings.welcome_full_report else "paid"


def offer_of(settings: Any) -> Offer:
    """The :class:`Offer` the configuration makes."""
    return Offer(
        kind=offer_kind(settings),
        price_usd=settings.price_usd,
        pack_price_usd=settings.pack_price_usd,
        anon_preview=bool(settings.anon_preview) and not settings.free_mode,
        email_verification=bool(settings.email_verification_required),
    )


def as_offer(offer: str | Offer | None) -> Offer:
    """An :class:`Offer` from what a caller passed: an offer, a kind or nothing."""
    if isinstance(offer, Offer):
        return offer
    if offer in OFFER_KINDS:
        return Offer(kind=str(offer))
    return Offer()


#: The paid offer's words. ``preview_anon`` and ``preview_account`` are the free
#: preview without and with an account; ``full`` the price of the full report;
#: ``refund`` and ``pack_refund`` the terms' refund in one sentence each. The
#: other keys are the places that need a word of their own.
COPY: dict[str, dict[str, Any]] = {
    "es": {
        "preview_anon": (
            "Sin cuenta y gratis, ves la clase de A a D y las banderas rojas de tu archivo."
        ),
        "preview_account": (
            "Con una cuenta gratis ves la clase de A a D y las banderas rojas de tu archivo."
        ),
        "full": "El informe completo, con cada cifra y el PDF, cuesta {price}.",
        "refund": (
            "Si no te sirve, te devolvemos el dinero: pídelo en los 7 días siguientes al pago."
        ),
        "pack_refund": (
            "En el paquete, si en esos 7 días no usaste ningún crédito, te lo devolvemos "
            "completo; si usaste alguno, la parte de los créditos sin usar."
        ),
        "trust_anon": "La clase y las banderas rojas, gratis y sin cuenta",
        "trust_account": "La clase y las banderas rojas, gratis con tu cuenta",
        "upload": "Subir mi archivo",
        "preview_title": "Vista previa",
        "preview_note": "La clase de A a D y las banderas rojas",
        "account_previews": "Con tu cuenta, {n} vistas previas gratis al mes.",
        "per_report": "por informe",
        "start_title": "Empieza por la vista previa gratis",
        "summary": (
            "Precios de Rigor: la vista previa gratis, el informe completo y el paquete de 3. "
            "Qué incluyen, devolución en 7 días y países con tarjeta."
        ),
        "single": "{price} por informe completo.",
        "upload_point": (
            "Gratis, la clase y las banderas rojas; el informe completo cuesta {price}."
        ),
        "signin_anon": (
            "Puedes subir tu archivo sin cuenta. Con tu cuenta guardas tus informes en un solo "
            "lugar y abres el completo."
        ),
        "signin_account": "Antes de subir, crea tu cuenta gratis.",
        "how_anon": (
            "Sube el archivo de tu plataforma tal cual, sin cuenta: un backtest, el historial "
            "de una cuenta o una serie de retornos.",
            "Gratis ves la clase de A a D, las banderas rojas y qué significa cada dimensión, "
            "en lenguaje llano.",
            "Crea tu cuenta y abre el informe completo, con cada cifra y el PDF, por {price}.",
            "Tus informes quedan guardados en tu cuenta.",
        ),
        "how_account": (
            "Crea tu cuenta gratis con tu correo.",
            "Sube el archivo de tu plataforma tal cual: un backtest, el historial de una cuenta "
            "o una serie de retornos.",
            "Gratis ves la clase de A a D, las banderas rojas y qué significa cada dimensión, "
            "en lenguaje llano.",
            "Abre el informe completo, con cada cifra y el PDF, por {price}.",
        ),
        "refund_q": "¿Y si el informe no me sirve?",
        "refund_a": (
            "Escribe a {contact} en los 7 días siguientes al pago, con el identificador del "
            "informe o de la compra, y te devolvemos el importe completo. En un paquete, si no "
            "usaste ningún crédito, te lo devolvemos completo; si usaste alguno, la parte de los "
            "créditos sin usar. Si pagaste con tarjeta, lo devolvemos desde Stripe a la misma "
            "tarjeta, en los plazos de tu banco. Los términos lo explican."
        ),
        "contact": "nuestro contacto de soporte",
        "price_q": "¿Cuánto cuesta y qué incluye el informe completo?",
        "price_a": (
            "{preview} {full} Incluye cada cifra, las gráficas, las banderas rojas, pruebas de "
            "estrés, riesgo, simulador de retos y PDF, según los datos aportados. {refund}"
        ),
        "signup_lead": (
            "Con tu cuenta tienes {n} vistas previas gratis al mes, con la clase y las banderas "
            "rojas, y tus informes, créditos y compras en un solo lugar."
        ),
        "next_preview": "Gratis ves la clase de A a D y las banderas rojas de tu archivo.",
        "gate_title": "Crea tu cuenta gratis para seguir",
        "gate_lead": (
            "Con tu cuenta tienes {limit} vistas previas gratis cada mes: la clase de A a D, las "
            "gráficas y las señales de alerta. Tu archivo no se guardó: al crear tu cuenta "
            "vuelves al formulario para subirlo otra vez. Si ya tienes un código de acceso, "
            "entra en tu cuenta y escríbelo en el formulario."
        ),
        "anon_box": "Crea tu cuenta y ábrelo completo por {price}.",
        "anon_signup": "Crear cuenta y abrirlo",
    },
    "en": {
        "preview_anon": (
            "Free and without an account, you see your file's A to D class and red flags."
        ),
        "preview_account": "With a free account you see your file's A to D class and red flags.",
        "full": "The full report, with every figure and the PDF, costs {price}.",
        "refund": "If it is no use to you, we refund your money: ask within 7 days of paying.",
        "pack_refund": (
            "For the pack, if you used none of its credits within those 7 days, we refund it in "
            "full; if you used some, the part of the unused credits."
        ),
        "trust_anon": "The class and the red flags, free and without an account",
        "trust_account": "The class and the red flags, free with your account",
        "upload": "Upload my file",
        "preview_title": "Preview",
        "preview_note": "The A to D class and the red flags",
        "account_previews": "With your account, {n} free previews a month.",
        "per_report": "per report",
        "start_title": "Start with the free preview",
        "summary": (
            "Rigor pricing: the free preview, the full report and the pack of 3. What they "
            "include, the 7-day refund and countries with card payment."
        ),
        "single": "{price} per full report.",
        "upload_point": "Free, the class and the red flags; the full report costs {price}.",
        "signin_anon": (
            "You can upload your file without an account. With an account your reports stay in "
            "one place and you open the full one."
        ),
        "signin_account": "Before you upload, create your free account.",
        "how_anon": (
            "Upload your platform's file as it is, without an account: a backtest, an "
            "account's history or a return series.",
            "For free you see the A to D class, the red flags and what each dimension means, "
            "in plain language.",
            "Create your account and open the full report, with every figure and the PDF, for "
            "{price}.",
            "Your reports stay saved in your account.",
        ),
        "how_account": (
            "Create your free account with your email.",
            "Upload your platform's file as it is: a backtest, an account's history or a "
            "return series.",
            "For free you see the A to D class, the red flags and what each dimension means, "
            "in plain language.",
            "Open the full report, with every figure and the PDF, for {price}.",
        ),
        "refund_q": "What if the report is no use to me?",
        "refund_a": (
            "Write to {contact} within 7 days of paying, with the report's or the purchase's "
            "identifier, and we refund the full amount. For a pack, if you used none of its "
            "credits, we refund it in full; if you used some, the part of the unused credits. "
            "If you paid by card, we refund it from Stripe to the same card, within your bank's "
            "times. The terms set it out."
        ),
        "contact": "our support contact",
        "price_q": "What does the full report cost and what does it include?",
        "price_a": (
            "{preview} {full} It includes every figure, charts, red flags, stress tests, risk, "
            "the challenge simulator and PDF, depending on the supplied data. {refund}"
        ),
        "signup_lead": (
            "With your account you get {n} free previews a month, with the class and the red "
            "flags, and your reports, credits and purchases in one place."
        ),
        "next_preview": "For free you see your file's A to D class and red flags.",
        "gate_title": "Create your free account to go on",
        "gate_lead": (
            "With your account you get {limit} free previews every month: the A to D class, the "
            "charts and the red flags. Your file was not kept: once your account exists you are "
            "back at the form to upload it again. If you already have an access code, sign in "
            "to your account and type it in the form."
        ),
        "anon_box": "Create your account and open it in full for {price}.",
        "anon_signup": "Create an account and open it",
    },
    "pt": {
        "preview_anon": (
            "Sem conta e grátis, você vê a classe de A a D e os alertas do seu arquivo."
        ),
        "preview_account": (
            "Com uma conta grátis você vê a classe de A a D e os alertas do seu arquivo."
        ),
        "full": "O relatório completo, com cada número e o PDF, custa {price}.",
        "refund": (
            "Se não servir para você, devolvemos o seu dinheiro: peça nos 7 dias seguintes ao "
            "pagamento."
        ),
        "pack_refund": (
            "No pacote, se nesses 7 dias você não usou nenhum crédito, devolvemos o valor total; "
            "se usou algum, a parte dos créditos não usados."
        ),
        "trust_anon": "A classe e os alertas, grátis e sem conta",
        "trust_account": "A classe e os alertas, grátis com a sua conta",
        "upload": "Enviar meu arquivo",
        "preview_title": "Prévia",
        "preview_note": "A classe de A a D e os alertas",
        "account_previews": "Com a sua conta, {n} prévias grátis por mês.",
        "per_report": "por relatório",
        "start_title": "Comece pela prévia grátis",
        "summary": (
            "Preços da Rigor: a prévia grátis, o relatório completo e o pacote de 3. O que "
            "incluem, devolução em 7 dias e países com cartão."
        ),
        "single": "{price} por relatório completo.",
        "upload_point": "Grátis, a classe e os alertas; o relatório completo custa {price}.",
        "signin_anon": (
            "Você pode enviar o seu arquivo sem conta. Com uma conta, seus relatórios ficam num "
            "só lugar e você abre o completo."
        ),
        "signin_account": "Antes de enviar, crie a sua conta grátis.",
        "how_anon": (
            "Envie o arquivo da sua plataforma como está, sem conta: um backtest, o histórico "
            "de uma conta ou uma série de retornos.",
            "Grátis, você vê a classe de A a D, os alertas e o que cada dimensão significa, em "
            "linguagem simples.",
            "Crie a sua conta e abra o relatório completo, com cada número e o PDF, por {price}.",
            "Os seus relatórios ficam guardados na sua conta.",
        ),
        "how_account": (
            "Crie a sua conta grátis com o seu e-mail.",
            "Envie o arquivo da sua plataforma como está: um backtest, o histórico de uma "
            "conta ou uma série de retornos.",
            "Grátis, você vê a classe de A a D, os alertas e o que cada dimensão significa, em "
            "linguagem simples.",
            "Abra o relatório completo, com cada número e o PDF, por {price}.",
        ),
        "refund_q": "E se o relatório não me servir?",
        "refund_a": (
            "Escreva para {contact} nos 7 dias seguintes ao pagamento, com o identificador do "
            "relatório ou da compra, e devolvemos o valor total. No pacote, se você não usou "
            "nenhum crédito, devolvemos o valor total; se usou algum, a parte dos créditos não "
            "usados. Se pagou com cartão, devolvemos pelo Stripe no mesmo cartão, nos prazos do "
            "seu banco. Os termos explicam isso."
        ),
        "contact": "o nosso contato de suporte",
        "price_q": "Quanto custa e o que inclui o relatório completo?",
        "price_a": (
            "{preview} {full} Inclui cada número, gráficos, alertas, testes de estresse, risco, "
            "simulador de desafios e PDF, conforme os dados enviados. {refund}"
        ),
        "signup_lead": (
            "Com a sua conta você tem {n} prévias grátis por mês, com a classe e os alertas, e "
            "seus relatórios, créditos e compras num só lugar."
        ),
        "next_preview": "Grátis, você vê a classe de A a D e os alertas do seu arquivo.",
        "gate_title": "Crie sua conta grátis para continuar",
        "gate_lead": (
            "Com a sua conta você tem {limit} prévias grátis por mês: a classe de A a D, os "
            "gráficos e as bandeiras vermelhas. Seu arquivo não foi guardado: com a conta criada "
            "você volta ao formulário para enviá-lo de novo. Se você já tem um código de acesso, "
            "entre na sua conta e digite-o no formulário."
        ),
        "anon_box": "Crie a sua conta e abra-o completo por {price}.",
        "anon_signup": "Criar conta e abri-lo",
    },
}


def _locale(locale: str) -> str:
    return locale if locale in COPY else "es"


def _usd(amount: float) -> str:
    # Lazy: pricing imports this module.
    from quant_trade.audit.pricing import usd

    return usd(amount)


def words(locale: str) -> dict[str, Any]:
    """The paid offer's words in ``locale`` (Spanish for any other)."""
    return COPY[_locale(locale)]


def preview_text(locale: str, offer: Offer) -> str:
    """The free preview: without an account while ``anon_preview``, else with one."""
    return words(locale)["preview_anon" if offer.anon_preview else "preview_account"]


def full_text(locale: str, offer: Offer) -> str:
    """The full report's price, from the settings."""
    return str(words(locale)["full"]).format(price=_usd(offer.price_usd))


def refund_text(locale: str) -> str:
    """The terms' refund of a report, in one sentence."""
    return str(words(locale)["refund"])


def pack_refund_text(locale: str) -> str:
    """The terms' refund of a pack, in one sentence."""
    return str(words(locale)["pack_refund"])


def paid_text(locale: str, offer: Offer) -> str:
    """The paid offer in three sentences: the free preview, the price, the refund."""
    return f"{preview_text(locale, offer)} {full_text(locale, offer)} {refund_text(locale)}"


def signup_lead(locale: str, offer: Offer, previews: int) -> str:
    """The sign-up page's lead: the account's free previews, the price, the refund."""
    lead = str(words(locale)["signup_lead"]).format(n=previews)
    return f"{lead} {full_text(locale, offer)} {refund_text(locale)}"


def next_report_text(locale: str, offer: Offer) -> str:
    """The last step of sign-up's "What happens next": the preview, the price, the refund."""
    return f"{words(locale)['next_preview']} {full_text(locale, offer)} {refund_text(locale)}"


def gate_text(locale: str, offer: Offer, limit: int) -> tuple[str, str]:
    """The "create your account" page of an upload the free tier does not cover,
    under the paid offer: the account's previews, the price, the refund."""
    copy = words(locale)
    lead = str(copy["gate_lead"]).format(limit=limit)
    return copy["gate_title"], f"{lead} {full_text(locale, offer)} {refund_text(locale)}"


def anon_box_text(locale: str, offer: Offer) -> str:
    """The box of a preview its uploader made without an account: the account
    opens it in full for the price, with the refund."""
    box = str(words(locale)["anon_box"]).format(price=_usd(offer.price_usd))
    return f"{box} {refund_text(locale)}"


def how_steps(locale: str, offer: Offer) -> tuple[str, ...]:
    """The landing's "How it works" under the paid offer."""
    steps = words(locale)["how_anon" if offer.anon_preview else "how_account"]
    return tuple(step.format(price=_usd(offer.price_usd)) for step in steps)


def refund_question(locale: str, contact: str = "") -> tuple[str, str]:
    """«¿Y si el informe no me sirve?» and its answer, as the terms put it.

    ``contact`` is the operator's support e-mail; without one the answer names
    the support contact the terms and the contact page give."""
    copy = words(locale)
    return copy["refund_q"], str(copy["refund_a"]).format(contact=contact or copy["contact"])


def price_question(locale: str, offer: Offer) -> tuple[str, str]:
    """The questions page's first question under the paid offer."""
    copy = words(locale)
    answer = str(copy["price_a"]).format(
        preview=preview_text(locale, offer),
        full=full_text(locale, offer),
        refund=refund_text(locale),
    )
    return copy["price_q"], answer


#: The sentences the other public pages use for the free first report, and what
#: the paid offer says in their place, by language. Each pattern is a regular
#: expression over a page's text; the replacement may name ``{paid}``
#: (:func:`paid_text`), ``{preview}``, ``{refund}`` or ``{upload}``. More
#: specific patterns come first. A test renders every public page with the
#: welcome offer and checks that each pattern still finds its sentence, so a
#: reworded promise cannot slip past the paid offer unnoticed.
PROMISES: dict[str, tuple[tuple[str, str], ...]] = {
    "es": (
        (
            r"Tu primer informe completo es gratis al crear tu cuenta\. Después, la vista "
            r"previa es gratis",
            "{preview} Con tu cuenta, la vista previa es gratis",
        ),
        (r"el paquete de 3\)\.", "el paquete de 3). {refund}"),
        (
            r"Para revisar el archivo y sus ausencias, el primer informe completo es gratis con "
            r"cuenta\.",
            "Para revisar el archivo y sus ausencias, súbelo. {paid}",
        ),
        (
            r"El primer informe completo gratis usa el mismo acceso que los demás artículos\.",
            "{paid}",
        ),
        (
            r"(?:Con tu cuenta, el|El|Tu) primer informe completo (?:también )?es gratis"
            r"(?: al crear (?:tu )?cuenta| con (?:tu )?cuenta)?(?:, con PDF)?\.",
            "{paid}",
        ),
        (
            r"Empieza por el primer informe completo gratis con tu cuenta para revisar",
            "Empieza por la vista previa gratis y el informe completo para revisar",
        ),
        (r"El informe gratis permite empezar", "El informe permite empezar"),
        (r"Qué llevar al informe gratis", "Qué llevar al informe"),
        (r"Pedir mi primer informe gratis", "{upload}"),
        (
            r"Las pagadas y el primer informe completo gratis se conservan",
            "Las pagadas se conservan",
        ),
        (
            r"Respuestas sobre el informe gratis de Rigor",
            "Respuestas sobre la vista previa de Rigor",
        ),
    ),
    "en": (
        (
            r"Your first full report is free when you create your account\. After that the "
            r"preview is free",
            "{preview} With an account the preview is free",
        ),
        (r"for a pack of 3\)\.", "for a pack of 3). {refund}"),
        (
            r"To examine the file and its gaps, your first full report is free with an "
            r"account\.",
            "To examine the file and its gaps, upload it. {paid}",
        ),
        (r"The free first full report uses the same access as the other articles\.", "{paid}"),
        (
            r"(?:With an account, your|Your) first full report is free"
            r"(?: too| with an account| when you create your account)?(?:, with the PDF)?\.",
            "{paid}",
        ),
        (
            r"Start with the free first full report available with your account to review",
            "Start with the free preview and the full report to review",
        ),
        (r"The free report lets you start", "The report lets you start"),
        (r"What to bring to the free report", "What to bring to the report"),
        (r"Get my free first report", "{upload}"),
        (r"Paid audits and the first free full report are kept", "Paid audits are kept"),
        (r"Answers about Rigor's free report", "Answers about Rigor's preview"),
    ),
    "pt": (
        (
            r"O seu primeiro relatório completo é grátis ao criar a sua conta\. Depois, a "
            r"prévia é grátis",
            "{preview} Com uma conta, a prévia é grátis",
        ),
        (r"o pacote de 3\)\.", "o pacote de 3). {refund}"),
        (
            r"Para examinar o arquivo e suas lacunas, o primeiro relatório completo é grátis "
            r"com conta\.",
            "Para examinar o arquivo e suas lacunas, envie-o. {paid}",
        ),
        (
            r"O primeiro relatório completo gratuito usa o mesmo acesso dos demais artigos\.",
            "{paid}",
        ),
        (
            r"(?:Com a sua conta, o|O seu|Seu|O) primeiro relatório completo (?:também )?é "
            r"grátis(?: ao criar a(?: sua)? conta| com (?:a sua )?conta)?(?:, com o PDF)?\.",
            "{paid}",
        ),
        (
            r"Comece pelo primeiro relatório completo grátis com sua conta para examinar",
            "Comece pela prévia grátis e pelo relatório completo para examinar",
        ),
        (r"O relatório grátis permite começar", "O relatório permite começar"),
        (r"O que levar ao relatório grátis", "O que levar ao relatório"),
        (r"Pedir o meu primeiro relatório grátis", "{upload}"),
        (r"As pagas e o primeiro relatório completo grátis ficam", "As pagas ficam"),
        (r"Respostas sobre o relatório grátis da Rigor", "Respostas sobre a prévia da Rigor"),
    ),
}

_COMPILED: dict[str, tuple[tuple[re.Pattern[str], str], ...]] = {
    locale: tuple((re.compile(pattern), new) for pattern, new in pairs)
    for locale, pairs in PROMISES.items()
}


def _replacements(locale: str, offer: Offer) -> dict[str, str]:
    copy = words(locale)
    return {
        "paid": paid_text(locale, offer),
        "preview": preview_text(locale, offer),
        "refund": refund_text(locale),
        "upload": str(copy["upload"]),
    }


def rewrite_text(text: str, locale: str, offer: str | Offer | None) -> str:
    """``text`` with each free-first-report sentence worded for the paid offer.

    Unchanged unless ``offer`` is the paid one: the welcome and free offers keep
    every page exactly as it was."""
    terms = as_offer(offer)
    if not terms.paid:
        return text
    lang = _locale(locale)
    values = _replacements(lang, terms)
    for pattern, new in _COMPILED[lang]:
        text = pattern.sub(_literal(new.format(**values)), text)
    return text


def _literal(value: str) -> Callable[[re.Match[str]], str]:
    """A replacement taken as written: no group references, no escapes."""
    return lambda _match: value


#: The raw-text elements a page carries: their content is never prose.
_RAW = re.compile(r"(<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>)", re.S | re.I)
_JSON_LD = re.compile(r"<script type='application/ld\+json'>(.*?)</script>", re.S)
_TAG = re.compile(r"(<[^>]*>)")
_ATTRIBUTE = re.compile(r"(\b(?:content|title|aria-label|alt)=')([^']*)(')")


def _rewrite_json(value: Any, locale: str, offer: Offer) -> Any:
    if isinstance(value, str):
        return rewrite_text(value, locale, offer)
    if isinstance(value, list):
        return [_rewrite_json(item, locale, offer) for item in value]
    if isinstance(value, dict):
        return {key: _rewrite_json(item, locale, offer) for key, item in value.items()}
    return value


def rewrite_html(page: str, locale: str, offer: str | Offer | None) -> str:
    """A rendered page with :func:`rewrite_text` applied to its text and its JSON-LD.

    Only the text between tags changes, escaped as the pages escape it; scripts
    and styles are left alone, except the structured data, which is decoded,
    rewritten and encoded the way ``seo._json_ld`` encodes it. Unchanged unless
    ``offer`` is the paid one."""
    terms = as_offer(offer)
    if not terms.paid:
        return page
    # Lazy: seo imports the page modules, which import this one.
    from quant_trade.audit.seo import _json_ld

    def raw(element: str) -> str:
        found = _JSON_LD.fullmatch(element)
        if found is None:
            return element
        try:
            data = json.loads(found.group(1))
        except ValueError:
            return element
        return _json_ld(_rewrite_json(data, locale, terms))

    def text(part: str) -> str:
        if not part:
            return part
        if part.startswith("<"):
            return _ATTRIBUTE.sub(lambda m: m.group(1) + text(m.group(2)) + m.group(3), part)
        plain = html.unescape(part)
        new = rewrite_text(plain, locale, terms)
        return part if new == plain else html.escape(new, quote=True)

    # ``split`` with one group: the odd items are the script and style elements.
    return "".join(
        raw(chunk) if index % 2 else "".join(text(part) for part in _TAG.split(chunk))
        for index, chunk in enumerate(_RAW.split(page))
    )


__all__ = [
    "COPY",
    "OFFER_KINDS",
    "PROMISES",
    "REFUND_DAYS",
    "Offer",
    "anon_box_text",
    "as_offer",
    "full_text",
    "gate_text",
    "how_steps",
    "next_report_text",
    "offer_kind",
    "offer_of",
    "pack_refund_text",
    "paid_text",
    "preview_text",
    "price_question",
    "refund_question",
    "refund_text",
    "rewrite_html",
    "rewrite_text",
    "signup_lead",
    "words",
]
