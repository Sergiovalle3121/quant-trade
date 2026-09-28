# Continuous track record (`track_seal`)

Code: `src/quant_trade/audit/track_seal.py` (the continuity core),
`track_seal_service.py` (the service layer the pages call), `store_hooks.py`
(tables and the delete / export / purge hooks) and `track_seal_pages.py`
(pages, behind `TRACK_SEAL_ENABLED = False`). On screen the feature is
"Historial continuo" / "Continuous track record" / "Histórico contínuo";
"sello" is only the `/v` badge and the name of the code.

## One-page summary for the owner

**What it is.** Someone who already holds a paid Rigor report of a trading
account statement can open a continuous record on it. From that day, every
new statement of the same account they upload (as another paid report) is
compared with the previous one. Trades and cash rows already recorded must
still be there, unchanged; new ones may only appear after the previous
cut-off. Each upload becomes one entry of a hash chain, dated by Rigor's
clock, never by the file's date. When a recorded operation is missing,
changed or an older one appears, the upload is still accepted but leaves a
dated event ("This upload differs from the previous one in N operations; it
may be a broker adjustment or an edit"). When the file cannot be the same
record at all (another account, another export format, another currency, a
statement that starts later than the first one, no new operations, rows
dated in the future), it is refused, nothing is written, and the page asks
for the complete history.

**Who it is for.** Privately (the MVP): a buyer of a robot or a signal, or
an investor, follows the statements a seller sends them, without the seller
cooperating. Publicly (after a switch the seller flips, with a checkbox
saying they hold the account or have permission): the seller shows their
own record at `/historial/{id}` with a badge and a `chain.json` anyone can
recompute with a hash tool.

**What it says about the trading.** The sealed stretch — the trades opened
a day or more after the record was opened — is re-audited with the same
engine as any upload. Under 30 observations it shows "no class yet: N of
30", never a D from too little data. "Time to know" is the number of months
left, at the current pace, to reach the significance section's minimum
track record length; it is an estimate that changes with every upload, not
a forecast, and it is blank ("no positive mean to measure") while the mean
return is not positive. The class of the whole latest file is shown too,
labelled as including the stretch before the opening, which the record
does not cover.

**What it does not do.** Nothing proves the broker issued the file; a
consistent forger who fabricates every statement from day one is not
detected; the uploader chose when to open and whether to publish, and
Rigor does not see their other accounts; a statement shows closed trades,
so an open loss on the day of an upload may not show; and without an
external timestamp, believing the dates means trusting that Rigor did not
alter its database (a reader should keep a copy of `chain.json`).

**Cost and quota.** No new price: each link is an ordinary paid report.
Opening is free. Five records per account, ever; deleting one does not free
its slot. No card or code is needed to open, end, delete, publish or
unpublish, and paying never changes a status, a class or an event.

**State of the build (2026-09-26).** Core, tables, hooks and the service
layer are built and tested offline on SQLite (and on PostgreSQL where
`RIGOR_TEST_PG_URL` is set, for the hooks). The pages are a separate PR
behind `TRACK_SEAL_ENABLED`; the public page waits for the legal review;
the Portuguese public page waits for a review in Brazil. What still needs
the owner is listed under "Pending owner items".

## Rules as built

### Opening (`track_seal_service.open_record`)

- The report must belong to the account (`store.account_for_audit`), be the
  account's own upload (`via` in `store.OWN_VIAS`, i.e. uploaded while
  signed in, not saved from someone's link or paid for as someone else's),
  be paid through the normal `/audits` flow (`record.paid`; there is no
  seal-specific form or credit), and not be purged.
- The file is re-read from `store.get_audit(id, with_blobs=True)`: the
  `report.*` file first, else the `live.*` statement, whose
  `inputs.source_format` (or `live_format`) in the stored result must be
  one of `mt4_statement_html`, `mt5_history_html`, `mt5_history_xlsx`,
  `myfxbook_csv`, `mql5_signal_csv`, `fxblue_csv`. Tester reports are never
  accepted. Without such a file, an `equity.csv` that
  `factsheet.monthly_grid` reads as a year-by-month table opens a monthly
  record (`source_format = monthly_table`).
