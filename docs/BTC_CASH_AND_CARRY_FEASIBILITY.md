# BTC cash-and-carry: gate prospectivo de factibilidad

Estado al 2026-08-13: **`INSUFFICIENT`**. No se creó un `ExperimentSpec`, no se
leyó ningún holdout y no se calculó P&L. El nuevo contrato sólo puede emitir:

- `FEASIBLE_FOR_DEVELOPMENT_COLLECTION`
- `INSUFFICIENT`
- `NO_GO`

Policy hash v1:
`98c3cc11d38c9aa08e48baf404fb93b09c7862cef5a955f2263772b3196000c5`.

Incluso el primer estado únicamente permite preparar una recolección de datos
de desarrollo. No permite red, backtest económico, promoción, derivados,
órdenes, depósitos, transferencias, retiros ni dinero real.

En **schema v1**, ese estado positivo es deliberadamente inalcanzable. Siempre
se agregan estos bloqueos `MISSING`:

- `EXTERNAL_ATTESTATION_TRUST_ROOT_NOT_IMPLEMENTED`;
- `EVIDENCE_CONTENT_BINDING_PARSERS_NOT_IMPLEMENTED`;
- `ACCOUNT_MANUAL_REVIEW_AUTHENTICITY_NOT_IMPLEMENTED`.

El constructor público también rechaza directamente un verdict positivo v1.
Esto evita que bytes inventados por el caller, aunque sus hashes sean
autoconsistentes, se conviertan en “evidencia”.

El código está aislado en
`quant_trade.research.prospective_carry_feasibility`. No importa módulos `v8`,
`v9` ni `carry`, no abre archivos y no escribe artefactos.

## Por qué se estudia, pero no se presupone rentable

La estructura que se quiere estudiar es exactamente una posición larga Spot
BTC/USDT, totalmente fondeada, y una posición corta del perpetuo lineal
BTC/USDT por la misma cantidad de BTC, en la misma venue. El financiamiento
positivo puede pagar al corto, pero el signo, intervalo y límites pueden
cambiar. Tampoco existe un vencimiento que obligue al perpetuo a converger.

