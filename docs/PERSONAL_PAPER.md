# Bot privado de ETF: desarrollo y observación simulada

Este módulo mantiene nueve carteras hipotéticas independientes: dos candidatas y un control,
cada una con costos 1×, 2× y 3×. Cada cartera representa una alternativa para el mismo capital
de **20,000 MXN**, no nueve cuentas financiadas. No envía órdenes, no usa credenciales de un
broker y nunca emite una aprobación de dinero real. No cambia las rutas del SaaS público.

## Protocolo congelado

Universo fijo: GLD, IWM, QQQ, SPY y TLT. Se reutilizan las señales causales del registro existente.

| Cartera | Ventana y regla | Frecuencia | Límite por ETF |
|---|---|---|---|
| inverse_volatility | Inverso de volatilidad de 63 sesiones | Mensual | 35% |
| vol_targeted_equal_weight | Igual peso, objetivo de volatilidad anual 10%, 63 sesiones, 252/año | Mensual | 25% |
| equal_weight_quarterly | Igual peso, control | Trimestral | 25% |

Objetivo máximo de exposición: 95%; reserva de efectivo: 5%. No hay cortos ni apalancamiento.
Una banda de cinco puntos porcentuales y un mínimo de 0.5% del capital inicial reducen cambios
pequeños. Las ventas para reducir una violación de límite evitan esa banda; las compras esperan
si la liquidez impide terminar la reducción. Los objetivos se calculan con una reserva conservadora
para costos para que cargos posteriores no produzcan una compra por encima del límite. Los
precios pueden desplazar los pesos entre decisiones; el módulo no garantiza pesos constantes.

Costos hipotéticos por lado: comisión 5, deslizamiento 5 y spread 2 puntos básicos; se cargan
como reducción de efectivo. Los escenarios 2× y 3× multiplican todos esos cargos. Las fracciones
tienen paso de 0.000001 participaciones; la liquidez limita una orden al 0.01% del volumen de la
barra admitida. Una orden incompleta expira: no se inventa liquidez ni se acumula una deuda.
En desarrollo, una ejecución al precio de apertura usa el volumen de la sesión anterior cerrada
como aproximación conservada en el manifest; el volumen total del día de ejecución todavía no
era conocido en esa apertura. Esta aproximación no prueba que hubiera liquidez disponible al
abrir. En prospectivo se exige el volumen de la cotización de un minuto observada.

Al alcanzar un drawdown de **5% en MXN**, o una pérdida diaria de 2%, se persiste una pausa
de nuevas compras; se siguen registrando valores y se permiten reducciones. Reiniciar el proceso
no elimina la pausa ni reinicia el máximo histórico. `resume` exige una revisión escrita de al
menos veinte caracteres y rechaza un drawdown aún incumplido. Es un freno operativo observado,
no una garantía de pérdida máxima: un gap, datos retrasados o el movimiento del tipo de cambio
pueden superar ese umbral.

## Dos tipos de evidencia

`development` permite reproducción explícita del historial conocido, usando decisiones al cierre
y ejecuciones hipotéticas en la siguiente sesión. Todo historial obtenido hoy, incluyendo fechas
recientes, se etiqueta desarrollo. El período 2005–2024 ya fue usado por los experimentos del
repositorio; tampoco se presume que 2025 en adelante sea un holdout intacto. El generador
`demo-data` inventa precios y FX para comprobar funcionamiento, siempre etiquetados `SYNTHETIC`.

`prospective` fija la hora de registro con el reloj UTC del sistema. El historial anterior sólo
calienta señales. **El primer cierre nuevo posterior al sello genera una única decisión inicial**;
se puede ejecutar en los primeros 300 segundos de la apertura siguiente si hay precio observado
y calendario confirmado. Después rige la frecuencia congelada. Una ventana perdida expira y
espera la siguiente decisión prevista; no se persigue el precio con una orden tardía. El reloj
inyectado permitido en pruebas deja `TEST_CLOCK_SIMULATION`, que no cuenta como observación real.

