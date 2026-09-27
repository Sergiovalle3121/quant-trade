"""Local synthetic admission smoke; no network or Stripe contact.

Run from the repository root with ``python tools/rigor_load_smoke.py --work-dir ../work``.
The caller must supply a scratch directory, and stdout is aggregate JSON only.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import platform
import sys
import tempfile
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from quant_trade.audit.settings import AuditSettings
from quant_trade.audit.store import make_store
from quant_trade.audit.web import create_app


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("page_fault_count", ctypes.c_ulong),
        ("peak_working_set", ctypes.c_size_t),
        ("working_set", ctypes.c_size_t),
        ("quota_peak_paged_pool", ctypes.c_size_t),
        ("quota_paged_pool", ctypes.c_size_t),
        ("quota_peak_nonpaged_pool", ctypes.c_size_t),
        ("quota_nonpaged_pool", ctypes.c_size_t),
        ("pagefile_usage", ctypes.c_size_t),
        ("peak_pagefile_usage", ctypes.c_size_t),
    ]


def memory_bytes() -> int:
    if os.name != "nt":
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(peak if sys.platform == "darwin" else peak * 1024)
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_ulong,
    ]
    process = ctypes.windll.kernel32.GetCurrentProcess()
    if not ctypes.windll.psapi.GetProcessMemoryInfo(
        process, ctypes.byref(counters), ctypes.sizeof(counters)
    ):
        raise OSError("GetProcessMemoryInfo failed")
    return int(counters.working_set)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def synthetic_curve() -> bytes:
    rows = ["timestamp,equity"]
    equity = 10000.0
    start = date(2020, 1, 1)
    for index in range(320):
        equity *= 1.0 + 0.0007 + 0.004 * math.sin(index * 1.713)
        rows.append(f"{start + timedelta(days=index)},{equity:.6f}")
    return ("\n".join(rows) + "\n").encode()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    run_at = datetime.now(UTC).isoformat()
    payload = synthetic_curve()
    with tempfile.TemporaryDirectory(prefix="rigor-load-", dir=work_dir) as scratch:
        db_path = Path(scratch) / "audit.db"
        settings = AuditSettings(
            database_url=f"sqlite:///{db_path}",
            bootstrap_samples=100,
            max_uploads_per_hour_per_ip=100,
            max_concurrent_audits=2,
            audit_queue_seconds=1,
        )
        app = create_app(settings, make_store(settings.database_url))
        durations: dict[str, list[float]] = {"landing": [], "upload": [], "pdf": []}
        statuses: dict[str, Counter[int]] = {key: Counter() for key in durations}
        durations_by_status: dict[str, dict[int, list[float]]] = {key: {} for key in durations}
        completed: list[tuple[str, str]] = []
        peak_rss = memory_bytes()
        stop = threading.Event()

        def watch_memory() -> None:
            nonlocal peak_rss
            while not stop.wait(0.1):
                peak_rss = max(peak_rss, memory_bytes())

        monitor = threading.Thread(target=watch_memory, daemon=True)
        monitor.start()
        cpu_start = time.process_time()
        wall_start = time.perf_counter()
        try:
            with TestClient(app) as client:

                def request(kind: str) -> tuple[str, int, float, tuple[str, str] | None]:
                    started = time.perf_counter()
                    if kind == "landing":
                        response = client.get("/?lang=es")
                    else:
                        response = client.post(
                            "/audits",
                            files={"equity": ("synthetic.csv", payload, "text/csv")},
                            data={"consent": "on"},
                            headers={"accept": "application/json"},
                        )
                    report = None
                    if kind == "upload" and response.status_code == 201:
                        body = response.json()
                        report = (body["audit_id"], body["token"])
                    return kind, response.status_code, time.perf_counter() - started, report

                with ThreadPoolExecutor(max_workers=12) as pool:
                    futures = [
                        pool.submit(request, kind) for kind in (["upload"] * 8 + ["landing"] * 12)
                    ]
                    for future in as_completed(futures):
                        kind, status, elapsed, report = future.result()
                        durations[kind].append(elapsed)
                        statuses[kind][status] += 1
                        durations_by_status[kind].setdefault(status, []).append(elapsed)
                        if report:
                            completed.append(report)

                if completed:
                    audit_id, token = completed[0]
                    app.state.store.mark_paid(
                        audit_id,
                        stripe_session_id="cs_test_synthetic",
                        at=datetime.now(UTC),
                    )
                    for _ in range(2):
                        started = time.perf_counter()
                        response = client.get(f"/audits/{audit_id}/pdf?token={token}")
                        durations["pdf"].append(time.perf_counter() - started)
                        statuses["pdf"][response.status_code] += 1
                        durations_by_status["pdf"].setdefault(response.status_code, []).append(
                            durations["pdf"][-1]
                        )
                ready = client.get("/ready")
                record_count = app.state.store.count_audits()
        finally:
            stop.set()
            monitor.join(timeout=1)
            app.state.store.engine.dispose()

        wall = time.perf_counter() - wall_start
        cpu = time.process_time() - cpu_start
        print(
            json.dumps(
                {
                    "run_at_utc": run_at,
                    "platform": platform.platform(),
                    "python": platform.python_version(),
                    "logical_cpus": os.cpu_count(),
                    "profile": {
                        "client": "in-process FastAPI TestClient, no external network",
                        "storage": "temporary local SQLite file",
                        "stripe": "none; one PDF report marked paid directly in synthetic store",
                        "bootstrap_samples": 100,
                        "max_concurrent_audits": 2,
                        "audit_queue_seconds": 1,
                        "multipart_admission_slots": 3,
                        "submitted_in_parallel": {"upload": 8, "landing": 12},
                        "pdf_requests_after_burst": 2,
                    },
                    "synthetic_file_format": "CSV timestamp,equity; 320 daily rows",
                    "synthetic_file_bytes": len(payload),
                    "synthetic_file_sha256": hashlib.sha256(payload).hexdigest(),
                    "requests": {kind: sum(counts.values()) for kind, counts in statuses.items()},
                    "status_counts": {kind: dict(counts) for kind, counts in statuses.items()},
                    "latency_seconds": {
                        kind: {
                            "p50": percentile(samples, 0.5),
                            "p95": percentile(samples, 0.95),
                        }
                        for kind, samples in durations.items()
                    },
                    "latency_by_status_seconds": {
                        kind: {
                            str(status): {
                                "p50": percentile(samples, 0.5),
                                "p95": percentile(samples, 0.95),
                            }
                            for status, samples in groups.items()
                        }
                        for kind, groups in durations_by_status.items()
                    },
                    "cpu_seconds": cpu,
                    "wall_seconds": wall,
                    "peak_process_rss_bytes": peak_rss,
                    "database_bytes": db_path.stat().st_size,
                    "completed_audits": record_count,
                    "readiness_status": ready.status_code,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
