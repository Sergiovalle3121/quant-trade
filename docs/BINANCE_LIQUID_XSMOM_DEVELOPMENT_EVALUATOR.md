# Evaluador DEVELOPMENT de XSMOM líquido de Binance

Estado: **IMPLEMENTADO, PERO BLOQUEADO PARA DATOS REALES — RESEARCH ONLY**

`prospective_xsmom_development.py` define el contrato offline del futuro
evaluador DEVELOPMENT de
`binance_liquid_xsmom_30d_top20_weekly_v1`. Su finalidad actual es hacer
revisables la causalidad, la ejecución y la contabilidad antes de que exista un
dataset apto. No habilita un backtest económico con los datos disponibles.

La declaración sellada aún contiene simultáneamente:

- `development_or_holdout_window_activated=false`;
- `economic_evaluation_allowed=false`;
- ausencia de un timestamp de preregistro independiente;
- clasificación point-in-time de stablecoins desconocida;
- costos de cuenta/símbolo sin vincular;
- ledger histórico de reglas por símbolo todavía no construido.
- ausencia de una fuente y política point-in-time para convertir USDT a USD.

Por ello, un manifiesto `CAUSAL_DEVELOPMENT` se rechaza después de validar su
envolvente y antes de abrir cualquiera de los tres archivos de mercado. El
resultado máximo sigue siendo `INSUFFICIENT_EVIDENCE`.

## Bundle requerido

El directorio es explícito y content-addressed:

```text
manifest.json
selection_panel.jsonl
execution_bars.jsonl
execution_terms.jsonl
```

`manifest.json` usa JSON canónico y fija estrategia/sello, Binance Spot, inicio
y fin DEVELOPMENT, límite de evidencia, frontera del holdout, hashes y conteos
exactos, commits de procedencia y digests de los artefactos fuente. Ningún
archivo puede llegar al holdout que comienza el 2023-11-29. El evaluador no
consulta la red ni busca caches alternativos.

`selection_panel.jsonl` satisface el contrato completo del generador XSMOM. La
decisión se reconstruye desde prefijos y exige exactamente la misma cohorte de
100 para candidato y control, 20 posiciones por cartera y el mismo
`cohort_digest`.

`execution_bars.jsonl` separa el open observable del viernes y el mark
observable al cerrar la barra. Una orden solo puede intentar el open exacto del
viernes, 24 horas después de la decisión del jueves. Si ese open falta, expira
sin retry. Un gap o halt no se interpreta como delisting; se conserva el último
mark. Solo `DELISTING_CONFIRMED`, observado causalmente, permite el write-down
conservador a cero cuando no hay salida ejecutable demostrada.

`execution_terms.jsonl` vincula, por símbolo y viernes, fee real de cuenta,
spread p75, impacto p75 y una copia denormalizada de tick, step, cantidades y
notional mínimos/máximos expresados explícitamente en la moneda quote USDT. La hora de observación del fee y el fin de la muestra
de costos deben ser como máximo el jueves, y sus hashes deben coincidir con los
artefactos de fees/costos del manifiesto. Para un artefacto real esa copia no es una segunda
fuente de verdad: debe coincidir exactamente con un
`BinanceSpotSymbolRulesLedger` receipt-bound y con su digest. El lookup se hace
al jueves y exige una observación con antigüedad máxima de 24 horas, todos los
filtros de market order aplicables y una atestación externa independiente. El
schema v2 actual clasifica incluso una captura local etiquetada `live` como
`UNATTESTED_SOURCE`: nunca produce `AVAILABLE_REAL`. Por tanto una regla
ausente, stale, test-only, no-`TRADING` o meramente local bloquea la evaluación.

## Contabilidad económica cerrada

El fixture sintético mantiene cuatro libros independientes con 200 USDT
nominales:

1. candidato top-20 por momentum;
2. control top-20 por liquidez, desde la misma cohorte;
3. BTC/USDT 95% más 5% cash;
4. BTC/USDT 100%.

Todas las carteras usan fechas, filtros y costos idénticos. Cada intento deja
cantidad solicitada, llena y rechazada, open, fill, fee, costo adverso, estado y
motivo. Los sells se procesan antes de los buys, no se permite saldo negativo,
short ni leverage, y el redondeo es conservador por lado.

Ese libro de prueba no afirma que `1 USDT = US$1`. Antes de calcular riqueza,
capital o beneficio en dólares se necesita un artefacto USDT/USD causal con
rate, hora de disponibilidad, fuente y digest para cada valoración. Mientras
no exista, el real path devuelve
`POINT_IN_TIME_USDT_USD_CONVERSION_NOT_IMPLEMENTED` sin abrir datos de mercado.

Se calculan dos escenarios cerrados:

- normal: costos 1× y fills 100%;
- stress: costos 2× y fills 50%; el remanente expira sin retry.

Los conteos de robustez dividen todos los retornos semanales completos en
exactamente cuatro bloques contiguos y comparan el candidato con los tres
benchmarks. Esos conteos son descriptivos: una campaña de un solo trial no
identifica PBO.

El tipo de resultado solamente admite `NO_GO` o `INSUFFICIENT_EVIDENCE`.
`promotion_authorized`, `live_execution_authorized` y
`real_money_authorized` son siempre falsos.

Los objetos públicos también fallan cerrados cuando se construyen directamente:
el verdict exige schema 1, el strategy ID sellado, hashes SHA-256, razones
limpias, conteos enteros y los dos escenarios exactos. Cada escenario exige los
cuatro libros tipados, los tres benchmarks de bloque con conteos de 0 a 4 y
ejecuciones tipadas que concuerden con sus métricas y costos. NaN, infinitos,
booleanos usados como números, timestamps no UTC, estados inventados, costos
negativos y cualquier autorización externa son inválidos.

## Modo sintético

`SYNTHETIC_TEST_ONLY` necesita el argumento explícito
`allow_synthetic_test_artifact=true`. Sirve exclusivamente para probar el
evaluator con fixtures offline: Friday-only, expiración, hashes, filtros,
costos, stress, cuatro bloques y benchmarks. Sus retornos se etiquetan
obligatoriamente como `SYNTHETIC_TEST_DATA_IS_NOT_ECONOMIC_EVIDENCE` y nunca
pueden convertirse en evidencia de rentabilidad.

Antes de usar datos reales se necesita una nueva declaración revisada y con
procedencia independiente que active expresamente DEVELOPMENT, sin modificar
ni volver a sellar post-hoc esta campaña bloqueada.
