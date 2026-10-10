"""The futures firms' pages of the challenge calculator: their words, as data.

Seven futures firms read on 2026-10-10 (``prop_presets.FUTURES_AS_OF``): Take
Profit Trader, MyFundedFutures, Tradeify, Bulenox, Earn2Trade, Alpha Futures
and Lucid Trading. ``challenge_calc`` adds them to ``FIRMS`` and ``FIRM_COPY``
after the firms it already had, in the order the presets list them, so their
pages are built like every other firm's (``challenge_pages.challenge_page``).

The ``faq`` answers are templates, as ``challenge_calc.FIRM_COPY``'s are:
``{rules[key]}``, ``{daily[key]}``, ``{field[key.name]}``, ``{accounts}``,
``{horizon}`` and ``{as_of}`` are filled from the presets, and the few dollar
figures and clock times written out are in that program's notes, which a test
checks.
"""

from __future__ import annotations

from typing import Any

#: Each futures firm's page: its path segment and its name in ``prop_presets``.
FUTURES_FIRMS: dict[str, str] = {
    "take-profit-trader": "Take Profit Trader",
    "myfundedfutures": "MyFundedFutures",
    "tradeify": "Tradeify",
    "bulenox": "Bulenox",
    "earn2trade": "Earn2Trade",
    "alpha-futures": "Alpha Futures",
    "lucid-trading": "Lucid Trading",
}

_TPT = "take-profit-trader-test-50k"
_MFF_RAPID_EOD = "myfundedfutures-rapid-eod-50k"
_MFF_RAPID = "myfundedfutures-rapid-50k"
_MFF_PRO = "myfundedfutures-pro-50k"
_MFF_BUILDER = "myfundedfutures-builder-50k"
_TRADEIFY_SELECT = "tradeify-select-50k"
_TRADEIFY_GROWTH = "tradeify-growth-50k"
_BULENOX_QUALIFICATION = "bulenox-qualification-eod-50k"
_BULENOX_MOMENTUM = "bulenox-momentum-eod-50k"
_E2T_TCP = "earn2trade-tcp-25k"
_E2T_GAUNTLET = "earn2trade-gauntlet-mini-50k"
_ALPHA_ZERO = "alpha-futures-zero-50k"
_ALPHA_STANDARD = "alpha-futures-standard-50k"
_ALPHA_ADVANCED = "alpha-futures-advanced-50k"
_LUCID_PRO = "lucid-pro-50k"


def _lead(firm: str, locale: str) -> str:
    """The lead every firm page shares, with the firm's name."""
    return {
        "es": (
            f"La calculadora de reto con las reglas publicadas de {firm}: escribe tu % de "
            "aciertos, tu ganancia y tu pérdida medias y tus operaciones por día. Rigor no está "
            f"afiliado a {firm}."
        ),
        "en": (
            f"The challenge calculator with {firm}'s published rules: enter your win rate, your "
            f"average win and loss and your trades per day. Rigor is not affiliated with {firm}."
        ),
        "pt": (
            f"A calculadora de desafio com as regras publicadas da {firm}: digite a sua taxa de "
            "acerto, o seu ganho e a sua perda médios e as suas operações por dia. O Rigor não é "
            f"afiliado à {firm}."
        ),
    }[locale]


