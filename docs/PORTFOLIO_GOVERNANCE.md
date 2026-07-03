# Portfolio Governance

Portfolio governance evaluates paper allocation candidates conservatively:

- Missing evidence rejects the candidate.
- Leverage, shorting, and real-money enablement are invalid policy settings.
- High pairwise correlation is flagged for review.
- Drawdown and loss-contribution metrics are reported for human review.
- Decision records always set `real_money_approved=false`.

Supported simulated decisions are `approve_simulated`, `reduce_allocation`, `pause_allocation`, `reject_allocation`, and `require_human_review`.
