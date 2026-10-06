# Private commercial and operational measurements

This delivery adds owner-only measurements to the existing authenticated
`AUDIT_PANEL_PATH` (default `/panel`). It does not change payment fulfillment,
credit consumption, report access, audit verdicts or public verification pages.
`/health`, `/ready` and `/live` keep their existing contracts. Retention status
does not become a readiness requirement or cause a Railway restart.

The public landing explains email confirmation next to its primary CTA in ES,
EN and PT **only when `AUDIT_EMAIL_VERIFICATION_REQUIRED=true`**. The underlying
email/card-verification gates are unchanged.

## Additive schema and privacy

`Store.metadata.create_all()` creates three tables using the existing startup
pattern. No existing table, column, ledger or customer blob is rewritten.

| Table | Persistent values | Purpose |
| --- | --- | --- |
| `ops_counters` | UTC day, language, operation, outcome, latency bucket, count | Private 30-day aggregate operations |
| `ops_jobs` | Fixed job name `retention`, latest attempt/success UTC, fixed error code, purge count | Last service retention attempt/success across restarts |
| `commercial_costs` | Exact UTC start/end dates, scope, category, USD cents, internal source reference, last update UTC | Operator-recorded costs |

Counters store no filename, report/account identifier, IP, email, token, request
path/query, customer content or exception text. The operations tables are not a
new analytics service. Aggregate rows and accounting references are not deleted
by customer-upload retention; the panel displays the last 30 UTC days. Keep
accounting references internal and free of customer data or secrets.

## Reading operations

Operations are `upload` (the complete POST request), `queue` (audit CPU-slot
wait), `audit` (import and calculation) and `pdf` (GET download, including cached
and public sample PDFs). Outcomes are success, invalid, busy, error and denied.
An invalid/paused/body-limit upload can be counted before multipart parsing.
Early upload rejections use ES unless the request query supplies a supported
language; accepted uploads use the parsed report language.

Counts and approximate histogram p50/p95 carry `MEASURED`; no samples produce
`NOT_MEASURED`. Percentiles show bucket **upper bounds**, including `>120 s`,
from successes only. These are request measurements, not CPU billable time or
proof of capacity. An upload success means a redirect was issued, not a paid
order. A denied/failed PDF does not consume or unlock a right.

Request handling updates a bounded in-memory buffer only. A daemon flushes to
SQL every 60 seconds; a private panel read also flushes. Writes increment
atomically across processes. Failed writes remain pending for retry, and the
panel reports the failure and process-local dropped-event count. The buffer
allows 4,096 distinct aggregate keys, never an unbounded request log.
Metrics are best effort: a crash can lose the unflushed buffer; a lost database
commit acknowledgement can make a retry ambiguous. Use the existing durable
payment/rights ledger for money and delivery reconciliation. Telemetry failure
must not change an upload, PDF, purge result or public health response.

On PostgreSQL, operations and cost writes/reads use their own one-connection
pool (no overflow), with a one-second pool wait, two-second connection and SQL
statement timeouts, and a 500 ms lock wait. This adds at most one database
connection per application process; customer transactions keep their existing
pool and timeout settings. The panel skips its counter flush when another flush
is already running. SQLite retains the existing engine.

Shutdown gives the daemon at most five seconds to persist its final buffer; it
never performs synchronous telemetry SQL on the lifespan caller. A stalled flush
can leave counters unpersisted at process exit, which the private failure state
reports. Counter totals remain best effort and never substitute for the ledger.

The service's existing `AUDIT_AUTO_PURGE=true` worker records health after each
run, including the initial run. The private panel distinguishes disabled,
unmeasured, first/latest attempt failed, recent success and success overdue by
**more than 36 hours**. A late replica cannot regress the latest attempt or
success timestamp. Failed monitoring writes never roll back a completed purge.
This status observes service-worker runs; it does not confirm a separate CLI
purge. Existing retention-delete authorization remains unchanged.

## Recording observed costs

The existing owner key authorizes the panel form. Submit the exact dates shown
for either `all` (rolling 30-day business total) or `x` (14-day acquisition
cohort). Dates are inclusive UTC calendar days. Four category totals are
required for the *same exact dates and scope*:

Invalid form values and database persistence failures produce distinct private
messages. A database failure never claims the cost was saved or exposes its
exception details. The save result remains visible if the metric read also fails.

- `infrastructure`: observed infrastructure and variable usage, including free
  and paid report usage; retain the actual invoice/allocation separately.
- `payments`: observed Stripe fees, FX and applicable taxes on fees.
- `acquisition`: observed campaign/ad spend.
- `support`: observed support expenditure or documented accounting allocation.

Use USD with at most two decimals and a short internal source reference.
Record a genuine zero explicitly. Missing categories, mismatched dates/scopes
or missing measurements produce `NOT_MEASURED`; the application never invents
costs or prices CPU seconds. Reposting the same period/scope/category replaces
that category total rather than adding it again; corrections update its source
and timestamp. The table holds the latest submitted total, **not an immutable
accounting revision history**. Retain original evidence in the operator's books.

