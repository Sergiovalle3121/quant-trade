"""A concrete checklist for the signal audience, using the public calculators.

All example inputs are declarations, never a reconstructed account. Flag
thresholds come from the report rules; this page introduces no new rule.
"""

from __future__ import annotations

from html import escape

from quant_trade.audit.audience_numbers import (
    reader_values,
    signal_copier_example,
    signal_copier_values,
)
from quant_trade.audit.calculator import calculator_url
from quant_trade.audit.guides import guide_url
from quant_trade.audit.reading import reading_url
from quant_trade.audit.ruin_calc import share_url
from quant_trade.audit.seller_message import COPY as SELLER_COPY
from quant_trade.audit.winrate import winrate_url

# Each check names a numeric comparison and the existing tool that supplies it.
# Evidence codes only open a sentence or stay in attributes: inside a sentence
# the report's localizer would print them capitalised and without agreement.
CHECKS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "es": (
        (
            "Meses frente a la suerte: Sharpe deflactado",
            "Los {months} meses declarados quedan por debajo de los {luck_months} meses "
            "que, como supuesto declarado aparte (Sharpe anual {sharpe}, {trials} "
            "configuraciones), harían falta para que el máximo esperado por azar quede "
            "debajo de ese Sharpe. La calculadora supone retornos diarios normales e "
            "independientes ({luck_frequency}/año) y búsquedas independientes; no fija "
            "un nivel de Sharpe deflactado. El informe calcula el Sharpe deflactado con "
            "los retornos del archivo; sin Sharpe y búsquedas no puedes hacer esa "
            "comparación.",
            "luck",
        ),
        (
            "Aciertos con intervalo y número de operaciones",
            "DECLARED: {rate} en {trades} operaciones da un intervalo Wilson al 95 % de "
            "{wilson_low} a {wilson_high}. Compara su extremo inferior con el acierto de "
            "equilibrio según ganancia y pérdida medias, antes de costos; revisa los "
            "costos aparte. El porcentaje solo "
            "no dice cuánto se pierde al fallar.",
            "winrate",
        ),
        (
            "Drawdown y flotante oculto",
            "DECLARED: un drawdown de {drawdown} no incluye necesariamente pérdidas "
            "abiertas. Compara saldo y equity y pide el flotante. El informe muestra la "
            "bandera de drawdown flotante oculto si la curva solo recoge cierres y hubo "
            "posiciones solapadas en el mismo instrumento; su regla de pérdida flotante "
            "al cierre avisa desde "
            "{floating_warn} del saldo. Sin esos datos, el flotante queda sin medir.",
            "audit",
        ),
        (
            "Ganancia en porcentaje frente a depósitos",
            "Compara el porcentaje ajustado por flujos con el resultado monetario dividido "
            "entre depósitos. La regla del informe señala ganancia inflada por flujos desde "
            "{inflated_min_gain} si el resultado monetario no es positivo o el resultado "
            "sobre depósitos es menor que un tercio (≈ {inflated_share}) de ese porcentaje. "
            "También señala recargas con drawdown de al menos {top_up_drawdown}. Un depósito no es "
            "resultado de operar; hacen falta fechas, depósitos y retiros.",
            "audit",
        ),
        (
            "Martingala y grid: tamaño después de perder",
            "La bandera de martingala compara la mediana del tamaño tras perder con la "
            "mediana tras ganar: avisa desde {martingale_ratio} veces, con al menos "
            "{martingale_min} casos de cada grupo. La de grid avisa desde {grid_min} "
            "entradas adicionales a peor precio y {grid_share} de las operaciones, con "
            "una posición previa abierta en el mismo instrumento y dirección. Pide "
            "tamaños, dirección, precios y fechas; son señales de revisión, no un diagnóstico.",
            "audit",
        ),
        (
            "Ruina al tamaño que copiarías",
            "Introduce el acierto declarado con sus {trades} operaciones, tu ganancia y "
            "pérdida medias al tamaño de copia, el horizonte y el límite que quieres estudiar: "
            "perder {ruin_limit} del saldo inicial en este ejemplo declarado. El enlace "
            "abre la calculadora con estas cifras y muestra tanto el cálculo con {rate} "
            "como el del extremo inferior de Wilson, {wilson_low}; sin las operaciones no "
            "hay intervalo. Cambiar tamaño cambia el resultado; el drawdown pasado no es "
            "un techo para pérdidas futuras.",
            "ruin",
        ),
        (
            "Qué pedirle al proveedor",
            "Usa el «{seller}» que incluye el informe y pide que cada cifra tenga su "
            "archivo de origen. Para este ejemplo declarado: «Envía el historial completo "
            "de los {months} meses y las {trades} operaciones, con tamaños, costos, "
            "depósitos y retiros; la equity con posiciones abiertas, el tamaño máximo y "
            "las cuentas cerradas o reiniciadas». Lo que no entregue queda sin medir.",
            "sample",
        ),
    ),
    "en": (
        (
            "Months of history against luck: deflated Sharpe",
            "The declared {months} months fall short of the {luck_months} months that, as "
            "a separate declared assumption (annual Sharpe {sharpe}, {trials} "
            "configurations), would be needed for the expected random maximum to fall "
            "below that Sharpe. The calculator assumes normal, independent daily returns "
            "({luck_frequency}/year) and independent searches; it does not set a deflated "
            "Sharpe level. The report computes deflated Sharpe from the file's returns; "
            "without Sharpe and search count you cannot make that comparison.",
            "luck",
        ),
        (
            "Win rate with its interval and trade count",
            "DECLARED: {rate} across {trades} trades gives a 95 % Wilson interval of "
            "{wilson_low} to {wilson_high}. Compare its lower end with the break-even "
            "win rate for the average win and loss, before costs; review costs separately. "
            "The percentage alone "
            "does not tell you how much a losing trade costs.",
            "winrate",
        ),
        (
            "Drawdown and hidden floating losses",
            "DECLARED: {drawdown} drawdown need not include open losses. Compare balance "
            "and equity and ask for floating P&L. The report flags hidden floating drawdown "
            "when the curve records only closed trades and positions on the same "
            "instrument overlapped; its "
            "end-of-statement floating-loss rule warns from {floating_warn} of balance. "
            "Without those data, floating P&L stays unmeasured.",
            "audit",
        ),
        (
            "Percentage gain against deposits",
            "Compare flow-adjusted gain with the monetary trading result divided by "
            "deposits. The report's inflated-gain rule starts at {inflated_min_gain} when "
            "the monetary result is nonpositive or the result on deposits is less than "
            "one third (≈ {inflated_share}) of that percentage. It also flags top-ups at "
            "a drawdown of at least {top_up_drawdown}. A deposit is not a trading result; "
            "dates, deposits and withdrawals are needed.",
            "audit",
        ),
        (
            "Martingale and grid: size after a loss",
            "The martingale flag compares median size after losses with median size after "
            "wins: it warns from {martingale_ratio} times, with at least {martingale_min} "
            "cases in each group. The grid flag warns from {grid_min} additional entries "
            "at worse prices and {grid_share} of trades, with an earlier position still "
            "open in the same instrument and direction. Ask for sizes, direction, prices "
            "and dates; these are prompts for review, not a diagnosis.",
            "audit",
        ),
        (
            "Ruin at the size you would copy",
            "Enter the declared win rate with its {trades} trades, your average win and loss at "
            "the copy size, the horizon and the limit you want to study: losing "
            "{ruin_limit} of initial balance in this declared example. The link opens the "
            "calculator with these figures and shows both the calculation at {rate} and "
            "the one at Wilson's lower end, {wilson_low}; without the trade count there is "
            "no interval. Changing size changes the result; past drawdown is not a "
            "ceiling on future losses.",
            "ruin",
        ),
        (
            "What to ask the provider",
            "Use the report's ‘{seller}’ and ask for a source file behind each "
            "figure. For this declared example: ‘Send the complete {months}-month history "
            "and {trades} trades with sizes, costs, deposits and withdrawals; equity with "
            "open positions, maximum size, and closed or restarted accounts.’ Anything "
            "not supplied remains unmeasured.",
            "sample",
        ),
    ),
    "pt": (
        (
            "Meses de histórico contra a sorte: Sharpe deflacionado",
            "Os {months} meses declarados ficam abaixo dos {luck_months} meses que, como "
            "hipótese declarada separada (Sharpe anual {sharpe}, {trials} configurações), "
            "seriam necessários para que o máximo esperado por acaso fique abaixo desse "
            "Sharpe. A calculadora supõe retornos diários normais e independentes "
            "({luck_frequency}/ano) e buscas independentes; não fixa um nível de Sharpe "
            "deflacionado. O relatório calcula o Sharpe deflacionado com os retornos do "
            "arquivo; sem Sharpe e número de buscas não é possível fazer essa comparação.",
            "luck",
        ),
        (
            "Acertos com intervalo e número de operações",
            "DECLARED: {rate} em {trades} operações dá um intervalo Wilson de 95 % de "
            "{wilson_low} a {wilson_high}. Compare o extremo inferior com a taxa de "
            "equilíbrio para ganho e perda médios, antes dos custos; revise os custos "
            "separadamente. A porcentagem sozinha "
            "não diz quanto custa errar.",
            "winrate",
        ),
        (
            "Drawdown e perdas flutuantes ocultas",
            "DECLARED: um drawdown de {drawdown} não inclui necessariamente perdas "
            "abertas. Compare saldo e equity e peça o resultado flutuante. O relatório "
            "sinaliza drawdown flutuante oculto quando a curva só registra operações "
            "fechadas e houve posições sobrepostas no mesmo instrumento; sua regra de "
            "perda flutuante no fim "
            "do extrato alerta a partir de {floating_warn} do saldo. Sem esses dados, "
            "o resultado flutuante fica sem medir.",
            "audit",
        ),
        (
            "Ganho em porcentagem contra depósitos",
            "Compare o ganho ajustado por fluxos com o resultado monetário dividido pelos "
            "depósitos. A regra do relatório sinaliza ganho inflado a partir de "
            "{inflated_min_gain} se o resultado monetário não é positivo ou o resultado "
            "sobre depósitos é menor que um terço (≈ {inflated_share}) dessa porcentagem. Também "
            "sinaliza recargas com drawdown de pelo menos {top_up_drawdown}. Depósito não "
            "é resultado de operações; são necessárias datas, depósitos e saques.",
            "audit",
        ),
        (
            "Martingale e grid: tamanho após perder",
            "A bandeira de martingale compara a mediana do tamanho após perder com a "
            "mediana após ganhar: alerta a partir de {martingale_ratio} vezes, com pelo "
            "menos {martingale_min} casos em cada grupo. A de grid alerta a partir de "
            "{grid_min} entradas adicionais a preços piores e {grid_share} das operações, "
            "com uma posição anterior aberta no mesmo instrumento e direção. "
            "Peça tamanhos, direção, preços e datas; são indícios para revisão, não um "
            "diagnóstico.",
            "audit",
        ),
        (
            "Ruína no tamanho que você copiaria",
            "Informe a taxa de acerto declarada com as {trades} operações, seu ganho e "
            "perda médios no tamanho de cópia, horizonte e limite que quer estudar: perder "
            "{ruin_limit} do saldo inicial neste exemplo declarado. O link abre a "
            "calculadora com esses números e mostra tanto o cálculo com {rate} quanto o "
            "do extremo inferior de Wilson, {wilson_low}; sem as operações não há "
            "intervalo. Mudar o tamanho muda o resultado; o drawdown passado não é um "
            "teto para perdas futuras.",
            "ruin",
        ),
        (
            "O que pedir ao fornecedor",
            "Use a ‘{seller}’ do relatório e peça o arquivo de origem de cada "
            "número. Para este exemplo declarado: ‘Envie o histórico completo dos "
            "{months} meses e das {trades} operações, com tamanhos, custos, depósitos e "
            "saques; a equity com posições abertas, o tamanho máximo e as contas "
            "encerradas ou reiniciadas.’ O que não for enviado fica sem medir.",
            "sample",
        ),
    ),
}

