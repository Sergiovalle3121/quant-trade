"""Whose strategy it is: an optional declaration that sets to whom the report speaks.

The upload form asks "¿De quién es esta estrategia?" with four answers: the
client's own ("own"), one they bought or are about to buy or copy ("buyer"),
one they provide and show to others ("provider"), or no answer. An answer is
stored as a DECLARED field of the result (``declared.ownership``); no answer
declares nothing, and the report then speaks in a neutral voice, never the
buyer's by default.

The voice changes only the sentences that speak to someone: "What to do
now", the plan to reach a better class, the questions section and the few
lines that send the reader to a seller. Two things follow from it: the
developer's "What to do now" adds a demo step (``demo_step``), and every
voice but the buyer's leaves out a question the files already answer
(``open_questions``). The order of the sections, every figure, the class
and the evidence tags are the same whatever the answer, and the public
verification page and cards never show it.

Each table below holds, per text, the wording for each voice that differs
from the buyer's, in Spanish, English and Portuguese side by side; a voice a
text does not list keeps the buyer's wording, which stays where it always
was (``report.LABELS``, ``plan``, ``verdict.MEANING``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from quant_trade.audit.live import MIN_BACKTEST_TRADES, MIN_LIVE_TRADES
from quant_trade.audit.verdict import MEANING as VERDICT_MEANING

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
            "Cambia a quién se dirigen las frases del informe y, si es tuya, añade un paso para "
            "probarla en demo: las cifras, la clase y las etiquetas son las mismas. Queda en el "
            "informe como declaración tuya y no aparece en la página pública."
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
            "It changes whom the report's sentences speak to and, if the strategy is yours, adds "
            "a step to try it on demo: the figures, the class and the tags stay the same. It "
            "stays in the report as your declaration and is not shown on the public page."
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
            "Muda a quem se dirigem as frases do relatório e, se a estratégia for sua, "
            "acrescenta uma etapa para testá-la em demo: os números, a classe e as etiquetas são "
            "os mesmos. Fica no relatório como declaração sua e não aparece na página pública."
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
    # The trial count was never declared nor counted: the deflated Sharpe was
    # taken at 1, the most favourable case, so fewer trials would change nothing.
    "next_trials_undeclared": {
        OWN: _say(
            "Declara cuántas configuraciones probaste o sube el XML de la optimización de MT5: "
            "el informe supuso 1, el caso más favorable, y aun así el Sharpe deflactado no llega "
            "a 0.95, así que reducir los intentos no lo cambia; lo que puede cambiarlo es un "
            "historial más largo del mismo sistema.",
            "Declare how many configurations you tried or upload the MT5 optimisation XML: the "
            "report assumed 1, the most favourable case, and even so the deflated Sharpe does "
            "not reach 0.95, so cutting trials does not change it; what can change it is a "
            "longer history of the same system.",
            "Declare quantas configurações você testou ou envie o XML da otimização do MT5: o "
            "relatório supôs 1, o caso mais favorável, e mesmo assim o Sharpe deflacionado não "
            "chega a 0.95, então reduzir as tentativas não o muda; o que pode mudá-lo é um "
            "histórico mais longo do mesmo sistema.",
        ),
        NEUTRAL: _say(
            "Conviene declarar cuántas configuraciones se probaron o subir el XML de la "
            "optimización de MT5: el informe supuso 1, el caso más favorable, y aun así el "
            "Sharpe deflactado no llega a 0.95.",
            "It is worth declaring how many configurations were tried or uploading the MT5 "
            "optimisation XML: the report assumed 1, the most favourable case, and even so the "
            "deflated Sharpe does not reach 0.95.",
            "Convém declarar quantas configurações foram testadas ou enviar o XML da otimização "
            "do MT5: o relatório supôs 1, o caso mais favorável, e mesmo assim o Sharpe "
            "deflacionado não chega a 0.95.",
        ),
    },
    # One configuration declared or counted: there is no search left to cut.
    "next_trials_one": {
        OWN: _say(
            "Con 1 configuración, el caso más favorable, el Sharpe deflactado no llega a 0.95: "
            "reducir los intentos no lo cambia; lo que puede cambiarlo es un historial más "
            "largo del mismo sistema.",
            "With 1 configuration, the most favourable case, the deflated Sharpe does not reach "
            "0.95: cutting trials does not change it; what can change it is a longer history of "
            "the same system.",
            "Com 1 configuração, o caso mais favorável, o Sharpe deflacionado não chega a 0.95: "
            "reduzir as tentativas não o muda; o que pode mudá-lo é um histórico mais longo do "
            "mesmo sistema.",
        ),
    },
    "next_oos": {
        OWN: _say(
            "Prueba la configuración en datos que el optimizador no vio: reoptimiza sin los "
            "últimos meses, corre el resultado sobre el periodo completo y declara la fecha de "
            "corte como inicio fuera de muestra. Esta prueba solo mide desde un inicio "
            "declarado; el periodo forward de la optimización de MT5 (su XML) se revisa aparte, "
            "en su propia sección.",
            "Test the settings on data the optimiser never saw: reoptimise without the last "
            "months, run the result over the whole period and declare the cut-off date as the "
            "out-of-sample start. This test only measures from a declared start; the forward "
            "period of the MT5 optimisation (its XML) is reviewed separately, in its own section.",
            "Teste a configuração em dados que o otimizador não viu: reotimize sem os últimos "
            "meses, rode o resultado no período completo e declare a data de corte como início "
            "fora da amostra. Este teste só mede a partir de um início declarado; o período "
            "forward da otimização do MT5 (seu XML) é revisado à parte, na sua própria seção.",
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
    # The developer already uploaded a forward export (``forward.py`` measured it):
    # it has its own section, and the out-of-sample test still needs a declared start.
    "next_oos_forward": {
        OWN: _say(
            "Prueba la configuración en datos que el optimizador no vio: reoptimiza sin los "
            "últimos meses, corre el resultado sobre el periodo completo y declara la fecha de "
            "corte como inicio fuera de muestra. El periodo forward que subiste se revisa en su "
            "propia sección; esta prueba solo mide desde un inicio declarado.",
            "Test the settings on data the optimiser never saw: reoptimise without the last "
            "months, run the result over the whole period and declare the cut-off date as the "
            "out-of-sample start. The forward period you uploaded is reviewed in its own "
            "section; this test only measures from a declared start.",
            "Teste a configuração em dados que o otimizador não viu: reotimize sem os últimos "
            "meses, rode o resultado no período completo e declare a data de corte como início "
            "fora da amostra. O período forward que você enviou é revisado na sua própria "
            "seção; este teste só mede a partir de um início declarado.",
        ),
    },
    # The declared out-of-sample stretch was measured and fell short: it has been
    # seen, so reoptimising on it would not make it unseen data again.
    "next_oos_seen": {
        OWN: _say(
            "Valida la configuración en fechas posteriores a las que ya usaste: reoptimizar "
            "sobre el tramo fuera de muestra que ya viste no cuenta como datos nuevos.",
            "Validate the settings on dates after the ones you have already used: reoptimising "
            "on the out-of-sample stretch you have already seen does not count as unseen data.",
            "Valide a configuração em datas posteriores às que você já usou: reotimizar sobre o "
            "trecho fora da amostra que você já viu não conta como dados novos.",
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
    # The same step when the backtest itself is too short for the comparison.
    "next_demo_short": {
        OWN: _say(
            f"La comparación con una cuenta necesita al menos {MIN_BACKTEST_TRADES} operaciones "
            f"cerradas en el backtest y {MIN_LIVE_TRADES} en la cuenta, y este backtest tiene "
            f"menos de {MIN_BACKTEST_TRADES}: alarga su periodo y, antes de operarla con dinero "
            f"real, córrela en una cuenta demo hasta tener {MIN_LIVE_TRADES} operaciones "
            "cerradas; luego sube los dos archivos juntos.",
            f"The comparison with an account needs at least {MIN_BACKTEST_TRADES} closed trades "
            f"in the backtest and {MIN_LIVE_TRADES} in the account, and this backtest has fewer "
            f"than {MIN_BACKTEST_TRADES}: lengthen its period and, before trading it with real "
            f"money, run it on a demo account until it has {MIN_LIVE_TRADES} closed trades; "
            "then upload both files together.",
            f"A comparação com uma conta precisa de pelo menos {MIN_BACKTEST_TRADES} operações "
            f"fechadas no backtest e {MIN_LIVE_TRADES} na conta, e este backtest tem menos de "
            f"{MIN_BACKTEST_TRADES}: alongue o seu período e, antes de operá-la com dinheiro "
            f"real, rode-a em uma conta demo até ter {MIN_LIVE_TRADES} operações fechadas; "
            "depois envie os dois arquivos juntos.",
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
    "next_keep_account": {
        OWN: _say(
            "Guarda este informe y su identificador; si cambias la configuración o pasas a "
            "otra cuenta, vuelve a auditarla y compara los dos informes.",
            "Keep this report and its identifier; if you change the settings or move to "
            "another account, audit it again and compare the two reports.",
            "Guarde este relatório e seu identificador; se você mudar a configuração ou passar "
            "para outra conta, audite-a de novo e compare os dois relatórios.",
        ),
        PROVIDER: _say(
            "Guarda este informe y su identificador; si cambias la configuración o pasas a "
            "otra cuenta, vuelve a auditarla y comparte el informe nuevo.",
            "Keep this report and its identifier; if you change the settings or move to "
            "another account, audit it again and share the new report.",
            "Guarde este relatório e seu identificador; se você mudar a configuração ou passar "
            "para outra conta, audite-a de novo e compartilhe o relatório novo.",
        ),
        NEUTRAL: _say(
            "Guarda este informe y su identificador; si la cuenta o señal cambia de "
            "configuración o pasa a otra cuenta, conviene auditarla de nuevo.",
            "Keep this report and its identifier; if the account or signal changes its "
            "settings or moves to another account, it is worth auditing it again.",
            "Guarde este relatório e seu identificador; se a conta ou sinal mudar de "
            "configuração ou passar para outra conta, convém auditá-la de novo.",
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
    "next_questions_fund": {
        OWN: _say(
            "Responde con tus documentos las preguntas que deja abiertas este informe: cada una "
            "dice qué la responde.",
            "Answer with your own documents the questions this report leaves open: each one "
            "says what answers it.",
            "Responda com os seus documentos às perguntas que este relatório deixa abertas: "
            "cada uma diz o que a responde.",
        ),
        PROVIDER: _say(
            "Prepara las respuestas a lo que te van a preguntar quienes vean este fondo: cada "
            "pregunta dice qué aportar.",
            "Prepare answers to what whoever sees this fund will ask you: each question says "
            "what to provide.",
            "Prepare as respostas ao que vão perguntar a você os que virem este fundo: cada "
            "pergunta diz o que fornecer.",
        ),
        NEUTRAL: _say(
            "Revisa las preguntas que deja abiertas este informe y lo que responde cada una.",
            "Go through the questions this report leaves open and what answers each one.",
            "Revise as perguntas que este relatório deixa abertas e o que responde cada uma.",
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
    # An account or signal: its trials are the accounts or signals behind it,
    # with no optimisation file to upload.
    "luck_uncounted_account": {
        OWN: _say(
            "El historial no dice cuántas cuentas o señales hay detrás de esta ni cuántas se "
            "cerraron o reiniciaron. La tabla muestra cuánto historial haría falta según "
            "cuántas fueran: declara cuántas llevas o has cerrado o reiniciado.",
            "The history does not say how many accounts or signals stand behind this one, or "
            "how many were closed or reset. The table shows how much history each count would "
            "need: declare how many you run or have closed or reset.",
            "O histórico não diz quantas contas ou sinais há por trás desta nem quantas foram "
            "encerradas ou reiniciadas. A tabela mostra quanto histórico seria necessário "
            "conforme quantas fossem: declare quantas você opera ou já encerrou ou reiniciou.",
        ),
        PROVIDER: _say(
            "El historial no dice cuántas cuentas o señales hay detrás de esta ni cuántas se "
            "cerraron o reiniciaron. La tabla muestra cuánto historial haría falta según "
            "cuántas fueran: te lo van a preguntar, así que declara cuántas llevas o has cerrado "
            "o reiniciado.",
            "The history does not say how many accounts or signals stand behind this one, or "
            "how many were closed or reset. The table shows how much history each count would "
            "need: you will be asked, so declare how many you run or have closed or reset.",
            "O histórico não diz quantas contas ou sinais há por trás desta nem quantas foram "
            "encerradas ou reiniciadas. A tabela mostra quanto histórico seria necessário "
            "conforme quantas fossem: vão perguntar isso a você, então declare quantas opera ou "
            "já encerrou ou reiniciou.",
        ),
        NEUTRAL: _say(
            "El historial no dice cuántas cuentas o señales hay detrás de esta ni cuántas se "
            "cerraron o reiniciaron. La tabla muestra cuánto historial haría falta según "
            "cuántas fueran: el número se puede declarar al subir el historial.",
            "The history does not say how many accounts or signals stand behind this one, or "
            "how many were closed or reset. The table shows how much history each count would "
            "need: the number can be declared when the history is uploaded.",
            "O histórico não diz quantas contas ou sinais há por trás desta nem quantas foram "
            "encerradas ou reiniciadas. A tabela mostra quanto histórico seria necessário "
            "conforme quantas fossem: o número pode ser declarado ao enviar o histórico.",
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


# An account or signal's "what to do now" opens as every other report does in
# each voice but the buyer's, whose wording names the account or signal.
LABELS["next_intro_account"] = LABELS["next_intro"]


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


#: What an account or signal's history does not say, as its out-of-sample
#: meaning opens in every voice (``verdict.MEANING`` words the buyer's): since
#: when it has traded unchanged, and whether it was reset or replaced a closed one.
_ACCOUNT_UNCHANGED: dict[str, str] = _say(
    "El historial no dice desde cuándo opera sin cambios esta cuenta o señal, ni si hubo "
    "reinicios o cuentas cerradas antes, así que no se sabe qué parte es prueba sobre datos "
    "nuevos.",
    "The history does not say since when this account or signal has traded unchanged, or "
    "whether it was reset or earlier accounts were closed, so it is not known which part is a "
    "test on unseen data.",
    "O histórico não diz desde quando esta conta ou sinal opera sem alterações, nem se houve "
    "reinícios ou contas encerradas antes, então não se sabe qual parte é teste sobre dados "
    "novos.",
)

#: ``verdict.MEANING`` texts that send the reader to a provider or manager.
MEANING: dict[str, dict[str, dict[str, str]]] = {
    "out_of_sample.NOT_MEASURED.account": {
        OWN: _say(
            f"{_ACCOUNT_UNCHANGED['es']} Declara la fecha desde la que no cambiaste la "
            "configuración para medirlo.",
            f"{_ACCOUNT_UNCHANGED['en']} Declare the date since which you have not changed the "
            "settings to measure it.",
            f"{_ACCOUNT_UNCHANGED['pt']} Declare a data desde a qual você não mudou a "
            "configuração para medi-lo.",
        ),
        PROVIDER: _say(
            f"{_ACCOUNT_UNCHANGED['es']} Te van a preguntar esa fecha y si hubo reinicios: "
            "declárala para medirlo.",
            f"{_ACCOUNT_UNCHANGED['en']} You will be asked for that date and whether there "
            "were resets: declare it to measure it.",
            f"{_ACCOUNT_UNCHANGED['pt']} Vão perguntar a você essa data e se houve reinícios: "
            "declare-a para medi-lo.",
        ),
        NEUTRAL: _say(
            f"{_ACCOUNT_UNCHANGED['es']} Declarar esa fecha permite medirlo.",
            f"{_ACCOUNT_UNCHANGED['en']} Declaring that date lets it be measured.",
            f"{_ACCOUNT_UNCHANGED['pt']} Declarar essa data permite medi-lo.",
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
    # The buyer's wording asks how many were tried and for the optimisation file.
    "multiplicity.WEAK": {
        OWN: _say(
            "Parte del resultado puede venir de elegir la mejor de muchas configuraciones. "
            "Valida la elegida en datos que no usaste al optimizar y, en la próxima versión, "
            "optimiza menos parámetros.",
            "Part of the result may come from picking the best of many configurations. "
            "Validate the chosen one on data you did not use while optimising and, in the next "
            "version, optimise fewer parameters.",
            "Parte do resultado pode vir de escolher a melhor entre muitas configurações. "
            "Valide a escolhida em dados que você não usou na otimização e, na próxima versão, "
            "otimize menos parâmetros.",
        ),
        PROVIDER: _say(
            "Parte del resultado puede venir de elegir la mejor de muchas configuraciones. Te "
            "van a preguntar si la elegida se validó en datos que no se usaron al optimizar.",
            "Part of the result may come from picking the best of many configurations. You "
            "will be asked whether the chosen one was validated on data not used while "
            "optimising.",
            "Parte do resultado pode vir de escolher a melhor entre muitas configurações. Vão "
            "perguntar a você se a escolhida foi validada em dados que não foram usados na "
            "otimização.",
        ),
        NEUTRAL: _say(
            "Parte del resultado puede venir de elegir la mejor de muchas configuraciones. "
            "Conviene validar la elegida en datos que no se usaron al optimizar.",
            "Part of the result may come from picking the best of many configurations. It is "
            "worth validating the chosen one on data not used while optimising.",
            "Parte do resultado pode vir de escolher a melhor entre muitas configurações. "
            "Convém validar a escolhida em dados que não foram usados na otimização.",
        ),
    },
    "multiplicity.WEAK.fund": {
        OWN: _say(
            "Parte del resultado puede venir de que este sea el mejor de varios fondos o "
            "estrategias. Declara como intentos todos los que llevas o has cerrado: un buen "
            "historial entre muchos pesa menos.",
            "Part of the result may come from this being the best of several funds or "
            "strategies. Declare as trials all the ones you run or have closed: one good record "
            "among many weighs less.",
            "Parte do resultado pode vir de este ser o melhor entre vários fundos ou "
            "estratégias. Declare como tentativas todos os que você administra ou já encerrou: "
            "um bom histórico entre muitos pesa menos.",
        ),
        PROVIDER: _say(
            "Parte del resultado puede venir de que este sea el mejor de varios fondos o "
            "estrategias. Te van a preguntar cuántos llevas o has cerrado: decláralo como "
            "número de intentos.",
            "Part of the result may come from this being the best of several funds or "
            "strategies. You will be asked how many you run or have closed: declare it as the "
            "number of trials.",
            "Parte do resultado pode vir de este ser o melhor entre vários fundos ou "
            "estratégias. Vão perguntar a você quantos administra ou já encerrou: declare isso "
            "como número de tentativas.",
        ),
        NEUTRAL: _say(
            "Parte del resultado puede venir de que este sea el mejor de varios fondos o "
            "estrategias del mismo gestor. Un buen historial entre muchos pesa menos.",
            "Part of the result may come from this being the best of several funds or "
            "strategies from the same manager. One good record among many weighs less.",
            "Parte do resultado pode vir de este ser o melhor entre vários fundos ou "
            "estratégias do mesmo gestor. Um bom histórico entre muitos pesa menos.",
        ),
    },
    # No trial count declared nor counted: the figure was taken at 1, the most
    # favourable case, so "many configurations" is not what this measured.
    "multiplicity.WEAK.undeclared": {
        OWN: _say(
            "Aun contando una sola configuración, el caso más favorable, el resultado no basta "
            "para descartar la suerte. No declaraste cuántas probaste: declara el número o sube "
            "el XML de la optimización, porque con más de una la conclusión sería más débil.",
            "Even counting a single configuration, the most favourable case, the result is not "
            "enough to rule out luck. You did not declare how many you tried: declare the "
            "number or upload the optimisation XML, since with more than one the conclusion "
            "would be weaker.",
            "Mesmo contando uma única configuração, o caso mais favorável, o resultado não "
            "basta para descartar a sorte. Você não declarou quantas testou: declare o número "
            "ou envie o XML da otimização, porque com mais de uma a conclusão seria mais fraca.",
        ),
        PROVIDER: _say(
            "Aun contando una sola configuración, el caso más favorable, el resultado no basta "
            "para descartar la suerte. Te van a preguntar cuántas se probaron: declara el "
            "número o aporta el XML de la optimización.",
            "Even counting a single configuration, the most favourable case, the result is not "
            "enough to rule out luck. You will be asked how many were tried: declare the "
            "number or provide the optimisation XML.",
            "Mesmo contando uma única configuração, o caso mais favorável, o resultado não "
            "basta para descartar a sorte. Vão perguntar a você quantas foram testadas: declare "
            "o número ou forneça o XML da otimização.",
        ),
        NEUTRAL: _say(
            "Aun contando una sola configuración, el caso más favorable, el resultado no basta "
            "para descartar la suerte. No se declaró cuántas se probaron: con más de una, la "
            "conclusión sería más débil.",
            "Even counting a single configuration, the most favourable case, the result is not "
            "enough to rule out luck. How many were tried was not declared: with more than "
            "one, the conclusion would be weaker.",
            "Mesmo contando uma única configuração, o caso mais favorável, o resultado não "
            "basta para descartar a sorte. Não foi declarado quantas foram testadas: com mais "
            "de uma, a conclusão seria mais fraca.",
        ),
    },
    "multiplicity.WEAK.undeclared.fund": {
        OWN: _say(
            "Aun contando un solo fondo, el caso más favorable, el resultado no basta para "
            "descartar la suerte. No declaraste cuántos fondos o estrategias llevas: declara el "
            "número, porque con más de uno la conclusión sería más débil.",
            "Even counting a single fund, the most favourable case, the result is not enough to "
            "rule out luck. You did not declare how many funds or strategies you run: declare "
            "the number, since with more than one the conclusion would be weaker.",
            "Mesmo contando um único fundo, o caso mais favorável, o resultado não basta para "
            "descartar a sorte. Você não declarou quantos fundos ou estratégias administra: "
            "declare o número, porque com mais de um a conclusão seria mais fraca.",
        ),
        PROVIDER: _say(
            "Aun contando un solo fondo, el caso más favorable, el resultado no basta para "
            "descartar la suerte. Te van a preguntar cuántos fondos o estrategias llevas o has "
            "cerrado: decláralo.",
            "Even counting a single fund, the most favourable case, the result is not enough to "
            "rule out luck. You will be asked how many funds or strategies you run or have "
            "closed: declare it.",
            "Mesmo contando um único fundo, o caso mais favorável, o resultado não basta para "
            "descartar a sorte. Vão perguntar a você quantos fundos ou estratégias administra "
            "ou já encerrou: declare isso.",
        ),
        NEUTRAL: _say(
            "Aun contando un solo fondo, el caso más favorable, el resultado no basta para "
            "descartar la suerte. No se declaró cuántos fondos o estrategias lleva el gestor: "
            "con más de uno, la conclusión sería más débil.",
            "Even counting a single fund, the most favourable case, the result is not enough to "
            "rule out luck. How many funds or strategies the manager runs was not declared: "
            "with more than one, the conclusion would be weaker.",
            "Mesmo contando um único fundo, o caso mais favorável, o resultado não basta para "
            "descartar a sorte. Não foi declarado quantos fundos ou estratégias o gestor "
            "administra: com mais de um, a conclusão seria mais fraca.",
        ),
    },
    # An account or signal has no optimisation to export: its trials are the
    # other accounts or signals behind it, and the ones closed or reset.
    "multiplicity.WEAK.account": {
        OWN: _say(
            "Parte del resultado puede venir de que esta sea la mejor de varias cuentas o "
            "señales. Declara como intentos todas las que llevas o has cerrado o reiniciado: "
            "una buena cuenta entre muchas pesa menos.",
            "Part of the result may come from this being the best of several accounts or "
            "signals. Declare as trials all the ones you run or have closed or reset: one good "
            "account among many weighs less.",
            "Parte do resultado pode vir de esta ser a melhor entre várias contas ou sinais. "
            "Declare como tentativas todas as que você opera ou já encerrou ou reiniciou: uma "
            "boa conta entre muitas pesa menos.",
        ),
        PROVIDER: _say(
            "Parte del resultado puede venir de que esta sea la mejor de varias cuentas o "
            "señales. Te van a preguntar cuántas llevas o has cerrado o reiniciado: decláralo "
            "como número de intentos.",
            "Part of the result may come from this being the best of several accounts or "
            "signals. You will be asked how many you run or have closed or reset: declare it as "
            "the number of trials.",
            "Parte do resultado pode vir de esta ser a melhor entre várias contas ou sinais. Vão "
            "perguntar a você quantas opera ou já encerrou ou reiniciou: declare isso como "
            "número de tentativas.",
        ),
        NEUTRAL: _say(
            "Parte del resultado puede venir de que esta sea la mejor de varias cuentas o "
            "señales. Una buena cuenta entre muchas pesa menos.",
            "Part of the result may come from this being the best of several accounts or "
            "signals. One good account among many weighs less.",
            "Parte do resultado pode vir de esta ser a melhor entre várias contas ou sinais. Uma "
            "boa conta entre muitas pesa menos.",
        ),
    },
    "multiplicity.WEAK.undeclared.account": {
        OWN: _say(
            "Aun contando una sola cuenta, el caso más favorable, el resultado no basta para "
            "descartar la suerte. No declaraste cuántas cuentas o señales llevas o has cerrado "
            "o reiniciado: declara el número, porque con más de una la conclusión sería más "
            "débil.",
            "Even counting a single account, the most favourable case, the result is not "
            "enough to rule out luck. You did not declare how many accounts or signals you run "
            "or have closed or reset: declare the number, since with more than one the "
            "conclusion would be weaker.",
            "Mesmo contando uma única conta, o caso mais favorável, o resultado não basta para "
            "descartar a sorte. Você não declarou quantas contas ou sinais opera ou já encerrou "
            "ou reiniciou: declare o número, porque com mais de uma a conclusão seria mais "
            "fraca.",
        ),
        PROVIDER: _say(
            "Aun contando una sola cuenta, el caso más favorable, el resultado no basta para "
            "descartar la suerte. Te van a preguntar cuántas cuentas o señales llevas o has "
            "cerrado o reiniciado: decláralo.",
            "Even counting a single account, the most favourable case, the result is not "
            "enough to rule out luck. You will be asked how many accounts or signals you run or "
            "have closed or reset: declare it.",
            "Mesmo contando uma única conta, o caso mais favorável, o resultado não basta para "
            "descartar a sorte. Vão perguntar a você quantas contas ou sinais opera ou já "
            "encerrou ou reiniciou: declare isso.",
        ),
        NEUTRAL: _say(
            "Aun contando una sola cuenta, el caso más favorable, el resultado no basta para "
            "descartar la suerte. No se declaró cuántas cuentas o señales hay detrás ni "
            "cuántas se cerraron o reiniciaron: con más de una, la conclusión sería más débil.",
            "Even counting a single account, the most favourable case, the result is not "
            "enough to rule out luck. How many accounts or signals stand behind it, or were "
            "closed or reset, was not declared: with more than one, the conclusion would be "
            "weaker.",
            "Mesmo contando uma única conta, o caso mais favorável, o resultado não basta para "
            "descartar a sorte. Não foi declarado quantas contas ou sinais há por trás nem "
            "quantas foram encerradas ou reiniciadas: com mais de uma, a conclusão seria mais "
            "fraca.",
        ),
    },
    "multiplicity.FAIL.undeclared.account": {
        OWN: _say(
            "Incluso contando una sola cuenta, el caso más favorable, el resultado no supera lo "
            "que daría un intento sin ventaja real. No declaraste cuántas cuentas o señales "
            "llevas o has cerrado o reiniciado: con más de una, la conclusión sería aún más "
            "débil.",
            "Even counting a single account, the most favourable case, the result does not "
            "exceed what a trial with no real edge would give. You did not declare how many "
            "accounts or signals you run or have closed or reset: with more than one, the "
            "conclusion would be weaker still.",
            "Mesmo contando uma única conta, o caso mais favorável, o resultado não supera o que "
            "uma tentativa sem vantagem real daria. Você não declarou quantas contas ou sinais "
            "opera ou já encerrou ou reiniciou: com mais de uma, a conclusão seria ainda mais "
            "fraca.",
        ),
        PROVIDER: _say(
            "Incluso contando una sola cuenta, el caso más favorable, el resultado no supera lo "
            "que daría un intento sin ventaja real. Te van a preguntar cuántas cuentas o señales "
            "llevas o has cerrado o reiniciado: con más de una, la conclusión sería aún más "
            "débil.",
            "Even counting a single account, the most favourable case, the result does not "
            "exceed what a trial with no real edge would give. You will be asked how many "
            "accounts or signals you run or have closed or reset: with more than one, the "
            "conclusion would be weaker still.",
            "Mesmo contando uma única conta, o caso mais favorável, o resultado não supera o que "
            "uma tentativa sem vantagem real daria. Vão perguntar a você quantas contas ou "
            "sinais opera ou já encerrou ou reiniciou: com mais de uma, a conclusão seria ainda "
            "mais fraca.",
        ),
        NEUTRAL: _say(
            "Incluso contando una sola cuenta, el caso más favorable, el resultado no supera lo "
            "que daría un intento sin ventaja real. No se declaró cuántas cuentas o señales hay "
            "detrás ni cuántas se cerraron o reiniciaron: con más de una, la conclusión sería "
            "aún más débil.",
            "Even counting a single account, the most favourable case, the result does not "
            "exceed what a trial with no real edge would give. How many accounts or signals "
            "stand behind it, or were closed or reset, was not declared: with more than one, "
            "the conclusion would be weaker still.",
            "Mesmo contando uma única conta, o caso mais favorável, o resultado não supera o que "
            "uma tentativa sem vantagem real daria. Não foi declarado quantas contas ou sinais "
            "há por trás nem quantas foram encerradas ou reiniciadas: com mais de uma, a "
            "conclusão seria ainda mais fraca.",
        ),
    },
    "multiplicity.NOT_MEASURED.undeclared.account": {
        OWN: _say(
            "No declaraste cuántas cuentas o señales llevas o has cerrado o reiniciado, así que "
            "la clase no puede pasar de B. Al declararlo (aunque sea 1), Rigor puede "
            "descontarlo.",
            "You did not declare how many accounts or signals you run or have closed or reset, "
            "so the class cannot go above B. Once you declare it (even if it is 1), Rigor can "
            "discount it.",
            "Você não declarou quantas contas ou sinais opera ou já encerrou ou reiniciou, então "
            "a classe não pode passar de B. Ao declarar esse número (mesmo que seja 1), o Rigor "
            "pode descontá-lo.",
        ),
        PROVIDER: _say(
            "No se declaró cuántas cuentas o señales llevas o has cerrado o reiniciado, así que "
            "la clase no puede pasar de B. Te lo van a preguntar: al declararlo (aunque sea 1), "
            "Rigor puede descontarlo.",
            "How many accounts or signals you run or have closed or reset was not declared, so "
            "the class cannot go above B. You will be asked: once you declare it (even if it is "
            "1), Rigor can discount it.",
            "Não foi declarado quantas contas ou sinais você opera ou já encerrou ou reiniciou, "
            "então a classe não pode passar de B. Vão perguntar isso a você: ao declarar esse "
            "número (mesmo que seja 1), o Rigor pode descontá-lo.",
        ),
        NEUTRAL: _say(
            "No se declaró cuántas cuentas o señales hay detrás de esta ni cuántas se cerraron o "
            "reiniciaron, así que la clase no puede pasar de B. Al declararlo (aunque sea 1), "
            "Rigor puede descontarlo.",
            "How many accounts or signals stand behind this one, or were closed or reset, was "
            "not declared, so the class cannot go above B. Once it is declared (even if it is "
            "1), Rigor can discount it.",
            "Não foi declarado quantas contas ou sinais há por trás desta nem quantas foram "
            "encerradas ou reiniciadas, então a classe não pode passar de B. Ao declarar esse "
            "número (mesmo que seja 1), o Rigor pode descontá-lo.",
        ),
    },
}


def _meaning_key(
    name: str, status: str, *, account: bool, fund: bool, undeclared: bool
) -> str | None:
    """The text ``verdict.meaning`` would pick, in its order, among its own
    keys and the ones only this module words (``.undeclared`` of a weak result,
    and of an account's)."""
    candidates = []
    if undeclared and fund:
        candidates.append(f"{name}.{status}.undeclared.fund")
    if undeclared and account:
        candidates.append(f"{name}.{status}.undeclared.account")
    if undeclared:
        candidates.append(f"{name}.{status}.undeclared")
    if fund:
        candidates.append(f"{name}.{status}.fund")
    if account:
        candidates.append(f"{name}.{status}.account")
    candidates.append(f"{name}.{status}")
    known = VERDICT_MEANING["es"]
    return next((key for key in candidates if key in known or key in MEANING), None)


def meaning(
    name: str,
    status: str,
    locale: str,
    role: str,
    *,
    account: bool = False,
    fund: bool = False,
    undeclared: bool = False,
) -> str | None:
    """A dimension's plain-language meaning in ``role``'s voice, or None to keep
    ``verdict.meaning`` (the buyer's, and every text that names nobody).

    The same flags as ``verdict.meaning`` pick the text, so a voiced wording
    never stands in for a more specific one that already names nobody."""
    if role == BUYER:
        return None
    key = _meaning_key(name, status, account=account, fund=fund, undeclared=undeclared)
    return MEANING.get(key or "", {}).get(role, {}).get(locale)


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
            "Sube el backtest de la misma estrategia, si lo tiene, junto a la cuenta: el "
            "informe compara los dos operación por operación.",
            "Upload the backtest of the same strategy, if it has one, with the account: the "
            "report compares the two trade by trade.",
            "Envie o backtest da mesma estratégia, se ela tiver um, junto com a conta: o "
            "relatório compara os dois operação por operação.",
        ),
        PROVIDER: _say(
            "Te van a pedir el backtest de la misma estrategia, si lo tiene: súbelo junto a la "
            "cuenta y el informe compara los dos operación por operación.",
            "You will be asked for the backtest of the same strategy, if it has one: upload it "
            "with the account and the report compares the two trade by trade.",
            "Vão pedir a você o backtest da mesma estratégia, se ela tiver um: envie-o junto "
            "com a conta e o relatório compara os dois operação por operação.",
        ),
        NEUTRAL: _say(
            "Sube el backtest de la misma estrategia, si lo tiene, junto a la cuenta: el "
            "informe compara los dos operación por operación.",
            "Upload the backtest of the same strategy, if it has one, with the account: the "
            "report compares the two trade by trade.",
            "Envie o backtest da mesma estratégia, se ela tiver um, junto com a conta: o "
            "relatório compara os dois operação por operação.",
        ),
    },
    "account_trials_undeclared": {
        OWN: _say(
            "Declara cuántas cuentas o señales llevas o has cerrado o reiniciado (aunque sea "
            "1) al subir el historial: Rigor lo descuenta.",
            "Declare how many accounts or signals you run or have closed or reset (even if it "
            "is 1) when you upload the history: Rigor discounts it.",
            "Declare quantas contas ou sinais você opera ou já encerrou ou reiniciou (mesmo "
            "que seja 1) ao enviar o histórico: o Rigor o desconta.",
        ),
        PROVIDER: _say(
            "Te van a preguntar cuántas cuentas o señales llevas o has cerrado o reiniciado: "
            "decláralo (aunque sea 1) al subir el historial y Rigor lo descuenta.",
            "You will be asked how many accounts or signals you run or have closed or reset: "
            "declare it (even if it is 1) when you upload the history and Rigor discounts it.",
            "Vão perguntar a você quantas contas ou sinais opera ou já encerrou ou reiniciou: "
            "declare esse número (mesmo que seja 1) ao enviar o histórico e o Rigor o desconta.",
        ),
        NEUTRAL: _say(
            "Declara cuántas cuentas o señales hay detrás de esta, o se cerraron o "
            "reiniciaron (aunque sea 1), al subir el historial: Rigor lo descuenta.",
            "Declare how many accounts or signals stand behind this one, or were closed or "
            "reset (even if it is 1), when you upload the history: Rigor discounts it.",
            "Declare quantas contas ou sinais há por trás desta, ou foram encerradas ou "
            "reiniciadas (mesmo que seja 1), ao enviar o histórico: o Rigor o desconta.",
        ),
    },
    "account_trials": {
        OWN: _say(
            "Declara como número de intentos cuántas cuentas o señales llevas o has cerrado o "
            "reiniciado: una buena cuenta entre muchas pesa menos.",
            "Declare how many accounts or signals you run or have closed or reset as the "
            "number of trials: one good account among many weighs less.",
            "Declare como número de tentativas quantas contas ou sinais você opera ou já "
            "encerrou ou reiniciou: uma boa conta entre muitas pesa menos.",
        ),
        PROVIDER: _say(
            "Te van a preguntar cuántas cuentas o señales llevas o has cerrado o reiniciado: "
            "decláralo como número de intentos, porque una buena cuenta entre muchas pesa "
            "menos.",
            "You will be asked how many accounts or signals you run or have closed or reset: "
            "declare it as the number of trials, since one good account among many weighs "
            "less.",
            "Vão perguntar a você quantas contas ou sinais opera ou já encerrou ou reiniciou: "
            "declare isso como número de tentativas, porque uma boa conta entre muitas pesa "
            "menos.",
        ),
        NEUTRAL: _say(
            "Declara como número de intentos cuántas cuentas o señales hay detrás de esta, o "
            "se cerraron o reiniciaron: una buena cuenta entre muchas pesa menos.",
            "Declare how many accounts or signals stand behind this one, or were closed or "
            "reset, as the number of trials: one good account among many weighs less.",
            "Declare como número de tentativas quantas contas ou sinais há por trás desta, ou "
            "foram encerradas ou reiniciadas: uma boa conta entre muitas pesa menos.",
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
    "account_flag_MARTINGALE_SIZING": {
        OWN: _say(
            "El tamaño crece tras las pérdidas: si llevas también una cuenta con tamaño fijo o "
            "riesgo fijo, súbela para comparar; si no, el riesgo real es el del tamaño máximo "
            "que llegó a abrir esta.",
            "Size grows after losses: if you also run an account at a fixed size or fixed risk, "
            "upload it to compare; if not, the real risk is that of the largest size this one "
            "opened.",
            "O tamanho cresce após as perdas: se você também opera uma conta com tamanho fixo ou "
            "risco fixo, envie-a para comparar; se não, o risco real é o do maior tamanho que "
            "esta chegou a abrir.",
        ),
        PROVIDER: _say(
            "El tamaño crece tras las pérdidas: te van a preguntar el tamaño máximo que puede "
            "abrir esta cuenta o señal y por un historial con tamaño fijo, si existe: apórtalos.",
            "Size grows after losses: you will be asked for the largest size this account or "
            "signal can open, and for a history at a fixed size if there is one: provide them.",
            "O tamanho cresce após as perdas: vão perguntar a você o tamanho máximo que esta "
            "conta ou sinal pode abrir e pedir um histórico com tamanho fixo, se existir: "
            "forneça-os.",
        ),
        NEUTRAL: _say(
            "El tamaño crece tras las pérdidas: el riesgo real depende del tamaño máximo que "
            "puede abrir esta cuenta o señal; un historial de la misma estrategia con tamaño "
            "fijo, si existe, permite compararlo.",
            "Size grows after losses: the real risk depends on the largest size this account or "
            "signal can open; a history of the same strategy at a fixed size, if there is one, "
            "allows a comparison.",
            "O tamanho cresce após as perdas: o risco real depende do tamanho máximo que esta "
            "conta ou sinal pode abrir; um histórico da mesma estratégia com tamanho fixo, se "
            "existir, permite comparar.",
        ),
    },
    "account_flag_GRID_AVERAGING": {
        OWN: _say(
            "Se abren posiciones contra la posición perdedora: si llevas también una cuenta sin "
            "promediar, súbela para ver cuánto depende de ello; si no, el riesgo real es el de "
            "todas las posiciones abiertas a la vez.",
            "Positions are added against the losing one: if you also run an account without "
            "averaging, upload it to see how much depends on it; if not, the real risk is that "
            "of all the positions open at once.",
            "Abrem-se posições contra a posição perdedora: se você também opera uma conta sem "
            "preço médio, envie-a para ver quanto depende disso; se não, o risco real é o de "
            "todas as posições abertas ao mesmo tempo.",
        ),
        PROVIDER: _say(
            "Se abren posiciones contra la posición perdedora: te van a preguntar cuántas abre "
            "como máximo esta cuenta o señal y por un historial sin promediar, si existe: "
            "apórtalos.",
            "Positions are added against the losing one: you will be asked how many this "
            "account or signal opens at most, and for a history without averaging if there is "
            "one: provide them.",
            "Abrem-se posições contra a posição perdedora: vão perguntar a você quantas esta "
            "conta ou sinal abre no máximo e pedir um histórico sem preço médio, se existir: "
            "forneça-os.",
        ),
        NEUTRAL: _say(
            "Se abren posiciones contra la posición perdedora: cuánto depende de ello se ve en "
            "el máximo de posiciones que abre esta cuenta o señal y, si existe, en un historial "
            "de la misma estrategia sin promediar.",
            "Positions are added against the losing one: how much depends on it shows in the "
            "most positions this account or signal opens and, if there is one, in a history of "
            "the same strategy without averaging.",
            "Abrem-se posições contra a posição perdedora: quanto depende disso se vê no máximo "
            "de posições que esta conta ou sinal abre e, se existir, num histórico da mesma "
            "estratégia sem preço médio.",
        ),
    },
    "account_flag_MANY_CONCURRENT_POSITIONS": {
        OWN: _say(
            "Sube la curva de equity con flotante de esta cuenta: muestra lo que pierden juntas "
            "las posiciones abiertas a la vez.",
            "Upload this account's equity curve with floating P&L: it shows what the positions "
            "open at once lose together.",
            "Envie a curva de patrimônio com flutuante desta conta: mostra o que as posições "
            "abertas ao mesmo tempo perdem juntas.",
        ),
        PROVIDER: _say(
            "Te van a preguntar cuántas posiciones abre como máximo a la vez esta cuenta o señal "
            "y te van a pedir la curva de equity con flotante: apórtala.",
            "You will be asked how many positions this account or signal opens at most at once, "
            "and for the equity curve with floating P&L: provide it.",
            "Vão perguntar a você quantas posições esta conta ou sinal abre no máximo ao mesmo "
            "tempo e pedir a curva de patrimônio com flutuante: forneça-a.",
        ),
        NEUTRAL: _say(
            "Lo que pierden juntas las posiciones abiertas a la vez se ve en la curva de equity "
            "con flotante y en el máximo de posiciones que abre esta cuenta o señal.",
            "What the positions open at once lose together shows in the equity curve with "
            "floating P&L and in the most positions this account or signal opens.",
            "O que as posições abertas ao mesmo tempo perdem juntas se vê na curva de patrimônio "
            "com flutuante e no máximo de posições que esta conta ou sinal abre.",
        ),
    },
    "account_flag_HIDDEN_FLOATING_DRAWDOWN": {
        OWN: _say(
            "El historial solo muestra el balance: sube la curva de equity (con flotante) de "
            "esta cuenta para medir el drawdown real.",
            "The history shows only the balance: upload this account's equity curve (with "
            "floating P&L) to measure the real drawdown.",
            "O histórico mostra só o saldo: envie a curva de patrimônio (com flutuante) desta "
            "conta para medir o drawdown real.",
        ),
        PROVIDER: _say(
            "El historial solo muestra el balance: te van a pedir la curva de equity (con "
            "flotante) de esta cuenta, que mide el drawdown real: apórtala.",
            "The history shows only the balance: you will be asked for this account's equity "
            "curve (with floating P&L), which measures the real drawdown: provide it.",
            "O histórico mostra só o saldo: vão pedir a você a curva de patrimônio (com "
            "flutuante) desta conta, que mede o drawdown real: forneça-a.",
        ),
        NEUTRAL: _say(
            "El historial solo muestra el balance: el drawdown real se mide con la curva de "
            "equity (con flotante) de esta cuenta.",
            "The history shows only the balance: the real drawdown is measured on this "
            "account's equity curve (with floating P&L).",
            "O histórico mostra só o saldo: o drawdown real se mede com a curva de patrimônio "
            "(com flutuante) desta conta.",
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
    "title_account_multiplicity": {
        OWN: _say(
            "Declara cuántas cuentas o señales llevas",
            "Declare how many accounts or signals you run",
            "Declare quantas contas ou sinais você opera",
        ),
        PROVIDER: _say(
            "Declara cuántas cuentas o señales llevas",
            "Declare how many accounts or signals you run",
            "Declare quantas contas ou sinais você opera",
        ),
        NEUTRAL: _say(
            "Declara cuántas cuentas o señales hay detrás",
            "Declare how many accounts or signals stand behind it",
            "Declare quantas contas ou sinais há por trás",
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
    # Asked of an account or signal only: a signal may have no backtest at all.
    "backtest_match": {
        "es": (
            "¿Se parece esta cuenta al backtest de la misma estrategia, si lo tiene, con la "
            "misma configuración?",
            "el backtest de la misma estrategia con la misma configuración, subido junto a esta "
            "cuenta: el informe compara los dos operación por operación",
        ),
        "en": (
            "Does this account look like the backtest of the same strategy, if it has one, "
            "with the same settings?",
            "the backtest of the same strategy with the same settings, uploaded together with "
            "this account: the report compares the two trade by trade",
        ),
        "pt": (
            "Esta conta se parece com o backtest da mesma estratégia, se ela tiver um, com a "
            "mesma configuração?",
            "o backtest da mesma estratégia com a mesma configuração, enviado junto com esta "
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
    # The modelling question when the uploaded file is a tester report that prints
    # no mode we recognise (``testdata.review_test_data``): sending the reader
    # back to that same report would answer nothing.
    "modelling_unread": {
        "es": (
            None,
            "un informe del probador que imprima el modo de modelado, porque el subido no "
            "indica uno que reconozcamos (en MT5, la prueba con «Cada tick basado en ticks "
            "reales» lo deja escrito en la calidad de históricos)",
        ),
        "en": (
            None,
            "a tester report that prints the modelling mode, since the uploaded one states none "
            "we recognise (in MT5, a test on “Every tick based on real ticks” writes it in the "
            "history quality)",
        ),
        "pt": (
            None,
            "um relatório do testador que imprima o modo de modelagem, porque o enviado não "
            "indica um que reconheçamos (no MT5, o teste com «Cada tick baseado em ticks reais» "
            "o deixa escrito na qualidade do histórico)",
        ),
    },
    # The tester report states its mode, and a red flag says the mode or the
    # history's quality falls short: what is open is the rerun.
    "modelling_flagged": {
        "es": (
            "¿Qué da el mismo backtest con cada tick (ticks reales en MT5) y un historial "
            "completo?",
            "el mismo backtest repetido así: el modo o la calidad del informe subido tienen una "
            "bandera roja",
        ),
        "en": (
            "What does the same backtest give on every tick (real ticks in MT5) with a complete "
            "history?",
            "the same backtest rerun that way: the uploaded report's mode or quality carries a "
            "red flag",
        ),
        "pt": (
            "O que dá o mesmo backtest com cada tick (ticks reais no MT5) e um histórico completo?",
            "o mesmo backtest repetido assim: o modo ou a qualidade do relatório enviado tem uma "
            "bandeira vermelha",
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

#: What answers a question asked of an account or signal (``question_item`` with
#: ``account``) where the backtest's answer names the robot: the account's own
#: trades and history. The question itself is ``analytics.ACCOUNT_QUESTIONS``.
ACCOUNT_QUESTIONS: dict[str, dict[str, tuple[str | None, str]]] = {
    "martingale": {
        "es": (
            None,
            "la lista de operaciones con sus tamaños y el tamaño máximo que puede abrir esta "
            "cuenta o señal",
        ),
        "en": (
            None,
            "the list of trades with their sizes, and the largest size this account or signal "
            "can open",
        ),
        "pt": (
            None,
            "a lista de operações com seus tamanhos e o tamanho máximo que esta conta ou sinal "
            "pode abrir",
        ),
    },
    "grid": {
        "es": (
            None,
            "la lista de operaciones con horas de entrada y tamaños, y el máximo de posiciones "
            "que abre a la vez esta cuenta o señal",
        ),
        "en": (
            None,
            "the list of trades with entry times and sizes, and the most positions this account "
            "or signal opens at once",
        ),
        "pt": (
            None,
            "a lista de operações com horas de entrada e tamanhos, e o máximo de posições que "
            "esta conta ou sinal abre ao mesmo tempo",
        ),
    },
    "recent_period": {
        "es": (
            None,
            "el historial de esta cuenta o señal en ese último tramo y la fecha de cualquier "
            "cambio de configuración",
        ),
        "en": (
            None,
            "this account or signal's history over that last stretch and the date of any change "
            "to its settings",
        ),
        "pt": (
            None,
            "o histórico desta conta ou sinal nesse último trecho e a data de qualquer mudança "
            "de configuração",
        ),
    },
}

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


def question_item(code: str, stored: str, locale: str, role: str, *, account: bool = False) -> str:
    """One stored question (``stored``, already in ``locale``) in ``role``'s voice.
    ``account``: asked of an account or signal, answered by its own history."""
    if role == BUYER:
        return stored
    answers = ACCOUNT_QUESTIONS if account and code in ACCOUNT_QUESTIONS else QUESTIONS
    entry = answers.get(code, {}).get(locale)
    template = QUESTION_ITEM.get(role, {}).get(locale)
    if entry is None or template is None:
        return stored
    ask, answer = entry
    return template.format(ask=ask or stored, answer=answer)


#: Red flags that leave the modelling question open although the tester report
#: states its mode: the mode is coarse, or the history's quality is low.
MODELLING_FLAGS: frozenset[str] = frozenset({"COARSE_TICK_MODEL", "TEST_DATA_QUALITY_LOW"})


def _modelling_code(data: Mapping[str, Any]) -> str | None:
    """Which wording the modelling question takes, or None when the files answer it."""
    review = data.get("test_data") or {}
    if review.get("status") != "MEASURED":
        return "modelling"  # not a tester report: the tester's HTML would answer it
    flags = {
        str(flag.get("code")) for flag in data.get("red_flags") or [] if isinstance(flag, Mapping)
    }
    if flags & MODELLING_FLAGS:
        return "modelling_flagged"
    if (review.get("tick_model") or {}).get("evidence") == "NOT_MEASURED":
        return "modelling_unread"
    return None  # the report states its mode; its test-data section shows it


def open_questions(data: Mapping[str, Any] | None, role: str) -> list[dict[str, str]]:
    """The stored questions (``vendor_questions``) as ``role`` reads them.

    The buyer's list stays as stored: the questions are for the seller, who
    can confirm what the header says. Every other voice lists what the files
    do not answer yet, so the modelling question, asked of every backtest,
    goes when the uploaded tester report already states a mode we recognise,
    asks about a rerun when a red flag says the mode or the quality falls
    short, and asks for a report that prints the mode when the uploaded one
    prints none we recognise. Copies; the stored result is unchanged."""
    questions = [dict(q) for q in (data or {}).get("vendor_questions") or []]
    if role == BUYER or data is None:
        return questions
    out: list[dict[str, str]] = []
    for question in questions:
        if question.get("code") == "modelling":
            code = _modelling_code(data)
            if code is None:
                continue
            question["code"] = code
        out.append(question)
    return out


def trials_step(dimension: Mapping[str, Any] | None, role: str) -> str:
    """The "What to do now" key for a weak or failed multiplicity in ``role``'s voice.

    Cutting trials only helps when more than one was counted or declared: an
    undeclared count was taken at 1, the most favourable case."""
    trials = ((dimension or {}).get("inputs") or {}).get("trials_used") or {}
    if trials.get("evidence") == "NOT_MEASURED":
        return "next_trials_undeclared" if role in (OWN, NEUTRAL) else "next_trials"
    value = trials.get("value")
    if role == OWN and isinstance(value, (int, float)) and value <= 1:
        return "next_trials_one"
    return "next_trials"


def oos_step(status: str, data: Mapping[str, Any], role: str) -> str:
    """The "What to do now" key for the out-of-sample test in ``role``'s voice.

    Only a declared start measures it (``engine._holdout``); a forward export
    has its own section (``forward.py``). Once the declared stretch has been
    measured and fell short, it has been seen."""
    if role != OWN:
        return "next_oos"
    if status in ("WEAK", "FAIL"):
        return "next_oos_seen"
    if (data.get("forward") or {}).get("status") == "MEASURED":
        return "next_oos_forward"
    return "next_oos"


def demo_step(data: Mapping[str, Any], role: str) -> str | None:
    """The developer's demo step of "What to do now", or None.

    Only the client's own robot with a trade list and no measured live
    comparison. ``live.compare_live`` needs ``MIN_BACKTEST_TRADES`` closed
    trades in the backtest and ``MIN_LIVE_TRADES`` in the account, so a
    shorter backtest gets the wording that names both."""
    if role != OWN:
        return None
    stats = data.get("trade_stats") or {}
    if stats.get("status") != "MEASURED" or (data.get("live") or {}).get("status") == "MEASURED":
        return None
    count = (stats.get("trade_count") or {}).get("value")
    if not isinstance(count, (int, float)) or count < MIN_BACKTEST_TRADES:
        return "next_demo_short"
    return "next_demo"


__all__ = [
    "ACCOUNT_QUESTIONS",
    "BUYER",
    "FORM",
    "LABELS",
    "LOCKED_GAINS",
    "MEANING",
    "MODELLING_FLAGS",
    "NEUTRAL",
    "OWN",
    "PLAN",
    "PROVIDER",
    "QUESTIONS",
    "ROLES",
    "VOICES",
    "Voiced",
    "choice_label",
    "demo_step",
    "gains_for",
    "labels_for",
    "meaning",
    "oos_step",
    "open_questions",
    "plan_text",
    "question_item",
    "role_of",
    "trials_step",
]
