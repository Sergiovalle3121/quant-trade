"""Portuguese (Brazil) words for the account screens.

Sign-up, sign-in, "Minha conta", password recovery, the upload gates and
"Minhas estratégias" read in Portuguese at ``/pt/cadastro``, ``/pt/entrar``
and ``/pt/conta``. The report itself, its PDF and the compare page still open
in English from here, as ``portuguese.link_locale`` says. Every sentence
keeps the limits of the Spanish and English text and passes the
profit-claim guard.
"""

from __future__ import annotations

from quant_trade.audit.accounts import FREE_PREVIEWS_PER_MONTH, MIN_PASSWORD_CHARS
from quant_trade.audit.seo import BRAND

PATHS_PT: dict[str, str] = {
    "signup": "/pt/cadastro",
    "signin": "/pt/entrar",
    "signout": "/pt/sair",
    "account": "/pt/conta",
    "forgot": "/pt/esqueci",
    "reset": "/pt/redefinir",
}

COPY_PT: dict[str, str] = {
    "eyebrow": "Sua conta",
    "signup_title": "Crie sua conta",
    "signup_lead": (
        "Ao criar sua conta, seu primeiro relatório completo é grátis, com o PDF. Depois "
        f"você tem {FREE_PREVIEWS_PER_MONTH} prévias grátis por mês, e seus relatórios, "
        "créditos e compras num só lugar."
    ),
    "signin_title": "Entre na sua conta",
    "signin_lead": "Seus relatórios, créditos e compras estão aqui.",
    "email": "E-mail",
    "password": "Senha",
    "password_new": "Nova senha",
    "password_current": "Senha atual",
    "password_help": f"Pelo menos {MIN_PASSWORD_CHARS} caracteres. Uma frase longa serve.",
    "signup_button": "Criar conta",
    "signin_button": "Entrar",
    "have_account": "Já tem conta?",
    "no_account": "Ainda não tem conta?",
    "signin_link": "Entrar",
    "back_to_signin": "Voltar ao login",
    "signup_link": "Crie uma grátis",
    "forgot_link": "Esqueci minha senha",
    "terms_agree": "Ao criar a conta você aceita os {terms} e a {privacy}.",
    "terms_link": "termos de serviço",
    "privacy_link": "política de privacidade",
    "benefits": (
        "Todos os seus relatórios numa lista, com a classe|"
        "Seus créditos de acesso à vista, sem procurar códigos|"
        "Desbloqueie um relatório com um clique usando seus créditos|"
        "Suas compras com cartão e com código, com data"
    ),
    "email_bad": "Esse e-mail não parece válido.",
    "password_short": f"A senha precisa de pelo menos {MIN_PASSWORD_CHARS} caracteres.",
    "password_long": "A senha é longa demais (no máximo 256 caracteres).",
    "password_bad": "A senha tem um caractere que não pode ser usado.",
    "password_common": (
        "Essa senha está entre as primeiras que qualquer lista de tentativas testa. Use uma "
        "frase sua, por exemplo três ou quatro palavras que só você juntaria."
    ),
    "taken": (
        "Não foi possível criar uma conta com esse e-mail. Se você já tem uma, entre com sua senha."
    ),
    "wrong": "O e-mail ou a senha não conferem.",
    "too_many": "Tentativas demais. Espere uma hora e tente de novo.",
    "csrf": "O formulário expirou. Recarregue a página e envie de novo.",
    "signed_out": "Você saiu da conta.",
    "welcome": "Conta criada. Envie um arquivo agora: o relatório fica salvo aqui.",
    "account_title": "Meus relatórios",
    "account_lead": "Tudo o que você auditou com esta conta, num só lugar.",
    "signed_in_as": "Conectado como",
    "signout_button": "Sair",
    "credits": "Créditos disponíveis",
    "credits_help": "Cada crédito desbloqueia um relatório completo.",
    "reports": "Relatórios",
    "paid_reports": "Relatórios completos",
    "new_audit": "Auditar outro arquivo",
    "first_audit": "Enviar meu primeiro arquivo",
    "reports_title": "Seus relatórios",
    "reports_none": (
        "Ainda não há relatórios na sua conta. Envie um arquivo com a sessão iniciada, ou abra "
        "um relatório que você já tem e toque em “Salvar na minha conta”."
    ),
    "col_date": "Data",
    "col_class": "Classe",
    "col_status": "Estado",
    "col_what": "Descrição",
    "open": "Abrir",
    "pdf": "PDF",
    "public_page": "Página pública",
    "compare_pick_label": "Escolher para comparar",
    "compare_button": "Comparar os dois escolhidos",
    "compare_help": "Marque dois relatórios completos e compare lado a lado, sem colar links.",
    "compare_pick": "Escolha exatamente dois relatórios completos da sua lista para comparar.",
    "compare_back": "Voltar aos meus relatórios",
    "compare_mine": "São relatórios da sua conta? Compare a partir da sua lista, sem links.",
    "compare_mine_button": "Escolher dos meus relatórios",
    "compare_lead": (
        "Dois relatórios da sua conta. Serve para ver o que mudou entre duas versões de uma "
        "estratégia ou entre dois robôs."
    ),
    "status_full": "Completo",
    "status_preview": "Prévia",
    "status_purged": "Arquivos apagados",
    "status_published": "Página pública",
    "status_saved": "Salvo de um link",
    "paid_card": "cartão",
    "paid_code": "código",
    "paid_welcome": "grátis, primeiro relatório",
    "welcome_kpi": "Primeiro relatório completo grátis",
    "welcome_available": "Disponível",
    "welcome_used": "Usado",
    "welcome_refused_file": (
        "Este arquivo já recebeu um relatório completo grátis, então desta vez "
        "é uma prévia. Seu relatório grátis continua disponível para outro arquivo."
    ),
    "welcome_refused_device": (
        "Este navegador já usou um relatório completo grátis em outra conta, então desta vez é "
        "uma prévia: assim a oferta não se repete com contas novas."
    ),
    "welcome_refused_network": (
        "Esta rede já usou os relatórios completos grátis deste mês, então desta vez é uma "
        "prévia. Seu relatório grátis continua disponível de outra rede ou no mês que vem."
    ),
    "welcome_notice": (
        "Seu primeiro relatório completo é grátis por criar a conta, com o PDF e a página de "
        "verificação. Para os próximos arquivos você tem {limit} prévias grátis por mês; o "
        "relatório completo custa {price} ({pack} o pacote de 3)."
    ),
    "no_description": "Sem descrição",
    "codes_title": "Seus códigos de acesso",
    "codes_none": "Ainda não há códigos na sua conta.",
    "codes_help": (
        "Um código que você usa com a sessão iniciada fica salvo aqui sozinho. Você também "
        "pode adicionar um que já tenha."
    ),
    "code_label": "Código de acesso",
    "code_add": "Adicionar à minha conta",
    "code_linked": "Código adicionado à sua conta.",
    "code_already": "Esse código já está na sua conta.",
    "code_other": "Esse código já está salvo em outra conta.",
    "code_unknown": "Não encontramos esse código. Confira se está completo.",
    "col_code": "Código",
    "col_added": "Adicionado",
    "col_left": "Restam",
    "col_used": "Usados",
    "col_expires": "Expira",
    "code_ref": "nº",
    "code_off": "desativado",
    "code_expired": "expirado",
    "code_empty": "esgotado",
    "never": "nunca",
    "purchases_title": "Suas compras",
    "purchases_none": "Ainda não há compras na sua conta.",
    "col_report": "Relatório",
    "stores_title": "O que guardamos e como apagar",
    "stores": (
        "Seu e-mail e uma impressão digital da sua senha (scrypt): nunca a senha em si.|"
        "Seus relatórios e os arquivos que você envia. Dos não pagos apagamos arquivos e "
        "relatório após {days} dias (fica só a impressão digital); os pagos e seu relatório "
        "grátis ficam para você continuar abrindo.|"
        "O endereço IP de cada envio, para os limites de uso; apagamos após {days} dias.|"
        "Seus códigos e compras, com data. Nunca vemos nem guardamos os dados do seu cartão: "
        "o pagamento com cartão é processado pela Stripe.|"
        "Uma marca aleatória do seu navegador e a impressão digital do arquivo, só para dar o "
        "relatório grátis uma vez. Elas ficam mesmo se você apagar a conta, sem o seu e-mail.|"
        "Se você entrou pelo link de um colega ou alguém entra pelo seu: a data, se já houve o "
        "primeiro relatório e uma marca aleatória do navegador (um hash), para evitar "
        "autoconvites. Ninguém vê quem entrou. É apagado com a conta de quem convida; se quem "
        "entrou apagar a sua, ficam só a data e o resultado, sem nada seu, para o limite "
        "mensal.|"
        "Se você chegou por um dos nossos links com etiqueta (como ?ref=f4), só essa etiqueta, "
        "para saber qual link funciona; ela sai com a conta.|"
        "Se você criar uma chave de recuperação, só a impressão dela (um hash) e a data, nunca "
        "a chave; ela sai ao ser usada ou com a conta.|"
        "Se você ativar a verificação em duas etapas, a chave secreta que seu app "
        "autenticador compartilha e o último código usado; ela sai ao desativar ou com a conta.|"
        "De cada sessão aberta: um rótulo curto do dispositivo (como «Chrome · Windows», nunca o "
        "texto completo do navegador), a rede e o último uso, para «Sessões abertas»; sai ao "
        "encerrar a sessão, ao expirar ou com a conta.|"
        "Para «Atividade recente»: cada entrada e cada mudança de segurança (senha, duas "
        "etapas, chave de recuperação, sessões encerradas) com a data, o rótulo do "
        "dispositivo e a rede; as últimas 50, apagadas após 90 dias ou com a conta. "
        "À parte, as tentativas com senha incorreta na sua conta: quantas por rede e hora, "
        "com o rótulo do dispositivo (nunca o que foi digitado); as últimas 20, apagadas "
        "após 90 dias ou com a conta. E, para cada navegador (sua marca aleatória, como hash), "
        "a hora da sua última visita a «Minha conta» e seu rótulo, para o aviso «Desde sua "
        "última visita»; sai após 90 dias sem visitas ou com a conta.|"
        "Para apagar tudo: «Apagar minha conta», no fim de «Minha conta». Remove na hora seu "
        "e-mail, senha, sessões e listas; você também pode apagar os relatórios que enviou."
    ),
    "col_paid": "Pago",
    "col_method": "Com",
    "buy_title": "Precisa de créditos?",
    "buy_code": "Comprar pelo WhatsApp",
    "buy_code_how": (
        "Você nos escreve pelo WhatsApp; a mensagem já diz que é para a sua conta.|"
        "Respondemos com os dados para o pagamento.|"
        "Com o pagamento confirmado você recebe um código: digite-o em Código de acesso e os "
        "créditos entram na sua conta."
    ),
    "buy_code_wait": (
        "Quem responde é uma pessoa. Se você escrever à noite ou no fim de semana, "
        "respondemos assim que virmos."
    ),
    "buy_prices_single": "Um relatório completo: {price}.",
    "buy_prices_pack": "Pacote de 3 créditos: {price}.",
    "buy_message": (
        "Olá, quero créditos para a minha conta: um relatório completo ou o pacote de 3."
    ),
    "buy_card": "Pague com cartão a partir da prévia de qualquer relatório.",
    "security_title": "Senha e dados",
    "export_title": "Baixar meus dados",
    "export_help": (
        "Um arquivo JSON com tudo o que guardamos da sua conta: seu e-mail, relatórios, "
        "códigos, compras, estratégias, prévias grátis e os endereços IP ainda não apagados. "
        "Nunca inclui sua senha nem os links privados."
    ),
    "export_button": "Baixar meus dados (JSON)",
    "invite_title": "Convide um colega",
    "invite_help": (
        "Compartilhe seu link pessoal. Quando alguém cria a conta com ele e recebe o primeiro "
        "relatório grátis, você recebe {credits} {unit} para um relatório completo, até {cap} "
        "por mês."
    ),
    "invite_unit_one": "crédito",
    "invite_unit_many": "créditos",
    "invite_label": "Seu link pessoal",
    "invite_share": "Enviar pelo WhatsApp",
    "invite_share_text": (
        "Conheça o Rigor: você envia seu backtest ou histórico e recebe uma auditoria "
        "independente. O primeiro relatório completo é grátis:"
    ),
    "invite_joined": "Entraram com seu link",
    "invite_waiting": "Aguardam o primeiro relatório",
    "invite_credited": "Créditos recebidos",
    "invite_month": "Este mês: {n} de {cap}",
    "invite_rules": (
        "Só contam contas novas de outras pessoas: não do seu mesmo navegador nem da sua "
        "mesma rede. O crédito aparece em «Seus códigos de acesso» e é usado como qualquer "
        "outro. Nunca mostramos quem entrou."
    ),
    "invited_banner": (
        "Um colega convidou você. Crie sua conta e o primeiro relatório completo é grátis."
    ),
    "change_password": "Trocar senha",
    "password_changed": "Senha trocada. Suas outras sessões foram encerradas.",
    "delete_title": "Apagar minha conta",
    "delete_help": (
        "Apaga seu e-mail, senha, sessões e a lista dos seus relatórios e códigos. Os "
        "relatórios continuam abrindo com o link privado até o fim do prazo de conservação, "
        "a menos que você marque a caixa para apagar também os que enviou com esta conta. Os "
        "que você salvou ou pagou a partir do link de outra pessoa só saem da sua lista."
    ),
    "delete_reports": "Apagar também os relatórios que enviei (não pode ser desfeito)",
    "delete_button": "Apagar minha conta",
    "deleted": "Sua conta foi apagada.",
    "forgot_title": "Recuperar sua senha",
    "forgot_lead": (
        "Ainda não enviamos e-mails. Escreva para nós a partir do e-mail da sua conta e "
        "enviamos um link de uso único para criar uma nova senha."
    ),
    "forgot_contact": "Escrever pelo WhatsApp",
    "forgot_message": f"Olá, esqueci a senha da minha conta {BRAND}. Meu e-mail é: ",
    "recover_title": "Com sua chave de recuperação",
    "recover_lead": (
        "Se você guardou sua chave de recuperação, crie uma nova senha aqui mesmo. Se não, "
        "escreva para nós."
    ),
    "recover_help": (
        "Digite o e-mail da sua conta, a chave de 20 caracteres que você guardou e sua nova "
        "senha. A chave funciona uma única vez; depois crie outra em Minha conta."
    ),
    "recovery_key": "Chave de recuperação",
    "recover_code": "Código do seu app (só com verificação em duas etapas)",
    "recover_code_help": "Deixe vazio se você não ativou a verificação em duas etapas.",
    "code_bad_reset": (
        "Sua conta tem verificação em duas etapas: digite também um código atual do seu app. Se "
        "você perdeu o telefone, entre com sua senha e use a chave na etapa do código, ou "
        "escreva para nós."
    ),
    "recover_button": "Salvar nova senha",
    "recover_none_title": "Não tem chave?",
    "recovery_bad": (
        "O e-mail ou a chave de recuperação não conferem, ou a chave já foi usada. Confira se "
        "você a digitou inteira."
    ),
    "recovered": (
        "Senha salva e sessões encerradas. Entre com ela e crie uma nova chave de recuperação "
        "em Minha conta: a anterior já foi usada."
    ),
    "recovery_title": "Chave de recuperação",
    "recovery_missing": (
        "Você ainda não tem chave. Com ela você mesmo cria uma nova senha se esquecer a sua, "
        "sem nos escrever e sem perder seus relatórios."
    ),
    "recovery_made": (
        "Criada em {date}. Se você a perdeu, crie uma nova: a anterior deixa de funcionar."
    ),
    "recovery_make": "Criar minha chave de recuperação",
    "recovery_new": "Criar uma chave nova",
    "recovery_nudge": (
        "Crie sua chave de recuperação: se esquecer sua senha, você mesmo a recupera em um minuto."
    ),
    "recovery_shown_title": "Sua chave de recuperação",
    "recovery_shown_lead": (
        "Guarde-a agora: é a única vez que a mostramos. Guardamos só a impressão dela, então "
        "ninguém pode vê-la de novo, nem nós."
    ),
    "recovery_shown_how": (
        "Copie-a em um gerenciador de senhas ou escreva-a em papel.|"
        "Se esquecer sua senha: Esqueci minha senha, seu e-mail, esta chave e uma nova senha.|"
        "Funciona uma única vez. Quem a tiver junto com seu e-mail pode entrar na sua conta: "
        "não a compartilhe."
    ),
    "recovery_done": "Já guardei, voltar para Minha conta",
    "sessions_title": "Sessões abertas",
    "sessions_help": (
        "Onde sua conta está aberta. Se não reconhecer alguma, encerre-a e troque sua senha."
    ),
    "col_device": "Dispositivo",
    "col_network": "Rede",
    "col_last_use": "Último uso",
    "col_started": "Desde",
    "col_action": "Ação",
    "session_this": "este navegador",
    "session_unknown": "Sem dados ainda",
    "session_end": "Encerrar",
    "sessions_end_others": "Encerrar todas as outras",
    "session_ended": "Sessão encerrada.",
    "sessions_ended": "Encerramos todas as outras sessões.",
    "activity_title": "Atividade recente",
    "activity_help": (
        "Entradas e mudanças de segurança da sua conta nos últimos 90 dias. Se vir algo que você "
        "não fez, troque sua senha e encerre as outras sessões."
    ),
    "col_when": "Quando",
    "col_event": "O que aconteceu",
    "event_signup": "Conta criada",
    "event_signin": "Entrada com senha",
    "event_signin_two_step": "Entrada com senha e código",
    "event_signin_recovery_key": "Entrada com a chave de recuperação (duas etapas desativada)",
    "event_password_changed": "Senha trocada",
    "event_password_recovered": "Senha nova com a chave de recuperação",
    "event_password_reset": "Senha nova com um link de redefinição",
    "event_two_step_on": "Verificação em duas etapas ativada",
    "event_two_step_off": "Verificação em duas etapas desativada",
    "event_two_step_off_by_owner": "Verificação em duas etapas desativada pelo suporte",
    "event_recovery_key_created": "Chave de recuperação nova",
    "event_session_ended": "Uma sessão foi encerrada",
    "event_sessions_ended": "Todas as outras sessões foram encerradas",
    "event_signin_failed_one": "Senha incorreta (1 tentativa)",
    "event_signin_failed": "Senha incorreta ({count} tentativas)",
    "notice_title": "Desde sua última visita",
    "notice_failed_one": "1 tentativa de entrar com senha incorreta.",
    "notice_failed": "{count} tentativas de entrar com senha incorreta.",
    "notice_new_device": "Uma entrada de um dispositivo novo: {device}.",
    "notice_unknown_device": "Uma entrada de um dispositivo desconhecido.",
    "notice_more_devices": "E mais {count} entradas de outros dispositivos novos.",
    "notice_help": "Se não foi você, troque sua senha e encerre as outras sessões.",
    "notice_link": "Ver a atividade recente",
    "two_step_card": "Verificação em duas etapas",
    "two_of_three": (
        "Com as duas etapas ativas, para entrar ou recuperar a conta você precisa de duas destas "
        "três coisas: sua senha, o código do seu app ou sua chave de recuperação. Guarde a chave "
        "longe da sua senha."
    ),
    "two_step_is_off": (
        "Desativada. Ative-a para que, além da sua senha, o login peça um código de 6 dígitos "
        "de um app autenticador (Google Authenticator, Microsoft Authenticator, 1Password ou "
        "outro)."
    ),
    "two_step_is_on": "Ativada desde {date}. Para desativá-la, digite um código atual do seu app.",
    "two_step_needs_key": (
        "Primeiro crie sua chave de recuperação: é sua saída se você perder o telefone."
    ),
    "two_step_turn_on": "Ativar verificação em duas etapas",
    "two_step_turn_off": "Desativar",
    "two_step_code": "Código de 6 dígitos",
    "two_step_code_help": "Seu app autenticador o mostra; ele muda a cada 30 segundos.",
    "two_step_setup_title": "Ative a verificação em duas etapas",
    "two_step_setup_lead": (
        "Conecte seu app autenticador e confirme com um código. Até lá nada muda."
    ),
    "two_step_setup_how": (
        "Abra seu app autenticador e escolha adicionar uma conta.|"
        "Escaneie o código QR ou digite a chave abaixo.|"
        "Digite o código de 6 dígitos que aparece para confirmar."
    ),
    "two_step_secret": "Não consegue escanear? Digite esta chave no app:",
    "two_step_confirm": "Confirmar e ativar",
    "two_step_cancel": "Cancelar e voltar para Minha conta",
    "two_step_title": "Digite o código do seu app",
    "two_step_lead": "Sua senha está certa. Falta o código de 6 dígitos do seu app autenticador.",
    "two_step_lost": "Perdeu o telefone?",
    "two_step_lost_help": (
        "Entre com sua chave de recuperação. Ela funciona uma única vez e desativa a "
        "verificação em duas etapas; depois crie uma chave nova e ative-a de novo."
    ),
    "two_step_lost_button": "Entrar com minha chave de recuperação",
    "code_bad": (
        "O código não é válido ou já foi usado. Espere o próximo código do seu app e confira "
        "se a hora do telefone está automática."
    ),
    "two_step_on": "Verificação em duas etapas ativada. Agora o login pede o código.",
    "two_step_off": "Verificação em duas etapas desativada.",
    "two_step_off_by_key": (
        "Você entrou com sua chave de recuperação e a verificação em duas etapas foi "
        "desativada. Crie uma chave nova e ative-a de novo."
    ),
    "two_step_expired": "A etapa do código expirou. Entre de novo com sua senha.",
    "reset_title": "Criar uma nova senha",
    "reset_lead": "Este link funciona uma vez e expira em 24 horas.",
    "reset_button": "Salvar senha",
    "reset_bad": "Este link já foi usado ou expirou. Peça um novo.",
    "reset_done": "Senha salva. Entre com ela.",
    "saved_box": "Salvo na sua conta.",
    "saved_link": "Ver meus relatórios",
    "save_box": "Salve este relatório na sua conta para encontrá-lo sem o link.",
    "save_button": "Salvar na minha conta",
    "save_other": "Este relatório está salvo em outra conta.",
    "anon_box": "Crie uma conta grátis para salvar este relatório e encontrá-lo sem o link.",
    "anon_signup": "Criar conta",
    "anon_signin": "Entrar",
    "credit_button": "Desbloquear com 1 crédito da sua conta",
    "credit_left": "Você tem {n} créditos.",
    "credit_left_one": "Você tem 1 crédito.",
    "credit_used": "Crédito usado: este é o relatório completo.",
    "free_left": "Prévias grátis este mês",
    "free_left_value": "{left} de {limit}",
    "gate_signin_title": "Crie sua conta grátis: seu primeiro relatório completo é por nossa conta",
    "gate_signin_lead": (
        "Ao criar sua conta, o primeiro arquivo que você enviar sai como relatório completo, "
        "com o PDF, sem custo. Depois você tem {limit} prévias grátis por mês: a classe de A a "
        "D, os gráficos e as bandeiras vermelhas. Seu arquivo não foi guardado: com a conta "
        "criada você volta ao formulário para enviá-lo de novo. Se você já tem um código de "
        "acesso, digite-o no formulário e não precisa de conta."
    ),
    "gate_code_title": "Esse código não funciona",
    "gate_code_lead": (
        "Não encontramos esse código ou ele não tem mais créditos. Confira, ou crie uma conta "
        "grátis para ter {limit} prévias por mês."
    ),
    "gate_quota_title": "Você usou suas {limit} prévias grátis deste mês",
    "gate_quota_lead": (
        "Elas renovam no dia 1º de cada mês. Para auditar agora, adicione créditos à sua "
        "conta: com créditos, cada arquivo novo sai como relatório completo."
    ),
    "gate_network_title": "Esta rede usou suas prévias grátis deste mês",
    "gate_network_lead": (
        "Também contamos as prévias grátis por rede, para frear contas descartáveis. Você pode "
        "auditar com um código ou com créditos na sua conta, ou voltar no dia 1º."
    ),
    "gate_signup": "Criar uma conta grátis",
    "gate_signin": "Já tenho conta",
    "gate_buy": "Ver preços e adicionar créditos",
    "gate_back": "Voltar à página inicial",
    "credit_on_upload": "Usamos 1 crédito da sua conta: este é o relatório completo.",
    "credit_none": "Não restam créditos na sua conta.",
    "saved_notice": "Relatório salvo na sua conta.",
    "nav_account": "Minha conta",
}

