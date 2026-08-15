# CCData / CoinDesk Data: solicitud para world order flow

Estado: `QUOTE_REQUIRED`. No se compraron datos, no se creó una cuenta, no se
envió información personal y no existe autorización de P&L ni de dinero real.

## Lo que sí está confirmado públicamente

La plataforma actualmente soportada es CoinDesk Data API. El OpenAPI público
observado el 14 de agosto de 2026 UTC declaró OpenAPI `3.0.3`, versión de API
`2.1.2009` y la operación `spot_v1_historical_days`. La respuesta diaria Spot
define, entre otros, `VOLUME_BUY`, `VOLUME_SELL`, `VOLUME_UNKNOWN` y sus
equivalentes de quote. El snapshot consultado tuvo 4,319,125 bytes y SHA-256
`d99c9bd28cb7b8d7f3be33c148ff3291863a10543429c57c6f54b6037171d82c`.
Ese hash es solo una observación reproducible de la documentación pública; no
es un compromiso permanente del proveedor ni una licencia.

Ese endpoint exige `market` e `instrument`; el enum público observado listó
182 markets Spot y no incluyó `CCCAGG`. Una llamada sin API key respondió 401.
Por tanto, que el schema tenga buy/sell no demuestra que la suscripción normal
entregue el agregado multi-exchange del paper. Eso debe aparecer como producto
o transformación contractual en la cotización, o habrá que comprar trades por
venue y reproducir la agregación con su historial de mappings.

El plan Personal es no comercial. Los planes Start-Up y Enterprise requieren
contacto; la página no publica un precio. Start-Up anuncia licencia comercial
predefinida y uso interno, pero solo 365 días de historia diaria. Enterprise
anuncia más de diez años, trades y entrega S3/Blob/BigQuery, por lo que es la
primera categoría que parece cubrir la ventana 2018--2023. Esto debe confirmarlo
una cotización escrita.

El proveedor anunció que eliminó el acceso gratuito a la API el 21 de mayo de
2026. El plan Personal que todavía aparece en la tabla no debe tratarse como
una vía de adquisición disponible sin confirmación.

El contrato API estándar permite uso interno sujeto al plan, pero contiene una
restricción amplia sobre uso relacionado con un `Financial Product`. Como la
definición incluye monedas y tokens, una licencia aceptable debe autorizar por
escrito investigación comercial interna, señales derivadas y trading por
cuenta propia. `Commercial` en una tabla de precios no basta.

La licencia también advierte que los datos no están destinados a trading y
limita su conservación tras terminar la suscripción. La enmienda debe permitir
explícitamente trading Spot con capital propio y conservar manifests, snapshots
sellados y backups de auditoría después de la terminación.

## Producto que se debe cotizar

El contrato machine-readable está en
`configs/data/ccdata_world_order_flow_request_v1.yaml`. En resumen:

- Spot, 2018-01-01 a 2023-11-28 para desarrollo, más entrega prospectiva;
- al menos 84 identidades estables, preferentemente 100;
- las once cotizaciones fiat USD, EUR, GBP, JPY, CHF, CAD, AUD, NZD, NOK, SEK y
  KRW;
- todas las venues Spot constituyentes, no Binance/USDT como sustituto;
- buy/sell/unknown en base y quote, más conteos de trades;
- identidad `BASE`, `QUOTE`, sus IDs y `TRANSFORM_FUNCTION`;
- mappings y composición de venues point-in-time;
- CCSEQ, received timestamps e invalidaciones/correcciones que permitan
  reconstruir qué se conocía en cada fecha;
- `SIDE`, `SOURCE`, `STATUS` y un revision log con `revised_at`, estado anterior
  y nuevo; el `STATUS` actual sin fecha de cambio no reconstruye un vintage;
- manifiesto inmutable con SHA-256, versión, revisión, generated-at y as-of;
- licencia explícita para guardar raw, investigar, derivar señales y operar
  únicamente capital propio, sin redistribuir los datos.

Un histórico actual ya corregido no demuestra un vintage histórico. Es
aceptable una cadena completa de mensajes originales, correcciones e
invalidaciones si puede reproducirse filtrando por `RECEIVED_TIMESTAMP`; de lo
contrario se requieren snapshots/as-of del proveedor. Un ETag o un hash creado
por nosotros solo prueba los bytes recibidos ahora.

## Texto listo para ventas

Subject: `Quote request: point-in-time signed spot order-flow data for internal proprietary research`

> We are a pre-revenue quantitative research project requesting the lowest-cost
> commercial plan or one-time extract that satisfies the scope below. The data
> will be used internally for research, backtesting, derived signals and
> proprietary trading with the customer's own capital. We will not redistribute
> raw data, manage client assets, sell signals or display licensed data.
>
> Please quote: (1) a historical delivery from 2018-01-01 through 2023-11-28;
> (2) prospective daily updates; (3) all setup, delivery, tax and minimum-term
> charges; and (4) data-retention rights after termination.
>
> Required scope is Spot data for at least 84 stable asset identities across all
> supported constituent venues and the quote currencies USD, EUR, GBP, JPY,
> CHF, CAD, AUD, NZD, NOK, SEK and KRW. We need daily buyer-, seller- and
> unknown-initiated base/quote volumes and trade counts, plus mapping and venue
> constituent history.
>
> For point-in-time reproducibility, please confirm whether historical delivery
> contains original CCSEQ messages, invalidations/corrections, reported and
> received timestamps, and whether a dataset can be replayed as known at an
> arbitrary as-of timestamp. If not, please describe available immutable
> snapshots, revision IDs and restatement policy.
>
> Before purchase, please provide a sample covering at least 10 assets, all 11
> quote currencies, 30 observations and all constituent venues; the exact
> machine-readable schema; a per-object SHA-256 manifest; dataset/revision/as-of
> identifiers; and a signed or otherwise independently verifiable delivery
> attestation.
>
> Please confirm in the written licence that internal commercial research,
> storage of raw responses, derived backtests/signals, and own-account trading
> are permitted. Please identify any restrictions involving a “Financial
> Product”, derived data, audit access, retention, or model outputs.

## Respuestas que deben bloquear la compra

- solo ofrece 365 días o historia restated sin correcciones/vintages;
- no define buyer/seller initiated o solo entrega taker-buy de una venue;
- sustituye las once fiat por USDT;
- no entrega mappings/constituents históricos;
- la licencia no autoriza explícitamente trading por cuenta propia;
- el costo fijo vuelve inviable una cuenta de US$200;
- no permite una muestra verificable antes de contratar.

Además, aun una oferta técnicamente correcta no se compra hasta que el P&L
anual neto esperado en escenario p25 supere dos veces todos los costos fijos.
Con US$200 y sin edge validado, ese techo aún no puede calcularse; el gate de
compra permanece `INSUFFICIENT_EVIDENCE`.

## Datos necesarios para enviar la solicitud

El formulario oficial exige nombre, apellido, empresa, cargo, email, sector y
consentimiento de comunicaciones. Esos datos no deben inferirse ni guardarse en
el repositorio. Alternativamente, el acuerdo publica `data@ccdata.io` como
contacto. El envío es una acción externa y debe hacerse desde la identidad que
aceptará la cotización y los términos.
