"""Words of the continuous track record's pages, in Spanish, English and
Portuguese, with identical keys (``tests/test_track_seal_copy.py``).

Every sentence passes the profit-claim guard in the three languages. On
screen the feature is "Historial continuo" / "Continuous track record" /
"Histórico contínuo"; the word "sello" names only the ``/v`` badge. Nothing
here calls a file or a record authentic, genuine, verified or unalterable,
promises anything "para siempre", or tells the reader to buy, sell, copy,
invest, pause or stop anything. Figures are formatted in, never written in.
"""

from __future__ import annotations

from quant_trade.audit.seo import BRAND

LANGUAGES: tuple[str, ...] = ("es", "en", "pt")

#: Paths per language: the account list, the public prefix, the two examples.
PATHS: dict[str, dict[str, str]] = {
    "es": {
        "records": "/cuenta/historiales",
        "public": "/historial",
        "example": "/historial/ejemplo",
        "coherence": "/coherencia/ejemplo",
    },
    "en": {
        "records": "/account/records",
        "public": "/record",
        "example": "/record/sample",
        "coherence": "/consistency/sample",
    },
    "pt": {
        "records": "/pt/conta/historicos",
        "public": "/pt/historico",
        "example": "/pt/historico/exemplo",
        "coherence": "/pt/coerencia/exemplo",
    },
}

