from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .allocators import ALLOCATORS
from .config import load_allocation_config
from .correlation import load_returns, pairwise_correlation
from .dashboard import write_dashboard
from .governance import recommend_decisions
from .registry import eligible_candidates
from .reports import write_run_artifacts
from .simulator import simulate_allocation


def run_allocation(config_path: Path | str):
    cfg = load_allocation_config(config_path)
    policy = cfg["policy"]
    candidates, rejected, cand_warnings = eligible_candidates(cfg["registry_path"])
    returns = load_returns(candidates)
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    allocator = ALLOCATORS[str(cfg.get("allocator", "conservative_blend"))]
    allocation = allocator(run_id, candidates, returns, policy)
    result = simulate_allocation(allocation, returns, policy.max_pairwise_correlation)
    evidence = {c.strategy_id: c.evidence_paths for c in candidates}
    decisions = recommend_decisions(
        allocation,
        evidence,
        result.risk_report.warnings + [w for ws in cand_warnings.values() for w in ws],
    )
    out = Path(str(cfg["output_root"])) / run_id
    write_run_artifacts(
        out,
        {"config_path": str(config_path), "allocator": cfg.get("allocator")},
        candidates,
        rejected,
        result,
        pairwise_correlation(returns),
        decisions,
    )
    write_dashboard(out, result)
    return out, result, candidates, rejected
