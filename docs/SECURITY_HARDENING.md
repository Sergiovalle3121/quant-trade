# Security Hardening

Phase 18 adds offline security checks for this paper-only research platform. It is not legal advice, not investment advice, and does not indicate production or real-money readiness.

- Secret scanning is local and reports only redacted previews.
- Config checks reject live broker endpoints and real-money approvals.
- Reports always state `real_money_ready=false`.
- CI should not require network access or external scanning services.
