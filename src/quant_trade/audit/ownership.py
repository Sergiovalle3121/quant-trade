"""Whose strategy it is: an optional declaration that sets to whom the report speaks.

The upload form asks "¿De quién es esta estrategia?" with four answers: the
client's own ("own"), one they bought or are about to buy or copy ("buyer"),
one they provide and show to others ("provider"), or no answer. An answer is
stored as a DECLARED field of the result (``declared.ownership``); no answer
declares nothing, and the report then speaks in a neutral voice, never the
buyer's by default.

The voice changes only the sentences that speak to someone: "What to do
now", the plan to reach a better class, the questions section and the few
lines that send the reader to a seller. The order of the sections, every
figure, the class and the evidence tags are the same whatever the answer,
and the public verification page and cards never show it.

Each table below holds, per text, the wording for each voice that differs
from the buyer's, in Spanish, English and Portuguese side by side; a voice a
text does not list keeps the buyer's wording, which stays where it always
was (``report.LABELS``, ``plan``, ``verdict.MEANING``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quant_trade.audit.live import MIN_LIVE_TRADES

OWN = "own"
BUYER = "buyer"
PROVIDER = "provider"
#: The voice when nothing was declared: it serves all three readers.
NEUTRAL = "neutral"
#: The answers the form offers, in its order; "" is "I'd rather not say".
ROLES: tuple[str, ...] = (OWN, BUYER, PROVIDER)
VOICES: tuple[str, ...] = (*ROLES, NEUTRAL)
LOCALES: tuple[str, ...] = ("es", "en", "pt")

#: The upload form's field: its label, help line and the four answers.
FORM: dict[str, dict[str, Any]] = {
    "es": {
        "label": "¿De quién es esta estrategia? (opcional)",
        "field": "De quién es la estrategia",
        "help": (
            "Cambia solo a quién se dirigen «Qué hacer ahora», el plan y las preguntas del "
            "informe: las cifras, la clase y las etiquetas son las mismas. Queda en el informe "
            "como declaración tuya y no aparece en la página pública."
        ),
        "choices": {
            OWN: "Es mía (la desarrollé o la opero yo)",
            BUYER: "La compré o la voy a comprar / copiar",
            PROVIDER: "Soy el proveedor y la muestro a otros",
            "": "Prefiero no decirlo",
        },
    },
    "en": {
        "label": "Whose strategy is this? (optional)",
        "field": "Whose strategy it is",
        "help": (
            "It only changes whom “What to do now”, the plan and the report's questions speak "
            "to: the figures, the class and the tags stay the same. It stays in the report as "
            "your declaration and is not shown on the public page."
        ),
        "choices": {
            OWN: "It's mine (I built it or I run it)",
            BUYER: "I bought it or am about to buy / copy it",
            PROVIDER: "I'm the provider and show it to others",
            "": "I'd rather not say",
        },
    },
    "pt": {
        "label": "De quem é esta estratégia? (opcional)",
        "field": "De quem é a estratégia",
        "help": (
            "Muda só a quem se dirigem «O que fazer agora», o plano e as perguntas do "
            "relatório: os números, a classe e as etiquetas são os mesmos. Fica no relatório "
            "como declaração sua e não aparece na página pública."
        ),
        "choices": {
            OWN: "É minha (eu a desenvolvi ou a opero)",
            BUYER: "Comprei ou vou comprar / copiar",
            PROVIDER: "Sou o fornecedor e a mostro a outros",
            "": "Prefiro não dizer",
        },
    },
}


def role_of(data: Mapping[str, Any] | None) -> str:
    """The voice of a stored result (its JSON dict): the declared role, else neutral."""
    declared = (data or {}).get("declared") or {}
    item = declared.get("ownership") if isinstance(declared, Mapping) else None
    value = item.get("value") if isinstance(item, Mapping) else None
    return str(value) if value in ROLES else NEUTRAL


def choice_label(value: Any, locale: str) -> str:
    """The form's wording of a declared answer, as the report's declarations show it."""
    choices = FORM.get(locale, FORM["es"])["choices"]
    return str(choices.get(str(value), value))


def _say(es: str, en: str, pt: str) -> dict[str, str]:
    return {"es": es, "en": en, "pt": pt}


#: ``report.LABELS`` keys in the voices that differ from the buyer's.
LABELS: dict[str, dict[str, dict[str, str]]] = {
    "next_intro": {
        OWN: _say(
            "Si la estrategia es tuya, esto es lo que conviene probar primero, según lo que "
            "encontró la auditoría.",
            "If the strategy is yours, this is what is worth testing first, from what the "
            "audit found.",
            "Se a estratégia é sua, isto é o que convém testar primeiro, segundo o que a "
            "auditoria encontrou.",
        ),
        PROVIDER: _say(
            "Si muestras esta estrategia a otros, esto es lo primero que te van a preguntar al "
            "ver este informe, según lo que encontró la auditoría, y con qué responder.",
            "If you show this strategy to others, this is what they will ask you first on "
            "seeing this report, from what the audit found, and what to answer with.",
            "Se você mostra esta estratégia a outros, isto é o que vão perguntar a você "
            "primeiro ao ver este relatório, segundo o que a auditoria encontrou, e com o que "
            "responder.",
        ),
        NEUTRAL: _say(
            "Esto es lo que conviene aclarar primero, según lo que encontró la auditoría.",
            "This is what is worth clearing up first, from what the audit found.",
            "Isto é o que convém esclarecer primeiro, segundo o que a auditoria encontrou.",
        ),
    },
    "next_live": {
        OWN: _say(
            "Busca por qué la cuenta real queda fuera de lo que el backtest hacía esperar: "
            "comprueba que corre la misma configuración y compara los costos de tu bróker con "
            "los del backtest.",
            "Find out why the live account falls outside what the backtest led you to expect: "
            "check that it runs the same settings and compare your broker's costs with the "
            "backtest's.",
            "Descubra por que a conta real fica fora do que o backtest levava a esperar: "
            "confira se roda a mesma configuração e compare os custos da sua corretora com os "
            "do backtest.",
        ),
        PROVIDER: _say(
            "Te van a preguntar por qué la cuenta real queda fuera de lo que el backtest hacía "
            "esperar: aporta el backtest exacto de la configuración que corre esa cuenta.",
            "You will be asked why the live account falls outside what the backtest led people "
            "to expect: provide the exact backtest of the settings that account runs.",
            "Vão perguntar a você por que a conta real fica fora do que o backtest levava a "
            "esperar: forneça o backtest exato da configuração que essa conta roda.",
        ),
        NEUTRAL: _say(
            "Conviene aclarar por qué la cuenta real queda fuera de lo que el backtest hacía "
            "esperar.",
            "It is worth clearing up why the live account falls outside what the backtest led "
            "one to expect.",
            "Convém esclarecer por que a conta real fica fora do que o backtest levava a esperar.",
        ),
    },
    "next_costs": {
        PROVIDER: _say(
            "Te van a preguntar si el resultado aguanta el spread y la comisión de su bróker: "
            "con un costo algo mayor que el de referencia, el margen se pierde.",
            "You will be asked whether the result can bear their broker's spread and "
            "commission: a cost a little above the reference erases the margin.",
            "Vão perguntar a você se o resultado suporta o spread e a comissão da corretora "
            "deles: com um custo um pouco acima do de referência, a margem desaparece.",
        ),
    },
    "next_costs_fail": {
        PROVIDER: _say(
            "Te van a preguntar por los costos: con el costo de referencia, las operaciones ya "
            "pierden dinero en neto.",
            "You will be asked about costs: at the reference cost the trades already lose "
            "money net.",
            "Vão perguntar a você sobre os custos: com o custo de referência, as operações já "
            "perdem dinheiro no líquido.",
        ),
    },
    "next_trials": {
        OWN: _say(
            "Reduce los intentos en la próxima versión (menos parámetros, rangos más cortos) y "
            "valida la configuración elegida en un tramo que no usaste al optimizar.",
            "Cut the trials in the next version (fewer parameters, narrower ranges) and "
            "validate the chosen settings on a stretch you did not use while optimising.",
            "Reduza as tentativas na próxima versão (menos parâmetros, faixas mais curtas) e "
            "valide a configuração escolhida em um trecho que você não usou na otimização.",
        ),
        PROVIDER: _say(
            "Te van a preguntar cuántas configuraciones se probaron antes de elegir esta y con "
            "qué periodo se eligió: ten a mano el XML de la optimización de MT5.",
            "You will be asked how many configurations were tried before this one was chosen, "
            "and on which period: keep the MT5 optimisation XML at hand.",
            "Vão perguntar a você quantas configurações foram testadas antes de escolher esta e "
            "em qual período ela foi escolhida: tenha à mão o XML da otimização do MT5.",
        ),
        NEUTRAL: _say(
            "Conviene aclarar cuántas configuraciones se probaron antes de elegir esta y con "
            "qué periodo se eligió.",
            "It is worth clearing up how many configurations were tried before this one was "
            "chosen, and on which period it was chosen.",
            "Convém esclarecer quantas configurações foram testadas antes de escolher esta e em "
            "qual período ela foi escolhida.",
        ),
    },
    "next_oos": {
        OWN: _say(
            "Prueba la configuración en datos que el optimizador no vio: reoptimiza sin los "
            "últimos meses, corre el resultado sobre el periodo completo y declara la fecha de "
            "corte como inicio fuera de muestra; o activa el periodo forward en la optimización "
            "de MT5 y sube ese XML.",
            "Test the settings on data the optimiser never saw: reoptimise without the last "
            "months, run the result over the whole period and declare the cut-off date as the "
            "out-of-sample start; or turn on the forward period in the MT5 optimisation and "
            "upload that XML.",
            "Teste a configuração em dados que o otimizador não viu: reotimize sem os últimos "
            "meses, rode o resultado no período completo e declare a data de corte como início "
            "fora da amostra; ou ative o período forward na otimização do MT5 e envie esse XML.",
        ),
        PROVIDER: _say(
            "Te van a preguntar cómo se comportó después de su optimización: aporta un informe "
            "del mismo robot, sin cambios, en fechas posteriores, o declara la fecha en que "
            "terminó la optimización.",
            "You will be asked how it behaved after its optimisation: provide a report of the "
            "same robot, unchanged, on later dates, or declare the date the optimisation ended.",
            "Vão perguntar a você como se comportou depois da otimização: forneça um relatório "
            "do mesmo robô, sem mudanças, em datas posteriores, ou declare a data em que a "
            "otimização terminou.",
        ),
        NEUTRAL: _say(
            "Hace falta un informe del mismo robot, sin cambios, en fechas posteriores a su "
            "optimización.",
            "A report of the same robot, unchanged, on dates after its optimisation is needed.",
            "É preciso um relatório do mesmo robô, sem mudanças, em datas posteriores à sua "
            "otimização.",
        ),
    },
    # Only the developer gets this step: before real money, enough demo trades
    # for the live comparison (``live.compare_live``) to be measured at all.
    "next_demo": {
        OWN: _say(
            "Antes de operarla con dinero real, córrela en una cuenta demo hasta tener al menos "
            f"{MIN_LIVE_TRADES} operaciones cerradas y sube ese historial junto al backtest: con "
            "menos, la comparación con el backtest no se puede medir.",
            "Before trading it with real money, run it on a demo account until it has at least "
            f"{MIN_LIVE_TRADES} closed trades and upload that history with the backtest: with "
            "fewer, the comparison with the backtest cannot be measured.",
            "Antes de operá-la com dinheiro real, rode-a em uma conta demo até ter pelo menos "
            f"{MIN_LIVE_TRADES} operações fechadas e envie esse histórico junto com o backtest: "
            "com menos, a comparação com o backtest não pode ser medida.",
        ),
    },
    "next_questions": {
        OWN: _say(
            "Responde con tus archivos las preguntas que deja abiertas este informe: cada una "
            "dice qué la responde.",
            "Answer with your own files the questions this report leaves open: each one says "
            "what answers it.",
            "Responda com os seus arquivos às perguntas que este relatório deixa abertas: cada "
            "uma diz o que a responde.",
        ),
        PROVIDER: _say(
            "Prepara las respuestas a lo que te van a preguntar tus clientes: cada pregunta "
            "dice qué aportar.",
            "Prepare answers to what your clients will ask you: each question says what to "
            "provide.",
            "Prepare as respostas ao que seus clientes vão perguntar a você: cada pergunta diz "
            "o que fornecer.",
        ),
        NEUTRAL: _say(
            "Revisa las preguntas que deja abiertas este informe y lo que responde cada una.",
            "Go through the questions this report leaves open and what answers each one.",
            "Revise as perguntas que este relatório deixa abertas e o que responde cada uma.",
        ),
    },
    "next_keep": {
        OWN: _say(
            "Guarda este informe y su identificador; si cambias el robot, vuelve a auditarlo y "
            "compara los dos informes.",
            "Keep this report and its identifier; if you change the robot, audit it again and "
            "compare the two reports.",
            "Guarde este relatório e seu identificador; se você mudar o robô, audite-o de novo "
            "e compare os dois relatórios.",
        ),
        PROVIDER: _say(
            "Guarda este informe y su identificador; si cambias la configuración, vuelve a "
            "auditarla y comparte el informe nuevo.",
            "Keep this report and its identifier; if you change the settings, audit them again "
            "and share the new report.",
            "Guarde este relatório e seu identificador; se você mudar a configuração, audite-a "
            "de novo e compartilhe o relatório novo.",
        ),
        NEUTRAL: _say(
            "Guarda este informe y su identificador; si el robot cambia, conviene auditarlo de "
            "nuevo.",
            "Keep this report and its identifier; if the robot changes, it is worth auditing "
            "it again.",
            "Guarde este relatório e seu identificador; se o robô mudar, convém auditá-lo de novo.",
        ),
    },
    "next_intro_fund": {
        OWN: _say(
            "Si el fondo es tuyo, esto es lo que conviene resolver primero, según lo que "
            "encontró la auditoría.",
            "If the fund is yours, this is what is worth resolving first, going by what the "
            "audit found.",
            "Se o fundo é seu, isto é o que convém resolver primeiro, segundo o que a auditoria "
            "encontrou.",
        ),
        PROVIDER: _say(
            "Si muestras este fondo a otros, esto es lo primero que te van a preguntar al ver "
            "este informe, según lo que encontró la auditoría.",
            "If you show this fund to others, this is what they will ask you first on seeing "
            "this report, going by what the audit found.",
            "Se você mostra este fundo a outros, isto é o que vão perguntar a você primeiro ao "
            "ver este relatório, segundo o que a auditoria encontrou.",
        ),
        NEUTRAL: _say(
            "Esto es lo que conviene aclarar primero sobre este fondo, según lo que encontró la "
            "auditoría.",
            "This is what is worth clearing up first about this fund, going by what the audit "
            "found.",
            "Isto é o que convém esclarecer primeiro sobre este fundo, segundo o que a "
            "auditoria encontrou.",
        ),
    },
    "next_fund_fees": {
        OWN: _say(
            "Declara si las rentabilidades son netas de todas las comisiones: la tabla de "
            "comisiones muestra cuánto cambiarían si no lo son.",
            "Declare whether the returns are net of all fees: the fee table shows how much they "
            "would change if they are not.",
            "Declare se as rentabilidades são líquidas de todas as taxas: a tabela de taxas "
            "mostra quanto mudariam se não forem.",
        ),
        PROVIDER: _say(
            "Te van a preguntar si las rentabilidades son netas de todas las comisiones: la "
            "tabla de comisiones muestra cuánto cambiarían si no lo son.",
            "You will be asked whether the returns are net of all fees: the fee table shows how "
            "much they would change if they are not.",
            "Vão perguntar a você se as rentabilidades são líquidas de todas as taxas: a tabela "
            "de taxas mostra quanto mudariam se não forem.",
        ),
        NEUTRAL: _say(
            "Conviene aclarar si las rentabilidades son netas de todas las comisiones: la tabla "
            "de comisiones muestra cuánto cambiarían si no lo son.",
            "It is worth clearing up whether the returns are net of all fees: the fee table "
            "shows how much they would change if they are not.",
            "Convém esclarecer se as rentabilidades são líquidas de todas as taxas: a tabela de "
            "taxas mostra quanto mudariam se não forem.",
        ),
    },
    "next_keep_fund": {
        OWN: _say(
            "Guarda este informe y su identificador; si cambias de estrategia, vuelve a auditar "
            "el fondo.",
            "Keep this report and its identifier; if you change strategy, audit the fund again.",
            "Guarde este relatório e seu identificador; se você mudar de estratégia, audite o "
            "fundo de novo.",
        ),
        PROVIDER: _say(
            "Guarda este informe y su identificador; si el fondo cambia de gestor o de "
            "estrategia, vuelve a auditarlo y comparte el informe nuevo.",
            "Keep this report and its identifier; if the fund changes manager or strategy, "
            "audit it again and share the new report.",
            "Guarde este relatório e seu identificador; se o fundo mudar de gestor ou de "
            "estratégia, audite-o de novo e compartilhe o relatório novo.",
        ),
        NEUTRAL: _say(
            "Guarda este informe y su identificador; si el fondo cambia de gestor o de "
            "estrategia, conviene auditarlo de nuevo.",
            "Keep this report and its identifier; if the fund changes manager or strategy, it "
            "is worth auditing it again.",
            "Guarde este relatório e seu identificador; se o fundo mudar de gestor ou de "
            "estratégia, convém auditá-lo de novo.",
        ),
    },
    "questions": {
        OWN: _say(
            "Preguntas que deja abiertas este informe",
            "Questions this report leaves open",
            "Perguntas que este relatório deixa abertas",
        ),
        PROVIDER: _say(
            "Lo que te van a preguntar tus clientes",
            "What your clients will ask you",
            "O que seus clientes vão perguntar a você",
        ),
        NEUTRAL: _say(
            "Preguntas que deja abiertas este informe",
            "Questions this report leaves open",
            "Perguntas que este relatório deixa abertas",
        ),
    },
    # A line under the questions' title; the buyer's list has none.
    "questions_intro": {
        OWN: _say(
            "Lo que tus archivos no responden todavía y, en cada caso, lo que lo respondería.",
            "What your files do not answer yet and, for each, what would answer it.",
            "O que os seus arquivos ainda não respondem e, em cada caso, o que responderia.",
        ),
        PROVIDER: _say(
            "Quien vea este informe va a preguntar esto. En cada pregunta, lo que conviene "
            "aportar para responderla.",
            "Whoever sees this report will ask this. For each question, what to provide to "
            "answer it.",
            "Quem vir este relatório vai perguntar isto. Em cada pergunta, o que convém "
            "fornecer para respondê-la.",
        ),
        NEUTRAL: _say(
            "Lo que el informe deja abierto y, en cada caso, lo que lo respondería.",
            "What the report leaves open and, for each, what would answer it.",
            "O que o relatório deixa em aberto e, em cada caso, o que responderia.",
        ),
    },
    "evidence_legend": {
        OWN: _say(
            "Cada cifra lleva su etiqueta: «Medido» si se calculó de tus archivos; «Declarado» "
            "si lo afirmas tú o tu plataforma, sin verificar; «No medido» si faltó un dato para "
            "calcularla.",
            "Every figure carries its tag: “Measured” when computed from your files; "
            "“Declared” when stated by you or your platform, not verified; “Not measured” when "
            "a piece was missing to compute it.",
            "Cada número leva sua etiqueta: «Medido» quando calculado a partir dos seus "
            "arquivos; «Declarado» quando afirmado por você ou pela sua plataforma, sem "
            "conferência; «Não medido» quando faltou um dado para calculá-lo.",
        ),
        PROVIDER: _say(
            "Cada cifra lleva su etiqueta: «Medido» si se calculó de tus archivos; «Declarado» "
            "si lo afirmas tú o tu plataforma, sin verificar; «No medido» si faltó un dato para "
            "calcularla.",
            "Every figure carries its tag: “Measured” when computed from your files; "
            "“Declared” when stated by you or your platform, not verified; “Not measured” when "
            "a piece was missing to compute it.",
            "Cada número leva sua etiqueta: «Medido» quando calculado a partir dos seus "
            "arquivos; «Declarado» quando afirmado por você ou pela sua plataforma, sem "
            "conferência; «Não medido» quando faltou um dado para calculá-lo.",
        ),
        NEUTRAL: _say(
            "Cada cifra lleva su etiqueta: «Medido» si se calculó de tus archivos; «Declarado» "
            "si se afirmó al subirlos o lo dice la plataforma, sin verificar; «No medido» si "
            "faltó un dato para calcularla.",
            "Every figure carries its tag: “Measured” when computed from your files; "
            "“Declared” when stated at upload or by the platform, not verified; “Not measured” "
            "when a piece was missing to compute it.",
            "Cada número leva sua etiqueta: «Medido» quando calculado a partir dos seus "
            "arquivos; «Declarado» quando afirmado no envio ou pela plataforma, sem "
            "conferência; «Não medido» quando faltou um dado para calculá-lo.",
        ),
    },
    "account_clean_unseen": {
        OWN: _say(
            "No vimos depósitos en plena pérdida ni un porcentaje que se aparte del dinero. El "
            "archivo no dice cuánto perdían las posiciones abiertas: exporta la curva de equity "
            "con flotante y súbela.",
            "We saw no deposit in a deep drawdown and no percentage that departs from the "
            "money. The file does not say how much the open positions were losing: export the "
            "equity curve with floating results and upload it.",
            "Não vimos depósitos em plena perda nem uma porcentagem que se afaste do dinheiro. "
            "O arquivo não diz quanto as posições abertas estavam perdendo: exporte a curva de "
            "patrimônio com o flutuante e envie-a.",
        ),
        PROVIDER: _say(
            "No vimos depósitos en plena pérdida ni un porcentaje que se aparte del dinero. El "
            "archivo no dice cuánto perdían las posiciones abiertas: te van a pedir la curva de "
            "equity con flotante, así que apórtala.",
            "We saw no deposit in a deep drawdown and no percentage that departs from the "
            "money. The file does not say how much the open positions were losing: you will be "
            "asked for the equity curve with floating results, so provide it.",
            "Não vimos depósitos em plena perda nem uma porcentagem que se afaste do dinheiro. "
            "O arquivo não diz quanto as posições abertas estavam perdendo: vão pedir a você a "
            "curva de patrimônio com o flutuante, então forneça-a.",
        ),
        NEUTRAL: _say(
            "No vimos depósitos en plena pérdida ni un porcentaje que se aparte del dinero. El "
            "archivo no dice cuánto perdían las posiciones abiertas: hace falta la curva de "
            "equity con flotante.",
            "We saw no deposit in a deep drawdown and no percentage that departs from the "
            "money. The file does not say how much the open positions were losing: the equity "
            "curve with floating results is needed.",
            "Não vimos depósitos em plena perda nem uma porcentagem que se afaste do dinheiro. "
            "O arquivo não diz quanto as posições abertas estavam perdendo: é preciso a curva "
            "de patrimônio com o flutuante.",
        ),
    },
    "luck_uncounted": {
        OWN: _say(
            "Los archivos no dicen cuántas configuraciones se probaron antes de elegir esta. La "
            "tabla muestra cuánto historial haría falta según cuántas fueran: declara cuántas "
            "probaste o sube el XML de la optimización.",
            "The files do not say how many configurations were tried before this one was "
            "picked. The table shows how much history each search size would need: declare "
            "how many you tried or upload the optimisation XML.",
            "Os arquivos não dizem quantas configurações foram testadas antes de escolher esta. "
            "A tabela mostra quanto histórico seria necessário conforme quantas fossem: "
            "declare quantas você testou ou envie o XML da otimização.",
        ),
        PROVIDER: _say(
            "Los archivos no dicen cuántas configuraciones se probaron antes de elegir esta. La "
            "tabla muestra cuánto historial haría falta según cuántas fueran: te lo van a "
            "preguntar, así que declara cuántas fueron o aporta el XML de la optimización.",
            "The files do not say how many configurations were tried before this one was "
            "picked. The table shows how much history each search size would need: you will be "
            "asked, so declare how many there were or provide the optimisation XML.",
            "Os arquivos não dizem quantas configurações foram testadas antes de escolher esta. "
            "A tabela mostra quanto histórico seria necessário conforme quantas fossem: vão "
            "perguntar isso a você, então declare quantas foram ou forneça o XML da otimização.",
        ),
        NEUTRAL: _say(
            "Los archivos no dicen cuántas configuraciones se probaron antes de elegir esta. La "
            "tabla muestra cuánto historial haría falta según cuántas fueran: el número se "
            "puede declarar al subir el archivo o medir con el XML de la optimización.",
            "The files do not say how many configurations were tried before this one was "
            "picked. The table shows how much history each search size would need: the number "
            "can be declared at upload or measured from the optimisation XML.",
            "Os arquivos não dizem quantas configurações foram testadas antes de escolher esta. "
            "A tabela mostra quanto histórico seria necessário conforme quantas fossem: o "
            "número pode ser declarado no envio ou medido com o XML da otimização.",
        ),
    },
    "crises_worse": {
        OWN: _say(
            "En {worse} de {n} crisis cayó más que su índice. Revisa qué la protege cuando el "
            "mercado cae.",
            "In {worse} of {n} crises it fell more than its benchmark. Check what protects it "
            "when markets fall.",
            "Em {worse} de {n} crises caiu mais que seu índice. Revise o que a protege quando o "
            "mercado cai.",
        ),
        PROVIDER: _say(
            "En {worse} de {n} crisis cayó más que su índice. Te van a preguntar qué la protege "
            "cuando el mercado cae.",
            "In {worse} of {n} crises it fell more than its benchmark. You will be asked what "
            "protects it when markets fall.",
            "Em {worse} de {n} crises caiu mais que seu índice. Vão perguntar a você o que a "
            "protege quando o mercado cai.",
        ),
        NEUTRAL: _say(
            "En {worse} de {n} crisis cayó más que su índice. Conviene aclarar qué la protege "
            "cuando el mercado cae.",
            "In {worse} of {n} crises it fell more than its benchmark. It is worth clearing up "
            "what protects it when markets fall.",
            "Em {worse} de {n} crises caiu mais que seu índice. Convém esclarecer o que a "
            "protege quando o mercado cai.",
        ),
    },
    "live_EDGE": {
        OWN: _say(
            "La cuenta real está en el borde: su resultado neto o su peor caída quedan peor que "
            "en el 95 % de las historias del backtest. Puede ser una mala racha, pero merece "
            "revisar si corre la misma configuración y con qué costos.",
            "The live account is at the edge: its net result or its deepest fall is worse than "
            "in 95 % of the backtest's histories. It may be a bad streak, but it is worth "
            "checking that it runs the same settings, and at what costs.",
            "A conta real está no limite: seu resultado líquido ou sua pior queda ficam piores "
            "que em 95 % das histórias do backtest. Pode ser uma fase ruim, mas vale conferir "
            "se roda a mesma configuração e com quais custos.",
        ),
        PROVIDER: _say(
            "La cuenta real está en el borde: su resultado neto o su peor caída quedan peor que "
            "en el 95 % de las historias del backtest. Puede ser una mala racha, pero te van a "
            "preguntar por ella.",
            "The live account is at the edge: its net result or its deepest fall is worse than "
            "in 95 % of the backtest's histories. It may be a bad streak, but you will be asked "
            "about it.",
            "A conta real está no limite: seu resultado líquido ou sua pior queda ficam piores "
            "que em 95 % das histórias do backtest. Pode ser uma fase ruim, mas vão perguntar a "
            "você sobre ela.",
        ),
        NEUTRAL: _say(
            "La cuenta real está en el borde: su resultado neto o su peor caída quedan peor que "
            "en el 95 % de las historias del backtest. Puede ser una mala racha, pero merece "
            "una explicación.",
            "The live account is at the edge: its net result or its deepest fall is worse than "
            "in 95 % of the backtest's histories. It may be a bad streak, but it deserves an "
            "explanation.",
            "A conta real está no limite: seu resultado líquido ou sua pior queda ficam piores "
            "que em 95 % das histórias do backtest. Pode ser uma fase ruim, mas merece uma "
            "explicação.",
        ),
    },
    "live_pair_low": {
        OWN: _say(
            "Menos de la mitad de las operaciones reales aparecen en el backtest en esas "
            "fechas: probablemente no es la misma configuración. Sube el backtest de la "
            "configuración exacta que corre esa cuenta.",
            "Fewer than half the live trades appear in the backtest on those dates: it is "
            "probably not the same configuration. Upload the backtest of the exact settings "
            "that account runs.",
            "Menos da metade das operações reais aparece no backtest nessas datas: "
            "provavelmente não é a mesma configuração. Envie o backtest da configuração exata "
            "que essa conta roda.",
        ),
        PROVIDER: _say(
            "Menos de la mitad de las operaciones reales aparecen en el backtest en esas "
            "fechas: probablemente no es la misma configuración. Te van a pedir el backtest "
            "exacto de esa cuenta: apórtalo.",
            "Fewer than half the live trades appear in the backtest on those dates: it is "
            "probably not the same configuration. You will be asked for that account's exact "
            "backtest: provide it.",
            "Menos da metade das operações reais aparece no backtest nessas datas: "
            "provavelmente não é a mesma configuração. Vão pedir a você o backtest exato dessa "
            "conta: forneça-o.",
        ),
        NEUTRAL: _say(
            "Menos de la mitad de las operaciones reales aparecen en el backtest en esas "
            "fechas: probablemente no es la misma configuración. Hace falta el backtest exacto "
            "de esa cuenta.",
            "Fewer than half the live trades appear in the backtest on those dates: it is "
            "probably not the same configuration. That account's exact backtest is needed.",
            "Menos da metade das operações reais aparece no backtest nessas datas: "
            "provavelmente não é a mesma configuração. É preciso o backtest exato dessa conta.",
        ),
    },
}

#: ``report.LOCKED_GAINS`` keys in the voices that differ from the buyer's.
LOCKED_GAINS: dict[str, dict[str, dict[str, str]]] = {
    "questions": {
        OWN: _say(
            "Qué preguntas deja abiertas y qué responde cada una",
            "Which questions it leaves open and what answers each one",
            "Que perguntas deixa abertas e o que responde cada uma",
        ),
        PROVIDER: _say(
            "Qué te van a preguntar tus clientes y qué aportar",
            "What your clients will ask you and what to provide",
            "O que seus clientes vão perguntar a você e o que fornecer",
        ),
        NEUTRAL: _say(
            "Qué preguntas deja abiertas y qué responde cada una",
            "Which questions it leaves open and what answers each one",
            "Que perguntas deixa abertas e o que responde cada uma",
        ),
    },
}


class Voiced(dict[str, str]):
    """One language's report labels in a declared voice; the language and the
    voice travel with the table, so helpers that receive only the labels
    still know both."""

    def __init__(self, base: Mapping[str, str], locale: str, role: str) -> None:
        super().__init__(base)
        self.locale = locale
        self.role = role


def labels_for(base: dict[str, str], locale: str, role: str) -> dict[str, str]:
    """``base`` (``report.LABELS[locale]``) in ``role``'s voice.

    The buyer's voice is ``base`` itself, unchanged."""
    if role == BUYER:
        return base
    out = Voiced(base, locale, role)
    for key, voices in LABELS.items():
        text = voices.get(role, {}).get(locale)
        if text is not None:
            out[key] = text
    return out


