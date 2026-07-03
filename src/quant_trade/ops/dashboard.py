from __future__ import annotations

import html
from pathlib import Path

from .reports import redact, write_csv, write_json


def generate_dashboard(out:Path, sessions:list, reliability:dict, alerts:list|None=None, incidents:list|None=None)->Path:
    out.mkdir(parents=True,exist_ok=True); data={'safety':'Paper trading / dry-run only. No live trading.','sessions':[getattr(s,'__dict__',s) for s in sessions],'reliability':reliability,'alerts':alerts or [],'incidents':incidents or [],'recommended_actions':['Review warnings','Resolve critical alerts','Run safety drills']}
    data=redact(data); write_json(out/'dashboard.json',data); write_csv(out/'sessions.csv',data['sessions']); write_csv(out/'reliability.csv',[data['reliability']]); write_csv(out/'alerts.csv',data['alerts']); write_csv(out/'incidents.csv',data['incidents']); write_csv(out/'risk_summary.csv',[{'risk':'paper_only','real_money_ready':False}]); write_csv(out/'latest_runs.csv',[{'status':data['reliability'].get('status','unknown')}])
    sections=['Session overview','Latest run status','Reliability metrics','Risk metrics','Drawdown summary','Orders/fills summary','Fill analysis','Reconciliation status','Active alerts','Open incidents','Kill switch status','Data freshness','Artifact integrity','Readiness status','Recommended actions']
    body='<h1>Paper Trading Operations Dashboard</h1><strong>Paper trading / dry-run only. No live trading.</strong>' + ''.join(f'<h2>{html.escape(s)}</h2><pre>{html.escape(str(data))}</pre>' for s in sections)
    (out/'index.html').write_text(f'<!doctype html><html><body>{body}</body></html>',encoding='utf-8'); return out/'index.html'