- The stored bytes are hashed and compared with `record.digests`; a
  mismatch is `stored_file_mismatch` (a storage fault, never the client's).
- The opening date is `now`, Rigor's clock. The first chain entry, the
  seal row, the upload row (with the canonical snapshot) and an `opened`
  event are written in one transaction, together with the quota (one
  conditional `UPDATE ... WHERE opened < 5`, so two openings at once cannot
  both pass on PostgreSQL).
- The account number is not read when opening: it is only needed to
  compare two statements.

### Continuing (`add_upload`)

- The record must be open and the account's; the report passes the same
  checks as at opening; a report already linked to this record is
  `already_linked`.
- The previous snapshot comes from the last upload row's `snapshot_json`;
  the new one from the new file. The previous statement's account number is
  read again from the store (`forensics.rows.account_key` on the previous
  report's bytes; `None` when that report was deleted or the format prints
  none — Myfxbook, MQL5 signals, monthly tables), the new one from the new
  bytes; both live in local variables of `add_upload`, are compared inside
  `track_seal.compare_uploads` and are dropped. They are never stored,
  hashed, logged or returned.
- `compare_uploads` decides (design §6.3): a refusal writes nothing; an
  outcome writes one upload row (chain entry at position + 1, `previous_hash`
  = the head), one event (`uploaded` with count 0, or `mismatch` with the
  count and the private detail), and updates `head_hash`, `upload_count`,
  `last_upload_at`, `last_cutoff` and `sealed_json`, in one transaction that
  re-checks the record is still open with the same number of uploads.
- Continuity rules (core): closed trades and cash rows up to the previous
  cut-off must be identical at the printed precision; nothing new may fall
  before it; the currency may not change; the cut-off must advance; nothing
  may be dated after `now + 14 h`. A position listed open in the previous
  statement must be accounted for by the same open position or by closed
  pieces with the same open time, symbol, side and open price. In monthly
  tables past months may not change (the last month may, while the previous
  upload was made inside it). Whole-minute clock offsets up to ±14 h and
  one-to-one symbol renames are figures, not events.

### Ending, deleting, publishing

- The holder ends an open record (`end_record`): status `ended`, reason
  `holder`, an `ended` event; the record is frozen with its date and can
  still be published. Deleting a linked report ends the record the same
  way with reason `report_deleted` (the chain entry stays, without its
  report).
- The holder deletes a record (`delete_record`, and `delete_account`):
  uploads and events vanish; a record that was ever published leaves a
  tombstone row (status `withdrawn`, `withdrawn_at`, nothing else) whose
  public page says only when it was withdrawn.
- Publishing (`publish`) requires the holder's checkbox (`holder_confirmed`;
  its date is stored in `holder_confirmed_at`), sets `published`,
  `published_since` (once; never reset) and `publish_hash`, and writes a
  `published` event. One set of operations admits one public record: a
  second record whose latest upload has the same content hash is refused
  (`already_public`). `unpublish` clears `published`, keeps
  `published_since` and writes an `unpublished` event. The owner's panel
  hides and shows a page reversibly (`hide`, `unhide`; `hidden_at`, events
  `hidden` and `shown`) while a complaint is looked at; ending or deleting
  is the holder's decision or a legal order's.
- The public view (`public_record`) is `None` — the same 404 — for a
  missing, hidden or not-currently-published record; it carries dates,
  counts, codes, hashes, the sealed stretch, events (date, kind, count
  only) and how many records the same account has opened.

### Purge

`store_hooks.on_purge` drops ended records that were never published once
their end is past `retention_days`. A published record, or its tombstone,
is never purged.

## Storage

Tables declared in `store_hooks.define_tables` on the `Store`'s metadata,
present from day one with every column the pages will need (there is no
ALTER path). Ids are `secrets.token_urlsafe(16)`; nothing derives from an
audit id.