#: "Minhas estratégias", the Portuguese of ``strategies.COPY``.
STRATEGIES_PT: dict[str, str] = {
    "section_title": "Minhas estratégias",
    "section_lead": (
        "Agrupe as versões de uma mesma estratégia ou robô. Cada estratégia mostra seus "
        "relatórios em ordem e, ao lado de cada versão, o que mudou em relação à anterior."
    ),
    "none": "Você ainda não tem estratégias. Crie uma e guarde nela seus relatórios.",
    "no_reports": "Envie um arquivo primeiro: depois poderá guardá-lo numa estratégia.",
    "versions": "{n} versões",
    "version_one": "1 versão",
    "latest": "Última classe",
    "open": "Ver estratégia",
    "file_title": "Guardar um relatório numa estratégia",
    "report": "Relatório",
    "strategy": "Estratégia",
    "new_strategy": "Nova estratégia…",
    "new_name": "Nome da nova estratégia",
    "new_name_help": "Por exemplo: EA Ouro, versão com stop mais curto.",
    "file_button": "Guardar na estratégia",
    "filed": "Relatório guardado na estratégia.",
    "file_bad": "Escolha um relatório da sua lista e uma estratégia, ou escreva um nome.",
    "strategy_full": "Você chegou ao máximo de estratégias de uma conta.",
    "page_lead": (
        "As versões desta estratégia em ordem, com o que cada relatório mediu. Uma diferença "
        "diz quais testes mudaram, não como a estratégia vai se sair."
    ),
    "col_version": "Versão",
    "col_date": "Data",
    "col_class": "Classe",
    "col_sharpe": "Sharpe anualizado",
    "col_dsr": "Sharpe deflacionado",
    "col_dd": "Queda máxima",
    "locked": "Prévia",
    "unlock": "Desbloquear para ver os números",
    "changed_title": "O que mudou em relação à versão {n}",
    "changed_locked": (
        "Classe {a} → {b}. Para ver o que mudou em cada teste, as duas versões precisam ser "
        "relatórios completos."
    ),
    "class_line": "Classe: {a} → {b}",
    "sharpe_line": "Sharpe: {a} → {b}",
    "better": "melhor",
    "worse": "pior",
    "same": "igual",
    "unclear": "sem mudança clara",
    "different_frequency": "não comparável (frequência de dados diferente)",
    "different_periods": "períodos diferentes (as datas quase não coincidem)",
    "changed": "mudou",
    "tries_note": (
        "{n} versões testadas: se você escolher a melhor, conta como {n} tentativas ao "
        "declarar as tentativas."
    ),
    "no_change": "Nenhum teste mudou de resultado.",
    "side_by_side": "Comparar lado a lado",
    "remove": "Tirar da estratégia",
    "rename": "Trocar nome",
    "rename_button": "Salvar nome",
    "name_label": "Nome",
    "delete": "Apagar estratégia",
    "delete_help": "Os relatórios continuam na sua lista; só o agrupamento sai.",
    "back": "Voltar à minha conta",
    "missing_title": "Não encontramos essa estratégia",
    "missing_lead": (
        "Talvez você a tenha apagado ou o link não seja da sua conta. Suas estratégias estão em "
        "«Minha conta»."
    ),
    "pdf_button": "Baixar resumo em PDF",
    "pdf_generated": (
        "Resumo da estratégia gerado em {date} a partir dos relatórios salvos. Cada relatório "
        "completo tem seu próprio PDF com o detalhe."
    ),
    "empty": "Esta estratégia ainda não tem relatórios. Guarde-os a partir da sua conta.",
    "note": (
        "Cada versão é lida com seus próprios arquivos e declarações. «Melhor» ou «pior» no "
        "Sharpe só aparece quando as faixas do bootstrap (5 % a 95 %) não se tocam; se se "
        "tocam, a diferença cabe no ruído da medição; com as mesmas datas esta regra é muito "
        "prudente. Se as datas de duas versões quase não coincidem, a diferença pode vir do "
        "mercado dessas datas e não da mudança. Cada teste é lido com as declarações do seu "
        "próprio relatório (tentativas, custos, fora da amostra), por isso as suas linhas "
        "dizem «mudou» e não «melhor» ou «pior»."
    ),
}
