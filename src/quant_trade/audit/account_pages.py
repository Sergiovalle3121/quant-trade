"""The account pages: sign up, sign in, "My reports", password and deletion.

Every page exists in Spanish (default) and English. Forms post back to the
same paths with a CSRF token; nothing here runs script. The pages reuse the
site's shell (``pages._page``) so the redesign styles them with the rest.
"""

from __future__ import annotations

from collections.abc import Sequence

from quant_trade.audit.accounts import FREE_PREVIEWS_PER_MONTH, MIN_PASSWORD_CHARS
from quant_trade.audit.compare import guard_page
from quant_trade.audit.engine import _safe_text
from quant_trade.audit.pages import _e, _field, _page, _page_hero
from quant_trade.audit.seo import BRAND
from quant_trade.audit.store import AccountAudit, AccountCode, AccountRecord
from quant_trade.audit.theme import CLASS_COLOURS, icon

#: Spanish paths are the default; English paths show the same page in English.
PATHS: dict[str, dict[str, str]] = {
    "es": {
        "signup": "/registro",
        "signin": "/entrar",
        "signout": "/salir",
        "account": "/cuenta",
        "forgot": "/olvide",
        "reset": "/restablecer",
    },
    "en": {
        "signup": "/signup",
        "signin": "/login",
        "signout": "/logout",
        "account": "/account",
        "forgot": "/forgot",
        "reset": "/reset",
    },
}

