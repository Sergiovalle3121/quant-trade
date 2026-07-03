from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC
from pathlib import Path
from typing import Any


@dataclass
class Finding:
    rule_id: str
    severity: str
    path: str
    line: int
    message: str
    preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SecurityReport:
    status: str
    findings: list[Finding] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    real_money_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "findings": [f.to_dict() for f in self.findings],
            "artifacts": self.artifacts,
            "real_money_ready": False,
        }


def run_id() -> str:
    from datetime import datetime

    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def ensure_output_dir(base: Path = Path("outputs/security")) -> Path:
    out = base / run_id()
    out.mkdir(parents=True, exist_ok=True)
    return out
