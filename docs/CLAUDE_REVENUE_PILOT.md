# Piloto de auditoría: de herramienta interna a algo vendible

Estado: **LISTO PARA 3 PILOTOS PRIVADOS — SIN DEMANDA VALIDADA — NO ES UNA
PROYECCIÓN DE INGRESOS**

Este documento no reemplaza a [`AUDIT_PILOT_PLAYBOOK.md`](AUDIT_PILOT_PLAYBOOK.md),
que ya define el cliente objetivo, el alcance de seguridad, la secuencia de 30
días y el ledger de métricas. Aquí está lo que faltaba para que un extraño pueda
usar el auditor sin Sergio en la llamada, y lo que se cambió en el código para
lograrlo.

## Por qué esta vía y no la otra

`docs/CLAUDE_ALPHA_SEARCH_REPORT.md` calcula, con el módulo
`quant_trade.ops.growth_feasibility`, que convertir US$100 en US$1,000,000 en un
mes tiene un techo de probabilidad de **1 en 112,915** sin ventaja, y que ninguna
volatilidad lo mejora. Un primer cliente de auditoría no tiene ese techo.

Esto no dice que alguien vaya a pagar. Dice que la probabilidad de que alguien
pague es una cantidad desconocida y averiguable, no una cantidad conocida y
minúscula. Por eso esta vía va primero.

## Qué se cambió, y qué problema resolvía cada cosa

| Cambio | Problema que resolvía |
|---|---|
| `quant-trade audit init` | El cliente tenía que calcular a mano el SHA-256 de su dataset y de su trial ledger y pegarlos en dos archivos. Un digest equivocado es **indistinguible** de resultados nunca ligados a los datos: el cliente recibía `NO_GO` por un error de dedo. |
| `quant-trade audit verify` | El `bundle_digest` existía pero el cliente no tenía forma de recomputarlo. Una dirección de contenido que nadie más puede verificar es decoración. |
| Orden por instrumento | Un panel exportado como `(symbol, timestamp)` —la forma que tiene casi todo research real— daba `TIMESTAMP_CAUSALITY = NO_GO`. La fixture limpia es de un solo símbolo, así que el bug **nunca aparecía en la demo**: habría aparecido en el primer paquete pagado. |
| `finding_class: DEFECT \| RESULT` | Un paquete metodológicamente impecable que simplemente no le gana a buy-and-hold recibía el mismo rojo que uno contaminado con look-ahead. El veredicto no cambió; ahora el reporte distingue un error de método de un resultado correctamente medido. |
| `--redact` | `audit.json` embebía rutas absolutas del disco, filtrando el layout del operador y los nombres originales del cliente en el entregable. |
| Exit codes 0/1/2 | `NO_GO` salía 0, así que nada se podía automatizar ni usar como gate. |
| `configs/audit/fixtures/** -text` | Las fixtures están fijadas por hash pero dependían del `text=auto` global. Un clone que reintrodujera CRLF convertía la demo "clean → PASS" en un `NO_GO` por manifest mismatch. |
| `artifacts/audit-sample/` | No existía ningún reporte terminado que enseñarle a un prospecto sin correr la herramienta. |

## Lo que el cliente hace, de principio a fin

Todo corre en la máquina del cliente. Nada sale de ahí salvo lo que él decida
enviar.

```bash
pip install -e ".[dev]"
quant-trade audit init --package-dir ./mi-research --evaluation-cutoff-utc "2024-12-31T23:59:59Z"
```

Eso deja cuatro archivos junto a su `dataset.csv`, con los dos digests ya
calculados. El cliente llena únicamente lo que sólo él puede saber:

| Archivo | Campo | Por qué se pide |
|---|---|---|
| `dataset.manifest.json` | `source_name`, `data_source` | Quién produjo los bytes y de qué feed vienen |
| | `captured_at_utc` | Cuándo los bajó; debe ser igual o anterior al cutoff |
| | `license` | Su derecho a usarlos |
| `results.json` | `strategy_net_return` | Neto de todo costo que declare |
| | `costs.*` | Los costos que efectivamente cargó |
| | `execution.signal_lag_bars` | Barras entre decisión y fill, mínimo 1 |
| | `benchmarks` | Al menos un retorno neto contra el cual comparar |
| `trial_ledger.json` | `trials` | Cada variante evaluada, **incluidas las que descartó** |

Luego:

```bash
quant-trade audit run --config ./mi-research/audit.yaml --out-dir ./salida --redact
```

Sale `0` si `PASS`, `1` si `INSUFFICIENT_EVIDENCE`, `2` si `NO_GO`. Y cualquiera
que reciba el reporte puede confirmar que no fue editado después:

