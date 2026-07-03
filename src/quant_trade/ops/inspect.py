from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def inspect_run(run_dir: Path) -> dict[str, Any]:
    if not run_dir.exists():
        return {
            "status": "fail",
            "warnings": ["run dir missing"],
            "files_found": [],
            "recommended_next_command": "quant-trade ops validate",
        }
    files = [path.name for path in run_dir.iterdir() if path.is_file()]
    metrics: dict[str, Any] = {}
    warnings: list[str] = []
    if (run_dir / "paper_metrics.json").exists():
        try:
            metrics = json.loads((run_dir / "paper_metrics.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warnings.append("Malformed paper_metrics.json")
    artifact_type = "paper_run" if "paper_metrics.json" in files else "unknown"
    return {
        "status": "pass" if not warnings else "warning",
        "detected_artifact_type": artifact_type,
        "files_found": files,
        "key_metrics": metrics,
        "warnings": warnings,
        "recommended_next_command": "quant-trade ops validate-session",
    }


def inspect_session(session: object, artifacts: Path | None) -> dict[str, Any]:
    return {
        "session_id": getattr(session, "session_id", str(session)),
        "latest_artifacts": str(artifacts) if artifacts else None,
        "recommended_next_command": "quant-trade ops run-cycle",
    }
