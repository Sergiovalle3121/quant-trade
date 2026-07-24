"""Trading opportunity scanner over pre-registered hypotheses.

Each hypothesis was registered in ``docs/PROFIT_HYPOTHESES_V5.md`` BEFORE any
campaign ran; the scanner only executes what was registered. Every hypothesis
appears in the leaderboard with an honest status:

- ``NOT_RUN_NO_DATASET``       — the registered dataset does not exist yet
  (the backfill attempts log is quoted as evidence when it explains why);
- ``NOT_RUN_DATASET_REJECTED`` — the dataset exists but fails fail-closed
  validation (mixed identity, clock skew, quarantined lines, no quotes);
- otherwise the campaign's own verdict (``PAPER_CANDIDATE`` at best,
  ``REJECTED``, ``NOT_RUN_INSUFFICIENT_REAL_DATA``).

Nothing here places orders. A leaderboard rank is never an authorization.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from quant_trade.evidence.canonical_json import atomic_write_json


@dataclass
class TradingOpportunityRow:
    hypothesis_id: str
    name: str
    status: str
    registered_in: str = ""
    dataset_paths: list[str] = field(default_factory=list)
    data_source: str = ""
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    per_snapshot_go_fraction: float | None = None
    walk_forward_windows: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TradingScanResult:
    evaluated_at_utc: str
    rows: list[TradingOpportunityRow]
    counts_by_status: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact": "TRADING_OPPORTUNITY_LEADERBOARD",
            "schema_version": 1,
            "evaluated_at_utc": self.evaluated_at_utc,
            "rows": [r.to_dict() for r in self.rows],
            "counts_by_status": self.counts_by_status,
            "real_money_authorized": False,
            "notes": [
                "hypotheses were pre-registered before any campaign ran",
                "PAPER_CANDIDATE is the maximum status; nothing here places orders",
                "NOT_RUN rows stay on the board — absence of evidence is visible",
            ],
        }


def _last_backfill_evidence(attempts_log: Path) -> str | None:
    """Quote the most recent recorded backfill attempt as NOT_RUN evidence."""
    if not attempts_log.exists():
        return None
    lines = [ln for ln in attempts_log.read_text(encoding="utf-8").splitlines() if ln]
    if not lines:
        return None
    try:
        last = json.loads(lines[-1])
    except json.JSONDecodeError:
        return None
    status = last.get("status", "")
    error = last.get("error", "")
    if status and error:
        return f"last backfill attempt: {status} ({error})"
    return None


def load_trading_scan_config(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not payload.get("hypotheses"):
        raise ValueError("trading scan config needs a non-empty 'hypotheses' list")
    return payload


def scan_trading_opportunities(
    config: dict[str, Any], *, evaluated_at_utc: str, config_dir: Path | None = None
) -> TradingScanResult:
    """Run every registered hypothesis whose dataset exists; report the rest."""
    from quant_trade.carry.research import run_carry_research

    root = config_dir or Path(".")

    def resolve(p: str) -> Path:
        candidate = Path(p)
        return candidate if candidate.is_absolute() else root / candidate

    rows: list[TradingOpportunityRow] = []
    for hyp in config["hypotheses"]:
        campaign = hyp.get("campaign")
        if campaign is None and hyp.get("campaign_config"):
            campaign = yaml.safe_load(
                resolve(str(hyp["campaign_config"])).read_text(encoding="utf-8")
            )
        if not isinstance(campaign, dict):
            raise ValueError(
                f"hypothesis {hyp.get('id')!r} needs an inline 'campaign' mapping "
                "or a 'campaign_config' path"
            )
        row = TradingOpportunityRow(
            hypothesis_id=str(hyp.get("id", "?")),
            name=str(hyp.get("name", "")),
            status="",
            registered_in=str(hyp.get("registered_in", "")),
        )

        required = [str(p) for p in hyp.get("requires_datasets", [])]
        data_path = campaign.get("data", {}).get("path")
        if data_path:
            required.append(str(data_path))
        row.dataset_paths = required
        missing = [p for p in required if not resolve(p).exists()]
        if missing:
            row.status = "NOT_RUN_NO_DATASET"
            row.reasons = [f"registered dataset missing: {p}" for p in missing]
            for p in missing:
                evidence = _last_backfill_evidence(
                    resolve(p).parent / "backfill_attempts.jsonl"
                )
                if evidence:
                    row.reasons.append(evidence)
                    break
            rows.append(row)
            continue

        # datasets referenced relative to the scan config must stay resolvable
        run_cfg = dict(campaign)
        if data_path:
            run_cfg["data"] = dict(campaign["data"], path=str(resolve(str(data_path))))
        try:
            result = run_carry_research(run_cfg)
        except ValueError as exc:
            row.status = "NOT_RUN_DATASET_REJECTED"
            row.reasons = [str(exc)]
            rows.append(row)
            continue

        row.status = result.decision
        row.data_source = result.data_source
        row.reasons = list(result.reasons)
        row.metrics = {
            "total_return": result.metrics.get("total_return"),
            "sharpe_per_period": result.metrics.get("sharpe_per_period"),
            "active_intervals": result.metrics.get("active_intervals"),
        }
        row.per_snapshot_go_fraction = result.per_snapshot_go_fraction
        row.walk_forward_windows = len(result.walk_forward)
        rows.append(row)

    # leaderboard order: candidates first (by per-period sharpe), NOT_RUN last
    def sort_key(r: TradingOpportunityRow) -> tuple[int, float]:
        if r.status == "PAPER_CANDIDATE":
            tier = 0
        elif r.status == "RESEARCH_CANDIDATE":
            tier = 1
        elif r.status.startswith("NOT_RUN"):
            tier = 3
        else:
            tier = 2
        sharpe = float(r.metrics.get("sharpe_per_period") or 0.0)
        return (tier, -sharpe)

    rows.sort(key=sort_key)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r.status] = counts.get(r.status, 0) + 1
    return TradingScanResult(
        evaluated_at_utc=evaluated_at_utc,
        rows=rows,
        counts_by_status=dict(sorted(counts.items())),
    )


def write_trading_leaderboard(path: str | Path, result: TradingScanResult) -> Path:
    return atomic_write_json(path, result.to_dict())