```bash
quant-trade audit verify --bundle ./salida/audit.json
```

Un `FILL_ME` sin reemplazar nunca puede pasar: el auditor lo rechaza. Eso es
deliberado — una plantilla que pasa sin llenarse no probaría nada.

## Guion de demo, dos minutos

Corre los dos ejemplos ya commiteados y muestra la diferencia:

```bash
quant-trade audit run --config configs/audit/clean.yaml --out-dir ./demo-limpio
quant-trade audit run --config configs/audit/contaminated.yaml --out-dir ./demo-sucio
```

Tres cosas que enseñar, en este orden:

1. **Look-ahead**: el paquete contaminado tiene una columna `future_return` y
   timestamps posteriores al cutoff. `LOOKAHEAD_COLUMNS` y `TIMESTAMP_CAUSALITY`
   se ponen en `NO_GO`, clase `DEFECT`.
2. **Ejecución en la misma barra**: `signal_lag_bars: 0` → `NEXT_BAR_EXECUTION`
   en `NO_GO`. Decidir y ejecutar al mismo precio es la forma más común de
   fabricar un backtest rentable sin darse cuenta.
3. **Bytes que no coinciden**: `results.json` declara un hash que no corresponde
   a `dataset.csv` → `RESULT_DATASET_BINDING` en `NO_GO`. Los resultados no
   estaban ligados a los datos que dicen haber usado.

Y luego la línea que separa esto de una promesa: aun con `PASS`, el reporte
exporta `expected_profit_established=false` y `real_money_authorized=false`.
Intentar construir un veredicto con esos campos en `true` **lanza una
excepción** (`audit/models.py`). No es una política escrita; es una invariante
del código.

## Lo que hay que decirle al cliente antes de que lo infiera mal

Los costos, benchmarks, `strategy_net_return` y `signal_lag_bars` los **declara
el cliente**; nada de eso se recalcula desde el dataset. La afirmación honesta
es que un paquete es *internamente consistente y ligado a bytes*, no que sus
números fueron reproducidos de forma independiente.

La palabra "auditoría" invita a la lectura fuerte. Dilo tú antes de que él lo
asuma; es lo que separa un piloto que se repite de uno que termina en una
discusión sobre qué se había prometido.

## Límites conocidos, sin maquillar

Estos son reales y hay que decirlos en la llamada, no descubrirlos a mitad del
piloto:

- **Sólo CSV/JSON/JSONL, 25 MB por defecto** (tope duro 100 MB), leído completo
  a memoria. **No hay parquet**, que es justamente lo que tiene la mayoría de
  los equipos de research reales. Es la limitación más probable de aparecer.
- Un dataset + un `results.json` por auditoría. No hay paquetes multi-archivo ni
  comprimidos.
- `LOOKAHEAD_COLUMNS` marca `NO_GO` ante cualquier columna que contenga
  `target_return`, `future_` o `lead_`. En research supervisado esos son nombres
  legítimos de etiquetas. Puede haber falsos positivos; hay que revisarlos a mano.
- No hay DSR, PSR, PBO, independencia walk-forward, concentración ni capacidad.
  Están fuera del MVP a propósito, no auditados y presentados como si lo estuvieran.
- **No hay licencia, términos de servicio, aviso de privacidad ni DPA en el
  repositorio.** El playbook ya lo señala. Para pilotos privados hace falta un
  acuerdo escrito de alcance y retención; esto no es asesoría legal.
- Correrlo hoy requiere instalar toda la plataforma (numpy, pandas, pydantic,
  rich) aunque el módulo de auditoría sólo necesite PyYAML, typer y la stdlib.
  No hay distribución independiente y **no se le puede entregar este repo
  privado a un cliente**.

## Los tres pilotos

La secuencia de 30 días está en el playbook y no se repite aquí. Lo único que
este documento agrega es la condición de entrada: **los días 1–5 ya están
hechos**. La demo es repetible desde un checkout limpio, los ejemplos están
commiteados, y el camino `init → run → verify` funciona sin intervención.

Lo siguiente no es código. Son diez conversaciones, y ninguna línea de este
repositorio las sustituye.

Recuerda el criterio de corte del playbook: se continúa sólo si al menos un
cliente **pagó de verdad**, no si dijo que pagaría. Pipeline, interés verbal y
disposición hipotética no son ingresos.

## Lo que no se construyó, a propósito

Sin billing, sin multi-tenancy, sin subida hosteada, sin sandbox para código
arbitrario, sin precios. El playbook lo prohíbe antes de validar demanda y esa
prohibición sigue en pie. Construir la plataforma antes de tener un cliente que
pagó es la forma más cara de evitar la conversación incómoda.
