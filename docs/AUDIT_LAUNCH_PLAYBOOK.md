# Plan de lanzamiento de la auditoría de backtests

Guía práctica para las primeras semanas de venta de la auditoría
(`src/quant_trade/audit/`) sin Stripe: el cliente paga por transferencia o
Mercado Pago y recibe un código de acceso por WhatsApp. Escrita el
2026-09-24.

Qué contiene:

1. Qué tener listo antes del primer mensaje.
2. Dónde están los compradores y qué permite cada comunidad.
3. Los tres canales con los que empezar.
4. Plantillas de mensajes en español e inglés, listas para copiar.
5. La propuesta para vendedores de robots (EA): página de verificación y sello.
6. Cómo atender a un cliente desde el primer mensaje hasta el informe entregado.
7. Plan semanal y qué medir.

## Regla que manda sobre todo lo demás

La auditoría mide la evidencia estadística de un archivo. No predice
resultados, no recomienda comprar ni vender un robot y no dice que alguien
vaya a superar un reto de prop firm. Esa regla vale igual para cada mensaje
que envíes (AGENTS.md, sección Phase 16):

- Ningún mensaje promete dinero, resultados ni retos superados. Las palabras
  que bloquea `audit/guard.py` (en español e inglés) tampoco van en un
  anuncio, una respuesta de foro ni un WhatsApp. Si dudas, pega el texto en
  `python -c "from quant_trade.audit.guard import find_claims; print(find_claims(open('msg.txt').read()))"`
  y no lo envíes hasta que salga `[]`.
- El sello y la página `/v/{id}` describen una auditoría de datos aportados,
  no comprobados con el bróker. Nunca se presentan como aval de un robot.
- Nunca pidas claves de bróker, contraseñas de cuenta ni acceso a MetaTrader.
- La clase no se negocia: el resultado sale del motor y es reproducible por
  hash, pague quien pague.

`tests/test_audit_launch_playbook.py` pasa el guard sobre este documento y
sobre cada plantilla. Si editas una plantilla, ejecuta
`python -m pytest tests/test_audit_launch_playbook.py -q` antes de usarla.

## 1. Antes del primer mensaje

Solo tú puedes hacer estos pasos (despliegue, variables y cuentas):

- [ ] Servicio desplegado en Railway siguiendo `docs/AUDIT_SAAS.md`
      ("Deploying on Railway" y "Testing a deployment on Railway").
- [ ] Variables: `AUDIT_BASE_URL` con tu dominio, `AUDIT_TRUSTED_PROXY_HOPS=1`,
      `AUDIT_ACCESS_CODES=true`, `AUDIT_FREE_MODE=false`,
      `AUDIT_PRICE_USD_CENTS=2900` y `AUDIT_CONTACT_URL=https://wa.me/<tu número>`.
- [ ] Datos del operador para términos y privacidad
      (`AUDIT_OPERATOR_NAME`, `AUDIT_OPERATOR_CONTACT`,
      `AUDIT_OPERATOR_ADDRESS`, `AUDIT_JURISDICTION`), y los dos textos
      revisados por un abogado antes de cobrar.
- [ ] `/health`, `/ejemplo` y la landing se abren en el móvil.
- [ ] Una prueba con un informe real de MT5 tuyo (el `Report.html` tal como
      lo guarda el probador). Hasta hoy los importadores solo se probaron con
      informes sintéticos, así que los primeros archivos reales de clientes
      también son una prueba: por eso las primeras auditorías son gratis
      (ver "Precios de lanzamiento").
- [ ] Un código de prueba creado y canjeado
      (`quant-trade audit codes create --credits 1 --note prueba` desde
      `railway ssh`).
- [ ] WhatsApp Business con mensaje de bienvenida, horario y un catálogo con
      un único producto: "Auditoría de backtest, informe completo".
- [ ] Un enlace de cobro de Mercado Pago (o tus datos de transferencia) y una
      hoja de cálculo de ventas (ver sección 6).
- [ ] Pregunta a un contador cómo facturar este servicio en tu país.

### Precios de lanzamiento

Recomendación del hilo de QA (G), frente a los competidores de
`docs/research/audit_iteration4/market_competitors.json` (EA Verdict USD 19,
EA X-Ray gratis y EUR 29, AntiOverfit EUR 97):

