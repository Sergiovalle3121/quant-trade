# Plan de construcción de patrimonio con `quant-trade`

## Decisión

`quant-trade` tendrá dos motores independientes:

1. **Ingresos del producto:** convertir sus controles de sesgo, procedencia,
   costos y holdout en un auditor reproducible para investigadores cuantitativos.
2. **Investigación propietaria:** falsar H2 (salida por deterioro de ranking y
   liquidez) sobre un panel causal de una sola venue.

Ninguno de los motores garantiza ingresos ni rentabilidad. El primero busca
crear flujo de efectivo mediante clientes; el segundo busca evidencia de una
ventaja limitada. No se financiará el segundo suponiendo que el primero venderá.

## Qué significan US$200

El límite sellado del canario es:

```text
canario permitido = min(10% del capital total de riesgo, US$500)
límite por activo = 5% del canario
activos distintos requeridos = 20
```

Por lo tanto, “tengo US$200” tiene dos interpretaciones muy diferentes:

| Escenario | Capital total de riesgo | Canario propuesto | Resultado previo a datos de venue |
|---|---:|---:|---|
| US$200 es todo el capital | US$200 | máximo US$20 | Cada activo recibe como máximo US$1; normalmente no alcanza el mínimo ejecutable. |
| US$200 es el canario | al menos US$2,000 | US$200 | Respeta el límite de 10%; todavía necesita 20 símbolos y límites reales vigentes. |

El segundo escenario **no dice que US$2,000 sean suficientes para ser
rentable**. Solo demuestra que un canario de US$200 estaría respaldado por el
capital mínimo exigido por la política.

El evaluador recibe `minimum_notional_usd` y
`minimum_notional_cushion_fraction` como supuestos configurables. Por ejemplo,
un mínimo suministrado de US$5 y un colchón de 20% implican:

```text
desembolso mínimo por activo = 5 × 1.20 = US$6
canario mínimo para un límite de 5% = 6 / 0.05 = US$120
capital total mínimo que lo respalda = 120 / 0.10 = US$1,200
```

Ese US$1,200 respalda el **canario ejecutable mínimo de US$120** bajo el
ejemplo. Respaldar específicamente el canario propuesto de US$200 exige
US$2,000; el resultado expone ambas cantidades por separado.

US$5 es únicamente un ejemplo de entrada; **no es una afirmación sobre los
límites actuales de ningún símbolo**. Antes de cualquier evaluación operativa
deben suministrarse mínimos, fees, tick, step y precios observados y trazables
por símbolo. Esta especificación no consulta una exchange.

## Objetivo de MXN 1,000,000

El capital está expresado en USD y el objetivo personal en MXN. No se usa una
paridad USD/MXN inventada. Primero se debe convertir el capital inicial a MXN
con evidencia externa vigente y después construir `GrowthGoal` con monto
inicial y meta en la misma moneda.

El módulo también permite estudiar múltiplos sin mezclar monedas:

- MXN 1,000 a MXN 1,000,000 equivale a 1,000×.
- US$200 a US$1,000,000 equivaldría a 5,000×, pero **esa no es la meta de MXN
  1,000,000**.
- US$200 a MXN 1,000,000 no tiene un múltiplo determinado hasta aportar un tipo
  de cambio verificable.

Para cada objetivo, el resultado muestra:

- retorno compuesto mensual requerido por el plazo;
- meses ilustrativos usando exclusivamente el retorno y aporte suministrados;
- aporte mensual requerido para el plazo bajo esa misma hipótesis;
- una bandera `extreme_1000x_target`;
- una bandera `impossible_1000x_one_month_target` para rechazar explícitamente
  el atajo de 1,000× en un mes.

“Imposible” en esta bandera significa que no es un objetivo de inversión
creíble, repetible ni financiable para el sistema; no que la operación
matemática carezca de resultado. Un escenario es una ilustración, nunca un
pronóstico o promesa.

## Motor 1: ingresos por auditoría

### Entregable inicial

Un flujo único y sin integración de dinero real:

```text
AuditInput -> AuditJob -> AuditVerdict -> reporte HTML/JSON
```

Debe reutilizar controles existentes para detectar:

- look-ahead y selección futura;
- identidad o universo inestable;
- omisión de fees, spread, impacto y rechazos;
- inspección o reutilización indebida del holdout;
- trials ausentes del ledger;
- resultados que no se reproducen desde un checkout limpio.

### Secuencia de validación

1. Empaquetar un reporte determinista con fixture público o sintético.
2. Entrevistar usuarios independientes y registrar su problema, proceso actual
   y criterio de compra.
3. Ejecutar pilotos asistidos, sin asumir precio ni demanda.
4. Medir tiempo ahorrado, defectos descubiertos y repetición de uso.
5. Solo con evidencia de compra, decidir empaque, precio, hosting y soporte.

No se construyen billing, infraestructura comercial ni proyecciones de ventas
antes de validar demanda. El plan no inventa precio, conversión ni ingresos.

## Motor 2: investigación H2

La hipótesis H2 no trata de anticipar pumps. Intenta reducir pérdidas
terminales saliendo cuando una moneda muestra deterioro causal de ranking o
turnover.

Secuencia bloqueante:

1. Reconstruir un panel Binance Spot point-in-time con identidad `CMC:<id>`.
2. Separar `eligible_to_open`, `tradable`, `mark_price` y `market_event`.
3. Sellar cohorte, regla H2, control, costos, benchmarks y refutación antes de
   evaluar resultados.
4. Ejecutar una sola vez en desarrollo.
5. Publicar `NO_GO` si falla; no crear variantes post-hoc.
6. Si pasa, preservar holdout y completar evidencia estadística.
7. Usar Demo y shadow únicamente después de superar los gates económicos.

El capital inicial no cambia los criterios de aprobación. Una estrategia mala
con US$20 sigue siendo mala; una estrategia prometedora sin evidencia sigue
siendo insuficiente.

## Contrato de `wealth_plan.py`

El cálculo también está disponible como CLI. Este ejemplo evalúa US$200 como
todo el capital de riesgo y, por tanto, un canario máximo de US$20:

```powershell
quant-trade wealth assess --total-risk-capital-usd 200 `
  --proposed-canary-usd 20 --eligible-asset-count 20 `
  --goal-starting-amount 200 --goal-target-amount 240 `
  --goal-currency USD --horizon-months 12
```

El comando imprime JSON; un estado `FEASIBLE` es solo factibilidad aritmética,
no una orden, una recomendación o una expectativa de retorno.

`evaluate_wealth_plan()` es una función pura. Distingue:

- `total_risk_capital_usd`;
- `proposed_canary_usd`;
- cantidad de activos elegibles;
- mínimo nocional y colchón suministrados;
- objetivo, moneda, plazo, aporte y retorno meramente ilustrativo.

Devuelve exactamente uno de estos estados:

- `FEASIBLE`: la aritmética suministrada satisface las restricciones;
- `NO_GO`: existe una contradicción o violación comprobable;
- `INSUFFICIENT_EVIDENCE`: falta una entrada requerida.

Todos los objetos internos son inmutables, la solicitud y evaluación tienen
digests canónicos y un resultado manipulado falla al recomputarse. Incluso un
resultado `FEASIBLE` siempre exporta:

```json
{
  "automatic_transition_authorized": false,
  "external_action_authorized": false,
  "real_money_authorized": false,
  "profit_claim_authorized": false
}
```

## Próximo punto de decisión

La ruta hacia patrimonio no es “depositar y esperar 1,000×”. Es aumentar de
forma verificable tres cantidades distintas:

1. ingreso ganado fuera del trading;
2. aportes al capital de riesgo que pueden perderse completamente;
3. evidencia de alpha neto sin elevar la probabilidad de ruina.

El primer desembolso real permanece bloqueado. La siguiente inversión del
proyecto es tiempo en el auditor y en el panel causal H2, no capital en la
venue.
