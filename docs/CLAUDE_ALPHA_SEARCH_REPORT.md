# Barrido de rutas de enriquecimiento: familias, venues y la aritmética de US$100

Estado: **NO_GO para el objetivo de 10,000× en un mes. INSUFFICIENT_EVIDENCE
para toda familia sobreviviente. Ninguna hipótesis nueva se preregistra.**

Rama `agent/claude-parallel`, base `04fecd8`. Ningún holdout fue leído, ninguna
campaña sellada fue retuneada, ningún dato de mercado fue descargado y ningún
dinero fue movido. Todas las cifras salen de módulos ejecutables
(`quant_trade.ops.growth_feasibility`, `quant_trade.ops.family_screen`), están
fijadas por tests y estampadas `evidence_class: ASSUMPTION`.

---

## 1. La pregunta directa, respondida

US$100 → US$1,000,000 en 30 días son **10,000×**. Reproducible con:

```bash
quant-trade wealth target-feasibility --start 100 --target 1000000 --days 30
```

| Cantidad | US$100 → US$1M (10,000×) | US$200 → US$1M (5,000×) |
|---|---:|---:|
| Retorno neto requerido, cada día calendario | **+35.9356%** | +32.8309% |
| Por sesión bursátil (20.71 sesiones en 30 días) | **+55.9990%** | +50.8648% |
| Volatilidad anualizada que **maximiza** la probabilidad | 1,497% | 1,440% |
| Probabilidad máxima alcanzable, sin ventaja | **1 en 112,915** | 1 en 54,483 |
| …con Sharpe 1.0 (muy bueno para retail) | 1 en 32,282 | 1 en 16,294 |
| …con Sharpe 2.0 (nivel institucional élite) | 1 en 9,982 | 1 en 5,269 |
| …con Sharpe 3.0 (techo declarado del screen) | 1 en 3,336 | 1 en 1,841 |
| Sharpe necesario para tener **5%** de probabilidad | **9.23** | 8.66 |
| Sharpe necesario para que sea un volado (50%) | **14.97** | 14.40 |

### Por qué más riesgo deja de ayudar

La intuición dice: si necesito 10,000×, subo el apalancamiento hasta que sea
posible. Es falsa, y esta es la razón exacta.

Bajo el modelo lognormal declarado, el log-retorno sobre un horizonte `T` tiene
media `(S·σ − σ²/2)·T` y desviación `σ·√T`. El término `−σ²/2` es el arrastre de
varianza. Al subir `σ`, la dispersión crece como `√σ²` pero la mediana cae como
`σ²`. La probabilidad de llegar al múltiplo `M` se maximiza en un punto finito:

```text
σ* = sqrt(2·ln(M)/T)          y      P_max = 1 − Φ(sqrt(2·ln M) − S·√T)
```

Pasado `σ*`, **más riesgo baja tus probabilidades**. Hay un test que lo verifica
en cuatro volatilidades distintas alrededor del óptimo
(`test_more_volatility_stops_helping_at_the_variance_optimum`).

Y en `σ*` hay una identidad exacta que resume todo el asunto:

```text
mediana en σ*  =  capital inicial ÷ múltiplo objetivo
```

Es decir: **a la volatilidad que maximiza tu probabilidad de convertir US$100 en
US$1,000,000, el resultado mediano es exactamente US$0.01.** Un centavo. No es
una aproximación ni una simulación; se deriva en dos líneas y está fijada como
test (`test_at_the_optimal_volatility_the_median_is_capital_divided_by_the_multiple`).

Ese es el trato real: la única configuración que te da una chance de 1 en 112,915
es la misma que casi con certeza te deja en cero. No es una estrategia de
esperanza positiva; es un billete de lotería con comisión.

### Lo que sí compone, y en cuánto tiempo

Con ventaja real, a la tasa de crecimiento geométrico `g = S²·(f − f²/2)` para
una fracción `f` de Kelly, el tiempo hasta 10,000× es `ln(10,000)/g`:

| Sharpe neto | Kelly completo | Medio Kelly |
|---|---:|---:|
| 0.5 | 73.7 años | 98.2 años |
| 1.0 | 18.4 años | 24.6 años |
| 1.5 | 8.2 años | 10.9 años |
| 2.0 | 4.6 años | 6.1 años |
| 3.0 | 2.0 años | 2.7 años |

