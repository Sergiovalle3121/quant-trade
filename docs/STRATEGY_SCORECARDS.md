# Strategy Scorecards

Strategy scorecards summarize evidence completeness across ten conservative categories: research quality, out-of-sample performance, robustness, stress resilience, paper-trial performance, operational reliability, execution quality, risk control, governance completeness, and human-review completeness.

Each category receives a score from 0 to 100, a status, evidence paths, notes, and blocking issues. Missing evidence is blocking. The overall score is weighted by `configs/evidence/scorecard_policy_conservative.yaml`.

`real_money_ready` is always `false`. A scorecard can never approve real-money trading.

```bash
quant-trade evidence scorecard --config configs/evidence/local_evidence_db.yaml --strategy-id <id>
quant-trade evidence lineage --config configs/evidence/local_evidence_db.yaml --strategy-id <id>
quant-trade evidence dashboard --config configs/evidence/local_evidence_db.yaml
```
