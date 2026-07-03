from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import OpsValidationError


@dataclass
class PaperOpsSession:
    session_id:str; display_name:str; status:str; strategy_name:str; strategy_params:dict[str,Any]; universe:list[str]; paper_config_path:str
    broker_config_path:str|None=None; cloud_config_path:str|None=None; expected_schedule:str='manual'; expected_timezone:str='UTC'; benchmark:str='cash'; owner:str='research'; risk_tier:str='validation'; max_drawdown_limit:float=0.2; max_daily_loss_limit:float=0.05; max_rejected_orders:int=5; max_stale_heartbeat_minutes:int=60; requires_broker_reconciliation:bool=True; requires_kill_switch_drill:bool=True; notes:str=''
@dataclass
class SessionRegistry: sessions:list[PaperOpsSession]=field(default_factory=list)
def load_session_registry(path:Path)->SessionRegistry:
    raw=yaml.safe_load(path.read_text(encoding='utf-8')) or {}; return SessionRegistry([PaperOpsSession(**s) for s in raw.get('sessions',[])])
def list_sessions(registry:SessionRegistry)->list[PaperOpsSession]: return registry.sessions
def get_session(registry:SessionRegistry, session_id:str)->PaperOpsSession:
    for s in registry.sessions:
        if s.session_id==session_id: return s
    raise OpsValidationError(f"Unknown paper ops session: {session_id}")
def validate_session_config(session:PaperOpsSession)->None:
    if session.status not in {'active','paused','retired','validation_only'}: raise OpsValidationError(f"Invalid session status: {session.status}")
    if not session.session_id or not session.strategy_name or not session.universe: raise OpsValidationError('Session requires id, strategy and universe')
    if session.max_drawdown_limit < 0: raise OpsValidationError('Drawdown limit must be non-negative')
def _latest_with_marker(roots:list[Path], sid:str, marker:str)->Path|None:
    c=[]
    for r in roots:
        if not r.exists(): continue
        for p in r.rglob(marker):
            if sid in str(p.parent): c.append(p.parent)
        for d in r.rglob(f"*{sid}*"):
            if d.is_dir() and (d/marker).exists(): c.append(d)
    return max(set(c), key=lambda p:p.stat().st_mtime) if c else None
def find_latest_session_artifacts(session:PaperOpsSession, artifact_roots:list[Path])->Path|None: return _latest_with_marker(artifact_roots, session.session_id, 'paper_metrics.json')
def find_latest_state(session:PaperOpsSession, state_roots:list[Path])->Path|None: return _latest_with_marker(state_roots, session.session_id, 'final_state.json')
