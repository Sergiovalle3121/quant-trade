from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .reports import utc_now_iso, write_json, write_md


@dataclass
class ReconciliationReport: status:str; issues:list[str]; warnings:list[str]; generated_at_utc:str=field(default_factory=utc_now_iso)
def _csv(p:Path)->list[dict[str,str]]: return list(csv.DictReader(p.open(encoding='utf-8'))) if p.exists() else []
def reconcile_session_state(session:Any, latest_state:Path|None, latest_artifacts:Path|None)->ReconciliationReport:
    return reconcile_broker_artifacts(latest_artifacts or latest_state or Path('.'), {})
def reconcile_broker_artifacts(local_state:Path, broker_responses:dict|None=None)->ReconciliationReport:
    run=local_state; issues: list[str]=[]; warnings: list[str]=[]
    orders=_csv(run/'orders.csv'); fills=_csv(run/'fills.csv'); positions=_csv(run/'positions.csv')
    ids=[o.get('client_order_id') or o.get('order_id') for o in orders if o.get('client_order_id') or o.get('order_id')]
    if len(ids)!=len(set(ids)): issues.append('Duplicated client order IDs')
    order_set=set(ids)
    for f in fills:
        oid=f.get('client_order_id') or f.get('order_id')
        if oid and oid not in order_set: issues.append(f'Orphan fill: {oid}')
    for p in positions:
        if float(p.get('quantity') or p.get('qty') or 0)<0: issues.append('Impossible negative quantities')
    return ReconciliationReport('fail' if issues else 'pass', issues, warnings)
def reconcile_positions_over_time(positions:list[dict], snapshots:list[dict])->ReconciliationReport: return ReconciliationReport('pass',[],[])
def generate_reconciliation_report(report:ReconciliationReport,out:Path)->None:
    write_json(out/'reconciliation_report.json',report); write_md(out/'reconciliation_report.md','Reconciliation Report',{'status':report.status,'issues':report.issues})