`track_seals`: `id`, `public_id` (the public path segment, independent of
the id), `account_id`, `opened_at`, `status` (`open` | `ended` |
`withdrawn`), `source_format`, `currency`, `method_version`
(`forensics.review.METHOD_VERSION`), `recipe_version`
(`track_seal.RECIPE_VERSION`), `upload_count`, `head_hash`, `last_upload_at`,
`last_cutoff`, `sealed_json`, `ended_at`, `ended_reason`, `withdrawn_at`,
`published_since`, `published`, `publish_hash`, `holder_confirmed_at`,
`hidden_at`.

`track_seal_uploads`: `id`, `seal_id`, `position` (1-based), `at` (Rigor's
clock), `audit_id` (cleared when that report is deleted), `source_format`,
`cutoff`, `closed_count`, `flow_count`, `currency`, `trades_sha256`,
`previous_hash`, `hash`, `recipe_version`, `entry_json` (the chain entry
without its hash), `snapshot_json` (the canonical records: closed trades,
cash rows, positions listed open, months; symbols, references, sides,
times and printed figures only — no account number, name, broker, comment
or file name).

`track_seal_events`: `id`, `seal_id`, `upload_id`, `at`, `kind` (one of
`store_hooks.EVENT_KINDS`: `opened`, `uploaded`, `mismatch`, `ended`,
`published`, `unpublished`, `hidden`, `shown`), `count`, `detail_json`
(private: one entry per differing operation with its kind, record kind,
reference, time and field names).

`track_seal_quota`: `account_id`, `opened` (never decremented; deleted with
the account).

What the export ("Descargar mis datos") includes: `store_hooks.export_account`
lists each record's dates, counts, hashes and events; never a snapshot, a
file or an account number.

## Chain recipe

Entry (strings and integers only):

```
{"v": "track-seal-1", "position": 3, "at": "2026-10-02T10:11:12Z",
 "cutoff": "2026-09-30T21:59:59Z", "closed_count": 40, "flow_count": 3,
 "currency": "USD", "source_format": "mt4_statement_html",
 "method_version": "forensics-1", "trades_sha256": "<64 hex>",
 "event_kind": "uploaded", "event_count": 0, "previous_hash": "<64 hex>"}
hash = sha256(json.dumps(entry, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
```

The first entry's `previous_hash` is `""`; the head is the last hash.
`trades_sha256` is the SHA-256 of the sorted canonical closed trades and
cash rows up to the cut-off (one hash per set of operations, whatever the
row order); for a monthly table, which has no trades, the service hashes
the sorted months instead, so two different monthly records never share a
publication hash. `chain_json` publishes the entries with their hashes and
the recipe in words (`track_seal_service.CHAIN_RECIPE`);
`tests/test_track_seal_service.py` recomputes the head from the stored
entries with `hashlib` and `json` only. `verify` recomputes every hash and
link; when it fails, the page attributes it to a Rigor error, hides the
class and warns in `/panel/historiales`.

## Sealed stretch

