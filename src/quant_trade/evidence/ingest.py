"""Offline artifact ingestion for evidence tracking."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from quant_trade.evidence.config import EvidenceConfig
from quant_trade.evidence.database import connect, initialize_database, insert_artifact
from quant_trade.evidence.models import EvidenceArtifact, EvidenceIngestReport, output_run_dir

SECRET_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in ["api[_-]?key", "secret", "token", "password", "private[_-]?key"]
]
TEXT_SUFFIXES = {".json", ".yaml", ".yml", ".csv", ".md", ".txt", ".html"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def looks_secret(path: Path, text: str) -> bool:
    haystack = f"{path.name}\n{text[:4096]}"
    return any(pattern.search(haystack) for pattern in SECRET_PATTERNS)


def sanitize_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if (
            any(pattern.search(str(key)) for pattern in SECRET_PATTERNS)
            or isinstance(value, str)
            and any(pattern.search(value) for pattern in SECRET_PATTERNS)
        ):
            clean[key] = "[REDACTED]"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            clean[key] = value
    return clean


def detect_artifact_type(path: Path, metadata: dict[str, Any]) -> str:
    text = "/".join(part.lower() for part in path.parts) + " " + path.name.lower()
    if "incident" in text:
        return "incident"
    if "alert" in text:
        return "alert"
    if "stress" in text:
        return "stress"
    if "allocation" in text:
        return "allocation"
    if "decision" in text:
        return "decision"
    if "review" in text:
        return "trial_review"
    if "trial" in text or "paper" in text:
        return "paper_trial"
    if "ops" in text or "readiness" in text:
        return "ops"
    if "research" in text or "backtest" in text or "metrics" in text:
        return "research"
    return str(metadata.get("artifact_type", "artifact"))


def infer_strategy_id(path: Path, metadata: dict[str, Any]) -> str:
    for key in ("strategy_id", "strategy", "strategy_name", "name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip())[:80]
    for part in reversed(path.parts):
        if part not in {
            "outputs",
            "research",
            "trials",
            "ops",
            "stress",
            "allocation",
            "incidents",
            "alerts",
        }:
            return re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(part).stem)[:80] or "unknown_strategy"
    return "unknown_strategy"


def read_metadata(path: Path, max_bytes: int) -> tuple[dict[str, Any], bool]:
    if path.stat().st_size > max_bytes or path.suffix.lower() not in TEXT_SUFFIXES:
        return {}, False
    text = path.read_text(encoding="utf-8", errors="replace")
    if looks_secret(path, text):
        return {}, True
    if path.suffix.lower() == ".json":
        try:
            loaded = json.loads(text)
            return (sanitize_metadata(loaded) if isinstance(loaded, dict) else {}), False
        except json.JSONDecodeError:
            return {"malformed": True}, False
    return {"preview": text[:500]}, False


def ingest_path(config: EvidenceConfig, path: Path) -> EvidenceIngestReport:
    initialize_database(config.database_path)
    run_id = f"evidence_{int(time.time())}"
    out_dir = output_run_dir(config.output_dir, run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    ingested = 0
    malformed: list[str] = []
    skipped: list[str] = []
    with connect(config.database_path) as conn:
        for file_path in sorted(files):
            metadata, is_secret = read_metadata(file_path, config.max_artifact_bytes)
            if is_secret:
                skipped.append(str(file_path))
                continue
            if metadata.get("malformed"):
                malformed.append(str(file_path))
            artifact = EvidenceArtifact(
                path=str(file_path),
                artifact_type=detect_artifact_type(file_path, metadata),
                sha256=sha256_file(file_path),
                strategy_id=infer_strategy_id(file_path, metadata),
                metadata=metadata,
            )
            insert_artifact(conn, artifact)
            ingested += 1
        conn.commit()
    report = EvidenceIngestReport(
        run_id,
        str(path),
        len(files),
        ingested,
        malformed,
        skipped,
        str(out_dir / "ingest_report.json"),
    )
    Path(report.output_path).write_text(json.dumps(report.__dict__, indent=2), encoding="utf-8")
    return report
