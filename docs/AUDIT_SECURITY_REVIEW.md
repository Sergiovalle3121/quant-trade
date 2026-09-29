# Backtest audit: security and robustness review

Reviewed on 2026-09-24 against `main` at 6df1d16, before the public launch on
Railway. Scope: the web service (`audit/web.py`), the importers
(`audit/importers.py`), the CSV readers (`audit/schema.py`), the engine's
resampling (`audit/engine.py`), the store (`audit/store.py`) and the
`serve` command. The question was how someone could hurt the service, or
another customer, with an upload, a link or a form, and what an unlucky
customer with a strange file sees.

Every change below has an offline, deterministic test in
`tests/test_audit_security.py`.

## What was changed

| # | Finding | Severity | Fix |
|---|---|---|---|
| 1 | A 5 MB CSV whose one line held millions of fields kept pandas inferring columns for many minutes (time grows with the square of the field count). Ten such uploads would stop the service. | High | Any CSV line over 32 KB (`MAX_CSV_LINE_BYTES`) is refused before pandas reads it, with a message in both languages. 500 variant names fit in under 15 KB. |
| 2 | The bootstrap drew `samples x returns` cells at once: a legal 190,000-row hourly curve took 38 s and about 1.5 GB of memory. A few at once would exhaust a Railway instance. | High | The bootstrap is capped at 10 million cells (`BOOTSTRAP_MAX_CELLS`), never below 50 samples; `samples` and `samples_requested` are both in the report. The same 190,000-row file now takes a few seconds. The resampled-risk module already had such a cap. |
| 3 | Nothing bounded how many audits ran at once: each upload took a thread-pool worker (up to 40) with its own memory. | High | At most `AUDIT_MAX_CONCURRENT_AUDITS` (2) are parsed and audited at once. Others wait up to `AUDIT_QUEUE_SECONDS` (30) without holding a thread, so the pages that share the thread pool keep answering, then get a 503 "busy, try again in a minute" page in their language. |
| 4 | Starlette writes every multipart file to a temporary file before the route runs, so the per-file limit came after an arbitrarily large body had been written to disk. | High | An ASGI middleware refuses a body over six files' worth plus 1 MiB: at once when `Content-Length` says so, or as soon as a chunked body passes the limit. The customer gets a 413 page in their language. |
| 5 | The upload rate limit counted only stored audits, so uploads that failed to parse (a zip bomb, a malformed file) could be repeated without end, each costing CPU. The waitlist had no limit at all. | Medium | Every upload attempt counts; after three times the hourly upload limit per address the service answers 429. Waitlist sign-ups are limited to 5 per hour per address. The in-memory attempt tables forget addresses whose attempts expired, so they cannot grow without bound. |
| 6 | A workbook member whose stored size is a lie (it inflates past its declared size) raised `BadZipFile` from the CRC check, which reached the customer as a bare English "Internal Server Error". | Medium | Damaged, encrypted or size-lying members are a `ReportFormatError` ("the workbook is damaged or encrypted"), in both languages. The declared-size check already bounded how much is inflated. |
| 7 | A delimited report with an unbalanced quote raised `csv.Error` (field larger than the limit), which is not a `ValueError`: another bare 500. | Medium | Refused as a `ReportFormatError` ("could not be read as a delimited list of trades"). |
| 8 | Any exception the importers or the engine did not anticipate became Starlette's plain-text English 500. | Medium | An importer crash is the "check the file format" message (400); an engine or storage failure is a localised "something failed on our side, nothing new was saved" page (500). A last-resort handler does the same for any route. The traceback goes to the server log with the path only, never the query string, and never to the customer. |
| 9 | XML with a document type was refused only when `<!DOCTYPE` or `<!ENTITY` appeared as ASCII bytes. An XLSX member in UTF-16 has a NUL after every byte and passed that check, so internal entities reached expat. Expat 2.6 limits entity amplification and ElementTree never fetches external entities, so this was defence in depth, not an open hole. | Low | A first streaming pass with bare expat stops at any DOCTYPE or ENTITY declaration in any encoding, before an entity can be expanded. |
| 10 | uvicorn's access log wrote every report URL with its `?token=`: anyone who can read the Railway logs could open every customer's report. It also wrote every full client IP. | High | `audit serve` runs uvicorn with a log filter that replaces the value of `token=` and `code=` with `[redacted]` and shortens the client address (`shorten_client_address`: IPv4 /24, IPv6 /48), and without the `Server` header. |
| 11 | No Content Security Policy and no framing protection: the publish and redeem buttons could be clickjacked from another site. | Medium | Every response, errors and the 413 included, carries `Content-Security-Policy` (`default-src 'none'`; script only as the print button's `window.print()` handler, allowed by its hash; inline styles; images from the site; forms to the site or Stripe Checkout; `frame-ancestors 'none'`; `base-uri 'none'`), `X-Frame-Options: DENY`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`, `nosniff` and `no-referrer`. HSTS is added when `AUDIT_BASE_URL` is `https`. |
| 12 | While `AUDIT_BASE_URL` is unset, canonical, Open Graph, badge-snippet, `robots.txt` and `sitemap.xml` links are built from the `Host` header, which the client chooses. The values were escaped, but a forged host would be echoed into a cacheable `/v/` page. | Low | A `Host` that is not a plain host name (letters, digits, dots, dashes, optional port) drops the absolute links instead of echoing it. Setting `AUDIT_BASE_URL` removes the dependency on `Host` entirely. |

## What was checked and found sound

- **Escaping.** Every page is built with `html.escape` on each dynamic value
  (`pages.py`, `report.py`, `charts.py`, `seo.py`). A test uploads an MT5
  report whose expert name, symbol and file name, and a description, carry
  script tags and event handlers, then parses the report (both languages),
  the verification page and the badge: no script tag other than the site's
  own `/static/app.js` (same origin, no inline code; added with the 2026-09-24
  redesign, and every page works without it) and no event-handler attribute
  other than the print button. Fonts are self-hosted (`font-src 'self'`), so
  no visitor request reaches a font service. Query values shown on pages
  (`code=`, `error=`, `lang=`) are matched against fixed values, never echoed.
- **Owner tokens.** 32 random bytes from `secrets` (43 URL-safe characters),
  stored only as SHA-256, compared with `hmac.compare_digest`. A wrong token
  and an unknown id are the same 404. The token is sent to no page but the
  owner's report and is kept out of the verification page, the badge and
  Open Graph tags. `Referrer-Policy: no-referrer` keeps it out of `Referer`.
  It does travel to Stripe inside the Checkout success URL, which is how the
  customer returns to the report.
- **Access codes.** About 59 bits from `secrets.choice`, stored only as
  SHA-256, printed once. Redemption is one conditional `UPDATE` inside the
  transaction that marks the audit paid, so a credit cannot be spent twice
  (covered by an existing concurrency test). Redeem attempts share the hourly
  per-address limit with uploads, which puts guessing a code far out of
  reach. A rejected code is never echoed.
- **Rate limits behind Railway.** `X-Forwarded-For` is ignored unless
  `AUDIT_TRUSTED_PROXY_HOPS` is set, and then the N-th entry from the right
  is used, so a forged header cannot pick the counted address.
- **Upload limits.** 5 MB per file; 200,000 equity rows, 50,000 trades, 500
  variants; XLSX at most 500 members and 40 MB declared uncompressed. With
  the fixes above, the slowest legal files measured were: a 190,000-row
  hourly curve (a few seconds), a 4.8 MB MT5 report of 6,000 trading days
  (about 8 s), a 4.9 MB optimisation export of 17,000 passes (about 1 s).
  Twelve pathological 5 MB shapes (unclosed cells, deep nesting, one huge
  cell, a comment that never ends, thousands of attributes, unbalanced
  quotes) are each refused within about 6 s.
- **Stripe webhook.** Signature checked locally with a timestamp tolerance
  before the payload is parsed; the body is bounded by the same request
  limit.
- **Stack traces.** FastAPI's docs and OpenAPI routes are off, `debug` is
  off, and every error path now renders a localised page.

## Limits that remain

- PDF statements are parsed by pdfplumber (pdfminer.six and pypdfium2) in a
  child process (`python -m quant_trade.audit.pdf_tables`, no shell, only
  `PATH` and `PYTHONPATH` in its environment) killed after 10 s, with its
  address space capped at 1 GB and its CPU at 10 s; only its JSON answer is
  read back. At most 30 pages, 20,000 characters per page and 200,000 table
  cells in all (a dense empty grid costs no characters), and the child's
  answer is read only up to 8 MB; any failure is the plain `pdf_statement`
  refusal.
- Old Excel workbooks (.xls) are parsed by xlrd 2.x, a third-party parser of
  a binary format. It is opened from memory with no formatting and each sheet
  on demand. Any exception it raises becomes the plain `legacy_xls` refusal.
  Its time is bounded by the 10 MB report limit and the 5,000,000-cell cap,
  not by a timeout.

- The attempt tables and the audit slots are per process. Railway runs one
  replica; with several, each would count separately.
- An audit that has started cannot be interrupted: Python cannot stop a
  thread. The time bound comes from the input limits and the capped
  resampling, measured above, not from a timeout.
- The service's own access log keeps only a shortened client address (IPv4
  /24, IPv6 /48) and the path with the token redacted. Railway keeps its own
  request logs, with full addresses, under its own retention; `/privacidad`
  and `/privacy` say so. Rate limiting still uses full addresses, in memory
  and in the audit row that the retention purge clears.
