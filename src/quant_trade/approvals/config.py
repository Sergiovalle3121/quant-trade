from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ApprovalWorkflowConfig(BaseModel):
    run_id: str = "local"
    output_dir: str = "outputs/approvals"
    default_ttl_hours: int = 24
    required_reviewers: list[str] = Field(default_factory=lambda: ["Sergio"])
    policy_path: str = "configs/approvals/approval_policy_conservative.yaml"

    @property
    def artifact_dir(self) -> Path:
        return Path(self.output_dir) / self.run_id


def load_workflow_config(path: Path) -> ApprovalWorkflowConfig:
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return ApprovalWorkflowConfig(**data)


def load_policy(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