Contribution is `gross live USD charges - succeeded USD refunds - recorded
costs`. Margin divides contribution by gross charges; zero gross has no defined
percentage. Negative contribution is displayed. Costs and resulting
contribution are `DECLARED`, not independently audited. Charge/refund totals
come from Rigor's ledger, not bank payouts or a tax-profit statement.

The X cohort includes accounts created in the last 14 UTC days whose existing
first-touch tag is `x` or `x-*`. Counts cover confirmations, first upload,
welcome delivery and live delivered purchases through the end of that window.
Each stage counts a distinct account; repeat buying requires multiple delivered
orders. Duplicate charges remain money to reconcile but do not count as a new
buyer or delivery. Old accounts with a new purchase are not new acquisitions;
changing a later campaign tag does not overwrite first-touch attribution.
Recent cohorts are incomplete and untagged traffic is not attributed to X.
Allocate X costs separately with documented evidence; the total and X views
are alternatives, not figures to add together. Rolling windows change daily,
so an older submitted window does not silently match today's window.

## Staged rollout and rollback

1. Confirm Railway's service branch, automatic-deploy setting, Dockerfile and
   healthcheck in the actual service dashboard. Keep the established `/ready`
   healthcheck unless a separately reviewed operator change authorizes another.
   The removed `railway.json` is not the active service configuration.
2. Create a staging service with a separate PostgreSQL database, environment,
   storage and hostname. Use synthetic data only. Do not copy a live Stripe key
   or customer upload to staging. Verify the current allowed test-audit and
   Stripe-test restrictions with existing offline HMAC fixtures.
3. Take an operator-authorized production backup and prove restore in a separate
   database before rollout. Run the additive startup against a populated
   staging schema once before scaling replicas; verify old tables and rights
   remain byte-for-byte/logically unchanged. No production data mutation is
   required to test the change.
4. Smoke the existing `/health`, `/ready`, `/live`, ES/EN/PT CTA and private panel.
   Verify wrong-key denial/no-store, synthetic confirmation, free preview,
   paid-right/credit retry, HTML/PDF delivery, and retention success/failure
   using isolated fixtures. Inject telemetry SQL failure and prove delivery
   remains available. Reconcile measured counters after a manual private flush.
5. Measure staging at concurrency 1/2/4/8 with a fixed synthetic file and bounded
   batches, stopping on an error, lost credit or growing queue. Measure actual
   PDF rendering and available resources separately. The local PostgreSQL
   checks in [LOCAL_POSTGRES_QA.md](LOCAL_POSTGRES_QA.md) are evidence for the
   tested host, not an assigned Railway capacity or production load approval.
6. Record backup, commit/image, measured p50/p95 and error counts before a manual
   production rollout. Do not saturate public production to discover capacity;
   use read-only public probes and the private panel after rollout.

Rollback deploys the previous application image/commit and keeps the three new
tables. The old application ignores them. Do not drop tables, reverse counters,
restore over a live payment ledger or delete customer files as a code rollback.
Reconcile any post-backup live purchases before considering data recovery.
No push, merge or deploy is performed by the local implementation/tests.

## Offline validation

Private report comparison explains why a numeric difference is unavailable,
using fixed ES/EN/PT messages and report indices only. It distinguishes missing
or invalid date/time evidence, absent time zones, inverted or different windows,
missing/nonpositive/nonfinite measured frequencies, missing/different frequency
labels, and equity versus closed-trade balance. Closed-trade balance omits open
positions. Equal timestamp instants remain comparable across time-zone offsets;
the existing relative frequency tolerance of `1e-6` remains unchanged.

Sharpe and drawdown evidence are checked independently: a missing `MEASURED`
tag, invalid value or overflowing difference withholds only the affected delta
when the context otherwise matches. Numeric strings, booleans, nonfinite values
and oversized integers are rejected. Both curve-type fields must be booleans;
both frequency labels must be nonempty strings. Two missing labels are incomplete
evidence, rather than a matching frequency. Malformed input/performance containers
fail closed without rendering their contents or raising numeric-overflow errors.

Differences remain arithmetic (report 2 minus report 1; drawdown in percentage
points), without significance tests, rankings or future-result claims. These
checks use stored results, preserve existing classifications and permissions,
and do not change credits or stored inputs. Diagnostics never echo timestamps,
labels, file names, cells, account identifiers or other free-form values.

Run the existing account/payment/rights/PDF/retention tests and the new
`tests/test_audit_commercial_observability.py`. The opt-in PostgreSQL suite
validates atomic counters, concurrent credit retry, additive schema preservation
and real pg_dump/pg_restore with synthetic fixtures. No test calls Stripe, email
delivery or a broker. Install PDF native dependencies through the deployment's
documented system dependencies, not by changing the SaaS dependency lock.
