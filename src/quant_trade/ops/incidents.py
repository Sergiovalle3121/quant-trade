from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .alerts import Alert
from .reports import utc_now_iso, write_json, write_md

STATUSES = {"open", "investigating", "mitigated", "resolved", "false_positive"}


@dataclass
class Incident:
    incident_id: str
    created_at_utc: str
    updated_at_utc: str
    session_id: str
    severity: str
    status: str
    title: str
    description: str
    root_cause: str = ""
    actions_taken: list[str] = field(default_factory=list)
    linked_alert_ids: list[str] = field(default_factory=list)
    linked_run_ids: list[str] = field(default_factory=list)
    owner: str = "ops"
    resolution_notes: str = ""


def create_incident_from_alert(alert: Alert) -> Incident:
    return Incident(
        incident_id=f"incident_{alert.alert_id}",
        created_at_utc=utc_now_iso(),
        updated_at_utc=utc_now_iso(),
        session_id=alert.session_id,
        severity=alert.severity,
        status="open",
        title=alert.title,
        description=alert.message,
        linked_alert_ids=[alert.alert_id],
    )


def _path(root: Path) -> Path:
    return root / "incidents.jsonl"


def save_incident(root: Path, incident: Incident) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with _path(root).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(incident)) + "\n")


def list_incidents(root: Path) -> list[Incident]:
    path = _path(root)
    if not path.exists():
        return []
    return [Incident(**json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()]


def update_incident(root: Path, incident_id: str, status: str, notes: str = "") -> Incident:
    if status not in STATUSES:
        raise ValueError(f"Invalid incident status: {status}")
    incidents = list_incidents(root)
    updated: Incident | None = None
    for incident in incidents:
        if incident.incident_id == incident_id:
            incident.status = status
            incident.updated_at_utc = utc_now_iso()
            incident.resolution_notes = notes
            updated = incident
    if updated is None:
        raise ValueError(f"Unknown incident: {incident_id}")
    root.mkdir(parents=True, exist_ok=True)
    _path(root).write_text(
        "\n".join(json.dumps(asdict(incident)) for incident in incidents) + "\n",
        encoding="utf-8",
    )
    return updated


def generate_incident_report(root: Path, out: Path) -> None:
    incidents = [asdict(incident) for incident in list_incidents(root)]
    write_json(out / "incident_report.json", incidents)
    write_md(out / "incident_report.md", "Incident Report", {"incidents": incidents})