`S = opened_at + 1 day` (Rigor's clock). The latest file is cut to the
trades opened at or after `S` (`track_seal.sealed_stretch_bytes`, a head
cut of the original rows; straddling trades are dropped) and the starting
balance `B0` is the file's initial balance plus the cash rows and the net
result of the trades settled before `S`. The cut is parsed and audited
exactly as `POST /audits` parses an upload — `schema.build_inputs(None,
DeclaredMetadata(trials_declared=False, initial_balance=B0),
report_bytes=cut, report_filename=<stored name>, now=now)` then
`engine.run_audit(inputs, bootstrap_samples=..., now=now)` — with no
declaration beyond the balance (1 trial, no cost, no benchmark file, no
market data). For a monthly table the stretch is the months after the
opening month, written as a `timestamp,return` series the way
`parse_equity_csv` rewrites a grid.

`sealed_json` (every figure is text with its evidence tag):

- `observations` (MEASURED) and `min_observations` (`schema.MIN_OBSERVATIONS`
  = 30, tagged DECLARED: a constant of the method, not a measurement).
- `class`: the verdict's overall class only when observations ≥ 30, else
  `""` with `pending_reason = too_few_observations`. Never a D from too
  little data.
- `months_to_know` (MEASURED when estimable): months left, at the current
  pace (observations per month over the stretch's span, `pace_per_month`),
  to reach `max(significance.min_track_record_length, MIN_OBSERVATIONS)`;
  `"0"` once reached. `""` with `reason = no_positive_mean` when the
  per-period Sharpe is not positive (no track record length reaches PSR
  0.95), or `too_few_observations` when the significance section could not
  measure or the span is too short for a pace. It is an estimate that
  changes with every upload, not a forecast.
- `full_class` (MEASURED): the class of the whole latest report, with
  `scope = whole_file_including_uncovered_pre_opening_stretch`.
- `start`, `first_observation`, `last_observation`, `computed_at`.

When the cut holds no trade the importer can read, the stretch is
`observations = "0"`, class pending. The stretch is recomputed on every
upload with the latest file.

## Freshness

`freshness(record, now)` is `current` while the last upload is younger than
45 days (75 days for a monthly table), else `stale` with the date of the
last upload ("sin cargas desde <fecha>").

## Refusal codes

Service (`track_seal_service.SERVICE_REFUSAL_CODES`):

| code | meaning |
|---|---|
| `not_found` | no such report on this account (also a report on another account: the same answer) |
| `not_own` | the report was saved or paid from someone's link, not uploaded by this account |
| `unpaid` | the report is not paid |
| `purged` | the report's files were purged |
| `unsupported_file` | no statement of a supported format and no monthly table in the report (tester reports included) |
| `empty_statement` | the statement holds no closed trade, cash row or month |
| `stored_file_mismatch` | the stored bytes do not match the stored digest (a storage fault) |
| `quota` | the account has opened five records already |
| `record_not_open` | the record is missing, not this account's, ended or withdrawn |
| `record_not_found` | the record is missing or not this account's (actions on a record) |
| `already_linked` | this report is already a link of this record |
| `already_public` | another public record holds the same operations |
| `holder_not_confirmed` | the holder's checkbox was not ticked |

Core (`track_seal.REFUSAL_CODES`), all written without an event:

| code | meaning |
|---|---|
| `account_differs` | the account numbers differ, or (formats without one) the five earliest trades are not in the new file |
| `format_changed` | another export format or family (an XLSX after an HTML counts) |
| `currency_changed` | the account currency differs |
| `partial_statement` | the export starts more than a minute after the previous one |
| `already_recorded` | the same cut-off and the same operations: the same export again |
| `cutoff_not_advanced` | no operation after the previous cut-off |
| `future_rows` | a row dated after `now + 14 h` |
| `earlier_rows` | a wider export that only adds rows before the first upload (extending backwards is the owner's decision) |

## Corpus regression (measured on 2026-09-26)

Run by the core on the public genuine corpus (real files only; never
fixtures, clients or production), as a scratch run whose log is not
committed:

- Real pairs and sequences: 15 pairs / 50 real transitions uploaded with 0
  false breaks; 1 mismatch, explained as a wider re-export; 23 refusals,
  each explained (same export again, cut-off not advanced, format change).
- Synthetic cut sequences on real files (`cut(D1) → cut(D2) → full`):
  116/116 uploaded without an operation.
- Seeded one-step alterations (a deleted trade, a P&L changed by one
  printed unit, an inserted copy, a removed withdrawal where the file has
  one): 296/296 gave exactly one `mismatch` event naming that record.
- No real pair exercised a clock offset or a symbol rename: those
  tolerances are covered by synthetic shifts of the same files only.

`tests/test_track_seal.py` keeps the fixture version of the same sequences;
`tests/test_track_seal_service.py` runs them through the store.

## Pending owner items

- `legal.py`: the new paragraph saying that each statement is kept, with
  its account number, until its report is deleted; how it is exported and
  deleted; how to claim a page, and that Rigor does not decide whose an
  account is.
- `/privacidad` and the delete-account copy: the withdrawal tombstone (a
  published record's link says only "withdrawn by the person who opened it
  on <date>" after deletion).
- Report link texts (`report.render` VALUE with its PT twin, `_report_html`
  ACCOUNTS): "Follow this record: every new statement they send you will
  be compared with this one" and "If this record is yours, open a
  continuous record: opening is free"; among the vendor questions, "Do
  they have a continuous record on Rigor? Ask for the link".
- `/panel` metrics reviewed by FIRST SALES: previews before payment,
  records with a second upload attempted (with or without credit), daily
  visits to `/historial` without a cookie.
- The go-ahead for private use (PR 2), the legal review before the public
  page (PR 3), and the review in Brazil before the Portuguese public page.
- Decision with MATH: whether `S` should carry an extra `+ 14 h` for server
  clocks ahead of UTC.

## Limits

The pages say them, and so does this document:

- The date is Rigor's, not the uploader's, but without an external
  timestamp believing it means trusting that Rigor did not alter its
  database: keep a copy of `chain.json`.
- Nothing is cut without leaving an event, but the uploader chose when to
  open and whether to publish, and Rigor does not see their other accounts.
- A statement shows closed trades; an open loss on the day of an upload may
  not show.
- Nothing proves the broker issued the file, and a consistent forger who
  fabricates every statement from day one is not detected.
- The account number of the previous statement is re-read from its stored
  report; once that report is deleted the comparison falls back to the
  five earliest trades, as for formats that print no account number.
- Myfxbook, MQL5 signal and FX Blue records are accepted on the strength of
  the fixture tests and the few real pairs the corpus holds for them; MT5 "Open Positions" sections are unverified against a
  real file, so an MT5 tail cut lists nothing open.
- A monthly re-upload that revises a past month without adding a new one
  has the same cut-off and, since a monthly snapshot has no trades, the
  same `trades_sha256`: the core answers `already_recorded` instead of a
  mismatch. It surfaces as a mismatch on the next upload that adds a month.
- The sealed stretch is audited with no declaration but the balance and
  without public market data, so its class can differ from the full
  report's for reasons other than the trades (no holding comparison, one
  trial assumed).

## Future work: external timestamp

Anchoring each head hash in a public timestamp service (or a public ledger)
would let a reader check the dates without trusting Rigor's database. Not
built: it needs a provider choice, a cost and a privacy review of what the
anchored hash reveals (nothing but the hash, by construction). The chain's
entries are already flat strings and integers so an anchor can be added
without changing the recipe.

## Pages (`track_seal_pages.py`, `track_seal_copy.py`)

Built as PR C2, behind three constants in `track_seal_pages.py` (never a
Railway variable): `TRACK_SEAL_ENABLED = False` (the account pages, the
examples and the owner panel), `TRACK_SEAL_PUBLIC_ENABLED = False` (the
public page, its badge and `chain.json`, after the legal review) and
`TRACK_SEAL_PUBLIC_PT_ENABLED = False` (the Portuguese public page, after a
review in Brazil). While the first is off `register` mounts nothing and
every path below answers 404. `register` is called from `web.create_app`
with the app's own closures (`session`, `signed_in_action` with its CSRF
check and rate limit, `panel_failures`, `settings`, `store`, `slots`); the
only things it imports from `web` are the slot wait (`_take_slot`), the
address reader (`_client_ip`) and the "busy" message. Every page is
`noindex`, out of `sitemap.xml`, without index, list or search, and passes
`guard.assert_report_clean` in Spanish, English and Portuguese.

Words live in `track_seal_copy.COPY` with identical keys in `es`, `en` and
`pt` (`tests/test_track_seal_copy.py` also renders every template with
extreme figures, checks the forbidden words of design §8 with the fixed
notices' exact phrases allowed, and that the brand comes only from
`seo.BRAND`). On screen the feature is "Historial continuo" / "Continuous
track record" / "Histórico contínuo"; the badge is "insignia" / "badge" /
"insígnia"; the words sello, auténtico, verificado, inalterable, "para
siempre", "demuestra" and the imperatives never appear.

### Account pages (signed-in only, like `/cuenta`)

| ES | EN | PT | shows |
|---|---|---|---|
| `/cuenta/historiales` | `/account/records` | `/pt/conta/historicos` | the account's records: status, opened date (the service's clock), uploads count, last upload and freshness ("Al día" / "sin cargas desde <fecha>"), the class of the stretch after the opening or "aún sin clase: N de M observaciones", the "Tiempo para saber" line, the whole file's class with "incluye lo anterior a la apertura, que no está cubierto", events with detail, method version and chain head, and every action |
| `/cuenta/historiales/{id}` | `/account/records/{id}` | `/pt/conta/historicos/{id}` | the same card plus the uploads table (position, date, cut-off, closed operations, cash movements, hash) |

Actions are POST forms with the session's CSRF token through the app's
`_signed_in_action`; the action segments are Spanish in every language, as
the account pages do (`/account/records/abrir`):

- `POST {records}/abrir` (`audit_id`): open a record from one of the
  account's eligible reports (`service.eligible_reports`: own `via`, paid,
  not purged, a supported statement or a monthly table whose digest still
  matches). The select lists only those. Re-import and re-audit run under
  the audit slot, like an upload, with `settings.bootstrap_samples`.
