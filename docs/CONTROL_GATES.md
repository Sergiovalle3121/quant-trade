# Control Gates

The approval package defines human gates for research promotion, paper trial continuation, simulated allocation, broker paper submission, cloud paper enablement, kill-switch clearance, incident resolution, and archive deletion confirmation.

## Gate behavior

- `strategy_candidate_promotion`: requires evidence paths for research and risk review.
- `paper_trial_continue`, `paper_trial_pause`, `paper_trial_complete`: require local trial evidence.
- `simulated_allocation_approval`: applies only to simulated allocation.
- `broker_paper_order_submission`: requires explicit paper-only approval.
- `cloud_paper_submission_enablement`: remains dry-run/paper-only and local approval only.
- `kill_switch_clear`: requires reviewer notes.
- `incident_resolution`: requires incident evidence.
- `archive_delete_confirmation`: requires explicit delete confirmation and approval.

No gate grants real-money readiness.
