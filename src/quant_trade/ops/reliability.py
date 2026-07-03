from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean

from .reports import utc_now_iso, write_csv, write_json, write_md


@dataclass
class ReliabilityMetrics:
    total_runs:int=0; successful_runs:int=0; failed_runs:int=0; warning_runs:int=0; success_rate:float=0; rolling_7d_success_rate:float=0; rolling_30d_success_rate:float=0; average_duration_seconds:float=0; p95_duration_seconds:float=0; stale_heartbeat_count:int=0; lock_failure_count:int=0; broker_api_error_count:int=0; risk_rejection_count:int=0; kill_switch_count:int=0; incident_count:int=0; missing_artifact_count:int=0; data_freshness_warnings:int=0; last_success_at:str|None=None; last_failure_at:str|None=None; generated_at_utc:str=field(default_factory=utc_now_iso)
def collect_run_summaries(artifact_roots:list[Path])->list[dict]:
    rows=[]
    for r in artifact_roots:
        if not r.exists(): continue
        for p in r.rglob('validation_report.json'):
            try: rows.append(json.loads(p.read_text(encoding='utf-8')))
            except json.JSONDecodeError: rows.append({'status':'fail','generated_at_utc':'','blocking_issues':['malformed validation report']})
    return rows
def calculate_reliability_metrics(run_summaries:list[dict], policy:dict|None=None)->ReliabilityMetrics:
    total=len(run_summaries); ok=[r for r in run_summaries if r.get('status')=='pass']; fail=[r for r in run_summaries if r.get('status')=='fail']; warn=[r for r in run_summaries if r.get('status')=='warning']
    m=ReliabilityMetrics(total, len(ok), len(fail), len(warn)); m.success_rate=(len(ok)/total if total else 0); m.rolling_7d_success_rate=m.success_rate; m.rolling_30d_success_rate=m.success_rate
    d=[float(r.get('duration_seconds',0)) for r in run_summaries if r.get('duration_seconds') is not None]; m.average_duration_seconds=mean(d) if d else 0; m.p95_duration_seconds=sorted(d)[int(.95*(len(d)-1))] if d else 0
    m.missing_artifact_count=sum(1 for r in run_summaries for i in r.get('blocking_issues',[]) if 'Missing required artifact' in str(i)); m.stale_heartbeat_count=sum(1 for r in run_summaries for w in r.get('warnings',[]) if 'heartbeat' in str(w).lower())
    m.last_success_at=max([r.get('generated_at_utc','') for r in ok], default=None); m.last_failure_at=max([r.get('generated_at_utc','') for r in fail], default=None); return m
def reliability_status(metrics:ReliabilityMetrics, policy:dict|None=None)->tuple[str,list[str]]:
    threshold=(policy or {}).get('min_success_rate_rolling_7d',0.8); issues=[]
    if metrics.total_runs and metrics.rolling_7d_success_rate<threshold: issues.append('Rolling 7d success rate below policy')
    if metrics.failed_runs: issues.append('Failed runs present')
    return ('fail' if issues else 'pass'), issues
def generate_reliability_report(metrics:ReliabilityMetrics,out:Path)->None:
    write_json(out/'reliability_metrics.json',metrics); write_md(out/'reliability_summary.md','Reliability Summary',{'metrics':metrics}); write_csv(out/'reliability_timeseries.csv',[metrics.__dict__])