- `POST {records}/{id}/cargar` (`audit_id`): add an upload from an eligible
  report not yet linked; a mismatch redirects with `done=mismatch&n=N` and
  the page says "Esta carga no coincide con la anterior en N operaciones;
  puede ser un ajuste del bróker o una edición."
- `POST {records}/{id}/terminar`, `POST {records}/{id}/borrar` (without
  `confirm=yes` it answers the confirmation page; with it, deletes),
  `POST {records}/{id}/publicar` (requires the checkbox `holder=on`: "Soy
  titular de esta cuenta de trading o tengo su permiso para publicar este
  historial"), `POST {records}/{id}/despublicar`.
- Every refusal code of the service and the core becomes a sentence per
  language (`refusal_<code>` in the copy), shown from `?error=<code>`;
  unknown codes are ignored. Flashes come from `?done=<kind>`.
- Once published (and while `TRACK_SEAL_PUBLIC_ENABLED`), the card shows the
  public link and the badge code in HTML, BBCode and Markdown. Absolute
  links use `AUDIT_BASE_URL` only; with the default base URL they are
  relative, never built from the `Host` header.
- A mismatch's detail lists kinds and counts of operations (record kind and
  field names); never a trade, a ticket or a symbol. The `ref` the table
  stores is not shown.

### Public page (only with `TRACK_SEAL_PUBLIC_ENABLED`)