| Oferta | Precio | Cuándo |
|---|---|---|
| Vista previa | Gratis | Siempre: clase, gráficas, banderas rojas y explicación de cada dimensión. |
| Primeras 10 auditorías completas | Gratis a cambio de opinión | Semanas 1 y 2. Pide el archivo real y una opinión sobre la claridad del informe. |
| Informe completo | USD 29 (`AUDIT_PRICE_USD_CENTS=2900`) | Desde la primera venta. |
| Paquete de 3 | USD 69 (`AUDIT_PACK_PRICE_USD_CENTS=6900`, código con `--credits 3`) | Para quien compara varios robots o varias versiones. |
| Informe completo | USD 49 | Cuando tengas opiniones publicables de clientes reales. |

La vista previa gratuita es el anzuelo: el trader ve la clase y las gráficas
de su propio archivo antes de pagar. Mándalo siempre a subir primero y a
pagar después.

## 2. Dónde están los compradores

Tres grupos compran este informe:

- **Compradores de EA**: quieren saber si el backtest que les enseña un
  vendedor es sobreajuste antes de pagar el robot.
- **Traders de retos de prop firm**: quieren conocer el drawdown remuestreado
  y las reglas de pérdida diaria de su estrategia antes de pagar el reto.
- **Vendedores de EA**: quieren una evidencia estadística pública que el
  comprador pueda comprobar por hash.

Casi todas las comunidades prohíben la autopromoción gratuita. Lo que sí
funciona sin romper reglas es contestar con contenido útil, sin enlaces, en
los foros, y promocionar solo en las secciones comerciales o en tu propio
perfil, blog o web.

Estado de la revisión: "leído" significa que la página de reglas se leyó el
2026-09-24. "Fragmento" significa que el sitio bloqueó la lectura
automática y el resumen sale de fragmentos de buscador de la página oficial.
Relee esas reglas en un navegador antes de publicar. "Sin comprobar" significa
que no se encontraron las reglas.

| Comunidad | URL | Para quién | Autopromoción | Reglas | Revisado |
|---|---|---|---|---|---|
| Forex Factory | https://www.forexfactory.com | Compradores y vendedores de EA (inglés) | Prohibido promocionar en los foros normales. Quien cobra a traders debe ser "Commercial Member", con identidad pública, y solo publica en el foro "Commercial Content". Cero tolerancia a fingirse cliente satisfecho. | https://www.forexfactory.com/userguide y el hilo "Rules for Commercial Members" | 2026-09-24, fragmento |
| MQL5 foro (inglés y español) | https://www.mql5.com/es/forum | Compradores y vendedores de EA; hay foro en español | Prohibida la publicidad directa o indirecta y hablar de productos de terceros. Los moderadores mandan la promoción al blog del propio perfil. | https://www.mql5.com/en/about/rules y https://www.mql5.com/en/forum/443428 | 2026-09-24, leído |
| MQL5 Market (fichas de producto) | https://www.mql5.com/en/market/rules | Vendedores de EA | Las fichas no admiten enlaces a terceros ni imágenes de premios, sellos o testimonios de terceros: el sello no puede ir en la ficha del Market. | https://www.mql5.com/en/market/rules | 2026-09-24, leído |
| MQL5 Freelance | https://www.mql5.com/en/job | Vendedores y programadores de EA | Prohibido intercambiar contactos antes de un acuerdo de trabajo y cobrar fuera del servicio. No sirve para vender la auditoría. | https://www.mql5.com/en/job/rules | 2026-09-24, leído |
| Reddit (r/algotrading, r/Forex, subreddits de prop firms) | https://www.reddit.com/r/algotrading | Traders cuantitativos y de retos (inglés) | Norma general de Reddit: contenido auténtico, poca autopromoción. Las reglas de cada subreddit mandan y no se pudieron leer. Supuesto: la mayoría retira enlaces a productos. | https://redditinc.com/policies/reddit-rules y `old.reddit.com/r/<sub>/about/rules` | 2026-09-24, sin comprobar |
| BabyPips | https://forums.babypips.com | Principiantes (inglés) | Prohibida la publicidad y los enlaces comerciales. Solo el programa "Participate & Promote" (nivel de confianza TL3) permite un tema comercial a la vez, con aviso. | https://www.babypips.com/forum-policy | 2026-09-24, fragmento |
| Forex Peace Army | https://www.forexpeacearmy.com/community | Compradores de EA desconfiados (inglés) | Publicidad prohibida en los foros; los clasificados ("Services Offered") admiten anuncios legales gratis. Expone a quien finge ser cliente. | https://www.forexpeacearmy.com/community/help/terms/ | 2026-09-24, fragmento |
| Myfxbook comunidad | https://www.myfxbook.com/community | Vendedores de EA y señales | No se encontraron las reglas. | https://www.myfxbook.com/terms | 2026-09-24, sin comprobar |
| TradingView | https://www.tradingview.com | Traders de retos y de scripts | Todo el contenido debe estar libre de promoción, incluidos chats privados y scripts. Solo los suscriptores Premium pueden poner un enlace en la firma. | https://www.tradingview.com/house-rules/ | 2026-09-24, leído |
| Discord de FTMO | https://ftmo.com/en/blog/ftmo-discord-community-a-guide-for-traders/ | Traders de retos | Invitación pública con verificación de entrada; las reglas están dentro. Supuesto: prohíbe promoción externa. Sirve para escuchar, no para vender. | Canal de reglas del servidor | 2026-09-24, sin comprobar |
| Discord de The5ers | https://help.the5ers.com | Traders de retos | Solo para clientes que compraron una cuenta. | Canal de reglas del servidor | 2026-09-24, fragmento |
| Rankia | https://www.rankia.com | Inversores en español | Se borra la publicidad y usar el foro como tablón de anuncios. Los mensajes pasan por un filtro automático desde abril de 2025. Los profesionales pueden participar explicando su trabajo. | https://www.rankia.com/rankia/informacion-foro | 2026-09-24, leído |
| Elite Trader | https://www.elitetrader.com | Futuros y discrecionales (inglés) | Publicidad y solicitudes prohibidas, también por mensaje privado, salvo patrocinadores de pago. | https://www.elitetrader.com/et/help/terms/ | 2026-09-24, leído |
| Trade2Win | https://www.trade2win.com | Traders minoristas (inglés) | Ningún anuncio, URL ni oferta de prueba. Un vendedor puede contestar preguntas concretas sobre su producto sin promocionarlo y debe declarar su interés comercial en el perfil. | https://www.trade2win.com/help/forum-guidelines/ | 2026-09-24, leído |