def gains_for(gains: Mapping[str, str], labels: Mapping[str, str]) -> dict[str, str]:
    """``report.LOCKED_GAINS[locale]`` in the voice ``labels`` carry."""
    role = getattr(labels, "role", BUYER)
    locale = getattr(labels, "locale", "")
    out = dict(gains)
    if role == BUYER:
        return out
    for key, voices in LOCKED_GAINS.items():
        text = voices.get(role, {}).get(locale)
        if text is not None:
            out[key] = text
    return out


#: ``verdict.MEANING`` texts that send the reader to a provider or manager.
MEANING: dict[str, dict[str, dict[str, str]]] = {
    "out_of_sample.NOT_MEASURED.account": {
        OWN: _say(
            "El historial no dice desde cuándo el robot opera sin cambios, así que no se sabe "
            "qué parte es prueba sobre datos nuevos. Declara la fecha desde la que no cambiaste "
            "la configuración para medirlo.",
            "The history does not say since when the robot has run unchanged, so it is not "
            "known which part is a test on unseen data. Declare the date since which you have "
            "not changed the settings to measure it.",
            "O histórico não diz desde quando o robô opera sem alterações, então não se sabe "
            "qual parte é teste sobre dados novos. Declare a data desde a qual você não mudou a "
            "configuração para medi-lo.",
        ),
        PROVIDER: _say(
            "El historial no dice desde cuándo el robot opera sin cambios, así que no se sabe "
            "qué parte es prueba sobre datos nuevos. Te van a preguntar esa fecha: declárala "
            "para medirlo.",
            "The history does not say since when the robot has run unchanged, so it is not "
            "known which part is a test on unseen data. You will be asked for that date: "
            "declare it to measure it.",
            "O histórico não diz desde quando o robô opera sem alterações, então não se sabe "
            "qual parte é teste sobre dados novos. Vão perguntar essa data a você: declare-a "
            "para medi-lo.",
        ),
        NEUTRAL: _say(
            "El historial no dice desde cuándo el robot opera sin cambios, así que no se sabe "
            "qué parte es prueba sobre datos nuevos. Declarar esa fecha permite medirlo.",
            "The history does not say since when the robot has run unchanged, so it is not "
            "known which part is a test on unseen data. Declaring that date lets it be "
            "measured.",
            "O histórico não diz desde quando o robô opera sem alterações, então não se sabe "
            "qual parte é teste sobre dados novos. Declarar essa data permite medi-lo.",
        ),
    },
    "out_of_sample.NOT_MEASURED.fund": {
        OWN: _say(
            "El historial mensual de un fondo es su historial real, pero no dice desde cuándo "
            "se aplica el mismo proceso ni si algún tramo es simulado. Declara esa fecha para "
            "medirlo.",
            "A fund's monthly record is its real history, but it does not say since when the "
            "same process has applied, or whether any stretch is simulated. Declare that date "
            "to measure it.",
            "O histórico mensal de um fundo é o seu histórico real, mas não diz desde quando se "
            "aplica o mesmo processo nem se algum trecho é simulado. Declare essa data para "
            "medi-lo.",
        ),
        PROVIDER: _say(
            "El historial mensual de un fondo es su historial real, pero no dice desde cuándo "
            "el gestor aplica el mismo proceso ni si algún tramo es simulado. Te van a "
            "preguntar esa fecha: declárala para medirlo.",
            "A fund's monthly record is its real history, but it does not say since when the "
            "manager has applied the same process, or whether any stretch is simulated. You "
            "will be asked for that date: declare it to measure it.",
            "O histórico mensal de um fundo é o seu histórico real, mas não diz desde quando o "
            "gestor aplica o mesmo processo nem se algum trecho é simulado. Vão perguntar essa "
            "data a você: declare-a para medi-lo.",
        ),
        NEUTRAL: _say(
            "El historial mensual de un fondo es su historial real, pero no dice desde cuándo "
            "el gestor aplica el mismo proceso ni si algún tramo es simulado. Declarar esa "
            "fecha permite medirlo.",
            "A fund's monthly record is its real history, but it does not say since when the "
            "manager has applied the same process, or whether any stretch is simulated. "
            "Declaring that date lets it be measured.",
            "O histórico mensal de um fundo é o seu histórico real, mas não diz desde quando o "
            "gestor aplica o mesmo processo nem se algum trecho é simulado. Declarar essa data "
            "permite medi-lo.",
        ),
    },
}