- A person with the report link has the report: the token is the only key,
  by design, so customers should share the `/v/` page instead.
- Customer accounts (PR #205, reviewed by the bug hunt on SQLite and
  PostgreSQL 16): sign-up answers 409 when an e-mail already has an account,
  so an address's registration can be learnt (5 sign-ups per hour per
  address). Without e-mail verification this is the accepted trade-off; it
  goes away once confirmation by e-mail exists. Fixed in the same review: a
  report saved or paid for from someone else's link is only unlinked when
  that account is deleted, never deleted (only reports the account uploaded
  are); the customer's description is withheld on `/cuenta` when the guard
  refuses it; failed sign-ins are limited per (address, e-mail) pair with
  higher per-address and per-e-mail ceilings, so nobody can lock the real
  owner out from elsewhere.
- Live abuse pass on accounts (bug hunt, two throwaway accounts, deleted
  afterwards): cookie flags, a new session at each sign-in, sign-out ending
  the server session, cross-account 404s and equal sign-in answers all held.
  Fixed after it: the sign-up and account-action limits let one attempt past
  the stated number; the per-e-mail ceiling on failed sign-ins went from 200
  to 50 an hour, because guesses spread over a pool of addresses only met
  that ceiling. Counters live in memory and restart with each deploy.
- Pre-launch sweep of the account surface (bug hunt, local): nothing high.
  Fixed after it: the per-e-mail ceiling blocked even the right password, so
  a few addresses could lock an owner out every hour; now it only stops an
  address past 2 failures on that e-mail. POST `/audits` checks
  `Sec-Fetch-Site`, else Origin or Referer, as a second layer (the domain is on
  the Public Suffix List); `Origin: null` is no signal, because our own
  no-referrer pages send it (a first version refused it and blocked every
  real upload; caught in Chromium before merge). The
  sign-in, sign-up and panel counters moved to the database (`attempts`,
  hashed keys), so deploys no longer reset them. Parked: sign-up's 409
  confirms an e-mail exists (needs e-mail verification); scrypt N=2^14.
