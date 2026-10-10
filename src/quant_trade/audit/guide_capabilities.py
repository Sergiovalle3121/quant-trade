"""What the report does with each guide's file, read from the code that does it.

Every export guide (``guides.GUIDES``) gets a line under its heading saying what
the file is for, and two to four points on what the importer and the engine
really do with that file type. Each point (:class:`Capability`) names:

* ``sources``: the functions or constants that do it, as ``module:attribute``
  under ``quant_trade.audit``; the test suite imports every one;
* ``formats``: the importer formats whose upload it is about; a guide may only
  list a point whose formats include one its file produces (``GUIDE_FORMATS``);
* ``fields``: the figures and names the text quotes, read from the code at
  render time (a report section title, a red flag's title, a threshold), so the
  guide says what the report says and moves when the code moves.

A point is only listed for a file type the code handles that way: Myfxbook,
MQL5 and FX Blue print no running balance, so their guides say the money
reconciliation stays NOT_MEASURED instead of promising one. A point the code
only does under a condition (the Myfxbook floating result needs the "Open
Trades" block and a deposit; the plateau needs the main optimisation export,
not the forward one) states that condition.
"""

from __future__ import annotations

import importlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from quant_trade.audit.account import ACCOUNT_FORMATS
from quant_trade.audit.importers import (
    BACKTESTINGPY_CSV,
    FXBLUE_CSV,
    MQL5_SIGNAL_CSV,
    MT4_STATEMENT_HTML,
    MT4_TESTER_HTML,
    MT5_HISTORY_HTML,
    MT5_HISTORY_XLSX,
    MT5_OPTIMIZATION_XML,
    MT5_TESTER_HTML,
    MT5_TESTER_XLSX,
    MYFXBOOK_CSV,
    NINJATRADER_CSV,
    NINJATRADER_EXECUTIONS_CSV,
    QUANTCONNECT_TRADES_CSV,
    REPORT_FORMATS,
    ROBINHOOD_CSV,
    TRADINGVIEW_CSV,
    TRADINGVIEW_XLSX,
    UNIVERSAL_FILLS_CSV,
    UNIVERSAL_TRADES_CSV,
    VECTORBT_CSV,
)

#: Where ``sources`` and the numeric ``fields`` live.
PACKAGE = "quant_trade.audit"

_MT5_TESTER = frozenset({MT5_TESTER_HTML, MT5_TESTER_XLSX})
_MT5_HISTORY = frozenset({MT5_HISTORY_HTML, MT5_HISTORY_XLSX})
_TRADINGVIEW = frozenset({TRADINGVIEW_CSV, TRADINGVIEW_XLSX})
_UNIVERSAL = frozenset({UNIVERSAL_TRADES_CSV, UNIVERSAL_FILLS_CSV})
#: Every platform file that becomes a list of closed trades.
_TRADE_LISTS = frozenset(REPORT_FORMATS)
#: Formats whose rows print the running balance the reconciliation compares with.
PRINTED_BALANCE_FORMATS = _MT5_TESTER | _MT5_HISTORY | {MT4_TESTER_HTML}
#: Account-tracking CSVs with no printed balance of their own.
NO_BALANCE_FORMATS = frozenset({MYFXBOOK_CSV, MQL5_SIGNAL_CSV, FXBLUE_CSV})

#: The files each guide's steps produce, as the importers name them.
GUIDE_FORMATS: dict[str, frozenset[str]] = {
    "mt5": _MT5_TESTER | _MT5_HISTORY,
    "cuenta-proveedor": _MT5_HISTORY | {MT4_STATEMENT_HTML},
    "mt5-optimization": frozenset({MT5_OPTIMIZATION_XML}),
    "mt4": frozenset({MT4_TESTER_HTML, MT4_STATEMENT_HTML}),
    "tradingview": _TRADINGVIEW,
    "ninjatrader": frozenset({NINJATRADER_CSV, NINJATRADER_EXECUTIONS_CSV}),
    "quantconnect": frozenset({QUANTCONNECT_TRADES_CSV}),
    "backtesting-py": frozenset({BACKTESTINGPY_CSV}),
    "vectorbt": frozenset({VECTORBT_CSV}),
    "myfxbook": frozenset({MYFXBOOK_CSV}),
    "mql5-signal": frozenset({MQL5_SIGNAL_CSV}),
    "fxblue": frozenset({FXBLUE_CSV}),
    "robinhood": frozenset({ROBINHOOD_CSV}),
    # The Console Tradebook is one row per fill, read by its column names.
    "zerodha": frozenset({UNIVERSAL_FILLS_CSV}),
    "csv-universal": _UNIVERSAL,
}


@dataclass(frozen=True)
class Capability:
    """One thing the report does with a file type, and the code that does it."""

    sources: tuple[str, ...]
    formats: frozenset[str]
    #: The point in Spanish, English and Portuguese; ``{name}`` comes from ``fields``.
    text: Mapping[str, str]
    #: ``name`` -> ``kind:reference`` (see :func:`field_value`).
    fields: Mapping[str, str] = field(default_factory=dict)


