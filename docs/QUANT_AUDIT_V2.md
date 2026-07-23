# Auditoría cuantitativa V2

Fecha: 2026-07-22  
Alcance: arquitectura, causalidad, datos, backtesting multi-activo, validación estadística, selección, paper trading y preparación operativa.

## Resumen ejecutivo

El repositorio ya contiene una base amplia de investigación cuantitativa: datos canónicos UTC, backtests single y multi-activo, costos, walk-forward, robustez estadística, trial ledger, selección, stress testing, paper trading, adaptadores de broker y controles operativos. No obstante, sigue siendo una plataforma de investigación/paper trading y **no está autorizada ni lista para enviar órdenes con dinero real**.

La corrección prioritaria de esta iteración endurece el contrato de `target_weights` del motor multi-activo. Antes de simular, el motor ahora rechaza columnas ausentes, timestamps o pesos inválidos, símbolos vacíos o desconocidos y pares timestamp/símbolo duplicados. Esto evita que entradas ambiguas se sobrescriban silenciosamente o produzcan asignaciones imposibles.

No se declara rentabilidad ni se emite un GO de estrategia: no se ejecutó una campaña comparable fuera de muestra que satisfaga todos los gates de promoción. Estado de inversión: **NO-GO** hasta completar validación reproducible con datos point-in-time y evidencia OOS suficiente.

## Mapa real de arquitectura

- `src/quant_trade/data` y `datalake`: carga, normalización UTC, paneles multi-activo, calidad, snapshots, manifests y binding de datasets.
- `strategies` y `research/signals`: reglas de señal y candidatos de investigación.
- `research`: experimentos, grid search, walk-forward, robustez, estadísticas y selección.
- `allocation`: construcción de portafolio, correlación, límites y gobernanza de asignación.
- `backtest`: motores single/multi-activo, portafolio y costos.
- `metrics` y `reporting`: métricas, curvas, trades y artefactos de reporte.
- `trials` y `evidence`: ledger persistente, scorecards, gates y trazabilidad de evidencia.
- `stress`: escenarios, shocks y simulación de estrés.
- `execution`: mapeo de órdenes, seguridad y reconciliación.
- `paper`: simulador, loop, eventos, riesgo, rebalanceo y reportes.
- `live`, `ops` y `cloud`: adaptadores/stubs, kill switches, locks, heartbeat, monitoring y controles de despliegue.
- `configs`: configuraciones reproducibles de estrategias y workflows.
- `tests`: causalidad, golden regression, brokers mockeados, kill switch, endpoints, datos, research, selección y operaciones.

## Flujo completo

1. **Datos:** proveedor/adaptador -> esquema OHLCV canónico -> UTC -> controles de calidad -> caché/snapshot + hash/manifiesto.
2. **Features:** transformaciones causales por símbolo usando únicamente información disponible hasta el timestamp de decisión.
3. **Señales:** estrategia produce score, señal o peso deseado; los parámetros se fijan dentro del train de cada fold.
4. **Posiciones objetivo:** allocation aplica límites por activo, exposición, leverage, shorting, correlación y reglas de gobernanza.
5. **Órdenes:** la diferencia entre posición actual y objetivo se convierte en intención de rebalanceo.
6. **Fills:** una decisión en barra `t` se ejecuta como pronto en la apertura de `t+1`; no se usa el cierre futuro para dimensionar el fill.
7. **Costos:** comisión, slippage y spread se cargan por notional; funding se devenga cuando está disponible.
8. **Contabilidad:** cash, cantidades, market value, equity, exposición y turnover se actualizan en un único flujo.
9. **Métricas:** retorno, CAGR, volatilidad, Sharpe, Sortino, drawdown, Calmar, turnover y métricas mensuales.
10. **Selección:** walk-forward/OOS, robustez, múltiples pruebas, trial ledger y gates de promoción.
11. **Paper trading:** eventos de mercado -> señal causal -> controles de riesgo -> orden simulada o adaptador paper -> fill -> reconciliación -> reporte/heartbeat.

## Riesgos y defectos

### Críticos

- Dinero real: no existe evidencia suficiente para autorizar live trading. Deben mantenerse bloqueados los endpoints live y requerirse habilitación humana explícita.
- Datos point-in-time: datos actuales o universos reconstruidos pueden introducir survivorship/selection bias si no se versionan membresías, delistings y acciones corporativas.
- Promoción: ninguna estrategia debe promoverse solo por rendimiento histórico; se requiere evidencia OOS, costos estresados y gates estadísticos inmutables.

### Altos

- El contrato de pesos multi-activo admitía filas duplicadas, símbolos desconocidos y pesos no numéricos; corregido en esta iteración con validación fail-closed.
- Los costos siguen siendo aproximaciones; faltan modelos calibrados por venue, participación, liquidez, latencia e impacto.
- Paper broker y backtest pueden divergir en calendario, estado parcial, rechazo, cancelación y reconciliación.
- Una búsqueda extensa puede inflar el mejor Sharpe; el trial ledger no debe borrarse y el número efectivo de pruebas debe alimentar DSR/controles equivalentes.

