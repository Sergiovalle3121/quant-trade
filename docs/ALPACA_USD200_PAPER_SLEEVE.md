# Sleeve Alpaca Paper de USD 200

## Estado y alcance

Este componente aísla una campaña **virtual** de exactamente USD 200. No abre
conexiones, no lee credenciales, no importa el adaptador de Alpaca y no puede
enviar órdenes. Su única salida operativa es una decisión local que indica si
un plan ya sellado puede entregarse **una sola vez** a una integración Paper
separada.

No habilita dinero real ni demuestra rentabilidad. En particular, no convierte
USD 200 en USD 1,000,000 y no justifica depositar capital. Sirve para que una
prueba Paper no utilice accidentalmente todo el buying power ficticio de la
cuenta Alpaca.

Implementación: `src/quant_trade/execution/alpaca_campaign_sleeve.py`.

## Contrato congelado

`SleevePolicy` fija:

- `initial_cash = 200 USD`;
- reserva mínima de fees de USD 5;
- exposición bruta y por símbolo máxima de USD 195;
- máximo de dos órdenes por día;
- quotes y snapshot con antigüedad máxima de 60 segundos;
- plan con vigencia máxima de cinco minutos;
- `paper_only = true` y `real_money_enabled = false`;
- leverage y shorts deshabilitados.

La política, el snapshot de cash/posiciones/órdenes abiertas, la evidencia de
activos y el plan producen digests SHA-256 sobre JSON canónico. El plan liga los
cuatro. Cualquier cambio posterior rompe el binding y el preflight se niega.
`SealedPaperPlan`, `SleevePreflight` y `CampaignOutcomeReceipt` solo pueden ser
creados por sus fábricas internas y son dataclasses congeladas.

Un hash detecta corrupción o cambios accidentales; no sustituye una firma ni
protege contra un atacante que ya controle el proceso y el disco.

## Preflight de cartera

`preflight_paper_plan` vuelve a validar el plan y calcula:

- cash conservador después de todas las compras abiertas y planeadas, sin usar
  ventas inciertas para financiar compras;
- exposición actual más el riesgo de todas las compras, suponiendo que las
  ventas pueden no ejecutarse;
- exposición de cada símbolo;
- posiciones y cash si todas las órdenes terminan ejecutándose;
- recuento diario después del plan.

Las órdenes abiertas existentes se incluyen en esa proyección, pero
`consume_once` no autoriza un plan nuevo hasta que hayan sido conciliadas y el
snapshot tenga `open_orders=()`. No se intenta inferir su estado.

Para compras, el riesgo usa `cantidad × max(limit_price, quote_price)`. Así, una
orden límite artificialmente barata no puede ocultar una posición enorme. La
obligación de cash usa el límite, que es el máximo precio de ejecución permitido.

El preflight falla cerrado cuando:

- un quote o snapshot está vencido o fechado en el futuro;
- falta evidencia exacta `tradable`/`fractionable` para algún símbolo;
- una venta, acumulada con órdenes abiertas, excede la posición;
- una compra invade la reserva de fees o supera exposición bruta/por símbolo;
- se intenta una orden market, short, leverage, live o distinta de `limit/day`;
- se reutiliza un `client_order_id`, se excede el contador diario o el plan
  expiró.

También se sellan restricciones operativas actuales de Alpaca: cantidad con un
máximo de nueve decimales, compra mínima de USD 1 y límite con hasta dos
decimales cuando el precio es al menos USD 1 (cuatro cuando es menor).

## Consumo idempotente y reinicios

`PaperPlanConsumptionLedger.consume_once` reclama primero el estado
`(campaign_id, trading_date ET, orders_submitted_today)` y crea un marcador
inmutable con `O_EXCL` **antes** de autorizar al llamador a remitir la orden
Paper. Un mutex por campaña serializa consume/finalize. Dos procesos, dos planes
distintos desde el mismo snapshot ni un contador diario rebobinado pueden ganar
el mismo capital. Tras un timeout o reinicio, encontrar el marcador produce
`should_submit = false`; nunca se adivina que el primer intento falló.

Después de un `COMMITTED`, el head deriva de los fills el cash máximo restante
(sin sumar fees) y las cantidades canónicas. El siguiente snapshot debe tener
exactamente esas posiciones, cash no mayor al máximo y cero órdenes abiertas.
Resetear el snapshot a USD 200 después de comprar produce
`REFUSED_STATE_DISCONTINUITY`, no una segunda autorización.

El ledger contiene:

1. `<plan_sha256>.consumption.json`, marcador de consumo pendiente;
2. `<plan_sha256>.outcome.json`, resultado terminal opcional e inmutable.
3. `<state_claim_sha256>.state-claim.json`, claim inmutable del estado previo;
4. un head por campaña, actualizado atómicamente y ligado por hash al head
   anterior; no permite otro plan mientras uno está pendiente y conserva el
   contador esperado;
5. un mutex efímero por campaña. Si un proceso muere sosteniéndolo, queda como
   bloqueo conservador que requiere revisión manual, nunca como autorización.

Los archivos tienen hashes internos y se vuelven a verificar en cada lectura.
Un marcador corrupto bloquea el plan en vez de desbloquear un reenvío.

## Fills parciales y rechazos

`PaperPlanConsumptionLedger.finalize` exige exactamente un outcome por orden
sellada. Solo devuelve `COMMITTED` cuando todas tienen `status=filled` y la
cantidad ejecutada coincide exactamente.

Un fill parcial, rechazo, cancelación, expiración, overfill, precio que viola el
límite o estado desconocido genera un único resultado `FAILED_CLOSED`, con:

- `campaign_halted = true`;
- `requires_manual_reconciliation = true`;
- cantidades realmente ejecutadas conservadas en el recibo;
- prohibición permanente de reenviar ese mismo plan.
- halt persistente de toda la campaña; este módulo no incluye un bypass ni una
  función automática para limpiarlo.

La atomicidad es de la **decisión de campaña**, no una promesa falsa de que el
broker puede revertir fills parciales. Después de un fallo se concilia la cuenta
manualmente fuera de este módulo. Un snapshot o plan nuevo de la misma campaña
seguirá rechazado; reanudar requeriría un procedimiento de revisión/reset manual
separado que este cambio deliberadamente no implementa.

## Flujo de integración futuro

1. Construir `SleeveSnapshot` desde un ledger virtual de la campaña, no desde el
   buying power completo de Alpaca; después del primer fill debe reconciliar con
   el estado canónico persistido por el sleeve.
2. Capturar `AlpacaAssetEvidence` punto-en-tiempo.
3. Crear `PaperPlannedOrder` con límite y `client_order_id` nuevo.
4. Ejecutar `seal_paper_plan` y persistir `plan_json(plan)`.
5. Ejecutar `consume_once`. Solo `should_submit=true` autoriza al código externo
   a llamar Alpaca Paper.
6. Consultar/reconciliar cada orden por `client_order_id` y llamar `finalize` una
   vez con los outcomes observados.

La integración con el adaptador existente queda deliberadamente fuera de este
cambio. Antes de agregarla se necesita una revisión separada de mapeo de
cantidades fraccionarias, estados Alpaca, cancelación y conciliación tras timeout.

## Pruebas

`tests/test_alpaca_campaign_sleeve.py` cubre proyección de cash/posiciones/open
orders, reserva, límites de exposición, quotes vencidos, elegibilidad, shorts,
contador diario, flags live, construcción directa, mutación, tampering,
expiración, duplicados/restart y outcomes completos, parciales y rechazados.
