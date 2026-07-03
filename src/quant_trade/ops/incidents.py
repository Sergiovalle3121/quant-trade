from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .alerts import Alert
from .reports import utc_now_iso, write_json, write_md

STATUSES={'open','investigating','mitigated','resolved','false_positive'}
@dataclass
class Incident:
    incident_id:str; created_at_utc:str; updated_at_utc:str; session_id:str; severity:str; status:str; title:str; description:str; root_cause:str=''; actions_taken:list[str]=field(default_factory=list); linked_alert_ids:list[str]=field(default_factory=list); linked_run_ids:list[str]=field(default_factory=list); owner:str='ops'; resolution_notes:str=''
def create_incident_from_alert(alert:Alert)->Incident: return Incident(f"incident_{alert.alert_id}",utc_now_iso(),utc_now_iso(),alert.session_id,alert.severity,'open',alert.title,alert.message,linked_alert_ids=[alert.alert_id])
def _path(root:Path)->Path: return root/'incidents.jsonl'
def save_incident(root:Path,inc:Incident)->None: root.mkdir(parents=True,exist_ok=True); _path(root).open('a',encoding='utf-8').write(json.dumps(asdict(inc))+'\n')
def list_incidents(root:Path)->list[Incident]:
    if not _path(root).exists(): return []
    return [Incident(**json.loads(line)) for line in _path(root).read_text(encoding='utf-8').splitlines() if line.strip()]
def update_incident(root:Path,incident_id:str,status:str,notes:str='')->Incident:
    if status not in STATUSES: raise ValueError(f'Invalid incident status: {status}')
    items=list_incidents(root); found=None
    for i in items:
        if i.incident_id==incident_id: i.status=status; i.updated_at_utc=utc_now_iso(); i.resolution_notes=notes; found=i
    if found is None: raise ValueError(f'Unknown incident: {incident_id}')
    root.mkdir(parents=True,exist_ok=True); _path(root).write_text('\n'.join(json.dumps(asdict(i)) for i in items)+'\n',encoding='utf-8'); return found
def generate_incident_report(root:Path,out:Path)->None:
    items=list_incidents(root); write_json(out/'incident_report.json',[asdict(i) for i in items]); write_md(out/'incident_report.md','Incident Report',{'incidents':[asdict(i) for i in items]})
