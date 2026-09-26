"""Portuguese (Brazil and Portugal) words for the public pages.

The landing, its prices and its questions exist in Portuguese at ``/pt``.
Pages that are not translated yet (the terms, the privacy policy, the
public verification page) open in English from a Portuguese page, so a visitor
never meets a broken or half-Spanish page. The copy keeps the same honest
limits as the Spanish and English versions and passes the profit-claim
guard, which reads Portuguese too.
"""

from __future__ import annotations

from typing import Any

from quant_trade.audit.accounts import FREE_PREVIEWS_PER_MONTH as _FREE
from quant_trade.audit.audiences import PLATFORMS_PT
from quant_trade.audit.redflags import FLAG_TITLES
from quant_trade.audit.seo import BRAND

#: The language names shown in the language switch, each in its own language.
LANGUAGE_NAMES: dict[str, str] = {"es": "Español", "en": "English", "pt": "Português"}

#: The language a Portuguese page links to for a page not yet in Portuguese.
FALLBACK = "en"


def link_locale(locale: str) -> str:
    """The language of a linked page that may not exist in ``locale`` yet."""
    return FALLBACK if locale == "pt" else locale


COPY_PT: dict[str, Any] = {
    "title": f"{BRAND} · Auditoria de backtests",
    "headline": "Envie seu backtest. Dizemos se ele é estatisticamente real.",
    "pitch": (
        "A maioria dos backtests que parecem bons no papel falha na conta real por "
        "sobreajuste, custos não contados ou dados com erros. Esta auditoria aplica os "
        "estimadores de Bailey e López de Prado (Sharpe probabilístico, Sharpe deflacionado "
        "pelo número de tentativas, bootstrap estacionário) à curva que você envia e devolve "
        "um veredito com cada número etiquetado segundo a sua evidência."
    ),
    "measure_title": "O que medimos",
    "measure": [
        "Se o Sharpe se distingue de zero, dado o tamanho, a assimetria e a curtose.",
        "Quanto sobrevive depois de descontar o número de tentativas que você declara.",
        "O que acontece com 1x, 2x e 3x o custo de operação, e o custo de equilíbrio.",
        "Se o trecho fora da amostra que você declara se sustenta.",
        f"{len(FLAG_TITLES)} bandeiras vermelhas: dados duplicados, picos, preços congelados "
        "e mais.",
        "Comparação com o benchmark que você enviar, se enviar um.",
    ],
    "not_title": "O que não fazemos",
    "not": (
        "Não executamos operações, não guardamos fundos nem chaves, não recomendamos "
        "estratégias e não prevemos resultados. Auditamos o arquivo que você envia."
    ),
    "form_title": "Pedir uma auditoria",
    "report": "Relatório da sua plataforma (recomendado)",
    "report_short": "Do jeito que a sua plataforma salva: HTML, XLSX ou CSV, até 10 MB.",
    "report_help": (
        "O arquivo como está: relatório HTML do testador ou do histórico do MetaTrader 5 ou 4 "
        "(ou o XLSX que o MetaTrader 5 exporta), a lista de operações do TradingView (CSV ou "
        "XLSX), o CSV de operações do NinjaTrader, QuantConnect, backtesting.py ou vectorbt, ou "
        "o histórico de operações em CSV ou Excel de qualquer outra corretora ou exchange. "
        "Reconhece o formato de exportação de " + PLATFORMS_PT + ". Até 10 MB."
    ),
    "live": "Extrato da conta real ou demo (opcional)",
    "live_help": (
        "O histórico da conta onde o robô roda (MetaTrader, o CSV que o Myfxbook, o FX Blue "
        "ou um sinal da MQL5 exportam, ou outro dos formatos acima). Dizemos se ela se "
        "comporta como o backtest e revisamos os depósitos e saques."
    ),
    "optimization": "Exportação de otimização do MT5 (XML, opcional)",
    "optimization_help": (
        "Conta as configurações que você testou: o Sharpe deflacionado usa esse número real."
    ),
    "equity": (
        "Curva de equity ou série de retornos (CSV ou Excel; obrigatória se você não enviar um "
        "relatório)"
    ),
    "equity_help": (
        "Colunas: timestamp e equity (ou return), em CSV, texto do Excel ou XLSX. Também a "
        "tabela de rentabilidades mensais de um fundo (um ano por linha, um mês por coluna). "
        "Até 5 MB."
    ),
    "initial_balance": "Saldo inicial (se o relatório não informar)",
    "challenge": "Desafio de prop firm para simular",
    "challenge_help": "Regras lidas no site oficial de cada firma em {as_of}. "
    "O relatório cita a fonte; confirme as regras com a firma antes de pagar o desafio.",
    "trades": "Operações fechadas (CSV, opcional)",
    "trades_help": "entry_time, exit_time, quantity, entry_price, exit_price, side.",
    "benchmark": "Benchmark (CSV, opcional)",
    "variants": "Matriz de variantes (CSV, opcional)",
    "variants_help": "Uma coluna de retornos por variante testada; habilita o PBO.",
    "trials": "Configurações testadas antes de escolher esta (vazio = não declarado)",
    "cost_bps": (
        "Custo extra por lado em pontos-base, além do que o seu relatório já detalha (vazio = 0)"
    ),
    "oos_start": "Início do trecho fora da amostra (opcional)",
    "net_of_fees": (
        "São rentabilidades de um fundo, já líquidas das suas taxas (só histórico mensal)"
    ),
    "benchmark_applicable": "Um benchmark se aplica?",
    "yes": "Sim",
    "no": "Não",
    "locale": "Idioma do relatório",
    "locale_note": "O relatório sai em português, espanhol ou inglês.",
    "description": "Descrição (opcional, não aparece no relatório)",
    "consent": (
        "Entendo que isto é uma ferramenta de pesquisa estatística, não uma recomendação de "
        "investimento, e que o arquivo é apagado após {retention} dias se não for pago. "
        "Aceito os termos do serviço e a política de privacidade."
    ),
    "consent_read": "Leia antes de enviar (em inglês):",
    "terms_link": "Termos do serviço",
    "privacy_link": "Política de privacidade",
    "legal_updated": "Última atualização",
    "submit": "Auditar",
    "free_note": "Modo gratuito: o relatório completo é entregue com marca d'água.",
    "paid_note": (
        "Com a sua conta, o primeiro relatório completo é grátis; depois, prévias grátis e o "
        "relatório completo por USD {price:.0f}."
    ),
    "signin_first": (
        "Antes de enviar, crie a sua conta grátis: o seu primeiro relatório sai completo, com "
        "PDF, sem pagar. Se você comprou um código, pode enviar sem conta."
    ),
    "signin_create": "Criar conta grátis",
    "signin_enter": "Já tenho conta",
    "waitlist_title": "Avise-me quando houver novidades",
    "email": "E-mail",
    "join": "Quero receber",
    "joined": "Inscrito. Obrigado.",
    "error_title": "Não foi possível auditar",
    "back": "Voltar",
    "disclaimer": "Aviso",
    "sample_link": "Ver um relatório de exemplo completo (dados sintéticos)",
    "meta_description": (
        "Auditoria estatística de backtests e históricos de trading para forex, ações, futuros "
        "e cripto. Envie o relatório do MetaTrader, TradingView, NinjaTrader, Python ou a sua "
        "curva de equity e receba um veredito de A a D, com cada número etiquetado segundo a "
        "sua evidência."
    ),
    "sample_description": (
        "Relatório completo de exemplo da auditoria de backtests, feito com dados sintéticos: "
        "veredito, gráficos, risco reamostrado e simulação de desafio."
    ),
    "guides_title": "Qual arquivo enviar",
    "guides_text": (
        "Envie o arquivo que a sua plataforma já salva. Se não souber qual exportar, há um guia "
        "curto para cada uma."
    ),
    "guides_link": "Ver os guias de exportação",
    "guide_q": "Qual arquivo eu exporto?",
    "map_title": "A sua plataforma não aparece ou o arquivo dá erro? Indique as colunas",
    "map_help": (
        "Só para uma lista em CSV ou Excel. Escreva o nome exato de cada coluna como aparece na "
        "primeira linha do arquivo; ao escolher o arquivo sugerimos os nomes. Com uma linha por "
        "operação: entrada, saída, quantidade e preços. Com uma linha por execução: hora, lado, "
        "quantidade e preço. O que ficar vazio é reconhecido sozinho."
    ),
    "map_groups": (
        ("Uma linha por operação", ("entry_time", "exit_time", "entry_price", "exit_price")),
        ("Uma linha por execução", ("time", "price")),
        ("Nos dois casos", ("side", "quantity", "symbol", "profit", "commission", "multiplier")),
    ),
    "map_found": "Colunas do seu arquivo:",
    "or_word": "ou",
    "map_roles": {
        "entry_time": "Data e hora de entrada",
        "exit_time": "Data e hora de saída",
        "entry_price": "Preço de entrada",
        "exit_price": "Preço de saída",
        "time": "Data e hora da execução",
        "price": "Preço da execução",
        "side": "Lado (compra ou venda)",
        "quantity": "Quantidade",
        "symbol": "Símbolo",
        "profit": "Resultado da operação",
        "commission": "Comissão",
        "multiplier": "Multiplicador do contrato",
    },
    "guide_list": "Guia para",
    "optimization_guide": "Como exportar o XML de otimização",
    "v_description": "{cls_label} {overall} · auditada em {date} · {notice}.",
    "how_title": "Como funciona",
    "how": [
        "Envie o arquivo da sua plataforma como está: um backtest, o histórico de uma conta ou "
        "uma série de retornos.",
        "Em segundos você vê, de graça, a classe de A a D, os gráficos, as bandeiras vermelhas "
        "e o que cada dimensão significa em linguagem simples.",
        "Se quiser todos os números, desbloqueia o relatório completo na mesma página e o "
        "guarda em PDF.",
        "Se quiser, publique uma página de verificação com selo para compartilhar.",
    ],
    "prices_title": "Preços",
    "price_free_title": "Prévia",
    "price_free": (
        "Classe de A a D, explicação de cada dimensão, gráficos, bandeiras vermelhas e hashes."
    ),
    "price_full_title": "Relatório completo",
    "price_full": (
        "Todo o detalhe numérico sem marca d'água, simulador de desafio, risco reamostrado, "
        "perguntas para o vendedor e página pública de verificação com selo."
    ),
    "price_free_mode": (
        "Neste momento o serviço está em modo gratuito: o relatório completo é entregue com "
        "marca d'água e sem custo."
    ),
    "pay_card": (
        "Pagamento com cartão no próprio relatório, processado pela Stripe: você o vê completo "
        "na hora, sem esperar um código."
    ),
    "pay_code": (
        "Pagamento por transferência ou outro meio que combinamos pelo WhatsApp: quando o "
        "pagamento é confirmado, enviamos um código de acesso e você o escreve no formulário "
        "ou no relatório."
    ),
    "contact": "Pedir um código",
    "price_pack": "Pacote de {n} relatórios: USD {price:.0f} (USD {each:.0f} cada um).",
    "refund_note": (
        "Se o relatório ler mal o seu arquivo (operações, saldo ou datas que não batem com a "
        "sua plataforma) e não conseguirmos corrigir, devolvemos o valor desse relatório."
    ),
    "account_note": (
        "O seu primeiro relatório completo, grátis ao criar a sua conta; depois, "
        f"{_FREE} prévias grátis por mês, e os seus relatórios e créditos num só lugar."
    ),
    "account_link": "Criar conta",
    "faq_title": "Perguntas frequentes",
    "faq": [
        (
            "Qual arquivo eu envio?",
            "O relatório da sua plataforma como está: MetaTrader 5 ou 4 (HTML), TradingView "
            "(CSV ou XLSX), NinjaTrader, QuantConnect, backtesting.py ou vectorbt. Para revisar "
            "a conta de outro trader, o histórico em CSV que o Myfxbook, o FX Blue ou um sinal "
            "da MQL5 exportam. Da sua corretora, exchange ou diário, o histórico de operações em "
            "CSV ou Excel: reconhece o formato de exportação de " + PLATFORMS_PT + ", e em "
            "qualquer outro as colunas são reconhecidas pelo nome. Uma curva de equity em CSV "
            "também serve.",
        ),
        (
            "Serve para ações, cripto, futuros ou um fundo?",
            "Sim. O Rigor não depende do mercado: mede o histórico que você envia. Para uma "
            "carteira de ações ou cripto, ou para um fundo ou um gestor, envie a curva de equity "
            "ou a série de retornos (diária, semanal ou mensal) em CSV ou Excel; de um fundo "
            "serve também a tabela de rentabilidades mensais da lâmina. Os relatórios do "
            "TradingView, NinjaTrader, QuantConnect, backtesting.py e vectorbt servem para "
            "qualquer ativo.",
        ),
        (
            "O que eu recebo e quanto demora?",
            "Em segundos, a prévia gratuita: classe de A a D, gráficos, bandeiras vermelhas e o "
            "que cada dimensão significa. O relatório completo acrescenta cada número, testes de "
            "estresse, risco e capital, simulador de desafios, a conta real frente ao backtest "
            "se você a enviar, perguntas para o vendedor e o PDF. Veja o exemplo completo antes "
            "de pagar.",
        ),
        (
            "Em que idioma sai o relatório?",
            "Por enquanto, em inglês ou espanhol, à sua escolha no formulário. O site já está em "
            "português; o relatório e o PDF em português vêm em seguida.",
        ),
        (
            "Por que enviar o XML de otimização do MT5?",
            "Porque ele conta as configurações que você testou. Com esse número real, o Sharpe "
            "deflacionado desconta a sorte de ter escolhido a melhor entre muitas.",
        ),
        (
            "O que significam MEASURED, DECLARED e NOT_MEASURED?",
            "MEASURED foi calculado a partir do seu arquivo; DECLARED foi informado por você e "
            "não pôde ser conferido; NOT_MEASURED não pôde ser calculado com o que você enviou.",
        ),
        (
            "Isto prevê resultados ou o desfecho de um desafio de prop firm?",
            "Não. Mede a evidência estatística do arquivo que você envia. O simulador de "
            "desafios e o risco reamostrado são estimativas sobre o seu próprio histórico, com "
            "as suposições escritas, não previsões.",
        ),
        (
            "Vocês conferem as minhas operações com a corretora?",
            "Não. Auditamos os dados que você fornece; não nos conectamos a nenhuma corretora "
            "nem pedimos chaves. Por isso o selo diz que os dados não foram conferidos com a "
            "corretora.",
        ),
        (
            "O que acontece com o meu arquivo?",
            "Fica guardado para poder gerar o seu relatório de novo. Se você não pagar, é "
            "apagado após {retention} dias e só ficam a classe e os hashes. Nunca é publicado: a "
            "página de verificação mostra a classe, as dimensões e os hashes, e só se você a "
            "publicar.",
        ),
        (
            "E se eu esquecer minha senha?",
            "Em Minha conta você cria uma chave de recuperação e a guarda. Se esquecer a senha, "
            "com seu e-mail e essa chave você mesmo cria uma nova, sem esperar um e-mail. "
            "Se você ativou a verificação em duas etapas, também pedimos o código do seu "
            "app. Da chave, só guardamos a impressão, nunca a chave em si.",
        ),
        (
            "Como se usa o selo?",
            "Publique a verificação a partir do seu relatório e copie o código do selo no seu "
            "site, Telegram ou fórum. O selo descreve uma auditoria estatística; não é uma "
            "promessa de resultados e não deve ser apresentado como tal.",
        ),
    ],
    "v_title": "Verificação pública de auditoria",
    "v_class": "Classe",
    "v_audited": "Data da auditoria",
    "v_published": "Publicada",
    "v_dimensions": "Dimensões",
    "v_dimension": "Dimensão",
    "v_status": "Resultado",
    "v_meaning": "O que significa",
    "v_inputs": "Hashes dos arquivos auditados (SHA-256)",
    "v_details": "Dados da auditoria",
    "v_format": "Formato do arquivo",
    "v_engine": "Motor",
    "v_trials_declared": "Tentativas declaradas",
    "v_trials_used": "Tentativas usadas no Sharpe deflacionado",
    "v_result_sha": "SHA-256 do resultado",
    "v_notice": "Aviso",
    "v_badge": "Selo para o seu site",
    "v_badge_help": "Copie este código no seu site, Telegram ou fórum:",
    "access_code": "Código de acesso (opcional)",
    "access_code_help": "Se você comprou um código, escreva-o e o relatório já nasce completo.",
}

