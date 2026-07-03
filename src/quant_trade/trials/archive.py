from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path


def create_trial_archive_index(trial_id: str) -> dict:
    root = Path("outputs/trials") / trial_id
    items = []
    if root.exists():
        for p in root.rglob("*"):
            if p.is_file() and ".env" not in p.name and "secret" not in p.name.lower():
                items.append({"path": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    return {"trial_id": trial_id, "files": items, "real_money_ready": False}


def archive_trial(trial_id: str) -> Path:
    idx = create_trial_archive_index(trial_id)
    out = Path("outputs/trials") / trial_id / "archive"
    out.mkdir(parents=True, exist_ok=True)
    ip = out / "archive_index.json"
    ip.write_text(json.dumps(idx, indent=2), encoding="utf-8")
    zp = out / f"{trial_id}_archive.zip"
    with zipfile.ZipFile(zp, "w") as z:
        for item in idx["files"]:
            z.write(item["path"])
        z.write(ip)
    return zp


def verify_trial_archive(trial_id: str) -> bool:
    return bool(create_trial_archive_index(trial_id)["files"])