Ninguna de esas filas describe una estrategia que este repositorio haya
encontrado. La evidencia medida es la contraria: **0 de 8 estrategias vencieron
a equal-weight** sobre datos reales de ETFs
([`REAL_DATA_VERDICT.md`](REAL_DATA_VERDICT.md),
[`BENCHMARK_AWARE_VERDICT.md`](BENCHMARK_AWARE_VERDICT.md)), con Sharpe
deflactado entre 0.000 y 0.006 contra un ledger de 109 trials.

> Nota de corrección: el plan inicial de esta tarea citaba "≈1,950% de
> volatilidad para un 5% de probabilidad". Ese número ignoraba el arrastre de
> varianza. Al implementarlo correctamente resultó ser más severo: **ninguna
> volatilidad alcanza el 5%** sin un Sharpe de al menos 9.23. Las cifras de este
> documento son las del módulo.

---

## 2. La restricción que realmente ata: costo fijo, no alpha

Antes de discutir señales, la aritmética de fricción a este tamaño de cuenta.

| Concepto | Sobre US$100 | Sobre US$200 | Sobre US$5,000 |
|---|---:|---:|---:|
| Alpaca SIP (`Algo Trader Plus`, US$99/mes) | **1,188%/año** | 594%/año | 23.8%/año |
| Rotación semanal en cripto (0.25% taker × 2 lados × 52) | 26.0%/año | 26.0%/año | 26.0%/año |
| Rotación mensual en cripto | 6.0%/año | 6.0%/año | 6.0%/año |
| Rotación semanal en acciones fraccionales (spread ~0.5 bp/lado) | 0.5%/año | 0.5%/año | 0.5%/año |

Dos consecuencias, ambas duras:

1. **Cualquier estrategia que requiera datos pagados es `NO_GO` aritmético a
   US$100–200.** La suscripción cuesta más que el capital. No es una opinión
   sobre el valor de los datos; es que el gasto fijo debe pagarse con ingreso
   ganado fuera de la cuenta.
2. **Cripto es ~50× más caro que acciones fraccionales sin comisión** para una
   cuenta de este tamaño. A 30% de volatilidad, la rotación semanal en cripto
   consume 0.87 de Sharpe bruto antes de que exista una sola señal. Esto invierte
   el foco cripto-céntrico que tiene el repositorio hoy.

---

## 3. Matriz de venues

Pediste ver más opciones que Alpaca. Todo lo siguiente es spot / long-only /
sin apalancamiento, que es la única frontera que este repositorio permite.

| Venue | Comisión spot | Fraccionales | Mínimo | Datos | Nota decisiva a US$100 |
|---|---|---|---|---|---|
| **Alpaca — acciones USA** | US$0 en acciones y ETFs | Sí | US$1 por orden de compra | IEX gratis; SIP US$99/mes | **La opción más barata.** El costo es sólo spread. |
| **Alpaca — cripto spot** | 0.15% maker / 0.25% taker (tier 1, 30d < US$100K) | Sí | — | Incluidos | 50× más caro por rotación. |
| **IBKR Lite** | US$0 en acciones/ETFs USA | Sí, 24,047 instrumentos elegibles | US$0.01 por operación fraccional | Delayed gratis; realtime por suscripción | Comparable a Alpaca; API más compleja. |
| **IBKR Pro (Tiered)** | US$0.0035/acción, **mínimo US$0.35 por orden** | Sí | — | Suscripción | El mínimo de US$0.35 sobre una posición de US$5 es 7% por lado. Descartado. |
| **Kraken Pro** | 0.25% maker / 0.40% taker (tier base) | Sí | — | Público | Peor que Alpaca cripto en taker. |
| **Coinbase Advanced** | 0.40% maker / 0.60% taker (tier base) | Sí | — | Público | El más caro de los evaluados. |

**Conclusión de venue:** a US$100–200, **acciones USA fraccionales con comisión
cero es la única clase donde el arrastre por fricción no domina.** Si algo se va
a intentar, se intenta ahí.