CAPABILITIES: dict[str, Capability] = {
    "balance_rebuilt": Capability(
        sources=("importers:_deal_cash", "importers:_balance_curve", "engine:_reconciliation"),
        formats=_MT5_TESTER | _MT5_HISTORY,
        fields={"recon": "integrity:recon_title", "flag": "flag:MONETARY_RECONCILIATION_MISMATCH"},
        text={
            "es": (
                "Rehace el saldo con el capital inicial, los depósitos y retiros y el resultado "
                "neto de cada operación cerrada, y lo compara con el saldo que el informe imprime "
                "en cada fila («{recon}»). Si el saldo impreso contradice las operaciones, sale la "
                "bandera «{flag}»."
            ),
            "en": (
                "It rebuilds the balance from the starting capital, the deposits and withdrawals "
                "and each closed trade's net result, and compares it with the balance the report "
                "prints on each row ('{recon}'). If the printed balance contradicts the trades, "
                "the red flag '{flag}' is raised."
            ),
            "pt": (
                "Refaz o saldo com o capital inicial, os depósitos e saques e o resultado líquido "
                "de cada operação fechada, e o compara com o saldo que o relatório imprime em cada "
                "linha ('{recon}'). Se o saldo impresso contradiz as operações, aparece a bandeira "
                "'{flag}'."
            ),
        },
    ),
    "mt5_history_balance": Capability(
        sources=("importers:_parse_mt5_history", "importers:_deal_cash", "engine:_reconciliation"),
        formats=_MT5_HISTORY,
        fields={"recon": "integrity:recon_title", "flag": "flag:MONETARY_RECONCILIATION_MISMATCH"},
        text={
            "es": (
                "Con el historial de MetaTrader 5, rehace el saldo con los depósitos, los retiros "
                "y el resultado neto de cada operación cerrada, y lo compara con el saldo que "
                "imprime cada fila («{recon}»). Si lo contradice, sale la bandera «{flag}»."
            ),
            "en": (
                "With the MetaTrader 5 history, it rebuilds the balance from the deposits, the "
                "withdrawals and each closed trade's net result, and compares it with the balance "
                "printed on each row ('{recon}'). If they contradict each other, the red flag "
                "'{flag}' is raised."
            ),
            "pt": (
                "Com o histórico do MetaTrader 5, refaz o saldo com os depósitos, os saques e o "
                "resultado líquido de cada operação fechada, e o compara com o saldo impresso em "
                "cada linha ('{recon}'). Se eles se contradizem, aparece a bandeira '{flag}'."
            ),
        },
    ),
    "mt4_tester_balance": Capability(
        sources=(
            "importers:_parse_mt4_tester",
            "importers:_balance_curve",
            "engine:_reconciliation",
        ),
        formats=frozenset({MT4_TESTER_HTML}),
        fields={"recon": "integrity:recon_title", "flag": "flag:MONETARY_RECONCILIATION_MISMATCH"},
        text={
            "es": (
                "Con el informe del probador, rehace el saldo con el capital inicial y el "
                "resultado de cada operación cerrada y lo compara con el saldo que imprime cada "
                "cierre («{recon}»). Si lo contradice, sale la bandera «{flag}»."
            ),
            "en": (
                "With the tester report, it rebuilds the balance from the starting capital and "
                "each closed trade's result and compares it with the balance printed on each "
                "close ('{recon}'). If they contradict each other, the red flag '{flag}' is "
                "raised."
            ),
            "pt": (
                "Com o relatório do testador, refaz o saldo com o capital inicial e o resultado "
                "de cada operação fechada e o compara com o saldo impresso em cada fechamento "
                "('{recon}'). Se eles se contradizem, aparece a bandeira '{flag}'."
            ),
        },
    ),
    "platform_drawdown": Capability(
        sources=("importers:_parse_mt5_tester", "engine:platform_equity_drawdown"),
        formats=_MT5_TESTER,
        fields={"open": "kpi:platform_equity_drawdown", "closed": "kpi:max_drawdown"},
        text={
            "es": (
                "Con el informe del probador, el drawdown de equidad que imprime MT5, que cuenta "
                "las operaciones abiertas, aparece como «{open}» (DECLARED) junto al «{closed}» "
                "de las operaciones cerradas."
            ),
            "en": (
                "With the tester report, the equity drawdown MT5 prints, which counts open "
                "trades, appears as '{open}' (DECLARED) next to the '{closed}' of the closed "
                "trades."
            ),
            "pt": (
                "Com o relatório do testador, o drawdown de patrimônio que o MT5 imprime, que "
                "conta as operações abertas, aparece como '{open}' (DECLARED) ao lado do "
                "'{closed}' das operações fechadas."
            ),
        },
    ),
    "history_money": Capability(
        sources=("account:ACCOUNT_FORMATS", "account:account_review"),
        formats=frozenset(ACCOUNT_FORMATS & (_MT5_HISTORY | {MT4_STATEMENT_HTML})),
        fields={"section": "label:account"},
        text={
            "es": (
                "Con el historial de una cuenta, no con el del probador, «{section}» separa lo "
                "que la cuenta ganó o perdió operando de lo que entró y salió en depósitos y "
                "retiros."
            ),
            "en": (
                "With an account history, not a tester report, '{section}' separates what the "
                "account made or lost by trading from the money paid in and out."
            ),
            "pt": (
                "Com o histórico de uma conta, não com o do testador, '{section}' separa o que a "
                "conta ganhou ou perdeu operando do que entrou e saiu em depósitos e saques."
            ),
        },
    ),
    "trials_or_xml": Capability(
        sources=("engine:trial_count", "schema:build_inputs"),
        formats=_MT5_TESTER,
        text={
            "es": (
                "El Sharpe deflactado descuenta la suerte con los intentos que declares; si "
                "subes también el XML de optimización y sus pasadas son al menos esas, usa ese "
                "número como MEASURED."
            ),
            "en": (
                "The deflated Sharpe takes the luck out with the trials you declare; if you also "
                "upload the optimisation XML and its passes are at least that many, it uses that "
                "number as MEASURED."
            ),
            "pt": (
                "O Sharpe deflacionado desconta a sorte com as tentativas que você declarar; se "
                "você também enviar o XML de otimização e as passadas forem pelo menos essas, usa "
                "esse número como MEASURED."
            ),
        },
    ),
    "passes_counted": Capability(
        sources=("importers:parse_optimization", "schema:build_inputs", "engine:trial_count"),
        formats=frozenset({MT5_OPTIMIZATION_XML}),
        text={
            "es": (
                "Cada fila del XML es una pasada y cuenta como un intento: si son al menos los "
                "que declaras, el Sharpe deflactado usa ese número como MEASURED."
            ),
            "en": (
                "Each row of the XML is a pass and counts as one trial: when there are at least "
                "as many as you declare, the deflated Sharpe uses that number as MEASURED."
            ),
            "pt": (
                "Cada linha do XML é uma passada e conta como uma tentativa: se forem pelo menos "
                "as que você declarar, o Sharpe deflacionado usa esse número como MEASURED."
            ),
        },
    ),
    "plateau": Capability(
        sources=(
            "plateau:parameter_stability",
            "plateau:METRICS",
            "plateau:FORWARD_EXPORT",
            "importers:_mt5_input_values",
        ),
        formats=frozenset({MT5_OPTIMIZATION_XML}),
        fields={
            "section": "label:plateau",
            "flag": "flag:ISOLATED_OPTIMUM",
            "passes": "int:plateau:MIN_PASSES",
            "share": "pct:plateau:PROFITABLE_SHARE",
            "keep": "pct:plateau:KEEP_SHARE",
        },
        text={
            "es": (
                "Con la exportación principal (sin periodo forward), «{section}» compara la "
                "configuración elegida (la del informe del probador o, si no aparece, la de mayor "
                "beneficio en la columna Profit) con las que están a un paso en cada parámetro; "
                "hacen falta al menos {passes} pasadas. Si menos del {share} de esas vecinas "
                "termina con ganancia, o su mediana conserva menos del {keep} del beneficio "
                "elegido, sale la bandera «{flag}»."
            ),
            "en": (
                "With the main export (no forward period), '{section}' compares the chosen "
                "settings (those of the tester report or, if they are not there, the highest "
                "profit in the Profit column) with those one step away on each parameter; it "
                "needs at least {passes} passes. If fewer than {share} of those neighbours end in "
                "profit, or their median keeps less than {keep} of the chosen profit, the red "
                "flag '{flag}' is raised."
            ),
            "pt": (
                "Com a exportação principal (sem período forward), '{section}' compara a "
                "configuração escolhida (a do relatório do testador ou, se ela não aparecer, a de "
                "maior lucro na coluna Profit) com as que estão a um passo em cada parâmetro; são "
                "necessárias pelo menos {passes} passadas. Se menos de {share} dessas vizinhas "
                "termina com lucro, ou a mediana delas conserva menos de {keep} do lucro "
                "escolhido, aparece a bandeira '{flag}'."
            ),
        },
    ),
    "forward": Capability(
        sources=(
            "forward:forward_review",
            "forward:is_forward",
            "plateau:FORWARD_EXPORT",
            "schema:build_inputs",
        ),
        formats=frozenset({MT5_OPTIMIZATION_XML}),
        fields={
            "section": "label:forward",
            "flag": "flag:FORWARD_NOT_HELD",
            "passes": "int:forward:MIN_PASSES",
            "plateau": "label:plateau",
        },
        text={
            "es": (
                "El formulario admite un solo XML: si subes el de una optimización con periodo "
                "forward (columnas Back Result y Forward Result), «{section}» mide si el orden del "
                "backtest se mantiene en ese tramo y si sus mejores pasadas siguen con ganancia; "
                "hacen falta al menos {passes} pasadas. Si no aguanta, sale la bandera «{flag}». "
                "Ese XML sustituye a la exportación principal, así que «{plateau}» queda como "
                "NOT_MEASURED."
            ),
            "en": (
                "The form takes a single XML: if you upload the one of an optimisation with a "
                "forward period (Back Result and Forward Result columns), '{section}' measures "
                "whether the backtest's ranking holds in that period and whether its best passes "
                "stay in profit; it needs at least {passes} passes. If it does not hold, the red "
                "flag '{flag}' is raised. That XML takes the place of the main export, so "
                "'{plateau}' stays NOT_MEASURED."
            ),
            "pt": (
                "O formulário aceita um só XML: se você enviar o de uma otimização com período "
                "forward (colunas Back Result e Forward Result), '{section}' mede se a ordem do "
                "backtest se mantém nesse trecho e se as melhores passadas continuam com lucro; "
                "são necessárias pelo menos {passes} passadas. Se não se sustenta, aparece a "
                "bandeira '{flag}'. Esse XML substitui a exportação principal, então '{plateau}' "
                "fica como NOT_MEASURED."
            ),
        },
    ),
    "same_test": Capability(
        sources=("importers:optimization_mismatch", "schema:build_inputs"),
        formats=frozenset({MT5_OPTIMIZATION_XML}),
        text={
            "es": (
                "Comprueba que el XML sea de la misma prueba que el informe del probador: si el "
                "robot, el símbolo o el marco temporal que declaran ambos archivos no coinciden, o "
                "si no comparten ningún nombre de parámetro, rechaza la subida y te dice qué "
                "difiere."
            ),
            "en": (
                "It checks that the XML comes from the same test as the tester report: if the "
                "robot, the symbol or the timeframe both files state differ, or if they share no "
                "input name, the upload is refused and you are told what differs."
            ),
            "pt": (
                "Confere se o XML é do mesmo teste que o relatório do testador: se o robô, o "
                "símbolo ou o timeframe que os dois arquivos declaram não coincidem, ou se eles "
                "não têm nenhum nome de parâmetro em comum, recusa o envio e diz o que difere."
            ),
        },
    ),
    "account_money": Capability(
        sources=("account:account_review", "account:INFLATED_MIN_GAIN"),
        formats=ACCOUNT_FORMATS,
        fields={"section": "label:account", "flag": "flag:GAIN_INFLATED_BY_FLOWS"},
        text={
            "es": (
                "«{section}» pone el % de ganancia, que quita los depósitos y retiros, junto al "
                "dinero que la cuenta ganó o perdió operando y al resultado sobre lo depositado. "
                "Si el % no se corresponde con ese dinero, sale la bandera «{flag}»."
            ),
            "en": (
                "'{section}' puts the percentage gain, which takes deposits and withdrawals out, "
                "next to the money the account made or lost by trading and the result on the "
                "money deposited. If the percentage does not match that money, the red flag "
                "'{flag}' is raised."
            ),
            "pt": (
                "'{section}' coloca a porcentagem de ganho, que tira os depósitos e saques, ao "
                "lado do dinheiro que a conta ganhou ou perdeu operando e do resultado sobre o "
                "depositado. Se a porcentagem não corresponde a esse dinheiro, aparece a bandeira "
                "'{flag}'."
            ),
        },
    ),
    "top_up": Capability(
        sources=("account:account_review", "account:TOP_UP_DRAWDOWN"),
        formats=ACCOUNT_FORMATS,
        fields={"flag": "flag:DEPOSIT_DURING_DRAWDOWN", "depth": "pct:account:TOP_UP_DRAWDOWN"},
        text={
            "es": (
                "Revisa cada depósito hecho después de la primera operación y marca los que "
                "llegaron con la cuenta al menos un {depth} por debajo de su máximo: «{flag}»."
            ),
            "en": (
                "It checks every deposit made after the first trade and marks those that arrived "
                "with the account at least {depth} below its peak: '{flag}'."
            ),
            "pt": (
                "Revisa cada depósito feito depois da primeira operação e marca os que chegaram "
                "com a conta pelo menos {depth} abaixo do seu pico: '{flag}'."
            ),
        },
    ),
    "floating_end": Capability(
        sources=(
            "importers:_parse_mt5_history",
            "importers:_parse_mt4_statement",
            "account:account_review",
            "account:FLOATING_WARN",
        ),
        formats=_MT5_HISTORY | {MT4_STATEMENT_HTML},
        fields={"flag": "flag:FLOATING_LOSS_AT_END", "share": "pct:account:FLOATING_WARN"},
        text={
            "es": (
                "Lee el resultado flotante de las posiciones que seguían abiertas al imprimir el "
                "historial y lo compara con el saldo: una pérdida abierta de al menos el {share} "
                "del saldo sale como «{flag}»."
            ),
            "en": (
                "It reads the floating result of the positions still open when the history was "
                "printed and compares it with the balance: an open loss of at least {share} of "
                "the balance is raised as '{flag}'."
            ),
            "pt": (
                "Lê o resultado flutuante das posições que seguiam abertas quando o histórico foi "
                "impresso e o compara com o saldo: uma perda aberta de pelo menos {share} do "
                "saldo aparece como '{flag}'."
            ),
        },
    ),
    "myfxbook_floating": Capability(
        sources=(
            "importers:_parse_myfxbook",
            "importers:_floating_from_open",
            "account:account_review",
            "account:FLOATING_WARN",
        ),
        formats=frozenset({MYFXBOOK_CSV}),
        fields={"flag": "flag:FLOATING_LOSS_AT_END", "share": "pct:account:FLOATING_WARN"},
        text={
            "es": (
                "Si la exportación trae el bloque «Open Trades» y algún depósito, lee el "
                "resultado flotante de esas posiciones abiertas y lo compara con el saldo que "
                "dejan los depósitos, los retiros y las operaciones cerradas: una pérdida abierta "
                "de al menos el {share} de ese saldo sale como «{flag}». Sin ese bloque no hay "
                "flotante que leer."
            ),
            "en": (
                "If the export holds the 'Open Trades' block and a deposit, it reads the floating "
                "result of those open positions and compares it with the balance the deposits, "
                "withdrawals and closed trades leave: an open loss of at least {share} of that "
                "balance is raised as '{flag}'. Without that block there is no floating result "
                "to read."
            ),
            "pt": (
                "Se a exportação trouxer o bloco 'Open Trades' e algum depósito, lê o resultado "
                "flutuante dessas posições abertas e o compara com o saldo que os depósitos, os "
                "saques e as operações fechadas deixam: uma perda aberta de pelo menos {share} "
                "desse saldo aparece como '{flag}'. Sem esse bloco não há resultado flutuante "
                "para ler."
            ),
        },
    ),
    "no_printed_balance": Capability(
        sources=("engine:_reconciliation", "engine:_NO_PRINTED_BALANCE_REASON"),
        formats=NO_BALANCE_FORMATS,
        fields={
            "recon": "integrity:recon_title",
            "reason": "integrity:recon_no_balance",
            "field": "form:report",
        },
        text={
            "es": (
                "Subido solo, en «{field}», el CSV no imprime un saldo propio, así que «{recon}» "
                "queda como NOT_MEASURED («{reason}»): no compara el saldo con cifras sacadas de "
                "las mismas filas."
            ),
            "en": (
                "Uploaded on its own, in '{field}', the CSV prints no balance of its own, so "
                "'{recon}' stays NOT_MEASURED ('{reason}'): it does not compare the balance with "
                "figures taken from the same rows."
            ),
            "pt": (
                "Enviado sozinho, em '{field}', o CSV não imprime um saldo próprio, então "
                "'{recon}' fica como NOT_MEASURED ('{reason}'): não compara o saldo com números "
                "tirados das mesmas linhas."
            ),
        },
    ),
    "live_compare": Capability(
        sources=("live:compare_live", "schema:build_inputs"),
        formats=NO_BALANCE_FORMATS,
        fields={
            "section": "label:live",
            "live": "int:live:MIN_LIVE_TRADES",
            "backtest": "int:live:MIN_BACKTEST_TRADES",
            "field": "form:live",
        },
        text={
            "es": (
                "Subido en «{field}» junto al backtest del robot, "
                "«{section}» sitúa el resultado, el % de aciertos y la peor caída de la cuenta "
                "entre historias sacadas al azar de las operaciones del backtest; hacen falta al "
                "menos {live} operaciones en la cuenta y {backtest} en el backtest."
            ),
            "en": (
                "Uploaded in '{field}' next to the robot's backtest, "
                "'{section}' places the account's result, win rate and deepest fall among "
                "histories drawn at random from the backtest's trades; it needs at least {live} "
                "trades in the account and {backtest} in the backtest."
            ),
            "pt": (
                "Enviado em '{field}' ao lado do backtest do robô, "
                "'{section}' situa o resultado, a taxa de acerto e a pior queda da conta entre "
                "históricos sorteados das operações do backtest; são necessárias pelo menos "
                "{live} operações na conta e {backtest} no backtest."
            ),
        },
    ),
    "busiest_account": Capability(
        sources=("importers:_parse_fxblue", "importers:_busiest_account"),
        formats=frozenset({FXBLUE_CSV, NINJATRADER_CSV, NINJATRADER_EXECUTIONS_CSV}),
        text={
            "es": (
                "Si el archivo trae varias cuentas, lee solo la que tiene más operaciones "
                "cerradas y lo avisa en el informe, para no mezclar saldos."
            ),
            "en": (
                "If the file holds several accounts, it reads only the one with the most closed "
                "trades and says so in the report, so balances are not mixed."
            ),
            "pt": (
                "Se o arquivo tiver várias contas, lê só a que tem mais operações fechadas e "
                "avisa no relatório, para não misturar saldos."
            ),
        },
    ),
    "cost_stress": Capability(
        sources=("engine:_costs", "costs:recost_trades", "costs:break_even_bps"),
        formats=_TRADE_LISTS,
        fields={"section": "label:costs", "times": "times:costs:DEFAULT_MULTIPLIERS"},
        text={
            "es": (
                "En «{section}» rehace el resultado con {times} veces un costo de referencia por "
                "lado y calcula el costo por lado con el que el resultado neto llega a cero."
            ),
            "en": (
                "In '{section}' it recomputes the result at {times} times a reference cost per "
                "side and works out the cost per side at which the net result reaches zero."
            ),
            "pt": (
                "Em '{section}' refaz o resultado com {times} vezes um custo de referência por "
                "lado e calcula o custo por lado com o qual o resultado líquido chega a zero."
            ),
        },
    ),
    "mt4_costs": Capability(
        sources=("importers:_parse_mt4_tester", "costs:reference_bps", "engine:_costs"),
        formats=frozenset({MT4_TESTER_HTML}),
        fields={
            "section": "label:costs",
            "times": "times:costs:DEFAULT_MULTIPLIERS",
            "bps": "number:costs:REFERENCE_BPS_WHEN_ZERO",
        },
        text={
            "es": (
                "Como el probador no desglosa comisión ni swap, «{section}» rehace el resultado "
                "con {times} veces el costo por lado que declares, o uno supuesto de {bps} puntos "
                "básicos si declaras cero, y calcula con qué costo el resultado llega a cero."
            ),
            "en": (
                "As the tester does not itemise commission or swap, '{section}' recomputes the "
                "result at {times} times the cost per side you declare, or an assumed {bps} "
                "basis points if you declare zero, and works out the cost at which the result "
                "reaches zero."
            ),
            "pt": (
                "Como o testador não detalha comissão nem swap, '{section}' refaz o resultado "
                "com {times} vezes o custo por lado que você declarar, ou um suposto de {bps} "
                "pontos-base se você declarar zero, e calcula com que custo o resultado chega a "
                "zero."
            ),
        },
    ),
    "nt_fees": Capability(
        sources=("importers:_parse_ninjatrader",),
        formats=frozenset({NINJATRADER_CSV}),
        text={
            "es": (
                "Resta de cada operación, como costo, las columnas Commission, Clearing Fee, "
                "Exchange Fee, IP Fee y NFA Fee que traiga la tabla; si todas valen cero, el "
                "informe lo avisa."
            ),
            "en": (
                "It subtracts from each trade, as a cost, the Commission, Clearing Fee, Exchange "
                "Fee, IP Fee and NFA Fee columns the grid holds; if they are all zero, the report "
                "says so."
            ),
            "pt": (
                "Desconta de cada operação, como custo, as colunas Commission, Clearing Fee, "
                "Exchange Fee, IP Fee e NFA Fee que a grade tiver; se todas forem zero, o "
                "relatório avisa."
            ),
        },
    ),
    "nt_executions": Capability(
        sources=("importers:_parse_ninjatrader_executions", "importers:FUTURES_POINT_VALUE_USD"),
        formats=frozenset({NINJATRADER_EXECUTIONS_CSV}),
        text={
            "es": (
                "Con la pestaña Executions de futuros de CME, empareja las ejecuciones por cuenta "
                "e instrumento en orden de llegada (FIFO) y valora cada operación con el valor "
                "por punto del contrato; las posiciones que siguen abiertas al final quedan fuera."
            ),
            "en": (
                "With the Executions tab of CME futures, it pairs the fills per account and "
                "instrument first in, first out and prices each trade with the contract's point "
                "value; positions still open at the end are left out."
            ),
            "pt": (
                "Com a aba Executions dos futuros da CME, pareia as execuções por conta e "
                "instrumento na ordem de chegada (FIFO) e valoriza cada operação com o valor do "
                "ponto do contrato; as posições ainda abertas no final ficam de fora."
            ),
        },
    ),
    "nt_coherence": Capability(
        sources=("importers:_parse_ninjatrader", "forensics.checks.platforms:run_NT_INVARIANTS"),
        formats=frozenset({NINJATRADER_CSV}),
        fields={"section": "integrity:forensic_title"},
        text={
            "es": (
                "Comprueba que la columna Cum. net profit sea la suma acumulada de Profit y que "
                "los números de operación no tengan huecos ni repeticiones; lo anota en "
                "«{section}»."
            ),
            "en": (
                "It checks that the Cum. net profit column is the running sum of Profit and that "
                "the trade numbers have no gaps or repeats; it notes this in '{section}'."
            ),
            "pt": (
                "Confere se a coluna Cum. net profit é a soma acumulada de Profit e se os números "
                "das operações não têm lacunas nem repetições; anota isso em '{section}'."
            ),
        },
    ),
    "tv_capital": Capability(
        sources=(
            "importers:_capital_from_percent",
            "importers:CAPITAL_FROM_PERCENT_MIN",
            "importers:_parse_tradingview_xlsx",
            "importers:_balance_curve",
        ),
        formats=_TRADINGVIEW,
        fields={"min": "number:importers:CAPITAL_FROM_PERCENT_MIN"},
        text={
            "es": (
                "Deduce el capital inicial de las columnas de P&L acumulado y su % en el CSV (si "
                "ese % llega al {min} % o más) o lo lee de las propiedades del XLSX, y el informe "
                "dice de dónde salió."
            ),
            "en": (
                "It works out the starting capital from the cumulative P&L and cumulative P&L % "
                "columns of the CSV (when that % reaches {min} % or more) or reads it from the "
                "XLSX properties, and the report says where it came from."
            ),
            "pt": (
                "Deduz o capital inicial das colunas de P&L acumulado e do seu % no CSV (se esse "
                "% chegar a {min} % ou mais) ou o lê das propriedades do XLSX, e o relatório diz "
                "de onde saiu."
            ),
        },
    ),
    "tv_coherence": Capability(
        sources=("importers:_parse_tradingview", "forensics.checks.platforms:run_TV_INVARIANTS"),
        formats=_TRADINGVIEW,
        fields={"section": "integrity:forensic_title"},
        text={
            "es": (
                "Comprueba que el P&L acumulado cuadre con la suma de las operaciones, que los "
                "números de operación no tengan huecos y que ninguna salida vaya antes de su "
                "entrada; lo anota en «{section}»."
            ),
            "en": (
                "It checks that the cumulative P&L matches the sum of the trades, that the trade "
                "numbers have no gaps and that no exit comes before its entry; it notes this in "
                "'{section}'."
            ),
            "pt": (
                "Confere se o P&L acumulado fecha com a soma das operações, se os números das "
                "operações não têm lacunas e se nenhuma saída vem antes da sua entrada; anota "
                "isso em '{section}'."
            ),
        },
    ),
    "qc_fees": Capability(
        sources=("importers:_parse_quantconnect",),
        formats=frozenset({QUANTCONNECT_TRADES_CSV}),
        text={
            "es": (
                "Resta de cada operación la columna Fees como costo MEASURED antes de las "
                "pruebas de costos."
            ),
            "en": "It subtracts each trade's Fees column as a MEASURED cost before the cost tests.",
            "pt": (
                "Desconta de cada operação a coluna Fees como custo MEASURED antes dos testes de "
                "custos."
            ),
        },
    ),
    "btpy_commission": Capability(
        sources=("importers:_parse_backtestingpy",),
        formats=frozenset({BACKTESTINGPY_CSV}),
        text={
            "es": (
                "Si la tabla trae la columna Commission, la resta como costo de cada operación; "
                "si no la trae, el informe avisa de que tu versión mete la comisión en los "
                "precios."
            ),
            "en": (
                "If the table has the Commission column, it subtracts it as each trade's cost; "
                "if not, the report says your version folds the commission into the prices."
            ),
            "pt": (
                "Se a tabela tiver a coluna Commission, ela é descontada como custo de cada "
                "operação; se não tiver, o relatório avisa que a sua versão coloca a comissão "
                "nos preços."
            ),
        },
    ),
    "vbt_fees": Capability(
        sources=("importers:_parse_vectorbt",),
        formats=frozenset({VECTORBT_CSV}),
        text={
            "es": (
                "Resta de cada operación sus columnas Entry Fees y Exit Fees como costo y deja "
                "fuera, con un aviso, las operaciones que no están cerradas."
            ),
            "en": (
                "It subtracts each trade's Entry Fees and Exit Fees columns as a cost and leaves "
                "out, with a warning, the trades that are not closed."
            ),
            "pt": (
                "Desconta de cada operação as colunas Entry Fees e Exit Fees como custo e deixa "
                "de fora, com um aviso, as operações que não estão fechadas."
            ),
        },
    ),
    "vbt_variants": Capability(
        sources=("importers:_parse_vectorbt", "schema:build_inputs", "engine:trial_count"),
        formats=frozenset({VECTORBT_CSV}),
        text={
            "es": (
                "Si el CSV trae varias variantes de parámetros (columna Column), audita la "
                "primera y las cuenta todas como intentos: el Sharpe deflactado usa ese número "
                "como MEASURED si es al menos el que declaras."
            ),
            "en": (
                "If the CSV holds several parameter variants (Column column), it audits the "
                "first and counts them all as trials: the deflated Sharpe uses that number as "
                "MEASURED when it is at least the one you declare."
            ),
            "pt": (
                "Se o CSV tiver várias variantes de parâmetros (coluna Column), audita a primeira "
                "e conta todas como tentativas: o Sharpe deflacionado usa esse número como "
                "MEASURED se for pelo menos o que você declarar."
            ),
        },
    ),
    "variants_matrix": Capability(
        sources=("schema:_parse_variants_csv", "engine:_cscv", "engine:trial_count"),
        formats=_TRADE_LISTS,
        text={
            "es": (
                "Si subes también la matriz de variantes (una columna de rendimientos por "
                "variante), cada columna cuenta como intento y el informe estima la probabilidad "
                "de sobreajuste (PBO) con validación cruzada combinatoria."
            ),
            "en": (
                "If you also upload the variants matrix (one column of returns per variant), "
                "each column counts as a trial and the report estimates the probability of "
                "backtest overfitting (PBO) with combinatorial cross-validation."
            ),
            "pt": (
                "Se você também enviar a matriz de variantes (uma coluna de retornos por "
                "variante), cada coluna conta como tentativa e o relatório estima a probabilidade "
                "de sobreajuste (PBO) com validação cruzada combinatória."
            ),
        },
    ),
    "trials_declared": Capability(
        sources=("engine:trial_count", "engine:UNDECLARED_TRIALS", "engine:_multiplicity"),
        formats=_TRADE_LISTS,
        text={
            "es": (
                "El Sharpe deflactado descuenta la suerte con el número de configuraciones que "
                "declares haber probado; si no lo declaras, calcula con 1, el caso más favorable, "
                "y lo dice."
            ),
            "en": (
                "The deflated Sharpe takes the luck out with the number of configurations you "
                "declare you tried; if you do not declare it, it computes with 1, the most "
                "favourable case, and says so."
            ),
            "pt": (
                "O Sharpe deflacionado desconta a sorte com o número de configurações que você "
                "declarar ter testado; se você não o declarar, calcula com 1, o caso mais "
                "favorável, e diz isso."
            ),
        },
    ),
    "recent_fade": Capability(
        sources=("decay:recent_review", "decay:RECENT_SHARE", "decay:DROP_Z"),
        formats=_TRADE_LISTS,
        fields={
            "section": "label:recent",
            "flag": "flag:EDGE_FADING",
            "trades": "int:decay:MIN_TRADES",
            "days": "int:decay:MIN_SPAN_DAYS",
            "parts": "parts:decay:RECENT_SHARE",
        },
        text={
            "es": (
                "«{section}» parte el historial en {parts} tramos de tiempo iguales y compara el "
                "último con los anteriores (hacen falta al menos {trades} operaciones y {days} "
                "días). Si las anteriores tenían una media positiva, las recientes no, y la caída "
                "es mayor de lo que explica el azar, sale la bandera «{flag}»."
            ),
            "en": (
                "'{section}' cuts the history into {parts} equal stretches of time and compares "
                "the last with the ones before (it needs at least {trades} trades and {days} "
                "days). If the earlier trades averaged a gain, the recent ones do not, and the "
                "drop is larger than chance explains, the red flag '{flag}' is raised."
            ),
            "pt": (
                "'{section}' divide o histórico em {parts} trechos de tempo iguais e compara o "
                "último com os anteriores (são necessárias pelo menos {trades} operações e {days} "
                "dias). Se as anteriores tinham média positiva, as recentes não, e a queda é "
                "maior do que o acaso explica, aparece a bandeira '{flag}'."
            ),
        },
    ),
    "loss_streak": Capability(
        sources=("streaks:loss_streak_review", "analytics:trade_statistics"),
        formats=_TRADE_LISTS,
        fields={"trades": "int:streaks:MIN_TRADES"},
        text={
            "es": (
                "Compara tu racha más larga de pérdidas con la que daría el azar con el mismo "
                "porcentaje de operaciones perdedoras (desde {trades} operaciones cerradas)."
            ),
            "en": (
                "It compares your longest losing streak with the one chance would give at the "
                "same share of losing trades (from {trades} closed trades)."
            ),
            "pt": (
                "Compara a sua maior sequência de perdas com a que o acaso daria com a mesma "
                "porcentagem de operações perdedoras (a partir de {trades} operações fechadas)."
            ),
        },
    ),
    "win_stats": Capability(
        sources=("analytics:trade_statistics",),
        formats=_TRADE_LISTS,
        text={
            "es": (
                "Calcula tu % de aciertos, neto de las comisiones que traiga el archivo, la "
                "ganancia y la pérdida media y el profit factor de tus operaciones cerradas."
            ),
            "en": (
                "It works out your win rate, net of the fees the file itemises, the average win "
                "and loss and the profit factor of your closed trades."
            ),
            "pt": (
                "Calcula a sua taxa de acerto, líquida das comissões que o arquivo trouxer, o "
                "ganho e a perda médios e o profit factor das suas operações fechadas."
            ),
        },
    ),
    "rh_pairing": Capability(
        sources=("importers:_parse_robinhood", "importers:OPTION_MULTIPLIER"),
        formats=frozenset({ROBINHOOD_CSV}),
        fields={"shares": "int:importers:OPTION_MULTIPLIER"},
        text={
            "es": (
                "Empareja tus compras y ventas de acciones y opciones por símbolo en orden de "
                "llegada (FIFO) y cuenta {shares} acciones por contrato; una opción que vence, se "
                "asigna o se ejerce cierra sin prima."
            ),
            "en": (
                "It pairs your stock and option buys and sells per symbol first in, first out "
                "and counts {shares} shares a contract; an option that expires, is assigned or is "
                "exercised closes at no premium."
            ),
            "pt": (
                "Pareia as suas compras e vendas de ações e opções por símbolo na ordem de "
                "chegada (FIFO) e conta {shares} ações por contrato; uma opção que vence, é "
                "atribuída ou exercida fecha sem prêmio."
            ),
        },
    ),
    "rh_unopened": Capability(
        sources=("importers:_parse_robinhood", "importers:ROBINHOOD_UNOPENED_WARNING"),
        formats=frozenset({ROBINHOOD_CSV}),
        text={
            "es": (
                "Deja fuera las ventas de posiciones que el archivo nunca muestra abiertas y las "
                "que siguen abiertas al final, y el informe dice cuántas son."
            ),
            "en": (
                "It leaves out the sales of positions the file never shows being opened and "
                "those still open at the end, and the report says how many there are."
            ),
            "pt": (
                "Deixa de fora as vendas de posições que o arquivo nunca mostra abertas e as que "
                "seguem abertas no final, e o relatório diz quantas são."
            ),
        },
    ),
    "fills_fifo": Capability(
        sources=("universal:_fills",),
        formats=frozenset({UNIVERSAL_FILLS_CSV}),
        text={
            "es": (
                "Con una fila por ejecución, empareja compras y ventas por símbolo en el orden en "
                "que ocurrieron (FIFO); las posiciones que siguen abiertas al final quedan fuera "
                "y el informe lo dice."
            ),
            "en": (
                "With one row per fill, it pairs buys and sells per symbol in the order they "
                "happened, first in, first out; positions still open at the end are left out and "
                "the report says so."
            ),
            "pt": (
                "Com uma linha por execução, pareia compras e vendas por símbolo na ordem em que "
                "aconteceram (FIFO); as posições ainda abertas no final ficam de fora e o "
                "relatório diz isso."
            ),
        },
    ),
    "columns_shown": Capability(
        sources=("universal:parse", "universal:SYNONYMS"),
        formats=_UNIVERSAL,
        fields={"example": "platform:column_profit"},
        text={
            "es": (
                "Reconoce las columnas por su nombre y el informe muestra cuál leyó como qué, por "
                "ejemplo «{example}»."
            ),
            "en": (
                "It recognises the columns by their names and the report shows which one was "
                "read as what, for example '{example}'."
            ),
            "pt": (
                "Reconhece as colunas pelo nome e o relatório mostra qual foi lida como o quê, "
                "por exemplo '{example}'."
            ),
        },
    ),
    "mapping_remembered": Capability(
        sources=("mapping:read_table", "mapping:header_signature", "mapping:usable_mapping"),
        formats=_UNIVERSAL,
        text={
            "es": (
                "Si alguna columna no se reconoce, la subida te muestra las columnas de tu "
                "archivo para que indiques cuál es cuál; con la sesión iniciada, esa elección se "
                "recuerda para la próxima exportación con las mismas columnas."
            ),
            "en": (
                "If a column is not recognised, the upload shows you your file's columns so you "
                "can say which is which; signed in, that choice is remembered for the next "
                "export with the same columns."
            ),
            "pt": (
                "Se alguma coluna não for reconhecida, o envio mostra as colunas do seu arquivo "
                "para você indicar qual é qual; com a sessão iniciada, essa escolha fica salva "
                "para a próxima exportação com as mesmas colunas."
            ),
        },
    ),
    "futures_point": Capability(
        sources=(
            "universal:_price_futures",
            "universal:FUTURES_WARNING",
            "importers:FUTURES_POINT_VALUE_USD",
            "importers:FUTURES_POINT_VALUE_OTHER",
        ),
        formats=_UNIVERSAL,
        text={
            "es": (
                "Si el archivo no trae columna de resultado ni de multiplicador, los futuros con "
                "código de contrato (por ejemplo ESZ6) se valoran con el valor por punto que "
                "publica su bolsa y el informe lista cuál usó."
            ),
            "en": (
                "If the file has no result column and no multiplier column, futures with a "
                "contract code (ESZ6, for example) are priced with the point value their "
                "exchange publishes and the report lists the one it used."
            ),
            "pt": (
                "Se o arquivo não tiver coluna de resultado nem de multiplicador, os futuros com "
                "código de contrato (por exemplo ESZ6) são valorizados com o valor do ponto que a "
                "sua bolsa publica e o relatório lista qual usou."
            ),
        },
    ),
}

