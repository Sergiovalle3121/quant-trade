"""Portuguese (pt-BR) texts of the audit report, installed next to Spanish and English.

Each table holds the Portuguese of module constants whose Spanish and English
sit side by side in that module; :func:`install` adds them under "pt", over the
English, so a text still missing in Portuguese reads in English, never blank.
``RULES`` gives the Portuguese of the engine's English notes, as
``i18n._RULES_SOURCE`` gives the Spanish; it also covers the questions and
assumptions a result stores in Spanish and English only, so the stored result
(and its hash) stays the same whatever languages the report adds.
"""

from __future__ import annotations

from typing import Any


def install(namespace: dict[str, Any], texts: dict[str, Any]) -> None:
    """Add ``texts`` under "pt" to the {"es", "en"} constants of ``namespace``."""
    for name, portuguese in texts.items():
        target = namespace[name]
        if "en" in target:
            target["pt"] = _over_english(target["en"], portuguese)
            continue
        # A table of items, each with its own {"es", "en"} texts.
        for key, text in portuguese.items():
            target[key]["pt"] = _over_english(target[key]["en"], text)


def _over_english(english: Any, portuguese: Any) -> Any:
    if isinstance(english, dict) and isinstance(portuguese, dict):
        return {**english, **portuguese}
    return portuguese