COPY: dict[str, dict[str, str]] = {
    "es": {
        "eyebrow": "Tu cuenta",
        "signup_title": "Crea tu cuenta",
        "signup_lead": (
            "Al crear tu cuenta, tu primer informe completo es gratis, con PDF. Después "
            f"tienes {FREE_PREVIEWS_PER_MONTH} vistas previas gratis al mes, y tus informes, "
            "créditos y compras en un solo lugar."
        ),
        "signin_title": "Entra a tu cuenta",
        "signin_lead": "Tus informes, créditos y compras te esperan aquí.",
        "email": "Correo electrónico",
        "password": "Contraseña",
        "password_new": "Contraseña nueva",
        "password_current": "Contraseña actual",
        "password_help": f"Al menos {MIN_PASSWORD_CHARS} caracteres. Una frase larga sirve.",
        "signup_button": "Crear cuenta",
        "signin_button": "Entrar",
        "have_account": "¿Ya tienes cuenta?",
        "no_account": "¿Aún no tienes cuenta?",
        "signin_link": "Entra",
        "signup_link": "Crea una gratis",
        "forgot_link": "Olvidé mi contraseña",
        "terms_agree": "Al crear la cuenta aceptas los {terms} y la {privacy}.",
        "terms_link": "términos del servicio",
        "privacy_link": "política de privacidad",
        "benefits": (
            "Todos tus informes en una lista, con su clase|"
            "Tus créditos de acceso a la vista, sin buscar el código|"
            "Desbloquea un informe con un clic usando tus créditos|"
            "Tus compras con tarjeta o código, con fecha"
        ),
        "email_bad": "Ese correo no parece válido.",
        "password_short": f"La contraseña necesita al menos {MIN_PASSWORD_CHARS} caracteres.",
        "password_long": "La contraseña es demasiado larga (máximo 256 caracteres).",
        "password_bad": "La contraseña tiene un carácter que no se puede usar.",
        "password_common": (
            "Esa contraseña es de las primeras que prueba cualquier lista de adivinanzas. Usa una "
            "frase propia, por ejemplo tres o cuatro palabras que solo tú asocies."
        ),
        "taken": (
            "No se pudo crear una cuenta con ese correo. Si ya tienes una, entra con tu contraseña."
        ),
        "wrong": "El correo o la contraseña no coinciden.",
        "too_many": "Demasiados intentos. Espera una hora y vuelve a probar.",
        "csrf": "El formulario caducó. Recarga la página y vuelve a enviarlo.",
        "signed_out": "Saliste de tu cuenta.",
        "welcome": "Cuenta creada. Ya puedes subir un archivo: el informe se guarda aquí.",
        "account_title": "Mis informes",
        "account_lead": "Todo lo que auditaste con esta cuenta, en un solo lugar.",
        "signed_in_as": "Sesión iniciada como",
        "signout_button": "Salir",
        "credits": "Créditos disponibles",
        "credits_help": "Cada crédito desbloquea un informe completo.",
        "reports": "Informes",
        "paid_reports": "Informes completos",
        "new_audit": "Auditar otro archivo",
        "first_audit": "Subir mi primer archivo",
        "reports_title": "Tus informes",
        "reports_none": (
            "Aún no hay informes en tu cuenta. Sube un archivo con la sesión iniciada, o abre "
            "un informe que ya tengas y pulsa «Guardar en mi cuenta»."
        ),
        "col_date": "Fecha",
        "col_class": "Clase",
        "col_status": "Estado",
        "col_what": "Descripción",
        "open": "Abrir",
        "pdf": "PDF",
        "public_page": "Página pública",
        "compare_pick_label": "Elegir para comparar",
        "compare_button": "Comparar los dos elegidos",
        "compare_help": "Marca dos informes completos y compáralos lado a lado, sin pegar enlaces.",
        "compare_pick": "Elige exactamente dos informes completos de tu lista para compararlos.",
        "compare_back": "Volver a mis informes",
        "compare_mine": "¿Son informes de tu cuenta? Compáralos desde tu lista, sin pegar enlaces.",
        "compare_mine_button": "Elegir en mis informes",
        "compare_lead": (
            "Dos informes de tu cuenta. Sirve para ver qué cambió entre dos versiones de una "
            "estrategia o entre dos robots."
        ),
        "status_full": "Completo",
        "status_preview": "Vista previa",
        "status_purged": "Archivos borrados",
        "status_published": "Página pública",
        "status_saved": "Guardado desde un enlace",
        "paid_card": "tarjeta",
        "paid_code": "código",
        "paid_welcome": "gratis, primer informe",
        "welcome_kpi": "Primer informe completo gratis",
        "welcome_available": "Disponible",
        "welcome_used": "Usado",
        "welcome_notice": (
            "Tu primer informe completo es gratis por crear tu cuenta, con PDF y página de "
            "verificación. Para tus siguientes archivos tienes {limit} vistas previas gratis al "
            "mes; el informe completo cuesta {price} ({pack} el paquete de 3)."
        ),
        "no_description": "Sin descripción",
        "codes_title": "Tus códigos de acceso",
        "codes_none": "Aún no hay códigos en tu cuenta.",
        "codes_help": (
            "Un código que canjeas con la sesión iniciada se guarda aquí solo. También puedes "
            "añadir uno que ya tengas."
        ),
        "code_label": "Código de acceso",
        "code_add": "Añadir a mi cuenta",
        "code_linked": "Código añadido a tu cuenta.",
        "code_already": "Ese código ya está en tu cuenta.",
        "code_other": "Ese código ya está guardado en otra cuenta.",
        "code_unknown": "No encontramos ese código. Revisa que esté completo.",
        "col_code": "Código",
        "col_added": "Añadido",
        "col_left": "Quedan",
        "col_used": "Usados",
        "col_expires": "Caduca",
        "code_ref": "n.º",
        "code_off": "desactivado",
        "code_expired": "caducado",
        "code_empty": "agotado",
        "never": "nunca",
        "purchases_title": "Tus compras",
        "purchases_none": "Aún no hay compras en tu cuenta.",
        "col_report": "Informe",
        "stores_title": "Qué guardamos y cómo borrarlo",
        "stores": (
            "Tu correo y una huella de tu contraseña (scrypt): nunca la contraseña en sí.|"
            "Tus informes y los archivos que subes. De los que no se pagan borramos archivos e "
            "informe a los {days} días (queda solo su huella); los pagados y tu informe gratis "
            "quedan para que sigas abriéndolos.|"
            "La dirección IP de cada subida, para los límites de uso; la borramos a los {days} "
            "días.|"
            "Tus códigos y compras, con fecha. Nunca vemos ni guardamos los datos de tu "
            "tarjeta: el pago con tarjeta lo procesa Stripe.|"
            "Una marca aleatoria de tu navegador y la huella del archivo, solo para dar el "
            "informe gratis una vez. Se conservan aunque borres la cuenta, sin tu correo.|"
            "Para borrar todo: «Borrar mi cuenta», al final de «Mi cuenta». Quita al instante tu "
            "correo, contraseña, sesiones y listas; puedes borrar también los informes que "
            "subiste."
        ),
        "col_paid": "Pagado",
        "col_method": "Con",
        "buy_title": "¿Necesitas créditos?",
        "buy_code": "Comprar por WhatsApp",
        "buy_code_how": (
            "Nos escribes por WhatsApp; el mensaje ya dice que es para tu cuenta.|"
            "Te respondemos con los datos para pagar.|"
            "Al confirmarse el pago recibes un código: lo escribes en «Código de acceso» y los "
            "créditos quedan en tu cuenta."
        ),
        "buy_code_wait": (
            "Responde una persona. Si escribes de noche o en fin de semana, te contestamos en "
            "cuanto lo veamos."
        ),
        "buy_prices_single": "Un informe completo: {price}.",
        "buy_prices_pack": "Paquete de 3 créditos: {price}.",
        "buy_message": (
            "Hola, quiero créditos para mi cuenta: un informe completo o el paquete de 3."
        ),
        "buy_card": "Paga con tarjeta desde la vista previa de cualquier informe.",
        "security_title": "Contraseña y datos",
        "change_password": "Cambiar contraseña",
        "password_changed": "Contraseña cambiada. Cerramos las demás sesiones.",
        "delete_title": "Borrar mi cuenta",
        "delete_help": (
            "Borra tu correo, tu contraseña, tus sesiones y la lista de tus informes y códigos. "
            "Los informes siguen abriendo con su enlace privado hasta su plazo de conservación, "
            "salvo que marques la casilla para borrar también los que subiste con esta cuenta. "
            "Los que guardaste o pagaste desde el enlace de otra persona solo salen de tu lista."
        ),
        "delete_reports": "Borrar también los informes que subí (no se puede deshacer)",
        "delete_button": "Borrar mi cuenta",
        "deleted": "Tu cuenta se borró.",
        "forgot_title": "Recupera tu contraseña",
        "forgot_lead": (
            "Todavía no enviamos correos. Escríbenos desde el correo de tu cuenta y te "
            "mandamos un enlace de un solo uso para poner una contraseña nueva."
        ),
        "forgot_contact": "Escribir por WhatsApp",
        "forgot_message": f"Hola, olvidé la contraseña de mi cuenta de {BRAND}. Mi correo es: ",
        "reset_title": "Pon una contraseña nueva",
        "reset_lead": "Este enlace funciona una sola vez y caduca en 24 horas.",
        "reset_button": "Guardar contraseña",
        "reset_bad": "Este enlace ya se usó o caducó. Pide uno nuevo.",
        "reset_done": "Contraseña guardada. Entra con ella.",
        "saved_box": "Guardado en tu cuenta.",
        "saved_link": "Ver mis informes",
        "save_box": "Guarda este informe en tu cuenta para encontrarlo sin el enlace.",
        "save_button": "Guardar en mi cuenta",
        "save_other": "Este informe está guardado en otra cuenta.",
        "anon_box": (
            "Crea una cuenta gratis para guardar este informe y encontrarlo sin el enlace."
        ),
        "anon_signup": "Crear cuenta",
        "anon_signin": "Entrar",
        "credit_button": "Desbloquear con 1 crédito de tu cuenta",
        "credit_left": "Tienes {n} créditos.",
        "credit_left_one": "Tienes 1 crédito.",
        "credit_used": "Crédito usado: este es el informe completo.",
        "free_left": "Vistas previas gratis este mes",
        "free_left_value": "{left} de {limit}",
        "gate_signin_title": "Crea tu cuenta gratis: tu primer informe completo no se paga",
        "gate_signin_lead": (
            "Al crear tu cuenta, el primer archivo que subas sale como informe completo, con "
            "PDF, sin pagar. Después tienes {limit} vistas previas gratis cada mes: la clase de "
            "A a D, las gráficas y las señales de alerta. Tu archivo no se guardó: al crear tu "
            "cuenta vuelves al formulario para subirlo otra vez. Si ya tienes un código de "
            "acceso, escríbelo en el formulario y no necesitas cuenta."
        ),
        "gate_code_title": "Ese código no sirve",
        "gate_code_lead": (
            "No encontramos ese código o ya no le quedan créditos. Revísalo, o crea una cuenta "
            "gratis para tener {limit} vistas previas cada mes."
        ),
        "gate_quota_title": "Ya usaste tus {limit} vistas previas gratis de este mes",
        "gate_quota_lead": (
            "Se renuevan el día 1 de cada mes. Para auditar ahora, añade créditos a tu cuenta: "
            "con créditos, cada archivo nuevo sale como informe completo."
        ),
        "gate_network_title": "Esta red ya usó sus vistas previas gratis de este mes",
        "gate_network_lead": (
            "Contamos las vistas previas gratis también por red, para frenar cuentas "
            "desechables. Puedes auditar con un código o con créditos en tu cuenta, o volver "
            "el día 1."
        ),
        "gate_signup": "Crear cuenta gratis",
        "gate_signin": "Ya tengo cuenta",
        "gate_buy": "Ver precios y añadir créditos",
        "gate_back": "Volver al inicio",
        "credit_on_upload": "Usamos 1 crédito de tu cuenta: este es el informe completo.",
        "credit_none": "No te quedan créditos en tu cuenta.",
        "saved_notice": "Informe guardado en tu cuenta.",
        "nav_account": "Mi cuenta",
    },
    "en": {
        "eyebrow": "Your account",
        "signup_title": "Create your account",
        "signup_lead": (
            "When you create your account, your first full report is free, with the PDF. "
            f"Then you get {FREE_PREVIEWS_PER_MONTH} free previews a month, and your reports, "
            "credits and purchases in one place."
        ),
        "signin_title": "Sign in to your account",
        "signin_lead": "Your reports, credits and purchases are waiting here.",
        "email": "E-mail",
        "password": "Password",
        "password_new": "New password",
        "password_current": "Current password",
        "password_help": f"At least {MIN_PASSWORD_CHARS} characters. A long phrase works.",
        "signup_button": "Create account",
        "signin_button": "Sign in",
        "have_account": "Already have an account?",
        "no_account": "No account yet?",
        "signin_link": "Sign in",
        "signup_link": "Create one for free",
        "forgot_link": "I forgot my password",
        "terms_agree": "By creating the account you accept the {terms} and {privacy}.",
        "terms_link": "terms of service",
        "privacy_link": "privacy policy",
        "benefits": (
            "All your reports in one list, with their class|"
            "Your access credits in sight, no code to look up|"
            "Unlock a report in one click with your credits|"
            "Your card and code purchases, with dates"
        ),
        "email_bad": "That e-mail address does not look valid.",
        "password_short": f"The password needs at least {MIN_PASSWORD_CHARS} characters.",
        "password_long": "The password is too long (256 characters at most).",
        "password_bad": "The password has a character that cannot be used.",
        "password_common": (
            "That password is among the first any guessing list tries. Use a phrase of your own, "
            "for example three or four words only you would put together."
        ),
        "taken": (
            "An account could not be created with that e-mail. If you already have one, sign "
            "in with your password."
        ),
        "wrong": "The e-mail or the password does not match.",
        "too_many": "Too many attempts. Wait an hour and try again.",
        "csrf": "The form expired. Reload the page and submit it again.",
        "signed_out": "You signed out.",
        "welcome": "Account created. Upload a file now: the report is saved here.",
        "account_title": "My reports",
        "account_lead": "Everything you audited with this account, in one place.",
        "signed_in_as": "Signed in as",
        "signout_button": "Sign out",
        "credits": "Credits available",
        "credits_help": "Each credit unlocks one full report.",
        "reports": "Reports",
        "paid_reports": "Full reports",
        "new_audit": "Audit another file",
        "first_audit": "Upload my first file",
        "reports_title": "Your reports",
        "reports_none": (
            "No reports on your account yet. Upload a file while signed in, or open a report "
            "you already have and press “Save to my account”."
        ),
        "col_date": "Date",
        "col_class": "Class",
        "col_status": "Status",
        "col_what": "Description",
        "open": "Open",
        "pdf": "PDF",
        "public_page": "Public page",
        "compare_pick_label": "Pick to compare",
        "compare_button": "Compare the two picked",
        "compare_help": "Tick two full reports and compare them side by side, no links to paste.",
        "compare_pick": "Pick exactly two full reports from your list to compare them.",
        "compare_back": "Back to my reports",
        "compare_mine": "Are they reports on your account? Compare them from your list, no links.",
        "compare_mine_button": "Pick from my reports",
        "compare_lead": (
            "Two reports from your account. Use it to see what changed between two versions "
            "of a strategy or between two robots."
        ),
        "status_full": "Full",
        "status_preview": "Preview",
        "status_purged": "Files deleted",
        "status_published": "Public page",
        "status_saved": "Saved from a link",
        "paid_card": "card",
        "paid_code": "code",
        "paid_welcome": "free, first report",
        "welcome_kpi": "Free first full report",
        "welcome_available": "Available",
        "welcome_used": "Used",
        "welcome_notice": (
            "Your first full report is free for creating your account, with the PDF and the "
            "verification page. For your next files you have {limit} free previews a month; "
            "the full report costs {price} ({pack} for a pack of 3)."
        ),
        "no_description": "No description",
        "codes_title": "Your access codes",
        "codes_none": "No codes on your account yet.",
        "codes_help": (
            "A code you redeem while signed in is saved here on its own. You can also add one "
            "you already have."
        ),
        "code_label": "Access code",
        "code_add": "Add to my account",
        "code_linked": "Code added to your account.",
        "code_already": "That code is already on your account.",
        "code_other": "That code is already saved on another account.",
        "code_unknown": "We could not find that code. Check that it is complete.",
        "col_code": "Code",
        "col_added": "Added",
        "col_left": "Left",
        "col_used": "Used",
        "col_expires": "Expires",
        "code_ref": "no.",
        "code_off": "disabled",
        "code_expired": "expired",
        "code_empty": "used up",
        "never": "never",
        "purchases_title": "Your purchases",
        "purchases_none": "No purchases on your account yet.",
        "col_report": "Report",
        "stores_title": "What we keep and how to delete it",
        "stores": (
            "Your e-mail and a fingerprint of your password (scrypt): never the password itself.|"
            "Your reports and the files you upload. For unpaid ones we delete the files and the "
            "report after {days} days (only their fingerprint stays); paid ones and your free "
            "report stay so you can keep opening them.|"
            "The IP address of each upload, for the usage limits; we delete it after {days} "
            "days.|"
            "Your codes and purchases, with dates. We never see or keep your card details: card "
            "payments are processed by Stripe.|"
            "A random mark of your browser and the file's fingerprint, only to give the free "
            "report once. They stay even if you delete the account, without your e-mail.|"
            "To delete it all: 'Delete my account', at the end of 'My account'. It removes your "
            "e-mail, password, sessions and lists at once; you can delete the reports you "
            "uploaded too."
        ),
        "col_paid": "Paid",
        "col_method": "With",
        "buy_title": "Need credits?",
        "buy_code": "Buy on WhatsApp",
        "buy_code_how": (
            "You message us on WhatsApp; the message already says it is for your account.|"
            "We reply with the payment details.|"
            "Once the payment is confirmed you get a code: enter it under Access code and the "
            "credits land on your account."
        ),
        "buy_code_wait": (
            "A person replies. If you write at night or at the weekend, we answer as soon as "
            "we see it."
        ),
        "buy_prices_single": "One full report: {price}.",
        "buy_prices_pack": "Pack of 3 credits: {price}.",
        "buy_message": "Hi, I want credits for my account: one full report or the pack of 3.",
        "buy_card": "Pay by card from the preview of any report.",
        "security_title": "Password and data",
        "change_password": "Change password",
        "password_changed": "Password changed. Your other sessions were signed out.",
        "delete_title": "Delete my account",
        "delete_help": (
            "Deletes your e-mail, password, sessions and the list of your reports and codes. "
            "The reports still open with their private link until their retention period "
            "ends, unless you tick the box to also delete the ones you uploaded with this "
            "account. Reports saved or paid for from someone else's link only leave your list."
        ),
        "delete_reports": "Also delete the reports I uploaded (cannot be undone)",
        "delete_button": "Delete my account",
        "deleted": "Your account was deleted.",
        "forgot_title": "Recover your password",
        "forgot_lead": (
            "We do not send e-mails yet. Write to us from your account's e-mail and we send "
            "you a one-time link to set a new password."
        ),
        "forgot_contact": "Write on WhatsApp",
        "forgot_message": f"Hi, I forgot the password of my {BRAND} account. My e-mail is: ",
        "reset_title": "Set a new password",
        "reset_lead": "This link works once and expires in 24 hours.",
        "reset_button": "Save password",
        "reset_bad": "This link was already used or has expired. Ask for a new one.",
        "reset_done": "Password saved. Sign in with it.",
        "saved_box": "Saved to your account.",
        "saved_link": "See my reports",
        "save_box": "Save this report to your account to find it without the link.",
        "save_button": "Save to my account",
        "save_other": "This report is saved on another account.",
        "anon_box": "Create a free account to save this report and find it without the link.",
        "anon_signup": "Create account",
        "anon_signin": "Sign in",
        "credit_button": "Unlock with 1 credit from your account",
        "credit_left": "You have {n} credits.",
        "credit_left_one": "You have 1 credit.",
        "credit_used": "Credit used: this is the full report.",
        "free_left": "Free previews this month",
        "free_left_value": "{left} of {limit}",
        "gate_signin_title": "Create your free account: your first full report is on us",
        "gate_signin_lead": (
            "When you create your account, the first file you upload comes out as a full "
            "report, with the PDF, at no cost. Then you get {limit} free previews every month: "
            "the A to D class, the charts and the red flags. Your file was not kept: once your "
            "account exists you are back at the form to upload it again. If you already have "
            "an access code, type it in the form and you need no account."
        ),
        "gate_code_title": "That code does not work",
        "gate_code_lead": (
            "We could not find that code or it has no credits left. Check it, or create a free "
            "account to get {limit} previews every month."
        ),
        "gate_quota_title": "You used your {limit} free previews this month",
        "gate_quota_lead": (
            "They renew on the 1st of each month. To audit now, add credits to your account: "
            "with credits, each new file comes out as a full report."
        ),
        "gate_network_title": "This network used its free previews this month",
        "gate_network_lead": (
            "We also count free previews per network, to slow down throwaway accounts. You can "
            "audit with a code or with credits on your account, or come back on the 1st."
        ),
        "gate_signup": "Create a free account",
        "gate_signin": "I have an account",
        "gate_buy": "See prices and add credits",
        "gate_back": "Back to the home page",
        "credit_on_upload": "We used 1 credit from your account: this is the full report.",
        "credit_none": "There are no credits left on your account.",
        "saved_notice": "Report saved to your account.",
        "nav_account": "My account",
    },
}

