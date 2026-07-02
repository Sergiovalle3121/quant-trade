from __future__ import annotations

import json
from pathlib import Path

from quant_trade.paper.models import PaperPosition, PaperSessionState


def save_state(path: Path, state: PaperSessionState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")


def load_state(path: Path) -> PaperSessionState:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["positions"] = {k: PaperPosition(**v) for k, v in raw.get("positions", {}).items()}
    return PaperSessionState(**raw)