Los cierres diarios deben tener `bar_end_utc` y `observed_at_utc`, pertenecer al calendario NYSE y
tener los cinco símbolos completos. El proveedor gratuito puede entregar datos tarde o revisarlos.
Sin un precio observable y acciones corporativas inequívocas en la apertura, el worker informa
`WAITING`. El precio de una barra de un minuto no representa un fill confirmado de un broker.
La hora de recepción se registra después de cada respuesta del proveedor. El cierre de mercado,
la hora del precio y la hora en que el programa crea una decisión son datos diferentes. Una
decisión creada después de la apertura siguiente expira sin borrar las valoraciones observadas.
Se exigen columnas explícitas de dividendos y splits; una columna ausente no significa cero.

La configuración de mercado usa `raw_with_actions`: dividendos y splits explícitos se aplican una
sola vez a las participaciones. Las señales usan un índice de retorno total construido únicamente
con acciones conocidas hasta cada sesión. Se valora con precios raw; no se suma un dividendo a
un precio ya ajustado por retorno total. El dividendo se acredita hipotéticamente en fecha ex,
no en fecha de pago, y no incluye impuestos. Este supuesto limita cualquier conclusión económica.
USD/MXN requiere fuente y fecha; se usa la última observación conocida, con antigüedad máxima
de siete días. No se fabrica tipo de cambio.

## Ejecución local

Instalar el extra opcional `personal-paper` del proyecto en un entorno privado. Todos los ejemplos
guardan datos en `state/`, que está ignorado por Git. Desde la raíz del checkout:

```powershell
$env:PYTHONPATH = "src"
python -m quant_trade.personal_paper demo-data --output state/demo
python -m quant_trade.personal_paper run --config configs/personal/synthetic_demo.yaml --data state/demo/synthetic_ohlcv.csv --fx state/demo/synthetic_fx.csv --database state/demo.sqlite
python -m quant_trade.personal_paper status --database state/demo.sqlite
```

El grupo equivalente `quant-trade personal-paper` contiene los mismos comandos. Para recoger un
snapshot privado de desarrollo y estudiar datos conocidos:

```powershell
python -m quant_trade.personal_paper fetch-data --cache state/market-cache --start 2020-01-02
```

`latest.txt` apunta al directorio del snapshot, con `panel.csv`, `fx.csv`, `calendar.csv` y un manifest
de procedencia. El comando `run` acepta esos archivos y `--calendar`; por defecto es desarrollo.
Usar bases distintas para desarrollo y prospectivo. Nunca cambiar modo/config/código en una base
ya sellada: un cambio requiere un nuevo experimento que preserve el anterior.

El worker ejecuta una iteración autónoma sin preparar CSV a mano:

```powershell
python -m quant_trade.personal_paper worker --config configs/personal/etf_private_v1.yaml --database state/personal/prospective.sqlite --cache state/personal/market-cache --start 2020-01-02
```

Valida hashes del cache, refresca una vez al día y después de un cierre nuevo, registra únicamente
observaciones posteriores al sello y busca precios de apertura cuando corresponde. Guarda
`worker_status.json` privado. Repetirlo mediante un programador local cada minuto permite observar
la apertura; el equipo debe estar encendido y conectado. El wrapper PowerShell incluido ejecuta
una iteración, conserva logs y devuelve un código de error. No registra por sí mismo una tarea ni
contrata infraestructura. Las zonas horarias y días festivos los determina el calendario, no una
hora mexicana fija. Tampoco configurar una tarea de Railway que modifique el servicio público.

El presupuesto configurado es 500 MXN/mes; no se crean servicios de pago. `--expenses archivo.csv`
admite `start,end,category,amount_mxn` con horas UTC. Suma conservadoramente todos los gastos
que tocan el mes; por encima del límite pausa compras y bloquea la siguiente recolección. Sin ese
registro el estado es `UNOBSERVED`, no gasto cero. Mantener costos externos reales por separado.

## Estado, recuperación y evaluación

SQLite usa WAL, fsync FULL y una transacción por iteración. Una escritura simultánea se rechaza;
el worker además usa un bloqueo del sistema operativo liberado tras un crash. Cada orden tiene
ID determinista. El diario forma una cadena de hashes y reconcilia efectivo y cantidades desde
fills y acciones corporativas; los estados, curvas, manifest e inputs consumidos también tienen
anclas. Un crash hace rollback; el siguiente intento vuelve a verificar antes de continuar. Esto
detecta ediciones accidentales, no constituye una firma criptográfica frente al propietario del disco.
Las cotizaciones prospectivas admitidas conservan fuente, horas de precio/recepción, precio,
volumen, acciones corporativas y FX en un evento con hash; cada fill referencia ese evento.
Una cotización incompleta o una fuente ausente se rechaza sin dejar una ejecución parcial.