### Cambio regulatorio relevante, verificado

FINRA retiró la regla Pattern Day Trader y Alpaca implementó un marco de margen
intradía el **4 de junio de 2026**. La designación PDT y el requisito de
US$25,000 desaparecieron de la plataforma; el mínimo para 4× de poder de compra
intradía bajó de US$25,000 a US$2,000. Ya no existe el tope de 3 day-trades por 5
días hábiles.

Esto **amplía** lo que una cuenta pequeña puede hacer legalmente. No cambia nada
de la sección 1: quita una restricción regulatoria, no la aritmética. Y las
cuentas cash siguen sujetas a reglas de liquidación; operar con fondos no
liquidados sigue produciendo violaciones de *free riding*.

---

## 4. Matriz de familias: el screen de capital, antes de tocar datos

Cada evaluación que corre este repositorio entra en un ledger append-only y sube
el umbral de Sharpe deflactado que todo resultado posterior debe superar. Una
familia que jamás pudo ejecutarse al capital disponible **igual cuesta poder
estadístico** cuando se prueba y se rechaza.

Por eso el screen corre primero y no lee un solo retorno. Pregunta únicamente si
la familia *podría* ejecutarse: ¿cada posición supera el mínimo del venue?,
¿queda algún Sharpe después de las fricciones?, ¿se puede pagar el dato fijo?,
¿existe una fuente point-in-time cuya licencia lo permita?

Resultado a **US$100**:

| # | Familia | Veredicto | Restricción vinculante | US$/posición | Costo/año | Sharpe bruto de empate |
|---|---|---|---|---:|---:|---:|
| 1 | Trend / TSMOM (ETF, long-cash, mensual) | `FEASIBLE` | — | $100.00 | 0.1% | 0.01 |
| 2 | Momentum cross-sectional (acciones, top-20) | `NO_GO` | `no_point_in_time_data` | $5.00 | 0.7% | 0.03 |
| 3 | Reversal de corto plazo (semanal, top-20) | `NO_GO` | `cost_drag` | $5.00 | 1,191% | 47.64 |
| 4 | Turn-of-month / overnight (SPY) **con SIP** | `NO_GO` | `cost_drag` | $100.00 | 1,188% | 74.26 |
| 4b | …la misma, con datos IEX gratuitos | `FEASIBLE` | — | $100.00 | 0.1% | 0.01 |
| 5 | Post-earnings drift (PEAD) | `NO_GO` | `cost_drag` | $10.00 | 1,191% | 39.70 |
| 6 | Defensive / low-volatility (trimestral) | `NO_GO` | `no_point_in_time_data` | $5.00 | 0.1% | 0.00 |
| 7 | Value on-chain AANV30 (cripto) | `NO_GO` | `cost_drag` | $1.00 | 1,554% | 19.43 |
| 8 | Carry de funding perpetuo (delta-neutral) | `NO_GO` | `cost_drag` | $50.00 | 182.5% | 18.25 |
| 9 | World order flow (CCData) | `NO_GO` | `data_license` | $10.00 | 126.0% | 1.57 |
| 10 | Event-driven / screen de delisting (cripto) | `INSUFFICIENT_EVIDENCE` | — | $5.00 | 0.5% | 0.01 |
| 11 | Prima de iliquidez (cripto micro-cap) | `INSUFFICIENT_EVIDENCE` | — | $5.00 | 1.2% | 0.01 |

**Tally: 8 `NO_GO`, 2 `INSUFFICIENT_EVIDENCE`, 2 `FEASIBLE` — sin gastar un solo
trial y sin abrir un solo dataset.**

### Lectura de la matriz

- **Lo que mata a la mayoría no es la señal, es la forma de ejecución.** Las
  familias 3, 5, 7 y 8 mueren por rotación: a US$100, rotar seguido es
  matemáticamente incompatible con cualquier Sharpe creíble.
- **Las familias 2 y 6 mueren por datos, no por costo.** Su arrastre es
  despreciable (0.7% y 0.1% anual). Lo que las bloquea es que un universo de
  acciones sin constituyentes point-in-time arrastra sesgo de supervivencia por
  construcción — exactamente el error que ya invalidó el panel cripto low-cap de
  este repositorio (`INVALIDATION.json`, seis causas registradas).