ACCOUNT_CSS = """
.acct-grid{display:grid;grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr);gap:36px;
align-items:start}
.acct-card{border:1px solid var(--border);border-radius:18px;padding:24px;
background:#fff}
.acct-perks{background:var(--surface-2)}
.acct-side{display:grid;gap:18px}
.acct-stores h3{margin:0 0 12px;font-size:1rem}
.acct-sec .acct-stores{margin-top:18px}
.acct-form{border:1px solid var(--border);border-radius:18px;padding:28px;background:#fff;
box-shadow:0 1px 2px rgba(0,0,0,.04)}
.acct-form form>p:last-child{margin-bottom:0}
.acct-danger{border-color:rgba(180,35,24,.28)}
.acct-danger h3{color:#b42318}
.acct-danger .btn{color:#b42318;border-color:rgba(180,35,24,.4)}
.acct-card h2{margin-top:0}
.acct-list{list-style:none;padding:0;margin:0;display:grid;gap:12px}
.acct-list li{display:flex;gap:10px;align-items:flex-start}
.acct-list svg{width:18px;height:18px;flex:none;margin-top:3px;color:var(--ok)}
.acct-alt{margin-top:18px;font-size:.92rem}
.acct-terms a{color:var(--text);text-underline-offset:3px}
.acct-head{display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between;
margin-bottom:8px}
.acct-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;
margin:18px 0 28px}
.acct-gift b{font-size:1.3rem;line-height:1.5}
.acct-gift.is-on{border-color:color-mix(in srgb,var(--ok) 45%,var(--border));
background:color-mix(in srgb,var(--ok) 7%,#fff)}
.acct-gift.is-on b{color:var(--ok)}
.acct-box span{display:inline-flex;align-items:center;gap:6px}
.acct-box svg{width:16px;height:16px;flex:none}
.acct-gate{text-align:left}.acct-gate .inline-form{display:flex;flex-wrap:wrap;gap:10px}
.acct-kpi{border:1px solid var(--border);border-radius:16px;padding:16px 18px;
background:#fff}
.acct-kpi b{display:block;font-size:1.9rem;line-height:1.1}
.acct-kpi span{color:var(--text-2);font-size:.86rem}
.acct-table{width:100%;border-collapse:collapse;font-size:.92rem;margin:8px 0 24px}
.acct-table th,.acct-table td{text-align:left;padding:10px 8px;
border-bottom:1px solid var(--border);vertical-align:middle}
.acct-table th{font-size:.78rem;text-transform:uppercase;letter-spacing:.04em;color:var(--text-2)}
.acct-scroll{overflow-x:auto}
.acct-links{display:flex;gap:6px;flex-wrap:wrap}
.acct-cls{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:50%;
font-weight:700;border:2px solid currentColor}
.acct-tag{display:inline-block;font-size:.78rem;padding:2px 8px;border-radius:999px;
border:1px solid var(--border);margin:2px 4px 2px 0;color:var(--text-2)}
.acct-sec{margin-top:40px}
.acct-sec h2{margin:0 0 10px}
.acct-card h3{margin:0 0 14px}
.acct-box{display:flex;flex-wrap:wrap;gap:10px 16px;align-items:center;
border:1px solid var(--border);border-radius:14px;padding:12px 16px;margin:14px 0;
font-size:.92rem;background:var(--surface-2)}
.acct-box form{margin:0}
.acct-box .btn{margin:0}
@media (max-width:760px){.acct-grid{grid-template-columns:1fr}
.acct-kpis{gap:8px;grid-template-columns:repeat(2,minmax(0,1fr))}
.acct-gift.is-on{grid-column:1/-1}.acct-gift b{font-size:1.15rem}
.acct-gate .btn{width:100%;justify-content:center}
.acct-kpi{padding:12px}.acct-kpi b{font-size:1.5rem}.acct-kpi span{display:block;font-size:.76rem;
line-height:1.35}.acct-form{padding:20px}}
@media (max-width:620px){.acct-reports thead{display:none}
.paper table.acct-reports{border:0;background:none;box-shadow:none;overflow:visible}
.acct-reports,.acct-reports tbody{display:block}
.acct-reports tr{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:8px 12px;
align-items:center;padding:14px 16px;margin:0 0 8px;border:1px solid var(--border);
border-radius:14px;background:#fff}
.acct-reports td{padding:0;border:0}
.acct-reports td:nth-child(2){grid-row:1;grid-column:1}
.acct-reports td:nth-child(1){grid-row:1;grid-column:2;font-variant-numeric:tabular-nums}
.acct-reports td:nth-child(5){grid-row:1;grid-column:3}
.acct-reports td:nth-child(3),.acct-reports td:nth-child(4){grid-column:1/-1}
.acct-reports td:nth-child(4){color:var(--text-2);font-size:.88rem}
.acct-reports.pick tr{grid-template-columns:auto auto minmax(0,1fr) auto}
.acct-reports.pick td:nth-child(1){grid-row:1;grid-column:1}
.acct-reports.pick td:nth-child(3){grid-row:1;grid-column:2}
.acct-reports.pick td:nth-child(2){grid-row:1;grid-column:3}
.acct-reports.pick td:nth-child(6){grid-row:1;grid-column:4}
.acct-reports.pick td:nth-child(4),.acct-reports.pick td:nth-child(5){grid-row:auto;
grid-column:1/-1}
.acct-reports.pick td:nth-child(4){color:inherit;font-size:inherit}
.acct-reports.pick td:nth-child(5){color:var(--text-2);font-size:.88rem}}
"""