UI_PT: dict[str, Any] = {
    "skip": "Pular para o conteúdo",
    "nav_how": "Como funciona",
    "nav_sample": "Exemplo",
    "footer_sample_pdf": "Exemplo em PDF",
    "footer_check": "Conferir um relatório",
    "v_check": "Recebeu o PDF ou o JSON deste relatório? Confira que não foi editado.",
    "v_check_link": "Conferir um arquivo",
    "nav_pricing": "Preços",
    "nav_guides": "Guias",
    "nav_faq": "Perguntas",
    "nav_account": "Minha conta",
    "nav_compare": "Comparar",
    "nav_menu": "Menu",
    "cta": "Começar grátis",
    "cta_full": "Comece com a prévia grátis",
    "cta_short": "Auditar",
    "hero_a": "Envie seu backtest ou seu histórico.",
    "hero_b": "Dizemos se é evidência ou sorte.",
    "trust": [
        ("shield", "Sem conexão com a sua corretora"),
        ("hash", "Impressão SHA-256 de cada arquivo"),
        ("globe", "Relatório em português, inglês ou espanhol"),
        ("key", "Primeiro relatório completo grátis com a sua conta"),
    ],
    "mock_url": "relatório · classe B",
    "mock_k": "Veredito",
    "cta_sample": "Ver um relatório de exemplo",
    "hero_lead": (
        "Para traders de qualquer mercado, quem compra um robô, quem vai fazer um desafio de "
        "prop firm e quem investe com um gestor. Envie o arquivo que você já tem e receba em "
        "segundos um veredito de A a D sobre sobreajuste, custos, fora da amostra e qualidade "
        "dos dados, com cada número etiquetado segundo a sua evidência."
    ),
    "mock_cap": "Ilustração com dados sintéticos",
    "mock_is": "Dentro da amostra",
    "mock_oos": "Fora da amostra",
    "mock_kpis": [
        ("0,41", "Sharpe deflacionado"),
        ("120", "Tentativas contadas"),
        ("3,2 pb", "Custo de equilíbrio"),
    ],
    "chip_trials": "Tentativas reais a partir do XML do MT5",
    "chip_hash": "Cada número com a sua evidência",
    "platforms": "Lê o arquivo que você já tem",
    "platforms_also": "E reconhece o formato de exportação de",
    "problem_eyebrow": "O problema",
    "problem_title": ("Um backtest bonito", "não é evidência."),
    "problem_lead": (
        "Quase qualquer estratégia fica bonita no papel. Estes são os três motivos pelos quais "
        "a maioria não se sustenta fora do testador."
    ),
    "problems": [
        (
            "Sobreajuste",
            "Você testa cem configurações e fica com a melhor. O acaso, sozinho, já desenha uma "
            "curva linda.",
        ),
        (
            "Custos",
            "Comissão, spread e slippage comem as vantagens pequenas. Muitos backtests os "
            "contam como zero.",
        ),
        (
            "Dados",
            "Barras duplicadas, preços congelados ou buracos inflam o resultado sem que ninguém "
            "perceba.",
        ),
    ],
    "dims_eyebrow": "O que medimos",
    "dims_title": ("Seis dimensões.", "Um veredito de A a D."),
    "dims_lead": (
        "Cada dimensão sai como Passa, Fraca, Não passa ou Não medida, com duas frases em "
        "linguagem simples sobre o que significa para você."
    ),
    "stats": [
        ("6", "dimensões auditadas"),
        ("{flags}", "bandeiras vermelhas revisadas em cada arquivo"),
        ("{presets}", "desafios de prop firms para simular"),
        ("{platforms}", "plataformas que reconhece"),
    ],
    "evidence_eyebrow": "Evidência",
    "evidence_title": ("Cada número diz", "de onde vem."),
    "evidence_lead": (
        "A diferença entre uma opinião e uma auditoria. Nunca apresentamos o que você declara "
        "como se tivéssemos medido."
    ),
    "evidence": [
        ("MEASURED", "Nós calculamos a partir do seu arquivo."),
        ("DECLARED", "Você ou a sua plataforma informou; não podemos conferir."),
        ("NOT_MEASURED", "Faltaram dados para medir, e dizemos quais."),
    ],
    "diff_eyebrow": "Por que é diferente",
    "diff_title": ("Feita para quem", "vai arriscar o próprio dinheiro."),
    "diffs": [
        (
            "layers",
            "Tentativas reais",
            "Com o XML de otimização do MT5 contamos as configurações que você testou, e o "
            "Sharpe deflacionado usa esse número, não um suposto.",
        ),
        (
            "hash",
            "Evidência por impressão digital",
            "Cada arquivo auditado fica identificado pelo seu SHA-256: qualquer pessoa pode "
            "conferir que é exatamente o mesmo.",
        ),
        (
            "dice",
            "Risco reamostrado",
            "Drawdown provável em um ano e simulação de desafios de prop firms, com as "
            "suposições escritas ao lado.",
        ),
        (
            "eye",
            "Página pública com selo",
            "Publique a verificação da sua auditoria e mostre-a com um selo que diz exatamente "
            "o que ela é e o que não é, em português, inglês ou espanhol.",
        ),
        (
            "percent",
            "Frente ao caixa",
            "Subtraímos o que o caixa pagava nas mesmas datas, na moeda da sua conta quando o "
            "seu relatório a indica (reais, pesos mexicanos, euros, libras, ienes, dólares "
            "canadenses ou francos suíços) e, se não, em dólares (letras do Tesouro dos EUA de "
            "3 meses). Dados públicos oficiais. Você vê o Sharpe sem o que o caixa já pagava "
            "e, se enviar um benchmark, o alfa, medido frente às letras dos EUA.",
        ),
        (
            "chart",
            "Mercado tranquilo e agitado",
            "Cada rentabilidade é atribuída segundo o VIX do dia anterior, e cada crise de data "
            "pública que o seu histórico cobre é medida à parte: você vê se o resultado depende "
            "de um só tipo de mercado.",
        ),
        (
            "globe",
            "Na sua moeda e depois da inflação",
            "Se a conta está em dólares, você vê o resultado em reais, pesos mexicanos, "
            "euros e mais "
            "quatro moedas ao câmbio de cada dia, e depois da inflação dos EUA (dados públicos "
            "do FRED).",
        ),
    ],
    "how_eyebrow": "Processo",
    "pricing_eyebrow": "Preços",
    "plan_free": "Prévia",
    "plan_free_amount": "Grátis",
    "plan_free_note": f"com a sua conta: o primeiro relatório completo e {_FREE} por mês",
    "plan_full": "Relatório completo",
    "plan_full_note": "por auditoria",
    "plan_badge": "Completo",
    "free_items": [
        "Classe de A a D e resumo em linguagem simples",
        "O que cada dimensão significa para você",
        "Gráficos de equity, drawdown e retornos mensais",
        "Bandeiras vermelhas e impressões digitais dos seus arquivos",
    ],
    "full_items": [
        "Todo o detalhe numérico, sem marca d'água",
        "Simulador de desafio de prop firm",
        "Risco reamostrado em um ano e o capital que pede",
        "Testes de estresse: o resultado sem as suas melhores operações",
        "A conta real frente ao seu backtest",
        "Perguntas para o vendedor do robô ou para o gestor",
        "Se funciona em cada mercado ou se um carrega o resto",
        "Para fundos: calendário ano por mês, pior mês e tempo para se recuperar",
        "O dinheiro real por trás do % de uma conta: depósitos, recargas e perdas abertas",
        "Frente ao caixa e ao mercado: o Sharpe sem o que o caixa pagava, VIX tranquilo ou "
        "agitado e crises conhecidas",
        "Se a conta está em dólares: o resultado na sua moeda e depois da inflação",
        "Página pública de verificação com selo",
    ],
    "upload_eyebrow": "Comece aqui",
    "upload_title": ("A sua auditoria,", "em um só arquivo."),
    "upload_lead": (
        "Envie o relatório do jeito que a sua plataforma salva. A classe, os gráficos e a "
        "explicação de cada dimensão são grátis."
    ),
    "upload_points": [
        "O seu arquivo nunca é publicado.",
        (
            "O seu primeiro relatório completo, grátis ao criar a sua conta; depois, "
            f"{_FREE} prévias grátis por mês. Sem cartão."
        ),
        "Apagado automaticamente se você não desbloquear o relatório.",
    ],
    "drop_title": "Arraste o seu relatório aqui",
    "drop_sub": "ou clique para escolher · até 10 MB",
    "drop_small": "Arraste ou clique",
    "no_report": "Não tem relatório? Envie a sua curva de equity",
    "extras": "Adicionar mais arquivos",
    "extras_note": "Opcional: XML de otimização, conta real ou demo, desafio de prop firm",
    "advanced": "Opções avançadas",
    "advanced_note": "Tudo tem um valor padrão",
    "busy_title": "Auditando o seu arquivo",
    "busy_sub": "Não feche esta página.",
    "busy_steps": [
        "Lendo o arquivo",
        "Medindo significância e tentativas",
        "Reamostrando cenários",
        "Redigindo o veredito",
    ],
    "faq_eyebrow": "Perguntas",
    "final_title": ("Antes de arriscar dinheiro numa estratégia,", "olhe com lupa."),
    "final_lead": "Envie o relatório e receba a classe, os gráficos e a explicação sem custo.",
    "footer_product": "Produto",
    "footer_legal": "Jurídico",
    "footer_news": "Novidades",
    "footer_base": "Só análise estatística: sem ordens, sem custódia e sem chaves de corretora.",
    "v_eyebrow": "Verificação pública",
    "v_copy": "Copiar código",
    "v_copied": "Copiado",
    "v_id": "ID",
    "guides_eyebrow": "Guias de exportação",
    "legal_eyebrow": "Jurídico",
    "error_eyebrow": "Algo não bate",
}