Lo que esto significa:

- Los mensajes privados no solicitados están prohibidos o mal vistos en casi
  todas partes. Escribe en privado solo a quien te lo pidió o a un vendedor
  a través del contacto comercial que él mismo publica en su web.
- En los foros, contesta la pregunta con lo que sabes, sin enlace. La gente
  mira tu perfil; ahí sí va la web si las reglas lo permiten.
- El sello no puede ir en la ficha de MQL5 Market. Para un vendedor sirve en
  su web, su canal de Telegram, su hilo comercial de Forex Factory, sus vídeos
  y la descripción de su señal fuera del Market.
- Las comunidades en español con reglas públicas son pocas (Rankia, foro
  español de MQL5). No se encontró ninguna comunidad grande de Telegram o
  Discord latinoamericana con reglas públicas. Esa es la ventaja: casi nadie
  ofrece esto en español.

## 3. Los tres canales con los que empezar

1. **Contenido en español en el blog de tu perfil de MQL5, más respuestas
   útiles en el foro español de MQL5.** Es donde están los compradores y
   vendedores de EA que hablan español, y los moderadores mandan la
   promoción al blog del perfil. Publica una entrada por semana (plantilla
   F3) y contesta en el foro sin enlaces (plantilla F2). Coste cero.
2. **Hilo en "Commercial Content" de Forex Factory, como Commercial Member
   con identidad pública.** Es el mayor punto de encuentro de compradores y
   vendedores de EA en inglés. Ofrece auditar gratis backtests públicos de
   robots cuyo vendedor dé su permiso y publica el informe completo (plantilla
   F1). Comprueba antes si la membresía comercial tiene coste.
3. **Contacto directo con vendedores de EA de habla hispana** a través del
   correo o formulario comercial que publican en su propia web, uno a uno y
   personalizado (plantillas V1 y V2). Un vendedor que publica su sello trae
   a sus compradores a `/v/{id}` y a la landing.

Después, cuando haya opiniones reales: Forex Peace Army (clasificados),
Reddit (entradas de método, tras leer las reglas de cada subreddit) y un
anuncio de pago si los números de la sección 7 lo justifican.

## 4. Plantillas

Cambia lo que va entre `<…>` antes de enviar. `<dominio>` es el valor de
`AUDIT_BASE_URL`. No añadas frases sobre resultados futuros: cada plantilla
pasa el guard tal como está.

### WhatsApp

#### W1 · ES · Respuesta al primer mensaje