def _locale(locale: str) -> str:
    return locale if locale in COPY else "es"


def path(kind: str, locale: str) -> str:
    return PATHS[_locale(locale)][kind]


def _hidden(name: str, value: str) -> str:
    return f"<input type='hidden' name='{name}' value='{_e(value)}'>"


def _shell(locale: str, title: str, lead: str, body: str, *, switch: str) -> str:
    content = (
        _page_hero(COPY[locale]["eyebrow"], title, lead)
        + f"<div class='paper page-main'><div class='wrap'><style>{ACCOUNT_CSS}</style>"
        + body
        + "</div></div>"
    )
    # Customer text (an e-mail, a description) is passed through ``_safe_text``
    # before it gets here; the guard is the last check, as on other pages.
    return guard_page(_page(title, locale, content, switch_href=switch, solid_nav=True))


def _alert(copy: dict[str, str], error: str = "", flash: str = "") -> str:
    out = ""
    if flash and flash in copy:
        out += f"<div class='flash' role='status'>{_e(copy[flash])}</div>"
    if error and error in copy:
        out += f"<div class='error' role='alert'>{_e(copy[error])}</div>"
    return out


def _benefits(copy: dict[str, str]) -> str:
    items = "".join(
        f"<li>{icon('check')}<span>{_e(item)}</span></li>" for item in copy["benefits"].split("|")
    )
    return f"<div class='acct-card acct-perks'><ul class='acct-list'>{items}</ul></div>"