def meaning(
    name: str, status: str, locale: str, role: str, *, account: bool = False, fund: bool = False
) -> str | None:
    """A dimension's plain-language meaning in ``role``'s voice, or None to keep
    ``verdict.meaning`` (the buyer's, and every text that names nobody)."""
    if role == BUYER:
        return None
    suffix = ".fund" if fund else ".account" if account else ""
    return MEANING.get(f"{name}.{status}{suffix}", {}).get(role, {}).get(locale)


#: Plan texts (``plan.py``) in the voices that differ from the buyer's: the
#: actions that send the reader to a provider or manager, the flag hints that
#: ask someone for a file, and three step titles.
PLAN: dict[str, dict[str, dict[str, str]]] = {
    "account_oos_declare": {
        OWN: _say(
            "Declara como inicio fuera de muestra la fecha desde la que no cambiaste la "
            "configuración: lo posterior se mide como datos nuevos.",
            "Declare the date since which you have not changed the settings as the "
            "out-of-sample start: what follows is measured as unseen data.",
            "Declare como início fora da amostra a data desde a qual você não mudou a "
            "configuração: o que vem depois é medido como dados novos.",
        ),
        PROVIDER: _say(
            "Te van a preguntar desde qué fecha no cambió la configuración: decláralo como "
            "inicio fuera de muestra y lo posterior se mide como datos nuevos.",
            "You will be asked since when the settings have not changed: declare that date as "
            "the out-of-sample start and what follows is measured as unseen data.",
            "Vão perguntar a você desde que data a configuração não mudou: declare-a como "
            "início fora da amostra e o que vem depois é medido como dados novos.",
        ),
        NEUTRAL: _say(
            "Declara como inicio fuera de muestra la fecha desde la que no cambió la "
            "configuración: lo posterior se mide como datos nuevos.",
            "Declare the date since which the settings have not changed as the out-of-sample "
            "start: what follows is measured as unseen data.",
            "Declare como início fora da amostra a data desde a qual a configuração não mudou: "
            "o que vem depois é medido como dados novos.",
        ),
    },
    "account_oos_backtest": {
        OWN: _say(
            "Sube el backtest del mismo robot junto a la cuenta: el informe compara los dos "
            "operación por operación.",
            "Upload the backtest of the same robot with the account: the report compares the "
            "two trade by trade.",
            "Envie o backtest do mesmo robô junto com a conta: o relatório compara os dois "
            "operação por operação.",
        ),
        PROVIDER: _say(
            "Te van a pedir el backtest del mismo robot: súbelo junto a la cuenta y el informe "
            "compara los dos operación por operación.",
            "You will be asked for the backtest of the same robot: upload it with the account "
            "and the report compares the two trade by trade.",
            "Vão pedir a você o backtest do mesmo robô: envie-o junto com a conta e o relatório "
            "compara os dois operação por operação.",
        ),
        NEUTRAL: _say(
            "Sube el backtest del mismo robot junto a la cuenta: el informe compara los dos "
            "operación por operación.",
            "Upload the backtest of the same robot with the account: the report compares the "
            "two trade by trade.",
            "Envie o backtest do mesmo robô junto com a conta: o relatório compara os dois "
            "operação por operação.",
        ),
    },
    "fund_history": {
        OWN: _say(
            "Sube el historial completo del fondo desde su inicio, sin años recortados.",
            "Upload the fund's full record since inception, with no years left out.",
            "Envie o histórico completo do fundo desde o início, sem anos cortados.",
        ),
        PROVIDER: _say(
            "Te van a pedir el historial completo del fondo desde su inicio, sin años "
            "recortados: apórtalo.",
            "You will be asked for the fund's full record since inception, with no years left "
            "out: provide it.",
            "Vão pedir a você o histórico completo do fundo desde o início, sem anos cortados: "
            "forneça-o.",
        ),
        NEUTRAL: _say(
            "Hace falta el historial completo del fondo desde su inicio, sin años recortados.",
            "The fund's full record since inception, with no years left out, is needed.",
            "É preciso o histórico completo do fundo desde o início, sem anos cortados.",
        ),
    },
    "fund_trials_undeclared": {
        OWN: _say(
            "Declara cuántos fondos o estrategias llevas o has cerrado (aunque sea 1) al subir "
            "el historial: Rigor lo descuenta.",
            "Declare how many funds or strategies you run or have closed (even if it is 1) "
            "when you upload the record: Rigor discounts it.",
            "Declare quantos fundos ou estratégias você administra ou já encerrou (mesmo que "
            "seja 1) ao enviar o histórico: o Rigor o desconta.",
        ),
        PROVIDER: _say(
            "Te van a preguntar cuántos fondos o estrategias llevas o has cerrado: decláralo "
            "(aunque sea 1) al subir el historial y Rigor lo descuenta.",
            "You will be asked how many funds or strategies you run or have closed: declare it "
            "(even if it is 1) when you upload the record and Rigor discounts it.",
            "Vão perguntar a você quantos fundos ou estratégias administra ou já encerrou: "
            "declare esse número (mesmo que seja 1) ao enviar o histórico e o Rigor o desconta.",
        ),
        NEUTRAL: _say(
            "Declara cuántos fondos o estrategias lleva o ha cerrado el gestor (aunque sea 1) "
            "al subir el historial: Rigor lo descuenta.",
            "Declare how many funds or strategies the manager runs or has closed (even if it "
            "is 1) when you upload the record: Rigor discounts it.",
            "Declare quantos fundos ou estratégias o gestor administra ou já encerrou (mesmo "
            "que seja 1) ao enviar o histórico: o Rigor o desconta.",
        ),
    },
    "fund_trials": {
        OWN: _say(
            "Declara como número de intentos cuántos fondos o estrategias llevas o has "
            "cerrado: un buen historial entre muchos pesa menos.",
            "Declare how many funds or strategies you run or have closed as the number of "
            "trials: one good record among many weighs less.",
            "Declare como número de tentativas quantos fundos ou estratégias você administra "
            "ou já encerrou: um bom histórico entre muitos pesa menos.",
        ),
        PROVIDER: _say(
            "Te van a preguntar cuántos fondos o estrategias llevas o has cerrado: decláralo "
            "como número de intentos, porque un buen historial entre muchos pesa menos.",
            "You will be asked how many funds or strategies you run or have closed: declare it "
            "as the number of trials, since one good record among many weighs less.",
            "Vão perguntar a você quantos fundos ou estratégias administra ou já encerrou: "
            "declare isso como número de tentativas, porque um bom histórico entre muitos pesa "
            "menos.",
        ),
        NEUTRAL: _say(
            "Declara como número de intentos cuántos fondos o estrategias lleva o ha cerrado "
            "el gestor: un buen historial entre muchos pesa menos.",
            "Declare how many funds or strategies the manager runs or has closed as the number "
            "of trials: one good record among many weighs less.",
            "Declare como número de tentativas quantos fundos ou estratégias o gestor "
            "administra ou já encerrou: um bom histórico entre muitos pesa menos.",
        ),
    },
    "fund_oos": {
        OWN: _say(
            "Declara como inicio fuera de muestra la fecha desde la que no cambió tu proceso de "
            "inversión, y aclara si algún tramo es simulado (pro forma): lo posterior se mide "
            "como datos nuevos.",
            "Declare the date since which your investment process has not changed as the "
            "out-of-sample start, and say whether any stretch is simulated (pro forma): what "
            "follows is measured as unseen data.",
            "Declare como início fora da amostra a data desde a qual o seu processo de "
            "investimento não mudou, e esclareça se algum trecho é simulado (pro forma): o que "
            "vem depois é medido como dados novos.",
        ),
        PROVIDER: _say(
            "Te van a preguntar desde qué fecha no cambió el proceso de inversión y si algún "
            "tramo es simulado (pro forma): declara esa fecha como inicio fuera de muestra y lo "
            "posterior se mide como datos nuevos.",
            "You will be asked since when the investment process has not changed and whether "
            "any stretch is simulated (pro forma): declare that date as the out-of-sample "
            "start and what follows is measured as unseen data.",
            "Vão perguntar a você desde que data o processo de investimento não mudou e se "
            "algum trecho é simulado (pro forma): declare essa data como início fora da amostra "
            "e o que vem depois é medido como dados novos.",
        ),
        NEUTRAL: _say(
            "Declara como inicio fuera de muestra la fecha desde la que no cambió el proceso de "
            "inversión, y aclara si algún tramo es simulado (pro forma): lo posterior se mide "
            "como datos nuevos.",
            "Declare the date since which the investment process has not changed as the "
            "out-of-sample start, and say whether any stretch is simulated (pro forma): what "
            "follows is measured as unseen data.",
            "Declare como início fora da amostra a data desde a qual o processo de "
            "investimento não mudou, e esclareça se algum trecho é simulado (pro forma): o que "
            "vem depois é medido como dados novos.",
        ),
    },
    "fund_costs": {
        OWN: _say(
            "Declara si las cifras son netas de las comisiones de gestión y de éxito: el "
            "informe muestra cuánto pesan las comisiones.",
            "Declare whether the figures are net of the management and performance fees: the "
            "report shows how much the fees weigh.",
            "Declare se os números são líquidos das taxas de administração e de performance: o "
            "relatório mostra quanto pesam as taxas.",
        ),
        PROVIDER: _say(
            "Te van a preguntar si las cifras son netas de las comisiones de gestión y de "
            "éxito: decláralo y el informe muestra cuánto pesan las comisiones.",
            "You will be asked whether the figures are net of the management and performance "
            "fees: declare it and the report shows how much the fees weigh.",
            "Vão perguntar a você se os números são líquidos das taxas de administração e de "
            "performance: declare isso e o relatório mostra quanto pesam as taxas.",
        ),
        NEUTRAL: _say(
            "Declara si las cifras son netas de las comisiones de gestión y de éxito: el "
            "informe muestra cuánto pesan las comisiones.",
            "Declare whether the figures are net of the management and performance fees: the "
            "report shows how much the fees weigh.",
            "Declare se os números são líquidos das taxas de administração e de performance: o "
            "relatório mostra quanto pesam as taxas.",
        ),
    },
    "flag_PROFIT_CONCENTRATION": {
        OWN: _say(
            "Revisa la mejor operación en el archivo (fecha, tamaño, precio) y sube más "
            "historial: con el resultado en una sola operación, el resto del sistema no está "
            "medido.",
            "Check the best trade in the file (date, size, price) and upload more history: "
            "with the result in one trade, the rest of the system is not measured.",
            "Revise a melhor operação no arquivo (data, tamanho, preço) e envie mais "
            "histórico: com o resultado em uma única operação, o resto do sistema não está "
            "medido.",
        ),
        PROVIDER: _say(
            "Te van a preguntar por la mejor operación (fecha, tamaño, precio): aporta más "
            "historial, porque con el resultado en una sola operación el resto del sistema no "
            "está medido.",
            "You will be asked about the best trade (date, size, price): provide more history, "
            "since with the result in one trade the rest of the system is not measured.",
            "Vão perguntar a você sobre a melhor operação (data, tamanho, preço): forneça mais "
            "histórico, porque com o resultado em uma única operação o resto do sistema não "
            "está medido.",
        ),
        NEUTRAL: _say(
            "Revisa la mejor operación en el archivo (fecha, tamaño, precio): con el resultado "
            "en una sola operación, el resto del sistema no está medido hasta que haya más "
            "historial.",
            "Check the best trade in the file (date, size, price): with the result in one "
            "trade, the rest of the system is not measured until there is more history.",
            "Revise a melhor operação no arquivo (data, tamanho, preço): com o resultado em uma "
            "única operação, o resto do sistema não está medido até haver mais histórico.",
        ),
    },
    "flag_MONETARY_RECONCILIATION_MISMATCH": {
        OWN: _say(
            "Exporta de nuevo el original del mismo periodo y compara saldo inicial, depósitos, "
            "retiros, resultado neto y saldo final; aclara divisa y posiciones abiertas.",
            "Export the original for the same period again and compare starting balance, "
            "deposits, withdrawals, net P&L and ending balance; clarify currency and open "
            "positions.",
            "Exporte de novo o original do mesmo período e compare saldo inicial, depósitos, "
            "saques, resultado líquido e saldo final; esclareça moeda e posições abertas.",
        ),
        PROVIDER: _say(
            "Te van a pedir una exportación original del mismo periodo: compara antes saldo "
            "inicial, depósitos, retiros, resultado neto y saldo final, y aclara divisa y "
            "posiciones abiertas.",
            "You will be asked for an original export of the same period: compare starting "
            "balance, deposits, withdrawals, net P&L and ending balance first, and clarify "
            "currency and open positions.",
            "Vão pedir a você uma exportação original do mesmo período: compare antes saldo "
            "inicial, depósitos, saques, resultado líquido e saldo final, e esclareça moeda e "
            "posições abertas.",
        ),
        NEUTRAL: _say(
            "Hace falta una exportación original del mismo periodo para comparar saldo "
            "inicial, depósitos, retiros, resultado neto y saldo final, y aclarar divisa y "
            "posiciones abiertas.",
            "An original export of the same period is needed to compare starting balance, "
            "deposits, withdrawals, net P&L and ending balance, and to clarify currency and "
            "open positions.",
            "É preciso uma exportação original do mesmo período para comparar saldo inicial, "
            "depósitos, saques, resultado líquido e saldo final, e esclarecer moeda e posições "
            "abertas.",
        ),
    },
    "flag_DEPOSIT_DURING_DRAWDOWN": {
        OWN: _say(
            "Hubo dinero nuevo en plena pérdida: mira el drawdown sin esos depósitos, que es el "
            "riesgo que corrió el sistema por sí solo.",
            "New money arrived in a deep loss: look at the drawdown without those deposits, "
            "which is the risk the system ran on its own.",
            "Entrou dinheiro novo em plena perda: veja o drawdown sem esses depósitos, que é o "
            "risco que o sistema correu sozinho.",
        ),
        PROVIDER: _say(
            "Hubo dinero nuevo en plena pérdida: te van a preguntar por qué se añadió y van a "
            "mirar el drawdown sin esos depósitos.",
            "New money arrived in a deep loss: you will be asked why it was added, and the "
            "drawdown without those deposits will be looked at.",
            "Entrou dinheiro novo em plena perda: vão perguntar a você por que foi adicionado e "
            "vão olhar o drawdown sem esses depósitos.",
        ),
        NEUTRAL: _say(
            "Hubo dinero nuevo en plena pérdida: mira el drawdown sin esos depósitos, que es el "
            "riesgo que corrió el sistema por sí solo.",
            "New money arrived in a deep loss: look at the drawdown without those deposits, "
            "which is the risk the system ran on its own.",
            "Entrou dinheiro novo em plena perda: veja o drawdown sem esses depósitos, que é o "
            "risco que o sistema correu sozinho.",
        ),
    },
    "flag_FLOATING_LOSS_AT_END": {
        OWN: _say(
            "Hay posiciones abiertas con pérdida: vuelve a subir el historial después de que se "
            "cierren para ver el resultado real.",
            "Positions are open at a loss: upload the history again after they close to see "
            "the real result.",
            "Há posições abertas com perda: envie o histórico de novo depois que forem fechadas "
            "para ver o resultado real.",
        ),
        PROVIDER: _say(
            "Hay posiciones abiertas con pérdida: te van a pedir un historial impreso después "
            "de que se cierren, que muestra el resultado real.",
            "Positions are open at a loss: you will be asked for a history printed after they "
            "close, which shows the real result.",
            "Há posições abertas com perda: vão pedir a você um histórico impresso depois que "
            "forem fechadas, que mostra o resultado real.",
        ),
        NEUTRAL: _say(
            "Hay posiciones abiertas con pérdida: un historial impreso después de que se "
            "cierren muestra el resultado real.",
            "Positions are open at a loss: a history printed after they close shows the real "
            "result.",
            "Há posições abertas com perda: um histórico impresso depois que forem fechadas "
            "mostra o resultado real.",
        ),
    },
    "flag_COARSE_TICK_MODEL": {
        OWN: _say(
            "Repite el backtest con cada tick (o ticks reales en MT5) y súbelo; solo los "
            "robots que operan al abrir la vela se pueden juzgar con precios de apertura.",
            "Run the backtest again on every tick (or real ticks in MT5) and upload it; only "
            "robots that trade at the bar's open can be judged on open prices.",
            "Repita o backtest com cada tick (ou ticks reais no MT5) e envie-o; só os robôs "
            "que operam na abertura do candle podem ser julgados com preços de abertura.",
        ),
        PROVIDER: _say(
            "Te van a pedir el mismo backtest con cada tick (o ticks reales en MT5): apórtalo; "
            "solo los robots que operan al abrir la vela se pueden juzgar con precios de "
            "apertura.",
            "You will be asked for the same backtest on every tick (or real ticks in MT5): "
            "provide it; only robots that trade at the bar's open can be judged on open prices.",
            "Vão pedir a você o mesmo backtest com cada tick (ou ticks reais no MT5): "
            "forneça-o; só os robôs que operam na abertura do candle podem ser julgados com "
            "preços de abertura.",
        ),
        NEUTRAL: _say(
            "Hace falta el mismo backtest con cada tick (o ticks reales en MT5); solo los "
            "robots que operan al abrir la vela se pueden juzgar con precios de apertura.",
            "The same backtest on every tick (or real ticks in MT5) is needed; only robots "
            "that trade at the bar's open can be judged on open prices.",
            "É preciso o mesmo backtest com cada tick (ou ticks reais no MT5); só os robôs que "
            "operam na abertura do candle podem ser julgados com preços de abertura.",
        ),
    },
    "flag_TEST_DATA_QUALITY_LOW": {
        OWN: _say(
            "Repite el backtest con un historial completo, idealmente con ticks reales, y "
            "compara el resultado.",
            "Rerun the backtest on a complete history, ideally real ticks, and compare the result.",
            "Repita o backtest com um histórico completo, de preferência com ticks reais, e "
            "compare o resultado.",
        ),
        PROVIDER: _say(
            "Te van a pedir el backtest repetido con un historial completo, idealmente con "
            "ticks reales: apórtalo junto al de ahora.",
            "You will be asked for the backtest rerun on a complete history, ideally real "
            "ticks: provide it next to this one.",
            "Vão pedir a você o backtest repetido com um histórico completo, de preferência com "
            "ticks reais: forneça-o junto com o atual.",
        ),
        NEUTRAL: _say(
            "Hace falta el backtest repetido con un historial completo, idealmente con ticks "
            "reales, para comparar el resultado.",
            "The backtest rerun on a complete history, ideally real ticks, is needed to "
            "compare the result.",
            "É preciso o backtest repetido com um histórico completo, de preferência com ticks "
            "reais, para comparar o resultado.",
        ),
    },
    "flag_EDGE_FADING": {
        OWN: _say(
            "Las operaciones recientes dejan de sumar: revisa qué cambió (mercado, bróker, "
            "ajustes) y juzga el sistema por su último tramo, no por el total.",
            "The recent trades stop adding up: check what changed (market, broker, settings) "
            "and judge the system on its last stretch, not on the total.",
            "As operações recentes deixam de somar: revise o que mudou (mercado, corretora, "
            "ajustes) e julgue o sistema pelo seu último trecho, não pelo total.",
        ),
        PROVIDER: _say(
            "Las operaciones recientes dejan de sumar: te van a preguntar qué cambió (mercado, "
            "bróker, ajustes) y van a juzgar el sistema por su último tramo, no por el total.",
            "The recent trades stop adding up: you will be asked what changed (market, broker, "
            "settings), and the system will be judged on its last stretch, not on the total.",
            "As operações recentes deixam de somar: vão perguntar a você o que mudou (mercado, "
            "corretora, ajustes) e vão julgar o sistema pelo seu último trecho, não pelo total.",
        ),
        NEUTRAL: _say(
            "Las operaciones recientes dejan de sumar: conviene aclarar qué cambió (mercado, "
            "bróker, ajustes) y juzgar el sistema por su último tramo, no por el total.",
            "The recent trades stop adding up: it is worth clearing up what changed (market, "
            "broker, settings) and judging the system on its last stretch, not on the total.",
            "As operações recentes deixam de somar: convém esclarecer o que mudou (mercado, "
            "corretora, ajustes) e julgar o sistema pelo seu último trecho, não pelo total.",
        ),
    },
    "flag_REPORT_HEADER_MISMATCH": {
        OWN: _say(
            "Vuelve a exportar el archivo original desde MetaTrader, no una captura, y súbelo "
            "tal cual.",
            "Export the original file from MetaTrader again, not a screenshot, and upload it "
            "as it is.",
            "Exporte de novo o arquivo original do MetaTrader, não uma captura de tela, e "
            "envie-o como está.",
        ),
        PROVIDER: _say(
            "Te van a pedir el archivo original que exporta MetaTrader, no una captura: "
            "apórtalo tal cual.",
            "You will be asked for the original file MetaTrader exports, not a screenshot: "
            "provide it as it is.",
            "Vão pedir a você o arquivo original que o MetaTrader exporta, não uma captura de "
            "tela: forneça-o como está.",
        ),
        NEUTRAL: _say(
            "Hace falta el archivo original que exporta MetaTrader, no una captura, subido tal "
            "cual.",
            "The original file MetaTrader exports, not a screenshot, is needed, uploaded as it is.",
            "É preciso o arquivo original que o MetaTrader exporta, não uma captura de tela, "
            "enviado como está.",
        ),
    },
    "title_account_out_of_sample": {
        OWN: _say(
            "Declara desde cuándo opera sin cambios",
            "Declare since when it has run unchanged",
            "Declare desde quando opera sem alterações",
        ),
        PROVIDER: _say(
            "Declara desde cuándo opera sin cambios",
            "Declare since when it has run unchanged",
            "Declare desde quando opera sem alterações",
        ),
    },
    "title_fund_out_of_sample": {
        OWN: _say(
            "Declara desde cuándo no cambias de proceso",
            "Declare since when your process is unchanged",
            "Declare desde quando o seu processo não muda",
        ),
        PROVIDER: _say(
            "Declara desde cuándo no cambias de proceso",
            "Declare since when your process is unchanged",
            "Declare desde quando o seu processo não muda",
        ),
    },
    "title_fund_multiplicity": {
        OWN: _say(
            "Declara cuántos fondos llevas",
            "Declare how many funds you run",
            "Declare quantos fundos você administra",
        ),
        PROVIDER: _say(
            "Declara cuántos fondos llevas",
            "Declare how many funds you run",
            "Declare quantos fundos você administra",
        ),
        NEUTRAL: _say(
            "Declara cuántos fondos lleva el gestor",
            "Declare how many funds the manager runs",
            "Declare quantos fundos o gestor administra",
        ),
    },
}


