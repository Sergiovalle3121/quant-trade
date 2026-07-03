# Broker Integrations

Phase 6 implements Alpaca Paper first because it has a small HTTPS paper API and can be hard-blocked to `https://paper-api.alpaca.markets`. Live trading is not implemented. Paper fills differ from real markets and are not evidence of real-money performance.

IBKR is deferred because it requires TWS/IB Gateway setup, operational supervision, and separate paper validation. The repository contains only a non-network IBKR stub in this phase.

Before any real-money consideration: independent risk review, endpoint redesign, kill switch testing, cloud monitoring, approval workflow, and explicit human authorization are required.

## Phase 7 cloud paper deployment note

Scheduled cloud workflows are paper-only and fail closed. Defaults are dry-run; paper submission requires explicit config, official Alpaca Paper endpoint credentials from env or AWS Secrets Manager, kill switch clear, and reviewed operations. No live trading endpoints or real-money execution are supported.

## Phase 18 security hardening

Security, compliance-style, and audit-hardening checks are offline and paper-only. They must not introduce live trading, live broker endpoints, secrets, external scanning-service dependencies, or legal/financial claims. Security reports must keep `real_money_ready=false`.