- Owner panel path (`AUDIT_PANEL_PATH`, 2026-09-28; tests in
  `tests/test_audit_owner_panel.py`). The panel can be served at a path the
  owner chooses; the default stays `/panel`. The value is checked
  (`settings.resolve_panel_path`: starts with `/`, 2 to 64 characters from
  `A-Z a-z 0-9 / _ -`, no `//`, no trailing slash, first segment not used by
  a public route) and an invalid one falls back to `/panel` with one start-up
  warning that never prints the value; the setting is also kept out of the
  settings `repr`. Fixed with it: without a valid `AUDIT_ADMIN_KEY` the panel
  used to answer 404 with the "audit not found" page, 400 to a POST without
  the key field and 405 to other methods, which told a scanner the path was
  special; now the routes are not mounted without a key, so GET, HEAD, POST
  and every other method get the ordinary localized 404 with the same
  headers. With a custom path, `/panel` is an unknown page too. The panel
  path is never written in `robots.txt` or the sitemap; its responses carry
  `X-Robots-Tag: noindex, nofollow` and `Cache-Control: no-store`. The key
  field takes at most 256 characters (as the login form already said), and
  the access-log filter redacts `key=` as well. Unchanged: the key travels
  only in POST bodies, is compared in constant time, and five wrong keys per
  address per hour answer 429 (`attempts` table). Limits: a custom path is
  obscurity, not a second secret, and it appears in Railway's own request
  log; with a key set, the path can still be told from an unknown page: it
  answers 405 to methods other than GET, HEAD and POST, 400 to a POST
  without the key field or with a key over 256 characters, and 307 to the
  same path with a trailing slash. The check for a first segment already in
  use sees the routes mounted before the panel plus the hidden track-record
  paths; a hidden feature that brings a new first segment has to be added
  to it. The track-record panel (`/historiales` under the panel
  path) follows the same path and rules and stays off with `TRACK_SEAL_ENABLED`.
