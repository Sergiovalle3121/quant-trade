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

## What the operator sets on Railway

- `AUDIT_BASE_URL=https://<your domain>`: absolute links stop depending on
  the `Host` header, and HSTS is turned on.
- `AUDIT_TRUSTED_PROXY_HOPS=1`, as before, so rate limits count the real
  client.
- Optional: `AUDIT_MAX_CONCURRENT_AUDITS` (default 2) and
  `AUDIT_QUEUE_SECONDS` (default 30). Raise the first only with more memory.
- Start the service with `quant-trade audit serve` (the Dockerfile already
  does), so the redacting log configuration is used.
