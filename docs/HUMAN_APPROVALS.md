# Human Approval Workflow

Phase 17 adds local, file-based approval records for paper-only governance. Approval records are JSONL artifacts under `outputs/approvals/<run_id>/` and never call an external service.

## Safety invariants

- Real-money approval cannot be requested or granted.
- `real_money_approved` is always `false`.
- Broker approval means paper-only review, not live endpoint readiness.
- Missing evidence blocks approval.
- Expired, rejected, or revoked approvals are invalid.
- Audit files redact fields whose names look like secrets, tokens, credentials, or passwords.

## CLI examples

```bash
quant-trade approvals request --type broker_paper_order_submission --title "Paper submit plan review" --evidence-path outputs/broker_plans/example --explicit-paper-only --config configs/approvals/approval_workflow_local.yaml
quant-trade approvals list --config configs/approvals/approval_workflow_local.yaml
quant-trade approvals show --approval-id appr_example --config configs/approvals/approval_workflow_local.yaml
quant-trade approvals approve --approval-id appr_example --reviewer Sergio --notes "Approved for Alpaca Paper only." --config configs/approvals/approval_workflow_local.yaml
quant-trade approvals reject --approval-id appr_example --reviewer Sergio --notes "Risk too high." --config configs/approvals/approval_workflow_local.yaml
quant-trade approvals verify --approval-id appr_example --config configs/approvals/approval_workflow_local.yaml
quant-trade approvals dashboard --config configs/approvals/approval_workflow_local.yaml
```

## Future integration hook

Future broker paper submission can call `require_approval(request_type, evidence_paths, policy)` to create a record, and `verify_approval(approval_id, request_type)` before continuing. Keep the broker path paper-only and mocked in tests.