El working paper de BIS [*Crypto carry*](https://www.bis.org/publ/work1087.pdf)
documenta carry elevado, pero atribuye su persistencia a fricciones de margen y
regulación. También muestra por qué el nombre “arbitraje sin riesgo” es
incorrecto: las dos piernas necesitan capital y gestión separada, y un aumento
del basis puede liquidar la pierna corta antes de que converja. Su evidencia de
futuros con vencimiento no demuestra que un perpetuo retail de Bybit sea
rentable neto; el propio paper destaca que los perpetuos no tienen convergencia
forzada por expiración.

Documentación primaria del venue usada para diseñar el contrato:

- [Instrument info de Bybit](https://bybit-exchange.github.io/docs/v5/market/instrument):
  estado, base, quote, settlement, tipo de contrato, tick/step, mínimo nocional,
  intervalo y límites de funding son campos dinámicos que deben capturarse.
- [Historial de funding](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate):
  el endpoint devuelve settlements por símbolo; el intervalo se consulta por
  separado y no debe fijarse por memoria.
- [Fee rate de cuenta](https://bybit-exchange.github.io/docs/v5/account/fee-rate):
  las tasas Spot y lineal son específicas de cuenta/categoría y el endpoint es
  autenticado. Una tasa publicada genérica no basta.
- [Funding fee](https://www.bybit.com/en/help-center/article/Funding-fee-calculation):
  el corto recibe sólo cuando el funding es positivo y mantiene la posición en
  el settlement. Bybit puede cambiar límites e intervalo; además, si el saldo
  disponible no basta, el funding adverso reduce margen y acerca liquidación.
- [Cálculo de liquidación aislada](https://www.bybit.com/en/help-center/article/Liquidation-Price-Calculation-under-Isolated-Mode-Unified-Trading-Account):
  la liquidación usa mark price, maintenance margin y fee de cierre vigentes.
- [KYC individual](https://www.bybit.com/en/help-center/article/Individual-KYC-FAQ):
  Bybit declara verificación de identidad obligatoria para sus productos.
- [Países restringidos](https://www.bybit.com/en/help-center/article/Service-Restricted-Countries)
  y [términos de Bybit](https://www.bybit.com/common-static/compliance/legal/BYBIT/b2e1c94c53ee5e12e165919de919337e.pdf):
  una lista web no sustituye la identificación de la entidad contractual ni
  una revisión de que Spot y derivados estén disponibles legalmente para la
  cuenta mexicana concreta.
- [Coin info](https://bybit-exchange.github.io/docs/v5/asset/coin-info):
  depósito, retiro, mínimos, fees y suspensiones de cadena son dinámicos.
- [Coinbase Exchange product book](https://docs.cdp.coinbase.com/api-reference/exchange-api/rest-api/products/get-product-book):
  el policy fija `api.exchange.coinbase.com/products/USDT-USD/book` como
  referencia primaria independiente de USDT/USD; no se puede escoger después
  la fuente que muestre la conversión más conveniente.

Estas fuentes explican qué debe medirse; no constituyen asesoría legal, fiscal
ni una promesa de ingreso.

## Auditoría del carry que ya existía

No se reutilizó la campaña V8 ni sus artefactos.

- V8 registró H1/H2/H3, pero su propio reporte termina en
  `NOT_RUN_NO_EVIDENCE`: la salida HTTPS fue bloqueada. Por tanto, sus tasas de
  break-even son aritmética sobre supuestos, no evidencia de edge.
- V9 corrigió fallas materiales: selección OOS, DSR con multiplicidad, equity
  por ledger, costos ligados a bytes/venue y el falso “mínimo de US$166,667”.
  Su curva pequeña mostró que lot step, mínimos y fee floors pueden dominar,
  pero esos términos estaban clasificados `ASSUMPTION` y usaban un precio de
  referencia.
- La capa `carry` anterior sí contiene una ruta que puede acabar en
  `PAPER_CANDIDATE` después de evaluar retornos. Este gate no la llama. Antes
  de un experimento hacen falta identidad, legalidad, costos, riesgo y
  factibilidad técnica point-in-time.
- La metadata seed antigua usa defaults de identidad e intervalo para BTC.
  Este contrato prohíbe inferirlos: necesita receipts distintos para
  `spot:BTCUSDT` y `linear:BTCUSDT`.
- El holdout y los paneles anteriores no se abren. Un futuro experimento tendrá
  una declaración y un dataset nuevos, ligados a su propio cutoff.

## Qué exige el contrato

Cada elemento llega como bytes offline más tres hashes: contenido, receipt de
transporte/request y attestation de revisión. El hash prueba que los bytes no
cambiaron; por sí solo no prueba su origen. Por eso cada receipt también exige
autoridad, scope exacto, identificador de revisión, licencia/uso comercial,
request time, response time, publication/effective time y, para evidencia
dinámica, server time y cutoff fijado del lado de la petición.
Los receipts marcados como venue-primary sólo aceptan hosts oficiales de
Bybit; la etiqueta por sí sola no vuelve primaria a una URL arbitraria.

Estas validaciones todavía son una envoltura, no autenticación. En v1 el caller
también podría escribir una attestation falsa, recalcular sus hashes y llenar a
mano `VenueAccountAssessment`, `InstrumentPairAssessment` y
`PointInTimeTerms`. No existe aún una firma contra una raíz externa confiable
ni un parser que demuestre que esos objetos fueron derivados de esos bytes.
Por eso incluso el fixture completo de tests retorna `INSUFFICIENT`.

Los 19 tipos obligatorios son:

1. términos del venue y entidad contractual;
2. revisión legal independiente de acceso Spot + perpetuos para `MX`;
3. KYC y capacidades reales de la cuenta;
4. instrumento Spot `bybit:spot:BTCUSDT`;
5. instrumento perpetuo `bybit:linear:BTCUSDT`;
6. fee Spot real de cuenta;
7. fee perpetuo real de cuenta;
8. schema/receipt de funding settled;
9. schema causal de spot, mark e index para basis;
10. order book Spot;
11. order book perpetuo;
12. modelo versionado de spread/impacto p95;
13. términos de borrow y collateral, más saldo prestado cero;
14. reglas de liquidation/MMR y distancia de liquidación;
15. conversión point-in-time USDT/USD;
16. memo fiscal mexicano revisado por profesional independiente;
17. stress offline/Demo del camino de transferencias;
18. stress offline/Demo de retiro congelado y cierre sin depender de retiro;
19. evaluación independiente de contraparte/custodia.

La cuenta debe tener API de sólo lectura y permisos de trade, withdrawal y
transfer apagados. La posición propuesta exige Spot totalmente pagado,
perpetuo aislado, sin préstamos y leverage `<= 1x`. Una cuenta o producto
explícitamente prohibido, KYC rechazado, identidad BTC/USDT inconsistente,
prelisting, préstamo, leverage mayor a 1x o buffer de liquidación menor a 50%
produce `NO_GO`. Información ausente, stale o no revisada produce
`INSUFFICIENT`, nunca aprobación por defecto.

La revisión fiscal debe resolver, como mínimo, tratamiento de compraventas Spot,
perpetuos y funding, realización, fees deducibles, valuación USDT/USD y
USDT/MXN, mantenimiento de registros y obligaciones mexicanas. El software no
decide esos puntos.

## Qué significan US$200

Con `US$200`, leverage `1x` y una reserva mínima de 20%, el techo antes de FX,
precio, fees y redondeo es:

```text
capital utilizable = 200 × (1 - 0.20) = US$160
capital por unidad de notional = Spot 1.0 + margen perp 1.0 = 2.0
notional máximo igualado por pierna = 160 / 2 = US$80
reserva sin asignar = US$40
```

Es decir, a lo sumo aproximadamente US$80 de BTC Spot y US$80 de margen para
un short perp de US$80, más US$40 de contingencia. No son US$160 de exposición
direccional neta: las cantidades BTC deben ser iguales. Tampoco es un cálculo
de ganancia.

El gate sólo completa la cantidad BTC cuando recibe simultáneamente precio
Spot, mark e index, USDT/USD, qty steps de ambas piernas, mínimos nocionales,
fees reales, fricción p95 y profundidad ejecutable. Redondea hacia abajo al
mínimo múltiplo común de ambos qty steps y exige profundidad de al menos 2× el
notional en cada book. La reserva debe cubrir una contingencia conservadora de
cuatro fills.

Hoy no existen esos receipts nuevos ni las revisiones de cuenta/legal/fiscal.
Por eso no puede concluirse siquiera que US$200 coloquen las dos órdenes, y
mucho menos que produzcan ingreso.

## Próximo paso permitido

No sellar una estrategia todavía. Primero construir una versión nueva del
loader, revisada independientemente, que:

1. reciba capturas sanitizadas sin keys, secretos ni identificadores privados;
2. fije trust roots fuera del payload del caller: claves públicas/CA,
   algoritmo, identidad del firmante, vigencia, revocación y rotación;
3. verifique una firma desprendida sobre los bytes crudos y sobre un receipt
   canónico que incluya request, cutoff, response y server time;
4. implemente parsers allowlisted y versionados para cada endpoint/documento;
   cada campo de cuenta, instrumento, fee, funding, book, liquidación y FX debe
   salir del parser, nunca ser proporcionado en paralelo por el caller;
5. ligue `raw_sha256 + parser_version + parsed_payload_sha256 + scope` y haga
   fallar diferencias entre Spot/perp/account/cutoff;
6. autentique los memos manuales legal, fiscal y de contraparte con firma,
   identidad profesional revisada, jurisdicción, alcance y expiración, sin
   guardar PII en el repo;
7. mantenga KYC/capacidades de cuenta en un import sanitizado y firmado, sin
   secretos ni permisos de trade/transfer/withdraw;
8. pase stress tests offline/Demo y una auditoría adversarial antes de retirar
   los tres blockers inmutables, lo cual requiere un nuevo schema/policy hash.

Sólo una versión posterior que implemente y pruebe todo lo anterior podrá
emitir `FEASIBLE_FOR_DEVELOPMENT_COLLECTION` y proponer un plan de recolección.
Ese plan deberá seguir sin P&L/holdout hasta preregistrar de forma independiente
la hipótesis, costos, falsificadores y presupuesto de trials. Cualquier
ejecución con derivados requiere una decisión humana y una ruta de seguridad
distinta de Gate 4 Spot.
