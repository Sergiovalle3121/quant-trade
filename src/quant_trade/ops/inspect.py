from __future__ import annotations

import json
from pathlib import Path


def inspect_run(run_dir:Path)->dict:
    if not run_dir.exists(): return {'status':'fail','warnings':['run dir missing'],'files_found':[],'recommended_next_command':'quant-trade ops validate'}
    files=[p.name for p in run_dir.iterdir() if p.is_file()]; metrics={}; warnings=[]
    if (run_dir/'paper_metrics.json').exists():
        try: metrics=json.loads((run_dir/'paper_metrics.json').read_text(encoding='utf-8'))
        except json.JSONDecodeError: warnings.append('Malformed paper_metrics.json')
    kind='paper_run' if 'paper_metrics.json' in files else 'unknown'
    return {'status':'pass' if not warnings else 'warning','detected_artifact_type':kind,'files_found':files,'key_metrics':metrics,'warnings':warnings,'recommended_next_command':'quant-trade ops validate-session'}
def inspect_session(session, artifacts)->dict: return {'session_id':session.session_id,'latest_artifacts':str(artifacts) if artifacts else None,'recommended_next_command':'quant-trade ops run-cycle'}