REPORT: dict[str, Any] = {
    "LABELS": {
        "title": "Rigor · Auditoria de backtest",
        "title_fund": "Rigor · Auditoria de histórico de fundo",
        "fund_net": (
            "Rentabilidades declaradas líquidas de taxas: são os números do próprio fundo após "
            "suas taxas, e o Rigor não mediu os custos."
        ),
        "generated": "Gerado",
        "audit_id": "Identificador",
        "inputs": "Arquivos auditados (sha256)",
        "verdict": "Veredito",
        "dimensions": "Dimensões",
        "dimension": "Dimensão",
        "status": "Status",
        "reasons": "Motivos",
        "performance": "Desempenho anualizado",
        "significance": "Significância estatística",
        "multiplicity": "Multiplicidade (número de tentativas)",
        "sensitivity": "Sensibilidade do Sharpe deflacionado ao número de tentativas",
        "bootstrap": "Bootstrap estacionário (por período)",
        "holdout": "Fora da amostra declarado",
        "costs": "Custos de operação",
        "benchmark": "Benchmark fornecido",
        "cscv": "Sobreajuste por validação cruzada combinatória (CSCV)",
        "subperiods": "Subperíodos (anos-calendário)",
        "rolling": "Janelas móveis",
        "red_flags": "Bandeiras vermelhas",
        "not_measured": "Não medido",
        "declared": "Declarado pelo cliente",
        "metric": "Métrica",
        "value": "Valor",
        "evidence": "Evidência",
        "note": "Nota",
        "none": "nenhuma",
        "flags_none": "Nenhuma bandeira vermelha nos arquivos auditados.",
        "trials": "tentativas",
        "expected_max": "Sharpe máximo esperado sem habilidade",
        "dsr": "Sharpe deflacionado (DSR)",
        "multiplier": "Multiplicador",
        "cost_recomputed": (
            "Esta tabela recalcula cada operação com seus preços e seu tamanho: sem custo extra "
            "dá {table}, {gap} de diferença em relação ao resultado líquido das operações "
            "({trades}), por arredondamento de preços ou conversão de moeda."
        ),
        "bps": "pb por lado",
        "gross": "Bruto",
        "cost": "Custo",
        "net": "Líquido",
        "win_rate": "Taxa de acerto",
        "win_rate_gross": "Taxa de acerto antes das taxas",
        "trades": "Operações",
        "in_sample": "Na amostra",
        "out_of_sample": "Fora da amostra",
        "year": "Ano",
        "return": "Retorno",
        "max_drawdown": "Drawdown máximo",
        "window": "Janela",
        "min_return": "Retorno mínimo",
        "min_drawdown": "Drawdown mínimo",
        "share_negative": "Fração negativa",
        "code": "Código",
        "severity": "Severidade",
        "detail": "Detalhe",
        "warnings": "Avisos de leitura",
        "client_text": "Descrição do cliente",
        "client_text_none": "Nenhuma descrição da estratégia foi escrita.",
        "chars": "{n} caracteres",
        "client_text_note": (
            "A descrição não é reproduzida neste relatório; ela consta no JSON. Expressões de "
            "promessa de resultados detectadas nela"
        ),
        "seal": "Selo do holdout declarado",
        "pay": "Pagar com cartão",
        "pay_pack": "Comprar o pacote de 3 (USD {price:.0f})",
        "pay_secure": (
            "Pagamento seguro com Stripe. Você vê o relatório completo assim que o pagamento é "
            "confirmado; nós nunca vemos nem guardamos os dados do seu cartão."
        ),
        "pay_links_note": (
            "O pagamento abre em outra aba. Quando terminar, volte aqui: o relatório é "
            "desbloqueado assim que a Stripe confirma o pagamento."
        ),
        "paid_check": "Já paguei: ver meu relatório",
        "buy_code_alt": "Prefere pagar por transferência? Peça um código aqui",
        "pack_left": (
            "Restam {n} relatórios no seu pacote. Para usá-los, digite este código ao "
            "desbloquear seus próximos relatórios:"
        ),
        "pack_used": "Você já usou os relatórios do seu pacote (código {code}).",
        "pack_keep": "Guarde-o: ele também aparece aqui sempre que você abre este relatório.",
        "locked": "Seção disponível no relatório completo",
        "disclaimer": "Aviso",
        "json_sha": "sha256 do JSON da auditoria",
        "thresholds": "Limites aplicados",
        "print": "Imprimir / salvar PDF",
        "pdf": "Baixar PDF",
        "obs": "observações",
        "source_equity": "curva de patrimônio",
        "source_returns": "série de retornos",
        "variance_policy": (
            "Variância usada: a maior entre a observada nas variantes que você enviou e a que o "
            "erro de amostragem produz."
        ),
        "pdf_long": "Baixar o relatório em PDF",
        "pdf_busy": "Gerando seu PDF… (alguns segundos)",
        "pdf_wait": "O PDF leva alguns segundos para ser gerado.",
        "pdf_check": "Quem receber o PDF ou o JSON pode conferir que ele não foi editado.",
        "pdf_check_link": "Como conferir",
        "switch": "Español",
        "my_account": "Minha conta",
        "yes": "sim",
        "no": "não",
        "redeem": "Tem um código de acesso? Digite-o para ver o relatório completo",
        "redeem_button": "Resgatar código",
        "code_error": (
            "Esse código não desbloqueou o relatório: não existe, já foi usado ou expirou. "
            "Copie-o exatamente como o recebeu e resgate-o novamente."
        ),
        "code_error_contact": "Se continuar sem funcionar, escreva para nós pelo botão acima.",
        "buy_code": "Comprar pelo WhatsApp",
        "buy_code_how": (
            "Você nos escreve pelo WhatsApp; a mensagem já leva o número deste "
            "relatório.|Respondemos com os dados para pagamento.|Quando o pagamento é "
            "confirmado, você recebe um código: digite-o aqui embaixo e o relatório abre "
            "completo."
        ),
        "buy_code_wait": (
            "Quem responde é uma pessoa. Se você escrever à noite ou no fim de semana, "
            "respondemos assim que virmos; enquanto isso, seu relatório continua neste link."
        ),
        "generic_rules": "Regras de referência genéricas, não as de uma empresa específica.",
        "unlock_jump": "Desbloquear o relatório completo",
        "unlock_nav": "Desbloquear",
        "account": "O dinheiro real da conta",
        "test_data": "Com quais dados o teste foi feito",
        "capital": "Quanto capital é necessário e em que tamanho",
        "plateau": "Pico isolado ou platô?",
        "plateau_intro": (
            "Comparamos a configuração escolhida com as que estão a um passo em cada parâmetro "
            "dentro do seu arquivo de otimização. Se, ao mover um parâmetro um passo, o "
            "resultado desaba, a configuração foi ajustada ao ruído do histórico."
        ),
        "plateau_by_report": "Escolhida: a que coincide com as entradas do relatório do testador.",
        "plateau_by_best": (
            "Escolhida: a passada com maior lucro, porque o relatório não traz entradas que "
            "coincidam com uma passada."
        ),
        "plateau_keep": "Do lucro escolhido que os vizinhos conservam (mediana).",
        "plateau_in_profit": "Dos vizinhos que terminam com lucro.",
        "plateau_neighbours": "Vizinhos a um passo",
        "plateau_parameter": "Parâmetro",
        "plateau_value": "Valor",
        "plateau_result": "Lucro",
        "plateau_clean": "Os vizinhos conservam boa parte do resultado: parece um platô.",
        "plateau_peak": (
            "Os vizinhos perdem boa parte do resultado: parece um pico isolado. Isso também "
            "aparece nas bandeiras vermelhas."
        ),
        "plateau_badge_clean": "Platô",
        "plateau_badge_peak": "Pico isolado",
        "plateau_forward_hint": (
            "Se você ativar o período forward no testador do MT5 e enviar essa otimização, o "
            "relatório acrescenta “Aguenta no período forward?”: compara cada configuração no "
            "período otimizado e em um posterior que o otimizador não usou para escolher."
        ),
        "forward": "Aguenta no período forward?",
        "forward_intro": (
            "O MetaTrader pode testar as mesmas configurações em um período posterior que o "
            "otimizador não usou para escolher (forward). Comparamos a ordem que o backtest dá "
            "com o que acontece depois nesse período."
        ),
        "forward_rank": (
            "Correlação de postos entre backtest e forward (1 = mesma ordem, 0 = sem relação)."
        ),
        "forward_top": "Das {n} melhores passadas do backtest terminam o forward com ganho.",
        "forward_all": "De todas as passadas terminam o forward com ganho.",
        "forward_chosen": "Das demais passadas ficam abaixo da escolhida no forward.",
        "forward_held": "As melhores passadas do backtest continuam à frente no período forward.",
        "forward_lost": (
            "A ordem do backtest não se sustenta no período forward. Isso também aparece nas "
            "bandeiras vermelhas."
        ),
        "forward_badge_held": "Aguenta",
        "forward_badge_lost": "Não aguenta",
        "capital_intro": (
            "Quanto dinheiro é preciso para que um ano ruim não leve mais que certa porcentagem "
            "da conta, com as operações deste arquivo. Sorteamos {samples:,} anos de operações "
            "ao acaso e tomamos a queda que só 5 % deles superam, ou a do próprio histórico, se "
            "for maior."
        ),
        "capital_fall": "Queda de referência em dinheiro, no tamanho do backtest.",
        "capital_history": "Maior queda do histórico na sua própria ordem.",
        "capital_platform": "Drawdown da plataforma com operações abertas.",
        "capital_short": (
            "Atenção: o arquivo cobre só {days} dias. Estes números estendem esse trecho para um "
            "ano e podem ficar aquém ou passar do ponto; tome-os como ordem de grandeza e peça "
            "um histórico de pelo menos um ano antes de definir o capital."
        ),
        "capital_limit": "Se você aceita perder até",
        "capital_needed": "Capital necessário no tamanho do backtest",
        "capital_scale": "Tamanho sobre o saldo inicial do arquivo ({balance})",
        "capital_scale_plain": "Tamanho sobre o saldo inicial",
        "capital_scale_help": (
            "1x é o tamanho de lote do backtest; 0.50x é a metade. Acima de 1x, a queda em "
            "dinheiro cresce na mesma proporção."
        ),
        "capital_fall_account": "Queda de referência em dinheiro, no tamanho que a conta usou.",
        "capital_needed_account": "Capital necessário no tamanho que a conta usou",
        "capital_scale_help_account": (
            "1x é o tamanho de lote que a conta usou; 0.50x é a metade. Acima de 1x, a queda em "
            "dinheiro cresce na mesma proporção."
        ),
        "capital_open_loss": (
            "Sua plataforma imprime um drawdown de {platform} com as operações abertas, contra "
            "{closed} com as fechadas. Esta seção só vê as operações fechadas: com as perdas "
            "abertas é preciso mais capital do que o da tabela."
        ),
        "capital_open_loss_floored": (
            "Sua plataforma imprime um drawdown de {platform} com as operações abertas, contra "
            "{closed} com as fechadas. Por isso os números de capital usam no mínimo o drawdown "
            "em dinheiro que a plataforma imprime com as operações abertas."
        ),
        "capital_closed_only": (
            "Só conta operações fechadas: as perdas das posições enquanto ainda estavam abertas "
            "não entram, então o capital necessário pode ser maior."
        ),
        "what_to_do": "O que fazer:",
        "capital_missing": (
            "Para calcular o capital e o tamanho, envie pelo menos 30 operações fechadas "
            "distribuídas em 3 meses ou mais do mesmo sistema; com um ano completo os números "
            "ficam mais firmes."
        ),
        "test_data_intro": (
            "O cabeçalho do relatório diz como os preços foram simulados, que parte do histórico "
            "o testador teve e quais datas foram testadas. Vale a pena conferir, então aqui o "
            "comparamos com as próprias operações."
        ),
        "test_data_clean": (
            "A modelagem, a qualidade dos dados e as datas declaradas não levantam nenhuma "
            "bandeira."
        ),
        "test_data_scope": (
            "Lido do cabeçalho tal como você o enviou: se alguém o editou, só detectamos quando "
            "ele não bate consigo mesmo ou com as operações."
        ),
        "account_intro": (
            "A porcentagem de ganho que os sites de históricos mostram exclui os depósitos e os "
            "saques. Aqui a colocamos ao lado do dinheiro que a conta ganhou ou perdeu operando, "
            "dos depósitos feitos em plena perda e das posições que continuavam abertas ao "
            "imprimir o histórico."
        ),
        "account_backtest": (
            "Esta revisão é para históricos de contas reais ou demo do MetaTrader 4 ou 5. Seu "
            "arquivo é um backtest."
        ),
        "account_gain": "Ganho em %, como os sites de históricos o mostram.",
        "account_money": "Resultado de operar, em dinheiro, sobre {deposited} depositados.",
        "account_floating": "Perda aberta sobre o saldo ao imprimir o histórico.",
        "account_clean": (
            "Não vimos depósitos em plena perda, nem uma perda aberta grande, nem uma "
            "porcentagem que se afaste do dinheiro."
        ),
        "account_clean_unseen": (
            "Não vimos depósitos em plena perda nem uma porcentagem que se afaste do dinheiro. O "
            "arquivo não diz quanto as posições abertas estavam perdendo: peça ao provedor a "
            "curva de patrimônio com o flutuante."
        ),
        "account_live": (
            "Revisão do histórico que você enviou como conta real. Suas bandeiras aparecem aqui "
            "e não mudam a classe do backtest."
        ),
        "account_deposits": "Depósitos depois de começar a operar, do maior para o menor",
        "account_date": "Data",
        "account_amount": "Valor",
        "account_before": "Saldo antes",
        "account_drawdown": "Drawdown na época",
        "account_scope": (
            "Lido do arquivo tal como você o enviou; nada foi conferido com a corretora."
        ),
        "account_trimmed_badge": "Para perguntar",
        "account_near_empty": (
            "Em {date} uma operação ganhou ou perdeu mais do que um saque havia deixado na "
            "conta: operou-se com a conta quase vazia ({days}). Uma porcentagem calculada sobre "
            "quase nada dispara, então medimos esses dias sobre o saldo de antes do saque. "
            "Pergunte por que quase tudo foi sacado e se continuou operando com o que sobrou."
        ),
        "account_near_empty_days": "{n} dia",
        "account_near_empty_days_many": "{n} dias",
        "account_trimmed": (
            "O arquivo começa com operações em {date}, sem o depósito que abriu a conta: pode "
            "faltar o início do histórico. O ganho em % é medido a partir do primeiro saldo do "
            "arquivo. Peça a exportação completa desde a abertura da conta."
        ),
        "luck": "Quanto sobra ao descontar a sorte?",
        "luck_intro": (
            "Quanto mais configurações se testam, mais alta sai a melhor, mesmo que nenhuma "
            "tenha vantagem. Aqui colocamos o Sharpe do arquivo ao lado do que a pura sorte "
            "daria com as configurações contadas, com a matemática publicada de Bailey e López "
            "de Prado e de Harvey e Liu. É a mesma conta que decide a dimensão «Número de "
            "configurações testadas», dita em números."
        ),
        "luck_badge_beats": "Supera a sorte",
        "luck_badge_below": "Não supera a sorte",
        "luck_badge_narrow": "Supera a sorte, sem margem",
        "luck_narrow": (
            "O Sharpe de {sharpe} supera o {luck} que {n} configurações sem habilidade dariam, "
            "mas não com a margem que exigimos: a confiança de que não seja sorte (DSR) é de "
            "{dsr}, e para cumprir esta dimensão exigimos {need}."
        ),
        "luck_beats": (
            "O Sharpe de {sharpe} supera o {luck} que {n} configurações sem habilidade dariam."
        ),
        "luck_below": (
            "Com {n} configurações, a pura sorte daria um Sharpe de {luck}, igual ou maior que o "
            "{sharpe} deste histórico."
        ),
        "luck_sharpe": (
            "Sharpe que {n} configurações sem habilidade dariam (o do arquivo: {sharpe})"
        ),
        "luck_years": (
            "Anos de histórico com os quais essa sorte fica abaixo deste Sharpe (o arquivo tem "
            "{span})"
        ),
        "luck_after": "Sharpe que sobra após descontar {n} configurações (Harvey e Liu)",
        "luck_years_unit": "anos",
        "luck_uncounted": (
            "Os arquivos não dizem quantas configurações foram testadas antes de escolher esta. "
            "A tabela mostra quanto histórico seria necessário conforme quantas fossem: pergunte "
            "ao vendedor."
        ),
        "luck_span_line": "Sharpe do arquivo: {sharpe}. Histórico: {span}.",
        "luck_table_trials": "Configurações testadas",
        "luck_table_luck": "Sharpe que a sorte daria",
        "luck_table_years": "Histórico necessário",
        "luck_table_enough": "Este histórico basta?",
        "luck_short": (
            "Com menos de um ano de histórico, um Sharpe anualizado muda muito com poucos dados: "
            "tome-o como ordem de grandeza."
        ),
        "luck_more_than": "mais de {n} anos",
        "luck_months": "{n} meses",
        "luck_month_one": "1 mês",
        "luck_under_month": "menos de 1 mês",
        "ride": "Como foi viver este histórico",
        "ride_intro": (
            "Um total e uma queda máxima não dizem como foi viver o histórico: quanto tempo "
            "passou sem uma nova máxima, quanto demorou para voltar a pior queda e como foram o "
            "pior dia e o pior mês. São os números que fazem alguém desligar um sistema."
        ),
        "ride_days": "{n} dias",
        "ride_under": "Maior tempo sem uma nova máxima ({start} a {end})",
        "ride_under_open": (
            "Tempo sem uma nova máxima desde {start}: continua em aberto no fim do arquivo"
        ),
        "ride_fall": "Pior queda: dias da máxima ({start}) à mínima ({low})",
        "ride_recovery": "Dias desde essa mínima até voltar à máxima",
        "ride_not_back": "sem voltar",
        "ride_not_back_note": "A pior queda não se recupera antes da última data do arquivo.",
        "ride_worst_day": "Pior dia ({date})",
        "ride_worst_month": "Pior mês ({month})",
        "ride_positive": (
            "Meses no positivo ({k} de {n}); maior sequência de meses no negativo: {run}"
        ),
        "ride_closed": (
            "A curva é reconstruída com operações fechadas: as perdas abertas não aparecem, "
            "então as quedas reais duraram e mediram pelo menos isto."
        ),
        "recent": "Continua funcionando no período recente?",
        "recent_intro": (
            "Um histórico longo pode parecer bom no total mesmo que seu último trecho já não "
            "some. Dividimos o tempo do histórico em três trechos iguais e comparamos o último "
            "com os dois anteriores, operação por operação."
        ),
        "recent_early": "Média por operação antes de {date}",
        "recent_late": "Média por operação desde {date}",
        "recent_net": "Resultado líquido desde {date} ({n} operações)",
        "recent_z": (
            "Distância entre as duas médias, em erros-padrão (-2 ou menos: uma queda que o acaso "
            "dificilmente explica)"
        ),
        "recent_held": (
            "O último terço do histórico não mostra uma queda para perdas que o acaso não explique."
        ),
        "recent_faded": (
            "O último terço do histórico tem média zero ou de perda por operação, uma queda que "
            "o acaso dificilmente explica. Isso também aparece nas bandeiras vermelhas."
        ),
        "recent_badge_held": "Se mantém",
        "recent_badge_weaker": "Mais fraco",
        "recent_weaker": (
            "A média por operação caiu de {early} para {late} ({change}) no último terço. "
            "Continua acima de zero e a queda cabe no que o acaso explica, mas convém "
            "acompanhá-la."
        ),
        "recent_badge_faded": "Se apaga",
        "shift": "A rentabilidade média mudou em algum momento?",
        "shift_intro": (
            "Procuramos o momento em que a rentabilidade média da curva mais mudou e medimos se "
            "essa mudança é maior que a oscilação normal dos seus retornos (teste CUSUM, que leva "
            "em conta que um retorno pode influenciar o seguinte). Não muda a classe."
        ),
        "shift_badge_changed": "Mudou",
        "shift_badge_steady": "Sem mudança clara",
        "shift_changed": (
            "A rentabilidade média mudou por volta de {date} (provavelmente entre {low} e "
            "{high}): {before} ao ano antes e {after} ao ano depois. Com p {p}, o acaso "
            "dificilmente explica uma diferença assim."
        ),
        "shift_steady": (
            "Não há uma mudança clara na rentabilidade média ao longo do histórico (p {p}): as "
            "diferenças entre trechos cabem na oscilação normal dos seus retornos. Não prova "
            "que não tenha mudado: uma mudança pequena pode passar despercebida."
        ),
        "shift_edge": (
            "O maior desvio está nos primeiros ou nos últimos retornos do histórico (p {p}), "
            "perto demais da borda para comparar um antes e um depois."
        ),
        "shift_before": "Rentabilidade média ao ano antes de {date}",
        "shift_after": "Rentabilidade média ao ano desde {date}",
        "shift_band": "banda de 90 %: {low} a {high}",
        "recent_year": "Ano de fechamento",
        "fund": "O que quem investe em um fundo revisaria",
        "fund_intro": (
            "Os números de uma lâmina de fundo e dois testes que os analistas de fundos usam: se "
            "as rentabilidades mensais estão suavizadas e se faltam meses com uma perda pequena. "
            "Não muda a classe: são perguntas a fazer."
        ),
        "fund_year": "Ano",
        "fund_total": "Total",
        "fund_months": "Jan,Fev,Mar,Abr,Mai,Jun,Jul,Ago,Set,Out,Nov,Dez",
        "fund_cagr": "Rentabilidade anual composta",
        "fund_vol": "Volatilidade anual",
        "fund_vol_u": "Volatilidade anual sem suavização (antes: {vol})",
        "fund_positive": "Meses no positivo ({n} meses)",
        "fund_worst": "Pior mês (melhor: {best})",
        "fund_dd": "Queda máxima",
        "fund_under": "Meses seguidos abaixo de uma máxima anterior",
        "fund_under_open": "Meses seguidos abaixo de uma máxima anterior (ainda sem recuperar)",
        "fund_losing": "Meses seguidos em perda, no máximo",
        "fund_smoothed": (
            "Cada mês se parece demais com o anterior (autocorrelação de {rho}). Costuma "
            "acontecer com ativos pouco líquidos ou avaliados com atraso, e faz a volatilidade "
            "parecer menor: sem essa suavização seria {vol_u} ao ano em vez de {vol}. Pergunte "
            "como e com que frequência as posições são avaliadas."
        ),
        "fund_few_small_losses": (
            "Há muitos meses com um ganho pequeno e pouquíssimos com uma perda pequena ({gains} "
            "contra {losses}), menos do que os meses vizinhos fazem esperar. Os estudos sobre "
            "fundos associam esse padrão a avaliações que evitam fechar um mês no negativo. "
            "Pergunte quem calcula o valor da cota e se um terceiro o revisa."
        ),
        "fund_clean": "Nem suavização nem falta de meses com perda pequena.",
        "fund_badge_clean": "Sem padrões",
        "fund_bench": "Frente ao seu índice de referência",
        "fund_bench_file": (
            "De {first} a {last}, {n} meses em comum com o índice que o próprio arquivo traz, "
            "com seus números tal como vêm."
        ),
        "fund_bench_upload": (
            "De {first} a {last}, {n} meses em comum com o arquivo de benchmark que você enviou."
        ),
        "fund_bench_gross": (
            "Se os números do fundo forem antes das taxas, esta comparação o favorece."
        ),
        "fund_bench_excess": "Diferença anual frente ao índice (fundo {fund}, índice {index})",
        "fund_bench_beat": "Meses em que superou o índice",
        "fund_bench_te": "Erro de rastreamento anual (índice de informação {ir})",
        "fund_bench_beta": "Beta frente ao índice (correlação {corr})",
        "skill_title": "Quanto é caixa, quanto é mercado e quanto sobra?",
        "skill_intro": (
            "Com {n} meses em comum com o índice, a rentabilidade média anual do fundo se divide "
            "em três partes que somam o total: o que as letras do Tesouro dos EUA de 3 meses "
            "pagavam, a exposição ao índice e o que sobra."
        ),
        "skill_intro_no_cash": (
            "Com {n} meses em comum com o índice, a rentabilidade média anual do fundo se divide "
            "em três partes que somam o total. Não havia taxa do caixa para essas datas: ela é "
            "tomada como zero, então o alfa inclui também o que o caixa teria pagado."
        ),
        "skill_part": "Parte",
        "skill_year": "Ao ano",
        "skill_cash": "Caixa (letras do Tesouro)",
        "skill_exposure": (
            "Exposição ao índice (beta {beta} vezes o que o índice rendeu acima do caixa)"
        ),
        "skill_alpha": "O que sobra (alfa)",
        "skill_total": "Rentabilidade média do fundo (média aritmética)",
        "skill_share": (
            "A exposição ao índice explica {share} da rentabilidade do fundo; o caixa fica à parte."
        ),
        "skill_no_share": "Sem proporção da exposição: {reason}.",
        "skill_range": "Alfa ao ano: {alpha}, faixa de 95 % de {low} a {high} (t = {t}).",
        "skill_needed": (
            "Com este alfa e este ruído, um histórico precisaria de uns {m} meses no total (hoje "
            "tem {n}) para o alfa "
            "ficar a dois erros padrão de zero. É uma conta, não uma promessa: não diz que o "
            "alfa exista nem que vá continuar."
        ),
        "skill_needed_long": (
            "Com este alfa e este ruído, nem 50 anos de histórico bastariam para o alfa ficar a "
            "dois erros padrão de zero. É uma conta, não uma promessa: não diz que o alfa exista "
            "nem que vá continuar."
        ),
        "skill_lagged": (
            "Somando o retorno do índice do mês anterior (Dimson), o beta sobe de {beta} para "
            "{lagged}: parte da exposição chega com um mês de atraso, algo típico de preços "
            "suavizados ou atrasados, e o beta simples não a vê. O alfa com esta correção é "
            "{alpha} ao ano."
        ),
        "skill_timing_up": (
            "O fundo ganhou mais nos meses de mercado muito agitado do que o seu beta explica "
            "(Treynor e Mazuy, t = {t}): isso vem de acertar o momento ou de ter posições com "
            "forma de opção. Descontado isso, o alfa de seleção é {alpha} ao ano."
        ),
        "skill_timing_down": (
            "O fundo ganhou menos nos meses de mercado muito agitado do que o seu beta explica "
            "(Treynor e Mazuy, t = {t}): isso vem de errar o momento ou de vender opções, e "
            "tirou rentabilidade."
        ),
        "skill_nm": "Sem divisão entre caixa, mercado e alfa: {reason}.",
        "fund_bench_up": "Captura na alta: parte das altas do índice que o fundo acompanha",
        "fund_bench_down": "Captura na baixa: parte das quedas do índice que o fundo acompanha",
        "fund_bench_trails": (
            "Rendeu menos que seu índice: {excess} ao ano nos meses em comum. Pergunte o que "
            "justifica pagar por gestão ativa em vez de um fundo de índice."
        ),
        "fund_bench_index_like": (
            "Segue seu índice muito de perto (correlação {corr}, tracking error {te} ao ano), o "
            "que os estudos chamam de gestão indexada disfarçada (closet indexing). Pergunte o "
            "que suas taxas oferecem que um fundo de índice não oferece."
        ),
        "fund_bench_worse": (
            "Acompanha menos das altas do índice ({up}) e mais das suas quedas ({down}). "
            "Pergunte em que tipo de mercado o gestor espera se sair melhor."
        ),
        "fund_bench_clean": (
            "À frente do seu índice nos meses em comum, sem segui-lo como um fundo de índice."
        ),
        "fund_bench_badge_clean": "À frente",
        "fund_bench_nm": "Comparação com o índice:",
        "fund_stress": "Como se saiu nas crises conhecidas?",
        "crises": "Como se saiu nas crises conhecidas?",
        "crises_intro": (
            "Rentabilidade da curva, com seus saldos de fim de mês, em cada queda de mercado de "
            "data pública que ela cobre por completo (do topo ao fundo do mercado). Um mês sem "
            "operações conta como estável. As datas são fixas: não se ajustam ao arquivo."
        ),
        "crises_subject": "Estratégia",
        "crises_no_trades": "nenhuma operação fechada na janela",
        "crises_worse": (
            "Em {worse} de {n} crises caiu mais que seu índice. Pergunte ao vendedor o que a "
            "protege quando o mercado cai."
        ),
        "fund_stress_intro": (
            "Rentabilidade do fundo em cada queda de mercado de data pública que seu histórico "
            "cobre por completo (do topo ao fundo do mercado). As datas são fixas: não se "
            "ajustam ao arquivo."
        ),
        "fund_stress_none": (
            "O histórico não cobre por completo nenhuma das quedas da lista (pontocom, 2008, "
            "euro 2011, 2015-16, final de 2018, covid, 2022, cripto 2022)."
        ),
        "fund_stress_head": "Crise",
        "fund_stress_fund": "Fundo",
        "fund_stress_index": "Índice",
        "fund_stress_12m": (
            "Piores 12 meses seguidos: {worst}; melhores: {best}. {share} dos períodos de 12 "
            "meses terminaram no positivo."
        ),
        "fund_stress_worse": (
            "Em {worse} de {n} crises caiu mais que seu índice. Pergunte o que protege a "
            "carteira quando o mercado cai."
        ),
        "fund_stress_dotcom": "Estouro da bolha pontocom",
        "fund_stress_gfc": "Crise financeira de 2008",
        "fund_stress_euro": "Crise da dívida do euro",
        "fund_stress_china_oil": "China e queda do petróleo",
        "fund_stress_late_2018": "Final de 2018",
        "fund_stress_covid": "Queda da covid",
        "fund_stress_rates_2022": "Inflação e juros, 2022",
        "fund_stress_crypto_2022": "Inverno cripto 2022",
        "instruments": "Funciona em cada instrumento?",
        "ins_intro": (
            "Quando um robô ou um sinal opera vários mercados, o total pode vir de um só "
            "enquanto os demais perdem. Não muda a classe: são perguntas a fazer."
        ),
        "ins_head": "Instrumento",
        "ins_other": "Outros ({n} com menos de {m} operações)",
        "ins_best": "Parte do resultado líquido que vem de {best}",
        "ins_one_carries": (
            "Um único instrumento sustenta o resultado: sem {best}, os demais juntos ficam em "
            "zero ou no prejuízo. Pergunte por que os demais são operados."
        ),
        "ins_mostly_one": (
            "Quase todo o resultado vem de {best} ({share}). Pergunte o que os demais acrescentam."
        ),
        "ins_best_over": (
            "Mais do que o resultado líquido vem de {best}: os demais juntos subtraem"
        ),
        "ins_most_lose": (
            "A maioria dos instrumentos termina em zero ou no prejuízo ({losing} de {readable}). "
            "Pergunte se a estratégia foi ajustada a poucos mercados."
        ),
        "ins_clean": "Nenhum instrumento carrega sozinho o resultado.",
        "ins_badge_clean": "Distribuído",
        "behaviour": "Como se comporta ao perder",
        "behaviour_intro": (
            "O que um diário de trading diria a você: se as perdas são mantidas por mais tempo "
            "que os ganhos, se uma nova entrada vem logo depois de perder e como se saem as "
            "operações depois de uma sequência de perdas. Não muda a classe: são perguntas a "
            "fazer."
        ),
        "beh_hold": (
            "Quanto dura uma operação perdedora frente a uma ganhadora (mediana: {loss} frente a "
            "{win})"
        ),
        "beh_quick": (
            "Operações após uma perda abertas em menos de 15 minutos (após um ganho: {win})"
        ),
        "beh_streak": (
            "Taxa de acerto após {k} perdas seguidas ({n} operações; em todo o histórico: {all})"
        ),
        "beh_losers_held_longer": (
            "As perdedoras ficam abertas bem mais tempo que as ganhadoras. Pergunte onde fica o "
            "stop e se ele é movido."
        ),
        "beh_quick_after_loss": (
            "Volta a entrar rápido depois de perder. Pergunte que regra segura a próxima "
            "operação depois de uma perda."
        ),
        "beh_worse_after_streak": (
            "Acerta menos depois de uma sequência de perdas. Pergunte se o tamanho ou as regras "
            "mudam nessas sequências."
        ),
        "beh_quick_nm": "Reentrada rápida após perder:",
        "beh_clean": "Nada se destaca na forma como opera depois de perder.",
        "beh_badge_clean": "Sem padrões",
        "beh_badge_found": "Para perguntar",
        "timing": "Quando ganha e quando perde",
        "timing_intro": (
            "Suas operações agrupadas por dia e horário de entrada. Se quase todo o resultado "
            "sai de um só dia ou de uma só faixa de horário, uma mudança no horário do servidor, "
            "feriados ou notícias pode apagá-lo."
        ),
        "timing_best_day": "{share:.0%} do resultado líquido sai das operações de {day}.",
        "timing_best_block": "{share:.0%} do resultado líquido sai da faixa {block}.",
        "timing_day": "Dia de entrada",
        "timing_block": "Horário de entrada",
        "timing_trades": "Operações",
        "timing_net": "Resultado líquido",
        "timing_hits": "Taxa de acerto",
        "live": "Backtest frente à conta real",
        "live_intro": (
            "Se as operações da conta real viessem do mesmo backtest, quão incomum seria o seu "
            "resultado? Sorteamos operações do backtest, tantas quanto a conta real tem, "
            "{samples:,} vezes, e situamos a conta real entre essas histórias."
        ),
        "live_CONSISTENT": (
            "A conta real se comporta como o backtest: seu resultado líquido e sua pior queda "
            "ficam dentro do que o backtest levava a esperar."
        ),
        "live_EDGE": (
            "A conta real está no limite: seu resultado líquido ou sua pior queda ficam piores "
            "que em 95 % das histórias do backtest. Pode ser uma fase ruim, mas merece perguntas "
            "ao vendedor."
        ),
        "live_INCONSISTENT": (
            "A conta real não se comporta como o backtest: seu resultado líquido ou sua pior "
            "queda ficam piores que em 99 % das histórias do backtest."
        ),
        "live_ABOVE": (
            "A conta real fica acima de 99 % das histórias do backtest. Um resultado assim "
            "costuma indicar que os dois arquivos não são da mesma configuração, tamanho ou "
            "conta: pergunte."
        ),
        "hero_live": "Conta real: {badge}.",
        "hero_live_money": "Resultado das operações: {result} sobre {deposits} depositados.",
        "hero_live_link": "Ver a comparação com o backtest",
        "live_badge_CONSISTENT": "Coerente",
        "live_badge_EDGE": "No limite",
        "live_badge_INCONSISTENT": "Não coerente",
        "live_badge_ABOVE": "Revisar",
        "live_col_backtest": "Backtest",
        "live_col_live": "Conta real",
        "live_col_live_rescaled": "Conta real, no tamanho do backtest",
        "live_col_expected": "Faixa esperada (90 %)",
        "live_trades": "Operações",
        "live_period": "Período",
        "live_per_month": "Operações por mês",
        "live_win_rate": "Taxa de acerto",
        "live_net": "Resultado líquido",
        "live_fall": "Pior queda",
        "live_avg_win": "Ganho médio",
        "live_avg_loss": "Perda média",
        "live_below": "Histórias do backtest com resultado líquido igual ou pior",
        "live_fall_above": "Histórias do backtest com queda igual ou mais profunda",
        "live_rescaled": (
            "A conta real opera {ratio:.2f} vezes o tamanho do backtest: cada operação real foi "
            "ajustada ao tamanho mediano do backtest antes de comparar."
        ),
        "live_same_size": "Mesmo tamanho de posição (±25 %): comparado como foi operado.",
        "live_pace": (
            "A conta real faz {ratio:.1f} vezes as operações por mês do backtest: pode não ser a "
            "mesma configuração."
        ),
        "live_overlap": (
            "Parte da conta real fica dentro do período do backtest: essas datas podem ter sido "
            "usadas para ajustar o backtest, então a comparação é menos exigente."
        ),
        "live_symbols": "A conta real opera símbolos que o backtest não tem: {symbols}.",
        "live_pair": "Mesmas datas, operação por operação",
        "live_pair_intro": (
            "De {start} a {end} os dois arquivos cobrem os mesmos dias. Procuramos cada operação "
            "real no backtest: mesmo lado, mesmo símbolo e entrada com menos de 60 minutos de "
            "diferença."
        ),
        "live_pair_found": "Operações reais encontradas no backtest",
        "live_pair_of": "{matched} de {total} ({share})",
        "live_pair_missing": "Operações do backtest que a conta real não fez",
        "live_pair_entry": "Diferença mediana de preço na entrada",
        "live_pair_exit": "Diferença mediana de preço na saída",
        "live_pair_gap": "Diferença de resultado nas operações pareadas",
        "live_pair_gap_value": "{total} ({each} por operação)",
        "live_pair_bps": "{bps} pb",
        "live_pair_low": (
            "Menos da metade das operações reais aparece no backtest nessas datas: provavelmente "
            "não é a mesma configuração. Peça ao vendedor o backtest exato dessa conta."
        ),
        "live_pair_help": (
            "pb = pontos-base (0.01 % do preço); positivo é pior para a conta. A diferença de "
            "resultado está no tamanho do backtest; negativa é o quanto a conta real fez abaixo "
            "do backtest nas mesmas operações."
        ),
        "reading": "Leitura do seu arquivo",
        "reading_intro": (
            "Antes de analisar qualquer coisa, recontamos suas operações linha por linha e "
            "comparamos com o resumo que sua plataforma imprime."
        ),
        "reading_platform": "Sua plataforma",
        "reading_rows": "Lido das linhas",
        "reading_ok": "Coincide",
        "reading_bad": "Não coincide",
        "reading_all_ok": "Tudo coincide: a análise parte dos mesmos números que você vê.",
        "reading_some_bad": (
            "Algo não coincide. Revise os avisos de leitura mais abaixo e, se achar que lemos "
            "seu arquivo errado, escreva para nós com o identificador do relatório."
        ),
        "boot_line": "Bootstrap estacionário por blocos, reamostragens:",
        "boot_block": "bloco",
        "point": "Estimativa",
        "engine": "versão do motor",
        "seed": "semente das simulações",
        "code_request": "Olá, quero um código do Rigor para o relatório {id}.",
        "code_request_price": (
            "Olá, quero comprar o relatório completo do Rigor {id} ({price}). Como faço o "
            "pagamento?"
        ),
        "keep_link": (
            "Guarde o link desta página: com ele você volta ao seu relatório. Se você o enviou "
            "com sua conta, ele também está em «Minha conta»."
        ),
        "pack": "pacote de 3 relatórios: USD {price:.0f}",
        "buy_includes": (
            "Todos os números de cada seção|PDF para guardar ou enviar|Página pública de "
            "verificação para compartilhar|Reembolso se o relatório ler seu arquivo errado"
        ),
        "publish": "Publicar verificação pública",
        "publish_help": (
            "Cria uma página pública com a classe, as dimensões e os hashes, e um selo para o "
            "seu site. Nunca mostra seus arquivos, operações nem descrição."
        ),
        "evidence_legend": (
            "Cada número leva sua etiqueta: MEASURED, calculado a partir dos seus arquivos; "
            "DECLARED, declarado por você ou pelo vendedor, sem conferência; NOT_MEASURED, "
            "faltou um dado para calculá-lo."
        ),
        "next": "O que fazer agora",
        "next_intro": (
            "Se você comprou ou está para comprar este robô ou sinal, isto é o que convém "
            "esclarecer primeiro, segundo o que a auditoria encontrou."
        ),
        "next_live": (
            "Pergunte ao vendedor por que sua conta real fica fora do que o backtest levava a "
            "esperar."
        ),
        "next_costs": (
            "Compare o spread e a comissão da sua corretora com os custos que o resultado "
            "suporta: com um custo um pouco acima do de referência, a margem desaparece."
        ),
        "next_costs_fail": (
            "Compare o spread e a comissão da sua corretora com o custo de referência: com esse "
            "custo as operações já perdem dinheiro no líquido."
        ),
        "next_trials": (
            "Pergunte quantas configurações foram testadas antes de escolher esta e em qual "
            "período ela foi escolhida."
        ),
        "next_oos": (
            "Peça um relatório do mesmo robô, sem mudanças, em datas posteriores à sua otimização."
        ),
        "next_flags": (
            "Revise as bandeiras vermelhas: elas apontam números que não podem ser tomados como "
            "estão."
        ),
        "next_questions": "Leve ao vendedor as perguntas deste relatório.",
        "next_keep": (
            "Guarde este relatório e seu identificador; se o robô mudar, peça uma nova auditoria."
        ),
        "next_link": "Ir para a seção",
        "meaning": "O que isso significa para você",
        "ladder": "O que cada classe exige",
        "ladder_intro": (
            "A classe não mede quanto o backtest ganhou, e sim quantas perguntas seus arquivos "
            "respondem. Uma classe melhor não significa que a estratégia vá funcionar."
        ),
        "ladder_class": "Classe",
        "ladder_needs": "O que é preciso",
        "ladder_you": "Seu relatório",
        "charts": "Gráficos",
        "detail_heading": "Detalhe",
        "locked_intro": (
            "O veredito, os gráficos e as explicações são gratuitos. O relatório completo diz a "
            "você, com os números do seu arquivo"
        ),
        "sample_full": "Ver como é um relatório completo (exemplo com dados sintéticos)",
        "trade_stats": "Estatísticas das operações",
        "streak_line": (
            "Com a mesma porcentagem de perdedoras e em ordem aleatória, o normal é uma "
            "sequência máxima de {chance} perdedoras seguidas, e 1 em cada 20 históricos chega a "
            "{rare}. Este histórico teve {observed}."
        ),
        "streak_clustered": (
            "As perdedoras vieram mais juntas do que o acaso explica: uma sequência assim "
            "aparece em menos de 1 em cada 20 ordens aleatórias. Costuma indicar perdas que "
            "dependem do tipo de mercado ou posições abertas ao mesmo tempo."
        ),
        "long": "Compras",
        "short": "Vendas",
        "risk": "Risco reamostrado em um ano",
        "risk_dd": "Drawdown máximo em um ano",
        "risk_prob": "Probabilidade de uma queda de pelo menos",
        "risk_underwater": "Períodos seguidos abaixo do topo, nas simulações",
        "risk_under_median": "mediana",
        "risk_under_p95": "em 1 de cada 20",
        "challenge": "Simulador de desafio de mesa proprietária (prop firm)",
        "challenge_rules": "Regras simuladas",
        "open_loss_badge": "Perdas abertas",
        "hidden_loss": (
            "O arquivo mostra apenas o saldo, e as bandeiras vermelhas encontraram perdas "
            "abertas que o saldo esconde (Drawdown flutuante oculto). Elas não entram aqui, "
            "então estes números saem otimistas: não decida com eles sem a curva de patrimônio "
            "com o flutuante."
        ),
        "challenge_open_loss": (
            "Sua plataforma imprime um drawdown de {dd} com as operações abertas, maior que o "
            "limite de perda total do desafio ({limit}). A simulação usa o saldo das operações "
            "fechadas, que não vê essas perdas abertas: com elas a conta do desafio pode ter "
            "tocado o limite."
        ),
        "outcome": "Resultado",
        "probability": "Nas simulações do histórico",
        "pass": "Atinge a meta",
        "fail_daily_loss": "Rompe a perda diária",
        "fail_total_loss": "Rompe a perda total",
        "unfinished": "Não termina a tempo",
        "ci95": "Intervalo de 95 % de atingir a meta",
        "days_to_target": "Dias úteis até a meta (p25 / p50 / p75)",
        "best_day_line": (
            "Regra do melhor dia desta firma: em {share} das vezes em que passa, o melhor dia "
            "fica acima do limite. Conforme a firma, isso eleva a meta ou bloqueia o saque."
        ),
        "ff_title": "Com as regras de qual firma seu histórico se encaixa?",
        "ff_intro": (
            "O mesmo histórico, reamostrado da mesma forma, com as regras publicadas de cada "
            "firma, da maior para a menor probabilidade de passar por todas as fases do programa "
            "dentro da regra do melhor dia, se a firma a tiver; em caso de empate, por nome. "
            "Compara regras; não recomenda comprar nenhum desafio."
        ),
        "ff_program": "Desafio",
        "ff_pass": "Passa",
        "ff_clean": "Passa dentro da regra do melhor dia",
        "ff_risk": "O que mais o derruba",
        "ff_no_rule": "sem regra",
        "ff_risk_none": "Nada nas simulações",
        "ff_risk_fail_daily_loss": "romper a perda diária",
        "ff_risk_fail_total_loss": "romper a perda total",
        "ff_risk_unfinished": "não atingir a meta a tempo",
        "ff_optimistic": (
            "Os mesmos números otimistas de cima se aplicam a esta tabela: o saldo esconde "
            "perdas abertas."
        ),
        "ff_all_pass": (
            "Com este histórico todos os programas passam em pelo menos 99 % das simulações: "
            "suas regras não os distinguem."
        ),
        "ff_all_fail": (
            "Com este histórico nenhum programa passa nas simulações; o que mais impede é {risk}."
        ),
        "ff_phases": "{n} fases",
        "ff_phase": "1 fase",
        "assumptions": "Premissas",
        "source": "Fonte",
        "as_of": "lida em",
        "questions": "Perguntas para fazer ao vendedor",
        "flags_free": "Bandeiras vermelhas detectadas",
        "report_source": "Formato do arquivo",
        "platform": "Dados que a plataforma declara",
        "colmap": "Como cada coluna do seu arquivo foi lida",
        "optimization": "Exportação de otimização",
        "passes": "configurações testadas",
        "trials_used": "Tentativas usadas no Sharpe deflacionado",
        "horizon": "1 ano",
        "reasons_detail": "Detalhe técnico de cada dimensão",
        "fees": "Custos que o relatório detalha",
        "plan": "Plano para subir de classe",
        "plan_intro": (
            "O que as regras da auditoria precisariam ver em cada dimensão aberta, da mais "
            "decisiva para a menos. Uma classe melhor significa que os arquivos respondem mais "
            "perguntas, não que a estratégia vá funcionar."
        ),
        "plan_class": "Se esta dimensão passasse e as demais ficassem iguais, a classe seria",
        "plan_none": "Todas as dimensões passam: não resta nenhum passo em aberto.",
        "plan_locked": "passos concretos, com os números do seu arquivo, no relatório completo",
        "kpis": "Resumo executivo",
        "toc": "Seções do relatório",
        "toc_unlock": "Relatório completo",
        "kpis_locked": "Os números-chave do seu arquivo aparecem no relatório completo.",
        "kpi_return": "Retorno total",
        "kpi_drawdown": "Drawdown máximo",
        "kpi_dd_platform": "Drawdown com operações abertas, segundo sua plataforma",
        "kpi_dd_p95": "Drawdown p95 reamostrado, 1 ano",
        "kpi_drawdown_closed": "Drawdown máximo (só fechadas)",
        "kpi_dd_p95_closed": "Drawdown p95 em 1 ano (só fechadas)",
        "kpi_sharpe": "Sharpe anualizado",
        "kpi_pf": "Profit factor",
        "kpi_trades": "Operações · % de acerto",
        "kpi_breakeven": "Custo extra que o leva a zero",
        "kpi_breakeven_negative": "já perde sem custo extra",
        "kpi_stress": "Sem as 5 melhores operações",
        "kpi_stress_curve": "Sem os 5 melhores períodos",
        "kpi_hint_return": "quanto a conta mudou em todo o histórico",
        "kpi_hint_drawdown": "a pior queda desde um topo",
        "kpi_hint_dd_p95": "queda superada em 1 de cada 20 anos simulados",
        "kpi_hint_sharpe": "rendimento frente aos seus altos e baixos; mais alto, mais estável",
        "kpi_hint_pf": "o ganho para cada 1 perdido",
        "kpi_hint_breakeven": "quanto mais operar pode custar antes de chegar a zero",
        "bps_side": "pb por lado",
        "stress": "Testes de estresse: sem os melhores resultados",
        "stress_intro": (
            "Retiramos os melhores períodos e operações do que você enviou e medimos o que "
            "sobra. Se o total cai a zero ou menos, depende de poucos eventos que podem não se "
            "repetir. Não é uma previsão."
        ),
        "stress_curve": "Sobre a curva (retorno total composto)",
        "stress_trades": "Sobre as operações fechadas (resultado líquido após comissões e swap)",
        "scenario": "Cenário",
        "stress_result": "Sobra",
        "stress_change": "Variação",
        "stress_positive": "Continua acima de zero?",
        "original": "Original",
        "stress_count": "de {total} cenários terminam em zero ou abaixo",
        "top5_share": "As 5 melhores operações somam este múltiplo do resultado líquido",
        "fund_fees": "Quanto as taxas levariam?",
        "fund_fees_intro": (
            "Os números não foram declarados líquidos de taxas. Assim ficaria o mesmo histórico "
            "com as taxas anuais habituais de um fundo ativo, descontadas mês a mês."
        ),
        "fund_fees_rate": "Taxa anual",
        "fund_fees_cagr": "Rentabilidade anual",
        "fund_fees_growth": "Crescimento total",
        "fund_fees_none": "Sem taxa",
        "fund_fees_management": (
            "As linhas de uma só porcentagem são apenas a taxa de administração. A última soma a "
            "taxa de performance clássica: 20 % do ganho de cada ano acima do máximo anterior."
        ),
        "fund_fees_break_even": (
            "Com uma taxa de {rate} ao ano ou mais, o fundo teria ficado igual ou abaixo do seu "
            "benchmark nos meses em comum."
        ),
        "fund_fees_behind": "O fundo já fica abaixo do seu benchmark antes de qualquer taxa.",
        "crises_market": "Mercado nessas datas",
        "crises_market_note": (
            "Mercado: fechamento do mês anterior à janela contra o fechamento do seu último mês, "
            "dados públicos do FRED consultados em {as_of} ({sources}). São ações dos EUA e "
            "bitcoin: se a estratégia opera outro mercado (moedas, commodities, outro país), "
            "considere-os só como contexto do que o mercado vivia, não como ponto de comparação."
        ),
        "fund_fees_two_twenty": "2 % + 20 % dos ganhos",
        "ranges_title": "Quanto disso pode ser acaso?",
        "ranges_intro": (
            "Com {n} operações, cada número tem uma margem. Faixa de 95 %: os valores de fundo "
            "compatíveis com estas operações, se cada uma for independente das demais e o "
            "sistema não tiver mudado. Não é uma previsão."
        ),
        "ranges_zero": (
            "A faixa da média por operação ou a do fator de lucro inclui o ponto de equilíbrio "
            "(0 e 1): com estas operações não é possível distinguir o sistema de um que nem "
            "ganha nem perde por operação."
        ),
        "ranges_below": (
            "A faixa da média por operação ou a do fator de lucro fica inteira abaixo do ponto "
            "de equilíbrio (0 e 1): com estas operações o sistema perde por operação, e o acaso "
            "não explica isso."
        ),
        "ranges_open": "sem limite",
        "lo_line": (
            "Sharpe corrigido pela autocorrelação (Lo, 2002): {lo}, frente a {plain} do cálculo "
            "simples."
        ),
        "lo_lower": (
            "Cada retorno tende a se parecer com o anterior (autocorrelação {rho}), algo típico "
            "de curvas suavizadas, de preços que se atualizam pouco ou de estratégias que mantêm "
            "posições por vários períodos: o Sharpe simples sai inflado."
        ),
        "alpha_line": (
            "Alfa de Jensen: {alpha} ao ano além do que o benchmark explica, depois de subtrair "
            "dos dois lados o que a letra do Tesouro dos EUA de 3 meses pagou (beta {beta}, "
            "t = {t}, {n} períodos)."
        ),
        "alpha_line_local": (
            "Alfa de Jensen: {alpha} ao ano além do que o benchmark explica, depois de subtrair "
            "da estratégia o que o caixa na moeda da conta pagou ({code}: {name}) e do "
            "benchmark, tomado como cotado em dólares, o que a letra do Tesouro dos EUA de 3 "
            "meses pagou (beta {beta}, t = {t}, {n} períodos)."
        ),
        "alpha_line_no_cash": (
            "Alfa de Jensen: {alpha} ao ano além do que o benchmark explica, sem subtrair o que "
            "o caixa pagou (beta {beta}, t = {t}, {n} períodos)."
        ),
        "alpha_clear_up": (
            "Com t acima de 2, é pouco provável que essa diferença seja só acaso. Não diz que vá "
            "se repetir."
        ),
        "alpha_clear_down": (
            "Com t abaixo de -2, é pouco provável que o atraso frente ao benchmark seja só acaso."
        ),
        "alpha_unclear": "Com t entre -2 e 2, a diferença não se distingue do acaso.",
        "lo_lower_plain": (
            "Os retornos de períodos próximos tendem a se mover juntos: o Sharpe simples sai "
            "inflado."
        ),
        "dependence_line": (
            "Se os retornos não forem tomados como independentes entre si, a variância do "
            "Sharpe se multiplica por {ratio}: a probabilidade de que o Sharpe real seja maior "
            "que zero passa de {plain} para {psr}."
        ),
        "dependence_track": (
            "Seriam necessários uns {track} retornos no total (hoje tem {n}) para que chegasse "
            "a 95% (com a conta simples, {plain_track})."
        ),
        "dependence_track_reached": (
            "Já chega a 95% com os {n} retornos que tem (bastariam uns {track})."
        ),
        "dependence_track_long": "Nem com dez vezes os {n} retornos que tem chegaria a 95%.",
        "dependence_pass_rests": (
            "Com a conta simples a probabilidade supera 95%; sem tomar os retornos como "
            "independentes, não chega."
        ),
        "dependence_none": (
            "Os retornos não dependem de forma apreciável uns dos outros: levar isso em conta "
            "não muda a probabilidade de que o Sharpe real seja maior que zero."
        ),
        "dependence_info": "É informativo: a classe usa a conta simples.",
        "lo_not_lower": (
            "Sharpe corrigido pela autocorrelação (Lo, 2002): não fica apreciavelmente abaixo de "
            "{plain}, então a ordem dos retornos não infla o Sharpe simples de forma apreciável. "
            "Se a correção o eleva, o relatório não a usa, para não favorecer o arquivo."
        ),
        "compare_help": "Cole o link de outro relatório seu para vê-los lado a lado.",
        "shuffle_title": "A pior queda do arquivo é normal para estes retornos?",
        "shuffle_line": (
            "Pior queda do arquivo: {observed}. Com os mesmos retornos em {samples} ordens "
            "aleatórias, a pior queda vai de {low} a {high} em 9 de cada 10 ordens (mediana "
            "{mid})."
        ),
        "shuffle_intro": (
            "Mudar a ordem não muda o Sharpe, a volatilidade nem o resultado final: só mostra "
            "que queda esses retornos costumam trazer ao longo de todo o arquivo. Não é a queda "
            "em um ano da tabela acima."
        ),
        "shuffle_TYPICAL": (
            "Está dentro do habitual para estes retornos: a ordem em que chegaram não a torna "
            "nem muito mais leve nem muito mais profunda."
        ),
        "shuffle_SHALLOWER": (
            "É mais leve do que em quase todas as ordens aleatórias: só {share} delas caem tão "
            "pouco. As perdas seguiram outras perdas menos do que o acaso daria. Assim se "
            "parecem as curvas suavizadas, as que fazem preço médio em posições perdedoras ou "
            "uma ordem favorável que não precisa se repetir. A queda do arquivo pode subestimar "
            "o risco."
        ),
        "shuffle_DEEPER": (
            "É mais profunda do que em quase todas as ordens aleatórias: só {share} delas caem "
            "tanto. As perdas vieram em sequência mais do que o acaso daria, então o Sharpe e a "
            "volatilidade sozinhos subestimam o que custou aguentar esta curva."
        ),
        "holding": "Ganha de comprar e manter o mercado?",
        "holding_intro": (
            "A estratégia opera sobretudo o {label}. Estes são os seus fechamentos diários ao "
            "lado de simplesmente comprar e manter o {label} nos mesmos dias, de {first} a "
            "{last} ({days} dias). O Sharpe mede o que cada unidade de risco paga: não muda com "
            "o tamanho da posição, então compara bem uma estratégia alavancada com o mercado sem "
            "alavancagem."
        ),
        "holding_not_measured": "Sem comparação com o {label}: {reason}.",
        "holding_strategy": "Estratégia",
        "holding_market": "Manter o {label}",
        "holding_return": "Rentabilidade no período",
        "holding_drawdown": "Pior queda",
        "holding_sharpe": "Sharpe nos mesmos {days} dias (rentabilidade por unidade de risco)",
        "holding_together": (
            "Correlação semanal (de sexta a sexta) com o {label}: {corr}. Para cada 1 % que o "
            "mercado se moveu em uma semana, a estratégia se moveu em média {beta} %. Usam-se "
            "semanas porque o horário de fechamento do arquivo e o do mercado podem não "
            "coincidir."
        ),
        "holding_no_clear_edge": (
            "A diferença de Sharpe ({z} erros padrão, medida com rentabilidades semanais) não "
            "basta para dizer que ganha do mercado."
        ),
        "holding_rides": (
            "Move-se quase no mesmo passo que o {label} e não mostra vantagem clara sobre "
            "mantê-lo: a diferença de Sharpe fica dentro do ruído de {weeks} semanas. O que ela "
            "acrescenta frente a comprar o mercado e esperar?"
        ),
        "holding_closed_only": (
            "O arquivo só traz o saldo ao fechar operações: os dias com posições abertas não "
            "aparecem, então a correlação e a pior queda da estratégia ficam curtas."
        ),
        "holding_source": (
            "Fechamentos do {label}: dados públicos de {source} lidos ao gerar o relatório. "
            "Nenhum dos dois Sharpe subtrai a taxa do caixa. Não muda a classe."
        ),
        "cash_sharpe": (
            "Subtraindo o que o caixa em dólares pagava nessas mesmas datas (letras do Tesouro "
            "dos EUA de 3 meses, {rate} ao ano em média), o Sharpe fica em {sharpe}."
        ),
        "cash_below": (
            "Rendeu menos que o caixa em dólares nessas datas ({ret} ao ano frente a {rate} "
            "das letras do Tesouro de 3 meses)."
        ),
        "cash_note": (
            "O Sharpe acima não subtrai nenhuma taxa. Se a conta não é em dólares, o justo "
            "seria subtrair a taxa da sua própria moeda. Fonte: {source}."
        ),
        "cash_sharpe_local": (
            "Subtraindo o que o caixa na moeda da conta ({code}) pagava nessas mesmas datas "
            "({name}, {rate} ao ano em média), o Sharpe fica em {sharpe}."
        ),
        "cash_below_local": (
            "Rendeu menos que o caixa na moeda da conta ({code}) nessas datas ({ret} ao ano "
            "frente a {rate} da {name})."
        ),
        "cash_note_local": (
            "O Sharpe acima não subtrai nenhuma taxa. A conta está em {code}, então aqui se "
            "subtrai a taxa dessa moeda, não a dos EUA. Fonte: {source}."
        ),
        "cash_rate_MXN": "taxa interbancária de um dia do México (OCDE)",
        "cash_rate_BRL": "taxa interbancária de um dia do Brasil (OCDE)",
        "cash_rate_EUR": (
            "taxa de um dia do euro, €STR do BCE (antes de outubro de 2019, a da OCDE)"
        ),
        "cash_rate_GBP": "taxa de um dia da libra, SONIA (Banco da Inglaterra)",
        "cash_rate_JPY": "taxa interbancária de um dia do Japão (OCDE)",
        "cash_rate_CAD": "taxa interbancária de um dia do Canadá (OCDE)",
        "cash_rate_CHF": "taxa interbancária de 3 meses da Suíça (OCDE)",
        "regime": "Como foi com o mercado tranquilo e com o mercado agitado?",
        "regime_intro": (
            "Cada rentabilidade do arquivo é atribuída segundo o VIX (quanto o mercado de opções "
            "espera que o S&P 500 se mova no mês seguinte) no fechamento do dia de mercado "
            "anterior ao seu início: mercado tranquilo abaixo de 20, agitado a partir de 20. "
            "Desde 1990 o VIX fechou em 20 ou mais cerca de um dia em cada três. Período: "
            "de {first} a {last}."
        ),
        "regime_not_measured": "Sem separação pelo VIX: {reason}.",
        "regime_calm": "Mercado tranquilo (VIX < 20)",
        "regime_turbulent": "Mercado agitado (VIX ≥ 20)",
        "regime_time": "Parte do tempo",
        "regime_returns": "Rentabilidades contadas",
        "regime_monthly": "Rentabilidade por mês (composta)",
        "regime_sharpe": "Sharpe (rentabilidade por unidade de risco)",
        "regime_better_calm": (
            "Foi melhor com o mercado tranquilo: a diferença de rentabilidade média ({z} erros "
            "padrão) é maior que o ruído."
        ),
        "regime_better_turbulent": (
            "Foi melhor com o mercado agitado: a diferença de rentabilidade média ({z} erros "
            "padrão) é maior que o ruído."
        ),
        "regime_no_clear_gap": (
            "A diferença de rentabilidade média entre as duas colunas ({z} erros padrão) não "
            "basta para dizer que se comporta de forma diferente conforme o mercado."
        ),
        "currency": "Quanto valeu a conta na sua moeda e depois da inflação?",
        "currency_intro": (
            "Os saldos da curva, em dólares, convertidos pela cotação de cada dia (taxa do "
            "meio-dia em Nova York do Federal Reserve), de {first} a {last}. Se você vive com "
            "outra moeda, isto é o que a conta valeu nela. A diferença em relação à linha em "
            "dólares vem do câmbio, não da estratégia: quando o dólar sobe frente à sua moeda, "
            "o resultado nela sobe, e quando cai, cai."
        ),
        "currency_assumed": (
            "O arquivo não diz em que moeda está a conta, então ela é lida como dólares. Se não"
            " for, esta seção não se aplica."
        ),
        "currency_not_measured": "Sem conversão para outras moedas: {reason}.",
        "currency_head": "Moeda",
        "currency_total": "Rentabilidade total",
        "currency_yearly": "Ao ano",
        "currency_fall": "Pior queda",
        "currency_dollars": "Dólares (a conta)",
        "currency_real": "Dólares depois da inflação dos EUA",
        "currency_inflation": "A inflação dos EUA nessas datas foi de {total} no total.",
        "currency_inflation_yearly": (
            "A inflação dos EUA nessas datas foi de {total} no total ({yearly} ao ano)."
        ),
        "currency_note": (
            "Os números em outras moedas não subtraem a inflação dessas moedas. A rentabilidade"
            " ao ano aparece com pelo menos um ano de histórico. Fonte: cotações e preços ao "
            "consumidor dos EUA de {source}, lidos ao gerar o relatório. Não muda a classe."
        ),
        "currency_intro_local": (
            "Os saldos da conta na sua própria moeda, de {first} a {last}, e o que valem "
            "depois da inflação dessa moeda: se cresceram menos que os preços, a conta perdeu "
            "poder de compra mesmo tendo crescido."
        ),
        "currency_account_local": "{name} (a conta)",
        "currency_real_local": "{name}, depois da sua inflação",
        "currency_inflation_local": (
            "A inflação local ({code}) nessas datas foi de {total} no total."
        ),
        "currency_inflation_local_yearly": (
            "A inflação local ({code}) nessas datas foi de {total} no total ({yearly} ao ano)."
        ),
        "currency_note_local": (
            "Depois da sua inflação: os saldos divididos pelo índice oficial de preços ao "
            "consumidor do país de cada mês, ou o do último mês publicado. A rentabilidade ao "
            "ano é mostrada a partir de um ano de histórico. Dados lidos ao gerar o relatório. "
            "Não muda a classe."
        ),
        "currency_note_mixed": (
            "As linhas «depois da sua inflação» dividem pelo índice oficial de preços ao "
            "consumidor de cada país de cada mês, ou o do último mês publicado; uma moeda sem "
            "esse índice em dia (por enquanto, o peso mexicano e o iene) mostra só a sua linha "
            "antes da inflação. A rentabilidade ao ano é mostrada a partir de um ano de "
            "histórico. Cotações e preços dos EUA de {source}, lidos ao gerar o relatório. Não "
            "muda a classe."
        ),
        "currency_prices": "Preços ao consumidor: {prices}.",
        "currency_prices_through": " (preços até {month})",
        "currency_attrib_EUR": "euro, Eurostat (via FRED)",
        "currency_attrib_CHF": "franco suíço, índice harmonizado do Eurostat",
        "currency_attrib_GBP": (
            "libra, Office for National Statistics, sob a Open Government Licence v3.0"
        ),
        "currency_attrib_CAD": (
            "dólar canadense, Banco do Canadá (IPC da Statistics Canada, disponível grátis em "
            "bankofcanada.ca)"
        ),
        "currency_attrib_BRL": "real, Banco Central do Brasil (IPCA do IBGE)",
        "currency_MXN": "Pesos mexicanos (MXN)",
        "currency_BRL": "Reais (BRL)",
        "currency_EUR": "Euros (EUR)",
        "currency_GBP": "Libras esterlinas (GBP)",
        "currency_JPY": "Ienes (JPY)",
        "currency_CAD": "Dólares canadenses (CAD)",
        "currency_CHF": "Francos suíços (CHF)",
        "regime_source": (
            "VIX: dados públicos de {source} (série VIXCLS, da CBOE) lidos ao gerar o "
            "relatório. Mede ações dos EUA: se a estratégia opera outro mercado, leia-o como "
            "um termômetro geral do medo nos mercados. Não muda a classe."
        ),
    },
    "LINK_TEXT": {
        "terms": "Termos de serviço",
        "privacy": "Política de privacidade",
    },
    "METHOD_COPY": {
        "eyebrow": "Metodologia",
        "title": "Como auditamos",
        "summary": (
            "O que o Rigor testa, com qual limiar e com quais fontes, o que significa cada "
            "etiqueta e o que ele não faz. Os valores desta página são os mesmos que o motor usa."
        ),
        "independence_title": "Independência",
        "independence": [
            (
                "O Rigor não vende robôs, sinais, cursos nem contas de mesa proprietária, e suas "
                "páginas não têm links de afiliado."
            ),
            (
                "O preço do relatório é o mesmo qualquer que seja a classe obtida: não cobramos "
                "mais por uma classe melhor."
            ),
            (
                "Não operamos, não guardamos dinheiro nem chaves e não nos conectamos a nenhuma "
                "corretora."
            ),
        ],
        "dims_title": "Seis perguntas, um limiar para cada uma",
        "col_pass": "O que é preciso para passar",
        "ladder_title": "Como a classe de A a D é definida",
        "evidence_title": "O que significa cada etiqueta",
        "evidence": [
            [
                "MEASURED",
                "Nós calculamos a partir do seu arquivo.",
            ],
            [
                "DECLARED",
                "Foi informado por você ou pela sua plataforma; não conseguimos conferir.",
            ],
            [
                "NOT_MEASURED",
                "Faltavam dados para medir, e o relatório diz quais.",
            ],
        ],
        "flags_title": "Os sinais de alerta que revisamos",
        "repro_title": "Reproduzível",
        "repro": [
            "Cada arquivo é identificado no relatório pela sua impressão digital SHA-256.",
            (
                "A reamostragem usa uma semente fixa que o relatório imprime: o mesmo arquivo "
                "com as mesmas declarações dá os mesmos números."
            ),
            "O relatório imprime a versão do motor que o gerou.",
        ],
        "limits_title": "O que ele não faz",
        "limits": [
            "Não prevê resultados futuros: mede a evidência que há nos dados que você envia.",
            "Lê os arquivos como chegam; não os confere com a corretora.",
            "Não recomenda comprar, vender, copiar nem investir em nada.",
            "Um relatório não é parecer jurídico, fiscal nem de investimento.",
        ],
        "refs_title": "Fontes",
        "data_title": "Dados públicos que usamos",
        "data": [
            "Cotações, taxas e preços dos EUA, fechamentos de mercados e outras taxas de caixa: "
            "FRED, Federal Reserve Bank of St. Louis.",
            "Preços ao consumidor da zona do euro e da Suíça: Eurostat.",
            "Preços ao consumidor do Reino Unido: Office for National Statistics, sob a Open "
            "Government Licence v3.0.",
            "Preços ao consumidor do Canadá: Banco do Canadá (IPC da Statistics Canada); esses "
            "dados estão disponíveis grátis em bankofcanada.ca.",
            "Preços ao consumidor do Brasil: Banco Central do Brasil (IPCA do IBGE).",
            "Todos são lidos ao gerar o relatório e nenhum muda a classe.",
        ],
    },
    "TAGLINE": "Auditoria estatística independente de backtests e históricos",
    "WATERMARK_TEXT": "PRÉVIA — NÃO PAGO",
    "DISCLAIMER": (
        "Esta auditoria é uma ferramenta de pesquisa estatística aplicada a dados fornecidos "
        "pelo cliente. Não é recomendação de investimento, não executa operações, não guarda "
        "fundos nem chaves e não prevê resultados futuros. Cada valor leva a sua etiqueta de "
        "evidência: MEASURED foi calculado a partir do arquivo, DECLARED foi afirmado pelo "
        "cliente e não pôde ser conferido, NOT_MEASURED não pôde ser calculado com o que foi "
        "fornecido."
    ),
    "SAMPLE_PATHS": "/pt/exemplo",
    "LOCKED_GAINS": {
        "plan": "O que mudar para subir de classe, com os seus números",
        "reasons_detail": "Por que cada dimensão recebeu a sua nota",
        "account": "Quanto é resultado das operações e quanto são depósitos",
        "live": "Se a conta real se parece com o seu backtest",
        "test_data": "Com quais dados e qual qualidade de ticks o teste foi feito",
        "stress": "O que sobra sem as suas melhores operações e meses",
        "timing": "Em quais horas e dias o resultado se concentra",
        "recent": "Se continua funcionando no período mais recente",
        "shift": "Se a rentabilidade média mudou em algum momento, e quando",
        "crises": "Como se saiu em 2008, na covid, em 2022 e em outras quedas conhecidas",
        "luck": (
            "Quanto Sharpe sobra ao descontar a sorte e quantos anos de histórico seriam "
            "necessários"
        ),
        "ride": "Tempo sem novas máximas, pior dia, pior mês e meses no positivo",
        "behaviour": "Se o risco aumenta depois de perder (martingale, preço médio)",
        "fund": "Calendário ano por mês, pior mês, queda mais profunda e tempo de recuperação",
        "instruments": "Se funciona em cada mercado ou se um carrega o resto",
        "trade_stats": "Taxa de acerto, operação média e sequências",
        "risk": "Quedas possíveis em um ano, segundo milhares de históricos reamostrados",
        "plateau": "Se os parâmetros escolhidos são um pico isolado ou uma zona estável",
        "forward": "Se se sustenta no trecho forward que não foi usado para ajustá-la",
        "capital": "Quanto capital exige e com qual tamanho de posição",
        "challenge": (
            "Com que frequência tocaria os limites de um desafio de mesa proprietária (prop firm)"
        ),
        "questions": "O que perguntar ao vendedor ou ao gestor",
        "performance": "Rentabilidade anual, volatilidade e drawdown máximo medidos",
        "significance": "Se o resultado se distingue da sorte",
        "multiplicity": "Quanto sobra ao descontar as configurações que foram testadas",
        "bootstrap": "A faixa de resultados plausíveis, com intervalos de confiança",
        "cscv": "A probabilidade de a melhor configuração ser sobreajuste",
        "subperiods": "O resultado ano a ano",
        "rolling": "Como o resultado muda ao longo do tempo",
        "red_flags": "Cada sinal de alerta com os seus números e o que fazer",
        "costs": "O que acontece com custos mais altos",
        "holdout": "O trecho fora da amostra que você declarou, medido à parte",
        "benchmark": "A comparação com o benchmark que você enviou",
        "holding": "Se ganha de simplesmente comprar e manter o mercado que opera",
        "regime": "Como foi com o mercado tranquilo e com o mercado agitado (VIX)",
        "currency": (
            "Quanto valeu a conta em pesos, reais, euros e outras moedas, e depois da "
            "inflação"
        ),
    },
    "DIMENSION_TITLES": {
        "statistical_significance": "Significância estatística",
        "multiplicity": "Número de configurações testadas",
        "costs": "Custos",
        "out_of_sample": "Fora da amostra",
        "data_quality": "Qualidade dos dados e forma de operar",
        "benchmark": "Benchmark",
    },
    "STATUS_TEXT": {
        "PASS": "Passa",
        "WEAK": "Fraca",
        "FAIL": "Não passa",
        "NOT_MEASURED": "Não medida",
        "NOT_APPLICABLE": "Não se aplica",
    },
    "KEY_LABELS": {
        "sharpe_annualised": "Sharpe anualizado",
        "gap": "Diferença de Sharpe (dentro menos fora da amostra)",
        "seal_id": "Identificador do selo",
        "selection_start": "Início da seleção",
        "selection_end": "Fim da seleção",
        "holdout_start": "Início do trecho reservado",
        "holdout_end": "Fim do trecho reservado",
        "sealed_at_utc": "Selado em (UTC)",
        "seal": "Selo (sha256)",
        "total_return": "Retorno total",
        "cagr": "Retorno anual composto",
        "volatility": "Volatilidade anual",
        "max_drawdown": "Drawdown máximo",
        "win_rate": "Taxa de acerto",
        "win_rate_gross": "Taxa de acerto antes das comissões",
        "trade_count": "Operações",
        "gross_profit": "Lucro bruto das ganhadoras",
        "gross_loss": "Perda bruta das perdedoras",
        "fees_total": "Comissão e swap",
        "net_pnl": "Resultado líquido",
        "profit_factor": "Fator de lucro",
        "expectancy": "Expectativa por operação",
        "average_win": "Ganho médio",
        "average_loss": "Perda média",
        "payoff_ratio": "Razão ganho médio / perda média",
        "largest_win_share": "Peso da maior ganhadora",
        "deposits_count": "Depósitos",
        "deposits_total": "Dinheiro depositado",
        "withdrawals_count": "Saques",
        "withdrawals_total": "Dinheiro sacado",
        "later_deposits": "Depósitos depois do início das operações",
        "trading_result": "Resultado das operações, em dinheiro",
        "percent_gain": "Ganho em %",
        "result_on_deposits": "Resultado sobre o dinheiro depositado",
        "withdrawn_share": "Parte sacada do que foi depositado",
        "top_ups": "Depósitos em plena perda",
        "floating_pnl": "Resultado flutuante na impressão",
        "floating_share": "Flutuante sobre o saldo",
        "tick_model": "Modelagem de preços",
        "trades_per_year": "Operações por ano",
        "chosen_result": "Lucro da configuração escolhida",
        "passes": "Passadas da otimização",
        "passes_in_profit": "Passadas com lucro",
        "chosen_top_share": "Posição da escolhida (percentil superior)",
        "neighbours_found": "Vizinhos encontrados",
        "neighbours_in_profit": "Vizinhos com lucro",
        "neighbours_keep": "Lucro que os vizinhos mantêm",
        "data_quality": "Qualidade dos dados",
        "tested_from": "Teste desde",
        "tested_to": "Teste até",
        "trades_outside_window": "Operações fora dessas datas",
        "mismatched_chart_errors": "Erros de gráficos não coincidentes",
        "tester_spread": "Spread do testador",
        "max_consecutive_wins": "Máximo de ganhadoras seguidas",
        "max_consecutive_losses": "Máximo de perdedoras seguidas",
        "losing_run_chance": "Sequência de perdas máxima normal por acaso",
        "losing_run_rare": "Sequência de perdas máxima por acaso, 1 em 20",
        "losing_run_odds": "Probabilidade de uma sequência assim por acaso",
        "mean_holding_hours": "Horas médias por operação",
        "median_holding_hours": "Horas medianas por operação",
        "trades_per_month": "Operações por mês",
        "psr": "Sharpe probabilístico (PSR)",
        "min_track_record_length": "Histórico mínimo necessário",
        "observations_short_by": "Observações que faltam",
        "cost_bps_per_side": "Custo por lado (pb)",
        "oos_start": "Início fora da amostra",
        "benchmark_applicable": "Benchmark se aplica",
        "overlap_share": "Datas em comum com o benchmark",
        "strategy_total_return": "Retorno total da estratégia",
        "benchmark_total_return": "Retorno total do benchmark",
        "excess_return": "Retorno acima do benchmark",
        "strategy_sharpe": "Sharpe da estratégia",
        "benchmark_sharpe": "Sharpe do benchmark",
        "tracking_error": "Erro de rastreamento",
        "information_ratio": "Índice de informação",
        "strategy_max_drawdown": "Drawdown máximo da estratégia",
        "benchmark_max_drawdown": "Drawdown máximo do benchmark",
        "drawdown_ratio": "Drawdown da estratégia frente ao do benchmark (vezes)",
        "initial_balance": "Saldo inicial",
        "dsr_at_declared": "DSR com as tentativas declaradas",
        "dsr_at_trials_used": "DSR com as tentativas usadas",
        "trials_to_half": "Tentativas que levam o DSR a 0.5",
        "trials_used": "Tentativas usadas",
        "trials": "Tentativas",
        "observations": "Observações",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "sqn": "SQN",
        "skewness": "Assimetria",
        "kurtosis": "Curtose",
        "floor": "Mínimo por erro de amostragem",
        "observed_across_variants": "Observado nas variantes",
        "sharpe_variance_used": "Variância do Sharpe usada",
        "sharpe_per_period": "Sharpe por período",
        "break_even_bps": "Custo de equilíbrio (pb por lado)",
        "break_even_pips": "Custo de equilíbrio (pips por lado)",
        "reference_pips": "Custo de referência (pips por lado)",
        "platform_equity_drawdown": "Drawdown com operações abertas (sua plataforma)",
        "commission": "Comissão",
        "swap": "Swap",
        "break_even_multiple": "Múltiplo do custo de equilíbrio",
        "reference_bps": "Custo de referência (pb por lado)",
        "dataset_digest": "Impressão digital do conjunto de dados",
    },
    "SEVERITY_TEXT": {
        "FAIL": "Grave",
        "WARN": "Aviso",
        "INFO": "Nota",
    },
    "PLATFORM_LABELS": {
        "strategy": "Estratégia",
        "symbol": "Símbolo",
        "period": "Período",
        "broker": "Corretora",
        "server": "Servidor",
        "account_type": "Tipo de conta",
        "margin_mode": "Modo de margem",
        "leverage": "Alavancagem",
        "history_quality": "Qualidade do histórico",
        "report_date": "Data do relatório",
        "start": "Início",
        "end": "Fim",
        "inputs": "Parâmetros",
        "input_names": "Nomes dos parâmetros",
        "input_values": "Valores escolhidos",
        "variants": "Variantes",
        "declared_total_net_profit": "Lucro líquido total",
        "declared_total_trades": "Total de operações",
        "declared_total_deals": "Total de transações",
        "declared_balance_drawdown_maximal": "Drawdown máximo do saldo",
        "declared_equity_drawdown_maximal": "Drawdown máximo do patrimônio",
        "declared_equity_drawdown_relative": "Drawdown relativo do patrimônio",
        "declared_maximal_drawdown": "Drawdown máximo",
        "declared_relative_drawdown": "Drawdown relativo",
        "declared_sharpe_ratio": "Sharpe",
        "declared_profit_factor": "Profit factor",
        "declared_balance": "Saldo",
        "declared_equity": "Patrimônio",
        "declared_final_equity": "Patrimônio final",
        "declared_closed_trade_pnl": "Resultado das operações fechadas",
        "declared_floating_pnl": "Resultado flutuante",
        "initial_deposit": "Depósito inicial",
        "model": "Modelagem",
        "modelling_quality": "Qualidade da modelagem",
        "mismatched_chart_errors": "Erros de gráficos não coincidentes",
        "parameters": "Valores dos parâmetros",
        "spread": "Spread",
        "closing_deals": "Transações de fechamento",
        "column_symbol": "Coluna lida como símbolo",
        "column_side": "Coluna lida como lado",
        "column_quantity": "Coluna lida como quantidade",
        "column_entry_time": "Coluna lida como hora de entrada",
        "column_exit_time": "Coluna lida como hora de saída",
        "column_entry_price": "Coluna lida como preço de entrada",
        "column_exit_price": "Coluna lida como preço de saída",
        "column_time": "Coluna lida como hora de execução",
        "column_price": "Coluna lida como preço de execução",
        "column_profit": "Coluna lida como resultado",
        "column_commission": "Colunas lidas como comissão",
        "column_swap": "Coluna lida como swap",
        "column_multiplier": "Coluna lida como multiplicador",
        "column_account": "Coluna lida como conta",
    },
    "FREQUENCY_TEXT": {
        "monthly": "mensal",
        "weekly": "semanal",
        "daily_trading": "diário (dias úteis)",
        "daily_calendar": "diário (todos os dias)",
        "hourly": "por hora",
        "intraday": "intradiário",
    },
    "THRESHOLD_LABELS": {
        "psr_pass": "PSR para passar",
        "psr_weak": "PSR mínimo",
        "dsr_pass": "DSR para passar",
        "dsr_weak": "DSR mínimo",
        "pbo_max": "PBO máximo",
        "cost_pass_multiplier": "múltiplo de custo que deve suportar",
        "oos_sharpe_pass": "Sharpe mínimo fora da amostra",
        "oos_gap_max": "queda máxima do Sharpe fora da amostra",
        "benchmark_drawdown_ratio_max": "drawdown máximo frente ao benchmark (vezes)",
    },
    "STRESS_SCENARIOS": {
        "best_1pct_periods": "Sem o melhor 1 % dos períodos ({removed})",
        "best_5_periods": "Sem os 5 melhores períodos",
        "best_10_periods": "Sem os 10 melhores períodos",
        "best_1_trades": "Sem a melhor operação",
        "best_5_trades": "Sem as 5 melhores operações",
        "best_10pct_trades": "Sem os melhores 10 % das operações ({removed})",
        "best_month": "Sem o melhor mês ({month})",
    },
    "WEEKDAYS": [
        "segunda-feira",
        "terça-feira",
        "quarta-feira",
        "quinta-feira",
        "sexta-feira",
        "sábado",
        "domingo",
    ],
    "TICK_MODEL_TEXT": {
        "every tick": "Cada tick",
        "control points": "Pontos de controle",
        "open prices only": "Somente preços de abertura",
        "real ticks": "Ticks reais",
    },
    "_MONTHS_SHORT": [
        "jan",
        "fev",
        "mar",
        "abr",
        "mai",
        "jun",
        "jul",
        "ago",
        "set",
        "out",
        "nov",
        "dez",
    ],
    "CLASS_LADDER": [
        [
            "A",
            (
                "A estatística e o número de tentativas passam; custos, fora da amostra e "
                "benchmark passam ou não se aplicam; os dados não têm sinais graves nem avisos."
            ),
        ],
        [
            "B",
            (
                "A estatística e o número de tentativas passam e nada falha, mas ainda falta "
                "medir ou reforçar custos, fora da amostra, benchmark ou qualidade dos dados."
            ),
        ],
        [
            "C",
            "Uma dimensão não passa, ou a estatística ou o número de tentativas ficam em fraca.",
        ],
        [
            "D",
            "Os dados ou a estatística não passam, ou duas dimensões ou mais não passam.",
        ],
    ],
}

