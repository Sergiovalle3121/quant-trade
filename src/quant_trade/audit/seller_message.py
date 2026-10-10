"""The questions for the seller as one message, ready to paste in a chat.

A buyer of a signal asked for the report's questions "in a message ready to
copy into the MQL5 or Telegram chat, with the key figures and the costs in
pips". When the client declared "La compré o la voy a comprar / copiar"
(``ownership.BUYER``), the questions section of the full report ends with a
plain text built from the report's own data only (``report._seller_message``):
a neutral greeting, the class, the dimensions that do not pass, the weak ones
apart and those not measured, two to four key figures with their evidence tag
in words (summary tiles complete them when the files gave fewer), the open
questions numbered, the public page's link when the report is published and
"Informe hecho con Rigor (rigorscore.com)". The copy button is the site's ``data-copy`` button
(``static/app.js``), so no new script is needed.

Only the buyer gets it: the developer's and the neutral voice send nobody to a
seller, and the provider's questions section already reads, item by item, what
clients will ask and what to provide (``ownership.QUESTION_ITEM``), so a second
text would repeat it. The locked preview does not render it (the lock box
names it, for the buyer only), and it is hidden when printed: the PDF already
carries the questions.

This module holds the message's words in Spanish, English and Portuguese side
by side, and the seller's wording of the stored questions that speak to the
buyer ("Pide el archivo de optimización" becomes "¿Puedes enviar el archivo de
optimización?"). The stored questions themselves are unchanged.
"""

from __future__ import annotations

#: Telegram takes 4,096 characters per message; the text stays under this.
MAX_CHARS = 4000
#: The ``?ref=`` tag of the public link in the message (``funnel.REF_TAGS``).
REF = "vendedor"
#: The id of the text the copy button copies.
TEXT_ID = "seller-message-text"
#: Key figures in the message: at least this many measured or declared ones
#: (summary tiles complete them) ...
MIN_FIGURES = 2
#: ... and at most this many lines, "not measured" ones included.
MAX_FIGURES = 4


def _say(es: str, en: str, pt: str) -> dict[str, str]:
    return {"es": es, "en": en, "pt": pt}


