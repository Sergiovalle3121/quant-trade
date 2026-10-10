"""The free tools page: one stable address for the tools that need no file.

Constants only. ``seo`` lists the page in the sitemap and ``pages`` renders it;
this module imports neither of them, nor ``check`` (which imports ``seo``), so
no import cycle can start here.

Every tool on the page uses figures the visitor declares and shows its
assumptions. None of them is an audit: no file is read and no A to D class is
given. The page shows no figure of its own.
"""

from __future__ import annotations

from typing import Any

#: The page's path in each language.
TOOLS_PATH: dict[str, str] = {"es": "/herramientas", "en": "/en/tools", "pt": "/pt/ferramentas"}

#: The tools, in the order the page and the landing show them.
TOOL_KEYS: tuple[str, ...] = ("calculator", "winrate", "challenge", "reading", "check")


def tools_url(locale: str) -> str:
    return TOOLS_PATH.get(locale, TOOLS_PATH["es"])


COPY: dict[str, dict[str, Any]] = {
    "es": {
        "nav": "Herramientas gratis",
        "eyebrow": "Herramientas gratis",
        "title": "Herramientas gratis para revisar un backtest",
        "seo_title": "Herramientas gratis para backtests e historiales",
        "summary": (
            "Calculadoras de suerte, aciertos y reto, tarjeta de cifras y comprobación de "
            "informes: gratis y sin registro. Cifras declaradas; ninguna es una auditoría."
        ),
        "intro": (
            "Todas usan cifras que tú declaras y muestran sus supuestos. No son una auditoría: "
            "no vemos tu archivo y no dan una clase de A a D."
        ),
        "inputs": "Qué escribes",
        "returns": "Qué devuelve",
        "no_account": "Sin registro",
        "open": "Abrir",
        "calculator": {
            "question": (
                "¿Cuánto de tu Sharpe podría explicar la suerte de haber probado muchas "
                "configuraciones?"
            ),
            "inputs": (
                "Sharpe anual, años de historial, configuraciones probadas y frecuencia de los "
                "rendimientos."
            ),
            "returns": (
                "El Sharpe que daría la suerte, el que queda tras el descuento y los años de "
                "historial necesarios."
            ),
        },
        "winrate": {
            "question": (
                "¿Tu % de aciertos es real o es la muestra? ¿Qué % necesitas con tu objetivo y "
                "tu stop?"
            ),
            "inputs": "Operaciones, % de aciertos, objetivo y stop en R.",
            "returns": (
                "Intervalo de confianza al 95 %, % de aciertos de equilibrio y cuántas "
                "operaciones hacen falta."
            ),
        },
        "challenge": {
            "question": (
                "¿Con qué frecuencia alcanzarías el objetivo de un reto de prop firm, o tocarías "
                "un límite, con tus cifras?"
            ),
            "inputs": (
                "% de aciertos, ganancia y pérdida medias, operaciones por día, firma y programa; "
                "opcionales: operaciones del historial y cuota."
            ),
            "returns": (
                "Probabilidad de alcanzar el objetivo, de tocar el límite diario o el total y de "
                "quedar sin terminar, con las reglas publicadas de la firma y su fecha."
            ),
        },
        "reading": {
            "question": "¿Qué dicen en contexto las cifras que publica alguien, o las tuyas?",
            "inputs": (
                "Hasta ocho cifras opcionales: operaciones, % de aciertos, profit factor, Sharpe, "
                "años, configuraciones, objetivo y stop."
            ),
            "returns": (
                "Una tarjeta para compartir con el intervalo de aciertos al 95 %, el mejor "
                "resultado esperado de monedas justas, el Sharpe por suerte y los aciertos de "
                "equilibrio."
            ),
        },
        "check": {
            "question": "¿Te enviaron el PDF o el JSON de un informe de Rigor?",
            "inputs": "El archivo del informe.",
            "returns": "Si salió así de Rigor, sin editar, con su fecha y su clase.",
        },
        "report_title": "¿Tienes el archivo?",
        "report_text": (
            "Con el archivo que exporta tu plataforma, el informe mide en lugar de suponer: "
            "significancia, configuraciones probadas, costo de equilibrio, dentro y fuera de "
            "muestra, calidad de datos y referencia. El primer informe completo es gratis con "
            "cuenta."
        ),
        "report_button": "Auditar mi archivo",
        "sample_link": "Ver un informe de ejemplo",
        "articles_link": "Leer los artículos",
        "band_eyebrow": "Herramientas gratis",
        "band_title": ("Sin el archivo a mano,", "empieza gratis"),
        "band_lead": "Herramientas sin registro con tus cifras declaradas y supuestos visibles.",
        "all_tools": "Ver todas las herramientas gratis",
    },
    "en": {
        "nav": "Free tools",
        "eyebrow": "Free tools",
        "title": "Free tools to check a backtest",
        "seo_title": "Free tools for backtests and track records",
        "summary": (
            "Luck, win rate and challenge calculators, figures card and report check: free and "
            "no signup. Declared figures and visible assumptions; none is an audit."
        ),
        "intro": (
            "Each one uses figures you declare and shows its assumptions. They are not an "
            "audit: we do not see your file and they give no A to D class."
        ),
        "inputs": "What you enter",
        "returns": "What you get",
        "no_account": "No signup",
        "open": "Open",
        "calculator": {
            "question": (
                "How much of your Sharpe could the luck of trying many configurations explain?"
            ),
            "inputs": "Annual Sharpe, years of history, configurations tried and return frequency.",
            "returns": (
                "The Sharpe luck would show, the Sharpe left after the haircut and the years of "
                "history needed."
            ),
        },
        "winrate": {
            "question": (
                "Is your win rate real, or just the sample? What win rate do you need with your "
                "target and stop?"
            ),
            "inputs": "Trades, win rate, target and stop in R.",
            "returns": (
                "95 % confidence interval, break-even win rate and how many trades are needed."
            ),
        },
        "challenge": {
            "question": (
                "How often would you reach a prop firm challenge target, or hit a limit, with "
                "your figures?"
            ),
            "inputs": (
                "Win rate, average win and loss, trades per day, firm and program; optional: "
                "trades in your history and the fee."
            ),
            "returns": (
                "Chance of reaching the target, hitting the daily or total limit and being left "
                "unfinished, under the firm's dated published rules."
            ),
        },
        "reading": {
            "question": "What do someone's published figures, or yours, say in context?",
            "inputs": (
                "Up to eight optional figures: trades, win rate, profit factor, Sharpe, years, "
                "configurations, target and stop."
            ),
            "returns": (
                "A shareable card with the 95 % win-rate interval, the expected best result from "
                "fair coins, the Sharpe from luck and the break-even win rate."
            ),
        },
        "check": {
            "question": "Did someone send you the PDF or JSON of a Rigor report?",
            "inputs": "The report file.",
            "returns": "Whether it left Rigor like this, unedited, with its date and class.",
        },
        "report_title": "Have the file?",
        "report_text": (
            "With the file your platform exports, the report measures instead of assuming: "
            "significance, configurations tried, break-even cost, in-sample versus "
            "out-of-sample, data quality and a benchmark. Your first full report is free with "
            "an account."
        ),
        "report_button": "Audit my file",
        "sample_link": "See a sample report",
        "articles_link": "Read the articles",
        "band_eyebrow": "Free tools",
        "band_title": ("No file at hand?", "Start free"),
        "band_lead": "No-signup tools with your declared figures and visible assumptions.",
        "all_tools": "See all free tools",
    },
    "pt": {
        "nav": "Ferramentas grátis",
        "eyebrow": "Ferramentas grátis",
        "title": "Ferramentas grátis para revisar um backtest",
        "seo_title": "Ferramentas grátis para backtests e históricos",
        "summary": (
            "Calculadoras de sorte, acerto e desafio, cartão de números e conferência de "
            "relatórios: grátis e sem cadastro. Números declarados; nenhuma é uma auditoria."
        ),
        "intro": (
            "Todas usam números que você declara e mostram as suas suposições. Não são uma "
            "auditoria: não vemos o seu arquivo e não dão uma classe de A a D."
        ),
        "inputs": "O que você digita",
        "returns": "O que devolve",
        "no_account": "Sem cadastro",
        "open": "Abrir",
        "calculator": {
            "question": (
                "Quanto do seu Sharpe a sorte de testar muitas configurações poderia explicar?"
            ),
            "inputs": (
                "Sharpe anual, anos de histórico, configurações testadas e frequência dos retornos."
            ),
            "returns": (
                "O Sharpe que a sorte mostraria, o que sobra depois do desconto e os anos de "
                "histórico necessários."
            ),
        },
        "winrate": {
            "question": (
                "Sua taxa de acerto é real ou é a amostra? De que taxa de acerto você "
                "precisa com o seu alvo e o seu stop?"
            ),
            "inputs": "Operações, taxa de acerto, alvo e stop em R.",
            "returns": (
                "Intervalo de confiança de 95 %, taxa de acerto de equilíbrio e quantas "
                "operações são necessárias."
            ),
        },
        "challenge": {
            "question": (
                "Com que frequência você atingiria a meta de um desafio de prop firm, ou tocaria "
                "um limite, com os seus números?"
            ),
            "inputs": (
                "Taxa de acerto, ganho e perda médios, operações por dia, empresa e programa; "
                "opcionais: operações do histórico e taxa."
            ),
            "returns": (
                "Probabilidade de atingir a meta, de tocar o limite diário ou o total e de ficar "
                "sem terminar, com as regras publicadas da empresa e a data."
            ),
        },
        "reading": {
            "question": "O que dizem, em contexto, os números que alguém publica, ou os seus?",
            "inputs": (
                "Até oito números opcionais: operações, taxa de acerto, profit factor, Sharpe, "
                "anos, configurações, alvo e stop."
            ),
            "returns": (
                "Um cartão para compartilhar com o intervalo de acertos de 95 %, o melhor "
                "resultado esperado de moedas justas, o Sharpe por sorte e a taxa de acerto de "
                "equilíbrio."
            ),
        },
        "check": {
            "question": "Recebeu o PDF ou o JSON de um relatório do Rigor?",
            "inputs": "O arquivo do relatório.",
            "returns": "Se ele saiu assim do Rigor, sem edição, com a data e a classe.",
        },
        "report_title": "Tem o arquivo?",
        "report_text": (
            "Com o arquivo que a sua plataforma exporta, o relatório mede em vez de supor: "
            "significância, configurações testadas, custo de equilíbrio, dentro e fora da "
            "amostra, qualidade dos dados e referência. O seu primeiro relatório completo é "
            "grátis com conta."
        ),
        "report_button": "Auditar meu arquivo",
        "sample_link": "Ver um relatório de exemplo",
        "articles_link": "Ler os artigos",
        "band_eyebrow": "Ferramentas grátis",
        "band_title": ("Sem o arquivo à mão,", "comece grátis"),
        "band_lead": (
            "Ferramentas sem cadastro com os seus números declarados e suposições visíveis."
        ),
        "all_tools": "Ver todas as ferramentas grátis",
    },
}


__all__ = ["COPY", "TOOLS_PATH", "TOOL_KEYS", "tools_url"]
