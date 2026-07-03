# Cloud Paper Trading Readiness

Future Phase 7 can run the paper workflow on a scheduled VM or container service connected to this GitHub repo. Secrets must live outside the repo in a secrets manager. CI should remain offline and never print secrets.

A production-like paper setup needs a scheduler, monitoring, alerts, health checks, dashboards, manual approval gates, a kill switch, append-only audit logs, backups, retention rules, and cost controls. This phase does not provision AWS resources and does not add Terraform.