#: The block around the text and the text's fixed lines.
COPY: dict[str, dict[str, str]] = {
    "es": {
        "title": "Mensaje para el vendedor",
        "title_fund": "Mensaje para el gestor",
        "who": "el vendedor",
        "who_fund": "el gestor",
        "intro": (
            "Para pegar en el chat de MQL5, en Telegram, en un correo o donde hables con {who}: "
            "la clase, unas cifras clave con su etiqueta y las preguntas de arriba, en un solo "
            "texto."
        ),
        "copy": "Copiar mensaje",
        "done": "Mensaje copiado",
        "trimmed_note": (
            "No caben todas en un mensaje de Telegram (menos de 4,000 caracteres): el mensaje "
            "lleva {shown} de las {total} preguntas; las demás están arriba."
        ),
        "lock": "Un mensaje para el vendedor con esas preguntas, listo para copiar",
        "lock_fund": "Un mensaje para el gestor con esas preguntas, listo para copiar",
        "hello": "Hola. Revisé los archivos de esta estrategia con Rigor y me quedaron algunas "
        "preguntas.",
        "hello_fund": "Hola. Revisé el historial de este fondo con Rigor y me quedaron algunas "
        "preguntas.",
        "class": "Clase del informe: {cls} (A es la más alta, D la más baja).",
        "dimensions": "Dimensiones que no superan: {items}.",
        "dimensions_none": "Dimensiones que no superan: ninguna.",
        "dimensions_weak": "Dimensiones débiles: {items}.",
        "unmeasured": "Dimensiones sin medir: {items}.",
        "figures": "Cifras clave:",
        "questions": "Preguntas:",
        "trimmed": "Quedan {n} preguntas más en el informe.",
        "trimmed_one": "Queda 1 pregunta más en el informe.",
        "thanks": "Gracias de antemano.",
        "public": "Informe público: {url}",
        "made": "Informe hecho con Rigor (rigorscore.com)",
        "not_measured": "no medido",
        "dd_platform": "Drawdown con operaciones abiertas, según el informe de la plataforma",
    },
    "en": {
        "title": "Message for the seller",
        "title_fund": "Message for the manager",
        "who": "the seller",
        "who_fund": "the manager",
        "intro": (
            "To paste in the MQL5 chat, on Telegram, in an email or wherever you talk to {who}: "
            "the class, a few key figures with their tag and the questions above, in one text."
        ),
        "copy": "Copy message",
        "done": "Message copied",
        "trimmed_note": (
            "They do not all fit in one Telegram message (under 4,000 characters): the message "
            "carries {shown} of the {total} questions; the rest are above."
        ),
        "lock": "A message for the seller with those questions, ready to copy",
        "lock_fund": "A message for the manager with those questions, ready to copy",
        "hello": "Hi. I went through this strategy's files with Rigor and have a few questions.",
        "hello_fund": "Hi. I went through this fund's record with Rigor and have a few questions.",
        "class": "Report class: {cls} (A is the highest, D the lowest).",
        "dimensions": "Dimensions that do not pass: {items}.",
        "dimensions_none": "Dimensions that do not pass: none.",
        "dimensions_weak": "Weak dimensions: {items}.",
        "unmeasured": "Dimensions not measured: {items}.",
        "figures": "Key figures:",
        "questions": "Questions:",
        "trimmed": "{n} more questions are in the report.",
        "trimmed_one": "1 more question is in the report.",
        "thanks": "Thanks in advance.",
        "public": "Public report: {url}",
        "made": "Report made with Rigor (rigorscore.com)",
        "not_measured": "not measured",
        "dd_platform": "Drawdown with open trades, per the platform's report",
    },
    "pt": {
        "title": "Mensagem para o vendedor",
        "title_fund": "Mensagem para o gestor",
        "who": "o vendedor",
        "who_fund": "o gestor",
        "intro": (
            "Para colar no chat do MQL5, no Telegram, num e-mail ou onde você fala com {who}: "
            "a classe, alguns números-chave com sua etiqueta e as perguntas acima, num só texto."
        ),
        "copy": "Copiar mensagem",
        "done": "Mensagem copiada",
        "trimmed_note": (
            "Nem todas cabem numa mensagem do Telegram (menos de 4.000 caracteres): a mensagem "
            "leva {shown} das {total} perguntas; as demais estão acima."
        ),
        "lock": "Uma mensagem para o vendedor com essas perguntas, pronta para copiar",
        "lock_fund": "Uma mensagem para o gestor com essas perguntas, pronta para copiar",
        "hello": "Olá. Analisei os arquivos desta estratégia com o Rigor e fiquei com algumas "
        "perguntas.",
        "hello_fund": "Olá. Analisei o histórico deste fundo com o Rigor e fiquei com algumas "
        "perguntas.",
        "class": "Classe do relatório: {cls} (A é a mais alta, D a mais baixa).",
        "dimensions": "Dimensões que não passam: {items}.",
        "dimensions_none": "Dimensões que não passam: nenhuma.",
        "dimensions_weak": "Dimensões fracas: {items}.",
        "unmeasured": "Dimensões não medidas: {items}.",
        "figures": "Números-chave:",
        "questions": "Perguntas:",
        "trimmed": "Há mais {n} perguntas no relatório.",
        "trimmed_one": "Há mais 1 pergunta no relatório.",
        "thanks": "Agradeço desde já.",
        "public": "Relatório público: {url}",
        "made": "Relatório feito com o Rigor (rigorscore.com)",
        "not_measured": "não medido",
        "dd_platform": "Drawdown com operações abertas, segundo o relatório da plataforma",
    },
}