FUTURES_FIRM_COPY: dict[str, dict[str, dict[str, Any]]] = {
    "take-profit-trader": {
        "es": {
            "title": "Calculadora del Trading Test de Take Profit Trader",
            "seo_title": "Calculadora del Trading Test de Take Profit Trader",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a Take Profit Trader: frecuencia "
                "de alcanzar el objetivo del Trading Test 50K o de tocar su drawdown trailing."
            ),
            "lead": _lead("Take Profit Trader", "es"),
            "faq": (
                (
                    "¿Qué objetivo y qué límites tiene el Trading Test 50K de Take Profit Trader?",
                    "Según el centro de ayuda de Take Profit Trader leído el {as_of}: "
                    f"{{rules[{_TPT}]}}. En la cuenta de USD 50.000 son USD 3.000 de objetivo y "
                    "USD 2.000 de pérdida máxima.",
                ),
                (
                    "¿Cómo funciona el drawdown trailing al cierre del día de Take Profit Trader?",
                    "Según la regla del drawdown leída el {as_of}, el balance mínimo sube con el "
                    "mayor balance de cierre del día y se detiene al llegar al balance inicial. La "
                    "cuenta se cierra si el balance lo toca en cualquier momento, también con "
                    "pérdidas abiertas; la calculadora solo mira cierres diarios, así que frente a "
                    "esa regla es optimista.",
                ),
                (
                    "¿Cómo trata la calculadora la regla de consistencia de Take Profit Trader?",
                    "Según el centro de ayuda leído el {as_of}, el mejor día debe quedar por "
                    f"debajo del {{field[{_TPT}.best_day_limit]}} de la ganancia neta total y el "
                    f"Test pide al menos {{field[{_TPT}.min_trading_days]}} días de trading; un "
                    "mejor día por encima sube el objetivo en lugar de terminar el Test. La "
                    "calculadora compara el mejor día con el objetivo cuando una trayectoria lo "
                    "alcanza, que es más estricto, y lo muestra como «dentro de la regla del "
                    "mejor día».",
                ),
                (
                    "¿Puedo usar un robot o mantener posiciones de noche en Take Profit Trader?",
                    "Según las políticas leídas el {as_of}, no: los bots, los algoritmos y la "
                    "ejecución automática están prohibidos también en el Test, y ninguna posición "
                    "puede quedar abierta para el día de trading siguiente (todas se cierran "
                    "antes de las 4:55 PM ET). La calculadora da cifras con tus números "
                    "declarados, pero una estrategia automática o que mantiene posiciones de "
                    "noche no se puede operar ahí tal cual.",
                ),
            ),
        },
        "en": {
            "title": "Take Profit Trader Trading Test calculator",
            "seo_title": "Take Profit Trader Trading Test calculator",
            "summary": (
                "Free, independent calculator, not affiliated with Take Profit Trader: how often "
                "you would reach the Trading Test 50K target or hit its trailing drawdown."
            ),
            "lead": _lead("Take Profit Trader", "en"),
            "faq": (
                (
                    "What target and limits does the Take Profit Trader Trading Test 50K have?",
                    "According to the Take Profit Trader help center read on {as_of}: "
                    f"{{rules[{_TPT}]}}. On the USD 50,000 account that is a USD 3,000 target "
                    "and a USD 2,000 maximum loss.",
                ),
                (
                    "How does the Take Profit Trader end-of-day trailing drawdown work?",
                    "According to the drawdown rule read on {as_of}, the minimum balance follows "
                    "the highest end-of-day balance up and stops once it reaches the starting "
                    "balance. The account is closed if the balance touches it at any moment, "
                    "open losses included; the calculator only checks daily closes, so it is "
                    "optimistic against that rule.",
                ),
                (
                    "How does the calculator treat the Take Profit Trader consistency rule?",
                    "According to the help center read on {as_of}, the best day must stay below "
                    f"{{field[{_TPT}.best_day_limit]}} of the total net profit and the Test asks "
                    f"for at least {{field[{_TPT}.min_trading_days]}} trading days; a best day "
                    "above it raises the target instead of ending the Test. The calculator "
                    "compares the best day with the profit target when a path reaches it, the "
                    "stricter reading, and shows it as within the best-day rule.",
                ),
                (
                    "Can I trade a bot or hold positions overnight at Take Profit Trader?",
                    "According to the policies read on {as_of}, no: bots, algorithms and "
                    "automated execution are prohibited on Test accounts too, and no position may "
                    "be held into the next trading day (every position is closed by 4:55 PM ET). "
                    "The calculator gives figures for your declared numbers, but an automated or "
                    "overnight strategy cannot be traded there as it is.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do Trading Test da Take Profit Trader",
            "seo_title": "Calculadora do Trading Test da Take Profit Trader",
            "summary": (
                "Calculadora grátis e independente, não afiliada à Take Profit Trader: frequência "
                "de atingir a meta do Trading Test 50K ou de tocar o drawdown trailing."
            ),
            "lead": _lead("Take Profit Trader", "pt"),
            "faq": (
                (
                    "Que meta e que limites tem o Trading Test 50K da Take Profit Trader?",
                    "Segundo a central de ajuda da Take Profit Trader lida em {as_of}: "
                    f"{{rules[{_TPT}]}}. Na conta de USD 50.000 são USD 3.000 de meta e USD 2.000 "
                    "de perda máxima.",
                ),
                (
                    "Como funciona o drawdown trailing de fim do dia da Take Profit Trader?",
                    "Segundo a regra do drawdown lida em {as_of}, o saldo mínimo sobe com o maior "
                    "saldo de fechamento do dia e para ao chegar ao saldo inicial. A conta é "
                    "encerrada se o saldo o tocar a qualquer momento, também com perdas abertas; "
                    "a calculadora só olha fechamentos diários, então é otimista diante dessa "
                    "regra.",
                ),
                (
                    "Como a calculadora trata a regra de consistência da Take Profit Trader?",
                    "Segundo a central de ajuda lida em {as_of}, o melhor dia deve ficar abaixo "
                    f"de {{field[{_TPT}.best_day_limit]}} do lucro líquido total e o Test pede "
                    f"pelo menos {{field[{_TPT}.min_trading_days]}} dias de trading; um melhor "
                    "dia acima disso eleva a meta em vez de encerrar o Test. A calculadora "
                    "compara o melhor dia com a meta quando uma trajetória a atinge, a leitura "
                    "mais estrita, e mostra como «dentro da regra do melhor dia».",
                ),
                (
                    "Posso usar um robô ou manter posições de um dia para o outro na Take Profit "
                    "Trader?",
                    "Segundo as políticas lidas em {as_of}, não: bots, algoritmos e execução "
                    "automática são proibidos também no Test, e nenhuma posição pode ficar aberta "
                    "para o dia de trading seguinte (todas são fechadas até as 4:55 PM ET). A "
                    "calculadora dá números com os seus dados declarados, mas uma estratégia "
                    "automática ou que mantém posições de um dia para o outro não pode ser "
                    "operada lá do jeito que está.",
                ),
            ),
        },
    },
    "myfundedfutures": {
        "es": {
            "title": "Calculadora del reto MyFundedFutures",
            "seo_title": "Calculadora de MyFundedFutures: Rapid, Pro y Builder",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a MyFundedFutures: frecuencia de "
                "alcanzar el objetivo de Rapid, Pro o Builder 50K o de tocar su pérdida máxima."
            ),
            "lead": _lead("MyFundedFutures", "es"),
            "faq": (
                (
                    "¿Qué objetivo y qué límites tienen Rapid EOD 50K y Rapid 50K de "
                    "MyFundedFutures?",
                    "Según el centro de ayuda de MyFundedFutures leído el {as_of}, Rapid EOD 50K: "
                    f"{{rules[{_MFF_RAPID_EOD}]}}. Rapid 50K: {{rules[{_MFF_RAPID}]}}. En la "
                    "cuenta de USD 50.000 los dos tienen USD 3.000 de objetivo y USD 2.000 de "
                    "pérdida máxima.",
                ),
                (
                    "¿Qué reglas tienen Pro 50K y Builder 50K de MyFundedFutures?",
                    f"Según el centro de ayuda leído el {{as_of}}, Pro 50K: {{rules[{_MFF_PRO}]}}. "
                    f"Builder 50K: {{rules[{_MFF_BUILDER}]}}. El límite de pérdida diaria de "
                    "USD 1.000 de Builder solo pausa el día; la calculadora termina ahí la "
                    "trayectoria, que es más estricto.",
                ),
                (
                    "¿Por qué la calculadora no fija la pérdida máxima de MyFundedFutures en el "
                    "balance inicial más USD 100?",
                    "Según el centro de ayuda leído el {as_of}, la pérdida máxima sigue al mayor "
                    "balance de cierre diario y se fija en el balance inicial más USD 100, y otra "
                    "página sitúa ese bloqueo en la etapa Sim Funded. La calculadora la deja "
                    "seguir sin fijarse, la lectura más estricta de las dos. Además, una posición "
                    "abierta que lleva el balance por debajo del mínimo termina la evaluación, y "
                    "eso no se ve en cierres diarios.",
                ),
                (
                    "¿Qué reglas de MyFundedFutures no ve la calculadora?",
                    "Según las páginas leídas el {as_of}: las posiciones abiertas se cierran "
                    "solas a las 4:10 PM EST, así que ninguna se mantiene de un día a otro; una "
                    "cuenta sin operaciones durante 7 días naturales seguidos puede cerrarse; "
                    "cada plan limita sus contratos, y en Rapid EOD, Rapid y Pro la política de "
                    "noticias se contradice, mientras que en Builder se permite operar con "
                    "noticias. La regla de consistencia "
                    f"({{field[{_MFF_RAPID_EOD}.best_day_limit]}} en Rapid EOD 50K, "
                    f"{{field[{_MFF_RAPID}.best_day_limit]}} en Rapid 50K y Pro 50K) no termina "
                    "la cuenta: pide más días de trading.",
                ),
            ),
        },
        "en": {
            "title": "MyFundedFutures challenge calculator",
            "seo_title": "MyFundedFutures calculator: Rapid, Pro and Builder",
            "summary": (
                "Free, independent calculator, not affiliated with MyFundedFutures: how often you "
                "would reach the Rapid, Pro or Builder 50K target or hit its maximum loss."
            ),
            "lead": _lead("MyFundedFutures", "en"),
            "faq": (
                (
                    "What target and limits do the MyFundedFutures Rapid EOD 50K and Rapid 50K "
                    "have?",
                    "According to the MyFundedFutures help center read on {as_of}, Rapid EOD "
                    f"50K: {{rules[{_MFF_RAPID_EOD}]}}. Rapid 50K: {{rules[{_MFF_RAPID}]}}. On "
                    "the USD 50,000 account both have a USD 3,000 target and a USD 2,000 maximum "
                    "loss.",
                ),
                (
                    "What rules do the MyFundedFutures Pro 50K and Builder 50K have?",
                    f"According to the help center read on {{as_of}}, Pro 50K: "
                    f"{{rules[{_MFF_PRO}]}}. Builder 50K: {{rules[{_MFF_BUILDER}]}}. Builder's "
                    "USD 1,000 daily loss limit only pauses the day; the calculator ends the path "
                    "there, the stricter reading.",
                ),
                (
                    "Why does the calculator not lock the MyFundedFutures maximum loss at the "
                    "starting balance plus USD 100?",
                    "According to the help center read on {as_of}, the maximum loss trails the "
                    "highest end-of-day balance and locks at the starting balance plus USD 100, "
                    "and another page puts that lock in the Sim Funded stage. The calculator lets "
                    "it trail without locking, the stricter reading of both. An open position "
                    "that takes the balance below the minimum also ends the evaluation, which "
                    "daily closes cannot see.",
                ),
                (
                    "Which MyFundedFutures rules does the calculator not see?",
                    "According to the pages read on {as_of}: open positions are closed "
                    "automatically at 4:10 PM EST, so none are held overnight; an account with no "
                    "trade for 7 consecutive calendar days may be closed; each plan caps its "
                    "contracts; and on Rapid EOD, Rapid and Pro the news policy contradicts "
                    "itself, while Builder allows news trading. The consistency rule "
                    f"({{field[{_MFF_RAPID_EOD}.best_day_limit]}} on Rapid EOD 50K, "
                    f"{{field[{_MFF_RAPID}.best_day_limit]}} on Rapid 50K and Pro 50K) does not "
                    "end the account: it asks for more trading days.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do desafio MyFundedFutures",
            "seo_title": "Calculadora da MyFundedFutures: Rapid, Pro e Builder",
            "summary": (
                "Calculadora grátis e independente, não afiliada à MyFundedFutures: frequência de "
                "atingir a meta do Rapid, Pro ou Builder 50K ou de tocar a perda máxima."
            ),
            "lead": _lead("MyFundedFutures", "pt"),
            "faq": (
                (
                    "Que meta e que limites têm o Rapid EOD 50K e o Rapid 50K da MyFundedFutures?",
                    "Segundo a central de ajuda da MyFundedFutures lida em {as_of}, Rapid EOD "
                    f"50K: {{rules[{_MFF_RAPID_EOD}]}}. Rapid 50K: {{rules[{_MFF_RAPID}]}}. Na "
                    "conta de USD 50.000 os dois têm USD 3.000 de meta e USD 2.000 de perda "
                    "máxima.",
                ),
                (
                    "Que regras têm o Pro 50K e o Builder 50K da MyFundedFutures?",
                    "Segundo a central de ajuda lida em {as_of}, Pro 50K: "
                    f"{{rules[{_MFF_PRO}]}}. Builder 50K: {{rules[{_MFF_BUILDER}]}}. O limite de "
                    "perda diária de "
                    "USD 1.000 do Builder só pausa o dia; a calculadora encerra ali a trajetória, "
                    "a leitura mais estrita.",
                ),
                (
                    "Por que a calculadora não fixa a perda máxima da MyFundedFutures no saldo "
                    "inicial mais USD 100?",
                    "Segundo a central de ajuda lida em {as_of}, a perda máxima acompanha o maior "
                    "saldo de fechamento diário e se fixa no saldo inicial mais USD 100, e outra "
                    "página coloca essa fixação na etapa Sim Funded. A calculadora a deixa "
                    "acompanhar sem se fixar, a leitura mais estrita das duas. Além disso, uma "
                    "posição aberta que leva o saldo abaixo do mínimo encerra a avaliação, e isso "
                    "não aparece em fechamentos diários.",
                ),
                (
                    "Que regras da MyFundedFutures a calculadora não vê?",
                    "Segundo as páginas lidas em {as_of}: as posições abertas são fechadas "
                    "automaticamente às 4:10 PM EST, então nenhuma fica de um dia para o outro; "
                    "uma conta sem operações por 7 dias corridos seguidos pode ser encerrada; "
                    "cada plano limita os contratos; e no Rapid EOD, no Rapid e no Pro a política "
                    "de notícias se contradiz, enquanto o Builder permite operar notícias. A "
                    f"regra de consistência ({{field[{_MFF_RAPID_EOD}.best_day_limit]}} no Rapid "
                    f"EOD 50K, {{field[{_MFF_RAPID}.best_day_limit]}} no Rapid 50K e no Pro 50K) "
                    "não encerra a conta: pede mais dias de trading.",
                ),
            ),
        },
    },
    "tradeify": {
        "es": {
            "title": "Calculadora del reto Tradeify",
            "seo_title": "Calculadora del reto Tradeify: Select y Growth",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a Tradeify: frecuencia de "
                "alcanzar el objetivo de Select o Growth 50K o de tocar su pérdida máxima."
            ),
            "lead": _lead("Tradeify", "es"),
            "faq": (
                (
                    "¿Qué objetivo y qué límites tienen Select 50K y Growth 50K de Tradeify?",
                    "Según el centro de ayuda de Tradeify leído el {as_of}, Select 50K: "
                    f"{{rules[{_TRADEIFY_SELECT}]}}. Growth 50K: {{rules[{_TRADEIFY_GROWTH}]}}. "
                    "La pérdida máxima en dólares: {accounts}.",
                ),
                (
                    "¿Se fija el drawdown de Tradeify durante la evaluación?",
                    "Según el artículo de drawdowns leído el {as_of}, no: sigue al mayor balance "
                    "de cierre diario y no se fija en las cuentas de evaluación, aunque se aplica "
                    "en tiempo real contra el valor de liquidación neto. La calculadora lo deja "
                    "seguir sin fijarse y solo mira cierres diarios, así que frente a una caída "
                    "dentro del día es optimista.",
                ),
                (
                    "¿Cómo trata la calculadora la consistencia de Select y de Growth?",
                    "Según las páginas leídas el {as_of}, en la evaluación Select ningún día "
                    f"puede superar el {{field[{_TRADEIFY_SELECT}.best_day_limit]}} de la "
                    "ganancia total, y por eso pide al menos "
                    f"{{field[{_TRADEIFY_SELECT}.min_trading_days]}} días; la calculadora compara "
                    "el mejor día con el objetivo cuando una trayectoria lo alcanza. La "
                    "evaluación Growth no tiene regla de consistencia: su regla del 35 % rige los "
                    "cobros de la cuenta Sim Funded, así que la calculadora no aplica ninguna.",
                ),
                (
                    "¿Cómo cuenta la calculadora el límite diario de Growth 50K?",
                    f"Según el centro de ayuda leído el {{as_of}}: {{daily[{_TRADEIFY_GROWTH}]}} "
                    "(USD 1.250), que se reinicia al empezar cada sesión, a las 6:00 PM ET. Al "
                    "tocarlo, Tradeify pausa el trading hasta la sesión siguiente sin cerrar la "
                    "cuenta; la calculadora termina ahí la trayectoria, que es más estricto. "
                    "Todas las posiciones se cierran antes de las 4:45 PM ET.",
                ),
            ),
        },
        "en": {
            "title": "Tradeify challenge calculator",
            "seo_title": "Tradeify challenge calculator: Select and Growth",
            "summary": (
                "Free, independent calculator, not affiliated with Tradeify: how often you would "
                "reach the Select or Growth 50K evaluation target or hit its maximum loss."
            ),
            "lead": _lead("Tradeify", "en"),
            "faq": (
                (
                    "What target and limits do the Tradeify Select 50K and Growth 50K have?",
                    "According to the Tradeify help center read on {as_of}, Select 50K: "
                    f"{{rules[{_TRADEIFY_SELECT}]}}. Growth 50K: {{rules[{_TRADEIFY_GROWTH}]}}. "
                    "The maximum loss in dollars: {accounts}.",
                ),
                (
                    "Does the Tradeify drawdown lock during the evaluation?",
                    "According to the drawdown article read on {as_of}, no: it trails the highest "
                    "end-of-day balance and does not lock on evaluation accounts, though it is "
                    "enforced in real time against the net liquidation value. The calculator lets "
                    "it trail without locking and only checks daily closes, so it is optimistic "
                    "against a drop within the day.",
                ),
                (
                    "How does the calculator treat the Select and Growth consistency rules?",
                    "According to the pages read on {as_of}, in the Select evaluation no day may "
                    f"exceed {{field[{_TRADEIFY_SELECT}.best_day_limit]}} of the total profit, "
                    "which is why it asks for at least "
                    f"{{field[{_TRADEIFY_SELECT}.min_trading_days]}} days; the calculator compares "
                    "the best day with the profit target when a path reaches it. The Growth "
                    "evaluation has no consistency rule: its 35 % rule governs the Sim Funded "
                    "account's payouts, so the calculator applies none.",
                ),
                (
                    "How does the calculator count the Growth 50K daily loss limit?",
                    "According to the help center read on {as_of}: "
                    f"{{daily[{_TRADEIFY_GROWTH}]}} (USD 1,250), reset at the start of each "
                    "session at 6:00 PM ET. When it is hit, Tradeify pauses trading until the "
                    "next session without closing the account; the calculator ends the path "
                    "there, the stricter reading. Every position is closed by 4:45 PM ET.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do desafio Tradeify",
            "seo_title": "Calculadora do desafio Tradeify: Select e Growth",
            "summary": (
                "Calculadora grátis e independente, não afiliada à Tradeify: frequência de atingir "
                "a meta da avaliação Select ou Growth 50K ou de tocar a perda máxima."
            ),
            "lead": _lead("Tradeify", "pt"),
            "faq": (
                (
                    "Que meta e que limites têm o Select 50K e o Growth 50K da Tradeify?",
                    "Segundo a central de ajuda da Tradeify lida em {as_of}, Select 50K: "
                    f"{{rules[{_TRADEIFY_SELECT}]}}. Growth 50K: {{rules[{_TRADEIFY_GROWTH}]}}. "
                    "A perda máxima em dólares: {accounts}.",
                ),
                (
                    "O drawdown da Tradeify se fixa durante a avaliação?",
                    "Segundo o artigo de drawdowns lido em {as_of}, não: ele acompanha o maior "
                    "saldo de fechamento diário e não se fixa nas contas de avaliação, embora "
                    "seja aplicado em tempo real contra o valor de liquidação líquido. A "
                    "calculadora o deixa acompanhar sem se fixar e só olha fechamentos diários, "
                    "então é otimista diante de uma queda dentro do dia.",
                ),
                (
                    "Como a calculadora trata a consistência do Select e do Growth?",
                    "Segundo as páginas lidas em {as_of}, na avaliação Select nenhum dia pode "
                    f"superar {{field[{_TRADEIFY_SELECT}.best_day_limit]}} do resultado total, e "
                    f"por isso ela pede pelo menos {{field[{_TRADEIFY_SELECT}.min_trading_days]}} "
                    "dias; a calculadora compara o melhor dia com a meta quando uma trajetória a "
                    "atinge. A avaliação Growth não tem regra de consistência: a sua regra de 35 % "
                    "vale para os saques da conta Sim Funded, então a calculadora não aplica "
                    "nenhuma.",
                ),
                (
                    "Como a calculadora conta o limite diário do Growth 50K?",
                    f"Segundo a central de ajuda lida em {{as_of}}: {{daily[{_TRADEIFY_GROWTH}]}} "
                    "(USD 1.250), reiniciado no início de cada sessão, às 6:00 PM ET. Ao tocá-lo, "
                    "a Tradeify pausa o trading até a sessão seguinte sem encerrar a conta; a "
                    "calculadora encerra ali a trajetória, a leitura mais estrita. Todas as "
                    "posições são fechadas até as 4:45 PM ET.",
                ),
            ),
        },
    },
    "bulenox": {
        "es": {
            "title": "Calculadora del reto Bulenox",
            "seo_title": "Calculadora de Bulenox: Qualification y Momentum",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a Bulenox: frecuencia de alcanzar "
                "el objetivo de Qualification o Momentum 50K o de tocar su pérdida máxima."
            ),
            "lead": _lead("Bulenox", "es"),
            "faq": (
                (
                    "¿Qué objetivo y qué límites tienen Qualification EOD 50K y Momentum EOD 50K "
                    "de Bulenox?",
                    "Según las páginas de Bulenox leídas el {as_of}, Qualification EOD 50K: "
                    f"{{rules[{_BULENOX_QUALIFICATION}]}}. Momentum EOD 50K: "
                    f"{{rules[{_BULENOX_MOMENTUM}]}}. La pérdida máxima en dólares: {{accounts}}.",
                ),
                (
                    "¿Por qué la calculadora pone un plazo de 30 días a la Qualification de "
                    "Bulenox?",
                    "Según las páginas leídas el {as_of}, la página de precios da 30 días de "
                    "acceso y el centro de ayuda dice que un reset no los alarga, mientras que la "
                    "FAQ dice que no hay máximo de días de trading. La calculadora usa los "
                    f"{{field[{_BULENOX_QUALIFICATION}.time_limit_days]}} días, la lectura más "
                    "estricta: {horizon} días hábiles en sus trayectorias.",
                ),
                (
                    "¿Cómo cuenta la calculadora el límite diario de Bulenox?",
                    "Según las páginas leídas el {as_of}, el límite diario (USD 1.100 en "
                    "Qualification EOD 50K y USD 1.200 en Momentum EOD 50K) pausa el trading el "
                    "resto del día y no cierra la cuenta; en la Qualification cuenta el P&L "
                    "realizado y no realizado con comisiones de 5:00 PM a 4:00 PM CT. La "
                    "calculadora lo revisa en cada cierre diario y termina la trayectoria al "
                    "tocarlo: más estricta por terminarla, optimista por no ver el día por "
                    "dentro.",
                ),
                (
                    "¿Se puede mantener una posición de noche u operar con noticias en Bulenox?",
                    "Según las páginas leídas el {as_of}, están prohibidas las posiciones de un "
                    "día a otro y de fin de semana, y se permite operar con noticias. En "
                    "Qualification EOD 50K los contratos crecen con la ganancia (2 hasta "
                    "USD 1.500, 4 hasta USD 4.000 y 7 después); la calculadora no modela el "
                    "tamaño de la posición.",
                ),
            ),
        },
        "en": {
            "title": "Bulenox challenge calculator",
            "seo_title": "Bulenox calculator: Qualification and Momentum",
            "summary": (
                "Free, independent calculator, not affiliated with Bulenox: how often you would "
                "reach the Qualification or Momentum 50K target or hit its maximum loss."
            ),
            "lead": _lead("Bulenox", "en"),
            "faq": (
                (
                    "What target and limits do the Bulenox Qualification EOD 50K and Momentum EOD "
                    "50K have?",
                    "According to the Bulenox pages read on {as_of}, Qualification EOD 50K: "
                    f"{{rules[{_BULENOX_QUALIFICATION}]}}. Momentum EOD 50K: "
                    f"{{rules[{_BULENOX_MOMENTUM}]}}. The maximum loss in dollars: {{accounts}}.",
                ),
                (
                    "Why does the calculator give the Bulenox Qualification a 30-day time limit?",
                    "According to the pages read on {as_of}, the pricing page gives 30 days of "
                    "access and the help center says a reset does not extend them, while the FAQ "
                    "says there is no maximum number of trading days. The calculator uses the "
                    f"{{field[{_BULENOX_QUALIFICATION}.time_limit_days]}} days, the stricter "
                    "reading: {horizon} business days on its paths.",
                ),
                (
                    "How does the calculator count the Bulenox daily loss limit?",
                    "According to the pages read on {as_of}, the daily limit (USD 1,100 on "
                    "Qualification EOD 50K and USD 1,200 on Momentum EOD 50K) pauses trading for "
                    "the rest of the day and does not close the account; on the Qualification it "
                    "counts realized and unrealized P&L with commissions from 5:00 PM to 4:00 PM "
                    "CT. The calculator checks it at every daily close and ends the path when it "
                    "is hit: stricter for ending it, optimistic for not seeing inside the day.",
                ),
                (
                    "Can I hold a position overnight or trade the news at Bulenox?",
                    "According to the pages read on {as_of}, overnight and weekend positions are "
                    "prohibited, and news trading is allowed. On the Qualification EOD 50K the "
                    "contracts grow with the profit (2 up to USD 1,500, 4 up to USD 4,000 and 7 "
                    "after); the calculator does not model position size.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do desafio Bulenox",
            "seo_title": "Calculadora da Bulenox: Qualification e Momentum",
            "summary": (
                "Calculadora grátis e independente, não afiliada à Bulenox: frequência de atingir "
                "a meta do Qualification ou do Momentum 50K ou de tocar a perda máxima."
            ),
            "lead": _lead("Bulenox", "pt"),
            "faq": (
                (
                    "Que meta e que limites têm o Qualification EOD 50K e o Momentum EOD 50K da "
                    "Bulenox?",
                    "Segundo as páginas da Bulenox lidas em {as_of}, Qualification EOD 50K: "
                    f"{{rules[{_BULENOX_QUALIFICATION}]}}. Momentum EOD 50K: "
                    f"{{rules[{_BULENOX_MOMENTUM}]}}. A perda máxima em dólares: {{accounts}}.",
                ),
                (
                    "Por que a calculadora dá um prazo de 30 dias ao Qualification da Bulenox?",
                    "Segundo as páginas lidas em {as_of}, a página de preços dá 30 dias de acesso "
                    "e a central de ajuda diz que um reset não os estende, enquanto a FAQ diz que "
                    "não há máximo de dias de trading. A "
                    f"calculadora usa os {{field[{_BULENOX_QUALIFICATION}.time_limit_days]}} "
                    "dias, a leitura mais estrita: {horizon} dias úteis nas suas trajetórias.",
                ),
                (
                    "Como a calculadora conta o limite diário da Bulenox?",
                    "Segundo as páginas lidas em {as_of}, o limite diário (USD 1.100 no "
                    "Qualification EOD 50K e USD 1.200 no Momentum EOD 50K) pausa o trading pelo "
                    "resto do dia e não encerra a conta; no Qualification ele conta o P&L "
                    "realizado e não realizado com comissões de 5:00 PM a 4:00 PM CT. A "
                    "calculadora o confere em cada fechamento diário e encerra a trajetória ao "
                    "tocá-lo: mais estrita por encerrá-la, otimista por não ver o dia por dentro.",
                ),
                (
                    "Dá para manter uma posição de um dia para o outro ou operar notícias na "
                    "Bulenox?",
                    "Segundo as páginas lidas em {as_of}, são proibidas as posições de um dia para "
                    "o outro e de fim de semana, e é permitido operar notícias. No Qualification "
                    "EOD 50K os contratos crescem com o ganho (2 até USD 1.500, 4 até USD 4.000 e "
                    "7 depois); a calculadora não modela o tamanho da posição.",
                ),
            ),
        },
    },
    "earn2trade": {
        "es": {
            "title": "Calculadora del reto Earn2Trade",
            "seo_title": "Calculadora de Earn2Trade: Career Path y Gauntlet Mini",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a Earn2Trade: frecuencia de "
                "alcanzar el objetivo de Trader Career Path o Gauntlet Mini o de tocar sus "
                "límites."
            ),
            "lead": _lead("Earn2Trade", "es"),
            "faq": (
                (
                    "¿Qué objetivo y qué límites tiene el Trader Career Path 25K de Earn2Trade?",
                    f"Según la página de Earn2Trade leída el {{as_of}}: {{rules[{_E2T_TCP}]}}. En "
                    "la cuenta de USD 25.000 son USD 1.750 de objetivo, USD 550 de pérdida diaria "
                    "y USD 1.500 de pérdida máxima.",
                ),
                (
                    "¿Qué objetivo y qué límites tiene el Gauntlet Mini 50K de Earn2Trade?",
                    "Según la página de Earn2Trade leída el {as_of}: "
                    f"{{rules[{_E2T_GAUNTLET}]}}. En la cuenta de USD 50.000 son USD 3.000 de "
                    "objetivo, USD 1.100 de pérdida diaria y USD 2.000 de pérdida máxima.",
                ),
                (
                    "¿Cómo cuenta la calculadora la pérdida diaria y el drawdown de Earn2Trade?",
                    "Según el centro de ayuda leído el {as_of}, la pérdida diaria se cuenta desde "
                    "el balance con el que empieza el día (de 5:00 PM a 5:00 PM CT) con "
                    "operaciones abiertas y cerradas y comisiones, y el drawdown sigue al mayor "
                    "cierre diario hasta el balance inicial, también con pérdidas abiertas. La "
                    "calculadora revisa los dos en cada cierre diario: no ve el flotante dentro "
                    "del día, así que frente a ellos es optimista.",
                ),
                (
                    "¿Cómo trata la calculadora la regla Maintain Consistency de Earn2Trade?",
                    "Según el centro de ayuda leído el {as_of}, ningún día puede ser el "
                    f"{{field[{_E2T_TCP}.best_day_limit]}} o más del P&L total; romperla no "
                    "termina la cuenta, pide seguir operando, y en la práctica exige al menos 4 "
                    "días que cierren con ganancia. La calculadora compara el mejor día con el "
                    "objetivo cuando una trayectoria lo alcanza, que es más estricto.",
                ),
            ),
        },
        "en": {
            "title": "Earn2Trade challenge calculator",
            "seo_title": "Earn2Trade calculator: Career Path and Gauntlet Mini",
            "summary": (
                "Free, independent calculator, not affiliated with Earn2Trade: how often you would "
                "reach the Trader Career Path or Gauntlet Mini target or hit its limits."
            ),
            "lead": _lead("Earn2Trade", "en"),
            "faq": (
                (
                    "What target and limits does the Earn2Trade Trader Career Path 25K have?",
                    "According to the Earn2Trade page read on {as_of}: "
                    f"{{rules[{_E2T_TCP}]}}. On the USD 25,000 account that is a USD 1,750 "
                    "target, a USD 550 daily loss limit and a USD 1,500 maximum loss.",
                ),
                (
                    "What target and limits does the Earn2Trade Gauntlet Mini 50K have?",
                    "According to the Earn2Trade page read on {as_of}: "
                    f"{{rules[{_E2T_GAUNTLET}]}}. On the USD 50,000 account that is a USD 3,000 "
                    "target, a USD 1,100 daily loss limit and a USD 2,000 maximum loss.",
                ),
                (
                    "How does the calculator count the Earn2Trade daily loss and drawdown?",
                    "According to the help center read on {as_of}, the daily loss is counted from "
                    "the balance the day starts with (5:00 PM to 5:00 PM CT) with open and closed "
                    "trades and commissions, and the drawdown trails the highest daily close up "
                    "to the starting balance, open losses included. The calculator checks both "
                    "at every daily close: it does not see the floating loss within the day, so "
                    "it is optimistic against them.",
                ),
                (
                    "How does the calculator treat the Earn2Trade Maintain Consistency rule?",
                    "According to the help center read on {as_of}, no day may be "
                    f"{{field[{_E2T_TCP}.best_day_limit]}} or more of the total P&L; breaking it "
                    "does not end the account, it asks for more trading, and in practice it needs "
                    "at least 4 days that close with a gain. The calculator compares the best day "
                    "with the profit target when a path reaches it, the stricter reading.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do desafio Earn2Trade",
            "seo_title": "Calculadora da Earn2Trade: Career Path e Gauntlet Mini",
            "summary": (
                "Calculadora grátis e independente, não afiliada à Earn2Trade: frequência de "
                "atingir a meta do Trader Career Path ou do Gauntlet Mini ou de tocar os limites."
            ),
            "lead": _lead("Earn2Trade", "pt"),
            "faq": (
                (
                    "Que meta e que limites tem o Trader Career Path 25K da Earn2Trade?",
                    f"Segundo a página da Earn2Trade lida em {{as_of}}: {{rules[{_E2T_TCP}]}}. Na "
                    "conta de USD 25.000 são USD 1.750 de meta, USD 550 de perda diária e "
                    "USD 1.500 de perda máxima.",
                ),
                (
                    "Que meta e que limites tem o Gauntlet Mini 50K da Earn2Trade?",
                    "Segundo a página da Earn2Trade lida em {as_of}: "
                    f"{{rules[{_E2T_GAUNTLET}]}}. Na conta de USD 50.000 são USD 3.000 de meta, "
                    "USD 1.100 de perda diária e USD 2.000 de perda máxima.",
                ),
                (
                    "Como a calculadora conta a perda diária e o drawdown da Earn2Trade?",
                    "Segundo a central de ajuda lida em {as_of}, a perda diária é contada a partir "
                    "do saldo com que o dia começa (de 5:00 PM a 5:00 PM CT) com operações "
                    "abertas e fechadas e comissões, e o drawdown acompanha o maior fechamento "
                    "diário até o saldo inicial, também com perdas abertas. A calculadora confere "
                    "os dois em cada fechamento diário: não vê a perda flutuante dentro do dia, "
                    "então é otimista diante deles.",
                ),
                (
                    "Como a calculadora trata a regra Maintain Consistency da Earn2Trade?",
                    "Segundo a central de ajuda lida em {as_of}, nenhum dia pode ser "
                    f"{{field[{_E2T_TCP}.best_day_limit]}} ou mais do P&L total; quebrá-la não "
                    "encerra a conta, pede continuar operando, e na prática exige pelo menos 4 "
                    "dias que fechem com ganho. A calculadora compara o melhor dia com a meta "
                    "quando uma trajetória a atinge, a leitura mais estrita.",
                ),
            ),
        },
    },
    "alpha-futures": {
        "es": {
            "title": "Calculadora del reto Alpha Futures",
            "seo_title": "Calculadora de Alpha Futures: Zero, Standard y Advanced",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a Alpha Futures: frecuencia de "
                "alcanzar el objetivo de Zero, Standard o Advanced 50K o de tocar sus límites."
            ),
            "lead": _lead("Alpha Futures", "es"),
            "faq": (
                (
                    "¿Qué objetivo y qué límites tienen Zero, Standard y Advanced 50K de Alpha "
                    "Futures?",
                    "Según las páginas de Alpha Futures leídas el {as_of}, Zero 50K: "
                    f"{{rules[{_ALPHA_ZERO}]}}. Standard 50K: {{rules[{_ALPHA_STANDARD}]}}. "
                    f"Advanced 50K: {{rules[{_ALPHA_ADVANCED}]}}.",
                ),
                (
                    "¿Cuál es la pérdida máxima de cada evaluación de Alpha Futures?",
                    "Según el centro de ayuda leído el {as_of}: {accounts}. Esa pérdida máxima "
                    "sigue al mayor balance de cierre diario y deja de subir en el balance "
                    "inicial; se rompe en cualquier momento, con el equity flotante o con el "
                    "balance cerrado, algo que una cifra por cierre diario no ve.",
                ),
                (
                    "¿Cómo trata la calculadora el Daily Loss Guard de Zero 50K?",
                    "Según el centro de ayuda leído el {as_of}, es el "
                    f"{{field[{_ALPHA_ZERO}.max_daily_loss]}} del balance inicial sobre el P&L "
                    "abierto y cerrado del día: al tocarlo se cierran las posiciones y la cuenta "
                    "queda bloqueada hasta el siguiente día de trading (6 PM ET), sin terminar. "
                    "La calculadora termina ahí la trayectoria: más estricta por terminarla, "
                    "optimista por no ver el P&L abierto dentro del día. Standard 50K y Advanced "
                    "50K no tienen límite de pérdida diaria en la evaluación.",
                ),
                (
                    "¿Puedo usar un robot en Alpha Futures?",
                    "Según la página de prácticas prohibidas leída el {as_of}, no: la IA, los "
                    "bots y el resto del trading automático están prohibidos en todos los tipos "
                    "de cuenta, igual que el trading de alta frecuencia y la cobertura entre "
                    "cuentas, y todas las posiciones se cierran antes de las 4:20 PM ET. La "
                    "calculadora da cifras con tus números declarados, pero una estrategia "
                    "automática no se puede operar ahí.",
                ),
            ),
        },
        "en": {
            "title": "Alpha Futures challenge calculator",
            "seo_title": "Alpha Futures calculator: Zero, Standard and Advanced",
            "summary": (
                "Free, independent calculator, not affiliated with Alpha Futures: how often you "
                "would reach the Zero, Standard or Advanced 50K target or hit its limits."
            ),
            "lead": _lead("Alpha Futures", "en"),
            "faq": (
                (
                    "What target and limits do the Alpha Futures Zero, Standard and Advanced 50K "
                    "have?",
                    "According to the Alpha Futures pages read on {as_of}, Zero 50K: "
                    f"{{rules[{_ALPHA_ZERO}]}}. Standard 50K: {{rules[{_ALPHA_STANDARD}]}}. "
                    f"Advanced 50K: {{rules[{_ALPHA_ADVANCED}]}}.",
                ),
                (
                    "What is the maximum loss of each Alpha Futures evaluation?",
                    "According to the help center read on {as_of}: {accounts}. That maximum loss "
                    "trails the highest end-of-day balance and stops at the starting balance; it "
                    "breaks at any moment, on floating equity or on the closed balance, which one "
                    "figure per daily close cannot see.",
                ),
                (
                    "How does the calculator treat the Zero 50K Daily Loss Guard?",
                    "According to the help center read on {as_of}, it is "
                    f"{{field[{_ALPHA_ZERO}.max_daily_loss]}} of the starting balance on the "
                    "day's open and closed P&L: reaching it flattens the positions and locks the "
                    "account until the next trading day (6 PM ET) without ending it. The "
                    "calculator ends the path there: stricter for ending it, optimistic for not "
                    "seeing the open P&L within the day. Standard 50K and Advanced 50K have no "
                    "daily loss limit in the evaluation.",
                ),
                (
                    "Can I trade a bot at Alpha Futures?",
                    "According to the prohibited practices page read on {as_of}, no: AI, bots and "
                    "other automated trading are prohibited on every account type, as are "
                    "high-frequency trading and hedging between accounts, and every position is "
                    "closed by 4:20 PM ET. The calculator gives figures for your declared "
                    "numbers, but an automated strategy cannot be traded there.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do desafio Alpha Futures",
            "seo_title": "Calculadora da Alpha Futures: Zero, Standard e Advanced",
            "summary": (
                "Calculadora grátis e independente, não afiliada à Alpha Futures: frequência de "
                "atingir a meta do Zero, Standard ou Advanced 50K ou de tocar os limites."
            ),
            "lead": _lead("Alpha Futures", "pt"),
            "faq": (
                (
                    "Que meta e que limites têm o Zero, o Standard e o Advanced 50K da Alpha "
                    "Futures?",
                    "Segundo as páginas da Alpha Futures lidas em {as_of}, Zero 50K: "
                    f"{{rules[{_ALPHA_ZERO}]}}. Standard 50K: {{rules[{_ALPHA_STANDARD}]}}. "
                    f"Advanced 50K: {{rules[{_ALPHA_ADVANCED}]}}.",
                ),
                (
                    "Qual é a perda máxima de cada avaliação da Alpha Futures?",
                    "Segundo a central de ajuda lida em {as_of}: {accounts}. Essa perda máxima "
                    "acompanha o maior saldo de fechamento diário e para no saldo inicial; "
                    "rompe-se a qualquer momento, com o patrimônio flutuante ou com o saldo "
                    "fechado, algo que um número por fechamento diário não vê.",
                ),
                (
                    "Como a calculadora trata o Daily Loss Guard do Zero 50K?",
                    "Segundo a central de ajuda lida em {as_of}, é "
                    f"{{field[{_ALPHA_ZERO}.max_daily_loss]}} do saldo inicial sobre o P&L aberto "
                    "e fechado do dia: ao atingi-lo, as posições são zeradas e a conta fica "
                    "bloqueada até o próximo dia de trading (6 PM ET), sem ser encerrada. A "
                    "calculadora encerra ali a trajetória: mais estrita por encerrá-la, otimista "
                    "por não ver o P&L aberto dentro do dia. O Standard 50K e o Advanced 50K não "
                    "têm limite de perda diária na avaliação.",
                ),
                (
                    "Posso usar um robô na Alpha Futures?",
                    "Segundo a página de práticas proibidas lida em {as_of}, não: IA, bots e "
                    "outras formas de trading automático são proibidos em todos os tipos de "
                    "conta, assim como o trading de alta frequência e o hedge entre contas, e "
                    "todas as posições são fechadas até as 4:20 PM ET. A calculadora dá números "
                    "com os seus dados declarados, mas uma estratégia automática não pode ser "
                    "operada lá.",
                ),
            ),
        },
    },
    "lucid-trading": {
        "es": {
            "title": "Calculadora de LucidPro de Lucid Trading",
            "seo_title": "Calculadora de LucidPro de Lucid Trading",
            "summary": (
                "Calculadora gratis e independiente, no afiliada a Lucid Trading: frecuencia de "
                "alcanzar el objetivo de la evaluación LucidPro 50K o de tocar su pérdida máxima."
            ),
            "lead": _lead("Lucid Trading", "es"),
            "faq": (
                (
                    "¿Qué objetivo y qué límites tiene LucidPro 50K de Lucid Trading?",
                    "Según el centro de ayuda de Lucid Trading leído el {as_of}: "
                    f"{{rules[{_LUCID_PRO}]}}. En la cuenta de USD 50.000 son USD 3.000 de "
                    "objetivo y USD 2.000 de pérdida máxima, con un pago único.",
                ),
                (
                    "¿Por qué la calculadora no fija la pérdida máxima de LucidPro?",
                    "Según el centro de ayuda leído el {as_of}, la pérdida máxima sigue al mayor "
                    "balance de cierre diario y se fija en el balance inicial más USD 100. La "
                    "calculadora la deja seguir sin fijarse, la lectura más estricta en cuanto al "
                    "bloqueo: en cierres diarios nunca mantiene viva una trayectoria que la regla "
                    "de la firma terminaría. Las páginas leídas no dicen si también se vigila "
                    "dentro del día; la calculadora solo mira cierres diarios, así que, si se "
                    "vigila, aquí es optimista.",
                ),
                (
                    "¿Simula la calculadora el límite de pérdida diaria de LucidPro?",
                    "No. Según el centro de ayuda leído el {as_of}, el límite diario se elige al "
                    "comprar: la calculadora simula la cuenta sin él. Activado, es un límite fijo "
                    "de USD 1.200 que corta el día sin suspender la cuenta.",
                ),
                (
                    "¿Qué reglas de LucidPro no ve la calculadora?",
                    "Según las páginas leídas el {as_of}: todas las posiciones se cierran antes de "
                    "las 4:45 PM EST, de lunes a viernes; el tamaño máximo es de 4 minis o 40 "
                    "micros, y están prohibidos el microscalping, el trading de alta frecuencia y "
                    "la cobertura, mientras que se permite operar con noticias. La consistencia "
                    "del 40 % es de la cuenta funded, no de la evaluación.",
                ),
            ),
        },
        "en": {
            "title": "Lucid Trading LucidPro calculator",
            "seo_title": "Lucid Trading LucidPro calculator: target and limits",
            "summary": (
                "Free, independent calculator, not affiliated with Lucid Trading: how often you "
                "would reach the LucidPro 50K evaluation target or hit its maximum loss."
            ),
            "lead": _lead("Lucid Trading", "en"),
            "faq": (
                (
                    "What target and limits does the Lucid Trading LucidPro 50K have?",
                    "According to the Lucid Trading help center read on {as_of}: "
                    f"{{rules[{_LUCID_PRO}]}}. On the USD 50,000 account that is a USD 3,000 "
                    "target and a USD 2,000 maximum loss, for a one-time fee.",
                ),
                (
                    "Why does the calculator not lock the LucidPro maximum loss?",
                    "According to the help center read on {as_of}, the maximum loss trails the "
                    "highest end-of-day balance and locks at the starting balance plus USD 100. "
                    "The calculator lets it trail without locking, the stricter reading of the "
                    "lock: on daily closes it never keeps alive a path the firm's rule would end. "
                    "The pages read do not say whether it is also checked within the day; the "
                    "calculator only checks daily closes, so if it is, the calculator is "
                    "optimistic here.",
                ),
                (
                    "Does the calculator simulate the LucidPro daily loss limit?",
                    "No. According to the help center read on {as_of}, the daily loss limit is "
                    "chosen at purchase: the calculator simulates the account without it. Turned "
                    "on, it is a fixed USD 1,200 limit that ends the day without suspending the "
                    "account.",
                ),
                (
                    "Which LucidPro rules does the calculator not see?",
                    "According to the pages read on {as_of}: every position is closed by 4:45 PM "
                    "EST, Monday to Friday; the size is capped at 4 minis or 40 micros; and "
                    "microscalping, high-frequency trading and hedging are prohibited, while news "
                    "trading is allowed. The 40 % consistency rule belongs to the funded account, "
                    "not to the evaluation.",
                ),
            ),
        },
        "pt": {
            "title": "Calculadora do LucidPro da Lucid Trading",
            "seo_title": "Calculadora do LucidPro da Lucid Trading",
            "summary": (
                "Calculadora grátis e independente, não afiliada à Lucid Trading: frequência de "
                "atingir a meta da avaliação LucidPro 50K ou de tocar a perda máxima."
            ),
            "lead": _lead("Lucid Trading", "pt"),
            "faq": (
                (
                    "Que meta e que limites tem o LucidPro 50K da Lucid Trading?",
                    "Segundo a central de ajuda da Lucid Trading lida em {as_of}: "
                    f"{{rules[{_LUCID_PRO}]}}. Na conta de USD 50.000 são USD 3.000 de meta e "
                    "USD 2.000 de perda máxima, com pagamento único.",
                ),
                (
                    "Por que a calculadora não fixa a perda máxima do LucidPro?",
                    "Segundo a central de ajuda lida em {as_of}, a perda máxima acompanha o maior "
                    "saldo de fechamento diário e se fixa no saldo inicial mais USD 100. A "
                    "calculadora a deixa acompanhar sem se fixar, a leitura mais estrita quanto à "
                    "fixação: em fechamentos diários nunca mantém viva uma trajetória que a regra "
                    "da firma encerraria. As páginas lidas não dizem se ela também é vigiada "
                    "dentro do dia; a calculadora só olha fechamentos diários, então, se for, aqui "
                    "é otimista.",
                ),
                (
                    "A calculadora simula o limite de perda diária do LucidPro?",
                    "Não. Segundo a central de ajuda lida em {as_of}, o limite diário é escolhido "
                    "na compra: a calculadora simula a conta sem ele. Ativado, é um limite fixo "
                    "de USD 1.200 que corta o dia sem suspender a conta.",
                ),
                (
                    "Que regras do LucidPro a calculadora não vê?",
                    "Segundo as páginas lidas em {as_of}: todas as posições são fechadas até as "
                    "4:45 PM EST, de segunda a sexta; o tamanho máximo é de 4 minis ou 40 micros; "
                    "e são proibidos o microscalping, o trading de alta frequência e o hedge, "
                    "enquanto é permitido operar notícias. A consistência de 40 % é da conta "
                    "funded, não da avaliação.",
                ),
            ),
        },
    },
}


__all__ = ["FUTURES_FIRMS", "FUTURES_FIRM_COPY"]