COPY: dict[str, dict[str, str]] = {
    "es": {
        "intro": (
            "Para elegir qué historial revisar, contrasta estas cifras y pide los datos que "
            "faltan. Ninguna lista elimina la posibilidad de perder la cuenta. Los umbrales "
            "del informe indican qué revisar; no son límites de seguridad."
        ),
        "free": (
            "Calculadoras, lector y ejemplo: gratis sin registro. Para calcular las banderas "
            "sobre tu archivo, el primer informe completo es gratis al crear tu cuenta."
        ),
        "luck": "Calculadora de suerte gratis",
        "winrate": "Calculadora de aciertos gratis",
        "audit": "Primer informe gratis con cuenta",
        "ruin": "Calculadora de ruina gratis",
        "sample": "Ejemplo de señal y mensaje para el vendedor",
        "example_title": "Ejemplo: aciertos, ganancia declarada y tamaño de copia",
        "declared": "Declarado: ejemplo hipotético, sin archivo de un proveedor.",
        "inputs": (
            "El anuncio dice «{rate} de aciertos y {trades} operaciones» y «{gain} en "
            "{months} meses con drawdown {drawdown}». Todas las entradas y salidas de este "
            "ejemplo se calculan a partir de declaraciones, no de una cuenta medida."
        ),
        "wilson": (
            "Wilson al 95 %: {wilson_low}–{wilson_high}. La muestra no fija la tasa "
            "futura; presupone operaciones independientes y el porcentaje puede estar redondeado."
        ),
        "ruin_result": (
            "Ruina a {ruin_limit}: hace falta el tamaño, no basta con el acierto. Supón "
            "ganancia media +{win} y pérdida media −{loss} del saldo inicial, fijas, y "
            "{horizon} operaciones futuras. En {samples} trayectorias, {ruin} toca una "
            "pérdida de {ruin_limit} del saldo inicial; con {wilson_low} de aciertos, lo "
            "hace {ruin_low}. Son frecuencias de simulación bajo esos supuestos, no una "
            "probabilidad observada del proveedor ni un intervalo de confianza para la ruina."
        ),
        "breakeven": (
            "Con +{win}/−{loss}, el acierto de equilibrio antes de costos es {breakeven}: "
            "el {rate} declarado queda por encima ({expectancy} por operación) y el "
            "{wilson_low} queda por debajo ({expectancy_low}); por eso la frecuencia de "
            "ruina pasa de {ruin} a {ruin_low}."
        ),
        "model": (
            "El tamaño es un supuesto aparte: no reconstruye el {gain}. El modelo usa "
            "operaciones independientes, importes fijos, sin capitalización ni costos "
            "adicionales; no reproduce martingala, gaps ni pérdidas agrupadas. El límite "
            "parte del saldo inicial, no del máximo de la curva."
        ),
        "reader": (
            "El lector reproduce el intervalo Wilson con {trades} y {rate}; el enlace ya "
            "lleva los {months} meses como {years} años. Ganancia y drawdown no son campos "
            "de esta versión. Con {trades} operaciones el lector también muestra el mejor "
            "acierto esperado de monedas justas ({coin}); el Sharpe anual esperado por "
            "suerte queda sin medir porque falta el número de configuraciones. {gain} y "
            "{drawdown} no permiten deducirlo ni detectar flujos o flotante; pide el "
            "historial."
        ),
        "reading": "Abrir el lector de cifras gratis",
        "guides": "Qué exportar:",
    },
    "en": {
        "intro": (
            "To choose which history to examine, compare these figures and request the "
            "missing data. No checklist removes the possibility of losing the account. "
            "Report thresholds indicate what to review; they are not safety limits."
        ),
        "free": (
            "Calculators, reader and sample: free without signup. To compute flags on your "
            "file, your first full report is free when you create an account."
        ),
        "luck": "Free luck calculator",
        "winrate": "Free win-rate calculator",
        "audit": "First report free with an account",
        "ruin": "Free risk-of-ruin calculator",
        "sample": "Signal sample and message for the seller",
        "example_title": "Example: win rate, declared gain and copy size",
        "declared": "Declared: a hypothetical example, without a provider's file.",
        "inputs": (
            "The advert says ‘{rate} wins and {trades} trades’ and ‘{gain} in {months} "
            "months with {drawdown} drawdown’. All inputs and outputs in this example "
            "come from declarations, not a measured account."
        ),
        "wilson": (
            "95 % Wilson interval: {wilson_low}–{wilson_high}. The sample does not fix "
            "the future rate; it assumes independent trades and the percentage may be rounded."
        ),
        "ruin_result": (
            "Ruin at {ruin_limit}: size is needed, win rate alone is insufficient. Assume "
            "an average win of +{win} and average loss of −{loss} of initial balance, "
            "fixed, over {horizon} future trades. Across {samples} paths, {ruin} touches "
            "a loss of {ruin_limit} of initial balance; at a {wilson_low} win rate, "
            "{ruin_low} does. These are simulation frequencies under those assumptions, "
            "not an observed probability for the provider or a confidence interval for ruin."
        ),
        "breakeven": (
            "With +{win}/−{loss}, the break-even win rate before costs is {breakeven}: "
            "the declared {rate} sits above it ({expectancy} per trade) and {wilson_low} "
            "sits below it ({expectancy_low}); that is why the ruin frequency moves from "
            "{ruin} to {ruin_low}."
        ),
        "model": (
            "Size is a separate assumption: it does not reconstruct the {gain}. The model "
            "uses independent trades, fixed amounts, no compounding or additional costs; "
            "it does not reproduce martingale, gaps or clustered losses. The threshold "
            "starts from initial balance, not the curve's peak."
        ),
        "reader": (
            "The reader reproduces the Wilson interval with {trades} and {rate}; the link "
            "already carries the {months} months as {years} years. Gain and drawdown are "
            "not fields in this version. With {trades} trades the reader also shows the "
            "best expected result of fair coins ({coin}); the expected annual Sharpe from "
            "luck stays unmeasured because the number of configurations is missing. "
            "{gain} and {drawdown} cannot supply it or detect flows or floating losses; "
            "ask for the history."
        ),
        "reading": "Open the free figure reader",
        "guides": "What to export:",
    },
    "pt": {
        "intro": (
            "Para escolher qual histórico examinar, compare estes números e peça os dados "
            "que faltam. Nenhuma lista elimina a possibilidade de perder a conta. Os limites "
            "do relatório indicam o que revisar; não são limites de segurança."
        ),
        "free": (
            "Calculadoras, leitor e exemplo: grátis sem cadastro. Para calcular as bandeiras "
            "no seu arquivo, o primeiro relatório completo é grátis ao criar sua conta."
        ),
        "luck": "Calculadora de sorte grátis",
        "winrate": "Calculadora de acertos grátis",
        "audit": "Primeiro relatório grátis com conta",
        "ruin": "Calculadora de ruína grátis",
        "sample": "Exemplo de sinal e mensagem para o vendedor",
        "example_title": "Exemplo: acertos, ganho declarado e tamanho de cópia",
        "declared": "Declarado: exemplo hipotético, sem arquivo de um fornecedor.",
        "inputs": (
            "O anúncio diz ‘{rate} de acertos e {trades} operações’ e ‘{gain} em {months} "
            "meses com drawdown {drawdown}’. Todas as entradas e saídas deste exemplo "
            "vêm de declarações, não de uma conta medida."
        ),
        "wilson": (
            "Intervalo Wilson de 95 %: {wilson_low}–{wilson_high}. A amostra não fixa "
            "a taxa futura; pressupõe operações independentes e a taxa pode estar arredondada."
        ),
        "ruin_result": (
            "Ruína a {ruin_limit}: é necessário o tamanho, só a taxa de acerto não basta. "
            "Suponha ganho médio +{win} e perda média −{loss} do saldo inicial, fixos, em "
            "{horizon} operações futuras. Em {samples} trajetórias, {ruin} toca uma perda "
            "de {ruin_limit} do saldo inicial; com {wilson_low} de acertos, {ruin_low} "
            "toca esse limite. São frequências de simulação sob essas hipóteses, não uma "
            "probabilidade observada do fornecedor nem um intervalo de confiança para ruína."
        ),
        "breakeven": (
            "Com +{win}/−{loss}, a taxa de acerto de equilíbrio antes dos custos é "
            "{breakeven}: os {rate} declarados ficam acima ({expectancy} por operação) e "
            "{wilson_low} fica abaixo ({expectancy_low}); por isso a frequência de ruína "
            "passa de {ruin} a {ruin_low}."
        ),
        "model": (
            "O tamanho é uma hipótese separada: não reconstrói o {gain}. O modelo usa "
            "operações independentes, valores fixos, sem capitalização nem custos adicionais; "
            "não reproduz martingale, gaps nem perdas agrupadas. O limite parte do saldo "
            "inicial, não do pico da curva."
        ),
        "reader": (
            "O leitor reproduz o intervalo Wilson com {trades} e {rate}; o link já leva "
            "os {months} meses como {years} anos. Ganho e drawdown não são campos desta "
            "versão. Com {trades} operações o leitor também mostra o melhor resultado "
            "esperado de moedas justas ({coin}); o Sharpe anual esperado por sorte fica "
            "sem medir porque falta o número de configurações. {gain} e {drawdown} não "
            "permitem deduzi-lo nem detectar fluxos ou perdas flutuantes; peça o "
            "histórico."
        ),
        "reading": "Abrir o leitor de números grátis",
        "guides": "O que exportar:",
    },
}