#: The stored questions (``analytics._QUESTIONS``) whose wording speaks to the
#: buyer ("Pide...", "Ask for...") or names "your broker", as the buyer asks
#: them of the seller. Every other stored question is already a plain question
#: and goes into the message as the report shows it.
SELLER_ASK: dict[str, dict[str, str]] = {
    "other_accounts": _say(
        "¿Es la única cuenta con esta estrategia? ¿Hay otras cuentas con ella que se cerraron "
        "o se reiniciaron?",
        "Is this the only account running this strategy? Are there other accounts with it "
        "that were closed or restarted?",
        "Esta é a única conta com esta estratégia? Há outras contas com ela que foram "
        "encerradas ou reiniciadas?",
    ),
    "backtest_match": _say(
        "¿La estrategia de esta cuenta tiene un backtest? Si lo tiene, ¿puedes enviarlo con la "
        "misma configuración que esta cuenta?",
        "Does this account's strategy have a backtest? If it does, can you send it with the "
        "same settings as this account?",
        "A estratégia desta conta tem um backtest? Se tiver, você pode enviá-lo com a mesma "
        "configuração desta conta?",
    ),
    "trials": _say(
        "¿Cuántas combinaciones de parámetros se probaron antes de elegir esta? ¿Puedes enviar "
        "el archivo de optimización?",
        "How many parameter combinations were tried before choosing this one? Can you send the "
        "optimisation file?",
        "Quantas combinações de parâmetros foram testadas antes de escolher esta? Você pode "
        "enviar o arquivo de otimização?",
    ),
    "costs": _say(
        "¿Qué spread, comisión y swap se usaron en la prueba? ¿De qué bróker son?",
        "Which spread, commission and swap did the test use? Which broker are they from?",
        "Quais spread, comissão e swap foram usados no teste? De qual corretora são?",
    ),
    "equity_curve": _say(
        "¿Puedes enviar la curva de equity (con el flotante), no solo la de balance?",
        "Can you send the equity curve (with floating results), not only the balance?",
        "Você pode enviar a curva de patrimônio (com o flutuante), não só a de saldo?",
    ),
    "trades": _say(
        "¿Puedes enviar la lista completa de operaciones cerradas, con tamaños, precios y fechas?",
        "Can you send the full list of closed trades, with sizes, prices and dates?",
        "Você pode enviar a lista completa de operações fechadas, com tamanhos, preços e datas?",
    ),
    "deposits": _say(
        "¿Puedes enviar el historial completo con cada depósito y retiro? ¿Cuánto dinero se "
        "depositó en total, cuándo, y cuánto se retiró?",
        "Can you send the full history with every deposit and withdrawal? How much money was "
        "deposited in total, when, and how much was withdrawn?",
        "Você pode enviar o histórico completo com cada depósito e saque? Quanto dinheiro foi "
        "depositado no total, quando, e quanto foi sacado?",
    ),
    "fund_other": _say(
        "¿El gestor lleva otros fondos o cuentas con la misma estrategia, incluidos los que se "
        "cerraron?",
        "Does the manager run other funds or accounts with the same strategy, including ones "
        "that were closed?",
        "O gestor tem outros fundos ou contas com a mesma estratégia, incluindo os que foram "
        "encerrados?",
    ),
    "fund_admin": _say(
        "¿Quién calcula el valor liquidativo y quién audita las cuentas del fondo? ¿Cómo se "
        "llaman el administrador y el auditor independientes?",
        "Who calculates the net asset value and who audits the fund's accounts? What are the "
        "names of the independent administrator and auditor?",
        "Quem calcula o valor da cota e quem audita as contas do fundo? Quais são os nomes do "
        "administrador e do auditor independentes?",
    ),
}


def words(locale: str) -> dict[str, str]:
    """The block's and the message's fixed words in ``locale`` (Spanish by default)."""
    return COPY.get(locale, COPY["es"])


def seller_question(code: str, stored: str, locale: str) -> str:
    """One open question as the buyer puts it to the seller: the seller's wording
    when the stored one speaks to the buyer, else the stored text (already in
    ``locale``)."""
    return SELLER_ASK.get(code, {}).get(locale) or stored


def chat_length(text: str) -> int:
    """The length a chat counts: UTF-16 code units, so a character outside the
    basic plane counts twice, as Telegram counts it."""
    return len(text.encode("utf-16-le")) // 2


__all__ = [
    "COPY",
    "MAX_CHARS",
    "MAX_FIGURES",
    "MIN_FIGURES",
    "REF",
    "SELLER_ASK",
    "TEXT_ID",
    "chat_length",
    "seller_question",
    "words",
]