- "Mi cuenta" in four parts (2026-09-28; `tests/test_audit_account_parts.py`):
  layout only. No form, action, CSRF field, limit or redirect changed; the
  four links are plain fragment links and the bar is CSS, so the Content
  Security Policy is as before. The page's message is still one of the fixed
  texts chosen by an allow-listed `done=` or `error=` code, never echoed.
- Checkout sessions and the language switch (payments, 2026-09-28, local
  review with Stripe simulated; `tests/test_audit_checkout_language.py`).
  Before, a buyer who changed language left the first Checkout session
  payable at Stripe for up to a day next to the new one, so the same purchase
  could be paid twice. Now the session of the other language is expired at
  Stripe after the redirect to the new one. What keeps it safe: only an
  `open` order of the same report (or account) and plan is sent, never one
  that is `paid_review`, `delivered` or `duplicate`; Stripe refuses to expire
  a complete session, so a payment that won the race stays paid and its
  webhook delivers; the local order is changed only after Stripe answers
  `expired`, with a conditional update that leaves a paid order untouched,
  and it keeps its session id, so a late paid webhook still settles once
  (a second charge is a `duplicate` for manual refund review, as before).
  The call is one attempt with a 10-second timeout in a background task, so
  it cannot delay or fail the new checkout; failures are logged with the
  session id and the error class only, never the key or Stripe's message.
  No new route, form field or redirect target; the Stripe key is used for
  one more endpoint. Limits: best effort (a failed expiry leaves the old
  session open, as it was before); the no-charge card check is not covered
  (no charge, no order); two switches at the same moment can expire each
  other's session, which charges nothing. Review follow-up: because an
  expired order is not reused, alternating languages would open one new
  Stripe session per click on `POST /audits/{id}/checkout`, which has no
  request limit of its own; expiry calls are now capped at 6 per purchase
  and per account in an hour (in memory, per process), and past the cap the
  old session stays open and is reused, so the sessions one report can open
  stay bounded. An order made after the new one is never expired (a slow
  older request cannot close the newer session), and a failed expiry reads
  the session once and marks the order only when Stripe already holds it as
  `expired`, never when it is `complete`. Also fixed: the two redirects of
  `POST /audits/{id}/checkout` that wrote `token=None` when the signed-in
  owner paid without the token in the URL now write an empty token.

## Launch basics (2026-09-28)