- **La familia 9 muere por licencia.** El API público de CCData/CoinDesk Data es
  Creative Commons Atribución-**NoComercial**; el acceso gratuito se retiró el
  2026-05-21 y el plan Start-Up sólo entrega 365 días de historia diaria. Ver
  [`WORLD_ORDER_FLOW_DATA_FEASIBILITY.md`](WORLD_ORDER_FLOW_DATA_FEASIBILITY.md).
- **La comparación 4 vs 4b es la más informativa del documento.** La misma
  estrategia, el mismo capital, la misma forma de ejecución: `NO_GO` con la
  suscripción de US$99, `FEASIBLE` sin ella. A este tamaño de cuenta el costo del
  dato, no la señal, es la variable de decisión.
- **Las dos `INSUFFICIENT_EVIDENCE` no son sobrevivientes.** Son familias cuya
  licencia de datos no está verificada. `UNKNOWN` es evidencia faltante, jamás
  permiso.

### Familias ya selladas: prohibido retunear

Estas están cerradas por decisiones previas y no admiten variantes post-hoc:

| Campaña | Veredicto | Por qué falló |
|---|---|---|
| `binance_btc_eth_tsmom_long_cash_v1` | `NO_GO` | +417.68% contra BTC +438.60%, ETH +626.59%, 50/50 +532.60%; DD −58.34%; ganó 1 de 4 bloques (se exigían 3) |
| `binance_btc_weekly_momentum_1w_long_cash_v1` | `NO_GO` | +255.73% contra BTC buy-and-hold +776.15%; **0 de 4 bloques**; DD −80.84% |
| `SPY_TOM_Dm1_P3_v1` | `INSUFFICIENT_EVIDENCE` | Sin bundle auténtico; ver §5 |
| `binance_liquid_xsmom_30d_top20_weekly_v1` | `INSUFFICIENT_EVIDENCE` | 9 bloqueadores declarados; panel `INVALID_LOOKAHEAD` |
| Crypto low-cap H1–H4 | `INSUFFICIENT_EVIDENCE` | Panel invalidado por look-ahead causal; presupuesto sellado de 15 trials |
| V8 H6/H7 | Bloqueadas | Se desbloquean sólo si H1–H3 se **miden** y rechazan |

Dos holdouts siguen reservados y sin leer: cripto low-cap 2023-11-29 → 2026-08-09
y Binance weekly 2023-11-29 → 2026-08-16. **Ninguno fue tocado en este trabajo.**

---

## 5. El bloqueador real de Track A, y por qué no se resuelve con dinero

La campaña SPY turn-of-month está completamente construida: spec sellado
`5d2c57f2…`, colector GET-only con lista blanca de 4 URLs, evaluador con fees por
vintage, corporate actions, calendario XNYS explícito, US$200 y SPY fraccional.
Es, con diferencia, el activo de investigación más terminado del repositorio.

Y aun así **no puede emitir un veredicto**. `prospective_spy_tom_development.py`
declara `VerdictStatus = Literal["INSUFFICIENT_EVIDENCE"]`: un único valor
posible. La razón está documentada: no existe un trust root externo con el que
autenticar una respuesta de Alpaca, así que ni siquiera un diagnóstico adverso
puede llamarse `NO_GO` de campaña.

Verifiqué los dos bloqueadores duros contra la documentación oficial antes de
recomendar cualquier gasto:

1. **Vintage de corporate actions — confirmado imposible en v1.** La
   documentación de Alpaca dice literalmente que *actualmente no hay garantías
   sobre el tiempo de creación de las corporate actions*, y que puede haber
   retrasos tanto en recibirlas de sus proveedores como en procesarlas. Sin
   marca temporal garantizada no hay vintage atestiguable, y el evaluador exige
   que el vintage preceda a la apertura de la sesión efectiva. Nota adicional,
   más débil: la referencia actual documenta `/v1/corporate-actions` y el
   `/v2/corporate_actions/announcements` del que depende el colector ya no
   aparece en ella. No encontré un aviso formal de deprecación, así que lo
   registro como señal, no como hecho verificado — y no hace falta para el
   veredicto: la ausencia de garantía temporal ya lo cierra.