VERDICT: dict[str, Any] = {
    "TRIAL_SOURCE": {
        "DECLARED": "declaradas",
        "MEASURED": "contadas nos arquivos",
        "NOT_MEASURED": "não declaradas (o caso mais favorável)",
    },
    "_TEXT": {
        "A": (
            "Classe A: não encontramos evidência de sobreajuste no que foi fornecido. Isto não é "
            "uma previsão de resultados futuros."
        ),
        "B": (
            "Classe B: a estatística se sustenta, mas faltam peças (custos, fora da amostra ou "
            "benchmark) para uma conclusão completa."
        ),
        "C": (
            "Classe C: há uma fraqueza importante; não confiaríamos neste backtest sem resolvê-la."
        ),
        "D": (
            "Classe D: o backtest não passa na auditoria; os números de destaque não podem ser "
            "tomados como estão."
        ),
        "C.account": (
            "Classe C: há uma fraqueza importante; não confiaríamos neste histórico de conta sem "
            "resolvê-la."
        ),
        "D.account": (
            "Classe D: o histórico de conta não passa na auditoria; os números de destaque não "
            "podem ser tomados como estão."
        ),
        "statistical_significance.PASS": (
            "Como teste único, o resultado é constante demais para ser explicado só pelo acaso "
            "(Sharpe distinguível de zero)."
        ),
        "statistical_significance.WEAK": (
            "Não está claro se o resultado supera o acaso: a faixa provável do Sharpe chega "
            "perto de zero."
        ),
        "statistical_significance.FAIL": (
            "O resultado não se distingue do acaso (o Sharpe não se distingue de zero)."
        ),
        "statistical_significance.NOT_MEASURED": "Significância não medida: {reason}.",
        "multiplicity.PASS": (
            "Com {trials_phrase}, o resultado continua acima do que a melhor tentativa sem "
            "habilidade produziria."
        ),
        "multiplicity.WEAK": (
            "Com {trials_phrase}, o Sharpe ajustado por esses testes não chega ao limiar: se "
            "mais configurações foram testadas, o resultado pode vir de escolher a melhor."
        ),
        "multiplicity.FAIL": (
            "Com {trials_phrase}, o resultado não supera o que a melhor dessas tentativas "
            "produziria sem habilidade."
        ),
        "multiplicity.NOT_MEASURED": "Multiplicidade não medida: {reason}.",
        "multiplicity.PASS.undeclared": (
            "Não foi declarado quantas configurações foram testadas; com 1, o caso mais "
            "favorável, o resultado continua acima do que uma tentativa sem habilidade "
            "produziria. Se mais foram testadas, declará-las pode mudar esta conclusão."
        ),
        "multiplicity.WEAK.undeclared": (
            "Não foi declarado quantas configurações foram testadas e, mesmo com 1, o caso mais "
            "favorável, o Sharpe ajustado pelos testes não chega ao limiar."
        ),
        "multiplicity.FAIL.undeclared": (
            "Não foi declarado quantas configurações foram testadas e, mesmo com 1, o caso mais "
            "favorável, o resultado não supera o que uma tentativa sem habilidade produziria."
        ),
        "costs.PASS": (
            "Com 3 vezes o custo de referência, o resultado das operações continua positivo."
        ),
        "costs.WEAK": (
            "As operações continuam no positivo com o custo de referência, mas não com 3 vezes "
            "esse custo."
        ),
        "costs.FAIL": "Com o custo de referência, as operações perdem dinheiro no líquido.",
        "costs.NOT_MEASURED": "Custos não medidos: {reason}.",
        "out_of_sample.PASS": (
            "No período separado para verificação (fora da amostra) o resultado se mantém e cai "
            "pouco em relação ao resto."
        ),
        "out_of_sample.WEAK": (
            "No período separado para verificação (fora da amostra) o resultado continua "
            "positivo, mas piora."
        ),
        "out_of_sample.FAIL": (
            "No período separado para verificação (fora da amostra) o resultado é negativo."
        ),
        "out_of_sample.NOT_MEASURED": "Fora da amostra não medido: {reason}.",
        "data_quality.PASS": "Sem sinais de alerta nos dados.",
        "data_quality.WEAK": "Sinais de aviso nos dados: {codes}.",
        "data_quality.FAIL": "Sinais graves nos dados: {codes}.",
        "benchmark.PASS": "Supera o benchmark fornecido com um drawdown não pior.",
        "benchmark.WEAK": "Supera o benchmark fornecido em retorno, mas não em risco.",
        "benchmark.FAIL": "Não supera o benchmark fornecido.",
        "benchmark.NOT_MEASURED": "Benchmark não medido: {reason}.",
        "benchmark.NOT_APPLICABLE": "Benchmark declarado como não aplicável.",
    },
    "MEANING": {
        "statistical_significance.PASS": (
            "Com tantos dados, um resultado assim é difícil de obter por pura sorte. Isso não "
            "diz nada sobre o que acontecerá depois: apenas que o histórico não é ruído."
        ),
        "statistical_significance.WEAK": (
            "O resultado pode se dever em parte à sorte: não há dados suficientes para separá-lo "
            "do acaso. Mais histórico, ou histórico real, esclareceria isso."
        ),
        "statistical_significance.FAIL": (
            "Com estes dados, o resultado não se distingue de jogar uma moeda. A curva pode "
            "parecer boa e ainda assim ser acaso."
        ),
        "statistical_significance.NOT_MEASURED": (
            "Não houve dados suficientes para medir se o resultado supera o acaso. Envie uma "
            "curva mais longa para obter esta resposta."
        ),
        "multiplicity.PASS": (
            "Mesmo descontando as configurações testadas, o resultado continua de pé. Se foram "
            "testadas mais do que as informadas, esta conclusão se enfraquece."
        ),
        "multiplicity.WEAK": (
            "Parte do resultado pode vir de escolher a melhor entre muitas configurações. "
            "Pergunte quantas foram testadas e peça o arquivo de otimização."
        ),
        "multiplicity.FAIL": (
            "Testando tantas configurações, um resultado assim aparece mesmo que nenhuma tenha "
            "vantagem real. Esse padrão aparece com frequência quando se ajustam parâmetros "
            "demais."
        ),
        "multiplicity.NOT_MEASURED": (
            "Não foi possível descontar o número de tentativas porque a significância não foi "
            "medida. Com uma curva mais longa é possível calculá-lo."
        ),
        "costs.PASS": (
            "As operações se sustentam mesmo que os custos tripliquem. Os custos reais dependem "
            "da sua corretora e da execução."
        ),
        "costs.WEAK": (
            "Com custos normais o resultado continua positivo, mas com custos altos desaparece. "
            "Um spread ou uma comissão maiores que os supostos o apagariam."
        ),
        "costs.FAIL": (
            "Com o custo de referência, as operações perdem dinheiro no líquido. O resultado do "
            "backtest depende de não pagar custos."
        ),
        "costs.NOT_MEASURED": (
            "Sem a lista de operações não é possível reaplicar os custos. Envie o relatório da "
            "plataforma para medi-los."
        ),
        "out_of_sample.PASS": (
            "No trecho que não foi usado para ajustar, o comportamento se mantém parecido. Só "
            "vale se esse trecho de fato não foi olhado durante a otimização."
        ),
        "out_of_sample.WEAK": (
            "Fora da amostra o resultado continua positivo, mas bem pior que dentro dela. É "
            "comum em estratégias um tanto sobreajustadas."
        ),
        "out_of_sample.FAIL": (
            "No trecho que não foi usado para ajustar, o resultado é negativo. O que funcionou "
            "no ajuste não se repetiu fora dele."
        ),
        "out_of_sample.NOT_MEASURED": (
            "Não foi indicado um trecho fora da amostra, então não há teste sobre dados novos. "
            "Informe a data em que a otimização termina para medi-lo."
        ),
        "out_of_sample.NOT_MEASURED.account": (
            "O histórico não diz desde quando o robô opera sem alterações, então não se sabe "
            "qual parte é teste sobre dados novos. Pergunte essa data ao fornecedor e declare-a "
            "para medi-lo."
        ),
        "data_quality.PASS": (
            "Não encontramos saltos, lacunas nem padrões de risco oculto nos arquivos. Isso não "
            "descarta erros que os arquivos não mostrem."
        ),
        "data_quality.WEAK": (
            "Há avisos nos dados que convém esclarecer antes de confiar nos números. Revise a "
            "lista de sinais de alerta e as perguntas para o vendedor."
        ),
        "data_quality.FAIL": (
            "Há problemas graves nos dados ou na forma de operar. Os números principais não "
            "podem ser tomados como estão."
        ),
        "benchmark.PASS": (
            "Supera a referência fornecida sem cair mais do que ela. Compare com outra "
            "referência se esta não representa a sua alternativa real."
        ),
        "benchmark.WEAK": (
            "Supera a referência em retorno, mas com mais risco. Parte da diferença pode ser "
            "apenas risco adicional."
        ),
        "benchmark.FAIL": (
            "Não supera a referência fornecida. Uma alternativa passiva teria dado um resultado "
            "igual ou melhor nesse período."
        ),
        "benchmark.NOT_MEASURED": (
            "Não foi fornecida uma referência para comparar. Envie a curva de um índice ou de "
            "comprar e manter para medi-lo."
        ),
        "benchmark.NOT_APPLICABLE": (
            "Foi declarado que não há uma referência aplicável. A comparação com uma alternativa "
            "passiva fica fora deste relatório."
        ),
    },
}