```text
¡Hola, <nombre>! Gracias por escribir.

La auditoría analiza el backtest o historial que ya tienes y te da una clase de A a D en seis dimensiones: significación estadística, número de intentos (Sharpe deflactado), costes, fuera de muestra, calidad de datos y comparación con un benchmark.

Cómo empezar:
1. Sube tu archivo en https://<dominio> tal cual sale de tu plataforma (MT5, MT4, TradingView, NinjaTrader, QuantConnect, backtesting.py o vectorbt).
2. La vista previa es gratis: ves la clase, las gráficas y qué significa cada dimensión.
3. Si quieres el informe completo, cuesta USD 29 y te mando un código de acceso.

Aquí tienes un informe de ejemplo con datos sintéticos: https://<dominio>/ejemplo

Es un análisis estadístico de los datos que subes; no predice resultados ni recomienda operar.
```

#### W1 · EN · Reply to the first message

```text
Hi <name>, thanks for getting in touch.

The audit analyses the backtest or history you already have and gives it a class from A to D across six dimensions: statistical significance, number of trials (deflated Sharpe), costs, out-of-sample, data quality and a benchmark comparison.

How to start:
1. Upload your file at https://<domain> exactly as your platform exports it (MT5, MT4, TradingView, NinjaTrader, QuantConnect, backtesting.py or vectorbt).
2. The preview is free: you see the class, the charts and what each dimension means.
3. If you want the full report, it is USD 29 and I send you an access code.

Here is a sample report built from synthetic data: https://<domain>/ejemplo

It is a statistical analysis of the data you upload; it does not predict results or recommend trading.
```

#### W2 · ES · Cómo exportar el informe de MetaTrader 5

```text
Para MetaTrader 5:
1. En el Probador de estrategias, al terminar la prueba, abre la pestaña "Backtest" (o "Informe").
2. Clic derecho > "Guardar como informe" y elige HTML. Sube ese archivo tal cual, sin abrirlo ni convertirlo.
3. Si optimizaste parámetros, en la pestaña "Optimización" haz clic derecho > "Exportar a XML" y súbelo también. Con ese archivo contamos las configuraciones que probaste y el Sharpe deflactado usa el número real.

Para TradingView: en el Probador de estrategias, "Lista de operaciones" > exportar (CSV o XLSX).

No necesito ninguna contraseña ni acceso a tu cuenta.
```

#### W2 · EN · How to export the MetaTrader 5 report

```text
For MetaTrader 5:
1. In the Strategy Tester, once the test finishes, open the "Backtest" (or "Report") tab.
2. Right-click > "Save as Report" and choose HTML. Upload that file as it is, without opening or converting it.
3. If you optimised parameters, right-click in the "Optimization" tab > "Export to XML" and upload it too. That file counts the configurations you tried, so the deflated Sharpe uses the real number.

For TradingView: in the Strategy Tester, "List of trades" > export (CSV or XLSX).

I never need a password or access to your account.
```

#### W3 · ES · Datos de pago

```text
Perfecto. El informe completo cuesta USD 29 (o el paquete de 3 por USD 69).

Puedes pagar por:
- Mercado Pago: <enlace de cobro>
- Transferencia: <datos bancarios>

Cuando vea el pago te mando un código de acceso. Lo escribes en tu informe, en el recuadro "¿Tienes un código de acceso?", y se desbloquea completo, con el simulador de reto, el riesgo remuestreado y la lista de preguntas para el vendedor.

Términos del servicio: https://<dominio>/terminos
```

#### W3 · EN · Payment details

```text
Great. The full report is USD 29 (or a pack of 3 for USD 69).

You can pay by:
- Mercado Pago: <payment link>
- Bank transfer: <bank details>

Once I see the payment I send you an access code. Type it in your report, in the "Have an access code?" box, and the full report unlocks, including the challenge simulator, the resampled risk and the list of questions for the vendor.

Terms of service: https://<domain>/terms
```

#### W4 · ES · Entrega del código

```text
Pago recibido, gracias.

Tu código de acceso: <código>
Sirve para <N> informe(s) y caduca el <fecha>.

Abre el enlace de tu informe (el que guardaste al subir el archivo), escribe el código en "¿Tienes un código de acceso?" y pulsa "Canjear código". Con el botón "Imprimir / guardar PDF" te lo quedas en PDF.

Guarda el código en privado: quien lo tenga puede usarlo. Si algo no carga, respóndeme aquí.
```

#### W4 · EN · Delivering the code

