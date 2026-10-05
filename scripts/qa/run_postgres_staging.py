"""Run a bounded, opt-in local PostgreSQL/ASGI scenario with real PDF and restore.

QA_POSTGRES_URL must already point to a disposable administrator account on
127.0.0.1:<explicit port>/postgres. The URL is never a CLI argument or printed.
This runner neither starts PostgreSQL nor connects to Railway or a broker.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy.engine import make_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audits", type=int, default=50)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--slots", type=int, default=2)
    parser.add_argument("--pg-bin", type=Path, required=True)
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--pdf-dll-directory", type=Path)
    args = parser.parse_args()
    if (
        not 15 <= args.audits <= 500
        or not 100 <= args.bootstrap <= 10000
        or not 1 <= args.slots <= 8
    ):
        parser.error("audits must be 15..500, bootstrap 100..10000, slots 1..8")
    value = os.environ.get("QA_POSTGRES_URL", "")
    if not value:
        parser.error("set QA_POSTGRES_URL to a disposable loopback PostgreSQL admin URL")
    url = make_url(value)
    if (
        url.get_backend_name() != "postgresql"
        or url.host != "127.0.0.1"
        or not url.port
        or url.database != "postgres"
    ):
        parser.error("QA_POSTGRES_URL must target 127.0.0.1:<explicit port>/postgres")
    suffix = ".exe" if os.name == "nt" else ""
    for name in ("pg_dump", "pg_restore"):
        if not (args.pg_bin / (name + suffix)).is_file():
            parser.error(f"{name} is missing from --pg-bin")
    if args.pdf_dll_directory and not args.pdf_dll_directory.is_dir():
        parser.error("--pdf-dll-directory must exist")
    root = Path(__file__).resolve().parents[2]
    target = args.report_dir.resolve()
    target.mkdir(parents=True, exist_ok=True)
    evidence = target / "postgres-load.json"
    # A skipped test must not borrow evidence from an earlier successful run.
    evidence.unlink(missing_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "QA_UPLOAD_COUNT": str(args.audits),
            "QA_BOOTSTRAP_SAMPLES": str(args.bootstrap),
            "QA_AUDIT_SLOTS": str(args.slots),
            "QA_EXTENDED_STAGING": "true",
            "QA_REQUIRE_PDF": "true",
            "QA_PG_BIN": str(args.pg_bin.resolve()),
            "QA_REPORT_DIR": str(target),
        }
    )
    if args.pdf_dll_directory:
        environment["WEASYPRINT_DLL_DIRECTORIES"] = str(args.pdf_dll_directory.resolve())
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_audit_ops_postgres.py",
            "-k",
            "bounded_upload",
            "--basetemp",
            str(target / "pytest-temp"),
            "--junitxml",
            str(target / "staging-junit.xml"),
            "-q",
            "-ra",
        ],
        cwd=root,
        env=environment,
        check=False,
    )
    if result.returncode:
        return result.returncode
    if not evidence.is_file():
        raise RuntimeError("staging returned without evidence; it may have been skipped")
    measured = json.loads(evidence.read_text(encoding="utf-8"))
    if (
        measured.get("uploads") != args.audits
        or not measured.get("pdf", {}).get("tested")
        or not measured.get("real_report_restore", {}).get("tested")
    ):
        raise RuntimeError("staging did not complete the requested upload and PDF scenario")
    print(f"Local PostgreSQL: {args.audits} completed reports; evidence: {evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