def _stores(copy: dict[str, str], retention_days: int) -> str:
    """What the account keeps and how to delete it, in plain words."""
    items = "".join(
        f"<li>{icon('check')}<span>{_e(item)}</span></li>"
        for item in copy["stores"].format(days=retention_days).split("|")
    )
    return (
        f"<div class='acct-card acct-stores'><h3>{_e(copy['stores_title'])}</h3>"
        f"<ul class='acct-list'>{items}</ul></div>"
    )


def _email_field(copy: dict[str, str], email: str) -> str:
    return _field(
        copy["email"],
        f"<input type='email' name='email' required maxlength='254' autocomplete='email' "
        f"value='{_e(_safe_text(email))}'>",
    )


def _q(next_path: str) -> str:
    """A ``next`` path as a query value: ``#`` and ``&`` must not end the link."""
    from urllib.parse import quote

    return quote(next_path, safe="/")


def _switch(kind: str, locale: str, next_path: str = "") -> str:
    other = "en" if locale == "es" else "es"
    query = f"?next={_e(_q(next_path))}" if next_path else ""
    return path(kind, other) + query


def signup_page(
    *,
    locale: str,
    csrf: str,
    error: str = "",
    email: str = "",
    next_path: str = "",
    retention_days: int = 30,
) -> str:
    locale = _locale(locale)
    copy = COPY[locale]
    from quant_trade.audit.legal import legal_url

    signin = path("signin", locale) + (f"?next={_e(_q(next_path))}" if next_path else "")
    form = (
        _alert(copy, error)
        + f"<form method='post' action='{path('signup', locale)}'>"
        + _hidden("csrf", csrf)
        + _hidden("next", next_path)
        + _email_field(copy, email)
        + _field(
            copy["password"],
            f"<input type='password' name='password' required minlength='{MIN_PASSWORD_CHARS}' "
            "maxlength='256' autocomplete='new-password'>",
            copy["password_help"],
        )
        + "<p class='muted acct-terms'>"
        + _e(copy["terms_agree"]).format(
            terms=f"<a href='{_e(legal_url('terms', locale))}'>{_e(copy['terms_link'])}</a>",
            privacy=f"<a href='{_e(legal_url('privacy', locale))}'>{_e(copy['privacy_link'])}</a>",
        )
        + "</p>"
        + f"<button class='btn btn-primary btn-lg' type='submit'>{_e(copy['signup_button'])}"
        "</button></form>" + f"<p class='acct-alt'>{_e(copy['have_account'])} "
        f"<a href='{_e(signin)}'>{_e(copy['signin_link'])}</a></p>"
    )
    body = (
        f"<div class='acct-grid'><div class='acct-form'>{form}</div>"
        f"<div class='acct-side'>{_benefits(copy)}{_stores(copy, retention_days)}</div></div>"
    )
    return _shell(
        locale,
        copy["signup_title"],
        copy["signup_lead"],
        body,
        switch=_switch("signup", locale, next_path),
    )


def signin_page(
    *,
    locale: str,
    csrf: str,
    error: str = "",
    flash: str = "",
    email: str = "",
    next_path: str = "",
) -> str:
    locale = _locale(locale)
    copy = COPY[locale]
    signup = path("signup", locale) + (f"?next={_e(_q(next_path))}" if next_path else "")
    form = (
        _alert(copy, error, flash)
        + f"<form method='post' action='{path('signin', locale)}'>"
        + _hidden("csrf", csrf)
        + _hidden("next", next_path)
        + _email_field(copy, email)
        + _field(
            copy["password"],
            "<input type='password' name='password' required maxlength='256' "
            "autocomplete='current-password'>",
        )
        + f"<button class='btn btn-primary btn-lg' type='submit'>{_e(copy['signin_button'])}"
        "</button></form>"
        + f"<p class='acct-alt'><a href='{path('forgot', locale)}'>{_e(copy['forgot_link'])}"
        "</a></p>" + f"<p class='acct-alt'>{_e(copy['no_account'])} "
        f"<a href='{_e(signup)}'>{_e(copy['signup_link'])}</a></p>"
    )
    body = f"<div class='acct-grid'><div class='acct-form'>{form}</div>{_benefits(copy)}</div>"
    return _shell(
        locale,
        copy["signin_title"],
        copy["signin_lead"],
        body,
        switch=_switch("signin", locale, next_path),
    )


