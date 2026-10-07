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

El grupo equivalente `quant-trade personal-paper` contiene los mismos comandos. La CLI principal
lo registra de forma diferida: sólo importa este módulo al invocar, listar o completar ese grupo.
`quant-trade audit serve`, que arranca el servicio web público, no carga el simulador; la prueba
`test_personal_paper_isolation.py` lo verifica. Para recoger un
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
`worker_status.json` privado mediante reemplazo atómico, también cuando se detiene por presupuesto.
El archivo contiene `checked_at_utc`; representa la última iteración que publicó estado, no un
heartbeat ni una aprobación económica. Si falla el proveedor, consultar también la fecha,
los logs y el código de salida: el archivo puede conservar el estado anterior. El resumen CLI
conserva el aviso de simulación y las causas de pausa de cada cartera.
Repetirlo mediante un programador local cada minuto permite observar
la apertura; el equipo debe estar encendido y conectado. El wrapper PowerShell incluido ejecuta
una iteración, conserva logs y devuelve el código de salida del worker. Funciona con Windows
PowerShell 5.1 y PowerShell 7: un aviso en stderr se registra en el log sin abortar el wrapper ni
ocultar ese código. No registra por sí mismo una tarea ni
contrata infraestructura. Las zonas horarias y días festivos los determina el calendario, no una
hora mexicana fija. Tampoco configurar una tarea de Railway que modifique el servicio público.

El presupuesto configurado es 500 MXN/mes; no se crean servicios de pago. `--expenses archivo.csv`
admite `start,end,category,amount_mxn` con horas UTC. Suma conservadoramente todos los gastos
que tocan el mes; por encima del límite pausa compras y bloquea la siguiente recolección. Sin ese
registro el estado es `UNOBSERVED`, no gasto cero. Un CSV vacío o sin gastos que intersecten el
mes vigente también es `UNOBSERVED`; un cero explícito del mes sí se conserva como cero declarado.
`WITHIN_DECLARED_BUDGET` exige que las tres categorías `infrastructure`, `data` y `fx_transfer`
cubran sin huecos desde el inicio del mes UTC hasta la hora de la comprobación, con ceros
explícitos cuando no hubo gasto. Si falta una categoría, un día o el tramo más reciente, el estado
es `PARTIALLY_OBSERVED`: lista `uncovered_categories` y su suma es sólo una cota inferior. Una suma
parcial que ya supera el límite sigue siendo `OVER_BUDGET` y pausa. Esto describe las filas
recibidas, no acredita que el registro sea veraz. Mantener costos externos reales por separado.

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

El [resumen de validación conservada](PERSONAL_PAPER_VALIDATION_20261005.md) publica las nueve
alternativas del replay de desarrollo, sus límites y los pasos pendientes para observación nueva.
Cambiar el código del worker requiere registrar una versión nueva; no se reutiliza ni reescribe
la base del replay congelado para adaptar su evidencia al software posterior.

## Diagnósticos de lectura y solicitudes de pausa

`status`, la lectura fuente de `export` y la revisión económica abren SQLite con
URI `mode=ro`, sin inicializar tablas, crear el directorio de la fuente ni cambiar
su modo de diario. Una ruta a otra base, un esquema incompleto o un archivo que
no sea SQLite se rechaza con un error de dominio. La salida CSV/JSON solicitada
por `export` sólo se crea después de verificar un registro válido. El lector
conserva una instantánea transaccional y lee los commits del WAL en la siguiente
transacción; no usa `immutable`, que podría omitir observaciones aún en el WAL.
SQLite puede crear sus auxiliares `-wal`/`-shm` dentro del directorio existente
de una fuente WAL. `mode=ro` protege los datos, esquema y modo del diario de la
fuente; no promete ausencia de archivos auxiliares ni evita sus requisitos de
acceso. La revisión conserva los datos confirmados en WAL.

La solicitud de pausa sólo sella las carteras activas que pasan a pausadas.
Una cartera ya pausada conserva su primera causa hasta una revisión para
reanudar. Un motivo adicional se registra como `manual_pause`; reiterar el mismo
último motivo mientras todas siguen pausadas no duplica estados ni solicitudes,
incluso después de reiniciar o valorar nuevamente. Una reanudación revisada
permite registrar una pausa posterior por la misma razón. La transacción hace
rollback completo si se interrumpe antes de terminar.

`pause` y `resume` sólo actúan sobre una base ya sellada por `run`. Un archivo de
cero bytes, una SQLite vacía o el esquema del bot sin manifest se rechazan con
`UnregisteredPaperDatabase` antes de cualquier escritura: no crean tablas, no
cambian el modo de diario ni registran solicitudes. El rechazo comprueba la base
en modo `mode=ro` y de nuevo bajo el lease del escritor. La CLI informa
`Paper pause refused`/`Paper resume refused` con código 2, y `run` puede inicializar
después el mismo archivo vacío. Si el presupuesto se excede y la ruta del worker
contiene un archivo así, no hay carteras que pausar: el worker publica igualmente
`BUDGET_PAUSED` y no recolecta. Una base ajena sigue deteniendo el worker.

Estos rechazos y el estado `PARTIALLY_OBSERVED` cambian archivos incluidos en el
hash sellado (`config.py`, `store.py`, `engine.py` y `worker.py`); `cli.py` no
forma parte de ese hash. Una base sellada con código anterior conserva `status`,
`export`, `pause` y `resume`, pero `run` y `worker` la rechazan por cambio de
código: la siguiente observación se registra en una base nueva, sin reescribir
la anterior ni el replay conservado de `4c39e97`.

El presupuesto sigue publicando `BUDGET_PAUSED` y su hora de comprobación en cada
iteración bloqueada, sin consultar proveedores. Esto actualiza el diagnóstico
operativo sin inflar el diario de posiciones. Los límites, estrategias, costos y
criterios económicos permanecen congelados; las correcciones de código exigen
una base nueva para un experimento posterior. Pruebas offline:
`test_personal_paper_read_only.py`, `test_personal_paper_pause_idempotency.py`,
`test_personal_paper_controls.py` y `test_personal_paper_limits.py`; esta última
fija los techos de capital, presupuesto, drawdown, pérdida diaria y costos, y el
rechazo de cualquier fill que produzca efectivo negativo o una posición corta.

## Protección del destino de escritura

El escritor inspecciona una ruta existente con `mode=ro` antes de abrirla para
escritura, conservando también datos ajenos confirmados en WAL. Admite destinos
nuevos, archivos de cero bytes, SQLite vacía y el esquema completo del bot. Exige
las cinco tablas originales, sus columnas y tipos, claves primarias, `NOT NULL` y
el hash único del diario; conserva autoíndices, estadísticas de SQLite e índices
sobre tablas propias. Rechaza bases ajenas, parciales, vistas y triggers adicionales
antes de cambiar su esquema o modo de diario.

Al adquirir `BEGIN IMMEDIATE`, vuelve a validar la conexión definitiva y crea
las tablas nuevas dentro de una sola transacción. Una interrupción hace rollback
de toda la inicialización; el siguiente intento puede usar la misma base vacía.
Después del commit activa WAL y sincronización FULL. Esta protección cubre errores
de ruta e inicializadores concurrentes del bot; el propietario del disco puede
reemplazar archivos fuera de sus bloqueos. Los respaldos conservan el esquema y
se verifican igual que antes. La suite offline `test_personal_paper_writer_guard.py`
prueba las rutas reales de `run` y `pause` con fuentes sintéticas, incluido WAL vivo
y conservado después de un crash. Cada experimento nuevo sigue sellando el código;
el replay histórico permanece asociado a su versión original.