#: The landing's "who it is for" cards in Portuguese (same order as ``AUDIENCE_PAGES``).
AUDIENCES_PT: dict[str, Any] = {
    "eyebrow": "Para quem é",
    "title": ("O mesmo rigor,", "seja qual for o seu mercado."),
    "lead": (
        "Forex, ações, futuros ou cripto; a sua estratégia, um robô comprado, um desafio ou o "
        "dinheiro que você confia a outra pessoa. Encontre o seu caso."
    ),
    "upload": "Você envia",
    "get": "Você recebe",
    "items": [
        (
            "layers",
            "Você compra ou usa um robô (EA)",
            "O backtest do vendedor parece perfeito e você não sabe se é sobreajuste.",
            "o relatório do testador do MetaTrader 4 ou 5 e, se tiver, o XML de otimização.",
            "se o resultado aguenta o número de tentativas, custos mais altos e perder as suas "
            "melhores operações, e o que perguntar ao vendedor.",
            "mt5",
        ),
        (
            "chart",
            "Você opera ações, futuros, forex ou cripto",
            "Você não sabe se a sua vantagem é real ou se a encontrou de tanto testar.",
            "a lista de operações do TradingView ou NinjaTrader, o CSV do QuantConnect, "
            "backtesting.py ou vectorbt, o histórico em CSV ou Excel de qualquer corretora, "
            "exchange ou diário (Interactive Brokers, Tradovate, thinkorswim, Binance e mais), "
            "ou a sua curva de equity.",
            "significância, Sharpe deflacionado, custos, se continua funcionando no período "
            "recente e que capital pede.",
            "tradingview",
        ),
        (
            "target",
            "Você vai pagar um desafio de prop firm",
            "Uma sequência ruim pode derrubar a conta mesmo que a estratégia funcione.",
            "o seu backtest ou histórico e o desafio que quer simular.",
            "com que frequência você tocaria a perda diária ou a total em {presets} desafios da "
            "FTMO, FundedNext, The5ers e Topstep, reamostrando o seu próprio histórico.",
            "",
        ),
        (
            "eye",
            "Você investe com um gestor, um sinal ou um fundo",
            "A porcentagem que mostram pode vir de depósitos, de poucos meses bons ou de um "
            "backtest.",
            "o histórico da conta dele (MetaTrader, Myfxbook, FX Blue ou sinal da MQL5) ou a "
            "tabela de rentabilidades mensais em CSV ou Excel.",
            "o resultado separado dos depósitos e saques, se a conta se parece com o backtest, "
            "se o histórico é evidência ou sorte e, com 24 meses ou mais, o calendário ano por "
            "mês e a queda mais funda.",
            "cuenta-proveedor",
        ),
    ],
    "guide": "Qual arquivo enviar",
    "more": "Ver o que revisa no seu caso",
    "also": "Outro caso:",
    "start": "Começar",
}