Reviewed against `main` at 9c77197. Scope: which pages search engines may
list, the icon files, the language of error pages and the short addresses
that forward to a page. No control was
relaxed: the Content Security Policy, the other security headers, the rate
limits and the redirect from Railway's address are unchanged. Every change
has an offline, deterministic test in `tests/test_audit_launch_basics.py`.

| # | Finding | Severity | Fix |
|---|---|---|---|
| L1 | The `X-Robots-Tag` header was decided with `path.startswith(DISALLOWED_PATHS)`, so the public `/pt/contato` was caught by the account prefix `/pt/conta` and kept out of search engines, by the header and by `robots.txt`. No private page was exposed. | Low | `seo.is_private_path` matches an entry or a page below it (`/pt/conta`, `/pt/conta/...`), not a longer word. `robots.txt` keeps every `Disallow` line and adds `Allow: /pt/contato` before them. Every route was compared with every private prefix: this was the only pair, and a test keeps it so. Every account, report, webhook and health path keeps its header. |
| L2 | The comparison pages (`/comparar`, `/compare`, `/pt/comparar`) and the e-mail confirmation pages (`/confirmar-correo`, `/confirm-email`, `/pt/confirmar-email`) were private only by `<meta name="robots">`; their 200 answers had no `X-Robots-Tag`. | Low | They send `X-Robots-Tag: noindex, nofollow` (`seo.NOINDEX_PATHS`), on every status. They are left out of `robots.txt` on purpose, so a crawler that follows a link reads the header. |
| L3 | `/favicon.ico` answered 404. | Low | `/favicon.ico` and `/apple-touch-icon.png` serve two files from the static allow-list (`theme.STATIC_FILES`, `theme.ICON_PATHS`): the route takes no file name from the request (a first version took `?icon_name=` and could answer another file of the allow-list; caught in review before merge, and a test asks with that query). They carry every security header and `Cache-Control: public, max-age=604800`, the same as `/static/`; every other route stays `no-store`. The policy `img-src 'self' data:` already allowed them. A read on Railway's address is forwarded to the domain like any other. |
| L4 | An error page under an English address was in Spanish. | Low | The language comes from the first step of the path, compared with a fixed set built from the route tables (`web.ENGLISH_ROOTS`); `?lang=` still accepts only `es`, `en` or `pt`. Nothing from the request is echoed. The 413 and "busy" pages, built before routing, follow the same rule. |
| L5 | Open redirect, already on `main`: the short addresses that forward to a page (`/soporte`, `/contact`, `/support`, `/en/support`, `/pt/suporte`, `/precios`, `/pricing`, `/en/pricing`, `/pt/precos` and the legal aliases under `/en` and `/pt`) were handlers whose target was a default argument, which FastAPI reads as a query parameter. `/soporte?contact_path=https://elsewhere.example/` answered 301 to that site. | Medium | One helper (`_forward` in `web.py`) registers them with a handler that takes no parameter, so the target is the one written in the code. A test asks every kind of alias with `contact_path`, `landing_path`, `legal_path`, `target` and `next` set to another site and gets the fixed page. |

Not changed here: `/panel` is not in `robots.txt` (another change handles
the panel).

## Accounts and e-mail hardening (2026-09-28)

Reviewed against `main` at 9c77197, before the public launch. Every change
below has an offline, deterministic test in
`tests/test_audit_account_hardening.py`.

