from __future__ import annotations

from pathlib import Path

from quant_trade.campaigns.models import CampaignConfig, RankedCandidate


def write_campaign_report(
    path: Path, config: CampaignConfig, ranked: list[RankedCandidate]
) -> None:
    accepted = [r for r in ranked if not r.rejected]
    lines = [
        f"# Campaign Summary: {config.campaign_name}",
        "",
        (
            "Research/backtesting only. No live trading, broker routing, "
            "or real-money approval is performed."
        ),
        "",
        f"Campaign ID: `{config.campaign_id}`",
        f"Mode: `{config.mode}`",
        f"Runs ranked: {len(ranked)}",
        f"Accepted after guardrails: {len(accepted)}",
        "",
        "## Top candidates",
        "",
    ]
    for candidate in accepted[:10]:
        penalty = (
            candidate.overfitting_penalty + candidate.turnover_penalty + candidate.drawdown_penalty
        )
        lines.append(
            f"- `{candidate.run_id}` `{candidate.strategy}` "
            f"composite={candidate.composite_score:.4f} "
            f"oos={candidate.oos_score:.4f} penalties={penalty:.4f}"
        )
    if not accepted:
        lines.append("- None; all candidates were rejected by conservative guardrails.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
