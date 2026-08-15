# World order flow: gate de factibilidad de datos

Estado actual: `INSUFFICIENT_EVIDENCE`. Este gate no implementa una estrategia,
señal, modelo ML, sort, backtest, trial, P&L, acceso al holdout, red ni dinero
real. Incluso un panel estructuralmente completo no puede superar
`INSUFFICIENT_EVIDENCE` en v1. Ya existe el loader offline y fail-closed
`quant_trade.data.ccdata_attested_loader`, pero este gate v1 todavía no consume
su resultado y aún no existen una raíz pública confiable, licencia ejecutada,
bundle firmado, parser contratado ni vintages reales del proveedor.

## Hipótesis que motivó el gate

La fuente primaria es Anastasopoulos, Gradojevic, Liu, Maynard y Tsiakas,
“Order flow and cryptocurrency returns”, *Journal of Financial Markets* 79
(2026), 101047, DOI
[`10.1016/j.finmar.2026.101047`](https://doi.org/10.1016/j.finmar.2026.101047).

El artículo publicado usa 84 monedas, del 1 de enero de 2018 al 30 de junio de
2022. Exige capitalización mayor a US$1M al inicio, precio y volumen continuos
no nulos y excluye stablecoins. La versión de conferencia de 2024/2025 decía 82
monedas; 84 es la cifra de la versión final publicada y no deben mezclarse las
dos versiones.

La definición exacta no es “volumen que subió menos volumen que bajó” ni una
vela de Binance:

1. CryptoCompare/CCData entrega volumen **buyer-initiated** y
   **seller-initiated**, agregado en la fuente sobre más de 300 exchanges.
2. Se calcula flujo en cada una de 11 monedas fiat: USD, EUR, GBP, JPY, CHF,
   CAD, AUD, NZD, NOK, SEK y KRW.
3. Para cada moneda/día, el flujo original es la diferencia logarítmica entre
   volumen comprador y vendedor.
4. Cada flujo se divide entre su volatilidad de las últimas 30 observaciones.
5. `world order flow` primero suma los 11 volúmenes compradores, suma los 11
   volúmenes vendedores, toma la diferencia logarítmica y aplica la misma
   estandarización de 30 observaciones.

El calendario diario de la fuente excluye fines de semana y feriados de
Estados Unidos. Son 30 **observaciones** de ese calendario, no 30 días
naturales. Los returns semanales del artículo cubren sábado 00:00 GMT a viernes
23:59 GMT; esa diferencia de calendario tendría que resolverse en una futura
especificación, no improvisarse en este gate.

## Evidencia económica, sin trasladarla al proyecto

La fuente estudia predicción de retorno `t+1`, sorts equal-weight por quintiles
y rebalanceo diario o semanal. Para el sort directo, ortogonaliza world order
flow respecto del retorno del mismo período para separar reversión de corto
plazo. También prueba OLS, ridge, lasso, elastic net, PCR, random forest,
stochastic gradient boosting, redes NN1–NN4 y combinaciones de modelos. Su test
OOS final va del 18 de febrero de 2020 al 30 de junio de 2022.

Esos resultados no constituyen evidencia para `quant-trade`: la publicación es
posterior al holdout actual, el objetivo del repo es long-only spot mientras el
resultado principal del paper suele ser long-short, y faltan datos autenticados
y costos/ejecución del venue objetivo. Por eso este módulo no contiene ninguna
de esas señales o variantes.

## Por qué los klines locales no sirven

`venue_klines.py` normaliza cada barra a OHLC, volumen base y turnover quote.
Al hacerlo, descarta los campos adicionales del wire de Binance, incluido
taker-buy. Las respuestas raw sí pueden quedar cacheadas, pero aun extrayendo
ese campo solo tendríamos:

- una venue;
- una cotización USDT, que no es USD ni una cesta G11 fiat;
- taker-buy y un complemento derivado, no el contrato signed buy/sell de la
  fuente;
- ninguna agregación multi-exchange de CryptoCompare;
- ninguna prueba PIT de la metodología histórica o sus revisiones.

El test adversarial codifica esta sustitución como `NO_GO`.

## Contrato de factibilidad v1

Por cada activo, fecha y moneda G11 se requieren volúmenes comprador y vendedor
positivos, identidad estable (`cmc_id`, chain y contract/native id), fechas
`computed_at`, `published_at` y `observed_at` anteriores a la decisión,
metodología/version, lista de fuentes/venues, hashes de bytes y términos de
licencia comercial. El panel estructural exige las 30 fechas por 11 monedas
para al menos 84 activos y verifica invariancia por prefijo.

Los hashes y metadatos recibidos por este gate son declaraciones del llamador,
no autenticidad criptográfica. Por ello v1 añade siempre
`EXTERNAL_SOURCE_LICENSE_VINTAGE_ATTESTATION_NOT_IMPLEMENTED`: el nombre se
refiere a la integración de la atestación en este gate, no a la ausencia del
loader aislado. Un sucesor solo podrá removerlo si consume un bundle verificado,
recalcula los hashes, valida una licencia comercial para trading con fines de
lucro y prueba que el proveedor conserva snapshots/vintages point-in-time de clasificación,
mapeos y agregación.

La API pública gratuita de CCData está descrita por el proveedor como Creative
Commons Attribution-NonCommercial; hacer dinero con esos datos requiere un
servicio/licencia de pago. Además, el endpoint OHLCV público ordinario no prueba
que entregue el mismo signed-volume histórico usado por los autores. La
publicación dice que los datos se ofrecen bajo solicitud, lo cual tampoco
concede por sí solo derechos comerciales ni demuestra vintages.

## Próximo paso permitido

Solicitar al proveedor/autores, antes de cualquier preregistro:

1. contrato/schema exacto de signed buy/sell volume G11 multi-exchange;
2. cobertura actual point-in-time suficiente y mapeo estable a CMC/chain;
3. política de correcciones y snapshots históricos reproducibles;
4. precio y licencia comercial escrita para investigación y trading propio;
5. lista de venues constituyentes por vintage y bytes descargables con hash.

Si cualquiera falla, la familia queda `NO_GO` o `INSUFFICIENT_EVIDENCE`. Si
algún día todos se autentican, el único siguiente paso sería redactar y revisar
un `ExperimentSpec` separado antes de abrir datos económicos. Nunca promoción
automática ni dinero real.
