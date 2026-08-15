# CCData attested loader v1

Estado: infraestructura offline terminada; evidencia externa real pendiente.
Este contrato no afirma que CCData haya firmado nada, no compra datos, no abre
red, no genera señales/P&L y no elimina el blocker del gate de world order flow.

El loader está en `quant_trade.data.ccdata_attested_loader`. La solicitud que
define qué se debe cotizar está en
`configs/data/ccdata_world_order_flow_request_v1.yaml`; la investigación de
producto/licencia está en `docs/CCDATA_WORLD_ORDER_FLOW_PROCUREMENT.md`.

## Frontera de confianza

Un SHA-256 local detecta cambios, pero el mismo actor que fabrica bytes también
puede fabricar el hash. Por eso el loader exige una raíz Ed25519 entregada por
el operador **fuera** del bundle:

- issuer y key id fijados por política;
- clave pública Ed25519 de 32 bytes y su fingerprint;
- vigencia de la clave;
- product ids permitidos.

`attestation.json` no puede aportar ni ampliar esa raíz. La API pública tampoco
permite inyectar un verificador: siempre usa la verificación Ed25519 de
`cryptography`. La firma desprendida cubre los bytes canónicos exactos de la
attestation; esta liga el SHA-256 de los bytes exactos de `manifest.json`.
Una clave incluida dentro del bundle, una firma inválida, una clave expirada o
un producto fuera de scope cierran el loader.

La raíz real deberá fijarse desde un canal independiente y ser revisada por una
segunda persona. Una clave creada por el recolector no constituye attestation
externa. Las pruebas usan una clave Ed25519 de fixture únicamente para verificar
el protocolo; jamás pueden autorizar un dataset real.

## Bundle exacto

```text
bundle/
  manifest.json       # JSON canónico + LF
  attestation.json    # JSON canónico + LF, firmado
  attestation.sig     # firma Ed25519 binaria desprendida
  source/...          # bytes externos content-addressed por receipts
  derived/
    observations.jsonl
    venues.jsonl
    revisions.json     # revised_at + hashes exactos old/new
```

El manifiesto usa schema v1, proveedor `CCData`, product/delivery ids,
`cryptocompare_signed_volume_g11_multi_exchange`, operación(es), versión de
schema, identidad/versión del parser y métodos de clasificación/agregación. Se
rechazan campos desconocidos y JSON no canónico.

La lista `required_provider_fields` fija buy/sell/unknown, base/quote e IDs,
market/instrument/mapping, conteos, transform, `SIDE`, `STATUS`, `SOURCE`,
`CCSEQ`, timestamps reportados/recibidos y el tipo de corrección/invalidation.
Que el OpenAPI público tenga algunos de estos campos no prueba que el producto
contratado entregue el agregado G11 multi-venue.

Cada byte externo tiene un receipt append-only con:

- sequence, receipt id, role y ruta contenida sin symlinks;
- tamaño y SHA-256 recalculados del archivo;
- `available_at` y `captured_at` canónicos;
- para datos: vintage id, revision id/sequence y predecessor superseded;
- hash del receipt y hash del receipt previo.

Se exige exactamente un receipt de cada tipo: cotización comercial, términos,
grant ejecutado, schema del proveedor, política de revisiones y calendario del
paper; además, uno o más `SIGNED_VOLUME_RAW`. Un quote no sustituye el grant.

## Licencia y vintages

La attestation firmada debe afirmar explícitamente autenticidad de bytes,
schema, constituents, cotización, términos, grant y correction log. También
debe confirmar que se revisó la restricción amplia de “Financial Product” y que
se permite trading con capital propio.

El manifiesto liga los bytes exactos de quote/terms/grant y exige vigencia en
México para:

- investigación comercial interna;
- almacenamiento raw local;
- backtests/señales derivadas;
- trading únicamente con capital propio.

Una historia actualmente restated no es point-in-time. La política firmada debe
confirmar vintages preservados, correcciones append-only, instante `revised_at`,
valor anterior y nuevo, y completitud del historial hasta el cutoff. `CCSEQ` y
`RECEIVED_TIMESTAMP` sin esa cadena explícita son insuficientes.

## Reparse y causalidad

El loader no inventa el schema raw. Recibe un parser revisado cuyo nombre,
versión, product id, schema version y hash de schema deben coincidir byte por
byte con el manifiesto firmado. Reparsea cada entrega raw y exige igualdad
exacta con ambos JSONL derivados.

La fila normalizada fija identidad `CMC:<cmc_id>`, chain/native-contract,
fecha, fiat G11, buy/sell positivos, venues constituyentes, timestamps causales,
vintage/revision y source receipt. Para cada celda se elige la última revisión
que ya estaba disponible en `knowledge_cutoff_utc`; las futuras se excluyen.
El digest de filas y receipts causales es independiente del manifiesto completo,
por lo que anexar una entrega futura conserva exactamente el prefijo.

## Resultado y límite de autorización

`LoadedAttestedCCDataBundle` solo puede construirse con la capacidad privada del
loader; una instancia forjada es rechazada. Aun una carga válida mantiene en
`false` autorización de uso comercial, preregistro, señal, backtest, P&L,
holdout, red y dinero real. Solo dice que la firma verificó contra **la raíz
suministrada** y que la proyección estructural fue rehashed/reparsed. No dice
que esa raíz sea realmente de CCData o de un revisor aceptable.

No se conecta todavía con `evaluate_world_order_flow_data_feasibility`; el
blocker `EXTERNAL_SOURCE_LICENSE_VINTAGE_ATTESTATION_NOT_IMPLEMENTED` permanece.
La integración futura requiere una raíz pública real del proveedor/revisor, un
bundle contratado real, el parser del schema contratado y revisión
independiente. Hasta entonces, no hay evidencia de edge ni razón para depositar
los US$200.
