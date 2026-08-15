# Medición offline de lotes y costos en MXN

`quant_trade.ops.tax_lot_ledger` responde una pregunta acotada: dado un
capital inicial ya expresado en MXN y una secuencia de fills normalizados,
¿cuánto P&L histórico queda después de comisiones, slippage observado y un
escenario tributario proporcionado expresamente por el operador?

No busca estrategias ni pronostica retornos. Tampoco consulta una venue,
credenciales, precios, divisas o reglas fiscales; no construye órdenes y todos
sus artefactos fijan `real_money_authorized=false`. Su resultado no demuestra
que el dinero pueda volver a ganarse.

## Evidencia requerida

Cada `TaxLotFill` registra:

- identidad, instrumento, hora UTC, lado y cantidad neta que cambia inventario;
- precio y moneda cotizada;
- conversión evento-a-evento a MXN y la etiqueta de su fuente;
- comisión, moneda de la comisión y, si difiere de la moneda cotizada, su
  conversión específica a MXN;
- evidencia de referencia opcional pero atómica: precio, hora UTC y fuente.

Los tres campos de referencia deben aparecer juntos. `reference_at_utc` debe
ser anterior o igual al fill; así un precio observado después de ejecutar no
puede presentarse como benchmark causal. Si falta la tripleta, el estado nunca
es `COMPLETE`: con marks suficientes será `INCOMPLETE_TCA` y los campos de
implementation shortfall, slippage adverso y costo transaccional serán `null`.

La cantidad debe ser la cantidad **neta de cualquier comisión descontada en el
activo base**. `fee_amount` se interpreta como un gasto de caja separado; un
normalizador no debe descontar la misma comisión dos veces.

Cada request declara un único `valuation_as_of_utc`, posterior o igual al
último fill. Todos los `MarkEvidence` deben tener exactamente ese mismo texto
de timestamp; no se permite sumar valuaciones tomadas en instantes distintos.
Cada posición abierta necesita su mark en ese corte. Si falta, el estado es
`INCOMPLETE_MARKS` y no se inventan P&L no realizado, equity ni retorno.

La trayectoria de caja también debe caber dentro de `initial_capital_mxn`. Si
en cualquier instante requiere más efectivo, el estado es
`INSUFFICIENT_FUNDING`. El P&L histórico de los fills puede conservarse como
medición, pero ambos retornos sobre capital quedan en `null`: dividir por el
capital insuficiente inventaría financiamiento o apalancamiento no declarado.
El faltante exacto permanece visible en `capital_shortfall_mxn`. Este estado
tiene prioridad si también faltan marks; los marks faltantes siguen listados.

El componente solo admite posiciones long y el método `FIFO` configurado de
forma explícita. Una venta mayor al inventario, identificadores duplicados,
eventos fuera de orden, NaN/Infinity, una conversión MXN distinta de uno o una
comisión en tercera moneda sin FX producen un error cerrado.

## Qué calcula

- notional bruto comprado y vendido en MXN;
- implementation shortfall firmado, comisiones y slippage adverso en MXN;
- capital mínimo que la trayectoria de caja habría requerido y cualquier
  faltante frente al capital inicial declarado;
- realizaciones FIFO, P&L bruto y P&L realizado antes de impuestos;
- lotes abiertos, valor marcado y P&L no realizado antes de impuestos;
- retornos sobre el capital inicial cuando toda la evidencia necesaria existe.

Los costos de adquisición se incorporan proporcionalmente al costo de cada
lote; las comisiones de salida se asignan proporcionalmente a las cantidades
FIFO realizadas. Los importes usan `Decimal` y los request/resultados se ligan
con SHA-256 de JSON canónico.

`signed_implementation_shortfall_mxn` conserva el signo: positivo significa
ejecución adversa y negativo, mejora frente a la referencia. Para no convertir
una mejora en un “costo negativo”, `adverse_slippage_mxn` es
`max(signed_implementation_shortfall_mxn, 0)` y `transaction_cost_mxn` es la
suma no negativa de ese valor y las comisiones. Si falta cualquier referencia,
los tres campos quedan desconocidos.

## Escenario tributario, no cálculo fiscal

No hay una tasa por defecto. Sin `TaxScenario`, todos los campos tributarios y
after-tax son `null`. El único modo admitido es
`POSITIVE_NET_REALIZED_PNL_MXN`: aplica la tasa explícita a
`max(P&L realizado pre-tax, 0)`. El escenario exige:

- tasa entre cero y uno;
- `declared_by_user=true`;
- etiqueta y fuente de la hipótesis.

Eso es una sensibilidad matemática, no una determinación de base gravable,
obligación, deducción, acreditamiento, temporalidad o tratamiento legal en
México. Un contador o asesor fiscal competente debe determinar esos conceptos
con estados de cuenta y regulación aplicable.

## Ejemplo mínimo

```python
from decimal import Decimal

from quant_trade.ops.tax_lot_ledger import (
    AfterTaxTcaRequest,
    MarkEvidence,
    TaxLotFill,
    TaxLotLedgerConfig,
    evaluate_after_tax_tca,
)

fill = TaxLotFill(
    fill_id="paper-1",
    instrument_id="CMC:1",
    executed_at_utc="2026-08-13T12:00:00Z",
    side="BUY",
    quantity=Decimal("0.001"),
    unit_price_quote=Decimal("60000"),
    quote_currency="USDT",
    mxn_per_quote=Decimal("19.20"),
    quote_fx_source="operator-supplied event-time observation",
    fee_amount=Decimal("0.06"),
    fee_currency="USDT",
    reference_price_quote=Decimal("59990"),
    reference_at_utc="2026-08-13T11:59:59Z",
    reference_source="operator-supplied pre-fill decision-price observation",
)
mark = MarkEvidence(
    instrument_id="CMC:1",
    as_of_utc="2026-08-14T12:00:00Z",
    unit_price_quote=Decimal("61000"),
    quote_currency="USDT",
    mxn_per_quote=Decimal("19.25"),
    quote_fx_source="operator-supplied mark-time observation",
)
measurement = evaluate_after_tax_tca(
    AfterTaxTcaRequest(
        initial_capital_mxn=Decimal("4000"),
        config=TaxLotLedgerConfig(lot_method="FIFO"),
        fills=(fill,),
        marks=(mark,),
        valuation_as_of_utc="2026-08-14T12:00:00Z",
    )
)
```

Para partir de US$200, el operador debe aportar primero una conversión
verificable y declarar su equivalente como `initial_capital_mxn`; el módulo no
presupone una paridad USD/MXN.