### Medios

- Timezones/calendarios: UTC evita ambigüedad básica, pero sesiones, DST, holidays y barras incompletas requieren calendarios por venue.
- Fills imposibles: el fallback open/close y las acciones fraccionarias pueden ser optimistas para instrumentos concretos.
- Funding, borrow, dividends, splits y delistings necesitan cobertura consistente por clase de activo.
- Métricas anualizadas pueden ser engañosas con muestras cortas, autocorrelación o frecuencias irregulares.

### Bajos

- Los reportes deben mostrar siempre versión de código, config y dataset binding.
- Warnings de dependencias deben reducirse para detectar regresiones reales con mayor señal.
- La documentación debe distinguir claramente diagnóstico de investigación de una recomendación de inversión.

## Fuentes potenciales de sesgo o error

- **Look-ahead:** señal calculada con cierre de `t` y fill en ese mismo cierre; normalizadores fit sobre todo el dataset; ranking con datos posteriores.
- **Leakage:** features/labels solapados entre train y test; imputación global; selección previa al split.
- **Survivorship:** universo formado solo por activos hoy vigentes.
- **Selection bias:** escoger fechas, símbolos o benchmarks después de observar resultados.
- **Data snooping:** repetir grids y reportar solo el ganador sin registrar trials.
- **Timezone:** mezclar timestamps naive, UTC y hora local o asignar una sesión al día incorrecto.
- **Doble contabilización:** descontar costos en fill y nuevamente en P&L; aplicar funding/dividendos dos veces.
- **Fills imposibles:** volumen ilimitado, precio no observable, acciones fraccionarias no soportadas o ejecución durante gaps.
- **Costos subestimados:** ignorar spread, impacto, borrow, funding, market data, rechazo y latencia.
- **Métricas engañosas:** Sharpe in-sample, CAGR en muestras cortas, drawdown sobre serie truncada o múltiples pruebas sin corrección.
- **Sobreajuste:** demasiados parámetros, ventanas elegidas ex post y fragilidad ante pequeñas perturbaciones.

## Capacidades que deben reutilizarse

Mantener y ampliar las pruebas de no-look-ahead y golden regression, el esquema canónico UTC, dataset bindings, costos conservadores por defecto, walk-forward, trial ledger, gates de promoción, stress testing, kill switch, locks, heartbeat, reconciliación, bloqueo de live endpoints y adaptadores externos mockeables. No deben eliminarse ni relajarse para mejorar métricas.

## Backtest vs simulated paper vs broker paper

- **Backtest:** replay determinista de historia, máxima reproducibilidad, fills modelados y sin estado externo.
- **Simulated paper:** loop autónomo con eventos y reloj de ejecución, pero fills todavía producidos internamente.
- **Broker paper:** órdenes reales al entorno paper del broker; incorpora rechazos, estados asíncronos, identificadores y reconciliación, sin capital real.

Resultados iguales no son esperables sin un contrato compartido de reloj, precios, redondeo, costos y estado. Las divergencias deben medirse y explicarse antes de cualquier promoción.

## Bloqueos para operación segura

1. Mantener live deshabilitado y sin credenciales durante esta fase.
2. Completar datos point-in-time y acciones corporativas por universo.
3. Calibrar ejecución/costos y añadir volumen, participación, fills parciales y rechazo.
4. Ejecutar walk-forward comparable con folds congelados y datasets hasheados.
5. Aplicar Monte Carlo/bootstrapping, DSR o corrección equivalente y múltiples pruebas usando el ledger completo.
6. Exigir estabilidad por régimen, sensibilidad paramétrica y costos estresados.
7. Ejecutar paper prolongado con reconciliación, alertas, kill switch y recovery probado.
8. Requerir revisión humana y límites operativos externos antes de habilitar cualquier endpoint live.

## Cambio implementado

`run_multi_asset_backtest` valida el esquema de pesos antes de construir órdenes. Se añadieron regresiones para duplicados, símbolos desconocidos y pesos no numéricos. Los errores ahora detienen la simulación en lugar de aceptar o sobrescribir silenciosamente datos ambiguos.

## Baseline reproducible

Comandos requeridos:

```bash
python -m pip install -e ".[dev]"
ruff check .
mypy src
python -m compileall -q src tests
pytest -q
```

Resultado registrado en la ejecución de trabajo precedente: instalación editable bloqueada por HTTP 403 del índice de paquetes; `ruff`, `mypy` y `compileall` pasaron; `pytest -q` reportó **223 passed, 54 warnings**. La publicación mediante API no dispone de un runner local equivalente, por lo que CI debe repetir estos checks sobre la rama remota.