#: Two to four points per guide, in the order the page lists them.
GUIDE_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "mt5": ("balance_rebuilt", "platform_drawdown", "history_money", "trials_or_xml"),
    "cuenta-proveedor": ("account_money", "top_up", "floating_end", "mt5_history_balance"),
    "mt5-optimization": ("passes_counted", "plateau", "forward", "same_test"),
    "mt4": ("mt4_tester_balance", "history_money", "mt4_costs", "recent_fade"),
    "tradingview": ("tv_capital", "tv_coherence", "cost_stress", "trials_declared"),
    "ninjatrader": ("nt_fees", "nt_executions", "nt_coherence", "busiest_account"),
    "quantconnect": ("qc_fees", "cost_stress", "trials_declared", "recent_fade"),
    "backtesting-py": ("btpy_commission", "cost_stress", "trials_declared", "loss_streak"),
    "vectorbt": ("vbt_variants", "variants_matrix", "vbt_fees", "cost_stress"),
    "myfxbook": ("account_money", "top_up", "myfxbook_floating", "no_printed_balance"),
    "mql5-signal": ("account_money", "top_up", "live_compare", "no_printed_balance"),
    "fxblue": ("account_money", "busiest_account", "live_compare", "no_printed_balance"),
    "robinhood": ("rh_pairing", "rh_unopened", "win_stats", "loss_streak"),
    "zerodha": ("fills_fifo", "win_stats", "recent_fade", "cost_stress"),
    "csv-universal": ("columns_shown", "mapping_remembered", "fills_fifo", "futures_point"),
}

