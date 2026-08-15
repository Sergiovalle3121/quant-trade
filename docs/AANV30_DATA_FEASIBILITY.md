# Gate prospectivo de factibilidad de datos AANV30

## Resultado que este componente puede producir

Este componente solamente identifica qué evidencia falta antes de poder
considerar un preregistro futuro. No contiene una estrategia, un trial, una señal, un
backtest, un ranking, una consulta de red, un registro de candidatos, acceso al
holdout ni un cálculo de P&L. El schema v1 **no puede producir ni construir**
`FEASIBLE_FOR_PREREGISTRATION`: sus entradas son objetos suministrados por el
llamador y no pueden demostrar por sí mismas que un SHA corresponda a bytes
reabiertos, que los datos pertenezcan a una publicación histórica disponible
en esa fecha o que una licencia permita realmente el uso comercial.

El módulo es
[`src/quant_trade/data/aanv30_feasibility.py`](../src/quant_trade/data/aanv30_feasibility.py).

## Definición congelada

Para una decisión en `t`, AANV30 se define como:

```text
media aritmética de ActiveAddresses de cada uno de los 30 días UTC completos
inmediatamente anteriores a t
-----------------------------------------------------------------------------
                  market cap USD exactamente en t
```

La media usa 30 conteos diarios. **No** es el número de direcciones distintas
en la ventana completa de 30 días. Una dirección activa en cinco días puede
contribuir a los cinco conteos diarios. El gate rechaza explícitamente
`WINDOW_UNIQUE_ACTIVE_ADDRESSES`; no transforma una métrica en la otra.

