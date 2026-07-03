from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from .reports import write_json


def _safe_files(root:Path):
    for p in root.rglob('*'):
        if p.is_file() and p.name!='.env' and not p.name.endswith('.env'): yield p
def create_artifacts_index(run_dir:Path)->dict:
    files=[]
    for p in _safe_files(run_dir): files.append({'path':str(p.relative_to(run_dir)),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size})
    return {'files':files}
def archive_run_artifacts(run_dir:Path, archive_dir:Path)->Path:
    archive_dir.mkdir(parents=True,exist_ok=True); idx=create_artifacts_index(run_dir); write_json(run_dir/'artifacts_index.json',idx); dest=archive_dir/f'{run_dir.name}.zip'
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as z:
        for p in _safe_files(run_dir): z.write(p,p.relative_to(run_dir))
    return dest
def verify_archive(archive_path:Path)->bool: return zipfile.is_zipfile(archive_path)
def apply_retention_policy(root:Path, keep_last_n:int, keep_days:int, confirm_delete:bool=False)->dict:
    dirs=sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p:p.stat().st_mtime, reverse=True) if root.exists() else []
    candidates=dirs[keep_last_n:]
    if confirm_delete:
        for p in candidates:
            for f in p.rglob('*'):
                if f.is_file(): f.unlink()
            for d in sorted([x for x in p.rglob('*') if x.is_dir()], reverse=True): d.rmdir()
            p.rmdir()
    return {'delete_required_confirmation':not confirm_delete,'candidates':[str(p) for p in candidates]}
