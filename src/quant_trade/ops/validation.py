from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .reports import utc_now_iso, write_json, write_md

REQUIRED=['paper_summary.md','paper_metrics.json','final_state.json','account_snapshots.csv','orders.csv','fills.csv','positions.csv','events.csv']
@dataclass
class OpsCheck: name:str; status:str; message:str
@dataclass
class OpsValidationReport:
    run_id:str; session_id:str; status:str; checks:list[OpsCheck]; blocking_issues:list[str]; warnings:list[str]; artifact_paths:dict[str,str]; generated_at_utc:str=field(default_factory=utc_now_iso)
def _read_json(p:Path)->dict[str,Any]: return json.loads(p.read_text(encoding='utf-8'))
def _read_csv(p:Path)->list[dict[str,str]]:
    with p.open(newline='',encoding='utf-8') as f: return list(csv.DictReader(f))
def validate_artifacts(run_dir:Path, session_id:str, run_id:str='validation', max_drawdown_pct:float=20.0, max_rejected:int=5)->OpsValidationReport:
    checks=[]; issues=[]; warnings=[]; paths={}
    for name in REQUIRED:
        p=run_dir/name; paths[name]=str(p)
        if not p.exists(): issues.append(f"Missing required artifact: {name}"); checks.append(OpsCheck(name,'fail','missing'))
        else: checks.append(OpsCheck(name,'pass','found'))
    state={}; metrics={}; snaps=[]; orders=[]; fills=[]; events=[]; positions=[]
    try:
        if (run_dir/'final_state.json').exists(): state=_read_json(run_dir/'final_state.json')
        if (run_dir/'paper_metrics.json').exists(): metrics=_read_json(run_dir/'paper_metrics.json')
        for n,var in [('account_snapshots.csv','snaps'),('orders.csv','orders'),('fills.csv','fills'),('events.csv','events'),('positions.csv','positions')]:
            if (run_dir/n).exists(): locals()[var]
        snaps=_read_csv(run_dir/'account_snapshots.csv') if (run_dir/'account_snapshots.csv').exists() else []
        orders=_read_csv(run_dir/'orders.csv') if (run_dir/'orders.csv').exists() else []
        fills=_read_csv(run_dir/'fills.csv') if (run_dir/'fills.csv').exists() else []
        events=_read_csv(run_dir/'events.csv') if (run_dir/'events.csv').exists() else []
        positions=_read_csv(run_dir/'positions.csv') if (run_dir/'positions.csv').exists() else []
        checks.append(OpsCheck('parse_artifacts','pass','parseable'))
    except Exception as exc:
        issues.append(f"Malformed artifact: {exc}"); checks.append(OpsCheck('parse_artifacts','fail',str(exc)))
    if snaps and state:
        last=snaps[-1]
        if abs(float(last.get('equity',0))-float(state.get('equity',state.get('final_equity',0))))>0.01: issues.append('Final equity does not match last account snapshot')
        if abs(float(last.get('cash',0))-float(state.get('cash',0)))>0.01: issues.append('Final cash does not match last account snapshot')
    if float(metrics.get('max_drawdown', metrics.get('max_drawdown_pct',0))) > max_drawdown_pct/100: issues.append('Drawdown exceeds configured limit')
    rejected=sum(1 for o in orders if o.get('status','').lower()=='rejected')
    if rejected>max_rejected: issues.append('Rejected order count exceeds limit')
    kill_times=[e.get('timestamp','') for e in events if 'kill' in e.get('event_type',e.get('type','')).lower()]
    if kill_times:
        kt=min(kill_times)
        if any(o.get('timestamp','')>kt for o in orders): issues.append('Orders found after kill switch trigger')
    ids=[o.get('order_id') or o.get('client_order_id') for o in orders if o.get('order_id') or o.get('client_order_id')]
    if len(ids)!=len(set(ids)): issues.append('Duplicate order IDs found')
    fids=[f.get('fill_id') for f in fills if f.get('fill_id')]
    if len(fids)!=len(set(fids)): issues.append('Duplicate fill IDs found')
    if not fills: warnings.append('No fills available; simulated or no-trade run')
    status='fail' if issues else ('warning' if warnings else 'pass')
    return OpsValidationReport(run_id, session_id, status, checks, issues, warnings, paths)
def generate_validation_report(report:OpsValidationReport,out:Path)->None:
    write_json(out/'validation_report.json', report); write_md(out/'validation_report.md','Ops Validation Report',{'status':report.status,'blocking_issues':report.blocking_issues,'warnings':report.warnings})
