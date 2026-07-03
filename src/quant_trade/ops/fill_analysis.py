from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median

from .reports import write_csv, write_json, write_md


@dataclass
class FillAnalysis: number_of_orders:int=0; number_of_fills:int=0; fill_rate:float=0; rejected_rate:float=0; partial_fill_count:int=0; average_slippage_bps:float=0; median_slippage_bps:float=0; max_slippage_bps:float=0; total_estimated_slippage_cost:float=0; total_commissions_or_fees:float=0; planned_notional:float=0; filled_notional:float=0; missing_fill_count:int=0; late_fill_count:int=0; unexpected_symbol_count:int=0; warnings:list[str]|None=None
def _csv(p:Path)->list[dict[str,str]]:
    return list(csv.DictReader(p.open(encoding='utf-8'))) if p.exists() else []
def analyze_fills(run_dir:Path)->FillAnalysis:
    orders=_csv(run_dir/'orders.csv'); fills=_csv(run_dir/'fills.csv'); by_order={f.get('order_id') or f.get('client_order_id'):f for f in fills}
    slips=[]; fees=0.0; filled=0.0; planned=0.0
    for o in orders:
        qty=abs(float(o.get('quantity') or o.get('qty') or 0)); px=float(o.get('expected_price') or o.get('limit_price') or o.get('price') or 0); planned += qty*px
        f=by_order.get(o.get('order_id') or o.get('client_order_id'))
        if f:
            fp=float(f.get('fill_price') or f.get('price') or px or 0); fq=abs(float(f.get('quantity') or f.get('qty') or qty)); filled += fp*fq; fees += float(f.get('commission') or f.get('fees') or 0)
            if px: slips.append((fp-px)/px*10000)
    rejected=sum(1 for o in orders if o.get('status','').lower()=='rejected')
    return FillAnalysis(len(orders),len(fills),len(fills)/len(orders) if orders else 0,rejected/len(orders) if orders else 0,0,mean(slips) if slips else 0,median(slips) if slips else 0,max([abs(s) for s in slips], default=0),sum(slips) if slips else 0,fees,planned,filled,max(0,len(orders)-rejected-len(fills)),0,0,[] if fills else ['Actual broker fills unavailable; analyzing simulated/no-fill artifacts only.'])
def compare_planned_vs_filled(run_dir:Path)->dict: return asdict(analyze_fills(run_dir))
def generate_fill_report(analysis:FillAnalysis,out:Path)->None:
    write_json(out/'fill_analysis.json',analysis); write_csv(out/'fill_analysis.csv',[asdict(analysis)]); write_md(out/'fill_analysis.md','Fill Analysis',{'analysis':analysis})