def plan_text(key: str, locale: str, role: str) -> str | None:
    """A plan text in ``role``'s voice, or None to keep the buyer's."""
    if role == BUYER:
        return None
    return PLAN.get(key, {}).get(role, {}).get(locale)


#: Each question of ``analytics.vendor_questions`` for a reader who is not the
#: buyer: the question in words that ask nobody in particular (None keeps the
#: stored one, already a plain question) and what answers it.
QUESTIONS: dict[str, dict[str, tuple[str | None, str]]] = {
    "fund_net": {
        "es": (
            None,
            "la ficha o el folleto del fondo, con sus comisiones y su clase de participación",
        ),
        "en": (None, "the fund's factsheet or prospectus, with its fees and share class"),
        "pt": (None, "a lâmina ou o prospecto do fundo, com suas taxas e sua classe de cotas"),
    },
    "fund_same_record": {
        "es": (
            None,
            "el historial del fondo desde su inicio, con los tramos simulados o de otro "
            "vehículo marcados",
        ),
        "en": (
            None,
            "the fund's record since inception, with any simulated or other-vehicle stretch marked",
        ),
        "pt": (
            None,
            "o histórico do fundo desde o início, com os trechos simulados ou de outro veículo "
            "marcados",
        ),
    },
    "fund_other": {
        "es": (
            "¿El gestor lleva otros fondos o cuentas con la misma estrategia, también cerrados?",
            "los historiales de los demás fondos o cuentas con la misma estrategia, también los "
            "cerrados",
        ),
        "en": (
            "Does the manager run other funds or accounts with the same strategy, closed ones "
            "included?",
            "the records of the other funds or accounts with the same strategy, closed ones "
            "included",
        ),
        "pt": (
            "O gestor administra outros fundos ou contas com a mesma estratégia, incluindo os "
            "encerrados?",
            "os históricos dos outros fundos ou contas com a mesma estratégia, incluindo os "
            "encerrados",
        ),
    },
    "fund_admin": {
        "es": (
            "¿Quién calcula el valor liquidativo y quién audita las cuentas del fondo?",
            "los nombres del administrador y del auditor independientes del fondo",
        ),
        "en": (
            "Who calculates the net asset value and who audits the fund's accounts?",
            "the names of the fund's independent administrator and auditor",
        ),
        "pt": (
            "Quem calcula o valor da cota e quem audita as contas do fundo?",
            "os nomes do administrador e do auditor independentes do fundo",
        ),
    },
    "other_accounts": {
        "es": (
            "¿Es la única cuenta con esta estrategia, contando las que se cerraron o se "
            "reiniciaron?",
            "los historiales de las demás cuentas con esta estrategia, también las cerradas o "
            "reiniciadas",
        ),
        "en": (
            "Is this the only account running this strategy, counting the ones closed or "
            "restarted?",
            "the histories of the other accounts running this strategy, closed or restarted "
            "ones included",
        ),
        "pt": (
            "Esta é a única conta com esta estratégia, contando as que foram encerradas ou "
            "reiniciadas?",
            "os históricos das outras contas com esta estratégia, incluindo as encerradas ou "
            "reiniciadas",
        ),
    },
    "backtest_match": {
        "es": (
            "¿Se parece esta cuenta al backtest del mismo robot con la misma configuración?",
            "el informe HTML del probador con la misma configuración, subido junto a esta "
            "cuenta: el informe compara los dos operación por operación",
        ),
        "en": (
            "Does this account look like the backtest of the same robot with the same settings?",
            "the tester's HTML report with the same settings, uploaded together with this "
            "account: the report compares the two trade by trade",
        ),
        "pt": (
            "Esta conta se parece com o backtest do mesmo robô com a mesma configuração?",
            "o relatório HTML do testador com a mesma configuração, enviado junto com esta "
            "conta: o relatório compara os dois operação por operação",
        ),
    },
    "live_record": {
        "es": (
            None,
            "el historial de esa cuenta real o demo exportado desde la plataforma, subido junto "
            "al backtest",
        ),
        "en": (
            None,
            "that live or demo account's history exported from the platform, uploaded together "
            "with the backtest",
        ),
        "pt": (
            None,
            "o histórico dessa conta real ou demo exportado da plataforma, enviado junto com o "
            "backtest",
        ),
    },
    "modelling": {
        "es": (
            None,
            "el informe HTML del probador, que trae el modo de modelado y la calidad de históricos",
        ),
        "en": (
            None,
            "the tester's HTML report, which states the modelling mode and history quality",
        ),
        "pt": (
            None,
            "o relatório HTML do testador, que traz o modo de modelagem e a qualidade do histórico",
        ),
    },
    "best_trade": {
        "es": (None, "la lista completa de operaciones cerradas, con fecha, tamaño y precio"),
        "en": (None, "the full list of closed trades, with date, size and price"),
        "pt": (None, "a lista completa de operações fechadas, com data, tamanho e preço"),
    },
    "recent_period": {
        "es": (
            None,
            "un informe del mismo robot en ese último tramo y la fecha de su última reoptimización",
        ),
        "en": (
            None,
            "a report of the same robot over that last stretch and the date of its last "
            "reoptimisation",
        ),
        "pt": (
            None,
            "um relatório do mesmo robô nesse último trecho e a data da sua última reotimização",
        ),
    },
    "recent_weaker": {
        "es": (
            None,
            "la fecha de cualquier cambio del sistema en ese tiempo, declarada como inicio "
            "fuera de muestra",
        ),
        "en": (
            None,
            "the date of any change to the system over that time, declared as the "
            "out-of-sample start",
        ),
        "pt": (
            None,
            "a data de qualquer mudança no sistema nesse período, declarada como início fora "
            "da amostra",
        ),
    },
    "one_instrument": {
        "es": (None, "un backtest de la misma configuración en los demás instrumentos"),
        "en": (None, "a backtest of the same settings on the other instruments"),
        "pt": (None, "um backtest da mesma configuração nos demais instrumentos"),
    },
    "exit_losses": {
        "es": (
            None,
            "la lista de operaciones con hora de entrada y de salida, y la regla con la que el "
            "sistema cierra una pérdida",
        ),
        "en": (
            None,
            "the list of trades with entry and exit times, and the rule the system closes a "
            "loss with",
        ),
        "pt": (
            None,
            "a lista de operações com hora de entrada e de saída, e a regra com que o sistema "
            "fecha uma perda",
        ),
    },
    "after_losses": {
        "es": (None, "la lista de operaciones con tamaños y horas de entrada"),
        "en": (None, "the list of trades with sizes and entry times"),
        "pt": (None, "a lista de operações com tamanhos e horas de entrada"),
    },
    "original_file": {
        "es": (
            "¿Es este el archivo original que exportó MetaTrader, sin editar, con el encabezado "
            "y la lista completa de operaciones?",
            "el archivo original que exportó MetaTrader, sin editar",
        ),
        "en": (
            "Is this the original file MetaTrader exported, unedited, with the header and the "
            "full list of trades?",
            "the original file MetaTrader exported, unedited",
        ),
        "pt": (
            "Este é o arquivo original que o MetaTrader exportou, sem edição, com o cabeçalho e "
            "a lista completa de operações?",
            "o arquivo original que o MetaTrader exportou, sem edição",
        ),
    },
    "trials": {
        "es": (
            "¿Cuántas combinaciones de parámetros se probaron antes de elegir esta?",
            "el XML de la optimización de MT5 o la matriz de variantes",
        ),
        "en": (
            "How many parameter combinations were tried before choosing this one?",
            "the MT5 optimisation XML or the variants matrix",
        ),
        "pt": (
            "Quantas combinações de parâmetros foram testadas antes de escolher esta?",
            "o XML da otimização do MT5 ou a matriz de variantes",
        ),
    },
    "out_of_sample": {
        "es": (
            None,
            "la fecha en que terminó la optimización, declarada al subir, o un informe del "
            "mismo robot en fechas posteriores",
        ),
        "en": (
            None,
            "the date the optimisation ended, declared at upload, or a report of the same robot "
            "on later dates",
        ),
        "pt": (
            None,
            "a data em que a otimização terminou, declarada no envio, ou um relatório do mesmo "
            "robô em datas posteriores",
        ),
    },
    "costs": {
        "es": (
            "¿Qué spread, comisión y swap se usaron, y de qué bróker son?",
            "el spread, la comisión y el swap del bróker, declarados al subir como costo por lado",
        ),
        "en": (
            "Which spread, commission and swap were used, and which broker are they from?",
            "the broker's spread, commission and swap, declared at upload as the cost per side",
        ),
        "pt": (
            "Que spread, comissão e swap foram usados, e de qual corretora são?",
            "o spread, a comissão e o swap da corretora, declarados no envio como custo por lado",
        ),
    },
    "equity_curve": {
        "es": (
            "¿Cuánto perdían las posiciones abiertas, que el balance no muestra?",
            "la curva de equity con flotante, no solo la de balance",
        ),
        "en": (
            "How much were the open positions losing, which the balance does not show?",
            "the equity curve with floating results, not only the balance",
        ),
        "pt": (
            "Quanto as posições abertas estavam perdendo, o que o saldo não mostra?",
            "a curva de patrimônio com o flutuante, não só a de saldo",
        ),
    },
    "trades": {
        "es": (
            "¿Cuáles fueron las operaciones cerradas, con tamaños, precios y fechas?",
            "la lista completa de operaciones cerradas con tamaños, precios y fechas",
        ),
        "en": (
            "What were the closed trades, with sizes, prices and dates?",
            "the full list of closed trades with sizes, prices and dates",
        ),
        "pt": (
            "Quais foram as operações fechadas, com tamanhos, preços e datas?",
            "a lista completa de operações fechadas com tamanhos, preços e datas",
        ),
    },
    "martingale": {
        "es": (
            None,
            "la lista de operaciones con sus tamaños y el tamaño máximo que permite el robot",
        ),
        "en": (None, "the list of trades with their sizes, and the largest size the robot allows"),
        "pt": (
            None,
            "a lista de operações com seus tamanhos e o tamanho máximo que o robô permite",
        ),
    },
    "grid": {
        "es": (
            None,
            "la lista de operaciones con horas de entrada y tamaños, y el máximo de posiciones "
            "que abre el robot",
        ),
        "en": (
            None,
            "the list of trades with entry times and sizes, and the most positions the robot opens",
        ),
        "pt": (
            None,
            "a lista de operações com horas de entrada e tamanhos, e o máximo de posições que o "
            "robô abre",
        ),
    },
    "stop_loss": {
        "es": (None, "la curva de equity con flotante y la regla de stop de cada operación"),
        "en": (None, "the equity curve with floating results and each trade's stop rule"),
        "pt": (None, "a curva de patrimônio com o flutuante e a regra de stop de cada operação"),
    },
    "payoff": {
        "es": (None, "la regla de stop del sistema y la lista completa de operaciones"),
        "en": (None, "the system's stop rule and the full list of trades"),
        "pt": (None, "a regra de stop do sistema e a lista completa de operações"),
    },
    "deposits": {
        "es": (
            "¿Cuánto dinero se depositó en total, cuándo, y cuánto se retiró?",
            "el historial completo de la cuenta, con cada depósito y retiro",
        ),
        "en": (
            "How much money was deposited in total, when, and how much was withdrawn?",
            "the account's full history, with every deposit and withdrawal",
        ),
        "pt": (
            "Quanto dinheiro foi depositado no total, quando, e quanto foi sacado?",
            "o histórico completo da conta, com cada depósito e saque",
        ),
    },
    "open_positions": {
        "es": (None, "un historial impreso después de que se cierren esas posiciones"),
        "en": (None, "a history printed after those positions close"),
        "pt": (None, "um histórico impresso depois que essas posições forem fechadas"),
    },
    "data_quality": {
        "es": (
            None,
            "el archivo original de la plataforma o del administrador, sin limpiar a mano",
        ),
        "en": (None, "the original file from the platform or administrator, not cleaned by hand"),
        "pt": (None, "o arquivo original da plataforma ou do administrador, sem limpeza manual"),
    },
}
# The long-history wording of the live-record question has the same answer.
QUESTIONS["live_record_long"] = QUESTIONS["live_record"]

