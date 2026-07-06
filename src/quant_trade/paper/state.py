from __future__ import annotations

import json
from pathlib import Path

from quant_trade.paper.models import PaperFill, PaperOrder, PaperPosition, PaperSessionState


def save_state(path: Path, state: PaperSessionState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")


def load_state(path: Path) -> PaperSessionState:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["positions"] = {k: PaperPosition(**v) for k, v in raw.get("positions", {}).items()}
    raw["open_orders"] = [PaperOrder(**o) for o in raw.get("open_orders", [])]
    raw["fills"] = [PaperFill(**f) for f in raw.get("fills", [])]
    return PaperSessionState(**raw)
