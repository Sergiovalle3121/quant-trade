# Research Campaigns

Phase 14 adds an offline, research-only campaign runner for controlled batches across universes, strategies, parameters, costs, split policies, regimes, and stress assumptions.

Campaigns never submit orders, connect to brokers, approve live trading, or imply real-money readiness. Outputs are artifacts for human review.

## CLI

```bash
quant-trade campaigns plan --config configs/campaigns/daily_etf_research_campaign.yaml
quant-trade campaigns run --config configs/campaigns/daily_etf_research_campaign.yaml
quant-trade campaigns aggregate --campaign-dir outputs/campaigns/<campaign_id>/latest
quant-trade campaigns dashboard --campaign-dir outputs/campaigns/<campaign_id>/latest
```

Artifacts include generated configs, run index, run results, conservative ranking, rejected candidates, a Markdown summary, and an HTML dashboard.