Esta hipótesis procede de Luca J. Liebi, *Is there a value premium in
cryptoasset markets?*, *Economic Modelling* 109 (2022), artículo 105777,
[DOI 10.1016/j.econmod.2022.105777](https://doi.org/10.1016/j.econmod.2022.105777).
La asociación publicada es una motivación para investigar, no una promesa de
replicación ni rentabilidad.

Hay evidencia que obliga a ser escépticos. Mercik, Zaremba y Demir incluyen
AANV dentro de un “factor zoo” de 36 características y encuentran que un grupo
pequeño de factores elimina los alphas significativos, que las variables de
liquidez dominan y que la selección concreta tiene persistencia temporal
limitada. Eso no refuta AANV30 por sí solo, pero sí contradice tratar un
hallazgo univariado como un edge permanente:
[*Crypto factor zoo (.Zip)*, DOI 10.1016/j.irfa.2026.105137](https://doi.org/10.1016/j.irfa.2026.105137).

## Evidencia exigida por activo

Cada activo necesita una identidad estable y coincidente en todas las fuentes:

- `chain_id`;
- `contract_or_native_id`, que debe identificar explícitamente un contrato o
  el activo nativo de la cadena;
- `cmc_id` numérico estable.

No se usa ticker como identidad. Colisiones CMC↔cadena/contrato, identidades
duplicadas y cambios de identidad dentro de la ventana producen `NO_GO`.

Para cada uno de los 30 días exactos se exige:

- conteo entero no negativo y semántica `DAILY_ACTIVE_ADDRESSES`;
- `observed_at_utc`, `computed_at_utc` y `published_at_utc` point-in-time;
- observación posterior al cierre del día, seguida por cálculo y publicación,
  todo disponible no después de la decisión;
- nombre y versión del método, nombre de la fuente y SHA-256 de los bytes
  fuente;
- licencia `COMMERCIAL_USE_PERMITTED`, SHA-256 de los términos archivados y
  momento en que se verificaron.

El método diario debe permanecer constante durante la ventana y también entre
todos los activos localmente completos. El proveedor, nombre de la definición
y versión deben ser exactamente iguales en la sección transversal; se aplica
la misma regla, por separado, al proveedor/definición/versión de market cap. Una
mezcla explícita produce `NO_GO`, porque comparar conteos con metodologías
distintas no es un sort transversal interpretable. Es indispensable
conservar además su definición operativa —por ejemplo, qué transacciones y qué
lados de una transferencia cuentan— porque “active address” no es naturalmente
idéntico entre cadenas UTXO, account-based, L1, L2 y tokens. El gate comprueba
procedencia y consistencia local; un PASS todavía requiere revisión humana de
comparabilidad antes de crear un preregistro.

El denominador necesita una observación de market cap USD efectiva exactamente
en `t`, positiva y con los mismos campos point-in-time, método, versión, bytes y
licencia. No se permite tomar el cierre posterior ni reconstruir el valor con
información futura.

Una etiqueta de licencia no sustituye una revisión legal. Los campos
`COMMERCIAL_USE_PERMITTED`, hash de términos y fecha de verificación son
requisitos de forma, pero continúan siendo autoafirmados en v1. `UNKNOWN` nunca
se convierte en permiso y una etiqueta aparentemente válida tampoco elimina el
blocker `COMMERCIAL_LICENSE_ATTESTATION_MISSING`. El repositorio no redistribuye
los bytes ni determina derechos por sí solo.

Aunque v1 conserva el SHA-256 declarado, no abre ni recalcula los bytes. Por
eso un llamador podría cambiar `active_addresses` y conservar el mismo SHA. El
digest causal del veredicto sí cambia con el valor declarado, pero el resultado
permanece bloqueado por `SOURCE_BYTES_REHASH_ATTESTATION_MISSING`. También queda
siempre presente `HISTORICAL_VINTAGE_ATTESTATION_MISSING` hasta disponer de una
cadena de recibos que demuestre cuándo existía cada vintage.

## Cobertura y estados

La barrera provisional es de 100 activos completamente elegibles. Es solamente
la cantidad mínima para que un posible diseño futuro de quintil superior pueda
contener 20 activos; dicho diseño no está implementado aquí.

- `FEASIBLE_FOR_PREREGISTRATION`: estado reservado para un schema posterior con
  loader de atestación externo. El constructor público lo rechaza en v1.
- `INSUFFICIENT_EVIDENCE`: existe un desconocido o faltante, una publicación no
  estaba disponible en la decisión, hay menos de 100 activos completos o solo
  existen metadatos autoafirmados. Aun con 100 activos perfectos de prueba, v1
  añade de forma inmutable los blockers de rehash de bytes, vintage histórico y
  licencia externa.
- `NO_GO`: existe una contradicción explícita, como semántica de ventana única,
  licencia no comercial, colisión de identidad, hash malformado, duplicado,
  market cap inválido u orden temporal imposible.

`NO_GO` tiene precedencia sobre faltantes. Todos los resultados fijan en
`false` autorización de dinero real, señales, P&L, holdout y red, además de
`profitability_evidence=false`.

## Invariancia causal

Antes de evaluar y sellar, el módulo elimina:

1. observaciones publicadas después de `decision_at_utc`;
2. días fuera de las 30 fechas exigidas.

Después ordena la evidencia causal y calcula su SHA-256 canónico. Agregar una
corrección, un activo o una observación publicados en el futuro debe producir
exactamente los mismos bytes del veredicto para el prefijo anterior. Las
pruebas adversariales verifican también reordenamientos, cobertura 29/30,
duplicados, licencias desconocidas y prohibidas, identidad, hashes, timestamps
y la diferencia entre media diaria y direcciones únicas de ventana.

La invariancia prueba que este evaluador no incorpora registros declarados como
futuros. No prueba que los timestamps declarados sean auténticos; esa es
precisamente la función pendiente del loader atestado.

## Universo y ejecutabilidad todavía no especificados

Los números 100 y 20 son únicamente una comprobación aritmética de cobertura
para un posible quintil futuro. V1 no define el universo point-in-time de market
cap, venue, liquidez, tradabilidad, stablecoins, listings, filtros de símbolo,
costos ni capacidad. Tampoco elige activos ni afirma que alguno sea ejecutable.
Todo ello pertenecería a una especificación futura separada, posterior a la
atestación de datos.

## Próximo paso permitido

El siguiente componente permitido es un loader offline que reabra bytes
receipt-bound, recalcule hashes, vincule cada valor extraído con esos bytes,
atestigüe el vintage histórico y valide evidencia externa de licencia. Después
de revisión independiente, un nuevo schema podría habilitar el estado reservado
`FEASIBLE_FOR_PREREGISTRATION`. Solo entonces se consideraría redactar —en un
cambio separado y antes de calcular resultados— una especificación falsable.
Hasta entonces el estado económico de AANV30 es `INSUFFICIENT_EVIDENCE`; no
existe un resultado de rentabilidad ni ejecutabilidad que reportar.