COPY: dict[str, dict[str, str]] = {
    "es": {
        "eyebrow": "Tu cuenta",
        "title": "Historial continuo",
        "lead": (
            "Cada estado de cuenta nuevo que registres se compara con el anterior y queda "
            "encadenado por hash, con la fecha del reloj de " + BRAND + ", no la del archivo."
        ),
        "back_account": "Volver a mis informes",
        "back_records": "Volver a mis historiales",
        "quota": "Historiales abiertos: {opened} de {allowed}. Borrar uno no libera su lugar.",
        "none": "Aún no abriste ningún historial.",
        "open_title": "Abrir un historial",
        "open_lead": (
            "Elige un informe pagado tuyo sobre un estado de cuenta (MT4, MT5, Myfxbook, "
            "MQL5, FX Blue) o una tabla mensual. Abrirlo es gratis; la fecha de apertura la "
            "pone el reloj de " + BRAND + "."
        ),
        "open_none": (
            "Ningún informe de tu cuenta sirve para abrir un historial: hace falta un informe "
            "pagado, subido con la sesión iniciada, sobre un estado de cuenta o una tabla "
            "mensual (nunca del probador)."
        ),
        "report_option": "Informe {id} · clase {cls} · {date}",
        "report_label": "Informe",
        "open_button": "Abrir historial",
        "paying_note": (
            "Cada estado nuevo es un informe pagado por el flujo normal; pagar no cambia la "
            "clase ni ningún evento."
        ),
        "status_open": "abierto",
        "status_ended": "terminado",
        "status_withdrawn": "retirado",
        "opened_on": "Abierto el",
        "uploads": "Cargas",
        "last_upload": "Última carga",
        "fresh_current": "Al día",
        "fresh_stale": "sin cargas desde {date}",
        "class_stretch": "Clase del tramo posterior a la apertura",
        "class_pending": "aún sin clase: {n} de {m} observaciones",
        "class_full": "Clase del historial completo",
        "class_full_note": "incluye lo anterior a la apertura, que no está cubierto",
        "time_to_know": "Tiempo para saber",
        "ttk_months": (
            "faltan unos {months} meses al ritmo actual ({pace} observaciones por mes) para "
            "llegar al mínimo de la sección de significancia; es una estimación que cambia "
            "con cada carga, no un pronóstico"
        ),
        "ttk_reached": (
            "ya se llegó al mínimo de la sección de significancia; sigue siendo una "
            "estimación que cambia con cada carga, no un pronóstico"
        ),
        "ttk_no_mean": "no hay promedio positivo que medir",
        "ttk_too_few": "aún no se puede estimar: faltan observaciones",
        "observations": "Observaciones del tramo",
        "head": "Cabeza de la cadena",
        "method": "Versión del método",
        "chain_ok": "La cadena se recalcula bien.",
        "chain_broken": (
            BRAND
            + " no pudo recalcular la cadena de este historial: es un error de "
            + BRAND
            + ", no de quien subió los archivos. La clase se oculta hasta que se revise."
        ),
        "events_title": "Eventos",
        "event_opened": "apertura",
        "event_uploaded": "carga que coincide con la anterior",
        "event_mismatch": "carga que no coincide con la anterior",
        "event_ended": "terminado por quien lo abrió",
        "event_published": "publicado",
        "event_unpublished": "despublicado",
        "event_hidden": "página pública ocultada por " + BRAND,
        "event_shown": "página pública vuelta a mostrar",
        "mismatch_line": (
            "Esta carga no coincide con la anterior en {n} operaciones; puede ser un ajuste "
            "del bróker o una edición."
        ),
        "op_deleted": "{n} que faltan",
        "op_inserted": "{n} nuevas antes del corte anterior",
        "op_changed": "{n} cambiadas",
        "op_open_changed": "{n} abiertas que no cuadran",
        "k_t": "operaciones cerradas",
        "k_f": "movimientos de caja",
        "k_o": "posiciones abiertas",
        "k_m": "meses",
        "fields": "campos",
        "count_label": "operaciones",
        "uploads_title": "Cargas registradas",
        "upload_cols": "N.º|Fecha|Corte|Operaciones cerradas|Movimientos de caja|Hash",
        "view": "Ver detalle",
        "add_title": "Registrar un estado nuevo",
        "add_lead": (
            "Elige otro informe pagado tuyo con el estado más reciente de la misma cuenta: la "
            "exportación completa, desde el principio."
        ),
        "add_none": "No hay otro informe pagado tuyo que registrar.",
        "add_button": "Registrar carga",
        "end_button": "Terminar",
        "end_help": (
            "Un historial terminado queda congelado con su fecha; se puede publicar, no continuar."
        ),
        "delete_button": "Borrar",
        "delete_confirm_title": "¿Borrar este historial?",
        "delete_confirm_lead": (
            "Se borran sus cargas y eventos. Si alguna vez estuvo publicado, su enlace dirá "
            "solo que fue retirado por quien lo abrió y la fecha. Su lugar en el cupo no se "
            "libera."
        ),
        "delete_confirm_button": "Sí, borrar",
        "cancel": "Cancelar",
        "publish_title": "Publicar",
        "publish_lead": (
            "La página pública muestra fechas, cantidades, la clase del tramo posterior a la "
            "apertura, los eventos (fecha, tipo y cuántas operaciones) y la cabeza de la "
            "cadena; nunca operaciones, archivos, cuenta, bróker ni tu correo."
        ),
        "holder_checkbox": (
            "Soy titular de esta cuenta de trading o tengo su permiso para publicar este historial"
        ),
        "publish_button": "Publicar",
        "unpublish_button": "Despublicar",
        "published_since": "Público desde",
        "public_link": "Página pública",
        "public_off": "La página pública está apagada en este servicio por ahora.",
        "hidden_note": (
            BRAND + " ocultó la página pública mientras revisa una reclamación; el historial "
            "sigue igual."
        ),
        "badge_title": "Código de la insignia",
        "badge_lead": (
            "Enlaza a la página pública; muestra la clase del tramo posterior a la apertura "
            "(o «en curso»), el id, la última carga y el aviso fijo."
        ),
        "badge_html": "HTML",
        "badge_bbcode": "BBCode",
        "badge_markdown": "Markdown",
        "done_opened": "Historial abierto con la fecha de hoy.",
        "done_uploaded": "Carga registrada: coincide con la anterior.",
        "done_ended": "Historial terminado.",
        "done_deleted": "Historial borrado.",
        "done_published": "Historial publicado.",
        "done_unpublished": "Historial despublicado.",
        "refusal_not_found": "Ese informe no está en tu cuenta.",
        "refusal_not_own": (
            "Ese informe se guardó o se pagó desde el enlace de otra persona; solo sirve un "
            "informe que subiste con la sesión iniciada."
        ),
        "refusal_unpaid": "Ese informe no está pagado.",
        "refusal_purged": "Los archivos de ese informe ya se borraron por retención.",
        "refusal_unsupported_file": (
            "Ese informe no tiene un estado de cuenta de un formato admitido ni una tabla "
            "mensual; un informe del probador no sirve."
        ),
        "refusal_empty_statement": "Ese estado no tiene operaciones cerradas ni movimientos.",
        "refusal_stored_file_mismatch": (
            "El archivo guardado no coincide con su hash: es un fallo de almacenamiento de "
            + BRAND
            + ", no tuyo."
        ),
        "refusal_quota": "Ya abriste los {allowed} historiales que admite una cuenta.",
        "refusal_record_not_open": "Ese historial no está abierto.",
        "refusal_record_not_found": "Ese historial no existe en tu cuenta.",
        "refusal_already_linked": "Ese informe ya es una carga de este historial.",
        "refusal_already_public": "Otro historial público ya tiene estas mismas operaciones.",
        "refusal_holder_not_confirmed": (
            "Para publicar hace falta marcar la casilla de titular o permiso."
        ),
        "refusal_account_differs": "no coincide con la cuenta del historial",
        "refusal_format_changed": (
            "Ese estado viene de otro formato de exportación; hace falta el mismo formato "
            "que la primera carga."
        ),
        "refusal_currency_changed": "Ese estado está en otra moneda que el historial.",
        "refusal_partial_statement": (
            "Ese estado empieza después que el anterior: hace falta la exportación completa "
            "del historial, desde el principio."
        ),
        "refusal_already_recorded": "este archivo ya está registrado",
        "refusal_cutoff_not_advanced": (
            "Ese estado no tiene ninguna operación posterior al corte anterior."
        ),
        "refusal_future_rows": "Ese estado tiene filas con fecha futura.",
        "refusal_earlier_rows": (
            "Ese estado empieza antes que la primera carga y solo añade filas anteriores. El "
            "historial arranca en su primera carga: una exportación más amplia hacia atrás "
            "no se registra, y no es una ruptura."
        ),
        "public_eyebrow": "Historial continuo",
        "public_title": "Historial continuo",
        "public_notice_label": "Aviso",
        "public_notice": (
            "Esta página resume un historial continuo: estados de cuenta que quien lo abrió "
            "registró en " + BRAND + ", comparados uno con otro y encadenados por hash, con "
            "fechas del reloj de " + BRAND + ". Los datos los aportó quien los subió y no "
            "están verificados con el bróker. La clase describe la evidencia estadística del "
            "tramo posterior a la apertura; no garantiza resultados, no es asesoría de "
            "inversión y no avala a ningún vendedor ni producto."
        ),
        "public_since": "público desde el {date} ({days} días después de abrirse)",
        "unpublished_period": "sin publicar del {start} al {end}",
        "ended_frozen": "Terminado el {date}: congelado desde entonces.",
        "account_records": (
            "Historiales abiertos por esta cuenta: {n}. " + BRAND + " no ve otras cuentas de "
            "la misma persona."
        ),
        "paid_note": "pagado por quien sube el archivo; pagar no cambia la clase",
        "calibration_caveat": "cambios aún no calibrados con re-exportaciones reales",
        "in_progress": "en curso",
        "withdrawn": "retirado por quien lo abrió el {date}",
        "limits_title": "Límites",
        "limits": (
            "La fecha la pone " + BRAND + ", no quien sube; pero sin marca de tiempo externa, "
            "creerla es confiar en que " + BRAND + " no alteró su base: conviene guardar "
            "chain.json aparte.|"
            "Nada se recorta sin dejar evento, pero quien sube eligió cuándo abrir y si "
            "publicar, y " + BRAND + " no ve sus otras cuentas.|"
            "Un estado muestra operaciones cerradas: una pérdida abierta el día de una carga "
            "puede no verse.|"
            "Nada prueba que el bróker emitió el archivo, ni se detecta a un falsificador "
            "consistente desde el primer día."
        ),
        "other_record": "¿Te pasaron otro historial? Revísalo en " + BRAND,
        "chain_link": "chain.json",
        "chain_help": "La cadena completa con la receta de cada hash, para recalcularla aparte.",
        "badge_in_progress": "en curso",
        "example_banner": "Ejemplo con datos inventados; no es el historial de nadie",
        "coherence_title": "Coherencia del archivo: ejemplo",
        "coherence_lead": (
            "Un estado de cuenta inventado y el mismo estado con tres ediciones: qué huellas "
            "deja cada una, cuáles no se ven y los límites del método."
        ),
        "coh_original": "Estado original",
        "coh_copied": "Con una operación duplicada (el mismo ticket dos veces, una hora después)",
        "coh_changed": "Con el resultado de una operación cambiado y el resumen sin tocar",
        "coh_careful": "Con una operación borrada y el resumen recalculado a mano",
        "coh_found": "Huellas medidas: {n} chequeos.",
        "coh_none": (
            "No encontramos las huellas que revisamos; eso no prueba que el archivo sea original."
        ),
        "coh_signal_sentence": (
            "Puede tener explicaciones legítimas; conviene aclararlo con quien generó el archivo."
        ),
        "coh_method": "El método es público: detecta ediciones descuidadas, no a quien lo estudie.",
        "coh_uncalibrated": (
            "Ninguna huella cuenta como señal todavía: cada chequeo aún no está calibrado con "
            "suficientes archivos reales de este formato (n = {n}); es información, no una "
            "señal."
        ),
        "coh_cols": "Chequeo|Original|Duplicada|Cambiada|Borrada con cuidado",
        "coh_clean": "sin huellas en este chequeo",
        "coh_info": "huella ({n})",
        "coh_signal": "señal ({n})",
        "coh_not_measured": "no medido",
        "coh_details": "Detalle por chequeo (códigos del método)",
        "coh_what_detected": "Qué se detecta",
        "coh_detected_text": (
            "Un ticket repetido y un resumen que ya no cuadra con las filas dejan huella: el "
            "importador compara los totales declarados con las filas, y la batería revisa "
            "tickets duplicados, el orden de los tickets, el signo del resultado frente a los "
            "precios y la precisión de cada símbolo."
        ),
        "coh_what_not": "Qué no se detecta",
        "coh_not_text": (
            "Una edición que también recalcula los totales no deja huella en un estado de MT4 "
            "sin saldo por fila. Tampoco se ve un archivo fabricado con cuidado desde el "
            "principio."
        ),
        "coh_limits": "Límites",
        "coh_limits_text": (
            "Cada huella es una pregunta neutral para quien generó el archivo, nunca una "
            "acusación. Un archivo editado con cuidado pasa estas pruebas."
        ),
        "coh_rows": "Filas leídas: {n}",
        "coh_method_version": "Versión del método",
        "coh_example_note": (
            "El estado es inventado y vive en el código de " + BRAND + "; no se subió ningún "
            "archivo."
        ),
        "not_public_note": "Este historial aún no está publicado.",
    },
    "en": {
        "eyebrow": "Your account",
        "title": "Continuous track record",
        "lead": (
            "Every new account statement you record is compared with the previous one and "
            "chained by hash, dated by " + BRAND + "'s clock, never by the file."
        ),
        "back_account": "Back to my reports",
        "back_records": "Back to my records",
        "quota": "Records opened: {opened} of {allowed}. Deleting one does not free its slot.",
        "none": "You have not opened a record yet.",
        "open_title": "Open a record",
        "open_lead": (
            "Pick one of your paid reports on an account statement (MT4, MT5, Myfxbook, MQL5, "
            "FX Blue) or on a monthly table. Opening is free; the opening date comes from "
            + BRAND
            + "'s clock."
        ),
        "open_none": (
            "No report on your account can open a record: it takes a paid report, uploaded "
            "while signed in, on an account statement or a monthly table (never a tester's)."
        ),
        "report_option": "Report {id} · class {cls} · {date}",
        "report_label": "Report",
        "open_button": "Open record",
        "paying_note": (
            "Each new statement is a report paid through the usual flow; paying changes "
            "neither the class nor any event."
        ),
        "status_open": "open",
        "status_ended": "ended",
        "status_withdrawn": "withdrawn",
        "opened_on": "Opened on",
        "uploads": "Uploads",
        "last_upload": "Last upload",
        "fresh_current": "Up to date",
        "fresh_stale": "no uploads since {date}",
        "class_stretch": "Class of the stretch after the opening",
        "class_pending": "no class yet: {n} of {m} observations",
        "class_full": "Class of the whole record",
        "class_full_note": "includes what came before the opening, which is not covered",
        "time_to_know": "Time to know",
        "ttk_months": (
            "about {months} more months at the current pace ({pace} observations a month) to "
            "reach the minimum of the significance section; an estimate that changes with "
            "every upload, not a forecast"
        ),
        "ttk_reached": (
            "the minimum of the significance section is reached; still an estimate that "
            "changes with every upload, not a forecast"
        ),
        "ttk_no_mean": "no positive mean to measure",
        "ttk_too_few": "cannot be estimated yet: too few observations",
        "observations": "Observations in the stretch",
        "head": "Chain head",
        "method": "Method version",
        "chain_ok": "The chain recomputes correctly.",
        "chain_broken": (
            BRAND + " could not recompute this record's chain: the error is " + BRAND + "'s, "
            "not the uploader's. The class is hidden until it is reviewed."
        ),
        "events_title": "Events",
        "event_opened": "opening",
        "event_uploaded": "upload matching the previous one",
        "event_mismatch": "upload that differs from the previous one",
        "event_ended": "ended by the person who opened it",
        "event_published": "published",
        "event_unpublished": "unpublished",
        "event_hidden": "public page hidden by " + BRAND,
        "event_shown": "public page shown again",
        "mismatch_line": (
            "This upload differs from the previous one in {n} operations; it may be a broker "
            "adjustment or an edit."
        ),
        "op_deleted": "{n} missing",
        "op_inserted": "{n} new before the previous cut-off",
        "op_changed": "{n} changed",
        "op_open_changed": "{n} open ones that do not add up",
        "k_t": "closed operations",
        "k_f": "cash movements",
        "k_o": "open positions",
        "k_m": "months",
        "fields": "fields",
        "count_label": "operations",
        "uploads_title": "Recorded uploads",
        "upload_cols": "No.|Date|Cut-off|Closed operations|Cash movements|Hash",
        "view": "View details",
        "add_title": "Record a new statement",
        "add_lead": (
            "Pick another of your paid reports with the latest statement of the same "
            "account: the complete export, from the beginning."
        ),
        "add_none": "There is no other paid report of yours to record.",
        "add_button": "Record upload",
        "end_button": "End",
        "end_help": "An ended record is frozen with its date; it can be published, not continued.",
        "delete_button": "Delete",
        "delete_confirm_title": "Delete this record?",
        "delete_confirm_lead": (
            "Its uploads and events are deleted. If it was ever published, its link will only "
            "say that it was withdrawn by the person who opened it, and when. Its slot is "
            "not freed."
        ),
        "delete_confirm_button": "Yes, delete",
        "cancel": "Cancel",
        "publish_title": "Publish",
        "publish_lead": (
            "The public page shows dates, counts, the class of the stretch after the "
            "opening, the events (date, kind and how many operations) and the chain head; "
            "never operations, files, account, broker or your e-mail."
        ),
        "holder_checkbox": (
            "I hold this trading account or have its holder's permission to publish this record"
        ),
        "publish_button": "Publish",
        "unpublish_button": "Unpublish",
        "published_since": "Public since",
        "public_link": "Public page",
        "public_off": "The public page is switched off on this service for now.",
        "hidden_note": (
            BRAND + " hid the public page while it looks at a complaint; the record itself "
            "is unchanged."
        ),
        "badge_title": "Badge code",
        "badge_lead": (
            "Links to the public page; shows the class of the stretch after the opening (or "
            '"in progress"), the id, the last upload and the fixed notice.'
        ),
        "badge_html": "HTML",
        "badge_bbcode": "BBCode",
        "badge_markdown": "Markdown",
        "done_opened": "Record opened with today's date.",
        "done_uploaded": "Upload recorded: it matches the previous one.",
        "done_ended": "Record ended.",
        "done_deleted": "Record deleted.",
        "done_published": "Record published.",
        "done_unpublished": "Record unpublished.",
        "refusal_not_found": "That report is not on your account.",
        "refusal_not_own": (
            "That report was saved or paid from someone else's link; only a report you "
            "uploaded while signed in can be used."
        ),
        "refusal_unpaid": "That report is not paid.",
        "refusal_purged": "That report's files were already deleted by retention.",
        "refusal_unsupported_file": (
            "That report holds no account statement of a supported format and no monthly "
            "table; a tester report cannot be used."
        ),
        "refusal_empty_statement": "That statement has no closed operations and no movements.",
        "refusal_stored_file_mismatch": (
            "The stored file does not match its hash: a storage fault of " + BRAND + "'s, "
            "not yours."
        ),
        "refusal_quota": "You have opened the {allowed} records an account admits.",
        "refusal_record_not_open": "That record is not open.",
        "refusal_record_not_found": "That record does not exist on your account.",
        "refusal_already_linked": "That report is already an upload of this record.",
        "refusal_already_public": "Another public record already holds these same operations.",
        "refusal_holder_not_confirmed": ("Publishing needs the holder-or-permission box ticked."),
        "refusal_account_differs": "does not match the record's account",
        "refusal_format_changed": (
            "That statement comes from another export format; it takes the same format as "
            "the first upload."
        ),
        "refusal_currency_changed": "That statement is in a currency other than the record's.",
        "refusal_partial_statement": (
            "That statement starts after the previous one: it takes the complete export of "
            "the history, from the beginning."
        ),
        "refusal_already_recorded": "this file is already recorded",
        "refusal_cutoff_not_advanced": (
            "That statement has no operation after the previous cut-off."
        ),
        "refusal_future_rows": "That statement has rows dated in the future.",
        "refusal_earlier_rows": (
            "That statement starts before the first upload and only adds earlier rows. The "
            "record starts at its first upload: a wider export reaching further back is not "
            "recorded, and it is not a break."
        ),
        "public_eyebrow": "Continuous track record",
        "public_title": "Continuous track record",
        "public_notice_label": "Notice",
        "public_notice": (
            "This page summarises a continuous track record: account statements the person "
            "who opened it recorded on " + BRAND + ", compared with one another and chained "
            "by hash, dated by " + BRAND + "'s clock. The data was supplied by the uploader "
            "and is not verified with a broker. The class describes the statistical evidence "
            "of the stretch after the opening; it is not a guarantee of results, not "
            "investment advice and not an endorsement of any vendor or product."
        ),
        "public_since": "public since {date} ({days} days after it was opened)",
        "unpublished_period": "not public from {start} to {end}",
        "ended_frozen": "Ended on {date}: frozen since then.",
        "account_records": (
            "Records opened by this account: {n}. " + BRAND + " does not see other accounts "
            "of the same person."
        ),
        "paid_note": "paid by the uploader; paying does not change the class",
        "calibration_caveat": "changes not yet calibrated with real re-exports",
        "in_progress": "in progress",
        "withdrawn": "withdrawn by the person who opened it on {date}",
        "limits_title": "Limits",
        "limits": (
            "The date is " + BRAND + "'s, not the uploader's; but without an external "
            "timestamp, believing it means trusting that " + BRAND + " did not alter its "
            "database: keeping chain.json elsewhere is wise.|"
            "Nothing is cut without leaving an event, but the uploader chose when to open "
            "and whether to publish, and " + BRAND + " does not see their other accounts.|"
            "A statement shows closed operations: an open loss on the day of an upload may "
            "not show.|"
            "Nothing proves the broker issued the file, and a consistent forger from day "
            "one is not detected."
        ),
        "other_record": "Were you handed another record? Check it on " + BRAND,
        "chain_link": "chain.json",
        "chain_help": "The whole chain with the recipe of each hash, to recompute it elsewhere.",
        "badge_in_progress": "in progress",
        "example_banner": "Sample with invented data; it is nobody's record",
        "coherence_title": "File consistency: sample",
        "coherence_lead": (
            "An invented account statement and the same statement with three edits: which "
            "traces each one leaves, which are not seen and the limits of the method."
        ),
        "coh_original": "Original statement",
        "coh_copied": "With a duplicated operation (the same ticket twice, an hour later)",
        "coh_changed": "With one operation's result changed and the summary left alone",
        "coh_careful": "With one operation deleted and the summary recomputed by hand",
        "coh_found": "Traces measured: {n} checks.",
        "coh_none": (
            "We did not find the traces we review; that does not prove the file is original."
        ),
        "coh_signal_sentence": (
            "It may have legitimate explanations; it is worth clarifying with whoever "
            "generated the file."
        ),
        "coh_method": (
            "The method is public: it detects careless edits, not someone who studies it."
        ),
        "coh_uncalibrated": (
            "No trace counts as a signal yet: each check is not yet calibrated on enough "
            "real files of this format (n = {n}); it is information, not a signal."
        ),
        "coh_cols": "Check|Original|Duplicated|Changed|Carefully deleted",
        "coh_clean": "no traces in this check",
        "coh_info": "trace ({n})",
        "coh_signal": "signal ({n})",
        "coh_not_measured": "not measured",
        "coh_details": "Detail per check (method codes)",
        "coh_what_detected": "What is detected",
        "coh_detected_text": (
            "A repeated ticket and a summary that no longer adds up with the rows leave a "
            "trace: the importer compares the declared totals with the rows, and the battery "
            "reviews duplicated tickets, ticket order, the sign of the result against the "
            "prices and the precision of each symbol."
        ),
        "coh_what_not": "What is not detected",
        "coh_not_text": (
            "An edit that also recomputes the totals leaves no trace in an MT4 statement "
            "without a balance per row. Nor is a file fabricated with care from the start "
            "seen."
        ),
        "coh_limits": "Limits",
        "coh_limits_text": (
            "Each trace is a neutral question for whoever generated the file, never an "
            "accusation. A carefully edited file passes these tests."
        ),
        "coh_rows": "Rows read: {n}",
        "coh_method_version": "Method version",
        "coh_example_note": (
            "The statement is invented and lives in " + BRAND + "'s code; no file was uploaded."
        ),
        "not_public_note": "This record is not published yet.",
    },
    "pt": {
        "eyebrow": "Sua conta",
        "title": "Histórico contínuo",
        "lead": (
            "Cada extrato novo que você registrar é comparado com o anterior e encadeado por "
            "hash, com a data do relógio do " + BRAND + ", nunca a do arquivo."
        ),
        "back_account": "Voltar aos meus relatórios",
        "back_records": "Voltar aos meus históricos",
        "quota": "Históricos abertos: {opened} de {allowed}. Excluir um não libera a vaga.",
        "none": "Você ainda não abriu nenhum histórico.",
        "open_title": "Abrir um histórico",
        "open_lead": (
            "Escolha um relatório pago seu sobre um extrato de conta (MT4, MT5, Myfxbook, "
            "MQL5, FX Blue) ou uma tabela mensal. Abrir é grátis; a data de abertura vem do "
            "relógio do " + BRAND + "."
        ),
        "open_none": (
            "Nenhum relatório da sua conta serve para abrir um histórico: é preciso um "
            "relatório pago, enviado com a sessão iniciada, sobre um extrato de conta ou uma "
            "tabela mensal (nunca do testador)."
        ),
        "report_option": "Relatório {id} · classe {cls} · {date}",
        "report_label": "Relatório",
        "open_button": "Abrir histórico",
        "paying_note": (
            "Cada extrato novo é um relatório pago pelo fluxo normal; pagar não muda a classe "
            "nem nenhum evento."
        ),
        "status_open": "aberto",
        "status_ended": "encerrado",
        "status_withdrawn": "retirado",
        "opened_on": "Aberto em",
        "uploads": "Envios",
        "last_upload": "Último envio",
        "fresh_current": "Em dia",
        "fresh_stale": "sem envios desde {date}",
        "class_stretch": "Classe do trecho após a abertura",
        "class_pending": "ainda sem classe: {n} de {m} observações",
        "class_full": "Classe do histórico completo",
        "class_full_note": "inclui o que veio antes da abertura, que não está coberto",
        "time_to_know": "Tempo para saber",
        "ttk_months": (
            "faltam uns {months} meses no ritmo atual ({pace} observações por mês) para "
            "chegar ao mínimo da seção de significância; é uma estimativa que muda a cada "
            "envio, não uma previsão"
        ),
        "ttk_reached": (
            "o mínimo da seção de significância já foi atingido; continua sendo uma "
            "estimativa que muda a cada envio, não uma previsão"
        ),
        "ttk_no_mean": "não há média positiva para medir",
        "ttk_too_few": "ainda não dá para estimar: faltam observações",
        "observations": "Observações do trecho",
        "head": "Cabeça da cadeia",
        "method": "Versão do método",
        "chain_ok": "A cadeia é recalculada sem erro.",
        "chain_broken": (
            "O "
            + BRAND
            + " não conseguiu recalcular a cadeia deste histórico: o erro é do "
            + BRAND
            + ", não de quem enviou os arquivos. A classe fica oculta até a revisão."
        ),
        "events_title": "Eventos",
        "event_opened": "abertura",
        "event_uploaded": "envio que coincide com o anterior",
        "event_mismatch": "envio que não coincide com o anterior",
        "event_ended": "encerrado por quem o abriu",
        "event_published": "publicado",
        "event_unpublished": "despublicado",
        "event_hidden": "página pública ocultada pelo " + BRAND,
        "event_shown": "página pública mostrada de novo",
        "mismatch_line": (
            "Este envio não coincide com o anterior em {n} operações; pode ser um ajuste da "
            "corretora ou uma edição."
        ),
        "op_deleted": "{n} que faltam",
        "op_inserted": "{n} novas antes do corte anterior",
        "op_changed": "{n} alteradas",
        "op_open_changed": "{n} abertas que não batem",
        "k_t": "operações fechadas",
        "k_f": "movimentos de caixa",
        "k_o": "posições abertas",
        "k_m": "meses",
        "fields": "campos",
        "count_label": "operações",
        "uploads_title": "Envios registrados",
        "upload_cols": "N.º|Data|Corte|Operações fechadas|Movimentos de caixa|Hash",
        "view": "Ver detalhes",
        "add_title": "Registrar um extrato novo",
        "add_lead": (
            "Escolha outro relatório pago seu com o extrato mais recente da mesma conta: a "
            "exportação completa, desde o início."
        ),
        "add_none": "Não há outro relatório pago seu para registrar.",
        "add_button": "Registrar envio",
        "end_button": "Encerrar",
        "end_help": (
            "Um histórico encerrado fica congelado com sua data; pode ser publicado, não "
            "continuado."
        ),
        "delete_button": "Excluir",
        "delete_confirm_title": "Excluir este histórico?",
        "delete_confirm_lead": (
            "Seus envios e eventos são excluídos. Se algum dia esteve publicado, seu link dirá "
            "apenas que foi retirado por quem o abriu, e quando. A vaga não é liberada."
        ),
        "delete_confirm_button": "Sim, excluir",
        "cancel": "Cancelar",
        "publish_title": "Publicar",
        "publish_lead": (
            "A página pública mostra datas, quantidades, a classe do trecho após a abertura, "
            "os eventos (data, tipo e quantas operações) e a cabeça da cadeia; nunca "
            "operações, arquivos, conta, corretora nem seu e-mail."
        ),
        "holder_checkbox": (
            "Sou titular desta conta de trading ou tenho permissão do titular para publicar "
            "este histórico"
        ),
        "publish_button": "Publicar",
        "unpublish_button": "Despublicar",
        "published_since": "Público desde",
        "public_link": "Página pública",
        "public_off": "A página pública está desligada neste serviço por enquanto.",
        "hidden_note": (
            "O " + BRAND + " ocultou a página pública enquanto analisa uma reclamação; o "
            "histórico continua igual."
        ),
        "badge_title": "Código da insígnia",
        "badge_lead": (
            "Leva à página pública; mostra a classe do trecho após a abertura (ou «em "
            "andamento»), o id, o último envio e o aviso fixo."
        ),
        "badge_html": "HTML",
        "badge_bbcode": "BBCode",
        "badge_markdown": "Markdown",
        "done_opened": "Histórico aberto com a data de hoje.",
        "done_uploaded": "Envio registrado: coincide com o anterior.",
        "done_ended": "Histórico encerrado.",
        "done_deleted": "Histórico excluído.",
        "done_published": "Histórico publicado.",
        "done_unpublished": "Histórico despublicado.",
        "refusal_not_found": "Esse relatório não está na sua conta.",
        "refusal_not_own": (
            "Esse relatório foi salvo ou pago pelo link de outra pessoa; só serve um "
            "relatório que você enviou com a sessão iniciada."
        ),
        "refusal_unpaid": "Esse relatório não está pago.",
        "refusal_purged": "Os arquivos desse relatório já foram excluídos pela retenção.",
        "refusal_unsupported_file": (
            "Esse relatório não tem um extrato de conta de um formato aceito nem uma tabela "
            "mensal; um relatório do testador não serve."
        ),
        "refusal_empty_statement": "Esse extrato não tem operações fechadas nem movimentos.",
        "refusal_stored_file_mismatch": (
            "O arquivo guardado não confere com seu hash: uma falha de armazenamento do "
            + BRAND
            + ", não sua."
        ),
        "refusal_quota": "Você já abriu os {allowed} históricos que uma conta admite.",
        "refusal_record_not_open": "Esse histórico não está aberto.",
        "refusal_record_not_found": "Esse histórico não existe na sua conta.",
        "refusal_already_linked": "Esse relatório já é um envio deste histórico.",
        "refusal_already_public": "Outro histórico público já tem estas mesmas operações.",
        "refusal_holder_not_confirmed": (
            "Para publicar é preciso marcar a caixa de titular ou permissão."
        ),
        "refusal_account_differs": "não coincide com a conta do histórico",
        "refusal_format_changed": (
            "Esse extrato vem de outro formato de exportação; é preciso o mesmo formato do "
            "primeiro envio."
        ),
        "refusal_currency_changed": "Esse extrato está em outra moeda que a do histórico.",
        "refusal_partial_statement": (
            "Esse extrato começa depois do anterior: é preciso a exportação completa do "
            "histórico, desde o início."
        ),
        "refusal_already_recorded": "este arquivo já está registrado",
        "refusal_cutoff_not_advanced": (
            "Esse extrato não tem nenhuma operação depois do corte anterior."
        ),
        "refusal_future_rows": "Esse extrato tem linhas com data futura.",
        "refusal_earlier_rows": (
            "Esse extrato começa antes do primeiro envio e só acrescenta linhas anteriores. "
            "O histórico começa no seu primeiro envio: uma exportação mais ampla para trás "
            "não é registrada, e não é uma quebra."
        ),
        "public_eyebrow": "Histórico contínuo",
        "public_title": "Histórico contínuo",
        "public_notice_label": "Aviso",
        "public_notice": (
            "Esta página resume um histórico contínuo: extratos de conta que quem o abriu "
            "registrou no " + BRAND + ", comparados entre si e encadeados por hash, com datas "
            "do relógio do " + BRAND + ". Os dados foram fornecidos por quem os enviou e não "
            "estão verificados com a corretora. A classe descreve a evidência estatística do "
            "trecho após a abertura; não garante resultados, não é recomendação de "
            "investimento e não endossa nenhum vendedor nem produto."
        ),
        "public_since": "público desde {date} ({days} dias depois de ser aberto)",
        "unpublished_period": "sem publicar de {start} a {end}",
        "ended_frozen": "Encerrado em {date}: congelado desde então.",
        "account_records": (
            "Históricos abertos por esta conta: {n}. O " + BRAND + " não vê outras contas da "
            "mesma pessoa."
        ),
        "paid_note": "pago por quem envia o arquivo; pagar não muda a classe",
        "calibration_caveat": "mudanças ainda não calibradas com re-exportações reais",
        "in_progress": "em andamento",
        "withdrawn": "retirado por quem o abriu em {date}",
        "limits_title": "Limites",
        "limits": (
            "A data é do " + BRAND + ", não de quem envia; mas sem um carimbo de tempo "
            "externo, acreditar nela é confiar que o " + BRAND + " não alterou seu banco de "
            "dados: convém guardar o chain.json à parte.|"
            "Nada é cortado sem deixar evento, mas quem envia escolheu quando abrir e se "
            "publicar, e o " + BRAND + " não vê suas outras contas.|"
            "Um extrato mostra operações fechadas: uma perda aberta no dia de um envio pode "
            "não aparecer.|"
            "Nada prova que a corretora emitiu o arquivo, nem se detecta um falsificador "
            "consistente desde o primeiro dia."
        ),
        "other_record": "Recebeu outro histórico? Confira no " + BRAND,
        "chain_link": "chain.json",
        "chain_help": "A cadeia completa com a receita de cada hash, para recalcular à parte.",
        "badge_in_progress": "em andamento",
        "example_banner": "Exemplo com dados inventados; não é o histórico de ninguém",
        "coherence_title": "Coerência do arquivo: exemplo",
        "coherence_lead": (
            "Um extrato de conta inventado e o mesmo extrato com três edições: que rastros "
            "cada uma deixa, quais não aparecem e os limites do método."
        ),
        "coh_original": "Extrato original",
        "coh_copied": "Com uma operação duplicada (o mesmo ticket duas vezes, uma hora depois)",
        "coh_changed": "Com o resultado de uma operação alterado e o resumo intocado",
        "coh_careful": "Com uma operação apagada e o resumo recalculado à mão",
        "coh_found": "Rastros medidos: {n} verificações.",
        "coh_none": (
            "Não encontramos os rastros que revisamos; isso não prova que o arquivo seja original."
        ),
        "coh_signal_sentence": (
            "Pode ter explicações legítimas; convém esclarecer com quem gerou o arquivo."
        ),
        "coh_method": "O método é público: detecta edições descuidadas, não quem o estuda.",
        "coh_uncalibrated": (
            "Nenhum rastro conta como sinal ainda: cada verificação ainda não está calibrada "
            "com arquivos reais suficientes deste formato (n = {n}); é informação, não um "
            "sinal."
        ),
        "coh_cols": "Verificação|Original|Duplicada|Alterada|Apagada com cuidado",
        "coh_clean": "sem rastros nesta verificação",
        "coh_info": "rastro ({n})",
        "coh_signal": "sinal ({n})",
        "coh_not_measured": "não medido",
        "coh_details": "Detalhe por verificação (códigos do método)",
        "coh_what_detected": "O que é detectado",
        "coh_detected_text": (
            "Um ticket repetido e um resumo que já não bate com as linhas deixam rastro: o "
            "importador compara os totais declarados com as linhas, e a bateria revisa "
            "tickets duplicados, a ordem dos tickets, o sinal do resultado frente aos preços "
            "e a precisão de cada símbolo."
        ),
        "coh_what_not": "O que não é detectado",
        "coh_not_text": (
            "Uma edição que também recalcula os totais não deixa rastro num extrato de MT4 "
            "sem saldo por linha. Também não se vê um arquivo fabricado com cuidado desde o "
            "início."
        ),
        "coh_limits": "Limites",
        "coh_limits_text": (
            "Cada rastro é uma pergunta neutra para quem gerou o arquivo, nunca uma "
            "acusação. Um arquivo editado com cuidado passa nestes testes."
        ),
        "coh_rows": "Linhas lidas: {n}",
        "coh_method_version": "Versão do método",
        "coh_example_note": (
            "O extrato é inventado e vive no código do " + BRAND + "; nenhum arquivo foi enviado."
        ),
        "not_public_note": "Este histórico ainda não está publicado.",
    },
}

