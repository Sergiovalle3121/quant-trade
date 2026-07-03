from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path

from .reports import utc_now_iso, write_json, write_md


@dataclass
class ReadinessPolicy:
    min_calendar_days_observed:int=1; min_success_rate:float=0.8; max_critical_incidents:int=0; max_open_incidents:int=0; max_drawdown_pct:float=20; max_rejected_order_rate:float=0.1; require_kill_switch_drill_passed:bool=True; require_reconciliation_passed:bool=True; require_fill_analysis:bool=True; require_no_stale_heartbeats:bool=True; require_dashboard_generated:bool=True; require_manual_review_notes:bool=False
@dataclass
class ReadinessReport: readiness_status:str; real_money_ready:bool; blocking_issues:list[str]; warnings:list[str]; evidence:dict; generated_at_utc:str=field(default_factory=utc_now_iso)
def evaluate_ops_readiness(session, validation_reports:list[dict], reliability_metrics, incidents:list, drills:list, policy:ReadinessPolicy, manual_review_notes:str='')->ReadinessReport:
    issues: list[str]=[]; warnings: list[str]=[]; success=getattr(reliability_metrics,'success_rate',0)
    if success < policy.min_success_rate: issues.append('Reliability success rate below policy')
    if not validation_reports: issues.append('Missing validation evidence')
    if any(r.get('status')=='fail' for r in validation_reports): issues.append('Validation failure present')
    if policy.require_manual_review_notes and not manual_review_notes: issues.append('Manual review notes required')
    if policy.require_kill_switch_drill_passed and not any(getattr(d,'name',d.get('name',''))=='kill_switch_drill' and getattr(d,'status',d.get('status',''))=='pass' for d in drills): issues.append('Kill switch drill evidence missing')
    open_inc=sum(1 for i in incidents if getattr(i,'status',i.get('status','')) in {'open','investigating'})
    if open_inc>policy.max_open_incidents: issues.append('Too many open incidents')
    return ReadinessReport('not_ready' if issues else 'paper_ops_ready',False,issues,warnings,{'session_id':getattr(session,'session_id',str(session)),'success_rate':success})
def generate_readiness_report(report:ReadinessReport,out:Path)->None: write_json(out/'readiness_report.json',report); write_md(out/'readiness_report.md','Operational Readiness',{'report':asdict(report)})
