from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SECRET_KEYS=("secret","token","key","password","credential","webhook")
def utc_now_iso()->str: return datetime.now(UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
def run_id(prefix:str='ops')->str: return f"{prefix}_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
def to_plain(v:Any)->Any:
    if is_dataclass(v) and not isinstance(v, type): return {k:to_plain(x) for k,x in asdict(v).items()}
    if isinstance(v,dict): return {str(k):to_plain(x) for k,x in v.items()}
    if isinstance(v,(list,tuple)): return [to_plain(x) for x in v]
    if isinstance(v,Path): return str(v)
    return v
def redact(value:Any)->Any:
    if isinstance(value,dict):
        return {k:("[REDACTED]" if any(s in k.lower() for s in SECRET_KEYS) else redact(v)) for k,v in value.items()}
    if isinstance(value,list): return [redact(v) for v in value]
    if isinstance(value,str):
        out=value
        for marker in ("api_key=", "token=", "secret=", "password="):
            if marker in out.lower(): out='[REDACTED]'
        return out
    return value
def write_json(path:Path,data:Any)->Path:
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(redact(to_plain(data)),indent=2,sort_keys=True),encoding='utf-8'); return path
def write_md(path:Path,title:str,sections:dict[str,Any])->Path:
    lines=[f"# {title}","","Paper trading / dry-run only. No live trading.",""]
    for k,v in sections.items(): lines += [f"## {k}", "", json.dumps(redact(to_plain(v)),indent=2) if not isinstance(v,str) else v, ""]
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text('\n'.join(lines),encoding='utf-8'); return path
def write_csv(path:Path, rows:list[dict[str,Any]])->Path:
    path.parent.mkdir(parents=True,exist_ok=True); keys=sorted({k for r in rows for k in r}) or ['message']
    with path.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=keys); w.writeheader(); w.writerows([{k:redact(r.get(k,'')) for k in keys} for r in rows])
    return path