```text
Payment received, thank you.

Your access code: <code>
It covers <N> report(s) and expires on <date>.

Open your report link (the one you saved when uploading), type the code in the "Have an access code?" box and press "Redeem code". The "Print / save PDF" button gives you a PDF copy.

Keep the code private: anyone who has it can use it. If anything does not load, reply here.
```

#### W5 · ES · Seguimiento a los tres días

```text
Hola, <nombre>. ¿Pudiste leer el informe?

Me ayudaría mucho saber dos cosas:
1. ¿Qué parte te resultó más clara y cuál menos?
2. ¿Te parece bien que cite tu opinión en la web con tu nombre o de forma anónima?

La opinión es sobre el informe, no sobre los resultados del robot. Gracias.
```

#### W5 · EN · Follow-up after three days

```text
Hi <name>, were you able to read the report?

Two answers would help me a lot:
1. Which part was clearest, and which was least clear?
2. May I quote your opinion on the website, with your name or anonymously?

The opinion is about the report, not about how the robot performs. Thank you.
```

#### W6 · ES · Cuando el archivo no se puede leer

```text
Gracias por avisar. El archivo no se pudo leer, así que no se creó ninguna auditoría y tu código sigue intacto.

¿Puedes mandarme una captura de la pantalla de error y decirme de qué plataforma y versión sale el archivo? Si es un informe de MT5, prueba a guardarlo de nuevo como HTML desde el Probador de estrategias sin abrirlo en Excel.

Si no se resuelve, te devuelvo el pago.
```

#### W6 · EN · When the file cannot be read

```text
Thanks for letting me know. The file could not be read, so no audit was created and your code is untouched.

Could you send me a screenshot of the error and tell me which platform and version produced the file? If it is an MT5 report, try saving it again as HTML from the Strategy Tester without opening it in Excel.

If it cannot be fixed, I will refund you.
```

### Foros

#### F1 · ES · Hilo en una sección comercial (Forex Factory, clasificados de FPA)

```text
Título: Auditoría estadística de backtests de EA: gratis para los primeros 10 robots públicos

Soy <nombre>, autor de una herramienta que audita backtests (miembro comercial, declaro mi interés).

Qué hace: lees el informe de MT5 o MT4 tal cual, o la lista de operaciones de TradingView, y das una clase de A a D en seis dimensiones: significación estadística, Sharpe deflactado con el número real de intentos (sale del XML de optimización), costes, fuera de muestra, calidad de datos y benchmark. Cada número dice si se midió del archivo, si lo declaró el usuario o si no se pudo medir.

Qué no hace: no se conecta a ningún bróker, no comprueba la cuenta real, no predice resultados y no recomienda comprar ningún robot.

Oferta de lanzamiento: audito gratis el backtest público de 10 robots si el vendedor da su permiso, y publico aquí el informe completo, sea cual sea la clase. Los hashes del archivo permiten que cualquiera repita el cálculo.

Informe de ejemplo con datos sintéticos: https://<dominio>/ejemplo
```

#### F1 · EN · Thread in a commercial section (Forex Factory, FPA classifieds)

```text
Title: Statistical audit of EA backtests: free for the first 10 public robots

I am <name>, the author of a backtest audit tool (commercial member, interest declared).

What it does: it reads the MT5 or MT4 report as exported, or the TradingView list of trades, and gives a class from A to D across six dimensions: statistical significance, deflated Sharpe using the real number of trials (taken from the optimisation XML), costs, out-of-sample, data quality and a benchmark. Every number says whether it was measured from the file, declared by the user, or could not be measured.

What it does not do: it never connects to a broker, it does not check the live account, it does not predict results and it does not recommend buying any robot.

Launch offer: I will audit the public backtest of 10 robots for free if the vendor agrees, and post the full report here, whatever the class. The file hashes let anyone repeat the calculation.

Sample report built from synthetic data: https://<domain>/ejemplo
```

#### F2 · ES · Respuesta útil en un foro, sin enlace

```text
Un backtest con curva perfecta suele ser la mejor de muchas configuraciones probadas. Tres comprobaciones rápidas:

1. ¿Cuántas combinaciones se optimizaron? Si fueron 500, un Sharpe de 2 puede ser pura suerte. El Sharpe deflactado (Bailey y López de Prado) descuenta ese número de intentos.
2. ¿Qué pasa con el doble de spread y comisión? Si la curva se aplana, el margen depende de los costes supuestos.
3. ¿Hay un tramo que no se usó para elegir parámetros? Mira ese tramo por separado.

Y si el robot promedia pérdidas o dobla el lote tras perder, el drawdown flotante no aparece en la curva de balance.
```