Se rechazan valores no finitos, símbolos faltantes, calendarios incoherentes, gaps injustificados,
precios/actions/FX previamente consumidos que cambien o sesiones eliminadas. Una revisión de
proveedor no se corrige silenciosamente. Preservar DB, archivos y logs, pausar y registrar una nueva
versión si se cambia la metodología; no borrar evidencia desfavorable.
Una ejecución de mercado prospectiva requiere calendario validado en todas sus iteraciones.
El registro conserva las versiones exactas del runtime, dependencias y criterios económicos;
actualizarlas exige preservar el experimento original y registrar uno nuevo.
El manifest distingue el commit observado de `git_worktree_dirty`; el hash sellado identifica
los bytes ejecutados. Publicar un commit después del registro no reescribe esos metadatos.

```powershell
python -m quant_trade.personal_paper pause --database state/personal/prospective.sqlite --reason "Revisar calidad de datos"
python -m quant_trade.personal_paper resume --database state/personal/prospective.sqlite --review "Revisé datos, posiciones y riesgo; continuar únicamente simulación."
python -m quant_trade.personal_paper export --database state/personal/prospective.sqlite --output state/personal/review
python -m quant_trade.personal_paper backup --database state/personal/prospective.sqlite --output state/personal/backups/prospective-20261005.sqlite
python -m quant_trade.personal_paper economic-review --database state/personal/prospective.sqlite --output state/personal/review --costs state/personal/expenses.csv
```

`backup` usa la API de respaldo de SQLite, incluye páginas pendientes del WAL y verifica integridad
y reconciliación antes de publicar un destino nuevo; nunca reemplaza una base existente. Para
restaurar, detener el worker, preservar la base original y ejecutar `status` sobre la copia. Apuntar
el worker a la copia sólo con los mismos hashes de código/configuración y los inputs preservados.
Un rollback de código incompatible debe conservar el experimento sellado y empezar otro; no se
reescribe la historia para adaptar sus resultados. Conservar copias privadas fuera del checkout.

`paper_90d_3rebals_complete` exige reloj real, calendario confirmado, noventa días transcurridos,
sesenta cierres nuevos y tres ciclos con fills efectivos para cada candidata y escenario. La banda,
una pausa o ventanas de apertura perdidas pueden retrasarlo mucho más de noventa días. No se
fuerzan operaciones para completar ese indicador. No es un dictamen de rentabilidad.

La revisión económica exige 252 intervalos completos entre cierres prospectivos (253 cierres
nuevos) y cobertura completa explícita
de gastos de infraestructura, datos y FX/transferencia, incluyendo ceros declarados. Compara con
el control en MXN en 1×/2×, usa bootstrap pareado de bloques de veinte sesiones, 10,000 muestras,
semilla 20261005, ajuste para dos candidatas y el historial de ensayos del ledger congelado. Si
faltan datos, retornos previos necesarios para DSR o costos, devuelve inconcluso. El manifest
exportado conserva todos los trials, hashes de configuración/código/dataset, fechas del sello y
tipo de evidencia. Ningún resultado activa dinero real: `real_money_approved=false` siempre.

La referencia económica inicial es el capital MXN sellado, no el valor del primer cierre. Se
incluyen los movimientos de FX y costos desde el registro hasta la última valoración, también
cuando ocurren antes del primer cierre. Para inferencia se exigen 252 intervalos completos entre
cierres (253 cierres nuevos); el intervalo inicial parcial se declara y se mantiene fijo en el
bootstrap. No se repite artificialmente un cargo único de apertura en cada bloque.

El ledger histórico conserva 109 resultados. En 48 grupos de ventanas aparece una combinación
aunque se declaran tres comparaciones; faltan los momentos de las otras combinaciones. El
generador actual ya registra todas las combinaciones, pero eso no completa evidencia histórica
ausente. La revisión económica permanece inconclusa mientras esa evidencia no sea auditable;
no inventa Sharpes ni reescribe los resultados para completar el contador.