REDFLAGS: dict[str, Any] = {
    "FLAG_TITLES": {
        "TOO_FEW_OBSERVATIONS": "Poucas observações demais",
        "NON_POSITIVE_EQUITY": "Patrimônio zerado ou negativo",
        "DUPLICATE_TIMESTAMPS": "Datas duplicadas",
        "NON_MONOTONIC_TIMESTAMPS": "Datas fora de ordem",
        "UNPARSEABLE_ROWS": "Linhas ilegíveis",
        "ZERO_VARIANCE": "Retornos sem variação",
        "STALE_MARKS": "Valores congelados",
        "MAD_SPIKES": "Saltos extremos",
        "IMPLAUSIBLE_SHARPE": "Sharpe inverossímil",
        "LARGE_GAPS": "Lacunas grandes entre linhas",
        "ZERO_DECLARED_COSTS": "Custos declarados como zero",
        "TRIALS_BELOW_VARIANTS": "Menos tentativas declaradas do que os arquivos mostram",
        "INVALID_TRADE_ROWS": "Operações ilegíveis",
        "TRADE_PNL_MISMATCH": "O resultado declarado por operação não bate",
        "MARTINGALE_SIZING": "Tamanho que cresce após perdas (martingale)",
        "GRID_AVERAGING": "Grade ou preço médio em perdas",
        "MANY_CONCURRENT_POSITIONS": "Muitas posições abertas ao mesmo tempo",
        "HIDDEN_FLOATING_DRAWDOWN": "Drawdown flutuante oculto",
        "NEGATIVE_PAYOFF_HIGH_WINRATE": "Muitos acertos pequenos e perdas grandes",
        "NO_STOP_EVIDENCE": "Sem sinal de stop loss",
        "PROFIT_CONCENTRATION": "Resultado concentrado em poucas operações",
        "TRADES_OUTSIDE_EQUITY": "Operações fora das datas da curva",
        "TRADES_EQUITY_UNRELATED": "Operações que não se movem com a curva",
        "GAIN_INFLATED_BY_FLOWS": "O % de ganho não reflete o dinheiro",
        "DEPOSIT_DURING_DRAWDOWN": "Depósitos em plena perda",
        "FLOATING_LOSS_AT_END": "Perda aberta que o saldo não mostra",
        "COARSE_TICK_MODEL": "Backtest com uma modelagem de preços grosseira",
        "TEST_DATA_QUALITY_LOW": "Histórico de preços incompleto no teste",
        "ISOLATED_OPTIMUM": "Parâmetros em um pico isolado",
        "FORWARD_NOT_HELD": "A otimização não se sustenta no período forward",
        "EDGE_FADING": "O resultado se apaga no período recente",
        "REPORT_HEADER_MISMATCH": "O cabeçalho do relatório não bate",
    },
}

PLAN: dict[str, Any] = {
    "TITLES": {
        "data_quality": "Resolva os sinais de alerta dos dados",
        "statistical_significance": "Forneça mais histórico",
        "multiplicity": "Meça quantas configurações foram testadas",
        "costs": "Confira os custos reais",
        "out_of_sample": "Adicione um trecho fora da amostra",
        "benchmark": "Compare com uma alternativa passiva",
    },
    "ACCOUNT_TITLES": {
        "out_of_sample": "Descubra desde quando opera sem alterações",
    },
    "FLAG_HINTS": {
        "TOO_FEW_OBSERVATIONS": (
            "Envie um histórico mais longo: pelo menos 30 retornos para medir, e 100 ou mais "
            "para que a conclusão não seja frágil."
        ),
        "NON_POSITIVE_EQUITY": (
            "A conta chegou a zero ou menos: revise o tamanho de posição e o saldo inicial."
        ),
        "DUPLICATE_TIMESTAMPS": (
            "Exporte uma linha por data; se houver várias contas ou símbolos, envie-os "
            "separadamente."
        ),
        "NON_MONOTONIC_TIMESTAMPS": "Ordene a curva por data antes de exportá-la.",
        "UNPARSEABLE_ROWS": "Exporte novamente da plataforma sem editar o arquivo à mão.",
        "ZERO_VARIANCE": (
            "A curva não se move: confira se você enviou a coluna de patrimônio correta."
        ),
        "STALE_MARKS": (
            "Há trechos com o mesmo valor repetido: use dados com cotação em cada período."
        ),
        "MAD_SPIKES": (
            "Há dias em que a conta se move mais de 15 %: se vêm de depósitos, saques ou preços "
            "errados, corrija-os; se são operações reais, o tamanho é muito agressivo para a "
            "conta."
        ),
        "IMPLAUSIBLE_SHARPE": (
            "Um Sharpe tão alto costuma vir de dados de baixa qualidade, custos omitidos ou um "
            "período curto: teste com ticks reais, custos reais e um período mais longo."
        ),
        "LARGE_GAPS": "Faltam intervalos de datas: exporte o período completo, sem cortes.",
        "ZERO_DECLARED_COSTS": (
            "Declare o custo por lado da sua corretora (spread, comissão e slippage)."
        ),
        "TRIALS_BELOW_VARIANTS": (
            "Declare o número real de configurações testadas; os arquivos mostram mais."
        ),
        "INVALID_TRADE_ROWS": "Exporte novamente as operações da plataforma, sem linhas editadas.",
        "TRADE_PNL_MISMATCH": (
            "O resultado por operação não bate com preços e tamanhos: revise o tamanho do "
            "contrato e a moeda da conta."
        ),
        "MARTINGALE_SIZING": (
            "O tamanho cresce após as perdas: com tamanho fixo ou risco fixo a curva mostra o "
            "risco real; envie-a assim para comparar."
        ),
        "GRID_AVERAGING": (
            "Abrem-se posições contra a posição perdedora: envie também um backtest sem preço "
            "médio para ver quanto depende disso."
        ),
        "MANY_CONCURRENT_POSITIONS": (
            "Limite as posições abertas ao mesmo tempo ou envie a curva de patrimônio com "
            "flutuante."
        ),
        "HIDDEN_FLOATING_DRAWDOWN": (
            "A curva mostra só o saldo: envie a curva de patrimônio (com flutuante) para medir o "
            "drawdown real."
        ),
        "NEGATIVE_PAYOFF_HIGH_WINRATE": (
            "Muitos acertos pequenos e perdas grandes: uma perda máxima por operação limitada "
            "tornaria visível o risco de cauda."
        ),
        "NO_STOP_EVIDENCE": (
            "A maior perda é muito superior à média: verifique se o stop loss existe."
        ),
        "PROFIT_CONCENTRATION": (
            "Revise a melhor operação no arquivo (data, tamanho, preço) e peça mais histórico: "
            "com o resultado em uma única operação, o resto do sistema não está medido."
        ),
        "TRADES_OUTSIDE_EQUITY": "Envie a curva e as operações da mesma conta e do mesmo período.",
        "TRADES_EQUITY_UNRELATED": (
            "As operações não explicam a curva: envie os dois arquivos da mesma conta."
        ),
        "GAIN_INFLATED_BY_FLOWS": (
            "A porcentagem sai de descontar depósitos e saques: julgue a conta também pelo "
            "dinheiro que ganhou ou perdeu ao operar."
        ),
        "DEPOSIT_DURING_DRAWDOWN": (
            "Entrou dinheiro novo em plena perda: veja o drawdown sem esses depósitos e pergunte "
            "por que foram adicionados."
        ),
        "FLOATING_LOSS_AT_END": (
            "Há posições abertas com perda: peça um histórico impresso depois que forem fechadas "
            "para ver o resultado real."
        ),
        "COARSE_TICK_MODEL": (
            "Peça o mesmo backtest com cada tick (ou ticks reais no MT5); só os robôs que operam "
            "na abertura do candle podem ser julgados com preços de abertura."
        ),
        "TEST_DATA_QUALITY_LOW": (
            "Peça o backtest repetido com um histórico completo, de preferência com ticks reais, "
            "e compare o resultado."
        ),
        "ISOLATED_OPTIMUM": (
            "Escolha valores em uma zona onde os vizinhos também terminem com lucro (um platô), "
            "mesmo que o resultado seja menor, e confira-os em um trecho fora da amostra."
        ),
        "FORWARD_NOT_HELD": (
            "As melhores passadas do backtest não se destacam com dados novos: otimize menos "
            "parâmetros ou com faixas mais amplas, e escolha uma configuração que também "
            "funcione no período forward."
        ),
        "EDGE_FADING": (
            "As operações recentes deixam de somar: pergunte o que mudou (mercado, corretora, "
            "ajustes) e julgue o sistema pelo seu último trecho, não pelo total."
        ),
        "REPORT_HEADER_MISMATCH": (
            "Peça o arquivo original que o MetaTrader exporta, não uma captura de tela, e "
            "envie-o novamente como está."
        ),
    },
    "GENERIC_FLAG_HINT": "Revise o detalhe do sinal na tabela de sinais de alerta.",
}

CHARTS: dict[str, Any] = {
    "TEXT": {
        "equity_title": "Curva de patrimônio",
        "equity_desc": "Patrimônio do arquivo fornecido ao longo do tempo.",
        "drawdown_title": "Drawdown (queda desde o pico anterior)",
        "drawdown_desc": "Distância percentual do patrimônio em relação ao seu pico anterior.",
        "fan_title": "Leque de cenários reamostrados",
        "fan_desc": "Percentis de trajetórias de patrimônio reamostradas do histórico fornecido.",
        "fan_note": (
            "Reamostrado do histórico fornecido; não é uma projeção nem descreve resultados "
            "futuros."
        ),
        "monthly_title": "Retornos mensais",
        "monthly_desc": (
            "Retorno de cada mês do calendário calculado a partir do patrimônio fornecido."
        ),
        "year": "Ano",
        "total": "Total",
        "median": "mediana",
        "insufficient": "Dados insuficientes para desenhar este gráfico.",
        "steps": "passos",
        "points": "pontos",
        "shown": "exibidos",
        "min": "mín.",
        "max": "máx.",
    },
    "MONTHS": [
        "Jan",
        "Fev",
        "Mar",
        "Abr",
        "Mai",
        "Jun",
        "Jul",
        "Ago",
        "Set",
        "Out",
        "Nov",
        "Dez",
    ],
}

#: Where a parse warning came from (``i18n._PREFIXES``).
PREFIXES: dict[str, str] = {
    "report": "relatório",
    "equity": "curva de patrimônio",
    "trades": "operações",
    "benchmark": "benchmark",
    "optimization": "otimização",
    "live": "conta real",
}

#: Labels in front of a totals mismatch (``i18n._COMPARED``).
COMPARED: dict[str, str] = {
    "closing deals vs Total Trades": "operações de fechamento versus Total Trades",
    "net profit": "resultado líquido",
    "net profit of closed positions": "resultado líquido das posições fechadas",
    "close rows vs Total trades": "linhas de fechamento versus Total trades",
    "closed trade P/L": "P/L das operações fechadas",
    "balance drawdown maximal": "drawdown máximo do saldo (Balance Drawdown Maximal)",
    "cumulative P&L": "P&L acumulado",
    "Cum. net profit": "Cum. net profit",
}

#: Where the starting balance came from (``i18n._INITIAL_SOURCES``).
INITIAL_SOURCES: dict[str, str] = {
    "Initial Deposit": "Initial Deposit (depósito inicial do relatório)",
    "Initial deposit": "Initial deposit (depósito inicial do relatório)",
    "first Balance row minus its own amount": (
        "a primeira linha de Balance menos o seu próprio valor"
    ),
    "summary Balance minus Deposit/Withdrawal minus Closed Trade P/L": (
        "o Balance do resumo menos Deposit/Withdrawal menos Closed Trade P/L"
    ),
    "the cumulative P&L and cumulative P&L % columns": (
        "as colunas de P&L acumulado e P&L acumulado %"
    ),
    "Properties: Initial capital": "Propriedades: Initial capital (capital inicial)",
}

#: Where the number of trials comes from (``i18n._TRIAL_SOURCES``).
TRIAL_SOURCES: dict[str, str] = {
    "not declared; computed with 1, the most favourable case": (
        "não declarado; calculado com 1, o caso mais favorável"
    ),
    "not declared; 1 assumed": "não declarado; calculado com 1, o caso mais favorável",
    "declared by the client": "declarado pelo cliente",
    "passes in the MT5 optimisation export": "passagens da exportação de otimização do MT5",
    "columns of the uploaded variants matrix": "colunas da matriz de variantes enviada",
    "parameter variants in the uploaded report": "variantes de parâmetros do relatório enviado",
}

#: Engine reasons for a figure not measured (``verdict.NOT_MEASURED_ES``).
NOT_MEASURED: dict[str, str] = {
    "fewer than three returns": "menos de três retornos",
    "zero variance": "variância zero",
    "PSR not computed": "PSR não calculado",
    "statistical significance not measured": "significância estatística não medida",
    "no trades uploaded; costs cannot be re-applied": (
        "nenhuma operação enviada; não é possível reaplicar os custos"
    ),
    "cost rows missing": "faltam linhas de custos",
    "no out-of-sample start declared": "não foi declarado um início fora da amostra",
    "declared out-of-sample start lies outside the uploaded series": (
        "o início fora da amostra declarado cai fora da série enviada"
    ),
    "out-of-sample window not evaluated": "trecho fora da amostra não avaliado",
    "no benchmark uploaded": "nenhum benchmark enviado",
    "client declared no applicable benchmark": "o cliente declarou que não se aplica benchmark",
    "no red flags": "sem sinais de alerta",
}

#: Lead-ins for engine reasons that carry their own detail.
REASON_LEADS: dict[str, str] = {
    "a side has fewer than": "um dos trechos tem menos retornos do que o necessário: ",
    "benchmark overlaps only": "o benchmark cobre muito poucas datas da estratégia: ",
    "split failed": "não foi possível dividir a série: ",
}

