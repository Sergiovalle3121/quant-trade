from __future__ import annotations

from pathlib import Path

import yaml

from .models import TrialPolicy


def load_trial_policy(path: Path | str | None) -> TrialPolicy:
    if not path:
        return TrialPolicy()
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return TrialPolicy.from_dict(raw.get("policy", raw))