`/historial/{public_id}` (EN `/record/{public_id}`, PT
`/pt/historico/{public_id}` only with `TRACK_SEAL_PUBLIC_PT_ENABLED`), plus
`/{prefix}/{public_id}/badge.svg` (`?lang=`) and `/{prefix}/{public_id}/chain.json`.
Built from `service.public_record`, an allow-list: the notice (the record's
equivalent of `pages.VERIFICATION_NOTICE`), "público desde el <fecha> (<N>
días después de abrirse)" and the unpublished periods, opened date, uploads
count, freshness, method and recipe versions, chain head, the class of the
stretch after the opening at the top (or "en curso"), observations,
"Tiempo para saber", the whole file's class with its note, events with only
date, kind and count (opened, uploaded, mismatch, ended, published,
unpublished; hidden/shown stay private), the calibration caveat "cambios
aún no calibrados con re-exportaciones reales" while
`REAL_PAIRS_DOCUMENTED` (15, from the corpus regression above) is below
`MIN_REAL_PAIRS` (5), "Historiales abiertos por esta cuenta: N. Rigor no ve
otras cuentas de la misma persona.", "pagado por quien sube el archivo;
pagar no cambia la clase", the limits, the `chain.json` link, the badge
and, at the foot, "¿Te pasaron otro historial? Revísalo en Rigor" (a link
to the upload form). Every figure carries MEASURED, DECLARED or
NOT_MEASURED. Nothing else: no performance figure, name, file, account,
broker, internal id, e-mail or outbound link (`tests/test_track_seal_pages.py`
greps the page, the badge and the chain for the fixture's account number,
name, robot, broker, symbols, tickets, the account's e-mail and the internal
ids). Missing, hidden, unpublished or never published: the same 404. A
withdrawn record that was once published answers only "retirado por quien
lo abrió el <fecha>". When `verify_chain` fails the page attributes it to
an error of the service, hides the class and `chain.json` says
`chain_ok: false`.