#: English plural template -> (its English singular, its Portuguese singular).
SINGULAR: dict[str, tuple[str, str]] = {
    "{n} row(s) of differences between the fund and its benchmark left out": (
        "{n} row of differences between the fund and its benchmark left out",
        "{n} linha de diferenças entre o fundo e seu benchmark ficou fora da análise",
    ),
    "{n} future period(s) with no change dropped (they have not happened yet)": (
        "{n} future period with no change dropped (it has not happened yet)",
        "{n} período futuro sem variação foi descartado (ainda não ocorreu)",
    ),
    "{n} row(s) with an unreadable timestamp or value dropped": (
        "{n} row with an unreadable timestamp or value dropped",
        "{n} linha com data ou valor ilegível foi descartada",
    ),
    "{n} trade row(s) with unreadable or non-positive fields dropped": (
        "{n} trade row with unreadable or non-positive fields dropped",
        "{n} linha de operações com campos ilegíveis ou não positivos foi descartada",
    ),
    "{n} row(s) with unreadable or non-positive fields dropped": (
        "{n} row with unreadable or non-positive fields dropped",
        "{n} linha com campos ilegíveis ou não positivos foi descartada",
    ),
    (
        "{n} closing deal(s) had no matching open volume; their money is in the balance but not "
        "in the trade list"
    ): (
        (
            "{n} closing deal had no matching open volume; its money is in the balance but not "
            "in the trade list"
        ),
        (
            "{n} fechamento não tinha volume aberto com o qual ser pareado; seu dinheiro está no "
            "saldo, mas não na lista de operações"
        ),
    ),
    "{n} position(s) still open at the end of the report; excluded from the closed trades": (
        "{n} position still open at the end of the report; excluded from the closed trades",
        "{n} posição continuava aberta no fim do relatório; fica fora das operações fechadas",
    ),
    "{n} closing trade(s) of positions the file never shows being opened (opened before "
    "its first date or transferred in) left out; download the full history to include them": (
        "{n} closing trade of a position the file never shows being opened (opened before "
        "its first date or transferred in) left out; download the full history to include it",
        "ficou de fora {n} fechamento de uma posição cuja abertura não aparece no arquivo "
        "(aberta antes da primeira data ou transferida); baixe o histórico completo para "
        "incluí-lo",
    ),
    "{n} option(s) expired: each closes at no premium, so its result is the whole premium, and its "
    "exit price shows 0.01 (the smallest option tick) because a trade needs a positive price": (
        "{n} option expired: it closes at no premium, so its result is the whole premium, and its "
        "exit price shows 0.01 (the smallest option tick) because a trade needs a positive price",
        "{n} opção venceu: fecha sem prêmio, então o resultado é o prêmio inteiro, e o preço de "
        "saída aparece como 0.01 (o mínimo de uma opção) porque uma operação precisa de um preço "
        "positivo",
    ),
    "{n} option(s) assigned or exercised: each closes at no premium and the shares it delivers "
    "open at the strike as their own trade, so the total result is right but the win rate and "
    "average trade count one position as two": (
        "{n} option assigned or exercised: it closes at no premium and the shares it delivers open "
        "at the strike as their own trade, so the total result is right but the win rate and "
        "average trade count one position as two",
        "{n} opção atribuída ou exercida: fecha sem prêmio e as ações que entrega abrem no preço "
        "de exercício como uma operação à parte, então o resultado total está correto, mas a % de "
        "acerto e a operação média contam uma posição como duas",
    ),
    "{n} option(s) assigned or exercised whose delivered shares are not in the file (no share "
    "trade at the strike within a few days), so their result leaves out the stock move": (
        "{n} option assigned or exercised whose delivered shares are not in the file (no share "
        "trade at the strike within a few days), so its result leaves out the stock move",
        "{n} opção atribuída ou exercida cujas ações entregues não estão no arquivo (nenhuma "
        "operação de ações no preço de exercício nesses dias), então o resultado não inclui o "
        "movimento das ações",
    ),
    "{n} fill(s) had no time, only a date; each was placed at the start of that day, so its "
    "order among that day's fills may be wrong": (
        "{n} fill had no time, only a date; it was placed at the start of that day, so its "
        "order among that day's fills may be wrong",
        "{n} execução sem horário, só com a data; foi colocada no início desse dia, então sua "
        "ordem entre as execuções desse dia pode estar errada",
    ),
    "{n} stock split(s) that would leave no shares held were not applied; the positions they touch "
    "may be read wrong": (
        "{n} stock split that would leave no shares held was not applied; the position it touches "
        "may be read wrong",
        "não foi aplicado {n} desdobramento ou grupamento que deixaria a posição sem ações; a "
        "posição afetada pode ser lida errado",
    ),
    "{n} share movement(s) that are not trades (transfers, mergers, splits) left out; the "
    "positions they change may be read wrong": (
        "{n} share movement that is not a trade (transfer, merger, split) left out; the "
        "position it changes may be read wrong",
        "ficou de fora {n} movimento de ações que não é uma operação (transferência, fusão, "
        "desdobramento); a posição que ele altera pode ser lida errado",
    ),
    "{n} deal(s) closed by the tester at the end of the test": (
        "{n} deal closed by the tester at the end of the test",
        "o testador fechou {n} operação no fim do teste",
    ),
    "{n} trade(s) closed by the tester at the end of the test": (
        "{n} trade closed by the tester at the end of the test",
        "o testador fechou {n} operação no fim do teste",
    ),
    "{n} more row(s) with an unreadable time were left out": (
        "{n} more row with an unreadable time was left out",
        "{n} linha a mais com horário ilegível ficou de fora",
    ),
    "{n} repeated row(s) (the same position listed twice) counted once": (
        "{n} repeated row (the same position listed twice) counted once",
        "{n} linha repetida (a mesma posição listada duas vezes) foi contada uma única vez",
    ),
    "{n} position(s) opened in the report were not closed; excluded": (
        "{n} position opened in the report was not closed; excluded",
        "{n} posição aberta no relatório não foi fechada; fica de fora",
    ),
    (
        "{n} close row(s) referenced an unknown ticket and were linked to the one open ticket "
        "with the same size"
    ): (
        (
            "{n} close row referenced an unknown ticket and was linked to the one open ticket "
            "with the same size"
        ),
        (
            "{n} linha de fechamento citava um ticket desconhecido e foi ligada ao único ticket "
            "aberto do mesmo tamanho"
        ),
    ),
    (
        "{n} close row(s) could not be paired with an entry; their money is in the balance but "
        "not in the trade list"
    ): (
        (
            "{n} close row could not be paired with an entry; its money is in the balance but "
            "not in the trade list"
        ),
        (
            "{n} linha de fechamento não pôde ser pareada com uma entrada; seu dinheiro está no "
            "saldo, mas não na lista de operações"
        ),
    ),
    "{n} position(s) never closed; excluded": (
        "{n} position never closed; excluded",
        "{n} posição nunca foi fechada; fica de fora",
    ),
    "{n} credit row(s) excluded: broker credit is not the trader's balance": (
        "{n} credit row excluded: broker credit is not the trader's balance",
        "{n} linha de crédito foi excluída: o crédito da corretora não é saldo do trader",
    ),
    "{n} open trade(s) at the end of the export; excluded": (
        "{n} open trade at the end of the export; excluded",
        "{n} operação aberta no fim da exportação; fica de fora",
    ),
    "{n} trade number(s) without one entry and one exit row": (
        "{n} trade number without one entry and one exit row",
        "{n} número de operação sem uma linha de entrada e uma de saída",
    ),
    (
        "{n} fee(s) charged in another coin than the price were left out of the costs, so costs "
        "are understated"
    ): (
        (
            "{n} fee charged in another coin than the price was left out of the costs, so costs "
            "are understated"
        ),
        (
            "{n} comissão cobrada em uma moeda diferente da do preço ficou fora dos custos, "
            "portanto os custos estão subestimados"
        ),
    ),
    "{n} multi-leg trade(s) kept as single trades": (
        "{n} multi-leg trade kept as a single trade",
        "{n} operação com várias pernas é tratada como uma só",
    ),
    "{n} open trade(s) excluded": (
        "{n} open trade excluded",
        "{n} operação aberta foi excluída",
    ),
    (
        "{n} day(s) with a trade result larger than the balance a withdrawal left (first on "
        "{date}) were measured on the balance before that withdrawal"
    ): (
        (
            "{n} day with a trade result larger than the balance a withdrawal left (first on "
            "{date}) was measured on the balance before that withdrawal"
        ),
        (
            "{n} dia com um resultado maior que o saldo deixado por um saque (o primeiro, "
            "{date}) foi medido sobre o saldo anterior a esse saque"
        ),
    ),
    "{n} cash flow(s) after the last trade ignored": (
        "{n} cash flow after the last trade ignored",
        "{n} movimentação de dinheiro posterior à última operação foi ignorada",
    ),
    (
        "{n} Balance cell(s) do not equal the previous balance plus the row's money; the "
        "reported Balance was kept"
    ): (
        (
            "{n} Balance cell does not equal the previous balance plus the row's money; the "
            "reported Balance was kept"
        ),
        (
            "{n} célula de Balance (saldo) não é o saldo anterior mais o dinheiro da linha; o "
            "Balance do relatório foi mantido"
        ),
    ),
    "{n} repeated pass number(s) counted once": (
        "{n} repeated pass number counted once",
        "{n} número de passagem repetido foi contado uma vez",
    ),
    "{n} equity value(s) at or below zero; returns are undefined there": (
        "{n} equity value at or below zero; returns are undefined there",
        "{n} valor de patrimônio em zero ou abaixo; ali os retornos não estão definidos",
    ),
    "{n} duplicated timestamp(s); the last value was kept": (
        "{n} duplicated timestamp; the last value was kept",
        "{n} data duplicada; o último valor foi mantido",
    ),
    "{n} single-period move(s) are extreme outliers; check for bad prints": (
        "{n} single-period move is an extreme outlier; check for bad prints",
        "{n} movimento de um único período é um outlier extremo; verifique se há preços errados",
    ),
    (
        "{n} trial(s) declared but the files show {m} variants or optimisation passes; the "
        "declared count is too low"
    ): (
        (
            "{n} trial declared but the files show {m} variants or optimisation passes; the "
            "declared count is too low"
        ),
        (
            "foi declarada {n} tentativa, mas os arquivos mostram {m} variantes ou passagens de "
            "otimização; o número declarado é baixo demais"
        ),
    ),
    "{n} trade row(s) dropped as unreadable": (
        "{n} trade row dropped as unreadable",
        "{n} linha de operações ilegível foi descartada",
    ),
    "{n} deposit(s) arrived while the account was at least {p} below its peak": (
        "{n} deposit arrived while the account was at least {p} below its peak",
        "{n} depósito entrou quando a conta estava pelo menos {p} abaixo de seu pico",
    ),
    (
        "{n} trade(s) fall outside the dates the header says were tested; ask for the original "
        "report file"
    ): (
        (
            "{n} trade falls outside the dates the header says were tested; ask for the original "
            "report file"
        ),
        (
            "{n} operação fica fora das datas que o cabeçalho diz terem sido testadas; peça o "
            "arquivo original do relatório"
        ),
    ),
    "PSR against E[max Sharpe] of {n} trial(s)": (
        "PSR against E[max Sharpe] of {n} trial",
        "PSR contra E[Sharpe máximo] de {n} tentativa",
    ),
    "PSR against E[max Sharpe] of {n} trial(s), {source}": (
        "PSR against E[max Sharpe] of {n} trial, {source}",
        "PSR contra E[Sharpe máximo] de {n} tentativa, {source}",
    ),
}

