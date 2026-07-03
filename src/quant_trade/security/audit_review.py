from __future__ import annotations

import json
from pathlib import Path

from quant_trade.security.models import Finding, SecurityReport
from quant_trade.security.redaction import sanitize_text

REQUIRED = {"event_id", "timestamp", "event_type"}


def review_audit_logs(paths: list[Path]) -> SecurityReport:
    findings: list[Finding] = []
    seen: set[str] = set()
    for path in paths:
        candidates = list(path.rglob("*.jsonl")) if path.is_dir() else [path]
        for file in candidates:
            lines = file.read_text(encoding="utf-8", errors="ignore").splitlines()
            for line_no, line in enumerate(lines, start=1):
                if sanitize_text(line) != line:
                    findings.append(
                        Finding("audit_secret", "critical", str(file), line_no, "Secret-like value")
                    )
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    findings.append(
                        Finding("audit_json", "high", str(file), line_no, "Invalid JSON")
                    )
                    continue
                missing = REQUIRED - set(obj)
                if missing:
                    findings.append(
                        Finding("audit_required_fields", "high", str(file), line_no, str(missing))
                    )
                event_id = str(obj.get("event_id", ""))
                if not event_id:
                    findings.append(
                        Finding("audit_event_id", "high", str(file), line_no, "Missing")
                    )
                elif event_id in seen:
                    findings.append(
                        Finding("audit_event_id_duplicate", "high", str(file), line_no, "Duplicate")
                    )
                seen.add(event_id)
                if "T" not in str(obj.get("timestamp", "")):
                    findings.append(
                        Finding("audit_timestamp", "high", str(file), line_no, "Not ISO-like")
                    )
    status = "fail" if any(f.severity == "critical" for f in findings) else "pass"
    return SecurityReport(status=status, findings=findings)