def checklist_sections(
    locale: str, question: str, *, audit_url: str, sample_url: str
) -> list[tuple[str, str]]:
    """Two normal audience sections, escaped like the surrounding document."""
    words = COPY[locale]
    figures = signal_copier_values(locale)
    # The sample's own section title, so the check names what the visitor will find.
    seller = SELLER_COPY[locale]["title"]
    urls = {
        "luck": calculator_url(locale),
        "winrate": winrate_url(locale),
        "audit": audit_url,
        # Pre-filled with the example, so the page opens on Wilson's lower-end twin.
        "ruin": share_url(locale, signal_copier_example().ruin_input),
        "sample": sample_url,
    }
    checks = "".join(
        f"<li><h3>{escape(title)}</h3><p>{escape(body.format(**figures, seller=seller))} "
        f"<a href='{escape(urls[tool], quote=True)}'>{escape(words[tool])}</a>.</p></li>"
        for title, body, tool in CHECKS[locale]
    )
    checklist = (
        f"<p>{escape(words['intro'])}</p><p>{escape(words['free'])}</p>"
        f"<ol data-signal-checklist>{checks}</ol>"
    )
    example = (
        "<div data-signal-example data-evidence='DECLARED'>"
        f"<p><strong>{escape(words['declared'])}</strong></p>"
        + "".join(
            f"<p>{escape(words[key].format(**figures))}</p>"
            for key in ("inputs", "wilson", "ruin_result", "breakeven", "model", "reader")
        )
        # The reader opens on the example's own fields, as the paragraph describes.
        + f"<p><a href='{escape(reading_url(locale, reader_values()), quote=True)}'>"
        f"{escape(words['reading'])}</a>.</p>"
        + f"<p>{escape(words['guides'])} "
        + " · ".join(
            f"<a href='{escape(guide_url(slug, locale))}'>{label}</a>"
            for slug, label in (("myfxbook", "Myfxbook"), ("mql5-signal", "MQL5"))
        )
        + ".</p></div>"
    )
    return [(question, checklist), (words["example_title"], example)]