#: The free tool that fits each guide: the luck calculator for optimised
#: backtests, the win-rate calculator for account and trade histories.
GUIDE_TOOL: dict[str, str] = {
    "mt5": "calculator",
    "cuenta-proveedor": "winrate",
    "mt5-optimization": "calculator",
    "mt4": "calculator",
    "tradingview": "calculator",
    "ninjatrader": "calculator",
    "quantconnect": "calculator",
    "backtesting-py": "calculator",
    "vectorbt": "calculator",
    "myfxbook": "winrate",
    "mql5-signal": "winrate",
    "fxblue": "winrate",
    "robinhood": "winrate",
    "zerodha": "winrate",
    "csv-universal": "winrate",
}

#: One line under each guide's heading: what this file lets the report do.
GUIDE_PURPOSE: dict[str, dict[str, str]] = {
    "mt5": {
        "es": (
            "Con este informe, Rigor rehace el saldo operación por operación, lo compara con el "
            "que imprime MT5 y descuenta del Sharpe la suerte de las configuraciones que probaste."
        ),
        "en": (
            "With this report, Rigor rebuilds the balance trade by trade, compares it with the "
            "one MT5 prints and takes the luck of the configurations you tried out of the Sharpe."
        ),
        "pt": (
            "Com este relatório, o Rigor refaz o saldo operação por operação, compara com o que "
            "o MT5 imprime e desconta do Sharpe a sorte das configurações que você testou."
        ),
    },
    "cuenta-proveedor": {
        "es": (
            "Con este historial, Rigor separa lo que la cuenta ganó o perdió operando de lo que "
            "entró y salió en depósitos y retiros, antes de que copies o inviertas."
        ),
        "en": (
            "With this history, Rigor separates what the account made or lost by trading from "
            "the money paid in and out, before you copy or invest."
        ),
        "pt": (
            "Com este histórico, o Rigor separa o que a conta ganhou ou perdeu operando do que "
            "entrou e saiu em depósitos e saques, antes que você copie ou invista."
        ),
    },
    "mt5-optimization": {
        "es": (
            "Con este archivo, Rigor cuenta cuántas configuraciones probaste y descuenta la "
            "suerte del Sharpe de la que elegiste."
        ),
        "en": (
            "With this file, Rigor counts how many configurations you tried and takes the luck "
            "out of the Sharpe of the one you chose."
        ),
        "pt": (
            "Com este arquivo, o Rigor conta quantas configurações você testou e desconta a "
            "sorte do Sharpe da que você escolheu."
        ),
    },
    "mt4": {
        "es": (
            "Con este informe, Rigor mide si el resultado aguanta costos más altos y si sigue "
            "funcionando en el tramo más reciente."
        ),
        "en": (
            "With this report, Rigor measures whether the result holds up under higher costs and "
            "whether it still works in the most recent stretch."
        ),
        "pt": (
            "Com este relatório, o Rigor mede se o resultado aguenta custos mais altos e se "
            "continua funcionando no trecho mais recente."
        ),
    },
    "tradingview": {
        "es": (
            "Con esta lista, Rigor busca tu capital inicial en el propio archivo, revisa que la "
            "lista cuadre consigo misma y descuenta del Sharpe la suerte de las configuraciones "
            "que probaste."
        ),
        "en": (
            "With this list, Rigor looks for your starting capital in the file itself, checks "
            "that the list adds up and takes the luck of the configurations you tried out of "
            "the Sharpe."
        ),
        "pt": (
            "Com esta lista, o Rigor procura o seu capital inicial no próprio arquivo, confere "
            "se a lista fecha consigo mesma e desconta do Sharpe a sorte das configurações que "
            "você testou."
        ),
    },
    "ninjatrader": {
        "es": (
            "Con esta tabla, Rigor resta las comisiones y tasas de cada operación y revisa que "
            "el beneficio acumulado cuadre con las operaciones."
        ),
        "en": (
            "With this grid, Rigor subtracts each trade's commission and fees and checks that "
            "the cumulative net profit adds up to the trades."
        ),
        "pt": (
            "Com esta grade, o Rigor desconta a comissão e as taxas de cada operação e confere "
            "se o lucro acumulado fecha com as operações."
        ),
    },
    "quantconnect": {
        "es": (
            "Con este CSV, Rigor resta las comisiones de cada operación y busca el costo por "
            "lado con el que tu resultado llega a cero."
        ),
        "en": (
            "With this CSV, Rigor subtracts each trade's fees and finds the cost per side at "
            "which your result reaches zero."
        ),
        "pt": (
            "Com este CSV, o Rigor desconta as taxas de cada operação e encontra o custo por "
            "lado com o qual o seu resultado chega a zero."
        ),
    },
    "backtesting-py": {
        "es": (
            "Con este CSV, Rigor mide si tu resultado aguanta costos más altos y si tu peor "
            "racha de pérdidas es más larga de lo que daría el azar."
        ),
        "en": (
            "With this CSV, Rigor measures whether your result holds up under higher costs and "
            "whether your worst losing streak is longer than chance would give."
        ),
        "pt": (
            "Com este CSV, o Rigor mede se o seu resultado aguenta custos mais altos e se a sua "
            "pior sequência de perdas é mais longa do que o acaso daria."
        ),
    },
    "vectorbt": {
        "es": (
            "Con este CSV, Rigor cuenta como intentos las variantes de parámetros que traiga y "
            "descuenta esa suerte del Sharpe de la que audita."
        ),
        "en": (
            "With this CSV, Rigor counts the parameter variants it holds as trials and takes "
            "that luck out of the Sharpe of the one it audits."
        ),
        "pt": (
            "Com este CSV, o Rigor conta como tentativas as variantes de parâmetros que ele "
            "tiver e desconta essa sorte do Sharpe da que audita."
        ),
    },
    "myfxbook": {
        "es": (
            "Con este CSV, Rigor separa el resultado de operar de los depósitos y retiros y, si "
            "la exportación trae las posiciones abiertas y los depósitos, avisa si esas "
            "posiciones cargan una pérdida que el saldo no muestra."
        ),
        "en": (
            "With this CSV, Rigor separates the trading result from deposits and withdrawals "
            "and, when the export lists the open positions and the deposits, warns if those "
            "positions carry a loss the balance does not show."
        ),
        "pt": (
            "Com este CSV, o Rigor separa o resultado das operações dos depósitos e saques e, se "
            "a exportação trouxer as posições abertas e os depósitos, avisa se essas posições "
            "carregam uma perda que o saldo não mostra."
        ),
    },
    "mql5-signal": {
        "es": (
            "Con este CSV, Rigor separa lo que la señal ganó o perdió operando de sus depósitos "
            "y retiros, y marca los depósitos hechos en plena caída."
        ),
        "en": (
            "With this CSV, Rigor separates what the signal made or lost by trading from its "
            "deposits and withdrawals, and marks deposits made deep in a drawdown."
        ),
        "pt": (
            "Com este CSV, o Rigor separa o que o sinal ganhou ou perdeu operando dos seus "
            "depósitos e saques, e marca os depósitos feitos em plena queda."
        ),
    },
    "fxblue": {
        "es": (
            "Con este CSV, Rigor separa lo que la cuenta ganó o perdió operando de sus depósitos "
            "y retiros y, junto al backtest del robot, compara la cuenta con la prueba."
        ),
        "en": (
            "With this CSV, Rigor separates what the account made or lost by trading from its "
            "deposits and withdrawals and, next to the robot's backtest, compares the account "
            "with the test."
        ),
        "pt": (
            "Com este CSV, o Rigor separa o que a conta ganhou ou perdeu operando dos seus "
            "depósitos e saques e, ao lado do backtest do robô, compara a conta com o teste."
        ),
    },
    "robinhood": {
        "es": (
            "Con este informe, Rigor convierte tus compras y ventas en operaciones cerradas, "
            "opciones incluidas, y mide tu % de aciertos y tus rachas de pérdidas."
        ),
        "en": (
            "With this report, Rigor turns your buys and sells into closed trades, options "
            "included, and measures your win rate and your losing streaks."
        ),
        "pt": (
            "Com este relatório, o Rigor transforma as suas compras e vendas em operações "
            "fechadas, opções incluídas, e mede a sua taxa de acerto e as suas sequências de "
            "perdas."
        ),
    },
    "zerodha": {
        "es": (
            "Con este Tradebook, Rigor empareja tus compras y ventas en el orden en que "
            "ocurrieron y somete tus operaciones a las mismas pruebas que un backtest."
        ),
        "en": (
            "With this Tradebook, Rigor pairs your buys and sells in the order they happened "
            "and puts your trades through the same tests as a backtest."
        ),
        "pt": (
            "Com este Tradebook, o Rigor pareia as suas compras e vendas na ordem em que "
            "aconteceram e submete as suas operações aos mesmos testes de um backtest."
        ),
    },
    "csv-universal": {
        "es": (
            "Con tu historial, Rigor reconoce las columnas por su nombre, te enseña cuál leyó "
            "como qué y somete tus operaciones a las mismas pruebas que un backtest."
        ),
        "en": (
            "With your history, Rigor recognises the columns by their names, shows you which "
            "one it read as what and puts your trades through the same tests as a backtest."
        ),
        "pt": (
            "Com o seu histórico, o Rigor reconhece as colunas pelo nome, mostra qual leu como "
            "o quê e submete as suas operações aos mesmos testes de um backtest."
        ),
    },
}