| # | Finding | Severity | Fix |
|---|---|---|---|
| A1 | Sign-up and e-mail change accepted any `x@y.z` without spaces: quotes, angle brackets, commas, malformed domains (`gmail..com`, `-gmail.com`) and IP addresses. The stored address goes into the `To` header, where `a,b@gmail.com` can read as two recipients. | Medium | New addresses must pass `accounts.simple_email` (ASCII, one `@`, name of `[A-Za-z0-9._%+-]` with no leading, trailing or doubled dot, domain of two or more labels ending in letters, 254 characters at most); the refusal is `email_simple` in the three languages. The reserved, disposable, typo and DNS checks run after it as before. Sign-in, recovery and the reset request keep `valid_email`, so an older account is never locked out. |
| A2 | "Send the link again" queued the same outbox row again: the same Message-ID and the same `Idempotency-Key`, which Resend does not deliver twice within 24 hours, so the customer probably got no second message. The row also kept its count of tries, so after eight claims a resent row stayed `queued` and was never sent. | Medium | A resend the customer asks for keeps the challenge, its link and its expiry, but starts its own tries and gets its own Message-ID and idempotency key (`mail.message_key`). Automatic retries of one message keep their key, so a retry after a lost reply is never delivered twice. The ten-minute spacing, the hourly limits and the token lifetimes are unchanged; a row left waiting by the old code, or left `sending` with its last try used and its lease expired, is sent on the next request. |
| A4 | The report's private token travelled inside `next` (double-encoded in the two-step and passkey redirects) in the links of the report's account box and in the sign-in redirects of save, credit, card check, redeem and checkout. `Referrer-Policy: no-referrer` and the log redaction covered it, but it was written into page HTML, browser history and any proxy log. | Medium | `next` names the report only. The key waits up to an hour in the cookie `rigor_report` (HttpOnly, SameSite=Lax, Secure on https), set when a signed-out visitor leaves a report through one of its forms (`POST /audits/{id}/account` for the account box) after the token was checked. After sign-in the cookie can only add `token=` to the address of that same report, which `safe_next` already accepted; its value must match `id.token` in URL-safe characters, so it cannot change the destination or inject a parameter. It is cleared at every sign-in. An older link with the key inside `next` is redirected to the clean address (sign-in, sign-up and second-step pages), and the passkey page moves it to the cookie. `POST /audits/{id}/account` refuses a post from another site (403), so another site cannot plant the cookie. |
| A5 | The choice `?extras=1` was lost for a visitor without an account: `next` was rebuilt without it and `safe_next` refused any query on the upload pages. | Low | `safe_next` accepts the three upload pages with exactly `?extras=1` (no other query, no anchor); the redirect to sign-up, the "account first" answer and the language switch of the form keep it. Every other query on those pages is still refused. |

Also changed, texts only (A3): while confirmation is required, the account
notice and the checkout refusal no longer say the free report is available
to an unconfirmed address, and the notice after sign-up says a confirmation
link was sent (only when delivery is configured). It shows on the account
page, or on the upload page or report a sign-up returns to; there only the
fixed value `welcome_confirm` is read from the query, and only a signed-in
account with an unconfirmed address sees the text.

Limits that remain from this pass:

- An account made before A1 keeps its address. If one holds a comma or a
  quote, mail to it is still composed from the stored value; the owner can
  list such accounts and ask those customers to change the address.
- The report token still appears in the report's own address and form
  actions, and in the Checkout return address sent to Stripe, as described
  above. A form rendered before this change can post the key inside `next`
  once; it works as before and the next page is clean.
- With two reports open, the cookie keeps the key of the last one a visitor
  left to sign in. Signing in from the other tab lands on that report
  without its key (a 404 for an account that does not hold it); opening the
  link again works.

## Customer audit: texts, links and labels (2026-09-28)

Reviewed against `main` at 8a536fb. Scope: wording, labels and links of the
public pages and the report in Spanish, English and Portuguese. No control was
relaxed and no header, redirect, form field, limit or setting changed. The
tests are offline and deterministic (`tests/test_audit_customer_copy.py`,
`tests/test_audit_portuguese_report.py`, `tests/test_audit_method.py`).

| # | Finding | Severity | Fix |
|---|---|---|---|
| T1 | A Portuguese report linked the Spanish check page (`/comprobar`) and the English terms and privacy pages. | Low | The three links come from the fixed tables `seo.CHECK_PATH` and `legal.LEGAL_PATHS` by the report's language; nothing from the request is read, and every target is a path of this site. |
| T5 | The source link of Brazil's inflation series answered 404 on the publisher's site. | Low | `market.PROVIDER_URLS["bcb"]` links the series page of Banco Central do Brasil's SGS. It is a fixed `https://` template filled with the series number written in the code, escaped where the report prints it. A report made before this change keeps the address stored in its result, because a stored result is never rewritten. |
| T7 | With no recovery key and automatic mail off, the forgot-password pages offered only the chat link. | Low | They show the operator's address first, as a `mailto:` link. The address is `AUDIT_OPERATOR_CONTACT`, the value the terms, privacy and contact pages already publish; it is shown only when it has an `@` and no space, it is HTML-escaped, and nothing is shown when it is not configured. The block disappears when automatic mail is on, as the chat link does. No form, field or route was added. |

