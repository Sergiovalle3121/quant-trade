# Plan de lanzamiento de Rigor: las primeras 10 ventas

Guía práctica para vender a mano los primeros informes de Rigor
(https://rigor.up.railway.app, código en `src/quant_trade/audit/`). Hoy el
cliente paga por transferencia, Mercado Pago o el medio que acuerdes por
WhatsApp y recibe un código de acceso; el pago con tarjeta se enciende solo
cuando las claves de Stripe estén en Railway. Primera versión: 2026-09-24.
Puesta al día: 2026-09-25.

Qué cambió respecto a la primera versión:

- El servicio se llama Rigor y tiene más secciones (lista en "Qué vendes").
- **No hay auditorías gratis.** El dueño lo pidió así ("antes de dar pruebas
  gratis necesito vender algo bien"). Lo gratis es la vista previa que
  cualquiera ve al subir su archivo; el informe completo se paga desde el
  primer cliente.
- La razón de regalar las primeras auditorías era que los importadores no se
  habían probado con archivos reales. Ya se probaron con 39 archivos reales
  públicos (MetaTrader en 7 idiomas, Myfxbook, señales de MQL5, FX Blue y
  TradingView): ver `docs/research/audit_iteration4/real_reports_check.md`,
  `mt_languages_check.md` y `tracking_exports_check.md`. Y si un informe lee
  mal el archivo, se devuelve el importe.
- Los códigos se crean desde el navegador en `/panel`; ya no hace falta
  `railway ssh`.
- Se añaden un canal (tus propios contactos) y dos plantillas: P1 y D2.

Qué contiene:

1. Qué vendes y a qué precio.
2. Qué tener listo antes del primer mensaje.
3. Dónde están los compradores y qué permite cada comunidad.
4. Los canales, en el orden en que conviene usarlos.
5. Plantillas de mensajes en español e inglés, listas para copiar.
6. La propuesta para vendedores de robots (EA): página de verificación y sello.
7. Cómo atender a un cliente desde el primer mensaje hasta el informe entregado.
8. Plan de las primeras semanas y qué medir.

## Regla que manda sobre todo lo demás

Rigor mide la evidencia estadística de un archivo. No predice resultados, no
recomienda comprar ni vender un robot y no dice que alguien vaya a superar un
reto de prop firm. Esa regla vale igual para cada mensaje que envíes
(AGENTS.md, sección Phase 16):

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
- Nunca te hagas pasar por cliente ni pidas a otros que lo hagan. Forex
  Factory y Forex Peace Army expulsan por eso, y basta un caso para perder la
  confianza que vende este servicio.

`tests/test_audit_launch_playbook.py` pasa el guard sobre este documento y
sobre cada plantilla, y comprueba que ninguna plantilla ofrece auditorías
gratis. Si editas una plantilla, ejecuta
`python -m pytest tests/test_audit_launch_playbook.py -q` antes de usarla.

## 1. Qué vendes y a qué precio

Un informe que responde, con el archivo que el cliente ya tiene, a la
pregunta que se hace antes de arriesgar dinero en un robot o en una cuenta
ajena: ¿este resultado es evidencia o es suerte, sobreajuste y costes mal
contados? Cada número dice si se midió del archivo (MEASURED), si lo declaró
el cliente o su plataforma (DECLARED) o si no se pudo medir (NOT_MEASURED).

Lo que ve gratis, al subir el archivo: la clase de A a D, las gráficas, las
banderas rojas, la lectura de su archivo (operaciones y resultado recontados
frente a lo que dice la plataforma) y qué significa cada dimensión.

Lo que desbloquea el informe completo (casi todo se ve en `/ejemplo`):

- Resumen ejecutivo, qué pide cada clase y plan para subir de clase.
- Sharpe deflactado con el número real de intentos (del XML de optimización
  de MT5) y "¿Pico aislado o meseta?" con las pasadas vecinas.
- Pruebas de estrés: el resultado sin sus mejores operaciones y meses.
- "Con qué datos se hizo la prueba": modelo de ticks y calidad del historial
  del probador de MT4 y MT5.
- "¿Sigue funcionando en el periodo reciente?" y "¿Aguanta en el periodo
  forward?".
- "Cuándo gana y cuándo pierde" (día y hora) y "Cómo se comporta al perder".
- Riesgo remuestreado a un año y "Qué capital necesita y a qué tamaño".
- Simulador de 16 retos de prop firm (FTMO, FundedNext, The5ers, Topstep),
  con las reglas leídas en la web de cada firma y su fecha.
- Para quien va a copiar o invertir: "Backtest frente a cuenta real"
  (la cuenta frente a miles de historias remuestreadas de su backtest y
  operación por operación en las mismas fechas) y "El dinero real de la
  cuenta" (depósitos y retiros separados del resultado de operar).
- Preguntas para hacerle al vendedor, PDF del informe, comparación de
  informes (`/comparar`), página de verificación pública con sello y
  `/comprobar`, donde cualquiera confirma por SHA-256 que un PDF salió de
  Rigor.

Lee 11 formatos tal cual: MetaTrader 5 y 4 (en 7 idiomas), TradingView,
NinjaTrader, QuantConnect, backtesting.py, vectorbt, Myfxbook, FX Blue, señales
de MQL5 y CSV.

### Precios

Comparación con competidores (`docs/research/audit_iteration4/market_competitors.json`
y fuentes públicas del 2026-09-25): EA Verdict USD 19, EA X-Ray EUR 29,
AntiOverfit EUR 97, ErgodicLabs Edge Matrix USD 29 por 25 análisis (sin
comprobar).

| Oferta | Precio | Cuándo |
|---|---|---|
| Vista previa | Gratis, siempre | Clase, gráficas, banderas rojas, lectura del archivo y explicación de cada dimensión. |
| Informe completo | USD 29 (`AUDIT_PRICE_USD_CENTS=2900`) | Desde el primer cliente. |
| Paquete de 3 | USD 69 (`AUDIT_PACK_PRICE_USD_CENTS=6900`, código con 3 créditos) | Para quien compara varios robots, versiones o un backtest y su cuenta. |
| Devolución | El importe de ese informe | Si el informe lee mal el archivo (operaciones, saldo o fechas) y no se puede corregir. |
| Informe completo | USD 49 | Solo cuando haya opiniones publicables de clientes reales. |

La vista previa es el anzuelo: el cliente ve la clase y las gráficas de su
propio archivo antes de pagar. Mándalo siempre a subir primero y a pagar
después. No regales el informe completo para conseguir una opinión: la
devolución por archivo mal leído ya quita el riesgo al primer comprador.

## 2. Antes del primer mensaje

Hecho (comprobado en `/health` el 2026-09-25): servicio en Railway con
Postgres, `AUDIT_ACCESS_CODES=true`, `AUDIT_FREE_MODE=false`, precio USD 29,
borrado automático, datos del operador en `/terminos` y enlace de WhatsApp en
el botón "Pedir un código".

Solo tú puedes hacer lo que falta:

- [ ] Crear un código de 1 crédito en `https://rigor.up.railway.app/panel`
      (con tu `AUDIT_ADMIN_KEY`, que está en Railway > Variables), canjearlo
      en un informe tuyo y desactivarlo. Así sabes hacerlo antes de que pague
      nadie.
- [ ] Tener a mano cómo cobrar: un enlace de Mercado Pago, tus datos de
      transferencia o PayPal. Escríbelos en la plantilla W3.
- [ ] WhatsApp Business con mensaje de bienvenida, horario y un catálogo con
      un producto: "Informe completo de Rigor, USD 29".
- [ ] Una hoja de cálculo de ventas (columnas en la sección 7).
- [ ] Preguntar a un contador cómo facturar este servicio en México, y que un
      abogado lea `/terminos` y `/privacidad` cuando puedas.
- [ ] Opcional: las claves de Stripe en Railway, para que se pueda pagar con
      tarjeta sin escribirte. Hasta entonces, todo pasa por WhatsApp.

## 3. Dónde están los compradores

Cinco grupos compran este informe:

- **Compradores de EA**: quieren saber si el backtest que les enseña un
  vendedor es sobreajuste antes de pagar el robot.
- **Traders de retos de prop firm**: quieren conocer el drawdown remuestreado
  y las reglas de pérdida diaria de su estrategia antes de pagar el reto.
- **Vendedores de EA**: quieren una evidencia estadística pública que el
  comprador pueda comprobar por hash.
- **Traders de acciones, futuros o cripto con estrategia propia**: quieren
  saber si su ventaja es real o la encontraron a fuerza de probar.
- **Quien va a copiar o invertir con otro trader**: quiere saber si la cuenta
  se parece al backtest y si el porcentaje se infla con depósitos.

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

## 4. Los canales, en orden

Meta: 10 ventas pagadas. Empieza por donde ya te conocen y sigue por donde
una sola venta trae a otros compradores.

1. **Tus propios contactos y los grupos de trading donde ya participas.**
   Es lo más rápido y no cuesta nada. Escribe uno a uno a quien sabes que usa
   robots, opera retos de prop firm o copia a otro trader (plantilla P1), y
   publica el mismo texto en tu estado de WhatsApp. En un grupo, publica solo
   si sus reglas permiten ofrecer servicios; si no, pregunta antes al
   administrador. Nunca a desconocidos por privado.
2. **Vendedores de EA de habla hispana**, a través del correo o formulario
   comercial que publican en su propia web, uno a uno y personalizado
   (plantillas V1 y V2). El vendedor paga su informe como cualquier cliente;
   lo que gana a cambio es una página de verificación y un sello que sus
   compradores pueden comprobar. Cada vendedor que publica su sello trae a
   sus compradores a `/v/{id}` y a la portada. Un mensaje y un seguimiento
   como máximo.
3. **Contenido en español en el blog de tu perfil de MQL5, más respuestas
   útiles en el foro español de MQL5 y en Rankia.** Los moderadores de MQL5
   mandan la promoción al blog del perfil. Publica una entrada por semana
   (plantilla F3) y contesta en los foros sin enlaces (plantilla F2). Es lento
   pero acumula: la gente mira tu perfil y ahí está la web.
4. **Hilo en "Commercial Content" de Forex Factory**, como Commercial Member
   con identidad pública (plantilla F1). Es el mayor punto de encuentro de
   compradores y vendedores de EA en inglés. Comprueba antes, en un
   navegador, si la membresía comercial tiene coste y qué exige.

5. **Traders de acciones, futuros y cripto que programan o prueban sus
   estrategias** (plantillas F2, F3 y D3). Rigor no depende del mercado, así
   que el mismo contenido sirve fuera del mundo de los robots de MetaTrader:
   el foro de la comunidad de QuantConnect, r/algotrading y los subreddits de
   cripto y futuros, siempre tras leer sus reglas (casi todos retiran enlaces
   a productos; ahí se aporta método, y la web va en el perfil). En
   TradingView no se promociona nada, ni por privado.

Después, cuando haya opiniones reales: Forex Peace Army (clasificados),
Reddit (entradas de método, tras leer las reglas de cada subreddit) y un
anuncio de pago si los números de la sección 8 lo justifican.

## 5. Plantillas

Cambia lo que va entre `<…>` antes de enviar. `<dominio>` es
`rigor.up.railway.app` (o el valor de `AUDIT_BASE_URL` si cambia). No añadas
frases sobre resultados futuros: cada plantilla pasa el guard tal como está.

### Tus contactos

#### P1 · ES · A un conocido que opera con robots, retos o cuentas ajenas

```text
Hola, <nombre>. Te escribo porque sé que <operas acciones o cripto con tu estrategia / usas robots / estás con retos de prop firm / inviertes con un gestor>.

Lancé Rigor, un servicio que audita backtests e historiales de cuenta: subes el informe de MetaTrader, TradingView, Myfxbook o tu plataforma tal cual, o tu curva de equity de cualquier mercado, y te dice con estadística si el resultado se sostiene o si es sobreajuste, costes mal contados o suerte. Da una clase de A a D, y cada número dice si se midió del archivo o si solo lo declaró la plataforma.

También compara un backtest con la cuenta real donde corre el robot y separa los depósitos del resultado de operar, que es donde más se maquilla un historial.

La vista previa es gratis: https://<dominio>
El informe completo cuesta USD 29, o USD 69 el paquete de 3. Si lee mal tu archivo, te devuelvo el importe.

Ejemplo completo: https://<dominio>/ejemplo
Si te sirve o conoces a alguien a quien le sirva, me ayudas mucho. Si no, no pasa nada.
```

#### P1 · EN · To someone you know who trades with robots, challenges or other people's accounts

```text
Hi <name>, I am writing because I know you <trade stocks or crypto with your own strategy / use trading robots / are doing prop-firm challenges / invest with a manager>.

I launched Rigor, a service that audits backtests and account histories: you upload the MetaTrader, TradingView, Myfxbook or other platform report as it is, or your equity curve from any market, and it tells you, with statistics, whether the result holds up or is overfitting, miscounted costs or luck. It gives a class from A to D, and every number says whether it was measured from the file or only declared by the platform.

It also compares a backtest with the live account the robot runs on, and separates deposits from trading results, which is where a history is most often dressed up.

The preview is free: https://<domain>
The full report is USD 29, or USD 69 for a pack of 3. If it misreads your file, I refund you.

Full sample: https://<domain>/ejemplo
If it is useful to you or someone you know, that helps me a lot. If not, no problem.
```

### WhatsApp

#### W1 · ES · Respuesta al primer mensaje

```text
¡Hola, <nombre>! Gracias por escribir.

Rigor analiza el backtest o el historial de cuenta que ya tienes y le da una clase de A a D en seis dimensiones: significación estadística, número de intentos (Sharpe deflactado), costes, fuera de muestra, calidad de datos y benchmark. Además revisa con qué datos se hizo la prueba, si el resultado depende de pocas operaciones, si sigue funcionando en el periodo reciente y qué capital pide.

Cómo empezar:
1. Sube tu archivo en https://<dominio> tal cual sale de tu plataforma (MT5, MT4, TradingView, NinjaTrader, Myfxbook, FX Blue, señales de MQL5, QuantConnect, backtesting.py o vectorbt).
2. La vista previa es gratis: ves la clase, las gráficas, las banderas rojas y qué significa cada dimensión.
3. Si quieres el informe completo, cuesta USD 29 (o USD 69 el paquete de 3) y te mando un código de acceso.

Aquí tienes un informe de ejemplo con datos sintéticos: https://<dominio>/ejemplo

Es un análisis estadístico de los datos que subes; no predice resultados ni recomienda operar.
```

#### W1 · EN · Reply to the first message

```text
Hi <name>, thanks for getting in touch.

Rigor analyses the backtest or account history you already have and gives it a class from A to D across six dimensions: statistical significance, number of trials (deflated Sharpe), costs, out-of-sample, data quality and a benchmark. It also checks what data the test used, whether the result rests on a few trades, whether it still works in the recent period and how much capital it needs.

How to start:
1. Upload your file at https://<domain> exactly as your platform exports it (MT5, MT4, TradingView, NinjaTrader, Myfxbook, FX Blue, MQL5 signals, QuantConnect, backtesting.py or vectorbt).
2. The preview is free: you see the class, the charts, the red flags and what each dimension means.
3. If you want the full report, it is USD 29 (or USD 69 for a pack of 3) and I send you an access code.

Here is a sample report built from synthetic data: https://<domain>/ejemplo

It is a statistical analysis of the data you upload; it does not predict results or recommend trading.
```

#### W2 · ES · Cómo exportar el informe

```text
Para MetaTrader 5:
1. En el Probador de estrategias, al terminar la prueba, abre la pestaña "Backtest" (o "Informe").
2. Clic derecho > "Guardar como informe" y elige HTML. Sube ese archivo tal cual, sin abrirlo ni convertirlo.
3. Si optimizaste parámetros, en la pestaña "Optimización" haz clic derecho > "Exportar a XML" y súbelo también. Con ese archivo contamos las configuraciones que probaste y el Sharpe deflactado usa el número real.

Para la cuenta donde corre el robot: en MetaTrader, pestaña "Historial" > clic derecho > "Informe" (HTML), o el CSV que exporta Myfxbook, FX Blue o la señal de MQL5. Súbelo en "Estado de cuenta real o demo".

Para TradingView: en el Probador de estrategias, "Lista de operaciones" > exportar (CSV o XLSX).

Hay una guía corta para cada plataforma en https://<dominio>/guias
No necesito ninguna contraseña ni acceso a tu cuenta.
```

#### W2 · EN · How to export the report

```text
For MetaTrader 5:
1. In the Strategy Tester, once the test finishes, open the "Backtest" (or "Report") tab.
2. Right-click > "Save as Report" and choose HTML. Upload that file as it is, without opening or converting it.
3. If you optimised parameters, right-click in the "Optimization" tab > "Export to XML" and upload it too. That file counts the configurations you tried, so the deflated Sharpe uses the real number.

For the account the robot runs on: in MetaTrader, "History" tab > right-click > "Report" (HTML), or the CSV that Myfxbook, FX Blue or the MQL5 signal exports. Upload it under "Live or demo account statement".

For TradingView: in the Strategy Tester, "List of trades" > export (CSV or XLSX).

There is a short guide for each platform at https://<domain>/guides
I never need a password or access to your account.
```

#### W3 · ES · Datos de pago

```text
Perfecto. El informe completo cuesta USD 29 (o el paquete de 3 por USD 69).

Puedes pagar por:
- <Mercado Pago: enlace de cobro>
- <Transferencia: datos bancarios>

Cuando vea el pago te mando un código de acceso. Lo escribes en tu informe, en el recuadro "¿Tienes un código de acceso?", y se desbloquea completo: pruebas de estrés, riesgo y capital, simulador de reto, cuenta real frente al backtest si la subiste, preguntas para el vendedor y el PDF.

Si el informe lee mal tu archivo y no se puede corregir, te devuelvo el importe.
Términos del servicio: https://<dominio>/terminos
```

#### W3 · EN · Payment details

```text
Great. The full report is USD 29 (or a pack of 3 for USD 69).

You can pay by:
- <Mercado Pago: payment link>
- <Bank transfer: bank details>

Once I see the payment I send you an access code. Type it in your report, in the "Have an access code?" box, and the full report unlocks: stress tests, risk and capital, the challenge simulator, the live account against the backtest if you uploaded it, questions for the vendor and the PDF.

If the report misreads your file and it cannot be fixed, I refund you.
Terms of service: https://<domain>/terms
```

#### W4 · ES · Entrega del código

```text
Pago recibido, gracias.

Tu código de acceso: <código>
Sirve para <N> informe(s).

Abre el enlace de tu informe (el que guardaste al subir el archivo), escribe el código en "¿Tienes un código de acceso?" y pulsa "Canjear código". Con el botón del PDF te lo quedas en tu equipo, y en https://<dominio>/comprobar cualquiera puede confirmar que ese PDF salió de Rigor.

Guarda el código en privado: quien lo tenga puede usarlo. Si algo no carga, respóndeme aquí.
```

#### W4 · EN · Delivering the code

```text
Payment received, thank you.

Your access code: <code>
It covers <N> report(s).

Open your report link (the one you saved when uploading), type the code in the "Have an access code?" box and press "Redeem code". The PDF button gives you a copy, and anyone can confirm at https://<domain>/check that the PDF came from Rigor.

Keep the code private: anyone who has it can use it. If anything does not load, reply here.
```

#### W5 · ES · Seguimiento a los tres días

```text
Hola, <nombre>. ¿Pudiste leer el informe?

Me ayudaría mucho saber dos cosas:
1. ¿Qué parte te resultó más clara y cuál menos?
2. ¿Te parece bien que cite tu opinión en la web con tu nombre o de forma anónima?

La opinión es sobre el informe, no sobre los resultados del robot. Y si conoces a alguien que esté por comprar un robot o copiar una cuenta, pásale el enlace. Gracias.
```

#### W5 · EN · Follow-up after three days

```text
Hi <name>, were you able to read the report?

Two answers would help me a lot:
1. Which part was clearest, and which was least clear?
2. May I quote your opinion on the website, with your name or anonymously?

The opinion is about the report, not about how the robot performs. And if you know someone about to buy a robot or copy an account, please pass on the link. Thank you.
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
Título: Rigor: auditoría estadística de backtests e historiales de EA (MT4, MT5, Myfxbook)

Soy <nombre>, autor de Rigor (miembro comercial, declaro mi interés).

Qué hace: lee el informe de MT5 o MT4 tal cual (en 7 idiomas), el XML de optimización, la lista de operaciones de TradingView, el CSV de Myfxbook, FX Blue o una señal de MQL5, o el historial de otras 21 plataformas (Interactive Brokers, Tradovate, cTrader, Rithmic, Binance y más; si no reconoce las columnas, te pregunta qué es cada una), y da una clase de A a D en seis dimensiones: significación estadística, Sharpe deflactado con el número real de intentos, costes, fuera de muestra, calidad de datos y benchmark. Cada número dice si se midió del archivo, si lo declaró la plataforma o si no se pudo medir.

También: el resultado sin sus mejores operaciones, el modelo de ticks del probador, si la mejor pasada es un pico aislado o una meseta, si el periodo reciente se parece al resto, y una cuenta real frente a miles de historias remuestreadas de su propio backtest, con los depósitos separados del resultado de operar.

Qué no hace: no se conecta a ningún bróker, no predice resultados y no recomienda comprar ningún robot.

Con una cuenta gratis, el primer informe completo no se paga; después, 3 vistas previas gratis al mes y USD 29 por informe completo, que se devuelven si lee mal el archivo. Los vendedores pueden publicar una página de verificación con los hashes del archivo auditado.

Informe de ejemplo con datos sintéticos: https://<dominio>/ejemplo
Cómo audita, con cada umbral: https://<dominio>/metodologia
```

#### F1 · EN · Thread in a commercial section (Forex Factory, FPA classifieds)

```text
Title: Rigor: statistical audit of EA backtests and account histories (MT4, MT5, Myfxbook)

I am <name>, the author of Rigor (commercial member, interest declared).

What it does: it reads the MT5 or MT4 report as exported (in 7 languages), the optimisation XML, the TradingView list of trades, the Myfxbook, FX Blue or MQL5 signal CSV, or the history from 21 other platforms (Interactive Brokers, Tradovate, cTrader, Rithmic, Binance and more; if it does not recognise the columns, it asks what each one is), and gives a class from A to D across six dimensions: statistical significance, deflated Sharpe using the real number of trials, costs, out-of-sample, data quality and a benchmark. Every number says whether it was measured from the file, declared by the platform, or could not be measured.

Also: the result without its best trades, the tester's tick model, whether the best pass is an isolated peak or a plateau, whether the recent period looks like the rest, and a live account compared with thousands of resampled histories of its own backtest, with deposits separated from trading results.

What it does not do: it never connects to a broker, it does not predict results and it does not recommend buying any robot.

A free account gets its first full report free; after that, 3 free previews a month and USD 29 per full report, refunded if it misreads the file. Vendors can publish a verification page with the hashes of the audited file.

Sample report built from synthetic data: https://<domain>/ejemplo
How it audits, with every threshold: https://<domain>/methodology
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
- Mira si las pasadas vecinas a la elegida también salen bien (meseta) o si la tuya está sola (pico aislado).
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
- Check whether the passes next to the chosen one also do well (a plateau) or whether yours stands alone (an isolated peak).
- Hold back a date range you never use for optimising.
- Rerun the test with double costs.

All of this is statistics on past data: it helps rule out illusions, it does not forecast the future.
```

F4 a F7 sirven solos, sin enlace: publícalos como respuesta cuando alguien
pregunte por un backtest, un robot, un reto o un gestor. El objetivo es que se
vea trabajo real. Solo donde las reglas del foro lo permitan añade al final
«Hice una herramienta que hace estas cuentas con tu archivo: <enlace>», y di
que es tuya.

#### F4 · ES · Explicación con números: cuánto Sharpe da la suerte sola

```text
Título: ¿Cuánto Sharpe sale por pura suerte? Números que puedes repetir en casa

Genera 200 estrategias de ruido puro: rendimientos diarios aleatorios con media cero, tres años de datos (756 días). Ninguna tiene ventaja. Calcula el Sharpe anualizado de cada una y quédate con la mejor.

Repitiendo el experimento 400 veces, la mejor de 200 tiene un Sharpe de alrededor de 1,6. Con 20 estrategias, la mejor ronda 1,1. Coincide con la fórmula del máximo esperado de Bailey y López de Prado: raíz(1/T) multiplicada por un término que crece con el número de pruebas.

Qué significa: si optimizaste 200 combinaciones y la mejor muestra Sharpe 1,5 en tres años, ese número por sí solo no distingue ventaja de suerte. Lo que ayuda:
- Anota cuántas pruebas hiciste de verdad, incluidas las que borraste.
- Compara el Sharpe de la elegida con el que daría la suerte con ese número de pruebas (Sharpe deflactado).
- Mira el tramo que no usaste para elegir.

El código son diez líneas de numpy; si quieres lo pego. Es estadística sobre datos pasados: descarta ilusiones, no prevé el futuro.
```

#### F4 · EN · Explainer with numbers: how much Sharpe luck alone gives

```text
Title: How much Sharpe comes from luck alone? Numbers you can repeat at home

Generate 200 pure-noise strategies: random daily returns with zero mean, three years of data (756 days). None has an edge. Compute each one's annualised Sharpe and keep the best.

Repeating the experiment 400 times, the best of 200 has a Sharpe of about 1.6. With 20 strategies, the best is around 1.1. That matches the expected-maximum formula from Bailey and López de Prado: sqrt(1/T) times a term that grows with the number of trials.

What it means: if you optimised 200 combinations and the best shows Sharpe 1.5 over three years, that number alone cannot tell an edge from luck. What helps:
- Write down how many trials you really ran, including the ones you deleted.
- Compare the chosen Sharpe with what luck would give for that number of trials (the deflated Sharpe).
- Look at the period you did not use to choose.

The code is ten lines of numpy; I can paste it if you like. It is statistics on past data: it rules out illusions, it does not forecast the future.
```

#### F5 · ES · Antes de comprar un EA o copiar una señal: cinco preguntas

```text
Antes de pagar por un robot o copiar una señal, cinco preguntas que se responden con el historial, no con la publicidad:

1. ¿El porcentaje viene de operar o de depósitos? Una recarga en mitad del historial cambia el crecimiento mostrado. Pide la lista de depósitos y retiros.
2. ¿Cuál fue el drawdown flotante, no solo el de balance? Un robot que promedia pérdidas puede tener una curva de balance lisa y una cuenta que estuvo al borde.
3. ¿Cuántas operaciones y cuántos meses hay? Treinta operaciones en tres buenos meses dicen poco.
4. ¿Qué queda si quitas las cinco mejores operaciones? Si el resultado cambia de signo, depende de muy pocos días.
5. ¿La cuenta real se parece a su backtest? Si la real va muy por debajo, el backtest no describía lo que pasa en vivo.

Nada de esto prevé el futuro; sirve para no confundir una buena racha con una ventaja.
```

#### F5 · EN · Before buying an EA or copying a signal: five questions

```text
Before paying for a robot or copying a signal, five questions the history answers, not the advertising:

1. Does the percentage come from trading or from deposits? A top-up in the middle of the history changes the growth shown. Ask for the list of deposits and withdrawals.
2. What was the floating drawdown, not just the balance one? A robot that averages down can show a smooth balance curve on an account that came close to the edge.
3. How many trades and how many months are there? Thirty trades in three good months say little.
4. What is left without the five best trades? If the result changes sign, it rests on very few days.
5. Does the live account look like its backtest? If live runs far below, the backtest did not describe what happens live.

None of this forecasts the future; it helps you not mistake a good streak for an edge.
```

#### F6 · ES · Antes de pagar un reto de prop firm

```text
Antes de pagar otro reto, puedes medir con tu propio historial qué regla te frena. Tres cuentas sencillas:

1. Pérdida diaria: busca en tu historial el peor día y los cinco peores. Compáralos con el límite diario del reto, calculado sobre el saldo inicial o sobre el máximo del día, según la firma.
2. Pérdida total: mira el peor tramo de pico a valle. Si ya se acerca al límite, una mala racha normal basta para tocarlo.
3. Regla del mejor día (consistencia): divide tu mejor día entre el resultado total. Algunas firmas frenan el retiro si ese día pesa demasiado.

Mejor todavía: remuestrea tus operaciones miles de veces y cuenta en qué porcentaje de las historias tocarías cada límite. Eso dice qué reto encaja con tu forma de operar, no si te irá bien.

Las reglas cambian; léelas en la web de la firma el día que pagas.
```

#### F6 · EN · Before paying for a prop firm challenge

```text
Before paying for another challenge, you can measure with your own history which rule stops you. Three simple checks:

1. Daily loss: find your worst day and your five worst days. Compare them with the challenge's daily limit, computed from the starting balance or from the day's high, depending on the firm.
2. Maximum loss: look at your worst peak-to-trough stretch. If it already comes close to the limit, an ordinary bad streak is enough to hit it.
3. Best-day rule (consistency): divide your best day by the total result. Some firms hold the payout if that day weighs too much.

Better still: resample your trades thousands of times and count in what share of the histories you would hit each limit. That tells you which challenge fits the way you trade, not whether it will go well.

Rules change; read them on the firm's site on the day you pay.
```

#### F7 · ES · Para quien evalúa un gestor o un fondo por su tabla mensual

```text
Si te enseñan una tabla de rentabilidades mensuales de un gestor o un fondo, cuatro preguntas antes de fiarte:

1. ¿Cuántos meses hay? Con 24 meses, un Sharpe alto tiene un margen de error muy ancho. Calcula el intervalo, no solo el número.
2. ¿Los meses son netos de comisiones? Una comisión de gestión y otra de éxito pueden cambiar bastante el resultado del inversor.
3. ¿Cómo le fue en los meses de crisis del mercado (marzo de 2020, 2022)? Un historial que empieza después no dice cómo se porta en una caída.
4. ¿Contra qué se compara? Un año del +12 % se lee distinto si el índice de referencia hizo +25 % o −10 %.

Nada de esto juzga al gestor; separa lo que el historial demuestra de lo que solo sugiere.
```

#### F7 · EN · For someone judging a manager or a fund by its monthly table

```text
If someone shows you a table of monthly returns for a manager or a fund, four questions before you rely on it:

1. How many months are there? With 24 months, a high Sharpe has a very wide margin of error. Compute the interval, not just the number.
2. Are the months net of fees? A management fee plus a performance fee can change the investor's result a lot.
3. How did it do in the market's crisis months (March 2020, 2022)? A history that starts afterwards says nothing about how it behaves in a fall.
4. What is it compared with? A +12 % year reads differently if the benchmark did +25 % or −10 %.

None of this judges the manager; it separates what the history shows from what it only suggests.
```

#### F8 · ES · Para quien evalúa un fondo: efectivo, mercado y lo que queda

```text
Cuando un fondo enseña su rentabilidad media al año, conviene partir ese número en tres:

1. Lo que pagaba el efectivo en esas mismas fechas (si el fondo es en dólares, las letras del Tesoro a 3 meses). Eso lo pagaba el dinero quieto.
2. Lo que viene de seguir a su índice: su beta por lo que el índice rindió sobre el efectivo. Eso lo da también un fondo indexado.
3. Lo que queda: el alfa. Es lo único que justifica pagar una gestión activa, y con pocos años su margen de error es ancho.

Con 36 meses o más en común con el índice se puede calcular, con su rango al 95 %. Si sale positivo pero no se distingue de cero, también se puede calcular cuántos meses harían falta.

Rigor lo hace con la tabla mensual del fondo y la de su índice: https://rigor.up.railway.app/para/inversores-gestores-fondos?ref=f8

No dice si invertir: separa lo que el historial demuestra de lo que solo sugiere.
```

#### F8 · EN · For someone judging a fund: cash, market and what is left

```text
When a fund shows its average return a year, it pays to split that number in three:

1. What cash paid over the same dates (for a dollar fund, 3-month Treasury bills). Money sitting still paid that.
2. What comes from following its index: its beta times what the index returned over cash. An index fund gives you that too.
3. What is left: the alpha. It is the only part that justifies paying for active management, and with few years its margin of error is wide.

With 36 months or more in common with the index it can be computed, with its 95 % range. If it comes out positive but cannot be told apart from zero, you can also compute how many months that would take.

Rigor does it from the fund's monthly table and its index's: https://rigor.up.railway.app/for/investors-managers-funds?ref=f8

It does not say whether to invest: it separates what the history shows from what it only suggests.
```

#### F9 · ES · El Sharpe en la moneda de tu cuenta

```text
El Sharpe mide el resultado por encima de lo que pagaba el efectivo. Casi todas las calculadoras restan la tasa de EE. UU., pero si tu cuenta está en pesos mexicanos, reales o euros, tu efectivo pagaba la tasa de tu moneda, y hubo años en que la diferencia fue de varios puntos.

Con la tasa de tu moneda, el mismo historial puede verse bastante menos bueno. Vale la pena recalcularlo antes de enseñarlo o de comprar una estrategia por su Sharpe.

Rigor usa la tasa oficial de la moneda de tu cuenta (pesos mexicanos, reales, euros, libras, yenes, dólares canadienses o francos suizos) cuando tu reporte la indica; si no la indica o está en dólares, la de EE. UU., y en otra moneda no calcula esa línea: https://rigor.up.railway.app/?ref=f9
```

#### F9 · EN · The Sharpe in your account's currency

```text
The Sharpe measures the return above what cash paid. Almost every calculator subtracts the US rate, but if your account is in Mexican pesos, reais or euros, your cash paid your currency's rate, and in some years the gap was several points.

With your currency's rate, the same history can look quite a bit less good. It is worth recomputing before you show it or buy a strategy for its Sharpe.

Rigor uses the official rate of your account's currency (Mexican pesos, reais, euros, pounds, yen, Canadian dollars or Swiss francs) when your report names it; if it names none or is in dollars, the US rate, and in another currency it leaves that line out: https://rigor.up.railway.app/en?ref=f9
```

#### F10 · ES · Si operas con Revolut o con Zerodha

```text
Si operas acciones con Revolut o en India con Zerodha, puedes revisar tu historial sin copiar nada a mano. Sube el archivo tal como lo descargas:

- Revolut: el estado de cuenta de acciones (CSV).
- Zerodha: el Tradebook de Console (Reports > Tradebook, en CSV).

El informe arma tus operaciones con las compras y ventas (un depósito nunca cuenta como resultado de operar) y mide si el resultado se distingue de la suerte. Qué subir y de dónde: https://rigor.up.railway.app/guias/csv-universal?ref=f10
```

#### F10 · EN · If you trade with Revolut or Zerodha

```text
If you trade stocks with Revolut, or in India with Zerodha, you can review your history without copying anything by hand. Upload the file as you download it:

- Revolut: the stocks account statement (CSV).
- Zerodha: the Console Tradebook (Reports > Tradebook, as CSV).

The report builds your trades from the buys and sells (a deposit never counts as a trading result) and measures whether the result stands out from luck. What to upload and where from: https://rigor.up.railway.app/guides/universal-csv?ref=f10
```

#### F11 · ES · Cuando alguien pregunta si es seguro

```text
Rigor no se conecta a tu bróker ni te pide claves: subes un archivo exportado. Tu cuenta puede usar verificación en dos pasos con una app de autenticación, y entonces para entrar o recuperarla hacen falta dos de tres: tu contraseña, el código de la app o tu clave de recuperación. En Mi cuenta ves dónde está abierta y cierras cada sesión, y ves tus entradas más recientes (hasta 90 días), incluidos los intentos con contraseña incorrecta. Más en las preguntas frecuentes: https://rigor.up.railway.app/?ref=f11#faq
```

#### F11 · EN · When someone asks whether it is safe

```text
Rigor does not connect to your broker or ask for keys: you upload an exported file. Your account can use two-step sign-in with an authenticator app, and then signing in or recovering it takes two of three: your password, the code from the app or your recovery key. In My account you see where it is open and sign out each session, and you see your most recent sign-ins (up to 90 days), including wrong-password tries. More in the FAQ: https://rigor.up.railway.app/en?ref=f11#faq
```

### Mensajes directos

Solo a quien te pidió información (en un hilo, un comentario o tu WhatsApp).
Nunca en foros que prohíben mensajes comerciales privados (Elite Trader,
Trade2Win, TradingView, MQL5 Freelance).

#### D1 · ES · A un trader de retos que preguntó por Rigor

```text
Hola, <nombre>. Me preguntaste por Rigor en <sitio>.

Para retos de prop firm, el informe completo incluye un simulador con 16 retos de FTMO, FundedNext, The5ers y Topstep, con las reglas leídas en la web de cada firma: estima, remuestreando tu propio historial, con qué frecuencia se tocaría la pérdida diaria o la total, y con qué frecuencia no se llegaría al objetivo a tiempo. También te dice qué capital pide tu estrategia para cada límite de pérdida. Son estimaciones con sus supuestos escritos, no una predicción del reto.

Puedes probar la vista previa gratis con tu lista de operaciones de TradingView o tu informe de MT5: https://<dominio>
El informe completo cuesta USD 29.
```

#### D1 · EN · To a challenge trader who asked about Rigor

```text
Hi <name>, you asked about Rigor on <site>.

For prop-firm challenges, the full report includes a simulator with 16 FTMO, FundedNext, The5ers and Topstep challenges, with the rules read on each firm's website: by resampling your own history it estimates how often the daily or total loss limit would be hit, and how often the target would not be reached in time. It also tells you how much capital your strategy needs for each loss limit. These are estimates with their assumptions written out, not a forecast of the challenge.

You can try the free preview with your TradingView list of trades or your MT5 report: https://<domain>
The full report is USD 29.
```

#### D2 · ES · A quien va a copiar o invertir con otro trader y preguntó por Rigor

```text
Hola, <nombre>. Me preguntaste cómo revisar la cuenta de <trader o señal> antes de copiarla o invertir.

Pídele dos archivos: el historial completo de su cuenta (el informe de MetaTrader, o el CSV de Myfxbook, FX Blue o su señal de MQL5) y, si lo tiene, el backtest de su robot. Súbelos juntos en https://<dominio>

Rigor separa los depósitos y retiros del resultado de operar, avisa si el porcentaje se infla con recargas o si quedan pérdidas abiertas al final, y compara la cuenta con miles de historias remuestreadas de su backtest y operación por operación en las mismas fechas. Guía: https://<dominio>/guias/cuenta-proveedor

La vista previa es gratis; el informe completo cuesta USD 29. No me conecto a su bróker ni a tu dinero, y no te digo si invertir o no: te doy los números para que decidas.
```

#### D2 · EN · To someone about to copy or invest with another trader who asked about Rigor

```text
Hi <name>, you asked how to check <trader or signal>'s account before copying it or investing.

Ask them for two files: the full history of their account (the MetaTrader report, or the Myfxbook, FX Blue or MQL5 signal CSV) and, if they have it, their robot's backtest. Upload both together at https://<domain>

Rigor separates deposits and withdrawals from trading results, warns when the percentage is inflated by top-ups or when losses are still open at the end, and compares the account with thousands of resampled histories of its backtest and trade by trade on the same dates. Guide: https://<domain>/guides/provider-account

The preview is free; the full report is USD 29. I never connect to their broker or your money, and I do not tell you whether to invest: I give you the numbers so you can decide.
```

#### D3 · ES · A un trader de acciones, futuros o cripto que preguntó por Rigor

```text
Hola, <nombre>. Me preguntaste si Rigor sirve para <acciones / futuros / cripto>.

Sí: Rigor no depende del mercado, mide el historial que subes. Puedes subir la lista de operaciones de TradingView o NinjaTrader, el CSV de QuantConnect, backtesting.py o vectorbt, o tu curva de equity o serie de retornos en CSV o Excel (diaria, semanal o mensual).

Te dice si tu Sharpe se distingue del azar, cuánto queda después de descontar las configuraciones que probaste, qué pasa con el doble de costes, si sigue funcionando en el periodo reciente y qué capital pide. Cada número dice si se midió del archivo o si no se pudo medir.

La vista previa es gratis: https://<dominio>
El informe completo cuesta USD 29. Ejemplo: https://<dominio>/ejemplo
```

#### D3 · EN · To a stock, futures or crypto trader who asked about Rigor

```text
Hi <name>, you asked whether Rigor works for <stocks / futures / crypto>.

Yes: Rigor does not depend on the market, it measures the history you upload. You can upload the TradingView or NinjaTrader list of trades, the QuantConnect, backtesting.py or vectorbt CSV, or your equity curve or return series as CSV or Excel (daily, weekly or monthly).

It tells you whether your Sharpe stands out from chance, how much is left after discounting the configurations you tried, what happens at double costs, whether it still works in the recent period and how much capital it needs. Every number says whether it was measured from the file or could not be measured.

The preview is free: https://<domain>
The full report is USD 29. Sample: https://<domain>/ejemplo
```

## 6. Propuesta para vendedores de EA

El argumento para un vendedor no es "tu robot sale bien", porque puede salir
C o D. Es este: **los compradores ya desconfían de los backtests, y la página
de verificación les deja comprobar por su cuenta qué archivo se auditó y con
qué resultado, sin que el vendedor enseñe sus operaciones.** Y antes de
publicar, el informe privado le dice qué preguntarán los compradores
(sobreajuste, costes, periodo reciente, cuenta real frente al backtest).

Qué recibe el vendedor por USD 29 (o USD 69 si audita tres versiones o un
backtest y su cuenta):

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

Soy el autor de Rigor, un servicio que audita backtests de EA a partir del informe de MT5 y del XML de optimización, y da una clase de A a D en seis dimensiones (significación, número de intentos, costes, fuera de muestra, calidad de datos y benchmark). Si tienes una cuenta real o demo con el robot, también la compara con el backtest.

Si quieres, el resultado se publica en una página de verificación con los hashes del archivo auditado y un sello para tu web o tu Telegram. El sello dice textualmente: "Auditoría estadística de datos aportados – no verificados con el bróker – no garantiza resultados". Así tus compradores comprueban qué archivo se auditó sin que enseñes tus operaciones.

La vista previa es gratis y la ves tú solo. El informe completo cuesta USD 29, y la publicación es opcional: la decides después de leerlo. Ejemplo con datos sintéticos: https://<dominio>/ejemplo

Si no te interesa, dímelo y no vuelvo a escribirte.
<tu nombre>
```

#### V1 · EN · First contact with an EA vendor

```text
Subject: A public page where your buyers can check your backtest

Hi <name>, I saw <robot name> on <site>.

I am the author of Rigor, a service that audits EA backtests from the MT5 report and the optimisation XML, and gives a class from A to D across six dimensions (significance, number of trials, costs, out-of-sample, data quality and benchmark). If you have a live or demo account running the robot, it also compares it with the backtest.

If you want, the result is published on a verification page with the hashes of the audited file and a badge for your website or Telegram. The badge says, word for word: "Statistical audit of supplied data – not verified with a broker – not a performance guarantee". Your buyers can then check which file was audited without you showing your trades.

The preview is free and only you see it. The full report is USD 29, and publishing is optional: you decide after reading it. Sample built from synthetic data: https://<domain>/ejemplo

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

## 7. De primer mensaje a informe entregado

Objetivo: contestar el mismo día y que el cliente vea su vista previa antes
de pagar.

| Paso | Qué haces | Plantilla o dónde |
|---|---|---|
| 1. Primer mensaje | Saluda, explica en tres líneas y manda a subir el archivo y a ver `/ejemplo`. | W1 |
| 2. No sabe exportar | Instrucciones de su plataforma. | W2 |
| 3. Sube el archivo | El cliente ve la vista previa gratis y guarda el enlace de su informe (lleva el token). El botón "Pedir un código" te escribe por WhatsApp con el id de su auditoría. | — |
| 4. Quiere el completo | Datos de pago y enlace a los términos. | W3 |
| 5. Paga | Confirma el pago en tu banco o Mercado Pago antes de nada. Luego, en `https://<dominio>/panel`, crea un código con 1 crédito (3 para el paquete) y en la nota pon nombre de pila y referencia del pago. El código se muestra una sola vez. | `/panel` |
| 6. Entrega | Envía el código por WhatsApp y por ningún otro canal. | W4 |
| 7. Canje | El cliente escribe el código en su informe y lo desbloquea; puede guardarlo en PDF. | — |
| 8. Si falla | Si el archivo no se lee, no se crea auditoría y el código queda intacto. Si el informe lee mal el archivo, desactiva el código en `/panel`, devuelve el pago y avisa en el proyecto para corregir el importador. | W6 |
| 9. Vendedor | Si es vendedor, explica cómo publicar la verificación. | V2 |
| 10. Seguimiento | A los tres días, pide opinión sobre el informe y que lo recomiende. | W5 |

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
- Retención: `AUDIT_AUTO_PURGE=true` ya está puesto, así que el servicio borra
  solo los archivos no pagados. Las páginas de verificación publicadas y sus
  sellos siguen funcionando después.

Hoja de ventas (una fila por venta, sin datos sensibles): fecha, nombre de
pila, canal por el que llegó, importe, medio de pago, referencia, id del
código, id de la auditoría, clase, ¿publicó verificación?, opinión.

## 8. Plan de las primeras semanas y qué medir

| Semana | Qué hacer | Meta |
|---|---|---|
| 1 | Checklist de la sección 2. P1 a 20 contactos y en tu estado de WhatsApp. Perfil de MQL5 completo y primera entrada de blog (F3). | 10 vistas previas con archivo real; primeras 2 ventas. |
| 2 | 10 vendedores de EA de habla hispana contactados uno a uno (V1). Cinco respuestas útiles (F2) en el foro español de MQL5 y en Rankia, sin enlaces. | 5 ventas acumuladas; 1 verificación publicada. |
| 3 | Hilo en Commercial Content de Forex Factory (F1) si la membresía comercial encaja. Segunda entrada de blog con lo aprendido (sin nombrar robots sin permiso). | 8 ventas acumuladas; 3 opiniones. |
| 4 | Revisa los números y decide: más contenido, clasificados de FPA o un anuncio de pago pequeño. Paquete de 3 para quien compare robots o revise una cuenta. | 10 ventas acumuladas. |

Qué medir cada semana, en la hoja de ventas:

- Conversaciones nuevas y de qué canal vienen.
- Vistas previas creadas (cuántos llegaron a subir un archivo).
- Ventas y conversión vista previa → venta.
- Archivos que fallaron al leerse y de qué plataforma (son fallos a
  corregir en `audit/importers.py`).
- Verificaciones publicadas y visitas que llegan desde un sello.

### Etiquetas para saber qué publicación trae clientes

Cada enlace a Rigor que publiques lleva al final la etiqueta de su texto:
`?ref=` y el id en minúsculas. Por ejemplo, el F6 enlaza a
`/para/retos-prop-firm?ref=f6`, el P1 a `/?ref=p1` y el D3 a
`/para/traders-acciones-futuros-cripto?ref=d3`. En tu perfil de un foro o red
usa la etiqueta del sitio (`mql5`, `rankia`, `reddit`, `ff`, `telegram`,
`youtube`, `x`, `instagram`, `facebook`, `linkedin`, `tiktok`, `email`) y en tu
estado de WhatsApp `w0`. La lista completa está en `audit/funnel.py`
(`REF_TAGS`) y en `/panel`.

En `/panel`, «Embudo de ventas» muestra por etiqueta y por día e idioma las
visitas, las cuentas nuevas, los informes gratis, las vistas previas y los
pagos. Una etiqueta que no está en la lista cuenta como «sin etiqueta». Cuenta
la primera etiqueta con la que llega cada navegador, durante 30 días.

Si casi nadie sube un archivo, el problema está en el mensaje o en el canal;
si suben pero no pagan, en el precio o en lo que enseña la vista previa. Vuelve
a esta guía y cambia una sola cosa cada vez. Solo cuando haya ventas y
opiniones reales tiene sentido pensar en pruebas gratis o en subir el precio.

## Límites de esta guía

- Todavía no hay ninguna venta: las metas de la sección 8 son objetivos, no
  estimaciones de demanda.
- Las reglas de las comunidades cambian. Las marcadas como "fragmento" o
  "sin comprobar" deben leerse en un navegador antes de publicar.
- No se publicó, registró ni envió nada al preparar esta guía.
- Los precios salen de la comparación con competidores públicos; no hay datos
  de ventas reales.
- Los importadores se probaron con 39 archivos reales públicos y con los
  informes de MT5 del dueño. NinjaTrader, QuantConnect, backtesting.py y
  vectorbt solo se probaron con archivos de ejemplo públicos, porque no hay
  exportaciones reales publicadas; el primer cliente de esas plataformas es
  también una prueba, cubierta por la devolución.
- La normativa sobre publicidad de servicios financieros y correos
  comerciales varía por país; consulta a un abogado antes de escribir en
  frío a vendedores fuera de tu país.