#### F2 · EN · Helpful forum answer, no link

```text
A backtest with a perfect curve is usually the best of many tested configurations. Three quick checks:

1. How many combinations were optimised? With 500 of them, a Sharpe of 2 can be pure luck. The deflated Sharpe (Bailey and López de Prado) discounts that number of trials.
2. What happens with double spread and commission? If the curve flattens, the edge depends on the assumed costs.
3. Is there a period that was not used to pick the parameters? Look at that period on its own.

And if the robot averages down or doubles the lot after a loss, the floating drawdown does not show on the balance curve.
```

#### F3 · ES · Entrada de blog (perfil de MQL5, Reddit tras leer sus reglas)

```text
Título: Por qué el XML de optimización cambia la lectura de tu backtest

Cuando optimizas un EA en MT5 y te quedas con la mejor pasada, eliges el máximo de muchas pruebas. Ese máximo es alto aunque ninguna configuración tenga ventaja real.

Ejemplo con datos sintéticos: 120 configuraciones de ruido puro. La mejor muestra un Sharpe que parece bueno; al descontar las 120 pruebas, el Sharpe deflactado ya no es significativo.

Qué hacer:
- Exporta el XML de la pestaña Optimización y guarda cuántas pasadas hiciste.
- Reserva un tramo de fechas que no uses para optimizar.
- Repite la prueba con el doble de costes.

Todo esto es estadística sobre datos pasados: sirve para descartar ilusiones, no para prever el futuro.
```

#### F3 · EN · Blog post (MQL5 profile, Reddit after reading its rules)

```text
Title: Why the optimisation XML changes how you should read your backtest

When you optimise an EA in MT5 and keep the best pass, you pick the maximum of many tests. That maximum is high even when no configuration has a real edge.

Example with synthetic data: 120 configurations of pure noise. The best one shows a Sharpe that looks good; after discounting the 120 tests, the deflated Sharpe is no longer significant.

What to do:
- Export the XML from the Optimization tab and keep count of how many passes you ran.
- Hold back a date range you never use for optimising.
- Rerun the test with double costs.

All of this is statistics on past data: it helps rule out illusions, it does not forecast the future.
```

### Mensajes directos

Solo a quien te pidió información (en un hilo, un comentario o tu WhatsApp).
Nunca en foros que prohíben mensajes comerciales privados (Elite Trader,
Trade2Win, TradingView, MQL5 Freelance).

#### D1 · ES · A un trader de retos que preguntó por la auditoría

```text
Hola, <nombre>. Me preguntaste por la auditoría en <sitio>.

Para retos de prop firm, el informe completo incluye un simulador con los presets de FTMO, FundedNext, The5ers y Topstep: estima, remuestreando tu propio historial, con qué frecuencia se tocaría la pérdida diaria o la total, y con qué frecuencia no se llegaría al objetivo a tiempo. Son estimaciones con sus supuestos escritos, no una predicción del reto.

Puedes probar la vista previa gratis con tu lista de operaciones de TradingView o tu informe de MT5: https://<dominio>
```

#### D1 · EN · To a challenge trader who asked about the audit

```text
Hi <name>, you asked about the audit on <site>.

For prop-firm challenges, the full report includes a simulator with FTMO, FundedNext, The5ers and Topstep presets: by resampling your own history it estimates how often the daily or total loss limit would be hit, and how often the target would not be reached in time. These are estimates with their assumptions written out, not a forecast of the challenge.

You can try the free preview with your TradingView list of trades or your MT5 report: https://<domain>
```

## 5. Propuesta para vendedores de EA

El argumento para un vendedor no es "tu robot sale bien", porque puede salir
C o D. Es este: **los compradores ya desconfían de los backtests, y la página
de verificación les deja comprobar por su cuenta qué archivo se auditó y con
qué resultado, sin que el vendedor enseñe sus operaciones.**

Qué recibe el vendedor:

- El informe completo privado, para mejorar el robot antes de publicarlo.
- Si decide publicarlo, `https://<dominio>/v/{id}`: clase, fecha, las seis
  dimensiones, los hashes SHA-256 de los archivos y el número de intentos
  usado. Nunca muestra archivos, operaciones, descripción ni token.