_AND = {"es": "y", "en": "and", "pt": "e"}
#: How many equal parts a share such as ``1/3`` cuts a span into, in words.
_PARTS = {
    "es": {2: "dos", 3: "tres", 4: "cuatro", 5: "cinco"},
    "en": {2: "two", 3: "three", 4: "four", 5: "five"},
    "pt": {2: "dois", 3: "três", 4: "quatro", 5: "cinco"},
}


def resolve(reference: str) -> Any:
    """The object a ``module:attribute`` reference under ``quant_trade.audit`` names."""
    module, _, name = reference.partition(":")
    found: Any = importlib.import_module(f"{PACKAGE}.{module}")
    for part in name.split("."):
        found = getattr(found, part)
    return found


def _figure(value: float, locale: str) -> str:
    from quant_trade.audit.public_card import _num

    return _num(value, locale, 0 if float(value).is_integer() else 1)


def _listed(items: Sequence[str], locale: str) -> str:
    if len(items) < 2:
        return "".join(items)
    return f"{', '.join(items[:-1])} {_AND[locale]} {items[-1]}"


def field_value(spec: str, locale: str) -> str:
    """A name or figure the report itself uses, from ``kind:reference``.

    ``label``, ``integrity``, ``kpi`` and ``platform`` are the report's own titles
    (``report.LABELS``, ``INTEGRITY_TEXT``, ``KEY_LABELS``, ``PLATFORM_LABELS``);
    ``form`` an upload field's label on the form (``pages._COPY``) without its
    "(optional)"; ``flag`` a red flag's title; ``pct``, ``int``, ``number`` and
    ``times`` a constant (``module:NAME``) as a percentage, a whole number, a
    number or a list of multiples, with the language's decimal mark; ``parts``
    a share (``1/3``) as the number of equal parts it makes, in words. A share
    that makes no whole number of parts raises, so the text is rewritten
    rather than wrong.
    """
    from quant_trade.audit import report
    from quant_trade.audit.redflags import FLAG_TITLES

    kind, _, reference = spec.partition(":")
    tables = {
        "label": report.LABELS,
        "integrity": report.INTEGRITY_TEXT,
        "kpi": report.KEY_LABELS,
        "platform": report.PLATFORM_LABELS,
    }
    if kind in tables:
        return str(tables[kind][locale][reference])
    if kind == "flag":
        return FLAG_TITLES[reference][locale]
    if kind == "form":
        # Lazy: pages imports this module.
        from quant_trade.audit.pages import _COPY

        return re.sub(r"\s*\([^()]*\)$", "", str(_COPY[locale][reference]))
    value = resolve(reference)
    if kind == "pct":
        return f"{_figure(round(float(value) * 100, 6), locale)} %"
    if kind in ("int", "number"):
        return _figure(float(value), locale)
    if kind == "times":
        return _listed([_figure(float(item), locale) for item in value], locale)
    if kind == "parts":
        parts = 1 / float(value)
        if round(parts) < 2 or abs(parts - round(parts)) > 1e-9:
            raise ValueError(f"{spec} does not cut a span into equal parts")
        return _PARTS[locale].get(round(parts), str(round(parts)))
    raise ValueError(f"unknown field kind: {spec}")


def capability_text(key: str, locale: str) -> str:
    """One point in ``locale``, its names and figures read from the code."""
    capability = CAPABILITIES[key]
    values = {name: field_value(spec, locale) for name, spec in capability.fields.items()}
    return capability.text[locale].format(**values)


def guide_points(slug: str, locale: str) -> list[str]:
    """What the report does with the file of the guide ``slug`` (its Spanish slug)."""
    return [capability_text(key, locale) for key in GUIDE_CAPABILITIES.get(slug, ())]


def guide_purpose(slug: str, locale: str) -> str:
    """The guide's line under its heading; "" for a guide without one."""
    return GUIDE_PURPOSE.get(slug, {}).get(locale, "")


__all__ = [
    "CAPABILITIES",
    "GUIDE_CAPABILITIES",
    "GUIDE_FORMATS",
    "GUIDE_PURPOSE",
    "GUIDE_TOOL",
    "NO_BALANCE_FORMATS",
    "PRINTED_BALANCE_FORMATS",
    "Capability",
    "capability_text",
    "field_value",
    "guide_points",
    "guide_purpose",
    "resolve",
]
