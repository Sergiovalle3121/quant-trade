# Local synthetic load baseline — 2026-09-27

The reproducible runner is [`tools/rigor_load_smoke.py`](../../../tools/rigor_load_smoke.py).
The timestamped aggregate result is
[`load-smoke-2026-09-27.json`](load-smoke-2026-09-27.json). It contains no
customer file, report token, payment key or external request.

From the repository root, after `python -m pip install -e ".[dev,web]"`:

```powershell
# Windows only: point to the MSYS2 UCRT64 Pango DLL folder installed per
# docs/AUDIT_SAAS.md. Use the actual local folder; no path is committed.
$env:WEASYPRINT_DLL_DIRECTORIES = '<MSYS2-root>\ucrt64\bin'
.venv\Scripts\python.exe tools\rigor_load_smoke.py --work-dir ..\ops-gates `
  > docs\launch\evidence\load-smoke-2026-09-27.json
```

On Linux, omit the DLL variable and use the environment's Python executable.
The script uses an in-process FastAPI `TestClient`; it never contacts Stripe,
Railway, a public site or a mail provider. It creates one temporary SQLite
database under `--work-dir`, generates a 7,697-byte, 320-row equity CSV, sends
8 uploads and 12 landing requests concurrently, then fetches a synthetic paid
report's PDF twice. The synthetic paid flag is set directly in the local
store; this is **not** a payment test. Config: 100 bootstrap samples, 2 audit
slots, 1-second audit queue and 3 multipart admissions per process.

Measured on a Huawei KLVL-WXXW, AMD Ryzen 5 5500U (6 cores, 12 threads),
7,896,625,152 bytes physical RAM, Windows 11 build 26200, Python 3.12.10,
WeasyPrint 70 with MSYS2 UCRT64 Pango. The JSON records the UTC run time.
All 12 landing requests and both PDF requests returned 200. Two uploads
returned 201; six returned controlled 503 responses, and only two audits
were persisted. Successful upload p50/p95 were 2.78/2.93 seconds with only
two samples. Landing p50/p95 were 0.11/0.16 seconds with 12 samples. The run
used 9.56 CPU-seconds over 7.32 wall-seconds and reached 251,387,904 bytes
peak process working set. PDF p95 was 4.10 seconds with only two samples.

This is a small functional overload baseline: 503 responses are expected when
the local admission/queue is saturated and the client must retry. Its p95s
are descriptive for this run only. It does not establish success under 100 or
1,000 daily registrations or purchases, production infrastructure capacity,
large file performance, a durable queue, or payment/webhook throughput. The
wide campaign capacity gate remains **NO-GO** pending staging load and cost
measurements using a controlled mix of realistic synthetic file sizes and
flows.