- El sello `https://<dominio>/v/{id}/badge.svg` para su web, Telegram, hilo
  comercial o vídeos, con el texto fijo "Auditoría estadística de datos
  aportados – no verificados con el bróker – no garantiza resultados"
  (en inglés: "Statistical audit of supplied data – not verified with a
  broker – not a performance guarantee").

Lo que hay que decirle siempre:

- Publicar es opcional y lo decide él. La clase no cambia por pagar ni por
  volver a pedirla.
- El sello no puede ir en la ficha de MQL5 Market (sus reglas prohíben sellos,
  premios de terceros y enlaces externos).
- El sello y la página nunca se usan como promesa de resultados; si lo hace,
  puede retirar la publicación (`unpublish`) y tú puedes negarte a seguir
  trabajando con él.

A quién escribir: vendedores de EA con web propia y un correo o formulario
comercial publicado, uno a uno. Un mensaje, un seguimiento como máximo, y
fuera de la lista si no contesta o pide no recibir más.

#### V1 · ES · Primer contacto con un vendedor de EA

```text
Asunto: Una página pública para que tus compradores comprueben tu backtest

Hola, <nombre>. Vi <nombre del robot> en <sitio>.

Tengo una herramienta que audita backtests de EA a partir del informe de MT5 y del XML de optimización, y da una clase de A a D en seis dimensiones (significación, número de intentos, costes, fuera de muestra, calidad de datos y benchmark).

Si quieres, el resultado se publica en una página de verificación con los hashes del archivo auditado y un sello para tu web o tu Telegram. El sello dice textualmente: "Auditoría estadística de datos aportados – no verificados con el bróker – no garantiza resultados". Así tus compradores comprueban qué archivo se auditó sin que enseñes tus operaciones.

La primera auditoría es gratis; la publicación es opcional y la decides tú después de ver el informe. Ejemplo con datos sintéticos: https://<dominio>/ejemplo

Si no te interesa, dímelo y no vuelvo a escribirte.
<tu nombre>
```

#### V1 · EN · First contact with an EA vendor

```text
Subject: A public page where your buyers can check your backtest

Hi <name>, I saw <robot name> on <site>.

I run a tool that audits EA backtests from the MT5 report and the optimisation XML, and gives a class from A to D across six dimensions (significance, number of trials, costs, out-of-sample, data quality and benchmark).

If you want, the result is published on a verification page with the hashes of the audited file and a badge for your website or Telegram. The badge says, word for word: "Statistical audit of supplied data – not verified with a broker – not a performance guarantee". Your buyers can then check which file was audited without you showing your trades.

The first audit is free; publishing is optional and you decide after reading the report. Sample built from synthetic data: https://<domain>/ejemplo

If this is not for you, just say so and I will not write again.
<your name>
```

#### V2 · ES · Cuando el vendedor ya tiene su informe

```text
Hola, <nombre>. Tu informe está listo: <enlace del informe>

Si quieres publicarlo, pulsa "Publicar verificación pública" al final del informe. Obtendrás:
- La página: https://<dominio>/v/<id>
- El sello: https://<dominio>/v/<id>/badge.svg y el código para pegarlo en tu web o Telegram.

El sello dice "Auditoría estadística de datos aportados – no verificados con el bróker – no garantiza resultados". Úsalo junto a ese texto, nunca como promesa de resultados, y recuerda que MQL5 Market no admite sellos de terceros en la ficha.

Puedes retirar la publicación cuando quieras desde el mismo informe.
```

#### V2 · EN · When the vendor has their report

```text
Hi <name>, your report is ready: <report link>

To publish it, press "Publish a public verification" at the bottom of the report. You get:
- The page: https://<domain>/v/<id>
- The badge: https://<domain>/v/<id>/badge.svg and the code to paste it on your website or Telegram.

The badge says "Statistical audit of supplied data – not verified with a broker – not a performance guarantee". Show it with that wording, never as a promise of results, and note that MQL5 Market does not allow third-party badges on product pages.

You can unpublish at any time from the same report.
```

## 6. De primer mensaje a informe entregado

Objetivo: contestar el mismo día y que el cliente vea su vista previa antes
de pagar.

| Paso | Qué haces | Plantilla o comando |
|---|---|---|
| 1. Primer mensaje | Saluda, explica en tres líneas y manda a subir el archivo y a ver `/ejemplo`. | W1 |
| 2. No sabe exportar | Instrucciones de su plataforma. | W2 |
| 3. Sube el archivo | El cliente ve la vista previa gratis y guarda el enlace de su informe (lleva el token). | — |
| 4. Quiere el completo | Datos de pago y enlace a los términos. | W3 |
| 5. Paga | Confirma el pago en tu banco o Mercado Pago antes de nada. Luego, en `railway ssh`: `quant-trade audit codes create --credits 1 --note "<nombre> MP <referencia> <fecha>" --expires-days 90`. El código se muestra una sola vez. | — |
| 6. Entrega | Envía el código por WhatsApp y nada más por ningún otro canal. | W4 |
| 7. Canje | El cliente escribe el código en su informe y lo desbloquea; puede guardarlo en PDF. | — |
| 8. Si falla | Si el archivo no se lee, no se crea auditoría y el código queda intacto. Si hace falta, desactiva el código (`quant-trade audit codes disable <id>`) y devuelve el pago. | W6 |
| 9. Vendedor | Si es vendedor, explica cómo publicar la verificación. | V2 |
| 10. Seguimiento | A los tres días, pide opinión sobre el informe. | W5 |

Reglas de trato:

- El cliente sube su archivo él mismo. Si te lo manda por WhatsApp, pídele
  que lo suba; si no puede, súbelo tú y borra la copia de tu teléfono. Nunca
  guardes archivos de clientes fuera del servicio ni en el repositorio.
- En la nota del código pon nombre de pila y referencia del pago, nada más:
  ni teléfono, ni correo, ni el código.
- No des opiniones de compra ("cómpralo", "no lo compres") ni de operativa.
  Si preguntan, remite al informe y a la lista de preguntas para el vendedor.
- Si alguien pide cambiar la clase, la respuesta es no: el resultado es
  reproducible por hash y lo decide el motor.
- Las opiniones que publiques hablan del informe (claridad, rapidez), nunca
  de resultados de trading.
- Retención: pon `AUDIT_AUTO_PURGE=true` en Railway y el servicio borra solo
  los archivos no pagados a diario (a mano: `quant-trade audit purge --days
  30 --yes`). Las páginas de verificación publicadas y sus sellos siguen
  funcionando después.

Hoja de ventas (una fila por venta, sin datos sensibles): fecha, nombre de
pila, canal por el que llegó, importe, medio de pago, referencia, id del
código, id de la auditoría, clase, ¿publicó verificación?, opinión.

## 7. Plan semanal y qué medir

| Semana | Qué hacer | Meta |
|---|---|---|
| 1 | Checklist de la sección 1. Perfil de MQL5 completo, primera entrada de blog (F3). Cinco respuestas útiles (F2) en el foro español de MQL5 y en Rankia, sin enlaces. | 10 conversaciones de WhatsApp; 10 auditorías gratis con archivo real. |
| 2 | Hilo en Commercial Content de Forex Factory (F1) si la membresía comercial encaja. 10 vendedores de EA contactados uno a uno (V1). | 3 vendedores con informe; 1 verificación publicada. |
| 3 | Pasa a USD 29. Segunda entrada de blog con lo aprendido en las auditorías gratis (sin nombrar robots sin permiso). Revisa las reglas de Reddit y publica una entrada de método si lo permiten. | Primeras 3 ventas. |
| 4 | Revisa los números y decide: más contenido, clasificados de FPA o un anuncio de pago pequeño. Paquete de 3 para quien compare robots. | 5 ventas; 3 opiniones publicables. |

Qué medir cada semana, en la hoja de ventas:

- Conversaciones nuevas y de qué canal vienen.
- Vistas previas creadas (cuántos llegaron a subir un archivo).
- Ventas y conversión vista previa → venta.
- Archivos que fallaron al leerse y de qué plataforma (son fallos a
  corregir en `audit/importers.py`).
- Verificaciones publicadas y visitas que llegan desde un sello.

Si en cuatro semanas casi nadie sube un archivo, el problema está en el
mensaje o en el canal; si suben pero no pagan, en el precio o en lo que
enseña la vista previa. Vuelve a esta guía y cambia una sola cosa cada vez.

## Límites de esta guía

- Las reglas de las comunidades cambian. Las marcadas como "fragmento" o
  "sin comprobar" deben leerse en un navegador antes de publicar.
- No se publicó, registró ni envió nada al preparar esta guía.
- Los precios salen de la comparación con competidores del 2026-09-24 y de la
  recomendación del hilo de QA; no hay todavía datos de ventas reales.
- Los importadores no se han probado con informes reales de clientes.
- La normativa sobre publicidad de servicios financieros y correos
  comerciales varía por país; consulta a un abogado antes de escribir en
  frío a vendedores fuera de tu país.