def forgot_page(*, locale: str, contact_url: str) -> str:
    locale = _locale(locale)
    copy = COPY[locale]
    button = ""
    if contact_url:
        from quant_trade.audit.report import _prefilled

        href = _prefilled(contact_url, copy["forgot_message"])
        button = (
            f"<p><a class='btn btn-primary btn-lg' href='{_e(href)}' rel='noopener noreferrer' "
            f"target='_blank'>{icon('chat')}{_e(copy['forgot_contact'])}</a></p>"
        )
    body = (
        "<div class='wrap-narrow'>"
        + button
        + f"<p class='acct-alt'><a href='{path('signin', locale)}'>{_e(copy['signin_link'])}</a>"
        "</p></div>"
    )
    return _shell(
        locale,
        copy["forgot_title"],
        copy["forgot_lead"],
        body,
        switch=_switch("forgot", locale),
    )


def compare_mine_note(locale: str) -> str:
    """Above the paste-links form, for a signed-in visitor: their own list is quicker."""
    locale = _locale(locale)
    copy = COPY[locale]
    return (
        "<div class='cmp-mine'><p>"
        f"{_e(copy['compare_mine'])} <a class='btn btn-dark btn-sm' "
        f"href='{path('account', locale)}#informes'>{_e(copy['compare_mine_button'])}</a>"
        "</p></div>"
    )


def gate_page(*, locale: str, reason: str, limit: int) -> str:
    """Why an upload did not run: no account, a bad code, or the month's free previews used.

    ``reason`` is ``signin``, ``code``, ``quota`` or ``network``.
    """
    locale = _locale(locale)
    copy = COPY[locale]
    reason = reason if reason in ("signin", "code", "quota", "network") else "signin"
    home = "/en" if locale == "en" else "/"
    if reason in ("signin", "code"):
        # After signing up or in, back to the upload form: the file was not kept.
        back = "?next=" + _e(_q(home + "#subir"))
        buttons = (
            f"<a class='btn btn-primary btn-lg' href='{path('signup', locale)}{back}'>"
            f"{_e(copy['gate_signup'])}</a>"
            f"<a class='btn btn-ghost btn-lg' href='{path('signin', locale)}{back}'>"
            f"{_e(copy['gate_signin'])}</a>"
        )
    else:
        buttons = (
            f"<a class='btn btn-primary btn-lg' href='{path('account', locale)}'>"
            f"{_e(copy['gate_buy'])}</a>"
            f"<a class='btn btn-ghost btn-lg' href='{home}'>{_e(copy['gate_back'])}</a>"
        )
    body = (
        "<div class='wrap-narrow'><div class='acct-card acct-gate'>"
        f"<div class='inline-form'>{buttons}</div></div></div>"
    )
    return _shell(
        locale,
        copy[f"gate_{reason}_title"].format(limit=limit),
        copy[f"gate_{reason}_lead"].format(limit=limit),
        body,
        switch=path("signup", "en" if locale == "es" else "es"),
    )


def reset_page(*, locale: str, csrf: str, token: str, error: str = "", valid: bool = True) -> str:
    locale = _locale(locale)
    copy = COPY[locale]
    if not valid:
        body = (
            "<div class='wrap-narrow'>"
            + _alert(copy, "reset_bad")
            + f"<p><a class='btn btn-dark' href='{path('forgot', locale)}'>"
            f"{_e(copy['forgot_link'])}</a></p></div>"
        )
    else:
        body = (
            "<div class='wrap-narrow'>"
            + _alert(copy, error)
            + f"<form method='post' action='{path('reset', locale)}'>"
            + _hidden("csrf", csrf)
            + _hidden("token", token)
            + _field(
                copy["password_new"],
                f"<input type='password' name='password' required "
                f"minlength='{MIN_PASSWORD_CHARS}' maxlength='256' autocomplete='new-password'>",
                copy["password_help"],
            )
            + f"<button class='btn btn-primary btn-lg' type='submit'>{_e(copy['reset_button'])}"
            "</button></form></div>"
        )
    return _shell(
        locale, copy["reset_title"], copy["reset_lead"], body, switch=_switch("reset", locale)
    )


def _date(stamp: str | None) -> str:
    return (stamp or "")[:10]


def _class_badge(overall: str) -> str:
    colour = CLASS_COLOURS.get(overall, "#64748b")
    return f"<span class='acct-cls' style='color:{colour}'>{_e(overall)}</span>"


def report_href(audit_id: str, locale: str) -> str:
    return f"/audits/{audit_id}?lang={locale}"


def _usd(cents: int) -> str:
    whole, rest = divmod(cents, 100)
    return f"USD {whole}" if rest == 0 else f"USD {whole}.{rest:02d}"


def comparable(item: AccountAudit, *, free_mode: bool = False) -> bool:
    """Whether a report on the list can go into a side-by-side comparison."""
    return not item.purged and (item.paid or free_mode)


def _reports_table(
    copy: dict[str, str],
    locale: str,
    audits: Sequence[AccountAudit],
    *,
    free_mode: bool = False,
) -> str:
    if not audits:
        return f"<p class='muted'>{_e(copy['reports_none'])}</p>"
    pickable = sum(1 for item in audits if comparable(item, free_mode=free_mode)) >= 2
    head = "".join(
        f"<th>{_e(copy[k])}</th>" for k in ("col_date", "col_class", "col_status", "col_what")
    )
    rows = []
    for item in audits:
        tags = []
        if item.purged:
            tags.append(copy["status_purged"])
        elif item.paid:
            method = copy.get(f"paid_{item.paid_with}", copy["paid_code"])
            tags.append(f"{copy['status_full']} · {method}")
        else:
            tags.append(copy["status_preview"])
        if item.published:
            tags.append(copy["status_published"])
        if not item.own:
            tags.append(copy["status_saved"])
        status = "".join(f"<span class='acct-tag'>{_e(t)}</span>" for t in tags)
        # The description is the customer's text: wording the guard refuses is withheld.
        what = _safe_text(item.description) if item.description else copy["no_description"]
        links = []
        if not item.purged:
            links.append((report_href(item.audit_id, locale), copy["open"]))
        if comparable(item, free_mode=free_mode):
            links.append((f"/audits/{item.audit_id}/pdf?lang={locale}", copy["pdf"]))
        if item.public_id:
            links.append((f"/v/{item.public_id}?lang={locale}", copy["public_page"]))
        opener = (
            "<div class='acct-links'>"
            + "".join(
                f"<a class='btn btn-ghost btn-sm' href='{_e(href)}'>{_e(label)}</a>"
                for href, label in links
            )
            + "</div>"
            if links
            else ""
        )
        pick = ""
        if pickable:
            pick = "<td>"
            if comparable(item, free_mode=free_mode):
                pick += (
                    f"<input type='checkbox' name='id' value='{_e(item.audit_id)}' "
                    f"aria-label='{_e(copy['compare_pick_label'])}'>"
                )
            pick += "</td>"
        rows.append(
            f"<tr>{pick}<td>{_e(_date(item.created_at))}</td>"
            f"<td>{_class_badge(item.overall_class)}</td>"
            f"<td>{status}</td>"
            f"<td>{_e(what)}</td>"
            f"<td>{opener}</td></tr>"
        )
    pick_head = "<th></th>" if pickable else ""
    table = (
        "<div class='acct-scroll'><table class='acct-table acct-reports"
        + (" pick" if pickable else "")
        + "'><thead>"
        f"<tr>{pick_head}{head}<th></th></tr>"
        f"</thead><tbody>{''.join(rows)}</tbody></table></div>"
    )
    if not pickable:
        return table
    return (
        f"<form method='get' action='{path('account', locale)}/comparar'>"
        f"<p class='muted'>{_e(copy['compare_help'])}</p>"
        + table
        + f"<p><button class='btn btn-dark' type='submit'>{_e(copy['compare_button'])}"
        "</button></p></form>"
    )