2. **Muestra al filo.** El evaluador exige ≥120 meses pareados completos, y la
   cobertura histórica de Alpaca empieza en 2016 tanto en el plan Basic como en
   el de pago. El propio doc de campaña advierte que *una sola exclusión por
   cierre temprano* dispara `MAXIMUM_ATTESTABLE_PAIRS_BELOW_120`.

**Consecuencia, y es la conclusión operativa de todo Track A:** pagar los US$99
mensuales y recolectar el bundle perfecto **no cambiaría el veredicto**. Se
gastaría entre 50% y 99% del capital mensual para llegar exactamente al mismo
`INSUFFICIENT_EVIDENCE` que ya se tiene gratis. Ese es el `NO_GO` temprano que
vale la pena tener.

---

## 6. Veredicto

**No se preregistra ninguna hipótesis nueva.** El handoff permite como máximo
una, y exige que sea independiente de los intentos previos, accesible con datos
legales y ejecutable con US$100. Ninguna de las 12 filas de la §4 cumple las
tres. Inventar una décimo tercera sería empezar una segunda búsqueda con la
primera todavía abierta — el mismo error que la regla de desbloqueo de H6/H7 ya
prohíbe explícitamente.

Lo que sí se construyó, que es lo que el handoff pide cuando ninguna hipótesis
supera pre-factibilidad:

- `quant_trade.ops.growth_feasibility` — el techo de probabilidad, el óptimo de
  varianza, el Sharpe requerido, Kelly y la carga de costo fijo. 47 tests.
- `quant_trade.ops.family_screen` — el gate de capital que rechaza una familia
  antes de que consuma un trial, un holdout o una suscripción. 44 tests.
- `quant_trade.metrics.normal` — una sola implementación del CDF normal,
  compartida; antes había una copia privada dentro de `metrics.statistics`.

### Próxima acción de mayor valor esperado

No es de investigación. Es
[`CLAUDE_REVENUE_PILOT.md`](CLAUDE_REVENUE_PILOT.md): diez conversaciones de
descubrimiento y tres pilotos de auditoría. La probabilidad de que alguien pague
por una auditoría es una cantidad desconocida y averiguable. La probabilidad de
10,000× en un mes es una cantidad conocida y es 1 en 112,915.

Si el capital sube a US$5,000 o más, la §4 cambia materialmente: la suscripción
SIP cae a 23.8% anual y varias familias vuelven a ser evaluables. Ese es el
argumento cuantitativo para que el ingreso ganado vaya primero.

---

## Apéndice: los supuestos exactos de la §4

La tabla de familias no es una opinión redactada: es la salida de
`screen_families()` sobre estos `StrategyFamilyProfile`. Se publican para que
cualquiera reconstruya la tabla y discuta un supuesto concreto en vez del
resultado. Todos con `capital_usd=100`, `portfolio_fraction_traded_per_rebalance=1.0`
salvo donde se indica, y `fractional_units_supported=True`.

| # | posiciones | rebal./año | bps/lado | mín. nocional | datos US$/mes | licencia | PIT | vol |
|---|---:|---:|---:|---:|---:|---|---|---:|
| 1 | 1 | 12 | 0.5 | $1 | 0 | `NOT_REQUIRED` | sí | 16% |
| 2 | 20 | 12 | 3 | $1 | 0 | `NOT_REQUIRED` | **no** | 25% |
| 3 | 20 | 52 | 3 | $1 | 99 | `COMMERCIAL_VERIFIED` | sí | 25% |
| 4 | 1 | 12 | 0.5 | $1 | 99 | `COMMERCIAL_VERIFIED` | sí | 16% |
| 4b | 1 | 12 | 0.5 | $1 | **0** | `COMMERCIAL_VERIFIED` | sí | 16% |
| 5 | 10 | 52 | 3 | $1 | 99 | `UNKNOWN` | — | 30% |
| 6 | 20 | 4 (25% del libro) | 3 | $1 | 0 | `NOT_REQUIRED` | **no** | 14% |
| 7 | 100 | 12 | 25 | $1 | 129 | `UNKNOWN` | — | 80% |
| 8 | 2 | 365 | 25 | $1 | 0 | `NOT_REQUIRED` | sí | 10% |
| 9 | 10 | 252 | 25 | $1 | 0 | `NON_COMMERCIAL` | — | 80% |
| 10 | 20 | 1 | 25 | $1 | 0 | `UNKNOWN` | sí | 80% |
| 11 | 20 | 1 | 60 | $5 | 0 | `UNKNOWN` | sí | 120% |