The badge (`record_badge_svg`) keeps the shape of the `/v` badge: the
class letter (or "·" and "en curso"), "Rigor · Historial continuo · <clase>",
the last upload date, the public id and `pages.BADGE_NOTICE` intact.

### Examples (invented data, banner "Ejemplo con datos inventados; no es el historial de nadie")

- `/historial/ejemplo`, `/record/sample`, `/pt/historico/exemplo`,
  registered before the public ids and available with
  `TRACK_SEAL_ENABLED` alone: a record with one mismatch event, a stale
  stretch ("sin cargas desde 2026-06-20" at the fixed clock
  `EXAMPLE_NOW`), a class B stretch, a time-to-know line and an unpublished
  period. Its data is `track_seal_pages.EXAMPLE_VIEW`.
- `/coherencia/ejemplo`, `/consistency/sample`, `/pt/coerencia/exemplo`: an
  invented MT4 statement embedded in the module (`SYNTHETIC_STATEMENT`, four
  trades and a deposit; no fixture is read at runtime) and the same
  statement with three edits made with `forensics.edit`: a duplicated
  ticket an hour later (noticed: the totals and the duplicated ticket), a
  changed result with the summary left alone (noticed: the totals and the
  sign of the result against the prices), and a deleted trade whose totals
  are rewritten by hand (not noticed: the limit, "un archivo editado con
  cuidado pasa estas pruebas"). The battery runs once per process
  (`coherence_results`). Check ids appear only inside a `<details>` block;
  the headlines are sentences. No calibration cell is granted yet, so every
  trace is INFO ("es información, no una señal").

### Owner: `/panel/historiales`

Protected exactly like `/panel`: the key travels in the POST body, is
compared in constant time, wrong keys count in the same `panel_failures`
log with the same ceiling, and without `AUDIT_ADMIN_KEY` the path is 404.
It lists every record (public id, opened date, status, published, hidden,
chain verification, uploads) and offers only hide / unhide (reversible,
events `hidden` / `shown`) while a complaint is looked at; a broken chain
shows a warning. No e-mails, no ending, no deleting.

### Tests

`tests/test_track_seal_pages.py` (offline, `TestClient`, switches
monkeypatched before `create_app`): 404 everywhere with the switch off;
public routes wait for their switches; account pages need a session; a
wrong CSRF token writes nothing; the whole flow (open from a paid own
report through the form, a second upload made from the fixture with
`forensics.edit`, the mismatch event and its detail, refusal sentences,
publish with and without the checkbox, the public page's allow-list, the
badge's content type and notice, `chain.json` recomputed with `hashlib` and
`json`, unpublish, end, delete with confirmation, the tombstone); the
English and Portuguese account pages; every refusal sentence in every
language; foreign or unknown reports; stale freshness; a broken chain on
the public page, the account page, `chain.json` and the panel; one public
record per set of operations; the examples in three languages with the
banner; the coherence variants; the panel's key, hide and unhide; sitemap
and robots; brand and guard on every page. `tests/test_track_seal_copy.py`
covers the copy.