The other changes of this pass are texts only. The terms describe password
recovery as the site does it: the recovery key, a one-time link sent only to
a confirmed address when mail is on, and writing to the operator otherwise.

## Customer audit of the public pages (2026-09-28)

Reviewed against `main` at 8a536fb, after a customer-style read of the
public pages in the three languages. No control was relaxed: the Content
Security Policy, the other security headers, the rate limits, the client
address logic, `safe_next` and the redirect from Railway's address are
unchanged. Every change has an offline, deterministic test in
`tests/test_audit_customer_audit_fixes.py`.

| # | Finding | Severity | Fix |
|---|---|---|---|
| K1 | The governing-law clause of the English and Portuguese terms, and the address on English and Portuguese pages, printed the one value of `AUDIT_JURISDICTION` and `AUDIT_OPERATOR_ADDRESS`, written in Spanish. | High (legal text in the wrong language; no exposure) | Four optional variables, `AUDIT_JURISDICTION_EN`, `AUDIT_JURISDICTION_PT`, `AUDIT_OPERATOR_ADDRESS_EN`, `AUDIT_OPERATOR_ADDRESS_PT`, read like the base ones (one line, 300 characters at most, HTML-escaped where printed). None has a default. An empty one shows the base value. An override only rewords a base value that is set: alone it prints nothing, the draft warning stays and `legal_configured` in `/health` keeps its meaning (the four base variables). |
| K4 | An address with a trailing slash (`/en/`, `/guias/`, `/soporte/`) answered 307 with `Location: http://...`: the router builds that address from the socket, which speaks plain http behind the proxy. The browser was sent to a plain http address. | Low | The address of that one redirect is rebuilt from `AUDIT_BASE_URL` (`_slash_redirect_https` in `web.py`). It applies only when `AUDIT_BASE_URL` is `https`, the request's `Host` is the site's own (a port after the name, as in `host:443`, is the same site), the answer is a 307 and its target is the same host and the requested path with the slash added or removed. Scheme and host come from configuration; path and query are the ones the router already wrote. See the choice below. |
| K6 | On sign-up and sign-in, the language switch kept `next` on the upload page of the other language. | Low | `next` moves to the upload page of the target language only when it is one of the three upload pages, with or without the one query `safe_next` accepts (`extras=1`); any other value is kept as it was. The value in the link still goes through `safe_next` when it is read, and a test checks every combination passes it unchanged. |
| K7 | The news form had no `autocomplete` or `maxlength`; its error redirect had no `#news`; the limit page of the Portuguese form was in English. | Low | `autocomplete='email'` and `maxlength='254'` (the server limit, `_EMAIL_MAX`, is unchanged and still decides). The error redirect adds the fixed fragment `#news`; nothing from the request is echoed. The 429 page is in Portuguese. The limit per address (`WAITLIST_PER_HOUR_PER_IP`) is unchanged. |
| K3 | An unknown guide or audience page answered 404 with the words of a missing audit. | Low | The 404 carries the fixed key `page_missing`; status, headers and the redirect of a slug from another language are unchanged. |

