"""Calibration runner of the file-consistency battery over a corpus of real
public files (never committed; ``docs/AUDIT_FORENSICS.md`` lists them).

Usage::

    python tests/forensics_corpus.py MANIFEST ROOT --out RESULT.json [--reserved] [--all]

``MANIFEST`` is a JSON list of ``{"path", "url", "sha256", "format", "group",
"genuine"}``; only genuine entries are run. Files of one ``group`` (the same
account exported on several dates) count once towards ``n``. The split is
deterministic: per family, entries sorted by SHA-256, every third one
(positions 2, 5, 8, ...) is the reserved third. Without ``--reserved`` the
calibration two thirds run; with it, the reserved third; ``--all`` runs both.

As a pytest module it is skipped unless ``FORENSICS_CORPUS_MANIFEST`` and
``FORENSICS_CORPUS_DIR`` are set, in which case it asserts that no check
answers SIGNAL on a genuine file (the calibration table is empty until a
frozen run grants a cell, so this guards the table, not the checks).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import pytest

from quant_trade.audit import importers
from quant_trade.audit.forensics import (
    CHECK_ORDER,
    STATUS_NOT_MEASURED,
    STATUS_SIGNAL,
    families,
    review,
)
from quant_trade.audit.forensics.results import ForensicResult


def split(entries: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Calibration two thirds and reserved third, per family, by SHA-256."""
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        by_family[families.family_of(entry["format"])].append(entry)
    calibration: list[dict[str, Any]] = []
    reserved: list[dict[str, Any]] = []
    for family in sorted(by_family):
        # One position per group, so both thirds hold whole accounts.
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entry in by_family[family]:
            groups[entry["group"]].append(entry)
        keyed = sorted(groups.items(), key=lambda item: min(e["sha256"] for e in item[1]))
        for position, (_group, members) in enumerate(keyed):
            (reserved if position % 3 == 2 else calibration).extend(members)
    return calibration, reserved


def run_one(path: Path, entry: dict[str, Any]) -> tuple[ForensicResult, list[str]]:
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != entry["sha256"]:
        raise ValueError(f"{path}: sha256 {digest} != manifest {entry['sha256']}")
    warnings: list[str] = []
    try:
        imported = importers.import_report(data, path.name)
        warnings = list(imported.warnings)
        currency = imported.currency
    except Exception:  # noqa: BLE001 - the battery still runs without the import
        currency = None
    result = review(
        data,
        source_format=entry["format"],
        imported_warnings=warnings,
        currency=currency,
    )
    return result, warnings


def run(manifest: Path, root: Path, *, which: str) -> dict[str, Any]:
    entries = [e for e in json.loads(manifest.read_text()) if e.get("genuine")]
    calibration, reserved = split(entries)
    chosen = {"calibration": calibration, "reserved": reserved, "all": calibration + reserved}[
        which
    ]
    files: list[dict[str, Any]] = []
    cells: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"n_files": 0, "n_groups": 0, "hits_files": 0, "hits_groups": 0, "groups": set()}
    )
    hit_groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in chosen:
        path = root / entry["path"]
        try:
            result, warnings = run_one(path, entry)
        except Exception as error:  # noqa: BLE001
            files.append({"path": entry["path"], "error": repr(error)[:200]})
            continue
        family = result.family
        record: dict[str, Any] = {
            "path": entry["path"],
            "sha256": entry["sha256"],
            "url": entry.get("url", ""),
            "format": entry["format"],
            "family": family,
            "group": entry["group"],
            "third": "reserved" if entry in reserved else "calibration",
            "rows_read": result.rows_read,
            "importer_warnings": warnings,
            "checks": {},
        }
        for check in result.checks:
            record["checks"][check.id] = {
                "status": check.status,
                "reason": check.reason,
                "hits": int(check.figure("n_hits") or 0),
                "figures": dict((k, v) for k, v, _e in check.figures),
                "examples": list(check.examples),
            }
            if check.status == STATUS_NOT_MEASURED:
                continue
            cell = cells[(check.id, family)]
            cell["n_files"] += 1
            cell["groups"].add(entry["group"])
            if int(check.figure("n_hits") or 0) > 0 or check.status == STATUS_SIGNAL:
                cell["hits_files"] += 1
                hit_groups[(check.id, family)].add(entry["group"])
        files.append(record)
    table = []
    for (check_id, family), cell in sorted(cells.items()):
        table.append(
            {
                "check": check_id,
                "family": family,
                "n_files": cell["n_files"],
                "n_groups": len(cell["groups"]),
                "hits_files": cell["hits_files"],
                "hits_groups": len(hit_groups[(check_id, family)]),
            }
        )
    return {"which": which, "files": files, "table": table}


def print_table(result: dict[str, Any]) -> None:
    print(
        f"{'check':22} {'family':14} {'files':>5} {'groups':>6} {'hit files':>9} {'hit groups':>10}"
    )
    for row in result["table"]:
        print(
            f"{row['check']:22} {row['family']:14} {row['n_files']:5d} {row['n_groups']:6d} "
            f"{row['hits_files']:9d} {row['hits_groups']:10d}"
        )
    errors = [f for f in result["files"] if "error" in f]
    if errors:
        print(f"{len(errors)} file(s) failed to run:")
        for item in errors:
            print("  ", item["path"], item["error"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--reserved", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    which = "all" if args.all else "reserved" if args.reserved else "calibration"
    result = run(args.manifest, args.root, which=which)
    print_table(result)
    if args.out:
        args.out.write_text(json.dumps(result, indent=1, sort_keys=True))
        print("written", args.out)
    return 0


MANIFEST = os.environ.get("FORENSICS_CORPUS_MANIFEST", "")
ROOT = os.environ.get("FORENSICS_CORPUS_DIR", "")


@pytest.mark.skipif(not (MANIFEST and ROOT), reason="no corpus configured")
def test_no_signal_on_genuine_files() -> None:
    result = run(Path(MANIFEST), Path(ROOT), which="all")
    signals = [
        (item["path"], check_id)
        for item in result["files"]
        if "checks" in item
        for check_id, check in item["checks"].items()
        if check["status"] == STATUS_SIGNAL
    ]
    assert signals == []
    assert set(CHECK_ORDER) >= {row["check"] for row in result["table"]}


if __name__ == "__main__":
    sys.exit(main())