#: How a question reads in each voice: the developer's and the neutral list say
#: what answers it; the provider's says it will be asked and what to provide.
QUESTION_ITEM: dict[str, dict[str, str]] = {
    OWN: _say(
        "{ask} Lo responde: {answer}.",
        "{ask} What answers it: {answer}.",
        "{ask} O que responde: {answer}.",
    ),
    PROVIDER: _say(
        "Te van a preguntar: «{ask}» Aporta {answer}.",
        "You will be asked: “{ask}” Provide {answer}.",
        "Vão perguntar a você: «{ask}» Forneça {answer}.",
    ),
    NEUTRAL: _say(
        "{ask} Lo responde: {answer}.",
        "{ask} What answers it: {answer}.",
        "{ask} O que responde: {answer}.",
    ),
}


def question_item(code: str, stored: str, locale: str, role: str) -> str:
    """One stored question (``stored``, already in ``locale``) in ``role``'s voice."""
    if role == BUYER:
        return stored
    entry = QUESTIONS.get(code, {}).get(locale)
    template = QUESTION_ITEM.get(role, {}).get(locale)
    if entry is None or template is None:
        return stored
    ask, answer = entry
    return template.format(ask=ask or stored, answer=answer)


__all__ = [
    "BUYER",
    "FORM",
    "LABELS",
    "LOCKED_GAINS",
    "MEANING",
    "NEUTRAL",
    "OWN",
    "PLAN",
    "PROVIDER",
    "QUESTIONS",
    "ROLES",
    "VOICES",
    "Voiced",
    "choice_label",
    "gains_for",
    "labels_for",
    "meaning",
    "plan_text",
    "question_item",
    "role_of",
]