def _codes_table(copy: dict[str, str], codes: Sequence[AccountCode], now: str) -> str:
    if not codes:
        return f"<p class='muted'>{_e(copy['codes_none'])}</p>"
    head = "".join(
        f"<th>{_e(copy[k])}</th>"
        for k in ("col_code", "col_added", "col_left", "col_used", "col_expires")
    )
    rows = []
    for item in codes:
        record = item.code
        state = ""
        if record.disabled:
            state = copy["code_off"]
        elif record.expires_at is not None and record.expires_at <= now:
            state = copy["code_expired"]
        elif record.credits_left == 0:
            state = copy["code_empty"]
        left = str(record.credits_left) + (
            f" <span class='acct-tag'>{_e(state)}</span>" if state else ""
        )
        rows.append(
            f"<tr><td>{_e(copy['code_ref'])} {_e(record.id)}</td>"
            f"<td>{_e(_date(item.linked_at))}</td><td>{left}</td>"
            f"<td>{record.credits_used}/{record.credits_total}</td>"
            f"<td>{_e(_date(record.expires_at) or copy['never'])}</td></tr>"
        )
    return (
        f"<div class='acct-scroll'><table class='acct-table'><thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _purchases_table(copy: dict[str, str], locale: str, audits: Sequence[AccountAudit]) -> str:
    paid = sorted((a for a in audits if a.paid), key=lambda a: a.paid_at or "", reverse=True)
    if not paid:
        return f"<p class='muted'>{_e(copy['purchases_none'])}</p>"
    head = "".join(
        f"<th>{_e(copy[k])}</th>" for k in ("col_paid", "col_report", "col_method", "col_class")
    )
    rows = [
        f"<tr><td>{_e(_date(a.paid_at))}</td>"
        f"<td><code title='{_e(a.audit_id)}'>{_e(a.audit_id[:8])}</code></td>"
        f"<td>{_e(copy.get(f'paid_{a.paid_with}', copy['paid_code']))}</td>"
        f"<td>{_class_badge(a.overall_class)}</td><td>"
        + (
            ""
            if a.purged
            else f"<a href='{_e(report_href(a.audit_id, locale))}'>{_e(copy['open'])}</a>"
        )
        + "</td></tr>"
        for a in paid
    ]
    return (
        f"<div class='acct-scroll'><table class='acct-table'><thead><tr>{head}<th></th></tr>"
        f"</thead><tbody>{''.join(rows)}</tbody></table></div>"
    )


def account_page(
    *,
    locale: str,
    account: AccountRecord,
    audits: Sequence[AccountAudit],
    codes: Sequence[AccountCode],
    credits: int,
    csrf: str,
    now: str,
    flash: str = "",
    error: str = "",
    access_codes: bool = False,
    card_payments: bool = False,
    contact_url: str = "",
    free_mode: bool = False,
    price_cents: int = 0,
    pack_price_cents: int = 0,
    free_left: int = 0,
    free_limit: int = 0,
    welcome: str = "",
    retention_days: int = 30,
) -> str:
    """ "My reports": the reports, credits, codes and purchases of one account."""
    locale = _locale(locale)
    copy = COPY[locale]
    home = "/en" if locale == "en" else "/"
    signout = (
        f"<form method='post' action='{path('signout', locale)}'>{_hidden('csrf', csrf)}"
        f"<button class='btn btn-ghost btn-sm' type='submit'>{_e(copy['signout_button'])}"
        "</button></form>"
    )
    header = (
        "<div class='acct-head'>"
        f"<p class='muted'>{_e(copy['signed_in_as'])} <b>{_e(_safe_text(account.email))}</b></p>"
        f"<div class='inline-form'><a class='btn btn-primary' href='{home}#subir'>"
        f"{_e(copy['new_audit'] if audits else copy['first_audit'])}</a>{signout}</div></div>"
    )
    free_value = copy["free_left_value"].format(left=free_left, limit=free_limit)
    # The free first report leads while it is unused: it is what a new account came for.
    gift = (
        f"<div class='acct-kpi acct-gift{' is-on' if welcome == 'available' else ''}'>"
        f"<b>{_e(copy['welcome_' + welcome])}</b>"
        f"<span>{_e(copy['welcome_kpi'])}</span></div>"
        if welcome in ("available", "used")
        else ""
    )
    kpis = (
        "<div class='acct-kpis'>"
        + (gift if welcome == "available" else "")
        + (
            f"<div class='acct-kpi'><b>{_e(free_value)}</b>"
            f"<span>{_e(copy['free_left'])}</span></div>"
            if free_limit
            else ""
        )
        + f"<div class='acct-kpi'><b>{credits}</b><span>{_e(copy['credits'])}. "
        f"{_e(copy['credits_help'])}</span></div>"
        + (gift if welcome != "available" else "")
        + f"<div class='acct-kpi'><b>{len(audits)}</b><span>{_e(copy['reports'])}</span></div>"
        f"<div class='acct-kpi'><b>{sum(1 for a in audits if a.paid)}</b>"
        f"<span>{_e(copy['paid_reports'])}</span></div></div>"
    )
    reports = (
        f"<section class='acct-sec' id='informes'><h2>{_e(copy['reports_title'])}</h2>"
        + _reports_table(copy, locale, audits, free_mode=free_mode)
        + "</section>"
    )
    codes_html = ""
    if access_codes or codes:
        add = ""
        if access_codes:
            add = (
                f"<form method='post' action='{path('account', locale)}/codigo'>"
                + _hidden("csrf", csrf)
                + f"<label for='acct-code'>{_e(copy['code_label'])}</label>"
                "<div class='inline-form'><input id='acct-code' type='text' name='code' required "
                "maxlength='40' autocomplete='off' spellcheck='false' "
                "placeholder='AUD-XXXX-XXXX-XXXX'>"
                f"<button class='btn btn-dark' type='submit'>{_e(copy['code_add'])}</button>"
                "</div></form>"
            )
        codes_html = (
            f"<section class='acct-sec'><h2>{_e(copy['codes_title'])}</h2>"
            f"<p class='muted'>{_e(copy['codes_help'])}</p>"
            + _codes_table(copy, codes, now)
            + add
            + "</section>"
        )
    buy = ""
    if (access_codes and contact_url) or card_payments:
        lines = ""
        if price_cents > 0:
            prices = copy["buy_prices_single"].format(price=_usd(price_cents))
            if pack_price_cents > 0:
                prices += " " + copy["buy_prices_pack"].format(price=_usd(pack_price_cents))
            lines += f"<p>{_e(prices)}</p>"
        if access_codes and contact_url:
            from quant_trade.audit.report import _prefilled

            href = _prefilled(contact_url, copy["buy_message"])
            lines += (
                f"<p><a class='btn btn-dark' href='{_e(href)}' rel='noopener noreferrer' "
                f"target='_blank'>{icon('chat')}{_e(copy['buy_code'])}</a></p>"
                "<ol class='buy-steps'>"
                + "".join(f"<li>{_e(step)}</li>" for step in copy["buy_code_how"].split("|"))
                + f"</ol><p class='muted'>{_e(copy['buy_code_wait'])}</p>"
            )
        if card_payments:
            lines += f"<p class='muted'>{_e(copy['buy_card'])}</p>"
        buy = f"<section class='acct-sec'><h2>{_e(copy['buy_title'])}</h2>{lines}</section>"
    purchases = (
        f"<section class='acct-sec'><h2>{_e(copy['purchases_title'])}</h2>"
        + _purchases_table(copy, locale, audits)
        + "</section>"
    )
    security = (
        f"<section class='acct-sec'><h2>{_e(copy['security_title'])}</h2>"
        "<div class='acct-grid'>"
        f"<form class='acct-card' method='post' action='{path('account', locale)}/contrasena'>"
        f"<h3>{_e(copy['change_password'])}</h3>"
        + _hidden("csrf", csrf)
        + _field(
            copy["password_current"],
            "<input type='password' name='current' required maxlength='256' "
            "autocomplete='current-password'>",
        )
        + _field(
            copy["password_new"],
            f"<input type='password' name='password' required minlength='{MIN_PASSWORD_CHARS}' "
            "maxlength='256' autocomplete='new-password'>",
            copy["password_help"],
        )
        + f"<button class='btn btn-dark' type='submit'>{_e(copy['change_password'])}</button>"
        "</form>"
        "<form class='acct-card acct-danger' method='post' "
        f"action='{path('account', locale)}/borrar'>"
        f"<h3>{_e(copy['delete_title'])}</h3><p class='muted'>{_e(copy['delete_help'])}</p>"
        + _hidden("csrf", csrf)
        + _field(
            copy["password_current"],
            "<input type='password' name='current' required maxlength='256' "
            "autocomplete='current-password'>",
        )
        + "<label class='check'><input type='checkbox' name='with_reports' value='yes'> "
        f"<span>{_e(copy['delete_reports'])}</span></label>"
        f"<p><button class='btn btn-ghost' type='submit'>{_e(copy['delete_button'])}</button></p>"
        "</form></div>" + _stores(copy, retention_days) + "</section>"
    )
    body = (
        _alert(copy, error, flash)
        + header
        + kpis
        # Without credits, how to get more comes before the list.
        + (buy if credits == 0 else "")
        + reports
        + codes_html
        + (buy if credits > 0 else "")
        + purchases
        + security
    )
    return _shell(
        locale,
        copy["account_title"],
        copy["account_lead"],
        body,
        switch=path("account", "en" if locale == "es" else "es"),
    )


def report_box(
    *,
    locale: str,
    state: str,
    audit_id: str,
    query: str,
    csrf: str = "",
    credits: int = 0,
    locked: bool = False,
    next_path: str = "",
) -> str:
    """The account line on a report page.

    ``state`` is ``anon`` (signed out), ``mine`` (on this account),
    ``unsaved`` (signed in, not on any account) or ``other`` (on another
    account). ``query`` is the report's own query string (token and language)
    for the forms; ``credits`` offers the one-click unlock when ``locked``.
    """
    locale = _locale(locale)
    copy = COPY[locale]
    base = f"/audits/{audit_id}"
    parts: list[str] = []
    if state == "anon":
        suffix = f"?next={_e(_q(next_path))}" if next_path else ""
        parts.append(
            f"<span>{_e(copy['anon_box'])}</span>"
            f"<a class='btn btn-dark btn-sm' href='{path('signup', locale)}{suffix}'>"
            f"{_e(copy['anon_signup'])}</a>"
            f"<a href='{path('signin', locale)}{suffix}'>{_e(copy['anon_signin'])}</a>"
        )
    elif state == "mine":
        parts.append(
            f"<span>{icon('check')} {_e(copy['saved_box'])}</span>"
            f"<a href='{path('account', locale)}'>{_e(copy['saved_link'])}</a>"
        )
    elif state == "unsaved":
        parts.append(
            f"<span>{_e(copy['save_box'])}</span>"
            f"<form method='post' action='{_e(base)}/save{_e(query)}'>{_hidden('csrf', csrf)}"
            f"<button class='btn btn-dark btn-sm' type='submit'>{_e(copy['save_button'])}"
            "</button></form>"
        )
    elif state == "other":
        return ""
    box = f"<div class='acct-box no-print'><style>{ACCOUNT_CSS}</style>{''.join(parts)}</div>"
    if locked and state in ("mine", "unsaved") and credits > 0:
        left = copy["credit_left_one"] if credits == 1 else copy["credit_left"].format(n=credits)
        box += (
            "<div class='acct-box no-print'>"
            f"<form method='post' action='{_e(base)}/credit{_e(query)}'>{_hidden('csrf', csrf)}"
            f"<button class='btn btn-primary' type='submit'>{icon('key')}"
            f"{_e(copy['credit_button'])}</button></form><span class='muted'>{_e(left)}</span>"
            "</div>"
        )
    return box


def all_texts() -> list[str]:
    """Every sentence the account pages can show, for the guard test."""
    return [text for copy in COPY.values() for text in copy.values()]


__all__ = [
    "ACCOUNT_CSS",
    "COPY",
    "PATHS",
    "account_page",
    "comparable",
    "all_texts",
    "forgot_page",
    "gate_page",
    "path",
    "report_box",
    "report_href",
    "reset_page",
    "signin_page",
    "signup_page",
]
