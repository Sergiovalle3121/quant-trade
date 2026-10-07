# Local PostgreSQL staging checks

These opt-in checks exercise the application against a real, isolated PostgreSQL
server using generated accounts, uploads, payments and credits. They do not read
Railway, production credentials, customer files, a payment provider or a broker.
All databases created by the suite have a random `rigor_qa_` prefix and are removed
after their connections are closed.

## Run

Use a disposable PostgreSQL server listening **only on `127.0.0.1`**, an explicit
unused port and an administrative account for the empty `postgres` database.
The checks refuse other hostnames, addresses or initial databases. The account
must be able to create and remove test databases. Do not reuse production
credentials.

On Windows, PostgreSQL provides [official installation and binary archive
options](https://www.postgresql.org/download/windows/); the archives are available
from [EDB](https://www.enterprisedb.com/download-postgresql-binaries). The local
verification used PostgreSQL 17.11 binaries obtained from that source, started as
a hidden process under the workspace, with no installed service or paid account.
The downloaded archive's locally calculated SHA-256 was
`80379b2c04d51c30225532e0ae04509899141e9957ed096fe749d7fd9df8f82f`.

Set `QA_POSTGRES_URL` to the local SQLAlchemy PostgreSQL/psycopg URL, `QA_PG_BIN`
to the folder containing `pg_dump` and `pg_restore`, and optionally
`QA_REPORT_DIR` to a directory for non-sensitive JSON evidence. From the
repository:

```powershell
python -m pytest tests/test_audit_ops_postgres.py `
  --basetemp=../qa-pytest-temp `
  --junitxml=../qa-results/postgres-junit.xml -q -ra
```

The normal offline suite skips these tests when `QA_POSTGRES_URL` is unset. The
backup/restore scenario also requires `QA_PG_BIN`. PostgreSQL credentials stay in
the environment and are never included in subprocess arguments or JSON evidence.

For the expanded scenario, install the application's PDF dependencies and run:

```powershell
python scripts/qa/run_postgres_staging.py `
  --audits 50 --bootstrap 1000 --slots 2 `
  --pg-bin ../pg/binaries/pgsql/bin --report-dir ../qa-extended `
  --pdf-dll-directory ../weasyprint-native/onedir/weasyprint/_internal
```

`QA_POSTGRES_URL` must already be set. The runner neither starts PostgreSQL nor
connects to Railway. The optional DLL argument is for Windows; on other platforms
use the normal WeasyPrint system dependencies. This command requires a real PDF
render and a successful restore. It produces JSON, JUnit, a synthetic PDF and
the byte-preserved HTML report restored from PostgreSQL. The report directory
contains generated data only, and should remain outside the repository.
PDF dependencies follow the [WeasyPrint installation documentation](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).

Allowed settings are 15–500 completed audits, 100–10,000 bootstrap samples and
1–8 analysis slots. Requests are distributed among bounded concurrency levels
1, 2, 4 and 8; the last batch at a level can contain fewer requests. These are
test settings, not deployment defaults.

## Scenarios

- Exhaustion of the separate telemetry pool times out in one second while a
  customer-pool query still succeeds. PostgreSQL cancels a deliberately slow
  telemetry statement after two seconds; its lock timeout is 500 ms. Customer
  transaction settings remain unchanged.
- Atomic operations-counter updates from 1, 2, 4 and 8 concurrent workers.
- Exhaustion of four credits across sixteen simultaneous attempts, followed by
  sixteen duplicate unlock attempts that consume exactly one additional credit.
- Creation of the three additive operations/cost tables over populated existing
  tables, preserving every pre-existing table's row count and content hash.
- Real `pg_dump` custom-format backup and transactional `pg_restore` into a second
  empty database. Comparison covers every application table, report blobs,
  account, session, order, credit grant and code balances. The restored session
  then opens the account page through the application.
- Real synthetic uploads through the ASGI application at bounded levels
  1, 2, 4 and 8. Each upload runs the analysis, writes PostgreSQL and returns an
  accessible full HTML report. Payment factories are replaced by rejecting
  stubs, email delivery is unconfigured, and settlement in the restore test is an
  in-process synthetic Stripe event.
- The expanded run accepts 20 KiB, 1 MiB and maximum-sized 5,000,000-byte CSVs.
  Invalid CSV, CSV above the reader limit, a file above the larger equity form
  limit, full admission and an analysis queue timeout each leave credits and
  report counts unchanged. The CSV reader returns 400 above its limit; the
  equity form accepts platform reports up to twice that limit and returns 413
  above 10,000,000 bytes.
- A real paid-report PDF passes through the application's download route and
  records its SHA-256 in the issued-files ledger. The expanded backup restores
  all completed reports, their original upload blobs, HTML, account session,
  a synthetic delivered pack order and its idempotent three-credit grant.

## Interpretation

Initial local verification on 2026-10-05: all 11 PostgreSQL scenarios passed (64.61 s).
The upload scenario was rerun after correcting its median calculation and passed
(40.16 s). Its 15 uploads produced 15 full HTML reports, no internal errors and
no lost credits. Operation-counter totals matched the completed uploads.

| Simultaneous uploads | Successful reports | Observed p50 | Observed p95 |
| --- | --- | --- | --- |
| 1 | 1 | 1.409 s | 1.409 s |
| 2 | 2 | 3.356 s | 3.357 s |
| 4 | 4 | 5.554 s | 7.300 s |
| 8 | 8 | 8.936 s | 14.187 s |

These tiny batches report the median and nearest-rank p95 of their observed
requests; they do not estimate a sustained-load latency distribution.
The schema check preserved 48 existing tables. Backup/restore compared all 51
application tables and recovered the authenticated session, order, report blob
and remaining two credits in 4.623 s, using a 79,336-byte synthetic archive.
Stripe requests and emails sent were both zero.

The expanded run on the same date passed in 123.16 s. It completed all 50 reports
with zero internal errors and zero lost credits. Each of the five rejection
cases preserved the report count and consumed zero credits. Its observed
latencies were:

| Maximum simultaneous uploads | Successful reports | Observed p50 | Observed p95 |
| --- | --- | --- | --- |
| 1 | 3 | 1.646 s | 1.803 s |
| 2 | 6 | 3.828 s | 4.111 s |
| 4 | 13 | 3.640 s | 6.856 s |
| 8 | 28 | 6.514 s | 12.448 s |

The genuine PDF download returned 200 and 220,219 bytes, with SHA-256
`eb0ef66b6c674b00525076a1d14b83f0d940c95f2389489cf3590f9f8c962986`.
Its issued-file fingerprint was included in the database backup. The restore
compared all 51 application tables and recovered 50 reports, the authenticated
session, delivered synthetic pack order and 13 remaining credits in 3.658 s.
The archive was 3,181,038 bytes. The restored report HTML and uploaded CSV were
byte-identical to the originals. The stored HTML was 156,694 bytes with SHA-256
`5f7c483ed09fc505ecd3446893510718c723df83e698a0dc4fa5984782a55ff0`.
PDF binaries are download artifacts rather than database blobs; the database
restore check verifies their recorded fingerprint and the report source.
External Stripe requests and delivered emails were again zero.

After isolating the telemetry pool and bounding worker shutdown, the eleven
counter/pool/credit/schema/restore checks passed in 24.34 s on the same local
server. A new fifty-audit expanded run passed in 109.60 s: zero internal errors,
zero lost credits, all five rejection cases preserved credits, a genuine PDF
download succeeded, and restore recovered 50 reports and 13 credits with all
51 tables equal. Its restore took 3.436 s. This remains local synthetic QA,
not a Railway capacity measurement or a production-data recovery test.

The initial upload check used 500 equity rows, 100 bootstrap samples, two analysis slots
and a 30-second queue. It checks exact credit conservation, completed report
counts and persisted operation counters. Its observed durations describe that
small local workload only. It is not a Railway load test, a production capacity
estimate, a measured conversion rate, or evidence of trading returns.

The expanded scenario uses 400 equity observations per upload, 1,000 bootstrap
samples, two analysis slots and a 30-second queue. Larger file fixtures add
whitespace rows, not extra observations. They exercise byte limits and parsing,
not the computational cost of maximum-row strategies. Saturation is created
deterministically by holding local admission/analysis slots; it is not a measured
arrival-rate threshold.

HTTP transport here is in-process ASGI. There is no live web server, TLS, proxy,
network ingress, Railway CPU/memory allocation, deployment restart or volume
restore. Actual card charges, email delivery and Railway staging must be verified
separately before release. The local checks do not establish production capacity,
marketing conversion or trading returns.

## Dedicated CI

`.github/workflows/rigor-postgres-qa.yml` provisions a disposable PostgreSQL 16
service bound to loopback on Ubuntu 24.04. It uses PostgreSQL 16 client tools,
native WeasyPrint libraries and ephemeral synthetic credentials, with no
production secrets. It runs the eleven counter/pool/credit/schema/restore checks and the
50-audit expanded scenario, and uploads JSON, JUnit and the synthetic PDF.
The workflow follows GitHub's [PostgreSQL service-container configuration](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).

The workflow runs for relevant pull requests and pushes, and can be dispatched
manually. Its Linux/PostgreSQL 16 execution is a separate check from the observed
Windows/PostgreSQL 17.11 measurements above. A workflow definition does not
establish that a remote run has passed; inspect its run results after pushing.