#: (English note template, its Portuguese), the placeholders unchanged.
RULES: tuple[tuple[str, str], ...] = (
    (
        "CUSUM of the returns in time order (Ploberger and Kramer); cautious long-run "
        "variance; p-value from the Brownian bridge",
        "CUSUM dos retornos em ordem de tempo (Ploberger e Krämer); variância de longo prazo "
        "prudente; valor p da ponte browniana",
    ),
    (
        "where the running sum strays furthest from its straight line; 95 % range (Bai)",
        "onde a soma acumulada mais se afasta da sua linha reta; intervalo de 95 % (Bai)",
    ),
    (
        "average return per period, annualised; 90 % band from its cautious standard error",
        "retorno médio por período, anualizado; banda de 90 % pelo seu erro-padrão prudente",
    ),
    ("fewer than 250 returns", "menos de 250 retornos"),
    (
        "a return is too large to measure its spread",
        "um retorno é grande demais para medir a sua dispersão",
    ),
    (
        "both {a} and {b} present; using {c}",
        "há colunas {a} e {b}; usa-se {c}",
    ),
    (
        "returns were percent-formatted; divided by 100",
        "os retornos vinham em %; foram divididos por 100",
    ),
    (
        "returns look like percentages (median |r| > 0.5); divided by 100",
        "os retornos parecem porcentagens (mediana |r| > 0.5); foram divididos por 100",
    ),
    (
        "{n} row(s) with an unreadable timestamp or value dropped",
        "{n} linha(s) com data ou valor ilegível descartada(s)",
    ),
    (
        "{n} future period(s) with no change dropped (they have not happened yet)",
        "{n} período(s) futuro(s) sem variação descartado(s) (ainda não ocorreram)",
    ),
    (
        "no side column; every trade treated as long",
        "não há coluna de lado; cada operação é tratada como comprada",
    ),
    (
        "{n} trade row(s) with unreadable or non-positive fields dropped",
        "{n} linha(s) de operações com campos ilegíveis ou não positivos descartada(s)",
    ),
    (
        "{n} row(s) with unreadable or non-positive fields dropped",
        "{n} linha(s) com campos ilegíveis ou não positivos descartada(s)",
    ),
    (
        "the uploaded equity file is used for returns; the report supplies the trades",
        "os retornos vêm da curva de patrimônio enviada; o relatório fornece as operações",
    ),
    (
        (
            "hedging account: the report does not say which entry each close belongs to; closes "
            "were matched to the open entry whose price explains their profit, else first-in "
            "first-out, so per-trade entry price and holding time are approximate (money results "
            "stay exact)"
        ),
        (
            "conta com hedge: o relatório não diz a qual entrada corresponde cada fechamento; "
            "cada fechamento foi pareado com a entrada aberta cujo preço explica o seu resultado "
            "ou, caso contrário, por ordem de chegada (FIFO), então o preço de entrada e a "
            "duração de cada operação são aproximados (os valores em dinheiro são exatos)"
        ),
    ),
    (
        (
            "{n} closing deal(s) had no matching open volume; their money is in the balance but "
            "not in the trade list"
        ),
        (
            "{n} fechamento(s) não tinham volume aberto com que parear; o dinheiro deles está no "
            "saldo, mas não na lista de operações"
        ),
    ),
    (
        "{n} position(s) still open at the end of the report; excluded from the closed trades",
        (
            "{n} posição(ões) ainda estavam abertas no fim do relatório; ficam fora das "
            "operações fechadas"
        ),
    ),
    (
        "{n} closing trade(s) of positions the file never shows being opened (opened before "
        "its first date or transferred in) left out; download the full history to include them",
        (
            "ficaram de fora {n} fechamento(s) de posições cuja abertura não aparece no "
            "arquivo (abertas antes da primeira data ou transferidas); baixe o histórico "
            "completo para incluí-los"
        ),
    ),
    (
        "{n} option(s) expired: each closes at no premium, so its result is the whole premium, and "
        "its exit price shows 0.01 (the smallest option tick) because a trade needs a positive "
        "price",
        (
            "{n} opção(ões) venceram: cada uma fecha sem prêmio, então o resultado é o prêmio "
            "inteiro, e o preço de saída aparece como 0.01 (o mínimo de uma opção) porque uma "
            "operação precisa de um preço positivo"
        ),
    ),
    (
        "{n} option(s) assigned or exercised: each closes at no premium and the shares it delivers "
        "open at the strike as their own trade, so the total result is right but the win rate and "
        "average trade count one position as two",
        (
            "{n} opção(ões) atribuídas ou exercidas: cada uma fecha sem prêmio e as ações que "
            "entrega abrem no preço de exercício como uma operação à parte, então o resultado "
            "total está correto, mas a % de acerto e a operação média contam uma posição como duas"
        ),
    ),
    (
        "{n} option(s) assigned or exercised whose delivered shares are not in the file (no share "
        "trade at the strike within a few days), so their result leaves out the stock move",
        (
            "{n} opção(ões) atribuídas ou exercidas cujas ações entregues não estão no arquivo "
            "(nenhuma operação de ações no preço de exercício nesses dias), então o resultado não "
            "inclui o movimento das ações"
        ),
    ),
    (
        "{n} fill(s) had no time, only a date; each was placed at the start of that day, so its "
        "order among that day's fills may be wrong",
        (
            "{n} execuções sem horário, só com a data; cada uma foi colocada no início desse "
            "dia, então sua ordem entre as execuções desse dia pode estar errada"
        ),
    ),
    (
        "{n} stock split(s) that would leave no shares held were not applied; the positions they "
        "touch may be read wrong",
        (
            "não foram aplicados {n} desdobramento(s) ou grupamento(s) que deixariam a posição "
            "sem ações; as posições afetadas podem ser lidas errado"
        ),
    ),
    (
        "{n} share movement(s) that are not trades (transfers, mergers, splits) left out; the "
        "positions they change may be read wrong",
        (
            "ficaram de fora {n} movimento(s) de ações que não são operações (transferências, "
            "fusões, desdobramentos); as posições que eles alteram podem ser lidas errado"
        ),
    ),
    (
        "{n} deal(s) closed by the tester at the end of the test",
        "o testador fechou {n} negócio(s) no fim do teste",
    ),
    (
        "{n} trade(s) closed by the tester at the end of the test",
        "o testador fechou {n} operação(ões) no fim do teste",
    ),
    (
        "{what}: the report states {declared} but the rows add up to {measured}",
        "{what}: o relatório indica {declared}, mas as linhas somam {measured}",
    ),
    (
        (
            "the Deals table charges {amount} in fees that the Positions table does not itemise "
            "per trade; they are in the balance curve only"
        ),
        (
            "a tabela de negócios (Deals) cobra {amount} em taxas que a tabela de posições não "
            "detalha por operação; elas estão apenas na curva de saldo"
        ),
    ),
    (
        "{n} position(s) opened in the report were not closed; excluded",
        "{n} posição(ões) aberta(s) no relatório não foram fechadas; ficam fora",
    ),
    (
        (
            "MetaTrader 4 tester profit already includes swap and commission; costs are not "
            "itemised, so the trade P&L is net"
        ),
        (
            "o resultado do testador do MetaTrader 4 já inclui swap e comissão; os custos não "
            "vêm detalhados, então o resultado de cada operação é líquido"
        ),
    ),
    (
        (
            "{n} close row(s) referenced an unknown ticket and were linked to the one open "
            "ticket with the same size"
        ),
        (
            "{n} linha(s) de fechamento citavam um ticket desconhecido e foram ligadas ao único "
            "ticket aberto do mesmo tamanho"
        ),
    ),
    (
        (
            "{n} close row(s) could not be paired with an entry; their money is in the balance "
            "but not in the trade list"
        ),
        (
            "{n} linha(s) de fechamento não puderam ser pareadas com uma entrada; o dinheiro "
            "delas está no saldo, mas não na lista de operações"
        ),
    ),
    (
        "{n} position(s) never closed; excluded",
        "{n} posição(ões) nunca foram fechadas; ficam fora",
    ),
    (
        (
            "{symbol}: a fill with an unreadable time ({time}) was left out; the trade it opened "
            "or closed is missing from the results"
        ),
        (
            "{symbol}: uma execução com horário ilegível ({time}) foi deixada de fora; a "
            "operação que ela abriu ou fechou falta nos resultados"
        ),
    ),
    (
        (
            "{symbol}: a trade with an unreadable time ({time}) was left out; it is missing from "
            "the results"
        ),
        (
            "{symbol}: uma operação com horário ilegível ({time}) foi deixada de fora; ela falta "
            "nos resultados"
        ),
    ),
    (
        "{n} more row(s) with an unreadable time were left out",
        "mais {n} linha(s) com horário ilegível foram deixadas de fora",
    ),
    (
        "{n} repeated row(s) (the same position listed twice) counted once",
        "{n} linha(s) repetida(s) (a mesma posição listada duas vezes) contada(s) uma única vez",
    ),
    (
        "{n} credit row(s) excluded: broker credit is not the trader's balance",
        "{n} linha(s) de crédito excluída(s): o crédito da corretora não é saldo do trader",
    ),
    (
        (
            "this TradingView export does not itemise commission; trade P&L is net of the "
            "commission set in the strategy properties"
        ),
        (
            "esta exportação do TradingView não detalha a comissão; o resultado de cada operação "
            "já desconta a comissão configurada na estratégia"
        ),
    ),
    (
        "{n} open trade(s) at the end of the export; excluded",
        "{n} operação(ões) aberta(s) no fim da exportação; ficam fora",
    ),
    (
        "{n} trade number(s) without one entry and one exit row",
        "{n} número(s) de operação sem uma linha de entrada e uma de saída",
    ),
    (
        "every trade has zero commission and fees",
        "todas as operações têm comissão e taxas zero",
    ),
    (
        "futures results computed with each contract's point value: {listed}",
        "resultados de futuros calculados com o valor por ponto de cada contrato: {listed}",
    ),
    (
        (
            "the profit column already subtracts commission (it matches the price move after "
            "costs), so it was read as net"
        ),
        (
            "a coluna de resultado já desconta a comissão (bate com o movimento do preço depois "
            "dos custos), então foi lida como líquida"
        ),
    ),
    (
        (
            "the file has no profit column: each trade's result is the price move times the "
            "quantity, with no contract multiplier"
        ),
        (
            "o arquivo não tem coluna de resultado: o de cada operação é o movimento do preço "
            "vezes a quantidade, sem multiplicador de contrato"
        ),
    ),
    (
        "no side column; the side was taken from the sign of the quantity",
        "não há coluna de lado; ele foi tirado do sinal da quantidade",
    ),
    (
        "no side column; the side was taken from the sign of the profit",
        "não há coluna de lado; ele foi tirado do sinal do resultado",
    ),
    (
        (
            "{n} fee(s) charged in another coin than the price were left out of the costs, so "
            "costs are understated"
        ),
        (
            "{n} taxa(s) cobrada(s) em uma moeda diferente da do preço ficaram fora dos custos, "
            "então os custos estão subestimados"
        ),
    ),
    (
        "{n} multi-leg trade(s) kept as single trades",
        "{n} operação(ões) de várias pernas tratada(s) como uma só",
    ),
    (
        (
            "this backtesting.py version folds commission into the fill prices; costs are not "
            "itemised"
        ),
        (
            "esta versão do backtesting.py inclui a comissão nos preços de execução; os custos "
            "não vêm detalhados"
        ),
    ),
    (
        "the file holds {n} parameter variants; only the first ({name}) was imported",
        "o arquivo contém {n} variantes de parâmetros; só a primeira ({name}) foi importada",
    ),
    (
        "{n} open trade(s) excluded",
        "{n} operação(ões) aberta(s) excluída(s)",
    ),
    (
        (
            "the stated initial balance {stated} differs from the deposits before the first "
            "trade ({deposits}); the deposits were used"
        ),
        (
            "o saldo inicial indicado ({stated}) não coincide com os depósitos anteriores à "
            "primeira operação ({deposits}); foram usados os depósitos"
        ),
    ),
    (
        "initial balance {amount} taken from {source}",
        "saldo inicial {amount} tirado de {source}",
    ),
    (
        (
            "the file does not state a starting balance; {amount} was assumed, which scales "
            "every return and drawdown"
        ),
        (
            "o arquivo não indica um saldo inicial; supôs-se {amount}, o que escala cada retorno "
            "e cada drawdown"
        ),
    ),
    (
        "the file holds {n} accounts; only the one with the most closed trades ({m}) was read",
        "o arquivo traz {n} contas; só foi lida a que tem mais operações fechadas ({m})",
    ),
    (
        (
            "{n} day(s) with a trade result larger than the balance a withdrawal left (first on "
            "{date}) were measured on the balance before that withdrawal"
        ),
        (
            "{n} dia(s) com um resultado maior que o saldo deixado por um saque (o primeiro em "
            "{date}) foram medidos sobre o saldo anterior a esse saque"
        ),
    ),
    (
        "{n} cash flow(s) after the last trade ignored",
        "{n} movimentação(ões) de dinheiro posterior(es) à última operação ignorada(s)",
    ),
    (
        (
            "{n} Balance cell(s) do not equal the previous balance plus the row's money; the "
            "reported Balance was kept"
        ),
        (
            "{n} célula(s) de Balance não são o saldo anterior mais o dinheiro da linha; "
            "manteve-se o Balance do relatório"
        ),
    ),
    (
        (
            "deposits or withdrawals were removed: the curve is a flow-adjusted index that "
            "starts at the initial balance"
        ),
        (
            "depósitos e saques foram removidos: a curva é um índice ajustado por fluxos que "
            "começa no saldo inicial"
        ),
    ),
    (
        "contract size inferred from reported profit: {sizes}",
        "tamanho de contrato deduzido do resultado do relatório: {sizes}",
    ),
    (
        (
            "money per point changes with the conversion to the account currency, so the size "
            "was inferred per trade from its reported profit: {symbols}"
        ),
        (
            "o dinheiro por ponto muda com a conversão para a moeda da conta, então o tamanho "
            "foi deduzido operação por operação a partir do resultado no relatório: {symbols}"
        ),
    ),
    (
        "the file's times carry no timezone (platform or server time); they were read as UTC",
        (
            "os horários do arquivo não indicam fuso horário (hora da plataforma ou do "
            "servidor); foram lidos como UTC"
        ),
    ),
    (
        (
            "the balance curve is built from closed trades only; it does not show floating "
            "(open-trade) drawdown, so the real drawdown was at least as deep"
        ),
        (
            "a curva de saldo é construída só com operações fechadas; não mostra o drawdown "
            "flutuante (das operações abertas), então o drawdown real foi pelo menos tão profundo"
        ),
    ),
    (
        "{n} repeated pass number(s) counted once",
        "{n} número(s) de passada repetido(s) contado(s) uma vez",
    ),
    (
        (
            "the pass count is the number of configurations the optimiser tried; a genetic "
            "optimisation lists only the passes it evaluated"
        ),
        (
            "o número de passadas é o de configurações que o otimizador testou; uma otimização "
            "genética só lista as passadas que avaliou"
        ),
    ),
    (
        "{n} return observations; at least {m} are needed",
        "{n} retornos observados; são necessários pelo menos {m}",
    ),
    (
        "{n} return observations; conclusions below {m} are fragile",
        "{n} retornos observados; abaixo de {m} as conclusões são frágeis",
    ),
    (
        "{n} equity value(s) at or below zero; returns are undefined there",
        "{n} valor(es) de patrimônio em zero ou abaixo; ali os retornos não estão definidos",
    ),
    (
        "{n} duplicated timestamp(s); the last value was kept",
        "{n} data(s) duplicada(s); manteve-se o último valor",
    ),
    (
        "rows were not in chronological order; sorted before analysis",
        "as linhas não estavam em ordem cronológica; foram ordenadas antes da análise",
    ),
    (
        "{n} of {m} rows could not be read",
        "não foi possível ler {n} de {m} linhas",
    ),
    (
        "every return is identical; nothing to measure",
        "todos os retornos são idênticos; não há nada para medir",
    ),
    (
        "{n} consecutive identical non-zero returns; looks forward-filled",
        "{n} retornos idênticos diferentes de zero seguidos; parece preenchimento para a frente",
    ),
    (
        "{n} consecutive identical non-zero returns",
        "{n} retornos idênticos diferentes de zero seguidos",
    ),
    (
        "{n} single-period moves are extreme outliers (>{a} and >{b} robust sigmas)",
        "{n} movimentos de um só período são outliers extremos (>{a} e >{b} sigmas robustos)",
    ),
    (
        "{n} single-period move(s) are extreme outliers; check for bad prints",
        "{n} movimento(s) de um só período são outliers extremos; verifique se há preços errados",
    ),
    (
        (
            "annualised Sharpe {s} exceeds {t}; almost always a look-ahead or a costless fill "
            "assumption"
        ),
        (
            "Sharpe anualizado {s} acima de {t}; quase sempre indica olhar o futuro (look-ahead) "
            "ou supor execuções sem custo"
        ),
    ),
    (
        "annualised Sharpe {s} exceeds {t}; rare outside intraday market making",
        "Sharpe anualizado {s} acima de {t}; raro fora do market making intradiário",
    ),
    (
        "largest gap between rows is {m}x the median spacing",
        "o maior intervalo entre linhas é {m}x o espaçamento mediano",
    ),
    (
        "no trading cost declared; the cost dimension uses a reference assumption",
        "nenhum custo de operação declarado; a dimensão de custos usa uma suposição de referência",
    ),
    (
        (
            "{n} trial(s) declared but the files show {m} variants or optimisation passes; the "
            "declared count is too low"
        ),
        (
            "{n} tentativa(s) declarada(s), mas os arquivos mostram {m} variantes ou passadas de "
            "otimização; o número declarado é baixo demais"
        ),
    ),
    (
        "{n} trade row(s) dropped as unreadable",
        "{n} linha(s) de operações ilegível(is) descartada(s)",
    ),
    (
        (
            "client-reported pnl differs from recomputed pnl by {p} of gross; the trades file "
            "may carry costs or a different contract size"
        ),
        (
            "o resultado que o arquivo declara difere do recalculado em {p} do bruto; o arquivo "
            "pode incluir custos ou usar outro tamanho de contrato"
        ),
    ),
    (
        (
            "after a loss the next trade is typically {r}x the size used after a win, and {p} of "
            "post-loss trades were larger ({a} after losses, {b} after wins)"
        ),
        (
            "após uma perda, a operação seguinte costuma ter {r}x o tamanho usado após um ganho, "
            "e {p} das operações após perda foram maiores ({a} após perdas, {b} após ganhos)"
        ),
    ),
    (
        "after a loss the next trade is typically {r}x the size used after a win",
        "após uma perda, a operação seguinte costuma ter {r}x o tamanho usado após um ganho",
    ),
    (
        (
            "{a} of {n} trades ({p}) were opened against an open position at a worse price: grid "
            "or averaging down"
        ),
        (
            "{a} de {n} operações ({p}) foram abertas contra uma posição aberta a preço pior: "
            "grid ou preço médio contra a perda"
        ),
    ),
    (
        "{a} of {n} trades ({p}) were opened against an open position at a worse price",
        "{a} de {n} operações ({p}) foram abertas contra uma posição aberta a preço pior",
    ),
    (
        (
            "the time-weighted gain is {g} while trading made {m} on {d} deposited; deposits and "
            "withdrawals shape the percentage"
        ),
        (
            "o ganho ponderado no tempo é {g}, enquanto operar deixou {m} sobre {d} depositados; "
            "os depósitos e saques moldam a porcentagem"
        ),
    ),
    (
        "{n} deposit(s) arrived while the account was at least {p} below its peak",
        "{n} depósito(s) chegaram quando a conta estava pelo menos {p} abaixo do seu máximo",
    ),
    (
        (
            "open positions carried a floating loss of {p} of the balance when the statement was "
            "printed; the balance does not show it"
        ),
        (
            "as posições abertas tinham uma perda flutuante de {p} do saldo quando o extrato foi "
            "impresso; o saldo não a mostra"
        ),
    ),
    (
        (
            "the test ran on control points: prices between those points were not simulated, so "
            "stops, targets and intrabar exits may have filled where the market never let them"
        ),
        (
            "o teste foi feito com pontos de controle: os preços entre esses pontos não foram "
            "simulados, então stops, alvos e saídas dentro do candle podem ter sido executados "
            "onde o mercado nunca permitiu"
        ),
    ),
    (
        (
            "the test ran on open prices only: prices between those points were not simulated, "
            "so stops, targets and intrabar exits may have filled where the market never let them"
        ),
        (
            "o teste foi feito só com preços de abertura: os preços entre esses pontos não foram "
            "simulados, então stops, alvos e saídas dentro do candle podem ter sido executados "
            "onde o mercado nunca permitiu"
        ),
    ),
    (
        (
            "the report states a data quality of {p}: part of the price history was missing or "
            "generated"
        ),
        (
            "o relatório declara uma qualidade de dados de {p}: parte do histórico de preços "
            "faltava ou era gerada"
        ),
    ),
    (
        (
            "the header states {p} modelling quality with control points, which MT4 does not "
            "print for that mode; ask for the original report file"
        ),
        (
            "o cabeçalho declara {p} de qualidade de modelagem com pontos de controle, algo que "
            "o MT4 não imprime nesse modo; peça o arquivo original do relatório"
        ),
    ),
    (
        (
            "the header states {p} modelling quality with open prices only, which MT4 does not "
            "print for that mode; ask for the original report file"
        ),
        (
            "o cabeçalho declara {p} de qualidade de modelagem só com preços de abertura, algo "
            "que o MT4 não imprime nesse modo; peça o arquivo original do relatório"
        ),
    ),
    (
        (
            "{n} trade(s) fall outside the dates the header says were tested; ask for the "
            "original report file"
        ),
        (
            "{n} operação(ões) ficam fora das datas que o cabeçalho diz terem sido testadas; "
            "peça o arquivo original do relatório"
        ),
    ),
    (
        "the tester's modelling mode, as printed in the report header",
        "o modo de modelagem do testador, tal como impresso no cabeçalho do relatório",
    ),
    (
        "share of the price history the tester had, as printed in the report header",
        (
            "parte do histórico de preços que o testador teve, tal como impressa no cabeçalho do "
            "relatório"
        ),
    ),
    (
        "as printed in the report header",
        "tal como impresso no cabeçalho do relatório",
    ),
    (
        "as printed in the report header; 'Current' is the spread when the test ran",
        (
            "tal como impresso no cabeçalho do relatório; 'Current' é o spread no momento em que "
            "o teste foi feito"
        ),
    ),
    (
        "trades that open or close outside the dates the header says were tested",
        "operações que abrem ou fecham fora das datas que o cabeçalho diz terem sido testadas",
    ),
    (
        "the file is not a MetaTrader tester report",
        "o arquivo não é um relatório do testador do MetaTrader",
    ),
    (
        "the report does not state a modelling mode we recognise",
        "o relatório não indica um modo de modelagem que reconheçamos",
    ),
    (
        "the report prints no data quality (n/a)",
        "o relatório não imprime a qualidade dos dados (n/a)",
    ),
    (
        "the report prints no test window",
        "o relatório não imprime as datas do teste",
    ),
    (
        "no test window or no trades to compare",
        "não há datas de teste ou operações com que comparar",
    ),
    (
        "the report does not print it",
        "o relatório não o imprime",
    ),
    (
        (
            "deepest fall in money over one year of trades drawn at random from the history, at "
            "the backtest's sizes"
        ),
        (
            "maior queda em dinheiro em um ano de operações sorteadas ao acaso do histórico, no "
            "tamanho do backtest"
        ),
    ),
    (
        "deepest fall in money of the closed trades in their own order",
        "maior queda em dinheiro das operações fechadas na sua própria ordem",
    ),
    (
        (
            "the largest of the resampled 95th percentile, the history's own fall and any "
            "drawdown with open trades from the platform or the equity curve"
        ),
        (
            "a maior entre o percentil 95 reamostrado, a queda do próprio histórico e qualquer "
            "drawdown com operações abertas da plataforma ou da curva de patrimônio"
        ),
    ),
    (
        (
            "the closed trades end with a net loss, so no size is given for them: at any size "
            "the history loses"
        ),
        (
            "as operações fechadas terminam com perda líquida, então não se indica um tamanho "
            "para elas: em qualquer tamanho o histórico perde"
        ),
    ),
    (
        "deepest fall in money of the uploaded equity curve, open trades included",
        "maior queda em dinheiro da curva de patrimônio enviada, com operações abertas",
    ),
    (
        "no equity curve with open trades in money",
        "não há uma curva de patrimônio em dinheiro com operações abertas",
    ),
    (
        (
            "the trades overlap as a grid or with hidden open losses, so closed trades "
            "understate the real fall; upload an equity curve that includes open trades or the "
            "platform report with its equity drawdown"
        ),
        (
            "as operações se sobrepõem em grid ou com perdas abertas ocultas, então as operações "
            "fechadas subestimam a queda real; envie uma curva de patrimônio que inclua as "
            "operações abertas ou o relatório da plataforma com o drawdown de patrimônio"
        ),
    ),
    (
        "the platform's maximal drawdown in money, open trades included",
        "o drawdown máximo da plataforma em dinheiro, com operações abertas",
    ),
    (
        "the file does not print the platform's drawdown in money",
        "o arquivo não imprime o drawdown da plataforma em dinheiro",
    ),
    (
        "days from the first entry to the last exit",
        "dias da primeira entrada até a última saída",
    ),
    (
        "reference fall / loss limit, at the backtest's sizes",
        "queda de referência / limite de perda, no tamanho do backtest",
    ),
    (
        "loss limit x starting balance / reference fall",
        "limite de perda x saldo inicial / queda de referência",
    ),
    (
        "closed trades per year in the history",
        "operações fechadas por ano no histórico",
    ),
    (
        "closed trades per year at the history's pace; the history is shorter than a year",
        "operações fechadas por ano no ritmo do histórico; o histórico dura menos de um ano",
    ),
    (
        "starting balance of the uploaded file",
        "saldo inicial do arquivo enviado",
    ),
    (
        "the file states no starting balance",
        "o arquivo não indica um saldo inicial",
    ),
    (
        "needs at least {n} closed trades; {m} supplied",
        "precisa de pelo menos {n} operações fechadas; foram fornecidas {m}",
    ),
    (
        (
            "needs trades spread over at least {n} days; a shorter history stretched to a year "
            "gives capital figures too uncertain to act on"
        ),
        (
            "precisa de operações distribuídas em pelo menos {n} dias; um histórico mais curto "
            "esticado para um ano dá cifras de capital incertas demais para decidir com elas"
        ),
    ),
    (
        (
            "the trades show almost no fall to size against: under half a percent of the "
            "starting balance"
        ),
        (
            "as operações quase não mostram uma queda com que dimensionar: menos de meio por "
            "cento do saldo inicial"
        ),
    ),
    (
        "the trades show no fall to size against",
        "as operações não mostram uma queda com que dimensionar",
    ),
    (
        (
            "{n} settings one step away keep {p} of the chosen profit at the median and {q} of "
            "them end with a profit: the chosen settings look like a lone peak"
        ),
        (
            "{n} configurações a um passo conservam na mediana {p} do resultado escolhido e {q} "
            "delas terminam com ganho: os parâmetros escolhidos parecem um pico isolado"
        ),
    ),
    (
        "from the rows of the optimisation export",
        "das linhas da exportação de otimização",
    ),
    (
        "rank of the chosen pass / passes",
        "posição da passada escolhida / passadas",
    ),
    (
        "median neighbour profit / chosen profit",
        "resultado mediano dos vizinhos / resultado escolhido",
    ),
    (
        "the chosen pass shows no profit",
        "a passada escolhida não tem ganho",
    ),
    (
        "the optimisation did not try the settings one step away (genetic or sparse)",
        "a otimização não testou as configurações a um passo (genética ou esparsa)",
    ),
    (
        "no optimisation file uploaded",
        "nenhum arquivo de otimização enviado",
    ),
    (
        (
            "the export has no Profit column; its Result column is the optimisation criterion "
            "(by default the final balance), not a profit"
        ),
        (
            "a exportação não tem coluna Profit; a sua coluna Result é o critério de otimização "
            "(por padrão, o saldo final), não um resultado"
        ),
    ),
    (
        "needs at least {n} passes with a profit column and a parameter that varies",
        "precisa de pelo menos {n} passadas com coluna de resultado e um parâmetro que varie",
    ),
    (
        "the file is a backtest, not an account history",
        "o arquivo é um backtest, não o histórico de uma conta",
    ),
    (
        (
            "time-weighted: deposits and withdrawals are taken out, as track-record sites "
            "compute gain"
        ),
        (
            "ponderado no tempo: depósitos e saques são retirados, como os sites de históricos "
            "calculam o ganho"
        ),
    ),
    (
        "closed trades after commission and swap, in the account currency",
        "operações fechadas depois de comissões e swap, na moeda da conta",
    ),
    (
        "trading result / money deposited",
        "resultado de operar / dinheiro depositado",
    ),
    (
        "withdrawn / deposited",
        "sacado / depositado",
    ),
    (
        "the file lists no deposit",
        "o arquivo não inclui nenhum depósito",
    ),
    (
        "the platform's own summary at the time of the statement",
        "resumo da própria plataforma no momento do extrato",
    ),
    (
        "floating result / balance",
        "resultado flutuante / saldo",
    ),
    (
        "the file does not state the floating result",
        "o arquivo não indica o resultado flutuante",
    ),
    (
        "earlier deposits and withdrawals plus trades closed before it",
        "depósitos e saques anteriores mais as operações fechadas antes dele",
    ),
    (
        "flow-adjusted drawdown on the day before",
        "drawdown ajustado por depósitos no dia anterior",
    ),
    (
        "no curve point before the deposit",
        "não há um ponto da curva antes do depósito",
    ),
    (
        "up to {n} positions were open at once on one symbol",
        "houve até {n} posições abertas ao mesmo tempo em um mesmo símbolo",
    ),
    (
        (
            "the curve is rebuilt from closed trades while positions overlapped; floating losses "
            "of open positions are not visible in it"
        ),
        (
            "a curva é reconstruída com operações fechadas enquanto havia posições sobrepostas; "
            "as perdas flutuantes das posições abertas não aparecem nela"
        ),
    ),
    (
        (
            "win rate {w} with the average loss {m}x the average win: rare large losses carry "
            "the risk"
        ),
        (
            "taxa de acerto de {w} com a perda média {m}x o ganho médio: o risco está em perdas "
            "grandes e pouco frequentes"
        ),
    ),
    (
        "the largest adverse excursion is {m}x the average loss; no sign of a fixed stop",
        "a maior excursão adversa é {m}x a perda média; não há sinal de um stop fixo",
    ),
    (
        (
            "the {k} best passes of the backtest end the forward period with a profit in {a} of "
            "cases, against {b} for all passes; rank correlation between the periods {r}"
        ),
        (
            "as {k} melhores passadas do backtest terminam o período forward com ganho em {a} "
            "dos casos, contra {b} de todas as passadas; correlação de postos entre os períodos "
            "{r}"
        ),
    ),
    (
        "rank correlation between the back and forward results {r}",
        "correlação de postos entre os resultados do backtest e do forward {r}",
    ),
    (
        (
            "the optimisation file has two result columns before Profit, as a forward export "
            "does, but they are not named Forward Result and Back Result; export it again from a "
            "terminal set to English"
        ),
        (
            "o arquivo de otimização tem duas colunas de resultado antes de Profit, como uma "
            "exportação forward, mas elas não se chamam Forward Result e Back Result; exporte-o "
            "novamente de um terminal em inglês"
        ),
    ),
    (
        (
            "the optimisation file is not a forward export (no Forward Result and Back Result "
            "columns)"
        ),
        (
            "o arquivo de otimização não é uma exportação forward (não tem as colunas Forward "
            "Result e Back Result)"
        ),
    ),
    (
        "needs at least {n} passes with a back and a forward result",
        "são necessárias pelo menos {n} passadas com resultado de backtest e de forward",
    ),
    (
        "every pass has the same back or forward result",
        "todas as passadas têm o mesmo resultado de backtest ou de forward",
    ),
    (
        "from the rows of the forward optimisation export",
        "das linhas da exportação forward",
    ),
    (
        "Spearman correlation between the back and the forward result of every pass",
        "correlação de Spearman entre o resultado de backtest e o de forward de cada passada",
    ),
    (
        "the best tenth of the passes by back result, at least five",
        "o melhor décimo das passadas por resultado de backtest, pelo menos cinco",
    ),
    (
        "share of the best backtest passes with a forward profit",
        "parcela das melhores passadas do backtest com ganho no forward",
    ),
    (
        "share of all passes with a forward profit",
        "parcela de todas as passadas com ganho no forward",
    ),
    (
        "median forward profit of the best backtest passes",
        "ganho mediano no forward das melhores passadas do backtest",
    ),
    (
        "median forward profit of all passes",
        "ganho mediano no forward de todas as passadas",
    ),
    (
        "the export has no Profit column for the forward period",
        "a exportação não tem a coluna Profit do período forward",
    ),
    (
        "share of the other passes with a lower forward result",
        "parcela das demais passadas com um resultado forward menor",
    ),
    (
        "forward profit of the pass matching the tester report",
        "ganho no forward da passada que coincide com o relatório do testador",
    ),
    (
        "no pass matches the inputs of the uploaded tester report",
        "nenhuma passada coincide com as entradas do relatório do testador enviado",
    ),
    (
        (
            "a forward export: its Profit column is the forward period's; the forward section "
            "reads it, and this check needs the main optimisation export"
        ),
        (
            "uma exportação forward: a sua coluna Profit é a do período forward; a seção forward "
            "a lê, e esta verificação precisa da exportação principal da otimização"
        ),
    ),
    (
        (
            "the {n} trades since {d} (the last third of the history) average {a} per trade, "
            "against {b} for the {m} earlier ones; the drop is {z} standard errors"
        ),
        (
            "as {n} operações desde {d} (o último terço do histórico) têm média de {a} por "
            "operação, contra {b} das {m} anteriores; a queda é de {z} erros-padrão"
        ),
    ),
    (
        "needs at least {n} closed trades",
        "são necessárias pelo menos {n} operações fechadas",
    ),
    (
        "the trades span less than two years, too short to compare periods",
        "as operações abrangem menos de dois anos, pouco demais para comparar períodos",
    ),
    (
        (
            "needs at least {n} closed trades in the recent third of the history and in the "
            "earlier two thirds"
        ),
        (
            "são necessárias pelo menos {n} operações fechadas no último terço do histórico e "
            "nos dois terços anteriores"
        ),
    ),
    (
        "a trade result is not a finite number",
        "um resultado de operação não é um número finito",
    ),
    (
        "closed trades by exit date; net result after the fees the file itemises",
        (
            "operações fechadas por data de fechamento; resultado líquido após os custos que o "
            "arquivo detalha"
        ),
    ),
    (
        "average net result per trade",
        "resultado líquido médio por operação",
    ),
    (
        "needs at least {n} winning and {m} losing trades",
        "são necessárias pelo menos {n} operações ganhadoras e {m} perdedoras",
    ),
    (
        "closed trades by entry and exit time; net result after the fees the file itemises",
        (
            "operações fechadas por horário de entrada e de fechamento; resultado líquido após "
            "os custos que o arquivo detalha"
        ),
    ),
    (
        "median hours a winning trade stays open",
        "horas medianas que uma ganhadora fica aberta",
    ),
    (
        "median hours a losing trade stays open",
        "horas medianas que uma perdedora fica aberta",
    ),
    (
        "median losing hold over median winning hold",
        "duração mediana das perdedoras dividida pela das ganhadoras",
    ),
    (
        "share of trades after a loss opened within 15 minutes of it",
        "parcela das operações após uma perda abertas em menos de 15 minutos",
    ),
    (
        "share of trades after a win opened within 15 minutes of it",
        "parcela das operações após um ganho abertas em menos de 15 minutos",
    ),
    (
        "after the fees the file itemises per trade",
        "depois dos custos que o arquivo detalha por operação",
    ),
    (
        "share of trades with a net profit after the fees the file itemises",
        (
            "parcela das operações com resultado líquido positivo, depois dos custos que o "
            "arquivo detalha"
        ),
    ),
    (
        "share of trades with a net profit",
        "parcela das operações com resultado líquido positivo",
    ),
    (
        "the file has no time of day",
        "o arquivo não tem horário do dia",
    ),
    (
        "the file is not a monthly track record",
        "o arquivo não é um histórico mensal",
    ),
    (
        "the fund's own returns after its fees; costs were not measured",
        "rentabilidades do próprio fundo após as suas taxas; os custos não foram medidos",
    ),
    (
        (
            "the net-of-fees declaration applies only to a monthly fund track record; costs are "
            "checked as usual"
        ),
        (
            "a declaração de rentabilidades líquidas de taxas só vale para o histórico mensal de "
            "um fundo; os custos são revisados como sempre"
        ),
    ),
    (
        "needs at least {n} monthly returns",
        "são necessárias pelo menos {n} rentabilidades mensais",
    ),
    (
        "the monthly returns do not vary",
        "as rentabilidades mensais não variam",
    ),
    (
        (
            "every published preset simulated on the same resampled daily paths, rules as each "
            "firm's page stated them on its as_of date; a program's phases are taken as fresh "
            "starts, so the chance of passing them all is the product of each phase's"
        ),
        (
            "cada desafio publicado simulado sobre os mesmos percursos diários reamostrados, com "
            "as regras que a página de cada firma indicava na sua data; as fases de um programa "
            "são tomadas como recomeços, então a probabilidade de passar por todas é o produto "
            "da de cada fase"
        ),
    ),
    (
        (
            "share of the resampled passes whose best day breaks the firm's best-day rule, "
            "checked at the pass on daily closes"
        ),
        (
            "proporção dos percursos reamostrados que chegam ao objetivo cujo melhor dia viola a "
            "regra do melhor dia da firma, conferida ao atingir o objetivo com fechamentos "
            "diários"
        ),
    ),
    (
        (
            "share of all resampled paths that reach the target with the best day inside the "
            "firm's best-day rule; the rule is checked at the pass, on daily closes"
        ),
        (
            "proporção de todos os percursos reamostrados que chegam ao objetivo com o melhor "
            "dia dentro da regra do melhor dia da firma; a regra é conferida ao atingir o "
            "objetivo, com fechamentos diários"
        ),
    ),
    (
        "the curve covers none of the dated market falls in full",
        "a curva não cobre por completo nenhuma das quedas de mercado com data",
    ),
    (
        "the curve is shorter than two months",
        "a curva dura menos de dois meses",
    ),
    (
        "the curve never moves 0.1 % from its start",
        "a curva nunca se afasta 0.1 % do seu início",
    ),
    (
        (
            "fixed calendar windows of widely recorded market falls; the curve's month-end "
            "returns compounded over each window it covers in full"
        ),
        (
            "períodos fixos de quedas de mercado com data pública; as rentabilidades de fim de "
            "mês da curva compostas em cada período que ela cobre por completo"
        ),
    ),
    (
        "the curve has no usable month-end levels",
        "a curva não tem saldos de fim de mês utilizáveis",
    ),
    (
        "month-end returns as the file states them",
        "rentabilidades de fim de mês tal como o arquivo as fornece",
    ),
    (
        "annualised standard deviation",
        "desvio-padrão anualizado",
    ),
    (
        "first-order autocorrelation of monthly returns",
        "autocorrelação de primeira ordem das rentabilidades mensais",
    ),
    (
        "annualised volatility of the unsmoothed returns",
        "volatilidade anualizada das rentabilidades sem suavização",
    ),
    (
        (
            "read as a monthly returns table (one row per year, one column per month); values "
            "taken as percentages"
        ),
        (
            "lido como tabela de rentabilidades mensais (uma linha por ano, uma coluna por mês); "
            "valores tomados como porcentagens"
        ),
    ),
    (
        (
            "read as a monthly returns table (one row per year, one column per month); values "
            "taken as fractions"
        ),
        (
            "lido como tabela de rentabilidades mensais (uma linha por ano, uma coluna por mês); "
            "valores tomados como frações"
        ),
    ),
    (
        (
            "read as a monthly returns table (one row per year, one column per month); values "
            "taken as fractions, as the year totals confirm"
        ),
        (
            "lido como tabela de rentabilidades mensais (uma linha por ano, uma coluna por mês); "
            "valores tomados como frações, como confirmam os totais anuais"
        ),
    ),
    (
        (
            "read as a monthly returns table (one row per year, one column per month); values "
            "taken as percentages, as the year totals confirm"
        ),
        (
            "lido como tabela de rentabilidades mensais (uma linha por ano, uma coluna por mês); "
            "valores tomados como porcentagens, como confirmam os totais anuais"
        ),
    ),
    (
        (
            "read as a monthly returns table (one row per year, one column per month); values "
            "taken as percentages (the file shows no % sign: check one month against the "
            "factsheet)"
        ),
        (
            "lido como tabela de rentabilidades mensais (uma linha por ano, uma coluna por mês); "
            "valores tomados como porcentagens (o arquivo não mostra o sinal %: compare um mês "
            "com a lâmina do fundo)"
        ),
    ),
    (
        "{count} unreadable month(s) left out of the table: {cells}",
        "{count} mês(es) ilegível(is) deixado(s) fora da tabela: {cells}",
    ),
    (
        "benchmark rows read from the table: the fund section compares the fund with them",
        (
            "linhas do índice de referência lidas da tabela: a seção de fundos compara o fundo "
            "com elas"
        ),
    ),
    (
        "{n} row(s) of differences between the fund and its benchmark left out",
        (
            "{n} linha(s) de diferenças entre o fundo e o seu índice de referência deixada(s) "
            "fora da análise"
        ),
    ),
    (
        "benchmark column {column} read: the fund section compares the fund with it",
        "coluna de índice de referência {column} lida: a seção de fundos compara o fundo com ela",
    ),
    (
        "the benchmark column {column} could not be read; left out",
        "a coluna de índice de referência {column} não pôde ser lida; fica fora",
    ),
    (
        "the benchmark's returns as supplied; Rigor did not check them against the index",
        (
            "rentabilidades do índice de referência tal como foram fornecidas; o Rigor não as "
            "conferiu com o índice"
        ),
    ),
    (
        "needs at least {n} months shared with the benchmark",
        "precisa de pelo menos {n} meses em comum com o índice de referência",
    ),
    (
        "the benchmark's monthly returns do not vary",
        "as rentabilidades mensais do índice de referência não variam",
    ),
    (
        "needs at least {n} months with the benchmark up",
        "precisa de pelo menos {n} meses com o índice de referência em alta",
    ),
    (
        "needs at least {n} months with the benchmark down",
        "precisa de pelo menos {n} meses com o índice de referência em baixa",
    ),
    (
        "fund's compound annual return minus the benchmark's",
        "rentabilidade anual composta do fundo menos a do índice de referência",
    ),
    (
        "annualised standard deviation of the monthly differences",
        "desvio-padrão anualizado das diferenças mensais",
    ),
    (
        (
            "fixed calendar windows of widely recorded market falls; the fund's months "
            "compounded over each window it covers in full"
        ),
        (
            "períodos fixos de quedas de mercado com data pública; os meses do fundo compostos "
            "em cada período que ele cobre por completo"
        ),
    ),
    (
        "the stated year total does not match its months for {years}",
        "o total anual indicado não bate com os seus meses em {years}",
    ),
    (
        "the file does not name each trade's instrument",
        "o arquivo não indica o instrumento de cada operação",
    ),
    (
        "every trade is on one instrument",
        "todas as operações são do mesmo instrumento",
    ),
    (
        (
            "closed trades by the instrument the file names; net result after the fees the file "
            "itemises"
        ),
        (
            "operações fechadas pelo instrumento que o arquivo indica; resultado líquido após os "
            "custos que o arquivo detalha"
        ),
    ),
    (
        "share with a net profit among trades that follow {n} losses in a row",
        "parcela com resultado líquido positivo entre as operações que seguem {n} perdas seguidas",
    ),
    (
        "distance of the recent average from the earlier one, in standard errors",
        "distância da média recente em relação à anterior, em erros-padrão",
    ),
    (
        (
            "the best trade makes {share} of the total of the winning trades; without it and the "
            "worst loss the rest keep {keep} of the net result ({n} trades)"
        ),
        (
            "a melhor operação responde por {share} do total das operações ganhadoras; sem ela e "
            "sem a pior perda, o restante conserva {keep} do resultado líquido ({n} operações)"
        ),
    ),
    (
        (
            "the best {k} trades make {share} of the total of the winning trades; without them "
            "and the {j} worst losses the rest keep {keep} of the net result ({n} trades)"
        ),
        (
            "as {k} melhores operações respondem por {share} do total das operações ganhadoras; "
            "sem elas e sem as {j} piores perdas, o restante conserva {keep} do resultado "
            "líquido ({n} operações)"
        ),
    ),
    (
        "the largest loss is {m}x the average loss; no sign of a fixed stop",
        "a maior perda é {m}x a perda média; não há sinal de um stop fixo",
    ),
    (
        (
            "{a} of {n} trades ({p}) close outside the dates of the equity curve; the two files "
            "may not describe the same account"
        ),
        (
            "{a} de {n} operações ({p}) fecham fora das datas da curva de patrimônio; talvez os "
            "dois arquivos não descrevam a mesma conta"
        ),
    ),
    (
        (
            "month by month the realised trade pnl and the equity change correlate at {c} over "
            "{n} months; the trades may not belong to this equity curve, so the cost dimension "
            "may not describe it"
        ),
        (
            "mês a mês, o resultado realizado das operações e a variação do patrimônio têm uma "
            "correlação de {c} em {n} meses; talvez as operações não sejam desta curva e, então, "
            "a dimensão de custos não a descreve"
        ),
    ),
    (
        "no long trades",
        "não há operações compradas",
    ),
    (
        "no short trades",
        "não há operações vendidas",
    ),
    (
        "no trades uploaded",
        "nenhuma operação enviada",
    ),
    (
        "under a year of history; annualising it would exaggerate",
        "menos de um ano de histórico; anualizá-lo o exageraria",
    ),
    (
        "no variants uploaded",
        "a matriz de variantes não foi enviada",
    ),
    (
        "fewer than ten returns",
        "menos de dez retornos",
    ),
    (
        "the simulator needs daily or finer data; the upload is coarser",
        "o simulador precisa de dados diários ou mais finos; os enviados são mais grossos",
    ),
    (
        "before commission and swap",
        "antes de comissão e swap",
    ),
    (
        "share of trades with pnl > 0",
        "proporção de operações com resultado > 0",
    ),
    (
        "commission and swap as reported, a positive cost",
        "comissão e swap do relatório, como custo positivo",
    ),
    (
        "no commission or swap total supplied",
        "o total de comissão ou swap não foi fornecido",
    ),
    (
        "gross pnl minus reported fees",
        "resultado bruto menos os custos do relatório",
    ),
    (
        "the uploaded history with its best outcomes removed; not a forecast",
        "o histórico enviado sem os seus melhores resultados; não é uma previsão",
    ),
    (
        "compounded total return of the uploaded curve",
        "retorno total composto da curva enviada",
    ),
    (
        "net result of the closed trades after reported fees",
        "resultado líquido das operações fechadas após os custos do relatório",
    ),
    (
        "best five trades / net result",
        "cinco melhores operações / resultado líquido",
    ),
    (
        "the curve is too short or not positive",
        "a curva é curta demais ou não é positiva",
    ),
    (
        "fewer than two closed trades",
        "menos de duas operações fechadas",
    ),
    (
        "fewer than {n} closed trades",
        "menos de {n} operações fechadas",
    ),
    (
        "the backtest has no closed trades",
        "o backtest não tem operações fechadas",
    ),
    (
        "the backtest has fewer than {n} closed trades",
        "o backtest tem menos de {n} operações fechadas",
    ),
    (
        "the live statement has fewer than {n} closed trades",
        "a conta real tem menos de {n} operações fechadas",
    ),
    (
        (
            "Backtest trades resampled with replacement, as many as the live statement holds; "
            "costs itemised per trade subtracted on both sides. Streaks are not preserved."
        ),
        (
            "Operações do backtest sorteadas com reposição, tantas quantas tem a conta real; os "
            "custos detalhados por operação são descontados dos dois lados. Não preserva as "
            "sequências."
        ),
    ),
    (
        (
            "Paired by side, symbol and entry time within 60 minutes, as the files state the "
            "times; price differences in basis points (0.01 %), positive when worse for the "
            "account; result differences at the backtest trade's size."
        ),
        (
            "Pareadas por lado, símbolo e horário de entrada com menos de 60 minutos de "
            "diferença, com os horários tal como os arquivos os fornecem; diferenças de preço em "
            "pontos-base (0.01 %), positivas quando são piores para a conta; diferenças de "
            "resultado no tamanho da operação do backtest."
        ),
    ),
    (
        "deepest drawdown the platform prints with open trades counted",
        "o drawdown mais profundo que a plataforma imprime contando as operações abertas",
    ),
    (
        "per side on {pair} at {price}, the median entry price",
        "por lado em {pair} a {price}, o preço de entrada mediano",
    ),
    (
        "paired live trades / live trades",
        "operações reais pareadas / operações reais",
    ),
    (
        "fewer than {n} paired trades",
        "menos de {n} operações pareadas",
    ),
    (
        "no live trades on the shared dates",
        "não há operações reais nas datas em comum",
    ),
    (
        "{s} resampled histories of {n} backtest trades, seed {seed}",
        "{s} históricos reamostrados de {n} operações do backtest, semente {seed}",
    ),
    (
        (
            "Entry times as the file states them (platform or server time); net result after the "
            "fees the file itemises per trade."
        ),
        (
            "Horários de entrada tal como o arquivo os fornece (hora da plataforma ou do "
            "servidor); resultado líquido depois dos custos que o arquivo detalha por operação."
        ),
    ),
    (
        "average net result per trade, account currency",
        "resultado líquido médio por operação, na moeda da conta",
    ),
    (
        "gross profit / gross loss",
        "ganho bruto / perda bruta",
    ),
    (
        (
            "gross profit / gross loss, before commission and swap; a platform that counts them "
            "inside each trade can show a slightly lower figure"
        ),
        (
            "ganho bruto / perda bruta, antes de comissões e swap; uma plataforma que os conta "
            "dentro de cada operação pode mostrar um número um pouco menor"
        ),
    ),
    (
        "no losing trades; the ratio is undefined",
        "não há operações perdedoras; a razão não está definida",
    ),
    (
        "no winning trades",
        "não há operações ganhadoras",
    ),
    (
        "no losing trades",
        "não há operações perdedoras",
    ),
    (
        "average win / average loss",
        "ganho médio / perda média",
    ),
    (
        "needs at least one win and one loss",
        "precisa de pelo menos uma ganhadora e uma perdedora",
    ),
    (
        "largest single win / gross profit",
        "maior ganhadora / ganho bruto",
    ),
    (
        "sqrt(min(N, {cap})) x mean / std of per-trade gross pnl",
        "raiz(mín(N, {cap})) x média / desvio do resultado bruto por operação",
    ),
    (
        "needs at least two trades with different results",
        "precisa de pelo menos duas operações com resultados diferentes",
    ),
    (
        "first entry to last exit",
        "da primeira entrada à última saída",
    ),
    (
        "trades span less than one day",
        "as operações abrangem menos de um dia",
    ),
    (
        "needs at least {n} daily returns that are not all identical; {m} supplied",
        (
            "precisa de pelo menos {n} retornos diários que não sejam todos idênticos; foram "
            "fornecidos {m}"
        ),
    ),
    (
        "needs at least {n} returns that are not all identical; {m} supplied",
        "precisa de pelo menos {n} retornos que não sejam todos idênticos; foram fornecidos {m}",
    ),
    (
        "the history is too short to resample a year at this frequency",
        "o histórico é curto demais para reamostrar um ano com esta frequência",
    ),
    (
        "resampled from the uploaded history, not a forecast",
        "reamostrado do histórico enviado, não é uma previsão",
    ),
    (
        "business days, resampled from the uploaded history, not a forecast",
        "dias úteis, reamostrado do histórico enviado, não é uma previsão",
    ),
    (
        "Wilson 95 % interval over the resampled paths; it ignores model error",
        (
            "intervalo de Wilson a 95 % sobre as trajetórias reamostradas; não inclui o erro do "
            "modelo"
        ),
    ),
    (
        "no resampled path reached the target within the limits",
        "nenhuma trajetória reamostrada atingiu o objetivo dentro dos limites",
    ),
    (
        "P[true Sharpe > 0] given length, skew and kurtosis",
        "P[Sharpe real > 0] dados o tamanho, a assimetria e a curtose",
    ),
    (
        "observations needed for PSR to reach 0.95",
        "observações necessárias para que o PSR chegue a 0.95",
    ),
    (
        "observed Sharpe <= 0; no track record length reaches 0.95",
        "Sharpe observado <= 0; nenhum tamanho de histórico chega a 0.95",
    ),
    (
        "unreachable",
        "inatingível",
    ),
    (
        "variance across {n} variants",
        "variância entre {n} variantes",
    ),
    (
        "sampling variance of the Sharpe estimator",
        "variância amostral do estimador de Sharpe",
    ),
    (
        "PSR against E[max Sharpe] of 1 trial",
        "PSR contra E[Sharpe máximo] de 1 tentativa",
    ),
    (
        "PSR against E[max Sharpe] of 1 trial, {source}",
        "PSR contra E[Sharpe máximo] de 1 tentativa, {source}",
    ),
    (
        "PSR against E[max Sharpe] of {n} trials",
        "PSR contra E[Sharpe máximo] de {n} tentativas",
    ),
    (
        "PSR against E[max Sharpe] of {n} trials, {source}",
        "PSR contra E[Sharpe máximo] de {n} tentativas, {source}",
    ),
    (
        "PSR against E[max Sharpe] of {n} trial(s)",
        "PSR contra E[Sharpe máximo] de {n} tentativa(s)",
    ),
    (
        "PSR against E[max Sharpe] of {n} trial(s), {source}",
        "PSR contra E[Sharpe máximo] de {n} tentativa(s), {source}",
    ),
    (
        "smallest power-of-two trial count with DSR < 0.5",
        "menor número de tentativas, em potências de dois, com DSR < 0.5",
    ),
    (
        "DSR stays >= 0.5 up to {n} trials",
        "o DSR se mantém >= 0.5 até {n} tentativas",
    ),
    (
        "too short",
        "curto demais",
    ),
    (
        "declared by the client; not verifiable",
        "declarado pelo cliente; não pode ser conferido",
    ),
    (
        "in-sample minus out-of-sample annualised Sharpe",
        "Sharpe anualizado dentro da amostra menos fora da amostra",
    ),
    (
        "strategy max drawdown over benchmark max drawdown",
        "drawdown máximo da estratégia dividido pelo do benchmark",
    ),
    (
        "benchmark has no drawdown",
        "o benchmark não tem drawdown",
    ),
    (
        "benchmark overlaps only {p} of the strategy timestamps",
        "o benchmark só coincide com {p} das datas da estratégia",
    ),
    (
        "fraction of CSCV splits where the IS winner is below the OOS median",
        (
            "fração das divisões CSCV em que a melhor dentro da amostra fica abaixo da mediana "
            "fora da amostra"
        ),
    ),
    (
        "CSCV requires at least two parameter variants",
        "o CSCV precisa de pelo menos duas variantes de parâmetros",
    ),
    (
        "variant_returns must contain only finite values",
        "a matriz de variantes só pode conter valores finitos",
    ),
    (
        (
            "observations must be divisible into equal CSCV partitions ({n} observations, {m} "
            "partitions)"
        ),
        (
            "as observações devem ser divididas em partições CSCV iguais ({n} observações, {m} "
            "partições)"
        ),
    ),
    (
        "a side has fewer than {n} returns (in-sample {a}, out-of-sample {b})",
        "um dos trechos tem menos de {n} retornos (dentro da amostra {a}, fora da amostra {b})",
    ),
    (
        "split failed: {error}",
        "não foi possível dividir a série: {error}",
    ),
    (
        "extra cost per side, on top of the report's fees, at which the ledger nets to zero",
        "custo extra por lado, além dos custos do relatório, com o qual o resultado fica em zero",
    ),
    (
        "cost per side at which the ledger nets to zero",
        "custo por lado com o qual o resultado fica em zero",
    ),
    (
        "no traded notional",
        "não há volume operado",
    ),
    (
        "undefined",
        "não definido",
    ),
    (
        "signed total the report itemises; negative is a cost",
        "total com sinal que o relatório detalha; negativo é um custo",
    ),
    (
        (
            "assumed slippage: the client declared zero cost; charged on top of the fees the "
            "report itemises"
        ),
        (
            "slippage suposto: o cliente declarou custo zero; é cobrado além dos custos que o "
            "relatório detalha"
        ),
    ),
    (
        "assumed: client declared zero cost",
        "suposto: o cliente declarou custo zero",
    ),
    (
        (
            "assumed slippage: an account history's prices are the broker's fills, so the spread "
            "is already in each result; charged on top"
        ),
        (
            "slippage suposto: os preços de um histórico de conta são as execuções da corretora, "
            "então o spread já está em cada resultado; é cobrado além disso"
        ),
    ),
    (
        "declared by the client; charged on top of the fees the report itemises",
        "declarado pelo cliente; é cobrado além dos custos que o relatório detalha",
    ),
    (
        "inferred from the timestamps",
        "deduzido das datas",
    ),
    (
        "starting balance of the imported report",
        "saldo inicial do relatório importado",
    ),
    (
        "no report imported",
        "nenhum relatório importado",
    ),
    (
        "rows of the export",
        "linhas da exportação",
    ),
    (
        "not declared",
        "não declarado",
    ),
    (
        "holdout not evaluated",
        "trecho fora da amostra não avaliado",
    ),
    (
        "balance rebuilt from closed trades; floating drawdown is not visible",
        "saldo reconstruído com operações fechadas; o drawdown flutuante não aparece",
    ),
    (
        "as uploaded",
        "tal como enviado",
    ),
    (
        "[withheld: promotional wording]",
        "[omitido: linguagem promocional]",
    ),
    (
        "Generic",
        "Genérico",
    ),
    (
        "Two-step evaluation, phase 1",
        "Avaliação em duas fases, fase 1",
    ),
    (
        "each of steps 1-3",
        "cada uma das fases 1-3",
    ),
    (
        "Reference rules typical of two-step evaluations; not any one firm's terms.",
        (
            "Regras de referência típicas das avaliações em duas fases; não são as de nenhuma "
            "firma específica."
        ),
    ),
    (
        "Daily loss: 5 % of the initial balance below the balance recorded at 00:00 CE(S)T.",
        "Perda diária: 5 % do saldo inicial abaixo do saldo registrado às 00:00 CE(S)T.",
    ),
    (
        "No time limit ({url}).",
        "Sem limite de tempo ({url}).",
    ),
    (
        (
            "Maximum loss is an end-of-day trailing limit; whether it stops trailing was not "
            "stated on the page read, so the simulator lets it trail (stricter)."
        ),
        (
            "A perda máxima é um limite que acompanha o fechamento de cada dia; a página lida "
            "não diz se ele para de se mover, então o simulador o deixa se mover (mais rigoroso)."
        ),
    ),
    (
        (
            "Best Day Rule: the best day may not exceed 50 % of the positive days' profit; "
            "checked when a path reaches the target, on daily closes."
        ),
        (
            "Regra do melhor dia: o melhor dia não pode superar 50 % do resultado dos dias "
            "positivos; é conferida quando um percurso chega ao objetivo, com fechamentos "
            "diários."
        ),
    ),
    (
        "No minimum trading days; no time limit ({url}).",
        "Sem mínimo de dias operados; sem limite de tempo ({url}).",
    ),
    (
        (
            "Daily loss: a percentage of the initial balance below the start-of-day balance, "
            "reset at 0:00 server time; it counts open losses, swap and commission."
        ),
        (
            "Perda diária: uma porcentagem do saldo inicial abaixo do saldo no início do dia, "
            "que é reiniciado às 0:00 no horário do servidor; conta perdas abertas, swap e "
            "comissão."
        ),
    ),
    (
        "No deadline; accounts with no trade for 60 days are deactivated.",
        "Sem prazo; as contas sem operações durante 60 dias são desativadas.",
    ),
    (
        "Expert advisors are not allowed on this model.",
        "Este modelo não permite robôs (expert advisors, EA).",
    ),
    (
        "Expert advisors allowed only on accounts below 50K.",
        "Robôs (expert advisors, EA) permitidos só em contas abaixo de 50K.",
    ),
    (
        (
            "Daily loss: 5 % below the higher of the previous day's closing balance or equity "
            "({url})."
        ),
        (
            "Perda diária: 5 % abaixo do maior entre o saldo e o patrimônio no fechamento do dia "
            "anterior ({url})."
        ),
    ),
    (
        (
            "Needs 3 days each closing at least 0.5 % of the initial balance in gain; the "
            "simulator counts any day with a non-zero return, so it is optimistic here."
        ),
        (
            "Exige 3 dias que fechem, cada um, com pelo menos 0.5 % do saldo inicial a favor; o "
            "simulador conta qualquer dia com retorno diferente de zero, então aqui ele é "
            "otimista."
        ),
    ),
    (
        "No trading from 2 minutes before to 2 minutes after high-impact news; not simulated.",
        (
            "Não se opera de 2 minutos antes até 2 minutos depois de notícias de alto impacto; "
            "não é simulado."
        ),
    ),
    (
        (
            "The 3 % daily limit suspends trading for the day instead of ending the account; not "
            "simulated."
        ),
        (
            "O limite diário de 3 % suspende as operações naquele dia em vez de encerrar a "
            "conta; não é simulado."
        ),
    ),
    (
        "Static stop-out at 6 %: stated on The5ers' blog, not on the rules page.",
        "Stop-out fixo em 6 %: indicado no blog da The5ers, não na página de regras.",
    ),
    (
        "No minimum days; unlimited time.",
        "Sem mínimo de dias; tempo ilimitado.",
    ),
    (
        (
            "The rules page table asks for 3 days that close in gain, while its text says there "
            "is no minimum days requirement; the simulator uses none (optimistic if the table "
            "applies)."
        ),
        (
            "A tabela da página de regras pede 3 dias que fechem com ganho, mas o texto dela diz "
            "que não há mínimo de dias; o simulador não aplica nenhum (otimista se a tabela "
            "valer)."
        ),
    ),
    (
        "Unlimited time.",
        "Tempo ilimitado.",
    ),
    (
        "No daily limit during the evaluation steps; static loss stated on The5ers' blog.",
        "Sem limite diário nas fases de avaliação; a perda fixa é indicada no blog da The5ers.",
    ),
    (
        "No position may risk more than 2 % of the balance at its stop loss; not simulated.",
        "Nenhuma posição pode arriscar mais de 2 % do saldo no seu stop loss; não é simulado.",
    ),
    (
        "Unlimited time, but each level is reachable for 48 hours after the previous one.",
        "Tempo ilimitado, mas cada nível só pode ser alcançado durante 48 horas após o anterior.",
    ),
    (
        (
            "Maximum loss trails the highest end-of-day balance and locks once it reaches the "
            "starting balance; it is monitored in real time, which daily data cannot see."
        ),
        (
            "A perda máxima acompanha o maior saldo de fechamento diário e se fixa ao chegar ao "
            "saldo inicial; é monitorada em tempo real, algo que os dados diários não enxergam."
        ),
    ),
    (
        "The daily loss limit is optional and not simulated.",
        "O limite de perda diária é opcional e não é simulado.",
    ),
    (
        (
            "Consistency target: the best day must stay at or below 55 % of the profit target, "
            "otherwise the target rises; checked when a path reaches the target, on daily closes."
        ),
        (
            "Meta de consistência: o melhor dia deve ficar em 55 % do objetivo de resultado ou "
            "menos; caso contrário, o objetivo sobe; é conferida quando um percurso chega ao "
            "objetivo, com fechamentos diários."
        ),
    ),
    (
        "No time limit stated on the pages read.",
        "As páginas lidas não indicam limite de tempo.",
    ),
    (
        "Source for the target and consistency rule: {url}",
        "Fonte do objetivo e da regra de consistência: {url}",
    ),
    (
        "the curve never falls below a previous high",
        "a curva nunca cai abaixo de um máximo anterior",
    ),
    (
        "the Sharpe ratio is zero or negative; there is no gain to discount",
        "o Sharpe é zero ou negativo; não há ganho a descontar",
    ),
    (
        "too short a history to discount",
        "histórico curto demais para descontar",
    ),
    (
        "annualised Sharpe of the uploaded history",
        "Sharpe anualizado do histórico enviado",
    ),
    (
        "best annualised Sharpe {n} trials with no skill would show",
        "melhor Sharpe anualizado que {n} tentativas sem habilidade mostrariam",
    ),
    (
        "first to last date of the uploaded history",
        "da primeira à última data do histórico",
    ),
    (
        "years of history at which the luck of {n} trials falls below this Sharpe",
        "anos de histórico com os quais a sorte de {n} tentativas fica abaixo deste Sharpe",
    ),
    (
        "one-sided p-value of the Sharpe, one test, with the spread of the deflated Sharpe",
        "valor p unilateral do Sharpe, um único teste, com a dispersão do Sharpe deflacionado",
    ),
    (
        "p-value x {n} (Bonferroni)",
        "valor p x {n} (Bonferroni)",
    ),
    (
        "annualised Sharpe after discounting {n} trials",
        "Sharpe anualizado depois de descontar {n} tentativas",
    ),
    (
        "share of the Sharpe the haircut removes",
        "parcela do Sharpe que o desconto remove",
    ),
    (
        (
            "E[max Sharpe] of unskilled trials (Bailey & Lopez de Prado); minimum backtest "
            "length (Bailey, Borwein, Lopez de Prado & Zhu); Bonferroni haircut (Harvey & Liu)"
        ),
        (
            "E[Sharpe máximo] de tentativas sem habilidade (Bailey e López de Prado); tamanho "
            "mínimo do backtest (Bailey, Borwein, López de Prado e Zhu); desconto de Bonferroni "
            "(Harvey e Liu)"
        ),
    ),
    (
        (
            "days with a trade result larger than the balance a withdrawal left, measured on the "
            "balance before that withdrawal"
        ),
        (
            "dias com um resultado maior que o saldo deixado por um saque, medidos sobre o saldo "
            "anterior a esse saque"
        ),
    ),
    (
        "too many trades to count the streak exactly",
        "operações demais para contar a sequência com exatidão",
    ),
    (
        "needs both losing and other trades",
        "precisa de operações perdedoras e não perdedoras",
    ),
    (
        "median longest losing run when trades lose as often as these, in random order",
        (
            "mediana da sequência de perdas mais longa com a mesma porcentagem de perdedoras, em "
            "ordem aleatória"
        ),
    ),
    (
        "longest losing run chance reaches once in twenty, at the same loss rate",
        (
            "sequência de perdas que o acaso atinge 1 a cada 20 vezes, com a mesma porcentagem "
            "de perdedoras"
        ),
    ),
    (
        "chance of a losing run at least this long, at the same loss rate",
        (
            "probabilidade de uma sequência de perdas pelo menos tão longa, com a mesma "
            "porcentagem de perdedoras"
        ),
    ),
    (
        "fewer than twenty points on the curve",
        "menos de vinte pontos na curva",
    ),
    (
        "the curve reaches zero or below",
        "a curva chega a zero ou abaixo",
    ),
    (
        "calendar days from a high until it is regained",
        "dias corridos desde um máximo até recuperá-lo",
    ),
    (
        "deepest fall from a previous high",
        "maior queda desde um máximo anterior",
    ),
    (
        "high to low",
        "do máximo ao mínimo",
    ),
    (
        "low to high",
        "do mínimo ao máximo anterior",
    ),
    (
        "not regained by the last date of the file",
        "não se recupera antes da última data do arquivo",
    ),
    (
        "from each day's last point",
        "com o último ponto de cada dia",
    ),
    (
        "the curve has no point on most days",
        "a curva não tem pontos na maioria dos dias",
    ),
    (
        "fewer than three calendar months",
        "menos de três meses corridos",
    ),
    (
        "calendar days from the uploaded equity curve; months from each month's last point",
        "dias corridos da curva de patrimônio enviada; meses com o último ponto de cada mês",
    ),
    (
        (
            "the monthly returns with each yearly fee taken out month by month; shown because "
            "the figures were not declared net of fees"
        ),
        (
            "as rentabilidades mensais com cada taxa anual descontada mês a mês; aparece porque "
            "os números não foram declarados líquidos de taxas"
        ),
    ),
    (
        (
            "the yearly fee that would leave the fund's months level with the benchmark's over "
            "the months they share"
        ),
        "a taxa anual que deixaria os meses do fundo no nível dos do benchmark nos meses em comum",
    ),
    (
        (
            "the curve was built from each trade's date and result only; without prices, "
            "quantities or entry times, holding times, entry timing and trade-level checks "
            "cannot be measured"
        ),
        (
            "a curva foi montada só com a data e o resultado de cada operação; sem preços, "
            "quantidades nem horários de entrada não é possível medir a duração das operações, o "
            "momento de entrada nem as verificações por operação"
        ),
    ),
    (
        (
            "the curve was read from the balance column you named; the file lists no trades, so "
            "trade-level checks cannot be measured"
        ),
        (
            "a curva foi lida da coluna de saldo que você indicou; o arquivo não lista "
            "operações, então não é possível medir as verificações por operação"
        ),
    ),
    (
        "{n} row(s) without a readable date or amount were left out",
        "ficaram de fora {n} linha(s) sem data ou valor legível",
    ),
    (
        (
            "read as a monthly returns table (one row per year, one column per month); values "
            "taken as fractions (four or more decimals and none reaching 1, with no % sign: "
            "check one month against the factsheet)"
        ),
        (
            "lido como tabela de rentabilidades mensais (uma linha por ano, uma coluna por mês); "
            "valores tomados como frações (quatro ou mais casas decimais e nenhum chegando a 1, "
            "sem o sinal %: compare um mês com a lâmina do fundo)"
        ),
    ),
    (
        "no losing period; downside deviation is zero",
        "nenhum período com perda; o desvio negativo é zero",
    ),
    (
        (
            "the futures results are in different currencies ({currencies}) and were added as "
            "they are, without converting them"
        ),
        (
            "os resultados de futuros estão em moedas diferentes ({currencies}) e foram somados "
            "como estão, sem convertê-los"
        ),
    ),
    (
        "fewer than ten closed trades",
        "menos de dez operações fechadas",
    ),
    (
        "fewer than fifty returns",
        "menos de cinquenta retornos",
    ),
    (
        (
            "the monthly returns with 2 % a year taken month by month and 20 % of each year's "
            "gain above the previous high taken at the year's end (high-water mark)"
        ),
        (
            "as rentabilidades mensais com 2 % ao ano descontados mês a mês e 20 % do ganho de "
            "cada ano acima do máximo anterior descontados no fechamento do ano (marca d'água)"
        ),
    ),
    (
        (
            "return beyond the benchmark's moves (Jensen's alpha), annualised; cautious "
            "standard error; what the 3-month US Treasury bill paid over the same periods "
            "subtracted from both sides"
        ),
        (
            "rentabilidade além dos movimentos do benchmark (alfa de Jensen), anualizada; erro "
            "padrão prudente; subtraído dos dois lados o que a letra do Tesouro dos EUA de 3 "
            "meses pagou nos mesmos períodos"
        ),
    ),
    (
        (
            "return beyond the benchmark's moves (Jensen's alpha), annualised; cautious standard "
            "error; no cash rate subtracted"
        ),
        (
            "rentabilidade além dos movimentos do benchmark (alfa de Jensen), anualizada; erro "
            "padrão prudente; sem subtrair a taxa do caixa"
        ),
    ),
    (
        (
            "alpha over its cautious standard error (the largest of HC3, Newey-West and one "
            "widened for autocorrelated misses); beyond about 2 it is unlikely to be chance"
        ),
        (
            "alfa dividido pelo seu erro padrão prudente (o maior entre HC3, Newey-West e um "
            "ampliado por erros autocorrelacionados); acima de 2, aproximadamente, é pouco "
            "provável que seja só acaso"
        ),
    ),
    (
        (
            "average yearly return split into cash, exposure to the benchmark (beta times its "
            "return over cash) and what is left (alpha); the three add up to the fund's average"
        ),
        (
            "rentabilidade anual média dividida entre caixa, exposição ao benchmark (beta vezes o "
            "seu retorno acima do caixa) e o que sobra (alfa); as três partes somam a média do "
            "fundo"
        ),
    ),
    (
        "cash is the 3-month US Treasury bill (FRED DTB3, converted to an annual yield)",
        (
            "o caixa é a letra do Tesouro dos EUA de 3 meses (FRED DTB3, convertida em rendimento "
            "anual)"
        ),
    ),
    (
        (
            "no cash rate was available, so cash is taken as zero and the alpha also holds (1 - "
            "beta) times what cash paid"
        ),
        (
            "não havia taxa do caixa disponível, então o caixa é tomado como zero e o alfa inclui "
            "também (1 - beta) vezes o que o caixa pagou"
        ),
    ),
    (
        (
            "exposure with last month's benchmark return added (Dimson, 1979); late or smoothed "
            "prices hide part of the exposure from the plain beta"
        ),
        (
            "exposição somando o retorno do benchmark do mês anterior (Dimson, 1979); preços "
            "atrasados ou suavizados fazem o beta simples não ver parte da exposição"
        ),
    ),
    (
        (
            "squared benchmark term (Treynor and Mazuy, 1966); above zero, the fund gained more "
            "in months of big market moves than its beta explains (good timing or option-like "
            "positions), below zero less (poor timing or selling options)"
        ),
        (
            "termo do benchmark ao quadrado (Treynor e Mazuy, 1966); acima de zero, o fundo "
            "ganhou mais nos meses de mercado muito agitado do que o seu beta explica (acertar o "
            "momento ou posições com forma de opção), abaixo, menos (errar o momento ou vender "
            "opções)"
        ),
    ),
    (
        "95 % range of the yearly alpha, cautious standard error and Student's t",
        "intervalo de 95 % do alfa anual, com erro padrão prudente e t de Student",
    ),
    (
        (
            "months a record with this alpha and this noise would need before the alpha is two "
            "standard errors from zero"
        ),
        (
            "meses de que um histórico com este alfa e este ruído precisaria para o alfa ficar a "
            "dois erros padrão de zero"
        ),
    ),
    (
        "fewer than 36 months shared with the benchmark",
        "menos de 36 meses em comum com o benchmark",
    ),
    ("the alpha is not above zero", "o alfa não é maior que zero"),
    ("already two standard errors from zero", "já está a dois erros padrão de zero"),
    (
        (
            "the exposure to the benchmark is not two standard errors from zero, so the split is "
            "not shown as a share"
        ),
        (
            "a exposição ao benchmark não está a dois erros padrão de zero, então a divisão não é "
            "mostrada como proporção"
        ),
    ),
    ("beta over its cautious standard error", "beta dividido pelo seu erro padrão prudente"),
    (
        "the exposure alone is larger than the fund's whole return",
        "a exposição sozinha é maior que todo o retorno do fundo",
    ),
    (
        "the exposure took away from the fund's return rather than adding to it",
        "a exposição tirou do retorno do fundo em vez de somar",
    ),
    (
        "the benchmark's returns take too few distinct values for the regressions",
        "os retornos do benchmark têm poucos valores distintos para as regressões",
    ),
    ("the series are not on the same months", "as séries não estão nos mesmos meses"),
    (
        "the fund's average return is not above zero",
        "o retorno médio do fundo não é maior que zero",
    ),
    ("the fund moves exactly with the benchmark", "o fundo se move exatamente como o benchmark"),
    (
        "fewer than 24 periods shared with the benchmark",
        "menos de 24 períodos em comum com o benchmark",
    ),
    (
        "the strategy moves exactly with the benchmark",
        "a estratégia se move exatamente com o benchmark",
    ),
    (
        "the benchmark's returns do not vary",
        "os retornos do benchmark não variam",
    ),
    (
        "the strategy's and the benchmark's returns are not on the same dates",
        "os retornos da estratégia e os do benchmark não estão nas mesmas datas",
    ),
    (
        "fewer than two periods a year",
        "menos de dois períodos por ano",
    ),
    (
        "the autocorrelations leave no variance to scale by",
        "as autocorrelações não deixam variância para escalar",
    ),
    (
        (
            "annualised Sharpe with the autocorrelation of the returns taken into account (Lo, "
            "2002); returns that follow each other make the plain figure too high"
        ),
        (
            "Sharpe anualizado levando em conta a autocorrelação dos retornos (Lo, 2002); quando "
            "um retorno segue o anterior, o número simples fica alto demais"
        ),
    ),
    (
        (
            "probability that the true Sharpe is above zero with the returns' dependence on "
            "each other taken into account: the variance for independent returns widened by the "
            "larger of a Newey-West and a first-order autocorrelation factor, never narrowed"
        ),
        (
            "probabilidade de que o Sharpe real seja maior que zero levando em conta a "
            "dependência entre os retornos: a variância para retornos independentes ampliada "
            "pelo maior entre um fator de Newey-West e um de autocorrelação de primeira ordem, "
            "nunca reduzida"
        ),
    ),
    (
        (
            "how many times the Sharpe's variance grows when the returns are not taken as "
            "independent (1 means no change)"
        ),
        (
            "quantas vezes a variância do Sharpe cresce quando os retornos não são tomados como "
            "independentes (1 significa sem mudança)"
        ),
    ),
    (
        "returns needed for that probability to reach 0.95",
        "retornos necessários para que essa probabilidade chegue a 0,95",
    ),
    (
        "observed Sharpe <= 0; the plain probability is already below one half",
        "Sharpe observado <= 0; a probabilidade simples já fica abaixo de metade",
    ),
    (
        "the moments leave no variance to scale by",
        "os momentos não deixam variância para escalar",
    ),
    (
        (
            "return beyond the benchmark's moves (Jensen's alpha), annualised; cautious "
            "standard error; what cash in the account's currency paid subtracted from the "
            "strategy and what the 3-month US Treasury bill paid subtracted from the benchmark, "
            "taken as priced in US dollars"
        ),
        (
            "retorno além dos movimentos do benchmark (alfa de Jensen), anualizado; erro "
            "padrão prudente; subtraído da estratégia o que o caixa na moeda da conta pagou e "
            "do benchmark, tomado como cotado em dólares, o que a letra do Tesouro dos EUA de 3 "
            "meses pagou"
        ),
    ),
    (
        "first-order autocorrelation of the returns",
        "autocorrelação de primeira ordem dos retornos",
    ),
    (
        "some resamples have no losing trade; the upper end is unbounded",
        "algumas reamostragens não têm operações perdedoras; o extremo superior não tem limite",
    ),
    (
        (
            "95 % ranges, each trade taken as an independent draw: Wilson for the win rate, "
            "Student's t for the average per trade, trades resampled for the profit factor"
        ),
        (
            "faixas de 95 %, cada operação tomada como um resultado independente: Wilson para a "
            "taxa de acerto, t de Student para a média por operação e operações reamostradas "
            "para o fator de lucro"
        ),
    ),
    (
        (
            "the strategy's closes against the market's public closes (FRED) on the days both "
            "are seen (the sparser of the two calendars); Sharpe ratios on those days without "
            "subtracting a cash rate, annualised by the days observed; correlation and beta on "
            "Friday-to-Friday weekly returns"
        ),
        (
            "os fechamentos da estratégia frente aos fechamentos públicos do mercado (FRED) nos "
            "dias em que ambos aparecem (o mais escasso dos dois calendários); Sharpe nesses "
            "dias sem subtrair a taxa do caixa, anualizado pelos dias observados; correlação e "
            "beta com rentabilidades semanais de sexta a sexta"
        ),
    ),
    (
        (
            "Sharpe ratio of the returns after subtracting what the 3-month US Treasury bill "
            "paid over the same days (FRED DTB3, converted from the discount rate to an annual "
            "yield), annualised like the headline Sharpe; a dollar rate"
        ),
        (
            "Sharpe dos retornos após subtrair o que a letra do Tesouro dos EUA de 3 meses "
            "pagou nos mesmos dias (FRED DTB3, convertida de taxa de desconto para rendimento "
            "anual), anualizado como o Sharpe principal; é uma taxa em dólares"
        ),
    ),
    (
        (
            "Sharpe ratio of the returns after subtracting what cash in the account's own "
            "currency paid over the same days (the short rate FRED publishes for that currency, "
            "converted to an annual yield by its own quote), annualised like the headline Sharpe"
        ),
        (
            "Sharpe dos retornos após subtrair o que o caixa na moeda da conta pagou nos mesmos "
            "dias (a taxa de curto prazo que o FRED publica para essa moeda, convertida em "
            "rendimento anual conforme a sua cotação), anualizado como o Sharpe principal"
        ),
    ),
    (
        "the Treasury bill rates could not be read when the report was made",
        "as taxas das letras do Tesouro não puderam ser lidas ao gerar o relatório",
    ),
    (
        "the Treasury bill rates do not cover the whole history",
        "as taxas das letras do Tesouro não cobrem todo o histórico",
    ),
    (
        "the account is not in US dollars and what cash in its currency paid could not be "
        "read for the whole history",
        "a conta não está em dólares americanos e não foi possível ler o que o "
        "caixa na sua moeda pagou para todo o histórico",
    ),
    (
        "the returns never move",
        "os retornos nunca se movem",
    ),
    (
        (
            "each return placed by the VIX close of the last market day before it starts (calm "
            "below 20, turbulent at 20 or above); return per month compounded over each "
            "regime's days; Sharpe annualised like the headline Sharpe; gap in mean returns over "
            "a cautious standard error (the largest of Welch's, Newey-West's and one widened "
            "for autocorrelated returns)"
        ),
        (
            "cada retorno atribuído segundo o fechamento do VIX do último dia de mercado "
            "anterior ao seu início (tranquilo abaixo de 20, agitado a partir de 20); "
            "rentabilidade por mês composta sobre os dias de cada regime; Sharpe anualizado "
            "como o Sharpe principal; diferença de retornos médios dividida por um erro padrão "
            "prudente (o maior entre o de Welch, o de Newey-West e um ampliado por retornos "
            "autocorrelacionados)"
        ),
    ),
    (
        "the VIX closes could not be read when the report was made",
        "os fechamentos do VIX não puderam ser lidos ao gerar o relatório",
    ),
    (
        "the VIX closes do not cover the whole history",
        "os fechamentos do VIX não cobrem todo o histórico",
    ),
    (
        "the history covers fewer than 90 days",
        "o histórico cobre menos de 90 dias",
    ),
    (
        "fewer than 20 returns in calm markets (VIX below 20)",
        "menos de 20 retornos com o mercado tranquilo (VIX abaixo de 20)",
    ),
    (
        "fewer than 20 returns in turbulent markets (VIX at 20 or above)",
        "menos de 20 retornos com o mercado agitado (VIX em 20 ou mais)",
    ),
    (
        "the curve reaches zero",
        "a curva chega a zero",
    ),
    (
        (
            "the dollar levels converted at the Federal Reserve's noon buying rate of each day "
            "(FRED H.10); return a year compounded over the calendar days, shown from one year of"
            " history; worst fall from a peak in that currency; before that currency's own "
            "inflation; a USDT or USDC account is read at one dollar per coin"
        ),
        (
            "os saldos em dólares convertidos pela taxa do meio-dia do Federal Reserve de cada "
            "dia (FRED H.10); rentabilidade ao ano composta sobre os dias corridos, mostrada a "
            "partir de um ano de histórico; pior queda desde um pico nessa moeda; antes da "
            "inflação dessa moeda; uma conta em USDT ou USDC é lida a um dólar por moeda"
        ),
    ),
    (
        (
            "the dollar levels divided by US consumer prices (FRED CPIAUCNS) of each point's "
            "month, or the latest month published; US inflation only"
        ),
        (
            "os saldos em dólares divididos pelos preços ao consumidor dos EUA (FRED CPIAUCNS) do"
            " mês de cada ponto, ou do último mês publicado; só inflação dos EUA"
        ),
    ),
    (
        "no currency is named in the file, so the curve is read as US dollars",
        "o arquivo não nomeia a moeda, então a curva é lida em dólares dos EUA",
    ),
    (
        "the account is not in US dollars",
        "a conta não está em dólares dos EUA",
    ),
    (
        "the exchange rates could not be read when the report was made",
        "as cotações não puderam ser lidas ao gerar o relatório",
    ),
    (
        "US consumer prices could not be read when the report was made",
        "os preços ao consumidor dos EUA não puderam ser lidos ao gerar o relatório",
    ),
    (
        "US consumer prices do not cover the whole history",
        "os preços ao consumidor dos EUA não cobrem todo o histórico",
    ),
    (
        (
            "the levels in that currency divided by that country's official consumer price index "
            "of each point's month, or the latest month published"
        ),
        (
            "os saldos nessa moeda divididos pelo índice oficial de preços ao consumidor desse "
            "país do mês de cada ponto, ou do último mês publicado"
        ),
    ),
    (
        (
            "the account's own levels in its currency; return a year compounded over the "
            "calendar days, shown from one year of history; worst fall from a peak"
        ),
        (
            "os saldos da conta na sua própria moeda; rentabilidade ao ano composta sobre os "
            "dias corridos, mostrada a partir de um ano de histórico; pior queda desde um pico"
        ),
    ),
    (
        "the consumer prices of the account's currency could not be read when the report was made",
        "os preços ao consumidor da moeda da conta não puderam ser lidos ao gerar o relatório",
    ),
    (
        "the consumer prices of the account's currency do not cover the whole history",
        "os preços ao consumidor da moeda da conta não cobrem todo o histórico",
    ),
    (
        "the strategy's compound return a year",
        "a rentabilidade composta anual da estratégia",
    ),
    (
        "fewer than 12 weeks shared with the market's public closes",
        "menos de 12 semanas em comum com os fechamentos públicos do mercado",
    ),
    (
        "no overlapping days",
        "nenhum dia em comum",
    ),
    (
        "the market's public closes could not be read when the report was made",
        "os fechamentos públicos do mercado não puderam ser lidos ao gerar o relatório",
    ),
    (
        "fewer than 60 days shared with the market's public closes",
        "menos de 60 dias em comum com os fechamentos públicos do mercado",
    ),
    (
        "the shared days span less than 90 calendar days",
        "os dias em comum cobrem menos de 90 dias corridos",
    ),
    (
        "one of the two series never moves",
        "uma das duas séries nunca se move",
    ),
    (
        (
            "the uploaded returns in random order: the same Sharpe, volatility and final result, "
            "only the order changes"
        ),
        (
            "os retornos enviados em ordem aleatória: o mesmo Sharpe, a mesma volatilidade e o "
            "mesmo resultado final, só a ordem muda"
        ),
    ),
    (
        "deepest fall of the uploaded order",
        "pior queda na ordem enviada",
    ),
    (
        "too few losing periods for their order to matter",
        "poucos períodos com perda para que a ordem importe",
    ),
    (
        "no losing period; the drawdown is zero in any order",
        "nenhum período com perda; a queda é zero em qualquer ordem",
    ),
    (
        "Resampled estimate from the supplied history: it is not a prediction.",
        "Estimativa reamostrada do histórico fornecido: não é uma previsão.",
    ),
    (
        "It assumes the future resembles the history; if the market changes, it no longer holds.",
        (
            "Supõe que o futuro se parece com o histórico; se o mercado mudar, a estimativa "
            "deixa de valer."
        ),
    ),
    (
        "A curve of daily closes does not show floating drawdown within the day.",
        "Uma curva de fechamentos diários não mostra o drawdown flutuante dentro do dia.",
    ),
    (
        "Resampled estimate from the supplied history: it is not a prediction.",
        "Estimativa reamostrada do histórico fornecido: não é uma previsão.",
    ),
    (
        (
            "Daily data cannot see intraday floating drawdown, so the estimate is optimistic "
            "against the daily and total limits."
        ),
        (
            "Com dados diários não se vê o drawdown flutuante intradiário, então a estimativa é "
            "otimista frente aos limites diários e totais."
        ),
    ),
    (
        (
            "It assumes the future resembles the history and that every day with a non-zero "
            "return counts as a trading day."
        ),
        (
            "Supõe que o futuro se parece com o histórico e que cada dia com retorno diferente "
            "de zero conta como dia operado."
        ),
    ),
    (
        "The firm's rules are those posted on the date shown; they may have changed.",
        "As regras da mesa são as publicadas na data indicada; podem ter mudado.",
    ),
    (
        (
            "Is this the only account running this strategy? Ask for the accounts that were "
            "closed or restarted too: showing only the one that went well is common."
        ),
        (
            "Esta é a única conta com esta estratégia? Peça também as contas que foram "
            "encerradas ou reiniciadas: mostrar só a que deu certo é comum."
        ),
    ),
    (
        (
            "Ask for the backtest of the same robot with the same settings: uploaded together "
            "with this account, the report compares the two trade by trade."
        ),
        (
            "Peça o backtest do mesmo robô com a mesma configuração: enviado junto com esta "
            "conta, o relatório compara os dois operação por operação."
        ),
    ),
    (
        (
            "Is there a live or demo account with at least {months} months of auditable history, "
            "with the same robot and settings?"
        ),
        (
            "Existe uma conta real ou demo com pelo menos {months} meses de histórico auditável "
            "com o mesmo robô e a mesma configuração?"
        ),
    ),
    (
        (
            "Is there a live or demo account with auditable history, with the same robot and "
            "settings? With a Sharpe like this one it would take about {months} months to tell "
            "it apart from chance: the longer the history, the better."
        ),
        (
            "Existe uma conta real ou demo com histórico auditável do mesmo robô e da mesma "
            "configuração? Com um Sharpe como este seriam necessários uns {months} meses para "
            "distingui-lo do acaso: quanto mais longo o histórico, melhor."
        ),
    ),
    (
        (
            "Which modelling mode and history quality was the backtest run with (real ticks, "
            "1-minute OHLC, open prices only)?"
        ),
        (
            "Com qual modo de modelagem e qualidade de histórico o backtest foi feito (ticks "
            "reais, OHLC de 1 minuto, somente preços de abertura)?"
        ),
    ),
    (
        (
            "What happened in the best trade (date, size, price), and what result does the "
            "system leave without it?"
        ),
        (
            "O que aconteceu na melhor operação (data, tamanho, preço) e que resultado o sistema "
            "deixa sem ela?"
        ),
    ),
    (
        (
            "What changed in the last stretch of the history, where the trades stop adding up? "
            "Was the system reoptimised afterwards?"
        ),
        (
            "O que mudou no último trecho do histórico, em que as operações deixam de somar? O "
            "sistema foi reotimizado depois?"
        ),
    ),
    (
        (
            "The average per trade in the last stretch is under half the earlier one: did "
            "anything change in the system or the market over that time?"
        ),
        (
            "A média por operação do último trecho é menos da metade da anterior: mudou algo no "
            "sistema ou no mercado nesse tempo?"
        ),
    ),
    (
        (
            "Almost all of the result comes from one instrument: was the system designed for it? "
            "What did it do on the others?"
        ),
        (
            "Quase todo o resultado vem de um único instrumento: o sistema foi projetado para "
            "ele? Que resultado deu nos demais?"
        ),
    ),
    (
        "Losing trades last longer than winners: how does the system decide to close a loss?",
        (
            "As operações perdedoras duram mais que as ganhadoras: como o sistema decide fechar "
            "uma perda?"
        ),
    ),
    (
        (
            "What does the system do after several losses in a row: change size, pause, or enter "
            "again straight away?"
        ),
        (
            "O que o sistema faz depois de várias perdas seguidas: muda o tamanho, faz uma pausa "
            "ou volta a entrar logo em seguida?"
        ),
    ),
    (
        (
            "Can you send the original file MetaTrader exported, unedited, with the header and "
            "the full list of trades?"
        ),
        (
            "Você pode enviar o arquivo original que o MetaTrader exportou, sem edição, com o "
            "cabeçalho e a lista completa de operações?"
        ),
    ),
    (
        (
            "How many parameter combinations were tried before choosing this one? Ask for the "
            "optimisation file."
        ),
        (
            "Quantas combinações de parâmetros foram testadas antes de escolher esta? Peça o "
            "arquivo de otimização."
        ),
    ),
    (
        "Which period was left out of the optimisation, and how did it behave there?",
        "Qual período ficou fora da otimização e como se comportou nele?",
    ),
    (
        "Which spread, commission and swap were used? Are they your broker's?",
        "Quais spread, comissão e swap foram usados? São os da sua corretora?",
    ),
    (
        (
            "Ask for the (floating) equity curve, not only the balance: the balance hides open "
            "losses."
        ),
        (
            "Peça a curva de patrimônio (flutuante), não só a de saldo: o saldo esconde as "
            "perdas abertas."
        ),
    ),
    (
        "Ask for the full list of closed trades with sizes, prices and dates.",
        "Peça a lista completa de operações fechadas com tamanhos, preços e datas.",
    ),
    (
        "Does the robot increase size after a loss? What is the largest size it can open?",
        (
            "O robô aumenta o tamanho depois de uma perda? Qual é o tamanho máximo que ele pode "
            "chegar a abrir?"
        ),
    ),
    (
        "Does the robot add positions against the move when price moves away? How many at most?",
        (
            "O robô abre posições adicionais contra o movimento quando o preço se afasta? "
            "Quantas no máximo?"
        ),
    ),
    (
        "Does every trade have a fixed stop loss? What was the largest open loss recorded?",
        "Cada operação tem um stop loss fixo? Qual foi a maior perda aberta registrada?",
    ),
    (
        (
            "Most trades win a little and a few lose a lot: what prevents a loss larger than "
            "those in the history?"
        ),
        (
            "A maioria das operações ganha pouco e algumas perdem muito: o que evita uma perda "
            "maior que as do histórico?"
        ),
    ),
    (
        (
            "Ask for the full history with every deposit and withdrawal: how much money was "
            "deposited in total, when, and how much was withdrawn?"
        ),
        (
            "Peça o histórico completo com cada depósito e saque: quanto dinheiro foi depositado "
            "no total, quando, e quanto foi sacado?"
        ),
    ),
    (
        "Which positions are still open, since when, and with what floating loss?",
        "Quais posições continuam abertas, desde quando e com qual perda flutuante?",
    ),
    (
        (
            "The history has jumps, gaps or repeated values: where does the data come from and "
            "how was it cleaned?"
        ),
        (
            "O histórico tem saltos, lacunas ou valores repetidos: de onde vêm os dados e como "
            "foram limpos?"
        ),
    ),
    (
        "Fixed sizes: no compounding and no size change after wins or losses.",
        "Tamanhos fixos: sem juros compostos nem mudanças de tamanho após ganhar ou perder.",
    ),
    (
        "Trades are drawn independently of one another; the history's own fall covers streaks.",
        (
            "As operações são sorteadas de forma independente; a queda do próprio histórico "
            "cobre as sequências."
        ),
    ),
    (
        "Costs are those the uploaded file itemises.",
        "Os custos são os que o arquivo enviado detalha.",
    ),
    (
        (
            "Money figures are at the sizes the file used; the relative size is computed on its "
            "starting balance, without later deposits."
        ),
        (
            "Os valores em dinheiro correspondem ao tamanho que o arquivo usou; o tamanho "
            "relativo é calculado sobre o seu saldo inicial, sem somar depósitos posteriores."
        ),
    ),
    (
        "It measures the history's losses; it is not a forecast.",
        "Mede as perdas do histórico; não é uma previsão.",
    ),
)

