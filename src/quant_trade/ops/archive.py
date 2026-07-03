from __future__ import annotations

import hashlib
import shutil
import zipfile
from collections.abc import Iterator
from pathlib import Path

from .reports import write_json


def _safe_files(root: Path) -> Iterator[Path]:
    for path in root.rglob("*"):
        if path.is_file() and path.name != ".env" and not path.name.endswith(".env"):
            yield path


def create_artifacts_index(run_dir: Path) -> dict[str, list[dict[str, object]]]:
    files = []
    for path in _safe_files(run_dir):
        files.append(
            {
                "path": str(path.relative_to(run_dir)),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
        )
    return {"files": files}


def archive_run_artifacts(run_dir: Path, archive_dir: Path) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "artifacts_index.json", create_artifacts_index(run_dir))
    destination = archive_dir / f"{run_dir.name}.zip"
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _safe_files(run_dir):
            archive.write(path, path.relative_to(run_dir))
    return destination


def verify_archive(archive_path: Path) -> bool:
    return zipfile.is_zipfile(archive_path)


def apply_retention_policy(
    root: Path, keep_last_n: int, keep_days: int, confirm_delete: bool = False
) -> dict[str, object]:
    del keep_days
    directories = (
        sorted(
            [path for path in root.iterdir() if path.is_dir()],
            key=lambda path: path.stat().st_mtime,
        )
        if root.exists()
        else []
    )
    candidates = directories[:-keep_last_n] if keep_last_n > 0 else directories
    if confirm_delete:
        for path in candidates:
            shutil.rmtree(path)
    return {
        "delete_required_confirmation": not confirm_delete,
        "candidates": [str(path) for path in candidates],
    }