#: The landing's pointer for someone about to copy or fund another trader.
INVESTOR_PT: dict[str, Any] = {
    "eyebrow": "Para quem vai copiar ou investir",
    "title": "Vai copiar ou investir com alguém?",
    "text": (
        "Peça o histórico completo da conta de MetaTrader dessa pessoa e envie junto com o "
        "backtest. O Rigor lê o dinheiro que de fato entrou e saiu e diz se a conta se parece "
        "com o que o backtest mostra, com cada número etiquetado segundo a sua evidência."
    ),
    "points": (
        "Depósitos e saques separados do resultado das operações",
        "A conta real frente a milhares de histórias do seu backtest",
        "Sem conexão com a corretora dela nem com o seu dinheiro",
    ),
    "cta": "Como revisar a conta",
}

#: Why trust Rigor before paying, each point with the page that proves it.
TRUST_PT: dict[str, Any] = {
    "eyebrow": "Trabalho real, não fumaça",
    "title": ("Sem robôs, sem sinais,", "sem promessas."),
    "lead": (
        "O Rigor não vende estratégias nem resultados: mede o arquivo que você envia e mostra "
        "como mede. Tudo desta seção você pode conferir antes de pagar."
    ),
    "items": [
        (
            "eye",
            "Veja um relatório inteiro antes de pagar",
            "O exemplo é um relatório completo, com o PDF, feito com dados sintéticos: você vê "
            "exatamente o que recebe (em inglês).",
            "Ver o exemplo",
            "sample",
        ),
        (
            "layers",
            "Métodos publicados, não uma caixa-preta",
            "Sharpe probabilístico e deflacionado (Bailey e López de Prado), probabilidade de "
            "sobreajuste e bootstrap estacionário (Politis e Romano). Cada teste e cada limite "
            "estão escritos.",
            "Ler a metodologia (em inglês)",
            "method",
        ),
        (
            "shield",
            "Não vendemos robôs nem sinais",
            "Não executamos ordens nem pedimos as chaves da sua corretora, e nenhum relatório "
            "promete resultados: um filtro automático barra qualquer texto que o faça.",
            "",
            "",
        ),
        (
            "hash",
            "Um relatório que não pode ser retocado",
            "Cada relatório leva a impressão SHA-256 dos seus arquivos e do resultado; qualquer "
            "pessoa pode conferir que um PDF ou um JSON não foi editado.",
            "Conferir um relatório (em inglês)",
            "check",
        ),
        (
            "lock",
            "O seu arquivo é seu",
            "Nunca é publicado. Se você não desbloquear o relatório, é apagado após {retention} "
            "dias, e você pode apagar a sua conta e os seus relatórios quando quiser.",
            "Política de privacidade (em inglês)",
            "privacy",
        ),
        (
            "card",
            "Se ler mal o seu arquivo, devolvemos o valor",
            "Se as operações, o saldo ou as datas não batem com a sua plataforma e não "
            "conseguimos corrigir, devolvemos o que você pagou por esse relatório.",
            "Termos do serviço (em inglês)",
            "terms",
        ),
    ],
    "who": "Quem está por trás: {name}, {address}.",
    "ask": "Dúvidas antes de enviar? Escreva pelo WhatsApp; responde uma pessoa.",
    "ask_link": "Escrever pelo WhatsApp",
}