#: (English template, Portuguese) for the verdict's reasons, one "; "-separated part
#: at a time, most specific first; the trial phrase they embed comes first.
REASONS: tuple[tuple[str, str], ...] = (
    (
        "1 declared trial",
        "1 tentativa declarada",
    ),
    (
        "{n} declared trials",
        "{n} tentativas declaradas",
    ),
    (
        "1 trial counted in the files",
        "1 tentativa contada nos arquivos",
    ),
    (
        "{n} trials counted in the files",
        "{n} tentativas contadas nos arquivos",
    ),
    (
        "1 trial not declared (the most favourable case)",
        "1 tentativa não declarada (o caso mais favorável)",
    ),
    (
        "{n} trials not declared (the most favourable case)",
        "{n} tentativas não declaradas (o caso mais favorável)",
    ),
    (
        "fewer than three returns",
        "menos de três retornos",
    ),
    (
        "zero variance",
        "variância zero",
    ),
    (
        "PSR not computed",
        "PSR não calculado",
    ),
    (
        "statistical significance not measured",
        "significância estatística não medida",
    ),
    (
        "no trades uploaded; costs cannot be re-applied",
        "nenhuma operação enviada; não é possível reaplicar os custos",
    ),
    (
        "no trades uploaded",
        "nenhuma operação enviada",
    ),
    (
        "costs cannot be re-applied",
        "não é possível reaplicar os custos",
    ),
    (
        "cost rows missing",
        "faltam linhas de custos",
    ),
    (
        "no out-of-sample start declared",
        "não foi declarado um início fora da amostra",
    ),
    (
        "declared out-of-sample start lies outside the uploaded series",
        "o início fora da amostra declarado cai fora da série enviada",
    ),
    (
        "out-of-sample window not evaluated",
        "trecho fora da amostra não avaliado",
    ),
    (
        "no benchmark uploaded",
        "nenhum benchmark enviado",
    ),
    (
        "client declared no applicable benchmark",
        "o cliente declarou que não se aplica benchmark",
    ),
    (
        "no red flags",
        "sem sinais de alerta",
    ),
    (
        "bootstrap p5 Sharpe > 0",
        "Sharpe p5 do bootstrap > 0",
    ),
    (
        "bootstrap p5 Sharpe <= 0",
        "Sharpe p5 do bootstrap <= 0",
    ),
    (
        "drawdown deeper than the benchmark",
        "drawdown mais profundo que o do benchmark",
    ),
    (
        "information ratio <= 0",
        "information ratio <= 0",
    ),
    (
        "a side has fewer than {a} returns (in-sample {b}, out-of-sample {c})",
        "um dos trechos tem menos de {a} retornos (dentro da amostra {b}, fora da amostra {c})",
    ),
    (
        "benchmark overlaps only {a} of the strategy timestamps",
        "o benchmark só coincide com {a} das datas da estratégia",
    ),
    (
        "split failed: {a}",
        "não foi possível dividir a série: {a}",
    ),
    (
        "DSR {a} between {b} and {c} with {d}",
        "DSR {a} entre {b} e {c} com {d}",
    ),
    (
        "DSR {a} >= {b} with {c}",
        "DSR {a} >= {b} com {c}",
    ),
    (
        "DSR {a} < {b} with {c}",
        "DSR {a} < {b} com {c}",
    ),
    (
        "PBO {a} >= {b}",
        "PBO {a} >= {b}",
    ),
    (
        "PBO {a} < {b}",
        "PBO {a} < {b}",
    ),
    (
        "net pnl at {a} is {b} > 0 but at {c} is {d} <= 0",
        "o resultado líquido a {a} é {b} > 0, mas a {c} é {d} <= 0",
    ),
    (
        "net pnl at {a} the reference cost is {b} <= 0",
        "o resultado líquido a {a} o custo de referência é {b} <= 0",
    ),
    (
        "net pnl at {a} the reference cost is {b} > 0",
        "o resultado líquido a {a} o custo de referência é {b} > 0",
    ),
    (
        "in-sample minus out-of-sample gap {a} <= {b}",
        "diferença entre dentro e fora da amostra {a} <= {b}",
    ),
    (
        "out-of-sample Sharpe {a} >= {b}",
        "Sharpe fora da amostra {a} >= {b}",
    ),
    (
        "out-of-sample Sharpe {a} <= 0",
        "Sharpe fora da amostra {a} <= 0",
    ),
    (
        "out-of-sample Sharpe {a} > 0",
        "Sharpe fora da amostra {a} > 0",
    ),
    (
        "excess return {a} <= 0",
        "retorno em excesso {a} <= 0",
    ),
    (
        "excess return {a} > 0",
        "retorno em excesso {a} > 0",
    ),
    (
        "drawdown ratio {a} <= {b}",
        "razão de drawdown {a} <= {b}",
    ),
    (
        "information ratio {a} > 0",
        "information ratio {a} > 0",
    ),
    (
        "PSR {a} >= {b}",
        "PSR {a} >= {b}",
    ),
    (
        "PSR {a} < {b}",
        "PSR {a} < {b}",
    ),
    (
        "PSR {a}",
        "PSR {a}",
    ),
    (
        "gap {a}",
        "diferença {a}",
    ),
)

__all__ = [
    "CHARTS",
    "COMPARED",
    "INITIAL_SOURCES",
    "NOT_MEASURED",
    "PLAN",
    "PREFIXES",
    "REASONS",
    "REASON_LEADS",
    "REDFLAGS",
    "REPORT",
    "RULES",
    "SINGULAR",
    "TRIAL_SOURCES",
    "VERDICT",
    "install",
]
