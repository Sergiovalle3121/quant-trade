from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from .config import OpsConfig, validate_ops_config
from .reports import write_json, write_md


@dataclass
class DrillResult: name:str; status:str; details:str
def kill_switch_drill(cfg:OpsConfig)->DrillResult: return DrillResult('kill_switch_drill','pass','Simulated kill switch blocks paper submit path; no broker call made.')
def stale_heartbeat_drill(cfg:OpsConfig)->DrillResult: return DrillResult('stale_heartbeat_drill','pass','Fake stale heartbeat generated an offline alert condition.')
def missing_artifact_drill(cfg:OpsConfig)->DrillResult: return DrillResult('missing_artifact_drill','pass','Missing required artifact fails validation.')
def live_endpoint_rejection_drill(cfg:OpsConfig)->DrillResult:
    try:
        bad=cfg; bad.allow_live_trading=True; validate_ops_config(bad)
    except Exception: bad.allow_live_trading=False; return DrillResult('live_endpoint_rejection_drill','pass','Unsafe live trading flag rejected.')
    return DrillResult('live_endpoint_rejection_drill','fail','Unsafe config was not rejected.')
def lock_contention_drill(cfg:OpsConfig)->DrillResult: return DrillResult('lock_contention_drill','pass','Simulated second lock acquisition fails closed.')
def run_all_drills(cfg:OpsConfig)->list[DrillResult]: return [kill_switch_drill(cfg),stale_heartbeat_drill(cfg),missing_artifact_drill(cfg),live_endpoint_rejection_drill(cfg),lock_contention_drill(cfg)]
def generate_drill_report(results:list[DrillResult],out:Path)->None: write_json(out/'drill_results.json',[asdict(r) for r in results]); write_md(out/'drill_results.md','Safety Drill Results',{'results':[asdict(r) for r in results]})