#: Report words the landing shows (the illustration, the dimension cards).
DIMENSION_TITLES_PT: dict[str, str] = {
    "statistical_significance": "Significância estatística",
    "multiplicity": "Número de configurações testadas",
    "costs": "Custos",
    "out_of_sample": "Fora da amostra",
    "data_quality": "Qualidade dos dados e forma de operar",
    "benchmark": "Benchmark",
}
STATUS_TEXT_PT: dict[str, str] = {
    "PASS": "Passa",
    "WEAK": "Fraca",
    "FAIL": "Não passa",
    "NOT_MEASURED": "Não medida",
    "NOT_APPLICABLE": "Não se aplica",
}
CLASS_B_PT = (
    "Classe B: a estatística se sustenta, mas faltam peças (custos, fora da amostra ou "
    "benchmark) para uma conclusão completa."
)
DISCLAIMER_PT = (
    "Esta auditoria é uma ferramenta de pesquisa estatística aplicada a dados fornecidos pelo "
    "cliente. Não é recomendação de investimento, não executa operações, não guarda fundos nem "
    "chaves e não prevê resultados futuros. Cada valor leva a sua etiqueta de evidência: "
    "MEASURED foi calculado a partir do arquivo, DECLARED foi afirmado pelo cliente e não pôde "
    "ser conferido, NOT_MEASURED não pôde ser calculado com o que foi fornecido."
)
MONTHS_PT: tuple[str, ...] = (
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
)