#: Words that never reach a screen of this feature (design §8), with the
#: exact phrases the fixed notices and the prompt allow.
FORBIDDEN_WORDS: dict[str, tuple[str, ...]] = {
    "es": (
        "auténtico",
        "auténtica",
        "genuino",
        "genuina",
        "verificado",
        "verificada",
        "verificados",
        "verificadas",
        "inalterable",
        "limpio",
        "limpia",
        "falso",
        "falsa",
        "manipulado",
        "manipulada",
        "sello",
        "sellado",
        "sellada",
        "para siempre",
        "demuestra",
        "es real",
        "historial real",
        "archivo real",
        "detén",
        "pausa",
        "copia",
        "invierte",
        "compra",
        "vende",
    ),
    "en": (
        "authentic",
        "genuine",
        "verified",
        "unalterable",
        "clean",
        "fake",
        "manipulated",
        "seal",
        "sealed",
        "forever",
        "is real",
        "real record",
        "real file",
        "stop",
        "pause",
        "copy",
        "invest",
        "buy",
        "sell",
    ),
    "pt": (
        "autêntico",
        "autêntica",
        "genuíno",
        "genuína",
        "verificado",
        "verificada",
        "verificados",
        "verificadas",
        "inalterável",
        "limpo",
        "limpa",
        "falso",
        "falsa",
        "manipulado",
        "manipulada",
        "selo",
        "selado",
        "selada",
        "para sempre",
        "demonstra",
        "é real",
        "histórico real",
        "arquivo real",
        "pare",
        "pause",
        "copie",
        "invista",
        "compre",
        "venda",
    ),
}
#: Exact phrases the forbidden-word test lets through: the fixed notices'
#: negation and the calibration corpus ("archivos reales").
ALLOWED_PHRASES: tuple[str, ...] = (
    "no están verificados con el bróker",
    "not verified with a broker",
    "não estão verificados com a corretora",
    "re-exportaciones reales",
    "real re-exports",
    "re-exportações reais",
    "archivos reales",
    "real files",
    "arquivos reais",
)


def all_texts() -> list[str]:
    """Every sentence of the pages, for the guard and the word tests."""
    return [text for copy in COPY.values() for text in copy.values()]


__all__ = ["ALLOWED_PHRASES", "COPY", "FORBIDDEN_WORDS", "LANGUAGES", "PATHS", "all_texts"]