**K4, the choice.** The other way was to make the server trust
`X-Forwarded-Proto` (uvicorn's `proxy_headers` with `forwarded_allow_ips`).
It was not taken: uvicorn trusts by the address of the peer, not by a count
of hops, and Railway's proxy has no fixed address, so it would mean trusting
every peer. With that setting uvicorn also replaces the socket address of
the request with the one in `X-Forwarded-For`, which is the input of
`client_ip` and of every rate limit: the address logic would change, and a
request that reached the service without passing the proxy could choose its
own scheme and address. Building the target from `AUDIT_BASE_URL` reads no
header the client controls, so `AUDIT_TRUSTED_PROXY_HOPS`, `client_ip` and
the rate limits work exactly as before (a test sends the limit of the news
form through `X-Forwarded-For` before and after the redirect). A request
with another `Host` keeps the router's own answer, as before.

Limits that remain from this pass:

- The rebuilt redirect needs `AUDIT_BASE_URL` set to the `https` address,
  as production has. With the default base the router's answer is unchanged.
- The description of the private pages (sign-up, sign-in, recovery,
  comparison) is one fixed sentence per language; they stay `noindex`.

## What the operator sets on Railway

- `AUDIT_BASE_URL=https://<your domain>`: absolute links stop depending on
  the `Host` header, and HSTS is turned on. Reads on the Railway address and
  on the domain's `www` name answer 308 to that fixed address (the target
  never comes from the request), so a visitor has one origin and one
  session; POSTs, `/health` and `/ready` are served where they arrive.
- `AUDIT_TRUSTED_PROXY_HOPS=1`, as before, so rate limits count the real
  client.
- Optional: `AUDIT_MAX_CONCURRENT_AUDITS` (default 2) and
  `AUDIT_QUEUE_SECONDS` (default 30). Raise the first only with more memory.
- Start the service with `quant-trade audit serve` (the Dockerfile already
  does), so the redacting log configuration is used.

## Customer audit: report wording, upload guidance and refusals (2026-09-29)

Reviewed against `main` at c6ce500. Scope: texts of the report, the upload
page and the refusals in Spanish, English and Portuguese. No reader,
threshold, limit or setting changed; no control was relaxed. Tests are
offline and deterministic (`tests/test_audit_report_polish.py`).

| # | Finding | Severity | Fix |
|---|---|---|---|
| P1 | A file that arrived with 0 bytes was answered "a file is missing"; a picture in the curve box was answered "needs a date column". | Low (wording) | `MESSAGES["empty_upload"]` names the box when the browser sent a file name with no bytes and nothing else was uploaded; `MESSAGES["curve_is_picture"]` when the curve box holds a file starting with a PNG, JPEG, GIF, TIFF or PDF signature (`PICTURE_SIGNATURES`) and the reader refused it. Both keep status 400; `_read_limited`, the byte limits and what is accepted are unchanged. The file name is never echoed. |
| P2 | A curve over the reader's 5 MB limit was told "10 MB" by the field or a byte count by the reader. | Low (wording) | `MESSAGES["curve_too_large"]` states `schema.MAX_UPLOAD_BYTES` as megabytes in both refusals (413 from the field, 400 from the reader). The field limit (`REPORT_FIELDS`, twice `max_upload_bytes`, so a platform report dropped in the curve box is still read as the report) and the reader's limit are unchanged. |
| P3 | A Portuguese report posted its comparison to `/compare` with `lang=pt`, which answered in Spanish. | Low | The report posts to `COMPARE_PATH["pt"]`; the three `POST` comparison routes treat `lang=pt` as Portuguese. Links, tokens and the checks on both reports are unchanged. |
| P4 | A preview of a file the account had already audited said nothing about the earlier report. | Low (product) | `Store.earlier_audit_of_same_files(account_id, audit_id)` looks only among audits linked to that account (`account_audits`), not purged, uploaded before this one, with the same set of SHA-256 digests (SQL prefilter on `equity_sha256` and `created_at`, then the full digest set, at most 20 candidates). `web._account_box` calls it only when the viewer is signed in as the owner of the report being viewed and the report is locked; the note links `/audits/<id>?lang=…` with no token, which that same account opens through its session. No report of another account is ever read for this or named. Nothing changes in what is spent. |
| P5 | The badge code made from an English or Portuguese verification page linked `/v/<id>` (Spanish). | Low | The link carries `?lang=en` or `?lang=pt` from the page's own language table; Spanish keeps the bare path. The badge, the page's allow-list and the public id are unchanged. |