#: The service's own messages (``web.MESSAGES``) in Portuguese: the refusals
#: an upload from ``/pt`` and the errors of a Portuguese page show.
MESSAGES_PT: dict[str, str] = {
    "consent_required": "Você precisa aceitar as condições para enviar a auditoria.",
    "cross_site": "Este envio não vem do formulário deste site. Abra a página e envie por lá.",
    "rate_limited": "Auditorias demais a partir deste endereço na última hora; tente mais tarde.",
    "too_large": (
        "O arquivo {what} passa de {limit}, o máximo que aceitamos: envie uma versão "
        "menor (por exemplo, um período mais curto ou menos passagens de otimização)."
    ),
    "optimization_too_large": (
        "O XML de otimização passa de {limit} (cerca de {passes} passagens), o "
        "máximo que aceitamos: otimize de novo com o algoritmo genético ou com faixas de "
        "parâmetros mais curtas e exporte outra vez. Você também pode enviar o relatório sem o "
        "XML e escrever o número de passagens em «Configurações testadas»."
    ),
    "equity_required": (
        "Falta o arquivo: envie o relatório da sua plataforma (MetaTrader, "
        "TradingView...) ou uma curva de equity."
    ),
    "invalid_declared": (
        "Algum dado declarado não é válido: o número de tentativas deve ser 1 ou "
        "mais, o custo não pode ser negativo, o saldo inicial deve ser positivo, o desafio deve "
        "ser um da lista, a descrição tem no máximo 2000 caracteres e a data fora da amostra vai "
        "como AAAA-MM-DD."
    ),
    "invalid_form": (
        "O formulário chegou incompleto ou com um valor inválido; revise-o e envie de novo."
    ),
    "invalid_upload": (
        "Não foi possível auditar o que você enviou do jeito que está; confira o formato dos "
        "arquivos."
    ),
    "page_missing": "Esta página não existe. Confira o endereço ou volte ao início.",
    "not_found": "Não encontramos essa auditoria. Confira se o link está completo.",
    "purged": "Esta auditoria foi apagada ao fim do prazo de conservação.",
    "payment_required": "O detalhe completo desta auditoria requer pagamento.",
    "payments_disabled": "Os pagamentos não estão ativados neste serviço.",
    "card_paid": (
        "Pagamento recebido: este é o relatório completo. A Stripe envia o recibo por e-mail."
    ),
    "card_pending": (
        "Estamos confirmando o seu pagamento com a Stripe. Recarregue esta página em "
        "alguns segundos; não pague de novo."
    ),
    "card_cancelled": "Pagamento cancelado: nada foi cobrado. Esta é a prévia.",
    "code_applied": "Código de acesso aplicado: este é o relatório completo.",
    "codes_disabled": "Este serviço não aceita códigos de acesso.",
    "busy": (
        "O serviço está calculando outras auditorias neste momento; envie o arquivo de novo "
        "em um minuto."
    ),
    "pdf_busy": "Estamos preparando outros PDFs neste momento. Tente de novo em alguns segundos.",
    "pdf_limit": "Você preparou vários PDFs há pouco. Tente de novo em alguns minutos.",
    "pdf_unavailable": (
        "O download em PDF não está disponível agora. Use o botão de imprimir da "
        "página do relatório e escolha salvar como PDF."
    ),
    "server_error": (
        "Algo falhou do nosso lado ao processar o pedido. Nada novo foi salvo; tente "
        "de novo e, se acontecer outra vez, fale conosco."
    ),
    "body_too_large": (
        "O envio passa de {limit} no total, o tamanho máximo que aceitamos: envie "
        "menos arquivos de uma vez ou versões menores."
    ),
    "publish_locked": "Só um relatório completo pode publicar uma verificação.",
}


__all__ = [
    "AUDIENCES_PT",
    "CLASS_B_PT",
    "COPY_PT",
    "DIMENSION_TITLES_PT",
    "DISCLAIMER_PT",
    "FALLBACK",
    "INVESTOR_PT",
    "LANGUAGE_NAMES",
    "MONTHS_PT",
    "STATUS_TEXT_PT",
    "TRUST_PT",
    "UI_PT",
    "link_locale",
]
