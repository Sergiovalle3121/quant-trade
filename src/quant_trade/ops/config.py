from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .exceptions import OpsConfigError

MODES={'local_validation','cloud_validation','dry_run_operations','paper_operations_review'}
ENVS={'local','aws'}
@dataclass
class OpsConfig:
    ops_name:str; environment:str; mode:str; session_registry_path:Path; artifact_roots:list[Path]; state_roots:list[Path]; audit_roots:list[Path]
    dashboard_output_dir:Path; reports_output_dir:Path; incident_output_dir:Path; archive_output_dir:Path
    allow_live_trading:bool=False; real_money_enabled:bool=False; allow_paper_order_submission:bool=False; secrets_redaction_enabled:bool=True
    stale_heartbeat_minutes:int=60; max_allowed_drawdown_pct:float=20.0; max_rejected_orders_per_day:int=5; max_missing_artifacts:int=0
    min_success_rate_rolling_7d:float=0.8; min_success_rate_rolling_30d:float=0.8; require_kill_switch_test:bool=True; require_reconciliation:bool=True
    require_artifact_integrity:bool=True; require_no_critical_incidents:bool=True

def load_ops_config(path:Path)->OpsConfig:
    raw=yaml.safe_load(path.read_text(encoding='utf-8')) or {}; base=path.parent.parent.parent if path.is_absolute() else Path.cwd()
    def p(v:str)->Path: return Path(v) if Path(v).is_absolute() else base / v
    cfg=OpsConfig(**{**raw,
        'session_registry_path':p(raw['session_registry_path']),
        'artifact_roots':[p(x) for x in raw.get('artifact_roots',[])], 'state_roots':[p(x) for x in raw.get('state_roots',[])], 'audit_roots':[p(x) for x in raw.get('audit_roots',[])],
        'dashboard_output_dir':p(raw['dashboard_output_dir']), 'reports_output_dir':p(raw['reports_output_dir']), 'incident_output_dir':p(raw['incident_output_dir']), 'archive_output_dir':p(raw['archive_output_dir'])})
    validate_ops_config(cfg); return cfg

def validate_ops_config(cfg:OpsConfig)->None:
    if cfg.environment not in ENVS: raise OpsConfigError(f"Unknown environment: {cfg.environment}")
    if cfg.mode not in MODES: raise OpsConfigError(f"Unknown mode: {cfg.mode}")
    if cfg.allow_live_trading or cfg.real_money_enabled: raise OpsConfigError('Live/real-money trading is permanently disabled')
    if not (cfg.dashboard_output_dir and cfg.reports_output_dir and cfg.incident_output_dir and cfg.archive_output_dir): raise OpsConfigError('Output directories must be explicit')