Procedencia de los costos por lado: 0.5 bp es el spread de SPY; 3 bps una
acción USA típica con comisión cero; 25 bps el taker tier-1 de Alpaca cripto;
60 bps la medición propia de libros Bybit micro-cap a US$100
([`CRYPTO_LOWCAP_COST_MODEL.md`](CRYPTO_LOWCAP_COST_MODEL.md)). US$129/mes es la
cotización registrada de CoinGecko Analyst
([`CRYPTO_LOWCAP_DATA_SOURCES.md`](CRYPTO_LOWCAP_DATA_SOURCES.md)).

**Si un supuesto está mal, cámbialo y vuelve a correr el screen.** Ese es el
punto de tenerlo como función pura y no como párrafo.

## Fuentes

- [Alpaca — FINRA retira la regla PDT y el nuevo marco de margen intradía](https://alpaca.markets/blog/finra-retires-the-pdt-rule-introducing-alpacas-new-intraday-margin-framework/)
- [Alpaca — tarifas de cripto spot por tier](https://docs.alpaca.markets/us/docs/crypto-fees)
- [Alpaca — planes de market data (Basic vs Algo Trader Plus, cobertura desde 2016)](https://docs.alpaca.markets/us/docs/about-market-data-api)
- [Alpaca — corporate actions: sin garantías sobre el tiempo de creación](https://docs.alpaca.markets/reference/corporateactions-1)
- [Interactive Brokers — comisiones de acciones](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php)
- [Interactive Brokers — trading fraccional](https://www.interactivebrokers.com/en/trading/fractional-trading.php)
- [McConnell & Xu, *Equity Returns at the Turn of the Month*, FAJ 64(2)](https://www.chesler.us/resources/academia/turn_of_the_month_stock_returns.pdf)
- Evidencia interna: [`REAL_DATA_VERDICT.md`](REAL_DATA_VERDICT.md),
  [`BENCHMARK_AWARE_VERDICT.md`](BENCHMARK_AWARE_VERDICT.md),
  [`BINANCE_BTC_ETH_TSMOM_DEVELOPMENT_VERDICT.md`](BINANCE_BTC_ETH_TSMOM_DEVELOPMENT_VERDICT.md),
  [`BINANCE_BTC_WEEKLY_MOMENTUM_DEVELOPMENT_VERDICT.md`](BINANCE_BTC_WEEKLY_MOMENTUM_DEVELOPMENT_VERDICT.md),
  [`SPY_TURN_OF_MONTH_DEVELOPMENT_EVALUATOR.md`](SPY_TURN_OF_MONTH_DEVELOPMENT_EVALUATOR.md),
  [`WORLD_ORDER_FLOW_DATA_FEASIBILITY.md`](WORLD_ORDER_FLOW_DATA_FEASIBILITY.md),
  [`AANV30_DATA_FEASIBILITY.md`](AANV30_DATA_FEASIBILITY.md),
  [`CRYPTO_VALIDATION_GATES.md`](CRYPTO_VALIDATION_GATES.md),
  [`WEALTH_BUILDING_PLAN.md`](WEALTH_BUILDING_PLAN.md).

Las tarifas de Kraken y Coinbase Advanced provienen de comparativas secundarias y
están marcadas como tales: no se usaron para ninguna decisión de este documento,
sólo para descartar venues más caros que Alpaca.

---

## Lo que este documento no dice

No dice que exista una estrategia rentable. No dice que US$100 puedan convertirse
en US$1,000,000. No autoriza un depósito, una orden, una suscripción ni una
transferencia. Y no debe leerse como asesoría de inversión: es aritmética sobre
supuestos declarados, con cada supuesto visible y refutable.
